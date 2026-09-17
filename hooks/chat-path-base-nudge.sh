#!/usr/bin/env bash
# chat-path-base-nudge.sh — PostToolUse(Bash): 作業ディレクトリが session を始めたフォルダから離れたとき、 chat の file 参照 (link の href・inline code の dir/file.ext) を右パネルが開く基準は変わらないことを、 session × 作業ディレクトリごとに 1 回だけ知らせる
#
# 何を防ぐか (正本 = conventions/claude-code-permissions.md#chat-link-resolution-base):
#   Bash で cd すると harness は「Primary working directory: <repo> (was <root>)」 と通知し、 system prompt も
#   「href は working directory からの相対」 と言う。 desktop app の右パネルの基準は session を始めたフォルダのまま
#   なので、 通知どおりに書いた path は開けない。 Stop hook chat-file-ref-enforce.sh は書いた後に全文を出し直させる
#   (事後・高い)。 本 hook は、 間違った前提が入った瞬間に反対の事実を 1 行入れる (事前・安い)。
#
# 述語:
#   fire = frontend が右パネルを持つ (env CLAUDE_CODE_ENTRYPOINT が claude-desktop / claude-desktop-3p / claude-vscode)
#        ∧ hook 入力の cwd ≠ session を始めたフォルダ (transcript の最初の environment snapshot、 先頭だけ読む)
#        ∧ この session でその cwd についてまだ知らせていない
#   cwd が変わった tool call の直後か、 その次の Bash の後に出る (harness が入力の cwd を更新する時点に依存)。
#
# 挙動: 非 block (-nudge)。 stdout JSON の additionalContext だけ。 状態は $TMPDIR/claude-chat-path-base/<session id>
#   (1 行目 = 基準フォルダ、 2 行目以降 = 知らせた cwd。 再起動で消えてよい)。 CLAUDE_CHAT_PATH_BASE_STATE_DIR で上書き可 (test 用)。
#   fail-open: jq / python3 / transcript / 部品の不在、 状態 dir を作れない、 session id が不正 = 沈黙。
#   部品の場所 = この hook の実体 (symlink を辿る) の ../scripts/lib。 CLAUDE_CONFIG_ROOT で上書き可 (test 用)。
#
# ⚠️ 限界: 効いたかどうかは本 hook からは見えない。 効果は Stop hook の発火率の前後比較で見る
#   (python3 scripts/lib/chat_file_refs.py calibrate <days>)。 worktree に入った session では app の基準も worktree に動くので、
#   本 hook の文面はその場合に不正確 (#chat-link-resolution-base の「本体が持つ fallback」)。
#   test = hooks/chat-path-base-nudge.test.sh

set -uo pipefail

case "${CLAUDE_CODE_ENTRYPOINT:-}" in
  claude-desktop|claude-desktop-3p|claude-vscode) ;;
  *) exit 0 ;;
esac
command -v jq >/dev/null 2>&1 || exit 0

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)"
SID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)"
TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
[ -n "$CWD" ] && [ -n "$SID" ] || exit 0
case "$SID" in *[!A-Za-z0-9_-]*) exit 0 ;; esac
CWD="${CWD%/}"

STATE_DIR="${CLAUDE_CHAT_PATH_BASE_STATE_DIR:-${TMPDIR:-/tmp}/claude-chat-path-base}"
STATE="$STATE_DIR/$SID"

ROOT=""
if [ -f "$STATE" ]; then
  ROOT="$(head -n 1 "$STATE" 2>/dev/null || true)"
  # 知らせ済みの cwd なら何もしない (2 行目以降と完全一致)
  tail -n +2 "$STATE" 2>/dev/null | grep -qxF -- "$CWD" && exit 0
fi

if [ -z "$ROOT" ]; then
  command -v python3 >/dev/null 2>&1 || exit 0
  [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0
  if [ -n "${CLAUDE_CONFIG_ROOT:-}" ]; then
    REPO="$CLAUDE_CONFIG_ROOT"
  else
    SELF="${BASH_SOURCE[0]:-$0}"
    while [ -L "$SELF" ]; do
      LINK="$(readlink "$SELF")"
      case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$(dirname "$SELF")/$LINK" ;; esac
    done
    REPO="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd)" || exit 0
  fi
  [ -f "$REPO/scripts/lib/transcript_turns.py" ] || exit 0
  ROOT="$(python3 - "$REPO/scripts/lib" "$TRANSCRIPT" <<'PY' 2>/dev/null || true
import sys
sys.path.insert(0, sys.argv[1])
try:
    import transcript_turns as tt
    print(tt.session_root_fast(sys.argv[2]) or "")
except Exception:
    pass
PY
)"
  ROOT="${ROOT%/}"
  [ -n "$ROOT" ] || exit 0
  mkdir -p "$STATE_DIR" 2>/dev/null || exit 0
  printf '%s\n' "$ROOT" > "$STATE" 2>/dev/null || exit 0
fi

[ "$CWD" = "$ROOT" ] && exit 0
printf '%s\n' "$CWD" >> "$STATE" 2>/dev/null || exit 0

case "$CWD" in
  "$ROOT"/*) EXAMPLE="${CWD#"$ROOT"/}/<file>" ;;
  *) EXAMPLE="" ;;
esac
MSG="📍 chat-path-base: 作業ディレクトリは ${CWD} になりましたが、 chat に書く file 参照を右パネルが開く基準は、 session を始めたフォルダ ${ROOT} のままです (Bash の cd には追従しません)。 markdown link の href は絶対 path で書く。 inline code の dir/file.ext も押せるリンクになるので、 ${ROOT} からの path で書く"
[ -n "$EXAMPLE" ] && MSG="${MSG} (例: ${EXAMPLE})"
MSG="${MSG}。 作業ディレクトリからの相対 path は「見つかりませんでした」 になります。 正本 = claude-config/conventions/claude-code-permissions.md#chat-link-resolution-base"

jq -n --arg m "$MSG" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $m}}'
exit 0
