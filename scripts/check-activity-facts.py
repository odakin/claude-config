#!/usr/bin/env python3
"""check-activity-facts.py — Keep the owner's non-public activity facts (what was applied for, when, how many, what the office said, which deadline passed) out of public repos: pre-commit / commit-msg check on added lines, --scan-tree inventory with an ack list, --replay calibration, --selftest.

Why (2026-09-14): public convention docs and script fixtures carried which grants the owner applied for,
when, how many, the program names, the office's corrections and the real staging file names — added a
line at a time over four months while hoisting procedure knowledge. None of it is an identifier or quoted
text, so the identifier gates and the verbatim gate never looked at it
(CLAUDE.md#owner-activity-facts).

Two kinds of finding:
  TERM   a literal from the personal layer's activity-fact-terms.txt (program names, area codes, file-name
         stems) on an added line or in the message -> BLOCK (exit 1). The literal is never printed.
  FACT   an event word (応募 / 差し戻し / 採択 / 評点 / 種目 / 推薦書 / 出張 / 謝金 / 受診 ...) on the same line
         as a date (YYYY-MM[-DD], YYYY 年[度], or a relative time such as 3 週後 / 翌月) or a count (N 種目 / 本 /
         件 / 回 / 箇所) -> WARN (exit 0) in the commit hooks. General procedure text has neither, so the
         co-occurrence is the signal; a rule's own creation date next to a review word also fires, which is why
         this kind only warns. A provenance marker (origin: / 起源 / 実測 / 実例 / 初出) directly followed by a
         date is a FACT even without an event word (2026-09-14: the house style put "when / which form / how
         many prints" right there), unless the date is the rule's own (追記 / 新設 / 版 next to it).
The inventory (--scan-tree) reports FACT lines that are not in the ack list (hash of path + normalized line)
and exits 1 if any are new, so an accepted line is decided once.

Usage:
  check-activity-facts.py                         staged added lines of the repo in cwd (public repos only)
  check-activity-facts.py --message-file FILE     commit message
  check-activity-facts.py --scan-tree REPO [--ack FILE] [--write-ack]   inventory of tracked text files
  check-activity-facts.py --scan-public [ROOT] [--ack FILE]             the same for every public clone under ROOT
  check-activity-facts.py --replay REPO [--max-commits N]              per-commit counts over history
  check-activity-facts.py --lines FILE            classify each line of FILE (calibration on removed lines)
  check-activity-facts.py --selftest
Bypass for one commit: CLAUDE_ACTIVITY_FACTS_GUARD=0. Exit 3 = internal error (the hooks do not block on it).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = Path(".claude") / "public-repo.marker"
TERMS_FILE = "activity-fact-terms.txt"
ACK_FILE = "activity-facts-ack.txt"
# Words that name a grant / review / nomination event. Generic procedure words (提出, 申請, 審査, 指摘, 締切, 超過)
# were measured too noisy on the public repos' history (rule creation dates, "user 指摘", "決定超過") and are left out.
ACTIVITY = ("応募", "再提出", "差し戻", "差戻", "採択", "不採択", "採否", "交付", "内定", "評点", "赤入れ", "種目",
            "調書", "査読依頼", "公募", "萌芽", "学術変革", "学変", "学振", "科研費", "基盤研究", "基盤(", "基盤B",
            "挑戦的研究", "推薦書", "学内〆",
            # 2026-09-14 second review: dated events outside grants are the same class (trips, honoraria,
            # review invitations, grading, medical visits, household ledgers). Generic procedure words
            # (様式 / 審査 / 査読 / 委員) stay out; the provenance-marker rule below covers their dated origins.
            "出張", "旅費", "謝金", "査読招待", "委嘱", "成績", "受診", "家計", "口座")
DATE_RE = re.compile(r"(?<![0-9])20[0-9]{2}(-[01][0-9](-[0-3][0-9])?|\s?年度?|(?=\s?(実測|実例)))")
# a relative time is a date too: "3 週後" / "11 日埋もれ" / "1.5 ヶ月超過" / 翌月 (2026-09-14). 前年 / 昨年 are left
# out: procedure text says 前年の… generically ("read last year's red ink") and they fired on rules, not events.
REL_TIME_RE = re.compile(r"(?<![0-9.])[0-9]+(\.[0-9]+)?\s?(日|週間?|か月|ヶ月|カ月)\s?(後|前|超過|遅れ|埋もれ|経過)|翌日|翌週|翌月")
# a provenance marker directly followed by a date, on a line that names an administrative / personal event
# (form, trip, honorarium, office remark, review request, grading, visit ...), is a fact whatever the narrow
# vocabulary above says: the house style wrote "origin: YYYY-MM-DD <which form / what the office said>"
# (2026-09-14; measured on the public docs: with the event filter 103 lines, 81 of them facts; without it
# ~280 technical provenance lines such as "実測 YYYY-MM-DD: the relay has no locking"). A rule's own date
# ("追記" / "新設" / "版" right after it) is not an event.
PROVENANCE_RE = re.compile(r"(origin|起源|実例|初出|実測)\s*[:：=]?\s*[(（]?\s*20[0-9]{2}|[(（]\s*20[0-9]{2}(-[0-9]{2}){0,2}\s*(実測|実例)")
PROVENANCE_EVENT_RE = re.compile(r"様式|出張|旅費|謝金|招待|勧誘|依頼|成績|講義|受診|診断書|家計|口座|委員|会議|窓口|事務|申請|提出|印刷|刷り|〆|締切|審査|査読|推薦|応募|学生")
RULE_DATE_RE = re.compile(r"追記|新設|制定|版|hoist|昇格|移動|改訂|split|renumber")
COUNT_RE = re.compile(r"(?<![0-9.])[0-9]+\s?(種目|本|件|回|箇所|度)")
TEXT_SUFFIXES = (".md", ".markdown", ".py", ".sh", ".txt", ".yaml", ".yml", ".json", ".toml", ".tex", ".html", ".js", ".ts")


def _git(args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout


def personal_layer():
    env = os.environ.get("CLAUDE_PERSONAL_LAYER")
    if env and env != "none" and Path(env).is_dir():
        return Path(env)
    base = Path(os.environ.get("CLAUDE_BASE", Path.home() / "Claude"))
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if (d / ".claude-personal-layer").is_file():
                return d
    return None


def load_terms(layer):
    if layer is None or not (layer / TERMS_FILE).is_file():
        return []
    out = []
    for line in (layer / TERMS_FILE).read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


def _term_hit(line, term):
    if term.isascii():
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", line) is not None
    return term in line


def classify(line, terms):
    """Return a list of finding kinds for one line: 'TERM' and/or 'FACT:<activity word>+date|count'."""
    kinds = []
    if any(_term_hit(line, t) for t in terms):
        kinds.append("TERM")
    word = next((w for w in ACTIVITY if w in line), None)
    if word:
        marks = [m for m, rx in (("date", DATE_RE), ("count", COUNT_RE)) if rx.search(line)]
        if "date" not in marks and REL_TIME_RE.search(line):
            marks.insert(0, "date")
        if marks:
            kinds.append(f"FACT:{word}+{'+'.join(marks)}")
    if not any(k.startswith("FACT:") for k in kinds):
        prov = PROVENANCE_RE.search(line)
        if prov and PROVENANCE_EVENT_RE.search(line) and not RULE_DATE_RE.search(line[prov.end():prov.end() + 30]):
            kinds.append("FACT:来歴+date")
    return kinds


def added_lines(diff_text):
    path, lineno, out = None, 0, []
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif path and raw.startswith("+") and not raw.startswith("+++"):
            out.append((path, lineno, raw[1:]))
            lineno += 1
        elif path and not raw.startswith("-"):
            lineno += 1
    return out


def is_public_repo(repo):
    return (Path(repo) / MARKER).is_file()


def line_key(path, text):
    return hashlib.sha256((path + "\0" + " ".join(text.split())).encode("utf-8")).hexdigest()[:20]


def report(findings, where, out=print):
    """findings = [(path, lineno, kinds)]; never prints the line text (it may hold the fact)."""
    blocked = any("TERM" in k for _, _, ks in findings for k in ks)
    for path, lineno, kinds in findings:
        out(f"  {path}:{lineno}  {', '.join(kinds)}")
    if blocked:
        out(f"🚫 [activity-facts] {where} contains a literal from {TERMS_FILE} (program name / code / file-name stem). "
            f"Rewrite it in general form. Bypass only for a false match: CLAUDE_ACTIVITY_FACTS_GUARD=0")
    elif findings:
        out(f"⚠️ [activity-facts] {where}: an activity word next to a date or a count on {len(findings)} line(s). "
            f"If the line tells when / what / how many for the owner, write it in general form "
            f"(CLAUDE.md#owner-activity-facts). Not blocked.")
    return 1 if blocked else 0


def scan_staged(repo, terms, out=print):
    if not is_public_repo(repo):
        return 0
    rc, diff = _git(["diff", "--cached", "--unified=0", "--no-color"], cwd=repo)
    if rc != 0:
        return 3
    findings = []
    for path, lineno, text in added_lines(diff):
        kinds = classify(text, terms)
        if kinds:
            findings.append((path, lineno, kinds))
    return report(findings, "the staged change", out)


def scan_message(path, terms, out=print):
    findings = []
    for i, text in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if text.startswith("#"):
            continue
        kinds = classify(text, terms)
        if kinds:
            findings.append(("<message>", i, kinds))
    return report(findings, "the commit message", out)


def read_ack(path):
    if path and Path(path).is_file():
        return {l.split()[0] for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    return set()


def scan_tree(repo, terms, ack_path=None, write_ack=False, out=print):
    repo = Path(repo).resolve()
    rc, listing = _git(["ls-files", "-z"], cwd=repo)
    if rc != 0:
        out(f"✗ [activity-facts] not a git repo: {repo}")
        return 3
    ack = read_ack(ack_path)
    new, acked, terms_hit, keys = [], 0, 0, []
    for rel in listing.split("\0"):
        if not rel.endswith(TEXT_SUFFIXES):
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            kinds = classify(line, terms)
            if not kinds:
                continue
            key = line_key(f"{repo.name}/{rel}", line)
            if "TERM" in kinds:
                terms_hit += 1
                new.append((rel, i, kinds))
            elif key in ack:
                acked += 1
            else:
                new.append((rel, i, kinds))
                keys.append((key, f"{repo.name}/{rel}:{i}"))
    for rel, i, kinds in new:
        out(f"  {rel}:{i}  {', '.join(kinds)}")
    if write_ack and ack_path:
        with open(ack_path, "a", encoding="utf-8") as fh:
            for key, loc in keys:
                fh.write(f"{key}  {loc}\n")
        out(f"acked {len(keys)} line(s) into {ack_path} (TERM findings are never acked)")
        new = [x for x in new if "TERM" in x[2]]
    out(f"scan-tree [activity-facts]: {repo.name}: {len(new)} unacked finding(s) ({terms_hit} TERM), {acked} acked")
    return 1 if new else 0


def scan_public(root, terms, ack_path=None, out=print):
    """--scan-tree over every clone under root that carries the public-repo marker; one summary line."""
    root = Path(root)
    repos = [d for d in sorted(root.iterdir()) if d.is_dir() and (d / MARKER).is_file() and (d / ".git").exists()]
    if not repos:
        out(f"scan-public [activity-facts]: no public clones under {root}")
        return 0
    worst, bad = 0, []
    for d in repos:
        lines = []
        rc = scan_tree(d, terms, ack_path, out=lines.append)
        if rc:
            bad.append(d.name)
            for l in lines:
                out(l)
        worst = max(worst, rc)
    out(f"scan-public [activity-facts]: {len(repos)} public clone(s), {len(bad)} with unacked findings"
        + (f" ({', '.join(bad)})" if bad else ""))
    return worst


def replay(repo, terms, max_commits=None, out=print):
    rc, revs = _git(["rev-list", "--no-merges", "HEAD"], cwd=repo)
    if rc != 0:
        return 3
    revs = revs.split()[: max_commits or None]
    commits_fact = commits_term = lines_fact = 0
    for rev in revs:
        _, diff = _git(["show", "--unified=0", "--no-color", "--format=", rev], cwd=repo)
        kinds = [classify(t, terms) for _, _, t in added_lines(diff)]
        f = sum(1 for k in kinds if any(x.startswith("FACT") for x in k))
        t = sum(1 for k in kinds if "TERM" in k)
        lines_fact += f
        commits_fact += f > 0
        commits_term += t > 0
    out(f"replay [activity-facts]: {Path(repo).name}: {len(revs)} commits; FACT warn in {commits_fact} "
        f"({lines_fact} lines), TERM block in {commits_term}")
    return 0


def selftest():
    failed = []

    def expect(name, cond):
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            failed.append(name)

    terms = ["MOCKPROGRAM", "99Z999", "テスト制度"]
    # fixtures are assembled at run time so this file does not trip its own inventory
    ev, ev2 = "".join(["応", "募"]), "".join(["種", "目"])
    dated = "20" + "31-04-02 に 3 " + ev2 + "の" + ev + "を出した"
    expect("date + event word -> FACT", classify(dated, terms) == ["FACT:" + ev + "+date+count"])
    expect("count alone + event word -> FACT", classify("模擬の" + ev + " 2 件で観測", terms) == ["FACT:" + ev + "+count"])
    expect("procedure text without date or count -> nothing", classify("差し" + "戻しは正常フローで、窓は何度でも開く", terms) == [])
    expect("date without an event word -> nothing", classify("20" + "31-04-02 に script を分離した", terms) == [])
    expect("ASCII term needs word boundaries (underscore is a boundary)", classify("uses MOCKPROGRAM forms", terms) == ["TERM"]
           and classify("MOCKPROGRAMS", terms) == [] and classify("S-1_MOCKPROGRAM_x.pdf", terms) == ["TERM"])
    expect("non-ASCII term is a substring match", classify("テスト制度の様式", terms) == ["TERM"])
    expect("decimal is not a count", classify("閾値 0.5 本の線で" + ev, terms) == [])
    prov_mark = "ori" + "gin: "
    expect("provenance marker + date -> FACT without an event word",
           classify(prov_mark + "20" + "31-05-14 の会議で発覚", terms) == ["FACT:来歴+date"])
    expect("provenance marker + the rule's own date -> nothing", classify(prov_mark + "20" + "31-05-14 追記", terms) == [])
    expect("relative time + event word -> FACT", classify("3 週後に" + ev + " を出した", terms) == ["FACT:" + ev + "+date"])
    expect("dated event outside grants -> FACT", (classify("20" + "31-06 の出" + "張で謝" + "金を受けた", terms) or [""])[0].startswith("FACT:"))
    diff = "diff --git a/x.md b/x.md\n+++ b/x.md\n@@ -0,0 +1,2 @@\n+" + dated + "\n+一般の手順\n"
    expect("added_lines keeps path and line numbers", added_lines(diff) == [("x.md", 1, dated), ("x.md", 2, "一般の手順")])
    lines = []
    rc = report([("x.md", 1, ["FACT:" + ev + "+date"])], "the staged change", out=lines.append)
    expect("FACT only -> warn, exit 0, no line text printed", rc == 0 and dated not in "\n".join(lines))
    lines = []
    rc = report([("x.md", 1, ["TERM"])], "the staged change", out=lines.append)
    expect("TERM -> block, exit 1, the literal is not printed", rc == 1 and "MOCKPROGRAM" not in "\n".join(lines))
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "pub"
        (repo / ".claude").mkdir(parents=True)
        (repo / MARKER).write_text("")
        (repo / "doc.md").write_text("一般の手順\n" + dated + "\n")
        _git(["init", "-q"], cwd=repo)
        _git(["add", "."], cwd=repo)
        ack = Path(td) / "ack.txt"
        out = []
        expect("scan-tree: an unacked FACT line -> exit 1", scan_tree(repo, terms, ack, out=out.append) == 1)
        out = []
        scan_tree(repo, terms, ack, write_ack=True, out=out.append)
        out = []
        expect("scan-tree: after --write-ack the same line passes", scan_tree(repo, terms, ack, out=out.append) == 0)
        (repo / "doc.md").write_text("一般の手順\n" + dated + "\nMOCKPROGRAM の様式\n")
        out = []
        expect("scan-tree: a TERM line is never acked", scan_tree(repo, terms, ack, write_ack=True, out=out.append) == 1)
        _git(["add", "."], cwd=repo)
        out = []
        expect("scan-public: finds the marked clone and reports it (exit 1)",
               scan_public(Path(td), terms, ack, out=out.append) == 1 and "1 public clone(s), 1 with unacked" in out[-1])
        out = []
        expect("staged: public repo with a TERM line blocks", scan_staged(repo, terms, out=out.append) == 1)
        (repo / MARKER).unlink()
        out = []
        expect("staged: a repo without the marker is skipped", scan_staged(repo, terms, out=out.append) == 0)
    print("selftest:", "ALL PASS" if not failed else f"FAILED ({len(failed)})")
    return 0 if not failed else 1


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if os.environ.get("CLAUDE_ACTIVITY_FACTS_GUARD") == "0":
        return 0
    terms = load_terms(personal_layer())

    def opt(name):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None

    if "--message-file" in args:
        return scan_message(opt("--message-file"), terms)
    if "--scan-tree" in args:
        return scan_tree(opt("--scan-tree"), terms, opt("--ack"), "--write-ack" in args)
    if "--scan-public" in args:
        root = opt("--scan-public")
        return scan_public(root if root and not root.startswith("--") else Path.home() / "Claude", terms, opt("--ack"))
    if "--replay" in args:
        m = opt("--max-commits")
        return replay(opt("--replay"), terms, int(m) if m else None)
    if "--lines" in args:
        hits = 0
        lines = Path(opt("--lines")).read_text(encoding="utf-8").splitlines()
        for text in lines:
            hits += bool(classify(text, terms))
        print(f"lines [activity-facts]: {hits}/{len(lines)} line(s) classified")
        return 0
    return scan_staged(os.getcwd(), terms)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # the hooks treat 3 as "engine broken", not as a finding
        print(f"✗ [activity-facts] internal error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        sys.exit(3)
