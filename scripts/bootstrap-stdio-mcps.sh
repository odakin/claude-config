#!/usr/bin/env bash
# bootstrap-stdio-mcps.sh — generic auto-bootstrap library for self-hosted stdio MCPs.
#
# 正本: claude-config/scripts/bootstrap-stdio-mcps.sh
#
# Usage:
#   bash bootstrap-stdio-mcps.sh <registry-file> <base-dir>
#
#   registry-file: plaintext, 1 line per pair "<subdir>:<mcp-name>"
#                  ('#' 以降 comment、 空行 skip)
#   base-dir:      base directory containing the subdirs (each <subdir>/
#                  must have server.mjs and package.json)
#
# 動作 (= fully 冪等):
#   1. registry を読む (= 不在なら silent exit 0)
#   2. `claude mcp list` と diff を取り、 未登録 pair を特定
#   3. 未登録 pair それぞれに対し:
#      a. <base-dir>/<subdir>/server.mjs が無ければ silent skip
#      b. <base-dir>/<subdir>/node_modules が無ければ `npm install` (初回 only)
#      c. `claude mcp add <mcp-name> -- node <full-path>` で登録
#   4. 登録に成功した pair を stdout に「<mcp-name> = node <path>」 1 行ずつ print
#
# Exit code: 0 always (fail-open)。 ファイル不在・npm 失敗・claude not found
#   は silent skip。 呼び出し側 (= layer 3 hook) は stdout の有無で「何か追加されたか」 を判定。
#
# 設計動機 (= 2026-06-26 cross-machine 切替頻発化対応):
#   各 user が <personal-layer>/hooks/ 等に inline 重複実装する必要を消す。
#   layer 3 (個人層) は thin wrapper hook で本 script を call するだけ、
#   mechanism は layer 1 で単一 SoT 化。
#
# 環境変数:
#   CLAUDE_BOOTSTRAP_NO_ADD  1 なら `claude mcp add` を実際には call しない (= dry-run、 test 用)
#   CLAUDE_BOOTSTRAP_MCP_LIST 既存 MCP list の代替 stdin (= test 用 mock)

set -uo pipefail

REGISTRY="${1:-}"
BASE_DIR="${2:-}"

if [ -z "$REGISTRY" ] || [ -z "$BASE_DIR" ]; then
  # silent (= fail-open、 docstring 想定外 invoke を session 起動阻害にしない)
  exit 0
fi

if [ ! -f "$REGISTRY" ]; then
  # registry 不在 = 何もしない (= 該当 repo が clone されていない等)
  exit 0
fi

if ! command -v claude >/dev/null 2>&1; then
  # test mock (CLAUDE_BOOTSTRAP_MCP_LIST) 注入時は dry-run 経路のみで CLI 不要 ->
  # CLI 不在の CI でも test が回るよう続行 (2026-07-10)
  [ "${CLAUDE_BOOTSTRAP_MCP_LIST+set}" = "set" ] || exit 0
fi

# 現状の登録済 MCP list (= test 用 mock 経由優先)
# Fast path: ~/.claude.json を python 直読 (= ~50ms)。 `claude mcp list` は
# MCP health check で 3-4s 食う (= --no-health-check flag 不在、 2026-06-26 計測) →
# SessionStart hook の latency が爆発するため直読を default、 fail で claude mcp list へ fallback。
# format: ~/.claude.json の projects[*].mcpServers の key 全部 (= 全 project 横断)、 改行区切り。
# 「<mcp-name>:」 prefix を付けて出力 = grep -E "^<name>[: ]" pattern と互換。
if [ "${CLAUDE_BOOTSTRAP_MCP_LIST+set}" = "set" ]; then
  current_mcps="$CLAUDE_BOOTSTRAP_MCP_LIST"
elif [ -f "$HOME/.claude.json" ] && command -v python3 >/dev/null 2>&1; then
  current_mcps="$(python3 -c '
import json, os, sys
try:
    d = json.load(open(os.path.expanduser("~/.claude.json")))
    names = set()
    for proj in d.get("projects", {}).values():
        for name in (proj.get("mcpServers", {}) or {}).keys():
            names.add(name)
    for n in sorted(names):
        print(f"{n}: stdio")
except Exception:
    sys.exit(0)
' 2>/dev/null || true)"
  # 直読 fail (= 空) なら fallback (= 健全側に倒す = 過剰 add より silent skip)
  if [ -z "$current_mcps" ]; then
    current_mcps="$(claude mcp list 2>/dev/null || true)"
  fi
else
  current_mcps="$(claude mcp list 2>/dev/null || true)"
fi

# registry の各 pair を iterate
while IFS=: read -r subdir mcpname; do
  [ -z "$subdir" ] && continue
  [ -z "$mcpname" ] && continue

  # 既登録なら skip (= 冪等 / fast path)
  # claude mcp list の format: "<mcp-name>: <type> - ..." or "<mcp-name> <type>"
  if printf '%s\n' "$current_mcps" | grep -qE "^${mcpname}[: ]"; then
    continue
  fi

  server_path="$BASE_DIR/$subdir/server.mjs"
  if [ ! -f "$server_path" ]; then
    # server.mjs 不在 = git pull 未完 or 配置ミス → silent skip
    continue
  fi

  # node_modules 不在なら npm install (= 初回 only、 ~10s 許容)
  if [ ! -d "$BASE_DIR/$subdir/node_modules" ]; then
    if command -v npm >/dev/null 2>&1; then
      (cd "$BASE_DIR/$subdir" && npm install --silent --no-audit --no-fund) >/dev/null 2>&1 || true
    fi
  fi

  if [ "${CLAUDE_BOOTSTRAP_NO_ADD:-0}" = "1" ]; then
    printf '%s (dry-run, would add: node %s)\n' "$mcpname" "$server_path"
  elif claude mcp add "$mcpname" -- node "$server_path" >/dev/null 2>&1; then
    printf '%s = node %s\n' "$mcpname" "$server_path"
  fi
done < <(sed 's/#.*//' "$REGISTRY" | awk 'NF {print $1}')

exit 0
