#!/usr/bin/env bash
# public-precommit-runner.test.sh — self-tests for the file-body pre-commit gate
#
# 設計動機: 2026-06-29 arxiv-digest archive 8 file が public-precommit-runner.sh
#   Tier B の substring FP で commit block。 word-boundary 化 (ASCII -wF / 非
#   ASCII -F) の root 修復に伴い、 (a) 既存 真陽性が hit し続ける + (b) 短 ASCII
#   term の embed FP が PASS する + (c) 非 ASCII term の substring 検出が
#   維持される、 の 3 invariant を test fixture で固定。
#
# 設計: runner を fresh temp git repo + mock personal layer で起動、 staged
#   file が leak token を含むかで exit code を確認。 layer 1 (claude-config
#   public) に置くので mock literal は claude-config/scripts/commit-msg-leak-
#   guard-runner.test.sh と同じ命名規約 (= MOCK_SECRET_TERM_ALPHA / NXYZ /
#   モック秘語) を使い、 layer 3 実 sensitive-terms.txt を絶対 embed しない
#   (= 2026-05-26 self-leak RCA、 hook-authoring.md#shared-matcher-mock-pattern)。
#
# 実行: bash public-precommit-runner.test.sh
#       全 pass で exit 0、 fail があれば exit 1

set -uo pipefail

RUNNER="$(cd "$(dirname "$0")" && pwd)/public-precommit-runner.sh"  # 絶対化: test は mock repo へ cd するため相対 path は壊れる (2026-07-10 fix)
[ -x "$RUNNER" ] || { echo "ERROR: $RUNNER not executable"; exit 1; }

PASS=0
FAIL=0
FAILED_CASES=""

TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

# ====================================================================
# Mock personal layer setup
# ====================================================================
MOCK_LAYER="$TMPDIR_TEST/mock-personal-layer"
mkdir -p "$MOCK_LAYER"
touch "$MOCK_LAYER/.claude-personal-layer"
echo "# mock personal layer" > "$MOCK_LAYER/CLAUDE.md"

# repos.md (Tier B 軸とは無関係だが find_personal_layer 側で必要に応じ参照)
cat > "$MOCK_LAYER/repos.md" << 'REPOS_EOF'
| repo | desc | visibility |
|---|---|---|
| `mockpriv-foo/` | mock private repo | private |
REPOS_EOF

# sensitive-terms.txt: ASCII (long + short) + 非 ASCII の三種
cat > "$MOCK_LAYER/sensitive-terms.txt" << 'TERMS_EOF'
MOCK_SECRET_TERM_ALPHA
NXYZ
モック秘語
TERMS_EOF

export CLAUDE_PERSONAL_LAYER="$MOCK_LAYER"

# ====================================================================
# Mock public repo (= .claude/public-repo.marker + staged file)
# ====================================================================
MOCK_REPO="$TMPDIR_TEST/mock-public-repo"
mkdir -p "$MOCK_REPO/.claude"
cat > "$MOCK_REPO/.claude/public-repo.marker" << 'MARKER_EOF'
# claude-public-repo-marker (mock)
MARKER_EOF

(
  cd "$MOCK_REPO"
  git init -q -b main
  git config user.email "noreply@github.com"
  git config user.name "test"
  echo "init" > .gitignore
  git add .gitignore .claude/public-repo.marker
  git commit -q -m "init"
) || { echo "ERROR: mock repo init failed"; exit 1; }

# ====================================================================
# Helpers
# ====================================================================
# expect_block <name> <file_content>: file を staged して runner が exit=1
expect_block() {
  local name="$1" content="$2"
  local fname stdout_out exit_code
  fname="testfile-$RANDOM.txt"
  printf '%s' "$content" > "$MOCK_REPO/$fname"
  (
    cd "$MOCK_REPO"
    git add "$fname" 2>/dev/null
    "$RUNNER" >/dev/null 2>&1
    echo "$?"
    git reset HEAD "$fname" >/dev/null 2>&1
    rm -f "$fname"
  ) > "$TMPDIR_TEST/_rc.txt"
  exit_code="$(cat "$TMPDIR_TEST/_rc.txt")"
  if [ "$exit_code" != "1" ]; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [exit!=1] $name (exit=$exit_code)\n"
    return
  fi
  PASS=$((PASS+1))
}

# expect_pass <name> <file_content>: file を staged して runner が exit=0
expect_pass() {
  local name="$1" content="$2"
  local fname exit_code
  fname="testfile-$RANDOM.txt"
  printf '%s' "$content" > "$MOCK_REPO/$fname"
  (
    cd "$MOCK_REPO"
    git add "$fname" 2>/dev/null
    "$RUNNER" >/dev/null 2>&1
    echo "$?"
    git reset HEAD "$fname" >/dev/null 2>&1
    rm -f "$fname"
  ) > "$TMPDIR_TEST/_rc.txt"
  exit_code="$(cat "$TMPDIR_TEST/_rc.txt")"
  if [ "$exit_code" != "0" ]; then
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  [exit!=0] $name (exit=$exit_code)\n"
    return
  fi
  PASS=$((PASS+1))
}

# ====================================================================
# Tier B BLOCK cases (真陽性 = word-boundary 化後も検出)
# ====================================================================
expect_block "block-long-ascii-as-word" \
  "config: MOCK_SECRET_TERM_ALPHA = abc"

expect_block "block-short-ascii-as-word" \
  "ship NXYZ milestone"

expect_block "block-nonascii-substring" \
  "ここにモック秘語が含まれる"

expect_block "block-nonascii-embed-in-cjk" \
  "プレフィックスモック秘語サフィックス"

# ====================================================================
# Tier B PASS cases (FP class = word-boundary 化で suppress されるべき)
# ====================================================================
# 短 ASCII term の substring embed (= arxiv-digest FP class の構造的代表)
expect_pass "pass-short-ascii-embed-prefix" \
  "audit XNXYZ component"

expect_pass "pass-short-ascii-embed-suffix" \
  "audit NXYZX component"

expect_pass "pass-short-ascii-embed-both" \
  "audit XNXYZX component"

expect_pass "pass-short-ascii-embed-alnum" \
  "audit NXYZ123 component"

expect_pass "pass-short-ascii-embed-underscore" \
  "audit NXYZ_FOO component"

# 長 ASCII term の substring embed
expect_pass "pass-long-ascii-embed" \
  "var XMOCK_SECRET_TERM_ALPHAX = 1"

# clean (= leak なし)
expect_pass "pass-clean" \
  "just some normal text"

# Tier A email: RFC 2606 予約 doc 用 domain は allowlist (2026-08-28、 selftest
# fixture の alt@example.com が block された FP を契機に追加)
expect_pass "pass-email-example-domain" \
  "fixture user = alt@example.com / cli-base@example.org"

# 実 domain の email は引き続き block (= allowlist 拡張の regression 逆側)。
# ⚠️ literal を source に書くと本 repo の pre-commit scan 自身に block される
# (実測) ので shell 連結で組む (= shared-matcher-mock-pattern と同じ理屈)
expect_block "block-email-real-domain" \
  "contact someone@gm""ail.com for details"

# ====================================================================
echo ""
echo "=== public-precommit-runner self-test ==="
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
