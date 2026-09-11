#!/usr/bin/env bash
# install-session-trailer.sh — 各 repo に prepare-commit-msg stub を冪等配置 (agent/session/model/effort trailer)
#
# 使い方:
#   install-session-trailer.sh [--refuse-existing] [<repo_path>]
#   repo_path 省略時は cwd。
#
# 動作:
#   1. 対象が git repo かを check
#   2. hooks dir を解決 (core.hooksPath 対応)
#   3. 既存 prepare-commit-msg があれば backup (.bak-<timestamp>)。
#      --refuse-existing なら user-managed hook を変更せず失敗する
#   4. 1 行 exec stub を書いて chmod +x
#   5. 冪等: 本 script が置いた stub は、 同じ runner を指していれば触らない (backup なし)。
#      git が track している file は書き換えない (lib/hook-stub.sh = conventions/hook-authoring.md#installer-tracked-stub)
#
# 設計: install-public-commit-msg.sh / install-public-precommit.sh と同 pattern
#   (= stub は 1 行 exec のみ、 本体は scripts/prepare-commit-msg-session.sh の
#   absolute path。 runner を編集すれば全 repo に波及する)。
#
# ⚠️ sibling installer との違い: 本 script は `.claude/public-repo.marker` を要求しない
#   (= 全 repo が対象)。 trailer は agent/session + model/effort だけを書き、host / account
#   や project 内容を持たないため、public / private で挙動が変わらず marker による
#   出し分けが不要 — 理由は runner の header を参照。
#   むしろ private repo (= 並列 session が同じ tree を触る作業場) でこそ効く。
#
# opt-out: 対象 repo で `git config agent.sessionTrailer false`
#   legacy の `claude.sessionTrailer false` / `codex.sessionTrailer false` も有効。
#   (= hook は置かれたまま no-op になる。 uninstall は .git/hooks/prepare-commit-msg を消す)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/prepare-commit-msg-session.sh"
# shellcheck source=lib/hook-stub.sh
. "$SCRIPT_DIR/lib/hook-stub.sh"
REFUSE_EXISTING=0

if [ "${1:-}" = "--refuse-existing" ]; then
  REFUSE_EXISTING=1
  shift
fi
if [ "$#" -gt 1 ]; then
  echo "usage: install-session-trailer.sh [--refuse-existing] [<repo_path>]" >&2
  exit 2
fi

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
# 規約: installer は git が track している file を書き換えない (lib/hook-stub.sh、
# conventions/hook-authoring.md#installer-tracked-stub)。 repo 内 hooksPath に置く untrack stub は
# .git/info/exclude に載せる (= 共有 repo の status に ?? を出さず、 他人の clone に無い stub を commit させない)。
if [ -e "$HOOK" ] || [ -L "$HOOK" ]; then
  if grep -q "$STUB_MARKER" "$HOOK" 2>/dev/null; then
    hook_stub_refresh "$REPO" "$HOOK" "$RUNNER" "$STUB_CONTENT" "prepare-commit-msg"
    exit 0
  elif hook_stub_is_tracked "$REPO" "$HOOK"; then
    # repo が track している自前の prepare-commit-msg (= 本 script の stub でない) → 退避も上書きもしない
    echo "refusing to replace git-tracked prepare-commit-msg hook: $HOOK" >&2
    exit 1
  else
    if [ "$REFUSE_EXISTING" -eq 1 ]; then
      echo "refusing to replace existing prepare-commit-msg hook: $HOOK" >&2
      exit 1
    fi
    TS="$(date +%Y%m%d-%H%M%S)"
    BAK="$HOOK.bak-$TS"
    mv "$HOOK" "$BAK"
    echo "existing prepare-commit-msg backed up: $BAK" >&2
  fi
fi

hook_stub_write "$REPO" "$HOOK" "$STUB_CONTENT" "prepare-commit-msg"
