#!/usr/bin/env python3
"""check-overleaf-drift.py — Overleaf 連携 repo の drift / 整備漏れ検出器。

「Overleaf 側が正本」の repo で GitHub pull だけして「最新」と誤信する構造的死角を塞ぐ。
設計動機 = ある物理共著 paper repo で 3 ヶ月の silent drift + project ID 喪失が発覚した
RCA (= 三例目 2026-06-12。 実例 ledger と sync script 契約の正本 =
conventions/overleaf-integration.md)。

検出 (= ~/Claude 直下の各 repo の scripts/overleaf-sync.sh --status を並列実行して分類):

- CRITICAL: PROJECT_ID 未設定 (= ID 喪失事故そのもの。 user が Overleaf web →
  Menu → Git から ID を回収して script に記入するまで吠え続ける)
- WARN: behind > 0 (= Overleaf に未取込みの共著者編集あり → merge 等で取込み)
- WARN: status 取得失敗 / timeout (= 検証不能 ≠ 同期済。 fail-loud)
- WARN: CLAUDE.md に Overleaf 連携の記述があるのに sync script 未整備
  (= ID 喪失リスク予備軍。 将来の新規 paper repo がここに引っかかる)
- INFO: 未 clone / 未 bootstrap (= 新マシン。 sync script 1 回実行で解消)
- INFO: token 未復元 (= ~/.secrets/overleaf-token の配置を案内)
- INFO: ahead > 0 (= local に Overleaf 未反映 commit。 push は user 明示 OK 必須)。
  status 行に ahead-expected marker があれば抑制 (= 管理 commit を push しない恒常
  ahead 運用の repo が dashboard を恒久 INFO で汚さないための契約、 template の
  AHEAD_EXPECTED=1)

skip (silent): script 出力に DEPRECATED (= Overleaf 連携を廃止した repo の標準 marker)。

使い方: 個人層の dashboard / cron の末尾から呼ぶ。 finding 0 件なら silent。
--root DIR で走査 root 変更 (既定 ~/Claude)、 --selftest 内蔵 (fixture repo 群で分類検証)。
sync script の契約 (--status が "ahead=N behind=M" を出す / exit 2 = 設定不足 /
廃止は DEPRECATED 表示) の正本 = conventions/overleaf-integration.md#sync-script-contract。
template = templates/overleaf-sync.sh.template。
"""

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
DEFAULT_ROOT = HOME / "Claude"
STATUS_TIMEOUT = 30  # network fetch を含むので余裕を持つ
SCRIPT_NAMES = ("overleaf-sync.sh", "sync-overleaf.sh")  # 後者 = 旧命名の互換
# CLAUDE.md で「Overleaf が同期対象」を示す高信号 pattern (誤爆を避け 1 行内共起のみ)
MENTION_RE = re.compile(r"Overleaf.{0,30}(正本|同期|連携|live git clone)", re.IGNORECASE)
# 機構そのものの説明行 (= 本検出器や規約を語る行) は連携の証拠にしない
# (= 三例目 sweep で発覚した自己参照偽陽性: 個人層 CLAUDE.md の検出器説明文に反応した)
META_RE = re.compile(r"drift|検出|契約")


def find_repos(root: Path):
    """(repo_dir, script_path or None) の列。 script があるか CLAUDE.md に言及がある repo。"""
    out = []
    self_home = Path(__file__).resolve()
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / ".git").exists():
            continue
        # 本検出器の home repo (= 機構の置き場、 規約 / template / installer を持つ) は
        # CLAUDE.md が構造的に「Overleaf 連携」 を言及し続けるため対象外
        # (= 三例目 sweep で発覚した自己参照偽陽性の第 2 形態。 META_RE では機構 home の
        # 全説明行を網羅できない)
        if d.resolve() in self_home.parents:
            continue
        script = None
        for name in SCRIPT_NAMES:
            p = d / "scripts" / name
            if p.is_file():
                script = p
                break
        mention = False
        claude_md = d / "CLAUDE.md"
        if claude_md.is_file():
            try:
                for line in claude_md.read_text(encoding="utf-8").splitlines():
                    if MENTION_RE.search(line) and not META_RE.search(line):
                        mention = True
                        break
            except Exception:
                mention = False
        if script or mention:
            out.append((d, script))
    return out


def run_status(script: Path):
    """--status を実行し (exit_code, combined_output) を返す。 timeout は (None, '')。"""
    try:
        r = subprocess.run(
            ["bash", str(script), "--status"],
            capture_output=True,
            text=True,
            timeout=STATUS_TIMEOUT,
            stdin=subprocess.DEVNULL,  # token 復元の interactive 起動を抑止
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return None, ""
    except Exception as e:
        return None, str(e)


def classify(repo: Path, script, code, out):
    """1 repo の status 結果を findings dict に変換 (= テスト可能に副作用分離)。"""
    findings = {"CRITICAL": [], "WARN": [], "INFO": []}
    name = repo.name
    if script is None:
        findings["WARN"].append(
            f"  - {name}: CLAUDE.md に Overleaf 連携の記述があるが scripts/overleaf-sync.sh"
            f" 未整備 (= project ID 喪失リスク。 overleaf-integration.md 規約で script 必須)"
        )
        return findings
    if "DEPRECATED" in out:
        return findings  # Overleaf 連携を廃止した repo
    if code is None:
        findings["WARN"].append(
            f"  - {name}: --status が timeout/実行失敗 (= 検証不能 ≠ 同期済。 network/token を確認)"
        )
        return findings
    if "PROJECT_ID 未設定" in out or "FIXME_PROJECT_ID" in out:
        findings["CRITICAL"].append(
            f"  - {name}: PROJECT_ID 未設定 (= ID 喪失状態。 回収 runbook ="
            f" overleaf-integration.md#id-recovery-runbook、 記入は install-overleaf-sync.sh"
            f" {repo.name} <URL|ID> の 1 コマンド)"
        )
        return findings
    if "overleaf-token" in out and code == 2:
        findings["INFO"].append(
            f"  - {name}: token 未復元 (= ~/.secrets/overleaf-token を配置。 発行は Overleaf"
            f" Account Settings → Git Integration、 復元手順は repo の sync script の案内に従う)"
        )
        return findings
    if "未 clone" in out or "未clone" in out:
        findings["INFO"].append(
            f"  - {name}: Overleaf clone 未 bootstrap (= bash {script.relative_to(repo)} で解消)"
        )
        return findings
    m = re.search(r"ahead=(\d+|\?) behind=(\d+|\?)", out)
    if not m:
        findings["WARN"].append(
            f"  - {name}: --status 出力を解析できない (exit={code}。 script の契約"
            f" \"ahead=N behind=M\" を確認)"
        )
        return findings
    ahead, behind = m.group(1), m.group(2)
    if behind not in ("0", "?") and int(behind) > 0:
        findings["WARN"].append(
            f"  - {name}: Overleaf に未取込みの編集 {behind} commits"
            f" (= 共著者の最新が local に無い。 bash {script.relative_to(repo)} --merge 等で取込み)"
        )
    if ahead not in ("0", "?") and int(ahead) > 0 and "ahead-expected" not in out:
        findings["INFO"].append(
            f"  - {name}: local が Overleaf より ahead={ahead} (= 反映には push が要るが"
            f" 共著者影響 → user 明示 OK 必須。 恒常 ahead 運用なら script の"
            f" AHEAD_EXPECTED=1 で本 INFO を抑制)"
        )
    if behind == "?" or ahead == "?":
        findings["WARN"].append(
            f"  - {name}: ahead/behind が確定できない (= upstream 設定 or fetch を確認)"
        )
    return findings


def collect(root: Path):
    repos = find_repos(root)
    findings = {"CRITICAL": [], "WARN": [], "INFO": []}
    if not repos:
        return findings

    def work(item):
        repo, script = item
        code, out = (0, "") if script is None else run_status(script)
        return classify(repo, script, code, out)

    with ThreadPoolExecutor(max_workers=4) as ex:
        for f in ex.map(work, repos):
            for sev in findings:
                findings[sev].extend(f[sev])
    return findings


def main() -> int:
    root = DEFAULT_ROOT
    if "--root" in sys.argv:
        root = Path(sys.argv[sys.argv.index("--root") + 1])
    findings = collect(root)
    if not any(findings.values()):
        return 0  # silent (= dashboard 慣習)
    print()
    print("=" * 64)
    print("📌 Overleaf drift (= Overleaf 正本 repo の未取込み編集 / 整備漏れ)")
    print("=" * 64)
    labels = {
        "CRITICAL": "🚨 CRITICAL (= project ID 喪失状態、 至急回収)",
        "WARN": "⚠️ WARN (= 未取込み drift / 検証不能 / 未整備)",
        "INFO": "ℹ️ INFO",
    }
    for sev in ("CRITICAL", "WARN", "INFO"):
        if findings[sev]:
            print(f"\n{labels[sev]} ({len(findings[sev])} 件):")
            for line in findings[sev]:
                print(line)
    print()
    print("規約 = claude-config/conventions/overleaf-integration.md (sync script 契約 + RCA)")
    print()
    return 0


def selftest() -> int:
    import tempfile

    fails = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def mk_repo(name, script_body=None, claude_md=""):
            d = root / name
            (d / ".git").mkdir(parents=True)
            if claude_md:
                (d / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
            if script_body is not None:
                (d / "scripts").mkdir()
                p = d / "scripts" / "overleaf-sync.sh"
                p.write_text(script_body, encoding="utf-8")
            return d

        # 1) drift あり (behind=3)
        mk_repo("r-drift", "#!/bin/bash\necho '[x] ahead=0 behind=3'\n")
        # 2) clean (behind=0) → finding 無し
        mk_repo("r-clean", "#!/bin/bash\necho '[x] ahead=0 behind=0'\n")
        # 3) ID 未設定 → CRITICAL
        mk_repo("r-noid", "#!/bin/bash\necho 'PROJECT_ID 未設定' >&2\nexit 2\n")
        # 4) deprecated → silent
        mk_repo("r-dep", "#!/bin/bash\necho 'DEPRECATED: Overleaf 廃止'\nexit 0\n")
        # 5) 言及あり script 無し → WARN
        mk_repo("r-mention", None, "# x\n- Overleaf と同期（Overleaf 側が正本）\n")
        # 6) token 無し → INFO
        mk_repo("r-token", "#!/bin/bash\necho '~/.secrets/overleaf-token が無い' >&2\nexit 2\n")
        # 7) ahead のみ → INFO
        mk_repo("r-ahead", "#!/bin/bash\necho '[x] ahead=2 behind=0'\n")
        # 7b) ahead だが marker で抑制 → silent (behind があれば behind は出る)
        mk_repo("r-aheadok", "#!/bin/bash\necho '[x] ahead=9 behind=0 ahead-expected'\n")
        # 8) 言及も script も無し → 対象外
        mk_repo("r-plain", None, "# 普通の repo\n")
        # 9) 機構の説明行のみ (= meta 言及、 個人層 dashboard 説明文型) → 対象外
        mk_repo(
            "r-meta",
            None,
            "- check-overleaf-drift.py: Overleaf drift 検出 (= 「Overleaf 側が正本」 repo の…)\n",
        )

        f = collect(root)
        blob = "\n".join(f["CRITICAL"] + f["WARN"] + f["INFO"])
        if not any("r-noid" in x for x in f["CRITICAL"]):
            fails.append("r-noid should be CRITICAL")
        if not any("r-drift" in x and "3 commits" in x for x in f["WARN"]):
            fails.append("r-drift behind=3 should be WARN")
        if not any("r-mention" in x and "未整備" in x for x in f["WARN"]):
            fails.append("r-mention should be WARN 未整備")
        if not any("r-token" in x for x in f["INFO"]):
            fails.append("r-token should be INFO")
        if not any("r-ahead" in x for x in f["INFO"]):
            fails.append("r-ahead should be INFO")
        for quiet in ("r-clean", "r-dep", "r-plain", "r-meta", "r-aheadok"):
            if quiet in blob:
                fails.append(f"{quiet} should be silent")
    if fails:
        print("SELFTEST FAIL:")
        for x in fails:
            print(f"  - {x}")
        return 1
    print("SELFTEST OK (10 fixtures, 11 assertions)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
