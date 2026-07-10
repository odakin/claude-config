<!-- doc-meta
when: 論文投稿ポータル (ScholarOne / Editorial Manager / arXiv) へ submit するとき
category: paper
summary: 論文投稿ポータル (ScholarOne / Editorial Manager / EJP / arXiv) 経由の submit の落とし穴 (= Chromium fork の広告 blocker で generic upload error → Safari 第一選択 / 非標準 TeX package 〔revtex4-2 / tikz-feynman〕 を source zip に同梱 / cover page metadata form は LaTeX source と独立管理 / Type1 font は soft 要求 / arXiv は最終 PDF 拒否 = source から自動ビルド 〔v1/v2 共通〕)、 投稿 checklist 込み、 paper-audit / rebuttal-letter / peer-review-workflow / erad-submission の 5 兄弟目 (投稿 side)
-->
# Paper Submission Workflow (= 投稿ポータル経由の落とし穴と定型対処)

論文投稿ポータル (Springer ScholarOne Manuscripts / Elsevier Editorial Manager / IOP EJP submission / arXiv 等) 経由で journal / preprint server に投稿する時の、 **ポータル固有の落とし穴 + 定型的な対処** の SoT。 Overleaf 連携経路は別 doc: [`overleaf-integration.md`](overleaf-integration.md)。

**Sibling docs** (= 論文 lifecycle を分担): 自分 paper の internal audit = [`paper-audit.md`](paper-audit.md) / 投稿後の referee report への返信 = [`rebuttal-letter.md`](rebuttal-letter.md) / 自分が referee として外部評価 = [`peer-review-workflow.md`](peer-review-workflow.md) / grant 申請 = [`erad-submission.md`](erad-submission.md)。 本書 (= paper submission) はこれら 4 の方向違いで、 完成した論文を journal / arXiv に **出す**側。

## <a id="tldr"></a>TL;DR — 詰まりやすい 5 点と第一選択の対処

| # | 症状 | 第一選択の対処 |
|---|---|---|
| 1 | 投稿ポータルで generic upload error (Editorial Manager 系) | **別ブラウザで retry** (§[browser-fallback](#browser-fallback))。 font/PDF/ファイル名の技術問題より先にブラウザを疑う |
| 2 | "Missing resources referenced by the TeX document" (revtex4-2 / tikz-feynman 等が Missing 判定) | ローカル TeX 環境から `.cls`/`.sty`/`.rtx`/`.tex`/`.lua` を **source zip に同梱** (§[package-bundling](#package-bundling)) |
| 3 | Cover page の author affiliation が LaTeX 修正で追随しない | **Authors & Institutions form を別途更新** (§[form-vs-source-independence](#form-vs-source-independence)) |
| 4 | "PDF should embed only Type1 fonts" 警告 | figure PDF に TrueType Courier 混入 が典型。 soft 要求のため実運用では通ることが多い、 blocker になったら figure 再生成 (§[type1-fonts](#type1-fonts)) |
| 5 | arXiv upload で processing error | **PDF は source tarball に含めない** — arXiv は source から自動ビルド (v1 / replace-file 全 version 共通、§[arxiv-source-only](#arxiv-source-only)) |

## <a id="browser-fallback"></a>1. Portal upload の generic error → 別ブラウザで retry

Editorial Manager 系ポータル (ScholarOne / Elsevier EM / EJP) のファイル upload が **generic "An error has occurred" で失敗した場合、 まず別ブラウザで retry**。 font / PDF format / ファイル名の技術問題を疑う前に、 まずブラウザを疑う。

### 症状のパターン

- エラーメッセージが具体的原因を示さない ("An error has occurred. Please try again. If the problem persists, please contact the Support Team")
- ファイルサイズはポータル上限に対して余裕あり
- 同じファイルが別ブラウザで一発通過する

### 原因 (経験則)

- **Chromium fork の広告 blocker / fingerprinting 対策が portal の XHR/multipart POST を interfere**。 Brave の Shields、 一部の Chrome 拡張、 privacy focused browser の tracker blocker 等が典型
- ScholarOne 側は多段の cookie / redirect / CSRF token を使うため、 aggressive shield と衝突しやすい
- Incognito でも同じ挙動なら Chromium fork 特有の互換性問題、 vanilla Chrome or Safari に切替

### 対処 (試行順、cheap → costly)

1. **Safari / vanilla Chrome で retry** — 最 cheap で確実
2. Brave 等の Shields を該当ドメイン (例: `mc.manuscriptcentral.com`) で off にして retry
3. Incognito でも同じなら別ブラウザに完全移行

### 用件別の default choice

- **論文投稿ポータルは「初期から Safari or vanilla Chrome で試す」を default** に (= 最初から Chromium fork の広告 blocker 系を回避)
- 個人環境で「Chromium fork = 自動化用 / Safari = 外部発信用」の役割分離を持っているなら、 投稿は Safari 側

### 実例

- 2026-07-08 EPJC (ScholarOne Manuscripts) Step 2 File Upload = Brave で generic error 連発、 Safari で 同ファイル 一発通過。 files はそれぞれ 1.14 MB (session 上限 488 MB の 0.5%)、 Type1 warning は blocker でなかった。

## <a id="package-bundling"></a>2. "Missing resources" → 非標準パッケージを zip に同梱

Editorial Manager 系ポータルの TeX 環境は **最小構成** で、 revtex4-2 / tikz-feynman 等の「業界標準だが core LaTeX ではない」 パッケージを **Missing 判定** する。 該当エラー例:

```
There are missing resources referenced by the TeX document, you must upload
all necessary resources for your TeX document before you may submit your
manuscript. File names are case sensitive.

revtex4-2 [Missing]
tikz-feynman [Missing]
```

### 対処: ローカル TeX 環境から必要ファイル一式を copy して source zip に同梱

```bash
# パッケージの実体所在を確認
kpsewhich revtex4-2.cls
# 補助ファイル (.sty / .rtx / .tex / .lua) の同ディレクトリを見る
ls "$(kpsewhich revtex4-2.cls | xargs dirname)"

# submission 用 dir に一式 copy (revtex4-2 例)
cp /usr/local/texlive/2025/texmf-dist/tex/latex/revtex/*.{cls,sty,rtx} <submission-dir>/
# tikz-feynman 例
cp /usr/local/texlive/2025/texmf-dist/tex/latex/tikz-feynman/*.{sty,tex,lua} <submission-dir>/

# sanity build (kpathsea は同ディレクトリを先に探す)
(cd <submission-dir> && latexmk -pdf <main>.tex)
```

### 同梱する典型ファイル

**revtex4-2 一式** (13 files):
- `revtex4-2.cls` (メインクラス)
- `revsymb4-2.sty`
- `ltxdocext.sty` `ltxfront.sty` `ltxgrid.sty` `ltxutil.sty`
- `aps4-2.rtx` `aps10pt4-2.rtx` `aps11pt4-2.rtx` `aps12pt4-2.rtx`
- `aapm4-2.rtx` `aip4-2.rtx` `apsrmp4-2.rtx` `sor4-2.rtx`

**tikz-feynman 一式** (5 files):
- `tikz-feynman.sty`
- `tikzfeynman.keys.code.tex`
- `tikzfeynman.patch.3.0.0.lua` `tikzfeynman.patch.3.0.1.lua`
- `tikzlibraryfeynman.code.tex`

### upload 分離 pattern (2 経路)

ポータルによっては source zip とは別に「LaTeX Supplemental File」として **パッケージ専用の追加 zip** を投げられる。 これによりメインの source zip を軽く保てる。 ScholarOne では File Designation = "LaTeX Supplemental File" or "Suppl File not for Review" で designation 可能。

### 追加 Missing が出た場合

同じ経路で `MnSymbol` / `braket` / `slashed` / `mathrsfs` 等を追加。 `kpsewhich <package>.sty` で場所を特定して copy。

### 実例

- 2026-07-08 EPJC = revtex4-2 と tikz-feynman が Missing 判定、 上記手順で 19 files を追加 zip (150 KB) として upload、 Step 2 通過

## <a id="form-vs-source-independence"></a>3. Cover page metadata は LaTeX と独立

投稿ポータルの **Authors & Institutions form** (ScholarOne Step 3、 Editorial Manager の Author list 相当) は、 提出する LaTeX source の `\author{}` / `\affiliation{}` block と **独立に管理**される。 LaTeX source を修正しても cover page metadata は自動追随しない。

### 落とし穴

- LaTeX 側で affiliation を更新 → source zip 再 upload → proof PDF の paper title page は正しく反映
- しかし **proof PDF の cover page (ScholarOne 生成の manuscript header)** は初回登録時の form value のまま → LaTeX 修正が反映されず
- Editor / referee は cover page の author list を見るため、 form が古いままだと author metadata が矛盾

### 対処

**LaTeX 側で author info を修正した時は、 必ず Authors & Institutions form も同時に更新**。 修正対象:

- Author name (綴り、 middle name の有無、 diacritics)
- Institution (大学名)
- Department (学科名 — 特に大学の英文組織名変更後は要注意)
- Email address
- ORCID
- 責任著者フラグ

### 実例

- 2026-07-08 EPJC = 責任著者の `\affiliation{}` 内 department name を旧名から現行名に修正 + source zip 差し替え、 しかし ScholarOne cover page が旧 form 値のまま → Step 3 form で 別途更新 → proof 再生成 で cover page も正しい表記に。 form 修正時に一時的に語順ミス (単語順を反転してしまう typo) を経て 3 回目で確定 = form 修正時も丁寧に (LaTeX source の literal 値と form 入力の literal 値が **両方合致** して初めて proof も cover page も正しくなる)。

## <a id="type1-fonts"></a>4. PDF Type1 font 要求

EPJC (と他の一部 journal) は **"The PDF file should embed only Type1 fonts"** を推奨する。 実運用では TrueType 混入は **soft 要求** で受理されることが多いが、 flag される可能性はある。

### 混入源の典型

- **figure PDF に埋め込まれた TrueType Courier** (macOS で作られた figure は Courier を default fallback として TrueType 埋め込みしがち、 `MacRomanEncoding` が signature)
- `hyperref` の url/eprint monospace 描画で Courier がフォールバック

### 診断

```python
import fitz  # PyMuPDF
doc = fitz.open("manuscript.pdf")
fonts = set()
for pno in range(len(doc)):
    for f in doc[pno].get_fonts(full=True):
        fonts.add((f[2], f[3]))
non_type1 = [(t, n) for (t, n) in fonts if t != "Type1"]
print(f"Non-Type1: {non_type1}")
```

### 対処 (優先度順)

1. **無視して投稿** — soft 要求のため、 実運用では通ることが多い。 arXiv v1 が同 font 構成で受理されているならまず問題なし
2. **`\urlstyle{rm}` を hyperref の後に追加** — hyperref 起因の Courier を除去 (⚠️ **`\usepackage{url}` を hyperref 直後に書く場合、 `\urlstyle{rm}` は `\usepackage{url}` の後に置かないと reset される**)
3. **figure PDF を再生成** — matplotlib / TikZ / Inkscape の設定で Type1 出力を強制、 macOS の Preview 経由の PDF export は避ける
4. **投稿後に blocker になったら editor に相談** — proof stage で fix する時間があることが多い

### 実例

- 2026-07-08 EPJC = 5 figure PDF 全てに TrueType Courier が MacRomanEncoding で埋め込み、 hyperref の URL 経由 Courier も 1 個。 `\urlstyle{rm}` 追加は無関係 (原因は figure)。 arXiv v1 が同 font 構成で受理済のため EPJC 投稿でも blocker にならなかった。

## <a id="arxiv-source-only"></a>5. arXiv は最終 PDF を受け付けない (source-only、v1 / v2 共通)

arXiv は **source から自動ビルド** する processing model なので、 **v1 initial upload でも v2 以降の replace-file でも、 tarball / zip に PDF を含めると processing error になる**。 「v2 特有のルール」 ではなく arXiv 一般則。

### 常に source-only で、v1/v2 で構成を揃える

typical 構成 (revtex 系 pdflatex 論文):

```
draft_A.tex           # 本文
ref.bib               # BibTeX ソース
utphysmod.bst         # non-standard BibTeX スタイル (arXiv 標準に無いので同梱)
Figures/
  <figure>.pdf        # 各図
```

### 含めるべきでないもの

- **最終 PDF** (arXiv が生成)
- `.aux` / `.log` / `.out` / `.blg` / `.fdb_latexmk` / `.fls` / `.toc` 等のビルド artifact
- macOS の `.DS_Store`
- `draft_ANotes.bib` 等の latexmk 副産物

### `.bbl` を含めるか

- **v1 パターン踏襲**: 含めない (arXiv が bibtex 実行)、 `.bst` を代わりに同梱
- **modern robust pattern**: `.bbl` を含める (arXiv が bibtex を skip、 build 高速化 + non-standard bib entry の 互換性 risk 軽減)
- どちらも動く、 v1 が既に受理されているなら **v1 パターンを踏襲** が安全

### submission bundle を作る手順

```bash
# 投稿用 dir を作成
mkdir -p submission/arxiv-vN
cp <paper>/draft_A.tex <paper>/ref.bib <paper>/utphysmod.bst submission/arxiv-vN/
mkdir -p submission/arxiv-vN/Figures
cp <paper>/Figures/*.pdf submission/arxiv-vN/Figures/  # 本文で参照される図のみ

# sanity build (aux 削除)
(cd submission/arxiv-vN && latexmk -pdf draft_A.tex && \
 rm -f draft_A.{aux,log,out,bbl,blg,fdb_latexmk,fls,toc,pdf} draft_ANotes.bib)

# zip 化
(cd submission/arxiv-vN && zip -r ../arxiv-vN-source.zip . -x "*.DS_Store")
```

### 実例

- 2026-07-08 arXiv 2606.19548 v2 replace = v1 と同構成 (draft_A.tex + ref.bib + utphysmod.bst + Figures 2 枚、 6 files 142 KB、 PDF 非同梱) で共著者に配布

## <a id="workflow-checklist"></a>投稿 workflow の定型 checklist

新しい journal に投稿する時、 以下を **submission 開始前** に整えると詰まりが減る:

1. **ブラウザ選択** = Safari / vanilla Chrome (§[browser-fallback](#browser-fallback))
2. **source zip 準備**
   - Main tex + bib + bst + figures (本文参照分のみ)
   - `.bbl` を含めるかの方針決定 (v1 パターン踏襲 or modern robust)
   - **非標準パッケージを事前同梱** (revtex4-2, tikz-feynman 等、 §[package-bundling](#package-bundling))
   - aux ファイル削除
3. **PDF 版**
   - journal 用は最終 PDF 同梱 (Main Document)、 arXiv 用は PDF 含めない (v1/v2 共通、§[arxiv-source-only](#arxiv-source-only))
   - Type1 font 状況を確認 (§[type1-fonts](#type1-fonts))
4. **Authors & Institutions form**
   - LaTeX の `\author{}` と form 入力を **両方** update (§[form-vs-source-independence](#form-vs-source-independence))
   - 特に Department 名の変更 / diacritics / ORCID
5. **Cover letter draft**
   - Novelty 1 段落 + arXiv reference + 事前 feedback record + statement of not published elsewhere + 責任著者 sign-off
6. **Referee suggestion**
   - 事前 feedback をくれた人物は "preferred reviewer" に入れない (COI 回避)、 editor に入れる (editorial handling)
   - topic match を第一、 personal connection は editor 推薦での compensating factor
7. **投稿完了後**
   - Manuscript ID を SESSION.md 系に記録
   - 受領確認メールを共著者に転送
   - arXiv v2 upload zip を投稿担当共著者に配布

## <a id="refine-history"></a>実例と refine 履歴 (= 新例が出たら本 convention を refine)

- **2026-07-08 EPJC 投稿 (neutrino-real-virtual)** = ScholarOne Manuscripts、 Brave で Step 2 failed → Safari 通過 (§[browser-fallback](#browser-fallback))、 revtex4-2 と tikz-feynman が Missing → 追加 zip 同梱 (§[package-bundling](#package-bundling))、 affiliation 修正が LaTeX と form で 2 系統管理 (§[form-vs-source-independence](#form-vs-source-independence))、 figure PDF 由来の TrueType Courier は soft 要求で受理 (§[type1-fonts](#type1-fonts))、 arXiv v2 用 zip は PDF 非同梱で共著者配布 (§[arxiv-source-only](#arxiv-source-only))。 Manuscript ID EPJC-26-07-091。
