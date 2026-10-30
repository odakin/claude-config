#!/usr/bin/env bash
# latexdiff-review-snapshot.sh — 共著レビュー用「変更点カラー版 PDF」を 1 コマンドで生成・配備（baseline を git rev から取り出し → \input の多 file は両版を平らに → レビュー markup unwrap --strip-cmd/--strip-color → latexdiff → compile → snapshot 命名〔#snapshot-artifact-naming 準拠、head = main tex と sub-file の最終 commit に pin〕→ 同 baseline 旧版 supersede → commit+push+open。behind/dirty guard + --selftest 内蔵、conventions/latex.md#latexdiff-review-snapshot）
# latexdiff-review-snapshot.sh — 共著レビュー用「変更点カラー版 PDF」を 1 コマンドで生成・配備する engine
#
# = このスクリプトが手順の SoT (code-as-SoT)。手法の背景・落とし穴表・「既定」の使い分けは
#   conventions/latex.md#latexdiff-review-snapshot、
#   snapshot の命名規則は conventions/expensive-intermediate-artifacts.md#snapshot-artifact-naming が正本。
#   検証状況: macOS + TeX Live (lualatex) で e2e 済。Windows (git-bash) は未検証
#   (open は command -v guard 済、bash 3.2+ 想定)。
#
# やること (= 共著レビュー中に「相手の push を取り込んだ最新の diff PDF」を回す loop の機械化):
#   1. baseline 版 tex を git revision から取り出す (作業 tree を汚さない、mktemp workdir + aux symlink)。
#      main tex が \input / \include で sub-file を読むなら、 両版を同じ手順で平らにする (latexdiff-flatten.py)
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
#   - 多 file の原稿は、 旧版の sub-file を git show で、 新版を作業 tree から取り、 両版とも comment を
#     剥がして \input / \include を中身で置き換えてから比べる (conventions/latex.md#latexdiff-multi-file)。
#     \subfile・\import は平らにできないので止まる。 --no-flatten はこの段を飛ばす
#     = sub-file が両版とも作業 tree の版になり、 sub-file の差分に色が付かない
#   - repo が upstream より behind なら abort (= 「相手の push が diff に入っていない」事故の防止。
#     pull してから再実行)
#   - main tex か sub-file が HEAD と異なる working tree 状態なら abort (= snapshot 名の <head7> が嘘になる。
#     commit するか --allow-dirty で "<head7>-dirty" 名を許可)。 <head7> は main tex と sub-file の最後の commit
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
#   --diff-only           latexdiff と検査までで止める (組版しない、 --no-deploy を含む、 結果 = workdir の diff.tex)
#   --new-file PATH       新版を作業 tree の main tex でなく PATH から読む (--no-deploy を含む、 main tex の dirty は見ない)。
#                         原稿に当てる前の提案の版や、 差分のために加工した写し (新版だけに入れた体裁の macro を旧版の形に
#                         戻したもの) と比べるとき。 比べるための一時 repo も commit も要らない
#                         (conventions/latex.md#latexdiff-new-file)。 sub-file は PATH の隣を先に見る
#   --no-flatten          多 file の原稿を平らにしない (上の「前提と guard」)
#   --keep-superseded     同 baseline の旧 snapshot を git rm しない
#   --no-push / --no-open
#   --allow-dirty / --allow-behind
#   --no-math-guard       wrapper 展開 + safecmd + 無印検査を行わない (= 2026-09-12 以前の挙動)
#   --allow-unmarked-math 無印の数式変更を検出しても停止しない (警告のみ)
#   --selftest            review-markup-clean.py の selftest と引数の対応 + 命名 format + 同梱 script の selftest
#                         + sub-file だけを変えた 2 版の case (latexdiff が要る、 TeX は要らない)

set -uo pipefail

BASE="" REPO="$PWD" TEX="" ENGINE="lualatex" BIB="bibtex" MATHMARKUP="1"
EXTRA_ARGS="" PREFIX="latexdiff" DEPLOY=1 SUPERSEDE=1 PUSH=1 OPEN=1
ALLOW_DIRTY=0 ALLOW_BEHIND=0 MATH_GUARD=1 ALLOW_UNMARKED=0 NEWFILE="" FLATTEN_ON=1 DIFF_ONLY=0
STRIP_CMDS=() STRIP_COLORS=()
SCRIPTDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXPANDER="$SCRIPTDIR/expand-display-math.py"
SAFECMD_GEN="$SCRIPTDIR/latexdiff-safecmd.py"
MARKUP_CHECK="$SCRIPTDIR/check-latexdiff-math-markup.py"
DUP_LABELS="$SCRIPTDIR/latexdiff-strip-dup-labels.py"   # deleted copy keeps no \label (whole markup / MOVE), 2026-09-13
FINE_FIX="$SCRIPTDIR/latexdiff-fine-fixups.py"   # repairs of --math-markup=fine output (accent / \frac / deleted-side commands)
INLINE_FINE="$SCRIPTDIR/latexdiff-inline-math.py"   # fine: in-line $..$ and \frac diffed token by token (wrap -> latexdiff -> unwrap)
FLATTEN="$SCRIPTDIR/latexdiff-flatten.py"   # \input / \include replaced by the text on both sides, old side via git show

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

# sub-file だけを変えた 2 版: 平らにすると印が付き、 平らにしないと付かない (= 直す前の engine の形)。
# snapshot 名の head が sub-file の commit に動くことと、 sub-file の未 commit で止まることも見る
selftest_multifile() {
    command -v latexdiff >/dev/null || { echo "WARN: latexdiff が無い — 多 file の case は未検査"; return 0; }
    local r out tex head7
    r=$(mktemp -d)
    local g=(git -C "$r" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@example.invalid)
    git init -q "$r"
    printf '%s\n' '\documentclass{article}' '\begin{document}' 'Opening.' '' '\input{sub}' '\end{document}' > "$r/main.tex"
    echo 'The original sentence.' > "$r/sub.tex"
    "${g[@]}" add -A && "${g[@]}" commit -qm base
    echo 'The revised sentence.' > "$r/sub.tex"
    "${g[@]}" add -A && "${g[@]}" commit -qm sub
    head7=$(git -C "$r" rev-parse --short=7 HEAD)
    out=$(bash "${BASH_SOURCE[0]}" --repo "$r" --tex main.tex --base HEAD~1 --diff-only 2>&1) || die "多 file の case が止まった: $out"
    tex=$(sed -n 's/^diff-only: //p' <<< "$out")
    sed -n '/begin{document}/,$p' "$tex" | grep -q '\\DIFadd{' || die "sub-file の変更に印が付かない: $tex"
    [[ "$out" == *"-to-$head7"* ]] || die "snapshot 名の head が sub-file の commit に動かない: $out"
    out=$(bash "${BASH_SOURCE[0]}" --repo "$r" --tex main.tex --base HEAD~1 --diff-only --no-flatten 2>&1) || die "--no-flatten の case が止まった: $out"
    tex=$(sed -n 's/^diff-only: //p' <<< "$out")
    sed -n '/begin{document}/,$p' "$tex" | grep -q '\\DIFadd{' && die "--no-flatten でも印が付いた = この case は赤を作れていない"
    echo 'A later edit.' >> "$r/sub.tex"
    out=$(bash "${BASH_SOURCE[0]}" --repo "$r" --tex main.tex --base HEAD~1 --diff-only 2>&1) && die "sub-file の未 commit で止まらない"
    [[ "$out" == *"差分あり"* ]] || die "sub-file の未 commit の message が違う: $out"
    rm -rf "$r"
    echo "multi-file case OK (marked when flattened, unmarked with --no-flatten, head and dirty follow the sub-file)"
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
    local msg; msg=$(bash "${BASH_SOURCE[0]}" --base HEAD --new-file "$d/none.tex" 2>&1)   # TeX も git も要らない段で止まる
    [[ "$msg" == *"--new-file"*"が無い"* ]] || die "--new-file の引数の扱いが壊れた: $msg"
    echo "--new-file option OK"
    rm -rf "$d"
    local s
    for s in "$EXPANDER" "$SAFECMD_GEN" "$MARKUP_CHECK" "$DUP_LABELS" "$FINE_FIX" "$INLINE_FINE" "$FLATTEN"; do
        if [[ -f "$s" ]]; then
            python3 "$s" --selftest >/dev/null || die "$(basename "$s") selftest failed"
            echo "$(basename "$s") selftest OK"
        else
            echo "WARN: $s 不在 — 数式 guard は未検査"
        fi
    done
    selftest_multifile
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
        --diff-only) DIFF_ONLY=1; DEPLOY=0; shift;;
        --new-file) NEWFILE="$2"; shift 2;;
        --no-flatten) FLATTEN_ON=0; shift;;
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
if [[ -n "$NEWFILE" ]]; then
    [[ -f "$NEWFILE" ]] || die "--new-file $NEWFILE が無い"
    NEWFILE=$(cd "$(dirname "$NEWFILE")" && pwd)/$(basename "$NEWFILE")   # --repo の dir から読んでも同じ file
    DEPLOY=0   # 写しは commit でない = snapshot の名前の head が決まらない
fi
command -v latexdiff >/dev/null || die "latexdiff が見つからない"
[[ "$DIFF_ONLY" -eq 1 ]] || command -v "$ENGINE" >/dev/null || die "engine '$ENGINE' が見つからない"
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

BASE7=$(git -C "$REPO" rev-parse --short=7 "$BASE") || die "baseline '$BASE' を解決できない"

# ---- workdir 構築 (作業 tree 不変) ----
D=$(mktemp -d) || die "mktemp 失敗"
echo "workdir: $D"
git -C "$REPO" show "$BASE:$TEX" > "$D/base.tex" || die "git show $BASE:$TEX 失敗"
cp "${NEWFILE:-$REPO/$TEX}" "$D/new.tex"
[[ -n "$NEWFILE" ]] && echo "new: $NEWFILE (--new-file、 配備しない)"

# ---- 多 file: 両版を同じ手順で平らにする (conventions/latex.md#latexdiff-multi-file) ----
GUARD_FILES=("$TEX")   # snapshot 名の head と dirty の検出が見る file = 差分の実 input
if [[ "$FLATTEN_ON" -eq 1 && ! -f "$FLATTEN" ]]; then
    echo "WARN: $FLATTEN が無い — sub-file の差分に色が付かない"
elif [[ "$FLATTEN_ON" -eq 1 ]] && { python3 "$FLATTEN" --has-inputs "$D/base.tex" || python3 "$FLATTEN" --has-inputs "$D/new.tex"; }; then
    SEARCH_ARG=()
    [[ -n "$NEWFILE" ]] && SEARCH_ARG=(--search "$(dirname "$NEWFILE")")
    python3 "$FLATTEN" "$D/new.tex" "$D/new.tex" --main "$TEX" --repo "$REPO" --list "$D/new.files" ${SEARCH_ARG[@]+"${SEARCH_ARG[@]}"} \
        || die "新版を平らにできない — 上の message (--no-flatten は sub-file の差分に色が付かない)"
    python3 "$FLATTEN" "$D/base.tex" "$D/base.tex" --main "$TEX" --repo "$REPO" --rev "$BASE" --list "$D/base.files" \
        || die "基準版を平らにできない — 上の message (--no-flatten は sub-file の差分に色が付かない)"
    while IFS= read -r f; do GUARD_FILES+=("$f"); done < "$D/new.files"
    echo "flatten: sub-file 基準版 $(wc -l < "$D/base.files" | tr -d ' ') 本 / 新版 $(wc -l < "$D/new.files" | tr -d ' ') 本"
fi

# ---- guard: main tex と sub-file の dirty 検出 (= snapshot 名の head hash が嘘にならないように) ----
DIRTY_SUFFIX=""
if [[ -z "$NEWFILE" && -n "$(git -C "$REPO" status --porcelain -- "${GUARD_FILES[@]}")" ]]; then
    if [[ "$ALLOW_DIRTY" -eq 1 ]]; then DIRTY_SUFFIX="-dirty";
    else die "${GUARD_FILES[*]} のどれかが HEAD と差分あり — commit するか --allow-dirty (名前に -dirty が付く)"; fi
fi

# head 側は「main tex と sub-file を最後に触った commit」に pin する (= diff の実 input。
# snapshot 配備 commit 等の無関係 commit で名前が変わらない)
HEAD7=$(git -C "$REPO" log -1 --format=%h --abbrev=7 HEAD -- "${GUARD_FILES[@]}")
[[ -n "$HEAD7" ]] || die "$TEX の履歴を解決できない"

for entry in "$REPO"/* "$REPO"/.[!.]*; do
    b=$(basename "$entry")
    [[ "$b" == ".git" || "$b" == "$TEX" || "$b" == ${PREFIX}-*.pdf ]] && continue
    [[ -e "$entry" ]] && ln -s "$entry" "$D/$b" 2>/dev/null
done
# main tex が repo の下の dir にあるときは、 その dir の file も隣に置く
# (図・bib・bst は tex の隣にあり、 root だけを link すると compile が読めない = 実測)
TEX_DIR=$(dirname "$TEX")
if [[ "$TEX_DIR" != "." ]]; then
    for entry in "$REPO/$TEX_DIR"/* "$REPO/$TEX_DIR"/.[!.]*; do
        b=$(basename "$entry")
        [[ "$b" == "$(basename "$TEX")" || "$b" == ${PREFIX}-*.pdf ]] && continue
        [[ -e "$entry" && ! -e "$D/$b" ]] && ln -s "$entry" "$D/$b" 2>/dev/null
    done
fi

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
# fine: latexdiff takes in-line $..$ (and \frac{..}{..}) as one token -> wrap them so only the changed symbols
# are marked, as in displays; unwrapped after the guard (conventions/latex.md#latexdiff-fine-markup)
INLINE_ARG=""
if [[ ( "$MATHMARKUP" == "3" || "$MATHMARKUP" == "fine" ) && -f "$INLINE_FINE" ]]; then
    python3 "$INLINE_FINE" wrap "$D/base.tex" "$D/base.tex" >/dev/null || die "latexdiff-inline-math.py wrap 失敗 (base)"
    python3 "$INLINE_FINE" wrap "$D/new.tex" "$D/new.tex" >/dev/null || die "latexdiff-inline-math.py wrap 失敗 (new)"
    INLINE_ARG="--add-to-config=MATHENV=difinlinemath"
fi
# shellcheck disable=SC2086
latexdiff --math-markup="$MATHMARKUP" --config VERBATIMENV=comment $INLINE_ARG $SAFE_ARG $EXTRA_ARGS \
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
if [[ -n "$INLINE_ARG" ]]; then
    python3 "$INLINE_FINE" unwrap "$D/diff.tex" >/dev/null || die "latexdiff-inline-math.py unwrap 失敗 (上の形)"
fi
if [[ "$DIFF_ONLY" -eq 1 ]]; then
    echo "diff-only: $D/diff.tex"
    echo "snapshot の名前の末尾: ${BASE7}-to-${HEAD7}${DIRTY_SUFFIX}"
    exit 0
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
    if [[ -n "$NEWFILE" ]]; then echo "no-deploy: 結果 = $D/diff.pdf (--new-file の写しとの差分 = 配備しない)"
    else echo "no-deploy: 結果 = $D/diff.pdf (配備時の名前: $NAME)"; fi
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
