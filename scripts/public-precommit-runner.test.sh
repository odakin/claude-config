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
| `odakin-prefs/` | allowlisted (例外 list) | private |
| `email-office/` | allowlisted (例外 list) | private |
| `health/` | allowlisted (例外 list) | private |
| `agent-board/` | allowlisted (例外 list) | private |
| `space-rock-diner/` | allowlisted (例外 list) | private |
REPOS_EOF
# ↑ 例外 list の名前も「非公開」として並べる。並べないと allowlist の test は
#   allowlist を外しても通ってしまう (= 2026-09-14 に実測、それまでの allowlist test は飾りだった)

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

# ====================================================================
# Tier A: home 直下の絶対 path (macOS/Linux + Windows)
# 実測: Windows 形 (`C:\Users\<name>`) が抜けていて、 別マシンで書かれた
# build spec の中の username が public repo に残っていた
# ====================================================================
# ⚠️ fixture の path を literal で書かない (= この test file 自身が Tier A で落ちる、
# docs/convention-design-principles.md#detector-fires-on-its-own-signal)。 実行時に組み立てる
A_UNIX="$(printf '/%s/someone/proj' Users)"
A_WIN_BS="$(printf 'C:\\%s\\Someone\\proj' Users)"
A_WIN_SL="$(printf 'D:/%s/Someone/proj' Users)"
# retina asset の file 名は email ではない (実測: vendored な UI asset で大量に発火した)
expect_pass "pass-retina-asset-name" \
  "icon: TrackCurvesButtonDisabled@2x.png"
# ⚠️ fixture の address も literal で書かない (= この test file 自身が Tier A で落ちる)
REAL_MAIL="$(printf 'someone@%s.example.jp' somewhere)"
expect_block "block-real-email-still" "contact: $REAL_MAIL"

expect_block "block-abs-path-unix"              "p = '$A_UNIX'"
expect_block "block-abs-path-windows-backslash" "p = r'$A_WIN_BS'"
expect_block "block-abs-path-windows-slash"     "p = \"$A_WIN_SL\""
expect_pass "pass-users-without-drive" \
  "docs: see the Users section of the manual"

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

# ssh remote の user 部 (git@<host>:owner/repo) は email でない = allowlist (2026-09-12、
# CI 検出器の selftest fixture の ssh URL が block された FP を契機に追加)。 literal は
# 旧 allowlist の runner に block されるので連結で組む
expect_pass "pass-ssh-remote-user" \
  "origin = git""@github.com:o/a.git / git""@gitlab.com:o/b.git / git""@bitbucket.org:o/c.git"

# 同じ git@ でも code host 以外の domain は block のまま (= allowlist 拡張の regression 逆側)
expect_block "block-git-at-other-domain" \
  "mail git""@gm""ail.com please"

# --------------------------------------------------------------------
# Tier C: file 本文の非例外 private repo 名 (2026-09-12 追加)
# 2026-09-12 まで repo 名を見るのは commit message 側だけで、 本文に書いた名前は
# 素通りしていた (実害あり = 公開 repo の SESSION.md へ push)。 mock repos.md の
# `mockpriv-foo` を使う (= 実 private repo 名を test file に literal で書かない、
# CLAUDE.md §Test file の private repo 名 literal 禁止)。
# --------------------------------------------------------------------
expect_block "block-tier-c-private-repo-name-in-body" \
  "2026-09-12 mockpriv-foo で踏んだ罠を層1 に上げた"

expect_block "block-tier-c-claude-path" \
  "cd ~/Claude/mockpriv-foo/ && make"

# word boundary: 名前の一部として現れるだけなら block しない (= FP 側の固定)
expect_pass "pass-tier-c-substring-not-word" \
  "mockpriv-foobar is a different token"

# 例外 list の repo 名は本文に書いてよい (= allowlist が body 側でも効く)
expect_pass "pass-tier-c-allowlisted-repo-name" \
  "詳細は odakin-prefs の該当 doc を参照 (email-office も同様)"

# 2026-09-12 追加の 2 名。health は普通の英単語としての出現が block されないこと、
# agent-board は layer-1 script の identity として書けることを固定する
# (= 追加理由は CLAUDE.md §例外 list の該当行。list を縮めたらここが落ちる)。
expect_pass "pass-tier-c-allowlist-health-as-english" \
  "run a health check on every repo and observe its health"
expect_pass "pass-tier-c-allowlist-agent-board" \
  "Discord to agent-board bridge engine"

# 2026-09-14 追加。企画リポと同名の公開 org / サイト URL を公開サイト側に書けることを固定する
expect_pass "pass-tier-c-allowlist-space-rock-diner" \
  "moved to https://space-rock-diner.pages.dev/ from space-rock-diner.github.io"

# 編集時の hook (hooks/public-leak-guard.sh) と本 runner は同じ email allowlist を持つ。
# 2026-09-12: runner だけ 2026-08-28 に例示 domain を足し、 hook は古いまま test fixture の
# Write ごとに確認 dialog を出していた → 片側だけの修正が再発しないよう一致を固定する。
GUARD="$(cd "$(dirname "$RUNNER")/.." && pwd)/hooks/public-leak-guard.sh"
allowlist_of() { grep -oE "grep -vE '\^\(noreply@anthropic[^']*'" "$1" | head -1; }
if [ -f "$GUARD" ] && [ -n "$(allowlist_of "$RUNNER")" ] \
   && [ "$(allowlist_of "$RUNNER")" = "$(allowlist_of "$GUARD")" ]; then
  PASS=$((PASS+1))
else
  FAIL=$((FAIL+1))
  FAILED_CASES="${FAILED_CASES}  - parity-email-allowlist: hook と runner の email allowlist が不一致\n"
fi
# hook 側の実挙動: 例示 domain の Write は確認なしで通る
if [ -f "$GUARD" ] && command -v jq >/dev/null 2>&1; then
  guard_out="$(jq -n --arg p "$MOCK_REPO/fixture.md" \
    '{tool_name:"Write",tool_input:{file_path:$p,content:"fixture user = someone@example.invalid"}}' \
    | bash "$GUARD" 2>/dev/null)"
  if [ -z "$guard_out" ]; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    FAILED_CASES="${FAILED_CASES}  - guard-email-example-domain: hook が例示 domain で確認を求めた\n"
  fi
fi

# markdown link guard (2026-09-13): a file moved one level down keeps `DOC.md` and must be
# stopped; the fixed link passes; an ignore-marked example passes; the escape env passes.
md_case() {   # md_case <name> <expect_rc> <content> [ENV=VAL]
  local name="$1" want="$2" content="$3" envkv="${4:-}" rc
  (
    cd "$MOCK_REPO"
    mkdir -p sub && printf 'target\n' > DOC.md && git add DOC.md >/dev/null 2>&1
    printf '%s\n' "$content" > sub/moved.md
    git add sub/moved.md >/dev/null 2>&1
    if [ -n "$envkv" ]; then env "$envkv" "$RUNNER" >/dev/null 2>&1; else "$RUNNER" >/dev/null 2>&1; fi
    echo "$?"
    git reset -q HEAD sub/moved.md DOC.md >/dev/null 2>&1
    rm -rf sub DOC.md
  ) > "$TMPDIR_TEST/_rc.txt"
  rc="$(cat "$TMPDIR_TEST/_rc.txt")"
  if [ "$rc" = "$want" ]; then PASS=$((PASS+1)); else
    FAIL=$((FAIL+1)); FAILED_CASES="${FAILED_CASES}  [exit=$rc want=$want] $name\n"; fi
}
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/fix-md-links.py" ]; then
  md_case "block-md-link-depth-after-move" 1 "see [doc](DOC.md)"
  md_case "pass-md-link-fixed-depth" 0 "see [doc](../DOC.md)"
  md_case "pass-md-link-ignore-marked-example" 0 "chat-rooted [doc](DOC.md) <!-- md-links:ignore -->"
  md_case "pass-md-link-escape-env" 0 "see [doc](DOC.md)" "CLAUDE_MD_LINKS_GUARD=0"
fi

# Tier D (2026-09-13): verbatim text of an unpublished document. Synthetic manuscript in a mock private
# project; the mock personal layer declares it. A quoted sentence blocks; a paraphrase and the escape env pass.
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/check-unpublished-quote.py" ]; then
  MOCK_ROOT="$TMPDIR_TEST/mock-claude-root"
  mkdir -p "$MOCK_ROOT/mockpriv-paper"
  printf '%s\n' '\begin{document}' \
    'We argue that the brass lantern regulator keeps the silent symmetry intact at every order of the toy expansion.' \
    '\end{document}' > "$MOCK_ROOT/mockpriv-paper/draft.tex"
  printf 'discover: %s .tex\n' "$MOCK_ROOT" > "$MOCK_LAYER/unpublished-sources.txt"
  export XDG_CACHE_HOME="$TMPDIR_TEST/cache"
  expect_block "block-unpublished-quoted-span" 'Example: `the brass lantern regulator keeps the silent symmetry intact` in a rule.'
  expect_pass "pass-unpublished-paraphrase" 'Example: a regulator that preserves a hidden symmetry to all orders.'
  uqf="uq-escape-$RANDOM.txt"
  printf '%s' 'Example: `the brass lantern regulator keeps the silent symmetry intact`.' > "$MOCK_REPO/$uqf"
  uq_rc="$(cd "$MOCK_REPO" && git add "$uqf" && env CLAUDE_UNPUBLISHED_GUARD=0 "$RUNNER" >/dev/null 2>&1; echo $?)"
  (cd "$MOCK_REPO" && git reset -q HEAD "$uqf" >/dev/null 2>&1; rm -f "$uqf")
  if [ "$uq_rc" = "0" ]; then PASS=$((PASS+1)); else
    FAIL=$((FAIL+1)); FAILED_CASES="${FAILED_CASES}  [exit=$uq_rc want=0] pass-unpublished-escape-env
"; fi
  rm -f "$MOCK_LAYER/unpublished-sources.txt"
  unset XDG_CACHE_HOME
fi

# Tier E (2026-09-14): activity facts. A literal from the mock layer's activity-fact-terms.txt blocks; an event word
# next to a date only warns. Fixture strings are split so this file does not trip the engine's own inventory.
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/check-activity-facts.py" ]; then
  printf '%s\n' 'MOCKPROGRAM' > "$MOCK_LAYER/activity-fact-terms.txt"
  expect_block "block-activity-fact-term" 'Uses the MOCKPROGRAM form for the budget table.'
  expect_pass "pass-activity-fact-warn-only" "20""31-04-02 に ""応募"" の様式を直した"
  expect_pass "pass-activity-fact-procedure" '差し戻しは正常フローで、窓は何度でも開く'
  rm -f "$MOCK_LAYER/activity-fact-terms.txt"
fi

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
