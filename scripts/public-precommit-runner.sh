#!/usr/bin/env bash
# public-precommit-runner.sh — 公開リポ pre-commit gate（Tier A + sensitive-terms.txt ephemeral）
# public-precommit-runner.sh — 公開リポの pre-commit gate
#
# 正本: claude-config/scripts/public-precommit-runner.sh
# 各 public repo の .git/hooks/pre-commit に 1 行 stub が入り、この
# script を absolute path で exec する (install-public-precommit.sh 参照)。
#
# 動作:
#   1. stage 済みファイルを列挙 (`git diff --cached --name-only`)
#   2. 各ファイルの追加行 (`^+` で始まる、`+++` ヘッダ除く) を抽出
#   3. Tier A 構造制約 regex を適用:
#        - email (allowlist: noreply@anthropic.com / noreply@github.com
#          / support@github.com)
#        - /Users/<name> 絶対 path
#        - IPv4 (RFC1918 / loopback / link-local / broadcast allowlist)
#        - token prefix (ghp_ / github_pat_ / sk- + 30 文字以上)
#   4. 個人層の `sensitive-terms.txt` (= lib/find-personal-layer.sh で動的解決、
#      foreign user では個人層なし → 空文字列でこのチェックは skip) が存在すれば
#      ephemeral に load して追加行に対して `grep -F -f` で literal check
#      (本 script は sensitive-terms.txt の中身を memory 上に持たない。
#       grep プロセスに file path を渡すだけで直接 read しない)
#   5. hit があれば `exit 1` で commit を reject。詳細を stderr に出す
#   6. `--no-verify` で bypass 可能 (git 標準の escape hatch)
#   7. leak gate を pass したら、対象 repo に
#      `<repo_root>/.claude/pre-commit-extra.sh` (executable) があれば
#      call + `exit $?` で chain する (`exec` ではない理由は本体の
#      該当箇所コメント参照)。repo 固有の commit 規律 (placeholder
#      検出・SESSION.md 同期警告等) はこちらに置く。stub は触らずに
#      済むので install-public-precommit.sh の冪等性が保たれる
#
# 設計思想:
#   本 script は `sensitive-repo-patterns.ja.md §3-3` の批判 (b)
#   「blacklist 自体が leak 源」を、**hook 本体 (claude-config, public)
#   と literal data (個人層 (layer 3) の sensitive-terms.txt + gitignore で
#   隔離) の構造分離** で回避する。本 script source には literal も特定の
#   個人層名も埋め込まれない (= 個人層は lib/find-personal-layer.sh で動的解決)。
#   詳細は claude-config/DESIGN.md §公開リポ leak 防止。
#
# Sibling (= 2-layer 防御):
#   本 script は **file 本文** (= stage 済 file の追加行) を Tier A/B で scan する。
#   commit message + subject は別 hook `commit-msg-leak-guard-runner.sh` (BLOCK)
#   が cover (= 2026-05-26 追加、 claude-code 2.1.x harness invoke bug の
#   mitigation option B、 詳細 conventions/hook-authoring.md#delivery-audit-4-axes (d) + DESIGN.md
#   §2026-05-26)。 install は `install-public-precommit.sh` (= 本 stub) +
#   `install-public-commit-msg.sh` (= sibling stub) で setup.sh Step 8 内 1 loop
#   で同時 install。 2 hook の matcher logic は分離 (= Tier A regex vs commit-msg
#   shared library)、 cover 範囲も file body vs commit message で disjoint で
#   相補的 (= 過去 leak の 「file 本文 OK + commit message に leak」 死角を埋める)。

set -uo pipefail

# 個人層の sensitive-terms.txt を動的解決。
# foreign user (個人層なし) では空文字列 → 後段の [ -f "$SENSITIVE_TERMS" ] で skip。
. "$(dirname "$0")/lib/find-personal-layer.sh"
PERSONAL_LAYER="$(find_personal_layer)"
SENSITIVE_TERMS=""
if [ -n "$PERSONAL_LAYER" ]; then
  SENSITIVE_TERMS="$PERSONAL_LAYER/sensitive-terms.txt"
fi

# ----------------------------------------------------------------------
# Stage 済みファイルを列挙。削除済み (D)・merge commit は skip。
# ----------------------------------------------------------------------
STAGED="$(git diff --cached --name-status 2>/dev/null | awk '$1 != "D" { print $NF }')"
[ -z "$STAGED" ] && exit 0

# ----------------------------------------------------------------------
# Merge conflict marker gate (staged content 全体、 shared lib)。
# 検出 logic / escape hatch / 設計動機 (2026-07-10 = conflict marker 入り conventions/*.md
# が public repo に commit+push された実事故) の SoT = lib/staged-conflict-markers.sh header。
# lib 不在は skip (= fail-open、 leak gate 本体を壊さない)。
# ----------------------------------------------------------------------
CONFLICT_LIB="$(dirname "$0")/lib/staged-conflict-markers.sh"
if [ -f "$CONFLICT_LIB" ]; then
  . "$CONFLICT_LIB"
  if ! check_staged_conflict_markers; then
    exit 1
  fi
fi

# ----------------------------------------------------------------------
# 各ファイルの追加行を 1 つのバッファに集約 (file:line prefix 付き)
# `git diff --cached -U0 --no-color -- <file>` の出力から `+` 行を抜く。
# +++ ヘッダを除外し、先頭の `+` を剥がす。
# 結果: 1 行ごとに "<file>\t<content>" の tab-separated 形式
# ----------------------------------------------------------------------
ADDED_BUF="$(mktemp)"
trap 'rm -f "$ADDED_BUF"' EXIT

while IFS= read -r file; do
  [ -z "$file" ] && continue
  [ -f "$file" ] || continue  # skip non-regular files (symlink 等は read)
  # Binary detection: git が "Binary files ... differ" と出すのでその
  # 行は grep に引っかからず scan 空振りで安全に skip される
  git diff --cached -U0 --no-color -- "$file" 2>/dev/null \
    | awk -v f="$file" '
        /^\+\+\+/ { next }
        /^\+/     { sub(/^\+/, ""); print f "\t" $0 }
      ' >> "$ADDED_BUF"
done <<< "$STAGED"

# 追加行なしでも early-exit しない (2026-06-18): 削除のみ commit (= 例: slug index の legacy 行
# 削除) でも、 末尾の repo-local chain hook (.claude/pre-commit-extra.sh = legacy append-only
# gate / tree drift) を走らせる必要があるため。 leak scan 自体は ADDED_BUF が空なら下流の
# awk/grep が自然に no-op になり HITS 空 → chain 到達、 で安全。

# ----------------------------------------------------------------------
# Tier A regex check
# ----------------------------------------------------------------------
HITS=""

# Tier A-1: email (allowlist を除外)
EMAIL_HITS="$(
  awk -F'\t' '{ print $2 }' "$ADDED_BUF" \
    | grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' 2>/dev/null \
    | grep -vE '^(noreply@anthropic\.com|noreply@github\.com|support@github\.com)$' \
    | sort -u \
    || true
)"
if [ -n "$EMAIL_HITS" ]; then
  HITS="${HITS}
[tier-a/email] $(printf '%s' "$EMAIL_HITS" | head -5 | tr '\n' ' ')"
fi

# Tier A-2: /Users/<name>
PATH_HITS="$(
  awk -F'\t' '{ print $2 }' "$ADDED_BUF" \
    | grep -oE '/Users/[a-z][a-z0-9_-]*' 2>/dev/null \
    | sort -u \
    || true
)"
if [ -n "$PATH_HITS" ]; then
  HITS="${HITS}
[tier-a/abs_path] $(printf '%s' "$PATH_HITS" | head -5 | tr '\n' ' ')"
fi

# Tier A-3: IPv4 (allowlist 除外)
IPV4_ALL="$(
  awk -F'\t' '{ print $2 }' "$ADDED_BUF" \
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
[tier-a/ipv4] $(printf '%s' "$IPV4_HITS" | sort -u | head -5 | tr '\n' ' ')"
fi

# Tier A-4: token prefix (本体を晒さず redact 表示)
TOKEN_HITS="$(
  awk -F'\t' '{ print $2 }' "$ADDED_BUF" \
    | grep -oE '(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,})' 2>/dev/null \
    | sort -u \
    || true
)"
if [ -n "$TOKEN_HITS" ]; then
  TOKEN_REDACTED="$(printf '%s' "$TOKEN_HITS" | head -3 | sed -E 's/^(.{10}).*/\1.../')"
  HITS="${HITS}
[tier-a/token_prefix] $TOKEN_REDACTED"
fi

# ----------------------------------------------------------------------
# Tier B: sensitive-terms.txt ephemeral literal check
#
# Word-boundary semantics (2026-06-29 追加):
#   - ASCII-only term (= 0x20-0x7e の printable のみで構成): word-boundary
#     一致 (`grep -wF`) を適用。 短 ASCII token (= 4-6 字程度) が arxiv 等の
#     英文 abstract 中の longer word の substring に偶然一致する FP class を
#     構造的に消す。 grep の word 境界 = `[A-Za-z0-9_]` 外、 つまり space /
#     punctuation / `-` 等は境界。 「SECRET」 in 「SECRET-KEY」 は依然 match
#     (= 意図的 leak、 substring でなく word の左境界が `-` で成立)
#   - 非 ASCII term (= 日本語等): 単純 substring 一致 (`grep -F`)。 CJK 連続
#     文字列に word 境界 概念が ill-defined ゆえ全 term 一律 `-w` 化は破壊的
#     (= 日本語 token は隣接 CJK と連結し空白で区切られないので、 grep の
#      ASCII word 境界が現れず単独 hit が不可能になる)
#   - sensitive-terms.txt は read-only、 ephemeral 分割 (= temp file 経由)
#     のみ。 script memory に literal は残さず (= path 引数で grep に渡す)
#
# 設計動機: 2026-06-29 arxiv-digest archive 8 file が短 ASCII term の
#   substring FP で commit block。 user 確定方針 = root 治療 (= word-boundary
#   化)、 escape hatch (= --no-verify) で逃げない。 詳細 RCA:
#   odakin-prefs/plans/2026-06-29-archive-leak-wordbound-results.md
# ----------------------------------------------------------------------
if [ -f "$SENSITIVE_TERMS" ] && [ -s "$SENSITIVE_TERMS" ]; then
  ASCII_TERMS="$(mktemp)"
  NA_TERMS="$(mktemp)"
  # 既存 EXIT trap は ADDED_BUF のみ — 拡張
  # shellcheck disable=SC2064
  trap "rm -f '$ADDED_BUF' '$ASCII_TERMS' '$NA_TERMS'" EXIT

  awk -v a="$ASCII_TERMS" -v n="$NA_TERMS" '
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*#/ { next }
    /^[ -~]+$/      { print > a; next }
                    { print > n }
  ' "$SENSITIVE_TERMS"

  LITERAL_HITS_ASCII=""
  if [ -s "$ASCII_TERMS" ]; then
    LITERAL_HITS_ASCII="$(
      awk -F'\t' '{ print $2 }' "$ADDED_BUF" \
        | grep -wFf "$ASCII_TERMS" 2>/dev/null \
        || true
    )"
  fi
  LITERAL_HITS_NA=""
  if [ -s "$NA_TERMS" ]; then
    LITERAL_HITS_NA="$(
      awk -F'\t' '{ print $2 }' "$ADDED_BUF" \
        | grep -Ff "$NA_TERMS" 2>/dev/null \
        || true
    )"
  fi

  # 結合 (= 空行除去 + head -5 で上限)
  LITERAL_HITS="$(
    {
      [ -n "$LITERAL_HITS_ASCII" ] && printf '%s\n' "$LITERAL_HITS_ASCII"
      [ -n "$LITERAL_HITS_NA" ]    && printf '%s\n' "$LITERAL_HITS_NA"
    } | sed '/^$/d' | head -5
  )"

  if [ -n "$LITERAL_HITS" ]; then
    LITERAL_COUNT="$(printf '%s\n' "$LITERAL_HITS" | wc -l | tr -d ' ')"
    LITERAL_FILES="$(
      awk -F'\t' 'NR==FNR { bad[$0]=1; next }
        bad[$2] { print $1 }' \
        <(printf '%s\n' "$LITERAL_HITS") "$ADDED_BUF" \
      | sort -u | head -5 | tr '\n' ' '
    )"
    HITS="${HITS}
[tier-b/literal] ${LITERAL_COUNT} line(s) match sensitive-terms.txt in: ${LITERAL_FILES}"
  fi
else
  # sensitive-terms.txt が不在または空 — Tier B は skip
  # Dropbox sync 未完了 or 新 Mac 初回 clone 時に到達する想定
  echo "[tier-b/skip] sensitive-terms.txt not found or empty — Tier B literal check skipped. Tier A regex check only." >&2
fi

# ----------------------------------------------------------------------
# 判定
# ----------------------------------------------------------------------
if [ -z "$HITS" ]; then
  # Tier A/B leak gate を pass。
  # repo-local extension があれば chain (exit code 透過)。
  # 注: exec ではなく call + exit にしているのは、bash の exec は EXIT
  # trap (上で $ADDED_BUF cleanup を登録済) を skip するため。tempfile を
  # leak させないため call → 終了コード透過 → 親の trap 発火、の順にする。
  REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  EXTRA_HOOK="$REPO_ROOT/.claude/pre-commit-extra.sh"
  if [ -n "$REPO_ROOT" ] && [ -x "$EXTRA_HOOK" ]; then
    "$EXTRA_HOOK" "$@"
    exit $?
  fi
  exit 0
fi

cat >&2 << EOF
[public-precommit-runner] commit rejected: potential leak detected.

repo:        $(git rev-parse --show-toplevel 2>/dev/null)
staged hits:$HITS

本 repo は .claude/public-repo.marker で public と宣言されています。
上記の追加行に構造 (Tier A) または literal (Tier B) の leak 候補が
含まれます。

対処:
  - tier-a/email       → placeholder または noreply allowlist へ
  - tier-a/abs_path    → \$HOME/ or ~/ 相対 path へ
  - tier-a/ipv4        → 0.0.0.0 / 127.0.0.1 / RFC1918 へ
  - tier-a/token_prefix → 即 revoke + secret manager へ移動
  - tier-b/literal     → 個人層の sensitive-terms.txt にある term を
                          本文から除去 or 一般化

意図的に commit したい場合は \`git commit --no-verify\` で bypass 可能
(escape hatch)。bypass 事例は個人層の leak-incidents.md (あれば) に
記録することを推奨。
EOF

exit 1
