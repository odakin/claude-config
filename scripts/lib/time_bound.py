#!/usr/bin/env python3
"""time_bound.py — 道具の --since / --until の値を日付か日時の先頭だけに絞り、 記録の時刻とは境界と同じ長さの先頭で比べる共通規則 (形の違う値で黙って 0 件・全件にしない)。--selftest。

記録の時刻を文字列のまま境界と比べると、 形の違う境界が error にならずに結果を変える (実測):
日時を渡すと日付の先頭 10 文字との比較で境界の日が丸ごと落ちる、 空白や `/` の区切り・日本語の日付を
渡すと全件が範囲の外に落ちるか、 範囲が消えて全件になる。 どれも「0 件 = 無い」 と読まれる。

  bound(value)      argparse の type。 YYYY-MM-DD か YYYY-MM-DDTHH[:MM[:SS]] だけを通す (空白の区切りは T に直す)。
                    それ以外の形は ArgumentTypeError = 道具が usage の error で止まる。
  bound_utc(value)  記録が UTC の道具の type。 bound に加えて末尾の Z (UTC の印) を受けて落とす。
                    時刻帯 (+09:00 など) は受けない = 換算しないまま比べて黙ってずれるより止める。
  head(ts, b)       記録の時刻の、 境界 b と同じ長さの先頭 (日付と時刻の間の空白は T とみなす)。
  out_of_range(ts, since, until)
                    head で比べて範囲の外か (両端を含む)。 時刻の無い記録は、 境界があれば外。
  git_since(b)      `git log --since` に渡す形。 git は時刻の無い日付をその日の今の時刻と読み、
                    その日の朝の commit を黙って落とす (実測) ので、 日付だけなら T00:00:00 を足す。

時刻帯は換算しない = 境界は記録の時刻と同じ時刻帯で渡す (どの時刻帯かは各道具の help に書く)。
"""
from __future__ import annotations

import argparse
import re

_BOUND_RE = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}(:\d{2}(:\d{2})?)?)?")
FORMS = "YYYY-MM-DD か YYYY-MM-DDTHH[:MM[:SS]]"


def bound(value: str) -> str:
    v = value.strip().replace(" ", "T", 1)
    if not _BOUND_RE.fullmatch(v):
        raise argparse.ArgumentTypeError(f"{value!r}: {FORMS} で渡す")
    return v


def bound_utc(value: str) -> str:
    v = value.strip()
    try:
        return bound(v[:-1] if v.endswith("Z") else v)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(f"{value!r}: UTC の {FORMS} (末尾の Z は付けてもよい) で渡す") from None


def head(ts: str, b: str) -> str:
    h = (ts or "")[:len(b)]
    return h[:10] + "T" + h[11:] if len(h) > 10 and h[10] == " " else h


def out_of_range(ts: str, since: str | None, until: str | None) -> bool:
    return bool((since and head(ts, since) < since) or (until and head(ts, until) > until))


def git_since(b: str) -> str:
    return b + "T00:00:00" if len(b) == 10 else b


def selftest() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name)
        ok = ok and bool(cond)

    def rejects(f, v: str) -> bool:
        try:
            f(v)
        except argparse.ArgumentTypeError:
            return True
        return False

    check("日付と日時の先頭を通す", [bound(x) for x in ("2030-01-02", "2030-01-02T10", "2030-01-02T10:59", "2030-01-02T10:59:07")]
          == ["2030-01-02", "2030-01-02T10", "2030-01-02T10:59", "2030-01-02T10:59:07"])
    check("空白の区切りは T に直す", bound(" 2030-01-02 10:59 ") == "2030-01-02T10:59")
    check("形の違う値は error (/ の区切り・日本語・時刻帯・Z・秒の小数)",
          all(rejects(bound, x) for x in ("2030/01/02", "1月2日", "2030年1月2日", "2030-01-02T10:59+09:00",
                                          "2030-01-02T10:59Z", "2030-01-02T10:59:07.5", "2030-01-02T", "")))
    check("bound_utc は末尾の Z だけを落とし、 時刻帯は止める",
          bound_utc("2030-01-02T10:59:00Z") == "2030-01-02T10:59:00" and rejects(bound_utc, "2030-01-02T10:59+00:00"))
    ts = "2030-01-02T10:59:30.123Z"
    check("日時の境界でもその日の記録を落とさない (先頭 10 文字との比較で落ちた形)",
          not out_of_range(ts, "2030-01-02T10:59", None) and not out_of_range(ts, "2030-01-02", "2030-01-02"))
    check("境界の分を含み、 次の分は外", not out_of_range(ts, None, "2030-01-02T10:59") and out_of_range(ts, "2030-01-02T11", None))
    check("記録の空白の区切りも T とみなす (git の reflog の形)",
          not out_of_range("2030-01-03 04:05:06 +0900", "2030-01-03T04:05", None)
          and out_of_range("2030-01-03 04:05:06 +0900", "2030-01-03T04:06", None))
    check("時刻の無い記録は、 境界があれば外・無ければ内", out_of_range("", "2026-01-01", None) and not out_of_range("", None, None))
    check("git_since は日付だけなら 0 時を足す", git_since("2030-01-02") == "2030-01-02T00:00:00"
          and git_since("2030-01-02T10:59") == "2030-01-02T10:59")
    print("time_bound selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    if not ap.parse_args().selftest:
        ap.error("use --selftest; import this module from a tool's argparse")
    raise SystemExit(selftest())
