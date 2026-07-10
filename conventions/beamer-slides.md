<!-- doc-meta
when: Beamer/metropolis で研究スライドを作る・直すとき
category: paper
summary: Beamer/metropolis 研究スライドの技術規約 (= install 不要フォント〔Fira/Harano Aji〕・配色・[shrink] の横縮小罠・standout の \\ 落とし穴・セクション扉を全 TOC+現在強調・PDF ページラベル重複の後処理修正〔page 番号振り直し〕・再現ビルド build.sh・視覚 QA ループ・matplotlib 図生成〔日本語/CIE 厳密スペクトル〕・論文図の領域レンダ抽出・.key 不可。giving-talks.md〔中身/作法〕と相補)
-->
# Beamer (metropolis) 研究スライド — ビルド・図・落とし穴

LaTeX Beamer(特に **metropolis** テーマ)で研究発表スライドを**プログラム的に作る/直す**ときの
技術規約。図の生成・抽出、再現可能なビルド、視覚 QA も含む。**読むタイミング:** Beamer スライドを
作る/直す、発表用の図を生成・論文から抽出する、PDF のページ番号がおかしい、日本語スライドのフォント。

棲み分け(§2 定義は1箇所):
- **発表の中身・作法**(主題選択・3-4 メッセージ・図優先・質問対応 等)= [`giving-talks.md`](giving-talks.md)(Geroch 蒸留)。
- **一般 LaTeX / 図** = [`latex.md`](latex.md) / [`tikz-pgfplots.md`](tikz-pgfplots.md)。本 file は **Beamer 固有**。
- 個人のスタイル選好(odakin)は personal layer 側(layer 1 からは参照しない)。

---

## 1. エンジンとフォント(system install ゼロで)

- **LuaLaTeX + metropolis** を基本にする。`\documentclass[aspectratio=169,11pt]{beamer}` で 16:9。
- **欧文(Fira)**: metropolis は Fira を `\iffontsavailable` で**安全判定**し、無ければ警告して fallback(ハードエラーにならない)。LuaLaTeX なら luaotfload が **TeX 同梱の `fira` パッケージ**を名前解決するので、**system フォント install 不要**で Fira が出る。(XeLaTeX 経路では system に Fira が要ることがある。)
- **日本語(CJK)**: LuaLaTeX + `\usepackage{luatexja}` + `\usepackage[haranoaji,deluxe]{luatexja-preset}`。**TeX 同梱の原ノ味ゴシック(Harano Aji)**を使うので install 不要。`deluxe` で複数ウェイト(和文太字)が効く。XeLaTeX 代替は `xeCJK` + system 和文(例: ヒラギノ)。

## 2. 配色(アクセント)

metropolis のパレットを上書き:

```latex
\setbeamercolor{frametitle}{bg=<accent>}
\setbeamercolor{progress bar}{fg=<accent>}
\setbeamercolor{alerted text}{fg=<accent2>}   % \alert{} の色
\setbeamercolor{title separator}{fg=<accent>}
\setbeamercolor{palette primary}{fg=white,bg=<dark>}  % ← standout / section page の背景はこれ
```

`palette primary` が **standout フレームとセクションページの背景色**を司る。

## 3. `[shrink]` の罠(重要)

- `[shrink]` は内容がはみ出したとき**縦横を一律(uniform)に縮小**して枠に収める。
- 副作用: 疎なスライドを「埋めよう」とフォントを大きくすると shrink が発動し、**テキスト箱が横にも縮んで全幅に届かず**、改行も縮小前(大フォント)レイアウトで固定 → 「無駄に幅が狭い + 不自然な改行」になる。
- **縮小させずに埋める正解 = `[shrink]` が発動しない範囲のフォントサイズを選ぶ**(全幅・自然改行のまま)。発動の有無はビルドログを `grep -i shrink` で確認(空 = 縮小なし = 全幅維持)。
- `[shrink=N]` は実測上「はみ出した時だけ必要分縮小」、N は**警告閾値**(強制最小縮小ではない)。安全網として残しつつ、フォントを発動しないサイズに合わせるのがコツ。
- 密な補足/付録スライドは「大フォント + shrink(縮小=狭幅)」より「`\small` 等で全幅」の方が読みやすい。

## 4. standout フレームの `\\` 落とし穴

`[standout]` 内で、サイズ変更グループ(例 `{\fontsize{60}{68}\selectfont ...}`)の直後に `\\[..]` を置くと
`! LaTeX Error: There's no line here to end.` が出る。→ 要素を1つにするか、空行(段落区切り)+ `\vspace` で代替。

## 5. セクション扉を「全セクション一覧 + 現在以外を薄く」にする

```latex
\usetheme[...,sectionpage=none]{metropolis}      % 既定のセクション扉を無効化
\setbeamertemplate{section in toc shaded}[default][30]  % 非現在を 30% 不透明
\AtBeginSection[]{\begin{frame}[c]{今日の道のり}
  \tableofcontents[currentsection,hideallsubsections]\end{frame}}
```

現在セクションが通常色、他がグレーの「現在地」扉になる。

## 6. フッタ番号

metropolis の `numbering=fraction` は standout/plain/セクション扉が混ざると**誤カウント**(欠番 + 「X/Y」重複)。
`numbering=none` で消すのが綺麗。通し番号が欲しいなら §7 の PDF ページラベルで持たせる。

## 7. PDF ページラベル重複と修正(=「ページ番号振り直し」)

- **症状**: ビューア(Preview のサムネイル等)で論理ページ番号が重複。例: タイトルと次スライドが両方「1」、セクション扉が直前番号を継承。
- **原因**: beamer は PDF の `/PageLabels` を**フレーム番号**(`\thepage = \insertframenumber`)で書くため、タイトル+次・非増分フレームが番号を共有する。`\hypersetup{pdfpagelabels=false}` では**直らない**(beamer が shipout で再設定、`\AtBeginDocument` でも勝てない)。
- **修正 = ビルド後に PDF を後処理**(PyMuPDF):

```python
import fitz, os
d = fitz.open("deck.pdf")
d.set_page_labels([{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 1}])  # 1,2,3,...
d.save("deck.tmp.pdf"); d.close(); os.replace("deck.tmp.pdf", "deck.pdf")
# fallback: カタログの /PageLabels を消す(d.xref_set_key(d.pdf_catalog(),"PageLabels","null"))→ 物理番号
```

- これを `build.sh` に入れて再コンパイルでも壊れないようにする。**落とし穴**: 非対話 shell(`zsh build.sh`)では `python3` が対話時と**別の python**(PATH が `.zshrc` 由来だと未適用)に解決され、PyMuPDF 無しのことがある。fitz を持つ python を自動探索:

```sh
PYEXE=""
for PY in python3 /usr/bin/python3 /Library/Developer/CommandLineTools/usr/bin/python3 \
          /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c 'import fitz' >/dev/null 2>&1; then PYEXE="$PY"; break; fi
done
```

## 8. 再現可能なビルド wrapper

`build.sh` = `latexmk -lualatex -interaction=nonstopmode deck.tex` → `python3 fix-pagelabels.py`。
metropolis は 2 パス以上必要(latexmk が面倒を見る)。「正規ビルドは ./build.sh」と .tex 冒頭にコメント。

## 9. 視覚 QA ループ(「コンパイル成功」を信用しない)

コンパイル → 各ページを PNG 化(PyMuPDF) → **画像を実際に見る** → 直す → 反復。ログでは捕れない
「下端での見切れ・色背景上の低コントラスト文字・不自然な改行・軸が欠けた図」を捕まえる(= `tikz-pgfplots.md` の
「compile 成功 ≠ visual 成功」 と同型)。

```python
import fitz
d = fitz.open("deck.pdf")
for i, p in enumerate(d):
    p.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(f"/tmp/p{i+1}.png")
```

ログ: `grep "^! " deck.log`(エラー)/ `grep Overfull deck.log`(はみ出し)/ `grep -i shrink deck.log`(意図しない縮小)。ただし**最終判定はレンダ画像**。

## 10. 図は「拾う」のでなく「生成する」

- **matplotlib でオリジナル模式図**(著作権リスクなし): 波束(Gauss 包絡 × 搬送波で「波束サイズ σ ≠ 波長 λ」を可視化)/「予想 vs 観測」曲線(`fill_between` でズレを塗る)/散乱模式(`patches.Circle` + 放射状の `annotate('', arrowprops=...)`)。`transparent=True, bbox_inches='tight'` で保存すると任意の背景に載る。
- **背景グラデ**: numpy で色を線形補間 → PIL `Image.fromarray`。
- **matplotlib の日本語ラベル**: `fm.fontManager.addfont(<CJK .otf>)` + `rcParams['font.family']=fm.FontProperties(fname=<otf>).get_name()`。TeX 同梱の Harano Aji OTF が install 不要で便利。`rcParams['axes.unicode_minus']=False`。
- **厳密な可視スペクトル(波長→色)**: CIE 1931 等色関数 → XYZ → sRGB。CMF は **Wyman–Sapra–Wenzel (2013) の多ローブ・ガウス近似**を使えばデータ表不要。手順: `XYZ=(x̄,ȳ,z̄)(λ)` → `RGB_lin = M_{XYZ→sRGB}·XYZ` → 負値(色域外)をクランプ(境界へデサチュレート)→ 正規化 → sRGB ガンマ。区分線形(Bruton 流)より色相が正確。

## 11. 論文の図を流用する(文献紹介系)

- 埋め込みラスタ: `page.get_images()` + `fitz.Pixmap(doc, xref)`。**ただし軸ラベル/凡例/inset は別ベクタで raster に含まれない**ことが多く、曲線だけ取れて軸が欠ける。
- 推奨 = **領域レンダリング**: `page.get_pixmap(matrix=fitz.Matrix(4,4), clip=fitz.Rect(x0,y0,x1,y1))`。`page.get_image_rects(xref)` で図の位置を取り、軸ラベルを含むよう clip を広げ、論文側キャプションは除外(自分のキャプションを付ける)。
- 紹介対象論文の図を、出典明記で当該論文の発表に使うのは正当な学術利用。装飾目的で web の著作権画像を拾わない(§10 でオリジナル生成 or ライセンス明確な素材)。

## 12. 出力形式の現実

- **`.key`(Keynote)はバイナリ package(IWA)で直接編集不可**。Keynote ユーザーへ渡すなら `.pptx`(Keynote が import 可)か、Beamer PDF で投影。
- **Marp**(Markdown → PDF/PPTX)はデッキをテキスト管理したい時の選択肢。レイアウト自由度は Beamer より低い。
</content>
