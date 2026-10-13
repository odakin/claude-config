#!/usr/bin/env bash
# install-docx-decl-patch.sh — Install the docx patch in available Python user sites, or --python PATH (setup Step 9).
# python-docx の Document.save() を全 python3 起動で自動正規化する patch を install。
# = single-quote XML 宣言 → Word ネイティブ (double-quote+CRLF) を save 時に自動適用し、
#   厳格 macOS Word の「破損/開いて修復」ダイアログを source で根絶する (race-free)。
# 機構: user site-packages に docx_decl_patch.py (symlink) + docx_decl_patch.pth を置く。
#       .pth が全 python3 起動で `import docx_decl_patch` し、lazy hook が docx import 時に
#       Document.save を wrap する (docx 非使用 script は overhead ほぼゼロ)。
# 規約: claude-config/conventions/office-automation.md#docx-checkbox-content-control
# idempotent: 何度実行しても安全 (symlink/.pth を上書き)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_SRC="$SCRIPT_DIR/docx_decl_patch.py"

if [ ! -f "$MODULE_SRC" ]; then
    echo "❌ $MODULE_SRC が無い" >&2
    exit 1
fi

# Install for each available user-site runtime; an explicit Python limits the scope.
if [ "${1:-}" = "--python" ]; then
    [ "$#" -eq 2 ] || { echo "Usage: $0 [--python /path/to/python3]" >&2; exit 2; }
    candidates=("$2")
elif [ "$#" -eq 0 ]; then
    candidates=()
    while IFS= read -r executable; do candidates+=("$executable"); done < <(type -a -p python3)
    for executable in /opt/homebrew/bin/python3 /usr/local/bin/python3 /opt/homebrew/opt/python@3.12/libexec/bin/python3; do
        [ ! -x "$executable" ] || candidates+=("$executable")
    done
else
    echo "Usage: $0 [--python /path/to/python3]" >&2
    exit 2
fi
seen_sites=""
for runtime in "${candidates[@]}"; do
    USER_SITE="$("$runtime" -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)"
    if [ -z "$USER_SITE" ]; then
        echo "WARNING: cannot resolve user site for $runtime" >&2
        continue
    fi
    case "$seen_sites" in *"|$USER_SITE|"*) continue ;; esac
    seen_sites="$seen_sites|$USER_SITE|"
    mkdir -p "$USER_SITE"
    ln -sf "$MODULE_SRC" "$USER_SITE/docx_decl_patch.py"
    printf 'import docx_decl_patch\n' > "$USER_SITE/docx_decl_patch.pth"
    echo "Installed docx-decl auto-patch: $runtime -> $USER_SITE"
    if "$runtime" -c 'import docx' 2>/dev/null; then
        "$runtime" - <<'VERIFY'
import docx, tempfile, zipfile
from pathlib import Path
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'verify.docx'
    document = docx.Document()
    document.add_paragraph('fixture')
    document.save(path)
    with zipfile.ZipFile(path) as archive:
        assert archive.read('word/document.xml').startswith(b'<?xml version="1.0" '), 'docx declaration patch not active'
print('docx declaration verified')
VERIFY
    else
        echo "  python-docx is not installed in this runtime; patch activates when it is imported."
    fi
done
[ -n "$seen_sites" ] || { echo "No usable Python user site found" >&2; exit 1; }
