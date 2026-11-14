<!-- doc-meta
when: 重要送信者・ML topic の見落とし防止 surface を設計するとき + 結果・通知・返事を待つ項目を台帳に立てるとき + 送り手を丸ごと雑音にする前 + 決着済み案件に自動督促が来続けるとき + 会員サービスからの情報流出のお詫びが網から落ちたとき (#vendor-breach-notice-class) + 止まっている待ちの項目を棚卸しするとき (#waiting-item-answer-elsewhere) + 当番が年ごとに替わる会の案内 (出欠のフォーム) を最初の便で拾う網を作るとき (#recurring-event-invitation)
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

<a id="list-all-pages"></a>**ラベルの全体を読む段 (未読に依らず「ラベルあり ∧ 記録に無い」 を出す段など) は、 一覧を 1 page で止めない** — `messages.list` は新しい順に返す ([`mcp.md#search-result-cap`](mcp.md#search-result-cap) と同じ) ので、 1 page (`maxResults`) で止めると、 その数より古いラベルつきの便が黙って段の外に出る (実測: 段に出るべき便が全部 1 page の外にあり、 段は 0 件だった)。 `nextPageToken` を尽きるまで辿り、 metadata を取る前に絞る = 段に並べない便は一覧の検索で外し (自分の送信なら `q="-in:sent"`)、 記録済みの id は引いてから metadata を取る (実測: 全部の metadata を取る形と同じ行を、 ずっと短い時間で出した)。 既読・未読・日付に依らない段を日数 (`newer_than:`) で切ると、 同じ取りこぼしが日数の外に移るだけ。

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
  q: "from:<送り手 domain> -subject:<雑音の件名> after:<起票の日>"}]`)。 網は条件に当たった未記録 mail を
  スレッドに依らず、 elevated tier で出す
- 条件は **件名の除外で雑音を削る** (サインイン用リンク等、 同じ送り手からの読む価値の無い通知)
- 期間は起票の日から切る (`after:<起票の日>`。 依頼を出した日が起票より前ならその日)。 今日から数える窓 (`newer_than`) だけの
  条件は起票より前の mail も含む (下の項)。 記録済みの mail は出さないので、 過去のやりとりに当たっても静か
- <a id="watch-query-after-request"></a>**特定の依頼への返事を待つなら、 期間を依頼の日から切る** (`after:<依頼の日>`)。 `newer_than` の窓は
  依頼より前の同じ送り手の mail も含み、 それが記録されていない (読めば済む通知だった) と「返事が届いた」 と出る (実測)。
  条件を書く瞬間には守られないことがある (実測) = 項目の台帳を commit する検査で、 日付の印 (`after:` / `before:`) の無い条件に
  1 行知らせる形を置ける (止めない。 起票より前から結果を待つ項目もある)
- <a id="watch-query-spam"></a>**Web フォーム経由の問い合わせの返事を待つときは `in:anywhere` を付ける**: フォームサービス
  (Wix など) の自動返信や、 店の担当者の初めての返事は迷惑メールに入りやすい。 Gmail の検索は既定で迷惑メールと
  ごみ箱を見ないので、 条件に `in:anywhere` が無いと網は黙る (実測: フォーム送信直後の自動返信が迷惑メールに
  入っていた)。 迷惑メールから見つけたら API で `SPAM` ラベルを外して `INBOX` を付ければ受信トレイに戻るが、
  これが画面の「迷惑メールではない」 と同じ学習の合図になるかは公開文書に書かれていない = 確実にしたいなら
  「迷惑メールにしない」 フィルタ (残る設定なので本人の OK を取ってから)
- <a id="watch-query-sender-wide"></a>**差出人だけの条件 (`from:<人>`) は、 その人の別件のメールにも当たる**: 同じ相手と別の案件を並行して持つと、
  別件の新しいスレッドがこの項目の返事として出る = 結ぶ項目は本文を読んで決める (実測: 網が結んだ項目と本文の案件が違った)。
  網は記録した mail を出さないが、 項目の行に「最終更新より新しい返事」 を記録済みも含めて添える表示を持つ環境では、 項目を更新するまで添え続ける
  = 別件として記録する turn で条件を持つ項目にも結び、 現在地に「別件 (どの項目の話か)」 と書く。 続くなら条件に件名の語を足して絞る
- 実装 = [`scripts/lib/mail_watch.py`](../scripts/lib/mail_watch.py) の `watch_queries` / `unrecorded_threads`。
  一般則 = [`convention-design-principles.md#retrieval-key-choice`](../docs/convention-design-principles.md#retrieval-key-choice)
  (thread ID でなく送り手・件名という別の鍵で引く)、 予告された inbound の時計は
  [`#expected-inbound-tripwire`](../docs/convention-design-principles.md#expected-inbound-tripwire)

## <a id="waiting-item-answer-elsewhere"></a>待ちの項目の答えは、 結んだスレッドの外に届いている

止まっている待ちの項目を棚卸しするとき、 結んだスレッドの最後の message だけを読むと「相手が黙っている」 に見える。 実際には答えが別の経路に来ていて、 項目の現在地だけが古いことがある (実測: 棚卸しの結果が「催促」 より「もう動いている」 に多く倒れた)。 催促や問いを書く前に、 1 件ごとに次を引く:

- **一斉配信** — 依頼や結果が ML の転送で、 名指しなしに届いている
- **成果物の置き場** — 判断を待っていた相手の答えが、 repo の commit や台帳に当たって終わっている
- **メール以外の依頼の経路** — 掲示板・チャットの依頼に答えが返り、 受け取りも済んでいる
- **自分の送信済み** — 途中経過の返事を出してあって、 項目に写っていない
- **自分の下書き** — 送ったつもりの返事が未送信のまま残っている (スレッドの一覧に送信済みと同じ形で混じる道具がある = 道具の側で下書きに印を付ける)
- **会議の要約** — 相手と口頭で決めた段取り ([`zoom-meetings.md#summary-mail-holds-agreements`](zoom-meetings.md#summary-mail-holds-agreements))
- **外部の system を前に読んだ写し** — 経理・支払いの system から取って手元に残した記録に、 待っていた処理 (精算・支払い) の結果がもう載っている。 窓口に聞く・本人にログインを頼む前に見る (実測)

項目の本文にある前提 (「来ていない」「未定」) も疑う: 書いた時点の読みで、 その後の変化は書いた人に届いていない。 答えが項目を立てる前に届いていることもある (項目を立てたときに 1 つの経路しか見なかった) = 引く範囲は項目を立てた日でなく、 依頼を出した日から (実測)。 本人に問うときは、 何の件かを 1 文で添える (止まっていた項目は本人も覚えていない)。

## <a id="sender-noise-volume-check"></a>送り手を丸ごと雑音にする前に、 class 別の件数を数える

「この domain は宣伝ばかり」 と送り手単位で雑音 list に入れると、 **同じ送り手から来る少数の見るべき mail
(審査結果・受付・請求の失敗) だけを確実に捨てる** 仕掛けになる。 宣伝の多い account で決めた判断を、 別の
account (機関アドレス等) にもそのまま写したときに起きやすい。

実測: 機関アカウントで送り手一括の雑音にしていた domain は、 実際には宣伝が 0 通で、 見るべき通知と
サインイン用リンクしか来ていなかった = 雑音 list が捨てていたのは見るべき通知だけだった。

- **入れる前に account ごとに `from:<domain>` を 1 年分数え、 件名で class に分ける**。 宣伝が無い account には入れない
- 雑音の class が件名で分かるなら、 **送り手でなく件名のパターンで雑音にする** (見るべき class が素通りする)
- 既存の送り手一括の行は、 見落としが出た turn でその account の実数を数え直す
- **件名が固定の通知まとめ (チャットツールのメンション通知など) は、 件名で class が分からない** — 1 通に複数の投稿が
  束ねられ、 任意の案内と期限つきの依頼 (回答期限のある調査など) が同居する。 件名で雑音にも、 読まずに「行動なし」
  にもしない = 本文の投稿ごとに読んでから決める (同じ送り手の通知が 1 スレッドにまとまる点は [#drop-by-message-id](#drop-by-message-id))
- <a id="obligation-words-miss-opportunities"></a>**送り手一括の雑音に「義務の語」 で穴を開ける形は、 義務でない機会の類を拾わない** — 全員を名指しで送る機関システムの
  個人宛の通知 (掲示の転送など) は、 送り手 1 つに義務・機会 (希望者が期限までに申し込む福利・任意参加)・お知らせが混ざる。
  名指しの段を守るために送り手ごと雑音にし、 義務の語 (重要・提出・回答期限) で破ると、 機会の案内 (受付開始・予約受付期間・申込) は
  語に当たらず全部落ちる。 件名の語に機会の類も入れるか、 送り手でなく件名の型で雑音にする
  ([`../docs/convention-design-principles.md#lapsing-opportunity-intake`](../docs/convention-design-principles.md#lapsing-opportunity-intake))。
  実測: 機会の案内が、 届いた日から申込の締切まで、 どの段にも出なかった。

## <a id="vendor-breach-notice-class"></a>情報流出のお詫びは広告と同じ顔で届く — 件名の語を組にして義務の class に入れる

会員になっているサービスからの「不正アクセスによる情報流出のお詫び」 は、 次の 3 つが重なって網から落ちる (実測):

- 広告・会報と同じ送り手 (info@ / magazine@ など) から届き、 Gmail は更新などの分類に入れる = 分類ごと雑音にしている account では黙って捨てられる
- 宛名は「お客様各位」 で、 名指しも期限の語も無い = 名指しの網も期限の網も掛からない
- 1 通だけ届く = 同じ件名の繰り返しで拾う網も掛からない

残る面は件名の語だけなので、 義務の class (分類で雑音にしていても上に出す語) に入れる:

- 「流出」「漏えい」「漏洩」 単独では、 ニュースの会報 (セキュリティの記事) が引っかかる。 **流出の語のすぐ後に「お詫び」「ご報告」「お知らせ」「おそれ」 が来る形** にする (英文は apology … leak / notice of data breach)。 実測: 1 年分の件名に当てると、 本物の通知は全部拾い、 ニュースの会報は 1 通も拾わなかった
- 入れる前に、 その語を含む件名を account ごとに 1 年分引いて当て、 拾う・拾わないを数える ([#sender-noise-volume-check](#sender-noise-volume-check) と同じ手)
- 語を server 側の検索 (Gmail の `subject:"…"`) に直して候補を絞る網では、 **パターンの先頭を文字にする**。 先頭が括弧の正規表現からは検索語が作れず、 その網でだけ黙って拾わない。 選択の括弧で始めず、 語ごとに分けて書く
- 拾った後は、 通知が本物かを、 メールのリンクでなく公式サイトの告知で確かめる (送り手のドメインがサービスの本体と違うことがある)。 使い回したパスワードの点検 = [`leaked-password-triage.md`](leaked-password-triage.md)

## <a id="recurring-event-invitation"></a>当番が替わる会の案内 — 年を越えて残る軸で拾い、 回答の控えと別の経路の告知を見る

年に 1 回の会 (懇親会・祝賀会など、 出欠をフォームで答え、 答えないと欠席になる案内) は、 次の形で網から落ちる (実測):

- 送り手は当番 (幹事) で、 年ごとに替わる (個人のアドレスの年も、 ML 経由の年もある) = 差出人の網は次の年に効かない
- 宛名は会員全員 (「各位」) で名指しが無い = 名指しの網が掛からない
- 最初の告知は別の経路 (学内の掲示板・portal) で先に出て、 メールの案内はその後に来る。 メールの本文が「◯月◯日に△△でお知らせした」 と先の告知の日を書いていることがある (日は年で違う)

拾い方:

- **過去の数年分の便を引いて、 年を越えて残る軸を選ぶ**。 当番が替わる会では差出人が替わり、 件名の形が残る (同じ人が毎年送る便は逆 = [`../docs/convention-design-principles.md#retrieval-key-choice`](../docs/convention-design-principles.md#retrieval-key-choice) の表の「年ごとの件名・差出人」 の行)。 残る軸 (件名の語) を網の本体にし、 その年の当番の表示名と宛先を控えに足す
- 件名の語を義務の class に入れると雑音の設定を貫く = **同じ会の名を件名に持つ自動の便を外す**: フォームの回答の控え (件名にフォームの題 = 会の名が入る) と、 出欠の後に来る参加者向けの詳細の便。 「案内・お知らせ・出欠」 の語との組で控えを外し、 詳細の語は否定の先読みで外す (先頭は文字のまま = [#vendor-breach-notice-class](#vendor-breach-notice-class) の 3 つ目)。 入れる前に account ごとに数年分の件名に当て、 拾う・拾わないを数える
- メールの網の外の先の告知は、 本文に書かれた日の少し後に期限を置いた年次の項目で探す (日が年で違うので、 早い年の後と遅い年の後に 1 回ずつ)。 掲示板を見張る定期のアクセスは、 ログインの切れを延ばす形になりやすい
- 案内が来た後に誰が出欠を決めるか (本人か、 決定を任された agent か) を委任の規則に書く。 網が鳴っても、 任された側が出欠を決めてしまうと本人には見えない

**試し方 = 過去の便で本物の見張りを回す**: 過去の案内が今も未読で未記録なら、 届いた直後と同じ条件にある。 見張りの本物の関数を、 検索の期間だけ広げて (Gmail の一覧の呼び出しを包み、 query の `newer_than:` を書き替える) 呼ぶと、 合成の fixture より強い確かめになる。 cache を書かない関数を呼ぶ。 合成の fixture も selftest に足す (翌年に過去の便が窓を出ても、 判定の regress を止める)。

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
共有の関数があっても、 **書き手の散文の形が契約の外なら同じ症状になる** (実測: thread の台帳の要約が `messageId <hex>、` と空白で区切って書かれ、 `messageId:` の形しか読まない harvester が記録済みの mail を session 開始のたびに「未認識」 に出し、 Stop の強制処分まで鳴り続けた)。 書式を 1 つに固定できない以上、 読み手が散文の空白区切り (12 桁以上の hex) と `thread_id:` の素値も読む。 症状が「記録したのに出続ける」 なら、 まず harvester にその台帳の text を通して id が拾えるかを確かめる。

<a id="drop-by-message-id"></a>**読み手が finding を「記録済み」 として落とす判定は message の id で行い、 thread の id の一致では落とさない**: thread が記録されていても、 そこに後から届いた message は未記録 (通知系の mail は 1 つの thread にまとまり、 ML の続報も同じ thread に来る)。 thread の一致で落とす検出器は、 記録済みの thread に届いた新しい依頼を黙って消す (実測)。 thread だけ記録された古い entry の root message は id が thread の id と同値なので、 記録済み集合を messageId ∪ threadId にしておけば root だけが落ち、 続報は残る (root を落とすかは読み手の判断。 書き手の道具は root を「読んだ message」 として索引に載せない = [`mail-thread-ledger.md`](mail-thread-ledger.md))。 台帳の抑制を cache の書き手だけでなく読み手の全部に当てる理由 = [`../docs/convention-design-principles.md#suppress-at-read-time`](../docs/convention-design-principles.md#suppress-at-read-time)。

## <a id="single-writer-thread-cursor"></a>記録の書き手を道具 1 つにし、 thread ごとに「読んだ位置」 の印を持つ

上の「書式を検出器ごとに持たない」 は読み手側の対策で、 書式が散る根 (= 人と agent が id を手で写す) は残る。
記録が高いと未記録が溜まり、 「記録済みか」 の判定は書き手が harvester を呼ばないと誤る (実測: 1 つの台帳だけを
grep して、 別の台帳に記録済みの続報を「未記録」 と判定した)。 対策 = **id を書くのは道具だけ**にする:

- 記録の単位は message でなく **thread**。 thread 1 つに entry 1 つ、 続報・返事・自分の返信は同じ entry の索引
  (`messages[]`、 1 通 1 行 = id・日時・方向・相手 〔相手発 = 差出人 / 自分発 = 宛先〕) に足し、 読んだ位置の印 (`recorded_upto`) を進める。 印と索引は
  harvester の契約の中の書式で書く (= 読み手を変えない。 道具の出力の形を harvester の fixture に足して固定する)。
- 道具は**全ての台帳**から記録済みを集める (1 つだけ grep しない)。 既定は dry-run で未記録の本文と書く予定の差分を
  出し、 書いた後に再 parse と round-trip (書いた id が harvester で拾われる) を検査し、 外れたら元の text に戻して
  「検査不能」 の終了値で止まる (違反の終了値と分ける)。 取得できなかった thread は「未記録」 に倒さない。
- 事実 (金額・日付・決定) は案件の正本 1 か所に書き、 索引の entry は pointer だけ。 進捗の叙述は項目の 1 欄を
  **上書き** (履歴は版管理に任せる)、 notes に日付つきの行を足さない = 台帳が log になって肥大しない。
- 既存分の移行は**追記だけ**: 印と索引を、 その entry が既に持つ id と一致する message についてだけ書く
  (= 「記録した」 を捏造しない)、 散文は変えない、 id を消さない (裸の 16 進を読む網が silent に反転する)。
  移行の前後で読み手の出力が変わらないことを実データで確かめてから commit する。
- 「印 ≠ 索引の最新」 は loud に出る側の失敗 (silent な抑制ではない)。 整合の検査を道具自身に持たせる。
- **下書きは message ではない**: Gmail の thread には未送信の下書きも入る。 読む部品の既定で落とさないと、 記録の道具は
  下書きを「送った」 と書き、 返事の見張りは「最後は自分発 = 返事済み」 と読んで相手の未返信を隠す (実測)。
  正本 = [`mail-thread-ledger.md#drafts-are-not-messages`](mail-thread-ledger.md#drafts-are-not-messages)。
- 索引の名前・向きのような派生値は id から引き直せる形に保ち、 書き方の規則を変えたら引き直す道具で揃える
  (手で直さない。 [`convention-design-principles.md#relabel-derived-from-key`](../docs/convention-design-principles.md#relabel-derived-from-key))。
- 記録の道具が項目の現在地を**上書き**するなら、 上書きされる前の値を毎回見せる (実測: 返事を 1 件記録した
  「次の一手」 がその 1 件だけを書き、 前の現在地に残っていた別の手順が項目から消えた。 `record-reply.py` は
  dry-run でも apply でも前の値を出す = 残っている手順は「次の一手」 に書き直す)。

## <a id="record-bound-mark-read"></a>未読を鍵にした見張りは対応済みで埋まる — 既読化を記録に束縛した道具で払う

Layer 3 の「ラベルの未読」 の段は、 記録を付けても Gmail の UNREAD が残るので、 対応済みの mail で膨らみ続け、
本物の数件が数百件に埋もれる (実測)。 記録を付ける側と既読にする側が別の操作で、 後者を誰もしないのが根。

- **既読化の判定を記録に束縛する**: 外す対象は「対応済み」 と記録で言えるものに限る = messageId か threadId が
  記録の台帳に在る (harvester は他の網と同じ関数 = [`#recorded-id-notation`](#recorded-id-notation))、 または
  「見て対応不要と決めた」 ack の台帳に日付と理由つきで在る。 どちらでもない未読は触らず、 仕分けの対象として一覧に出す。
  外すのは UNREAD だけ (ほかのラベル・削除・移動はしない)、 既定は dry-run。 道具 = `scripts/mark-handled-read.py`
  (個人の構成 = 見るラベルと台帳の場所は呼び出し側が渡す)。
- **仕分けの流れに入れる**: 記録を付けたら同じ流れで既読化まで回す (人の記憶に頼らない)。 ML の議論のように
  「読んで対応不要」 と決めたものは、 候補 (`--ack-snippet`) の件名を見てから ack に足す (見ずに貼らない)。
- **auto mode**: その場で書いた一括の既読化 script は外部への書き込みとして止められる (実測)。 判定を記録に束縛した
  専用の道具にし、 その path だけを allow に宣言する (宣言した rule を各マシンへ配る仕組みで。 settings を session 中に
  手で直さない = [`claude-code-permissions.md`](claude-code-permissions.md))。
- **ack の台帳は許可そのもの**: 止められた既読化を通すために agent が自分で ack を書くと、 自己承認として止められる
  (実測)。 ack を足すのは本人の OK の後 (件名と日付を見せて判断を仰ぐ)。
- 見張りの段自体も同じ判定で「未対応の未読」 だけを出す形に寄せると、 既読化を待たずに埋もれが消える
  (既読化は Gmail 側の見た目、 段の中身は判定で決まる = 両方を同じ関数で)。
