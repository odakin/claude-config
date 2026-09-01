#!/usr/bin/env bash
# setup-codex.sh — claude-config の共有規約を Codex に安全に導入する
#
# Claude Code の setup.sh とは独立している。`~/.claude/`、Claude の hooks、
# settings、LaunchAgent には一切触れない。
#
# Usage:
#   scripts/setup-codex.sh [--replace] [--set-default-effort <level>] [--configure-safe-local]
#
# Installs layer-4 Codex entry points that link to public layer-1 instructions,
# two skills, and the Codex-native hook bundle.
# Existing user-managed targets are refused unless --replace is supplied.
# The default refusal mode preflights every target before making any change;
# replacement preserves a timestamped backup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME must be set}"
CODEX_USER_DIR="${CODEX_USER_DIR:-$USER_HOME/.codex}"
CODEX_WORKSPACE_ROOT="${CODEX_WORKSPACE_ROOT:-$USER_HOME/Documents/Codex}"
REPLACE=0
EFFORT=""
CONFIGURE_SAFE_LOCAL=0

usage() {
  cat <<'EOF'
Usage: setup-codex.sh [--replace] [--set-default-effort <level>] [--configure-safe-local]

Install local Codex entry points that consume claude-config's public
instructions, skills, and hook bundle through symlinks.

  --replace                     Back up and replace an existing non-managed target.
  --set-default-effort <level>  Set model_reasoning_effort in Codex config.toml.
                                Allowed: low, medium, high, xhigh, max, ultra.
  --configure-safe-local        Let Codex autonomously perform safe local work in
                                the workspace, while preserving approvals for
                                external or out-of-scope actions.
  -h, --help                    Show this help.

Environment overrides for testing or nonstandard installs:
  CODEX_USER_DIR, CODEX_WORKSPACE_ROOT
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --replace) REPLACE=1 ;;
    --set-default-effort)
      shift
      [ "$#" -gt 0 ] || { echo "--set-default-effort requires a value" >&2; exit 2; }
      EFFORT="$1"
      ;;
    --configure-safe-local) CONFIGURE_SAFE_LOCAL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$EFFORT" in
  ""|low|medium|high|xhigh|max|ultra) ;;
  *) echo "invalid effort: $EFFORT" >&2; exit 2 ;;
esac

install_link() {
  local source="$1"
  local target="$2"
  local parent
  parent="$(dirname "$target")"
  mkdir -p "$parent"

  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    echo "OK: $target -> $source"
    return
  fi

  if [ -e "$target" ] || [ -L "$target" ]; then
    if [ "$REPLACE" -ne 1 ]; then
      echo "refusing to replace existing target: $target (rerun with --replace)" >&2
      exit 1
    fi
    local backup="${target}.bak-$(date +%Y%m%d-%H%M%S)"
    mv "$target" "$backup"
    echo "Backed up: $target -> $backup"
  fi

  ln -s "$source" "$target"
  echo "Installed: $target -> $source"
}

preflight_link() {
  local source="$1"
  local target="$2"

  if [ ! -e "$source" ]; then
    echo "missing managed source: $source" >&2
    return 1
  fi

  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    return 0
  fi

  if [ -e "$target" ] || [ -L "$target" ]; then
    if [ "$REPLACE" -ne 1 ]; then
      echo "refusing to replace existing target: $target (rerun with --replace)" >&2
      return 1
    fi
  fi
}

remove_legacy_managed_home_agents() {
  local legacy_target="$USER_HOME/AGENTS.md"
  local managed_source="$CONFIG_ROOT/codex/HOME-AGENTS.md"
  if [ -L "$legacy_target" ] && [ "$(readlink "$legacy_target")" = "$managed_source" ]; then
    rm "$legacy_target"
    echo "Migrated: removed legacy managed home instruction link: $legacy_target"
  fi
}

update_codex_config() {
  local config="$CODEX_USER_DIR/config.toml"
  mkdir -p "$CODEX_USER_DIR"
  if [ -f "$config" ]; then
    cp "$config" "${config}.bak-$(date +%Y%m%d-%H%M%S)"
  fi

  python3 - "$config" "$EFFORT" "$CONFIGURE_SAFE_LOCAL" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
effort = sys.argv[2]
configure_safe_local = sys.argv[3] == "1"
text = path.read_text(encoding="utf-8") if path.exists() else ""

def set_top_level(key: str, value: str) -> None:
    global text
    line = f"{key} = {value}"
    pattern = rf"^{re.escape(key)}\s*=.*$"
    table = re.search(r"^\[", text, flags=re.M)
    if table:
        top_level, remainder = text[:table.start()], text[table.start():]
    else:
        top_level, remainder = text, ""
    if re.search(pattern, top_level, flags=re.M):
        top_level = re.sub(pattern, line, top_level, flags=re.M)
    else:
        top_level = top_level.rstrip() + (chr(10) * 2 if top_level.strip() else "") + line + chr(10)
    text = top_level + remainder

if effort:
    set_top_level("model_reasoning_effort", f'"{effort}"')
if configure_safe_local:
    set_top_level("approval_policy", '"on-request"')
    set_top_level("sandbox_mode", '"workspace-write"')
path.write_text(text, encoding="utf-8")
PY
}

preflight_link "$CONFIG_ROOT/codex/HOME-AGENTS.md" "$CODEX_USER_DIR/AGENTS.md"
preflight_link "$CONFIG_ROOT/codex/AGENTS.md" "$CODEX_WORKSPACE_ROOT/AGENTS.md"
preflight_link \
  "$CONFIG_ROOT/codex/skills/claude-config-conventions" \
  "$CODEX_USER_DIR/skills/claude-config-conventions"
preflight_link \
  "$CONFIG_ROOT/codex/skills/claude-config-operations" \
  "$CODEX_USER_DIR/skills/claude-config-operations"
preflight_link \
  "$CONFIG_ROOT/codex/hooks" \
  "$CODEX_USER_DIR/claude-config-hooks"
preflight_link \
  "$CONFIG_ROOT/codex/hooks/hooks.json" \
  "$CODEX_USER_DIR/hooks.json"

remove_legacy_managed_home_agents
install_link "$CONFIG_ROOT/codex/HOME-AGENTS.md" "$CODEX_USER_DIR/AGENTS.md"
install_link "$CONFIG_ROOT/codex/AGENTS.md" "$CODEX_WORKSPACE_ROOT/AGENTS.md"
install_link \
  "$CONFIG_ROOT/codex/skills/claude-config-conventions" \
  "$CODEX_USER_DIR/skills/claude-config-conventions"
install_link \
  "$CONFIG_ROOT/codex/skills/claude-config-operations" \
  "$CODEX_USER_DIR/skills/claude-config-operations"
install_link \
  "$CONFIG_ROOT/codex/hooks" \
  "$CODEX_USER_DIR/claude-config-hooks"
install_link \
  "$CONFIG_ROOT/codex/hooks/hooks.json" \
  "$CODEX_USER_DIR/hooks.json"

if [ -n "$EFFORT" ] || [ "$CONFIGURE_SAFE_LOCAL" -eq 1 ]; then
  update_codex_config
  [ -z "$EFFORT" ] || echo "Set Codex default reasoning effort: $EFFORT"
  [ "$CONFIGURE_SAFE_LOCAL" -eq 0 ] || echo "Configured safe local autonomy."
fi

echo "Codex layer-4 integration installed. Claude Code files were not modified."
