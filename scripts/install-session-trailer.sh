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
#   5. 冪等: 本 script が置いた stub なら backup せず上書き更新のみ
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

# core.hooksPath が repo の worktree 内を指し、 そこに stub が untracked で置かれる場合は
# .git/info/exclude に載せる (= clone ごとの設定。 共有 repo の status に `??` を出し続けない、
# かつ他人の clone では存在しない stub を commit させない、 2026-09-12)。 track 済みなら repo の判断に任せる。
exclude_if_untracked_in_worktree() {
  case "$HOOK" in "$REPO"/*) ;; *) return 0 ;; esac
  local rel="${HOOK#"$REPO"/}"
  case "$rel" in .git/*) return 0 ;; esac
  git -C "$REPO" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1 && return 0
  local ex
  ex="$(git -C "$REPO" rev-parse --git-path info/exclude 2>/dev/null)" || return 0
  case "$ex" in /*) ;; *) ex="$REPO/$ex" ;; esac
  mkdir -p "$(dirname "$ex")" 2>/dev/null || return 0
  grep -qxF "/$rel" "$ex" 2>/dev/null || printf '/%s\n' "$rel" >> "$ex"
}

# --- 既存 hook の扱い ---
if [ -e "$HOOK" ] || [ -L "$HOOK" ]; then
  if grep -q "$STUB_MARKER" "$HOOK" 2>/dev/null; then
    # 既存 stub が同じ runner を指していれば書き換えない (理由 = install-public-precommit.sh の同所)
    cur="$(sed -n 's/^exec "\(.*\)" "\$@"$/\1/p' "$HOOK" | head -n 1)"
    cur="${cur/#\$HOME/$HOME}"
    if [ -n "$cur" ] && [ "$cur" -ef "$RUNNER" ]; then
      [ -x "$HOOK" ] || chmod +x "$HOOK"
      exclude_if_untracked_in_worktree
      echo "prepare-commit-msg stub up to date: $HOOK"
      exit 0
    fi
    printf '%s' "$STUB_CONTENT" > "$HOOK"
    chmod +x "$HOOK"
    exclude_if_untracked_in_worktree
    echo "prepare-commit-msg stub refreshed: $HOOK"
    exit 0
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

printf '%s' "$STUB_CONTENT" > "$HOOK"
chmod +x "$HOOK"
echo "prepare-commit-msg stub installed: $HOOK"
