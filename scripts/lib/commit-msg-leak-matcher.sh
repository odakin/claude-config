#!/bin/bash
# commit-msg-leak-matcher.sh — sourceable matcher library
#
# 正本: claude-config/scripts/lib/commit-msg-leak-matcher.sh
#
# 用途: commit message から leak 候補 (= 非例外 private repo 名 +
# sensitive-terms.txt literal) を検出する共通 matcher。 2 caller がある:
#
#   (1) odakin-prefs/hooks/commit-msg-leak-guard.sh (= claude-code PreToolUse
#       Bash hook、 warn mode、 message は Bash 引数 `git commit -m "..."`
#       から抽出)
#   (2) claude-config/scripts/commit-msg-leak-guard-runner.sh (= git native
#       commit-msg hook、 BLOCK mode、 message は git が渡す $1
#       (.git/COMMIT_EDITMSG path) から読む)
#
# 2 caller で matcher logic を duplicate すると drift する (= sensitive-terms.txt
# 参照方式 + allowlist 7 件 + repo 名抽出 regex の同期保証が破綻)、 そのため
# library 化して同じ logic を両方が source する DRY design。
#
# Layer placement: 本 file は layer 1 (claude-config public)。 algorithm 自体
# (= regex pattern + 7 allowlist 名) は public-safe (= 7 allowlist 名は既に
# claude-config/CLAUDE.md §例外 list で public 化済)。 layer 3 data
# (= repos.md / sensitive-terms.txt) は find-personal-layer.sh の cascade で
# 動的解決、 layer 1 source に literal は埋め込まない。
#
# 使い方 (source して call):
#
#   . "$(dirname "$0")/lib/commit-msg-leak-matcher.sh"
#   MESSAGE="$(cat /path/to/msg)"
#   run_leak_matcher "$MESSAGE"
#   if [ -n "$LEAK_MATCHER_HITS" ]; then
#     echo "leak detected:$LEAK_MATCHER_HITS"
#     exit 1
#   fi
#
# 出力: グローバル変数 `LEAK_MATCHER_HITS` に hit summary を set (= 文字列、
# 空なら hit なし)。 hit detail format は人間可読 (= "[repo-name] X Y" 等)。
#
# 依存: bash 3.2 (= macOS stock)、 grep、 sed、 wc。 find-personal-layer.sh
# は本 library と同 dir (lib/) に存在 (= source 済前提)。
#
# 設計 notes:
#   - 8 allowlist 名 (= gmail-mcp-config / research-collab / email-office /
#     odakin-prefs / secrets-config / physics-research / conferences / 推薦書) は本 file
#     に literal embed。 これらは既に claude-config/CLAUDE.md §例外 list で public、
#     leak 軸の問題なし。 list 変更時は両方を sync (= §10 4 軸 sweep 義務)
#   - repos.md 内 format: `| \`<repo>/\` | <desc> | private[ (...)] |` の
#     table 行を grep。 future schema 変更時に regex 適用範囲が壊れる
#     可能性、 grep 結果 0 件なら matcher (b) は skip (= fail-open)

# ====================================================================
# allowlist: claude-config/CLAUDE.md §例外 list と sync
# ====================================================================
LEAK_MATCHER_ALLOWLIST="gmail-mcp-config research-collab email-office odakin-prefs secrets-config physics-research conferences 推薦書"

# ====================================================================
# main entry point
#   $1: commit message (= 多 line 可、 改行含む)
# 結果: LEAK_MATCHER_HITS グローバル変数を set
# ====================================================================
run_leak_matcher() {
  local message="$1"
  local personal_layer sensitive_terms repos_md
  local literal_hits hit_count
  local private_repos filtered_repos repo skip allow
  local repo_hits path_hits

  LEAK_MATCHER_HITS=""

  [ -n "$message" ] || return 0

  # find-personal-layer.sh は本 file と同 dir (lib/) に存在
  if [ -z "${LEAK_MATCHER_PERSONAL_LAYER_LOADED:-}" ]; then
    . "$(dirname "${BASH_SOURCE[0]}")/find-personal-layer.sh"
    LEAK_MATCHER_PERSONAL_LAYER_LOADED=1
  fi
  personal_layer="$(find_personal_layer)"

  # foreign user (= personal layer なし) では layer 3 data 参照不可、 全 skip
  [ -n "$personal_layer" ] || return 0

  # ----------------------------------------------------------------
  # (a) sensitive-terms.txt literal match
  # ----------------------------------------------------------------
  sensitive_terms="$personal_layer/sensitive-terms.txt"
  if [ -s "$sensitive_terms" ]; then
    literal_hits="$(
      printf '%s' "$message" \
        | grep -Ff "$sensitive_terms" 2>/dev/null \
        | head -5 \
        || true
    )"
    if [ -n "$literal_hits" ]; then
      hit_count="$(printf '%s\n' "$literal_hits" | wc -l | tr -d ' ')"
      # 表示時も literal 本体を晒さず count のみ (= public-precommit-runner.sh
      # の Tier B 方針と一致)
      LEAK_MATCHER_HITS="${LEAK_MATCHER_HITS}
  [literal] ${hit_count} line(s) match sensitive-terms.txt"
    fi
  fi

  # ----------------------------------------------------------------
  # (b) 非例外 private repo 名 (whole-word match)
  # ----------------------------------------------------------------
  repos_md="$personal_layer/repos.md"
  filtered_repos=""
  repo_hits=""
  if [ -f "$repos_md" ]; then
    private_repos="$(
      grep -E '^\| `[^`]+/?`' "$repos_md" 2>/dev/null \
        | grep -E '\| *private' \
        | sed -E 's/^\| `([^/`]+)\/?`.*/\1/' \
        | sort -u \
        || true
    )"

    while IFS= read -r repo; do
      [ -n "$repo" ] || continue
      skip=0
      for allow in $LEAK_MATCHER_ALLOWLIST; do
        if [ "$repo" = "$allow" ]; then
          skip=1; break
        fi
      done
      [ "$skip" = "1" ] && continue
      filtered_repos="${filtered_repos}${repo}
"
    done <<< "$private_repos"

    while IFS= read -r repo; do
      [ -n "$repo" ] || continue
      case "$repo" in
        *[!\ -~]*)
          # 非 ASCII (= 日本語等): 単純含有判定 (boundary 概念不明確、 false
          # positive 多めだが OK)
          if printf '%s' "$message" | grep -qF -- "$repo" 2>/dev/null; then
            repo_hits="${repo_hits}${repo} "
          fi
          ;;
        *)
          # ASCII: word boundary
          if printf '%s' "$message" \
              | grep -qE "(^|[^A-Za-z0-9_-])${repo}([^A-Za-z0-9_-]|$)" 2>/dev/null; then
            repo_hits="${repo_hits}${repo} "
          fi
          ;;
      esac
    done <<< "$filtered_repos"

    if [ -n "$repo_hits" ]; then
      LEAK_MATCHER_HITS="${LEAK_MATCHER_HITS}
  [repo-name] $repo_hits"
    fi
  fi

  # ----------------------------------------------------------------
  # (c) ~/Claude/<X>/ path pattern (X ∈ filtered_repos)
  # (b) で hit したら (c) は冗長 (= 同 evidence)、 skip
  # ----------------------------------------------------------------
  path_hits=""
  if [ -z "$repo_hits" ] && [ -n "$filtered_repos" ]; then
    while IFS= read -r repo; do
      [ -n "$repo" ] || continue
      if printf '%s' "$message" \
          | grep -qE "~/Claude/${repo}/|/Users/[^/]+/Claude/${repo}/" 2>/dev/null; then
        path_hits="${path_hits}~/Claude/${repo}/ "
      fi
    done <<< "$filtered_repos"

    if [ -n "$path_hits" ]; then
      LEAK_MATCHER_HITS="${LEAK_MATCHER_HITS}
  [repo-path] $path_hits"
    fi
  fi
}
