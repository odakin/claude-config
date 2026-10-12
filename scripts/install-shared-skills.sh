#!/usr/bin/env bash
# install-shared-skills.sh — claude-config の skills/<name>/ (誰でも使う skill、 例 = /wrap) を Claude Code と Codex の skill の置き場に配線する (個人層・本人の skill が同名で在れば、 そちらを残す)
#
# usage: install-shared-skills.sh [--check] [--quiet] [--claude-dir DIR] [--codex-dir DIR] [--codex-only] [--selftest]
#   --claude-dir  Claude Code の設定 dir (既定 ~/.claude)。 skill は <DIR>/skills/<name>
#   --codex-dir   Codex の home (既定 = $CODEX_HOME か ~/.codex。 ただし --claude-dir を既定から変えたときは
#                 指定しない限り Codex 側は触らない = test が本物の ~/.codex を触らないため)
#   --codex-only  Codex 側だけ (scripts/setup-codex.sh が呼ぶ)
#   --check       書かずに、 配線が足りない skill を列挙して exit 1 (揃っていれば exit 0)
#   --quiet       変えたときだけ出す (pull・session 開始から呼ぶとき)
#
# 何をするか (skill ごと・置き場ごと。 冪等):
#   - 無い → 置く。 macOS / Linux = symlink、 Windows (Git Bash / MSYS / Cygwin) = copy + 印の file
#     (.claude-config-shared-skill)。 copy は印がある時だけ、 中身が違えば作り直す (= pull の修正が届く)
#   - 壊れた symlink (指す先が消えた) → 置き直す
#   - 本 repo の skill を指す symlink → そのまま
#   - それ以外 (個人層の skill への symlink・本人が置いた dir・印の無い copy) → 触らない。 個人層の同名の skill が優先
#     (= その skill が本 repo の skill を手順の正本として指し、 その人の値だけを持つ = conventions/closing-sweep.md#personal-skill)
#   - Codex: 個人層の宣言 (claude-config-personal-skills.json の state) が同じ名前を持つなら触らない (個人層の installer が管理する)
#
# 呼び元: scripts/sync-hook-settings.sh (= setup.sh Step 2 / setup.sh が生成する post-merge hook / 個人層の session 開始の bootstrap
#   の 3 経路が呼ぶ) → pull だけで新しい skill が全員に届く。 Codex は scripts/setup-codex.sh も呼ぶ。
# 依存: bash 3.2 / ln / cp / diff / readlink (macOS・Linux・Git Bash に標準で在る。 readlink -f は使わない)
# 規約: conventions/closing-sweep.md#personal-skill / OS の違い = conventions/windows-msys.md、 Codex = codex/PARITY.md#wrap-workflow-integration

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${SHARED_SKILLS_SRC:-$ROOT/skills}"
MARK=".claude-config-shared-skill"
CHECK=0; QUIET=0; CLAUDE_DIR=""; CODEX_DIR=""; SELFTEST=0; CODEX_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --quiet) QUIET=1 ;;
    --claude-dir) CLAUDE_DIR="$2"; shift ;;
    --codex-dir) CODEX_DIR="$2"; shift ;;
    --codex-only) CODEX_ONLY=1 ;;
    --selftest) SELFTEST=1 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install-shared-skills: 知らない引数: $1" >&2; exit 2 ;;
  esac
  shift
done

copy_mode=0
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) copy_mode=1 ;; esac
[ "${SHARED_SKILLS_COPY_MODE:-0}" = "1" ] && copy_mode=1

say() { [ "$QUIET" -eq 1 ] || echo "$@"; }

# copy の中身が元と同じか (印の file は比べない)
same_copy() {  # $1 = src, $2 = dst
  diff -rq -x "$MARK" "$1" "$2" >/dev/null 2>&1
}

# 置き場 1 つに skill 1 つを配線する。 戻り値 0 = 揃った / 1 = 足りない (--check) / 0 で何も出さない = 触らない
wire_one() {  # $1 = src, $2 = dst, $3 = label, $4 = codex state file (or "")
  local src="$1" dst="$2" label="$3" state="$4" name
  name="$(basename "$dst")"
  if [ -n "$state" ] && [ -f "$state" ] && grep -q "\"$name\"[[:space:]]*:" "$state" 2>/dev/null; then
    return 0   # Codex の個人層の宣言が持つ名前 = 個人層の installer の管轄
  fi
  if [ -L "$dst" ]; then
    if [ "$(readlink "$dst")" = "$src" ]; then
      return 0
    fi
    if [ -e "$dst" ]; then
      say "  kept: $label (別の skill を指している = 個人層・本人の skill が優先)"
      return 0
    fi
    if [ "$CHECK" -eq 1 ]; then echo "  broken link: $label"; return 1; fi
    rm -f "$dst"   # 壊れた symlink = 指す先が消えた
  elif [ -e "$dst" ]; then
    if [ -f "$dst/$MARK" ]; then
      same_copy "$src" "$dst" && return 0
      if [ "$CHECK" -eq 1 ]; then echo "  stale copy: $label"; return 1; fi
      rm -rf "$dst"
    else
      say "  kept: $label (本人の skill が在る = そちらが優先)"
      return 0
    fi
  elif [ "$CHECK" -eq 1 ]; then
    echo "  missing: $label"; return 1
  fi
  mkdir -p "$(dirname "$dst")"
  if [ "$copy_mode" -eq 1 ]; then
    cp -R "$src" "$dst" && printf '%s\n' "$src" > "$dst/$MARK" && echo "  copied: $label"
  else
    ln -s "$src" "$dst" && echo "  linked: $label -> $src"
  fi
}

run() {
  local claude_dir codex_dir rc=0 src name
  claude_dir="${CLAUDE_DIR:-$HOME/.claude}"
  codex_dir="$CODEX_DIR"
  if [ -z "$codex_dir" ] && [ -z "$CLAUDE_DIR" ]; then
    codex_dir="${CODEX_HOME:-$HOME/.codex}"
  fi
  [ -d "$SRC_DIR" ] || return 0
  for src in "$SRC_DIR"/*/; do
    src="${src%/}"
    [ -f "$src/SKILL.md" ] || continue
    name="$(basename "$src")"
    if [ "$CODEX_ONLY" -eq 0 ] && [ -d "$claude_dir" ]; then
      wire_one "$src" "$claude_dir/skills/$name" "Claude Code skill $name" "" || rc=1
    fi
    if [ -n "$codex_dir" ] && [ -d "$codex_dir" ]; then
      wire_one "$src" "$codex_dir/skills/$name" "Codex skill $name" "$codex_dir/claude-config-personal-skills.json" || rc=1
    fi
  done
  return $rc
}

selftest() {
  local t fails=0 out
  t="$(mktemp -d "${TMPDIR:-/tmp}/shared-skills.XXXXXX")"
  mkdir -p "$t/src/demo" "$t/claude" "$t/codex" "$t/personal/demo"
  printf -- '---\nname: demo\ndescription: x\n---\nbody\n' > "$t/src/demo/SKILL.md"
  printf -- '---\nname: demo\ndescription: mine\n---\n' > "$t/personal/demo/SKILL.md"
  ok() { if eval "$2"; then echo "  ok: $1"; else echo "  NG: $1"; fails=$((fails + 1)); fi; }
  S() { SHARED_SKILLS_SRC="$t/src" bash "$0" --claude-dir "$t/claude" --codex-dir "$t/codex" "$@"; }

  S --quiet >/dev/null
  ok "無い → symlink を置く (Claude / Codex)" '[ "$(readlink "$t/claude/skills/demo")" = "$t/src/demo" ] && [ "$(readlink "$t/codex/skills/demo")" = "$t/src/demo" ]'
  ok "揃っていれば --check は 0" 'S --check >/dev/null'
  out="$(S --quiet)"; ok "2 回目は何もしない (冪等・無出力)" '[ -z "$out" ]'
  rm "$t/claude/skills/demo"; ln -s "$t/personal/demo" "$t/claude/skills/demo"
  S --quiet >/dev/null
  ok "個人層の skill への symlink は残す (個人層が優先)" '[ "$(readlink "$t/claude/skills/demo")" = "$t/personal/demo" ]'
  rm "$t/claude/skills/demo"; ln -s "$t/gone/demo" "$t/claude/skills/demo"
  ok "壊れた symlink は --check で出る" '! S --check >/dev/null'
  S --quiet >/dev/null
  ok "壊れた symlink は置き直す" '[ "$(readlink "$t/claude/skills/demo")" = "$t/src/demo" ]'
  rm "$t/claude/skills/demo"; mkdir -p "$t/claude/skills/demo"; echo own > "$t/claude/skills/demo/SKILL.md"
  S --quiet >/dev/null
  ok "本人が置いた dir (印なし) は触らない" '[ "$(cat "$t/claude/skills/demo/SKILL.md")" = own ]'
  rm -rf "$t/claude/skills/demo" "$t/codex/skills/demo"
  printf '{"version":1,"skills":{"demo":"/x/skill/demo"}}\n' > "$t/codex/claude-config-personal-skills.json"
  S --quiet >/dev/null
  ok "Codex: 個人層の宣言が持つ名前は触らない" '[ ! -e "$t/codex/skills/demo" ] && [ ! -L "$t/codex/skills/demo" ]'
  rm -f "$t/codex/claude-config-personal-skills.json"
  rm -rf "$t/claude/skills" "$t/codex/skills"
  SHARED_SKILLS_COPY_MODE=1 S --quiet >/dev/null
  ok "Windows (copy): 印つきの copy を置く" '[ -f "$t/claude/skills/demo/SKILL.md" ] && [ ! -L "$t/claude/skills/demo" ] && [ -f "$t/claude/skills/demo/'"$MARK"'" ]'
  echo changed >> "$t/src/demo/SKILL.md"
  ok "Windows (copy): 元が変わると --check が出す" '! SHARED_SKILLS_COPY_MODE=1 S --check >/dev/null'
  SHARED_SKILLS_COPY_MODE=1 S --quiet >/dev/null
  ok "Windows (copy): 元が変わると作り直す" 'grep -q changed "$t/claude/skills/demo/SKILL.md"'
  rm -rf "$t/claude2"; mkdir -p "$t/claude2"
  SHARED_SKILLS_SRC="$t/src" HOME="$t/fakehome" bash "$0" --claude-dir "$t/claude2" --quiet >/dev/null
  ok "--claude-dir だけなら Codex 側は触らない (test が本物の ~/.codex を触らない)" '[ ! -e "$t/fakehome/.codex" ]'
  rm -rf "$t/c3" "$t/x3"; mkdir -p "$t/c3" "$t/x3"
  SHARED_SKILLS_SRC="$t/src" bash "$0" --claude-dir "$t/c3" --codex-dir "$t/x3" --codex-only --quiet >/dev/null
  ok "--codex-only は Claude 側を触らない" '[ ! -e "$t/c3/skills" ] && [ -L "$t/x3/skills/demo" ]'
  rm -rf "$t"
  [ "$fails" -eq 0 ] && echo "selftest: PASS" && return 0
  echo "selftest: FAIL ($fails)"; return 1
}

if [ "$SELFTEST" -eq 1 ]; then selftest; exit $?; fi
run
