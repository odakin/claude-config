#!/usr/bin/env bash
# office-stage-run.sh — 任意の Office 駆動 command を事前 grant 済み staging dir 経由で 1 回走らせる (入力を stage → `{}` を staged path に置換して実行 → 成功時に書き戻し、 office-automation.md#office-pregranted-staging-dir)
#
# WHY
#   Excel / Word / PowerPoint に案件 dir の file を直接開かせると、 folder へ書く瞬間に
#   「ファイル アクセスを許可」 dialog が folder ごとに出る。 layer-1 wrapper (xlsx-to-pdf.sh 等) は内部で
#   staging するが、 手書きの osascript (cell 記入 / 独自 export) には lib を source する数行が要り、
#   in-place で書いてしまいがち。 本 script はその数行を 1 command にする (= hooks/office-inplace-guard.py が
#   in-place を deny したときの直し方)。
#
# Usage
#   office-stage-run.sh [--no-copy-back] [--out NAME=DEST]... <file> -- <command> [args...]
#     {}          → staged copy of <file> (basename 保持)。 command の引数の中で置換 (部分一致も可)
#     {dir}       → staging subdir。 出力 (PDF 等) をここに書かせ、 --out で持ち帰る
#     --out NAME=DEST  成功時に {dir}/NAME を DEST へ copy (複数可)。 無ければ失敗扱い
#     --no-copy-back   staged copy を <file> へ書き戻さない (= 読むだけ / 出力だけ欲しい時)
#   例
#     office-stage-run.sh form.xlsx -- osascript fill.applescript {}
#     office-stage-run.sh form.xlsx --no-copy-back --out form.pdf=out/form.pdf -- osascript export.applescript {} {dir}/form.pdf
#   AppleScript 側は path を literal で書かず `on run argv` で受ける (literal の in-place path は guard が止める)。
#
# 契約
#   * command の exit code をそのまま返す。 成功時だけ書き戻し (内容が変わった時のみ、 同 dir の tmp → mv で atomic) +
#     --out の持ち帰り + subdir 削除。 失敗時は subdir を残して path を stderr に出す (診断用、 lib と同じ)
#   * staging が使えない環境 (非 macOS / Office 未 install / CLAUDE_OFFICE_STAGING=0) は lib の規則どおり
#     in-place に落ちる (予期せぬ理由なら lib が ⚠️ + fallback log)。 {} = <file>、 {dir} = <file> の dir
#   * bash 3.2 compatible
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/office-staging.sh
. "$SCRIPT_DIR/lib/office-staging.sh"

usage() { sed -n '11,21p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

COPY_BACK=1
OUTS=()
SRC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-copy-back) COPY_BACK=0; shift ;;
    --out) [ $# -ge 2 ] || usage; OUTS+=("$2"); shift 2 ;;
    --out=*) OUTS+=("${1#--out=}"); shift ;;
    -h|--help) usage ;;
    --) shift; break ;;
    *) [ -z "$SRC" ] || usage; SRC="$1"; shift ;;
  esac
done
[ -n "$SRC" ] && [ $# -gt 0 ] || usage
[ -f "$SRC" ] || { echo "office-stage-run: input not found: $SRC" >&2; exit 2; }

ACTIVE=0
office_stage_prune 7
if office_stage_file "$SRC"; then
  ACTIVE=1
  STAGED="$OFFICE_STAGED"; SDIR="$OFFICE_STAGE_DIR"
else
  office_stage_report_fallback "$SRC"
  STAGED="$SRC"; SDIR="$(cd "$(dirname "$SRC")" && pwd)"
fi

CMD=()
for a in "$@"; do
  a="${a//\{dir\}/$SDIR}"
  a="${a//\{\}/$STAGED}"
  CMD+=("$a")
done

"${CMD[@]}"
rc=$?

if [ "$rc" -ne 0 ]; then
  [ "$ACTIVE" -eq 1 ] && echo "office-stage-run: command failed (rc=$rc); staged copy kept for diagnosis: $SDIR" >&2
  exit "$rc"
fi

for spec in ${OUTS[@]+"${OUTS[@]}"}; do
  name="${spec%%=*}"; dest="${spec#*=}"
  if [ "$name" = "$spec" ] || [ -z "$dest" ]; then
    echo "office-stage-run: --out needs NAME=DEST: $spec" >&2; rc=2; continue
  fi
  if [ ! -f "$SDIR/$name" ]; then
    echo "office-stage-run: expected output missing: $SDIR/$name" >&2; rc=1; continue
  fi
  if [ "$SDIR/$name" != "$dest" ]; then
    mkdir -p "$(dirname "$dest")" && cp -p "$SDIR/$name" "$dest" || rc=1
  fi
done

if [ "$ACTIVE" -eq 1 ] && [ "$COPY_BACK" -eq 1 ] && ! cmp -s "$STAGED" "$SRC"; then
  tmp="$(mktemp "$(dirname "$SRC")/.office-stage-XXXXXX")" \
    && cp -p "$STAGED" "$tmp" && mv -f "$tmp" "$SRC" \
    || { echo "office-stage-run: copy back failed; staged copy kept: $SDIR" >&2; exit 1; }
fi

if [ "$rc" -eq 0 ]; then
  [ "$ACTIVE" -eq 1 ] && office_stage_cleanup
else
  [ "$ACTIVE" -eq 1 ] && echo "office-stage-run: output step failed; staged copy kept: $SDIR" >&2
fi
exit "$rc"
