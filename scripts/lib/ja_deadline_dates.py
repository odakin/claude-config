"""ja_deadline_dates.py — 日本語の文から「期限らしい日付」 を取る共通部品（散文 = task 記録・メモの次の期限 / メール本文 = 入力・提出・申請の〆切。 締切語の隣接・行動語・行動窓の範囲の終端・月の無い日付と相対表現と英文の日付・日付が読めないときの急ぎの語・引用除去・述語の指紋。 docs/convention-design-principles.md#single-deadline-field-many-legs / #elapsed-time-urgency-inversion / #unclassified-defaults-to-loud、 --selftest）

使い方 (散文 = 記録の本文から次の期限):
    nearest_prose_deadline(text, today, base, window=14)   # today..today+window の最早 (無ければ None)
    prose_deadline_dates(text, base)                        # 期限らしい日付の全件 [(date, 文脈)]

使い方 (メール本文 = 受信者の行動が要る〆切):
    extract_input_deadlines(body, today, horizon_days=7, require_action=True)   # [{"date", "time", "context", "kind", "form"}]
    deadlines_from_body(body, received, horizon_days=120, require_action=True)   # 引用を落として日付だけの昇順 list
    urgency_signals(text)                                    # 急ぎ・締切の語 (日付が取れなくても「期限なし」 と扱わないための印)
    strip_quoted(body)                                       # 返信の引用部を落とす (転送本文は残す)
    drop_reply_headers(body)                                 # 引用の中身は残し、 引用ヘッダ行 (日時つき) だけ落とす
    predicate_version(*extra)                                # 抽出述語の指紋 (cache の鮮度判定用)

2 つを分けている理由: 散文は「〆」 単独・「申請」「応募」 が期限の印になり、 済/完了 の記号で終わった項目を除く必要がある。
メール本文は締切語だけでは一般の期限の言及 (工事は M/D まで 等) を拾うので、 **締切語 ∧ 行動語 (またはフォーム URL)** の 2 条件にする。
⚠️ 2 条件の語彙に同じ語を入れない (= その語 1 つで関門を通る。 例: 「応募」 は締切語側だけ)。 語彙を変えたら predicate_version が変わる。

年の無い日付は基準日 (散文 = 記録を書いた日 / メール = 受信日) 以降で最も近い日に解く。 月の無い「N日」・相対表現 (今週中 / 明日まで / 金曜まで)・
英文 (by Oct 5 / by Friday) も同じ基準日から解く (メール本文だけ。 散文は月日の形のまま)。
**空の結果は「期限が無い」 を意味しない** (方言の列挙は収束しない)。 呼び出し側は urgency_signals と組にして、 「語はあるのに日付が取れない」 を
「期限なし」 と同じ扱いにしない (docs/convention-design-principles.md#unclassified-defaults-to-loud)。
heuristic なので、 **結果は表示の並べ替え・印・候補の提示に使い、 それだけで自動処分しない**。 呼び出し側は import 失敗を含めて fail-open にする。
"""
from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------
DATE_JA_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")                 # 「6月10日」 (全角は正規化後)
DATE_SLASH_RE = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/.])")    # 「6/10」
ZEN2HAN = str.maketrans("０１２３４５６７８９：／～〜", "0123456789:/~~")
NORMALIZE_FORM = "NFKC"


def normalize_text(s: str) -> str:
    """NFKC で字を揃えてから (康熙部首の「⽉」「⽇」 → 「月」「日」、 全角の数字・記号・括弧 → 半角 = 実測で康熙部首の形の
    日付を落とした)、 NFKC が変えない波ダッシュ「〜」 も含めて半角に揃える。"""
    return unicodedata.normalize(NORMALIZE_FORM, s or "").translate(ZEN2HAN)


def resolve_year(month: int, day: int, today: date) -> date | None:
    """月日 → today 以降で最も近い date。 不正な月日は None。"""
    for y in (today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


# ---------------------------------------------------------------------------
# 散文 (記録の本文から次の期限)
# ---------------------------------------------------------------------------
PROSE_DATE_RE = re.compile(DATE_SLASH_RE.pattern + r"|" + DATE_JA_RE.pattern)
PROSE_CTX_RE = re.compile(r"(〆|締切|締め切り|期限|期日|まで|応募|提出|申込|申請)")
PROSE_DONE_RE = re.compile(r"(✅|済|完了)")
PRE_CHARS, POST_CHARS, DONE_CHARS = 10, 8, 12


def prose_deadline_dates(text: str, base: date) -> list[tuple[date, str]]:
    """期限らしい日付の全件 (出現順)。 締切語が隣接 ∧ 済/完了 が隣接しない日付だけ。 窓は隣の日付で切る。"""
    t = normalize_text(str(text or ""))
    ms = list(PROSE_DATE_RE.finditer(t))
    out: list[tuple[date, str]] = []
    lo = 0
    for i, m in enumerate(ms):
        mo, dy = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        hi = ms[i + 1].start() if i + 1 < len(ms) else len(t)
        near = t[max(lo, m.start() - PRE_CHARS): min(hi, m.end() + POST_CHARS)]
        done_near = t[max(lo, m.start() - DONE_CHARS): min(hi, m.end() + DONE_CHARS)]
        gap = len(t[m.end():]) - len(t[m.end():].lstrip(" 　"))
        tail = PROSE_CTX_RE.match(t, m.end() + gap)
        lo = tail.end() if tail else m.end()  # 日付の直後に付いた締切語はその日付のもの
        if not PROSE_CTX_RE.search(near) or PROSE_DONE_RE.search(done_near):
            continue
        d = resolve_year(int(mo), int(dy), base)
        if d is not None:
            out.append((d, near.replace("\n", " ").strip()))
    return out


def nearest_prose_deadline(text: str, today: date, base: date, window: int = 14) -> date | None:
    """today..today+window に入る期限らしい日付の最早。 無ければ None。"""
    cands = [d for d, _ in prose_deadline_dates(text, base) if today <= d <= today + timedelta(days=window)]
    return min(cands) if cands else None


# ---------------------------------------------------------------------------
# メール本文 (受信者の行動が要る〆切)
# ---------------------------------------------------------------------------
# 締切語 (= 予定の日付でなく期限)。 日付の後方 12 字か前方 16 字 (「登録期限: M/D」 の label 前置型) にあれば締切文脈
DEADLINE_CTX_RE = re.compile(r"(まで|〆切|締切|締め切り|期限|期日|提出|納入|応募|申込期限)")
# 行動語 (= 受信者が何かをする)。 一般の期限の言及 (工事・閉室) を拾わないための 2 つめの条件。
# 事務の念押しは手続きの名詞 (申請) だけで期限を示すことがある。 「応募」 は締切語側にあるので入れない
INPUT_ACTION_RE = re.compile(r"(入力|回答|登録|提出|記入|投票|アンケート|確認|書き込|修正|ご希望|希望を|申請)")
# 本文にあれば行動語の代わりになる入力先 (日程調整・フォーム・共有シート)
FORM_URL_RE = re.compile(r"(chouseisan\.com|forms\.gle|forms\.office\.com|docs\.google\.com/(forms|spreadsheets)|drive\.google\.com)",
                         re.IGNORECASE)
# 行動窓の範囲表記「<label> … A ～ B」 の B は締切語を持たないが期限。 label は「何かをする期間」 に限る (開催期間・会期は入れない)
PERIOD_LABEL_RE = re.compile(r"(登録期間|申請期間|提出期間|受付期間|募集期間|申込期間|入力期間|回答期間|訂正期間)")
_DATE_ANY = r"(\d{1,2}\s*月\s*\d{1,2}\s*日|(?<![\d/.])\d{1,2}/\d{1,2}(?![\d/.]))"
RANGE_TAIL_RE = re.compile(_DATE_ANY + r"[^\n~]{0,14}~[^\S\n]*$")
# 返信の引用ヘッダ (以降は引用 = 古い期限)
REPLY_HEADER_RE = re.compile(r"^\s*(\d{4}年\d{1,2}月\d{1,2}日.*[:：]|On .+ wrote:)\s*$")

# --- 月日の揃った書き方以外の方言 (月の無い日付・相対表現・曜日・英文) ---
# 人が人に書く依頼は「N日が締め切り」「今週中に」「by Friday」 のように月を書かないことが多い。
# 月日の形しか読めない抽出は、 その依頼を「期限なし」 と同じに扱う (= 取得の失敗が「なし」 に化ける)。
# ⚠️ 方言の列挙は収束しない。 読めなかった場合の備えは urgency_signals (締切語・急ぎの語はあるのに日付が取れない
#    = 「本文を読むまで分からない」 を呼び出し側が大きく出す) で、 ここの列挙はその件数を減らすだけ。
# 月の無い日付「N日」。 月日の一部・期間・回数・相対 (N日間 / N日目 / N日前 …) は除く
DAY_ONLY_RE = re.compile(r"(?<![\d月/.:年])(\d{1,2})\s*日(?!間|目|ほど|程|前|後|以内|以上|以降|ごと|おき|分|付|頃|ころ|連続|本)")
DAY_ONLY_PRE_EXCLUDE_RE = re.compile(r"(あと|残り|約|ほぼ|およそ|計|全|丸)\s*$")
# 月の無い日付は証拠が弱いので、 締切語の**直接の隣接**だけを文脈に取る (曜日の括弧・時刻・助詞 1 つは挟める)
DAY_ONLY_POST_RE = re.compile(
    r"^\s*(?:[（(][月火水木金土日祝・]+[)）])?\s*(?:の?\s*\d{1,2}(?::\d{2}|時)(?:\d{1,2}分)?\s*)?"
    r"(?:が|を|は|の|で)?\s*(まで|〆|締切|締め切り|期限|期日|必着|厳守)")
DAY_ONLY_PRE_RE = re.compile(r"(〆切|締切|締め切り|期限|期日|〆)\s*(?:は|が|を|:|=|、)?\s*$")
_WD_JA = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
# 相対表現。 語尾 (中 / まで / 〆 …) が期限の意味を持つ形だけを取る (「明日は休みです」 は取らない)
# 「まで」 は「までに」 か文末の形だけ (「今日まで気づかなかった」「明日までは出張」 = 期限ではない)
_REL_SUFFIX = r"(?:中|までに|まで(?=です|でお願|。|\n|$)|〆|締切|締め切り|いっぱい)"
REL_JA_RES = (
    ("today", re.compile(r"(?:今日|本日)\s*" + _REL_SUFFIX)),
    ("tomorrow", re.compile(r"(?:明日|あす)\s*(?:" + _REL_SUFFIX + r"|の?(?:朝|午前|正午|昼|夕方|夜)(?:中|までに))")),
    ("day2", re.compile(r"(?:明後日|あさって)\s*" + _REL_SUFFIX)),
    ("this_week", re.compile(r"今週\s*(?:中|いっぱい|内|末までに)")),
    ("next_week", re.compile(r"来週\s*(?:中|いっぱい|内|末までに)")),
    ("this_month", re.compile(r"(?:今月|当月)\s*(?:中|いっぱい|内|末までに)|(?<![\d今来先毎])月末\s*(?:までに|〆|締切|締め切り)")),
    ("next_month", re.compile(r"来月\s*(?:中|いっぱい|末までに)")),
)
REL_JA_WD_RE = re.compile(r"(来週の?\s*)?(?:今週の?\s*)?([月火水木金土日])曜日?\s*(?:[（(]\d{1,2}日?[)）])?\s*"
                          r"(?:中|までに|まで(?=です|でお願|。|\n|$)|〆|締切|締め切り|が期限|が締)")
# 年つきの日付 (2030.7.24 / 2030/7/24 / 2030-07-24)。 月日だけの形は直前の数字や記号を避けるので、 年つきはここで読む
FULL_DATE_RE = re.compile(r"(?<!\d)(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?!\d)")
_YEAR_BEFORE_RE = re.compile(r"(20\d{2})\s*年\s*$")
_YEAR_AFTER_RE = re.compile(r"^,?\s*(20\d{2})\b")
# 英文の日付と締切文脈。 月名は先頭大文字だけ (助動詞 may を拾わない)
_EN_MON_ALT = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
               r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_EN_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
              "sep": 9, "oct": 10, "nov": 11, "dec": 12}
EN_MD_RE = re.compile(r"\b" + _EN_MON_ALT + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*:\d)")
EN_DM_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _EN_MON_ALT + r"\b")
_EN_WD_ALT = r"(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day"
_EN_WD = {"mon": 0, "tues": 1, "wednes": 2, "thurs": 3, "fri": 4, "satur": 5, "sun": 6}
# by / until / before は日付の**直前**にあるときだけ (「written by X on Sep 5」 を拾わない)。 deadline / due は同じ文の中
EN_CTX_PRE_RE = re.compile(
    r"(?:\b(?:by|until|till|before|on or before|no later than|not later than)\s+(?:the\s+)?(?:end\s+of\s+)?"
    r"(?:" + _EN_WD_ALT + r",?\s+)?|\b(?:deadline|due(?!\s+to\b))\b[^.\n]{0,30})$", re.IGNORECASE)
EN_CTX_POST_RE = re.compile(r"^[^.\n]{0,30}\b(?:deadline|at the latest|due date)\b", re.IGNORECASE)
EN_ACTION_RE = re.compile(r"\b(?:submit|send|reply|respond|register|confirm|complete|fill|provide|upload|return|review|"
                          r"sign|let (?:me|us) know|get back)\b", re.IGNORECASE)
EN_REL_RE = re.compile(
    r"\b(?:by|until|before)\s+(?:the\s+)?(tomorrow|today|tonight|EOD|end\s+of\s+(?:the\s+|this\s+)?(?:day|week|month)|"
    r"(?:(this|next)\s+)?" + _EN_WD_ALT + r")\b", re.IGNORECASE)
# 急ぎ・締切の語 (日付が取れなくても「読まないと分からない期限がある」 の印になる)。 「取り急ぎ」 は結びの定型なので除く
URGENCY_WORD_RE = re.compile(
    r"(締切|締め切り|〆切|〆|期限|期日|(?<!これ)(?<!それ)(?<!今)(?<!いま)までに|必着|至急|(?<!取り)急ぎ|早急|緊急|なるべく早|できるだけ早|お早めに|"
    r"\bdeadline\b|\bdue (?:date|by|on)\b|\bno later than\b|\bat the latest\b|\burgent(?:ly)?\b|\bASAP\b|"
    r"\bas soon as possible\b)", re.IGNORECASE)


def resolve_day_only(day: int, base: date) -> date | None:
    """月の無い「N日」 → base 以降で最も近い N 日 (その月に N 日が無ければ次の月)。"""
    y, m = base.year, base.month
    for _ in range(3):
        try:
            d = date(y, m, day)
        except ValueError:
            d = None
        if d is not None and d >= base:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def _month_end(y: int, m: int) -> date:
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(ny, nm, 1) - timedelta(days=1)


def _week_end(base: date, weeks_ahead: int = 0) -> date:
    """その週の金曜 (base が土日ならその日)。 weeks_ahead=1 で翌週の金曜。"""
    if weeks_ahead == 0 and base.weekday() >= 5:
        return base
    monday = base - timedelta(days=base.weekday()) + timedelta(weeks=weeks_ahead)
    return monday + timedelta(days=4)


def _weekday_on_or_after(base: date, wd: int, next_week: bool = False) -> date:
    if next_week:
        return base - timedelta(days=base.weekday()) + timedelta(weeks=1, days=wd)
    return base + timedelta(days=(wd - base.weekday()) % 7)


def resolve_relative(kind: str, base: date) -> date:
    """相対表現の種類 → 日付 (base = 受信日)。"""
    if kind == "today":
        return base
    if kind == "tomorrow":
        return base + timedelta(days=1)
    if kind == "day2":
        return base + timedelta(days=2)
    if kind == "this_week":
        return _week_end(base)
    if kind == "next_week":
        return _week_end(base, 1)
    if kind == "this_month":
        return _month_end(base.year, base.month)
    if kind == "next_month":
        ny, nm = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
        return _month_end(ny, nm)
    raise ValueError(kind)


def urgency_signals(text: str) -> list[str]:
    """件名・本文 (引用を除いたもの) に出る急ぎ・締切の語を、 出現順・重複なしで返す純関数。
    呼び出し側の使い方 = 「語はあるのに deadlines_from_body が空」 を「期限なし」 と同じに扱わない。"""
    seen: list[str] = []
    for m in URGENCY_WORD_RE.finditer(normalize_text(text or "")):
        w = m.group(0).lower()
        if w not in seen:
            seen.append(w)
    return seen


def is_period_range_end(text: str, m: re.Match) -> bool:
    """日付 match m が「<行動窓の label> … 日付A ～ 日付B」 の B なら True (正規化済み text 前提)。"""
    base = max(0, m.start() - 40)
    rm = RANGE_TAIL_RE.search(text[base: m.start()])
    if not rm:
        return False
    range_start = base + rm.start()
    return bool(PERIOD_LABEL_RE.search(text[max(0, range_start - 40): range_start]))


def extract_input_deadlines(body: str, today: date, horizon_days: int = 7, require_action: bool = True) -> list[dict]:
    """本文から受信者の行動が要る〆切を抽出する純関数。

    条件 = 日付が today..today+horizon ∧ 締切文脈 ∧ (前後に行動語 ∨ 本文にフォーム URL)。 同じ日付は 1 件。
    日付の形 (各 item の `form`) = 月日 (ja) / M/D (slash) / 英文の月名 (en) / 月の無い「N日」 (day-only) / 相対表現・曜日 (rel)。
    締切文脈 = 締切語が後方 12 字 / 前方 16 字 ∨ 行動窓の範囲の終端 ∨ 英文の by・deadline (月の無い日付は締切語の直接の隣接だけ、
    相対表現は語尾がその役)。
    require_action=False = 行動語を要求しない。 **宛先がその人だけの、 人が書いた mail** 向け (一斉の案内と違い、 そこに書かれた
    期限は受け手のもの。 「N日が締め切りなので」 のように行動語を書かない依頼が落ちる)。 一斉の案内には既定 (True) のまま使う。"""
    text = normalize_text(body)
    has_form_url = bool(FORM_URL_RE.search(text))
    out: list[dict] = []
    seen: set[str] = set()

    def add(s: int, e: int, d: date | None, form: str, ctx_ok: bool):
        if d is None or not (today <= d <= today + timedelta(days=horizon_days)):
            return
        if not ctx_ok:
            return  # 締切文脈なし = 予定の日付
        pre = text[max(0, s - 60): s]
        post = text[e: e + 60]
        if require_action and not (has_form_url or INPUT_ACTION_RE.search(pre) or INPUT_ACTION_RE.search(post)
                                   or EN_ACTION_RE.search(text[max(0, s - 80): s]) or EN_ACTION_RE.search(text[e: e + 80])):
            return  # 行動の証拠なし = 一般の期限の言及
        if d.isoformat() in seen:
            return
        seen.add(d.isoformat())
        ctx = (pre[-25:] + text[s:e] + post[:35]).replace("\n", " ").strip()
        out.append({"date": d.isoformat(), "time": None, "context": ctx, "kind": "input-deadline", "form": form})

    def ctx(s: int, e: int) -> bool:
        return bool(DEADLINE_CTX_RE.search(text[e: e + 12]) or DEADLINE_CTX_RE.search(text[max(0, s - 16): s])
                    or EN_CTX_PRE_RE.search(text[max(0, s - 48): s]) or EN_CTX_POST_RE.match(text[e: e + 48]))

    def dated(year: str | None, mo: int, dy: int) -> date | None:
        """年が書いてあればその年の日付 (過去なら None)、 無ければ today 以降で最も近い日。"""
        if not year:
            return resolve_year(mo, dy, today)
        try:
            d = date(int(year), mo, dy)
        except ValueError:
            return None
        return d if d >= today else None

    full_spans: list[tuple[int, int]] = []
    for m in FULL_DATE_RE.finditer(text):
        full_spans.append(m.span())
        mo, dy = int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            add(m.start(), m.end(), dated(m.group(1), mo, dy), "full", ctx(m.start(), m.end()))
    for m in DATE_JA_RE.finditer(text):
        full_spans.append(m.span())
        ym = _YEAR_BEFORE_RE.search(text[max(0, m.start() - 8): m.start()])
        add(m.start(), m.end(), dated(ym.group(1) if ym else None, int(m.group(1)), int(m.group(2))), "ja",
            ctx(m.start(), m.end()) or is_period_range_end(text, m))
    for m in DATE_SLASH_RE.finditer(text):
        if any(a <= m.start() < b for a, b in full_spans):
            continue  # 年つきの日付の一部
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            add(m.start(), m.end(), resolve_year(mo, dy, today), "slash",
                ctx(m.start(), m.end()) or is_period_range_end(text, m))
    for rx, mo_g, dy_g in ((EN_MD_RE, 1, 2), (EN_DM_RE, 2, 1)):
        for m in rx.finditer(text):
            full_spans.append(m.span())
            mo, dy = _EN_MONTHS[m.group(mo_g)[:3].lower()], int(m.group(dy_g))
            ym = _YEAR_AFTER_RE.match(text[m.end(): m.end() + 8])
            if 1 <= dy <= 31:
                add(m.start(), m.end(), dated(ym.group(1) if ym else None, mo, dy), "en", ctx(m.start(), m.end()))
    for m in DAY_ONLY_RE.finditer(text):
        if any(s <= m.start() < e for s, e in full_spans):
            continue  # 月日の一部 (「9月 28日」 等)
        if DAY_ONLY_PRE_EXCLUDE_RE.search(text[max(0, m.start() - 4): m.start()]):
            continue  # 「あと 2 日」 = 期間
        dy = int(m.group(1))
        if 1 <= dy <= 31:
            add(m.start(), m.end(), resolve_day_only(dy, today), "day-only",
                bool(DAY_ONLY_POST_RE.match(text[m.end(): m.end() + 24])
                     or DAY_ONLY_PRE_RE.search(text[max(0, m.start() - 10): m.start()])))
    for kind, rx in REL_JA_RES:
        for m in rx.finditer(text):
            add(m.start(), m.end(), resolve_relative(kind, today), "rel", True)
    for m in REL_JA_WD_RE.finditer(text):
        add(m.start(), m.end(), _weekday_on_or_after(today, _WD_JA[m.group(2)], bool(m.group(1))), "rel", True)
    for m in EN_REL_RE.finditer(text):
        w = m.group(1).lower()
        if m.group(3):
            d = _weekday_on_or_after(today, _EN_WD[m.group(3).lower()], (m.group(2) or "").lower() == "next")
        elif w.startswith("tomorrow"):
            d = today + timedelta(days=1)
        elif "week" in w:
            d = _week_end(today)
        elif "month" in w:
            d = _month_end(today.year, today.month)
        else:
            d = today  # today / tonight / EOD / end of day
        add(m.start(), m.end(), d, "rel", True)
    return out


def strip_quoted(body: str) -> str:
    """返信の引用部を落とす (= 古い期限を今の依頼と取り違えない)。 転送本文は残す (= 転送の期限は本物)。"""
    out: list[str] = []
    for ln in (body or "").splitlines():
        if ln.lstrip().startswith(">"):
            continue
        if REPLY_HEADER_RE.match(ln):
            break
        out.append(ln)
    return "\n".join(out)


def drop_reply_headers(body: str) -> str:
    """引用ヘッダ行 (「YYYY年M月D日(曜) H:MM 名前 <addr>:」 / 「On ... wrote:」、 行頭の > は何段でも) だけを落とす。
    引用の中身は残す = 元の mail に書かれた日時が今も生きている検出器 (予定の抽出) 向け。 ヘッダの日時は
    「いつ書かれたか」 であって予定ではないのに、 日付 + 時刻の形なので予定として拾われる (実測の誤検出)。"""
    return "\n".join(ln for ln in (body or "").splitlines()
                     if not REPLY_HEADER_RE.match(ln.lstrip().lstrip(">").lstrip(" >")))


def deadlines_from_body(body: str, received: date, horizon_days: int = 120, require_action: bool = True) -> list[str]:
    """引用を除いた本文の〆切を ISO 日付の昇順 list で返す純関数。 取れなければ []。
    require_action = extract_input_deadlines と同じ (宛先がその人だけの、 人が書いた mail には False)。
    ⚠️ [] は「期限が無い」 ではなく「読み取れなかった」 を含む。 急ぎ・締切の語の有無は urgency_signals で別に見る。"""
    try:
        found = extract_input_deadlines(strip_quoted(body), received, horizon_days, require_action)
    except Exception:
        return []
    return sorted({d["date"] for d in found})


def predicate_version(*extra: str) -> str:
    """メール本文の抽出述語 (正規表現と引用ヘッダ) の指紋。 cache に持たせ、 違えば捨てる (= 手で上げる版番号を持たない)。
    呼び出し側の窓の幅など、 結果を変える値は extra に渡す。"""
    parts = [r.pattern for r in (DATE_JA_RE, DATE_SLASH_RE, DEADLINE_CTX_RE, INPUT_ACTION_RE, FORM_URL_RE,
                                 PERIOD_LABEL_RE, RANGE_TAIL_RE, REPLY_HEADER_RE,
                                 DAY_ONLY_RE, DAY_ONLY_PRE_EXCLUDE_RE, DAY_ONLY_POST_RE, DAY_ONLY_PRE_RE, REL_JA_WD_RE,
                                 EN_MD_RE, EN_DM_RE, EN_CTX_PRE_RE, EN_CTX_POST_RE, EN_ACTION_RE, EN_REL_RE,
                                 URGENCY_WORD_RE, FULL_DATE_RE, _YEAR_BEFORE_RE, _YEAR_AFTER_RE)]
    parts += [rx.pattern for _k, rx in REL_JA_RES]
    parts += ["normalize:" + NORMALIZE_FORM]          # 正規化を変えると結果が変わる = 古い cache を捨てさせる
    parts += [str(x) for x in extra]
    return hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
def _selftest() -> int:
    ok = 0
    ng = 0

    def check(cond, name):
        nonlocal ok, ng
        if cond:
            ok += 1
            print(f"  PASS: {name}")
        else:
            ng += 1
            print(f"  FAIL: {name}")

    # --- 散文 (合成データ) ---
    base, today = date(2030, 2, 1), date(2030, 3, 10)
    legs = ("① 要旨 2/20〆 → ② 手続き 2/28 提出 → ③ 登録 (窓 3/1-31) 〔✅ 3/10 支払済〕 → ④ 学内助成\n"
            "応募 3/15〆。 条件 = 3/12 の会議で承認")
    check(nearest_prose_deadline(legs, today, base) == date(2030, 3, 15),
          "散文: 過去の項目・済の項目・締切語の無い日付を除いて次の期限を取る")
    check(nearest_prose_deadline("報告書は 3/20 提出済", today, base) is None, "散文: 済 が隣接する日付は取らない")
    check(nearest_prose_deadline("✅ 提出済 3/20", today, base) is None, "散文: 済 が前にあっても取らない")
    check(nearest_prose_deadline("次回は 4/30〆", today, base) is None, "散文: 窓より先は取らない")
    check(nearest_prose_deadline("3/15〆。 条件 = 3/12 会議", today, base) == date(2030, 3, 15),
          "散文: 隣の日付の直後の〆を次の日付のものと読まない")
    check(nearest_prose_deadline("（〆 3/13）は別の窓口", today, base) == date(2030, 3, 13), "散文: 締切語が前にある形")
    check(nearest_prose_deadline("３月１４日（金）までに", today, base) == date(2030, 3, 14), "散文: 全角数字と月日表記")
    check(nearest_prose_deadline("3⽉14⽇（金）までに", today, base) == date(2030, 3, 14), "散文: 康熙部首の「⽉」「⽇」 の月日表記")
    check(nearest_prose_deadline("12/25〆", date(2030, 12, 20), date(2030, 11, 1)) == date(2030, 12, 25), "散文: 年の解決は base 以降")
    check(prose_deadline_dates("", base) == [], "散文: 空文字は空")

    # --- メール本文 (合成データ) ---
    t = date(2030, 7, 20)
    check([d["date"] for d in extract_input_deadlines("回答は 7⽉ 24⽇（⽔）までに提出してください。", t, 7)] == ["2030-07-24"],
          "メール: 康熙部首の「⽉」「⽇」「⽔」 で書かれた期限 (全角の括弧も)")
    check([d["date"] for d in extract_input_deadlines("報告書は7月25日までに提出してください。", t, 7)] == ["2030-07-25"],
          "メール: 締切語 + 行動語")
    check(extract_input_deadlines("工事は7月25日まで続く見込みです。", t, 7) == [], "メール: 行動語が無い期限の言及は取らない")
    check([d["date"] for d in extract_input_deadlines("ご都合を https://chouseisan.com/s?h=x に 7/24 までにどうぞ。", t, 7)]
          == ["2030-07-24"], "メール: フォーム URL が行動語の代わり")
    check(extract_input_deadlines("報告書は8月20日までに提出してください。", t, 7) == [], "メール: horizon の外は取らない")
    check([d["date"] for d in extract_input_deadlines("登録期限: 7/23(火)\n参加の登録をお願いします。", t, 7)] == ["2030-07-23"],
          "メール: 締切語が日付より前 (label 前置型)")
    rng = "【受付期間】\n７月２１日（月）11:00～７月２２日（火）11:00\n窓口で登録してください。"
    check([d["date"] for d in extract_input_deadlines(rng, t, 7)] == ["2030-07-22"],
          "メール: 行動窓の範囲の終端を取り、 始端は取らない")
    check(extract_input_deadlines("学会の開催期間は7月21日～7月24日です。参加登録はお済みですか。", t, 7) == [],
          "メール: 開催期間の範囲の終端は取らない")
    check(extract_input_deadlines("7月21日～7月29日は窓口を閉室します。", t, 30) == [], "メール: label の無い範囲は取らない")
    nen = "書類の件でご連絡します。\n助成の申請期限は７月25日（金）です。"
    check([d["date"] for d in extract_input_deadlines(nen, t, 7)] == ["2030-07-25"], "メール: 手続きの名詞 (申請) だけの念押し")
    check(extract_input_deadlines("採択結果は7月25日に通知します。応募者数は120件でした。", t, 60) == [],
          "メール: 「応募」 1 語では締切語と行動語を兼ねない")
    quoted = "承知しました。\n\n2030年7月20日(土) 10:00 X <x@example.com>:\n> 報告書は7月23日（火）までに提出してください。"
    check(deadlines_from_body(quoted, t) == [], "メール: 引用部だけにある古い期限は取らない")
    fwd = "---------- Forwarded message ---------\n差戻の件、7月24日（水）までにご修正ください。"
    check(deadlines_from_body(fwd, t) == ["2030-07-24"], "メール: 転送本文の期限は取る")
    rh = "了解です。\n\n2030年7月24日(水) 8:31 Taro <taro@example.org>:\n\n> > 2030年7月23日(火) 22:46 <hanako@example.org>:\n> 7月30日 13:00 から打ち合わせ\nOn Tue, Jul 23, 2030 at 9:00 PM Hanako wrote:"
    dr = drop_reply_headers(rh)
    check("8:31" not in dr and "22:46" not in dr and "wrote:" not in dr and "7月30日 13:00" in dr,
          "引用ヘッダ: ヘッダ行 (> 付きも) だけ落とし、 引用の中身は残す")
    # --- 月の無い日付・相対表現・英文 (合成データ。 2030-07-20 は土曜) ---
    def dl(body, base=t, horizon=45, action=True):
        return [d["date"] for d in extract_input_deadlines(body, base, horizon, action)]

    check(dl("資料を添付します。24日が締め切りなので、よろしくお願いします。", action=False) == ["2030-07-24"],
          "月なし: 「N日が締め切り」 を受信日以降の最も近い N 日に解く (行動語を要求しない宛先 1 人の mail)")
    check(dl("資料を添付します。24日が締め切りなので、よろしくお願いします。") == [],
          "月なし: 行動語を要求する既定では、 行動語の無い文は取らない (一斉の案内の誤検出を増やさない)")
    check(dl("回答は 5日（月）17:00 までにお願いします。") == ["2030-08-05"],
          "月なし: 受信日より前の日は翌月に解く (曜日の括弧と時刻を挟める)")
    check(dl("締切は31日です。ご提出ください。", date(2030, 9, 5), 60) == ["2030-10-31"],
          "月なし: その月に無い日 (9 月の 31 日) は次の月")
    check(dl("会議は24日に開催します。出欠を回答してください。") == [],
          "月なし: 締切語が直接隣接しない日付は取らない (予定の日付)")
    check(dl("作業には3日間かかるので、提出期限を延ばしてください。") == [] and dl("あと2日で締切です。登録を。") == [],
          "月なし: 期間 (N日間 / あと N 日) は日付として読まない")
    check(dl("9月 24日までに登録してください。", date(2030, 9, 1)) == ["2030-09-24"],
          "月なし: 月日の一部 (空白を挟んだ形) を月の無い日付として二重に読まない")
    check(dl("今週中にご回答ください。", date(2030, 7, 22)) == ["2030-07-26"], "相対: 今週中 = その週の金曜")
    check(dl("明日までに提出をお願いします。") == ["2030-07-21"] and dl("明日は休講です。") == [],
          "相対: 語尾 (まで / 中) のある形だけ取る")
    check(dl("金曜までに確認してください。", date(2030, 7, 22)) == ["2030-07-26"]
          and dl("来週の水曜までに確認してください。", date(2030, 7, 22)) == ["2030-07-31"],
          "相対: 曜日 = 受信日以降の最初のその曜日 / 「来週の」 は翌週")
    check(dl("今月中に申請してください。") == ["2030-07-31"] and dl("月末に懇親会があります。登録を。") == [],
          "相対: 今月中 = 月末日。 語尾の無い「月末」 は取らない")
    check(dl("Please send your report by Aug 2.") == ["2030-08-02"]
          and dl("The deadline for registration is 2 August. Please register.") == ["2030-08-02"],
          "英文: by + 月名の日付 / deadline + 日 月")
    check(dl("The report was written by Kim on Aug 2. Please review it.") == [],
          "英文: 日付の直前に無い by は締切文脈にしない")
    check(dl("Could you reply by Friday?", date(2030, 7, 22)) == ["2030-07-26"]
          and dl("Please confirm by tomorrow.") == ["2030-07-21"], "英文: by + 曜日 / by tomorrow")
    check(dl("You may 3 times retry. Please submit.") == [], "英文: 助動詞 may を月名として読まない")
    check(dl("The meeting moved due to the storm on Aug 2. Please confirm.") == []
          and dl("Your report is due on Aug 2. Please submit it.") == ["2030-08-02"],
          "英文: due to (理由) は締切文脈にしない / due on は取る")
    check(dl("【回答期限：2030.7.29】ご回答ください。") == ["2030-07-29"] and dl("提出は 2030/8/1 までに。") == ["2030-08-01"],
          "年つき: 2030.7.29 / 2030/8/1 の形を読む")
    check(dl("特典の登録は 2031年12月31日までです。", horizon=200) == []
          and dl("The offer is open until 31st December 2031. Please register.", horizon=200) == [],
          "年つき: 書かれた年を無視して今年の日付に解かない (窓の外の年は取らない)")
    check(dl("今日まで気づいていませんでした。確認します。", action=False) == []
          and dl("明日までは不在です。", action=False) == [] and dl("これは本日までにご提出ください。") == ["2030-07-20"],
          "相対: 「まで」 は「までに」 か文末の形だけ (経過の「今日まで」 は取らない)")
    check(urgency_signals("これまでに頂いた資料です") == [] and urgency_signals("来週前半までにお願いします") == ["までに"],
          "急ぎの語: 「これまでに」 は拾わず、 日付の読めない「〜までに」 は拾う")
    check(urgency_signals("至急ご確認ください") == ["至急"] and urgency_signals("取り急ぎご連絡まで。") == []
          and urgency_signals("Re: URGENT: the deadline") == ["urgent", "deadline"],
          "急ぎの語: 至急・urgent・deadline を拾い、 結びの「取り急ぎ」 は拾わない")
    undated = "先日の件、締め切りが近いのでお早めにお願いします。"
    check(deadlines_from_body(undated, t, require_action=False) == [] and urgency_signals(undated) == ["締め切り", "お早めに"],
          "急ぎの語: 日付が取れない依頼でも語は残る (= 呼び出し側が「期限なし」 と同じに扱わないための印)")
    v = predicate_version("120")
    check(v == predicate_version("120") and v != predicate_version("7"), "指紋: 同じ述語と extra で同じ、 extra が違えば違う")
    print(f"\n==== RESULT: PASS={ok} FAIL={ng} ====")
    return 1 if ng else 0


if __name__ == "__main__":
    # 引数なしの直接実行も selftest を回す (検査の runner は lib の module を引数なしで実行する =
    # `--selftest` を渡したときだけ回す形だと、 説明を出して 0 で終わり、 回さずに緑になる)
    sys.exit(_selftest())
