#!/usr/bin/env bash
# sync-hook-settings.sh — 層1 hook の配線 (symlink + settings.json の entry) を hooks/settings-entries.json に揃える (無いものを足すだけ・冪等)
#
# usage: sync-hook-settings.sh [--no-link] [--check] [SETTINGS]
#   SETTINGS   既定 = ~/.claude/settings.json。 hook の置き場は <SETTINGS の dir>/hooks/
#   --no-link  symlink は張らず settings の entry だけ足す (symlink を別の段で張る呼び元用)
#   --check    書かずに、 足りない symlink / entry を列挙して exit 1 (揃っていれば exit 0)
#
# 何をするか:
#   1. link:  entry が参照する hook file (hooks/<name>) の symlink を張る。 無いもの・壊れた symlink
#             (= 指す先が消えた。 例: 他の層から本 repo へ移設された hook) だけを張り直し、 生きている
#             symlink と通常 file (Windows の copy 方式) は触らない。 Windows は copy で置く
#   2. merge: scripts/lib/merge-hook-event.sh で event ごとに無い entry を足す。 既存の entry・他の層が
#             足した entry は触らない (= 削除はしない。 退役 hook の掃除は setup.sh の cleanup が持つ)
#
# 呼び元 (= 3 経路が同じ list と同じ関数を使う):
#   setup.sh Step 2 / setup.sh が生成する post-merge hook (pull だけで新しい hook が効く) /
#   個人層の session 開始 bootstrap (setup.sh を再実行しない machine 向け)
#
# なぜ file に出したか (2026-09-12): hook の list が setup.sh の中の文字列にしか無く、 新しい層1 hook を
#   足しても setup.sh を再実行しない machine では settings に entry が入らず、 hook が走らなかった
#   (post-merge は既存 symlink の更新しかしない)。 list を 1 file にして、 pull の経路からも読めるようにした。
#
# 依存: jq (無ければ何もせず exit 0。 --check では exit 2)。 bash 3.2 compatible。

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRIES="${SYNC_HOOK_ENTRIES:-$ROOT/hooks/settings-entries.json}"
LINK=1
CHECK=0
SETTINGS=""
for arg in "$@"; do
  case "$arg" in
    --no-link) LINK=0 ;;
    --check) CHECK=1 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) SETTINGS="$arg" ;;
  esac
done
SETTINGS="${SETTINGS:-$HOME/.claude/settings.json}"
HOOKS_DST="$(dirname "$SETTINGS")/hooks"

if ! command -v jq >/dev/null 2>&1; then
  echo "sync-hook-settings: jq が無いので何もしない" >&2
  [ "$CHECK" -eq 1 ] && exit 2
  exit 0
fi
[ -f "$ENTRIES" ] || { echo "sync-hook-settings: $ENTRIES が無い" >&2; exit 0; }

missing=0

# ---------- 1. link ----------
if [ "$LINK" -eq 1 ]; then
  case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) copy_mode=1 ;; *) copy_mode=0 ;; esac
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    src="$ROOT/hooks/$name"
    dst="$HOOKS_DST/$name"
    [ -f "$src" ] || continue
    if [ -e "$dst" ]; then
      continue  # 生きている symlink / 通常 file は触らない
    fi
    if [ "$CHECK" -eq 1 ]; then
      echo "  missing link: $name"
      missing=$((missing + 1))
      continue
    fi
    mkdir -p "$HOOKS_DST"
    rm -f "$dst" 2>/dev/null  # 壊れた symlink
    if [ "$copy_mode" -eq 1 ]; then
      cp -f "$src" "$dst" && echo "  Copied hook: $name"
    else
      ln -s "$src" "$dst" && echo "  Linked hook: $name"
    fi
  done < <(jq -r 'to_entries[] | select(.key | startswith("_") | not) | .value[].hooks[]?.command' "$ENTRIES" \
             | sed -e 's#^.*/hooks/##' -e 's/ .*$//' | tr -d '\r' | sort -u)
fi

# ---------- 2. merge ----------
events="$(jq -r 'keys[] | select(startswith("_") | not)' "$ENTRIES" | tr -d '\r')"

if [ "$CHECK" -eq 1 ]; then
  if [ ! -f "$SETTINGS" ]; then
    echo "  missing settings: $SETTINGS"
    exit 1
  fi
  for event in $events; do
    while IFS= read -r cmd; do
      [ -n "$cmd" ] || continue
      if ! jq -e --arg ev "$event" --arg cmd "$cmd" \
          '.hooks[$ev] // [] | map(.hooks[]?.command // "") | any(contains($cmd))' "$SETTINGS" >/dev/null 2>&1; then
        echo "  missing entry: $event $cmd"
        missing=$((missing + 1))
      fi
    done < <(jq -r --arg ev "$event" '.[$ev][].hooks[]?.command | sub("^.*/hooks/"; "")' "$ENTRIES" | tr -d '\r')
  done
  [ "$missing" -eq 0 ] && exit 0
  exit 1
fi

if [ ! -f "$SETTINGS" ]; then
  mkdir -p "$(dirname "$SETTINGS")"
  echo '{}' > "$SETTINGS"
  echo "  Created: $SETTINGS"
fi
# shellcheck source=lib/merge-hook-event.sh
. "$ROOT/scripts/lib/merge-hook-event.sh"
for event in $events; do
  merge_hook_event "$event" "$(jq -c --arg ev "$event" '.[$ev]' "$ENTRIES")" "$SETTINGS"
done
exit 0
