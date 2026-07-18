<!-- doc-meta
when: 共同作業の成果物・記録・発言を特定の人物に帰属して報告・記録・文面化する前 (= commit author / 最終編集者 / メール送信者 / 議事メモの書き手 等の「運搬者」欄を見た瞬間)
category: harness-core
summary: carrier proxy (= commit author / push 者 / 送信者 / 記録の書き手) を内容の判断主体・発言主体と等値しない — 帰属 5 規律 (proxy 種類の明示 / collaborative default = group product / inline marker = 宛先 tag / 発言者 ≠ 記録者 / load-bearing 帰属は複数 proxy verify) + 機械化不能の honest 限界
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
4. <a id="statement-attribution"></a>**発言の帰属: 記録の書き手・転送者・要約者を発言者と混同しない。** thread・議事・チャットの「誰が言ったか」が曖昧なら「〜の記録によると (発言者未確認)」と hedge する。 複数人会議 (Zoom 等) の指摘・発見を named collaborator 1 人に reflex で寄せない — 不明なら「全員で」or 確認。
5. <a id="load-bearing-verify"></a>**帰属が load-bearing な場面では単一 proxy から断定を書かない。** メール文面・論文 credit・attribution ledger 記入・対外報告など、 誤帰属が外に出る/固着する場面では、 **複数の独立 proxy で verify するか user に確認**する。 安価な 1 手 (= `git log --format='%an'` で author 欄の分布を見る / thread の別 message と突合) で高価な誤帰属を防ぐ。

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
