#!/usr/bin/env bash
# repo-sync-sweep.test.sh — repo-sync-sweep.sh の test (一時 dir の bare remote + clone で各状態・並列起動・lock・stash の空振りを検証)
#
# 実行: bash scripts/repo-sync-sweep.test.sh
# git の設定は一時 file に隔離する (= 手元の global config や、 identity 未設定の CI に左右されない。
# engine が作る stash commit の identity もここで与える)。
# 並走の窓は engine の test 用 env (CLAUDE_SYNC_SWEEP_TEST=1 + _TEST_HOLD_PRE / _POST) で決定的に開ける。

set -u
ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/repo-sync-sweep.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
ng()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL="$TMP/gitconfig"
git config --global user.email t@t
git config --global user.name t
git config --global init.defaultBranch main
git config --global commit.gpgsign false
git_quiet() { git "$@"; }

TAB="$(printf '\t')"
# line_of <出力> <種別> <repo 名> → その repo の行 (本文が「repo 名 + 空白 or :」 で始まる行)
line_of() {
  printf '%s\n' "$1" | awk -F'\t' -v k="$2" -v n="$3" '$1==k && (index($2, n" ")==1 || index($2, n":")==1)'
}

# --- remote (bare) + seed clone を作る helper ---
mk_remote() {  # $1 = name
  local r="$TMP/remotes/$1.git"
  mkdir -p "$r"; git_quiet init -q --bare "$r"
  local seed="$TMP/seed-$1"
  git_quiet clone -q "$r" "$seed" 2>/dev/null
  echo "v1" > "$seed/f.txt"
  echo "g1" > "$seed/g.txt"      # remote が触らない tracked file (= 非衝突 dirty 用)
  ( cd "$seed" && git_quiet add -A && git_quiet commit -qm init && git_quiet push -q origin HEAD:main )
  echo "$r"
}
advance_remote() {  # $1 = remote path, $2 = name — remote を 1 commit 進める
  local seed="$TMP/seed2-$2"
  git_quiet clone -q "$1" "$seed"
  echo "v2-$(wc -c < "$seed/f.txt" | tr -d ' ')" >> "$seed/f.txt"
  ( cd "$seed" && git_quiet add -A && git_quiet commit -qm advance && git_quiet push -q origin HEAD:main )
}

ROOT="$TMP/Claude"; mkdir -p "$ROOT"
run() { CLAUDE_SYNC_SWEEP_TEST=1 bash "$ENGINE" --root "$ROOT" "$@"; }

echo "=== T1: --help / 不明な引数 / --root の値なし / root 不在 ==="
out="$(bash "$ENGINE" --help)"
echo "$out" | grep -q "使い方" && ok "--help が使い方を出す" || ng "--help (got: $out)"
out="$(bash "$ENGINE" --bogus)"; rc=$?
[ "$rc" -eq 0 ] && line_of "$out" A repo-sync-sweep | grep -q "不明な引数" \
  && ok "不明な引数は A 行 + exit 0 (fail-open)" || ng "不明な引数 (rc=$rc got: $out)"
out="$(bash "$ENGINE" --root)"
line_of "$out" A repo-sync-sweep | grep -q "値が無い" && ok "--root の値なしは A 行" || ng "--root 値なし (got: $out)"
out="$(bash "$ENGINE" --root "$TMP/nope")"
[ -z "$out" ] && ok "root 不在は沈黙" || ng "root 不在 (got: $out)"

echo "=== T2: 全 repo が up-to-date → 沈黙 / --all では S 行・N 行 ==="
RA="$(mk_remote a)"; git_quiet clone -q "$RA" "$ROOT/repoA"
out="$(run)"
[ -z "$out" ] && ok "all up-to-date → silent" || ng "should be silent (got: $out)"
out="$(run --all)"
[ -n "$(line_of "$out" S repoA)" ] && ok "--all では最新の repo も S 行" || ng "expected S repoA (got: $out)"
mkdir -p "$ROOT/noup" && ( cd "$ROOT/noup" && git_quiet init -q && echo x > x && git_quiet add x && git_quiet commit -qm x )
out="$(run --all)"
[ -n "$(line_of "$out" N noup)" ] && ok "--all では upstream 未設定を N 行" || ng "expected N noup (got: $out)"
out="$(run)"
[ -z "$out" ] && ok "--all 無しでは upstream 未設定も沈黙" || ng "should be silent (got: $out)"

echo "=== T3: behind-only & clean → ff + P 行 ==="
advance_remote "$RA" a
out="$(run)"
[ -n "$(line_of "$out" P repoA)" ] && ok "behind-clean が P 行" || ng "expected P repoA (got: $out)"
b="$(cd "$ROOT/repoA" && git fetch -q; git rev-list --count HEAD..@{u})"
[ "$b" = "0" ] && ok "repoA が最新化された (behind=0)" || ng "repoA still behind=$b"

echo "=== T4: behind & tracked-dirty (非衝突) → stash→ff→pop + 変更保全 ==="
RB="$(mk_remote b)"; git_quiet clone -q "$RB" "$ROOT/repoB"
advance_remote "$RB" b
echo "local-uncommitted" >> "$ROOT/repoB/g.txt"
out="$(run)"
[ -n "$(line_of "$out" P repoB)" ] && ok "behind + tracked-dirty が P 行" || ng "expected P repoB (got: $out)"
b="$(cd "$ROOT/repoB" && git rev-list --count HEAD..@{u})"
[ "$b" = "0" ] && ok "repoB が最新化された (behind=0)" || ng "repoB still behind=$b"
grep -q "local-uncommitted" "$ROOT/repoB/g.txt" && ok "未 commit の変更が pop で保全された" || ng "local 変更が失われた (= 重大)"
[ -z "$(cd "$ROOT/repoB" && git stash list)" ] && ok "stash entry が残っていない" || ng "stash が残存"

echo "=== T5: behind & staged dirty → pop --index で staged のまま復元 ==="
RI="$(mk_remote i)"; git_quiet clone -q "$RI" "$ROOT/repoI"
advance_remote "$RI" i
( cd "$ROOT/repoI" && echo "staged-local" >> g.txt && git_quiet add g.txt )
out="$(run)"
b="$(cd "$ROOT/repoI" && git rev-list --count HEAD..@{u})"
[ "$b" = "0" ] && ok "staged dirty でも最新化された" || ng "repoI still behind=$b"
st="$(cd "$ROOT/repoI" && git diff --cached --name-only)"
[ "$st" = "g.txt" ] && ok "staged のまま復元された (= 並列 session の staging window を壊さない)" || ng "staged が失われた (got: '$st')"

echo "=== T6: behind & untracked のみ → stash せず ff ==="
RF="$(mk_remote f)"; git_quiet clone -q "$RF" "$ROOT/repoF"
advance_remote "$RF" f
echo "scratch" > "$ROOT/repoF/untracked-only.txt"
out="$(run)"
b="$(cd "$ROOT/repoF" && git rev-list --count HEAD..@{u})"
[ "$b" = "0" ] && ok "untracked のみでも最新化された" || ng "repoF still behind=$b"
[ -f "$ROOT/repoF/untracked-only.txt" ] && ok "untracked file はそのまま" || ng "untracked file が消えた"
[ -z "$(cd "$ROOT/repoF" && git stash list)" ] && ok "untracked のみでは stash しない" || ng "不要な stash が作られた"

echo "=== T7a: 未 commit の変更と upstream が同じ file → stash せず A 行 (#autostash-foreign-wip) ==="
RG="$(mk_remote g)"; git_quiet clone -q "$RG" "$ROOT/repoG"
advance_remote "$RG" g
echo "conflicting-local" >> "$ROOT/repoG/f.txt"
out="$(run)"
line_of "$out" A repoG | grep -q "同じ file に当たる (f.txt)" \
  && ok "重なりを A 行で出し、 file 名を添えた" || ng "expected A repoG 同じ file (got: $out)"
[ "$(cd "$ROOT/repoG" && git rev-list --count HEAD..@{u})" -gt 0 ] && grep -q "conflicting-local" "$ROOT/repoG/f.txt" \
  && [ -z "$(cd "$ROOT/repoG" && git stash list)" ] \
  && ok "重なる repo には触らない (behind のまま・変更そのまま・stash なし)" || ng "重なる repo に触った"

echo "=== T7: (重なり検査を外して) pop conflict → 自動解決せず、 stash list で確かめて「残っている」 と出す ==="
out="$(CLAUDE_SYNC_SWEEP_TEST_SKIP_OVERLAP=1 run)"
line_of "$out" A repoG | grep -q "stash pop が conflict" && ok "pop conflict が A 行" || ng "expected A repoG conflict (got: $out)"
[ -n "$(cd "$ROOT/repoG" && git stash list)" ] && ok "stash entry が残っている (= 変更は失われていない)" || ng "stash が消えた"
line_of "$out" A repoG | grep -q "stash に残っている (確認済: stash@{0}" \
  && ok "「stash に残っている」 を stash list で確認してから出した" || ng "確認済 + ref が無い (got: $out)"
line_of "$out" A repoG | grep -q 'checkout -- \. &&' \
  && ng "unmerged path で失敗する git checkout -- . を案内している" || ok "失敗する復旧手順 (git checkout -- . &&) を案内しない"
printf '%s\n' "$out" | grep -v "^[PAULSN]$TAB" | grep -q . \
  && ng "契約外の行 (git の出力) が混ざった (got: $out)" || ok "出力は全行「種別<TAB>本文」 (git の出力を漏らさない)"

echo "=== T8: kill switch (CLAUDE_SYNC_AUTOSTASH=0) → stash せず A 行のみ ==="
RH="$(mk_remote h)"; git_quiet clone -q "$RH" "$ROOT/repoH"
advance_remote "$RH" h
echo "local-uncommitted" >> "$ROOT/repoH/g.txt"
out="$(CLAUDE_SYNC_AUTOSTASH=0 run)"
line_of "$out" A repoH | grep -q "auto-stash 無効化中" && ok "kill switch で A 行のみ" || ng "expected A repoH 無効化中 (got: $out)"
b="$(cd "$ROOT/repoH" && git rev-list --count HEAD..@{u})"
[ "$b" -gt 0 ] && ok "kill switch 時は最新化しない (behind=$b)" || ng "kill switch なのに最新化された"

echo "=== T9: diverged → A 行のみ ==="
RC="$(mk_remote c)"; git_quiet clone -q "$RC" "$ROOT/repoC"
advance_remote "$RC" c
( cd "$ROOT/repoC" && echo "localcommit" >> g.txt && git_quiet add -A && git_quiet commit -qm local )
out="$(run)"
line_of "$out" A repoC | grep -q "diverged" && ok "diverged が A 行" || ng "expected A repoC diverged (got: $out)"

echo "=== T10: ahead-only → U 行のみ (push しない) ==="
RD="$(mk_remote d)"; git_quiet clone -q "$RD" "$ROOT/repoD"
( cd "$ROOT/repoD" && echo "hoist" >> h.txt && git_quiet add -A && git_quiet commit -qm hoist )
out="$(run)"
[ -n "$(line_of "$out" U repoD)" ] && ok "ahead-only が U 行" || ng "expected U repoD (got: $out)"
a="$(cd "$ROOT/repoD" && git rev-list --count @{u}..HEAD)"
[ "$a" = "1" ] && ok "repoD は push されていない (ahead=1)" || ng "repoD ahead=$a"

echo "=== T11: fetch 失敗は「同期済み」 に化けず A 行 + 手順は実際の root を指す ==="
RE="$(mk_remote e)"; git_quiet clone -q "$RE" "$ROOT/repoE"
advance_remote "$RE" e
b="$(cd "$ROOT/repoE" && git rev-list --count HEAD..@{u})"
[ "$b" = "0" ] && ok "repoE は fetch 前なので behind=0 に見える (= 事故の前提条件)" || ng "repoE should look behind=0 (got: $b)"
rm -rf "$RE"
out="$(run)"
line_of "$out" A repoE | grep -q "fetch 未完了" && ok "fetch 失敗が A 行" || ng "expected A repoE fetch 未完了 (got: $out)"
line_of "$out" A repoE | grep -qF "cd $ROOT/repoE" && ok "手順の path は --root を指す (~/Claude 決め打ちでない)" || ng "path が root を指さない (got: $out)"

# ---- 並走 (conventions/hook-authoring.md#cross-session-hook-concurrency) ----
# 以下は test ごとに専用 ROOT で回す (= 上の repo 群の状態に左右されない)。
mk_behind_dirty() {  # $1 = root, $2 = remote 名, $3 = repo 名 → behind=1 ∧ g.txt が未 commit
  local r; r="$(mk_remote "$2")"; git_quiet clone -q "$r" "$1/$3"
  advance_remote "$r" "$2"
  echo "local-wip" >> "$1/$3/g.txt"
}
lockdir()   { echo "$1/.git/claude-sync-sweep.lock"; }
behind_of() { (cd "$1" && git fetch -q 2>/dev/null; git rev-list --count HEAD..@{u}); }
stash_n()   { (cd "$1" && git stash list | wc -l | tr -d ' '); }
bg_run() {  # bg_run <out> [VAR=val ...] — 背景で engine を起動 (pid は $!)
  local out="$1"; shift
  env "$@" CLAUDE_SYNC_SWEEP_TEST=1 bash "$ENGINE" --root "$ROOT" > "$out" 2>&1 &
}
wait_for() {  # wait_for <秒> <条件式> — 条件が真になるまで 0.1 秒刻みで待つ
  local i=0 n=$(( $1 * 10 )); shift
  while [ "$i" -lt "$n" ]; do eval "$1" && return 0; sleep 0.1; i=$((i+1)); done
  return 1
}

echo "=== T12: 生きた holder の lock がある repo は skip し L 行 (lock は消さない) ==="
ROOT="$TMP/root12"; mkdir -p "$ROOT"; mk_behind_dirty "$ROOT" j repoJ
sleep 60 & HOLDER=$!
mkdir "$(lockdir "$ROOT/repoJ")"; echo "$HOLDER $(date +%s) 1" > "$(lockdir "$ROOT/repoJ")/owner"
out="$(run)"
line_of "$out" L repoJ | grep -q "skip" && line_of "$out" L repoJ | grep -q "pid $HOLDER" \
  && ok "lock 中の repo を skip と L 行 (holder の pid 付き)" || ng "expected L repoJ skip + pid (got: $out)"
[ "$(behind_of "$ROOT/repoJ")" -gt 0 ] && grep -q local-wip "$ROOT/repoJ/g.txt" && [ "$(stash_n "$ROOT/repoJ")" = 0 ] \
  && ok "lock 中の repo には触らない (behind のまま・変更そのまま・stash なし)" || ng "lock 中の repo に触った"
[ -d "$(lockdir "$ROOT/repoJ")" ] && ok "生きた holder の lock を消さない" || ng "他人の lock を消した"
kill "$HOLDER" 2>/dev/null; wait "$HOLDER" 2>/dev/null

echo "=== T13: 持ち主の死んだ lock / 古すぎる lock は除去して処理し L 行 ==="
ROOT="$TMP/root13"; mkdir -p "$ROOT"; mk_behind_dirty "$ROOT" k repoK
sh -c 'exit 0' & DEAD=$!; wait "$DEAD"
mkdir "$(lockdir "$ROOT/repoK")"; echo "$DEAD $(date +%s) 1" > "$(lockdir "$ROOT/repoK")/owner"
out="$(run)"
line_of "$out" L repoK | grep -q "古い lock" && ok "死んだ holder の lock を除去したと L 行" || ng "expected L repoK 古い lock (got: $out)"
[ "$(behind_of "$ROOT/repoK")" = 0 ] && grep -q local-wip "$ROOT/repoK/g.txt" && [ "$(stash_n "$ROOT/repoK")" = 0 ] \
  && ok "除去後は通常どおり stash→ff→pop" || ng "除去後の処理が壊れた"
[ ! -e "$(lockdir "$ROOT/repoK")" ] && ok "処理後に自分の lock を解放した" || ng "lock が残った"
mk_behind_dirty "$ROOT" k2 repoK2          # 年齢による stale: holder は生きているが取得から LOCK_STALE 秒超
sleep 60 & HOLDER=$!
mkdir "$(lockdir "$ROOT/repoK2")"; echo "$HOLDER $(( $(date +%s) - 100 )) 1" > "$(lockdir "$ROOT/repoK2")/owner"
out="$(CLAUDE_SYNC_SWEEP_LOCK_STALE=30 run)"
line_of "$out" L repoK2 | grep -q "古い lock" && [ "$(behind_of "$ROOT/repoK2")" = 0 ] \
  && ok "取得から LOCK_STALE 秒を超えた lock は holder が生きていても除去" || ng "expected L repoK2 古い lock + 最新化 (got: $out)"
kill "$HOLDER" 2>/dev/null; wait "$HOLDER" 2>/dev/null

echo "=== T14: 2 本同時 (先発が stash を持っている間に後発) → 後発は skip、 変更は 1 回だけ stash→pop ==="
ROOT="$TMP/root14"; mkdir -p "$ROOT"; mk_behind_dirty "$ROOT" l repoL
bg_run "$TMP/t14a.out" CLAUDE_SYNC_SWEEP_TEST_HOLD_POST=3; PA=$!
wait_for 10 '[ "$(stash_n "$ROOT/repoL")" = 1 ]' || ng "先発が stash しなかった (= test の前提崩れ)"
bg_run "$TMP/t14b.out"; PB=$!
wait "$PA" "$PB"
outA="$(cat "$TMP/t14a.out")"; outB="$(cat "$TMP/t14b.out")"
line_of "$outB" L repoL | grep -q "skip" && ok "後発は lock を見て skip と L 行" || ng "expected L skip in B (got: $outB)"
[ -n "$(line_of "$outA" P repoL)" ] && ok "先発が最新化を完了した" || ng "expected P in A (got: $outA)"
[ "$(behind_of "$ROOT/repoL")" = 0 ] && grep -q local-wip "$ROOT/repoL/g.txt" && [ "$(stash_n "$ROOT/repoL")" = 0 ] \
  && ok "最終状態: 最新・変更保全・stash 残骸なし" || ng "最終状態が壊れた"
printf '%s\n%s\n' "$outA" "$outB" | grep -q "stash に残っている" \
  && ng "誤報「stash に残っている」 が出た" || ok "誤報「stash に残っている」 は出ていない"
[ ! -e "$(lockdir "$ROOT/repoL")" ] && ok "lock は解放された" || ng "lock が残った"

echo "=== T15: 2 本を完全同時に起動 ×3 → fetch 衝突は再試行で吸収・最新化は 1 回・誤報なし ==="
t15ok=1
for rnd in 1 2 3; do
  ROOT="$TMP/root15-$rnd"; mkdir -p "$ROOT"; mk_behind_dirty "$ROOT" "m$rnd" repoM
  bg_run "$TMP/t15a.out"; PA=$!; bg_run "$TMP/t15b.out"; PB=$!
  wait "$PA" "$PB"
  both="$(cat "$TMP/t15a.out" "$TMP/t15b.out")"
  np="$(line_of "$both" P repoM | wc -l | tr -d ' ')"
  if [ "$(behind_of "$ROOT/repoM")" != 0 ] || ! grep -q local-wip "$ROOT/repoM/g.txt" \
     || [ "$(stash_n "$ROOT/repoM")" != 0 ] || [ "$np" -gt 1 ] || [ -e "$(lockdir "$ROOT/repoM")" ] \
     || printf '%s\n' "$both" | grep -q -e "stash に残っている" -e "fetch 未完了" -e "何も作らなかった"; then
    t15ok=0; echo "    round $rnd: np=$np"; printf '%s\n' "$both" | sed 's/^/    | /'
  fi
done
[ "$t15ok" = 1 ] && ok "3 回とも: 最新・変更保全・stash 残骸なし・最新化 1 回・lock 解放・fetch 未完了/誤報なし" \
  || ng "同時起動で不変条件が崩れた (上の round 出力参照)"

echo "=== T16: stash した変更が途中で別 process に pop された → 「残っている」 と言わず sha と探し方 ==="
ROOT="$TMP/root16"; mkdir -p "$ROOT"; mk_behind_dirty "$ROOT" n repoN
bg_run "$TMP/t16.out" CLAUDE_SYNC_SWEEP_TEST_HOLD_POST=2; PA=$!
wait_for 10 '[ "$(stash_n "$ROOT/repoN")" = 1 ]' || ng "stash されなかった (= test の前提崩れ)"
( cd "$ROOT/repoN" && git stash pop -q )          # sweep 以外の actor が pop する
wait "$PA"; out="$(cat "$TMP/t16.out")"
line_of "$out" A repoN | grep -q "stash list に無い" && line_of "$out" A repoN | grep -q "fsck --unreachable --no-reflogs" \
  && ok "stash が無いと確かめて、 sha と探し方を出した" || ng "expected 無い + fsck (got: $out)"
line_of "$out" A repoN | grep -q "stash に残っている" \
  && ng "無い stash を「残っている」 と言った" || ok "無い stash を「残っている」 と言っていない"
s7="$(printf '%s\n' "$out" | sed -n 's/.*stash した変更 (\([0-9a-f]*\)).*/\1/p' | head -1)"
[ -n "$s7" ] && [ -z "$(cd "$ROOT/repoN" && git diff "$s7" -- $(git stash show --name-only "$s7"))" ] \
  && ok "案内した比較手順 (git diff <sha> -- <stash の file>) で worktree との一致を確かめられた" || ng "比較手順が使えない (sha='$s7')"
# ⚠️ 案内の sha は full でなければならない: `git stash show|apply <N>` は数字だけの引数を stash@{N}
#    と解釈するので、 short sha が全桁数字だと (7 桁で約 3.7%) 案内どおり打つと壊れる。
#    上の比較手順 assert だけでは、 その 3.7% を引いたときにしか落ちない (= CI の flaky になる)。
#    一般則 = conventions/shell-env.md#ambiguous-identifier-in-issued-commands
#            + conventions/debugging-discipline.md#flaky-is-a-symptom
[ "${#s7}" -eq 40 ] && ok "案内の sha は full (= 全桁数字の short sha が stash@{N} と誤解される穴を塞いだ)" \
  || ng "案内の sha が ${#s7} 桁 ('$s7') — full でないと全桁数字のとき git stash show/apply が stash@{N} と解釈する"
grep -q local-wip "$ROOT/repoN/g.txt" && ok "変更は worktree に在る" || ng "変更が消えた"

echo "=== T17: stash push が何も作らなかった (直前に別 process が stash) → 他人の stash を pop せず中止 ==="
ROOT="$TMP/root17"; mkdir -p "$ROOT"; mk_behind_dirty "$ROOT" o repoO
bg_run "$TMP/t17.out" CLAUDE_SYNC_SWEEP_TEST_HOLD_PRE=2; PA=$!
wait_for 10 '[ -d "$(lockdir "$ROOT/repoO")" ]' || ng "lock が取られなかった (= test の前提崩れ)"
sleep 0.5                                           # 先発が lock 内で状態を読み直し終えるのを待つ
( cd "$ROOT/repoO" && git_quiet stash push -q -m foreign )   # 別 actor が先に stash する
wait "$PA"; out="$(cat "$TMP/t17.out")"
line_of "$out" A repoO | grep -q "何も作らなかった" && ok "自分の stash が作られなかったことを検出して中止" || ng "expected 何も作らなかった (got: $out)"
[ "$(stash_n "$ROOT/repoO")" = 1 ] && ( cd "$ROOT/repoO" && git stash list | grep -q foreign ) \
  && ok "他人の stash は pop されずに残っている" || ng "他人の stash を pop した"
[ "$(behind_of "$ROOT/repoO")" -gt 0 ] && ok "中止したので最新化していない" || ng "中止したはずが最新化した"

# ---------- _bg_fetch: timeout した repo を裏で完走させる (2026-09-12) ----------
# engine 本体は 8s timeout を強制的に起こせないので、 関数だけ取り出して単体で回す。
# 守る性質: ① 裏 fetch が実際に remote ref を進める ② 完走後に lock を外す
# ③ lock 保持中は二重起動しない ④ kill switch で投げない
echo "== _bg_fetch (裏 fetch で ratchet を断つ) =="
BGF="$(sed -n '/^_bg_fetch() {/,/^}/p' "$ENGINE")"
bgr="$(mk_remote bgf)"
bgc="$TMP/bgf"
git_quiet clone -q "$bgr" "$bgc"
advance_remote "$bgr" bgf
mkdir -p "$TMP/fok"

(
  eval "$BGF"
  _FETCHOK="$TMP/fok"
  _TIMEOUT_BIN="$(command -v timeout 2>/dev/null || command -v gtimeout 2>/dev/null || true)"
  _bg_fetch "$bgc"
  i=0
  while [ -d "$bgc/.git/claude-bg-fetch.lock" ] && [ "$i" -lt 100 ]; do sleep 0.2; i=$((i+1)); done
)

if [ -e "$TMP/fok/.bg-bgf" ]; then ok "_bg_fetch: 報告用 marker を書く"; else ng "_bg_fetch: marker が無い"; fi
if [ -d "$bgc/.git/claude-bg-fetch.lock" ]; then ng "_bg_fetch: 完走後も lock が残る"; else ok "_bg_fetch: 完走後に lock を外す"; fi
if [ "$( cd "$bgc" && git rev-list --count HEAD..@{u} 2>/dev/null )" -ge 1 ]; then
  ok "_bg_fetch: 裏 fetch が remote ref を進めた"
else
  ng "_bg_fetch: remote ref が進んでいない (= 裏 fetch が走っていない)"
fi

# ③ lock 保持中は起動しない
mkdir -p "$bgc/.git/claude-bg-fetch.lock"
rm -f "$TMP/fok/.bg-bgf"
( eval "$BGF"; _FETCHOK="$TMP/fok"; _TIMEOUT_BIN=""; _bg_fetch "$bgc" )
if [ -e "$TMP/fok/.bg-bgf" ]; then ng "_bg_fetch: lock 保持中に二重起動した"; else ok "_bg_fetch: lock 保持中は起動しない"; fi

# ④ kill switch
rm -rf "$bgc/.git/claude-bg-fetch.lock"
( eval "$BGF"; _FETCHOK="$TMP/fok"; _TIMEOUT_BIN=""; CLAUDE_SYNC_SWEEP_BG=0 _bg_fetch "$bgc" )
if [ -e "$TMP/fok/.bg-bgf" ]; then ng "_bg_fetch: CLAUDE_SYNC_SWEEP_BG=0 でも起動した"; else ok "_bg_fetch: kill switch で投げない"; fi

echo
echo "==== RESULT: PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ]
