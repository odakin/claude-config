#!/bin/bash
# latexdiff-review-snapshot.sh — 共著レビュー用「変更点カラー版 PDF」を 1 コマンドで生成・配備する engine
#
# = このスクリプトが手順の SoT (code-as-SoT)。手法の背景・落とし穴表・「既定」の使い分けは
#   conventions/latex.md#latexdiff-review-snapshot、
#   snapshot の命名規則は conventions/expensive-intermediate-artifacts.md#snapshot-artifact-naming が正本。
#   検証状況: macOS + TeX Live (lualatex) で e2e 済。Windows (git-bash) は未検証
#   (open は command -v guard 済、bash 3.2+ 想定)。
#
# やること (= 共著レビュー中に「相手の push を取り込んだ最新の diff PDF」を回す loop の機械化):
#   1. baseline 版 tex を git revision から取り出す (作業 tree を汚さない、mktemp workdir + aux symlink)
#   2. (option) レビュー markup コマンド (\cl 等) を両版から unwrap (= 中身は残し wrapper だけ除去。
#      理由: latexdiff の \DIFadd{\cl{...}} は ulem 下線が {...} group を改行不能 box 化して
#      行がページ外へ溢れる + diff 内で draft 色は冗長)
#   3. latexdiff (既定: 標準 UNDERLINE style + --math-markup=1 + VERBATIMENV=comment)
#   4. compile cycle (engine ×1 → bibtex → engine ×2)、error 検出 + page 数報告
#   5. (--no-deploy でなければ) snapshot 命名規則で repo に配備:
#        <prefix>-YYYY-MM-DD-HHMM-<base7>-to-<head7>.pdf
#      同 baseline の旧 snapshot は superseded として git rm (--keep-superseded で抑止)、
#      commit + push (+ macOS なら open)
#
# 使い方 (paper repo 内で):
#   latexdiff-review-snapshot.sh --base <rev> [--strip-cmd cl --strip-cmd CL --strip-color Orange]
#
# 前提と guard:
#   - main tex は単一 file 前提 (\input 多 file 構成は sub-file が両版とも working tree 版になる
#     = main file の差分のみ色付く。多 file は latexdiff --flatten の導入を検討、未実装)
#   - repo が upstream より behind なら abort (= 「相手の push が diff に入っていない」事故の防止。
#     pull してから再実行)
#   - main tex が HEAD と異なる working tree 状態なら abort (= snapshot 名の <head7> が嘘になる。
#     commit するか --allow-dirty で "<head7>-dirty" 名を許可)
#   - 複雑な原稿で compile が壊れる場合の追加 flag (--disable-citation-markup / PICTUREENV 等) は
#     --latexdiff-args で注入 (対処表は latex.md の節を参照)
#
# options:
#   --base REV            (必須) baseline revision (= 共著者が最後に見た commit)
#   --repo DIR            対象 repo (default: cwd)
#   --tex FILE            main tex (default: repo 直下で \documentclass を含む唯一の .tex を自動検出)
#   --strip-cmd NAME      \NAME{...} を unwrap (repeatable、両版に適用)
#   --strip-color NAME    \color{NAME} token を除去 (repeatable、両版に適用)
#   --engine CMD          default: lualatex
#   --bib MODE            bibtex|none (default: bibtex)
#   --math-markup N       default: 1
#   --latexdiff-args STR  latexdiff への追加引数 (空白区切りで展開)
#   --out-prefix NAME     default: latexdiff
#   --no-deploy           build のみ (結果 PDF path を表示して終了、repo に触らない)
#   --keep-superseded     同 baseline の旧 snapshot を git rm しない
#   --no-push / --no-open
#   --allow-dirty / --allow-behind
#   --selftest            strip logic + 命名 format の内蔵テスト (TeX 不要)

set -uo pipefail

BASE="" REPO="$PWD" TEX="" ENGINE="lualatex" BIB="bibtex" MATHMARKUP="1"
EXTRA_ARGS="" PREFIX="latexdiff" DEPLOY=1 SUPERSEDE=1 PUSH=1 OPEN=1
ALLOW_DIRTY=0 ALLOW_BEHIND=0
STRIP_CMDS=() STRIP_COLORS=()

die() { echo "ERROR: $*" >&2; exit 1; }

# ---- embedded strip helper (balanced-brace unwrap; escaped brace 対応) ----
write_strip_py() {
cat > "$1" << 'PYEOF'
import sys
def strip_cmd(text, cmd):
    out, i, n = [], 0, len(text)
    pat = '\\' + cmd + '{'
    while i < n:
        j = text.find(pat, i)
        if j < 0:
            out.append(text[i:]); break
        out.append(text[i:j])
        k = j + len(pat); depth = 1
        while k < n and depth > 0:
            if text[k] == '{' and text[k-1] != '\\': depth += 1
            elif text[k] == '}' and text[k-1] != '\\': depth -= 1
            k += 1
        out.append(text[j+len(pat):k-1])
        i = k
    return ''.join(out)

def process(text, cmds, colors):
    for cmd in cmds:
        prev = None
        while prev != text:
            prev = text
            text = strip_cmd(text, cmd)
    for c in colors:
        text = text.replace('\\color{' + c + '}', '')
    return text

if __name__ == '__main__':
    if sys.argv[1] == '--selftest':
        t = r'a \cl{x \eqref{y} {n{e}s\}t}} b \CL{deep \cl{in}} c'
        r = process(t, ['cl', 'CL'], [])
        assert r == r'a x \eqref{y} {n{e}s\}t} b deep in c', repr(r)
        t2 = r'{\color{Orange}multi par} \color{Orange} rest'
        r2 = process(t2, [], ['Orange'])
        assert r2 == r'{multi par}  rest', repr(r2)
        t3 = 'no markup at all'
        assert process(t3, ['cl'], ['Orange']) == t3
        print('strip selftest OK')
        sys.exit(0)
    path = sys.argv[1]
    cmds = [a for a in sys.argv[2].split(',') if a]
    colors = [a for a in sys.argv[3].split(',') if a]
    with open(path) as f: text = f.read()
    with open(path, 'w') as f: f.write(process(text, cmds, colors))
PYEOF
}

# ---- selftest (TeX 不要) ----
run_selftest() {
    local d; d=$(mktemp -d)
    write_strip_py "$d/strip.py"
    python3 "$d/strip.py" --selftest || die "strip selftest failed"
    local name="latexdiff-2026-01-02-0304-abc1234-to-def5678.pdf"
    [[ "$name" =~ ^latexdiff-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[a-f0-9]{7}-to-[a-f0-9]{7}(-dirty)?\.pdf$ ]] \
        || die "naming format regex failed"
    echo "naming format OK"
    rm -rf "$d"
    echo "ALL SELFTESTS PASS"
    exit 0
}

# ---- arg parse ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --base) BASE="$2"; shift 2;;
        --repo) REPO="$2"; shift 2;;
        --tex) TEX="$2"; shift 2;;
        --strip-cmd) STRIP_CMDS+=("$2"); shift 2;;
        --strip-color) STRIP_COLORS+=("$2"); shift 2;;
        --engine) ENGINE="$2"; shift 2;;
        --bib) BIB="$2"; shift 2;;
        --math-markup) MATHMARKUP="$2"; shift 2;;
        --latexdiff-args) EXTRA_ARGS="$2"; shift 2;;
        --out-prefix) PREFIX="$2"; shift 2;;
        --no-deploy) DEPLOY=0; shift;;
        --keep-superseded) SUPERSEDE=0; shift;;
        --no-push) PUSH=0; shift;;
        --no-open) OPEN=0; shift;;
        --allow-dirty) ALLOW_DIRTY=1; shift;;
        --allow-behind) ALLOW_BEHIND=1; shift;;
        --selftest) run_selftest;;
        *) die "unknown option: $1";;
    esac
done

[[ -n "$BASE" ]] || die "--base <rev> は必須 (= 共著者が最後に見た commit)"
command -v latexdiff >/dev/null || die "latexdiff が見つからない"
command -v "$ENGINE" >/dev/null || die "engine '$ENGINE' が見つからない"
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || die "$REPO は git repo でない"

# ---- guard: behind 検出 (= 相手の push 取りこぼし防止) ----
git -C "$REPO" fetch --quiet 2>/dev/null || true
if git -C "$REPO" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    BEHIND=$(git -C "$REPO" rev-list --count 'HEAD..@{u}')
    if [[ "$BEHIND" -gt 0 && "$ALLOW_BEHIND" -eq 0 ]]; then
        die "upstream より $BEHIND commit behind — 相手の push が diff に入らない。pull してから再実行 (or --allow-behind)"
    fi
fi

# ---- main tex 検出 ----
if [[ -z "$TEX" ]]; then
    TEX=$(cd "$REPO" && grep -l '\\documentclass' -- *.tex 2>/dev/null | head -5)
    [[ $(echo "$TEX" | grep -c .) -eq 1 ]] || die "main tex を一意に検出できない — --tex で指定 (候補: $TEX)"
fi
[[ -f "$REPO/$TEX" ]] || die "$REPO/$TEX が無い"

# ---- guard: main tex の dirty 検出 (= snapshot 名の head hash が嘘にならないように) ----
DIRTY_SUFFIX=""
if ! git -C "$REPO" diff --quiet HEAD -- "$TEX"; then
    if [[ "$ALLOW_DIRTY" -eq 1 ]]; then DIRTY_SUFFIX="-dirty";
    else die "$TEX が HEAD と差分あり — commit するか --allow-dirty (名前に -dirty が付く)"; fi
fi

BASE7=$(git -C "$REPO" rev-parse --short=7 "$BASE") || die "baseline '$BASE' を解決できない"
# head 側は「main tex を最後に触った commit」に pin する (= diff の実 input。
# snapshot 配備 commit 等の無関係 commit で名前が変わらない)
HEAD7=$(git -C "$REPO" log -1 --format=%h --abbrev=7 HEAD -- "$TEX")
[[ -n "$HEAD7" ]] || die "$TEX の履歴を解決できない"

# ---- workdir 構築 (作業 tree 不変) ----
D=$(mktemp -d) || die "mktemp 失敗"
echo "workdir: $D"
for entry in "$REPO"/* "$REPO"/.[!.]*; do
    b=$(basename "$entry")
    [[ "$b" == ".git" || "$b" == "$TEX" || "$b" == ${PREFIX}-*.pdf ]] && continue
    [[ -e "$entry" ]] && ln -s "$entry" "$D/$b" 2>/dev/null
done
git -C "$REPO" show "$BASE:$TEX" > "$D/base.tex" || die "git show $BASE:$TEX 失敗"
cp "$REPO/$TEX" "$D/new.tex"

# ---- strip (両版に同一適用 = 未変更 markup が spurious diff にならない) ----
if [[ ${#STRIP_CMDS[@]} -gt 0 || ${#STRIP_COLORS[@]} -gt 0 ]]; then
    write_strip_py "$D/strip.py"
    CMDS=$(IFS=,; echo "${STRIP_CMDS[*]:-}")
    COLORS=$(IFS=,; echo "${STRIP_COLORS[*]:-}")
    python3 "$D/strip.py" "$D/base.tex" "$CMDS" "$COLORS" || die "strip (base) 失敗"
    python3 "$D/strip.py" "$D/new.tex" "$CMDS" "$COLORS" || die "strip (new) 失敗"
    echo "stripped: cmds=[$CMDS] colors=[$COLORS]"
fi

# ---- latexdiff + compile ----
# shellcheck disable=SC2086
latexdiff --math-markup="$MATHMARKUP" --config VERBATIMENV=comment $EXTRA_ARGS \
    "$D/base.tex" "$D/new.tex" > "$D/diff.tex" 2>"$D/latexdiff.err" || die "latexdiff 失敗: $(tail -3 "$D/latexdiff.err")"

( cd "$D" && "$ENGINE" -interaction=nonstopmode diff.tex >/dev/null 2>&1
  [[ "$BIB" == "bibtex" ]] && bibtex diff >/dev/null 2>&1
  "$ENGINE" -interaction=nonstopmode diff.tex >/dev/null 2>&1
  "$ENGINE" -interaction=nonstopmode diff.tex >/dev/null 2>&1 )
[[ -f "$D/diff.pdf" ]] || die "diff.pdf が生成されなかった — $D/diff.log を確認"
NERR=$(grep -c '^!' "$D/diff.log" 2>/dev/null || true)
[[ "${NERR:-0}" -eq 0 ]] || die "compile error ${NERR} 件 — $D/diff.log を確認 (複雑原稿の対処表 = conventions/latex.md の latexdiff 節、--latexdiff-args で flag 注入)"
PAGES=$(grep -o '([0-9]* pages' "$D/diff.log" | tail -1 | tr -dc '0-9')
echo "build OK: ${PAGES:-?} pages, 0 errors"

# ---- deploy ----
NAME="${PREFIX}-$(date +%Y-%m-%d-%H%M)-${BASE7}-to-${HEAD7}${DIRTY_SUFFIX}.pdf"
if [[ "$DEPLOY" -eq 0 ]]; then
    echo "no-deploy: 結果 = $D/diff.pdf (配備時の名前: $NAME)"
    exit 0
fi
cp "$D/diff.pdf" "$REPO/$NAME"
(
    cd "$REPO"
    if [[ "$SUPERSEDE" -eq 1 ]]; then
        for old in ${PREFIX}-*-"${BASE7}"-to-*.pdf; do
            [[ "$old" == "$NAME" || ! -e "$old" ]] && continue
            git rm -q --ignore-unmatch "$old" && echo "superseded: $old"
        done
    fi
    git add "$NAME"
    git commit -q -m "レビュー用 latexdiff snapshot: ${BASE7} → ${HEAD7}${DIRTY_SUFFIX} (${PAGES:-?}pp)

生成: claude-config/scripts/latexdiff-review-snapshot.sh
disposal: レビュー完了後 or 新 snapshot への supersede で削除可" || die "commit 失敗"
    if [[ "$PUSH" -eq 1 ]]; then git push -q || echo "WARN: push 失敗 — 手動で push してください"; fi
)
echo "deployed: $REPO/$NAME"
[[ "$OPEN" -eq 1 ]] && command -v open >/dev/null && open "$REPO/$NAME"
exit 0
