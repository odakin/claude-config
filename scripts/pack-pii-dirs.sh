#!/usr/bin/env bash
# pack-pii-dirs.sh — 個人情報が file 名に出る dir を、1 個の暗号化 tar に畳む (汎用)。
#
# なぜ: git-crypt は **中身しか暗号化しない**。file 名は remote のツリーに平文で残るので、
# `answers/A00X0001-1.jpg` や `records_2025_A00X0002_surname.docx` のような名前は
# それ自体が個人情報になる。tar に畳むとツリーに見えるのは tar 1 個だけで、中の file 名は
# tar 内部に保たれる (= 連番化 + 対応表のような「対応表が壊れたら終わり」の仕組みが要らない)。
#
# 対象 dir は **各 repo の `.pii-pack-dirs`** が宣言する (= repo 固有の知識をこの機構に持たない):
#     <dir>                     … <dir>.tar に畳む
#     <dir><TAB><tar の path>   … tar 名を別に指定 (= dir 名自体に ID が入っている場合)
#     # 行と空行は無視
#
#   pack    … 畳んで追跡から外し .gitignore に入れる (working tree の file は残す)
#             **展開して 1 file ずつ byte 比較**し、1 つでも違えば中断する
#   unpack  … tar を展開して手元に戻す (clone 直後 / 別マシン)
#   check   … tar より新しい file があるか (= 畳み忘れ) を報告
#
# tar 自体が git-crypt の対象 pattern に載っているかは repo 側の .gitattributes 次第。
# ⚠️ 履歴には旧 file 名が残る。これは「これ以上広げない」ための操作。
# ⚠️ pack 後、新しい file は git に入らない (dir が ignore されるため) → check がそれを拾う。

set -euo pipefail
# $0 は相対で渡されうる。 check-all は別 repo に cd するので、 先に絶対化する。
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
REPO="${2:-$(git rev-parse --show-toplevel)}"
cd "$REPO"
CONF=".pii-pack-dirs"
export COPYFILE_DISABLE=1          # macOS の ._ AppleDouble を tar に入れない

# ⚠️ config 不在の guard は pack/unpack/check の直前で行う。 先頭に置くと、
#    config を持たない repo から check-all を呼んだ時に
#    case へ到達せず何も検査されない (2026-09-12 に実際そうなった)。
_require_conf() { [ -f "$CONF" ] || { echo "対象外: $REPO に $CONF が無い"; exit 0; }; }

_entries() { grep -vE '^\s*(#|$)' "$CONF"; }
_dir()  { printf '%s' "$1" | cut -f1; }
_tar()  { local t; t=$(printf '%s' "$1" | cut -f2 -s); [ -n "$t" ] && printf '%s' "$t" || printf '%s.tar' "$(_dir "$1")"; }
_files() { ( cd "$1" && find . -type f ! -name '.DS_Store' | LC_ALL=C sort ); }

do_pack() {
  _require_conf
  while IFS= read -r line; do
    d=$(_dir "$line"); t=$(_tar "$line")
    [ -d "$d" ] || { echo "skip (dir 無し): $d"; continue; }
    n=$(_files "$d" | wc -l | tr -d ' ')
    [ "$n" -eq 0 ] && { echo "skip (file 無し): $d"; continue; }
    echo "── $d → $t  ($n file)"
    ( cd "$d" && _files . | tar -cf "$REPO/$t" -T - )
    tmp=$(mktemp -d); tar -xf "$t" -C "$tmp"; bad=0
    while IFS= read -r f; do
      cmp -s "$d/$f" "$tmp/$f" || { echo "   ✗ 不一致: $f"; bad=1; }
    done < <(_files "$d")
    rm -rf "$tmp"
    [ "$bad" -ne 0 ] && { echo "   中断: byte 比較に失敗。tar を捨てて何も変更しない。"; rm -f "$t"; exit 1; }
    echo "   ✓ $n file を byte 比較で照合"
    git ls-files --error-unmatch "$d" >/dev/null 2>&1 && git rm -r -q --cached "$d"
    git add "$t"
    grep -qxF "/$d/" .gitignore 2>/dev/null || printf '/%s/\n' "$d" >> .gitignore
  done < <(_entries)
  git add .gitignore
  echo; echo "完了。git status を見てから commit すること (working tree の file は消していない)。"
}

do_unpack() {
  _require_conf
  while IFS= read -r line; do
    d=$(_dir "$line"); t=$(_tar "$line")
    [ -f "$t" ] || continue
    mkdir -p "$d"; tar -xf "$t" -C "$d"
    echo "展開: $t → $d/  ($(_files "$d" | wc -l | tr -d ' ') file)"
  done < <(_entries)
}

do_check() {
  _require_conf
  stale=0
  while IFS= read -r line; do
    d=$(_dir "$line"); t=$(_tar "$line")
    [ -d "$d" ] || continue
    if [ ! -f "$t" ]; then
      [ "$(_files "$d" | wc -l | tr -d ' ')" -gt 0 ] && { echo "  ⚠️ 未梱包: $d (tar 無し = git に入っていない)"; stale=1; }
      continue
    fi
    newer=$(find "$d" -type f ! -name '.DS_Store' -newer "$t" | wc -l | tr -d ' ')
    [ "$newer" -gt 0 ] && { echo "  ⚠️ 畳み忘れ: $d に tar より新しい file が $newer 件"; stale=1; }
  done < <(_entries)
  return "$stale"
}

do_check_all() {
  rc=0
  for r in "$HOME"/Claude/*/; do
    [ -f "$r/.pii-pack-dirs" ] || continue
    out=$(cd "$r" && CONF=".pii-pack-dirs" bash "$SELF" check "$r" 2>&1) || rc=1
    [ -n "$out" ] && { echo "  [$(basename "$r")]"; echo "$out"; }
  done
  [ "$rc" -eq 0 ] && echo "  OK: 対象 repo すべて畳み済み"
  return "$rc"
}

case "${1:-}" in
  pack)   do_pack ;;
  check-all) do_check_all ;;
  unpack) do_unpack ;;
  check)  do_check ;;
  *) echo "usage: $0 {pack|unpack|check} [repo]" >&2; exit 2 ;;
esac
