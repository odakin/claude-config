<!-- doc-meta
when: matplotlib で図 (論文・研究費調書・発表スライド・様式) を生成する script を書く/直すとき
category: paper
summary: matplotlib 図の「全ラベル枠内」機械 gate (assert_texts_inside = render 済み extent を axes 枠と照合し 1 px 超過で図の生成自体を落とす)・機構 fact・射程の限界
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

関連: スライド文脈の図生成 (日本語フォント・CJK PDF 罠・オリジナル模式図) は
[`beamer-slides.md#generate-figures-not-scavenge`](beamer-slides.md#generate-figures-not-scavenge)。
