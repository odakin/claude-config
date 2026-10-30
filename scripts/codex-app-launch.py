#!/usr/bin/env python3
"""codex-app-launch.py — Codex の仕事を Codex アプリで進行が見え、 その窓から話しかけられる形で起こす (アプリを書き手にする)。

Why (実測): `codex exec` で起こした仕事は Codex アプリのどこにも出ない (状態 DB に source=exec で入り、 アプリの一覧は
対話の種類だけを出す)。 手元の共有 app-server daemon (`codex app-server daemon`、 unix socket の上の websocket で JSON-RPC)
に thread を作って turn を走らせ、 アプリに `codex://threads/<id>?hostId=local` を開かせると一覧には載るが、 走って
いる間アプリは「別のアプリで開いています」 と出して進行を出さず、 話しかけられない (書き手の lock が daemon にある。
アプリ 26.1002 では読み込みに失敗した thread は左の「最近の項目」 にも載らなかった)。 アプリが自分で共有 daemon に繋ぐ
経路 (環境変数 CODEX_APP_SERVER_USE_LOCAL_DAEMON=1) はアプリ本体にあるが、 アプリが常に設定の上書きを渡すので
この版では使われない (アプリ本体の code で確認)。
既定の形 (CLI 0.162 / アプリ 26.1002 で実測): (1) 使い捨ての app-server (`codex app-server`、 stdio の JSON 行) で
thread を作り (model・effort・cwd・sandbox・書き込み可 dir・承認を固定)、 名前を付け、 `thread/inject_items` で履歴に
起動の記録を 1 項目入れる (rollout file ができる。 model は呼ばない。 turn の無い thread は rollout が無くアプリで
開けなかった)。 process を閉じると誰も thread を持たない。 (2) 起動文を `codex queue` で予約する (誰も持たない
thread の予約は DB に残る)。 (3) アプリに開かせる → アプリが書き手として thread を開き、 予約を turn として走らせる
= 進行はアプリに出て、 その窓から話しかけられる。 固定した model・effort・書き込み可 dir・承認はアプリの turn でも
保たれた。 **network だけはアプリの既定 (~/.codex/config.toml、 既定 off) に戻る** = 掲示板の command は Codex の
許可規則で sandbox の外で走らせる (setup-codex-board-rule.py、 `--allow-board-engine`)。
**Codex の仕事はアプリで見える形で起こす** = 盲検の封じた sandbox も既定はアプリが書き手。 アプリに出ない形
(`--writer daemon`、 `--no-reveal`) は理由が要る (`--daemon-reason '<理由>'` か env CODEX_DAEMON_REASON、 無ければ起こさない)。
daemon は固定した network を保つ代わりに、 走っている間アプリで進行が見えない (進行 = TUI の `codex resume <id>`)。 daemon は
誰も見ていない idle の thread を turn の終わりから 40〜60 秒で手放す。

subcommand:
  start --cwd DIR --prompt-file FILE [--model M] [--effort E] [--sandbox MODE] [--approval POLICY] [--network]
        [--writable-root DIR]... [--name TITLE] [--host HOST] [--sealed] [--no-reveal] [--writer app|daemon]
        [--daemon-reason WHY] [--allow-board-engine BOARD_PY] [--record FILE] [--json]
      既定 (--writer app) = 上の (1)〜(3)。 --writer daemon (理由つき) は daemon を確かめ、 無ければ
      `codex app-server daemon start`、 thread を作って最初の turn を始め、 アプリに開かせる。 --no-reveal も daemon が書き手。
      --host: この機械の名前と違えば何もせず止める (別の機械で起こす仕事を先に起こさない)。
      --sealed: 盲検の封じた sandbox 用。 書き手に依らず、 本番の前に保存しない thread (ephemeral) を同じ設定で作り、 応答の
        instructionSources (Codex が読む指示 file) に cwd の外の file があれば止める (global の ~/.codex/AGENTS.md
        だけは sandbox から切れない残余として通し、 申告する)。 検査ができないときは起こさない (入力欄に入れる経路へ落ちない)。
        アプリの turn の network はアプリの既定 (off) なので、 --network との組は止める = 文献は起動の前に sandbox に入れる。
      --allow-board-engine: 掲示板の worker 用。 その engine の worker の subcommand を sandbox の外で走らせる Codex の
        規則 (setup-codex-board-rule.py) がこの機械に無ければ入れる。
      --record: 掲示板の launch 記録 (json) に thread id・機械・時刻・書き手を書き足す。
      Codex の CLI が無い・app-server に繋がらなければ、 アプリの新規 thread の入力欄に起動文を入れて開く deep link
      (`codex://threads/new?path=…&prompt=…`、 本人が送信を押す) を出して exit 4。
  continue --thread ID --prompt-file FILE [--effort E] [--host HOST] [--no-reveal] [--writer app|daemon] [--daemon-reason WHY]
      既定 = 次の turn を予約してアプリに開かせる (アプリが走らせる)。 daemon で走らせるのは理由つきだけ。
      既存の thread に次の turn を送る (盲検の訂正版の 2 回目を同じ reviewer に返す = `codex exec resume` の代わり)。
      daemon で開いて turn を始める。 アプリが書き手として持っている thread は daemon が開けない = `codex queue` で
      予約し、 アプリが次の turn として拾う (実測)。
  rpc METHOD [PARAMS_JSON]
      daemon に JSON-RPC を 1 回送って結果を出す (起動がおかしいときに daemon の状態を読む。 例 = `rpc thread/loaded/list`
      = いま daemon が読み込んでいる thread。 実測 = 誰も見ていない idle の thread は turn の終わりから 40〜60 秒で外れ、
      `thread/unsubscribe` では外れなかった)。 型の一覧 = `codex app-server generate-json-schema --out <dir>`。
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


class Stdio:
    """JSON-RPC with a one-shot `codex app-server` over stdio (one JSON object per line). Closing it ends the process,
    so nobody holds the threads it made (the app can then become their writer at once; the daemon keeps an idle thread
    for 40〜60 s)."""

    def __init__(self, cli: str, timeout: float = 60.0):
        self.p = subprocess.Popen([cli, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.timeout, self.n = timeout, 0
        self.lines: "list[str]" = []
        self.t = threading.Thread(target=self._pump, daemon=True)
        self.cv = threading.Condition()
        self.t.start()

    def _pump(self) -> None:
        for line in self.p.stdout:
            with self.cv:
                self.lines.append(line)
                self.cv.notify_all()
        with self.cv:
            self.lines.append("")
            self.cv.notify_all()

    def send(self, obj: dict) -> None:
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def call(self, method: str, params: dict) -> dict:
        self.n += 1
        rid = self.n
        self.send({"id": rid, "method": method, "params": params})
        end = time.time() + self.timeout
        with self.cv:
            while True:
                while not self.lines:
                    if not self.cv.wait(timeout=max(0.0, end - time.time())):
                        raise TimeoutError(method)
                line = self.lines.pop(0)
                if line == "":
                    raise EOFError(f"app-server ended during {method}")
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("id") == rid and ("result" in m or "error" in m):
                    if "error" in m:
                        raise RuntimeError(f"{method}: {m['error'].get('message') or m['error']}")
                    return m["result"]

    def close(self) -> int:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            return self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.p.kill()
            return self.p.wait()


def queue_message(cli: str, thread_id: str, text: str) -> tuple[bool, str]:
    """`codex queue`: the thread's writer takes it as its next turn; with no writer it waits until the thread is opened
    (measured: the app took it as a turn on opening the thread)."""
    try:
        p = subprocess.run([cli, "queue", "--thread", thread_id, "--message", text], capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL)
    except Exception as e:
        return False, str(e)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0 and "Queued message" in out, out.strip()[-400:]


def ensure_board_rule(engine: str) -> tuple[bool, str]:
    """Install the Codex rule that runs this board engine's worker subcommands outside the sandbox (an app-run thread
    has the app's sandbox, whose network is off by default), when it is missing: (current after the call, the line)."""
    tool = Path(os.environ.get("CODEX_APP_LAUNCH_BOARD_RULE_TOOL") or HERE / "setup-codex-board-rule.py")
    if not tool.is_file():
        return False, f"掲示板の許可規則の道具が無い: {tool}"
    p = subprocess.run([sys.executable, str(tool), "--install", "--engine", engine], capture_output=True, text=True,
                       timeout=60)
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()


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


def writer_of(a) -> str:
    """Who runs the thread: the app (default, sealed reviews too: progress visible in the app, which can be talked to
    there) or the daemon (only with a reason, see daemon_reason; --no-reveal never opens the app)."""
    w = getattr(a, "writer", None)
    if w:
        return w
    return "daemon" if a.no_reveal else "app"


def daemon_reason(a) -> str:
    """Why this thread runs where the app cannot show it: --daemon-reason or CODEX_DAEMON_REASON ('' = no reason)."""
    return (getattr(a, "daemon_reason", None) or os.environ.get("CODEX_DAEMON_REASON") or "").strip()


def compose_fallback(a, cwd: str, prompt: str, why: str) -> int:
    url = compose_url(cwd, prompt)
    print(f"⚠️ {why} = 自動では起こせない。 本人がアプリで送信を押す形にする:")
    print(f"  入力欄に起動文を入れて開く: open {json.dumps(url)}")
    print(f"  (起動文 = {a.prompt_file}。 model と effort はアプリの入力欄の下で {a.model or '既定'} / {a.effort or '既定'} を選ぶ)")
    if not a.no_reveal and open_in_app(url):
        print("  → アプリに開いた (送信はまだ)")
    return 4


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
    writer, rule = writer_of(a), ""
    if getattr(a, "allow_board_engine", None):
        ok, rule = ensure_board_rule(os.path.realpath(os.path.expanduser(a.allow_board_engine)))
        if not ok and writer == "app":
            # An app-run board worker without the rule cannot reach the board (the app's sandbox has no network).
            if not daemon_reason(a):
                print(f"⛔ 掲示板の許可規則が入らない ({rule}) = アプリの worker は掲示板に届かない。 規則を入れ直す"
                      " (setup-codex-board-rule.py) か、 アプリに出ない形でよい理由を --daemon-reason に書く", file=sys.stderr)
                return 2
            print(f"⚠️ 掲示板の許可規則が入っていない ({rule}) = daemon を書き手にする (理由: {daemon_reason(a)})", file=sys.stderr)
            writer = "daemon"
    if writer == "daemon" and not daemon_reason(a):
        print("⛔ アプリに出ない形 (書き手 = daemon) は理由が要る = 起こさない。 Codex の仕事はアプリで見える形で起こす"
              " (--writer と --no-reveal を外す)。 要るなら --daemon-reason '<理由>'", file=sys.stderr)
        return 2
    if writer == "app" and a.sealed and a.network:
        print("⛔ 封じた sandbox の --network はアプリの turn では効かない (network はアプリの既定に戻る) = 起こさない。"
              " 文献は起動の前に sandbox に入れて --network を外す。 web が要る判定なら --writer daemon --daemon-reason '<理由>'",
              file=sys.stderr)
        return 2
    if writer == "app":
        return launch_app(a, cwd, prompt, rule)
    return launch_daemon(a, cwd, prompt, rule)


def launch_app(a, cwd: str, prompt: str, rule: str) -> int:
    """(1) a one-shot stdio app-server makes, names and seeds the thread, (2) the prompt is queued, (3) the app opens it
    and runs the queued prompt as the thread's writer."""
    def fall_back(why: str) -> int:
        if a.sealed:  # the compose link would start a thread nobody checked
            print(f"⛔ 封じた sandbox の検査ができない ({why}) = 起こさない", file=sys.stderr)
            return 4
        return compose_fallback(a, cwd, prompt, why)

    cli = codex_cli()
    if not cli:
        return fall_back("Codex の CLI が見つからない")
    try:
        s = Stdio(cli)
    except OSError as e:
        return fall_back(f"app-server を起こせない ({e})")
    residual: list[str] = []
    try:
        s.call("initialize", {"clientInfo": CLIENT})
        s.send({"method": "initialized"})
        if a.sealed:
            pre = s.call("thread/start", thread_params(cwd, a.model, a.effort, a.sandbox, a.approval, a.network, ephemeral=True,
                                                       writable=a.writable_root))
            bad, residual = outside_sources(pre.get("instructionSources"), cwd)
            if bad:
                print("⛔ 封じた sandbox の外の指示 file を Codex が読む = 起こさない (sandbox を祖先に AGENTS.md・CLAUDE.md の"
                      " 無い場所へ): " + ", ".join(bad), file=sys.stderr)
                s.close()
                return 5
        res = s.call("thread/start", thread_params(cwd, a.model, a.effort, a.sandbox, a.approval, a.network,
                                                    writable=a.writable_root))
        tid = res["thread"]["id"]
        if a.name:
            try:
                s.call("thread/name/set", {"threadId": tid, "name": a.name})
            except Exception as e:  # the title falls back to the first message
                print(f"  (名前を付けられなかった: {e})", file=sys.stderr)
        # A thread with no history has no rollout file, and the app cannot open it (measured): one model-visible
        # record, with no turn and no model call, writes it.
        s.call("thread/inject_items", {"threadId": tid, "items": [{"type": "message", "role": "developer", "content": [
            {"type": "input_text", "text": f"Launch record: codex-app-launch.py made this thread ({a.name or 'a Codex task'})"
                                           " for the Codex app to run. Its instructions arrive as the next user message."}]}]})
    except Exception as e:
        s.close()
        return fall_back(f"app-server で thread を作れない ({e})")
    s.close()
    queued, qout = queue_message(cli, tid, prompt)
    if not queued:
        print(f"⛔ thread {tid} は作ったが、 起動文を予約できない ({qout})。 アプリで開いて起動文を貼って送る:"
              f" open '{reveal_url(tid)}' (起動文 = {a.prompt_file})", file=sys.stderr)
        return 6
    revealed = open_in_app(reveal_url(tid))
    sources = res.get("instructionSources") or []
    got_model, got_effort = res.get("model") or "?", res.get("reasoningEffort") or "?"
    return report(a, tid, cwd, got_model, got_effort, sources, residual, revealed, "app", rule)


def report(a, tid, cwd, got_model, got_effort, sources, residual, revealed, writer, rule) -> int:
    cli = codex_cli() or "codex"
    out = {"thread_id": tid, "host": short_host(), "cwd": cwd, "writer": writer,
           "model": got_model, "effort": got_effort, "instruction_sources": sources, "residual_sources": residual,
           "revealed": revealed, "launched_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if rule:
        out["board_rule"] = rule
    if a.record:
        try:
            rec = json.loads(Path(a.record).read_text(encoding="utf-8"))
        except Exception:
            rec = {}
        rec.update(codex_thread=tid, launched_host=out["host"], launched_at=out["launched_at"], surface="codex-app",
                   writer=writer)
        Path(a.record).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    want = " / ".join(x for x in (a.model, a.effort) if x)
    mismatch = (a.model and got_model != a.model) or (a.effort and got_effort != a.effort)
    print(f"→ Codex の仕事を起こした: thread {tid} (model {got_model} / effort {got_effort}"
          + (f" ⚠️ 頼んだ値 {want} と違う" if mismatch else "") + f", cwd {cwd}, 書き手 = {'アプリ' if writer == 'app' else 'daemon'})")
    if writer == "app":
        print(f"  アプリ: {'開かせた = アプリが予約した起動文を走らせ、 進行が出る。 その窓から話しかけられる' if revealed else '開かせていない = 予約はアプリで開いたときに走る:'}"
              f" open '{reveal_url(tid)}'")
        print("  network はアプリの既定 (Codex の設定) = 掲示板の command は許可規則で sandbox の外で走る"
              + (f" ({rule})" if rule else ""))
    else:
        print(f"  アプリ: {'左の「最近の項目」 に載せた (アプリに開かせた)' if revealed else '開かせていない = 本人が見るなら'}"
              f" open '{reveal_url(tid)}'")
        print("  走っている間はアプリに「別のアプリで開いています」 と出る (仕事は手元の共有 daemon が動かす)。 進行を見る ="
              f" {cli} resume {tid} (同じ daemon に繋ぐ TUI)。 終わって 40〜60 秒後にアプリで開けば続きを話せる")
    if ct is not None:
        print(f"  知らせる = {ct.queue_hint(tid, '<掲示板の thread id と書いた中身を 1 行>')}")
    print(f"  読んだ指示 file: {', '.join(sources) or '(なし)'}"
          + (f" (封じた sandbox の外の残余 = {', '.join(residual)}: spec と sandbox の AGENTS.md で受ける)" if residual else ""))
    return 1 if mismatch else 0


def launch_daemon(a, cwd: str, prompt: str, rule: str) -> int:
    sock = daemon_socket(start=True)
    if not sock:
        return compose_fallback(a, cwd, prompt, "共有の Codex daemon に繋がらない")
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
    return report(a, tid, cwd, got_model, got_effort, sources, residual, revealed, "daemon", rule)


def continue_thread(a) -> int:
    """Send the next turn to an existing thread (the revised round of a sealed review goes to the same reviewer): by
    default it is queued and the app runs it, so the progress shows there. The shared daemon runs it only with a reason;
    the daemon refuses while another process (the app) holds the thread, and then the turn is queued too."""
    stop = host_mismatch(a.host)
    if stop:
        print("⛔ " + stop, file=sys.stderr)
        return 3
    tid = a.thread
    if ct is not None:
        tid = ct.resolve(a.thread) or a.thread
    prompt = Path(a.prompt_file).read_text(encoding="utf-8")
    if writer_of(a) == "app":
        cli = codex_cli()
        if not cli:
            print(f"⛔ Codex の CLI が見つからない。 アプリでその thread を開き、 起動文を貼って送る: open '{reveal_url(tid)}'"
                  f" (起動文 = {a.prompt_file})", file=sys.stderr)
            return 4
        queued, qout = queue_message(cli, tid, prompt)
        if not queued:
            print(f"⛔ 予約できない ({qout})", file=sys.stderr)
            return 5
        revealed = open_in_app(reveal_url(tid))
        print(f"→ thread {tid} の次の turn を予約した (アプリが走らせる)" + (" (アプリに開かせた)" if revealed else ""))
        return 0
    if not daemon_reason(a):
        print("⛔ アプリに出ない形 (書き手 = daemon) は理由が要る = 送らない。 要るなら --daemon-reason '<理由>'", file=sys.stderr)
        return 2
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
            cli = codex_cli()
            if "active writer" in str(e) and cli:
                # The app holds the thread (it runs app-launched workers): its next turn comes from the queue.
                queued, qout = queue_message(cli, tid, prompt)
                if queued:
                    revealed = False if a.no_reveal else open_in_app(reveal_url(tid))
                    print(f"→ thread {tid} はアプリが書き手 = 次の turn を予約した (アプリが今の turn の後に走らせる)"
                          + (" (アプリに開かせた)" if revealed else ""))
                    return 0
                print(f"⛔ 予約もできない ({qout})", file=sys.stderr)
            print(f"⛔ thread {tid[:8]} を daemon で開けない ({e})。 アプリで続けるか、 アプリで閉じてからやり直す",
                  file=sys.stderr)
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


def rpc(a) -> int:
    """One JSON-RPC call to the shared daemon, its result printed as JSON (read the daemon's state when a launch behaves
    unexpectedly: `rpc thread/loaded/list`, `rpc thread/list '{"limit": 5}'`, `rpc thread/read '{"threadId": "…"}'`)."""
    try:
        params = json.loads(a.params or "{}")
    except ValueError as e:
        print(f"⛔ params が JSON でない: {e}", file=sys.stderr)
        return 2
    sock = daemon_socket(start=False)
    if not sock:
        print("⛔ 共有の Codex daemon が動いていない (codex app-server daemon start で起こせる)", file=sys.stderr)
        return 4
    w = WS(sock)
    try:
        w.call("initialize", {"clientInfo": CLIENT})
        w.send({"method": "initialized"})
        try:
            res = w.call(a.method, params)
        except RuntimeError as e:
            print(f"⛔ {e}", file=sys.stderr)
            return 1
    finally:
        w.close()
    print(json.dumps(res, ensure_ascii=False, indent=1))
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
            if meth == "thread/resume" and p.get("threadId") == "held-by-app":
                data = json.dumps({"id": m["id"], "error": {"code": -32600,
                                   "message": "thread held-by-app already has an active writer"}}).encode()
                c.sendall(bytes([0x81, 126]) + struct.pack(">H", len(data)) + data)
                continue
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


_FAKE_CLI = r'''
import json, os, sys
def w(o):
    with open(os.environ["CAL_FAKE_LOG"], "a") as f:
        f.write(json.dumps(o) + "\n")
if sys.argv[1:2] == ["queue"]:
    a = sys.argv[2:]
    t = a[a.index("--thread") + 1]
    w({"queue": t, "message": a[a.index("--message") + 1]})
    print("Queued message q-1 for thread " + t + ".")
    sys.exit(0)
if sys.argv[1:2] == ["app-server"]:
    for line in sys.stdin:
        m = json.loads(line)
        w(m)
        if "id" not in m:
            continue
        p = m.get("params") or {}
        r = {}
        if m["method"] == "thread/start":
            r = {"thread": {"id": "01cccccc-0000-7000-8000-000000000003"}, "model": p.get("model"),
                 "reasoningEffort": (p.get("config") or {}).get("model_reasoning_effort"),
                 "instructionSources": [x for x in [os.environ.get("CAL_FAKE_SOURCES")] if x]}
        print(json.dumps({"method": "note"}))
        print(json.dumps({"id": m["id"], "result": r}), flush=True)
    sys.exit(0)
sys.exit(2)
'''


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
                 writable_root=["~/.cache/board-fixture"], writer="daemon", allow_board_engine=None, daemon_reason="selftest")
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
                                                host=None, no_reveal=True, writer="daemon", daemon_reason="selftest"))
    meths = [m.get("method") for m in log]
    checks.append(("continue → thread/resume の後に turn/start (同じ reviewer に次の turn)", rc == 0
                   and meths[:4] == ["initialize", "initialized", "thread/resume", "turn/start"]))
    log.clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rpc(argparse.Namespace(method="thread/loaded/list", params='{"limit": 3}'))
    checks.append(("rpc → 1 回の呼び出しと結果の JSON", rc == 0 and [m.get("method") for m in log][2:3] == ["thread/loaded/list"]
                   and json.loads(buf.getvalue()) == {}))
    bad, res = outside_sources(["/a/AGENTS.md"], "/a/b", home="/h")
    checks.append(("outside_sources: 祖先の AGENTS.md は外", bad == ["/a/AGENTS.md"] and res == []))
    u = compose_url("/x y", "a&b=c\nd")
    checks.append(("compose_url: path と prompt を符号化", u.startswith("codex://threads/new?path=%2Fx%20y&prompt=a%26b%3Dc%0Ad")))
    checks.append(("reveal_url", reveal_url("t1") == "codex://threads/t1?hostId=local"))
    # the app as the writer: a one-shot stdio app-server (a fake CLI here) makes, names and seeds the thread, and the
    # prompt goes through `codex queue`; the daemon is not used
    fake, flog, rec2 = os.path.join(tmp, "fake-codex"), os.path.join(tmp, "fake.jsonl"), os.path.join(tmp, "r2.launch.json")
    Path(fake).write_text(f"#!{sys.executable}\n" + _FAKE_CLI, encoding="utf-8")
    os.chmod(fake, 0o755)
    Path(rec2).write_text('{"role": "role-x-y"}', encoding="utf-8")
    os.environ.update(CODEX_CLI_PATH=fake, CAL_FAKE_LOG=flog)
    log.clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch(args(writer=None, record=rec2))
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    lines = [json.loads(x) for x in Path(flog).read_text(encoding="utf-8").splitlines()]
    meths = [m.get("method") for m in lines if "method" in m]
    checks.append(("app: 使い捨ての app-server で start・name・inject (turn は始めない、 daemon は使わない)", rc == 0
                   and meths == ["initialize", "initialized", "thread/start", "thread/name/set", "thread/inject_items"]
                   and not log))
    ts = next(m for m in lines if m.get("method") == "thread/start")["params"]
    checks.append(("app: model・effort・書き込み先を thread/start に固定", ts.get("model") == "gpt-x"
                   and ts["config"]["model_reasoning_effort"] == "xhigh"
                   and ts["config"]["sandbox_workspace_write"]["writable_roots"]))
    q = [m for m in lines if "queue" in m]
    checks.append(("app: 起動文を codex queue で予約", len(q) == 1 and q[0]["queue"].startswith("01cccccc")
                   and "board worker" in q[0]["message"]))
    checks.append(("app: 書き手 = app を返し、 launch 記録にも書く", out["writer"] == "app"
                   and json.loads(Path(rec2).read_text(encoding="utf-8")).get("writer") == "app"))
    checks.append(("書き手の既定: --no-reveal だけ daemon、 封印も app", writer_of(args(writer=None, sealed=True)) == "app"
                   and writer_of(args(writer=None, no_reveal=True)) == "daemon" and writer_of(args(writer=None)) == "app"))
    for nm, kw in (("--writer daemon", dict(writer="daemon")), ("--no-reveal", dict(writer=None, no_reveal=True))):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = launch(args(daemon_reason=None, **kw))
        checks.append((f"理由の無い {nm} は起こさない", rc == 2))
    log.clear()
    Path(flog).write_text("", encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        rc = launch(args(writer=None, sealed=True, network=False, daemon_reason=None))
    lines = [json.loads(x) for x in Path(flog).read_text(encoding="utf-8").splitlines()]
    starts = [m["params"] for m in lines if m.get("method") == "thread/start"]
    checks.append(("封印 + app: 本番の前に ephemeral の thread で指示 file を検査する", rc == 0 and len(starts) == 2
                   and starts[0].get("ephemeral") is True and not starts[1].get("ephemeral") and not log))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = launch(args(writer=None, sealed=True, network=True, daemon_reason=None))
    checks.append(("封印 + app + --network は起こさない", rc == 2))
    os.environ["CAL_FAKE_SOURCES"] = "/tmp/outside/AGENTS.md"
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = launch(args(writer=None, sealed=True, network=False, daemon_reason=None))
    os.environ.pop("CAL_FAKE_SOURCES")
    checks.append(("封印 + app: sandbox の外の指示 file で止まる", rc == 5))
    _cli_saved = os.environ["CODEX_CLI_PATH"]
    os.environ["CODEX_CLI_PATH"] = os.path.join(tmp, "none")
    _bp = ct.BUNDLE_PATHS if ct is not None else None
    if ct is not None:
        ct.BUNDLE_PATHS = ()
    import shutil as _sh0
    if not _sh0.which("codex"):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = launch(args(writer=None, sealed=True, network=False, daemon_reason=None))
        checks.append(("封印 + app: CLI が無ければ入力欄の経路へ落ちず止まる", rc == 4))
    os.environ["CODEX_CLI_PATH"] = _cli_saved
    if ct is not None:
        ct.BUNDLE_PATHS = _bp
    # a board worker: the rule is installed first; without it the daemon runs the thread only with a reason
    tool = os.path.join(tmp, "rule-tool.py")
    Path(tool).write_text("import sys\nprint('rule probe')\nsys.exit(1)\n", encoding="utf-8")
    os.environ["CODEX_APP_LAUNCH_BOARD_RULE_TOOL"] = tool
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = launch(args(writer=None, daemon_reason=None, allow_board_engine=os.path.join(tmp, "board.py")))
    checks.append(("掲示板の規則が入らず理由も無ければ起こさない", rc == 2))
    for rc_tool, want_writer in ((0, "app"), (1, "daemon")):
        Path(tool).write_text(f"import sys\nprint('rule probe')\nsys.exit({rc_tool})\n", encoding="utf-8")
        os.environ["CODEX_APP_LAUNCH_BOARD_RULE_TOOL"] = tool
        log.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = launch(args(writer=None, allow_board_engine=os.path.join(tmp, "board.py")))
        o = json.loads(buf.getvalue().strip().splitlines()[-1])
        checks.append((f"掲示板の規則が{'入った' if rc_tool == 0 else '入らない'} → 書き手 = {want_writer}",
                       rc == 0 and o["writer"] == want_writer and o.get("board_rule") == "rule probe"
                       and (bool(log) == (want_writer == "daemon"))))
    os.environ.pop("CODEX_APP_LAUNCH_BOARD_RULE_TOOL")
    Path(flog).write_text("", encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = continue_thread(argparse.Namespace(thread="held-by-app", prompt_file=pf, effort=None, host=None, no_reveal=True,
                                                writer=None, daemon_reason="selftest"))
    q = [json.loads(x) for x in Path(flog).read_text(encoding="utf-8").splitlines() if '"queue"' in x]
    checks.append(("continue: アプリが書き手の thread は daemon が断る → 予約に回す", rc == 0 and len(q) == 1
                   and q[0]["queue"] == "held-by-app"))
    Path(flog).write_text("", encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = continue_thread(argparse.Namespace(thread="plain", prompt_file=pf, effort=None, host=None, no_reveal=False,
                                                writer=None, daemon_reason=None))
    q = [json.loads(x) for x in Path(flog).read_text(encoding="utf-8").splitlines() if '"queue"' in x]
    checks.append(("continue の既定: 予約してアプリに走らせる", rc == 0 and len(q) == 1 and q[0]["queue"] == "plain"))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = continue_thread(argparse.Namespace(thread="plain", prompt_file=pf, effort=None, host=None, no_reveal=True,
                                                writer=None, daemon_reason=None))
    checks.append(("continue: 理由の無い daemon は送らない", rc == 2))
    os.environ.pop("CAL_FAKE_LOG")
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
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = launch(args(json=False, writer="app"))
        checks.append(("CLI 無し (書き手 = app) → 本人が押す deep link (exit 4)", rc == 4 and "codex://threads/new?" in buf.getvalue()))
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
    s.add_argument("--no-reveal", action="store_true", help="アプリに開かせない (一覧には載らない。 書き手 = daemon)")
    s.add_argument("--writer", choices=["app", "daemon"],
                   help="thread を走らせる側 (既定 = app。 --no-reveal なら daemon。 daemon は --daemon-reason が要る)")
    s.add_argument("--daemon-reason", help="アプリに出ない形で起こす理由 (env CODEX_DAEMON_REASON でも可)")
    s.add_argument("--allow-board-engine", help="掲示板の worker: この board.py の worker の subcommand を sandbox の外で"
                   "走らせる Codex の規則が無ければ入れる (setup-codex-board-rule.py)")
    s.add_argument("--record", help="掲示板の launch 記録 (json) に thread id・機械・時刻・書き手を書き足す")
    s.add_argument("--json", action="store_true")
    n = sub.add_parser("continue")
    n.add_argument("--thread", required=True, help="thread id か一意な先頭")
    n.add_argument("--prompt-file", required=True)
    n.add_argument("--effort", choices=EFFORTS)
    n.add_argument("--host")
    n.add_argument("--no-reveal", action="store_true")
    n.add_argument("--writer", choices=["app", "daemon"], help="次の turn を走らせる側 (既定 = app = 予約)")
    n.add_argument("--daemon-reason", help="daemon で走らせる理由 (env CODEX_DAEMON_REASON でも可)")
    r = sub.add_parser("rpc")
    r.add_argument("method", help="app-server の method (例 thread/loaded/list)")
    r.add_argument("params", nargs="?", help="params の JSON (既定 {})")
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
    if a.cmd == "rpc":
        return rpc(a)
    if a.cmd == "check-self":
        return check_self(a)
    print(compose_url(os.path.realpath(os.path.expanduser(a.cwd)), Path(a.prompt_file).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
