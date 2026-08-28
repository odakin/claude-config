#!/usr/bin/env bash
# audit-public-repos.sh — 全 public repo の leak 定期監査（週次 scheduled-task 対象）
# audit-public-repos.sh — public repo 群の leak 監査
#
# 動作:
#   1. `gh repo list --visibility public` で public repo 一覧取得
#   2. `~/Claude/<name>/` に存在する repo を対象に絞る
#   3. 各対象 repo で:
#        a. `.claude/public-repo.marker` の有無 (missing は warn)
#        b. Tier A 構造制約 regex (public-leak-guard.sh と同じ 5 種)
#           を `git grep -nE` で適用
#        c. 個人層の `sensitive-terms.txt` (= lib/find-personal-layer.sh で動的解決、
#           foreign user では個人層なし → 空文字列でこのチェックは skip) が存在
#           すれば ephemeral に `git grep -nFf` で literal check
#   4. 結果を `/tmp/public-leak-audit-<YYYYMMDD-HHMMSS>.md` に出力
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
REPORT="$(mktemp /tmp/public-leak-audit-XXXXXX.md)"
chmod 600 "$REPORT"

# Tier A regex (public-leak-guard.sh と同じ。
# 各 pattern を個別に `git grep -nE` して後で allowlist 除外する)
EMAIL_RE='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
PATH_RE='/Users/[a-z][a-z0-9_-]*'
IPV4_RE='([0-9]{1,3}\.){3}[0-9]{1,3}'
TOKEN_RE='(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,})'
DISCORD_ID_RE='<@&?[0-9]{17,20}>'

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

  # Tier A scan
  repo_hits=""

  # email (with allowlist filter)
  email_raw="$(git -C "$repo" grep -nE "$EMAIL_RE" 2>/dev/null \
    | grep -vE '(noreply@anthropic\.com|noreply@github\.com|support@github\.com|[A-Za-z0-9._%+-]+@example\.(com|org|net|invalid))' \
    || true)"
  if [ -n "$email_raw" ]; then
    repo_hits="${repo_hits}

### [tier-a/email]
\`\`\`
$(printf '%s\n' "$email_raw" | head -20)
\`\`\`"
  fi

  # /Users/<name>
  path_raw="$(git -C "$repo" grep -nE "$PATH_RE" 2>/dev/null || true)"
  if [ -n "$path_raw" ]; then
    repo_hits="${repo_hits}

### [tier-a/abs_path]
\`\`\`
$(printf '%s\n' "$path_raw" | head -20)
\`\`\`"
  fi

  # IPv4 (post-filter allowlist)
  ipv4_raw="$(git -C "$repo" grep -nE "$IPV4_RE" 2>/dev/null || true)"
  ipv4_filtered=""
  if [ -n "$ipv4_raw" ]; then
    while IFS= read -r line; do
      # line: path:line:content. IP を抽出して allowlist 判定。
      ip="$(printf '%s' "$line" | grep -oE "$IPV4_RE" | head -1)"
      [ -z "$ip" ] && continue
      case "$ip" in
        0.0.0.0|255.255.255.255) continue ;;
        127.*|10.*|192.168.*|169.254.*) continue ;;
        172.16.*|172.17.*|172.18.*|172.19.*|172.2[0-9].*|172.3[01].*) continue ;;
      esac
      ipv4_filtered="${ipv4_filtered}${line}
"
    done <<< "$ipv4_raw"
  fi
  if [ -n "$ipv4_filtered" ]; then
    repo_hits="${repo_hits}

### [tier-a/ipv4]
\`\`\`
$(printf '%s' "$ipv4_filtered" | head -20)
\`\`\`"
  fi

  # discord_mention (Discord snowflake `<@NNN>` / `<@&NNN>`)
  discord_raw="$(git -C "$repo" grep -nE "$DISCORD_ID_RE" 2>/dev/null || true)"
  if [ -n "$discord_raw" ]; then
    repo_hits="${repo_hits}

### [tier-a/discord_mention]
\`\`\`
$(printf '%s\n' "$discord_raw" | head -20)
\`\`\`"
  fi

  # token prefix
  token_raw="$(git -C "$repo" grep -nE "$TOKEN_RE" 2>/dev/null || true)"
  if [ -n "$token_raw" ]; then
    # 本体 redact: 先頭 10 文字以降を伏せる
    token_redacted="$(printf '%s\n' "$token_raw" \
      | sed -E "s/(ghp_[A-Za-z0-9]{6}|github_pat_[A-Za-z0-9_]{4}|sk-[A-Za-z0-9]{6})[A-Za-z0-9_]+/\1.../g")"
    repo_hits="${repo_hits}

### [tier-a/token_prefix]
\`\`\`
$(printf '%s\n' "$token_redacted" | head -20)
\`\`\`"
  fi

  # Tier B literal (sensitive-terms.txt, ephemeral)
  if [ -f "$SENSITIVE_TERMS" ] && [ -s "$SENSITIVE_TERMS" ]; then
    literal_raw="$(git -C "$repo" grep -nFf "$SENSITIVE_TERMS" 2>/dev/null || true)"
    if [ -n "$literal_raw" ]; then
      # 本体を晒さず「何行 hit、どのファイルか」のみ
      literal_count="$(printf '%s\n' "$literal_raw" | wc -l | tr -d ' ')"
      literal_files="$(printf '%s\n' "$literal_raw" | awk -F: '{ print $1 }' | sort -u | head -20)"
      repo_hits="${repo_hits}

### [tier-b/literal]
${literal_count} line(s) matched sensitive-terms.txt in:
\`\`\`
$(printf '%s\n' "$literal_files")
\`\`\`"
    fi
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

# exit code: 0 clean, 1 hits, 2 missing markers
if [ "$TOTAL_HITS" -gt 0 ]; then
  exit 1
fi
if [ "$MISSING_MARKER_COUNT" -gt 0 ]; then
  exit 2
fi
exit 0
