#!/usr/bin/env python3
"""claude-stream-log.py — 無人の `claude -p --output-format stream-json` を起動し、 流れてくる event を人が読める log に直して書く (全部の assistant の文・tool の名前・hook の知らせ・結果。 終了値は claude のもの、 --selftest)

なぜ (一般形。 実測は個人層の RCA の記録):
  `claude -p` の既定 (`--output-format text`) は、 最後の assistant の message しか出さない。 turn の終わりの検査 (Stop hook) が
  追記を求めると、 最後の message は追記になり、 本報告は log から消える。 無人の定期実行の log はその run の唯一の記録
  (`--no-session-persistence` で transcript を残さない) なので、 本報告ごと失われる (正本 = conventions/scheduled-tasks.md#headless-log-full-report)。
  stream-json は全部の message を流すが、 生のまま log に書くと tool の結果 (mail の本文など) まで入り、 log が大きくなり写しが増える。

使い方 (launchd の plist の起動行 = scripts/install-launchd-cron.sh が書く。 手で叩く物ではない):
  python3 claude-stream-log.py -- <claude の絶対 path> -p --output-format stream-json --verbose [--include-hook-events] ... "<prompt>"
  option (-- の前): --no-disclaim (TCC の責任者を移さない = test 用) / --no-partial (経過の file を書かない) / --selftest

log に書くもの:
  - 開始の行 (時刻・model・session の先頭 8 字) と終わりの行 (時刻・終了値・turn の数・かかった時間)
  - assistant の text の全文 (top level の message だけ。 subagent の中の文は出さない)
  - tool の名前と短い目印 1 行 (Bash = description か command の先頭、 file 系 = path、 Grep / Glob = pattern、 他 = 名前だけ)
  - user の text (hook が返した文 = 「Stop hook feedback: …」 など) の先頭 300 字
  - hook の systemMessage (止めずに知らせた文) と、 hook の失敗 (終了値が 0・2 以外)
  - tool の結果がエラーのときだけ、 その先頭 160 字
  - 結果がエラーのときは結果の文 (認証切れ・Prompt is too long は log の末尾に出る = scripts/lib/launchd_job_log.py の判定が読む)
log に書かないもの: tool の結果の中身・thinking・SessionStart の注入・rate limit 等の system event
いつ書くか: claude が終わってから一度に書く (= log の更新時刻は run の終わり。 予定の run が log に残っていないことで
  起動しなかった run と終わらない run を見つける検出器の前提を保つ = launchd_job_log.missed_fire)。 途中の経過は
  <log>.partial に逐次書き (stdout が通常の file のときだけ。 macOS の F_GETPATH で path を知る)、 正常に書き終えたら消す
  = 止まった run の手掛かりだけが残る。
TCC: claude を「自分がプライバシー許可の責任者」 として起動する (lib/tcc_disclaim.spawn_disclaimed)。 以前の起動行は
  sh が claude を exec していた = claude が自分の責任者だった。 python を親にしても許可の帰属を変えないため
  (python が責任者になると、 claude と子が使ってきた許可 〔カレンダー・cloud storage の dir など〕 が効かなくなる)。
  disclaim できない (macOS 以外・関数が無い) ときは普通に起動し、 開始の行にその旨を書く。
signal: SIGTERM / SIGINT / SIGHUP は claude に回し、 claude が終わるのを待ってから、 それまでの分を書いて終える。
stdin は /dev/null (= `claude -p` が stdin を 3 秒待って警告を出す形を避ける)。 stderr は継ぐ (= そのまま log に入る)。
"""
from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
try:
    from tcc_disclaim import spawn_disclaimed
except Exception:  # lib が無い配置 = 普通に起動する
    spawn_disclaimed = None

TEXT_HEAD = 300      # user の text・hook の知らせの先頭
ERR_HEAD = 160       # tool の結果のエラー・hook の失敗の先頭
RESULT_MAX = 2000    # 結果の文 (エラーのとき)
DRAIN_AFTER_EXIT = 3.0   # claude が終わった後、 pipe の残りを読む猶予 (孫が書き口を持ち続けても止まらない)


def _one_line(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _short_path(p: str) -> str:
    home = os.path.expanduser("~")
    p = str(p)
    return "~" + p[len(home):] if home and p.startswith(home + os.sep) else p


def tool_hint(name: str, inp) -> str:
    """tool の呼び出しの目印 (中身は出さない)。"""
    if not isinstance(inp, dict):
        return ""
    if name == "Bash":
        d = inp.get("description") or ""
        return _one_line(d, 120) if d else _one_line(inp.get("command") or "", 80)
    for k in ("file_path", "notebook_path", "path"):
        if inp.get(k):
            return _short_path(inp[k])
    for k in ("pattern", "skill", "description", "subagent_type"):
        if inp.get(k):
            return _one_line(inp[k], 80)
    if name == "WebFetch" and inp.get("url"):
        u = str(inp["url"])
        return u.split("/")[2] if u.count("/") >= 2 else _one_line(u, 60)
    return ""


class Renderer:
    def __init__(self):
        self.lines: list[str] = []
        self.model = ""
        self.session = ""
        self.result: dict | None = None
        self.tools: dict[str, str] = {}

    def feed(self, raw: str) -> list[str]:
        """1 行を読み、 log に足す行を返す (self.lines にも足す)。"""
        raw = raw.rstrip("\n")
        if not raw.strip():
            return []
        try:
            e = json.loads(raw)
        except ValueError:
            e = None
        try:
            out = self._render(e) if isinstance(e, dict) else [_one_line(raw, 500)]
        except Exception as exc:  # 想定外の形の event でも log を書き続ける (中継が落ちると run の記録ごと失う)
            out = [f"  (読めない event: {type(exc).__name__}: {_one_line(raw, 160)})"]
        self.lines.extend(out)
        return out

    def _render(self, e: dict) -> list[str]:
        t, st = e.get("type"), e.get("subtype")
        out: list[str] = []
        if t == "system" and st == "init":
            self.model = str(e.get("model") or "")
            self.session = str(e.get("session_id") or "")
        elif t == "assistant" and not e.get("parent_tool_use_id"):
            for c in (e.get("message") or {}).get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and str(c.get("text") or "").strip():
                    out.extend(str(c["text"]).rstrip().splitlines())
                elif c.get("type") == "tool_use":
                    name = str(c.get("name") or "?")
                    self.tools[str(c.get("id") or "")] = name
                    hint = tool_hint(name, c.get("input"))
                    out.append(f"  · {name}" + (f": {hint}" if hint else ""))
        elif t == "user" and not e.get("parent_tool_use_id"):
            content = (e.get("message") or {}).get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for c in content or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and str(c.get("text") or "").strip():
                    out.append(f"  ↩ {_one_line(c['text'], TEXT_HEAD)}")
                elif c.get("type") == "tool_result" and c.get("is_error"):
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(str(x.get("text") or "") for x in body if isinstance(x, dict))
                    name = self.tools.get(str(c.get("tool_use_id") or ""), "tool")
                    out.append(f"  ✗ {name} の結果がエラー: {_one_line(body or '', ERR_HEAD)}")
        elif t == "system" and st == "hook_response":
            ev = str(e.get("hook_event") or e.get("hook_name") or "hook")
            raw = str(e.get("stdout") or e.get("output") or "").strip()
            try:
                j = json.loads(raw) if raw.startswith("{") else None
            except ValueError:
                j = None
            if isinstance(j, dict) and str(j.get("systemMessage") or "").strip():
                out.append(f"  ℹ {ev} hook: {_one_line(j['systemMessage'], TEXT_HEAD)}")
            code = e.get("exit_code")
            if (isinstance(code, int) and code not in (0, 2)) or e.get("outcome") not in (None, "success"):
                err = str(e.get("stderr") or "").strip()
                out.append(f"  ⚠ {ev} hook ({e.get('hook_name') or '?'}) が失敗 (終了値 {code}, {e.get('outcome')})"
                           + (f": {_one_line(err, ERR_HEAD)}" if err else ""))
        elif t == "result":
            self.result = e
        return out

    def header(self, started: float, disclaimed: bool) -> str:
        parts = [datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S") + " 開始"]
        if self.model:
            parts.append(self.model)
        if self.session:
            parts.append("session " + self.session[:8])
        if not disclaimed:
            parts.append("⚠ TCC の責任者を claude に移せなかった (python の許可で動く)")
        return "── " + " · ".join(parts) + " ──"

    def footer(self, ended: float, started: float, rc: int, note: str = "") -> list[str]:
        out = []
        r = self.result
        if r is None:
            out.append("（結果の行が無い = claude が結果を書かずに終わった）")
        elif r.get("is_error"):
            out.extend(("結果 (エラー): " + str(r.get("result") or r.get("subtype") or "")[:RESULT_MAX]).splitlines() or [""])
        dur = int(ended - started)
        bits = [datetime.fromtimestamp(ended).strftime("%H:%M:%S") + " 終了", f"rc={rc}"]
        if r is not None and r.get("num_turns") is not None:
            bits.append(f"{r.get('num_turns')} turns")
        bits.append(f"{dur // 60}m{dur % 60:02d}s")
        if note:
            bits.append(note)
        out.append("── " + " · ".join(bits) + " ──")
        return out


def _stdout_file_path() -> str | None:
    """stdout が通常の file ならその path (macOS の F_GETPATH)。 それ以外は None。"""
    try:
        if not stat.S_ISREG(os.fstat(1).st_mode):
            return None
        getpath = getattr(fcntl, "F_GETPATH", None)
        if getpath is None:
            return None
        raw = fcntl.fcntl(1, getpath, bytes(1024))
        return os.fsdecode(raw.split(b"\0", 1)[0]) or None
    except OSError:
        return None


def _spawn(argv: list[str], disclaim: bool):
    """(pid か Popen, 読み口の fd, disclaim できたか)。"""
    prog = argv[0] if os.sep in argv[0] else (shutil.which(argv[0]) or argv[0])
    argv = [prog] + argv[1:]
    rd, wr = os.pipe()
    dn = os.open(os.devnull, os.O_RDONLY)
    try:
        if disclaim and spawn_disclaimed is not None:
            pid = spawn_disclaimed(argv, fds={0: dn, 1: wr})
            if pid is not None:
                return pid, rd, True
        p = subprocess.Popen(argv, stdin=dn, stdout=wr)
        return p, rd, False
    finally:
        os.close(wr)
        os.close(dn)


def run(argv: list[str], disclaim: bool = True, partial: bool = True) -> int:
    started = time.time()
    try:
        child, rd, disclaimed = _spawn(argv, disclaim)
    except OSError as exc:
        print(f"── {datetime.fromtimestamp(started):%Y-%m-%d %H:%M:%S} 開始 ──\n"
              f"claude-stream-log: 起動できない: {argv[0]}: {exc}\n── 終了 · rc=127 ──", flush=True)
        return 127
    pid = child if isinstance(child, int) else child.pid
    stopped_by: list[int] = []

    def _forward(signum, _frame):
        stopped_by.append(signum)
        try:
            os.kill(pid, signum)
        except OSError:
            pass

    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, _forward)

    rend = Renderer()
    out_path = _stdout_file_path() if partial else None
    part_path = out_path + ".partial" if out_path else None
    part = None
    if part_path:
        try:
            part = open(part_path, "w", encoding="utf-8")
            part.write(rend.header(started, disclaimed) + "\n")
            part.flush()
        except OSError:
            part = None
    buf = b""
    status = None
    exited_at = None
    while True:
        if status is None:
            try:
                got, st = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                got, st = pid, 0
            if got == pid:
                status, exited_at = st, time.monotonic()
        if exited_at is not None and time.monotonic() - exited_at > DRAIN_AFTER_EXIT:
            break
        try:
            ready, _, _ = select.select([rd], [], [], 0.5)
        except InterruptedError:
            continue
        if not ready:
            continue
        try:
            chunk = os.read(rd, 65536)
        except InterruptedError:
            continue
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            new = rend.feed(line.decode("utf-8", "replace"))
            if part and new:
                try:
                    part.write("\n".join(new) + "\n")
                    part.flush()
                except OSError:
                    pass
    if buf.strip():
        rend.feed(buf.decode("utf-8", "replace"))
    os.close(rd)
    if status is None:
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            status = 0
    if os.WIFEXITED(status):
        rc = os.WEXITSTATUS(status)
    elif os.WIFSIGNALED(status):
        rc = 128 + os.WTERMSIG(status)
    else:
        rc = 1
    note = f"signal {stopped_by[0]} で止められた" if stopped_by else ""
    text = "\n".join([rend.header(started, disclaimed)] + rend.lines + rend.footer(time.time(), started, rc, note)) + "\n"
    try:  # bytes で書く (= launchd の C locale でも locale の符号化に依らない)
        sys.stdout.buffer.write(text.encode("utf-8", "replace"))
        sys.stdout.buffer.flush()
        wrote = True
    except OSError:
        wrote = False
    if part:
        try:
            part.close()
            if wrote:
                os.unlink(part_path)
        except OSError:
            pass
    return rc


def _selftest() -> int:
    import tempfile
    ok = fail = 0

    def check(cond, label):
        nonlocal ok, fail
        print(("  PASS: " if cond else "  FAIL: ") + label)
        ok, fail = ok + bool(cond), fail + (not cond)

    events = [
        {"type": "system", "subtype": "init", "model": "test-model", "session_id": "abcdef0123456789"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "本報告 1 行目\n本報告 2 行目"},
                                                      {"type": "tool_use", "id": "t1", "name": "Bash",
                                                       "input": {"command": "cat secret.txt", "description": "台帳を読む"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "メールの本文 SECRET-BODY"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Read",
                                                       "input": {"file_path": os.path.expanduser("~/Claude/x.md")}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True,
                                                  "content": "File does not exist."}]}},
        {"type": "assistant", "parent_tool_use_id": "t9", "message": {"content": [{"type": "text", "text": "SUBAGENT-TEXT"}]}},
        {"type": "system", "subtype": "hook_response", "hook_event": "Stop", "hook_name": "Stop",
         "stdout": json.dumps({"systemMessage": "人に回す: 件名 A"}), "exit_code": 0, "outcome": "success"},
        {"type": "system", "subtype": "hook_response", "hook_event": "SessionStart", "hook_name": "SessionStart",
         "stdout": "{\"hookSpecificOutput\": {\"additionalContext\": \"INJECTED-DIGEST\"}}", "exit_code": 0, "outcome": "success"},
        {"type": "system", "subtype": "hook_response", "hook_event": "PreToolUse", "hook_name": "PreToolUse:Bash",
         "stdout": "", "stderr": "boom", "exit_code": 1, "outcome": "error"},
        {"type": "user", "message": {"content": [{"type": "text", "text": "Stop hook feedback:\n追記を 1 行書いてください"}]}},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "THINKING-TEXT"},
                                                      {"type": "text", "text": "追記の 1 行"}]}},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}},
        {"type": "assistant", "message": "not-a-dict"},
        {"type": "result", "subtype": "success", "is_error": False, "result": "追記の 1 行", "num_turns": 2},
    ]
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "events.jsonl")
        with open(src, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.write("plain text line from cli\n")
        fake = os.path.join(td, "fake-claude")
        with open(fake, "w") as f:
            f.write(f"#!/bin/sh\ncat '{src}'\nread x && echo STDIN-WAS-READ >&2\nexit 3\n")
        os.chmod(fake, 0o755)
        log = os.path.join(td, "job.log")
        with open(log, "w") as lf:
            rc = subprocess.run([sys.executable, os.path.abspath(__file__), "--", fake, "-p", "x"],
                                stdout=lf, stderr=subprocess.STDOUT).returncode
        text = open(log, encoding="utf-8").read()
        lines = text.splitlines()
        check(rc == 3, f"終了値は claude のもの (got {rc})")
        check("本報告 1 行目" in text and "本報告 2 行目" in text and "追記の 1 行" in text,
              "本報告と追記の両方が log に残る (text 形式なら追記だけになる形)")
        check(lines[0].startswith("── ") and "test-model" in lines[0] and "session abcdef01" in lines[0],
              "開始の行に model と session の先頭 8 字")
        check(lines[-1].startswith("── ") and "rc=3" in lines[-1] and "2 turns" in lines[-1], "終わりの行に終了値と turn の数")
        check("  · Bash: 台帳を読む" in text and "~/Claude/x.md" in text, "tool は名前と目印 (description・path) だけ")
        check("SECRET-BODY" not in text and "cat secret.txt" not in text, "tool の結果の中身と、 description がある Bash の command は書かない")
        check("✗ Read の結果がエラー: File does not exist." in text, "tool の結果のエラーは先頭だけ書く")
        check("SUBAGENT-TEXT" not in text and "THINKING-TEXT" not in text and "INJECTED-DIGEST" not in text,
              "subagent の文・thinking・SessionStart の注入は書かない")
        check("ℹ Stop hook: 人に回す: 件名 A" in text, "hook の systemMessage を書く")
        check("⚠ PreToolUse hook (PreToolUse:Bash) が失敗 (終了値 1, error): boom" in text, "hook の失敗を書く")
        check("↩ Stop hook feedback: 追記を 1 行書いてください" in text, "hook が返した文 (user の text) を書く")
        check("plain text line from cli" in text, "JSON でない行はそのまま書く")
        check("読めない event: AttributeError" in text and "追記の 1 行" in text, "想定外の形の event でも落ちずに書き続ける")
        check("STDIN-WAS-READ" not in text, "stdin は /dev/null (claude が stdin を待たない)")
        check(not os.path.exists(log + ".partial") or sys.platform != "darwin", "正常に書き終えたら経過の file を消す")
        # 認証切れ: 結果の文が log の末尾 6 行に入る (launchd_job_log.failure_kind が読む)
        auth = [{"type": "system", "subtype": "init", "model": "m", "session_id": "s"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Not logged in · Please run /login"}]}},
                {"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login",
                 "num_turns": 1}]
        with open(src, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(e) for e in auth) + "\n")
        with open(fake, "w") as f:
            f.write(f"#!/bin/sh\ncat '{src}'\nexit 1\n")
        with open(log, "w") as lf:
            rc = subprocess.run([sys.executable, os.path.abspath(__file__), "--", fake], stdout=lf).returncode
        tail = open(log, encoding="utf-8").read().splitlines()[-6:]
        check(rc == 1 and any("結果 (エラー): Not logged in" in ln for ln in tail), "認証切れの文が末尾 6 行に入る")
        # signal: SIGTERM を claude に回し、 それまでの分を書いて終える
        with open(fake, "w") as f:
            f.write("#!/bin/sh\necho '{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"途中まで\"}]}}'\n"
                    "trap 'exit 143' TERM\nsleep 8 & wait\n")
        with open(log, "w") as lf:
            p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--", fake], stdout=lf)
            time.sleep(1.0)
            during = os.path.exists(log + ".partial") and "途中まで" in open(log + ".partial", encoding="utf-8").read()
            p.send_signal(signal.SIGTERM)
            rc = p.wait(timeout=20)
        text = open(log, encoding="utf-8").read()
        check(sys.platform != "darwin" or during, "走っている間は経過を <log>.partial に書く")
        check(rc == 143 and "途中まで" in text and "signal 15 で止められた" in text, f"SIGTERM を回して途中までを書く (rc={rc})")
        # 起動できない
        with open(log, "w") as lf:
            rc = subprocess.run([sys.executable, os.path.abspath(__file__), "--", os.path.join(td, "no-such")],
                                stdout=lf).returncode
        check(rc == 127 and "起動できない" in open(log, encoding="utf-8").read(), "起動できない claude は 127 と 1 行")
    print(f"\n==== RESULT: PASS={ok} FAIL={fail} ====")
    return 0 if fail == 0 else 1


def main(argv: list[str]) -> int:
    if "--selftest" in (argv[:argv.index("--")] if "--" in argv else argv):
        return _selftest()
    if "--" not in argv:
        print("usage: claude-stream-log.py [--no-disclaim] [--no-partial] -- <claude> -p --output-format stream-json --verbose ...",
              file=sys.stderr)
        return 2
    i = argv.index("--")
    opts, cmd = argv[:i], argv[i + 1:]
    if not cmd:
        print("claude-stream-log: -- の後に起動する command が無い", file=sys.stderr)
        return 2
    return run(cmd, disclaim="--no-disclaim" not in opts, partial="--no-partial" not in opts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
