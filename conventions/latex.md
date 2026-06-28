# LaTeX 規約

LaTeX を含むリポで適用。CLAUDE.md から参照: `~/Claude/claude-config/conventions/latex.md`

## 式の安全規則
- **equation/align 環境内は原則変更しない。** 変更は事前にユーザー確認。物理的内容の追加はコメントとして提案（ハルシネーション混入防止）
- 英語校正・文法修正など確実に正しい本文修正は可

## `\mathbb{数字}` は黙って化ける — 単位行列は `\mathbbm{1}` (bbm)

- **`\mathbb{数字}`(例 `\mathbb 1`, `\mathbb 0`)を使わない。** `amssymb` の `\mathbb` は**大文字 A–Z しかグリフを持たない**ため、数字を渡すと **compile error を出さずに黙って化ける**(missing glyph / 別字へ fallback)。= **視覚 QA でしか気づかない**沈黙故障(コンパイル成功 = 正しい、ではない好例)。
- **単位行列・恒等作用素は `\usepackage{bbm}` + `\mathbbm{1}`**(真の黒板太字 1)。代替: `\mathds{1}`(dsfont)、最低限 `\mathbf{1}`。同様に黒板太字の数字が要る一般ケースも `\mathbb` でなく bbm/dsfont 系を使う。
- **発火**: PDF の**視覚 QA で実物確認**が第一(doc 記載だけでは発火しない)。より確実には pre-commit / build で `\mathbb\s*\{?\s*[0-9]` を grep する mechanical guard を足す(= doc rule より発火信頼度が高い)。
- 実例: ある物理ノートの式で $\gamma_5^2=\,$`\mathbb 1` が化けていた(`\mathbbm{1}` で修正)。`\mathbb` を識別子マクロのつもりで数字に当てると起きる。

## comment-out 流儀の編集後は live `\cite` 集合を照合する

旧文を `%...` で残して次行に新文を書く「comment-out keep」 流儀で編集すると、 行末まで `%` が
飲み込むため、 同じ行にあった `\cite{...}` を**意図せずコメントアウトして引用が落ちる**危険がある。
**comment-out edit のたびに、 各行の code 部 (= 最初の `%` より前) の live `\cite` key 集合を
baseline と照合**し不変を確認する (= `\bibcite` や aux 経由でなく source の `%` 前を見る)。 安価:

```bash
# 各行の最初の % より前に現れる \cite キーを抽出して sort -u で集合化、 baseline と diff
awk -F'%' '{print $1}' file.tex | grep -oE '\\cite[a-zA-Z]*\{[^}]*\}' | sort -u
```

## comment-out / `\begin{comment}` した構造的要素を「原稿にある」と主張しない

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

## latexdiff で差分レビュー PDF を作る

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
| 3 分かかる / output が無限ループ | CFONT の color markup が page builder と干渉 | `--type=UNDERLINE`（色でなく下線/取消線）+ ソースの `twocolumn`→`onecolumn` |
| `Paragraph ended before \align` | latexdiff が変更 align 内に空行（`\par`）を挿入 | 後処理で数式環境内の空行を除去 |
| natbib citation でハング | citation markup × natbib | `--disable-citation-markup` |

**推奨 flag の既定**（複雑な物理原稿で安定する組合せ）:

```bash
latexdiff --type=UNDERLINE --math-markup=off --disable-citation-markup \
  --config "PICTUREENV=(?:picture|tikzpicture|feynman|DIFnomarkup)[\w\d*@]*" \
  "$D/old.tex" "$D/new.tex" > "$D/diff.tex"
# 後処理（数式環境内の \par 除去 + twocolumn→onecolumn）後に pdflatex を 2 回
```

- `--math-markup=off`: 式中の add/del は色付けしない（式の変更は新版として出るが色は付かない）。数式の add/del markup はコンパイルを壊しやすいので既定 off にし、文章・構造・コメント削除の差分を確実に出す方を取る。
- **「投稿用でなく差分レビュー用」と割り切る**: markup 除去・図 placeholder・数式色なしは*意図的な簡略化*。

**別解（latexdiff のコンパイル問題を完全回避）**: Overleaf 連携の原稿なら **Overleaf の History 比較**（baseline 版 ↔ 現在）が確実で、pre/post 処理が要らず数式まで色分けされる。

> この pre/post 処理は各 paper repo の `latexdiff/` 配下の再生成スクリプトに固める運用でよい。**baseline commit・どのマクロを展開するか等の原稿固有値はその repo 側に置き、手法の正本（本節）を参照する**（= SoT は上層 1 つ、下層から参照）。

## 長さ・段落構造の判断にコメントアウト行を数えない

**ルール:** 段落の切れ目・節の分割・restructure 等、 「文書の長さ / 段落の重さ」 を根拠にした編集判断は **rendered 出力 (= PDF に出る内容) だけで見積もる**。 `%` でコメントアウトされた行・ブロック (= 旧 draft・代替表現・comment-out keep で残した旧文) は source 行数を膨らませるだけで読者には出ないので、 長さの勘定に入れない。

**Why:** comment-out keep 流儀 (= 旧文を `%` で残し直下に新文を書く) や、 複数の代替表現を `%` で寝かせる運用では、 source 行数と rendered 分量が大きく乖離する。 source を上から眺めて「この段落は長い / 詰め込みすぎ」 と判断すると、 実際には普通サイズの段落を不要に分割する誤りに陥る (= 行番号レンジ L_a–L_b を分量の代理指標にすると、 間に寝た `%` ブロックを数えてしまう)。

**How to apply:** 「長い / 分割すべき」 と言う前に、 対象範囲の `%` 行を除いた live 本文だけを読む。 安価:

```bash
# コメント行・空行を落として live 本文の分量だけ見る
grep -vE '^\s*%' file.tex
```

display math・図は行数でなく rendered での専有量で別途見積もる。

## 地の文に math 文字を裸で書かない (math mode 保護)

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

## プリアンブル定義のマクロを優先する (絶対則)

**リポのプリアンブルで定義されているマクロ (semantic / typing shortcut / 色付き / 数式 alias / その他、種類問わず) が対象概念に存在する場合、生の primitive 記法を使うことを禁止する。**

⚠️ **「`\op` だけの話」 ではない**。プリアンブルで定義されているありとあらゆるマクロが対象。色付き semantic macro (`\op` `\st` `\rf` `\pd` 等) だけでなく、typing shortcut (`\h` = `\hat`、`\wh` = `\widehat`、`\tx` = `\text`、`\md` = `\middle|`、`\sqbr{}` = `\left[...\right]` 等) や数学演算子 (`\Tr`、`\fnl`、`\commutator{}{}` 等) も同等に強制対象。

例外は以下 **2 つに限定** (狭く解釈する):
1. プリアンブル定義が**無い**概念 (= grep で見つからない)
2. author drafting marker (= `\cl{}` `\green{}` 等の一時的 highlight、後で消す前提のスクラッチ、semantic 意味なし)

これ以外、「raw でも動くから raw で書く」 「見た目同じだから raw で OK」 「タイプが少し短いから raw で済ます」 は全部 NG。

### 対象範囲の例 (= 全部対象、これでも非網羅)

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

### 確認用 grep (= 「定義がある macro 名なのか?」 をチェック)

```bash
# ある token (e.g. \red, \op, \fn, \Tr) の定義をプリアンブルで探す
grep -nE '\\(newcommand|renewcommand|providecommand|nc|def|NewDocumentCommand|DeclareDocumentCommand|DeclareMathOperator)\*?\{?\\<token>' main.tex
```

`\NewDocumentCommand` / `\nc` (= `\newcommand` の独自 shortcut) / `\providecommand` 形式は `\newcommand` 1 種類だけ grep してると見落とすので、上の widening grep を必ず使う。

### 理由 (rule の hard 化を支える 4 条)

1. **一斉追従**: macro 定義を refine (e.g. journal 投稿時に色除去 + ハットスタイル変更、フォント差し替え) すると全箇所が一斉追従、生記法は drift する。プリアンブルがあるのに使わないと「定義したが効かない」 dead 領域になる
2. **Greppability**: `\op{T}` は概念として grep 可能 (= 全 operator 占用箇所が `grep '\\op{'` で引ける)、生 `\hat{T}` は raw notation で grep しても operator かどうか判別不能
3. **意図の明示**: `\op{T}` は読み手に「operator T」 を伝えるが、`\hat{T}` は単なる hat 記号で物理 / 数学的意味が伝わらない
4. **共著者・後継者の dx**: 1 人が手で raw を選ぶたびに、共著者の grep が外れる、後継者の refine が壊れる、レビュアーが「なぜここだけ違うの?」 と問う。**プリアンブル定義 = 既に「これを使え」 と全員に向けて宣言されている。raw 書きはその宣言を裏切る行為。**

### リポ固有 fallback

リポ固有の active semantic macro 一覧と例外運用は各リポの `CLAUDE.md §LaTeX rules` 参照 (Layer 2)。Layer 1 の本則は「プリアンブルにあれば必ず使う」、Layer 2 は「このリポで何が active か」 のディレクトリ。

## マクロ alias の forcing function

上の絶対則を「読めば守る」 discipline だけに頼ると、共著者の Claude や別 session で raw 記法が静かに再混入する。**典型的な抜け道**: atom（`\h`・`\bs`・各 subscript alias）が個別には正規 alias なのに、それらを束ねた **compound macro をバイパスして書き下した形**（`\h T_{...}` を専用マクロの代わりに longhand）は、atom-level の grep / linter をすり抜ける。違反は linter が見る一段上で起きる。さらに別 dialect（別の綴り・別 primitive）でまるごと書かれた領域は、denylist に列挙していない綴りなので 0 hit で素通りする。

→ 各 LaTeX repo に **3 段の機械 enforcement** を置く:

1. **repo-local の check script**（例: `scripts/check-preamble-aliases.py`）— body を走査し、プリアンブルに macro があるのに raw を使う箇所を HARD 違反として列挙、hard>0 で `exit 1`。macro vocabulary は repo ごとに違うので script は **Layer 2（各 repo の `scripts/`）に置く**（本 Layer 1 doc は pattern の SoT、実装は repo 側）。検出規則には atom だけでなく **その repo の compound macro をバイパスした形**（lookahead で対象を絞り、別概念の同形記号を誤検出しない）まで含めるのが肝。
2. **committed pre-commit hook**（`.githooks/pre-commit` + `core.hooksPath` を張る `scripts/install-hooks.{sh,ps1}`）— clone 初回に 1 度 install すれば、以後の commit で 1. を自動実行し raw を含む commit を block。hook は version 管理下に置き、各著者の環境（mac / Windows git-bash）で動くよう `sh` で書く。既存の char-fixer 等があれば conditional に chain（無い環境では no-op）。⚠️ **Windows gotcha**: `.gitattributes` で hook と `*.sh` を `eol=lf` 強制しないと、checkout 時に CRLF 化して shebang（`#!/bin/sh`）が壊れる（`* text=auto eol=lf` 1 行で足りる）。git-bash の挙動は version 差があるので、Windows 共著者が居るなら初回に実機 smoke-test（適当な違反を commit して block されるか）を 1 度回す。
3. **CI**（`.github/workflows/*.yml` で push/PR ごとに 1. を実行）— pre-commit hook を install していない clone（= 制御できない共著者）でも server 側で必ず検出する最終防衛線。pure-script なので LaTeX build 不要・高速。

⚠️ **mechanize の限界を明示する**: 微分の `d` のように「regex で raw と正用を判別できない」 category は lint 不能 → discipline に残す（noisy rule を足すと false positive で linter の信頼を失う）。mechanize できる subset とできない subset を分け、後者は doc に明記する。

各 repo の `CLAUDE.md §LaTeX rules` から本節を参照し、session 開始時に `git config core.hooksPath` が `.githooks` を指すか確認 → 空なら install を促す手順を repo 側に書く。

## 新規 macro に fixed framing text を含める前に source-render asymmetry の罠を抑える

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

## コンパイラ

odakin の標準は **pdf 直接出力 (= pdftex 系)**。tex+dvi+dvipdfmx の 2 段ワークフローは**英語論文では使わない**。

- **英語のみ** → **`lualatex`** が odakin の標準 (= TeXShop が `LuaTeX-1.21.0` で生成、PDF Producer 欄で確認済)。`pdflatex` も可 (どちらも pdf 直接出力で互換)
- **日本語含む** → `ptex2pdf` (内部で platex + dvipdfmx) または `lualatex` (jlreq クラス等)
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

## Bibliography スタイル
- **JHEP.bst を使う**（個人的好み）。`note` フィールドも表示するバージョンを使用
- 正本: `~/Claude/claude-config/JHEP.bst`（ver. 2.18 ベース + note 全 entry type で有効化、md5: `bcca8042…`）
- `setup.sh` が texmf-local にインストール（odakin: 自動、他ユーザー: オプション表示）
- texmf-local 未設定の場合は正本からリポにコピーして使う
- `\bibliographystyle{JHEP}` を指定

## biblatex は使わない（JHEP.bst と非互換）

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

## 日本語著者の BibTeX 処理

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

## refs.bib 整備フロー（実物検証によるハルシネーション防止）

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

## JHEP.bst 記法
JHEP.bst はフィールドから自動リンクを生成するので `\href` 手書き不要（二重リンクの原因）。
- `doi`: DOI 本体のみ（例: `10.1103/PhysRevA.61.012104`）
- `eprint`: arXiv ID のみ（例: `quant-ph/9905023`）。`archivePrefix = "arXiv"` と併用
- `url`: doi や eprint があれば不要
- `note`: 自由テキスト。自動リンク対象外の補足情報に使う

## hyperref 設定
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

### 旧設計の失敗 (2026-05-14)

旧 setup.sh Step 6 は「`.tex/.bib` を含む repo にだけ install」 という時点依存検出を採用していた。 問題は 2 つ:

1. **時点依存**: setup.sh 実行時に `.tex` 不在の repo は skip → 後から `.tex` 追加されても hook 未 install のまま
2. **bash glob 深度不足**: 検出 logic `ls "$REPO_DIR"**/*.tex` は globstar 無効時に 1 階層しか見ない。 個人層 private repo の `.tex` が深い path (depth 4) で detection failed

→ 全 repo install に切替えた (hook 自体が no-op skip するので害無し)。 移行は `setup.sh` を 1 回再実行すれば既存 repo に retroactive install される。

### fix-bib-unicode の codepoint scope (2026-05-15 確認)

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

### vendored / verbatim LaTeX の opt-out (2026-06-09)

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

### 設計動機 (2026-06-09)

hook に除外機構が無く、 ある repo に arXiv の LaTeX ソースを verbatim 取り込んだ時、 初回 commit で bibliography 著者名 (`Krämer`→`Kr{\"a}mer`) と dash が自動正規化され「verbatim」 が崩れた。 public な本 repo から全 repo に配られる hook に opt-out が無いのは設計欠陥、 と判断して `.gitattributes` honor を追加。 改変は意味的には identity-preserving (LaTeX 描画同一) だが、 vendored source は upstream との byte 一致が価値なので除外できるべき。

## 日本語横罫線 (em-dash 系) の書き方 (2026-05-15、 個人層 LaTeX project 経験で導入)

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

## ドキュメント読み取り

- **内容理解が目的なら PDF を `pages` パラメータ付きで読む。** tex ソースはトークン消費が大きい（数万トークンになることも）。PDF なら必要なページだけ効率的に読める
- tex は **数式の編集が必要な場合のみ** 開く。その場合も `offset`/`limit` で必要な範囲に限定する

### 論文を grep/検証する: PDF プログラム抽出より arXiv ソース (2026-06-09)

上の「PDF を `pages` で読む」は **Read tool の視覚読解**（page を rendered で見るので数式も正確）。一方、**論文を grep / 数値裏取り / 反復参照** したくて `fitz`(PyMuPDF) や `pymupdf4llm` で**プログラム的にテキスト抽出**する場合は別問題で、数式忠実度が崩れる:

- `pymupdf4llm` (markdown): 構造は綺麗だが **ギリシャ/数式記号が壊れる**（θ→✓、Ω→⌦ 等）、図が junk テーブル化
- column-aware `fitz` `get_text`: 記号は保つが 2 段組の単語間スペース欠落・表フラット化

⇒ **数式が命の物理論文を機械的に扱うなら arXiv の LaTeX ソース (.tex) を取る**（math は LaTeX のまま完全、変換を挟むほど壊れる）。繰り返し参照する論文は .tex を repo に vendoring する手もある（その際 `-latex-autofix` で auto-fix から除外 = 上記「vendored / verbatim LaTeX の opt-out」）。図バイナリ・class file は除外し PDF/Dropbox 等に。worked example: 2026-06-09 Planck 2018 読書会で arXiv ソースを採用。

## チャット本文での位置参照

- **ページ番号・セクション名・式番号で位置を示す。tex の行番号は使わない。** 行番号はツールが tex を読むときの内部座標で、ユーザー側 (PDF / TeXShop) には不可視。ユーザーがナビゲートできない参照は無効
- 行番号は Edit 等の tool 引数として内部で使うだけに留める
- ページ番号・**式番号・節番号**は `.aux` の `\newlabel{<label>}{{<番号>}{<page>}...}` の**第 1 フィールド (= 番号)** から引ける (= `zref-clever` を使う note は `\zref@newlabel{<label>}{\default{<番号>}...}` 行も同値)。最新ビルドの aux が無ければ PDF を読む
- **共著者の未 compile な `.tex` から番号を引く**には、 preamble の driver で 1 パス compile して aux を生成する。日本語 note (`ascmac` / `[dvipdfmx]` graphicx 等) は `uplatex -output-directory=<tmp> -interaction=nonstopmode <file>.tex` で通す (= pdflatex では通らない)。出力を tmp に逃がせば元の clone / Overleaf 入れ子を汚さない

## チャットで LaTeX / 数式を渡すときは code block で（コピペ保全）

ユーザーがコピペして使う LaTeX / 数式片を chat 本文に出すときは **必ず code block（fenced or inline backtick）に入れる**。 markdown は code span の**外**では `_` を強調（italic）マーカーとして消費するため、 `x_{\mu}` のような下付き満載の LaTeX を地の文に書くと **`_` が剥がれてコピペが壊れる**（`^` も環境次第）。 code span 内は markdown 非適用で `_` `^` `\` `{}` が literal 保持される。

- **コピペ用**の LaTeX / コード / `_` を含むパス → **code block**（保全優先）
- chat 上で**読ませるだけ**の数式（コピペ不要）は別軸 — 環境によって `$...$` が未レンダーなので Unicode 添字・上付きで書く

## .gitignore
**LaTeX 生成 PDF はリポに含める（ignore しない）。** 共同編集者がコンパイル環境を持っていない場合でも最新の PDF を参照できるようにするため。`*.pdf` を ignore する場合は `!<main>.pdf` で除外対象から外す。

共有リポでは共同編集者のために .gitignore に LaTeX 中間ファイルのパターンを明記する（`~/.gitignore_global` に頼らない）:
```
*.aux *.bbl *.blg *.log *.out *.toc *.fdb_latexmk *.fls *.synctex.gz *.synctex(busy) *.dvi
```

## .gitattributes（改行コード正規化）

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

## 日本語長 title の文節境界改行 (title_wrap pattern)

ポスター・slide・cover page 等の **display title** で日本語 long title (= 15 文字以上) を扱う時、 LaTeX の auto-wrap は機械的に「N 文字/行」 で改行するため、 助詞「に」 「の」 や単語「保存量」 の途中で改行されて editorial 不自然になる。

**例**: 「一般相対性理論における二つの保存量:エネルギーと重力電荷」 (17 chars)

- auto-wrap (= 32pt × text_width 100mm): 「一般相対性理論に / おける二つの保存 / 量:エネルギーと重 / 力電荷」 (= 4 行、 助詞・単語途中改行)
- title_wrap で手動指定: 「一般相対性理論における / 二つの保存量: / エネルギーと重力電荷」 (= 3 行、 文節境界)

### How to apply

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

### When to use

short title (= 13 chars 以下) は auto-wrap で OK、 title_wrap 不要。 long title で auto-wrap 結果が editorial 不自然なときのみ **opt-in** で使う (= 全 title に title_wrap を強制すると過剰運用、 short title での手動指定は冗長)。

### font override pattern (= long content への対応)

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

### paragraph break の保持 (= 段落区切り)

abstract 等の長 content で **段落区切り**を保ちたい場合: yaml の block scalar `|` の空行は LaTeX `\providecommand{...}{<value>}` 内では消える (= 単純 space 化される) ので、 build script で `\n\n` → `\par ` 変換する:

```python
abstract_latex = re.sub(r"\n\s*\n", r"\\par ", abstract_yaml)
```

PDF 上で段落区切りが visible (= LaTeX default `\parskip` で 1 行分の vertical gap)。 強調したいなら template 側で `\setlength{\parskip}{4pt}` 等。

### Why

editorial typography で「機械改行を許容しない」 のは標準。 magazine cover / book cover / 学会ポスター等の display title は **文節境界改行**が defacto standard で、 auto-wrap 結果は visual quality を下げる。 yaml で行配列を持つ pattern は (a) wrap が text 編集の一部として扱える (b) display と web (= wrap なし) で同じ source から両方 generate できる、 2 つの利点がある。

## <a id="pdf-visual-verification"></a>PDF 視覚検証 reflex: compile success + log no-error だけで完了としない

LaTeX edit 後、 `pdflatex` が完走しても visual の overflow / misalignment / text 切れは普通に起きる。 「compile 成功」 を成功 signal にすると見落とす。 edit のたびに以下を回す:

1. `pdflatex -interaction=nonstopmode FILE.tex 2>&1 | grep -iE "^! |Overfull"` — fatal error + overflow warning を確認（platex DVI workflow なら `platex ... ; dvipdfmx ...` の各段で同 grep）
   - ⚠️ **`grep undefined` だけで済ませない**: `^!` (TeX error) は `Double subscript`・`Missing $` 等で出るが、TeX は recover して PDF を出すため「undefined 参照ゼロ」だけ見ると error を見逃す（例: `\newcommand{\X}{Y_{\rm z}}` を `\X_{...}` と使う double-subscript は PDF が出ても下付きが壊れる）。**必ず `^!` を grep** し、`error 0` を確認する。
2. `python3 -c "import fitz; doc=fitz.open('FILE.pdf'); pix=doc[N].get_pixmap(dpi=200); pix.save('/tmp/check.png')"` — 該当 page を PNG 化
3. `/tmp/check.png` を Read tool で開いて **視覚確認** (= 「compile OK」 だけで完了としない)
4. `Overfull \hbox (N pt too wide)` warning が出たら必ず該当 page を render して overflow が visual に問題ないか確認

### 典型 trap (= 2026-05-18 EC erratum note 編集で連続再発)

| Symptom | Cause | Fix |
|---|---|---|
| `\paragraph{...}` 直後の `\colorbox{...}` が page 右に流れる + 右端 truncate | `\paragraph` は inline header、 後続 box が paragraph 内の continuation 扱い | `\subsubsection*{...}` か `\par\medskip\noindent\textbf{...}\par` で block separate |
| tikz の隣接 node が重なる | 2 node 間の position 計算が tight | 1 つの node に統合 (e.g., `=` と次 text を 1 node) または coordinates を広げる |
| `\verb|...|` が `\colorbox{...}\parbox{...}` 内で `! \verb illegal in argument` | `\verb` は box 引数内で使えない | `\texttt{...\\_...}` で literal underscore escape |
| `\bfseries` が math mode で `! Command \bfseries invalid in math mode` | bold を math 内で適用しようとした | `\boldsymbol{}` か、 `\text{\bfseries ...}` で text 切り替え |
| Unicode `✗` `✓` で `! LaTeX Error: Unicode character (U+xxxx)` | utf8 inputenc default で読めない記号 | `$\times$` `\checkmark` に置換、 または `\usepackage{pifont}` + `\ding{}` |
| table の comment 列が page 右を超えて truncate | column が自然幅で expand、 long text で overflow | `p{width}` で wrap 化 + `\setlength{\tabcolsep}{4pt}` で間隔調整 + 必要なら `\footnotesize` |
| tikzpicture 全体が page 右に偏る | tikz の `\node[align=center]` の width が長い text で右に extend、 bounding box が asymmetric | text 位置を `align=center` の代わりに固定 coord で配置 + node 間 spacing を測って overlap 避ける |

### Why

`pdflatex` の exit code 0 + `! ` error 不在は **build success** の signal であって **visual success** の signal ではない。 `Overfull \hbox` は warning として log に出るだけで build を止めない (= 文字が page 外に hanging するだけ)。 PDF を visual で見ない限り「✓ IS RIGHT (phy...」 で truncate されている等の事故は気付けない。 PyMuPDF (`fitz`) は poppler 不要で macOS default で使えるので、 reflex として安価。

---

## 編集向け infographic / poster / 1 枚 figure の design 規約

scientific infographic (= A4 / A3 1 枚もの) や poster を LaTeX で制作するときの design choice。 TikZ / pgfplots を多用する制作では本 file の上記 LaTeX 一般規約 + `conventions/tikz-pgfplots.md` (TikZ/pgfplots gotchas) を併読。

### 印刷前提なら light theme + cream paper

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

### Libertinus フォントファミリー (= 数式統一の選択肢)

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

### macOS Hiragino と Libertinus の組合せ

```latex
\setmainjfont{HiraMinProN-W3}[BoldFont=HiraMinProN-W6]
\setsansjfont{HiraginoSans-W3}[BoldFont=HiraginoSans-W6]
```

PostScript 名 (= `HiraMinProN-W3` 等) が必要。 display name (= `Hiragino Mincho ProN W3`) では fontspec が見つけられない。 詳細は [`tikz-pgfplots.md` hiragino-postscript-name](tikz-pgfplots.md#hiragino-postscript-name)。

### 数式 + 日本語を mix する align 環境

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

### print fidelity を A4 強制したい場合

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
