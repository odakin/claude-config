#!/usr/bin/env bash
# install-precommit-bib.sh — 共通 pre-commit (pre-commit-bib) を repo に張る。 repo が自分で管理する pre-commit は置き換えない
#
# 使い方:
#   install-precommit-bib.sh <repo>...            # 張る (setup.sh Step 6 が全 repo に対して呼ぶ)
#   install-precommit-bib.sh --check <repo>...    # 書かずに点検。 finding を 1 行ずつ出し、 あれば exit 1
#
# 何をするか (repo ごと。 hook の位置は git が実際に使う path = core.hooksPath を反映):
#   - public repo (.claude/public-repo.marker) は対象外 (pre-commit は Step 8 の stub が管轄)
#   - 本 script が置いたもの (pre-commit-bib への link / 古い場所の pre-commit-bib への link / 旧版のコピー)
#     だけを最新化する
#   - それ以外の pre-commit (repo が track する hook、 repo の installer が張った link、 他ツールの hook) は
#     退避も上書きもしない。 pre-commit-bib を中から呼んでいるか (chain) を表示するだけ
#   - repo が自前の pre-commit を宣言しているのに、 効いている pre-commit が pre-commit-bib か空なら、
#     pre-commit-bib を入れずに finding として repo 側の入れ方を案内する (= --check が出すのはこれ)
#
# 「自前の pre-commit を宣言している」 = 次のどれかを git が track している:
#   hooks/pre-commit / .githooks/pre-commit / pre-commit に触れる scripts/install-hooks.sh (か install-hooks.sh)
#   repo の hook を自動では有効化しない: 共同研究者が push できる code を、 clone ごとの同意 (installer の実行) なしに
#   git hook にしないため。
#
# 起点 (2026-09-16): 旧 Step 6 は既存 hook の link 先が pre-commit-bib でなければ付け替え、 通常 file は .bak に
#   退避して置き換えていた。 repo が自分の hook (検査 gate) から pre-commit-bib を chain している場合も区別せず、
#   gate が黙って無効になっていた。 規約 = conventions/hook-authoring.md#installer-tracked-stub

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${PRECOMMIT_BIB_SRC:-$SCRIPT_DIR/pre-commit-bib}"
# shellcheck source=lib/hook-stub.sh
. "$SCRIPT_DIR/lib/hook-stub.sh"

IS_WINDOWS=false
case "${PRECOMMIT_BIB_OS:-$(uname -s)}" in MINGW*|CYGWIN*|MSYS*) IS_WINDOWS=true ;; esac

MODE=install
if [ "${1:-}" = "--check" ]; then MODE=check; shift; fi
if [ $# -eq 0 ]; then
  echo "usage: $(basename "$0") [--check] <repo>..." >&2
  exit 2
fi
if [ ! -f "$SRC" ]; then
  echo "ERROR: $SRC not found" >&2
  exit 2
fi

INSTALLED=0; UP_TO_DATE=0; LEFT_ALONE=0; FINDINGS=0

# 本 script が置いた link か (pre-commit-bib そのもの / 別の場所の pre-commit-bib = base を移した後の古い link)
is_ours_link() {  # $1 = hook
  [ -L "$1" ] || return 1
  [ "$1" -ef "$SRC" ] && return 0
  [ "$(basename "$(readlink "$1")")" = "pre-commit-bib" ]
}

# 本 script (か旧 Step 6) が置いたコピーか
is_ours_copy() {  # $1 = hook
  [ -f "$1" ] && [ ! -L "$1" ] && grep -q "fix-bib-unicode" "$1" 2>/dev/null
}

# repo が自前の pre-commit を宣言していれば、 その入れ方を 1 行で出す
declared_own() {  # $1 = repo
  local repo="$1" p
  for p in scripts/install-hooks.sh install-hooks.sh; do
    if [ -f "$repo/$p" ] && grep -q "pre-commit" "$repo/$p" 2>/dev/null \
       && git -C "$repo" ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then
      echo "run: (cd $repo && sh $p)"; return 0
    fi
  done
  if [ -f "$repo/hooks/pre-commit" ] && git -C "$repo" ls-files --error-unmatch -- hooks/pre-commit >/dev/null 2>&1; then
    echo "run: ln -sf ../../hooks/pre-commit $repo/.git/hooks/pre-commit"; return 0
  fi
  if [ -f "$repo/.githooks/pre-commit" ] && git -C "$repo" ls-files --error-unmatch -- .githooks/pre-commit >/dev/null 2>&1; then
    echo "run: git -C $repo config core.hooksPath .githooks"; return 0
  fi
  return 1
}

chain_note() {  # $1 = hook
  if grep -q "pre-commit-bib" "$1" 2>/dev/null; then
    echo "chains pre-commit-bib"
  else
    echo "does not call pre-commit-bib (LaTeX fix / conflict-marker gate inactive here)"
  fi
}

link_ours() {  # $1 = hook
  rm -f "$1"
  if [ "$IS_WINDOWS" = true ]; then
    cp -f "$SRC" "$1" && chmod +x "$1"
  else
    ln -s "$SRC" "$1"
  fi
}

finding() {  # $1 = repo name, $2 = what is active, $3 = how the repo installs its own
  FINDINGS=$((FINDINGS + 1))
  echo "  ⚠ $1: the repo manages its own pre-commit, but the active pre-commit is $2 → $3"
}

for arg in "$@"; do
  repo="${arg%/}"
  [ -e "$repo/.git" ] || continue
  name="$(basename "$repo")"
  [ -f "$repo/.claude/public-repo.marker" ] && continue
  decl="$(declared_own "$repo" || true)"
  # --check が出すのは「宣言した repo の hook が効いていない」 だけ = 宣言の無い repo は git を呼ばずに飛ばす
  [ "$MODE" = check ] && [ -z "$decl" ] && continue

  hook="$(git -C "$repo" rev-parse --git-path hooks/pre-commit 2>/dev/null)" || continue
  case "$hook" in /*) ;; *) hook="$repo/$hook" ;; esac
  custom_hooks_path="$(git -C "$repo" config --get core.hooksPath 2>/dev/null || true)"

  if [ -L "$hook" ] || [ -e "$hook" ]; then
    if hook_stub_is_tracked "$repo" "$hook"; then
      # repo の中身 (core.hooksPath の track 済み hook / track 済み file への link)
      LEFT_ALONE=$((LEFT_ALONE + 1))
      [ "$MODE" = install ] && echo "  repo-managed: $name ($(chain_note "$hook"))"
    elif is_ours_link "$hook" || is_ours_copy "$hook"; then
      if [ -n "$decl" ]; then
        finding "$name" "claude-config pre-commit-bib" "$decl"
      elif [ "$MODE" = install ]; then
        if [ "$IS_WINDOWS" = true ]; then
          if cmp -s "$hook" "$SRC"; then UP_TO_DATE=$((UP_TO_DATE + 1))
          else link_ours "$hook"; echo "  Updated (copy): $name"; INSTALLED=$((INSTALLED + 1)); fi
        elif [ "$hook" -ef "$SRC" ] && [ -L "$hook" ]; then
          UP_TO_DATE=$((UP_TO_DATE + 1))
        else
          link_ours "$hook"; echo "  Updated (symlink): $name"; INSTALLED=$((INSTALLED + 1))
        fi
      fi
    else
      # 本 script が置いていない pre-commit = 退避も上書きもしない
      LEFT_ALONE=$((LEFT_ALONE + 1))
      if [ "$MODE" = install ]; then
        if [ -L "$hook" ]; then
          echo "  left alone: $name (-> $(readlink "$hook"); $(chain_note "$hook"))"
        else
          echo "  left alone: $name (existing pre-commit; $(chain_note "$hook"))"
        fi
      fi
    fi
  else
    if [ -n "$decl" ]; then
      finding "$name" "missing" "$decl"
    elif [ -n "$custom_hooks_path" ]; then
      # core.hooksPath の先 (repo の中 / 全 repo 共通の dir) には書かない
      LEFT_ALONE=$((LEFT_ALONE + 1))
      [ "$MODE" = install ] && echo "  not installed: $name (core.hooksPath=$custom_hooks_path has no pre-commit)"
    elif [ "$MODE" = install ]; then
      mkdir -p "$(dirname "$hook")"
      link_ours "$hook"
      echo "  Installed: $name"
      INSTALLED=$((INSTALLED + 1))
    fi
  fi
done

if [ "$MODE" = install ]; then
  # 全 repo の link は同じ実体を指すので、 実体 1 つを見れば足りる (#killed-hook-stub)
  hook_exec_heal "$SRC" "pre-commit-bib" 2>&1 | sed 's/^/  /' || true
  echo "  Installed/updated: $INSTALLED repos"
  echo "  Already up to date: $UP_TO_DATE repos"
  echo "  Left alone (not installed by claude-config): $LEFT_ALONE repos"
  [ "$FINDINGS" -gt 0 ] && echo "  Repos whose own pre-commit is not active: $FINDINGS (see ⚠ above)"
  exit 0
fi
[ "$FINDINGS" -eq 0 ]
