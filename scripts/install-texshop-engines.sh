#!/bin/bash
# install-texshop-engines.sh — 層1 の texshop/*.engine を TeXShop の Engines dir に symlink する (無ければ足す・在れば触らない)。
#
# 使い方:
#   bash scripts/install-texshop-engines.sh                 既定 = この repo の texshop/ → ~/Library/TeXShop/Engines/
#   bash scripts/install-texshop-engines.sh --src DIR --engines DIR   置き場を指定 (呼び元の test 用)
#   bash scripts/install-texshop-engines.sh --selftest      自分の検査 (一時 dir だけを触る)
#
# 振る舞い:
#   - 入れた engine ごとに 1 行を出す。 何もしなければ無音 (= 毎回呼んでよい)。
#   - TeXShop の Engines dir (TeXShop を 1 度起動すると作られる) が無ければ何もしない (TeXShop の無い機・未起動の機)。
#   - 同名の file・symlink が既に在れば置き換えない (本人の engine を守る。 層1 の engine を更新したいときは、 symlink なら更新は自動で届く)。
#   - 原稿は先頭の `% !TEX TS-program = <engine の名前>` で engine を選ぶ。 開いたままの原稿には効かない (閉じて開き直す)。
#
# 呼び元: setup.sh (macOS) / 個人層の SessionStart の bootstrap (毎 session)。
# 正本 = conventions/latex.md#texshop-engines
set -u

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/texshop"
dst="$HOME/Library/TeXShop/Engines"

install_engines() {  # $1 = src dir, $2 = Engines dir
  local s="$1" d="$2" f t
  [ -d "$s" ] && [ -d "$d" ] || return 0
  for f in "$s"/*.engine; do
    [ -f "$f" ] || continue
    t="$d/$(basename "$f")"
    if [ -e "$t" ] || [ -L "$t" ]; then
      continue
    fi
    if ln -s "$f" "$t" 2>/dev/null; then
      echo "  $(basename "$f") → $d (原稿の \`% !TEX TS-program = $(basename "$f" .engine)\` で選ばれる。 開いている原稿は閉じて開き直すと効く)"
    fi
  done
}

selftest() {
  local tmp out fail=0
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/src" "$tmp/eng"
  printf '#!/bin/bash\n' > "$tmp/src/a.engine"
  printf '#!/bin/bash\n' > "$tmp/src/b.engine"
  printf 'mine\n' > "$tmp/eng/b.engine"
  out="$(install_engines "$tmp/src" "$tmp/eng")"
  if [ -L "$tmp/eng/a.engine" ] && [ "$(readlink "$tmp/eng/a.engine")" = "$tmp/src/a.engine" ]; then echo "PASS 未導入の engine を symlink する"; else echo "FAIL symlink が無い"; fail=1; fi
  case "$out" in *"a.engine"*"TS-program = a"*) echo "PASS 入れた engine と選び方を 1 行で出す" ;; *) echo "FAIL 出力が違う: $out"; fail=1 ;; esac
  if [ "$(cat "$tmp/eng/b.engine")" = "mine" ] && [ ! -L "$tmp/eng/b.engine" ]; then echo "PASS 本人の同名の file は触らない"; else echo "FAIL 本人の file を置き換えた"; fail=1; fi
  out="$(install_engines "$tmp/src" "$tmp/eng")"
  if [ -z "$out" ]; then echo "PASS 入っていれば無音"; else echo "FAIL 2 回目に出た: $out"; fail=1; fi
  out="$(install_engines "$tmp/src" "$tmp/none")"
  if [ -z "$out" ] && [ ! -e "$tmp/none" ]; then echo "PASS Engines dir が無ければ何もしない"; else echo "FAIL Engines dir を作った・出た"; fail=1; fi
  rm -rf "$tmp"
  return "$fail"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --src) src="$2"; shift 2 ;;
    --engines) dst="$2"; shift 2 ;;
    --selftest) selftest; exit $? ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
install_engines "$src" "$dst"
