<!-- doc-meta
when: Indico (CERN 等) の会議に abstract 投稿・参加登録・支払いを進めるとき、会議の実績やアカウント重複を確認するとき
category: office
summary: Indico (indico.cern.ch 系) の abstract 投稿で実際に踏んだ機構と落とし穴 (= CERN SSO の login 経路選択 〔guest 登録の確認 mail が来ない / 外部 ID = Google 等で入り既存 profile に紐付ける〕 / 所属は SSO 同期を切らないと編集不可 / 別 mail で profile が二重化したら merge 依頼 / abstract form の Authors 〔= 発表者を含む著者〕 と順序は手動並べ替え 〔alphabetical は自分で〕 / 受理通知 mail に abstract ID / reminder 分単位 〔1 週間 = 10080〕 / 本文は plain text 寄り)。 jps-talk-submission.md / paper-submission.md の sibling (会議 abstract 側)
-->
# indico-abstract-submission.md — Indico 会議 abstract 投稿の機構と落とし穴

**Load this when**: Indico (CERN が運営する indico.cern.ch、 または各機関の self-hosted Indico) の会議に abstract / talk を申し込むとき、 あるいは login・所属・重複アカウントで詰まったとき。

会議ごとの値 (締切・track 名・字数上限・採否通知時期) は当該 event page が正本。 本 file は **Indico という platform で毎回同じように効く機構と落とし穴**だけを持つ (= [jps-talk-submission.md](jps-talk-submission.md) / [paper-submission.md](paper-submission.md) と同じ思想)。 個人の ID・どの外部 ID で入ったかは個人層に置く。

## 1. login 経路 (indico.cern.ch = CERN SSO)

- login ボタンは CERN SSO に飛ぶ。 選択肢は概ね (a) CERN account / (b) **guest (external) account を新規作成** / (c) **外部 ID provider (Google 等) でサインイン**。
- (b) は **確認 mail が届かない・遅れることがある** (2026-08 実測: 待っても来ない)。 先に (c) を試す。 Google で入ると、 **同じ mail address の既存 Indico profile があればそこに紐付く** (= 過去に登録した profile がそのまま使える)。
- 「Google で入る経路が無いように見える」 時は、 SSO 画面の **"Sign in with …" / "link account"** 系の導線を探す — 初見で見えにくい位置にある。
- 一度外部 ID で入れたら、 以後もその ID で入る (= 別の mail で guest を作ると profile が二重化する)。

## 2. profile と所属

- profile の **affiliation は SSO から同期**されている場合、 編集欄が disabled。 profile 設定の **「同期 (sync) を OFF」** にしてから書き換える。
- 別 mail address で profile ができてしまった (= 職場 mail と個人 mail の 2 つ) ときは **Indico サポート (event の contact ではなく indico 運営) に merge 依頼** mail を送る。 返事は数日〜。 abstract は先に出してよい (= merge は後追いで効く)。

## 3. abstract form

- **Authors と Co-authors は別欄**: Indico の "Authors" = primary authors (= 発表者を含む、 採録に載る著者)、 "Co-authors" = 副次。 **通常の共著論文の著者は全員 Authors に入れ、 自分に speaker flag** を立てる。 Co-authors 欄は空でよい。
- **並び順は手動** (= 追加順のまま)。 alphabetical にしたいなら自分で並べ替える (drag / 上下)。 後から気付くと編集で直せるが、 提出前に 1 度見る。
- 著者 entry は Indico の user DB 検索で追加できるが、 **所属が古い** ことがある (= 本人 profile 未更新)。 表示名・所属を form 上で上書きして揃える。
- 本文は plain text 中心 (= markdown は効かない、 LaTeX は event 設定次第)。 字数 / 単語数上限は event 設定、 超過は submit 時に弾かれる。
- **タイトルの大文字**: 投稿 form は何も強制しない。 分野の慣習 (素粒子は sentence case が普通) に合わせる。 副題の区切りは「:」 + 次語を大文字 ("…: Real vs virtual propagation")。
- 受理通知 mail (subject に "abstract" + event 名) に **abstract ID と URL** が入る — 記録はその mail の messageId と ID を残す (= 後の採否通知・修正依頼は ID で来る)。
- "Submit" 後も締切まで編集可 (= event 設定次第)。 編集したら再度 confirmation が来ることがある。

## 4. reminder / calendar

- event timetable の reminder 設定は **分単位**の数値入力 (1 週間前 = 10080、 1 日前 = 1440)。
- 採否通知は event page の "Call for Abstracts" に書かれた日付を calendar / TODO に入れる (= Indico から自動では来ない)。

## 5. 記録の最小セット (個人層 / 案件 repo 側)

- login に使った外部 ID・profile URL・merge 依頼の有無 (= 次回また詰まらないため)
- abstract ID・提出版本文・著者順・confirmation mail の messageId
- 採否通知の期日 (TODO)

## <a id="registration-payment-separation"></a>6. 採択・参加登録・決済・猶予は別の状態

- Abstract の提出・採択は参加登録を兼ねるとは限らない。参加登録番号と採択番号を
  別々に記録し、登録完了画面と通知を確認する。登録完了は支払い完了ではない。
- 登録時には実際のフォームの必須項目と文字数上限を読む。登録フォームの `Abstract`
  欄は、別途採択された概要の投稿欄と容量が違う場合がある。既に採択済みなら、欄の
  用途と許容内容を確認して既存ID/URLへの参照を使い、科学概要を勝手に改作しない。
- 送信後に入力画面へ戻っても再送を連打しない。赤枠・文字数制限・エラー表示と
  サーバー側の登録状態を調べる。AXで値やエラーが省略されている場合は、スクリーン
  ショットまたは画面に対応するDOM属性で補う。[フォームの送信確認](web-form-automation.md#submit-truth-is-server-state)
- 重複プロフィールの統合依頼は独立案件。依頼済みを統合済みとせず、実際のprimary
  メール・ログイン先・採択済み投稿との関連を確認する。既存主アカウントで登録可能か
  と、統合が完了したかを混同しない。新しいアカウントを追加して重複を増やさない。
- 参加費の区分・通貨・宿泊等の包含範囲・手数料は支払画面で確認する。日付や国籍・
  学生区分の既定値をそのまま使わない。決済と対外連絡は、それぞれの明示承認に従う。
- 猶予の依頼・運営の承認・支払実行・受領確認を別々に追う。早割期限、通常登録期限、
  支払受領期限、個別の発表取消期限も別。一般期限の前の催促は、すぐ期限切れという
  意味でも、その日まで枠が保証されるという意味でもない。

## <a id="conference-evidence"></a>7. 会議の実体と参加価値を分けて評価する

Indicoへの掲載や著名な諮問委員名だけを保証として扱わない。過去の登壇者・実験
グループ自身の活動記録など、運営サイト外の一次資料で参加実績を裏取りする。
実開催の裏付け、今年の登壇者、研究テーマとの適合、運営・返金条件、会議録投稿の
義務や追加費用は別の論点。実体のある会議でも、今年の交流価値まで確定はしない。

## <a id="itinerary-quote-comparison"></a>8. 渡航費は同じ旅程条件で比較する

出発日だけでなく、現地到着日・現地を出る日・日本帰着日を固定して比較する。
水曜現地発でも日本着が木曜になる旅程を、水曜帰国便と同列にしない。安価でも
長時間乗継や別の必要宿泊が増えるなら、その条件を金額の横に示す。
検索例の日付を実際の訪問可能日と混同せず、曜日変更は招待者との調整事項として残す。
総額・通貨・税/燃油・手荷物・変更/取消条件・取得時点・販売元を確認し、広告の最安値や
片道区間額を、選択した往復便の確定総額として報告しない。費用の安さと研究費への
支出適格性も別であり、予算枠をそのまま未拘束残額と扱わない。
