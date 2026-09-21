<!-- doc-meta
when: ポッドキャストを RSS で各配信先 (Spotify / Apple Podcasts / Amazon Music / YouTube) に登録するとき + 番組の画像・説明文・各回の紹介文を配信先に載せるとき + 公開予約を API で入れる・配信を自動にするとき + LISTEN (listen.style) を API で操作するとき
category: office
summary: 配信先への登録は「ホストの RSS を渡し、RSS のメール宛に届く確認で持ち主を示す」の繰り返しで、先に RSS を完成させる (1 回分以上・長さ入り)。画像は RGB の JPEG で渡す (PNG は透明度つきに保存し直されることがある)。ホストの RSS の番組リンクは変えられないことがあるので、公式サイトへのリンクは番組の説明文と各回の紹介文の末尾に書く (回ごとの目印つき)。API で公開予約を入れるときは時差が無視されうる = UTC に直して渡し、作ったら読み戻す。無人のマシンに配信させるなら、音声を読む仕事 (上げる・予約する) は OK を出す手元でやり、無人の側は公開の確認と掲載と知らせだけにする。LISTEN は GraphQL で上げられるが、番組の設定を変える口は無い
-->
# ポッドキャストの配信（配信先への登録・載せる文・公開予約）

仕上げた音声をホスト (RSS を出すサービス) に上げ、各配信先に番組を登録し、回ごとに公開していく場面。
音声の仕上げそのもの (音量・ジングル) は [`podcast-audio-finishing.md`](podcast-audio-finishing.md)、
収録の分割は [`audio-transcription.md#splitting-long-recordings`](audio-transcription.md#splitting-long-recordings)。

## <a id="rss-directories"></a>配信先への登録

どの配信先も「ホストの RSS の URL を渡す → RSS に書かれたメールアドレス宛に届く確認で持ち主を示す」の形をとる。
**先に RSS を完成させる**: 回が 1 つも無い・長さ (`itunes:duration`) が空の RSS は登録の段で失敗する (実測、Spotify)。
アカウントの作成・パスワード・電話番号・支払い方法・規約への同意・本人確認は番組の持ち主が自分でやる。
確認のメールは RSS のアドレス宛なので、そのメールボックスが読めれば確認コードの受け取りは代われる。

| 配信先 | 入口 | 持ち主の確認 | 注意 (実測) |
|---|---|---|---|
| Spotify | Spotify for Creators の「既存の番組を追加」 | RSS のメール宛に数字の確認コード | カテゴリは RSS でなく登録画面で選ぶ (3 つまで)。ホスト一覧に無ければ「その他」。一度「数分待って」で失敗し、画像を JPEG に替えた後に通った (どれが効いたかは切り分けていない)。番組ページが開くまで数時間 |
| Apple Podcasts | Podcasts Connect の「RSS フィードがある番組を追加」 | Apple Account でのログイン | Apple Account は支払い方法の登録と Apple Podcasts の規約同意で有効になる。追加すると下書き → 「コンテンツ配信権」の選択 → 処理が終わってから「公開」→ 審査 (数日)。カテゴリは主と副の 2 つだけ使う ([Apple Podcasts categories](https://podcasters.apple.com/support/1691-apple-podcasts-categories)) |
| Amazon Music | Amazon Music for Podcasters | RSS のメール宛に確認のリンク | 配信が始まると番組ページの URL がメールで届く (実測では 1 時間以内)。Audible にも出る |
| YouTube | YouTube Studio「作成 → 新しいポッドキャスト → RSS フィードを送信」 | 上級機能の解放 (自撮りの短い動画 / 身分証 / 一定期間の利用履歴のどれか) | 電話番号の確認だけでは開かない。審査は通常 24 時間と表示される |

登録できたら、各配信先の番組ページの URL を公式サイトとホストの「配信先」欄に入れる。
URL は開くことを確かめてから入れる (登録直後は開かない)。

## <a id="artwork-jpeg"></a>番組の画像は RGB の JPEG で

3000 × 3000 の PNG をホストに上げると、透明度つき (RGBA) の PNG に保存し直されて容量も膨らむことがある (実測)。
Apple Podcasts は RGB を求めるので、**配信先に渡すのは RGB の JPEG** にする (JPEG は透明度を持てないので同じことが起きない)。
PNG は元の絵として手元に残す。

## <a id="show-website-link"></a>公式サイトへのリンクは説明文に書く

ホストが出す RSS の番組リンク (`<link>`) はホスト自身の番組ページに固定され、変える欄が無いことがある (実測)。
その場合、公式サイトへのリンクは**番組の説明文の末尾**と**各回の紹介文の末尾**に書く。アプリは各回の紹介文を
番組の説明文より目立つ所に出すので、回の方にも要る。サイトの各回の区画に目印 (`id="ep3"` など) を付け、
紹介文からは `…/#ep3` でその回へ直接飛ばす。回の紹介文に足す 1 行は予約の道具で自動で付けると漏れない。

## <a id="host-normalization"></a>ホストの音量調整は外す

手元で -16 LUFS に仕上げたなら、ホストのアップロード時の「ラウドネスをノーマライズする」は外す。
作り直させると符号化が 1 回増え、雑音除去が入ることもある。外して上げると、配信ファイルが手元の MP3 と
バイト単位で同じになることを確かめられる (sha256 を比べる)。

## <a id="scheduled-publish-api"></a>API で公開予約を入れるとき

- **時差の指定が無視されることがある**: `+09:00` 付きで渡しても、その数字が UTC として保存された (実測、LISTEN)。
  現地時間の枠は UTC に直し、時差を書かない形で渡す。作ったら**予約時刻を読み戻して**期待と比べる
- 予約時刻を渡すと状態は「予約済み」になる (下書きを指定しても)。公開はホストが時刻に行い、配信先には RSS で届く
- 紹介文を後から書き換えるときは、書き換えない欄 (題・公開範囲・回の番号) も読んだ値を渡し直す。
  省いた欄が消えるかはサービス次第なので、書き換えの前後で全欄を読み比べる

## <a id="unattended-release-split"></a>配信を無人のマシンに任せるとき

音声は多くの場合クラウドストレージか作業用のマシンにある。無人のマシンの launchd からは
`~/Library/CloudStorage/` が読めないことが多い ([`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md))。
そこで仕事を 2 つに分ける:

1. **手元 (回を用意する場)**: 仕上げ・題・紹介文を用意して持ち主の OK をもらい、**OK を記録したその場で**
   音声を上げて公開予約まで済ませる。予約表 (回ごとの題・紹介文・音声の sha256・枠・OK・状態) を git に置いて push する
2. **無人のマシン**: 1 日数回、予約表を pull して、予約した回が公開されたかをホストに問い合わせ、公開されたら
   公式サイトに載せて push する。次の枠が空・OK 待ちの回が近い・OK 済みなのに予約されていない・公開時刻を過ぎても
   公開されない、を知らせる。**音声は読まない**

こうすると、無人のマシンに要るのは 2 つの repo と API のトークンと git の push だけで、マシンを替えても担当を移すだけで済む。
同じことを知らせ続けないよう、知らせの本文が前回と違うときだけ送る (起きたこと = 予約した・公開した、は毎回送る)。

## <a id="listen-style-api"></a>LISTEN (listen.style) の API

公式の説明書は無く、GraphQL を introspection で読んだ (実測)。

- 窓口 = `https://listen.style/graphql`、認証 = Bearer の API トークン (設定の「API トークン」で作る)
- 音声 = `createPresignedUploadUrl(fileName, type: AUDIO, contentType)` → 返った `uploadUrl` に PUT → `path` を
  `createEpisode(..., media: {audioPath})` に渡す。`createEpisode` は `status: SCHEDULED` + `scheduledAt` で予約、
  `normalizeLoudness: false` でホストの音量調整を外す。`scheduledAt` の時差は無視される (上の節)
- 読む = `episodes(ids)` / `podcast(id)`。紹介文は **HTML で保存される** (`<p>…</p>`)
- 紹介文の書き換え = `updateEpisode` (題と公開範囲は必須。回の番号も渡す。状態・音声・出演者は省けば変わらなかった)
- **番組の設定 (説明文・配信先の URL・カテゴリ) を変える mutation は無い** = 画面から。作成画面ではカテゴリを 1 つしか選べない
- 公式の MCP (`@ondinc/listen-mcp-server`) は読むだけ
- RSS は python の `urllib` の既定の User-Agent だと 403 を返す (curl では読める)

## 関連

- [`podcast-audio-finishing.md`](podcast-audio-finishing.md) — 配信用の音声の仕上げ
- [`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md) — launchd からクラウドストレージを読む
- [`static-site-form-backend.md`](static-site-form-backend.md) — 静的サイトの受け口 (お便りフォーム等)
