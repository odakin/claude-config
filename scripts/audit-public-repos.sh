#!/usr/bin/env bash
# audit-public-repos.sh — 全 public repo の leak 定期監査（週次 scheduled-task 対象）
# audit-public-repos.sh — public repo 群の leak 監査
#
# 動作:
#   1. `gh repo list --visibility public` で public repo 一覧取得
#   2. `~/Claude/<name>/` に存在する repo を対象に絞る
#   3. 各対象 repo で:
#        a. `.claude/public-repo.marker` の有無 (missing は warn)
#        b. 中身は scan-public-tree.sh --force に委ねる (= commit gate と同じ runner に tree 全体を通す。
#           Tier A-E + 受理一覧 + generated: 宣言 + 公刊済みの書誌 + 許可複合語が gate と同じに効く)
#   4. 結果を `$TMPDIR/public-leak-audit-XXXXXX` (markdown) に出力
#   5. missing marker と発見 hit を summary として stdout にも出す
#
# 運用:
#   - 初回: 手動実行して既存 leak を洗い出す
#   - 以降: scheduled-task の週次実行で定期 sweep
#   - 発見 leak は個人層の `leak-incidents.md` (あれば) に追記する判断
#     (修正 / 受容 / 素材移動) を user が実施
#
# 設計:
#   - 本 script は script source に literal も特定の個人層名も埋め込まない。
#     sensitive-terms.txt は grep -Ff でファイル参照するのみ、 個人層 path は
#     lib/find-personal-layer.sh で動的解決。
#   - `gh repo list` で列挙される public repo には認証 gh user 所有分のみ
#     含まれる。 他 org の public repo (= 共同研究 org 等) は owner=current
#     user では出てこないので、 local checkout に marker を持つ repo を
#     追加で scan する方式で補完する。
#
# 現 scope の限界 (= 2026-05-26 noted):
#   - 本 audit は **file 本文** (= working tree の `git grep`) のみ scan。
#     commit message + subject の leak (= `git log --format=%B` 経由検出) は
#     現 scope 外。 後者は 2-layer 防御の commit 時 gate (=
#     `commit-msg-leak-guard-runner.sh`、 BLOCK mode) で予防、 過去 commit の
#     retrospective surface は `odakin-prefs/scripts/unified-dashboard.py` の
#     `check_leak_repair_commits()` (= leak repair commit trend monitor) が
#     partial cover。 message 本文の literal scan を本 audit に追加する case は
#     future enhancement (= shared matcher library を git log 出力に適用)。

set -uo pipefail

HOME_CLAUDE="$HOME/Claude"

# 個人層の sensitive-terms.txt を動的解決。
# foreign user (個人層なし) では空文字列 → 後段の [ -f "$SENSITIVE_TERMS" ] で skip。
. "$(dirname "$0")/lib/find-personal-layer.sh"
PERSONAL_LAYER="$(find_personal_layer)"
SENSITIVE_TERMS=""
if [ -n "$PERSONAL_LAYER" ]; then
  SENSITIVE_TERMS="$PERSONAL_LAYER/sensitive-terms.txt"
fi
# mktemp で unpredictable filename + owner-only permission
# ⚠️ template の X は末尾に置く。 BSD (macOS) の mktemp は `XXXXXX.md` の X を置換せず literal の名前で作るので、
# 2 回目以降は「File exists」 で REPORT が空になり、 報告の書き込みが全部失敗していた (実測)
REPORT="$(mktemp "${TMPDIR:-/tmp}/public-leak-audit-XXXXXX")" || { echo "audit-public-repos.sh: mktemp failed" >&2; exit 3; }   # 3 = 監査自体が走らなかった (2 は marker 欠落)
chmod 600 "$REPORT"


# ----------------------------------------------------------------------
# Target repos enumeration
# ----------------------------------------------------------------------
TARGETS_FILE="$(mktemp)"
trap 'rm -f "$TARGETS_FILE"' EXIT

# 1) 認証 gh user 所有の public repo のうち local に clone 済みのもの
if command -v gh >/dev/null 2>&1; then
  gh repo list --visibility public --limit 200 --json name --jq '.[].name' 2>/dev/null \
    | while IFS= read -r name; do
        [ -z "$name" ] && continue
        [ -d "$HOME_CLAUDE/$name/.git" ] && printf '%s\n' "$HOME_CLAUDE/$name"
      done >> "$TARGETS_FILE"
fi

# 2) local の他 org public repo (marker 持ち) を追加
#    gh list に出ない sogebu/LorentzArena 等を拾うための第二経路。
for d in "$HOME_CLAUDE"/*/; do
  [ -d "$d.git" ] || continue
  if [ -f "${d}.claude/public-repo.marker" ]; then
    # 正規化 (末尾 / を除去)
    printf '%s\n' "${d%/}"
  fi
done >> "$TARGETS_FILE"

# 重複排除
sort -u -o "$TARGETS_FILE" "$TARGETS_FILE"

# ----------------------------------------------------------------------
# Report initial
# ----------------------------------------------------------------------
{
  printf '# Public Repo Leak Audit — %s\n\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
  printf '**Targets** (%d):\n' "$(wc -l < "$TARGETS_FILE" | tr -d ' ')"
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    printf -- '- `%s`\n' "$t"
  done < "$TARGETS_FILE"
  printf '\n'
  if [ -f "$SENSITIVE_TERMS" ] && [ -s "$SENSITIVE_TERMS" ]; then
    printf '**Tier B literal check**: enabled (sensitive-terms.txt present)\n\n'
  else
    printf '**Tier B literal check**: DISABLED (no sensitive-terms.txt)\n\n'
  fi
} > "$REPORT"

# ----------------------------------------------------------------------
# Per-repo scan
# ----------------------------------------------------------------------
TOTAL_HITS=0
MISSING_MARKER_COUNT=0

while IFS= read -r repo; do
  [ -z "$repo" ] && continue
  name="$(basename "$repo")"
  marker_note=""

  # marker check
  if [ ! -f "$repo/.claude/public-repo.marker" ]; then
    marker_note=" — ⚠ MISSING MARKER"
    MISSING_MARKER_COUNT=$((MISSING_MARKER_COUNT + 1))
    # marker がなくても scan は続ける (既存 leak の把握のため)
  fi

  # 中身の検査は scan-public-tree.sh に委ねる = commit gate と同じ runner に tree 全体を通すので、
  # 受理一覧・generated: 宣言・公刊済みの書誌・許可複合語が gate と同じに効く。 以前は Tier A/B を
  # この script 独自の grep で持っていて gate より粗く (受理一覧を読まない・comment 行も term として照合)、
  # 毎週同じ誤検知で exit 1 になり、 数百 MB の報告を書いていた (実測)。 --force = 台帳の「走査済」 を無視
  # (= 週次の役割は gate を通らない書き込み 〔CI の bot commit・web 編集〕 の後追い)
  repo_hits=""
  scan_rc=0
  scan_out="$(bash "$(dirname "$0")/scan-public-tree.sh" --repo "$repo" --force --quiet 2>&1)" || scan_rc=$?
  if [ "$scan_rc" -eq 1 ]; then   # 0 = finding 無し / 2 = 対象外 (commit が無い等)
    repo_hits="

### [scan-public-tree] exit=${scan_rc}
\`\`\`
$(printf '%s\n' "$scan_out" | head -60)
\`\`\`"
  fi

  if [ -n "$repo_hits" ]; then
    printf '## `%s`%s\n%s\n\n' "$name" "$marker_note" "$repo_hits" >> "$REPORT"
    # hit count: 各 section の先頭 `### [...]` を数える
    section_count="$(printf '%s\n' "$repo_hits" | grep -c '^### \[' || echo 0)"
    TOTAL_HITS=$((TOTAL_HITS + section_count))
  else
    printf '## `%s`%s\n\n  clean ✓\n\n' "$name" "$marker_note" >> "$REPORT"
  fi

  # Marker missing の場合は注意書きを報告に追記 (scan の後に)
  if [ -n "$marker_note" ]; then
    {
      printf '  → Missing `.claude/public-repo.marker`. Recommend:\n'
      printf '%s\n' '    1. create marker (see templates or copy from another public repo)'
      printf '%s %s\n' '    2. run `install-public-precommit.sh`' "$repo"
      printf '%s %s\n\n' '    3. run `install-public-commit-msg.sh`' "$repo"
    } >> "$REPORT"
  fi
done < "$TARGETS_FILE"

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
{
  printf '\n---\n\n# Summary\n\n'
  printf -- '- Targets scanned: %d\n' "$(wc -l < "$TARGETS_FILE" | tr -d ' ')"
  printf -- '- Repos with hits (section count): %d\n' "$TOTAL_HITS"
  printf -- '- Missing markers: %d\n\n' "$MISSING_MARKER_COUNT"
  if [ "$TOTAL_HITS" -gt 0 ]; then
    printf 'Next step: review each `### [tier-...]` section above.\n'
    printf 'For each hit decide: **修正** / **受容** / **素材移動** and\n'
    printf 'append an entry to your personal layer leak-incidents.md (if maintained).\n'
  else
    printf 'No hits. All public repos clean ✓\n'
  fi
} >> "$REPORT"

# stdout summary
printf '[audit-public-repos] report: %s\n' "$REPORT"
printf '  targets: %s\n' "$(wc -l < "$TARGETS_FILE" | tr -d ' ')"
printf '  hit sections: %s\n' "$TOTAL_HITS"
printf '  missing markers: %s\n' "$MISSING_MARKER_COUNT"

# exit code: 0 clean, 1 hits, 2 missing markers, 3 = 監査自体が走らなかった (report を作れない)
if [ "$TOTAL_HITS" -gt 0 ]; then
  exit 1
fi
if [ "$MISSING_MARKER_COUNT" -gt 0 ]; then
  exit 2
fi
exit 0
