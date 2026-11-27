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

途中で記録したかの部品 (multi-session-coordination.md#dialogue-record-split の「研究者の発言は締めを待たず、 指揮所が受けた turn に
書く」 を、 締めの網より前に見る。 使い手 = 個人層の指揮所の Stop の網):
  owner_quotes = 対話係の便の「」 の中の文のうち、 空白を除いて 8 字以上で、 同じ窓の研究者の発言の一部であるもの。
    研究の判断か作業の指示かは文から決めない (決められない) = 使い手は止めずに知らせる。
  quote_in_repo = その逐語が project の repo に入っているか (作業 tree の全体に文のまま、 または便の後に変わった file の中に
    空白を詰めた形 = 改行で折った写しも数える。 言い換えは数えない)。
  midway_cover = その依頼への note のうち `midway-record: <理由 4 字以上>` か、 record_note が数える `dialogue-record: ` の形の、
    いちばん新しい時刻 = それより前の便の逐語では知らせない。
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


# ---- 途中で記録したか (上の docstring の「途中で記録したかの部品」)
QUOTE = re.compile(r"「([^「」]{2,400})」")
MIDWAY_PREFIX = "midway-record: "
MIN_QUOTE_CHARS = 8
_SPACE = re.compile(r"\s+")


def squash(s):
    return _SPACE.sub("", s or "")


def owner_quotes(text, owner_heads, min_chars=MIN_QUOTE_CHARS):
    """便の文の「」 の中の文のうち、 空白を除いて min_chars 字以上で、 owner_heads (同じ窓の研究者の発言) のどれかの
    一部であるもの (空白を詰めて比べる。 同じ文は 1 回)。"""
    heads = [squash(h) for h in owner_heads if h]
    out, seen = [], set()
    for q in QUOTE.findall(text or ""):
        s = squash(q)
        if len(s) < min_chars or s in seen or not any(s in h for h in heads):
            continue
        seen.add(s)
        out.append(q)
    return out


def _base_commit(repo, since_iso):
    out = _git(["rev-list", "-1", "--before=" + since_iso, "HEAD"], repo)
    return out.strip() if out else ""


def quote_in_repo(repo, quote, since_iso, max_files=400, max_bytes=2_000_000):
    """逐語が project の repo に入っていれば True。 (1) 作業 tree の全体 (未追跡も) に文のまま在る (git grep -F、 1 行の逐語だけ)
    か、 (2) since より後に変わった file (commit・未 commit・未追跡) の中に空白を詰めた形で在る (改行で折った写し)。
    git が読めなければ True (= 知らせない側に倒す。 使い手は止めない網なので、 読めない repo で鳴り続けない)。"""
    repo = Path(repo)
    if _git(["rev-parse", "--git-dir"], repo) is None:
        return True
    one = quote.strip()
    if one and "\n" not in one and _git(["grep", "-qF", "--untracked", "-e", one], repo) is not None:
        return True
    want = squash(quote)
    base = _base_commit(repo, since_iso)
    names = (_git(["diff", "--name-only", base], repo) if base else _git(["ls-files"], repo)) or ""
    names += "\n" + (_git(["ls-files", "--others", "--exclude-standard"], repo) or "")
    seen = set()
    for n in names.splitlines():
        n = n.strip()
        if not n or n in seen:
            continue
        seen.add(n)
        if len(seen) > max_files:
            break
        f = repo / n
        try:
            if not f.is_file() or f.stat().st_size > max_bytes:
                continue
            if want in squash(f.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def midway_cover(events, request_id, workspace=None):
    """その依頼への逃げ道の note のうち、 いちばん新しいものの created_at (無ければ '')。 数える note =
    `midway-record: <理由 4 字以上>` か、 record_note が数える `dialogue-record: ` の形 (skip <理由> / <repo>@<commit>)。"""
    best = ""
    for e in events:
        if e.get("kind") != "note" or e.get("request_id") != request_id:
            continue
        s, at = str(e.get("summary") or ""), str(e.get("created_at") or "")
        ok = False
        if s.startswith(MIDWAY_PREFIX):
            ok = len(s[len(MIDWAY_PREFIX):].strip()) >= 4
        elif s.startswith(NOTE_PREFIX):
            ok = record_note([e], request_id, workspace)[0] is not None
        if ok and at > best:
            best = at
    return best


def midway_line(items, window_min, rule="multi-session-coordination.md#dialogue-record-split", heads_max=3):
    """知らせの 1 行。 items = [dict(request, project, quote)] (古い順)。 頭の heads_max 件の逐語の頭と残りの件数を言う
    (まとめた知らせで、 作業の指示の後ろに研究の判断が隠れないように 1 件だけにしない)。"""
    if not items:
        return ""
    first = items[0]
    heads = []
    for it in items[:heads_max]:
        h = _SPACE.sub(" ", it["quote"]).strip()
        heads.append("「%s」" % (h if len(h) <= 18 else h[:18] + "…"))
    more = "" if len(items) <= heads_max else " (ほか %d 件)" % (len(items) - heads_max)
    reqs = sorted({it["request"] for it in items})
    return ("📝 研究の対話係の便 (依頼 %s) にある研究者の発言の逐語 %s%s が、 %d 分たっても %s の repo に入っていない"
            " = 研究の判断 (用語・主結果・構成・方針) なら共有の記録 (SESSION の現在地か裁定の台帳) に逐語で写す、"
            " 書き方・作業の指示なら写さずに続けてよい (写さない理由を残すなら、 その依頼に note `%s<理由>`)。 規則 = %s"
            % (", ".join(reqs), " ".join(heads), more, window_min, first["project"], MIDWAY_PREFIX, rule))


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
        # ---- 途中で記録したか (合成の文。 中身は家事の頼み = どの研究の議論とも無関係)
        heads = ["棚の上の箱は、 左から順に大きさで並べ直しておいて。 急がない。", "窓を閉めて"]
        msg = ("相手の言葉どおり「棚の上の箱は、左から順に大きさで並べ直しておいて」 とのこと。"
               " 短い「窓を閉めて」 と、 相手の言葉でない「床を拭いてから乾かす」 もある。")
        got = owner_quotes(msg, heads)
        expect("逐語 = 研究者の発言の一部で 8 字以上 (空白を詰めて比べる)",
               [squash(q) for q in got], ["棚の上の箱は、左から順に大きさで並べ直しておいて"])
        expect("同じ逐語は 1 回", len(owner_quotes(msg + msg, heads)), 1)
        q = got[0]
        expect("repo に無い逐語 = False", quote_in_repo(repo, q, "2099-01-05T00:00:00Z"), False)
        (repo / "notes.md").write_text("- 記録: 棚の上の箱は、 左から順に\n  大きさで並べ直しておいて (相手の言葉)\n", encoding="utf-8")
        expect("便の後に足した未追跡の file に、 改行で折った写しが在る = True",
               quote_in_repo(repo, q, "2099-01-05T00:00:00Z"), True)
        git("add", "notes.md")
        git("commit", "-q", "-m", "n", date="2099-01-06T00:00:00Z")
        expect("commit した後も True", quote_in_repo(repo, q, "2099-01-05T00:00:00Z"), True)
        (repo / "notes.md").write_text("- 記録: 別のこと\n", encoding="utf-8")
        git("commit", "-q", "-am", "n2", date="2099-01-07T00:00:00Z")
        expect("写しを消した後は False", quote_in_repo(repo, q, "2099-01-05T00:00:00Z"), False)
        (repo / "one.md").write_text("棚の上の箱は、左から順に大きさで並べ直しておいて\n", encoding="utf-8")
        git("add", "one.md")
        git("commit", "-q", "-m", "o", date="2099-01-01T12:00:00Z")
        expect("便より前から在る 1 行の逐語も True (git grep)", quote_in_repo(repo, q, "2099-01-05T00:00:00Z"), True)
        expect("git の読めない dir は True (知らせない側)", quote_in_repo(ws / "nope", q, "2099-01-05T00:00:00Z"), True)
        mnote = {"kind": "note", "request_id": "R1", "created_at": "2099-01-05T03:00:00Z", "summary": MIDWAY_PREFIX + "作業の指示で記録は要らない"}
        expect("midway-record の note (理由つき) の時刻", midway_cover([req, mnote], "R1"), "2099-01-05T03:00:00Z")
        expect("理由の短い midway-record は数えない", midway_cover([req, dict(mnote, summary=MIDWAY_PREFIX + "x")], "R1"), "")
        expect("dialogue-record: skip の note も数え、 新しい方を返す",
               midway_cover([req, mnote, skip], "R1"), "2099-01-05T03:00:00Z")
        expect("ほかの依頼の note は数えない", midway_cover([dict(mnote, request_id="R9")], "R1"), "")
        many = [dict(request="R1", project="proj", quote=q)] + [dict(request="R1", project="proj", quote="短い%d" % i) for i in range(3)]
        line = midway_line(many, 30)
        expect("知らせの 1 行 = 逐語の頭 3 件・残りの件数・分・project・逃げ道の note を言う",
               all(w in line for w in ("「棚の上の箱は、左から順に大きさで並", "「短い1」", "ほか 1 件", "30 分", "proj の repo",
                                       MIDWAY_PREFIX)) and "短い2" not in line and "\n" not in line, True)
        expect("3 件以下なら「ほか」 を言わない", "ほか" in midway_line(many[:3], 30), False)
        expect("項目が無ければ空", midway_line([], 30), "")
    print("dialogue_record selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv[1:] else 0)
