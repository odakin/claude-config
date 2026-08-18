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
# permission 矯正 (毎回、冪等):
#   - canonical / backup は 0600 (cp -p は旧 mode を保存するので backup も明示矯正 —
#     644 の premigration backup が group-readable な $HOME 配下に残った実例 2026-08-18)
#   - ~/.gmail-mcp と account dir は 0700 (credential 置き場に group/other の traverse 不要)
#   - 既存 backup (*.premigration.* / *.expired*) と legacy dir 内の loose secret file も
#     毎 run 0600 に self-heal (= 「backup を作る瞬間の chmod」 だけでは、旧版 engine が
#     他マシンに残した 0644 backup は永遠に直らない — run するだけで矯正される位置に置く)
#
# 前提: git-crypt unlock 済 (ciphertext のまま link を張ると全 consumer が JSON parse
#       error で死ぬため、magic bytes を見て abort する。空 file も同様に abort)
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
mkdir -p "$MCP_DIR"
chmod 700 "$MCP_DIR"   # credential 置き場は owner-only
chmod 700 "$REPO_DIR/secrets" 2>/dev/null || true   # filename (= alias 一覧) も他 user に見せない
# アカウント一覧は secrets/ の canonical file 名から導出 (ハードコードしない)。
# alias は path 部品になるので plain token のみ許可 (traversal 等の surprise を skip)。
ACCOUNTS=()
for f in "$REPO_DIR"/secrets/gmail-*-credentials.json; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"; a="${b#gmail-}"; a="${a%-credentials.json}"
    case "$a" in
        *[!A-Za-z0-9_-]*|"")
            echo "⚠️  skip: alias が不正な canonical 名: $b (allowed: letters, digits, _, -)" >&2
            continue
            ;;
    esac
    ACCOUNTS+=("$a")
done
if [ "${#ACCOUNTS[@]}" -eq 0 ]; then
    echo "⚠️  secrets/ に gmail-<alias>-credentials.json が 0 件 (初回 setup なら OK — client keys のみ link)"
fi
CHANGED=0

is_ciphertext() {
    # git-crypt の magic bytes (\0GITCRYPT) なら true (= unlock されていない)
    [ "$(head -c 9 "$1" 2>/dev/null | LC_ALL=C tr -d '\0')" = "GITCRYPT" ]
}

harden_existing_secrets() {
    # 既存 backup (*.premigration.* / *.expired*) と legacy dir (旧構成の残骸等) 内の
    # loose secret file を毎 run 0600 に、group/other bit の立った dir を 0700 に矯正する
    # self-heal。link_one の backup-時 chmod は「この run が作る backup」 しか守らない —
    # 旧版 engine が残した 0644 backup が group-readable な $HOME 構成で他 local user に
    # 読める実例 (2026-08-18) の再発防止で、pull + run の自然な動線だけで直るようにする。
    # 冪等・非致命 (既に 0600/0700 なら黙る)。中身は一切読まない (名前 pattern + mode のみ)。
    # find の -perm は BSD/GNU 両対応の「-g+r 形式 (= 当該 bit が立っている)」 のみ使う。
    local f d
    while IFS= read -r f; do
        [ -f "$f" ] || continue
        chmod 600 "$f" 2>/dev/null && echo "  🔒 mode 矯正 0600: $f" || true
    done < <(find "$MCP_DIR" -type f \
        \( -name '*.premigration.*' -o -name '*.expired*' \
           -o -name '*credentials*.json*' -o -name '*oauth*.json*' -o -name '*token*.json*' \) \
        \( -perm -g+r -o -perm -g+w -o -perm -g+x \
           -o -perm -o+r -o -perm -o+w -o -perm -o+x \) 2>/dev/null)
    while IFS= read -r d; do
        [ -d "$d" ] || continue
        chmod 700 "$d" 2>/dev/null && echo "  🔒 mode 矯正 0700: $d/" || true
    done < <(find "$MCP_DIR" -type d \
        \( -perm -g+r -o -perm -g+w -o -perm -g+x \
           -o -perm -o+r -o -perm -o+w -o -perm -o+x \) 2>/dev/null)
}

link_one() {
    local canonical="$1" runtime="$2"
    if [ ! -f "$canonical" ] || [ ! -s "$canonical" ]; then
        echo "❌ canonical 不在または空: $canonical (git pull / git-crypt unlock を確認)" >&2
        return 1
    fi
    if is_ciphertext "$canonical"; then
        echo "❌ canonical が ciphertext: $canonical (先に git-crypt unlock)" >&2
        return 1
    fi
    chmod 600 "$canonical" 2>/dev/null || true  # git は mode を保存しないので毎回矯正
    # dir 矯正は「symlink 済 → return」より前 (= 変更なしの run でも 700 が効く)
    mkdir -p "$(dirname "$runtime")"
    chmod 700 "$(dirname "$runtime")"
    if [ -L "$runtime" ]; then
        if [ "$(readlink "$runtime")" = "$canonical" ]; then
            echo "✓ $runtime (symlink 済)"
            return 0
        fi
        rm "$runtime"   # 別 target への symlink → 張り替え
    elif [ -f "$runtime" ]; then
        if ! cmp -s "$runtime" "$canonical"; then
            cp -p "$runtime" "$runtime.premigration.$TS"
            chmod 600 "$runtime.premigration.$TS"   # cp -p は旧 mode (644 だった実例あり) を保存するので矯正
            echo "  ↳ 実 file を backup: $runtime.premigration.$TS"
        fi
        rm "$runtime"
    fi
    ln -s "$canonical" "$runtime"
    echo "✓ $runtime → canonical に link"
    CHANGED=1
}

echo "=== gmail runtime credential → repo canonical symlink (冪等) ==="
# ⚠️ 空配列の "${ACCOUNTS[@]}" は bash 3.2 + set -u で unbound エラーになるため guard 展開
for acct in ${ACCOUNTS[@]+"${ACCOUNTS[@]}"}; do
    link_one "$REPO_DIR/secrets/gmail-$acct-credentials.json" \
             "$MCP_DIR/$acct/credentials.json"
done

echo "--- OAuth client keys ---"
link_one "$REPO_DIR/secrets/gmail-gcp-oauth.keys.json" "$MCP_DIR/gcp-oauth.keys.json"
for acct in ${ACCOUNTS[@]+"${ACCOUNTS[@]}"}; do
    link_one "$REPO_DIR/secrets/gmail-gcp-oauth.keys.json" \
             "$MCP_DIR/$acct/gcp-oauth.keys.json"
done

# 既存 backup / legacy 残骸の mode self-heal (冪等、clean なら無音)
harden_existing_secrets

echo ""
if [ "$CHANGED" = 1 ]; then
    echo "完了。実行中の MCP server は旧 token を in-memory 保持しているので、"
    echo "次回 Claude Code 起動から symlink 経由で読む (即時反映は不要)。"
else
    echo "変更なし (全 link 済)。"
fi
