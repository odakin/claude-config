#!/usr/bin/env bash
# dropbox-root.sh — Dropbox install root を OS 横断で resolve（dropbox-refs 規約用）
# claude-config/scripts/dropbox-root.sh
#
# Resolve the Dropbox install root for the current user. Prints absolute
# path on success, exits non-zero with stderr error on failure.
#
# Resolution order (first match wins):
#   1. $DROPBOX_ROOT environment variable (override; must be a directory)
#   2. ~/.dropbox/info.json `personal.path` (preferred)
#   3. ~/.dropbox/info.json `business.path`
#   4. ~/Dropbox                                       (legacy default)
#   5. ~/Library/CloudStorage/Dropbox                  (macOS Sonoma+)
#   6. ~/Library/CloudStorage/Dropbox-Personal         (multi-account)
#
# Used by setup-dropbox-refs.sh and reusable as a building block for any
# script that needs portable Dropbox path resolution. See
# conventions/dropbox-refs.md for the surrounding convention.

set -euo pipefail

# 1. Environment variable override
if [ -n "${DROPBOX_ROOT:-}" ]; then
    if [ -d "$DROPBOX_ROOT" ]; then
        echo "$DROPBOX_ROOT"
        exit 0
    fi
    echo "ERROR: \$DROPBOX_ROOT is set ($DROPBOX_ROOT) but is not a directory" >&2
    exit 1
fi

# 2-3. Dropbox's own info.json (most authoritative)
INFO="$HOME/.dropbox/info.json"
if [ -f "$INFO" ]; then
    RESOLVED="$(python3 - "$INFO" <<'PYEOF' 2>/dev/null || true
import json, os, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
for key in ("personal", "business"):
    entry = data.get(key)
    if isinstance(entry, dict):
        p = entry.get("path", "")
        if p and os.path.isdir(p):
            print(p)
            sys.exit(0)
sys.exit(2)
PYEOF
)"
    if [ -n "$RESOLVED" ]; then
        echo "$RESOLVED"
        exit 0
    fi
fi

# 4-6. Filesystem fallback chain
for candidate in \
    "$HOME/Dropbox" \
    "$HOME/Library/CloudStorage/Dropbox" \
    "$HOME/Library/CloudStorage/Dropbox-Personal"
do
    if [ -d "$candidate" ]; then
        echo "$candidate"
        exit 0
    fi
done

cat >&2 <<'EOF'
ERROR: cannot resolve Dropbox install root.
  Tried (in order):
    $DROPBOX_ROOT
    ~/.dropbox/info.json (personal / business)
    ~/Dropbox
    ~/Library/CloudStorage/Dropbox
    ~/Library/CloudStorage/Dropbox-Personal
  If Dropbox is installed elsewhere, set DROPBOX_ROOT to its absolute path.
EOF
exit 1
