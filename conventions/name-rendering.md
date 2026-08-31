<!-- doc-meta
when: 人名を記録・文面・印字物に書く瞬間で、手元にある表記が機械 field (メールヘッダ / git author / CSV・LDAP export / 登録システム) 由来のとき
category: harness-core
summary: transliteration・正規化された人名 field は不可逆な投影 — 手元に無い表記形 (native script / 濁点・記号 / 漢字) を推測で復元しない。3 択 (権威 source から取る / 本人に聞く / その表記を使わない) + 高 stakes 印字物の照合 + 確定後の SoT 化と errata
-->
# 人名表記の復元禁止 — transliteration は不可逆

機械 field に載っている人名は、**元の表記を正規化して落とした投影**であって元の表記そのものではない。投影は不可逆なので、**手元に無い表記形を推測で作ってはいけない**。

## <a id="lossy-name-fields"></a>なぜ復元できないのか

人名 field は経路のどこかで必ず正規化される。代表的な情報落ち:

| 落ち方 | 例 | 復元不能な理由 |
|---|---|---|
| ローマ字化 | `Hanako` | 対応する native 表記が多数存在する (日本語の名は同じ読みに何十通りもの漢字が当たる)。姓も同様に異体字を持つ (Sai → 斉 / 齋 / 齊) |
| 記号の平坦化 | `Jose` / `Muller` | José / Müller のどちらが元かは field から決まらない。ASCII 折り畳みは戻せない |
| 字系の転写 | `Dmitry` | Dmitri / Dmitrii など複数の転写規則があり、逆変換は一意でない |
| 姓名の順・大文字化 | `Hanako YAMADA` | 全大文字が示すのは**どちらが姓か**だけ。字系・字体については何も言っていない |
| その他 | 頭文字化 / 切り詰め / 戸籍名 vs 通称 / 改姓前後 | いずれも情報を捨てる方向の変換 |

⚠️ **逆方向も同じく不可逆**。native 表記からローマ字表記を作るのも推測で、同じ姓の漢字に複数の読みがあれば当てられない。「読めるから書ける」は成り立たない。

## <a id="no-name-reconstruction"></a>規律: 手元に無い表記形は作らない

推測で埋めず、次の 3 択のどれかを取る。

1. **権威ある source から取る。** 強い順に、**本人の署名・自己申告 > 所属機関の公式サイト・公式名簿 > 本人の出版物の著者名 > 第三者による言及**。第三者言及は最弱で、それ自体が同じ推測を経ている可能性がある。
2. **本人 (または確実に知る人) に聞く。** 名前は本人が正本を持つ数少ない fact で、聞くコストは常に誤記のコストより安い。
3. **その表記を使わない。** 手元にある形のまま書く (= ヘッダの英字表記をそのまま引く)、または名前を避けた書き方にする。**「分からないので書かない」は正当な選択肢**であって、埋めなければならない空欄ではない。

推測した表記を「たぶんこれ」と括弧なしで記録に書き込んだ瞬間、それは後続の全 readout にとって既成事実になる。

## <a id="name-printing-stakes"></a>高 stakes: 物理的に残る / 対外に出る印字

**招待状・案内状・賞状・名札・記念品・著者名・credit・振込先・名簿**では、誤記が刷り直しや対外的な失礼に直結する。ここでは推測混入を絶対に許さず、**印字の直前に正本と 1 回照合する**。

これは [paper-audit.md](paper-audit.md) の投稿前検査や [office-automation.md #print-preflight](office-automation.md#print-preflight) の刷る前検査と同じ位置にある gate — 不可逆な出力の手前に検査を置く。

## <a id="name-sot-once"></a>確定したら SoT 化して掃討する

正しい表記が確定したら、その場の修正で終わらせない。

1. **正本を 1 箇所に置く** (連絡先 doc の当人 entry 等) — 以後の参照は全て pointer。表記の根拠 (誰の明示か / 公式サイトの何を見たか) も併記する。
2. **誤形を全 record で grep して掃討する。** 1 箇所直して終わりにしない。推測由来の誤記は複製されている前提で探す。
3. **誤りの記録は削除でなく errata で残す** (= [convention-design-principles.md #errata-on-preserved-records](../docs/convention-design-principles.md#errata-on-preserved-records))。「どこから誤ったか」が残らないと同じ経路で再発する。
4. 掃討後に残る誤形の出現は「これは誤記だった」という errata 記述**のみ**であること — grep 結果をそこまで確認して初めて掃討完了。

## <a id="name-rendering-evidence"></a>再発 evidence (genericized)

- メールヘッダの `<given> <FAMILY>` 形式のローマ字表記から、運用記録の注記として native 表記を漢字で補った。名の読みに当たる漢字は多数あり、当てたものは誤りだった。**約 4 週間、誤形が唯一の内部記録として生存**し、その人物の記念行事 (= 案内状・記念品に名前を刷る計画) の起案時に表記の揺れとして表面化、本人由来の情報で訂正された。
  - 落ちた判断: ヘッダは「姓がどちらか」を伝えていただけなのに、**字系まで伝えていると読んだ**。公式サイトに正しい表記が載っており、1 回の参照で防げた (= 安価な検証を回さずに高価な失敗を選んだ形)。
  - 効いた点: 記録が 1 箇所に集約されていたため、確定後の grep 掃討で混入が 1 箇所と確定できた。

## <a id="name-rendering-mechanization-limit"></a>機械化の限界 (honest)

「この表記は推測か観測か」は自然言語 semantic で、hook / lint では判定できない (= [convention-design-principles.md #proxy-blind-spot](../docs/convention-design-principles.md#proxy-blind-spot))。実効的な構造対策は 2 つだけ:

- **正本 1 箇所 + pointer** (= 次回の readout を推測不要にする)。
- **確定時の grep 掃討** (= 既に散った誤形を刈る)。誤形が判明した時点では、それは検索可能な literal なので、ここだけは機械が効く。

「気をつける」は対策として弱い。名前を書く場面は多く、推測は書いている本人には推測に見えない。

## <a id="name-rendering-adjacent-kernels"></a>隣接 kernel

- **行為・発言の帰属** = [actor-attribution.md](actor-attribution.md) (= carrier proxy ≠ author)。**同じ family** — 記録 field は現実の lossy な投影で、逆変換を推測で埋めてはいけない。あちらは「誰の行為か」、こちらは「その人の名前はどう書くか」。
- **アウトリーチ宛先の身元 verify** = [research-email.md](research-email.md) (= その宛先が当該論文の著者本人かの corroboration)。「誰に出すか」であって「どう書くか」ではない。
- **identifier の取り違え** = [identity-in-config.md #homonym-author-id](identity-in-config.md) (= 同姓同名による author ID の誤同定)。表記でなく ID の同定問題。
- **日本語の敬称** = [japanese-email-honorifics.md](japanese-email-honorifics.md) (= 名前に付ける敬称の内/外規律)。表記が確定した後の話。
