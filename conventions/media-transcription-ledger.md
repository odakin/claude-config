<!-- doc-meta
when: 定期的に届く画像 stream (板書写真・スキャン書類・写真メモ) を SoT 化する仕組みを設計するとき + 手書き画像の読取結果を記録・転記するとき
category: office
summary: 画像 stream は fetch されるだけでは SoT に入らない — transcript home + 読取 ledger + 未読 detector + 保守的自動読取 routine の 4 点セットで「読んだか不可視」問題を design-out する
-->
# Media transcription ledger (= 画像 stream の読取記録パターン)

定期的に届く画像 (= ミーティング板書の写真、 スキャンされた紙書類、 ホワイトボード・付箋の写真メモ) は、
**fetch・archive されただけでは SoT に入らない**。 内容はモデルが画像を読んで初めてテキスト化されるが、
その読取が session ごとの ad hoc 作業だと:

- 「どの画像を読んだか」 がどこにも記録されず、 未読と既読の区別が不可視になる
- 読取結果が chat に流れて消え、 構造化 DB への転記が部分的・非追跡になる
- 新着画像に重要情報 (新しい候補・確定・日程) が写っていても、 誰かが偶然読むまで silent に沈む

実例 (2026-07): 研究室ミーティングの板書写真を bot が 2 年半・約 100 枚 daily fetch していたが
transcript の置き場が無く、 直近 2 枚に写っていた新規候補 8 名 + 日程確定 1 件が最大 12 日間
どの SoT にも入らなかった (発覚は user の指摘)。

## パターン (4 点セット)

### 1. transcript home + 読取 ledger

読取結果の**正本ファイル**を 1 つ決める (例: `docs/meeting-board/{年度}.md`)。 構成:

- 冒頭に **読取 ledger 表** (撮影日 / 読取日 / 下流 DB への反映状況)。 「読んだか」 を機械可読にする
  ため、 節見出しは日付の固定書式 (`## YYYY-MM-DD`) にする (= 下記 detector が正規表現で拾う)
- 画像 1 枚 = 1 節。 verbatim 転記を基本とし、 **判読不確実な箇所には必ず ⚠️ marker** を付ける
- 下流 DB (候補リスト・人物 DB 等) へ転記したら節に転記済 marker を付け、 判断 data の home は
  下流 DB に移す (= transcript は「何が書いてあったか」 の記録、 判断状態は持たない)
- 対象範囲の開始日を決め、 それ以前は「未読 backlog」 と冒頭に明記する (= 全量読取を前提にしない。
  un-defer 条件も書く)

### 2. 手書き OCR の不確実性規律

手書き画像の読取は誤読が構造的に混ざる。 規律:

- **⚠️ 付きの読取を事実として下流に転記しない** (裏取りしてから)。 特に人名・日付・状態変更は保守的に
- 曖昧な領域は**画像を crop + 拡大して再読**する (全景 1 回読みで確定させない)。 それでも不確実なら
  ⚠️ のまま user 確認に回す
- 板書の担当者名・行為の帰属は**一次資料 (メール・チャット記録) で verify してから記録**する
  (= 板書の「○○さんから連絡」 は計画とも完了とも読める。 帰属一般則は
  [`actor-attribution.md`](actor-attribution.md))
- 同一人物の表記揺れ (ひらがな・愛称・姓のみ) は同定根拠を note に残す。 同定不能なら entry を
  立てず transcript の要確認リストに置く

### 3. 未読 detector (= 機械が見張る)

「画像はあるが transcript 節が無い日付」 を突合する小さな detector を dashboard 等の定期 surface に
統合する。 設計:

- source = 画像 metadata (fetch 済 JSON・ディレクトリの日付) / target = transcript の日付節
- 未読 = 猶予期間内 🟡 / 超過 🔴。 finding 0 件なら silent、 source 不在は fail-open
- `--selftest` を内蔵し、 CI / check runner で回す

これが**harness 非依存の backstop** になる: 下記の自動読取 routine が死んでも・人が忘れても、
未読は surface され続ける。

### 4. 自動読取 routine (任意) — 保守的 split

読取自体を定期 routine (cron + headless LLM session) に任せる場合、 **自動でやる操作を additive な
低リスク操作に限定**する:

- **自動 OK**: transcript 節の追記 (自動読取 marker 付き)、 新規名の候補登録 (出典・未確認 marker
  付き)、 読取 ledger 更新
- **人間に回す**: 状態遷移 (確定・断り・日程変更)、 calendar 登録、 外部発信 (メール・チャット投稿)、
  ⚠️ 付き読取の解釈 — これらは transcript に「要人間確認」 として列挙し、 TODO を 1 件起票して
  人間の surface に載せる
- routine の死は detector (§3) が拾う = **routine + detector の 2 層**で「自動化が silent に
  止まって未読が溜まる」 を防ぐ

## 設計の根 (なぜ ledger が要るか)

テキスト stream (メール・チャット) は grep 可能なので「あとから探せる」 が、 画像 stream は
**読取という変換を経ないと検索に引っかからない**。 変換が記録されない限り、 「fetch 済 = 把握済」 という
錯覚だけが残る (= 検索可能性の非対称)。 transcript home はこの変換の永続化であり、 読取 ledger は
変換の**網羅性の証明**である。

## 変更履歴

- 2026-07-21: 初版 (= 研究室ミーティング板書 2 年半分が transcript home 不在で未読不可視だった
  incident から抽出。 現時点の実例は 1 件 = N=1、 別 domain の 2 例目で内容を再検証する)
