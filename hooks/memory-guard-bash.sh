#!/usr/bin/env bash
# memory-guard-bash.sh — メモリ書き込みガード — Bash 用（§8 feedback deny + escape hatch）
# memory-guard-bash.sh — Bash 経由のメモリ書き込みガード (deny + escape-hatch)
# Edit/Write ツールのガード (memory-guard.sh) を補完
#
# 正本: claude-config/hooks/memory-guard-bash.sh
# setup.sh が ~/.claude/hooks/ に symlink を作成
#
# 対象: PreToolUse (Bash)
# 動作: メモリパスへの書き込みパターンを検出したら deny
#       - MEMORY.md への write は pass (index 更新のため)
#       - command 文字列に "machine-local" を含めば escape hatch として pass
#       - rm / ls / cat 等の read/delete は対象外 (書き込みパターンのみ)
# 依存: jq（なければ入力全体をパターンマッチ）
#
# jq 不在時の fallback 挙動: COMMAND に入力 JSON 全体を代用する。 WRITE_PATTERN は
# 「書き込み記号の後に memory path が続く」形なので JSON 全体でも概ね同じ判定に
# なるが、 tool_input 以外のフィールドに書き込み風文字列があると偽陽性 deny に
# なりうる (= fail-closed 側に倒れる、 escape hatch で通せる)。
#
# ⚠️ WRITE_PATTERN の検出限界 (= 本 hook は defense-in-depth の一層であり保証ではない):
#   検出するのは高信号 pattern (>, >>, tee, cp, mv と同一 command 内でその後に
#   memory path が literal で続く形) のみ。 以下は原理的に検出**不能**:
#     - interpreter 経由:  python3 -c "open('<memory path>','w').write(...)"
#     - 変数間接 redirect: OUT=<memory path>; echo x > "$OUT"
#       (redirect 記号の後に /memory/ literal が現れないため)
#     - script file 経由:  書き込みロジックを file に書いて bash script.sh
#   完全検出は shell 意味解析が必要で regex では原理的に不能 (proxy 盲点、
#   docs/convention-design-principles.md#proxy-blind-spot)。 検出を際限なく
#   強化するのでなく、 限界を明示して規律 + human-steering と併用する。
#   既知の非検出形は memory-guard-bash.test.sh の P6/P7 で回帰仕様として固定済。
#
# 2026-04-17 変更: warning-only → deny に格上げ (Edit/Write ガードとの一貫性)

set -uo pipefail  # -e は使わない (grep no-match 等の正当な非ゼロ exit があるため、 hook-authoring.md#shebang-set-policy)

INPUT=$(cat)

# 高速パス: memory を含まなければ即通過
[[ "$INPUT" != *"/.claude/projects/"*"/memory/"* ]] && exit 0

if command -v jq &> /dev/null; then
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
else
    COMMAND="$INPUT"
fi

[[ -z "$COMMAND" ]] && exit 0

# 書き込みパターン: > redirect, tee, cp, mv
WRITE_PATTERN='(>|tee |cp |mv ).*/.claude/projects/.*/memory/'
if ! echo "$COMMAND" | grep -qE "$WRITE_PATTERN"; then
    exit 0
fi

# MEMORY.md のみへの書き込みは whitelist (index 更新)
# 書き込み先が MEMORY.md のみなら pass
NON_MEMORY_MD_WRITES=$(echo "$COMMAND" | grep -oE "$WRITE_PATTERN"'[^ ]*' | grep -v '/memory/MEMORY\.md' | wc -l | tr -d ' ')
if [[ "$NON_MEMORY_MD_WRITES" -eq 0 ]]; then
    exit 0
fi

# Escape hatch: command 文字列に "machine-local" を含む
if echo "$COMMAND" | grep -q "machine-local"; then
    exit 0
fi

# --- 書き込みを deny ---
cat >&2 << 'EOF'
memory-guard-bash: メモリディレクトリへの Bash 書き込みを deny しました。

Memory directory はマシンローカル (git 非同期)。cross-machine で効かせたい情報は
git 同期先 (claude-config/, あなたの個人層 (あれば), 該当プロジェクトの CLAUDE.md / SESSION.md / DESIGN.md) に書く。

詳細: claude-config/docs/convention-design-principles.md §8 (= #rule-vs-mechanism) (memory policy)。

意図的なマシンローカル書き込みの escape hatch:
  command 文字列のどこかに "machine-local" を含めると pass する
  (例: コメント # machine-local: foo / 変数名 MACHINE_LOCAL_REASON 等)
EOF

if command -v jq &> /dev/null; then
    jq -n '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Memory はマシンローカル。cross-machine で効かせたい情報は git 同期先に書く。意図的なマシンローカル書き込みは command に machine-local 文字列を含める。"}}'
else
    echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Memory はマシンローカル。git 同期先に書くか command に machine-local を含める。"}}'
fi
exit 0
