#!/usr/bin/env python3
"""manuscript-candidate-regions.py — 候補の全文が原稿のどの保護領域に当たるかを、 書く前に engine の述語で出す。

`manuscript-claim-guard.py scan` は HEAD と作業ツリーの差しか読まないので、 まだ当てていない候補は見えない。
裁定の記録 (`approve --region`) に引ける発言は最新のものだけなので、 候補がどの領域に当たるかは、
著者の次の発言が来る前に知りたい。 当ててから拒否を見る形だと、 その間に次の発言が来ると同じ裁定を
言い直してもらうことになる。 結論の節は見出しで判定するので、 節の題の変更で保護の境界も動く (実測)。

候補は写しに当てた全文の file を渡す (`apply-text-pairs.py` を写しに掛けたものなど)。 読むだけで、
原稿も承認の state も変えない。 判定は engine の `protected_changes` そのもの (述語を複製しない)。

Usage:
  manuscript-candidate-regions.py <repo> <repo からの path> <候補の file> [--base <rev>]
      出力 = 1 行ずつ `<path> :: <region> (<kind>)`、 当たらなければ `none`。 基準の既定 = HEAD
  manuscript-candidate-regions.py --selftest
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().with_name("manuscript-claim-guard.py")


def load_engine():
    spec = importlib.util.spec_from_file_location("manuscript_claim_guard_engine", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def candidate_regions(repo: Path, rel: str, candidate: Path, base: str = "HEAD") -> list[dict]:
    old = subprocess.run(["git", "-C", str(repo), "show", f"{base}:{rel}"],
                         capture_output=True, text=True, check=True).stdout
    return load_engine().protected_changes(rel, old, candidate.read_text(encoding="utf-8"), repo)


def selftest() -> int:
    tex = ("\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\nShort abstract.\n\\end{abstract}\n"
           "\\section{Introduction}\nFirst claim.\n\\section{Method}\nBody text.\n"
           "\\section{Conclusions}\nLast claim.\n\\end{document}\n")
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="fixture",
               GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_NAME="fixture",
               GIT_COMMITTER_EMAIL="fixture@example.invalid")
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td).resolve() / "repo"
        repo.mkdir()
        (repo / "main.tex").write_text(tex, encoding="utf-8")
        for args in (["init", "-q"], ["add", "main.tex"], ["commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
        cases = [
            ("本文の節は当たらない", tex.replace("Body text.", "Other text."), []),
            ("結論の節は conclusion", tex.replace("Last claim.", "Another claim."), ["conclusion"]),
            ("序論と概要は 2 つ", tex.replace("First claim.", "New claim.").replace("Short abstract.", "New abstract."),
             ["abstract", "intro"]),
        ]
        for name, text, expected in cases:
            cand = Path(td) / "cand.tex"
            cand.write_text(text, encoding="utf-8")
            got = sorted({c["region"] for c in candidate_regions(repo, "main.tex", cand)})
            ok = got == sorted(expected)
            print(("ok  " if ok else "FAIL"), name, got)
            fails += 0 if ok else 1
    print("selftest:", "PASS" if not fails else f"{fails} FAIL")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="候補の全文が当たる原稿の保護領域を書く前に出す")
    ap.add_argument("repo", nargs="?", type=Path)
    ap.add_argument("path", nargs="?", help="repo からの原稿の path")
    ap.add_argument("candidate", nargs="?", type=Path, help="候補の全文の file")
    ap.add_argument("--base", default="HEAD", help="比べる版 (既定 HEAD)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.repo and a.path and a.candidate):
        ap.error("repo・path・candidate の 3 つが要る")
    changes = candidate_regions(a.repo.resolve(), a.path, a.candidate, a.base)
    for c in changes:
        print(f"{c['file']} :: {c['region']} ({c['kind']})")
    if not changes:
        print("none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
