#!/usr/bin/env bash
# office-staging.test.sh — office-staging.sh + office_staging.py の self-test (hermetic、 Office 不要、 fake HOME)
#
# 検査: (1) 無効化 env / override / default の root 解決 (2) stage → basename 保持 + .source provenance
#       (3) cleanup は root 外を拒否 (4) prune は古い subdir だけ消す (5) bash 版と python 版の root が一致 (= drift 検出)
# 実 Office を起こす e2e は scope 外 (= 実機検証 ledger は office-automation.md#office-pregranted-staging-dir)。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/office-staging.sh"
PY="$HERE/office_staging.py"
[ -f "$LIB" ] || { echo "SKIP: lib not found: $LIB"; exit 0; }
[ -f "$PY" ] || { echo "SKIP: python lib not found: $PY"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not found"; exit 0; }
# shellcheck source=/dev/null
. "$LIB"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
mkdir -p "$HOME"
unset CLAUDE_OFFICE_STAGING CLAUDE_OFFICE_STAGING_DIR

PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "✅ $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "❌ $1"; }
check() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3 (expected [$2], got [$1])"; fi; }

py_root() { PYTHONPATH="$HERE" python3 -c 'import office_staging; print(office_staging.staging_root() or "")'; }

# T1: 無効化 env → 両実装とも空
CLAUDE_OFFICE_STAGING=0 office_staging_root >"$TMP/r1" 2>&1; check "$(cat "$TMP/r1")" "" "T1 bash: CLAUDE_OFFICE_STAGING=0 → 空"
check "$(CLAUDE_OFFICE_STAGING=0 py_root)" "" "T1 python: CLAUDE_OFFICE_STAGING=0 → 空"

# T2: Office 未 install (fake HOME に group container 無し) → 空 (非 macOS も空)
check "$(office_staging_root)" "" "T2 bash: group container 不在 → 空"
check "$(py_root)" "" "T2 python: group container 不在 → 空"

# T3: fake group container を置く → macOS なら root、 非 macOS なら空。 両実装で一致が本質
mkdir -p "$HOME/Library/Group Containers/UBF8T346G9.Office"
b3="$(office_staging_root)"; p3="$(py_root)"
check "$p3" "$b3" "T3 default root: bash == python ([$b3])"
if [ "$(uname)" = "Darwin" ]; then
    check "$b3" "$HOME/Library/Group Containers/UBF8T346G9.Office/claude-office-staging" "T3 macOS default root = group container 配下"
else
    check "$b3" "" "T3 非 macOS → 空 (in-place)"
fi

# T4: override → 両実装一致 + stage / provenance / cleanup
export CLAUDE_OFFICE_STAGING_DIR="$TMP/override-root"
check "$(office_staging_root)" "$TMP/override-root" "T4 bash override root"
check "$(py_root)" "$TMP/override-root" "T4 python override root"
printf 'hello' > "$TMP/案件 form.docx"
if office_stage_file "$TMP/案件 form.docx"; then
    check "$(basename "$OFFICE_STAGED")" "案件 form.docx" "T4 staged basename 保持"
    check "$(cat "$OFFICE_STAGED")" "hello" "T4 staged content"
    check "$(cat "$OFFICE_STAGE_DIR/.source")" "$TMP/案件 form.docx" "T4 .source provenance"
    case "$OFFICE_STAGE_DIR" in "$TMP/override-root"/*) ok "T4 subdir は root 配下" ;; *) bad "T4 subdir が root 外: $OFFICE_STAGE_DIR" ;; esac
    d4="$OFFICE_STAGE_DIR"
    office_stage_cleanup
    [ ! -e "$d4" ] && ok "T4 cleanup で subdir 消滅" || bad "T4 cleanup 後も残存: $d4"
    check "${OFFICE_STAGE_DIR:-}" "" "T4 cleanup 後 OFFICE_STAGE_DIR 空"
else
    bad "T4 office_stage_file が失敗"
fi

# T5: 無効化時は stage が rc=1 + 変数空 (= 呼び出し側 in-place 分岐)
if CLAUDE_OFFICE_STAGING=0 office_stage_file "$TMP/案件 form.docx"; then bad "T5 無効化でも stage された"; else ok "T5 無効化で rc=1"; fi
check "${OFFICE_STAGED:-}" "" "T5 無効化で OFFICE_STAGED 空"

# T6: cleanup は root 外を拒否
mkdir -p "$TMP/outside/x"; OFFICE_STAGE_DIR="$TMP/outside/x"
office_stage_cleanup 2>/dev/null
[ -d "$TMP/outside/x" ] && ok "T6 root 外は削除拒否" || bad "T6 root 外を削除してしまった"

# T7: prune は古い subdir だけ消す (bash + python)
mkdir -p "$TMP/override-root/old-1" "$TMP/override-root/new-1"
touch -t 202001010000 "$TMP/override-root/old-1"
office_stage_prune 7
[ ! -e "$TMP/override-root/old-1" ] && ok "T7 bash prune: 古い subdir 削除" || bad "T7 bash prune: 古い subdir 残存"
[ -d "$TMP/override-root/new-1" ] && ok "T7 bash prune: 新しい subdir 保持" || bad "T7 bash prune: 新しい subdir を消した"
mkdir -p "$TMP/override-root/old-2"; touch -t 202001010000 "$TMP/override-root/old-2"
PYTHONPATH="$HERE" python3 -c 'import office_staging; office_staging.prune(7)'
[ ! -e "$TMP/override-root/old-2" ] && ok "T7 python prune: 古い subdir 削除" || bad "T7 python prune: 古い subdir 残存"
[ -d "$TMP/override-root/new-1" ] && ok "T7 python prune: 新しい subdir 保持" || bad "T7 python prune: 新しい subdir を消した"

# T8: python Stage: copy / copy_back / 正常終了 cleanup / 例外時 keep
PYTHONPATH="$HERE" python3 - "$TMP" <<'EOF' && ok "T8 python Stage contract" || bad "T8 python Stage contract"
import os, sys
from office_staging import Stage
tmp = sys.argv[1]
book = os.path.join(tmp, "book.xlsx"); img = os.path.join(tmp, "seal.png")
open(book, "w").write("B"); open(img, "w").write("I")
with Stage(book, img) as st:
    sb, si = st.paths
    assert st.active and os.path.dirname(sb) == st.dir and os.path.basename(sb) == "book.xlsx", st.paths
    assert open(os.path.join(st.dir, ".source")).read().split("\n")[:2] == [book, img]
    open(sb, "w").write("B2")
    st.copy_back(sb, book)
    d = st.dir
assert open(book).read() == "B2", "copy_back failed"
assert not os.path.exists(d), "cleanup failed"
try:
    with Stage(book) as st:
        d = st.dir
        raise RuntimeError("boom")
except RuntimeError:
    pass
assert os.path.isdir(d), "failure dir must be kept"
os.environ["CLAUDE_OFFICE_STAGING"] = "0"
with Stage(book) as st:
    assert not st.active and st.paths == [book], "in-place fallback"
EOF

echo "--- office-staging.test: PASS=$PASS FAIL=$FAIL ---"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
