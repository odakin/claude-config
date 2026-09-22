"""Compare a selected historical engine with the worktree engine: hook path (explicit files / dir) and pre-commit path, N new files."""
import argparse, os, runpy, subprocess, sys, tempfile, time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('count', type=int)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument('--before-ref', required=True)
args = parser.parse_args()
if args.count < 1:
    parser.error('count must be positive')
N, CC = args.count, args.repo.resolve()
os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
td = tempfile.mkdtemp()
old_src = Path(td) / "old" / "scripts"; old_src.mkdir(parents=True)
(old_src / "manuscript-claim-guard.py").write_text(
    subprocess.run(["git", "-C", str(CC), "show", args.before_ref + ":scripts/manuscript-claim-guard.py"], capture_output=True, text=True).stdout)
os.symlink(CC / "scripts/lib", old_src / "lib")
engines = {"old": runpy.run_path(str(old_src / "manuscript-claim-guard.py"), run_name="old"),
           "new": runpy.run_path(str(CC / "scripts/manuscript-claim-guard.py"), run_name="new")}


def mkrepo(suffix):
    repo = Path(tempfile.mkdtemp()) / "r"; repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
    g("init", "-q"); (repo / "README.md").write_text("x\n"); g("add", "-A"); g("commit", "-qm", "i")
    (repo / "big").mkdir()
    for i in range(N):
        (repo / "big" / f"f{i}{suffix}").write_text("x\n")
    return repo, g


for suffix in (".txt", ".pdf"):
    repo, g = mkrepo(suffix)
    files = " ".join(f"big/f{i}{suffix}" for i in range(N))
    for name, eng in engines.items():
        for label, cmd in (("hook: add files && commit -- files", f"git add {files} && git commit -m x -- {files}"),
                           ("hook: add dir && commit -- dir", "git add big/ && git commit -m x -- big/")):
            t0 = time.time()
            try:
                for rp, mode, paths in eng["commit_targets"](cmd, repo):
                    eng["changes_for_repo"](rp, mode, paths)
                res = "ok"
            except Exception as e:
                res = type(e).__name__
            print(f"{suffix} {name:3} {label:38} {time.time()-t0:6.1f}s {res}")
    g("add", "big/")
    for name, eng in engines.items():
        t0 = time.time()
        eng["changes_for_repo"](repo, "index", [])
        print(f"{suffix} {name:3} {'pre-commit: staged diff (index mode)':38} {time.time()-t0:6.1f}s")
