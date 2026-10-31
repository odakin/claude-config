<!-- doc-meta
when: WebSearch / WebFetch / browser 自動化の信頼性を判断するとき + ある図書館が本を所蔵しているかを API で確かめるとき (#cinii-library-holdings) + 生成した HTML を内蔵 Browser pane で開いて tool で確かめるとき (#browser-pane-local-file-snapshot) + 内蔵 Browser pane でサイトにログインしているかを判定するとき (#login-state-check) + ログイン画面を見てサイトの公開範囲を言う前 (#login-page-not-access-restriction) + Google サイトの編集画面を pane で操作するとき (#google-sites-editor) + 手元の preview を見られない相手にページを画像で見せるとき (#headless-page-screenshot) + 学会サイトの記事 PDF がリンク切れで入手の経路を探すとき (#dead-society-pdf) + YouTube の音声を取得するとき・HTML しか渡っていないとき・yt-dlp が SABR / 403 で失敗するとき (#youtube-audio-extraction) + 企業サイトの製品の告知ページが WebFetch・curl で 403 を返すとき (#corporate-notice-403) + 先行研究を API で探す・「扱った研究は無い」 を範囲つきで書くとき (#literature-search-apis)
category: web
summary: #javascript-tool-gotchas (async IIFE → `{}` / 出力 filter = 文字 whitelist / 戻り値は約 3KB で切れる / 内部 endpoint 直叩き) + Claude in Chrome の permission 障害は再インストール前に `list_connected_browsers` (再ログイン後の stale 接続) + WebSearch / WebFetch の信頼性 caveat (summary hallucination、 事実値は source 直接確認) + CSR SPA は fetch に空シェル (200≠実在、 実ブラウザ描画で検証) + booking.com の宿への連絡は確認メールに返信しても届かない = web のメッセージ画面を pane で開きログインは本人 (#booking-property-messaging) + **claude.ai share ページは in-app Browser pane が素通し / page 内 same-origin fetch は snapshot API も 200 (= headless / curl は全滅、 #claude-share-page-access)** + **browser cookie replay は OAuth-token SPA を認証しない (= Box `/f/` 等 member 限定クラウドフォルダは無人 upload 不可、 session API 401 / shared-item 404 で spike 1 回で確定)** + Claude in Chrome MCP の 2 層 permission モデル + bug 53630 (sites/docs.google.com domain silent block) + **内蔵 Browser pane で frameset / popup / 連動 select の古い web app を JS で読み書き (#browser-pane-frameset-popups、 拡張が prompt 無しで拒否する domain の逃げ道)** + Google サイトの編集画面は本文への `type` が確定しない = リンク挿入の窓で文と URL を入れ、 中身は節の削除で消し、 公開は確認画面を経て cookie なしの取得で確かめる (#google-sites-editor)
-->
# Web ツール (WebSearch / WebFetch) の信頼性 caveat

WebSearch / WebFetch は便利だが post-processing 由来の落とし穴があり、**事実確認用途では補助検証が必須**。

> **関連**: tool result に外部由来の adversarial 指示文が混入する prompt injection の取扱は別規約 [prompt-injection.md](prompt-injection.md) に分離 (web tools 以外の MCP / Bash / Read にも横断するため)。

## <a id="websearch-summary-hallucinates"></a>WebSearch の summary は hallucinate する

WebSearch の result block 末尾に付く自然言語 summary は検索エンジンが推測した情報を含み、リンク先 source に存在しない値を捏造することがある。**事実値 (メールアドレス・電話番号・URL・固有名) は summary だけで採用してはいけない**。

### How to apply

- メールアドレス・電話番号・URL のような事実値は、リンクされた source ページ (公式サイト・PDF press release 等) の原文を curl で取って確認してから採用する (WebFetch の答えも要約モデルを通る = 下の [#webfetch-answer-is-generated](#webfetch-answer-is-generated))
- 複数の異なる値が出てきたら最新の公式 source を優先
- ヒットしたリンクのうち最も authoritative なもの (組織の公式 domain 等) を優先

### 典型パターン

ある組織の窓口メールアドレスを WebSearch で取得しようとすると、summary に「`<role>@<domain-A>`」 のような値が返ってくることがある。実際に source を確認すると、PDF (古い文書) には「`<role>@<domain-B>`」、現行公式 contact ページには「`<role>@<domain-C>`」 と書いてあって、summary に出た `<domain-A>` 版はどちらにも存在しない hallucination だった、というケース。検索エンジンが「`<role>` + 組織ドメインの慣用 prefix」 から推測しただけ。

### <a id="webfetch-answer-is-generated"></a>WebFetch の答えも生成物 — 原文の数・主張の確認に使わない

WebFetch は取った page を小さなモデルに渡し、 prompt への答えを返す。 その答えは原文の写しではなく生成物で、 原文に無い数や主張を足すことがある (実測: 論文 PDF のある節の要約を頼むと、 原文が「3 か 4」 とする数を「5〜7」 と答え、 原文に無い検査の基準まで並べた)。 原文の数・言い回し・ある節の推奨を確かめるときは、 原文を読む = PDF は curl で取って PyMuPDF で text にするか、 手元の写しを開く。 WebFetch の答えと規約の記述が食い違ったら、 まず WebFetch の側を疑う。

## <a id="youtube-audio-extraction"></a>YouTube の音声を取得する — HTML・通常配信・HLS を分ける

音声の解析を頼まれたときは、URL から取得できるかを先に確認する。取得を試す前に、利用者へ音源の用意と再添付を丸投げしない。
WebFetch の失敗や検索の 0 件は、動画や音声の不存在を意味しない。ページのタイトル・投稿者・説明欄は実ブラウザで確認できる場合がある。

### HTML と音源の区別

- ページをコピーした `<!DOCTYPE html>...` は音声ファイルではない。YouTube は音声を別に配信する。
- 保存 HTML の `ytInitialPlayerResponse.streamingData.adaptiveFormats` に `audio/mp4` / `audio/webm` があっても、直接取得する `url` があるとは限らない。`serverAbrStreamingUrl` だけ、または映像形式に `signatureCipher` がある場合もある。HTML の JS を実行せず、必要な JSON のフィールドだけを読む。
- 形式の一覧と、実際にダウンロードできることは別に確かめる。期限付き配信 URL には IP・署名などが含まれ得るため、正本や公開ログには残さず、必要なら通常の動画 URL を案件側で管理する。

### 取得と M4A への格納

使う Python・Node.js・`yt-dlp`・FFmpeg の実体と版を確認する。古い `yt-dlp` が失敗した場合は、対応する Python の一時 venv に現行版を入れて再確認する。既存のシステム環境を更新する作業とは分ける。
通常の `-f bestaudio` が 403 で失敗しても、同じ公開動画の HLS 音声は取得できる場合がある。

以下は Bash / zsh 用。`python3.14` は実在する対応版に置き換え、URL を指定し、同じ shell で順に実行する。Node.js・`ffmpeg`・`ffprobe` が PATH にあることが前提。

```bash
audio_work=$(mktemp -d "${TMPDIR:-/tmp}/youtube-audio.XXXXXX")
python3.14 -m venv "$audio_work/venv"
"$audio_work/venv/bin/python" -m pip install --disable-pip-version-check 'yt-dlp[default]'
node_bin=$(command -v node)
video_url='https://www.youtube.com/watch?v=VIDEO_ID'

"$audio_work/venv/bin/yt-dlp" \
  --js-runtimes "node:$node_bin" \
  --no-playlist --no-progress --socket-timeout 15 \
  --retries 1 --extractor-retries 1 --fragment-retries 1 \
  --abort-on-unavailable-fragments \
  -f 'bestaudio[protocol=m3u8_native]/best[protocol=m3u8_native]' \
  -o "$audio_work/source.media" "$video_url"

ffprobe -v error \
  -show_entries format=format_name,duration,size:stream=codec_name,codec_type,sample_rate,channels \
  -of json "$audio_work/source.media"
```

`/best[...]` は音声と映像を含む HLS も候補にする。取得したファイルに音声 stream があることと codec を読み、**AAC なら**次で無再エンコードの M4A にする。他 codec なら対応するコンテナを選ぶか、必要な変換を明示する。

```bash
ffmpeg -hide_banner -loglevel warning -n \
  -i "$audio_work/source.media" -map 0:a:0 -c:a copy "$audio_work/audio.m4a"
ffprobe -v error \
  -show_entries format=duration,size:stream=codec_name,codec_type,sample_rate,channels \
  -of json "$audio_work/audio.m4a"
ffmpeg -v error -xerror -i "$audio_work/audio.m4a" -map 0:a:0 -f null -
```

各コマンドの終了値を確認し、失敗した段で止める。HLS の一部欠落を成功扱いしないため、取得時に `--abort-on-unavailable-fragments` を指定する。
拡張子で中身を判定しない。HLS から `.mp4` 名で保存されたものが生 AAC だった実測があり、その長さは bitrate からの推定値だった。M4A に格納した後の長さ・codec・デコード結果を確認し、動画の表示尺と大きく違えば欠落を調べる。
一時フォルダは恒久保管先ではない。後続作業に残す音源は、その案件の成果物置き場へ移し、利用者が開けるファイルの参照を渡す。

### 実測範囲と失敗の切り分け

2026-10-17、macOS の公開動画 1 件で確認:

| 経路 | 結果 |
|---|---|
| Python 3.9 / `yt-dlp` 2025.10.14 | Python 非推奨・SABR の URL 欠落警告の後、ページ再読込を要求して失敗 |
| Python 3.14.4 / Node.js 22.16.0 / `yt-dlp[default]` 2026.08.19、`-f bestaudio` | 形式 251 を選べたが、音声本体の取得は HTTP 403 |
| 同じ一時環境で上の HLS 選択式 | 形式 234、31 fragment を取得。FFmpeg 6.0 で AAC を M4A に格納し、44.1 kHz・2 ch・動画の表示尺に合う長さを確認 |

成功時の取得コマンドには `--abort-on-unavailable-fragments` が付いていなかった。上の再利用手順では欠落時に止める指定を加えた。全動画・認証が要る動画・他 OS での成功を保証する実測ではない。
DNS エラーは実行環境のネットワーク許可を、403 は選んだ配信形式と現行ツールの対応を切り分ける。sandbox の許可は正規の承認経路で扱い、ログイン・権限・地域制限を越える手順にはしない。
**音声の取得、デコード、聴取、文字起こし・採譜の検証は別段階**として報告する。ファイルが取れただけで、演奏を聴いた・正確に採譜できると約束しない。
音声から文章を起こすときの検証は [audio-transcription.md](audio-transcription.md) を参照。

## WebFetch は `<head>` 内 meta タグ・JSON-LD を落とす

WebFetch は HTML → markdown 変換 + 内部要約モデル処理を経るため、`<head>` 内の `<meta>` `<link>` `<script type="application/ld+json">` 等は実質的に削られる。「**Open Graph / Twitter Card / canonical / verification meta / JSON-LD / hreflang を確認したい**」 用途では WebFetch は使えない。

### How to apply

- meta / OG / JSON-LD / canonical / hreflang / verification token の検証は **`curl + sed` で生 HTML を取得して grep** する
- 例: `curl -sS https://example.com/ | sed -n '/<head>/,/<\/head>/p'`
- JSON-LD が body 内に出力されているケースもあるので、見つからなければ `curl ... | grep -A20 '"@type"'` で全文 grep
- WebFetch は記事本文抽出・要約・自然言語回答用途には適切 (= ナラティブ系コンテンツ向け)

### 典型パターン

WebFetch に「`<head>` 内の meta タグを抽出して」 と prompt しても「<head> セクションは提供されていません」 と返答するケースがある。post-processing で削られているため。代わりに `curl + sed` で head を取得して verification meta / Open Graph / JSON-LD を直接確認する。SEO 検証 (Search Console verification token / OG image / Event JSON-LD 等の live 確認) で典型的に発生する。

## <a id="csr-spa"></a>CSR な SPA は WebFetch / fetch に空シェルしか返さない (= 200 ≠ ページ実在)

Client-side rendering の SPA (= JS が描画してから中身が入るサイト) は、**WebFetch も同一オリジンの `fetch()` も、実在 route と存在しない route に対して同一の空アプリシェル (HTTP 200・ほぼ同一バイト数・本文テキストなし) を返す**。サーバーが routing を JS に委ねており unknown route でも 404 を返さず shell を返すため。つまり **HTTP status 200 や fetch 成功は「その URL が実在し、その内容である」 ことの保証にならない** (= `mcp.md` / inline §3「tool の signal を guarantee と取り違えない」 の false-positive 版 — null を不在と短絡する裏返しで、 200 を実在と短絡する形)。

### How to apply

- SPA の URL の**実在・内容**を確認したいときは、**JS を実行する実ブラウザ (Claude in Chrome 等) で navigate して、描画後の DOM** (本文テキスト量・`<h1>`/見出し・期待語の有無) で判定する。`curl`/WebFetch の status や生 HTML では判別できない
- **404 の見分けは status でなく描画後の content** で行う: 実在ページは本文が十分長く期待トークン (固有名・見出し) を含む / 不在ページは別 fallback (極端に短い本文・無関係な見出し) に落ちる。両者を 1 件ずつ実測して閾値を掴んでから一括判定する
- 描画ツールが**無い**環境では「fetch では検証不能」 と正直に surface する (= search index が返す**そのページ自身の `<title>` + 一致するスコア/固有名**は弱い corroboration として使えるが、 live render 確認ではないと明示する)
- WebFetch は記事本文抽出・要約には有効 (= サーバーが本文を返す従来型ページ向け)。SPA の存在確認には不適

### 典型パターン

CSR SPA のニュース/結果ページの URL を多数検証する場面 (例: fifa.com の試合レポート URL を 40 本) で、`fetch` は実在 URL も故意の偽 URL も同一の空シェル (200・~4.5KB・本文/og:title なし) を返し status からは判別不能だった。実ブラウザで navigate すると、実在ページは本文数千字 + 該当見出しが描画され、不在ページは本文 ~140 字の無関係 fallback に落ちる明確な差が出た。**「200 が返った = ページがある」 と短絡せず描画後 DOM を読む**ことで全件を確定できた。

## <a id="claude-share-page-access"></a>claude.ai の share ページは in-app Browser pane なら読める (= headless / curl は全滅、 page 内 fetch なら API も通る)

`claude.ai/share/<uuid>` (= 会話の公開共有ページ) は前節の CSR SPA + Cloudflare bot 保護の複合で、 経路によって結果が全く違う (2026-08-24/28 実測):

| 経路 | 結果 |
|---|---|
| WebFetch / curl (browser UA でも) | 200 だが空シェル (本文なし) |
| curl で `/api/chat_snapshots/<id>` | 403 Cloudflare チャレンジ |
| headless ブラウザ (CDP) | 描画後も Cloudflare interstitial (= bot 判定) |
| **Claude Code 内蔵 Browser pane** | **✅ 完全レンダリング** — `get_page_text` で会話全文が読める |
| **ページ内 (page context) からの same-origin `fetch`** | **✅ snapshot API も 200** で JSON 全文 |

### How to apply

- **user が share URL を貼ったら、 内蔵 Browser pane で開いて読むのが最短** (`preview_start {url}` → `get_page_text`)。 login 不要。 会話 DOM は全文が実高さで layout される (= 中規模会話で非仮想化を実測、 超長会話は未検証)
- pane 内で blob download を発火させると macOS では `~/Downloads` に着地する (= agent 自身が export 動作を e2e 検証できる)。 ⚠️ 同名 file の再 download は隠し temp (`.XXXX.com.anthropic.…`) のまま確定しないことがある (n=1 観測) — 検証時は既存 file を先に消す
- 構造化 (message 単位・話者付き) が要るなら `javascript_tool` で page context から `fetch('/api/chat_snapshots/<id>?rendering_mode=messages')` — JSON schema の実測 gotcha: `chat_messages[].text` は**空**で、 本文は `content[]` の `type:"text"` block 群 / web 検索を含む会話には placeholder block (「\`\`\`This block is not supported on your current device yet.\`\`\`」 literal) が混入 / 引用は `<cite index="…">` タグが本文に埋まる (タグだけ strip) / message 単位の `truncated` flag あり
- ログイン済みの通常会話ページ (`/chat/<uuid>`) も同型: `/api/organizations` で org uuid → `/api/organizations/<org>/chat_conversations/<id>?tree=True&rendering_mode=messages` (= share 経路と違い login cookie が要る。 2026-08-28 時点で式のみ・未実測)
- **user 側の手元 export はブックマークレットが適形** (= 自分のブラウザ・自分のクリック = bot 保護の回避ではない)。 gotcha 3 つ: ① `javascript:` URL はアドレス欄ペーストで prefix が剥がされる → ブックマーク作成後に**編集画面の URL 欄**へ貼る (スマホも同じ、 実行はページを開いた状態でアドレス欄にブックマーク名を打って候補 tap) ② 生成 Blob は **UTF-8 BOM を付ける** — Android の text viewer は charset ヒント無し UTF-8 を Shift_JIS と誤判定して文字化け表示する (中身は健全なので気付きにくい) ③ `#` を含む文字列は `\x23` に escape (= URL fragment 切断対策)
- **線を守る**: 実ブラウザの画面 / user のクリックで閉じる形は正当。 これを headless 化・無人化・stealth flag で回すのは bot 保護の回避で、 やらない (session の他の操作まで permission guard に落ちる実害も観測済)

### 典型パターン

「claude.ai の会話を Claude Code に渡したい」: share URL を curl / WebFetch / headless で読もうとして全滅し、 bot 保護の回避に向かいそうになる — が、 正解は上の 2 経路 (pane 直読 / page 内 fetch)。 スマホからでも share ページ + ブックマークレット 1 tap で全文 `.md` が落とせる。

## <a id="booking-sites-browser-pane"></a>予約サイト (じゃらん / booking.com / 価格.com) の料金表は WebFetch でなく Browser pane で読む

宿の料金・部屋一覧・運営者情報を裏取りするとき、 WebFetch は 3 通りに壊れる (実測):

| サイト | WebFetch の結果 | Browser pane (`navigate` → `get_page_text`) |
|---|---|---|
| じゃらん (`jalan.net/yad<ID>/plan/`) | 本文が文字化けして要約側が「読めない」 (文字コードの取り違え) | ✅ 全プラン × 全部屋の 1 名 / 2 名料金、 「※バスなしトイレなし」 注記、 空室カレンダーまで text で取れる |
| booking.com (`/hotel/jp/<slug>.ja.html`) | 空 (JS 描画) | ✅ 部屋タイプの literal 名、 評価点と件数、 管理者の自己紹介文、 規則 (門限・年齢) が取れる。 料金は日付を選ぶまで出ない |
| 価格.com トラベル (`travel.kakaku.com`) | `ENOTFOUND` (fetch 先から DNS 不到達) | 未実測 (WebSearch の summary に最安値が出るが、 summary は hallucinate しうる = 本 doc 冒頭) |
| フードデリバリーの店ページ (Uber Eats `/jp/store/…`) | 403 Forbidden | ✅ 住所を入れなくても、 セットと単品のメニュー名・宅配の価格・受付時間が text で取れる |
| 宅配ピザ等の注文サイト (店を選ぶまで値段を出さない SPA) | 空 or 値段なし | 値段は出ない (店と受け取り方の選択が要る) → 裏の一覧 API を読む ([`machine-route-first.md#read-only-endpoint-discovery`](machine-route-first.md#read-only-endpoint-discovery)) |

### How to apply

- **URL を先に組む**: じゃらんは施設 ID から `https://www.jalan.net/yad<ID>/plan/` (料金一覧)、 booking.com は `.ja.html` を付けると日本語で出る。 WebSearch で施設ページの URL を取ってから pane で開く
- **取る項目を決めてから読む** (口コミの裏取りなら [`consumer-review-posting.md#price-claim`](consumer-review-posting.md#price-claim) の一覧)。 `get_page_text` は 3 万字前後で「この宿を見た人は他に」 の推薦一覧が繰り返し混じるので、 `max_chars` は 25,000〜30,000 で足りる
- 料金は**日付・人数で変わる**ので、 幅 (最安〜通常) と取得日を手元の記録に残し、 公開文には幅だけ書く
- <a id="stale-third-party-prices"></a>**口コミ・地図・まとめ記事の価格は掲載時期が分からず、 古いことが多い** (実測: 地図サイトのメニュー欄の値が、 宅配アプリの現在価格から逆算した店頭価格よりはるかに安かった)。 人に伝える値は、 今注文できる経路 (公式の注文ページ・宅配アプリ・公式 PDF の価格表) で上か下を押さえてから出す。 宅配アプリの価格は店頭の 2〜3 割増し (実測) なので、 上限の目安には使えるが、 店頭価格そのものとしては書かない
- 店の「公式サイト」 として第三者の頁に載っている domain は、 失効して別物 (広告・カジノ等) に替わっていることがある (実測)。 運営会社の頁から辿った URL を使う

## <a id="booking-property-messaging"></a>予約サイト (booking.com) 経由で宿に連絡する = web のメッセージ画面を Browser pane で、 ログインは本人

予約した宿に書類 (領収書・宿泊の証明の様式) を頼む・到着の段取りを聞くなど、 宿に直接連絡したいとき:

- **確認メール・宿からの通知メールに返信しても宿に届かない** (実測): From も Reply-To も予約サイトの noreply。 宿のメールアドレスは確認メールに載らないことが多く、 無人運営 (スマートチェックイン) の宿はチェックイン案内にも載っていないことがある (実測)。 施設ページの「管理会社」 欄が実際の相手
- **連絡路 = 予約サイトのメッセージ**。 本人の携帯アプリではメッセージ欄が見つからないことがある (実測) → web の inbox を内蔵 Browser pane で開く: `https://secure.booking.com/inbox/partner-chat?vertical=accommodation&external_id=<予約番号>&bn=<予約番号>&product=post_booking&channel=partner_chat`
- **ログインは本人**: メールアドレスを入れると英字 6 文字の認証コードがメールで届く (件名にコードが入る、 実測)。 agent は本人のメールからコードを読んで伝えてよいが、 入力は本人 (認証情報を agent が打たない)
- 送信: 入力欄 (placeholder「メッセージを入力」) に `form_input` で本文 → aria-label「このメッセージを送信する」 のボタン → **送信後に画面の本文を読み戻して照合** (空行を含む改行は保たれた、 実測)
- **入力欄への記入も、 本人の「送って」 の後にする**: 下書きを見せただけの段階で本文を入力欄に入れようとすると、 自動モードの安全チェックが「実世界への送信」 として記入の段階で止める (実測)。 本人の明示の OK を取ったら、 記入 → 送信 → 読み戻しを一続きで行う。 本人が「なぜ送れないのか」 と聞いたら、 経路はある (ログイン済み) が、 その文面への OK が要る、 と答える
- **本文に URL を入れない・添付は付かない**: 予約サイトの messaging security がリンクを削除する (施設側が許可した domain だけ通る、 partner 向け資料の二次解説で確認)。 メッセージは「メールアドレスを聞く」 「受け取り方法を相談する」 に使い、 書類はアドレスが分かってからメールで送る
- 送信は外部発信 = 本文を chat で見せて本人の明示 OK を取ってから
- **宿の返事はメール通知が来ないことがある** (実測: web の inbox に返事が出てから 1 時間半以上、 通知メールが届かなかった)。 返事を待つときは web の inbox を開いて見る
- ログインしているかの判定は [`#login-state-check`](#login-state-check) (booking.com の実例: 「管理画面ログイン」 は footer の施設向けリンクでログイン中も出る / 推測した `messages.html` は「お探しのページが見つかりません」 に落ちる)。 予約番号が手元に無いときは header の吹き出しアイコンから「メールボックス」 を開く
- **無人運営の宿は、 勤め先の指定書式への押印・署名を断り、 自社の証明書を有料で (退室後に) 出すことがある** (実測)。 書式への押印が要る出張では予約前にメッセージで確かめる。 施設ページの設備欄に「フロントサービス: 領収書を発行可能」 とあれば、 施設発行の領収書を頼む理由として示せる (記載項目を並べて頼む = [`research-email.md#approver-vs-issuer`](research-email.md#approver-vs-issuer))。 ただしこの語が何を指すかは施設で違う: 予約サイトで決済した民泊が「直接の決済が無いので領収書は出せない、 インボイスなら出せる」 と答えた (実測) = 返事は全文を読み、 代わりに出せる書類を拾う。 書類の選び方の順序 = [`research-email.md#lodging-proof-choice`](research-email.md#lodging-proof-choice)
- **予約時に示されていない料金 (書類の発行手数料など) を求められたら**、 掲載・確認メール・案内のどこにも無いことを証拠に残し ([`#listing-evidence-capture`](#listing-evidence-capture))、 返事の中で「予約時に提示の無かった料金」 と名指しして、 予約サイトへの相談を考えていると添える。 強さは、 条件つき + 「〜も考えております」 程度が通りやすい (断定の「申し立てます」「ご了承ください」 は強すぎ、 「念のため確認させていただければ」 は弱すぎ、 と本人に直された = 実測)

## <a id="corporate-notice-403"></a>企業サイトの製品の告知ページが WebFetch・curl で 403 のとき = 打ち直さず、 同じ会社の別の頁と報道で埋める

大手メーカーの企業サイトの告知ページ (製品のお詫び・お知らせ) が、 WebFetch でも curl でも `403` / `Access Denied` (CDN の bot 判定、 参照番号つきの短い頁) を返すことがある。 ブラウザ風の User-Agent・`Accept-Language`・`Referer` を付けても同じだった (実測)。

- **header を変えて打ち直さない** — 2 回目の 403 で止める。 それ以上は bot 保護の回避に寄る (線は [`#claude-share-page-access`](#claude-share-page-access) の「線を守る」 と同じ)。
- **同じ会社の別のドメイン (製品サポートの案内の頁) は読めることがある** (実測)。 対象の確かめ方・当面の使い方・受付時間はそちらに出る。 ⚠️ 電話番号と対象品番の一覧は告知の頁にしか無く、 案内の頁は link で指すだけのことがある (実測) = 案内の頁を読んで「電話番号は公表されていない」 と言わない。
- **品番・台数・事故件数は業界紙・報道が告知を写して載せる** — 使ったら出所 (記事の URL と日付) を記録に書く。
- **本人が申込フォームを開いているなら、 その頁の文を貼ってもらう** — フォームの頁に問い合わせ先の電話番号・受付時間・項目の一覧が出ていた (実測)。
- 埋まらない項目は「未確認 (403 で開けず)」 と書き、 推測で埋めない。 内蔵 Browser pane で開けるかは未実測。

## <a id="listing-evidence-capture"></a>掲載内容を証拠に残す (後から書き換えられる前に) — pane の画面キャプチャ + 元メールの .eml + ハッシュ

予約サイト・通販の掲載 (料金・設備・規則) や相手とのメッセージを、 争いに備えて残すとき:

- **画面**: 内蔵 Browser pane に該当箇所を出し、 macOS の `screencapture -x -R <x>,<y>,<w>,<h> <file>.png` で pane の範囲を撮る。 範囲の上端を 0 にしてメニューバーの時計を入れると、 撮った日時が画像に残る。 範囲は一度全画面 (`screencapture -x`) を撮って pane の位置を読んでから決める。 横にはみ出す頁は `document.documentElement.style.zoom` を下げてから撮る (表示倍率だけで中身は変わらない = 記録に書き添える)。 被さる通知 (セキュリティの注意等) は × を押してから撮る
- **元のメール**: Gmail API の `format=raw` で .eml に保存する (送信元の DKIM 署名が付いたまま = 後から改変できない)。 予約番号や暗証番号が入るので、 渡すときは伏せる
- **本文の検索結果**: 争点の語 (手数料・金額・証明) が掲載に**無い**ことも証拠になる = 頁の全文を読み込ませてから (下までスクロールして遅延読み込みを出す) 語を数え、 件数を記録に書く
- **一覧**: 各ファイルが何を示すか + 取得日時 + `shasum -a 256` を 1 つの txt にまとめる
- ⚠️ headless Chromium (`--headless --print-to-pdf`) は予約サイトの頁で終わらなかった (実測、 timeout)。 粘らずに pane + `screencapture` に切り替える
- <a id="booking-docs-from-mail"></a>**予約サイトの領収書・予約確認書を事務に出す PDF にするときは、 受信メールの原本から作る** (実測): 予約サイトが送る「領収書」 メールはサイトの「領収書を印刷」 と同じ中身。 .eml から本文の HTML を取り、 `cid:` の画像を data URI に置き換えて、 ローカルの HTML を headless Chromium で PDF にする (ローカル file なら終わる)。 pane でサイトの「印刷」 を押すと print dialog、 page から file を保存させると毎回の保存確認が本人の画面に出る (本人に「いちいち出るのがうざい」 と言われた) = pane では取らない。 予約確認書には予約の暗証番号が載るので、 事務に出すなら伏せる
- 保存先は git の外 (本人の同期ストレージ)。 記録 (TODO 等) には所在だけ書く ([`confidential-repo-boundary.md#physical-access-codes`](confidential-repo-boundary.md#physical-access-codes) と同じ扱い)

## <a id="cookie-replay-oauth-spa"></a>Browser cookie replay は OAuth-token SPA を認証しない (= member 限定クラウドフォルダは無人 upload 不可)

Chromium (Brave/Chrome) の cookie DB を復号して session cookie を replay すれば authenticated アクセスできる — これは **cookie-session 方式のサイト (伝統的サーバーセッション、 Slack の `d` cookie 等) にのみ成立**する。 **OAuth/token 方式の modern SPA (Box enterprise・多くの SaaS) では成立しない**: 認証本体は login 後に fetch される **in-memory の access token** で、 cookie DB には persist されないため、 cookie を全部そろえて replay しても API 呼び出しが 401 になる。

### How to apply

- **クラウドフォルダの共有 link の種別を最初に見分ける**: 公開共有 link (Box `/s/…`、 Drive の「リンクを知っている全員」) は anonymous / cookie 経路が効くことがある。 **member 限定フォルダ (Box `/f/{folder-id}`、 login required) は無人 upload の経路が構造的に無い** (= shared-item API は `sharedNotFound` 404、 cookie replay は session API が 401)
- member 限定フォルダへの提出を自動化しようとする前に、 **cookie replay が効くか 1 回 spike** して決める: session cookie を復号 → `common/session` 等の authenticated endpoint を叩く → 401 なら cookie 経路は死んでいると確定し、 深追いしない
- 残る automation 経路は **live authenticated browser を driving する** (Claude in Chrome MCP で file input に `file_upload`) のみ。 これは semi-manual (browser を開いた状態が要る) + SPA UI 変更に脆い。 payoff (= 5 秒の drag & drop) と天秤にかけ、 大抵は **user 手動 upload を正規手順**にするのが妥当
- API 直叩きの正道は OAuth App 登録だが、 **他組織 tenant (省庁・大学の Box 等) では tenant admin 承認が要る** = 現実的でないことが多い

### 典型パターン

省庁運営の Box enterprise (member 限定 `/f/` フォルダ) への書類提出を自動化しようとした場面。 Brave の `Brave Safe Storage` 鍵で box.com cookie (`z` session ほか) を復号・replay したが、 `common/session` が **401**、 `shared-item?sharedName=…` が **404 sharedNotFound** で、 cookie 経路は認証を carry しないと確定した (= `z` は httponly session cookie だが OAuth access token を含まない)。 Claude in Chrome も未接続だったため無人経路は不在と結論し、 user 手動 upload を正規手順として維持した。 **member 限定クラウドフォルダは「cookie を取れれば自動化できる」 という直感が成立しない**ことを最初の spike で確定させるのが、 深追いで時間を溶かさない鍵。

## Multi-national service の global と local entity は別 product line

Multi-national の regulated service (証券 broker / banking / payment / SaaS の地域版等) で「Service X が feature Y を提供しているか」 を user 居住国の文脈で確認するとき、**global parent の product page と local entity の product page を別々に検証する**。entity-level で product line が大きく異なり、global の宣伝に local が含まれていない sub-feature が頻繁にある。

### How to apply

- user の居住国に割当てられる **local entity の公式 product page を first source** として検証 (例: `*.co.jp`, `*.de` 等の domain)
- global parent の product page、broker comparison サイト、第三者 review は **outdated や誤情報の risk** が高い — 採用前に local entity の公式情報で confirm
- regulated service の典型 gotcha: account 開設は居住国 entity に固定 (regulatory requirement) で、global parent や別 entity への transfer は事実上不可な場合が多い

### 典型パターン

「Interactive Brokers が cash 個別債券を提供している」 は global IB (IBKR LLC) には true だが、Japan resident が assigned される IBSJ では cash bond は提供無し (entity-level product line drop)。同様に「Saxo Bank は global で cash bond 5,200+」 は true だが Saxo Bank Securities Japan は CFD のみで cash bond 0 件。日本居住者は別 entity に switch できない (居住国固定)。global の評判で実用判断すると、routing された local entity で実機能が無く戦略が崩壊する。

---

## Filter 条件は capture と一緒に metadata に記録

UI 上の filter (通貨選択、日付範囲、商品分類等) を適用して data を取った場合、**filter の正確な scope を snapshot metadata に記録する**。後で「この項目は 0 件だった」 と読み返したとき、それが (a) filter で除外していただけ なのか (b) 実 inventory が 0 だった のかが、metadata 無しで判別できなくなる。

### How to apply

- snapshot 保存時に `filter_applied: <verbatim>` を metadata block で記録 (例: 「米ドル除く 9 通貨選択」)
- UI に複数 filter dimension があるなら全部記録する (currency / date range / type / status 等)
- partial capture (lazy-load / pagination で全部取れていない) も同様に `partial: true` + `result_count_total / result_count_captured` で明示
- 全 data が必要なら filter 解除 + export 機能で再取得を優先 (`§ロックイン済 web app からのテーブル data 取得は scrape より export を優先` 参照)

### 典型パターン

複数通貨 filter を当てて非 USD 9 通貨を取得 → 「TRY/CNY/RUB は 0 件」 と結論 → 後日全 filter 解除で取り直すと TRY 6 件 / CNY 1 件 / RUB のみ実 0 件、と判明。**「filter で除外」 と「在庫 0」 を後の自分が判別できる metadata** を残しておけば、reasoning gap に気付ける。

---

## ロックイン済 web app からのテーブル data 取得は scrape より export を優先

認証済 web UI (broker / CRM / e-commerce / analytics dashboard 等) のテーブル view から data を取得するときは、**scrape を始める前に「CSV ダウンロード」 / "Export" / "Excel" ボタンの有無を確認する**。ある場合は scrape より遥かに早く正確で、ページ実装の癖に破綻しない。

### How to apply

- 認証済 web UI でテーブル data を見ている時、ページ上に "CSVダウンロード" / "Export" / "Download CSV" / "Excel" / "ダウンロード" 等のボタンが無いか先に探す
- 見つかった場合: それを使う。ファイルとして保存され、機械可読、virtual-scroll や lazy-load の影響を受けない
- 無い場合のみ scrape (DOM 抽出 / paste 経由) に移る
- export 結果のスコープは要確認 — 多くのアプリは「現在のフィルタ」 を反映するが、一部は**全 data** を出す (= フィルタした表示より広い)。1 度ダウンロードして件数を確認するだけで判別できる
- export を見落としたまま scrape に着手すると、後から「CSV あった」 で全 work がやり直しになる。**最初の 30 秒で UI を全体スキャンしてから方針を決める** のが結果的に速い

### 典型パターン

paste-and-transcribe で rendered DOM を写す方針を取った後で問題が複合する: lazy-load で見えていない行が rendered DOM に存在しない、virtual-scroll 領域外の行は paste できない、複数 dump 間で重複・脱漏が発生する、別フィルタの dump 同士で混乱、行のセル順序がブラウザ render 設定に依存して微妙にズレる、等。CSV export は raw 値ベースで一発取得できるためこれらが構造的に発生しない。

一方、UI badge ("NEW" / "保有中" / "在庫切れ" 等) は CSV に含まれないことが多い。**badge を本当に必要とする用途**では、CSV export を canonical source にし、DOM scrape を annotation overlay として **両方取る hybrid アプローチ**を採る (CSV で 95% の事実、DOM で 5% の UI 注釈)。

**Browser MCP の制約**: Claude in Chrome MCP は安全 rule で**証券 broker / trading platform の domain を navigate level で block** する (取引執行リスク予防)。block 確認は 1 navigate で済むので時間損失は小さいが、broker UI からの抽出方針を browser-based で立てる前に試行確認する価値はある。block されたら user paste / CSV download / API access に切り替える。

---

## <a id="raw-export-snapshot-3set"></a>外部 system からの snapshot は raw export + 構造化 + script の 3 点 set

外部 web app / SaaS / API から data の point-in-time snapshot を取るとき、**(a) raw export (CSV/Excel/JSON 等) + (b) 構造化 form (YAML/parquet 等) + (c) (a) → (b) の conversion script** を 3 点 set で保存する。後で再 derive、schema 拡張、問題追跡 (transcribe error 検出等) が可能になる。

### How to apply

- 取得経路の優先順: 外部 system の export ボタン > 公開 API > DOM scrape (`§ロックイン済 web app からのテーブル data 取得は scrape より export を優先` 参照)
- 保存場所: data ディレクトリ配下、private repo なら git-crypt 暗号化下、public repo なら .gitignore 必須
- 命名: `{source}_{YYYY-MM-DD}.{ext}` (e.g., `sbi_2026-05-04.csv` + `sbi_2026-05-04.yaml`)
- conversion script は repo に保存 (raw → 構造化 を再現可能に)。script が **user-specific overlay (held flag、annotation 等) を hardcode** している場合、機密情報を持つので git-crypt 対象に追加 (`.gitattributes` で `tools/<script>.py filter=git-crypt` 指定)
- snapshot は **append-only** / 上書き禁止: rotate するならファイル名に日付を入れて新規ファイル。schema 進化に伴う migration script は別途
- 構造化 YAML には raw export の filename + 取得時刻 + filter scope を metadata block で記録

### 典型パターン

manual transcribe で snapshot を作る方針は (a) transcription error、(b) partial capture (途中で疲れる、scroll-load 限界)、(c) 後から re-derive 不能 のいずれかで失敗する。raw export を保存しておけば script の bug 修正後に再 derive で済み、transcribe やり直しが要らない。逆に conversion script を repo に置かずに「一度きりの ad-hoc 変換」 で済ませると、schema が drift した後に「以前どう変換したか」 が grep 不能になる。

### 関連
- snapshot ディレクトリ構造の例: `<repo>/data/<source>_inventory/{source}_{date}.csv` (raw) + `.yaml` (構造化) + `<repo>/tools/{source}_csv_to_yaml.py` (conversion)

---

## 学術論文 PDF の WebFetch 限界と迂回路

学術文献の URL を素朴に WebFetch する典型失敗パターンと迂回路。

| ソース | 挙動 | 迂回路 |
|---|---|---|
| 古い scan PDF（例: 日本気象学会「天気」 1990 年代以前、CCITT FAX 圧縮の bitmap） | 本文テキスト抽出不可（画像 PDF） | CiNii / AGU 等の abstract page、後継論文の citation 中の要約 |
| Wiley Online Library / ResearchGate / Elsevier | 403 Forbidden | arXiv preprint、著者個人ページ、ADS abstract |
| <a id="ads-human-verification"></a>ADS (`ui.adsabs.harvard.edu/abs/...`) | curl には「Human Verification」 の頁 (AWS WAF の確認の script) を返し、 WebFetch には HTTP 405 を返すことがある (実測)。 `adsabs.harvard.edu/full/...` も通らなかった | 確認の頁を通す操作はしない。 物理なら INSPIRE の record (`inspirehep.net/api/literature?q=…`)、 他は ADS の API (token が要る) か OpenAlex・Crossref。 学会の講演要旨 (BAAS など) で ADS にしか無いものは「未確認 (取得先が機械の読み取りを断る)」 と書く |
| arXiv (`arxiv.org/abs/...`) | フルテキスト OK | 物理・数学・CS 系の第一選択 |
| CiNii (`ci.nii.ac.jp/naid/...`) | 旧 `naid` URL は `cir.nii.ac.jp/crid/...` に 301 redirect | redirect 先で再 WebFetch |
| arXiv **PDF** (`arxiv.org/pdf/<id>`) | WebFetch は PDF stream を summarizer に渡し「binary で読めない」 と返す (abs page は OK)。 取得物は harness の tool-results dir に落ちる (= sealed review では deny path) | `curl -sL -o x.pdf https://arxiv.org/pdf/<id> && pdftotext -layout x.pdf x.txt` を作業 dir で、 `grep -n` で該当箇所を引く (2026-09 実測: 7 本 + 41 pp まで問題なし) |
| TLS 証明書の切れた data release site (例: 実験 collaboration の release page) | WebFetch: `certificate has expired` | `curl -skL` (http 経路) で取得し file 名と hash を記録。 中身は公開 data product なので改竄 risk は低いが、 hash を review の note に残す |
| <a id="paper-pdf-routes"></a>OA の出版版 (Springer・OUP の誌面、 PoS の会議録) を curl で | 出版社のサイトが PDF でなく HTML (bot 検査の頁) を返す | INSPIRE の record が出版社の PDF を保管していることがある = `https://inspirehep.net/api/literature/<recid>?fields=documents.url` の URL を curl (`fields=documents` だけでは空が返った record がある、 実測)。 引く論文の一覧と一緒に出す道具 = `ai-collaboration/scripts/inspire-bibliography.py citing` |
| 学位論文 (機関リポジトリ、 国の URN resolver 経由) | curl は 403、 内蔵 Browser pane は「セキュリティ検証」 の頁で止まる。 OpenAlex・Semantic Scholar に本体が無いことがある | 検証の頁を通す操作はしない。 先に INSPIRE の `documents.url` を見る (学位論文の PDF を保管していた、 実測)。 無ければ人に普通のブラウザで 1 回保存してもらい、 それまでは「未確認 (取得先が機械の読み取りを断る)」 と書く |
| <a id="large-scan-pdf-few-pages"></a>数十 MB のスキャンの報告書 (OCR の文字層つき) から数頁の表だけを読む | WebFetch は大きな PDF を要約に渡せず、 OCR の文字層は表の桁と数字が崩れる | 内蔵 Browser pane で PDF と同じ origin の頁を開き (検証の頁で止まる取得先には使わない = 上の行)、 `javascript_tool` で pdf.js (cdnjs の ES module) を読み込んで `getDocument({url, disableAutoFetch: true, disableStream: true})` で開く = 範囲の要求で要る頁だけが来る (file を落とさない)。 文字層 (`getTextContent`) は表の頁を探すのにだけ使い、 表は頁を canvas に描いて画面の写しで読む (OCR の数字をそのまま写さない)。 記録には印字の頁番号を書く (PDF の頁との差を目次で 1 回決める)。 実測 |

### How to apply

- arXiv ID があれば arXiv → なければ INSPIRE・OpenAlex の要旨 (ADS の頁は上の行のとおり機械に読ませないことがある) → 後継論文の citation 経由、の順で確認する
- 古い和文論文は本文 PDF が画像形式なら諦めて、引用している後継論文の本文中要約を信用する
- 商用 publisher の paywall ページは内容が取れないので時間を浪費しない
- ⚠️ **`pdftotext -layout` は 2 段組の論文で左右の段を同じ行に混ぜる**。物理・数学の論文 (REVTeX 等) の
  本文を読むなら **`-layout` を付けない** (= 段ごとに読み順で出る)。`-layout` が要るのは表・調書・帳票など
  **1 段組で桁位置に意味がある** PDF。実測 (2026-09、41 pp の 2 段組 preprint): `-layout` 版は脚注と本文が
  交互に並んで grep の前後関係が信用できず、無指定版で読み直した。1 本の PDF から両方作って使い分けてよい
  (`pdftotext -layout x.pdf x-layout.txt; pdftotext x.pdf x-flow.txt`)。
- 長い `grep` の出力は harness が tool-results dir に退避することがある (= 封じた review では読めない path)。
  文献照合の grep は `| head -40` で切って本文に残す。

### <a id="dead-society-pdf"></a>学会サイトの記事 PDF がリンク切れのとき (和文の学会誌・会誌)

学会誌の記事を探すと、 学会サイトのバックナンバー一覧に本文 PDF への link があるのに、 開くと 404 のことがある。 調べる順と、 入手の経路:

1. **書誌を確かめる**: CiNii Research の OpenSearch (`https://cir.nii.ac.jp/opensearch/all?q=<題> <著者>&format=json`、 app ID なしで引けた) で巻・号・頁を取る。 researchmap の業績欄は号を書いていないことがある = 号は学会の目次 PDF で決める。 researchmap の「MISC」 は査読つき原著でなく解説・総説の欄
2. **学会サイトの一覧から link を取る**: 古い学会サイトは Shift_JIS が多く、 そのまま grep すると文字化けで当たらない = `iconv -f CP932 -t UTF-8` を通してから。 404 なら**同じ号の他の記事も試す** (号の単位でサーバーから抜けていることがある、 実測)
3. **Web アーカイブを domain ごと引く**: `http://web.archive.org/cdx/search/cdx?url=<domain>/&matchType=domain&filter=original:.*<file 名>.*&output=txt&fl=timestamp,original,statuscode` は、 サイトの引っ越し前の path (別 dir) の保存も拾う。 `wayback/available?url=` は path の完全一致しか見ないので、 これだけで「保存なし」 と言わない。 status 列で、 いつから 404 かも分かる
4. **NDL サーチの書誌は所蔵の証拠にならないことがある**: `R100000136-` で始まる record は id の後半が CiNii Research の crid と同じ = CiNii の書誌の写し (実測)。 国会図書館がその雑誌を持っているかは別に確かめる
5. **入手の経路** (どれも本人か、 頼まれた人が出す): ① 学会事務局にリンク切れを知らせる ② 図書館の文献複写 ③ 著者に PDF を頼む。 ⚠️ 学会サイトの「メーリングリスト」 の address は会員全員に届く = 問い合わせ先にしない。 事務局の address は入会案内・事務局の頁にあり、 JavaScript で組み立てられていて HTML を grep しても出ないことがある (`document.write` で名前と domain をつなぐ形 = script の中の 2 つの文字列を読む、 実測)

---

## <a id="literature-search-apis"></a>先行研究を API で探す (OpenAlex・Crossref・arXiv・INSPIRE・CiNii・J-STAGE) — 不在は範囲つきで書く

「この問いを扱った研究は無い」 は、 引いた DB・クエリ・件数を添えたときだけ書ける。 道具 = [`../scripts/lit-search.py`](../scripts/lit-search.py) (DOI ごとの書誌の照合は [`../scripts/check-doi-list.py`](../scripts/check-doi-list.py))。

- **Google Scholar は使わない**: CAPTCHA・ボット検出を回避して叩かない。 被引用の追跡は OpenAlex の `filter=cites:<W id>` で代え、 Scholar にしか無い被引用 (書籍・学位論文・会議録の一部) は範囲外と書く
- **OpenAlex の 2 つの検索は別物**: `search=<語>` は全文の関連度検索で雑音が多い。 `filter=title_and_abstract.search:<論理式>` は引用符・AND/OR が効き、 題名と要旨だけを見る。 ⚠️ **両方を同じ URL に付けると、 両方に当たる件だけが残り、 件数が小さく出る** (実測 = 論理式のつもりで検索語の欄に仮の 1 字を入れて起きた)
- 要旨は `abstract_inverted_index` ({語: [位置]}) で返る = 位置の順に並べ直す。 持っていない文献もある (購読誌の一部)
- <a id="newest-measurement-search"></a>**新しい測定を探すときは題名の検索で止めない**: 題名に目当ての語が無い論文 (実験名だけの題、 proceedings) は INSPIRE の題名検索 (`t …`) に出ない。 arXiv の要旨の検索を提出日の新しい順で足す (`lit-search.py arxiv 'cat:… AND abs:"…"' --newest`)。 書き方が割れる語 (記号と言葉) は式を分ける。 総説の定期の版と、 集計する group の版ごとの page も別に見る (実測: 題名の検索が落とした測定を要旨の検索が拾い、 新しい版の page は入口の一覧に載っていなかった)
- <a id="inspire-all-then-filter"></a>**語を組んだ式の 0 件を信じず、 1 語の全件を手元で絞る**: 要旨の語を `and` で組む式は語形 (単数・複数・ハイフン) で 0 件になりやすい。 被引用と 1 語の検索の全件を要旨つきで取り、 手元で絞る = `lit-search.py --json inspire '<式>' --all --abstract` (実測: 組んだ式の 0 件の中に、 1 語の全件の絞り込みで拾えた論文があった)
- <a id="pdg-listing-route"></a>**PDG の listing (粒子の寿命・幅の文献値)**: `https://pdg.lbl.gov/<年>/listings/rpp<年>-list-<名>.pdf` (`K-zero-S`、 `K-zero-L`、 `B-zero`、 `Bs-zero`、 `D-zero` など)。 名前を外すと PDF でなく HTML が返る = 先頭の `%PDF` を確かめる (実測)
- **INSPIRE (高エネルギー物理)**: 全文検索 `fulltext:"…"` は INSPIRE が全文を持つ論文 (主に arXiv) だけを見る = 範囲にそう書く。 要旨の句は `abstracts.value:"…"` で引け、 `and` で組める (`abstract:` の形は 0 件を返すことがある、 実測)。 被引用 `refersto:recid:<recid>` で集めて題・要旨で絞ると、 範囲を数で書ける。 ⚠️ 複合の式の罠 2 つ (`arxiv:<id>` は他の条件と AND にならない / `de > 年` はその年を含まない) と書き方の正本 = [`ai-collaboration/scripts/inspire-bibliography.py`](../../ai-collaboration/scripts/inspire-bibliography.py) 冒頭の「API のこつ」。 陽性対照の式にも意味の無い語の foil を当て、 0 件になるのを先に見る
- <a id="inspire-record-to-bib"></a>**INSPIRE の record を書誌 (bib・文献台帳) に写すときの罠 3 つ** (実測): (1) `titles` の先頭は出版社の題で、 出版社 (APS・Elsevier など) の record では数式が MathML の tag のまま入っている (例 = `… <math><mi>N</mi></math> …`)。 同じ record の arXiv 由来の題は語まで違うことがある = 差し替えず、 出版社の題の MathML を TeX (`$…$`) に写す (2) `publication_info` に記事番号 (`artid`) と頁 (`page_start` / `page_end`) の両方を持つ record があり、 頁で引く誌でも記事番号らしい値が付いている = 誌の引き方に合わせて選ぶ (頁で引く誌は頁、 記事番号で引く誌は `artid`)。 Crossref の記事番号も誌によって内部の id を返す (下の Crossref の項) = 1 つの源で決めず、 2 つの源の一致か誌面の印字で決める (3) 写した `inspire_id` (recid) が別の論文を指したまま残っていることがある = recid を直引きして texkey・DOI・arXiv と一致するかを見て、 外れたら entry の DOI・arXiv から逆引きした値にする。 bib を照合する道具 = [`../scripts/inspire-bib-audit.py`](../scripts/inspire-bib-audit.py) (題の MathML の tag は外してから比べる)
- **対照の式が期待と違ったら、 条件を 1 つずつ外して原因を決める**: 2 つの条件を組んだ式の結果から、 片方の不具合を結論しない (実測: 論文の id の条件が他の条件と組めない罠を、 日付の条件の不具合と読み違えた)。 片方だけを変えた式をそれぞれ回してから、 どちらが効いていないかを書く
- **候補を「新しく見つけた」 と書く前に、 その project の記録 (note・計画・文献の bib・前の検索の記録) を候補の名で引く** (実測: 前の記録が既に扱っていた系統を新顔と書きかけ、 commit の後の点検で直した)。 外の検索の null から不在を言う前に内の記録を引くのと同じ点検の、 逆向き
- <a id="not-published-claim"></a>**「その program・方式は公表されていない」「その資料は有料で読めない」 と書く前に 3 か所を引く**: (1) その program で図を作った論文の本文 (方法・技術の節に方式の一部が載っていることが多い。 program の頁が「公開していない」 と言うのは code のことで、 方式のことではない) (2) 著者の他の著作 (INSPIRE の `a <著者名>` で全件の題を見て、 可視化・実装の題を開く。 学会の講演要旨も数に入れる) (3) 論文が有料でも、 配布物 (program・表・source) は著者の機関の頁で無料のことがある = 「配布物も有料」 と書く前に配布の頁を探す (実測: 別の検査が配布物を有料と書いて未確認にしていたが、 配布の頁で source と表が無料で取れ、 判定が付いた)。 書くときは、 公開されていないもの (program) と公表されている部分 (方式の何が、 どの論文のどの節に) を分ける
- <a id="software-prior-art-survey"></a>**「その種類の program はほかに無い」「〜するのは X だけ」 と書く前に、 論文に載らない公開の program も引く** (実測: 論文の program だけを見て「だけ」 と判定したが、 公開の code に同じことをする program があった)。 (1) 探す: GitHub の repository 検索を語ごとに分けて星の多い順に引く (`gh api -X GET search/repositories -f q='<語> in:name,description' -f sort=stars`。 名前と説明だけを引く = 全文から引くと、 分野の普通の語は無関係の repo で埋まる)。 製品 (教育・プラネタリウムの software、 game) は公式の説明と利用者の forum で (2) 確かめる: README・説明の文でなく source の行で決める (camera・観測者が入れる範囲の下限、 止める条件、 座標系、 物理の式を使っているか)。 説明に「できる」 とあっても画面の効果だけのことがあり、 説明に何も無くても source が扱っていることがある (実測で両方)。 作者が「物理的に正確でない」 と書く program は、 その言葉と一緒に表に入れて数に入れない (3) 版を固定する: 根拠の行は commit と一緒に書く (`git ls-remote <url> HEAD` は API の回数を使わない)。 code は保存せず commit で指す (4) API の上限: GitHub の code 検索 (`search/code`) は 1 分あたりの回数が小さく、 数 repo で止まる (実測)。 止まったら `git clone --depth 1 --filter=blob:limit=2m` で手元に取って grep で読む (実行しない)。 arXiv の API も続けて引くと「Rate exceeded」 を返す = OpenAlex で代える (5) 書く: 検索式・日付・見た件数と、 見ていない系統 (作品の投稿 site、 機械の読み取りを断る forum) を表の外に並べ、 本文の主張は見た範囲で言える形にする
- **論文の PDF の本文を語で引くとき**: text にしたら NFKC で合字 (`ﬁ` `ﬂ`) を畳んでから当てる。 行ごとに当てるなら、 行をまたぐ句は当たらない = 1 行に収まる部分で引く (実測: 頁にある句が 0 件と出た)。 0 件を「本文に無い」 と書く前に、 この 2 つを外して確かめる。 <a id="pdf-text-nul-grep"></a>⚠️ **text に NUL が混ざると grep が黙って 0 件を返す**: Bash tool の `grep` は NUL を含む file を binary と見て、 `-c` でも何も出さず終了値 1 で終わる (実測: 40 KB の text に NUL が 2 個あるだけで、 17 回出る語が 0 件に見えた)。 text にする時に NUL を除くか `grep -a` で引き、 必ず当たるはずの語 (著者名) で対照を取ってから 0 件を読む
- **Semantic Scholar は鍵なしの利用ですぐ HTTP 429** (実測)。 打ち直しを連打しない = 検索ログに「使えなかった」 と書く
- **Crossref の `query.bibliographic` の total-results は関連度の母集団** (数百万件になる) = ヒット数として書かない。 上位だけを見る
- **Crossref の `issued` は最初の公開 (online-first) の年** = 巻の年と 1 違うことがある。 書誌の照合は年の差 1 までを一致と数え、 entry には巻の年を書く。 記事番号 (`page` / `article-number`) は誌によって内部の id や `n/a` を返す = 推測で埋めず空欄にする
- 出版社の PDF (Wiley/AGU の `pdfdirect`、 AMS の `downloadpdf`、 MDPI) は curl に 403 か空の応答を返す (ボット検出、 実測)。 迂回しない = arXiv・機関リポジトリの OA 版 (OpenAlex の `best_oa_location`、 arXiv API の題名・著者の検索) を探し、 無ければ要旨止まりと記録する
- **日本語の文献**: CiNii Research の OpenSearch (`cir.nii.ac.jp/opensearch/articles?q=…&format=json`、 app ID なし) と J-STAGE WebAPI (`api.jstage.jst.go.jp/searchapi/do?service=3&text=…`、 Atom の XML)。 J-STAGE に載らない学会誌 (学会の頁に PDF を置く誌) は J-STAGE の検索では出ない = CiNii も引く
- **lookup の code を自分で書くなら**: 誤り応答 (4xx/5xx) を cache に残さない (残すと次の試行が cache の誤りを読み、 引き直したつもりで同じ失敗を見続ける、 実測)
- **検索ログに残すもの**: 日付・DB・クエリ (そのまま)・API の総数・見た件数 (上位何件か、 題名の語で絞ったか)・採用した件数。 見た件数と総数を分ける = 総数を全部見たとは書かない。 被引用の多い起点から追うときは、 起点ごとに見た件数を書く (上位 N 件で切ったなら残りの件数も)

---

## <a id="cinii-library-holdings"></a>ある図書館が本を持っているかを調べる (= CiNii Books OpenSearch の参加組織フィルタ)

大学図書館に購入を依頼する前などに、 その図書館が既に持っているか (複本になるか) を確かめる経路。 図書館ごとの OPAC 画面を開かずに、 API で引ける。

- **API**: `https://ci.nii.ac.jp/books/opensearch/search?q=<書名など>&format=json` に、 参加組織コード `fano=<その図書館のコード>` を足すと、 その図書館の所蔵だけに絞れる (app ID なしで引けた、 実測)。 件数は `@graph[0]["opensearch:totalResults"]`、 書誌は `items`。 フィルタなしの件数と比べると、 絞れているかを 1 回で確かめられる。
- **参加組織コード**: CiNii Books の図書館ページ (`ci.nii.ac.jp/library/<コード>`) の URL にある。 一度調べたら、 その図書館を使う側の非公開の記録に置く。
- **判断は OPAC で確かめる**: CiNii の所蔵は各図書館の登録を集めたもので、 登録の遅れや、 別の版・別の巻の扱いの違いがある。 「持っていない」 と結論する前に、 その図書館の OPAC で書名と版を確かめる。 電子書籍の所蔵は CiNii に出ないことがある。 実測では、 CiNii で「その館に無い」 と出た本のかなりの部分が OPAC にあった (CiNii に載っていない紙の本、 電子書籍、 ISBN の無い古い登録の 3 通り)。 ∴ 参加組織フィルタは候補を絞る下調べで、 所蔵なしの結論には使わない。 OPAC は ISBN と書名の両方で引く (古い登録は ISBN で当たらない)。
- **道具と、 購入依頼までの手順**: [`scripts/book-lookup.py`](../scripts/book-lookup.py) (`bib` / `held` / `opac` / `price`) と [book-purchase-lookup.md](book-purchase-lookup.md) (書誌 → 所蔵 → 価格と入手 → 品切れ本 → 申込メール)。

## <a id="chrome-domain-permission-model"></a>Claude in Chrome MCP の domain permission モデル

Claude in Chrome 拡張 (Chrome / Brave / 他 Chromium で動く Anthropic 公式拡張、 `mcp__Claude_in_Chrome__*` の MCP tools を提供) は **2 層の permission モデル** で動く。 設定間違いと混同しやすいので構造を理解しておく。

### 2 層の独立した permission

| 層 | 何 | 設定場所 |
|---|---|---|
| **(1) Chrome 標準の host_permissions** | content-script injection、 user-driven 操作時のページ読取 | `chrome://extensions/?id=<extId>` の「サイトへのアクセス」 (= 「すべてのサイト」 / 「特定のサイト」) |
| **(2) Claude in Chrome 独自の AI-driven domain allow-list** | MCP 経由で Claude が programmatic に navigate / click / type する場合の per-domain 許可 | 拡張の sidepanel 内 prompt (= **「Permission required」 dialog**) で domain 単位に Always allow / one-time / Decline を選択 |

**重要**: (1) を「すべてのサイト」 にしても (2) は domain ごとに別途許可が必要。 これは AI-driven 自動操作を user 確認下に置く意図的な安全機構。

### 期待される UX

MCP の `navigate` (or `left_click` / `type` 等) が未許可 domain に対して呼ばれると:
1. backend は `permission_required: <domain>` を return
2. **拡張の sidepanel に「Permission required: <domain>」 prompt が出る** (3 択: 「Allow this action」 / 「Always allow actions on this site」 / 「Decline」)
3. user が「Always allow actions on this site」 を選べば該当 domain が allow-list に追加 → 以降の MCP 経由操作は permission check pass

### 既知バグ: prompt が render されないことがある (= 詰む)

backend が `permission_required` を return しても、 **sidepanel の prompt UI が render されない** 既知バグがある ([GitHub claude-code #53630](https://github.com/anthropics/claude-code/issues/53630), [#57219](https://github.com/anthropics/claude-code/issues/57219))。 この状態だと user は「Always allow actions on this site」 を click する手段がなく、 MCP 操作が完全に詰む (= silent block)。

公式の「reset allowlist」 UI は無く、 報告されている workaround:
- 拡張を一度削除 → Chrome Web Store から再インストール (= storage clear)
- profile を変える / Chrome / Brave / Chromium を切り替える
- バグ報告 (上記 GitHub issue にコメントで repro 情報を添える)

### prompt すら出ずに拒否される domain がある (= 拡張では詰み、 Browser pane に切替)

`navigate` が **"Navigation to this domain is not allowed"** を即返し、 sidepanel に Permission required dialog が出ない domain がある
(実測: 科研費電子申請システムの本体 `www-kaken.jsps.go.jp`。 トップの `www-shinsei.jsps.go.jp` は prompt が出て通る)。
拡張の設定でサイト許可を足す経路もあるが、 **Claude Code 内蔵の Browser pane は別 surface で allow-list も別** なので、 そちらで通るなら
切替が最短 (login は pane を表示して user が打つ)。 frameset / popup 型の古い web app は pane + JS の方が扱いやすい
([#browser-pane-frameset-popups](#browser-pane-frameset-popups))。

### MCP tab group は user の手動タブと別

Claude in Chrome MCP は **自分専用の tab group** で動く。 user が手動で開いたタブと MCP が操作するタブは別管理:
- `tabs_context_mcp` は MCP の tab group 内のタブだけを返す (user の他タブは見えない)
- 「user が既にログイン済の sg-l タブ」 のような既存セッションを MCP から直接操作することは不可
- MCP は `tabs_create_mcp` で自分の tab group 内に新規タブを開いて navigate する

これは tab group ごとに permission state が独立する設計の帰結。 user が手動でタブを操作している間に MCP が裏で別ドメインに勝手に navigate するのを防ぐ。

### <a id="javascript-tool-gotchas"></a>`javascript_tool` の gotcha (実測)

- **async IIFE の戻りは `{}` に潰れる**: `(async () => {...})()` を最後の式に置くと Promise が serialize されて `{}` が返る。 top-level `await` が使えるので `await (async () => {...})()` で結果の文字列/JSON を最後の式にする。
- **出力 filter**: tool 結果に cookie / query string に見える文字列 (`=` `&` `;` を含む urlencoded 風の並び、 HTML の `href` 群など) が含まれると結果全体が `[BLOCKED: Cookie/query string data]` に置換される。 DOM を調べる時は `outerHTML` を返さず、 属性名・テキスト・長さだけを組み立てて返す (記号は `->` `|` `:` 等に置換)。 body を捕捉した時も同じ。 画面の文字 (店名・件名) を返すときは記号の置換では足りず、 返す文字を **whitelist で絞る** (かな・漢字・英数字と少数の記号だけ残して他は `_`)。 同じ処理でも、 行の中身次第で一部の回だけ伏せられる (実測)。
- **戻り値は約 3KB で切れる** (末尾に `[TRUNCATED]`): 長い結果は件数を減らして分けて呼ぶか、 localhost の受信 server に POST して file で受ける。 一覧を月ごと・ページごとに回す処理は、 1 回の返り値に収まる範囲で区切る ([`machine-route-first.md #page-widget-walk`](machine-route-first.md#page-widget-walk))。
- **「公開 API が無い web app」 の機械経路**: ログイン済みページの page context から、 UI が叩いている内部 endpoint を同じ method / encoding / header で `fetch` する (= XHR を一時 hook して実 UI 操作 1 回分を捕捉すれば method・field 名が全部分かる。 method 違い〔POST vs PUT〕・encoding 違い〔multipart vs urlencoded〕で 404 になるので推測で組まない)。 GUI click の自動化より速く・行数に依らず・座標に依らない。 recipe 全文 = [`machine-route-first.md #internal-endpoint-replay`](machine-route-first.md#internal-endpoint-replay)。

### 公式ドキュメント

- [Claude in Chrome Permissions Guide](https://support.claude.com/en/articles/12902446-claude-in-chrome-permissions-guide) (= 公式 permission モデル説明)
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions) (= MCP tool permission の上位概念)

### How to apply

- `permission_required: <domain>` を踏んだら、 まず sidepanel を user に見てもらい prompt の有無を確認 (= 既知バグかどうかの切り分け)
- prompt があれば「Always allow actions on this site」 を user に click してもらう
- prompt がなければ、 **再インストールの前に `list_connected_browsers` を見る** (2026-09-05 実測): 拡張のアカウント再ログイン / 再接続の後は**旧接続と新接続が 2 本並び、 session は旧接続を掴んだまま**になる。 この状態では navigate だけ通り、 read / screenshot / click が全部 `Permission denied for this action on this domain` になり、 Claude が開いたタブは user のブラウザに見えず、 prompt も (旧接続側に飛ぶので) 出ない = 「render バグ」 と区別がつかない。 `connectedAt` が最新の browser を `select_browser` すると新 tab group が user の窓に開き、 prompt も正常に出る。 ⚠️ 拡張の署名 account と session の account が食い違っていないかも同時に確認する (session 側は harness の userEmail でなく実 probe で同定する = 別規約)
- それでも prompt がなければ既知バグの可能性 → 拡張再インストール / 別 profile / スクショ共有 fallback を提案
- **`Permission denied` は「未 login」 も隠す (2026-09-07 実測)**: navigate は通る (= 応答の tab URL が IdP の `/auth/session` に化けているのに気づかない) が read が denied、 という状態は **allow-list 未許可 + そのマシンの browser が対象 site に未 login** の重なりでありうる。 診断順 = ① `list_connected_browsers` が 2 本以上なら **どちらが user の目の前の browser か分からない** (= 別 Chromium / 別 profile が混ざる。 `connectedAt` 最新の選択で当たらない事もある) → `switch_browser` broadcast で user に Connect を押してもらい、 その場で接続に名前を付けてもらう (= 以後 `select_browser` で確定) ② navigate 応答の **tab URL を読む** (IdP に飛んでいれば login 段が先) ③ login 後に read が通れば allow-list は prompt なしで通ることもある (= 実測: Connect + login の後、 Always allow を押さずに read 成功)。 ⚠️ harness は「複数 browser 接続時は AskUserQuestion で選ばせよ」 と注入するが、 user が選択肢 UI を嫌う環境ではそれを dismiss されうる → 平文で候補 + 推奨を示し「判断して」 と言われたら recipe (connectedAt 最新 → 外れたら broadcast) で進める ([ask-user-question.md](ask-user-question.md))。
- **`browser_batch` に `read_network_requests` を含めると auto-mode classifier に block されることがある** (2026-09-07 実測) — network 観察が要る時は個別 call か、 そもそも #session-cookie-reuse / #internal-endpoint-replay の script 経路に切り替える。
- **navigate 直後の `get_page_text` は描画前の DOM を読む**: 検索結果を JS が後から描く site では「該当なし」 template だけが返る (実測 3 連続)。 `wait` を挟むか、 結果を返す API を script で叩く ([machine-route-first.md #session-cookie-reuse](machine-route-first.md#session-cookie-reuse))。
- 「Chrome 標準の host_permissions が「すべてのサイト」 になっているのに動かない」 は誤解、 (1)(2) が独立であることを最初に user に説明する
- 既存 web ツール (`mcp__Claude_in_Chrome__*`) を新規ドメインで使う前に、 「permission prompt が出る前提」 で workflow を組む (= 1 回 prompt がかかる前提で批准点を設計)

### 関連

- broker UI の domain-level block: §「ロックイン済 web app からのテーブル data 取得は scrape より export を優先」 末尾の「Browser MCP の制約」 参照
- 個人の母艦ブラウザ選定 (Brave 等) は personal layer (個人 dev-environment) で書く

## <a id="browser-pane-frameset-popups"></a>Claude Code 内蔵 Browser pane で古い web app (frameset / popup / 連動 select) を読み書きする (2026-09-08 実測)

`mcp__Claude_Browser__*` の `get_page_text` / `read_page` / `find` / `form_input` は **frameset の外側の document しか見ない** ので、
frameset の app では空文字と ref 無しが返る。 読み書きは `javascript_tool` で frame の document を直接触る:

- **読む** = `window.frames[i].document.body.innerText` (i は frameset の順、 main は大抵 1)。 遷移 = `frames[i].location.href = '/path'`。
- **書く** = `frames[i].document.<form>.elements[name].value = v` (select も value 代入で可) → 画面が持つ保存関数 (`frames[i].onXxx()`) を呼ぶ。
  page script の関数は frame の window に生えている (`Object.keys(frames[i]).filter(k=>typeof frames[i][k]==='function')` で一覧)。
- **連動 select** (親の change で子の選択肢が入る) は `e.dispatchEvent(new frames[i].Event('change',{bubbles:true}))` — **Event は frame の window のもの**を使う。
- **popup** (`window.open('',name)` + hidden form `target=name` で開く画面) は pane で潰れて権限エラー等の副作用が出る →
  同じ form を **`target='_self'` にして submit** すれば同 frame に出る (権限エラーは popup 不成立の副作用で、 データ権限の問題ではない)。
- <a id="browser-pane-popup-fetch"></a>**page が開いた popup (`window.open(url)`) は agent が読めない・閉じられない**。 開いている間は他の tab の JS も止まる (閉じるのは本人)。
  中身が普通の GET の画面なら、 popup を開かずに **opener の tab から `fetch(url,{credentials:'include'})` → `TextDecoder(<page の charset>)` → `DOMParser`** で読む
  (同じ origin なので login の cookie が付く。 使うのは読むだけの GET だけ)。 値が `input` の `value` に入っている画面 (業務 app の伝票・申請書) は `innerText` に出ないので、
  `name` で拾う。 url は opener の `onclick` / frame の `location.href` から取る (frameset の中に読み込まれていることもある = 上の frame の読み方で先に探す) (実測)
- <a id="browser-pane-form-post-list"></a>**別窓に見えるボタンが、 実は frame への form の POST のことがある** — 「一覧」「明細」 を開くボタン (画像の `input`) の `onclick` を先に読む。
  `form.action='…'; form.submit()` の形なら、 その form の `FormData` を同じ action に `fetch` で POST し、 返る frameset の `<FRAME src>` を続けて `fetch` すれば、 別窓も画面遷移も起こさずに一覧が読める。
  server が POST で「どの行を選んだか」 を session に覚える作りなら、 POST → 一覧の GET を 1 対ずつ順に回す (並列にしない) (実測)。 「popup だから読めない」 と結論する前に onclick を見る。
- <a id="browser-pane-script-computed-values"></a>**一覧の金額が、 HTML では 0 で、 page の script が足して表示する作りがある** — fetch した HTML には 0 しか無い (画面には額が出る)。
  page の script の足し算 (例: `el.innerHTML = Number(el.innerHTML) + N`) を、 要素の id ごとに拾って再現する。 古い app は旧版の行をコメントアウトで並べて残しているので、 `//` で始まる行を除いてから拾う (除かないと 2 重に足す)。
  再現した額の合計を、 画面の別の場所の合計 (残高の表の執行額など) と突き合わせ、 一致したものだけを記録する (実測 = 一致で拾い漏れと 2 重拾いを止められた)。
- <a id="js-result-to-file-hash"></a>**`javascript_tool` の戻り値を file に写すときは hash で照合する** — 戻り値の文字列を自分で file に書き直すのは転記であって複写ではない (写し間違いが混じりうる)。
  browser 側で `crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))` を出し、 写した file の SHA-256 と照合してから使う。 取り込む道具に `--sha256` を渡して照合を道具にさせる形にすると、 照合を飛ばせない (実測)。
- **lockButton + setTimeout 型の submit** (古い業務 app に多い) は、 関数を呼んだ後 **3〜4 秒待ってから次の JS**。 連続呼びは 2 回目以降が捨てられる。
  行追加・再計算がサーバ往復なら 1 回ごとに待つ。
- **file input は JS から置けない** (CSV 取込 / 添付 upload) → 人間の 1 操作。 行追加 + 代入で代替できるなら AI 側で済ませる。
- **認証情報は user が pane を表示して打つ** (Claude は打たない)。 pane が hidden だと user は打てないので「表示して」 と頼む。
- **合成 click は page の copy handler を発火させて OS clipboard を書き換える**ことがある (pane が警告する) — 読みは innerText、 遷移は location / 関数呼びで済ませ click を減らす。
- **本番 record に試し書きしない** = 検証は sandbox (別種目の新規 draft 等) で往復 → 読み戻し → 削除まで通してから本番。

実例 (科研費電子申請システムの読み・書き経路 + driver 設計) = [kakenhi-proposal.md#ai-read-route](kakenhi-proposal.md#ai-read-route) / [#ai-write-route](kakenhi-proposal.md#ai-write-route)。

## <a id="browser-pane-local-file-snapshot"></a>内蔵 Browser pane で project folder の外の `file://` を開くと、 静的な snapshot になり page tool が使えない

生成した HTML を目で確かめたいとき、 scratchpad など作業 folder の外の file を `preview_start {url: "file:///…"}` で開くと、 表示は出るが `find` / `read_page` / `get_page_text` は「local file なので操作できない」 で拒否される (実測)。 page の中身を tool で確かめるなら:

- 作業 folder の中の、 **git が ignore する dir** に出力を書く (生成物を commit に混ぜない)
- `.claude/launch.json` にその dir を配信する静的 server (`python3 -m http.server <port> --bind 127.0.0.1 -d <dir>`) を置き、 `preview_start {name}` → `navigate` で `http://localhost:<port>/<file>` を開く (既にある設定を使えるなら足さない)
- 確かめ終わったら `preview_stop` し、 出力を消す (私的な中身の HTML を置きっぱなしにしない)

## <a id="browser-download-automation"></a>**Chrome 拡張**からの file download — 保存されないように見えたら、 保存先の確認の sheet 待ちか silent block かを見分ける

> ⚠️ **scope (2026-09-02 実測で確定)**: 本 § の silent block は **Claude in Chrome (= 拡張経由の実ブラウザ)** の話。
> **Claude Code 内蔵の Browser pane は別 surface で、 script 発火の blob download が `~/Downloads` に着地する**
> — 実測 = pane 内で `javascript_tool` から `Blob` + `<a download>.click()` を撃ち、 2 秒後に `~/Downloads/` に
> 実体 file を確認 (26 byte、 中身一致)。 ∴ **「ブラウザからは落とせない」 と一般化して下の fallback ladder に
> 逃げる前に、 内蔵 pane で試す**。 内蔵 pane の読み取り能力は [`#claude-share-page-access`](#claude-share-page-access) の比較表側 (= 完全レンダリング / `get_page_text` / `javascript_tool`)。
> ⚠️ **内蔵 pane は HTTP Basic 認証の入力欄を出さず、 401 のページを表示して止まる** (実測) = Basic 認証のサイトは拡張 (実ブラウザで本人がログイン) で読む。
> 本人が URL に ID/PW を埋めて pane で開く形は勧めない (認証情報が URL・履歴に残る)。

**現象**: browser MCP (Claude in Chrome 等) で page 内 JS から download を発火させても、 **保存が一切実行されない** — blob + `<a download>` の `.click()` も `location.assign(<content-disposition URL>)` も、 browser の download 履歴 (History DB の `downloads` table) に **record すら残らず** 無音で落ちる。 extension/CDP 経由の合成 click も user gesture 扱いにならず、 link click での download も発火しない (= 実測、 Chromium 系)。 ⚠️ record も file も無い状態は、 下の診断の「保存先の確認待ち」 と同じ見え方をする = この実測が確認の sheet の見落としでなかったかは確かめていない。 `fetch()` 自体は page 内で成功する (= bytes は取れている) が、 **base64 で tool 結果に持ち出すのは MCP 側 filter が block する** — これは data-exfiltration guard なので**回避しない** (chunk 分割等での evasion は禁止)。

**診断**: 「DL したはずが落ちてこない」 時は、 保存先 dir の監視より先に **browser の download 履歴 DB を直接読む** (= 稼働中でも DB copy → sqlite で `downloads` table)。 record が無ければ「保存先違い」 ではない。 「発火していない」 と「保存先の確認待ち」 の 2 つが残る — <a id="pending-save-sheet"></a>**保存先の確認の sheet** (macOS の保存の panel。 見出しは「<site> が次の保存を要求しています」) が答えを待っている間も、 History DB の record も保存先の file も無い (bytes は見えない一時 file に書かれ、 答えると file が現れて mtime は download を始めた時刻になる)。 sheet は browser の窓のある画面に出て tab の screenshot には写らず、 別の display に出ることもある = 「発火していない」 と決める前に全 display を `screencapture -x <file1> <file2>` で撮って見る (実測: 拡張経由の blob + `<a download>.click()` が sheet で止まっていたのを「保存されない」 と判断し、 本人が sheet の「保存」 を押すと file が出た)。 sheet のボタンは Claude からは押せない (System Events は補助アクセスの許可が要り、 拡張は native の panel に届かない) = 本人に押してもらう。 併せて download URL が**期限付き token** (`?time=...` 等の signed param) を持つ場合、 stale な page から取った URL の fetch は **200 + login page HTML** を返す (= サイズが数 KB の HTML なら token 切れ。 page を reload してから再試行)。

**How to apply** — fallback ladder (上から順に):

1. **user の手 click** (= 物理的に browser の前にいる人に依頼。 先に [`#pending-save-sheet`](#pending-save-sheet) の確認の sheet が出ていないかを見る = 出ていれば「保存」 を押してもらうだけで済む。 リモート操作中の user は click できないことに注意 — 「どの機械の browser を操作しているか」 と「user がどこにいるか」 は別物)。
2. **cloud 共有リンク経由**: user が手元マシンで DL → cloud storage の共有リンク (Dropbox folder link は `&dl=1` で zip 一括) を chat に貼ってもらい、 worker 側で `curl -L`。 zip の filename mangling は cp437 → utf-8 re-decode で復元 (= office-automation の `zip-cp932-filenames` と同じ手当)。
3. **メール添付経由**: user が自分宛に添付送信 → Gmail 系 MCP の attachment download で取得。

**典型パターン**: SSO 保護の社内 groupware (掲示板 / ファイル管理) を logged-in browser session 越しに読むのは成功するが、 file 取得だけが上記 block で落ちる — 読み (get_page_text / find) と取得 (download) は別権限帯だと思って設計する。

## <a id="browser-pane-input-quirks"></a>内蔵 Browser pane の操作の癖（キー・スクリーンショット・再読み込み）

- **`computer` の `key` で送った Enter / Return が、ページに届かないことがある**（実測: textarea に改行が入らず、
  `keydown` の記録自体が残らない）。ページ側の不具合と決める前に、`type` で改行文字 `"\n"` を送るか、
  値を入れて `input` イベントを発火させ、**値を読み戻して**確かめる
- **スクリーンショットが真っ白（灰一色）で返る**ことがある（ページ遷移・再読み込みの直後に続いた、実測）。
  待っても直らないときは、見た目の確認を `javascript_tool` / `read_page` での要素の位置・状態の読み取りに切り替える
- <a id="login-state-check"></a>**ログインしているかは、ページ上部のアカウント表示（名前・アイコン）をスクリーンショットで見て判定する**。
  ページの文字に「ログイン」 があることはログアウトの証拠にならない（施設・業者向けの管理画面リンクや、
  機能ごとの「ログインして〜」 はログイン中でも出る、実測）。推測で作った URL が 404 やトップページに落ちると、
  文字には検索フォームしか出ずログアウトに見える（実測）= 正しい入口（手順書の URL・ヘッダのメニュー）から開き直してから判定する。
  ログアウトと言う前に 1 枚撮る
- <a id="login-page-not-access-restriction"></a>**サイトを開いてログイン画面が出ても、 そのサイトが限定公開とは限らない**。
  pane に残っていたアカウント選択の画面に回されただけのことがある（実測: 「組織のアカウント限定」 と報告したサイトが、
  共有の設定では「インターネット上の誰でも」 で、 ログインなしの取得にも本文を返した）。公開範囲を言う前に、
  cookie を持たない取得（`curl -sL <URL>` の状態コードと本文）か、サイトの共有設定の画面で確かめる
- **`#` だけ違う URL への `navigate` はページを読み直さない**（古い版が表示されたまま）。作り直したページを確かめるときは
  `location.reload()` を使う
- **ロボット判定（Turnstile 等）は自動操作では通れない**（トークンが発行されない、実測）。**突破しようとしない**。
  判定を通った送信の確認は人に頼む（[`static-site-form-backend.md#turnstile`](static-site-form-backend.md#turnstile)）

## <a id="google-sites-editor"></a>Google サイト（新しい版）の編集画面を内蔵 Browser pane で操作する

Google サイトには中身を書き換える API が無く、編集は画面の操作になる（経路の順番 = [`machine-route-first.md#route-ladder`](machine-route-first.md#route-ladder) の最後の段）。実測した癖:

- **本文のテキストボックスに `computer` の `type` で入れた文字は確定しないことがある** — 入れたはずの文字が消える、
  古い文に戻る、一部だけ残る（実測）。`key` で 1 文字ずつ送ると入るが遅い。
  **リンクを挿入する窓（「テキスト」 と「リンク」 の 2 つの入力欄）は `type` をそのまま受け付ける** = 1 行の文とその URL なら、
  挿入の panel から「テキスト ボックス」 を置き、その窓で表示の文と URL を入れるのが確実。
  入れた後は `get_page_text` で本文を読み戻して確かめる（画面の見た目では消えた文字に気づきにくい）
- **ページの中身を消すときは、ページの削除より節の削除** — 各節の「セクションを削除」 の button で消すと、
  ページと URL は残る（外から張られたリンクが 404 にならない）。ページの削除は外部サイトのデータの削除として、
  本人の明示の承認がないと auto mode の分類器に止められる（実測）
- **「公開」 は 2 段** — 編集画面の「公開」 → 変更点の確認画面（左に変わったページの一覧、右に下書きと公開中の版が並ぶ）→ その画面の「公開」。
  確認画面は、変えたページの数と中身を本人に見せる面として使える。「サイトを公開しました」 の表示が出たら、
  上の [`#login-page-not-access-restriction`](#login-page-not-access-restriction) と同じく cookie を持たない取得で
  各ページの本文とリンク先を確かめる（編集画面で見た文と、公開された版が一致するかを見る）
- 編集画面の URL は `sites.google.com/d/<site id>/p/<page id>/edit` で、アカウントは `?authuser=<email>` で選ぶ（[`google-url.md`](google-url.md)）

## <a id="headless-page-screenshot"></a>相手が preview を見られないときは、ページ全体を画像に撮って送る

内蔵 Browser pane の preview はその機械の app でしか見えない（スマホから会話している相手には届かない）。
「見えない」 と言われたら、ページ全体を PNG に撮って添付で送る。道具 = [`../scripts/page-screenshot.py`](../scripts/page-screenshot.py)
（スマホ幅 = `--width 390 --mobile`、PC = `--width 1280`。`file://` の生成物も server なしで撮れる。`--selftest` あり）。

headless Chrome の `--screenshot` をそのまま使うと 3 つの罠に当たる（どれも実測）:

- **`--window-size` の幅には下限がある**: `--headless=new --window-size=390,…` はもっと広い画面で描かれ、右が切れた絵になる。
  端末の幅は DevTools の口（CDP）の `Emulation.setDeviceMetricsOverride` で指定する
- **別オリジンの iframe（埋め込みプレーヤー・ロボット判定）があるページで、書いた後に Chrome が終わらないことがある** = 自分で起動するなら打ち切りの時間を付ける
- **`captureBeyondViewport` でページ全体を撮ると、別オリジンの iframe が白く写る** = 画面の高さをページ全体に広げてから普通に撮る

送る前に:

- **縦に極端に長い画像は添付で届かないことがある**（780×12400 px は送れず、780×5000 px は届いた）= `--split <高さ>` で縦に分ける
- 撮った絵を 1 枚は自分で読む（右端の切れ・白い枠・エラー表示）。`file://` で開いたページではロボット判定の欄がエラー表示になる = 本番の不具合と取り違えない
- 開けなかったページ（file が無い等）は道具が失敗で返す（Chrome のエラー画面を撮って成功にしない）
