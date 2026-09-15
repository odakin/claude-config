#!/usr/bin/env bash
# scan-public-tree.test.sh — self-tests for the full-tree re-run of the public gate
#
# 固定する invariant:
#   (1) clean な tree は 0 finding で終わり、 台帳に 0 で記録される
#   (2) 既存 file の Tier A leak を見つける (= gate 本体は staged 差分しか見ないので、
#       この走査だけが「gate を入れる前から在った中身」 を捕まえられる)
#   (3) finding ありの repo は台帳で skip されない (= 検出器が自分の finding を隠さない)
#   (4) .claude/public-tree-accept.txt の token は棚卸しでだけ落ちる
#   (5) --force は台帳を無視して走査し直す
#
# 実行: bash scan-public-tree.test.sh   (全 pass で exit 0)

set -uo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)/scan-public-tree.sh"
[ -x "$SELF" ] || { echo "ERROR: $SELF not executable"; exit 1; }

PASS=0
FAIL=0
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

check() {
  if [ "$1" = "ok" ]; then PASS=$((PASS + 1)); echo "  PASS: $2"
  else FAIL=$((FAIL + 1)); echo "  FAIL: $2"; fi
}

# 個人層を切って Tier B/D を対象外にする (= test の決定性。 Tier A だけを見る)
export CLAUDE_PERSONAL_LAYER=none

mk_repo() {  # $1 = name, $2 = ファイル本文
  local d="$T/$1"
  mkdir -p "$d/.claude"
  printf '# marker\n' > "$d/.claude/public-repo.marker"
  printf '%s\n' "$2" > "$d/note.md"
  git -C "$d" init -q
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@example.com -c user.name=t commit -qm init >/dev/null 2>&1
  echo "$d"
}

run() {  # $1 = state dir, 残り = 引数
  local st="$1"; shift
  CLAUDE_STATE_DIR="$st" "$SELF" "$@" 2>/dev/null
}

echo "=== scan-public-tree self-test ==="

# ---- (1) clean ----
ST1="$T/state1"
CLEAN="$(mk_repo clean 'ふつうの文。 path は ~/Claude/ のように書く。')"
out="$(run "$ST1" --repo "$CLEAN")"; rc=$?
[ "$rc" -eq 0 ] && check ok "T1: clean な tree は rc=0" || check ng "T1: clean な tree は rc=0 (rc=$rc: $out)"
grep -q "	0$" "$ST1/public-tree-scan.tsv" 2>/dev/null \
  && check ok "T1b: 台帳に 0 で記録" || check ng "T1b: 台帳に 0 で記録"

# ---- (2) 既存 file の Tier A leak ----
ST2="$T/state2"
# ⚠️ fixture の絶対 path を literal で書かない (= この test file 自身が Tier A で落ちる、
# docs/convention-design-principles.md#detector-fires-on-its-own-signal)。 実行時に組み立てる
FAKE_ABS="/Users""/someone"
DIRTY="$(mk_repo dirty "setup は ${FAKE_ABS}/Claude/x を見る。")"
out="$(run "$ST2" --repo "$DIRTY")"; rc=$?
[ "$rc" -eq 1 ] && check ok "T2: 既に commit 済の Tier A leak を見つける" \
  || check ng "T2: 既に commit 済の Tier A leak を見つける (rc=$rc)"
printf '%s' "$out" | grep -q 'tier-a/abs_path' \
  && check ok "T2b: 見出しに tier 名が出る" || check ng "T2b: 見出しに tier 名が出る"

# ---- (3) finding ありは skip されない ----
out2="$(run "$ST2" --repo "$DIRTY")"; rc2=$?
[ "$rc2" -eq 1 ] && check ok "T3: finding ありは台帳で skip されない" \
  || check ng "T3: finding ありは台帳で skip されない (rc=$rc2)"
printf '%s' "$out2" | grep -q '台帳に走査済' && check ng "T3b: 台帳 skip と言わない" || check ok "T3b: 台帳 skip と言わない"

# ---- (4) 受理 file ----
ST4="$T/state4"
printf '%s   # 見た上で残すと決めた例\n' "$FAKE_ABS" > "$DIRTY/.claude/public-tree-accept.txt"
out="$(run "$ST4" --repo "$DIRTY")"; rc=$?
[ "$rc" -eq 0 ] && check ok "T4: 受理 token は棚卸しで落ちる" || check ng "T4: 受理 token は棚卸しで落ちる (rc=$rc: $out)"
rm -f "$DIRTY/.claude/public-tree-accept.txt"

# ---- (5) --force ----
ST5="$T/state5"
run "$ST5" --repo "$CLEAN" >/dev/null 2>&1
out="$(run "$ST5" --repo "$CLEAN")"
printf '%s' "$out" | grep -q '台帳に走査済' && check ok "T5: 2 回目は台帳で skip" || check ng "T5: 2 回目は台帳で skip"
out="$(run "$ST5" --repo "$CLEAN" --force)"
printf '%s' "$out" | grep -q '台帳に走査済' && check ng "T5b: --force は skip しない" || check ok "T5b: --force は skip しない"

# ---- (6) --all は marker つきだけを見る ----
ST6="$T/state6"
NOMARK="$(mk_repo nomark 'marker の無い repo')"
rm -f "$NOMARK/.claude/public-repo.marker"
out="$(run "$ST6" --all --root "$T")"
printf '%s' "$out" | grep -q 'nomark' && check ng "T6: marker 無しは対象外" || check ok "T6: marker 無しは対象外"

# ---- (7) --max は 1 回で走査する数を区切る ----
ST7="$T/state7"
mk_repo m1 'ふつうの文 1' >/dev/null
mk_repo m2 'ふつうの文 2' >/dev/null
mk_repo m3 'ふつうの文 3' >/dev/null
out="$(run "$ST7" --all --root "$T" --max 2)"
n="$(wc -l < "$ST7/public-tree-scan.tsv" 2>/dev/null | tr -d ' ')"
[ "${n:-0}" -eq 2 ] && check ok "T7: --max 2 で 2 repo だけ走査" || check ng "T7: --max 2 で 2 repo だけ走査 (実際 ${n:-0})"
printf '%s' "$out" | grep -q '中断' && check ok "T7b: 中断を明示する" || check ng "T7b: 中断を明示する"

# ---- (8) 受理一覧は隠し場所にならない ----
ST8="$T/state8"
printf 'THIS-TOKEN-IS-NOWHERE-IN-THE-TREE   # tree に無い文字列\n' > "$CLEAN/.claude/public-tree-accept.txt"
out="$(run "$ST8" --repo "$CLEAN")"; rc=$?
[ "$rc" -eq 1 ] && check ok "T8: tree に無い受理 token は finding" || check ng "T8: tree に無い受理 token は finding (rc=$rc)"
printf '%s' "$out" | grep -q '新しい開示' && check ok "T8b: 理由を明示する" || check ng "T8b: 理由を明示する"
rm -f "$CLEAN/.claude/public-tree-accept.txt"

echo
echo "==== RESULT: PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
