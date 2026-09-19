#!/usr/bin/env bash
# visible-html-comment-enforce.test.sh — logic + incident-replay selftest
#
# §A incident replay: hook 向けの marker を HTML comment として最終メッセージに置いた turn (冒頭 / 末尾 / 閉じ忘れ) で fire。
# §B 誤検出の regression: comment 無し / inline code の中 / fenced block の中 (list の中の fence を含む) /
#     途中の text にだけ在る (最終発話は clean) / tool 入力 (Bash command) にだけ在る。
# §C fail-open と配線: stop_hook_active / transcript 不在 / 空入力 / 部品の不在 = 沈黙。 symlink 経由で部品を見つける。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/visible-html-comment-enforce.py"
REPO="$(cd "$HERE/.." && pwd)"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

pass=0; fail=0; results=()
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# mktranscript path final_text [mid_text] [bash_command]
mktranscript() {
  local path="$1" final="$2" mid="${3:-}" cmd="${4:-ls}"
  {
    jq -nc '{type:"user", message:{content:"図を直して"}}'
    [ -n "$mid" ] && jq -nc --arg t "$mid" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
    jq -nc --arg c "$cmd" '{type:"assistant", message:{content:[{type:"tool_use", name:"Bash", input:{command:$c}}]}}'
    jq -nc '{type:"user", message:{content:[{type:"tool_result", content:"ok"}]}}'
    jq -nc --arg t "$final" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
  } > "$path"
}

mkpayload() { jq -n --arg t "$1" --argjson a "${2:-false}" '{hook_event_name:"Stop", transcript_path:$t, stop_hook_active:$a}'; }

# assert label expect(1/0) payload [needle]
assert() {
  local label="$1" expect="$2" input="$3" needle="${4:-}"
  local out actual=0
  out="$(printf '%s' "$input" | CLAUDE_CONFIG_ROOT="${ROOT_OVERRIDE:-$REPO}" "$HOOK" 2>&1)" || true
  printf '%s' "$out" | grep -qF '"decision"' && actual=1
  if [ "$actual" = "$expect" ] && { [ -z "$needle" ] || printf '%s' "$out" | grep -qF -- "$needle"; }; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual needle=$needle out=${out:0:200})")
  fi
}

BT='`'
N=0
case_() {  # case_ label expect final [needle] [mid] [cmd]
  N=$((N+1))
  local t="$TMP/t$N.jsonl"
  mktranscript "$t" "$3" "${5:-}" "${6:-ls}"
  assert "$1" "$2" "$(mkpayload "$t")" "${4:-}"
}

echo "=== §A incident replay ==="
case_ "A1: 冒頭に marker の comment = fire + 見つけた comment を示す" 1 \
  $'<!-- skip-open -->\n直しました。' "skip-open"
case_ "A2: 末尾の comment = fire" 1 \
  $'直しました。\n\n<!-- marker -->'
case_ "A3: 閉じ忘れの comment = fire" 1 \
  $'直しました。 <!-- marker'
case_ "A4: 説明の inline code と裸の comment が同居 = fire" 1 \
  "${BT}<!-- a -->${BT} は見えます。 <!-- b -->" "<!-- b -->"

echo "=== §B 誤検出の regression ==="
case_ "B1: comment 無し = silent" 0 "直しました。 a < b で a -- b。"
case_ "B2: inline code の中 = silent" 0 "あれは ${BT}<!-- skip-open -->${BT} という目印です。"
case_ "B3: fenced block の中 = silent" 0 $'例:\n\n```\n<!-- skip-open -->\n```\n以上。'
case_ "B4: list の中の fence = silent" 0 $'- 例\n    ```html\n    <!-- x -->\n    ```\n- 次'
case_ "B5: 途中の text にだけ在る (最終発話は clean) = silent" 0 "直しました。" "" "<!-- mid -->"
case_ "B6: Bash command の comment にだけ在る = silent" 0 "直しました。" "" "" "make   # <!-- skip-open -->"

echo "=== §C fail-open と配線 ==="
mktranscript "$TMP/c.jsonl" $'<!-- m -->\n直しました。'
assert "C1: stop_hook_active = silent (1 回だけ)" 0 "$(mkpayload "$TMP/c.jsonl" true)"
assert "C2: transcript 不在 = silent" 0 "$(mkpayload "$TMP/none.jsonl")"
assert "C3: 空入力 = silent" 0 ""
ROOT_OVERRIDE="$TMP/empty-root" assert "C4: 部品の不在 = silent" 0 "$(mkpayload "$TMP/c.jsonl")"
mkdir -p "$TMP/dot-claude-hooks"
ln -s "$HOOK" "$TMP/dot-claude-hooks/visible-html-comment-enforce.py"
out="$(mkpayload "$TMP/c.jsonl" | env -u CLAUDE_CONFIG_ROOT "$TMP/dot-claude-hooks/visible-html-comment-enforce.py" 2>&1)" || true
printf '%s' "$out" | grep -qF '"decision"' && { pass=$((pass+1)); results+=("✅ C5: symlink 経由で部品を見つけて fire"); } \
  || { fail=$((fail+1)); results+=("❌ C5: symlink 経由で fire しない (${out:0:120})"); }

echo
for r in "${results[@]}"; do echo "$r"; done
echo
echo "pass=$pass fail=$fail"
[ "$fail" = 0 ] || exit 1
echo "ALL PASS"
