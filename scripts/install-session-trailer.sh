#!/usr/bin/env bash
# install-session-trailer.sh — 各 repo に prepare-commit-msg stub を冪等配置 (Claude-Session trailer)
#
# 使い方:
#   install-session-trailer.sh [<repo_path>]
#   repo_path 省略時は cwd。
#
# 動作:
#   1. 対象が git repo かを check
#   2. hooks dir を解決 (core.hooksPath 対応)
#   3. 既存 prepare-commit-msg があれば backup (.bak-<timestamp>)
#   4. 1 行 exec stub を書いて chmod +x
#   5. 冪等: 本 script が置いた stub なら backup せず上書き更新のみ
#
# 設計: install-public-commit-msg.sh / install-public-precommit.sh と同 pattern
#   (= stub は 1 行 exec のみ、 本体は scripts/prepare-commit-msg-session.sh の
#   absolute path。 runner を編集すれば全 repo に波及する)。
#
# ⚠️ sibling installer との違い: 本 script は `.claude/public-repo.marker` を要求しない
#   (= 全 repo が対象)。 trailer は session id しか書かず public / private で挙動が
#   変わらないため、 marker による出し分けが不要 — 理由は runner の header を参照。
#   むしろ private repo (= 並列 session が同じ tree を触る作業場) でこそ効く。
#
# opt-out: 対象 repo で `git config claude.sessionTrailer false`
#   (= hook は置かれたまま no-op になる。 uninstall は .git/hooks/prepare-commit-msg を消す)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/prepare-commit-msg-session.sh"

if [ ! -f "$RUNNER" ]; then
  echo "runner not found: $RUNNER" >&2
  exit 1
fi

REPO="${1:-$(pwd)}"
REPO="$(cd "$REPO" 2>/dev/null && pwd)" || { echo "not a directory: ${1:-$(pwd)}" >&2; exit 1; }

# --- git repo check ---
if [ ! -d "$REPO/.git" ] && [ ! -f "$REPO/.git" ]; then
  echo "not a git repo: $REPO" >&2
  exit 1
fi

# --- hooks dir 取得 (core.hooksPath 対応、 install-public-commit-msg.sh と同 logic) ---
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
HOOK="$HOOKS_DIR/prepare-commit-msg"

STUB_MARKER="prepare-commit-msg-session.sh"
STUB_CONTENT="#!/bin/bash
# Stub installed by claude-config/scripts/install-session-trailer.sh
# Do not edit — update prepare-commit-msg-session.sh instead.
exec \"$RUNNER\" \"\$@\"
"

# --- 既存 hook の扱い ---
if [ -f "$HOOK" ]; then
  if grep -q "$STUB_MARKER" "$HOOK" 2>/dev/null; then
    printf '%s' "$STUB_CONTENT" > "$HOOK"
    chmod +x "$HOOK"
    echo "prepare-commit-msg stub refreshed: $HOOK"
    exit 0
  else
    TS="$(date +%Y%m%d-%H%M%S)"
    BAK="$HOOK.bak-$TS"
    mv "$HOOK" "$BAK"
    echo "existing prepare-commit-msg backed up: $BAK" >&2
  fi
fi

printf '%s' "$STUB_CONTENT" > "$HOOK"
chmod +x "$HOOK"
echo "prepare-commit-msg stub installed: $HOOK"
