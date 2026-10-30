#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session-fetched-docs-report.py — ある session が取得して読んだ原典 (論文・資料の PDF) を会話記録から並べ、 repo に保存したかを出す。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#collect-from-transcript) で、 一時 dir に落として読んだ原典を保存し漏らさないため。
判定に使った論文を一時 dir に置いたまま締めを終えると、 一時 dir と一緒に消え、 判定をだれも確かめ直せない
(実測: 頁を読んだ論文だけを保存し、 語の検索で判定した論文を一時 dir に残したまま締めを終えた)。
置き場と保存の規則 = closing-sweep.md#fetched-originals。 本 script は session 本体の分だけを数える (agent・worker の取得は数えない)。

拾うもの (session 本体の記録 <projects-dir>/<project>/<session id>.jsonl の道具の呼び出し):
  1. arXiv の原典 — Bash の command か WebFetch の URL に arxiv.org/pdf/ か arxiv.org/e-print/ があれば、 その中の arXiv の番号を全部。
     loop (`for id in A B C; do curl …/pdf/$id`) も拾える。 URL の無い command の番号は数えない (書誌の API・INSPIRE の検索を除くため)
  2. 手元の PDF — (a) Read の file_path、 (b) Bash の curl -o / wget -O の書き先、 (c) Bash の command に現れる取り込み口
     (DROP_DIRS = ~/Desktop・~/Downloads) の下の `….pdf`、 (d) arXiv 以外の URL で WebFetch が保存した PDF (結果の「also saved to」 の path)。 repo の中の PDF (保存済みの原物を読み直した・組版の生成物) と、
     隣に同じ名前の .tex がある PDF (組版の生成物) は数えない。 path の変数は同じ command で先に代入したものだけ展開し、
     展開できない path と glob は数えない (loop の取得は 1 の番号で拾う)

判定:
  arXiv → 探した repo の追跡済み file の path にその番号 (版の有無を問わない) があれば ✅ (path)、 無ければ ⚠️ 保存なし
  手元の PDF → 在れば大きさと sha256 で追跡済みの PDF と照合し、 同じものがあれば ✅ (path)、 無ければ ⚠️ 保存なし。
     もう無ければ ❌ (取得した元が分からないので、 記録の command を見て決める)
  ⚠️ / ❌ は 1 件ずつ決める: 判定・計算・引用の根拠に使ったなら版を固定して取り直し、 原物の置き場へ。
  使っていない (開いただけ・別の論文だった・自分で作った図) なら保存せず、 報告に理由を 1 行。

使い方:
  session-fetched-docs-report.py <session id か先頭の数文字>   # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  session-fetched-docs-report.py abcd1234 --touched-only        # 既定 = 作業ルート (--root、 既定 ~/Claude) の全 repo で探す
  session-fetched-docs-report.py abcd1234 --json
  session-fetched-docs-report.py abcd1234 --strict              # ⚠️ / ❌ が 1 件でもあれば exit 1
  session-fetched-docs-report.py --selftest

記録の読み方・repo の集め方は session-scripts-report.py と共有する (import)。
OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library + git、 Python 3.8+、 出力は UTF-8)。
"""
import argparse
import hashlib
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

DROP_DIRS = ("~/Desktop", "~/Downloads")
ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:pdf|e-print)/", re.I)
# 新しい形 YYMM.NNNNN (2007-04 から) と古い形 archive/YYMMNNN。 版 vN は別に取る
ARXIV_ID_RE = re.compile(
    r"(?<![\w.])((?:0[7-9]|[1-9]\d)(?:0[1-9]|1[0-2])\.\d{4,5}"
    r"|(?:hep-th|hep-ph|hep-ex|hep-lat|gr-qc|astro-ph|cond-mat|quant-ph|math-ph|nucl-th|nucl-ex|physics|math)"
    r"(?:\.[A-Z]{2})?/\d{7})(v\d+)?(?![\w])")
PDF_TOKEN_RE = re.compile(r"(['\"]?)((?:~|/|\$\{?\w+\}?/)[^\s'\";|&<>()]*?\.pdf)\1(?=[\s'\";|&<>)]|$)", re.I)
# WebFetch は PDF を要約に渡せず、 取得物を tool-results の下に保存して結果の末尾にその path を書く
WEBFETCH_SAVED_RE = re.compile(r"also saved to (\S+?\.pdf)\b", re.I)
OUTPUT_RE = re.compile(r"\b(?:curl|wget)\b[^\n;|&]*?\s(?:-o|--output|-O|--output-document)\s+(['\"]?)([^\s'\";|&<>]+)\1")
# 取り込む前の検査のために空の dir へ写した写し (`cp <元> <写し>`)。 写しが消えても元で照合する
CP_RE = re.compile(r"(?:^|[\s;&|(])cp\s+(?:-\w+\s+)*(['\"]?)([^\s'\";|&<>]+)\1\s+(['\"]?)([^\s'\";|&<>]+)\3(?=\s*(?:$|[;&|\n)]))")


def _expand_at(cmd, pos, raw, cwd):
    p = ssr._subst(raw, ssr._vars_at(cmd, pos))
    if "$" in p or "*" in p or "?" in p:
        return None
    return ssr._expand(p, ssr._cwd_at(cmd, pos, cwd))


def collect(calls, drop_dirs=DROP_DIRS):
    """(arxiv, local) を返す。 arxiv = {id: {"versions": set, "time": 最初の時刻, "cmd": 先頭}}、
    local = {path: {"how": 取得の形, "time": 最初の時刻}}。"""
    drops = [os.path.realpath(os.path.expanduser(d)) for d in drop_dirs]
    arxiv, local, copied_from = {}, {}, {}

    def add_local(path, how, ts):
        if path and path.lower().endswith(".pdf") and path not in local:
            local[path] = {"how": how, "time": ts}

    def add_arxiv(text, ts, head):
        for m in ARXIV_ID_RE.finditer(text):
            rec = arxiv.setdefault(m.group(1), {"versions": set(), "time": ts, "cmd": head})
            if m.group(2):
                rec["versions"].add(m.group(2))

    for name, inp, ts, _err, cwd, _out in calls:
        cmd = inp.get("command") or "" if name == "Bash" else ""
        for m in CP_RE.finditer(cmd):
            src, dst = _expand_at(cmd, m.start(2), m.group(2), cwd), _expand_at(cmd, m.start(4), m.group(4), cwd)
            if src and dst and src.lower().endswith(".pdf"):
                if not dst.lower().endswith(".pdf"):
                    dst = os.path.join(dst, os.path.basename(src))
                copied_from[dst] = src

    for name, inp, ts, _err, cwd, out in calls:
        if name == "Read":
            fp = inp.get("file_path") or ""
            if fp.lower().endswith(".pdf"):
                add_local(ssr._expand(fp, cwd), "Read で開いた", ts)
            continue
        if name == "WebFetch":
            url = inp.get("url") or ""
            if ARXIV_URL_RE.search(url):
                add_arxiv(url, ts, "WebFetch " + url[:100])
            else:
                saved = WEBFETCH_SAVED_RE.search(out or "")
                if saved:
                    add_local(saved.group(1), "WebFetch が保存した (" + url[:80] + ")", ts)
            continue
        if name != "Bash":
            continue
        cmd = inp.get("command") or ""
        if ARXIV_URL_RE.search(cmd):
            add_arxiv(cmd, ts, cmd.strip().splitlines()[0][:120])
        for m in OUTPUT_RE.finditer(cmd):
            add_local(_expand_at(cmd, m.start(2), m.group(2), cwd), "URL から取得 (curl / wget の書き先)", ts)
        for m in PDF_TOKEN_RE.finditer(cmd):
            p = _expand_at(cmd, m.start(2), m.group(2), cwd)
            if p and any(os.path.realpath(p).startswith(d + os.sep) for d in drops):
                add_local(p, "取り込み口の file (" + os.path.dirname(p) + ")", ts)
    for p, rec in local.items():
        if p in copied_from:
            rec["origin"] = copied_from[p]
    return arxiv, local


def tracked_files(repos):
    """{repo: [追跡済みの相対 path]}。"""
    out = {}
    for r in repos:
        rc, s = ssr._git(["ls-files"], r)
        out[r] = s.splitlines() if rc == 0 else []
    return out


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_by_id(aid, files):
    pat = re.compile(r"(?<![\d.])" + re.escape(aid) + r"(?![\d])")
    return [os.path.basename(r) + ":" + f for r, fs in files.items() for f in fs if pat.search(f)]


def find_by_content(path, files):
    try:
        size = os.path.getsize(path)
        digest = None
        hits = []
        for r, fs in files.items():
            for f in fs:
                if not f.lower().endswith(".pdf"):
                    continue
                full = os.path.join(r, f)
                try:
                    if os.path.getsize(full) != size:
                        continue
                except OSError:
                    continue
                digest = digest or _sha(path)
                if _sha(full) == digest:
                    hits.append(os.path.basename(r) + ":" + f)
        return hits
    except OSError:
        return []


def is_build_product(path):
    return os.path.exists(os.path.splitext(path)[0] + ".tex")


def judge(arxiv, local, files):
    rows = []
    for aid, rec in sorted(arxiv.items(), key=lambda kv: kv[1]["time"]):
        hits = find_by_id(aid, files)
        ver = ",".join(sorted(rec["versions"])) or "版の指定なし"
        rows.append({"kind": "arxiv", "time": rec["time"][:19], "what": "arXiv:" + aid + " (" + ver + ")",
                     "mark": "✅" if hits else "⚠️",
                     "note": ("保存あり: " + ", ".join(hits[:3])) if hits else "保存なし (取得: " + rec["cmd"] + ")"})
    for path, rec in sorted(local.items(), key=lambda kv: kv[1]["time"]):
        real = os.path.realpath(path)
        origin = rec.get("origin")
        if not os.path.exists(real) and origin and os.path.exists(origin):
            path, real = path + " (写し、 元 = " + origin + ")", os.path.realpath(origin)
        if os.path.exists(real):
            repo = ssr.repo_of(real)
            if repo or is_build_product(real):
                continue
            hits = find_by_content(real, files)
            mark, note = ("✅", "同じ中身を保存: " + ", ".join(hits[:3])) if hits else ("⚠️", "保存なし")
        else:
            if is_build_product(real):
                continue
            mark, note = "❌", "もう無い (取得した元は記録の command で確かめる)"
        rows.append({"kind": "local", "time": rec["time"][:19], "what": path, "mark": mark, "note": rec["how"] + " — " + note})
    return rows


def report(session, pdirs, root, touched_only, as_json, drop_dirs=DROP_DIRS):
    paths = ssr.find_main_transcripts(pdirs, session)
    if not paths:
        print("記録が見つからない (session " + session + ")。 見た dir: " + ", ".join(str(d) for d in pdirs))
        return 2, 0
    calls = []
    for p in paths:
        calls.extend(ssr.read_calls(p))
    arxiv, local = collect(calls, drop_dirs)
    repos = ssr.touched_repos(calls, root) if touched_only else ssr.all_repos(root)
    rows = judge(arxiv, local, tracked_files(repos))
    bad = sum(1 for r in rows if r["mark"] in ("⚠️", "❌"))
    if as_json:
        print(json.dumps({"session": session, "transcripts": [str(p) for p in paths], "repos": len(repos),
                          "rows": rows, "unsaved": bad}, ensure_ascii=False, indent=1))
        return 0, bad
    print("記録: " + ", ".join(str(p) for p in paths))
    print("探した repo: " + str(len(repos)) + " 個" + (" (session が触ったものだけ)" if touched_only else ""))
    print("取得した原典: arXiv " + str(sum(1 for r in rows if r["kind"] == "arxiv")) +
          " 件 / 手元の PDF " + str(sum(1 for r in rows if r["kind"] == "local")) + " 件")
    for r in sorted(rows, key=lambda r: (r["mark"] == "✅", r["time"])):
        print(r["mark"] + " " + r["time"] + "  " + r["what"])
        print("      " + r["note"])
    print("保存なし・もう無い: " + str(bad) + " 件" + ("" if not bad else
          " → 1 件ずつ決める: 判定・計算・引用の根拠に使ったなら版を固定して取り直し、 原物の置き場へ。"
          " 使っていないなら保存せず、 報告に理由 (closing-sweep.md#fetched-originals)"))
    return 0, bad


def _capture(fn):
    import io
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


def selftest():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as t:
        root = os.path.join(t, "work")
        repo = os.path.join(root, "proj")
        os.makedirs(os.path.join(repo, "refs"))
        ssr._git(["init", "-q"], repo)
        ssr._git(["config", "user.email", "t@example.invalid"], repo)
        ssr._git(["config", "user.name", "t"], repo)
        Path(repo, "refs", "author_2024_topic_arxiv2401.00001v2.pdf").write_bytes(b"%PDF-1.4 stored by id")
        Path(repo, "refs", "kept.pdf").write_bytes(b"%PDF-1.4 kept original")
        ssr._git(["add", "refs"], repo)
        ssr._git(["commit", "-q", "-m", "refs"], repo)
        drop = os.path.join(t, "home", "Desktop")
        os.makedirs(drop)
        Path(drop, "given.pdf").write_bytes(b"%PDF-1.4 kept original")      # 保存済みと同じ中身
        Path(drop, "other.pdf").write_bytes(b"%PDF-1.4 not stored anywhere")
        scratch = os.path.join(t, "scratch")
        os.makedirs(scratch)
        Path(scratch, "note.tex").write_text("x", encoding="utf-8")
        Path(scratch, "note.pdf").write_bytes(b"%PDF-1.4 build")
        Path(scratch, "dl.pdf").write_bytes(b"%PDF-1.4 fetched by url")
        proj = os.path.join(t, "projects", "-x")
        os.makedirs(proj)
        sid = "feedface-0000-0000-0000-000000000000"
        recs = []

        def call(i, name, inp, result="x"):
            recs.append({"type": "assistant", "timestamp": "2026-01-01T00:00:%02d" % i, "cwd": repo,
                         "message": {"content": [{"type": "tool_use", "id": "t%d" % i, "name": name, "input": inp}]}})
            recs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t%d" % i,
                                                                  "content": result}]}})
        call(1, "Bash", {"command": 'D=/tmp/x; for id in 2401.00001 2402.00002; do curl -sL -o $D/$id.pdf "https://arxiv.org/pdf/$id"; done'})
        call(2, "Bash", {"command": "curl -s 'https://export.arxiv.org/api/query?id_list=2403.00003'"})
        call(3, "Read", {"file_path": os.path.join(drop, "given.pdf")})
        call(4, "Bash", {"command": "cp " + os.path.join(drop, "other.pdf") + " /elsewhere/"})
        call(5, "Read", {"file_path": os.path.join(repo, "refs", "kept.pdf")})
        call(6, "Read", {"file_path": os.path.join(scratch, "note.pdf")})
        call(7, "Read", {"file_path": os.path.join(t, "gone", "vanished.pdf")})
        call(8, "Bash", {"command": "S=" + scratch + "; curl -sL -o $S/dl.pdf https://example.org/a.pdf"})
        call(9, "Bash", {"command": "curl -sL -o $UNKNOWN/q.pdf 'https://arxiv.org/pdf/hep-th/9901001v3'"})
        # 検査のために空の dir へ写した写し (消えている) を Read → 元 (取り込み口、 保存済み) で照合する
        call(10, "Bash", {"command": "W=" + os.path.join(t, "scan") + "; mkdir -p $W && cp " + os.path.join(drop, "given.pdf") + " $W/paper.pdf"})
        call(11, "Read", {"file_path": os.path.join(t, "scan", "paper.pdf")})
        call(12, "WebFetch", {"url": "https://arxiv.org/pdf/2405.00005v2", "prompt": "p"})
        call(13, "WebFetch", {"url": "https://arxiv.org/abs/2406.00006", "prompt": "p"})
        saved = os.path.join(t, "tool-results", "webfetch-1.pdf")
        Path(saved).parent.mkdir()
        Path(saved).write_bytes(b"%PDF-1.4 fetched")
        call(14, "WebFetch", {"url": "https://example.org/report.pdf", "prompt": "p"},
             "読めません\n[Binary content (application/pdf, 1MB) also saved to " + saved + "]")
        Path(proj, sid + ".jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

        calls = ssr.read_calls(Path(proj, sid + ".jsonl"))
        arxiv, local = collect(calls, drop_dirs=(drop,))
        check(set(arxiv) == {"2401.00001", "2402.00002", "hep-th/9901001", "2405.00005"},
              "arXiv = URL のある command と WebFetch の PDF の番号だけ (loop も、 古い形も。 書誌の API と abs の頁は数えない)")
        check(arxiv["2405.00005"]["versions"] == {"v2"}, "WebFetch の URL の版も取る")
        check(arxiv["hep-th/9901001"]["versions"] == {"v3"}, "版を取る")
        rows = {r["what"]: r for r in judge(arxiv, local, tracked_files([repo]))}
        check(rows["arXiv:2401.00001 (版の指定なし)"]["mark"] == "✅", "名前に番号がある保存は ✅ (版が違っても)")
        check(rows["arXiv:2402.00002 (版の指定なし)"]["mark"] == "⚠️", "保存の無い番号は ⚠️")
        check(rows[os.path.join(drop, "given.pdf")]["mark"] == "✅", "取り込み口の PDF は中身で照合して ✅ (名前が違っても)")
        check(rows[os.path.join(drop, "other.pdf")]["mark"] == "⚠️", "Bash に出た取り込み口の PDF で保存の無いものは ⚠️")
        check(os.path.join(repo, "refs", "kept.pdf") not in rows, "repo の中の PDF は数えない")
        check(os.path.join(scratch, "note.pdf") not in rows, "隣に .tex がある PDF (組版の生成物) は数えない")
        check(rows[os.path.join(t, "gone", "vanished.pdf")]["mark"] == "❌", "もう無い PDF は ❌")
        check(rows[os.path.join(scratch, "dl.pdf")]["mark"] == "⚠️", "curl -o の書き先は変数を展開して数える")
        check(not any("q.pdf" in k for k in rows), "展開できない変数の書き先は数えない")
        check(rows[saved]["mark"] == "⚠️", "WebFetch が保存した PDF (arXiv 以外) も数える")
        copy = [r for k, r in rows.items() if k.startswith(os.path.join(t, "scan", "paper.pdf"))]
        check(len(copy) == 1 and copy[0]["mark"] == "✅" and "写し" in copy[0]["what"],
              "消えた写しは cp の元で照合する (❌ にしない)")
        res = []
        _capture(lambda: res.append(report(sid[:8], [Path(t, "projects")], root, True, False, drop_dirs=(drop,))))
        check(res == [(0, 7)], "保存なし・もう無い = 7 (2402.00002・hep-th/9901001・2405.00005・other・vanished・dl・WebFetch の PDF)")
        out = json.loads(_capture(lambda: report(sid[:8], [Path(t, "projects")], root, True, True, drop_dirs=(drop,))))
        check(out["unsaved"] == 7 and out["repos"] == 1, "json も同じ数")
    print("selftest: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ssr._utf8_stdout()
    ap = argparse.ArgumentParser(description="session が取得して読んだ原典を並べ、 repo に保存したかを出す")
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    ap.add_argument("--projects-dir")
    ap.add_argument("--root", default="~/Claude", help="作業ルート (repo を探す範囲)")
    ap.add_argument("--touched-only", action="store_true", help="session が触った repo だけで探す")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID)")
    rc, bad = report(a.session, ssr.projects_dirs(a.projects_dir), a.root, a.touched_only, a.json)
    if rc:
        return rc
    return 1 if (a.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
