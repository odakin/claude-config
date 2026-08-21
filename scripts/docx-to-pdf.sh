#!/usr/bin/env bash
# docx-to-pdf.sh — Word docx/doc → PDF 変換（macOS 既定 Word 忠実版 → --pages で Pages → 非 macOS LibreOffice、Word 経路は事前 grant 済み staging dir 経由で sandbox dialog を回避、office-automation.md#docx-to-pdf-pages）
# docx-to-pdf.sh — convert a Word document (docx/doc) to PDF, cross-platform.
#
# Sibling of xlsx-to-pdf.sh (spreadsheets). python-docx / textutil can read or
# edit a .docx but cannot RENDER a PDF; producing a visual copy (to show, to
# attach, or to hand a form to someone to fill in) needs a real engine. This
# picks one automatically.
#
# Why a docx-specific script (not just "run soffice"):
#   On macOS, LibreOffice is often NOT installed (Microsoft Office + Pages are),
#   and office-automation.md marks LibreOffice as "not recommended on mac".
#   Reaching for `soffice` first is the exact failure mode this script prevents —
#   call this and it uses the right engine for the platform.
#
# Engine selection:
#   macOS (default) : Microsoft Word via osascript — layout-faithful, for a
#                     reviewer-facing copy. Handles the stale-cache + cold-start
#                     gotchas (full kill + shell `open` + warm-up sleep).
#                     ⭐ docx は「Word 体裁が契約」 の正式書類 (= 行政・学術・社内
#                     様式) が大半なので、 default は Word 忠実版に倒す
#                     (2026-06-23 反転、 office-automation.md §docx-pdf-stale-cache
#                     「context-first reflex」 = Pages の re-flow で官公署様式の
#                     見出し/表の重なり artifact を踏んだ RCA)。
#   --pages         : Pages.app via AppleScript — layout NON-faithful (= re-flow).
#                     content check (= 値が入ったか) のみで体裁不問 + Word 不在
#                     環境 + cold-start 嫌い のいずれかなら明示で選ぶ。
#   --word          : (backward compat、 default 反転前の旧 flag) no-op、 即 shift。
#   non-macOS       : LibreOffice (soffice / libreoffice) on PATH.
#
# 🔑 Word engine runs through a PRE-GRANTED STAGING DIR (2026-08-21):
#   Word is App-Sandboxed and pops its own "ファイル アクセスを許可" dialog the first
#   time it has to WRITE into a folder (= the PDF export; reading the docx is fine).
#   Every new project dir → a new dialog, and a remote operator cannot click it.
#   So the docx is copied into the Office App Group container
#   (~/Library/Group Containers/UBF8T346G9.Office/claude-office-staging/<unique>/),
#   which is inside Word's sandbox = no grant needed; the PDF is exported there and
#   copied back next to the source. Caller-visible API is unchanged.
#   --no-stage / CLAUDE_OFFICE_STAGING=0 restores the in-place behaviour;
#   CLAUDE_OFFICE_STAGING_DIR=<dir> overrides the root (= a fixed dir you granted
#   once by hand). Lib = scripts/lib/office-staging.sh,
#   doc = office-automation.md#office-pregranted-staging-dir.
#
# Refs: conventions/office-automation.md  #docx-to-pdf-pages  #docx-pdf-stale-cache
#
# Usage:
#   docx-to-pdf.sh [--pages|--word] [--no-stage] <input.docx> [output.pdf]
#     output.pdf  defaults to <input> with a .pdf extension, next to the source.
set -euo pipefail

ENGINE_PAGES=0
NO_STAGE=0
while :; do
  case "${1:-}" in
    --pages)    ENGINE_PAGES=1; shift ;;
    --word)     shift ;;   # backward compat: default is now Word, so --word is no-op
    --no-stage) NO_STAGE=1; shift ;;
    *) break ;;
  esac
done

SRC="${1:?usage: docx-to-pdf.sh [--pages|--word] [--no-stage] <input.docx> [output.pdf]}"
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
  office_stage_file() { return 1; }; office_stage_cleanup() { :; }; office_stage_prune() { :; }
fi
if [ "$NO_STAGE" = 1 ]; then CLAUDE_OFFICE_STAGING=0; export CLAUDE_OFFICE_STAGING; fi

warn_tmp_input() {
  # Word.app sandbox は /tmp 配下を grant 永続化できない (= 「ファイル アクセスを許可」
  # ダイアログの button が disabled で押せない、 conventions/office-automation.md
  # §docx-tmp-sandbox-deny)。 staging が効かず in-place で Word を当てる時だけ warn。
  case "$SRC" in
    /tmp/*|/private/tmp/*)
      echo "⚠️  docx-to-pdf: input is under /tmp ($SRC) and staging is unavailable" >&2
      echo "    Word.app sandbox cannot persist /tmp folder grants — permission dialog" >&2
      echo "    will appear and may be ungrantable. Move docx under your project dir" >&2
      echo "    (= ~/<repo>/...) or enable staging (office-automation.md#office-pregranted-staging-dir)." >&2
      ;;
  esac
}

have() { command -v "$1" >/dev/null 2>&1; }
soffice_bin() { if have soffice; then echo soffice; elif have libreoffice; then echo libreoffice; fi; }

render_pages() {
  # Robust macOS automation; uses the verified `export ... as PDF` form.
  osascript - "$SRC" "$PDF" <<'AS'
on run argv
  set srcPath to item 1 of argv
  set pdfPath to item 2 of argv
  with timeout of 200 seconds
    tell application "Pages"
      activate
      set theDoc to open POSIX file srcPath
      delay 2
      export theDoc to POSIX file pdfPath as PDF
      close theDoc saving no
    end tell
  end timeout
end run
AS
}

render_word() {
  # Word engine: stale in-memory cache + cold-start failures
  # (office-automation.md #docx-pdf-stale-cache). Defenses: full kill → shell
  # `open` (file association = cold-start safe) → warm-up sleep → save as the
  # active document, wrapped in `with timeout` (default AppleEvent timeout is
  # 60s — too short for cold-start). save-as syntax is Word-version dependent.
  #
  # Staging (office-automation.md #office-pregranted-staging-dir): copy the docx
  # into the pre-granted dir, export there, copy the PDF back. The unique subdir
  # also keeps Word's in-memory cache from matching a previous run's path.
  local wsrc="$SRC" wpdf="$PDF"
  office_stage_prune 7
  if office_stage_file "$SRC"; then
    wsrc="$OFFICE_STAGED"
    wpdf="$OFFICE_STAGE_DIR/$(basename "$PDF")"
    echo "staging: $OFFICE_STAGE_DIR (pre-granted, no sandbox dialog)" >&2
  else
    warn_tmp_input
  fi
  pkill -x "Microsoft Word" 2>/dev/null || true
  sleep 2
  open "$wsrc"
  sleep 6
  if ! osascript <<AS 2>&1; then
with timeout of 240 seconds
  tell application "Microsoft Word"
    save as active document file name "$wpdf" file format format PDF
  end tell
end timeout
AS
    echo "" >&2
    echo "❌ Word AppleScript automation failed (cold-start / -1712 timeout / -609 connection)." >&2
    echo "   Fallback (office-automation.md §docx-pdf-stale-cache fallback 1):" >&2
    echo "   open the file in Word manually and use File > 名前を付けて保存 > PDF。" >&2
    echo "   srcfile: $SRC" >&2
    [ "$wsrc" != "$SRC" ] && echo "   staged copy kept for diagnosis: $OFFICE_STAGE_DIR" >&2
    osascript -e 'tell application "Microsoft Word" to close active document saving no' >/dev/null 2>&1 || true
    return 1
  fi
  osascript -e 'tell application "Microsoft Word" to close active document saving no' >/dev/null 2>&1 || true
  if [ "$wpdf" != "$PDF" ]; then
    [ -f "$wpdf" ] || { echo "❌ Word reported success but no PDF in staging: $wpdf" >&2; return 1; }
    cp -p "$wpdf" "$PDF"
    office_stage_cleanup
  fi
}

render_soffice() {
  local bin outdir profile gen
  bin="$(soffice_bin)"; [ -n "$bin" ] || return 1
  outdir="$(dirname "$PDF")"
  profile="$(mktemp -d)"; trap 'rm -rf "$profile"' RETURN
  "$bin" --headless -env:UserInstallation="file://$profile" \
      --convert-to pdf --outdir "$outdir" "$SRC" >/dev/null
  gen="$outdir/$(basename "${SRC%.*}").pdf"
  [ "$gen" = "$PDF" ] || mv -f "$gen" "$PDF"
}

if [ "$(uname)" = "Darwin" ]; then
  if [ "$ENGINE_PAGES" = 1 ]; then
    [ -d "/Applications/Pages.app" ] || { echo "❌ --pages requested but /Applications/Pages.app not found" >&2; exit 1; }
    render_pages
  elif osascript -e 'tell application "Finder" to exists application file id "com.microsoft.Word"' 2>/dev/null | grep -qi true; then
    render_word
  elif [ -d "/Applications/Pages.app" ]; then
    render_pages   # Word 不在 → Pages fallback (legacy install profile)
  elif have soffice || have libreoffice; then
    render_soffice
  else
    echo "❌ macOS engine missing: install Microsoft Word (default), or pass --pages with Pages.app installed." >&2
    exit 1
  fi
else
  if have soffice || have libreoffice; then
    render_soffice
  else
    echo "❌ No conversion engine: install LibreOffice (soffice), or run on macOS (Pages/Word)." >&2
    exit 1
  fi
fi

[ -f "$PDF" ] || { echo "❌ conversion produced no PDF: $PDF" >&2; exit 1; }
echo "PDF: $PDF"
ls -la "$PDF"
