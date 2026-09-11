#!/usr/bin/env bash
# lib/hook-stub.sh — hook stub installer 共通の「既存 stub の扱い」 (source して使う、 単体実行しない)
#
# 規約 (conventions/hook-authoring.md#installer-tracked-stub):
#   installer は git が track している file を書き換えない。
#   core.hooksPath が repo 内を指す repo では hook stub が repo の中身になっており、 installer が
#   書き換えると worktree が汚れ続け、 SessionStart の自動 pull (stash → ff → pop) と衝突する
#   (2026-09-12、 "$HOME/..." 形で track された stub を installer が毎回 absolute path で上書きしていた)。
#
#   - track 済み stub: 内容は書かない。 過去の installer が書き換えた差分 (= worktree 側が installer の書く
#     4 行そのままで、 track 版の exec 先が実在する) なら track 版に戻す。 それ以外は触らず、 必要なら警告だけ出す。
#   - untrack の stub: 同じ runner を指していれば書かない (mtime も動かさない)。 違えば最新化。
#     repo の worktree 内に置いた untrack stub は .git/info/exclude に載せる (clone ごとの設定)。
#
# 使う側 (installer) は set -euo pipefail 下で source する前提。 各関数は失敗を握りつぶして return する。

# stub の exec 先を出す ("$HOME" は展開)
hook_stub_target() {
  local t
  t="$(sed -n 's/^exec "\(.*\)" "\$@"$/\1/p' "$1" 2>/dev/null | head -n 1)" || true
  printf '%s\n' "${t/#\$HOME/$HOME}"
}

# stub が runner を指すか (runner 省略時は「exec 先の file が実在するか」)
hook_stub_points_to() {  # $1 = stub file, $2 = runner (省略可)
  local t
  t="$(hook_stub_target "$1")"
  [ -n "$t" ] || return 1
  if [ -n "${2:-}" ]; then
    [ "$t" -ef "$2" ]
  else
    [ -f "$t" ]
  fi
}

# hook が repo の worktree 内なら repo 相対 path を出す (.git/ 配下・repo 外なら失敗)
hook_stub_rel() {  # $1 = repo, $2 = hook
  case "$2" in "$1"/*) ;; *) return 1 ;; esac
  local rel="${2#"$1"/}"
  case "$rel" in .git/*) return 1 ;; esac
  printf '%s\n' "$rel"
}

# hook を repo が track しているか
hook_stub_is_tracked() {  # $1 = repo, $2 = hook
  local rel
  rel="$(hook_stub_rel "$1" "$2")" || return 1
  git -C "$1" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1
}

# file が installer の書く 4 行そのままの stub か (= shebang / header / Do not edit / exec の 4 行だけ)。
# 1 行でも手で足してあれば偽 = 自動で戻す対象にしない。
hook_stub_is_pristine() {  # $1 = file
  awk '
    NR == 1 { ok = ($0 == "#!/bin/bash") }
    NR == 2 { ok = ok && ($0 ~ /^# Stub installed by claude-config\//) }
    NR == 3 { ok = ok && ($0 ~ /^# Do not edit/) }
    NR == 4 { ok = ok && ($0 ~ /^exec ".*" "\$@"$/) }
    END     { exit !(ok && NR == 4) }
  ' "$1" 2>/dev/null
}

# 過去の installer が track 済み stub に書いた差分を track 版に戻す。 戻したら 0。
hook_stub_restore_drift() {  # $1 = repo, $2 = hook, $3 = runner (省略可)
  local repo="$1" hook="$2" runner="${3:-}" rel tmp
  hook_stub_is_tracked "$repo" "$hook" || return 1
  rel="$(hook_stub_rel "$repo" "$hook")" || return 1
  git -C "$repo" diff --quiet -- "$rel" 2>/dev/null && return 1
  hook_stub_is_pristine "$hook" || return 1
  tmp="$(mktemp)" || return 1
  if git -C "$repo" show "HEAD:$rel" > "$tmp" 2>/dev/null && hook_stub_points_to "$tmp" "$runner"; then
    rm -f "$tmp"
    git -C "$repo" checkout -- "$rel" 2>/dev/null || return 1
    echo "hook stub restored to the tracked version: $hook"
    return 0
  fi
  rm -f "$tmp"
  return 1
}

# repo の worktree 内に置いた untrack stub を .git/info/exclude に載せる
hook_stub_exclude() {  # $1 = repo, $2 = hook
  local rel ex
  rel="$(hook_stub_rel "$1" "$2")" || return 0
  git -C "$1" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1 && return 0
  ex="$(git -C "$1" rev-parse --git-path info/exclude 2>/dev/null)" || return 0
  case "$ex" in /*) ;; *) ex="$1/$ex" ;; esac
  mkdir -p "$(dirname "$ex")" 2>/dev/null || return 0
  grep -qxF "/$rel" "$ex" 2>/dev/null || printf '/%s\n' "$rel" >> "$ex" || true
  return 0
}

# 本 installer が置いた既存 stub を冪等に最新化する
hook_stub_refresh() {  # $1 = repo, $2 = hook, $3 = runner, $4 = stub content, $5 = label
  local repo="$1" hook="$2" runner="$3" content="$4" label="$5"
  if hook_stub_is_tracked "$repo" "$hook"; then
    hook_stub_restore_drift "$repo" "$hook" "$runner" && return 0
    if hook_stub_points_to "$hook" "$runner"; then
      echo "$label stub up to date (tracked by the repo): $hook"
    else
      echo "WARNING: $label stub is tracked by git and points elsewhere; not rewriting it: $hook" >&2
      echo "  fix it in the repo and commit: exec \"$runner\" \"\$@\"" >&2
    fi
    return 0
  fi
  if hook_stub_points_to "$hook" "$runner"; then
    echo "$label stub up to date: $hook"
  else
    printf '%s' "$content" > "$hook"
    echo "$label stub refreshed: $hook"
  fi
  [ -x "$hook" ] || chmod +x "$hook"
  hook_stub_exclude "$repo" "$hook"
}

# 新規 stub を置く
hook_stub_write() {  # $1 = repo, $2 = hook, $3 = stub content, $4 = label
  printf '%s' "$3" > "$2"
  chmod +x "$2"
  hook_stub_exclude "$1" "$2"
  echo "$4 stub installed: $2"
}
