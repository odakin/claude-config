#!/bin/sh
# install-launchd-cron.sh — 汎用 launchd cron 登録エンジン (macOS)。
# 原理 doc: conventions/scheduled-tasks.md (= 機構選択の一般則 §0 + 本エンジンの SoT note)。
# このスクリプトが plist / label / cron→StartCalendarInterval 設計の SoT
# (= 呼び出し側 doc に複製しない、 drift 防止。 = install-remote-control-server.sh と同じパターン)。
#
# 効果: 無人ルーチンを launchd cron で回す plist を生成・登録・状態確認・解除する。
# 実行は CLI 認証 (= ~/.claude.json の単一 oauthAccount) で行われ、 Cowork desktop app の
# アカウント切り替えに非依存 (= scheduled-tasks.md §アカウント切り替えに非依存にしたいとき)。
# idempotent (再実行可)。 2 type をサポート:
#   - skill : `claude -p --permission-mode bypassPermissions` で SKILL.md を indirection 実行
#             (= run-time に Claude judgment が要る routine)
#   - cmd   : script を直接実行 (= 決定的 routine、 claude 不要 = token ゼロ)
#
# == 汎用エンジンとしての境界 ==
# ROUTINES list / label prefix / workdir は **エンジンに焼かず呼び出し側が渡す** (= 公開層 = 全
# Claude Code ユーザーで true な汎用機構のみ。 個別ジョブ定義は呼び出し側 = 個人層の責務)。
#
# == 使い方 ==
#   install-launchd-cron.sh --label-prefix PREFIX --workdir DIR \
#     --routine "id|type|target|cron" [--routine ...] [ACTION]
#
#   ACTION (既定 = 全 routine install):
#     (なし) | install          全 routine を install / 更新
#     --status                   全 routine の状態 + log tail
#     --run <task-id>            1 routine を前景で 1 回実行 (= 動作確認)
#     --install-one <task-id>    1 routine だけ install
#     --uninstall-one <task-id>  1 routine を bootout + plist 削除 (= 期間限定ジョブの停止等。
#                                 routine spec 不要 = label-prefix + id だけで動く)
#     --uninstall                全 routine を bootout + plist 削除
#
#   routine spec = "task-id|type|target|cron"
#     type   = skill | cmd
#     target = SKILL.md (skill) or script (cmd) の絶対 path (= git 管理 repo 内 / cross-machine 追跡可)
#     cron   = 5-field (minute hour dom month dow)。 `*/N` step 分 (= `*/30` → Minute [0,30,...]) と
#              `N-M` 曜日範囲 (= `1-5` → Weekday 月〜金) を StartCalendarInterval 配列へ展開する
#              (launchd は step を持たないため)。
#
#   env:
#     CRON_MODEL   skill routine の `--model` を pin (空なら CLI 既定)。 既定 model が unavailable
#                  なとき (例: 停止 model) に `CRON_MODEL=sonnet ... --install-one X` で渡す
#     CLAUDE_BIN   claude バイナリ path を上書き (既定 = command -v claude → ~/.local/bin/claude)
#
# ⚠️ macOS 限定 (launchd)。 ⚠️ launchd は LANG 空 (C locale) なので skill prompt は ASCII のみ
#    (conventions/shell-multibyte-truncation.md)。 ⚠️ 無人ルーチンは「どのマシンに登録するか」 を
#    要管理 (conventions/multi-machine-state.md)。
# ---------------------------------------------------------------------------
set -u

case "$(uname -s)" in
  Darwin) ;;
  *) echo "[skip] launchd cron is macOS-only (got $(uname -s))"; exit 0 ;;
esac

LA_DIR="${LCRON_LA_DIR:-$HOME/Library/LaunchAgents}"   # LCRON_LA_DIR は test 用 override
LOG_DIR="${LCRON_LOG_DIR:-$HOME/Library/Logs}"
DOMAIN="gui/$(id -u)"
CRON_MODEL="${CRON_MODEL:-}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")}"

LABEL_PREFIX=""
WORKDIR='$HOME'           # 既定: literal。 plist の `cd "..."` 内で launchd runtime に展開される
ROUTINES_ACC=""           # newline 区切りで "id|type|target|cron" を蓄積
ACTION="install"
ACTION_ARG=""

usage() {
  echo "usage: $0 --label-prefix PREFIX [--workdir DIR] --routine \"id|type|target|cron\" [--routine ...] \\"
  echo "          [install | --status | --run <id> | --install-one <id> | --uninstall-one <id> | --uninstall]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --label-prefix)  LABEL_PREFIX="${2:-}"; shift ;;
    --workdir)       WORKDIR="${2:-}"; shift ;;
    --routine)       ROUTINES_ACC="${ROUTINES_ACC}${2:-}
" ; shift ;;
    --status)        ACTION="status" ;;
    --run)           ACTION="run"; ACTION_ARG="${2:-}"; shift ;;
    --install-one)   ACTION="install_one"; ACTION_ARG="${2:-}"; shift ;;
    --uninstall-one) ACTION="uninstall_one"; ACTION_ARG="${2:-}"; shift ;;
    --uninstall)     ACTION="uninstall" ;;
    install|"")      ACTION="install" ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "ERROR: unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[ -n "$LABEL_PREFIX" ] || { echo "ERROR: --label-prefix が必須" >&2; usage >&2; exit 2; }

label_for()  { echo "${LABEL_PREFIX}.$1"; }
plist_path() { echo "$LA_DIR/${LABEL_PREFIX}.$1.plist"; }
log_for()    { echo "$LOG_DIR/${LABEL_PREFIX}.$1.log"; }

# ascii-only な無人実行 prompt (= SKILL.md を indirection で読ませる。 SKILL.md が SoT)
prompt_for() {
  echo "Read the file $1 and execute every step in it, in order, as an unattended scheduled run. Follow its safety rules strictly and do not skip its verification gates. Be concise."
}

list_ids() {
  printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r id _; do
    [ -n "$id" ] && printf '%s ' "$id"
  done
}

# task-id にマッチする routine spec を 1 行返す (= subshell capture、 vars は汚さない)
find_routine() {
  printf '%s\n' "$ROUTINES_ACC" | while IFS= read -r line; do
    case "$line" in
      "$1|"*) printf '%s\n' "$line"; break ;;
    esac
  done
}

# plist 生成は plistlib に委譲 (= XML エスケープ事故回避 + cron→StartCalendarInterval 変換)
write_plist() {
  task_id="$1"; kind="$2"; target="$3"; cron="$4"
  label="$(label_for "$task_id")"; plist="$(plist_path "$task_id")"; logf="$(log_for "$task_id")"
  if [ "$kind" = skill ]; then prompt="$(prompt_for "$target")"; else prompt=""; fi
  python3 - "$label" "$CLAUDE_BIN" "$kind" "$target" "$prompt" "$logf" "$cron" "$plist" "$CRON_MODEL" "$WORKDIR" <<'PYEOF'
import sys, plistlib
label, claude_bin, kind, target, prompt, logf, cron, out, model, workdir = sys.argv[1:11]
minute, hour, dom, month, dow = cron.split()
# minute: '*' / 整数 / '*/N' step (= 毎 N 分。 StartCalendarInterval は step を持たないので
# Minute 値を列挙して array に展開する。 例: '*/30' → [0, 30])
if minute == '*':
    minutes = [None]
elif minute.startswith('*/'):
    step = int(minute[2:]); minutes = list(range(0, 60, step))
else:
    minutes = [int(minute)]
base = {}
if hour != '*': base['Hour'] = int(hour)
if dom != '*': base['Day'] = int(dom)
if dow == '*':
    weekdays = [None]
elif '-' in dow:
    a, b = dow.split('-'); weekdays = list(range(int(a), int(b) + 1))
else:
    weekdays = [int(dow)]
entries = []
for m in minutes:
    for w in weekdays:
        e = dict(base)
        if m is not None: e['Minute'] = m
        if w is not None: e['Weekday'] = w
        entries.append(e)
sci = entries[0] if len(entries) == 1 else entries
# CLI 認証で実行。 API key/inference token を unset して必ず claude.ai OAuth を使う。
prefix = ('unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; '
          'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"; '
          'cd "%s" && ' % workdir)
if kind == 'skill':
    model_flag = ('--model %s ' % model) if model else ''
    cmd = prefix + 'exec "%s" -p --permission-mode bypassPermissions %s"%s"' % (claude_bin, model_flag, prompt)
else:  # cmd = 決定的 script を直接実行 (claude 不要)
    cmd = prefix + 'exec bash "%s"' % target
d = {
    'Label': label,
    'ProgramArguments': ['/bin/sh', '-c', cmd],
    'StartCalendarInterval': sci,
    'RunAtLoad': False,
    'ProcessType': 'Background',
    'StandardOutPath': logf,
    'StandardErrorPath': logf,
}
with open(out, 'wb') as f:
    plistlib.dump(d, f)
PYEOF
  echo "  plist: $plist  ($kind, cron: $cron)"
}

bootstrap_one() {
  task_id="$1"
  label="$(label_for "$task_id")"; plist="$(plist_path "$task_id")"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null
  launchctl bootstrap "$DOMAIN" "$plist" 2>/dev/null \
    || launchctl load -w "$plist" 2>/dev/null   # 旧 macOS fallback
  if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    echo "  OK loaded: $label"
  else
    echo "  WARN load 確認できず: $label (launchctl print 失敗)"
  fi
}

cli_account() {
  python3 -c 'import json;print(json.load(open("'"$HOME"'/.claude.json")).get("oauthAccount",{}).get("emailAddress","?"))' 2>/dev/null
}

cmd_install() {
  echo "== launchd cron 無人ルーチン install (host: $(hostname -s)) =="
  echo "   CLI bin: $CLAUDE_BIN"
  echo "   CLI account: $(cli_account)"
  [ -x "$CLAUDE_BIN" ] || { echo "ERROR: claude が見つからない: $CLAUDE_BIN"; exit 1; }
  mkdir -p "$LA_DIR" "$LOG_DIR"
  printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r task_id kind target cron; do
    [ -n "$task_id" ] || continue
    if [ ! -f "$target" ]; then
      echo "  WARN skip $task_id: target 不在 ($target) — 該当 repo を git pull したか確認"
      continue
    fi
    echo "- $task_id"
    write_plist "$task_id" "$kind" "$target" "$cron"
    bootstrap_one "$task_id"
  done
  echo
  echo "✅ install 完了。 動作確認は呼び出し元の --run <task-id>、 状態は --status。"
  echo "ℹ️  これらは CLI 認証 (= 上記 account) で走る。 Cowork のアカウント切替に非依存。"
}

cmd_status() {
  echo "== launchd cron 状態 (host: $(hostname -s)) =="
  printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r task_id kind target cron; do
    [ -n "$task_id" ] || continue
    label="$(label_for "$task_id")"; logf="$(log_for "$task_id")"
    echo "- $task_id ($kind, cron: $cron)"
    if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$label" 2>/dev/null | grep -E "state =|last exit code|runs =" | sed 's/^/    /'
    else
      echo "    (未登録)"
    fi
    [ -f "$logf" ] && { echo "    --- log tail ---"; tail -n 4 "$logf" | sed 's/^/    /'; }
  done
  return 0
}

cmd_run() {  # 手動 1 回実行 (= launchd を介さず、 plist と同じ実行を前景で走らせる)
  spec="$(find_routine "$ACTION_ARG")"
  [ -n "$spec" ] || { echo "ERROR: 未知の routine: $ACTION_ARG"; echo "有効: $(list_ids)"; exit 1; }
  IFS='|' read -r task_id kind target cron <<EOF
$spec
EOF
  echo "== 手動実行: $task_id ($kind) =="
  if [ "$kind" = skill ]; then
    mflag=""; [ -n "$CRON_MODEL" ] && mflag="--model $CRON_MODEL"
    eval "cd \"$WORKDIR\"" && exec "$CLAUDE_BIN" -p --permission-mode bypassPermissions $mflag "$(prompt_for "$target")"
  else
    eval "cd \"$WORKDIR\"" && exec bash "$target"
  fi
}

cmd_install_one() {  # 単体 install (= このマシンでは一部 routine だけ動かしたい時)
  [ -n "$ACTION_ARG" ] || { echo "usage: --install-one <task-id>"; exit 1; }
  [ -x "$CLAUDE_BIN" ] || { echo "ERROR: claude が見つからない: $CLAUDE_BIN"; exit 1; }
  spec="$(find_routine "$ACTION_ARG")"
  [ -n "$spec" ] || { echo "ERROR: 未知の routine: $ACTION_ARG"; echo "有効: $(list_ids)"; exit 1; }
  IFS='|' read -r task_id kind target cron <<EOF
$spec
EOF
  [ -f "$target" ] || { echo "ERROR: target 不在 ($target) — 該当 repo を git pull したか確認"; exit 1; }
  mkdir -p "$LA_DIR" "$LOG_DIR"
  echo "== 単体 install: $task_id (host: $(hostname -s)) =="
  echo "   CLI account: $(cli_account)"
  write_plist "$task_id" "$kind" "$target" "$cron"
  bootstrap_one "$task_id"
  echo "✅ $task_id を install。 動作確認は呼び出し元の --run $task_id。"
}

cmd_uninstall_one() {  # 単体 uninstall (= 期間限定ジョブの停止等。 routine spec 不要)
  [ -n "$ACTION_ARG" ] || { echo "usage: --uninstall-one <task-id>"; exit 1; }
  label="$(label_for "$ACTION_ARG")"; plist="$(plist_path "$ACTION_ARG")"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null
  rm -f "$plist"
  echo "✅ removed: $label"
}

cmd_uninstall() {
  printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r task_id kind target cron; do
    [ -n "$task_id" ] || continue
    label="$(label_for "$task_id")"; plist="$(plist_path "$task_id")"
    launchctl bootout "$DOMAIN/$label" 2>/dev/null
    rm -f "$plist"
    echo "  removed: $label"
  done
  echo "✅ uninstall 完了"
}

case "$ACTION" in
  status)         cmd_status ;;
  run)            cmd_run ;;
  install_one)    cmd_install_one ;;
  uninstall_one)  cmd_uninstall_one ;;
  uninstall)      cmd_uninstall ;;
  install)        cmd_install ;;
esac
