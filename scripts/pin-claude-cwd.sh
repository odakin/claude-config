#!/bin/sh
# Pin the Claude.app (Cowork desktop) "New session" folder picker start directory.
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
defaults write com.anthropic.claudefordesktop NSNavLastRootDirectory -string "$TARGET"
