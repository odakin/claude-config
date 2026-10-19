#!/usr/bin/env bash
# latexdiff-review-snapshot.sh — 共著レビュー用「変更点カラー版 PDF」を 1 コマンドで生成・配備（baseline を git rev から取り出し → レビュー markup unwrap --strip-cmd/--strip-color → latexdiff → compile → snapshot 命名〔#snapshot-artifact-naming 準拠、head = main tex 最終 commit に pin〕→ 同 baseline 旧版 supersede → commit+push+open。behind/dirty guard + --selftest 内蔵、conventions/latex.md#latexdiff-review-snapshot）
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
#      行がページ外へ溢れる + diff 内で draft 色は冗長)。
#      実装は ai-collaboration の scripts/review-markup-clean.py を呼ぶ (= 色外しの実装は 1 本、
#      ここには引数の対応だけを持つ)。 探す順 = $AI_COLLABORATION_DIR → claude-config の隣 → 原稿 repo の隣、
#      無ければ停止して clone 先を出す (外さずに続けると溢れた行と draft 色のままの PDF を配ってしまう)
#   3. 数式の silent miss 対策 (既定 ON、--no-math-guard で無効):
#      両版の display-math wrapper macro を本物の環境へ展開 (expand-display-math.py) +
#      preamble の全 macro を latexdiff の safe-command list へ (latexdiff-safecmd.py)。
#      どちらも「compile は通るのに式の変更が無色」になる経路 (latex.md の症状表 2 行)
#   4. latexdiff (既定: 標準 UNDERLINE style + --math-markup=1 + VERBATIMENV=comment)
#      → 出力を check-latexdiff-math-markup.py --scan で検査し、display math 内に
#        無印の変更が残っていれば deploy 前に停止 (--allow-unmarked-math で続行)
#   5. compile cycle (engine ×1 → bibtex → engine ×2)、error 検出 + page 数報告
#   6. (--no-deploy でなければ) snapshot 命名規則で repo に配備:
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
#   --strip-cmd NAME      \NAME{...} を unwrap (repeatable、両版に適用。 = review-markup-clean.py --macro)
#   --strip-color NAME    {\color{NAME}...} の群を開く (repeatable、両版に適用。 = review-markup-clean.py --color。
#                         群の外の \color{NAME} は残る = 残ったら警告。 % コメントの中は触らない)
#   --engine CMD          default: lualatex
#   --bib MODE            bibtex|none (default: bibtex)
#   --math-markup N       default: 1 (2 = coarse、 3 = fine: 式の中の変わった token だけ。 fine の壊れ方は latexdiff-fine-fixups.py が直す)
#   --latexdiff-args STR  latexdiff への追加引数 (空白区切りで展開)
#   --out-prefix NAME     default: latexdiff
#   --no-deploy           build のみ (結果 PDF path を表示して終了、repo に触らない)
#   --keep-superseded     同 baseline の旧 snapshot を git rm しない
#   --no-push / --no-open
#   --allow-dirty / --allow-behind
#   --no-math-guard       wrapper 展開 + safecmd + 無印検査を行わない (= 2026-09-12 以前の挙動)
#   --allow-unmarked-math 無印の数式変更を検出しても停止しない (警告のみ)
#   --selftest            review-markup-clean.py の selftest と引数の対応 + 命名 format + 同梱 5 script の selftest

set -uo pipefail

BASE="" REPO="$PWD" TEX="" ENGINE="lualatex" BIB="bibtex" MATHMARKUP="1"
EXTRA_ARGS="" PREFIX="latexdiff" DEPLOY=1 SUPERSEDE=1 PUSH=1 OPEN=1
ALLOW_DIRTY=0 ALLOW_BEHIND=0 MATH_GUARD=1 ALLOW_UNMARKED=0
STRIP_CMDS=() STRIP_COLORS=()
SCRIPTDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXPANDER="$SCRIPTDIR/expand-display-math.py"
SAFECMD_GEN="$SCRIPTDIR/latexdiff-safecmd.py"
MARKUP_CHECK="$SCRIPTDIR/check-latexdiff-math-markup.py"
DUP_LABELS="$SCRIPTDIR/latexdiff-strip-dup-labels.py"   # deleted copy keeps no \label (whole markup / MOVE), 2026-09-13
FINE_FIX="$SCRIPTDIR/latexdiff-fine-fixups.py"   # repairs of --math-markup=fine output (accent / \frac / deleted-side commands)

die() { echo "ERROR: $*" >&2; exit 1; }

# ---- review markup の除去 = ai-collaboration の review-markup-clean.py (実装は向こうの 1 本) ----
find_cleaner() {
    local d
    for d in "${AI_COLLABORATION_DIR:-}" "$SCRIPTDIR/../../ai-collaboration" "$REPO/../ai-collaboration"; do
        [[ -n "$d" && -f "$d/scripts/review-markup-clean.py" ]] && { echo "$d/scripts/review-markup-clean.py"; return 0; }
    done
    return 1
}

# $1 = cleaner, $2 = tex (その場で書き換える)。 --strip-cmd → --macro / --strip-color → --color
strip_markup() {
    local a=() x
    for x in ${STRIP_CMDS[@]+"${STRIP_CMDS[@]}"}; do a+=(--macro "$x"); done
    for x in ${STRIP_COLORS[@]+"${STRIP_COLORS[@]}"}; do a+=(--color "$x"); done
    python3 "$1" "$2" "$2" ${a[@]+"${a[@]}"}
}

# 群の外に残った \color{NAME} の行数 (% で始まる行は数えない)。 $@ = tex
count_bare_color() {
    local c="$1"; shift
    cat "$@" | grep -v '^[[:space:]]*%' | grep -cF "\\color{$c}"
}

# ---- selftest (TeX 不要) ----
run_selftest() {
    local d; d=$(mktemp -d)
    local cleaner STRIP_CMDS=(cl CL) STRIP_COLORS=(Orange)
    if cleaner=$(find_cleaner); then
        python3 "$cleaner" --selftest >/dev/null || die "review-markup-clean.py selftest failed ($cleaner)"
        echo "review-markup-clean.py selftest OK ($cleaner)"
        printf '%s\n' 'a \cl{x {n}} {\color{Orange}y} \CL{z} % \cl{kept}' '\begin{quote}\color{Orange} w\end{quote}' > "$d/t.tex"
        strip_markup "$cleaner" "$d/t.tex" >/dev/null || die "strip の引数の対応が壊れた"
        [[ "$(cat "$d/t.tex")" == 'a x {n} y z % \cl{kept}'$'\n''\begin{quote}\color{Orange} w\end{quote}' ]] \
            || die "strip の引数の対応が壊れた: $(cat "$d/t.tex")"
        [[ "$(count_bare_color Orange "$d/t.tex")" == 1 ]] || die "群の外の \\color の数え方が壊れた"
        echo "strip mapping OK"
    else
        echo "WARN: review-markup-clean.py が無い (AI_COLLABORATION_DIR / claude-config の隣 / cwd の隣) — strip は未検査"
    fi
    local name="latexdiff-2026-01-02-0304-abc1234-to-def5678.pdf"
    [[ "$name" =~ ^latexdiff-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-[a-f0-9]{7}-to-[a-f0-9]{7}(-dirty)?\.pdf$ ]] \
        || die "naming format regex failed"
    echo "naming format OK"
    rm -rf "$d"
    local s
    for s in "$EXPANDER" "$SAFECMD_GEN" "$MARKUP_CHECK" "$DUP_LABELS" "$FINE_FIX"; do
        if [[ -f "$s" ]]; then
            python3 "$s" --selftest >/dev/null || die "$(basename "$s") selftest failed"
            echo "$(basename "$s") selftest OK"
        else
            echo "WARN: $s 不在 — 数式 guard は未検査"
        fi
    done
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
        --no-math-guard) MATH_GUARD=0; shift;;
        --allow-unmarked-math) ALLOW_UNMARKED=1; shift;;
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
    CLEANER=$(find_cleaner) || die "--strip-cmd / --strip-color は ai-collaboration の scripts/review-markup-clean.py を使う — 見つからない。 claude-config の隣に clone する (git clone https://github.com/odakin/ai-collaboration) か、 置き場所を AI_COLLABORATION_DIR に入れる"
    for side in base new; do
        OUT=$(strip_markup "$CLEANER" "$D/$side.tex") || die "strip ($side) 失敗 — 閉じていない wrapper は上の message の位置"
        echo "stripped $side: ${OUT##*: }"
    done
    CMDS=$(IFS=,; echo "${STRIP_CMDS[*]:-}")
    COLORS=$(IFS=,; echo "${STRIP_COLORS[*]:-}")
    echo "stripped: cmds=[$CMDS] colors=[$COLORS] ($CLEANER)"
    for c in ${STRIP_COLORS[@]+"${STRIP_COLORS[@]}"}; do
        NBARE=$(count_bare_color "$c" "$D/base.tex" "$D/new.tex")
        [[ "${NBARE:-0}" -gt 0 ]] && echo "WARN: 群の外の \\color{$c} が ${NBARE} 行残った (--strip-color は {\\color{$c}…} の群だけを開く) — diff PDF のその範囲は $c のまま"
    done
fi

# ---- 数式 silent miss 対策 (両版に同一適用 = LaTeX 的には no-op) ----
SAFE_ARG=""
if [[ "$MATH_GUARD" -eq 1 ]]; then
    if [[ -f "$EXPANDER" && -f "$SAFECMD_GEN" ]]; then
        python3 "$EXPANDER" "$D/base.tex" "$D/base.tex" || die "display-math wrapper 展開 (base) 失敗"
        python3 "$EXPANDER" "$D/new.tex"  "$D/new.tex"  || die "display-math wrapper 展開 (new) 失敗"
        SAFE=$(python3 "$SAFECMD_GEN" "$D/new.tex") || die "safe-command list の生成に失敗"
        if [[ -n "$SAFE" ]]; then
            SAFE_ARG="--append-safecmd=$SAFE"
            echo "math guard: wrapper 展開 + safecmd $(awk -F, '{print NF}' <<< "$SAFE") macros"
        else
            echo "math guard: wrapper 展開 (preamble に自作 macro なし)"
        fi
    else
        echo "WARN: $EXPANDER / $SAFECMD_GEN が無い — 数式の silent miss guard なしで続行"
        MATH_GUARD=0
    fi
fi

# ---- latexdiff + compile ----
# shellcheck disable=SC2086
latexdiff --math-markup="$MATHMARKUP" --config VERBATIMENV=comment $SAFE_ARG $EXTRA_ARGS \
    "$D/base.tex" "$D/new.tex" > "$D/diff.tex" 2>"$D/latexdiff.err" || die "latexdiff 失敗: $(tail -3 "$D/latexdiff.err")"
# changed (whole markup) or moved blocks appear twice with the same \label -> amsmath "Multiple \label's" is fatal below;
# keep each label on the new copy only (conventions/latex.md#latexdiff-move-artifacts)
# fine markup breaks in recurring ways (accent outside the markup, second argument of \frac outside it,
# deleted-side commands commented out) -> repair before the guard counts unmarked changes
if [[ ( "$MATHMARKUP" == "2" || "$MATHMARKUP" == "coarse" || "$MATHMARKUP" == "3" || "$MATHMARKUP" == "fine" ) && -f "$FINE_FIX" ]]; then
    python3 "$FINE_FIX" fix "$D/diff.tex" || die "latexdiff-fine-fixups.py 失敗"
fi
if [[ -f "$DUP_LABELS" ]]; then
    NDUP=$(python3 "$DUP_LABELS" "$D/diff.tex")
    [[ "${NDUP:-0}" -gt 0 ]] && echo "label guard: 削除側の \label ${NDUP} 件を除去"
fi

# ---- guard: display math 内に無印の変更が残っていないか (= 色の出ない差分 PDF) ----
if [[ "$MATH_GUARD" -eq 1 && -f "$MARKUP_CHECK" ]]; then
    UNMARKED=$(python3 "$MARKUP_CHECK" --scan "$D/diff.tex" | tail -1)
    if [[ "${UNMARKED:-0}" -gt 0 ]]; then
        python3 "$MARKUP_CHECK" --scan "$D/diff.tex" --verbose | head -20
        [[ "$ALLOW_UNMARKED" -eq 1 ]] \
            || die "display math 内に無印の変更 ${UNMARKED} 件 — この PDF は式の変更を色なしで落とす (共著者には「変えていない」に見える)。preamble に新しい構造 macro があるなら LATEXDIFF_BENIGN_EXTRA=名前,名前 で宣言、意図的に無視するなら --allow-unmarked-math。詳細 = conventions/latex.md#latexdiff-review-snapshot"
        echo "WARN: 無印の数式変更 ${UNMARKED} 件 — --allow-unmarked-math 指定のため続行"
    else
        echo "math guard: 無印の数式変更 0 件"
    fi
fi

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
