#!/bin/sh
# pin-claude-cwd.sh — Claude.app folder picker 起点固定 (= NSNavLastRootDirectory を `$1` に固定、 read-first で drift 時のみ write、 setup.sh Step 2b2 の launchd から 1 秒間隔で呼ばれる、 macOS 限定、 conventions/claude-app-cwd-pin.md)
# Pin the Claude.app (Claude Code desktop) "New session" folder picker start directory.
#
# The picker opens at the value of `NSNavLastRootDirectory` in the
# `com.anthropic.claudefordesktop` defaults domain (macOS AppKit NSOpenPanel
# standard behavior). Navigating to another folder OVERWRITES that value, so the
# next picker opens there instead. To keep it pinned, a launchd LaunchAgent
# (com.claude-config.pin-claude-cwd) re-writes it on a short interval.
#
# Arg $1 = directory to pin (default: $HOME). setup.sh passes <base> (the parent
# of the claude-config checkout = where your repos live).
#
# Opt out: see conventions/claude-app-cwd-pin.md.
# macOS only (no-op elsewhere — `defaults` is a macOS tool).

TARGET="${1:-$HOME}"
# Write ONLY when the stored value actually differs. In the common steady state
# (already pinned) this is just a read, so the agent does not mark the prefs
# domain dirty / trigger a cfprefsd disk flush on every tick — it writes only
# right after the picker drifted. (Read and write cost ~the same CPU; the win is
# avoiding tens of thousands of redundant prefs writes per day.)
cur=$(defaults read com.anthropic.claudefordesktop NSNavLastRootDirectory 2>/dev/null)
[ "$cur" = "$TARGET" ] || defaults write com.anthropic.claudefordesktop NSNavLastRootDirectory -string "$TARGET"
