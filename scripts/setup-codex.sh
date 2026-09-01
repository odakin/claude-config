#!/usr/bin/env bash
# setup-codex.sh — claude-config の共有規約を Codex に安全に導入する
#
# Claude Code の setup.sh とは独立している。`~/.claude/`、Claude の hooks、
# settings、LaunchAgent には一切触れない。
#
# Usage:
#   scripts/setup-codex.sh [--replace] [--set-default-effort <level>] [--configure-safe-local]
#
# Installs symlinks for the Codex workspace instruction file and the
# claude-config-conventions skill. Existing user-managed targets are refused
# unless --replace is supplied; replacement preserves a timestamped backup.

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

Install claude-config's Codex workspace instructions and skill as symlinks.

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

install_link "$CONFIG_ROOT/codex/AGENTS.md" "$CODEX_WORKSPACE_ROOT/AGENTS.md"
install_link \
  "$CONFIG_ROOT/codex/skills/claude-config-conventions" \
  "$CODEX_USER_DIR/skills/claude-config-conventions"

if [ -n "$EFFORT" ] || [ "$CONFIGURE_SAFE_LOCAL" -eq 1 ]; then
  update_codex_config
  [ -z "$EFFORT" ] || echo "Set Codex default reasoning effort: $EFFORT"
  [ "$CONFIGURE_SAFE_LOCAL" -eq 0 ] || echo "Configured safe local autonomy."
fi

echo "Codex integration installed. Claude Code files were not modified."
