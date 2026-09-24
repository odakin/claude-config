"""Claude Code の設定フォルダ (CLAUDE_CONFIG_DIR) の認証が切れているかを、 `claude` を呼ばずに読む共有判定。

使い手 = scripts/check-desktop-logout-auth.py (問い合わせを打ち、 そのマシンで 🔴) と
scripts/fleet-heartbeat.py (判定を beat に載せ、 他のマシンの check-fleet-status.py が 🔴)。
heartbeat は `claude` を呼ばない設計なので (監視が監視対象と共倒れしないため)、 ここも `security` と file しか読まない。

述語 (= code-as-SoT):
  - keychain の項目 = KEYCHAIN_PREFIX + sha256(設定フォルダの path) の先頭 8 桁 (実測で一致)。 更新時刻 (mdat) は
    `security find-generic-password -s <項目>` の属性だけを読む (値は読まない)。 トークンの更新やログインが
    成功すると mdat が進む
  - 問い合わせの記録 (LEDGER、 1 行 = 時刻 TAB tag TAB フォルダ TAB ok|FAIL(...) TAB ...) は
    check-desktop-logout-auth.py --probe が書く
  - 切れた (dead) = そのフォルダの最後の問い合わせが失敗 ∧ その後に keychain が更新されていない
    (= ログインし直していない、 更新も成功していない)。 問い合わせが無い・keychain が読めないなら判定しない
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import subprocess
import time
from pathlib import Path

KEYCHAIN_PREFIX = "Claude Code-credentials-"
LEDGER = Path.home() / ".claude" / "state" / "desktop-logout-probe.log"
_MDAT_RE = re.compile(r'"mdat"<timedate>=0x[0-9A-F]*\s+"(\d{14})Z')


def keychain_service(config_dir: str) -> str:
    return KEYCHAIN_PREFIX + hashlib.sha256(config_dir.encode()).hexdigest()[:8]


def keychain_mdat(service: str) -> float | None:
    """keychain 項目の更新時刻 (epoch)。 属性だけ読む。 無い・読めない・security が無いなら None。"""
    try:
        cp = subprocess.run(["security", "find-generic-password", "-s", service],
                            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = _MDAT_RE.search(cp.stdout + cp.stderr)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()


def read_ledger(ledger: Path = LEDGER) -> list[dict]:
    """問い合わせの記録。 読めない行は飛ばす。 各要素 = {t, tag, dir, ok}。"""
    rows = []
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            t = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        rows.append({"t": t, "tag": parts[1], "dir": parts[2], "ok": parts[3] == "ok"})
    return rows


def last_probe(rows: list[dict], config_dir: str) -> dict | None:
    mine = [r for r in rows if r["dir"] == config_dir]
    return max(mine, key=lambda r: r["t"]) if mine else None


def is_dead(rows: list[dict], config_dir: str, mdat: float | None) -> dict | None:
    """切れていれば最後の (失敗した) 問い合わせ、 そうでなければ None。"""
    r = last_probe(rows, config_dir)
    if r is None or r["ok"]:
        return None
    if mdat is not None and mdat > r["t"]:
        return None  # 失敗の後にログインし直した / 更新が成功した
    return r


def selftest() -> int:
    fails = 0

    def ck(name, cond):
        nonlocal fails
        print(("  PASS  " if cond else "  FAIL  ") + name)
        fails += not cond

    d = "~/.claude-acct"
    rows = [{"t": 100.0, "tag": "a", "dir": d, "ok": True}, {"t": 200.0, "tag": "b", "dir": d, "ok": False},
            {"t": 150.0, "tag": "c", "dir": "~/.claude-other", "ok": False}]
    ck("最後の問い合わせが失敗 ∧ その後の更新なし = 切れた", is_dead(rows, d, 150.0)["tag"] == "b")
    ck("失敗の後に keychain が更新された = 切れていない (ログインし直した)", is_dead(rows, d, 250.0) is None)
    ck("keychain が読めなくても失敗は切れたと数える", is_dead(rows, d, None) is not None)
    ck("最後が成功なら切れていない", is_dead(rows + [{"t": 300.0, "tag": "d", "dir": d, "ok": True}], d, 150.0) is None)
    ck("問い合わせの無いフォルダは判定しない", is_dead(rows, "~/.claude-none", 0.0) is None)
    ck("keychain 項目名 = sha256(path) の先頭 8 桁",
       keychain_service(d) == KEYCHAIN_PREFIX + hashlib.sha256(d.encode()).hexdigest()[:8])
    ck("mdat の属性を UTC として読む", _MDAT_RE.search('"mdat"<timedate>=0x32303236  "20260923034324Z\\000"') is not None)
    print(f"config_dir_auth selftest: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
