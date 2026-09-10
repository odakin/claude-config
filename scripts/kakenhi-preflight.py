#!/usr/bin/env python3
"""kakenhi-preflight.py — 科研費 研究計画調書の「機関事務が必ず突く点」を提出前に機械検出（様式骨格の生存 / 埋め込み指示の抽出 / 表記 lint / 経費明細の粒度・費目帰属、kakenhi-proposal.md#office-review-loop）

なぜ必要か
----------
調書を **様式 docx のまま書かず LaTeX 等で組み直す** と、様式に印字されていた見出し・
表ラベル・記述欄が「自分が打った文字列」に変わり、改訂のたびに **黙って消える**。
様式 docx を埋める運用なら `diff-form-docx.py` が LABEL_OVERWRITE / 見出し消失で捕まえるが、
組み直し運用ではその網が丸ごと外れる。実例 (2026-09): 「研究計画最終年度前年度応募」欄の
見出し 2 行と研究期間セルが消えた状態で提出し、機関事務に「元の様式にあった部分が消えている、
様式の改変は認められない」と差し戻された。**様式 docx にはその指示自体が印字されていた**
(「該当しない場合は記述欄を削除することなく、空欄のまま提出すること。」)。

同じ提出回の赤字 28 箇所を類型化すると、大半は **様式・記入要領に既に書いてあることの未適用**か、
**年に依らない定型チェック** (経費明細の粒度・費目帰属・表記) だった。本 script はその年非依存の
部分を機械化する。年ごとの中身 (must / must_not 語) は各年の staging gate が持てばよい。

検査
----
[FORM]  --form <様式.docx> [--pdf <調書.pdf>]
  🔴 SKELETON_LOST     様式が「削除することなく」等で明示保護した欄の label が PDF に無い
  🟠 SKELETON_MISSING  その他の pre-printed 見出し・表ラベルが PDF に無い
  ℹ️ INSTRUCTION       様式に埋め込まれた指示文の一覧 (category 別、1 つずつ適用を verify する)
[PDF]   --pdf <調書.pdf>
  🔴 ENTITY            HTML 実体参照の残置 (&#12316; 等)
  🟠 ABBREV            官公庁・機関名の略称 (文科省 → 文部科学省 等)
  🟠 BARE_NUMBER       裸の括弧数字 (「（160）」= 被引用数の単位落ち)
[CSV]   --keihi <経費明細.csv>   (cp932 / utf-8 どちらも可)
  🔴 KEIHI_FIELD_BYTES  「事項」が 72 バイト超 (一時保存で全画面が保存されない)
  🔴 KEIHI_WAVEDASH     波ダッシュ (確認用 PDF に実体参照が焼かれる)
  🟠 KEIHI_CATEGORY     費目帰属の誤り (サブスク・ライセンス・API・クラウド・業者委託 → その他 等)
  🟠 KEIHI_DOUBLE_COUNT 二重計上の疑い (「その他」の行に滞在費・旅費)
  🟠 KEIHI_SPEC_MISSING 設備備品費の「品名・仕様」に型番・仕様が無い
  🟠 KEIHI_TRAVEL_DETAIL 旅費の「事項」に場所・回数・日数・人数が無い
  🟠 KEIHI_MULTI_ITEM   1 行に異種の事項 (「論文投稿料、クラウド計算資源」等)

使い方
------
    kakenhi-preflight.py --form forms/s-13.docx --pdf build/chosho.pdf --keihi KEIHIMEISAI.csv
    kakenhi-preflight.py --keihi KEIHIMEISAI.csv          # 経費だけ
    kakenhi-preflight.py --form forms/s-74.docx           # 骨格 + 指示の一覧だけ (起草前に 1 回)
    # 種目が複数様式を持つとき (挑戦的研究 = 概要版 + 本文) は --form / --pdf を繰り返す。
    # 骨格と PDF text は和集合で突き合わせるので、片方だけ渡すと偽の SKELETON_MISSING が出る。
    kakenhi-preflight.py --form forms/s-42-1.docx --form forms/s-42-2.docx \
                         --pdf gaiyou.pdf --pdf honbun.pdf
    kakenhi-preflight.py --selftest

終了コード: 0 = 🔴 なし (🟠 は残っていてもよい) / 1 = 🔴 あり / 2 = 実行エラー。
🟠 は「事務が突く可能性が高い」であって誤検出もある — 潰すか、理由を書いて残すかを人が決める。

正本: claude-config/conventions/kakenhi-proposal.md
  #office-review-loop (指摘の類型) / #form-template-integrity (様式骨格) /
  #keihi-meisai-granularity (粒度) / #keihi-meisai-expense-category (費目帰属) /
  #keihi-meisai-field-limits (byte 上限) / #textfield-wavedash-entity (実体参照)
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

# ── 様式 docx から骨格を拾うための規則 ────────────────────────────────────────
# 「この欄を消すな」と様式自身が書いている印。ここに掛かる見出しは 🔴 扱いにする。
PROTECTED_MARKERS = ("削除することなく", "削除しないこと", "動かさないこと", "削除せず")
# 様式の注意書きテキストボックス (作成時に消す前提のもの) は骨格ではない。
DROP_MARKERS = ("このテキストボックスごと削除", "本留意事項の内容を十分に確認")
# 番号付き大見出し: 「２　応募者の研究遂行能力及び研究環境」「４ 研究計画最終年度前年度応募…」
HEADING_RE = re.compile(r"^[0-9０-９]{1,2}[\s　]+\S")

# 埋め込み指示の分類 (scan-form-instructions.py の docx 版。keyword → category)
INSTRUCTION_PATTERNS = [
    ("削除することなく", "欄の保持", "記述欄・見出しを消さない (該当なしでも空欄で残す)"),
    ("削除しないこと", "欄の保持", "空白頁が生じても削除しない"),
    ("動かさないこと", "欄の保持", "各頁上部のタイトル・指示書きを動かさない"),
    ("頁以内", "分量", "指定頁数を超えない (下限側は #office-review-loop の 7 割)"),
    ("超えない", "分量", "指定の上限を超えない"),
    ("字以内", "分量", "字数上限 (Web 欄は byte 換算に注意)"),
    ("ポイント以上", "書式", "本文の最小文字サイズ"),
    ("下線", "書式", "指定された下線 (本人・代表者・分担者) を全 entry に機械付与"),
    ("掲載が確定しているものに限", "業績", "未掲載を業績として並べない (引用文献として掲載状態ラベルを付ける)"),
    ("同定するに十分な情報", "業績", "誌名・巻号・頁・発表年まで書く (arXiv 番号だけにしない)"),
    ("具体的かつ明確に記述", "内容", "指示された小項目 (1)(2)… を漏れなく立てる"),
    ("役割を記述", "内容", "研究代表者・研究分担者の具体的な役割を書く"),
    ("その旨記述", "内容", "該当しない場合も「該当しない」と書く (無言で空けない)"),
    ("参考にすること", "内容", "参照先の規程・要領に literal 正対させる"),
]

# ── 表記 lint ────────────────────────────────────────────────────────────────
# 官公庁・機関の略称。調書は正式名称で書く (2026-09 に「文科省」を全件赤字指摘)。
ABBREV_MAP = {
    "文科省": "文部科学省",
    "厚労省": "厚生労働省",
    "経産省": "経済産業省",
    "農水省": "農林水産省",
    "国交省": "国土交通省",
    "学振": "日本学術振興会",
    "振興会": None,  # 文脈依存 — 報告のみ
}
ENTITY_RE = re.compile(r"&#\d+;|&[a-zA-Z]{2,8};")
# 「（160）」型の裸の数字 = 単位・意味が落ちた数 (2026-09 に被引用数を「(160)」と書いて赤字)。
BARE_NUMBER_RE = re.compile(r"[（(](\d{2,4})[）)]")

# ── 経費明細 lint ────────────────────────────────────────────────────────────
CAT_NAMES = {"A": "設備備品費", "B": "消耗品費", "C": "国内旅費", "D": "外国旅費",
             "E": "人件費・謝金", "F": "その他"}
# keyword → 載せるべき費目。事務が「行を分けて」「その他に」と赤字にする定番。
CATEGORY_RULES = [
    (re.compile(r"サブスクリプション|ライセンス|API利用|API 利用|クラウド|使用料|利用料|保守|レンタル|リース"), "F",
     "サブスクリプション等の利用料・保守は「その他」"),
    (re.compile(r"業者委託|委託|校閲|校正|英文校閲"), "F", "業者委託 (英文校閲等) は「その他」"),
    (re.compile(r"謝金|RA|アルバイト|人件費|研究員|補助者"), "E", "謝金・人件費は「人件費・謝金」"),
    (re.compile(r"投稿料|掲載料|出版"), "F", "論文投稿料・掲載料は「その他」"),
    (re.compile(r"専門書|文献|図書|消耗品|文具"), "B", "書籍・消耗品は「消耗品費」"),
]
# 「その他」に旅費相当が紛れる = 旅費との二重計上 (2026-09 に「滞在費は外国旅費に含まれるため削除」)
DOUBLE_COUNT_RE = re.compile(r"滞在費|宿泊費|渡航費|航空券|交通費|旅費")
# 旅費の事項に必要な粒度
TRAVEL_DETAIL_RE = re.compile(r"\d+\s*回|\d+\s*泊|\d+\s*日間|\d+\s*名|年\d+|各\d+")
# 設備の品名・仕様に型番・仕様が入っている印
SPEC_RE = re.compile(r"[A-Za-z0-9]|相当|メモリ|GB|TB|コア")
WAVEDASH_RE = re.compile(r"[〜～]")
# 1 行に異種を詰めた印: 読点で並んだ両側が別々の CATEGORY_RULES に当たる
SPLIT_RE = re.compile(r"[、,・]")


def die(msg: str) -> "NoReturn":          # noqa: F821 — docstring の終了コード契約 (2 = 実行エラー)
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(2)


def nfkc(s: str) -> str:
    """比較用の正規化: NFKC + 空白全除去 (全角/半角・和欧間空白の揺れを吸収)。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def nbytes(s: str) -> int:
    """電子申請システムの byte 換算 (全角 2 / 半角 1)。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


# ── docx 読み取り ────────────────────────────────────────────────────────────
_WT = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
_WP = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.S)
_WTC = re.compile(r"<w:tc(?:\s[^>]*)?>.*?</w:tc>", re.S)
_TXBX = re.compile(r"<w:txbxContent>.*?</w:txbxContent>", re.S)


def _runs(xml: str) -> str:
    return "".join(m.group(1) for m in _WT.finditer(xml))


def read_form(path: Path) -> dict:
    """様式 docx から (骨格候補, 保護欄, 指示文) を取り出す。

    骨格候補 = ① 番号付き大見出し ② 表のヘッダセル (短い label)。
    注意書きテキストボックス (作成時に削除する前提) は骨格から除く。

    「削除することなく」等の保護マーカーは、**それが書かれた見出しの配下** (= 文書順で
    次の見出しが来るまで) に効く。マーカーと見出しは別ノードなので、文書順に走査して
    欄 scope で紐付ける (同一ノードの文字列一致で判定すると 2026-09 の実例を取り逃す)。
    """
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    except FileNotFoundError:
        die(f"様式が見つからない: {path}")
    except (zipfile.BadZipFile, KeyError):
        die(f"docx として読めない (.doc 形式 / 破損 / 別 file?): {path}")
    body = _TXBX.sub("", xml)          # 骨格判定からテキストボックスを外す
    all_text = _runs(xml)              # 指示文の抽出はテキストボックスも含めて拾う

    # 文書順のノード列 (段落 / 表セル) を作る
    nodes = []
    for m in re.finditer(r"<w:p(?:\s[^>]*)?>.*?</w:p>|<w:tc(?:\s[^>]*)?>.*?</w:tc>", body, re.S):
        kind = "cell" if m.group(0).startswith("<w:tc") else "para"
        t = _runs(m.group(0)).strip()
        if t and not any(d in t for d in DROP_MARKERS):
            nodes.append((kind, t))

    headings, cells, protected_labels = [], [], set()
    section = None                      # 直近の見出し
    section_labels: list[str] = []       # その見出し配下の骨格 label
    guarded = False                      # その見出し配下に保護マーカーが出たか

    def flush():
        if section and guarded:
            protected_labels.add(section)
            protected_labels.update(section_labels)

    for kind, t in nodes:
        if kind == "para" and HEADING_RE.match(t):
            flush()
            section, section_labels, guarded = t, [], False
            headings.append(t)
            continue
        if any(k in t for k in PROTECTED_MARKERS):
            guarded = True
        # 表ヘッダ = 短いラベル。長文セル (記述欄の指示書き) は骨格に数えない。
        if kind == "cell" and len(t) <= 24:
            cells.append(t)
            section_labels.append(t)
    flush()

    instructions = []
    for sent in re.split(r"(?<=。)", all_text):
        sent = sent.strip()
        if not sent:
            continue
        for kw, cat, hint in INSTRUCTION_PATTERNS:
            if kw in sent:
                instructions.append((cat, hint, sent[:120]))
                break
    return dict(headings=headings, cells=cells, protected=sorted(protected_labels),
                instructions=instructions)


def read_pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("⚠️  PyMuPDF 未導入のため PDF 検査を skip (pip install pymupdf)", file=sys.stderr)
        return ""
    if not path.exists():
        die(f"PDF が見つからない: {path}")
    try:
        doc = fitz.open(path)
    except Exception as e:                      # noqa: BLE001 — fitz は多様な例外を投げる
        die(f"PDF として読めない: {path} ({e})")
    return "".join(page.get_text() for page in doc)


# ── 検査本体 ─────────────────────────────────────────────────────────────────
def check_form_skeleton(form: dict, pdf_text: str) -> list[tuple]:
    """様式に印字されていた見出し・ラベルが、組み直した PDF に生き残っているか。

    様式が「削除することなく」等で明示保護した欄 (= `protected`) の消失は 🔴。
    それ以外の見出し・表ラベルの消失は 🟠 (意図的に持たない様式構成もあるため)。
    """
    out = []
    if not pdf_text:
        return out
    hay = nfkc(pdf_text)
    protected = {nfkc(p) for p in form["protected"]}

    def missing(label: str) -> bool:
        n = nfkc(label)
        return len(n) >= 4 and n not in hay

    seen = set()
    for label in form["headings"] + form["cells"]:
        if label in seen:
            continue
        seen.add(label)
        if not missing(label):
            continue
        if nfkc(label) in protected:
            out.append(("🔴", "SKELETON_LOST",
                        f"様式が削除を禁じた欄が PDF に無い: 「{label[:60]}」"))
        else:
            out.append(("🟠", "SKELETON_MISSING",
                        f"様式の見出し・ラベルが PDF に無い: 「{label[:60]}」"))
    return out


def check_pdf_text(pdf_text: str) -> list[tuple]:
    out = []
    if not pdf_text:
        return out
    flat = nfkc(pdf_text)
    for m in ENTITY_RE.finditer(pdf_text):
        out.append(("🔴", "ENTITY", f"HTML 実体参照の残置: {m.group(0)}"))
    for ab, full in ABBREV_MAP.items():
        if ab in flat:
            hint = f" → 「{full}」" if full else " (文脈確認)"
            out.append(("🟠", "ABBREV", f"略称「{ab}」が本文にある{hint}"))
    for m in BARE_NUMBER_RE.finditer(pdf_text):
        n = int(m.group(1))
        if 1900 <= n <= 2100 or len(m.group(1)) < 3:
            continue          # 年号・2 桁は対象外
        if _is_symbol_label(pdf_text, m.start()):
            continue          # 粒子名の質量ラベル Δ(1232) / N(1440) / f(500) 等
        out.append(("🟠", "BARE_NUMBER", f"裸の括弧数字「{m.group(0)}」= 何の数か書く (例: 被引用 {n})"))
    return out


def _is_symbol_label(text: str, idx: int) -> bool:
    """括弧の直前が「記号」なら、中の数はラベル (粒子の質量等) であって裸の数ではない。

    物理の調書では Δ(1232) / N(1440) / f(500) が必ず出るので、CJK・かな以外の
    文字 (ラテン・ギリシャ・数学記号 ∆ U+2206 等) が直前に来る場合は対象外にする。
    """
    j = idx - 1
    while j >= 0 and text[j] in " \u3000":
        j -= 1
    if j < 0:
        return False
    c = text[j]
    if "\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff":
        return False          # かな・漢字の直後は日本語の丸括弧 = 対象
    return c.isalpha() or unicodedata.category(c).startswith("S")


def _decode_csv(path: Path) -> str:
    if not path.exists():
        die(f"経費明細 CSV が見つからない: {path}")
    raw = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    die(f"CSV のエンコーディングを判定できない: {path}")


def check_keihi(path: Path) -> list[tuple]:
    """経費明細 CSV の粒度・費目帰属・byte 上限。

    列は電子申請システムの取込フォーマット:
      費目区分 / 年度 / 品名・仕様 / 設置機関 / 事項 / 数量 / 単価 / 金額
    """
    out = []
    rows = list(csv.reader(io.StringIO(_decode_csv(path))))
    if not rows:
        return [("🔴", "KEIHI_EMPTY", f"{path.name}: 行が無い")]
    body = rows[1:] if rows[0] and "費目" in rows[0][0] else rows
    if not any(len(r) >= 8 and r[0].strip() for r in body):
        return [("🔴", "KEIHI_SCHEMA",
                 f"{path.name}: 取込フォーマット (8 列: 費目区分/年度/品名・仕様/設置機関/"
                 f"事項/数量/単価/金額) の行が 1 つも無い — 別 file か、列がずれている")]
    for i, r in enumerate(body, start=1):
        if len(r) < 8 or not r[0].strip():
            continue
        cat, fy, spec, _inst, item = r[0].strip(), r[1].strip(), r[2].strip(), r[3].strip(), r[4].strip()
        where = f"{path.name} {fy} {CAT_NAMES.get(cat, cat)} 行{i}"
        text = spec or item

        if item and nbytes(item) > 72:
            out.append(("🔴", "KEIHI_FIELD_BYTES",
                        f"{where}: 事項 {nbytes(item)} バイト > 72 「{item}」"))
        if WAVEDASH_RE.search(text):
            out.append(("🔴", "KEIHI_WAVEDASH", f"{where}: 波ダッシュ 「{text}」"))

        if cat == "A":
            if not spec:
                out.append(("🟠", "KEIHI_SPEC_MISSING", f"{where}: 設備備品費に品名・仕様が無い"))
            elif not SPEC_RE.search(spec):
                out.append(("🟠", "KEIHI_SPEC_MISSING",
                            f"{where}: 品名・型番まで書く 「{spec}」 (例: 「〜用計算機・〈製品名/メモリ〉相当」)"))
        if cat in ("C", "D") and item and not TRAVEL_DETAIL_RE.search(item):
            out.append(("🟠", "KEIHI_TRAVEL_DETAIL",
                        f"{where}: 旅費の事項に場所・回数・日数・人数が無い 「{item}」"))
        if cat == "F" and item and DOUBLE_COUNT_RE.search(item):
            out.append(("🟠", "KEIHI_DOUBLE_COUNT",
                        f"{where}: 「その他」に旅費相当 「{item}」 (旅費との二重計上)"))
        if item:
            for rx, want, why in CATEGORY_RULES:
                if rx.search(item) and cat != want:
                    if want == "F" and cat == "D" and DOUBLE_COUNT_RE.search(item):
                        continue  # 招聘旅費に含まれる渡航・滞在費は D で正しい
                    out.append(("🟠", "KEIHI_CATEGORY",
                                f"{where}: {why} — 現在は「{CAT_NAMES.get(cat, cat)}」 「{item}」"))
                    break
            parts = [p for p in SPLIT_RE.split(item) if p.strip()]
            if len(parts) >= 2:
                hits = {want for p in parts for rx, want, _ in CATEGORY_RULES if rx.search(p)}
                if len(hits) >= 2:
                    out.append(("🟠", "KEIHI_MULTI_ITEM",
                                f"{where}: 1 行に異種の事項 「{item}」 (行を分ける)"))
    return out


# ── 出力 ─────────────────────────────────────────────────────────────────────
def report(findings: list[tuple], instructions: list[tuple] | None) -> int:
    if instructions:
        print("── 様式に埋め込まれた指示 (1 つずつ適用を verify する) " + "─" * 20)
        seen = set()
        for cat, hint, sent in instructions:
            key = (cat, hint)
            if key in seen:
                continue
            seen.add(key)
            print(f"  ℹ️ [{cat}] {hint}")
            print(f"     └ 様式: {sent}")
        print()
    if not findings:
        print("✅ 検出なし")
        return 0
    hard = [f for f in findings if f[0] == "🔴"]
    print("── 検出 " + "─" * 52)
    for sev, code, msg in sorted(findings, key=lambda f: (f[0] != "🔴", f[1])):
        print(f"  {sev} {code}: {msg}")
    print(f"\n🔴 {len(hard)} 件 / 🟠 {len(findings) - len(hard)} 件")
    print("🟠 は誤検出もある — 潰すか、理由を書いて残すかを人が決める "
          "(正本: kakenhi-proposal.md#office-review-loop)")
    return 1 if hard else 0


# ── selftest (2026-09 の差し戻し実例を before/after で回帰させる) ─────────────
def selftest() -> int:
    import tempfile

    ok = True

    def expect(name, got_codes, want, forbid=()):
        nonlocal ok
        miss = [w for w in want if w not in got_codes]
        extra = [f for f in forbid if f in got_codes]
        if miss or extra:
            ok = False
            print(f"  ✗ {name}: 欠 {miss} / 余 {extra} (got {sorted(set(got_codes))})")
        else:
            print(f"  ✓ {name}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # --- 経費明細: 差し戻し前 (赤字を受けた形) ---
        before = td / "before.csv"
        before.write_text(
            "費目区分,年度,品名・仕様,設置機関,事項,数量,単価,金額\n"
            "A,2027,数値計算用計算機,東京都内,,1,1000,1000\n"
            "B,2027,,,数式処理ソフトウェアライセンス,,,60\n"
            "C,2027,,,国内研究会での成果発表,,,250\n"
            "E,2027,,,英文校閲・RA謝金,,,70\n"
            "F,2027,,,研究会開催費（会場費・招聘者滞在費）,,,150\n"
            "F,2027,,,論文投稿・掲載料、クラウド計算資源利用料,,,100\n"
            "C,2027,,,国際共同研究の相互訪問に伴う研究打合せおよび成果発表のための出張旅費（年2回、各3泊4日、1名）,,,200\n",
            encoding="utf-8")
        codes = [c for _, c, _ in check_keihi(before)]
        expect("経費 before: 品名・型番なし", codes, ["KEIHI_SPEC_MISSING"])
        expect("経費 before: ライセンスが消耗品費", codes, ["KEIHI_CATEGORY"])
        expect("経費 before: 旅費に日数・人数なし", codes, ["KEIHI_TRAVEL_DETAIL"])
        expect("経費 before: その他に滞在費 (二重計上)", codes, ["KEIHI_DOUBLE_COUNT"])
        expect("経費 before: 1 行に異種", codes, ["KEIHI_MULTI_ITEM"])
        expect("経費 before: 事項 72 バイト超", codes, ["KEIHI_FIELD_BYTES"])

        # --- 経費明細: 差し戻し後 (修正した形) ---
        after = td / "after.csv"
        after.write_text(
            "費目区分,年度,品名・仕様,設置機関,事項,数量,単価,金額\n"
            "A,2027,ワークステーション（数値計算用）・Xeon w5/メモリ128GB 相当,○○大学,,1,1000,1000\n"
            "B,2027,,,専門書・文献,,,45\n"
            "C,2027,,,国内研究会での成果発表（年3回、各2泊3日、1名）,,,250\n"
            "D,2027,,,海外研究者の招聘旅費（欧州から1名、7日間：航空券・滞在費）,,,200\n"
            "E,2027,,,数値計算補助のRA謝金（博士後期課程学生）,,,40\n"
            "F,2027,,,英文校閲（業者委託）,,,30\n"
            "F,2027,,,論文投稿料,,,30\n"
            "F,2027,,,クラウド計算資源利用料,,,40\n"
            "F,2027,,,研究会開催費（会場費）,,,150\n",
            encoding="utf-8")
        codes = [c for _, c, _ in check_keihi(after)]
        expect("経費 after: 全 clean", codes, [],
               forbid=["KEIHI_SPEC_MISSING", "KEIHI_CATEGORY", "KEIHI_TRAVEL_DETAIL",
                       "KEIHI_DOUBLE_COUNT", "KEIHI_MULTI_ITEM", "KEIHI_FIELD_BYTES"])

        # --- 表記 lint ---
        codes = [c for _, c, _ in check_pdf_text(
            "本研究は文科省の事業で……ヒッグス・インフレーション[12]（160）……令和９(2027)年度……")]
        expect("表記: 略称", codes, ["ABBREV"])
        expect("表記: 裸の括弧数字", codes, ["BARE_NUMBER"])
        codes = [c for _, c, _ in check_pdf_text("文部科学省の事業。被引用 160。(2027) 年度。")]
        expect("表記: 正しい形は clean", codes, [], forbid=["ABBREV", "BARE_NUMBER"])
        # 粒子名の質量ラベルは裸の数字ではない (物理の調書で必ず出る偽陽性)
        codes = [c for _, c, _ in check_pdf_text(
            "Δ(1232) 等のハドロン共鳴、N(1440)、∆(1232) も同様。")]
        expect("表記: 粒子名は偽陽性にしない", codes, [], forbid=["BARE_NUMBER"])
        codes = [c for _, c, _ in check_pdf_text("経費は 1&#12316;2 万円")]
        expect("表記: 実体参照", codes, ["ENTITY"])

        # --- 様式骨格: 欄が消えた PDF を検出できるか ---
        form = dict(
            headings=["４　研究計画最終年度前年度応募を行う場合の記述事項",
                      "２　応募者の研究遂行能力及び研究環境"],
            cells=["研究種目名", "課題番号", "研究期間"],
            protected=["４　研究計画最終年度前年度応募を行う場合の記述事項", "研究期間"],
            instructions=[])
        lost = check_form_skeleton(form, "２ 応募者の研究遂行能力及び研究環境\n本文……")
        expect("骨格: 保護欄の消失は 🔴", [c for _, c, _ in lost], ["SKELETON_LOST"])
        expect("骨格: 表ラベルの消失", [c for _, c, _ in lost], ["SKELETON_MISSING"])
        kept = check_form_skeleton(form, "４ 研究計画最終年度前年度応募を行う場合の記述事項\n"
                                         "２ 応募者の研究遂行能力及び研究環境\n"
                                         "研究種目名 課題番号 研究期間")
        expect("骨格: 全部あれば clean", [c for _, c, _ in kept], [],
               forbid=["SKELETON_LOST", "SKELETON_MISSING"])

    print("\n" + ("✅ selftest PASS" if ok else "❌ selftest FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--form", type=Path, action="append", default=[],
                    help="様式 docx (骨格・埋め込み指示の source)。種目が複数様式を持つなら繰り返す")
    ap.add_argument("--pdf", type=Path, action="append", default=[],
                    help="組み上がった調書 PDF。様式が複数なら対応する PDF を全部渡す")
    ap.add_argument("--keihi", type=Path, action="append", default=[], help="経費明細 CSV (複数可)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not (a.form or a.pdf or a.keihi):
        ap.print_help()
        return 2

    findings, instructions = [], None
    # 種目によって様式は複数ある (挑戦的研究の S-42-1 概要版 + S-42-2 本文 等)。
    # 骨格も PDF text も **和集合**で突き合わせる — 概要版の見出しを本文 PDF に探すと
    # 偽の SKELETON_MISSING が出るため、片側だけ渡す運用にしない。
    pdf_text = "\n".join(read_pdf_text(q) for q in a.pdf)
    if a.form:
        forms = [read_form(q) for q in a.form]
        merged = dict(headings=[h for f in forms for h in f["headings"]],
                      cells=[c for f in forms for c in f["cells"]],
                      protected=[p for f in forms for p in f["protected"]],
                      instructions=[i for f in forms for i in f["instructions"]])
        instructions = merged["instructions"]
        findings += check_form_skeleton(merged, pdf_text)
    findings += check_pdf_text(pdf_text)
    for c in a.keihi:
        findings += check_keihi(c)
    return report(findings, instructions)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
