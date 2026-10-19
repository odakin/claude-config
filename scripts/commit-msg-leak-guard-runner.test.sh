#!/usr/bin/env bash
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

# cwd 非依存にする: 本 test は途中で claude-config へ cd するので、 相対 path のままだと
# cd 後に $RUNNER が解決できず全 case が exit 127 になる (2026-09-12 実測、 ~/Claude から実行)。
RUNNER="$(cd "$(dirname "$0")" && pwd)/commit-msg-leak-guard-runner.sh"
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
!モック秘語町
TERMS_EOF

# 偽 review-instance-terms.txt (= matcher (d) 審査軸 が読む種目名の list)
# 実在の種目名は embed しない (= 本 file は layer 1 public。 実語の責任は
# odakin-prefs 側 test)。 判定は **種目語 × 評価語の共起** なので、 片方だけの
# case が pass することを下の 3 case で verify する。
cat > "$MOCK_LAYER/review-instance-terms.txt" << 'REVIEW_EOF'
モック種目(甲)
MOCKGRANT
REVIEW_EOF

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


# 自己 lint: expect_* の呼び出し名が全部定義済か (= case 名の typo で case が
# silent に消えるのを防ぐ)。 bash 3.2 には command_not_found_handle が無く
# (macOS 既定 = 3.2.57、 実測で未発火)、 未定義 command は stderr へ流れて次へ進むため、
# case が 1 つも実行されないまま suite が緑になる (2026-09-12 実測: expect_no_hit で 2 case 消失)。
# 一般則 = claude-config/docs/convention-design-principles.md#fail-loud-not-fail-empty
for _h in $(grep -oE '^ *expect_[a-z_]+' "$0" | tr -d ' ' | sort -u); do
  type "$_h" >/dev/null 2>&1 || {
    echo "ERROR: 未定義 helper を呼んでいる: $_h (= case 名の typo、 その case は実行されない)"
    exit 1
  }
done

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

# (a-0) 許可複合語 (`!` 行、 lib/sensitive-terms.sh): 複合語だけの言及は通り、 同じ message に姓だけの言及があれば止まる
expect_pass "pass-allowed-compound" \
  "map: モック秘語町 の座標を直す"
expect_block "block-compound-foil-bare-term" \
  "map: モック秘語町 と モック秘語さんの件"

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

# --------------------------------------------------------------------
# (d) 審査軸 — 種目語 × 評価語の **共起** でのみ発火 (2026-09-12)
# 起源の実害は「公開 repo の message に種目名と模擬評点が入って push 済」。
# 片方だけで発火させると規約 doc の正当な文が全部落ちるので、共起を要求する。
# --------------------------------------------------------------------
expect_block "block-review-instance-cooccurrence" \
  "モック種目(甲) の模擬審査: 段で評点が割れた (前段 5 / 後段 3)"

expect_block "block-review-instance-ascii-term" \
  "MOCKGRANT review: score split across stages"

# 種目語だけ = 制度一般を論じる正当な文 (規約 doc で頻出)
expect_pass "pass-review-subject-only" \
  "モック種目(甲) の様式は頁数制限が種目ごとに違う"

# 評価語だけ = 審査 process の方法論 (同上)
expect_pass "pass-review-verb-only" \
  "評点は相対評価なので母集団を宣言させる。絶対評価と分けて出させる"

# 段階番号は評点ではない (= 近接判定だと落ちる実測 case の回帰 fixture)
expect_pass "pass-review-stage-number-not-score" \
  "Stage 1 の評点と所見を専用 file に書き切らせ、Stage 2 では書き換え禁止"

# Tier D (2026-09-13): verbatim text of an unpublished document in the message (synthetic source).
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/check-unpublished-quote.py" ]; then
  UQ_ROOT="$TMPDIR_TEST/uq-root"
  mkdir -p "$UQ_ROOT/mockpriv-paper"
  printf '%s\n' '\begin{document}' 'We argue that the copper kettle estimator keeps the quiet invariance exact at every order of the toy series.' '\end{document}' > "$UQ_ROOT/mockpriv-paper/draft.tex"
  printf 'discover: %s .tex\n' "$UQ_ROOT" > "$MOCK_LAYER/unpublished-sources.txt"
  export XDG_CACHE_HOME="$TMPDIR_TEST/uq-cache"
  expect_block "block-unpublished-quote-in-message" 'Fix the rule: `the copper kettle estimator keeps the quiet invariance exact`'
  expect_pass "pass-unpublished-paraphrase-in-message" 'Fix the rule about an estimator that keeps an invariance'
  rm -f "$MOCK_LAYER/unpublished-sources.txt"; unset XDG_CACHE_HOME
fi

# Tier E (2026-09-14): activity facts in the message (literal blocks, co-occurrence only warns; split fixtures).
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/check-activity-facts.py" ]; then
  printf '%s\n' 'MOCKPROGRAM' > "$MOCK_LAYER/activity-fact-terms.txt"
  expect_block "block-activity-fact-term-in-message" 'Fix the MOCKPROGRAM budget table'
  af_msg="$TMPDIR_TEST/msg-af-$RANDOM.txt"
  printf '%s' "Fix the form used on 20""31-04-02 for the ""応募""" > "$af_msg"
  af_err="$("$RUNNER" "$af_msg" message 2>&1 >/dev/null)"; af_rc=$?
  if [ "$af_rc" = "0" ] && printf '%s' "$af_err" | grep -q '\[activity-facts\]'; then PASS=$((PASS+1)); else
    FAIL=$((FAIL+1)); FAILED_CASES="${FAILED_CASES}  [exit=$af_rc, warning shown?] pass-activity-fact-warn-only-in-message\n"; fi
  rm -f "$MOCK_LAYER/activity-fact-terms.txt"
fi

# Tier F (2026-10-19): a value from the mock layer's value index in the message blocks; the same digits inside a
# longer number pass.
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/check-value-index.py" ]; then
  mkdir -p "$MOCK_LAYER/private"
  printf '## <a id="leak-index"></a>index\n\n- digits: `090-0000-1234` (mock)\n' > "$MOCK_LAYER/private/v.md"
  printf 'private/v.md#leak-index\n' > "$MOCK_LAYER/value-index.txt"
  expect_block "block-value-index-in-message" 'Call 090 0000 1234 about the room'
  expect_pass "pass-value-index-longer-number-in-message" 'Bump id 1090000012345'
  rm -rf "$MOCK_LAYER/private" "$MOCK_LAYER/value-index.txt"
fi

# ====================================================================
# Stage 0 (2026-09-29): 学生の識別子 (check-student-identifiers.py --commit-msg)。 公開 repo (= ここ) でも、
# marker の無い private repo でも止まる (= Stage 0 は marker の safety net より前)。 この test だけの架空の一覧を env で渡す。
# 学籍番号の形の値は実行時に組み立てる (この file 自体が gate に当たらないように)。 述語の SoT = engine の docstring。
# ====================================================================
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$RUNNER")/check-student-identifiers.py" ]; then
  SID_LIST="$TMPDIR_TEST/student-identity.json"
  printf '%s\n' '{"schema": 1, "full_names_cjk": ["仮野 名子"], "full_names_latin": [["karino", "nako"]], "surnames_latin": ["karino"]}' > "$SID_LIST"
  SID_PAT="$TMPDIR_TEST/pii-patterns.txt"
  printf '%s\n' '(?i)(?<![0-9a-z])[a-z][0-9]{2}[a-z][0-9]{3,4}(?![0-9a-z])' > "$SID_PAT"
  SID_ID="$(printf 'A%02dX%s' 12 3456)"
  CLAUDE_STUDENT_IDENTITY="$SID_LIST" CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" \
    expect_block "block-student-name-in-message" "fix: 仮野 名子 さんの提出物の扱い"
  CLAUDE_STUDENT_IDENTITY="$SID_LIST" CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" \
    expect_block "block-student-id-in-message" "fix: see $SID_ID"
  CLAUDE_STUDENT_IDENTITY="$SID_LIST" CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" \
    expect_pass "pass-student-surname-only-in-message" "fix: karino さんの件 (姓だけは message に当てない)"
  CLAUDE_STUDENT_IDENTITY="$SID_LIST" CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" \
    expect_pass "pass-student-name-in-merge-message" "Merge branch 仮野 名子" "merge"
  # escape hatch: exit 0 (= 止めたのがこの gate だという証拠。 skip の 1 行が stderr に出るので expect_pass は使わない)
  esc_msg="$TMPDIR_TEST/msg-esc-$RANDOM.txt"; printf '%s' "fix: see $SID_ID" > "$esc_msg"
  CLAUDE_STUDENT_ID_GUARD=0 CLAUDE_STUDENT_IDENTITY="$SID_LIST" CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" \
    "$RUNNER" "$esc_msg" message >/dev/null 2>&1
  esc_rc=$?
  if [ "$esc_rc" = "0" ]; then PASS=$((PASS+1)); else
    FAIL=$((FAIL+1)); FAILED_CASES="${FAILED_CASES}  [exit!=0] pass-student-id-escape-hatch-proves-which-gate (exit=$esc_rc)\n"; fi
  # marker の無い private repo: Stage 0 は走り、 公開 repo の leak 検出 (偽 private repo 名) は走らない
  PRIV="$TMPDIR_TEST/private-repo"
  mkdir -p "$PRIV" && git -C "$PRIV" init -q -b main
  sid_priv() { # <case> <want exit> <message> → private repo の中で runner を回す
    local name="$1" want="$2" content="$3" f rc
    f="$TMPDIR_TEST/msg-priv-$RANDOM.txt"; printf '%s' "$content" > "$f"
    (cd "$PRIV" && CLAUDE_STUDENT_IDENTITY="$SID_LIST" CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" "$RUNNER" "$f" message >/dev/null 2>&1)
    rc=$?
    if [ "$rc" = "$want" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); FAILED_CASES="${FAILED_CASES}  [exit!=$want] $name (exit=$rc)\n"; fi
  }
  sid_priv "block-student-name-in-private-repo" 1 "fix: 仮野 名子 さんの件"
  sid_priv "block-student-id-in-private-repo" 1 "fix: see $SID_ID"
  sid_priv "pass-private-repo-name-in-private-repo" 0 "fix mockpriv-foo/CLAUDE.md path"
  # engine が見出しなしで落ちた: commit は通し、 1 行出す (= 故障を違反と読まない)
  SID_FAKE="$TMPDIR_TEST/fake-scripts-sid"; mkdir -p "$SID_FAKE/lib"
  cp "$RUNNER" "$SID_FAKE/commit-msg-leak-guard-runner.sh"
  for f in "$(dirname "$RUNNER")"/lib/*; do ln -s "$f" "$SID_FAKE/lib/$(basename "$f")"; done
  printf 'import sys\nsys.exit(1)\n' > "$SID_FAKE/check-student-identifiers.py"
  crash_msg="$TMPDIR_TEST/msg-crash-$RANDOM.txt"; printf '%s' "fix: see $SID_ID" > "$crash_msg"
  crash_err="$(cd "$PRIV" && bash "$SID_FAKE/commit-msg-leak-guard-runner.sh" "$crash_msg" message 2>&1 >/dev/null)"; crash_rc=$?
  if [ "$crash_rc" = "0" ] && printf '%s' "$crash_err" | grep -q '学生の識別子の検査が異常終了'; then PASS=$((PASS+1)); else
    FAIL=$((FAIL+1)); FAILED_CASES="${FAILED_CASES}  [exit=$crash_rc, line shown?] pass-student-id-engine-crash-is-not-a-block\n"; fi
fi

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
