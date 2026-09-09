#!/usr/bin/env bash
# pasted-command-comment-guard.test.sh — logic + incident-replay selftest
#
# 正本: claude-config/hooks/pasted-command-comment-guard.test.sh
#
# §A incident replay: 2026-09-09 の事故ブロック (git status / grep / git rebase
#     --continue に行内 # 注釈) を合成 transcript で再現し fire を確認。
# §B FP regression: 注釈なしの素コマンド / 貼り付け指示語なし / shebang /
#     quote 内 `#` / fence 外 / stop_hook_active / transcript 不在 = silent を固定化。
# §C 行頭 # 単独行も fire (= 「注釈を独立行に逃がす」 では直らないことの固定化)。
# §D 英語 chat の貼り付け指示語 (= 層1 hoist で追加。 cue は推定なので FP 監視対象)。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/pasted-command-comment-guard.sh"
[ -x "$HOOK" ] || { echo "FAIL: hook not executable: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq 不在 (環境依存) — selftest 省略"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在 — selftest 省略"; exit 0; }

pass=0; fail=0; results=()
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mktranscript() {
  local path="$1" final="$2"
  {
    jq -nc '{type:"user", message:{content:"直して"}}'
    jq -nc --arg t "$final" '{type:"assistant", message:{content:[{type:"text", text:$t}]}}'
  } > "$path"
}

assert() {
  local label="$1" expect="$2" final="$3" active="${4:-false}"
  local tp="$TMP/t.$RANDOM.jsonl" out actual=0
  mktranscript "$tp" "$final"
  out="$(jq -nc --arg p "$tp" --argjson a "$active" \
            '{transcript_path:$p, stop_hook_active:$a}' | "$HOOK" 2>&1)" || true
  case "$out" in *'"decision":"block"'*) actual=1 ;; esac
  if [ "$actual" = "$expect" ]; then
    pass=$((pass+1)); results+=("  PASS  $label")
  else
    fail=$((fail+1)); results+=("  FAIL  $label (expect=$expect actual=$actual)")
  fi
}

FENCE='```'

# ---------- §A incident replay (2026-09-09) ----------
assert "A1 事故そのもの: git rebase --continue に行内 # 注釈" 1 \
"これをターミナルで実行してください。

${FENCE}
cd ~/Claude/odakin-prefs
git status                                            # \"interactive rebase in progress\"
git add CLAUDE.md leak-incidents.md
git rebase --continue                                 # todo 残り 0 なのでこれで完了
git push
${FENCE}"

assert "A2 grep 行の行内注釈 (全角括弧つき)" 1 \
"打ってみてください。

${FENCE}
grep -rn 'foo' --include='*.md' .    # 空のはず（除去済み）
${FENCE}"

# ---------- §C 行頭 # 単独行も壊れる ----------
assert "C1 行頭 # の説明行 (独立行へ逃がしても zsh は command not found)" 1 \
"貼り付けて実行してください。

${FENCE}
# ここから rebase の続き
git rebase --continue
${FENCE}"

# ---------- §D 英語 chat (層1 hoist で追加、 cue は推定校正) ----------
assert "D1 英語の貼り付け指示 + 行内 # = 発火" 1 \
"Run this in your terminal:

${FENCE}
git rebase --continue   # todo is empty now
${FENCE}"

assert "D2 英語 + 注釈なし = 発火しない" 0 \
"Run the following in your terminal:

${FENCE}
git rebase --continue
${FENCE}"

# ---------- §B FP regression ----------
assert "B1 注釈なしの素コマンド = 発火しない" 0 \
"ターミナルで実行してください。

${FENCE}
cd ~/Claude/odakin-prefs
git rebase --continue
git push
${FENCE}"

assert "B2 貼り付け指示語なし (script の中身を見せているだけ) = 発火しない" 0 \
"現在の実装はこうなっています。

${FENCE}
git rebase --continue   # todo 残り 0
${FENCE}"

assert "B3 shebang 行は # 扱いしない" 0 \
"これを実行してください。

${FENCE}
sh /tmp/fix.sh
${FENCE}
中身は #!/usr/bin/env bash で始まります。"

assert "B4 quote 内の # は誤検出しない" 0 \
"実行してください。

${FENCE}
grep -n '^#' /tmp/foo.txt
${FENCE}"

assert "B5 fence 外に # があっても発火しない" 0 \
"実行してください (# は説明用の記号です)。

${FENCE}
git push
${FENCE}"

assert "B6 stop_hook_active=true は loop guard で無発火" 0 \
"実行してください。

${FENCE}
git rebase --continue   # todo 残り 0
${FENCE}" true

# transcript 不在 = silent
out="$(jq -nc '{transcript_path:"/nonexistent/x.jsonl", stop_hook_active:false}' | "$HOOK" 2>&1)" || true
if [ -z "$out" ]; then pass=$((pass+1)); results+=("  PASS  B7 transcript 不在 = fail-open silent")
else fail=$((fail+1)); results+=("  FAIL  B7 transcript 不在で出力: $out"); fi

printf '%s\n' "${results[@]}"
echo "pasted-command-comment-guard: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ] || exit 1
