<!-- doc-meta
when: matplotlib で図 (論文・研究費調書・発表スライド・様式) を生成する script を書く/直すとき + 物理の模型から図解 (バナー・表紙・スライドの飾り) を描くとき (#model-based-illustration-check) + 曲線上の点・基準線・必要量に注記と矢印を付けるとき (#annotation-colors-and-arrows) + 図の文字列の数式が `Unknown symbol` で落ちたとき (#mathtext-unsupported-commands)
category: paper
summary: matplotlib 図の「全ラベル枠内」機械 gate (assert_texts_inside = render 済み extent を axes 枠と照合し 1 px 超過で図の生成自体を落とす)・既存図を置換するときの情報 inventory / snapshot / actual-render layering review・機構 fact・射程の限界
-->
# matplotlib 図の QA — ラベルはみ出しは目視でなく機械 gate で落とす

## <a id="label-gate-principle"></a>原則: 図 script は「全ラベル枠内」を assert で保証する

論文・研究費調書・発表スライドの matplotlib 図で「文字が枠からはみ出す」は、**目視レビューでは
構造的に取りこぼす**: 高 dpi PNG の縮小表示では数 px のはみ出しが見えず、1 箇所直すと別の
1 箇所がはみ出す whack-a-mole になる (実測: 人間 flag 3 連発まで気付けなかった)。

根治は**図 script 側に、render 済み extent を axes 枠と照合する機械 gate を組み込み、
1 px でも越えたら図の生成自体を assert で落とす**こと。導入した瞬間に gate が複数の実犯を
px 単位 (右 +13.5 / 右 +17.3 / 下 +3.5 / 下 +3.0) で特定し、1 往復で全滅した。

これは文書 layer の [`latex.md#pdf-line-collision-detection`](latex.md#pdf-line-collision-detection)
(= 生成 PDF の行 bbox 交差判定) と同じ哲学 — **「compile/render 成功 ≠ 視覚的成功」の沈黙故障を、
生成物の幾何を機械照合して build 時に顕在化させる**。図の中は本 doc、組版の行かぶりは latex.md 側。

## <a id="assert-texts-inside"></a>snippet: `assert_texts_inside`

```python
def assert_texts_inside(fig, *axes, tol=2.0):
    """全 ax.text が axes 枠内に収まることの機械 gate。

    目視レビューは縮小表示で数 px のはみ出しを見逃す。 label を足す・動かす
    たびにこの assert が render 済み extent で検査するので、 はみ出しはビルド時に落ちる。
    軸ラベル・title・legend は対象外 (ax.texts のみ = data 座標の text)。
    """
    fig.canvas.draw()
    bad = []
    for ax in axes:
        bb = ax.get_window_extent()
        for t in ax.texts:
            tb = t.get_window_extent()
            if not (tb.x0 >= bb.x0 - tol and tb.x1 <= bb.x1 + tol and
                    tb.y0 >= bb.y0 - tol and tb.y1 <= bb.y1 + tol):
                over = (round(bb.x0 - tb.x0, 1), round(tb.x1 - bb.x1, 1),
                        round(bb.y0 - tb.y0, 1), round(tb.y1 - bb.y1, 1))
                bad.append((t.get_text()[:18].replace("\n", "/"), "px over (L,R,B,T):", over))
    assert not bad, bad
```

呼び出しは `fig.savefig(...)` の**直前**に `assert_texts_inside(fig, ax)` (複数 axes 可)。

## <a id="label-gate-mechanics"></a>機構 fact (実測)

- **`fig.canvas.draw()` が必要** (Agg backend で OK)。extent は figure 座標 (px)。
- **対象は `ax.texts` のみ** = `ax.text()` / `ax.annotate()` の data 座標 text。
  xlabel / ylabel / title / legend / tick labels は構造的に枠外が正しいので対象外。
- assert の失敗 message に**ラベル先頭 18 字 + 4 辺の超過 px** を出すのが実用の肝
  (= どのラベルをどっちへ何 px 動かすかが 1 発で分かる。負値 = 枠内マージン)。
- `tol` は 2 px 程度 (anti-alias / rounding 吸収)。
- log 軸でも extent は px なのでそのまま効く。
- ⚠️ **`bbox_inches="tight"` は gate の代替にならない、むしろ発見を遅らせる**: はみ出した
  text を canvas 拡張で「保存」してしまうため、gate 無しだと PNG 上では「はみ出しても
  欠けずに見える」= レイアウト崩れに気付くのがさらに遅れる (これも gate が要る理由)。

## <a id="label-gate-scope-limits"></a>限界: gate の射程は axes 矩形のみ

- **射程 = axes の矩形枠との包含判定だけ**。「斜め線 (領域境界) の内側に収める」
  「ラベル同士の相互重なり」は射程外 → そこは文言短縮・配置で担保し、**目視 1 回で確認**する
  (導入当日にも「枠内だが領域外」の残余 1 件が実際に出た。gate を過信しない)。
- 図の外側 (caption との衝突・本文との行かぶり) は文書 layer の担当 =
  [`latex.md#pdf-line-collision-detection`](latex.md#pdf-line-collision-detection)。

## <a id="figure-replacement-information-audit"></a>既存図の置換は情報 inventory → 一旦 hoist → 明示的に prune

共同著者や過去の自分が作った図を描き直すとき、見た目の改善だけで置換すると、旧図が担っていた情報が黙って消える。着手前に旧図と caption から、少なくとも配置・座標と向き・時間窓・物体や検出器の範囲・重なりや因果関係・代表値と readout・記号対応・極限や適用条件を列挙する。新図の各項目に `preserved`、`translated`、`omitted by explicit author decision` のいずれかを付ける。判断不能を「不要」として落とさない。

最初の比較版では、移せる情報を一度すべて新図へ載せて欠落を可視化する。その後の簡略化は、重複・混雑・本文や caption への移管を一項目ずつ判断して行う。この「一旦 hoist」は最終図を情報過多にする指示ではなく、暗黙の削除を防ぐ review 順序である。採否の判断は project の DESIGN、現行 generator と出力は project の図 source、比較表は project の review note が所有する。

広い変更の直前には、generator、PDF/PNG、caption を日付と入力状態 ID を持つ snapshot に保存する。snapshot は復元用で、現行の表記・綴り・後続修正の正本にしない。どの file と figure environment だけを戻すかを書き、原稿全体を古い snapshot で上書きしない。一般の snapshot 命名は [`expensive-intermediate-artifacts.md#snapshot-artifact-naming`](expensive-intermediate-artifacts.md#snapshot-artifact-naming) に従う。

artist の source と z-order が正しく見えても、最終 render では線・塗り・arrowhead・label が同色や近い色で重なって消える。変更ごとに実際の PDF または原寸 PNG を確認し、次を別々に見る。

- arrow の shaft と head が背景・曲線・塗りの上で両方読めるか
- 軸線と通常の axis arrow、tick、平均や閾値の guide が同じ役割に見えるか
- label が指す対象と同色・同 z-order に埋もれていないか
- 片方の panel の意味を変えたとき、panel title、軸、caption の名詞も同時に変わったか
- caption に残した時間窓・正規化・parameter が、図で実際に計算したものと一致するか

自動 bbox gate は文字の枠外だけを検出し、同色重なりや semantic な欠落を検出しない。情報 inventory と actual-render review は `assert_texts_inside` の代替でなく補完である。

関連: スライド文脈の図生成 (日本語フォント・CJK PDF 罠・オリジナル模式図) は
[`beamer-slides.md#generate-figures-not-scavenge`](beamer-slides.md#generate-figures-not-scavenge)。

## <a id="read-back-published-figure"></a>図を pixel から数値に読み戻して本文と突き合わせる (2026-09-12)

図と本文の整合は目視では判定できない。**完成した図 (PDF / PNG) を数値に読み戻す**と、
「図の境界線が本文の式と同じ関係か」「図の点が本文の桁と合うか」が数値で言える。
道具 = [`scripts/read-plot-axes.py`](../scripts/read-plot-axes.py) (枠と目盛りを自動検出 → 軸較正 →
塗り潰し marker の重心 `--dots` / 網掛け帯の上下端 `--bands` / 境界線の傾き `--line` を data 座標で返す、
`--selftest` は foil つき)。vector 経路の姉妹 = `ai-collaboration/scripts/svg-contour-extract.py`
(published figure の path から輪郭を復元。元が SVG で輪郭そのものが要るならこちら)。

使いどころは 3 つとも「自分では気付けない」類:

1. **自分の図 vs 自分の本文** — 図の境界線が本文の定義式から導けるか。実測 (2026-09): 対数平面の
   境界線を読み戻すと `log x + log y = const` で、本文の閾値条件そのものだと確認できた。逆に
   ずれていれば、図の生成時の parameter が本文と違う (= 最も発見しにくい種類の不整合)。
2. **図の点 vs 本文の桁** — 図に打った代表点の座標を読み、本文が書いた桁と比べる。実測では
   本文の値と図の点が 10³ ずれていた (本文が上限を「≲」 で書いていたので誤りではないが、検算する
   読み手には矛盾に見える = [`kakenhi-proposal.md#mock-review-and-claims`](kakenhi-proposal.md#mock-review-and-claims)
   の「同一量の別表式は定義点で恒等式に繋ぐ」の検出器)。
3. **他人の図** — referee・審査委員として、本文の主張が図から読めるかを検算する。

⚠️ **読み取り精度の下限は 1 pixel 相当**。script は `1px=` として dex (log 軸) を印字するので、
**それより細かい桁を主張しない**。300 dpi で 3 桁分の対数軸なら 1 px ≈ 0.01 dex 程度、
図を小さく crop すると簡単に 0.1 dex まで粗くなる。

⚠️ **枠の内側に文字がある図では、文字が marker や帯と誤検出される**。対策は 2 つとも実測で決めた:
marker は**円形度** (面積 ÷ bbox の内接円の面積) と縦横比で落とす、帯は「枠高の 1% 未満の run を
捨てる」(固定 3 行では文字の行が偽の帯 2 本になった)。⚠️ 円形度を**素の充填率** (面積 ÷ bbox) で
測ってはいけない — 離散化のため**どんな円盤でも 0.66〜0.75 にしかならず** (πr²/(2r+1)² が π/4 に
下から漸近する)、0.75 を閾値にすると本物の marker が境界に乗る。π/4 で割って正規化すると
大きさに依らない量になり、円盤 0.84〜0.95 / 文字 0.76 以下と分離する。

⚠️ **検出数は下限として読む**。円形度で選ぶので、**矢印や線に接した marker は円形でなくなり落ちる** —
同じ図で 2 点取れた実装と 1 点落ちた実装があった。返ってきた数が図の見た目と合うかを必ず目で確認する。

⚠️ 境界線 fit は残差が大きいとき `trustworthy: false` を返す (判定 = 最大残差が軸幅の 5% 未満
**かつ** rms < 0.1 dex)。**この警告が出た fit の傾きは使わない** — 数値が返ってくること自体は
正しさの証拠ではない。実測 2 例: 凡例の箱を追った fit が slope −0.96 / rms 2.06 dex を返した
(真値 −1。上 30% を捨てると −1.0015 / rms 0.022)、別の図では文字と網掛けを拾って −0.83 を返した。

独立実装との突合が効く: 同じ図の網掛け帯の上下端を、独立に書いた 2 実装と手計算の 3 者で読み、
log₁₀ で小数 2 桁まで一致した (= 読み取り自体の検証になる)。図を読み戻す作業は**他の誰かが同じ図を
読んだ値と突き合わせられる**ので、重要な図では独立に 2 回読む。

## <a id="model-based-illustration-check"></a>図解を物理モデルから描くときは、 模型の性質を数値で確かめてから出す

バナー・表紙・スライドの飾りのように「見た目のための図」 でも、 物理の模型から描くなら中身は正しくする (見る人は物理の人)。 見た目が良いまま模型が壊れている、 は普通に起きる:

- **何を模型にしたかを script の docstring に書く** (式・定数・出典の種類・合成であること)。 実データでないなら「合成」 と明記する
- **その模型が満たすはずの量を 1 つ以上、 数値で確かめて print する**: 厳密解との一致 (例: 2 次元イジング模型の自発磁化と Onsager の式)、 包絡線を越えないこと、 同じ時刻の点が乗るはずの曲線からのずれ、 既知の飛程・閾値との一致
- **よくある壊れ方 (実測)**:
  - 「等時間隔」 のつもりで各軌道を同じ個数に等分していた (軌道ごとに Δt が違う = ストロボ写真にならない)
  - 物質中の粒子のエネルギー損失を 1 桁取り違え、 飛跡の長さが非物理的になっていた (公式から長さを出す形に直した)
  - 対称性で等価な 2 状態のどちらに落ちるかが乱数で決まり、 意図した配色 (低温 = 寒色) と逆になった (対称操作で揃える)
- 描いた画像は必ず目で見る (配置・切れ・潰れ)。 数値の検査と目視は別の失敗を捕まえる

## <a id="multi-panel-correspondence"></a>多パネル図は色・題・線でパネルどうしの対応を見せる

同じ量を別の見せ方 (3D・上から見た図・断面) で並べる図では、 読者は「どのパネルとどのパネルが同じ条件か」「どの線がどの断面か」 を色と形で拾う。 対応が説明なしで読めないと、 caption を読んでも図が意味不明になる (実測: 1 枚の図を著者の指摘で下の順に直した)。

1. **同じ条件には図の全部の要素で同じ色を使う** — 3D の面、 上から見た図の colormap、 断面の曲線、 colorbar まで 1 色の系統で揃える。 主役の条件 (本文の主な regime) を落ち着いた基調色、 もう一方の条件を強調色にする。 colormap を条件ごとに分けたら colorbar を並べて目盛を 1 組にし、 caption に「色は条件、 濃さは値」 を 1 文で書く。 明るさの段階を揃えた colormap にすると、 同じ濃さが同じ値を表す。
2. **並ぶパネルの題は同じ型の句にする** — 片方が名詞句で片方が別の構文、 にしない。 条件の値は題の 2 行目に同じ形で書く。
3. **派生パネル (上から見た図・断面) の題に自分のパネル記号を入れない** — 「(c) top view of (a)」 でなく「top view of (a)」。 記号は派生元を指すときだけ使う。 記号は飛ばさず振り直す (a, b, e と飛ばさない)。
4. **引いた線は、 何の線かが caption か凡例で分かるものだけ残す** — 説明の無い補助線は消す。 範囲内でほぼ平らになって情報が見えない線を残すなら、 なぜそう見えるかを caption に言葉で書く。 主役の線 (光円錐のような基準) を実線、 従の線を破線にする。
5. **断面のパネルは、 上段の断面線と同じ色を断面の軸線に付ける** — どこを切ったかが説明なしで読める。
6. **比較のパネルは他のパネルと同じ尺度にする** — 他が linear なら linear。 尺度を変えて見えなくなった主張 (裾の値など) は caption から落とすか、 別の図で見せる。
7. **図の軸のためだけに補助記号を定義しない** — 軸は元の量の比で書く (定義した記号は読者の記憶を占める)。
8. **模式図の parameter は、 物理的な意味が無ければ切りの良い値にする** (√2 から来た 0.707 より 0.7)。

## <a id="curve-end-marks-and-band-ends"></a>曲線の端の印と、 2 本の曲線に挟まれた帯の端 (実測)

parameter を走査して描いた曲線と、 2 本の曲線に挟まれた帯 (上限と下限の間) で、 読者が「折れ線」「はみ出し」 と言った形。 どれも data でなく描き方の問題だった。

1. **斜めに来る曲線の端に向きのある印 (`"|"` や `"_"`) を打たない** — 線の端に縦の棒が付くと、 線がそこで折れたように見える。 端を示すなら文字 (値や名前) を脇に置くか、 向きの無い印 (小さい点) にする。 印を消す前に、 端の数点の data が単調かを数値で見て、 折れが data でないことを確かめる。
2. **帯の上限と下限は同じ parameter 範囲で走査する** — 片方だけ範囲を広く取ると、 帯の端から線がはみ出し、 読者は「帯はどう決めたのか」 と問う。 片方が端で発散して描けないなら、 両方をその手前で切り、 切った理由と値を caption に書く。
3. **帯の端は直線で結ばない** — 端の点どうしを直線で結ぶと、 塗りの端が斜めの折れ線になる。 端は「parameter を端の値に固定して、 上限から下限へ動かした軌跡」 で閉じる (= その帯の定義どおりの境界)。
4. **境界が parameter の対数で動くなら、 その側は log 等間隔で走査する** — 線形の刻みでは端の近くに点が足りず、 端が折れて見える。
5. **読者が「ここが折れて見える」 と言ったら、 直す前にその場所の pixel を切り出して拡大し、 どの描画要素がそう見せているかを見る** — 描き方の候補 (帯の端・印・刻み) は複数あり、 推測で 1 つ直すと別の要素が残る (実測: 帯の端を直して、 原因だった端の印を残した)。 `PIL` で `crop` → `resize` → 見る、 と、 端の数点の data を print する、 の 2 つで切り分けが済む。

## <a id="annotation-colors-and-arrows"></a>注記の色と矢印 — どの注記がどの点を指し、 どの矢印がどこから出るかを見せる

曲線の上の点 (端点・極大・観測の基準点) に注記を付け、 水平の基準線と「足りない量」 の矢印を足した 1 枚の図で、 通読で止められた形 (実測)。
図の数値が正しくても、 読者が「どの文字がどの点の話か」「この矢印はどこから出ているか」 を追えないと読めない。

1. **注記ごとに色を 1 つ割り当て、 点の印・文字・引き出し線を同じ色にする**。 別の注記は別の色にする。
   灰色と黒だけで済ませない: 注記を灰色で揃えると、 同じ灰色の基準線 (水平線とその label) と区別がつかない。
   色覚に配慮した Okabe–Ito の色 (`#0072B2` `#D55E00` `#009E73` `#CC79A7` など) から選び、 主役の曲線は黒のままにする。
2. **矢印は、 何を表すかに合わせて出どころを決める**。 曲線に沿った動き (時間発展・転がり) は、 曲線の上に矢尻を置く。
   曲線から離れた弦の矢印は、 どの点から出てどこへ向かうのかが読めない。 向きを示す矢尻は 1 つにする (並べても情報は増えない)。
3. **「足りない量」 は、 それが要る場所に縦の矢印で置き、 値を label に書く** (例: 基準線から極大までの差)。 2 点を斜めに結ぶ矢印にしない。
4. **同じ時点を指す 2 つの量の高さが違うなら、 違いを図と label の両方で見せる** — 曲線上の点 (その位置での量) と水平線 (全体の量) がずれていると、
   読者は「合っていない」 と止まる。 2 つを短い縦線で結び、 label に関係式 (どの寄与の分だけ違うか) を書く。
5. **読者が最初に聞く基準点を印す** (例: 観測が参照する点・規格化の点)。 図にその点が無いと、 本文の数値と図を結べない。
6. **色・矢印を変えたら原寸の PNG で見直す** ([#figure-replacement-information-audit](#figure-replacement-information-audit) の actual-render review)。
   文字が線に重なっていないか、 引き出し線が別の点を指して見えないかを見る。

## <a id="mathtext-unsupported-commands"></a>mathtext に無い LaTeX の命令

matplotlib の mathtext は LaTeX の部分集合で、 `\tfrac` のような命令を知らない。
図の文字列に書くと、 描画の時点 (`tight_layout()` / `savefig()`) で `ValueError` (`ParseFatalException: Unknown symbol: \tfrac`) で落ちる (実測)。
`\frac{3}{2}` か `3/2` に書き換える。 本文の TeX と同じ macro で図の文字を書きたいなら `rcParams["text.usetex"] = True` で TeX に描かせる (TeX の install が要る)。
