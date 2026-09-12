#!/usr/bin/env bash
# run-all-checks.sh — claude-config の全機械検査を 1 コマンドで回す (検査リストの SoT)
#
# 正本: <claude-config>/scripts/run-all-checks.sh
# 呼び元: (a) ローカル手動 / (b) .github/workflows/checks.yml (CI は本 script を呼ぶだけ —
#         検査リストをここに一元化し、 CI yml と local の drift を design-out する)
#
# 検査内容:
#   1. 自動生成 index の同期   (generate-doc-index.py --check-all)
#   1b. 生成 doc の同期        (generate-tree.py --check: CLAUDE.md tree / CONVENTIONS.md 列挙 / conventions/README.md)
#   2. 手動保守 index / script inventory / Codex integration contract の整合
#   3. python validator selftest 群 (--selftest を持つ全 script を自動発見)
#   4. bash test 群            (hooks/*.test.sh + scripts/**/*.test.sh)
#   5. bash 構文検査           (setup.sh + hooks/*.sh + scripts/*.sh の bash -n)
#   6. merge conflict marker 残置検査 (tracked file 全対象の git grep)
#
# 環境依存 test の扱い: 各 .test.sh / --selftest は自分の依存 (jq / macOS 固有 tool /
# owner transcript) が無い時に SKIP を出して exit 0 する責務を持つ (silent skip 禁止、
# skip 理由は test 自身が出力する)。 本 runner は集計のみ。
#
# 失敗の自己申告: set -e の test で bare `[ ... ]` / `grep -q` を assertion にするなら
# scripts/lib/test-err-trap.sh を source して、 落ちた行と command を stderr に出す
# (無言の exit 1 だと CI log には下の "✗ test: <name>" しか残らない)。 BSD/GNU 差は
# push 前に scripts/with-gnu-userland.sh で手元再現できる。
# 正本 = conventions/hook-authoring.md#set-e-test-failure-report
#
# bash 3.2 compatible。 exit 1 = いずれかの検査が fail。
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0; FAILED_NAMES=""

run() {
    # $1 = label, 残り = command
    local label="$1"; shift
    echo ""
    echo "── $label"
    if "$@"; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1)); FAILED_NAMES="$FAILED_NAMES
  ✗ $label"
    fi
}

# 1. 自動生成 index 同期
run "index sync (--check-all)" python3 scripts/generate-doc-index.py --check-all "$ROOT"

# 1b. 生成 doc の同期 (CLAUDE.md 構造 tree / CONVENTIONS.md 列挙 / conventions/README.md、
#     源 = conventions/*.md 冒頭 doc-meta + scripts/hooks の header 1 行目)
run "generated docs sync (generate-tree.py --check)" python3 scripts/generate-tree.py --check

# 2. 手動保守 index (office-automation ほか、 validator が対象を自分で解決)
run "office-automation index" python3 scripts/check-office-automation-index.py
run "scripts inventory" python3 scripts/check-script-index.py . --index scripts/README.md --scan scripts
run "hooks inventory" python3 scripts/check-script-index.py . --index hooks/README.md --scan hooks
run "Codex hook inventory" python3 scripts/check-script-index.py . --index codex/PARITY.md --scan codex/hooks
run "Codex integration contract" python3 scripts/check-codex-integration.py --check
# 2b. markdown の #anchor を PATH で解決して着地先に実在するか (本 repo 内の自己参照を含む)。
#     check-inbound-refs は設計上 target repo の内部 ref を見ないので、その穴を塞ぐ別の目。
#     --base . = 本 repo だけを走査 (CI に兄弟 repo が無くても、着地先の無い cross-repo link は skip)。
#     起源 = 2026-09-13、分割 6 日後に壊れた自己参照 21 件 (convention-design-principles #self-reference-is-nobodys-business)
run "markdown anchors resolve (check-md-anchors)" python3 scripts/check-md-anchors.py --base "$ROOT" --quiet
#     相対 link の着地先 file の実在。直せる型 (../ の段数ずれ・git が記録した改名) が 1 件でもあれば FAIL、
#     後継の無い削除や数式・散文の誤認は報告のみ。起源 = 2026-09-13 fleet で段数ずれ 91 + 改名 20 を修正
#     (convention-design-principles #link-target-rot)
run "markdown link targets exist (fix-md-links --strict)" python3 scripts/fix-md-links.py --base "$ROOT" --strict --quiet
# ↓ 中身の検査 (generate-tree / index / codex contract) は上と重複するが、 hook script 自体が
#   実行可能で exit 0 する smoke test として意図的に残す (重複削除で hook の壊れが盲点化する)
run "claude-config pre-commit extra" bash .claude/pre-commit-extra.sh

# 3. --selftest を持つ python script を自動発見して全実行
#    (発見条件 = scripts/ 直下 *.py で本文に --selftest を含む。 hardcode リストを持たない)
for py in scripts/*.py; do
    [ -f "$py" ] || continue
    if grep -q -- "--selftest" "$py"; then
        run "selftest: $(basename "$py")" python3 "$py" --selftest
    fi
done

# 4. bash test 群
for t in hooks/*.test.sh scripts/*.test.sh scripts/lib/*.test.sh codex/hooks/*.test.sh; do
    [ -f "$t" ] || continue
    run "test: $(basename "$t")" bash "$t"
done

# 5. bash 構文検査 (実行はしない)
syntax_fail=0
for sh in setup.sh hooks/*.sh scripts/*.sh scripts/lib/*.sh .claude/pre-commit-extra.sh; do
    [ -f "$sh" ] || continue
    if ! bash -n "$sh" 2>/dev/null; then
        echo "  ✗ bash -n fail: $sh"
        syntax_fail=1
    fi
done
run "bash -n (all shell scripts)" test "$syntax_fail" -eq 0

# 6. merge conflict marker 残置 (tracked file 全対象。 実事故 2026-07-10 = conflict marker 入りの
#    conventions/*.md を commit+push、 検出器ゼロで同日 review まで気づかず。 pattern は {7} 表記 =
#    本 script 自身の自己 match 回避。 marker を例として引用したい doc は行頭を避ける / indent する)
check_conflict_markers() {
    local hits
    hits="$(git grep -n -E '^(<{7}|>{7}) ' 2>/dev/null || true)"
    if [ -n "$hits" ]; then
        echo "$hits"
        echo "  ✗ merge conflict marker が tracked file に残置"
        return 1
    fi
    return 0
}
run "conflict markers (git grep)" check_conflict_markers

echo ""
echo "════════════════════════════════════"
echo " run-all-checks: PASS=$PASS FAIL=$FAIL"
[ -n "$FAILED_NAMES" ] && echo "$FAILED_NAMES"
echo "════════════════════════════════════"
exit $((FAIL > 0 ? 1 : 0))
