#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-filevault-posture.py — 「FileVault は On なのに復旧キーが手元に無い」 を毎回見る

設計動機:
  FileVault の有効化と復旧キーの保管は **別の操作**なので、 前者だけ済んだ状態が静かに残る。
  平時は何も起きず、 気づくのは鍵が要った瞬間 = もう手遅れの瞬間。 しかも「前に確かめた」 という
  記憶は carrier にならない (実測: 有効化は一瞬で終わるので、 利用者が Off だと思っている機が
  On になっている側に倒れる)。 ∴ 実機の状態と台帳を突き合わせる検査を発火面に載せる。

  規約の正本 = conventions/macos-filevault.md (#posture-check)。
  循環しない置き場の一般則 = conventions/secret-handoff.md#do-not-store-inside-the-lock。

出力の約束 (= ここを崩さない):
  - **鍵の値を一切出力しない**。 有無・照合状態・欄の存在だけを見る (末尾数文字も出さない)。
    値を読むのは「欄が空でないか」 の判定のためだけで、 変数に取り出したまま print しない。
  - 台帳が**読めない** (暗号化されたまま / 権限が無い / 壊れている) ときは緑にせず 🟠 を出す。
    fail-open を「finding 0 件」 と見分けがつかない状態にしない。
  - `--ledger` を渡さなければ何も言わず exit 0 (= 台帳を使っていない環境の出力を汚さない opt-in)。
  - macOS 以外 / `fdesetup` が無い環境でも落ちずに silent exit 0 (= CI で緑を壊さない)。

台帳の書式 (= 実装が期待する最小形。 これ以外の行は無視するので、 人間向けの注記は自由に書ける):

    [家の機 (通称は自由)]
    hostname     : some-host          # ← 機械が「この機のブロック」 を引く key。 無いと照合の射程外
    filevault    : On                 # 任意 (人間向け)
    recovery_key : XXXX-XXXX-...      # 存在と非空だけを見る。 値は読み捨てる
    照合状態     : 照合済 2026-01-01  # 「照合済」 / "verified" を含むかだけを見る

  - ブロックの始まりは行頭の `[`。 `key : value` の区切りは最初の `:`。
  - `hostname` が無いブロックは、 header 行に hostname 文字列が含まれるかで拾う (fallback)。

使い方:

    check-filevault-posture.py --ledger PATH        # findings を print (0 件なら silent)
    check-filevault-posture.py --ledger PATH --strict   # 🔴 があれば exit 1 (CI 用)
    check-filevault-posture.py --selftest           # 内蔵 fixture で述語を検証
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

GITCRYPT_MAGIC = b"\x00GITCRYPT"
VERIFIED_RE = re.compile(r"照合済|verified", re.IGNORECASE)
KEY_FIELDS = ("recovery_key", "recoverykey", "復旧キー")
HOST_FIELDS = ("hostname", "host")


# ── 実機の状態 ────────────────────────────────────────────────────────────────
def filevault_status() -> str | None:
    """'on' / 'off' / None (= 判定できない環境)。 例外は投げない。"""
    exe = shutil.which("fdesetup")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    text = (out.stdout or "") + (out.stderr or "")
    low = text.lower()
    if "filevault is on" in low:
        return "on"
    if "filevault is off" in low:
        return "off"
    return None


def machine_names() -> list[str]:
    """この機を指しうる名前 (hostname / ComputerName)。 小文字化して返す。"""
    names: list[str] = []
    for argv in (["hostname", "-s"], ["scutil", "--get", "ComputerName"]):
        exe = shutil.which(argv[0])
        if not exe:
            continue
        try:
            out = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=10)
        except Exception:
            continue
        v = (out.stdout or "").strip()
        if v:
            names.append(v.lower())
    return names


# ── 台帳 ─────────────────────────────────────────────────────────────────────
class LedgerUnreadable(Exception):
    pass


def read_ledger_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(GITCRYPT_MAGIC):
        raise LedgerUnreadable("暗号化されたまま (git-crypt が unlock されていない)")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerUnreadable(f"text として読めない ({exc.__class__.__name__})") from exc


def parse_blocks(text: str) -> list[dict]:
    """[header] で始まるブロック列を {header, fields} に。 値は保持するが caller は print しない。"""
    blocks: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
            cur = {"header": stripped[1:-1], "fields": {}}
            blocks.append(cur)
            continue
        if cur is None or ":" not in stripped or stripped.startswith("#"):
            continue
        k, _, v = stripped.partition(":")
        key = k.strip().lower()
        if key:
            cur["fields"].setdefault(key, v.strip())
    return blocks


def _field(fields: dict, names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in fields:
            return fields[n]
    return None


def match_block(blocks: list[dict], names: list[str]) -> dict | None:
    """hostname 欄での一致を優先し、 無ければ header への部分一致で拾う。"""
    for b in blocks:
        host = _field(b["fields"], HOST_FIELDS)
        if host and host.strip().lower() in names:
            return b
    for b in blocks:
        header = b["header"].lower()
        if any(n and n in header for n in names):
            return b
    return None


# ── 述語 ─────────────────────────────────────────────────────────────────────
def evaluate(status: str | None, blocks: list[dict], names: list[str]) -> list[str]:
    """findings を返す。 値は含めない。"""
    out: list[str] = []
    block = match_block(blocks, names)

    unkeyed = [b for b in blocks if not _field(b["fields"], HOST_FIELDS)]

    if status == "on":
        if block is None and unkeyed:
            # ⚠️ 「鍵が無い」 と断定しない: hostname の無いブロックのどれかがこの機かもしれない。
            #    ここで「無い」 と言うと鍵の再発行 (= 記録済の鍵を無効化する) を誘発する。
            out.append(f"🔴 FileVault は On だが、 台帳でこの機のブロックを引けない "
                       f"(hostname 行の無いブロックが {len(unkeyed)} 件ある = そのどれかがこの機かもしれない。 "
                       "**鍵を再発行する前に**該当ブロックに hostname を書く)")
        elif block is None:
            out.append("🔴 FileVault は On だが、 この機の復旧キーが台帳に無い "
                       "(= ロックアウトされたら復旧手段が無い。 システム設定 → プライバシーとセキュリティ "
                       "→ FileVault → パスワードリセット → 復旧キー「表示」 で取れる)")
        else:
            key = _field(block["fields"], KEY_FIELDS)
            if not key:
                out.append("🔴 FileVault は On で台帳にこの機のブロックはあるが、 復旧キーの欄が空")
            elif not VERIFIED_RE.search(_field(block["fields"], ("照合状態", "verified", "status")) or ""):
                out.append("🟡 復旧キーは記録済だが未照合 "
                           "(= その機で `sudo fdesetup validaterecovery` が true を返すまで「保管済み」 ではない。 root 要 = 人の操作)")
    elif status == "off":
        if block is not None and _field(block["fields"], KEY_FIELDS):
            out.append("🟡 FileVault は Off なのに台帳にこの機の復旧キーがある "
                       "(= 無効化後の記録の残り。 ブロックを消すか、 有効化し直すかを決める)")

    if unkeyed:
        out.append(f"🟡 台帳の {len(unkeyed)} ブロックに hostname 行が無い "
                   "(= その機では照合されず、 穴が出ても黙る。 各ブロックに hostname を書く)")
    return out


# ── selftest ─────────────────────────────────────────────────────────────────
LEDGER_FIXTURE = """# comment
[this machine]
hostname     : host-a
filevault    : On
recovery_key : XXXX-XXXX
照合状態     : 未照合

[other machine]
hostname     : host-b
recovery_key : YYYY-YYYY
照合状態     : 照合済 2026-01-01

[no host key]
recovery_key : ZZZZ-ZZZZ
"""


def selftest() -> int:
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok = ok and cond

    blocks = parse_blocks(LEDGER_FIXTURE)
    check("3 blocks parsed", len(blocks) == 3)
    check("hostname match", (match_block(blocks, ["host-b"]) or {}).get("header") == "other machine")
    check("header fallback", (match_block(blocks, ["no host key"]) or {}).get("header") == "no host key")
    check("no match -> None", match_block(blocks, ["host-zzz"]) is None)

    f_on_missing = evaluate("on", blocks, ["host-zzz"])
    check("On + block 無し → 🔴", any(x.startswith("🔴") for x in f_on_missing))
    # ⚠️ hostname 無しブロックが在るときは「鍵が無い」 と断定しない (= 再発行を誘発しないため)
    check("引けない理由が hostname 欠けなら断定しない",
          any("引けない" in x for x in f_on_missing) and not any("台帳に無い" in x for x in f_on_missing))
    keyed_only = [b for b in blocks if b["header"] != "no host key"]
    check("hostname 欠けが 0 件なら「台帳に無い」 と言う",
          any("台帳に無い" in x for x in evaluate("on", keyed_only, ["host-zzz"])))
    f_on_unverified = evaluate("on", blocks, ["host-a"])
    check("On + 未照合 → 🟡", any("未照合" in x for x in f_on_unverified))
    check("On + 未照合 で 🔴 は出さない", not any(x.startswith("🔴") for x in f_on_unverified))
    f_on_verified = evaluate("on", blocks, ["host-b"])
    check("On + 照合済 → その機の finding 無し",
          not any(("未照合" in x) or x.startswith("🔴") for x in f_on_verified))
    check("hostname 欠けブロックを毎回 🟡", all(any("hostname 行が無い" in x for x in f)
                                              for f in (f_on_missing, f_on_unverified, f_on_verified)))
    f_off = evaluate("off", blocks, ["host-a"])
    check("Off + 鍵あり → 🟡 (記録の残り)", any("Off なのに" in x for x in f_off))
    check("判定不能なら機体 finding を出さない",
          not any(x.startswith("🔴") for x in evaluate(None, blocks, ["host-a"])))

    joined = " ".join(f_on_unverified + f_off + f_on_verified)
    check("値を出力しない", not any(tok in joined for tok in ("XXXX", "YYYY", "ZZZZ")))

    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="FileVault が On なのに復旧キーが台帳に無い状態を検出する")
    ap.add_argument("--ledger", help="復旧キー台帳の path (省略すると何もしない = opt-in)")
    ap.add_argument("--hostname", action="append", default=[],
                    help="この機を指す名前を明示 (既定 = hostname -s / ComputerName)")
    ap.add_argument("--strict", action="store_true", help="🔴 があれば exit 1 (CI 用)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.ledger:
        return 0

    status = filevault_status()
    if status is None:
        return 0  # macOS でない / fdesetup が無い / 判定できない → 黙る

    path = Path(args.ledger).expanduser()
    if not path.exists():
        print(f"🟠 FileVault 復旧キーの台帳が見つからない ({path}) — FileVault は {status.upper()}")
        return 0
    try:
        text = read_ledger_text(path)
    except LedgerUnreadable as exc:
        print(f"🟠 FileVault 復旧キーの台帳が読めない: {exc} — 検査できていない (緑ではない)")
        return 0
    except OSError as exc:
        print(f"🟠 FileVault 復旧キーの台帳が読めない: {exc.__class__.__name__} — 検査できていない (緑ではない)")
        return 0

    names = [h.lower() for h in args.hostname] or machine_names()
    findings = evaluate(status, parse_blocks(text), names)
    for line in findings:
        print(line)
    if args.strict and any(line.startswith("🔴") for line in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
