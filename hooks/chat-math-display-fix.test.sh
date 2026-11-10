#!/usr/bin/env bash
# chat-math-display-fix.test.sh — 表示の hook (MessageDisplay) と、 chat-math-render-guard の直す部品・追記・差し戻しの後の判定・数式でない `$` の selftest
#
# §A 表示の hook: 崩れる式を描ける形へ (`$E_I$` / 60 文字超 / 読点の直後の `\(E_I\)` / `\[…\]` / 数だけ / 表の `|`)、
#     触らないもの (code block の中・金額・CLI の session)、 行のまとまりをまたぐ code block、 session の印と計器、 copy の配線、 壊れた入力。
# §B Stop の hook: 追記の文と直した形 / 数式でない `$` を報告しない / 本物の式は報告する / 差し戻しの後の判定 (自分の差し戻し
#     の後は止めずに数える・他の hook の差し戻しの後は止める) / 表示の印がある session では直った式で止めない / 校正が差し戻された版を数える。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DISP="$HERE/chat-math-display-fix.py"
GUARD="$HERE/chat-math-render-guard.py"
[ -f "$DISP" ] && [ -f "$GUARD" ] || { echo "FAIL: hook not found under $HERE"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not found"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not found"; exit 0; }

pass=0; fail=0; results=()
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export TMPDIR="$TMP/tmpdir"; mkdir -p "$TMPDIR"
export CHAT_MATH_STATE_DIR="$TMP/state"; mkdir -p "$CHAT_MATH_STATE_DIR"

ok() { pass=$((pass+1)); results+=("✅ $1"); }
ng() { fail=$((fail+1)); results+=("❌ $1 :: $(printf '%s' "$2" | head -c 300)"); }

# disp label entrypoint delta expect_substring(空 = 出力なし) [index final message_id session]
disp() {
  local label="$1" ep="$2" delta="$3" want="$4" idx="${5:-0}" fin="${6:-true}" mid="${7:-m-1}" sid="${8:-sess-a}"
  local payload out shown
  payload="$(jq -n --arg d "$delta" --argjson i "$idx" --argjson f "$fin" --arg m "$mid" --arg s "$sid" \
    '{hook_event_name:"MessageDisplay", session_id:$s, turn_id:"t", message_id:$m, index:$i, final:$f, delta:$d}')"
  out="$(printf '%s' "$payload" | CLAUDE_CODE_ENTRYPOINT="$ep" python3 "$DISP" 2>&1)"
  if [ -z "$want" ]; then
    [ -z "$out" ] && ok "$label" || ng "$label" "$out"
    return
  fi
  shown="$(printf '%s' "$out" | jq -r '.hookSpecificOutput.displayContent // empty' 2>/dev/null)"
  if grep -qF -- "$want" <<< "$shown"; then ok "$label"; else ng "$label (want=$want)" "$out"; fi
}

D=claude-desktop

# ---- §A 表示の hook ---------------------------------------------------------------------------------
disp "A1 \$E_I\$ は {} を付ける" $D '定義を残す: $E_I$ の件。' '$E_{I}$'
disp "A2 60 文字超の \$…\$ は \\(…\\) へ" $D '展開: $E_I(\boldsymbol P)=|\boldsymbol P|+m_I^2/(2|\boldsymbol P|)+\dots$ を使う。' '\(E_{I}(\boldsymbol P)=|\boldsymbol P|+m_{I}^{2}/(2|\boldsymbol P|)+\dots\)'
disp "A3 読点の直後の \\(E_I\\) は空白と {}" $D '位相、\(E_I\) です。' '位相、 \(E_{I}\) です。'
disp "A4 文中の \\[…\\] は \\(…\\) へ" $D '次の式 \[ E=mc^2 \] を見よ。' '\(E=mc^2\)'
disp "A5 \\[ と \\] だけの行は \$\$ へ" $D $'式:\n\\[\nE=mc^2\n\\]\n以上。' $'$$\nE=mc^2\n$$'
disp "A6 数だけの \$30\$ は地の文" $D '合計 $30$ 個。' '合計 30 個。'
disp "A7 表のセルの | は \\vert" $D $'| 量 | 式 |\n|---|---|\n| 内積 | $\\langle\\psi|\\phi\\rangle$ |' '\vert'
disp "A8 code block の中は触らない" $D $'例:\n```\n$E_I$ と \\(K\\)\n```\n以上。' ''
disp "A9 金額は触らない" $D 'Opus は $4/$20、 Fable は $10/$50 で、 半額以下です。' ''
disp "A10 描ける式だけの返事は何も出さない" $D '時刻 $t$ と \( x_{0}\in U \) を取る。' ''
disp "A11 CLI の session は見ない" cli '定義を残す: $E_I$ の件。' ''
out="$(jq -n '{session_id:"s", index:0, final:true, delta:"定義: $E_I$"}' | env -u CLAUDE_CODE_ENTRYPOINT CHAT_MATH_DISPLAY_FIX_ANY=1 python3 "$DISP" 2>&1)"
grep -qF 'E_{I}' <<< "$out" && ok "A12 CHAT_MATH_DISPLAY_FIX_ANY は entrypoint を問わない" || ng "A12" "$out"
# 行のまとまりをまたぐ code block (対話の端末)
disp "A13a まとまり 0 で code block が開く" $D $'前置き\n```\n' '' 0 false m-fence
disp "A13b まとまり 1 は code block の中 = 触らない" $D $'$E_I$ はそのまま\n' '' 1 false m-fence
disp "A13c まとまり 2 で閉じた後は直す" $D $'```\n後: $E_I$ の件\n' '$E_{I}$' 2 true m-fence
[ ! -e "$TMPDIR/chat-math-display-fix/msg-m-fence" ] && ok "A13d final で引き継ぎの file を消す" || ng "A13d" "残っている"
[ -e "$TMPDIR/chat-math-display-fix/sess-a" ] && ok "A14 session の印を置く" || ng "A14" "$(ls -R "$TMPDIR")"
grep -q '"kind": "display_fix"' "$CHAT_MATH_STATE_DIR/chat-math-events.jsonl" 2>/dev/null && ok "A15 直した数を計器に足す" || ng "A15" "$(cat "$CHAT_MATH_STATE_DIR/chat-math-events.jsonl" 2>/dev/null)"
out="$(printf '{not json' | CLAUDE_CODE_ENTRYPOINT=$D python3 "$DISP" 2>&1; echo "rc=$?")"
[ "$out" = "rc=0" ] && ok "A16 壊れた入力は黙る" || ng "A16" "$out"
mkdir -p "$TMP/copy" && cp "$DISP" "$GUARD" "$TMP/copy/"
out="$(jq -n '{session_id:"s", index:0, final:true, delta:"定義: $E_I$"}' | CLAUDE_CODE_ENTRYPOINT=$D python3 "$TMP/copy/chat-math-display-fix.py" 2>&1)"
grep -qF 'E_{I}' <<< "$out" && ok "A17 copy の配線でも隣の部品を読む" || ng "A17" "$out"

# ---- §B Stop の hook ---------------------------------------------------------------------------------
# mkt path final_text [feedback_line second_text]
mkt() {
  local path="$1" final="$2" fb="${3:-}" second="${4:-}"
  {
    jq -nc '{type:"user", entrypoint:"claude-desktop", message:{content:"数式を説明して"}}'
    jq -nc --arg t "$final" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
    if [ -n "$fb" ]; then
      jq -nc --arg t "$fb" '{type:"user", isMeta:true, message:{content:$t}}'
      jq -nc --arg t "$second" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
    fi
  } > "$path"
}
# stop label expect(1/0) transcript active [needle] [session]
stop() {
  local label="$1" expect="$2" t="$3" active="$4" needle="${5:-}" sid="${6:-sess-b}"
  local out actual=0
  out="$(jq -n --arg t "$t" --argjson a "$active" --arg s "$sid" '{hook_event_name:"Stop", session_id:$s, transcript_path:$t, stop_hook_active:$a}' | python3 "$GUARD" 2>&1)"
  grep -qF '"decision"' <<< "$out" && actual=1
  if [ "$actual" = "$expect" ] && { [ -z "$needle" ] || grep -qF -- "$needle" <<< "$out"; }; then ok "$label"; else ng "$label (expect=$expect actual=$actual needle=$needle)" "$out"; fi
}

t="$TMP/b1.jsonl"; mkt "$t" '定義を残す: $E_I$ の件。'
stop "B1 追記を求め、 全文は出し直させない" 1 "$t" false "返事の全文は出し直さない"
stop "B2 直した形を添える" 1 "$t" false '直した形 `$E_{I}$`'
for case in "B3 金額|Opus は \$4/\$20、 Fable は \$10/\$50 で、 半額以下です。" \
            "B4 shell の変数|消した 1: 「bmps=(\$CACHE/*.bmp(N)) # zsh (N) = nullglob」→「bmps=(\$CACHE/*.png(N))」" \
            "B5 題に入った \$\$|session「Close \$\$ and \\\$ gaps in guard」 を読んだ。" \
            "B6 書き方の言及 \$…\$|注記の中の数式を \$…\$ で書く。"; do
  label="${case%%|*}"; text="${case#*|}"
  t="$TMP/$(printf '%s' "$label" | tr -c 'A-Za-z0-9' '_').jsonl"; mkt "$t" "$text"
  stop "$label は数式でない = 止めない" 0 "$t" false
done
t="$TMP/b7.jsonl"; mkt "$t" '展開: $E_I(\boldsymbol P)=|\boldsymbol P|+m_I^2/(2|\boldsymbol P|)+\dots$ を使う。'
stop "B7 E_I( で始まる長い式は shell と見なさない" 1 "$t" false "DL_LONG"
t="$TMP/b8.jsonl"; mkt "$t" '阻止能 $dE/dx$ を測る。'
stop "B8 小文字の \$dE/dx\$ は数式として報告" 1 "$t" false "DL_NOSYM"
own=$'Stop hook feedback:\nchat-math-render-guard: この返事の数式のうち次の 1 箇所は…'
other=$'Stop hook feedback:\n別の hook: 行が足りない'
t="$TMP/b9.jsonl"; mkt "$t" '定義: $E_I$' "$own" '追記: 崩れた式は \(E_I\) です。'
before="$(grep -c after_own_block "$CHAT_MATH_STATE_DIR/chat-math-events.jsonl" 2>/dev/null || true)"
stop "B9 自分の差し戻しの後は止めない" 0 "$t" true
after="$(grep -c after_own_block "$CHAT_MATH_STATE_DIR/chat-math-events.jsonl" 2>/dev/null || true)"
[ "${after:-0}" -gt "${before:-0}" ] && ok "B10 自分の差し戻しの後に残った式を計器に数える" || ng "B10" "before=$before after=$after"
t="$TMP/b11.jsonl"; mkt "$t" '本文 (式なし)' "$other" '書き直し: 定義 $E_I$ の件。'
stop "B11 他の hook の差し戻しの後の返事は判定して止める" 1 "$t" true "DL_NOSYM"
t="$TMP/b12.jsonl"; mkt "$t" '定義を残す: $E_I$ の件。 積 $xy$ も。'
mkdir -p "$TMPDIR/chat-math-display-fix" && : > "$TMPDIR/chat-math-display-fix/sess-shown"
stop "B12 表示の印がある session では直らない式だけで止める" 1 "$t" false 'DL_NOSYM: $xy$' sess-shown
t="$TMP/b13.jsonl"; mkt "$t" '定義を残す: $E_I$ の件。'
stop "B13 表示の印がある session で全部直るなら止めない" 0 "$t" false "" sess-shown
# 校正 = 画面に出た全ての版 (差し戻された版も) を数える
mkdir -p "$TMP/home/.claude-x/projects/p" "$TMP/home/.claude/projects/q"
mkt "$TMP/home/.claude-x/projects/p/s1.jsonl" '定義: $E_I$' "$own" '定義: $E_{I}$'
out="$(HOME="$TMP/home" python3 "$GUARD" --calibrate 1 0 2>&1)"
grep -qE 'roots=2 displayed=2 fired=1 .*own_blocked=1' <<< "$out" && ok "B14 校正は全ての設定フォルダの、 差し戻された版も数える" || ng "B14" "$out"

for r in "${results[@]}"; do echo "$r"; done
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
