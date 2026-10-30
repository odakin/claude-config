#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay-session-scripts.py — 一時 dir に書いて消えた script を、 その session の会話記録の Write / Edit を順に当て直して復元する。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#evidence-scripts) で、 記録の根拠に使った script が scratchpad などから
もう消えていたとき (session-scripts-report.py の ❌ もう無い)。 会話記録には Write の全文と Edit の差分が残っているので、
その順に当て直せば最後の形が戻る (実測: 締めの時点で scratchpad が消えていて、 根拠に使った script をこの手で戻した)。

読む記録 = 本体の会話記録と、 その session が起こした agent の記録 (Agent tool の subagents/、 Workflow tool の
subagents/workflows/<run>/)。 時刻順に混ぜて当てる。
戻せないもの: Bash で直した分 (sed・heredoc の置換・cp)。 最後の Write より後にその file の名を含む Bash の呼び出しがあれば
「Bash でも触った = 戻した形は最後の形と違いうる」 と出す。 Edit の old_string が見つからない (= 間に Bash の直しがあった) ときも出す。
戻した file は「復元した形」 であって、 実行した形と同じだと確かめたものではない = 置く前に読み、 差を直す。
file に書かずに流した code (heredoc・`-c`) は `--bash-match <名前>=<目印>` で、 目印の文字列を含む Bash の command を
そのまま <名前> に書き出す (冒頭に実行の時刻の注釈。 一致が 2 つ以上なら <名前>.2 …。 実測: 記録の数値の根拠にした heredoc の
分析が file に無く、 使い捨ての取り出し script を書いた)。 目印は command の中の、 その code にしか無い短い文字列にする
(引用符・改行を含む目印は記録の escape と合わないことがある = path や変数名のような素の語が確実)。

使い方:
  replay-session-scripts.py <session id か先頭の数文字> --list                 # 戻せる file と、 今あるか (ある / もう無い) の一覧
  replay-session-scripts.py <id8> --out <dir>                                 # もう無い file を全部 <dir> に戻す
  replay-session-scripts.py <id8> --out <dir> foo.py bar.py                    # 名前 (basename か path の一部) で選ぶ (ある file も戻す)
  replay-session-scripts.py <id8> --out <dir> --bash-match check.sh=<目印>      # 流した command を取り出す (繰り返し可、 file の復元はしない)
  replay-session-scripts.py --selftest

projects-dir の既定 = この機械の全部の設定 dir の projects/ (lib/claude_config_dirs.py、 session-scripts-report.py と同じ)。
OS: macOS / Linux / Windows で同じに動く (標準 library だけ、 Python 3.8+)。
"""
import argparse
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd  # noqa: E402
except Exception:  # noqa: BLE001
    _ccd = None


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# 本体の記録 + その session が起こした agent の記録 (Agent tool = subagents/、 Workflow tool = subagents/workflows/<run>/)。
# agent が一時 dir に書いた検算の script も戻すため (実測: 本体の記録だけを読み、 agent の書いた script を戻せなかった)
TRANSCRIPT_GLOBS = ("{s}*.jsonl", "{s}*/subagents/agent-*.jsonl", "{s}*/subagents/workflows/*/agent-*.jsonl")


def find_transcripts(session, explicit=None):
    found = []
    for g in TRANSCRIPT_GLOBS:
        pat = "*/" + g.format(s=glob.escape(session))
        if explicit:
            found.extend(sorted(Path(explicit).expanduser().glob(pat)))
        elif _ccd is not None:
            found.extend(Path(f) for _lab, f in _ccd.transcript_files(pat, roots=list(_ccd.projects_dirs())))
        else:
            found.extend(sorted((Path.home() / ".claude" / "projects").glob(pat)))
    return found


def tool_calls(path, with_time=False):
    """assistant の tool_use を記録順に (name, input)。 with_time なら (timestamp, name, input)。"""
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") != "assistant":
            continue
        content = (o.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                call = (c.get("name"), c.get("input") or {})
                out.append((o.get("timestamp") or "",) + call if with_time else call)
    return out


def replay(calls):
    """path → {"text", "notes"}。 Write で全文を置き、 Edit / MultiEdit を順に当てる。 Bash で名が出たら印。"""
    files = {}
    for name, inp in calls:
        if name == "Write" and inp.get("file_path"):
            files[inp["file_path"]] = {"text": inp.get("content", ""), "notes": []}
        elif name in ("Edit", "MultiEdit") and inp.get("file_path") in files:
            f = files[inp["file_path"]]
            edits = inp.get("edits") if name == "MultiEdit" else [inp]
            for e in edits or []:
                old, new = e.get("old_string", ""), e.get("new_string", "")
                if old and old in f["text"]:
                    f["text"] = f["text"].replace(old, new) if e.get("replace_all") else f["text"].replace(old, new, 1)
                else:
                    f["notes"].append("Edit の old_string が見つからない (間に Bash の直しがあった?)")
        elif name == "Bash":
            cmd = inp.get("command", "")
            for p, f in files.items():
                if os.path.basename(p) in cmd:
                    note = "最後の Write の後に Bash でも触った (戻した形は最後の形と違いうる)"
                    if note not in f["notes"]:
                        f["notes"].append(note)
    return files


def select(files, names, only_gone):
    out = {}
    for p, f in files.items():
        if names and not any(n == os.path.basename(p) or n in p for n in names):
            continue
        if not names and only_gone and os.path.exists(p):
            continue
        out[p] = f
    return out


def bash_matches(timed, needle):
    """(timestamp, command) の list = 目印を含む Bash の command (記録の順)。"""
    return [(ts, inp.get("command", "")) for ts, name, inp in timed
            if name == "Bash" and needle and needle in inp.get("command", "")]


def write_bash_matches(timed, specs, out):
    """specs = ["名前=目印", …]。 一致した command を out/名前 に書く。 一致の無い spec があれば 1。"""
    rc = 0
    for spec in specs:
        name, sep, needle = spec.partition("=")
        if not sep or not name or not needle:
            print(f"⚠️ --bash-match は 名前=目印 の形: {spec}")
            rc = 1
            continue
        hits = bash_matches(timed, needle)
        if not hits:
            print(f"⚠️ 記録に一致する Bash の command が無い: {name} (目印 = {needle!r})")
            rc = 1
            continue
        for k, (ts, cmd) in enumerate(hits, 1):
            dest = out / (name if k == 1 else f"{Path(name).stem}.{k}{Path(name).suffix}")
            head = (f"# 会話記録の Bash の command そのまま (実行 {ts or '?'} UTC)。 path は当時のもの = 回す前に読む。\n")
            dest.write_text(head + cmd + ("" if cmd.endswith("\n") else "\n"), encoding="utf-8")
            print(f"取り出し: {dest} ({len(cmd.splitlines())} 行、 {ts or '?'})")
    return rc


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--projects-dir")
    ap.add_argument("--bash-match", action="append", default=[], metavar="NAME=SUBSTR",
                    help="目印を含む Bash の command を <out>/NAME に書き出す (heredoc・-c で流した code)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_intermixed_args(argv)  # 「<id8> --out <dir> foo.py」 の順 (使い方の例) でも名前を拾う
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("session id が要る")
    trs = find_transcripts(a.session, a.projects_dir)
    if not trs:
        print(f"⚠️ 会話記録が見つからない: {a.session}")
        return 1
    timed = []
    for t in trs:
        timed.extend(tool_calls(t, with_time=True))
    timed.sort(key=lambda x: x[0])  # 本体と agent の記録を時刻順に混ぜる (同じ file を両方が触ることがある)
    files = replay([(n, i) for _ts, n, i in timed])
    if a.list:
        for p, f in files.items():
            mark = "ある" if os.path.exists(p) else "もう無い"
            print(f"{mark}\t{p}" + "".join(f"\n    ⚠️ {n}" for n in f["notes"]))
        return 0
    if not a.out:
        ap.error("--out <dir> か --list が要る")
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    rc_bash = write_bash_matches(timed, a.bash_match, out) if a.bash_match else 0
    if a.bash_match and not a.names:   # 取り出しだけを頼まれた = 消えた file の一括復元はしない
        return rc_bash
    chosen = select(files, a.names, only_gone=True)
    used = set()
    for p, f in chosen.items():
        base = os.path.basename(p)
        dest, k = out / base, 2
        while dest.name in used or dest.exists():
            dest = out / f"{Path(base).stem}.{k}{Path(base).suffix}"
            k += 1
        used.add(dest.name)
        dest.write_text(f["text"], encoding="utf-8")
        print(f"復元: {dest} ({len(f['text'].splitlines())} 行) ← {p}" + "".join(f"\n    ⚠️ {n}" for n in f["notes"]))
    for n in a.names:
        if not any(n == os.path.basename(p) or n in p for p in chosen):
            print(f"⚠️ 記録に Write が無い: {n}")
    return rc_bash


def selftest():
    ok = True

    def expect(label, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and bool(cond)

    with tempfile.TemporaryDirectory() as d:
        gone = os.path.join(d, "scratch", "gone.py")
        kept = os.path.join(d, "kept.py")
        Path(kept).write_text("x = 1\n", encoding="utf-8")
        rows = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "1", "name": "Write",
             "input": {"file_path": gone, "content": "a = 1\nb = 2\n"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "2", "name": "Edit",
             "input": {"file_path": gone, "old_string": "b = 2", "new_string": "b = 3"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "3", "name": "Write",
             "input": {"file_path": kept, "content": "x = 1\n"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "4", "name": "Edit",
             "input": {"file_path": kept, "old_string": "no such", "new_string": "y"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "5", "name": "Bash",
             "input": {"command": "sed -i '' s/x/z/ kept.py"}}]}},
        ]
        proj = Path(d) / "projects" / "p"
        proj.mkdir(parents=True)
        (proj / "abcd1234-0000.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        files = replay(tool_calls(proj / "abcd1234-0000.jsonl"))
        expect("Write の全文に Edit を順に当てる", files[gone]["text"] == "a = 1\nb = 3\n")
        expect("Edit の old_string が無いと印", any("old_string" in n for n in files[kept]["notes"]))
        expect("最後の Write の後に Bash で名が出たら印", any("Bash" in n for n in files[kept]["notes"]))
        expect("名前なしは もう無い file だけを選ぶ", list(select(files, [], True)) == [gone])
        expect("名前で選べば ある file も戻す", list(select(files, ["kept.py"], True)) == [kept])
        wf = proj / "abcd1234-0000" / "subagents" / "workflows" / "wf_1"
        wf.mkdir(parents=True)
        agent_file = os.path.join(d, "scratch", "agent_check.py")
        (wf / "agent-w1.jsonl").write_text(json.dumps({"type": "assistant", "timestamp": "2026-01-01T00:00:00Z",
            "message": {"content": [{"type": "tool_use", "id": "w", "name": "Write",
                                     "input": {"file_path": agent_file, "content": "ok = True\n"}}]}}) + "\n",
            encoding="utf-8")
        out = Path(d) / "out"
        rc = main(["abcd1234", "--out", str(out), "--projects-dir", str(Path(d) / "projects")])
        expect("--out に戻した file を書く", rc == 0 and (out / "gone.py").read_text(encoding="utf-8") == "a = 1\nb = 3\n")
        expect("Workflow の agent が書いた file も戻す", (out / "agent_check.py").read_text(encoding="utf-8") == "ok = True\n")
        out2 = Path(d) / "out2"
        rc = main(["abcd1234", "--out", str(out2), "kept.py", "--projects-dir", str(Path(d) / "projects")])
        expect("--out の後に並べた名前も拾う (使い方の例の順)", rc == 0 and (out2 / "kept.py").exists())
        heredoc = "cd /tmp/x && python3 - <<'EOF'\nimport json\nprint(json.load(open('analysis/report.json')))\nEOF"
        (proj / "abcd1234-0000.jsonl").open("a", encoding="utf-8").write(json.dumps(
            {"type": "assistant", "timestamp": "2026-01-02T03:04:05Z", "message": {"content": [
                {"type": "tool_use", "id": "6", "name": "Bash", "input": {"command": heredoc}}]}}) + "\n")
        out3 = Path(d) / "out3"
        rc = main(["abcd1234", "--out", str(out3), "--bash-match", "inspect.sh=analysis/report.json",
                   "--projects-dir", str(Path(d) / "projects")])
        got = (out3 / "inspect.sh").read_text(encoding="utf-8") if (out3 / "inspect.sh").exists() else ""
        expect("--bash-match は目印を含む Bash の command をそのまま書き、 冒頭に時刻の注釈",
               rc == 0 and got.endswith(heredoc + "\n") and "2026-01-02T03:04:05Z" in got.splitlines()[0])
        expect("--bash-match だけなら消えた file の一括復元はしない", not (out3 / "gone.py").exists())
        rc = main(["abcd1234", "--out", str(out3), "--bash-match", "none.sh=no-such-marker",
                   "--projects-dir", str(Path(d) / "projects")])
        expect("一致の無い --bash-match は 1 で終わる", rc == 1 and not (out3 / "none.sh").exists())
    print("selftest: " + ("ALL PASS" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
