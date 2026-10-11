#!/usr/bin/env bash
# chat-math-render-guard.test.sh — logic + incident-replay selftest
#
# §A incident replay (2026-10-09〜11 に Code タブで生表示になった形): 読点の直後の `\(` / 記号の無い `\(g\)` /
#     `\(-i\,d/dx\)` (CLI flag 形) / `$P_D$` / `$ x $` / `\[…\]` / `\|` / 60 文字超の `$…$` / 表のセルの `|`。
# §B 誤検出の regression: 空白の後の `\(…\)` (`\,` 入りを含む) / `$t$` / `$x-y$` / `$1/N^2$` / 1 行と複数行の `$$` /
#     inline code と fenced block の中 / 強調で包んだ式 / `{-}i` / 通貨の `$5` / CLI の session。
# §C fail-open: stop_hook_active / transcript 不在 / 空入力 = 沈黙。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/chat-math-render-guard.py"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not found"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not found"; exit 0; }

pass=0; fail=0; results=()
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# mktranscript path entrypoint final_text
mktranscript() {
  local path="$1" ep="$2" final="$3"
  {
    jq -nc --arg ep "$ep" '{type:"user", entrypoint:$ep, message:{content:"数式を説明して"}}'
    jq -nc '{type:"assistant", message:{content:[{type:"tool_use", name:"Read", input:{file_path:"x"}}]}}'
    jq -nc '{type:"user", message:{content:[{type:"tool_result", content:"ok"}]}}'
    jq -nc --arg t "$final" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
  } > "$path"
}

mkpayload() { jq -n --arg t "$1" --argjson a "${2:-false}" '{hook_event_name:"Stop", transcript_path:$t, stop_hook_active:$a}'; }

# assert label expect(1/0) payload [needle]
assert() {
  local label="$1" expect="$2" input="$3" needle="${4:-}"
  local out actual=0
  out="$(printf '%s' "$input" | python3 "$HOOK" 2>&1)" || true
  if printf '%s' "$out" | grep -qF '"decision"' && printf '%s' "$out" | grep -qF 'chat-math-render-guard'; then
    actual=1
  fi
  if [ "$actual" = "$expect" ] && { [ -z "$needle" ] || printf '%s' "$out" | grep -qF -- "$needle"; }; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect actual=$actual needle=${needle:-}) :: $(printf '%s' "$out" | head -c 300)")
  fi
}

# case label entrypoint expect needle final_text
case_() {
  local label="$1" ep="$2" expect="$3" needle="$4" text="$5"
  local t="$TMP/$(printf '%s' "$label" | tr -c 'A-Za-z0-9' '_').jsonl"
  mktranscript "$t" "$ep" "$text"
  assert "$label" "$expect" "$(mkpayload "$t")" "$needle"
}

D=claude-desktop

# ---- §A fire --------------------------------------------------------------------------------------
case_ "A1 読点の直後の \\(" $D 1 "BS_PREV" '開集合、\( x=1 \) とする。'
case_ "A2 記号の無い \\(g\\)" $D 1 "BS_NOSYM" '関数 \( g \) に対して'
case_ "A3 \\(-i\\,d/dx\\) は flag 形" $D 1 "BS_FLAG" '運動量は \(-i\,d/dx\) である。'
case_ "A4 \$P_D\$" $D 1 "DL_NOSYM" '検出器の運動量 $P_D$ を固定する。'
case_ "A5 \$ x \$" $D 1 "DL_OPEN" '変数 $ x $ を取る。'
case_ "A6 \\[…\\]" $D 1 "BRACKET" '次の式 \[ E=mc^2 \] を見よ。'
case_ "A7 \\| in \$…\$" $D 1 "DL_BAD_ESC" 'ノルム $\|v\|$ は有限。'
case_ "A8 60 文字超の \$…\$" $D 1 "DL_LONG" '式 $\langle\varphi_0|H\varphi_0\rangle=E=\langle\psi|H\psi\rangle+\langle\psi|V\psi\rangle$ を使う。'
case_ "A9 表のセルの |" $D 1 "TABLE_PIPE" $'| 量 | 式 |\n|---|---|\n| 内積 | $\\langle\\psi|\\phi\\rangle$ |'
case_ "A10 句点の直後の \\( (記号あり)" $D 1 "BS_PREV" '微分同相。\( y_{j}:=x_{j+1} \) と置く。'
case_ "A11 desktop-3p でも発火" claude-desktop-3p 1 "BS_NOSYM" '定数 \( K \) を取る。'
case_ "A12 \$[0,1]\$" $D 1 "DL_NOSYM" '区間 $[0,1]$ 上で。'
case_ "A13 \$…\$ だけで記号の無い返事は KaTeX が読まれない" $D 1 "MSG_NO_KATEX" '積 $xy$ と $ab$ の組。'
case_ "A14 数字始まりで記号の無い \$1/|p|\$" $D 1 "DL_DIGIT" '発散は $1/|p|$ の形。'

# ---- §B silent ------------------------------------------------------------------------------------
case_ "B1 空白の後の \\(…\\)" $D 0 "" '開集合 \( x_{0}\in U \) とする。'
case_ "B2 \\, 入りも空白の後なら描かれる" $D 0 "" '測度 \( a\,\mathrm d^{N}x \) を押し出す。'
case_ "B3 \$t\$ と \$x-y\$" $D 0 "" '時刻 $t$ と差 $x-y$ を取る。'
case_ "B4 数字始まりで ^ を持つ \$1/N^2\$" $D 0 "" '展開は $1/N^2$ の次数で。'
case_ "B5 1 行の \$\$…\$\$ (\\\\0 を含む)" $D 0 "" $'行列は\n$$D\\Phi=\\begin{pmatrix}a&b\\\\0&1\\end{pmatrix}$$\nである。'
case_ "B6 複数行の \$\$ block" $D 0 "" $'次を示す。\n$$\n\\int_{\\mathbb R} b(\\omega)\\,g(\\omega)\\,\\mathrm d\\omega=\\iint a\\,g(h)\n$$\n以上。'
case_ "B7 inline code の中" $D 0 "" '例: `\(K\)` は生表示になる (規約の例示)。'
case_ "B8 fenced block の中" $D 0 "" $'例:\n```\n\\(K\\) と $P_D$\n```\n以上。'
case_ "B9 強調で包んだ式" $D 0 "" '結論は **\( b\in C_0^\infty \)** である。'
case_ "B10 {-}i は flag 形でない" $D 0 "" '運動量は \( {-}i\,\mathrm d/\mathrm dx \) である。'
case_ "B11 通貨の \$5" $D 0 "" '価格は $5 で、 送料は $3 です。'
case_ "B12 CLI の session は見ない" cli 0 "" '関数 \( g \) に対して、\( x=1 \) とする。'
case_ "B13 行頭の \\(" $D 0 "" $'前置き。\n\\( \\omega \\) を固定する。'
case_ "B14 ( の直後の \\(" $D 0 "" '集合 (\( \omega=0 \) の等位面) を見る。'
case_ "B15 添字 x_1 形は記号なしでも可" $D 0 "" '座標 \( x_1 \) を取る。'
case_ "B16 \$\\hat T\$ と \$T_{D}\$" $D 0 "" '演算子 $\hat T$ と $T_{D}$ を比べる。'

# ---- §C fail-open ---------------------------------------------------------------------------------
t="$TMP/c1.jsonl"; mktranscript "$t" $D '関数 \( g \) に対して'
assert "C1 stop_hook_active は沈黙" 0 "$(mkpayload "$t" true)"
assert "C2 transcript 不在は沈黙" 0 "$(mkpayload "$TMP/nope.jsonl")"
assert "C3 空入力は沈黙" 0 ""
assert "C4 壊れた JSON は沈黙" 0 "{not json"

for r in "${results[@]}"; do echo "$r"; done
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
