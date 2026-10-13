#!/bin/bash
# Run the proposed Step 7 (Hammerspoon opt-in) block in isolation. macOS with /Applications/Hammerspoon.app only.
# Usage: test_step7.sh <proposed setup.sh>
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -- "${1:-$ROOT/setup.sh}"
BLOCK="$(awk '/^HS_SRC="\$SCRIPT_DIR\/hammerspoon\/init.lua"/{p=1} /^# --- 8\. Install pre-commit/{p=0} p' "$1")"
[ -n "$BLOCK" ] || { echo "FAIL: block not found"; exit 1; }
[ -d /Applications/Hammerspoon.app ] || { echo "SKIP: Hammerspoon.app not installed"; exit 0; }
T="$(mktemp -d)"; fail=0
mkdir -p "$T/base/claude-config/hammerspoon"; echo '-- cfg' > "$T/base/claude-config/hammerspoon/init.lua"
SRC="$T/base/claude-config/hammerspoon/init.lua"

run() {  # run <home> [VAR=val ...]
    local home="$1"; shift
    ( HOME="$home"; SCRIPT_DIR="$T/base/claude-config"; REPO_DIRNAME=claude-config
      GH_USER=someone; LAYER=""; WANT_HAMMERSPOON=0; unset CLAUDE_HAMMERSPOON
      for kv in "$@"; do export "${kv?}"; done
      eval "$BLOCK" )
}
check() { if eval "$2"; then :; else echo "FAIL: $1"; fail=1; fi; }

h="$T/h1"; mkdir -p "$h"; out="$(run "$h")"
check "1 default skips"            '[ ! -e "$h/.hammerspoon/init.lua" ] && [[ "$out" == *"SKIPPED (opt-in)"* ]]'
h="$T/h2"; mkdir -p "$h"; out="$(run "$h" WANT_HAMMERSPOON=1)"
check "2 --hammerspoon installs"   '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$SRC" ]'
out="$(run "$h")"
check "3 re-run keeps it"          '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$SRC" ] && [[ "$out" == *"already installed"* ]]'
out="$(run "$h" CLAUDE_HAMMERSPOON=0)"
check "4 =0 leaves it alone"       '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$SRC" ] && [[ "$out" == *"触らない"* ]]'
h="$T/h5"; mkdir -p "$h" "$T/prefs/hammerspoon"; echo '-- local' > "$T/prefs/hammerspoon/local.lua"
out="$(run "$h" LAYER="$T/prefs")"
check "5 personal layer opts in"   '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$SRC" ] && [ -L "$h/.hammerspoon/local.lua" ]'
h="$T/h6"; mkdir -p "$h"; out="$(run "$h" GH_USER=odakin)"
check "6 owner opts in"            '[[ "$out" == *"(owner)"* ]] && [ -L "$h/.hammerspoon/init.lua" ]'
h="$T/h7"; mkdir -p "$h/.hammerspoon"; echo '-- mine' > "$h/.hammerspoon/init.lua"; out="$(run "$h")"
check "7 own init.lua untouched"   '[ ! -L "$h/.hammerspoon/init.lua" ] && [ "$(cat "$h/.hammerspoon/init.lua")" = "-- mine" ] && [ ! -e "$h/.hammerspoon/init.lua.bak" ]'
h="$T/h8"; mkdir -p "$h/.hammerspoon" "$T/dotfiles/hammerspoon"; ln -s "$T/dotfiles/hammerspoon/init.lua" "$h/.hammerspoon/init.lua"; out="$(run "$h")"
check "8 other repo link untouched" '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$T/dotfiles/hammerspoon/init.lua" ]'

h="$T/h9"; mkdir -p "$h"; out="$(run "$h" CLAUDE_HAMMERSPOON=1)"
check "9 environment opt-in" '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$SRC" ]'
h="$T/h10"; mkdir -p "$h/.hammerspoon" "$T/other/claude-config/hammerspoon"
echo '-- other' > "$T/other/claude-config/hammerspoon/init.lua"
ln -s "$T/other/claude-config/hammerspoon/init.lua" "$h/.hammerspoon/init.lua"
out="$(run "$h")"
check "10 same-named checkout untouched" '[ "$(readlink "$h/.hammerspoon/init.lua")" = "$T/other/claude-config/hammerspoon/init.lua" ]'

rm -rf "$T"
[ "$fail" = 0 ] && echo "step7 block: 10/10 PASS"
exit "$fail"
