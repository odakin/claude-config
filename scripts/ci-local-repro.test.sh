#!/usr/bin/env bash
# ci-local-repro.test.sh — ci-local-repro.sh の fixture test (commit 行列の rc・空 HOME・元 repo 無変更・hook 非複製・使い方の誤り・GNU shim)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib/test-err-trap.sh"
TOOL="$SCRIPT_DIR/ci-local-repro.sh"

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

R="$T/repo"
mkdir -p "$R"
git -C "$R" init -q --template=
git -C "$R" config user.name fixture
git -C "$R" config user.email noreply@github.com
git -C "$R" config commit.gpgsign false
printf '%s\n' 'echo "HOME=$HOME"' 'exit 0' > "$R/probe.sh"
git -C "$R" add probe.sh
git -C "$R" commit -q -m good
GOOD="$(git -C "$R" rev-parse --short HEAD)"
printf '%s\n' 'echo "HOME=$HOME"' 'exit 3' > "$R/probe.sh"
git -C "$R" commit -q -am bad
BAD="$(git -C "$R" rev-parse --short HEAD)"

snapshot() { git -C "$R" worktree list --porcelain; git -C "$R" status --porcelain; ls -A "$R/.git"; }
before="$(snapshot)"

# 1. 行列: good は rc=0、 bad は rc=3 で出力末尾が添えられ、 全体の exit は 1
rc=0
out="$(TMPDIR="$T" bash "$TOOL" --repo "$R" --at "$GOOD" --at "$BAD" --userland native \
  --tail 3 -- sh probe.sh 2>&1)" || rc=$?
[ "$rc" -eq 1 ]
printf '%s\n' "$out" | grep -qE "\($GOOD\) +native +rc=0$"
printf '%s\n' "$out" | grep -qE "\($BAD\) +native +rc=3$"

# 2. 空の HOME: 失敗行に添えられた HOME は work dir 配下で、 呼び元の HOME ではない
printf '%s\n' "$out" | grep -qE '\| HOME=.*ci-local-repro\.[^/]+/home-[0-9]+$'
if printf '%s\n' "$out" | grep -qxF "    | HOME=$HOME"; then
  echo "caller HOME leaked into the run" >&2
  exit 1
fi

# 3. work dir は既定で消える
work="$(printf '%s\n' "$out" | sed -n 's/^work: \(.*\) (removed at exit)$/\1/p')"
[ -n "$work" ]
[ ! -e "$work" ]

# 4. 元 repo は無変更 (worktree 一覧・status・.git 直下)
[ "$(snapshot)" = "$before" ]

# 5. --keep: clone に hook template が複製されていない
out="$(TMPDIR="$T" bash "$TOOL" --repo "$R" --at "$GOOD" --keep -- sh probe.sh 2>&1)"
work="$(printf '%s\n' "$out" | sed -n 's/^work: \(.*\) (kept)$/\1/p')"
[ -d "$work/clone-$GOOD" ]
[ -z "$(ls -A "$work/clone-$GOOD/.git/hooks" 2>/dev/null)" ]
rm -rf "$work"

# 6. 使い方の誤り: '-- CMD' なし / 未知の revision / 不正な --userland は exit 2
rc=0; bash "$TOOL" --repo "$R" >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ]
rc=0; TMPDIR="$T" bash "$TOOL" --repo "$R" --at no-such-rev -- true >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ]
rc=0; bash "$TOOL" --repo "$R" --userland bsd -- true >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ]

# 7. GNU userland: Linux か、 with-gnu-userland.sh が Homebrew の GNU 版を見つければ、 run の中の stat は GNU になる
if [ "$(uname -s)" = Linux ] || bash "$SCRIPT_DIR/with-gnu-userland.sh" true >/dev/null 2>&1; then
  rc=0
  out="$(TMPDIR="$T" bash "$TOOL" --repo "$R" --userland gnu \
    -- sh -c 'stat --version 2>/dev/null | head -n 1 | grep -q GNU' 2>&1)" || rc=$?
  [ "$rc" -eq 0 ]
  printf '%s\n' "$out" | grep -qE " gnu +rc=0$"
else
  echo "SKIP: GNU userland check (no GNU stat on this machine)"
fi

# 8. system の gitconfig も外れる (Apple の Command Line Tools の gitconfig は init.defaultBranch=main を持つ)
rc=0
out="$(TMPDIR="$T" bash "$TOOL" --repo "$R" -- sh -c '[ -z "$(git config --get init.defaultBranch)" ]' 2>&1)" || rc=$?
[ "$rc" -eq 0 ]

echo "ci-local-repro tests passed"
