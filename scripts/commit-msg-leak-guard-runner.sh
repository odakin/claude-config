#!/bin/bash
# commit-msg-leak-guard-runner.sh — 公開リポ commit-msg hook（BLOCK mode、 2026-05-26 追加。 shared matcher library を source。 claude-code 2.1.x harness invoke bug の修復 option B）
# commit-msg-leak-guard-runner.sh — git native commit-msg hook (BLOCK mode)
#
# 正本: claude-config/scripts/commit-msg-leak-guard-runner.sh (layer 1)
# 各 public repo の .git/hooks/commit-msg に 1 行 stub が入り、本 script を
# absolute path で exec する (install-public-commit-msg.sh 参照)。
#
# 動作:
#   1. git が $1 に COMMIT_EDITMSG path、 $2 に message source ("message"
#      "template" "merge" "squash" "commit") を渡す (= git commit-msg hook
#      spec)
#   2. merge commit / fixup / squash 等は scope 外 (= 通常 reword 不可)、
#      $2 で skip 判定
#   3. message を読み、 shared matcher (= claude-config/scripts/lib/
#      commit-msg-leak-matcher.sh) で leak 候補検出
#   4. hit があれば exit 1 で commit を reject、 詳細を stderr に出す
#   5. `--no-verify` で bypass 可能 (git 標準の escape hatch)
#
# Mode: BLOCK (= claude-code 側 PreToolUse Bash hook の WARN mode と相補)。
#   理由 = WARN だと §5.1 single-viewpoint trap で hook output を読み流す
#   risk があり、 git 層で BLOCK にすると harness が抜けても止まる (=
#   2026-05-26 confirmed root cause = claude-code 2.1.x harness invoke bug
#   の修復 option B、 詳細 `conventions/hook-authoring.md#delivery-audit-4-axes (d) 軸`)。
#
# Gating: `.claude/public-repo.marker` を持つ repo のみ install されるので、
#   private repo の commit には fire しない (= install-public-commit-msg.sh
#   が marker check)。 本 runner 自体も safety net として marker 不在なら
#   silent pass (= 万が一 private repo に間違って install された場合の防御)。
#
# 設計思想:
#   既存 `public-precommit-runner.sh` (= file 本文 Tier A 検出) と本 runner
#   (= commit message Tier A + B 検出) は 2 layer 防御。 stage 済 file の
#   本文と、 commit message を独立に gate (= file 本文 OK だが commit
#   message に leak の事例が過去 5+ 件、 leak-incidents.md 参照)。
#   matcher logic は claude-code hook (= warn mode) と共通 library で DRY。
#
# 依存: bash 3.2 (= macOS stock)、 grep、 sed、 wc

set -uo pipefail

MSG_FILE="${1:-}"
MSG_SOURCE="${2:-}"

# ----------------------------------------------------------------------
# scope filter: 通常の commit (= 新規入力 + amend reword) のみ対象
# ----------------------------------------------------------------------
# git commit-msg hook の $2 ($GIT_COMMIT_SOURCE):
#   message  = -m / -F で渡された (= 我々の主 target)
#   template = .gitmessage 等 (= editor 起動、 我々の主 target)
#   merge    = merge commit の auto-generated message (skip)
#   squash   = squash merge (skip)
#   commit   = amend (= reword、 target)
#   ""       = 新規 commit + editor 起動 (= target)
case "$MSG_SOURCE" in
  merge|squash) exit 0 ;;
esac

[ -n "$MSG_FILE" ] || exit 0
[ -r "$MSG_FILE" ] || exit 0

# ----------------------------------------------------------------------
# repo marker safety net: marker 不在なら silent pass
# (= 主な gating は install-public-commit-msg.sh、 本 check は double-safe)
# ----------------------------------------------------------------------
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ] && [ ! -f "$REPO_ROOT/.claude/public-repo.marker" ]; then
  exit 0
fi

# ----------------------------------------------------------------------
# Read message (= comment lines stripped; git scrubs them at commit time
# but reading filtered version mirrors what git will actually store)
# ----------------------------------------------------------------------
# `git stripspace --strip-comments` を使うのが ideal だが、 全ての git
# version で同 flag があるとは限らないので sed で `^#` 行を除外
MESSAGE="$(grep -v '^#' "$MSG_FILE" 2>/dev/null || true)"

# 空 message なら git 側が後で reject するので skip
[ -n "$MESSAGE" ] || exit 0

# ----------------------------------------------------------------------
# matcher invoke (shared library)
# ----------------------------------------------------------------------
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MATCHER_LIB="$SELF_DIR/lib/commit-msg-leak-matcher.sh"
if [ ! -r "$MATCHER_LIB" ]; then
  # library 不在 = claude-config 配置異常、 fail-open (= 既存 commit flow を
  # 壊さない)。 user に visibility が無いので stderr に notice
  echo "[commit-msg-leak-guard-runner] WARNING: matcher library missing: $MATCHER_LIB (leak check skipped)" >&2
  exit 0
fi
# shellcheck source=/dev/null
. "$MATCHER_LIB"

run_leak_matcher "$MESSAGE"
HITS="${LEAK_MATCHER_HITS:-}"

# ----------------------------------------------------------------------
# 判定
# ----------------------------------------------------------------------
if [ -z "$HITS" ]; then
  exit 0  # silent pass
fi

# BLOCK mode: stderr に詳細 + exit 1 で git commit を reject
cat >&2 << EOF
[commit-msg-leak-guard] commit rejected: leak candidate in commit message.

repo:         $REPO_ROOT
message file: $MSG_FILE
hits:$HITS

本 repo は .claude/public-repo.marker で public と宣言されています。
commit message に非例外 private repo 名 または sensitive-terms.txt の
literal term が含まれます (= git log で grep 可能な public surface)。

対処:
  - 該当 repo 名を抽象化 (= "上流リポ" / "研究 LaTeX project" /
    "個人層" 等) して new commit message で再 commit
  - 既に push 済の修復は force push せず leak-incidents.md に記録
    (= claude-config/CLAUDE.md §「安全規則」 + odakin-prefs/leak-incidents.md
    の運用と整合)

例外 list (= mention OK な非公開 repo 8 個):
  gmail-mcp-config, research-collab, email-office,
  odakin-prefs, secrets-config, physics-research,
  conferences, 推薦書

意図的に commit したい場合は \`git commit --no-verify\` で bypass 可能
(escape hatch)。 但し意図的 bypass は leak-incidents.md に記録推奨。

詳細規約:
  - claude-config/CLAUDE.md §「安全規則 (公開リポ)」
  - odakin-prefs/leak-incidents.md (事例集計)
  - claude-config/conventions/hook-authoring.md#delivery-audit-4-axes (d) (= 2026-05-26 root
    cause + 本 hook の設計動機)
EOF

exit 1
