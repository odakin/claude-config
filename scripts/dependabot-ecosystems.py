#!/usr/bin/env python3
"""dependabot-ecosystems.py — dependabot.yml の ecosystem を repo の実体に合わせる（manifest の無い / git-crypt で暗号化された npm・pip・github-actions の entry を検出、 --apply で contents API 経由で削る (全部消えるなら file ごと削除)、 manifest があるのに未設定は ℹ️、 --render で配置時に template から選ぶ、 --selftest。 conventions/github-security-automation.md#dependabot-ecosystem-must-exist）

背景: 全 repo に同じ dependabot.yml (npm + pip + github-actions) を配る baseline だと、 manifest
の無い ecosystem の update job が毎回 "Error during file fetching; aborting: ... not found" で
失敗し、 Dependabot Updates が恒常 red になる (実例: owner の約 20 repo。 検出 =
scripts/check-ci-red.py の Dependabot 枠)。

対象 repo (複数併用可、 重複は除去):
  位置引数 OWNER/NAME / --repos-file PATH|- (1 行 1 repo、 # 以降 comment)。
  どれも無ければ認証 user の repo (gh repo list、 archived 除外)。 個人層の repo 一覧から作るなら
    check-ci-red.py --from-repos-md <repos.md> --print-targets | dependabot-ecosystems.py --repos-file -
  そのうち認証 user が admin の repo だけを触る (= 自分の repo と admin の org repo。 共同編集者
  として write だけ持つ他人の repo は触らない)。 archived / fork / dependabot.yml 無しは対象外。

述語 (= code-as-SoT):
  - entry を「manifest あり」 と判定する条件 (directory 直下で見る。 `directories:` 複数指定の
    entry と下表以外の ecosystem は判定せず残す):
      npm            package.json
      pip            requirements*.txt / requirements/*.txt / *.in / setup.py / setup.cfg /
                     pyproject.toml / Pipfile
      github-actions directory が / なら .github/workflows/*.yml|yaml、 他は action.yml|yaml
  - 見つかった manifest が全部 git-crypt の暗号 blob (先頭 \\0GITCRYPT) なら「無い」 と同じ扱い
    (= Dependabot は読めずに失敗する)
  - tree API が truncated を返した repo は判定しない (= 見えていない manifest を無いと言わない)
  - 逆向き (manifest はあるのに ecosystem が未設定) は ℹ️ として出すだけで足さない

書き換え: entry の block (`- package-ecosystem:` から次の entry 直前まで) を text のまま削る
(= comment や cooldown の書式を保つ)。 削った結果を yaml で読み直し、 残る ecosystem が期待と
一致しなければ書かない。 書き込みは contents API (= local clone に触らない。 並列 session の
作業ツリーと衝突しない)。 author は git の global user.name / user.email を noreply のときだけ
明示する (それ以外は GitHub の既定に任せる = 推測した実 email を公開履歴に焼かない)。
--render OWNER/NAME --template PATH: template から、 その repo に manifest の無い npm / pip の entry を
落として stdout に出す (github-actions は baseline が workflow を置く前提で常に残す)。
出力: 要修正 / 検査不能 / ℹ️ の一覧 (既定は plan のみ、 --apply で書き込み)。 exit 0。
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

CFG_PATH = ".github/dependabot.yml"
GITCRYPT_MAGIC = b"\x00GITCRYPT"
JUDGED = ("npm", "pip", "github-actions")
_ENTRY_RE = re.compile(r"^(\s*)-\s+package-ecosystem:\s*[\"']?([\w-]+)[\"']?")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# ---------------------------------------------------------------- pure logic

def _norm_dir(d: str) -> str:
    return (d or "/").strip().strip("/")


def manifests_for(eco: str, directory: str, paths) -> list[str] | None:
    """eco の manifest を paths (repo 内の全 file path) から探す。 None = 判定しない ecosystem。"""
    d = _norm_dir(directory)
    pre = f"{d}/" if d else ""

    def in_dir(p):  # directory 直下の file 名 (直下でなければ None)
        if not p.startswith(pre):
            return None
        rest = p[len(pre):]
        return rest if "/" not in rest else None

    if eco == "npm":
        return [p for p in paths if in_dir(p) == "package.json"]
    if eco == "pip":
        names = {"setup.py", "setup.cfg", "pyproject.toml", "Pipfile"}
        out = []
        for p in paths:
            n = in_dir(p)
            if n and (n in names or re.fullmatch(r"requirements.*\.txt", n) or n.endswith(".in")):
                out.append(p)
            elif p.startswith(pre + "requirements/") and p.endswith(".txt") \
                    and "/" not in p[len(pre + "requirements/"):]:
                out.append(p)
        return out
    if eco == "github-actions":
        if not d:
            return [p for p in paths if re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p)]
        return [p for p in paths if in_dir(p) in ("action.yml", "action.yaml")]
    return None


def entries(cfg: dict):
    """dependabot.yml の updates → [(ecosystem, directory or None)] (directories 指定は None)。"""
    out = []
    for u in (cfg or {}).get("updates") or []:
        eco = u.get("package-ecosystem")
        out.append((eco, u.get("directory") if "directories" not in u else None))
    return out


def judge(cfg_text: str, paths, encrypted) -> dict:
    """→ {keep: [...], drop: [(eco, 理由)], info: [...]}。 encrypted(path) -> bool。"""
    cfg = yaml.safe_load(cfg_text) or {}
    keep, drop = [], []
    configured = set()
    for eco, d in entries(cfg):
        configured.add(eco)
        if d is None or eco not in JUDGED:
            keep.append(eco)
            continue
        found = manifests_for(eco, d, paths)
        if not found:
            drop.append((eco, "manifest 無し"))
        elif all(encrypted(p) for p in found):
            drop.append((eco, "manifest が git-crypt で暗号化"))
        else:
            keep.append(eco)
    info = []
    for eco in JUDGED:
        if eco not in configured:
            found = manifests_for(eco, "/", paths) or []
            if found and not all(encrypted(p) for p in found):
                info.append(f"{eco} は manifest があるのに未設定 ({found[0]})")
    return {"keep": keep, "drop": drop, "info": info}


def remove_entries(text: str, drop_ecos) -> str:
    """dependabot.yml の text から drop_ecos の entry block を削る (書式は保つ)。"""
    out, skipping, indent = [], False, None
    for line in text.splitlines(keepends=True):
        m = _ENTRY_RE.match(line)
        if m:
            indent = len(m.group(1))
            skipping = m.group(2) in drop_ecos
        elif skipping and line.strip() and (len(line) - len(line.lstrip())) <= (indent or 0) \
                and not line.lstrip().startswith("#"):
            skipping = False  # 次の top-level key 等
        if not skipping:
            out.append(line)
    res = re.sub(r"\n{3,}", "\n\n", "".join(out))
    return res.rstrip("\n") + "\n"


def remaining_ecos(text: str) -> list[str]:
    return [e for e, _ in entries(yaml.safe_load(text) or {})]


def parse_repo_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip()
        if s and _REPO_RE.match(s):
            out.append(s)
    return out


# ---------------------------------------------------------------- GitHub I/O

def gh(args, *, raw=False):
    """gh api → (data, None) か (None, 理由)。 raw=True なら bytes を返す。"""
    try:
        r = subprocess.run(["gh", "api", *args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, e.__class__.__name__
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return None, (err[-1] if err else f"rc={r.returncode}")[:80]
    if raw:
        return r.stdout, None
    try:
        return json.loads(r.stdout or b"null"), None
    except json.JSONDecodeError:
        return None, "JSON 解釈不能"


def author_fields():
    def cfg(k):
        return subprocess.run(["git", "config", "--global", k], capture_output=True,
                              text=True).stdout.strip()
    name, email = cfg("user.name"), cfg("user.email")
    if name and email.endswith("@users.noreply.github.com"):
        return ["-f", f"author[name]={name}", "-f", f"author[email]={email}",
                "-f", f"committer[name]={name}", "-f", f"committer[email]={email}"]
    return []


def _encrypted_checker(repo, branch):
    cache = {}

    def encrypted(p):
        if p not in cache:
            body, e = gh(["-H", "Accept: application/vnd.github.raw",
                          f"repos/{repo}/contents/{p}?ref={branch}"], raw=True)
            cache[p] = e is None and bool(body) and body.startswith(GITCRYPT_MAGIC)
        return cache[p]
    return encrypted


def _tree_paths(repo, branch):
    tree, err = gh([f"repos/{repo}/git/trees/{branch}?recursive=1"])
    if err:
        return None, f"tree: {err}"
    if tree.get("truncated"):
        return None, "tree が truncated (大きすぎて全 path が見えない)"
    return [t["path"] for t in tree.get("tree") or [] if t.get("type") == "blob"], None


def inspect(repo: str) -> dict:
    """1 repo を調べて plan の 1 行分を返す。"""
    info, err = gh([f"repos/{repo}"])
    if err:
        return {"repo": repo, "status": "検査不能", "why": f"repo 情報: {err}"}
    if info.get("archived") or info.get("fork"):
        return {"repo": repo, "status": "skip"}
    if not (info.get("permissions") or {}).get("admin"):
        return {"repo": repo, "status": "skip", "why": "admin でない"}
    branch = info.get("default_branch") or "main"
    meta, err = gh([f"repos/{repo}/contents/{CFG_PATH}?ref={branch}"])
    if err:
        if "404" in err:
            return {"repo": repo, "status": "skip", "why": "dependabot.yml 無し"}
        return {"repo": repo, "status": "検査不能", "why": f"dependabot.yml: {err}"}
    text = base64.b64decode(meta.get("content") or "").decode("utf-8", "replace")
    paths, err = _tree_paths(repo, branch)
    if err:
        return {"repo": repo, "status": "検査不能", "why": err}
    try:
        j = judge(text, paths, _encrypted_checker(repo, branch))
    except yaml.YAMLError as e:
        return {"repo": repo, "status": "検査不能",
                "why": f"dependabot.yml が YAML として読めない ({e.__class__.__name__})"}
    return {"repo": repo, "status": "ok" if not j["drop"] else "fix", "branch": branch,
            "sha": meta.get("sha"), "text": text, **j}


def apply(row: dict) -> str:
    repo, drop = row["repo"], [e for e, _ in row["drop"]]
    what = ", ".join(drop)
    if not row["keep"]:
        _, err = gh(["-X", "DELETE", f"repos/{repo}/contents/{CFG_PATH}",
                     "-f", f"message=dependabot.yml: remove (no readable manifest for {what})",
                     "-f", f"sha={row['sha']}", "-f", f"branch={row['branch']}", *author_fields()])
        return f"削除 {'✓' if not err else '✗ ' + err}"
    new = remove_entries(row["text"], set(drop))
    if sorted(remaining_ecos(new)) != sorted(row["keep"]):
        return "✗ 書き換え結果の検証に失敗 (手で直す)"
    b64 = base64.b64encode(new.encode()).decode()
    _, err = gh(["-X", "PUT", f"repos/{repo}/contents/{CFG_PATH}",
                 "-f", f"message=dependabot.yml: drop {what} (no readable manifest)",
                 "-f", f"content={b64}", "-f", f"sha={row['sha']}",
                 "-f", f"branch={row['branch']}", *author_fields()])
    return f"{what} を削除 {'✓' if not err else '✗ ' + err}"


def render(repo: str, template_text: str) -> tuple[str | None, str | None]:
    """template から、 repo に manifest が無い (か暗号化された) npm / pip の entry を落とす。
    → (text, None) か (None, 理由)。 github-actions は常に残す。"""
    info, err = gh([f"repos/{repo}"])
    if err:
        return None, f"repo 情報を取れない ({err})"
    branch = info.get("default_branch") or "main"
    paths, err = _tree_paths(repo, branch)
    paths = paths or []  # 空 repo (tree 無し) は manifest 無しとして扱う
    encrypted = _encrypted_checker(repo, branch)
    drop = set()
    for eco in ("npm", "pip"):
        found = manifests_for(eco, "/", paths)
        if not found or all(encrypted(p) for p in found):
            drop.add(eco)
    return remove_entries(template_text, drop), None


def default_repos() -> list[str]:
    r = subprocess.run(["gh", "repo", "list", "--no-archived", "--limit", "1000",
                        "--json", "nameWithOwner"], capture_output=True, text=True)
    try:
        return [x["nameWithOwner"] for x in json.loads(r.stdout)]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="dependabot.yml の ecosystem を repo の実体に合わせる")
    ap.add_argument("repos", nargs="*", metavar="OWNER/NAME")
    ap.add_argument("--repos-file", metavar="PATH|-")
    ap.add_argument("--apply", action="store_true", help="plan でなく書き込む")
    ap.add_argument("--render", metavar="OWNER/NAME", help="template から選んだ dependabot.yml を出す")
    ap.add_argument("--template", metavar="PATH", help="--render の template")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.render:
        if not args.template:
            print("--render には --template が要る", file=sys.stderr)
            return 2
        text, err = render(args.render, Path(args.template).read_text(encoding="utf-8"))
        if err:
            print(f"render: {err}", file=sys.stderr)
            return 1
        sys.stdout.write(text)
        return 0

    repos = list(args.repos)
    if args.repos_file:
        src = sys.stdin.read() if args.repos_file == "-" else Path(args.repos_file).read_text(
            encoding="utf-8")
        repos += parse_repo_lines(src)
    if not repos and not args.repos_file:
        repos = default_repos()
    repos = list(dict.fromkeys(repos))
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(inspect, repos))
    fixes = [r for r in rows if r["status"] == "fix"]
    bad = [r for r in rows if r["status"] == "検査不能"]
    infos = [(r["repo"], i) for r in rows for i in r.get("info") or []]
    print(f"dependabot.yml の ecosystem 検査: {len(repos)} repo / 要修正 {len(fixes)} / "
          f"検査不能 {len(bad)}{' (--apply)' if args.apply else ' (plan のみ、 --apply で書き込み)'}")
    for r in sorted(fixes, key=lambda r: r["repo"]):
        drops = "、 ".join(f"{e} ({why})" for e, why in r["drop"])
        tail = "→ file ごと削除" if not r["keep"] else f"残す = {', '.join(r['keep'])}"
        res = f"  … {apply(r)}" if args.apply else ""
        print(f"  {r['repo']}: 削る = {drops} / {tail}{res}")
    for r in bad:
        print(f"  ⚠️ 検査不能 {r['repo']}: {r['why']}")
    for repo, i in infos:
        print(f"  ℹ️ {repo}: {i}")
    return 0


# ---------------------------------------------------------------- selftest

TEMPLATE_SAMPLE = """version: 2
updates:
  - package-ecosystem: "npm"
    cooldown:
      default-days: 7
    directory: "/"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: 5

  - package-ecosystem: "pip"
    cooldown:
      default-days: 7
    directory: "/"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: 5

  - package-ecosystem: "github-actions"
    cooldown:
      default-days: 7
    directory: "/"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: 5
"""


def selftest() -> int:
    global gh
    checks = []

    def ck(n, c):
        checks.append((n, bool(c)))

    tpl = TEMPLATE_SAMPLE
    paths = ["README.md", ".github/workflows/ci.yml", "sub/package.json", "pyproject.toml",
             "requirements/dev.txt", "tools/action.yml"]
    ck("npm は directory 直下だけ", manifests_for("npm", "/", paths) == [])
    ck("npm: sub 指定なら見つかる", manifests_for("npm", "/sub", paths) == ["sub/package.json"])
    ck("pip: pyproject + requirements/*.txt",
       manifests_for("pip", "/", paths) == ["pyproject.toml", "requirements/dev.txt"])
    ck("github-actions: / は workflows",
       manifests_for("github-actions", "/", paths) == [".github/workflows/ci.yml"])
    ck("github-actions: 他 dir は action.yml",
       manifests_for("github-actions", "tools", paths) == ["tools/action.yml"])
    ck("判定しない ecosystem は None", manifests_for("gomod", "/", paths) is None)

    j = judge(tpl, ["README.md", ".github/workflows/ci.yml"], lambda p: False)
    ck("template: npm / pip を manifest 無しで落とす",
       [e for e, _ in j["drop"]] == ["npm", "pip"] and j["keep"] == ["github-actions"])
    j = judge(tpl, ["package.json", "requirements.txt"], lambda p: p == "requirements.txt")
    ck("暗号化 manifest は無いと同じ", ("pip", "manifest が git-crypt で暗号化") in j["drop"]
       and ("github-actions", "manifest 無し") in j["drop"] and j["keep"] == ["npm"])
    j = judge("version: 2\nupdates:\n  - package-ecosystem: npm\n    directory: /\n",
              ["package.json", "requirements.txt"], lambda p: False)
    ck("逆向き (manifest あり・未設定) は info",
       any(i.startswith("pip は manifest があるのに未設定") for i in j["info"]))
    multi = "version: 2\nupdates:\n  - package-ecosystem: npm\n    directories: ['/a', '/b']\n"
    ck("directories 指定は判定せず残す", judge(multi, [], lambda p: False)["keep"] == ["npm"])

    new = remove_entries(tpl, {"npm", "pip"})
    ck("block 削除: 残りは github-actions だけ", remaining_ecos(new) == ["github-actions"])
    ck("block 削除: cooldown 等の書式を保つ", "cooldown:\n      default-days: 7" in new
       and new.startswith("version: 2\nupdates:\n"))
    ck("block 削除: 空行が 3 連続しない", "\n\n\n" not in new)
    cmt = ("version: 2\nupdates:\n  - package-ecosystem: \"pip\"\n    directory: \"/\"\n"
           "    # comment\n  - package-ecosystem: npm\n    directory: /\nregistries: {}\n")
    r2 = remove_entries(cmt, {"pip"})
    ck("block 削除: 字下げした comment も block ごと消え、 後続 top-level key は残る",
       remaining_ecos(r2) == ["npm"] and "# comment" not in r2 and "registries: {}" in r2)
    ck("repos-file: comment / 空行 / 形式不正を除く",
       parse_repo_lines("a/b\n# x\n\nnot-a-repo\n c/d  # note\n") == ["a/b", "c/d"])

    # gh を差し替えて render / inspect
    enc = GITCRYPT_MAGIC + b"..."

    def fake(args, *, raw=False):
        path = args[-1]
        if path in ("repos/o/web", "repos/o/secret"):
            return {"default_branch": "main", "permissions": {"admin": True}}, None
        if path == "repos/o/theirs":
            return {"default_branch": "main", "permissions": {"admin": False}}, None
        if path == "repos/o/web/git/trees/main?recursive=1":
            return {"tree": [{"path": "package.json", "type": "blob"}]}, None
        if path == "repos/o/secret/git/trees/main?recursive=1":
            return {"tree": [{"path": "requirements.txt", "type": "blob"}]}, None
        if path.startswith("repos/o/secret/contents/requirements.txt"):
            return enc, None
        if path.startswith("repos/o/web/contents/package.json"):
            return b"{}", None
        return None, "Not Found (HTTP 404)"

    gh = fake
    t_web, _ = render("o/web", tpl)
    t_sec, _ = render("o/secret", tpl)
    ck("render: package.json のある repo は npm + github-actions",
       remaining_ecos(t_web) == ["npm", "github-actions"])
    ck("render: 暗号化された requirements.txt しか無い repo は github-actions だけ",
       remaining_ecos(t_sec) == ["github-actions"])
    ck("inspect: admin でない repo は触らない", inspect("o/theirs")["status"] == "skip")
    ck("inspect: dependabot.yml 無しは skip", inspect("o/web").get("why") == "dependabot.yml 無し")

    fails = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'✅' if ok else '❌'} {n}")
    print(f"--- dependabot-ecosystems selftest: PASS={len(checks) - len(fails)} FAIL={len(fails)} ---")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
