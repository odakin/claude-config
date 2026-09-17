#!/usr/bin/env bash
# chat-file-ref-enforce.test.sh — logic + incident-replay selftest
#
# §A incident replay: cd で repo に入った後、 repo の中からの path を link / inline code で書いた最終発話 (= 右パネルで
#     「このファイルが見つかりませんでした」) と、 repo を基準にした session が ../ で外の repo を指す形を再現して fire を確認。
# §B 誤検出の regression: 基準フォルダからの正しい path / 絶対 path / ~/ / URL / anchor / fenced block の中 /
#     どこにも無い path / 区切りの無い名前 / 追加フォルダの中へ ../ で出る path / CLI の session / 途中の text だけ。
# §C fail-open と配線: stop_hook_active / transcript 不在 / 空入力 / 部品の不在・例外 = 沈黙。 symlink 経由で部品を見つける。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/chat-file-ref-enforce.sh"
REPO="$(cd "$HERE/.." && pwd)"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }

pass=0; fail=0; results=()
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ROOT="$TMP/root"
mkdir -p "$ROOT/book/drafts" "$ROOT/book/notes" "$ROOT/tools/scripts" "$TMP/extra"
: > "$ROOT/book/drafts/intro.md"; : > "$ROOT/book/notes/design.md"; : > "$ROOT/tools/scripts/run.py"
: > "$ROOT/CLAUDE.md"; : > "$TMP/extra/memo.md"

# mktranscript path entrypoint root additional_json final_text [mid_text]
#   環境 snapshot (root) → user → assistant tool_use (cwd = root/book に cd した後) → tool_result → final
mktranscript() {
  local path="$1" ep="$2" root="$3" extra="$4" final="$5" mid="${6:-}"
  {
    jq -nc --arg r "$root" --argjson x "$extra" \
      '{type:"attachment", cwd:$r, attachment:{type:"environment", snapshot:{workingDirectory:$r, additionalWorkingDirectories:$x}}}'
    jq -nc --arg r "$root" --arg ep "$ep" '{type:"user", cwd:$r, entrypoint:$ep, message:{content:"試稿を開いて"}}'
    [ -n "$mid" ] && jq -nc --arg r "$root/book" --arg t "$mid" '{type:"assistant", cwd:$r, message:{content:[{type:"text", text:$t}]}}'
    jq -nc --arg r "$root/book" '{type:"assistant", cwd:$r, message:{content:[{type:"tool_use", name:"Bash", input:{command:"cd book && ls"}}]}}'
    jq -nc --arg r "$root/book" '{type:"user", cwd:$r, message:{content:[{type:"tool_result", content:"ok"}]}}'
    jq -nc --arg r "$root/book" --arg t "$final" '{type:"assistant", cwd:$r, message:{content:[{type:"text", text:$t}]}}'
  } > "$path"
}

mkpayload() { jq -n --arg t "$1" --argjson a "${2:-false}" '{hook_event_name:"Stop", transcript_path:$t, stop_hook_active:$a}'; }

# assert label expect(1/0) payload [needle] [env...]
assert() {
  local label="$1" expect="$2" input="$3" needle="${4:-}"
  local out actual=0
  out="$(printf '%s' "$input" | CLAUDE_CONFIG_ROOT="$REPO" "$HOOK" 2>&1)" || true
  if printf '%s' "$out" | grep -qF '"decision"' && printf '%s' "$out" | grep -qF 'chat-file-ref'; then
    actual=1
  fi
  if [ "$actual" = "$expect" ] && { [ -z "$needle" ] || printf '%s' "$out" | grep -qF -- "$needle"; }; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual needle=$needle out=${out:0:200})")
  fi
}

BT='`'
N=0
case_() {  # case_ label expect final [needle] [ep] [root] [extra_json] [mid]
  N=$((N+1))
  local t="$TMP/t$N.jsonl"
  mktranscript "$t" "${5:-claude-desktop}" "${6:-$ROOT}" "${7:-[]}" "$3" "${8:-}"
  assert "$1" "$2" "$(mkpayload "$t")" "${4:-}"
}

echo "=== §A incident replay ==="
case_ "A1: link が repo の中からの path (cd の後) = fire + 正しい path" 1 \
  "こちらです: [drafts/intro.md](drafts/intro.md)" "book/drafts/intro.md"
case_ "A2: inline code が repo の中からの path = fire" 1 \
  "試稿 ${BT}drafts/intro.md${BT} の最後の節です。" "book/drafts/intro.md"
case_ "A3: 行番号・anchor つき href も解決して fire" 1 \
  "[design](notes/design.md#opening) と [run.py:12](scripts/run.py:12)" "tools/scripts/run.py"
case_ "A4: repo を基準にした session が ../ で外へ (追加フォルダ無し) = fire (フォルダの外)" 1 \
  "[run](../tools/scripts/run.py)" "フォルダの外" "claude-desktop" "$ROOT/book"
case_ "A5: VS Code の panel も対象" 1 "[x](drafts/intro.md)" "" "claude-vscode"
case_ "A6: 第三者版 desktop も対象" 1 "[x](drafts/intro.md)" "" "claude-desktop-3p"

echo "=== §B 誤検出の regression ==="
case_ "B1: 基準フォルダからの path = silent" 0 "[intro](book/drafts/intro.md) と ${BT}tools/scripts/run.py${BT}"
case_ "B2: 絶対 path = silent" 0 "[intro]($ROOT/book/drafts/intro.md)"
case_ "B3: ~/ と URL と anchor だけ = silent" 0 "[a](~/drafts/intro.md) [b](https://example.com/drafts/intro.md) [c](#drafts)"
case_ "B4: fenced block の中 = silent" 0 "例:
${BT}${BT}${BT}
[drafts/intro.md](drafts/intro.md) ${BT}drafts/intro.md${BT}
${BT}${BT}${BT}"
case_ "B5: どこにも無い path = silent" 0 "[x](path/to/file.md) ${BT}src/foo.ts${BT}"
case_ "B6: 区切りの無い名前の inline code = silent" 0 "${BT}intro.md${BT} と ${BT}CLAUDE.md${BT}"
case_ "B7: ../ で出た先が追加フォルダの中 = silent" 0 "[run](../tools/scripts/run.py)" "" "claude-desktop" "$ROOT/book" "[\"$ROOT\"]"
case_ "B8: CLI の session = silent" 0 "[drafts/intro.md](drafts/intro.md)" "" "cli"
case_ "B9: 途中の text だけに在り最終発話は clean = silent" 0 "完了しました。" "" "claude-desktop" "$ROOT" "[]" "[drafts/intro.md](drafts/intro.md)"
case_ "B10: inline code の中の link 記法 = silent" 0 "${BT}[a](drafts/intro.md)${BT}"

echo "=== §C fail-open と配線 ==="
mktranscript "$TMP/c.jsonl" claude-desktop "$ROOT" "[]" "[drafts/intro.md](drafts/intro.md)"
assert "C1: stop_hook_active=true = silent (loop guard)" 0 "$(mkpayload "$TMP/c.jsonl" true)"
assert "C2: transcript 不在 = silent" 0 "$(mkpayload "$TMP/no-such.jsonl")"
assert "C3: 空入力 = silent" 0 ""

out="$(mkpayload "$TMP/c.jsonl" | CLAUDE_CONFIG_ROOT="$TMP/no-such-repo" "$HOOK" 2>&1)" || true
[ -z "$out" ] && { pass=$((pass+1)); results+=("✅ C4: 部品が無い = silent"); } \
  || { fail=$((fail+1)); results+=("❌ C4: 部品が無いのに出力 (${out:0:120})"); }
mkdir -p "$TMP/broken/scripts/lib"
echo 'raise RuntimeError("broken")' > "$TMP/broken/scripts/lib/chat_file_refs.py"
cp "$REPO/scripts/lib/transcript_turns.py" "$TMP/broken/scripts/lib/"
out="$(mkpayload "$TMP/c.jsonl" | CLAUDE_CONFIG_ROOT="$TMP/broken" "$HOOK" 2>&1)" || true
[ -z "$out" ] && { pass=$((pass+1)); results+=("✅ C5: 部品が例外で落ちる = silent"); } \
  || { fail=$((fail+1)); results+=("❌ C5: 部品が壊れているのに出力 (${out:0:120})"); }

# C6: ~/.claude/hooks と同じ symlink 経由 (CLAUDE_CONFIG_ROOT 無し) で部品を見つけて fire する
mkdir -p "$TMP/dot-claude-hooks"
ln -s "$HOOK" "$TMP/dot-claude-hooks/chat-file-ref-enforce.sh"
out="$(mkpayload "$TMP/c.jsonl" | env -u CLAUDE_CONFIG_ROOT "$TMP/dot-claude-hooks/chat-file-ref-enforce.sh" 2>&1)" || true
printf '%s' "$out" | grep -qF '"decision"' && { pass=$((pass+1)); results+=("✅ C6: symlink 経由で部品を見つけて fire"); } \
  || { fail=$((fail+1)); results+=("❌ C6: symlink 経由で fire しない (${out:0:120})"); }

echo
for r in "${results[@]}"; do echo "$r"; done
echo
echo "pass=$pass fail=$fail"
[ "$fail" = 0 ] || exit 1
echo "ALL PASS"
