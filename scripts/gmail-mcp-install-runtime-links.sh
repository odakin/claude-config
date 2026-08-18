#!/bin/bash
# gmail-mcp-install-runtime-links.sh — ~/.gmail-mcp/ の runtime credential を config repo canonical への symlink に張り替える冪等エンジン (generic、 layer 1 が実行実体。 runbook = conventions/gmail-mcp-multiaccount.md)
#
# Usage: gmail-mcp-install-runtime-links.sh <config-repo-dir>
#
# 設計:
#   canonical = 本リポ secrets/gmail-<account>-credentials.json (git-crypt 暗号化 tracked)
#   runtime   = ~/.gmail-mcp/<account>/credentials.json (= canonical への symlink)
#   OAuth client keys も同様: secrets/gmail-gcp-oauth.keys.json ←
#     ~/.gmail-mcp/gcp-oauth.keys.json + ~/.gmail-mcp/<account>/gcp-oauth.keys.json
#
# 冪等性:
#   - 既に正しい symlink → skip
#   - 実 file が居る → 中身が canonical と同一なら黙って置換、違えば
#     .premigration.<ts> に backup してから置換 (= このマシン固有の token は失われない。
#     refresh_token はマシン非依存なので canonical 側 token で全マシン動く =
#     calendar/classroom の repo 共有 token と同じ運用実績)
#   - 不在 → dir 作成 + symlink
#
# 前提: git-crypt unlock 済 (ciphertext のまま link を張ると全 consumer が JSON parse
#       error で死ぬため、magic bytes を見て abort する)
#
# 新マシン手順: private config repo を clone → git-crypt unlock →
#   bash install-runtime-links.sh (認証は canonical 配布済なので不要)

set -euo pipefail

REPO_DIR="${1:-}"
if [ -z "$REPO_DIR" ] || [ ! -d "$REPO_DIR/secrets" ]; then
    echo "Usage: $0 <config-repo-dir>  (= secrets/ を持つ private config repo)" >&2
    exit 1
fi
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
MCP_DIR="$HOME/.gmail-mcp"
TS="$(date +%Y%m%d%H%M%S)"
# アカウント一覧は secrets/ の canonical file 名から導出 (ハードコードしない)
ACCOUNTS=()
for f in "$REPO_DIR"/secrets/gmail-*-credentials.json; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"; a="${b#gmail-}"; ACCOUNTS+=("${a%-credentials.json}")
done
CHANGED=0

is_ciphertext() {
    # git-crypt の magic bytes (\0GITCRYPT) なら true (= unlock されていない)
    [ "$(head -c 9 "$1" 2>/dev/null | LC_ALL=C tr -d '\0')" = "GITCRYPT" ]
}

link_one() {
    local canonical="$1" runtime="$2"
    if [ ! -f "$canonical" ]; then
        echo "❌ canonical 不在: $canonical (git pull を確認)" >&2
        return 1
    fi
    if is_ciphertext "$canonical"; then
        echo "❌ canonical が ciphertext: $canonical (先に git-crypt unlock)" >&2
        return 1
    fi
    chmod 600 "$canonical" 2>/dev/null || true  # git は mode を保存しないので毎回矯正
    if [ -L "$runtime" ]; then
        if [ "$(readlink "$runtime")" = "$canonical" ]; then
            echo "✓ $runtime (symlink 済)"
            return 0
        fi
        rm "$runtime"   # 別 target への symlink → 張り替え
    elif [ -f "$runtime" ]; then
        if ! cmp -s "$runtime" "$canonical"; then
            cp -p "$runtime" "$runtime.premigration.$TS"
            echo "  ↳ 実 file を backup: $runtime.premigration.$TS"
        fi
        rm "$runtime"
    fi
    mkdir -p "$(dirname "$runtime")"
    ln -s "$canonical" "$runtime"
    echo "✓ $runtime → canonical に link"
    CHANGED=1
}

echo "=== gmail runtime credential → repo canonical symlink (冪等) ==="
for acct in "${ACCOUNTS[@]}"; do
    link_one "$REPO_DIR/secrets/gmail-$acct-credentials.json" \
             "$MCP_DIR/$acct/credentials.json"
done

echo "--- OAuth client keys ---"
link_one "$REPO_DIR/secrets/gmail-gcp-oauth.keys.json" "$MCP_DIR/gcp-oauth.keys.json"
for acct in "${ACCOUNTS[@]}"; do
    link_one "$REPO_DIR/secrets/gmail-gcp-oauth.keys.json" \
             "$MCP_DIR/$acct/gcp-oauth.keys.json"
done

echo ""
if [ "$CHANGED" = 1 ]; then
    echo "完了。実行中の MCP server は旧 token を in-memory 保持しているので、"
    echo "次回 Claude Code 起動から symlink 経由で読む (即時反映は不要)。"
else
    echo "変更なし (全 link 済)。"
fi
