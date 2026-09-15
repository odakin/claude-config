"""ja_deadline_dates.py — 日本語の散文 (task 記録・メモ) から「期限らしい日付」 を取る共通部品（締切語が隣接 ∧ 済/完了 が隣接しない日付だけ。 窓は隣の日付で切る = 隣の項目の〆や済を誤帰属しない。 docs/convention-design-principles.md#single-deadline-field-many-legs、 --selftest）

使い方:
    from ja_deadline_dates import nearest_prose_deadline, prose_deadline_dates
    nearest_prose_deadline(text, today, base, window=14)   # today..today+window の最早 (無ければ None)
    prose_deadline_dates(text, base)                        # 期限らしい日付の全件 [(date, 文脈)]

年の無い日付 (`3/20` / `3月20日`) は base (= 記録を書いた日) 以降で最も近い日に解く。
散文の heuristic なので、 **結果は表示の並べ替えや候補の提示に使い、 それだけで自動処分しない**。
呼び出し側は import 失敗を含めて fail-open にする (= 取れなければ従来の期限欄のまま)。
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta

DATE_RE = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/.])|(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 締切語。 散文では「〆」 単独や「申請」「応募」 が期限の印になる (メール本文の抽出語彙とは別に持つ)
CTX_RE = re.compile(r"(〆|締切|締め切り|期限|期日|まで|応募|提出|申込|申請)")
DONE_RE = re.compile(r"(✅|済|完了)")
_ZEN = str.maketrans("０１２３４５６７８９／", "0123456789/")
PRE_CHARS, POST_CHARS, DONE_CHARS = 10, 8, 12


def _resolve(mo: int, dy: int, base: date) -> date | None:
    for y in (base.year, base.year + 1):
        try:
            cand = date(y, mo, dy)
        except ValueError:
            return None
        if cand >= base:
            return cand
    return None


def prose_deadline_dates(text: str, base: date) -> list[tuple[date, str]]:
    """期限らしい日付の全件 (出現順)。 締切語が隣接 ∧ 済/完了 が隣接しない日付だけ。"""
    t = str(text or "").translate(_ZEN)
    ms = list(DATE_RE.finditer(t))
    out: list[tuple[date, str]] = []
    lo = 0
    for i, m in enumerate(ms):
        mo, dy = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        hi = ms[i + 1].start() if i + 1 < len(ms) else len(t)
        near = t[max(lo, m.start() - PRE_CHARS): min(hi, m.end() + POST_CHARS)]
        done_near = t[max(lo, m.start() - DONE_CHARS): min(hi, m.end() + DONE_CHARS)]
        gap = len(t[m.end():]) - len(t[m.end():].lstrip(" 　"))
        tail = CTX_RE.match(t, m.end() + gap)
        lo = tail.end() if tail else m.end()  # 日付の直後に付いた締切語はその日付のもの
        if not CTX_RE.search(near) or DONE_RE.search(done_near):
            continue
        d = _resolve(int(mo), int(dy), base)
        if d is not None:
            out.append((d, near.replace("\n", " ").strip()))
    return out


def nearest_prose_deadline(text: str, today: date, base: date, window: int = 14) -> date | None:
    """today..today+window に入る期限らしい日付の最早。 無ければ None。"""
    cands = [d for d, _ in prose_deadline_dates(text, base) if today <= d <= today + timedelta(days=window)]
    return min(cands) if cands else None


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

    base, today = date(2030, 2, 1), date(2030, 3, 10)
    legs = ("① 要旨 2/20〆 → ② 手続き 2/28 提出 → ③ 登録 (窓 3/1-31) 〔✅ 3/10 支払済〕 → ④ 学内助成\n"
            "応募 3/15〆。 条件 = 3/12 の会議で承認")
    check(nearest_prose_deadline(legs, today, base) == date(2030, 3, 15),
          "4 項目の散文: 過去の項目・済の項目・締切語の無い日付を除いて次の期限を取る")
    check(nearest_prose_deadline("報告書は 3/20 提出済", today, base) is None, "済 が隣接する日付は取らない")
    check(nearest_prose_deadline("✅ 提出済 3/20", today, base) is None, "済 が前にあっても取らない")
    check(nearest_prose_deadline("次回は 4/30〆", today, base) is None, "窓より先は取らない")
    check(nearest_prose_deadline("3/15〆。 条件 = 3/12 会議", today, base) == date(2030, 3, 15),
          "隣の日付の直後の〆を次の日付のものと読まない (3/12 は取らない)")
    check(nearest_prose_deadline("（〆 3/13）は別の窓口", today, base) == date(2030, 3, 13), "締切語が前にある形")
    check(nearest_prose_deadline("３月１４日（金）までに", today, base) == date(2030, 3, 14), "全角数字と月日表記")
    check(nearest_prose_deadline("12/25〆", date(2030, 12, 20), date(2030, 11, 1)) == date(2030, 12, 25), "年の解決は base 以降")
    check(prose_deadline_dates("", base) == [], "空文字は空")
    print(f"\n==== RESULT: PASS={ok} FAIL={ng} ====")
    return 1 if ng else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
