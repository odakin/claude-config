<!-- doc-meta
when: Indico (CERN 等) で運営される国際会議に abstract を投稿する・アカウントで詰まったとき
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
