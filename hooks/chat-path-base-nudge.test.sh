#!/usr/bin/env bash
# chat-path-base-nudge.test.sh — logic selftest
#
# §A fire: cwd が基準フォルダから離れた最初の Bash の後に 1 回 / 別の cwd ならもう 1 回 / 基準の外の cwd / VS Code。
#     A5-A10 = 文の 2 つ: 実体が中 = 絶対 path の文 (相対 path は「版によっては」) / 実体が外 (symlink の repo・
#     その実体の path・settings にだけ在る追加フォルダ) = 「ここの file は絶対 path でも開かない」 / app で足したフォルダ = 中。
# §B silent: 同じ cwd の 2 回目 / cwd = 基準フォルダ / CLI / entrypoint 無し / 基準に戻ってから同じ cwd へ再び。
# §C fail-open と配線: 空入力 / transcript 不在 / session id が不正 / 部品の不在 / 状態 dir を作れない / symlink 経由。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/chat-path-base-nudge.sh"
REPO="$(cd "$HERE/.." && pwd)"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

pass=0; fail=0; results=()
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# 手元の環境から切り離す: 部品は settings の追加フォルダを HOME (か CLAUDE_CONFIG_DIR) の下の settings から読む
mkdir -p "$TMP/home/.claude" && export HOME="$TMP/home"
unset CLAUDE_CONFIG_DIR
ROOT="$TMP/root"; mkdir -p "$ROOT/book" "$ROOT/tools" "$TMP/elsewhere" "$TMP/sync/repo" "$TMP/added/sub" "$TMP/setonly/sub"
ln -s "$TMP/sync/repo" "$ROOT/fs"   # repo の場所が同期フォルダへの symlink (実例の形)
printf '{"permissions":{"additionalDirectories":["%s"]}}\n' "$TMP/setonly" > "$TMP/home/.claude/settings.json"

T="$TMP/t.jsonl"
{
  jq -nc '{type:"queue-operation"}'
  jq -nc --arg r "$ROOT" '{type:"attachment", cwd:$r, attachment:{type:"environment", snapshot:{workingDirectory:$r, additionalWorkingDirectories:[]}}}'
  jq -nc --arg r "$ROOT" '{type:"user", cwd:$r, entrypoint:"claude-desktop", message:{content:"x"}}'
} > "$T"
T2="$TMP/t2.jsonl"   # app で足したフォルダ ($TMP/added) と settings にだけ在るフォルダ ($TMP/setonly) を snapshot に持つ session
{
  jq -nc --arg r "$ROOT" --arg a "$TMP/added" --arg s "$TMP/setonly" '{type:"attachment", cwd:$r, attachment:{type:"environment", snapshot:{workingDirectory:$r, additionalWorkingDirectories:[$s, $a]}}}'
  jq -nc --arg r "$ROOT" '{type:"user", cwd:$r, entrypoint:"claude-desktop", message:{content:"x"}}'
} > "$T2"

payload() { jq -n --arg c "$1" --arg s "${2:-sess-1}" --arg t "${3:-$T}" '{hook_event_name:"PostToolUse", tool_name:"Bash", cwd:$c, session_id:$s, transcript_path:$t}'; }

# run expect(1/0) label payload [needle] [entrypoint] [state_dir] [config_root]
run() {
  local expect="$1" label="$2" input="$3" needle="${4:-}" ep="${5-claude-desktop}" sd="${6:-$TMP/state}" cr="${7:-$REPO}"
  local out actual=0
  out="$(printf '%s' "$input" | CLAUDE_CODE_ENTRYPOINT="$ep" CLAUDE_CHAT_PATH_BASE_STATE_DIR="$sd" CLAUDE_CONFIG_ROOT="$cr" "$HOOK" 2>&1)" || true
  grep -qF 'additionalContext' <<< "$out" && grep -qF 'chat-path-base' <<< "$out" && actual=1
  if [ "$actual" = "$expect" ] && { [ -z "$needle" ] || grep -qF -- "$needle" <<< "$out"; }; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual needle=$needle out=${out:0:200})")
  fi
}

echo "=== §A fire ==="
run 1 "A1: 基準フォルダから離れた最初の Bash の後 = fire + 基準フォルダと例" "$(payload "$ROOT/book")" "book/<file>"
run 1 "A2: 別の cwd へ移った = もう 1 回" "$(payload "$ROOT/tools")" "$ROOT"
run 1 "A3: 基準フォルダの外の cwd = fire (ここの file は絶対 path でも開かない)" "$(payload "$TMP/elsewhere")" "絶対 path で書いても"
run 1 "A4: VS Code の panel も対象" "$(payload "$ROOT/book" sess-vs)" "" "claude-vscode"
run 1 "A5: 中の cwd の文は「版によっては」 (cd した先も探す版がある)" "$(payload "$ROOT/book" sess-a5)" "探す版もあるが頼らない"
run 1 "A6: 中に見えるが実体は同期フォルダ (symlink の repo) = 開かない文" "$(payload "$ROOT/fs" sess-a6)" "実体 (symlink を解いた先)"
run 1 "A11: 開かない文は、 足すフォルダ (symlink の repo の実体) を名指す" "$(payload "$ROOT/fs" sess-a11)" "$(cd "$TMP/sync/repo" && pwd -P) をこの session に 1 回足す"
run 1 "A7: その実体の path そのもの (会話記録の cwd の形) = 開かない文" "$(payload "$TMP/sync/repo" sess-a7)" "右パネルでは開きません"
run 1 "A8: settings にだけ在る追加フォルダ = 開かない文" "$(payload "$TMP/setonly/sub" sess-a8 "$T2")" "右パネルでは開きません"
run 1 "A9: app で足したフォルダ = 絶対 path の文 (開かない文でない)" "$(payload "$TMP/added/sub" sess-a9 "$T2")" "href は絶対 path で書く"
out="$(payload "$TMP/added/sub" sess-a9b "$T2" | CLAUDE_CODE_ENTRYPOINT=claude-desktop CLAUDE_CHAT_PATH_BASE_STATE_DIR="$TMP/state" CLAUDE_CONFIG_ROOT="$REPO" "$HOOK" 2>&1)" || true
grep -qF '開きません' <<< "$out" && { fail=$((fail+1)); results+=("❌ A10: app で足したフォルダに開かない文が出た (${out:0:160})"); } \
  || { pass=$((pass+1)); results+=("✅ A10: app で足したフォルダに開かない文を出さない"); }

echo "=== §B silent ==="
run 0 "B1: 同じ cwd の 2 回目 = silent" "$(payload "$ROOT/book")"
run 0 "B2: cwd = 基準フォルダ = silent" "$(payload "$ROOT")"
run 0 "B3: 末尾の / は同じフォルダ = silent" "$(payload "$ROOT/")"
run 0 "B4: 基準に戻ってから同じ cwd へ再び = silent" "$(payload "$ROOT/book")"
run 0 "B5: CLI の session = silent" "$(payload "$ROOT/book" sess-cli)" "" "cli"
run 0 "B6: entrypoint が無い = silent" "$(payload "$ROOT/book" sess-none)" "" ""

echo "=== §C fail-open と配線 ==="
run 0 "C1: 空入力 = silent" ""
run 0 "C2: transcript 不在 = silent" "$(payload "$ROOT/book" sess-c2 "$TMP/no-such.jsonl")"
run 0 "C3: session id に / を含む = silent (状態 file 名に使わない)" "$(payload "$ROOT/book" "../evil")"
run 0 "C4: 部品が無い = silent" "$(payload "$ROOT/book" sess-c4)" "" "claude-desktop" "$TMP/state" "$TMP/no-such-repo"
: > "$TMP/not-a-dir"
run 0 "C5: 状態 dir を作れない = silent" "$(payload "$ROOT/book" sess-c5)" "" "claude-desktop" "$TMP/not-a-dir/state"
[ ! -e "$TMP/state/../evil" ] && [ ! -e "$TMP/evil" ] && { pass=$((pass+1)); results+=("✅ C6: 不正な session id で file を作っていない"); } \
  || { fail=$((fail+1)); results+=("❌ C6: 状態 dir の外に file ができた"); }

mkdir -p "$TMP/dot-claude-hooks"; ln -s "$HOOK" "$TMP/dot-claude-hooks/chat-path-base-nudge.sh"
out="$(payload "$ROOT/book" sess-link | env -u CLAUDE_CONFIG_ROOT CLAUDE_CODE_ENTRYPOINT=claude-desktop CLAUDE_CHAT_PATH_BASE_STATE_DIR="$TMP/state" "$TMP/dot-claude-hooks/chat-path-base-nudge.sh" 2>&1)" || true
grep -qF 'additionalContext' <<< "$out" && { pass=$((pass+1)); results+=("✅ C7: symlink 経由で部品を見つけて fire"); } \
  || { fail=$((fail+1)); results+=("❌ C7: symlink 経由で fire しない (${out:0:120})"); }
printf '%s' "$out" | jq -e '.hookSpecificOutput.hookEventName == "PostToolUse"' >/dev/null 2>&1 && { pass=$((pass+1)); results+=("✅ C8: 出力は PostToolUse の JSON"); } \
  || { fail=$((fail+1)); results+=("❌ C8: 出力の JSON が不正 (${out:0:120})"); }

echo
for r in "${results[@]}"; do echo "$r"; done
echo
echo "pass=$pass fail=$fail"
[ "$fail" = 0 ] || exit 1
echo "ALL PASS"
