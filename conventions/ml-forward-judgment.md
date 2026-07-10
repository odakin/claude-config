<!-- doc-meta
when: ML forward された依頼メールを inbox 化するとき
category: mail
summary: ML forward された依頼メールの inbox 化時の reflex 判定 trap 防止 (= 元 TO に名前なし = action なし、 ではない / 過去 ML の分野割当を遡る規律)
-->
# ML forward された依頼メールの inbox 化判定規律

学科 ML / 部署 ML / 委員会 ML 経由で「Forwarded / 転送」 された**依頼メール**を inbox に記録するときの reflex 判定 trap と、 それを防ぐためのゲート質問。 CLAUDE.md から参照: `~/Claude/claude-config/conventions/ml-forward-judgment.md`

## 典型的な誤判定 pattern

ML 主任 (= 学科主任 / 専攻主任 / 委員会幹事 / チームリード) が部署外 (= 外部部署 / 上位委員会 / 外注先 / 顧客企業) から受けた依頼メールを ML 全体に Fwd するパターン:

```
[元メール]
  From: 部署 X
  To: 分野責任者 A、B、C、D、E (= 5 名)
  Cc: 部署 X 内部
  Subject: ○○の作成依頼

[ML Fwd]
  From: A (= 主任)
  To: <ml-address>@gr.example.com
  Subject: [ml-id:NNNN] Fwd: ○○の作成依頼
  Body: |
    皆様
    主任の A です。
    部署 X より下記依頼がありました。 該当者は対応をお願いします。
    
    > [元メール本文]
```

このとき Claude (or user) が「**元メール To が分野責任者 5 名で、 自分の名前は無い → action 不要**」 と reflex 判定すると、 **実際は自分も該当者**であるケースを見落とす。

### Why この reflex は trap か

- **分野責任者 ≠ 実際の作問者・担当者**: 元メール TO は「分野代表 5 名」 で、 ML forward はその後ろにいる「実作業者全員」 への展開。 実際の作業者は ML メンバー (= 数十人) から自分の分野の作問者として割り当てられている
- **分野割当は別 ML スレッドで決まっている**: 「自分が今期の○○分野担当だよ」 は半年前の別 ML スレッドで決まっている。 元 Fwd メールを単体で見ても割当の事実は読み取れない
- **本人発信なし**: 主任からの Fwd は「皆様」 宛で、 「○○さんお願い」 ではない (= 配慮した broadcast)。 「自分宛じゃない」 ように見えるが、 そのメンバー全員が**個別の自分宛**として読まないといけない

## 防止のためのゲート (= inbox 化時に通す)

ML forward された依頼メールを inbox 化する判断で、 以下のゲートを必ず通す:

1. **元メール To に自分の名前 / アドレスが入っているか?**
   - Yes → 直接的 action 必要、 inbox category = 要対応
   - No → ゲート 2 へ (= reflex で「action なし」 と即断しない)

2. **元メール本文に「分野」 「担当」 「責任者」 「作問」 「審査」 等の役割割当キーワードがあるか?**
   - Yes → 過去 ML スレッドで自分が割当されている可能性、 ゲート 3 へ
   - No → 純 FYI として inbox category = 確認済の可能性高

3. **過去の関連 ML スレッドで自分の名前が割当 source として出ているか?**
   - 検索: `from:<主任 or 部署> subject:(関連 keyword)` (= 過去 1 年)
   - 該当スレッドの本文を読み、 「分野 / 担当 / 作問者」 として自分の名前を grep
   - Yes → 実は対応必要、 inbox category = 要対応、 該当する元 ML スレッドを cross_ref で参照
   - No → category = 確認済・action なし

## inbox entry の書式 (= 判定の根拠を残す)

```yaml
- id: "YYYY-MM-DD-<topic>-fwd-from-<主任 alias>"
  subject: "[ml-id:NNNN] Fwd: ○○の作成依頼"
  from: "<主任> (<email>)"
  to: "<ml-address>@gr.example.com"
  category: 対応済 (= ゲート 3 で割当判明、 提出済)
  cross_ref:
    - "<repo>/inbox:YYYY-MM-DD-<assignment-source-thread>"
  summary: |
    [元メール内容を 1 段落で]
  notes: |
    判定経緯 (= ML forward 依頼の reflex trap 防止):
    - 元メール TO は「分野責任者 N 名」 で、 自分は元 TO 外
    - **ただし** 過去 ML [ml-id:MMMM] (YYYY-MM-DD 主任メール) で
      「○○分野: <自分の名前>」 と割当られていた
    - よって自分も該当者、 inbox category = 要対応として記録

    関連スレッド: <repo>/inbox:YYYY-MM-DD-<source>
```

ゲート 3 の根拠 (= 過去 ML スレッドの message ID + 該当行) を notes に残すことで、 future の Claude が「**この判定はどう導かれたか**」 を追体験可能。

## メタ規律 (= 「動かない事象を見るバイアス」)

「**目の前のメール 1 通だけ**を見て対応要否を判断する」 のは reflex として速いが、 **複数 thread に跨がる役割割当**の context を見逃す。 inbox 化は「**過去 ML を遡って分野割当を確認**」 を含む作業で、 単一メール読みより重い。 後回しにできない (= 後回しにすると trap で見落とす)。

ML forward された依頼を inbox 化するときは、 以下の構造的問いを通す:
- 「**この依頼の対象者は誰か**?」 を元メール To だけでなく、 過去 ML の割当履歴も含めて確定する
- 「**自分は対象に含まれるか**?」 を割当履歴と照合して確定する
- 確定できなければ user に問い合わせる (= 不確定なまま「action なし」 と reflex 判定しない)

## 失敗例 → 防止導入 RCA

2026-05 事例: 主任 A から学科 ML に Fwd された「○○作成依頼」 を inbox 化したとき、 元 TO の 5 名 (= 分野責任者) に自分が含まれない事を根拠に「action なし」 と判定。 半月後に主任からのリマインダー [ml-id:NNNN+1] で「**未提出の方は今週金曜まで**」 と来て、 過去 ML で自分が「○○分野: <自分の名前>」 と割当されていた事が判明。 締切前に提出できたが、 リマインダーが無ければ超過のリスクがあった。

導入後: ML forward 依頼の inbox 化時、 ゲート 3 (= 過去 ML スレッドの割当履歴確認) を必ず通す。 ゲート 3 を skip すると同種 trap が再発する pattern。
