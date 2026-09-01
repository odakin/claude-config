#!/usr/bin/env bash
# audit-codex-integration.sh — claude-config の Codex 導入を read-only で確認する
#
# Claude 側には一切書き込まない。managed symlink と Codex config の概況を表示し、
# --repo を渡した場合だけ既存 Git-side gate も確認する。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME must be set}"
CODEX_USER_DIR="${CODEX_USER_DIR:-$USER_HOME/.codex}"
CODEX_WORKSPACE_ROOT="${CODEX_WORKSPACE_ROOT:-$USER_HOME/Documents/Codex}"
REPOS=()
REPO_COUNT=0
ISSUES=0

usage() {
  cat <<'EOF'
Usage: audit-codex-integration.sh [--repo <path>]...

Read-only audit of the claude-config Codex integration.

  --repo <path>  Also inspect the existing Git-side guards in this repository.
  -h, --help     Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      shift
      [ "$#" -gt 0 ] || { echo "--repo requires a path" >&2; exit 2; }
      REPOS+=("$1")
      REPO_COUNT=$((REPO_COUNT + 1))
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

check_link() {
  local label="$1"
  local source="$2"
  local target="$3"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    echo "OK: $label"
    return 0
  fi
  echo "MISSING: $label ($target should link to $source)" >&2
  ISSUES=$((ISSUES + 1))
  return 1
}

personal_source_from_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  sed -n 's/^<!-- personal-source: \(.*\) -->$/\1/p' "$target" | sed -n '1p'
}

public_source_from_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  sed -n 's/^<!-- public-source: \(.*\) -->$/\1/p' "$target" | sed -n '1p'
}

check_personal_global_agents() {
  local target="$CODEX_USER_DIR/AGENTS.md"
  local public_source personal_layer personal_source hooks post_merge extension
  local expected_file
  [ -f "$target" ] && [ ! -L "$target" ] \
    && grep -qxF '<!-- claude-config-codex: global-personal-composite -->' "$target" || return 1

  public_source="$(public_source_from_global_agents)"
  personal_layer="$(personal_source_from_global_agents)"
  personal_source="$personal_layer/codex/AGENTS.md"
  if [ "$public_source" != "$CONFIG_ROOT/codex/HOME-AGENTS.md" ] \
    || [ ! -f "$personal_layer/.claude-personal-layer" ] \
    || [ ! -s "$personal_source" ]; then
    echo "MISSING: managed personal global AGENTS.md sources are no longer valid" >&2
    ISSUES=$((ISSUES + 1))
    return 0
  fi

  expected_file="$(mktemp "${TMPDIR:-/tmp}/audit-codex-personal.XXXXXX")"
  {
    printf '%s\n' '<!-- claude-config-codex: global-personal-composite -->'
    printf '<!-- public-source: %s -->\n' "$public_source"
    printf '<!-- personal-source: %s -->\n' "$personal_layer"
    printf '%s\n\n' '<!-- Generated local state. Re-run setup-codex.sh; do not edit. -->'
    cat "$public_source"
    printf '\n\n<!-- owner-private Codex overlay follows; source remains layer 3 -->\n\n'
    cat "$personal_source"
  } > "$expected_file"
  if cmp -s "$expected_file" "$target"; then
    echo "OK: local L1 + explicit L3 global instruction composite"
  else
    echo "MISSING: managed personal global AGENTS.md is stale or edited; rerun setup-codex.sh --personal-layer" >&2
    ISSUES=$((ISSUES + 1))
  fi
  rm -f "$expected_file"

  hooks="$personal_layer/.git/hooks"
  post_merge="$hooks/post-merge"
  extension="$hooks/post-merge.d/claude-config-codex-personal-layer.sh"
  if [ -x "$extension" ] \
    && grep -qF -- '--refresh-personal-layer' "$extension" 2>/dev/null \
    && [ -f "$post_merge" ] \
    && grep -qF '# claude-config post-merge extensions' "$post_merge" 2>/dev/null; then
    echo "OK: personal-layer pull refresh"
  else
    echo "MISSING: automatic personal-layer pull refresh" >&2
    ISSUES=$((ISSUES + 1))
  fi
  return 0
}

echo "=== Codex layer-4 integration ==="
if ! check_personal_global_agents; then
  check_link "local global AGENTS.md entry point" \
    "$CONFIG_ROOT/codex/HOME-AGENTS.md" \
    "$CODEX_USER_DIR/AGENTS.md" || true
fi
check_link "local Codex-workspace AGENTS.md entry point" \
  "$CONFIG_ROOT/codex/AGENTS.md" \
  "$CODEX_WORKSPACE_ROOT/AGENTS.md" || true
check_link "local claude-config-conventions skill" \
  "$CONFIG_ROOT/codex/skills/claude-config-conventions" \
  "$CODEX_USER_DIR/skills/claude-config-conventions" || true
check_link "local claude-config-operations skill" \
  "$CONFIG_ROOT/codex/skills/claude-config-operations" \
  "$CODEX_USER_DIR/skills/claude-config-operations" || true
check_link "local claude-config hook implementation" \
  "$CONFIG_ROOT/codex/hooks" \
  "$CODEX_USER_DIR/claude-config-hooks" || true
check_link "local Codex hook configuration" \
  "$CONFIG_ROOT/codex/hooks/hooks.json" \
  "$CODEX_USER_DIR/hooks.json" || true

LEGACY_HOME_AGENTS="$USER_HOME/AGENTS.md"
if [ -L "$LEGACY_HOME_AGENTS" ] \
  && [ "$(readlink "$LEGACY_HOME_AGENTS")" = "$CONFIG_ROOT/codex/HOME-AGENTS.md" ]; then
  echo "MIGRATION REQUIRED: legacy managed home AGENTS.md link remains: $LEGACY_HOME_AGENTS" >&2
  ISSUES=$((ISSUES + 1))
fi

CONFIG_FILE="$CODEX_USER_DIR/config.toml"
if [ -f "$CONFIG_FILE" ]; then
  echo "Codex config: $CONFIG_FILE"
  python3 - "$CONFIG_FILE" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
top = re.split(r"^\[", text, maxsplit=1, flags=re.M)[0]
for key in ("model", "model_reasoning_effort", "approval_policy", "sandbox_mode"):
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", top, flags=re.M)
    print(f"  {key} = {match.group(1)}" if match else f"  {key} = (not set)")
PY
else
  echo "NOTE: Codex config not found: $CONFIG_FILE"
fi

echo "NOTE: These are layer-4 links to public layer-1 source, or an explicitly selected L1+L3 local composite. A fresh clone has no effect until this installer runs on that machine."
echo "NOTE: Codex requires a one-time trust review before user-level hooks run; inspect it in the Codex client."

if [ "$REPO_COUNT" -gt 0 ]; then
for requested_repo in "${REPOS[@]}"; do
  if ! repo_root="$(git -C "$requested_repo" rev-parse --show-toplevel 2>/dev/null)"; then
    echo "INVALID: not a Git repository: $requested_repo" >&2
    ISSUES=$((ISSUES + 1))
    continue
  fi

  hooks_dir="$(git -C "$repo_root" config --get core.hooksPath 2>/dev/null || true)"
  if [ -z "$hooks_dir" ]; then
    hooks_dir="$(git -C "$repo_root" rev-parse --git-path hooks 2>/dev/null)"
  elif [ "${hooks_dir#/}" = "$hooks_dir" ]; then
    hooks_dir="$repo_root/$hooks_dir"
  fi

  echo "=== Git-side guards: $repo_root ==="
  if [ -f "$repo_root/.claude/public-repo.marker" ]; then
    for guard in \
      "pre-commit:public-precommit-runner.sh" \
      "commit-msg:commit-msg-leak-guard-runner.sh"; do
      hook="${guard%%:*}"
      marker="${guard#*:}"
      if [ -f "$hooks_dir/$hook" ] && grep -qF "$marker" "$hooks_dir/$hook" 2>/dev/null; then
        echo "OK: public $hook gate"
      else
        echo "MISSING: public $hook gate" >&2
        ISSUES=$((ISSUES + 1))
      fi
    done
  elif [ -e "$hooks_dir/pre-commit" ] && grep -q "fix-bib-unicode" "$hooks_dir/pre-commit" 2>/dev/null; then
    echo "OK: shared LaTeX/conflict pre-commit gate"
  else
    echo "NOTE: no managed pre-commit gate detected (this may be intentional)."
  fi
done
fi

if [ "$ISSUES" -gt 0 ]; then
  echo "Codex integration audit found $ISSUES issue(s)." >&2
  exit 1
fi

echo "Codex integration audit completed without required-link or requested-gate findings."
