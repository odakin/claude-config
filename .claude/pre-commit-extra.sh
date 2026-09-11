#!/bin/bash
# .claude/pre-commit-extra.sh — claude-config 固有の pre-commit 規律 (検査 1-3・5 = 警告のみ / 検査 4 legacy gate = BLOCK)
#
# public-precommit-runner.sh が leak gate を pass 後に chain で呼ぶ (= 既存 channel への
# 相乗り。 新規 standalone 検出器 / dashboard 項目を増やさない)。 exit code は親に透過するが、
# 本 hook は **warning のみで常に exit 0** にして commit を止めない (= drift は annoyance 級で、
# convention-design-principles.md §9.1 〔= #blast-radius-triage〕 の triage に従い catastrophic 級の block を当てない)。
#
# 検査: (1) 生成 doc、(2) 自動生成 index、(3) Codex integration contract、(5) SESSION.md の行数を
#       その commit の瞬間・その本人へ warning で surface する。CI は (1)-(3) を BLOCK として実行する
#       (= doc 記載の recall 依存 trigger を機械発火に格上げ)。(5) は CI に無い (= 行数で red にしない)。
#
# 由来: DESIGN.md 2026-06-13「CONVENTIONS.md 冒頭の conventions/ 列挙」 の格上げ trigger の実体
#       (35→56 file の列挙 drift が ~2.5 ヶ月 silent 累積した RCA)。 2026-07-10 に comm ベースの
#       hook 内実装から generate-tree.py --check へ置換 (DESIGN.md 2026-07-10 参照)。
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ -d "$REPO_ROOT/conventions" ] || exit 0

warned=0

# --- 検査 1+2: 生成 doc の同期 (CLAUDE.md tree / CONVENTIONS.md 列挙 / conventions/README.md) ---
# 旧実装 (2026-06-13): 本 hook 内の comm ベース列挙照合 (存在のみ、 説明文 drift は検出外)。
# 2026-07-10 に scripts/generate-tree.py --check へ置換 (= 検出 logic の二重実装を解消 + 説明文
# レベルの drift も検出。 源 = conventions/*.md 冒頭 doc-meta + scripts/hooks の header 1 行目)。
GEN="$REPO_ROOT/scripts/generate-tree.py"
if [ -f "$GEN" ] && command -v python3 >/dev/null 2>&1; then
  if ! python3 "$GEN" --check >/dev/null 2>&1; then
    echo "⚠️  [claude-config] 生成 doc (CLAUDE.md tree / CONVENTIONS.md 列挙 / conventions/README.md) が源と drift:" >&2
    python3 "$GEN" --check 2>&1 | grep -v "in sync" | head -20 | sed 's/^/    /' >&2
    echo "    → python3 scripts/generate-tree.py --write で再生成 (警告のみ・commit は継続)" >&2
    warned=1
  fi
fi

# --- 検査 2: 自動生成 index の同期 (warn のみ) ---
# md に section を足して index 再生成を忘れる drift (実例: 2026-06-30 の §17/§8.16/§8.17 が
# principles index から ~10 日欠落) を commit の瞬間に surface する。 CI (checks.yml ->
# run-all-checks.sh) が push 後の block 層、 ここは commit 時の早期 warn 層 (二層は意図的)。
IDXGEN="$REPO_ROOT/scripts/generate-doc-index.py"
if [ -f "$IDXGEN" ] && command -v python3 >/dev/null 2>&1; then
  if ! python3 "$IDXGEN" --check-all "$REPO_ROOT" >/dev/null 2>&1; then
    echo "  ⚠️ [pre-commit-extra] 自動生成 index が md と OUT OF SYNC:" >&2
    python3 "$IDXGEN" --check-all "$REPO_ROOT" 2>&1 | grep "❌" | sed 's/^/    /' >&2
    echo "    → python3 scripts/generate-doc-index.py <doc.md> <doc.index.yaml> で再生成 (警告のみ・commit は継続)" >&2
    warned=1
  fi
fi

# --- 検査 3: Codex integration contract (warn のみ) ---
# 正本 pointer・SESSION の durable detail・旧 capability claim・Hook adapter contract を
# 軽量に照合する。詳細な判定は script に一本化し、ここへ再実装しない。
CODEX_GATE="$REPO_ROOT/scripts/check-codex-integration.py"
if [ -f "$CODEX_GATE" ] && command -v python3 >/dev/null 2>&1; then
  if ! python3 "$CODEX_GATE" --check >/dev/null 2>&1; then
    echo "  ⚠️ [pre-commit-extra] Codex integration contract が OUT OF SYNC:" >&2
    python3 "$CODEX_GATE" --check 2>&1 | sed 's/^/    /' >&2
    echo "    → python3 scripts/check-codex-integration.py --check で確認 (警告のみ・CI では BLOCK)" >&2
    warned=1
  fi
fi

# --- 検査 5: SESSION.md の行数 (warn のみ、 CI には無い) ---
# 目安 ~80 行 (CONVENTIONS.md#pre-push-check)。 2026-09-11 に 506 行まで育ってから縮退した。 byte では 91 KB =
# 個人層の肥大検出器の閾値 (150 KB) の遥か下で、 誰も見ていなかった。 staged の SESSION.md が SESSION_WARN_LINES
# 行以上なら、 追記した本人にその場で縮退の手順を案内する。 閾値 = 縮退直後の 47 行 (健康 floor) と数日分の追記
# では点かない位置 (conventions/memory-file-slimming.md#regrowth-backstop)。 同じ値を個人層の肥大検出器も持つ。
SESSION_WARN_LINES=100
if git -C "$REPO_ROOT" diff --cached --name-only -- SESSION.md | grep -qx 'SESSION.md'; then
  session_lines="$(git -C "$REPO_ROOT" show :SESSION.md 2>/dev/null | wc -l | tr -d ' ')"
  if [ -n "$session_lines" ] && [ "$session_lines" -ge "$SESSION_WARN_LINES" ]; then
    echo "  ⚠️ [pre-commit-extra] SESSION.md = $session_lines 行 (≥ $SESSION_WARN_LINES。 目安 ~80 = CONVENTIONS.md#pre-push-check):" >&2
    echo "    → 新 entry は「日付 + 何を + 正本への pointer」 の 1-3 行に。 経緯・実測は正本 doc か SESSION-archive.md へ MOVE (手順 = conventions/memory-file-slimming.md)" >&2
    warned=1
  fi
fi

if [ "$warned" -eq 1 ]; then
  echo "    (警告のみ・commit は継続)" >&2
fi

# --- 検査 4: legacy append-only (= 上の warn-only 群と違い BLOCK する例外) ---
# catastrophic 級: published §-number の転送先 (slug index の legacy 値) を黙って落とすと、
# 下層 repo / 他ユーザ / 過去メモの §-ref が永久に解決不能になる (= 回収不可)。 §9.1 triage で
# block。 staged の *.index.yaml を HEAD と比較し、 legacy が縮んでいたら commit を止める。 意図的な
# 節削除は `LEGACY_RETIRE_OK=1 git commit ...` で明示 override (= 消すのは可・黙っては不可)。
# 正本: scripts/check-legacy-append-only.py / convention-design-principles §14.7 (= #inbound-ref-robustness)。
GATE="$REPO_ROOT/scripts/check-legacy-append-only.py"
if [ -f "$GATE" ]; then
  if ! python3 "$GATE" --staged >&2; then
    exit 1
  fi
fi

exit 0
