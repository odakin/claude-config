#!/usr/bin/env python3
"""check-yaml-lint.py — fleet 横断 YAML hazard lint (yamllint を危険 rule 限定で全 repo の tracked yaml に回す。 truthy / dup-key / implicit-octal / syntax、 git-crypt lock file skip、 yamllint 未 install や root 不在は SKIP、 --selftest は毒入り fixture で検出能力自体を検証。 規約 = conventions/yaml-hazards.md#yamllint-hazard-config)

YAML の意味論 hazard (= parser は仕様どおりなのに人間の意図と乖離する class) のうち
機械検出可能なものを「書いた瞬間に怒られる」 層で塞ぐ検査器。 検出するのは:

  - truthy 誤爆 (Norway problem): `no:` / `yes` / `on` が YAML 1.1 parser で bool に化ける
  - key 重複: 後勝ち silent merge で先の値が機械から不可視になる
  - implicit octal: `0755` が 493 に化ける
  - syntax error (= yamllint が rule 無しでも常時報告)

rule 選定・config の設計理由・gotcha (⚠️ `extends: null` は yamllint を crash させ
「rc=1 + stdout 空」 を clean と誤読させる / opt-out directive は純粋行必須) の正本 =
conventions/yaml-hazards.md#yamllint-hazard-config。

scope:
  - root (= 既定 ~/Claude、 env CLAUDE_YAML_LINT_ROOT で override) 直下の git repo 群の
    tracked *.yml / *.yaml (git ls-files 経由 = gitignored 生成物は自動除外)。
  - root 不在 / repo ゼロ / yamllint 未 install は SKIP 宣言して exit 0
    (= run-all-checks の環境依存 test 契約。 CI 等 fleet が無い環境では selftest が発火面)。
  - git-crypt lock 中の file (= 先頭 magic \\x00GITCRYPT) は skip。
  - 検査対象から外したい file (= 生成物で generator 側が保証する等) は yamllint 標準の
    file 先頭 `# yamllint disable` / `# yamllint disable rule:<rule>` で opt-out する
    (⚠️ directive 行に説明文を後置しない — parse されず silent 無効。 説明は次の comment 行)。

declared 圏外 (= 本 lint では原理的に拾えない、 domain schema gate が相補):
  - scalar 内の「コロン + 空白」 が mapping に化ける事故 (= valid YAML なので lint 不能)。
  - `3.10` → 3.1 等の float 化 (= quote の習慣で防ぐ、 yaml-hazards.md#hazard-classes)。

exit: 0 = clean or SKIP / 1 = finding あり or 検査自体の故障 (= config 破損等は
「rc≠0 + stdout 空 + stderr あり」 で出る — これを clean と誤読せず loud に fail)。
--selftest は毒入り fixture で「0 件」 が「検出器が寝ている 0 件」 でないことを検証する。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ⚠️ `extends: null` を書かない — yamllint 1.37 は extends キーが null だと crash する
# (= rc=1 + stdout 空。 これを「clean」 と誤読した実績があり selftest が捕捉した。 extends は
# キーごと省略すると「指定 rule のみ」 になる)
CONF = (
    '{rules: {'
    'key-duplicates: enable, '
    # truthy の ignore: GitHub workflow の trigger key `on:` は正当 (GitHub parser は対応済み、
    # yamllint の有名 FP class)。 .github/ と workflow template 置き場を rule 限定で除外
    # (= dup-key / syntax 検査は workflow にも効いたまま)
    'truthy: {allowed-values: ["true","false","True","False"], check-keys: true, level: error, '
    'ignore: [".github/", "templates/"]}, '
    'octal-values: {forbid-implicit-octal: true, forbid-explicit-octal: false}}}'
)

GITCRYPT_MAGIC = b"\x00GITCRYPT"


def find_yamllint():
    from shutil import which
    for cand in ("yamllint",
                 os.path.expanduser("~/Library/Python/3.9/bin/yamllint"),
                 os.path.expanduser("~/.local/bin/yamllint")):
        if which(cand) or os.path.exists(cand):
            return cand
    return None


def collect_files(root: Path):
    files = []
    if not root.is_dir():
        return files
    for repo in sorted(root.iterdir()):
        if not (repo / ".git").exists():
            continue
        try:
            out = subprocess.run(
                ["git", "-C", str(repo), "ls-files", "*.yml", "*.yaml"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except Exception:
            continue
        for rel in out.split("\n"):
            rel = rel.strip()
            if not rel:
                continue
            p = repo / rel
            if not p.is_file():
                continue
            try:
                if open(p, "rb").read(10).startswith(GITCRYPT_MAGIC):
                    continue  # git-crypt locked (CI 等)
            except OSError:
                continue
            files.append(str(p))
    return files


def run_lint(yl: str, files):
    """returns (findings_lines, hard_error)"""
    if not files:
        return [], None
    r = subprocess.run([yl, "-d", CONF, "-f", "parsable"] + files,
                       capture_output=True, text=True)
    lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
    # yamllint 自体の異常 (config error 等) は rc≠0 + stdout 空 + stderr あり で出る —
    # これを「clean」 と誤読しない (= selftest が捕捉した extends:null crash の教訓)
    if r.returncode not in (0, 1) or (r.returncode != 0 and not lines and r.stderr.strip()):
        return lines, r.stderr.strip() or f"rc={r.returncode}"
    return lines, None


def selftest(yl: str) -> int:
    fixtures = {
        # (filename, content, expect_flagged)
        "truthy-key.yaml": ("no: 1\nyes: 2\n", True),          # Norway problem (key)
        "truthy-value.yaml": ("flag: yes\nother: on\n", True),  # truthy value
        "dup-key.yaml": ("a: 1\nb: 2\na: 3\n", True),           # silent 後勝ち merge
        "octal.yaml": ("mode: 0755\n", True),                    # implicit octal
        "syntax.yaml": ("a: [1, 2\n", True),                     # syntax error
        "clean.yaml": ('a: "no"\nb: true\nc: "0755"\n', False),  # quote 済 = clean
        "optout.yaml": ("# yamllint disable\nno: 1\n", False),   # 標準 opt-out
        "optout-rule.yaml": ("# yamllint disable rule:truthy\nno: 1\n", False),  # rule 限定 opt-out
        ".github/workflows/wf.yml": ("on: push\njobs: {}\n", False),  # workflow の on: は FP 除外
        ".github/workflows/dup.yml": ("on: push\na: 1\na: 2\n", True),  # 除外は truthy 限定 = dup は効く
    }
    passed = failed = 0
    with tempfile.TemporaryDirectory() as td:
        # git-crypt skip は collect_files 側の責務なので magic file を直接検証
        crypt = Path(td) / "locked.yaml"
        crypt.write_bytes(GITCRYPT_MAGIC + b"\x00junk")
        if open(crypt, "rb").read(10).startswith(GITCRYPT_MAGIC):
            passed += 1
        else:
            failed += 1
            print("  FAIL: git-crypt magic 判定")
        for name, (content, expect) in fixtures.items():
            p = Path(td) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            lines, err = run_lint(yl, [str(p)])
            flagged = bool(lines)
            if flagged == expect:
                passed += 1
            else:
                failed += 1
                print(f"  FAIL: {name} expect flagged={expect} got {lines or err}")
    print(f"selftest: {passed} passed, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    yl = find_yamllint()
    if yl is None:
        print("SKIP: yamllint 未 install (pip install yamllint) — YAML hazard lint を飛ばす")
        return 0
    if "--selftest" in sys.argv:
        return selftest(yl)
    root = Path(os.environ.get("CLAUDE_YAML_LINT_ROOT", os.path.expanduser("~/Claude")))
    files = collect_files(root)
    if not files:
        print(f"SKIP: {root} 配下に lint 対象の git repo yaml が無い (= fleet 不在環境、 selftest が発火面)")
        return 0
    lines, err = run_lint(yl, files)
    if err:
        # config 破損等の実行エラーは env 依存 SKIP でなく検査自体の故障 = loud に fail
        print(f"🔴 yamllint 実行エラー (検査が回っていない): {err}")
        return 1
    if lines:
        print(f"🔴 YAML hazard {len(lines)} 件 (truthy / dup-key / octal / syntax):")
        for l in lines:
            print("  " + l)
        return 1
    print(f"OK: {len(files)} yaml files clean (truthy / dup-key / octal / syntax)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
