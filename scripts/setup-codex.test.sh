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

run_setup_for() {
  local home="$1"
  local codex_dir="$2"
  local workspace="$3"
  shift 3
  HOME="$home" \
  CODEX_USER_DIR="$codex_dir" \
  CODEX_WORKSPACE_ROOT="$workspace" \
  "$SCRIPT_DIR/setup-codex.sh" "$@"
}

run_setup --set-default-effort high --configure-safe-local

[ "$(readlink "$TEST_CODEX_DIR/AGENTS.md")" = "$CONFIG_ROOT/codex/HOME-AGENTS.md" ]
[ "$(readlink "$TEST_WORKSPACE/AGENTS.md")" = "$CONFIG_ROOT/codex/AGENTS.md" ]
[ "$(readlink "$TEST_CODEX_DIR/skills/claude-config-conventions")" = "$CONFIG_ROOT/codex/skills/claude-config-conventions" ]
[ "$(readlink "$TEST_CODEX_DIR/skills/claude-config-operations")" = "$CONFIG_ROOT/codex/skills/claude-config-operations" ]
[ "$(readlink "$TEST_CODEX_DIR/claude-config-hooks")" = "$CONFIG_ROOT/codex/hooks" ]
[ "$(readlink "$TEST_CODEX_DIR/hooks.json")" = "$CONFIG_ROOT/codex/hooks/hooks.json" ]
grep -q '^## Four-layer boundary$' "$TEST_CODEX_DIR/AGENTS.md"
grep -q '^## Autonomous in-scope work$' "$TEST_CODEX_DIR/AGENTS.md"
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

PERSONAL_LAYER="$TEMP_ROOT/personal-layer"
mkdir -p "$PERSONAL_LAYER/codex" "$PERSONAL_LAYER/.git/hooks"
: > "$PERSONAL_LAYER/.claude-personal-layer"
printf '%s\n' '# private Codex fixture' 'INITIAL_PERSONAL_OVERLAY' > "$PERSONAL_LAYER/codex/AGENTS.md"
cat > "$PERSONAL_LAYER/.git/hooks/post-merge" <<'EOF'
#!/usr/bin/env bash
# managed-by: claude-config setup-dropbox-refs
true
EOF
chmod +x "$PERSONAL_LAYER/.git/hooks/post-merge"
PERSONAL_LAYER="$(cd "$PERSONAL_LAYER" && pwd -P)"

run_setup --personal-layer "$PERSONAL_LAYER"

[ ! -L "$TEST_CODEX_DIR/AGENTS.md" ]
grep -qx '<!-- claude-config-codex: global-personal-composite -->' "$TEST_CODEX_DIR/AGENTS.md"
grep -qx "<!-- personal-source: $PERSONAL_LAYER -->" "$TEST_CODEX_DIR/AGENTS.md"
grep -qx 'INITIAL_PERSONAL_OVERLAY' "$TEST_CODEX_DIR/AGENTS.md"
grep -q '^# Global Codex conventions$' "$TEST_CODEX_DIR/AGENTS.md"
[ "$(stat -f '%Lp' "$TEST_CODEX_DIR/AGENTS.md")" = "600" ]
grep -qF '# claude-config post-merge extensions' "$PERSONAL_LAYER/.git/hooks/post-merge"
PERSONAL_REFRESH="$PERSONAL_LAYER/.git/hooks/post-merge.d/claude-config-codex-personal-layer.sh"
[ -x "$PERSONAL_REFRESH" ]
grep -qF -- '--refresh-personal-layer' "$PERSONAL_REFRESH"

printf '%s\n' 'UPDATED_PERSONAL_OVERLAY' >> "$PERSONAL_LAYER/codex/AGENTS.md"
"$PERSONAL_LAYER/.git/hooks/post-merge" 0 0 0 >/dev/null
grep -qx 'UPDATED_PERSONAL_OVERLAY' "$TEST_CODEX_DIR/AGENTS.md"

HOME="$TEST_HOME" \
CODEX_USER_DIR="$TEST_CODEX_DIR" \
CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" >/dev/null

run_setup --replace
[ "$(readlink "$TEST_CODEX_DIR/AGENTS.md")" = "$CONFIG_ROOT/codex/HOME-AGENTS.md" ]

CONFLICT_HOME="$TEMP_ROOT/conflict-home"
CONFLICT_CODEX_DIR="$CONFLICT_HOME/.codex"
CONFLICT_WORKSPACE="$CONFLICT_HOME/Documents/Codex"
mkdir -p "$CONFLICT_CODEX_DIR"
printf 'user hook configuration\n' > "$CONFLICT_CODEX_DIR/hooks.json"

if run_setup_for "$CONFLICT_HOME" "$CONFLICT_CODEX_DIR" "$CONFLICT_WORKSPACE" \
  --set-default-effort high --configure-safe-local >/dev/null 2>&1; then
  echo "expected setup to refuse a user-managed hooks.json" >&2
  exit 1
fi

grep -qx 'user hook configuration' "$CONFLICT_CODEX_DIR/hooks.json"
[ ! -e "$CONFLICT_CODEX_DIR/AGENTS.md" ]
[ ! -e "$CONFLICT_WORKSPACE/AGENTS.md" ]
[ ! -e "$CONFLICT_CODEX_DIR/skills/claude-config-conventions" ]
[ ! -e "$CONFLICT_CODEX_DIR/skills/claude-config-operations" ]
[ ! -e "$CONFLICT_CODEX_DIR/claude-config-hooks" ]
[ ! -e "$CONFLICT_CODEX_DIR/config.toml" ]

run_setup_for "$CONFLICT_HOME" "$CONFLICT_CODEX_DIR" "$CONFLICT_WORKSPACE" --replace
[ "$(readlink "$CONFLICT_CODEX_DIR/hooks.json")" = "$CONFIG_ROOT/codex/hooks/hooks.json" ]
hook_backup="$(find "$CONFLICT_CODEX_DIR" -maxdepth 1 -type f -name 'hooks.json.bak-*' -print -quit)"
[ -n "$hook_backup" ]
grep -qx 'user hook configuration' "$hook_backup"

ln -s "$CONFIG_ROOT/codex/HOME-AGENTS.md" "$TEST_HOME/AGENTS.md"

run_setup --set-default-effort high --configure-safe-local

[ ! -e "$TEST_HOME/AGENTS.md" ]

HOME="$TEST_HOME" \
CODEX_USER_DIR="$TEST_CODEX_DIR" \
CODEX_WORKSPACE_ROOT="$TEST_WORKSPACE" \
  "$SCRIPT_DIR/audit-codex-integration.sh" >/dev/null

rm "$TEST_CODEX_DIR/AGENTS.md"
printf 'user instruction\n' > "$TEST_CODEX_DIR/AGENTS.md"
if run_setup >/dev/null 2>&1; then
  echo "expected setup to refuse a user-managed global AGENTS.md" >&2
  exit 1
fi
grep -qx 'user instruction' "$TEST_CODEX_DIR/AGENTS.md"

run_setup --replace
[ "$(readlink "$TEST_CODEX_DIR/AGENTS.md")" = "$CONFIG_ROOT/codex/HOME-AGENTS.md" ]
backup=""
for candidate in "$TEST_CODEX_DIR"/AGENTS.md.bak-*; do
  if grep -qx 'user instruction' "$candidate"; then
    backup="$candidate"
    break
  fi
done
[ -n "$backup" ]

echo "setup-codex tests passed"
