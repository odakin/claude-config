#!/bin/bash
# standing-cc-guard.sh — 定型の Cc (ある種類のメールに毎回入れる宛先) の送信前検査 (PreToolUse)
# hook-wiring: engine — 呼び手 = 利用者の層の shim (config を渡して本 file を exec する、 下の段落)
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
#   excluded_cc:        trigger が当たったメールで Cc に入れない宛先 (届くが、 その種類のメールの担当外になった人など)。
#                       exclusion_keywords の有無に依らず、 入っていたら止める (別の話題のメールには口を出さない)
#   excluded_note:      (1 行) excluded_cc の理由。 止めた理由の文に出す
#   label:              (1 行) 「どういうメールの規律か」 の説明。 止めた理由の文に出す
#   reason_doc:         (1 行) 規律の正本の在り処。 止めた理由の文に出す
#   bash_send_cli:      (1 行) Bash で打つ送信 CLI の file 名 (例: mailer.py)。 書けば Bash tool の command も検査する
#                       (無ければ Bash は素通し)。 command 中のこの CLI の呼び出しを 1 通ずつ send_email の入力の形
#                       {tool_name, tool_input: {subject, body, cc, attachments}} に直し、 下の検査を同じく通す
#   bash_send_flag:     (1 行) 実際に送る印の option (既定 --send)。 無い呼び出し (= dry-run) は見ない
#   bash_tool_name:     (1 行) 直した入力の tool 名。 {account} は --account の値 (既定 mcp__gmail-{account}__send_email)。
#                       tools の一覧に当てるので、 MCP の送信 tool と同じ名前にしておけば同じ一覧で両方が対象になる
#   bash_value_flags:   値を取る option を足す (既定 = --account --to --cc --bcc --subject --body --body-file --attach
#                       --reply-to-message --quote-chain --ack-newer --thread-id --in-reply-to --references --from-name)
#
# Bash の CLI で読むもの: --cc と --bcc (カンマ区切り) → cc / --subject → subject / --body-file の中身と --body → body /
#   --attach → attachments / --account → tool 名。 ⚠️ 返信で件名を省くと件名 (Re: …) は見えない = trigger は本文と
#   添付の path で当てる。 引用の付け足し (CLI が後から足す元メールの本文) も見えない。 1 行に呼び出しが複数あれば 1 つずつ見る。
#
# 動作: 足りない必須 Cc / 入っている休止の宛先 / 入っている除外の宛先があれば permissionDecision: ask (= user が認めれば通る)。
#   deny にしないのは、 個別のメールで Cc を意図して変える正当な場合があるため。 それ以外は silent pass。
# 依存: jq (Bash の CLI を読むときは python3 も)。 test = standing-cc-guard.test.sh

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

# 送信 CLI の command → send_email の入力 (1 行 1 JSON)。 ⚠️ heredoc を <( … ) や $( … ) の中に書かない =
# macOS 標準の bash 3.2 は中の括弧・{ } で構文を誤る (実測: if の塊ごと飛ばされた) ので、 先に変数へ読む
read -r -d '' PY_CONVERT <<'PY' || true
import json, os, shlex
env = os.environ
try:
    cmd = json.loads(env["STANDING_CC_INPUT"]).get("tool_input", {}).get("command", "") or ""
except Exception:
    raise SystemExit(0)
cli = env["STANDING_CC_CLI"]
if cli not in cmd:
    raise SystemExit(0)
try:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="|&;")
    lex.whitespace_split = True
    toks = list(lex)
except ValueError:
    toks = cmd.split()
STOP = {"&&", "||", ";", "|", "&", ";;"}
TAKES = {"--account", "--to", "--cc", "--bcc", "--subject", "--body", "--body-file", "--attach", "--reply-to-message",
         "--quote-chain", "--ack-newer", "--thread-id", "--in-reply-to", "--references", "--from-name"}
TAKES |= {f.strip() for f in env.get("STANDING_CC_VALUE_FLAGS", "").splitlines() if f.strip()}
send_flag = env["STANDING_CC_SEND_FLAG"]
def read(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""
def addrs(v):
    return [a.strip() for a in v.split(",") if a.strip()]
for i, t in enumerate(toks):
    if os.path.basename(t) != cli:
        continue
    args = []
    for x in toks[i + 1:]:
        if x in STOP:
            break
        args.append(x)
    acct, subject, body, send, cc, attach = "", "", "", False, [], []
    j = 0
    while j < len(args):
        a, val = args[j], None
        if a.startswith("--") and "=" in a:
            a, val = a.split("=", 1)
        if a in TAKES and val is None:
            j += 1
            val = args[j] if j < len(args) else ""
        if a == send_flag:
            send = True
        elif a == "--account":
            acct = val
        elif a in ("--cc", "--bcc"):
            cc += addrs(val)
        elif a == "--subject":
            subject = val
        elif a == "--body-file":
            body += read(val)
        elif a == "--body":
            body += val
        elif a == "--attach":
            attach.append(val)
        j += 1
    if send:
        name = env["STANDING_CC_TOOL_NAME"].replace("{account}", acct or "unknown")
        print(json.dumps({"tool_name": name, "tool_input": {"subject": subject, "body": body, "cc": cc,
                                                             "attachments": attach}}, ensure_ascii=False))
PY

# Bash: config の送信 CLI の実送信を 1 通ずつ send_email の入力の形 (1 行 1 JSON) に直し、 本 file に通し直す
if [[ "$TOOL" == "Bash" ]]; then
    CLI=$(parse_yaml_scalar "bash_send_cli" "$CONFIG")
    [[ -n "$CLI" ]] || exit 0
    command -v python3 &> /dev/null || exit 0
    SENDFLAG=$(parse_yaml_scalar "bash_send_flag" "$CONFIG")
    TOOLNAME=$(parse_yaml_scalar "bash_tool_name" "$CONFIG")
    [[ -n "$TOOLNAME" ]] || TOOLNAME='mcp__gmail-{account}__send_email'   # ${…:-…} に書くと { } で展開が切れる
    while IFS= read -r one; do
        [[ -z "$one" ]] && continue
        OUT=$(printf '%s' "$one" | bash "$0")
        if [[ -n "$OUT" ]]; then
            printf '%s\n' "$OUT"
            exit 0
        fi
    done < <(STANDING_CC_INPUT="$INPUT" STANDING_CC_CLI="$CLI" STANDING_CC_SEND_FLAG="${SENDFLAG:---send}" \
             STANDING_CC_TOOL_NAME="$TOOLNAME" \
             STANDING_CC_VALUE_FLAGS="$(parse_yaml_list "bash_value_flags" "$CONFIG")" python3 -c "$PY_CONVERT" 2>/dev/null)
    exit 0
fi

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

# Step 1b: 除外の宛先 (trigger が当たったメールでは exclusion_keywords に依らず入れない)
EXCLUDED_HIT=""
while IFS= read -r addr; do
    [[ -z "$addr" ]] && continue
    echo "$CC_LIST" | grep -qiF -- "$addr" && EXCLUDED_HIT="$EXCLUDED_HIT
  - $addr"
done <<< "$(parse_yaml_list "excluded_cc" "$CONFIG")"
if [[ -n "$EXCLUDED_HIT" ]]; then
    NOTE=$(parse_yaml_scalar "excluded_note" "$CONFIG")
    ask "⚠️ この種類のメールに入れない宛先が Cc に入っている (config の excluded_cc):$EXCLUDED_HIT

trigger keyword 検出: \"$TRIGGER_HIT\"
${NOTE:+理由 = ${NOTE}。 }外してから送る (前の便の Cc を写した時に起きやすい)。${DOC:+ 正本 = ${DOC}。}
意図してこのメールだけ入れるなら承認で通る。"
fi

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

$LABEL は config の required_cc 全員の Cc が要る。${DOC:+ 正本 = ${DOC}。}

意図して Cc 構成を変えるメールなら承認で通る。 そうでなければ止めて Cc を足してから送る。"
