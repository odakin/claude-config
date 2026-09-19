<!-- doc-meta
when: 重要送信者・ML topic の見落とし防止 surface を設計するとき + 結果・通知・返事を待つ項目を台帳に立てるとき + 送り手を丸ごと雑音にする前 + 決着済み案件に自動督促が来続けるとき
category: mail
summary: 重要送信者・ML トピックを Gmail filter + retroactive labeling + dashboard surface の 3 layer で見落とし防止。 別スレッドで届く待ち結果は待ち項目の検索条件で拾う (#new-thread-expected-inbound) / 送り手一括の雑音化は class 別の件数を数えてから (#sender-noise-volume-check) / 決着済み案件への自動督促は本文の案件 ID で畳む (#settled-matter-key) / 「記録済み」 の書式は検出器間で 1 つ (#recorded-id-notation)
-->
# Email surface pattern (= 重要送信者・ML トピックの見落とし防止)

特定の送信者 (= 重要部署・取引先・上長) や ML 上のトピック (= 委員会業務・会議・人事) を**機械的に検出して Claude セッション開始時に必ず surface する**仕組み。 「見落とした」 を「規律違反」 ではなく「仕組み不足」 と捉えて構造化する。 CLAUDE.md から参照: `~/Claude/claude-config/conventions/email-surface-pattern.md`

## 動機 (= 規律 vs 仕組み)

「重要メールを見落とさないように気をつける」 は規律で、 失敗すると user / Claude の責任に帰される。 一方:

- Gmail filter が自動で「重要」 ラベル + STARRED + IMPORTANT を付ける
- セッション開始時に必ず走らせる dashboard script が「重要」 ラベル付き未読を最優先で表示する

の組み合わせなら、 規律に依存せず構造的に検出される。 規律と機械的検出は補完関係で、 機械的検出が「規律の負担を下げる」 ことに価値がある。 関連事例として `conventions/expensive-intermediate-artifacts.md` (= `/tmp` への artifact 永続化 reflex を hook で機械的検出) や `conventions/google-url.md` (= `/u/N/` URL 禁止を hook で検出) も同型の「reflex を hook で構造化する」 pattern。

## 構成 (= 3 layer)

### Layer 1: Gmail filter (= 自動ラベル付け)

Gmail filter で 2 種類のパターンを catch:

**Pattern A: 送信元 address による検出** (= 特定の部署 / 取引先 / 上長)
```
from:(<addr1> OR <addr2> OR <addr3>)
→ addLabels: [<重要送信者ラベル>, STARRED, IMPORTANT]
```

例: 機密性の高い業務を扱う部署の 3 メールアドレスから来るメール全てに「<部署名>」 ラベル + 黄色星 + 重要マーク自動付与。

**Pattern B: ML + subject keyword による検出** (= 学科 ML 等での重要トピック)
```
to:<ml-address> AND (subject:keyword1 OR subject:keyword2 OR ...)
→ addLabels: [<トピックラベル>, IMPORTANT]
```

例: 学科 ML での「<業務名> / 運営委員 / 担当割当 / 学科会議」 等 subject に対し「学科業務」 ラベル + 重要マーク。

注意:
- Pattern A は STARRED + IMPORTANT 両方付ける (= 強い signal)、 Pattern B は IMPORTANT のみ (= ML は数多いので STARRED は noise になる)
- subject keyword に too greedy なものを含めない (= 「入学」 だと「入学式」 「入学予定者数」 等の false positive)、 一方で narrow すぎると洩れる。 false positive を許容して洩れ防止優先が運用上は筋

### Layer 2: Retroactive labeling (= 既存メールへの遡及適用)

Gmail filter は**新規メールにのみ適用される**。 setup 後の filter は過去メールに作用しないため、 過去 1 年分等の既存メールには別途 batch_modify でラベル付与:

```python
# Pseudocode
msg_ids = search("<filter と同じ query>", max_results=N)
batch_modify(messageIds=msg_ids, addLabelIds=[<同 label ids>])
```

setup 直後の dashboard surface で既存の未読も一斉に visible になるので、 過去の見落としを retroactive に発見できる。 これが filter のみ (= 新規メール) と batch_modify (= 過去) の両輪。

### Layer 3: Dashboard surface (= セッション開始時の最優先表示)

セッション開始時の dashboard script で「重要」 ラベル付き **未読のみ**を取得して件名・送信者・経過時間で表示。 0 件なら無音 (= dashboard を散らかさない)。

```python
# Pseudocode
service = build_gmail_service(creds)
for label_name in ["<重要送信者ラベル>", "<トピックラベル>"]:
    label_id = resolve_label_id(service, label_name)
    msgs = list_messages(service, labelIds=[label_id, "UNREAD"], max=20)
    if msgs:
        print(f"=== 🚨 {label_name}: {len(msgs)} 件未読 ===")
        for m in msgs:
            print(f"  • {m.sender_short:30s} ({m.age}) {m.subject[:60]}")
```

dashboard 全体の末尾で呼び出し (= 既存 TODO 表示等の後)、 user / Claude が「最も新しい関心事」 として認識する位置に配置。

## リポ間の連携

```
gmail filter setup    -> 各 user の MCP 設定リポ + Gmail コンソール
batch_modify code     -> 各 user の odakin-prefs 等個人層の scripts/
dashboard surface     -> 個人層 scripts の <surface-name>.py を
                         unified-dashboard.py 末尾から subprocess invoke
session-start step    -> 該当業務リポの CLAUDE.md §「セッション開始時 (自動実行)」
                         で「dashboard を必ず走らせる + surface セクションを
                         最優先で対処」 を明記
ラベル運用注釈        -> 該当業務リポの contacts.yaml (or 同等の住所録) entry
                         に「filter で自動ラベル付け対象」 を記録 (= 削除時の
                         手当て根拠)
```

## false positive / false negative の trade-off

- **filter が too greedy** (= 例: subject に「入学」 を含む全 ML) → 入学式・入学予定者数等の false positive、 ラベルが noisy。 軽微、 見落とし防止優先で許容
- **filter が too narrow** (= 例: subject に「<業務名>」 の完全一致のみ) → 「<業務名>運営委員」 「担当割当」 関連を取りこぼし、 見落とし発生。 重大、 false negative は許容しない
- **判定原則**: false positive を許容して false negative を防ぐ方向で設計

ラベル名の選択も「狭めすぎない」 がベター (= 「<業務名>-ML」 より「学科業務-ML」 で会議・人事等も catch する余地)。 ただしラベル名が広すぎると surface 件数が爆発する trade-off あり、 user の実情に合わせて調整。

## 失敗からの導入 RCA (= 規律ではなく仕組みで防ぐ)

過去事例 (= 2026-05): 重要部署からのメール 1 通を「あとで対応」 して数日見落とし、 同テーマの ML 議論が並行して走っていることにも気付かず、 user 指摘で発覚。 規律 (= 「重要部署メールはすぐ対応」) は守っていたつもりでも、 humanly 5 日も経つと埋没する。

導入後: filter + dashboard surface で session 開始毎に「重要部署未読 N 件 / ML 重要トピック未読 M 件」 が画面に出るようになり、 構造的に reflex 化される。 規律負担を下げ、 同時に過去の埋没メールも retroactive labeling で一斉発見できる。

## <a id="raw-sweep-declared-skip"></a>surface を迂回した raw sweep は「決着済み」 を知らない

surface 機構 (= filter / label / dashboard) は **既に「見送り」 と決めた class を抑制する**のが仕事。
∴ user の質問に答えるために **mailbox を直接 query した** (= 「最近の ○○ 関係のメール」 型の
ad-hoc sweep) とき、 その結果には **決着済みの案件が普通に混ざる** — surface されていないのは
「見落としている」 からではなく「意図して黙らせている」 からである。

これを知らずに報告すると、 **user が数日前に自分で決めた見送りを、 未対応として突き返す**
ことになる (= 決定の巻き戻しを迫る形になり、 user の時間を二度使わせる)。 定期的に届く
reminder は declared skip の**予定された自然減衰**であって、 新しい signal ではない。

**規律**: raw sweep の結果を「未対応」「要判断」 として報告する前に、 各件について
**task 台帳と受信記録に決着 (= 完了 / declared skip / class opt-out) が無いか grep する**。
外部検索の null を内部確認なしに「不在」 と結論しない規律の **positive 版** (= 外部の hit を
内部確認なしに「未処理」 と結論しない)。 grep 先は task 台帳の status と、 surface 設定の
opt-out list の両方 — 後者にしか痕跡が無い決着もある (= class 単位の opt-out は個別 task を
作らずに終わることがある)。

初出: 未応答の査読招待を「受ける/断るを決めた方がよい」 と報告したが、
1 件は前日に user が「無視でいい」 と declared skip 済 (= task 台帳に status 完了で記録)、
もう 1 件は 3 週間前に class ごと opt-out 済 (= surface 設定の opt_out_senders に登録) だった。
どちらも直前の session で自分が関与した決定ではなく、 台帳を引けば 1 grep で分かった。

## <a id="new-thread-expected-inbound"></a>待っている結果が別スレッドで来る — 待ち項目に検索条件を持たせる

返信待ちの網は普通「送った mail のスレッドに相手の新着があるか」 を見る。 ところが **審査結果・受付通知・
サポートの返事・申込システムの通知** は no-reply の自動送信で、 **毎回 新しいスレッド** になる。 送った
スレッドには何も来ないので、 網は原理的に黙る。 さらにこういう送り手は宣伝メールと同じ domain から来るので、
雑音 list にも入っていることが多い。

実測: 結果通知が 1 通、 名指し (本文に宛名が無い) / 未認識 (送り手 domain が雑音 list) / 返信待ち (新スレッド) /
期限 (回答の目安がまだ先) の **4 つの網を全部すり抜け**、 人に聞かれるまで気づかなかった。 台帳には
「結果は機関アドレス宛」 と散文で書いてあったが、 散文は何も見張らない。

- **待ち項目を立てる turn で、 送り手と件名で検索条件を書く** (例 `watch_query: [{account: <受信 account>,
  q: "from:<送り手 domain> -subject:<雑音の件名> newer_than:45d"}]`)。 網は条件に当たった未記録 mail を
  スレッドに依らず、 elevated tier で出す
- 条件は **件名の除外で雑音を削る** (サインイン用リンク等、 同じ送り手からの読む価値の無い通知)
- 期間は待つ長さに合わせる (`newer_than` を回答見込み + 余裕に)。 記録済みの mail は出さないので、 過去の
  やりとりに当たっても静か
- 実装 = [`scripts/lib/mail_watch.py`](../scripts/lib/mail_watch.py) の `watch_queries` / `unrecorded_threads`。
  一般則 = [`convention-design-principles.md#retrieval-key-choice`](../docs/convention-design-principles.md#retrieval-key-choice)
  (thread ID でなく送り手・件名という別の鍵で引く)、 予告された inbound の時計は
  [`#expected-inbound-tripwire`](../docs/convention-design-principles.md#expected-inbound-tripwire)

## <a id="sender-noise-volume-check"></a>送り手を丸ごと雑音にする前に、 class 別の件数を数える

「この domain は宣伝ばかり」 と送り手単位で雑音 list に入れると、 **同じ送り手から来る少数の見るべき mail
(審査結果・受付・請求の失敗) だけを確実に捨てる** 仕掛けになる。 宣伝の多い account で決めた判断を、 別の
account (機関アドレス等) にもそのまま写したときに起きやすい。

実測: 機関アカウントで送り手一括の雑音にしていた domain は、 実際には宣伝が 0 通で、 見るべき通知と
サインイン用リンクしか来ていなかった = 雑音 list が捨てていたのは見るべき通知だけだった。

- **入れる前に account ごとに `from:<domain>` を 1 年分数え、 件名で class に分ける**。 宣伝が無い account には入れない
- 雑音の class が件名で分かるなら、 **送り手でなく件名のパターンで雑音にする** (見るべき class が素通りする)
- 既存の送り手一括の行は、 見落としが出た turn でその account の実数を数え直す

## <a id="settled-matter-key"></a>決着済み案件への自動督促 — 本文の案件 ID で畳む (消さない)

決着 (完了 / 見送り) させた案件に、 相手のシステムが自動リマインダを送り続けることがある。 これも **毎回
別スレッド** なので、 messageId / threadId で「記録済み」 を判定する網では未認識のまま再浮上し、 義務の
class に見えれば最上位に出る。 実測: 見送りを決めた依頼の督促を「未認識の義務」 として拾い、 決着を知らずに
重複で起票した。

効く鍵は **本文に必ず入る案件 ID** (招待 URL の UUID / 原稿 ID / 受付番号) で、 スレッドが変わっても同じ。

- 決着させる turn で、 台帳の項目に `matter_key:` を書く (短い・汎用の文字列は誤爆するので書かない。
  実装は 8 文字未満を捨てる)
- 網は **自動送信の送り手** (no-reply / notifications@ 等) ∧ **決着済み項目の key が件名・snippet・本文に入る**
  mail だけを、 未認識の段と義務の push から外し、 **専用の 1 行段に残す** (消すと、 黙らせた物が見えなくなる)
- **人間発は畳まない** — 決着済み案件への人の新しい連絡は見たい (見送り close で死ぬ網を作らない)
- **項目を open に戻すと key は使われない** = 誤って畳んだときの戻し方が台帳の操作 1 つで済む
- 本文を引くのは自動送信の mail だけにする (人間発は判定に本文が要らない、 API 呼び出しを増やさない)
- 実装 = [`scripts/lib/mail_watch.py`](../scripts/lib/mail_watch.py) の `settled_matter_keys` / `split_settled`。
  surface を迂回した raw sweep 側の同じ問題 = 上の [#raw-sweep-declared-skip](#raw-sweep-declared-skip)

## <a id="recorded-id-notation"></a>「記録済み」 の書式を検出器ごとに持たない

記録には `messageId:x` のほか、 ログ行の短縮形 (`mid:x`) なども混ざる。 複数の網がそれぞれ独自の regex で
記録済み集合を作ると、 **ある網だけが短縮形を読まず、 記録済みの mail を「未認識」 に出し続ける** (実測:
他の網は共有の harvester を使っていて、 1 つの網だけが独自 regex だった)。 書式の読み取りは共有の関数 1 つに
寄せ、 その関数に「どの網が使っているか」 の一覧と、 一覧の全員が実際に import しているかの selftest を持たせる。
一般則 = [`data-pipeline-automation.md#multipath-key-normalization`](data-pipeline-automation.md#multipath-key-normalization)。
