<!-- doc-meta
when: 文書・code・hook・道具・設定・規則の文書を作る・変える実装に入る前 + 本人の名で出す文 (返信・返答書) の起草を頼まれたとき + 下請け (別 session の worker・subagent) に実装や起草を渡す依頼書を書くとき + 確認済みの方針が引かれていない実装の依頼を受けたとき + 実装を終えて本人に見せる前
category: harness-core
summary: 実装に入る前に方針を短く出して本人のフィードバックを受け、 その後に実装する大原則。 方針の段を立てる範囲と立てない作業、 方針の書き方、 文の起草の場合 (返信・返答書)、 下請けへの 2 段の依頼、 実装の後の照合、 実装の報告の書き方、 harness の既定との関係、 機械の網
-->
# 方針を先に出してから実装する (policy before implementation)

<a id="rule"></a>**実装に入る前に、 方針を短く出して本人のフィードバックを受け、 その後に実装する。** 実装 = 文書・code・hook・道具・設定・規則の文書を作る・変えること、 本人の名で出す文を起草すること。 方針 = 何をどこにどの形で作る・変えるか、 誰がやるか (自分か下請けか、 下請けならその重さ = model と effort)、 推す案とその理由 (比べた候補があれば 1 行ずつ)、 触らないもの、 既存の規則・仕組みとの食い違いとその言い直し、 本人に決めてもらうこと (1 項目 1 問いと推す答え、 3 つまで)。 方針の誤りは、 実装の後に見つかると実装ごと作り直しになり、 本人は成果物を読み通してから方針の誤りに気づく (実測: 方針の段で直された誤りは、 どれも入力の読み 〔相手の主張の意味・文献の中身・定義〕 の誤りで、 文の書き方の誤りではなかった)。 **方針の段は、 何でも本人に聞く段ではない**: 自分で決められる項目は推す答えのまま方針に書いて理由を添え (問いにしない)、 問いは本人にしか決められないものだけにする。 方針は 1 つの返事に項目を並べ、 確認の要る点を名指しして、 1 回の往復で出す。 確認の前は実装に手を付けない。 <a id="one-answer-is-not-approval"></a>**方針の中の 1 つの問いへの答えは、 方針の全体の確認ではない** = 答えが 1 問にしか来なければ、 答えを入れた方針の全体を見せ、 残りの項目の確認を取ってから実装する (実測: 素材の選び方の問いに答えが来た所で全体の承認と読んで試作まで作り、 本人に方針を先にと止められ、 残りの項目は退けられた)。 フィードバックを受けたら、 確認済みの方針を file に置き、 その turn で実装に入るか、 運ぶもの (その file と本人の確認の発言を引いた下請けへの依頼・期日つき TODO) に変える ([`multi-session-coordination.md#green-light-carrier`](multi-session-coordination.md#green-light-carrier))。 **実装の後は、 見せる前に、 成果物が依頼と確認済みの方針に答えているかを、 書いた者でない目で照合する** ([下の節](#post-implementation-check))。

## <a id="scope"></a>方針の段を立てる範囲

**本人が別の形を選びうる変更に、 方針の段を立てる。** 次のどれかに当たれば立てる:

- 入力 (相手の主張・原典・既存の仕組み・本人の過去の裁定) の読みに判断が入る
- 置き場所・形・名前・範囲に、 筋の通る候補が 2 つ以上ある
- 既存の規則・手順の意味 (何を止め、 何を許すか) を変える、 既存の文を言い直す
- 新しい仕組みを作る (file・script・hook・設定・定期実行・掲示板の項目)
- 複数の repo にまたがる、 公開 repo に載る、 他の人の手元に届く
- 本人の名で出す文で、 中身に判断を含むもの (答える・採否を決める・頼む・断る・約束する・事情を説明する)

<a id="no-policy-stage"></a>**方針の段を立てずに進める作業** (本人が別の形を選ぶ余地が無いか、 本人が既に選んでいるもの):

1. 記録 (SESSION の現在地・TODO・受領・返事の記録・ログ) と、 生成物の作り直し
2. 入力の読みが一意な機械的な作業: typo・リンク切れ・明らかな誤記の訂正、 決まった値の置換、 検査が指した形の直し (意味を変えないもの)
3. 本人の依頼の発言そのものが方針を言っているもの (「X を Y に替えて」「この案で」「断って」 = その発言を方針として記録に引く)。 <a id="fix-conflict-toward-owner"></a>規則・記録の食い違いを直す依頼は、 どちらの文に揃えるかの選択 = 本人の直前の発言から向きが一つに読めるときは、 その向きで直し、 向きを返事の 1 行目に書く。 向きの確かめの問い =「直した後、 本人が直前に求めていたことができるようになるか」。 できなくなる向きは本人の向きではない = 当てずに 2 案で聞く (実測: 本人の求めを断っていた agent が、 食い違いを自分の断りの側に揃えた = [`agent-rule-ownership.md#refusal-not-in-owner-rules`](agent-rule-ownership.md#refusal-not-in-owner-rules))
4. 確認済みの方針の続き (同じ方針の中の実装の残り、 検収で見つけた直し、 自分の確認で見つけた欠陥の直し = [`concise-output.md#fix-found-defect`](concise-output.md#fix-found-defect))
5. 読む・調べる・再現する・候補を作るだけの作業 (変更を伴わない。 方針の材料になる)
6. 本人が中身の判断を委ねた区画の中 (委ねた範囲の中だけ。 委ねた発言を記録に引く)
7. 壊れた状態を、 直前の自分の変更を戻して元に戻すこと (本当の直しは方針から)
8. 頼まれた中身と記録の事実だけで文が決まる短い返信 (受領の礼・日程の承諾・頼まれた書類の送付・記録にある事実の回答 = [下の起草の節](#drafting))

線を「本人が別の形を選びうるか」 に置く理由: 範囲を実装すべてにすると、 1 文の直しや記録にも往復が入り、 本人が「なぜこれを確認させるのか」 と返す形 ([`concise-output.md#no-reason-to-deviate`](concise-output.md#no-reason-to-deviate) の実測) が戻る。 選ぶ余地がある所だけに往復を入れると、 方針の誤りが起きうる所を覆う。 迷ったら方針の段を立てる (往復 1 回の損は、 作り直しの損より小さい)。

## <a id="how-to-write"></a>方針の書き方

- 上の [規則](#rule) の要素を、 1 項目 1〜2 行で並べる ([`concise-output.md#work-list-two-lines`](concise-output.md#work-list-two-lines))。
- 直す文は、 今の文と直した文を並べて見せる ([`concise-output.md#show-the-text-being-changed`](concise-output.md#show-the-text-being-changed))。 要約だけで聞くと「見せて」 と返って往復が増える。
- 推す答えから外れる理由の見当たらない項目は、 決めることとして並べない (推す答えのまま方針に書く = [`concise-output.md#no-reason-to-deviate`](concise-output.md#no-reason-to-deviate))。 本人に決めてもらう項目は [`concise-output.md#decision-questions`](concise-output.md#decision-questions) の形で書く。
- 並列の下請けの方針は、 揃うのを待たずに届いた順に見せる。 揃った後にまとめるときは、 何本にも共通の中身・違い・子が挙げた「決めてもらうこと」 の全件と採否を表にする ([`multi-session-coordination.md#parallel-collation-table`](multi-session-coordination.md#parallel-collation-table))。

## <a id="drafting"></a>文の起草の場合 (返信・返答書・共同研究者や編集者への文)

本人の名で出す文の起草も実装の 1 つで、 いきなり下書きを書かず、 先に方針を出して本人の確認を取り、 確認の後に起草する。 方針の 4 要素: (1) 答える論点と骨子 (何を主張し、 何を主張しないか) (2) 相手の主張の、 そのまま採る・言い直す・採らないの別と拠り所 (原典の頁・式、 文書の節。 確かめられなかったものは未確認と書く) (3) 返答の文の外で変えるもの (原稿・書類・予定) があるか (4) 本人に決めてもらうこと (1 項目 1 問いと推す答え)。 方針は短く書き、 答える先の元の文を同じ返事に見せる ([`concise-output.md#show-the-source-being-answered`](concise-output.md#show-the-source-being-answered))。 長い下書きを先に出すと、 本人は下書きを読み通してから方針の誤りに気づき、 下書きは方針ごと書き直しになる (実測: 下書きへの直しの多くが方針の段の誤りだった)。 範囲 = 中身に判断を含む文 (相手の主張に答える・採否を決める・頼む・断る・約束する・事情を説明する)。 頼まれた中身と記録の事実だけで文が決まる短い返信 (受領の礼・日程の承諾・頼まれた書類の送付・記録にある事実の回答) は、 方針と下書きがほぼ同じ文になるので、 全文を見せる段から始める。 確認の後に起草した文は、 これまでどおり全文を見せて送る OK をもらう。 共著者・編集者・referee に出す文で、 直しの案か他人の文についての言明を含むものは、 全文と一緒に照合票を見せる ([`rebuttal-letter.md#pre-send-verification-sheet`](rebuttal-letter.md#pre-send-verification-sheet))。 返答書を段落ごとに照合する事例 = [`rebuttal-letter.md`](rebuttal-letter.md)。

## <a id="delegating"></a>下請けに渡すとき

- **依頼を 2 段にする**: 方針だけを成果物にする依頼 (実装・下書きはさせない) → 依頼側が方針を検収し、 本人に見せて確認を取る → 確認済みの方針の file と本人の確認の発言を verbatim で引いた実装の依頼。 本人の依頼の発言そのものが方針を言っているときは、 その発言を方針として引き、 実装の段から始める。
- **下請けが書く方針の「決めてもらうこと」 の宛先は依頼側にする**: 依頼書に「本人に決めてもらうこと」 と書かせず、 「依頼側に決めてもらうこと (本人の裁定が要ると考えるものは理由を添える)」 と書かせる。 依頼側は検収で 1 つずつ、 決めるか本人に回すかを分け、 本人に見せるのは方針の確認の 1 回と、 本人にしか決められない問いだけにする ([`concise-output.md#only-owner-rulings`](concise-output.md#only-owner-rulings))。 下請けは本人とのやりとりを見ていないので、 本人が既に決めたことや依頼側が決められることも、 本人への問いとして書きやすい (実測: 下請けの方針の本人への問いを依頼側がそのまま中継し、 大半が本人に要らない問いだった)。
- **方針の段の下請けは最も重い effort で起こさない** (実装・起草の段が最も重い effort でも、 方針の段はその一段下。 方針は短く、 本人がすぐ直す前提。 実測: 方針だけの段を最も重い effort で起こし、 本人が一段下げた)。
- **依頼書に、 方針の段か実装の段かを書く** (実装の段なら確認済みの方針の file と本人の確認の発言、 方針の段を立てない作業なら [上の一覧](#no-policy-stage) のどれに当たるかと 1 行の理由 = [`multi-session-coordination.md#orientation-prepay`](multi-session-coordination.md#orientation-prepay))。
- **同じ仕事を何人かの下請けに並べて書かせるとき**: 並べる前に、 何の誤りを減らすために並べるかを依頼書に書く。 中身 (方針) が決まった後の文の起草は、 1 人が書き、 もう 1 人 (書き手と別の vendor) は書かずに方針と草稿を答える先 (referee など) の原文・共著者の原文と並べて疑う形を既定にし、 集約の表に何本にも共通の中身と少数意見の全件を残す。 理由 = 同じ材料・方針・点検を渡すと違うのは言い回しだけで、 比べは違う所しか拾わない (正本と理由 = [`multi-session-coordination.md#parallel-drafting`](multi-session-coordination.md#parallel-drafting))。
- **受ける側**: 実装を求める依頼書に、 確認済みの方針 (本人の発言の verbatim) も、 方針の段を立てない理由も書いていなければ、 方針だけを提出して止まり、 そのことを提出に書く。

## <a id="post-implementation-check"></a>実装の後の照合

成果物の各部分が、 依頼の問いと確認済みの方針に答えているかを、 書いた者でない目 (別の session・subagent) で照合してから見せる。 方針が正しくても、 実装が依頼に答えているかは別に崩れる。 書いた者の試験と、 直した箇所を 1 つずつ外す mutant が全部通った後でも、 書いた者でない目は、 書いた者が思いつかなかった入力の形で誤りを見つける (実測) = 照合は試験の言い換えでなく、 試験の知らない入力の形を探す段で、 試験が通っても照合は要る。 照合させる側は、 依頼と確認済みの方針と成果物を渡し、 結論は渡さない (渡すと照合が結論の確認になる)。 やり方の正本 = [`multi-session-coordination.md#delegate-output-inspection`](multi-session-coordination.md#delegate-output-inspection) / [`#review-handoff`](multi-session-coordination.md#review-handoff)、 見せる直した文を当てた形で検査に通すこと = [`concise-output.md#check-the-proposal-before-showing`](concise-output.md#check-the-proposal-before-showing)。 返答書を段落ごとに照合する形と、 共著者・編集者・referee に出す文 (直しの案か他人の文についての言明を含むもの) を送る前の照合票 (送る文面と一緒に本人に見せる) は [`rebuttal-letter.md`](rebuttal-letter.md) の事例 (照合票 = [`#pre-send-verification-sheet`](rebuttal-letter.md#pre-send-verification-sheet)) で、 この節はその一般則。 照合する目が下請けなら、 その下請けが他人の文について出した読みも、 原文と照らすまで仮説 ([`multi-session-coordination.md#delegate-output-inspection`](multi-session-coordination.md#delegate-output-inspection) の 3)。

## <a id="reporting"></a>実装の報告

「変えていない」「そのまま」 と書くのは、 単位 (文・段落の意味・式) を言うときだけにする。 文を変えずに間へ文を入れても、 段落の意味は変わる (実測: 文はそのままと報告した段落に、 間へ入れた文で意味が変わっていた)。

## <a id="harness-defaults"></a>harness の既定との関係

agent の既定の指示 (情報が揃えば動く、 承認を待たずに進む mode) は規則の文書ではなく、 この文書で変えられない。 本人の常設の指示がこの原則を置いているときは、 [範囲](#scope) の中では、 本人の方針の確認が「揃っているべき情報」 の一部になる。

## <a id="machine-nets"></a>機械の網

- **掲示板の worker の起動文**: 依頼が実装を求め、 確認済みの方針も方針の段を立てない理由も書いていないなら、 方針だけを提出して止まる、 の 1 文を起動文に入れる (worker が最初に読む文 = 届き方が最も強い。 検出器ではないので誤って鳴らない)。
- **掲示板の request の段の印**: 依頼側が request に段 (方針 / 実装 / 方針の段を立てない作業) を書き、 実装には確認済みの方針の引用か file を添える。 印が無い・実装に引用が無い request には、 投稿の出力に注意を 1 行出す (止めない)。 印の無い request では、 返信の起草を頼む語の検出が代わりに走り、 方針の段の無い起草の依頼を名指しする。 形と較正 = [`../../ai-collaboration/board/CONTRACT.md#policy-stage-check`](../../ai-collaboration/board/CONTRACT.md#policy-stage-check)。
- **turn 終わりの hook は置かない**: 実装の前に方針が出たかは、 返事の表面から見分けられない ([`concise-output.md#not-machine-detectable`](concise-output.md#not-machine-detectable))。

関連: [`docs/convention-design-principles.md`](../docs/convention-design-principles.md) §4 (行動の前に方位を取る。 その次の段が、 実装の前に方針を見せること) / [`agent-rule-ownership.md#additive-and-free-zones`](agent-rule-ownership.md#additive-and-free-zones) (規則の文書の変更にも方針の確認が掛かる。 規則を緩める変更の裁定はそれと別に本人)。
