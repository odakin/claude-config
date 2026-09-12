#!/usr/bin/env bash
# commit-msg-leak-matcher.sh — commit message leak matcher (= sensitive-terms.txt + repos.md private list - 8 allowlist の (a)(b)(c) check + 審査中の申請を識別する種目語×評価語の共起 (d))、 claude-code hook + git-side runner の両方が source する DRY 実装
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
  #
  # Word-boundary semantics (2026-06-29 sibling fix with
  # public-precommit-runner.sh Tier B):
  #   - ASCII-only term: grep -wF (word-boundary)、 短 ASCII token の
  #     substring FP class (= 例: arxiv 英文 abstract 内の longer word に
  #     偶然一致) を消す
  #   - 非 ASCII term (日本語等): grep -F (substring) を維持、 CJK は
  #     word 境界 ill-defined ゆえ -w 一律適用は破壊的
  # ----------------------------------------------------------------
  sensitive_terms="$personal_layer/sensitive-terms.txt"
  if [ -s "$sensitive_terms" ]; then
    local ascii_terms na_terms ascii_hits na_hits
    ascii_terms="$(mktemp)"
    na_terms="$(mktemp)"
    awk -v a="$ascii_terms" -v n="$na_terms" '
      /^[[:space:]]*$/ { next }
      /^[[:space:]]*#/ { next }
      /^[ -~]+$/      { print > a; next }
                      { print > n }
    ' "$sensitive_terms"

    ascii_hits=""
    if [ -s "$ascii_terms" ]; then
      ascii_hits="$(
        printf '%s' "$message" \
          | grep -wFf "$ascii_terms" 2>/dev/null \
          || true
      )"
    fi
    na_hits=""
    if [ -s "$na_terms" ]; then
      na_hits="$(
        printf '%s' "$message" \
          | grep -Ff "$na_terms" 2>/dev/null \
          || true
      )"
    fi
    rm -f "$ascii_terms" "$na_terms"

    literal_hits="$(
      {
        [ -n "$ascii_hits" ] && printf '%s\n' "$ascii_hits"
        [ -n "$na_hits" ]    && printf '%s\n' "$na_hits"
      } | sed '/^$/d' | head -5
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

  # ----------------------------------------------------------------
  # (d) 審査軸 — 審査中の申請の「種目 × 評価」 共起 (2026-09-12)
  #
  # (a) の sensitive-terms.txt は個人情報と infra の語が対象で、 **審査を受けて
  # いる申請を識別する語は射程外**だった。 実害: 公開 repo の commit message に
  # 種目名と模擬審査の評点の実数が入り、 本文を一般形に直しても message 経由で
  # 相殺される状態で push 済になった (2026-09-12、 履歴は owner 判断で据え置き)。
  #
  # 判定は **共起** で行う。 単独語では切れないため:
  #   - 種目名だけ → 規約 doc が制度一般を論じる正当な文で頻出 (FP 過多)
  #   - 評価語だけ → 審査 process の方法論を書く文で頻出 (同上)
  #   - 近接 (評価語 → 数字) → 「Stage 1 の評点」 のような段階番号で FP
  #     (実測: 実際の sanitize 後 message がこれで落ちた)
  # 種目名と評価語が同じ message に同居して初めて「特定の申請への評価」 になる。
  #
  # 層: **種目名は値なので個人層** ($personal_layer/review-instance-terms.txt、
  # 無ければ本 check は skip)。 評価語は制度に依らない一般語なので本 file が持つ。
  # ----------------------------------------------------------------
  local review_terms subject_hit ra_terms rn_terms
  review_terms="$personal_layer/review-instance-terms.txt"
  if [ -s "$review_terms" ]; then
    ra_terms="$(mktemp)"; rn_terms="$(mktemp)"
    awk -v a="$ra_terms" -v n="$rn_terms" '
      /^[[:space:]]*$/ { next }
      /^[[:space:]]*#/ { next }
      /^[ -~]+$/      { print > a; next }
                      { print > n }
    ' "$review_terms"
    subject_hit=""
    if [ -s "$ra_terms" ]; then
      subject_hit="$(printf '%s' "$message" | grep -owFf "$ra_terms" 2>/dev/null | sort -u | head -3 || true)"
    fi
    if [ -z "$subject_hit" ] && [ -s "$rn_terms" ]; then
      subject_hit="$(printf '%s' "$message" | grep -owFf "$rn_terms" 2>/dev/null | sort -u | head -3 || true)"
      [ -n "$subject_hit" ] || subject_hit="$(printf '%s' "$message" | grep -oFf "$rn_terms" 2>/dev/null | sort -u | head -3 || true)"
    fi
    rm -f "$ra_terms" "$rn_terms"
    if [ -n "$subject_hit" ] \
        && printf '%s' "$message" \
             | grep -qE '評点|評定|採点|点数|スコア|score|採否|採択可否|不採択' 2>/dev/null; then
      LEAK_MATCHER_HITS="${LEAK_MATCHER_HITS}
  [review-instance] 種目名 × 評価語の共起 ($(printf '%s' "$subject_hit" | tr '\n' ' '))— 公開面に特定の申請への評価が出る"
    fi
  fi
}
