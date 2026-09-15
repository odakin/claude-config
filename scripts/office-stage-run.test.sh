#!/usr/bin/env bash
# office-stage-run.test.sh — office-stage-run.sh の hermetic test (Office は起こさない: CLAUDE_OFFICE_STAGING_DIR で root を tmp に向け、 command は sh)
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="$HERE/office-stage-run.sh"
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/office-stage-run-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/proj" "$TMP/root"
export CLAUDE_OFFICE_STAGING_DIR="$TMP/root"
export CLAUDE_OFFICE_STAGING_LOG="$TMP/fallback.log"
unset CLAUDE_OFFICE_STAGING

echo "=== staging あり ==="
printf 'orig\n' > "$TMP/proj/form.xlsx"
out="$(bash "$RUN" "$TMP/proj/form.xlsx" -- sh -c 'case "$1" in "$2"/*) printf "edited\n" > "$1" ;; *) exit 9 ;; esac' _ {} "$TMP/root" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "command は staging root の中の copy を受け取る" || ng "rc=$rc $out"
[ "$(cat "$TMP/proj/form.xlsx")" = "edited" ] && ok "成功時に書き戻す" || ng "書き戻されていない: $(cat "$TMP/proj/form.xlsx")"
[ -z "$(ls -A "$TMP/root")" ] && ok "成功時に subdir を消す" || ng "残骸: $(ls -A "$TMP/root")"

printf 'orig\n' > "$TMP/proj/b.docx"
bash "$RUN" --no-copy-back --out b.pdf="$TMP/proj/out/b.pdf" "$TMP/proj/b.docx" -- sh -c 'printf pdf > "$1"; printf x >> "$2"' _ {dir}/b.pdf {} >/dev/null 2>&1; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(cat "$TMP/proj/out/b.pdf")" = "pdf" ]; } && ok "--out で {dir} の出力を持ち帰る" || ng "--out: rc=$rc"
[ "$(cat "$TMP/proj/b.docx")" = "orig" ] && ok "--no-copy-back は原本に触らない" || ng "原本が変わった"

printf 'orig\n' > "$TMP/proj/c.xlsx"
out="$(bash "$RUN" "$TMP/proj/c.xlsx" -- sh -c 'printf bad > "$1"; exit 3' _ {} 2>&1)"; rc=$?
[ "$rc" -eq 3 ] && ok "command の exit code を返す" || ng "rc=$rc"
[ "$(cat "$TMP/proj/c.xlsx")" = "orig" ] && ok "失敗時は書き戻さない" || ng "失敗なのに書き戻した"
case "$out" in *"kept for diagnosis"*) ok "失敗時は subdir を残して path を出す" ;; *) ng "診断 path が出ない: $out" ;; esac

out="$(bash "$RUN" --out missing.pdf="$TMP/proj/m.pdf" "$TMP/proj/c.xlsx" -- true 2>&1)"; rc=$?
{ [ "$rc" -ne 0 ] && case "$out" in *"expected output missing"*) true ;; *) false ;; esac; } \
  && ok "--out の出力が無ければ失敗" || ng "missing output: rc=$rc $out"

echo "=== staging 無効 (in-place fallback) ==="
printf 'orig\n' > "$TMP/proj/d.xlsx"
CLAUDE_OFFICE_STAGING=0 bash "$RUN" "$TMP/proj/d.xlsx" -- sh -c '[ "$1" = "$2" ] && printf inplace > "$1"' _ {} "$TMP/proj/d.xlsx" >/dev/null 2>&1; rc=$?
{ [ "$rc" -eq 0 ] && [ "$(cat "$TMP/proj/d.xlsx")" = "inplace" ]; } && ok "CLAUDE_OFFICE_STAGING=0 → {} = 原本" || ng "fallback: rc=$rc"

echo "=== 引数 ==="
bash "$RUN" "$TMP/proj/d.xlsx" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 2 ] && ok "-- と command が無ければ usage (rc=2)" || ng "rc=$rc"
bash "$RUN" "$TMP/proj/nope.xlsx" -- true >/dev/null 2>&1; rc=$?
[ "$rc" -eq 2 ] && ok "入力が無ければ rc=2" || ng "rc=$rc"

echo
echo "=== Result: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
