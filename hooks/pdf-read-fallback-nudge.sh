#!/usr/bin/env bash
# pdf-read-fallback-nudge.sh — PostToolUse(Read): Read tool が .pdf を `pdftoppm is not installed` で fail した時に PyMuPDF 1-liner を system reminder で injection (= 2026-05-18 RCA、 規律 wording に依存しない機械的 enforcement layer)
#
# PostToolUse(Read) hook: when Read tool fails on a .pdf path with the
# `pdftoppm is not installed` error (typical on machines where poppler
# has no bottle and source build fails — e.g. macOS Intel kabylake
# under Tier 2 Homebrew configuration), nudge Claude to try PyMuPDF
# BEFORE saying anything like "cannot read", "will use Wolfram", "will
# try arXiv HTML", "will come back when on the other machine", etc.
#
# Why this exists (= 2026-05-18 RCA):
#
#   The Read tool internally requires poppler's pdftoppm for PDF page
#   rendering. On machines where pdftoppm is absent, Read returns
#   `Error: pdftoppm is not installed`. The discipline `CLAUDE.md
#   inline §18` + `work-discipline.md §「PDF Read tool error を別経
#   路への lazy substitution で覆い隠さない」` says: try PyMuPDF
#   (`python3 -c "import fitz; ..."`) FIRST before declaring "cannot
#   read" or substituting with any other path (arXiv HTML / Wolfram /
#   WebFetch / deferral narrative).
#
#   But the discipline depends on Claude's reflex interpretation of
#   the wording, which has failed twice within 2026-05-18:
#     (a) Morning: Read tool fail → arXiv HTML v1 lazy substitution
#         → arXiv preprint attribution misidentified (HTML v1 section
#         names were treated as authoritative; real authors were a
#         different research group).
#     (b) Afternoon (POST initial discipline commit): Read tool fail
#         → "alternative-tool で完全に賄える" + skipped PyMuPDF/sips,
#         jumped straight to the alternative. The alternative
#         execution itself was valid, but skipping the regulated
#         default path was a discipline violation.
#
#   This hook provides a MECHANICAL enforcement layer that does not
#   depend on Claude reading the discipline correctly: every time the
#   failure symptom appears, an explicit system reminder is emitted
#   with the exact PyMuPDF 1-liner ready to copy.
#
# Behavior:
#   - Read stdin JSON (Claude Code hook protocol)
#   - Extract .tool_input.file_path and .tool_response.{output,error}
#   - If file_path ends with .pdf (case-insensitive) AND the response
#     contains `pdftoppm is not installed`, emit a multi-line system
#     reminder to stdout with the exact PyMuPDF command for the given
#     path
#   - Also conditionally include `sips PDF→PNG` as fallback option (2)
#     when PyMuPDF text extraction is empty (image-only PDF)
#   - PyMuPDF availability is detected; if `python3 -c "import fitz"`
#     fails, the reminder also includes installation hint
#     (`pip3 install --user pymupdf`)
#   - Silent (exit 0 with no stdout) when:
#       - No stdin / no jq / malformed JSON
#       - file_path is not .pdf
#       - Response doesn't contain the failure marker
#       - python3 itself is missing (no PyMuPDF possible)
#
# Exit codes:
#   - Always exit 0 (informational nudge, not a blocker)
#   - The hook emits a "system-reminder" XML wrapper around the
#     guidance so Claude sees it as a system signal in the next turn
#
# Invariants:
#   - The hook NEVER blocks (exit 0). It only adds context.
#   - The hook is idempotent: same input → same output.
#   - No state files; the hook is stateless and per-call.

set -u

# Require jq and stdin (Claude Code hook protocol invariant).
if ! command -v jq >/dev/null 2>&1 || [ -t 0 ]; then
  exit 0
fi

STDIN_JSON="$(cat 2>/dev/null || true)"
[ -n "$STDIN_JSON" ] || exit 0

# Extract the file path being read and the tool response payload.
FILE_PATH="$(printf '%s' "$STDIN_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo '')"
[ -n "$FILE_PATH" ] || exit 0

# .pdf extension check (case-insensitive).
case "$FILE_PATH" in
  *.pdf|*.PDF|*.Pdf) ;;
  *) exit 0 ;;
esac

# Look for the poppler/pdftoppm failure signature anywhere in the response.
# Different Claude Code versions may put the error in .tool_response.error,
# .tool_response.output, .tool_response (plain string), or as a wrapping
# top-level message, so grep the whole stdin JSON.
if ! printf '%s' "$STDIN_JSON" | grep -q 'pdftoppm is not installed'; then
  exit 0
fi

# python3 must be available; otherwise no PyMuPDF possible.
if ! command -v python3 >/dev/null 2>&1; then
  exit 0
fi

# Detect PyMuPDF availability.
PYMUPDF_AVAILABLE=0
if python3 -c 'import fitz' >/dev/null 2>&1; then
  PYMUPDF_AVAILABLE=1
fi

# Escape single quotes in the file path for shell embedding.
ESCAPED_PATH="$(printf '%s' "$FILE_PATH" | sed "s/'/'\\\\''/g")"

# Emit the system reminder. Claude Code wraps PostToolUse stdout in a
# <system-reminder> block automatically, so the content here is the
# direct guidance text.

cat <<EOF
<system-reminder>
PDF Read tool failed for: $FILE_PATH

This is the failure mode that triggered the 2026-05-18 RCA chain (see
\`~/Claude/odakin-prefs/CLAUDE.md inline §18\` + \`work-discipline.md §「PDF Read
tool error を別経路への lazy substitution で覆い隠さない」\`).

BEFORE saying "PDF が読めない" / "別 path で賄える" / "Wolfram で..." / "arXiv HTML
で..." / "後で引き直す" / "家 MacBook に戻ってから" or any other substitution
narrative, run the following PyMuPDF command FIRST and expose the result in
chat:

    python3 -c "import fitz; doc = fitz.open('$ESCAPED_PATH'); print(doc.metadata); print('pages:', doc.page_count); print(doc[0].get_text()[:500])"

EOF

if [ "$PYMUPDF_AVAILABLE" -eq 0 ]; then
  cat <<'EOF'
NOTE: PyMuPDF (`import fitz`) is NOT importable on this machine. Install it
with:

    pip3 install --user pymupdf

If pip3 is also unavailable, fall back to `sips -s format png -Z 1500
<path> --out <out>.png` (macOS only) for image-mode reading, then read the
PNG via the Read tool.

EOF
else
  cat <<'EOF'
PyMuPDF is importable on this machine — the 1-liner above should work.

If PyMuPDF returns empty text (scanned image-only PDF), fall back to:

    sips -s format png -Z 1500 <path> --out <out>.png

and read the PNG via the Read tool.

EOF
fi

cat <<'EOF'
Substitution to arXiv HTML / Wolfram / WebFetch is acceptable ONLY AFTER
PyMuPDF has been tried and its result exposed in chat. When using arXiv
HTML, version-match the user's PDF (v2 PDF → v2 HTML, never v1) and
cross-check author/title with PyMuPDF metadata. The 2026-05-18 morning
RCA shows that HTML v1 section names alone — without PyMuPDF-based
author verification — led to attributing an arXiv preprint to the
wrong research group.
</system-reminder>
EOF

exit 0
