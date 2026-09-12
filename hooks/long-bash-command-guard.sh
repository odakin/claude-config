#!/usr/bin/env bash
# long-bash-command-guard.sh — 長すぎる Bash command を block — PreToolUse(Bash): 閾値超は分割 / file 経由に誘導
#
# 正本: claude-config/hooks/long-bash-command-guard.sh
# setup.sh が ~/.claude/hooks/ に symlink を作成 (Step 2)
#
# 対象: PreToolUse (Bash)
# 動作: tool_input.command の長さ (Unicode codepoint) が閾値を超えたら exit 2 で block し、
#       分割 / file 経由への書き換えを stderr で指示する (= user には dialog が出ない)。
#
# Why:
#   auto mode では Bash の自動承認を classifier が判定するが、 長大な command は
#   判定から外れて **user への確認 dialog** にフォールバックする。 しかも長大 command は
#   pattern 化できないので dialog に「常に許可」 が出ず、 同じ形を打つたびに毎回止まる
#   (= user 側から見ると「いちいち聞かれる」。 席を外していればそこで作業が止まる)。
#
#   実測 (2026-09-12、 desktop app の permission dialog log + transcript 突合): 同一 session
#   同一 cwd の Bash 56 回のうち dialog が出たのは長大 command の 2 回だけで、
#   heredoc を含む 1,917 / 2,104 / 2,111 文字は通過、 4,272 / 8,916 文字が ask。
#   ∴ 閾値は 2,100〜4,200 文字のどこか。 既定 3,000 は安全側に寄せた値。
#
#   これは「危険だから止める」 gate ではなく、 **同じ結果をより短い形で書けば dialog 自体が
#   発生しない**という書き換え誘導 (= user の待ち時間を消すのが目的)。
#
# 正しい代替 (block されたら):
#   1. 追記・置換の単位で分割する (例: 9 entry を 3 回に分ける)
#   2. 本文を scratchpad の file に書いてから、 短い command で流す:
#        (Write tool で /tmp/.../chunk.yaml を書く) → cat /tmp/.../chunk.yaml >> target.yaml
#   3. file 編集そのものが目的なら Edit / Write tool を使う (= path 単位の permission 判定に
#      なるので command 長は関係しない)
#
# 調整:
#   CLAUDE_LONG_BASH_LIMIT=<n>  閾値 (文字)。 既定 3000。 `0` で無効化。
#
# 依存: jq (なければ fail-open で exit 0)

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

LIMIT="${CLAUDE_LONG_BASH_LIMIT:-3000}"
case "$LIMIT" in
  ''|*[!0-9]*) exit 0 ;;   # 数値でなければ何もしない (fail-open)
  0) exit 0 ;;             # 明示的な無効化
esac

INPUT="$(cat)"
[ -z "$INPUT" ] && exit 0

# 早期脱出 (= 大多数の Bash 呼び出しで jq を起動しない): command は JSON 全体の部分文字列なので
# `JSON の長さ <= 閾値` なら command も必ず閾値以下。 shell の ${#} が byte を返す locale でも
# byte 数 >= codepoint 数なので、 この向きの不等式は壊れない。
[ "${#INPUT}" -le "$LIMIT" ] && exit 0

LEN="$(printf '%s' "$INPUT" | jq -r '(.tool_input.command // "") | length' 2>/dev/null || true)"
case "$LEN" in
  ''|*[!0-9]*) exit 0 ;;
esac

[ "$LEN" -le "$LIMIT" ] && exit 0

cat >&2 <<EOF
[long-bash-command-guard] この Bash command は ${LEN} 文字で、 閾値 ${LIMIT} を超えている。

そのまま実行すると auto mode の自動承認から外れ、 user に確認 dialog が出て作業が止まる
(長大 command は pattern 化できないので「常に許可」 も出ず、 毎回聞かれる)。
同じ結果をより短い形で書けば dialog 自体が発生しない。 次のどれかに書き換えること:

  1. 単位で分割する (例: 9 entry の追記 → 3 回に分ける)
  2. 本文を scratchpad の file に書いてから短い command で流す
       Write tool で <scratchpad>/chunk.yaml を作る → cat <scratchpad>/chunk.yaml >> <target>
  3. file 編集が目的なら Edit / Write tool を使う (= command 長は判定に関係しない)

閾値の変更 / 無効化: CLAUDE_LONG_BASH_LIMIT=<文字数> (0 で無効)
詳細: claude-config/conventions/claude-code-permissions.md#long-command-falls-back-to-ask
EOF
exit 2
