#!/bin/bash
# standing-cc-guard.sh — 定型の Cc (ある種類のメールに毎回入れる宛先) の送信前検査 (PreToolUse)
#
# 一般則の正本 = conventions/gmail-sending.md#standing-cc-inactive (+ 定型 Cc の一覧を持つ運用全般)。
# 本 file は engine。 どの話題のメールに・誰を Cc に入れるかは呼び出し側の config (YAML) が持つ:
#   STANDING_CC_CONFIG=<config.yaml> で渡す (未設定・file 不在 = 何もしない = fail-open)。
#   呼び出し側 (個人層) は config を渡して本 file を exec する shim を hooks に置く。
#
# config (YAML、 各 list は「  - 値」 の行):
#   tools:              対象の tool 名 (無ければ tool 名が send_email で終わるもの全部)
#   trigger_keywords:   件名・本文・添付の path のどれかに含まれたら検査を起動する語
#   exclusion_keywords: trigger があってもこれを含めば検査しない語 (同じ語を使うが Cc の要らない種類のメール)
#   required_cc:        trigger が当たったメールで Cc に必ず入れる宛先
#   inactive_cc:        休業・異動で届かない宛先。 Cc に入っていたら trigger の有無に依らず止める
#   label:              (1 行) 「どういうメールの規律か」 の説明。 止めた理由の文に出す
#   reason_doc:         (1 行) 規律の正本の在り処。 止めた理由の文に出す
#
# 動作: 足りない必須 Cc / 入っている休止の宛先があれば permissionDecision: ask (= user が認めれば通る)。
#   deny にしないのは、 個別のメールで Cc を意図して変える正当な場合があるため。 それ以外は silent pass。
# 依存: jq。 test = standing-cc-guard.test.sh

INPUT=$(cat)
command -v jq &> /dev/null || exit 0

CONFIG="${STANDING_CC_CONFIG:-}"
[[ -n "$CONFIG" && -f "$CONFIG" ]] || exit 0

parse_yaml_list() {
    local key="$1" file="$2"
    awk -v key="$key" '
        $0 ~ "^"key":" { in_list=1; next }
        in_list && /^[a-zA-Z]/ { in_list=0 }
        in_list && /^  - / {
            sub(/^  - /, "")
            sub(/^"/, ""); sub(/"$/, "")
            sub(/^'"'"'/, ""); sub(/'"'"'$/, "")
            sub(/[ \t]*#.*/, "")
            sub(/[ \t]+$/, "")
            if (length($0) > 0) print
        }
    ' "$file"
}

parse_yaml_scalar() {
    local key="$1" file="$2"
    awk -v key="$key" '
        $0 ~ "^"key":[ \t]" {
            sub("^"key":[ \t]*", "")
            sub(/^"/, ""); sub(/"[ \t]*(#.*)?$/, "")
            print; exit
        }
    ' "$file"
}

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
TOOLS=$(parse_yaml_list "tools" "$CONFIG")
if [[ -n "$TOOLS" ]]; then
    echo "$TOOLS" | grep -qxF -- "$TOOL" || exit 0
else
    [[ "$TOOL" == *send_email ]] || exit 0
fi

SUBJECT=$(echo "$INPUT" | jq -r '.tool_input.subject // empty')
BODY=$(echo "$INPUT" | jq -r '.tool_input.body // empty')
ATTACHMENTS=$(echo "$INPUT" | jq -r '.tool_input.attachments // [] | join("\n")')
CC_LIST=$(echo "$INPUT" | jq -r '.tool_input.cc // [] | if type == "array" then join("\n") else . end')
SEARCH_CONTENT="$SUBJECT
$BODY
$ATTACHMENTS"

LABEL=$(parse_yaml_scalar "label" "$CONFIG")
DOC=$(parse_yaml_scalar "reason_doc" "$CONFIG")
[[ -n "$LABEL" ]] || LABEL="定型の Cc を入れる種類のメール"

ask() {
    jq -n --arg reason "$1" '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":$reason}}'
    exit 0
}

# Step 0: 休止の宛先 (trigger に依らない = 別の話題のメールに写した Cc も止める)
INACTIVE_HIT=""
while IFS= read -r addr; do
    [[ -z "$addr" ]] && continue
    echo "$CC_LIST" | grep -qF -- "$addr" && INACTIVE_HIT="$INACTIVE_HIT
  - $addr"
done <<< "$(parse_yaml_list "inactive_cc" "$CONFIG")"
if [[ -n "$INACTIVE_HIT" ]]; then
    ask "⚠️ 休業・異動で届かない宛先が Cc に入っている (config の inactive_cc):$INACTIVE_HIT

外してから送る (入れると bounce で戻る)。${DOC:+ 経緯 = $DOC}"
fi

# Step 1: trigger / exclusion
TRIGGER_HIT=""
while IFS= read -r kw; do
    [[ -z "$kw" ]] && continue
    if echo "$SEARCH_CONTENT" | grep -qF -- "$kw"; then TRIGGER_HIT="$kw"; break; fi
done <<< "$(parse_yaml_list "trigger_keywords" "$CONFIG")"
[[ -n "$TRIGGER_HIT" ]] || exit 0
while IFS= read -r kw; do
    [[ -z "$kw" ]] && continue
    echo "$SEARCH_CONTENT" | grep -qF -- "$kw" && exit 0
done <<< "$(parse_yaml_list "exclusion_keywords" "$CONFIG")"

# Step 2: 必須 Cc
MISSING=""
while IFS= read -r required; do
    [[ -z "$required" ]] && continue
    echo "$CC_LIST" | grep -qF -- "$required" || MISSING="$MISSING
  - $required"
done <<< "$(parse_yaml_list "required_cc" "$CONFIG")"
[[ -n "$MISSING" ]] || exit 0

ask "⚠️ 定型 Cc の不足候補:

trigger keyword 検出: \"$TRIGGER_HIT\"
不足 Cc:$MISSING

$LABEL は config の required_cc 全員の Cc が要る。${DOC:+ 正本 = $DOC。}

意図して Cc 構成を変えるメールなら承認で通る。 そうでなければ止めて Cc を足してから送る。"
