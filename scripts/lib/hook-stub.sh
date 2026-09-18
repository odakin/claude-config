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
#
# 規約 2 (conventions/hook-authoring.md#killed-hook-stub):
#   macOS に exec で kill される hook は、 同じ bytes・同じ mode の新しい inode に作り直す (中身は変えない)。
#   macOS は kill の判定を file (inode) ごとに覚えるので、 同じ inode への上書きでは直らない。 stub を書くときも
#   一時 file + mv で新しい inode に置く。

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

# hook を repo が track しているか。 hook が symlink なら link 先 (1 段) で判定する:
# .git/hooks/pre-commit → repo の track 済み hook という link は repo の中身であり、 installer が link 越しに
# 書くと track 済み file 本体が書き換わる (2026-09-16、 repo の installer が張った link を見分けていなかった)。
hook_stub_is_tracked() {  # $1 = repo, $2 = hook
  local rel h="$2" d r
  if [ -L "$h" ]; then
    h="$(readlink "$h")"
    case "$h" in /*) ;; *) h="$(dirname "$2")/$h" ;; esac
  fi
  d="$(cd "$(dirname "$h")" 2>/dev/null && pwd -P)" || return 1
  r="$(cd "$1" 2>/dev/null && pwd -P)" || return 1
  rel="$(hook_stub_rel "$r" "$d/$(basename "$h")")" || return 1
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

# ---------- macOS に exec で kill される hook (conventions/hook-authoring.md#killed-hook-stub) ----------
# macOS は provenance 付きの script を exec するとき syspolicyd に malware scan させ、 判定を file (inode) ごとに
# kernel に覚えさせる。 syspolicyd が詰まって scan が失敗すると「malware」 側に倒して覚え、 以後その file の exec は
# 即 SIGKILL (git は "hook ... died of signal 9")。 中身は関係ない = 同じ bytes の新しい inode は scan し直されて通る。
HOOK_EXEC_PROBE_ENV="${HOOK_EXEC_PROBE_ENV:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/hook-exec-probe.bash}"
_HOOK_EXEC_OS="${HOOK_EXEC_PROBE_OS:-$(uname -s 2>/dev/null || true)}"

# symlink を辿った実体の path
hook_real_path() {  # $1 = file
  local f="$1" t n=0
  while [ -L "$f" ] && [ "$n" -lt 20 ]; do
    t="$(readlink "$f")" || return 1
    case "$t" in /*) f="$t" ;; *) f="$(dirname "$f")/$t" ;; esac
    n=$((n + 1))
  done
  printf '%s\n' "$f"
}

# exec すると SIGKILL で止まるか (0 = 止まる)。 bash の script だけを見る: $BASH_ENV に exit 0 だけの file を渡すので
# hook は 1 行も走らず、 exec が通るかだけが分かる。 bash 以外の shebang と macOS 以外は調べない (= 1)。
hook_exec_killed() {  # $1 = file
  local f="$1" l rc=0
  [ "$_HOOK_EXEC_OS" = Darwin ] || return 1
  case "$f" in */*) ;; *) f="./$f" ;; esac   # PATH を引かせない
  [ -f "$f" ] && [ -x "$f" ] || return 1
  IFS= read -r l < "$f" 2>/dev/null || [ -n "${l:-}" ] || return 1
  case "$l" in '#!'*bash*) ;; *) return 1 ;; esac
  { BASH_ENV="$HOOK_EXEC_PROBE_ENV" "$f" </dev/null >/dev/null 2>&1; } 2>/dev/null || rc=$?
  [ "$rc" -eq 137 ]
}

# 同じ bytes・同じ mode の新しい inode に置き換える (symlink は実体を作り直す)。 中身は変えない =
# track 済み file でも git の差分は出ない (#installer-tracked-stub と両立)
hook_recreate() {  # $1 = file
  local f tmp
  f="$(hook_real_path "$1")" || return 1
  [ -f "$f" ] || return 1
  tmp="$(mktemp "$(dirname "$f")/.$(basename "$f").XXXXXX")" || return 1
  if cp -p "$f" "$tmp" && cmp -s "$f" "$tmp" && mv -f "$tmp" "$f"; then
    return 0
  fi
  rm -f "$tmp"
  return 1
}

# kill される hook を 1 回だけ作り直す。 0 = 作り直して通った / 1 = 何もしない (kill されていない・調べられない) /
# 2 = 作り直しても kill される (syspolicyd がまだ詰まっているか、 本当に malware と判定された。 繰り返さない)
hook_exec_heal() {  # $1 = file, $2 = label
  local real
  hook_exec_killed "$1" || return 1
  real="$(hook_real_path "$1")" || real="$1"
  [ "$real" = "$1" ] && real="" || real=" (-> $real)"
  if hook_recreate "$1" && ! hook_exec_killed "$1"; then
    echo "$2 recreated (macOS was killing it on exec): $1$real"
    return 0
  fi
  echo "WARNING: $2 is still killed by macOS on exec after recreating it: $1$real" >&2
  echo "  see claude-config/conventions/hook-authoring.md#killed-hook-stub" >&2
  return 2
}

# hook と、 stub ならその exec 先 (runner) も見る。 stub の検査は runner を exec する前に終わるので、 runner は別に見る
hook_exec_heal_chain() {  # $1 = hook, $2 = label
  local t rc=1 r=0
  hook_exec_heal "$1" "$2" || rc=$?
  t="$(hook_stub_target "$1")"
  if [ -n "$t" ] && [ -f "$t" ]; then
    hook_exec_heal "$t" "$2 runner" || r=$?
    [ "$r" -eq 2 ] && rc=2
    [ "$r" -eq 0 ] && [ "$rc" -ne 2 ] && rc=0
  fi
  return "$rc"
}

# stub の中身を新しい inode に書く (同じ inode への上書きでは macOS の kill の判定が残る)
hook_stub_put() {  # $1 = hook, $2 = content
  local tmp
  tmp="$(mktemp "$(dirname "$1")/.$(basename "$1").XXXXXX")" || return 1
  if printf '%s' "$2" > "$tmp" && chmod 755 "$tmp" && mv -f "$tmp" "$1"; then
    return 0
  fi
  rm -f "$tmp"
  return 1
}

# 本 installer が置いた既存 stub を冪等に最新化する
hook_stub_refresh() {  # $1 = repo, $2 = hook, $3 = runner, $4 = stub content, $5 = label
  local repo="$1" hook="$2" runner="$3" content="$4" label="$5"
  if hook_stub_is_tracked "$repo" "$hook"; then
    if ! hook_stub_restore_drift "$repo" "$hook" "$runner"; then
      if hook_stub_points_to "$hook" "$runner"; then
        echo "$label stub up to date (tracked by the repo): $hook"
      else
        echo "WARNING: $label stub is tracked by git and points elsewhere; not rewriting it: $hook" >&2
        echo "  fix it in the repo and commit: exec \"$runner\" \"\$@\"" >&2
      fi
    fi
    hook_exec_heal_chain "$hook" "$label stub" || true
    return 0
  fi
  if hook_stub_points_to "$hook" "$runner"; then
    echo "$label stub up to date: $hook"
  else
    hook_stub_put "$hook" "$content"
    echo "$label stub refreshed: $hook"
  fi
  [ -x "$hook" ] || chmod +x "$hook"
  hook_stub_exclude "$repo" "$hook"
  hook_exec_heal_chain "$hook" "$label stub" || true
}

# 新規 stub を置く
hook_stub_write() {  # $1 = repo, $2 = hook, $3 = stub content, $4 = label
  hook_stub_put "$2" "$3"
  hook_stub_exclude "$1" "$2"
  echo "$4 stub installed: $2"
  hook_exec_heal_chain "$2" "$4 stub" || true
}
