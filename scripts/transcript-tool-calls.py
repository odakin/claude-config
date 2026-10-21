#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcript-tool-calls.py — 会話記録にある実際の tool の呼び出しと結果を対にして、 PostToolUse の入力と同じ形の JSON で出す。--selftest 内蔵。

用途: hook を作る・直すとき、 合成の入力だけでなく実際の出力を流して発火と沈黙を確かめる (RCA で呼び出しの入力と結果を並べて読むのにも使える)。
  合成の入力は書いた人の想定どおりの形になる。 実際の出力は想定の外の行を持つ (例 = 本文に header と同じ形の行がある)。
  ⚠️ 実測: 合成の入力の test は全部通ったのに、 実際の出力では本文の行に引っかかって黙る hook だった。
  正本の手順 = conventions/hook-authoring.md#replay-real-tool-output。

出力の形 (PostToolUse の hook が stdin で受ける key):
  {"hook_event_name": "PostToolUse", "session_id", "tool_name", "tool_input", "tool_response", "tool_use_id"}
  tool_response は記録の tool_result の content をそのまま (文字列か content block の配列)。

使い方:
  transcript-tool-calls.py <session id か先頭の数文字> --tool '<tool 名の正規表現>'       # 当たった最初の 1 件を JSON 1 つで
  transcript-tool-calls.py abcd1234 --tool '__read_email$' --index 2                    # 3 件目 (0 始まり)
  transcript-tool-calls.py abcd1234 --tool '^Bash$' --all                               # 全部を 1 行 1 件 (JSON Lines)
  transcript-tool-calls.py abcd1234 --tool '__read_email$' --out-dir <一時 dir>          # 1 件 1 file (call-<n>.json)
  transcript-tool-calls.py abcd1234 --tool '__read_email$' --list                       # 番号・tool 名・入力の冒頭だけ (どれを流すか選ぶ)
  流し方: 1 件を <一時 dir>/in.json に出してから bash hooks/<対象>.sh < <一時 dir>/in.json

⚠️ 出力は会話記録の中身 (mail の本文・file の中身) = 一時 dir に置き、 repo に入れない。 test の fixture は合成で書く。
projects-dir の既定 = この機械の全部の設定 dir の projects/ (lib/claude_config_dirs.py)。 --projects-dir でその dir だけ。
OS: macOS / Linux / Windows で同じに動く (標準 library だけ、 出力は UTF-8)。
"""
import argparse
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def find_transcripts(session, projects_dir=None):
    """その session の本体の記録 (<project>/<session id>.jsonl)。 subagent の記録は含めない。"""
    pat = "*/" + glob.escape(session) + "*.jsonl"
    if _ccd is not None:
        roots = [str(Path(projects_dir).expanduser())] if projects_dir else None
        return [Path(p) for _lab, p in _ccd.transcript_files(pat, roots=roots)]
    roots = [Path(projects_dir).expanduser()] if projects_dir else [Path.home() / ".claude" / "projects"]
    return [Path(p) for r in roots for p in sorted(glob.glob(str(r / pat)))]


def tool_calls(lines, tool_re):
    """記録の行 (JSON 文字列) から、 tool 名が tool_re に当たる呼び出しを結果と対にして、 PostToolUse の入力の dict で返す (記録の順)。
    結果の無い呼び出し (途中で止まった) は出さない。"""
    rx = re.compile(tool_re)
    uses, out = {}, []
    session_id = None
    for line in lines:
        try:
            e = json.loads(line)
        except (ValueError, TypeError):
            continue
        session_id = session_id or e.get("sessionId")
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and rx.search(b.get("name") or ""):
                uses[b.get("id")] = b
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in uses:
                u = uses.pop(b["tool_use_id"])
                out.append({"hook_event_name": "PostToolUse", "session_id": session_id, "tool_name": u.get("name"),
                            "tool_input": u.get("input") or {}, "tool_response": b.get("content"),
                            "tool_use_id": u.get("id")})
    return out


def selftest():
    rows = [
        {"sessionId": "s1", "message": {"content": [{"type": "tool_use", "id": "u1", "name": "mcp__x__read_email",
                                                      "input": {"messageId": "m1"}}]}},
        {"sessionId": "s1", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1",
                                                      "content": [{"type": "text", "text": "To: a\n\nbody"}]}]}},
        {"sessionId": "s1", "message": {"content": [{"type": "tool_use", "id": "u2", "name": "Bash", "input": {"command": "ls"}}]}},
        {"sessionId": "s1", "message": {"content": [{"type": "tool_result", "tool_use_id": "u2", "content": "a\nb"}]}},
        {"sessionId": "s1", "message": {"content": [{"type": "tool_use", "id": "u3", "name": "mcp__x__read_email",
                                                      "input": {"messageId": "m3"}}]}},
        "not json",
    ]
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    got = tool_calls(lines, r"__read_email$")
    checks = [
        ("当たった呼び出しを結果と対にする", len(got) == 1 and got[0]["tool_input"] == {"messageId": "m1"}
         and got[0]["tool_response"] == [{"type": "text", "text": "To: a\n\nbody"}]),
        ("PostToolUse の入力の key がそろう", set(got[0]) == {"hook_event_name", "session_id", "tool_name", "tool_input",
                                                        "tool_response", "tool_use_id"} and got[0]["session_id"] == "s1"),
        ("結果の無い呼び出しは出さない", all(g["tool_use_id"] != "u3" for g in got)),
        ("文字列の結果もそのまま", tool_calls(lines, r"^Bash$")[0]["tool_response"] == "a\nb"),
        ("当たらなければ空", tool_calls(lines, r"^Nothing$") == []),
    ]
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "proj"
        proj.mkdir()
        (proj / "abcd1234-0000.jsonl").write_text("\n".join(lines), encoding="utf-8")
        found = find_transcripts("abcd1234", projects_dir=d)
        checks.append(("--projects-dir で session の記録を見つける", [p.name for p in found] == ["abcd1234-0000.jsonl"]))
    ok = True
    for name, good in checks:
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    ap.add_argument("--tool", help="tool 名の正規表現 (部分一致。 固定するなら ^…$)")
    ap.add_argument("--index", type=int, default=0, help="何件目を出すか (0 始まり、 既定 0)")
    ap.add_argument("--all", action="store_true", help="当たった全部を JSON Lines で")
    ap.add_argument("--list", action="store_true", help="番号・tool 名・入力の冒頭だけを並べる")
    ap.add_argument("--out-dir", help="1 件 1 file (call-<n>.json) で置く dir")
    ap.add_argument("--projects-dir", help="この projects dir だけを見る")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.session or not a.tool:
        ap.error("session id (か先頭の数文字) と --tool が要る")
    paths = find_transcripts(a.session, a.projects_dir)
    if not paths:
        sys.exit(f"記録が見つからない: session {a.session} (見た dir = {a.projects_dir or '全部の設定 dir の projects/'})")
    found = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            found.extend(tool_calls(f, a.tool))
    if not found:
        sys.exit(f"当たる呼び出しが無い: --tool {a.tool!r} (記録 = {', '.join(str(p) for p in paths)})")
    if a.list:
        for i, h in enumerate(found):
            print(f"{i}\t{h['tool_name']}\t{json.dumps(h['tool_input'], ensure_ascii=False)[:120]}")
        return
    if a.out_dir:
        d = Path(a.out_dir).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        for i, h in enumerate(found):
            (d / f"call-{i}.json").write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")
        print(f"{len(found)} 件を {d} に置いた (call-0.json …)", file=sys.stderr)
        return
    if a.all:
        for h in found:
            print(json.dumps(h, ensure_ascii=False))
        return
    if not 0 <= a.index < len(found):
        sys.exit(f"--index {a.index} は範囲外 (当たった {len(found)} 件、 --list で番号を見る)")
    print(json.dumps(found[a.index], ensure_ascii=False))


if __name__ == "__main__":
    main()
