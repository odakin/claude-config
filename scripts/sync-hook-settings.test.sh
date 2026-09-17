#!/usr/bin/env bash
# sync-hook-settings.test.sh — 層1 hook の配線 (symlink + settings の entry) を揃える script の test
#
# 固定する性質:
#   - 空の環境で 1 回走らせると、 list の全 event の entry と、 参照先 hook の symlink が揃う
#   - 2 回目は何も足さない (冪等) / 他の層が足した entry は残る
#   - 壊れた symlink (= 移設で指す先が消えた) は張り直し、 生きている通常 file は触らない
#   - --check は書かずに不足を列挙して exit 1、 揃っていれば exit 0
#   - list の command はすべて hooks/ に実在する file を指す (typo で配線が silent に死なない)
#   - setup.sh に hook の list を文字列で持ち直していない (= 二重管理に戻っていない)

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SYNC="$HERE/sync-hook-settings.sh"
ENTRIES="$ROOT/hooks/settings-entries.json"
pass=0; fail=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ok() { pass=$((pass + 1)); }
ng() { fail=$((fail + 1)); echo "FAIL: $1"; [ -n "${2:-}" ] && printf '  got: %s\n' "$2"; }

command -v jq >/dev/null 2>&1 || { echo "SKIP: jq が無い"; exit 0; }

S="$TMP/claude/settings.json"
events="$(jq -r 'keys[] | select(startswith("_") | not)' "$ENTRIES")"

# --check: settings が無い → exit 1
bash "$SYNC" --check "$S" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 1 ] && ok || ng "--check は settings 不在で exit 1" "rc=$rc"

out="$(bash "$SYNC" "$S" 2>&1)"
[ -f "$S" ] && ok || ng "settings.json を作る"
for ev in $events; do
  want="$(jq -r --arg ev "$ev" '.[$ev] | length' "$ENTRIES")"
  got="$(jq -r --arg ev "$ev" '.hooks[$ev] // [] | length' "$S")"
  [ "$want" = "$got" ] && ok || ng "$ev の entry 数 (want $want)" "$got"
done
while IFS= read -r name; do
  [ -L "$TMP/claude/hooks/$name" ] && [ "$(readlink "$TMP/claude/hooks/$name")" = "$ROOT/hooks/$name" ] \
    && ok || ng "symlink: $name"
done < <(jq -r 'to_entries[] | select(.key | startswith("_") | not) | .value[].hooks[]?.command' "$ENTRIES" \
           | sed -e 's#^.*/hooks/##' -e 's/ .*$//' | sort -u)

bash "$SYNC" --check "$S" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && ok || ng "--check は揃った後 exit 0" "rc=$rc"
out="$(bash "$SYNC" "$S" 2>&1)"
[ -z "$out" ] && ok || ng "2 回目は何も足さない (冪等)" "$out"

# 他の層の entry は残り、 足りない分だけ足される
printf '%s\n' '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"~/.claude/hooks/other-layer-hook.sh"}]}]}}' > "$TMP/s2.json"
bash "$SYNC" --no-link "$TMP/s2.json" >/dev/null 2>&1
jq -e '[.hooks.Stop[].hooks[].command] | any(contains("other-layer-hook.sh"))' "$TMP/s2.json" >/dev/null \
  && ok || ng "他の層の Stop entry を消さない"
want="$(jq -r '.Stop | length' "$ENTRIES")"
got="$(jq -r '.hooks.Stop | length' "$TMP/s2.json")"
[ "$got" = "$((want + 1))" ] && ok || ng "Stop に層1の entry を足す (want $((want + 1)))" "$got"
[ ! -d "$TMP/hooks" ] && ok || ng "--no-link は symlink を張らない"

# 壊れた symlink は張り直す / 生きている通常 file は触らない
first="$(jq -r '.SessionStart[0].hooks[0].command' "$ENTRIES" | sed -e 's#^.*/hooks/##' -e 's/ .*$//')"
rm -f "$TMP/claude/hooks/$first"; ln -s "$TMP/moved-away/$first" "$TMP/claude/hooks/$first"
second="$(jq -r '.SessionStart[1].hooks[0].command' "$ENTRIES" | sed -e 's#^.*/hooks/##' -e 's/ .*$//')"
rm -f "$TMP/claude/hooks/$second"; echo "local copy" > "$TMP/claude/hooks/$second"
bash "$SYNC" "$S" >/dev/null 2>&1
[ "$(readlink "$TMP/claude/hooks/$first")" = "$ROOT/hooks/$first" ] && ok || ng "壊れた symlink を張り直す"
[ "$(cat "$TMP/claude/hooks/$second")" = "local copy" ] && ok || ng "通常 file (copy 方式) は触らない"

# list の command は実在する hook file を指す
while IFS= read -r name; do
  [ -f "$ROOT/hooks/$name" ] && ok || ng "list の hook が hooks/ に無い: $name"
done < <(jq -r 'to_entries[] | select(.key | startswith("_") | not) | .value[].hooks[]?.command' "$ENTRIES" \
           | sed -e 's#^.*/hooks/##' -e 's/ .*$//' | sort -u)

# setup.sh は list を文字列で持たない (= 二重管理に戻っていない)
if grep -qE "^[A-Z_]+_ENTRIES='\[" "$ROOT/setup.sh"; then
  ng "setup.sh に hook の list が文字列で残っている (hooks/settings-entries.json に一本化する)"
else
  ok
fi

# 退役 registry と list が矛盾しない (= 同じ hook を毎回足して毎回外す、 にならない) + 掃除を setup.sh に hardcode していない
RETIRED="$ROOT/hooks/retired-hooks.txt"
while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in
    *:*) ev="${line%%:*}"; name="${line#*:}" ;;
    *)   ev=""; name="$line" ;;
  esac
  if jq -e --arg ev "$ev" --arg n "/$name" \
      '[to_entries[] | select(.key | startswith("_") | not) | select($ev == "" or .key == $ev)
        | .value[].hooks[]?.command | split(" ") | .[] | select(endswith($n))] | length > 0' "$ENTRIES" >/dev/null 2>&1; then
    ng "retired-hooks.txt の $line が settings-entries.json にも在る (足して外すを毎回繰り返す)"
  else
    ok
  fi
done < <(sed 's/#.*//' "$RETIRED" 2>/dev/null | awk 'NF {print $1}')
if grep -q 'Removing obsolete' "$ROOT/setup.sh"; then
  ng "setup.sh に退役 hook の掃除が hardcode で残っている (hooks/retired-hooks.txt に書く)"
else
  ok
fi

# sync が退役 registry の hook を外す (end-to-end: 足す + 外す)
T3="$(mktemp -d "${TMPDIR:-/tmp}/sync-hook-retired.XXXXXX")"
mkdir -p "$T3/hooks"
ln -s "$ROOT/hooks/gone-hook.sh" "$T3/hooks/gone-hook.sh"
echo '{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/gone-hook.sh"}]}]}}' > "$T3/settings.json"
printf 'gone-hook.sh  # test\n' > "$T3/retired.txt"
SYNC_HOOK_RETIRED="$T3/retired.txt" bash "$ROOT/scripts/sync-hook-settings.sh" --check "$T3/settings.json" >/dev/null 2>&1 \
  && ng "--check が退役 hook の残骸を不足に数えない" || ok
SYNC_HOOK_RETIRED="$T3/retired.txt" bash "$ROOT/scripts/sync-hook-settings.sh" "$T3/settings.json" >/dev/null 2>&1
if grep -q 'gone-hook.sh' "$T3/settings.json" || [ -L "$T3/hooks/gone-hook.sh" ]; then
  ng "sync が退役 hook を外さない"
else
  ok
fi
SYNC_HOOK_RETIRED="$T3/retired.txt" bash "$ROOT/scripts/sync-hook-settings.sh" --check "$T3/settings.json" >/dev/null 2>&1 \
  && ok || ng "外した後の --check が clean にならない"
rm -rf "$T3"

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
