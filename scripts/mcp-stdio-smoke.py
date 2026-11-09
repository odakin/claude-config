#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp-stdio-smoke.py — stdio の MCP サーバを 1 回起動し、 initialize と tools/list を送って tool の一覧が返るかを確かめる。--selftest 内蔵。

用途: 依存の版上げ (Dependabot の PR など) を当てる前・当てた後に、 自前の MCP サーバが起動して tool を返すかを機械で確かめる。
  private repo で CI が実際には走らないとき、 PR に付く緑の印は何も確かめていないことがある
  (conventions/github-security-automation.md)。 lock file の変更を scratch の clone に当てて `npm ci` を回し、
  そのうえでこの道具でサーバを起動すると、 依存の import と SDK の配線までが通るかが分かる。 PR を当てる順に merge した clone で
  確かめ、 本番に当てた後は merge 後の main と試した tree が同じかを `git diff` で見る (同じなら確かめた内容がそのまま本番にある)。
  認証の情報は読まない = tool の一覧は、 多くのサーバが認証の前に返す。 一覧の前に認証の file を読むサーバでは失敗に見えるので、
  そのときは失敗の行の stderr の末尾を読む。

確かめること: 標準入力に JSON-RPC の 3 行 (initialize / notifications/initialized / tools/list) を書いて閉じ、
  標準出力から id 2 の応答を探す。 tools の数が --min-tools 以上なら exit 0。
  返らない・数が足りない・起動しない → exit 1 (stderr の末尾の行を添える)。 使い方の誤り → exit 2。

使い方:
  mcp-stdio-smoke.py <サーバの dir>                         # 既定の起動 = node server.mjs (dir の中で)
  mcp-stdio-smoke.py <サーバの dir> -- python3 server.py    # -- の後が起動の command
  mcp-stdio-smoke.py <dir> --names                          # tool の名前も出す
  mcp-stdio-smoke.py <dir> --unset-env '_CREDENTIALS_PATH$'  # 名前が正規表現に当たる環境変数を外して起動 (何度でも)
  mcp-stdio-smoke.py <dir> --timeout 30 --min-tools 3
  mcp-stdio-smoke.py --selftest

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library、 Python 3.8+)。 起動の command は PATH から探す。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

PROTOCOL_VERSION = "2025-06-18"


def _messages():
    return [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "mcp-stdio-smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]


def smoke(cwd, command, timeout=20.0, unset_env=()):
    """サーバを起動して tools/list の結果を返す。 戻り値 = (tools の list か None, stderr の末尾の行)。"""
    env = dict(os.environ)
    for pat in unset_env:
        rx = re.compile(pat)
        for k in [k for k in env if rx.search(k)]:
            env.pop(k)
    stdin_text = "\n".join(json.dumps(m) for m in _messages()) + "\n"
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
    except (OSError, ValueError) as e:
        return None, f"起動できない: {e}"
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        err = (err or "") + f"\n({timeout:g} 秒で止めた)"
    tools = None
    for line in (out or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == 2:
            result = msg.get("result")
            if isinstance(result, dict) and isinstance(result.get("tools"), list):
                tools = result["tools"]
    tail = [ln for ln in (err or "").splitlines() if ln.strip()]
    return tools, (tail[-1] if tail else "")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # 起動の command は `--` の後ろだけ (argparse の REMAINDER は dir の後の option まで command に飲み込む = 実測)
    command = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description="stdio の MCP サーバが tool の一覧を返すかを確かめる",
                                 epilog="起動の command は -- の後に書く (既定 = node server.mjs)")
    ap.add_argument("dir", nargs="?", help="サーバを起動する dir")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--min-tools", type=int, default=1)
    ap.add_argument("--names", action="store_true", help="tool の名前も出す")
    ap.add_argument("--unset-env", action="append", default=[], metavar="REGEX",
                    help="名前がこの正規表現に当たる環境変数を外して起動する (何度でも)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.dir:
        ap.error("サーバの dir を渡す")
    if not os.path.isdir(a.dir):
        print(f"{a.dir}: dir が無い", file=sys.stderr)
        return 2
    command = command or ["node", "server.mjs"]
    try:
        unset = [re.compile(p).pattern for p in a.unset_env]
    except re.error as e:
        print(f"--unset-env の正規表現が読めない: {e}", file=sys.stderr)
        return 2
    tools, tail = smoke(a.dir, command, timeout=a.timeout, unset_env=unset)
    if tools is None:
        print(f"{a.dir}: tools/list の応答が無い" + (f" — stderr: {tail}" if tail else ""))
        return 1
    print(f"{a.dir}: tools={len(tools)}")
    if a.names:
        for t in tools:
            print(f"  {t.get('name', '?')}")
    if len(tools) < a.min_tools:
        print(f"{a.dir}: tool が {a.min_tools} 本に足りない" + (f" — stderr: {tail}" if tail else ""))
        return 1
    return 0


FAKE_SERVER = r'''
import json, sys
n = int(sys.argv[1])
for line in sys.stdin:
    try:
        m = json.loads(line)
    except ValueError:
        continue
    if m.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": m["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}}), flush=True)
    elif m.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [{"name": "t%d" % i} for i in range(n)]}}), flush=True)
'''


def selftest():
    ok = True

    def check(label, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as d:
        srv = os.path.join(d, "fake_server.py")
        with open(srv, "w", encoding="utf-8") as f:
            f.write(FAKE_SERVER)
        crash = os.path.join(d, "crash.py")
        with open(crash, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.stderr.write('boom: missing module\\n')\nsys.exit(1)\n")
        py = sys.executable
        tools, _ = smoke(d, [py, srv, "3"])
        check("3 本の tool を返すサーバ → 3 本", tools is not None and len(tools) == 3)
        check("main: 3 本 → exit 0", main([d, "--", py, srv, "3"]) == 0)
        check("main: dir の後の option は command に入らない",
              main([d, "--unset-env", "X_PATH$", "--min-tools", "3", "--", py, srv, "3"]) == 0)
        check("main: --min-tools が dir の後でも効く", main([d, "--min-tools", "4", "--", py, srv, "3"]) == 1)
        check("main: 0 本で --min-tools 1 → exit 1", main([d, "--", py, srv, "0"]) == 1)
        tools, tail = smoke(d, [py, crash])
        check("起動してすぐ落ちる → 応答なし + stderr の末尾", tools is None and "boom" in tail)
        check("main: 落ちるサーバ → exit 1", main([d, "--", py, crash]) == 1)
        tools, tail = smoke(d, [os.path.join(d, "no-such-binary")])
        check("起動できない command → 応答なし", tools is None and tail.startswith("起動できない"))
        os.environ["SMOKE_TEST_SECRET_PATH"] = "x"
        envdump = os.path.join(d, "envdump.py")
        with open(envdump, "w", encoding="utf-8") as f:
            f.write(FAKE_SERVER.replace("n = int(sys.argv[1])", "import os\nn = 0 if 'SMOKE_TEST_SECRET_PATH' in os.environ else 2"))
        tools, _ = smoke(d, [py, envdump], unset_env=[r"SECRET_PATH$"])
        check("--unset-env で外した変数は子に渡らない", tools is not None and len(tools) == 2)
        os.environ.pop("SMOKE_TEST_SECRET_PATH", None)
        check("main: 無い dir → exit 2", main([os.path.join(d, "nope")]) == 2)
    print("selftest:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
