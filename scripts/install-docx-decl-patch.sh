#!/usr/bin/env bash
# install-docx-decl-patch.sh — 上記 patch を user site-packages に `.pth`+symlink で install（setup.sh Step 9、 全 python3 起動で auto-load、 idempotent）
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

# 既定 python3 の user site-packages (= python-docx もここに入る運用)
USER_SITE="$(python3 -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)"
if [ -z "$USER_SITE" ]; then
    echo "⚠️  python3 の user site-packages を解決できず → skip" >&2
    exit 0
fi

mkdir -p "$USER_SITE"
ln -sf "$MODULE_SRC" "$USER_SITE/docx_decl_patch.py"
printf 'import docx_decl_patch\n' > "$USER_SITE/docx_decl_patch.pth"

# 検証: 素の python3 が Word 形式宣言を書くか (docx があれば)
if python3 -c 'import docx' 2>/dev/null; then
    VERIFY="$(python3 - <<'PY'
import docx, tempfile, os, zipfile
d = docx.Document(); d.add_paragraph("x"); p = tempfile.mktemp(suffix=".docx"); d.save(p)
ok = zipfile.ZipFile(p).read("word/document.xml")[:20] == b'<?xml version="1.0" '
os.remove(p); print("OK" if ok else "FAIL")
PY
)"
    echo "✅ docx-decl auto-patch installed → $USER_SITE (自動正規化 verify: $VERIFY)"
else
    echo "✅ docx-decl auto-patch installed → $USER_SITE (python-docx 未導入 = 現状 no-op、導入後に自動有効)"
fi
