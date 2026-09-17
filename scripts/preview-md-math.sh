#!/bin/bash
# preview-md-math.sh — 数式入りの Markdown を MathJax つき HTML にして browser で開く。
#
# Claude Code の desktop app の右パネルは、 Markdown の中の TeX 数式
# (\( \) / \[ \] / $ $) を描かない。 数式を含む .md を人に見せるときは、
# この script で HTML に変換して browser で開く (pandoc が必要)。
#
# usage:
#   preview-md-math.sh [--out DIR] [--no-open] FILE.md [FILE.md ...]
#     --out DIR   出力先 (既定 = 最初の FILE が在る git repo の build/preview、
#                 repo の外なら FILE と同じ dir の .preview)
#     --no-open   変換だけして開かない (環境変数 NO_OPEN=1 でも同じ)
#   出力した HTML の path を 1 行ずつ stdout に出す。
#
# 出力先は git の管理外に置く (repo の .gitignore に build/ を足す)。
# 変換した HTML は、 その時点の内容の写しで、 .md を直しても更新されない。
# .md を編集した turn では、 もう一度変換してから見せる。
# MathJax は CDN から読むので、 offline では数式が描かれない。
set -euo pipefail

out=""
open_after=1
[ "${NO_OPEN:-0}" = 1 ] && open_after=0
files=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --no-open) open_after=0; shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) files+=("$1"); shift ;;
  esac
done
[ ${#files[@]} -gt 0 ] || { echo "usage: $0 [--out DIR] [--no-open] FILE.md ..." >&2; exit 2; }
command -v pandoc >/dev/null || { echo "pandoc が見つからない" >&2; exit 3; }

first_dir="$(cd "$(dirname "${files[0]}")" && pwd)"
root="$(git -C "$first_dir" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$out" ]; then
  if [ -n "$root" ]; then out="$root/build/preview"; else out="$first_dir/.preview"; fi
fi
mkdir -p "$out"

for f in "${files[@]}"; do
  abs="$(cd "$(dirname "$f")" && pwd)/$(basename "$f")"
  if [ -n "$root" ] && [ "${abs#"$root"/}" != "$abs" ]; then rel="${abs#"$root"/}"; else rel="$(basename "$f")"; fi
  name="$(printf '%s' "${rel%.md}" | tr '/' '_').html"
  pandoc "$abs" \
    -f markdown+tex_math_single_backslash+tex_math_dollars-yaml_metadata_block \
    -s --mathjax --toc --metadata title="$rel" \
    -V lang=ja -V maxwidth=46em -o "$out/$name"
  echo "$out/$name"
  if [ "$open_after" = 1 ]; then
    if command -v open >/dev/null; then open "$out/$name"; elif command -v xdg-open >/dev/null; then xdg-open "$out/$name"; fi
  fi
done
