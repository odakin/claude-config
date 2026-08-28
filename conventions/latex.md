<!-- doc-meta
when: LaTeX を含むリポで作業するとき
category: paper
summary: LaTeX 固有規約（物理リポで参照）
-->
# LaTeX 規約

LaTeX を含むリポで適用。CLAUDE.md から参照: `~/Claude/claude-config/conventions/latex.md`

## <a id="equation-safety"></a>式の安全規則
- **equation/align 環境内は原則変更しない。** 変更は事前にユーザー確認。物理的内容の追加はコメントとして提案（ハルシネーション混入防止）
- 英語校正・文法修正など確実に正しい本文修正は可

## <a id="mathbb-digits"></a>`\mathbb{数字}` は黙って化ける — 単位行列は `\mathbbm{1}` (bbm)

- **`\mathbb{数字}`(例 `\mathbb 1`, `\mathbb 0`)を使わない。** `amssymb` の `\mathbb` は**大文字 A–Z しかグリフを持たない**ため、数字を渡すと **compile error を出さずに黙って化ける**(missing glyph / 別字へ fallback)。= **視覚 QA でしか気づかない**沈黙故障(コンパイル成功 = 正しい、ではない好例)。
- **単位行列・恒等作用素は `\usepackage{bbm}` + `\mathbbm{1}`**(真の黒板太字 1)。代替: `\mathds{1}`(dsfont)、最低限 `\mathbf{1}`。同様に黒板太字の数字が要る一般ケースも `\mathbb` でなく bbm/dsfont 系を使う。
- **発火**: PDF の**視覚 QA で実物確認**が第一(doc 記載だけでは発火しない)。より確実には pre-commit / build で `\mathbb\s*\{?\s*[0-9]` を grep する mechanical guard を足す(= doc rule より発火信頼度が高い)。
- 実例: ある物理ノートの式で $\gamma_5^2=\,$`\mathbb 1` が化けていた(`\mathbbm{1}` で修正)。`\mathbb` を識別子マクロのつもりで数字に当てると起きる。

## <a id="cite-set-after-commentout"></a>comment-out 流儀の編集後は live `\cite` 集合を照合する

旧文を `%...` で残して次行に新文を書く「comment-out keep」 流儀で編集すると、 行末まで `%` が
飲み込むため、 同じ行にあった `\cite{...}` を**意図せずコメントアウトして引用が落ちる**危険がある。
**comment-out edit のたびに、 各行の code 部 (= 最初の `%` より前) の live `\cite` key 集合を
baseline と照合**し不変を確認する (= `\bibcite` や aux 経由でなく source の `%` 前を見る)。 安価:

```bash
# 各行の最初の % より前に現れる \cite キーを抽出して sort -u で集合化、 baseline と diff
awk -F'%' '{print $1}' file.tex | grep -oE '\\cite[a-zA-Z]*\{[^}]*\}' | sort -u
```

## <a id="commented-out-not-present"></a>comment-out / `\begin{comment}` した構造的要素を「原稿にある」と主張しない

**ルール:** 式・節・定義・分解・関数といった**構造的要素が「原稿 (= rendered PDF) に存在する」と主張する前に、その要素が active state に在るかを source で 1 query verify する**。`%` 行・`\begin{comment}...\end{comment}` ブロック内の要素は **source には文字列として在るが output には出ない (= silent non-existence)**。prose 上の summary (= `SESSION.md` / `DESIGN.md` / handoff / メール下書き) に「ある / 移行済み」と書いてあっても、それは authoritative ではない。**authoritative なのは active source だけ**。

**Why:** comment-out-keep 流儀 (= 旧 draft を `%` で寝かせる) や「Obsolete 節へ隔離」運用では、ある要素が *かつて active だった* 時点の prose summary が残り、後で `%` 化されても summary は追従しない (= summary は active state の **mirror** で、change 時に更新が 1 つ脱落する)。この stale summary を SoT として読むと、**存在しない対象に対する解決策**を考え・共著者に相談し・外部発信してしまう (= phantom problem への labor 浪費)。さらに `grep` で要素名を引くと `%` 行も hit するため、**素朴な「grep したら在った」では verify にならない** — hit 行の先頭が `%` か、`\begin{comment}` 内かまで見て初めて active 判定になる (= `%` が素朴 grep を無効化する)。

**How to apply:**

1. 構造的要素を chat / メール / 規約 / handoff で「原稿にある」と参照する前に、active 本文だけを見る:

```bash
# コメント行を落として live 本文だけ grep (= 先頭 % 行を除外)
grep -vE '^\s*%' file.tex | grep -nE '<element>'
# または各 hit 行の先頭が % / \begin{comment} 内でないかを必ず確認
grep -nE '<element>' file.tex
```

2. prose summary (`SESSION.md`「migration 完了」等) と active source が食い違ったら **active source が勝つ**。summary 側を errata / 更新する。
3. 第三者 (共著者・レビュアー) が「その要素が原稿のどこにあるか分からない」と言ったら、それは **記憶の曖昧さでなく grep 等価の signal** — 推測で解決策を返す前に自分で active grep を回す。

これは上の「comment-out 流儀の編集後は live `\cite` 集合を照合する」「長さ・段落構造の判断にコメントアウト行を数えない」と同じ **`%` は output から silent** という kernel の、*存在主張* 版 (前者 = 引用落ち / 中者 = 長さ誤算 / 本節 = 存在誤主張、3 つの consequence)。一般則 — 単一情報源の positive 主張の前に安価な検証を回す / prose summary を SoT と読み違えない — の正本は `CLAUDE.md` inline §3 (positive-claim branch) + [`docs/convention-design-principles.md` §2.3](../docs/convention-design-principles.md#sot-read-side) (read 側 SoT)・[§2.5](../docs/convention-design-principles.md#sot-duplication-trichotomy) (prose-mirror は別所 state の mirror で change 時に drift) で、本節はその LaTeX source への HOW 適用。

**事例 (2026-06、物理 LaTeX 原稿):** ある直和分解 (`H = A ⊕ B` 型) が運用台帳の prose で「migration 完了」と記録されたまま、4 日後に `%` + `\begin{comment}` で寝かされた。prose summary はその stale を ~7 週間保持し、その間に派生ノート PDF・`DESIGN.md` entry・共著者宛メール 3 通が**この分解を active 前提で**論じた (左辺の macro 名すら prose 側と source 側で食い違っていた = source 未参照の tell)。共著者が「その分解が原稿のどこにあるか把握できない」と明示 signal を出していたが、当時は記憶の問題と読み流し active grep を回さなかった。最終的に「まだ原稿にあるんだっけ?」の直接質問で初めて comment-out 状態が発覚した。

## <a id="latexdiff-review-snapshot"></a>latexdiff で差分レビュー PDF を作る

共著者に「どこを変えたか」を渡すとき、`latexdiff old.tex new.tex > diff.tex` で **追加=下線 / 削除=取り消し線** のレンダリング済み PDF を作れる。comment-out-keep 流儀（旧文を `%` 化）の編集は raw の git diff では読みにくいので、latexdiff の方が共著者に優しい。

**baseline は git revision から都度取り出す**（aux file は symlink で借り、作業 tree を汚さない）:

```bash
D=$(mktemp -d)
git show <BASELINE>:paper.tex > "$D/old.tex"            # 過去版
cp paper.tex "$D/new.tex"                                # 現在版
ln -s "$PWD/Figures" "$PWD/ref.bib" "$PWD"/*.bst "$D"/   # 図・bib・bst を借りる
```

⚠️ byte-pristine な baseline を**作業 tree に tracked file として置かない**: char-normalizer pre-commit hook が commit 時に dash/accent/quote を書き換えて baseline byte が崩れ、spurious 差分になる。byte 一致が要る baseline は **untracked + gitignore** にするか、上のように git revision から都度取り出す（下記 §pre-commit hook「byte-pristine な baseline は tracked にしない」と同根）。

**plain `latexdiff` がそのままコンパイルできない時の定石**（複雑な原稿で頻発。diff の前処理・後処理で回避する）:

| 症状 | 原因 | 対処 |
|---|---|---|
| diff のノイズが多すぎる | レビュー markup（色付き注釈コマンド等）まで差分対象になる | diff 前に markup を strip（中身は残し注釈コマンドだけ除去） |
| `Missing \cr` / `\endgroup` / display math 破壊 | 環境を隠した自作マクロ（例: align を包む `\al{}`）が `\DIFadd` に巻かれる | diff 前に当該マクロを本物の `\begin{align}…\end{align}` へ展開 |
| tikz error の連鎖 | ネストした tikzpicture/feynman 図が壊れる | 図を placeholder 文字列へ置換 +（下の）`--config PICTUREENV=…` |
| 3 分かかる / output が無限ループ | CFONT の color markup が page builder と干渉 | `--type=UNDERLINE`（色でなく下線/取消線）。**hang の真因は CFONT 単独**で、UNDERLINE なら `twocolumn` のままコンパイルできる（2026-08 実証。旧対処の `onecolumn` 化は不要 = 実紙面レイアウトの diff の方が共著者に優しい） |
| `Paragraph ended before \align` | latexdiff が変更 align 内に空行（`\par`）を挿入 | 後処理で数式環境内の空行を除去 |
| natbib citation でハング | citation markup × natbib | `--disable-citation-markup` |

**推奨 flag の既定**（複雑な物理原稿で安定する組合せ）:

```bash
latexdiff --type=UNDERLINE --math-markup=off --disable-citation-markup \
  --config "PICTUREENV=(?:picture|tikzpicture|feynman|DIFnomarkup)[\w\d*@]*" \
  "$D/old.tex" "$D/new.tex" > "$D/diff.tex"
# 後処理（数式環境内の \par 除去）後に pdflatex を 2 回（+ bibtex を挟むと citation が [?] でなく実番号になる）
```

- `--math-markup=off`: 式中の add/del は色付けしない（式の変更は新版として出るが色は付かない）。数式の add/del markup はコンパイルを壊しやすいので既定 off にし、文章・構造・コメント削除の差分を確実に出す方を取る。
- **「投稿用でなく差分レビュー用」と割り切る**: markup 除去・図 placeholder・数式色なしは*意図的な簡略化*。

**別解（latexdiff のコンパイル問題を完全回避）**: Overleaf 連携の原稿なら **Overleaf の History 比較**（baseline 版 ↔ 現在）が確実で、pre/post 処理が要らず数式まで色分けされる。

> **標準ケースは engine script で機械化済**: [`scripts/latexdiff-review-snapshot.sh`](../scripts/latexdiff-review-snapshot.sh) が「baseline 取り出し → markup unwrap (`--strip-cmd`/`--strip-color`) → latexdiff → compile cycle → snapshot 命名 ([`expensive-intermediate-artifacts.md#snapshot-artifact-naming`](expensive-intermediate-artifacts.md#snapshot-artifact-naming) 準拠、 head 側は main tex を最後に触った commit に pin) → 同 baseline 旧版の supersede 削除 → commit+push+open」 を 1 コマンドで回す (= 共著レビュー中に相手の push を取り込んで diff を更新する loop 用。 behind / dirty guard 内蔵、 手順詳細 = script docstring が SoT)。 ⚠️ **「既定」の使い分け**: engine の既定 (`--math-markup=1` + `VERBATIMENV=comment` + lualatex) は**単一 main file・comment 環境・tikz 図なしの素直な原稿**で実証した組合せ。 上の症状表に当たる複雑原稿 (tikz / natbib / 自作数式環境マクロ) では**本節の保守的既定** (`--math-markup=off` / `--disable-citation-markup` / `PICTUREENV` 等) を `--latexdiff-args` で注入する — 2 つの既定は矛盾でなく原稿クラス別。 **原稿固有値 (= baseline commit・strip 対象 markup・engine) は各 repo の CLAUDE.md に呼び出し 1 行として置き、 手法の正本 (本節 + engine) を参照する** (= SoT は上層 1 つ、下層から参照)。 engine で吸収できない exotic な pre/post 処理 (マクロ展開・図 placeholder 等) が要る原稿のみ、 従来通り repo の `latexdiff/` 配下に固有スクリプトを置く。
>
> ⚠️ markup unwrap が必要な理由: `\DIFadd{\cl{長文}}` のように **group を丸ごと下線 markup に包むと ulem が改行不能 box 化してページ外に溢れる** (= 描画はされるが 1 行で切れる)。 review 注釈系コマンドは diff 前に unwrap するのが根治 (= diff 内で draft 色は冗長でもある)。 両版に同一適用すれば未変更 markup が spurious diff にならない。

## <a id="stash-roundtrip-build-artifacts"></a>baseline 比較に git stash round-trip を使わない (tracked 生成物と衝突する)

**ルール:** 「この overfull / warning / 挙動は自分の編集**前**からあったか?」 という baseline 比較のために、 compile が上書きする tracked 生成物 (committed PDF 等) を持つ tree で `git stash` → 再 build → `git stash pop` の round-trip をしない。 baseline は tree を動かさない read-only 経路で取る:

```bash
# 単一 file の baseline を取り出して比較 (working tree 不動)
git show HEAD:notes/foo.tex > /tmp/foo-baseline.tex
# tree 全体の baseline build が要るなら worktree (元 tree は不動)
git worktree add /tmp/baseline-wt HEAD && (cd /tmp/baseline-wt && <build>)
```

**Why:** stash してから build を走らせると、 tracked 生成物が working tree で再生成され**新しい local change になる** → `git stash pop` が「Your local changes ... would be overwritten by merge」 で **abort する**。 このとき編集一式は stash に閉じ込められ、 tree は baseline 状態のまま — 気付かず作業を続けると、 disk 上の file が全部「編集前」 を見せる (実 incident 2026-07-10: rename 編集一式が pop fail で stash に残留し、 直後の参照がすべて pre-rename 状態を読んだ)。 PDF に限らず、 build が上書きする tracked 生成物 (図・生成 tex・data file) すべてで同型。

**復旧 (pop が abort した場合):** 作業は失われていない (abort 時 stash entry は保持される、 `git stash list` で確認)。 衝突している生成物 (= baseline build が作った側、 どうせ再生成できる) を `git checkout -- <生成物>` で捨ててから `git stash pop` すれば全編集が戻る。 pop 成功後、 生成物は編集後 source から再 build すれば一致する。

## <a id="out-of-tree-build-input-shadowing"></a>tree 外 build で source dir を入力 path の先頭に置かない (古い生成物が新しい生成物を隠す)

**ルール:** baseline 比較や scratch build のために source tree の外で compile するとき、 `TEXINPUTS` / `BIBINPUTS` / `BSTINPUTS` に source dir を **cwd より先**に置かない。 cwd を先頭にする:

```bash
# 正: cwd (= scratch dir、 今の run が生成した .bbl/.aux がある) を先に見る
export TEXINPUTS=".:$SRC:" BIBINPUTS=".:$SRC:" BSTINPUTS=".:$SRC:"
# 誤: source dir が先。 $SRC に残る古い paper.bbl 等を掴む
export TEXINPUTS="$SRC:"
```

**Why:** source dir には過去の in-place compile が残した生成物 (`.bbl` / `.aux` / `.toc` / `.ind`) が untracked で残っていることがある。 `$SRC` が先だと、 scratch dir で bibtex が**今まさに書いた** `.bbl` を LaTeX が読まず、 source dir 側の**古い** `.bbl` を読む。 症状は「新しく追加した `\cite` だけが undefined」「TOC の項目が古い」 等、 **自分の編集と無関係に見える偽陽性**で、 しかも bib entry を grep すると存在するので原因に辿り着きにくい。

**診断:** 生成物側と aux 側の key 集合を突き合わせる。 数が 1 つ違い、 欠けている key が「最近追加されたもの」 なら入力 path の shadowing を疑う:

```bash
comm -23 <(grep -o '^\\bibitem{[^}]*}' paper.bbl | sed 's/.*{\(.*\)}/\1/' | sort) \
         <(grep -o 'bibcite{[^}]*}'    paper.aux | sed 's/.*{\(.*\)}/\1/' | sort)
```

実 incident (2026-08-04): 共著論文の baseline 比較で `TEXINPUTS="$SRC:"` を使い、 共著者が当日追加した cite 1 件を「未解決」 と誤報告しかけた。 `.bbl` には `\bibitem` があるのに `.aux` の `\bibcite` が 1 件だけ足りない、 が決め手だった。 **根治は scratch dir を汚さないことでなく、 source dir 側の古い生成物を掴ませないこと** — source tree で一度でも in-place compile したことがあるなら常に該当する。

⚠️ 同じ shadowing は `\input` / `\includegraphics` の解決先でも起きる (= source dir 側の古い生成 tex / 古い図を掴む)。 cwd 優先は path 変数 3 つ全部に効かせる。

## <a id="text-structure-hierarchy"></a>文章の構造化と見出し階層 (`\paragraph` は `\subsubsection` より下)

**ルール (3 段):**

1. **文章はなるべく構造化する** — 論文・研究ノート・technical doc の本文を長い prose ブロックで流さず、意味のまとまりごとに見出し (`\section` / `\subsection` / `\subsubsection`) で区切る。読者 (共著者・レビュアー・後の自分) が目次と body の対応で navigate できることを既定にする。
2. **意味のまとまりで段落を分ける** — 1 段落 = 1 主張 (topic sentence 1 本を発展させる本文数文)。話題転換・新しい観点への移行では段落を切る。1 節を単一の巨大段落で書かない。
3. **`\paragraph` は `\subsubsection` より下の階層** — LaTeX 見出し階層は `\section` > `\subsection` > `\subsubsection` > `\paragraph` > `\subparagraph`。`\paragraph` は **run-in inline header** (見出し行が本文冒頭と同一行に流れる形式) なので、番号付き block heading の代替として top-level に並べない。`\subsubsection` を先に使い、その下で更に細分化が要る箇所でのみ `\paragraph` を置く。

**Why:**

- `\paragraph` は本来 4 段目 (`\section`/`\subsection`/`\subsubsection` の下) の inline header。トップに並べると (a) 目次に出ない (デフォルト `tocdepth`)、(b) 番号が振られない、(c) 直後に `\colorbox`/`\begin{itemize}` 等の block 要素を置くと **paragraph の continuation** として解釈され layout が壊れる (右にはみ出す・page break が変になる、 [PDF 視覚検証 typical trap](#pdf-visual-verification) の 1 行目参照)。読者にも「これは節見出しなのか単なる段落強調なのか」判別が付かない。
- run-on paragraph (段落が延々と続く) は topic sentence が拾えず読解負荷が上がる。共著レビュー・rebuttal でも「どこを直せば直るか」の議論単位が失われる。

**How to apply:**

- 新規 note・論文の draft を書く段階で「この節は subsection で切るか / subsubsection で切るか / paragraph で inline header にするか」を hierarchy を意識して決める。「とりあえず `\paragraph{...}` で見出しっぽく書く」を default にしない。
- 既存 note で run-in `\paragraph` を top-level 見出しとして使ってしまっている場合の移行 heuristic (= 既存 §番号を動かさないための現場判断):
  - **既に `\subsection` を持つ note** → `\paragraph` を `\subsubsection` に昇格 (既存 §N.M 番号不変)
  - **`\subsection` を持たない小物 note (section 直下に paragraph)** → `\paragraph` を `\subsection` に昇格 (subsubsection にすると `X.0.N` 型に壊れるため)
  - 大物 note (≥15pp) には TOC (`\tableofcontents` + 適宜 `tocdepth=2`) を付け、目次から navigate できるようにする
- 意味段落の切り方: (a) topic sentence が変わる、(b) 主語 / 論点が移る、(c) 例示 → 一般化 の遷移、(d) 逆接 (「しかし」「一方」) の直前 — いずれかで段落を切る候補。1 段落が 15 行を超えたら 2 段落以上に割れないかを疑う。
- edit 判断のとき **段落の重さは source 行数でなく rendered 分量で見る** (= 下の「§長さ・段落構造の判断にコメントアウト行を数えない」の kernel を継承)。

**事例 (2026-07-04 einstein-cartan LIVE note family 統一)**: `induced-action` / `induced-action-per-term` / `verified-results` / `docs/ec_one_loop_notes` / `convention-conversion` / `handcheck-final` + 小物 8 note で run-in `\paragraph` を top-level heading として使っていた計 ~150 本を、既存 §番号を保ったまま `\subsubsection` (subsection ありの大物) または `\subsection` (subsection なしの小物) に一斉昇格 (Chip H/I/J/K/L)。詳細 = `einstein-cartan/CLAUDE.md §「見出しの論文型規律 (2026-07-04 確立)」`。

## <a id="exclude-comments-from-length"></a>長さ・段落構造の判断にコメントアウト行を数えない

**ルール:** 段落の切れ目・節の分割・restructure 等、 「文書の長さ / 段落の重さ」 を根拠にした編集判断は **rendered 出力 (= PDF に出る内容) だけで見積もる**。 `%` でコメントアウトされた行・ブロック (= 旧 draft・代替表現・comment-out keep で残した旧文) は source 行数を膨らませるだけで読者には出ないので、 長さの勘定に入れない。

**Why:** comment-out keep 流儀 (= 旧文を `%` で残し直下に新文を書く) や、 複数の代替表現を `%` で寝かせる運用では、 source 行数と rendered 分量が大きく乖離する。 source を上から眺めて「この段落は長い / 詰め込みすぎ」 と判断すると、 実際には普通サイズの段落を不要に分割する誤りに陥る (= 行番号レンジ L_a–L_b を分量の代理指標にすると、 間に寝た `%` ブロックを数えてしまう)。

**How to apply:** 「長い / 分割すべき」 と言う前に、 対象範囲の `%` 行を除いた live 本文だけを読む。 安価:

```bash
# コメント行・空行を落として live 本文の分量だけ見る
grep -vE '^\s*%' file.tex
```

display math・図は行数でなく rendered での専有量で別途見積もる。

## <a id="math-mode-protection"></a>地の文に math 文字を裸で書かない (math mode 保護)

**ルール:** 地の文 (= `$...$` `\(...\)` `equation` 環境の外) では、 `^` `_` `\dagger` `\hat` 等の **math mode 専用記号を含む式片**を裸で書かない。 全部 `$...$` で囲うか、 日本語に置き換える。

**Why:** TeX は地の文で `^` `_` を見ると math mode 解釈を試み、 `Missing $ inserted` エラーで build が止まる (= 「Emergency stop」 まで行く)。 地の文に「a^†」 「α_n」 「c_{n+1}」 等を裸で書くのは典型的 bug 源。 章 draft 編集時に頻発、 編集者は気付きにくい (= rendered PDF を見ないと build 失敗が visible にならない)。

**How to apply (= edit 時 self-check):**
- 地の文に演算子記号 / 添字 / Greek + subscript を書く前に、 数式環境内かを確認
- 安全な置き換え:
  - `a^†` (地の文) → `$\hat{a}^\dagger$` または「a に dagger」 等の言い換え
  - `α_n` (地の文) → `$\alpha_n$` または「規格化定数」 等の言い換え
  - `|n+1⟩` (地の文) → `$\ket{n+1}$` または「次の段」 等の言い換え
- **edit 後 must build**: tex 編集後は必ず `make` / `ptex2pdf` で build を確認、 「Missing $ inserted」 エラーが出たら該当行を grep で見つけて修正
- 検出 grep (大まかに): `grep -nE '[^\$\\\\\{]a\^|[^\$\\\\\{]α_|[^\$\\\\\{]c_n' file.tex` 等

**事例 (2026-05-10 quantum-mechanics-textbook 第 1 部最終章 draft restructure)**: 7 commit に渡る章書き直しの過程で、 Claude が地の文に「a^† と a の代数構造」 「α_n の積」 「a^†|n⟩ ∝ |n+1⟩」 等を裸で書いて 3 箇所で build を破壊。 1 commit 内で 3 回 build retry が必要だった。 edit 直後の build verify で発覚 → 該当箇所を `$\hat{a}^\dagger$` 等で囲って修正。

## <a id="preamble-macros-first"></a>プリアンブル定義のマクロを優先する (絶対則)

**リポのプリアンブルで定義されているマクロ (semantic / typing shortcut / 色付き / 数式 alias / その他、種類問わず) が対象概念に存在する場合、生の primitive 記法を使うことを禁止する。**

⚠️ **「`\op` だけの話」 ではない**。プリアンブルで定義されているありとあらゆるマクロが対象。色付き semantic macro (`\op` `\st` `\rf` `\pd` 等) だけでなく、typing shortcut (`\h` = `\hat`、`\wh` = `\widehat`、`\tx` = `\text`、`\md` = `\middle|`、`\sqbr{}` = `\left[...\right]` 等) や数学演算子 (`\Tr`、`\fnl`、`\commutator{}{}` 等) も同等に強制対象。

例外は以下 **2 つに限定** (狭く解釈する):
1. プリアンブル定義が**無い**概念 (= grep で見つからない)
2. author drafting marker (= `\cl{}` `\green{}` 等の一時的 highlight、後で消す前提のスクラッチ、semantic 意味なし)

これ以外、「raw でも動くから raw で書く」 「見た目同じだから raw で OK」 「タイプが少し短いから raw で済ます」 は全部 NG。

### <a id="preamble-macros-scope-examples"></a>対象範囲の例 (= 全部対象、これでも非網羅)

| カテゴリ | マクロ例 | 対応する生記法 (= 禁止) |
|---|---|---|
| 色付き semantic | `\op{T}` (operator + red) | `\red{T}`、`\hat{T}`、`\textcolor{red}{T}` |
| 色付き semantic | `\st\rho` (state + magenta + mathsfit) | `\magenta{\rho}`、`\hat\rho` 単体 |
| 色付き semantic | `\rf{f}` (real func + blue) | `\blue{f}` |
| 色付き semantic | `\pd{X}`、`\pdf{X}{x}` (prob dist + cyan) | `\cyan{X}`、`\cyan{X\fn{...}}` |
| 関数呼出 | `\fn{x}`、`\fnl{X}` (auto-spacing + paren/bracket) | `\paren{x}`、`(x)`、`\sqbr{X}` (function call 文脈で) |
| 数学演算子 | `\Tr`、`\Tr\fnl{X}` | `\tx{Tr}`、`\Tr\sqbr{X}`、`\Tr[X]` |
| 数学演算子 | `\commutator{A}{B}` | `[A,B]` (commutator 文脈で) |
| typing shortcut | `\h` (= `\hat`) / `\wh` (= `\widehat`) | `\hat{}` / `\widehat{}` |
| typing shortcut | `\tx` (= `\text`) / `\mc` (= `\mathcal`) / `\ms` (= `\mathscr`) | `\text{}` / `\mathcal{}` / `\mathscr{}` |
| typing shortcut | `\md` (= `\middle|`) | `\middle\|` |
| 物理 alias | `\rh` (= `\hat\rho`)、`\Ah` (= `\hat A`)、`\TD` (= `T_\tx{D}`) 等 | バラ書き (`\hat\rho`、`\hat A`、`T_\tx{D}`) |

### <a id="preamble-macros-check-grep"></a>確認用 grep (= 「定義がある macro 名なのか?」 をチェック)

```bash
# ある token (e.g. \red, \op, \fn, \Tr) の定義をプリアンブルで探す
grep -nE '\\(newcommand|renewcommand|providecommand|nc|def|NewDocumentCommand|DeclareDocumentCommand|DeclareMathOperator)\*?\{?\\<token>' main.tex
```

`\NewDocumentCommand` / `\nc` (= `\newcommand` の独自 shortcut) / `\providecommand` 形式は `\newcommand` 1 種類だけ grep してると見落とすので、上の widening grep を必ず使う。

### <a id="preamble-macros-rationale"></a>理由 (rule の hard 化を支える 4 条)

1. **一斉追従**: macro 定義を refine (e.g. journal 投稿時に色除去 + ハットスタイル変更、フォント差し替え) すると全箇所が一斉追従、生記法は drift する。プリアンブルがあるのに使わないと「定義したが効かない」 dead 領域になる
2. **Greppability**: `\op{T}` は概念として grep 可能 (= 全 operator 占用箇所が `grep '\\op{'` で引ける)、生 `\hat{T}` は raw notation で grep しても operator かどうか判別不能
3. **意図の明示**: `\op{T}` は読み手に「operator T」 を伝えるが、`\hat{T}` は単なる hat 記号で物理 / 数学的意味が伝わらない
4. **共著者・後継者の dx**: 1 人が手で raw を選ぶたびに、共著者の grep が外れる、後継者の refine が壊れる、レビュアーが「なぜここだけ違うの?」 と問う。**プリアンブル定義 = 既に「これを使え」 と全員に向けて宣言されている。raw 書きはその宣言を裏切る行為。**

### <a id="preamble-macros-repo-fallback"></a>リポ固有 fallback

リポ固有の active semantic macro 一覧と例外運用は各リポの `CLAUDE.md §LaTeX rules` 参照 (Layer 2)。Layer 1 の本則は「プリアンブルにあれば必ず使う」、Layer 2 は「このリポで何が active か」 のディレクトリ。

## <a id="macro-alias-forcing-function"></a>マクロ alias の forcing function

上の絶対則を「読めば守る」 discipline だけに頼ると、共著者の Claude や別 session で raw 記法が静かに再混入する。**典型的な抜け道**: atom（`\h`・`\bs`・各 subscript alias）が個別には正規 alias なのに、それらを束ねた **compound macro をバイパスして書き下した形**（`\h T_{...}` を専用マクロの代わりに longhand）は、atom-level の grep / linter をすり抜ける。違反は linter が見る一段上で起きる。さらに別 dialect（別の綴り・別 primitive）でまるごと書かれた領域は、denylist に列挙していない綴りなので 0 hit で素通りする。

→ 各 LaTeX repo に **3 段の機械 enforcement** を置く:

1. **repo-local の check script**（例: `scripts/check-preamble-aliases.py`）— body を走査し、プリアンブルに macro があるのに raw を使う箇所を HARD 違反として列挙、hard>0 で `exit 1`。macro vocabulary は repo ごとに違うので script は **Layer 2（各 repo の `scripts/`）に置く**（本 Layer 1 doc は pattern の SoT、実装は repo 側）。検出規則には atom だけでなく **その repo の compound macro をバイパスした形**（lookahead で対象を絞り、別概念の同形記号を誤検出しない）まで含めるのが肝。
2. **committed pre-commit hook**（`.githooks/pre-commit` + `core.hooksPath` を張る `scripts/install-hooks.{sh,ps1}`）— clone 初回に 1 度 install すれば、以後の commit で 1. を自動実行し raw を含む commit を block。hook は version 管理下に置き、各著者の環境（mac / Windows git-bash）で動くよう `sh` で書く。既存の char-fixer 等があれば conditional に chain（無い環境では no-op）。⚠️ **Windows gotcha**: `.gitattributes` で hook と `*.sh` を `eol=lf` 強制しないと、checkout 時に CRLF 化して shebang（`#!/bin/sh`）が壊れる（`* text=auto eol=lf` 1 行で足りる）。git-bash の挙動は version 差があるので、Windows 共著者が居るなら初回に実機 smoke-test（適当な違反を commit して block されるか）を 1 度回す。
3. **CI**（`.github/workflows/*.yml` で push/PR ごとに 1. を実行）— pre-commit hook を install していない clone（= 制御できない共著者）でも server 側で必ず検出する最終防衛線。pure-script なので LaTeX build 不要・高速。

⚠️ **mechanize の限界を明示する**: 微分の `d` のように「regex で raw と正用を判別できない」 category は lint 不能 → discipline に残す（noisy rule を足すと false positive で linter の信頼を失う）。mechanize できる subset とできない subset を分け、後者は doc に明記する。

各 repo の `CLAUDE.md §LaTeX rules` から本節を参照し、session 開始時に `git config core.hooksPath` が `.githooks` を指すか確認 → 空なら install を促す手順を repo 側に書く。

## <a id="fixed-framing-macro"></a>新規 macro に fixed framing text を含める前に source-render asymmetry の罠を抑える

`\newcommand{\foo}[N]{...prefix...#1...suffix...}` 形式で **argument の前後に hardcoded prose を持つ macro** を定義する場合、 source level (= `.tex` の grep / git diff / 自分の音読) では prefix/suffix と argument の grammatical 統合が **見えない**。 短 argument で正しく書けた fixed text が、 長 / 拡張 argument で render 後に文法的 broken する。 これは pdftotext / 視覚 PDF inspection でしか expose 不能な class の bug。

**典型失敗例 (= 2026-05-18、 物理 LaTeX project の retraction marker macro)**:

```latex
% 旧定義 (= bug あり)
\newcommand{\subretracted}[1]{%
  \par\noindent\textit{[Retracted. See #1 above for context.]}\par%
}
```

- 短 argument: `\subretracted{Movement 3 retraction box}` → "See Movement 3 retraction box above for context." ✓
- 拡張 argument: `\subretracted{Movement 3 retraction box --- the literature fact remains valid}` → "See Movement 3 retraction box --- the literature fact remains valid above for context." ✗ ("remains valid above for context" が文法的に意味不明)

source レベルでは「うまく書けている」 ように見える。 10 instances 中 5 instances broken だが 4 layer の sweep を回しても本人気付かず、 pdftotext で初めて発覚した実例。

**回避設計 (= 推奨される 1st choice)**: macro に hardcoded prose を持たせず、 **全 prose を argument に持たせる**。 macro は wrapper のみ:

```latex
% 修正後 (= bug 不能)
\newcommand{\subretracted}[1]{%
  \par\noindent\textit{[Retracted. #1]}\par%
}
% caller 側で full sentence を渡す:
%   \subretracted{See Movement 3 retraction box above for context.}
%   \subretracted{See Movement 3 retraction box above. The literature fact remains valid.}
```

caller が完結した sentence を渡すので、 macro 側 fixed text と argument の grammatical 衝突が原理的に起きない。

**回避不能で fixed framing を含めざるを得ない場合 (= 2nd choice)**: commit 前に必ず render verify。 全 instance を pdftotext で extract → semantic 読み:

```bash
pdftotext -layout file.pdf - > /tmp/render.txt
grep -B1 -A2 "your-marker-keyword" /tmp/render.txt
```

複数 instance がある場合は **全部** 読む (= 1 instance だけ verify して OK と結論する trap も同 class)。

**一般化 (= 同 class の bug が出やすい構造)**: figure caption macro / table header macro / footnote wrapper macro / theorem environment / itemize/enumerate label customization / hyperref anchor macro 等、 「macro 側で fixed prose を author し、 argument で variable 部分のみ受ける」 全ての構造に同警戒。 source 静的解析 (grep / lint) では基本的に expose 不能、 render が唯一の検証手段。

## <a id="compilers"></a>コンパイラ

odakin の標準は **pdf 直接出力 (= pdftex 系)**。tex+dvi+dvipdfmx の 2 段ワークフローは**英語論文では使わない**。

- **英語のみ** → **`lualatex`** が odakin の標準 (= TeXShop が `LuaTeX-1.21.0` で生成、PDF Producer 欄で確認済)。`pdflatex` も可 (どちらも pdf 直接出力で互換)
- **日本語含む** → `ptex2pdf` (内部で platex + dvipdfmx) または `lualatex` (jlreq クラス等)
- **<a id="class-dictates-engine"></a>class が engine を決める** (= 齟齬は engine 側で patch できない、 class を変えるか engine を変えるかの二択):

  | documentclass | 使う engine |
  |---|---|
  | `article` / `book` / `report` 等 (LaTeX default) | pdflatex / lualatex |
  | `jsarticle` / `jsbook` / `jarticle` / `jbook` (pTeX classes) | **platex + dvipdfmx** (pdflatex / lualatex は不可) |
  | `uplatex` 系 (Unicode 日本語 pTeX) | **uplatex + dvipdfmx** |
  | `ltjsarticle` / `ltjsbook` / `jlreq` 等 (LuaLaTeX-JS) | **lualatex** (luatexja 経由) |
  | `bxjsarticle` 等 (BX/JS series、 engine-agnostic) | class option で切替 |

  **診断**: `jsarticle` 等の pTeX class に `pdflatex` を打つと `! LaTeX Error: Unicode character X (U+XXXX) not set up for use with LaTeX` が日本語 1 文字ごとに連発する fingerprint が出る (2026-07-13 観測)。 log にこの pattern を見たら engine 選択ミス確定 → 正しい経路は `platex → platex → dvipdfmx` または `latexmk -latex=platex -pdfdvi <file>`。 `pdflatex` に別 patch を当てる方向は原理的に不可 (= class 側で pLaTeX 前提の macro を使っているため)。

  **同 fingerprint の別原因 (engine は正しい場合)**: 正しい `platex` 経路でも、**丸数字 ①②③ (U+2460 系) 等の JIS X 0208 外文字**は同じ `Unicode character not set up` エラーになる (2026-08 に公募要領の「公募内容③⑤」を調書へ引用して観測)。対処 = `uplatex` へ移行 / `otf` package の `\ajMaru{3}` / 引用文なら番号を落として書き換え (調書等の使い捨て文書は書き換えが最速)。エラー行数が「日本語ほぼ全文字」なら engine ミス、「特定の記号だけ」なら本項。
- **BibTeX フルビルド**:
  - **lualatex (英語、odakin 標準)**: `lualatex → bibtex → lualatex → lualatex`
  - pdflatex (英語、互換代替): `pdflatex → bibtex → pdflatex → pdflatex`
  - lualatex + 日本語著者: **`lualatex → upbibtex → lualatex → lualatex`**（後述「日本語著者の BibTeX 処理」 参照、`bibtex` は不可）
  - platex 系 (日本語、tex+dvi 経由): `platex → bibtex → platex → platex → dvipdfmx`
- リポの CLAUDE.md / README に手順があればそちらを優先

⚠️ **graphics 駆動 driver の罠**: `\usepackage{graphicx}` の default driver は engine 依存:
- pdflatex / lualatex → pdftex / luatex driver (= .pdf を直接読める、.xbb 不要)
- platex (tex+dvi) → dvips driver (= .pdf 不可、.xbb もデフォルトでは読まない)

英語論文を pdflatex で書いていれば graphics は素直に動く。platex 系で .pdf 図を使うなら `\usepackage[dvipdfmx]{graphicx}` または `\documentclass[...,dvipdfmx]{...}` が必要。

⚠️ **driver 指定は graphics 以外にも要る**: `hyperref` / `xcolor` / `tikz` も DVI 経由では driver を渡さないと `\special{ps: SDict ...}` 等の PostScript special を吐き、`dvipdfmx` が `Interpreting PS code failed` で壊れる（PDF は一応出るが**リンク・色・図が壊れ**、`ptex2pdf` は `failed` を返す）。 package ごとに `[dvipdfmx]` を付けるより **`\documentclass[...,dvipdfmx]{...}` で全 package に一括適用**するのが確実（global option を各 package が拾う）。

⚠️ **`ptex2pdf` / `platex` の exit code は信用しない**: clean な DVI（`Output written on ....dvi`）が出ていても wrapper が非ゼロ exit を返すことがある。確実な build は **`platex → platex → dvipdfmx` を個別実行**し、(a) log を `grep -iE "^! |Overfull"`、(b) `.pdf` が実際に再生成されたか（timestamp / `dvipdfmx` の `... bytes written`）で判定する。exit code 単独を成功 signal にしない。

⚠️ <a id="nonstopmode-hides-undefined-env"></a>**`-interaction=nonstopmode` は undefined environment を握り潰して PDF を出す**: クラスが `amsmath` を読んでいないのに `\begin{equation*}` を書くと `! LaTeX Error: Environment equation* undefined.` が出るが、**nonstopmode では build が続き PDF も生成される** (中身は壊れた組版)。学会・申請書の配布クラスは `amsmath` を仮定できない (2026-08-22 実測: 科研費 LaTeX クラス)。→ **build の度に `grep -c "^!" *.log` が 0 であることを確認する**。素の `\[ ... \]` は amsmath なしで動くので、可搬性が要る文書ではこちらを既定にする。

## <a id="matplotlib-cjk-figure-embedding"></a>matplotlib の CJK 入り図は PNG で取り込む (PDF は platex+dvipdfmx で描画だけ化ける)

matplotlib が CJK フォント (macOS Hiragino 等の `.ttc`、`pdf.fonttype = 42`) を埋め込んだ PDF を
`\includegraphics` で platex + dvipdfmx に通すと、**図中の日本語ラベルが描画だけ化ける**
(2026-08-21 実測)。見落としやすい理由 = **文字抽出 (ToUnicode) は正常**で、viewer によっては
読めることもある → 「PDF を目視した」だけでは気づかない。fitz / gs の両エンジンで化けたので、
投稿先・審査側の PDF 変換でも危険と判断する。

- ❌ `pdf.fonttype = 3` — 古い matplotlib では CJK 非対応 (`UnicodeEncodeError`)、しかも失敗時に
  出力 PDF を壊す (0 byte / 不完全)。
- ❌ gs `-dNoOutputFonts` で outline 化 — 化けた glyph をそのままパス化するだけで無効
  (+ gs 既定の PDF 1.7 は dvipdfmx が取り込み拒否し build が silent 失敗する。1.5 を指定しても無意味)。
- ✅ **Agg レンダリングの PNG (300 dpi) を `\includegraphics` する** — viewer / 変換系に依存しない。
  モノクロ印刷前提の書類 (科研費調書等) なら品質は十分。
- 代替 (vector が必要な場合): `.ttc` でない単体 TTF (IPAex 等) を `font_manager` で指定して Type 42
  埋め込み (未検証)。

検証の作法: 図を含む頁を **fitz 等で raster 化して目視** (PDF viewer の表示を信じない)、
`page.get_fonts()` で埋め込みフォントの素性も見る。

## <a id="tall-inline-math-line-collision"></a>キャプションに背の高い行内数式を書かない (行送りを超えて上の行に食い込む)

**肩付き・添字・`\int` の上下限**を持つ行内数式は行の高さを押し上げる。キャプションは `\small` で組まれる
ことが多く (`caption` パッケージの設定、あるいは `\caption{\small ...}` と手で書く。⚠️ **標準クラスの
`\@makecaption` はサイズを変えない** = 「既定で小さい」ではない)、行送りが絶対値として狭いぶん破綻が目立つ。

実測 (2026-08-22): `$e^{-i(E-i\Gamma/2)s}$` を含む caption 行の bbox が上の行に **2.5 pt 食い込み**、
著者から「キャプションが本文と被っている」と報告された。**この事例ではインク自体は接触していなかった**
(raster 化して確認) が、読み手には重なりとして映る。逆に別行立てを回り込みに入れた事例では**インクが
本当に重なった** (→ 次節) ので、bbox の重なりを見つけたら**必ず raster 化して裁定する**。

- ✅ **キャプションは語で書く。式は本文が持つ** (= caption は「何を見るか」を言う場所で、定義を置く場所ではない)
- ✅ 本文の行内でも高さを抑えたいときは、背の高い部分に**名前を与える** —
  `e^{-(s-\Delta T)^2\sigma_E^2/2}` → `w(s-\Delta T)`（`$w$` は幅 `$1/\sigma_E$` の Gauss 窓）。
  二重の肩付きが消え、読者にとっても平易になる
- ❌ `\smash` / `\raisebox` で高さを詐称する — TeX の衝突回避を無効化して**本当に**重なる
- 別行立てに逃がせるなら逃がす。ただし回り込み中は不可 (→ 次節)

## <a id="wrapfig-no-display-math"></a>wrapfigure の回り込み段落に別行立て数式を入れない (キャプションが本文に重なる)

`wrapfig` は図の高さから「短くする行数」を数えて回り込みを作る。`wrapfig.sty` 自身のコメントによれば
**別行立ての数式は一律「3 行」として数えられ**、また「大きな数式は見た目が悪い / 小さな数式なら問題ない」
とも明記されている (= 「使うな」ではなく「数え方が近似である」)。この近似が外れると
**本文が全幅に戻った上にキャプションが印字され、インクが物理的に重なる** (2026-08-22 実測: 回り込み段落に
`\[ \int_0^\infty ... \]` を入れた瞬間、図のキャプション末尾 2 行が本文の上に印刷された)。

- ✅ 回り込み中の式は**行内**に置く (高さ対策は前節)
- ✅ 別行立てが要るなら、`\begin{wrapfigure}[N]{r}{...}` で行数 N を明示する (= 近似を人間が上書き。
  本文を増減したら再調整が要るのでコメントを残す)、図を通常 float にする、式を回り込みの外の段落へ移す
- ⚠️ 検出は目視より機械 (→ 次節)。「見た目が崩れていないか」を人間の注意力に任せない

## <a id="pdf-line-collision-detection"></a>PDF の行かぶりを機械検出する (PyMuPDF、目視に頼らない)

組版の重なりは**生成 PDF の行 bbox を総当たりで交差判定**すれば決定論的に見つかる。図・回り込み・
狭い段・詰めた `\vspace` を使った書類 (投稿論文・申請書・様式) では、build の最後に必ず回す。

```python
import fitz, itertools                      # pip install pymupdf
for pno, p in enumerate(fitz.open(path), 1):
    L = [(fitz.Rect(l["bbox"]), "".join(s["text"] for s in l["spans"]).strip())
         for b in p.get_text("dict")["blocks"] for l in b.get("lines", []) ]
    L = [(r, t) for r, t in L if t]
    for (r1, t1), (r2, t2) in itertools.combinations(L, 2):
        x = r1 & r2
        if not x.is_empty and x.height > 2.0 and x.width > 3.0:   # 閾値は経験値
            print(f"p{pno}: {t1[:24]!r} ∩ {t2[:24]!r}")
```

- **本物の事故**: 別ブロック同士 (= キャプション ∩ 本文、図 ∩ 本文) の交差。必ず直す
- **許容しうる flag**: 隣接行同士が肩付き・`\int`・`\sqrt`・`\gtrsim` 等で数 pt 重なるもの
  (= glyph bbox の重なりで、インクは `\lineskip` が守っている)。**必ず raster 化して目視で裁定**する
- 画像との衝突も同様に `p.get_image_info()` の bbox と突き合わせれば取れる
- **図の中身側の同哲学 gate** (= matplotlib ラベルの枠内保証、図 script 側で assert):
  [`matplotlib-figure-qa.md#assert-texts-inside`](matplotlib-figure-qa.md#assert-texts-inside)

## <a id="wrapfigure-page-carryover"></a>wrapfigure が頁末に来ると次頁冒頭が短行で続く

`wrapfigure` は図の高さから「短くする行数」を決めるため、図が頁下端に来ると**次頁の冒頭数行も
狭いまま**になる (白い穴が空く)。対処 = 図を段落のもっと前に置く / 幅を絞る / 行数を明示
`\begin{wrapfigure}[N]{r}{...}` (N = その頁に残る行数。本文を増減したら要再調整なのでコメントを残す)。

## <a id="wrapfig-caption-page-overflow-loss"></a>wrapfigure の箱が頁末を越えると越えた分の caption は黙って消える

`wrapfigure` は頁をまたげないため、図 + caption の箱が頁下端を越えると、**越えた部分の
caption が error も warning もなく視覚的に切断される** (= 文の途中で「…に置」のように途切れて
印刷される。PDF の text 層には全文が残ることがあり、`get_text()` 検査では検出できない =
視覚 render の確認が必須)。周辺本文を増減した時・caption を伸ばした時・幅を広げた時
(= 幅↑ → 回り込み本文の行数↑ + caption の折り返し行数変化で箱の高さが動く) に発生しやすい。

- 対処: caption を短く保つ (図中ラベルと重複する説明は削る) / caption 末尾の文字列が
  **頁内に視覚的に在るか** をビルド後に raster 化して確認 (text 層 grep は偽陰性)
- 幅の trade-off: wrapfigure を広げると図中文字は大きくなるが、回り込み本文の行が
  短くなって総行数が増え、頁溢れ・箱の頁末超えの両方を誘発する — 広げたら必ず頁数と
  caption 完結を再検査する
- sibling: 次頁短行の穴 = [#wrapfigure-page-carryover](#wrapfigure-page-carryover) /
  別行立て禁止 = [#wrapfig-no-display-math](#wrapfig-no-display-math)

## <a id="bibliography-style"></a>Bibliography スタイル
- **JHEP.bst を使う**（個人的好み）。`note` フィールドも表示するバージョンを使用
- 正本: `~/Claude/claude-config/JHEP.bst`（ver. 2.18 ベース + note 全 entry type で有効化、md5: `0934fe19…`。 2026-07-24 に header comment 内の Unicode curly quotes を LaTeX 式 ``…'' に正規化 = char-fixer 配下 repo へ配布しても md5 が割れない idempotent 化、 機能変更なし）
- `setup.sh` が **TEXMFHOME** にインストール（odakin: 自動、他ユーザー: オプション表示。 user 所有 + ls-R 不要ゆえ sudo/texhash 不要。 ⚠️ 旧方式 texmf-local + texhash は ls-R が root 所有だと silent fail し「cp 成功・kpsewhich 不可視」 の死角を作る = 2026-07-24 実測 RCA、 導線 verify は `kpsewhich JHEP.bst` の md5 照合）
- **リポに vendor する場合は必ず正本から copy し、 `md5 -q <repo>/JHEP.bst` を正本 md5 と照合する**。 ⚠️ **他 repo からの copy は禁止** — 既存 repo には note 無効の stock v2.7 等の stale copy が複数残存しており、 そこから copy すると stale が増殖する（2026-07-24 RCA: `@unpublished` in-preparation entry の note が silent に落ちる形で発覚。 「note 表示有効」 と信じている file が実は stock、 は目視で見抜けない = md5 照合が唯一の cheap gate）
- `\bibliographystyle{JHEP}` を指定
- 将来 style を改版したら: 正本を編集 → 本節の md5 更新 → `setup.sh` 再実行で TEXMFHOME 同期 → vendor 済み repo は次に触る時に md5 照合で気付く

## <a id="no-biblatex"></a>biblatex は使わない（JHEP.bst と非互換）

JHEP.bst は **legacy BibTeX 用の `.bst`** であり、`biblatex` とは互換性が無い。次のようなコードを見つけたら legacy BibTeX に切り替える:

```latex
% ❌ biblatex (JHEP.bst が効かない)
\usepackage[backend=bibtex]{biblatex}
\addbibresource{refs.bib}
...
\printbibliography

% ✅ legacy BibTeX (JHEP.bst 想定の正式記法)
\bibliographystyle{JHEP}
\bibliography{refs}
```

biblatex で同等の出力スタイルを使いたければ `biblatex-jheppub` 等の別パッケージが要るが、odakin の運用では legacy BibTeX + JHEP.bst が canonical。

## <a id="japanese-authors-bibtex"></a>日本語著者の BibTeX 処理

`bibtex`（legacy, ASCII 想定）は日本語著者を name parse できず、姓の最初の 1 文字が文字化け（U+FFFD）または "First Last" 誤判定で姓だけ消える。対策は 2 段:

**(1) コマンド**: `bibtex` でなく **`upbibtex`**（TeX Live 同梱、UTF-8 直接処理）を使う

```bash
# ❌ bibtex main          → 「川.~紳一」のような出力に化ける
# ✅ upbibtex main        → 日本語そのまま処理
```

**(2) refs.bib の表記**: 著者を `{...}` ブレースで囲み、bibtex の First/Last name parser を回避する

```bibtex
% ❌ bibtex は「川上」を First、「紳一」を Last と誤判定
author = {川上 紳一 and 吉田 英太郎}

% ✅ ブレースで姓名一括 → 単一 entity 扱い、化けない
author = {{川上 紳一} and {吉田 英太郎}}
```

JHEP.bst のような `F.~Last` 形式の bst では、ブレース内が全部 Last 扱いになって「川上 紳一」 のまま出力される。

## <a id="refs-bib-verification"></a>refs.bib 整備フロー（実物検証によるハルシネーション防止）

文献情報（著者・タイトル・巻号ページ）を refs.bib に追加する前に、次の優先順で**実物検証**する:

1. **PDF 実物が手元にある** → 直読して書誌情報を確定
2. **PDF 実物がない** → 同論文を引用している後発論文の参考文献欄で交差検証
3. **どちらも無い** → entry を作らない（推測で作らない）

**やってはいけないこと**:

- WebSearch の summary だけを根拠に entry を作る（summary は hallucinate する。[`web-tools.md` websearch-summary-hallucinates](web-tools.md#websearch-summary-hallucinates) 参照）
- 既存 refs.bib の entry を**検証せずに**信用する（共同編集者や過去の自分が誤同定している可能性。実例: 同名著者の別論文と取り違え、改訂版のタイトルを初版と混同 等）
- 似たキーワード・近い年代の論文を「これだろう」 と推測して埋める

**典型的な落とし穴**:

- Mandelbrot 1977 と 1982 で本のタイトルが違う（1977: *Fractals: Form, Chance, and Dimension* / 1982: *The Fractal Geometry of Nature*。同著者・近接年・関連内容で取り違いやすい）
- 同姓著者の別人（例: 「川上 紳一」 と「川上 智一」）
- 巻通しページと号内ページの混在（学会誌で 2 種の page number が併記される場合）

## <a id="jhep-bst-notation"></a>JHEP.bst 記法
JHEP.bst はフィールドから自動リンクを生成するので `\href` 手書き不要（二重リンクの原因）。
- `doi`: DOI 本体のみ（例: `10.1103/PhysRevA.61.012104`）
- `eprint`: arXiv ID のみ（例: `quant-ph/9905023`）。`archivePrefix = "arXiv"` と併用
- `url`: doi や eprint があれば不要
- `note`: 自由テキスト。自動リンク対象外の補足情報に使う

## <a id="jhep-future-citation"></a>JHEP.bst で future citation（in preparation、タイトル未定）を引く

執筆中の続編論文などを「著者 + in preparation」だけで引きたい（タイトル未確定なので入れない）場合の recipe（2026-07-13、Overleaf 共著 paper で確立）:

```bibtex
@unpublished{Oda:2026prep,
    author = "Oda, Kin-ya and friends",
    note = "{\unskip}, in preparation"
}
```

- **`@unpublished` を使う**。`@article` + `journal = "in preparation"` は workaround としては動くが、entry type の意味が誤り。また `@article` で journal を空にすると空 journal block の「`, .`」が残骸として render される
- **note 先頭の `{\unskip},`**: title が空だと bst が author と note の間の区切り（カンマ）を落とし「`friends in preparation`」と連結される。素の `", in preparation"` では今度は author block 末尾の space が残り「`friends , in`」になる。`{\unskip},` が前の space を潰してから comma を置く → 「`K.-y. Oda and friends, in preparation.`」
- bibtex の `Warning--empty title` は想定内（無害）
- **タイトル確定時**: `title = "{...}"` を追加し、note を素の `"in preparation"` に戻す（title があれば bst が区切りを正しく出すので `{\unskip},` hack は不要になる）
- 前提: note を render する版の JHEP.bst（[正本](#bibliography-style)）。stock JHEP.bst は note を落とすのでこの recipe 全体が silent no-op になる

## <a id="hyperref-settings"></a>hyperref 設定
**新規 LaTeX ドキュメントは以下の hyperref 設定を使う:**
```latex
\usepackage[bookmarks=true,bookmarksnumbered=true,setpagesize=false]{hyperref}
```
- `\hypersetup{colorlinks=true}` は使わない。hyperref のデフォルト (`linkcolor=red`, `citecolor=green`, `urlcolor=magenta`) は赤緑紫がモトリーで見にくい。`allcolors=blue` で揃える手もあるが、印刷時にも色が乗るので避ける
- 上記 `[bookmarks=true,...]` 設定はリンク本文を黒のままにし、PDF annotation の薄い枠 (border box) のみ追加する。枠表示は viewer 依存（Preview/Adobe では薄く表示、印刷では非表示）
- 完全に枠も色も無くしたい場合は `\hypersetup{hidelinks}` を追加
- 既存の `\hypersetup{colorlinks=true}` がある場合はリンク色を改善するため上記に migrate する

## <a id="pre-commit-hook"></a>pre-commit hook（Unicode→LaTeX 自動修正）
`setup.sh` が **全リポに自動インストール** (Step 6)。 hook 自体が staged file 中の `.tex/.bib/.bst/.cls/.sty` の有無を判定し、 LaTeX file 不在の repo では no-op で exit 0 (`scripts/pre-commit-bib` L31-35)。 よって LaTeX file 検出は install 時に不要、 全 repo install で robust。

手動確認・インストール:
```bash
# 確認: .git/hooks/pre-commit が pre-commit-bib を指しているか
ls -la .git/hooks/pre-commit
# インストール (setup.sh が走らなかった repo の retroactive fix):
ln -s ~/Claude/claude-config/scripts/pre-commit-bib .git/hooks/pre-commit
```

ステージされた `.tex`/`.bib` 等の非 LaTeX 文字（Unicode 引用符、ダッシュ等）を自動でLaTeXコマンドに変換する。 具体例:

- `—` (Unicode em-dash U+2014) → `---` (LaTeX em-dash command)
- `–` (Unicode en-dash U+2013) → `--`
- `"..."` (Unicode smart quotes) → `` ``...'' ``
- `ö` 等 Unicode 西欧文字 → `{\"o}` 等の LaTeX accent command

**Claude への規律**: `.tex/.bib` を新規作成・編集する前に本 convention を読むこと。 Markdown 流儀で literal `—` を直書きすると LaTeX で正しく render されない (Unicode em-dash は通常の LaTeX font に欠落することが多い)。 hook が機械的に catch するが、 hook 未 install repo では catch されない (= 2026-05-14 個人層 private repo の深い path で発生、 RCA は `claude-config/DESIGN.md`)。

### <a id="pre-commit-hook-old-design-failure"></a>旧設計の失敗 (2026-05-14)

旧 setup.sh Step 6 は「`.tex/.bib` を含む repo にだけ install」 という時点依存検出を採用していた。 問題は 2 つ:

1. **時点依存**: setup.sh 実行時に `.tex` 不在の repo は skip → 後から `.tex` 追加されても hook 未 install のまま
2. **bash glob 深度不足**: 検出 logic `ls "$REPO_DIR"**/*.tex` は globstar 無効時に 1 階層しか見ない。 個人層 private repo の `.tex` が深い path (depth 4) で detection failed

→ 全 repo install に切替えた (hook 自体が no-op skip するので害無し)。 移行は `setup.sh` を 1 回再実行すれば既存 repo に retroactive install される。

### <a id="fix-bib-unicode-codepoint-scope"></a>fix-bib-unicode の codepoint scope (2026-05-15 確認)

hook (`scripts/fix-bib-unicode.py`) の `UNICODE_MAP` は **U+2013 (en-dash) と U+2014 (em-dash) のみ** dash 系で handle する。 他の「視覚的に似ているが codepoint が違う horizontal-line 系文字」 は scope 外:

| codepoint | 字形 | hook 挙動 | 物理書での出処 |
|---|---|---|---|
| U+2013 | `–` (en-dash) | → `--` | 範囲記号 (page 12--15) |
| U+2014 | `—` (em-dash) | → `---` | 欧文 em-dash |
| **U+2500** | `─` (box drawings light horizontal) | **scope 外、 保持** | 日本語典籍の罫線 (1 つでは細い、 2 つ並べて `──` で長い横棒) |
| U+2015 | `―` (horizontal bar) | scope 外、 保持 | 日本語小説の dash 様 (= em-dash 様の太い横棒) |
| U+30FC | `ー` (katakana-hiragana prolonged sound mark) | scope 外、 保持 | カタカナ長音 (= dash ではないが視覚的に紛らわしい) |

✅ **math 内の en/em-dash は math-mode-aware に正規化される (2026-06-18 修正)**: 以前は `$–$`
(= U+2013 を math mode 内で minus のつもりで書く) も hook が `$--$` に変換し、 LaTeX が `--` を
minus 2 個と印字して壊れていた。 現在は `fix-bib-unicode.py` の `_fix_dashes_math_aware` walker が
math (`$...$` / `$$...$$` / `\(...\)` / `\[...\]` / equation 系環境) 内の en/em-dash を **単一 ASCII
`-`** に正規化する (text mode の `–`→`--` とは別扱い)。 変換時は stderr に note が出るので意図を
確認すること。 とはいえ math の負号は最初から ASCII `-` で書くのが確実 (= walker の `\text{}` ネスト
等の限界に依存しない)。

**hook が file を必ず書換える 2 つの帰結** (= byte-pristine が要る場面の運用):
- **byte-pristine な baseline は tracked にしない**: 共著者版の verbatim copy を latexdiff 用に
  置く等、 byte 一致を保ちたい file は **untracked + gitignore** にする (= tracked だと commit 時に
  hook が dash/accent/quote を書換えて baseline が崩れる)。
- **byte-pristine な subset を commit/push する時は `git commit --no-verify`** (= hook を bypass、
  Overleaf scoped subset push 等。 [`overleaf-integration.md` scoped-subset-push](overleaf-integration.md#scoped-subset-push))。

**Claude 規律**: `.tex/.bib` を書くとき、 「視覚的に em-dash」 のつもりで何の codepoint を打鍵しているか自覚する。 input method (= IME) が打鍵によって違う codepoint を吐くことがあり、 同じ文書内で codepoint 不一致が発生する (= 2026-05-15 個人層 private 日本語 LaTeX project の lecture draft で comments 部 U+2014 / body 部 U+2500 の混在を 1 セッション内で気付かずに作成、 hook が U+2014 のみ変換した結果 visual 一致だが source 不一致に着地)。 IME の確認 + 章執筆 1 個分書いたら `grep -P "[\x{2013}\x{2014}\x{2015}\x{2500}]"` で出現 codepoint を audit する。

### <a id="vendored-latex-opt-out"></a>vendored / verbatim LaTeX の opt-out (2026-06-09)

hook は自分が書く LaTeX を正規化する道具なので、 **第三者の vendored ソース (arXiv 論文ソース等) を repo に byte-for-byte で取り込む時は触られると困る** (= 著者名アクセントや dash が勝手に LaTeX エスケープ化され、 upstream と diff したとき spurious 差分になる)。

そこで `pre-commit-bib` は `.gitattributes` で **path 単位の opt-out** を honor する。 該当 path の `latex-autofix` 属性を unset すれば、 その file は auto-fix から除外され byte 保存される:

```gitattributes
# 例: vendored な論文ソースを丸ごと保護
notes/vendor/**            -latex-autofix
papers/upstream/ms.tex     -latex-autofix
```

- 属性なし (= 既定) の file は従来どおり fix される (= 後方互換)。
- 仕組み: hook が staged LaTeX file 各々に `git check-attr latex-autofix -- <file>` を問い、 `unset` のものを fixer から外す (`scripts/pre-commit-bib`)。 末尾の layer-3 chain hook は除外と無関係に常に走る。
- `.gitattributes` は commit に乗るので全 clone (共同編集者含む) に伝播する。
- ⚠️ opt-out は「自動 fix からの保護」 であって「自分が書く新規 .tex でアクセント直書き OK」 ではない。 vendored 取り込み専用。

### <a id="pre-commit-hook-design-motivation"></a>設計動機 (2026-06-09)

hook に除外機構が無く、 ある repo に arXiv の LaTeX ソースを verbatim 取り込んだ時、 初回 commit で bibliography 著者名 (`Krämer`→`Kr{\"a}mer`) と dash が自動正規化され「verbatim」 が崩れた。 public な本 repo から全 repo に配られる hook に opt-out が無いのは設計欠陥、 と判断して `.gitattributes` honor を追加。 改変は意味的には identity-preserving (LaTeX 描画同一) だが、 vendored source は upstream との byte 一致が価値なので除外できるべき。

## <a id="japanese-horizontal-rule"></a>日本語横罫線 (em-dash 系) の書き方 (2026-05-15、 個人層 LaTeX project 経験で導入)

日本語典籍 (= 物理書・数学書・小説・新聞) で多用される「**思考の挿入・補足・話題転換**」 を示す長い横棒 (typographically: `──` or `――`) を LaTeX で書く 3 方式の比較。 視覚的には全て似ているが source / build / hook との相互作用が異なる。

| 方式 | source 例 | PDF 出力 (uplatex + jsbook/jsarticle) | hook 相互作用 | 視覚的 feel |
|---|---|---|---|---|
| (a) U+2500 doubled | `本章はこう書く ── これが結論` | 日本語 font の box drawings light horizontal glyph × 2 = `──` (細く均一の幅の罫線 2 連) | hook scope 外、 保持 | 日本語典籍に最も忠実 |
| (b) LaTeX em-dash | `本章はこう書く --- これが結論` | em-dash 1 個 = `—` (タイポグラフィ的な横棒 1 本) | hook が U+2014 → `---` に変換 (= source clean を保てる) | 欧文 em-dash スタイル、 やや短い |
| (c) LaTeX em-dash doubled | `本章はこう書く ------ これが結論` | em-dash 2 個隣接 = `——` (タイポグラフィ的な横棒 2 連) | ASCII only、 hook 介入なし | (a) に近い罫線風、 ただし接続点に細い seam が見えうる |

**ligature 機構**: LaTeX で `---` は 3 文字 ligature として em-dash 1 個に変換される。 `------` は 「`---` + `---`」 と parse され em-dash 2 個になる。 `----` (4 文字) は `---` + `-` で em-dash + hyphen、 `-----` (5 文字) は `---` + `--` で em-dash + en-dash になるので、 横罫線目的なら 3 の倍数 (= 3 か 6) を使う。

**推奨選択** (= 2026-05-15 個人層 LaTeX project の lecture draft 判断):

- **日本語典籍に近い見た目**を最優先 → (a) U+2500 doubled。 ただし IME 由来の codepoint 混在事故に注意 (= 上の「fix-bib-unicode の codepoint scope」 参照)
- **source ASCII clean + hook 非依存**を優先 → (c) `------`。 (a) に近い視覚 feel を ASCII で実現
- **欧文流儀でよい / 単一の em-dash で十分** → (b) `---`。 最もシンプル

**過去の事故 + 判断経緯**: 個人層 LaTeX project の lecture draft で当初 (a) U+2500 doubled を使用、 5/15 セッションで Claude が「uplatex + okumacro が日本語横罫線として render する」 と verify なし主張、 user の「これ本当?」 で実物 verify、 (b) `---` に一旦切替するも user が日本語典籍の見た目を考慮し直して (c) `------` に再切替で着地。 okumacro は実際には U+2500 の render に関与しておらず、 単に uplatex default の日本語 font が U+2500 を box-drawing glyph で render するだけだった (= Claude の typographic 主張は実物 verify なしには信用しない、 詳細規律は個人層 work-discipline.md §「Typographic claim」)。

## <a id="document-reading"></a>ドキュメント読み取り

- **内容理解が目的なら PDF を `pages` パラメータ付きで読む。** tex ソースはトークン消費が大きい（数万トークンになることも）。PDF なら必要なページだけ効率的に読める
- tex は **数式の編集が必要な場合のみ** 開く。その場合も `offset`/`limit` で必要な範囲に限定する

### <a id="grep-arxiv-source"></a>論文を grep/検証する: PDF プログラム抽出より arXiv ソース (2026-06-09)

上の「PDF を `pages` で読む」は **Read tool の視覚読解**（page を rendered で見るので数式も正確）。一方、**論文を grep / 数値裏取り / 反復参照** したくて `fitz`(PyMuPDF) や `pymupdf4llm` で**プログラム的にテキスト抽出**する場合は別問題で、数式忠実度が崩れる:

- `pymupdf4llm` (markdown): 構造は綺麗だが **ギリシャ/数式記号が壊れる**（θ→✓、Ω→⌦ 等）、図が junk テーブル化
- column-aware `fitz` `get_text`: 記号は保つが 2 段組の単語間スペース欠落・表フラット化

⇒ **数式が命の物理論文を機械的に扱うなら arXiv の LaTeX ソース (.tex) を取る**（math は LaTeX のまま完全、変換を挟むほど壊れる）。繰り返し参照する論文は .tex を repo に vendoring する手もある（その際 `-latex-autofix` で auto-fix から除外 = 上記「vendored / verbatim LaTeX の opt-out」）。図バイナリ・class file は除外し PDF/Dropbox 等に。worked example: 2026-06-09 Planck 2018 読書会で arXiv ソースを採用。

## <a id="chat-position-reference"></a>チャット本文での位置参照

- **ページ番号・セクション名・式番号で位置を示す。tex の行番号は使わない。** 行番号はツールが tex を読むときの内部座標で、ユーザー側 (PDF / TeXShop) には不可視。ユーザーがナビゲートできない参照は無効
- 行番号は Edit 等の tool 引数として内部で使うだけに留める
- ページ番号・**式番号・節番号**は `.aux` の `\newlabel{<label>}{{<番号>}{<page>}...}` の**第 1 フィールド (= 番号)** から引ける (= `zref-clever` を使う note は `\zref@newlabel{<label>}{\default{<番号>}...}` 行も同値)。最新ビルドの aux が無ければ PDF を読む
- **共著者の未 compile な `.tex` から番号を引く**には、 preamble の driver で 1 パス compile して aux を生成する。日本語 note (`ascmac` / `[dvipdfmx]` graphicx 等) は `uplatex -output-directory=<tmp> -interaction=nonstopmode <file>.tex` で通す (= pdflatex では通らない)。出力を tmp に逃がせば元の clone / Overleaf 入れ子を汚さない

## <a id="latex-in-chat-codeblock"></a>チャットで LaTeX / 数式を渡すときは code block で（コピペ保全）

ユーザーがコピペして使う LaTeX / 数式片を chat 本文に出すときは **必ず code block（fenced or inline backtick）に入れる**。 markdown は code span の**外**では `_` を強調（italic）マーカーとして消費するため、 `x_{\mu}` のような下付き満載の LaTeX を地の文に書くと **`_` が剥がれてコピペが壊れる**（`^` も環境次第）。 code span 内は markdown 非適用で `_` `^` `\` `{}` が literal 保持される。

- **コピペ用**の LaTeX / コード / `_` を含むパス → **code block**（保全優先）
- chat 上で**読ませるだけ**の数式（コピペ不要）は別軸 — 環境によって `$...$` が未レンダーなので Unicode 添字・上付きで書く

## <a id="gitignore"></a>.gitignore
**LaTeX 生成 PDF はリポに含める（ignore しない）。** 共同編集者がコンパイル環境を持っていない場合でも最新の PDF を参照できるようにするため。`*.pdf` を ignore する場合は `!<main>.pdf` で除外対象から外す。

共有リポでは共同編集者のために .gitignore に LaTeX 中間ファイルのパターンを明記する（`~/.gitignore_global` に頼らない）:
```
*.aux *.bbl *.blg *.log *.out *.toc *.fdb_latexmk *.fls *.synctex.gz *.synctex(busy) *.dvi
```

## <a id="gitattributes-line-endings"></a>.gitattributes（改行コード正規化）

以下のケースでは LaTeX リポに `.gitattributes` を置くことを推奨:
- Dropbox / iCloud 等のクラウド同期配下で運用するリポ（同期中に改行コードが書き換わることがある）
- Windows 共同編集者がいる共有リポ（CRLF 混入で git が全行 diff と見なすのを防ぐ）

どちらにも該当しないリポ（Linux/Mac のみ、個人運用）では不要。

推奨内容:
```
# Normalize line endings to LF in the repository
* text=auto eol=lf

# Binary files — no conversion
*.pdf binary
*.png binary
*.jpg binary
```

---

## <a id="japanese-title-wrap"></a>日本語長 title の文節境界改行 (title_wrap pattern)

ポスター・slide・cover page 等の **display title** で日本語 long title (= 15 文字以上) を扱う時、 LaTeX の auto-wrap は機械的に「N 文字/行」 で改行するため、 助詞「に」 「の」 や単語「保存量」 の途中で改行されて editorial 不自然になる。

**例**: 「一般相対性理論における二つの保存量:エネルギーと重力電荷」 (17 chars)

- auto-wrap (= 32pt × text_width 100mm): 「一般相対性理論に / おける二つの保存 / 量:エネルギーと重 / 力電荷」 (= 4 行、 助詞・単語途中改行)
- title_wrap で手動指定: 「一般相対性理論における / 二つの保存量: / エネルギーと重力電荷」 (= 3 行、 文節境界)

### <a id="title-wrap-how-to-apply"></a>How to apply

1. yaml の data file に `title_wrap.ja` 配列 (= 行 list) を optional field で許可:
   ```yaml
   title:
     ja: "一般相対性理論における二つの保存量:エネルギーと重力電荷"   # 純粋なタイトル (= web 用、 wrap なし)
   title_wrap:
     ja:
       - "一般相対性理論における"
       - "二つの保存量:"
       - "エネルギーと重力電荷"
   ```
2. build script で `title_wrap.ja` を LaTeX の改行 (`\\`) で結合して inject:
   ```python
   title_for_template = " \\\\ ".join(line.strip() for line in title_wrap)
   ```
3. font size は **最大行の文字数が text_width 内に収まる** ように choose:
   - default 40pt: 約 7 chars/line (= 100mm width)
   - 32pt: 約 9 chars/line
   - 25pt: 約 11 chars/line

### <a id="title-wrap-when-to-use"></a>When to use

short title (= 13 chars 以下) は auto-wrap で OK、 title_wrap 不要。 long title で auto-wrap 結果が editorial 不自然なときのみ **opt-in** で使う (= 全 title に title_wrap を強制すると過剰運用、 short title での手動指定は冗長)。

### <a id="title-wrap-font-override"></a>font override pattern (= long content への対応)

title だけでなく abstract 等の長 content も同様の課題が出る (= 2 段落 abstract が default 10pt で footer 領域を侵食、 等)。 解: yaml に `font.{title,abstract}.{size,leading}` override block を許可、 default は template の `\providecommand` で:

```yaml
font:
  title:
    size: 25         # default 40 (pt)
    leading: 31      # default 46 (pt)
  abstract:
    size: 9.5        # default 10 (pt)
    leading: 14.5    # default 17 (pt)
```

template 側:
```latex
\providecommand{\seminartitlefontsize}{40}
\providecommand{\seminartitleleading}{46}
% ...
{\fontsize{\seminartitlefontsize pt}{\seminartitleleading pt}\selectfont \seminartitleja}
```

これで content 長に応じた個別 case adjustment を yaml で完結 (= テンプレ本体は触らない、 各 case は yaml の override で対応)。

### <a id="title-wrap-paragraph-break"></a>paragraph break の保持 (= 段落区切り)

abstract 等の長 content で **段落区切り**を保ちたい場合: yaml の block scalar `|` の空行は LaTeX `\providecommand{...}{<value>}` 内では消える (= 単純 space 化される) ので、 build script で `\n\n` → `\par ` 変換する:

```python
abstract_latex = re.sub(r"\n\s*\n", r"\\par ", abstract_yaml)
```

PDF 上で段落区切りが visible (= LaTeX default `\parskip` で 1 行分の vertical gap)。 強調したいなら template 側で `\setlength{\parskip}{4pt}` 等。

### <a id="title-wrap-why"></a>Why

editorial typography で「機械改行を許容しない」 のは標準。 magazine cover / book cover / 学会ポスター等の display title は **文節境界改行**が defacto standard で、 auto-wrap 結果は visual quality を下げる。 yaml で行配列を持つ pattern は (a) wrap が text 編集の一部として扱える (b) display と web (= wrap なし) で同じ source から両方 generate できる、 2 つの利点がある。

## <a id="pdf-visual-verification"></a>PDF 視覚検証 reflex: compile success + log no-error だけで完了としない

LaTeX edit 後、 `pdflatex` が完走しても visual の overflow / misalignment / text 切れは普通に起きる。 「compile 成功」 を成功 signal にすると見落とす。 edit のたびに以下を回す:

1. `pdflatex -interaction=nonstopmode FILE.tex 2>&1 | grep -iE "^! |Overfull"` — fatal error + overflow warning を確認（platex DVI workflow なら `platex ... ; dvipdfmx ...` の各段で同 grep）
   - ⚠️ **`grep undefined` だけで済ませない**: `^!` (TeX error) は `Double subscript`・`Missing $` 等で出るが、TeX は recover して PDF を出すため「undefined 参照ゼロ」だけ見ると error を見逃す（例: `\newcommand{\X}{Y_{\rm z}}` を `\X_{...}` と使う double-subscript は PDF が出ても下付きが壊れる）。**必ず `^!` を grep** し、`error 0` を確認する。
2. `python3 -c "import fitz; doc=fitz.open('FILE.pdf'); pix=doc[N].get_pixmap(dpi=200); pix.save('/tmp/check.png')"` — 該当 page を PNG 化
3. `/tmp/check.png` を Read tool で開いて **視覚確認** (= 「compile OK」 だけで完了としない)
4. `Overfull \hbox (N pt too wide)` warning が出たら必ず該当 page を render して overflow が visual に問題ないか確認

### <a id="pdf-visual-verification-traps"></a>典型 trap (= 2026-05-18 EC erratum note 編集で連続再発)

| Symptom | Cause | Fix |
|---|---|---|
| `\paragraph{...}` 直後の `\colorbox{...}` が page 右に流れる + 右端 truncate | `\paragraph` は inline header、 後続 box が paragraph 内の continuation 扱い | `\subsubsection*{...}` か `\par\medskip\noindent\textbf{...}\par` で block separate |
| tikz の隣接 node が重なる | 2 node 間の position 計算が tight | 1 つの node に統合 (e.g., `=` と次 text を 1 node) または coordinates を広げる |
| `\verb|...|` が `\colorbox{...}\parbox{...}` 内で `! \verb illegal in argument` | `\verb` は box 引数内で使えない | `\texttt{...\\_...}` で literal underscore escape |
| `\bfseries` が math mode で `! Command \bfseries invalid in math mode` | bold を math 内で適用しようとした | `\boldsymbol{}` か、 `\text{\bfseries ...}` で text 切り替え |
| Unicode `✗` `✓` で `! LaTeX Error: Unicode character (U+xxxx)` | utf8 inputenc default で読めない記号 | `$\times$` `\checkmark` に置換、 または `\usepackage{pifont}` + `\ding{}` |
| table の comment 列が page 右を超えて truncate | column が自然幅で expand、 long text で overflow | `p{width}` で wrap 化 + `\setlength{\tabcolsep}{4pt}` で間隔調整 + 必要なら `\footnotesize` |
| tikzpicture 全体が page 右に偏る | tikz の `\node[align=center]` の width が長い text で右に extend、 bounding box が asymmetric | text 位置を `align=center` の代わりに固定 coord で配置 + node 間 spacing を測って overlap 避ける |

### <a id="pdf-visual-verification-why"></a>Why

`pdflatex` の exit code 0 + `! ` error 不在は **build success** の signal であって **visual success** の signal ではない。 `Overfull \hbox` は warning として log に出るだけで build を止めない (= 文字が page 外に hanging するだけ)。 PDF を visual で見ない限り「✓ IS RIGHT (phy...」 で truncate されている等の事故は気付けない。 PyMuPDF (`fitz`) は poppler 不要で macOS default で使えるので、 reflex として安価。

→ overflow を**そもそも出さない**設計則は [固定幅の箱に可変幅テキストを入れない](#fixed-width-box-overflow) (= 検出の前に予防)。

## <a id="fixed-width-box-overflow"></a>固定幅の箱に可変幅テキストを入れない (= 枠線が壊れる)

`\fbox{\begin{minipage}{Nmm}...\end{minipage}}` / `\parbox{Nmm}{...}` / 固定幅 `tabular` 列 (`p{Nmm}`) のような **固定幅コンテナに幅が読めない可変テキスト** (= 氏名・住所・機関名・タイトル・引用文字列 等、 長さが input 次第で変わるもの) を入れると、 内容が箱幅を超えた瞬間に **Overfull \hbox** になり、 視覚的には **枠線が割れる / 右にはみ出す / 紙面外へ流れる**。 source では「幅 Nmm 指定だから収まる」 ように見えるが、 収まるかは render しないと分からない (= [PDF 視覚検証](#pdf-visual-verification) の source-render asymmetry の layout 版)。

**回避設計 (= 1st choice = 幅を当てない)**: 箱幅を固定値で**推測しない**。 内容に自動フィットする container を使う:

- 複数行ブロックを枠で囲む (= 住所ラベル・宛名等) → **固定幅 minipage でなく `\fbox{\begin{tabular}{@{}l@{}} 行1 \\ 行2 \\ ... \end{tabular}}`**。 `\fbox` が tabular の自然幅 (= 最長行) にフィットするので overflow し得ない。
- 1 行なら `\fbox{...}` を直接 (= 自然幅)。
- レイアウト上どうしても固定幅で揃えたい場合 → **最長行が収まる幅を render で確認**してから固定 + auto-wrap が要るなら `p{Nmm}` 等で**改行を許す** (= はみ出しを折返しに変える)。

**検証**: 上記を使っても、 commit / 印刷 / user 提示の前に必ず [PDF 視覚検証](#pdf-visual-verification) を回す (= log の `Overfull \hbox` を 0 にする + PNG render で枠が 4 辺とも閉じているか目視)。 Overfull が残っているのに「できた」 と言わない。

**過去事例**: 固定幅 `minipage{150mm}` に長い機関名を `\LARGE` で入れた住所ラベルで、 機関名行が箱幅を超えて右枠線が消えた。 幅を広げる対症療法 (→158mm) でも Overfull が残り、 `tabular` 自動フィットに変えて根治した (= Overfull 0 + 枠 4 辺復活)。 幅当ては input 依存で脆い。

---

## <a id="infographic-design"></a>編集向け infographic / poster / 1 枚 figure の design 規約

scientific infographic (= A4 / A3 1 枚もの) や poster を LaTeX で制作するときの design choice。 TikZ / pgfplots を多用する制作では本 file の上記 LaTeX 一般規約 + `conventions/tikz-pgfplots.md` (TikZ/pgfplots gotchas) を併読。

### <a id="infographic-light-theme-print"></a>印刷前提なら light theme + cream paper

dark theme (= 黒背景 + 明色 text) は screen で映えるが **印刷時 toner / inkjet を大量消費**する。 1 枚 infographic を「印刷物として家に貼る / 配布する」 用途なら light theme 一択。 cream paper (`#FBF8F2` 系) は pure white より editorial で目に優しい。

```latex
\definecolor{bgpage}{HTML}{FBF8F2}    % cream paper
\definecolor{bgcard}{HTML}{FFFFFF}    % 白カード
\definecolor{fgstrong}{HTML}{1A1D26}  % near-black charcoal
\definecolor{fg}{HTML}{2E323F}        % body text
\definecolor{fgmute}{HTML}{6E7280}    % muted secondary
\usepackage{eso-pic}
\AddToShipoutPictureBG*{\AtPageLowerLeft{\color{bgpage}\rule{\paperwidth}{\paperheight}}}
```

### <a id="infographic-libertinus-font"></a>Libertinus フォントファミリー (= 数式統一の選択肢)

scientific infographic で Latin (= 英文) + math + Japanese を共存させる場合、 `TeX Gyre Pagella` 系より `Libertinus` 系の方が refined。 4 family を 1 set で揃えられる:

```latex
\setmainfont{LibertinusSerif}[
  Extension=.otf, UprightFont=*-Regular, ItalicFont=*-Italic,
  BoldFont=*-Semibold, BoldItalicFont=*-SemiboldItalic,
  Numbers=Lining,
]
\setsansfont{LibertinusSans}[
  Extension=.otf, UprightFont=*-Regular, ItalicFont=*-Italic,
  BoldFont=*-Bold, Numbers=Lining,
]
\setmathfont{LibertinusMath-Regular.otf}
\setmonofont{LibertinusMono-Regular.otf}
```

**`Numbers=Lining` (vs `OldStyle`)**: Libertinus の数字は default で OldStyle (= 「123」 が baseline からはみ出す古風な numerals) になりがち。 印刷 / 図表で数値を扱うなら `Lining` (= 現代的、 同高 numerals) に明示。 `Numbers=OldStyle` を意図的に選ぶのは literary 書籍用途のみ。

### <a id="infographic-hiragino-libertinus"></a>macOS Hiragino と Libertinus の組合せ

```latex
\setmainjfont{HiraMinProN-W3}[BoldFont=HiraMinProN-W6]
\setsansjfont{HiraginoSans-W3}[BoldFont=HiraginoSans-W6]
```

PostScript 名 (= `HiraMinProN-W3` 等) が必要。 display name (= `Hiragino Mincho ProN W3`) では fontspec が見つけられない。 詳細は [`tikz-pgfplots.md` hiragino-postscript-name](tikz-pgfplots.md#hiragino-postscript-name)。

### <a id="infographic-math-japanese-align"></a>数式 + 日本語を mix する align 環境

infographic / poster で「label / 関係記号 / 値」 を縦に揃えたいとき、 個別 TikZ node × 3 で配置するより `array{r@{\;}c@{\;}l}` 1 個に集約する方が baseline 整列が math engine 任せで精密:

```latex
\node[anchor=north west, font=\fontsize{7.4}{9.2}\selectfont, text=fgstrong, inner sep=0pt]
  at (x, y) {%
  $\renewcommand{\arraystretch}{1.0}\begin{array}{r@{\;}c@{\;}l}
    z              & \gtrsim   & 10^{12} \\
    t              & \sim      & 10^{-6}\text{--}10^{-5}\,\text{s} \\
    \text{過去}    & \approx   & 138\,\text{億年前} \\
    \text{距離}    & \approx   & 461\,\text{億光年} \\
    T_{\gamma}     & \gtrsim   & 10^{12}\,\text{K}\;\text{\tiny(90 MeV)}
  \end{array}$%
};
```

3 列の意味:
- `r` = label (= 右揃え、 z / t / 過去 / 距離 / T_γ が右端で揃う)
- `@{\;}` = 列間 spacing (= math thick space で固定、 array default の wide gap を抑制)
- `c` = 関係記号 (= 中央揃え、 ≳ / ~ / ≈ が縦軸で揃う)
- `l` = 値 (= 左揃え、 数値以降が左端で揃う)

**日本語は `\text{}` 内に書く**: math mode 内の `過去` / `距離` / 単位 (`億年前` / `億光年` / `K` / `s` / `MeV` / `GeV` / `eV`) は全部 `\text{...}` で囲む。 単位を裸で書くと `K` が math italic になる (= `K` 1 文字が変数扱い) 等の事故が起きる。 range の `--` (= en-dash) も math mode では double-minus に解釈されるので `\text{--}` 経由。

luatexja は `$過去$` (= 裸の kanji) も accept するが、 標準 idiom は `\text{過去}` (= 移植性 / 明示性で勝る)。

### <a id="infographic-print-a4"></a>print fidelity を A4 強制したい場合

```latex
\documentclass[10pt]{article}
\usepackage[paperwidth=297mm, paperheight=210mm, margin=0pt]{geometry}  % A4 landscape
\pagestyle{empty}
\parindent=0pt

\begin{document}
\noindent\begin{tikzpicture}[x=1mm, y=1mm]
  \useasboundingbox (0,0) rectangle (297, 210);
  ...
\end{tikzpicture}
\end{document}
```

`[x=1mm, y=1mm]` で TikZ 座標が mm 単位に固定、 `geometry` で page size mm 指定。 printer で「実寸印刷」 設定にすれば狙い通りの mm 単位で印刷される。 screen 表示では browser / viewer の zoom が効く。

## <a id="latexdiff-ulem-option-clash"></a>latexdiff: 本文が `ulem` を option なしで読むと差分 markup が silent に壊れる (2026-08-21)

**症状**: `latexdiff old.tex new.tex > diff.tex` → pdflatex は `! LaTeX Error: Option clash for package ulem.` を吐くが batchmode では PDF が出てしまい、 **追加/削除の下線・取り消し線が欠落した「差分に見えない差分 PDF」** ができる。 原因 = 本文の `\usepackage{...,ulem}` (option なし) と latexdiff preamble の `\RequirePackage[normalem]{ulem}` の衝突。

**対処**: 生成した diff.tex の先頭 (documentclass より前) に `\PassOptionsToPackage{normalem}{ulem}` を入れる。 1 行で済む:
```bash
latexdiff old.tex new.tex | sed '1s/^/\\PassOptionsToPackage{normalem}{ulem}\n/' > build/diff.tex
```
**検証**: diff.log の `^!` が 0 であること + 変更ページを画像化して markup を目視 (text 抽出は下線 markup で単語が分断されるので信用しない)。

**差分 PDF は 1 頁目に「何と何の差か」 を書く**: 差分を複数種類 (= 投稿版との全差分 / 直近の修正だけ 等) 送ると取り違えが起きる。 生成した diff.tex の `\begin{document}` 直後に表紙 1 頁を挿し込み、 **old / new が相手にとって何の版か**を書く (= 日付と出来事で指す。 内部 version 名・commit hash は書かない = [`physics-notes.md#no-internal-shorthand-in-deliverables`](physics-notes.md#no-internal-shorthand-in-deliverables))。 色の凡例・生成日時は不要 (= 差分 PDF を開けば色は自明、 情報を足すほど表紙が読まれない)。 そもそも**相手にとって意味のある切れ目でない差分は送らない** — 自分の作業日を境にした差分は相手の手元の版と対応しない。

**関連の罠**: 変更ブロック内の `\label {key}` (空白入り) は latexdiff が `\label` と `{key}` の間に markup を挟んで `! Argument of \label has an extra }` になる → 新規に書く label は `\label{key}` (空白なし)。
