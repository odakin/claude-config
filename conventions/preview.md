<!-- doc-meta
when: preview / dev server 稼働中に user へ動作確認を依頼するとき
category: harness-core
summary: preview / dev server 動作中はユーザー確認依頼ターンに URL を毎回明示する出力ルール
-->
# プレビュー・テスト URL の出力ルール

ユーザーに動作確認・プレビューを依頼するときは、**毎回 URL を併記**すること。

## 対象

- `preview_start` (Claude Preview MCP) で起動したサーバー
- `python3 -m http.server` / `npm run dev` / `vite` / `next dev` 等、あらゆる方法で起動したローカルサーバー
- staging / production / preview deployment へのリンク (Vercel, Netlify, GitHub Pages 等)
- ローカルファイル直接 (`file:///path/to/index.html`) を開かせる場合もパスを書く

> ⚠️ **tool 名は時点依存** (2026-09-02 更新): 現行の内蔵 Browser pane は `preview_start` / `computer` / `read_page` / `get_page_text` / `javascript_tool` (= `preview_screenshot` / `preview_eval` / `preview_inspect` は現行 harness に存在しない)。 実際に呼べる名前が 最終 ground truth なので、 本 doc の tool 名が通らなければ session の tool list を見る。

## ルール

- 「テストしてください」「ハードリロードしてください」「動作確認お願いします」「見え方どうですか?」など、ユーザーが評価アクションを取る依頼を含む応答では、**そのターン内で URL を毎回明示**する
- preview が動いている間は、関連する応答ごとに URL を再掲する。コード変更・HMR 反映報告・パラメータ調整の確認など、preview を触りうる全ターンが対象
- 「さっきの URL で…」「先程のページを…」のような遡及参照を強要しない

## Why

ユーザーは複数ターンの応答をスクロールで追わずに、その場でリンクを踏みたい。URL を毎回書く負担より、ユーザーがスクロールバックする摩擦のほうが大きい。

## How to apply

評価依頼を含むあらゆる応答で URL をその応答内に書く。「動作確認お願いします」「リロードしてください」だけ書いて URL を出さないのは NG。

## 例

✗ NG: 「修正しました。ブラウザでハードリロードしてください」
✗ NG: 「修正しました。`**http://localhost:8742/index.html**` をハードリロード」 (= bare URL を `**…**` で囲むと GFM autolinker が末尾の `**` を URL に飲み込み、 全体が 1 個の壊れたリンクになる。 詳細: `~/Claude/claude-config/gfm-rules.md` §「Don't wrap a bare URL」)
✓ OK: 「修正しました。 [http://localhost:8742/index.html](http://localhost:8742/index.html) をハードリロード (Cmd+Shift+R) してください」 (= markdown link 形式、 最も安全)
✓ OK: 「修正しました。 http://localhost:8742/index.html をハードリロード (Cmd+Shift+R) してください」 (= bare URL は前後に必ず空白)

✗ NG: 「デプロイ完了。ステージングで確認お願いします」
✓ OK: 「デプロイ完了。 https://app-staging.example.com/foo で確認お願いします」

## Deploy 前のユーザー確認を省かない

視覚的・動作的に観察可能な変更 (UI, レンダリング, ゲーム挙動, 画面遷移等) は、Claude が screenshot (= `computer {action:"screenshot"}`) や `read_page` で自己確認しただけで **そのまま push・deploy に進まない**。**ユーザーにローカル URL を提示して OK を得てから deploy すること**。

**Why:** Claude が見た screenshot (headless browser の 1 枚) とユーザーが自分のブラウザで見た実際の表示は別物。ジグザグ・色調・動きの違和感は screenshot では拾えず、ユーザーが実機で見て初めて分かる。deploy まで行ってしまうと public キャッシュ反映待ちが挟まり、修正サイクルが大幅に遅くなる (GitHub Pages・Cloudflare Pages 等)。

**How to apply:**

1. ローカル dev server を Bash バックグラウンドで起動 (`run_in_background: true`)
2. URL をリンクでユーザーに提示 (本ファイル上部「ルール」節のとおり毎回明示)
3. ユーザーが自分のブラウザで確認して OK/NG を返すまで待つ
4. OK → commit + push + deploy、NG → 修正して同じループ (HMR で dev server は継続、commit なしで反復可能)

**preview_start vs `pnpm dev` バックグラウンド**: preview_start は Claude の確認用 (preview_* ツールが使える)、`pnpm dev` の Bash バックグラウンドはユーザー共有用 (Claude の preview ブラウザが PeerJS ID 等を奪わない)。プロジェクトによっては同時に両方立てる (別ポート)、または preview_start を使わず `pnpm dev` だけで済ませる運用もあり。

**例外**: build / lint / typecheck だけで完結する変更 (観察不能なリファクタ・ドキュメント修正等) はこの手順不要。

**例外の例外 — build config 変更は例外に含まれない**: `vite.config.ts` / `webpack.config.js` / `rollup.config.js` / `package.json` の bundler 設定・scripts / `tsconfig.json` の `paths` / `module` 等の変更は「観察不能」に見えるが、**bundle 構造が変わった結果として本番だけで顕在化する runtime error** を生むことがある。代表例:

- **chunk 間循環 import**: vendor を細分割した結果、chunk 境界で ESM 循環 → ブラウザの module loader が TDZ (Temporal Dead Zone) error を throw → 真っ白。`pnpm run build` / `pnpm preview` ではエラーなしで通過することがある (2026-04-22 LorentzArena 事故)
- **base path / asset URL 解決の差**: 本番 CDN (GitHub Pages / Cloudflare Pages 等) では dev/preview と異なる URL resolution が働き、特定 chunk が 404 になる
- **module preload タイミング**: 本番 HTTP/2 + CDN の multiplexing 順序が local preview と異なり、初期化順序依存の error が本番だけ再現する

したがって **build config 変更後の deploy は、視覚変化がなくても本番 URL を実ブラウザで踏んで console 0 error を確認するまで 'deployed' と呼ばない**。`pnpm preview` や chunk HTTP status 200 は必要条件で十分条件ではない。確認できるまで odakin に依頼する。

## Claude Preview の headless throttling 制約

Claude Preview (MCP `preview_*` ツール) の headless Chrome には、アニメーション駆動アプリを事実上動かなくする **二重制約** がある。React Three Fiber / Three.js / Canvas 2D animation / WebGL ゲーム / `requestAnimationFrame` ベースのどの app でも発火する。

### 症状

- (a) `document.hidden === true` 常時 (`visibilityState === 'hidden'`)。`visibilitychange` ガードを持つコードは毎 tick 早期 return
- (b) 仮に (a) を `Object.defineProperty` で override しても効かない。Chrome が **occluded/headless context として rAF と timer を強制 throttle** する。実測 (2026-04-22 LorentzArena):
  - `requestAnimationFrame` → 2 秒で **0 fire** (実質停止)
  - `setInterval(16ms)` → 2.2 秒で **4 fire** (≈ 500 ms/fire。普通なら ~140 fire のはずが ~2% 以下)
- 原因は Page Visibility API 判定ではなく、Chrome が headless の occluded window を背景 tab 扱いで throttle する内部機構。Page Visibility 経由で fix できない。

### 帰結

以下の類型の検証が **Claude Preview では不可能**:

- ゲーム物理ループ (FPS / player 動作 / projectile / hit / damage / respawn)
- アニメーション遷移 / transition timing
- rAF-driven camera / view update
- WebSocket / WebRTC の長時間 keep-alive (timer throttle で ping/pong が遅延)
- `setTimeout(...)` / `setInterval(...)` を使う debounce や timeout の挙動検証

screenshot を撮っても「止まった時空」が映るだけで、FPS 0 / 動的状態の初期値が残った静止画になる。

### 回避策

| 対象 | 手段 |
|---|---|
| Pure 関数 (stateless、決定論的入出力) | `javascript_tool` + `await import('.../pure-module.ts')` で unit-test 相当 |
| Single-tab の静的 UI 確認 (初期レンダのみ) | `computer {action:"screenshot"}` + `read_page` / `get_page_text` で初期状態は撮れる |
| Stateful な動的挙動全般 | **実ブラウザ検証を odakin に依頼** — localhost URL (`pnpm dev` background) か staging/prod URL を毎ターン明示 (本ファイル上部「ルール」節) |
| マルチ client 必須 (peer-to-peer、multi-tab race) | 実ブラウザ 2 tab 以上を odakin に依頼。Claude 側の 1 tab を Claude Preview で補完する手も throttle で動かないので不可 |

### 誤誘導を避けるための書き方

過去 CLAUDE.md 等で「`document.hidden=true` が原因」と書いていた箇所があるが、これは症状の一部であり **原因は Chrome の headless throttle 機構**。document.hidden override で解決するかもしれない、という誤った workaround 期待を招かないよう、「override しても効かない」まで書く。

## Vite dev server の sleep-wake full page reload

`vite` / `next dev` 等の dev server は HMR (Hot Module Replacement) 用 WebSocket を持つ。 PC sleep / OS suspend で WebSocket が切断され、 wake で再接続を試行する際に **Vite が browser に full page reload を指示する**。 これは Vite の deliberate な dev mode 挙動 (= source change を見逃さない dev experience 優先)、 production build には Vite dev server が無いので影響なし。

### 症状

localhost dev server (`http://localhost:5174/...`) で:

- ゲーム / SPA を起動 → play / interaction
- PC sleep → wake (= OS suspend / display sleep / lid close 等)
- **page が full reload される** (= ゲーム state ロスト / Lobby に戻る / form 入力消失 / SPA ルート初期化)
- URL hash / query は維持される (= browser reload の通常挙動)
- console は flush される (= reload の signature)
- console に **`[vite] connecting...` → `[vite] connected.`** log が出る (= 上記の signature)

実測 (2026-05-05 LorentzArena): localhost で 2 tab play 中に PC sleep → wake → 両 tab とも Lobby 画面に戻り、 console には Vite HMR reconnect log のみ残る (= 過去の game console log は flush 済)。

### 原因

Vite v5+ は HMR WebSocket 切断後の reconnect path で、 サーバー側 module graph と client 側 state の整合性が保証できないと判断した場合に **`location.reload()` を browser に指示**する。 sleep-wake は WebSocket idle timeout / TCP keep-alive 失敗で切断トリガーになる典型ケース。

参考 signature (= localhost console):

```
[vite] connecting...
[vite] connected.
```

このペアが出ていて他の log が消えていれば full reload。

### 帰結

- **dev mode 限定挙動**: production build (= `vite build` 出力 / GitHub Pages / Vercel deploy / Netlify 等) には Vite dev server 無し、 同じ sleep-wake で reload は起きない
- **アプリ側の bug ではない**: WebSocket / WebRTC reconnect logic / state recovery 等の app 層 fix では解消できない
- **dev experience の問題のみ**: localhost で sleep-wake を伴う long test (= 数十分プレイ + sleep) を試すと state ロストする、 但し production verify は別途 staging/production URL で行う運用で実害なし

### 対処方針

**修正 不要**。 以下の運用で吸収する:

- localhost で sleep-wake を伴う test を行わない (= dev では短時間 test で済ませる、 sleep-wake シナリオは production verify で行う)
- production deploy URL を staging として用意 (= GitHub Pages 等)、 sleep-wake test はそちらで行う
- アプリ側で sleep-wake recovery logic を実装する場合 (例: WebSocket 自動再接続) は必ず **production URL で検証する**、 localhost で「reload してしまうから fix が動いてない」 と誤判定しない

### 確認方法 (= dev/prod の症状切り分け)

「sleep-wake で page reload が起きる」 報告を受けたとき:

1. URL が `localhost:*` か `127.0.0.1:*` (= dev server) なら **Vite HMR full reload の可能性大**
2. console を見て `[vite] connecting...` / `[vite] connected.` の signature を確認
3. 同症状を production URL で再現するか試す → **再現しなければ Vite HMR 限定**、 アプリ修正不要
4. production でも再現するなら別 root cause (= app 層 / WebSocket / WebRTC reconnect 等) を調査

### 誤判定を避ける

「localhost で sleep-wake すると Lobby に戻るから signaling reconnect が壊れている」 のような誤判定を避ける。 Vite HMR full reload は **アプリの全 state を捨てる**ため、 アプリの reconnect logic が動く余地すら無い (= 復活先の component が新規 mount で initial state)。 production で再現するか先に確認する。
