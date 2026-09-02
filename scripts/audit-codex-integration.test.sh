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
ln -s "$CONFIG_ROOT/codex/HOME-AGENTS.md" "$TEST_CODEX_DIR/AGENTS.md"
ln -s "$CONFIG_ROOT/codex/AGENTS.md" "$TEST_WORKSPACE/AGENTS.md"
ln -s "$CONFIG_ROOT/codex/skills/claude-config-conventions" \
  "$TEST_CODEX_DIR/skills/claude-config-conventions"
ln -s "$CONFIG_ROOT/codex/skills/claude-config-operations" \
  "$TEST_CODEX_DIR/skills/claude-config-operations"
ln -s "$CONFIG_ROOT/codex/skills/codex-automation-routing" \
  "$TEST_CODEX_DIR/skills/codex-automation-routing"
ln -s "$CONFIG_ROOT/codex/hooks" "$TEST_CODEX_DIR/claude-config-hooks"
ln -s "$CONFIG_ROOT/codex/hooks/hooks.json" "$TEST_CODEX_DIR/hooks.json"
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

rm "$TEST_CODEX_DIR/skills/codex-automation-routing"
if HOME="$TEST_HOME" \
  CODEX_USER_DIR="$TEST_CODEX_DIR" \
  CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" >/dev/null 2>&1; then
  echo "expected audit to fail for a missing managed skill" >&2
  exit 1
fi

# --- composite mode: public-layer pull refresh coverage ---
PERSONAL_LAYER="$TEMP_ROOT/personal-layer"
mkdir -p "$PERSONAL_LAYER/codex"
: > "$PERSONAL_LAYER/.claude-personal-layer"
printf '# test overlay\n' > "$PERSONAL_LAYER/codex/AGENTS.md"
git -C "$PERSONAL_LAYER" init -q
COMPOSITE_HOME="$TEMP_ROOT/home-composite"
COMPOSITE_CODEX="$COMPOSITE_HOME/.codex"
COMPOSITE_WS="$COMPOSITE_HOME/Documents/Codex"
mkdir -p "$COMPOSITE_HOME"
HOME="$COMPOSITE_HOME" \
CODEX_USER_DIR="$COMPOSITE_CODEX" \
CODEX_WORKSPACE_ROOT="$COMPOSITE_WS" \
  "$SCRIPT_DIR/setup-codex.sh" --personal-layer "$PERSONAL_LAYER" >/dev/null

GOOD_POST_MERGE="$TEMP_ROOT/post-merge-with-refresh"
printf '%s\n' 'setup-codex.sh --refresh-personal-layer' > "$GOOD_POST_MERGE"
BAD_POST_MERGE="$TEMP_ROOT/post-merge-without-refresh"
printf '#!/bin/sh\n' > "$BAD_POST_MERGE"

HOME="$COMPOSITE_HOME" \
CODEX_USER_DIR="$COMPOSITE_CODEX" \
CODEX_WORKSPACE_ROOT="$COMPOSITE_WS" \
CLAUDE_CONFIG_POST_MERGE="$GOOD_POST_MERGE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" >/dev/null

if HOME="$COMPOSITE_HOME" \
  CODEX_USER_DIR="$COMPOSITE_CODEX" \
  CODEX_WORKSPACE_ROOT="$COMPOSITE_WS" \
  CLAUDE_CONFIG_POST_MERGE="$BAD_POST_MERGE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" > "$TEMP_ROOT/audit-stale.out" 2>&1; then
  echo "expected audit to fail when the public-layer post-merge lacks the refresh" >&2
  exit 1
fi
grep -q "public-layer pull refresh" "$TEMP_ROOT/audit-stale.out"

echo "audit-codex-integration tests passed"
