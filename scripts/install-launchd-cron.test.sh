#!/usr/bin/env bash
# install-launchd-cron.test.sh — install-launchd-cron.sh の cron 展開 (リスト / 範囲 / step)、 読めない cron で plist を書く前に止まること、 --ensure が cron の変わった routine を直すことの test
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
#   T6b --ensure は loaded で照合前の routine の cron も読む / 全部照合済みなら python を起動しない
#   T8 loaded 済み routine の cron (または変換の版) が変わったら --ensure が StartCalendarInterval だけ書き換えて
#      再 load (ProgramArguments の pin は残す)、 実行中なら保留、 plist が消えていれば書き直す、 照合済み印の読み書き
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$HERE/install-launchd-cron.sh"
V="$(sed -n 's/^CAL_VERSION=\([0-9]*\).*/\1/p' "$ENGINE")"   # 照合済み印の版
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
  print)     [ -f "$STATE/\${2##*/}" ] || exit 1
             [ -f "$STATE/\${2##*/}.running" ] && echo "state = running"
             exit 0 ;;
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

echo "T6b --ensure の定常状態と照合前の読めない routine"
: > "$STATE/$PREFIX.broken"
engine --routine "good|cmd|$TARGET|0 9 * * *" --routine "broken|cmd|$TARGET|0 25 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
rc=$?
[ "$rc" -ne 0 ] && [ ! -e "$(plist_of good)" ] && [ "$(wc -l <"$TMP/err" | tr -d ' ')" = 1 ] && grep -q 'routine broken' "$TMP/err" \
  && ok "loaded で未照合の broken も読む = good も install せず止まる" || ng "rc=$rc plist=$(ls "$LA" 2>/dev/null) err=$(cat "$TMP/err")"
rm -f "$STATE/$PREFIX.broken"
engine --routine "good|cmd|$TARGET|0 9 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ -f "$(plist_of good)" ] && ok "broken を直せば good が入る" || ng "$(cat "$TMP/out" "$TMP/err")"
nopy_engine() {  # python3 を「起動したら印を残して失敗する」 偽物にして engine を回す
  PATH="$TMP/nopy:$BIN:$PATH" LCRON_LA_DIR="$LA" LCRON_LOG_DIR="$TMP/log" CLAUDE_BIN="$BIN/claude" HOME="$TMP" \
    sh "$ENGINE" --label-prefix "$PREFIX" "$@"
}
mkdir -p "$TMP/nopy"
printf '#!/bin/sh\n: > "%s/python-ran"\nexit 1\n' "$TMP" > "$TMP/nopy/python3"
chmod +x "$TMP/nopy/python3"
rm -f "$TMP/python-ran"
nopy_engine --routine "good|cmd|$TARGET|0 9 * * *" --ensure >"$TMP/out" 2>&1
[ $? -eq 0 ] && [ ! -e "$TMP/python-ran" ] && [ ! -s "$TMP/out" ] && ok "全部 loaded + 照合済みなら python を起動せず無言" || ng "python が走った / $(cat "$TMP/out")"

echo "T7 cron を読まない action / 指定 routine だけ読む action"
engine --routine "good|cmd|$TARGET|0 9 * * *" --routine "broken|cmd|$TARGET|0 25 * * *" --install-one good >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ -f "$(plist_of good)" ] && ok "--install-one good は broken に止められない" || ng "$(cat "$TMP/out" "$TMP/err")"
engine --routine "broken|cmd|$TARGET|0 25 * * *" --status >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && ok "--status は止まらない" || ng "--status: $(cat "$TMP/err")"
engine --uninstall-one good >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ ! -e "$(plist_of good)" ] && ok "--uninstall-one は止まらない" || ng "--uninstall-one: $(cat "$TMP/err")"

echo "T8 loaded 済み routine の cron が変わったら --ensure が calendar だけ直す"
rm -rf "$LA" "$STATE"; mkdir -p "$STATE"
STAMP="$TMP/Library/Application Support/install-launchd-cron/$PREFIX.upd.cron"
engine --routine "upd|cmd|$TARGET|0 9 10 * *" --install-one upd >/dev/null 2>&1
# install 後に plist の command へ手で pin 相当の印を足す (= 自動更新が ProgramArguments を触らないことの確認用)
python3 -c 'import plistlib,sys; p=sys.argv[1]; d=plistlib.load(open(p,"rb")); d["ProgramArguments"][-1]+=" # PIN-MARK"; plistlib.dump(d,open(p,"wb"))' "$(plist_of upd)"
has_pin() { python3 -c 'import plistlib,sys; sys.exit(0 if "PIN-MARK" in plistlib.load(open(sys.argv[1],"rb"))["ProgramArguments"][-1] else 1)' "$(plist_of upd)"; }
[ "$(cat "$STAMP" 2>/dev/null)" = "$V 0 9 10 * *" ] && ok "install が照合済み印を書く (空白を含む既定 dir)" || ng "印: $(cat "$STAMP" 2>&1)"

engine --routine "upd|cmd|$TARGET|0 9 10 4 *" --ensure >"$TMP/out" 2>"$TMP/err"
rc=$?
got="$(sci "$(plist_of upd)")"
if [ "$rc" -eq 0 ] && [ "$got" = '{"Day":10,"Hour":9,"Minute":0,"Month":4}' ] && grep -q "ensure update: upd" "$TMP/out" \
   && grep -q "OK loaded: $PREFIX.upd" "$TMP/out" && has_pin && [ "$(cat "$STAMP")" = "$V 0 9 10 4 *" ] && [ ! -s "$TMP/err" ]; then
  ok "cron の変更 → calendar だけ書き換え + 再 load + 印更新 (pin は残る)"
else
  ng "rc=$rc got=$got out=$(tr '\n' ' ' <"$TMP/out") err=$(cat "$TMP/err") stamp=$(cat "$STAMP")"
fi

rm -f "$TMP/python-ran"
nopy_engine --routine "upd|cmd|$TARGET|0 9 10 4 *" --ensure >"$TMP/out" 2>&1
[ $? -eq 0 ] && [ ! -e "$TMP/python-ran" ] && [ ! -s "$TMP/out" ] && ok "更新後の 2 回目は python 0 回・無言" || ng "$(cat "$TMP/out")"

rm -f "$STAMP"
engine --routine "upd|cmd|$TARGET|0 9 10 4 *" --ensure >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ ! -s "$TMP/out" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$V 0 9 10 4 *" ] \
  && ok "印が無く calendar が一致 (= 旧 engine で入れた routine) → 書き換えず印だけ書く" || ng "out=$(cat "$TMP/out") stamp=$(cat "$STAMP" 2>&1)"

printf '1 0 9 10 4 *\n' > "$STAMP"
engine --routine "upd|cmd|$TARGET|0 9 10 4 *" --ensure >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && [ ! -s "$TMP/out" ] && [ "$(cat "$STAMP")" = "$V 0 9 10 4 *" ] \
  && ok "変換の版が古い印 → 照合し直して印を今の版に" || ng "out=$(cat "$TMP/out") stamp=$(cat "$STAMP")"

: > "$STATE/$PREFIX.upd.running"
engine --routine "upd|cmd|$TARGET|0 9 10 5 *" --ensure >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && grep -q "ensure update 保留: upd" "$TMP/out" && [ "$(sci "$(plist_of upd)")" = '{"Day":10,"Hour":9,"Minute":0,"Month":4}' ] \
  && [ "$(cat "$STAMP")" = "$V 0 9 10 4 *" ] && ok "実行中の job は書き換えず保留 (印も据え置き)" || ng "out=$(cat "$TMP/out") stamp=$(cat "$STAMP")"
rm -f "$STATE/$PREFIX.upd.running"
engine --routine "upd|cmd|$TARGET|0 9 10 5 *" --ensure >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && grep -q "ensure update: upd" "$TMP/out" && [ "$(sci "$(plist_of upd)")" = '{"Day":10,"Hour":9,"Minute":0,"Month":5}' ] \
  && ok "実行が終われば次の --ensure で直す" || ng "out=$(cat "$TMP/out")"

rm -f "$(plist_of upd)"
engine --routine "upd|cmd|$TARGET|0 9 10 6 *" --ensure >"$TMP/out" 2>"$TMP/err"
[ $? -eq 0 ] && grep -q "ensure install: upd (loaded だが plist が無い)" "$TMP/out" && [ "$(sci "$(plist_of upd)")" = '{"Day":10,"Hour":9,"Minute":0,"Month":6}' ] \
  && ok "loaded だが plist が消えていれば書き直す" || ng "out=$(cat "$TMP/out") err=$(cat "$TMP/err")"

engine --routine "upd|cmd|$TARGET|0 9 10 6 *" --uninstall-one upd >/dev/null 2>&1
[ ! -e "$STAMP" ] && [ ! -e "$(plist_of upd)" ] && ok "--uninstall-one が印も消す" || ng "印が残った"

echo "T9 関門の失敗 (python が起動できない等) を待機と分ける + 旧形の plist を --ensure が新形に直す"
GT="$TMP/gtarget.sh"; printf '#!/bin/sh\necho ran > "%s/ran"\n' "$TMP" > "$GT"; chmod +x "$GT"
gcmd() { python3 -c 'import plistlib,sys; print(plistlib.load(open(sys.argv[1],"rb"))["ProgramArguments"][2])' "$(plist_of "$1")"; }
for g in "true:0:ran" "false:0:skip" "sh -c 'exit 69':69:skip"; do
  gate="${g%%:*}"; rest="${g#*:}"; want_rc="${rest%%:*}"; want_run="${rest#*:}"
  engine --workdir "$TMP" --gate "$gate" --routine "g|cmd|$GT|0 9 * * *" --install-one g >/dev/null 2>&1
  rm -f "$TMP/ran"
  HOME="$TMP" /bin/sh -c "$(gcmd g)" >/dev/null 2>"$TMP/gerr"; rc=$?
  ran=skip; [ -f "$TMP/ran" ] && ran=ran
  if [ "$rc" = "$want_rc" ] && [ "$ran" = "$want_run" ]; then ok "関門 [$gate] → rc=$rc / $ran"
  else ng "関門 [$gate] → rc=$rc (want $want_rc) / $ran (want $want_run) err=$(cat "$TMP/gerr")"; fi
done
grep -q "routine gate failed rc=69" "$TMP/gerr" && ok "関門の失敗は stderr に 1 行 (= launchd の log に残る)" || ng "stderr=$(cat "$TMP/gerr")"
# 旧形の plist (+ 手で足した pin) を置き、 旧版の照合済み印を書いてから --ensure
python3 - "$(plist_of g)" <<'PYOLD'
import plistlib, re, sys
p = sys.argv[1]; d = plistlib.load(open(p, "rb")); c = d["ProgramArguments"][2]
c = re.sub(r'\{ (.+?); _g=\$\?;.*?fi; \} && exec ', r'\1 || exit 0; exec ', c, flags=re.S) + " # PIN-MARK"
d["ProgramArguments"][2] = c; plistlib.dump(d, open(p, "wb"))
PYOLD
gcmd g | grep -q ' || exit 0; exec ' && ok "旧形の plist を用意できた" || ng "旧形にできない: $(gcmd g)"
printf '2 0 9 * * *\n' > "$TMP/Library/Application Support/install-launchd-cron/$PREFIX.g.cron" 2>/dev/null \
  || { mkdir -p "$TMP/lstate"; printf '2 0 9 * * *\n' > "$TMP/lstate/$PREFIX.g.cron"; }
PATH="$BIN:$PATH" LCRON_LA_DIR="$LA" LCRON_LOG_DIR="$TMP/log" CLAUDE_BIN="$BIN/claude" HOME="$TMP" \
  sh "$ENGINE" --label-prefix "$PREFIX" --workdir "$TMP" --gate "sh -c 'exit 69'" --routine "g|cmd|$GT|0 9 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
c="$(gcmd g)"
if printf '%s' "$c" | grep -q '_g=\$?' && ! printf '%s' "$c" | grep -q ' || exit 0; exec ' && printf '%s' "$c" | grep -q 'PIN-MARK' \
   && grep -q "ensure update: g" "$TMP/out"; then ok "--ensure が旧形の関門を新形に直す (pin は残す)"
else ng "out=$(cat "$TMP/out") err=$(cat "$TMP/err") cmd=$c"; fi

echo "T10 skill は stream-json の log 中継で起動し、 どの type も CLAUDE_ROUTINE_ID を export する"
SB="$TMP/sbin"; mkdir -p "$SB"
FIX="$TMP/stream.jsonl"
cat > "$FIX" <<'JSONL'
{"type":"system","subtype":"init","model":"fake-model","session_id":"0123456789abcdef"}
{"type":"assistant","message":{"content":[{"type":"text","text":"本報告の行"}]}}
{"type":"user","message":{"content":[{"type":"text","text":"Stop hook feedback:\n追記を求める"}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"追記の行"}]}}
{"type":"result","subtype":"success","is_error":false,"result":"追記の行","num_turns":2}
JSONL
cat > "$SB/claude" <<EOF
#!/bin/sh
if [ "\$1" = "--help" ]; then
  echo "  --no-session-persistence  --settings <x>  --output-format <format> (text, json, stream-json)  --include-hook-events"
  exit 0
fi
echo "routine=\$CLAUDE_ROUTINE_ID" > "$TMP/seen-env"
cat "$FIX"
exit 5
EOF
chmod +x "$SB/claude"
sengine() {  # stream-json を持つ偽の claude で engine を回す
  PATH="$BIN:$PATH" LCRON_LA_DIR="$LA" LCRON_LOG_DIR="$TMP/log" CLAUDE_BIN="$SB/claude" HOME="$TMP" \
    sh "$ENGINE" --label-prefix "$PREFIX" "$@"
}
SKT="$TMP/SKILL.md"; : > "$SKT"
pcmd() { python3 -c 'import plistlib,sys; print(plistlib.load(open(sys.argv[1],"rb"))["ProgramArguments"][2])' "$(plist_of "$1")"; }
RENDER="$HERE/claude-stream-log.py"
CRON_MODEL=m1 sengine --workdir "$TMP" --routine "sk|skill|$SKT|0 9 * * *" --install-one sk >"$TMP/out" 2>"$TMP/err"
c="$(pcmd sk)"
want_launch="exec python3 \"$RENDER\" -- \"$SB/claude\" -p --output-format stream-json --verbose --include-hook-events --no-session-persistence"
case "$c" in
  *"$want_launch"*"--model m1 "*) ok "skill の起動行 = 中継 + stream-json + 既存の flag と model の pin" ;;
  *) ng "skill の起動行: $c" ;;
esac
case "$c" in *'export CLAUDE_ROUTINE_ID="sk"; '*) ok "skill も CLAUDE_ROUTINE_ID を export" ;; *) ng "routine id が無い: $c" ;; esac
python3 - "$(plist_of sk)" "$HERE/lib" <<'PYJL' && ok "runs_claude_p は新しい起動行でも claude -p と読む" || ng "runs_claude_p が読めない"
import plistlib, sys
sys.path.insert(0, sys.argv[2])
import launchd_job_log as j
sys.exit(0 if j.runs_claude_p(plistlib.load(open(sys.argv[1], "rb"))) else 1)
PYJL

echo "T11 起動して log に本報告と追記の両方が残る + 終了値は claude のもの"
mkdir -p "$TMP/log"
LOGF="$TMP/log/$PREFIX.sk.log"; : > "$LOGF"
HOME="$TMP" PATH="$PATH" /bin/sh -c "$(pcmd sk)" >>"$LOGF" 2>&1; rc=$?
[ "$rc" -eq 5 ] && ok "終了値 5 がそのまま出る" || ng "rc=$rc log=$(cat "$LOGF")"
grep -q "本報告の行" "$LOGF" && grep -q "追記の行" "$LOGF" && ok "本報告と追記の両方が log に残る" || ng "log: $(cat "$LOGF")"
grep -q "^── .* 開始 · fake-model · session 01234567 ──" "$LOGF" && tail -n 1 "$LOGF" | grep -q "rc=5" \
  && ok "開始と終わりの行" || ng "log: $(cat "$LOGF")"
grep -q "routine=sk" "$TMP/seen-env" 2>/dev/null && ok "claude の中から CLAUDE_ROUTINE_ID が見える" || ng "env: $(cat "$TMP/seen-env" 2>&1)"

echo "T12 stream-json を持たない CLI では従来の exec に戻る (routine id は付ける)"
CRON_MODEL=m1 engine --workdir "$TMP" --routine "old|skill|$SKT|0 9 * * *" --install-one old >/dev/null 2>&1
c="$(pcmd old)"
case "$c" in
  *"exec \"$BIN/claude\" -p "*) case "$c" in *claude-stream-log*) ng "中継が入った: $c" ;; *) ok "従来の exec claude -p" ;; esac ;;
  *) ng "起動行: $c" ;;
esac
case "$c" in *'CLAUDE_ROUTINE_ID="old"'*) ok "degrade しても routine id は付く" ;; *) ng "routine id が無い: $c" ;; esac

echo "T13 旧形の skill の plist を --ensure が中継つきに直す (pin は残す・2 回目は無言)"
CRON_MODEL=m1 engine --workdir "$TMP" --routine "old2|skill|$SKT|0 9 * * *" --install-one old2 >/dev/null 2>&1
# old = 旧 engine が書いた形 (routine id 無し) で、 plist の claude は stream-json を持つ版 / old2 = plist の claude が持たない版
python3 - "$(plist_of old)" "$(plist_of old2)" "$BIN/claude" "$SB/claude" <<'PYOLD2'
import plistlib, sys
for p, tid, swap in ((sys.argv[1], "old", True), (sys.argv[2], "old2", False)):
    d = plistlib.load(open(p, "rb")); c = d["ProgramArguments"][2]
    c = c.replace('export CLAUDE_ROUTINE_ID="%s"; ' % tid, '') + " # PIN-MARK"
    if swap:
        c = c.replace('"%s"' % sys.argv[3], '"%s"' % sys.argv[4])
    d["ProgramArguments"][2] = c; plistlib.dump(d, open(p, "wb"))
PYOLD2
for t in old old2; do printf '3 0 9 * * *\n' > "$TMP/Library/Application Support/install-launchd-cron/$PREFIX.$t.cron"; done
sengine --workdir "$TMP" --routine "old|skill|$SKT|0 9 * * *" --routine "old2|skill|$SKT|0 9 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
c="$(pcmd old)"
case "$c" in
  *"exec python3 \"$RENDER\" -- \"$SB/claude\" -p --output-format stream-json --verbose --include-hook-events "*"--model m1 "*"PIN-MARK"*)
    ok "旧形 → 中継つき (claude の path・model の pin・手で足した印は残る)" ;;
  *) ng "直らない: $c / out=$(cat "$TMP/out") err=$(cat "$TMP/err")" ;;
esac
c2="$(pcmd old2)"
case "$c2" in
  *claude-stream-log*) ng "stream-json を持たない claude に中継を付けた: $c2" ;;
  *'export CLAUDE_ROUTINE_ID="old2"; '*"exec \"$BIN/claude\" -p "*PIN-MARK*) ok "plist の claude が stream-json を持たなければ exec のまま (routine id だけ足す)" ;;
  *) ng "old2: $c2" ;;
esac
case "$c" in *'unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; export CLAUDE_ROUTINE_ID="old"; '*) ok "routine id を unset の直後に足す" ;; *) ng "routine id: $c" ;; esac
grep -q "ensure update: old" "$TMP/out" && ok "ensure update が出る" || ng "out=$(cat "$TMP/out")"
c1="$c"
sengine --workdir "$TMP" --routine "old|skill|$SKT|0 9 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
[ ! -s "$TMP/out" ] && [ "$(pcmd old)" = "$c1" ] && ok "2 回目は無言・起動行も同じ" || ng "2 回目: out=$(cat "$TMP/out")"
rm -f "$TMP/Library/Application Support/install-launchd-cron/$PREFIX.old.cron"
sengine --workdir "$TMP" --routine "old|skill|$SKT|0 9 * * *" --ensure >"$TMP/out" 2>"$TMP/err"
[ ! -s "$TMP/out" ] && [ "$(pcmd old)" = "$c1" ] && ok "印が無くても照合して書き換えない (冪等)" || ng "冪等でない: $(pcmd old)"

echo "T14 cmd も CLAUDE_ROUTINE_ID を export し、 script から見える"
CT="$TMP/cmdjob.sh"; printf '#!/bin/sh\necho "cmd-routine=$CLAUDE_ROUTINE_ID" > "%s/cmd-env"\n' "$TMP" > "$CT"; chmod +x "$CT"
engine --workdir "$TMP" --routine "cj|cmd|$CT|0 9 * * *" --install-one cj >/dev/null 2>&1
HOME="$TMP" /bin/sh -c "$(pcmd cj)" >/dev/null 2>&1
grep -q "cmd-routine=cj" "$TMP/cmd-env" 2>/dev/null && ok "cmd の script から routine id が見える" || ng "cmd env: $(cat "$TMP/cmd-env" 2>&1) cmd=$(pcmd cj)"

echo
echo "install-launchd-cron.test.sh: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
