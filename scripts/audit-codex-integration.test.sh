#!/usr/bin/env bash
# audit-codex-integration.test.sh — Codex integration audit の fixture test

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

TEST_HOME="$TEMP_ROOT/home"
TEST_CODEX_DIR="$TEST_HOME/.codex"
TEST_WORKSPACE="$TEST_HOME/Documents/Codex"
mkdir -p "$TEST_CODEX_DIR/skills" "$TEST_WORKSPACE"
ln -s "$CONFIG_ROOT/codex/HOME-AGENTS.md" "$TEST_HOME/AGENTS.md"
ln -s "$CONFIG_ROOT/codex/AGENTS.md" "$TEST_WORKSPACE/AGENTS.md"
ln -s "$CONFIG_ROOT/codex/skills/claude-config-conventions" \
  "$TEST_CODEX_DIR/skills/claude-config-conventions"
ln -s "$CONFIG_ROOT/codex/skills/claude-config-operations" \
  "$TEST_CODEX_DIR/skills/claude-config-operations"
printf 'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n' \
  > "$TEST_CODEX_DIR/config.toml"

HOME="$TEST_HOME" \
CODEX_USER_DIR="$TEST_CODEX_DIR" \
CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" >/dev/null

TEST_REPO="$TEMP_ROOT/repo"
mkdir -p "$TEST_REPO/.claude" "$TEST_REPO/.hooks"
git -C "$TEST_REPO" init -q
git -C "$TEST_REPO" config core.hooksPath .hooks
touch "$TEST_REPO/.claude/public-repo.marker"
printf '%s\n' 'public-precommit-runner.sh' > "$TEST_REPO/.hooks/pre-commit"
printf '%s\n' 'commit-msg-leak-guard-runner.sh' > "$TEST_REPO/.hooks/commit-msg"

HOME="$TEST_HOME" \
CODEX_USER_DIR="$TEST_CODEX_DIR" \
CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" --repo "$TEST_REPO" >/dev/null

rm "$TEST_REPO/.hooks/commit-msg"
if HOME="$TEST_HOME" \
  CODEX_USER_DIR="$TEST_CODEX_DIR" \
  CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" --repo "$TEST_REPO" >/dev/null 2>&1; then
  echo "expected audit to fail for a missing public Git-side gate" >&2
  exit 1
fi

rm "$TEST_CODEX_DIR/skills/claude-config-operations"
if HOME="$TEST_HOME" \
  CODEX_USER_DIR="$TEST_CODEX_DIR" \
  CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" >/dev/null 2>&1; then
  echo "expected audit to fail for a missing managed skill" >&2
  exit 1
fi

echo "audit-codex-integration tests passed"
