#!/usr/bin/env python3
"""check-ci-red.py — GitHub Actions の red 検出器（repo 横断で「default branch の最新 completed run が失敗中の workflow」 を列挙し、 連続失敗 run 数・継続時間・最後の success を印字、 長期 red を 🚨 で強調。 取得失敗は「検査不能」 行で明示 = 黙って緑にしない、 finding 0 件 silent、 --as-of で過去時点を再現、 --selftest 内蔵。 呼び出し側 = 個人層 dashboard / session 開始 hook）

背景 (= 汎用化した事故形): CI の結果は push した人の画面にしか出ない。 push を多数の
session や無人 job が打つ運用では、 red が「誰かが見るだろう」 のまま何日も続く
(実例: ある public repo の検査 workflow が、 BSD 専用コマンド 1 行のせいで 10 日・225 push
連続 red だったのに誰も気付かなかった)。 本 script は「今 red の workflow」 を呼び出し側に
届ける engine。 何を対象 repo とするか (= repo 一覧の正本) は呼び出し側が決める。
red を見つけた後の原因追跡 (streak の起点・最初の失敗行・導入 commit の pickaxe) は
scripts/ci-red-streak.py (red / green の述語は同じ)。 手順 = conventions/debugging-discipline.md#ci-red-streak-forensics。

述語 (= code-as-SoT、 変更時はここが正):
  - 対象 workflow = state が active のもの (disabled は走らないので対象外)
  - 対象 run = default branch の completed run のうち、 event が pull_request 系でないもの
  - 判定に使う conclusion: red = failure / timed_out / startup_failure、 green = success。
    それ以外 (cancelled / skipped / neutral / stale / action_required) は読み飛ばす
    (= 並行 push の打ち切りや path filter の skip に red / green を上書きさせない)
  - red = 判定に使う最新 run が red。 streak = そこから遡って連続する red の本数、
    継続時間 = 最初の red run の作成時刻から現在 (--as-of 指定時はその時刻) まで
  - 🚨 長期 = 継続 LONG_HOURS 時間以上 または LONG_RUNS run 以上
    (= 「push した本人が直すだろう」 の窓を越えた red)
  - 遡りの上限 = MAX_PAGES × PAGE run。 上限まで red なら run 数に「+」 を付ける

取得失敗の扱い: repo / workflow 一覧 / run 一覧のどれかの API が失敗したら、 その repo を
  「検査不能」 として最後に 1 行にまとめる (= 「動いて 0 件」 と「動かなかった」 を区別する。
  docs/convention-design-principles.md#silent-probe-false-healthy)。 gh 自体が使えない
  (未認証 / network) ときは repo ごとに並べず 1 行で言う。
cache は持たない (= 毎回取りに行く。 鮮度が価値の検出器 =
  conventions/debugging-discipline.md#run-scoped-cache)。

対象 repo の与え方 (複数併用可、 重複は除去):
  --repo OWNER/NAME          繰り返し可
  --repos-file PATH|-        1 行 1 repo、 # 以降は comment
  --owner OWNER              gh repo list OWNER --no-archived で列挙
  どれも無ければ認証 user 自身の repo (gh repo list、 archived 除外)
  --note-unprobed NAME=理由   呼び出し側で名前解決できなかった repo を検査不能行に合流させる

出力: red も検査不能も無ければ無出力。 exit 0 (fail-open)。 --strict なら red または
  検査不能があるとき exit 1。 Dependabot 枠は --dependabot detail (repo 別の行、 既定) /
  summary (1 行 = repo 数と ecosystem 別の数。 毎 session 出る面向け) / off。
過去時点の再現: --as-of 2026-09-01T05:00:00Z → その時刻までに完了した run だけで判定
  (= 検出器が当時あったら何を出したかの backtest。 workflow の active/disabled、 repo の
  archived、 Dependabot alert の open/closed は現在の値を使う = 過去の state は API で引けない)。
依存: gh CLI (認証済)。 API call 数 ≈ repo 数 × 2 + active workflow 数 (+ 長い red の遡り)。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

RED = frozenset({"failure", "timed_out", "startup_failure"})
GREEN = frozenset({"success"})
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
# Dependabot Updates (GitHub 管理の dynamic workflow) は 1 workflow に ecosystem ごとの
# update job が相乗りする (display_title = "<ecosystem> in <dir> - Update #N")。 job ごとに
# success / failure が交互に並ぶので workflow 単位の streak は意味を持たない → 別枠で job 単位に
# 最新 run を読む (= CI red ではなく「依存更新が止まっている」 signal として出す)。
DEPENDABOT_PREFIX = "dynamic/dependabot/"
DEPENDABOT_CFG = ".github/dependabot.yml"
_DEP_TITLE_RE = re.compile(r"^(.*?) - Update #\d+$")
# job の最新 run が workflow の最新 run よりこれ以上古ければ、 config から消えた job とみなす
# (= monthly 間隔までは cover。 quarterly 等の長い間隔を他と混ぜた job は run の合間に消える)
STALE_JOB_DAYS = 40

FIRST_PAGE = 20   # 大半の workflow はここで green に届く
PAGE = 100        # streak が FIRST_PAGE を越えたときの遡り単位
MAX_PAGES = 10    # 遡り上限 = 1000 run (API の filter 付き一覧も 1000 件が上限)
LONG_HOURS = 24
LONG_RUNS = 10
WORKERS = 16
API_TIMEOUT = 20
DISPLAY_TZ = None  # None = system local。 selftest は UTC に固定する

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def gh_api(path: str):
    """gh api を叩いて (data, None) か (None, 理由) を返す。 理由 = gh の stderr 最終行。"""
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                           timeout=API_TIMEOUT)
    except FileNotFoundError:
        return None, "gh CLI 不在"
    except subprocess.TimeoutExpired:
        return None, f"{API_TIMEOUT}s timeout"
    if r.returncode != 0:
        lines = [l.strip() for l in (r.stderr or "").splitlines() if l.strip()]
        msg = lines[-1] if lines else f"gh rc={r.returncode}"
        if msg.startswith("gh: "):
            msg = msg[4:]
        return None, msg[:80]
    try:
        return (json.loads(r.stdout) if r.stdout.strip() else None), None
    except json.JSONDecodeError:
        return None, "JSON 解釈不能"


def gh_repo_list(owner: str | None):
    """gh repo list [OWNER] --no-archived → ([owner/name], None) か (None, 理由)。"""
    cmd = ["gh", "repo", "list"] + ([owner] if owner else []) + [
        "--no-archived", "--limit", "1000", "--json", "nameWithOwner"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=API_TIMEOUT * 2)
    except FileNotFoundError:
        return None, "gh CLI 不在"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if r.returncode != 0:
        lines = [l.strip() for l in (r.stderr or "").splitlines() if l.strip()]
        return None, (lines[-1] if lines else f"gh rc={r.returncode}")[:80]
    try:
        return [x["nameWithOwner"] for x in json.loads(r.stdout)], None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, "JSON 解釈不能"


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_as_of(s: str) -> datetime:
    """ISO 8601 (Z 可、 日付だけ可)。 timezone 無しは UTC とみなす。"""
    dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_repo_lines(text: str):
    """1 行 1 repo。 → ([owner/name], [(行, 理由)])"""
    ok, bad = [], []
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        (ok if _REPO_RE.match(s) else bad).append(s)
    return ok, [(b, "形式不正 (OWNER/NAME でない)") for b in bad]


def usable_runs(runs, as_of=None):
    """completed ∧ 非 PR event ∧ (as_of 以前に完了) の run だけ残す。 順序 (= 新しい順) は保持。"""
    out = []
    for r in runs:
        if r.get("status", "completed") != "completed":
            continue
        if r.get("event") in PR_EVENTS:
            continue
        if as_of is not None:
            t = r.get("updated_at") or r.get("created_at")
            if t and parse_ts(t) > as_of:
                continue
        out.append(r)
    return out


def walk(runs):
    """新しい順の run 列から streak を読む (純関数)。

    return dict(state='red'|'green'|'none', n_red, first_red, latest_red, last_green)
      first_red = streak の最古の red run / latest_red = 最新の red run /
      last_green = streak の直前にある success (見つからなければ None)
    """
    n, first, latest, green = 0, None, None, None
    for r in runs:
        c = r.get("conclusion")
        if c in RED:
            n += 1
            if latest is None:
                latest = r
            first = r
        elif c in GREEN:
            green = r
            break
        # それ以外の conclusion は読み飛ばす (docstring の述語)
    state = "red" if latest is not None else ("green" if green is not None else "none")
    return {"state": state, "n_red": n, "first_red": first,
            "latest_red": latest, "last_green": green}


def runs_path(repo, wf_id, branch, per_page, page, as_of):
    q = (f"repos/{repo}/actions/workflows/{wf_id}/runs?branch={quote(branch, safe='')}"
         f"&status=completed&exclude_pull_requests=true&per_page={per_page}&page={page}")
    if as_of is not None:
        stamp = as_of.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        q += "&created=" + quote("<=" + stamp, safe="")
    return q


def workflow_streak(repo, wf, branch, as_of):
    """1 workflow の streak → (dict, None) か (None, 理由)。 dict には capped を足す。"""
    data, err = gh_api(runs_path(repo, wf["id"], branch, FIRST_PAGE, 1, as_of))
    if err:
        return None, err
    raw = (data or {}).get("workflow_runs") or []
    st = walk(usable_runs(raw, as_of))
    st["capped"] = False
    if st["state"] != "red" or st["last_green"] is not None or len(raw) < FIRST_PAGE:
        return st, None
    # streak が最初の page を越えている → PAGE 件単位で green まで遡り直す
    allruns = []
    for page in range(1, MAX_PAGES + 1):
        data, err = gh_api(runs_path(repo, wf["id"], branch, PAGE, page, as_of))
        if err:
            return None, err
        raw = (data or {}).get("workflow_runs") or []
        allruns.extend(raw)
        st = walk(usable_runs(allruns, as_of))
        st["capped"] = False
        if st["last_green"] is not None or len(raw) < PAGE:
            return st, None
    st["capped"] = True
    return st, None


def is_dependabot(wf) -> bool:
    return (wf.get("path") or "").startswith(DEPENDABOT_PREFIX)


def dependabot_failures(repo, wf, branch, as_of):
    """Dependabot Updates の job (ecosystem × dir) ごとに最新 decisive run を読む
    → ([(job, 最新の失敗 run)], None) か (None, 理由)。 読むのは最初の page だけ
    (= job 単位の streak 長は数えない)。 config から消えた job の古い失敗は page 内に残り
    うるので、 次のどちらかに当たる job は出さない:
      - 最新 run が workflow の最新 run より STALE_JOB_DAYS 以上古い
      - version update の job (= title に " for <pkg>" が無い) で、 最新 run が dependabot.yml の
        最終 commit より前 (= config を直した後に一度も走っていない。 Dependabot は config の push
        直後に version update の全 job を走らせるので、 残っている job なら新しい run がある)。
        security update の job ("... for <pkg>") は alert 起点で走り config の push では走り直さない
        ので、 この間引きの対象外。 commit 時刻が取れなければ間引かない (= 隠す側に倒さない)
      - security update の job で、 repo に open な Dependabot alert が 1 件も無い (= 直す対象が
        既に無い。 alert API が失敗したら間引かない)"""
    data, err = gh_api(runs_path(repo, wf["id"], branch, FIRST_PAGE, 1, as_of))
    if err:
        return None, err
    usable = usable_runs((data or {}).get("workflow_runs") or [], as_of)
    if not usable:
        return [], None
    newest = max(parse_ts(r["created_at"]) for r in usable)
    groups = {}
    for r in usable:
        t = r.get("display_title") or ""
        m = _DEP_TITLE_RE.match(t)
        groups.setdefault(m.group(1) if m else t, []).append(r)
    out = []
    for job, runs in sorted(groups.items()):
        st = walk(runs)
        if st["state"] != "red":
            continue
        last = parse_ts(runs[0]["created_at"])
        if newest - last > timedelta(days=STALE_JOB_DAYS):
            continue  # config から消えた job の古い失敗
        out.append((job, st["latest_red"], last))
    if out:
        changed = config_changed_at(repo, branch, as_of)
        if changed is not None:
            out = [x for x in out if " for " in x[0] or x[2] >= changed]
    if any(" for " in x[0] for x in out):
        alerts, err = gh_api(f"repos/{repo}/dependabot/alerts?state=open&per_page=1")
        if not err and alerts == []:
            out = [x for x in out if " for " not in x[0]]  # open alert が無い = 直す対象が無い
    return [(job, run) for job, run, _ in out], None


def config_changed_at(repo, branch, as_of):
    """dependabot.yml の最終 commit 時刻。 取れなければ None (= 呼び出し側は間引かない)。"""
    q = (f"repos/{repo}/commits?path={quote(DEPENDABOT_CFG, safe='/')}"
         f"&sha={quote(branch, safe='')}&per_page=1")
    if as_of is not None:
        q += "&until=" + quote(as_of.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               safe="")
    data, err = gh_api(q)
    if err or not data:
        return None
    try:
        return parse_ts(data[0]["commit"]["committer"]["date"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def check_repo(repo, as_of=None):
    """→ (CI red の list, Dependabot job 失敗の list, 検査不能の理由 or None)。
    archived は対象外 (silent)。"""
    info, err = gh_api(f"repos/{repo}")
    if err:
        return [], [], f"repo 情報: {err}"
    if not isinstance(info, dict):
        return [], [], "repo 情報: 空応答"
    if info.get("archived"):
        return [], [], None
    branch = info.get("default_branch") or "main"
    wfs, err = gh_api(f"repos/{repo}/actions/workflows?per_page=100")
    if err:
        return [], [], f"workflow 一覧: {err}"
    reds, deps, fails = [], [], []
    for wf in (wfs or {}).get("workflows") or []:
        if wf.get("state") != "active":
            continue
        if is_dependabot(wf):
            jobs, err = dependabot_failures(repo, wf, branch, as_of)
            if err:
                fails.append(f"{wf.get('name') or wf.get('path')}: {err}")
            elif jobs:
                deps.append({"repo": repo, "jobs": jobs})
            continue
        st, err = workflow_streak(repo, wf, branch, as_of)
        if err:
            fails.append(f"{wf.get('name') or wf.get('path')}: {err}")
            continue
        if st["state"] == "red":
            reds.append(dict(st, repo=repo, workflow=wf.get("name") or wf.get("path") or "?",
                             branch=branch))
    return reds, deps, ("; ".join(fails) if fails else None)


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def _fmt_ts(s: str) -> str:
    return _fmt_dt(parse_ts(s))


def _fmt_dur(td: timedelta) -> str:
    h = td.total_seconds() / 3600
    return f"{h:.0f} 時間" if h < 24 else f"{h / 24:.1f} 日"


def render(reds, deps, unprobed, now, n_repos, as_of=None, dep_mode="detail"):
    """表示行の list (空 = 無出力)。 CI red は長期 → 継続の長い順、 次に Dependabot、 最後に検査不能。"""
    if dep_mode == "off":
        deps = []
    if not reds and not deps and not unprobed:
        return []
    for x in reds:
        x["age"] = now - parse_ts(x["first_red"]["created_at"])
        x["long"] = x["age"] >= timedelta(hours=LONG_HOURS) or x["n_red"] >= LONG_RUNS
    reds = sorted(reds, key=lambda x: (not x["long"], -x["age"].total_seconds(),
                                       x["repo"], x["workflow"]))
    tail = f"、 as of {_fmt_dt(now)}" if as_of is not None else ""
    lines = [f"🚦 CI red — default branch の最新 completed run が失敗している workflow "
             f"({len(reds)} 件 / {n_repos} repo 検査{tail})"]
    for x in reds:
        mark = "🚨 長期" if x["long"] else "🔴"
        n = f"{x['n_red']}{'+' if x['capped'] else ''}"
        lr, fr, g = x["latest_red"], x["first_red"], x["last_green"]
        if g is not None:
            gtxt = f"最後の success {_fmt_ts(g['created_at'])} ({(g.get('head_sha') or '')[:7]})"
        elif x["capped"]:
            gtxt = f"遡った {MAX_PAGES * PAGE} run 内に success 無し"
        else:
            gtxt = "success の記録なし"
        lines.append(f"  {mark} {x['repo']} · {x['workflow']}: {n} run 連続 red "
                     f"({lr.get('conclusion')}) / {_fmt_dur(x['age'])} 継続 "
                     f"({_fmt_ts(fr['created_at'])}〜、 {gtxt})")
        lines.append(f"      最新の失敗 = {lr.get('html_url', '')} "
                     f"({(lr.get('head_sha') or '')[:7]})")
    if deps and dep_mode == "summary":
        eco = {}
        for d in deps:
            for e in {j.split(" in ", 1)[0] for j, _ in d["jobs"]}:
                eco[e] = eco.get(e, 0) + 1
        by = " / ".join(f"{e} {n}" for e, n in sorted(eco.items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"  🟡 Dependabot update job の失敗 {len(deps)} repo ({by}。 "
                     f"= CI でなく依存更新が止まっている。 repo 別の内訳 = --dependabot detail)")
    elif deps:
        lines.append(f"  🟡 Dependabot update job の失敗 {len(deps)} repo "
                     f"(= CI でなく依存更新が止まっている。 job ごとの最新 run が失敗):")
        for d in sorted(deps, key=lambda d: d["repo"]):
            jobs = "、 ".join(f"{j} ({_fmt_ts(r['created_at'])[5:10]})" for j, r in d["jobs"])
            lines.append(f"      {d['repo']}: {jobs}")
    if unprobed:
        body = "; ".join(f"{name} ({why})" for name, why in unprobed)
        lines.append(f"  ⚠️ 検査不能 {len(unprobed)} repo (= 緑とは限らない): {body}")
    if reds:
        lines.append("  → 失敗行の確認: gh run view <URL 末尾の run id> -R <repo> --log-failed")
    return lines


def collect_targets(args):
    """→ (targets, unprobed, gh_down 理由 or None)"""
    targets, unprobed = list(args.repo or []), []
    for spec in args.note_unprobed or []:
        name, _, why = spec.partition("=")
        unprobed.append((name.strip(), why.strip() or "理由不明"))
    if args.repos_file:
        try:
            text = sys.stdin.read() if args.repos_file == "-" else open(
                args.repos_file, encoding="utf-8").read()
        except OSError as e:
            return targets, unprobed + [(args.repos_file, f"repos-file 読めず: {e}")], None
        ok, bad = parse_repo_lines(text)
        targets += ok
        unprobed += bad
    owners = list(args.owner or [])
    if not (args.repo or args.repos_file or owners):
        owners = [None]  # 認証 user 自身
    for owner in owners:
        names, err = gh_repo_list(owner)
        if err:
            unprobed.append((owner or "(認証 user)", f"repo 列挙: {err}"))
        else:
            targets += names
    seen, uniq = set(), []
    for t in targets:
        if t.lower() not in seen:
            seen.add(t.lower())
            uniq.append(t)
    return uniq, unprobed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GitHub Actions の red workflow を repo 横断で検出")
    ap.add_argument("--repo", action="append", metavar="OWNER/NAME")
    ap.add_argument("--repos-file", metavar="PATH|-")
    ap.add_argument("--owner", action="append")
    ap.add_argument("--note-unprobed", action="append", metavar="NAME=理由")
    ap.add_argument("--as-of", metavar="ISO8601")
    ap.add_argument("--strict", action="store_true", help="red / 検査不能があれば exit 1")
    ap.add_argument("--dependabot", choices=("detail", "summary", "off"), default="detail",
                    help="Dependabot update job 失敗の出し方 (既定 detail)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()

    as_of = parse_as_of(args.as_of) if args.as_of else None
    now = as_of or datetime.now(timezone.utc)

    # gh 自体が使えない (未認証 / network) なら repo ごとに並べず 1 行で言う
    _, err = gh_api("rate_limit")
    if err:
        print(f"⚠️ CI red 検査不能 (= 緑とは限らない): gh api が使えない ({err}) — "
              f"`gh auth status` を確認")
        return 1 if args.strict else 0

    targets, unprobed = collect_targets(args)
    reds, deps = [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda r: (r, check_repo(r, as_of)), targets))
    for repo, (rs, ds, why) in results:
        reds += rs
        deps += ds
        if why:
            unprobed.append((repo, why))
    for line in render(reds, deps, unprobed, now, len(targets), as_of, args.dependabot):
        print(line)
    if args.dependabot == "off":
        deps = []
    return 1 if args.strict and (reds or deps or unprobed) else 0


# ---------------------------------------------------------------- selftest

def selftest() -> int:
    global gh_api, gh_repo_list, DISPLAY_TZ
    DISPLAY_TZ = timezone.utc
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))

    base = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)

    def R(c, h, event="push", upd_h=None, rid=None, title=""):
        t = (base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        u = (base + timedelta(hours=upd_h if upd_h is not None else h)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        rid = rid if rid is not None else int(h * 100)
        return {"id": rid, "status": "completed", "conclusion": c, "event": event,
                "created_at": t, "updated_at": u, "head_sha": f"{rid:07d}abc",
                "display_title": title,
                "html_url": f"https://github.com/o/r/actions/runs/{rid}"}

    # walk
    ck("最新 success → green", walk([R("success", 3)])["state"] == "green")
    w = walk([R("failure", 3), R("failure", 2), R("success", 1)])
    ck("red 2 本 + success → red n=2", w["state"] == "red" and w["n_red"] == 2)
    ck("first_red = streak の最古", w["first_red"]["id"] == 200)
    ck("last_green = 直前の success", w["last_green"]["id"] == 100)
    w = walk([R("failure", 4), R("cancelled", 3), R("failure", 2), R("success", 1)])
    ck("cancelled は読み飛ばし (streak を切らない)", w["n_red"] == 2 and w["last_green"])
    ck("cancelled の後ろの success → green",
       walk([R("cancelled", 2), R("success", 1)])["state"] == "green")
    ck("run 無し → none", walk([])["state"] == "none")
    ck("skipped だけ → none", walk([R("skipped", 1)])["state"] == "none")
    ck("timed_out / startup_failure も red",
       walk([R("timed_out", 2), R("startup_failure", 1)])["n_red"] == 2)
    ck("success の記録が無い red", walk([R("failure", 1)])["last_green"] is None)

    # usable_runs
    u = usable_runs([R("failure", 3, event="pull_request"), R("success", 2)])
    ck("pull_request run は判定から除外", len(u) == 1 and u[0]["conclusion"] == "success")
    u = usable_runs([R("failure", 3, upd_h=10), R("success", 2)],
                    as_of=base + timedelta(hours=5))
    ck("as_of より後に完了した run は除外", len(u) == 1 and u[0]["conclusion"] == "success")

    # runs_path
    p = runs_path("o/r", 7, "feat/x", 20, 1, base)
    ck("branch を URL encode", "branch=feat%2Fx" in p)
    ck("as_of → created<= filter", "created=%3C%3D2026-09-01T00%3A00%3A00Z" in p)
    ck("as_of 無しなら created 無し", "created=" not in runs_path("o/r", 7, "main", 20, 1, None))

    # parse_repo_lines
    ok, bad = parse_repo_lines("a/b\n# c\n\n  d/e  # note\nnot-a-repo\n")
    ck("repos-file: comment / 空行 / 行末 comment", ok == ["a/b", "d/e"])
    ck("repos-file: 形式不正は検査不能へ", len(bad) == 1 and bad[0][0] == "not-a-repo")

    # check_repo / workflow_streak (gh_api を差し替え)
    streak150 = [R("failure", 2000 - i, rid=10000 - i) for i in range(150)]
    history = {
        "red150": streak150 + [R("success", 100, rid=5)] + [R("failure", 50, rid=4)],
        "red1200": [R("failure", 5000 - i, rid=20000 - i) for i in range(1200)],
        "green": [R("success", 9, rid=9), R("failure", 8, rid=8)],
        "short": [R("failure", 30, rid=31), R("success", 29, rid=30)],
        # ecosystem ごとの job が交互に並ぶ (pip = red / github_actions = green / npm = red)
        "dep": [R("failure", 60, rid=606, title="pip in /. - Update #6"),
                R("success", 60, rid=605, title="github_actions in /. - Update #5"),
                R("failure", 60, rid=604, title="npm_and_yarn in /. - Update #4"),
                # config (h=50 に commit) より前が最後の run = config で消した job → 出さない
                R("failure", 45, rid=607, title="cargo in /. - Update #7"),
                # security update (alert 起点) は config の commit より古くても出す
                R("failure", 44, rid=608, title="npm_and_yarn in /. for lodash - Update #8"),
                R("failure", 40, rid=603, title="github_actions in /. - Update #3"),
                R("success", 40, rid=602, title="npm_and_yarn in /. - Update #2"),
                R("failure", 40, rid=601, title="pip in /. - Update #1"),
                # config から消えた job (最新 run が他より 50 日古い) → 出さない
                R("failure", 60 - 24 * 50, rid=600, title="bundler in /. - Update #0")],
    }
    wf_ids = {1: "red150", 2: "red1200", 3: "green", 4: "short", 5: "red150", 6: "dep"}
    calls = []

    cfg_changed = {"o/r": (base + timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    open_alerts = {"o/r": [{"number": 1}]}

    def fake_api(path):
        calls.append(path)
        if path == "rate_limit":
            return {"resources": {}}, None
        if "/dependabot/alerts?" in path:
            a = open_alerts.get(path[len("repos/"):].split("/dependabot")[0], "error")
            return (None, "HTTP 403") if a == "error" else (a, None)
        if "/commits?path=" in path:
            t = cfg_changed.get(path[len("repos/"):].split("/commits")[0])
            if t == "error":
                return None, "Server Error (HTTP 500)"
            return ([{"commit": {"committer": {"date": t}}}] if t else []), None
        if path == "repos/o/missing":
            return None, "Not Found (HTTP 404)"
        if path == "repos/o/old":
            return {"archived": True, "default_branch": "main"}, None
        if path.startswith("repos/o/") and path.count("/") == 2:
            return {"archived": False, "default_branch": "main"}, None
        if path == "repos/o/nowf/actions/workflows?per_page=100":
            return None, "Server Error (HTTP 502)"
        if path == "repos/o/r/actions/workflows?per_page=100":
            return {"workflows": [
                {"id": 1, "name": "long", "state": "active", "path": ".github/workflows/l.yml"},
                {"id": 2, "name": "huge", "state": "active", "path": ".github/workflows/h.yml"},
                {"id": 3, "name": "ok", "state": "active", "path": ".github/workflows/o.yml"},
                {"id": 4, "name": "short", "state": "active", "path": ".github/workflows/s.yml"},
                {"id": 5, "name": "off", "state": "disabled_manually", "path": "x"},
                {"id": 6, "name": "Dependabot Updates", "state": "active",
                 "path": "dynamic/dependabot/dependabot-updates"},
            ]}, None
        if path == "repos/o/flaky/actions/workflows?per_page=100":
            return {"workflows": [{"id": 9, "name": "w", "state": "active", "path": "w"}]}, None
        if "/actions/workflows/9/runs" in path:
            return None, "HTTP 403: rate limit"
        m = re.search(r"/workflows/(\d+)/runs\?.*per_page=(\d+)&page=(\d+)", path)
        if m:
            runs = history[wf_ids[int(m.group(1))]]
            pp, pg = int(m.group(2)), int(m.group(3))
            return {"workflow_runs": runs[(pg - 1) * pp: pg * pp]}, None
        return None, f"unexpected {path}"

    gh_api = fake_api
    reds, deps, why = check_repo("o/r")
    byname = {x["workflow"]: x for x in reds}
    ck("Dependabot Updates は CI red に混ぜない", "Dependabot Updates" not in byname)
    ck("commits API path に dependabot.yml と branch を渡す",
       any("/commits?path=.github/dependabot.yml&sha=main&per_page=1" in c for c in calls))
    cfg_changed["o/r"] = "error"
    jobs_err = [j for j, _ in dependabot_failures("o/r", {"id": 6}, "main", None)[0]]
    cfg_changed["o/r"] = None
    jobs_none = [j for j, _ in dependabot_failures("o/r", {"id": 6}, "main", None)[0]]
    ck("config の commit 時刻が取れなければ間引かない (失敗 / 空応答とも)",
       "cargo in /." in jobs_err and "cargo in /." in jobs_none)
    open_alerts["o/r"] = []
    jobs_closed = [j for j, _ in dependabot_failures("o/r", {"id": 6}, "main", None)[0]]
    open_alerts["o/r"] = "error"
    jobs_alert_err = [j for j, _ in dependabot_failures("o/r", {"id": 6}, "main", None)[0]]
    open_alerts["o/r"] = [{"number": 1}]
    ck("open alert が無ければ security update の失敗は出さない",
       "npm_and_yarn in /. for lodash" not in jobs_closed and "pip in /." in jobs_closed)
    ck("alert API が失敗したら security update の失敗を出す (隠さない)",
       "npm_and_yarn in /. for lodash" in jobs_alert_err)
    ck("Dependabot は job 単位で red を読む (交互に並んでも) + 消えた job は出さない",
       len(deps) == 1 and [(j, r["id"]) for j, r in deps[0]["jobs"]]
       == [("npm_and_yarn in /.", 604), ("npm_and_yarn in /. for lodash", 608),
           ("pip in /.", 606)])
    ck("disabled workflow は対象外", "off" not in byname)
    ck("green workflow は finding にしない", "ok" not in byname)
    ck("150 連続 red を page を跨いで数える",
       byname.get("long", {}).get("n_red") == 150 and not byname["long"]["capped"])
    ck("150 連続 red の直前の success を拾う", byname["long"]["last_green"]["id"] == 5)
    ck("上限まで red → capped + 1000", byname.get("huge", {}).get("capped") is True
       and byname["huge"]["n_red"] == MAX_PAGES * PAGE)
    ck("短い red も finding", byname.get("short", {}).get("n_red") == 1)
    ck("全 workflow 取得できたら検査不能なし", why is None)
    ck("green workflow は 1 page で止まる (遡り call なし)",
       not any("workflows/3/runs" in c and "per_page=100" in c for c in calls))
    ck("repo 404 → 検査不能",
       check_repo("o/missing") == ([], [], "repo 情報: Not Found (HTTP 404)"))
    ck("archived → 対象外 (silent)", check_repo("o/old") == ([], [], None))
    ck("workflow 一覧失敗 → 検査不能", "workflow 一覧: Server Error" in (check_repo("o/nowf")[2] or ""))
    ck("run 一覧失敗 → workflow 名つき検査不能",
       check_repo("o/flaky") == ([], [], "w: HTTP 403: rate limit"))

    # render
    now = base + timedelta(hours=2000.5)
    lines = render(reds, deps, [("o/missing", "repo 情報: Not Found (HTTP 404)")], now, 3)
    text = "\n".join(lines)
    ck("render: header に件数", lines and "(3 件 / 3 repo 検査)" in lines[0])
    ck("render: 150 run は 🚨 長期", "🚨 長期 o/r · long: 150 run 連続 red" in text)
    ck("render: capped は +", "huge: 1000+ run 連続 red" in text and "遡った 1000 run 内に success 無し" in text)
    ck("render: 検査不能 1 行", "⚠️ 検査不能 1 repo (= 緑とは限らない): o/missing" in text)
    ck("render: 長期が先頭", lines[1].startswith("  🚨 長期"))
    ck("render: Dependabot は別枠 (件数に数えない)",
       "🟡 Dependabot update job の失敗 1 repo" in text
       and "o/r: npm_and_yarn in /. (09-03)、 npm_and_yarn in /. for lodash (09-02)、 "
           "pip in /. (09-03)" in text)
    t5 = "\n".join(render([], deps, [], now, 1))
    ck("render: Dependabot だけでも出す", "(0 件 / 1 repo 検査)" in t5 and "🟡" in t5
       and "失敗行の確認" not in t5)
    two = deps + [{"repo": "o/s", "jobs": [("npm_and_yarn in /. for x", deps[0]["jobs"][0][1])]}]
    t6 = render([], two, [], now, 2, dep_mode="summary")
    ck("summary: 1 行 + ecosystem 別の repo 数 (多い順)",
       len(t6) == 2 and "2 repo (npm_and_yarn 2 / pip 1。" in t6[1])
    ck("off: Dependabot だけなら無出力", render([], deps, [], now, 1, dep_mode="off") == [])
    short_only = [dict(byname["short"])]
    t2 = "\n".join(render(short_only, [], [], base + timedelta(hours=31), 1))
    ck("render: 1 時間・1 run は 🔴", "  🔴 o/r · short: 1 run 連続 red (failure) / 1 時間 継続" in t2)
    ck("render: 最後の success を表示", "最後の success 2026-09-02 05:00 (0000030)" in t2)
    ten = [dict(byname["short"], n_red=LONG_RUNS)]
    ck("render: 10 run 以上は時間が短くても 🚨",
       "🚨 長期" in "\n".join(render(ten, [], [], base + timedelta(hours=31), 1)))
    ck("render: 何も無ければ無出力", render([], [], [], now, 5) == [])
    t3 = "\n".join(render([], [], [("x", "未 clone")], now, 0))
    ck("render: 検査不能だけでも出す (0 件と区別)", "0 件" in t3 and "検査不能 1 repo" in t3)

    # main: gh が使えない → 1 行、 targets の検査不能と note-unprobed の合流
    def dead_api(path):
        return None, "HTTP 401: Bad credentials"
    gh_api = dead_api
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--repo", "o/r"])
    out = buf.getvalue().strip().splitlines()
    ck("gh 不調 → 1 行だけ + exit 0", rc == 0 and len(out) == 1 and "gh api が使えない" in out[0])
    with redirect_stdout(io.StringIO()):
        ck("gh 不調 + --strict → exit 1", main(["--repo", "o/r", "--strict"]) == 1)
    gh_api = fake_api
    gh_repo_list = lambda owner: (None, "HTTP 404")  # noqa: E731
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--repo", "o/missing", "--repo", "O/Missing", "--owner", "ghost",
                   "--note-unprobed", "local-dir=未 clone"])
    t4 = buf.getvalue()
    ck("repo 名の重複 (大小文字違い) は 1 回だけ検査", "1 repo 検査" in t4)
    ck("note-unprobed / owner 列挙失敗 / 404 が 1 行に合流",
       "検査不能 3 repo" in t4 and "local-dir (未 clone)" in t4 and "ghost (repo 列挙: HTTP 404)" in t4)

    fails = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'✅' if ok else '❌'} {n}")
    print(f"--- check-ci-red selftest: PASS={len(checks) - len(fails)} FAIL={len(fails)} ---")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
