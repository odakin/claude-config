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

# ---- (4b) 数字を含む tag (ipv4) も受理で落ちる ----
# `[a-z_]+` だと ipv4 の 4 に当たらず、 token を消した後の空の tag 行が残っていた
ST4B="$T/state4b"
FAKE_IP="$(printf '203.0.%s.9' 113)"   # literal で書くと test file 自身が Tier A で落ちる
IPREPO="$(mk_repo iprepo "endpoint は $FAKE_IP を使う")"
printf '%s   # 文書用 IP (RFC 5737)\n' "$FAKE_IP" > "$IPREPO/.claude/public-tree-accept.txt"
out="$(run "$ST4B" --repo "$IPREPO")"; rc=$?
[ "$rc" -eq 0 ] && check ok "T4b2: ipv4 tag も受理で落ちる" || check ng "T4b2: ipv4 tag も受理で落ちる (rc=$rc: $out)"

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

# ---- (9) finding ありの repo が予算を食い潰さない (= 未記録を先に回す) ----
# 素直に並べると、 finding ありは走査済にならないので --max の枠を毎回そいつらが取り、
# 一度も見ていない repo に永久に到達しない
ST9="$T/state9"; mkdir -p "$ST9"
R9="$T/root9"; mkdir -p "$R9"          # 他の test repo を巻き込まない専用 root
( cd "$R9" && mkdir -p a_dirty/.claude z_fresh/.claude )
for n in a_dirty z_fresh; do
  printf '# marker\n' > "$R9/$n/.claude/public-repo.marker"
  printf 'ふつうの文\n' > "$R9/$n/note.md"
  git -C "$R9/$n" init -q
  git -C "$R9/$n" add -A >/dev/null 2>&1
  git -C "$R9/$n" -c user.email=t@example.com -c user.name=t commit -qm init >/dev/null 2>&1
done
printf '%s\t%s\t2026-01-01\t1\n' "$R9/a_dirty" deadbeef > "$ST9/public-tree-scan.tsv"
out="$(run "$ST9" --all --root "$R9" --max 1)"
printf '%s' "$out" | grep -q 'z_fresh' && check ok "T9: 未記録の repo を先に走査" || check ng "T9: 未記録の repo を先に走査"

# ---- (10) 走査済 repo でも受理一覧は検証される ----
# gate は受理一覧を除外し、走査は台帳で skip する = 後から足した受理 entry を誰も見ない窓
ST10="$T/state10"
run "$ST10" --repo "$CLEAN" >/dev/null 2>&1          # 先に clean として台帳に記録
printf 'NOT-IN-THE-TREE-EITHER   # 後から足した tree に無い token\n' > "$CLEAN/.claude/public-tree-accept.txt"
out="$(run "$ST10" --repo "$CLEAN")"; rc=$?
[ "$rc" -eq 1 ] && check ok "T10: 走査済でも受理一覧は検証される" || check ng "T10: 走査済でも受理一覧は検証される (rc=$rc: $out)"
printf '%s' "$out" | grep -q '台帳に走査済' && check ng "T10b: skip で素通りしない" || check ok "T10b: skip で素通りしない"
rm -f "$CLEAN/.claude/public-tree-accept.txt"

# ---- (12) 台帳は repo ごとの最新の行で読む (2026-11-05): 古い 0 の後に finding を記録したら、
# 次の回は skip しない (= 「どこかの行が 0」 で skip すると、 新しく見つけた finding が次の回から隠れる) ----
ST12="$T/state12"
out="$(run "$ST12" --repo "$DIRTY")"; rc=$?
[ "$rc" -eq 1 ] && check ok "T12: finding を記録する" || check ng "T12: finding を記録する (rc=$rc)"
# 台帳の path は scanner が書いた形 (macOS の /private 付き) をそのまま使い、 その前に古い 0 の行を置く
REC_PATH="$(awk -F'\t' 'NR == 1 { print $1 }' "$ST12/public-tree-scan.tsv" 2>/dev/null)"
{ printf '%s\tdeadbeef\t2026-09-15\t0\n' "$REC_PATH"; cat "$ST12/public-tree-scan.tsv"; } > "$ST12/ledger.new" \
  && mv "$ST12/ledger.new" "$ST12/public-tree-scan.tsv"
out="$(run "$ST12" --repo "$DIRTY")"; rc=$?
printf '%s' "$out" | grep -q '台帳に走査済' \
  && check ng "T12b: 最新の行が finding なら古い 0 で skip しない" || check ok "T12b: 最新の行が finding なら古い 0 で skip しない"

# ---- (11) 照合器の対照 (2026-11-05): 個人層ありの走査では、 先頭に架空の非公開 repo 名を置いた大きな tree を
# 偽の個人層で runner に通す。 照合器が大きな入力で一致を落とす間は 🔴 を出して台帳に 0 を書かない。
# 照合器が直った版 (here-string) では 🔴 が出ず、 clean な tree は台帳に 0 で残る ----
MOCK_LAYER="$T/mock-layer"
mkdir -p "$MOCK_LAYER"
: > "$MOCK_LAYER/.claude-personal-layer"
printf '# mock\n' > "$MOCK_LAYER/CLAUDE.md"
printf '| repo | desc | visibility |\n|---|---|---|\n| `mockpriv-foo/` | mock | private |\n' > "$MOCK_LAYER/repos.md"
ST11="$T/state11"
# 印 ctl-df は未公開文書の逐語の検査 (D-1) がこの機械で armed のときだけ付く = 偽の個人層に源を 1 つ置く (2026-11-09)
MROOT11="$T/mock-claude-root-11"
mkdir -p "$MROOT11/mockpriv-paper"
printf '%s\n' '\begin{document}' \
  'We argue that the amber lantern estimator keeps the patient symmetry intact at every order of the toy series.' \
  '\end{document}' > "$MROOT11/mockpriv-paper/draft.tex"
printf 'discover: %s .tex\n' "$MROOT11" > "$MOCK_LAYER/unpublished-sources.txt"
out="$(XDG_CACHE_HOME="$T/uq-cache11" CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST11" "$SELF" --repo "$CLEAN" 2>/dev/null)"; rc=$?
printf '%s' "$out" | grep -q '照合器の対照が落ちた' \
  && check ng "T11: 照合器は大きな入力でも一致を拾う (対照が落ちた: $out)" || check ok "T11: 照合器は大きな入力でも一致を拾う"
grep -q "	0	ctl-df$" "$ST11/public-tree-scan.tsv" 2>/dev/null \
  && check ok "T11b: 対照が通り漏洩の段まで回った回は clean を 0 (印 ctl-df) で記録" \
  || check ng "T11b: 対照が通り漏洩の段まで回った回は clean を 0 (印 ctl-df) で記録 (rc=$rc)"
rm -f "$MOCK_LAYER/unpublished-sources.txt"
ST11C="$T/state11c"
out="$(CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST11C" "$SELF" --repo "$CLEAN" 2>/dev/null)"; rc=$?
grep -q "	0	ctl$" "$ST11C/public-tree-scan.tsv" 2>/dev/null \
  && check ok "T11f: foil: D-1 の源が無い機械では、 漏洩の段を通っても印は ctl だけ (走査済に数えない)" \
  || check ng "T11f: foil: D-1 の源が無い機械では、 漏洩の段を通っても印は ctl だけ (rc=$rc)"
# 非公開 repo 名を先頭に置いた大きな tree は Tier C で finding になる (= 9/15 型の取りこぼしの再現)
BIGLEAK="$(mk_repo bigleak "$(printf 'see mockpriv-foo for this\n'; awk 'BEGIN { for (i = 1; i <= 6000; i++) printf "line %d: filler\n", i }')")"
out="$(CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST11" "$SELF" --repo "$BIGLEAK" 2>/dev/null)"; rc=$?
[ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q 'tier-c' \
  && check ok "T11c: 大きな tree の非公開 repo 名を拾う" || check ng "T11c: 大きな tree の非公開 repo 名を拾う (rc=$rc: $out)"

# ---- (13) agent の session から回しても漏洩の段まで届く (2026-11-05): 原稿の主張と権限規約の gate は agent の
# session の commit を見るので、 tree 全体が追加に見える棚卸しで規則の文書 (CLAUDE.md) に当たって止まる。
# 棚卸しは agent の env を外して runner を回す (replay-public-gate.sh と同じ) ----
ST13="$T/state13"
RULEDOC="$(mk_repo ruledoc 'ふつうの文。')"
printf '# CLAUDE.md\n\n規則の文書の例。\n' > "$RULEDOC/CLAUDE.md"
git -C "$RULEDOC" add -A >/dev/null 2>&1
git -C "$RULEDOC" -c user.email=t@example.com -c user.name=t commit -qm rule >/dev/null 2>&1
out="$(CLAUDE_CODE_SESSION_ID=scan-test-session CLAUDE_STATE_DIR="$ST13" "$SELF" --repo "$RULEDOC" 2>/dev/null)"; rc=$?
[ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q '0 finding' \
  && check ok "T13: agent の session から回しても漏洩の段まで届く" || check ng "T13: agent の session から回しても漏洩の段まで届く (rc=$rc: $out)"

# ---- (14) 受理済みの Tier A の当たりがあっても Tier D〜F を回す (2026-11-09): runner が A〜C に当たりがあると
# D〜F を回さない作りだった間、 棚卸しはその repo を D〜F を見ずに「受理済みのみの 0」 と記録していた ----
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$SELF")/check-unpublished-quote.py" ]; then
  MROOT="$T/mock-claude-root"
  mkdir -p "$MROOT/mockpriv-paper"
  printf '%s\n' '\begin{document}' \
    'We argue that the velvet compass estimator keeps the gentle balance alive at every order of the toy series.' \
    '\end{document}' > "$MROOT/mockpriv-paper/draft.tex"
  printf 'discover: %s .tex\n' "$MROOT" > "$MOCK_LAYER/unpublished-sources.txt"
  ST14="$T/state14"
  ACC="$(mk_repo accd "setup は ${FAKE_ABS}/Claude/x を見る。
Example: \`the velvet compass estimator keeps the gentle balance alive\` in a rule.")"
  printf '%s   # 見た上で残すと決めた例\n' "$FAKE_ABS" > "$ACC/.claude/public-tree-accept.txt"
  out="$(XDG_CACHE_HOME="$T/uq-cache" CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST14" "$SELF" --repo "$ACC" 2>/dev/null)"; rc=$?
  [ "$rc" -eq 1 ] && grep -q '識別子でない漏洩の段' <<< "$out" \
    && check ok "T14: 受理済みの Tier A の当たりの後も Tier D の当たりを finding にする" \
    || check ng "T14: 受理済みの Tier A の当たりの後も Tier D の当たりを finding にする (rc=$rc: $out)"
  ACC2="$(mk_repo accd2 "setup は ${FAKE_ABS}/Claude/x を見る。")"
  printf '%s   # 見た上で残すと決めた例\n' "$FAKE_ABS" > "$ACC2/.claude/public-tree-accept.txt"
  out="$(XDG_CACHE_HOME="$T/uq-cache" CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST14" "$SELF" --repo "$ACC2" 2>/dev/null)"; rc=$?
  [ "$rc" -eq 0 ] && grep -q 'Tier D-F も通った' <<< "$out" && grep -q "	0	ctl-df$" <<< "$(tail -1 "$ST14/public-tree-scan.tsv")" \
    && check ok "T14b: foil: 受理済みのみで Tier D〜F も通った回は 0 (印 ctl-df) で記録" \
    || check ng "T14b: foil: 受理済みのみで Tier D〜F も通った回は 0 (印 ctl-df) で記録 (rc=$rc: $out)"
  # 印 ctl だけの古い 0 (D〜F を見ていないことがある) は走査済に数えない
  REC14="$(tail -1 "$ST14/public-tree-scan.tsv" | cut -f1)"
  printf '%s\tdeadbeef\t2026-11-07\t0\tctl\n' "$REC14" >> "$ST14/public-tree-scan.tsv"
  out="$(XDG_CACHE_HOME="$T/uq-cache" CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST14" "$SELF" --repo "$ACC2" 2>/dev/null)"
  grep -q '台帳に走査済' <<< "$out" \
    && check ng "T14c: 印 ctl だけの 0 は走査済に数えない" || check ok "T14c: 印 ctl だけの 0 は走査済に数えない"
  out="$(XDG_CACHE_HOME="$T/uq-cache" CLAUDE_PERSONAL_LAYER="$MOCK_LAYER" CLAUDE_STATE_DIR="$ST14" "$SELF" --repo "$ACC2" 2>/dev/null)"
  grep -q '台帳に走査済' <<< "$out" \
    && check ok "T14d: foil: 印 ctl-df の 0 は走査済に数える" || check ng "T14d: foil: 印 ctl-df の 0 は走査済に数える"
  rm -f "$MOCK_LAYER/unpublished-sources.txt"
fi

# ---- (15) 作業リポの機密の検査 (Tier D-2) も棚卸しで走る (2026-11-09): D-2 は remote のある repo でだけ動くので、
# remote の無い一時 repo で回す棚卸しでは黙って素通りしていた。 一時 repo に仮の remote を置く ----
if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$SELF")/check-confidential-leak.py" ]; then
  PAT15="$T/mock-leak-patterns"
  printf 'mock-label\tMOCK-CONF-TOKEN-[0-9]+\n' > "$PAT15"
  ST15="$T/state15"
  D2REPO="$(mk_repo d2repo 'ふつうの文。 MOCK-CONF-TOKEN-42 を含む。')"
  out="$(CLAUDE_LEAK_PATTERNS="$PAT15" CLAUDE_LEAK_SOURCES="$T/no-such-pointer" CLAUDE_STATE_DIR="$ST15" "$SELF" --repo "$D2REPO" 2>/dev/null)"; rc=$?
  [ "$rc" -eq 1 ] && grep -q 'confidential-leak' <<< "$out" \
    && check ok "T15: tree の中の作業リポの機密 (Tier D-2) を finding にする" \
    || check ng "T15: tree の中の作業リポの機密 (Tier D-2) を finding にする (rc=$rc: $out)"
  out="$(CLAUDE_LEAK_PATTERNS="$PAT15" CLAUDE_LEAK_SOURCES="$T/no-such-pointer" CLAUDE_STATE_DIR="$ST15" "$SELF" --repo "$CLEAN" --force 2>/dev/null)"; rc=$?
  [ "$rc" -eq 0 ] && check ok "T15b: foil: その token の無い tree は 0" || check ng "T15b: foil: その token の無い tree は 0 (rc=$rc: $out)"
fi

echo
echo "==== RESULT: PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
