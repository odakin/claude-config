#!/usr/bin/env bash
# xlsx-to-pdf.sh — convert a spreadsheet (xlsx/xls/ods) to PDF, cross-platform.
#
# Why this exists:
#   openpyxl can read/write cell values but cannot RENDER a PDF. Producing a
#   visual snapshot of a filled-in form (for attachment, or to catch merged-cell
#   value clipping / "####" overflow that cell-value checks miss) needs a real
#   rendering engine. This script picks one automatically.
#
# Engine selection (in order):
#   1. LibreOffice — `soffice --headless --convert-to pdf` if soffice/libreoffice
#                    is on PATH. Cross-platform (Linux / Windows / macOS).
#                    Converts the WHOLE workbook within its print areas.
#   2. Microsoft Excel via osascript — macOS only, fallback when LibreOffice is
#                    absent. Supports converting a single named sheet.
#
# 🔑 The macOS + Excel engine needs the Excel "Automation" permission:
#   The first run triggers a macOS dialog ("osascript" wants to control
#   "Microsoft Excel") → click Allow / 許可.
#   ⚠️ A background run (nohup / detached / an agent's run_in_background) cannot
#      surface that dialog and fails with AppleEvent timeout (-1712). Run the
#      first time in the FOREGROUND and answer the dialog; once granted it runs
#      unattended. Change later: System Settings > Privacy & Security > Automation.
#
# Usage:
#   xlsx-to-pdf.sh <input.xlsx> [sheet] [output.pdf]
#     sheet       Excel engine only: export just that worksheet. The LibreOffice
#                 engine ignores it (with a warning) and exports the whole book.
#     output.pdf  defaults to <input> with a .pdf extension, next to the source.
set -euo pipefail

SRC="${1:?usage: xlsx-to-pdf.sh <input.xlsx> [sheet] [output.pdf]}"
SHEET="${2:-}"
SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
[ -f "$SRC" ] || { echo "❌ not found: $SRC" >&2; exit 1; }
PDF="${3:-${SRC%.*}.pdf}"
case "$PDF" in /*) : ;; *) PDF="$(pwd)/$PDF" ;; esac
rm -f "$PDF"

# --- pick a rendering engine ------------------------------------------------
SOFFICE=""
if command -v soffice >/dev/null 2>&1; then
  SOFFICE="soffice"
elif command -v libreoffice >/dev/null 2>&1; then
  SOFFICE="libreoffice"
fi

if [ -n "$SOFFICE" ]; then
  # Engine 1: LibreOffice (cross-platform). Exports the whole workbook.
  if [ -n "$SHEET" ]; then
    echo "⚠️  LibreOffice engine exports the whole workbook; sheet '$SHEET' is ignored (Excel engine only)." >&2
  fi
  OUTDIR="$(dirname "$PDF")"
  PROFILE="$(mktemp -d)"          # isolated profile so it works while LibreOffice is open
  trap 'rm -rf "$PROFILE"' EXIT
  "$SOFFICE" --headless -env:UserInstallation="file://$PROFILE" \
      --convert-to pdf --outdir "$OUTDIR" "$SRC" >/dev/null
  GEN="$OUTDIR/$(basename "${SRC%.*}").pdf"   # soffice names it <basename>.pdf
  if [ "$GEN" != "$PDF" ]; then mv -f "$GEN" "$PDF"; fi
elif [ "$(uname)" = "Darwin" ]; then
  # Engine 2: Microsoft Excel via osascript (macOS). Supports single-sheet export.
  # Reset stale Excel state first (2026-06-05 RCA): `quit` is ASYNC — it returns
  # before Excel has fully exited, so a leftover process from a prior run in the same
  # session causes AppleEvent no-response (-1712) or parameter errors (-50). The sleep
  # covers the async quit so the next `open` starts clean.
  #   NOTE: this also closes any workbook the user has open in Excel — safe only while
  #   the user is NOT editing in Excel during the run. If -1712/-50 still occurs, the
  #   caller should `killall "Microsoft Excel"; sleep 4` (last resort; see
  #   conventions/office-automation.md#xlsx-to-pdf-script).
  osascript -e 'tell application "Microsoft Excel" to quit' >/dev/null 2>&1 || true
  sleep 3
  osascript - "$SRC" "$SHEET" "$PDF" <<'AS'
on run argv
  set srcPath to item 1 of argv
  set sheetName to item 2 of argv
  set pdfPath to item 3 of argv
  with timeout of 200 seconds
    tell application "Microsoft Excel"
      activate
      set wbk to open workbook workbook file name (POSIX file srcPath)
      if sheetName is "" then
        set tgt to active sheet of wbk
      else
        set tgt to worksheet sheetName of wbk
      end if
      save as tgt filename (POSIX file pdfPath) file format PDF file format with overwrite
      close wbk saving no
    end tell
  end timeout
end run
AS
else
  echo "❌ No conversion engine found: install LibreOffice (soffice) or run on macOS with Microsoft Excel." >&2
  exit 1
fi

[ -f "$PDF" ] || { echo "❌ conversion produced no PDF: $PDF" >&2; exit 1; }
echo "PDF: $PDF"
ls -la "$PDF"
