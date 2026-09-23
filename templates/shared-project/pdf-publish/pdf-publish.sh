#!/bin/sh
# pdf-publish.sh — build した PDF を共有フォルダ (Dropbox など) へ写す。 git push のたびに pre-push hook から背景で走る。
#
# 正本 = claude-config/templates/shared-project/pdf-publish/ (repo の tools/pdf-publish/ はその写し。
#   直すときは正本を直して claude-config/scripts/install-pdf-publish.py で配り直す)。
# なぜ: PDF を git に commit すると、 差分が効かず版ごとにまるごと履歴に積まれる
#   (claude-config/conventions/repo-history-growth.md)。 PDF は git に入れず、 push のたびにここから共有フォルダへ写す。
# 何をするか: push される commit で変わった文書 (.tex) について、 PDF が古い (か無い) なら BUILD で組み直し、
#   共有フォルダへ写す (写し先より新しいときだけ上書き)。 変わっていない文書は触らない。
# 設定: .pdf-publish.conf (repo で共有) + .pdf-publish.local (この機械だけ。 git に入れない)
#   DEST=<Dropbox 直下からの共有フォルダの path>      DROPBOX_ROOT=<Dropbox の場所> (自動で探せないとき)
#   DOC=<文書の .tex、 glob 可>   BUILD=<組むコマンド、 文書の dir で走る。 {stem} = 文書名> (DOC の次の行、 省略可)
# 使い方: sh tools/pdf-publish/pdf-publish.sh [--all] [--range <from>..<to>] [--new <sha>] [--dry-run]
#   引数なし = --all (全文書)。 hook は push の範囲を --range / --new で渡す。
# 止める: 環境変数 PDF_PUBLISH=0。 記録 = <git dir>/pdf-publish.log
# 限界: 文書の path に空白があると扱えない。 \documentclass を持たない .tex (断片) は組まない。

[ "${PDF_PUBLISH:-1}" = "0" ] && exit 0
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$ROOT" || exit 0
[ -f .pdf-publish.conf ] || exit 0
GITDIR=$(git rev-parse --absolute-git-dir 2>/dev/null) || exit 0
LOG="$GITDIR/pdf-publish.log"
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t pdfpub) || exit 0
trap 'rm -rf "$TMP"' EXIT

MODE=all; DRY=0
: > "$TMP/changed"
while [ $# -gt 0 ]; do
  case "$1" in
    --all) MODE=all ;;
    --dry-run) DRY=1 ;;
    --range) MODE=range; git diff --name-only "$2" >> "$TMP/changed" 2>/dev/null; shift ;;
    --new) MODE=range; git log --format= --name-only "$2" --not --remotes >> "$TMP/changed" 2>/dev/null; shift ;;
  esac
  shift
done

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; [ "$DRY" = 1 ] && printf '%s\n' "$*"; }

# 設定を読む (conf → local の順、 local が勝つ)。 DOC と BUILD は組にして TMP/docs に並べる
DEST=""; DR="${DROPBOX_ROOT:-}"
: > "$TMP/docs"
for f in .pdf-publish.conf .pdf-publish.local; do
  [ -f "$f" ] || continue
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      DEST=*) DEST=${line#DEST=} ;;
      DROPBOX_ROOT=*) DR=${line#DROPBOX_ROOT=} ;;
      DOC=*) printf '%s\n' "${line#DOC=}" >> "$TMP/docs"; printf '\n' >> "$TMP/docs" ;;
      BUILD=*) sed '$d' "$TMP/docs" > "$TMP/d2" && mv "$TMP/d2" "$TMP/docs"; printf '%s\n' "${line#BUILD=}" >> "$TMP/docs" ;;
    esac
  done < "$f"
done
[ -n "$DEST" ] || { log "NG DEST が .pdf-publish.conf に無い"; exit 0; }
if [ -z "$DR" ]; then
  for c in "$HOME/Library/CloudStorage/Dropbox" "$HOME/Dropbox" "${USERPROFILE:-/nonexistent}/Dropbox"; do
    [ -d "$c" ] && { DR=$c; break; }
  done
fi
OUT="$DR/$DEST"
if [ -z "$DR" ] || [ ! -d "$OUT" ]; then
  log "skip 共有フォルダ ($OUT) がこの機械に無い — 共有の招待を受けるか、 .pdf-publish.local に DROPBOX_ROOT= / DEST= を書く"
  exit 0
fi

# 文書ごとに: 変わった文書だけ (--all は全部)、 PDF が古ければ組み、 新しければ写す
while IFS= read -r glob && IFS= read -r build; do
  for tex in $glob; do
    [ -f "$tex" ] || continue
    grep -q '\\documentclass' "$tex" 2>/dev/null || continue
    if [ "$MODE" = range ] && ! grep -qxF "$tex" "$TMP/changed"; then continue; fi
    dir=$(dirname "$tex"); stem=$(basename "$tex" .tex); pdf="$dir/$stem.pdf"
    if [ -n "$build" ] && { [ ! -f "$pdf" ] || [ "$tex" -nt "$pdf" ]; }; then
      cmd=$(printf '%s' "$build" | sed "s/{stem}/$stem/g")
      if [ "$DRY" = 1 ]; then log "would build ($dir): $cmd"
      elif (cd "$dir" && sh -c "$cmd") >> "$LOG" 2>&1; then log "ok build ($dir): $cmd"
      else log "NG build ($dir): $cmd"; continue
      fi
    fi
    [ -f "$pdf" ] || continue
    name="$stem.pdf"
    if [ "$stem" = main ]; then
      # main.pdf は意味のある一番近い dir 名に (src / paper のような dir は飛ばし、 無ければ repo 名)
      d=$(cd "$dir" && pwd)
      while [ "$d" != "$ROOT" ] && [ "$d" != "/" ]; do
        case "$(basename "$d")" in src|tex|latex|manuscript|paper|draft|text|overleaf|external) d=$(dirname "$d") ;; *) break ;; esac
      done
      name="$(basename "$d").pdf"
    fi
    dst="$OUT/$name"
    if [ ! -f "$dst" ] || [ "$pdf" -nt "$dst" ]; then
      if [ "$DRY" = 1 ]; then log "would copy $pdf -> $dst"
      elif cp -p "$pdf" "$dst.tmp.$$" 2>>"$LOG" && mv -f "$dst.tmp.$$" "$dst"; then log "ok copy $pdf -> $dst"
      else rm -f "$dst.tmp.$$"; log "NG copy $pdf -> $dst"
      fi
    fi
  done
done < "$TMP/docs"
exit 0
