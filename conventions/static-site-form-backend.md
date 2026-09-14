<!-- doc-meta
when: 静的サイト (GitHub Pages 等) に投稿フォーム・お便り欄・問い合わせ欄を置くとき + Cloudflare Pages へ引っ越す / Pages Functions・D1・Turnstile を CLI で組むとき + GitHub Pages の旧 URL から新しい URL へ転送するとき
category: web
summary: 静的ホスティングは送られた内容を受け取れない。mailto は宛先を公開し、別ドメインのフォームサービスへの送信は結果をページ側で読めない (受け口がエラーでも「届いた」と表示してしまう実測)。同じサイトに関数を置ける Cloudflare Pages + Functions + D1 なら、成否を正しく表示できる。Pages は Workers と違い URL にアカウント名が入らない。GitHub 連携はリポ所有者のブラウザ許可が要り、Direct Upload で作ると後から Git 連携に変えられない。Turnstile は wrangler で作れ (challenge-widgets.write)、受け口は success・action・hostname を必須にして確認できなければ拒否する。自動操作のブラウザは Turnstile を通れないので最終確認は人が送る。GitHub Pages の旧 URL は配信元を転送用ブランチに切り替え、組み直しを依頼する
-->
# 静的サイトにフォームの受け口を置く

公開サイトが静的ホスティング（GitHub Pages など）で、読者からの投稿（お便り・問い合わせ）を受けたい場面。

## <a id="options"></a>選択肢と、それぞれの壊れ方

静的ホスティングは置いたファイルを配るだけで、**送られてきた内容を受け取って保存するプログラムを動かせない**。
フォームの画面はサイト側で作れても、受け取る場所は別に要る。

| 方式 | 壊れ方 |
|---|---|
| `mailto:` でメールアプリを開く | **宛先のアドレスがページに出る**。メールアプリを設定していない端末では開かない |
| 別ドメインのフォームサービス（Google フォーム等）へ JS で送る | 別ドメインなので `no-cors` になり、**応答を読めない**。受け口がエラーを返しても画面は「届いた」と出る（実測: ローカルの受け口に 501 を返させても成功表示） |
| 同じサイトに関数を置く（Cloudflare Pages Functions など） | 同一オリジンなので**成否を JSON で読んで正しく表示できる**。宛先も出ない |

外部のフォームサービスを使う場合も、アカウント作成は利用者本人の操作になる。

## <a id="cloudflare-pages"></a>Cloudflare Pages + Functions + D1 の組み方

- **Workers でなく Pages で作る**: 作成画面は既定で Workers に誘導するが、Workers の URL は
  `<名前>.<アカウントのサブドメイン>.workers.dev` でアカウント名が入る。Pages は `<プロジェクト名>.pages.dev`
- **GitHub 連携は画面で 1 回**: Cloudflare の GitHub App をリポ（組織なら組織）に入れる許可は、所有者がブラウザで押すしかない
  （CLI では代われない）。「Only select repositories」で対象リポだけにする
- **Direct Upload で作ると、後から Git 連携に変えられない**（公式: "If you choose Direct Upload, you cannot switch to Git integration later."）。
  push で自動公開したいなら、最初から Git 連携で作る
- **生成物を commit しているサイトはビルド不要**: `wrangler.toml` に `pages_build_output_dir = "docs"` などを書き、
  ビルドコマンドは空。`functions/` はリポのルートに置く（出力ディレクトリの中ではない）。`wrangler.toml` はダッシュボードの設定より優先される
- **存在しない URL にはトップページが返る**（`404.html` が無いと SPA 扱い）。リポの他のファイル（`wrangler.toml` 等）は配信されない
- **D1**: `wrangler d1 create <名前>` → `wrangler.toml` の `[[d1_databases]]` に id（秘密ではない）→
  `wrangler d1 execute <名前> --remote --file=schema.sql`。1 行は 2 MB まで
- 無料枠（公式ドキュメント、執筆時点）: 静的ファイルは無制限、関数は Workers と合わせて 1 日 10 万リクエスト、
  D1 は 1 日 500 万行の読み・10 万行の書き・全体 5 GB、Turnstile は回数無制限

## <a id="endpoint-design"></a>受け口の作り

- 同じサイトからの送信だけ受ける（`Origin` のホストがリクエスト先と違えば 403）
- 人には見えない欄を置き、埋まっていたら**成功を返して保存しない**（機械に失敗を学ばせない）
- 長さの上限を持つ。上限は「長さの目安」ではなく**いたずらの 1 通を大きくさせない蓋**なので、人が書く分には
  実質無制限の値でよい（例: 400 字詰め原稿用紙 50 枚）。保存先の 1 行の上限より十分小さくする
- `fetch` からは JSON、JavaScript の無い普通のフォーム送信（`Accept` に `application/json` が無い）には
  ページへの 303 転送を返す（生の JSON 画面を見せない）
- 送り主を特定する情報（IP・メールアドレス）は保存しない。未読／既読は日時の列で持ち、消さない
- メール通知は、Cloudflare からの送信に**独自ドメインの登録が要る**（Email Service のエラー
  `E_SENDER_DOMAIN_NOT_AVAILABLE`）。ドメインが無ければ、溜まった分を読みに行く道具を作り、日常の確認面（ダッシュボード等）に未読件数を出す

## <a id="turnstile"></a>Turnstile（ロボット判定）

- **wrangler で作れる**: `wrangler turnstile widget create` があり、`wrangler login` の権限に
  `challenge-widgets.write` が含まれる（手元の 4.131 で確認）。古い版や API トークン前提の手順だけを見て「画面でしか作れない」と決めない
- **秘密鍵は画面にもファイルにも出さない**: 作成時の JSON を 1 つのシェルの変数に受け、`jq` で取り出し、
  `wrangler pages secret put TURNSTILE_SECRET --project-name <p>` へ**標準入力で**渡す。前後に `pages secret list` で書き込み先を確かめる
- **秘密鍵の確認**: `widget get` で返る秘密鍵が作成時と同じこと、ドメインとモードが合うこと、テスト用トークン
  `XXXX.DUMMY.TOKEN.XXXX` で siteverify すると `invalid-input-response`（`invalid-input-secret` ではない）になること
- **受け口の合格条件は 3 つ**: `success === true`、`action` が期待値、`hostname` が本番のホスト名（`localhost` を本番に入れない）。
  秘密鍵が無い・通信失敗・形が変は**拒否**（確認できないものは受け付けない）
- **トークンは 1 回きり**（公式: "Each token can only be validated once. A replayed token will be rejected with the `timeout-or-duplicate` error code."）、
  有効期限は 5 分。ページは確認欄を**明示描画して ID を持ち、送るたびにその ID でリセット**する。期限切れの自動更新
  （`refresh-expired`）は既定で有効
- **自動操作のブラウザは Turnstile を通れない**（トークンが発行されない、実測）。**判定を突破しようとしない**。
  本物の確認を通った送信の最終確認は、人に自分のブラウザから 1 通送ってもらい、保存を確かめる
- ローカルでは Cloudflare のテスト用の鍵（必ず通る／必ず落ちる）と `.dev.vars` で試す

## <a id="local-verification"></a>アカウントに触らずに確かめる

`npm i -D wrangler` → `npx wrangler d1 execute <名前> --local --file=schema.sql` → `npx wrangler pages dev`。
受け口に正常・空・長すぎ・別オリジン・罠の欄入り・上限ちょうど／1 字超過を投げ、表を読んで保存を確かめる。
上限の境目は、BMP 外の文字（絵文字）で数え方がずれないかも見る（JS の `length` は UTF-16 の単位）。

## <a id="github-pages-redirect"></a>GitHub Pages の旧 URL から新しい URL へ転送する

GitHub Pages はサーバー側の転送ができない。

1. 転送用のブランチ（例: `gh-pages`）を作り、`docs/index.html` と `docs/404.html` に同じ転送ページを置く:
   `location.replace(新URL + location.pathname + location.search + location.hash)`（同じ場所へ）+
   `<meta http-equiv="refresh">`（JS 無し用）+ `rel="canonical"` + `noindex`。`.nojekyll` も置く
2. Cloudflare がそのブランチをプレビューとして組んでも失敗しないよう、ブランチにも出力先だけの `wrangler.toml` を置く
3. 配信元を切り替える: `gh api -X PUT repos/<o>/<r>/pages -f "source[branch]=gh-pages" -f "source[path]=/docs"`
4. **切り替えただけでは組み直されない**（切り替え前の中身のまま、実測）→ `gh api -X POST repos/<o>/<r>/pages/builds`
5. CDN が 10 分ほど古い中身を返す（`cache-control: max-age=600`）。確認はキャッシュされていないパスで行う

## 変更履歴

- 初版: 静的サイトから同一オリジンの受け口への引っ越し一式（選択肢の壊れ方・Pages・D1・受け口・Turnstile・転送）を実運用から整理
