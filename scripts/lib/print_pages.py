#!/usr/bin/env python3
"""print_pages.py — 刷る PDF の各頁が「窓口に出す頁」 かを、作る時に file へ宣言し、刷る直前に読む。宣言の無い頁は見出しから推定する。

なぜ要るか (規約 = conventions/office-automation.md#print-submission-pages-only):
    配布される様式の file は「窓口に出す頁」 と「出さない頁」 (様式付属の説明書き・記載例・マスタ / 選択肢の一覧・
    控え・白紙) の束であることが多い。生成の単位を様式の file にすると、後者が黙って紙に流れる。頁数の検査は
    「はみ出していない」 しか言わず、むしろ全頁を刷る前提を追認する (実測)。どの頁を出すかは file の外 (様式の
    記入 map) で決まり、刷る段では見えない。∴ 作る側が決めた頁の役割を**刷る file の中に書き込み**、刷る直前の
    gate が読む。宣言の無い file は見出しの語から推定し、複数頁なら宣言を求めて止める。

宣言 (record): PDF の Info 辞書の key ``PrintPages`` に JSON:
    {"v": 1, "src": "<誰が宣言したか>", "pages": [{"role": "submit", "label": "<頁の名前>"}, ...],
     "dropped": [{"from": 3, "role": "instructions", "label": "..."}],   # 任意 = 元の file から外した頁
     "include_flagged": "<理由>"}                                        # 任意 = 推定で疑わしい頁を理由つきで残した
    pages の長さ = file の頁数。 raster 化・頁の抜き出しで Info が落ちる経路は copy_record で引き継ぐ。

役割 (ROLES): submit = 窓口に出す (受付印を押して返される控えを含む) / keep = 手元の控え (PDF が控え = 刷らない) /
    instructions = 説明書き・注意事項・要領 / example = 記載例・見本 / master = マスタ・選択肢の一覧 / blank = 白紙。
    刷るのは submit だけ。

推定 (classify): 頁の上端 30% の行と大きい字の行を見る。
    strong = 記入例・記載例・見本・表示例 / 控 / 注意事項・留意事項・要領・手引・記入方法 / 白紙 (文字も線も画像も無い、
             画像だけで白い、「このページは空白」)。 宣言の無い 1 頁でも止める。
    weak   = 見出しが「…について」 / 罫線も画像も無い短い行の一覧 (マスタ)。 1 頁なら止めない、一覧に ⚠️ で出す。
    誤判定の害の向き: 止めすぎ = 宣言を 1 回足す手間 (--include-flagged で理由つきで残せる) / 見逃し = 紙の無駄
    (gate の無い状態と同じ)。 ∴ 疑わしきは一覧に出し、止めるのは strong と「宣言の無い複数頁」 だけ。

記入 map 側 (様式ごとの spec を持つ生成道具が使う): role_map_problems (頁の役割の宣言の矛盾) / anchor_misses (宣言した頁の
    目印が PDF のその頁に在るか = 雛形の改訂で頁がずれたら止める) / declare_submit (刷る file に「全頁 = 提出頁」 を書く。
    宣言の無い頁に strong の推定が当たれば書かずに止める理由を返す)。

    sys.path.insert(0, str(<claude-config>/"scripts"/"lib"))
    from print_pages import read_record, write_record, copy_record, classify, inventory, problems, parse_pages
    from print_pages import role_map_problems, anchor_misses, declare_submit

直接実行 = selftest。 --scan <PDF か dir ...> = 頁の推定を当てて疑わしい頁を出す (止める語を変える前の較正:
実際に出した物と出さない物の束に当てて誤検出を数える)。
"""
from __future__ import annotations

import json
import re
import unicodedata

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - 呼び出し側で SKIP / エラー表示
    fitz = None

KEY = "PrintPages"
VERSION = 1
ROLES = {
    "submit": "提出",
    "keep": "控え",
    "instructions": "説明書き",
    "example": "記載例",
    "master": "マスタ・一覧",
    "blank": "白紙",
}
PRINTED = {"submit"}

# 推定の語 (NFKC + 空白除去した行に当てる。 英語は空白を 1 つに潰した小文字の行)
_EXAMPLE_JA = re.compile(r"(記入例|記載例|記入見本|記載見本|作成例|表示例|入力例|見本(?!市)|サンプル|[（(【〔\[]例[）)】〕\]])")
_EXAMPLE_EN = re.compile(r"\b(sample|example|specimen)\b")
_KEEP_JA = re.compile(r"([（(【〔\[]控え?[）)】〕\]]|本人控|申請者控|提出者控|控用|^控え?$)")
_KEEP_EN = re.compile(r"\b(applicant'?s copy|copy for (the )?(applicant|your records))\b")
_INSTR_JA = re.compile(r"(注意事項|留意事項|要領|手引|記入方法|記入上の注意|記載上の注意|作成上の注意|募集要項|申請要項)")
_INSTR_EN = re.compile(r"^(instructions?|guidelines?|notes)\b|^how to (fill|complete|apply)\b")
_ABOUT_JA = re.compile(r"について$")
_BLANK_TEXT = re.compile(r"(このページは空白|このページは白紙|以下余白のページ|intentionally left blank)", re.I)
_SENTENCE = re.compile(r"(。|\.\s*\.\s*\.)")


def _need_fitz():
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required")


# ---------------------------------------------------------------- 宣言 (record)

def _info_xref(doc, create: bool) -> int | None:
    kind, val = doc.xref_get_key(-1, "Info")
    if kind != "xref":
        if not create:
            return None
        doc.set_metadata(doc.metadata or {})   # Info 辞書を作る (既存の metadata は保つ)
        kind, val = doc.xref_get_key(-1, "Info")
        if kind != "xref":
            raise RuntimeError("PDF の Info 辞書を作れない")
    return int(val.split()[0])


def read_record(doc) -> dict | None:
    """宣言を返す (無い・壊れている = None)。"""
    x = _info_xref(doc, create=False)
    if x is None:
        return None
    kind, val = doc.xref_get_key(x, KEY)
    if kind != "string":
        return None
    try:
        rec = json.loads(val)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and isinstance(rec.get("pages"), list) else None


def write_record(doc, pages: list, src: str, dropped: list | None = None, include_flagged: str | None = None,
                 fidelity: dict | None = None) -> dict:
    """開いている fitz.Document に宣言を書く (保存は呼び出し側)。 pages = [{"role", "label"}] を頁の順に、長さ = 頁数。
    fidelity = 様式の雛形との照合に要るもの {template, sha256, targets, drop, blank} (formcase の build が書き、 刷る直前の
    preflight が同じ照合を回す = conventions/form-case-pipeline.md#fidelity)。 raster 化・頁の抜き出しでも copy_record が引き継ぐ。"""
    _need_fitz()
    if len(pages) != doc.page_count:
        raise ValueError(f"宣言の頁数 {len(pages)} ≠ file の頁数 {doc.page_count}")
    bad = [p.get("role") for p in pages if p.get("role") not in ROLES]
    if bad:
        raise ValueError(f"役割 {bad} は {sorted(ROLES)} のどれでもない")
    rec = {"v": VERSION, "src": str(src),
           "pages": [{"role": p["role"], "label": str(p.get("label") or "")[:60]} for p in pages]}
    if dropped:
        rec["dropped"] = dropped
    if include_flagged:
        rec["include_flagged"] = str(include_flagged)
    if fidelity:
        rec["fidelity"] = fidelity
    doc.xref_set_key(_info_xref(doc, create=True), KEY, fitz.get_pdf_str(json.dumps(rec, ensure_ascii=False)))
    return rec


def copy_record(src_doc, dst_doc, page_indices=None) -> bool:
    """src の宣言を dst に写す (raster 化・頁の抜き出しで Info が落ちる経路用)。 page_indices = dst の頁が src の何頁目
    (0 始まり) か。 省略 = 同じ頁の並び。 写したら True。"""
    rec = read_record(src_doc)
    if rec is None:
        return False
    idx = list(range(len(rec["pages"]))) if page_indices is None else list(page_indices)
    if any(i >= len(rec["pages"]) for i in idx):
        return False
    write_record(dst_doc, [rec["pages"][i] for i in idx], rec.get("src", ""), rec.get("dropped"),
                 rec.get("include_flagged"), fidelity=rec.get("fidelity"))
    return True


# ---------------------------------------------------------------- 推定 (classify)

def _lines(page) -> list:
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            txt = "".join(sp["text"] for sp in ln["spans"]).strip()
            if txt:
                out.append((ln["bbox"][1], ln["bbox"][0], max(sp["size"] for sp in ln["spans"]), txt))
    out.sort()
    return out


def _ja(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def _en(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().lower()


def _heading(ls, h) -> str:
    """頁の名前 = 上端 30% の 4 字以上の行のうち、最初の 5 行で一番大きい字の行 (決裁欄の「承認」 等の短い語を避ける)。"""
    cand = [x for x in ls if x[0] < h * 0.30 and len(_ja(x[3])) >= 4][:5]
    if not cand:
        return _tidy(ls[0][3]) if ls else ""
    m = max(x[2] for x in cand)
    return _tidy(next(x for x in cand if x[2] >= m * 0.95)[3])


def _tidy(s: str) -> str:
    """表示用: 字間の空白 (「旅　費　請　求　書」) を詰め、 40 字で切る。"""
    return re.sub(r"(?<=[^\x00-\x7f])[\s\u3000]+(?=[^\x00-\x7f])", "", s.strip())[:40]


def _empty_raster(page) -> bool:
    """画像だけの頁が白紙か = 36 dpi で暗い画素 (< 160) が 2 個以下。 白紙の scan は 0、 短い 1 語だけの頁でも 10 を超える
    (実測) = 字の少ない頁を白紙と誤らない側に倒す。"""
    pix = page.get_pixmap(dpi=36, colorspace=fitz.csGRAY)
    return sum(1 for v in pix.samples if v < 160) <= 2


def classify(page) -> dict:
    """{"role": 推定の役割 or None, "strength": "strong" / "weak" / None, "why": 根拠, "heading": 見出し, "text": 文字の有無}。
    role None = 提出頁に見える (か、中身を読めない = text False)。"""
    _need_fitz()
    ls = _lines(page)
    res = {"role": None, "strength": None, "why": "", "heading": "", "text": bool(ls)}
    if not ls:
        if not page.get_images() and not page.get_drawings():
            res.update(role="blank", strength="strong", why="文字・線・画像のどれも無い")
        elif page.get_images() and _empty_raster(page):
            res.update(role="blank", strength="strong", why="画像だけで、白い")
        return res
    h = page.rect.height
    sizes = sorted(x[2] for x in ls)
    med = sizes[len(sizes) // 2]
    top = [x for x in ls if x[1] >= 0 and x[0] < h * 0.30][:6]
    big = [x for x in ls if x[2] >= med * 1.3][:6]
    res["heading"] = _heading(ls, h)
    if len(ls) <= 3 and any(_BLANK_TEXT.search(x[3]) for x in ls):
        res.update(role="blank", strength="strong", why=f"「{ls[0][3][:20]}」 だけの頁")
        return res
    cands = [(x[3], "上端") for x in top] + [(x[3], "大きい字") for x in big]
    for txt, where in cands:
        ja, en = _ja(txt), _en(txt)
        if len(ja) > 40:
            continue
        for role, pj, pe in (("example", _EXAMPLE_JA, _EXAMPLE_EN), ("keep", _KEEP_JA, _KEEP_EN),
                             ("instructions", _INSTR_JA, _INSTR_EN)):
            if pj.search(ja) or pe.search(en):
                res.update(role=role, strength="strong", why=f"{where}の「{txt[:30]}」")
                return res
    for txt, where in cands:
        if _ABOUT_JA.search(_ja(txt)) and len(_ja(txt)) <= 40:
            res.update(role="instructions", strength="weak", why=f"{where}の見出しが「…について」")
            return res
    if not page.get_drawings() and not page.get_images() and len(ls) >= 8:
        lens = sorted(len(_ja(x[3])) for x in ls)
        body = "".join(x[3] for x in ls)
        if lens[len(lens) // 2] <= 12 and not _SENTENCE.search(body):
            res.update(role="master", strength="weak", why=f"罫線も画像も無い短い行 {len(ls)} 本 (一覧・マスタ)")
    return res


def inventory(doc) -> list:
    """頁ごとに {"n", "heading", "declared": {"role", "label"} or None, "guess": classify の結果}。"""
    rec = read_record(doc)
    decl = rec["pages"] if rec and len(rec["pages"]) == doc.page_count else None
    out = []
    for i, p in enumerate(doc):
        g = classify(p)
        out.append({"n": i + 1, "declared": decl[i] if decl else None, "guess": g, "heading": g["heading"]})
    return out


def _label(item) -> str:
    g, d = item["guess"], item["declared"]
    name = (d or {}).get("label") or g["heading"] or ("(文字なし = raster)" if not g["text"] else "")
    return name[:40]


def describe(item) -> str:
    """一覧の 1 行。"""
    g, d = item["guess"], item["declared"]
    if d:
        mark = "✓" if d["role"] in PRINTED else "✗"
        s = f"p.{item['n']} {mark} {ROLES.get(d['role'], d['role'])} 「{_label(item)}」 (宣言)"
        if d["role"] in PRINTED and g["role"]:
            s += f" — 推定では {ROLES[g['role']]}? ({g['why']})"
        return s
    if g["role"]:
        mark = "✗" if g["strength"] == "strong" else "⚠️"
        return f"p.{item['n']} {mark} {ROLES[g['role']]}? 「{_label(item)}」 ({g['why']})"
    return f"p.{item['n']} ・ 「{_label(item)}」" + ("" if g["text"] else " (中身を読めない)")


def problems(doc) -> tuple:
    """(blocking, lines)。 blocking = 刷ってはいけない理由 (空 = 刷ってよい)、 lines = 頁の一覧 (describe)。

    宣言あり: 頁数が宣言と違う / submit でない頁がある → 止める。
    宣言なし: strong の推定がある頁 → 止める。 2 頁以上 → どれを出すかの宣言を求めて止める (weak の ⚠️ は一覧に)。"""
    _need_fitz()
    rec = read_record(doc)
    items = inventory(doc)
    lines = [describe(it) for it in items]
    blocking = []
    if rec is not None:
        if len(rec["pages"]) != doc.page_count:
            blocking.append(f"頁の宣言 ({len(rec['pages'])} 頁、 {rec.get('src', '?')}) と file の頁数 {doc.page_count} が違う"
                            " = 宣言の後に頁が足された / 抜かれた")
            return blocking, [describe(dict(it, declared=None)) for it in items]
        off = [it for it in items if it["declared"]["role"] not in PRINTED]
        if off:
            blocking.append("窓口に出さない頁が入っている: " + ", ".join(
                f"p.{it['n']} {ROLES.get(it['declared']['role'], it['declared']['role'])}" for it in off))
        return blocking, lines
    strong = [it for it in items if it["guess"]["strength"] == "strong"]
    if strong:
        blocking.append("窓口に出さない頁に見える: " + ", ".join(
            f"p.{it['n']} {ROLES[it['guess']['role']]}? ({it['guess']['why']})" for it in strong))
    if doc.page_count >= 2:
        blocking.append(f"{doc.page_count} 頁のうち、どれを窓口に出すかの宣言が無い")
    return blocking, lines


# ---------------------------------------------------------------- 記入 map (様式ごとの spec) の頁の役割

def norm_text(s: str) -> str:
    """照合用: NFKC + 空白を全部除く (Word / Excel の PDF は字間に空白や全角半角の揺れが入る)。"""
    return _ja(s or "")


def role_map_problems(roles: dict, groups: dict, n_pages: int | None = None, name: str = "") -> list:
    """頁の役割の宣言 (記入 map 側) の矛盾。 空 = 問題なし。

    roles  = {頁 (1 始まり): {"role", "anchor"?, ...}} / groups = {出力のまとまり: [頁, ...]} (= 1 本の刷る file)
    n_pages = 文書まるごとを 1 本の PDF にする経路 (Word 等) の総頁数。 渡すと全頁の役割を必須にする。
    - 役割は ROLES のどれか、 submit の頁は anchor (その頁に必ずある字) を持つ
    - まとまりの頁は submit だけ / submit の頁はどれかのまとまりに入る (= 出す頁を刷り忘れない)"""
    p = f"{name}: " if name else ""
    out = []
    roles = {int(k): (v if isinstance(v, dict) else {"role": v}) for k, v in (roles or {}).items()}
    if n_pages is not None and sorted(roles) != list(range(1, int(n_pages) + 1)):
        out.append(f"{p}頁の役割が 1〜{n_pages} 頁の全部に無い (在るのは {sorted(roles)})")
    if not roles:
        return out
    for k, r in roles.items():
        if r.get("role") not in ROLES:
            out.append(f"{p}頁 {k} の役割 {r.get('role')!r} は {list(ROLES)} のどれでもない")
        if r.get("role") == "submit" and not r.get("anchor"):
            out.append(f"{p}頁 {k} (submit) に anchor (その頁に必ずある字) が無い")
    grouped = set()
    for gid, pages in (groups or {}).items():
        for pg in pages or []:
            grouped.add(int(pg))
            r = roles.get(int(pg))
            if r is None:
                out.append(f"{p}まとまり {gid} の頁 {pg} に役割が無い")
            elif r.get("role") != "submit":
                out.append(f"{p}まとまり {gid} の頁 {pg} は {r.get('role')} (= 窓口に出さない頁) — まとまりから外す")
    for k, r in roles.items():
        if r.get("role") == "submit" and k not in grouped:
            out.append(f"{p}頁 {k} は submit なのにどのまとまりにも無い (= 刷られない)")
    return out


def anchor_misses(doc, roles: dict) -> list:
    """[(頁, anchor)] = 宣言の anchor が PDF のその頁に無いもの (= 雛形が改訂されて頁の中身がずれた)。"""
    bad = []
    for k, r in (roles or {}).items():
        r = r if isinstance(r, dict) else {"role": r}
        a, k = r.get("anchor"), int(k)
        if not a:
            continue
        if k > doc.page_count or norm_text(a) not in norm_text(doc[k - 1].get_text()):
            bad.append((k, a))
    return bad


def declare_submit(doc, labels: list, src: str, dropped: list | None = None) -> tuple:
    """doc (= 刷る file、 全頁が窓口に出す頁) に宣言を書く。 返り値 = (止める理由の list, 表示の行の list)。

    labels[i] = i 頁目の名前 (None = 見出しから)。 宣言の無い頁 (label が None) に strong の推定が当たれば止める
    (= 記入 map に役割を書くか、 まとまりから外すかを決めてから刷る)。 宣言した頁の推定は行に出すだけ。
    止める理由があれば書かない。 保存は呼び出し側。"""
    stop, lines, names = [], [], []
    for i, page in enumerate(doc):
        g = classify(page)
        declared = labels[i] if i < len(labels) else None
        names.append(declared or g["heading"])
        if declared is None and g["strength"] == "strong":
            stop.append(f"{i + 1} 頁は{ROLES[g['role']]}に見える ({g['why']})")
        elif g["role"]:
            lines.append(f"⚠️ {i + 1} 頁: {ROLES[g['role']]}? ({g['why']}) — "
                         + ("宣言では提出頁 (anchor 照合済み)" if declared else "窓口に出す頁か見る"))
    if not stop:
        write_record(doc, [{"role": "submit", "label": n} for n in names], src, dropped=dropped)
    return stop, lines


# ---------------------------------------------------------------- 頁の指定

def parse_pages(spec: str, n: int) -> list:
    """"all" / "1-2,4" → 1 始まりの頁番号の list (重複なし・順序を保つ)。 範囲外は ValueError。"""
    spec = (spec or "").strip().lower()
    if spec == "all":
        return list(range(1, n + 1))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"頁の指定 {part!r} が読めない (例: all / 1-2,4)")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b > n or a > b:
            raise ValueError(f"頁 {part} が範囲外 (1-{n})")
        for k in range(a, b + 1):
            if k not in out:
                out.append(k)
    if not out:
        raise ValueError("頁の指定が空")
    return out


def changed_pages(new_doc, old_doc, dpi: int = 100) -> list:
    """new の頁のうち old の同じ番号の頁と見た目が違うもの (1 始まり)。 old に無い頁は違う側。 刷り直しを変わった頁だけに
    するための比較 (同じ中身の描画は画素まで一致する。 差は 64 階調を超える画素が 3 個以上)。"""
    _need_fitz()
    out = []
    for i, p in enumerate(new_doc):
        if i >= old_doc.page_count:
            out.append(i + 1)
            continue
        q = old_doc[i]
        a = p.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        b = q.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        if (a.width, a.height) != (b.width, b.height):
            out.append(i + 1)
            continue
        sa, sb = a.samples, b.samples
        diff = 0
        for k in range(len(sa)):
            if abs(sa[k] - sb[k]) > 64:
                diff += 1
                if diff >= 3:
                    break
        if diff >= 3:
            out.append(i + 1)
    return out


# ---------------------------------------------------------------- selftest

def selftest() -> None:
    import os
    import tempfile

    _need_fitz()
    d = tempfile.mkdtemp()
    font = None
    for cand in ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"):
        if os.path.exists(cand):
            font = cand
            break

    def page(doc, lines, rules=True):
        p = doc.new_page()
        if font:
            p.insert_font(fontname="jp", fontfile=font)
        y = 60
        for i, t in enumerate(lines):
            p.insert_text((60, y), t, fontsize=16 if i == 0 else 10, fontname="jp" if font else "japan")
            y += 24
        if rules:
            for k in range(5):
                p.draw_line((50, 300 + 20 * k), (500, 300 + 20 * k))
        return p

    doc = fitz.open()
    page(doc, ["甲 申請書", "氏名", "所属"])                               # 提出頁
    page(doc, ["研究計画書", "テーマ"])                                          # 提出頁
    page(doc, ["本制度について", "1. 申請条件について", "支給の基準は…"])    # weak: …について
    page(doc, ["【表示例】", "This research was supported by …"])               # strong: 表示例
    doc.new_page()                                                              # strong: 白紙
    page(doc, ["（控）", "受付番号"])                                            # strong: 控
    page(doc, ["記入上の注意", "1. 黒のボールペンで"], rules=False)               # strong: 注意
    page(doc, ["所属", "学科", "教授", "准教授", "講師", "助教", "基盤研究", "萌芽", "若手"], rules=False)  # weak: マスタ
    g = [classify(p) for p in doc]
    assert g[0]["role"] is None and g[1]["role"] is None, g[:2]
    assert (g[2]["role"], g[2]["strength"]) == ("instructions", "weak"), g[2]
    assert (g[3]["role"], g[3]["strength"]) == ("example", "strong"), g[3]
    assert (g[4]["role"], g[4]["strength"]) == ("blank", "strong"), g[4]
    assert (g[5]["role"], g[5]["strength"]) == ("keep", "strong"), g[5]
    assert (g[6]["role"], g[6]["strength"]) == ("instructions", "strong"), g[6]
    assert (g[7]["role"], g[7]["strength"]) == ("master", "weak"), g[7]
    # 控除 (= 税の書類の題) は控えではない / 見本市は見本ではない
    t = fitz.open()
    page(t, ["扶養控除等申告書", "氏名"])
    page(t, ["見本市 出展申込書", "氏名"])
    assert classify(t[0])["role"] is None and classify(t[1])["role"] is None, [classify(p) for p in t]

    # 宣言なし: 複数頁 = 止める、 strong の頁は名指し
    blk, lines = problems(doc)
    assert any("宣言が無い" in b for b in blk) and any("p.4 記載例?" in b for b in blk), blk
    assert any(x.startswith("p.3 ⚠️ 説明書き?") for x in lines), lines
    # 宣言なし 1 頁: 提出頁 = 通る / weak だけ = 通る / strong = 止める
    one = fitz.open()
    one.insert_pdf(doc, from_page=0, to_page=0)
    assert problems(one)[0] == [], problems(one)
    weak1 = fitz.open()
    weak1.insert_pdf(doc, from_page=2, to_page=2)
    assert problems(weak1)[0] == [], problems(weak1)
    strong1 = fitz.open()
    strong1.insert_pdf(doc, from_page=3, to_page=3)
    assert problems(strong1)[0], problems(strong1)

    # 宣言あり: submit だけ = 通る / submit でない頁 = 止める / 頁数が違う = 止める
    two = fitz.open()
    two.insert_pdf(doc, from_page=0, to_page=1)
    write_record(two, [{"role": "submit", "label": "様式 1"}, {"role": "submit", "label": "研究計画書"}], "selftest",
                 dropped=[{"from": 3, "role": "instructions", "label": "説明書き"}])
    f2 = os.path.join(d, "two.pdf")
    two.save(f2, garbage=3, deflate=True)
    r = fitz.open(f2)
    assert read_record(r)["pages"][1]["label"] == "研究計画書", read_record(r)
    assert problems(r)[0] == [], problems(r)
    bad = fitz.open()
    bad.insert_pdf(doc, from_page=0, to_page=2)
    write_record(bad, [{"role": "submit"}, {"role": "submit"}, {"role": "instructions", "label": "説明書き"}], "selftest")
    assert any("出さない頁" in b for b in problems(bad)[0]), problems(bad)
    r.insert_pdf(doc, from_page=4, to_page=4)
    assert any("頁数" in b for b in problems(r)[0]), problems(r)
    try:
        write_record(fitz.open(f2), [{"role": "submit"}], "x")
        raise AssertionError("頁数の違う宣言を書けてしまった")
    except ValueError:
        pass
    # Info の他の値 (印の Keywords) を壊さない / raster 化で写せる
    two.set_metadata({"keywords": "paper-only:seal-image"})
    assert read_record(two) is not None and two.metadata["keywords"] == "paper-only:seal-image"
    ras = fitz.open()
    for p in two:
        np_ = ras.new_page(width=p.rect.width, height=p.rect.height)
        np_.insert_image(np_.rect, pixmap=p.get_pixmap(dpi=30))
    assert copy_record(two, ras) and problems(ras)[0] == [], problems(ras)
    sub = fitz.open()
    sub.insert_pdf(two, from_page=1, to_page=1)
    assert copy_record(two, sub, [1]) and read_record(sub)["pages"][0]["label"] == "研究計画書"
    # raster で宣言なしの複数頁 = 止める (中身を読めない)
    ras2 = fitz.open()
    for p in doc:
        if p.number < 2:
            np_ = ras2.new_page(width=p.rect.width, height=p.rect.height)
            np_.insert_image(np_.rect, pixmap=p.get_pixmap(dpi=30))
    blk, lines = problems(ras2)
    assert any("宣言が無い" in b for b in blk) and all("中身を読めない" in x for x in lines), (blk, lines)

    # 頁の指定
    assert parse_pages("all", 4) == [1, 2, 3, 4] and parse_pages("1-2,4,2", 4) == [1, 2, 4]
    for badspec in ("0", "5", "3-2", "x", ""):
        try:
            parse_pages(badspec, 4)
            raise AssertionError(badspec)
        except ValueError:
            pass
    # 変わった頁: 同じ = なし / 1 頁だけ字を変える = その頁 / 頁が増えた = 増えた頁
    old = fitz.open()
    page(old, ["申請書", "氏名 甲"])
    page(old, ["研究計画書", "テーマ"])
    new = fitz.open()
    page(new, ["申請書", "氏名 甲"])
    page(new, ["研究計画書", "テーマ 改"])
    page(new, ["追加", "頁"])
    assert changed_pages(old, old) == [] and changed_pages(new, old) == [2, 3], changed_pages(new, old)
    # 記入 map の頁の役割 / 頁の目印 / 刷る file への宣言
    roles = {1: {"role": "submit", "anchor": "甲 申請書"}, 2: {"role": "submit", "anchor": "計画書"},
             3: {"role": "instructions", "anchor": "本制度について"}}
    assert role_map_problems(roles, {"g": [1, 2]}, n_pages=3) == []
    for bad_roles, groups, n, word in ((roles, {"g": [1, 2, 3]}, 3, "外す"), (roles, {"g": [1]}, 3, "刷られない"),
                                       ({1: {"role": "submit", "anchor": "a"}}, {"g": [1]}, 3, "全部"),
                                       ({**roles, 3: {"role": "note"}}, {"g": [1, 2]}, 3, "どれでもない"),
                                       ({**roles, 2: {"role": "submit"}}, {"g": [1, 2]}, 3, "anchor")):
        probs = role_map_problems(bad_roles, groups, n_pages=n)
        assert any(word in x for x in probs), (word, probs)
    assert role_map_problems({}, {"g": [1]}) == []   # 総頁数を渡さない経路 (sheet を選んで組む) は宣言が無くてよい
    w = fitz.open()
    for t in ("甲 申請書", "研究 計画書", "本制度について"):
        page(w, [t])
    assert anchor_misses(w, roles) == [], anchor_misses(w, roles)
    assert anchor_misses(w, {**roles, 2: {"role": "submit", "anchor": "について"}}) == [(2, "について")]
    g2 = fitz.open()
    g2.insert_pdf(w, from_page=0, to_page=1)
    stop, lines = declare_submit(g2, ["様式", "計画書"], "selftest", dropped=[{"from": 3, "role": "instructions"}])
    assert not stop and read_record(g2)["pages"][1]["label"] == "計画書"
    ex = fitz.open()
    page(ex, ["旅費請求書"])
    page(ex, ["記入例"])
    stop, _ = declare_submit(ex, [None, None], "selftest")
    assert stop and read_record(ex) is None, stop   # 宣言の無い頁の strong = 止めて書かない
    print("print_pages selftest: PASS")


def scan(paths, strong_only: bool = False) -> dict:
    """PDF (file か dir、 dir は再帰) の頁を推定し、 疑わしい頁を 1 行ずつ出す。 返り値 = 集計。
    推定の較正用 = 止める語を足す・外す前に、 実際に出した物と出さない物の束に当てて誤検出を数える。"""
    import os
    from collections import Counter

    files = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                if "/.git" in root:
                    continue
                files += [os.path.join(root, n) for n in sorted(names) if n.lower().endswith(".pdf")]
        elif p.lower().endswith(".pdf"):
            files.append(p)
    count = Counter()
    for f in files:
        try:
            d = fitz.open(f)
        except Exception:  # noqa: BLE001 - 壊れた・暗号化の PDF は数えるだけ
            count["unreadable"] += 1
            continue
        if d.needs_pass or d.is_encrypted:
            count["unreadable"] += 1
            continue
        count["files"] += 1
        rec = read_record(d)
        for page in d:
            count["pages"] += 1
            g = classify(page)
            if not g["role"] or (strong_only and g["strength"] != "strong"):
                continue
            count[g["strength"]] += 1
            print(f"{g['strength']:6} {ROLES[g['role']]:6} p.{page.number + 1:<3} {f}  {g['why']}"
                  + ("  [宣言あり]" if rec else ""))
    print(f"-- files {count['files']} / pages {count['pages']} / strong {count['strong']} / weak {count['weak']}"
          f" / 読めない {count['unreadable']}")
    return dict(count)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="刷る頁の宣言と推定 (引数なし = selftest)")
    ap.add_argument("--scan", nargs="+", metavar="PATH", help="PDF / dir の頁を推定して疑わしい頁を出す (推定の較正用)")
    ap.add_argument("--strong-only", action="store_true", help="--scan で strong (止める側) だけ出す")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.scan:
        scan(a.scan, a.strong_only)
    else:
        selftest()
