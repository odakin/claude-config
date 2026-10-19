#!/usr/bin/env bash
# decision-question-jargon-nudge.sh — Stop + PreToolUse(AskUserQuestion / turn 終わりの箱 wrap_up): 本人への問いに作業側の語 (掲示板の動詞・台帳の符号・event id・内輪の略語) が入っていたら 1 回だけ注意する (Stop は 1 回の block で問いの部分の短い追記を求め、 tool 側は既定で additionalContext。 engine = scripts/decision-question-jargon.py、 語 = hooks/decision-question-jargon-terms.txt + ~/.claude/decision-question-jargon-ext.txt。 conventions/concise-output.md#decision-questions)
#
# 正本: claude-config/hooks/decision-question-jargon-nudge.sh (setup.sh が ~/.claude/hooks/ に symlink。 hooks/settings-entries.json で
#       Stop と PreToolUse[AskUserQuestion|mcp__.*__wrap_up] に登録 = 配線は利用者の裁定で)
#
# 何を塞ぐか: 本人に判断を求める文を、 作業側の語 (掲示板の動詞 handover / accept、 検品の符号 W-3、 台帳の番号 C1・O6、 内輪の略語)
#   で書き、 本人から「何を言っているか分からない」 と返される事故 (規約があっても散文では直らなかった = 実測)。
#   判定・語の一覧・除外・出力の形・校正の手順 = engine の docstring。
#
# 故障: engine 不在・python 不在・入力不正・部品の import 失敗・語の一覧が無い = 沈黙 (exit 0)。 止めるのは Stop の 1 回だけ
#   (stop_hook_active なら沈黙)。 tool 側を deny にするなら env DECISION_QUESTION_JARGON_TOOL_MODE=deny。
# 環境変数: DECISION_QUESTION_JARGON_DISABLE=1 / DECISION_QUESTION_JARGON_ENGINE (test 用に engine を差し替え) /
#   DECISION_QUESTION_JARGON_TERMS / DECISION_QUESTION_JARGON_EXT / DECISION_QUESTION_JARGON_TOOL_MODE
set -u
[ "${DECISION_QUESTION_JARGON_DISABLE:-}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
if [ -n "${DECISION_QUESTION_JARGON_ENGINE:-}" ]; then
  ENGINE="$DECISION_QUESTION_JARGON_ENGINE"
else
  HERE="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}" 2>/dev/null)"
  ENGINE="$HERE/../scripts/decision-question-jargon.py"
fi
[ -f "$ENGINE" ] || exit 0
python3 "$ENGINE" auto 2>/dev/null
exit 0
