#!/usr/bin/env bash
# setup-codex.test.sh — setup-codex.sh の隔離・冪等・非上書き性を検証する

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

TEST_HOME="$TEMP_ROOT/home"
TEST_CODEX_DIR="$TEST_HOME/.codex"
TEST_WORKSPACE="$TEST_HOME/Documents/Codex"
mkdir -p "$TEST_CODEX_DIR" "$TEST_HOME"
python3 - "$TEST_CODEX_DIR/config.toml" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(
    'model = "gpt-5.6-terra"\n'
    'model_reasoning_effort = "low"\n\n'
    '[desktop]\n'
    'followUpQueueMode = "queue"\n',
    encoding="utf-8",
)
PY

run_setup() {
  HOME="$TEST_HOME" \
  CODEX_USER_DIR="$TEST_CODEX_DIR" \
  CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/setup-codex.sh" "$@"
}

run_setup --set-default-effort high --configure-safe-local

[ "$(readlink "$TEST_WORKSPACE/AGENTS.md")" = "$CONFIG_ROOT/codex/AGENTS.md" ]
[ "$(readlink "$TEST_CODEX_DIR/skills/claude-config-conventions")" = "$CONFIG_ROOT/codex/skills/claude-config-conventions" ]
grep -qx 'model_reasoning_effort = "high"' "$TEST_CODEX_DIR/config.toml"
grep -qx 'approval_policy = "on-request"' "$TEST_CODEX_DIR/config.toml"
grep -qx 'sandbox_mode = "workspace-write"' "$TEST_CODEX_DIR/config.toml"
awk '
  BEGIN { table = 0; effort = approval = sandbox = desktop = bad = 0 }
  /^\[/ { table = 1 }
  /^model_reasoning_effort = "high"$/ {
    if (table) bad = 1
    effort += 1
  }
  /^approval_policy = "on-request"$/ {
    if (table) bad = 1
    approval += 1
  }
  /^sandbox_mode = "workspace-write"$/ {
    if (table) bad = 1
    sandbox += 1
  }
  /^followUpQueueMode = "queue"$/ { desktop += 1 }
  END {
    if (bad || effort != 1 || approval != 1 || sandbox != 1 || desktop != 1) exit 1
  }
' "$TEST_CODEX_DIR/config.toml"
[ ! -e "$TEST_HOME/.claude" ]

run_setup --set-default-effort high --configure-safe-local

rm "$TEST_WORKSPACE/AGENTS.md"
printf 'user instruction\n' > "$TEST_WORKSPACE/AGENTS.md"
if run_setup >/dev/null 2>&1; then
  echo "expected setup to refuse a user-managed AGENTS.md" >&2
  exit 1
fi
grep -qx 'user instruction' "$TEST_WORKSPACE/AGENTS.md"

echo "setup-codex tests passed"
