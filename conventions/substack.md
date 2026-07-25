<!-- doc-meta
when: Substack 記事の入稿・notes/コメント回収をするとき
category: web
summary: Substack 規約（入稿: Markdown→リッチテキスト変換手順 / 取得: notes・コメントの Gmail MCP + WebFetch 経由回収）
-->
# Substack 規約

本ファイルは Substack 上の「書く側」（入稿）と「読む側／集める側」（取得）の両方の運用ノウハウを記録する。

---

# 入稿

## エディタの制約

Substack のエディタはリッチテキスト（WYSIWYG）。**Markdown 記法を直接認識しない。** `## 見出し` や `**太字**` をそのまま貼るとプレーンテキストとして表示される。

## 使えるフォーマット（Substack エディタが持つ機能）

- 見出し（H1〜H6）
- **太字** / *イタリック*
- 箇条書き（番号付き / 番号なし）
- 引用ブロック
- リンク
- 脚注
- 画像（ドラッグ＆ドロップ）
- 水平線
- 埋め込み（YouTube, X, Spotify 等）

## 使えないフォーマット

- **テーブル** — サポートなし。箇条書きや見出し付きリストで代替
- **コードブロック** — GitHub Gist 埋め込みのみ（fenced code block 不可）
- **インラインコード** — 不可

## 原稿の書き方

Markdown で書いてよい（見出し・太字・箇条書き等は全て Substack の機能に対応する）。ただし:

1. **テーブルは使わない** → 箇条書きに変換
2. **内部ファイル参照は除去** → `→ concepts.md §7` のような記法は読者に意味がない
3. **コードブロックは使わない** → 必要なら Gist 埋め込み
4. **太字を全角括弧・句読点に隣接させない** → `**「…」**です` の形は GFM の flanking 規則で parse されず、md-to-substack でも `**` が literal のまま公開に露出する（実例 2026-07-25、公開後に発覚し手動修正）。閉じ `**` の直前が全角約物なら直後は空白・句読点にする、または鍵括弧だけで強調して bold を外す。一般則は `gfm-rules.md`（CJK bold × 全角句読点）。md-to-substack のプレビューで `**` が残っていないか確認するのが最終 gate

## 入稿手順

1. `drafts/` フォルダに Markdown 原稿を作成（例: `drafts/article-substack.md`）
2. [md-to-substack.netlify.app](https://md-to-substack.netlify.app/) をブラウザで開く
3. 原稿を左のテキストエリアに貼る。冒頭の HTML コメント行（`<!-- タイトル: ... -->` 等）は含めず、**本文（概要行）から末尾まで**を貼る
   - ⚠️ Claude Code の Bash から `pbcopy` でクリップボードに渡す手は使えないことがある（sandbox 解除でも user session の pasteboard に書き込めない環境を実測、2026-06-12）。原稿ファイルをエディタで開いて手動コピーが確実
4. 右のプレビューでフォーマットを確認（見出し・太字・箇条書き・リンク・水平線）
5. 「Copy for Substack」ボタンを押す → クリップボードにリッチテキストがコピーされる
6. Substack ダッシュボードの **Create → Article** で新規記事エディタを開き、本文エリアに貼り付け（Cmd+V）
7. タイトル・サブタイトルはエディタ上部の専用欄に入力（本文に H1 を含めると重複する → §タイトル管理）

## 公開フロー（エディタ → 公開）

1. プレビュー画面（Mobile / Desktop / Email 切替）から編集に戻るボタンは **Done**。Share は共有リンク用なので公開前は押さない
2. エディタ右上の **Continue** → Publish ダイアログ（Audience / コメント許可 / タグ / Delivery / Scheduling）
3. ⚠️ Delivery の「Send via email and the Substack app」は**既定で ON** = 公開と同時に全購読者へメール配信される。サイト掲載のみにしたいときはチェックを外す
4. **Send to everyone now** で公開

## タグ

- タグ名に**スペースは使えない**（例: 「Claude Code」は不可 → 「Claude」または「ClaudeCode」）
- 新規タグの Create が「Something went wrong」で失敗することがある（同一ダイアログ内で他のタグは付与できたのに特定の新規タグだけ落ちる事例: 2026-06-12、原因未特定）。1 回リトライしてだめなら**タグなしで公開してよい** — タグは公開後に Post settings からいつでも追加でき、公開のブロッカーにしない

## オプション設定（md-to-substack ツール）

- **Enable smart quotes**: ON 推奨（`"` → `""`）
- **Add extra spacing between lines**: OFF（ON にすると各行が別段落になる）
- **Auto-update preview**: ON

## ダッシュの注意

日本語ダッシュは Substack で安定しない:

- 下書きエディタでは `―`（U+2015）がきれいに見えるが、公開後は `—`（U+2014）の方が長く表示される
- どちらも 2 連にすると間が空くことがある
- **最も確実な対策はダッシュをなるべく使わず、括弧や読点で代替すること**
- どうしても使う場合は `——`（U+2014 の 2 連）

## タイトル管理

- Substack のタイトル・サブタイトルはエディタ上部の専用欄に入力（本文に H1 を含めると重複する）
- 原稿ファイルでは HTML コメントで記録: `<!-- タイトル: ... -->` `<!-- サブタイトル: ... -->`
- 概要（リード文）を本文冒頭に置く場合は、イタリック段落の頭に「概要:」と入れて水平線で区切る

## 注意事項

- 公開前に Substack のプレビュー機能でも最終確認すること
- 画像は md-to-substack では変換されない → Substack エディタで手動挿入
- Substack の Notes（短文投稿）では太字・イタリック・リンクのみ使用可能（見出し・箇条書し不可）

---

# 取得（notes / コメントの事後回収）

自分または他人が Substack に書いた note や article comment を事後に取得して Markdown 化する際の手順。研究リポで過去の発言を原文保存したい、分析の証跡として確保したい、といった用途を想定する。

## 3 つの取得経路と特性

### (1) WebFetch で note URL を直接取得

`substack.com/@{user}/note/c-{id}` 形式の URL を WebFetch すると、note 本文が **JSON 内の `body` フィールド** として埋め込まれた HTML が返ってくる。ページの visible HTML 側には本文がないため、WebFetch への prompt で「body フィールドから抽出してくれ」と明示する必要がある。note の投稿時刻（ISO timestamp）も同じ JSON から取れる。

**成功率**: 明示プロンプトなら高い。最初の試行で「ページの visible HTML には本文がない」と返してきたら、prompt を「JSON object の body / text フィールドから生テキストだけ返せ」に強化して再試行する。

### (2) Gmail 通知メール経由 — reaction 型

`reaction@mg1.substack.com` からの "X liked your comment on Y" 通知メールは、**like 対象となった自分のコメント本文を HTML 内に verbatim で引用している**。reaction 通知が1件でもあれば、そこからコメント本文を復元できる。

### (3) Gmail 通知メール経由 — forum 型（**落とし穴**）

`forum@mg1.substack.com` からの "New comment on Y" 通知メールは、**他者の新規返信本文のみ**を含み、**返信先となった自分のコメントの本文は含まない**。forum 通知から自分のコメントを復元することは**不可能**。

これは retrieval の設計上の盲点になりやすい。forum 通知は「返信がついた」という事実を知るには十分だが、本文復元には使えない。

## 実用上の含意

- **自分のコメント本文を取るには reaction 通知を探す**。Gmail 検索: `from:substack.com "your comment" after:YYYY/MM/DD` で reaction と forum の両方が出てくるので、**reaction を優先**
- reaction 通知が1件もないコメント（誰も Like していないコメント）は、Gmail 経由では取得**不能**。Substack UI から直接スクレイプするか、記憶に頼るしかない
- 同一本文のコメントが note と article comment の両方に存在することがある（ユーザーが同じテキストを複数チャネルに出すケース）。片方の取得経路で失敗しても、もう片方から取れる可能性がある
- **取得順序の推奨**: note URL が判明しているなら WebFetch を最初に試す（メール解析より速い）→ 駄目なら reaction 通知を探す → 駄目なら UI

## 通知メールの URL について

Substack 通知メール本文に含まれる記事・コメント URL は、**すべて `email.mg1.substack.com/c/...` 形式の mailgun トラッキング URL**。canonical な `substack.com/...` URL は通知メールからは直接取れない。canonical URL が必要な場合は、別途 Substack UI か reaction/forum 通知の subject 行から記事タイトルを取って検索する、等の別経路が必要。

## Gmail MCP との併用

`gmail_read_email` の出力は HTML-heavy なメールで 70〜200 KB に達し、Claude のメインコンテキスト token limit を超える。自動的にファイルに dump される挙動と、subagent 経由の chunked 処理パターンは → `mcp.md` の Gmail MCP セクション参照
