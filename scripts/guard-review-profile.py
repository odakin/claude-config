"""Profile manuscript-claim-guard changes_for_repo on N untracked files (mock repo)."""
import argparse, cProfile, os, pstats, runpy, subprocess, sys, tempfile, time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('count', type=int)
parser.add_argument('suffix')
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
if args.count < 1:
    parser.error('count must be positive')
N, SUFFIX = args.count, args.suffix
os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
eng = runpy.run_path(str(args.repo.resolve() / "scripts/manuscript-claim-guard.py"), run_name="eng")
with tempfile.TemporaryDirectory() as td:
    repo = Path(td) / "r"; repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "i"], check=True)
    d = repo / "big"; d.mkdir()
    for i in range(N):
        (d / f"f{i}{SUFFIX}").write_text("x\n")
    targets = eng["commit_targets"](f"git add big/ && git commit -m x -- big/", repo)
    t0 = time.time()
    pr = cProfile.Profile(); pr.enable()
    ch = eng["changes_for_repo"](*targets[0])
    pr.disable()
    dt = time.time() - t0
    print(f"N={N} suffix={SUFFIX!r}: {dt:.2f}s ({1000*dt/N:.1f} ms/file), changes={len(ch)}")
    st = pstats.Stats(pr); st.sort_stats("cumulative")
    calls = st.stats
    sub = sum(v[1] for k, v in calls.items() if k[2] == "run" and "subprocess" in k[0])
    print("subprocess.run calls:", sub)
    st.print_stats(8)
