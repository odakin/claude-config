<!-- doc-meta
when: 押印 (ハンコ) のスマホ写真から書類合成用の透過 PNG (シャープな輪郭 + 自然なかすれ + 写真由来の色 + 複数バリアント) を作るとき + 印影・ロゴ等の小さいラスタ素材を高解像度化したいのに補間拡大がボケるとき
category: office
summary: 実写 1 枚 (印影 ~300px 径) から 3000×3000 透過 PNG 30 変奏を量産した実 session の確定パラメータ付きフル pipeline。核心 = 補間拡大では元画像の情報量を超えられないので potrace でベクトル化してから任意解像度でラスタライズ (エッジ鮮鋭度 実測 13 倍)。2 値化しきい値は redness = R − min(G,B) > 110 を比較シートで user に選ばせる (甘いと文字の窓が潰れる)。かすれは均一に濃い実物からは取れないので合成 — ランダム散布でなく「縁 + 押し圧ムラ + 実写の局所薄部」に寄せ、抜け率 4% が本物のシャチハタに最も近い (9% でデザイン品に見え始める)。色はベタ単色でなく実写インク色を最近傍補完で転写。variant は seed × 抜け率 × 回転のみ変え、色マップ等は cache。検証は目視でなく数値 5 項目 (bbox 内収まり / 隣接ペア差分 >2% / α0 率 / 薄色画素 0 / 文字の穴保存)。下流の派生版正規化 (content fill 一定化) + random picker pattern も併記
-->

# ハンコ写真のデジタル化 pipeline (photo → vector → textured 透過 PNG variants)

スマホ写真に写った押印 (ハンコ) から、書類合成用の透過 PNG を作るフル手順。 実際に 2268×4032 JPEG (印影の実サイズ約 300px 径) から 3000×3000 の透過 PNG 30 枚を量産した session (2026-07) の**確定済みパラメータ付き**。 印影に限らず「小さく写ったベタ塗り図形をシャープに高解像度化したい」 一般 (ロゴ・落款・スタンプ) に使える。

関連 slug: 手書き**署名**の photo → 透過 PNG は [`office-automation.md#signature-photo-to-transparent-png`](office-automation.md#signature-photo-to-transparent-png) (= 輝度しきい値だけの簡易版で足りる系統、 本 doc はそのハンコ版フル pipeline)。 挿入時の濃度調整は [`office-automation.md#signature-image-overlay-density`](office-automation.md#signature-image-overlay-density)。 ⚠️ 運用上の注意 = 電子印影を拒否して実押印を求める事務窓口が存在する ([`office-automation.md#physical-seal-required`](office-automation.md#physical-seal-required))。 どの窓口で画像印影が通るかは組織依存の運用知識なので各自の個人層 (layer 3) に記録する。

## <a id="vectorize-dont-upscale"></a>全体の設計思想 (先に読むこと)

最重要の教訓: **元画像の情報量を超える解像度は、補間拡大では得られない**。 LANCZOS で拡大してから赤色抽出するだけだと「ピンボケみたい」 になる。 解決策は**ベクトル化**: 輪郭をベジェ曲線として抽出すれば任意の解像度でシャープにラスタライズできる (実測でエッジ鮮鋭度 13 倍改善: 勾配平均 7.5 → 97.1)。

ただしベクトル化には副作用が 2 つある:

1. **2 値化しきい値が甘いと文字が潰れる**。 エッジの半透明領域まで「線」 に含まれて線が太り、 文字の隙間が埋まる。 しきい値は必ず複数試して比較シートを作り、 user に選ばせること。
2. **紙目・かすれの質感が消える**。 ベタ塗りになるので、 必要なら後工程でかすれを合成する (→ [#kasure-synthesis](#kasure-synthesis))。

## 環境準備

```bash
# macOS
brew install potrace librsvg
# Linux
apt-get install -y potrace librsvg2-bin
pip install pillow numpy scipy
```

potrace はラスタ→ベクトル変換、 rsvg-convert は SVG の高解像度ラスタライズに使う。 この 2 つが品質の要。

## Step 1: 印影の検出とクロップ

「赤らしさ」 = R − min(G, B) で印影を検出する。 単純な R の高さではなく G/B との差を使うのは、 **白い紙も R が高い**から。

```python
from PIL import Image
import numpy as np

img = Image.open('input.jpg')
arr = np.array(img).astype(np.float32)
r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
redness = r - np.minimum(g, b)
mask = redness > 30          # 検出用のゆるい閾値
ys, xs = np.where(mask)
cx, cy = int(xs.mean()), int(ys.mean())          # 重心 = 中心
r_max = max(xs.max()-xs.min(), ys.max()-ys.min()) // 2
half = r_max + 15            # 15px 余白
crop = Image.fromarray(np.array(img)[cy-half:cy+half, cx-half:cx+half])
```

実測例: 中心 (1133, 2012)、 half = 181 → 362×362 のクロップ。 **以降の全工程でこのクロップ座標を使い回すこと** (色マップとシルエットの位置合わせに必須)。

## Step 2: 拡大 → 2 値化 → ベクトル化

**順番が重要**: 先に大きく補間拡大してから 2 値化する。 ネイティブ解像度で 2 値化すると細い線・小さい隙間が量子化で失われる。

```python
scale = 6                    # 362px → 2172px
big = crop.resize((crop.width*scale, crop.height*scale), Image.LANCZOS)
big_arr = np.array(big).astype(np.float32)
redness = big_arr[:,:,0] - np.minimum(big_arr[:,:,1], big_arr[:,:,2])

THRESHOLD = 110              # ← user 確認必須。 50/70/90/110 で比較シートを作れ
binary = (redness > THRESHOLD).astype(np.uint8) * 255
Image.fromarray(255 - binary).save('mask.pbm')   # potrace は黒を追跡する
```

```bash
potrace mask.pbm -b svg -o mask.svg -t 2 -a 1.0 -O 0.2
```

- `-t 2`: 2px 未満の斑点ノイズ除去 (大きくしすぎると細部が消える)
- `-a 1.0`: コーナー最適化のバランス値
- `-O 0.2`: 曲線最適化

しきい値の傾向: 低い (50) と線が太くはっきり、 高い (110) と線が細くシャープ (採用実績 = 110)。 **文字の隙間 (閉じた「窓」 を持つ字) が全しきい値で保存されているか**、 scipy.ndimage で穴の数を数えて検証すると確実:

```python
from scipy import ndimage
holes = ndimage.binary_fill_holes(ink_mask) & ~ink_mask
labeled, n = ndimage.label(holes)
```

## Step 3: 高解像度ラスタライズ

```python
# SVG の色を差し替えてから任意サイズで書き出し
svg = open('mask.svg').read().replace('fill="#000000"', 'fill="#BE3732"')
open('colored.svg', 'w').write(svg)
```

```bash
rsvg-convert -w 3000 -h 3000 -b none colored.svg -o flat_3000.png
```

`-b none` で背景透過。 この時点で「かすれ無しのベタ塗り版 (flat)」 が完成。 **SVG 自体も成果物として残す** (無限解像度・色変更自由)。

## <a id="kasure-synthesis"></a>Step 4: かすれの合成

実物の押印が均一に濃い場合 (実測例: インク内 redness の p5 = 119 で濃淡ほぼ無し)、 実写の濃淡だけではかすれが作れないので合成する。 ランダム散布は嘘っぽくなるため、 **実際に薄くなりやすい場所に寄せる**のが肝:

```python
from scipy import ndimage

SIZE = 3000
# shape: flat 版のアルファ (0..1)。 ink = shape > 0.5

def octave(rng, res):
    """低解像度乱数を BICUBIC 拡大した 1 オクターブ"""
    n = rng.random((res, res)).astype(np.float32)
    im = Image.fromarray((n*255).astype(np.uint8)).resize((SIZE, SIZE), Image.BICUBIC)
    return np.array(im).astype(np.float32) / 255.0

rng = np.random.default_rng(seed)
# 斑点 (紙繊維にインクが乗らない感じ)。 細かすぎると縮小表示で消えるので粗めに
speck = (octave(rng,55) + 0.65*octave(rng,110) + 0.40*octave(rng,220) + 0.22*octave(rng,450)) / 2.27
# 押し圧の大ムラ
patch = (octave(rng,6) + 0.6*octave(rng,12) + 0.3*octave(rng,24)) / 1.9
# それぞれ 0..1 に正規化すること

# 線の縁ほど抜けやすい重み
dist = ndimage.distance_transform_edt(ink)
edge_w = np.clip(1.0 - dist / 55.0, 0, 1)

# 実写の局所的な薄さ (絶対値でなく局所平均との比を使う: 縁が一律に薄判定されるのを防ぐ)
local_mean = ndimage.uniform_filter(redness_3000, size=90)
local_norm = redness_3000 / (local_mean + 8.0)
real_low = np.clip((1.06 - local_norm) / 0.12, 0, 1)

potential = 0.55*speck + 0.45*(0.42*patch + 0.38*edge_w + 0.20*real_low)

# かすれ量 (抜け率) から閾値を分位で一発決定 (二分探索不要)
coverage = 0.04                                   # light = 4% が最も自然と確定
t = np.quantile(potential[ink], 1.0 - coverage)
holes = np.clip((potential - t) * 22.0 + 0.5, 0, 1)   # 急峻に立てて穴の縁もシャープに
alpha = np.clip(shape * (1.0 - 0.92 * holes), 0, 1)
```

かすれ量の目安 (user テスト結果):

| 抜け率 | 印象 |
|---|---|
| 1〜2% | ほぼベタ。 かすれを入れた意味が薄い |
| **4% (light)** | **本物のシャチハタ印影に一番近い。 採用値** |
| 9% (medium) | 「わざとかすれさせたデザイン」 に見え始める |
| 16% (strong) | 落款・和風ロゴ向け |

判断のコツ: 100% 表示ではなく**実寸相当に縮小して見る**と自然さがわかる。

## <a id="photo-color-transfer"></a>Step 5: 写真の色を使う (単色をやめる)

ベタの単色 (#BE3732) ではなく実写のインク色ムラを乗せる。 問題は写真のエッジ部が紙色と混ざって薄いこと。 対策は**濃いインク画素からの最近傍色補完**:

```python
# 元写真をベクトル化と同じクロップ・同じ 3000px グリッドに拡大しておく
strong = redness_3000 > 110         # ベクトル化と同じ基準
ind = ndimage.distance_transform_edt(~strong, return_distances=False, return_indices=True)
R = np.where(strong, r, r[tuple(ind)])   # strong 以外は最近傍 strong の色
G = np.where(strong, g, g[tuple(ind)])
B = np.where(strong, b, b[tuple(ind)])

# 紙のグレー被りを軽く補正
R = np.clip((R - 8) * 1.06, 0, 255)
G = np.clip(G * 0.96, 0, 255)
B = np.clip(B * 0.96, 0, 255)

rgba = np.zeros((SIZE, SIZE, 4), np.uint8)
rgba[:,:,0], rgba[:,:,1], rgba[:,:,2] = R, G, B
rgba[:,:,3] = (alpha * 255).astype(np.uint8)
rgba[rgba[:,:,3] == 0] = 0          # アルファ 0 の画素は RGB も 0 にクリア
```

検証: インク部 (alpha>128) に redness<60 の薄い画素が 0% であること。

## <a id="variant-mass-production"></a>Step 6: バリアント量産

書類ごとに違う印影に見せるため、 乱数シード・かすれ量・回転をばらす:

```python
coverage = rng.uniform(0.025, 0.060)   # light 中心のばらつき
# 回転分布は user 要望で調整。 採用例は反時計回り寄せ:
if rng.random() < 0.7:
    angle = rng.uniform(-9.0, -0.5)    # 7 割をマイナス側
else:
    angle = rng.uniform(-0.5, 5.0)

im = Image.fromarray(rgba, 'RGBA')
im = im.rotate(angle, resample=Image.BICUBIC, expand=False,
               center=(SIZE//2, SIZE//2), fillcolor=(0,0,0,0))
```

色マップと edge_w、 real_low はバリアント間で共通なので**一度だけ計算して cache** する (1 枚あたり約 3 秒に短縮)。 各バリアントで変えるのはノイズ場 (seed)、 coverage、 angle のみ。

必ず付けるもの: 番号つきコンタクトシート (user が選べる)、 specs.txt (番号・かすれ%・回転角の一覧)、 zip。

## <a id="verification-checklist"></a>検証チェックリスト

作った後に必ず**数値で**確認する (目視だけに頼らない):

1. 回転後もコンテンツが完全にキャンバス内か (`np.where(alpha>0)` の bbox)
2. バリアント同士が実際に違うか (隣接ペアのアルファ差分率 > 2%)
3. アルファ 0 率が期待通りか (実測例 約 80%)、 中間アルファは輪郭部の少量のみか
4. インク部に薄い色 (redness<60) が混ざっていないか
5. 文字の隙間 (穴) が全て保存されているか

## <a id="downstream-derivative-pattern"></a>下流運用の一般 pattern (= 量産後にどう使うか)

原盤 (最大解像度) と書類挿入用の派生版を分ける:

- **原盤は最大解像度 1 系列だけ durable な場所に残す** (縮小はいつでもできる、 逆は不可)。 git repo には縮小派生版のみ commit し、 原盤は cloud storage 等の git 外 archive + README back-pointer (= ルールは書かず個人層の SoT を指す)。
- **派生版は content fill を一定に正規化する** (bbox trim → 一定余白 pad → 固定 px、 例 fill 0.89 / 600×600): variant ごとの余白差を消し、 挿入 driver の px 指定と独立にどの variant でも同じ見た目サイズになる。
- **挿入のたびに variant を random に選ぶ** (pool = canonical + variants の一様 sample): 実物の押印は毎回微妙に違うので、 byte 一致の同一印影を全書類に使い回さない。 同一書類内の複数押印欄は相異なる variant を引く。
- canonical path・picker script・どの窓口で画像印影が通るか等の個別運用は各自の layer 3 に置き、 本 doc は手順の SoT に留める。

## user とのやり取りで学んだこと

- 途中判断 (しきい値、 かすれ量、 回転分布) は**必ず比較シートを作って選ばせる**。 4 分割グリッド + ラベルが有効。
- 「かすれをもう少し」 のような曖昧な指示は、 数値化して段階提示する (1.0% / 1.5% / 2.0% など)。
- 選択肢を出しすぎて「味がわからなくなった」 と言われたら、 根拠つきで 1 つ推薦する (本物の印影の特徴と比較して)。
- マスターは最大解像度 1 枚だけ残せばいい (縮小はいつでもできる、 逆は不可) と user に伝える。
- 過去に単色で作ったものを「写真の色を使ってるんだよね?」 と聞かれたら、 **正直に「単色だった」 と認めて作り直す**こと。

## 最終成果物の構成 (実例)

```
hanko_thr110_flat.svg              # ベクター原本 (無限解像度)
hanko_thr110_flat_3000.png         # ベタ版
hanko_photocolor_light_3000.png    # 写真色 + light かすれ (マスター)
hanko_variants_30.zip              # バリアント 30 枚 + specs.txt
variants_sheet.png                 # 一覧シート
```

origin: 2026-07-25、 実物押印のスマホ写真 1 枚から 30 variant を量産した実 session のガイド (作成した Claude 自身の手順書) を層 1 へ編集 landing。 パラメータは全て当該 session の user テストで確定した採用値。
