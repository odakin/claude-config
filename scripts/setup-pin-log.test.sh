#!/bin/bash
# Run setup.sh Step 2b2 (folder-picker pin agent) in isolation with stub launchctl/defaults.
# Usage: test_step2b2.sh <setup.sh>
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -- "${1:-$ROOT/setup.sh}"
SETUP="$1"
BLOCK="$(awk '/^xml_escape\(\) \{/{print} /^# --- 2b2\./{p=1} /^# --- 2c\./{p=0} p' "$SETUP")"
T="$(mktemp -d)"; fail=0
mkdir -p "$T/bin" "$T/base/claude-config/scripts"; : > "$T/base/claude-config/scripts/pin-claude-cwd.sh"
# stub launchctl: "list <label>" succeeds when $T/loaded exists; bootstrap/bootout toggle it and log the call
cat > "$T/bin/launchctl" <<EOF
#!/bin/bash
echo "\$*" >> "$T/launchctl.log"
case "\$1" in
  list) [ -e "$T/loaded" ] ;;
  bootstrap|load) touch "$T/loaded" ;;
  bootout|unload) rm -f "$T/loaded" ;;
esac
EOF
printf '#!/bin/bash\nexit 0\n' > "$T/bin/defaults"   # desktop app prefs domain exists
chmod +x "$T/bin/launchctl" "$T/bin/defaults"

run() {
    ( export HOME="$T/home" PATH="$T/bin:$PATH"; mkdir -p "$HOME"
      SCRIPT_DIR="$T/base/claude-config"; CLAUDE_DIR="$T/base"; CLAUDE_PIN_CWD="${CLAUDE_PIN_CWD:-}"
      uname() { echo Darwin; }
      eval "$BLOCK" )
}
check() { if eval "$2"; then :; else echo "FAIL: $1"; fail=1; fi; }
PL="$T/home/Library/LaunchAgents/com.claude-config.pin-claude-cwd.plist"

out="$(run)"
check "1 fresh install loads"          '[ -e "$T/loaded" ] && [[ "$out" == *"Installing launchd agent"* ]]'
check "2 log is per-user"              'grep -q "<string>$T/home/Library/Logs/pin-claude-cwd.log</string>" "$PL" && ! grep -q /tmp/ "$PL"'
check "3 log dir exists"               '[ -d "$T/home/Library/Logs" ]'
: > "$T/launchctl.log"; out="$(run)"
check "4 re-run is a no-op"            '[[ "$out" == *"already loaded"* ]] && ! grep -q -E "bootstrap|bootout" "$T/launchctl.log"'
sed -i '' "s#$T/home/Library/Logs/pin-claude-cwd.log#/tmp/pin-claude-cwd.log#" "$PL"   # an old-version plist
: > "$T/launchctl.log"; out="$(run)"
check "5 old plist is replaced"        '[[ "$out" == *"plist changed"* ]] && grep -q bootout "$T/launchctl.log" && grep -q bootstrap "$T/launchctl.log" && ! grep -q /tmp/ "$PL" && [ -e "$T/loaded" ]'
: > "$T/launchctl.log"; out="$(CLAUDE_PIN_CWD=0 run)"
check "6 opt-out still removes"        '[ ! -e "$PL" ] || [[ "$out" == *"SKIPPED"* ]]'

rm -rf "$T"
[ "$fail" = 0 ] && echo "step2b2 block: 6/6 PASS"
exit "$fail"
