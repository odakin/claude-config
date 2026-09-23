"""規則の書き写し lint — process doc に規則の本文 (とくに廃止した版) が手で書き写されていないか。

token は spec から導出する (人が一覧を書かない):
  - ``superseded``: 規則の廃止した版の言い回し。 process doc に出たら「古い規則の残骸」
  - ``markers``:    規則を定義する固有の言い回し (任意)。 home と view の外に出たら「書き写し」
  - 記号つきの固定値 (``○`` / ``☑`` で始まり 2 文字以上の fixed 値): 値の書き写し
  - ``claim``: 規則の ``claims:`` (about の語の近くに矛盾する数・否定) と、 cell の値の主張 (``<cell> = 『値』``) を spec と照合
照合は正規化 (``nrm``: 全角半角・空白・括弧・markdown・少数の送り仮名) の後。 token は助詞 (は/を/が)・連結 (・/と)・
数字の後の「日」 の違いを許す (``token_re``)。
  - ``statement``: 規則の形の文 (cell 番地・規則の語 × 値・否定) を規則の home の外に書いている行 (矛盾していなくても。
    process doc は規則 id か generated view だけを置く)
  - ``state``: 案件 README (``is_case_readme``) に案件の状態を手で書いている行 (未提出・提出予定・未印刷・印刷版・
    押印待ち・返事待ち・未決・「〜時点は」・〆の日付 等、 ``STATE_PATTERNS``)。 状態の正本は submission.yaml
    (README には ``formcase:view kind=status`` の生成表) と案件の TODO で、 README の写しは状態が進んでも残って古くなる
    (実測: 案件 README の過半に写しがあり、 2 か月前の「残 = 提出」 が残っていた)。 file 名 (backtick の中) は見ない
  - ``region``: 区間 marker (generated view / history) の入れ子・閉じ忘れ・宙に浮いた閉じ (``views.region_problems``)。
    区間は除外範囲そのものなので、 崩れると後ろの行が黙って lint から外れる / 戻る。 承認できない (全対象 doc)
除外: generated view の中 / ``<!-- formcase:history -->`` 区間 (経緯・理由) / 案件の値の出典表 / 理由つき承認一覧
(設定の ``lint.ack``)。 走査対象 = 設定の ``lint.targets`` (手順・入口・案件の doc)。 規則の理由・経緯の home
(spec の ``meta.history_home``) は superseded と statement だけ (= 経緯は history 区間で囲む)。
claims の網羅 = ``claims_coverage()`` (値・yes/no の規則に claims が無いと ``formcase.py lint`` が落ちる)。

⚠️ 射程: 宣言した語彙と形だけ (about に無い同義語・行をまたぐ主張・番地も規則の語も無い文は見えない。 一覧と、 それが紙を
変えない構造 (= gate が spec で workbook を裁く) = form-case-pipeline.md #lint-reach。 docs/convention-design-principles.md #proxy-blind-spot)。
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

from . import config as CF
from . import rules as R
from . import specs as S
from . import views as V

ALL_KINDS = ("superseded", "marker", "value")


def invalidate() -> None:
    """設定・spec が差し替わったら、 設定から組んだ正規表現を作り直す (config.configure / reset が呼ぶ)。"""
    _rule_ref_re.cache_clear()
    _value_shape_re.cache_clear()


def ack_path() -> Path | None:
    return CF.lint_ack()


def targets(root: Path | None = None) -> list:
    """[(path, kinds)]。 手順・入口・案件の doc は全 kind、 経緯の home は superseded だけ
    (= 経緯の home は理由の中で規則の値を語ってよいが、 廃止した版を**今の規則として**書くのは誤り。
    経緯として古い版を書く箇所は history 区間で囲む)。

    走査する doc の一覧は engine が持たない: 設定の ``lint.targets`` = [{glob, require_sibling?}]
    (glob は workspace_root からの相対、 ``require_sibling`` = 同じ dir にその file が在るものだけ)。"""
    root = Path(root).resolve() if root else CF.workspace_root()
    procs = []
    for rule in CF.lint_cfg().get("targets") or []:
        sib = rule.get("require_sibling")
        for p in sorted(root.glob(str(rule["glob"]))):
            if sib and not (p.parent / str(sib)).exists():
                continue
            if p.is_file() and p not in procs:
                procs.append(p)
    homes = homes_of_rules()
    out = [(p, ALL_KINDS + ("claim", "statement") + (("state",) if is_case_readme(p) else ()))
           for p in procs if p.resolve() not in homes]
    out += [(p, ("superseded", "statement")) for p in sorted(homes)]
    return out


def is_case_readme(p) -> bool:
    """案件の README か。 判定は設定の ``lint.case_readme`` = [{glob, name_re?, or_sibling?}] (config.match_rule)。"""
    return CF.match_rule(p, CF.lint_cfg().get("case_readme")) is not None


# 案件の状態を言う語 (README に手で書くと、 状態が進んでも写しが残る)。 file 名は backtick を外してから見る。
STATE_PATTERNS = [
    (re.compile(r"未提出|未印刷|未送付|未受領|未取得|未着手|まだ作っていない|作成しない"), "未〜"),
    (re.compile(r"(提出|送付|送信|印刷)予定|(提出|送付|送信)を.{0,12}約束"), "予定・約束"),
    (re.compile(r"(提出|送付|送信)済"), "済"),
    (re.compile(r"印刷版"), "印刷版"),
    (re.compile(r"(押印|返事|返答|回答|確認|承認|判断|素材)待ち|確認前|手配中"), "待ち"),
    (re.compile(r"未決"), "未決"),
    (re.compile(r"時点(?:は|で|、|\))"), "時点"),
    (re.compile(r"〆\s*\**\s*\d|deadline\s*\d|期限\s*\d{1,2}/\d{1,2}"), "期日"),
    (re.compile(r"^#{1,6}\s*(残|進捗|提出状況)|(^|\s)残\s*[=＝:：]"), "残"),
]
_CODE_SPAN = re.compile(r"`[^`]*`")


def state_hits(line: str) -> list:
    """案件の状態を手で書いている語 [(label, matched)]。 backtick の中 (file 名・command) と HTML comment 行は見ない。"""
    s = line.strip()
    if s.startswith("<!--"):
        return []
    s = _CODE_SPAN.sub("", s)
    out = []
    for rx, label in STATE_PATTERNS:
        m = rx.search(s)
        if m:
            out.append((label, m.group(0).strip()))
    return out


def homes_of_rules() -> set:
    """規則の理由・経緯の home。 spec の ``meta.history_home`` (spec file からの相対 path) から導出。"""
    return S.history_homes()


def tokens() -> list:
    """[(token, rule id, kind)]。"""
    out = []
    for rid, r in R.all_rules().items():
        if r.get("same_as"):
            continue                     # 借りた本文は借り元の規則として 1 回だけ数える
        for t in r.get("superseded") or []:
            out.append((t, rid, "superseded"))
        for t in r.get("markers") or []:
            out.append((t, rid, "marker"))
    for sid, spec in S.all_specs().items():
        for e in spec.get("cells") or []:
            v = e.get("value")
            if e.get("state") == "fixed" and isinstance(v, str) and len(v) >= 3 and v[0] in "○☑":
                rid = f"{sid}/{e['rule']}" if e.get("rule") else f"{sid}:{e['ref']}"
                out.append((v, rid, "value"))
    seen, uniq = set(), []
    for t in out:
        if (t[0], t[2]) not in seen:
            seen.add((t[0], t[2]))
            uniq.append(t)
    return uniq


def _norm(s: str) -> str:
    return re.sub(r"[\s　]+", " ", s.replace("`", "").replace("*", ""))


# ---------------------------------------------------------------------------
# 正規化と値の主張
# ---------------------------------------------------------------------------
# 表記の揺れ (全角/半角・空白・括弧・markdown・送り仮名の漢字/かな) を吸ってから照合する。 語彙を増やして
# 言い換えを追うのではなく、「同じ語の書き方の違い」 だけをここで潰す (= 表は短く保つ)。
_VARIANTS = (("無し", "なし"), ("有り", "あり"), ("但し", "ただし"), ("下さい", "ください"), ("出来る", "できる"),
             ("書き込ま", "書か"), ("記入しない", "書かない"), ("記入せず", "書かず"), ("丸1日", "1日"))
_DROP = set("「」『』\"'`*()（）[]［］【】〈〉《》<>")
_CONNECT = {"、": "・", "／": "・", "/": "・"}
_NUM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d])")
_NEG = ("書かない", "書かず", "不要", "省く", "省い", "省略", "入れない")   # 「のみ / だけ」 は範囲の限定であって否定でない (実 doc で誤検出)


def nrm(s: str) -> str:
    """照合用の正規化: NFKC → markdown・括弧・引用符・空白を除く → 連結記号を ・ に → 表記の揺れを 1 つに。"""
    import unicodedata

    t = unicodedata.normalize("NFKC", s)
    t = "".join("" if ch in _DROP or ch.isspace() else _CONNECT.get(ch, ch) for ch in t)
    for a, b in _VARIANTS:
        t = t.replace(a, b)
    return t


def token_re(token: str):
    """廃止版・定義文の token を、 助詞 (は/を/が) の違い・連結 (・/と) の違い・数字の後の「日」 の有無を許す正規表現に。"""
    t = nrm(token)
    out = []
    for i, ch in enumerate(t):
        prev = t[i - 1] if i else ""
        if ch in "はをが" and prev and not ("ぁ" <= prev <= "ん"):
            out.append("[はをが]?")
        elif ch == "・":
            out.append("[・と]?")
        else:
            out.append(re.escape(ch))
    pat = "".join(out)
    pat = re.sub(r"(\\?\d(?:\\\.\d+)?)日", r"\1日?", pat)
    return re.compile(pat)


def _claims_of_rules() -> list:
    """[(rule id, claim dict)]。 spec の規則の ``claims:`` (値を持つ規則が「これと矛盾する言い方」 を宣言する)。"""
    out = []
    for sid, spec in S.all_specs().items():
        entries = list(spec.get("cells") or []) + list((spec.get("nittei") or {}).get("rules") or []) \
            + list(spec.get("cross_checks") or [])
        for e in entries:
            rid = e.get("rule") or e.get("id")
            for c in e.get("claims") or []:
                out.append((f"{sid}/{rid}", c))
    return out


CLAIM_WINDOW = 12   # about の語の後ろ何文字 (正規化後) までを「その語についての主張」 とみなすか


CLAIM_KINDS = ("value", "negation", "forbid", "forbid_re", "affirm", "other_numbers")
# 否定の語が直後に来る token は「その値にしない」 と言っている = 矛盾の主張ではない (「学部名にしない」「空欄で出さない」)
_NEG_AFTER = re.compile(r"^.{0,6}?(?:ない|無い|なし|無し|せず|ず[、。・]|不要|禁止|NG|❌|×|でなく|ではなく|ません|誤り|違反)")
_NEG_BEFORE = re.compile(r"(?:❌|×|NG|旧|誤|非|脱)$")
_AFFIRM = ("書く", "書いて", "書き", "記入する", "記入して", "記入し", "入れる", "入れて", "埋める", "埋めて", "焼く", "焼いて",
           "焼き", "印字する", "印字して", "書き込む")


def _negated(line_n: str, start: int, end: int) -> bool:
    return bool(_NEG_AFTER.match(line_n[end:end + 10]) or _NEG_BEFORE.search(line_n[max(0, start - 2):start]))


def _claim_found(c: dict, line_n: str, pos: int, win: int) -> bool:
    """about の語の直後の窓 ``line_n[pos:pos+win]`` (正規化済み) に、 claim の宣言する「矛盾する言い方」 があるか。
    否定の判定は窓でなく行で見る (= 窓の端で切れた「… =TODAY() なし」 を取り違えない)。"""
    after = line_n[pos:pos + win]

    def neg(m):
        return _negated(line_n, pos + m.start(), pos + m.end())

    if "value" in c and str(c["value"]) in _NUM_RE.findall(after):
        return True
    if c.get("negation") and any(nrm(w) in after for w in _NEG):
        return True
    for t in c.get("forbid") or []:
        if any(not neg(m) for m in re.finditer(re.escape(nrm(str(t))), after)):
            return True
    for pat in c.get("forbid_re") or []:
        if any(not neg(m) for m in re.finditer(pat, after)):
            return True
    if c.get("affirm"):
        for v in _AFFIRM:
            if any(not neg(m) for m in re.finditer(re.escape(v), after)):
                return True
    if c.get("other_numbers"):
        ok = {float(str(x).replace(",", "")) for x in c["other_numbers"]}
        unit = re.escape(nrm(str(c.get("unit") or "")))
        for n in re.findall(r"(?<![\d.,/-])(\d{1,3}(?:,\d{3})+|\d+)(?![\d,/-])" + unit, after):
            v = float(n.replace(",", ""))
            if v >= 100 and v not in ok:
                return True
    return False


def rule_claim_hits(line_n: str, claims) -> list:
    """[(rule id, says)]。 1 行 (正規化済み) の中で、 規則と矛盾する主張の形を探す。

    claim (spec の規則の ``claims:``) = ``about`` の語の**直後** (``window``、 既定 CLAIM_WINDOW 文字以内) に、 次の
    どれかが来る形。 ``context`` の語が行のどこかに要り、 ``unless`` の語が行にあれば除外:
      ``value`` = その数 / ``negation: true`` = 否定の語 (書かない・不要 …) / ``forbid`` = その語 (直後が否定なら除く) /
      ``forbid_re`` = 正規表現 / ``affirm: true`` = 書く・入れる・焼く (空が正の欄に当方が書く、 直後が否定なら除く) /
      ``other_numbers`` = 100 以上の数でその一覧に無いもの (``unit`` があればその単位の付いた数だけ = 日付を拾わない。
      単価 5,000 円の規則に 10,000 円)
    近さを要求するのは、 長い行の遠い所にある数 (§番号など) や否定 (別の話の「書かない」) を主張と取り違えないため
    (実 doc の誤検出を確かめて入れた)。"""
    hits = []
    for rid, c in claims:
        if c.get("context") and not any(nrm(k) in line_n for k in c["context"]):
            continue
        if any(nrm(k) in line_n for k in c.get("unless") or []):
            continue
        win = int(c.get("window") or CLAIM_WINDOW)
        found = False
        for k in c.get("about") or []:
            nk = nrm(k)
            for m in re.finditer(re.escape(nk), line_n):
                if _claim_found(c, line_n, m.end(), win):
                    found = True
                    break
            if found:
                break
        if found:
            hits.append((rid, c.get("says") or ""))
    return hits


# ---------------------------------------------------------------------------
# claims の網羅: 値・yes/no の規則は claims を持つ (無いと audit が落ちる = 網羅が黙って後退しない)
# ---------------------------------------------------------------------------
_VALUE_SHAPE_BASE = (r"[0-9０-９]|『[^』]+』|☑|□|○|空欄|空で|空の|書かない|書かず|しない|にしない|消す|残さない|不要|出ない|"
                     r"だけ|のみ|本人|事務|窓口|担当|自動転記|=|＝|数式|固定値|文字列")


@lru_cache(maxsize=1)
def _value_shape_re():
    """値・yes/no の規則の形。 「誰が書く欄か」 を言う語は組織ごとに違うので、 設定の ``lint.value_shape_words``
    (例: 窓口の部署名・相手の呼び方) を足せる (= 一覧を engine が持たない)。"""
    extra = [re.escape(str(w)) for w in CF.lint_cfg().get("value_shape_words") or []]
    return re.compile(_VALUE_SHAPE_BASE + ("|" + "|".join(extra) if extra else ""))


def rule_entries() -> list:
    """[(rule id, entry, spec id)]。 規則になる spec の entry (cells の rule / nittei・cross_checks の summary か same_as)。"""
    out = []
    for sid, spec in S.all_specs().items():
        for e in spec.get("cells") or []:
            if e.get("rule"):
                out.append((f"{sid}/{e['rule']}", e, sid))
        for e in list((spec.get("nittei") or {}).get("rules") or []) + list(spec.get("cross_checks") or []):
            if e.get("summary") or e.get("same_as"):
                out.append((f"{sid}/{e['id']}", e, sid))
    return out


def value_shaped(rule: dict, entry: dict) -> bool:
    """値・yes/no の規則か (= claims が要る)。 cell の state が値そのもの (fixed / empty / as_template / changed / checkbox)、
    ``values:`` を持つ、 または summary が値・否定・誰が書くかの形を含む。"""
    if entry.get("state") in ("fixed", "empty", "as_template", "changed", "checkbox", "checkbox_pair", "checkbox_exclusive"):
        return True
    if entry.get("values") or entry.get("type") in ("date", "number", "textfmt"):
        return True
    return bool(_value_shape_re().search(rule.get("summary") or ""))


def claims_coverage(entries=None) -> list:
    """claims の網羅の問題 = [(rule id, 理由)]。 空なら網羅。 entries = [(rule id, entry)] (selftest 用、 既定 = 全 spec)。"""
    if entries is None:
        allr = R.all_rules()
        ents = {rid: e for rid, e, _s in rule_entries()}
    else:
        ents = dict(entries)
        allr = {rid: {"summary": e.get("summary", "")} for rid, e in ents.items()}
    problems = []
    for rid, e in ents.items():
        tgt = e.get("same_as")
        if tgt and not e.get("claims"):
            te = ents.get(tgt) or {}
            if not te.get("claims"):
                problems.append((rid, f"same_as {tgt} の先にも claims が無い"))
            continue
        cl = e.get("claims")
        if cl:
            for i, c in enumerate(cl):
                if not c.get("about"):
                    problems.append((rid, f"claims[{i}] に about が無い"))
                if not any(k in c for k in CLAIM_KINDS):
                    problems.append((rid, f"claims[{i}] に矛盾の形 ({'/'.join(CLAIM_KINDS)}) が無い"))
                if not c.get("says"):
                    problems.append((rid, f"claims[{i}] に says (何と矛盾するか) が無い"))
            continue
        na = str(e.get("claims_na") or "").strip()
        if value_shaped(allr.get(rid, {}), e):
            problems.append((rid, "値・yes/no の規則なのに claims が無い" + (" (claims_na は値の規則には使えない)" if na else "")))
        elif not na:
            problems.append((rid, "claims も claims_na (値の規則でない理由) も無い"))
    return problems


_ADDR = r"(?<![A-Z0-9])({addr})(?![0-9])"
_QUOTED = r"[「『`\"']([^」』`\"']{1,40})[」』`\"']"
_ASSIGN = r"\s*(?:[=＝:：→]|は|に|を)\s*"


def cell_facts(forms=None) -> dict:
    """{(form, cell): (state, value, label)}。 spec の fixed (文字列の値) / empty の cell。 sheet 付き ref は cell だけを key に。"""
    out = {}
    for sid, spec in S.all_specs().items():
        if forms and sid not in forms:
            continue
        for e in spec.get("cells") or []:
            st = e.get("state")
            if st not in ("fixed", "empty"):
                continue
            v = e.get("value")
            if st == "fixed" and (not isinstance(v, str) or v.startswith("=") or not v.strip()):
                continue
            refs = e["ref"] if isinstance(e["ref"], list) else [e["ref"]]
            for r in refs:
                if ":" in r.split("!")[-1]:
                    continue
                cell = r.split("!")[-1]
                key = (sid, cell)
                out[key] = None if key in out and out[key] != (st, v, e.get("label", "")) else (st, v, e.get("label", ""))
    return {k: v for k, v in out.items() if v is not None}


def cell_claim_hits(raw_line: str, facts: dict) -> list:
    """[(form/cell, says)]。 行の中の「<cell> = 『値』」「<cell> は空」 を spec の値と比べる。 cell が複数の form で
    違う値なら (どの様式の話か行から決められない) 照合しない。"""
    import unicodedata

    line = unicodedata.normalize("NFKC", raw_line).replace("`", "'")
    by_cell = {}
    for (sid, cell), fact in facts.items():
        by_cell.setdefault(cell, []).append((sid, fact))
    hits = []
    for cell, cands in by_cell.items():
        if cell not in line:
            continue
        if len({(f[0], f[1]) for _s, f in cands}) > 1:
            continue
        sid, (st, v, label) = cands[0]
        for m in re.finditer(_ADDR.format(addr=re.escape(cell)) + _ASSIGN + "(?:" + _QUOTED + r"|([☑□○☐])|(空欄|空))", line):
            claimed = m.group(2) or m.group(3)
            empty_claim = bool(m.group(4))
            if st == "empty" and claimed and nrm(claimed) not in ("", "空欄"):
                hits.append((f"{sid}/{cell}", f"{cell} は空が正 (spec) なのに『{claimed}』 と書いてある"))
            elif st == "fixed" and empty_claim:
                hits.append((f"{sid}/{cell}", f"{cell} は『{v}』 (spec) なのに空と書いてある"))
            elif st == "fixed" and claimed and nrm(claimed) != nrm(v) and nrm(v) not in nrm(claimed):
                hits.append((f"{sid}/{cell}", f"{cell} は『{v}』 (spec) なのに『{claimed}』 と書いてある"))
    return hits


# ---------------------------------------------------------------------------
# 規則の形の文: process doc は cell / 値の規則を書かない (規則 id か generated view を置く)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)                 # 1 行ごとに組み直すと lint 全体が数倍になる (実測)
def _rule_ref_re():
    """規則 id の参照 (`<form>/<rule>`) の regex。 様式 id は spec から導出する (人が一覧を書かない)。"""
    ids = sorted(S.spec_ids(), key=len, reverse=True)
    if not ids:
        return re.compile(r"(?!)")
    return re.compile(r"`?(?:" + "|".join(re.escape(x) for x in ids) + r")/[a-z0-9-]+`?")
_LINKISH = re.compile(r"\]\([^)]*\)|https?://\S+|`[^`\n]*[/.][^`\n]*`")
_STMT_MARK = re.compile(r"^.{0,12}?(『|「|☑|□|○(?!前置)|(?<!架)空(?:欄|で|の|に)|書かない|書かず|書く|書いて|記入|入れる|入れない|入れて|"
                        r"焼く|焼いて|消す|消して|残す|残さない|不要|必ず|にする|にしない|とする|(?<![0-9/:.,-])[0-9][0-9,.]*(?:円|日(?![0-9])|pt|字|%))")
_ADDR_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{1,3}[1-9][0-9]{0,2})(?![0-9A-Za-z])")


def _keep(s: str) -> str:
    """statement 用の正規化 = NFKC + 空白・markdown の強調を除く (引用符は残す = 値の印)。"""
    import unicodedata

    t = unicodedata.normalize("NFKC", s)
    return "".join("" if ch.isspace() or ch in "*`" else ch for ch in t)


def statement_vocab(forms) -> tuple:
    """(規則の語, cell 番地)。 語 = その様式の規則の claims の about (人が一覧を書かない)、 番地 = spec の cells の ref。"""
    words, addrs = set(), set()
    for rid, c in _claims_of_rules():
        if rid.split("/")[0] in forms:
            for a in c.get("about") or []:
                # 数字を含む語は語彙にしない。 全角数字・丸数字 (①…) は NFKC で [0-9] に畳んでから見る
                if len(nrm(str(a))) >= 2 and not re.search(r"[0-9]", unicodedata.normalize("NFKC", str(a))):
                    words.add(_keep(str(a)))
    for sid, spec in S.all_specs().items():
        if sid in forms:
            for e in spec.get("cells") or []:
                for r in (e["ref"] if isinstance(e["ref"], list) else [e["ref"]]):
                    addrs.add(str(r).split("!")[-1].split(":")[0])
    return words, addrs, form_context_words(forms)


def form_context_words(forms) -> set:
    """行が様式の話をしているかの印 = spec の group の sheet 名・様式の title の語 (人が一覧を書かない)。"""
    out = set()
    for sid, spec in S.all_specs().items():
        if sid not in forms:
            continue
        stop = "|".join(re.escape(w) for w in CF.lint_cfg().get("context_stopwords") or [])
        drop = r"[【】（）()\s　]" + (("|" + stop) if stop else "")
        for g in (spec.get("groups") or {}).values():
            for sh in g.get("sheets") or []:
                t = re.sub(drop, "", str(sh))
                for part in re.split(r"[・]", t):
                    if len(part) >= 3:
                        out.add(part)
        meta = spec.get("meta") or {}
        for part in re.split(r"[\s（）()・、]+", str(meta.get("title") or "")):
            if len(part) >= 3:
                out.add(part)
        # 配布雛形の file 名の語 = 人が様式を呼ぶ名前
        for part in re.split(r"[\s_【】（）()・、,.=0-9]+", str(meta.get("form") or "")):
            part = part.strip("-")
            if len(part) >= 3 and re.search(r"[^\x00-\x7f]", part):
                out.add(part)
    return out


def statement_hits(line: str, vocab) -> list:
    """行の中の「規則の語 / cell 番地」 の直後 12 字以内に値・否定・書く/書かないの印がある箇所 = 規則の形の文。
    規則 id の参照 (`3_/stay-days`) と link・path は先に除く (= 参照は規則を書いていない)。 規則の語 (番地でない) は、
    行に様式の話の印 (sheet 名・様式名、 ``form_context_words``) がある時だけ数える (= 「経路」「会費」 の一般語の誤検出)。"""
    words, addrs = vocab[0], vocab[1]
    ctx = {_keep(c) for c in vocab[2]} if len(vocab) > 2 else set()
    ln = _keep(_LINKISH.sub("", _rule_ref_re().sub("", line)))
    hits = []
    for m in _ADDR_TOKEN.finditer(ln):
        if m.group(1) in addrs and _STMT_MARK.match(ln[m.end():]):
            hits.append(m.group(1))
    if ctx and not any(c in ln for c in ctx):
        return hits
    for w in sorted(words):
        for m in re.finditer(re.escape(w), ln):
            if _STMT_MARK.match(ln[m.end():]):
                hits.append(w)
                break
    return hits


def _value_source_table(line: str, state, prev_row: bool) -> bool:
    """案件 README の「値の出典」 表 (**表の最初の行 = header** に 出典) の行か (= 案件の事実と出所。 規則ではない)。
    state = 直前の行までの判定、 prev_row = 直前の行が表の行か。 header 以外の行の「出典」 でも立てると、 途中の行に
    「出典」 を含む表では以降の行が全部 lint の外に落ちる (実測)。"""
    if not line.startswith("|"):
        return False
    return bool(state) if prev_row else "出典" in line


def load_ack() -> list:
    p = ack_path()
    if p is None or not p.exists():
        return []
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return d.get("acks") or []


def forms_for(path: Path) -> tuple:
    """doc が話している様式 (cell の値の主張を照合する範囲)。 案件 README = その dir の submission.yaml の form、
    それ以外は設定の ``lint.forms_by_path`` = [{glob, forms}] の最初に当たったもの (無ければ全様式)。"""
    p = Path(path).resolve()
    mani = p.parent / "submission.yaml"
    if mani.exists():
        try:
            d = yaml.safe_load(mani.read_text(encoding="utf-8")) or {}
            fs = tuple(sorted({str(x.get("form")) for x in (d.get("documents") or {}).values()}))
            if fs:
                return fs
        except Exception:  # noqa: BLE001
            pass
    rule = CF.match_rule(p, CF.lint_cfg().get("forms_by_path"))
    return tuple(rule["forms"]) if rule else tuple(S.spec_ids())


def scan(paths=None, root: Path | None = None) -> list:
    """findings = [(relpath, line, token, rule, kind)]。 kind = superseded / marker / value / claim / statement / state /
    region (区間 marker の崩れ = token に説明)。

    照合は正規化 (nrm) の後の正規表現 (token_re) = 全角半角・空白・括弧・助詞 (は/を/が)・連結 (・/と)・数字の後の「日」
    の違いは同じ言い回しとして拾う。 claim = spec が宣言した「規則と矛盾する主張の形」 と、 cell の値の主張 (<cell> = 『値』)。"""
    root = Path(root).resolve() if root else CF.workspace_root()
    toks = [(t, token_re(t), rid, kind) for t, rid, kind in tokens()]
    rclaims = _claims_of_rules()
    acks = {(a["file"], a["token"]) for a in load_ack() if a.get("reason")}
    res = []
    items = ([(Path(p), ALL_KINDS + ("claim", "statement") + (("state",) if is_case_readme(p) else ()))
              for p in paths] if paths else targets(root))
    for p, kinds in items:
        raw = p.read_bytes()
        if raw.startswith(b"\x00GITCRYPT"):
            continue
        text = raw.decode("utf-8")
        ex = V.spans(text)
        rel = str(p.resolve().relative_to(root)) if str(p.resolve()).startswith(str(root)) else str(p)
        facts = cell_facts(forms_for(p)) if "claim" in kinds else {}
        vocab = statement_vocab(forms_for(p)) if "statement" in kinds else None
        ex_st = ex + list(V._fences(text))
        for ln_, why in V.region_problems(text):   # 区間 marker の崩れは除外範囲そのものを狂わせる = acks で黙らせない
            res.append((rel, ln_, why, "-", "region"))
        off, src_tbl, prev_row = 0, False, False
        for i, line in enumerate(text.split("\n")):
            start, off = off, off + len(line) + 1
            src_tbl = _value_source_table(line, src_tbl, prev_row)
            prev_row = line.startswith("|")
            if any(s < off - 1 and start < e for s, e in ex):   # 行が区間と重なれば除外 (行内の marker も可)
                continue
            nl = nrm(line)
            flagged = set()
            for t, rx, rid, kind in toks:
                if kind in kinds and rx.pattern and rx.search(nl) and (rel, t) not in acks:
                    res.append((rel, i + 1, t, rid, kind))
                    flagged.add(rid)
            if "claim" in kinds:
                for rid, says in rule_claim_hits(nl, rclaims) + cell_claim_hits(line, facts):
                    # 同じ行で同じ規則を token が既に拾っていれば claim は重ねない (1 行 1 規則 1 件)
                    if rid not in flagged and (rel, says) not in acks and (rel, rid) not in acks:
                        res.append((rel, i + 1, says, rid, "claim"))
                        flagged.add(rid)
            if "state" in kinds and not src_tbl and not any(s < off - 1 and start < e for s, e in ex_st):
                sh = state_hits(line)
                if sh and not any((rel, w) in acks for _l, w in sh):
                    res.append((rel, i + 1, " / ".join(w for _l, w in sh), "-", "state"))
            if "statement" in kinds and not flagged and not src_tbl \
                    and not any(s < off - 1 and start < e for s, e in ex_st):
                sh = statement_hits(line, vocab)
                if sh and (rel, "statement:" + nrm(line)[:40]) not in acks:
                    res.append((rel, i + 1, " ".join(sorted(set(sh))[:4]), "-", "statement"))
    return res


def render(findings) -> None:
    what = {"superseded": "廃止した版の規則の言い回し", "marker": "規則の定義文の書き写し",
            "value": "規則の値の書き写し", "claim": "規則と矛盾する値の主張",
            "statement": "規則の形の文 (cell 番地・規則の語 × 値・否定) を規則の home の外に書いている",
            "state": "案件の状態を README に手で書いている", "region": "区間 marker の対応が崩れている:"}
    for rel, line, t, rid, kind in findings:
        if kind == "region":
            print(f"   🔴 {rel}:{line}: {what[kind]} {t}")
            continue
        print(f"   🔴 {rel}:{line}: {what[kind]} {t!r}" + ("" if kind == "state" else f" (規則 {rid})"))
    if any(k == "region" for *_x, k in findings):
        print("   → formcase:view / formcase:history の区間は入れ子にしない (区間の中の強調・見出しは marker でなく普通の md で)。"
              " 崩れたままだと、 後ろの行が lint から黙って外れたり戻ったりする")
    if any(k == "state" for *_x, k in findings):
        print("   → 状態の正本 = submission.yaml (README には <!-- formcase:view kind=status --> を置いて views --write) と"
              " 案件の TODO (未決の問い・約束・返事待ちは TODO の notes)。 README は file の説明・値の出典・経緯"
              f" (経緯は <!-- formcase:history --> で囲む) だけ。 状態でない語なら {ack_path()} に file と語と理由")
    if any(k not in ("state", "region") for *_x, k in findings):
        print("   → 直し方: その行を規則 id への pointer か generated view (formcase:view) にする。 経緯として残すなら "
              f"<!-- formcase:history --> で囲む。 どれも違うなら {ack_path()} に理由つきで承認")
