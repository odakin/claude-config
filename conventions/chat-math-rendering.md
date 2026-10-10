<!-- doc-meta
when: チャットの返事に数式を書くとき (読ませる数式・コピペ用の LaTeX の両方) + 返事の数式が生の TeX のまま表示されたとき + 数式の書き方の規則を CLAUDE.md や template に置くとき
category: harness-core
summary: チャットの数式の書き方は返事を読む画面で決まる。 desktop の Code タブは KaTeX で描くので、 描ける区切りと KaTeX にあるコマンドだけを使う (`\[…\]`・physics パッケージ・行またぎ・表のセルの `|`・日本語の直後の `\(` は生表示)。 CLI のターミナルは描かないので Unicode。 コピペ用の LaTeX は code block
-->
# チャットでの数式の書き方

返事の数式がどう見えるかは、 **返事を読む画面** で決まる。 同じ書き方が、 ある画面では描かれ、 別の画面では生の TeX のまま出る。 書く前に、 読む画面を決める。

## <a id="by-surface"></a>画面ごとの書き方

| 画面 | 数式の描画 | 書き方 |
|---|---|---|
| Claude desktop app の Code タブ | KaTeX で描く | LaTeX を [#code-tab-katex](#code-tab-katex) の規則で |
| Claude Code CLI (ターミナル) | 描かない | `_` / `^` + Unicode (σ ∂ ℏ ∫ など) |
| 画面が決まらない (複数の画面で読まれる・どれか分からない) | — | Unicode (どの画面でも崩れない) |
| コピペして `.tex` に貼る LaTeX 片 | (読ませない) | code block = [latex.md#latex-in-chat-codeblock](latex.md#latex-in-chat-codeblock) |

Code タブかどうかは、 system prompt の記述 (Claude desktop app の Code tab で動いている旨) か、 環境変数 `CLAUDE_CODE_ENTRYPOINT` (= `claude-desktop`) で分かる。 Remote Control でスマホから読む session のように、 同じ session でも読む画面が変わることがある。 迷ったら Unicode。

## <a id="code-tab-katex"></a>Code タブで LaTeX を書くときの規則

実測 (Code タブで 20 件の試験。 アプリ本体 2.26454.2 の描画設定とも照合):

- 区切りは `$…$` (インライン)・`$$…$$` (ディスプレイ)・`\(…\)` (インライン) だけ。 **`\[…\]` は描かれず生のまま出る**。 生で出た文字列はそのまま Markdown に渡るので、 `_{…}` の `_` が強調に取られて添字まで消える。
- 開きの `$` の直後と閉じの `$` の直前に空白を置かない (`$ x $` は生表示)。 インライン数式は 1 行に収める (行をまたぐと生表示)。
- **`\(` の直前には半角空白を 1 つ置く**。 日本語の文字 (読点・括弧を含む) の直後に `\(` を置くと数式の開始にならず、 `\(` と `\)` のバックスラッシュだけが Markdown のエスケープとして消えて `(…)` の生の文字列が出る (本体 2.31226.1 で実測。 同じ返事の中で直前が半角空白か ASCII 文字の式は描かれた)。 「…なので、\(x\) は」 でなく 「…なので、 \(x\) は」 と書く。
- 表のセルに `|` や `\|` を含む数式を書かない (`$\langle\psi|\phi\rangle$` はセルの区切りに取られる)。 `\mid` / `\vert` / `\lVert` で代えるか、 表の外に出す。
- コマンドは KaTeX にあるものだけ。 **physics パッケージは不可** (`\dd` `\dv` `\pdv` `\abs` `\norm` `\ev` `\mel` `\comm` `\tr` `\Tr`) → `\mathrm{d}x`, `\frac{\partial f}{\partial x}`, `|x|`, `\|v\|`, `\langle A\rangle`, `\operatorname{Tr}` で書く。 `\mathbb{1}` `\mathds{1}` `\id` も不可 (→ `\mathbb{I}` か `\mathbf{1}`)。 repo のプリアンブル固有のマクロも不可。
- 使えるもの (実測): `\ket` `\bra` `\braket` `\mathscr` `\mathfrak` `\bm` `\boldsymbol` `\operatorname` `\dfrac` `\lVert` `\coloneqq` `\hbar`。
- 数式を code block や backtick の中に入れない (描かれない)。 `$$` の block の内側に空行を置かない。
- 長い導出はチャットに書かず、 `.md` ファイルや Artifact に出す。

**未知のコマンド 1 つで式全体が生になる理由**: 描画器は KaTeX をエラーを投げない設定で呼び、 エラーの色を地の文と同じにしている。 KaTeX は解釈できない式を丸ごと元の文字列として出すので、 式全体が普通の文字で出る (赤字にならないので、 壊れたと気づきにくい)。

**版で変わる**: 上は 2.26454.2 での挙動 (`\(` の直前の空白の規則だけ 2.31226.1)。 描画器はアプリの中でも画面ごとに設定が違う (ドル記号 1 個の数式を切っている描画器もある)。 規則が合わなくなったら、 [claude-app-bundle-reading.md](claude-app-bundle-reading.md) の手順で本体を読み直すか、 画面で 1 回試す。

## <a id="where-to-put-the-rule"></a>規則をどこに置くか

規則の本文は本 doc だけに置き、 CLAUDE.md や template には要点と本 doc への参照だけを書く (同じ本文を複数の file に写すと、 片方だけ直る)。 個人層で書き方を絞る (例: 画面によらず常に Unicode) のは自由。 その時も、 どの画面が何を描くかの事実は本 doc に合わせる。
