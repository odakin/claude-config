#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay-session-scripts.py — 一時 dir に書いて消えた script を、 その session の会話記録の Write / Edit を順に当て直して復元する。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#evidence-scripts) で、 記録の根拠に使った script が scratchpad などから
もう消えていたとき (session-scripts-report.py の ❌ もう無い)。 会話記録には Write の全文と Edit の差分が残っているので、
その順に当て直せば最後の形が戻る (実測: 締めの時点で scratchpad が消えていて、 根拠に使った script をこの手で戻した)。

戻せないもの: Bash で直した分 (sed・heredoc の置換・cp)。 最後の Write より後にその file の名を含む Bash の呼び出しがあれば
「Bash でも触った = 戻した形は最後の形と違いうる」 と出す。 Edit の old_string が見つからない (= 間に Bash の直しがあった) ときも出す。
戻した file は「復元した形」 であって、 実行した形と同じだと確かめたものではない = 置く前に読み、 差を直す。

使い方:
  replay-session-scripts.py <session id か先頭の数文字> --list                 # 戻せる file と、 今あるか (ある / もう無い) の一覧
  replay-session-scripts.py <id8> --out <dir>                                 # もう無い file を全部 <dir> に戻す
  replay-session-scripts.py <id8> --out <dir> foo.py bar.py                    # 名前 (basename か path の一部) で選ぶ (ある file も戻す)
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


def find_transcripts(session, explicit=None):
    pat = "*/" + glob.escape(session) + "*.jsonl"
    if explicit:
        return sorted(Path(explicit).expanduser().glob(pat))
    if _ccd is not None:
        return [Path(f) for _lab, f in _ccd.transcript_files(pat, roots=list(_ccd.projects_dirs()))]
    return sorted((Path.home() / ".claude" / "projects").glob(pat))


def tool_calls(path):
    """assistant の tool_use を記録順に (name, input)。"""
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
                out.append((c.get("name"), c.get("input") or {}))
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


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--projects-dir")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("session id が要る")
    trs = find_transcripts(a.session, a.projects_dir)
    if not trs:
        print(f"⚠️ 会話記録が見つからない: {a.session}")
        return 1
    calls = []
    for t in trs:
        calls.extend(tool_calls(t))
    files = replay(calls)
    if a.list:
        for p, f in files.items():
            mark = "ある" if os.path.exists(p) else "もう無い"
            print(f"{mark}\t{p}" + "".join(f"\n    ⚠️ {n}" for n in f["notes"]))
        return 0
    if not a.out:
        ap.error("--out <dir> か --list が要る")
    chosen = select(files, a.names, only_gone=True)
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
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
    return 0


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
        out = Path(d) / "out"
        rc = main(["abcd1234", "--out", str(out), "--projects-dir", str(Path(d) / "projects")])
        expect("--out に戻した file を書く", rc == 0 and (out / "gone.py").read_text(encoding="utf-8") == "a = 1\nb = 3\n")
    print("selftest: " + ("ALL PASS" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
