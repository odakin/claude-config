<!-- doc-meta
when: TikZ / pgfplots を含む LaTeX project で図を作るとき
category: paper
summary: TikZ/pgfplots 固有 gotchas（infographic / poster / 1 枚 figure 制作で必読、 latex.md と併読）
-->
# TikZ / pgfplots 規約

TikZ や pgfplots を含む LaTeX project で適用。 一般 LaTeX 規約は [`conventions/latex.md`](latex.md)、 PDF 視覚検証規律は [`latex.md` pdf-visual-verification](latex.md#pdf-visual-verification) を併読。

本 file の知見は **cosmology infographic 制作 (= [odakin/infographics](https://github.com/odakin/infographics) `cosmology-history/`) で多数 iteration を user feedback 駆動で回した記録** (= 2026-05-19 初版 20 iteration + 2026-06-02 に密度プロット再設計で更に多数、 後者で「床塗り closedcycle」「named anchor の scope 非追従」「中央寄せ＝平行移動」「aspect 変更時の回転再計算」 を追加。 2026-07-10 には共著論文の集合図・写像図 〔= 手描きホワイトボードの paper 図化〕 を author feedback 駆動で ~10 iteration 回し、 §集合図の anchor / §セマンティック配色の移植 / §数値検証 / §縦積み包含鎖 を追加)。 大半は「公式 doc 通りには動かない / 動くが直感に反する」 系の罠で、 1 度踏むと原因特定に 1-2 turn 浪費する。

## pgfplots `width` / `height` は axis title / xlabel を含めて bounding しない

**通説**: `width=Wmm, height=Hmm` は axis 全体の outer bounding box。 label / tick / title 全部含まれて W × H に収まる。

**実態**: ylabel (rotated) や xlabel は **outer box の外側** に renderer される。 axis ticks までは width/height に収まるが、 axis title はその外。

**症状**: card 内に pgfplots を置くと、 「width = card_width - margin」 で計算したのに ylabel / xlabel が card 境界からはみ出す。

**対処** (= 3 段組合せ):

1. **scope を内側にずらす**: `\begin{scope}[shift={(x, y)}]` の x/y を card 境界から十分内側にする。 axis 外側 label area の分を margin で抜く
2. **axis size を縮小**: `width` / `height` を card 利用可能 size より小さく設定
3. **xlabel/ylabel に explicit shift**: `xlabel style={yshift=Nmm}` `ylabel style={xshift=Nmm}` で label 位置を内側に押し込む

```latex
% card 内 199mm × 104mm に plot を収める例
\begin{scope}[shift={(106, 22)}]   % card 左から 16mm、 下から 8mm に scope 原点
  \begin{axis}[
    width=176mm, height=90mm,        % outer は card より十分小さく
    xlabel style={font=\fontsize{8.5}{10}\selectfont, yshift=0mm},
    ylabel style={font=\fontsize{8.5}{10}\selectfont, xshift=3mm},  % 右に 3mm 押し込み
    ...
  ]
    ...
  \end{axis}
\end{scope}
```

3 つの shift の役割は overlap する (= scope shift で全体を内側に、 size 縮小で更に縮め、 label 個別 shift で微調整)。 1 つだけでは不十分なケースが多い。

## pgfplots は outer top と data top の間に internal padding を持つ

**症状**: subtitle や caption を pgfplots 環境の **外** に node として置くと、 axis outer top との visual gap が closing できない。 外部 node を outer top ぎりぎりに置いても、 「subtitle と data 領域 (era label 等)」 の間に 3-5mm の空白が残る。 user 視点では「タイトル下に無駄な余白」 と認識される。

**原因**: pgfplots は outer box 内部に inner padding を確保している (= y-axis tick label と data 領域の間、 data 領域の上下に作業空間)。 outer top 自体を外部から押し込んでもこの padding は埋まらない。

**対処**: subtitle / 補助 caption を **`title=` axis option 経由で axis 環境内** に置く。 padding zone がそのまま subtitle 空間として利用される。

```latex
\begin{axis}[
  title={%
    \fontsize{10}{12}\selectfont\sffamily\bfseries\color{fgstrong}メインタイトル%
    \\[-0.5mm]%
    \fontsize{7.5}{9.5}\selectfont\normalfont\itshape\color{fgmute}サブタイトル text...%
  },
  title style={
    anchor=south west,
    at={(rel axis cs:0, 1)},
    align=left,
    yshift=0.5mm,
    inner sep=0pt,
  },
  ...
]
```

- `at={(rel axis cs:0, 1)}` で title 起点を data area の左上に置く
- `anchor=south west` + multi-line で title が上向きに伸び、 padding zone を埋める
- `\\[-0.5mm]` で 2 行の間も詰める
- 外部 node はもはや作らない (= 重複削減)

**Why**: 外部 node 方式では subtitle と data 間に「padding 高さ ≥ 0 の不可避空白」 が常に残る。 内部 title 方式は padding 空間そのものを subtitle が占有するので **真に gap = 0** が達成できる。

## `\addplot ... node[pos=p, sloped]` の pos は path-length parametric で予測困難

**症状**: log-log plot で `\addplot[smooth, samples=80, domain=1e-7:2]` を作り、 `node[pos=0.5, sloped, anchor=south]` で line label を attach すると、 想定外の位置に出る。 特に samples を **linear-domain** で取っているとき (= domain=`1e-7:2` は linear sampling、 log sampling ではない)、 大半の sample が x ≈ 2 付近にクラスタし、 視覚的な「線分の真ん中」 と pos=0.5 は一致しない。

**対処** (= 2 択):

1. **explicit `axis cs:` + manual `rotate=`**: 線のどこに label を置きたいか axis 座標で指定、 line slope から visual 回転角を手動計算
   ```latex
   % rad line slope -4 on log-log, plot width 176mm / 7.3 decades = 24mm/decade x,
   % height 90mm / 21 decades = 4.3mm/decade y. Visual slope -4 × (4.3/24) ≈ -0.72.
   % Angle = atan(-0.72) ≈ -36°.
   \node[anchor=center, rotate=-34, inner sep=0.7mm, fill=bgcard, ...]
     at (axis cs:6e-6, 1e13) {放射 $\rho_{\text{rad}} \propto a^{-4}$};
   ```
2. **`samples at`** で log spacing を作り、 そこに pos= で attach。 ただし `samples at` の指定は煩雑

**Why**: `samples=80` は默认 linear spacing。 log-log plot 上で「線の中央」 は log-uniform で測るのが直感的だが、 pgfplots の pos は path-length 基準。 両者がズレる。

**★ aspect を変えたら回転角を都度再計算する (reflex)**: 手動 `rotate=` で線ラベルを線と平行にした後、 **`ymax` / `xmax` / `xmin` / `ymin` / `width` / `height` のどれか 1 つでも変えると** Dx/Dy (= decade 数比) または H/W (= data area 縦横比) が変わり、 線の visual slope が変わる → 回転角がズレる。 角度 = `atan(n × (H/W) × Dx/Dy)` (n = 冪の絶対値、 例 ρ∝a⁻⁴ なら 4)。 H/W は data area の縦横比で、 1 度 visual 一致させた角度から逆算 calibration するのが速い (= cosmology infographic では H/W≈0.49)。 これを怠ると「軸を広げたら線とラベルがズレた」 が必ず起きる (= 本 session で `ymax` を 1e16→1e20→1e30→1e35、 `xmax` を 2→10 と変える度に放射ラベルを -41→-36→-28→-25 と再補正した)。

## TikZ `\foreach` で多変数 + 色名引数は `\col` 等 expansion で失敗

**症状**:
```latex
\foreach \i/\x/\col in {1/1.05e-7/c0, 2/1.5e-7/c1, ...} {
  \node[circle, fill=\col, ...] at (axis cs:\x, 4e-5) {\i};
}
```
で `! Undefined control sequence. \col` が出る。 単純なはずなのに動かない。

**原因**: pgfmath / TikZ math と pgfkeys のスタイル expansion が tangle、 特に `axis cs:\x` の数値 parse と `fill=\col` の color name expansion が干渉する場合がある。

**対処**: 個別 node に展開する。 多少冗長だが reliable。

```latex
\node[circle, fill=c0, ...] at (axis cs:1.05e-7, 4e-5) {1};
\node[circle, fill=c1, ...] at (axis cs:1.5e-7,  4e-5) {2};
...
```

または `\stagebadge{i}{x}{col}` 系の `\newcommand` macro を作って明示展開。

**Why**: pgfmath は `\x` を数値として、 `\col` を color macro として、 同 expansion 中に異なる context で解釈しようとすると失敗する。 macro 展開 timing と expansion context の問題。 動くケースもある (= `\foreach \i/\x in {1/22.5, ...}` のような 2 変数 + 数値のみは安定) ので、 失敗時は個別 node fallback が rule of thumb。

## smooth functional curve は `\draw plot[smooth, samples=N]` を使う、 Bezier 4-segment は angular

**症状**: Higgs potential / Mexican hat / 任意の 4 次関数を `\draw .. controls (a,b) and (c,d) .. (e,f)` 形式の Bezier で描くと、 制御点が少ない (= 4-8 segment) と curve が angular (= 「W 文字風」) に見える。 user feedback で「4 次関数に見えない、 W みたい」 と指摘される類。

**対処**: parametric plot + smooth + 多 sample:

```latex
% V(φ) = c(φ² − v²)² の smooth 描画 (= 100+ samples で滑らか)
\draw[c1, line width=1pt, smooth, samples=120, domain=-2.7:2.7] plot
  ({1.6*\x}, {0.32*(\x*\x - 1.96)*(\x*\x - 1.96) - 1});
```

- `samples=120` で domain を細分、 segment 間の visual 角度を最小化
- `smooth` で点間を Catmull-Rom 系 interpolation
- `\x*\x` で `\x²` (pgfmath は `^` を演算子として認識しないので multiplication で記述)
- 座標スケール調整は `({1.6*\x}, {... mm 単位})` 等で外側に出す

### Mexican hat の aesthetic (= 「W」 に見えない parameter 選び)

Higgs / Mexican hat の cross-section は数学的には W 形状だが、 **central peak の高さ vs outer rim の高さ** の比で見え方が変わる:

- **比 1:1** → 「W」 文字に見える (= 中央山と両端山が同じ高さ)
- **比 1:5 以上** → 「中央 ぺったんこ + 両端急角度」 の sombrero (帽子のつば) 様シルエット、 物理 textbook iconic

`V(φ) = c(φ² − v²)²` の parameter で V(0) = c·v⁴ (中央 peak の高さ)、 V(2v) = c·9v⁴ = 9·V(0) (= 2v 点で 9 倍)。 outer rim を peak の 5 倍以上にするには、 domain を `[-2.5v, 2.5v]` 程度まで広げて outer の急角度部分を含める。

例: `c = 0.32, v² = 1.96` (= v ≈ 1.4)、 domain `-2.7:2.7`:
- V(0) = 0.32 × 1.96² ≈ 1.23
- V(±1.4) = 0 (minima)
- V(±2.7) = 0.32 × (7.29 − 1.96)² ≈ 9.1
- 比 outer/peak ≈ 7.4 → sombrero 様

## <a id="hiragino-postscript-name"></a>macOS Hiragino font は PostScript 名で指定

**症状**: `\setmainjfont{Hiragino Mincho ProN W3}` は `! Package fontspec Error: The font "Hiragino Mincho ProN W3" cannot be found.` で失敗する。

**原因**: macOS の `.ttc` ファイル (= TrueType Collection) は複数 weight を 1 file 内に持ち、 display name (= "Hiragino Mincho ProN W3") は ファイル内 face を識別する family + style suffix。 fontspec / luaotfload は **PostScript name** (= `HiraMinProN-W3`) で参照する必要がある。

**確認方法**:
```bash
python3 -c "
from fontTools.ttLib import TTCollection
t = TTCollection('/System/Library/Fonts/ヒラギノ明朝 ProN.ttc')
for i, f in enumerate(t.fonts):
    names = {n.nameID: str(n) for n in f['name'].names if n.nameID == 6}
    print(i, names)
"
```

`nameID == 6` が PostScript name。 .ttc 内に複数 face があるので index ごとに違う PostScript 名が出る (= e.g., W3 と W6)。

**対処**:
```latex
\setmainjfont{HiraMinProN-W3}[BoldFont=HiraMinProN-W6]
\setsansjfont{HiraginoSans-W3}[BoldFont=HiraginoSans-W6]
```

macOS 標準で使える Hiragino face の PostScript 名 (W3/W4/W5/W6/W7 等):
- `HiraMinProN-W3` / `HiraMinProN-W6` (= 明朝 ProN)
- `HiraginoSans-W3` / `HiraginoSans-W6` 等 (= 角ゴシック ProN ベース、 W0〜W9 まで)
- `HiraKakuProN-W3` / `HiraKakuProN-W6` (= 角ゴシック ProN)

## TikZ matrix で `text=fgmute` (= 色) と math mode の干渉

**症状**: `\matrix[matrix of nodes, column 1/.style={text=fgmute, font=...}]` で 1 列目に math symbol を入れると、 期待通り fgmute 色で表示されないことがある。 特に math 内の数字や Greek letter が default 色 (= black) に戻る。

**対処**: per-cell explicit `\color{fgmute}` を使う、 または matrix を諦めて explicit `\node` で 1 個ずつ配置 (= alignment は手動で揃える)。 または `\node[...]{$...$}` の color style が math context で reset される問題なので、 `\color{...}` を `$...$` 内に書く:
```latex
{$\color{fgmute} z$ }
```

ただし math fragment color 設定は font / glyph によっては部分的にしか効かない。 visual check 必須。

## `\addplot {f} \closedcycle` は端点を結ぶだけで「床まで」 塗らない

**症状**: 曲線の下を ymin (= axis 床) まで塗りたくて `\addplot[fill=...] {f(x)} \closedcycle;` と書くと「線の下全部」 にならない。 特に **水平線** (= `{1}` のような const) では `\closedcycle` が始点↔終点を結ぶだけ → **面積ゼロで全く塗られない**。 斜め線でも「曲線と〔端点を結ぶ弦〕で囲む三角形」 が塗られ、 「床まで」 ではない。

**原因**: `\closedcycle` は plot path の **最終点を最初点へ直線で結ぶ** だけで、 axis 床 (ymin) へは下りない。

**対処**: 床の 2 隅を明示的に経由して閉じる:
```latex
\addplot[fill=plotrad, fill opacity=0.16, draw=none, domain=1e-9:10, samples=80]
  {1.22e-4 * x^(-4)} -- (axis cs:10,1e-5) -- (axis cs:1e-9,1e-5) -- cycle;
```
const (= 水平線) は `\addplot` を諦めて矩形 `\fill[...] (axis cs:xmin,ymin) rectangle (axis cs:xmax,1);` で塗る。

**実害例**: cosmology infographic で DE (= ρ_Λ=const 水平線) だけ塗られず、 放射/物質も「線の下」 ではなく三角形を塗っていた。 床まで閉じる形に直して 3 成分とも「線の下を重ね塗り (= 下ほど多色が重なる)」 が揃った。

## `current axis.south west` 等の anchor は `\end{axis}` 後・scope shift 下で **追従しない**

**症状**: `\begin{scope}[shift={(x,y)}]` 内で axis を描き、 `\end{axis}` の後に軸外要素 (= 例: off-scale バッジ) を `at ([xshift=-14mm]current axis.south west)` で配置。 ところが **scope の shift を変えても、 軸本体は動くのにこの要素だけ取り残される** (= 元位置に固定される)。

**原因**: scope の `shift` (= canvas transformation) は axis の **描画** には効くが、 `current axis.south west` が返す座標は shift 適用前の値。 named anchor を後から参照すると pre-shift 座標 + 個別 xshift で配置され、 scope shift に連動しない。

**対処**: 連動させたい軸外要素は **軸内の named node** を基準にする。 軸内のバッジ等に名前を付け、 軸外要素をそれ基準に置くと、 基準が軸と一緒に動くので追従する:
```latex
\node[circle, ...] (b4) at (axis cs:3e-9, 4e-5) {4};   % 軸内、 named
...
\end{axis}
\node[circle, ...] at ([xshift=-12mm]b4) {3};          % 軸外、 b4 基準 → 追従する
```

**実害例**: plot を card 中央に寄せようと scope を動かしたら、 off-scale ①②③ バッジだけが card 左端に取り残された (= 軸は動いた)。 ④ を named node 化し ①②③ を④基準に変えて解決。

## plot を card 内で中央寄せ = 単なる平行移動 (= アスペクト比の問題ではない)

**罠**: 「余白を四方均等に」 と言われて **アスペクト比** (= 軸と card の縦横比一致) を持ち出すと話がこじれる。 **「左右均等 ∧ 上下均等」 は単に内容を card 中央に置くだけ** (= 平行移動 = scope shift)、 アスペクト比は無関係。 アスペクト比一致が要るのは **「四辺すべて同じ値」** の場合だけ (= 実用上ほぼ不要)。

**手順** (= 実測 → 平行移動):
1. render PNG から **内容の bounding box を実測** — ink ピクセル (= 彩度 `max-min>45` or 暗さ `max<200`) の min/max を取る。 card border (= 低彩度・明色) は ink 判定に掛からず閾値で自然に除外される
2. 内容 center と card center の差を計算
3. axis scope の `shift` をその差だけ動かす (= **size 不変なので回転や aspect に影響なし**)
4. 再 render → 再実測で左右差・上下差が ~0 か確認 (= 本 session で 0.04mm まで追い込んだ)

§「width/height は label を bound しない」 + §「outer top と data top の internal padding」 で見たように pgfplots の内部 geometry は直感と違う。 **モデルで推論せず実測する** のが速い (= 本 session で誤った geometry モデルから推論して数 turn 浪費した。 既存の本 file を読めば width/height の挙動は書いてあったのに、 読まず再導出した反省)。

## <a id="set-diagram-analytic-geometry"></a>集合図・写像図の anchor は解析的に計算する (目測しない)

数学論文の集合図 (= Venn 風の楕円 + 写像矢印 + 特別な点) では、 **「接している / 被っている / 中心からズレている」 が author の目に即座に留まる**。 目測配置は iteration を浪費する (= 実測 ~10 往復のうち大半が sub-mm の位置調整だった)。 幾何は全部解析的に決められる:

- **楕円周上の点**: 中心 $(x_0,y_0)$、 半径 $(a,b)$ の楕円は $(x_0 + a\cos t,\ y_0 + b\sin t)$。 矢印の始点・終点を「楕円周上ぴったり」 にするにはこのパラメータ点を使う。 既存座標が周上に乗っているかは $((x-x_0)/a)^2 + ((y-y_0)/b)^2 = 1$ で検算
- **外点から円への接線**: 中心 $C$、 半径 $r$ の円と外点 $P$ (距離 $d = |CP|$) の接点は、 $C{\to}P$ 方向から **$\pm\arccos(r/d)$** の角度にある (= 「kernel の縁キワキワから 1 点に潰れる」 系の破線はこれで厳密に引ける)
- **座標を hardcode したら計算式を直上コメントに残す** (= 図形を動かした人が再計算できる。 例: `% C=(-0.8,-0.72), r=0.66, P=(6.6,-0.72); tangent points at +-acos(r/d)`)
- **矢頭のクリアランス**: `very thick` + `Stealth` の矢頭は **~0.2-0.3cm** 占有する。 tip 座標だけでなく「tip から 0.3cm 後方」 が他の stroke に触れないかまで見る (= 「先端の三角が楕円に被って醜い」 は tip が線から 0.1cm 逃げていても起きる)
- **集合内 label は内側に収まるか計算**: 高さ $y$ での楕円の半幅は $a\sqrt{1-(y/b)^2}$。 label の中心 + 半幅がこれを超えたら位置を変える。 境界近くの点の label は下でなく **横 (left=/right=)** に置くと安全
- **矢印は「数学的に正しい集合」 に着地させる**: 写像 $f\colon A \to B$ の矢印は ambient set でなく **像の集合 (= 内側の楕円) の周上** に終点を置く。 逆写像の矢印は定義域 (= その像集合) の周上から出す。 「どの集合からどの集合へ」 が図の主張そのものなので、 便宜配置は誤読を生む
- **弧の caption は弧の頂点に密着**: cubic Bezier `(P0) .. controls (P1) and (P2) .. (P3)` の $t$ での点は $\sum \binom{3}{i}(1-t)^{3-i}t^i P_i$。 頂点付近 ($t \approx 0.35$-$0.5$) を計算して `anchor=south` を直上に置く。 制御点を変えたら再計算 (= §pos=p の「aspect を変えたら回転再計算」 と同型の reflex)

## <a id="standalone-figure-semantic-colors"></a>standalone 図に本文のセマンティック配色を移植する

本文が「概念ごとに色を割り当てる」 論文 (= 例: 古典観測量 = 青 / 量子観測量 = 赤 の color coding) の図を `\documentclass[tikz]{standalone}` で作るとき:

1. **色は名前でなく定義ごとコピー**: stock xcolor の `blue` / `red` は本文の palette と **別の色** (= 特に Okabe–Ito 等の color-blind friendly palette は CMYK 指定)。 本文 preamble の `\definecolor` 行を **verbatim で** standalone に移植し、 同じ色名を使う。 「だいたい青」 で stock 色を使うと author の「論文で定義した通りの色になってる？」 で差し戻される
2. **セマンティック macro の展開は定義を読んでから**: 図中で本文の記法 (= 例: `\rff{R}{\Omega}` = 「R と括弧は青、 引数は黒」) を手展開するとき、 **どの部分にどの色が掛かるかは preamble の macro 定義が正本**。 記憶や見た目からの推測は間違える (= 実測: 状態色を 2 回取り違えた)。 `grep 'Command{\\<name>}' main.tex` して展開する
3. **standalone の必須 package**: `\operatorname` は amsmath、 `\mathscr` は mathrsfs が要る (= 素の standalone では Undefined control sequence)。 本文が使う書体 (= mathsfit 等) は図では `\mathsf` 近似で通ることが多い
4. **図の .tex source は生成 .pdf の隣に置く** (= `fig/name.tex` + `fig/name.pdf`)、 冒頭コメントに compile 行を書く。 共著者が独立に再生成・編集できる

## <a id="numeric-color-glyph-verification"></a>色と glyph の検証は目視でなく PyMuPDF で数値確認

render PNG の目視は **色と字形については信用できない**:

- 細い花文字 (= script 書体) を高倍率で見ると **黒が暖色に見える** (= 実測: 黒指定の $\mathscr{H}$ を橙と誤認して再修正しかけた)
- 低 DPI render では **glyph の形を誤読する** (= 実測: 他論文の上付き $-1$ を「フック付きの特殊記号」 と誤認、 900dpi + 文字コード抽出で普通の minus と確定)

ground truth は PDF の text layer にある:

```python
import fitz
page = fitz.open("fig.pdf")[0]
for block in page.get_text("rawdict")["blocks"]:
    for line in block.get("lines", []):
        for span in line["spans"]:
            txt = "".join(ch["c"] for ch in span["chars"])
            print(repr(txt), "color=%06x" % span["color"], span["font"])
```

- `span["color"]` = 実際に焼かれた色 (= `000000` なら黒で確定)、 `span["font"]` = 実 face、 `ch["c"]` = Unicode codepoint (= glyph の同定)、 `ch["bbox"]` = 高 DPI crop の正確な切り出し座標
- 用途: (a) 色変更が本当に反映されたかの確認 (b) 参照論文の記法の同定 (= 「あの記号は何か」) (c) 特定要素の zoom render の座標取り
- §「compile 成功 ≠ visual 成功」 の render loop と相補 (= layout は目視、 色・字形は数値)

## <a id="vertical-inclusion-stack"></a>横長の包含鎖は縦積み node にする

$A \supset B \supset C$ の鎖が長い名前で横に伸びて不格好なときは、 数学書の塔記法 (= Galois 拡大の図式と同じ) で縦に積む:

```latex
\node[anchor=south, align=center, inner sep=1pt] at (0,1.9)
  {$A$\\
   $\cup$\\
   $B$\\
   $\cup$\\
   $C$};
```

- 縦書きの包含は **cup glyph `$\cup$`** で書く (= どちら向きに 90° 回しても cup 形に収束するので、 rotatebox は不要かつ無意味)
- 同じ図に交わり $\cap$ (= 二項演算子) が居ても混同はまず起きない (= 縦積みは「上下に被演算子」、 演算子は「左右に被演算子」 で構文が割れる)。 気になる場合の実質的代替は横鎖に戻すことだけ
- 集合を名指す最下段の項が、 その集合の図形の真上に来るように積むと「塔 = この図形の名前」 が読める

## サイクル: 「compile 成功」 ≠ 「visual 成功」

TikZ / pgfplots の edit 直後、 `lualatex` exit code 0 + log error 0 でも **以下は普通に起きる**:
- Label が card 境界からはみ出す
- 線が data 領域外まで extend して clip される
- 数式中央揃えが微妙にズレている
- font が想定と違う (= 別 face fallback)

[`latex.md` pdf-visual-verification](latex.md#pdf-visual-verification) で defined されている **render → PNG → 視覚確認** loop を、 TikZ / pgfplots では特に必須化する。 公式 doc 通りに書いても rendering は doc と異なることが多いため、 「公式 doc を引用して fixed と主張」 は使えない (= user に「動いてない」 と指摘される)。

### TikZ / pgfplots 編集後の render reflex

```bash
# 1 行 compile + render (= editor の save hook 化推奨)
lualatex -interaction=nonstopmode FILE.tex && \
  pdftoppm -r 300 -png FILE.pdf /tmp/render && \
  open /tmp/render-1.png
```

`pdftoppm -r 300` で 300 DPI = 印刷品質。 細部の overflow / misalignment まで確認可能。 PIL.crop で局所拡大して特定要素を inspection:
```python
from PIL import Image
img = Image.open('/tmp/render-1.png')
w, h = img.size
img.crop((int(w*0.27), int(h*0.42), w, h)).save('/tmp/zoom.png')
```

### 「fix した」 と user に報告する前に必須化する 3 step

1. **edit → compile → render PNG → 視覚確認**
2. ある特定の要素 (= user feedback の対象、 例: 「subtitle と graph の gap」) が **実際に変わったか** を before/after で比較
3. 周辺要素 (= 同 area の他要素) に **副作用が無いか** scan (= scope shift で xlabel が card 底からはみ出る、 等の cascade)

step 3 を省略すると、 1 修正で別 issue を作り、 user の次 turn で発覚する loop が始まる。 本 session の 20 iteration の半分はこの cascade の発見と修正だった (= 反省)。

## 関連

- 全 LaTeX 規約 (= 数式マクロ規律、 PDF 視覚検証 reflex 等): [`latex.md`](latex.md)
- pgfplots 公式 manual: [pgfplots.sourceforge.net](https://pgfplots.sourceforge.net/pgfplots.pdf)
- 「規律の reflex 化」 関連は owner の personal layer に記録 (= collaborator は access 不要)
