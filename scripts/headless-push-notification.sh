#!/usr/bin/env bash
# headless-push-notification.sh — 無人の定期実行から、 閉じた headless `claude -p` 1 回でスマホ (Claude アプリ) に push 通知を送る。 --probe で送らずに送れる状態かだけを見る (token 不要)
# ---------------------------------------------------------------------------
# 使い方:
#   headless-push-notification.sh "本文 1" ["本文 2" ...]   … 本文を 1 通の push にまとめて送る
#   headless-push-notification.sh --probe                   … CLI が見つかり、 使う config dir がログイン済みかだけ見る
#
# env:
#   CLAUDE_PUSH_CONFIG_DIR  使う Claude の config dir (既定 = 未設定なら既定の ~/.claude)。
#                           既定の config dir は account 切替で変わる / 未ログインのマシンがあるので、
#                           届けたい account に pin した dir を渡すのが安全
#   CLAUDE_PUSH_STATE_DIR   本文と log の置き場 (既定 ~/.local/state/claude-push)。 ~/ 配下の project の外であること
#   CLAUDE_PUSH_TITLE       本文の 1 行目 (既定「通知」)
#   CLAUDE_PUSH_MODEL       model (既定 sonnet)
#   CLAUDE_PUSH_DRY=1       claude を呼ばず、 送る本文だけを出す
#
# exit: 0 = PushNotification を呼べた (「Not sent (user active)」 を含む = キーボード操作中は送られない仕様) /
#       1 = CLI が無い・未ログイン・出力に PUSH_RESULT 行が無い。 呼び出し側は非 0 を「届いていない」 として残すこと。
#
# なぜこう閉じるか (正本 = conventions/public-page-watch.md#sealed-headless-push、 各項は実測):
#   - hook を止める (--settings の disableAllHooks)。 止めないと config dir の SessionStart / Stop hook が走り、
#     通知を送らずに hook の求める別の仕事を始めた
#   - MCP を外す (--strict-mcp-config に --mcp-config を渡さない)。 --tools で絞っても MCP の tool は残った
#   - project の外で起動する (= CLAUDE.md の自動読込を避ける)
#   - prompt は stdin で渡す。 `--tools <tools...>` は可変長で、 後ろに置いた prompt まで tool 名として飲み込む
#   - launchd は LANG 空なので prompt は ASCII。 多バイトの本文は file に書いて Read させる
#   - `--bare` は hook も止めるが OAuth を使えなくなるので使わない
#   - CLI は launchd の PATH に無い場所 (npm の global prefix 等) にあることがある = 候補を順に探す
# ---------------------------------------------------------------------------
set -u

find_claude() {
  for c in "$(command -v claude 2>/dev/null || true)" "$HOME/.local/bin/claude" "$HOME/.npm-global/bin/claude" \
           /opt/homebrew/bin/claude /usr/local/bin/claude; do
    [ -n "$c" ] && [ -x "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

[ -n "${CLAUDE_PUSH_CONFIG_DIR:-}" ] && [ -d "$CLAUDE_PUSH_CONFIG_DIR" ] && export CLAUDE_CONFIG_DIR="$CLAUDE_PUSH_CONFIG_DIR"
unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN

if [ "${1:-}" = "--probe" ]; then
  CB="$(find_claude)" || { echo "claude CLI が見つからない (PATH・~/.local/bin・~/.npm-global/bin・/opt/homebrew/bin・/usr/local/bin)" >&2; exit 1; }
  st="$("$CB" auth status 2>/dev/null || true)"
  printf '%s' "$st" | grep -q '"loggedIn": *true' \
    || { echo "push 用の CLI が未ログイン (${CLAUDE_CONFIG_DIR:-~/.claude}。 直し方 = CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR:-~/.claude} claude auth login)" >&2; exit 1; }
  exit 0
fi

[ "$#" -gt 0 ] || exit 0

STATE_DIR="${CLAUDE_PUSH_STATE_DIR:-$HOME/.local/state/claude-push}"
mkdir -p "$STATE_DIR" || exit 1
MSG="$STATE_DIR/push-message.txt"
{
  printf '%s\n' "${CLAUDE_PUSH_TITLE:-通知}"
  for a in "$@"; do printf '・%s\n' "$a"; done
} > "$MSG"

if [ "${CLAUDE_PUSH_DRY:-}" = "1" ]; then
  cat "$MSG"
  exit 0
fi

CLAUDE_BIN="$(find_claude)" || { echo "headless-push-notification: claude CLI が見つからない" >&2; exit 1; }
cd "$STATE_DIR" || exit 1
printf '%s' "Use the Read tool on the file $MSG. Then call the PushNotification tool exactly once, with the full text of that file as the message. Do nothing else. If the tool result says Not sent because the user is active, that is expected: do not retry. Finally print one line: PUSH_RESULT followed by the tool result." \
  | "$CLAUDE_BIN" -p --no-session-persistence \
      --settings '{"remoteControlAtStartup":false,"disableAllHooks":true}' \
      --strict-mcp-config \
      --disable-slash-commands \
      --permission-mode bypassPermissions \
      --model "${CLAUDE_PUSH_MODEL:-sonnet}" \
      --tools Read PushNotification > "$STATE_DIR/push-last.log" 2>&1
rc=$?
cat "$STATE_DIR/push-last.log"
grep -q "PUSH_RESULT" "$STATE_DIR/push-last.log" || exit 1
exit $rc
