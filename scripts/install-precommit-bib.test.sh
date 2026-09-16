#!/usr/bin/env bash
# install-precommit-bib.test.sh — install-precommit-bib.sh の test (repo が管理する pre-commit を置き換えない)
#
#   P1  hook の無い素の repo → pre-commit-bib を link / 再実行で変化なし
#   P2  repo の installer が張った link (track 済み hooks/pre-commit、 chain あり) → そのまま、 .bak なし
#   P3  他ツールの untrack な pre-commit (通常 file) → そのまま、 .bak なし
#   P4  2026-09-16 の実例: 宣言した repo の slot に pre-commit-bib → 置き換えず finding、 --check exit 1、
#       repo の installer を走らせた後は --check exit 0
#   P5  宣言した repo の新しい clone (hook 無し) → pre-commit-bib を入れず finding
#   P6  相対 link で repo の track 済み hook を指す (scripts/pre-commit.sh 型、 chain なし) → そのまま
#   P7  core.hooksPath の track 済み hook → そのまま、 .git/hooks に何も作らない
#   P8  旧版のコピー → link に置き換え / 別の場所の pre-commit-bib への link → 張り直し
#   P9  pre-push だけの installer (pre-commit に触れない) → 宣言とみなさず pre-commit-bib を入れる
#   P10 public marker の repo → 触らない
#   P11 Windows (copy): 素の repo に copy / 他の hook はそのまま / 再実行で変化なし
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$HERE/install-precommit-bib.sh"
SRC="$HERE/pre-commit-bib"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  ok: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  NG: $1"; }

mkrepo() {  # $1 = dir
  git init -q "$1"
  git -C "$1" config user.name t
  git -C "$1" config user.email t@example.invalid
  git -C "$1" config commit.gpgsign false
}
commit_all() { git -C "$1" add -A && git -C "$1" commit -q --no-verify -m init; }
no_bak() { ! ls "$1/.git/hooks" 2>/dev/null | grep -q 'pre-commit\.bak'; }
repo_hook() {  # $1 = file: 検査 gate を走らせてから pre-commit-bib を chain する repo の hook
  printf '#!/bin/bash\necho gate\nBIBFIX="$HOME/Claude/claude-config/scripts/pre-commit-bib"\nif [ -x "$BIBFIX" ]; then "$BIBFIX"; fi\n' > "$1"
  chmod +x "$1"
}
declared_repo() {  # $1 = dir: hooks/pre-commit + scripts/install-hooks.sh を track (検証 repo の template と同じ形)
  mkrepo "$1"
  mkdir -p "$1/hooks" "$1/scripts"
  repo_hook "$1/hooks/pre-commit"
  printf '#!/bin/bash\nset -e\nREPO="$(cd "$(dirname "$0")/.." && pwd)"\nln -sf "$REPO/hooks/pre-commit" "$REPO/.git/hooks/pre-commit"\n' > "$1/scripts/install-hooks.sh"
  commit_all "$1"
}

echo "=== P1: plain repo gets pre-commit-bib; re-run changes nothing ==="
R="$TMP/p1"; mkrepo "$R"
bash "$SUT" "$R" >/dev/null 2>&1
[ -L "$R/.git/hooks/pre-commit" ] && [ "$R/.git/hooks/pre-commit" -ef "$SRC" ] && ok "linked" || ng "not linked"
out="$(bash "$SUT" "$R" 2>&1)"
echo "$out" | grep -q "Already up to date: 1 repos" && ok "re-run is up to date" || ng "re-run output: $out"

echo "=== P2: link installed by the repo's own installer is kept ==="
R="$TMP/p2"; declared_repo "$R"
bash "$R/scripts/install-hooks.sh"
before="$(cat "$R/hooks/pre-commit")"
out="$(bash "$SUT" "$R" 2>&1)"
[ "$(readlink "$R/.git/hooks/pre-commit")" = "$R/hooks/pre-commit" ] && ok "link target kept" || ng "link changed -> $(readlink "$R/.git/hooks/pre-commit")"
[ "$(cat "$R/hooks/pre-commit")" = "$before" ] && ok "tracked hook content unchanged" || ng "tracked hook rewritten"
no_bak "$R" && ok "no backup" || ng "backup created"
echo "$out" | grep -q "chains pre-commit-bib" && ok "reports the chain" || ng "output: $out"
bash "$SUT" --check "$R" >/dev/null 2>&1 && ok "--check clean" || ng "--check flagged a working repo"

echo "=== P3: another tool's untracked pre-commit is kept ==="
R="$TMP/p3"; mkrepo "$R"
printf '#!/bin/sh\necho other-tool\n' > "$R/.git/hooks/pre-commit"; chmod +x "$R/.git/hooks/pre-commit"
out="$(bash "$SUT" "$R" 2>&1)"
grep -q other-tool "$R/.git/hooks/pre-commit" && [ ! -L "$R/.git/hooks/pre-commit" ] && ok "kept" || ng "replaced"
no_bak "$R" && ok "no backup" || ng "backup created"
echo "$out" | grep -q "does not call pre-commit-bib" && ok "reports missing chain" || ng "output: $out"

echo "=== P4: declared repo whose slot holds pre-commit-bib (2026-09-16) ==="
R="$TMP/p4"; declared_repo "$R"
ln -s "$SRC" "$R/.git/hooks/pre-commit"
out="$(bash "$SUT" "$R" 2>&1)"
[ "$R/.git/hooks/pre-commit" -ef "$SRC" ] && ok "installer does not guess the repo hook" || ng "installer changed the slot"
echo "$out" | grep -q "⚠ p4: the repo manages its own pre-commit, but the active pre-commit is claude-config pre-commit-bib" && ok "install mode warns" || ng "output: $out"
chk="$(bash "$SUT" --check "$R" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && echo "$chk" | grep -q "scripts/install-hooks.sh" && ok "--check exit 1 with the repo installer" || ng "--check rc=$rc: $chk"
bash "$R/scripts/install-hooks.sh"
bash "$SUT" --check "$R" >/dev/null 2>&1 && ok "--check clean after the repo installer" || ng "--check still flags"

echo "=== P5: fresh clone of a declared repo ==="
R="$TMP/p5"; declared_repo "$R"
out="$(bash "$SUT" "$R" 2>&1)"
[ ! -e "$R/.git/hooks/pre-commit" ] && [ ! -L "$R/.git/hooks/pre-commit" ] && ok "pre-commit-bib not installed" || ng "something installed"
echo "$out" | grep -q "active pre-commit is missing" && ok "warns" || ng "output: $out"
bash "$SUT" --check "$R" >/dev/null 2>&1; [ $? -eq 1 ] && ok "--check exit 1" || ng "--check did not flag"

echo "=== P6: relative link to a tracked repo hook without chain ==="
R="$TMP/p6"; mkrepo "$R"; mkdir -p "$R/scripts"
printf '#!/bin/bash\necho readme-gate\n' > "$R/scripts/pre-commit.sh"; chmod +x "$R/scripts/pre-commit.sh"
printf '#!/bin/bash\nln -sf ../../scripts/pre-commit.sh .git/hooks/pre-commit\n' > "$R/scripts/install-hooks.sh"
commit_all "$R"
ln -s ../../scripts/pre-commit.sh "$R/.git/hooks/pre-commit"
bash "$SUT" "$R" >/dev/null 2>&1
[ "$(readlink "$R/.git/hooks/pre-commit")" = "../../scripts/pre-commit.sh" ] && ok "relative link kept" || ng "link changed"
bash "$SUT" --check "$R" >/dev/null 2>&1 && ok "--check clean" || ng "--check flagged"

echo "=== P7: core.hooksPath with a tracked hook ==="
R="$TMP/p7"; mkrepo "$R"; mkdir -p "$R/.githooks"
repo_hook "$R/.githooks/pre-commit"; commit_all "$R"
git -C "$R" config core.hooksPath .githooks
bash "$SUT" "$R" >/dev/null 2>&1
[ -z "$(git -C "$R" status --porcelain)" ] && ok "worktree clean" || ng "worktree dirty: $(git -C "$R" status --porcelain)"
[ ! -e "$R/.git/hooks/pre-commit" ] && ok "nothing written to .git/hooks" || ng ".git/hooks/pre-commit created"
bash "$SUT" --check "$R" >/dev/null 2>&1 && ok "--check clean" || ng "--check flagged"
R2="$TMP/p7b"; mkrepo "$R2"; mkdir -p "$R2/.githooks"; repo_hook "$R2/.githooks/pre-commit"; commit_all "$R2"
chk="$(bash "$SUT" --check "$R2" 2>&1)"  # exit 1 は想定どおり (pipefail 下で pipe にすると grep の成否が消える)
echo "$chk" | grep -q "core.hooksPath .githooks" && ok "fresh clone: --check suggests hooksPath" || ng "no hooksPath suggestion: $chk"

echo "=== P8: our old copy / stale link are refreshed ==="
R="$TMP/p8"; mkrepo "$R"
cp "$SRC" "$R/.git/hooks/pre-commit"
bash "$SUT" "$R" >/dev/null 2>&1
[ -L "$R/.git/hooks/pre-commit" ] && [ "$R/.git/hooks/pre-commit" -ef "$SRC" ] && ok "copy upgraded to link" || ng "copy not upgraded"
mkdir -p "$TMP/oldbase/claude-config/scripts"; cp "$SRC" "$TMP/oldbase/claude-config/scripts/pre-commit-bib"
rm "$R/.git/hooks/pre-commit"; ln -s "$TMP/oldbase/claude-config/scripts/pre-commit-bib" "$R/.git/hooks/pre-commit"
bash "$SUT" "$R" >/dev/null 2>&1
[ "$R/.git/hooks/pre-commit" -ef "$SRC" ] && ok "stale link relinked" || ng "stale link kept -> $(readlink "$R/.git/hooks/pre-commit")"

echo "=== P9: pre-push-only installer is not a pre-commit declaration ==="
R="$TMP/p9"; mkrepo "$R"; mkdir -p "$R/scripts"
printf '#!/bin/bash\nln -sf "$PWD/hooks/private-pre-push" .git/hooks/pre-push\n' > "$R/scripts/install-hooks.sh"
commit_all "$R"
bash "$SUT" "$R" >/dev/null 2>&1
[ "$R/.git/hooks/pre-commit" -ef "$SRC" ] && ok "pre-commit-bib installed" || ng "not installed"

echo "=== P10: public repo is not touched ==="
R="$TMP/p10"; mkrepo "$R"; mkdir -p "$R/.claude"; : > "$R/.claude/public-repo.marker"
bash "$SUT" "$R" >/dev/null 2>&1
[ ! -e "$R/.git/hooks/pre-commit" ] && ok "untouched" || ng "installed into a public repo"

echo "=== P11: Windows copy mode ==="
R="$TMP/p11"; mkrepo "$R"
PRECOMMIT_BIB_OS=MINGW64_NT bash "$SUT" "$R" >/dev/null 2>&1
[ -f "$R/.git/hooks/pre-commit" ] && [ ! -L "$R/.git/hooks/pre-commit" ] && cmp -s "$R/.git/hooks/pre-commit" "$SRC" && ok "copied" || ng "not copied"
out="$(PRECOMMIT_BIB_OS=MINGW64_NT bash "$SUT" "$R" 2>&1)"
echo "$out" | grep -q "Already up to date: 1 repos" && ok "re-run is up to date" || ng "output: $out"
R2="$TMP/p11b"; mkrepo "$R2"
printf '#!/bin/sh\necho other-tool\n' > "$R2/.git/hooks/pre-commit"
PRECOMMIT_BIB_OS=MINGW64_NT bash "$SUT" "$R2" >/dev/null 2>&1
grep -q other-tool "$R2/.git/hooks/pre-commit" && no_bak "$R2" && ok "foreign hook kept" || ng "foreign hook replaced"

echo
echo "=== Result: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
