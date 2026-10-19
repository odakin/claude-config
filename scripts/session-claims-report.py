#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session-claims-report.py — ある session が返事と記録に書いた「根拠の無い検算の主張」 と「先送り」 を会話記録から並べる。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#collect-from-transcript) で、 次の 2 つを取りこぼさないため。
  A. 検算・照合の主張に根拠の file が無い — 「手で平方完成して一致」「独立に再現」 と記録や返事に書いたが、 その計算は
     頭の中 (推論) だけで、 script も出力も残っていない。 session-scripts-report.py は書いた script を数えるので、
     script を書かなかった主張はそこに現れない (実測: 受領の記録に手計算の検算を書き、 締めの後に問われて初めて script にした)。
  B. 先送り — 記録や返事に「次に〜するとき」「後で」 と書いたが、 期限つきの TODO・plan・掲示板の依頼のどれにも載せていない
     (実測: 監査の受領の記録に「次にノートを触るとき注記」 と書き、 そのまま締めた)。 人の記憶も次の session の記憶も carrier でない。

拾うもの (session 本体の記録の、 Claude 自身の返事の文と、 file に書いた内容 = Write / Edit / MultiEdit の本文と Bash の command 全体):
  A1 手の印 (手で / 手計算 / 暗算 / 頭の中 / by hand / mentally) と、 検算の語 (一致 / 再現 / 確か / 確認 / 検算 / 照合 / 再導出 /
     平方完成 / verif / reproduc / check / agree) が同じ行にある
  A2 独立検査の語 (独立検査 / 独立に再現 / 独立に再導出 / 独立の検算 / independent check / independently re-derived) があり、
     同じ行に根拠の file (.py / .wls / .nb / .ipynb / .m / script / スクリプト) が無い
  B  先送りの語 (次に…とき・時・際 / 後で / あとで / 次回 / そのうち / いずれ / later / next time) があり、 同じ行に carrier
     (TODO の id = 日付で始まる id / plan / TODO / 掲示板 / thread / request / 期限 / deadline / carrier) が無い
誤検出は出る (説明の中の「後で」 など)。 1 行ずつ読んで、 A は今 script にして回すか主張を消す、 B は今やるか carrier に載せる。

使い方:
  session-claims-report.py <session id か先頭の数文字>     # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  session-claims-report.py abcd1234 --json
  session-claims-report.py abcd1234 --strict               # 1 件でもあれば exit 1
  session-claims-report.py --selftest

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library、 Python 3.8+、 出力は UTF-8)。
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ssr", HERE / "session-scripts-report.py")
ssr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ssr)

HAND = r"(手で|手計算|暗算|頭の中|by hand|mentally)"
CHECK = r"(一致|再現|確か|確認|検算|照合|再導出|平方完成|verif|reproduc|check|agree)"
INDEP = r"(独立検査|独立に再現|独立に再導出|独立の検算|independent(?:ly)?\s+(?:check|re-?deriv|verif))"
EVIDENCE = r"(\.py\b|\.wls\b|\.nb\b|\.ipynb\b|\.m\b|script|スクリプト)"
DEFER = r"(次に[^。\n]{0,30}?(とき|時|際)|後で|あとで|次回|そのうち(?!\s*\d|の)|いずれ(?![もか])|\blater\b|next time)"
CARRIER = r"(\b20\d\d-\d\d-\d\d-[a-z0-9-]+|plan|TODO|掲示板|thread|request|期限|deadline|carrier)"

A1_RE = re.compile(HAND + r".*" + CHECK + "|" + CHECK + r".*" + HAND, re.I)
A2_RE = re.compile(INDEP, re.I)
EV_RE = re.compile(EVIDENCE, re.I)
B_RE = re.compile(DEFER, re.I)
CAR_RE = re.compile(CARRIER, re.I)


def assistant_texts(path):
    """Claude 自身の返事の文を (ts, text)。"""
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") != "assistant":
            continue
        content = (o.get("message") or {}).get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                    out.append((o.get("timestamp", ""), c["text"]))
    return out


def written_texts(calls):
    """file に書いた内容を (ts, where, text)。 calls = session-scripts-report.read_calls の tuple (先頭 3 つだけ使う = 後ろに欄が増えても壊れない)。"""
    out = []
    for name, inp, ts, *_ in calls:
        if name == "Write":
            out.append((ts, inp.get("file_path", ""), inp.get("content", "")))
        elif name == "Edit":
            out.append((ts, inp.get("file_path", ""), inp.get("new_string", "")))
        elif name == "MultiEdit":
            for e in inp.get("edits") or []:
                out.append((ts, inp.get("file_path", ""), e.get("new_string", "")))
        elif name == "Bash":
            out.append((ts, "Bash", inp.get("command", "")))
    return out


def scan(items):
    """items = [(ts, where, text)] → findings [(kind, ts, where, line)] (同じ行は 1 回)。"""
    seen, found = set(), []
    for ts, where, text in items:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or len(line) > 2000:
                continue
            kinds = []
            if A1_RE.search(line):
                kinds.append("A1 手の検算")
            if A2_RE.search(line) and not EV_RE.search(line):
                kinds.append("A2 根拠の無い独立検査")
            if B_RE.search(line) and not CAR_RE.search(line):
                kinds.append("B 先送り")
            for k in kinds:
                key = (k, line[:200])
                if key in seen:
                    continue
                seen.add(key)
                found.append((k, ts, where, line))
    return found


def report(session, pdirs, as_json, strict):
    paths = ssr.find_main_transcripts(pdirs, session)
    if not paths:
        print("記録が見つからない: session=%s (見た dir: %s)" % (session, ", ".join(map(str, pdirs))))
        return 2
    items = []
    for p in paths:
        items += [(ts, "返事", t) for ts, t in assistant_texts(p)]
        items += written_texts(ssr.read_calls(p))
    found = scan(items)
    if as_json:
        print(json.dumps([{"kind": k, "ts": ts, "where": w, "line": l} for k, ts, w, l in found], ensure_ascii=False, indent=1))
    else:
        print("記録: " + ", ".join(map(str, paths)))
        print("拾った行: %d (A = 根拠の無い検算の主張 → 今 script にして回すか主張を消す / B = 先送り → 今やるか carrier に載せる)" % len(found))
        for k, ts, w, l in found:
            print("%s  %s  [%s]\n      %s" % (k, ts[:19], w if len(w) < 90 else "…" + w[-88:], l[:240]))
    return 1 if (strict and found) else 0


def selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL", name, got, want)

    items = [
        ("t1", "ledger.md", "受領側の独立検査 (手で平方完成): 係数が一致"),
        ("t2", "ledger.md", "受領側の独立検査 = check.py で一致"),
        ("t3", "ledger.md", "推す = ノートに注記 1 行 (次にノートを触るとき)"),
        ("t4", "ledger.md", "次にノートを触るとき注記する (TODO 2026-10-20-note-fix)"),
        ("t5", "返事", "差分を見て問題なければ送って"),
        ("t6", "返事", "We independently re-derived eq. (3)."),
        ("t7", "返事", "We independently re-derived eq. (3) in check_eq3.py."),
        ("t8", "返事", "後で直します"),
        ("t9", "返事", "5 種類あり、 そのうち 2 種類を見た。 いずれも記録先がある"),
    ]
    got = sorted((k[:2], ts) for k, ts, _w, _l in scan(items))
    expect("findings", got, [("A1", "t1"), ("A2", "t1"), ("A2", "t6"), ("B ", "t3"), ("B ", "t8")])
    # end to end on a synthetic transcript
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "proj"
        proj.mkdir()
        rec = [
            {"type": "assistant", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": [
                {"type": "text", "text": "手計算で確かめて一致した"},
                {"type": "tool_use", "id": "x1", "name": "Write", "input": {"file_path": "/r/a.md", "content": "後で注記する"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x1"}]}},
        ]
        (proj / "abcd1234-0000.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rec), encoding="utf-8")
        paths = ssr.find_main_transcripts([Path(d)], "abcd1234")
        items = [(ts, "返事", t) for ts, t in assistant_texts(paths[0])] + written_texts(ssr.read_calls(paths[0]))
        kinds = sorted(k[:2] for k, *_ in scan(items))
        expect("end-to-end", kinds, ["A1", "B "])
    print("selftest:", "ok" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ssr._utf8_stdout()
    ap = argparse.ArgumentParser(description="session が書いた根拠の無い検算の主張と先送りを並べる")
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    ap.add_argument("--projects-dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID)")
    return report(a.session, ssr.projects_dirs(a.projects_dir), a.json, a.strict)


if __name__ == "__main__":
    sys.exit(main())
