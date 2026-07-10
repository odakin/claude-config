#!/usr/bin/env bash
# google-url-guard.sh — Google URL 安定性ガード — PreToolUse(Edit|Write|MultiEdit|Bash): /u/N/ 禁止 + `?authuser=<email>` 必須
# google-url-guard.sh — Google URL の安定性 / 多アカウント対応をガード
#
# 正本: claude-config/hooks/google-url-guard.sh
# setup.sh が ~/.claude/hooks/ に symlink を作成 (Step 2 の Installing Claude Code hooks)
#
# 対象: PreToolUse (Edit | Write | MultiEdit | Bash)
# 動作: tool_input 内に以下のいずれかが含まれていたら permissionDecision=ask
#       でユーザー確認を仰ぐ:
#       (A) Google URL の /u/N/ パターン (account slot index)
#       (B) Account-sensitive な Google URL に ?authuser=<email> が無い
#
# Why:
#   /u/N/ はブラウザの Google アカウント追加順に依存し、別マシン・
#   再ログインで壊れる不安定 URL。authuser=<email> はマルチアカウント
#   ユーザー (= 同じブラウザに複数の Google アカウントをログイン) で
#   どのアカウント (= 誰の view) で開くかを決定論的に指定する。stable ID
#   だけでは active account 依存で壊れる (= 別アカウントが active なら
#   access 権が無く 404 / 別 view が開く)。
#
#   2026-04-16: /u/N/ で 2 回再発、機械的ブロック導入
#   2026-05-09: Classroom URL で authuser= 抜け再発、本検出を追加
#
#   convention (google-url.md) と CLAUDE.md inline ルールが両方あっても
#   Claude が読まないことがあるため、機械的にブロックする。
#
# 正しい代替:
#   - Stable ID + authuser=<email>:
#       classroom.google.com/c/{id}?authuser=<email>
#       docs.google.com/document/d/{id}/edit?authuser=<email>
#       drive.google.com/file/d/{id}?authuser=<email>
#   - Gmail (stable URL 不在): mail.google.com/mail/u/?authuser=<email>#<view>
#   - Account-less root: classroom.google.com/, mail.google.com/mail/
#     (current active account で開く、決定論性を諦めた場合のみ)
#
# Single-account user 向け注: authuser= 無しでも動くが、後で multi-account
# になった瞬間に壊れる pre-emptive 規律。permissionDecision=ask なので毎回
# allow すれば通せる。
#
# 依存: jq (なければ fail-open で exit 0)

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

INPUT="$(cat)"
[ -z "$INPUT" ] && exit 0

CONTENT="$(printf '%s' "$INPUT" | jq -r '.tool_input | tostring' 2>/dev/null || true)"
[ -z "$CONTENT" ] && exit 0

# 早期脱出: google.com / googleapis.com を含まなければスキップ
case "$CONTENT" in
  *google.com*|*googleapis.com*) ;;
  *) exit 0 ;;
esac

# ---------- (A) /u/N/ slot index pattern ----------
SLOT_HITS=$(
  printf '%s' "$CONTENT" \
    | grep -oE '(google\.com|googleapis\.com)[^[:space:]]*\/u\/[0-9]+\/' 2>/dev/null \
    | head -5 \
    || true
)

# ---------- (B) account-sensitive Google URLs missing authuser= ----------
# 1) すべての Google URL を broad regex で抽出
#    URL terminator: 空白, ", <, >, ), ', `, |, {, } (= placeholder URL `{classId}` を排除するため)
ALL_GOOGLE_URLS=$(
  printf '%s' "$CONTENT" \
    | grep -oE 'https?://[a-z]+\.google\.com/[^[:space:]"<>){}`|]+' 2>/dev/null \
    || true
)

# 2) bash case glob で account-sensitive な URL のみフィルタ + authuser= 有無 check
#    case glob で path 末尾に実 ID 文字 ([A-Za-z0-9_-] 等) を必須化することで、
#    `https://classroom.google.com/c/{classId}` 型 placeholder (regex で `{` 直前で
#    切れて `https://classroom.google.com/c/` になる) を skip する。
ACCOUNT_SENSITIVE_HITS=""
while IFS= read -r url; do
  [ -z "$url" ] && continue

  # account-sensitive な service path のみ対象 (root URL や placeholder は除外)
  case "$url" in
    *mail.google.com/mail/[a-z]*) ;;                                                          # gmail (root /mail/ は除外、/mail/u/...|/mail/inbox 等)
    *classroom.google.com/c/[A-Za-z0-9_-]*|*classroom.google.com/a/[A-Za-z0-9_-]*) ;;         # classroom
    *drive.google.com/file/d/[A-Za-z0-9_-]*|*drive.google.com/drive/folders/[A-Za-z0-9_-]*) ;;  # drive
    *docs.google.com/document/d/[A-Za-z0-9_-]*|*docs.google.com/spreadsheets/d/[A-Za-z0-9_-]*|*docs.google.com/presentation/d/[A-Za-z0-9_-]*) ;;  # docs/sheets/slides
    *calendar.google.com/calendar/[a-z]*) ;;                                                  # calendar (/calendar/r, /calendar/u/N/ 等)
    *photos.google.com/album/[A-Za-z0-9_-]*|*photos.google.com/share/[A-Za-z0-9_-]*|*photos.google.com/photo/[A-Za-z0-9_-]*) ;;  # photos
    *meet.google.com/[a-z]*) ;;                                                               # meet (/lookup/<code>, /<code>)
    *) continue ;;
  esac

  # authuser= があれば OK
  case "$url" in
    *authuser=*) ;;
    *)
      ACCOUNT_SENSITIVE_HITS="$ACCOUNT_SENSITIVE_HITS$url
"
      ;;
  esac
done <<< "$ALL_GOOGLE_URLS"

ACCOUNT_SENSITIVE_HITS=$(printf '%s' "$ACCOUNT_SENSITIVE_HITS" | head -5)

# どちらも hit なし → exit 0
if [ -z "$SLOT_HITS" ] && [ -z "$ACCOUNT_SENSITIVE_HITS" ]; then
  exit 0
fi

# ---------- error message ----------
{
  if [ -n "$SLOT_HITS" ]; then
    echo "[google-url-guard] Google URL に /u/N/ パターン検出 (account slot は不安定):"
    echo ""
    printf '%s\n' "$SLOT_HITS"
    echo ""
  fi

  if [ -n "$ACCOUNT_SENSITIVE_HITS" ]; then
    echo "[google-url-guard] account-sensitive な Google URL に ?authuser=<email> 無し:"
    echo ""
    printf '%s\n' "$ACCOUNT_SENSITIVE_HITS"
    echo ""
  fi

  cat << 'EOF'
代替: stable ID + ?authuser=<email> を付ける。
  classroom.google.com/c/{id}?authuser=<email>
  docs.google.com/document/d/{id}/edit?authuser=<email>
  mail.google.com/mail/u/?authuser=<email>#inbox
詳細: claude-config/conventions/google-url.md
EOF
} >&2

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask"
  }
}'
exit 0
