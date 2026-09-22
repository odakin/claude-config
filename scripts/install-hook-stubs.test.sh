#!/usr/bin/env bash
# install-hook-stubs.test.sh — hook stub installer 3 本 + heal-hook-stubs.sh の test (lib/hook-stub.sh の規約)
#
# 規約 = installer は git が track している file を書き換えない (conventions/hook-authoring.md#installer-tracked-stub):
#   T1 track 済みの "$HOME/..." 形 stub (同じ runner) → 書き換えない
#   T2 track 済みで別の場所を指す stub → 書き換えない (警告だけ)
#   T3 untrack の古い stub (.git/hooks) → 最新化する
#   T4 repo 内 hooksPath の untrack trailer stub → .git/info/exclude に 1 行
#   T5 通常の .git/hooks → exclude に触らない
#   T6 過去の installer が track 済み stub に書いた差分 → installer 実行で track 版に戻る
#   T7 heal-hook-stubs.sh → installer の書いた差分だけ戻し、 user の手直しには触らない
#   T8 track 済みの自前 pre-commit (stub でない) → 退避も上書きもしない
# 規約 2 = macOS に exec で kill される hook は同じ bytes の新しい inode に作り直す (#killed-hook-stub):
#   T11 kill される untrack stub → installer が作り直す / T12 kill される track 済み stub → 作り直しても git は clean
#   T13 heal-hook-stubs.sh: kill される runner と symlink 先 (repo の hook) を作り直し、 2 回目は無音
#   T14 作り直しても kill される → WARNING を出して 1 回で止める / T15 検査は hook の本体を 1 行も走らせない
#   T16 bash 以外の hook・macOS 以外は調べない
#   T17 --surface = 戻した / 作り直した / 要対応 の 3 見出し / T18 --check = 書かずに列挙して exit 1
#   (偽の kill 一覧は inode 番号 = 印を付けた inode は hard link で生かす。 Linux の fs は番号を再利用する)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# checkout が $HOME の外 (= /private/tmp の使い捨て worktree 等) だと "$HOME/..." 形の stub が作れず、
# $HOME 形と絶対 path 形が同じ文字列になって T6/T7 の fixture が dirty にならない (2026-09-12)。
# その時だけ checkout の最上位 dir を HOME とみなす = 置き場所に依らず 2 つの形を区別する。
# fixture の git は mkrepo が repo-local に設定するので、 HOME の差し替えは結果に効かない。
case "$HERE/" in
  "$HOME"/*) : ;;
  *) _top="${HERE#/}"; HOME="/${_top%%/*}"; export HOME ;;
esac
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

# 偽の exec 検査 (#killed-hook-stub): 本物の macOS の kill は任意に起こせないので、 BASH_ENV の中で「exec された
# file の inode が $FAKE_KILLED に載っていれば自分を SIGKILL」 する。 macOS と同じく判定は inode ごと = 同じ bytes でも
# 新しい inode なら通る。 $FAKE_KILLED_PATHS の path は inode に依らず kill し続ける (= 作り直しても直らない場合)。
# OS も Darwin に固定し、 Linux の CI でも同じ経路を通す。 ($0 は BASH_ENV の中では "bash" なので path は ps から取る)
FAKE_ENV="$TMP/fake-exec-probe.bash"
cat > "$FAKE_ENV" <<'EOF'
set -- $(ps -ww -o args= -p $$)
p="${2:-}"
set -- $(ls -iL "$p" 2>/dev/null)
if grep -qxF "$p" "$FAKE_KILLED_PATHS" 2>/dev/null || { [ -n "${1:-}" ] && grep -qx "$1" "$FAKE_KILLED" 2>/dev/null; }; then
  kill -9 $$
fi
exit 0
EOF
export HOOK_EXEC_PROBE_OS=Darwin HOOK_EXEC_PROBE_ENV="$FAKE_ENV"
export FAKE_KILLED="$TMP/killed-inodes" FAKE_KILLED_PATHS="$TMP/killed-paths"
: > "$FAKE_KILLED"; : > "$FAKE_KILLED_PATHS"
inode() { set -- $(ls -iL "$1"); echo "$1"; }
# 印を付けた inode は hard link で控えを取って生かす: Linux の fs (ext4) は空いた inode 番号をすぐ再利用するので、
# 作り直しで空いた番号が次の一時 file に付き、 別の file の判定を引き継ぐ (2026-09-22 CI の T13 / T17)。 macOS (APFS) は
# 番号を再利用しないので手元では出ない。 控え = 同じ inode の別 path (macOS の実物も hard link は path に依らず kill)
KEEP="$TMP/keep-inodes"; mkdir -p "$KEEP"; keep_n=0
kill_mark() { inode "$1" >> "$FAKE_KILLED"; keep_n=$((keep_n+1)); ln -L "$1" "$KEEP/$keep_n" 2>/dev/null || ln "$1" "$KEEP/$keep_n"; }
execs() {  # hook を偽の検査で exec して 137 以外なら真
  { BASH_ENV="$FAKE_ENV" "$1" </dev/null >/dev/null 2>&1; } 2>/dev/null
  [ $? -ne 137 ]
}
ok() { PASS=$((PASS+1)); echo "  ok: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  NG: $1"; }

mkrepo() {  # $1 = dir, $2 = "public" なら marker を置く
  git init -q "$1"
  git -C "$1" config user.name t
  git -C "$1" config user.email t@example.invalid
  git -C "$1" config commit.gpgsign false
  if [ "${2:-}" = "public" ]; then
    mkdir -p "$1/.claude"
    : > "$1/.claude/public-repo.marker"
  fi
}
home_rel="${HERE/#$HOME/\$HOME}"
stub() {  # $1 = exec target
  printf '#!/bin/bash\n# Stub installed by claude-config/scripts/install-x.sh\n# Do not edit.\nexec "%s" "$@"\n' "$1"
}
clean() { [ -z "$(git -C "$1" status --porcelain -- "$2")" ]; }

# 共通 fixture: hooksPath = scripts/hooks、 "$HOME/..." 形 stub を track
mk_tracked_repo() {  # $1 = dir
  mkrepo "$1" public
  git -C "$1" config core.hooksPath scripts/hooks
  mkdir -p "$1/scripts/hooks"
  stub "$home_rel/public-precommit-runner.sh" > "$1/scripts/hooks/pre-commit"
  stub "$home_rel/commit-msg-leak-guard-runner.sh" > "$1/scripts/hooks/commit-msg"
  chmod +x "$1/scripts/hooks/pre-commit" "$1/scripts/hooks/commit-msg"
  git -C "$1" add -A && git -C "$1" commit -q --no-verify -m init
}

echo "=== T1: tracked \$HOME-form stubs stay untouched ==="
R="$TMP/r1"; mk_tracked_repo "$R"
bash "$HERE/install-public-precommit.sh" "$R" >/dev/null 2>&1
bash "$HERE/install-public-commit-msg.sh" "$R" >/dev/null 2>&1
clean "$R" scripts/hooks && ok "tracked stubs not rewritten" || ng "worktree dirtied: $(git -C "$R" status --porcelain)"

echo "=== T2: tracked stub pointing elsewhere is left alone (warning only) ==="
stub "/old/place/public-precommit-runner.sh" > "$R/scripts/hooks/pre-commit"
git -C "$R" commit -q --no-verify -am "old path"
err="$(bash "$HERE/install-public-precommit.sh" "$R" 2>&1 >/dev/null)"
clean "$R" scripts/hooks && ok "tracked stub not rewritten" || ng "tracked stub rewritten"
case "$err" in *"not rewriting"*) ok "warning printed" ;; *) ng "no warning (got: $err)" ;; esac

echo "=== T3: untracked stale stub in .git/hooks is refreshed ==="
R3="$TMP/r3"; mkrepo "$R3" public
stub "/old/place/public-precommit-runner.sh" > "$R3/.git/hooks/pre-commit"
i3="$(inode "$R3/.git/hooks/pre-commit")"
bash "$HERE/install-public-precommit.sh" "$R3" >/dev/null 2>&1
grep -qF "exec \"$HERE/public-precommit-runner.sh\"" "$R3/.git/hooks/pre-commit" && ok "stale stub refreshed" || ng "not refreshed: $(cat "$R3/.git/hooks/pre-commit")"
# 同じ inode への上書きでは macOS の kill の判定が残る = 書くときは新しい inode (#killed-hook-stub)
[ "$(inode "$R3/.git/hooks/pre-commit")" != "$i3" ] && ok "refreshed into a new inode" || ng "refreshed in place (same inode)"
[ -x "$R3/.git/hooks/pre-commit" ] && ok "refreshed stub is executable" || ng "refreshed stub lost +x"

echo "=== T4: untracked in-worktree trailer stub is excluded ==="
bash "$HERE/install-session-trailer.sh" "$R" >/dev/null 2>&1
bash "$HERE/install-session-trailer.sh" "$R" >/dev/null 2>&1
clean "$R" scripts/hooks/prepare-commit-msg && ok "trailer stub hidden from status" || ng "trailer stub still shows"
n="$(grep -cxF '/scripts/hooks/prepare-commit-msg' "$R/.git/info/exclude" 2>/dev/null || true)"
[ "$n" = "1" ] && ok "exclude entry written once" || ng "exclude entry count = $n"

echo "=== T5: plain .git/hooks install leaves exclude alone ==="
R5="$TMP/r5"; mkrepo "$R5"
before="$(cat "$R5/.git/info/exclude" 2>/dev/null || true)"
bash "$HERE/install-session-trailer.sh" "$R5" >/dev/null 2>&1
after="$(cat "$R5/.git/info/exclude" 2>/dev/null || true)"
[ -x "$R5/.git/hooks/prepare-commit-msg" ] && ok "stub installed in .git/hooks" || ng "stub missing"
[ "$before" = "$after" ] && ok "exclude unchanged" || ng "exclude changed"

echo "=== T6: installer restores its own past drift on a tracked stub ==="
R6="$TMP/r6"; mk_tracked_repo "$R6"
stub "$HERE/public-precommit-runner.sh" > "$R6/scripts/hooks/pre-commit"   # = 旧 installer が書いた absolute 形
clean "$R6" scripts/hooks && ng "fixture should be dirty" || ok "fixture dirty (old installer drift)"
out="$(bash "$HERE/install-public-precommit.sh" "$R6" 2>&1)"
clean "$R6" scripts/hooks && ok "drift restored to tracked version" || ng "still dirty (got: $out)"

echo "=== T7: heal-hook-stubs.sh restores installer drift only ==="
H="$TMP/heal"; mkdir -p "$H"
mk_tracked_repo "$H/a"
stub "$HERE/commit-msg-leak-guard-runner.sh" > "$H/a/scripts/hooks/commit-msg"          # installer drift
mk_tracked_repo "$H/b"
printf '#!/bin/bash\n# my own tweak\nexec "%s/public-precommit-runner.sh" "$@"\n' "$HERE" > "$H/b/scripts/hooks/pre-commit"   # user の手直し
out="$(bash "$HERE/heal-hook-stubs.sh" "$H" 2>&1)"
clean "$H/a" scripts/hooks && ok "installer drift healed" || ng "a still dirty"
clean "$H/b" scripts/hooks && ng "user edit was reverted" || ok "user edit left alone"
case "$out" in *"restored"*"/a/"*) ok "heal reported" ;; *) ng "heal output: $out" ;; esac
out2="$(bash "$HERE/heal-hook-stubs.sh" "$H" 2>&1)"
[ -z "$out2" ] && ok "second run silent" || ng "second run not silent: $out2"

echo "=== T8: tracked custom pre-commit is neither moved nor overwritten ==="
R8="$TMP/r8"; mkrepo "$R8" public
git -C "$R8" config core.hooksPath .githooks
mkdir -p "$R8/.githooks"
printf '#!/bin/bash\necho custom\n' > "$R8/.githooks/pre-commit"; chmod +x "$R8/.githooks/pre-commit"
git -C "$R8" add -A && git -C "$R8" commit -q --no-verify -m init
bash "$HERE/install-public-precommit.sh" "$R8" >/dev/null 2>&1
clean "$R8" .githooks && ok "custom hook untouched" || ng "custom hook changed: $(git -C "$R8" status --porcelain)"
ls "$R8/.githooks" | grep -q '\.bak-' && ng "backup created" || ok "no backup created"

echo "=== T9: installer-style stub with a hand-added line is not reverted ==="
mk_tracked_repo "$H/c"
{ stub "$HERE/public-precommit-runner.sh"; echo "# extra line added by hand"; } > "$H/c/scripts/hooks/pre-commit"
bash "$HERE/heal-hook-stubs.sh" "$H" >/dev/null 2>&1
bash "$HERE/install-public-precommit.sh" "$H/c" >/dev/null 2>&1
clean "$H/c" scripts/hooks && ng "hand-edited stub was reverted" || ok "hand-edited stub left alone"
grep -q "extra line added by hand" "$H/c/scripts/hooks/pre-commit" && ok "hand-added line survives" || ng "hand-added line lost"

echo "=== T10: .git/hooks symlink to a tracked repo hook is not written through ==="
R10="$TMP/r10"; mkrepo "$R10" public
mkdir -p "$R10/hooks"
# runner 名を含むが installer の stub 形ではない repo の hook (= 自前の検査から runner を chain する形)
printf '#!/bin/bash\necho gate\n"%s" "$@"\n' "$HERE/public-precommit-runner.sh" > "$R10/hooks/pre-commit"
chmod +x "$R10/hooks/pre-commit"
git -C "$R10" add -A && git -C "$R10" commit -q --no-verify -m init
ln -s "$R10/hooks/pre-commit" "$R10/.git/hooks/pre-commit"
bash "$HERE/install-public-precommit.sh" "$R10" >/dev/null 2>&1
clean "$R10" hooks && ok "tracked hook not rewritten through the link" || ng "tracked hook rewritten: $(git -C "$R10" diff -- hooks)"
[ "$(readlink "$R10/.git/hooks/pre-commit")" = "$R10/hooks/pre-commit" ] && ok "link kept" || ng "link moved/replaced"

echo "=== T11: installer recreates an untracked stub that macOS kills on exec ==="
R11="$TMP/r11"; mkrepo "$R11"
bash "$HERE/install-session-trailer.sh" "$R11" >/dev/null 2>&1
H11="$R11/.git/hooks/prepare-commit-msg"; cp "$H11" "$TMP/h11.orig"
kill_mark "$H11"
execs "$H11" && ng "fixture should be killed" || ok "fixture killed (inode marked)"
out="$(bash "$HERE/install-session-trailer.sh" "$R11" 2>&1)"
execs "$H11" && ok "stub executes after installer" || ng "still killed (got: $out)"
cmp -s "$H11" "$TMP/h11.orig" && ok "same bytes" || ng "content changed"
[ -x "$H11" ] && ok "still executable" || ng "lost +x"
case "$out" in *"recreated"*"$H11"*) ok "recreation reported" ;; *) ng "no report (got: $out)" ;; esac
out="$(bash "$HERE/install-session-trailer.sh" "$R11" 2>&1)"
case "$out" in *recreated*) ng "second run recreated again: $out" ;; *) ok "second run leaves it alone" ;; esac

echo "=== T12: tracked stub that macOS kills is recreated with the worktree still clean ==="
R12="$TMP/r12"; mk_tracked_repo "$R12"
kill_mark "$R12/scripts/hooks/pre-commit"
bash "$HERE/install-public-precommit.sh" "$R12" >/dev/null 2>&1
execs "$R12/scripts/hooks/pre-commit" && ok "tracked stub executes after installer" || ng "tracked stub still killed"
clean "$R12" scripts/hooks && ok "worktree clean (same bytes, same mode)" || ng "worktree dirtied: $(git -C "$R12" status --porcelain)"

echo "=== T13: heal-hook-stubs.sh recreates killed runners and symlink targets, then is silent ==="
H13="$TMP/heal13"; mkdir -p "$H13"
mkrepo "$H13/a"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TMP/fake-runner.sh"; chmod +x "$TMP/fake-runner.sh"
stub "$TMP/fake-runner.sh" > "$H13/a/.git/hooks/commit-msg"; chmod +x "$H13/a/.git/hooks/commit-msg"
kill_mark "$TMP/fake-runner.sh"
mkrepo "$H13/b"
mkdir -p "$H13/b/hooks"
printf '#!/bin/bash\necho gate\n' > "$H13/b/hooks/pre-commit"; chmod +x "$H13/b/hooks/pre-commit"
git -C "$H13/b" add -A && git -C "$H13/b" commit -q --no-verify -m init
ln -s ../../hooks/pre-commit "$H13/b/.git/hooks/pre-commit"
kill_mark "$H13/b/hooks/pre-commit"
out="$(bash "$HERE/heal-hook-stubs.sh" "$H13" 2>&1)"
execs "$TMP/fake-runner.sh" && ok "killed runner recreated" || ng "runner still killed (got: $out)"
execs "$H13/b/.git/hooks/pre-commit" && ok "symlinked hook executes" || ng "symlinked hook still killed (got: $out)"
[ -L "$H13/b/.git/hooks/pre-commit" ] && ok "link kept" || ng "link replaced by a file"
clean "$H13/b" hooks && ok "tracked link target unchanged in git" || ng "tracked target dirtied"
case "$out" in *"runner recreated"*"fake-runner.sh"*) ok "runner recreation reported" ;; *) ng "runner report missing (got: $out)" ;; esac
out2="$(bash "$HERE/heal-hook-stubs.sh" "$H13" 2>&1)"
[ -z "$out2" ] && ok "second run silent" || ng "second run not silent: $out2"

echo "=== T14: a hook still killed after recreation is reported once, not retried ==="
H14="$TMP/heal14"; mkdir -p "$H14"; mkrepo "$H14/a"
printf '#!/bin/bash\nexit 0\n' > "$H14/a/.git/hooks/pre-push"; chmod +x "$H14/a/.git/hooks/pre-push"
cp "$H14/a/.git/hooks/pre-push" "$TMP/h14.orig"
echo "$H14/a/.git/hooks/pre-push" > "$FAKE_KILLED_PATHS"
out="$(bash "$HERE/heal-hook-stubs.sh" "$H14" 2>&1)"; rc=$?
: > "$FAKE_KILLED_PATHS"
[ "$rc" -eq 0 ] && ok "heal exits 0" || ng "heal exit $rc"
case "$out" in *"WARNING"*"still killed"*"pre-push"*) ok "still-killed warning shown" ;; *) ng "no warning (got: $out)" ;; esac
[ "$(printf '%s\n' "$out" | grep -c 'still killed')" = "1" ] && ok "reported once" || ng "reported more than once"
cmp -s "$H14/a/.git/hooks/pre-push" "$TMP/h14.orig" && ok "content unchanged" || ng "content changed"

echo "=== T15: the exec probe runs no line of the hook (real probe file) ==="
R15="$TMP/r15"; mkdir -p "$R15"
printf '#!/bin/bash\ntouch "%s/ran"\n' "$R15" > "$R15/hook"; chmod +x "$R15/hook"
( unset HOOK_EXEC_PROBE_ENV; . "$HERE/lib/hook-stub.sh"; hook_exec_killed "$R15/hook" ) && ng "reported killed" || ok "not killed"
[ ! -e "$R15/ran" ] && ok "hook body did not run" || ng "hook body ran during the probe"

echo "=== T16: non-bash hooks and non-macOS are not probed ==="
H16="$TMP/heal16"; mkdir -p "$H16"; mkrepo "$H16/a"
printf '#!/bin/sh\nexit 0\n' > "$H16/a/.git/hooks/post-merge"; chmod +x "$H16/a/.git/hooks/post-merge"
printf '#!/bin/bash\nexit 0\n' > "$H16/a/.git/hooks/pre-commit"; chmod +x "$H16/a/.git/hooks/pre-commit"
kill_mark "$H16/a/.git/hooks/post-merge"; kill_mark "$H16/a/.git/hooks/pre-commit"
i_sh="$(inode "$H16/a/.git/hooks/post-merge")"; i_bash="$(inode "$H16/a/.git/hooks/pre-commit")"
HOOK_EXEC_PROBE_OS=Linux bash "$HERE/heal-hook-stubs.sh" "$H16" >/dev/null 2>&1
[ "$(inode "$H16/a/.git/hooks/pre-commit")" = "$i_bash" ] && ok "non-macOS: nothing recreated" || ng "recreated on non-macOS"
bash "$HERE/heal-hook-stubs.sh" "$H16" >/dev/null 2>&1
[ "$(inode "$H16/a/.git/hooks/post-merge")" = "$i_sh" ] && ok "#!/bin/sh hook not touched" || ng "sh hook recreated"
[ "$(inode "$H16/a/.git/hooks/pre-commit")" != "$i_bash" ] && ok "bash hook recreated on macOS" || ng "bash hook not recreated"

echo "=== T17: --surface groups restored / recreated / still-killed under their own headings ==="
H17="$TMP/heal17"; mkdir -p "$H17"
mk_tracked_repo "$H17/a"
stub "$HERE/commit-msg-leak-guard-runner.sh" > "$H17/a/scripts/hooks/commit-msg"      # installer drift → restored
mkrepo "$H17/b"
printf '#!/bin/bash\nexit 0\n' > "$H17/b/.git/hooks/pre-commit"; chmod +x "$H17/b/.git/hooks/pre-commit"
kill_mark "$H17/b/.git/hooks/pre-commit"                                               # → recreated
printf '#!/bin/bash\nexit 0\n' > "$H17/b/.git/hooks/pre-push"; chmod +x "$H17/b/.git/hooks/pre-push"
echo "$H17/b/.git/hooks/pre-push" > "$FAKE_KILLED_PATHS"                                # → still killed
out="$(bash "$HERE/heal-hook-stubs.sh" --surface "$H17" 2>&1)"
: > "$FAKE_KILLED_PATHS"
case "$out" in *"track 版に戻した"*"/a/scripts/hooks/commit-msg"*"#installer-tracked-stub"*) ok "restored under its heading" ;; *) ng "restored heading (got: $out)" ;; esac
case "$out" in *"kill されていた git hook"*"/b/.git/hooks/pre-commit"*"#killed-hook-stub"*) ok "recreated under its heading" ;; *) ng "recreated heading (got: $out)" ;; esac
case "$out" in *"要対応"*"still killed"*"/b/.git/hooks/pre-push"*) ok "still-killed under the action heading" ;; *) ng "action heading (got: $out)" ;; esac
out2="$(bash "$HERE/heal-hook-stubs.sh" --surface "$H17" 2>&1)"
[ -z "$out2" ] && ok "--surface silent when nothing to do" || ng "--surface not silent: $out2"

echo "=== T18: --check lists killed hooks without writing and exits 1 ==="
H18="$TMP/heal18"; mkdir -p "$H18"; mkrepo "$H18/a"
printf '#!/bin/bash\nexit 0\n' > "$H18/a/.git/hooks/commit-msg"; chmod +x "$H18/a/.git/hooks/commit-msg"
kill_mark "$H18/a/.git/hooks/commit-msg"; i18="$(inode "$H18/a/.git/hooks/commit-msg")"
out="$(bash "$HERE/heal-hook-stubs.sh" --check "$H18" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && ok "exit 1 when a hook is killed" || ng "exit $rc"
case "$out" in "killed: $H18/a/.git/hooks/commit-msg") ok "killed hook listed" ;; *) ng "output: $out" ;; esac
[ "$(inode "$H18/a/.git/hooks/commit-msg")" = "$i18" ] && ok "--check did not recreate" || ng "--check wrote the file"
bash "$HERE/heal-hook-stubs.sh" "$H18" >/dev/null 2>&1
out="$(bash "$HERE/heal-hook-stubs.sh" --check "$H18" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && ok "exit 0 and silent after healing" || ng "after heal: rc=$rc out=$out"

echo
echo "=== Result: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
