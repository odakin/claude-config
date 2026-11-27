#!/usr/bin/env python3
"""dialogue_record.py — 研究の対話係の提出を受けた後、 研究の現在地が project の記録に写ったかを掲示板の event と git から判定する部品。

何を塞ぐか (正本 = conventions/closing-sweep.md#dialogue-list-intake、 multi-session-coordination.md#dialogue-record-split):
  対話係の締めの一覧 (引き継ぎ書) が project の repo の外 (研究者の個人の層) に置かれて受け取られ、 project の SESSION の
  停止点は古いまま残った (実測)。 検収は引き継ぎの物の受け取りで、 写したかは見ない = 写したかを、 道具が別に数える。

判定 (文の一致では見ない = 言い換えで外れる):
  対話係の依頼 = 依頼の details に `worker-kind: dialogue` (掲示板の `request --dialogue` の印) があるか、 担当の役の名が
    `role-<project>-dialogue` (末尾に窓の頭 8 字が付いてもよい)。 Codex の依頼は印を持てない (道具が断る) ので役の名でも見る。
    ⚠️ 起動の文を対話係の形にするか (CONTRACT.md#dialogue-worker-handoff) は役の名から推さない = それとは別の、 知らせのための判定。
  外の提出 = 提出の deliverables のどれも `<project>/` の下に無い (workspace からの path。 project の dir が workspace に在るときだけ)。
  写した = 提出の時刻より後に、 project の SESSION.md の「現在地の行」 (📌・停止点・現在地・「次」 を含む行) を変えた commit が在るか、
    作業 tree に未 commit のその変更が在る。 SESSION.md にその印の行が 1 つも無ければ、 SESSION.md の変更なら何でも数える。
  理由つきで通す = その依頼への note の summary が `dialogue-record: ` で始まる:
    `dialogue-record: <repo>@<commit>` (写した commit を名指す。 commit が repo に在れば写したと数える) /
    `dialogue-record: skip <理由 4 字以上>` (停止点が本当に変わらない回など)。

使い手: scripts/child-wrap-check.py --hook-accept (受け取りの直後の 1 行) / 個人層の締めの Stop の網と点呼の道具。
OS: macOS / Linux / Windows (Git Bash)。 標準 library、 Python 3.8+。 --selftest 内蔵。
"""
import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path

DIALOGUE_ROLE = re.compile(r"^role-[a-z0-9][a-z0-9-]*-dialogue(?:-[0-9a-f]{8})?$")
STATE_MARK = re.compile(r"📌|停止点|現在地|^\s*[-*]?\s*\**次\**\s*[=:：]|\*\*次\*\*")
NOTE_PREFIX = "dialogue-record: "
REF = re.compile(r"^([A-Za-z0-9._-]+)@([0-9a-f]{7,40})\b")
REPO_AT = re.compile(r"^([A-Za-z0-9._-]+)@[0-9a-f]{7,40}:(.+)$")
SESSION_FILE = "SESSION.md"


def _details(ev):
    return str(ev.get("details") or "")


def _assignee(ev):
    a = ev.get("assignee") or {}
    return str(a.get("session_id") or "") if isinstance(a, dict) else ""


def _project(ev):
    p = ev.get("project")
    return str((p.get("key") if isinstance(p, dict) else p) or "")


def is_dialogue_request(req):
    if any(line.strip() == "worker-kind: dialogue" for line in _details(req).splitlines()):
        return True
    return bool(DIALOGUE_ROLE.match(_assignee(req)))


def project_dir(workspace, key):
    d = Path(workspace) / key
    return d if key and d.is_dir() and (d / ".git").exists() else None


def outside_deliverables(submit, workspace, key):
    """提出の deliverables が全部 project の外なら、 その list。 1 つでも project の中に在るか、 deliverables が無ければ []。"""
    dels = [str(x) for x in (submit.get("deliverables") or []) if str(x).strip()]
    if not dels:
        return []
    ws = Path(workspace).resolve()
    proj = (ws / key).resolve()
    out = []
    for d in dels:
        m = REPO_AT.match(d)  # `<repo>@<commit>:<path>` = その repo の版の file
        raw = Path(os.path.expanduser(m.group(1) + "/" + m.group(2) if m else d))
        if raw.is_absolute():
            p = raw.resolve()
        elif not m and not (ws / raw).exists() and (proj / raw).exists():
            p = (proj / raw).resolve()  # project の repo からの path で書いた提出 (repo の中)
        else:
            p = (ws / raw).resolve()
        if p == proj or proj in p.parents:
            return []
        out.append(d)
    return out


def _git(args, cwd, timeout=30):
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None


def _changed_lines(patch):
    return [ln[1:] for ln in patch.splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]


def state_changes_since(repo, since_iso, session_file=SESSION_FILE):
    """提出の後に SESSION.md の現在地の行を変えた commit の短い id の list (作業 tree の未 commit の変更は 'worktree')。"""
    repo = Path(repo)
    f = repo / session_file
    if not f.is_file():
        return []
    try:
        has_mark = any(STATE_MARK.search(ln) for ln in f.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        has_mark = False

    def counts(patch):
        lines = _changed_lines(patch)
        return bool(lines) and (not has_mark or any(STATE_MARK.search(ln) for ln in lines))

    out = []
    log = _git(["log", "--since=" + since_iso, "--format=%x00%h", "-p", "--", session_file], repo) or ""
    for chunk in log.split("\x00")[1:]:
        sha, _, patch = chunk.partition("\n")
        if counts(patch):
            out.append(sha.strip())
    wt = _git(["diff", "HEAD", "--", session_file], repo) or ""
    if counts(wt):
        out.append("worktree")
    return out


def record_note(events, request_id, workspace=None):
    """その依頼への `dialogue-record: ` の note を新しい順に見て、 (種類, 中身) を返す。 種類 = 'commit' / 'skip' / None。
    commit を名指す note は、 workspace を渡せばその repo に commit が在るときだけ数える。"""
    notes = sorted((e for e in events if e.get("kind") == "note" and e.get("request_id") == request_id
                    and str(e.get("summary") or "").startswith(NOTE_PREFIX)),
                   key=lambda e: str(e.get("created_at") or ""), reverse=True)
    for e in notes:
        body = str(e["summary"])[len(NOTE_PREFIX):].strip()
        if body.startswith("skip"):
            reason = body[4:].strip(" :：")
            if len(reason) >= 4:
                return "skip", reason
            continue
        m = REF.match(body)
        if m:
            if workspace is None or _git(["cat-file", "-e", m.group(2) + "^{commit}"], Path(workspace) / m.group(1)) is not None:
                return "commit", m.group(0)
    return None, ""


def _ts(s):
    try:
        return _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def gaps(events, workspace, requester=None, request_ids=None):
    """対話係の依頼のうち、 提出が project の外に在り、 提出の後に project の現在地が写っていないものの list。
    1 件 = dict(request, submit, project, outside, accepted)。 requester = 依頼元の session の id (頭が合えば数える)。
    request_ids = 見る依頼を絞る。 提出 (submit) の無い依頼は見ない。 受け取りの有無は accepted に入れる。"""
    by_req = {}
    for e in events:
        rid = e.get("request_id")
        if rid:
            by_req.setdefault(rid, []).append(e)
    out = []
    for rid, evs in by_req.items():
        if request_ids is not None and rid not in request_ids:
            continue
        req = next((e for e in evs if e.get("kind") == "request"), None)
        if not req or not is_dialogue_request(req):
            continue
        if requester:
            sid = str((req.get("actor") or {}).get("session_id") or "")
            if not (sid and (sid.startswith(requester) or requester.startswith(sid))):
                continue
        subs = sorted((e for e in evs if e.get("kind") == "submit"), key=lambda e: str(e.get("created_at") or ""))
        if not subs:
            continue
        sub, key = subs[-1], _project(req)
        repo = project_dir(workspace, key)
        outside = outside_deliverables(sub, workspace, key) if repo else []
        if not outside:
            continue
        if state_changes_since(repo, str(sub.get("created_at") or "")):
            continue
        if record_note(evs, rid, workspace)[0]:
            continue
        accepted = any(e.get("kind") == "accept" for e in evs)
        out.append(dict(request=rid, submit=sub.get("event_id"), project=key, outside=outside, accepted=accepted))
    return out


def gap_line(g, rule="closing-sweep.md#dialogue-list-intake"):
    return ("📌 研究の対話係の提出 (%s) は project の外 (%s) にあり、 提出の後に %s/%s の現在地の行 (停止点・📌) が変わっていない"
            " = 一覧の「共有 repo に写すもの」 (研究者の発言は逐語・停止点・未決) を %s の SESSION の現在地と裁定の台帳に写す"
            " (この turn か、 この窓の締めで)。 本当に変わらない回は、 その依頼に note `%sskip <理由>` (写した commit を名指すなら"
            " `%s%s@<commit>`)。 規則 = %s"
            % (g["request"], ", ".join(g["outside"])[:160], g["project"], SESSION_FILE, g["project"], NOTE_PREFIX, NOTE_PREFIX,
               g["project"], rule))


def _selftest():
    import tempfile
    ok = True

    def expect(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL", name, got, want)

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        repo = ws / "proj"
        repo.mkdir()
        env = dict(os.environ, GIT_AUTHOR_DATE="2099-01-01T00:00:00Z", GIT_COMMITTER_DATE="2099-01-01T00:00:00Z")

        def git(*a, date=None):
            e = dict(env)
            if date:
                e.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], cwd=str(repo),
                                  capture_output=True, env=e, text=True)
        git("init", "-q")
        (repo / SESSION_FILE).write_text("# S\n- 📌 停止点: 節 A\n- 図: 済み\n", encoding="utf-8")
        git("add", SESSION_FILE)
        git("commit", "-q", "-m", "s", date="2099-01-01T00:00:00Z")
        req = {"kind": "request", "event_id": "R1", "request_id": "R1", "project": {"key": "proj"},
               "actor": {"session_id": "aaaa1111-0000-4000-8000-000000000000"}, "details": "",
               "assignee": {"session_id": "role-proj-dialogue-aaaa1111"}}
        sub = {"kind": "submit", "event_id": "S1", "request_id": "R1", "created_at": "2099-01-02T00:00:00Z",
               "deliverables": ["prefs/plans/x-dialogue-handoff.md"]}
        acc = {"kind": "accept", "event_id": "A1", "request_id": "R1", "created_at": "2099-01-02T01:00:00Z"}
        evs = [req, sub, acc]
        expect("役の名で対話係と見る", is_dialogue_request(req), True)
        expect("印で対話係と見る", is_dialogue_request({"details": "a: b\nworker-kind: dialogue"}), True)
        expect("ほかの役は対話係でない", is_dialogue_request({"assignee": {"session_id": "role-proj-build-desk"}}), False)
        expect("提出が外 + 写していない = 1 件", [g["request"] for g in gaps(evs, ws)], ["R1"])
        expect("依頼元で絞る (頭 8 字)", (len(gaps(evs, ws, requester="aaaa1111")), len(gaps(evs, ws, requester="bbbb2222"))), (1, 0))
        expect("知らせの文が project と note の形を名指す", all(w in gap_line(gaps(evs, ws)[0]) for w in ("proj/SESSION.md", "dialogue-record: skip")), True)
        inside = dict(sub, deliverables=["proj/notes/handoff.md"])
        expect("提出が project の中 = 見ない", gaps([req, inside, acc], ws), [])
        (repo / "review").mkdir()
        (repo / "review" / "CLOSING.md").write_text("x\n", encoding="utf-8")
        expect("project の repo からの path の提出も中", gaps([req, dict(sub, deliverables=["review/CLOSING.md"]), acc], ws), [])
        expect("<repo>@<commit>:<path> の提出は repo の部分で見る",
               (len(gaps([req, dict(sub, deliverables=["prefs@1234567:plans/x.md"]), acc], ws)),
                gaps([req, dict(sub, deliverables=["proj@1234567:notes/x.md"]), acc], ws)), (1, []))
        # 現在地でない行だけ変えた commit は数えない
        (repo / SESSION_FILE).write_text("# S\n- 📌 停止点: 節 A\n- 図: 済み (検収も)\n", encoding="utf-8")
        git("commit", "-q", "-am", "other", date="2099-01-03T00:00:00Z")
        expect("現在地でない行の変更では写したと数えない", len(gaps(evs, ws)), 1)
        # 現在地の行を変えた commit (提出の後) で消える
        (repo / SESSION_FILE).write_text("# S\n- 📌 停止点: 節 B\n- 図: 済み (検収も)\n", encoding="utf-8")
        git("commit", "-q", "-am", "state", date="2099-01-04T00:00:00Z")
        expect("提出の後に停止点の行を変えた = 写した", gaps(evs, ws), [])
        expect("提出より前の変更は数えない", len(state_changes_since(repo, "2099-01-05T00:00:00Z")), 0)
        # 作業 tree の未 commit の変更も数える
        (repo / SESSION_FILE).write_text("# S\n- 📌 停止点: 節 C\n- 図: 済み (検収も)\n", encoding="utf-8")
        expect("未 commit の現在地の変更も数える", state_changes_since(repo, "2099-01-05T00:00:00Z"), ["worktree"])
        git("checkout", "-q", "--", SESSION_FILE)
        late = dict(sub, created_at="2099-01-05T00:00:00Z")
        expect("提出の後に変更が無ければ 1 件", len(gaps([req, late, acc], ws)), 1)
        skip = {"kind": "note", "request_id": "R1", "created_at": "2099-01-05T02:00:00Z",
                "summary": NOTE_PREFIX + "skip 停止点は前の版のまま正しい"}
        expect("skip の note (理由つき) で通す", gaps([req, late, acc, skip], ws), [])
        expect("理由の短い skip は通さない", len(gaps([req, late, acc, dict(skip, summary=NOTE_PREFIX + "skip")], ws)), 1)
        head = git("rev-parse", "--short", "HEAD").stdout.strip()
        cnote = dict(skip, summary=NOTE_PREFIX + "proj@" + head)
        expect("commit を名指す note (repo に在る) で通す", gaps([req, late, acc, cnote], ws), [])
        expect("在らない commit の note は通さない", len(gaps([req, late, acc, dict(skip, summary=NOTE_PREFIX + "proj@deadbee")], ws)), 1)
        expect("提出の無い依頼は見ない", gaps([req], ws), [])
        expect("project の dir が無い依頼は見ない", gaps([dict(req, project={"key": "nope"}), late], ws), [])
    print("dialogue_record selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv[1:] else 0)
