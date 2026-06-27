#!/bin/bash
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
