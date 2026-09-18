<!-- doc-meta
when: 共同作業の成果物・記録・発言を特定の人物に帰属して報告・記録・文面化する前 (= commit author / 最終編集者 / メール送信者 / 議事メモの書き手 等の「運搬者」欄を見た瞬間) + 対外文書で第三者を名指しして誤り・訂正・批判・優先権を主張する文を書く瞬間 (= claim-target 軸) + 記録に「決定」「方針」「担当」 と書く瞬間 (= 決定の状態の軸、 #decision-state-at-record-time)
category: harness-core
summary: carrier proxy (= commit author / push 者 / 送信者 / 記録の書き手) を内容の判断主体・発言主体と等値しない — 帰属 5 規律 (proxy 種類の明示 / collaborative default = group product / inline marker = 宛先 tag / 発言者 ≠ 記録者 / load-bearing 帰属は複数 proxy verify) + claim-target 軸 (= 主張は誰についてのものか — 自己生成した名指しの無検証断定・内部略称の衝突展開) + 決定の状態の軸 (= 決定 / 提案 / 他 session の自己申告を記録の瞬間に確かめる、 両方向に壊れる) + 機械化不能の honest 限界
-->
# Actor / statement attribution — 行為・発言の帰属規律

共同作業の記録 (git log / 共同編集 doc / メール thread / 議事メモ / チャット) を読んで「誰がやった・誰が言った」を報告・記録する時の規律。核心 = carrier proxy を内容の判断主体・発言主体と等値しない。

## <a id="carrier-not-author"></a>問題の形: carrier proxy ≠ author

記録系は「運搬者 (carrier)」を 1 名だけ持つ欄 (= commit author、 送信者、 最終編集者、 メモの書き手) を必ず備えるが、 **その欄が識別するのは「誰がその記録を system に運び込んだか」であって、 「誰が内容を起草・判断・発言したか」ではない**。 carrier を author と読むのは運が悪い推測ではなく **表現形式の構造的限界を事実と取り違える category error**:

- collaborative editing では「commit author = 1 名」という表現構造自体が group reality を潰す lossy encoding。 会議で全員が議論しながら書いた 146 行も、 git 上は誰か 1 人の名前で運ばれる。
- 同じ repo で **author 欄は「どの経路が push したか」で変わる**: 本人の live 編集を coding agent が auto-push すれば owner 名になり、 web 側 sync bridge が押せば別名になる。 author 欄の多様性は判断主体の多様性とは別の軸。
- メール送信者 ≠ 意思決定者 (= 秘書送信 / 代理送信 / 合議の結果を 1 人が送る)。 議事メモの書き手 ≠ 発言者。

これは「単一情報源からの結論飛躍」の帰属 domain 形態: proxy が 1 個しか見えない時、 それを確定情報に昇格させる reflex が働く。 さらに narrative を先に組んでから証拠を当てはめると、 proxy の多様性 (= 複数 author が混在している事実) 自体を確認せずに単独 author 物語が走る。

## <a id="attribution-rules"></a>帰属 5 規律

1. **proxy の種類を明示して報告する。** 「X の編集」でなく「commit author = X (= push 者、 起草者とは限らない)」。 carrier 欄を報告文に写す瞬間に proxy 種を括弧で注記する — 断定形に落とすのはこの瞬間なので、 書式で塞ぐ。
2. <a id="group-product-default"></a>**collaborative context の default = group product。** live meeting での共同編集・共著 Overleaf・共同研究 repo では、 **単独 authorship を主張する積極的証拠がない限り** group product として framing する。 「1 人の名前で運ばれてきた」は積極的証拠ではない (= 上の lossy encoding)。
3. <a id="inline-marker-addressee"></a>**inline marker (`\red{[XX: ...]}` / `%% TODO(XX)` 等) = 宛先 tag 付き group to-do** であって「XX 個人への指令」「XX の担当宣言」ではない。 tag は「誰に見てほしいか」の routing であり authorship / ownership の主張ではない。
4. <a id="statement-attribution"></a>**発言の帰属: 記録の書き手・転送者・要約者を発言者と混同しない。** thread・議事・チャットの「誰が言ったか」が曖昧なら「〜の記録によると (発言者未確認)」と hedge する。 複数人会議 (Zoom 等) の指摘・発見を named collaborator 1 人に reflex で寄せない — 不明なら「全員で」or 確認。 ⚠️ <a id="stage-label-reads-as-speaker"></a>**「<人名> レビュー「…」」 のように段階名に人名を入れた句は、 「その人が担当した段階で出た評価」 とも「その人が言った」 とも読める** — 後の session は後者に読み替えて対外文面に使う (実測)。 引用を記録するとき、 発言者を確かめていなければ人名をどこにも置かず「〜という評価になった」 と書く。
5. <a id="load-bearing-verify"></a>**帰属が load-bearing な場面では単一 proxy から断定を書かない。** メール文面・論文 credit・attribution ledger 記入・対外報告など、 誤帰属が外に出る/固着する場面では、 **複数の独立 proxy で verify するか user に確認**する。 安価な 1 手 (= `git log --format='%an'` で author 欄の分布を見る / thread の別 message と突合) で高価な誤帰属を防ぐ。

## <a id="claim-target-attribution"></a>第二の帰属軸: claim-target (その主張は誰についてのものか)

carrier 軸 (= 誰がやった・言った) と直交するもう 1 つの軸: **claim-target = 主張の対象が誰か**。 「X らの計算の誤りを特定・訂正した」 型の文では、 行為の帰属 (訂正したのは我々) が正しくても **対象の帰属 (誰の・どの論文の誤りか)** が独立に誤りうる。 対外文書 (研究費調書・論文・rebuttal・推薦書・謝辞・メールでの他者言及) で第三者を名指しして誤り・訂正・批判・優先権を語る文は、 この軸の最高 stakes 面。

failure form (実測、 genericized):

- **自己生成した帰属は「検証済みの既知」 と同じ顔で出てくる。** retrieval 由来の fact と生成由来の補完は流暢さで区別できない — 特に説得文書では「具体名がある方が強い」 圧が名前の生成を促し、 生成された名前は書いた本人 (= 同 session の自分) にとって検証対象と認識されない。
- **内部略称の衝突展開**: グループ内略称・愛称 (2-4 文字) が同分野の著名研究者の姓の prefix と衝突すると、 対外文書化の瞬間に著名名へ「復元」 される。 実例: 共著者の略称が他研究者の姓と衝突し、 **自著論文の誤植訂正が「その研究者の論文の誤りを訂正」 に化けて提出文書に焼かれた** ([name-rendering.md](name-rendering.md) の姉妹 — あちらは表記の不可逆復元、 こちらは指示対象の不可逆復元)。
- **一次 distortion はしばしば名前より上流**: 「自著の誤植を訂正 (erratum)」 → 「先行研究の誤りを訂正」 の框のすり替えが先にあり、 名前はその框を埋める補完として後から入る。 名前だけ削っても框が残る (= 同事故では匿名版の同型文が別 2 箇所に併存していた)。

規律 (帰属 5 規律への追加 4 本):

6. <a id="named-claim-verify"></a>**名指し × {誤り・訂正・批判・優先権・反駁} 語彙の文を書いた瞬間 = 一次記録との突合 gate。** 検証は安価 (repo grep 1 発 / 文献 DB 1 引き): 名指しの姓が対象論文の著者 list に実在するか・自分側の記録にその人の誤りを発見した record が実在するかを見る。 実測の誤 gloss (「X ら = arXiv:NNNN」) は当該 arXiv の著者 list と 1 手で矛盾していた。
7. **内部略称は対外文書に出る前に正式名へ解決してから書く** (グループの中立識別子規約があればそれに従う)。 略称のまま生成に渡すと衝突展開の入力になる。
8. **検証できない名指しは削る** — 多くの場合、 真実 (自著の誤りを機械検証で検出・訂正した等) の方が主張として強い (instance rule = [kakenhi-proposal.md #mock-review-and-claims](kakenhi-proposal.md#mock-review-and-claims))。
9. **derived 文書間の帰属不一致を見つけたら、 解決方向は「互いに合わせる」 でなく「SoT に対して検証」。** 具体度が高い方を真とみなす specificity bias に注意 — 実測の増幅 mode では、 整合性 sweep が匿名で正しい記録を名指しの誤りに「特定」 して**裏付け文書を製造**した (= 整合性軸は内部無矛盾しか見えず、 coherent な誤りを捕まえられない)。

## <a id="decision-state-at-record-time"></a>第三の軸: 決定の状態 (それは決まったことか、 誰が決めたか)

carrier 軸・claim-target 軸と別に、 **記録に「決定」「方針」「担当」 と書く瞬間**に壊れる軸がある。 書こうとしている内容が次のどれかを、 その瞬間に確かめる:

- (a) **owner の決定** — owner の発言そのものを引ける (原文の動詞のまま書ける)
- (b) **提案・試稿・叩き台** — agent や協力者が出したもので、 採否は未定
- (c) **他 session の自己申告** — 別の agent session が名乗った窓口・担当・触らない範囲

両方向に壊れる (実測):

10. **決定でないものを決定として写さない。** 試稿に書いてある順序や、 他 session が名乗った窓口が、 次の記録では「決まったこと」 になる。 控える側の制約 (「編集しない」) ほど確かめずに受け入れられ、 言い換えで強まり、 「〜なので見送った」 という記録のたびに別の file へ写る。 board 上の形と読む側・書く側の規則 = [multi-session-coordination.md#board-role-claim-is-not-assignment](multi-session-coordination.md#board-role-claim-is-not-assignment)。
11. **決定を提案のまま置かない。** agent の提案に owner が同意した返事は決定であり、 同じ turn で決定の置き場に書く。 書き落とすと、 後で owner に指摘されるまで正本に無い。 決定か提案のままかが読み切れないときは、 記録する turn で owner に聞く (推測でどちらかに寄せない)。
12. **確かめる先は owner の発言そのもの。** 書いた agent 自身の報告や tool の説明文は、 自分の判断を「指示に基づき」 と書くことがある (実測)。 会話記録の user 役の発言を引く ([debugging-discipline.md#transcript-search-archived-and-quoted](debugging-discipline.md#transcript-search-archived-and-quoted))。
13. **置き場は 1 か所、 原文の動詞で。** owner の決定は決定を集める 1 か所 (設計 doc の決定欄・project の指示 file) に書き、 他の記録はそこを指す。 提案は「提案」「比較材料」 と明記する。 置き場が無いまま各所に全文で写すと、 出所が消えて後の読み手には (a) と (b)(c) の区別がつかなくなり、 訂正も写しの数だけ要る。

14. <a id="premise-provenance"></a>**原稿の headline を支える前提の文は、 出所と著者の確認状況を一次記録で引いてから論じる。** 前提の 1 文 (「現実の系では X ≪ 1」 型) が疑われたら、 物理を論じる前に、 誰がいつ書き、 著者がいつ何を確認したかを確定する。 前提が AI の起草のまま著者の確認を経ずに headline の根拠になっていた、 という型は (b) を (a) として扱った記録の一種である。
    - **初出**: `git log -S '<前提の文の特徴的な部分>' --format='%h %ad %an | %s | %(trailers)' -- <原稿>` は出現回数が変わった commit を並べる (最古 = 初出、 最新 = 撤去)。 整形で文が変わっていれば短い特徴語で引き直す。 `-S` は回数の差しか見ないので移動は見えない ([`overleaf-integration.md#push-sweeps-editor-edits`](overleaf-integration.md#push-sweeps-editor-edits) の注)。
    - **書き手**: git author は commit した account であって書き手ではない。 `Co-Authored-By` と session trailer ([`multi-session-coordination.md#session-provenance-trailer`](multi-session-coordination.md#session-provenance-trailer)) で agent を読む。 trailer の付き始めより前の commit は「trailer 無し = 人の commit」 と読まず、 件名の癖・掲示板・会話記録で判定して根拠を書く。 付き始めの commit を証拠の境界として記録する。
    - **どの clone で作られたか**: 手元の reflog に `commit:` として現れるか、 fast-forward の範囲で届いたかを見る。 fast-forward の行は着地点しか出ないので、 `git merge-base --is-ancestor <commit> <着地点>` を直前と直後の着地点に当てて範囲を決める。 範囲で届いたなら別の clone (別のマシン・別の checkout) で作られた。 reflog は clone ごとで期限もあるので、 見えないことは不在の証拠にならない。
    - **確認状況**: review 台帳で、 前提を含む節を誰がいつ確認したかを引き、 「式の整合を確認した」 と「前提が現実の系に当たるか確認した」 を分けて書く。 前提が一度も著者の確認を通っていなければそう明記する。 headline の変更そのものの扱いは [`manuscript-claim-ownership.md`](manuscript-claim-ownership.md)、 前提を lab の量で検算する手順は [`paper-audit.md#regime-premise-in-lab-quantities`](paper-audit.md#regime-premise-in-lab-quantities)。

## <a id="attribution-evidence"></a>再発 evidence (genericized)

- 共著物理論文の Overleaf git mirror を pull し、 単一 commit author の 146 行更新を「その人の update」と単独 narrative で報告 → 実際は会議で共著者全員が live 編集した group product (user 訂正 1)。 再 framing 後も、 同日朝に owner 名義の commit 20+ 本 (= owner の live 編集を coding agent が auto-push した分) が並んでいる事実を git log で確認しないまま narrative を維持 (user 訂正 2)。 **1 incident 内で規律 2 (group default) と規律 5 (proxy 分布の安価な確認) を連続で落とした**。
- 複数人 Zoom review の指摘を named collaborator 1 人に一括帰属 → user 訂正 → **同 session 内で再発** (= reflex bias であり単発 slip でない)。 以後その project は記録に「帰属: 両名」marker を明示する運用。
- 別 project では同型誤帰属 (共有 doc に書き下した人を式の originator と呼ぶ / 共著論文を 1 人の paper と呼ぶ) が繰り返され、 **project-local の attribution ledger** (= 対象 → 真の originator の表) が防御として作られた。 project-local ledger は当該 repo 内では効くが横断的には効かない (= 別 repo・別 domain で再発した) — 本 doc はその横断 SoT。

## <a id="attribution-mechanization-limit"></a>機械化の限界 (honest)

- 帰属判断は自然言語 semantic であり、 hook / gate / lint での機械 enforcement は不能 (= [convention-design-principles.md §8.8 (= #proxy-blind-spot)](../docs/convention-design-principles.md#proxy-blind-spot) の帰属 domain)。 narrative 規律 + human-steering (= user が誤帰属を捕まえる) が floor であることを honest に認める。
- 効く構造対策は 2 つ: (a) **帰属が繰り返し混同される対象は SoT 側に ledger を持つ** (= record の self-disambiguation、 次の readout を 1-shot 化)。 (b) **proxy 種の併記を書式にする** (規律 1) — 「気をつける」でなく、 carrier 欄を写す時の定型に proxy 種注記を焼き込む。

## <a id="attribution-adjacent-kernels"></a>隣接 kernel (別 domain、 混同しない)

- **実行経路・原因の帰属 (機械 domain)** = [debugging-discipline.md #execution-path-attribution](debugging-discipline.md#execution-path-attribution) (= 内容指紋で経路を確定 / control case で discriminate)。 対象が人でなく機構。
- **アウトリーチ宛先の身元 verify** = [research-email.md](research-email.md) §アウトリーチ前の身元確認 (= 宛先が論文著者本人かの corroboration)。 「これから接触する相手は誰か」であって「この記録は誰の行為か」ではない。
- **文献の著者名 verify** (= citation authorship の誤同定・hallucination) は帰属 family だが kernel は「未検証 identity の断定」 — 検証原則は規律 5 と同じ (複数 proxy / 一次資料 verify)。
- **役割の自己申告の board 上の形** = [multi-session-coordination.md #board-role-claim-is-not-assignment](multi-session-coordination.md#board-role-claim-is-not-assignment) (読む側・書く側の規則と表示時の注意)。 一般形は本 doc の [#decision-state-at-record-time](#decision-state-at-record-time)。
- **人名の表記** = [name-rendering.md](name-rendering.md) (= ローマ字化・記号平坦化された name field から native 表記を推測で復元しない)。**同じ lossy-encoding family** で、本 doc が「その記録は誰の行為か」、あちらが「その人の名前はどう書くか」。
