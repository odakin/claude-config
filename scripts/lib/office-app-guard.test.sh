#!/usr/bin/env bash
# office-app-guard.test.sh — office-app-guard.sh の hermetic test (osascript / open を PATH の stub に差し替え、 Office は起こさない。 macOS 以外でも走る)
#
# 検査: (1) 未起動 = quit しない・背景起動・起動した分だけ最後に quit (2) staged copy だけ = 自分の文書を閉じて quit
#       (3) user の文書あり (保存済 / 未保存 / 名前だけの新規) = quit も close もしない (4) 応答なし・dialog = quit しない
#       (5) 確認と quit の間に文書が開かれた = quit しない (6) has-path (7) 前面を返す条件 (8) python の橋
#       (9) wrapper に quit / kill / activate / active document / workbook 1 が戻っていない (lint)
#       (10) macOS のみ: xlsx-to-pdf.sh を stub の上で通し、 user の文書があれば quit せず PDF を作る
# stub の状態 = $MOCK/{running,docs,front,log}。 AppleScript 本体の挙動は実機検証 (office-automation.md#office-app-reset-guard)。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/office-app-guard.sh"
[ -f "$LIB" ] || { echo "SKIP: lib not found: $LIB"; exit 0; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/office-app-guard-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"; mkdir -p "$HOME"
export CLAUDE_OFFICE_STAGING_DIR="$TMP/stage-root"; mkdir -p "$CLAUDE_OFFICE_STAGING_DIR"
export CLAUDE_OFFICE_STAGING_LOG="$TMP/fallback.log"
export CLAUDE_OFFICE_APP_WAIT=2 CLAUDE_OFFICE_APP_LAUNCH_WAIT=2
unset CLAUDE_OFFICE_STAGING
MOCK="$TMP/mock"; STUBS="$TMP/stubs"; mkdir -p "$MOCK" "$STUBS"
export MOCK

PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "✅ $1"; }
bad() { FAIL=$((FAIL + 1)); echo "❌ $1"; }
check() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3 (expected [$2], got [$1])"; fi; }
logged() { grep -qx -- "$1" "$MOCK/log" 2>/dev/null; }

# ---- stubs --------------------------------------------------------------------
cat > "$STUBS/osascript" <<'STUB'
#!/usr/bin/env bash
# fake osascript: 文書一覧・close・quit を $MOCK の file で模す
script=""; args=()
if [ "${1:-}" = "-" ]; then shift; script="$(cat)"; args=("$@")
else while [ $# -gt 0 ]; do [ "$1" = "-e" ] && { script="$script
$2"; shift; }; shift; done; fi
running="$(cat "$MOCK/running" 2>/dev/null || echo false)"
lower() { LC_ALL=C tr 'A-Z' 'a-z'; }
case "$script" in
  *office-app-guard:documents*)
    [ "$running" = true ] || { echo not-running; exit 0; }
    [ -f "$MOCK/hang" ] && { echo "execution error: AppleEvent timed out. (-1712)" >&2; exit 1; }
    echo ok; cat "$MOCK/docs" 2>/dev/null; exit 0 ;;
  *office-app-guard:close-ours*)
    : > "$MOCK/docs.new"
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      fn="$(printf '%s' "${line#*	}" | lower)"; hit=0
      for a in ${args[@]+"${args[@]}"}; do [ "$(printf '%s' "$a" | lower)" = "$fn" ] && hit=1; done
      if [ "$hit" = 1 ]; then echo "close ${line#*	}" >> "$MOCK/log"; else printf '%s\n' "$line" >> "$MOCK/docs.new"; fi
    done < "$MOCK/docs"
    mv "$MOCK/docs.new" "$MOCK/docs"
    [ -f "$MOCK/inject_on_close" ] && cat "$MOCK/inject_on_close" >> "$MOCK/docs"
    exit 0 ;;
  *office-app-guard:quit-if-empty*)
    [ "$running" = true ] || { echo not-running; exit 0; }
    prefix="${args[0]}"; n=0
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      sv="${line%%	*}"; fn="${line#*	}"
      case "$fn" in "$prefix"*) [ "$sv" = true ] && continue ;; esac
      n=$((n + 1))
    done < "$MOCK/docs"
    if [ "$n" -gt 0 ]; then echo "blocked $n"; exit 0; fi
    [ -f "$MOCK/cancel" ] && { echo canceled; exit 0; }
    echo quit >> "$MOCK/log"; echo false > "$MOCK/running"; echo quit; exit 0 ;;
  *"is running"*)
    echo "$running"; exit 0 ;;
  *"path to frontmost application"*)
    cat "$MOCK/front" 2>/dev/null; exit 0 ;;
  *"save as tgt filename"*)   # xlsx-to-pdf.sh の export (e2e 用): PDF を作る
    echo "export" >> "$MOCK/log"; : > "${args[2]}"; exit 0 ;;
  *)
    echo "other" >> "$MOCK/log"; exit 0 ;;
esac
STUB
cat > "$STUBS/open" <<'STUB'
#!/usr/bin/env bash
# fake open: -g -b <id> = 背景起動 / -a <app> = 前面を返す
case "$*" in
  "-g -b "*) echo "launch-bg ${3:-}" >> "$MOCK/log"; echo true > "$MOCK/running" ;;
  "-a "*) echo "activate $2" >> "$MOCK/log"; printf '%s/\n' "$2" > "$MOCK/front" ;;
  *) echo "open $*" >> "$MOCK/log" ;;
esac
exit 0
STUB
chmod +x "$STUBS/osascript" "$STUBS/open"
export PATH="$STUBS:$PATH"

reset_mock() { rm -f "$MOCK"/*; echo "${1:-false}" > "$MOCK/running"; : > "$MOCK/docs"; : > "$MOCK/log"; }
STAGED="$CLAUDE_OFFICE_STAGING_DIR/20260101T000000-1-abc/form.xlsx"
USERDOC="$HOME/Documents/budget.xlsx"   # staging root の外 = user の文書
TAB="$(printf '\t')"

# 関数は subshell で呼ぶ (= 各 case の env を汚さない)
run() { ( . "$LIB"; "$@"; echo "RESET=${OFFICE_APP_RESET:-} LAUNCHED=${OFFICE_APP_LAUNCHED:-}" ) 2>"$TMP/err"; }

# ---- T1: Excel が起動していない ----------------------------------------------
reset_mock false
check "$(bash "$LIB" state excel)" "not-running" "T1 state: 未起動"
out="$(run office_app_reset excel)"
check "$out" "RESET=not-running LAUNCHED=" "T1 reset: 未起動なら何もしない"
logged quit && bad "T1 reset: 未起動なのに quit した" || ok "T1 reset: quit を撃たない"
out="$( . "$LIB"; office_app_launch_background excel; echo "L=$OFFICE_APP_LAUNCHED"; office_app_release excel; echo "running=$(cat "$MOCK/running")" )"
logged "launch-bg com.microsoft.Excel" && ok "T1 launch: open -g -b で背景起動" || bad "T1 launch: 背景起動していない ($(cat "$MOCK/log"))"
case "$out" in *"L=1"*"running=false"*) ok "T1 release: 自分が起動した空の Excel は最後に quit" ;; *) bad "T1 release: $out" ;; esac

# ---- T2: 起動中、 開いているのは staged copy だけ ----------------------------
reset_mock true
printf 'false\t%s\n' "$STAGED" > "$MOCK/docs"
check "$(bash "$LIB" state excel)" "clear" "T2 state: staged copy だけ = clear (未保存でも自分の copy)"
out="$(run office_app_reset excel)"
check "$out" "RESET=quit LAUNCHED=" "T2 reset: quit"
logged "close $STAGED" && ok "T2 reset: staged copy を先に閉じる" || bad "T2 reset: staged copy を閉じていない"
logged quit && ok "T2 reset: quit を撃つ" || bad "T2 reset: quit していない"
check "$(cat "$MOCK/running")" "false" "T2 reset: 終了まで待つ"

# ---- T3: 起動中、 user の文書が開いている (must not quit) --------------------
for variant in "false${TAB}$USERDOC" "true${TAB}$USERDOC" "false${TAB}Book1"; do
    reset_mock true
    printf '%s\n%s\n' "$variant" "false${TAB}$STAGED" > "$MOCK/docs"
    label="${variant#*	} (saved=${variant%%	*})"
    check "$(bash "$LIB" state excel)" "user-docs 1" "T3 state: user の文書 $label → user-docs"
    out="$(run office_app_reset excel)"
    check "$out" "RESET=skipped-user-docs LAUNCHED=" "T3 reset: $label → skipped"
    logged quit && bad "T3 reset: $label があるのに quit した" || ok "T3 reset: $label → quit しない"
    grep -q "close ${variant#*	}" "$MOCK/log" && bad "T3 reset: user の文書を close した" || ok "T3 reset: user の文書を close しない"
    grep -q "reset (quit) を省いて続行" "$TMP/err" && ok "T3 reset: 省いた理由を stderr に出す" || bad "T3 reset: notice が無い: $(cat "$TMP/err")"
    check "$(grep -c . "$MOCK/docs")" "2" "T3 reset: 文書は 2 つとも開いたまま"
done
# 起動していた Excel (= 自分が起動していない) は release でも quit しない
reset_mock true
out="$( . "$LIB"; office_app_launch_background excel; echo "L=$OFFICE_APP_LAUNCHED"; office_app_release excel )"
check "$out" "L=0" "T3 launch: 既に起動中なら launched=0"
logged quit && bad "T3 release: 自分が起動していない Excel を quit した" || ok "T3 release: 起動していた Excel は quit しない"
# 自分が起動したが、 実行中に user が文書を開いた → quit しない
reset_mock false
( . "$LIB"; office_app_launch_background excel; printf 'false\t%s\n' "$USERDOC" >> "$MOCK/docs"; office_app_release excel ) 2>/dev/null
logged quit && bad "T3 release: 実行中に開かれた user の文書があるのに quit した" || ok "T3 release: 実行中に user が開いた文書があれば quit しない"

# ---- T4: 起動用 book (保存済) は妨げない、 未保存なら user の文書扱い ----------
STARTUP="$HOME/Library/Group Containers/UBF8T346G9.Office/User Content/Startup/Excel/PERSONAL.XLSB"
reset_mock true; printf 'true\t%s\n' "$STARTUP" > "$MOCK/docs"
check "$(bash "$LIB" state excel)" "clear" "T4 保存済みの起動用 book → clear"
out="$(run office_app_reset excel)"; check "$out" "RESET=quit LAUNCHED=" "T4 保存済みの起動用 book だけなら quit"
reset_mock true; printf 'false\t%s\n' "$STARTUP" > "$MOCK/docs"
check "$(bash "$LIB" state excel)" "user-docs 1" "T4 未保存の起動用 book → user-docs"

# ---- T5: 応答なし / dialog / 確認と quit の間に文書が開かれた ----------------
reset_mock true; touch "$MOCK/hang"
check "$(bash "$LIB" state excel)" "unknown" "T5 応答なし → unknown"
out="$(run office_app_reset excel)"; check "$out" "RESET=skipped-unknown LAUNCHED=" "T5 応答なし → quit も kill もしない"
logged quit && bad "T5 応答なしで quit した" || ok "T5 応答なしで quit しない"
reset_mock true; printf 'false\t%s\n' "$STAGED" > "$MOCK/docs"; printf 'false\t%s\n' "$USERDOC" > "$MOCK/inject_on_close"
out="$(run office_app_reset excel)"; check "$out" "RESET=skipped-user-docs LAUNCHED=" "T5 確認後に user が文書を開いた → quit しない"
logged quit && bad "T5 race で quit した" || ok "T5 race: 数え直して quit を止める"
reset_mock true; touch "$MOCK/cancel"
out="$(run office_app_reset excel)"; check "$out" "RESET=skipped-dialog LAUNCHED=" "T5 dialog で quit が取り消された → skipped-dialog"

# ---- T6: has-path -------------------------------------------------------------
reset_mock true; printf 'false\t%s\n' "$USERDOC" > "$MOCK/docs"
bash "$LIB" has-path excel "$USERDOC" && ok "T6 has-path: 同じ path" || bad "T6 has-path: 同じ path を見逃した"
bash "$LIB" has-path excel "/elsewhere/BUDGET.xlsx" && ok "T6 has-path: Excel は同名 (大小無視) も既に開いている扱い" || bad "T6 has-path: Excel の同名を見逃した"
bash "$LIB" has-path word "/elsewhere/budget.xlsx" && bad "T6 has-path: Word で別 path を同一視した" || ok "T6 has-path: Word は path 一致だけ"
reset_mock false
bash "$LIB" has-path excel "$USERDOC" && bad "T6 has-path: 未起動なのに rc=0" || ok "T6 has-path: 未起動 → rc=1"
# Excel は /private/tmp/x を /tmp/x と答える (実測) → 渡した /private 付き path でも一致して閉じられる
reset_mock true; printf 'true\t/tmp/work/deck.pptx\n' > "$MOCK/docs"
bash "$LIB" has-path powerpoint "/private/tmp/work/deck.pptx" && ok "T6 has-path: /private/tmp と /tmp を同一視" || bad "T6 has-path: /private/tmp と /tmp を別物扱い"
bash "$LIB" close-ours powerpoint "/private/tmp/work/deck.pptx"
logged "close /tmp/work/deck.pptx" && ok "T6 close-ours: /private 付きで渡しても app の答えた path の文書を閉じる" || bad "T6 close-ours: 閉じ損ねた ($(cat "$MOCK/log"))"

# ---- T7: 前面を返す条件 --------------------------------------------------------
reset_mock true
printf '/Applications/Microsoft Excel.app/\n' > "$MOCK/front"
bash "$LIB" front-restore "/Applications/Editor.app/" "Microsoft Excel.app"
logged "activate /Applications/Editor.app" && ok "T7 Excel が前面を奪っていたら元の app に返す" || bad "T7 返していない ($(cat "$MOCK/log"))"
reset_mock true; printf '/Applications/Other.app/\n' > "$MOCK/front"
bash "$LIB" front-restore "/Applications/Editor.app/" "Microsoft Excel.app"
grep -q '^activate' "$MOCK/log" && bad "T7 user が別 app に移ったのに前面を動かした" || ok "T7 Excel が前面でなければ何もしない"
reset_mock true; printf '/Applications/Microsoft Excel.app/\n' > "$MOCK/front"
bash "$LIB" front-restore "/Applications/Microsoft Excel.app/" "Microsoft Excel.app"
grep -q '^activate' "$MOCK/log" && bad "T7 元から Excel が前面だったのに動かした" || ok "T7 元から Excel が前面なら返さない"

# ---- T8: python の橋 (実装は bash 1 つ) ---------------------------------------
if command -v python3 >/dev/null 2>&1; then
    reset_mock true; printf 'false\t%s\n' "$USERDOC" > "$MOCK/docs"
    check "$(PYTHONPATH="$HERE" python3 -c 'import office_staging as o; print(o.office_app("state","excel").stdout.strip())')" "user-docs 1" "T8 python office_app(state) = bash と同じ判定"
    reset_mock false
    check "$(PYTHONPATH="$HERE" python3 -c 'import office_staging as o; r=o.office_app("launch","excel"); print(r.stdout.strip(), r.returncode)')" "launched=1 0" "T8 python office_app(launch) → launched=1"
else
    echo "SKIP T8 (python3 なし)"
fi

# ---- T9: lint = wrapper に直接の quit / kill / activate / 前面依存の参照が戻っていない ----
SCRIPTS="$(cd "$HERE/.." && pwd)"
for f in "$SCRIPTS/xlsx-to-pdf.sh" "$SCRIPTS/docx-to-pdf.sh" "$SCRIPTS/pptx-to-pdf.sh" "$SCRIPTS/affix-image-xlsx.py" "$SCRIPTS/office-stage-run.sh"; do
    [ -f "$f" ] || { bad "T9 lint: file が無い: $f"; continue; }
    hits="$(grep -nE 'killall|pkill|to quit|quit saving|active (document|presentation)|workbook 1|System Events' "$f" | grep -vE '^[0-9]+:[[:space:]]*(#|--)' | grep -vE 'never `{1,2}(active|workbook 1)|needs no System Events')"   # 「使わない」 と書いた説明文は除く
    # activate は Office の tell の中だけ禁止 (Pages 経路は背景化できず残す = 同節の射程外)
    hits="$hits$(awk '/tell application (id )?"(Microsoft|com\.microsoft)/ {office=1} /tell application "Pages"/ {office=0} /^[[:space:]]*activate[[:space:]]*$/ && office {print FILENAME":"NR": activate in an Office tell"}' "$f")"
    if [ -z "$hits" ]; then ok "T9 lint: $(basename "$f") に直接の quit / kill / activate / active 参照が無い"
    else bad "T9 lint: $(basename "$f"): $hits"; fi
done
hits="$(grep -vE '^[[:space:]]*(#|--)' "$LIB" | grep -nE 'killall|pkill|quit saving|^[[:space:]]*activate[[:space:]]*$|open -g -j')"
[ -z "$hits" ] && ok "T9 lint: guard 自体に kill / saving 付き quit / activate / hidden 起動が無い" || bad "T9 lint: guard: $hits"

# ---- T10: macOS のみ = xlsx-to-pdf.sh を stub の上で通す ---------------------
if [ "$(uname)" = "Darwin" ] && [ -f "$SCRIPTS/xlsx-to-pdf.sh" ]; then
    mkdir -p "$TMP/proj"; printf 'x' > "$TMP/proj/form.xlsx"
    E2E_PATH="$STUBS:/usr/bin:/bin"   # soffice を外して Excel 経路に入れる
    reset_mock true; printf 'false\t%s\n' "$USERDOC" > "$MOCK/docs"; printf '/Applications/Editor.app/\n' > "$MOCK/front"
    PATH="$E2E_PATH" bash "$SCRIPTS/xlsx-to-pdf.sh" "$TMP/proj/form.xlsx" >"$TMP/e2e.out" 2>&1; rc=$?
    { [ "$rc" -eq 0 ] && [ -f "$TMP/proj/form.pdf" ]; } && ok "T10 xlsx-to-pdf.sh: user の文書がある Excel でも PDF を作る" || bad "T10 rc=$rc $(tail -5 "$TMP/e2e.out")"
    logged quit && bad "T10 xlsx-to-pdf.sh: user の文書があるのに quit した" || ok "T10 xlsx-to-pdf.sh: user の文書がある Excel を quit しない"
    check "$(grep -c . "$MOCK/docs")" "1" "T10 xlsx-to-pdf.sh: user の文書は開いたまま"
    rm -f "$TMP/proj/form.pdf"
    reset_mock false; printf '/Applications/Editor.app/\n' > "$MOCK/front"
    PATH="$E2E_PATH" bash "$SCRIPTS/xlsx-to-pdf.sh" "$TMP/proj/form.xlsx" >"$TMP/e2e.out" 2>&1; rc=$?
    { [ "$rc" -eq 0 ] && [ -f "$TMP/proj/form.pdf" ]; } && ok "T10 xlsx-to-pdf.sh: 未起動から PDF を作る" || bad "T10 (未起動) rc=$rc $(tail -5 "$TMP/e2e.out")"
    { logged "launch-bg com.microsoft.Excel" && logged quit; } && ok "T10 xlsx-to-pdf.sh: 背景で起動し、 自分が起動した Excel を最後に quit" || bad "T10 (未起動) log: $(tr '\n' ' ' < "$MOCK/log")"
    rm -f "$TMP/proj/form.pdf"
    reset_mock true; printf 'false\t%s\n' "$HOME/elsewhere/form.xlsx" > "$MOCK/docs"
    PATH="$E2E_PATH" bash "$SCRIPTS/xlsx-to-pdf.sh" "$TMP/proj/form.xlsx" >"$TMP/e2e.out" 2>&1; rc=$?
    { [ "$rc" -ne 0 ] && ! logged export; } && ok "T10 xlsx-to-pdf.sh: 同名の book が開いていれば開かずに止まる" || bad "T10 (同名) rc=$rc log: $(tr '\n' ' ' < "$MOCK/log")"
else
    echo "SKIP T10 (macOS でない = xlsx-to-pdf.sh の Excel 経路に入らない)"
fi

echo "--- office-app-guard.test: PASS=$PASS FAIL=$FAIL ---"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
