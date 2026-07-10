#!/usr/bin/env bash
# setup-dropbox-refs.sh — personal layer の dropbox-collabs.yaml を読んで symlink を生成
# claude-config/scripts/setup-dropbox-refs.sh
#
# Read a personal-layer YAML registry of "collaboration name → Dropbox
# subpath" mappings, and create per-repo `<base>/<name>/dropbox-refs`
# symlinks pointing into the user's Dropbox install.
#
# Idempotent. Safe to re-run after every YAML edit, git pull, or as a
# claude-config setup.sh step. Silent on no-change. Prints CREATED /
# UPDATED on changes, WARN on missing repo dirs or missing Dropbox targets,
# ERROR (non-zero exit) only on unrecoverable failures (bad YAML, no
# Dropbox).
#
# Usage:
#   setup-dropbox-refs.sh <yaml-path> [base-dir]
#
# Defaults:
#   base-dir = parent of the yaml file's parent (typically ~/Claude when
#              the yaml lives in ~/Claude/<personal-layer>/)
#
# YAML schema (mapping form):
#
#   collaborations:
#     <repo-name>:
#       subpath: <Dropbox-relative path>
#       description: optional, human-readable
#     another-repo:
#       subpath: Some/Other/Path
#
# For each entry, creates:
#   <base-dir>/<name>/dropbox-refs -> <DBROOT>/<subpath>
#
# Skipped (with stderr warning, exit still 0) when:
#   - Repo dir <base-dir>/<name> does not exist (collaboration not cloned
#     locally yet)
#   - Dropbox subpath does not exist (folder not synced, or shared invite
#     not yet accepted)
#
# Hard error (exit non-zero) when:
#   - YAML missing or unparseable
#   - Cannot resolve Dropbox install root
#   - Destination already exists as a regular file or directory (refuses
#     to clobber non-symlink user data)
#
# See conventions/dropbox-refs.md for the surrounding convention.

set -euo pipefail

YAML="${1:-}"
BASE_DIR="${2:-}"

if [ -z "$YAML" ]; then
    echo "Usage: $(basename "$0") <yaml-path> [base-dir]" >&2
    exit 2
fi
if [ ! -f "$YAML" ]; then
    echo "ERROR: yaml file not found: $YAML" >&2
    exit 2
fi

if [ -z "$BASE_DIR" ]; then
    # Default: parent of the yaml's parent.
    # e.g. ~/Claude/<personal-layer>/dropbox-collabs.yaml → ~/Claude
    BASE_DIR="$(cd "$(dirname "$(dirname "$YAML")")" && pwd -P)"
fi

if [ ! -d "$BASE_DIR" ]; then
    echo "ERROR: base dir not found: $BASE_DIR" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
DROPBOX_ROOT_SCRIPT="$SCRIPT_DIR/dropbox-root.sh"
if [ ! -x "$DROPBOX_ROOT_SCRIPT" ]; then
    echo "ERROR: dropbox-root.sh not found or not executable at $DROPBOX_ROOT_SCRIPT" >&2
    exit 1
fi

DBROOT="$("$DROPBOX_ROOT_SCRIPT")"
if [ -z "$DBROOT" ] || [ ! -d "$DBROOT" ]; then
    echo "ERROR: cannot resolve Dropbox root (got: '$DBROOT')" >&2
    exit 1
fi

# Parse YAML with PyYAML and emit TAB-separated "name<TAB>subpath" lines.
ENTRIES="$(python3 - "$YAML" <<'PYEOF'
import sys, yaml
try:
    with open(sys.argv[1]) as f:
        data = yaml.safe_load(f)
except Exception as e:
    sys.stderr.write(f"YAML parse error: {e}\n")
    sys.exit(2)
if data is None:
    sys.exit(0)
if not isinstance(data, dict):
    sys.stderr.write("ERROR: YAML root must be a mapping\n")
    sys.exit(2)
collabs = data.get("collaborations", {})
if not isinstance(collabs, dict):
    sys.stderr.write("ERROR: 'collaborations' must be a mapping\n")
    sys.exit(2)
for name, entry in collabs.items():
    if not isinstance(entry, dict):
        continue
    subpath = entry.get("subpath", "")
    if not isinstance(subpath, str) or not subpath:
        continue
    if "\t" in name or "\t" in subpath:
        sys.stderr.write(f"ERROR: TAB character in name or subpath ({name})\n")
        sys.exit(2)
    print(f"{name}\t{subpath}")
PYEOF
)" || { echo "ERROR: failed to parse YAML registry: $YAML" >&2; exit 1; }

if [ -z "$ENTRIES" ]; then
    # Empty registry — nothing to do, exit silently
    exit 0
fi

CHANGED=0
WARNED=0

while IFS=$'\t' read -r NAME SUBPATH; do
    [ -n "$NAME" ] || continue
    REPO="$BASE_DIR/$NAME"
    LINK="$REPO/dropbox-refs"
    TARGET="$DBROOT/$SUBPATH"

    if [ ! -d "$REPO" ]; then
        echo "[dropbox-refs] WARN: repo dir not found, skipping: $REPO" >&2
        WARNED=$((WARNED + 1))
        continue
    fi
    if [ ! -d "$TARGET" ]; then
        echo "[dropbox-refs] WARN: Dropbox target not found, skipping: $TARGET" >&2
        echo "[dropbox-refs]       (collaboration: $NAME — synced? invite accepted?)" >&2
        WARNED=$((WARNED + 1))
        continue
    fi

    if [ -L "$LINK" ]; then
        CURRENT="$(readlink "$LINK")"
        if [ "$CURRENT" = "$TARGET" ]; then
            : # already correct, silent
        else
            rm "$LINK"
            ln -s "$TARGET" "$LINK"
            echo "[dropbox-refs] UPDATED: $LINK -> $TARGET (was: $CURRENT)"
            CHANGED=$((CHANGED + 1))
        fi
    elif [ -e "$LINK" ]; then
        echo "[dropbox-refs] ERROR: $LINK exists and is not a symlink. Refusing to clobber." >&2
        WARNED=$((WARNED + 1))
        continue
    else
        ln -s "$TARGET" "$LINK"
        echo "[dropbox-refs] CREATED: $LINK -> $TARGET"
        CHANGED=$((CHANGED + 1))
    fi
done <<< "$ENTRIES"

# Silent success on no-change so post-merge / setup.sh re-runs don't spam.
exit 0
