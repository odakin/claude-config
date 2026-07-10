#!/bin/bash
# memory-guard.sh — メモリ書き込みガード — Edit/Write 用（§8 feedback deny + escape hatch: machine-local marker）
# memory-guard.sh — メモリファイル書き込みガード (deny + escape-hatch)
# CONVENTIONS.md §2「記録先の判別」の機械的チェックポイント
#
# 正本: claude-config/hooks/memory-guard.sh
# setup.sh が ~/.claude/hooks/ に symlink を作成
#
# 対象: PreToolUse (Edit|Write)
# 動作: メモリディレクトリへの書き込みを permissionDecision=deny でブロック
#       - MEMORY.md (index) は whitelist
#       - content に "<!-- machine-local:" marker があれば escape hatch として pass
# 依存: jq（なければ grep フォールバック）
#
# jq 不在時の fallback 挙動 (= 方針: deny 判定は狭めず、 escape hatch 側を緩める):
#   - FILE_PATH は grep/sed で抽出 (file_path キーのみ対応)。 抽出できなければ
#     exit 0 = その入力形については fail-open。
#   - CONTENT は入力 JSON 全体で代用 → machine-local marker 判定が「content 内」
#     でなく「入力のどこか」に緩む (= escape hatch が広がる方向の fail-open)。
#     deny 判定自体 (path pattern) は jq 有無で不変。
#
# ⚠️ 検出限界 (= 本 hook は defense-in-depth の一層であり保証ではない):
#   本 hook が見るのは Edit/Write tool の file_path だけ。 Bash 経由の書き込みは
#   sibling の memory-guard-bash.sh が cover するが、 そちらも redirect/tee/cp/mv
#   の高信号 pattern のみで interpreter 経由等は素通りする (そちらの header 参照)。
#   完全検出は原理的に不能 (proxy 盲点、
#   docs/convention-design-principles.md#proxy-blind-spot) なので、 検出を際限なく
#   強化するのでなく、 限界を明示して規律 + human-steering と併用する。
#
# 2026-04-17 変更: ask → deny に格上げ (memory/ への feedback_* 流入を構造的に防ぐ)

INPUT=$(cat)

# --- 高速パス: "memory" を含まなければ即通過 ---
[[ "$INPUT" != *"/memory/"* ]] && exit 0

# --- file_path と content を抽出（jq 優先、なければ grep） ---
if command -v jq &> /dev/null; then
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.file // empty')
    # Write は .content、Edit は .new_string に書き込み内容が入る
    CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // empty')
else
    FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | head -1 | sed 's/.*: *"//;s/"$//')
    CONTENT="$INPUT"  # fallback: match against whole input
fi

[[ -z "$FILE_PATH" ]] && exit 0
[[ "$FILE_PATH" != *"/.claude/projects/"*"/memory/"* ]] && exit 0

# MEMORY.md（インデックス）は通過
[[ "$FILE_PATH" == */MEMORY.md ]] && exit 0

# Escape hatch: content に machine-local marker があれば通過
if echo "$CONTENT" | grep -q "machine-local:"; then
    exit 0
fi

# --- 書き込みを deny ---
cat >&2 << 'EOF'
memory-guard: メモリファイルへの書き込みを deny しました。

Memory directory はマシンローカル (git 非同期)。cross-machine で効かせたい情報は
git 同期先 (claude-config/, あなたの個人層 (あれば), 該当プロジェクトの CLAUDE.md / SESSION.md / DESIGN.md) に書く。

詳細: claude-config/docs/convention-design-principles.md §8 (= #rule-vs-mechanism) (memory policy)、
      claude-config/docs/personal-layer.md (4 層モデル)。

このマシン固有の事実 (macOS 設定・ハード構成等) を意図的に記録する escape hatch:
  content に `<!-- machine-local: <理由> -->` marker を含めると pass する。
EOF

if command -v jq &> /dev/null; then
    jq -n '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Memory directory はマシンローカル。cross-machine で効かせたい情報は git 同期先 (claude-config/, 個人層, 該当プロジェクトの dynamic docs) に書く。意図的なマシンローカル書き込みは content に `<!-- machine-local: <理由> -->` marker を含める。"}}'
else
    echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Memory はマシンローカル。git 同期先に書くか、content に <!-- machine-local: --> marker を含める。"}}'
fi
exit 0
