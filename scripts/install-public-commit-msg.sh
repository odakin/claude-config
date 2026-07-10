#!/usr/bin/env bash
# install-public-commit-msg.sh — 各 public repo に commit-msg stub を冪等配置（marker check + core.hooksPath cascade）
# install-public-commit-msg.sh — public repo に commit-msg leak guard hook
# の 1 行 stub を配置する。
#
# 使い方:
#   install-public-commit-msg.sh [<repo_path>]
#   repo_path が省略された場合は cwd を使う。
#
# 動作:
#   1. 対象ディレクトリが git repo かを check
#   2. `.claude/public-repo.marker` が存在するかを check (なければ refuse)
#   3. 既存 `.git/hooks/commit-msg` があれば backup (`.bak-<timestamp>`)
#   4. 新しい stub を書き、 chmod +x
#   5. 冪等性: 既に本 script が設置した stub があれば上書きのみ (backup なし)
#
# 設計: install-public-precommit.sh と同 pattern (= stub は 1 行 exec
#   のみ、 本体は claude-config/scripts/commit-msg-leak-guard-runner.sh
#   の absolute path を参照、 更新は runner を edit するだけで全 repo
#   に波及する)。
#
# 動機 (2026-05-26): claude-code 2.1.x harness invoke bug (= Anthropic
#   issues #52715 + #59513、 詳細 `conventions/hook-authoring.md#delivery-audit-4-axes (d)`)
#   で PreToolUse Bash hook が silent skip される。 git native commit-msg
#   hook は harness 経由しないので bypass されない。 既存
#   public-precommit-runner.sh (= file 本文 Tier A) と相補的 2 layer 防御。

set -euo pipefail

# Resolve the runner (a sibling of this installer) so the generated stub
# works regardless of where claude-config is cloned. This previously
# hardcoded "$HOME/Claude/claude-config/...", which broke whenever the repo
# lived anywhere other than ~/Claude (e.g. Windows clones directly under ~).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/commit-msg-leak-guard-runner.sh"

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
  echo "this script refuses to install commit-msg hook on repos without the marker." >&2
  echo "create the marker first if this repo is indeed public." >&2
  exit 1
fi

# --- hooks dir 取得 (core.hooksPath 対応) ---
# install-public-precommit.sh と同 logic
HOOKS_DIR="$(cd "$REPO" && git config --get core.hooksPath 2>/dev/null || true)"
if [ -z "$HOOKS_DIR" ]; then
  HOOKS_DIR="$(cd "$REPO" && git rev-parse --git-path hooks 2>/dev/null || true)"
fi
if [ -z "$HOOKS_DIR" ]; then
  HOOKS_DIR="$REPO/.git/hooks"
elif [ "${HOOKS_DIR#/}" = "$HOOKS_DIR" ]; then
  HOOKS_DIR="$REPO/$HOOKS_DIR"
fi
mkdir -p "$HOOKS_DIR"
HOOK="$HOOKS_DIR/commit-msg"

STUB_MARKER="commit-msg-leak-guard-runner.sh"
STUB_CONTENT="#!/bin/bash
# Stub installed by claude-config/scripts/install-public-commit-msg.sh
# Do not edit — update commit-msg-leak-guard-runner.sh instead.
exec \"$RUNNER\" \"\$@\"
"

# --- 既存 hook の扱い ---
if [ -f "$HOOK" ]; then
  if grep -q "$STUB_MARKER" "$HOOK" 2>/dev/null; then
    # 既に本 script が設置した stub。 上書きで最新化 (冪等)
    printf '%s' "$STUB_CONTENT" > "$HOOK"
    chmod +x "$HOOK"
    echo "commit-msg stub refreshed: $HOOK"
    exit 0
  else
    # 他の commit-msg hook が既にある → backup
    TS="$(date +%Y%m%d-%H%M%S)"
    BAK="$HOOK.bak-$TS"
    mv "$HOOK" "$BAK"
    echo "existing commit-msg backed up: $BAK" >&2
  fi
fi

printf '%s' "$STUB_CONTENT" > "$HOOK"
chmod +x "$HOOK"
echo "commit-msg stub installed: $HOOK"
