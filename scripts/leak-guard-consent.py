#!/usr/bin/env python3
"""公開 repo の漏洩検査 (public-precommit-runner.sh) が止めた文字列に本人の承認を付け、 その repo でだけ通す。

なぜ (実測): 本人が公開サイトに載せると決めたリンクを検査が止めた。 検査の案内は「`--no-verify` で検査を全部外す」
だけで、 agent 側の守り (escape-hatch-guard / manuscript-claim-guard) は全部を外す操作を止める = 本人が許可しても
通る道が無かった (本人「本人が許可してんのになんで勝手に止めてんの？通す道もなしで。」)。
直し方: 検査が止めた文字列を控え、 本人の発言そのもの (会話記録と照合) を承認として記録すると、 その文字列だけを
その repo でだけ通す。 通すのは Tier B (個人層の語の一覧の語) と Tier C (非公開 repo の名前) の 2 段だけ。
メール・path・IP・token (Tier A) と、 未公開文書の逐語・活動の事実ほか (Tier D 以降) は承認で外さない。

形:
    note-block  runner が止めたときに呼ぶ。 止めた Tier B の語と Tier C の repo 名を、 この機械の控え
                (`~/.claude/state/leak-guard-blocked/<repo の key>.json`、 機械ごと = 公開しない) に書く
    allowed     runner が照合の前に呼ぶ。 この repo で承認済みの文字列を 1 行ずつ出す (`--tier terms|repo-name`)
    record      本人の発言で、 この repo で最後に止めた文字列を承認として記録する (`--quote '<本人の発言>'` か `--latest`)
    list        承認の一覧
    --selftest  合成の語だけで一連を確かめる (実の語の一覧を読まない)

承認の記録 = `<個人層>/leak-guard-consents.jsonl` (1 行 1 件 = repo の key・段・文字列・本人の発言・その発言の時刻・
session・記録の時刻)。 個人層は git で同期する = 記録して push すれば、 どの機械の commit (無人の定期 job も) も読む。
repo の key = origin の URL の `<owner>/<name>` (無ければ repo の dir の名前) = 機械が違っても同じ。

本人の発言の照合は原稿の守り (`manuscript-claim-guard.py`) の部品を使う: この session の会話記録の、 人が書いた
発言だけを読み、 `--quote` が verbatim で在ること (短い引用は発言の全体と一致すること) を確かめる。 agent の要約・
言い換えは承認にならない。 照合できない (session が分からない・会話記録が無い) なら記録しない。
人が端末から承認するときは、 runner の案内どおり人が自分で `git commit --no-verify` を打つ (この道具は agent の
session からの記録だけを受け付ける)。

使い方:
    python3 leak-guard-consent.py record --repo <repo> --quote '<本人の発言>'   # 最後に止めた文字列を承認する
    python3 leak-guard-consent.py record --repo <repo> --latest                 # 本人の最新の発言で
    python3 leak-guard-consent.py list [--repo <repo>]
    python3 leak-guard-consent.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONSENT_FILE = "leak-guard-consents.jsonl"
TIERS = ("terms", "repo-name")
SCRIPTS = Path(__file__).resolve().parent


def state_dir() -> Path:
    return Path(os.environ.get("LEAK_GUARD_STATE_DIR") or (Path.home() / ".claude" / "state" / "leak-guard-blocked"))


def personal_layer(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    r = subprocess.run(["bash", "-c", f'. "{SCRIPTS}/lib/find-personal-layer.sh" && find_personal_layer'],
                       capture_output=True, text=True)
    p = r.stdout.strip()
    return Path(p) if r.returncode == 0 and p else None


def repo_key(repo: Path) -> str:
    """origin の URL の <owner>/<name>。 無ければ dir の名前 (機械が違っても同じ値にする)。"""
    r = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True)
    url = r.stdout.strip() if r.returncode == 0 else ""
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else repo.resolve().name


def load_consents(layer: Path | None) -> list[dict]:
    p = layer / CONSENT_FILE if layer else None
    if not p or not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def allowed(layer: Path | None, key: str, tier: str) -> list[str]:
    seen, out = set(), []
    for c in load_consents(layer):
        if c.get("repo") == key and c.get("tier") == tier and c.get("string") and c["string"] not in seen:
            seen.add(c["string"])
            out.append(c["string"])
    return out


def read_lines(path: str | None) -> list[str]:
    if not path or not Path(path).is_file():
        return []
    return [x for x in Path(path).read_text(encoding="utf-8").splitlines() if x]


def blocked_terms(added_text: str, ascii_terms: list[str], na_terms: list[str], allow: list[str]) -> list[str]:
    """runner の Tier B と同じ照合 (許可した複合語を消してから、 ASCII = 単語境界 / 非 ASCII = 部分一致)。"""
    for w in allow:
        added_text = added_text.replace(w, " ")
    hits = [t for t in ascii_terms if re.search(rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])", added_text)]
    hits += [t for t in na_terms if t in added_text]
    return hits


def repo_names_from_hits(hits_text: str) -> list[str]:
    """matcher の `[repo-name] a b ` の行から名前を出す (path の段 = [repo-path]/[claude-path] は承認の外)。"""
    out = []
    for line in hits_text.splitlines():
        m = re.match(r"\s*\[repo-name\]\s*(.*)$", line)
        if m:
            out += [x for x in m.group(1).split() if x]
    return out


def note_block(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    added = "\n".join(x.split("\t", 1)[-1] for x in read_lines(a.added))
    terms = blocked_terms(added, read_lines(a.ascii), read_lines(a.na), read_lines(a.allow))
    names = repo_names_from_hits(a.repo_hits or "")
    if not terms and not names:
        return 0
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    key = repo_key(repo)
    (d / (key.replace("/", "__") + ".json")).write_text(json.dumps(
        {"repo": key, "path": str(repo.resolve()), "at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
         "terms": terms, "repo_names": names}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def load_mcg():
    spec = importlib.util.spec_from_file_location("manuscript_claim_guard", SCRIPTS / "manuscript-claim-guard.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def owner_said(quote: str | None, latest: bool, session: str | None, transcript: str | None, mcg=None):
    """(発言の時刻, 発言の全文, その後の本人の発言の数) か、 照合できない理由 (str)。"""
    mcg = mcg or load_mcg()
    sess = mcg.parse_session(session) if session else mcg.session_from_env()
    if sess is None:
        return "agent の session が分からない (--session <agent>:<id>)。 人が端末から承認するなら、 人が自分で git commit --no-verify を打つ"
    path = Path(transcript) if transcript else mcg.find_transcript(sess[0], sess[1])
    if path is None or not Path(path).is_file():
        return f"session {sess[0]}:{sess[1]} の会話記録が見つからない = 本人の発言を照合できない"
    msgs = mcg.user_messages(Path(path), {}, choice_answers=True)
    if not msgs:
        return "この session に本人の発言が無い"
    if latest:
        idx = len(msgs) - 1
        if not msgs[idx][1].strip():
            return "本人の最新の入力に引ける文が無い (選択肢やボタンだけの答え) = 承認の文を本人に 1 行打ってもらってから引く"
    else:
        q = mcg.collapse_ws(quote or "")
        idx = mcg.quote_index(quote or "", msgs)
        if idx is not None and len(q.strip(mcg.EDGE_PUNCT)) < mcg.SHORT_QUOTE and q != mcg.collapse_ws(msgs[idx][1]):
            idx = None   # 短い引用は発言の全体と一致する時だけ (「OK」 が「OK じゃない」 に当たらないように)
        if idx is None:
            return "--quote が、 この session の本人の発言に verbatim で見つからない (要約・言い換えは承認にならない)"
    return msgs[idx][0], msgs[idx][1], len(msgs) - 1 - idx


def record(a: argparse.Namespace, mcg=None) -> int:
    if bool(a.quote) == bool(a.latest):
        print("record: --quote '<本人の発言>' か --latest のどちらか 1 つ", file=sys.stderr)
        return 2
    repo = Path(a.repo)
    key = repo_key(repo)
    sp = state_dir() / (key.replace("/", "__") + ".json")
    if not sp.is_file():
        print(f"record: {key} で検査が止めた記録がこの機械に無い = 何を承認するか分からない。 この機械で同じ commit を"
              f"作り直して検査に止めさせてから記録する", file=sys.stderr)
        return 3
    blocked = json.loads(sp.read_text(encoding="utf-8"))
    said = owner_said(a.quote, a.latest, a.session, a.transcript, mcg)
    if isinstance(said, str):
        print(f"record: {said}。 記録しない。", file=sys.stderr)
        return 4
    at, text, after = said
    layer = personal_layer(a.layer)
    if layer is None:
        print("record: 個人層が見つからない = 記録の置き場所が無い。", file=sys.stderr)
        return 3
    have = {(c.get("tier"), c.get("string")) for c in load_consents(layer) if c.get("repo") == key}
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    sess = a.session or "%s:%s" % ((mcg or load_mcg()).session_from_env() or ("?", "?"))
    new = [("terms", t) for t in blocked.get("terms", [])] + [("repo-name", n) for n in blocked.get("repo_names", [])]
    new = [x for x in new if x not in have]
    with (layer / CONSENT_FILE).open("a", encoding="utf-8") as f:
        for tier, s in new:
            f.write(json.dumps({"repo": key, "tier": tier, "string": s, "quote": text, "said_at": at, "session": sess,
                                "recorded": now}, ensure_ascii=False) + "\n")
    sp.unlink()
    print(f"{key}: {len(new)} 件を承認として記録した (Tier B の語 {sum(1 for t, _ in new if t == 'terms')}・"
          f"repo 名 {sum(1 for t, _ in new if t == 'repo-name')}、 本人の発言 {at or '時刻不明'}"
          + (f"、 その後に本人が {after} 回発言" if after else "") + f")。 記録 = {layer / CONSENT_FILE}。"
          " 個人層を commit + push すると、 ほかの機械の commit もこの承認を読む")
    return 0


def list_consents(a: argparse.Namespace) -> int:
    layer = personal_layer(a.layer)
    key = repo_key(Path(a.repo)) if a.repo else None
    rows = [c for c in load_consents(layer) if key is None or c.get("repo") == key]
    for c in rows:
        print(f"{c.get('repo')}  {c.get('tier')}  {c.get('said_at') or ''}  「{c.get('quote', '')[:60]}」")
    if not rows:
        print("承認は無い")
    return 0


def selftest() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        os.environ["LEAK_GUARD_STATE_DIR"] = str(d / "state")
        layer = d / "layer"
        layer.mkdir()
        repo = d / "pubrepo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@example.invalid:mockowner/mocksite.git"],
                       check=True)
        if repo_key(repo) != "mockowner/mocksite":
            fails.append(f"repo の key: {repo_key(repo)}")
        if blocked_terms("a MOCKTERM b モック語c", ["MOCKTERM", "NX"], ["モック語"], []) != ["MOCKTERM", "モック語"]:
            fails.append("Tier B の照合")
        if blocked_terms("NXYZ", ["NX"], [], []):
            fails.append("ASCII の単語境界")
        if blocked_terms("モック語の会", [], ["モック語"], ["モック語の会"]):
            fails.append("許可した複合語")
        if repo_names_from_hits("  [repo-name] mockpriv-a mockpriv-b \n  [claude-path] x") != ["mockpriv-a", "mockpriv-b"]:
            fails.append("repo 名の取り出し")
        added = d / "added.tsv"
        added.write_text("f.txt\tモック語と mockpriv-a\n", encoding="utf-8")
        na = d / "na.txt"
        na.write_text("モック語\n", encoding="utf-8")
        note_block(argparse.Namespace(repo=str(repo), added=str(added), ascii=None, na=str(na), allow=None,
                                      repo_hits="  [repo-name] mockpriv-a "))

        class FakeMcg:   # 会話記録の代わり (本人の発言 2 つ)
            EDGE_PUNCT, SHORT_QUOTE = " 。、", 12
            collapse_ws = staticmethod(lambda s: " ".join(s.split()))
            parse_session = staticmethod(lambda s: tuple(s.split(":", 1)))
            session_from_env = staticmethod(lambda: ("claude", "test"))
            find_transcript = staticmethod(lambda a, b: added)
            user_messages = staticmethod(lambda p, e, choice_answers=False: [("t1", "リンクも載せる。検査を直して"), ("t2", "OK")])

            @staticmethod
            def quote_index(q, msgs):
                for i in range(len(msgs) - 1, -1, -1):
                    if " ".join(q.split()) in " ".join(msgs[i][1].split()):
                        return i
                return None
        base = dict(repo=str(repo), layer=str(layer), session="claude:test", transcript=None)
        if record(argparse.Namespace(quote="勝手な要約", latest=False, **base), FakeMcg) != 4:
            fails.append("本人の発言に無い引用を記録した")
        if record(argparse.Namespace(quote="OK じゃない", latest=False, **base), FakeMcg) != 4:
            fails.append("無い引用 (部分) を記録した")
        if record(argparse.Namespace(quote="リンクも載せる。検査を直して", latest=False, **base), FakeMcg) != 0:
            fails.append("本人の発言の引用で記録できない")
        if allowed(layer, "mockowner/mocksite", "terms") != ["モック語"] or \
                allowed(layer, "mockowner/mocksite", "repo-name") != ["mockpriv-a"]:
            fails.append(f"承認の読み出し: {load_consents(layer)}")
        if allowed(layer, "mockowner/other", "terms"):
            fails.append("別の repo に承認が効いた")
        if record(argparse.Namespace(quote="リンクも載せる。検査を直して", latest=False, **base), FakeMcg) != 3:
            fails.append("止めた記録が無いのに記録した")
    for f in fails:
        print("❌", f)
    print("✅ selftest PASS (照合・単語境界・許可した複合語・repo 名・本人の発言の照合・repo ごとの承認)" if not fails
          else f"❌ selftest FAIL {len(fails)}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", choices=("note-block", "allowed", "record", "list"))
    ap.add_argument("--repo")
    ap.add_argument("--layer", help="個人層 (既定 = lib/find-personal-layer.sh で探す)")
    ap.add_argument("--tier", choices=TIERS)
    ap.add_argument("--added")
    ap.add_argument("--ascii")
    ap.add_argument("--na")
    ap.add_argument("--allow")
    ap.add_argument("--repo-hits")
    ap.add_argument("--quote")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--session")
    ap.add_argument("--transcript")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.cmd in ("note-block", "allowed", "record") and not a.repo:
        ap.error("--repo が要る")
    if a.cmd == "note-block":
        return note_block(a)
    if a.cmd == "allowed":
        if not a.tier:
            ap.error("--tier が要る")
        for s in allowed(personal_layer(a.layer), repo_key(Path(a.repo)), a.tier):
            print(s)
        return 0
    if a.cmd == "record":
        return record(a)
    if a.cmd == "list":
        return list_consents(a)
    ap.error("note-block / allowed / record / list / --selftest のどれか")
    return 2


if __name__ == "__main__":
    sys.exit(main())
