#!/usr/bin/env bash
# install-launchd-cron.test.sh — install-launchd-cron.sh の cron 展開 (リスト / 範囲 / step) と、 読めない cron で plist を書く前に止まることの test
#
# launchctl と uname は偽物を PATH の先頭に置く (= 実 launchd に触らず、 Linux CI でも install 経路を通す)。
# plist の書き先は LCRON_LA_DIR で一時 dir。
#   T1 時の欄のリスト (5 8,12,17 * * *) → 3 entry、 --ensure で install される
#   T2 既存の書き方: 単一値は dict / */30 分 / 1-5 曜日
#   T3 範囲 + step + リストの組み合わせ / 月の欄 / 曜日の 7 = 0 / 全域は key を書かない
#   T4 日と曜日が両方指定 → 別 entry (= cron の「どちらかに合えば」)
#   T5 読めない cron → install / --install-one / --ensure とも exit 非 0・stderr 1 行・traceback 無し・plist 無し・
#      「ensure install」 無し
#   T6 読めない routine が 1 本でもあれば --ensure は他の routine も install しない
#   T7 --install-one は指定した routine の cron だけ読む / --status と --uninstall-one は止まらない
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$HERE/install-launchd-cron.sh"
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 が無い (plist 生成に必要)"; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  ok: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  NG: $1"; }

BIN="$TMP/bin"; STATE="$TMP/state"
mkdir -p "$BIN" "$STATE"
printf '#!/bin/sh\necho Darwin\n' > "$BIN/uname"
printf '#!/bin/sh\nexit 0\n' > "$BIN/claude"
cat > "$BIN/launchctl" <<EOF
#!/bin/sh
case "\$1" in
  bootstrap) : > "$STATE/\$(basename "\$3" .plist)" ;;
  bootout)   rm -f "$STATE/\${2##*/}" ;;
  print)     [ -f "$STATE/\${2##*/}" ] ;;
  *)         exit 1 ;;
esac
EOF
chmod +x "$BIN/uname" "$BIN/claude" "$BIN/launchctl"
if [ "$(PATH="$BIN:$PATH" command -v launchctl)" != "$BIN/launchctl" ]; then
  echo "FAIL: 偽の launchctl が PATH の先頭に来ない (実 launchd に触るので中止)"; exit 1
fi
TARGET="$TMP/job.sh"; : > "$TARGET"
LA="$TMP/la"
PREFIX="test.lcron"

engine() {  # engine を sh で起動 (= shebang と同じ。 CI の sh は dash = POSIX の検査にもなる)
  PATH="$BIN:$PATH" LCRON_LA_DIR="$LA" LCRON_LOG_DIR="$TMP/log" CLAUDE_BIN="$BIN/claude" HOME="$TMP" \
    sh "$ENGINE" --label-prefix "$PREFIX" "$@"
}
sci() {  # plist の StartCalendarInterval を key 順の compact json で
  python3 -c 'import json,plistlib,sys; print(json.dumps(plistlib.load(open(sys.argv[1],"rb"))["StartCalendarInterval"], sort_keys=True, separators=(",",":")))' "$1"
}
plist_of() { echo "$LA/$PREFIX.$1.plist"; }

N=0
expect_sci() {  # $1 = 名前, $2 = cron, $3 = 期待する StartCalendarInterval (json)
  N=$((N+1)); id="ok$N"
  engine --routine "$id|cmd|$TARGET|$2" --install-one "$id" >"$TMP/out" 2>"$TMP/err"
  rc=$?
  if [ "$rc" -ne 0 ] || [ ! -f "$(plist_of "$id")" ]; then
    ng "$1: rc=$rc / plist 無し ($(tr '\n' ' ' <"$TMP/err"))"; return
  fi
  got="$(sci "$(plist_of "$id")")"
  if [ "$got" = "$3" ]; then ok "$1"; else ng "$1: got $got / want $3"; fi
}

echo "T1 時の欄のリスト (--ensure)"
engine --routine "hours|cmd|$TARGET|5 8,12,17 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
rc=$?
got="$( [ -f "$(plist_of hours)" ] && sci "$(plist_of hours)")"
want='[{"Hour":8,"Minute":5},{"Hour":12,"Minute":5},{"Hour":17,"Minute":5}]'
[ "$rc" -eq 0 ] && [ "$got" = "$want" ] && ok "5 8,12,17 * * * → 3 entry" || ng "rc=$rc got=$got"
grep -q "ensure install: hours" "$TMP/out" && grep -q "OK loaded: $PREFIX.hours" "$TMP/out" \
  && ok "ensure install + OK loaded が出る" || ng "ensure の出力: $(tr '\n' ' ' <"$TMP/out")"
[ ! -s "$TMP/err" ] && ok "stderr 空" || ng "stderr: $(cat "$TMP/err")"

echo "T2 既存の書き方 (出力は変えない)"
expect_sci "単一値は dict" "0 3 * * *" '{"Hour":3,"Minute":0}'
expect_sci "*/30 分" "*/30 * * * *" '[{"Minute":0},{"Minute":30}]'
expect_sci "1-5 曜日" "30 10 * * 1-5" '[{"Hour":10,"Minute":30,"Weekday":1},{"Hour":10,"Minute":30,"Weekday":2},{"Hour":10,"Minute":30,"Weekday":3},{"Hour":10,"Minute":30,"Weekday":4},{"Hour":10,"Minute":30,"Weekday":5}]'
expect_sci "毎時" "7 * * * *" '{"Minute":7}'

echo "T3 範囲 + step + リスト / 月 / 曜日 7 / 全域"
expect_sci "範囲の step" "0 8-18/5 * * *" '[{"Hour":8,"Minute":0},{"Hour":13,"Minute":0},{"Hour":18,"Minute":0}]'
expect_sci "範囲とリスト" "15 9-10 * * 1,5" '[{"Hour":9,"Minute":15,"Weekday":1},{"Hour":9,"Minute":15,"Weekday":5},{"Hour":10,"Minute":15,"Weekday":1},{"Hour":10,"Minute":15,"Weekday":5}]'
expect_sci "リスト内の範囲と重複" "0,0-1 9 * * *" '[{"Hour":9,"Minute":0},{"Hour":9,"Minute":1}]'
expect_sci "月の欄を読む" "0 9 10 4 *" '{"Day":10,"Hour":9,"Minute":0,"Month":4}'
expect_sci "曜日の 7 は 0" "0 9 * * 0,7" '{"Hour":9,"Minute":0,"Weekday":0}'
expect_sci "全域の範囲は wildcard" "0 9 * 1-12 0-6" '{"Hour":9,"Minute":0}'
expect_sci "*/1 は wildcard" "*/1 9 * * *" '{"Hour":9}'

echo "T4 日と曜日が両方指定"
expect_sci "日 OR 曜日" "0 9 1,15 * 1" '[{"Day":1,"Hour":9,"Minute":0},{"Day":15,"Hour":9,"Minute":0},{"Hour":9,"Minute":0,"Weekday":1}]'

echo "T5 読めない cron で止まる"
bad_case() {  # $1 = cron, $2 = error 行に含まれるべき文字列
  for action in install --install-one --ensure; do
    N=$((N+1)); id="bad$N"
    rm -f "$STATE"/*
    if [ "$action" = --install-one ]; then
      engine --routine "$id|cmd|$TARGET|$1" --install-one "$id" >"$TMP/out" 2>"$TMP/err"
    else
      engine --routine "$id|cmd|$TARGET|$1" $action >"$TMP/out" 2>"$TMP/err"
    fi
    rc=$?
    what="\"$1\" $action"
    lines="$(wc -l <"$TMP/err" | tr -d ' ')"
    if [ "$rc" -ne 0 ] && [ "$lines" = 1 ] && grep -qF -- "$2" "$TMP/err" && grep -qF "$id" "$TMP/err" \
       && ! grep -q Traceback "$TMP/out" "$TMP/err" && [ ! -e "$(plist_of "$id")" ] \
       && ! grep -q "ensure install\|OK loaded\|plist:" "$TMP/out"; then
      ok "$what"
    else
      ng "$what: rc=$rc stderr($lines)=$(tr '\n' ' ' <"$TMP/err") stdout=$(tr '\n' ' ' <"$TMP/out")"
    fi
  done
}
bad_case "5 8,12,x * * *" '時の欄 "8,12,x"'
bad_case "60 * * * *"     '分の欄 "60"'
bad_case "0 9-5 * * *"    '時の欄 "9-5"'
bad_case "*/0 * * * *"    '分の欄 "*/0"'
bad_case "0 8,,12 * * *"  '時の欄 "8,,12"'
bad_case "0 9 * * MON"    '曜日の欄 "MON"'
bad_case "0 9 0 * *"      '日の欄 "0"'
bad_case "0 9 * 13 *"     '月の欄 "13"'
bad_case "5/15 * * * *"   '分の欄 "5/15"'
bad_case "5 8 * *"        '5 欄'

echo "T6 読めない routine が 1 本あれば --ensure は何も install しない"
rm -rf "$LA" "$STATE"; mkdir -p "$STATE"
engine --routine "good|cmd|$TARGET|0 9 * * *" --routine "broken|cmd|$TARGET|0 25 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
rc=$?
[ "$rc" -ne 0 ] && [ ! -e "$(plist_of good)" ] && [ ! -e "$(plist_of broken)" ] && ! grep -q "ensure install" "$TMP/out" \
  && ok "good も install しない" || ng "rc=$rc plist=$(ls "$LA" 2>/dev/null) out=$(tr '\n' ' ' <"$TMP/out")"
[ "$(wc -l <"$TMP/err" | tr -d ' ')" = 1 ] && grep -q 'routine broken' "$TMP/err" \
  && ok "stderr は broken の 1 行" || ng "stderr: $(cat "$TMP/err")"

echo "T7 cron を読まない action / 指定 routine だけ読む action"
engine --routine "good|cmd|$TARGET|0 9 * * *" --routine "broken|cmd|$TARGET|0 25 * * *" --install-one good >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ -f "$(plist_of good)" ] && ok "--install-one good は broken に止められない" || ng "$(cat "$TMP/out" "$TMP/err")"
engine --routine "broken|cmd|$TARGET|0 25 * * *" --status >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && ok "--status は止まらない" || ng "--status: $(cat "$TMP/err")"
engine --uninstall-one good >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ ! -e "$(plist_of good)" ] && ok "--uninstall-one は止まらない" || ng "--uninstall-one: $(cat "$TMP/err")"

echo
echo "install-launchd-cron.test.sh: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
