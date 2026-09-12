<!-- doc-meta
when: matplotlib で図 (論文・研究費調書・発表スライド・様式) を生成する script を書く/直すとき
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
2. **図の点 vs 本文の桁** — 図に打った代表点の座標を読み、本文の「10⁻⁵⁹」 等と比べる。実測では
   本文の値と図の点が 10³ ずれていた (どちらも「≲」 の範囲で誤りではないが、検算する読み手には
   矛盾に見える = [`kakenhi-proposal.md#mock-review-and-claims`](kakenhi-proposal.md#mock-review-and-claims)
   の「同一量の別表式は定義点で恒等式に繋ぐ」の検出器)。
3. **他人の図** — referee・審査委員として、本文の主張が図から読めるかを検算する。

⚠️ **読み取り精度の下限は 1 pixel 相当**。script は `1px=` として dex (log 軸) を印字するので、
**それより細かい桁を主張しない**。300 dpi で 3 桁分の対数軸なら 1 px ≈ 0.01 dex 程度、
図を小さく crop すると簡単に 0.1 dex まで粗くなる。

⚠️ **枠の内側に文字がある図では、文字が marker や帯と誤検出される**。対策は 2 つとも実測で決めた:
marker は充填率 (円盤 = π/4 ≈ 0.785) と縦横比で落とす (0.6 では文字が残り 0.75 で消えた)、
帯は「枠高の 1% 未満の run を捨てる」(固定 3 行では文字の行が偽の帯 2 本になった)。

⚠️ **検出数は下限として読む**。円形度で選ぶので、**矢印や線に接した marker は円形でなくなり落ちる** —
同じ図で 2 点取れた実装と 1 点落ちた実装があった。返ってきた数が図の見た目と合うかを必ず目で確認する。

⚠️ 境界線 fit は残差が大きいとき `trustworthy: false` を返す (判定 = 最大残差が軸幅の 5% 未満
**かつ** rms < 0.1 dex)。**この警告が出た fit の傾きは使わない** — 数値が返ってくること自体は
正しさの証拠ではない。実測 2 例: 凡例の箱を追った fit が slope −0.96 / rms 2.06 dex を返した
(真値 −1。上 30% を捨てると −1.0015 / rms 0.022)、別の図では文字と網掛けを拾って −0.83 を返した。

独立実装との突合が効く: 同じ図の帯を 2 つの実装と手計算で読み、3 者が log₁₀ で
−13.52 〜 −0.97 に一致した (= 読み取り自体の検証になる)。図を読み戻す作業は**他の誰かが同じ図を
読んだ値と突き合わせられる**ので、重要な図では独立に 2 回読む。
