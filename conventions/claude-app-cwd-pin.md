# Pinning the Claude desktop folder picker (`com.claude-config.pin-claude-cwd`)

**macOS only.** Installed **by default** by `setup.sh` (Step 2b2). Opt-out is supported and documented below.

## What it does

The Claude desktop app (Cowork) "New session" **folder picker** opens at the
directory stored in `NSNavLastRootDirectory` under the
`com.anthropic.claudefordesktop` defaults domain — this is standard macOS AppKit
`NSOpenPanel` behavior. When you browse to a different folder in that picker,
the value is **overwritten**, so the next new session opens there instead. Over
time the picker "drifts" away from your workspace.

To keep it pinned, `setup.sh` installs a launchd LaunchAgent that re-writes the
value on a short interval:

- **Agent:** `com.claude-config.pin-claude-cwd` (user LaunchAgent)
- **Script:** `scripts/pin-claude-cwd.sh` — a one-liner `defaults write … NSNavLastRootDirectory`
- **Pins to:** `<base>` = the parent of your `claude-config` checkout (where `setup.sh`
  clones your repos). Passed to the script as `$1` at install time.
- **Interval:** every ~2 seconds (see the throttle note below)
- **Log:** `/tmp/pin-claude-cwd.log` (normally empty)

This only affects the **Claude desktop app's folder picker**. It does not touch
any other app, the CLI, or any file. It is harmless (a no-op in effect) if you
never open the desktop app.

## Why a polling loop (and not a hook / WatchPath)

The value is written by the app through `cfprefsd` (which caches and batches
writes to disk), so a `WatchPaths` trigger on the preferences plist is
unreliable. A short `StartInterval` poll is robust. The script is a trivial
one-liner, so the cost of running it every couple of seconds is negligible.

### ⚠️ launchd throttle gotcha (if you tune the interval)

launchd's default `ThrottleInterval` is **10 seconds** — a job will not relaunch
more than once per `ThrottleInterval` regardless of `StartInterval`. So lowering
`StartInterval` alone does **not** speed it up; you must lower `ThrottleInterval`
too. The installed plist sets **both** to `2`. The 2-second window is the maximum
time the picker can stay on a wrong folder after you manually browse away.

## Opt out

Default-ON on macOS. To disable:

- **Recommended (one step):** `touch ~/.claude/pin-claude-cwd.off`, then run `./setup.sh`.
  With the marker present, `setup.sh` will not (re)install it **and will stop + remove a
  job a previous run already loaded** (so the marker can never lie about an agent that is
  still running). `CLAUDE_PIN_CWD=0 ./setup.sh` does the same for a single run.
- **Manual (without re-running setup):**
  ```sh
  launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.claude-config.pin-claude-cwd.plist
  rm ~/Library/LaunchAgents/com.claude-config.pin-claude-cwd.plist
  touch ~/.claude/pin-claude-cwd.off   # so re-running setup.sh won't reinstall it
  ```

The picker simply reverts to plain last-used behavior when disabled.

## Verify / reload

```sh
launchctl list com.claude-config.pin-claude-cwd          # PID + exit status 0 = OK
defaults read com.anthropic.claudefordesktop NSNavLastRootDirectory   # current pin
# live test: overwrite, wait, confirm auto-revert
defaults write com.anthropic.claudefordesktop NSNavLastRootDirectory -string "/tmp" \
  && sleep 3 && defaults read com.anthropic.claudefordesktop NSNavLastRootDirectory

# reload after editing the plist:
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.claude-config.pin-claude-cwd.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.claude-config.pin-claude-cwd.plist
```

cf. Adding `<base>` to Finder Favorites (a one-click shortcut in the picker's left
sidebar) is orthogonal and complementary.
