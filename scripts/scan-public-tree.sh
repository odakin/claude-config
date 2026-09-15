#!/usr/bin/env bash
# scan-public-tree.sh — 公開 repo の現在の tree 全体を pre-commit gate の全 Tier に通す
#
# 正本: claude-config/scripts/scan-public-tree.sh
# 規律: conventions/confidential-repo-boundary.md#gate-installed-after-history
#
# Why: pre-commit gate は **staged 差分 (= これから足す行) しか見ない**。 gate を入れる前から
#   履歴のある repo では、 既に commit 済の全 file が一度も検査されないまま公開される。
#   「gate を入れた」 は「検査した」 ではない — 設置と同じ turn に tree 全体を 1 回通すまでが
#   1 単位。 実測: gate を新設した repo を初回 push した直後にこの走査をかけると、 Tier C
#   (非公開 repo 名への参照) が既存の設計メモに残っていた。 gate 単体は素通りしていた。
#
# 機構: tracked file を temp dir へ `git archive` で展開 → `git init` + `git add -A -f` →
#   public-precommit-runner.sh を temp repo で実行する。 HEAD の無い fresh repo なので
#   **全 file が「追加行」 として見え**、 gate の全 Tier (A 構造 / B literal / C 非公開 repo 名 /
#   D 未公開文書の逐語・機密 / E 活動の事実) がそのまま tree 全体に当たる。
#   本物の index も working tree も remote も触らない (= 読むだけ)。
#
# ⚠️ 射程: **現在の tree だけ**。 過去の commit の中身と commit message は見ない
#   (= 履歴は go-forward な操作では消えない、 conventions/confidential-repo-boundary.md §6)。
#   commit message の棚卸しは check-unpublished-quote.py --replay が別に持つ。
#
# usage:
#   scan-public-tree.sh [--repo DIR]          1 repo (既定 = cwd の repo)
#   scan-public-tree.sh --all [--root DIR]    marker つき repo を全部 (既定 root = claude-config の親)
#   --max N                                   この 1 回で新しく走査する repo 数の上限 (既定 = 無制限)
#   --force                                   台帳を無視して再走査
#   --quiet                                   finding 無しの行を出さない
#
# ⚠️ 1 repo あたり数分かかる (= Tier D が未公開文書の索引を毎回作り直す)。 定期検査から呼ぶときは
#   `--max 2` のように区切る: 台帳が進捗を持つので、 何回かに分けて全体が埋まる。
#   ⚠️ **未記録の repo を先に回す** — finding ありは走査済にしない設計なので、 素直に並べると
#   予算を毎回そいつらが食い潰し、 一度も見ていない repo に永久に到達しない。
#
# 受理: repo の `.claude/public-tree-accept.txt` (1 行 1 substring、 `#` 以降は理由)。
#   既に公開されていて「見た上で残す」 と決めた Tier A の token を、 この棚卸しでだけ落とす。
#   **gate 本体には効かない** (= 新しい書き込みは今までどおり止まる)。 件数と file 名を出す
#   Tier B/C は受理できない — 実名や非公開 repo 名を「受理」 で寝かせないため、 直すしかない。
#
# 台帳 (machine-local): $CLAUDE_STATE_DIR (既定 ~/.claude/state)/public-tree-scan.tsv
#   repo<TAB>HEAD sha<TAB>走査日<TAB>finding 件数
#   **HEAD が進んでも再走査しない** — 新しい行は gate 本体が見ているので 1 repo 1 回で足りる。
#   gate の Tier を足した / 検出語の源を変えた ときだけ --force で回し直す。
#
# exit: 0 = finding 無し (or 対象外) / 1 = finding あり / 2 = usage error

set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SELF_DIR/public-precommit-runner.sh"
DEFAULT_ROOT="$(cd "$SELF_DIR/../.." && pwd)"   # = claude-config を含む base dir
STATE_DIR="${CLAUDE_STATE_DIR:-$HOME/.claude/state}"
LEDGER="$STATE_DIR/public-tree-scan.tsv"

MODE="one"
REPO_ARG=""
ROOT="$DEFAULT_ROOT"
FORCE=0
QUIET=0
MAXN=0          # 0 = 無制限

while [ $# -gt 0 ]; do
  case "$1" in
    --all)    MODE="all" ;;
    --repo)   shift; REPO_ARG="${1:-}" ;;
    --root)   shift; ROOT="${1:-}" ;;
    --max)    shift; MAXN="${1:-0}" ;;
    --force)  FORCE=1 ;;
    --quiet)  QUIET=1 ;;
    -h|--help) sed -n '1,44p' "$0"; exit 0 ;;
    *) echo "scan-public-tree.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -x "$RUNNER" ] || { echo "scan-public-tree.sh: runner not executable: $RUNNER" >&2; exit 2; }

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }

record() {
  # $1 = repo path, $2 = sha, $3 = findings count
  mkdir -p "$STATE_DIR" 2>/dev/null || return 0
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$(date +%Y-%m-%d)" "$3" >> "$LEDGER"
}

# 台帳に **何らかの** 記録があるか (= finding ありも含む)。 --all の順序づけに使う:
# finding ありの repo は走査済にしない設計なので、 素直に並べると予算 (--max) を毎回
# そいつらが食い潰し、 **一度も見ていない repo に永久に到達しない**。 未記録を先に回す。
has_record() {
  [ -f "$LEDGER" ] || return 1
  awk -F'\t' -v r="$1" '$1 == r { found = 1 } END { exit found ? 0 : 1 }' "$LEDGER"
}

already_scanned() {
  [ "$FORCE" -eq 1 ] && return 1
  [ -f "$LEDGER" ] || return 1
  # **finding 0 で終わった記録があるときだけ走査済**。 finding ありの記録で skip すると、
  # 直さなかった repo が静かに対象から外れる (= 検出器が自分の finding を隠す)
  awk -F'\t' -v r="$1" '$1 == r && $4 == 0 { found = 1 } END { exit found ? 0 : 1 }' "$LEDGER"
}

# ----------------------------------------------------------------------
# レビュー済みとして受理した finding を落とす。
#
# 対象 = repo の `.claude/public-tree-accept.txt` (1 行 1 substring、 `#` 以降は理由)。
# **gate 本体 (= これから足す行) には効かない** — 効くのはこの棚卸しだけ。 既に公開されていて
# 「見た上で残すと決めた」 ものを毎回再提示しないための口で、 新しい書き込みは今までどおり止まる。
#
# 落とせるのは token を並べる Tier (A) の行だけ。 件数と file 名を出す Tier (B/C) の行は
# 受理できない (= 直すしかない)。 意図的: 実名や非公開 repo 名を「受理」 で寝かせない。
# ----------------------------------------------------------------------
# 受理一覧が「隠し場所」 になっていないかを確かめる。
#
# 受理してよいのは **既にこの tree の他の場所に在る文字列** だけ (= 見た上で残すと決めた finding)。
# tree に無い文字列が並んでいたら、 それは受理ではなく **新しい開示** で、 しかも受理一覧は
# gate の対象外なので黙って通る。 gate を外した代償をここで払い戻す。
validate_accept() {
  local accept="$1" root="$2" term
  [ -f "$accept" ] || return 0
  while IFS= read -r term; do
    term="${term%%#*}"
    term="$(printf '%s' "$term" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -z "$term" ] && continue
    if ! grep -rqF --exclude='public-tree-accept.txt' -- "$term" "$root" 2>/dev/null; then
      printf '%s\n' "$term"
    fi
  done < "$accept"
}

filter_accepted() {
  local accept="$1"
  [ -f "$accept" ] || { cat; return 0; }
  local sed_args=() term
  while IFS= read -r term; do
    term="${term%%#*}"
    term="$(printf '%s' "$term" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -z "$term" ] && continue
    sed_args+=(-e "s|$(printf '%s' "$term" | sed 's/[][\.*^$/&|]/\\&/g')||g")
  done < "$accept"
  [ "${#sed_args[@]}" -eq 0 ] && { cat; return 0; }
  # 受理 substring を消し、 tag だけ残った Tier A 行を落とす
  sed "${sed_args[@]}" | sed -E '/^\[tier-a\/[a-z_]+\][[:space:]]*$/d'
}

# ----------------------------------------------------------------------
# 1 repo を走査。 0 = clean / 1 = finding / 2 = 対象外 (commit 無し等) / 3 = 台帳で skip
# ----------------------------------------------------------------------
scan_one() {
  local repo="$1" name sha tmp out rc
  name="$(basename "$repo")"

  sha="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || {
    say "[scan-public-tree] $name: 対象外 (commit がまだ無い)"
    return 2
  }

  if already_scanned "$repo"; then
    say "[scan-public-tree] $name: skip (台帳に走査済。 回し直すなら --force)"
    return 3
  fi

  tmp="$(mktemp -d)" || return 2
  # tracked file だけを展開 (= untracked / 未 commit の変更は gate 本体の担当)
  if ! git -C "$repo" archive HEAD 2>/dev/null | tar -x -C "$tmp" 2>/dev/null; then
    rm -rf "$tmp"
    say "[scan-public-tree] $name: 対象外 (git archive に失敗)"
    return 2
  fi
  # repo-local の chain hook は走査では動かさない (= 副作用を持ちうる)
  rm -f "$tmp/.claude/pre-commit-extra.sh"

  (
    cd "$tmp" || exit 2
    git init -q 2>/dev/null
    # -f = .gitignore を無視。 実 repo で tracked な file が ignore 対象のことがある
    git add -A -f 2>/dev/null
  )

  local accept_bad
  accept_bad="$(validate_accept "$repo/.claude/public-tree-accept.txt" "$tmp")"

  out="$(cd "$tmp" && "$RUNNER" 2>&1)"
  rc=$?
  rm -rf "$tmp"

  if [ -n "$accept_bad" ]; then
    printf '%s\n' "🔴 [scan-public-tree] $name: 受理一覧に tree のどこにも無い文字列がある (= 受理でなく新しい開示)"
    printf '%s\n' "$accept_bad" | sed 's/^/    /'
    printf '%s\n' "    → 受理一覧に書けるのは、 既に tree に在る finding だけ。 消すか、 本文側を直す"
    record "$repo" "$sha" 1
    return 1
  fi

  if [ "$rc" -eq 0 ]; then
    say "[scan-public-tree] $name: 0 finding"
    record "$repo" "$sha" 0
    return 0
  fi

  # finding 行だけを取り出して受理 filter をかける (= 全 Tier の見出しを拾う)
  local hits
  # ⚠️ `[tier-b/skip]` 等の **skip 通知**は finding ではない (= 検査しなかった、 という報告)。
  # 拾うと「対象外」 が「違反」 に化ける
  hits="$(printf '%s\n' "$out" \
    | grep -E '^\[(tier-|unpublished-quote|activity-facts|confidential-leak)' \
    | grep -v '/skip\]' \
    | filter_accepted "$repo/.claude/public-tree-accept.txt" \
    | sed '/^[[:space:]]*$/d')"

  if [ -z "$hits" ]; then
    # `commit rejected:` (= Tier A/B/C の汎用見出し) は上で filter 済の詳細に対応するので
    # ここでは見ない。 見るのは `commit rejected by ...` (= Tier D/E / link guard 等、
    # 見出し行を持たない別経路) だけ
    if printf '%s' "$out" | grep -q 'commit rejected by'; then
      # 受理 filter で消えたが、 見出しを持たない別の理由で落ちている = 黙って通さない
      printf '%s\n' "⚠️ [scan-public-tree] $name: 受理済み以外の理由で runner が落ちた"
      printf '%s\n' "$out" | sed 's/^/    /'
      record "$repo" "$sha" 1
      return 1
    fi
    say "[scan-public-tree] $name: 0 finding (= 残りは .claude/public-tree-accept.txt の受理済みのみ)"
    record "$repo" "$sha" 0
    return 0
  fi

  printf '%s\n' "🔴 [scan-public-tree] $name: finding あり (= 既に公開されている中身)"
  printf '%s\n' "$hits" | sed 's/^/    /'
  printf '%s\n' "    → 直すか、 見た上で残すなら $name/.claude/public-tree-accept.txt に理由つきで 1 行"
  printf '%s\n' "    → 履歴の書き換えをするかは人間の判断 (既定 = しない)"
  record "$repo" "$sha" 1
  return 1
}

# ----------------------------------------------------------------------
RC=0
if [ "$MODE" = "all" ]; then
  [ -d "$ROOT" ] || { echo "scan-public-tree.sh: no such root: $ROOT" >&2; exit 2; }
  found=0
  scanned=0
  # 未記録 → 記録あり の順に並べる (= 予算がある限り、 まだ一度も見ていない repo を先に)
  fresh=""; seen=""
  for d in "$ROOT"/*/; do
    [ -f "${d}.claude/public-repo.marker" ] || continue
    [ -d "${d}.git" ] || continue
    found=$((found + 1))
    if has_record "${d%/}"; then seen="$seen
${d%/}"; else fresh="$fresh
${d%/}"; fi
  done
  for r in $(printf '%s\n%s\n' "$fresh" "$seen" | sed '/^$/d'); do
    scan_one "$r"
    rc_one=$?
    [ "$rc_one" -eq 1 ] && RC=1
    # 新しく走査した repo だけ数える (= 台帳 skip 〔3〕 と対象外 〔2〕 は上限を消費しない)
    if [ "$rc_one" -eq 0 ] || [ "$rc_one" -eq 1 ]; then
      scanned=$((scanned + 1))
      if [ "$MAXN" -gt 0 ] && [ "$scanned" -ge "$MAXN" ]; then
        say "[scan-public-tree] --max $MAXN に達したので中断 (台帳が進捗を持つので続きは次回)"
        break
      fi
    fi
  done
  say "[scan-public-tree] marker つき $found repo を対象に走査"
else
  if [ -n "$REPO_ARG" ]; then
    REPO="$(git -C "$REPO_ARG" rev-parse --show-toplevel 2>/dev/null)"
  else
    REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
  fi
  [ -n "${REPO:-}" ] || { echo "scan-public-tree.sh: not a git repo (--repo DIR で指定)" >&2; exit 2; }
  scan_one "$REPO"
  [ $? -eq 1 ] && RC=1
fi

exit "$RC"
