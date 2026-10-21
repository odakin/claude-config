#!/usr/bin/env python3
"""codex-app-launch.py — Codex の仕事を Codex アプリの一覧に出る形で起こす (手元の共有 app-server daemon に thread を作り、 アプリに開かせる)。

Why (実測、 CLI 0.159.2 / アプリ 26.928): `codex exec` で起こした仕事は Codex アプリのどこにも出ない。 exec の thread は
状態 DB に source=exec で記録され、 アプリの一覧 (thread/list の既定 = 対話の種類だけ) から外れる。 アプリは自分の
app-server (stdio) と cloud 側の host を使い、 外の process は前者に繋げない。 一方 CLI は手元に共有の app-server daemon
(`codex app-server daemon`、 unix socket の上の websocket で JSON-RPC) を持ち、 そこに作った thread は source=vscode
(対話の種類) で同じ状態 DB に入る。 アプリに `codex://threads/<id>?hostId=local` を開かせると、 その thread を表示し、
左の「最近の項目」 に載る。 開かせないと一覧に載らなかった (1 分半後の観察)。

限界 (実測): daemon が thread を動かしている間、 アプリはその thread を「別のアプリで開いています」 と出し、 進行を
表示せず、 そこから話しかけられない (writer lock が daemon にある)。 turn が終わって誰も見ていなければ daemon は
30〜45 秒で thread を手放し、 その後はアプリで開いて続けられる。 走っている間の進行を見るのは TUI (`codex resume <id>`
/ `codex agents`、 どちらも同じ daemon に繋ぐ) の役。 model と effort は thread/start と turn/start で固定し、
応答と状態 DB で読み戻す。

subcommand:
  start --cwd DIR --prompt-file FILE [--model M] [--effort E] [--sandbox MODE] [--approval POLICY] [--network]
        [--writable-root DIR]... [--name TITLE] [--host HOST] [--sealed] [--no-reveal] [--record FILE] [--json]
      daemon を確かめ (無ければ `codex app-server daemon start`)、 thread を作って最初の turn を始め、 アプリに開かせる。
      --host: この機械の名前と違えば何もせず止める (別の機械で起こす仕事を先に起こさない)。
      --sealed: 盲検の封じた sandbox 用。 本番の前に保存しない thread (ephemeral) を同じ設定で作り、 応答の
        instructionSources (Codex が読む指示 file) に cwd の外の file があれば止める (global の ~/.codex/AGENTS.md
        だけは sandbox から切れない残余として通し、 申告する)。 封じた sandbox では writer を止めない reveal も同じ。
      --record: 掲示板の launch 記録 (json) に thread id・機械・時刻を書き足す。
      daemon に繋がらなければ、 アプリの新規 thread の入力欄に起動文を入れて開く deep link
      (`codex://threads/new?path=…&prompt=…`、 本人が送信を押す) を出して exit 4。
  continue --thread ID --prompt-file FILE [--effort E] [--host HOST] [--no-reveal]
      既存の thread に次の turn を送る (盲検の訂正版の 2 回目を同じ reviewer に返す = `codex exec resume` の代わり)。
      アプリがその thread を開いて書き手になっている間は daemon が開けない = アプリで続けるか、 アプリで閉じてから。
  check-self --model M [--effort E]
      worker の 0 段目: 自分の thread ($CODEX_THREAD_ID) の model と effort を状態 DB で読み、 違えば exit 1。
  compose-link --cwd DIR --prompt-file FILE
      本人が押す形の deep link だけを出す (daemon を使わない)。
  --selftest

規約 = ai-collaboration board/CONTRACT.md#codex-worker-launch、 headless の codex exec を止める hook =
hooks/codex-headless-launch-check.sh。 状態 DB と socket の配置は未文書の手元の layout = 読めなければ「分からない」 を返す。
env: CODEX_CLI_PATH (CLI の path) / CODEX_HOME / CODEX_APP_LAUNCH_SOCKET (test: daemon の socket) /
     CODEX_APP_LAUNCH_HOSTNAME (test: この機械の名前) / CODEX_APP_LAUNCH_NO_OPEN=1 (test: アプリを開かない)。
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
try:
    import codex_threads as ct  # noqa: E402
except Exception:  # pragma: no cover - partial checkout
    ct = None

CLIENT = {"name": "codex-app-launch", "title": "codex-app-launch", "version": "1"}
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
RULE = "ai-collaboration/board/CONTRACT.md#codex-worker-launch"


# ---------------------------------------------------------------- websocket (stdlib, client side only)

class WS:
    """JSON-RPC over websocket on a unix socket (the daemon's control socket speaks HTTP upgrade + websocket frames)."""

    def __init__(self, path: str, timeout: float = 30.0, sock=None):
        self.s = sock or socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if sock is None:
            self.s.settimeout(timeout)
            self.s.connect(path)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = self.s.recv(4096)
            if not d:
                raise ConnectionError("daemon closed during the handshake")
            buf += d
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise ConnectionError("no websocket upgrade: " + head.split(b"\r\n")[0].decode("utf-8", "replace"))
        self.n = 0
        self.notes: list[dict] = []

    def _take(self, n: int) -> bytes:
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d:
                raise EOFError("daemon closed the connection")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, op: int, data: bytes) -> bytes:
        mask = os.urandom(4)
        n = len(data)
        hdr = bytes([0x80 | op])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        return hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))

    def send(self, obj: dict) -> None:
        self.s.sendall(self._frame(0x1, json.dumps(obj).encode()))

    def recv(self) -> dict:
        msg = b""
        while True:
            b0, b1 = self._take(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._take(8))[0]
            mask = self._take(4) if b1 & 0x80 else None
            data = self._take(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 0x9:
                self.s.sendall(self._frame(0xA, data))
                continue
            if op == 0x8:
                raise EOFError("daemon closed the connection")
            if op in (0xA,):
                continue
            msg += data
            if b0 & 0x80:
                return json.loads(msg)

    def call(self, method: str, params: dict, timeout: float = 60.0) -> dict:
        self.n += 1
        rid = self.n
        self.send({"id": rid, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            m = self.recv()
            if m.get("id") == rid and ("result" in m or "error" in m):
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error'].get('message') or m['error']}")
                return m["result"]
            self.notes.append(m)
        raise TimeoutError(method)

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


# ---------------------------------------------------------------- machine, daemon, app

def this_host_names() -> set[str]:
    forced = os.environ.get("CODEX_APP_LAUNCH_HOSTNAME")
    names = {forced} if forced else set()
    if not forced:
        names.add(socket.gethostname())
        for args in (["scutil", "--get", "LocalHostName"], ["scutil", "--get", "ComputerName"], ["hostname", "-s"]):
            try:
                out = subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
            except Exception:
                out = ""
            if out:
                names.add(out)
    return {norm_host(n) for n in names if n}


def short_host() -> str:
    """This machine's name as the board writes it (`hostname` up to the first dot)."""
    return os.environ.get("CODEX_APP_LAUNCH_HOSTNAME") or socket.gethostname().split(".")[0]


def norm_host(name: str) -> str:
    n = (name or "").strip().lower()
    for suffix in (".local", ".lan"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.split("@")[-1]


def host_mismatch(want: str | None) -> str | None:
    """None when this machine is the one named (or none was named), else the message to stop with."""
    if not want:
        return None
    here = this_host_names()
    if norm_host(want) in here:
        return None
    return (f"この仕事は {want} で起こす依頼 (この機械 = {', '.join(sorted(here))})。 ここでは起こさない: {want} の session が"
            " 掲示板の依頼を読んで起こす")


def codex_cli() -> str | None:
    if ct is not None:
        return ct.codex_binary()
    return os.environ.get("CODEX_CLI_PATH")


def daemon_socket(start: bool = True) -> str | None:
    """The shared daemon's control socket path (starts the daemon when asked and it is not running)."""
    forced = os.environ.get("CODEX_APP_LAUNCH_SOCKET")
    if forced:
        return forced
    cli = codex_cli()
    if not cli:
        return None
    if start:
        try:
            subprocess.run([cli, "app-server", "daemon", "start"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        except Exception:
            pass
    try:
        out = subprocess.run([cli, "app-server", "daemon", "version"], capture_output=True, text=True, timeout=30,
                             stdin=subprocess.DEVNULL).stdout
        info = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return None
    path = info.get("socketPath")
    if info.get("status") != "running" or not path:
        return None
    return os.path.realpath(path)


def reveal_url(thread_id: str) -> str:
    return f"codex://threads/{thread_id}?hostId=local"


def compose_url(cwd: str, prompt: str) -> str:
    return "codex://threads/new?" + urllib.parse.urlencode({"path": cwd, "prompt": prompt}, quote_via=urllib.parse.quote)


def open_in_app(url: str) -> bool:
    if os.environ.get("CODEX_APP_LAUNCH_NO_OPEN") == "1" or sys.platform != "darwin":
        return False
    try:
        return subprocess.run(["open", url], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------- launch

def thread_params(cwd: str, model: str | None, effort: str | None, sandbox: str, approval: str, network: bool,
                  ephemeral: bool = False, writable: list[str] | None = None) -> dict:
    cfg: dict = {}
    if effort:
        cfg["model_reasoning_effort"] = effort
    sww: dict = {}
    if network and sandbox == "workspace-write":
        sww["network_access"] = True
    if writable and sandbox == "workspace-write":
        sww["writable_roots"] = [os.path.realpath(os.path.expanduser(w)) for w in writable]
    if sww:
        cfg["sandbox_workspace_write"] = sww
    p = {"cwd": cwd, "sandbox": sandbox, "approvalPolicy": approval, "config": cfg or None}
    if model:
        p["model"] = model
    if ephemeral:
        p["ephemeral"] = True
    return p


def outside_sources(sources, cwd: str, home: str | None = None) -> tuple[list[str], list[str]]:
    """(instruction files outside cwd that a sealed launch refuses, residual global files it reports)."""
    home = home or os.path.expanduser("~")
    root = os.path.realpath(cwd)
    glob_agents = {os.path.realpath(os.path.join(os.environ.get("CODEX_HOME") or os.path.join(home, ".codex"), n))
                   for n in ("AGENTS.md", "AGENTS.override.md")}
    bad, residual = [], []
    for s in sources or []:
        p = os.path.realpath(str(s))
        if p == root or p.startswith(root + os.sep):
            continue
        (residual if p in glob_agents else bad).append(str(s))
    return bad, residual


def launch(a) -> int:
    stop = host_mismatch(a.host)
    if stop:
        print("⛔ " + stop, file=sys.stderr)
        return 3
    cwd = os.path.realpath(os.path.expanduser(a.cwd))
    if not os.path.isdir(cwd):
        print(f"⛔ cwd が無い: {cwd}", file=sys.stderr)
        return 2
    prompt = Path(a.prompt_file).read_text(encoding="utf-8")
    sock = daemon_socket(start=True)
    if not sock:
        url = compose_url(cwd, prompt)
        print("⚠️ 共有の Codex daemon に繋がらない = 自動では起こせない。 本人がアプリで送信を押す形にする:")
        print(f"  入力欄に起動文を入れて開く: open {json.dumps(url)}")
        print(f"  (起動文 = {a.prompt_file}。 model と effort はアプリの入力欄の下で {a.model or '既定'} / {a.effort or '既定'} を選ぶ)")
        if not a.no_reveal and open_in_app(url):
            print("  → アプリに開いた (送信はまだ)")
        return 4
    w = WS(sock)
    try:
        w.call("initialize", {"clientInfo": CLIENT})
        w.send({"method": "initialized"})
        residual: list[str] = []
        if a.sealed:
            pre = w.call("thread/start", thread_params(cwd, a.model, a.effort, a.sandbox, a.approval, a.network, ephemeral=True,
                                                       writable=a.writable_root))
            bad, residual = outside_sources(pre.get("instructionSources"), cwd)
            if bad:
                print("⛔ 封じた sandbox の外の指示 file を Codex が読む = 起こさない (sandbox を祖先に AGENTS.md・CLAUDE.md の"
                      " 無い場所へ): " + ", ".join(bad), file=sys.stderr)
                return 5
        res = w.call("thread/start", thread_params(cwd, a.model, a.effort, a.sandbox, a.approval, a.network, writable=a.writable_root))
        tid = res["thread"]["id"]
        if a.name:
            try:
                w.call("thread/name/set", {"threadId": tid, "name": a.name})
            except Exception as e:  # the title falls back to the first message
                print(f"  (名前を付けられなかった: {e})", file=sys.stderr)
        turn = {"threadId": tid, "input": [{"type": "text", "text": prompt}]}
        if a.effort:
            turn["effort"] = a.effort
        w.call("turn/start", turn)
        sources = res.get("instructionSources") or []
        got_model, got_effort = res.get("model") or "?", res.get("reasoningEffort") or "?"
    finally:
        w.close()
    revealed = False if a.no_reveal else open_in_app(reveal_url(tid))
    cli = codex_cli() or "codex"
    out = {"thread_id": tid, "host": short_host(), "cwd": cwd,
           "model": got_model, "effort": got_effort, "instruction_sources": sources, "residual_sources": residual,
           "revealed": revealed, "launched_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if a.record:
        try:
            rec = json.loads(Path(a.record).read_text(encoding="utf-8"))
        except Exception:
            rec = {}
        rec.update(codex_thread=tid, launched_host=out["host"], launched_at=out["launched_at"], surface="codex-app")
        Path(a.record).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    want = " / ".join(x for x in (a.model, a.effort) if x)
    mismatch = (a.model and got_model != a.model) or (a.effort and got_effort != a.effort)
    print(f"→ Codex の仕事を起こした: thread {tid} (model {got_model} / effort {got_effort}"
          + (f" ⚠️ 頼んだ値 {want} と違う" if mismatch else "") + f", cwd {cwd})")
    print(f"  アプリ: {'左の「最近の項目」 に載せた (アプリに開かせた)' if revealed else '開かせていない = 本人が見るなら'}"
          f" open '{reveal_url(tid)}'")
    print("  走っている間はアプリに「別のアプリで開いています」 と出る (仕事は手元の共有 daemon が動かす)。 進行を見る ="
          f" {cli} resume {tid} (同じ daemon に繋ぐ TUI)。 終わって 30〜45 秒後にアプリで開けば続きを話せる")
    if ct is not None:
        print(f"  知らせる = {ct.queue_hint(tid, '<掲示板の thread id と書いた中身を 1 行>')}")
    print(f"  読んだ指示 file: {', '.join(sources) or '(なし)'}"
          + (f" (封じた sandbox の外の残余 = {', '.join(residual)}: spec と sandbox の AGENTS.md で受ける)" if residual else ""))
    return 1 if mismatch else 0


def continue_thread(a) -> int:
    """Send the next turn to an existing thread through the shared daemon (the revised round of a sealed review goes to
    the same reviewer: the counterpart of `codex exec resume <id>`, listed in the app). Refused by the daemon while
    another process (the app) holds the thread: continue it there, or close it there first."""
    stop = host_mismatch(a.host)
    if stop:
        print("⛔ " + stop, file=sys.stderr)
        return 3
    tid = a.thread
    if ct is not None:
        tid = ct.resolve(a.thread) or a.thread
    prompt = Path(a.prompt_file).read_text(encoding="utf-8")
    sock = daemon_socket(start=True)
    if not sock:
        print("⛔ 共有の Codex daemon に繋がらない。 アプリでその thread を開き、 起動文を貼って送る: "
              f"open '{reveal_url(tid)}' (起動文 = {a.prompt_file})", file=sys.stderr)
        return 4
    w = WS(sock)
    try:
        w.call("initialize", {"clientInfo": CLIENT})
        w.send({"method": "initialized"})
        try:
            w.call("thread/resume", {"threadId": tid})
        except RuntimeError as e:
            print(f"⛔ thread {tid[:8]} を daemon で開けない ({e})。 アプリが開いているなら、 アプリで続けるか、 アプリで閉じてから"
                  " やり直す", file=sys.stderr)
            return 5
        turn = {"threadId": tid, "input": [{"type": "text", "text": prompt}]}
        if a.effort:
            turn["effort"] = a.effort
        w.call("turn/start", turn)
    finally:
        w.close()
    revealed = False if a.no_reveal else open_in_app(reveal_url(tid))
    print(f"→ thread {tid} に次の turn を送った{' (アプリに開かせた)' if revealed else ''}。 進行 = {codex_cli() or 'codex'} resume {tid}")
    return 0


def check_self(a) -> int:
    tid = os.environ.get("CODEX_THREAD_ID", "")
    rows = ct.thread_rows(ids=[tid]) if (ct is not None and tid) else []
    if not rows:
        print(f"この thread ({tid[:8] or '?'}) の model を手元の記録で読めない (別の機械の thread か、 アプリの cloud 側の thread)。"
              " 依頼元に 1 行言って止まる")
        return 1
    model, effort = rows[0].get("model") or "?", rows[0].get("reasoning_effort") or "?"
    ok = model == a.model and (not a.effort or effort == a.effort)
    print(f"{'✅' if ok else '⛔'} この thread の記録 = model {model} / effort {effort} (頼まれた値 = {a.model}"
          + (f" / {a.effort}" if a.effort else "") + ")")
    return 0 if ok else 1


# ---------------------------------------------------------------- selftest

def _fake_daemon(path: str, log: list, sources: list[str]):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    def handle(c):
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += c.recv(4096)
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nupgrade: websocket\r\nconnection: Upgrade\r\n\r\n")
        rest = buf.split(b"\r\n\r\n", 1)[1]
        srvws = WS.__new__(WS)
        srvws.s, srvws.buf, srvws.n, srvws.notes = c, rest, 0, []
        while True:
            try:
                m = srvws.recv()
            except Exception:
                return
            log.append(m)
            if "id" not in m:
                continue
            p, meth = m.get("params") or {}, m.get("method")
            if meth == "thread/start":
                tid = "eph" if p.get("ephemeral") else "01aaaaaa-0000-7000-8000-000000000001"
                r = {"thread": {"id": tid}, "model": p.get("model") or "m-default",
                     "reasoningEffort": (p.get("config") or {}).get("model_reasoning_effort"), "instructionSources": sources}
            else:
                r = {}
            data = json.dumps({"method": "note"}).encode()
            c.sendall(bytes([0x81, len(data)]) + data)  # an unmasked server notification before the answer
            data = json.dumps({"id": m["id"], "result": r}).encode()
            c.sendall(bytes([0x81, 126]) + struct.pack(">H", len(data)) + data)

    threading.Thread(target=serve, daemon=True).start()
    return srv


def _selftest() -> int:
    import argparse
    checks = []
    tmp = tempfile.mkdtemp(prefix="cal-")
    sockp = os.path.join(tmp, "d.sock")
    log: list = []
    sources = [os.path.expanduser("~/.codex/AGENTS.md")]
    srv = _fake_daemon(sockp, log, sources)
    os.environ.update(CODEX_APP_LAUNCH_SOCKET=sockp, CODEX_APP_LAUNCH_NO_OPEN="1", CODEX_APP_LAUNCH_HOSTNAME="Mac-mini")
    cwd = os.path.join(tmp, "work")
    os.mkdir(cwd)
    pf = os.path.join(tmp, "p.txt")
    Path(pf).write_text("You are the board worker for role `role-x-y`.", encoding="utf-8")
    rec = os.path.join(tmp, "r.launch.json")
    Path(rec).write_text('{"role": "role-x-y"}', encoding="utf-8")

    def args(**kw):
        d = dict(cwd=cwd, prompt_file=pf, model="gpt-x", effort="xhigh", sandbox="workspace-write", approval="never",
                 network=True, name="worker · gpt-x xhigh", host=None, sealed=False, no_reveal=False, record=None, json=True,
                 writable_root=["~/.cache/board-fixture"])
        d.update(kw)
        return argparse.Namespace(**d)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch(args(record=rec))
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    meths = [m.get("method") for m in log]
    checks.append(("start → initialize, thread/start, name, turn/start", rc == 0 and meths[:5] == [
        "initialize", "initialized", "thread/start", "thread/name/set", "turn/start"]))
    ts = next(m for m in log if m.get("method") == "thread/start")["params"]
    sww = ts["config"]["sandbox_workspace_write"]
    checks.append(("model・effort・network・書き込み先を thread/start に固定", ts.get("model") == "gpt-x"
                   and ts["config"]["model_reasoning_effort"] == "xhigh" and sww["network_access"] is True
                   and sww["writable_roots"] == [os.path.realpath(os.path.expanduser("~/.cache/board-fixture"))]))
    tu = next(m for m in log if m.get("method") == "turn/start")["params"]
    checks.append(("turn/start に起動文と effort", tu["effort"] == "xhigh" and "board worker" in tu["input"][0]["text"]))
    checks.append(("応答の model・effort を返す", out["model"] == "gpt-x" and out["effort"] == "xhigh" and out["thread_id"].startswith("01aaaaaa")))
    r = json.loads(Path(rec).read_text(encoding="utf-8"))
    checks.append(("launch 記録に thread と機械", r.get("codex_thread") == out["thread_id"] and r.get("launched_host") == "Mac-mini" and r.get("role") == "role-x-y"))
    with contextlib.redirect_stderr(io.StringIO()):
        checks.append(("別の機械の依頼は起こさない (exit 3)", launch(args(host="odakin-MacBook-M5")) == 3))
    checks.append(("同じ機械の名前 (大小・.local) は通す", host_mismatch("mac-mini.local") is None))
    log.clear()
    sources[:] = [os.path.expanduser("~/.codex/AGENTS.md"), os.path.join(tmp, "AGENTS.md")]
    with contextlib.redirect_stderr(io.StringIO()):
        rc = launch(args(sealed=True))
    checks.append(("封印: cwd の外の指示 file で止める (exit 5、 本番の thread を作らない)", rc == 5
                   and [m.get("params", {}).get("ephemeral") for m in log if m.get("method") == "thread/start"] == [True]))
    log.clear()
    sources[:] = [os.path.expanduser("~/.codex/AGENTS.md"), os.path.join(cwd, "AGENTS.md")]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch(args(sealed=True))
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    checks.append(("封印: cwd の中と global の AGENTS.md は通し、 global を残余として申告", rc == 0 and len(out["residual_sources"]) == 1))
    log.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        rc = continue_thread(argparse.Namespace(thread="01aaaaaa-0000-7000-8000-000000000001", prompt_file=pf, effort="high",
                                                host=None, no_reveal=True))
    meths = [m.get("method") for m in log]
    checks.append(("continue → thread/resume の後に turn/start (同じ reviewer に次の turn)", rc == 0
                   and meths[:4] == ["initialize", "initialized", "thread/resume", "turn/start"]))
    bad, res = outside_sources(["/a/AGENTS.md"], "/a/b", home="/h")
    checks.append(("outside_sources: 祖先の AGENTS.md は外", bad == ["/a/AGENTS.md"] and res == []))
    u = compose_url("/x y", "a&b=c\nd")
    checks.append(("compose_url: path と prompt を符号化", u.startswith("codex://threads/new?path=%2Fx%20y&prompt=a%26b%3Dc%0Ad")))
    checks.append(("reveal_url", reveal_url("t1") == "codex://threads/t1?hostId=local"))
    os.environ.pop("CODEX_APP_LAUNCH_SOCKET")
    os.environ["CODEX_CLI_PATH"] = os.path.join(tmp, "none")
    if ct is not None:
        ct.BUNDLE_PATHS = ()
    import shutil as _sh
    if not _sh.which("codex"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = launch(args(json=False))
        checks.append(("daemon 無し → 本人が押す deep link (exit 4)", rc == 4 and "codex://threads/new?" in buf.getvalue()))
    srv.close()
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None) -> int:
    import argparse
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return _selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--cwd", required=True)
    s.add_argument("--prompt-file", required=True)
    s.add_argument("--model")
    s.add_argument("--effort", choices=EFFORTS)
    s.add_argument("--sandbox", default="workspace-write", choices=["read-only", "workspace-write", "danger-full-access"])
    s.add_argument("--approval", default="never", choices=["untrusted", "on-request", "never"])
    s.add_argument("--network", action="store_true", help="workspace-write の sandbox から network を開く (掲示板への投稿・文献を取る盲検など)")
    s.add_argument("--writable-root", action="append", default=[], help="cwd の外で書いてよい dir (繰り返し可。 掲示板の cache など)")
    s.add_argument("--name", help="アプリの一覧に出る題 (既定 = 起動文の先頭)")
    s.add_argument("--host", help="起こす機械の名前。 この機械でなければ止める")
    s.add_argument("--sealed", action="store_true", help="封じた sandbox: cwd の外の指示 file を読むなら起こさない")
    s.add_argument("--no-reveal", action="store_true", help="アプリに開かせない (一覧には載らない)")
    s.add_argument("--record", help="掲示板の launch 記録 (json) に thread id・機械・時刻を書き足す")
    s.add_argument("--json", action="store_true")
    n = sub.add_parser("continue")
    n.add_argument("--thread", required=True, help="thread id か一意な先頭")
    n.add_argument("--prompt-file", required=True)
    n.add_argument("--effort", choices=EFFORTS)
    n.add_argument("--host")
    n.add_argument("--no-reveal", action="store_true")
    c = sub.add_parser("check-self")
    c.add_argument("--model", required=True)
    c.add_argument("--effort", choices=EFFORTS)
    k = sub.add_parser("compose-link")
    k.add_argument("--cwd", required=True)
    k.add_argument("--prompt-file", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "start":
        return launch(a)
    if a.cmd == "continue":
        return continue_thread(a)
    if a.cmd == "check-self":
        return check_self(a)
    print(compose_url(os.path.realpath(os.path.expanduser(a.cwd)), Path(a.prompt_file).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
