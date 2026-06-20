# Chalkboard close-up merge — 板書写真の close-up annotation を広域写真に統合

## 場面

板書写真 PDF を組み立てるとき、 同じ板書を「広域 (wide)」 + 「拡大 (close-up)」 で 2 枚撮ることがある (= 拡大側は注釈の追記後に撮るパターン)。 PDF を時系列 page で並べるとくり返しになる + close-up の annotation が拡大側にしかない、 という構造的読みづらさが出る。

これを「広域 1 枚に close-up 注を merge した 1 page」 に統合し、 close-up page を落として PDF を圧縮するための **decision flow + 実装 recipe** を以下に置く。

初出: 2026-06-19 量子力学 (発展) 第10回、 ∫ℏ dk の ℏ が dk の Jacobian であることを示す「係数」 注を p4 close-up から p3 広域に merge ([lectures @ f9d27fe](https://github.com/odakin/lectures/commit/f9d27fe))。

---

## 意思決定 — PIL inline composite か Keynote 手作業か

| 観点 | PIL inline (= automated) | Keynote 手作業 (= recommended for free-form) |
|---|---|---|
| 注の位置が「明確 anchor (= 数式や図のすぐ脇)」 | 〇 anchor pixel 検出すれば成立 | 〇 |
| 注の位置が free-form (= 板書の空きスペースに矢印で誘導) | △ paste 位置 + 矢印向きを自動推定するとほぼ間違える | ◎ 視覚で 1-2 操作 |
| 矢印・引出線が必要 | △ 向き反転事故が起きる (= 注 → 元 か 元 → 注 か、 意味論で決まる) | ◎ Keynote の線ツールで自然 |
| Iteration コスト | × user に毎回 preview を見せて位置 fine-tune | ◎ user が掴んで動かす |
| 完全自動化 | 〇 (anchor 確実な時のみ) | × user 1 step 介在 |

**reflex**: free-form な配置 (= 注の置き場が文脈依存) なら **最初から Keynote 経路** に行く。 PIL inline の 2-3 試行で時間を溶かさない。 2026-06-19 で v1 (= 自動 anchor) → v2 (= 壁エリア + 矢印追加) → v3 (= 矢印逆) と 3 iteration 溶かして user 「画像は私が手でやったほうが早いな」 で Keynote 切替 → 1 ターンで決着、 という RCA。

---

## Workflow B (Keynote 手作業、 推奨)

### Step 1 — 透過 chalk PNG を作る (= chalk pixel のみ opaque、 黒板背景 transparent)

```python
from PIL import Image, ImageFilter
import numpy as np

p_closeup = Image.open('close_up_photo.jpg').convert('RGB')
# 注の bounding box (close-up 内の crop 範囲) を視覚で当てる
chunk = p_closeup.crop((x0, y0, x1, y1))

gray = np.array(chunk.convert('L'))
# threshold gradient: chalk ↔ 黒板 の境界
# - blackboard noise: gray 60-100 → alpha = 0
# - faint chalk: gray 100-140 → gradient alpha
# - solid chalk: gray > 140 → alpha = 255
alpha = np.clip((gray.astype(np.int16) - 100) * 6, 0, 255).astype(np.uint8)
alpha_img = Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(radius=1.5))
# 端 jagged 防止に Gaussian blur 1.5 px

rgba = np.dstack([np.array(chunk), np.array(alpha_img)])
Image.fromarray(rgba).save('chalk_chunk.png')
```

**threshold 数値の根拠 + 当たりのつけ方**:
- 黒板は純黒でなく、 dust / smudge / lighting で local mean が gray 60-100。 threshold が低すぎる (~80) と背景全部 opaque で「黒い patch」 として浮く。
- chalk のはっきり書かれた線は gray > 140。 ぼやけた chalk 痕跡が 100-140 で、 gradient transparency で連続化させると自然。
- threshold は写真の明るさ / 黒板の色で動く (= 写真ごとに 100-140 と 80-120 の範囲で適応的に決める)。 ヒストグラムで `np.mean(gray > thr)` を 60/80/100/120/140 で表示して「chalk のみの割合 ~ 5%」 になる threshold を選ぶ:
  ```python
  for thr in [60, 80, 100, 120, 140]:
      print(f'thr={thr}: frac above = {np.mean(gray>thr):.3f}')
  ```

### Step 2 — Keynote .key を AppleScript で auto 生成

theme 名は **日本語ローカライズ** (= macOS の言語設定依存)。 odakin 環境では `"黒板"` (chalkboard theme = 黒地に白文字、 板書写真と統合相性 ◎)。 theme 一覧確認:

```bash
osascript -e 'tell application "Keynote" to return name of every theme'
# 例: ベーシックホワイト, …, 黒板, …
```

AppleScript snippet (= `make_keynote.applescript`):

```applescript
tell application "Keynote"
    activate
    set newDoc to make new document with properties {document theme:theme "黒板"}
    tell newDoc
        try
            set width to 4032
            set height to 2268
        end try
        tell first slide
            -- 背景 (= 広域写真): full-bleed 配置
            set bgImg to make new image with properties {file:POSIX file "/path/to/wide_photo.png"}
            tell bgImg
                set position to {0, 0}
            end tell
            -- 注 (= 透過 chalk chunk): 初期位置は anchor 近くに
            set ovImg to make new image with properties {file:POSIX file "/path/to/chalk_chunk.png"}
            tell ovImg
                set position to {2300, 950}
            end tell
        end tell
    end tell
    save newDoc in POSIX file "/path/to/output.key"
end tell
```

実行:
```bash
osascript make_keynote.applescript
open /path/to/output.key   # Keynote.app で開く
```

**注意点**:
- `theme "Black"` (英語名) で `-1728` エラー = ローカライズされた theme 名でないと取れない
- `width` / `height` で 4032x2268 等の native 解像度を渡すと Keynote が受け入れる (= 標準 1920x1080 への scale-down を防げる)
- floating image は `set position to {x, y}` で左上 anchor 配置

### Step 3 — user が Keynote で chunk を掴んで位置調整

odakin が opaque chalk chunk を掴んでドラッグ → 数式の真下や指したい場所へ。 必要なら shift+drag で aspect 保持リサイズ。 矢印が要れば Keynote の図形ツールで線を引く (= chalk 色 e.g. `(235, 235, 220)` 風)。

完了したら Cmd+S で save (= .key を上書き)。

### Step 4 — slide PNG export を AppleScript で

```applescript
tell application "Keynote"
    activate
    set targetFile to POSIX file "/path/to/output.key"
    try
        open targetFile
    end try
    delay 1
    set exportDir to POSIX file "/path/to/export_dir"
    tell front document
        export to exportDir as slide images with properties {image format:PNG, export style:IndividualSlides}
    end tell
end tell
```

出力 = `export_dir/exported.001.png` (= 4032x2268 RGBA、 native 解像度で書き出し)。 RGB 化は `Image.open(...).convert('RGB')` で。

### Step 5 — PDF に組み直し

```python
from PIL import Image
pages = []
# 旧 page 順を保ちつつ、 close-up page を抜いた sequence で
for n in keep_pages:
    pages.append(Image.open(f'orig_p{n}.png').convert('RGB'))
# merged page を該当位置に挿入
pages.insert(merged_pos, Image.open('exported.001.png').convert('RGB'))

pages[0].save(out_pdf, save_all=True, append_images=pages[1:],
              format='PDF', quality=92, resolution=300)
```

**reflex**: 元の N-page 版は `<orig>.<N>page.bak` でバックアップ (= visual transcript の元証拠を捨てない、 後日 close-up が必要になった時に復元可能)。

---

## Workflow A (PIL inline composite、 anchor 明確時のみ)

### 適用条件

- 注を貼る位置に **明確な anchor (= 識別可能な chalk feature)** が広域写真に既にある
- 矢印不要 (= 注が anchor の直近に貼られる)

### Recipe

```python
from PIL import Image, ImageFilter
import numpy as np

wide = Image.open('wide.png').convert('RGB')
closeup = Image.open('closeup.png').convert('RGB')

# crop chalk annotation from close-up (= STEP 1 と同じ)
chunk_box = (x0, y0, x1, y1)
chunk = closeup.crop(chunk_box)

# scale factor: close-up が wide の何 % をカバーしているか視覚 / pixel 計測で決定
# (= wide で対応する region の width / close-up の crop width)
scale = 0.5  # 典型値: close-up が wide の右半下を 2x zoom した場合 0.5x

new_size = (int(chunk.width * scale), int(chunk.height * scale))
chunk_scaled = chunk.resize(new_size, Image.LANCZOS)

# chalk mask (Step 1 と同じ threshold logic)
gray = np.array(chunk_scaled.convert('L'))
mask = (gray > 110).astype(np.uint8) * 255
mask_img = Image.fromarray(mask).filter(ImageFilter.MaxFilter(3))
mask_arr = np.array(mask_img) > 0

# paste — mask 経由で chalk pixel のみ書き換え (= 背景の rectangle 化を防ぐ)
wide_arr = np.array(wide)
chunk_arr = np.array(chunk_scaled)
h, w = chunk_arr.shape[:2]
roi = wide_arr[paste_y:paste_y+h, paste_x:paste_x+w]
roi[mask_arr] = chunk_arr[mask_arr]
wide_arr[paste_y:paste_y+h, paste_x:paste_x+w] = roi

Image.fromarray(wide_arr).save('merged.png')
```

### 失敗 mode と対処

- **背景全体が長方形に明るくなる** = mask 経由でなく直接 `roi = np.maximum(roi, chunk_arr)` をやった結果。 mask 経由 (上記) で chalk pixel のみ書き換える
- **paste 位置が anchor からずれる** = (a) crop の brace tip の local 座標を `np.where(mask_arr)` で測る、 (b) wide の anchor pixel 位置を別途測る、 (c) 差分で paste 位置を出す。 目視で「だいたい」 では必ずずれる
- **close-up の board divider などの不要 chalk が一緒に paste される** = crop box を狭めて除外する (= 視覚で当ててから crop box を絞る)

---

## 関連

- 板書 PDF の自動取り込み手順 (Picker API → Dropbox 配置) は project 側 doc を参照 (例: `lectures/CLAUDE.md §「Google Photos からの自動取り込み」`)
- AppleScript 全般の制約 (theme ローカライズ等) は OS 言語設定依存。 macOS 日本語環境前提
- 板書写真 PDF → notes.md transcript 時の sympy verify reflex は [`scientific-computing.md §6`](scientific-computing.md)
