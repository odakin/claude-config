#!/usr/bin/env bash
# chat-file-ref-enforce.sh — Stop: 最終メッセージの file 参照 (link / path に見える inline code) が desktop の右パネルで開けない形なら、 正しい path を添えて 1 回だけ書き直させる
#
# 何を塞ぐか (正本 = conventions/claude-code-permissions.md#chat-link-resolution-base):
#   desktop app は chat の相対 path を **session を始めたときに選んだフォルダ** に連結して開く。
#   Bash で cd すると harness は「Primary working directory: <repo> (was <root>)」 と通知し、
#   system prompt も「href は working directory からの相対」 と言うので、 repo の中からの path を
#   書きたくなる。 しかし右パネルの基準は変わらないので「このファイルが見つかりませんでした」 になる。
#   inline code の `dir/file.ext` も形だけでリンクとして描かれ (実在しない path も)、 同じ基準で開かれる (実測)。
#
# 述語 (= scripts/lib/chat_file_refs.py の find_broken):
#   fire = session の frontend が右パネルを持つ (transcript の entrypoint が claude-desktop / claude-desktop-3p / claude-vscode)
#        ∧ 最終発話の markdown link の href か、 `/` を含み拡張子で終わる inline code が
#          「基準フォルダに連結すると無い (か、 フォルダの外に出る)」
#        ∧ 「transcript に出た cwd か基準フォルダ直下の dir に連結すると在る」
#   除外 = URL / anchor だけの href / 絶対 path / ~/ / fenced code block の中 / どこにも無い path。
#   基準フォルダ = transcript に最初に現れた cwd。
#   校正 (実測、 desktop transcript の最終発話): 発火は約 8% の turn、 link を含むのは約 1%。
#   link の検出は目視で全件が開けない形 (repo の中からの path / ../ で始まる path / 基準外)。
#   inline code の検出が大半を占める (= 押せるのに開けない link になっている、 と読む。 リンク化の条件は下の限界を参照)。
#   再校正 = python3 scripts/lib/chat_file_refs.py calibrate <days>。
#
# 挙動: fire 時 decision=block + reason (開けない参照と正しい path の候補)。 stop_hook_active=true は即 exit 0。
#   fail-open: jq / python3 / transcript / 部品 (scripts/lib/chat_file_refs.py・transcript_turns.py) の不在や例外は沈黙。
#   部品の場所 = この hook の実体 (symlink を辿る) の ../scripts/lib。 CLAUDE_CONFIG_ROOT で上書き可 (test 用)。
#
# ⚠️ 射程の限界:
#   - Remote Control で別端末から見ている画面では、 正しい path でも開けない (#rc-chat-panel-no-render)。 hook からは見分けられない。
#   - 基準フォルダの外の file は、 絶対 path に直しても右パネルでは開けないことがある (#chat-link-rendering-scope)。
#   - どこにも実在しない path の inline code も押せる (開けない) リンクになるが、 正しい path を示せないので拾わない
#     (= 例示の path。 fenced block に入れるよう規約で扱う)。
#   test = hooks/chat-file-ref-enforce.test.sh

set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)"
[ "$ACTIVE" = "true" ] && exit 0

TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
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
LIB="$REPO/scripts/lib/chat_file_refs.py"
[ -f "$LIB" ] && [ -f "$REPO/scripts/lib/transcript_turns.py" ] || exit 0

REASON="$(python3 "$LIB" hook "$TRANSCRIPT" 2>/dev/null || true)"
[ -n "$REASON" ] || exit 0

jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
