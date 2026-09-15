"""ja_deadline_dates.py — 日本語の文から「期限らしい日付」 を取る共通部品（散文 = task 記録・メモの次の期限 / メール本文 = 入力・提出・申請の〆切。 締切語の隣接・行動語・行動窓の範囲の終端・引用除去・述語の指紋。 docs/convention-design-principles.md#single-deadline-field-many-legs / #elapsed-time-urgency-inversion、 --selftest）

使い方 (散文 = 記録の本文から次の期限):
    nearest_prose_deadline(text, today, base, window=14)   # today..today+window の最早 (無ければ None)
    prose_deadline_dates(text, base)                        # 期限らしい日付の全件 [(date, 文脈)]

使い方 (メール本文 = 受信者の行動が要る〆切):
    extract_input_deadlines(body, today, horizon_days=7)    # [{"date", "time", "context", "kind"}]
    deadlines_from_body(body, received, horizon_days=120)    # 引用を落として日付だけの昇順 list
    strip_quoted(body)                                       # 返信の引用部を落とす (転送本文は残す)
    predicate_version(*extra)                                # 抽出述語の指紋 (cache の鮮度判定用)

2 つを分けている理由: 散文は「〆」 単独・「申請」「応募」 が期限の印になり、 済/完了 の記号で終わった項目を除く必要がある。
メール本文は締切語だけでは一般の期限の言及 (工事は M/D まで 等) を拾うので、 **締切語 ∧ 行動語 (またはフォーム URL)** の 2 条件にする。
⚠️ 2 条件の語彙に同じ語を入れない (= その語 1 つで関門を通る。 例: 「応募」 は締切語側だけ)。 語彙を変えたら predicate_version が変わる。

年の無い日付は基準日 (散文 = 記録を書いた日 / メール = 受信日) 以降で最も近い日に解く。
heuristic なので、 **結果は表示の並べ替え・印・候補の提示に使い、 それだけで自動処分しない**。 呼び出し側は import 失敗を含めて fail-open にする。
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------
DATE_JA_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")                 # 「6月10日」 (全角は正規化後)
DATE_SLASH_RE = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/.])")    # 「6/10」
ZEN2HAN = str.maketrans("０１２３４５６７８９：／～〜", "0123456789:/~~")


def normalize_text(s: str) -> str:
    """全角数字・コロン・スラッシュ・波ダッシュを半角に揃える。"""
    return (s or "").translate(ZEN2HAN)


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


def is_period_range_end(text: str, m: re.Match) -> bool:
    """日付 match m が「<行動窓の label> … 日付A ～ 日付B」 の B なら True (正規化済み text 前提)。"""
    base = max(0, m.start() - 40)
    rm = RANGE_TAIL_RE.search(text[base: m.start()])
    if not rm:
        return False
    range_start = base + rm.start()
    return bool(PERIOD_LABEL_RE.search(text[max(0, range_start - 40): range_start]))


def extract_input_deadlines(body: str, today: date, horizon_days: int = 7) -> list[dict]:
    """本文から受信者の行動が要る〆切を抽出する純関数。

    条件 = 日付が today..today+horizon ∧ (締切語が後方 12 字 / 前方 16 字 ∨ 行動窓の範囲の終端)
         ∧ (前後 60 字に行動語 ∨ 本文にフォーム URL)。 同じ日付は 1 件。"""
    text = normalize_text(body)
    has_form_url = bool(FORM_URL_RE.search(text))
    out: list[dict] = []
    seen: set[str] = set()

    def consider(m: re.Match, month: int, day: int):
        d = resolve_year(month, day, today)
        if d is None or not (today <= d <= today + timedelta(days=horizon_days)):
            return
        if not (DEADLINE_CTX_RE.search(text[m.end(): m.end() + 12])
                or DEADLINE_CTX_RE.search(text[max(0, m.start() - 16): m.start()])
                or is_period_range_end(text, m)):
            return  # 締切文脈なし = 予定の日付
        pre = text[max(0, m.start() - 60): m.start()]
        post = text[m.end(): m.end() + 60]
        if not (has_form_url or INPUT_ACTION_RE.search(pre) or INPUT_ACTION_RE.search(post)):
            return  # 行動の証拠なし = 一般の期限の言及
        if d.isoformat() in seen:
            return
        seen.add(d.isoformat())
        ctx = (pre[-25:] + text[m.start(): m.end()] + post[:35]).replace("\n", " ").strip()
        out.append({"date": d.isoformat(), "time": None, "context": ctx, "kind": "input-deadline"})

    for m in DATE_JA_RE.finditer(text):
        consider(m, int(m.group(1)), int(m.group(2)))
    for m in DATE_SLASH_RE.finditer(text):
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            consider(m, mo, dy)
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


def deadlines_from_body(body: str, received: date, horizon_days: int = 120) -> list[str]:
    """引用を除いた本文の〆切を ISO 日付の昇順 list で返す純関数。 取れなければ []。"""
    try:
        found = extract_input_deadlines(strip_quoted(body), received, horizon_days)
    except Exception:
        return []
    return sorted({d["date"] for d in found})


def predicate_version(*extra: str) -> str:
    """メール本文の抽出述語 (正規表現と引用ヘッダ) の指紋。 cache に持たせ、 違えば捨てる (= 手で上げる版番号を持たない)。
    呼び出し側の窓の幅など、 結果を変える値は extra に渡す。"""
    parts = [r.pattern for r in (DATE_JA_RE, DATE_SLASH_RE, DEADLINE_CTX_RE, INPUT_ACTION_RE, FORM_URL_RE,
                                 PERIOD_LABEL_RE, RANGE_TAIL_RE, REPLY_HEADER_RE)]
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
    check(nearest_prose_deadline("12/25〆", date(2030, 12, 20), date(2030, 11, 1)) == date(2030, 12, 25), "散文: 年の解決は base 以降")
    check(prose_deadline_dates("", base) == [], "散文: 空文字は空")

    # --- メール本文 (合成データ) ---
    t = date(2030, 7, 20)
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
    v = predicate_version("120")
    check(v == predicate_version("120") and v != predicate_version("7"), "指紋: 同じ述語と extra で同じ、 extra が違えば違う")
    print(f"\n==== RESULT: PASS={ok} FAIL={ng} ====")
    return 1 if ng else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
