# Zenn.dev 記事執筆の規約

Zenn.dev (日本語技術記事プラットフォーム) に記事を書く / 既存記事を編集するときの **platform 仕様と markdown の落とし穴**。zenn-cli + GitHub 連携での運用手順 (`zenn new:article` / preview / 自動デプロイ) は各リポの CLAUDE.md (例: `zenn-articles/CLAUDE.md`) 側、dev.to へのクロスポスト変換は `devto-articles/CLAUDE.md` 側に置く — 本 file は platform の制約と GFM 執筆作法に閉じる (Substack 版の対は `substack.md`)。

## Platform 制約 (= 確認済み)

- **タイトルは 70 文字以内**。英語タイトルは 1 文字 = 1 カウントなので特に注意。
- **HTML はサニタイズされる**: `<br>` 以外の生 HTML は通らない。
- **動作する独自記法**: `:::message` (情報・グレー)、`:::message alert` (警告・赤)、`:::details タイトル` (折りたたみ)。
- **動作する標準 markdown**: `#`〜`###` 見出し、`**bold**`、`*italic*`、`---` 区切り線、`>` 引用、Mermaid 図、テーブル。
- **1 記事の上限は 50,000 字** (zenn.dev の表示文字数ベース)。

### 文字数の見積もり

`wc -m` の生値は markdown 記号・改行・frontmatter を含むため zenn 表示文字数より大きい:

- 日本語記事: `wc -m ÷ 2.7 ≈ zenn 表示字数`
- 英語記事: `wc -m ÷ 1.5 ≈ zenn 表示字数`

上限 50,000 字に対しては、日本語なら `wc -m` で約 135,000 字が目安。

## frontmatter

```yaml
---
title: "（70 字以内）"
emoji: "🔍"
type: "tech"        # または "idea"
topics: ["AI", "ChatGPT", "Claude"]   # 配列。dev.to へ出すときは tags へ変換 (devto-articles 側)
published: false    # 公開時に true
---
```

## 構造化の作法

- **情報・補足** → `:::message` で囲む。
- **結論・立場の変化・重要な注意** → `:::message alert` で囲む。
- **長すぎて畳みたい塊** (初期レポート等) → `:::details タイトル` で折りたたむ。
- **複数論点** → 太字リード文 (`**論点。** 本文…`) で区切る。
- **セクション冒頭の 1 行サマリー** → イタリック (`*…*`)。
- **`---` 区切り線** は大きな節の切れ目だけに使う (話者交代・小見出しでは使わない)。
- **`>` 引用ブロック** は他者の過去発言を引用する場面のみ (話者ラベルには使わない — 話者は `###` 見出し + 絵文字等で分ける)。

## Markdown 執筆の落とし穴 (= GFM、 zenn / dev.to 共通で再発)

- **GFM bold × 全角句読点 (= 正本は `claude-config/gfm-rules.md`)**: 閉じ `**` の直前が全角句読点で直後が CJK 文字だと GFM の right-flanking delimiter 条件が不成立で bold が壊れる (例 `（A）**が` → `（A）** が`)。delimiter ルール全体 (開き/閉じ・スペース挿入位置・`****` 禁止) は `gfm-rules.md` が正本。チャット UI や一部レンダラは GFM より寛容なので、そこで通っても zenn/GFM で壊れることがある (= 別レンダラで通った原文を貼るときは要再確認)。
- **翻訳プロンプト指示文の混入**: 翻訳時にプロンプトへ入れた指示文 (`*This text is finalized. Do not modify.*` 等) が訳出結果に残ることがある。訳後に指示文・メタコメントが混入していないか grep 確認する (特に `:::message` ブロック末尾にイタリックで残るパターン)。
- **編集・翻訳時の inline bold 落ち**: running prose 内の `**bold**` は編集・翻訳で落ちやすい。原文と編集版で running prose の bold 箇所を突合する (`:::message` ボックスやリストで代替済みの箇所は対象外)。
- **応答末尾の取りこぼし**: `:::message` ブロックの終わりと応答全体の終わりを混同しない (ブロックの外にも段落が続くことがある)。転記後はソースと記事の最終段落を突合する。

## モバイル / コピペ運用の注意

- スマホの Claude アプリ等で md を開くと **markdown 記号が消える**ことがある。コピペ投稿用の md は**テキストエディタ**で開く (= 記号を保ったままコピーする)。
