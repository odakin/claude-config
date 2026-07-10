#!/bin/bash
# public-leak-guard.sh — 公開リポ leak 防止 — PreToolUse(Edit|Write|MultiEdit) Tier A 構造制約 regex
# public-leak-guard.sh — 公開リポへの構造的 leak の検出 (Tier A regex only)
#
# 正本: claude-config/hooks/public-leak-guard.sh
# setup.sh が ~/.claude/hooks/ に symlink を作成
#
# 対象: PreToolUse (Edit | Write | MultiEdit)
# 動作: 対象ファイルが git repo 内で、その repo root に
#       `.claude/public-repo.marker` が存在する場合に、書き込み content を
#       Tier A 構造制約 regex で scan する。hit した場合は
#       permissionDecision=ask で user 確認を仰ぐ。
#
# 設計思想:
#   - 本 hook は `sensitive-repo-patterns.ja.md §3-3` の「構造制約」
#     原則を純粋適用する層。literal blocklist は一切持たない
#     (= script source に固有名詞を埋め込まない = public な claude-config
#     に置いても meta-leak しない)
#   - literal 的な leak (組織名、間接 context 表現等) は pre-commit 層
#     (public-precommit-runner.sh) で ephemeral に sensitive-terms.txt を
#     読んで catch する。そちらは本 hook とは独立した責務
#   - 設計の全体像と代替案の棄却理由は `claude-config/DESIGN.md` の
#     「公開リポ leak 防止」セクション参照
#
# 依存: jq (なければ fail-open で exit 0)
#
# Tier A 検出パターン:
#   1. email        — [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}
#                     (noreply@anthropic.com / noreply@github.com 等は allowlist)
#   2. abs_path     — /Users/[a-z][a-z0-9_-]*
#   3. ipv4         — \b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b
#                     (0.0.0.0 / 127.0.0.1 / 255.255.255.255 / RFC1918
#                      private range / 169.254.*  link-local を allowlist)
#   4. token_prefix — ghp_[A-Za-z0-9]{30,} / github_pat_[A-Za-z0-9_]{30,}
#                     / sk-[A-Za-z0-9]{30,}
#   5. discord_mention — <@&?[0-9]{17,20}>
#                     Discord snowflake user/role mention. Config field
#                     names like "mention_target" look innocent but carry
#                     persistent cross-server PII — see
#                     `conventions/identity-in-config.md`.

set -uo pipefail

# --- 高速パス 1: jq がないと content 抽出が困難 → fail-open ---
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

# --- stdin を読む ---
INPUT="$(cat)"
[ -z "$INPUT" ] && exit 0

# --- file_path を抽出 ---
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
[ -z "$FILE_PATH" ] && exit 0

# --- 高速パス 2: file_path の所属 repo root を特定 ---
#
# file_path は存在しないこともある (Write で新規作成の場合)。
# なので親ディレクトリから遡って .git を探す。
dir="$(dirname "$FILE_PATH")"
while [ "$dir" != "/" ] && [ -n "$dir" ]; do
  if [ -d "$dir/.git" ] || [ -f "$dir/.git" ]; then
    REPO_ROOT="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

[ -z "${REPO_ROOT:-}" ] && exit 0

# --- 高速パス 3: marker file がなければ素通し ---
[ -f "$REPO_ROOT/.claude/public-repo.marker" ] || exit 0

# --- content を抽出 ---
# Edit:      tool_input.new_string
# Write:     tool_input.content
# MultiEdit: tool_input.edits[].new_string (配列を改行で join)
CONTENT="$(printf '%s' "$INPUT" | jq -r '
  .tool_input.new_string //
  .tool_input.content //
  (.tool_input.edits // [] | map(.new_string // "") | join("\n")) //
  empty
' 2>/dev/null || true)"

[ -z "$CONTENT" ] && exit 0

# ----------------------------------------------------------------------
# Tier A regex check
#
# hits 配列には "pattern_name: matched_sample" を詰める。
# pattern_name と一致した具体文字列のペアを後でまとめて表示する。
# ----------------------------------------------------------------------
HITS=""

# --- 1. email ---
# GNU grep 拡張に依存しないため `grep -oE` を使う。
# allowlist: grep -v で除外。
EMAIL_HITS="$(
  printf '%s' "$CONTENT" \
    | grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' 2>/dev/null \
    | grep -vE '^(noreply@anthropic\.com|noreply@github\.com|support@github\.com)$' \
    || true
)"
if [ -n "$EMAIL_HITS" ]; then
  HITS="${HITS}
[email] $(printf '%s' "$EMAIL_HITS" | head -3 | tr '\n' ' ')"
fi

# --- 2. abs_path ---
# `/Users/<name>` の形を検出。allowlist は設けない (個人絶対 path は
# 公開 repo に書くべきでない)。
PATH_HITS="$(
  printf '%s' "$CONTENT" \
    | grep -oE '/Users/[a-z][a-z0-9_-]*' 2>/dev/null \
    | sort -u \
    || true
)"
if [ -n "$PATH_HITS" ]; then
  HITS="${HITS}
[abs_path] $(printf '%s' "$PATH_HITS" | head -3 | tr '\n' ' ')"
fi

# --- 3. ipv4 ---
# dotted quad を検出し、allowlist で除外。allowlist:
#   - 0.0.0.0                (wildcard)
#   - 127.x                  (loopback)
#   - 255.255.255.255        (broadcast)
#   - 10.x                   (RFC1918)
#   - 172.{16..31}.x         (RFC1918)
#   - 192.168.x              (RFC1918)
#   - 169.254.x              (link-local)
IPV4_ALL="$(
  printf '%s' "$CONTENT" \
    | grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' 2>/dev/null \
    || true
)"
IPV4_HITS=""
if [ -n "$IPV4_ALL" ]; then
  while IFS= read -r ip; do
    [ -z "$ip" ] && continue
    case "$ip" in
      0.0.0.0|255.255.255.255) continue ;;
      127.*|10.*|192.168.*|169.254.*) continue ;;
      172.16.*|172.17.*|172.18.*|172.19.*|172.2[0-9].*|172.3[01].*) continue ;;
    esac
    IPV4_HITS="${IPV4_HITS}${ip}
"
  done <<< "$IPV4_ALL"
fi
if [ -n "$IPV4_HITS" ]; then
  HITS="${HITS}
[ipv4] $(printf '%s' "$IPV4_HITS" | sort -u | head -3 | tr '\n' ' ')"
fi

# --- 4. token_prefix ---
# 長さ 30+ の prefix-match 強制で docs の例示 (e.g. "ghp_...") を避ける。
TOKEN_HITS="$(
  printf '%s' "$CONTENT" \
    | grep -oE '(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,})' 2>/dev/null \
    | sort -u \
    || true
)"
if [ -n "$TOKEN_HITS" ]; then
  # 本体は晒さず pattern 名と prefix のみを表示 (token 自体は leak の物)
  TOKEN_REDACTED="$(printf '%s' "$TOKEN_HITS" | head -3 | sed -E 's/^(.{10}).*/\1.../')"
  HITS="${HITS}
[token_prefix] $TOKEN_REDACTED"
fi

# --- 5. discord_mention ---
# Discord snowflake user (`<@NNN>`) or role (`<@&NNN>`) mention.
# Fields like mention_target / notify_user 等は application config の顔
# をしていても中身は persistent cross-server PII (dox 素材になりうる)。
# allowlist を設けない: `<@USER_ID>` のような placeholder は数字部分が
# 17 桁以上にならないため regex に hit しない。
DISCORD_HITS="$(
  printf '%s' "$CONTENT" \
    | grep -oE '<@&?[0-9]{17,20}>' 2>/dev/null \
    | sort -u \
    || true
)"
if [ -n "$DISCORD_HITS" ]; then
  HITS="${HITS}
[discord_mention] $(printf '%s' "$DISCORD_HITS" | head -3 | tr '\n' ' ')"
fi

# ----------------------------------------------------------------------
# 判定と出力
# ----------------------------------------------------------------------
if [ -z "$HITS" ]; then
  exit 0  # silent pass
fi

# hit ありならユーザー確認 (permissionDecision=ask)
cat >&2 << EOF
[public-leak-guard] 公開リポへの書き込みに Tier A 構造制約 hit:

対象ファイル: $FILE_PATH
repo root:    $REPO_ROOT
hit pattern(s):$HITS

本 repo は .claude/public-repo.marker で public と宣言されています。
上記は email / 絶対 path / 非 private IPv4 / token prefix に該当する
構造で、通常 public repo に書くべきでない値です。

書き込んで良い場合のみ承認してください。判断に迷う場合は:
  - email → placeholder または noreply allowlist へ
  - /Users/<name>/ → \`\$HOME/\` or \`~/\` 相対 path へ
  - IPv4 → 0.0.0.0 / 127.0.0.1 / RFC1918 の汎用例示 IP へ
  - token → 即 revoke + secret manager へ移動
  - discord_mention → layer 3 (collaborator registry) に canonical を置き、
    config は \`mention_target_env: DISCORD_MENTION_<NAME>\` で env 変数名のみ保持
    (詳細: \`conventions/identity-in-config.md\`)
EOF

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask"
  }
}'
exit 0
