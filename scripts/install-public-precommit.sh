#!/bin/bash
# install-public-precommit.sh — 各 public repo に pre-commit stub を冪等配置
# install-public-precommit.sh — public repo に pre-commit gate の
# 1 行 stub を配置する。
#
# 使い方:
#   install-public-precommit.sh [<repo_path>]
#   repo_path が省略された場合は cwd を使う。
#
# 動作:
#   1. 対象ディレクトリが git repo かを check
#   2. `.claude/public-repo.marker` が存在するかを check (なければ refuse)
#   3. 既存 `.git/hooks/pre-commit` があれば backup (`.bak-<timestamp>`)
#   4. 新しい stub を書き、chmod +x
#   5. 冪等性: 既に本 script が設置した stub があれば上書きのみ (backup なし)
#
# 設計:
#   stub は 1 行 exec のみ。本体は claude-config/scripts/public-precommit-runner.sh
#   の absolute path を参照。これにより各 public repo の hook 側に
#   logic が散らず、更新は runner を edit するだけで全 repo に波及する。
#
# Sibling installer:
#   本 script は `.git/hooks/pre-commit` (= file 本文 Tier A/B scan) のみ install。
#   commit message + subject scan は別 installer `install-public-commit-msg.sh`
#   が `.git/hooks/commit-msg` を担当 (= 2026-05-26 追加、 claude-code 2.1.x
#   harness invoke bug の mitigation option B、 詳細 conventions/hook-authoring.md
#   §2 (d) + DESIGN.md §2026-05-26)。 setup.sh Step 8 は両 installer を同 loop
#   で同時呼出、 marker 持つ repo に 2 hook を bundle install する設計。

set -euo pipefail

# Resolve the runner (a sibling of this installer) so the generated stub
# works regardless of where claude-config is cloned. This previously
# hardcoded "$HOME/Claude/claude-config/...", which broke whenever the repo
# lived anywhere other than ~/Claude (e.g. Windows clones directly under ~).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/public-precommit-runner.sh"

REPO="${1:-$(pwd)}"
REPO="$(cd "$REPO" 2>/dev/null && pwd)" || { echo "not a directory: ${1:-$(pwd)}" >&2; exit 1; }

# --- git repo check ---
if [ ! -d "$REPO/.git" ] && [ ! -f "$REPO/.git" ]; then
  echo "not a git repo: $REPO" >&2
  exit 1
fi

# --- marker check ---
if [ ! -f "$REPO/.claude/public-repo.marker" ]; then
  echo "no .claude/public-repo.marker in $REPO" >&2
  echo "this script refuses to install pre-commit on repos without the marker." >&2
  echo "create the marker first if this repo is indeed public." >&2
  exit 1
fi

# --- hooks dir 取得 (core.hooksPath 対応、worktree や bare repo でも動く) ---
# 優先順位:
#   1. core.hooksPath の設定 (per-clone カスタム)
#   2. git rev-parse --git-path hooks (GIT_DIR/hooks)
#   3. $REPO/.git/hooks (最終 fallback)
# 1. と 2. はどちらも repo 内相対 path を返しうるので、相対なら REPO を prefix する。
HOOKS_DIR="$(cd "$REPO" && git config --get core.hooksPath 2>/dev/null || true)"
if [ -z "$HOOKS_DIR" ]; then
  HOOKS_DIR="$(cd "$REPO" && git rev-parse --git-path hooks 2>/dev/null || true)"
fi
if [ -z "$HOOKS_DIR" ]; then
  HOOKS_DIR="$REPO/.git/hooks"
elif [ "${HOOKS_DIR#/}" = "$HOOKS_DIR" ]; then
  # 相対 path が返ってきた場合は REPO root を prefix
  HOOKS_DIR="$REPO/$HOOKS_DIR"
fi
mkdir -p "$HOOKS_DIR"
HOOK="$HOOKS_DIR/pre-commit"

STUB_MARKER="public-precommit-runner.sh"
STUB_CONTENT="#!/bin/bash
# Stub installed by claude-config/scripts/install-public-precommit.sh
# Do not edit — update public-precommit-runner.sh instead.
exec \"$RUNNER\" \"\$@\"
"

# --- 既存 hook の扱い ---
if [ -f "$HOOK" ]; then
  if grep -q "$STUB_MARKER" "$HOOK" 2>/dev/null; then
    # 既に本 script が設置した stub。上書きで最新化 (冪等)
    printf '%s' "$STUB_CONTENT" > "$HOOK"
    chmod +x "$HOOK"
    echo "pre-commit stub refreshed: $HOOK"
    exit 0
  else
    # 他の pre-commit が既にある → backup
    TS="$(date +%Y%m%d-%H%M%S)"
    BAK="$HOOK.bak-$TS"
    mv "$HOOK" "$BAK"
    echo "existing pre-commit backed up: $BAK" >&2
  fi
fi

printf '%s' "$STUB_CONTENT" > "$HOOK"
chmod +x "$HOOK"
echo "pre-commit stub installed: $HOOK"
