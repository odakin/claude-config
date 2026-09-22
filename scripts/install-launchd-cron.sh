#!/bin/sh
# install-launchd-cron.sh — 汎用 launchd cron 登録エンジン（無人ルーチンを launchd cron で回す plist 生成・登録・状態確認・解除。--label-prefix / --workdir / --routine "id\|type\|target\|cron" を呼び出し側が渡す＝ROUTINES 焼かず汎用、cron の各欄の , リスト・N-M 範囲・*/S と N-M/S step を StartCalendarInterval 配列へ展開 (読めない欄は plist を書く前に 1 行で exit 2)、skill=claude -p indirection / cmd=直接実行、CLI 認証で Claude Code (desktop) 切替非依存、--status/--run/--install-one/--uninstall-one/--uninstall/--ensure（未install を install=新ホスト自動配備 + loaded でも cron が plist とずれていれば calendar だけ書き換えて再 load、SessionStart から呼ぶ）、idempotent、macOS 限定、conventions/scheduled-tasks.md#launchd-cron-engine）
# install-launchd-cron.sh — 汎用 launchd cron 登録エンジン (macOS)。
# 原理 doc: conventions/scheduled-tasks.md (= 機構選択の一般則 §0 + 本エンジンの SoT note)。
# このスクリプトが plist / label / cron→StartCalendarInterval 設計の SoT
# (= 呼び出し側 doc に複製しない、 drift 防止。 = install-remote-control-server.sh と同じパターン)。
#
# 効果: 無人ルーチンを launchd cron で回す plist を生成・登録・状態確認・解除する。
# 実行は CLI 認証 (= ~/.claude.json の単一 oauthAccount) で行われ、 Claude Code desktop app の
# アカウント切り替えに非依存 (= scheduled-tasks.md#account-switch-independent)。
# idempotent (再実行可)。 2 type をサポート:
#   - skill : `claude -p --permission-mode bypassPermissions` で SKILL.md を indirection 実行
#             (= run-time に Claude judgment が要る routine)。 CLI が対応していれば
#             `--no-session-persistence` を併用 = 無人 run の session を保存しない
#             (= 「最近の項目」/session 一覧を cron session で汚さない。 transcript は残らないため
#             事後デバッグは StandardOutPath の log file が唯一の手掛かり。 機構差の SoT =
#             conventions/scheduled-tasks.md#headless-session-persistence)
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
#     --ensure                   未 install の routine を install + loaded 済みでも cron (または engine の
#                                 cron→calendar 変換の版) が plist とずれていれば StartCalendarInterval だけ
#                                 書き換えて再 load (= 冪等・quiet・fail-open)。 SessionStart 等から呼び、
#                                 新 routine も cron の変更も git pull したマシンに自動で届く。
#                                 ⚠️ 届くのは calendar だけ: command 側 (--gate / CRON_MODEL / CRON_EFFORT /
#                                 CRON_CONFIG_DIR / target) の変更は --install-one で入れ直す (= 自動で作り直すと
#                                 install 時に手で渡した pin が消えるため、 あえて触らない)。 実行中の job は殺さない
#                                 よう次の --ensure に回す。 照合済み印 = $LCRON_STATE_DIR (既定
#                                 ~/Library/Application Support/install-launchd-cron/) の <label>.cron
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
#     cron   = 5-field (minute hour dom month dow)。 各欄に書ける形 = `*` / `N` / `N-M` / `*/S` /
#              `N-M/S` と、 それらの `,` 区切り (例: `5 8,12,17 * * *` / `*/30 9-17 * * 1-5`)。
#              launchd は範囲・リスト・step を持たないので、 値を列挙して StartCalendarInterval の
#              配列へ展開する (全域になる欄は key を書かない = wildcard)。 曜日の 7 は 0 (日曜)。
#              日と曜日が両方 `*` 以外なら cron と同じく「どちらかに合えば」 走る (= 別 entry に分ける)。
#              名前 (`MON` / `JAN`)・`N/S`・`@daily` 等は読まない: install / --install-one / --ensure は
#              plist を 1 枚も書く前に「どの routine のどの欄の何が読めないか」 を 1 行ずつ stderr に
#              出して exit 2 (--status / --run / --uninstall* は cron を読まないので止まらない)。
#
#   env:
#     CRON_MODEL   skill routine の `--model` を pin (空なら CLI 既定)。 既定 model が unavailable
#                  なとき (例: 停止 model) に `CRON_MODEL=sonnet ... --install-one X` で渡す
#     CRON_EFFORT  skill routine の `--effort` を pin (空なら CLI 既定)。 low/medium/high/xhigh/max
#     CRON_CONFIG_DIR
#                  routine を **別 account の認証ストア (CLAUDE_CONFIG_DIR)** で走らせる pin
#                  (空 = 従来どおり既定 ~/.claude.json の account)。 plist に
#                  `export CLAUDE_CONFIG_DIR="<dir>"` を焼く (skill/cmd 両 kind、 cmd は claude を
#                  呼ばなければ無害)。 用途 = 対話 CLI の account を保ったまま無人 routine の消費
#                  account だけ分離する (例: usage 制限 window を無人時間帯に揃える)。
#                  ⚠️ dir は事前に `CLAUDE_CONFIG_DIR=<dir> claude auth login` 済 + headless 生成可
#                  であること (metadata 上 login 済でも headless 401 になりうる — 導入時は --run で probe)。
#                  ⚠️ MCP 登録 / settings.json は config dir ごとに独立 — routine が MCP (Gmail 等) を
#                  使うなら pin 先 dir にも同じ登録が必要。
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
STATE_DIR="${LCRON_STATE_DIR:-$HOME/Library/Application Support/install-launchd-cron}"   # --ensure の照合済み印
CAL_VERSION=3   # plist 変換の版 (2 = 各欄の , / N-M / */S / N-M/S + 月 + 日と曜日の OR、 3 = 関門の起動行が失敗を待機と分ける)
DOMAIN="gui/$(id -u)"
CRON_MODEL="${CRON_MODEL:-}"
CRON_EFFORT="${CRON_EFFORT:-}"
CRON_CONFIG_DIR="${CRON_CONFIG_DIR:-}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")}"

# node の場所を install 時に解決して plist PATH へ追記する (2026-08-29)。
# launchd の PATH には nvm 等の node が乗らないため、 stdio MCP server (command: node / npx) を
# headless routine が spawn できない環境がある (= claude 本体が native binary だと routine 自体は
# 走るのに MCP だけ silent に欠ける)。 install した shell で node が解決できればその dir を焼く。
NODE_BIN_DIR="$(command -v node 2>/dev/null || true)"
[ -n "$NODE_BIN_DIR" ] && NODE_BIN_DIR="$(dirname "$NODE_BIN_DIR")"

# skill routine の session を保存しない (= 「最近の項目」 を無人 run で汚さない)。 --print 専用 flag。
# 古い CLI は未対応の可能性があるため install/run 時に capability check し、 対応時のみ付与
# (= 未対応 CLI では従来挙動に degrade、 routine を殺さない)。
CLAUDE_HELP="$("$CLAUDE_BIN" --help 2>/dev/null || true)"
NOPERSIST_FLAG=""
printf '%s' "$CLAUDE_HELP" | grep -q -- --no-session-persistence && NOPERSIST_FLAG="--no-session-persistence"

# さらに Remote Control の startup 自動有効化 (= settings の remoteControlAtStartup: true) を
# cron run では per-invocation で無効化する。 有効のままだと無人 run が hostname-prefix の
# RC session (例: <hostname>-<codename>) として claude.ai に登録され「最近の項目」 に出る +
# session が終了せず積み上がる事例あり (機構差の SoT = scheduled-tasks.md#headless-session-persistence)。
# 対話 session の I3 (= 手元 session のリモート続行) には影響しない (= cron invocation のみ override)。
RCOFF=""
printf '%s' "$CLAUDE_HELP" | grep -q -- --settings && RCOFF=1

LABEL_PREFIX=""
WORKDIR='$HOME'           # 既定: literal。 plist の `cd "..."` 内で launchd runtime に展開される
GATE_SNIPPET=""           # 任意: 各 job の wrapper に挿入する gate。 `cd && <gate> || exit 0; exec ...`
                          #       gate が非 0 で終わると routine は実行されず exit 0 (= defer)。
                          #       active-routine-host pattern (multi-machine-state.md) 等に使う
ROUTINES_ACC=""           # newline 区切りで "id|type|target|cron" を蓄積
ACTION="install"
ACTION_ARG=""

usage() {
  echo "usage: $0 --label-prefix PREFIX [--workdir DIR] [--gate SNIPPET] --routine \"id|type|target|cron\" [--routine ...] \\"
  echo "          [install | --ensure | --status | --run <id> | --install-one <id> | --uninstall-one <id> | --uninstall]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --label-prefix)  LABEL_PREFIX="${2:-}"; shift ;;
    --workdir)       WORKDIR="${2:-}"; shift ;;
    --gate)          GATE_SNIPPET="${2:-}"; shift ;;
    --routine)       ROUTINES_ACC="${ROUTINES_ACC}${2:-}
" ; shift ;;
    --status)        ACTION="status" ;;
    --run)           ACTION="run"; ACTION_ARG="${2:-}"; shift ;;
    --install-one)   ACTION="install_one"; ACTION_ARG="${2:-}"; shift ;;
    --uninstall-one) ACTION="uninstall_one"; ACTION_ARG="${2:-}"; shift ;;
    --uninstall)     ACTION="uninstall" ;;
    --ensure)        ACTION="ensure" ;;
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

# cron→StartCalendarInterval 変換と plist 生成 (= plistlib に委譲、 XML エスケープ事故回避)。
#   plist_py check <task-id> <cron> [...]    cron だけ読む (組を並べて 1 process で)。 読めない組ごとに
#                                            1 行を stderr に出し、 1 つでもあれば exit 2
#   plist_py write <task-id> <cron> <...>     plist を書く (読めない cron は check と同じ 1 行で exit 2)
plist_py() {
  python3 - "$@" <<'PYEOF'
import sys, re, plistlib

# 関門 (--gate) の起動行。 関門の終了値は 0 = 実行 / 1 = 待機 (別のマシンが本番)。 旧形 `GATE || exit 0` は
# それ以外の非 0 (python3 が起動できない exit 69・127 など) も「待機」 と同じ exit 0 にしていた = ジョブが
# 黙って永久に休み、 launchd の記録は成功のまま (conventions/shell-env.md#job-python-by-capability)。
# 新形は待機だけを exit 0 にし、 失敗は非 0 で終わらせて launchd の終了コード (cron health・fleet の job health) に出す。
def gate_block(gate):
    return ('{ %s; _g=$?; if [ "$_g" -eq 1 ]; then exit 0; elif [ "$_g" -ne 0 ]; then '
            'echo "routine gate failed rc=$_g" >&2; exit "$_g"; fi; } && ' % gate)


_OLD_GATE_RE = re.compile(r'(cd "[^"]*" && )(.+?) \|\| exit 0; (exec )', re.S)


def upgrade_gate(cmd):
    """旧形 `cd W && GATE || exit 0; exec ...` を新形 `cd W && { GATE; ... } && exec ...` に (他は 1 文字も変えない)。"""
    m = _OLD_GATE_RE.search(cmd)
    if not m:
        return cmd
    return cmd[:m.start()] + m.group(1) + gate_block(m.group(2)) + m.group(3) + cmd[m.end():]

# 5 欄の名前・plist key・値域。 曜日の 7 は 0 (日曜) と同じ。
FIELDS = [('分', 'Minute', 0, 59), ('時', 'Hour', 0, 23), ('日', 'Day', 1, 31),
          ('月', 'Month', 1, 12), ('曜日', 'Weekday', 0, 7)]
NUM = re.compile(r'[0-9]+')

class Unreadable(Exception):
    pass

class CronError(Exception):
    pass

def expand_field(text, lo, hi, weekday):
    """1 欄を値の list へ。 全域なら None (= plist に key を書かない = launchd の wildcard)。
    書ける形 = '*' / 'N' / 'N-M' / '*/S' / 'N-M/S' と、 それらの ',' 区切り。"""
    values = set()
    for item in text.split(','):
        body, slash, step_text = item.partition('/')
        step = 1
        if slash:
            if not NUM.fullmatch(step_text) or int(step_text) == 0:
                raise Unreadable
            step = int(step_text)
        if body == '*':
            a, b = lo, hi
        elif '-' in body:
            a_text, _, b_text = body.partition('-')
            if not (NUM.fullmatch(a_text) and NUM.fullmatch(b_text)):
                raise Unreadable
            a, b = int(a_text), int(b_text)
        elif NUM.fullmatch(body) and not slash:
            a = b = int(body)
        else:
            raise Unreadable
        if not lo <= a <= b <= hi:
            raise Unreadable
        values.update(range(a, b + 1, step))
    if weekday and 7 in values:
        values.discard(7); values.add(0)
    full = set(range(0, 7)) if weekday else set(range(lo, hi + 1))
    return None if values == full else sorted(values)

def calendar_entries(task_id, cron):
    parts = cron.split()
    if len(parts) != 5:
        raise CronError('ERROR: routine %s: cron "%s" が 5 欄 (分 時 日 月 曜日) でない (%d 欄)'
                         % (task_id, cron, len(parts)))
    sets = {}
    for (name, key, lo, hi), text in zip(FIELDS, parts):
        try:
            sets[key] = expand_field(text, lo, hi, key == 'Weekday')
        except Unreadable:
            raise CronError('ERROR: routine %s: cron "%s" の%sの欄 "%s" を読めない '
                             '(書ける形 = * / N / N-M / */S / N-M/S と , 区切り、 範囲 %d-%d)'
                             % (task_id, cron, name, text, lo, hi))
    def product(keys):
        entries = [{}]
        for key in keys:
            if sets[key] is not None:
                entries = [dict(e, **{key: v}) for e in entries for v in sets[key]]
        return entries
    common = ['Minute', 'Hour', 'Month']
    if sets['Day'] is not None and sets['Weekday'] is not None:
        # cron は日と曜日が両方指定だと「どちらかに合えば」 走る。 launchd の 1 entry は全 key が
        # 合った時だけ走るので、 日の系統と曜日の系統を別 entry にする。
        return product(common + ['Day']) + product(common + ['Weekday'])
    return product(common + ['Day', 'Weekday'])

def entries_or_exit(task_id, cron):
    try:
        return calendar_entries(task_id, cron)
    except CronError as e:
        sys.stderr.write('%s\n' % e)
        sys.exit(2)

if sys.argv[1] == 'check':
    pairs = sys.argv[2:]
    bad = 0
    for i in range(0, len(pairs) - 1, 2):
        try:
            calendar_entries(pairs[i], pairs[i + 1])
        except CronError as e:
            sys.stderr.write('%s\n' % e)
            bad = 1
    sys.exit(2 if bad else 0)

if sys.argv[1] == 'recal':
    # loaded な routine の calendar を spec と比べ、 ずれていれば StartCalendarInterval だけを書き換える
    # (= ProgramArguments は関門の旧形を新形にするだけ = install 時の CRON_MODEL / CRON_EFFORT / CRON_CONFIG_DIR の pin を保つ)。
    # 組 = <task-id> <cron> <plist> <running 0|1>。 1 組ごとに "same|held|updated|missing <task-id>" を出す。
    import os
    args = sys.argv[2:]
    for i in range(0, len(args) - 3, 4):
        task_id, cron, path, running = args[i:i + 4]
        entries = entries_or_exit(task_id, cron)
        want = entries[0] if len(entries) == 1 else entries
        try:
            with open(path, 'rb') as f:
                d = plistlib.load(f)
        except Exception:
            print('missing', task_id)
            continue
        pa = list(d.get('ProgramArguments') or [])
        new_pa = pa[:2] + [upgrade_gate(pa[2]) if isinstance(pa[2], str) else pa[2]] + pa[3:] if len(pa) >= 3 else pa
        if d.get('StartCalendarInterval') == want and new_pa == pa:
            print('same', task_id)
        elif running == '1':
            print('held', task_id)   # 実行中の job を bootout すると殺すので、 次の呼び出しに回す
        else:
            d['StartCalendarInterval'] = want
            d['ProgramArguments'] = new_pa
            with open(path + '.tmp', 'wb') as f:
                plistlib.dump(d, f)
            os.replace(path + '.tmp', path)
            print('updated', task_id)
    sys.exit(0)

task_id, cron, label, claude_bin, kind, target, prompt, logf, out, model, workdir, gate, nopersist, rcoff, effort, config_dir, node_dir = sys.argv[2:19]
entries = entries_or_exit(task_id, cron)
sci = entries[0] if len(entries) == 1 else entries
# CLI 認証で実行。 API key/inference token を unset して必ず claude.ai OAuth を使う。
# CRON_CONFIG_DIR pin があれば別 account の認証ストアを export (= 消費 account の分離)。
pin = ('export CLAUDE_CONFIG_DIR="%s"; ' % config_dir) if config_dir else ''
# install 時に解決した node の dir を PATH 末尾に追記 (= nvm 環境で stdio MCP が張れない対策)
base_path = "$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if node_dir and node_dir not in base_path.split(":"):
    base_path += ":" + node_dir
prefix = ('unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; ' + pin +
          'export PATH="%s"; ' % base_path +
          'cd "%s" && ' % workdir)
# 任意の gate: cd の後・exec の前に挿入。 gate の 1 = defer (exit 0)、 その他の非 0 = 失敗 (= 同じ終了値で終わる。 gate_block)
gate_prefix = gate_block(gate) if gate else ''
if kind == 'skill':
    model_flag = ('--model %s ' % model) if model else ''
    model_flag += ('--effort %s ' % effort) if effort else ''
    nopersist_flag = (nopersist + ' ') if nopersist else ''
    rcoff_flag = '--settings \'{"remoteControlAtStartup":false}\' ' if rcoff else ''
    cmd = prefix + gate_prefix + 'exec "%s" -p %s%s--permission-mode bypassPermissions %s"%s"' % (claude_bin, nopersist_flag, rcoff_flag, model_flag, prompt)
else:  # cmd = 決定的 script を直接実行 (claude 不要)
    cmd = prefix + gate_prefix + 'exec bash "%s"' % target
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
}

write_plist() {
  task_id="$1"; kind="$2"; target="$3"; cron="$4"
  label="$(label_for "$task_id")"; plist="$(plist_path "$task_id")"; logf="$(log_for "$task_id")"
  if [ "$kind" = skill ]; then prompt="$(prompt_for "$target")"; else prompt=""; fi
  plist_py write "$task_id" "$cron" "$label" "$CLAUDE_BIN" "$kind" "$target" "$prompt" "$logf" "$plist" "$CRON_MODEL" "$WORKDIR" "$GATE_SNIPPET" "$NOPERSIST_FLAG" "$RCOFF" "$CRON_EFFORT" "$CRON_CONFIG_DIR" "$NODE_BIN_DIR" \
    || { echo "  ERROR plist を書けず: $task_id (登録しない)" >&2; return 1; }
  record_cron "$task_id" "$cron"
  echo "  plist: $plist  ($kind, cron: $cron)"
}

# --ensure の照合済み印 = 「この cron をこの変換の版で plist に書いた」。 印が spec と一致する loaded routine は
# plist を読まずに skip する (= 定常状態で python を起動しない)。 印は cache にすぎず、 正本は plist
# (= 消えても次の --ensure が plist と照合して書き直す)。 cron→calendar 変換の意味を変えたら CAL_VERSION を
# 上げる = 全 loaded routine を 1 回照合し直させる。
record_cron() {
  mkdir -p "$STATE_DIR" 2>/dev/null
  printf '%s %s\n' "$CAL_VERSION" "$2" > "$STATE_DIR/${LABEL_PREFIX}.$1.cron" 2>/dev/null
  return 0
}

# plist を書く action は書き始める前に cron を読む (= 読めない書き方で「ensure install」 だけ出て
# 未登録のまま残る・途中の routine まで install して止まる、 を防ぐ)。 $1 = 空白区切りの task-id
# (空 = 全 routine)。 読めない routine ごとに 1 行を stderr に出し、 1 つでもあれば非 0。
check_crons() {
  only="${1:-}"
  printf '%s\n' "$ROUTINES_ACC" | {
    set --
    while IFS='|' read -r task_id kind target cron; do
      [ -n "$task_id" ] || continue
      if [ -n "$only" ]; then
        case " $only " in *" $task_id "*) ;; *) continue ;; esac
      fi
      set -- "$@" "$task_id" "$cron"
    done
    [ $# -eq 0 ] || plist_py check "$@"
  }
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
  # routine が実際に消費する account (= CRON_CONFIG_DIR pin 時はその dir の .claude.json、
  # 既定は ~/.claude.json。 config JSON の場所は default と pinned dir で違う点に注意)。
  if [ -n "$CRON_CONFIG_DIR" ]; then
    python3 -c 'import json;print(json.load(open("'"$CRON_CONFIG_DIR"'/.claude.json")).get("oauthAccount",{}).get("emailAddress","?"))' 2>/dev/null
  else
    python3 -c 'import json;print(json.load(open("'"$HOME"'/.claude.json")).get("oauthAccount",{}).get("emailAddress","?"))' 2>/dev/null
  fi
}

cmd_install() {
  check_crons || exit 2
  echo "== launchd cron 無人ルーチン install (host: $(hostname -s)) =="
  echo "   CLI bin: $CLAUDE_BIN"
  echo "   CLI account: $(cli_account)${CRON_CONFIG_DIR:+  (config-dir pin: $CRON_CONFIG_DIR)}"
  [ -x "$CLAUDE_BIN" ] || { echo "ERROR: claude が見つからない: $CLAUDE_BIN"; exit 1; }
  mkdir -p "$LA_DIR" "$LOG_DIR"
  printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r task_id kind target cron; do
    [ -n "$task_id" ] || continue
    if [ ! -f "$target" ]; then
      echo "  WARN skip $task_id: target 不在 ($target) — 該当 repo を git pull したか確認"
      continue
    fi
    echo "- $task_id"
    write_plist "$task_id" "$kind" "$target" "$cron" && bootstrap_one "$task_id"
  done
  echo
  echo "✅ install 完了。 動作確認は呼び出し元の --run <task-id>、 状態は --status。"
  echo "ℹ️  これらは CLI 認証 (= 上記 account) で走る。 Claude account 切替に非依存。"
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
  # plist と同じ環境で走らせる (= config-dir pin も再現。 導入時の headless 401 probe はこの経路)
  [ -n "$CRON_CONFIG_DIR" ] && export CLAUDE_CONFIG_DIR="$CRON_CONFIG_DIR" && echo "   (config-dir pin: $CRON_CONFIG_DIR, account: $(cli_account))"
  if [ "$kind" = skill ]; then
    mflag=""; [ -n "$CRON_MODEL" ] && mflag="--model $CRON_MODEL"
    [ -n "$CRON_EFFORT" ] && mflag="$mflag --effort $CRON_EFFORT"
    RCOFF_ARGS=""; [ -n "$RCOFF" ] && RCOFF_ARGS='--settings {"remoteControlAtStartup":false}'
    eval "cd \"$WORKDIR\"" && exec "$CLAUDE_BIN" -p $NOPERSIST_FLAG $RCOFF_ARGS --permission-mode bypassPermissions $mflag "$(prompt_for "$target")"
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
  check_crons "$task_id" || exit 2
  [ -f "$target" ] || { echo "ERROR: target 不在 ($target) — 該当 repo を git pull したか確認"; exit 1; }
  mkdir -p "$LA_DIR" "$LOG_DIR"
  echo "== 単体 install: $task_id (host: $(hostname -s)) =="
  echo "   CLI account: $(cli_account)"
  write_plist "$task_id" "$kind" "$target" "$cron" || exit 1
  bootstrap_one "$task_id"
  echo "✅ $task_id を install。 動作確認は呼び出し元の --run ${task_id}。"
}

cmd_uninstall_one() {  # 単体 uninstall (= 期間限定ジョブの停止等。 routine spec 不要)
  [ -n "$ACTION_ARG" ] || { echo "usage: --uninstall-one <task-id>"; exit 1; }
  label="$(label_for "$ACTION_ARG")"; plist="$(plist_path "$ACTION_ARG")"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null
  rm -f "$plist" "$STATE_DIR/$label.cron"
  echo "✅ removed: $label"
}

cmd_uninstall() {
  printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r task_id kind target cron; do
    [ -n "$task_id" ] || continue
    label="$(label_for "$task_id")"; plist="$(plist_path "$task_id")"
    launchctl bootout "$DOMAIN/$label" 2>/dev/null
    rm -f "$plist" "$STATE_DIR/$label.cron"
    echo "  removed: $label"
  done
  echo "✅ uninstall 完了"
}

cmd_ensure() {  # 未 install の routine を install + loaded でも calendar が spec とずれていれば直す (= SessionStart 等から冪等に呼ぶ自己修復。 quiet + fail-open)
  # target 未取得 (git pull 待ち) は無音 skip / skill で claude 不在も skip。
  # → 新 routine を ROUTINES に足して git pull した後、 次 session でそのマシンに自動 install される。
  # → 既存 routine の cron を書き換えて (または engine の変換が変わって) git pull した後も、 次 session で
  #    そのマシンの plist の StartCalendarInterval だけが書き換わって再 load される (= ProgramArguments は
  #    関門の旧形 `GATE || exit 0` を新形にするだけなので install 時の CRON_MODEL 等の pin は残る)。 job が実行中なら殺さないよう次回に回す。
  #    照合済み印 (record_cron) が spec と一致する loaded routine は plist を読まない (= 定常状態で python 0 回)。
  # ⚠️ fail-open の例外 = install / 照合する routine の読めない cron (= 呼び出し側の spec の誤り)。 1 本でも
  #    あれば 1 行ずつ stderr に出して、 何も変えず exit 2 (= 「ensure install」 だけ出て未登録、 を起こさない)。
  todo="$(printf '%s\n' "$ROUTINES_ACC" | while IFS='|' read -r task_id kind target cron; do
    [ -n "$task_id" ] || continue
    [ -f "$target" ] || continue                                    # target 未取得 = 静かに skip
    { [ "$kind" = skill ] && [ ! -x "$CLAUDE_BIN" ]; } && continue  # skill は claude 必須
    if info="$(launchctl print "$DOMAIN/${LABEL_PREFIX}.$task_id" 2>/dev/null)"; then
      stamp=""; f="$STATE_DIR/${LABEL_PREFIX}.$task_id.cron"
      [ -f "$f" ] && IFS= read -r stamp < "$f"
      [ "$stamp" = "$CAL_VERSION $cron" ] && continue               # 照合済み = 冪等 skip
      # ⚠️ $(...) の中の case は bash 3.2 (macOS /bin/sh) がパターンの ")" で構文を誤るので "(" を前置
      case "$info" in
        (*"state = running"*) printf 'V1 %s\n' "$task_id" ;;
        (*)                   printf 'V0 %s\n' "$task_id" ;;
      esac
    else
      printf 'I %s\n' "$task_id"
    fi
  done)"
  [ -n "$todo" ] || return 0
  ids="$(printf '%s\n' "$todo" | while read -r _ task_id; do printf '%s ' "$task_id"; done)"
  check_crons "$ids" || exit 2
  mkdir -p "$LA_DIR" "$LOG_DIR" 2>/dev/null

  # loaded な routine: calendar を照合し、 ずれていれば calendar だけ書き換えて再 load
  printf '%s\n' "$todo" | {
    set --
    while read -r tag task_id; do
      case "$tag" in V*) ;; *) continue ;; esac
      IFS='|' read -r _ _ _ cron <<EOF
$(find_routine "$task_id")
EOF
      set -- "$@" "$task_id" "$cron" "$(plist_path "$task_id")" "${tag#V}"
    done
    [ $# -eq 0 ] || plist_py recal "$@"
  } | while read -r result task_id; do
    IFS='|' read -r _ kind target cron <<EOF
$(find_routine "$task_id")
EOF
    case "$result" in
      same)    record_cron "$task_id" "$cron" ;;
      held)    echo "  ~ ensure update 保留: $task_id (実行中。 次の --ensure で直す)" ;;
      updated) echo "  ~ ensure update: $task_id (cron: $cron)"
               bootstrap_one "$task_id"; record_cron "$task_id" "$cron" ;;
      missing) echo "  + ensure install: $task_id (loaded だが plist が無い)"
               write_plist "$task_id" "$kind" "$target" "$cron" && bootstrap_one "$task_id" ;;
    esac
  done

  # 未 install の routine
  for task_id in $(printf '%s\n' "$todo" | while read -r tag task_id; do [ "$tag" = I ] && printf '%s ' "$task_id"; done); do
    IFS='|' read -r task_id kind target cron <<EOF
$(find_routine "$task_id")
EOF
    echo "  + ensure install: $task_id"
    write_plist "$task_id" "$kind" "$target" "$cron" && bootstrap_one "$task_id"
  done
  return 0
}

case "$ACTION" in
  status)         cmd_status ;;
  run)            cmd_run ;;
  install_one)    cmd_install_one ;;
  uninstall_one)  cmd_uninstall_one ;;
  uninstall)      cmd_uninstall ;;
  ensure)         cmd_ensure ;;
  install)        cmd_install ;;
esac
