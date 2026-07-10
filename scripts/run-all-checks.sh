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
#   2. 手動保守 index の整合   (check-office-automation-index.py: dangling/orphan)
#   3. python validator selftest 群 (--selftest を持つ全 script を自動発見)
#   4. bash test 群            (hooks/*.test.sh + scripts/**/*.test.sh)
#   5. bash 構文検査           (setup.sh + hooks/*.sh + scripts/*.sh の bash -n)
#   6. merge conflict marker 残置検査 (tracked file 全対象の git grep)
#
# 環境依存 test の扱い: 各 .test.sh / --selftest は自分の依存 (jq / macOS 固有 tool /
# owner transcript) が無い時に SKIP を出して exit 0 する責務を持つ (silent skip 禁止、
# skip 理由は test 自身が出力する)。 本 runner は集計のみ。
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

# 3. --selftest を持つ python script を自動発見して全実行
#    (発見条件 = scripts/ 直下 *.py で本文に --selftest を含む。 hardcode リストを持たない)
for py in scripts/*.py; do
    [ -f "$py" ] || continue
    if grep -q -- "--selftest" "$py"; then
        run "selftest: $(basename "$py")" python3 "$py" --selftest
    fi
done

# 4. bash test 群
for t in hooks/*.test.sh scripts/*.test.sh scripts/lib/*.test.sh; do
    [ -f "$t" ] || continue
    run "test: $(basename "$t")" bash "$t"
done

# 5. bash 構文検査 (実行はしない)
syntax_fail=0
for sh in setup.sh hooks/*.sh scripts/*.sh scripts/lib/*.sh; do
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
