#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""headless-worker-reports.py — ある session が Bash から起こした worker (headless の `claude -p` / `codex exec` と、 Codex アプリに出る起動の道具 `codex-app-launch.py start|continue`) を会話記録から数え上げ、 worker の作業 dir に残った成果物 (HANDOFF・結果・教訓候補・script) を読み出す。--selftest 内蔵。

用途: Agent tool の subagent は subagent-reports.py、 掲示板と token の子は各々の道具で引けるが、
Bash から直接起動した worker (封じた sandbox の盲検 reviewer など) はどの口にも現れない。
worker の報告は端末の log と作業 dir にしか残らず、 起動した側が拾わないと session の終わりに消える。
締めの整理 (知見を正本へ移す) で取りこぼさないために、 実行位置の分かる候補と文字列だけの候補を分けて引く。

出すもの (起動ごと):
  - 起動時刻、 作業 dir (command の `cd <dir>`、 無ければ記録の cwd)、 model / effort、 config dir
  - 記録の約束の根拠: 親 session・tool call・元 command の hash に一致する機械ローカルの注入記録、
    起動文の MARKER、明示 runner の指定、作業 dir 文書の3項目の記載を区別する。
    会話記録は元 command のままなので、自動注入の判定は updatedInput の文字列に頼らない。
    selected だけ・準備/起動失敗・記録破損は ⚠️。added/present は runner の処理の証拠で、モデル受領は別確認。
  - 作業 dir の成果物候補: HANDOFF.md / REVIEW-RESULTS.md / STAGE*-RESULTS.md / ledger.yaml / DONE /
    scratch/hoist-candidates.md と script (checks/・scratch/ の *.py) の一覧。作成者は別に確認する。
  - HANDOFF.md と hoist-candidates.md の本文 (--max-chars、 0 = 全部)
  - worker 自身の会話記録: runner が記録した明示 session UUID に一致し、起動以降に更新された1 file だけ。
    ID が不明なら列挙しない。同じ cwd の他 session を worker の記録と扱わない。

作業 dir が sandbox なら、 進み具合と受領検査は ai-collaboration scripts/inspect-review-sandbox.py。

Codex アプリに出る起動 (scripts/codex-app-launch.py、 手元の共有 Codex daemon に thread を作りアプリに開かせる):
  - 起動と数える tool call = 実行位置で `codex-app-launch.py start|continue` を呼んだもの、 と、 実行位置の board.py
    (掲示板の request / launch) の出力に掲示板の起動の行 (`→ 起動した: Codex thread <id>`) があるもの。
  - thread id = 起動の出力 (`→ Codex の仕事を起こした: thread <id>` / `--json` の thread_id / `→ thread <id> に次の turn
    を送った`)、 無ければ `continue --thread`。 出力に無い start は「thread 不明」 (起動が止まったか出力を切った)。
  - 作業 dir = `--cwd` (start)、 無ければ thread の rollout の先頭 session_meta の cwd。 model / effort = 起動の出力、
    無ければ command の `--model` / `--effort`。 worker の会話記録 = その thread の rollout
    ($CODEX_HOME/sessions/*/*/*/rollout-*-<id>.jsonl と archived_sessions/、 起動以降に更新されたもの)。
  - 出力に起動の行があっても command の実行位置に起動の道具・board.py が無い tool call (会話記録を grep した出力など)
    と、 command の文字列に `codex-app-launch.py start|continue` が出るだけの tool call は文字列候補。
  - 記録の約束は自動では注入されない (注入 hook は claude -p / codex exec だけを書き換える) = 起動文 file の MARKER か
    作業 dir の AGENTS.md / CLAUDE.md の記載を見る。 掲示板の worker の報告は掲示板の submit。

usage:
  headless-worker-reports.py <session id の先頭> [--max-chars N] [--projects-dir DIR ...]
  headless-worker-reports.py --selftest
  headless-worker-reports.py --selftest --against-root OLD_CHECKOUT  # 元 command のままの連結試験 (旧版は赤)
検出: 注入器と同じ lexer で単純コマンドの実行位置を読み、1 呼出しの複数 worker も数える。
引用・commit message などの文字列一致と未対応構文は別表示 (起動の件数や成果物の読出しに混ぜない)。
会話記録の API 送信の写し (type = api-request-blob) は読まない (前の tool call を送信時の形で繰り返す = 二重に数える)。
従来の regex に一致する呼出しは文字列候補として残すので、未対応構文の手確認経路を失わない。
各実行で検索対象 config の古い孤立した注入記録を整理する (保持条件は注入器の docstring)。
--prune-receipts は整理だけを行う。未使用期間中の定期実行は設けない。
0 件のときは、 見た記録 file を出して終わる (= 使っていない、 と区別できる)。 標準 library だけ。
既知の限界 (実測): 起動を wrapper で包んだ形 (`caffeinate -i <path>/codex exec …`) や、 作業 dir を変数で与えた形
(`cd "$SB" && …`) は lexer が実行位置を読めず「文字列候補」 に落ちる = 起動として数えない。 その回は候補の
元 command を目で確かめる (sandbox の受領は結果 file の有無で判定する)。 lexer の拡張は未着手。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import importlib.util
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None
try:
    import compressed_jsonl as _cj
except Exception:  # pragma: no cover - 古い配置 (圧縮した rollout は読めなかった本数として出す)
    _cj = None
# 読めなかった圧縮した rollout (理由 → path の set)。 run() の終わりに 1 行で出す
ROLLOUT_UNREADABLE: dict = {}

# the binary may be given by path (an app-bundled CLI, a pinned version) and wrapped (caffeinate, env): the path
# prefix is consumed before the name so that `/Applications/.../codex exec` and `caffeinate -i /opt/x/codex exec`
# count as launches (measured: three sealed-sandbox reviewer runs fell to "string candidates" without this)
LAUNCH_RE = re.compile(r"(?:^|[\s;&|(])(?:[^\s;&|()'\"]*/)?(claude\b[^\n;&|]*?\s(?:-p|--print)\b|codex\s+exec\b)")
MARKER = "記録の約束"
TOP = ("HANDOFF.md", "REVIEW-RESULTS.md", "ledger.yaml", "DONE")
TEXTS = ("HANDOFF.md", "scratch/hoist-candidates.md")
_RECEIPTS = None

# Codex app launches (scripts/codex-app-launch.py): the command names the launcher, the tool result names the thread.
# The launcher prints `→ Codex の仕事を起こした: thread <id> (model M / effort E…` (start), a JSON line with thread_id
# (start --json) or `→ thread <id> に次の turn を送った` (continue); the board prints `→ 起動した: Codex thread <id> (host,
# model M / effort E…` when it ran the launcher. The board's launch note reads `起動した: …` without the arrow and
# `model … / effort`, so reading the board back is not taken for a launch.
APP_LAUNCHER = "codex-app-launch.py"
APP_TEXT_RE = re.compile(r"codex-app-launch\.py['\"]?\s+(?:start|continue)\b")
_THREAD = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
THREAD_ID = re.compile(_THREAD)
APP_STARTED_RE = re.compile(r"→ Codex の仕事を起こした: thread " + _THREAD + r" \(model (\S+) / effort ([^\s,)]+)")
APP_CONTINUED_RE = re.compile(r"→ thread " + _THREAD + r" に次の turn を送った")
BOARD_STARTED_RE = re.compile(r"→ 起動した: Codex thread " + _THREAD + r" \(([^,)]*), model (\S+) / effort ([^\s,)]+)")
PERSISTED_RE = re.compile(r"Full output saved to: (\S+\.txt)")
# A copy of the request sent to the API repeats earlier tool calls and results, without a timestamp and with the
# command in its wire form (measured: a `cd <dir> &&` the harness had prefixed), so its hash differs from the
# recorded command: read as a record it counts a tool call twice and finds no receipt for the copy.
COPY_TYPES = ("api-request-blob",)


def receipt_engine():
    global _RECEIPTS
    if _RECEIPTS is None:
        path = Path(__file__).resolve().parents[1] / 'hooks' / 'headless-record-clause-nudge.py'
        spec = importlib.util.spec_from_file_location('headless_record_receipts', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _RECEIPTS = module
    return _RECEIPTS


def literal_options(engine, args, kind) -> tuple[str | None, str | None]:
    """Report literal CLI flags only; do not guess expanded or effective settings."""
    if any(arg is None for arg in args):
        return None, None  # An expansion can also introduce an option terminator.
    if kind == 'claude':
        positions = list(engine.claude_option_indices(args))
    else:
        positions, i = [], 1
        while i < len(args):
            arg = args[i] or ''
            if arg == '--':
                break
            key = arg.partition('=')[0]
            positions.append((i, key))
            i += 2 if key in engine.CODEX_VALUES and '=' not in arg else 1
    values = {'model': [], 'effort': []}
    for i, key in positions:
        target = 'model' if key == '--model' or (kind == 'codex' and key == '-m') else 'effort' if key == '--effort' else None
        if target:
            arg = args[i] or ''
            value = arg.partition('=')[2] if '=' in arg else args[i+1] if i+1 < len(args) else None
            values[target].append(value)
    return tuple(v[0] if len(v) == 1 and isinstance(v[0], str) else None for v in values.values())


def projects_dirs(explicit=None) -> list[Path]:
    """--projects-dir の指定、 無ければこの機械の全部の設定フォルダの projects/ (lib/claude_config_dirs.py)。"""
    if explicit:
        return [Path(p).expanduser() for p in explicit]
    if _ccd is not None:
        return [Path(p) for p in _ccd.projects_dirs()]
    out = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        out.append(Path(env).expanduser() / "projects")
    home = Path.home()
    out.append(home / ".claude" / "projects")
    out.extend(sorted(p / "projects" for p in home.glob(".claude-*") if p.is_dir()))
    return [p for p in dict.fromkeys(out) if p.is_dir()]


def session_files(dirs: list[Path], session: str) -> list[Path]:
    if _ccd is not None:  # 同じ file は 1 回。 写しは全部読む (受領の記録は写しごとの設定フォルダの state/ にある)
        return [Path(f) for _lab, f in _ccd.transcript_files(f"*/{glob.escape(session)}*.jsonl", roots=[str(d) for d in dirs],
                                                              copies="all")]
    found = []
    for d in dirs:
        found.extend(sorted(d.glob(f"*/{session}*.jsonl")))
    return found


def expand(path: str) -> Path:
    path = path.strip("'\"").replace("$HOME", str(Path.home())).replace("${HOME}", str(Path.home()))
    return Path(path).expanduser()


def option_value(args, name):
    """The last literal value of `name` (`--x V` or `--x=V`); None when absent or given by an expansion."""
    value = None
    for i, arg in enumerate(args):
        if arg == name:
            value = args[i + 1] if i + 1 < len(args) else None
        elif isinstance(arg, str) and arg.startswith(name + "="):
            value = arg.partition("=")[2]
    return value


def script_index(argv):
    """Index of the script in `<script> …` or `python3 [-flags] <script> …`; None when there is none."""
    i = 0
    if argv and isinstance(argv[0], str) and Path(argv[0]).name.startswith("python"):
        i = 1
        while i < len(argv) and isinstance(argv[i], str) and argv[i].startswith("-"):
            i += 1
    return i if i < len(argv) and isinstance(argv[i], str) else None


def app_launch_call(argv):
    """`codex-app-launch.py start|continue …` at an executable position → (subcommand, the rest), else None."""
    i = script_index(argv)
    if i is None or Path(argv[i]).name != APP_LAUNCHER or len(argv) <= i + 1 or argv[i + 1] not in ("start", "continue"):
        return None
    return argv[i + 1], argv[i + 2:]


def board_call(argv) -> bool:
    """board.py (the board engine or its forwarder) at an executable position."""
    i = script_index(argv)
    return i is not None and Path(argv[i]).name == "board.py"


def result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and isinstance(x.get("text"), str))
    return content if isinstance(content, str) else ""


def app_markers(text: str) -> dict:
    """The launcher's lines (start / continue, in output order) and the board's launch lines in one tool result."""
    found = {"launcher": [], "board": []}
    for line in text.splitlines():
        s = line.strip()
        m = APP_STARTED_RE.search(s)
        if m:
            found["launcher"].append({"sub": "start", "thread": m.group(1), "model": m.group(2), "effort": m.group(3)})
            continue
        m = APP_CONTINUED_RE.search(s)
        if m:
            found["launcher"].append({"sub": "continue", "thread": m.group(1)})
            continue
        m = BOARD_STARTED_RE.search(s)
        if m:
            found["board"].append({"sub": "start", "thread": m.group(1), "host": m.group(2).strip(),
                                   "model": m.group(3), "effort": m.group(4)})
            continue
        if s.startswith("{") and '"thread_id"' in s:  # start --json (not `codex exec --json`'s thread.started event)
            try:
                o = json.loads(s)
            except ValueError:
                continue
            if (isinstance(o, dict) and "instruction_sources" in o and isinstance(o.get("thread_id"), str)
                    and THREAD_ID.fullmatch(o["thread_id"])):
                found["launcher"].append({"sub": "start", "thread": o["thread_id"], "model": o.get("model"),
                                          "effort": o.get("effort"), "cwd": o.get("cwd"), "host": o.get("host")})
    return found


def tool_outputs(transcript: Path) -> dict:
    """tool_use_id → the Codex launch lines in its result. A large output that the harness saved to a file
    (`<persisted-output>` with a 2 KB preview) is read from that file."""
    out = {}
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"tool_result"' not in line or ("thread" not in line and "persisted-output" not in line):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") in COPY_TYPES:
                continue
            content = (obj.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict) or b.get("type") != "tool_result" or not isinstance(b.get("tool_use_id"), str):
                    continue
                text = result_text(b)
                saved = PERSISTED_RE.search(text) if "persisted-output" in text else None
                if saved:
                    try:
                        p = Path(saved.group(1))
                        if p.is_file() and p.stat().st_size <= 8_000_000:
                            text = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        pass
                found = app_markers(text)
                if found["launcher"] or found["board"]:
                    out.setdefault(b["tool_use_id"], found)
    return out


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def rollout_id(path: Path) -> str:
    """The thread id at the end of a rollout's name (`rollout-<time>-<id>.jsonl`, or `.jsonl.zst` once Codex compressed it)."""
    name = path.name[: -len(".zst")] if path.name.endswith(".jsonl.zst") else path.name
    return name[: -len(".jsonl")][-36:] if name.endswith(".jsonl") else ""


def rollouts(thread) -> list[Path]:
    """The rollout file of a thread id, or of a unique id prefix (8+ characters, as `continue --thread` takes).
    Codex compresses old rollouts to .jsonl.zst; both forms are found."""
    if not isinstance(thread, str) or not re.fullmatch(r"[0-9a-f][0-9a-f-]{7,35}", thread):
        return []
    home, found = codex_home(), []
    for pattern in (f"sessions/*/*/*/rollout-*{thread}*.jsonl", f"archived_sessions/rollout-*{thread}*.jsonl"):
        for p in [*home.glob(pattern), *home.glob(pattern + ".zst")]:
            if rollout_id(p).startswith(thread) and THREAD_ID.fullmatch(rollout_id(p)):
                found.append(p)
    return sorted(found) if len({rollout_id(p) for p in found}) == 1 else []


def _first_line(path: Path) -> str:
    if not path.name.endswith(".jsonl.zst"):
        with path.open(encoding="utf-8", errors="replace") as fh:
            return fh.readline()
    if _cj is None:
        ROLLOUT_UNREADABLE.setdefault("no-means", set()).add(str(path))
        return ""
    import collections
    tally = collections.Counter()
    try:
        with _cj.open_lines(path, errors="replace", tally=tally) as lines:
            return next(iter(lines), "")
    finally:
        for reason in tally:
            ROLLOUT_UNREADABLE.setdefault(reason, set()).add(str(path))


def rollout_cwd(path: Path):
    """The working directory in a rollout's first record (session_meta)."""
    try:
        meta = json.loads(_first_line(path))
    except (OSError, ValueError):
        return None
    payload = meta.get("payload") if isinstance(meta, dict) and meta.get("type") == "session_meta" else None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return Path(cwd) if isinstance(cwd, str) and cwd else None


def epoch(ts):
    try:
        return _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def app_launches(obj: dict, cmd: str, sid: str, tool_id: str, apps: list, board: bool, found) -> list[dict]:
    """The Codex app launches of one tool call: the launcher at an executable position (thread from its output, or
    `continue --thread`), and board.py whose output carries the board's launch line. Launch lines without either at an
    executable position, and the launcher named only inside a string, are text candidates."""
    found = found or {"launcher": [], "board": []}
    cds = re.findall(r"(?:^|[\s;&|(])cd\s+((?:\"[^\"]+\"|'[^']+'|[^\s;&|]+))", cmd)
    here = expand(cds[-1]) if cds else None  # a relative --cwd / --prompt-file is read from the shell's directory
    if not (here and here.is_absolute()):
        here = Path(obj["cwd"]) if obj.get("cwd") else None
    base = {"ts": obj.get("timestamp"), "kind": "codex-app", "config": None, "marker": MARKER in cmd, "runner": False,
            "parent_session": sid, "tool_use_id": tool_id, "receipt": None, "worker_session": None, "shell_cwd": here,
            "command_sha256": hashlib.sha256(cmd.encode("utf-8", errors="surrogatepass")).hexdigest()}
    rows, lines = [], {sub: [x for x in found["launcher"] if x["sub"] == sub] for sub in ("start", "continue")}
    for sub, rest in apps:
        seen = lines[sub].pop(0) if lines[sub] else {}
        thread = seen.get("thread") or (option_value(rest, "--thread") if sub == "continue" else None)
        rows.append(dict(base, sub=sub, via="launcher", detection="execution", thread=thread, seen=bool(seen),
                         cwd=option_value(rest, "--cwd") or seen.get("cwd"),
                         model=seen.get("model") or option_value(rest, "--model"),
                         effort=seen.get("effort") or option_value(rest, "--effort"),
                         prompt_file=option_value(rest, "--prompt-file"), host=seen.get("host") or option_value(rest, "--host")))
    if board:
        for seen in found["board"]:
            rows.append(dict(base, sub="start", via="board", detection="execution", thread=seen["thread"], seen=True, cwd=None,
                             model=seen.get("model"), effort=seen.get("effort"), prompt_file=None, host=seen.get("host")))
    note = None
    if not rows and (found["launcher"] or found["board"]):
        note = "出力に Codex の起動の行があるが、 command の実行位置に起動の道具・board.py が無い (記録や log を読んだ出力か、 未対応の構文)"
    elif not rows and APP_TEXT_RE.search(cmd):
        note = "command の文字列に codex-app-launch.py start|continue が出る (引用か、 未対応の構文)"
    if note:
        rows.append(dict(base, sub=None, via=None, detection="text", thread=None, seen=False, cwd=None, model=None,
                         effort=None, prompt_file=None, host=None, note=note))
    for j, row in enumerate(rows):
        row["launch_index"] = f"app-{j}"
        row["rollouts"] = rollouts(row["thread"]) if row["detection"] == "execution" else []
        if row["rollouts"]:
            row["thread"] = rollout_id(row["rollouts"][0])  # a `--thread` prefix becomes the full id
        cwd = row["cwd"]
        if isinstance(cwd, str):
            cwd = expand(cwd)
            row["cwd"] = Path(os.path.normpath(here / cwd)) if not cwd.is_absolute() and here else cwd
        elif row["rollouts"]:
            row["cwd"] = rollout_cwd(row["rollouts"][0])
    return rows


def launches(transcript: Path) -> list[dict]:
    out = []
    outputs = tool_outputs(transcript)
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"Bash"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") in COPY_TYPES:
                continue
            content = (obj.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict) or b.get("type") != "tool_use" or b.get("name") != "Bash":
                    continue
                cmd = str((b.get("input") or {}).get("command", ""))
                sid = str(obj.get('sessionId') or obj.get('session_id') or transcript.stem)
                tool_id = b.get('id') if isinstance(b.get('id'), str) else ''
                parsed, apps, board = [], [], False
                try:
                    engine = receipt_engine()
                    receipts = engine.read_receipts(engine.receipt_root(transcript), sid, tool_id, cmd)
                    try:
                        for words in engine.shell_commands(cmd):
                            position = engine.executable_index(words)
                            argv = [word.value for word in words[position:]] if position is not None else []
                            app = app_launch_call(argv)
                            if app:
                                apps.append(app)
                                continue
                            board = board or board_call(argv)
                            runner = False
                            if argv and argv[0] and Path(argv[0]).name.startswith('python') and len(argv) > 2:
                                if argv[1] and Path(argv[1]).name == 'headless-record-clause-nudge.py' and argv[2] == '--run':
                                    argv, runner = argv[3:], True
                            kind = engine.worker_kind(argv)
                            if kind:
                                parsed.append((kind, argv, runner))
                    except ValueError:
                        parsed, apps, board = [], [], False
                except Exception:
                    receipts = []  # Legacy inspection stays available; no receipt means unverified.
                out.extend(app_launches(obj, cmd, sid, tool_id, apps, board, outputs.get(tool_id)))
                m = LAUNCH_RE.search(cmd)
                if not m and not receipts and not parsed:
                    continue
                cds = re.findall(r"(?:^|[\s;&|(])cd\s+((?:\"[^\"]+\"|'[^']+'|[^\s;&|]+))", cmd[:m.start() + 1] if m else cmd)
                cwd = expand(cds[-1]) if cds else (Path(obj["cwd"]) if obj.get("cwd") else None)
                cfg = re.search(r"CLAUDE_CONFIG_DIR=(\S+)", cmd)
                by_index = {r.get('launch_index', 0): r for r in receipts}
                entries, automatic = [], 0
                for item in parsed:
                    receipt = None if item[2] else by_index.pop(automatic, None)
                    automatic += not item[2]
                    entries.append((item, receipt))
                entries.extend((None, r) for r in by_index.values())
                for index, (item, receipt) in enumerate(entries or [(None, None)]):
                    kind = (receipt or {}).get('kind') or (item[0] if item else
                            'codex' if m and 'codex' in m.group(1) else 'claude' if m else 'unknown')
                    model = effort = None
                    if item and item[0] == kind:
                        model, effort = literal_options(engine, item[1], kind)
                    worker = (receipt or {}).get('worker') or {}
                    if not isinstance(worker, dict):
                        worker = {}
                    out.append({
                        "ts": obj.get("timestamp"),
                        "cwd": Path(worker['cwd']) if isinstance(worker.get('cwd'), str) else cwd,
                        "kind": kind,
                        "config": Path(worker['config_dir']) if isinstance(worker.get('config_dir'), str) else expand(cfg.group(1)) if cfg else None,
                        "model": model, "effort": effort,
                        "marker": MARKER in cmd,
                        "runner": item[2] if item else False,
                        "detection": 'execution' if item or receipt else 'text',
                        "parent_session": sid, "tool_use_id": tool_id,
                        "command_sha256": hashlib.sha256(cmd.encode('utf-8', errors='surrogatepass')).hexdigest(),
                        "launch_index": index, "receipt": receipt,
                        "worker_session": worker.get('session_id'),
                    })
    return out


def promise(launch: dict) -> str:
    receipt = launch.get('receipt')
    if receipt:
        state = receipt.get('state')
        resume = (receipt.get('worker') or {}).get('resume')
        if state in ('added', 'present'):
            return f"注入記録: {state} (runner の処理を照合済み、モデル受領は未確認{'、resume snapshot に注意' if resume else ''})"
        return f"⚠️ 注入記録: {state} (runner の注入成功を確認できない。起動結果を確認する)"
    app = launch.get("kind") == "codex-app"
    if launch.get("via") == "board":
        return "掲示板の依頼の worker = 報告は掲示板の submit (記録の約束は依頼の spec と hand-off 文。 依頼の thread を inbox / show で確かめる)"
    if launch["marker"]:
        return "起動文に約束の MARKER あり (内容・受領は未確認)"
    if app and launch.get("prompt_file"):
        prompt = expand(launch["prompt_file"])
        if not prompt.is_absolute() and launch.get("shell_cwd"):
            prompt = launch["shell_cwd"] / prompt
        try:
            if MARKER in prompt.read_text(encoding="utf-8", errors="replace"):
                return "起動文 file に約束の MARKER あり (内容・受領は未確認)"
        except OSError:
            pass
    if launch.get("runner"):
        return "起動文に自動注入 runner の指定あり (受領は worker の報告・成果物で確認)"
    cwd = launch["cwd"]
    for name in ("CLAUDE.md", "AGENTS.md"):
        p = cwd / name if cwd else None
        if p and p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            # Require the three record items together, not a mere HANDOFF reference.
            for paragraph in re.split(r'\n\s*\n', text):
                low = paragraph.lower()
                japanese = all(t in paragraph for t in ('捨てた案', '気づいた', '確かめていない'))
                english = all(t in low for t in ('discarded', 'noticed', 'unverified'))
                if ('HANDOFF' in paragraph or MARKER in paragraph) and (japanese or english):
                    return f"作業 dir の {name} に3項目の記録条項あり (読込・受領は未確認)"
    if app:
        return "⚠️ 記録の約束の根拠が無い (起動の道具の起動文には自動で入らない = 起動文 file か作業 dir の AGENTS.md に書く。 worker の報告・成果物を確認する)"
    return "⚠️ 記録から約束の受領を確認できない (hook の有効性・起動形式と、worker の報告・成果物を確認する)"


def worker_transcripts(launch: dict) -> list[Path]:
    if launch.get("kind") == "codex-app":  # the thread id comes from this tool call's own output (or --thread)
        since, out = epoch(launch.get("ts")), []
        for path in launch.get("rollouts") or []:
            try:
                if since is None or path.stat().st_mtime >= since - 1:
                    out.append(path)
            except OSError:
                pass
        return out
    cwd = launch["cwd"]
    worker_id = launch.get('worker_session')
    issued = (launch.get('receipt') or {}).get('issued_ns')
    if ((launch.get('receipt') or {}).get('state') not in ('added', 'present')
            or launch.get('kind') != 'claude' or not cwd or not launch.get('config')
            or not isinstance(worker_id, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', worker_id)
            or not isinstance(issued, int) or issued <= 0):
        return []
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    path = launch['config'] / 'projects' / slug / (worker_id + '.jsonl')
    try:
        return [path] if path.stat().st_mtime_ns >= issued and path.is_file() else []
    except OSError:
        return []


def report(launch: dict, n: int, max_chars: int) -> None:
    app = launch.get('kind') == 'codex-app'
    if launch.get('detection') == 'text':
        print(f"== 文字列候補 {n}: {launch['ts']}  {launch['kind']} (実行位置は未確認)")
        if app:
            print(f"   {launch.get('note')}。 起動と数えず、元の tool call を確認する。")
        else:
            print("   引用・引数内の言及、または未対応構文。起動と数えず、元の tool call を確認する。")
        print(f"   tool call: {launch.get('tool_use_id') or 'ID なし'}")
        return
    cwd = launch["cwd"]
    if app:
        print(f"== 起動 {n}: {launch['ts']}  codex-app {launch['sub']}  thread={launch['thread'] or '不明'}"
              f"  model={launch['model'] or '未特定'}  effort={launch['effort'] or '未特定'}")
        how = "掲示板 (board.py) が起動の道具を呼んだ" if launch.get('via') == 'board' else "起動の道具 codex-app-launch.py"
        print(f"   起こし方: {how} = Codex アプリの一覧に出る thread" + (f" (機械 {launch['host']})" if launch.get('host') else ""))
        if not launch.get('seen'):
            print("   ⚠️ 起動の出力に thread の行が無い (起動が止まったか、 出力を切った)"
                  + (" = --thread の値で引いた" if launch['thread'] else ""))
        ts = worker_transcripts(launch)
        print(f"   worker の会話記録 (rollout {len(ts)}): " + (", ".join(str(t) for t in ts)
              or "この機械に起動以降の rollout が無い (別の機械の thread か、 thread id が不明)"))
    else:
        print(f"== 起動 {n}: {launch['ts']}  {launch['kind']}  model指定={launch['model'] or '未特定'}  effort指定={launch['effort'] or '未特定'}")
    print(f"   作業 dir: {cwd if cwd else '不明 (command に cd が無く、 記録に cwd も無い)'}")
    print(f"   記録の約束: {promise(launch)}")
    if not cwd or not cwd.is_dir():
        print("   作業 dir が今は無い")
        return
    have = [n_ for n_ in TOP if (cwd / n_).exists()] + [p.name for p in sorted(cwd.glob("STAGE*-RESULTS.md"))]
    if (cwd / "scratch" / "hoist-candidates.md").exists():
        have.append("scratch/hoist-candidates.md")
    print("   作業 dir の成果物候補: " + (", ".join(have) or "なし"))
    scripts = [str(p.relative_to(cwd)) for sub in ("checks", "scratch") for p in sorted((cwd / sub).glob("*.py"))]
    print(f"   作業 dir の script 候補・作成者未確認 ({len(scripts)}): " + (", ".join(scripts) or "なし"))
    if not app:
        ts = worker_transcripts(launch)
        print(f"   worker の会話記録 ({len(ts)}): " + (", ".join(str(t) for t in ts) or "起動と結び付く session ID / 記録なし (同じ作業 dir の他 session は列挙しない)"))
    for name in TEXTS:
        p = cwd / name
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            cut = text if max_chars == 0 else text[:max_chars]
            print(f"   ---- {name} ({len(text)} 字{'' if cut == text else f'、 先頭 {max_chars} 字'})")
            print(cut.rstrip())


def run(session: str, dirs: list[Path], max_chars: int) -> int:
    ROLLOUT_UNREADABLE.clear()
    cleanup(dirs)
    files = session_files(dirs, session)
    if not files:
        print(f"session {session} の記録が見つからない (見た dir: {', '.join(map(str, dirs))})")
        return 1
    all_l = []
    for f in files:
        all_l.extend(launches(f))
    seen, uniq = {}, []

    def evidence_rank(item):
        receipt = item.get('receipt')
        if not receipt:
            return (0, 0)
        if receipt.get('state') == 'unreadable':
            return (2, 0)  # Do not hide corrupt evidence behind a successful copy.
        return (1, receipt.get('issued_ns', 0))

    for l in all_l:  # Native tool identity keeps launches separate; legacy rows also use cwd/time.
        key = (l.get('parent_session'), l.get('tool_use_id'), l.get('command_sha256'), l.get('launch_index'))
        if not l.get('tool_use_id'):
            key += (str(l['cwd']), l['ts'])
        if key not in seen:
            seen[key] = len(uniq)
            uniq.append(l)
        elif evidence_rank(l) > evidence_rank(uniq[seen[key]]):
            uniq[seen[key]] = l
    print(f"見た記録: {', '.join(str(f) for f in files)}")
    count = sum(l.get('detection') != 'text' for l in uniq)
    apps = sum(l.get('detection') != 'text' and l.get('kind') == 'codex-app' for l in uniq)
    print(f"headless・Codex アプリの起動候補: {count} 件 (うち Codex アプリ {apps} 件) / 文字列候補: {len(uniq) - count} 件 (session {session})")
    for i, l in enumerate(uniq, 1):
        report(l, i, max_chars)
    if ROLLOUT_UNREADABLE:
        reasons = {"no-means": "展開の手段が無い", "failed": "展開の途中で失敗"}
        print("⚠️ 圧縮した rollout (.jsonl.zst) を読めなかった = "
              + " / ".join(f"{reasons.get(k, k)} {len(v)} 本" for k, v in sorted(ROLLOUT_UNREADABLE.items()))
              + " (その起動の作業 dir は rollout から取れていない)")
    return 0


def cleanup(dirs):
    engine = receipt_engine()
    for root in dict.fromkeys(d.parent / 'state' / 'headless-record-clause' for d in dirs):
        result = engine.prune_receipts(root, dirs)
        if result['removed'] or result['errors']:
            print(f"注入記録の整理: {root}: 削除 {result['removed']} 件 / 保留を伴うエラー {result['errors']} 件")


def receipt_regression(repo):
    import shlex
    import subprocess
    hook = repo / 'hooks/headless-record-clause-nudge.py'
    reporter = repo / 'scripts/headless-worker-reports.py'
    with tempfile.TemporaryDirectory(prefix='headless-receipt-test-') as td:
        root = Path(td).resolve()
        parent_cfg, child_cfg, work = root/'parent', root/'child', root/'work'
        work.mkdir()
        parent_log = parent_cfg/'projects'/'synthetic'/'parent-synthetic.jsonl'
        parent_log.parent.mkdir(parents=True)
        parent_log.write_text('')
        fake_bin = root/'bin'
        fake_bin.mkdir()
        for name in ('claude', 'codex'):
            fake = fake_bin/name
            fake.write_text('#!'+sys.executable+'''\nimport json,sys,os,re
from pathlib import Path
if '--session-id' in sys.argv:
    sid=sys.argv[sys.argv.index('--session-id')+1]
    log=Path(os.environ['CLAUDE_CONFIG_DIR'])/'projects'/re.sub(r'[^A-Za-z0-9]', '-', os.getcwd())/(sid+'.jsonl')
    log.parent.mkdir(parents=True,exist_ok=True)
    log.write_text('{}\\n')
print(json.dumps({"argv":sys.argv[1:],"stdin":sys.stdin.read()}))
''')
            fake.chmod(0o755)
        env = dict(os.environ, PATH=str(fake_bin)+os.pathsep+os.environ['PATH'],
                   CLAUDE_CONFIG_DIR=str(parent_cfg))

        def launch(command, tool_id, execute=True, stdin=''):
            ev = {'session_id':'parent-synthetic','tool_use_id':tool_id,
                  'hook_event_name':'PreToolUse','tool_name':'Bash','cwd':str(work),
                  'transcript_path':str(parent_log),'tool_input':{'command':command}}
            p = subprocess.run([sys.executable,str(hook)],input=json.dumps(ev),text=True,capture_output=True,env=env,check=True)
            updated = json.loads(p.stdout)['hookSpecificOutput']['updatedInput']['command']
            if execute:
                done = subprocess.run(['/bin/bash','-c',updated],cwd=work,env=env,input=stdin,text=True,capture_output=True)
            else:
                done = None
            # The harness persists the ORIGINAL tool input, never updatedInput.
            row = {'sessionId':'parent-synthetic','timestamp':'2042-01-01T00:00:00Z','cwd':str(work),
                   'message':{'content':[{'type':'tool_use','id':tool_id,'name':'Bash','input':{'command':command}}]}}
            parent_log.write_text(json.dumps(row)+'\n')
            return done, row

        def report():
            return subprocess.run([sys.executable,str(reporter),'parent-synthetic','--projects-dir',str(parent_cfg/'projects')],env=env,text=True,capture_output=True,check=True).stdout

        cmd = 'CLAUDE_CONFIG_DIR='+shlex.quote(str(child_cfg))+" claude -p 'SYNTHETIC_PROMPT_PRIVATE'"
        done, row = launch(cmd, 'tool-one')
        assert done.returncode == 0 and '記録の約束' in json.dumps(json.loads(done.stdout),ensure_ascii=False)
        result = report()
        assert '注入記録: added' in result and '⚠️' not in result, result
        print('OK original transcript input joins the actual runner receipt')
        shadow = root/'shadow'/'projects'/'synthetic'/parent_log.name
        shadow.parent.mkdir(parents=True)
        shadow.write_text(parent_log.read_text())
        duplicate = subprocess.run([sys.executable,str(reporter),'parent-synthetic',
                                    '--projects-dir',str(root/'shadow'/'projects'),
                                    '--projects-dir',str(parent_cfg/'projects')],env=env,text=True,capture_output=True,check=True).stdout
        assert duplicate.count('注入記録: added') == 1 and '⚠️' not in duplicate, duplicate
        print('OK a duplicate transcript without receipts cannot hide matching execution evidence')
        receipts = list((parent_cfg/'state/headless-record-clause').rglob('*.json'))
        assert receipts and all('SYNTHETIC_PROMPT_PRIVATE' not in p.read_text() for p in receipts)
        print('OK receipt stores no prompt text')
        for field in ('id','command','session'):
            changed = json.loads(json.dumps(row))
            block = changed['message']['content'][0]
            if field == 'id':
                block['id'] = 'another-tool'
            elif field == 'command':
                block['input']['command'] += ' '
            else:
                changed['sessionId'] = 'another-session'
            parent_log.write_text(json.dumps(changed)+'\n')
            assert '注入記録: added' not in report(), field
        print('OK mismatched session, tool id and original command never borrow a receipt')
        launch(cmd, 'tool-one', execute=False)
        assert '注入記録: selected' in report() and '注入記録: added' not in report()
        print('OK a new unexecuted attempt cannot reuse an older success')

        launch('claude -p pending', 'tool-pending', execute=False)
        assert '注入記録: selected' in report() and '⚠️' in report()
        done, _ = launch('codex exec -', 'tool-stdin', stdin='original stdin task')
        assert done.returncode == 0 and '注入記録: added' in report()
        done, _ = launch('/nonexistent/claude -p task', 'tool-failure')
        assert done.returncode == 127 and '注入記録: exec_failed' in report() and '⚠️' in report()
        failed = next(p for p in (parent_cfg/'state/headless-record-clause').rglob('*-failed.json')
                      if json.loads(p.read_text())['tool_use_id'] == 'tool-failure')
        late = json.loads(failed.read_text())
        late['state'] = 'added'
        failed.with_name(failed.name.replace('-failed.json','-applied.json')).write_text(json.dumps(late))
        assert '注入記録: exec_failed' in report() and '注入記録: added' not in report()
        print('OK selection, stdin delivery and launch failure remain distinct')

        launch('claude -p first; codex exec second', 'tool-two-workers')
        result = report()
        assert result.count('== 起動 ') == 2 and result.count('注入記録: added') == 2, result
        print('OK both workers in one tool call keep their own receipts')
        launch(shlex.quote(sys.executable)+' '+shlex.quote(str(hook))+' --run claude -p explicit; codex exec automatic', 'tool-mixed-wrapper')
        result = report()
        assert result.count('== 起動 ') == 2 and result.count('注入記録: added') == 1, result
        assert result.index('自動注入 runner の指定') < result.index('注入記録: added'), result
        print('OK an explicit wrapper does not shift the automatic launch receipt index')
        launch('claude --model sample-a -p first; codex exec --model sample-b second', 'tool-models')
        result = report()
        assert 'sample-a' in result and 'sample-b' in result, result
        launch("claude -p 'explain --model sample-decoy' --model sample-real", 'tool-model-mention')
        result = report()
        assert 'sample-real' in result and 'sample-decoy' not in result, result
        launch('flag=--; claude -p "$flag" --model=sample-prompt', 'tool-dynamic-option-boundary')
        assert 'sample-prompt' not in report()
        print('OK model arguments belong to their own launch, not another launch or prompt text')

        # A bare HANDOFF mention never stands in for the three-item obligation.
        (work/'CLAUDE.md').write_text('See old HANDOFF.md files for background.\n')
        row['message']['content'][0]['id']='unrecorded'
        parent_log.write_text(json.dumps(row)+'\n')
        assert '⚠️' in report() and 'HANDOFF を求めている' not in report()
        (work/'CLAUDE.md').write_text('Write HANDOFF.md: options you discarded and why, what you noticed along the way, and what remains unverified or assumed.\n')
        assert '記録条項' in report() and '⚠️' not in report()
        print('OK HANDOFF mentions and actual record requirements are distinguished')

        slug = ''.join(c if c.isascii() and c.isalnum() else '-' for c in str(work))
        child_logs = child_cfg/'projects'/slug
        child_logs.mkdir(parents=True)
        child_id='44444444-4444-4444-8444-444444444444'
        (child_logs/'unrelated-session.jsonl').write_text('{}\n')
        (child_logs/(child_id+'.jsonl')).write_text('{}\n')
        launch(cmd,'tool-no-child-id')
        assert 'unrelated-session.jsonl' not in report() and child_id+'.jsonl' not in report()
        launch(cmd+' --session-id '+child_id,'tool-child-id')
        result=report()
        assert child_id+'.jsonl' in result and 'unrelated-session.jsonl' not in result, result
        os.utime(child_logs/(child_id+'.jsonl'), (1,1))
        assert child_id+'.jsonl' not in report()
        print('OK only a linked child session is listed')
        done,_=launch("claude -p 'task: 記録の約束'",'tool-manual-promise')
        assert '--append-system-prompt' not in json.loads(done.stdout)['argv']
        assert '注入記録: present' in report()
        done,_=launch("claude --bare --no-session-persistence -p 'task: 記録の約束'",'tool-manual-with-flags')
        assert '--append-system-prompt' not in json.loads(done.stdout)['argv']
        print('OK a clause marker in the prompt does not cause a second clause')
        done,_=launch("claude --add-dir '記録の約束' -p task",'tool-marker-in-path')
        assert '--append-system-prompt' in json.loads(done.stdout)['argv']
        print('OK a marker in an option value does not masquerade as a prompt clause')
        applied = next(p for p in (parent_cfg/'state/headless-record-clause').rglob('*-applied.json')
                       if json.loads(p.read_text())['tool_use_id'] == 'tool-marker-in-path')
        applied.write_text('{')
        assert '注入記録: unreadable' in report() and '⚠️' in report()
        print('OK a malformed receipt is uncertainty, never a successful injection')

        blocked = root/'blocked'
        (blocked/'projects'/'synthetic').mkdir(parents=True)
        (blocked/'state').write_text('not a directory')
        ev={'session_id':'synthetic-failure','tool_use_id':'tool-log-failure','tool_name':'Bash',
            'transcript_path':str(blocked/'projects'/'synthetic'/'synthetic-failure.jsonl'),
            'tool_input':{'command':'claude -p task'}}
        p=subprocess.run([sys.executable,str(hook)],input=json.dumps(ev),env=env,text=True,capture_output=True,check=True)
        rewritten=json.loads(p.stdout)['hookSpecificOutput']['updatedInput']['command']
        done=subprocess.run(['/bin/bash','-c',rewritten],cwd=work,env=env,input='',text=True,capture_output=True)
        assert done.returncode == 0 and '記録の約束' in json.dumps(json.loads(done.stdout),ensure_ascii=False)
        print('OK a receipt write failure does not block or contaminate the worker')
    return 0



def followup_regression(repo, case=None):
    """Behavioral regressions runnable against an unmodified old checkout."""
    import subprocess
    import time
    import shlex
    reporter = repo / 'scripts/headless-worker-reports.py'
    hook = repo / 'hooks/headless-record-clause-nudge.py'
    with tempfile.TemporaryDirectory(prefix='headless-followup-test-') as td:
        root = Path(td).resolve()
        projects = root/'cfg'/'projects'
        logs = projects/'synthetic'
        logs.mkdir(parents=True)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(projects.parent))

        def row(command, tool='synthetic-tool', sid='synthetic-parent'):
            return json.dumps({'sessionId':sid, 'timestamp':'SYNTHETIC', 'cwd':str(root),
                               'message':{'content':[{'type':'tool_use','name':'Bash','id':tool,
                                                      'input':{'command':command}}]}})+'\n'

        def output(sid, more=()):
            return subprocess.run([sys.executable,str(reporter),sid,'--projects-dir',str(projects),*more],
                                  env=env,text=True,capture_output=True,check=True).stdout

        if case in (None, 'detection'):
            log = logs/'synthetic-parent.jsonl'
            mentions = [
                "git commit -m 'mention claude -p in prose'",
                "echo 'use codex exec for this task'",
                "python3 -c 'print(\"codex exec sample\")'",
                "grep 'claude -p' sample.txt",
                "cat <<'END'\nclaude -p sample\nEND\n",
                "# codex exec sample\necho done",
                "python3 board.py request --summary 'run codex exec sample'",
                "cat <<< 'codex exec sample'",
                "export NOTE='codex exec sample'",
            ]
            for n, command in enumerate(mentions):
                log.write_text(row(command, 'mention-'+str(n)))
                result = output('synthetic-parent')
                assert '== 起動 ' not in result, (command,result)
                if LAUNCH_RE.search(command):
                    assert '== 文字列候補 ' in result, (command,result)
                assert '作業 dir の成果物' not in result, result
            print('OK quoted arguments, commit messages, comments and heredoc data are not counted as launches')
            positive = [
                'claude -p task', 'claude --print task', 'codex exec task',
                'cd /tmp && CLAUDE_CONFIG_DIR=/tmp/cfg claude --model sample -p task',
                'printf task | codex exec -', '(claude -p task)',
                'env NOTE=sample command claude -p task', '/opt/sample/claude -p task',
                'codex -m sample exec task', 'codex e task',
                '/opt/sample/App.app/Contents/MacOS/codex exec task',
                'claude -p "$(cat prompt.txt)" < /dev/null',
                "python3 /opt/sample/headless-record-clause-nudge.py --run claude -p task",
            ]
            log.write_text(''.join(row(c,'positive-'+str(n)) for n,c in enumerate(positive)))
            result = output('synthetic-parent')
            assert result.count('== 起動 ') == len(positive), result
            log.write_text(row('claude -p first; codex exec second'))
            assert output('synthetic-parent').count('== 起動 ') == 2
            # Unsupported or nested execution still has a visible manual-inspection route.
            for c in ('if true; then claude -p task; fi', 'bash -c "cd /tmp; codex exec task"',
                      'cd "$SB" && caffeinate -i /opt/sample/codex exec --json -o out.md resume 0123abcd "task" < /dev/null',
                      'echo "$(codex exec task)"'):
                log.write_text(row(c))
                fallback = output('synthetic-parent')
                assert '== 文字列候補 ' in fallback and '== 起動 ' not in fallback, c
            print('OK executable-position positives, multiple launches and unsupported-syntax fallback remain visible')

        if case in (None, 'retention'):
            state = projects.parent/'state'/'headless-record-clause'
            old = time.time_ns() - 40*24*60*60*1_000_000_000

            def make(sid, *, age=True, legacy=False):
                log = logs/(sid+'.jsonl')
                log.write_text('{}\n')
                ev = {'hook_event_name':'PreToolUse','tool_name':'Bash','session_id':sid,
                      'tool_use_id':'synthetic-tool','transcript_path':str(log),
                      'tool_input':{'command':'claude -p synthetic'}}
                p = subprocess.run([sys.executable,str(hook)],input=json.dumps(ev),env=env,
                                   text=True,capture_output=True,check=True)
                assert 'updatedInput' in p.stdout
                paths = list((state/hashlib.sha256(sid.encode()).hexdigest()).glob('*.json'))
                assert paths
                for path in paths:
                    receipt = json.loads(path.read_text())
                    if age:
                        receipt['issued_ns'] = old
                    if legacy:
                        receipt.pop('parent_transcript',None)
                    path.write_text(json.dumps(receipt))
                    if age:
                        os.utime(path,ns=(old,old))
                return log, paths

            live_log, live = make('live-parent')
            gone_log, gone = make('gone-parent')
            recent_log, recent = make('recent-parent',age=False)
            legacy_log, legacy = make('legacy-parent',legacy=True)
            corrupt_log, corrupt = make('corrupt-parent')
            copy_log, copied = make('copied-parent')
            fresh_log, fresh = make('fresh-phase-parent')
            # A new phase for a long-lived attempt must survive the grace period.
            os.utime(fresh[0],None)
            corrupt[0].write_text('{broken')
            os.utime(corrupt[0],ns=(old,old))
            shadow = root/'shadow'/'projects'/'moved'
            shadow.mkdir(parents=True)
            (shadow/copy_log.name).write_text(copy_log.read_text())
            more = ['--projects-dir',str(shadow.parent)]
            output('live-parent',more)
            assert all(p.exists() for p in live+gone+recent+legacy+corrupt+copied+fresh)
            for p in (gone_log,recent_log,legacy_log,corrupt_log,copy_log,fresh_log):
                p.unlink()
            result = output('live-parent',more)
            assert not any(p.exists() for p in gone), 'old orphan receipt was not removed: '+result
            assert all(p.exists() for p in live+recent+legacy+corrupt+copied+fresh)
            assert live_log.exists() and not gone_log.exists()
            assert not gone[0].parent.exists(), 'empty receipt dir left behind'
            output('live-parent',more)  # idempotent
            print('OK old orphans are pruned; live, young, copied, legacy, corrupt and freshly written evidence survives')
            # Symlinked metadata never grants deletion authority over another directory.
            target = root/'unrelated'
            target.mkdir()
            sentinel = target/'keep.json'
            sentinel.write_text('keep')
            (state/('a'*64)).symlink_to(target,target_is_directory=True)
            output('live-parent',more)
            assert sentinel.read_text() == 'keep'
            print('OK cleanup is idempotent and does not follow receipt-directory symlinks')
    return 0


def app_launch_regression() -> None:
    """Codex app launches: the launcher's start / continue, the board running it, and lookalikes that are not launches."""
    import contextlib
    import io
    a, b, c, d, e, f = (f"{n}1a15c9b-cf1d-74d2-8507-0745d7d7a1b{n}" for n in "abcdef")
    old_home = os.environ.get("CODEX_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["CODEX_HOME"] = str(tmp / "codex")
        try:
            box, board_cwd, gone = tmp / "box", tmp / "workspace", tmp / "gone"
            box.mkdir()
            board_cwd.mkdir()
            (box / "prompt.txt").write_text(f"review the copy\n{MARKER}: write HANDOFF.md\n")
            day = tmp / "codex" / "sessions" / "2042" / "01" / "02"
            day.mkdir(parents=True)
            for tid, cwd in ((a, box), (b, board_cwd), (e, board_cwd)):
                (day / f"rollout-2042-01-02T10-00-00-{tid}.jsonl").write_text(
                    json.dumps({"type": "session_meta", "payload": {"id": tid, "cwd": str(cwd)}}) + "\n")
            archived = tmp / "codex" / "archived_sessions"
            archived.mkdir()
            (archived / f"rollout-2042-01-02T11-00-00-{d}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": d, "cwd": str(gone)}}) + "\n")
            saved = tmp / "tool-results" / "big.txt"
            saved.parent.mkdir()
            saved.write_text("x\n" * 2000 + f"→ 起動した: Codex thread {e} (Mac-mini, model m-big / effort high, アプリに開かせた)。\n")
            launcher = "/opt/sample/claude-config/scripts/codex-app-launch.py"
            rows, n = [], 0

            def call(cmd, out, ts="2020-01-01T00:00:00Z", listed=False, line_type="assistant"):
                nonlocal n
                n += 1
                tid = f"tool-app-{n}"
                rows.append(json.dumps({"type": line_type, "timestamp": ts, "sessionId": "app-parent", "cwd": str(tmp),
                                        "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                                 "input": {"command": cmd}}]}}, ensure_ascii=False))
                body = [{"type": "text", "text": out}] if listed else out
                rows.append(json.dumps({"type": "user", "timestamp": ts, "sessionId": "app-parent",
                                        "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": body}]}},
                                       ensure_ascii=False))
                return tid

            start = call(f"python3 {launcher} start --cwd {box} --prompt-file {box}/prompt.txt --model m-ask --effort low"
                         " --name 'sealed judge' --sealed 2>&1 | head -5",
                         f"→ Codex の仕事を起こした: thread {a} (model m-run / effort xhigh ⚠️ 頼んだ値 m-ask / low と違う, cwd {box})\n"
                         f"  アプリ: 左の「最近の項目」 に載せた (アプリに開かせた) open 'codex://threads/{a}?hostId=local'")
            cont = call(f"python3 {launcher} continue --thread {a[:8]} --prompt-file round2.txt --effort high",
                        "⛔ 共有の Codex daemon に繋がらない。 アプリでその thread を開き、 起動文を貼って送る")
            board = call("python3 ~/Claude/agent-board/scripts/board.py request --to codex --to-session role-x-y --summary s 2>&1 | tail -25",
                         f"→ 受け手を Codex アプリに出る形で起こす (… cwd {board_cwd} …):\n  python3 {launcher} start --cwd {board_cwd} …\n"
                         f"→ 起動した: Codex thread {b} (mac mini, model m-board / effort low, アプリに開かせた)。 読んだ指示 file: (なし)\n"
                         "posted 20420101T000000Z-claude-000000 (起動の記録)", listed=True)
            call("python3 board.py show --thread t",
                 f"note: 起動した: Codex thread {c} (Mac-mini, m-note low)。 同じ依頼を別の機械で起こさない")
            call("python3 board.py request --to codex --to-session role-x-y --launch-host MacBook --summary s",
                 "→ 起動する機械 = MacBook (この機械 Mac-mini ではない) = ここでは起こさない")
            grep = call("grep -n 起動した some-session.jsonl",
                        f"12: → 起動した: Codex thread {c} (Mac-mini, model m-grep / effort low)\n"
                        f"13: → Codex の仕事を起こした: thread {c} (model m-grep / effort low, cwd /x)")
            mention = call("git commit -m 'count codex-app-launch.py start in the closing sweep'", "")
            js = call(f"cd {box} && python3 -I {launcher} start --cwd ../gone --prompt-file p.txt --json",
                      json.dumps({"thread_id": d, "host": "Mac-mini", "cwd": str(gone), "model": "m-json", "effort": "medium",
                                  "instruction_sources": []}))
            call("head -c 600 events.jsonl", json.dumps({"type": "thread.started", "thread_id": c}))  # a codex exec event
            big = call("python3 board.py launch --request r1",
                       f"<persisted-output>\nOutput too large (99KB). Full output saved to: {saved}\n\nPreview (first 2KB):\nx\n</persisted-output>")
            stale = call(f"python3 {launcher} continue --thread {f} --prompt-file r.txt",
                         f"→ thread {f} に次の turn を送った。 進行 = codex resume {f}", ts="2020-01-03T00:00:00Z")
            # the copy of the API request repeats the start call in its wire form: not a second launch
            call(f"cd {tmp} && python3 {launcher} start --cwd {box} --prompt-file {box}/prompt.txt", "", line_type="api-request-blob")
            proj = tmp / "cfg" / "projects" / "p"
            proj.mkdir(parents=True)
            log = proj / "app-parent.jsonl"
            log.write_text("\n".join(rows) + "\n")

            got = {(l["tool_use_id"], l["detection"]): l for l in launches(log) if l["kind"] == "codex-app"}
            executed = [k[0] for k in got if k[1] == "execution"]
            assert sorted(executed) == sorted([start, cont, board, js, big, stale]), executed
            assert sorted(k[0] for k in got if k[1] == "text") == sorted([grep, mention]), got.keys()
            s = got[(start, "execution")]
            assert s["thread"] == a and s["model"] == "m-run" and s["effort"] == "xhigh" and s["cwd"] == box and s["seen"]
            assert "起動文 file に約束の MARKER" in promise(s) and worker_transcripts(s)
            k = got[(cont, "execution")]
            assert k["sub"] == "continue" and k["thread"] == a and not k["seen"] and k["effort"] == "high" and k["cwd"] == box
            o = got[(board, "execution")]
            assert o["via"] == "board" and o["thread"] == b and o["cwd"] == board_cwd and o["host"] == "mac mini"
            assert promise(o).startswith("掲示板の依頼の worker")
            j = got[(js, "execution")]
            assert j["thread"] == d and j["model"] == "m-json" and j["cwd"] == gone and worker_transcripts(j)
            g = got[(big, "execution")]
            assert g["thread"] == e and g["model"] == "m-big" and g["cwd"] == board_cwd
            t = got[(stale, "execution")]
            assert t["thread"] == f and not t["rollouts"]
            print("OK the launcher's start / continue / --json and the board's launch line count; a grep and a mention do not")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                assert run("app-parent", [tmp / "cfg" / "projects"], 0) == 0
            text = buf.getvalue()
            assert "(うち Codex アプリ 6 件) / 文字列候補: 2 件" in text, text
            assert text.count("== 起動 ") == 6 and f"thread={a}" in text and "rollout-2042-01-02T10-00-00-" + a in text, text
            assert "⚠️ 起動の出力に thread の行が無い" in text and "= --thread の値で引いた" in text, text
            assert "作業 dir が今は無い" in text and "この機械に起動以降の rollout が無い" in text, text
            os.utime(day / f"rollout-2042-01-02T10-00-00-{a}.jsonl", (1, 1))
            assert not worker_transcripts(launches(log)[0])
            print("OK a rollout older than the launch is not taken for the worker's record")
        finally:
            if old_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_home


def compressed_rollout_regression() -> None:
    """Codex compresses old rollouts to .jsonl.zst: the thread id, the cwd and the worker's record come from them too,
    and a rollout that cannot be decompressed here is reported, not taken for a missing one."""
    import contextlib
    import io
    try:
        import compressed_jsonl as cj
    except Exception:
        cj = None
    g = "00000000-0000-4000-8000-0000000000c7"
    old_home = os.environ.get("CODEX_HOME")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["CODEX_HOME"] = str(tmp / "codex")
        try:
            box = tmp / "box"
            box.mkdir()
            archived = tmp / "codex" / "archived_sessions"
            archived.mkdir(parents=True)
            zpath = archived / f"rollout-2042-01-03T10-00-00-{g}.jsonl.zst"
            meta = (json.dumps({"type": "session_meta", "payload": {"id": g, "cwd": str(box)}}) + "\n").encode()
            packed = cj.compress_for_test(meta) if cj is not None else None
            launcher = "/opt/sample/claude-config/scripts/codex-app-launch.py"
            proj = tmp / "cfg" / "projects" / "p"
            proj.mkdir(parents=True)
            log = proj / "zst-parent.jsonl"
            log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
                {"type": "assistant", "timestamp": "2020-01-01T00:00:00Z", "sessionId": "zst-parent", "cwd": str(tmp),
                 "message": {"content": [{"type": "tool_use", "id": "z-1", "name": "Bash",
                                          "input": {"command": f"python3 {launcher} continue --thread {g[:8]} --prompt-file r.txt"}}]}},
                {"type": "user", "timestamp": "2020-01-01T00:00:00Z", "sessionId": "zst-parent",
                 "message": {"content": [{"type": "tool_result", "tool_use_id": "z-1",
                                          "content": f"→ thread {g} に次の turn を送った。 進行 = codex resume {g}"}]}},
            ]) + "\n")
            if packed is None:
                print("SKIP a compressed rollout is read (no zstd decompressor on this machine)")
            else:
                zpath.write_bytes(packed)
                z = [l for l in launches(log) if l["kind"] == "codex-app" and l["detection"] == "execution"]
                assert len(z) == 1 and z[0]["thread"] == g, z
                assert z[0]["cwd"] == box and worker_transcripts(z[0]) == [zpath], z
                print("OK a compressed rollout gives the thread id, the cwd and the worker's record")
            if cj is not None:
                zpath.write_bytes(packed or b"x")
                saved, cj.FORCE = cj.FORCE, "none"
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        assert run("zst-parent", [tmp / "cfg" / "projects"], 0) == 0
                finally:
                    cj.FORCE = saved
                text = buf.getvalue()
                assert "圧縮した rollout (.jsonl.zst) を読めなかった" in text and "展開の手段が無い 1 本" in text, text
                print("OK a compressed rollout that cannot be decompressed here is reported")
        finally:
            if old_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_home


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        box = tmp / "box"
        (box / "scratch").mkdir(parents=True)
        (box / "checks").mkdir()
        (box / "CLAUDE.md").write_text("Write HANDOFF.md: options discarded, things noticed, and what remains unverified.\n")
        (box / "HANDOFF.md").write_text("# handoff\nlesson\n")
        (box / "scratch" / "hoist-candidates.md").write_text("cand\n")
        (box / "checks" / "a.py").write_text("print(1)\n")
        bare = tmp / "bare"
        bare.mkdir()
        proj = tmp / "cfg" / "projects" / "p"
        proj.mkdir(parents=True)

        def bash(ts, cmd, cwd=None):
            o = {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}
            if cwd:
                o["cwd"] = cwd
            return json.dumps(o, ensure_ascii=False) + "\n"

        (proj / "abcd1234-x.jsonl").write_text(
            bash("T1", f"cd {box} && CLAUDE_CONFIG_DIR={tmp}/wcfg claude -p \"do it\" --model m1 --effort high < /dev/null > run.log")
            + bash("T2", "ls -la && echo claude -pretend")
            + bash("T3", "claude --print 'x'", cwd=str(bare))
            + bash("T4", f"cd '{bare}' ; codex exec \"y {MARKER}\"")
            + bash("T5", "git commit -m 'mention claude -p in text'")
            + bash("T6", "python3 '/opt/sample/headless-record-clause-nudge.py' --run claude -p task", cwd=str(bare)))
        ls = launches(proj / "abcd1234-x.jsonl")
        assert [l["ts"] for l in ls] == ["T1", "T3", "T4", "T5", "T6"], [l["ts"] for l in ls]   # T5 remains visible as text, separately from executable-position candidates.
        assert ls[0]["cwd"] == box and ls[0]["model"] == "m1" and ls[0]["effort"] == "high" and ls[0]["config"] == tmp / "wcfg"
        assert ls[1]["cwd"] == bare and ls[2]["kind"] == "codex" and ls[2]["marker"]
        assert "記録条項あり" in promise(ls[0]) and promise(ls[1]).startswith("⚠️") and "MARKER あり" in promise(ls[2])
        assert "受領を確認できない" in promise(ls[1]) and "渡っていない" not in promise(ls[1])
        assert "自動注入 runner" in promise(ls[4]) and "受領は worker" in promise(ls[4])
        wslug = re.sub(r"[^A-Za-z0-9]", "-", str(box))
        (tmp / "wcfg" / "projects" / wslug).mkdir(parents=True)
        child_id = '44444444-4444-4444-8444-444444444444'
        (tmp / "wcfg" / "projects" / wslug / (child_id + '.jsonl')).write_text("{}\n")
        assert worker_transcripts(ls[0]) == []
        ls[0]['worker_session'] = child_id
        ls[0]['receipt'] = {'issued_ns': 1, 'state': 'added'}
        assert len(worker_transcripts(ls[0])) == 1
        assert run("abcd1234", [tmp / "cfg" / "projects"], 0) == 0
        assert run("zzzz", [tmp / "cfg" / "projects"], 0) == 1
    app_launch_regression()
    compressed_rollout_regression()
    receipt_regression(Path(__file__).resolve().parents[1])
    followup_regression(Path(__file__).resolve().parents[1])
    print("selftest OK")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--followup-selftest" in argv:
        repo = Path(argv[argv.index('--against-root')+1]).resolve() if '--against-root' in argv else Path(__file__).resolve().parents[1]
        case = argv[argv.index('--case')+1] if '--case' in argv else None
        return followup_regression(repo, case)
    if "--selftest" in argv:
        if "--against-root" in argv:
            return receipt_regression(Path(argv[argv.index("--against-root")+1]).resolve())
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?")
    ap.add_argument("--prune-receipts", action="store_true")
    ap.add_argument("--max-chars", type=int, default=2000)
    ap.add_argument("--projects-dir", action="append")
    a = ap.parse_args(argv)
    dirs = projects_dirs(a.projects_dir)
    if a.prune_receipts:
        cleanup(dirs)
        return 0
    if not a.session:
        ap.error('session または --prune-receipts が必要です')
    return run(a.session, dirs, a.max_chars)


if __name__ == "__main__":
    sys.exit(main())
