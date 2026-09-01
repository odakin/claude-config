#!/usr/bin/env bash
# setup-codex.sh — claude-config の共有規約を Codex に安全に導入する
#
# Claude Code の setup.sh とは独立している。`~/.claude/`、Claude の hooks、
# settings、LaunchAgent には一切触れない。
#
# Usage:
#   scripts/setup-codex.sh [--replace] [--set-default-effort <level>] [--configure-safe-local] [--personal-layer <path>]
#
# Installs layer-4 Codex entry points that link to public layer-1 instructions,
# two skills, and the Codex-native hook bundle. When an owner explicitly opts
# in with --personal-layer, it instead renders an L4-only global instruction
# composite from the public source and that layer's short Codex overlay.
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
PERSONAL_LAYER=""
PERSONAL_AGENTS=""
REFRESH_PERSONAL_LAYER=0

usage() {
  cat <<'EOF'
Usage: setup-codex.sh [--replace] [--set-default-effort <level>] [--configure-safe-local] [--personal-layer <path>]

Install local Codex entry points that consume claude-config's public
instructions, skills, and hook bundle through symlinks. An explicitly selected
personal layer is consumed only through an L4-generated global-instruction
composite; its contents never enter this repository.

  --replace                     Back up and replace an existing non-managed target.
  --set-default-effort <level>  Set model_reasoning_effort in Codex config.toml.
                                Allowed: minimal, low, medium, high, xhigh.
  --configure-safe-local        Let Codex autonomously perform safe local work in
                                the workspace, while preserving approvals for
                                external or out-of-scope actions.
  --personal-layer <path>       Explicitly bind one marked layer-3 directory.
                                Requires <path>/codex/AGENTS.md, a concise
                                Codex-specific private overlay. A local
                                post-merge refresh is installed when safe.
  --refresh-personal-layer [path]
                                Refresh an existing managed personal composite.
                                Internal post-merge entry point; it never
                                creates a new binding.
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
    --personal-layer)
      shift
      [ "$#" -gt 0 ] || { echo "--personal-layer requires a directory" >&2; exit 2; }
      PERSONAL_LAYER="$1"
      ;;
    --refresh-personal-layer)
      REFRESH_PERSONAL_LAYER=1
      if [ "$#" -gt 1 ] && [ "${2#--}" = "$2" ]; then
        shift
        PERSONAL_LAYER="$1"
      fi
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# Codex config reference の実在値のみ (2026-09 時点 verify 済)。 無効値を config.toml に
# 書くと Codex 側の起動 error になるため、 whitelist は製品の受理集合に一致させる。
case "$EFFORT" in
  ""|minimal|low|medium|high|xhigh) ;;
  *) echo "invalid effort: $EFFORT (allowed: minimal, low, medium, high, xhigh)" >&2; exit 2 ;;
esac

if [ "$REFRESH_PERSONAL_LAYER" -eq 1 ] && { [ -n "$EFFORT" ] || [ "$CONFIGURE_SAFE_LOCAL" -eq 1 ]; }; then
  echo "--refresh-personal-layer cannot change Codex configuration" >&2
  exit 2
fi

if [ "$REFRESH_PERSONAL_LAYER" -eq 1 ] && [ "$REPLACE" -eq 1 ]; then
  echo "--refresh-personal-layer cannot replace an existing binding" >&2
  exit 2
fi

canonical_directory() {
  (cd "$1" && pwd -P)
}

configure_personal_layer() {
  [ -n "$PERSONAL_LAYER" ] || return 0
  if [ ! -d "$PERSONAL_LAYER" ]; then
    echo "personal layer is not a directory: $PERSONAL_LAYER" >&2
    exit 2
  fi
  PERSONAL_LAYER="$(canonical_directory "$PERSONAL_LAYER")"
  if [ ! -f "$PERSONAL_LAYER/.claude-personal-layer" ]; then
    echo "personal layer marker is missing: $PERSONAL_LAYER/.claude-personal-layer" >&2
    exit 2
  fi
  PERSONAL_AGENTS="$PERSONAL_LAYER/codex/AGENTS.md"
  if [ ! -s "$PERSONAL_AGENTS" ]; then
    echo "personal Codex overlay is missing or empty: $PERSONAL_AGENTS" >&2
    exit 2
  fi
}

public_global_agents() {
  printf '%s\n' "$CONFIG_ROOT/codex/HOME-AGENTS.md"
}

managed_personal_header() {
  local public_source
  public_source="$(public_global_agents)"
  printf '%s\n' '<!-- claude-config-codex: global-personal-composite -->'
  printf '<!-- public-source: %s -->\n' "$public_source"
  printf '<!-- personal-source: %s -->\n' "$PERSONAL_LAYER"
  printf '%s\n' '<!-- Generated local state. Re-run setup-codex.sh; do not edit. -->'
}

is_managed_public_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  [ -L "$target" ] && [ "$(readlink "$target")" = "$(public_global_agents)" ]
}

is_managed_personal_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  local public_source
  public_source="$(public_global_agents)"
  [ -f "$target" ] && [ ! -L "$target" ] \
    && grep -qxF '<!-- claude-config-codex: global-personal-composite -->' "$target" \
    && grep -qxF "<!-- public-source: $public_source -->" "$target" \
    && grep -qxF "<!-- personal-source: $PERSONAL_LAYER -->" "$target"
}

personal_layer_from_managed_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  [ -f "$target" ] && [ ! -L "$target" ] || return 1
  sed -n 's/^<!-- personal-source: \(.*\) -->$/\1/p' "$target" | sed -n '1p'
}

render_personal_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  local temporary
  mkdir -p "$CODEX_USER_DIR"
  temporary="$(umask 077; mktemp "${target}.tmp.XXXXXX")"
  {
    managed_personal_header
    printf '\n'
    cat "$(public_global_agents)"
    printf '\n\n<!-- owner-private Codex overlay follows; source remains layer 3 -->\n\n'
    cat "$PERSONAL_AGENTS"
  } > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$target"
}

preflight_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  if [ -z "$PERSONAL_LAYER" ]; then
    preflight_link "$(public_global_agents)" "$target"
    return
  fi

  if [ ! -e "$target" ] && [ ! -L "$target" ]; then
    return
  fi
  if is_managed_public_global_agents || is_managed_personal_global_agents; then
    return
  fi
  if [ "$REPLACE" -ne 1 ]; then
    echo "refusing to replace existing global AGENTS.md: $target (rerun with --replace)" >&2
    return 1
  fi
}

install_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  if [ -z "$PERSONAL_LAYER" ]; then
    install_link "$(public_global_agents)" "$target"
    return
  fi

  if [ -e "$target" ] || [ -L "$target" ]; then
    if ! is_managed_public_global_agents && ! is_managed_personal_global_agents; then
      local backup="${target}.bak-$(date +%Y%m%d-%H%M%S)"
      mv "$target" "$backup"
      echo "Backed up: $target -> $backup"
    fi
  fi
  render_personal_global_agents
  echo "Installed: managed local global AGENTS.md composite"
}

append_post_merge_dispatcher() {
  local post_merge="$1"
  if grep -qF '# claude-config post-merge extensions' "$post_merge" 2>/dev/null; then
    return
  fi
  cat >> "$post_merge" <<'EOF'

# claude-config post-merge extensions
# Local extension scripts are optional and must never make git pull fail.
POST_MERGE_EXTENSION_DIR="$(dirname "$0")/post-merge.d"
for POST_MERGE_EXTENSION in "$POST_MERGE_EXTENSION_DIR"/*.sh; do
  [ -x "$POST_MERGE_EXTENSION" ] || continue
  "$POST_MERGE_EXTENSION" "$@" || \
    echo "[claude-config] WARNING: post-merge extension failed: $POST_MERGE_EXTENSION" >&2
done
EOF
}

write_post_merge_dispatcher() {
  local post_merge="$1"
  cat > "$post_merge" <<'EOF'
#!/usr/bin/env bash
# managed-by: claude-config setup-codex-personal-dispatch
# Dispatch optional local post-merge extensions without failing git pull.

# claude-config post-merge extensions
# Local extension scripts are optional and must never make git pull fail.
POST_MERGE_EXTENSION_DIR="$(dirname "$0")/post-merge.d"
for POST_MERGE_EXTENSION in "$POST_MERGE_EXTENSION_DIR"/*.sh; do
  [ -x "$POST_MERGE_EXTENSION" ] || continue
  "$POST_MERGE_EXTENSION" "$@" || \
    echo "[claude-config] WARNING: post-merge extension failed: $POST_MERGE_EXTENSION" >&2
done
EOF
  chmod +x "$post_merge"
}

install_personal_refresh_hook() {
  local hooks_dir="$PERSONAL_LAYER/.git/hooks"
  local post_merge extension_dir extension
  [ -d "$hooks_dir" ] || {
    echo "NOTE: personal layer is not a Git checkout; automatic refresh after pull is unavailable."
    return
  }
  post_merge="$hooks_dir/post-merge"
  if [ ! -e "$post_merge" ]; then
    write_post_merge_dispatcher "$post_merge"
  elif grep -qF '# managed-by: claude-config setup-dropbox-refs' "$post_merge" 2>/dev/null; then
    append_post_merge_dispatcher "$post_merge"
  elif ! grep -qF '# claude-config post-merge extensions' "$post_merge" 2>/dev/null \
    && ! grep -qF '# managed-by: claude-config setup-codex-personal-dispatch' "$post_merge" 2>/dev/null; then
    echo "NOTE: existing personal-layer post-merge hook is user-managed; automatic Codex refresh was not attached."
    return
  fi

  extension_dir="$hooks_dir/post-merge.d"
  extension="$extension_dir/claude-config-codex-personal-layer.sh"
  mkdir -p "$extension_dir"
  if [ -e "$extension" ] \
    && ! grep -qF '# managed-by: claude-config setup-codex-personal-layer' "$extension" 2>/dev/null \
    && [ "$REPLACE" -ne 1 ]; then
    echo "NOTE: existing personal-layer refresh extension is user-managed; leaving it unchanged."
    return
  fi
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%s\n' '# managed-by: claude-config setup-codex-personal-layer'
    printf '%s\n' '# Refresh only an already selected L4 Codex personal composite.'
    printf 'CODEX_USER_DIR=%q CODEX_WORKSPACE_ROOT=%q %q --refresh-personal-layer %q\n' \
      "$CODEX_USER_DIR" "$CODEX_WORKSPACE_ROOT" "$SCRIPT_DIR/setup-codex.sh" "$PERSONAL_LAYER"
  } > "$extension"
  chmod 700 "$extension"
  echo "Installed: personal-layer post-merge refresh extension"
}

configure_personal_layer

if [ "$REFRESH_PERSONAL_LAYER" -eq 1 ]; then
  if [ -z "$PERSONAL_LAYER" ]; then
    PERSONAL_LAYER="$(personal_layer_from_managed_global_agents || true)"
  fi
  if [ -z "$PERSONAL_LAYER" ]; then
    echo "SKIP: no managed Codex personal-layer binding to refresh."
    exit 0
  fi
  configure_personal_layer
  if ! is_managed_personal_global_agents; then
    echo "SKIP: managed Codex global instructions no longer select this personal layer."
    exit 0
  fi
  render_personal_global_agents
  echo "Refreshed: managed local global AGENTS.md composite"
  exit 0
fi

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

preflight_global_agents
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
install_global_agents
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

if [ -n "$PERSONAL_LAYER" ]; then
  install_personal_refresh_hook
fi

echo "Codex layer-4 integration installed. Claude Code files were not modified."
