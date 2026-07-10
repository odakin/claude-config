#!/bin/bash
# commit-msg-leak-guard-runner.test.sh — 上記 runner の self-test（15 case、 BLOCK / PASS / merge skip 等）
# commit-msg-leak-guard-runner.test.sh — self-tests for the git-side runner
#
# 設計: runner に git commit-msg hook 互換の引数 ($1=msg file path、 $2=
#       source 種別) を渡し、 exit code + stderr を確認。 claude-code 側 hook
#       (= odakin-prefs/hooks/commit-msg-leak-guard.test.sh) と相補。
#
# 実行: bash commit-msg-leak-guard-runner.test.sh
#       全 pass で exit 0、 fail があれば exit 1
#
# 重要 (2026-05-26 sanitize): 本 file は layer 1 (claude-config public) に
# 置かれるため、 test case の literal に **実 private repo 名を embed しては
# ならない**。 mock personal layer (= temp dir + 偽 repos.md / 偽
# sensitive-terms.txt) を CLAUDE_PERSONAL_LAYER env var 経由で injection し、
# matcher が偽 private repo 名 (= `mockpriv-foo` 等) を検出することを verify
# する。 実 private repo 名を検出する責任は odakin-prefs/hooks/
# commit-msg-leak-guard.test.sh が負う (= layer 3 private、 mention OK)。

set -uo pipefail

RUNNER="$(dirname "$0")/commit-msg-leak-guard-runner.sh"
[ -x "$RUNNER" ] || { echo "ERROR: $RUNNER not executable"; exit 1; }

PASS=0
FAIL=0
FAILED_CASES=""

TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

# ====================================================================
# Mock personal layer setup
# matcher が層 3 から拾う 2 file (= repos.md + sensitive-terms.txt) を
# 偽 content で provisioning、 CLAUDE_PERSONAL_LAYER で injection
# ====================================================================
MOCK_LAYER="$TMPDIR_TEST/mock-personal-layer"
mkdir -p "$MOCK_LAYER"
# find_personal_layer() の検出条件: 該当 dir に .claude-personal-layer + CLAUDE.md
touch "$MOCK_LAYER/.claude-personal-layer"
echo "# mock personal layer" > "$MOCK_LAYER/CLAUDE.md"

# 偽 repos.md (= matcher (b) が parse する table format)
# format: | `<repo>/` | <desc> | private |
cat > "$MOCK_LAYER/repos.md" << 'REPOS_EOF'
| repo | desc | visibility |
|---|---|---|
| `mockpriv-foo/` | mock private repo foo | private |
| `mockpriv-bar/` | mock private repo bar | private |
| `mockpriv-with-numbers-42/` | another mock private | private |
| `mockpriv-multi-word-name/` | multi-word mock | private |
| `mockpub-public/` | mock public, hook target | public |
| `gmail-mcp-config/` | example allowlist 1 | private |
| `odakin-prefs/` | example allowlist 2 | private |
REPOS_EOF

# 偽 sensitive-terms.txt (= matcher (a) が grep -F する literal list)
# - long ASCII term: word-boundary 化前後で挙動が変わらない (= 「embed されにくい」)
# - 短 ASCII term `NXYZ` (4 char): word-boundary 化の対象 (= 2026-06-29
#   arxiv-digest FP class の検出 fixture、 embed 内では match しないこと)
# - 非 ASCII term: substring 維持 (= 日本語 boundary ill-defined)
cat > "$MOCK_LAYER/sensitive-terms.txt" << 'TERMS_EOF'
MOCK_SECRET_TERM_ALPHA
mock-confidential-keyword
NXYZ
モック秘語
TERMS_EOF

export CLAUDE_PERSONAL_LAYER="$MOCK_LAYER"

# ====================================================================
# Helpers
# ====================================================================
# expect_block <case_name> <message_content> [source]
# 本 test は **claude-config 内で実行されること** を assume (= 親 repo に
# .claude/public-repo.marker あり、 runner が marker check を pass する)。
expect_block() {
  local name="$1" content="$2" source="${3:-message}"
  local msg_file stderr_out exit_code
  msg_file="$TMPDIR_TEST/msg-$RANDOM.txt"
  printf '%s' "$content" > "$msg_file"

  stderr_out="$("$RUNNER" "$msg_file" "$source" 2>&1 >/dev/null)"
  exit_code=$?

  if [ "$exit_code" != "1" ]; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [exit!=1] $name (exit=$exit_code)\n"
    return
  fi
  if ! echo "$stderr_out" | grep -q "commit rejected"; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [no-reject-msg] $name\n"
    return
  fi
  PASS=$((PASS+1))
}

# expect_pass: exit 0 + stderr 空
expect_pass() {
  local name="$1" content="$2" source="${3:-message}"
  local msg_file stderr_out stdout_out exit_code
  msg_file="$TMPDIR_TEST/msg-$RANDOM.txt"
  printf '%s' "$content" > "$msg_file"

  stderr_out="$("$RUNNER" "$msg_file" "$source" 2>&1 >/dev/null)"
  stdout_out="$("$RUNNER" "$msg_file" "$source" 2>/dev/null)"
  exit_code=$?

  if [ "$exit_code" != "0" ]; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [exit!=0] $name (exit=$exit_code)\n"
    return
  fi
  if [ -n "$stderr_out" ]; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [unexpected-stderr] $name: $(echo "$stderr_out" | head -1)\n"
    return
  fi
  if [ -n "$stdout_out" ]; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [unexpected-stdout] $name\n"
    return
  fi
  PASS=$((PASS+1))
}

# cd to claude-config (= 親 repo に marker あり、 runner が marker pass する)
cd "$(dirname "$RUNNER")/.." || exit 1
[ -f ".claude/public-repo.marker" ] || {
  echo "ERROR: test expects to run from claude-config (marker not found)"
  exit 1
}

# ====================================================================
# BLOCK cases (= 偽 private repo 名 / 偽 sensitive term / path pattern)
# ====================================================================
expect_block "block-priv-repo-name-simple" \
  "fix mockpriv-foo/CLAUDE.md path"

expect_block "block-priv-repo-with-numbers" \
  "mockpriv-with-numbers-42: SESSION.md update"

expect_block "block-priv-repo-multiword" \
  "Add mockpriv-multi-word-name marker macro"

expect_block "block-second-priv-repo" \
  "mockpriv-bar セッションで作業"

expect_block "block-multiline" \
  "first line short
body with mockpriv-foo mention
end"

expect_block "block-amend-source" \
  "fix mockpriv-foo oversight" \
  "commit"

# (a) sensitive-terms literal
expect_block "block-sensitive-literal" \
  "update MOCK_SECRET_TERM_ALPHA configuration"

expect_block "block-sensitive-literal-kebab" \
  "rotate mock-confidential-keyword settings"

# 2026-06-29 word-boundary regression suite
# (a-1) 短 ASCII term: standalone word は依然 hit
expect_block "block-short-ascii-word" \
  "ship NXYZ milestone today"

# (a-2) 非 ASCII term: substring 維持 ゆえ word 外の embed でも hit
expect_block "block-nonascii-substring" \
  "ここにモック秘語があります"

expect_block "block-nonascii-embed-in-cjk" \
  "プレフィックスモック秘語サフィックス"

# (c) ~/Claude/<X>/ path pattern (= matcher で (b) が hit する条件下、
# matcher 実装は (b) hit 時 (c) skip)。 (c) を独立に観るなら repo 名 を
# 含まない path-only message が必要だが、 path 内に repo 名が出る限り (b)
# が先に hit する。 そのため (c) は (b) 経由で間接的に cover される)。

# ====================================================================
# PASS cases (= clean / allowlist / merge skip / squash skip / empty)
# ====================================================================
expect_pass "pass-clean-typo" \
  "fix typo"

expect_pass "pass-allowlist-gmail-mcp-config" \
  "fix gmail-mcp-config oauth flow"

expect_pass "pass-allowlist-odakin-prefs" \
  "odakin-prefs: add new hook"

expect_pass "pass-public-claude-config" \
  "claude-config: refine convention"

expect_pass "pass-public-mockpub" \
  "mockpub-public: feature add"

# merge source = skip (= mockpriv-foo leak 含むが scope 外)
expect_pass "skip-merge-source" \
  "Merge branch 'feature' (with mockpriv-foo)" \
  "merge"

# squash source = skip
expect_pass "skip-squash-source" \
  "squashed commits (with mockpriv-foo)" \
  "squash"

# git scrubs comment lines (^#) so we should too
expect_pass "skip-comment-only-leak" \
  "fix typo
# Please enter the commit message for your changes (mockpriv-foo related)
# Lines starting with '#' will be ignored."

# empty message = skip
expect_pass "skip-empty-message" \
  ""

# 2026-06-29 word-boundary regression suite (PASS side = FP class)
# (a-3) 短 ASCII term の substring embed: word-boundary 化で hit しないこと
#   (= 旧 substring match では "NXYZ" を含む "XNXYZX" 等で誤 BLOCK されていた、
#    arxiv-digest 6/24_ogawa.json FP の構造的代表)
expect_pass "skip-short-ascii-embed-prefix" \
  "audit XNXYZ component"

expect_pass "skip-short-ascii-embed-suffix" \
  "audit NXYZX component"

expect_pass "skip-short-ascii-embed-both" \
  "audit XNXYZX component"

expect_pass "skip-short-ascii-embed-alnum" \
  "audit NXYZA component"

# underscore は grep -w で word char ゆえ、 NXYZ_FOO の embed も match しない
expect_pass "skip-short-ascii-embed-underscore" \
  "audit NXYZ_FOO component"

# ====================================================================
echo ""
echo "=== commit-msg-leak-guard-runner self-test ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "Failed cases:"
  printf "$FAILED_CASES"
  exit 1
fi
echo "OK"
exit 0
