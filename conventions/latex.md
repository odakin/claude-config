<!-- doc-meta
when: LaTeX を含むリポで作業するとき + revtex で 1 頁の文書 (正誤表など) を組むとき (#revtex-short-document)
category: paper
summary: LaTeX 固有規約（物理リポで参照）
-->
# LaTeX 規約

LaTeX を含むリポで適用。CLAUDE.md から参照: `~/Claude/claude-config/conventions/latex.md`

## <a id="equation-safety"></a>式の安全規則
- **原稿の表題・概要・序論・結論・式を AI agent が変える条件は [`manuscript-claim-ownership.md#rule`](manuscript-claim-ownership.md#rule) が正本** (著者の項目ごとの裁定 = 著者の発言の verbatim。 変更は提案として出す。 印字しない指示は直接書く許可ではない。 英語校正は可)。 機械 gate = `scripts/manuscript-claim-guard.py`。

## <a id="bare-parenthetical-crossrefs"></a>裸の括弧参照と `\labelcref`・`\eqref` の置き場所の検出、保持検査

裸の括弧参照を避ける文体を採用した原稿では、[check-latex-crossrefs.py](../scripts/check-latex-crossrefs.py) で候補を列挙する。`(Sec.~\ref{sec:x})` と `(\cref{sec:x})` は同じ表示上の問題なので、片方だけに一致する grep では検査にならない。改行・複数参照・付録や図式の参照・一般的な括弧マクロも対象とし、コメント・数式・verbatim は除外する。

同じ実行で `\labelcref` の置き場所も検査する。前提の文体は、参照が独立に立つ位置では `\cref` で「Eq. (N)」と印字し、名詞の直後に同格で添える位置だけ `~\labelcref` で素の「(N)」を置くものである。素の番号は名詞に付いていないと何を指すか読めず、`~` が無いと番号が行頭に落ちうる。候補は次の 3 形。

- `comma-apposition`: 名詞からカンマで離して浮かせた番号。例は `the flux, \labelcref{eq:a}, is conserved`。
- `independent-position`: 前置詞・接続詞・冠詞・be 動詞・一部の動詞の直後、文・段落・脚注・キャプションの先頭、または見出しや display 数式の直後に置いた番号。`in~\labelcref` のように `~` が付いていても同格にはならないので候補に出る。
- `missing-tie`: 名詞・インライン数式・マクロ引数の直後にあるが `~` の無い番号。参照に続く `and` / `or` / `to` の 2 つ目も対象。

範囲の 2 つ目 `--\labelcref` と、参照に続くカンマ区切りの項は正しい形として通し、`--list-all` で点検用に表示する。`\blue{...}` のようなインラインのマクロと素の `{...}` は透過し、その前の語で判定する。裸の括弧参照として既に出た `\labelcref` は重ねて出さない。判定は閉じた機能語リストに基づくため、リストに無い動詞の直後の `~\labelcref` は出ない。この文体を採らない原稿では `--no-labelcref-form` で外す。`~` の付かない `\labelcref` だけを拾う grep は、`~` 付きの独立位置を拾えないので代わりにならない (sweep の pattern を違反の一形で書く罠の一般則 = [`convention-design-principles.md#sweep-null-needs-per-form-control`](../docs/convention-design-principles.md#sweep-null-needs-per-form-control))。

<a id="eqref-placement"></a>`\eqref` も同じ素の「(N)」を印字するので、同じ 3 形で検査する。cleveref を使わない文体では独立の位置を `Eq.~\eqref` (`Eqs.~` / `Equation~`) と書き、名詞の直後の同格だけ `~\eqref` にする。型の語が前にある形は名詞の扱いで候補に出ない。参照に続く `and` / `or` / `to` の 2 つ目の `\eqref` は `~` の有無に依らず通す (`Eqs.~\eqref{a} and \eqref{b}`)。`\eqref` を独立の位置で使う文体を採らない原稿では `--no-eqref-form` で外す。実測: この形の検査が `\labelcref` にしか無かった間、cleveref を使わない原稿の「by~\eqref」「formula \eqref」は候補に出ず、手で全部を読むしかなかった。

使い方はスクリプトの `--help` と `--selftest` が正本。`--list-all` は関係を説明した括弧参照も含めて確認でき、`--baseline <git-ref>` は参照コマンド・ラベル・引用・保護領域の保持を比較する。`--report` は入力ハッシュ付きの検査記録を生成する。任意のマクロや include を展開する TeX 処理系ではないため、原稿から読み込むファイルも明示的に渡す。

修正は自動置換しない。参照先を読んで定義・導出・検証・設定の関係を判定し、本文の動詞や前置詞に結び付ける。`\labelcref` の候補も、名詞の直後に付け直すか、`\cref` にするか、近くの文が既に意図を果たしているので参照を落とすかを、文を読んで決める。`\cref` にするときは前に `~` を置かない。cleveref が名前と番号を自分で繋ぐので、番号だけが行頭に落ちることはない。候補ゼロや保持検査の成功は文意の正しさを保証しない。文意の確認と再ビルド後の目視確認を別に行う。

## <a id="mathbb-digits"></a>`\mathbb{数字}` は黙って化ける — 単位行列は `\mathbbm{1}` (bbm)

- **`\mathbb{数字}`(例 `\mathbb 1`, `\mathbb 0`)を使わない。** `amssymb` の `\mathbb` は**大文字 A–Z しかグリフを持たない**ため、数字を渡すと **compile error を出さずに黙って化ける**(missing glyph / 別字へ fallback)。= **視覚 QA でしか気づかない**沈黙故障(コンパイル成功 = 正しい、ではない好例)。
- **単位行列・恒等作用素は `\usepackage{bbm}` + `\mathbbm{1}`**(真の黒板太字 1)。代替: `\mathds{1}`(dsfont)、最低限 `\mathbf{1}`。同様に黒板太字の数字が要る一般ケースも `\mathbb` でなく bbm/dsfont 系を使う。
- **発火**: PDF の**視覚 QA で実物確認**が第一(doc 記載だけでは発火しない)。より確実には pre-commit / build で `\mathbb\s*\{?\s*[0-9]` を grep する mechanical guard を足す(= doc rule より発火信頼度が高い)。
- 実例: ある物理ノートの式で $\gamma_5^2=\,$`\mathbb 1` が化けていた(`\mathbbm{1}` で修正)。`\mathbb` を識別子マクロのつもりで数字に当てると起きる。

## <a id="uppercase-protect-symbols"></a>`\MakeUppercase` は記号の小文字も大文字にする — 物理量の文字は `\NoCaseChange{…}` で守る

見出しや英題を template 側で `\MakeUppercase{…}` にして all-caps で組むと、 題に入っている物理量・単位の記号 (`1/f` の f、 `pH`、 `mV` など) も大文字に化ける。 compile は通るので目視でしか見えない (実測)。

- LaTeX 2022-06 以降の `\MakeUppercase` は expl3 の case changing で、 `\NoCaseChange{f}` の中身を変えない (それより古い kernel は `textcase` package の `\NoCaseChange`)。
- template に値を流す生成器は、 大文字化から守る字を指定できる入口 (例 = 題の LaTeX 版を上書きする設定の key) を持つ。 公開用の plain な題には `\NoCaseChange` を入れない (web や一覧に命令が漏れる)。
- 入口を持つだけでは、 書き忘れた回にまた化ける (実測 = 記号と単位で 2 回)。 生成器は題に化ける形 (小文字の直後に大文字の語 = `eV`・`GeV`・`pH` / 数字/小文字 = `1/f` / 小文字 1 字の関数 = `f(R)`) を見つけたら、 守る版が書かれていない限り止まる。 普通の英単語と頭字語 (all-caps の語) は拾わない形にする。
- PDF の文字層で題を照合する検査が大文字小文字を無視していると、 この誤りは通る = 大文字化した版の検査では「守った字が小文字で残っているか」 を別に見る。

## <a id="italic-wrapper-upright-text"></a>文を `\textit` で包む macro は、 数式の中の `\text` (添字の P・単位の GeV) まで斜体にする — macro の中で `\let\text\textup`

引用文などを斜体で組む macro (`\newcommand{\qt}[1]{``\textit{#1}''}`) で包むと、 中の数式の `M_\text{P}` の P や `10^{16}\,\text{GeV}` の GeV まで斜体になる (実測)。 amsmath の `\text` は周りの文の字体を継ぐので、 立体の添字・単位が斜体の変数に見える。 compile は通るので目視でしか見えない。

- 直し方 = macro の中で `\text` を立体に差し替える: `\newcommand{\qt}[1]{``\textit{\let\text\textup#1}''}`。 差し替えは macro の群の中だけで効き、 本文の `\text` は変わらない。 `\textup` は数式の中でも働く (中で元の `\text` を呼ぶ = 循環しない)。
- 記号の macro の側を `\mathrm{P}` にしても直るが、 同じ文書で同じ macro を使う全部の式が変わる。 包む macro の側で直すほうが、 直す所が 1 つで済む。
- 斜体にしたら、 組んだ PDF の引用の中の添字と単位を拡大して見る (変わったのは字体だけなので、 文字層の検査では見えない)。

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
# 印字される部分だけを探す。 外した所 (% の後ろ・comment 環境・\iffalse) の一致は件数が出る
python3 scripts/tex-printed-grep.py '<element>' file.tex
# 外した所の行も見る
python3 scripts/tex-printed-grep.py --hidden '<element>' file.tex
# 鍵を変えずに用語を置き換えた後、 古い語の残りを探す (\label・\ref・\cite の鍵の引数を外す)
python3 scripts/tex-printed-grep.py -i --no-keys '<古い語>' file.tex
```

   `grep -v '^%'` では `\begin{comment}` の中と行末の comment を落とせない。 鍵の文字列は印字されないので、 用語の置き換えの後に `--no-keys` なしで探すと一致の大半が鍵の中になり、 本物の残りが埋もれる (実測)。 依頼書や台帳が「本文の文」 と挙げた文、 これから直す文も、 手を付ける前に同じ道具で通す (実測: 依頼書が本文として挙げた文が comment 環境の中にあり、 印字される同じ主張は別の節にあった)。 ある節を丸ごと comment に入れる commit は、 その節に後から足した文も一緒に寝かせる。 記録が本文にあると書いている文は、 節を寝かせた後にこの道具で確かめ直す (実測)。

2. prose summary (`SESSION.md`「migration 完了」等) と active source が食い違ったら **active source が勝つ**。summary 側を errata / 更新する。
3. 第三者 (共著者・レビュアー) が「その要素が原稿のどこにあるか分からない」と言ったら、それは **記憶の曖昧さでなく grep 等価の signal** — 推測で解決策を返す前に自分で active grep を回す。
4. <a id="strip-comments-keep-lines"></a>行番号を保ったまま comment を消して本文を script で調べるときは、 `%` の後ろだけを消して `%` 自身は残す。 comment だけの行を空行にすると、 本文に無い段落の切れ目ができ、 段落で区切る判定 (`\n\n`) が誤る (実測)。 行番号が要らず、 組版を変えない写しが要るなら、 comment だけの行を丸ごと落とす (`ai-collaboration/scripts/strip-tex-comments.py`)。

これは上の「comment-out 流儀の編集後は live `\cite` 集合を照合する」「長さ・段落構造の判断にコメントアウト行を数えない」と同じ **`%` は output から silent** という kernel の、*存在主張* 版 (前者 = 引用落ち / 中者 = 長さ誤算 / 本節 = 存在誤主張、3 つの consequence)。一般則 — 単一情報源の positive 主張の前に安価な検証を回す / prose summary を SoT と読み違えない — の正本は `CLAUDE.md` inline §3 (positive-claim branch) + [`docs/convention-design-principles.md` §2.3](../docs/convention-design-principles.md#sot-read-side) (read 側 SoT)・[§2.5](../docs/convention-design-principles.md#sot-duplication-trichotomy) (prose-mirror は別所 state の mirror で change 時に drift) で、本節はその LaTeX source への HOW 適用。

**事例 (2026-06、物理 LaTeX 原稿):** ある直和分解 (`H = A ⊕ B` 型) が運用台帳の prose で「migration 完了」と記録されたまま、4 日後に `%` + `\begin{comment}` で寝かされた。prose summary はその stale を ~7 週間保持し、その間に派生ノート PDF・`DESIGN.md` entry・共著者宛メール 3 通が**この分解を active 前提で**論じた (左辺の macro 名すら prose 側と source 側で食い違っていた = source 未参照の tell)。共著者が「その分解が原稿のどこにあるか把握できない」と明示 signal を出していたが、当時は記憶の問題と読み流し active grep を回さなかった。最終的に「まだ原稿にあるんだっけ?」の直接質問で初めて comment-out 状態が発覚した。

## <a id="latexdiff-review-snapshot"></a>latexdiff で差分レビュー PDF を作る

共著者に「どこを変えたか」を渡すとき（直した後だけでなく、まだ当てていない変更を提案して承認を求めるときも）、`latexdiff old.tex new.tex > diff.tex` で **追加=下線 / 削除=取り消し線** のレンダリング済み PDF を作る。文章で書いた変更の一覧だけでは、数式を含む変更はどこがどう変わるのかが読み取りにくい（実測）。comment-out-keep 流儀（旧文を `%` 化）の編集は raw の git diff でも読みにくい。提案の段階では原稿を変えず、仮に当てた版を一時 dir で組んで diff し、項目の一覧と照らせるよう印を付ける（[#latexdiff-item-labels](#latexdiff-item-labels)）。

<a id="latexdiff-new-file"></a>**作業 tree に無い版と比べるときは engine の `--new-file <写し>`**（仮に当てた提案の版、差分のために加工した写し）。base は git の revision から取り、新版は写しから読む（配備はしない）。比べるための一時 repo も commit も要らない。一時 repo に commit するなら、git の path を shell の変数（`$S/…`）で書かない: 原稿の guard は command の文字列を読むので repo を決められず、`inspection unavailable (git-unreadable)` で止める（実測、違反ではなく検査不能。path を展開した形で書けば通る = [`claude-code-permissions.md#git-path-variable-blinds-guard`](claude-code-permissions.md#git-path-variable-blinds-guard)）。

<a id="latexdiff-one-pass-of-two"></a>**2 つの pass が同じ原稿に入った後で、片方の変更にだけ印を付ける**: 依頼の開始時の rev をそのまま基準にすると、相手の変更にも印が付く。基準の版に相手の pass の変更を当て、両側に相手の変更が入った形で比べると、印は自分の pass だけに付き、相手の行は今の値のまま読める。engine の base は git の revision なので、捨てる clone の中で、基準の commit の上に相手の `git diff -U0` を `git apply --unidiff-zero` で当てて commit し、`--repo <clone> --base <その commit> --no-deploy` で組む。段落 1 行の原稿では相手と自分が同じ行を直していて patch が当たらないことがある。その file は新版から自分の変更だけを文字列で戻して基準にする（実測）。組む前に `git diff -U0 <基準> <新版>` の hunk の数が自分の pass の数と合うかを見る。

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
| 新版だけに入れた体裁の macro（引用を斜体にする `\qt{…}`・`\enquote{…}` など）で、包んだ文がまるごと削除 + 追加になり、下線の付いた追加側が改行できずに右の余白からはみ出す | latexdiff は旧版の ``…'' と新版の `\qt{…}` を、中の字句が同じでも別の token と見る。追加側は ulem の下線の群になり、改行できない（実測） | 差分の写しで、その macro を旧版の形（``…''）に戻し（括弧の釣り合いを数えて置き換える）、engine の `--new-file <写し>` で比べる（[#latexdiff-new-file](#latexdiff-new-file)）。`--strip-cmd` は中身だけを残すので、引用符が消えた差分になる。体裁の変更は差分に出ないので報告に 1 行書き、字句が変わっていないことは [`scripts/tex-prose-pass-invariants.py`](../scripts/tex-prose-pass-invariants.py) `--quote-macro NAME` で数える |
| diff のノイズが多すぎる | レビュー markup（色付き注釈コマンド等）まで差分対象になる | diff 前に markup を strip（中身は残し注釈コマンドだけ除去） |
| `Missing \cr` / `\endgroup` / display math 破壊 | 環境を隠した自作マクロ（例: align を包む `\al{}`）が `\DIFadd` に巻かれる | diff 前に当該マクロを本物の `\begin{align}…\end{align}` へ展開 |
| **数式の変更が diff に色で出ない**（error は無い） | 同上: latexdiff は環境名で数式を認識するので、`\al{…}` の中身の変更は「引数付き command の差し替え」扱い = 旧式は `%DIFDELCMD` で comment out、新式は無印挿入 | 同じ展開を **両側**に当ててから diff。道具 = [`scripts/expand-display-math.py`](../scripts/expand-display-math.py)（展開する macro は入力の preamble から**導出**するので新しい wrapper も自動追随、balanced brace + `%` コメント + `\{` escape を扱う、`--selftest` 22 件）。engine が既定で当てる。2026-09-08 に或る paper repo で付録の式の符号反転が無印だった実例。機構 = [`overleaf-integration.md#latexdiff-wrapper-macro-expansion`](overleaf-integration.md#latexdiff-wrapper-macro-expansion) |
| **引数付き自作 macro の中だけの変更が無印**（`\pn{x+y}`→`\pn{x-y}`: 旧式は `%DIFDELCMD` で comment out、新式は `\DIFadd` 無しで挿入。`\frac` や添字は色が付くので気づきにくい） | latexdiff は safe-command list（`\DIFadd{}` の中に入れてよい command）に無い command を含む token を着色しない | preamble の全 macro 名を **原稿から導出**して `--append-safecmd=a,b,c` に渡す（手書き list は新 macro で再発する）。さらに diff 出力を機械で走査し「display math 内で `\DIFaddbegin…\DIFaddend` に `\DIFadd{}` 外の残りがある / `%DIFDELCMD` の payload が実 command」を数えて 0 でなければ再生成を fail させる（= silent miss を silent にしない）。道具 = [`scripts/latexdiff-safecmd.py`](../scripts/latexdiff-safecmd.py)（list は preamble から導出、展開対象は expander に問い合わせる）+ [`scripts/check-latexdiff-math-markup.py`](../scripts/check-latexdiff-math-markup.py)（`--scan` が数え、`--selftest` は preamble の引数付き macro 全部に合成変更を通す）。engine が既定で両方回す |
| **safe-command を足しても command 単位の変更が無印**（`\hat{e}` の削除、`\Big[`・`\Big\{`、`\phantom{…}`、`\dotsb`、`&{}`: coarse の `%DIFDELCMD` payload。2026-09-13 の実測で 21 件、wrapper 展開・safe-command 済みの状態で残った） | coarse は数式を token 単位で差分し、差し替え token が macro でない command だと着色せずに comment out / 挿入することがある | `--math-markup=whole`（変更のあった式を丸ごと旧 = 削除色・新 = 追加色で出す）にする。副作用の `Multiple \label's` は [`scripts/latexdiff-strip-dup-labels.py`](../scripts/latexdiff-strip-dup-labels.py) で削除側の label を落として消す。engine は既定 whole + この除去（[#latexdiff-move-artifacts](#latexdiff-move-artifacts)） |
| `Misplaced alignment tab character &` / `Misplaced \cr`（math-markup coarse / whole で、off では通る） | latexdiff は数式 markup を `\\` と `&` でしか分割しないので、行区切りを包む自作マクロ（例: `\nn` = `\nonumber\\`）が `\DIFadd{…}` 内に閉じ込められる | 同じ前処理で `\nn` → `\nonumber\\` も展開（定義行は除外）。これで `--math-markup=coarse` が通り、`off`（削除式が消える）へ落とさずに済む。row-break macro も上の expander が preamble から導出する（本体に `\\` を含む 0 引数 macro） |
| tikz error の連鎖 | ネストした tikzpicture/feynman 図が壊れる（`PICTUREENV` を足しても入れ子は通らない、 実測） | 図を placeholder へ置換 +（下の）`--config PICTUREENV=…`。 **図を diff PDF に残したいとき**は、 外側の `tikzpicture` を丸ごと中身の hash から作った引数なしの macro 名（例 `\tikzphabcdefgh{}`）に置き換えて両側で diff し、 diff の出力でその macro を元の図の source に戻す。 同じ図は同じ名前になるので、 変わっていない図は無印で残り、 足した図・消した図は図ごと追加・削除として出る |
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

<a id="latexdiff-item-labels"></a>**項目の一覧と照らして読んでもらう diff には、 変更箇所に項目名の印を付ける**: 変更の一覧 (項目番号つき) と照らして diff を読む人のために、 新しい側だけに `\itemtag{A1}` のような印を足して diff する。 印の command は両側の preamble に同じ定義で置き（preamble は差分にならない）、 latexdiff の safe-command list に入れない（list に無い command は `\DIFadd` に包まれず、 印は下線の付かない普通の文字で出る）。 caption の中に置くなら `\DeclareRobustCommand` で定義する。 印は数式環境の中に置けないので、 式の変更は直前の地の文の行に付ける。 印の位置は行番号でなく行の書き出しの文字列で決めると、 原稿が少し動いても付け直せる。 変わった頁だけを渡すときは、 差分の色 (追加・削除) が出ている頁で選ぶ（道具 = [`scripts/latexdiff-changed-pages.py`](../scripts/latexdiff-changed-pages.py)、 説明の頁は `--keep 1`）。 印の頁だけで選ぶと、 頁をまたぐ節・段落の続きの頁と、 印を付けていない小さな変更 (参照の言い換えなど) の頁が落ちる（実測）。 頁を「節の頁」 で決めると、 `figure*` が後ろの頁へ流れて図が抜ける。 印は頁を選ぶためでなく、 一覧と照らして読むための目印。 数式の変更を見せる diff では `--math-markup=off` を使わない（off は新しい式だけを無印で出すので、 式の項目が読めない。 coarse か whole、 上の表）。

**共著 review 中の原稿は「清掃版どうし」で diff する**: 着色 (`\red{...}`) と著者間問答が残っていると、 latexdiff では **着色の差が実質の差を埋める**。
`ai-collaboration/scripts/review-markup-clean.py` を **基準版と現在版の両方に当ててから** latexdiff を回すと、 実質の変更だけが見える
(投稿前清掃と同じ script を使うので「読み合わせで見えていたもの」 と「投稿するもの」 がずれない)。
基準版の選び方 = 信用できない改稿 pass の**直前の commit** (= 著者と共著者の最後の合意点)。 再生成は 1 コマンドの script にして live を変えるたびに回す。
正本 = [`edit-intent-record.md#cleaned-base-diff`](../../ai-collaboration/conventions/edit-intent-record.md#cleaned-base-diff)。

**別解（latexdiff のコンパイル問題を完全回避）**: Overleaf 連携の原稿なら **Overleaf の History 比較**（baseline 版 ↔ 現在）が確実で、pre/post 処理が要らず数式まで色分けされる。

> **標準ケースは engine script で機械化済**: [`scripts/latexdiff-review-snapshot.sh`](../scripts/latexdiff-review-snapshot.sh) が「baseline 取り出し → markup unwrap (`--strip-cmd`/`--strip-color`) → latexdiff → compile cycle → snapshot 命名 ([`expensive-intermediate-artifacts.md#snapshot-artifact-naming`](expensive-intermediate-artifacts.md#snapshot-artifact-naming) 準拠、 head 側は main tex を最後に触った commit に pin) → 同 baseline 旧版の supersede 削除 → commit+push+open」 を 1 コマンドで回す (= 共著レビュー中に相手の push を取り込んで diff を更新する loop 用。 behind / dirty guard 内蔵、 手順詳細 = script docstring が SoT)。 ⚠️ **「既定」の使い分け**: engine の既定 (`--math-markup=1` + `VERBATIMENV=comment` + lualatex) は**comment 環境・tikz 図なしの素直な原稿**で実証した組合せ。 上の症状表に当たる複雑原稿 (tikz / natbib / 自作数式環境マクロ) では**本節の保守的既定** (`--math-markup=off` / `--disable-citation-markup` / `PICTUREENV` 等) を `--latexdiff-args` で注入する — 2 つの既定は矛盾でなく原稿クラス別。 **原稿固有値 (= baseline commit・strip 対象 markup・engine) は各 repo の CLAUDE.md に呼び出し 1 行として置き、 手法の正本 (本節 + engine) を参照する** (= SoT は上層 1 つ、下層から参照)。 **baseline の選び方は投稿の節目で切り替える**: 投稿前は著者が「この版から」 と決めた内部 snapshot、 **投稿 (preprint / 雑誌) の後は投稿版の commit** を baseline にし、 投稿前の diff は記録として残して再生成しない (投稿後の作業で referee と共著者が見たいのは「投稿版から何が変わったか」 であって内部 snapshot からの差ではない、 実測)。 投稿版の commit は投稿の記録 (package を作った commit、 受付メールの eprint 番号) から同定し、 投稿と最初の投稿後の編集の間に commit が無いことを `git log` で確かめてから既定にする。 engine で吸収できない exotic な pre/post 処理 (マクロ展開・図 placeholder 等) が要る原稿のみ、 従来通り repo の `latexdiff/` 配下に固有スクリプトを置く。
>
> <a id="latexdiff-multi-file"></a>**多 file の原稿は、 両版を同じ手順で平らにしてから比べる** — 付録などを `\input` で分けた原稿をそのまま latexdiff に渡すと、 sub-file が両版とも working tree の版になり、 sub-file の差分に色が付かない。 旧版は `git show <rev>:<file>` で sub-file ごと取り出し、 両版とも comment を剥がし、 `\input` を中身で置き換える (道具 = [`scripts/latexdiff-flatten.py`](../scripts/latexdiff-flatten.py)、 path は TeX と同じく main tex の dir から)。 engine は既定でこの段を通し、 snapshot 名の head と dirty の検出も sub-file まで見る。 `\subfile`・`\import` は平らにできないので止まる。 display の自作 macro (`\al{…}` 型) は、 上の症状表どおり環境に展開しておかないと式の変更が無色になる。 式の中の変えた記号だけに印を付けるなら `--math-markup=fine` にし、 下の [#latexdiff-fine-markup](#latexdiff-fine-markup) の順に通す (whole の出力への差し替えは形を書き換えた式だけ。 式全体を whole にすると、 添字 1 つの変更でも式ごと削除線と下線になる)。 engine に無い段 (括弧の macro の置き換え、 形を書き換えた式の差し替え) が要る原稿は手順を repo の script にし、 平らにする段は同じ道具を呼ぶ。 生成した diff の `.tex` は原稿の形をしているので commit しない (原稿の保護の gate に原稿と読まれる)。 渡すのは PDF だけ (実測)。
>
> ⚠️ markup unwrap が必要な理由: `\DIFadd{\cl{長文}}` のように **group を丸ごと下線 markup に包むと ulem が改行不能 box 化してページ外に溢れる** (= 描画はされるが 1 行で切れる)。 review 注釈系コマンドは diff 前に unwrap するのが根治 (= diff 内で draft 色は冗長でもある)。 両版に同一適用すれば未変更 markup が spurious diff にならない。
>
> <a id="one-markup-stripper"></a>⚠️ **markup を外す実装は `ai-collaboration/scripts/review-markup-clean.py` の 1 本** — engine の `--strip-cmd` / `--strip-color` もそれを呼ぶ (`--macro` / `--color`)。 原稿ごとに外す script を書き足さない。 素朴な brace の数え方は次の形で誤る (実測 = engine に埋め込んでいた以前の実装が全部に当たった): ① 直前の 1 文字だけでエスケープを判定すると、 改行の `\\` の直後の `}` を `\}` と読み、 後ろの `}` まで食う ② `%` コメントを飛ばさないと、 引数の中のコメントの `}` で閉じ、 コメント行の閉じない `\cl{` から数えて地の文の `}` を消す (群が閉じなくなる) ③ wrapper の `{` と `}` が単独の行にあると、 外した後に空行が 2 つでき段落が割れる ④ 閉じていない wrapper を黙って通す。 外し方の約束: `{\color{名前}…}` は群ごと開く (中の `\bfseries` などの宣言は後ろへ効きうる)、 群の外の `\color{名前}` は外さない (engine は残ったら警告)、 `%` コメントの中は触らない。 外す道具を入れ替えたときは、 同じ入力で前後の diff PDF を組んで頁画像を比べる ([`compare-tex-builds.py --pixels`](../../ai-collaboration/scripts/compare-tex-builds.py))。
>
> <a id="math-guard-is-a-pair"></a>⚠️ **上の症状表 3 行 (wrapper 展開 / safe-command / 無印検査) は engine の既定に入っている** (2026-09-12)。 それ以前は**表に対策が書いてあるだけで engine は適用しておらず**、 engine を呼ぶ repo は「compile 0 error・式の変更だけ無色」 の PDF を共著者に渡し得た (= 規約に書いた対策が道具に入っていない型の drift。 合成 repo の実測: 旧挙動は新式を `\DIFadd` 無しで挿入し旧式を comment out、 既定では両式が着色される)。 **展開と検査は対でしか効かない** — 展開前の本文には display-math 環境が無いので、 検査だけ回すと同じ silent miss に対して 0 を返す (= 検査の 0 は「安全」 ではなく「展開していない」 でもあり得る)。 無印が残ったときは deploy 前に停止する: preamble に新しい構造 macro があるなら `LATEXDIFF_BENIGN_EXTRA=名前,名前` で宣言し、 意図して無視するなら `--allow-unmarked-math`、 guard 自体を切るなら `--no-math-guard` (= 旧挙動)。

## <a id="latexdiff-fine-markup"></a>式の中の変わった記号だけに印を付ける差分 (`--math-markup=fine`) の壊れ方と直し方

共著者が「式もちゃんと変更箇所だけ」 と求めるとき (添字 1 つ・関係記号 1 つの変更で式全体に削除線が付くのを避けたいとき) は `--math-markup=fine` を使う (latexdiff の番号では fine = 3、 2 は coarse)。 実際の原稿では fine の出力が決まった形で壊れる (実測):

| 症状 | 原因 | 直し方 |
|---|---|---|
| `Missing { inserted` が式 1 本から連鎖 | 引数を取る accent (`\widehat` など) が印の前に置き去りになる: `\widehat \DIFadd{L^i}` | accent を印の中へ: `\DIFadd{\widehat L^i}`。 原稿の自作 accent も同じ扱いにする |
| `Argument of \frac has an extra }` / `Paragraph ended before \frac` | `\frac` を含む `\DIFadd{…}` が 1 つ目の引数で閉じ、 2 つ目の引数が印の外に出る | 2 つ目の引数を同じ `\DIFadd` の中へ戻す |
| エラーは無いが、 消した側の式が欠けて読める (分数の横線・ハット・`≳` が消える)。 無印検査が削除側の command を数える | 印で包めない command (`\over`・accent・関係記号) を削除側で `%DIFDELCMD` に comment out する | その command を隣の `\DIFdel{…}` の中へ戻す |
| 括弧の自作 macro (`\fn{…}` `\pn{…}` `\sqbr{…}` `\ab{…}`) の中の 1 文字の変更で、 引数全体が旧 (削除線) と新 (下線) の横並びになり、 長い指数が頁の右からはみ出す | latexdiff は数式の中で macro を引数ごと 1 token と見る (safe-command に入れても中へは降りない) | 両側で macro を素の括弧に置き換えてから比べる (`\over` を含む中身は群 `{…}` を残す)。 diff の PDF では括弧の大きさが伸びないが、 差分を読む用途には足りる |
| 分数を消した側が無印として数えられ、 消えた分数が読めない (`{1\ov4}` を消した・`{A\ov4}` を `A` にした) | `\over` の別名 (`\ov`) だと直す道具が分数を見つけられない。 閉じ括弧の行が `%%%` で終わる形もある | 両側で別名を `\over` に置き換えてから比べる。 `%%%` の形と、 残した token の両側の括弧だけが comment out される形は `fix` が直す (over-pct / over-tail) |
| 行ベクトルを列ベクトルに書き換えた式で、 古い形が見えず、 新しい形に削除線の付いたコンマだけが残る。 `\left(` `\right)` が無印 | 形の書き換えは token の差分では読めない。 `\left` / `\right` は印の外に出る | その式だけ `--math-markup=whole` の出力 (旧 = 削除線 + 新 = 下線) に差し替える。 括弧だけなら両側を素の `(` `)` にしてから比べる |
| 文中の数式 (`$…$`) は、 記号 1 つの変更でも式ごと削除線と下線になり、 長い式は旧と新が横に並んで右の余白からはみ出す (display の式は記号だけに印が付くのに) | latexdiff は文中の数式を 1 語として切る。 `--math-markup` が効くのは数式環境の中だけ | 両側で文中の数式を数式環境で包んでから比べ、 後で `$…$` に戻す (下の `latexdiff-inline-math.py`) |
| 分数の分子の記号 1 つの変更で、 分数が丸ごと旧と新の 2 つ並ぶ (文中でも display でも) | `\frac{…}{…}` は引数ごと 1 token | 両側で `\frac{A}{B}` を `{A\over B}` に置き換えてから比べる (組版は同じ。 同じ道具の `wrap` がする) |
| 旧版にだけある display (消した式) が、 隣の新しい display と 1 つの式に混ざり、 `Undefined control sequence` `\MBLOCKRIGHTBRACE` で止まる。 `\left\{` `\right\}` が無印に数えられる | latexdiff が消した式を新しい式の対にし、 消した側の `\right\}` を `\MBLOCKRIGHTBRACE` (定義の無い名前) に置き換えたまま `\DIFdel{…}` に残す。 `\left` / `\right` は印の外に出る | 両側で `\left\{…\right\}` を素の `\{…\}` にしてから比べる (`\max\left\{a,b\right\}` → `\max\{a,b\}`)。 それでも 2 式が混ざる (消した式の token が新しい式の中に `\DIFdel` で残る) なら、 その式を whole の出力から取った「消した式を丸ごと削除 + 新しい式を丸ごと追加」 に置き換える。 ⚠️ `splice` は、 whole の出力で消した式の削除が新しい式の直前にあり、 新しい式がその追加の塊の最後にある形しか扱わない (新しい式の後に文が続く・削除が離れている形は `ValueError`) = この形は自前で置き換える (実測) |

- 道具 = [`../scripts/latexdiff-fine-fixups.py`](../scripts/latexdiff-fine-fixups.py): `fix diff.tex [--accents 自作名]` が上 3 行を直し、 `splice diff.tex whole.tex --labels eq:a,eq:b` が 4 行目の差し替えをする (`whole.tex` = 同じ入力を `--math-markup=whole` で比べ、 [`latexdiff-strip-dup-labels.py`](../scripts/latexdiff-strip-dup-labels.py) を当てたもの)。 engine ([`latexdiff-review-snapshot.sh`](../scripts/latexdiff-review-snapshot.sh)) は `--math-markup 2` のとき `fix` を自動で通す。
- 文中の数式と分数 = [`../scripts/latexdiff-inline-math.py`](../scripts/latexdiff-inline-math.py): latexdiff の前に両側を `wrap` (文中の数式を環境 `difinlinemath` で包み、 `\frac` を `\over` に)、 latexdiff に `--add-to-config="MATHENV=difinlinemath"` を渡し、 検査の後に `unwrap` (`$…$` に戻す。 丸ごと消した文中の式は latexdiff が display に組み直すので、 文中に戻す)。 ⚠️ 包むときは `\begin{difinlinemath}` の直後に空白を置く — 空白が無いと、 `{` で始まる式の `{…}` を latexdiff が環境の引数と読み、 旧と新の対応が崩れる (実測)。 engine は `--math-markup 3` のとき自動で通す。
- 順番 = (`wrap`) → latexdiff → `latexdiff-strip-dup-labels.py` → `fix` → (`splice`) → [`check-latexdiff-math-markup.py --scan`](../scripts/check-latexdiff-math-markup.py) (`difinlinemath` も数式として見る) → (`unwrap`) → 組版。 `fix` の前に検査すると、 削除側の comment out を無印として数える。
- 項目の印 (`\itemtag{…}` のような自作の macro) を new 側にだけ足して差分に番号を付けるときは、 その macro も `--append-safecmd` に足す。 足さないと、 display の中や直前に入った印が `\DIFadd` の外に出て、 無印検査が式の変更として数える (実測)。
- 組版エラー 0・無印 0 でも、 変えた式の頁を 1 枚画像で見る (消した側の式が正しく読めるか、 形の書き換えが式ごと表示になっているか)。
- 上の表を当てても直らない原稿 (組版が止まる式が残る、 whole に差し替える式が増えて記号単位にならない) は、 式を latexdiff に渡さない = 次の [#latexdiff-eqtree](#latexdiff-eqtree)。

## <a id="latexdiff-eqtree"></a>式を latexdiff に渡さず、 構文木で比べる (`latexdiff-eqtree.py`)

fine は token の平らな列を比べるので、 `_{a` のような波括弧の途中まで一致させ、 消した側に閉じ括弧だけが残る (`\MBLOCKRIGHTBRACE` で組版が止まる)。 消した式を隣の新しい式と 1 つに混ぜることもある。 fix は出てきた形を後から直す手当なので、 形が増えるたびに道具を足すことになる (実測)。

- 道具 = [`../scripts/latexdiff-eqtree.py`](../scripts/latexdiff-eqtree.py): 新旧の display を対応づけ、 組ごとに同じ placeholder に置き換えて latexdiff には地の文だけを比べさせる。 式は構文木 (群・分数・括弧・macro の引数・添字) を単位に比べて placeholder に戻すので、 印は必ず釣り合った単位に付く。 文中の式 (latexdiff が旧と新を丸ごと並べたもの) と図の中の式も同じ比べ方で印が付く。
- 順番 = 上の [#latexdiff-multi-file](#latexdiff-multi-file) の平らにする段と display の macro の展開 → `protect` → latexdiff → `restore` → 組版 → `overflow` (旧の記号も並べたために列を超えた式の番号) → 番号が出たら平らな file からもう一度、 番号を渡して `protect` → 組版 → [#latexdiff-views-check](#latexdiff-views-check)。 手順の script の雛形は道具の冒頭の usage。
- 見え方の約束 = 式番号は新しい側。 括弧の大きさ・字間・行の切れ目は変更として印を付けない。 旧にしかない式は番号なしで、 それを引く消した文には旧の番号を出す (基準の版の `.aux` を渡す)。 共通の部分が少ない組は式ごと表示 (旧に取り消し線、 新に下線)。 移動した式は旧の場所に取り消し線、 新の場所に下線。
- ⚠️ 無印の検査 ([`check-latexdiff-math-markup.py --scan`](../scripts/check-latexdiff-math-markup.py)) は、 この経路では式について常に 0 になる (式に latexdiff の印が無い) = 式の合格の根拠にしない。 式の検査は道具の読み戻し (追加を除くと旧、 削除を除くと新、 合わなければ止まる) と次節。
- ⚠️ placeholder を自作するなら普通の語を 3 つ並べる。 latexdiff は共通の部分が `MINWORDSBLOCK` (既定 3) 語に満たないと前後の変更に畳むので、 1 語の placeholder は「消して足した」 形になり、 同じ式が 2 回出る (実測)。
- ⚠️ 比較の記憶を `id()` で引かない。 一時の node の id は使い回されるので、 組むたびに結果が変わる (実測)。 生成の道具は同じ入力で 2 回回し、 頁の文字が一致することを確かめる (`latexdiff-views-check.py --same a.pdf b.pdf`)。
- engine ([`latexdiff-review-snapshot.sh`](../scripts/latexdiff-review-snapshot.sh)) には組み込んでいない = repo の手順の script から呼ぶ。

## <a id="latexdiff-views-check"></a>差分 PDF を元の 2 版に読み戻して確かめる (`latexdiff-views-check.py`)

印の検査は印の形しか見ない。 [`../scripts/latexdiff-views-check.py`](../scripts/latexdiff-views-check.py) は `diff.tex` の `\DIFadd` と `\DIFdel` を定義し直して 2 つの文書を組み、 追加だけを残した版を新の版と、 削除だけを残した版を旧の版と、 抽出した文字で比べる (語でなく文字なので、 改行・ハイフン・図の順に左右されない)。 印の作り方に依らないので、 自作の道具にも素の latexdiff にも当てられる。

- 新の側は一致が合格 (数字・括弧・ハイフンを除く)。 合わなければ exit 1。
- 旧の側は読むだけ。 新にしかない display は番号の空行として残り、 新にしかない節と図は label と図そのものが残り、 latexdiff が語の間の空白を追加の側に入れた所は語がつながる (実測)。 出た語がこの 3 つで説明できることを見る。

## <a id="latexdiff-deleted-blank-lines"></a>latexdiff は削除された空行を comment out できない — diff PDF と live で段落の切れ方が違ったら削除空行の残留を疑う (2026-09-08)

**症状**: diff PDF ではある文から新段落が始まるのに、 live の原稿では前の段落に繋がっている (またはその逆)。

**原因**: latexdiff は削除行を `%DIFDELCMD <` で comment out するが、 空行 (= `\par`) は comment out すると意味が変わるのでそのまま残す。 旧版にあって新版で消えた空行は diff source に生き残り、 diff PDF には旧版の段落切れが出る。

**事故検出器として使う**: 「diff の方が段落が切れている」 は、 改稿 pass で空行が事故で落ちた (= 段落併合が決定でなく実装事故) 印になりうる。 2026-09-08 の研究 LaTeX project では序論と §4.4 の 2 箇所がこれで見つかった (どちらも記録に併合の決定が無い)。 sweep = diff source で「削除ブロック内でない削除空行」 を数え、 各々を live と突き合わせる (削除ブロック内の空行と、 新版でも段落切れがある箇所は無害)。 逆方向 (新版で増えた段落切れ) は事故の型ではない。

## <a id="latexdiff-move-artifacts"></a>block の MOVE は latexdiff に「削除 + 挿入」 と見える — label 重複の良性 error と無印 token (2026-09-08)

**症状**: 付録や節を verbatim で移動した diff を組版すると、 amsmath の `Multiple \label's` error が移動 block の式の数だけ出る (PDF は出る、 当該 label への cref だけ不定)。 加えて math-markup の gate が移動 block 内の数式 token を「無印」 と数える。

**原因**: 移動元 (DIFdel 側) と移動先 (挿入側) の両方に同じ `\label{}` が残る。 `--math-markup=off` なら error 0 だが削除側の式そのものが消える。

**扱い**: 恒久手当 = 実装済 (2026-09-13) — [`scripts/latexdiff-strip-dup-labels.py`](../scripts/latexdiff-strip-dup-labels.py) が `\DIFdelbegin … \DIFdelend` の中の `\label` を落とす (engine [`latexdiff-review-snapshot.sh`](../scripts/latexdiff-review-snapshot.sh) は latexdiff の直後に自動適用、 project の regen script は同 script を呼ぶ)。 error は 0 になり、 旧版だけにあった label への参照だけが undefined で残る (diff としては正しい)。 同じ重複は **`--math-markup=whole` では変更のあった式すべて**で起きる (旧式と新式が丸ごと 2 回出る) ので、 whole を使うなら必須。 それ以前の扱い = coarse のまま error と無印 token の件数を「MOVE 由来」 として ledger に記録していた。

## <a id="float-drift-after-insert"></a>display を 1 本足したら `[t]` の表が次頁 = References に流れた — float の source 位置を前へ (2026-09-08)

**症状**: 付録末尾の `\begin{table}[t]` が、 本文が数行伸びただけで次頁の上 = References の中に置かれる。

**原因**: `[t]` float は source 位置以降の最初の「上」 に置かれる。 付録の最終頁で source が頁の下半分にあると、 次頁 (References) の上に行く。

**対処**: float の source を、 参照する段落より前 (頁の前半に来る位置) へ移す。 参照文 (`\cref{tab:…} collects …`) は末尾のままでよい。 `[h]` / `[H]` より安定で、 組版後に「Table 1 の頁 < References の頁」 を PDF text で機械確認する。

## <a id="figures-in-body-references-last"></a>本文の図を本文の中に置き、 文献表を付録の後ろに置く — `placeins` の section option と `[tbp]`

**症状**: 本文の `[t]` の図が、 付録と文献表の後ろの最後の数頁にまとめて出る (実測: 本文の図 5 枚のうち 3 枚)。

**原因**: `[t]` の float は頁の上端にしか置けない。 本文の終わりの方で図が続くと置き場が足りず、 置ける頁まで後ろへ送られ、 付録の見出しも文献表も越える。 [#float-drift-after-insert](#float-drift-after-insert) の 1 枚の流れと同じ仕組みの、 本文全体の版。

**対処**:

- `\usepackage[section]{placeins}` を読む。 各 `\section` の手前で溜まった float を出し切るので、 図はその節の中か直後に出て、 付録と文献表へ越えない。 `\FloatBarrier` を手で置く形は、 節を足したときに置き忘れる。
- 図の位置の指定を `[t]` から `[tbp]` に広げる (`[!t]` は `[!tbp]`)。 出し切るときの置き場 (頁の下端・float だけの頁) が増え、 半端な余白の頁が減る。
- 確かめ = 組んだ後に [`scripts/latex-float-placement.py`](../scripts/latex-float-placement.py) `paper.tex` (`.aux` の float ごとの頁と付録の始まりの頁を比べ、 本文の float が付録の頁にあれば exit 1)。 PDF の本文から「Fig. N」 を探す形は、 class ごとに caption の書式が違い、 本文の行頭の参照も拾う。

**文献表の位置**: 物理 (特に素粒子) の原稿では 本文 → 謝辞 → 付録 → 文献表 の順が多く、 雛形によっては文献表が付録の前にある。 どちらに置くかは著者の家風と投稿先の指定で決める。 付録の後ろへ移すときは `\bibliographystyle{…}` と `\bibliography{…}` の 2 行を `\end{document}` の直前へ動かす (付録の中の `\cite` も同じ文献表に入る)。 上の道具は source の位置 (付録の前 / 後ろ) も出す。

## <a id="align-split-tag-orphan"></a>長い display の式番号が下の行に回るのは amsmath の標準 — 欠陥として報告しない (2026-09-12、 著者裁定)

**何が起きるか**: 式が本文幅に収まらないと、 amsmath は式番号 (tag) を式の**下の行**に置く。 `align` を `\nn` で 2 行に割った場合も、 第 1 行に `&` が無く第 2 行が右端まで届けば同じになる。 overfull ではないので log には何も出ない。

**判断**: これは amsmath の設計どおりの配置で、 組版の欠陥ではない。 著者裁定 (2026-09-12): 「番号が下に行くのは完全にカノニカル」。

- 査読・盲検 review でこれを **should-fix にしない**。 報告するなら位置の事実だけにする (overfull と同じ扱い = [`edit-intent-record.md#overfull-not-a-gate`](../../ai-collaboration/conventions/edit-intent-record.md#overfull-not-a-gate)、 検査 spec の書き方 = [`cold-eyes-isolation.md#spec-leakage`](../../ai-collaboration/conventions/cold-eyes-isolation.md#spec-leakage) の表)。
- 改稿 pass で、 番号を最終行に戻すために式の割り方や語順を**変えない**。
- 触るのは投稿先の style が明示的に禁じている場合だけで、 そのときの正本は投稿先の指示。 手段は第 1 行にも `&` を置いて欄を揃える、 または 1 本の長い式なら `multline`。

**起源**: 2026-09-12 の盲検 review がこの配置を「式番号が 3 行目に単独で落ちる」 と should-fix で報告し、 本節も一度その前提で書かれた。 著者が据え置き、 同じ日のうちに「欠陥ではない」 へ訂正した (= reviewer 側の誤判定の記録、 見慣れない配置は欠陥の証拠ではない)。

## <a id="qed-alone-after-display"></a>証明が数式で終わると ■ だけが次の頁に回る — `\qedhere` は番号つきの式の番号を消す

**何が起きるか**: amsthm の `proof` が別行立ての数式で終わると、 ■ は数式の次の行に 1 つで置かれる。 数式の直後は頁を割ってよい所 (`\postdisplaypenalty` = 0) なので、 そこで頁が割れると ■ だけが次の頁の頭に出る。

- **`\qedhere` は番号つきの amsmath の式では使えない**: ■ を数式の最後の行の右端に置く代わりに、 その行の式番号を消す (実測。 番号を参照していれば参照が壊れ、 後の番号も 1 つずれる)。 番号の無い式 (`align*` など) なら使える。
- **■ の行と数式を離さない手**: 証明の最後の数式だけ `\postdisplaypenalty` を 10000 にする (LaTeX の既定で `\predisplaypenalty` も 10000 なので、 頁が足りなければ数式の 1 行前から次の頁へ移る)。 「最後の数式か」 は、 数式を組む macro (`\al{…}` 型) の後ろを覗き、 空白と空行を飛ばして `\end{proof}` が来るかで決める (`\futurelet` で見て、 `\end` なら引数を取って名前を比べ、 違えば `\end{…}` を元に戻す)。 penalty は数式の環境の外 (`\begin` の前) で設定する (環境の中の cell で設定しても group を出ると消える)。
- **確かめ方**: ■ を文字列 (`\renewcommand{\qedsymbol}{QEDMARK}` など) にした試しの文書で、 前に文を足して長さを変えながら組み、 前の定義で ■ が数式と別の頁になる長さを見つけ、 同じ長さを新しい定義で組む。 本全体は前と後の定義で組み比べて頁の画素が同じか ([`compare-tex-builds.py --pixels`](../../ai-collaboration/scripts/compare-tex-builds.py)、 割れていない所は変わらない)。

## <a id="dots-before-closing-delimiter"></a>amsmath は `\cdots`・`\dots` の直後が閉じ括弧か `$` のとき右に `\,` を足す — 括弧の中に点だけだと左右が揃わない

**何が起きるか**: amsmath の `\cdots` (と `\dotso`・`\dotsc`) は、 直後の字を覗いて、 閉じ括弧 (`)` `]` `\}` `\right` `\bigr` …)・数式の終わり `$`・`,` `;` `.` のとき点の右に `\,` を足す (`\extrap@` / `\extra@`)。 `(x_1, \dots)` のように点の左にカンマの後の空きがある並びではこれで左右が揃うが、 `\left(\cdots\right)` や `$\dots$` だけの数式のように点の左が開き括弧か数式の頭だと、 右だけが細い空き 1 つ分広い (実測 = 括弧と点のインクの間が左 1.45pt・右 3.1pt、 10pt)。 log にも警告にも出ない。

- **直し方 (LuaTeX)**: `\extra@` を包み、 amsmath が `\,` を足すと決めたときだけ、 今の数式の最後の要素を Lua で見る (`tex.nest[tex.nest.ptr].tail` が空 = 数式の頭、 開きの noad、 または `\left` の fence)。 点の左がそれで、 右が閉じ括弧か `$` なら `\,` を足さない。 それ以外 (`(1,\dots)`・`(1+\cdots)`) は amsmath のまま。 pdfTeX / XeTeX では今の数式の最後の要素を見られないので、 原稿の側で `\pn{\cdots}` のような書き方を 1 つの macro にして、 そこで点の右の空きを打ち消す。
- **確かめ方**: `\pn{\cdots}` / `(\cdots)` / `(\dots)` / `(1,\dots)` / `(1+\cdots)` を 1 行ずつ組み、 高解像度の画像で隣り合うインクの塊の間を測る。 本全体は前と後で組み比べる (変わるのは点だけの括弧と、 点だけの行内数式の右の空き)。

## <a id="named-refs-without-cleveref"></a>参照に種類の名前 (定理・図・付録) を自動で付ける — cleveref を使わない形と、 `\autoref` が和文で詰まる罠

**何がしたいか**: 「性質~\ref{…}」 の「性質」 を手で打たず、 ラベルの種類から名前を出す。 cleveref を使わない原稿でも組める形。

- **定理の仲間が番号を共有していると種類が区別できない**: amsthm の `\newtheorem{property}[theorem]{性質}` は counter `theorem` を進めるので、 hyperref の anchor は `theorem.1.7` になり、 `\autoref` は全部「定理」 と出す。 aliascnt で種類ごとの counter 名を付ける: `\newaliascnt{property}{theorem}\newtheorem{property}[property]{性質}\aliascntresetthe{property}` (番号の列は同じ)。 名前は `\def\propertyautorefname{性質}` のように種類ごとに、 図・表・付録は class の名前を使う (`\def\figureautorefname{\figurename}` など)
- **`\autoref` は番号の後ろに空の箱 (`\null`) を置く**: LuaTeX-ja は英数字と和文の間に空き (xkanjiskip) を入れるが、 空の箱が挟まると入らないので「付録Aに」 と詰まる (実測。 手で書いた「付録~\ref{…}に」 は「付録 A に」)。 和文の原稿では、 anchor の種類から名前を引いて「名前~\ref{ラベル}」 と組む命令を作る (`\r@ラベル` の 4 つめの欄が anchor。 preamble の `\makeatletter` から `\makeatother` の間に置く):

```latex
\def\rf@name#1.#2\@nil{\@ifundefined{#1autorefname}{}{\csname #1autorefname\endcsname~}}
\newcommand{\rf}[1]{\@ifundefined{r@#1}{}{%
  \edef\rf@anchor{\expandafter\expandafter\expandafter\@fourthoffive\csname r@#1\endcsname}%
  \expandafter\rf@name\rf@anchor.\@nil}\ref{#1}}
```

  手で書いたのと同じ組みになる (リンクも番号だけ)。 ラベルが未定義の回は名前を出さず `\ref` の ?? だけ
- 式は `\eqref` のまま (`\autoref` の式は括弧が付かない)。 章・節は「第 1 章」「1.2 節」 の形にならないので、 名前を前に付ける命令では引かない
- **既存の原稿を置き換えるとき**: 書いてある名前と、 そのラベルの種類から出る名前が一致した所だけを置き換える。 種類は `.aux` の anchor から読む (`\include` した章のラベルは章ごとの `.aux` にあり、 main.aux には無い = 実測)。 置き換えの前と後を同じ原稿の写しで組み比べ、 頁の画素と字が同じなら組みは変わっていない

## <a id="tcolorbox-footnotes-to-page"></a>tcolorbox の枠の中の脚注を、 本文と同じ番号で頁の下に出す

**何が起きるか**: tcolorbox の中身は minipage で組まれるので、 中の `\footnote` は枠の下に a, b… の別系統の番号で出る。

- footnotehyper (hyperref と組める footnote package) の `\savenotes` / `\spewnotes` で、 脚注を枠の外へ預けて頁の下に出す。 `\newtcolorbox` で作った環境は `\makesavenoteenv{環境名}` で包む
- 枠の中でも本文の脚注の番号を使う: 枠の中身の最初で、 minipage の脚注の counter 名 `\@mpfn` を `footnote` に、 印の書式 `\thempfn` を `\thefootnote` に戻す。 tcolorbox の key で全部の枠に掛ける (`\makeatletter` の中で)。 これが無いと、 頁の下に出ても印は a のまま (実測):

```latex
\tcbset{every box/.append style={before upper app={%
  \renewcommand\@mpfn{footnote}%
  \renewcommand\thempfn{\thefootnote}}}}
```
- **`\tcolorboxenvironment` で囲んだ環境 (定理の仲間など) は `\makesavenoteenv` が効かない**: tcolorbox は env の hook にラベル `tcolorbox` で枠を開く処理を登録する。 ラベルの無い preamble の処理は同じ hook の中で後に回るので、 `\savenotes` が枠の内側で走る (実測)。 預ける処理にラベルを付け、 順序の規則で枠の外側に置く:

```latex
\ExplSyntaxOn
\clist_map_inline:nn { definition, theorem, lemma }   % 枠で囲んだ環境
  {
    \AddToHook{env/#1/before}[boxnotes]{\savenotes}
    \AddToHook{env/#1/after}[boxnotes]{\spewnotes}
    \DeclareHookRule{env/#1/before}{boxnotes}{before}{tcolorbox}
    \DeclareHookRule{env/#1/after}{boxnotes}{after}{tcolorbox}
  }
\ExplSyntaxOff
```

- **確かめ方**: 本文の脚注・`\newtcolorbox` の枠の中の脚注・定理の枠の中の脚注を並べた試しの文書で、 印が続き番号になり、 本文が頁の下に並ぶこと。 本全体は前と後を組み比べ、 変わるのは枠の中に脚注がある頁と、 その後ろの脚注の番号だけ

## <a id="lua-ul-highlight-emph"></a>`\emph` を色の帯 (蛍光ペン) にする — lua-ul の罠と文献表

- lua-ul (LuaLaTeX の下線・帯。 行をまたいでも続く) の `\highLight[色]{…}` で帯を引く。 **色を付けるには luacolor を lua-ul より前に読む** (無いと「Color support in lua-ul requires luacolor」 で止まる)
- **`\newunderlinetype\名前{…}` が作るのは切り替え**で、 その後ずっと線が引かれる。 引数を取る命令にするには群で包む: `\newcommand\myul[1]{{\名前 #1}}` (実測 = 包まずに使うと文書の終わりまで線が続いた)。 色つきの線は `{\leaders\hbox{\color{色}\vrule width .5pt height -.28ex depth .4ex}}`
- **luacolor は色を attribute で持つので、 色の境目でも字詰め (kerning) が効く**: 頭の 1 字だけ色の付いた語で、 字が 0.1pt ほど動く (実測)。 入れる前と後を組み比べる (改行・改頁は変わらなかった)
- **`\emph` を置き換えるなら、 文献表の中では元に戻す**: bst (JHEP.bst など) は題を `\emph` で組む。 `\NewCommandCopy{\origemph}{\emph}` → `\RenewDocumentCommand{\emph}{m}{\highLight[色]{#1}}` → `\AddToHook{env/thebibliography/begin}{\let\emph\origemph}`
- 和文の強調の案を並べるときの見どころ: 新しい用語の太字と区別がつくか、 白黒で刷っても残るか、 中に数式があっても組めるか (圏点 `\kenten` は数式に点を打てない)。 組んだ姿を並べて決める = [#variant-comparison-images](#variant-comparison-images)

## <a id="figure-table-shared-counter"></a>図と表を 1 本の通し番号にする (jsclasses・ltjsbook)

- `\let\c@table\c@figure` (`\makeatletter` の中で) で表が図の counter を使う。 番号の見た目は `\thefigure` と `\thetable` を同じ形に定義する
- hyperref の anchor は `figure.…` と `table.…` に分かれたままなので、 種類の名前を付ける参照 ([#named-refs-without-cleveref](#named-refs-without-cleveref)) では「図」「表」 が種類どおりに出る (実測)

## <a id="luatexja-per-command-kanji-weight"></a>1 つの命令だけ和文の字の太さを替える (luatexja) — 和文の字体を 1 つ足し、 縦組みの宣言も添える

- ltjsclasses の `\bfseries` の和文はゴシックの既定の太さで、 命令ごとに太さを選ぶ指定は無い。 用語の強調など特定の命令だけ細めの太字にしたいときは、 和文の字体を 1 つ足し、 その命令の中でだけ選ぶ:
  ```latex
  \DeclareKanjiFamily{JY3}{termweight}{}
  \DeclareFontShape{JY3}{termweight}{m}{n}{<-> s * [\Cjascale] file:HaranoAjiGothic-Regular.otf:-kern;jfm=min}{}
  \DeclareKanjiFamily{JT3}{termweight}{}% 縦組み (使わなくても宣言する)
  \DeclareFontShape{JT3}{termweight}{m}{n}{<->ssub*gt/m/n}{}
  \newcommand{\term}[1]{{\bfseries\kanjifamily{termweight}\kanjiseries{m}\selectfont #1}}
  ```
- 寸法と JFM はクラスの和文に合わせる (`\Cjascale`・`jfm=min`)。 合わせないと字の大きさと詰めが本文と変わる。 太さは字の file 名だけで替わる (TeX Live の haranoaji / haranoaji-extra に明朝・ゴシックの太さ違いがある)。 欧文の字は `\bfseries` のまま。
- ⚠️ 横組み (JY3) だけ宣言すると、 縦組み (JT3) の font shape が無いという警告が出る (実測)。 縦組みを使わない文書でも、 上のように JT3 を `ssub` で既定の字体に置き換えて添える。
- 替えたら同じ原稿で前と後を組み比べる。 変わる頁がその命令のある頁とちょうど一致し、 字と頁割りが動かないことを確かめる ([#variant-comparison-images](#variant-comparison-images))。

## <a id="symbol-width-repagination"></a>記号幅の変わる一括置換は、 総頁数が同じまま頁割りだけ動かす — `.aux` の label→頁 で見る (2026-09-12)

**症状**: 記法の一括置換 (下付き添字を縦棒つきの label に替える等) で本文の文字列長が変わると、 総頁数は不変でも**付録の開始頁・表・図の頁**が動く。 目次の頁番号も変わる。

**なぜ頁数比較では足りない**: 組版 gate の「頁数・未定義参照・error」 ([`edit-intent-record.md#build-gate`](../../ai-collaboration/conventions/edit-intent-record.md#build-gate)) のうち頁数は**総和**なので、 前半が 1 頁縮んで後半が 1 頁伸びると相殺して気付かない。

**対処**: `.aux` の `\newlabel` から label→(番号, 頁) を取り、 版間で比べる。 頁が動いた label と**番号が動いた** label (= 参照の意味が変わる) を分けて出す。 道具 = [`ai-collaboration/scripts/compare-tex-builds.py`](../../ai-collaboration/scripts/compare-tex-builds.py) (`--before-aux/--after-aux`)。 同 script の `--before-log/--after-log` は log の**折返しを復元**してから overfull を数える (79 桁で折れた警告は素の grep が落とす)。 規律 = [`physics-verification-cycle.md#page-count-is-not-pagination`](../../ai-collaboration/conventions/physics-verification-cycle.md#page-count-is-not-pagination)。

## <a id="variant-comparison-images"></a>記法・体裁の案は、 組版した姿を左右に並べて決める (source の diff では決められない) (2026-09-12)

**規則**: 記法・語順・体裁に複数案があり著者が選ぶとき、 **案ごとに別に組んで、 決定点の左右比較画像を出してから聞く**。
source の断片や置換規則を提示して「どちらにしますか」 と聞かない。 幅・添字の高さ・式番号の位置・隣の記号との衝突は、
組版して初めて見える (著者 2026-09-12「ソースだけじゃ分からん。 実際に見ないと。 一瞬ブランチ切る？」)。

**手順**: (1) 変換を規則ベースの script にして案を切り替えられるようにする (= 手で打ち直さない。 案が 3 つに増えても再実行だけ)。
(2) 案ごとに live を汚さず組む (ローカル branch か scratch の .tex)。 (3) 決定点の語句を anchor に左右 zoom を作り、 画像で渡す。
(4) 採否が決まってから live に当てる。 **案の生成・組版・比較は使い捨てでよいが、 採用した変換規則は sidecar と決定 ledger に残す**。

**道具**: [`claude-config/scripts/pdf-side-by-side.py`](../scripts/pdf-side-by-side.py) — 2 つの PDF の同じ語句の周りを
左右に並べた比較頁 (`compare.pdf` + `cmp-NN.png`) を作る。 anchor は両版で変わらない語句を選ぶ (案で語句自体が変わる箇所は
その直前の文を anchor に)。 `--diff-pages` で本文が違う頁を頁ごと並べる。
組版が壊れていないかの機械比較 (error / 未定義参照 / overfull / label→頁 の drift) は別の道具 =
[`ai-collaboration/scripts/compare-tex-builds.py`](../../ai-collaboration/scripts/compare-tex-builds.py)。
一括置換の純粋性は [`check-rename-purity.py`](../../ai-collaboration/scripts/check-rename-purity.py)。

**実例 (2026-09-12)**: ある量の記法で 4 案 (縦棒 + hat 有無 / 下付き / 肩・次数なし / 肩・次数つき) を同じ変換 script の
mode 切替で作り、 各案を組んで数箇所ずつの左右比較を渡した。 決め手は紙の上にしか無かった = 下付きは同じ論文の
別の量の添字と label の位置が割れる、 次数なしの肩は別の次数の量に見える、 縦棒は制限の用法と衝突する
([`paper-audit.md#notation-rename-sweep`](paper-audit.md#notation-rename-sweep) の 3 番)。

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

<a id="stale-copy-in-scratch-cwd"></a>⚠️ **逆向きの shadowing — cwd を先に見るなら、 cwd は毎回新しい dir に**: 前の試しで preamble や macro の file を写した scratch dir を使い回すと、 cwd を先に見るので、 その古い写しが source dir の新しい file を隠す。 `$SRC//` (再帰) にすると、 source dir の下の古い写し (build の写しの dir など) も拾う。 試しの文書が「直す前の挙動」 を出し続けて、 仕掛けが効いていないと誤って結論しかけた (実測)。 試しの文書は `mktemp -d` の dir で組み、 log で読んだ path を確かめる (`grep -o '([^ ()]*preamble.tex' t.log`)。

⚠️ <a id="eq-number-from-current-build"></a>**人が式番号・頁で指したときも、 source dir に残った `.aux` で引かない**: 共著者が「(77) 式」 と書いたら、 その番号は相手が読んだ版 (送った PDF・いまの版) のもの。 source dir の `.aux` は前に in-place で組んだ古い版のことがあり、 同じ label が別の番号を指す (実測)。 いまの版を tree 外で組み、 その `.aux` の `\newlabel` で番号から label を引く。 相手が読んだのが差分の PDF なら、 その PDF の番号とも突き合わせる。

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

**事例 (2026-07-04 研究 LaTeX project の LIVE note family 統一)**: 大物 note 数本 + 小物 8 note で run-in `\paragraph` を top-level heading として使っていた計 ~150 本を、既存 §番号を保ったまま `\subsubsection` (subsection ありの大物) または `\subsection` (subsection なしの小物) に一斉昇格 (Chip H/I/J/K/L)。詳細は当該 repo の CLAUDE.md を slim 化の前に archive へ移した版の「見出しの論文型規律 (2026-07-04 確立)」 の節。

## <a id="exclude-comments-from-length"></a>長さ・段落構造の判断にコメントアウト行を数えない

**ルール:** 段落の切れ目・節の分割・restructure 等、 「文書の長さ / 段落の重さ」 を根拠にした編集判断は **rendered 出力 (= PDF に出る内容) だけで見積もる**。 `%` でコメントアウトされた行・ブロック (= 旧 draft・代替表現・comment-out keep で残した旧文) は source 行数を膨らませるだけで読者には出ないので、 長さの勘定に入れない。

**Why:** comment-out keep 流儀 (= 旧文を `%` で残し直下に新文を書く) や、 複数の代替表現を `%` で寝かせる運用では、 source 行数と rendered 分量が大きく乖離する。 source を上から眺めて「この段落は長い / 詰め込みすぎ」 と判断すると、 実際には普通サイズの段落を不要に分割する誤りに陥る (= 行番号レンジ L_a–L_b を分量の代理指標にすると、 間に寝た `%` ブロックを数えてしまう)。

**How to apply:** 「長い / 分割すべき」 と言う前に、 対象範囲の `%` 行を除いた live 本文だけを読む。 安価:

```bash
# comment と空行を落として、 印字される本文の分量だけ見る (comment 環境の中も落ちる)
python3 scripts/tex-printed-grep.py '\S' file.tex
```

display math・図は行数でなく rendered での専有量で別途見積もる。

## <a id="source-comment-scope"></a>source の comment に査読の記録を書かない — 置き場は results note

**ルール:** source の comment に書くのは、 版ごとの変更の要点・組版の注・コメントアウトした旧文 (盲検に出すときは写しで剥がす) まで。 **査読の verdict・finding の一覧・記録の置き場 (results・plans・notes・SESSION・DESIGN) への path・依頼の token (掲示板の request id を含む)・依頼者の発言の引用は書かない**。 置き場は results note と commit message の本文 (件名に結論を書くと、 盲検の受け手が repo の log から読む)。 path の先が査読の記録でない材料の note でも、 置き場への path なら検査は警告する = 材料の所在は repo の索引 (notes の README など) に書く (実測)。

**Why:** comment は剥がす段のある経路 (封じた sandbox の referee copy) では消えるが、 剥がす段の無い経路 (repo を直読する受け手) では対象と一緒に届く。 受領のたびに記録を source に書き戻すと、 次の round の盲検の対象に前回の結論が入る (実測: 掲示板経由の受け手が、 対象の先頭 comment に前回の verdict と訂正の一覧を読んだと申告した)。 汚染経路の分類 = [`cold-eyes-isolation.md`](../../ai-collaboration/conventions/cold-eyes-isolation.md#contamination-channels) (d)。

**How to apply:** 盲検に出す対象は経路に依らず写しにする (`strip-tex-comments.py IN OUT` → `check-review-target.py OUT` が exit 0)。 commit 時は .tex の comment に足した査読の語と記録への path を `check-review-target.py --staged-warn` が警告する (commit は止めない。 個人層の pre-commit に配線して使う)。

**本文も同じ** (実測): 「盲検で査読を受け、 その訂正を取り込んだ」 と受領を本文に 1 文で書くと、 comment を剥がした写しにも残り、 組版面で全読者に届く (封じた判定 session が申告規則で停止した = 検出器は働いたが 1 走分が無駄になる)。 受領の事実も results note に。 `check-review-target.py` はこの型の本文の文を kind body-history で止める。

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

**事例 (2026-05-10 或る教科書 project の第 1 部最終章 draft restructure)**: 7 commit に渡る章書き直しの過程で、 Claude が地の文に「a^† と a の代数構造」 「α_n の積」 「a^†|n⟩ ∝ |n+1⟩」 等を裸で書いて 3 箇所で build を破壊。 1 commit 内で 3 回 build retry が必要だった。 edit 直後の build verify で発覚 → 該当箇所を `$\hat{a}^\dagger$` 等で囲って修正。

## <a id="preamble-macros-first"></a>プリアンブル定義のマクロを優先する (絶対則)

**リポのプリアンブルで定義されているマクロ (semantic / typing shortcut / 色付き / 数式 alias / その他、種類問わず) が対象概念に存在する場合、生の primitive 記法を使うことを禁止する。**

⚠️ **「`\op` だけの話」 ではない**。プリアンブルで定義されているありとあらゆるマクロが対象。色付き semantic macro (`\op` `\st` `\rf` `\pd` 等) だけでなく、typing shortcut (`\h` = `\hat`、`\wh` = `\widehat`、`\tx` = `\text`、`\md` = `\middle|`、`\sqbr{}` = `\left[...\right]` 等) や数学演算子 (`\Tr`、`\fnl`、`\commutator{}{}` 等) も同等に強制対象。

例外は以下 **2 つに限定** (狭く解釈する):
1. プリアンブル定義が**無い**概念 (= grep で見つからない)
2. author drafting marker (= `\cl{}` `\green{}` 等の一時的 highlight、後で消す前提のスクラッチ、semantic 意味なし)。 著者が自分の推敲に使う印で、 AI が原稿に入れる文には付けない (正本 = [`edit-intent-record.md#no-draft-color-marks`](../../ai-collaboration/conventions/edit-intent-record.md#no-draft-color-marks))

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

> 新しい記号を足して検査が生の文字を止めたとき (preamble に、 その文字を別の意味の alias に割り当てた使われていない定義が残っている場合など): 検査の設定に例外を足す前に、 原稿の既存の流儀で書ける別の記法が無いかを見る (例: 長さの新記号でなく、 既存の「幅の 2 乗」 の族の添字違い)。 例外を足すのは、 その文字が本当に必要なときだけ。

上の絶対則を「読めば守る」 discipline だけに頼ると、共著者の Claude や別 session で raw 記法が静かに再混入する。**典型的な抜け道**: atom（`\h`・`\bs`・各 subscript alias）が個別には正規 alias なのに、それらを束ねた **compound macro をバイパスして書き下した形**（`\h T_{...}` を専用マクロの代わりに longhand）は、atom-level の grep / linter をすり抜ける。違反は linter が見る一段上で起きる。さらに別 dialect（別の綴り・別 primitive）でまるごと書かれた領域は、denylist に列挙していない綴りなので 0 hit で素通りする。

→ 各 LaTeX repo に **3 段の機械 enforcement** を置く:

1. **check script** — body を走査し、プリアンブルに macro があるのに raw を使う箇所を HARD 違反として列挙、hard>0 で `exit 1`。**engine は layer 1 の [`scripts/check-preamble-aliases.py`](../scripts/check-preamble-aliases.py)**（`python3 .../check-preamble-aliases.py paper.tex`）。macro vocabulary は repo ごとに違うが、**その vocabulary は当の preamble から導出できる**ので、repo ごとに script を fork する必要はない（旧版の本節は「macro 名の表を各 repo が持つ」前提で layer 2 常駐を指示していた。手書きの表は書いた人が思い出せた macro しか守らない = [documented-not-wired](../docs/convention-design-principles.md#documented-not-wired) の温床なので、導出に置き換えた）。engine は `\newcommand` 系の定義を読み、body 側の空白・括弧の揺れを吸収し、**compound macro をバイパスした形**（`\hat\rho_\S` を `\rh` でなく `\rhS` と名指す）を長い一致優先で拾う。**alias を定義だけして chain した compound**（`\TD` = `T_\tx{D}` on `\tx` = `\text`）は定義を段階展開して raw 形まで届かせる。導出で表せない repo 固有値（`\Tr\sqbr{` → `\Tr\fnl{` のような、どの macro の body でもない綴り / 意味的に別概念の alias / soft 扱い）は script 隣の JSON config（`targets` / `ignore_macros` / `soft_macros` / `extra_hard` / `extra_soft`）に置き、**engine 本体はどこへ mirror しても同一**に保つ（配布契約 = [`shared-repo.md#style-checker-mirror`](shared-repo.md#style-checker-mirror)）。偽陽性の設計（plain-text body を判定対象にしない・alias の alias を raw と呼ばない 等）は script の docstring が正本。
2. **committed pre-commit hook**（`.githooks/pre-commit` + `core.hooksPath` を張る `scripts/install-hooks.{sh,ps1}`）— clone 初回に 1 度 install すれば、以後の commit で 1. を自動実行し raw を含む commit を block。hook は version 管理下に置き、各著者の環境（mac / Windows git-bash）で動くよう `sh` で書く。既存の char-fixer 等があれば conditional に chain（無い環境では no-op）。⚠️ **Windows gotcha**: `.gitattributes` で hook と `*.sh` を `eol=lf` 強制しないと、checkout 時に CRLF 化して shebang（`#!/bin/sh`）が壊れる（`* text=auto eol=lf` 1 行で足りる）。git-bash の挙動は version 差があるので、Windows 共著者が居るなら初回に実機 smoke-test（適当な違反を commit して block されるか）を 1 度回す。
3. **CI**（`.github/workflows/*.yml` で push/PR ごとに 1. を実行）— pre-commit hook を install していない clone（= 制御できない共著者）でも server 側で必ず検出する最終防衛線。pure-script なので LaTeX build 不要・高速。

⚠️ **mechanize の限界を明示する**: 微分の `d` のように「regex で raw と正用を判別できない」 category は lint 不能 → discipline に残す（noisy rule を足すと false positive で linter の信頼を失う）。mechanize できる subset とできない subset を分け、後者は doc に明記する。

⚠️ **未採用の alias を drift と読み違えない**: 導出は「preamble に定義がある」しか見ないので、**定義だけして誰も使っていない alias**（昔の名残・別概念の semantic alias）も raw 形を大量に告発する。gate に入れる前に engine の `[alias N×]` 表示で仕分ける — alias 側が 0 回なら drift ではなく「採用されなかった macro」なので、**採る（sweep する）か `ignore_macros` に入れるかを 1 度決める**。既存原稿に初めて当てる時はこれが finding の大半を占める（実測: 手入れ済みの 3 原稿で adopted 174 / unused 628）。

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

- 短 argument: `\subretracted{Section 2 correction note}` → "See Section 2 correction note above for context." ✓
- 拡張 argument: `\subretracted{Section 2 correction note --- the earlier bound still holds}` → "See Section 2 correction note --- the earlier bound still holds above for context." ✗ ("remains valid above for context" が文法的に意味不明)

source レベルでは「うまく書けている」 ように見える。 10 instances 中 5 instances broken だが 4 layer の sweep を回しても本人気付かず、 pdftotext で初めて発覚した実例。

**回避設計 (= 推奨される 1st choice)**: macro に hardcoded prose を持たせず、 **全 prose を argument に持たせる**。 macro は wrapper のみ:

```latex
% 修正後 (= bug 不能)
\newcommand{\subretracted}[1]{%
  \par\noindent\textit{[Retracted. #1]}\par%
}
% caller 側で full sentence を渡す:
%   \subretracted{See Section 2 correction note above for context.}
%   \subretracted{See Section 2 correction note above. The earlier bound still holds.}
```

caller が完結した sentence を渡すので、 macro 側 fixed text と argument の grammatical 衝突が原理的に起きない。

**回避不能で fixed framing を含めざるを得ない場合 (= 2nd choice)**: commit 前に必ず render verify。 全 instance を pdftotext で extract → semantic 読み:

```bash
pdftotext -layout file.pdf - > /tmp/render.txt
grep -B1 -A2 "your-marker-keyword" /tmp/render.txt
```

複数 instance がある場合は **全部** 読む (= 1 instance だけ verify して OK と結論する trap も同 class)。

**一般化 (= 同 class の bug が出やすい構造)**: figure caption macro / table header macro / footnote wrapper macro / theorem environment / itemize/enumerate label customization / hyperref anchor macro 等、 「macro 側で fixed prose を author し、 argument で variable 部分のみ受ける」 全ての構造に同警戒。 source 静的解析 (grep / lint) では基本的に expose 不能、 render が唯一の検証手段。

## <a id="prescript-tall-nucleus"></a>左肩の添字 macro は核の高さで浮く — `\prescript` でなく標準 strut を基準にする (2026-09-13)

`\newcommand{\ord}[2]{\prescript{(#1)}{}{#2}}` (mathtools) のように左上添字を macro にすると、 `\prescript` は**引数の box の高さ**で添字の位置を決める。 核が `\hat{\overset{a,b}{X}}` のように飾り (overset・hat) で背が高いと、 添字が box の天辺まで持ち上がり、 核との間も空く。 error も warning も出ない。

**処方**: macro の側で基準の高さを固定する。

```latex
\newcommand{\ord}[2]{{\mathstrut}^{(#1)}\!#2}  % 左肩の高さは \mathstrut (TeX 標準の strut = 丸括弧の高さ)
```

⚠️ `{\vphantom{X}}^{(#1)}` のように**特定の文字**を基準にしない — その文字に合わせた場当たりの macro になり、 別の核では同じ問題が形を変えて残る (著者の指摘: 1 つの文字に対してだけ恣意的に最適化した macro になる)。 `\mathstrut` は内容によらず標準の高さを与えるための strut。 飾りの無い核では見た目はほぼ不変 (添字と核の間は `\!` の分だけ `\prescript` より詰まる)。

**確認**: 使用箇所のうち最も背の高い核を含む式を 1 つ render して、 飾り無しの核と添字の高さが揃うことを見る (途中の推敲 pass の目視 gate にはしない = [#visual-verification-intensity](#visual-verification-intensity))。

## <a id="index-after-tall-delimiter"></a>背の高い閉じ括弧の後の段違い添字は空 atom に付ける — `\right]{}^{ab}{}_{\mu\nu}` (2026-09-13)

`\left[ … \right]^{\mathbf{bc}}{}_{\nu\rho}` のように上付きだけを閉じ括弧に直接付けると、 TeX は上付きを**括弧の高さ**に合わせて持ち上げる一方、 `{}_{…}` の下付きは空 atom の標準位置に沈むので、 上下の添字の高さが揃わない (中身が `(\Gamma^{(2)})^{-1}` のように背が高いほど目立つ)。

**処方**: 段違い添字は上下とも空 atom に付ける。 括弧との隙間が気になれば `\!` を 1 つ (著者の手直し、 2026-09-13)。

```latex
\left[\Paren{\Gamma^{(2)}}^{-1}\right]\!{}^{\mathbf{bc}}{}_{\nu\rho}   % 上下とも空 atom、 高さが揃う
```

**冪は括弧に直接付けたままでよい** (`\left(\frac{h}{v}\right)^2`、 `(\ldots)^{-1}`): 冪は括弧全体に掛かる量なので括弧の高さに合うのが正しい。 対象は**添字** (index) だけ。 sweep = `grep -nE '\\right[])}]\^\{[^}]*\}\{\}_'` (1 行に収まる形だけ、 行をまたぐ形は目視)。

## <a id="maketitle-handset-author-block"></a>手組み author block と `\maketitle` を併用したら題扉の余白を詰める

物理原稿では、 所属・ORCID・脚注 email を細かく組むために `\author` を使わず **`\maketitle` の後ろに `center` 環境で著者ブロックを手組み**することがある。
このとき標準 `article` の `\@maketitle` は **空の author / date 枠のぶんだけ余白を出す** (`1.5em` + 空 tabular + `1em` + 空 date + `1.5em`)。
題扉が 1 頁に収まらない、 abstract が脚注に押し付けられる、 という症状の第一容疑者。

```latex
\makeatletter
\def\@maketitle{%
  \newpage \null
  \vskip -1em%            (標準は 2em)
  {\centering \LARGE \@title \par}%
  \vskip 1em}%            (標準は 1.5em + 空 author + 1em + 空 date + 1.5em)
\makeatother
```

- ⚠️ **`center` 環境でなく `\centering`**。 `center` は前後に `\addvspace` を出すので、 直前の負の `\vskip` が打ち消される (`-1em` も `-3em` も同じ位置になり「効かない」 と誤診する)。
- 自動日付を消すのは `\date{}` を `\maketitle` の前に置くだけ (投稿原稿の清書項目。 `\maketitle` 自体は動かさない)。
- **効果は目視でなく座標で測る** — PyMuPDF で 1 頁目の text block の上端・下端を出し、 本文頁の text top と比べる:

```python
import fitz
p = fitz.open("paper.pdf")[0]
for y0, y1, s in sorted((b[1], b[3], b[4][:40]) for b in p.get_text("blocks") if b[4].strip()):
    print(round(y0), round(y1), s)
```

  題名の上端が本文頁の text top (例: 109 pt) より上に出たら詰めすぎ。 詰めた結果 1 頁目に本文が流れ込むのが嫌なら abstract の後に `\newpage` (目次を挟むなら `\newpage\tableofcontents\newpage`)。

## <a id="float-above-handset-title"></a>`\maketitle` を使わず題を手で組んだら、 1 頁目の上に図を置かせない

短いノートでは `\maketitle` を使わず、 `center` 環境で題と日付を手で組むことがある。
このとき `[t]` や `[tb]` の図は、 1 頁目の**題より上**に置かれうる (実測: 図 1 が題の上に出た)。
標準の `article`・`ltjsarticle` の `\maketitle` は 1 頁目の上の float を止める (`\global\@topnum\z@`) が、 手で組んだ題は止めない。

```latex
\begin{center} … 題と日付 … \end{center}
\suppressfloats[t]   % この頁の上には float を置かない
```

- 図をその図を使う節の直後に `[ht]` で置くと、 説明の途中で図が次の頁の頭に飛ばず、 読む流れに沿う。 頁数が増えないかは組んで確かめる。

## <a id="supplement-in-same-pdf"></a>Supplemental Material は、 まず同じ PDF の文献表の後に置く

付録が長すぎて、 導出・別表現・検算を Supplemental Material へ移すときの形。 投稿まで同じ source で組み、 相互参照を壊さないため。

- **置き方**: `\bibliography{...}` の後に `\input{supplement-....tex}` を置く。 その file の冒頭で `\clearpage`、 section と equation の counter を 0 に戻し、 `\thesection` と `\theequation` を `S\arabic{...}` にする。 hyperref を読んでいるなら `\theHsection` と `\theHequation` も同じ形にして、 PDF の destination 名を本文の節・式と重ねない。 題は `\section*{Supplemental Material}` とし、 冒頭の 1 文で「S のついた番号はこの補足、 他は本文」 と断る。
- **利点**: 本文・付録・補足の間の `\ref` がそのまま働く。 付録から補足の式を指すことも、 補足から本文の式を指すこともできる。 雑誌が別 PDF を求める段になったら、 xr で外部参照に切り替えて分ける。
- **移し方**: 移設は verbatim で、 行の対応を機械で照合する ([`paper-audit.md#relocation-rebinding-sweep`](paper-audit.md#relocation-rebinding-sweep)、 [`scripts/verify-verbatim-move.py`](../scripts/verify-verbatim-move.py))。 付録に残す式が、 移した block の中でだけ定義された記号を使っていないかも見る ([`paper-audit.md#orphaned-definition-after-move`](paper-audit.md#orphaned-definition-after-move))。 付録の側には「入力 (定義) と出力 (結果・限界)」 を残し、 補足への案内を 1 文置く。
- **量の目安** (実測): 導出と検算が主な付録は 4 分の 1 ほどに縮む。 定義と結果が主で散文の注意書きが多い付録は、 移設だけでは 2〜3 割しか縮まない。 そこから先は文を詰める書き直しで、 著者の通読が要る。

## <a id="companion-paper-split"></a>原稿の一部を別論文 (companion paper) に分ける

付録や補足が独立の論文として立つと判断したとき、 同じ repo で 2 本を並べて組む形。 移設そのものの規律は [`paper-audit.md#relocation-rebinding-sweep`](paper-audit.md#relocation-rebinding-sweep) (verbatim-first) に従い、 ここは文書をまたぐときに増える作業を持つ。

- **置き場所**: 別論文の source は本論文と同じ dir に置く。 preamble の macro・文献・bst・build の設定をそのまま共有でき、 path の glob で原稿の範囲を決める保護の設定 ([`manuscript-claim-ownership.md#mechanism`](manuscript-claim-ownership.md#mechanism)) も新しい file に自動で掛かる。 別の dir に置くと glob の外に出て、 保護が黙って外れる。
- **名前に中身の範囲を入れない**: file 名と引用 key は、 移す範囲が広がっても変わらない語にする (`companion`、 `theory-paper` など)。 範囲の語で付けると、 範囲が広がった時点で改名と引用の付け替えが要る (実測)。
- **手順**: (1) 移す前に [`scripts/latex-split-deps.py`](../scripts/latex-split-deps.py) で依存を出す (A = 残る側から移す側の label への参照、 B = 移す側から残る側への参照、 C = 移す側だけが使う引用、 D = 移す側の文で旧い入れ物を指す語)。 (2) 1 つめの commit で逐語に移し、 [`scripts/verify-verbatim-move.py`](../scripts/verify-verbatim-move.py) `--from <本論文> --to <別論文>` で照合する。 (3) 2 つめの commit で A・B・D を付け替える。
- **本論文側 (A)**: 本文から移した付録への案内は、 別論文の引用に換える。 残る付録が移した付録の式を使っていたら、 まず本論文に残る同じ内容の式を探す (一般の式の特別な場合を、 別の付録や本文が既に書いていることが多い。 実測では 2 件とも見つかった)。 基本の定義を別論文の引用に頼らない。 付録を並べて紹介する文からも外す。
- **別論文側 (B・D)**: hyperref より前に `\usepackage{xr-hyper}` を読み、 `\externaldocument[I-]{main}` で本論文の label を接頭辞つきで読む (本論文を先に組む)。 本論文への参照は `Sec.~\ref{I-sec:x} of Ref.~\cite{paperI}` の形に書き換える。 接頭辞なしで読ませると、 本論文の番号が別論文の番号のように印字される。 "the main text"・"this appendix"・"Supplemental Material" は、 別論文での呼び方 (Ref.~[I]・this section・the appendices) に換える。 補足を付録として入れるときは、 補足の頭 (counter の reset・S 番号・導入文) を外す。
- **相互の引用**: 両論文を `refs.bib` の in preparation の `@misc` で引き合い、 arXiv に出たら差し替える。
- **共有フォルダへの写し**: push のたびに PDF を写す仕組み ([`repo-history-growth.md`](repo-history-growth.md) の pdf-publish) に別論文を 1 行足す。 写しの仕組みは今ある文書の PDF を写すだけで、 改名前の名前の PDF は共有フォルダに残る。 改名したら古い写しを消す。 共有フォルダは相手も見ているので、 消す前に持ち主に確かめる。

## <a id="compilers"></a>コンパイラ

odakin の標準は **pdf 直接出力 (= pdftex 系)**。tex+dvi+dvipdfmx の 2 段ワークフローは**英語論文では使わない**。

- **英語のみ** → **`lualatex`** が odakin の標準 (= TeXShop が `LuaTeX-1.21.0` で生成、PDF Producer 欄で確認済)。`pdflatex` も可 (どちらも pdf 直接出力で互換)
- **日本語含む** → `ptex2pdf` (内部で platex + dvipdfmx) または `lualatex` (jlreq クラス等)。 owner が全ての文書を LuaLaTeX で組むと決めた場合の source の書き方・移し方・機械の検査 = [#lualatex-compat](#lualatex-compat)
- **<a id="class-dictates-engine"></a>class が engine を決める** (= 齟齬は engine 側で patch できない、 class を変えるか engine を変えるかの二択):

  | documentclass | 使う engine |
  |---|---|
  | `article` / `book` / `report` 等 (LaTeX default) | pdflatex / lualatex |
  | `jsarticle` / `jsbook` / `jarticle` / `jbook` (pTeX classes) | **platex + dvipdfmx** (pdflatex / lualatex は不可) |
  | `uplatex` 系 (Unicode 日本語 pTeX) | **uplatex + dvipdfmx** |
  | `ltjsarticle` / `ltjsbook` / `jlreq` 等 (LuaLaTeX-JS) | **lualatex** (luatexja 経由) |
  | `bxjsarticle` 等 (BX/JS series、 engine-agnostic) | class option で切替 |

  **診断**: `jsarticle` 等の pTeX class に `pdflatex` を打つと `! LaTeX Error: Unicode character X (U+XXXX) not set up for use with LaTeX` が日本語 1 文字ごとに連発する fingerprint が出る (2026-07-13 観測)。 log にこの pattern を見たら engine 選択ミス確定 → 正しい経路は `platex → platex → dvipdfmx` または `latexmk -latex=platex -pdfdvi <file>`。 `pdflatex` に別 patch を当てる方向は原理的に不可 (= class 側で pLaTeX 前提の macro を使っているため)。

  **同 fingerprint の別原因 (engine は正しい場合)**: 正しい `platex` 経路でも、**丸数字 ①②③ (U+2460 系) 等の JIS X 0208 外文字**は同じ `Unicode character not set up` エラーになる (公募要領の丸数字つきの項目を調書へ引用して観測)。対処 = `uplatex` へ移行 / `otf` package の `\ajMaru{3}` / 引用文なら番号を落として書き換え (調書等の使い捨て文書は書き換えが最速)。エラー行数が「日本語ほぼ全文字」なら engine ミス、「特定の記号だけ」なら本項。
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

⚠️ <a id="latexmk-pdf-overrides-rc"></a>**`latexmk -pdf` は `.latexmkrc` の engine 指定を上書きする** — repo が `.latexmkrc` で `$pdf_mode = 4` (lualatex) を宣言していても、コマンドラインの `-pdf` は `$pdf_mode = 1` (pdflatex) を意味するので、**error 0・警告なしで別 engine の PDF が出る**。壊れないので気付かない: 変わるのは合字・アクセント・分数まわりの組で、抽出テキストでは `Poincaré` → `Poincar´e`、`spin-1/2` の分数が潰れる形で出る (2026-09-12 実測)。→ **`.latexmkrc` を持つ repo では `latexmk` を素で叩く** (engine を明示したいときは `-pdf` でなく `-lualatex` / `-pdflatex`)。焼き直した PDF を比較検証に使うなら、まず `metadata['producer']` が旧版と一致するかを見る (= 中身の diff を読む前に engine の同一性を確かめる)。

⚠️ <a id="partial-aux-cleanup"></a>**`.aux` だけ消して `.fdb_latexmk` を残すと、 latexmk が止まる**: latexmk は前回の記録 (`.fdb_latexmk`) を見て、 source が変わっていないと engine を回さずに bibtex だけを呼ぶ。 `.aux` が空なので bibtex は `I found no \citation commands` で失敗し、 latexmk は exit 12 で終わる (実測)。 PDF は古いまま残るので、 頁数だけ見ると成功に見える。 中間 file は `latexmk -c` でまとめて消すか、 `.aux` と一緒に `.fdb_latexmk`・`.fls`・`.bbl` も消す。

⚠️ <a id="nonstopmode-hides-undefined-env"></a>**`-interaction=nonstopmode` は undefined environment を握り潰して PDF を出す**: クラスが `amsmath` を読んでいないのに `\begin{equation*}` を書くと `! LaTeX Error: Environment equation* undefined.` が出るが、**nonstopmode では build が続き PDF も生成される** (中身は壊れた組版)。学会・申請書の配布クラスは `amsmath` を仮定できない (実測: 科研費の LaTeX クラス)。→ **build の度に `grep -c "^!" *.log` が 0 であることを確認する**。素の `\[ ... \]` は amsmath なしで動くので、可搬性が要る文書ではこちらを既定にする。

## <a id="silent-typesetting-traps"></a>silent に効かない組版指定 — 書いたのに無視される 5 型 (2026-09-12)

いずれも **error も warning も出ず、出力だけが指定と違う**。目視では気づけないので、疑ったら**出力 PDF を測る** ([`scripts/measure-pdf-layout.py`](../scripts/measure-pdf-layout.py))。

### <a id="declare-paper-size"></a>用紙は documentclass の option に明示する (標準 class の既定は letterpaper)

`\documentclass[11pt]{article}` のように用紙の option を書かないと、 標準 class (article / report / book、 revtex も) は **letterpaper** で組む。 build は error も warning も出さず、 頁数も版面も自然に見えるので、 A4 の紙に刷る段 (印刷の preflight が本体のトレイと PDF の寸法を比べる) まで気づかない (実測: 1 つの project の 2 文書が長く Letter のまま組まれていた)。 `a4wide` や `geometry` の余白設定は版面を決めるだけで、 用紙を A4 にはしない (geometry に `a4paper` を渡せば用紙も決まる)。

- **書く**: `\documentclass[11pt,a4paper]{article}` のように、 用紙を source に書く (刷る紙の側に合わせる。 どの機械で組んでも同じ頁になる)。 jsarticle / ltjsarticle 系は既定が A4 (検査も警告を出さない)
- **確かめる**: `python3 scripts/check-tex-papersize.py FILE.tex` (option に用紙が無い `\documentclass` を列挙、 exit 1) / `--pdf FILE.pdf` (組んだ PDF の 1 頁目の寸法を A4 / Letter で言う)。 pre-commit に `--staged-warn` を繋ぐと、 staged の .tex で用紙の無い `\documentclass` を warn する (commit は止めない)
- pdflatex / lualatex (pdf mode) では class option だけで PDF の MediaBox まで届く。 hyperref の `setpagesize=false` が残っていても届く (実測、 LuaLaTeX)。 止まるのは dvipdfmx の経路で、 次の節 (papersize special が要る)

### <a id="dvipdfmx-papersize"></a>documentclass の用紙指定は、 papersize special が出ないと PDF の用紙に届かない (dvipdfmx)

`\documentclass[a4paper]{...}` の用紙 option は版面の寸法を決めるだけで、 PDF の MediaBox は **papersize special** で決まる。 special を出すのは `hyperref` (driver が dvipdfmx のときの既定)・`geometry`・jsclasses の `papersize` option で、 **どれも無ければ dvipdfmx の既定**になる。 既定は環境依存なので、**同じ tex が機械によって A4 になったり Letter になったりする**。版面は指定どおりの寸法のまま別サイズの紙に載るので、**上下の余白だけが非対称に詰まる**という出方をする。

- 診断: `python3 -c "import fitz; print(fitz.open('x.pdf')[0].rect)"` → A4 = 595.28 × 841.89 pt / Letter = 612 × 792 pt
- 対策 (環境非依存、preamble に 1 行):
  ```latex
  \AtBeginDvi{\special{papersize=210mm,297mm}}
  ```
- `dvipdfmx -p a4` でも直るが、**誰がどこで組んでも同じにしたいなら tex 側に書く**
- jsclasses (jsarticle / jsbook) なら、class option に `papersize` を足すだけでよい (`\documentclass[uplatex,dvipdfmx,a5paper,papersize]{jsbook}`)。用紙の option を変えたとき (A4 → A5 など) も special が追随する。実測: `dvipdfmx` option だけでは Letter のままだった
- ⚠️ special を出す package を読むかどうかで、 **同じ repo でも file ごとに A4 と Letter が分かれる** (`geometry` を使う file だけ A4、 使わない file が Letter。 両方を並べて刷って初めて気づく)
- ⚠️ `hyperref` の special は **`setpagesize=false` で止まり**、 dvipdfmx の既定に落ちる。 古い雛形にこの option が残っていることがある。 実測 (platex + dvipdfmx、 `letter` class): `a4paper` + `setpagesize=false` → Letter / `a4paper` のみ → A4 / どちらも無し → Letter (標準 class の既定は letterpaper)

### <a id="tabular-cell-two-lines"></a>表の 1 つの欄だけが長くて表がはみ出すときは、 その欄の中を小さな tabular で 2 行に折る

1 つの欄を長くすると列の幅がその欄で決まり、 表全体が版面からはみ出す (Overfull \hbox)。 その欄だけを `\begin{tabular}[t]{@{}l@{}}前半,\\ 後半\end{tabular}` にすると、 他の行は 1 行のまま、 その行だけが 2 行になる。 標準の tabular で書け、 `[t]` で 1 行目を同じ行の他の欄にそろえる。 原稿の数を断片で pin している test があれば、 折った後の source の文字列に合わせて断片を直す (実測)。

### <a id="tabular-cell-trailing-hspace"></a>tabular セル末尾の裸 `\hspace` は `\unskip` に消される

列幅を作るつもりで `\multicolumn{n}{|l|}{\hspace{<幅>}}` と書いても効かない (array がセル末尾の glue を `\unskip` で削る)。`\mbox{}` で挟む。

```latex
\multicolumn{3}{|l|}{\mbox{}\hspace{<幅>}\mbox{}}   % 効く
```

症状は「幅指定が黙って無視され、表幅が中身の最大幅で決まる」。**同じ書き方をした別の表と並べて幅が揃わないまで気づかない**ので、複数の表で同じ幅指定をしている文書では全部の実測幅を比べる。

### <a id="filldraw-without-shape"></a>形を書かない `\filldraw` は何も描かない

```latex
\filldraw[black] (0,0);                  % 出力ゼロ
\filldraw[black] (0,0) circle (0.4mm);   % 点が出る
```

「点を打ったつもりで打っていない」が起きる。逆向きの事故もある — **テンプレートを複製するとき、この no-op 行を「点がある」と読んで再現すると、元には無かった点を足してしまう**。複製元の意図は source でなく**出力**で確かめる。

### <a id="tikz-grid-rect-vs-lines"></a>TikZ の grid は「線の位置」と「切り取り矩形」が独立

`\draw[step=1] (a,b) grid (c,d)` の格子線は **step の整数倍**に置かれ、`(a,b)-(c,d)` は**切り取り範囲**でしかない。∴ 矩形の角を整数にすると一番外の線が縁と一致して窮屈に見え、**半 step だけ外に取ると線の位置は変わらないまま外周に余白が付く** (マニュアルの定型)。

```latex
\draw[step=1,dotted] (-3,-3) grid (3,3);        % 外周の線が縁と一致
\draw[step=1,dotted] (-3.5,-3.5) grid (3.5,3.5); % 線は -3..3 のまま、外に半マス
```

矩形を半 step 広げると bounding box も広がるので、**高さに余裕のない配置では行が伸びる**。広げたら出力を測り直す。

### <a id="multirow-vs-raisebox-centering"></a>縦中央に置くのは `\multirow` だけ、`\raisebox` は持ち上げるだけ

背の高い行 (図を入れたセル等) のラベルを枠の縦中央に置きたいとき:

- `\multirow{N}{*}{...}` は**自動で中央**に来る
- `\raisebox{...}{...}` は**指定した分だけ持ち上げる**だけ

両方を使っている表では**ラベルの高さが揃わない**。図のセルは multirow が使えないことが多いので、`\raisebox{\dimexpr<基準>+<実測>pt\relax}` のように実測で合わせることになる。その場合:

1. **実測値は図の寸法に連動する**。図の縦幅を変えたら再調整が要る → tex にその旨をコメントで残す
2. 調整は「枠の上下罫線の中点」と「ラベルの中心」の差を測って足し引きする (1 回で ±0.5 pt に入る)
3. 罫線を拾うときは**図の座標軸を罫線と誤認しない** — 軸も水平で細長い。幅で閾値を切る (罫線は表幅、軸は図幅)

## <a id="jsclasses-mag-true-lengths"></a>jsclasses の 10pt 以外は版面ごと拡大する — mm で書いた長さが黙って伸びる (`nomag*`)

jsarticle / jsbook は、 `11pt` `12pt` などを指定すると、 既定では `\mag` で版面全体を拡大して字の大きさを作る。 このとき、 preamble や package が `mm` `pt` で指定した長さも同じ倍率で伸びる。 error も warning も出ない。

- 実測 (uplatex + dvipdfmx、 jsbook、 A5): `eso-pic` で引いた `\rule{40mm}{10mm}` は、 `11pt` では 43.8 mm に描かれた (1.095 倍)。 `11pt,nomag*` と `10pt` では 40.0 mm だった。 PDF の用紙寸法はどれも同じで、 頁数も `11pt` と `11pt,nomag*` で変わらなかったので、 頁数や用紙を見ても気づけない。
- 診断: PDF に描かれた罫の幅を測る (`fitz` の `page.get_drawings()` の `rect.width` を mm に直す)。
- 対策: 実寸で描きたい物 (小口の色帯、 囲みの余白、 TikZ の図、 `geometry` の指定) がある文書では、 class option に `nomag*` を足す (`\documentclass[uplatex,dvipdfmx,a5paper,papersize,11pt,nomag*]{jsbook}`)。 `nomag*` は `\mag` を使わず、 字の大きさだけを変える。 1 行の字数と頁割りは `11pt` と同じになる。
- 個別に実寸を書くなら `truemm` `truept` を使う手もあるが、 package の中の長さまでは直せない。

## <a id="back-of-book-notes"></a>巻末に回したノートに、 元の章の番号と頁つきの参照を付ける (小口の色帯つき)

本文から出した計算や補足を巻末にまとめる本で、 「ノート 3.2」 のように元の章の番号を付け、 本文からは「(→ ノート 3.2，p.123)」 と頁つきで参照する仕掛け。 章の `\label` を使うので、 章の順番を入れ替えても番号が追随する。

```latex
\makeatletter
\newcounter{backnote}
\newcommand{\backnote@chap}{}
\renewcommand{\thebacknote}{\ref*{\backnote@chap}.\arabic{backnote}}
% 巻末側: その章の分の始まり。 #1 = 元の章の \label
\newcommand{\backnotesof}[1]{%
  \setcounter{backnote}{0}\renewcommand{\backnote@chap}{#1}%
  \section*{第\ref*{#1}章のノート}%
  \addcontentsline{toc}{section}{第\ref*{#1}章のノート}}
% 巻末側: ノート 1 本。 #1 = このノートの \label、 #2 = 題
\newcommand{\backnote}[2]{%
  \refstepcounter{backnote}\label{#1}%
  \subsection*{ノート \thebacknote\quad #2}}
% 本文側
\newcommand{\tobacknote}[1]{（→ ノート~\ref{#1}，p.\pageref{#1}）}
\makeatother
```

- `\thebacknote` の中の章番号は `\ref*` (hyperref の星つき = リンクを作らない版) にする。 番号そのものは、 本文側の `\ref` がリンクにする。
- 巻末では式番号が本文と紛れるので、 `\renewcommand{\theequation}{N.\arabic{equation}}` のように頭文字を付ける。
- 小口の色帯 (閉じた本の外から巻末の場所が分かる) は `eso-pic` で、 奇数頁は右端、 偶数頁は左端に描く。 帯を出す範囲は `\newif` のスイッチを `\global` で切り替える。 `\include` の直後に `\clearpage` してから切ると、 最後の頁まで帯が付く。

```latex
\usepackage{eso-pic}
\makeatletter
\newif\ifthumb@band
\newcommand{\thumbbandon}{\global\thumb@bandtrue}
\newcommand{\thumbbandoff}{\global\thumb@bandfalse}
\newlength{\thumbbandwidth}\setlength{\thumbbandwidth}{4mm}
\AddToShipoutPictureBG{%
  \ifthumb@band
    \ifodd\value{page}%
      \AtPageLowerLeft{\hspace*{\dimexpr\paperwidth-\thumbbandwidth}%
        {\color{blue!35}\rule{\thumbbandwidth}{\paperheight}}}%
    \else
      \AtPageLowerLeft{{\color{blue!35}\rule{\thumbbandwidth}{\paperheight}}}%
    \fi
  \fi}
\makeatother
```

- 帯の幅を実寸にするには、 上の [#jsclasses-mag-true-lengths](#jsclasses-mag-true-lengths) の `nomag*` が要る。
- 実測: uplatex + dvipdfmx + jsbook で、 章付きの番号、 頁つきの参照、 目次の項目、 外側の端の帯が意図どおりに出た。 章番号を `\ref` で引くので、 参照が落ち着くまで組版を繰り返す。

<a id="chapter-thumb-tabs"></a>**章ごとの爪 (小口の章見出し)**: 本文の各頁の外側の端に、 章ごとに高さをずらした色の四角 (爪) と章番号を付けると、 閉じた本の小口から章の位置が分かる。 巻末の帯と同じ `eso-pic` の背景で描く。

```latex
\makeatletter
\newif\ifthumb@on
\newcounter{thumb@base}\newcounter{thumb@slot}
\newcommand{\thumbslots}{10}                                % 縦に並べる段の数
\newlength{\thumbwidth}\setlength{\thumbwidth}{6mm}
\newlength{\thumbheight}\setlength{\thumbheight}{16mm}      % 1 段の高さ
\newlength{\thumbtop}\setlength{\thumbtop}{20mm}            % 紙の上端から 1 段目まで
\g@addto@macro\mainmatter{\global\thumb@ontrue}             % 前付けには付けない
\g@addto@macro\backmatter{\global\thumb@onfalse}            % 巻末には付けない
\let\thumb@appendix\appendix                                % 付録は本文の最後の章の次の段から
\renewcommand{\appendix}{\setcounter{thumb@base}{\value{chapter}}\thumb@appendix}
\newcommand{\thumb@tab}{%
  \setcounter{thumb@slot}{\numexpr\value{thumb@base}+\value{chapter}-1\relax}%
  \@whilenum\value{thumb@slot}>\numexpr\thumbslots-1\relax\do{\addtocounter{thumb@slot}{-\thumbslots}}%
  \raisebox{\dimexpr\paperheight-\thumbtop-\thumbheight*\numexpr\value{thumb@slot}+1\relax\relax}{%
    \rlap{{\color{blue}\rule{\thumbwidth}{\thumbheight}}}%
    \makebox[\thumbwidth][c]{\raisebox{\dimexpr.5\thumbheight-.5ex\relax}{%
      {\color{white}\sffamily\bfseries\small\thechapter}}}}}
\AddToShipoutPictureBG{%
  \ifthumb@on\ifnum\value{chapter}>0 \ifthumb@band\else
    \ifodd\value{page}\AtPageLowerLeft{\hspace*{\dimexpr\paperwidth-\thumbwidth}\thumb@tab}%
    \else\AtPageLowerLeft{\thumb@tab}\fi
  \fi\fi\fi}
\makeatother
```

- 巻末の帯 (上の `\ifthumb@band`) が出ている頁には爪を出さない。 帯は全高・淡色、 爪は段ごと・濃色にして見分ける。
- `\appendix` は章の番号を 0 に戻すので、 戻す前の値を控えて段をずらさないと、 付録 A が第 1 章と同じ高さに出る。
- 章の頁は、 次の章の `\cleardoublepage` で前の章の最後の頁が出てから番号が進むので、 各頁の爪は正しい章になる (空白の偶数頁は前の章の爪になる)。
- 紙の端まで色を出すには、 仕上がり線の外まで色を伸ばす塗り足しが要る。 `papersize` で仕上がり寸法の PDF を作るとこの余白が無いので、 入稿前に印刷所の指定で作り直す (帯も同じ)。
- 確かめ方: 各頁の外側の数 mm を切り出して横に並べると、 閉じた本の小口の見え方になる (PyMuPDF で頁を画像にして端を crop)。
- 実測 (uplatex + dvipdfmx + jsbook、 A5)。

<a id="makefile-include-deps"></a>**`\include` する file の置き場を増やしたら、 Makefile の依存にも足す**: 依存が `chapters/*.tex` などの wildcard だけだと、 新しい folder (前付けなど) の file を直しても `make` が「最新」 と判断して組み直さない。 画面の PDF が古いまま気づきにくい (実測)。

## <a id="matplotlib-cjk-figure-embedding"></a>matplotlib の CJK 入り図は PNG で取り込む (PDF は platex+dvipdfmx で描画だけ化ける)

matplotlib が CJK フォント (macOS Hiragino 等の `.ttc`、`pdf.fonttype = 42`) を埋め込んだ PDF を
`\includegraphics` で platex + dvipdfmx に通すと、**図中の日本語ラベルが描画だけ化ける**
(2026-08-21 実測)。見落としやすい理由 = **文字抽出 (ToUnicode) は正常**で、viewer によっては
読めることもある → 「PDF を目視した」だけでは気づかない。fitz / gs の両エンジンで化けたので、
投稿先・審査側の PDF 変換でも危険と判断する。

- ❌ Hiragino 等の字体のまま `pdf.fonttype = 3` に切り替える — glyph 名が非 ASCII の字体では `UnicodeEncodeError`
  で落ち、しかも失敗時に出力 PDF を壊す (0 byte / 不完全)。 字体ごと替えれば 3 で通る (下の ✅)。
- ❌ gs `-dNoOutputFonts` で outline 化 — 化けた glyph をそのままパス化するだけで無効
  (+ gs 既定の PDF 1.7 は dvipdfmx が取り込み拒否し build が silent 失敗する。1.5 を指定しても無意味)。
- ✅ **Agg レンダリングの PNG (300 dpi) を `\includegraphics` する** — viewer / 変換系に依存しない。
  モノクロ印刷前提の書類 (科研費調書等) なら品質は十分。
- 代替 (vector が必要な場合): `.ttc` でない単体 TTF (IPAex 等) を `font_manager` で指定して Type 42
  埋め込み (未検証)。
- ✅ (vector のまま、 LuaLaTeX で実測) TeX 同梱の原ノ味 OTF を `addfont()` で登録し、 `pdf.fonttype` は既定 (3) のまま
  → `\includegraphics` した頁で描画も文字抽出も正常。 原ノ味でも 42 にすると日本語だけ消える = [`beamer-slides.md` §10](beamer-slides.md#generate-figures-not-scavenge)。

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

## <a id="line-initial-punct-scan"></a>行頭の句読点 (禁則違反) を機械 scan する — bold 境界で prebreakpenalty が不発になる

pLaTeX の禁則処理は通常 `。、` の行頭落ちを防ぐが、**`\textbf{…（…）}。` のように bold group の閉じ直後に
句読点が来ると、フォント境界で prebreakpenalty が効かず「。」が行頭に印字される**ことがある
(2026-08 実測: run-in 見出し `\textbf{(1) …（初年度）}。本文…` の見出しが行幅ちょうどで終わり、
直後の「。」が次行頭に落ちた。提出後の第三者査読で発覚)。

- **修正**: 句読点を bold の内側に含める (`\textbf{…（…）。}` — 太字の句点は視覚上ほぼ区別されず、
  同一 JFM run 内なので禁則が正常に効く)。`\nobreak` 挿入でも防げるが、内側に含める方が自己文書化される。
- **検出を機械化する**: 生成 PDF を PyMuPDF で行走査し、行頭が `。、）」` の行を flag する:

  ```python
  import fitz
  for i, page in enumerate(fitz.open("out.pdf")):
      for line in page.get_text().split("\n"):
          s = line.strip()
          if s and s[0] in "。、）」":
              print(f"p{i+1} 行頭禁則: {s[:30]!r}")
  ```

  0 件 = silent でビルド毎に回せる。⚠️ 様式が独自 wrap するセル内文字列 (電子申請システムの経費明細等、
  自分の組版でない部分) は偽陽性として除外してよい。sibling の PDF 検品 = [#pdf-line-collision-detection](#pdf-line-collision-detection)。

## <a id="revtex-short-document"></a>revtex4-2 で 1 頁の文書 (正誤表・短い note) を組むときの崩れ

- **`\date{}` を書くと「(Dated: )」 が出る** — revtex は空の日付も組む。 日付を出さないなら `\date` の行ごと書かない。
- **itemize の上下の空きが `\setlength{\topsep}` で変わらない** — revtex は list に入るたびに `\@listi` で `\topsep` などを設定し直す。 詰めた箇条書きは `\begin{list}{\textbullet}{\setlength{\topsep}{3pt}\setlength{\itemsep}{0pt}…}` のように list の第 2 引数で設定する。 行内の数式が長く underfull が出るなら、 list を `{\raggedright … \par}` で囲む (囲む前の段落は `\par` で閉じる)。
- **最後の頁の段そろえで、 見出しが前の項目に貼り付く** — `reprint` の 2 段組は最後の頁の左右の段の高さをそろえる。 そろえ切れない長さのとき、 段の切れ目の後ろの見出し (`\section*{Data Availability}` など) が上の空きを失って前の項目に密着する。 `\vfill` や `\vspace*` を足しても直らない (実測)。 直し方 = class option に `nobalancelastpage` を足し、 `\raggedbottom` を置き、 段を切りたい位置 (箇条書きなら項目の間) に `\pagebreak` を手で置く。 `\raggedbottom` だけだと脚注 (著者の email) が段の途中に出る (実測)。 中身の長さが変わったら `\pagebreak` の位置を動かし直す (頁の画像で左右の段の長さを見る)。
- 用紙は revtex も既定が letter = [#declare-paper-size](#declare-paper-size)。 版元が組み直す投稿用の原稿では、 用紙は版元の組版が決める。

## <a id="bibliography-style"></a>Bibliography スタイル
- **JHEP.bst を使う**（個人的好み）。`note` フィールドも表示するバージョンを使用
- 正本: `~/Claude/claude-config/JHEP.bst`（ver. 2.18 ベース + note 全 entry type で有効化、md5: `0934fe19…`。 2026-07-24 に header comment 内の Unicode curly quotes を LaTeX 式 ``…'' に正規化 = char-fixer 配下 repo へ配布しても md5 が割れない idempotent 化、 機能変更なし）
- `setup.sh` が **TEXMFHOME** にインストール（odakin: 自動、他ユーザー: オプション表示。 user 所有 + ls-R 不要ゆえ sudo/texhash 不要。 ⚠️ 旧方式 texmf-local + texhash は ls-R が root 所有だと silent fail し「cp 成功・kpsewhich 不可視」 の死角を作る = 2026-07-24 実測 RCA、 導線 verify は `kpsewhich JHEP.bst` の md5 照合）
- **リポに vendor する場合は必ず正本から copy し、 `md5 -q <repo>/JHEP.bst` を正本 md5 と照合する**。 ⚠️ **他 repo からの copy は禁止** — 既存 repo には note 無効の stock v2.7 等の stale copy が複数残存しており、 そこから copy すると stale が増殖する（2026-07-24 RCA: `@unpublished` in-preparation entry の note が silent に落ちる形で発覚。 「note 表示有効」 と信じている file が実は stock、 は目視で見抜けない = md5 照合が唯一の cheap gate）
- `\bibliographystyle{JHEP}` を指定
- 将来 style を改版したら: 正本を編集 → 本節の md5 更新 → `setup.sh` 再実行で TEXMFHOME 同期 → vendor 済み repo は次に触る時に md5 照合で気付く
- <a id="citation-order-numbering"></a>**番号は初出順で付く** (JHEP.bst は unsorted): ある文献の最初の引用を消す・後ろへ動かすと、 その文献と、 旧初出から新初出までの間で初めて引かれる文献の番号がまとめて変わる。 同じ build の中では bibtex が付け直すので不整合は出ないが、 **build の外に書いた番号 (査読返答・決定台帳・共著者へのメール・review note) は黙って古くなる** ⇒ build の外では bib key で書く。 2 版の PDF で番号が動いたら、 `.aux` の `\citation` の順で初出の位置を追うと原因が 1 行で分かる (実例: 脚注の引用を 1 つ消しただけで、 別の文献の番号が 9 繰り下がった。 誤りではなかった)。

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

## <a id="bibtex-name-doi-pitfalls"></a>refs.bib の姓と DOI の落とし穴

- **小文字の語を含むハイフンつきの姓** (`Ferrer-i-Cancho` の型): bibtex は小文字で始まる部分を von 部として読み、 姓が割れて `Ferrer-i Cancho` と出る (実測)。 姓をブレースで囲む: `author = {{Ferrer-i-Cancho}, Ramon}`
- **natbib の plainnat は `\doi{…}` を出す**: `url` パッケージ (か hyperref) を読んでいない文書では `\doi` が生の文字列になり、 DOI や URL に「_」 があると `! Missing $ inserted` で止まる (実測)。 natbib + plainnat 系の style で DOI を持つ bib を使う原稿は `\usepackage{url}` を読む
- **照合の年**: Crossref の `issued` は最初の公開の年で、 巻の年と 1 違うことがある。 照合の道具の側の扱い = [`web-tools.md#literature-search-apis`](web-tools.md#literature-search-apis)

## <a id="refs-bib-verification"></a>refs.bib 整備フロー（実物検証によるハルシネーション防止）

文献情報（著者・タイトル・巻号ページ）を refs.bib に追加する前に、次の優先順で**実物検証**する:

1. **PDF 実物が手元にある** → 直読して書誌情報を確定
2. **PDF 実物がない** → 同論文を引用している後発論文の参考文献欄で交差検証
3. **どちらも無い** → entry を作らない（推測で作らない）

**照合の道具**: entry を足した turn のうちに [`../scripts/inspire-bib-audit.py`](../scripts/inspire-bib-audit.py) を bib 全体に回す (INSPIRE 収録の文献は題・第一著者・誌・巻・初頁・DOI を突き合わせる)。 SKIP になったもの (graphics・CS の会議録・本) は手元の PDF の 1 頁目を読んで照合する。 ⚠️ 原稿の起草と同じ turn で文献をまとめて足すと、 本文の流れに気を取られて書誌を記憶で埋める (実測: 記憶で足した題のうち複数が別の題・別の名だった)。 起草中は key と arXiv / DOI だけを置き、 題と著者は道具か PDF から入れる。

**やってはいけないこと**:

- WebSearch の summary だけを根拠に entry を作る（summary は hallucinate する。[`web-tools.md` websearch-summary-hallucinates](web-tools.md#websearch-summary-hallucinates) 参照）
- 既存 refs.bib の entry を**検証せずに**信用する（共同編集者や過去の自分が誤同定している可能性。実例: 同名著者の別論文と取り違え、改訂版のタイトルを初版と混同 等）
- 似たキーワード・近い年代の論文を「これだろう」 と推測して埋める

**本 (教科書) の照合経路** (実測): 論文と違って DOI の registry が無いので、 出版社の商品頁 (著者・章題の一覧)、 Google Books (章題と開始頁)、 図書館の union catalog (出版地・頁数・series・ISBN・LCCN、 [`web-tools.md#cinii-library-holdings`](web-tools.md#cinii-library-holdings)) の 3 つを重ねる。 **章番号はどの情報源にも印字されないことがある** → 本文では章を題と開始頁で引く (「章 N」 と書かない)。 章の中身 (節題・式) は本を開かない限り未照合なので、 その本に帰属させるのは順序と題だけにし、 結果そのものは原典 (原論文・総説) に帰属させる。

**典型的な落とし穴**:

- Mandelbrot 1977 と 1982 で本のタイトルが違う（1977: *Fractals: Form, Chance, and Dimension* / 1982: *The Fractal Geometry of Nature*。同著者・近接年・関連内容で取り違いやすい）
- 同姓著者の別人（例: 「川上 紳一」 と「川上 智一」）
- 巻通しページと号内ページの混在（学会誌で 2 種の page number が併記される場合）

## <a id="jhep-bst-notation"></a>JHEP.bst 記法
JHEP.bst はフィールドから自動リンクを生成するので `\href` 手書き不要（二重リンクの原因）。
- `doi`: DOI 本体のみ（例: `10.1103/PhysRevA.61.012104`）
- `eprint`: arXiv ID のみ（例: `quant-ph/9905023`）。`archivePrefix = "arXiv"` と併用
- <a id="jhep-bst-no-braced-identifiers"></a>`doi`・`eprint` の値を波括弧で包まない (`doi = "{10.1103/…}"` の形): JHEP.bst は値をそのまま link の URL に入れるので、 波括弧が URL に残って開けない link になる (実測)。 組んだら PDF の link の URL に波括弧が残っていないかを見る (PyMuPDF なら `page.get_links()` の `uri`)
- `url`: doi や eprint があれば不要
- `note`: 自由テキスト。自動リンク対象外の補足情報に使う。 **全 entry で印字される**ので、 entry の内部の覚え書き (なぜ入れたか・どの note の比較対象か) は `annote` に書く (JHEP.bst は `annote` を読まない = 文献表に出ない)
- 欧文の著者を `"{Last, First}"` と括弧で包むと、 `F. Last` にならず「Last, First」 のまま出る = 欧文の著者は包まない (和文の著者を包む理由は [#japanese-authors-bibtex](#japanese-authors-bibtex))
- <a id="jhep-bst-japanese-books"></a>**和書・訳書**:
  - 題: JHEP.bst は題を `\emph` で組むので、 和文の題はゴシックの太字になり、 数字だけ斜体になる (実測)。 `title = "{\normalfont『題』}"` と『』で括って立てる
  - 叢書の番号を `number` に入れると「no.~75 in 叢書名」 と英語の形で出る → 和書は番号を `series = "{叢書名 75}"` に含める
  - 訳書: 原著と訳書は別の entry にして `\cite{原著,訳書}`。 訳書の `author` は原著者の表記 (和文なので括弧で包む)、 訳者は `note = "{訳者 訳}"`。 照合は国立国会図書館の書誌と CiNii Books の 2 つで (版・叢書・訳者・ISBN)

## <a id="jhep-future-citation"></a>JHEP.bst で future citation（in preparation、タイトル未定）を引く

執筆中の続編論文などを「著者 + in preparation」だけで引きたい（タイトル未確定なので入れない）場合の recipe（2026-07-13、Overleaf 共著 paper で確立）:

```bibtex
@unpublished{Author:2026prep,
    author = "Author, A. and friends",
    note = "{\unskip}, in preparation"
}
```

- **`@unpublished` を使う**。`@article` + `journal = "in preparation"` は workaround としては動くが、entry type の意味が誤り。また `@article` で journal を空にすると空 journal block の「`, .`」が残骸として render される
- **note 先頭の `{\unskip},`**: title が空だと bst が author と note の間の区切り（カンマ）を落とし「`friends in preparation`」と連結される。素の `", in preparation"` では今度は author block 末尾の space が残り「`friends , in`」になる。`{\unskip},` が前の space を潰してから comma を置く → 「`K.-y. Oda and friends, in preparation.`」
- bibtex の `Warning--empty title` は想定内（無害）
- **タイトル確定時**: `title = "{...}"` を追加し、note を素の `"in preparation"` に戻す（title があれば bst が区切りを正しく出すので `{\unskip},` hack は不要になる）
- 前提: note を render する版の JHEP.bst（[正本](#bibliography-style)）。stock JHEP.bst は note を落とすのでこの recipe 全体が silent no-op になる

## <a id="doi-table-from-registry"></a>ノートの文献表は DOI の登録記録から作り、同じ記録で照合し直す

md のノートに文献表 (著者・誌名・巻・頁・年 + DOI) を置くときも [#refs-bib-verification](#refs-bib-verification) と同じで、書誌を記憶から打たない。

- **作る**: DOI の一覧だけを手で持ち、表の行は Crossref (`https://api.crossref.org/works/<DOI>`) の記録から script で組む。記憶から打った DOI は別の論文を指すことがある (Elsevier の旧形式 `10.1016/0030-4018(87)90275-6` のような括弧つきは特に)。
- **照合し直す**: 表を直した後に、表の各行の DOI を引き直して巻・先頭頁 (または論文番号)・年を比べ、Crossref の第一著者と題を並べて出す検査を 1 本置く。数字が合うだけでは別論文を指していても通るので、著者と題は人が読む。
- **DOI は link の表示文字列から読む**: 括弧を含む DOI は URL 側で `%28` `%29` に直してあるので、検査は `[10.xxxx/...](https://doi.org/...)` の角括弧の中を DOI として取る。
- **Crossref に無い DOI がある**: 登録機関が別の DOI (国内学会誌の JaLC など) は Crossref が 404 を返す。「DOI が誤り」とは読まず、照合の外として別表に分ける。本・DOI の無い古い論文も同じ別表へ。
- **要求の header に個人のメールアドレスを入れない**: Crossref の「polite pool」は `mailto:` を勧めるが、使う人のアドレスを外部へ送ることになる。数百件までなら無くても通る。入れるなら本人に聞いてから。
- **読んだ深さを行ごとに書く**: 本文 / 要旨 / 二次資料 / 未読。書誌が合っていることと、中身を読んだことは別の主張。

## <a id="inspire-inbook-handbook-metadata"></a>INSPIRE の `@inbook` (Springer handbook の章) は booktitle・editor が空 — CrossRef の book 記録で補う (2026-09-13)

**症状**: INSPIRE の bibtex で取った handbook の章 (例: *Handbook of Quantum Gravity* の章、 DOI `10.1007/978-981-19-3079-9_21-1`) は `@inbook` に author・title・eprint・doi・year しか無く、 bibtex が `Warning--empty booktitle` を出し、 JHEP.bst は収録本を印字しない。

**処方**: 章 DOI の末尾 (`_21-1` 等) を落とした **book DOI** を CrossRef API で引き、 `booktitle`・`editor`・`publisher` を補う (推測で埋めない = [#refs-bib-verification](#refs-bib-verification))。

```bash
curl -s https://api.crossref.org/works/10.1007/978-981-19-3079-9 | python3 -c "import json,sys; m=json.load(sys.stdin)['message']; print(m['title'], [(e['given'], e['family']) for e in m.get('editor', [])], m['publisher'])"
```

- **`address` は足さない**: publisher 名が地名を含む (`Springer Nature Singapore`) と、 JHEP.bst は「(Singapore), Springer Nature Singapore」 と二重に印字する。
- **author 欄の list 全体を 1 組の括弧で包まない**: `author = "{Chkareuli, J.L. and Froggatt, C.D. and Nielsen, H.B.}"` は bibtex に 1 人の literal 名として渡り、 姓・名の順も `and` も生のまま印字される。 外側の括弧だけ外す (アクセント用の `{\'i}` などは残す)。 INSPIRE 以外の source から写した entry で起きやすい。
- 補った後は `.bbl` を開いて「in *Handbook …*, C. Bambi, L. Modesto and I. Shapiro, eds., Springer Nature Singapore (2024)」 の形になっていることを確かめる。

## <a id="hyperref-settings"></a>hyperref 設定
**新規 LaTeX ドキュメントは以下の hyperref 設定を使う:**
```latex
\usepackage[bookmarks=true,bookmarksnumbered=true,setpagesize=false]{hyperref}
```
- `\hypersetup{colorlinks=true}` は使わない。hyperref のデフォルト (`linkcolor=red`, `citecolor=green`, `urlcolor=magenta`) は赤緑紫がモトリーで見にくい。`allcolors=blue` で揃える手もあるが、印刷時にも色が乗るので避ける
- 上記 `[bookmarks=true,...]` 設定はリンク本文を黒のままにし、PDF annotation の薄い枠 (border box) のみ追加する。枠表示は viewer 依存（Preview/Adobe では薄く表示、印刷では非表示）
- 完全に枠も色も無くしたい場合は `\hypersetup{hidelinks}` を追加
- 既存の `\hypersetup{colorlinks=true}` がある場合はリンク色を改善するため上記に migrate する

<a id="hyperref-publish-only"></a>**紙で読む本の原稿は、 執筆中は hyperref を切り、 画面で配る版だけに入れる手がある**: 刷った本の読者はリンクもしおりも使わない。 切り替えは preamble で `\ifdefined\<名前>` のときだけ hyperref を読み、 配る版を組む make の target が写しの入口の頭にその `\def` を足して組む (repo 直下の PDF と latexmk の記録を変えない)。 hyperref を外すと、 hyperref が黙って隠していたものが出る:

- `\texorpdfstring` が未定義になる → 外した側で `\providecommand{\texorpdfstring}[2]{#1}`。 `\nameref` は `nameref` パッケージ単体で使える。
- hyperref ありで組んでいた頃の索引 (`.ind`) に `\hyperpage{…}` が残り、 最初の組版が `Undefined control sequence` で止まる → `\providecommand{\hyperpage}[1]{#1}` を置く (latexmk は止まった回の後に索引を作り直さないことがある = 実測。 そのときは写しの `.ind` と `.fdb_latexmk` を消して組み直す)。
- <a id="jsclasses-footnote-leading-space"></a>**jsclasses / ltjsclasses の脚注の頭に空白が残る**: このクラスは `\footnote{…}` の中身を引数でなく `{` からのかたまりとして読む (`\verb` を使えるように。 `\jsc@f@@t` が `\let` で `{` を取る) ので、 `\footnote{` の直後の改行が空白になり、 番号と本文の間が少し広がる。 hyperref は脚注を引数で読み直すので、 この空白を消していた (実測 = hyperref を外したら脚注のある頁だけ見た目が変わった)。 外した側で `\def\jsc@f@@t{\bgroup\aftergroup\jsc@@foot\afterassignment\ignorespaces\let\jsc@next}`。 hyperref ありとなしで段落の頭の node を書き出して比べると見つかる (`pre_linebreak_filter` で、 glue の subtype 13 = ソースの空白)。
- **確かめ方**: 同じ原稿の写しから両方の版を組み、 頁の画素を比べる ([`compare-tex-builds.py --pixels`](../../ai-collaboration/scripts/compare-tex-builds.py)、 リンクの枠は描かれない)。 違いがリンクとしおりの有無だけかは PyMuPDF で数える (`sum(len(p.get_links()) for p in doc)`、 `len(doc.get_toc())`)。 PDF の byte を `/Link` で grep すると、 LuaTeX は object を圧縮した stream に入れるので 0 になる (実測)。 著者が原稿を書き進めている repo では、 時間をおいて組んだ 2 つの PDF の差に原稿の変更が混ざるので、 両方を同じ写しから続けて組む。
- <a id="hyperref-unlink-equations-only"></a>**全部は切らず、 式へのリンクだけ外す手**: しおりと章・図などへのリンクは残し、 式の番号だけをリンクにしない。 hyperref の `\Hy@setref@link#1#2#3#4#5#6\@nil#7` (引数 = 番号・頁・題・anchor・file、 `#7` = どれを出すか) を包み、 anchor 名 (`#4`) が `equation.` で始まるときは `#7{#1}{#2}{#3}{#4}{#5}` だけを出す。 anchor 名がほかの名前のときは、 元の macro に引数を括弧で包み直して渡す (包み直さないと 2 字以上の番号が割れる)。 `\eqref` だけを `\ref*` に直す形だと、 `\ref` で式を指した所が残る。 hyperref の内部の macro なので、 版を上げたら式のリンクの数を数え直す。 hyperref を外さないので、 上の 3 つの罠は出ない。

## <a id="pre-commit-hook"></a>pre-commit hook（Unicode→LaTeX 自動修正）
`setup.sh` が **全リポに自動インストール** (Step 6)。 hook 自体が staged file 中の `.tex/.bib/.bst/.cls/.sty` の有無を判定し、 LaTeX file 不在の repo では no-op で exit 0 (`scripts/pre-commit-bib` L31-35)。 よって LaTeX file 検出は install 時に不要、 全 repo install で robust。

手動確認・インストール:
```bash
# 確認: .git/hooks/pre-commit が pre-commit-bib を指しているか (repo が自前の hook を持つなら、 その hook が pre-commit-bib を呼んでいるか)
ls -la .git/hooks/pre-commit
# インストール (setup.sh が走らなかった repo の retroactive fix。 既存の hook は置き換えない):
bash ~/Claude/claude-config/scripts/install-precommit-bib.sh .
```

⚠️ **repo が自前の pre-commit (検査 gate) を持つときは、 その hook の中から pre-commit-bib を呼ぶ** (例: `BIBFIX="$HOME/Claude/claude-config/scripts/pre-commit-bib"; if [ -x "$BIBFIX" ]; then "$BIBFIX"; fi`)。 Step 6 は repo が管理する hook を置き換えず、 chain の有無を表示するだけ (2026-09-16 まで Step 6 は repo の hook を pre-commit-bib で置き換えていた = [`hook-authoring.md#installer-tracked-stub`](hook-authoring.md#installer-tracked-stub))。

ステージされた `.tex`/`.bib` 等の非 LaTeX 文字（Unicode 引用符、ダッシュ等）を自動でLaTeXコマンドに変換する。 具体例:

- `—` (Unicode em-dash U+2014) → `---` (LaTeX em-dash command)
- `–` (Unicode en-dash U+2013) → `--`
- `"..."` (Unicode smart quotes) → `` ``...'' ``
- `ö` 等 Unicode 西欧文字 → `{\"o}` 等の LaTeX accent command

**Claude への規律**: `.tex/.bib` を新規作成・編集する前に本 convention を読むこと。 Markdown 流儀で literal `—` を直書きすると LaTeX で正しく render されない (Unicode em-dash は通常の LaTeX font に欠落することが多い)。 hook が機械的に catch するが、 hook 未 install repo では catch されない (= 2026-05-14 個人層 private repo の深い path で発生、 RCA は `claude-config/DESIGN.md`)。

<a id="fontspec-textendash"></a>⚠️ **LuaLaTeX / XeLaTeX で `\newfontfamily` で読んだ字体には TeX の合字が付かない = その字体で `--` を使うなら `\newfontfamily\X[Ligatures=TeX]{…}` と付け、 付けないなら `\textendash` / `\textemdash` を書く**: hook は `–` を `--` に書き換えるが、 `--` を en dash にするのは字体の `Ligatures=TeX` で、 fontspec は `\setmainfont` / `\setsansfont` には既定で付けるのに `\newfontfamily` には付けない。 その字体の中の `--` は 2 本のハイフンのまま組まれる (実測: 大きな数字の指数の負号が「--36」 になった)。 build は通るので、 PDF を画像にして見るか文字を抽出して `--` を探す。 曲引用符も同じ (hook が書く ``` `` ''``` が字のまま出る)。

<a id="generated-tex-opt-out"></a>⚠️ **テンプレートに値を流し込んで `.tex` を書き出す道具 (ポスター・様式など) では、 書き出した `.tex` を hook から外す** (`.gitattributes` に `<出力の path> -latex-autofix` = [`#vendored-latex-opt-out`](#vendored-latex-opt-out))。 正本は道具に流し込む data の側で、 PDF は hook が書き換える前の `.tex` から組まれる。 書き換わるのは commit した `.tex` だけなので、 その `.tex` を組み直したときに初めて `--` が刷られる = build の検査では見えない (実測: 英語の題の en dash)。 hook の書き換えを道具の側で先回りして真似る形にはしない (hook が書き換える字 = dash・曲引用符・アクセントを道具が追いかけ続けることになる)。 道具の側で字を直すのは、 hook に依らず正しく組まれるようにするとき (xeCJK の文書の欧文の欄 = 次項) だけ。 外した後は、 道具の test で「出力の path に行が当たる」 と「本物の hook で commit しても字が残る」 を確かめ、 出力の PDF の文字に `--` / ``` `` ``` / `''` が残っていたら止める。

<a id="xecjk-latin-punctuation"></a>⚠️ **xeCJK を読む文書の欧文だけの行に、 Unicode の `–` `—` `“` `”` `‘` `’` を書かない**: xeCJK はこれらを和文の字として扱い、 和文の字体で組んで隣の空白を消す (架空の例: 「WAVES —A STUDY」「‘INSIDE’VIEW」。 実測)。 build は通り、 抽出した文字列もほぼ正しく見えるので、 PDF の span の字体を見ないと気づかない。 欧文の行は `Ligatures=TeX` を付けた字体で `--` / `---` / ``` `` ''``` / `` ` `` / `'` と書く (前々項)。 値を流し込む道具なら、 欧文の欄の値だけ Unicode をこの入力に直して書き出す (数式の中は除く。 和文の欄の `—` は和文の字のままがよい)。 字間を空けた (`LetterSpace`) 字体では、 `{--}` や `\textendash` の境目で字間が切れてダッシュの片側が詰まるので、 包まない `--` が最も揃う (包むのは隣の `-` `` ` `` `'` とつながるときだけ)。 検査は PDF の行ごとに、 欧文の字体の span と、 ダッシュ・引用符だけの和文の字体の span が同じ行に並んでいないかを見る (抽出すると和文の字体の `–` は `‒`、 `—` は結合文字 U+0336 になることがある)。 和文の欄の中でも、 欧文の語どうしをつなぐダッシュ (欧文の人名を連ねた固有名など) は欧文の字として `--` で書く (和文の字体で組まれて抽出で `‒` になり、 題目を正本と照合する検査に落ちた。 実測)。

<a id="cjk-font-weight-glyph-coverage"></a>⚠️ **和文の字体は太さごとに持っている字が違う。 常用の外の字や簡体字を含む人名・固有名を組む前に、 使う太さにその字があるかを確かめる**: 同じ書体の家族でも、 細い太さに入っている字が太い太さには無いことがあり、 簡体字は日本語の字体のどの太さにも無いことがある (実測: 見出し用の一番太い太さにだけ字が無く、 一段細い太さでは組めた)。 xelatex・lualatex は字体に無い字を `Missing character: There is no … in font …` と log に書くだけで error にせず、 PDF ではその字が黙って抜ける (build も、 抽出した文字列を正本と照合する検査も通ることがある)。 確かめ方 = `fc-list ":charset=<16 進の符号位置>" family style` で、 その字を持つ字体と太さを出す (書体名で grep するときは、 同じ名前で始まる別の言語用の字体を数えないよう、 家族名を行頭から当てる)。 対処 = その欄だけ字のある太さか字体で組む。 人名の表記そのもの (本人の字か日本の字体か) は本人か owner が決める ([`name-rendering.md#cjk-names-in-japanese-print`](name-rendering.md#cjk-names-in-japanese-print))。 値を流し込んで組む道具は、 組んだ後に log の `Missing character` を拾って 1 件でもあれば止める (入れる前に、 既存の出力を組み直して 0 件であることを確かめると、 入れた瞬間に過去の出力が止まらない)。

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
- ⚠️ opt-out は「自動 fix からの保護」 であって「自分が書く新規 .tex でアクセント直書き OK」 ではない。 外すのは、 正本が別にあって `.tex` を手で書かない file だけ = vendored の取り込み・機械が作り直す照合の基準 ([`#md-tex-source-and-copy`](#md-tex-source-and-copy))・道具が書き出す `.tex` ([`#generated-tex-opt-out`](#generated-tex-opt-out))。
- <a id="autofix-with-pathspec-commit"></a>⚠️ **`git commit -- <path>` (並列 session 対策の pathspec commit) と自動 fix**: pathspec commit は一時の index で commit するので、 hook が直して `git add` しても、 commit の後に main の index へ直す前の版が書き戻される (`git status` が `MM`、 実測)。 この状態は 2 つの害を持つ: path を付けない次の `git commit` は直す前の版を commit して直しを黙って戻す。 並列の session はこの `MM` を他人の書きかけと読む (実測: 別の agent が「並行 session の未 commit の編集」 と記録した)。 そこで hook は、 pathspec commit (hook が見る `GIT_INDEX_FILE` の file 名が `next-index-*.lock`) で文字を直したときは作業木だけを直して commit を止め、 「pathspec commit — stopped so that the main index does not keep the pre-fix version. Run the same commit again」 と出す = **同じ commit をそのまま打ち直す** (直す文字はもう無いので通り、 index・作業木・HEAD が揃う)。 普通の commit・`-a`・`--include` (`index.lock`) は直して re-stage して通る (hook は「auto-fixed non-LaTeX characters and re-staged」 と出す。 main の index に古い版は残らない)。 警告を出して読んだ側が手で揃える形にしなかったのは、 その 1 手が打たれずに `MM` が残ったため (実測)。 この判定より前の hook の写し (copy で置いた環境) で `MM` が残ったら、 `git diff HEAD -- <path>` が空なら `git restore --staged <path>` で index を HEAD に揃え、 空でなければ同じ path でもう一度 commit する。 fix が掛かった file を別の検査の基準にしているなら、 その検査を回し直す。
- <a id="autofix-generated-tex"></a>⚠️ **生成器が書く .tex に自動 fix が掛かったら、 生成器の側を fix の後の形に直す** (実測): commit されるのは fix の後の .tex で、 生成器は次の実行で fix の前の形 (例 = em dash `—` U+2014) を書き直すので、 commit と生成器の出力が毎回ずれる (生成器を回すたびに作業ツリーが dirty になり、 commit のたびに同じ fix が掛かる)。 hook が「auto-fixed」 と言ったら、 生成器を回し直して commit 済みの .tex と diff を取り、 差の文字を生成器の source で fix の後の形 (`---` など) に書き換えて、 diff が 0 になるのを確かめる

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

**過去の事故 + 判断経緯**: 個人層 LaTeX project の lecture draft で当初 (a) U+2500 doubled を使用、 5/15 セッションで Claude が「uplatex + okumacro が日本語横罫線として render する」 と verify なし主張、 user の「これ本当?」 で実物 verify、 (b) `---` に一旦切替するも user が日本語典籍の見た目を考慮し直して (c) `------` に再切替で着地。 okumacro は実際には U+2500 の render に関与しておらず、 単に uplatex default の日本語 font が U+2500 を box-drawing glyph で render するだけだった (= Claude の typographic 主張は実物 verify なしには信用しない、 詳細規律は個人層 work-discipline-archive.md §「Typographic / rendering claim は実物 verify なしに主張しない」)。

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
- chat 上で**読ませるだけ**の数式（コピペ不要）は別軸 — 書き方は返事を読む画面で決まる (desktop の Code タブ = KaTeX の規則で LaTeX / CLI のターミナル・画面が決まらないとき = Unicode 添字・上付き)。 正本 = [chat-math-rendering.md](chat-math-rendering.md)

## <a id="md-math-preview"></a>数式入りの Markdown を人に見せるときは HTML にして browser で開く (右パネルは数式を描かない)

Claude Code の desktop app の右パネルは、 Markdown の中の TeX 数式 (`\( \)` / `\[ \]` / `$ $`) を描かず、 source のまま表示する。 数式を含む設計ノートや試稿の `.md` を link で渡しても、 読む側には式が読めない。

- 対策: [`scripts/preview-md-math.sh`](../scripts/preview-md-math.sh) で MathJax つきの HTML に変換して browser で開く (pandoc が必要。 出力は repo の `build/preview/` で、 git の管理外に置く)。
- 変換した HTML はその時点の写しで、 `.md` を直しても更新されない。 **`.md` を編集した turn では、 変換し直してから見せる** (人に「もう一度実行して」 と頼まない。 repo の指示 file に「見せるとき・直したときは Claude が変換する」 と 1 行書いておくと、 次の session にも伝わる)。
- MathJax は CDN から読むので、 offline では数式が描かれない。
- `.tex` の原稿は対象外 (PDF を組んで見せる)。

## <a id="md-tex-source-and-copy"></a>同じノートを Markdown と TeX の両方で持つときは、 片方を正本、 片方を写しにする

数式の多い Markdown のノートを TeX でも組みたくなることがある (本の preamble で読みたい、 式を原稿へ持っていきたい)。 そのとき二つとも直せる状態に置くと、 片方だけを直した時点から黙ってずれる (一般則 = [`docs/convention-design-principles.md#no-duplicate-rules`](../docs/convention-design-principles.md#no-duplicate-rules))。 作った turn に、 どちらが正本でどちらが写しかを決めて、 両方の頭に書く。

**どちらを正本にするかは「これから誰が直すか」 で決める。**

| これから直すのは | 正本 | 理由 |
|---|---|---|
| AI (調査の材料・設計のノート・AI が書いて AI が更新する文書) | md | AI は md のほうが速く確実に直せる。 diff が読める。 chat から link で開ける。 TeX の写しは読むためと式を持ち出すための参照 |
| 著者 (原稿・章・著者が 1 文ずつ裁定する文章) | tex | 著者が自分の editor と自分の macro で直す。 md は試稿として凍結し、 以後は直さない |

迷ったら、 次に直すのが誰かを著者に 1 行で聞く。 「両方を正本にして同期する」 は選ばない (双方向の同期は、 どちらの変更が新しいかを誰も判定できなくなる)。

**写しの作り方 — 機械でできる所は機械で、 生成になる所は照合する。**

1. **構造は機械で**: 見出し・表・箇条書き・リンクは pandoc に任せる。 [`scripts/md-note-to-tex.py`](../scripts/md-note-to-tex.py) が節ごとの骨格 (`raw/sec-NN.tex`) を作る。 骨格は照合の基準なので手で直さない。
2. **数式は生成になる**: md の数式が Unicode の地の文 (`P₁`、 `α ≥ 1`、 `|n⟩⟨n|`) で書いてあると、 TeX に直す作業は規則で書き切れず、 人か worker が読んで書くことになる。 これは転記ではなく生成で、 語の置換や数値の書き換えが申告なしに混じりうる (同じ性質 = [`photographed-document-transcription.md#quotation-extraction`](photographed-document-transcription.md#quotation-extraction))。 仕様に「文は一字も変えない。 分からない式は見たままにして注を付ける」 と書き、 直した節を骨格と機械で突き合わせる。
3. **照合**: [`scripts/check-md-tex-copy.py`](../scripts/check-md-tex-copy.py) が、 日本語の字・数字・4 字以上の英字の語の並びを骨格と比べる。 worker に渡すなら、 worker 自身にこの検査を回させて ✓ になるまで直させる (節ごとに別 context に分けると、 1 本の出力が長くなりすぎない)。
   - worker に渡す仕様に書くこと: 割り当ての file と「ほかは触らない・git は操作しない」 / 文は一字も変えない (言い換え・要約・追加・削除・並べ替えの禁止を列挙) / 記号の書き方は写し先の macro と既存の本文に合わせる (見本の file を名指す) / 数式にするものとしないものの線引きを例で (ただの数・人名・単位つきの値) / 曖昧な式は見たままにして `% TODO` の注を付ける (検査はコメントを見ない) / 報告の形 (作った file・検査の結果・注を付けた箇所・正本の式そのものが怪しい箇所は直さずに報告)。 最後の項目は、 写しを作る作業が正本の通読を兼ねるので、 正本の側の直し候補が副産物として集まる。
4. **検査が見ないものを言う**: この照合は数式の意味を見ない (記号の取り違え、 上付きと下付きの取り違え)。 意味は組んだ PDF を読んで確かめる。 報告には「文の一致は全節、 式の意味は目視した範囲」 と範囲を分けて書く。

**写しの鮮度は機械で見る。 人に「あとで反映して」 を残さない** ([`#human-memory-not-a-carrier`](../docs/convention-design-principles.md#human-memory-not-a-carrier))。 `check-md-tex-copy.py DIR --source NOTE.md` は、 正本から骨格を作り直して保存してある骨格と比べ、 違う節を「写しが古い」 と出す。 これを session の開始や CI で回る検査に入れておくと、 md だけを直した次の機会に出る。 正本を直した turn で写しも直すのが既定で、 検査はその取りこぼしの網である。 repo には手順を 3 行で書いておく (骨格を作り直す → 変わった節の写しを直す → 検査して組む)。

**実測した壊れ方** (照合の述語と周りの仕掛け):

- **数は「数字 1 字ずつ」 で比べる**。 数の単位で比べると、 `p₁²` は骨格では `12` と続き、 正しい TeX の `p_1^2` では `1` と `2` に割れるので、 正しく直した節が不一致になる。 `10³` も同じ。
- **命令名だけでなく環境名も語から外す**。 骨格の `\begin{pmatrix}` を家風の `\pmat{}` に直すと、 語 `pmatrix` の数が変わる。
- **欧文のアクセントは書き方を問わず同じ字とみなす** (`é` / `\'e` / `{\'e}`)。 pre-commit の Unicode 自動修正が後から書き方を変える。
- **骨格は Unicode の自動修正から外す**。 自動修正 hook が骨格の `φ` を `$\varphi$` などに書き換えると、 骨格を作り直すたびに差分が出て、 鮮度の検査が意味を失う。 `.gitattributes` に `<dir>/raw/** -latex-autofix` を書く (opt-out の機構 = [`#vendored-latex-opt-out`](#vendored-latex-opt-out))。
- **文字で描いた図は組めない**。 `verbatim` の中の罫線の字と和文は等幅にならず、 桁が揃わない。 同じ中身の TikZ の図に差し替え、 照合からは `verbatim` と `\input` の行を外す。
- **md に写しへの案内を 1 行足すと、 それも正本の変更である**。 骨格を作り直してから commit する (直さないと、 最初の鮮度の検査で自分の変更が出る)。

## <a id="built-pdf-phone-sync"></a>組んだ PDF の最新版を同期フォルダの 1 か所へ写す (携帯で常に読めるように)

原稿やノートの PDF は repo ごとに散らばっていて、 携帯からは読めない。 (読むために PDF を build のたびに commit する代わりにもなる = 差分の効かない版は毎回まるごと履歴に積まれる、 [`repo-history-growth.md#generated-binaries`](repo-history-growth.md#generated-binaries)。 git から外した = ignore した PDF も写し、 設定の build 規則があれば、 共同編集者が source だけ push した文書を写す前に組み直す。 共同編集者と共有フォルダでやりとりする仕組みは同節。) [`scripts/sync-built-pdfs.py`](../scripts/sync-built-pdfs.py) が、 作業 dir の下の全 repo から「同じ場所に同じ名前の `.tex` がある PDF」 を見つけて、 同期フォルダ (Dropbox 等) の `<repo>/<名前>.pdf` へ写す。 設計の判断は次のとおり (細部は script の冒頭)。

- **対象の一覧を人が書かない**。 新しいノートを組めば、 登録なしで次の回から写る (人が育てる一覧は育たない = [`docs/convention-design-principles.md#detector-config-must-be-derived`](../docs/convention-design-principles.md#detector-config-must-be-derived))。 絞るのは除外の側で、 保管庫の dir (archive / old / submissions など) と、 直近 N 日に commit も変更も無い PDF を外す。 一度写したものは、 その後も更新し続ける。
- **暗号化している PDF は写さない** (git-crypt の filter が付いた path)。 復号した写しを repo の外に置くと、 暗号化で守っていた範囲が黙って広がる。 携帯で読みたいものが暗号化の側にあるときは、 写すかどうかを持ち主が決める。
- **発火は AI のターンの終わり (Stop hook、 背景で実行、 出力なし)**。 PDF はほぼ AI のターンの中で組まれるので、 組んだ直後に写る。 macOS の launchd の定期実行にしないのは、 launchd の process が同期フォルダ (`~/Library/CloudStorage/`) に書けないため ([`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md))。 残る隙間 = 人が editor で組んだ分は、 次の AI のターンの終わりまで写らない。 同じ hook を session の開始にも配線しておくと、 ターンの終わりの hook が走らない環境でも次の session で追いつく (出力の無い hook なので、 開始時の注入は増えない)。 hook には実走の印 (時刻を 1 行書く file) を持たせる。 副作用だけの hook は、 走っていなくても誰も気づかない。
- **複数のマシンが同じ写し先に書く前提で、 上書きは「中身が違う ∧ 元のほうが新しい」 ときだけ**。 pull の遅れたマシンが古い PDF で新しい写しを上書きしない。 同じ理由で、 写し先の PDF を自動では消さない (別のマシンにまだ無い PDF を消してしまう)。 整理は `--prune-report` の一覧を見て人が決める。
- **`main.pdf` のような名前は、 写すときに意味のある dir 名か repo 名に付け替える** (携帯の一覧で `main.pdf` が並んでも選べない)。
- **親の repo が ignore している入れ子の clone (Overleaf の clone など) も見る**。 共著の原稿の本体がそこにあることが多い。

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

## <a id="latex-pdf-audit"></a>LaTeX log と PDF の検査を再利用する

LuaLaTeX が sandbox 内で `no writeable cache path` を報告し、その後に大量の `nullfont` / missing-character 警告を出す場合は、まず最初の fontloader エラーを調べる。書込み可能な TeX キャッシュを指定するか、必要なキャッシュへの限定された実行権限で再ビルドする。後続の文字欠落を一文字ずつ原稿側で直さない。失敗時に PDF ファイルが生成されても正常な成果物とは扱わず、再ビルド後に log と PDF を同じ組で検査する。

反復する log 集計、PDF 全フォント検査、確認頁のレンダリングには [latex-pdf-audit.py](../scripts/latex-pdf-audit.py) を使う。既存の [印刷 preflight](../scripts/pdf-print-preflight.py) はプリンタ向けの別契約であり、この検査は印刷忠実度を判定しない。

```sh
python3 scripts/latex-pdf-audit.py paper.pdf --log paper.log --source paper.tex --json
python3 scripts/latex-pdf-audit.py paper.pdf --log paper.log --render-dir review-pages --pages 2,4-6
```

検査項目・exit code・CLI の正本は script の docstring と `--help`。入力不在を成功扱いせず、従来の `!` error と `-file-line-error` 形式を確認する。参照未解決、missing glyph、Type 3、未完了 log、rerun 要求を検出し、overfull は既定で報告のみとする。`--source` の鮮度判定は明示された file の mtime 比較であり、正しい source から生成された証明ではない。

出力の `visual_review: not_assessed` は画像を検査したという意味ではなく、画像確認の要否も判定しない。要否は下記の成果物別の範囲で決める。画像確認を行う場合は生成された PNG を開いて確認する。既存 PNG を上書きしないため、再検査時は新しい出力 directory を指定する。

### <a id="redistribute-old-pdf"></a>昔組んだ PDF を配り直す前に、 未解決の参照が無いかを本文で見る

過去の講義ノート等を「前の版をとりあえず」 と配るとき、 log が残っていなければ上の audit は回せない。 PDF の本文テキストに **`[?`** (未解決の引用) や **`??`** (未解決の相互参照) が無いかを探す (PyMuPDF の `get_text()` で全頁を連結して検索すれば足りる)。 文献処理 (bibtex) を回さずに書き出した PDF は、 引用が全部 `[?,?]` で参考文献の頁も無い形になり、 見た目では気づきにくい (実測)。

- 見つかったら source を複製して文献処理込みで組み直す (`latexmk` が bibtex まで回す。 pTeX 系 class なら `latexmk -pdfdvi -latex='platex -interaction=nonstopmode -halt-on-error %O %S' -e '$dvipdf=q/dvipdfmx %O -o %D %S/'`)
- 組み直した版と前の版は、 空白を除いたテキストを比べ、 引用番号 (`[?]` ↔ `[1,2]`) を正規化すれば一致することを確かめる。 残る差が目次の頁番号だけなら本文は同じ (TeX の版が違うと頁割りが動く、 実測)
- 配った先の file を差し替える手順は配布先による (Classroom の添付なら [`google-classroom-api.md#replace-attachment-in-place`](google-classroom-api.md#replace-attachment-in-place))

### <a id="visual-verification-intensity"></a>成果物の種類で視覚検査の強度を分ける

**論文・ノートの通常編集**では、ビルド、参照、変更した数式・論理を検査し、必要に応じて font を確認する。ページ画像化・目視照合・pixel 比較は既定の完了条件にしない。図や組版自体を変更するとき、レイアウト不具合が疑われるとき、または著者が求めたときだけ必要なページを画像で確認する。固定様式向けの検査を一律適用しない。

**既存様式への記入**（申請書、Word/Excel/PDF template、帳票、overlay）では、欄・罫線・改頁・既存文字を動かしていないこと自体が受入条件なので、基準版との pixel 比較を使う。論文でも renderer・font・生成経路の移行後に版面同値性を証明する場合、または並行生成で PDF の出所が不明になり同じ source の二つの出力を照合する場合に限り、全ページ比較を追加してよい。通常の source/PDF 対応は隔離ビルド、入力 hash、完了した log で確立し、全ページ画像比較を代用にしない。

origin: 論文の通常改稿で固定様式向けの全ページ画像照合を流用し、検査が過剰になった事例から区別を明文化。


## <a id="scratch-build-dir"></a>別 dir で組版するとき、生成物を原稿 dir へ symlink しない

原稿を触らずに組版だけ別 dir でやる定型は「原稿 dir の中身を symlink して `.tex` だけ copy する」だが、**symlink の対象から build 生成物 (`.aux` `.log` `.pdf` `.bbl` `.blg` `.out` `.toc` `.synctex.gz` `.fls` `.fdb_latexmk`) を必ず除く**。除かないと `pdflatex` が symlink 越しに書き戻し、原稿 dir の生成物を毎回上書きする。図・bst・bib・画像だけを symlink する。

被害は 2 つある。① 著者が editor (TeXShop / Overleaf のローカル clone 等) で見ている PDF が、こちらの組版のたびに差し替わる。② 著者の typeset と組版が重なると、書きかけの `.aux` を読んで**自分の gate が偽の error を報告する** (`! File ended while scanning use of \@newl@bel.` + 未定義参照が全件並ぶ)。この error は原稿ではなく競合の像なので、原稿を直しても消えない。

```sh
for f in "$SRC"/*; do bn=$(basename "$f")
  case "$bn" in paper.tex|*.aux|*.log|*.pdf|*.bbl|*.blg|*.out|*.toc|*.synctex.gz|*.fls|*.fdb_latexmk) continue;; esac
  ln -s "$f" "$BUILD/$bn"
done
cp "$SRC/paper.tex" "$BUILD/"
```

gate が上のような error を出したら、原稿を疑う前に **同じ組版をもう一度走らせる**。1 回で消えるなら競合、消えなければ原稿。

origin: 2026-09-12 或る paper repo、著者が TeXShop で編集中の Overleaf clone を組版 dir から symlink し、`paper.aux` / `paper.pdf` を上書きしていた。競合した 1 回だけ gate が `errors: 1` と未定義参照 474 件を報告した (原稿は無傷)。


## <a id="pdf-visual-verification"></a>図・組版を対象とする PDF 視覚検証

図・組版の修正ではコンパイル成功だけで配置の正しさは分からない。[成果物別の範囲](#visual-verification-intensity)で画像確認が必要な場合に以下を使う。通常の本文・数式編集に毎回適用しない:

1. `pdflatex -interaction=nonstopmode FILE.tex 2>&1 | grep -iE "^! |Overfull"` — fatal error + overflow warning を確認（platex DVI workflow なら `platex ... ; dvipdfmx ...` の各段で同 grep）
   - ⚠️ **`grep undefined` だけで済ませない**: `^!` (TeX error) は `Double subscript`・`Missing $` 等で出るが、TeX は recover して PDF を出すため「undefined 参照ゼロ」だけ見ると error を見逃す（例: `\newcommand{\X}{Y_{\rm z}}` を `\X_{...}` と使う double-subscript は PDF が出ても下付きが壊れる）。**必ず `^!` を grep** し、`error 0` を確認する。
2. `python3 -c "import fitz; doc=fitz.open('FILE.pdf'); pix=doc[N].get_pixmap(dpi=200); pix.save('/tmp/check.png')"` — 該当 page を PNG 化
3. `/tmp/check.png` を Read tool で開いて **視覚確認** (= 「compile OK」 だけで完了としない)
4. 図・組版の確認対象に `Overfull \hbox (N pt too wide)` warning が出たら、該当 page で切れを確認。 ⚠️ ただし共著原稿の改稿 pass の**途中**では overfull を語順変更で消さない — 改行位置は後続の編集で動くので、 掃除は投稿直前の final pass で 1 回 (正本 = ai-collaboration [`edit-intent-record.md#overfull-not-a-gate`](../../ai-collaboration/conventions/edit-intent-record.md#overfull-not-a-gate)、 2026-09-09 著者裁定)

### <a id="pdf-visual-verification-traps"></a>典型 trap (= 2026-05-18 研究ノート編集で連続再発)

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

## <a id="texshop-lualatex-and-external-builds"></a>TeXShop で LuaLaTeX 前提の source を開く・外部の build と共存させる

- **LuaLaTeX でしか組めない source (ltjsarticle、 fontspec、 LuaTeX-ja) は先頭に `% !TEX TS-program = lualatex` を書く** (`% !TEX encoding = UTF-8 Unicode` も)。 無いと TeXShop は既定の engine (pdfTeX / uplatex の経路) で typeset してエラーで止まり、 著者には「コンパイル結果が見えない」 になる (実測)。 この行は file を開いた時に読まれるので、 開いたままの文書には効かない = 閉じて開き直す。
- **tex に紐づいたプレビュー窓は、 その PDF を外部の build (CLI の lualatex・build script) が書き換えると描画しなくなることがある** (ページ番号は出るのに紙が灰色のまま。 ⌘W → ⌘T の再 typeset・ページ送り・表示形式の切替・ズームでは戻らない、 実測)。 PDF 自体は正常で、 **同じ PDF を独立の書類として開く** (ファイル > 開く、 または `open -a TeXShop <pdf>`) と描画する。 壊れた窓は TeXShop の再起動で消える。 外から組むときは、 著者に「開き直して」 と伝えるか、 TeXShop 側の typeset だけで組む ([#scratch-build-dir](#scratch-build-dir) の aux の競合とは別の症状)。

## <a id="write-while-author-has-it-open"></a>著者が editor で開いている原稿に書き込む

著者が自分の buffer を持つ editor (TeXShop など) で原稿を開いている間に disk の file を書き換えると、 editor が読み直さない限り、 著者の次の保存がこちらの変更を消す (editor が「別のアプリが変更した」 と確かめる場合も、 上書きを選べば同じ)。 著者が通読しながら直している最中に、 同じ file を直すときの手順:

1. 作業は写しでする。 書き込みは最後の 1 回にまとめる (書くたびに著者の画面とずれる)。 写しの検査は写しのまま回す (数式・引用・数値の不変量 = [`scripts/tex-prose-pass-invariants.py`](../scripts/tex-prose-pass-invariants.py) `--head-file <写し>`)。
2. 書く直前に、 著者の保存した変更が disk にあるかを見る。 `git diff -- <file>` が空でなければ、 写しを作った時の版 (base)・著者の版・こちらの版を 3-way merge する (`git merge-file <こちら> <base> <著者>`)。 著者の変更 (段落の区切り・1 語の直し) は残す。
3. 書いたらすぐ、 著者に「disk の版を読み直してから続けて」 と頼む (閉じて開き直すのが確実)。 読み直す前に打った文字は失われるので、 書く前に一言かけられるならかける。
4. 著者が自分で入れた変更は、 著者の言葉を添えて別の commit にする (こちらの直しと混ぜない = どちらの変更かが履歴で分かる)。

## <a id="texshop-engines"></a><a id="texshop-uplatex-engine"></a>TeXShop の engine で原稿を組む (latexmk-lualatex / uplatex)

[`texshop/`](../texshop/) に TeXShop の engine を置いている。 原稿は先頭の `% !TEX TS-program = <engine の名前>` で選ぶ。

| engine | 何をするか | 向く原稿 |
|---|---|---|
| [`latexmk-lualatex`](../texshop/latexmk-lualatex.engine) | `latexmk -lualatex` で必要な回数だけ組み、 文献と索引も回す。 PDF を直接出す。 文献・索引の道具は原稿の dir の `.latexmkrc` で選ぶ (日本語なら `$bibtex = 'upbibtex %O %S'` と `$makeindex = 'upmendex %O -o %D %S'`) | LuaLaTeX の原稿 (ltjsbook / ltjsarticle、 LuaTeX-ja) |
| [`uplatex`](../texshop/uplatex.engine) | `ptex2pdf -l -u` (uplatex + dvipdfmx) を 3 回、 間に upbibtex と mendex | jsbook / jsarticle に `uplatex` option を付けた原稿 |

- **入れ方**: `bash scripts/install-texshop-engines.sh` が `texshop/*.engine` を `~/Library/TeXShop/Engines/` に symlink する (無ければ足すだけ、 本人の同名の file は触らない、 TeXShop を 1 度も起動していない機では何もしない)。 setup.sh (macOS) が呼ぶ。 毎回呼んでも無音なので、 個人層の SessionStart から呼べば、 新しく足した engine も各 Mac に届く。
- **どちらの engine も `-interaction=nonstopmode -halt-on-error`** で、 エラーで入力待ちにならず止まる。
- <a id="latexmk-up-to-date-after-agent-build"></a>**console の「Nothing to do」「All targets (…) are up-to-date」 は壊れていない** (実測): latexmk は時刻でなく file の中身の hash で組むかを決める。 TeXShop が組む前に保存し直しても中身が同じなら組まない。 agent が shell で `make` / `latexmk` を回した直後に本人が TeXShop で組むと、 この表示で何もしない = PDF は既に最新。 本人が「組めなくなった」 と言ったら、 まず hash を照合する (`<name>.fdb_latexmk` の source の行の md5 と `md5 -q <file>`)。 組み直させたいときは console の「作業ファイルを削除」 の後に組むか `latexmk -g`。 **防ぎ方**: agent が確かめのために組むときは、 本人が TeXShop で組む原稿の dir で `make` / `latexmk` を回さず、 組版の source を写した dir (例 `build/check/`、 git の管理外) で組む。 本人の PDF と `.fdb_latexmk` が変わらないので、 本人が組めば変わった分が組まれる (実例の形 = Makefile の `check` target が source を rsync して写しの中で `make` する)。 写しの PDF は、 PDF を携帯などへ写す仕組みの対象から外す。 本人の dir で組んでしまった turn では、 TeXShop ではこの表示になることを返事に書く。
- **TeXShop が知らない program 名を書くと、 黙って既定の経路に落ちる** (実測: TeXShop に無い名前を書いた uplatex の原稿が、 既定の欄を lualatex にした Mac で lualatex で組まれた)。 既定の経路 (環境設定の pdfTeX の欄・TeX+DVI の欄) は Mac ごとの設定なので、 ある Mac で組めた原稿が別の Mac で組めないことがある = 原稿の側で engine を名指す。
- **落ちた時の見え方**: 違う engine は原稿の class で止まり、 console で入力を待つ。 log は 0 byte、 `<name>.synctex(busy)` が残り、 process も残る。 console で中止するか process を止めてから、 原稿を閉じて開き直す (program の行は file を開いた時に読まれる = [#texshop-lualatex-and-external-builds](#texshop-lualatex-and-external-builds) と同じ)。
- **uplatex の原稿を LuaLaTeX に移すとき** (実測): class を `ltjsbook` / `ltjsarticle` に (`uplatex,dvipdfmx,papersize,nomag*` は外す)、 ふりがなは okumacro の代わりに `luatexja-ruby`、 `pxjahyper` は外す。 版面と字送りは jsclasses と同じで、 頁数も変わらなかった。 狭い表の欄で英字の名前のはみ出しが増えることがある (LuaTeX の改行の違い)。

## <a id="lualatex-compat"></a>LuaLaTeX で組める source にする・保つ

owner が文書を LuaLaTeX で組む (TeXShop の既定の経路が lualatex など) なら、 agent が CLI の platex で組めた source を渡しても、 owner の手元では class で止まって PDF が出ない (実測: log 0 byte で console が入力待ち = [#texshop-engines](#texshop-engines) の「落ちた時の見え方」)。 agent の build は何も言わないので、 source の側で engine を合わせる。

- **LuaLaTeX で組めない印**: pTeX / upTeX の class (`jsarticle` / `jsbook` / `jsreport`、 `jarticle` 系、 `ujarticle` 系、 `tarticle` 系)、 class option の `dvipdfmx` / `dvips` / `platex` / `uplatex`、 package の `otf` / `pxjahyper` / `okumacro` / `plext` / `pxcjkcat`、 package に付けた DVI の driver option (`\usepackage[dvipdfmx]{graphicx}` / `{xcolor}` / `{hyperref}`)、 `% !TEX TS-program = platex` / `uplatex` / `ptex2pdf`
- **書き方・移し方**: 日本語は `ltjsarticle` / `ltjsbook` / `ltjsreport` (英語は `article`)。 class option は `11pt,a4paper` などだけを書く (`dvipdfmx` `uplatex` `papersize` `nomag` `nomag*` は書かない)。 package にも DVI の driver option を書かない (graphicx・xcolor・hyperref は LuaLaTeX の driver を自分で選ぶ)。 `otf` の `\ajMaru` などは `luatexja-otf`、 okumacro のふりがなは `luatexja-ruby` に置き換え、 `pxjahyper` は読まない。 先頭に `% !TEX TS-program = lualatex` と `% !TEX encoding = UTF-8 Unicode` ([#texshop-lualatex-and-external-builds](#texshop-lualatex-and-external-builds))。 組んだら頁数と用紙を前の版と比べる ([#declare-paper-size](#declare-paper-size))
- **jsarticle の 11pt・12pt は `\mag` で版面ごと拡大して組む** ([#jsclasses-mag-true-lengths](#jsclasses-mag-true-lengths))。 geometry と dvipdfmx の経路では PDF の用紙まで A4 より大きくなった (実測)。 ltjs 系に移すとこの罠も無くなる
- **`article` の本文に日本語がある文書は `\usepackage{luatexja}` を足し、 `\begin{document}` の直前で読む**: pTeX は class に依らず日本語を組んだが、 LuaLaTeX の `article` は luatexja が無いと日本語の字を黙って落とす (log に `Missing character` が 193 件出ただけで error にならなかった、 実測)。 preamble の先頭で読むと、 後ろの `a4wide` と組み合わさって `\textheight` が 621pt から 432pt に縮み、 1 頁の表が 2 頁になった (実測、 仕組みは未確認)。 直前で読むと元の版面のまま組めた。 日本語が主の文書なら `ltjsarticle` に移す方が素直
- **機械**: [`scripts/check-tex-engine.py`](../scripts/check-tex-engine.py) が上の印を source から読む。 `FILE …` (1 = 印あり) / `--staged` (pre-commit 用。 新しく足した file は止める = 1、 直した既存の file は警告、 3 = 走らなかった) / `--fleet ROOT` (ROOT 直下の全 repo の棚卸し、 報告があれば 1)。 移すのは [`scripts/migrate-tex-to-lualatex.py`](../scripts/migrate-tex-to-lualatex.py) `SRC.tex WORKDIR` (上の書き換えをして、 前の経路と LuaLaTeX の PDF を頁数・用紙・ink・文字列で比べる。 数字を読んでから `--apply`)。 どの層の pre-commit に繋ぐかは owner の層が決める (本 repo は配線しない)
- **engine を owner 以外が決める文書** (他者が配った様式の雛形、 diff の基準に取ってある写し、 engine を共著者・学生が決めている原稿) は、 file の中に `% tex-engine-decided-by: <誰が決めるか>` を書く。 file を書き換えたくなければ repo の `.claude/tex-engine-decided-by.txt` に glob と `# 誰が決めるか` を 1 行ずつ書く。 検査はどちらの形も読む

## <a id="enumerate-vs-enumitem-option-syntax"></a>`enumerate` package の下で `[label=(\roman*)]` は組めない

`\usepackage{enumerate}` (option は `[(i)]` `[a)]` のような雛形) を読む preamble で、 `enumitem` の書き方 `\begin{enumerate}[label=(\roman*)]` を書くと `! Missing number, treated as zero.` で止まる。 原稿の preamble の写しで note を組むときに起きる (実測 = 2 本)。 直し方 = その preamble では `[(i)]` の雛形にする。 enumitem を足すのは原稿の preamble の変更なので著者の判断。

## <a id="latexdiff-ulem-option-clash"></a>latexdiff: 本文が `ulem` を option なしで読むと差分 markup が silent に壊れる (2026-08-21)

**症状**: `latexdiff old.tex new.tex > diff.tex` → pdflatex は `! LaTeX Error: Option clash for package ulem.` を吐くが batchmode では PDF が出てしまい、 **追加/削除の下線・取り消し線が欠落した「差分に見えない差分 PDF」** ができる。 原因 = 本文の `\usepackage{...,ulem}` (option なし) と latexdiff preamble の `\RequirePackage[normalem]{ulem}` の衝突。

**対処**: 生成した diff.tex の先頭 (documentclass より前) に `\PassOptionsToPackage{normalem}{ulem}` を入れる。 1 行で済む:
```bash
latexdiff old.tex new.tex | sed '1s/^/\\PassOptionsToPackage{normalem}{ulem}\n/' > build/diff.tex
```
**検証**: diff.log の `^!` が 0 であること + 変更ページを画像化して markup を目視 (text 抽出は下線 markup で単語が分断されるので信用しない)。

**差分 PDF は 1 頁目に「何と何の差か」 を書く**: 差分を複数種類 (= 投稿版との全差分 / 直近の修正だけ 等) 送ると取り違えが起きる。 生成した diff.tex の `\begin{document}` 直後に表紙 1 頁を挿し込み、 **old / new が相手にとって何の版か**を書く (= 日付と出来事で指す。 内部 version 名・commit hash は書かない = [`physics-notes.md#no-internal-shorthand-in-deliverables`](physics-notes.md#no-internal-shorthand-in-deliverables))。 色の凡例・生成日時は不要 (= 差分 PDF を開けば色は自明、 情報を足すほど表紙が読まれない)。 そもそも**相手にとって意味のある切れ目でない差分は送らない** — 自分の作業日を境にした差分は相手の手元の版と対応しない。

**関連の罠**: 変更ブロック内の `\label {key}` (空白入り) は latexdiff が `\label` と `{key}` の間に markup を挟んで `! Argument of \label has an extra }` になる → 新規に書く label は `\label{key}` (空白なし)。

## <a id="abbreviation-first-occurrence"></a>略語は本文で長形が初めて出る箇所で定義する (2026-09-11)

**ルール**: 略語は、本文 (abstract の外) で長形が**初めて**出る箇所に「長形 (略語)」 の形で 1 回だけ定義する。 それより前では略語も長形も使わず、 定義の後は略語で通す。 abstract は自己完結なので別扱いで、 abstract の中の長形や定義は本文の定義を免除しない。 節題と、 長形を含む固有名は例外。

**検査は 2 条件**: (1) 略語が定義より前に出ない、 (2) 定義が長形の初出に付いている。 (1) だけでは、 後から前の節に書き足した段落が長形を使っていても通ってしまう。 2026-09-11 に同じ原稿を 2 回独立に走査し、 2 回とも (1) だけを見て取りこぼした (序論に書き足した段落が、 後ろの節にある定義より前で長形を使っていた)。

**道具**: [`scripts/check-abbreviations.py`](../scripts/check-abbreviations.py) — D1 重複定義 / D2 定義前の使用 / D3 定義より前の長形 / D4 定義後の長形 / S1 「et al.」 「Ref.」 などの後の文末スペース / U (情報) 定義の無い大文字 token。 長形は「(ABBR)」 の直前の語の頭文字から推定し、 推定できないものは `--long ABBR='…'`、 固有名は `--allow`、 独自の display wrapper は `--display-macro` で渡す。 project 固有の allow / long は project 側の shim に置く。 投稿前 gate の spec に並べる (`paper-audit.md#gate-spec-anchor-list`)。

## <a id="notation-first-use"></a>記法は初めて使う箇所で説明するか、 そこから定義の式を指す (2026-09-13)

**ルール**: 添字の括弧 (反対称化・対称化)、 左肩の次数、 独自の演算子などの記法は、 本文で**初めて使う**箇所で説明するか、 そこに定義の式への参照を置く。 定義の式が付録や後の節にあること自体は構わない。 関連する 2 つの記法を 1 つの脚注でまとめて指してよい (後の記法の初出より前にその脚注があれば、 読み手は既に知っている)。

**式の前方参照**: まだ印字されていない式を `\cref` で引くときは、 その式の記号が何かを同じ文で一言添える (`the kinetic operator of Eq. (X)` の形)。 前方参照そのものは誤りではない。

**道具**: [`scripts/tex-first-use.py`](../scripts/tex-first-use.py) — `--pattern REGEX --defined-at LABEL` で初出の行と節を出し、 初出が定義より前で、 それより前にも直後にも定義への参照が無ければ exit 1。 `--exclude` で同じ形の別物 (次数ラベル `^{(2)}` など) を外し、 `--stop-at '\\appendix'` で付録の手前で止める。 `--forward-refs` はまだ印字されていない式への参照を列挙する (読む候補であって exit は変えない)。 略語は [#abbreviation-first-occurrence](#abbreviation-first-occurrence) と `check-abbreviations.py` が受け持つ。

**なぜ**: 2026-09-13 の通読で著者が「対称化と反対称化は最初に出る場所で説明されているか」 と止まった。 定義の式は付録にあり、 本文の初出から数百行離れていた。 記法ごとに正規表現を変え、 次数ラベルを除き、 付録の手前で止める grep を 2 回手で書き直して答えた。 道具にした最初の版は、 preamble の `\let\origappendix\appendix` を付録の開始と読み、 初出より前の脚注にある参照も数えなかった。 どちらも実物の原稿に 1 回当てて見つかった (selftest の fixture だけでは出なかった)。

## <a id="author-notes-as-comments"></a>著者への注記は `%` comment + 見える印で置く (pdflatex は日本語の脚注を通さない)

原稿の中に「ここは著者が埋める・確かめる」 という注記を残すとき、 脚注に日本語や記号 (★ など) を書くと pdflatex が `Unicode character ... not set up` で止まる (実測)。 bib の `note` 欄に書いても同じ (bbl 経由で本文に入る)。

- 注記の本文は、 その文の直後の行に `% ★ ...` の comment で置く (1 文 1 行の原稿なら文と対応が取れる)。
- 本文には `\red{[check]}` のような ASCII の見える印だけを置く。 PDF で場所が分かり、 組版は壊れない。
- bib の照合メモは entry の外の `%` 行に。 BibTeX は entry の外の行を読まない。
- latexmk が `exit 12` で止まるのに `main.log` に `!` が無いときは、 古い `.bbl` を掴んでいる。 `.bbl` `.aux` `.blg` を消して回し直す。

## <a id="symbol-rename"></a>1 文字記号の一括改名 (y→x、 r→\zeta_x の類) の手順 (2026-09)

原稿の 1 文字記号は素の置換ができない。 同じ文字が `\frac` `\right` `\sqrt` の中、 `\cite`/`\ref` の key、 別の記号の添字
(`\sigma_z`)、 英単語、 別の量 (Mandelstam の s と Bloch 成分の s、 Yukawa の y と Δm/Γ の y)、 `\%` の後ろに現れる。
道具 = [`scripts/tex-rename-symbols.py`](../scripts/tex-rename-symbols.py) (standalone な文字だけを対象にする `scan` / `apply`)。

1. **走査**: `scan FILE --letters ryz` で standalone な出現を行番号つきで全部見る。 「同じ文字で別の量」 (Mandelstam の s、
   Yukawa の y) をここで見つけ、 exact 置換の list か `--keep` の正規表現に分ける。 `ry^2` のような 2 文字連結は standalone
   でないので exact list に入れる。
2. **exact → standalone** の順で `apply`。 `\bar r` は `\bar{\zeta}_x` に整う。 置換が後続の英字と連結すると止まる。
3. **再走査**で残り 0 (keep した文字だけが残る) を確かめる。 ⚠️ コメントを `%.*` で消す自作 script は `\%` 以後の記号を黙って
   残す (実測)。 `(?<!\\)%` を使う。
4. **図の label は別**: matplotlib の `r'$y=\Delta m/\Gamma$'` などは図の script 側。 再生成に走査の cache が要る図は、
   cache の有無を先に確かめる (無ければ再走査に時間が掛かる = 同じ日に組み直せない可能性を先に言う)。
5. **再組版** → PDF の text を PyMuPDF で引いて旧記号 0 件・新記号 N 件を数え、 頁を PNG に描いて目視。
6. **commit は承認と同じ turn で** ([manuscript-claim-ownership.md#commit-in-approval-turn](manuscript-claim-ownership.md#commit-in-approval-turn))。
   図の再生成を待つなら、 承認済みの tex を先に commit し、 生成物は後の commit にする (主張の承認の対象は text であって生成物ではない)。
7. 旧記号のまま残るもの (日付つきの査読依頼・報告書・作業記録・probe の変数名) は触らない。 commit message に列挙する。

記号の**選び方** (衝突の検査) は [paper-audit.md#symbol-collision-sweep](paper-audit.md#symbol-collision-sweep)。

## <a id="braket-set-ket"></a>braket.sty の `\Set{…}` の中で `\ket` / `\bra` が壊れる — `\vert` で再定義する

**症状:** `\Set{\ket\psi\in\mathcal H | …}` が `Extra }` / `Missing }` で止まる。 小文字の `\set{…}` は通るが、 その `|` は `\mid` の間隔になる。

**原因:** braket.sty の `\ket` は `\mathinner{|{#1}\rangle}` で、 文字の `|` を含む。 `\Set` は引数の中の `|` を `\SetVert` (= `\egroup\;\middle|\;\bgroup`) に差し替えるので、 `\ket` の中の `|` まで乗っ取られて group が崩れる。 `\protect` は効かず、 `\noexpand` は通るが ket が消える。

**直し方:** preamble で `\usepackage{braket}` の後に、 文字の `|` を control sequence の `\vert` に替えた定義を置く (字形は同じ、 `\Set` / `\set` / 単独 / `\Braket` との併用で正しく出る):

```latex
\renewcommand{\ket}[1]{\mathinner{\vert{#1}\rangle}}
\renewcommand{\bra}[1]{\mathinner{\langle{#1}\vert}}
```

`\Ket` / `\Bra` は `\left| … \right|` なので元から安全。 ⚠️ 既存原稿で `\ket` を多数使っていても、 字形が変わらないので一括の書き換えは要らない (build して `\Set` の箇所が通ることだけ確かめる)。

## <a id="smash-parbox-into-ruled-box"></a>表の空行を積んだ記入欄に、 枠の大きさを変えずに文章を流し込む

表の空行を積んで作った記入欄 (`\multirow` の見出し + 空の行 N 本) のセルに後から文章を入れると、 行の高さが変わって枠も頁も崩れる。 枠の 1 行目のセルに、 高さと幅が 0 の箱で置き、 下の空行の上へ流す:

```latex
\newcommand{\fillin}[1]{\rlap{\smash{\parbox[t]{0.66\textwidth}{#1}}}}
% 枠の 1 行目 (幅を決める \hspace はそのまま残す)
  &\multicolumn{3}{|l|}{\fillin{本文…}\mbox{}\hspace{0.68\textwidth}\mbox{}}\\
  &&\multicolumn{3}{|l|}{}\\   % 残りの空行は触らない
```

- `\parbox[t]` で 1 行目の baseline がセルの baseline に揃い、 `\smash` で行の高さが、 `\rlap` で幅が 0 になる (幅を決める既存の `\hspace` はそのまま効く)
- 表の行の高さと本文の行送りはどちらも `\baselineskip` なので、 素の文は空行にそのまま重なる。 分数や別行立ての式は行送りを伸ばす = 枠に入るかは組版して枠の下端で確かめる (はみ出しても警告は出ない、 実測)。 入らなければ別行立てを 1 行の中央寄せに、 分数を斜線に
- ⚠️ `\smash` の引数に段落区切り (`\par`・空行) を入れると `Paragraph ended before \makesm@sh was complete` で止まる。 改行は `\\`、 中央寄せの 1 行は `\\ \hspace*{\fill}<式>\hspace*{\fill}\\`
- 表の一番上が、 幅の指定だけを持つ空の細い行になっていたら、 外して幅を次の行のセルの `\makebox[<幅>]{…}` で保つ。 `[t]` の表は先頭の罫線 (`\cline`) の位置で揃うので、 隣に `[t]` で並べた表の上端は揃ったまま (実測)。 その行にあった見出しは `\raisebox{<高さ>}[0pt][0pt]{…}` で次の行に高さ 0 で置く
