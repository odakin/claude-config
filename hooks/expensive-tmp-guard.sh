#!/bin/bash
# expensive-tmp-guard.sh — PreToolUse(Bash): Audiveris / oemer / ML training 系の -output /tmp/ パターンを検出して `permissionDecision: ask`
# expensive-tmp-guard.sh — 高コスト中間 artifact を /tmp に書く reflex を機械的に warn
#
# 正本: claude-config/hooks/expensive-tmp-guard.sh
# setup.sh が ~/.claude/hooks/ に symlink を作成 (Step 2 の Installing Claude Code hooks)
#
# 対象: PreToolUse (Bash)
# 動作: Bash command が以下のパターンに該当したら permissionDecision=ask
#       でユーザー確認を仰ぐ:
#       (A) `Audiveris` (case-insensitive) を含み、 かつ `-output /tmp/` または
#           `--output /tmp/` を含む
#       (B) `oemer` を含み、 かつ `-o /tmp/` または `--output-dir /tmp/` を含む
#       (C) ML 系 (= `python.*train|fit`) で `--checkpoint-dir /tmp/` または
#           `--output-dir /tmp/` を含む (= 弱検出、 false positive 許容)
#
# Why:
#   /tmp は macOS reboot で sweep される + 数日経過で OS の tmpcleaner 系
#   ジョブが消す可能性がある scratch 領域。 OCR engine / ML training script /
#   数値シミュレーションの **再生成に 5 分以上 + input state (DPI、 version、
#   `-constant` override 等) が再現困難** な artifact を /tmp に書くと、
#   reboot 後に再生成コストが大きく、 user / 後の Claude session に永続化を
#   後追い修復させる failure mode に陥る。
#
#   2026-05-10 楽譜分析 OCR pipeline で発生: Audiveris OCR 実験 8 retry を
#   /tmp/audiveris-{2400,4800}dpi-{p1,p12}-{retry,override}/ に出力 (= 各 .omr
#   生成 10〜90 分、 maxPixelCount / sheetStepTimeOut の -constant override
#   が必要)、 8 hours 後 user 指摘「永続化されとらんやん」 で発覚。 6.3 MB
#   をリポ内 scores/<work>-ocr-experiments/ へ後追い永続化。
#
#   convention (expensive-intermediate-artifacts.md) と CLAUDE.md inline
#   ルール §12 が両方あっても Claude が読まないことがあるため、 機械的に
#   警告する。 reflex 検出のみで、 ゲート質問の判断は依然として書き手の責務。
#
# 正しい代替:
#   楽譜・楽曲解析: `scores/<work>-<engine>-experiments/`
#   ML training:   `data/checkpoints/<run-id>/` または `experiments/<run-id>/`
#   数値シミュレーション: `data/runs/<config-hash>/`
#   OCR 一般:      `data/ocr-<engine>/<source>/`
#   詳細: claude-config/conventions/expensive-intermediate-artifacts.md
#
# 例外 (= 真の disposable で /tmp が正しい場合):
#   - PNG render (= pdftoppm / ghostscript) で input PDF から数秒〜数分で
#     再生成可能なもの: /tmp で OK、 本 hook は検出しない
#   - 1 回 quick test の Audiveris run で結果を 1 度見れば捨てるもの:
#     permissionDecision=ask なので「実験 1 回試行、 永続化対象外」 と
#     justify して allow すれば通せる
#
# 依存: jq (なければ fail-open で exit 0)

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

INPUT="$(cat)"
[ -z "$INPUT" ] && exit 0

# Bash tool の command 文字列を抽出
COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$COMMAND" ] && exit 0

# 早期脱出: /tmp/ を含まなければ skip
case "$COMMAND" in
  *"/tmp/"*) ;;
  *) exit 0 ;;
esac

# ---------- (A) Audiveris with -output /tmp/ ----------
# Audiveris は case-insensitive で match (= バイナリは Audiveris.app だが
# CLI で audiveris 別名で呼ぶケースもあるため両方)
AUDIVERIS_HIT=""
case "$COMMAND" in
  *[Aa]udiveris*)
    case "$COMMAND" in
      *"-output /tmp/"*|*"--output /tmp/"*|*"-output=/tmp/"*|*"--output=/tmp/"*)
        AUDIVERIS_HIT="yes"
        ;;
    esac
    ;;
esac

# ---------- (B) oemer with -o /tmp/ or --output-dir /tmp/ ----------
OEMER_HIT=""
case "$COMMAND" in
  *oemer*)
    case "$COMMAND" in
      *"-o /tmp/"*|*"--output-dir /tmp/"*|*"-o=/tmp/"*|*"--output-dir=/tmp/"*)
        OEMER_HIT="yes"
        ;;
    esac
    ;;
esac

# ---------- (C) ML training script with checkpoint to /tmp/ ----------
# 弱検出: python ... (train|fit|finetune|pretrain) ... --checkpoint-dir /tmp/...
# false positive 許容 (= permissionDecision=ask なので allow で通せる)
ML_HIT=""
case "$COMMAND" in
  *python*train*|*python*fit*|*python*finetune*|*python*pretrain*)
    case "$COMMAND" in
      *"--checkpoint-dir /tmp/"*|*"--output-dir /tmp/"*|*"--save-dir /tmp/"*|\
      *"--checkpoint-dir=/tmp/"*|*"--output-dir=/tmp/"*|*"--save-dir=/tmp/"*)
        ML_HIT="yes"
        ;;
    esac
    ;;
esac

# どれも hit なし → exit 0
if [ -z "$AUDIVERIS_HIT" ] && [ -z "$OEMER_HIT" ] && [ -z "$ML_HIT" ]; then
  exit 0
fi

# ---------- error message ----------
{
  echo "[expensive-tmp-guard] 高コスト中間 artifact を /tmp に書こうとしている:"
  echo ""
  if [ -n "$AUDIVERIS_HIT" ]; then
    echo "  検出: Audiveris -output /tmp/..."
  fi
  if [ -n "$OEMER_HIT" ]; then
    echo "  検出: oemer -o /tmp/... (または --output-dir /tmp/...)"
  fi
  if [ -n "$ML_HIT" ]; then
    echo "  検出: python *(train|fit|...) --checkpoint-dir /tmp/..."
  fi
  echo ""
  cat << 'EOF'
ゲート質問: この出力、 reboot 後に再生成すると 5 分以上かかるか?
            かつ input state (DPI / version / -constant override 等) が再現困難か?

  - Yes → リポ内に永続 placement、 + experiment context を記述する README.md 必須
  - No  → /tmp で OK (= ask に対して allow で通す)

リポ内 placement の例:
  楽譜・楽曲解析: scores/<work>-<engine>-experiments/
  ML training:   data/checkpoints/<run-id>/ または experiments/<run-id>/
  数値計算:      data/runs/<config-hash>/
  OCR 一般:      data/ocr-<engine>/<source>/

詳細: claude-config/conventions/expensive-intermediate-artifacts.md
EOF
} >&2

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask"
  }
}'
exit 0
