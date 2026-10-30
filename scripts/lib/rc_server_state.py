#!/usr/bin/env python3
"""rc_server_state.py — Remote Control サーバーの中身を log と process から読み、 古い server を無人で起こし直す部品 (fleet-heartbeat が使う)

なぜ: 「スマホから始めた session が動かない」 の切り分けには、 その server の待機数・接続中の session・子 process・
  実行中の CLI の版が要る。 これらは server の居る機械でしか読めず、 常駐機には session も人も居ない。 そこで
  毎時の beat に載せて他の機械から読む (正本 = conventions/multi-machine-state.md#fleet-heartbeat)。
  直す手順を人に覚えさせない: 古い CLI で動き続ける server は、 止めて困る仕事が無い時に機械が起こし直す。
  人の手が要るもの (macOS の許可ダイアログ) は、 答えられるまで reader が出し続ける。

読むだけの関数は claude を呼ばず、 secret を読まない。 session の題 (利用者の文面) は beat に載せない =
  log からは id と status だけを取り、 process は pid・経過時間だけを取る (command の行は載せない)。
  すべて fail-open = 読めない項目は欠けるだけで、 beat を止めない。

書く動作は refresh() の 1 つだけ (launchctl kickstart)。 呼ぶ側が decide_refresh() の判定を通した時だけ呼ぶ。
"""

import glob as globmod
import json
import os
import re
import subprocess
import time
from pathlib import Path

# 色と画面制御だけを落とす。 session の URL は端末の hyperlink (OSC 8) の中に在るので残す
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
CAPACITY_RE = re.compile(r"Capacity: (\d+)/(\d+)")
ENV_RE = re.compile(r"[?&]environment=(env_[A-Za-z0-9]+)")
SESSION_LINK_RE = re.compile(r"claude\.ai/code/(session_[A-Za-z0-9]+)")
SESSION_EVENT_RE = re.compile(r"\[(\d\d:\d\d:\d\d)\] Session (\w+)[^\n]*?(cse_[A-Za-z0-9]+)")
STATE_RE = re.compile(r"(Ready|Connected|Reconnecting)\b")
CONFIG_DIR_RE = re.compile(r"CLAUDE_CONFIG_DIR=(?:\"|&quot;)?([^\"&;\s<]+)")
VERSION_PATH_RE = re.compile(r"/versions/([^/]+)$")
TCC_MSG_RE = re.compile(r"msgID=([0-9.]+)")
TCC_SERVICE_RE = re.compile(r"kTCCService(\w+)")
TCC_CLIENT_RE = re.compile(r"(/[^\s,\"'}]*claude[^\s,\"'}]*)", re.I)

QUIET_FLOOR_MIN = 360        # 会話記録が書かれていない時間がこれ未満なら、 使っている最中と見て起こし直さない
BUSY_PCT = 5.0               # server の子孫の CPU の合計がこれ以上なら、 長い処理の最中と見て起こし直さない
COOLDOWN_S = 6 * 3600        # 起こし直しの間隔の下限
UNANSWERED_AGE_MIN = 10      # 利用者の発言のあと、 返事が無いまま経った時間の下限
UNANSWERED_WINDOW_H = 72     # これより古い会話記録は見ない (= 閉じた会話を出し続けない)


def sh(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def log_facts(log_path, tail_bytes=65536):
    """server の log の末尾から、 待機数・状態・接続中の session の id・環境 id・最近の session の出来事を読む。"""
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            tail = f.read().decode("utf-8", errors="replace")
    except Exception:
        return {}
    text = ANSI_RE.sub("", tail).replace("\r", "\n")
    facts = {}
    caps = list(CAPACITY_RE.finditer(text))
    if caps:
        last = caps[-1]
        facts["capacity"] = [int(last.group(1)), int(last.group(2))]
        facts["session_ids"] = sorted(set(SESSION_LINK_RE.findall(text[last.end():])))
    states = STATE_RE.findall(text)
    if states:
        facts["state"] = states[-1].lower()
    envs = ENV_RE.findall(text)
    if envs:
        facts["environment"] = envs[-1]
    events = [{"at": m.group(1), "event": m.group(2).lower(), "id": m.group(3)}
              for m in SESSION_EVENT_RE.finditer(text)]
    if events:
        facts["session_events"] = events[-5:]
    return facts


def parse_etime(s):
    """ps の etime ([[dd-]hh:]mm:ss) を秒にする。 読めなければ None。"""
    m = re.fullmatch(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)", s.strip())
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def parse_ps(out):
    """`ps -axo pid=,ppid=,pcpu=,etime=` の出力を {pid: (ppid, pcpu, etime 秒)} にする。"""
    table = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) < 4 or not p[0].isdigit() or not p[1].isdigit():
            continue
        try:
            table[int(p[0])] = (int(p[1]), float(p[2]), parse_etime(p[3]))
        except ValueError:
            continue
    return table


def process_facts(pid, table):
    """server の経過時間・直接の子の数・最古の子の経過・子孫の CPU の合計。"""
    pid = int(pid)
    if pid not in table:
        return {}
    kids = {}
    for p, (pp, _, _) in table.items():
        kids.setdefault(pp, []).append(p)
    desc, todo = [], list(kids.get(pid, []))
    while todo:
        p = todo.pop()
        desc.append(p)
        todo.extend(kids.get(p, []))
    direct = kids.get(pid, [])
    ages = [table[p][2] for p in direct if table[p][2] is not None]
    facts = {"uptime_s": table[pid][2], "children": len(direct),
             "busy_pct": round(sum(table[p][1] for p in desc), 1)}
    if ages:
        facts["oldest_child_min"] = max(ages) // 60
    return facts


def running_exe(pid):
    """動いている process の実行 file の path。 取れなければ None。"""
    rc, out = sh(["lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn"])
    for line in out.splitlines():
        if line.startswith("n/"):
            return line[1:]
    return None


def stale_reason(exe, started, home):
    """動いている CLI が手元の最新より古ければ理由を返す (古くなければ None)。

    native installer = ~/.local/bin/claude → versions/<版> の版の名前で比べる。 固定の場所の複製や npm の様に
    path に版が無い形は、 file (差し替えの印 `.source` があればそれも) が起動より後に更新されたかで見る。
    """
    if not exe or started is None:
        return None
    p = Path(exe)
    m = VERSION_PATH_RE.search(exe)
    launcher = Path(home) / ".local/bin/claude"
    if m and launcher.exists():
        cur = os.path.basename(os.path.realpath(launcher))
        return f"{m.group(1)} -> {cur}" if cur != m.group(1) else None
    try:
        t = p.stat().st_mtime
    except OSError:
        return "exe gone"
    stamp = p.parent / ".source"
    if stamp.exists():
        t = max(t, stamp.stat().st_mtime)
    return "exe replaced" if t > started + 60 else None


def config_dir_of(plist, home):
    """launchd の plist の起動行の CLAUDE_CONFIG_DIR。 指定が無ければ既定の ~/.claude。"""
    rc, out = sh(["plutil", "-convert", "xml1", "-o", "-", str(plist)])
    m = CONFIG_DIR_RE.search(out if rc == 0 else "")
    return Path(m.group(1)) if m else Path(home) / ".claude"


def transcript_facts(config_dir, now):
    """会話記録の更新が止まっている時間 (分) と、 利用者の発言に返事が付いていない会話。"""
    files = []
    for f in globmod.glob(str(Path(config_dir) / "projects" / "*" / "*.jsonl")):
        try:
            st = os.stat(f)
        except OSError:
            continue
        if st.st_size:
            files.append((st.st_mtime, f))
    files.sort(reverse=True)
    facts = {"quiet_min": int((now - files[0][0]) / 60) if files else None, "unanswered": []}
    for mtime, f in files[:5]:
        age_min = int((now - mtime) / 60)
        if age_min > UNANSWERED_WINDOW_H * 60:
            break
        if age_min >= UNANSWERED_AGE_MIN and last_speaker(f) == "user":
            facts["unanswered"].append({"id": Path(f).stem[:8], "age_min": age_min})
    return facts


def last_speaker(path, tail_bytes=65536):
    """会話記録の最後の発言者 ("user" / "assistant")。 読めなければ None。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("type") in ("user", "assistant") and not d.get("isMeta"):
            return d["type"]
    return None


def parse_tcc(text):
    """tccd の log から、 CLI の許可ダイアログのうち答えの記録が無いものを返す。"""
    answered = {m.group(1) for line in text.splitlines() if "AUTHREQ_RESULT" in line
                for m in [TCC_MSG_RE.search(line)] if m}
    pending = []
    for line in text.splitlines():
        if "AUTHREQ_PROMPTING" not in line:
            continue
        msg, client = TCC_MSG_RE.search(line), TCC_CLIENT_RE.search(line)
        if not client or (msg and msg.group(1) in answered):
            continue
        svc = TCC_SERVICE_RE.search(line)
        pending.append({"service": svc.group(1) if svc else "unknown",
                        "client": os.path.basename(client.group(1)), "at": line[:16]})
    return pending[-5:]


def tcc_pending(window="24h"):
    """答えを待っている許可ダイアログ。 log を読めなければ None (= 「無い」 と区別する)。"""
    rc, out = sh(["/usr/bin/log", "show", "--last", window, "--style", "compact", "--predicate",
                  'subsystem == "com.apple.TCC" AND '
                  '(eventMessage CONTAINS "AUTHREQ_PROMPTING" OR eventMessage CONTAINS "AUTHREQ_RESULT")'],
                 timeout=40)
    return parse_tcc(out) if rc == 0 else None


def decide_refresh(facts, now, last_refresh, off=False):
    """古い server を起こし直してよいかを (可否, 理由) で返す。

    条件 = 古い ∧ 会話記録が QUIET_FLOOR_MIN 分以上止まっている ∧ 子孫が忙しくない ∧ 間隔を空けた。
    接続が残っていても止める理由にしない = 起動時の session が残り続ける server は接続 0 にならない (実測)。
    """
    if off:
        return False, "off"
    if not facts.get("stale"):
        return False, "current"
    if facts.get("busy_pct", 0) >= BUSY_PCT:
        return False, "busy"
    q = facts.get("quiet_min")
    if q is None or q < QUIET_FLOOR_MIN:
        return False, "recent activity"
    if now - last_refresh < COOLDOWN_S:
        return False, "cooldown"
    return True, "stale and quiet"


def refresh(label):
    """launchd の server を起こし直す。 成功したら True。"""
    rc, _ = sh(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"])
    return rc == 0


def load_refresh_state(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def save_refresh_state(path, state):
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        t = p.with_suffix(".tmp")
        t.write_text(json.dumps(state))
        os.replace(t, p)
    except OSError:
        pass


def server_facts(label, pid, log_path, plist, home, table, now=None):
    """1 本の server について beat に載せる項目を集める。"""
    now = now if now is not None else time.time()
    facts = log_facts(log_path)
    if pid:
        facts.update(process_facts(pid, table))
        exe = running_exe(pid)
        if exe:
            facts["exe"] = exe.replace(str(home), "~", 1)
            up = facts.get("uptime_s")
            reason = stale_reason(exe, (now - up) if up is not None else None, home)
            facts["stale"] = reason
    facts.update(transcript_facts(config_dir_of(plist, home), now))
    return facts


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "s.log"
        log.write_bytes(("·✔︎· Connected · Claude · main\n    Capacity: 2/32 · New sessions\n"
                         "    \x1b]8;;https://claude.ai/code/session_AAA?from=cli\x07name\x1b]8;;\x07\n"
                         "    https://claude.ai/code/session_BBB\n"
                         "Continue in https://claude.ai/code?environment=env_TEST1\n"
                         "[07:49:32] Session completed (1h 2m 3s) cse_CCC\n").encode())
        f = log_facts(log)
        assert f["capacity"] == [2, 32] and f["session_ids"] == ["session_AAA", "session_BBB"], f
        assert f["environment"] == "env_TEST1" and f["state"] == "connected", f
        assert f["session_events"] == [{"at": "07:49:32", "event": "completed", "id": "cse_CCC"}], f
        assert log_facts(Path(td) / "none.log") == {}
        # 接続が無くなった後は古い link を数えない
        log.write_bytes("Capacity: 1/32\nhttps://claude.ai/code/session_OLD\n·✔︎· Ready · Claude\nCapacity: 0/32\n".encode())
        f = log_facts(log)
        assert f["capacity"] == [0, 32] and f["session_ids"] == [] and f["state"] == "ready", f

        assert parse_etime("01:02") == 62 and parse_etime("1:00:00") == 3600
        assert parse_etime("2-01:00:00") == 176400 and parse_etime("x") is None
        t = parse_ps("  10   1  0.0  1-00:00:00\n  11  10  1.5  10:00\n  12  11  4.0  05:00\n  13  1 9.9 00:01\nbad\n")
        p = process_facts(10, t)
        assert p == {"uptime_s": 86400, "children": 1, "busy_pct": 5.5, "oldest_child_min": 10}, p
        assert process_facts(99, t) == {}

        home = Path(td) / "h"
        (home / ".local/bin").mkdir(parents=True)
        vers = home / ".local/share/claude/versions"
        vers.mkdir(parents=True)
        (vers / "2.0.1").write_text("x")
        (vers / "2.0.2").write_text("x")
        (home / ".local/bin/claude").symlink_to(vers / "2.0.2")
        assert stale_reason(str(vers / "2.0.1"), 1.0, home) == "2.0.1 -> 2.0.2"
        assert stale_reason(str(vers / "2.0.2"), 1.0, home) is None
        fixed = home / "fixed"
        fixed.mkdir()
        (fixed / "claude").write_text("x")
        now = time.time()
        assert stale_reason(str(fixed / "claude"), now + 3600, home) is None
        assert stale_reason(str(fixed / "claude"), now - 3600, home) == "exe replaced"
        assert stale_reason(str(fixed / "gone"), now, home) == "exe gone"
        assert stale_reason(None, now, home) is None

        cfg = Path(td) / "cfg"
        (cfg / "projects/p").mkdir(parents=True)
        waiting = cfg / "projects/p/aaaaaaaa-1.jsonl"
        waiting.write_text(json.dumps({"type": "assistant"}) + "\n" + json.dumps({"type": "user"}) + "\n")
        done = cfg / "projects/p/bbbbbbbb-2.jsonl"
        done.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "assistant"}) + "\n")
        (cfg / "projects/p/empty.jsonl").write_text("")
        old = now - 3600
        os.utime(waiting, (old, old))
        os.utime(done, (old, old))
        f = transcript_facts(cfg, now)
        assert f["quiet_min"] == 60 and f["unanswered"] == [{"id": "aaaaaaaa", "age_min": 60}], f
        os.utime(waiting, (now, now))
        assert transcript_facts(cfg, now)["unanswered"] == [], "返事を書いている最中は出さない"
        ancient = now - 80 * 3600
        os.utime(waiting, (ancient, ancient))
        os.utime(done, (ancient, ancient))
        assert transcript_facts(cfg, now)["unanswered"] == [], "閉じた会話は出し続けない"

        tcc = ("2026-01-01 10:00:00.000 Df tccd[1] AUTHREQ_PROMPTING: msgID=1.1, service=kTCCServiceSystemPolicyDesktopFolder, "
               "subject=Sub:{/u/.local/share/claude-stable-path/claude}\n"
               "2026-01-01 10:01:00.000 Df tccd[1] AUTHREQ_PROMPTING: msgID=2.2, service=kTCCServiceSystemPolicyDownloadsFolder, "
               "subject=Sub:{/u/.local/share/claude/versions/2.0.2}\n"
               "2026-01-01 10:02:00.000 Df tccd[1] AUTHREQ_RESULT: msgID=1.1, authValue=2\n"
               "2026-01-01 10:03:00.000 Df tccd[1] AUTHREQ_PROMPTING: msgID=3.3, service=kTCCServiceAll, subject=Sub:{/Applications/Other.app}\n")
        assert parse_tcc(tcc) == [{"service": "SystemPolicyDownloadsFolder", "client": "2.0.2",
                                   "at": "2026-01-01 10:01"}], parse_tcc(tcc)
        assert parse_tcc("") == []

        base = {"stale": "2.0.1 -> 2.0.2", "busy_pct": 0.0, "quiet_min": 400, "capacity": [1, 32]}
        assert decide_refresh(base, now, 0) == (True, "stale and quiet"), "接続が残っていても止まった server は起こし直す"
        assert decide_refresh(base, now, 0, off=True) == (False, "off")
        assert decide_refresh({**base, "stale": None}, now, 0) == (False, "current")
        assert decide_refresh({**base, "busy_pct": 80.0}, now, 0) == (False, "busy")
        assert decide_refresh({**base, "quiet_min": 30}, now, 0) == (False, "recent activity")
        assert decide_refresh({**base, "quiet_min": None}, now, 0) == (False, "recent activity")
        assert decide_refresh(base, now, now - 60) == (False, "cooldown")

        st = Path(td) / "state/r.json"
        assert load_refresh_state(st) == {}
        save_refresh_state(st, {"l": 5})
        assert load_refresh_state(st) == {"l": 5}
    print("rc_server_state selftest: ok")


if __name__ == "__main__":
    selftest()
