#!/usr/bin/env bash
# xlsx-to-pdf.sh — spreadsheet → PDF 変換（LibreOffice soffice 優先 → macOS Excel osascript fallback、Excel 経路は事前 grant 済み staging dir 経由で sandbox dialog を回避 + 原本を export 時再保存から守る、office-automation.md#xlsx-to-pdf-script）
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
# 🔑 The Excel engine runs through a PRE-GRANTED STAGING DIR (2026-08-21):
#   Excel is App-Sandboxed and pops its own "ファイル アクセスを許可" dialog the first
#   time it has to WRITE into a folder (= the PDF export) — once per new folder, and
#   it blocks the AppleScript (-1712) while nobody can click it remotely. The
#   workbook is therefore copied into the Office App Group container
#   (~/Library/Group Containers/UBF8T346G9.Office/claude-office-staging/<unique>/),
#   exported there (no grant needed inside Excel's sandbox) and the PDF copied back.
#   Bonus: Excel's export path re-saves the workbook it opened (observed with
#   macro-bearing forms) — with staging that hits the COPY, the original stays
#   byte-identical. --no-stage / CLAUDE_OFFICE_STAGING=0 = in-place (old behaviour);
#   CLAUDE_OFFICE_STAGING_DIR=<dir> = override root. Lib = scripts/lib/office-staging.sh,
#   doc = office-automation.md#office-pregranted-staging-dir.
#
# 🔒 Never touches the user's Excel work, never comes to the front (2026-09-15):
#   Excel is launched with `open -g` (background) and never `activate`d; if it took the front
#   anyway, focus goes back to the app you were using. The pre-run reset quits Excel ONLY when
#   every open workbook is a staged copy (= left over from an earlier run) — with any other
#   workbook open it skips the reset and opens/closes only its own copy. It never kills Excel.
#   If this run launched Excel, it quits it again at the end (again only when nothing else is
#   open). Refuses to run when Excel already has a workbook with the same name open (Excel
#   cannot open two, and closing "ours" could discard your edits).
#   Lib = scripts/lib/office-app-guard.sh, doc = office-automation.md#office-app-reset-guard.
#
# Usage:
#   xlsx-to-pdf.sh [--no-stage] <input.xlsx> [sheet] [output.pdf]
#     sheet       Excel engine only: export just that worksheet. The LibreOffice
#                 engine ignores it (with a warning) and exports the whole book.
#     output.pdf  defaults to <input> with a .pdf extension, next to the source.
set -euo pipefail

NO_STAGE=0
case "${1:-}" in --no-stage) NO_STAGE=1; shift ;; esac

SRC="${1:?usage: xlsx-to-pdf.sh [--no-stage] <input.xlsx> [sheet] [output.pdf]}"
SHEET="${2:-}"
SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
[ -f "$SRC" ] || { echo "❌ not found: $SRC" >&2; exit 1; }
PDF="${3:-${SRC%.*}.pdf}"
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
GUARD_LIB="$(cd "$(dirname "$0")" && pwd)/lib/office-app-guard.sh"
if [ "$NO_STAGE" = 1 ]; then CLAUDE_OFFICE_STAGING=0; export CLAUDE_OFFICE_STAGING; fi

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
  # Staging (office-automation.md#office-pregranted-staging-dir): Excel opens and
  # exports inside its own App Group container → no folder-grant dialog, and the
  # export-time re-save hits the copy, not the original.
  WSRC="$SRC"; WPDF="$PDF"
  office_stage_prune 7
  if office_stage_file "$SRC"; then
    WSRC="$OFFICE_STAGED"
    WPDF="$OFFICE_STAGE_DIR/$(basename "$PDF")"
    echo "staging: $OFFICE_STAGE_DIR (pre-granted, no sandbox dialog)" >&2
  else
    office_stage_report_fallback "$SRC"   # 予期せぬ fallback = ⚠️ stderr + fallback log (意図的 --no-stage は沈黙)
  fi
  [ -f "$GUARD_LIB" ] || { echo "❌ missing $GUARD_LIB (required: without it this script cannot tell whether Excel holds your work)" >&2; exit 1; }
  # shellcheck source=lib/office-app-guard.sh
  . "$GUARD_LIB"
  # Reset stale Excel state (2026-06-05 RCA: a leftover instance from earlier runs answers
  # -1712 / -50). The guard quits Excel only when it holds nothing but staged copies, waits
  # for the async quit to finish, and otherwise leaves Excel alone (#office-app-reset-guard).
  office_front_remember
  office_app_reset excel
  if office_app_has_path excel "$WSRC"; then
    echo "❌ Excel already has a workbook named '$(basename "$WSRC")' open — close it in Excel first (this script will not close your workbook)." >&2
    exit 1
  fi
  if ! office_app_launch_background excel; then
    echo "❌ Excel did not start / answer in the background." >&2
    office_app_failure_hint excel
    exit 1
  fi
  if ! osascript - "$WSRC" "$SHEET" "$WPDF" <<'AS'; then
on run argv
  set srcPath to item 1 of argv
  set sheetName to item 2 of argv
  set pdfPath to item 3 of argv
  with timeout of 200 seconds
    tell application id "com.microsoft.Excel"
      -- no `activate`: Excel stays in the background
      set wbk to open workbook workbook file name (POSIX file srcPath)
      try
        if sheetName is "" then
          set tgt to active sheet of wbk
        else
          set tgt to worksheet sheetName of wbk
        end if
        save as tgt filename (POSIX file pdfPath) file format PDF file format with overwrite
      on error errMsg number errNum
        close wbk saving no   -- close ONLY the workbook this script opened
        error errMsg number errNum
      end try
      close wbk saving no
    end tell
  end timeout
end run
AS
    echo "❌ Excel AppleScript export failed (see error above)." >&2
    office_app_close_ours excel "$WSRC"
    office_app_release excel
    office_front_restore "Microsoft Excel.app"
    office_app_failure_hint excel
    [ "$WSRC" != "$SRC" ] && echo "   staged copy kept for diagnosis: $OFFICE_STAGE_DIR" >&2
    exit 1
  fi
  office_app_release excel
  office_front_restore "Microsoft Excel.app"
  if [ "$WPDF" != "$PDF" ]; then
    [ -f "$WPDF" ] || { echo "❌ Excel reported success but no PDF in staging: $WPDF" >&2; exit 1; }
    cp -p "$WPDF" "$PDF"
    office_stage_cleanup
  fi
else
  echo "❌ No conversion engine found: install LibreOffice (soffice) or run on macOS with Microsoft Excel." >&2
  exit 1
fi

[ -f "$PDF" ] || { echo "❌ conversion produced no PDF: $PDF" >&2; exit 1; }
echo "PDF: $PDF"
ls -la "$PDF"
