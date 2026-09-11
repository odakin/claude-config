#!/usr/bin/env bash
# ci-local-repro.sh — Linux CI だけで落ちる command を commit ごとに手元で再現する (使い捨て clone × native/GNU userland × 空の HOME の行列)
#
# 正本: claude-config/scripts/ci-local-repro.sh / 自身の検査 = ci-local-repro.test.sh
# 規約: conventions/debugging-discipline.md#ci-red-streak-forensics
#
# 使い方:
#   ci-local-repro.sh [--repo DIR] [--at REV]... [--userland native|gnu|both]
#                     [--env VAR=VAL]... [--path-append DIRS] [--system-gitconfig] [--tail N] [--keep]
#                     -- CMD [ARG...]
#   例 (親 commit / 導入 commit / 現在 × 2 userland = commit 単位の二分):
#     ci-local-repro.sh --at 07866f1^ --at 07866f1 --at origin/main --userland both \
#       -- bash scripts/setup-codex.test.sh
#   今の作業ツリーを 1 回 GNU で走らせるだけなら scripts/with-gnu-userland.sh --clean-env で足りる。
#
# 何をするか:
# - REV ごとに `git clone --shared --template= --no-checkout` → hook 無効で detached checkout。
#   live checkout に worktree・index・hook 実行の痕跡を残さない。 --at 省略時は HEAD
#   (= commit 済みの内容。 未 commit の変更は入らない)。
# - `env -i` で HOME = 空の一時 dir、 最小 PATH、 TMPDIR、 LANG/LC_ALL、 USER、 CI=true、
#   GIT_CONFIG_NOSYSTEM=1 と --env だけを渡し、 clone の root で CMD を実行する (手元の ~/.gitconfig・
#   init.templateDir・PATH 上の tool を持ち込まない)。 GIT_CONFIG_NOSYSTEM は Apple の Command Line Tools
#   の system gitconfig (init.defaultBranch=main) を外すため — ubuntu runner の git は master になる
#   (2026-09-11 の 2 本目の red streak)。 --system-gitconfig で残す。
# - native = OS 標準の /usr/bin 等。 gnu = 同じ dir の with-gnu-userland.sh を通す (Homebrew の gnubin dir
#   だけを PATH 先頭に差し、 python3・bash・awk は動かさない = debugging-discipline.md#one-variable-per-arm)。
#   Linux では native が既に GNU なので wrapper を通さない。 GNU 版が無ければ gnu の行は SKIP。
# - 結果を「REV (short) userland rc=N」 の行列で出す。 失敗した行には出力の末尾 N 行 (既定 15) を添える。
#
# なぜ: macOS の BSD 版 stat / sed / date は Linux runner の GNU 版と引数の意味が違う (例: `stat -f '%Lp'`
#   は BSD では permission bits、 GNU では「%Lp という file」 の file-system 情報)。 手元では test が通り
#   CI だけが落ちる。 2026-09-01〜09-11 に claude-config main の checks が push 225 回連続 red だった
#   原因はこの 1 行で、 親 / 導入 / HEAD × native / gnu の行列で commit 単位に確定した。
#
# 限界: 再現するのは userland・git の既定・環境変数の差まで。 bash は OS の版のまま (macOS 3.2 / CI 5.x)。
#   kernel・filesystem・runner に preinstall された tool・network の差は再現しない。 clone は --shared なので
#   実行中に元 repo で gc --prune しない。 macOS の /usr/bin/mktemp は template 無しの `mktemp -d` で
#   TMPDIR を見ず per-user の /var/folders/…/T に作る (2026-09-11 実測、 env -i 下でも通常環境でも) ので、
#   CMD 内の一時 file は run ごとの TMPDIR に閉じない (空 HOME と clone は閉じる)。
#
# exit: 0 = 全 run が rc=0 (gnu の SKIP を含む) / 1 = いずれかが失敗 / 2 = 使い方・git の誤り。
# bash 3.2 compatible。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAP="$SCRIPT_DIR/with-gnu-userland.sh"

usage() {
  cat >&2 <<'EOF'
usage: ci-local-repro.sh [--repo DIR] [--at REV]... [--userland native|gnu|both]
                         [--env VAR=VAL]... [--path-append DIRS] [--system-gitconfig]
                         [--tail N] [--keep] -- CMD [ARG...]
EOF
  exit "${1:-2}"
}

REPO="."
REVS=()
NREV=0
USERLAND="native"
ENVS=()
PATH_APPEND=""
TAIL_N=15
KEEP=0
NOSYS=(GIT_CONFIG_NOSYSTEM=1)

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) [ $# -ge 2 ] || usage; REPO="$2"; shift 2 ;;
    --at) [ $# -ge 2 ] || usage; REVS+=("$2"); NREV=$((NREV + 1)); shift 2 ;;
    --userland) [ $# -ge 2 ] || usage; USERLAND="$2"; shift 2 ;;
    --env)
      [ $# -ge 2 ] || usage
      case "$2" in *=*) ;; *) echo "ci-local-repro: --env needs VAR=VAL" >&2; usage ;; esac
      ENVS+=("$2"); shift 2 ;;
    --path-append) [ $# -ge 2 ] || usage; PATH_APPEND="$2"; shift 2 ;;
    --tail) [ $# -ge 2 ] || usage; TAIL_N="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --system-gitconfig) NOSYS=(); shift ;;
    -h|--help) usage 0 ;;
    --) shift; break ;;
    *) echo "ci-local-repro: unknown argument: $1" >&2; usage ;;
  esac
done
[ $# -gt 0 ] || { echo "ci-local-repro: missing '-- CMD'" >&2; usage; }
case "$USERLAND" in
  native) ULS="native" ;;
  gnu) ULS="gnu" ;;
  both) ULS="native gnu" ;;
  *) echo "ci-local-repro: --userland must be native, gnu or both" >&2; usage ;;
esac
case "$TAIL_N" in ''|*[!0-9]*) echo "ci-local-repro: --tail needs a number" >&2; usage ;; esac
[ "$NREV" -gt 0 ] || REVS=(HEAD)

TOP="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "ci-local-repro: not a git repository: $REPO" >&2; exit 2; }
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ci-local-repro.XXXXXX")" || exit 2
cleanup() { [ "$KEEP" = 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT

echo "repo: $TOP"
if [ "$KEEP" = 1 ]; then echo "work: $WORK (kept)"; else echo "work: $WORK (removed at exit)"; fi

OS="$(uname -s)"
if [ "$OS" = Linux ]; then
  BASE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"; LOC="C.UTF-8"
else
  BASE_PATH="/usr/bin:/bin:/usr/sbin:/sbin"; LOC="en_US.UTF-8"
fi
[ -n "$PATH_APPEND" ] && BASE_PATH="$BASE_PATH:$PATH_APPEND"

GNU_READY=1
case " $ULS " in
  *" gnu "*)
    if [ "$OS" = Linux ]; then
      echo "gnu: Linux — the native userland is already GNU (no wrapper)"
    elif [ ! -f "$WRAP" ]; then
      GNU_READY=0; echo "gnu: $WRAP not found — gnu runs SKIP"
    else
      probe="$(env -i HOME="$WORK" PATH="$BASE_PATH" bash "$WRAP" true 2>&1)"
      if [ $? -eq 0 ]; then
        echo "gnu: via ${WRAP##*/} (${probe#*: })"
      else
        GNU_READY=0; echo "gnu: ${probe:-${WRAP##*/} failed} — gnu runs SKIP"
      fi
    fi ;;
esac

FAILED=0
n=0
for rev in "${REVS[@]}"; do
  sha="$(git -C "$TOP" rev-parse --verify --quiet "${rev}^{commit}")" || {
    echo "ci-local-repro: unknown revision: $rev" >&2; exit 2; }
  short="$(git -C "$TOP" rev-parse --short "$sha")"
  dir="$WORK/clone-$short"
  if [ ! -d "$dir" ]; then
    git clone -q --shared --template= --no-checkout "$TOP" "$dir" || exit 2
    git -C "$dir" -c core.hooksPath=/dev/null -c advice.detachedHead=false \
      checkout -q --detach "$sha" || exit 2
  fi
  for ul in $ULS; do
    label="$(printf '%-24s %-6s' "$rev ($short)" "$ul")"
    if [ "$ul" = gnu ] && [ "$GNU_READY" = 0 ]; then
      echo "$label SKIP (no GNU userland)"; continue
    fi
    n=$((n + 1))
    PRE=()
    if [ "$ul" = gnu ] && [ "$OS" != Linux ]; then PRE=(bash "$WRAP"); fi
    home="$WORK/home-$n"; tmp="$WORK/tmp-$n"; log="$WORK/log-$n.txt"
    mkdir -p "$home" "$tmp"
    ( cd "$dir" && env -i HOME="$home" PATH="$BASE_PATH" TMPDIR="$tmp" LANG="$LOC" LC_ALL="$LOC" \
        USER="${USER:-ci}" CI=true ${NOSYS[@]+"${NOSYS[@]}"} ${ENVS[@]+"${ENVS[@]}"} \
        ${PRE[@]+"${PRE[@]}"} "$@" ) >"$log" 2>&1
    rc=$?
    echo "$label rc=$rc"
    if [ "$rc" -ne 0 ]; then
      FAILED=1
      tail -n "$TAIL_N" "$log" | sed 's/^/    | /'
    fi
  done
done
exit "$FAILED"
