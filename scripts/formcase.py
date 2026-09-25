#!/usr/bin/env python3
"""formcase — 様式の案件の入口 CLI。 規約の正本 = conventions/form-case-pipeline.md。

instance (どの repo の / どの様式の案件か) は設定 file (formcase.config.json) が持つ: 呼び元の repo に置き、
そこの shim package から configure() で渡す / FORMCASE_CONFIG で指す / cwd から上に置く。

    python3 formcase.py new --form <spec id> --case DIR --doc ID [--workbook NAME] [--todo REPO:ID] [--group G] [--from-doc D]
                                                          新しい案件を配布雛形から (manifest + 記入 stub + README 枠)。
                                                          --group G --from-doc D = 先に出した document の workbook を base に
    python3 formcase.py add-group CASE --doc D --group G   既にある document に manifest に無い group を足す
                                                          (draft + 既定の出力名 + その group だけの stub fill_<doc>_<G>.py。 workbook は触らない)
    python3 formcase.py build CASE [--doc D] [--group G ...] [--out-dir DIR]
                                                          draft group の PDF を作る (gate 必須、 凍結 group は作らない)
    python3 formcase.py status [CASE ...|--all]          案件の document / group / 状態の一覧
    python3 formcase.py check  [CASE ...|--all] [--quiet] 構造 + 凍結の不変条件 + 印刷した紙の鮮度 (exit 1 = 🔴)
    python3 formcase.py freeze CASE DOC GROUP --state printed|sent|submitted|unknown [--date D|unknown] [--evidence T] [--note T]
                               --paper same|differs|unverified [--paper-diff T] [--paper-basis T] [--paper-commit H] [--date-ack T]
                                                          (printed/sent/submitted は --paper 必須、 differs/unverified は --paper-diff 必須)
    python3 formcase.py annotate CASE DOC GROUP [--issue current|previous[N]] [--paper …] [--paper-diff T] [--paper-basis T]
                               [--paper-commit H] [--date-ack T] [--note T]   記録と紙の関係・日付不明の確認済み・note を後から注記 (digest は触らない)
    python3 formcase.py reopen CASE DOC GROUP --reason T [--date D]
    python3 formcase.py normalize CASE DOC                 workbook を Excel で開いて保存するだけ (freeze の前提 = Mac Excel の保存形)
    python3 formcase.py guard --staged [--repo PATH]       pre-commit 用 (凍結出力・凍結 sheet の staged 変更を BLOCK)
    python3 formcase.py rules [ID ...]                     spec の規則 (id / summary / 経緯) を表示
    python3 formcase.py views --check|--write [FILE ...]   doc の generated view を spec と照合 / 描き直す
    python3 formcase.py lint [--staged]                    process doc の規則の書き写し + 案件 README の状態の書き写しを検出
                                                          (--staged = pre-commit 用: stage した案件 README / submission.yaml の案件だけ、
                                                           README の generated view の鮮度も見る。 exit 1 = BLOCK)
    python3 formcase.py audit                              check --all --quiet + views --check + lint (発火面用)
    python3 formcase.py --selftest

CASE = submission.yaml のある dir。 --all = 設定の case_roots の下の全 manifest。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from formcase import check as C  # noqa: E402
from formcase import config as CF  # noqa: E402
from formcase import guard as G  # noqa: E402
from formcase import lifecycle as L  # noqa: E402
from formcase import manifest as M  # noqa: E402


def discover(roots=None) -> list:
    """設定の case_roots の下の案件 dir (= submission.yaml のある dir)。 root 直下の case_root_skip は見ない。"""
    out = []
    skip = CF.case_root_skip()
    for r in roots if roots is not None else CF.case_roots():
        r = Path(r)
        if not r.is_dir():
            continue
        for p in sorted(r.glob("**/" + M.MANIFEST_NAME)):
            if p.relative_to(r).parts[:1] and p.relative_to(r).parts[0] in skip:
                continue
            out.append(p.parent)
    return out


def case_label(case: Path) -> str:
    """案件の見出し。 dir 名が案件を表さない (= 案件 dir の下の書類 dir) ときは親も出す
    (その dir 名の一覧 = 設定の case_label_with_parent)。"""
    case = Path(case)
    return f"{case.parent.name}/{case.name}" if case.name in CF.case_label_with_parent() else case.name


def _cases(args) -> list:
    if getattr(args, "all", False) or not args.cases:
        return discover()
    return [Path(c).resolve() for c in args.cases]


def cmd_status(args) -> int:
    for case in _cases(args):
        try:
            m = M.load(case)
        except M.Locked:
            print(f"── {case.name}: SKIP (git-crypt locked)")
            continue
        print(f"── {case_label(case)}")
        for doc, form, gid, st, dt, outs, note, extra in C.status_rows(m):
            mark = "🧊" if st in M.FROZEN_STATES else "✏️ "
            print(f"   {mark} {doc:<14} {form:<4} {gid:<12} {st:<9} {dt:<10} {outs}")
            for line in extra:
                print(f"{'':>8}{line}")
            if note:
                print(f"{'':>8}note: {note}")
    return 0


def cmd_check(args) -> int:
    bad = False
    cases = _cases(args)
    if not cases:
        print("(formcase: manifest が 1 つも無い)")
    for case in cases:
        label = case_label(case)
        try:
            m = M.load(case)
        except M.Locked:
            print(f"── {label}: SKIP (git-crypt locked = 未検査)")
            continue
        except M.ManifestError as e:
            print(f"── {label}\n   🔴 {e}")
            bad = True
            continue
        bad |= C.render(label, C.check_case(m, digests=not args.no_digest), quiet_ok=args.quiet)
    return 1 if bad else 0


def cmd_freeze(args) -> int:
    m = M.load(args.case)
    cur = L.freeze(m, args.doc, args.group, args.state, args.date, args.evidence, args.note, paper=args.paper,
                   paper_diff=args.paper_diff, paper_basis=args.paper_basis, paper_commit=args.paper_commit,
                   date_ack=args.date_ack)
    m.save()
    _refresh(args.case)
    print(f"🧊 {args.doc}/{args.group} = {cur['state']} {cur['date']} (sha256 {len(cur['frozen']['sha256'])} file, "
          + (f"docx digest)" if cur['frozen'].get('docx_digest') else f"sheet {len(cur['frozen'].get('sheet_digest') or {})})") + (f" paper={cur['paper']}" if cur.get("paper") else ""))
    if M.paper_line(cur):
        print(f"   {M.paper_line(cur)}")
    return 0


def cmd_annotate(args) -> int:
    if (args.paper is None and not (args.paper_diff or args.paper_basis or args.paper_commit) and args.date_ack is None
            and args.outputs_ack is None and args.note is None):
        print("🔴 annotate に書くものが無い (--paper … / --date-ack … / --outputs-ack … / --note …)", file=sys.stderr)
        return 2
    m = M.load(args.case)
    it = L.annotate(m, args.doc, args.group, args.issue, paper=args.paper, paper_diff=args.paper_diff,
                    paper_basis=args.paper_basis, paper_commit=args.paper_commit, date_ack=args.date_ack,
                    outputs_ack=args.outputs_ack, note=args.note)
    m.save()
    _refresh(args.case)
    print(f"📝 {args.doc}/{args.group} {args.issue or 'current'} ({it.get('state')} {it.get('date', '')}): "
          + ", ".join(f"{k}={it[k]!r}" for k in ("paper", "paper_commit", "date_ack", "outputs_ack", "note") if k in it))
    if M.paper_line(it):
        print(f"   {M.paper_line(it)}")
    return 0


def cmd_reopen(args) -> int:
    m = M.load(args.case)
    new = L.reopen(m, args.doc, args.group, args.reason, args.date)
    m.save()
    _refresh(args.case)
    print(f"✏️  {args.doc}/{args.group} = draft issue {new['issue']} → 出力 {new['outputs']}")
    return 0


def _refresh(case) -> None:
    """manifest を変えたら案件 README の状態表 (generated view) を描き直す = README の状態を手で直す場面を作らない。"""
    from formcase import views as V
    line = V.refresh_case(Path(case).resolve())
    if line:
        print(line)


def cmd_guard(args) -> int:
    repo = Path(args.repo).resolve() if args.repo else G.repo_toplevel(".")
    if repo is None:
        return 0
    try:
        blocks = G.staged_findings(repo)
    except Exception as e:  # noqa: BLE001  engine 故障で commit を止めない (呼び元が rc で判別)
        print(f"⚠️ formcase guard の内部エラー (commit は止めない): {e}", file=sys.stderr)
        return 3
    if blocks:
        print("🔴 formcase: 凍結 (印刷済・送付済・提出済) の記録を変える commit を止めた", file=sys.stderr)
        for b in blocks:
            print(f"   - {b}", file=sys.stderr)
        print(f"   使い方 = {CF.usage_doc()}", file=sys.stderr)
        return 1
    return 0


def view_files() -> list:
    """generated view を持つ md (= 'formcase:view' を含む file)。 一覧を持たず走査で見つける
    (探す場所 = 設定の views.roots / views.files。 どちらも workspace_root からの相対)。"""
    ws = CF.workspace_root()
    v = CF.view_cfg()
    out = [p for p in (ws / str(f) for f in v.get("files") or []) if p.exists()]
    for rel in v.get("roots") or []:
        r = ws / str(rel)
        if r.is_dir():
            out += sorted(r.glob("**/*.md"))
    out += [c / "README.md" for c in discover() if (c / "README.md").exists()]   # 案件 README の状態表 (kind=status)
    res = []
    for p in out:
        try:
            b = p.read_bytes()
        except OSError:
            continue
        if not b.startswith(M.GITCRYPT_MAGIC) and b"formcase:view kind=" in b:
            res.append(p)
    return res


def cmd_rules(args) -> int:
    from formcase import rules as R
    allr = R.all_rules()
    for rid in (args.ids or sorted(allr)):
        r = allr.get(rid)
        if r is None:
            print(f"🔴 規則 {rid} が無い")
            return 1
        print(f"{rid}  [{r.get('label', '')}]  {' / '.join(r['refs'])[:60]}")
        print(f"    {r['summary']}")
        if r.get("history"):
            print(f"    経緯: {r['history']}" + (f"   (本文 = {r['same_as']})" if r.get("same_as") else ""))
    return 0


def cmd_views(args) -> int:
    from formcase import views as V
    files = [Path(f) for f in args.files] or view_files()
    bad = False
    for p, st, detail in V.check_files(files, write=args.write):
        if st in ("ok", "locked") and args.quiet:
            continue
        mark = {"ok": "✅", "written": "✏️ ", "stale": "🔴", "error": "🔴", "locked": "⏭️ "}[st]
        print(f"{mark} {p}: {st} {detail}".rstrip())
        bad |= st in ("stale", "error")
    if bad:
        print("   → 規則は spec (forms/reference/*.yaml) を直し、 formcase.py views --write で描き直す (view を手で書き換えない)")
    return 1 if bad else 0


def staged_case_docs(repo: Path, names) -> list:
    """stage した path から、 lint と view の鮮度を見る案件 README を選ぶ (README そのもの / submission.yaml の dir の README)。"""
    from formcase import lint as LI
    out = []
    for n in names:
        p = repo / n
        if Path(n).name == "README.md":
            cand = p
        elif Path(n).name == M.MANIFEST_NAME:
            cand = p.parent / "README.md"
        else:
            continue
        if cand.exists() and LI.is_case_readme(cand) and cand not in out:
            out.append(cand)
    return out


def cmd_lint_staged(args) -> int:
    import contextlib
    import io
    import subprocess

    from formcase import lint as LI
    from formcase import views as V
    repo = Path(args.repo).resolve() if args.repo else G.repo_toplevel(".")
    names = CF.repos()
    if repo is None or (names and repo.name not in names):
        return 0
    try:
        names = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                               capture_output=True, text=True, check=True).stdout.split("\n")
        docs = staged_case_docs(repo, [x for x in names if x])
        if not docs:
            return 0
        f = LI.scan(paths=docs)
        stale = [(p, st, d) for p, st, d in V.check_files(docs) if st in ("stale", "error")]
    except Exception as e:  # noqa: BLE001  engine 故障で commit を止めない (呼び元が rc で判別)
        print(f"⚠️ formcase lint --staged の内部エラー (commit は止めない): {e}", file=sys.stderr)
        return 3
    if not f and not stale:
        return 0
    print("🔴 formcase: 案件 README の commit を止めた (状態の書き写し / 古い generated view)", file=sys.stderr)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        LI.render(f)
    sys.stderr.write(buf.getvalue())
    for p, st, d in stale:
        print(f"   🔴 {p}: generated view が {st} {d} → formcase.py views --write {p}", file=sys.stderr)
    print(f"   (working tree の file を見る。 使い方 = {CF.usage_doc()} #case-readme)", file=sys.stderr)
    return 1


def cmd_lint(args) -> int:
    from formcase import lint as L
    if getattr(args, "staged", False):
        return cmd_lint_staged(args)
    cov = L.claims_coverage()
    for rid, why in cov:
        print(f"   🔴 spec {rid}: {why} (値・yes/no の規則は claims で「矛盾する言い方」 を宣言する = "
              "form-case-pipeline.md #lint-reach)")
    f = L.scan()
    L.render(f)
    if cov:
        return 1
    if not f and not args.quiet:
        print("✅ formcase lint: 規則の書き写し (廃止版の言い回し・記号つき固定値・規則と矛盾する値の主張) なし "
              "(射程 = 正規化した表記の揺れ + spec が宣言した言い換えの形。 それ以外の言い換えは見えない = "
              "form-case-pipeline.md #lint-reach)")
    return 1 if f else 0


def cmd_new(args) -> int:
    from formcase import scaffold as SC
    res = SC.new_case(args.form, args.case, args.doc, args.workbook, args.todo, group=args.group,
                      from_doc=args.from_doc)
    print(f"✏️  {'base' if args.from_doc else '雛形'} → {res['workbook']}")
    if res.get("notice"):
        print(f"   {res['notice']}")
    print(f"✏️  manifest → {res['manifest']}")
    print(f"✏️  記入 stub → {res['stub']}  (value=None の欄を一次情報から埋めて python3 で実行)")
    print(f"✏️  README → {res['readme']}  (値の出典だけを書く。 状態は README 先頭の生成表 = manifest から)")
    print(f"   次: python3 {res['stub'].name} --dry-run → 記入 → formcase.py build {args.case} --doc {args.doc}")
    return 0


def cmd_add_group(args) -> int:
    from formcase import scaffold as SC
    res = SC.add_group(args.case, args.doc, args.group)
    print(f"✏️  manifest → {res['manifest']}  ({args.doc}/{args.group} = draft)")
    print(f"✏️  記入 stub → {res['stub']}  (value=None の欄を一次情報から埋める。 任意の欄 〔本人の住所・口座など〕 は"
          f" 回答があれば行を足す、 値は stub に書かず value_from / value_from_text で実行時に読む)")
    print(f"   次: python3 {res['stub'].name} --group {args.group} --dry-run → 記入 → "
          f"formcase.py build {args.case} --doc {args.doc} --group {args.group}")
    return 0


def cmd_build(args) -> int:
    from formcase import check as CK
    from formcase import recipes as RC
    m = M.load(args.case)
    docs = [args.doc] if args.doc else list(m.documents)
    rc = 0
    for lv, where, msg in CK.frozen_lines(m):
        print(f"   {lv} {where}: {msg}")
    for doc in docs:
        allg = list((m.doc(doc).get("groups") or {}).keys())
        want = args.group or [g for g in allg if not m.group_is_frozen(doc, g)]
        frozen = [g for g in want if m.group_is_frozen(doc, g)]
        if frozen and not args.out_dir:
            print(f"🔴 {doc}: group {frozen} は凍結 = 作らない。 作り直すなら formcase.py reopen {args.case} {doc} <group> "
                  "--reason … (新しい file 名の issue)。 照合だけなら --out-dir に作る")
            rc = 1
            continue
        try:
            recipe = RC.recipe_for(m.doc(doc).get("form"))
        except RC.BuildError as e:
            print(f"⏭️  {doc}: {e}")
            continue
        want = [g for g in want if g in recipe.outputs] if not args.group else want
        if not want:
            print(f"⏭️  {doc}: 作る group が無い (全部凍結、 または recipe の射程外)")
            continue
        print(f"── build {doc}: group {want}" + (f" → {args.out_dir} (照合用、 案件 dir には書かない)" if args.out_dir else ""))
        try:
            written = RC.build(m, doc, want, args.out_dir)
        except RC.BuildError as e:
            print(f"🔴 {e}")
            rc = 1
            continue
        for g, outs in written.items():
            for role, p in outs.items():
                print(f"   ✏️  {g}/{role} → {p}")
        print("   👁 render して目視 (gate は既知の失敗形しか見ない)。 刷ったら formcase.py freeze … --state printed --paper same")
    return rc


def cmd_bind(args) -> int:
    """雛形の identity (sha256) と素刷り (Excel が雛形をそのまま刷った PDF、 cache) を記録し、 雛形の宣言と素刷りの差
    (= 雛形自身の欠陥: Excel が刷らない字・####) を出す。 build は記録と違う雛形なら ⚠️ (form-case-pipeline.md#fidelity)。"""
    import subprocess

    from formcase import fidelity as FD
    from formcase import specs as S
    spec = S.get(args.form)
    if spec is None:
        print(f"🔴 spec {args.form!r} が無い (在るのは {S.spec_ids()})")
        return 2
    rec = FD.write_bind(spec, blank=not args.no_blank)
    print(f"── bind {args.form}: {rec['template']} sha256 {rec['template_sha256'][:12]}… → {FD.bind_file(spec)}")
    tpl = S.template_path(spec)
    for key, p in (rec.get("blank") or {}).items():
        if not p:
            print(f"   ⚪ {key}: 素刷りを作れなかった")
            continue
        sheet = key.split("!")[0]
        r = subprocess.run([sys.executable, str(FD.STATIC_TEXT), str(tpl), p, "--target", key, "--filled", str(tpl), "--blank", p],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        body = [x.rstrip() for x in r.stdout.splitlines()[1:] if x.strip()]
        print(f"   素刷り {sheet}: {p}")
        for x in body:
            print("   " + x.strip() + ("   ← 雛形自身の欠陥 (Excel が刷らない字) = render: で直すか受け入れる" if x.strip().startswith("🔴") else ""))
    return 0


def cmd_normalize(args) -> int:
    """workbook を Excel で開いて保存するだけ (値は書かない) = Mac Excel の格子の形にする (freeze の前提、 fingerprint.py)。
    凍結 group の記録 (値・書式) が変わらないことを後で確かめ、 変わったら元の bytes に戻す。"""
    import shutil
    import tempfile

    from formcase import excel as X
    from formcase import fingerprint as FP

    m = M.load(args.case)
    wb = m.workbook(args.doc)
    if wb is None or not wb.exists():
        print(f"🔴 {args.doc}: workbook が無い", file=sys.stderr)
        return 2
    from formcase import docx_form as DF
    from formcase import specs as SP
    if DF.is_docx(SP.get(m.doc(args.doc).get("form"))):
        print(f"✅ {wb.name}: Word 様式は normalize 不要 (fill が雛形から作り直し、 digest は文字と書式だけを見る)")
        return 0
    M.read_bytes(wb)
    before = FP.last_writer(wb)
    if before == FP.MAC_EXCEL:
        print(f"✅ {wb.name}: 既に Mac Excel の保存形 (何もしない)")
        return 0
    with tempfile.TemporaryDirectory(prefix="formcase-normalize-") as td:
        backup = Path(td) / wb.name
        shutil.copy2(wb, backup)
        try:
            X.write_cells(wb, [])      # calculate + save のみ
        except X.ExcelError as e:      # osascript の標準エラーは逐語で e に入っている
            print(f"🔴 {e}", file=sys.stderr)
            return 2
        drift = []
        for gid, g in (m.doc(args.doc).get("groups") or {}).items():
            cur = g.get("current") or {}
            if cur.get("state") in M.FROZEN_STATES and (cur.get("frozen") or {}).get("sheet_digest"):  # docx の document は normalize の対象外
                vals, fmts = M.frozen_sheet_changes(cur["frozen"], wb)
                drift += [f"{gid}: {s}" for s in vals] + [f"{gid}: {s} (書式)" for s in fmts]
        if drift:
            shutil.copy2(backup, wb)
            print(f"🔴 Excel の保存で凍結 group の記録が変わる {drift} → 元の bytes に戻した (normalize しない)", file=sys.stderr)
            return 1
    print(f"✏️  {wb.name}: 最後の保存 {before or '不明'} → {FP.last_writer(wb)} (値は書いていない、 凍結 group の記録は不変)")
    return 0


def cmd_markers(args) -> int:
    from formcase import markers as MK
    bad = False
    for case in (_cases(args)):
        try:
            m = M.load(case)
        except M.Locked:
            continue
        st, p = MK.check_case(m, write=args.write)
        if st in ("ok", "absent-ok") and args.quiet:
            continue
        mark = {"ok": "✅", "absent-ok": "✅", "written": "✏️ ", "stale": "🔴", "extra": "🟡"}[st]
        print(f"{mark} {p}: {st}")
        bad |= st == "stale"
    if bad:
        print("   → 隔離 marker は submission.yaml からの生成物: formcase.py markers --write (手で直さない)")
    return 1 if bad else 0


def cmd_audit(args) -> int:
    ns = argparse.Namespace
    rc = 0
    print("── formcase check (案件 manifest)")
    rc |= cmd_check(ns(cases=[], all=True, quiet=True, no_digest=False))
    print("── formcase markers --check (隔離 marker)")
    rc |= cmd_markers(ns(cases=[], all=True, write=False, quiet=True))
    print("── formcase views --check (generated view)")
    rc |= cmd_views(ns(files=[], write=False, quiet=True))
    print("── formcase lint (規則の書き写し)")
    rc |= cmd_lint(ns(quiet=True))
    print("── formcase spec (頁の役割 = 窓口に出す頁だけを刷る、 form-case-pipeline.md #page-roles)")
    from formcase import specs as SP
    probs = [p for sp in SP.all_specs().values() for p in SP.page_role_problems(sp)]
    for p in probs:
        print(f"🔴 {p}")
    rc |= 1 if probs else 0
    if rc == 0:
        print("✅ formcase audit: 問題なし")
    return rc


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        from formcase import selftest
        return selftest.run()
    ap = argparse.ArgumentParser(prog="formcase.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "check"):
        p = sub.add_parser(name)
        p.add_argument("cases", nargs="*")
        p.add_argument("--all", action="store_true")
        if name == "check":
            p.add_argument("--quiet", action="store_true", help="問題の無い案件は出さない")
            p.add_argument("--no-digest", action="store_true", help="sheet digest を読まない (速い)")
    p = sub.add_parser("freeze")
    p.add_argument("case"); p.add_argument("doc"); p.add_argument("group")
    p.add_argument("--state", required=True, choices=M.FROZEN_STATES)
    p.add_argument("--date"); p.add_argument("--evidence"); p.add_argument("--note")
    for q in (p, sub.add_parser("annotate")):
        if q is not p:
            q.add_argument("case"); q.add_argument("doc"); q.add_argument("group")
            q.add_argument("--issue", help="current (既定) / previous[N]")
        q.add_argument("--paper", choices=M.PAPER_VALUES)
        q.add_argument("--paper-diff"); q.add_argument("--paper-basis"); q.add_argument("--paper-commit")
        q.add_argument("--date-ack", help="date: unknown を owner に確認して分からなかった記録 (聞き直さない)")
        if q is not p:
            q.add_argument("--outputs-ack", help="凍結 issue に出力 file の記録が無いことを確かめた記録 (どこを探したか)")
            q.add_argument("--note", help="issue の note を置き換える (draft も可。 状態の説明は README でなくここ)")
    p = sub.add_parser("reopen")
    p.add_argument("case"); p.add_argument("doc"); p.add_argument("group")
    p.add_argument("--reason", required=True); p.add_argument("--date")
    p = sub.add_parser("guard")
    p.add_argument("--staged", action="store_true", required=True)
    p.add_argument("--repo")
    p = sub.add_parser("rules")
    p.add_argument("ids", nargs="*")
    p = sub.add_parser("views")
    p.add_argument("files", nargs="*")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("lint")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--staged", action="store_true", help="pre-commit 用: stage した案件 README (と submission.yaml の案件) だけ")
    p.add_argument("--repo")
    sub.add_parser("audit")
    p = sub.add_parser("markers")
    p.add_argument("cases", nargs="*")
    p.add_argument("--all", action="store_true")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("normalize")
    p.add_argument("case"); p.add_argument("doc")
    p = sub.add_parser("new")
    p.add_argument("--form", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--doc", required=True)
    p.add_argument("--workbook")
    p.add_argument("--todo")
    p.add_argument("--group", help="その group だけの document (= 後で出す group を別 workbook にする様式)")
    p.add_argument("--from-doc", help="同じ案件の document の workbook を base に copy (数式で先の group を参照する様式)")
    p = sub.add_parser("add-group")
    p.add_argument("case")
    p.add_argument("--doc", required=True)
    p.add_argument("--group", required=True)
    p = sub.add_parser("build")
    p.add_argument("case")
    p.add_argument("--doc")
    p.add_argument("--group", action="append")
    p.add_argument("--out-dir")
    p = sub.add_parser("bind", help="雛形の sha256 と素刷りを記録する (雛形を採用・改訂したとき)")
    p.add_argument("form")
    p.add_argument("--no-blank", action="store_true", help="素刷り (Excel) を作らない = sha256 だけ記録")
    args = ap.parse_args(argv)
    try:
        return {"status": cmd_status, "check": cmd_check, "freeze": cmd_freeze,
                "reopen": cmd_reopen, "annotate": cmd_annotate, "guard": cmd_guard, "rules": cmd_rules,
                "views": cmd_views, "lint": cmd_lint, "audit": cmd_audit,
                "new": cmd_new, "add-group": cmd_add_group, "build": cmd_build, "markers": cmd_markers,
                "normalize": cmd_normalize, "bind": cmd_bind}[args.cmd](args)
    except M.ManifestError as e:
        print(f"🔴 {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        # pre-commit の入口 (guard / lint --staged) だけは、 想定外の例外を 1 で落とさない。
        # 1 = 「明示の BLOCK」 は呼び元 (pre-commit chain) の約束なので、 engine の故障が
        # 1 になると**無関係な commit が全部止まる** (= 案件 README も新規 file も。 実測)。
        # しかも「凍結を守って止めた」 のと区別がつかない。
        # 故障は 3 = 「検査が走っていない」 として呼び元に渡し、 commit は通す。
        # cmd_guard / cmd_lint_staged の内側にも同じ受けがあるが、 その try の外
        # (import・repo の解決・設定の読み込み) で落ちる型はここでしか拾えない。
        if args.cmd == "guard" or (args.cmd == "lint" and getattr(args, "staged", False)):
            print(f"⚠️ formcase {args.cmd} の内部エラー (commit は止めない): {e!r}", file=sys.stderr)
            return 3
        raise


if __name__ == "__main__":
    sys.exit(main())
