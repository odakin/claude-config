#!/usr/bin/env bash
# pptx-to-pdf.sh — PowerPoint pptx → PDF 変換（fidelity-first = PowerPoint native export 優先 → LibreOffice fallback、HFS path 罠 + 網掛け/pattern fill 潰し回避 + EMF ラスタライズ verify、PowerPoint 経路は事前 grant 済み staging dir 経由、office-automation.md#pptx-to-pdf-powerpoint）
# pptx-to-pdf.sh — convert a PowerPoint deck (pptx/ppt) to PDF, FIDELITY-FIRST.
#
# Why this exists:
#   Exporting slides to PDF recurs (archiving / publishing a talk). The trap is
#   FIDELITY: third-party converters (LibreOffice/soffice) often flatten
#   PowerPoint PATTERN FILLS — hatching / 網掛け / screens / gradients — into a
#   solid tone and rasterize coarsely. PowerPoint's OWN export uses the same
#   renderer that displays the slides, so vector shapes and pattern fills
#   survive. So for pptx we PREFER PowerPoint and treat LibreOffice as a last
#   resort (the OPPOSITE priority from xlsx-to-pdf.sh, where LibreOffice is fine).
#
# Engine selection (in order):
#   1. Microsoft PowerPoint via osascript (macOS) — highest fidelity. PREFERRED.
#   2. LibreOffice — `soffice --convert-to pdf`. Cross-platform FALLBACK only.
#      ⚠️ may flatten pattern fills / hatching → always verify (see below).
#
# 🔑 Two macOS PowerPoint gotchas baked in:
#   (a) HFS path for `save … in`. PowerPoint's `save in` treats a POSIX path
#       string ("/Users/…") as an HFS path where "/" is a LITERAL filename char,
#       so it SILENTLY writes a junk-named file into its default folder and
#       reports success — producing NO file at your target. Fix: hand it a
#       colon-separated HFS path via `(POSIX file p) as text`.
#   (b) Automation permission. The first FOREGROUND run triggers a macOS dialog
#       ("osascript" wants to control "Microsoft PowerPoint") → Allow. A
#       background run can't surface it and fails with -1743 / -1712.
#
# 🔑 The PowerPoint engine runs through a PRE-GRANTED STAGING DIR (2026-08-21):
#   PowerPoint is App-Sandboxed like Word / Excel (same "ファイル アクセスを許可"
#   folder dialog on the first WRITE into a new folder). The deck is copied into the
#   Office App Group container (~/Library/Group Containers/UBF8T346G9.Office/
#   claude-office-staging/<unique>/, shared by all three apps' entitlements),
#   exported there, and the PDF copied back. --no-stage / CLAUDE_OFFICE_STAGING=0
#   = in-place; CLAUDE_OFFICE_STAGING_DIR=<dir> = override root.
#   Lib = scripts/lib/office-staging.sh, doc = office-automation.md#office-pregranted-staging-dir.
#   (Verified on Word + Excel; PowerPoint shares the entitlement — see the doc's ledger.)
#
# Safety: opens the deck, exports, and closes ONLY the document it opened
#   (saving no). It does NOT quit PowerPoint and does NOT touch any other open
#   document — safe to run while you have other PowerPoint work open.
#
# ⚠️ EMF FIGURES + FIDELITY: on macOS, PowerPoint rasterizes embedded EMF vector
#   graphics on export (usually at adequate resolution). For a deck whose figures
#   carry FINE hatching / pattern fills (the "潰れ" risk), VERIFY — render the
#   suspect page at high DPI and eyeball it:
#     python3 -c 'import fitz; fitz.open("out.pdf")[N].get_pixmap(dpi=200).save("p.png")'
#   See conventions/office-automation.md#pptx-to-pdf-powerpoint.
#
# Usage:
#   pptx-to-pdf.sh [--no-stage] <input.pptx> [output.pdf]
#     output.pdf  defaults to <input> with a .pdf extension, next to the source.
set -euo pipefail

NO_STAGE=0
case "${1:-}" in --no-stage) NO_STAGE=1; shift ;; esac

SRC="${1:?usage: pptx-to-pdf.sh [--no-stage] <input.pptx> [output.pdf]}"
SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
[ -f "$SRC" ] || { echo "❌ not found: $SRC" >&2; exit 1; }
PDF="${2:-${SRC%.*}.pdf}"
case "$PDF" in /*) : ;; *) PDF="$(pwd)/$PDF" ;; esac
rm -f "$PDF"

# staging lib (= 無ければ no-op で in-place 続行)
STAGING_LIB="$(cd "$(dirname "$0")" && pwd)/lib/office-staging.sh"
if [ -f "$STAGING_LIB" ]; then
  # shellcheck source=lib/office-staging.sh
  . "$STAGING_LIB"
else
  office_stage_file() { return 1; }; office_stage_cleanup() { :; }; office_stage_prune() { :; }; office_stage_report_fallback() { :; }
fi
if [ "$NO_STAGE" = 1 ]; then CLAUDE_OFFICE_STAGING=0; export CLAUDE_OFFICE_STAGING; fi

if [ "$(uname)" = "Darwin" ] && [ -d "/Applications/Microsoft PowerPoint.app" ]; then
  # Engine 1 (preferred): Microsoft PowerPoint native export — highest fidelity.
  WSRC="$SRC"; WPDF="$PDF"
  office_stage_prune 7
  if office_stage_file "$SRC"; then
    WSRC="$OFFICE_STAGED"
    WPDF="$OFFICE_STAGE_DIR/$(basename "$PDF")"
    echo "staging: $OFFICE_STAGE_DIR (pre-granted, no sandbox dialog)" >&2
  else
    office_stage_report_fallback "$SRC"   # 予期せぬ fallback = ⚠️ stderr + fallback log (意図的 --no-stage は沈黙)
  fi
  if ! osascript - "$WSRC" "$WPDF" <<'AS'; then
on run argv
  set srcPath to item 1 of argv
  set outHFS to (POSIX file (item 2 of argv)) as text   -- HFS path: gotcha (a)
  tell application "Microsoft PowerPoint"
    with timeout of 580 seconds
      open srcPath
      set theDoc to active presentation                 -- the just-opened deck
      try
        save theDoc in outHFS as save as PDF
      on error e number n
        try
          close theDoc saving no
        end try
        error "PowerPoint save failed (" & n & "): " & e
      end try
      close theDoc saving no            -- close ONLY this doc; never quit the app
    end timeout
  end tell
end run
AS
    echo "❌ PowerPoint AppleScript export failed (see error above)." >&2
    [ "$WSRC" != "$SRC" ] && echo "   staged copy kept for diagnosis: $OFFICE_STAGE_DIR" >&2
    exit 1
  fi
  if [ "$WPDF" != "$PDF" ]; then
    [ -f "$WPDF" ] || { echo "❌ PowerPoint reported success but no PDF in staging: $WPDF" >&2; exit 1; }
    cp -p "$WPDF" "$PDF"
    office_stage_cleanup
  fi
elif command -v soffice >/dev/null 2>&1 || command -v libreoffice >/dev/null 2>&1; then
  # Engine 2 (fallback): LibreOffice. ⚠️ may flatten pattern fills / hatching.
  echo "⚠️  PowerPoint not found — using LibreOffice. Pattern fills / hatching (網掛け) may flatten; verify the result." >&2
  SOFFICE="$(command -v soffice || command -v libreoffice)"
  OUTDIR="$(dirname "$PDF")"
  PROFILE="$(mktemp -d)"; trap 'rm -rf "$PROFILE"' EXIT   # isolated profile: works while LO is open
  "$SOFFICE" --headless -env:UserInstallation="file://$PROFILE" \
      --convert-to pdf --outdir "$OUTDIR" "$SRC" >/dev/null
  GEN="$OUTDIR/$(basename "${SRC%.*}").pdf"   # soffice names it <basename>.pdf
  if [ "$GEN" != "$PDF" ]; then mv -f "$GEN" "$PDF"; fi
else
  echo "❌ No engine: install Microsoft PowerPoint (macOS, best fidelity) or LibreOffice (soffice)." >&2
  exit 1
fi

[ -f "$PDF" ] || { echo "❌ conversion produced no PDF: $PDF" >&2; exit 1; }
echo "PDF: $PDF"
ls -la "$PDF"
