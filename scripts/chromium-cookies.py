#!/usr/bin/env python3
"""chromium-cookies.py — macOS の Chromium 系 browser (Brave / Chrome) の cookie を復号して取り出す。

用途: user が browser で login 済みの web app (SSO 保護の groupware 等) に、 **画面 drive でなく
script から** session cookie 付きで HTTP を撃つための入口 (= machine-route-first.md #wiring-gap-is-a-task
の「API 的な自動接続」 の最小部品)。 password や token を新たに発行できない環境 (SAML-only で
API password auth が admin 限定、 OAuth client も admin 登録要) で、 browser session を再利用する。

機構 (Chromium on macOS):
  - cookie DB = `<profile>/Cookies` (sqlite、 browser 稼働中は lock されるので **copy してから読む**)
  - `encrypted_value` は `v10` prefix + AES-128-CBC。 key = PBKDF2-HMAC-SHA1(
      password = Keychain generic password "<Browser> Safe Storage", salt = b"saltysalt",
      iterations = 1003, dklen = 16)、 IV = b" " * 16。
  - Chromium 130+ は平文の先頭 32 byte に host_key の SHA-256 が付く → 剥がす (= 旧版は付かないので
    復号後に「先頭 32 byte を剥がすと printable になる」 で判定)。
  - Keychain 読み出し = `security find-generic-password -w -s "<Browser> Safe Storage"`。
    **初回は macOS の Keychain 許可 dialog が出る** (= user が「常に許可」 を押せば以後 silent)。
    これは認証境界 = user 専権、 script は代行しない。

使い方:
  python3 chromium-cookies.py --browser brave --domain cybozu.com            # name=value 一覧 (値は表示)
  python3 chromium-cookies.py --browser brave --domain cybozu.com --format header   # "Cookie:" header 1 行
  python3 chromium-cookies.py --browser brave --domain cybozu.com --format json
  --domain は suffix match (host_key が ".cybozu.com" / "<org>.cybozu.com" 両方 hit)。 複数指定可。
  --names JSESSIONID,CB_LOCALE で絞り込み。

Python から:
  from chromium_cookies import load_cookies   # (= 本 file を module として import、 hyphen なので importlib)
  jar = load_cookies("brave", ["cybozu.com"])  # -> {name: value}

⚠️ 値は secret (= session hijack 可能)。 chat / log / commit に貼らない。 出力は pipe して使う。
⚠️ session cookie の寿命は browser 側の login に従う (SAML session が切れたら user が browser で
   再 login = 1 手)。 script 側は 401/302→login page を検知して「再 login 要」 と言うだけ。
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BROWSERS = {
    "brave": ("~/Library/Application Support/BraveSoftware/Brave-Browser", "Brave Safe Storage", "Brave"),
    "chrome": ("~/Library/Application Support/Google/Chrome", "Chrome Safe Storage", "Chrome"),
    "chromium": ("~/Library/Application Support/Chromium", "Chromium Safe Storage", "Chromium"),
}


def _keychain_password(service: str, account: str) -> bytes:
    out = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", service, "-a", account],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"Keychain '{service}' を読めない (rc={out.returncode}): {out.stderr.strip()}\n"
                         "→ dialog で「許可」/「常に許可」 を押したか確認。 CLI 経由なら Terminal に Keychain 権限が要る。")
    return out.stdout.strip().encode()


def _derive_key(password: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, dklen=16)


def _decrypt(enc: bytes, key: bytes, host_key: str) -> str:
    if not enc:
        return ""
    if enc[:3] not in (b"v10", b"v11"):
        return enc.decode("utf-8", "replace")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # lazy import
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
    dec = cipher.decryptor()
    raw = dec.update(enc[3:]) + dec.finalize()
    raw = raw[: -raw[-1]]  # PKCS#7
    # Chromium 130+: SHA-256(host_key) prefix
    if len(raw) >= 32 and raw[:32] == hashlib.sha256(host_key.encode()).digest():
        raw = raw[32:]
    return raw.decode("utf-8", "replace")


def load_cookies(browser: str, domains, profile: str = "Default", names=None) -> dict:
    base, service, account = BROWSERS[browser]
    db = Path(base).expanduser() / profile / "Cookies"
    if not db.exists():
        raise SystemExit(f"cookie DB が無い: {db}")
    key = _derive_key(_keychain_password(service, account))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "Cookies"
        shutil.copy2(db, tmp)
        con = sqlite3.connect(str(tmp))
        rows = con.execute("select host_key, name, encrypted_value, value from cookies").fetchall()
        con.close()
    out = {}
    for host_key, name, enc, value in rows:
        h = host_key.lstrip(".")
        if not any(h == d or h.endswith("." + d) for d in domains):
            continue
        if names and name not in names:
            continue
        out[name] = value or _decrypt(enc, key, host_key)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--browser", choices=BROWSERS, default="brave")
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--domain", action="append", required=True, help="suffix match、 複数可")
    ap.add_argument("--names", help="comma 区切りで cookie 名を絞る")
    ap.add_argument("--format", choices=["lines", "header", "json"], default="lines")
    a = ap.parse_args()
    names = set(a.names.split(",")) if a.names else None
    jar = load_cookies(a.browser, a.domain, a.profile, names)
    if not jar:
        print("(該当 cookie なし = browser で未 login か domain 違い)", file=sys.stderr)
        sys.exit(2)
    if a.format == "json":
        print(json.dumps(jar, ensure_ascii=False))
    elif a.format == "header":
        print("Cookie: " + "; ".join(f"{k}={v}" for k, v in jar.items()))
    else:
        for k, v in jar.items():
            print(f"{k}={v}")


if __name__ == "__main__":
    main()
