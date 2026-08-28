<!-- doc-meta
when: matplotlib の 3D (mplot3d) で半透明の模式イラスト (平面波・波束・濃度場などスライド/論文の概念図) を描くとき
category: paper
summary: 半透明 3D イラストの実測知見 — 周期構造は視線角で消える (projection averaging)・粗密は alpha でなく点密度で・疑似 volume render はスラブ合成・裾の楕円が生む「下から見てる」錯視の解消・スライド素材の透明背景
-->
# matplotlib 3D イラスト — 半透明・粗密・視線角の実測知見

スライドや論文の概念図として mplot3d で半透明のイラスト (平面波、波束、濃度場) を描くときの
非自明な実測知見。2026-08-27〜28 に「3D 平面波の粗密」「2D 面上の Gauss 波束」の反復
(~15 render) で得たもの。以下、変調軸を x、視線と x 軸のなす角を θ とする。

## <a id="projection-averaging"></a>周期構造は視線角で消える (projection averaging)

x 方向に周期 λ の濃淡 (粗密) をもつ半透明の 3D 構造は、**1 本の視線が横切る x の幅
Δx ≈ (奥行き) × cos θ / sin θ が λ/2 を超えると、投影の平均化で縞が消える**。

- 縞をはっきり見せたいなら θ ≈ 80–90° (= 視線が変調軸にほぼ垂直 = 構造を「横から」見る)。
- **正面寄り (θ 小) の視点では縞の消失は原理的で、点数・alpha・真の volume renderer でも救えない**
  (どの視線も全位相を積分するので画面上は一様になる)。正面から見せたい場合は、連続の濃淡は
  捨てて**離散のオブジェクト (波面の板など) に周期を担わせる**のが正解。
- 対角 (θ = 45°) はちょうど縞が死ぬ帯域。中間角は縞がぼやけたまま残り、中途半端に見える。

## <a id="density-not-alpha"></a>粗密は alpha 変調でなく点密度で描く

ランダム点雲で濃度場 ∝ f(x) を見せるとき、**一様ランダム配置 + alpha を f(x) で変調**は
投影の重なりで alpha が平均化されて構造がほぼ消える (実測)。**点の密度そのものを f(x) に
比例させる** (累積分布を数値積分して逆 CDF サンプリング、alpha は一定、seed 固定) と、
投影後も密度差として生き残る。点は小さく (s ≈ 2) 大量に (数万点) が締まる。

```python
xg = np.linspace(0, XMAX, 4000)
F = np.concatenate([[0], np.cumsum(0.5 * (dens[1:] + dens[:-1]) * np.diff(xg))])
X = np.interp(rng.uniform(0, F[-1], N), F, xg)   # 密度 ∝ dens の逆 CDF サンプリング
```

## <a id="slab-volume-render"></a>疑似 volume render = 視線に垂直な薄スラブの合成

mplot3d に真の volume renderer は無いが、**視線にほぼ垂直な薄スラブを N 枚重ねる**古典手法で
「空間そのものが霧のように濁る」見た目が出せる。各スラブを変調軸方向に細片分割し、細片の
alpha を A_slab·f(x) とする。N 枚合成の実効 opacity は 1−(1−A_slab)^N なので、山で目標
opacity PEAK にしたければ **A_slab = 1−(1−PEAK)^(1/N)**。全 quad は 1 つの
`Poly3DCollection(..., zsort="average")` に入れる (= 奥行きソートを一括で効かせる)。
視線角の制約は上の §projection-averaging がそのまま効く。

## <a id="mplot3d-camera-facts"></a>mplot3d カメラの機構 fact

- **azim はカメラ位置の方位角で +x 軸から測る**。法線が x の板を「正面から」見る = azim ≈ 0 側。
  azim = −90 は板の真横 (edge-on)。「正面から見たい」という要望を azim を −90 側へ振って
  応えると逆に横顔になる (実測で 2 往復無駄にした)。
- `ax.set_proj_type("ortho")` (平行投影) にすると奥行き層の位相ズレが消え、周期構造が全域で揃う。
- 立方体を立方体に見せるには **axis limits をデータ範囲ぴったり** + `set_box_aspect` が必要
  (既定の margin が縮尺を歪める)。

## <a id="gaussian-skirt-ambiguity"></a>Gauss 山の裾の楕円は「下から見てる」錯視を生む

低仰角で Gauss 山 (`plot_surface`) を描くと、裾の平坦部が薄い楕円として残り、上下が曖昧な
Necker 反転で「底面が手前に来て下から見ている」ように読める。輪郭の楕円を消すのが根治:

- `facecolors` の per-face alpha を**高さに比例させてフェード** (`shade=False`、
  floor 付き `A·(c₀ + (1−c₀)(Z/H)^p)` でフェードのきつさを独立調整)。
- 裾を広く描く (Gauss らしい流れ) 場合は、**外縁だけ radial の smoothstep 窓で alpha → 0**
  に落とす (= 切り口の楕円エッジを見せない)。
- 底面 = 円にしたいときは極座標グリッド (r, θ) で面を張る (矩形グリッドの角が出ない)。

## <a id="slide-asset-transparency"></a>スライド素材は透明背景で書き出す

Keynote/PowerPoint に貼る PNG は `savefig(..., transparent=True)` で RGBA 化する
(検証 = 角ピクセルの alpha が 0 か)。注意: 半透明の要素は白背景前提で調色していると
濃い背景に載せたとき沈む — deck が白基調かを先に確認する。
