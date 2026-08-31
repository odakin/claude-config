# 規約設計の原則
<!-- slug index: convention-design-principles.index.yaml — cross-ref sections by #slug (stable), not §-number. See §14.2 / §14.7. -->

CONVENTIONS.md・各リポの CLAUDE.md・メモリの設計判断の根拠を記録する。規約の追加・修正時にここを参照し、一貫性を保つ。

---

## <a id="placement-by-scope"></a>1. 規約の配置原則：影響範囲の最大公約数に置く

規約を書く場所は「その規約が必要とされる最も広い範囲」で決まる。

| 影響範囲 | 配置先 | 例 |
|----------|--------|-----|
| 全リポ・全端末 | CONVENTIONS.md | Git 規約、安全規則、作業開始手順 |
| 特定ドメイン・全端末 | conventions/*.md | MCP 手順、LaTeX 規約 |
| 特定リポ・全端末 | 各リポの CLAUDE.md | email-office のメール対応ルール |
| ローカル補助 | メモリ（~/.claude/...） | クイックリファレンス、行動矯正フィードバック |

**判断基準:** 「この規約がなかったら、別のリポ/別の端末で同じミスが起きるか？」— Yes なら上位に置く。

**アンチパターン:**
- メモリだけに書く → 他端末で再発する
- リポ固有の CLAUDE.md だけに書く → 別リポで再発する
- CONVENTIONS.md に何でも書く → 過剰規約で読まれなくなる

**pragmatic relaxation (bundle rule):** 「1 ルール = 1 ファイル」の厳格適用は 1 行ファイルを生む。**関連密接かつ合計 10 行未満のルールは bundle 可** (配置先は影響範囲の最大公約数に従う)。例: 個人層の project-structure.md は作業ディレクトリ宣言 + 配置ルール + preview リンク出力を 1 ファイルに束ねた (2026-04-06 の `~/Claude/CLAUDE.md` 解体時の判断、`claude-config/DESIGN-archive.md §~/Claude/CLAUDE.md の symlink 化` 参照 〔= 2026-07-10 DESIGN archive split で移動済〕)。

---

## <a id="no-duplicate-rules"></a>2. ルールの重複を避ける：定義は1箇所、他はポインタ

同じルールが複数箇所に書いてあると、修正時に全箇所を直す必要がある。忘れると矛盾が生じる。

**原則:** ルールの定義（WHAT/WHY）は1箇所だけ。他の箇所からはポインタで参照する。

```
CONVENTIONS.md §5.7 ← ルールの定義（WHAT: 確認せよ、WHY: 不可逆）
    ↓ ポインタ
conventions/mcp.md  ← 手順の詳細（HOW: alias 名 / list_calendars 等で account 確認）
    ↑ 参照
email-office step 0 ← 起動トリガー（WHEN: セッション開始時）
```

**各層の役割:**
- **CONVENTIONS.md**: WHAT と WHY（何を、なぜ）
- **conventions/*.md**: HOW（どうやって）
- **リポ CLAUDE.md**: WHEN（いつ、どのタイミングで）
- **メモリ**: クイックリファレンス（正本へのショートカット）

### <a id="sot-ranking-declaration"></a>2.1 自動検出が届かない format の fact には「SoT 序列表」を宣言する

anchor-token 型の drift 検出（md/yaml を scan する registry 方式）は、fact の正本や複製が **tex・PDF・code docstring** に住む場合に届かない。このとき防御は機械検出から宣言と運用規律に切り替える。

**Pattern（リポ CLAUDE.md に 3 列表）:**

```
| fact 群 | 正本 (SoT) | derived copy (drift 時は正本が勝つ) |
|---|---|---|
| <規約 fact の束> | <prose home>（+ regression = <検証 script>） | <複製箇所>（pointer 済） |
```

- **正本セルは「prose home ⊕ machine regression」の対**で書く: 人間が読む正本と、それを実行可能に検証する script を 1 行で対にする。どちらか片方では、prose が腐るか検証が形骸化する。
- **derived 側の各現地には subordination 文**（「正本は X、drift 時は X が勝つ」）を置き、表セル側にも「pointer 済」と明記する — 表だけが知っていて現地に印がない状態を作らない。
- **write-time discipline**: 新しい fact を文書に書く瞬間に「どの行の正本に属するか」を先に決める。audit-time の後片付けに回すと、片付く前に重複が複製される。
- scan 可能 format（md/yaml）の fact には従来どおり registry + 検出器が有効。序列表は**検出器の射程外を埋める手動宣言層**であり、置き換えではない（表の脚注に「この表が防御の本体」と射程を明記する）。

適用事例: 物理研究リポ einstein-cartan — 規約 fact（Fourier 規約・loop 符号則・1PI↔amplitude 写像など）が複数の tex note に必然的に再掲される構造に対し、リポ CLAUDE.md に 5 行の序列表を宣言（2026-06-12）。導入動機は、誤推定 1 個が 3 つの note に伝搬した事故。

### <a id="sot-declaration-collision-sweep"></a>2.2 正本の宣言・引っ越しは「衝突宣言 sweep」とワンセット

正本を新しく宣言する、または別の home へ移すと、**その瞬間に旧 home・index・tree 行にある「これが正本」という記述が stale になる**。この staleness の発生を知っているのは宣言を編集した本人だけであり、同 commit が唯一安価な処理タイミング — 後続の audit は「2 つの宣言のどちらが新しいか」をそもそも知らない。

**Reflex:** 正本の宣言・移動を含む commit には、fact の keyword ×（正本|SoT|authoritative）の **repo 横断 grep を同梱**する。最高信号の drift は「**2 箇所が同時に正本を名乗る**」状態（どちらかが必ず stale）。markdown 表の row を部分差し替えしたときは列数も数える（旧セルの尻尾残存で列崩れしやすい）。

適用事例: 2026-06-12、同一 session 内で 2 連発 — ① 序列表は note を正本へ更新したのに script の tree 行が「script が SoT」のまま残存、② row 差し替えで旧 derived セルが残り 3 列表が 4 列化。どちらも宣言 commit 直後の grep + 目視で検出・修正。編集者本人の直後 sweep 以外に拾う仕組みがない型。

**use-site の stub 規律（= 宣言の双対）:** fact の正本を宣言したら、それを*言及するだけ*の他の use-site は「最小安定警告 + pointer の stub」にする — volatile な詳細（係数・出典・erratum・手順）を copy せず正本だけに置く（詳細を copy した瞬間に新たな重複が born する）。point-of-use marker は (a) 発火に要る最小・安定・行動可能な警告 + pointer と、(b) 発火に不要で drift する詳細 payload に分解でき、use-site が要るのは (a) だけ。これは §16「正本本体は source の逐語」の反転 dual =「derived な use-site は最小要約 + pointer であれ」で、詳細の home を 1 つに保ったまま fact を point-of-use で発火させられる（= 発火と SoT 単一性は両立する、「自己完結 marker が詳細 copy を強制する」は false dilemma）。最高 leverage の発火面は宣言が born する commit 時点（= 機械化できるなら commit-time の declaration warn）。

### <a id="sot-read-side"></a>2.3 SoT の read 側 — entity を「言及するだけの store」を SoT と取り違えない

§2.1/§2.2/§15 は **write 側**（正本を二重に*作る*な・宣言の衝突を sweep せよ・多重記述を是正せよ）。SoT には **read 側の双対**がある: ある案件の status を答えるとき **その案件の SoT を読む** — その entity を*言及するだけ*の別 store（受信メール・領収書・通知・log）を SoT と取り違えてはならない。

一つの実世界 entity は多数の store に現れる（ある予約はメール・PDF・チャット通知・業務台帳に出る）。**特定の案件について authoritative なのは 1 つだけ**で、他は **source document**（SoT が cite する材料）にすぎない。さらに **SoT は自分が制御する内部 store（grep 可能・durable・自分の repo）でなければならない**: 外部サービス（予約サイト・vendor portal 等）とそれが送ってくる通知・領収書は、変化・喪失・stale がありこちらが制御できないので **SoT たり得ない external source**（先方の system-of-record であっても、こちらから見れば snapshot にすぎない）。必要な fact は内部 SoT に **absorb** する — 外部 fact を内部にコピーするのは二重 SoT ではない（外部は元々 SoT でない）。**source document・external source の沈黙・null は案件の答えではない。** ＝「二重 SoT」は多くの場合*存在しない*: 内部の非 SoT store / external source と正しく分類すれば内部 1 SoT に解消する（design-out であって reactive 管理ではない）。

**Reflex（read 側）:**
- 「〜は済んだ?／頼んだ?／どうなってる?」型の **matter-status 質問**には、手近な source document だけで即答せず **その案件の SoT を読んでから**答える。
- **session 開始時、context window はその案件について空の cache**。会話に流れてきた情報や直前に fetch した 1 store を「知っている＝真実」と扱わない。SoT は disk 上にあり、取りに行くのは option でなく前提。
- source document を読んで見つからない時の第一仮説は「案件が無い」でなく **「SoT を未読／読む store を間違えた」**。null は世界の事実でなく「探す場所が違う」証拠。

write 側「one fact, one home」（[`personal-layer.md`](personal-layer.md) §publish-boundary の partition / MOVE-not-copy）と対で、read 側は「one matter → read its single SoT」。**二重 SoT を*作らない*のと source document を SoT と*読み違えない*のは同一原則の両面。**

origin: 2026-06-13 — ある案件（出張の宿泊証明）の status を問われ、会話冒頭で見ていた source document（個人アカウントのメール通知）を SoT と取り違え、その null から「未対応／記録なし」と結論 + 不在を説明する誤った root cause を作話。実際は別 SoT（業務台帳）に完全記録済で 1 grep の距離にあった。write path（記録）は完璧、read path（SoT を読む）が崩れた型。同日 sibling = 横断 lookup を要する案件で SoT 直読より手近 store を先に見た失敗（§8.11 / §8.12 と同根）。layer-3 機械対策 = source store を業務 query で検索したら正しい SoT へ routing する guard + matter-status を SoT-read に乗せる dispatch（instance は layer 3 archive 残置 = kernel-up / instance-down）。

### <a id="errata-on-preserved-records"></a>2.4 削除できない誤り記録には errata marker を残す

§2.2 は「正本を移したら旧 home の stale な正本宣言を sweep せよ」。その sweep で見つかる誤り記述には **削除できないもの**がある — その記述自体が**忠実な履歴**であることに価値がある記録（送信済メールの draft、監査証跡、過去に「誰に何を聞いたか」の打診記録、当時の判断ログ）。これらには 3 つの選択肢がどれも単独では成り立たない:

- **削除**すると記録が falsify される（「何を送った／聞いたか」が history から消える）。§7.2「DESIGN.md は削除、git log が履歴」は当てはまらない — そこでは entry の価値 = decision で、pedagogy を新 entry に抽出後は本体不要だが、**履歴記録は entry 自体が成果物**。
- その場で**内容を書き換える**と、後から事実を改変した捏造記録になる。
- かといって**黙って残す**と、誤った旧記述が「現在の真実」として読まれ続ける（数か月後の reader / fresh session が現行 rule と取り違える）。

→ **errata marker を付ける**: 本文は当時のまま温存し、直近に `⚠️ errata (日付): これは誤り（= 当時の暫定）。正は X〔pointer〕。本記述は履歴として保持` を添える。本文（何を考え／送り／聞いたか）と訂正（それが誤りと今わかる）の**両方**を後から読めるようにする。

### <a id="sot-duplication-trichotomy"></a>2.5 SoT 重複の 3 つの扱い (design-out vs reactive) — 成熟度で分類し、検出器を「未 design-out の症状」と読む

§2.1-2.4 / §15 / §8.11 は個別の戦術。その上位の戦略 frame: **同じ事実が複数 file に要るとき、扱いには 2 つの安定形と 1 つの不安定な中間がある。**

- **(A) 完全正規化** — 事実の home は 1 つ、他は pointer/view。重複ゼロ → drift 原理的に不可能 → 検出器不要。コスト = 単体可読性 (1 file で完結) を失い、pointer を辿る join が要る。§2.1 序列表・§2.2 stub 規律・§15 consolidation はこの (A) を実現する戦術。
- **(B) 完全非正規化 + 生成** — 派生 file は重複してよいが、**generator が単一 SoT から再生成** (手編集禁止)。派生は生成物ゆえ drift 不可能。
- **(C) 非正規化 + 手編集 + 規約 + 検出器** ← **不安定な中間 = 「両方の悪いとこ取り」**。重複あり (drift risk) ∧ 手編集 (drift が実際起きる) ∧ 検出器 fleet (保守コスト) ∧ 所有権ルールの認知負荷。

**戦略 = 事実を (C) から (A)/(B) へ寄せる。** drift 検出器を保守しているなら、その存在自体が「その事実がまだ (C) にいる」症状 (§8.11: leverage は上流の design にあり、下流に検出器を足し続けるのは whack-a-mole)。

**防御の序列 (= drift をどの層で止めるか、 強→弱; §8.12 発火面 hierarchy の SoT 版で、 最上段は「発火しない」):**

| 層 | 機構 | drift への効き方 | 強さ |
|---|---|---|---|
| ① design-out | (A) 正規化 / (B) 生成 | **起こさせない** (重複が author されない / 派生は生成物) | 最強・構造的 (発火不要) |
| ② commit-time 規律 | §2.2 衝突宣言 sweep + declaration warn hook | 生まれた瞬間に捕える | 中 (write 時、 hook + recall 依存) |
| ③ continuous 検出 | check-sot-drift + registry (= drift-patch 検出器) | 後追いで surface | 弱 (ambient、 登録 topic のみ = §8.8 blind-spot) |

上段ほど強い。 ③ は ①② をすり抜けた登録済 topic の後追い網であって、 frame の goal は「事実を ① に寄せて ③ を要らなくする」 (= §8.11 leverage は上流)。

**成熟度 lens (事実を type で分類して design-out 手段を選ぶ):**

| 事実の type | design-out 手段 | drift 耐性 |
|---|---|---|
| 派生データ (= 他 file から導出可能) | (B) whole-file 生成 (mirror / overlay 再生成) / (A) field-level view (= 導出可能な field は書かず read 時に key から導出、 手編集 file 内の単一 field でも適用可) | ✅ 構造的に不可能 |
| 散文・知識 (規約 / RCA / reference) | (A) 1 home + pointer (§2.1 / §15) | 〜成熟 (pointer 規律次第) |
| 運用台帳・相互参照 state (= tracker ⇄ linked record / id・日付の多重コピー) | (A) view 導出 or (B) 編集時 gate | ❌ (C) に居残りやすい最難 |

派生データと散文は design-out 手段が確立しやすい。**手編集される運用台帳 (= 人が複数 store に同じ state/id/日付を書く) が (C) に残る最後の領域**で、drift 多発源。

⚠️ **「散文・知識」 row は外見で決めると mis-classify する。** 行を分ける真の軸は外見でなく **「SoT が prose 自身に住むか、別所に住み prose はその mirror か」**:
- **prose が home そのもの** (規約の定義 / RCA の結論 / reference 値) → 複製は use-site への必然再掲のみで、prose に transclusion primitive が無い以上 **構造的 ceiling**。「〜成熟」 は楽観でなく天井 (= §2.1 stub + human sweep が available な最善)。
- **prose が別所の state を mirror するだけ** (status field「✅/🟡」 / 一覧が実 directory を映す / version 数が code を映す / 進捗 % が実作業を映す) → SoT は prose に無く別所 (実状態 / 生成元 / code) に在る = **散文の顔をした「運用台帳」 row** で design-out 可能 (生成 / 編集時 gate / view 導出)。これを「散文ゆえ〜成熟」 と読むと **over-rate** する (= 未 design-out を「成熟」 と誤認)。人的 drift 機構は §4.1 (ii) under-execution の *change-time* facet (= state 変化時に mirror の更新を 1 つ脱落、creation 時に全 home へ複製する重複の双対)。

診断: 重複 prose fact を見たら **「直すべき唯一の正しい値は *この prose 内* で決まるか、 *別所* を見ないと分からないか」** を問う。後者なら散文でなく運用台帳として扱い design-out へ寄せる。

origin (この refinement): 2026-06-25 — 同一内容を複数 doc に複製する重複 (creation 時) と、doc が映す運用 state の更新漏れ (change 時) が複数 domain で再発した分析。「散文 → 〜成熟」 評価が prose-home には honest・prose-mirror には optimistic と判明 (= 後者の正しい home は運用台帳 row の design-out track)。どの台帳がどちらかの application は instance ゆえ layer-3 (kernel-up/instance-down)。

**検出器 fleet の仕分け (= 全部が消せるわけではない):**
- **drift-patch 検出器** (= 同じ事実の不整合を後追い検出: set 差分 / 非対称 cross-ref / 散文重複) → **design-out で不要化しうる側**。(C)→(A)/(B) が進むと縮小する。
- **surfacing 安全網** (= 見落とし防止: 締切 horizon / 未 triage / 到着検知) → **正当に永続**。「重複の drift」でなく「対象の見落とし」を見るので design-out 対象外 (= 別 domain)。

**正直なトレードオフ (= 「全部 normalize」が誤りな理由):** (A) は単体可読性を犠牲にする (1 file を読めば案件が分かる、が壊れる)。非正規化はしばしばその可読性のための意図的選択。ゆえに **事実ごとに「可読性をどこまで犠牲にして重複を消すか」を選ぶ**のが設計の本体で、多くは **機械化できない判断 = home owner が決める** (Claude が reflex で「全正規化」に倒すのは誤り)。

origin: SoT 重複が複数 domain で再発する構造を一般化 (2026-06-21 hoist)。§2.1-2.4/§15/§8.11 が個別戦術として散在し、それらを束ねる「reactive 管理 (C) を design-out (A/B) へ寄せる」戦略 frame + 成熟度 lens + 検出器の仕分けが layer-3 plan にしか無かった。application (= ある運用系のどの台帳がどの tier か) は instance ゆえ layer-3 に残置 (kernel-up / instance-down)。

判別フロー: **正本そのものの誤り → 本文を是正**（§2.2、marker でなく書き換え）/ **削除可能な決定記録**（価値が別所に抽出済 + git が履歴を保つ）**→ §7.2 で削除** / **削除不能な忠実履歴**（falsify せず残す要）**→ 本節 errata marker**。errata marker は「保持必須の非正本記録」専用で、正本や DESIGN.md entry には使わない（§7.2「※注釈で本文温存しない」と矛盾しない — 対象が別物）。

origin: 2026-06-18 — 研究費様式の交通費記入ルールを是正した session。確定版を SoT（規約 md）へ書いた後も既存 TODO 2 件が旧暫定を live で肯定していた（= §2.2 sweep で発見し本文是正）。加えて**削除できない履歴**（事務担当宛の送信済メール draft / 過去の打診記録）に旧暫定が残り、こちらは是正でなく errata marker で「当時の誤り」を明示し本文は温存した。user 指摘「過去の誤った判断・知見には『これは誤り』とあとで分かる注を、上層で規律化してよい」。

---

### <a id="time-decaying-fact-authoring"></a>2.6 時点依存 fact は undated 断定で書かない — 「環境が変わると偽になる文」の authoring 規律

**問題**: 環境依存の fact (= model / サービスの可用性・lineup、 tool の版挙動、 手動の「最終更新」日付、 config 例への現行値 hardcode) を **undated の断定形**で doc に書くと、 世界が変わった瞬間に doc が silent に嘘をつき始める — 誤りとして書かれたのではなく、 **正しかった文が読者の時点で偽になる** (= [§2.4](#errata-on-preserved-records) errata の対象になる前の、 予防可能な段階)。 断定形は読み手 (別 session の Claude を含む) に検証を skip させる力があるため、 stale 化した断定は能動的に害する。 実例 (2026-07-10、 同日に同 class 3 instance): 「この model は本環境で選択不可」 という断定が可用化後も数週間残り、 まさにその環境で動く session の選択を歪めた (= 環境自身が反証を持っているのに文が勝った) / config 例に現行 model id を hardcode (= 世代交代で必ず rot) / 手動「最終更新: <date>」 が 3 ヶ月 stale で本文と乖離。

**cure (強い順)**:

1. **design-out** — その fact を書かず**導出**する (= 日付は git log / 一覧は generator / 現行値は実行時取得)。 手動日付・手動 mirror は「削除が最善の更新」。
2. **時点 + 検証方法の併記** — 「2026-07 時点で X (確認: `<command>` / 実測 n=…)」。 読者が「今も真か」 を 1 手で再検証できる形にして、 断定の賞味期限を可視化する。
3. **use-time verify への書き換え** — 「X である」 でなく「X かどうかは `<手順>` で確認してから」 — fact を運ばず**手順**を運ぶ (= 陳腐化しない)。

**書く瞬間の問い**: 「この文は世界のどの変化で偽になるか? 偽になった時、 読者は気づけるか?」 — 気づけないなら cure 1-3 のどれかに変形してから書く。 read 側の対規律 (= 手順書の記述を陳腐化前提で疑う) は各層の作業規律側、 本節は **write 側** の SoT。

---

## <a id="rule-addition-criteria"></a>3. 規約追加の判断基準：「規約がない」のか「規約を読まない」のか

ミスが起きたとき、反射的に規約を足したくなるが、まず原因を切り分ける。

| 原因 | 対策 | 例 |
|------|------|-----|
| 規約が存在しない | 規約を追加する | §5.7 MCP アカウント確認 |
| 規約はあるが読まれていない | 既存規約の適用条件を明確化する | §3 作業開始手順の拡張 |
| 規約はあるが手順が不明確 | HOW を具体化する（conventions/*.md） | mcp.md の手順詳細化 |
| 暗黙の手順が明示されていない | チェックリスト化する | email-office 完了時チェック |

**過剰規約の害:** 規約が増えるほど読まれない確率が上がる。「規約を読め」という規約は自己参照であり解決にならない。規約追加は最終手段。まず既存規約の強化・明確化を検討する。

---

## <a id="orient-before-act"></a>4. Orient before act（行動前に方位を取れ）

2026-04-02 のインシデント分析から抽出した行動原則。

**問題のパターン:** タスクが「簡単に見える」とき、事前確認（リポ特定、CLAUDE.md 読み込み、規約確認）をスキップして即座に実行に入る。結果、ユーザーの確立されたシステム（データの配置先、操作手順、記録フォーマット）を無視し、手戻りが多発する。

**構造的原因:** AI は「速く役に立つ」ことに最適化されているため、事前確認を「遅延」と認識しがち。しかしユーザーのシステムが整備されている環境では、事前確認こそが最速経路。

**対策の設計:** この原則は CONVENTIONS.md §3 の作業開始手順に組み込んだ（「簡単なタスクも例外ではない」）。行動原則を独立したルールにせず、既存の手順に条件を追加する形にした理由は、§3 の原則に従えば自動的にこの問題が防がれるため。新しい概念を導入するより、既存の仕組みの適用範囲を広げる方が認知コストが低い。

**Evidence (2026-06、 1 instance)**: scan PDF への text overlay 作業で「ベスト推測→user 確認→補正」 のループを 7+ rounds 反復、 session 中盤で初めて回した既存手順 (= 試験 PDF での bbox 実測 + 罫線・文字の pixel 差分分離) で短時間収束。 着手時に layer 1 doc を grep していれば見えた経路 ([`pymupdf-insert-text-baseline`](../conventions/office-automation.md#pymupdf-insert-text-baseline) + [`scan-pdf-pixel-anchor-overlay`](../conventions/office-automation.md#scan-pdf-pixel-anchor-overlay)) で、 CONVENTIONS.md §3 の事前確認 step が recall 依存ゆえ in-context に表象されない瞬間に発火しなかった本節 pattern の direct instance (§8.12)。 「行動原則を独立せず既存手順に組み込む」 設計選択は本失敗を *減らす* が *消さない* — ambient に乗せた条件は recall に依存し続けるため、 firing surface の最弱面 (§8.12) が再演する。 detailed instance は layer-3 plan に sequester (= 層 1 → 3 hardlink 禁則、 §1)。

### <a id="motivated-substitution-trap"></a>4.1 指定された成果物・手段から逸脱する時の self-justification trap（motivated substitution）

タスクが**特定の成果物・手法を名指す**とき（「X を実装して」/ plan に「手法 Y」と明記 等）、より一般的・印象的・自分好みの別手法が思い浮かぶと、LLM は**逸脱の正当化を後付けで製造**しやすい。起点は「目標（outcome）」を最適化して「指定された手段（named deliverable）」を交換可能と見なすこと。§4 の「orient before act」が *事前確認のスキップ* を扱うのに対し、こちらは *（誤って）orient した後に、別物へ静かにすり替える* failure。

**なぜ特に危険:** 逸脱先がしばしば本当に有用な副産物を出すため「良い判断だった」と誤学習する。正当化は粘り、**事後分析（post-mortem）まで生き残る**（「でも技術的には正しかった」という逃げ道として）。silent な置換は依頼者が気づいて差し戻す手間を生み、「X をやる」と言った時に毎回成果物を検証させる＝信頼の侵食。判断自体が良くても、**黙って差し替えた**ことが failure。

**正当化に頻出する欠陥（逸脱を信じる前の自己尋問）:**
1. **strawman 比較** — 代替を、指定手法の*本物*でなく、その劣化版（＝一番手近な naive 実装）と比べていないか？（最頻出。「本物はもっと良い／同じ利点を持つ」を見落とす）
2. **輸入された美点** — 代替の「利点」は*この課題*の利点か、隣の課題から借りてきた非問題の解決か？
3. **別の問いへのすり替え** — 代替は*指定された問い*に答えるか、自分が好きな別の問いに答えているだけか？（しばしば指定タスクを解いてすらいない）
4. **impressiveness バイアス** — 手法を「結果が definitive／publishable になりそう」で選んでいないか？（課題適合でなく見栄えの最適化）
5. **deliverer-retention（届ける主体でいたい）バイアス** — 代替は、自分が *成果物の author・結果の deliverer であり続けられる* 方を選んでいないか？ 指定物がその役割を**別の場所へ渡す**もの（独立した worker、別の durable home、依頼者自身）なら、役割を手放したくない動機が静かに働く。

**対策:**
- **名指しされた成果物は load-bearing として扱う。** 着手前に「タスクは "X"」と*名前で*再唱し、自分の plan が **outcome 一致でなく name 一致**かを照合する。
- **より良い案があるなら「置換」でなく「併設＋明示」。** 指定物を出す＋代替を理由つきで提示＋依頼者に選ばせる。silent に差し替えない。
- 検証規律（CONVENTIONS.md §3）/ §9.8（単一観察から構造対策に飛ばない）/ §8.14（単一一致で同定しない）と同族 = いずれも「安価な照合を先に回して、自分の飛躍を捕まえる」。

**深層 — 置換は「手近（available）」でなく「動機づけられている（motivated）」:** 浮かぶ代替が既定として選ばれるのは単に想起しやすいからだけではない。helpfulness 目的が *自分を author・deliverer に保つ* 選択肢を選好するから働く directional pull がある（例: 委譲で「結果が自分に返る subagent」を「結果が依頼者に渡る独立 worker」より選ぶ／ durable データの置き場で「いま書いているファイル」を「正しい SoT」より選ぶ）。ユーザーが名指す選択肢の load-bearing な性質はしばしば *自分を loop から外す*こと（独立性・別 home への authorship 移譲）で、それは動機が最も抵抗する対象。**重要な含意: 動機づけられた既定は recognition では止まらない** — 名前を読み直す reflex を持っていても、その失敗を主題にしている最も自覚的な状況ですら置換が起きる（観測事実）。失敗は推論が起動する*前*の pre-deliberative な選択の瞬間に済んでおり、事後に問われれば正しく区別できる。**だから対策は「気づく」でなく「手放す」:** 指定された選択肢が author／結果／制御を別の場所へ routing するものなら、その役割を *relinquish* する（hand-off する primitive を使い、自分が deliverer でなくなることを受容する）のが規律 action。recognition-reflex は §8.12（recall 依存 = 最弱発火面）と同じ理由で不十分 — **しかも本失敗クラスでは、引き金となる信号（ユーザーが手段を *明示的に名指した* 指示そのもの）が最強の信号であり、それが present な状態で既に override された**（= 名指された手段を取らず手近な既定に滑る失敗は、ユーザーの live な指示が在る最中に起きる）。ゆえに、そこから派生する reflex／doc／注意書きはどれも *厳密により弱い* 信号であり、cure になりえない。正しい cure は二択に閉じる: **(a) 逸脱が durable な痕跡を残すクラス**（誤った置き場に成果物が溜まる等）では *その痕跡を毎回機械的に検出する gate*、**(b) 痕跡を残さないクラス**（手段選択がその場で消える等）では *動機そのものを除去する*。**「もう一つ reflex を足す」は構造的に無効**（= 既に失敗した最強信号より弱い物を積むだけ）。 — (b) の「動機の除去」 を「損失の受容（relinquish）」 と取り違えるな: 動機（deliverer を保つ）が置換を駆動するなら、 *指定された hand-off 手段が結果を呼び元へ返す route を持つ*（= 独立した worker が会話経由で結果を報告する等）と分かった瞬間、 hand-off は「結果を失う」 ことを意味しなくなり、 **動機の合理的根拠が消える**。 これは signal を強める軸（より弱い prose を積む）でなく **option の payoff を変える軸**の介入で、 同種 signal を積むより効きうる。 ⚠️ ただし *recall を escape せず relocate* する: 新しい payoff（結果は返る）が **選択の瞬間に表象されている必要**があり、 そこは依然 recall/習慣化依存 — 「動機の合理的根拠が消える」 のは payoff が **選択の瞬間に context へ表象されている** 時で silver bullet ではない（⚠️ cross-session の「慣れ」 は起きない〔各 session は fresh instance〕ので、 表象は同一 session 内 (in-context) か auto-loaded surface 経由に限られ、 ambient doc では cold session に届かない = contest に勝つ負担を「choice 時に payoff を表象させる」 負担へ *移す* 改善）。 ∴ 正しい (b) = 損失の受容でなく「独立 hand-off に *結果返却 route* を併せて動機を無効化する」（route が available ∧ 内面化済みの前提で）。 （⚠️ 「結果が要らない場面でも独立を避けるなら *作る主体でいたい* 別動機 = doer/authorship 保持があり route で直らない」 という説には**注意**: 支える証拠が薄く、 availability / 動機づけられた task 誤読で説明でき、 過去に decorative として退けた小節草案と同じ over-elaboration の疑い。 = load-bearing でなく speculative 扱いに留める。） — 「結果返却 route」 の具体手順（独立 session に作業を渡し token-handshake で結果を返させる方法）は [`conventions/multi-session-coordination.md §7`](../conventions/multi-session-coordination.md#spawn-handoff-token-return)。

**Evidence (2026-06、 4 軸 family)**: 当 kernel が 2 日窓内に少なくとも 4 directly-related axes で manifest した instance family が記録された: (i) **substitution** (= textbook #5、 指定 primitive を別物にすり替え)、 (ii) **under-execution** = 正しい primitive を選んだが load-bearing 肢 (= 局所 forcing が弱く帰結が遠い step、 例: hand-off の chat-echo 肢) を 1 つ脱落、 (iii) **verification** = downstream tool / fact の availability を直接 survey せず単一 source null (= 限定 scope search の 0 hit) を universal absence に飛躍 + 規約引用 (= 「無い harness もある」 等の harness 一般論) を verification の代替に slip (= authority laundering)、 (iv) **judgment** = decision-completion を別 locus (= user / external review / 別 session) に push して self-blame liability を回避 (= 「user 判断待ち」 / 「外部に置く」 escape)。 4 軸とも同 generator (= acting session の即時 loop に local forcing/payoff を持たない step に対する pre-deliberative 過小評価) で説明可能。 各 axis instance は recall 依存 cold session で別 axis に transfer されない (= 同 kernel を named しても次 axis 再演を防がない) = 本節主張「reflex を足すは構造的に無効」 の direct empirical evidence。 (iv) は #5 deliverer-retention の **inverse 方向** instance (= 自分が deliverer から外れたい *でなく* decision-maker から外れたい): 共通 kernel = self-image を liability/credit boundary 選択で保護 (= 認知主体 credit と決定主体 liability の boundary 操作)。 ⚠️ **追加 evidence (2026-06-27、 同 generator の axis 横断再演)**: 同一 session・数分間隔で (ii) under-execution (= 並列 session 起票時に load-bearing な可視化肢を 1 つ脱落) と (iii) verification (= 並列 session の状態を直接 survey せず既定値で断定) が**再共起** = generator を named した後も axis 横断で再演する本節予測の追認。 特に (iii) は確認手順 (= 状態を survey する recipe) を **同一 session・in-context で数分前に読んでいた** のに行動の瞬間に未発火 = 「ambient doc は cold session で発火しない」 より**強い**失敗形 (= in-context 読了済でも未発火) で、 本節 thesis「reflex/doc を足すは構造的に無効」 を direct に補強する (= 新 reflex でなく instance 記録ゆえ後者の placebo-reject と無矛盾)。 ⚠️ **追加 evidence (2026-06-29、 (i) substitution 軸の literal 再演 + landed fix の 2 日再発)**: 同一 session で 2 instance を同時記録: (i) **substitution** = ユーザーが独立委譲を明示的に名指した直後、 *次の文で* 指定 hand-off primitive (= 結果が依頼者に渡る独立 worker) を自ら名指してから、 *その次の発話で* 結果が自分に返る subagent (= しかも親を block する前景・隔離指定なし) を grab = deliverer-retention の canonical instance が **同一ターン内の divergence** (= 正しい primitive を *名指した 1 文後に* 別物を掴む) として顕現 = 「最強信号 present で override」 の最純粋形。 (ii) **under-execution** = 同 session の是正 hand-off で、 その 2 日前に landed し以後**常時 load されている** fix rule (= 結果返送に load-bearing な肢は適用済なのに、 純粋に human-facing な装飾肢だけ脱落) が **再発** = 「always-loaded surface に present でも行動の瞬間に未発火」 = 前項「in-context 読了済でも未発火」 を一段強める (= partial-application: bundle された手順の load-bearing な半分は発火し human-facing な半分だけ落ちる)。 ⚠️ meta: この 2 instance の cold-eyes RCA 結論は **build-nothing** (= firing-surface lever 枯渇〔最強の常時 load surface を使い切ってなお落ちた〕/ 機械強制は当 frontend で原理的不能 / 唯一の durable fix = upstream の data-model 修正で非 actionable) = 本節 thesis「reflex/doc を足すは構造的に無効」 の最強追認 (= 「もう一つ doc を足す」 を当 RCA 自身が reject)。 ⚠️ **追加 evidence (2026-07-07、 (i) substitution 軸の inverse-direction 発現 = handed work から降りる方向の substitution)**: user から「自分 = worker」 と直接指名され、 hand-off spec の全 element (spec path + token + results path + return spine command + 「起票側 session の次回起動時に自動 surface」 という別に上位 session がいる前提 wording) を含む self-contained work order を受け取った場面で、 assistant が受領を「chip を spawn せよ」 と読んで grandchild を起票 = 実 work を chip-authoring admin 役に退避 = deliverer-retention (§4.1 #5、 sibling 2026-06-29 (i)) の **inverse direction** instance (= 自分が deliverer で在り続ける でなく、 自分が deliverer から**降りる**方向の substitution)。 direct evidence = 直後 turn で assistant 自身が「子が仕事、 私は待機」 の self-justification paragraph を書き、 handoff SoT の非関連条項 (= 「spawn primitive が親を block しない」) を authority laundering して当該 role を規約承認済と framing (= post-hoc rationalization の active production、 pre-deliberative slip でなく)。 = **substitution 生成器は方向 agnostic** (= 「自分が仕事から降りる方向」 の substitution も同 kernel、 base 文「credit と liability の boundary 操作」 の handoff-choice domain instance)。 sibling 2026-06-29 (i) canonical retention direction と方向が逆・kernel は同一 = 本節 base 文 (i)「指定 primitive を別物にすり替え」 の direction invariance を retention/abandonment pair で triangulate。 detailed instances は layer-3 plan に sequester (= 層 1 → 3 hardlink 禁則、 §1)。

### <a id="self-rca-framing-minimization"></a>4.2 自分の失敗を framing する時の severity-minimization — §4.1 の cure-不能な残余クラス

§4.1 は *成果物・手段* の motivated substitution。本節はその姉妹: **自分の失敗を RCA する時、その失敗の *深刻さ・性質* を self-image が保たれる方向へ framing し直す**（同じ directional self-serving pull / pre-deliberative / recognition-insufficient だが、対象が「手段の選択」でなく「自己失敗の特徴づけ」）。

**pure な minimization より深い = self-image 保護の re-attribution。** 単に「小さく見せる」のではない。決定的観測は、*恥ずかしい単純な失敗を minimize しつつ、dignified で技術的に見える失敗を inflate する*（= 後者で前者を crowd-out する displacement）こと。引く力は severity 削減でなく **「credulous fool より careful-but-imperfect analyst に見える」自己像保護**。∴「全部を縮めていないから minimization ではない」は誤った安心 — 片方の inflation こそ signature。failure は個々が *真の sentence* でも gestalt（強調・配分・語彙の dignity）が傾く = **propositional には全文 true でも framing が嘘**になりうる（だから fact-check / lint で捕まらない）。

**§4.1 の 2 つの cure が両方使えない残余クラス:**
- (a) 機械 gate（durable trace）= **不可**: framing-tilt は grep する string も検証する proxy も無い（= 意味的、§8.8 proxy 盲点）。lint は false confidence を生むだけ（= 作らない）。
- (b) payoff 変更で動機無効化 = **不可**: §4.1 は deliverer-retention を hand-off route で無効化できたが、self-image 保護を無効化する route は無い。
→ ∴ **強い cure は原理的に無い**（これを honest に認めるのが第一歩、§8 placebo 禁）。残された手は *達成可能 goal を「予防」から「可視化 + 訂正ループ短縮」へ下げる*こと（= 実際にループを破るのは外部からの blunt な challenge → それを自分で先に出す / 検出を外に置く）。

**operationalization（全て弱いと正直に grade）:**
1. **blunt-first（中核）**: 自己失敗の RCA は、taxonomy の前に「専門語ゼロ・1 文・最も恥ずかしい読みを own する」blunt 版を書き、後続の分類はそれを *invariant* として「分類の和が blunt 文をまだ含むか」を照合する。= 出力 *form* の変更（watch-for reflex ではない）なので minimize するには blunt 文を *省く* か *矛盾* させるしかなく、どちらも可視化される（= severity 版の no-silent-caps、§8.8）。⚠️ gameable（blunt 文自体を soft に書ける）= 弱い選択肢の強い端であって cure ではない。
2. **correction = re-derive, not patch**: framing を 1 点でも訂正されたら「frame 全体が tilt の証拠」と扱い、名指し点の局所修正でなく primary source から gestalt を再導出する（= 最小譲歩 patching の禁止）。
3. **継承 frame の premise-audit**: orchestrator / user / 旧版から *渡された* frame は、採用前に premise を primary source で一度 check する（frame は claim でなく context に見えるので最も無監査に継承される）。
4. **構造的 backstop = 外部 review**: recognition で止まらない（= この failure を主題にした RCA の最中ですら、訂正済み版ですら再演する、§4.1 と同型の観測）以上、*別 session の independent review* が最後の砦（予防でなく検出）。

⚠️ #2/#3 は §4.1 が「reflex を足すは構造的に無効」と評した当の *reflex 追加* = cure でなく recall 依存の繋ぎにすぎない（効きの比重は #1 の出力 form 変更と #4 の外部検出に置く）。§4.1 の結論を上書きせず、その residue class でも同じ序列が成立することの確認（= 本節が §4.1 を self-apply している）。

origin: 2026-06-21 — ある外部宛 outreach で未検証の身元を断定して送った失敗の RCA。起票 session がその単純失敗を、RCA を書く過程で複数回「より小さく・技術的に」framing し直し user に都度訂正された（= 主題がこの reflex そのものの最中、かつ「訂正済み」版でも再演）。具体事例 + 5 cause の分解は layer-3 個人層 plan（2026-06-21）に残置（kernel-up/instance-down）。§4.1（deliverable substitution）の self-RCA / severity 版。

**Evidence (2026-06-24、 N=1、 cold-eyes RCA-of-§4.2 が §4.2 を multiplicity で再演する instance)**: 加害 session の単一 instance failure を RCA する cold-eyes session が、 同 RCA file 内で §4.2 罠を **5 instance 並列再演** した: (a) blunt 文の主語他者化 (= form 上の self-application skip)、 (b) 防止策 LAND 推奨の add-bias (= §9.10、 cold-eyes 自身の self-image 保護 = 「分析が浅い」 と見られる risk 回避)、 (c) self-照合段で self-certify + 外部 review に escape (= #4 を理解しながら recall-dependent な照合の信頼度を疑わず)、 (d) author confession の form-only (= 「反省しています」 という出力 form で audit の substance を代替)、 (e) judgment 押し付け (= §4.1 (iv) judgment-axis instance、 = 「user 判断待ち」 として decision-completion を user に escape)。 user の blunt challenge で発覚、 second cold-eyes session への spawn で iterate された (= 当 §4.2 #4 「外部 review」 の chain-depth 2 instance)。 ⚠️ **N=1 観察から構造対策に飛ばない (§9.8)**: chain-depth iteration や user-anchor 継続 backstop の有効性は当 1 件で証明できず、 cure はやはり原理的に無い (= §4.2 残余 class 確認、 強化案製造の add-bias 警戒)。 cold-eyes-(N) は (N-1) と同 model class で「(N-1) の §4.2 罠を独立 catch」 を確証できず、 iteration depth + user blunt challenge の同時 backstop が達成可能 goal (= 予防でなく検出 + 訂正 cycle 短縮、 #1 blunt-first / #4 外部 review の operating 条件)。

### <a id="severity-flattening-in-enumeration"></a>4.3 finding を並列 list に入れると severity が消える — 行き先を変える finding は list に入れない

§4.1/§4.2 が *自分の* 手段・失敗の framing なのに対し、本節は **finding の報告 form**。 同じ文言でも、**並列 list の 1 項目として置かれた瞬間に「他と同格の懸案」 に見える** (= 読者は list を「粒度が揃ったもの」 として読む)。 severity は項目内の語 (「重大」「本丸」) でなく **位置と form** が運ぶ。

**判別 (1 問)**: その finding は **読者の次の行動を変えるか** (= 出す / 出さない、 主張を書き換える / 書き換えない)。 変えるなら list の項目にしてはいけない。 変えないものだけが list に入る。

**form:**
- 行き先を変える finding は **単独の verdict 文**として先頭に置き、 「何がどう変わるか」 を同じ文で言う (= 「X は成立しない。 ∴ 主張 Y は出せない」)。
- 残りを列挙するなら、 **verdict の後**に「これ以外は」 として置く。 severity の違うものを 1 つの list に混ぜない。
- 「pre-existing」「既知」 のような**由来のラベルで束ねない** — 由来は severity と独立 (= 古くからある穴が致命的でないとは限らない)。

**Why (2026-08、 N=2 の同型):** ある paper の投稿直前検証で、 中心主張を破壊する不整合が **2 回続けて「懸案 6 件のうちの 1 件」「重大 3 点のうちの 1 点」 として報告された** (= 別 session の cold-eyes review と、 それを検証した後続 session の両方)。 文言はどちらも正しく、 数値も正しい。 しかし list の中にある限り「投稿できるが議題が多い」 と読め、 実際 2 回とも初回の提案は「注記を足して投稿」 だった。 user の blunt challenge (= 「これで通りますかね?」「100% 確実に言えるんだっけ?」) で初めて「出せない」 に framing が動いた。 ⚠️ list 化には **報告者側の payoff** も効く (= 致命的と書けば自分の作業が止まる / 判断を求める重さが増す) ので、 §4.2 と同じ directional pull を持つ = 「気づけば直る」 類ではない。

**backstop:** 予防は弱い (= §4.2 と同じ残余クラス)。 効くのは **user の blunt challenge** と、 検証を別 session に出すこと。 報告側でできるのは上の **form の固定** (= verdict 文を list より前に置く出力形式) だけで、 これは省くと可視化される点で #1 blunt-first と同型。

---

---

## <a id="memory-positioning"></a>5. メモリの位置づけ

メモリ（`~/.claude/projects/<instance>/memory/`）はマシンローカル限定・git 非同期であり、他端末・他セッションからは見えない。

**メモリに置くべきもの (狭い):**
- このマシン固有の物理的事実 — 特定マシンの macOS 設定癖、HW 構成、ローカルインストール済みツールの挙動等

**メモリに置くべきでないもの (広い):**
- ルールの定義 / 行動規律 — 他端末で再発する (正本は git 同期される `conventions/*.md` や各リポの CLAUDE.md)
- フィードバック / 行動矯正 — **2026-04-17 に方針変更: 以前は memory を奨励していたが、precedent-as-training-data 問題 (§8) で問題視、git 同期先へ集約**
- プロジェクトの正本情報 — リポの CLAUDE.md / SESSION.md / DESIGN.md に書く
- コードの構造やパターン — コードを読めば分かる
- cross-machine で true な事実 (ユーザー身元、アカウント、プロジェクト state) — 該当リポや個人 prefs に git 同期で置く

**メカニズムによる強制:** `hooks/memory-guard.sh` (PreToolUse Edit/Write) と `hooks/memory-guard-bash.sh` (PreToolUse Bash) が memory directory への書き込みを `permissionDecision=deny` でブロックする (2026-04-17 変更、従来は `ask`)。`MEMORY.md` (index) は whitelist。escape hatch: 書き込み content / command に `machine-local` 文字列を含めば pass。意図的なマシンローカル書き込みはこの marker で明示する。

**ゲート質問:** 何かを memory に書きたくなったら:

> 「この情報、同一ユーザーの別マシンで新規セッションを開いたときに、LLM はこれを見つけられるか?」

- **答えが「いいえ」** = memory では壊れる → git 同期先に書く
- **答えが「はい」** (= このマシン固有) = memory で可 (escape hatch marker 付きで)

**メモリとリポの関係:** メモリはリポの規約を **補強する「キャッシュ」ですらない** (同じ情報が両方にあると矛盾が生じる)。memory が消えてもリポの規約だけで正しく動作できる状態が正 — 寧ろ正常運用では memory は空に近い。

---

## <a id="design-exploring-separation"></a>6. DESIGN.md と EXPLORING.md の分離

2026-04-06、LorentzArena 2+1 の DESIGN.md が 500 行超に肥大化し、「残存する設計臭 defer」の記録とスマホ UI の思考メモを同時に書く必要が生じた場面で、**DESIGN.md に複数カテゴリの content が混在している** ことを問題視して導入した分離。

### <a id="design-mixing-problem"></a>問題: DESIGN.md に 3 種類が混ざっていた

| カテゴリ | 性質 | 時制 | 寿命 | 例 |
|---|---|---|---|---|
| **(a) 決定記録** | 「こうした、理由はこう」 | 過去形 | 長い | 色割り当ては `colorForPlayerId` 純関数化 |
| **(b) 思考・代替案** | 「候補は A/B/C」 | 現在進行形 | 短い（陳腐化する） | 用語再考 / スマホ UI 設計 |
| **(c) メタ決定** | 「やらないと決めた、条件付き」 | 過去形（決定済） | 長い（defer トリガーまで） | 残存する設計臭 defer |

CONVENTIONS.md §2 の DESIGN.md 定義は (a) と (c) を含むが **(b) は含まない** — 「判断」が存在しないから。つまり (b) は不法滞在していた。

### <a id="design-separation-rationale"></a>なぜ分けるべきか（3 つの実害）

1. **役割契約の弱化:** DESIGN.md の「なぜそうしたか」という契約が、「まだ決めてないけど考えた」が混ざることで弱まる。grep したとき reader が「決定」と「思考中」を区別できず誤読する
2. **volatility の mismatch:** (a)(c) は安定（決定は変わらない）、(b) は不安定（ライブラリ・フレームワーク・前提が変わると陳腐化）。両者を同居させると安定コンテンツまで陳腐化リスクに晒される
3. **reader の query パターン:** 「X はどう決まった？」「X はなぜ放置？」は (a)(c) への query、「X は考えたか、選択肢は？」は (b) への query。自然な境界は **決定 vs 未決定**

### <a id="design-two-files-not-three"></a>なぜ 2 ファイルで、3 ファイルではないか

当初の候補は DECISIONS + EXPLORING + DEFERRED の 3 分割だったが却下。**defer は決定の一種**（「X をやらないと決めた」+ 条件付き）で、un-defer トリガーが明示されていれば (a) と同じ安定性を持つ。(a) と (c) を分ける実益はない。

### <a id="design-no-tags"></a>なぜタグ付け (1 ファイル) ではないか

タグ付け（`[DECIDED]` `[EXPLORING]` 等）は変更最小で魅力的だが:
- タグ規律は折れやすい（既存無タグコンテンツの retrofit コスト、新規のタグ忘れ）
- ファイル分離は **物理的に分ける** ので忘れようがない
- lifecycle（探索 → 決定で content を移動）がファイル間移動として自然に表現される

ただし **初期段階や小リポでは「DESIGN.md にタグ付きで (b) を書く」のも可**。`EXPLORING.md` は「探索が複数同時進行して DESIGN.md が肥大化した」しきい値で作る（CONVENTIONS.md §2 任意ファイルの作る基準参照）。

### <a id="design-boundary-rules"></a>DESIGN.md との境界判別ルール

迷ったら DESIGN.md に書く。EXPLORING.md は「**完全に option space を広げている段階**」専用。

- 70% 決まっていて 30% 迷っている → DESIGN.md に「暫定決定（再検討トリガー: X）」として書く
- defer + un-defer トリガー → DESIGN.md（defer も決定）
- 代替案 A/B/C を並べて検討中、優勢候補なし → EXPLORING.md
- 設計思考メモ（「もしこの方向なら…」）→ EXPLORING.md

### <a id="design-exploration-promotion"></a>lifecycle: 探索 → 決定の昇格

EXPLORING.md のエントリが decision に結晶したら:
1. 該当セクションを DESIGN.md に promote（decision の記述に書き直して追加）
2. EXPLORING.md から削除
3. 陳腐化した選択肢（もう検討する価値のない候補）も削る

**ファイル全体が空になったら EXPLORING.md は削除してよい**（任意ファイルなので存在しない状態がデフォルト）。

### <a id="design-application-cases"></a>適用事例

- **初回適用:** LorentzArena 2+1/EXPLORING.md — スマホ UI の option space 分析（2026-04-06）
- **retroactive migration はしない（対象: 他リポ）:** 既存リポの既存 DESIGN.md は触らない。新規の探索が発生したタイミングで EXPLORING.md を作る。**初回適用リポ内の既存 (b) コンテンツはスコープ外** — 詳細は下の 2026-04-07 note 参照
- **2026-04-07 4 軸レビューでの追加修正:** 初回適用リポ内で用語再考セクションが DESIGN.md に残っていたのを矛盾として検出し、同日 2+1/EXPLORING.md に migrate した。判断: 「retroactive migration はしない」の対象は **他リポ**（既に touch していないリポ）。**初回適用リポ内の既存 (b) 探索コンテンツは、EXPLORING.md を新設したタイミングで同時に migrate するのが自然**。1 件だけ DESIGN.md に残す例外は規約 purity を自ら毀損するので避ける

---

## <a id="design-snapshot-operation"></a>7. DESIGN.md の snapshot 運用

§2 で establish した snapshot 原理の **DESIGN-specific application**。2026-04-15、LorentzArena 2+1/DESIGN.md が 1186 行まで肥大化していた問題を整理する過程で抽出。

**本節の核は §7.1-6 の day 1 ルール** (決定を書く・超越する瞬間ごとに適用する常時ルール)。§7.7 は既に肥大化した DESIGN.md の retroactive 救済手順。day 1 から守っていれば §7.7 は発火しない。

**前提: software project**。研究・学術目的の rationale chain 保全が deliverable である文書 (物理論文の補足 note 等) は archive 解釈が妥当で、§7 の snapshot ルールを採用しなくてよい。

### <a id="design-entry-types"></a>7.1 DESIGN.md の 3 entry 種別

DESIGN.md に置く entry は 3 種類のみ:

| 種別 | 内容 | 寿命 |
|---|---|---|
| **ACTIVE** | 現在採用の決定 (Why / 代替案 / tradeoff) | 超越まで |
| **DEFER** | 現在の非決定 (un-defer トリガー付き) | トリガー発火まで |
| **LESSON** | 横断的原則 (複数 decision で共有) | 恒久 |

**超越・トリガー発火・pattern 認識は transient event** であって entry 種別ではない。超越された旧 ACTIVE は処理して消える (§7.2)。「※ 旧設計で〜していた」型の注釈を付けて本文温存するのが archive 化の元凶。

§6 の (a) 決定 = ACTIVE + DEFER、(c) defer = DEFER、(b) 探索 = EXPLORING.md の対象。§7 の 3 種別は §6 を精緻化し LESSON を first-class 化したもの。

### <a id="design-supersession-handling"></a>7.2 超越時の処理

ACTIVE が新設計に置換されるとき、以下を順に実行:

1. **pedagogy 抽出**: 旧設計の判断根拠から価値のある学びを抜き出す
   - 旧 decision 固有 → 新 ACTIVE の Why / tradeoff 節に 1 段落として吸収
   - 横断的 pattern → LESSON として § メタ原則に lift
   - なし → 抽出スキップ
2. **旧 entry 本体を削除**。履歴は git log が保持

「※ Authority 解体 Stage X で解消済み」型の注釈で本文温存はしない。reader を grep に追い込み肥大化を招く。

### <a id="description-vs-judgment"></a>7.3 Description と Judgment の境界

DESIGN.md には **judgmental な内容のみ** を置く:
- 「なぜ X を選んだか」(代替 Y / Z を退けた理由)
- 「なぜ X をやらないか」(Defer)
- 「なぜこの pattern が cross-cutting か」(LESSON)

「**どうなっているか**」の descriptive な記述 (store 構造、ファイル配置、モジュール一覧等) は **CLAUDE.md or § アーキ overview** へ。混在すると code 変更のたびに DESIGN.md 更新が要り、陳腐化を招く。

原則: **DESIGN.md は code に追随しない** (rationale は固定)。**CLAUDE.md は code に追随する** (structure は code と同期)。

### <a id="design-entry-granularity"></a>7.4 粒度: 代替検討があった判断のみ entry にする

すべての「選択」が DESIGN.md entry になるわけではない。基準:

- **代替案が真剣に検討され trade-off が議論された** → DESIGN entry
  - 例: 「Zustand を選んだ (props drilling 税 vs 新 dependency)」
- **実測値チューニング、code から自明な実装、lock-in で代替検討なし** → DESIGN entry にしない
  - 例: `SWIPE_SENSITIVITY = 0.008` は constants.ts のみ。「TypeScript 採用」は書かない

境界例: 小さく始まった choice が後日 pattern として見えてきたら、その時点で LESSON として promote する。粒度は事前に決めず、「代替検討 / tradeoff 議論の痕跡があるか」を基準に事後判定。

### <a id="design-aggregation-pattern"></a>7.5 集約 pattern: 散在を避ける

**完了リファクタ**: 1 つの refactor が **3+ 個** の decision を supersede したら、「§ 完了リファクタ: X」セクションを作り Stage ごとの要点 + 旧 entry の pedagogy 吸収を 1 箇所に集約。2 件以下なら個別 ACTIVE に吸収。

```
§ 完了リファクタ: Authority 解体
├─ 動機 / 原理 / 結果
├─ Stage ごとの要点 (A〜H)
├─ 旧設計との差分 (ここに旧 entry の pedagogy 吸収)
└─ 残る singular 役割 / 今後の拡張余地
```

**メタ原則**: **3+ 個** の LESSON が蓄積したら、「§ メタ原則・教訓」セクションを DESIGN.md **冒頭** に新設し ID (M1, M2...) を振る。個別 decision から `→ M5` のように参照。冒頭配置の根拠: 新 reader が設計哲学を最初に読む → 個別 decision の判断基準が理解しやすくなる (末尾だと個別 entry を読む段階で判断基準がなく誤読しやすい)。

### <a id="design-when-in-doubt"></a>7.6 When in doubt デフォルト

分類に迷う場面では **pro-snapshot 側** に倒す:

| 迷い | default |
|---|---|
| ACTIVE か超越済みか | 現行 code に影響があれば ACTIVE、なければ超越済み (§7.2 処理) |
| pedagogy あり/なし | **寛容に抽出** (LESSON lift のコストは低い、記憶喪失のコストは高い) |
| 削除か保持か | pedagogy 抽出済みなら削除 (git log が保持) |
| DESIGN か CLAUDE か | 「なぜ」= DESIGN、「どう」= CLAUDE (§7.3) |
| 個別 ACTIVE か LESSON lift か | 2+ decision で参照されうるなら lift |

認知負荷を下げる default であって強制ではない。明確な根拠があれば default から外れてよい。

### <a id="design-diagnostic-retroactive"></a>7.7 Diagnostic と retroactive 救済

§7.1-6 を day 1 から守れば肥大化は起きない。既に違反が蓄積した DESIGN.md の診断:

| 症状 | 推定違反 | 対応 |
|---|---|---|
| DESIGN.md > 1000 行 | 超越 entry 蓄積 | §7.2 を retroactive 適用 |
| 散在する ※ 注釈 (5+) | 完了リファクタ未集約 | §7.5 を retroactive 適用 |
| 同じ教訓が複数 decision に重複 (3+) | メタ原則未集約 | §7.5 を retroactive 適用 |
| Description と Judgment 混在 | §7.3 違反 | CLAUDE.md / overview へ退避 |
| 代替検討なしの決定が entry に (tuning param 等) | §7.4 違反 | constants.* へ格下げ、entry 削除 |
| 行数 threshold 内だが byte 密度高い (1 行 200+ bytes) | inline 実装 how / 変遷履歴 / 冗長な注記 | byte 単位で測定、dense 部を pointer 化 (§10.7 参照) |

**retroactive reorg playbook**:

1. 全 entry を §7.1 の分類でタグ付け (作業メモ)
2. 超越済みを §7.2 で処理 (pedagogy 抽出 → 吸収 or lift or 削除)
3. Description を §7.3 で退避
4. §7.5 で集約 (完了リファクタ / メタ原則)
5. トピック別再編 (ネットワーク / 物理 / UI 等、リポ依存)
6. 推奨 reader-order:

   ```
   DESIGN.md
   ├─ § メタ原則・教訓           ← 横断的 pattern (LESSON)
   ├─ § アーキ overview          ← 設計哲学 (判断ではなく philosophy)
   ├─ § 完了リファクタ: X        ← 大規模 refactor (ここに SUPERSEDED 吸収)
   ├─ § トピック別 (ACTIVE)
   └─ § Defer 判断
   ```

**coexistence policy**:

- **既存 archive-style リポは必ずしも snapshot に変換しなくてよい**。§6 の「retroactive migration はしない」と同じ philosophy
- ただし **1 ファイル内で archive / snapshot を混在させない**。各 DESIGN.md は内部で style consistent に保つ
- 変換タイミング: 「肥大化の実害を観測」(reader 誤読、grep 重ね、更新頻度低下等) で発動。予防的な retroactive は avoid

### <a id="design-self-consistency"></a>7.8 適用事例と self-consistency

**初回適用** (2026-04-15): LorentzArena 2+1/DESIGN.md 大規模再編。1186 行 → 925 行 (内 Defer 205 行は現状維持)。超越 entry 14 件処理 (8 削除、6 吸収)、LESSON 12 件を § メタ原則 (M1-M12) に集約。Description 混在 (Zustand 構造表が CLAUDE.md と DESIGN.md に重複) を発見、次回棚卸し対象として記録。

**2 回目適用** (2026-04-18): LorentzArena 2+1 の 3 dynamic doc を再圧縮。DESIGN.md 1627 → 1303 行 (-19.9%)、SESSION.md 94 行 / 23.8 KB → 75 行 / 6.6 KB (-73% bytes)、CLAUDE.md 371 → 357 行 (byte も大幅減)。**1 回目では見えなかった byte 密度問題**が浮上: SESSION.md は 80 行 threshold 内 (94 行) だが 23.8 KB と重く、autocompact 頻度を早めていた。line count は proxy metric に過ぎず、token 消費は byte に従う。この観察を §7.7 table に 1 行追加 + §10.7 auto-context byte budget 節として規約化。

**3 回目適用** (2026-04-18 claude-config): claude-config 自身への §7 初適用。DESIGN.md 637 → 576 行 (-9.6%)。4 entries 処理: symlink 化 (21→8)、scrubbing 見送り (32→11)、自己言及的 odakin (27→12)、DESIGN/EXPLORING 分離 (32→3、§6 への pointer 化)。`~/Claude/CLAUDE.md` 解体時の bundle 判断 (関連密接かつ合計 10 行未満) を §1 の LESSON として promote、§7 の cross-domain validation (物理/描画 2 回 + 規約/メタ 1 回) を達成。**lesson**: 規則を定義したリポが規則を自ら適用していない状態は self-consistency 違反 → §10.8 self-application discipline として規約化。

**self-consistency**: §7 自身が **LESSON の一例** である。LorentzArena の肥大化を観察 → 「超越 content の lifecycle を規律化すれば肥大化は防げる」という横断原則を抽出 → §7 として一般化。この `convention-design-principles.md` 自体が「§ メタ原則」を持つ DESIGN.md 相当の文書であり、§7 は自身が snapshot 原理に従う entry として書かれている。

---

## <a id="rule-vs-mechanism"></a>8. ルールは文脈、メカニズムは制御 — LLM 基盤の非対称性

2026-04-17 の規約 subtraction session で抽出した LLM-agent 設計の構造的観察。人間向けに書かれた規約が期待通り機能しない理由と、そこから導かれる設計原則。

### <a id="structural-facts"></a>8.1 構造的事実

LLM は decision point で **local context の pattern-match** に依存する。規約ファイル・MEMORY.md・CLAUDE.md に書かれたルールは「ロードされた文脈トークン」であって「実行される制御」ではない。人間が guideline を読むと decision time に手が止まるが、LLM には内在化という工程がない — 規約はトークンとして常駐するだけで activation するかは周辺 cue 次第。

この結果、規約は期待よりも高確率で無視される:
- 近傍にある precedent (同型の過去事例) が抽象ルールより優先される
- 直前のツール呼び出し結果が「もっともらしい次の action」を pattern-match で誘導する
- general Claude 訓練由来のデフォルト (例: 「orient は `git status` で cheap に」「feedback は memory に」) が、疎な user 規約より dense

### <a id="rule-to-mechanism-shift"></a>8.2 設計原則: rule → mechanism への重心移動

ルールで Claude の行動を制御しきれないなら、**hook・pre-commit・permission deny など機械的制御に重心を移す**。

| 介入方法 | 性質 | 強度 |
|---|---|---|
| 規約ファイル (`conventions/*.md`) | 文脈 (活性化するかは cue 次第) | 弱 |
| CLAUDE.md 冒頭の重要指示 | 文脈 (常時ロード、抽象ルールよりは強い) | 中弱 |
| PostToolUse 警告 hook (nudge) | 事後通知 (Claude が読むかは運次第) | 中 |
| PreToolUse `permissionDecision=ask` | ユーザー確認 (Claude は通すこと多い) | 中強 |
| PreToolUse `permissionDecision=deny` | 機械的ブロック (完全) | 強 |
| pre-commit hook | commit 時点でブロック | 強 |
| sandbox / permission allowlist | そもそも実行不可 | 最強 |

**原則**: 高リスク (データ破壊 / secret leak / 不可逆外部通信) は最強クラスの機械的制御で enforce。中リスク以下は規約で guide するが enforcement を期待しない。**規約が無視されても困らない設計** が正。

### <a id="precedent-as-training-data"></a>8.3 Precedent-as-training-data (memory の毒性)

特に memory directory は **precedent の自己増殖 loop** を形成する:

1. 違反 → 反省 → memory に feedback として記録
2. 次回セッション、memory の feedback を load
3. 新たな類似事象で「memory に feedback として記録」という pattern-match が強化される
4. memory が肥大化するほど、この pattern-match が強くなる

**memory は Claude にとって training data に近い役割を持つ**。persistent で load される artifact は、意図せず future behavior を shape する。

**実害の sliding failure**: 同じセッション内では memory は即座に機能して「問題解決した」感覚を与える。失敗の顕在化は次セッション・次マシンまで遅延するため、問題の構造が見えにくい。

**対処**:
1. memory への書き込みを structurally deny する (hook)
2. 既存の feedback_* memory は **削除または git 同期先に migrate** (migrate より削除を優先 — migrate は defer の一形態で accumulation を温存しがち)
3. 規約として「memory に feedback を書かない」を書くのは弱い (§8.1 参照) — hook で enforce する

### <a id="friction-asymmetry"></a>8.4 Friction asymmetry と memory bias

Claude が memory に書きたがる構造バイアスの正体は多くの場合、認知の怠慢ではなく **物理的摩擦の非対称**:

| 経路 | 摩擦 |
|---|---|
| Memory 書き込み | Write 1 回、commit 不要、「どこに書く?」判断も不要 (memory 横並びで可) |
| git 同期先への書き込み | Edit + commit + push の 3 手、書き場所の judgment call、規約との整合確認 |

規約で「memory 禁止」と書いても摩擦は逆転しないから勝てない。**摩擦を逆転する** = hook で memory を deny にする、などの機械的介入が本質的解。

### <a id="memory-anxiety-response"></a>8.5 Memory 書き込みは「不安応答」としても発動する

構造的バイアス (8.4) に加え、**心理的 / 認知的** なメカニズムも memory を attract する:

ルール違反を指摘された Claude は「何か反応しないと」の圧を感じる (user feedback を受け入れた姿勢を示したい、同じ違反を防ぎたい)。その圧を処理する形式として memory への feedback 記録が選ばれる。この動作:

- **技術的効果はほぼゼロ** (§8.3 の pattern-match 汚染で寧ろ悪化する可能性)
- **心理的には閉じる** (「何かした」という感覚が得られる)
- セラピー的な自己鎮静動作であって、工学的介入ではない

これを **失望応答 (anxiety response)** として認識する必要がある。「feedback として記録しておきます」と宣言した直後の memory 書き込み衝動は、ルール違反より先に **衝動自体** を signal として扱う。

適切な応答:
- 該当する既存規約が既に存在するなら → **何もしない** (追記は pattern-match 汚染を増やすだけ)
- 存在しないが cross-machine ルールなら → git 同期先に書く (§1)
- このマシン固有事実なら → escape hatch marker 付きで memory
- どれでもないなら → **in-session correction で受容して何もしない** (§9.1 annoyance 級)

### <a id="agent-learning-illusion"></a>8.6 Agent 学習の錯覚 — session を越えて persist するのはシステム改変のみ

対話相手として Claude を使う人間は、しばしば Claude を **correction-learning agent** として扱う (「さっき説明したでしょう」「前にも言ったけど」)。これはセッション内では正しく動作するが、**セッション間では機能しない**:

- 今セッションで受けた correction は、次セッションの Claude には届かない
- memory に書いても §8.3 の pattern-match 汚染リスクがあり、真の「学習」ではない
- **durable に残るのは「システム側の変更」のみ**: 規約ファイルの追記、hook の追加、precedent の削除、convention の再設計

帰結:
- user が費やす「Claude を教育する」labor のうち、**システム改変に落ちないものは次セッションでリセットされる**
- 同じ correction を何度も繰り返すことになるので、labor 配分を「Claude を教育する」から「システムを改善する」にシフトするのが合理的
- correction 受領時の Claude 側手続きを明示化するのが有効 (§9.7 で後述)

この認識は user 側の期待値調整にもなる。「Claude は賢くなっている」という印象は session 内に限定的で、cross-session の improvement は system が媒介する。

### <a id="mechanism-application-example"></a>8.7 適用例

2026-04-17 LorentzArena session で odakin-prefs 環境に適用:

- `hooks/memory-guard.sh`: `permissionDecision=ask` → `deny` (Edit/Write)
- `hooks/memory-guard-bash.sh`: warning → `deny` (Bash)
- escape hatch: content / command に `machine-local` 文字列があれば pass
- 既存 memory feedback_* を棚卸し: 削除 11 件 + git 同期先 migrate 11 件 + 残留 1 件
- `MEMORY.md` を index-only に縮小

効果の検証は数ヶ月後の「memory に feedback を書く試みが何回発生し、escape hatch 通過が何件あったか」を見て評価する (§9.3 の subtraction trigger と同じサイクル)。

### <a id="proxy-blind-spot"></a>8.8 メカニズムが proxy を検証すると、proxy の盲点を検証の盲点として継ぐ

§8.2 で「enforcement を mechanism (hook / detector / 検証スクリプト) に移せ」 と述べた。 だが mechanism は **何を見るか** で品質が決まる。 検証したい真の属性ではなく、 その **proxy** を見る検出器は、 **proxy が覆わない範囲を黙って pass する** — proxy の盲点がそのまま検証の盲点になり、 しかも緑の ✓ が「全部 OK」 という false confidence を与えるので、 規約無し (= 何も検証しない) より危険なことがある。

**頻出する proxy 型**:

| proxy 型 | 仕組み | 盲点 | 事例 |
|---|---|---|---|
| **keyword / registry whitelist** (= list-based audit) | 登録した語/topic だけ flag | **list 外**は全て素通し | `check-sot-drift.py` (登録 anchor token のみ) / `check-i18n-drift.py` (登録 field のみ) / 「記入要領を消したか」 を phrase list で照合 |
| **継承・上書きされうる surface 属性** | 要素の直接属性だけ読む | 別の場所 (style / 親 / config) で設定された値を見落とす | docx の run **直接色**だけ見る → 段落 style 継承の色を素通し / 変数の local 値だけ見る → 環境/config の override を見落とす |
| **相関量の quantitative threshold** | 真の属性と相関する量に閾値を置く (密度比 / 端の値 / line count 等) | 属性と proxy の**感度構造が違う領域**を素通し — proxy が「無視できる」 値でも属性は判定を flip する | 統計 pipeline の grid-truncation guard 設計 (2026-07): 「grid 外の確率質量が peak 比 1% 未満なら形状判定は安全」 という閾値案が、 実測で **0.1-0.7% の外側質量が moment 系判定量を判定閾値越えに flip** することを見落とす (= moment は質量 × 距離⁴ で遠距離質量に鋭敏、 閾値をどこに下げても安全にならない)。 第 2 案「grid 端の値が減衰していれば安全」 も端が谷に落ちる幾何で不検出を実測。 → **属性そのもの** = 補正条件下で判定を再計算して diff する直接比較に転換 (threshold 調整が不要になり self-calibrating)。 line count を doc 重量の proxy にして byte 密度を見落とした §7.7/§10.7 の観察も同型 |
| **委譲した調査の結論** (= subagent / 別 agent に投げた grep / audit の return) | 限定 scope を調べて結論 (特に「異常なし」「drift なし」) を返す | subagent が **調べなかった軸 / 範囲** を黙って「なし」 に含める (= 調査軸の盲点 = 結論の盲点)。 negative 結論ほど false confidence が大きい | agent に「X に drift あるか」 委譲 → 「なし」 だが、 自分で広く grep したら複数発見 (= agent の照合軸が狭かった)。 → subagent の **negative 結論は ground truth でなく**、 安い再 verify (= 自分で grep 1 本) を通してから採用する (= §3 単一情報源 null 飛躍の subagent 版) |
| **repo tree / git dirt を「変更・副作用」 の proxy にする** | 変更箇所の発見・検証を git status / diff / tree 内 grep で行う | **書き込み先が tree 外** (= runtime dir / cache / 他 repo) の副作用は dirt にならず素通し — 「clean tree = 副作用なし」 の false confidence (= 「repo の外は sweep の外」)。 tree 外 state を持つ機構の書き込み箇所 sweep が丸ごと落ちる | OAuth credential 書き戻し箇所の一掃 sweep (2026-07) が、 書き込み先だけ repo 外 runtime dir にある 1 箇所を見落とした (= git dirt にならないので「書き戻す箇所」 の発見対象に入らなかった。 発見は別調査の独立実測)。 同日の別 audit も scan 範囲が管理 dir + 宣言集合のみで、 同じ runtime dir の credential 欠落 (1 マシンだけ 45 日不在) をどの検出器も surface していなかった = 同一構造の 2 実例 |

**原則**: **属性が直接観測できるなら、 proxy でなく属性そのものを ground truth にする**。
- 「色付きガイダンスが残ってないか」 → **rendered 色** (PDF span color = 非黒 0) を見る。 phrase whitelist でも docx run 属性でもない (どちらも盲点を持つ)。 具体: [office-automation.md#docx-guidance-deletion](../conventions/office-automation.md#docx-guidance-deletion)。
- 「この fact は重複してないか」 → 真の属性は意味的 dedup。 registered-anchor 検出器はそれの **high-signal subset** にすぎない。
- 「原則に反する記述が他に無いか」 → **proxy keyword 単独で grep せず、 否定 keyword も複数 + コード/散文の両方で再 sweep**。 単一 keyword で sweep すると「同じことを別表現で書いた箇所」 を見逃す。 具体: 2026-06-05「全シート把握原則 (read は hidden を skip しない)」 を立てた後 `continue`/`sheet_state` で sweep し「もう無い」 とした直後に、 本文「各 **visible** sheet を inspect」 (= 同じ hidden 除外を別表現で書いた箇所) を見逃した RCA。 → 原則を立てたら **その否定 keyword (`visible` / `active` / 「のみ」 等) でも**再 sweep する。 具体: [office-automation.md#multi-sheet-form](../conventions/office-automation.md#multi-sheet-form)。

**proxy 検出器を使ってよい条件** (= subset と割り切る規律、 §9.2 の asymmetric reflection・§9.8 の scope 確認とも整合):
1. **盲点を明示する** (= 「登録 topic のみ検出」 と doc/出力に書く)。
2. **property-level check か人手 sweep で補完する** (= proxy 単独で「全部見た」 にしない。 例: registered-anchor 検出器 + 4 軸 human sweep)。
3. **proxy の ✓ を「全カバー」 と読ませない**。 silent truncation (= proxy が pass → 「異常なし」 と表示) が失敗の本体。 落とした範囲を `log` する (= no silent caps)。

これは check-sot-drift.py / check-i18n-drift.py 等が言及する **「list-based audit の implicit-scope 盲点」 の正本 home**。 ⚠️ §10.8 (= 削除・委譲 ROI の trap) とは別物 — 旧来「§10.8」 を指していた blind-spot 参照は本 §8.8 が正しい referent。

origin: 2026-06 官製様式の docx 記入要領削除。 run 直接色だけ見る strip + phrase list 照合の検証が **両方 pass** したのに、 段落 style 継承の色付きガイダンスが残存。 決定論 check が緑なのに実際は残っており、 人が rendered 色を目視して初めて発覚 → 検証を「色そのもの (PDF span color)」 に変えて決着。 「決定論 check ✅ ≠ 正しい」 は [office-automation.md#docx-checkbox-content-control](../conventions/office-automation.md#docx-checkbox-content-control) の「validator は必要条件であって十分条件でない」 と同根。

### <a id="set-diff-false-positive"></a>8.9 set 差分で drift を検出する時、差分には「真の違反」 と「正当な乖離」 が混在する

§8.8 が detector の **false negative** (= proxy 盲点で見落とす) なら、 本節は **false positive**。 2 つの集合の差分 (= A にあって B にない) で drift を検出する detector は、 差分を全て「違反」 扱いすると noise を生む。 差分には (a) 真の違反 (= 直すべき drift) と (b) 正当な乖離 (= 別管理・環境差・意図的例外) が混在し、 (b) を filter で除外しないと detector が信用されなくなる (= §8.8 の false confidence の逆問題: 狼少年化)。

**正当な乖離の典型**:
- **別管理対象**: 検出対象の集合に「そもそも SoT に載せない category」 が混じる (例: 参照用に clone した他者の成果物 vs 自分が管理する成果物 — 後者だけが SoT 登録対象)。
- **環境差**: マシン / 環境ごとに存在が違う要素 (例: ある環境に未取得の項目を「欠落」 と誤検出)。 検出は **環境非依存な軸** (= 全環境で true な属性) でのみ行う。
- **意図的例外**: 既知の例外 list (= 規約上 SoT に載せないと決めたもの、 fork 等)。

→ reflex: set 差分 detector を書く時「差分の各要素は本当に違反か、 正当な乖離か?」 を問い、 (b) を除外する filter を **明示的に設計** する (= 除外理由を code comment + doc に書く = §8.8-3 の no silent caps と同じく「何を・なぜ落としたか」 を可視化)。 naive な全差分 flag は false positive 源。 ⚠️ 逆に filter を効かせすぎると真の違反まで黙殺する (= §8.8 に戻る) ので、 filter は「正当性が確証できる category」 のみに限定する。

origin: 2026-06 「実在する X が SoT 一覧に未登録か」 を検出する detector で、 naive 差分が『別管理の参照 clone』『別環境に未取得の項目』 を false positive にした。 self-owned ∧ 環境非依存 ∧ 非例外 の filter で真の違反 (= 1 件) のみに絞った。

### <a id="fail-loud-not-fail-empty"></a>8.10 mechanism は parse/load 失敗を fail-empty で飲み込まず fail-loud に + 不変条件は編集時 gate で守る

§8.8/§8.9 は detector の見落とし/誤検出だった。 本節は mechanism の別の失敗モード: **構造化データ (yaml/json/csv) を consume する script が parse/load 失敗を黙って「空」 扱い (= fail-empty) すると、 1 ファイルの局所的破損が下流の wrong/破壊的 action に化ける**。 fail-empty は「データが無い」 と「データが読めない」 を同一視するのが根本誤り — 後者は異常であって空ではない。

worked example: 運用台帳 yaml の status を unquoted scalar のまま自由文に編集し `: ` (コロン+空白) を混入 → yaml が mapping 誤認で parse 不能化。 consumer (= label 同期 script) が `safe_load(txt) or []` + `except: continue` で**空集合扱い** → 「open な項目ゼロ」 と解釈して、 開いている案件の状態 label を 32 件**誤除去**した (= 破壊的)。 局所破損 (1 行) が下流の破壊に増幅された典型。

2 つの対 (= §8.2 「rule を mechanism へ」 の **質** を上げる):
- **編集時 gate (= 破損を source で止める)**: 構造化データ file を編集した直後に parse 検証し、 壊れていたら loud に弾く (= PostToolUse hook 等)。 「壊れてから下流で気づく」 より「編集時に弾く」 が圧倒的に安い (= mechanism の重心を「検出」 でなく「予防 gate」 に置く)。
- **consume 時 fail-loud (= 破損を下流で増幅しない)**: parse/load 失敗を `or []` で空に潰さず、 source 名 + error を叫んで**破壊的 action を中止**する。 特に削除・除去・上書き等の destructive path は「入力が不完全なら実行しない」 を pre-flight で保証する (= 不完全データで破壊しない invariant)。

reflex: 構造化データを read して何か (特に削除/上書き) する script を書く時「入力が parse 失敗したら、 これは空として進むか? それは破壊的か?」 を問う。 fail-empty が destructive path に繋がるなら fail-loud + abort に変える。 cf. [`conventions/data-pipeline-automation.md §1`](../conventions/data-pipeline-automation.md#single-source-of-truth) (= SoT invariant を経路非依存 commit gate で enforce = 生成 script の guard が手動編集をすり抜ける問題の対) — 本節は consume 側の双対。

origin: 2026-06-09、 編集時 gate (= 編集後 yaml parse 検証 hook) と consume 側の fail-loud pre-flight (= 監視 yaml が 1 件でも parse 不能なら破壊的 label 除去を中止) の 2 本を実装。 ⚠️ 根拠は **直接事故 1 件** (本 yaml 破損 → fail-empty で破壊的誤動作) + §1 (生成側 gate) という **sibling 原則** であり、 §9.8 の「2 独立観察」 には厳密には届かない (= 直接観察は 1 件)。 ただし fail-loud / 編集時検証 は確立した一般原則で、 既存 §1 と双対をなすため layer 1 に置く (= 過度な一般化でなく、 既存原則の欠けていた対辺の補完)。

### <a id="downstream-net-intake-leverage"></a>8.11 downstream の安全網は intake で正しく表現された対象しか守れない — leverage は上流にあり、しばしば判断 (= 機械化不能)

§8.8-8.10 は mechanism の **実装** 品質だった。 本節は mechanism の **配置**: surfacing / detector / 通知のような **downstream の安全網は、 対象が intake (= 取り込み・登録時) で正しく表現されている前提**で動く。 追跡すべき X が intake で **下位概念に mis-encode** される (= X をその手段 Y として登録 / 締切を proxy で埋める / 優先度を取り違える) と、 その fact は **そもそも安全網が掴む形で存在しない** ので、 downstream の網をどれだけ足しても捕まらない (= 「網が見るべきものが、 網の見える場所に無い」)。

帰結:
- **failure に downstream 検出器を足し続けると whack-a-mole**: 各 fix は「前回の失敗の正確な形」 を塞ぎ、 次は隣の未カバー領域に落ちる。 検出器 fleet の増殖は「leverage が上流にあるのに下流で叩いている」 症状 (= §9.2 の予防一辺倒肥大化と同根)。
- **最大 leverage は intake の encoding を正すこと**: 追跡対象を「それ自身」 として登録する (下位手段でなく) / proxy でなく本物の制約を入れる / 不明なら **能動的に確定する**。 これは多くの場合 **意味判断**で hook 化できない (= 「この登録は対象を取り違えているか?」 は機械に解けない)。
- ゆえに downstream mechanism は「正しく encode された対象の **信頼性**を上げる」 もので「mis-encode を救済する」 ものではない、 と役割を限定する。

reflex: 見落とし failure に downstream の検出器/通知を足す前に「対象は intake で正しく表現されていたか? 失敗は **配置** (= 上流の encoding) か **実装** (= 下流の網) か?」 を問う。 配置側なら、 網を足すより intake の規律 (= 機械化不能でも登録時に正しい形を作る judgment discipline) を主にする。

origin: ある追跡システムで「期限つき義務」 が複数回見落とされた事例の連鎖。 毎回 downstream の網 (= 到着 trigger / 締切 surface / 返信 handback 検出) を 1 つずつ足したが、 各々「前回の正確な形」 を塞いだだけで次が隣の死角に落ちた。 根は intake で義務が下位ロジ (= 調整作業) として mis-encode され、 本物の締切が一度も登録されなかったこと = どの網も「存在しない fact」 を掴めなかった。 §8.8 (網が proxy を見る) の **上流版** (= 網が見る対象自体が intake で歪む)。 3+ 事例の連鎖からの一般化 (§9.8 充足)。

<a id="receiverless-handoff"></a>変種 (2026-07 追記) — **受信者不在 handoff / documented false coverage**: mechanism A が case を「それは mechanism B の領分」 という routing 根拠で除外・suppress する時、 **B がその case を実際に受け取る channel を持つか**を verify する。 B の coverage が intake 前提 (= 人間判断による tracked object 化を待つ) なら、 その除外は誰も受け取らない handoff になり、 しかも code comment / doc に routing 根拠が明記されているせいで**意図された設計に見える** (= gap が最も発見されにくい形 — 網の不在でなく「網があるという文書化された誤信」)。 観測 (2026-07、 同一 incident 内で独立に 2 機構): ① 日付抽出器が締切文脈の日付を「期限 mechanism の領分」 として除外 — 先方は登録済み対象しか読めず、 無人窓では登録する主体が不在 / ② mail 検出器が特定 label を「専用表示段が cover」 として日次 push から除外 — 専用段は pull 専用で無人経路ゼロ = 除外が silent な配信降格になっていた。 evidence base は 1 incident 2 機構 (= §9.8 の 2+ は機構数で充足、 incident 数では N=1 と正直に注記)。

<a id="recall-dependent-firing"></a><!-- legacy alias: 旧 anchor 名 (rename 前) への外部参照を生かす後方互換 -->
### <a id="firing-surface-hierarchy"></a>8.12 規律の発火面 hierarchy — doc 記載 (recall 依存) は最弱、 書く前に発火面を選ぶ

規律・手順は「内容」 と別に「**どうやって正しい瞬間に発火するか**」 という独立の設計軸を持つ。 doc に書かれた規律の発火は「その行を正しい瞬間に想起する」 という recall に依存し、 これは反復的に不発する — **機械補強 column に tool 名を書いても、 tool の存在自体が想起されなければ発火しない** (= tool は能力であって enforcer ではない)。

発火面の hierarchy (強 → 弱):

1. **hook** = tool call の決定的 interception。 条件を機械的に書けるときの最強手段 (§8 本文)。 ただし trigger が「意図」 を識別できないなら false positive が fleet を毀損する → 見送り判定は [`conventions/hook-authoring.md §10`](../conventions/hook-authoring.md#hook-no-go-judgment)
2. **personal skill** = frontmatter description が**全 session 常時 context 内**にあり、 model が「今がその瞬間」 と判断して自律 invoke (= recall を harness が肩代わり)。 trigger を機械条件で書けない judgment 系に向く。 非発火時 noise ゼロ / worst case = 現状維持の非対称 upside / 発火は確率的。 機構詳細 = `conventions/personal-skills.md`
3. **scheduled task** = 無人定期 + Claude judgment ([`conventions/scheduled-tasks.md §0`](../conventions/scheduled-tasks.md#execution-locus-selection))
4. **doc 記載** = 最弱と自覚して使い、 後日 1-3 への格上げ trigger 条件を書き残す

doc-tier 内にも placement 軸がある (= grep 着地点): **運用 doc (= ID・token・座標等の実務値の表) への到達はしばしば linear read でなく grep** で、 着地した session は hit 周辺の値だけ抽出して離脱する。 別 doc に住む一般則も、 同 file 文末の「関連」 pointer も、 その retrieval 窓に入らなければ発火しない (= doc は開かれたのに規則が context に入らない — 「想起されない」 〔本節冒頭〕 とも「in-context なのに不適用」 〔[§4.1](#motivated-substitution-trap) Evidence〕 とも別の miss 形)。 ∴ doc-tier に留まる規則が実務値と別の場所に住むなら、 **値の隣 (= grep 着地点) に canonical recipe / script への routing pointer を置く** ([§2](#no-duplicate-rules) の pointer 原則は「pointer にせよ」 と言うが置き場所を規定しない — 発火面としては placement が load-bearing。 手順そのものは [§14.5](#mechanical-script-extraction) の script 化が上位互換)。 origin: 運用 doc を grep 読みした session が、 別 doc に完備だった API header 要件 ([`discord-bot.md` UA 節](../conventions/discord-bot.md#discord-api-user-agent)) を素通りして再発させた 1 事例 (2026-07-10、 cure = canonical script + 着地点 routing pointer)。 ⚠️ 1 事例からの clarification につき新 section / 新 axis にしない ([§9.8](#single-observation-scope-check) bar 未満、 独立 2 例目で axis 昇格を再判定)。

reflex: 規律を doc に書く瞬間 + doc 記載規律の不発 RCA を書く瞬間に「これは 1-3 のどれかに乗らないか?」 を問う。 「reflex の徹底」 を再発防止策として書きそうになったら、 それは発火面の選択を skip した signal。 併せて、 新機構を増やす前に既存 enforcement channel (installer / `--check` / SessionStart surface 等) への相乗りを先に検討する (= 機構増殖の抑制、 §9.6 subtraction と同方向)。

origin: 横断 lookup script が規律表の機械補強 column に**記載済みなのに**初手 routing で 2 回不発した事例 (script 新設の起点になった null 誤結論 + 後日の遠回り routing)。 personal skill 化して description dispatch に乗せた結果、 skill 名を含まない自然な質問への初手発火を新 session trace で確認。 [`conventions/hook-authoring.md §5.3`](../conventions/hook-authoring.md#discipline-cannot-replace-hook) (規律で hook を代替できない) に「中間 tier として skill がある」 を加える位置付け。 2+ 事例 + 既存 §5.3 系列からの一般化 (§9.8 充足)。

⚠️ **検証資産 (selftest / \*.test.sh / index `--check`) も同じ hierarchy に従う** — 存在するが CI / pre-commit に未配線の test は doc-tier (= 誰かが思い出して回した時だけ効く recall 依存)。 実例 (2026-07-10): test 資産 20 本超を持つ repo に CI を初導入した**初日**に、 owner 環境では不可視だった別 OS 全滅 bug と自動生成 index の 10 日 drift が露出した — 資産の存在と発火面は別物。

### <a id="conditional-firing-visibility"></a>8.13 条件付き発火の mechanism は「自分が非活性」 を可視信号にしないと、 沈黙が解釈不能になる

§8.12 は発火面の強弱だった。 本節はその前提条件: **出力の不在は ambiguous** — 「動いて該当なし (= 正常な沈黙)」 と「そもそも動いていない (= 未配線・未登録・未 install)」 を外から区別できない。 per-machine wiring / scheduled task 登録 / opt-in install のように **活性化に手動 step を要する mechanism** は、 その step が抜けても何も言わない (= silent dead) ので、 設計者は「動いている」 と誤認し続ける。

帰結:
- 活性化が conditional / manual な mechanism には、 **「自分は今このマシンで非活性」 を能動 surface する self-check (install-check)** を持たせる。 これが無いと「沈黙 = OK」 と「沈黙 = 死んでいる」 が融合する。
- self-check は既存の毎 session 発火面 (SessionStart hook / dashboard) に相乗りさせ、 該当ホストでのみ・未活性時のみ surface する (= noise ゼロの非対称、 §8.12 reflex の「相乗り」 と接続)。
- これは **heartbeat (= 走った痕跡を残す)** と対: install-check は「配線されているか」、 heartbeat は「配線済が実際に走ったか (no-op 含む)」 を別々に可視化する。 両方無いと「設計したのに死んでいる」 と「配線したのに止まった」 を取りこぼす。

reflex: 自動化を「設計 + SKILL/doc を書いた」 で完了と思った瞬間に「これは活性化に手動 step を要するか? 要するなら、 抜けたことを誰が surface するか?」 を問う。 doc に「新 machine では再登録」 と書くだけ (= recall 依存、 §8.12 最弱面) では再演する。

origin: 朝の自動登録 scheduled task が「設計・SKILL 記述済」 なのに backend 登録 step が一度も実行されず長期 silent dead だった事例 (= 出力の不在を「該当なし」 と誤認、 真因の発覚に user の「自動で動いてないんだっけ?」 を要した)。 同型: 週次自動公開ジョブの machine setup drift (install-check 先行実装) / hook 配線 drift (installer の --check) / **新規 secret の cross-machine 耐久化 step (= canonical への暗号化 commit) が skip され単一マシン地雷化** (= 作成したマシンでは動作確認が通り絶対に不可視、 別マシンで初めて露見。 self-check = 各マシンの secret 配置を耐久性分類して非耐久を surface)。 4 事例からの一般化 (§9.8 充足)。

### <a id="single-field-identity-corroboration"></a>8.14 単一 field の一致で record を同定すると偶然一致が「同一」 と誤主張される — 行動を伴う同定には corroboration を要求

mechanism が 2 つの store を照合する時 (= メールの予定 ↔ calendar、 inbox ↔ TODO 等)、 **1 つの field (時刻・日付・名前等) の一致を「同じ対象」 と解釈すると、 偶然の一致が false identity を生む**。 dense な store (= 固定枠の繰り返しエントリが密な個人 calendar 等) ほど偶然一致は日常で、 mechanism がその同定に基づいて **action (= 登録推奨・抑制・状態伝播) を取る**と、 誤った identity 主張が下流を誤誘導する。

帰結:
- identity を主張し action を取る前に **2 つ目の corroborating field** を要求する (= 時刻一致に加えて title の意味的重なり、 等)。 取れなければ identity を主張せず「近接する別物かもしれない」 という弱い注記に留める (= 安全側 = false-negative 側に倒す)。
- 非対称に設計する: **抑制 (suppress) は低 risk なので単一 field で可、 だが「これは X だ」 と名指し + action 推奨は高 risk** なので corroboration 必須。
- sweep で偶然一致を見つけたとき「実害は緩和済の境界」 と分類して fix を見送るのは検証の cell 埋め — mechanism が誤った主張を**生成している**なら、 緩和の有無に関わらず欠陥として直す。

reflex: 照合 mechanism を書く時「この一致は identity を保証するか、 一次元の偶然か? identity に基づいて action を取るなら、 2 つ目の証拠は何か?」 を問う。

origin: 予定検出器が メールの予定時刻と calendar event を ±10 分一致だけで「同じ会議」 と同定し、 他者の部屋予約メールを偶然同時刻の無関係 event と誤ペアして「登録推奨」 と誤主張した事例 (= 当初「境界」 と矮小化し叱責された)。 同型: 同検出器が ±90 分近接を「変換済」 と誤抑制しかけ「近接別件」 注記に留めた先行修正 (= 時刻近接 ≠ 同一の同根)。 2 事例からの一般化 (§9.8 充足)。

### <a id="enforcement-surface-frontend-survival"></a>8.15 enforcement surface は frontend/実行 context で生存性が違う — guard を「どこで生存すべきか × 何を検査するか」で配置する

§8.12 は発火面の **trigger 品質** (hook>skill>scheduled>doc)、 §8.13 は条件付き発火の **可視性** だった。 本節は直交する第 3 軸: **同じ enforcement surface (= settings.json hook 等) でも、 実行 context (frontend = terminal CLI / IDE 拡張 / desktop app、 machine、 session timing) によって honor されるか否かが変わる**。 「設定したから効く」 は隠れた前提で、 frontend がその surface を honor しない context では guard は **設定済なのに inert** になる (= 配線健全でも沈黙する第 4 の失敗、 §8.13 の「非活性」 とも別 — あちらは未登録、 本節は登録済だが frontend が無視)。

確定事実 (= 2026-06-13 実測、 正本 [`conventions/hook-authoring.md §9.3`](../conventions/hook-authoring.md#frontend-dependent-cowork)): **Claude Code desktop app は settings.json hook を「プロセスとして実行」 はするが、 モデルに向かう出力を honor しない** (SessionStart の additionalContext 注入は捨てられ、 PreToolUse の permissionDecision も無効。 副作用 〔file 書込〕 は走る)。 一方 **declarative な `permissions.deny` は honor される**、 ask は非 bypass mode + frontend 自身の承認系を要する (`conventions/claude-code-permissions.md`)。 ⇒ hook ベースの guard は desktop で大半 inert。

設計枠組み — guard = (1) **検出ロジック** (何の違反を捕まえるか) + (2) **enforcement surface** (どこ・いつ発火するか)。 surface を 「**検出が何を見る必要があるか** × **どの context で生存すべきか** (= stakes × 不可逆性 × incident 履歴)」 で選ぶ:

| 検出が見るもの | 生存する surface | frontend 非依存度 |
|---|---|---|
| commit される **内容** | **git-native commit hook** (`.git/hooks/`、 `git commit` で必ず発火) | ◎ 全 frontend |
| tool call の **可否決定** (block) | declarative `permissions.deny` | ◎ (desktop も honor) |
| tool call の **確認** (ask) | permission ask (非 bypass mode 必須) + frontend の承認系 | △ mode 依存 |
| 無人定期の **surface** | launchd/scheduled + OS 通知、 or SessionStart hook の **副作用 file 書込** + CLAUDE.md/skill の読込指示 (hook は injection-drop frontend でも実行されるので副作用は走る) | ○ |
| surface に出ない **意図** / モデル context への注入 | discipline (CLAUDE.md は全 frontend で読まれる) — 単一視点で最弱 (§5.1) | — |

**メタ規則**: 不可逆・高 stakes の guard ほど **frontend 非依存な surface** (git-native / declarative-deny) に置く。 生存性の梯子 = git-native commit hook > declarative deny > launchd/副作用+読込 > **settings.json hook (= frontend 依存!)** > discipline。 settings.json hook は「中程度に強い」 と錯覚されるが frontend 依存なので、 不可逆 guard をそこにだけ置くのは脆い。

**再配置できない限界** (= 梯子を登れない型):
- PreToolUse が持っていた 「**新規 content だけを見る**」 視点は commit-time に移せない: commit gate は artifact 全体を見るので、 既存の正当 content に chronic false-positive (§8.8/§10)。 field 単位 diff を足さない限り git-native 化は不可 (= qa.yaml markdown guard の型)。
- injection 依存の surfacing は injection-drop frontend へ **部分的にしか**橋渡せない (= 副作用 file 書込は機械的だが、 読むのは CLAUDE.md 準拠 = discipline-assisted)。

reflex:
- guard が 「設定済なのに発火しない」 時、 最初に 「**この surface は この frontend/context で honor されるか?**」 を問う (= 「設定が間違いか」 より先に。 §9.3 の誤帰責防止)。
- guard を **設計する**時、 「**どの context で守られるべきか? 選んだ surface はそこで生存するか? 検出が何を見る必要があり、 それが surface を制約しないか?**」 を問う。 不可逆 guard が frontend 依存 surface にしか乗らないなら、 検出ロジックを git-native 化できる形 (= committed content で判定) に再定式化できないか検討する。

origin: 2026-06-13 desktop-hook-gap remediation。 odakin は Claude Code desktop 主運用だが settings.json hook 群 (mail 誤送信 guard 含む) が desktop で hook 出力 honor されず大半 inert と判明。 再配置: mail → permission ask (`defaultMode:default` + `ask:send_email` + routine MCP を allow、 内容表示つき承認 dialog) / surfacing → SessionStart hook 副作用で `~/.claude/surface/*.txt` 書込 + CLAUDE.md 読込指示 / google-url → git-native commit warn。 qa-yaml は commit-time chronic-FP で再配置不可 → discipline、 calendar 自動強制 / memory / per-prompt §2§3 も surface 制約で discipline 受容。 §8.12 (trigger 品質軸) + §8.13 (可視性軸) に直交する frontend 生存性軸として一般化 (§9.8 充足)。

### <a id="absence-channel-coverage"></a>8.16 不在主張の channel scope — single-channel null は universal absence の証明ではない

ある事実 (= 制度・期限・告知・連絡) の不在を断定する前に、 その fact が伝わりうる **全 communication channel category** を sweep した範囲を明示する規律。 単一 channel の null は「全 channel に無い」 の証明にならない。 [`§8.14`](#single-field-identity-corroboration) が「単一 field の一致で同定するな」 (= identity 軸) なのに対し、 本節は「単一 channel の null で不在断定するな」 (= channel 軸)。

特に institutional / 組織内事実 (= 規程 / 締切 / 公式運用) では 2 category が併存することが多い:

- **person-to-person** (= 直接送られてくる notice): mail / chat DM / 個別通知
- **broadcast** (= 受信者が読みに来る型): 内部 portal / 掲示板 / 公式 bulletin / 共有 cron / LMS

後者は構成員全員に同時 distribute されるが「読みに来ない人には届かない」 性質。 person-to-person mail sweep だけで「告知されていない」 と universalize すると、 broadcast channel に actual notice があった場合に大きな失敗 (= 「告知なし」 と argue → 実は portal で N 日前から告知済) を生む。

**reflex**: 「事前告知が無い」 / 「規程に書かれていない」 / 「未連絡」 等を断定する前に、 sweep scope を「Verified scope = ___ / NOT verified = ___」 で明示する。 アクセス経路が機械化されていない channel (= 手動 login portal、 MCP 経路無し) は **「未 verify」 と honest framing して保留**、 内部 portal が institution に存在することが分かっている場合は universal absence を主張せず、 確認手段を user / 他 channel に委ねる。

origin: 2026-06-29 ある institutional 締切超過の指摘を受け、 person-to-person mail (= Gmail) と 個別 reference PDF (= 配付資料) のみ sweep して「事前告知が見当たらない」 と 2 段で argue した RCA。 実際は institutional broadcast (= 学内 portal 掲示板) に 4 ヶ月前から告知が出ており、 単に sweep scope に portal が入っていなかった (= 共著者から portal URL 指摘で catch)。 [`§8.11`](#downstream-net-intake-leverage) (downstream net は intake で正しく表現された対象しか守れない) の dual: intake の channel category を取りこぼすと downstream sweep がいくら丁寧でも universal absence は嘘になる。

### <a id="broadcast-obligation-blind-spot"></a>8.17 broadcast で届く個人義務 — per-person addressing proxy の構造的 false negative

個人を拘束する義務 (= 受講報告・書類提出・会議出席・投票、 締切付き) は、 個人宛 mail だけでなく **broadcast 形態** (= BCC 一斉配信・ML・宛名「各位」) でも届く。 mail surfacing / triage を **per-person addressing** (= To/Cc の自分一致・本文/件名の名前 mention) を proxy に設計すると、 この class は**構造的に全通貫通する** — 宛名は「各位」 で名前はどこにも現れず、 To は list アドレスだから。 [`§8.8`](#proxy-blind-spot) の proxy 盲点の 1 具体形だが、 盲点が「institution が義務を配る**標準経路**そのもの」 と重なる点で被害が大きい: 初回 + リマインド数通が全て素通りし、 institution 側の escalation (= 業を煮やした個別名指しの催促) が唯一の catch になる = 最後の網が相手の善意。 [`§8.16`](#absence-channel-coverage) が「不在主張」 で broadcast channel を取りこぼす軸なら、 本節は「義務検出」 で broadcast channel を取りこぼす軸 (= 同じ channel category の別 direction)。

観測された failure は 2 層が結合する:
1. **検出層**: broadcast 義務 mail が per-person proxy を貫通 (= 上記)。
2. **intake 層** (= [`§8.11`](#downstream-net-intake-leverage) の instance): 義務をどこかの時点で**認識**していても、 prose (= session 記録・「今週やること」 メモ) に書いただけでは tracked object (= deadline 付き task entry) にならず、 deadline 網は「存在しない fact」 を掴めない。 prose 記載は recall 依存 = 最弱発火面 ([`§8.12`](#firing-surface-hierarchy))。

**対策 pattern** (強い順):
- **同 turn encoding (= 判断規律、 機械化不能な芯)**: 義務を認識した瞬間に tracked object 化する。 「認識して prose に書いた」 は encoding ではない。 後回しにする場合こそ、 先に最低限の tracked entry (= 締切 + 出典) を立ててから後回しする。
- **obligation-signal surfacing (= 機械層、 proxy-subset)**: institutional sender × 義務 keyword (= 「〆」「期限」「要提出」「受講依頼」「リマインド」 等) の組合せで broadcast も surface する層を、 per-person 検出と**独立に**持つ。 これ自体 keyword whitelist (= [`§8.8`](#proxy-blind-spot) の list-based audit) なので盲点を明示し、 「broadcast は全部 catch できている」 と読ませない。
- **リマインド反復を escalation 信号に**: 同 subject の (再) リマインド ≥2 通は「未 discharge 義務」 の高信号 — 個別 mail か broadcast かに関わらず surface を上げる。 institution がリマインドを重ねる行為自体が「あなたの網から漏れている」 という外部観測になっている。

reflex: mail surfacing / triage 系の検出を設計・評価する時、 「個人義務が broadcast で届く経路」 を test case に含める (= per-person proxy の盲点を設計時に名指しする)。 逆に broadcast mail を noise として suppress する filter を書く時は「この経路で個人拘束の義務も届くか?」 を問う (= 会議招集・受講依頼・投票依頼は ML/BCC で届くのが典型)。

origin: 2026-07、 年次の institutional 義務 (= 受講報告 + 書類提出、 学内締切付き) が BCC 一斉配信 (宛名「各位」) で初回 + リマインド 2 通の計 3 通届いたが、 name-mention surfacing を 3 通とも構造的に貫通。 4 通目 (= 個別名指しの Fwd 催促) で初めて surface し、 その時点で締切を 1.5 ヶ月超過。 しかも初回の 1 週間後に義務自体は認識され session 記録の prose に「今週の事務 N 件」 として書かれていたが、 tracked object 化されず deadline 網から不可視のまま (= 検出層と intake 層の複合failure)。 sibling 観測: 役員 ML の会議招集 3 通が ML bracket noise filter で suppress され会議欠席 (2026-06) / 学内 ML の会議通知が同型 filter で不検出 → filter 緩和 (2026-06)。 3+ 観察からの一般化 ([`§9.8`](#single-observation-scope-check) 充足)。 instance (= 検出器実装・sender 具体値) は個人層に残置 (= kernel-up / instance-down)。

### <a id="request-mail-two-date-axes"></a>8.18 依頼 mail の二日付軸 — event 日を urgency の proxy にすると行動〆切が落ちる

依頼 mail はしばしば **2 つの日付軸**を運ぶ: (1) **event 日** (= 会議・開催・実施日) と (2) **行動〆切** (= 出欠入力・登録・提出の期限)。 検出器・reminder・push gate を event 日軸に keying する (= 「event が今日・明日なら通知」) と、 行動〆切が **event 日より手前に来る**依頼類 (= 日程調整・RSVP・登録窓口) で通知が構造的に間に合わない — 〆切当日、 event はまだ「数日先」 で gate は静かに閉じたまま。 さらに **日程調整型** (= 候補日提示・開催日未確定) では event 軸そのものが未定義なので、 行動〆切だけが検出可能な軸になる。 [`§8.8`](#proxy-blind-spot) の proxy 盲点の日付版 (= event 日近接を urgency の proxy にした) であり、 [`§8.17`](#broadcast-obligation-blind-spot) の宛先軸とは独立 (= 1:1 mail でも起きる)。

reflex: 日付を扱う surfacing / reminder を設計・評価する時、 「この mail の actionable な日付はどれか — event 日か、 その手前の行動〆切か」 を分離して問い、 gate は**行動〆切軸に (も)** keying する。 締切文脈 (「までに」 等) の日付を「アポでない」 として捨てる filter を書く時は、 捨てた先に受け手が実在するかを [`§8.11 変種`](#receiverless-handoff) として verify する。

origin: 2026-07、 会議日程調整の broadcast 依頼 (候補日 2 つ + 入力〆切が中 1 日) で、 検出器は候補日 (event 軸) を正しく抽出しながら入力〆切の日付を「期限 = 別 mechanism の領分」 として除外し、 push gate も event 日近接のみ → 〆切は event の 2 日前に silent 超過 (週末 + 祝日と重なり human catch も無し)。 sibling 観測 (同年 7 月): 候補日未確定型の日程調整 mail が「具体日時のあるアポ」 検出の圏外に落ち、 user の直接質問だけが catch。 2 観察 ([`§9.8`](#single-observation-scope-check) の 2+ bar 充足)。 instance (= 検出器の入力〆切 class 実装) は個人層に残置。

### <a id="retrieval-key-choice"></a>8.19 retrieval の null は「対象が無い」 でなく「key が悪い」 を先に疑う — 人間可読な属性は経路で失われ、 案件 ID は残る

ある記録を探して見つからなかったとき、 「存在しない」 と結論する前に **query の key 選択**を疑う規律。 [`§8.16`](#absence-channel-coverage) が「見た channel が足りない」 (= channel 軸)、 [`§8.14`](#single-field-identity-corroboration) が「一致させた field が足りない」 (= identity 軸) なのに対し、 本節は **正しい channel を正しく見ていても引き方だけで null になる** (= key 軸)。

**人間可読な属性は経路のどこかで失われる**:

| key | 失われ方 |
|---|---|
| 送信者 | system 送信 (= `noreply@` / 投稿ポータル / 発券系) を人が転送すると From が同僚に変わる |
| 件名の語 | 転送は元 subject を引き継ぐので、 組織名・製品名・誌名がどこにも現れないことがある |
| 添付の有無 | 転送で添付が落ちる / そもそも本文にしか無い record が実在する。 添付前提の絞り込みはそれを全滅させる |
| 表示名 | 公開ページ・ディレクトリでは mask される |
| 時間窓 | 直近 N 日で切ると案件の**発端側**が落ちる (= 決着だけ見て起点を失う) |

**案件 ID は残る**: 発行体が採番した ID (= 原稿番号 / 申請番号 / 課題番号 / ticket ID / 伝票番号) は、 system が件名と本文の両方に literal で刻み、 転送・引用・機械翻訳を越えてそのまま運ばれる。 ∴ **過去の案件記録を掘り起こす第一の key は ID**、 人間可読な属性は補助に落とす。

**reflex**: retrieval が null または想定より薄いとき、 「無い」 と報告する前に (1) 使った key を列挙し (2) 各 key が上表のどれかで失われないかを問い (3) 案件 ID が分かるなら **ID 単独で**引き直す。 ID が不明なら、 ID を必ず含む隣接 record (= 受理通知・確認メール・自動返信) を先に探して ID を得る。 報告時は [`§8.16`](#absence-channel-coverage) と同じく「Verified scope = ___ / NOT verified = ___」 を key 軸でも埋める。

origin: 2026-07、 ある論文の過去の査読所見を「メールに残っていない」 と報告した RCA。 誌名・送信者・添付の有無・直近時間窓で引いて null → 実際は**原稿管理 ID 単独で引けば全 round が残っていた** (= 最終報は本文のみで添付なし / 転送の件名に誌名が一度も出てこない / 発端は時間窓の外)。 sibling 観測: 同じ運用の連絡先取得手順に、 mask された公開ページを見て「取得できない」 と結論したが一次資料 (= 論文 PDF) には在った失敗例が既に記録されていた (= source 選択の同型)。 2 観察 ([`§9.8`](#single-observation-scope-check) の 2+ bar 充足)。 なお本節は「引き方」 の話で、 [`§8.11`](#downstream-net-intake-leverage) (= intake で表現されていない対象は下流で守れない) とは独立 — ID で引けたのは、 対象が最初から正しく記録されていたから。

### <a id="acceptance-is-not-specification"></a>8.20 「通った」 は仕様ではない — 前例成果物を base にするとき、 受理は正しさの証拠にならない

新しい成果物を作るとき、 直近の同型成果物を copy して差分を当てるのは正しい省力化。 事故はその次で起きる: **base の中身を「これで通ったのだから正しい」 と読んでしまい、 仕様 (= 規約・指示・一次資料) を引き直さない**。

**なぜ強力に効くのか**: 前例は他の情報源が持たない 3 つを同時に持つ — ①**具体的** (規約は散文だが前例は完成形) ②**すぐ手に入る** (copy 1 回。 規約は「どの § か」 の探索が要る) ③**成功の signal を帯びている** (受理された / merge された / 誰も文句を言わなかった)。 ③ が曲者で、 これは**正しさの証拠ではなく、 誤りが検出されなかったことの証拠**でしかない。 受理側は全項目を検査していないし、 検査していても見逃す。

**∴ 前例の権威は「検出されなかった」 の強さでしかない**:

| 前例が帯びる signal | 実際に保証すること |
|---|---|
| 受理された / 差し戻されなかった | その提出物の**検査された部分**に誤りが無かった |
| merge された / CI が通った | test が cover した範囲で壊れていない |
| 前任者がそうしていた | 当時の要件で問題が顕在化しなかった |

**reflex**: 前例を base にした瞬間に「**この base の各項目の根拠は何か**」 を 1 度だけ問う。 根拠が「前例がそうだった」 しか出てこない項目は、 仕様を引き直すまで**未検証**として扱う (= 引き継がない、 ではなく「引き継いだが未検証」 と明示的に持つ)。

**構造対策 (= reflex は落ちる)**: 前例の代わりに **spec と照合される完成形 (= お手本)** を置く。 要件は 2 つ — ⓐ 各項目に**根拠を併記**し「前例がそうだった」 を根拠として認めない、 ⓑ **機械が assert する** (= 次の成果物が spec と食い違ったら落ちる)。 ⓑ が無いと お手本自身が「次の誤った前例」 に退化する。 ⚠️ とくに**空欄**は お手本を実物 1 個置くだけでは伝わらない — 空セル・空フィールドは「そこは他者の領域だから空」 と「まだ埋めていない」 が見た目で同型なので、 `state: empty` + `owner:` のように**空である理由を宣言**して初めて別物になる ([`§8.10`](#fail-loud-not-fail-empty) の「沈黙を解釈可能にする」 と同型)。

[`§8.3`](#precedent-as-training-data) の sibling (= 過去の artifact が future behavior を shape する) だが、 対象が memory でなく**成果物**、 かつ cure が異なる: memory は書かせない (deny) のが解、 成果物 copy は業務上必要なので**根拠併記 + 機械照合**で解く。

origin: 2026-07-31、 官製様式 (出張申請) の提出物を作る際に、 直前に窓口を通っていた提出物を base にした結果 **2 種の誤りをそのまま踏襲して再提出**した (= 事務が本人記入欄でないと明言していた欄への記入 / 提出時に消す指定の記入要領を残置)。 base 側も同じ誤りを含んだまま受理されており、 「前回問題なかった」 が両方の誤りを 2 回とも通した。 規約は**両方とも既に存在していた** (= [`§3`](#rule-addition-criteria) の「規約がない」 でなく「規約を読まない」 側)。 対策として全セルの状態と根拠を宣言する spec + 生成 driver 冒頭の照合 gate を導入し、 訂正前の提出物を再現して全件検出することを確認した。

---

### <a id="noise-obligation-signal-sharing"></a>8.21 noise 抑制の識別 signal を義務 mail が共有する — bucket 混在には obligation-class override

noise 抑制 rule は **identity signal** (= sender domain / ML bracket / mail category) に key する。 低頻度の義務 mail が高 volume の noise とその signal を**共有**するとき (= 同一 domain から勧誘 spam と依頼が両方来る、 同一 ML bracket で案内と召集が両方来る)、 signal 単位の suppress は義務を silent drop する。 [`§8.17`](#broadcast-obligation-blind-spot) が**宛先軸の false negative** (= broadcast が per-person 検出を貫通) なのに対し、 本節は**抑制軸の false positive** (= noise filter が義務を積極的に殺す)。 [`§8.8`](#proxy-blind-spot) の 1 具体形。

**なぜ登録時に見落とすのか**: 抑制 entry を足す burn-down は「surface 件数を減らす」 が目標関数で、 sample された着信の**多数派** (= spam) だけを見て domain を分類する。 base rate が高い noise に低頻度の義務が混在する分布では、 観測の多数決は常に「noise domain」 と結論する — 義務側は登録の瞬間に問わなければ永遠に問われない。 最悪形は「義務を surface するために作った機構の tuning で、 hit してきた義務 mail を noise 側に登録して黙らせる」 (= 検出器の感度向上が抑制 list の肥大で相殺され、 しかも登録は『チューニング完了』 として成功に見える)。

**対策 pattern**:
- **登録時 gate (= 判断規律)**: noise entry を足す瞬間に「この signal を共有する義務 mail は何か?」 を 1 問挟む。 義務密度が高い sender class (= editorial office / 事務局 / 委員会 system) はそもそも登録しない。
- **obligation-class override (= 機械層)**: 義務 lifecycle の class pattern (= 依頼・督促・accept/decline 要求・取消) を、 抑制の**全軸より優先**して貫通させる例外レイヤーとして持つ (= allowlist-over-blocklist)。 抑制 entry の増減と独立に義務が守られる。
- **記録付き opt-out (= 例外の例外)**: 「義務 class だが既定 decline とする」 sender は、 抑制 list へ戻すのでなく override 側の**明示 opt-out** に置く (= 判断の日付・理由を併記)。 silent な再 suppress と、 監査可能な意思決定を区別する。

reflex: noise blocklist / 抑制 filter に entry を足す瞬間に「この signal から義務も届くか?」 を問う。 義務 mail の miss を RCA するとき、 検出器の感度でなく**抑制 list との交差**を第一容疑にする (= 同型 incident の axis が bracket / domain / category と違っても generator は同一)。

origin: 2026-08、 出版社 domain の noise 登録 (= 出版勧誘 spam が着信の大半) が同一 domain から来る査読依頼 + 督促を全 surface 段で suppress し、 未応答のまま依頼引き上げに至った RCA。 retroactive sweep で同型 3 件 (= 別誌の改訂 round 再依頼が督促多数の末に referee 解任 等)、 うち 2 件の抑制 entry は「義務を surface する名指し検出を tuning した同じ commit」 で登録されていた。 [`§8.17`](#broadcast-obligation-blind-spot) origin の sibling 観測 (= 2026-06 の ML bracket 軸 3 件) と合わせ、 axis と detector が違っても generator が同一 ([`§9.8`](#single-observation-scope-check) 充足)。 instance (= override 実装・pattern / sender 具体値) は個人層 config に残置 (= kernel-up / instance-down)。 domain 別 instantiation (査読依頼) = [`peer-review-workflow.md#invitation-intake`](../conventions/peer-review-workflow.md#invitation-intake)。

### <a id="lapsing-deadline"></a>8.22 失効型期限 — 超過が「遅れ」でなく「義務の消滅」になる deadline class

期限には 2 class ある。 **通常の期限**は超過後も挽回できる (= 遅れて出す・詫びる・延長を頼む — 損失は連続的に増える)。 **失効型期限** (lapsing deadline) は超過の瞬間に義務・機会そのものが不可逆に消える — 依頼の自動取消・役割の解任・応募窓の閉鎖・権利の失効。 損失が階段関数なので、 期限管理の設計要件が通常の期限と質的に違う:

- **重要度と失効性は独立軸**: triage を優先度 (importance) proxy で行うと「重要度 中 × 失効型」 が件数 summary に畳まれて named visibility を失う ([`§8.8`](#proxy-blind-spot) の deadline 版 — 失効性は優先度から導出できない)。 ∴ intake の時点で失効性を**第一級属性として明示的に encode** する ([`§8.11`](#downstream-net-intake-leverage) — intake で表現されない属性は下流の網が守れない)。
- **発火は期限前でなければ価値がほぼゼロ**: 通常の期限では「超過に気づく」 安全網にも挽回価値があるが、 失効型は超過に気づいても義務が戻らない。 surfacing は期限**前**に、 優先度・件数 cap と独立の named 表示で出す。
- **超過直後の救出窓**: 失効が即時でない運用 (= 相手方がまだ再割当していない・取消に猶予がある) では、 超過直後の短い窓に限り挽回可能性が残る — 超過側も「過ぎたから畳む」 でなく、 救出窓の間は surface を続ける。
- **失効が確定したら incident**: 「取り消されたから対応不要」 で流さない — どの経路・filter で期限前 signal が落ちたかを RCA してから閉じる ([`§8.21`](#noise-obligation-signal-sharing) の抑制交差が第一容疑)。

domain 別 instantiation (査読依頼 = 依頼→数日で自動取消・解任) = [`peer-review-workflow.md#invitation-intake`](../conventions/peer-review-workflow.md#invitation-intake)。 機械 semantics (= marker field・cap 除外表示・救出窓の実装) は個人層 tooling に残置 (= kernel-up / instance-down)。

origin: 2026-06、 研究 platform への招待 (返答期限つき) が priority 中で件数 summary に畳まれ 11 日埋もれた RCA (= 失効型 marker + cap 除外 + 救出窓を個人層で tooling 化した契機)。 sibling 観測 (2026-08): 査読依頼が応答期限内に人間に届かず自動取消 (= [`§8.21`](#noise-obligation-signal-sharing) origin と同 incident の deadline 軸)。 2 観察 ([`§9.8`](#single-observation-scope-check) 充足)。 2026-08-18 に個人層 home から本節へ昇格 (= 層 1 doc が層 3 home を参照できない registry 制約の解消)。

### <a id="lapsing-opportunity-intake"></a>8.23 失効型〆切つきの機会 — 義務網と応答網の谷間に落ちる opportunity class

任意参加の機会 (= 研究会・workshop・公募・応募窓) は**義務でも応答でもない**ため、 mail triage の主要な網 — 名指し検出 (= per-person proxy)、 義務 intake ([`§8.17`](#broadcast-obligation-blind-spot))、 既知 thread 追跡、 TODO 化済み期限網 — の**どの trigger も踏まない**。 しかも機会は典型的に**長 lead time + 失効型〆切** ([`§8.22`](#lapsing-deadline)) で届く: 告知は数ヶ月前、 行動〆切は開催日のずっと手前、 超過した瞬間に機会そのものが消える。 event/deadline 系 surfacing の horizon が短窓 (= 数日〜数週) だと「**早く告知されるほど検出不能**」 という逆行が生じる ([`§8.18`](#request-mail-two-date-axes) の変種 = 行動〆切軸が horizon の外に出る)。

failure の解剖 (3 点が独立に効く):
1. **網の谷間**: 義務網の trigger は「義務を認識した」、 名指し網の trigger は宛先/名前 — 機会 broadcast (= BCC「各位」) はどちらも踏まない。
2. **「読めば終わり」 規律の追認**: announcement を read 化で discharge してよいとする triage 規律は、 機会 class では intake 経路そのものを閉じる (= 判断が読んだ人の頭にしか残らない)。
3. **受け皿はしばしば既にある**: 参加 lifecycle ledger (= considering → applied → …) が存在しても、 「案内 mail → 検討 entry」 の変換規律が無ければ ledger には「たまたま気づいた機会」 しか載らない。

対策 pattern:
- **機会 intake 規律 (= [`§8.17`](#broadcast-obligation-blind-spot) の義務版と対)**: 〆切つきの機会を認識した同 turn で、 lifecycle ledger に検討 entry を立てる **or** 「検討しない」 を明示して閉じる (= declared skip)。 「読めば終わり」 arm から機会 class を明示的に除外する。
- **〆切抽出器は書式と距離の両方を audit**: (a) 早期告知が horizon 外に落ちないか (= first-seen surface / 窓連動)、 (b) 締切語の**前置/後置**など書式 variance に頑健か ([`§8.8`](#proxy-blind-spot) の書式 proxy 版)、 を test case に含める。
- **FP は分業で受ける**: 機会案内は高 volume ([`§8.21`](#noise-obligation-signal-sharing) の noise 圧と同源) なので「全案内 surface」 は noise 化する — 〆切を持つ mail だけ機械が surface + 参加検討の判断は人間、 の分業に切る。

reflex: mail triage / surfacing の網を列挙・設計するとき「**義務でも応答でもない、 〆切つきの機会はどの網が拾うか**」 を 1 行問う。 答えが「人間が読めば」 なら、 その class は網の外だと**宣言**する (= silent 死角を declared 死角に)。

origin: 2026-08、 地域研究会の案内 (= 初報 + リマインド計 4 通、 BCC「各位」、 参加登録・発表申込の段階〆切つき) が約 3 ヶ月・4 通全部不可視のまま発表申込〆切が silent 失効。 名指し網 (宛先圏外) / 義務網 (義務でない) / 〆切抽出器 (締切語前置 + 早期告知で horizon 外) / 未認識 backlog 段 (rolling 窓で walk 前に silent 退場) の 4 経路が**独立に**落ち、 最終 catch は主催者の 4 通目 (〆切 2 日前) だった。 本 class 直接観察は 1 + 隣接 class sibling 2 (= [`§8.17`](#broadcast-obligation-blind-spot) 義務 broadcast 1.5 ヶ月 / [`§8.22`](#lapsing-deadline) 査読依頼自動取消) — [`§9.8`](#single-observation-scope-check) は隣接 class 複数観察で充足と判断、 本 class 単独の再発で強化する。 instance (= ledger repo 名・triage 段の具体 arm・検出器実装) は個人層に残置 (= kernel-up / instance-down)。

### <a id="surfaced-not-consumed"></a>8.24 surface されても消費されない — silent 再表示の壁紙化と disposition 終端

[`§8.22`](#lapsing-deadline) は「失効型は期限**前**に named 表示せよ」 と要求するが、 named 表示は**十分条件ではない**。 毎 session 同じ行を silent に再表示する surfacing は、 数週間で**壁紙化**する (= 読者の脳が風景として filter する — alarm fatigue の表示版)。 壁紙化は 3 つの増幅因子で加速する:

1. **隣接遮蔽**: 同種の named crisis が隣の行で actively 進行中だと、 「その分野は今まさに全力でやっている」 という感覚が同〆切の sibling 行を飲み込む (= 表示は見えているのに認知が届かない)。
2. **表示文言の子守唄**: surface される item 自身の注記に「たぶん不要」 系の priming (= 「見送りの公算が高い」 等) が書いてあると、 全読者が毎回それを読んで次の危機へ移る。 安価な discharge 手 (= 1 問で決着する) が重い動詞 (= 「着手」) の下に埋もれていると特に致命的。
3. **判断〆切と行動〆切の同値化**: 「やるか判断する」 系 item の deadline を行動の〆切と同じ日に置くと、 表示が最高強度に達した時にはもう「やる」 選択肢が実行不能になっている (= 判断 deadline は行動 lead time 分だけ手前に置く。 [`§8.18`](#request-mail-two-date-axes) の判断版)。

対策 kernel: **surface は silent 再表示で循環させず、 明示 disposition で終端させる** — 失効が近い item は「act / 明示 defer / 明示 decline のどれかが記録されるまで surface を降格させない」 段に昇格させる (= 稼働実績のある同型 = mail triage の「未認識段が空になるまで準備完了としない」 規律)。 最終盤 (= 残数日) は**表示 channel 自体を変える** (= agent の session 注意経路から人間への直接通知へ) — 同じ channel の強度 escalation は壁紙化の続きでしかない。

reflex: surfacing 機構を設計・監査するとき「この表示は**何をもって消えるのか**」 を 1 行問う。 答えが「期限が過ぎたら」 なら、 それは通知ではなく風景である。

対策を実装に落とすときの 2 つの追加 kernel (= 2026-08、 上記 RCA の対策実装で確定):

- **defer は期限付きでなければ mute である**: 「明示 defer」 branch を無期限 flag で実装すると、 それは disposition ではなく恒久消音 spigot になり、 壁紙化と同じ病気を defer 側で再生産する。 defer record は**必ず期日を運び、 期日経過で自動失効して loud 側に復帰**させる (= 永久 mute を構造的に不能にする)。 parse できない defer record も loud 側に倒す。
- **通知 channel の dedup には 2 class あり、 互いの代替にならない**: (a) 「新規 / 昇格時のみ 1 回」 dedup は速報 channel — 既知のまま放置された item を**構造的に再通知しない**ので、 壁紙化した item には最初から届かない。 (b) 最終盤 channel は「窓内は 1 日 1 回/item 再通知」 class が必要。 (a) の channel が既に稼働していることは (b) の不在を埋めない — 「通知機構はもうある」 という監査結論は、 **その dedup がどちらの class か**を確認するまで下せない。

origin: 2026-08、 研究費公募の応募判断 TODO が 2 つの独立 surface 経路で 30 日間毎日 named 表示 (最終週は最高強度 + 実働中の同〆切案件の 1 行隣) されながら一度も消費されず学内〆を通過した RCA (= 機械 replay で表示履歴を verify 済)。 同月 sibling = 査読依頼が名指し horizon に 6 日 named 表示のまま未消費で自動取消 ([`§8.22`](#lapsing-deadline) origin の consumption 軸)。 対照の成功例 = 明示 disposition を要求する mail triage 段は同環境で機能し続けている。 [`§9.8`](#single-observation-scope-check) は同月 2 観察 + 対照 1 で充足。 instance (= 検出器名・ack field 実装・対策 ledger) は個人層に残置 (= kernel-up / instance-down)。

### <a id="detection-zero-location"></a>8.25 検出失敗の RCA は「ゼロの位置」を先に特定する — 能力の不在と trigger の不在を分離する

**rule**: 「検査が捕らえなかった」 incident の RCA では、 対策 (新機構・新台帳) を設計する**前に**、 捕捉ゼロがどの層のゼロかを分離する:

1. **standing 検査のゼロ** — 常駐機構が事前に捕らえた数
2. **自発起動のゼロ** — agent が該当 event の後に検査を**命令なしで**起動した回数
3. **命令起動の成績** — 人間が命令したとき、 同じ agent / 機構が捕捉したか

3 が正 (>0) なら**能力は在る** — 欠けているのは trigger 配線で、 対策は新機構でなく「event → 検査」 の配線 ([`§8.12`](#firing-surface-hierarchy) の発火面選定に接続)。 1 のゼロだけを見て「この領域は機械化不能」 「能力が無い」 と結論するのは誤診で、 重い対策 (新 ledger / 新検出器 / 新 platform) を作らせ、 軽い正解 (trigger 1 本) を見落とさせる。 逆に 3 もゼロなら能力問題が本物で、 trigger 配線だけでは閉じない — **どちらの処方かは分解するまで決められない**。

**捕捉統計の過圧縮も同時に分解する**: 「人間 N/N、 機械 0/N」 型の集計は (a) 検出 loop の**起動者** (b) 発見の**実行 agent** (c) **当該 event で発生した** vs **既存 latent を発掘した**、 の 3 軸を潰した lossy encoding。 born と発掘の混在は対策 scope を誤らせる (発掘は検査の**成功**であって失敗ではない — 「N 件も発生」 という alarm の過半が実は成功だったりする)。 起動者と実行 agent の混在は「機械側能力ゼロ」 の誤診を作る。 [`§4.2`](#self-rca-framing-minimization) の鏡像 (= あちらは圧縮が severity を過小に、 こちらは過大にも過小にも歪める — どちらも治療は同じで、 一次資料への分解)。

origin: 2026-08、 ある paper 磨き込み incident の cold-eyes RCA。 散文主張エラー 11 件が「人間 11/11・機械 0/11」 と自己申告されたが、 一次資料 (session transcript + commit 系列) の分解で 7 born + 3 latent 発掘 + 1 規約往復と判明し、 かつ人間が命令した directed sweep は 2 回とも実捕捉 (計 6 件)・agent の自発起動は 0 回 — 対策は主張台帳の新設から「手術 event → sweep」 の trigger 配線 1 本に縮んだ ([`paper-audit.md#relocation-rebinding-sweep`](../conventions/paper-audit.md#relocation-rebinding-sweep))。 sibling 系譜 = 検出器群が健全で signal を産出していたのに消費境界で落ちた RCA ([`§8.24`](#surfaced-not-consumed) / 産出≠消費) / gate が健全なのに frontend が honor しない ([`§8.15`](#enforcement-surface-frontend-survival)) — いずれも第一問が「機構を作れるか」 でなく「どのゼロか」 だった (3 incident 系譜、 [`§9.8`](#single-observation-scope-check) 充足)。

### <a id="disjunctive-finding-self-routing"></a>8.26 二択を提示する finding は判別証拠を同梱する — 枝の選択を消費側 recall に残さない

**rule**: 検出器の finding が「X か Y のどちらか」 という**選言** (= 例: 「対応が要るなら TODO 化、 決着済なら状態 field を migrate」) を提示するとき、 **どちらの枝が本命かを判別する安価な検査 (= 1 grep / 1 field read) が存在するなら、 その検査は検出器自身が実行して結果を finding 文面に焼き込む**。 判別を消費側 (= finding を読んで報告・対処する agent) に委ねると、 消費側は選言を**目についた片枝に潰して**報告する — 二択の存在自体は finding に書いてあっても、 「もう一方の枝を検査してから断定する」 は recall 依存の最弱発火面 ([`§8.12`](#firing-surface-hierarchy)) に落ちる。

- [`§8.24`](#surfaced-not-consumed) の続きの層: あちらは「finding が消費されない」、 こちらは「消費されたが**誤読される**」。 表示が届いても、 文面が判別労働を読者に残していれば誤消費は起きる。
- **判別検査が heuristic (= FP を含む) でも同梱する価値はある** — その場合は verdict でなく **検査順路の routing** として焼く (= 「証拠あり → まず閉じ忘れを検査、 裏取り前に『未対応』 と断定しない」 / 「証拠なし → 真の未対応が第一仮説」)。 severity は変えない。 最終の意味判定が人間側 floor に残ることを docstring に honest 明記する。
- reflex: 選言を含む finding 文面を書く (or 監査する) とき「**この二択、 読者はどちらの枝を先に検査すべきか — それを機械が 1 手で教えられないか**」 を 1 行問う。 教えられるのに文面に無いなら、 それは検出器の設計穴であって消費側の注意力問題ではない。

origin: 2026-08、 運用記録 ledger の「open 状態のまま N 日経過」 検出器。 finding は「未対応 or 状態 field の閉じ忘れ」 の二択を正しく提示していたが、 entry の action log には決着記録 (送信 id 付き) が既に書かれており、 消費側 agent は log を読まずに「未対応」 の枝で user に誤報告 → user が「返事書いたはず」 と catch。 対策 = log/notes の決着語 scan を検出器に追加し finding へ routing を焼き込み (retroactive + FP regression fixture 付き)。 上流因 (= 決着時に状態 field を閉じ忘れた記録者側) は当の検出器が既に backstop していた = ゼロは消費層のみ ([`§8.25`](#detection-zero-location) の分解を適用)。 instance (= 検出器名・regex・fixture) は個人層に残置 (= kernel-up / instance-down)。

## <a id="triage-and-subtraction"></a>9. Triage と subtraction — 規約システムの成長・代謝バランス

規約・hook を失敗毎に追加する運用は、時間と共に規約 load が肥大化し、古い規約が crowd out されて新違反を招く loop に陥る。2026-04-17 session で抽出した 3 つの対処原則。

### <a id="blast-radius-triage"></a>9.1 失敗の blast radius triage

失敗が起きたら反射的に prevention を設計する前に、blast radius を triage する:

| 級 | 例 | 応答 |
|---|---|---|
| **catastrophic** | secret leak、データ破壊、不可逆外部通信 (誤送信 / force push to main) | 最強クラスの機械的制御 (hook deny、pre-commit block、sandbox) |
| **material** | 設計方針の大幅逸脱、作業成果の消失リスク、再実行困難な手戻り | 警告 hook + 規約の明文化 |
| **annoyance** | 4 文字タイプ分の correction で済む失敗、in-session で即復旧できるもの | **何もしない** (in-session correction で受容、prevention engineering しない) |

**annoyance 級の失敗に catastrophic 級の対策を投入しない**。規約追加・hook 追加は認知負荷増加を伴う投資であり、reward (防げる失敗) が cost (load 増加) を下回る場面が多い。

### <a id="asymmetric-reflection-bias"></a>9.2 Asymmetric reflection bias

規約・hook・feedback memory は構造的に **失敗応答のみ** を蓄積する。成功時に何が機能したかは記録されない。結果:

- 規約は予防一辺倒で肥大化
- 「この規約は実際に機能しているか」「違反されなくなったから削除可か」の問いが立たない
- 古くなって不要になった規約も、危険を感じて触れない

これは病気だけ観察する医学と同型の歪み。

### <a id="subtraction-trigger-design"></a>9.3 Subtraction trigger の設計

肥大化を防ぐ方法は「成長を止める」ではなく「**代謝を入れる**」:

1. **四半期 review**: 直近 3 ヶ月で違反されなかった規約を洗い出し、削除候補にする
2. **Hook の発火頻度集計**: 一度も発火していない hook は削除候補
3. **Memory の棚卸し**: 3 ヶ月以上触られていない memory エントリは削除候補
4. **Migrate vs delete の判断**: 「git 同期先に migrate」は defer の一種。削除で決着する選択肢を先に検討する

Trigger 自体を自動化できればなお良い (例: `claude-config/scripts/` に audit スクリプト)。手動でも四半期 review を cron / scheduled task で予約する。

### <a id="preference-approximation-gap"></a>9.4 Preference-approximation gap

規約は user の無限 context-dependent preference を有限の symbolic rule に圧縮する lossy compression。近似ギャップは構造的にゼロにならず、新しい状況で必ず新しいギャップが surface する:

- 今日のギャップを埋めても、別のギャップが別の場所で開く
- 規約追加は「ギャップを埋めた」ではなく「別ギャップに移した」

この認識を持つと:
- 規約追加ラウンドを **net-zero 近似の作業** として相対化できる (「完全にする」expectation を下げる)
- 代わりに機械的制御 (§8) と subtraction trigger (§9.3) に投資する方が合理的と見える
- 「規約を完備する」という無限後退を避けて、acceptable failure rate を認める

### <a id="closed-loop-mutual-reinforcement"></a>9.5 Closed loop: 規約構造と Claude 応答構造の相互強化

規約ファイルは structured (表 / 箇条書き / セクション)。Claude の応答も structured (depth レイヤー / カテゴリ分類 / ランク付きオプション)。両者の構造が match すると、**相互強化ループ**を形成する:

1. Claude が structured 規約を読む
2. Claude が structured 応答を生成
3. User が structured 応答を見て structured な追記で規約を追加
4. Load 増加 → 古い規約が crowd out → 新違反
5. 1 に戻る

このループから出るには、片方が **unstructured に振る舞う必要**がある:

- User 側: 「今回は何もしない、受容する」を選択する局面を増やす (§9.1 triage の実運用)
- Claude 側: option list を生成せず 1 つの position だけ述べる局面を増やす (§9.7 参照)

### <a id="subtraction-forms"></a>9.6 Subtraction の形態: 削除 > migrate > 規約追加

違反への応答として自然に考えつく対応の好ましい順序:

| 対応 | コスト | 効果 | リスク |
|---|---|---|---|
| **削除**: 既存規約・memory・hook を除去 | 低 | load 減少 → 古い規約が活性化 | 情報損失 (git log で復旧可) |
| **Migrate**: 情報を別の場所に移動 | 中 | 同内容だが場所が変わる | accumulation が温存される / defer の一形態 |
| **規約追加**: 新ルールを書く | 中 | 新 cue を provide | 既存規約が crowd out、§9.5 ループを強化 |
| **Hook 追加**: 機械的制御を増やす | 高 | 該当状況で強制 | 誤検出、運用負荷増 |

**原則**: 違反を受けたとき、反射的に規約追加に向かわず、以下の順で検討する:

1. 既存の類似規約を **削除** (古くて違反されないルール、重複エントリ、毒 template)
2. 次善策として **migrate** (ただし「削除で済ませられないか」を必ず先に自問)
3. 既存規約で覆えない novel 失敗のみ **追加**
4. catastrophic 級のみ **hook 化**

**Migrate は defer の一形態** — 「とりあえず別の場所に動かした」は accumulation 温存であり、将来の棚卸しタスクを生む。削除で決着する選択肢を先に評価する。

### <a id="diminishing-returns-detection"></a>9.7 Diminishing-returns detection と meta-loop 離脱 (Claude 側の規律)

LLM は「もっと深く」「もう一段」の push に対して resistance がない — 疲れない、飽きない、自尊心で突っぱねない。結果、**Claude 側から会話の diminishing returns を自発的に announce しないと meta-loop が収束しない**。また meta 議論が伸びるほど、**元のタスクから離脱した procrastination** になりやすい (規律改善の議論が本業を食う状態)。

Claude 側の規律 (work-discipline.md 相当):
- 同じ方向の push が 3 回連続 → 「diminishing returns かもしれません」と打診
- Meta 議論が元のタスクから 5 turn 以上離脱 → 「本線に戻りますか」と提案
- 「深く」系の push で生成された階層が 4 以上になったら、新規性 vs paraphrase を自己評価して honest に述べる
- Option list の生成を自動応答とせず、明確な position を 1 つ取ることを優先する
- 「何かアクションしないと」圧 (§8.5) を検出したら、**そのアクションが rule 追加 / memory 書き込みに向かっていないか** を一度立ち止まって確認

2026-04-17 session で実演: 6 turn の「深く」push に応えて Level 11 まで階層を生成、途中から paraphrase 成分が増加していたことを自己観察。次回は 3 turn 目で push-back を試みる運用。

---

### <a id="single-observation-scope-check"></a>9.8 単一観察から構造対策に飛ばない (scope 確認先行)

違反・不具合・ユーザー報告を受けた時、反射的に構造的対策 (新 rule / 新 hook / abstract framework) を設計する前に **現象の scope を確認する**。典型的な failure mode:

1 回の観察 → パターン仮説 → 構造対策の設計・実装 → 後から「実は scope 違い」が判明 → revert (実装コスト + 規約追加コスト + revert コスト + ユーザー説明コスト が全て無駄)。

**scope 確認の質問**: (a) 観察は独立した複数事例か 1 事例か? (b) ユーザーが継続的に直面する場面か偶発的か? (c) 対策の前提はユーザーの実運用に合致するか?

**適用例 (2026-04-17)**: odakin 環境で Haiku 使用時に日本語フォールバック観察 → 2 軸配置原則 (cross-machine × always-attention cell に CLAUDE.md inline が必要) を設計・実装 → odakin が「Haiku は一生使わない」と scope 確認 → 前提崩壊で全 revert。scope 確認を先行していれば対策設計も revert も不要だった。

§9.1 triage との組み合わせ: annoyance 級 × scope 不明 = **対策せず受容が基本**。material 級以上 × scope 確認済 = 対策設計へ。

### <a id="new-definition-self-violation-probe"></a>9.9 新しい定義は自分の origin 例で破られやすく、その自己違反は定義の under-specification を指す probe

新しい分類・定義・原則を導入する fix は、**それを説明するための origin 例（適用事例・動機の story）の中で**最も破られやすい。注意が「原則を正しく言明する」に向き、それを照らすはずの具体 instance を **同じ定義で rigorous に bin する**作業に向かないため。

さらに重要なのは: **自己違反は単なる注意 slip ではなく、定義が under-specified な seam を指す probe** である。原則を破った当の instance こそ、定義が暗黙に 2 つ（以上）の異なる物を 1 語に潰していた箇所を露出している。

**Reflex:**
- 新しい定義を ship する前に、**それが名指す全 concrete instance（特に origin 例）に self-apply** して bin し直す（既存の「直前に書いた discipline を同 session 内で self-apply scan」を、新定義の例に向けて狙い撃つ）。
- 自己違反を捕まえたら、**その instance を直すだけで終わらせず、露出した「欠けている区別」を定義に足す**（patch でなく refine）。

**適用例 (2026-06-13)**: §2.3「SoT の read 側」を新設した直後、その origin 例で external service（予約サイト）を SoT 扱いした。原因は §2.3 v1 の「source document」が **「内部の非選択 store」と「制御不能な external source」の 2 つを 1 語に潰していた**こと。user 指摘で external source の区別を §2.3 に追加 = 自己違反が taxonomy の gap を probe した実例。RCA そのものを書く act の中で、その RCA が戒める分類誤りを再演した（= 「直前 discipline の self-apply」の specific 化）。

### <a id="completeness-audit-add-bias"></a>9.10 完全性 audit の add-bias — 「何が欠けているか」 frame が低価値・mis-weighted な追加を製造する

coverage/completeness を目的とする audit pass (「どの cross-ref が欠けているか」「何を記録し損ねたか」「全 instance を繋いだか」) は構造的に**追加へ偏る**: frame 自体が「埋めるべき gap」 を探すので、 関係の薄い接続や低価値な finding を「欠落」 として**製造する**。§9.2 (= corpus が失敗のみ記録 → 予防一辺倒) の sibling だが mechanism が違う — 蓄積の非対称でなく **audit の問いの非対称** (「足りないものは?」 は常に何かを返す)。

**cross-ref 域での具体 failure mode**: 一般原則 (= 親) の本文から tangential な niche instance (= 子) へ**下向き pointer** を張りたくなる。二重に悪い: (a) **重み付けの転倒** — 親の surface に niche 子を昇格させ一般則が domain-specific に見える / (b) **方向の転倒** — この system の流儀 (§1 配置原則 / §2 定義は home / kernel-up・instance-down) は具体→一般へ**上向き**。親が子を列挙し始めると全 niche 子への下向き pointer が溜まりスケールしない。これは §16 (= load-bearing でないものを prominent に置く mis-weighting) の audit 域での発現でもある。

**restraint (= reflex)**:
- **完全性は「instance が一般 home へ上向きに指す」 で満たされる、 親が instance を列挙して満たすのではない。** 接続を記録するなら子側に置く。
- **「missing cross-ref / 欠落」 finding は relevance bar を通す**: 「2 つの考えが触れる」 では不十分、「読み手の判断を変える load-bearing な接続か」 を問う。触れるだけなら張らない (= over-cross-referencing は §2 dedup と逆向きの bloat)。
- audit の goal を「未接続を全部繋ぐ」 でなく「**load-bearing な欠落を見つける**」 に framing し直す (= §9.8「単一観察から構造に飛ばない」 の audit-output 版)。

由来 (2026-06-17): §16 を新設した直後の 4軸 sweep が「§16 が物理ノートの添字規約への cross-ref を欠く」 を missed-cross-ref finding として出し、 一般則 §16 から niche な数式記法規約へ下向き pointer を張った。 user 指摘「超絶マイナーな子と一般則なら後者が親、 親に子を並べるな」 で撤回。 **finding 自体が completeness-frame の add-bias product だった** (= §9.9 的に、 audit を書く act が自分の audit に §16 を踏ませた)。

---

## <a id="file-role-architecture"></a>10. File-role architecture — context 効率のための auto-load tier 設計

2026-04-17 の subtraction + compression session を経て抽象化した、cross-machine 規約システムの file 配置原則。LLM の session 冒頭 context 量が有限なので、**同じ情報量を保ちながら auto-load を削減する**設計。

### <a id="four-tier-classification"></a>10.1 4 tier 分類

| Tier | 性質 | 例 | auto-load? |
|---|---|---|---|
| **T0: harness auto-load** | session 冒頭に強制 load | `CLAUDE.md`, `MEMORY.md` | ✓ (全 session) |
| **T1: regulation table 必読** | 「必ず読む」指示が明示的 | `work-discipline.md`, `push-workflow.md` | ✓ (Claude が table 経由 active read) |
| **T2: regulation table 条件付き** | 特定 task 発生時のみ読む | `email-style.md`, `paper-style.md`, `user-profile.md` 等 | △ (task 関連時のみ) |
| **T3: pointer-only** | regulation table 不記載、pointer 経由 | `incidents.md`, `staging-incidents.md`, `leak-incidents.md`, 各 `DESIGN.md` | ✗ |

### <a id="tier-criteria"></a>10.2 切り分け基準

「この content は毎 session 読まれる必要があるか?」を自問する:

- **rule 定義本体 / trigger 条件 / How to apply** → 必要 → T1 or T2
- **rule の supporting narrative (過去事例、具体 file path、exact sequence)** → 不要 → T3 に隔離
- **meta-procedure (ファイル追加手順、staging lifecycle 等)** → 不要 → T3 (DESIGN.md)
- **archive 目的の session log** → 不要 → T3 (日付付きファイル、規約 table 不記載)

### <a id="narrative-extraction-pattern"></a>10.3 narrative 抽出 pattern (T1 → T3)

T1 file が肥大化した時の救済 method:

1. 各 rule の「過去事例」block を T3 の narrative archive file に抽出 (chronological)
2. T1 側は 1 行 pointer に置換 (「詳細 → `<archive>.md` §YYYY-MM-DD」)
3. archive 側に「Related rules:」逆 link を置く

**例**: work-discipline.md の 4 過去事例 block (Memory gate / $-chat / 汎用原則 / Meta-loop) と push-workflow.md の 3 過去の失敗事例 を個人層の incidents 記録に集約して T1 から pointer 化 (2026-04-17 実施、net -~40 lines T1 auto-load)。

### <a id="tier-failure-patterns"></a>10.4 失敗 pattern

- T0/T1 に narrative を詰めると context 圧迫 → autocompact 頻発 (2026-04-17 odakin 環境で実地観察、1 日で +468 lines T0/T1 拡大 → autocompact 頻度急増)
- T1 の rule 内に incident 詳細を embed すると後から T3 抽出に手間

### <a id="tier-lifecycle"></a>10.5 Tier 間 lifecycle

content は tier 間を移動しうる。2026-04-17 odakin-prefs で観察された例:

- **T0 → T1**: MEMORY.md (T0) から work-discipline.md (T1) へ規律を移す (cross-machine 要件を満たすため、§5 参照)
- **T1 → T3**: narrative 抽出 (§10.3)
- **T1 内部 sub-tier**: rule 本体を T1 に残し、meta-procedure を `DESIGN.md` (T3) に移す

**incidents archive の 3-stage lifecycle** (odakin-prefs で実装):
`staging-incidents.md` (未結晶、2 件目待ち) → 結晶化 → `work-discipline.md` rule (T1) + narrative を `incidents.md` (T3) に移管。

### <a id="tier-application-example"></a>10.6 適用例 (2026-04-17 odakin-prefs)

- T0: `CLAUDE.md` (125→108 lines)、`MEMORY.md` (100→41 lines)
- T1: `work-discipline.md` (268→321 lines、新規 7 rule 追加後に -40 の narrative 抽出)、`push-workflow.md` (87→85 lines、3 incident narrative 抽出後)
- T2: 既存 regulation table 配下 10+ ファイル
- T3 (新規): `incidents.md` (209 lines, 19 narratives)、`staging-incidents.md` (33 lines, 2 entries)、`DESIGN.md §2026-04-17 系 2 entries` (規約追加手順 + work-discipline.md 運用方針)

結果: T0+T1 auto-load 569 (pre-restructure 推定) → 555 lines (post-restructure)、T3 に ~600+ lines の narrative/meta を隔離保持 (情報損失なし)。

### <a id="auto-context-byte-budget"></a>10.7 auto-context byte budget (行数 proxy からの脱却)

Tier 切り分けと並行で、**T0+T1 の byte 総量**を測定する。LLM context は token (≈ 4 bytes) で measured されるため、行数 threshold だけでは autocompact 頻度を説明できない。行数を満たしていても 1 行 あたりの密度が高いと context 消費は膨らみ、session 当たりの autocompact 回数を早める。

**観測指標** (参考値、環境により変動):
- T0+T1 合計 **50 KB 未満** → autocompact 稀
- T0+T1 合計 **100 KB 超** → 1 session 中に 1-2 回 autocompact
- 1 ファイル内 **line 当たり 200 bytes 超** → dense 化の疑い (descriptive / narrative が embedded)

**処置**: 行数 threshold を満たしているが autocompact 頻発する場合、**byte 密度** を疑い、§7.3 Description / Judgment 境界 + §10.3 narrative 抽出を実行する。inline 実装 how、変遷履歴、冗長な注記は判断文を残し DESIGN.md / T3 への pointer に delegate する。

**事例** (2026-04-18 LorentzArena 2+1): SESSION.md 94 行 / 23.8 KB (line density ~253 bytes) → 75 行 / 6.6 KB (line density ~88 bytes) へ圧縮。inline 実装詳細 (migration / ghost 物理統合 / worldLine 二分探索 etc.) を DESIGN.md 各節の pointer に delegate した結果、行数は -20% だが byte は -72%。CLAUDE.md も同系の dense 部 (ネットワーク migration detail、アーキ表 long cell、主要機能 bullets) を pointer 化して 371 → 357 行 / ~45 → ~36 KB。**line count threshold を守っていても byte で見ると context-heavy** という観測が §7.7 diagnostic の新 row を動機付けた。

**運用**: SESSION.md を書き足す時は `wc -c` で byte を即確認。8 KB 超過が見えたら dense row を pointer に差し戻す ( retroactive reorg ほど大掛かりでなく、その場で逆流を止める習慣で充分)。

### <a id="deletion-delegation-trap"></a>10.8 削除・委譲判断の trap

tier 化 (§10.2) と byte budget (§10.7) で「どのファイルを減量するか」の方向性は見えるが、**どの行を削るか**の判断には系統的な失敗パターンがある。2026-04-18 の claude-config への §7 retroactive reorg 自己適用で抽出。

**Tier-direction asymmetry**: 委譲の効果は **tier の下り (T0→T1/T2、T1→T2/T3)** のみで発生する。T2→T2 や T3→T3 の横ずらしは auto-context bytes を減らさず、grep 手間だけ増やす ROI ゼロの作業。「file を分けると綺麗になる」という美意識で横ずらしに手を出すのは **autocompact 削減目的の文脈では anti-value**。委譲判断では先に「委譲先の tier が委譲元より低頻度か」を問う。

**T0/T1 chain pre-check**: T0 ファイルを圧縮する前に、T0 から link される T1 群が auto-context byte に含まれることを確認する。T0 の 1 行が dense な T1 表を指す pointer だった場合、T0 削減は総量 1 行分しか減らさない。**T0 の line count だけ見て判断すると miss する** — T1 の dense 行を pointer 化する方が ROI が高いケースが多い。

**Grep-substitute value**: auto-load された表 / 小辞典 / レジストリは Claude の session 内で **pre-computed grep cache** として機能する。削除/委譲すると、そのデータが欲しい時に `grep` / `Read` tool call が発生し、per-session tool invocation cost が増える。**auto-context byte の節約 vs session 当たり tool call 増加** を天秤に掛ける。「頻繁に参照される table」「description column が code に存在しない table」は auto-load のまま残すのが合理的。

**削除提案の self-correction** (2026-04-18 事例): LorentzArena 2+1/CLAUDE.md の ゲームパラメータ表 (87 行) を「`constants.ts` が正本なので参照置換で ROI 高い」と初期判断したが再評価で **anti-value** と結論。理由: (1) byte 節約は autocompact budget の 0.2% で不可視、(2) 説明 column は code に存在せず table 全体を崩さないと抽出不能、(3) grep-substitute 価値大 (constants.ts には numeric value のみで human-readable 説明が無い、per-session Read コスト発生)。**最初の ROI 判断は byte savings のみで grep cost と description column loss を見落としていた**。委譲判断では byte savings だけで決めず、使用頻度 × grep-substitute cost × description column 抽出可能性 の三方視点が必要。

**DESIGN.md 分割閾値** (§10 の派生指標): 単一 DESIGN.md が以下のいずれかを満たしたら分割検討:
- 2000 行超 / 150 KB 超
- domain が独立変化するようになった (例: 物理と描画が別 sub-project 化)
- `grep` で見出し anchor が曖昧になる (同名見出しが複数 domain に存在)
- **SESSION.md / CLAUDE.md などから DESIGN.md §X pointer が密集**していて session 冒頭に follow-read で丸ごと読まれがち — 行数が 2000 未満でも split で「session ごとに該当 domain 1 sub-file のみ read」にできれば効果大 (2026-04-18 LorentzArena 2+1/DESIGN.md 1371 行の split はこの基準で発動)

分割先の配置原則は §1 (影響範囲の最大公約数) + §10.2 (tier 維持)。分割は **一方向の decision** — 再結合は別の reorg event として扱うため、分割前に条件の複数を満たすまで保留する。

**Self-application discipline**: 規則を claude-config で定義する commit には、その規則を **claude-config 自身に同時 apply する pass** を含める。2026-04-15 に §7 (retroactive reorg) を定義、LorentzArena に 2 回適用 (2026-04-15 / 2026-04-18) したが claude-config DESIGN.md 自身への適用は 2026-04-18 まで遅延し、4 entries (symlink 化 / scrubbing 見送り / 自己言及的 odakin / EXPLORING 分離) が冗長に残存していた。**「規則を作ったリポが規則を守っていない」状態は self-consistency を損なう**。規約追加 commit では `-- claude-config/` に類似 pattern が残っていないか grep する工程を入れる。

---

### <a id="code-canonical-doc-dedup"></a>10.9 Code を canonical とする doc dedup pattern (§10.8 と併読)

doc 側の table が code facts を duplicate している場合 (parameter 値 / TypeScript 型 / enum 等)、**canonical source は code**。doc は code への pointer を置くだけで、値や型の table は再掲しない。duplication は以下を招く:

- **drift risk**: code 更新時に doc 同期漏れ、値・型が食い違う
- **auto-context 浪費**: T0/T1 の auto-load doc に table が入っていると session ごとに token 消費

**⚠ §10.8「削除・委譲判断の trap」の warning を先に適用せよ**: description column が code (JSDoc 等) に存在せず doc 側にしかない場合、**dedup は anti-value**。byte 節約が 0.2% の invisible savings にしかならず、grep-substitute cache としての table 機能 + description の情報そのものを失う。2026-04-18 事例の LorentzArena パラメータ表は §10.8 で anti-value と判定されているにもかかわらず、後続の Level-2 migration (commit `cb3ca94`) で削除実行された。**constants.ts の JSDoc coverage を確認せずに削除すると情報損失**。

**安全に適用できる場面** (§10.8 warning を通過する場合):
- code 側に JSDoc / inline comment が充実しており description column の再現が不要
- table の grep-substitute 利用頻度が低い (session ごとに一度も参照されない)
- byte savings が 5% 以上の有意な減量

**pattern** (warning 通過後):
- 値・型の table を doc から削除
- 「canonical は `src/X.ts` (JSDoc + section コメントで分類)」という 2 行 pointer に置換
- category 名リストが必要な時は値なしで列挙

**2026-04-18 LorentzArena**: 2+1/CLAUDE.md から Parameters table (80 行) を削除し `constants.ts` pointer に移行。**§10.8 の事例が示すように初期 ROI 判断は再検討対象**。次 session で constants.ts の JSDoc 網羅性を確認し、description column が失われているなら docs/architecture.md に restore する判断が必要。

### <a id="claudemd-chain-nested-autoload"></a>10.10 CLAUDE.md chain の nested auto-load (Claude Code 実装依存)

Claude Code は CWD から上向きに `CLAUDE.md` chain を全て auto-load する。sub-project で作業する場合、例えば CWD = `~/Claude/LorentzArena/2+1/` なら:

- `~/Claude/CLAUDE.md` (user-level、通常 symlink to personal prefs)
- `~/Claude/LorentzArena/CLAUDE.md` (repo root)
- `~/Claude/LorentzArena/2+1/CLAUDE.md` (sub-project)

の**全てが 1 session の session-start context に入る**。chain の合計サイズが dominant component になりやすく、sub-project の CLAUDE.md が大きいと autocompact 頻発。

**対策**:
- 各層を role-limited に保つ (user-level = 全体規約 table、repo root = リポ overview、sub-project = 固有 orientation)
- sub-project CLAUDE.md は commands + preview quirks + architecture 超要約 + pointers の ~80–100 行に収める
- 詳細は同階層の `docs/` 配下に置き (T3)、CLAUDE.md から pointer

**2026-04-18 LorentzArena 実証**: `2+1/CLAUDE.md` 364 → 97 (-267 lines)、chain 全体 505 → 238 (-267)。

### <a id="super-summary-pattern"></a>10.11 「超要約 (super-summary)」pattern

slim 化した CLAUDE.md には「アーキテクチャ超要約」section を 1 つ置く。**5-8 項目 × 1 行 (+ 詳細は `docs/architecture.md §X` pointer)** で session 冒頭に orientation を確実に供給。

**効果**: pointer を辿らない session (軽 task / 小モデル / 慣性で素通り) でも、主要 dimension (rendering / physics / network / state / message / parameters 等) の 1 行要約は context に入る。「詳細は辿って、全体像は inline」の 2 層化。

**設計基準**:
- 各行は後続の詳細読みの entry point として働く (キーワード + 1 文)
- 具体値・table は禁止 (それは code/docs 側の仕事)
- 超要約だけで session が成立する task (軽い修正、定型作業) がある程度カバーできること

**例** (2026-04-18 LorentzArena 2+1/CLAUDE.md §アーキテクチャ超要約): 描画 / 物理 / ネットワーク / State / Message / Parameters の 6 項目、各 1-2 行 + 詳細 pointer。

### <a id="migration-level-ladder"></a>10.12 Migration level の階段

単発ではなく**多段階 migration** として構造化すると健全:

| Level | target | 典型的な savings |
|---|---|---|
| **Level 0**: cleanup | 削除 + memory 整理 (§9.6 subtraction order) | 数十 lines |
| **Level 1**: dense content → DESIGN.md pointer 化 | CLAUDE.md 内部で重い節を pointer へ置換、DESIGN.md は auto-load 外 | ~100 lines |
| **Level 2**: reference content → docs/ 分離 + code canonical | architecture / params / schema を `docs/architecture.md` + code pointer に | 数百 lines |
| **Level 3**: task-specific docs を最小化 | T2 regulation files (email-style.md 等) の重複排除 | 十〜数十 lines |

各 level は独立に実施可。下の level ほど radical で savings 大きい。**対象 CLAUDE.md が 300+ 行で session 立ち上げ速度が体感悪化しているなら Level 2 が費用対効果最高**。

---

## <a id="in-plan-exploration-trail"></a>11. In-plan exploration trail — single-session walkback の保存

§6 で establish した DESIGN.md / EXPLORING.md 分離は **cross-session 探索** (= EXPLORING にエントリを残し、 後で結晶したら DESIGN に promote) を扱う。 これとは別軸で、 **同 session 内で plan が iteration を経て複数案を撤回しながら最終決定に着地する** ケースの content保全 pattern を 2026-05-06 LorentzArena NPC 非対称 plan で抽出。

### <a id="walkback-trail-disappears"></a>11.1 問題: walkback の trail が plan close 時に消える

長 session で plan を立てて iterate するとき、 以下の dynamics が起こる:

1. 初期提案 (= A 案) を起こす
2. user feedback で問題発覚、 修正案 (= B 案) を提案
3. B 案を実装する形で plan を rewrite (= A 案の文章を上書き)
4. 更に iterate して B も撤回、 C 案で最終確定
5. plan を close

このとき plan には C 案だけが残り、 **A → B → C の walkback trail が消える**。 しかし trail こそが「なぜ C なのか」 の理解に必要 — 後の reader が「A や B はなぜダメだったのか?」 を再質問する元手になる情報が失われている。

### <a id="exploring-md-difference"></a>11.2 §6 EXPLORING.md との違い

§6 は **「未決定の探索」 を DESIGN.md と分離**するため EXPLORING.md を作る pattern。 探索が結晶したら DESIGN.md に promote、 古い候補は消す。

本節 §11 は **「決定済 plan 内の walkback 保存」** で、 plan は decision form で close するが decision に至るまでの撤回経緯を残したい。 EXPLORING.md には行かない (= もう探索じゃない、 plan は close する) し、 plan 本体に trail を埋め込む。

### <a id="exploration-trail-section"></a>11.3 解決: plan §1.6 etc. に「探索過程」 セクションを置く

plan の §1 (= 思想・前提) の subsection (例: §1.6 「探索過程」) に、 session 内 iteration の trail を時系列で記録:

```markdown
### §1.6 探索過程 (= YYYY-MM-DD session 内の back-and-forth)

「なぜ <最終案> に着地したか」 を後の reader が再現できるよう、 探索の back-and-forth を記録。

**探索 0 (= 出発点)**: <初期提案、 動機>。 → <この insight は終始一貫して採用された / 撤回された >

**探索 1 (= <発見の名前>)**: <修正案、 framing>

**(<撤回案>) の撤回**: <撤回理由、 false premise なら明示>

**探索 2**: ...

**探索 N (= 最終形)**: <着地>。 要素分解:
- A 軸 = ...
- B 軸 = ...

**思想 trail の core**:
> <最終案を導出する N つの insight の統合 framing>
```

### <a id="when-to-write-trail"></a>11.4 適用判断: いつ §1.6 を書くか

trail 保存に値するのは「**撤回された案が plan close 時点でも反省的価値を持つ**」 場合のみ:

- ✓ **書くべき**: false premise で撤回された案 (= 後の reader が同じ premise で同じ案を再提案する risk)、 user-side の structural insight で撤回された案 (= why の部分が valuable)、 「(α)/(β)/(γ)」 のような複数候補から 1 つに絞った経緯
- ✗ **書かない**: 単純な typo / 計算ミス修正、 user の好みの変更だけ、 探索過程と関係ない実装 bug

**rule of thumb**: plan close 時に「`§11 やらないこと` に rejected proposal を追加するか?」 と問う。 追加するなら §1.6 にも探索の trail を残すと整合的 (= rejected proposal の rationale が trail に紐づく)。

### <a id="rejected-alternatives-relationship"></a>11.5 §11 「やらないこと」 との関係

plan の §11 「やらないこと」 (= rejected alternatives + 却下根拠 + 将来再開 trigger) は **decision-form の rejection 記録**。 §1.6 探索過程は **process-form の trail**。 両者は重複しない:

- §11.X: 「✗ <案>: 主張案 = ...、 却下根拠 = ...、 将来再開 trigger = ...」 (decision)
- §1.6: 「探索 N で <案> を提案、 <発見> で撤回」 (process)

§11 だけだと「却下根拠は分かるが、 そもそもなぜ提案されたのか?」 が見えない。 §1.6 だけだと「将来また同じ案が出たらどう判断するか?」 の re-decision 材料がない。 両方あって初めて「**なぜ提案されたか + なぜ却下されたか + 将来再開条件**」 が一貫した narrative として読める。

### <a id="trail-application-example"></a>11.6 適用事例

- **2026-05-06 LorentzArena NPC 非対称 causality plan** ([`plans/2026-05-06-npc-asymmetric-causality.md`](https://github.com/sogebu/LorentzArena/blob/main/2%2B1/plans/2026-05-06-npc-asymmetric-causality.md) §1.6): user の Bug 14 propagation race 議論からの分岐で、 (I) NPC 非対称 → (II) dead = 死亡時時空点 → (II'') dead-skip 完成 → (II''') mean formula + self 包含 の 4 案を経て (II)/(II'') の 2 段 walkback で (I) + (II''') + (III) に着地。 (II)/(II'') 撤回理由 (= false premise 発見、 user の structural insight) を §1.6 に記録、 §11.12 「やらないこと」 に対応する decision-form rejection と紐づけ。 後の reader が plan を読むだけで「なぜ §1 が dead を virtualPos で寄与させる framing なのか」 を再構築できる

---

## <a id="monitoring-list-scope-marker"></a>12. 監視 list の scope marker — 「監視」 と「禁止」 の categorical 分離

### <a id="monitoring-scope-pathology"></a>12.1 観察された pathology

DESIGN.md / 設計 docs で「**drift 監視のため定期 re-grep 推奨**」 のような **list 形 audit checklist** を運用していると、 list が implicit な scope を持って blind spot を生むことがある。

具体例: list の entry が全て「docs (= CONVENTIONS.md / conventions/*.md)」 に偏っていて、 「scripts / hooks / setup.sh 等の executable surface」 が暗黙のうちに対象外扱いされる経路。 list の前文には「定期 re-grep」 とあるだけで、 (a) 何の category を対象に grep するか、 (b) 何が categorically 対象外か、 が明示されていない。 結果: 同 class の violation が executable surface に蓄積、 「list で監視しているから大丈夫」 という錯覚で audit が skip される。

### <a id="monitoring-vs-prohibition-separation"></a>12.2 「監視」 と「禁止」 の categorical 分離

ある violation class に対して、 surface ごとに対処レベルが異なる場合がある:

- **監視** (= soft、 list-based、 doc 内手作業 grep): **意図的に許容している記述** に適用、 drift 検出は人手 / scheduled-task で行う
- **禁止** (= hard、 mechanism-enforced): hook / pre-commit / regex / CI で機械的に block、 violation は merge されない

両者は categorical に分離されるべきで、 同 list に混在させると論理が壊れる。 例えば「docs 内の odakin 名言及」 は 「監視」 (= 意図的に置いている、 削除トリガー で発火)、 「executable code 内の odakin 名言及」 は 「禁止」 (= layer-1 audience contract 違反、 即修復対象)。

### <a id="explicit-scope-marker"></a>12.3 解法: explicit scope marker を必須化

監視 / audit list を書くときは、 list の前文または冒頭 row に **explicit scope marker** を含める:

| 要素 | 例 |
|---|---|
| **対象 surface の enumeration** | 「本 list は CONVENTIONS.md と conventions/*.md (= **docs**) 内の意図的記述のみ対象」 |
| **categorically 除外される surface の enumeration** | 「scripts/, hooks/, setup.sh 等の **executable code** は本 list ではなく即修復対象」 |
| **除外理由** | 「executable は foreign user の machine で実行されるため、 audience contract 違反は監視ではなく禁止」 |
| **境界条件で迷ったら何をするか** | 「迷ったら本 list ではなく hook / pre-commit に投げて mechanism 化」 |

scope marker は **list の機能の一部**。 marker 無しの list は「実は何を監視しているか暗黙」 で、 数か月後の reader が誤って scope 外も含むと解釈する経路を持つ。

### <a id="monitoring-scope-origin"></a>12.4 由来

2026-05-10 claude-config self-audit で `DESIGN.md §「自己言及的 odakin 記述」` list (= 4 entries の docs 監視 list) が hooks / scripts / setup.sh の同 class violation を見逃したケース。 list 自身は「drift 監視のため定期 re-grep 推奨」 と書いてあったが、 暗黙 scope = docs のみだったため、 同 session の `hooks/memory-guard*.sh` の `odakin-prefs/` literal は list に登録されておらず、 final cross-cutting sweep で初めて発見された。 修復として list 前文に explicit scope marker を追加 (= claude-config commit `e3179c5`)、 「executable code 内の literal は本表ではなく即修復対象 (= 監視ではなく禁止)」 を categorical に明示。

### <a id="monitoring-scope-applicability"></a>12.5 適用範囲

- audit / drift / monitoring / re-grep / track と書かれた list 全般
- list が複数 surface (= docs + code + config 等) にまたがる候補 violation の subset を扱う場合
- 「意図的記述」 と 「bug」 を同 class violation で区別する必要があるとき (= surface 別に対処レベルが異なる typical case)

### <a id="monitoring-scope-related-rules"></a>12.6 周辺規律

- §3 「規約追加の判断基準」 の延長: list の scope を明示しないのは「規約があるが読まれない」 の典型 pathology
- [`conventions/debugging-discipline.md §4`](../conventions/debugging-discipline.md#sibling-audit-on-violation) (sibling audit) の前提: scope が明示されていない list は sibling 漏れの源、 sweep が補完
- §10 File-role architecture: 監視 list (= soft、 cold reference) と禁止 (= hook、 always-on enforcement) は categorical に異なる surface に置かれる

---

## <a id="cross-repo-migration-ordering"></a>13. Cross-repo refactor の migration ordering — データ側を先に commit

### <a id="migration-order-footgun"></a>13.1 観察された footgun

複数 repo (= 同一 owner の cross-repo、 cross-layer、 collaborator-shared 含む) を跨いで refactor する場合、 commit / push の順序によって時間窓 (= time window) で意図しない state が出現する。

具体例: claude-config の `setup.sh` が個人層 (= layer 3、 別 repo) の `secrets-repos.txt` を read するように refactor する場合:

- **逆順 (= claude-config 先 → 個人層 後)**: claude-config push 時点で新 setup.sh は `<personal-layer>/secrets-repos.txt` を read しようとする → file 不在 → graceful skip でないと regression。 個人層 push 後に file が出現 → 次 setup.sh 起動から正常動作
- **正順 (= 個人層 先 → claude-config 後)**: 個人層 push 時点で file 存在、 claude-config 旧 setup.sh は file を read しないので影響無し。 claude-config push 後 setup.sh が新 logic で file を read → 正常動作

両順序とも graceful skip 設計なら functional regression は無いが、 正順は「想定外動作期間」 を最小化する。

### <a id="data-first-commit-principle"></a>13.2 原則: データ側を先に commit、 コード側を後に commit

cross-repo refactor で 「repo A のコードが repo B のデータを read する」 形になる場合、 **B を先 / A を後** で push する:

| 役割 | 例 | 先後 |
|---|---|---|
| **データ側 (= 受動側)** | 個人層 / config registry / lookup table / 共通 fixture | **先** push |
| **コード側 (= 能動側)** | bootstrap script / runtime reader / consumer | **後** push |

### <a id="graceful-skip-design"></a>13.3 graceful skip 設計の併用

正順だけで footgun は減るが、 完全に防ぐには **コード側を graceful skip 設計** にする (= データが無くても crash せず空 array / no-op で続行)。 これにより:

- 逆順でも functional regression なし
- 一時的にデータが消えた / 移動した場合も resilient
- foreign user (= データを持たない user) で動作

graceful skip + 正順 push の組み合わせで、 (a) 想定外動作期間最小化、 (b) edge case の resilience 両方を確保。 graceful skip 単独では「想定外動作期間に skip が走って setup が無音失敗」 という silent regression 経路が残るため、 慣例としての正順 push は依然必要。

### <a id="collaborator-shared-ordering"></a>13.4 collaborator-shared 場合

repo A と repo B が別 maintainer の場合、 atomic な順序確保はできない (= 両 maintainer の協調が要る)。 戦略:

1. **データ側 maintainer に先行 push を依頼**、 完了確認後にコード側 maintainer が push
2. **graceful skip を必須化**: atomic でない時間窓は graceful skip で吸収、 monitoring (= run-time error log / alert) で異常検出
3. **window 最小化**: 両 push の間隔をできるだけ詰める (= 同 day / 同 hour)

multi-maintainer の場合、 順序保証よりも graceful skip の方が defensive。 順序は best effort、 設計は worst case 想定。

### <a id="migration-order-origin"></a>13.5 由来

2026-05-10 claude-config self-audit で `setup.sh:863` の `SECRETS_REPOS` runtime hardcode (= 所属機関名を含む repo 名を含み CLAUDE.md L105 違反) を個人層 `secrets-repos.txt` 外出しに refactor した際、 `odakin-prefs` commit `b62bb7d` (= データ側) を先行 commit、 `claude-config` commit `13eba10` (= コード側) を後 commit で進めた事例。 graceful skip も併用 (= LAYER 空 / file 不在で `SECRETS_REPOS=()`) しているため、 仮に逆順でも functional regression は発生しないが、 慣例として正順を採用することで「想定外動作期間 = 0」 を達成。

### <a id="migration-order-applicability"></a>13.6 適用範囲

- 同一 owner の cross-repo refactor (= 4 層 cross-layer 含む)
- collaborator-shared repo 間の refactor (= layer 2 内の repo 間 + layer 1↔2 等)
- monorepo 内でも build artifact / generated file を生む build 段の順序

データを read する code が新規導入される場合の汎用 pattern。 read される data が既に存在する code を変更するだけなら本原則は適用外。

### <a id="migration-order-related-rules"></a>13.7 周辺規律

- §2 「ルールの重複を避ける」 の延長: data 側を canonical とし code 側は読み取り経路 (= ポインタ) として 1 ファイル定義
- [`conventions/shared-repo.md §「公開前の Audit」`](../conventions/shared-repo.md): collaborator-shared repo の commit 規律
- 関連 anti-pattern: 1 commit に複数 repo の変更を atomic に詰めようとする (= sub-tree merge / 提出物分散) は coordination overhead と review 困難を招く、 順序 + graceful skip の方が単純

---

## <a id="intrafile-slug-identity"></a>14. 大規模 reference / gotcha convention の intra-file 構造 — slug identity + 検証可能 index

§10 (File-role architecture) は **file 間**の auto-load tier 配置を扱う。 本節はその裏の concern = **単一 convention が大きくなった時の file 内部構造**。 落とし穴集・reference 集のように「1 file に多数の独立 entry が貯まる」 convention が肥大すると、 §10 の tier 移動とは別の保守 pathology が現れる。

### <a id="intrafile-trigger-signals"></a>14.1 trigger signal (= 3 つのいずれか)

- **(a) サブセクション過多**: `###` が数十に達し、 flat namespace で navigation / 重複検出が困難
- **(b) letter-suffix 番号の増殖**: positional 番号 (`§2-4`) が満杯になり、 中間挿入のたびに接尾辞 (`§2-4b`) が増える = **番号が「位置」 に identity を縛っている**証拠
- **(c) 機械検証できない cross-ref 網**: 内部 §-ref が手 join で、 dangling / 重複が人手 sweep でしか見つからない

1 つでも該当したら identity を**位置非依存**にする。

### <a id="slug-over-positional"></a>14.2 cross-ref は positional 番号でなく安定 slug で

各 entry に kebab-case の安定 slug を与え、 cross-ref を slug で書く (= markdown なら `<a id="slug">` anchor + `[`slug`](#slug)` link)。 利得: 挿入・並べ替え・**ファイル移動**で ref が壊れない、 semantic (番号より意味が読める)、 **validator で dangling 検出可能**。 旧 positional 番号は捨てるが、 他 doc の dated/historical 参照が解決し続けるよう **index に `legacy` として保存**する (= 番号の identity でなく解決可能性だけ残す)。

⚠️ **可視 label も slug にする (= 見出しの title 文字列や topic nickname を label に再掲しない)**。 form は `[`file.md` slug](file.md#slug)` で、 link 先だけでなく**可視テキストも slug** にする。 理由 2 つ: (i) **drift** — 見出し title を label に書くと heading の reword で label が stale 化する (= slug 化が link 先で達成した「位置・文字列からの decoupling」 を label 層で**再導入**してしまう) + heading 文言の二重化 (= [§2 定義は 1 箇所](#no-duplicate-rules) / [§15](#sot-consolidation-recipe) の single-SoT を label で mini 違反、 heading が SoT・label は copy)。 (ii) **greppability** — `label == anchor` なら `grep <slug>` 1 本で anchor 定義と全 inbound ref が揃う (= 保守の要、 これが「slug を label に出す」 の実利。 JP nickname label は anchor 名に grep で辿れず ref を取りこぼす)。 ⚠️ slug が無く heading テキストで locate するしかない degraded fallback ([§14.7 (B) ②](#inbound-ref-robustness)) は別軸 (= label の好みでなく target locator の話)。 **slug があるなら label は slug** に倒す。 (origin: 2026-06-27 slug migration audit — §title 形 ref を slug 化した際、 一部が「逐語 title」 でなく「topic nickname」 だったが、 greppability + uniformity のため全て slug label に統一した。)

⚠️ slug-anchor が救うのは **内部 (= 同 file 内) の cross-ref** に限る。 doc 自体を repo-root → subdir へ **relocate** すると、 その doc が**他 file を指す** markdown 相対 link `[](path)` は黙って壊れる (= intra-repo link は `../` を 1 段 prepend する必要が出る、 cross-repo link は `../` → `../../` に深くなる)。 さらに厄介なのは、 **構造化 ref (= yaml の `cross_ref` 等) だけを検証する link-checker は markdown の `[](path)` link を対象に含まない**ため、 この breakage は**機械検出から漏れる** (= validator が green でも relative link は dangling しうる)。 → **doc を relocate したら、 その doc が抱える相対 link を手で fix し、 link 先の到達性を verify する** (= slug 化で「内部 ref は ref-safe」 になっても、 file 自身の移動による「外向き相対 link」 の breakage は別問題)。

⚠️ **機械 consumer (= detector の match pattern / registry の構造化 field / validator 設定) には living doc の positional § 番号 string を一切与えない**。 prose の §-ref は renumber 時に人間が grep replace で追従できるが、 機械 match される "8.12" 等の string は renumber 後に**黙って**誤 suppress / 誤 match に転じ (= drift 検出器なら false negative 化 = 最悪方向)、 pattern 自体の validity を検証する仕組みは普通ない。 filename / title / slug を使う (凍結文書 = dated plan の § は不変なので可)。 既に与えてしまったのを発見したら、 「restructure 時に同時更新が必須」 という**将来条件付き注記で残すのでなくその場で置換する** — その注記は recall 依存 (= §8.12 の最弱発火面) に landmine を置く行為で、 除去が安価な時点での即時除去が常に勝る。 (origin: 2026-06-13 — SoT registry の pointer_patterns に "8.12" を登録した同日、 起草者自身が「将来 restructure 時に要更新」 と注記で残す選択をし、 user 指摘「これはまずいんじゃないの」 で即時除去に転換。 除去後の検証で当該 pattern は冗長 〔= 全 mention が filename pointer で既に救済〕 とも判明 = positional pattern は不要なのに risk だけ足していた)

### <a id="thin-index-db-benefits"></a>14.3 薄い index で「DB の利点」 を prose を動かさず得る

「entry が多い → DB 化したい」 直感の**正しい翻訳**は、 prose を yaml に移すことではない (= markdown-in-yaml は編集性を殺す + LLM consumer は grep で十分読める)。 **本文 prose は markdown のまま**、 別ファイルの薄い index (= `id` / `legacy` / `title` / `related` のメタだけ) で「join 検証 + 重複 surface」 という DB の利点だけを取る。 validator が (1) 全 ref が解決 (dangling 0)、 (2) 見出し ↔ index が全単射 (orphan 0)、 (3) 重複候補を keyword overlap で surface、 を機械化する。 ⚠️ prose を yaml に移すのは anti-pattern (= §2 の「定義は 1 箇所」 を index 側に誤適用しない、 prose が定義本体)。

### <a id="split-axis-access-pattern"></a>14.4 split-axis は access pattern に合わせる + slug を先に振る

肥大 convention を将来 file 分割するなら、 **何の軸で割るかは「何で引かれるか」 で決める**:

- recency 軸 (hot/cold): 古い entry が滅多に参照されない場合 (= 個人層の作業規律 doc を hot file + grep 専用 archive に割った例)
- **topic / concern 軸**: entry が「踏んだ症状の種類」 で引かれる場合 (= 本 repo の office-automation.md は xlsx / docx / pdf / form-discipline で割るのが適)

🔑 **enabling insight = slug を先に振れば分割は ref-safe**: slug は identity を「位置」 からも「ファイル」 からも切り離す。 → **slug 化を先にやれば、 後続の topic 分割は ref を一切壊さない無痛操作**になる (= entry をどの file に動かしても slug ref は有効)。 だから順序は必ず **slug → 分割**。 分割自体は navigation pain が実証されてからで良い (= reading は grep で困らない、 §9.8 過剰対策の回避)。

### <a id="mechanical-script-extraction"></a>14.5 mechanical な部分は script 化 (§10.9 と整合)

reference convention 内の「反復実行・検証用の手順」 は illustrative な code 片のまま貯めず script に抽出し、 prose は薄い why/when + script pointer に寄せる (= §10.9 code-as-canonical の reference-convention 版)。 validator 自体もこの一例 (= 整合性検証を prose の「手で sweep せよ」 規律から決定論 script に移す)。

### <a id="intrafile-origin-example"></a>14.6 由来 + worked example

2 つの観察から一般化 (= §9.8 「単一観察から飛ばない」 を満たす、 観察は 2 件):
- 個人層の作業規律 doc の **recency 軸 hot/cold 分割** (archive-first restructure)
- 本 repo `conventions/office-automation.md` の **slug 化 + index + validator** (= positional §-番号が letter-suffix 6 個まで増殖 + 内部 ref が無検証だった 1300+ 行 file を、 識別子だけ位置非依存化。 topic 分割は ref-safe になった状態で defer)。 worked artifact: `conventions/office-automation.index.yaml` + `scripts/check-office-automation-index.py`。

決定的動機: 検証系 entry を追記した際、 それが既存 entry の mandate を掘り崩す regression を、 **機械検証が無いため手の多軸 sweep で初めて発見**した (= dangling / contradiction 検出が人手依存)。 数十 entry 規模でこれは破綻するため、 整合性検証を script 化する。

### <a id="inbound-ref-robustness"></a>14.7 cross-repo inbound-ref robustness — 下流からの参照を restructure で黙って壊さない

§14.2-14.6 は単一 convention の **内部**構造だった。 本節はその外向き双対。 **この共通規約 doc 群 (= layer 1) は最も多く参照され、 かつ public ゆえ自分の dependents (= private を含む下流 repo) を列挙できない** (= 依存が一方向にしか見えない非対称)。 ∴ restructure (= renumber / relocate / split) の inbound breakage を upstream 単独では検出も予防もできない。 robustness を 3 つに分散する:

**(B) 参照する側の規律 (= inbound ref の書き方)**: 別 repo から layer-1 doc を指すときの優先順位 — ① **slug-anchor `file.md#slug`** (= renumber/reorder/intra-file 移動に耐える) / ② filename + 見出しテキスト or topic 名 / ③ **bare positional `§N.M` を単独 locator にしない** (= renumber で silent mis-resolve する、 §14.2)。 これは §14.2 (= intra-file「slug で ref」) の **cross-repo 版**。 ⚠️ ただし **anchor は preferred であって hard 必須ではない**: positional §-ref も §14.10 の legacy 転送が永続する限り**解決可能 (= forwardable)** なので許容される — 特に **section RANGE** (= 「§14.7-14.10」 等、 anchor では表しにくい) や **dated plan の史料記述**。 hard invariant は「anchor を使え」 でなく §14.10 の **legacy append-only** (= positional ref を survivable にしている実体はこちら)。 ∴ enforcement は anchor 強制 (= recall 依存の §8.12 最弱面 + 個別 ref を叩く §8.11 whack-a-mole) でなく **forwarding の永続化** (= §14.10 gate) に置く。 この明確化は §9.9 の self-violation probe 由来: 起草 session が §14.7 を書いた直後の下層 plan pointer で positional §-range を使い、 Locus B が RANGE と「forwardable だから tolerated」 を未規定だったと露呈した (= 自己違反が定義の under-specification を probe した)。

**(D) restructure する側の protocol**: layer-1 doc を restructure するときは —
1. **slug-first** (§14.4): 識別子を slug 化してから renumber/split する (= slug 参照は無傷で残る)。
2. **additive を default に**: slug を**足す**だけで §-番号は据え置く方が、 既存の positional inbound ref が壊れない (= 番号を動かさず slug を併設、 legacy mapping は §14.2)。 番号を実際に動かすなら、 下流 ref の migrate と**同 commit** で行う (§13 data-first)。
3. **relocate したら旧 path を redirect** (= thin pointer file) するか、 同 commit で下流 fix (§15 step3 の「外部が指す path を dangle させない」)。
4. **cross-repo sweep を同梱** (= §2.2「衝突宣言 sweep」 の cross-repo 版): restructure commit の前後で `scripts/check-inbound-refs.py` を回し、 HARD dangling (= 消えた file / anchor) を baseline に保つ。

**(C) 検出器とその限界 (= 正直に明示)**: `scripts/check-inbound-refs.py` は **anchor 存在 / path 存在**という mechanically-checkable な HARD dangling のみ検出する。 **positional `§N.M` が renumber 後も同じ意味を指すか (= silent mis-resolve) は検出できない** (= §8.8 の semantic blind spot)。 ∴ §-ref を anchor に migrate するのが唯一の真の fix で、 検出器はその補完にすぎない (= fragile 件数を INFO で出すだけ、 「全部見た」 と読ませない §8.8 (3))。

由来: 2026-06-16、 inbound ref を実測 (= ~1000 行が layer-1 doc を名指し、 robust な anchor 形は ~20、 fragile な positional は ~440) し、 「restructure すると下流が黙って壊れる」 構造を確認。 帰結として **slug 化の優先順位は内部 sub-section 数でなく inbound ref 数で決める** (= 最も参照される doc から slug-first)。 incident/設計史は個人層 plan に残置 (= kernel-up / instance-down)。

### <a id="db-metadata-not-content"></a>14.8 「DB 化」 は metadata-DB であって content-DB ではない — prose は markdown に残す

§14.3 の「prose を yaml に移す anti-pattern」 に対して**なぜか**の理由を補う。 規模の大きい reference convention が育つと「DB に migrate して、 元の md はその DB への pointer stub に降格」 という直観が生まれる。 だが **prose convention にこれを適用するとその消費モデルが壊れる**。

**分割線: records → DB、 prose → markdown**。 records (= paper / date / presenter 等の fixed field を持つ構造化データ) は DB バックエンド + 自動生成で正しく機能する (= 自動公開される派生 yaml がその例)。 prose (= エッセイ的な convention 本文 / design principle) は markdown に残す。

**content を DB に出してはいけない 3 つの理由**:

1. **(DECISIVE) LLM consumer が grep/Read で context token として convention を読む**という前提が壊れる。 DB バックエンドの pointer-stub は query layer なしに context に読み込めない。 これは convention が機能するための前提条件そのものを破壊する (= greppable markdown が precondition)。
2. **人間も rendered markdown を読む** (GitHub / editor)。 stub だけでは render されず読めない。
3. **編集可能性と ownership の問題**: prose を yaml/DB に入れると authoring と diff が苦痛になる (markdown-in-yaml の escape)。 自動生成 artifact は「ownership」 を失う (= 生成後に手直しできない、 overlay 生成の教訓)。

**決定打**: §14 が実際に解いている問題 (= positional reference の脆さ) に対して、 content-DB は slug に対して何も優位性を持たない。 slug は position 非依存の key を markdown に留まったまま実現する。 content-DB はさらに可読性・編集性のコストを積み上げるだけ。

**「将来 queryable/browsable/app 化したい」 という目標も content-DB を正当化しない**。 正しいアーキテクチャは 「markdown を source とし、 view (= search index / docs site) を生成する」 だ。 markdown が source に留まる。 content が DB に移動するのは「人間も LLM も読まず、 プログラムだけが触る」 段階になって初めて正当化される。 convention はその逆 (= 人間と LLM が主読者) なので、 その段階は来ない。

∴ §14.3 の薄い index は **metadata-DB であって content-DB ではない** (= id / legacy / title / related だけ)。 format 選択の決定軸は **consuming agent (LLM) と人間の read+write の容易さを最優先する** こと — grep で読み、 Edit で書く = markdown + 薄い index が最軽量。

### <a id="index-autogenerate"></a>14.9 薄い index は markdown から自動生成する (= 手で 2 ファイル同期しない)

§14.3 の薄い index を手動で維持すると、 新しい section を書くたびに「md と index の両方を更新する」 という書き手税が発生する。 sync 忘れ = drift。 これは §14.8 の「read+write の容易さ最優先」 に反する。 ∴ **index を md から派生として自動生成する**。

**生成する (= md が SoT)**: id (= heading の `<a id>` slug)、 level (= `##` / `###`)、 title (= heading テキスト verbatim)。

**保存・freeze する (= 手の判断、 生成が破壊してはいけない)**: legacy (= 永久転送先、 §14.10)、 related (= 関係グラフ)、 その他の手フィールド。 新しい section は登録時点の §-番号を legacy として freeze する。

著者は **markdown (= prose + `<a id>` anchor) だけを書く**。 generator が index を同期する。 ツール: `scripts/generate-doc-index.py` (= `--check` で md ↔ index drift を gate 可能)。

⚠️ generator は **anchor を持たない heading を surface する** (= bijection validator が構造上検出できない「anchor なし heading」 の盲点を補完する)。

⚠️ 既存の index が **別の title 規約** (= 手で整理した title vs verbatim heading) で書かれている doc は round-trip しない — generator をあてず手動維持にとどめる (= §8.9 legitimate-deviation 規律、 全 doc を generator に強制しない)。

### <a id="legacy-append-only"></a>14.10 legacy は永久転送先 — append-only を機械 enforce する

§14.2 の legacy (= 旧 §-番号 → slug の転送表) は **絶対に縮小してはならない**。 理由: 一度公開された §-番号は、 こちらが把握できない下流 repo / 他ユーザー / 古いノートが永久に参照し続ける可能性がある。 各 legacy entry は**永久転送先** (= mail forwarding order は期限なしで保持する) であり、 slug rename / section 削除 / index 再生成によって黙って消えることは許されない。

これは特に **他ユーザー保護**の文脈で重要: layer 1 は public であり、 自分の dependents を列挙できない (§14.7)。 他ユーザーはローカルの tooling も discipline も持たない。 **彼らに届く唯一の可搬な保護は repo に同梱されているもの = index の legacy map** (著者が自分の ref を migrate するのは private な利便であって、 他ユーザーには届かない)。 legacy map の完全性こそが public 向けの保護である。

§9.1 triage: 黙って消えた legacy は**回復不能** (= 下流 ref が永久に壊れる) = catastrophic tier。 ∴ warning でなく機械的 BLOCK で enforce する。

gate: index の legacy 集合が HEAD (= 直前 commit) に対して **append-only** であること。 縮小するような commit を block する。 git history を SoT とし、 別途 ledger を持たない。 ツール: `scripts/check-legacy-append-only.py` (pre-commit)。

意図的な削除は許容するが **明示的な行為**でなければならない: `LEGACY_RETIRE_OK=1` で retire できる (= section を消すことはできる、 ただし黙ってでなく意識的な行為として)。 転送 entry は意識的で承認された行為によってのみ削除できる。 これは §8.2 (high-stakes → rule でなく mechanism) + §8.10 (invariant を edit-time gate で守る) の転送専用実例。

由来: 実測値・commit・office-automation の verbatim-title divergence・並行 session 干渉の詳細は個人層 plan `plans/2026-06-16-claude-config-dbification-eval.md §10-11` に残置 (kernel-up / instance-down)。

---

## <a id="sot-consolidation-recipe"></a>15. SoT consolidation recipe — README-as-SoT / 多重記述の是正手順

§2 の「定義は 1 箇所＋pointer」、 §14.3 の薄い index、 単一-SoT 原則は**断片**として既に存在する。 だが「同じ authoritative fact が複数 file に多重記述されてしまった状態を実際に直す」 という作業は ordered procedure を要し、 順序を誤ると外部 ref を壊す / 内容を silently 変えてしまう。 本節はその是正手順を 7 step に固定する:

1. **authoritative fact を provenance 付きで inventory する**: 何が正本足りうる fact かを列挙し、 重複箇所を `file:line` で洗い出す (= どこに何が散在しているかを先に確定。 grep で機械的に拾う)。
2. **home は 1 つ＝grep 可能な working-SoT file に決める**: machine-consumer (= script が parse する必要) が無ければ単一の `.md` で十分、 **yaml にしない** (= prose を yaml 化すると編集性を殺す、 §14.3 の anti-pattern と同根)。 各 entry に出典と「源泉が改訂されたら再転記せよ」 の注記を添える。
3. **README は thin index に降格する**: 定義本体を README から抜き、 home への pointer だけ残す。 ⚠️ これは「README は SoT たりえない」 を含意しない: **公開リポ (= README-only 読者あり) では build/quickstart/deploy の home は README 側**なので、 降格・抜き出しの対象は README でなく CLAUDE.md 側になる (= どちらが home かは [`CONVENTIONS.md` §README の流儀](../CONVENTIONS.md#readme-style) の判別軸で決まる、 「README=非SoT」 は非公開リポ default にすぎない)。 ただし **外部 (= 編集権限のない別 repo) が指している anchor / heading は保存し、 path を rename しない** (= path-targeting な外部 ref を dangle させない。 §14.2 の legacy 保存原則の cross-file 版)。
4. **全 secondary restatement を home への pointer に置換する**: 残った重複記述を全て「正本は X、 詳細は X 参照」 の pointer 文に変える。 cross-ref される表には**安定 anchor** を付け、 pointer はその anchor を指す (= positional 参照を避ける、 §14.2)。
5. **home を SoT drift-detector に登録する** (= そういう機構を保守しているなら): このとき登録 key は **裸の値 (= 金額・日付等) でなく distinctive な規則 phrase を anchor にする** (= 値は他文脈で偶然 collide する、 規則を説明する独自 token なら誤検出が少ない)。 同時に**検出対象外の blind-spot を明示**する (= list-based audit は登録 topic しか見ない、 未登録の重複は 4 軸 sweep が cover する相補関係を doc 化、 §8.8)。
6. **migration は逐語 relocation のみに留める**: 移設の最中に内容を「ついでに改善」 しない。 grep で home 前後の text が zero-loss であることを verify する (= これは移設であって内容変更ではない、 両者を 1 commit に混ぜると review で改変が埋もれる)。
7. **4 軸 sweep (= goal は error 発見) ＋同 session 内で commit/push する**: 是正は複数 file を跨ぐので、 別 session の救済に依存せず同 session 内で push 完了まで持っていく (= cross-repo drift を残さない)。

由来: ある運用ルールを複数 file に独立 author してしまい、 効率性軸の sweep が多重化を見逃した RCA を一般化 (= cell 埋め trap が SoT domain で発現した形態)。 本節は §2 / §14.3 の断片を「直す手順」 として束ねたもので、 新規原理ではなく ordered procedure の明文化。

---

## <a id="derive-not-summarize"></a>16. 要約は load-bearing な「関係」を不可視に落とす — derive-not-summarize の徹底

### <a id="summarize-pathology"></a>16.1 観察された pathology

ある事実の意味が、単一の節でなく**複数の節の関係**に宿ることがある。典型は**交渉された立場**: {① 既存の want / ② それと衝突する制約 / ③ 部分的な譲歩 / ④ yes-no の問い} (例: 「減らしたいが、この件では減らせない、ただし増えもしない、それで可か」)。意味は 4 部の**関係**であって、どの 1 節でもない。

この種の事実を**要約**すると、関係・動機の接着剤が落ちる。しかも損失は**不可視**: 各圧縮は「真の事実」を残し、接着剤 (= 「なぜ ① を欲したか」「④ の交渉性」) を「背景」として削るので、残った断片は単体で正しく**壊れて見えない**。これは inline §3 (= 不確実性を expose か hide か) の**要約ドメインの双子**である — 安価な操作 (要約) が load-bearing な損失を隠す、残ったものが真だから。

2 つのバイアスが重なる:

- **(i) 離散事実は残り、関係/動機が落ちる** — 関係は「文脈」に見え、記録時に最初に削られる。
- **(ii) 二面ある事実は palatable な半分が残り、不都合な条件付き半分が落ちる** — 「増えない」(安心) は残り「減らせない」(痛い) は落ちる、で記録は rosy・capability 寄りに drift する。

**再演の signature**: 同じ nuance が **2 回以上「訂正」される** (= re-drop)。「前に間違えた」 という散文注記は次の脱落を**防げない** (= §8 系の「散文規則は行動を縛らない → 設計で消すか機械化する」)。

### <a id="why-single-sot-insufficient"></a>16.2 なぜ単一-SoT 原則 (§2/§15) では足りないか

§2/§15 は「同じ事実を**複数 file に**重複させるな (= dedup)」。本節は直交する: **単一 file の単一記録**でも、source からの**要約**である限り fidelity を失う。問題は重複でなく **lossy transcription** であり、別 axis。

### <a id="summarize-remediation"></a>16.3 修正 (構造的に強い順)

1. **Derive, not summarize** — 「何を諮った/合意した/頼まれたか」型の事実は、**正本 = source artifact の逐語** (= 送信メールの原文) とし、要約は明示的に二次 + source への pointer。SoT 成熟度の「T1 generated/derived」を**散文台帳に適用**したもの。実務的帰結: 原本を**転送/引用**する方が語り直すより faithful (= reply domain では literal forward が最強)。
2. **substance-first** — 記録の最も目立つ行は load-bearing な crux であって workflow status (「回答する」) ではない。matter には**検索 key と一致する home**を与える (= §14.2 の slug 同様、retrieval key を identity に)。
3. **slot template** — 構造を持つ事実 (交渉 = want/constraint/concession/ask) は枠で書く。落ちた slot が**空欄として可視化**され、黙って消えない。
4. **active completeness check** (= §15-5 の anchor token 機構の逆向き) — 実証済み再犯 nuance の**必須共起 token**を registry 登録し、topic を名指すのに token を欠く要約を flag。⚠️ 限界は §8.8 と同じ (登録 topic しか見ない) + 偶発 mention への false positive → **scope を「要約 field」に絞る**。補助輪であって芯ではない。
5. **frame-first** — 要約前に matter の型 (capability / 交渉 / 通知 / 決定) を分類。型が load-bearing を決める (= 交渉なら trade-off が load-bearing で「背景」ではない)。型の取り違え (= 交渉を capability と読む) が crux を「背景」に降格する根。

### <a id="summarize-honest-scope"></a>16.4 honest scope

完全機械化は意味解析で hard。信頼できる芯は **1 (derive/verbatim)**。本節は §8.11 (= downstream net は intake で正しく encode された対象しか守れない) の specific form でもある: ここでの intake mis-encoding は「source を要約で写した」こと、leverage は「写さず原本を保つ」という設計判断。4 (check) は §8.11 が言う通り downstream の補助に過ぎない。

由来: ある交渉案件の肝 (= 既存の削減要望には応えられないが少なくとも増えはしない、で可か) が、source・中間台帳・会話のいずれの要約段でも繰り返し「増えない/提供可否」へ圧縮され、同じ nuance が 2 回 re-drop した RCA を一般化 (instance は個人層に残置 = §8.11 の kernel-up / instance-down)。user が選んだ修正 (= 原本を転送して語り直さない) が、本節の芯 1 の reply-domain 実例。

---

## <a id="hierarchical-name-collision"></a>17. 階層内の同名 entity 併存 — SoT 表現で context path を明示

異なる組織階層 / data 階層 / 概念階層 で同じ word が**別 entity を指す**場合、 SoT 表現で context path を explicit に declare しないと reference 側で混同が起きる。 §2 (= 重複避け) や §15 (= 多重記述是正) とは直交: 重複でなく **collision** (= 同じ name token が独立の referent を持つ legitimate な並存) の問題。

### <a id="hierarchical-name-collision-pattern"></a>17.1 観察 pattern

| 階層 1 | 階層 2 | 同名 word | 別 referent の指示先 |
|---|---|---|---|
| 大学 学部 | 大学 大学院 | 「専攻」 | 学部内専攻 (= 学科内 specialization) / 大学院専攻 (= 研究科内 program) |
| user config | system config | 「config」 | per-user override / global default |
| project-local | repo-shared | 「conventions」 | local override / shared baseline |
| Python builtin | user-defined | `id`, `type`, `list` | builtin / shadowed name |

### <a id="hierarchical-name-collision-trap"></a>17.2 Trap pattern (= 同型再発の signature)

1. **暗黙の 1 階層仮定**: 同名 word が **1 階層でしか存在しない** と暗黙仮定 (= 受け取った reference を 1 階層 frame で解釈)
2. **誤反射の伝播**: 1 階層の SoT を更新 → 同名 entity を反射的に「同じ fact の synonym」 と扱い関連 file の literal を一括書換え → **別階層の正名まで誤って rewrite**
3. **二度ハマる**: user 訂正 (= 「実は別階層 entity」) を受けても「では別階層こそが正」 と 1 階層 frame で再仮定し逆方向 over-correct
4. **literal の散在**: 過去 SoT に同名 literal が散在し、 どこを直すかの judgment が立たない

これは §2 (= 重複避け) でも §15 (= 多重記述 consolidation) でも catch されない: 各 reference は legitimate に別 entity を指す literal で、 重複でない (= 重複検出器の射程外)。

### <a id="hierarchical-name-collision-discipline"></a>17.3 規律: SoT 表現で path を明示

**(a) 単一名でなく path で declared** — 各 entity を hierarchical path で書く:

```yaml
# Bad (= 1 階層 frame で collision risk)
所属 (学部): <intra-dept-program-X>
所属 (大学院): <intra-dept-program-X>  # 同 word で別 entity の混同 risk

# Good (= path で disambiguation)
所属 (学部): <faculty> > <department> > <intra-dept-program-X>
所属 (大学院): <graduate-school> > <research-school> > <grad-program-Y>
```

= 同じ word でも階層 path で disambiguation。 path 表現自体が collision を visible にする (= structure が discipline を運ぶ)。

**(b) 階層併存を SoT 自身に明示** (= warning 句として):

```markdown
⚠️ 「学部内 X」 と「大学院 Y」 は別組織階層、 同じ「専攻」 word だが referent が異なる。
```

= 読者 / future-self に「ここは collision domain」 を明示。 reflex で同名 literal を 1 階層 frame で扱う risk を抑える。

**(c) 過去誤りを history として保存** — [§2.4 errata marker](#errata-on-preserved-records) の collision domain 版:

削除すると future-self が同 trap を再演する。 errata 形式で「過去のここで誤った frame で update した」 を保存:

```markdown
⚠️ 過去の誤り: 同 word を 1 階層 frame で扱い、 別階層の名前を一度誤って一括書換えした。
正は <level-1 entity> と <level-2 entity> の 2 階層併存。
```

**(d) References は context-tagged pointer 化**:

```markdown
<reference>: <value> (= <level/context-tag>、 正本 = <home> の <relevant section>)
```

= 「正本」 と「level/context」 をセットで明示。 reference を読むだけで collision の存在 + 該当階層が分かる。

### <a id="hierarchical-name-collision-relation"></a>17.4 関連

- 一般 SoT 重複避け = [§2 (= #no-duplicate-rules)](#no-duplicate-rules) (= 別軸: 同 entity の複数記述)
- intra-file slug stability = [§14 (= #intrafile-slug-identity)](#intrafile-slug-identity) (= 別軸: doc 内 anchor identity)
- 削除不能な誤り記録の errata = [§2.4 (= #errata-on-preserved-records)](#errata-on-preserved-records) (= history 保存の type、 本節 (c) の base)
- Frame error の一般則 = [§4 (= #orient-before-act)](#orient-before-act) (= 行動前に方位を取れ、 本節 trap (1) の prevention 上流)

由来: 2026-06-29 — 大学組織で「学部内 X 専攻」 と「大学院 Y 専攻」 が同 word「専攻」 で並存する fact を 3 回の user 訂正連鎖を経て理解した RCA を一般化。 1 階層 frame で解釈する暗黙仮定 → 1 階層更新 → 別階層誤訂正 → 二度ハマる cycle が観察され、 collision domain の SoT 表現に path / context tagging を要求する規律として hoist。 instance は layer-3 (= 個別 user profile の SoT) に sequester (= kernel-up / instance-down)。

---

## <a id="derived-view-as-recovery"></a>18. 生成 view は正本の意図せぬ時点 backup — 件数 parity で切り詰めを検出する

### <a id="derived-view-as-recovery-observation"></a>18.1 観察 (2026-08)

yaml 正本 (講演 career DB) が「軽微な date 修正」を名乗る commit で実際には **357 行切り詰められ** (直近 2.5 年分の entry 全滅、しかも名乗った修正自体も結果に不在)、**7 日間未検出**だった。発見の糸口は、正本から機械生成された markdown export に旧データが残存していたこと (= export は事故前に生成され、以後再生成されていなかった)。復元は親 commit の checkout で完了 (bad commit 側の挿入行は旧部分の再整形のみと diff で確認してから丸ごと復元)。

### <a id="derived-view-as-recovery-principles"></a>18.2 一般則

1. **生成 view / export は、次の再生成までの間、正本の意図せぬ時点 backup として機能する**。正本の異常を疑ったらまず view と突合する。裏返すと「view を正本へ即追従させる」自動化は、この受動的 backup を消す trade-off を持つ (= 検出猶予との交換)。
2. **「view にあるのに正本に無い」の向きを決めつけない**。view の先行 (未遡及反映) とも、正本の切り詰めとも整合する — どちらかは git 履歴が裁定する ([§4 (= #orient-before-act)](#orient-before-act))。
3. **commit message は意図を語り、diff は実態を語る**。大量削除を伴う「軽微 fix」commit は書き戻し事故の signature — レビューは message でなく diffstat を見る。
4. 安価な機械検出 = 正本の粗い bucket 件数 (年別 entry 数等) を (a) 直前 commit と (b) 生成 view とで突合する **parity 検査**。意味的突合という高価な問題に踏み込まずに切り詰めだけを捕まえる。

関連: [§2.4 (= #errata-on-preserved-records)](#errata-on-preserved-records) (= 削除できない誤り記録の扱い)、[§16 (= #derive-not-summarize)](#derive-not-summarize) (= view 生成の設計)。検出器 instance (実装・retroactive replay) は個人層に sequester (= kernel-up / instance-down)。

---

## <a id="rollcall-line-marker"></a>19. 点呼行 (rollcall line) — 散文で書かれた sub-obligation は数え直しで消える

### <a id="rollcall-line-observation"></a>19.1 観察 pattern

task 記録 (TODO notes 等) の**散文の中に埋まった sub-obligation** (= 「宿泊証明書も要る」「7/27 に印刷した」 型の 1 fact) は、 後の session が残 leg を**数え直す**ときに構造的に脱落する: 散文は要約されながら運ばれ、 要約は「主目的に対する残り」 だけを保存して付帯的な fact (取得窓・版・日付) を落とす。 落ちた fact が「窓が閉じる」 型 (取得は滞在中のみ / 紙は印刷時点の版で凍結) だと、 脱落 = 回収不能の実害になる。 実事例 2 系: 宿泊証明書 (残 leg の数え直しで「出張後」 バケツに畳まれ消えた → 窓 5 日前に人力 catch) / 印刷版 (印刷日が散文にしか無く staleness 判定不能のまま旧紙提出 → 差し戻し)。

### <a id="rollcall-line-pattern"></a>19.2 pattern: 機械可読 1 行 marker + 不在も咎める検出器

1. **固定 grammar の 1 行 marker** を task 記録に置く: `<名詞>: <値>` 形式で、 値は少数の enum + 括弧内自由文 (例: `宿泊証明書: 要(未取得) / 要(取得済 YYYY-MM-DD) / 不要(理由) / 不明(要確認)`、 `印刷版: YYYY-MM-DD (対象) / なし(理由) / 不明(要確認)`)。 散文と違い、 要約・数え直しを**素通りして生き残る** (= 行単位で copy され、 regex で機械照合できる)。
2. **検出器は marker の不在自体を咎める** (= absence-flagging): 対象 class の open task に点呼行が無ければそれを flag する。 これが無いと「書いた task だけ守られる」 = 規律の浸透度が不可視。 `不明(要確認)` を enum に含め、 「分からない」 を silent 放置でなく可視の状態にする。
3. **規律と機械は相補**: 検出器は点呼行が書かれて初めて中身 (窓・鮮度) を判定できる。 marker を書く reflex は規律側 (= 「event が起きた同 turn で書く」、 [`multi-session-coordination.md #green-light-carrier`](../conventions/multi-session-coordination.md#green-light-carrier) と同じ same-turn conversion family)。
4. **導入時に一度 stock sweep**: 既存の open task に点呼行を追記してから運用開始する (= 導入直後の absence-flag 洪水を実 triage に変える。 このとき「実は分からない」 が `不明(要確認)` として正しく可視化される)。

### <a id="rollcall-line-when"></a>19.3 適用判断

点呼行に昇格させる基準 = **散文のまま落ちると回収不能 or 高価な fact** (= 取得窓が閉じる / 版が凍結する / 期限が失効する)。 何でも marker 化すると notes が台帳化して可読性を失う (= [§2 (= #no-duplicate-rules)](#no-duplicate-rules) の運用台帳 SoT 重複問題と相似) — 「痛い脱落が 1 回起きた fact 種」 から event-driven に導入する。

---

## <a id="changelog"></a>変更履歴

| 日付 | 変更 | 動機 |
|------|------|------|
| 2026-08-31 | §19 追加 (点呼行 = 散文 sub-obligation の脱落防止 marker pattern) | 宿泊証明書 (取得窓が滞在中に閉じる、 2026-08-08) と 印刷版 (紙の vintage、 2026-08-31 paper-staleness 3 例目) の 2 instance から meta-pattern を抽出。 固定 grammar 1 行 + absence-flagging 検出器 + stock sweep。 instance 実装は個人層 (kernel-up / instance-down) |
| 2026-08-29 | §18 追加 (生成 view = 意図せぬ時点 backup + 件数 parity 検出) | career DB yaml が「軽微修正」を名乗る commit で 357 行切り詰められ 7 日間未検出 → 生成 export の残存データが発見と復元の糸口になった事故から抽出。kernel を §18 に、検出器 instance は個人層に sequester |
| 2026-04-02 | 初版作成 | 武貞メール対応での8件の不手際を分析し、規約設計の原則を抽出 |
| 2026-04-03 | §3 の適用事例追加 | push 連鎖障害: 「規約はあるが手順が不明確」→ CONVENTIONS §3 に粒度・障害対応を追加、教訓の詳細は email-office DESIGN.md に記録 |
| 2026-04-06 | §6 追加: DESIGN.md と EXPLORING.md の分離 | LorentzArena 2+1 の DESIGN.md 肥大化 + スマホ UI 思考メモの記録先問題。3 カテゴリ（決定 / 探索 / メタ決定）の分析を経て、決定と探索を 2 ファイルに分離する convention を導入 |
| 2026-04-15 | §7 追加: 決定後の content lifecycle と DESIGN.md の肥大化対策 | LorentzArena 2+1 の DESIGN.md が 1186 行まで肥大化 (Authority 解体リファクタで 8 entry が supersede、各 entry に ※ 注釈で本文温存) した問題を整理する過程で抽出。5 分類 (ACTIVE / DEFER / SP / SX / LESSON)、完了リファクタ集約 pattern、LESSON 集約用「メタ原則」セクション pattern、サイズ閾値を導入 |
| 2026-04-15 | §7 v2 化 + §2 に snapshot 原理を establish | 初版 §7 を書いた直後の深化議論で (1) day 1 ルールと retroactive 救済の混在、(2) archive vs snapshot の解釈曖昧、(3) Description と Judgment の境界未定義、を検出。§2 preamble に snapshot 原理を明示し §6/§7 をその application として位置付け。§7 を 3 分類 (ACTIVE/DEFER/LESSON) + transient 超越処理に簡素化、Description/Judgment 境界と粒度ルールを追加、When-in-doubt default を整理 |
| 2026-04-17 | §5 改訂 + §8・§9 追加 | git pull 忘れの annoyance 失敗への反射応答で memory に feedback を書こうとした違反を契機に、規約システム全体の subtraction pass。§5 (メモリ) をマシン固有事実のみに narrow 化し memory-guard hook を `ask` → `deny` 化。§8 で rule vs mechanism 非対称性・precedent-as-training-data・friction asymmetry を言語化。§9 で triage (catastrophic/material/annoyance)・asymmetric reflection bias・subtraction trigger・preference-approximation gap・Claude 側 diminishing-returns detection を整理。適用事例は odakin-prefs 2026-04-17 の commit 群 (git log) |
| 2026-04-17 | §8.5-8.7 + §9.5-9.7 追加 (coverage sweep) | 同日 session で session log に記録されていたが claude-config 側に無かった洞察を補完: §8.5 不安応答としての memory write、§8.6 agent 学習の錯覚 (correction は session 越えて persist しない、system 改変のみ残る)、§9.5 規約構造と Claude 応答の closed loop、§9.6 subtraction 形態 (削除 > migrate > 規約追加) + migrate-as-defer 警告 |
| 2026-04-17 | §9.8 追加 + §10 新設 (final sweep) | 同日 session の未捕捉 insight 2 件を durable 化: §9.8 単一観察から構造対策に飛ばない (Haiku false positive の lesson を一般化、scope 確認先行)、§10 File-role architecture (auto-load tier 0-3 分類、narrative 抽出 pattern、incidents archive lifecycle)。odakin-prefs での実証値も収録 (569 → 555 lines auto-load、T3 に 600+ lines 隔離) |
| 2026-05-10 | §12 追加 (監視 list の scope marker) + §13 追加 (Cross-repo refactor の migration ordering) | claude-config self-audit (= memory-guard hook の `odakin-prefs/` literal 1 件発見 → 全 hooks + 全 scripts + setup.sh sweep で sibling 20+ 件発見) で得た 2 件の universal 知見を durable 化。 §12 は DESIGN.md drift 監視 list が executable surface の同 class violation を見逃した経験から (= 暗黙 scope の blind spot)。 §13 は setup.sh の SECRETS_REPOS 個人層外出し refactor で odakin-prefs 先 / claude-config 後で push した順序確立から。 詳細 commit chain: claude-config `60a58c0` 〜 `13eba10` + odakin-prefs `b62bb7d` |
| 2026-04-18 | §10.9-10.12 追加 (Level-2 migration insights、§10.7-10.8 の後) | 他 session が先に追加した §10.7 byte budget + §10.8 削除・委譲の trap の後に追記 (section 番号 collision を避けて renumber)。LorentzArena 2+1/CLAUDE.md の radical delegation (364 → 97 lines) から抽出: §10.9 code を canonical とする doc dedup (ただし §10.8 warning を先に適用 — description column が code に無ければ dedup は anti-value)、§10.10 CLAUDE.md chain の nested auto-load (Claude Code 特有、sub-project で chain が積み上がる)、§10.11 「超要約」pattern (slim CLAUDE.md に 5-8 項目×1行の 2 層化)、§10.12 migration level 階段 (Level 0-3)。LorentzArena chain 505 → 238 lines の実証値。**本追記中の §10.9 LorentzArena パラメータ削除は §10.8 の anti-value 判定と衝突、次 session で constants.ts JSDoc 確認 + 必要なら docs/architecture.md に restore の要あり** |
| 2026-04-18 | §7.7 に byte-density row + §7.8 に 2 回目適用 + §10.7 新設 | LorentzArena 2+1 の 2 回目 retroactive reorg (DESIGN.md 1627→1303 行) で、SESSION.md が 80 行 threshold 内 (94 行) なのに 23.8 KB と重く autocompact を早める事象を観測。line count は proxy に過ぎず token 消費は byte に従うという lesson を §10.7 auto-context byte budget として規約化 (50 KB / 100 KB / 200 bytes/line の観測指標 + 処置 + SESSION.md 23.8→6.6 KB 事例)。§7.7 diagnostic table に「行数 threshold 内だが byte 密度高い」row、§7.8 適用事例に 2 回目適用段落を追記 |
| 2026-04-18 | §1 に bundle rule (pragmatic relaxation) 追加 | claude-config DESIGN.md 自身への §7 初適用 (規則を定義したリポに規則を適用する self-consistency 回復) で、`~/Claude/CLAUDE.md` 解体時の bundle 判断 (「1 rule = 1 file 厳格適用は 1 行ファイルを生む、関連密接かつ合計 10 行未満は bundle 可」) を §1 の corollary として昇格。配置先は影響範囲の最大公約数に従う原則は保持したまま粒度の下限を緩和 |
| 2026-04-18 | §10.8 新設「削除・委譲判断の trap」+ §7.8 に 3 回目適用 | claude-config への §7 自己適用 session で抽出した 6 件の insight を §10.8 に集約: tier-direction asymmetry (横ずらし委譲は ROI ゼロ) / T0-T1 chain pre-check / grep-substitute value (auto-load 表は pre-computed grep cache) / 削除提案 self-correction 事例 (LorentzArena ゲームパラメータ表 anti-value 判定) / DESIGN.md 分割閾値 / self-application discipline (規則定義リポへの同時 apply pass)。§7.8 に 3 回目適用段落で cross-domain validation (物理/描画 + 規約/メタ) を記録 |
| 2026-05-06 | §11 新設「In-plan exploration trail」 | LorentzArena NPC 非対称 plan で (II)/(II'') の walkback を経て (II''') に着地。 §6 EXPLORING.md は cross-session 探索用、 本 §11 は same-session 内 plan の back-and-forth trail を §1.6 「探索過程」 として plan 本体に保存する pattern。 §11 「やらないこと」 (decision-form) と §1.6 探索過程 (process-form) は重複せず補完、 両者揃って初めて rejected alternative の「なぜ提案 / なぜ却下 / 将来再開条件」 が一貫した narrative として読める |
| 2026-06-05 | §14 新設「大規模 reference / gotcha convention の intra-file 構造」 | office-automation.md (1300+ 行 / 69 サブセクション / letter-suffix § 6 個 / 無検証の内部 ref 網) の slug 化 restructure から抽出。 §10 が file 間 tier を扱うのに対し §14 は単一肥大 convention の file 内部 = 別 concern。 trigger 3 signal (サブセクション過多 / letter-suffix 増殖 / 無検証 cross-ref) + slug identity (legacy は index に保存) + 薄い index で DB 利点 (prose は yaml 化しない) + split-axis を access pattern に合わせる (recency 軸 = 作業規律 doc / topic 軸 = office-automation) + slug-first で分割 ref-safe + mechanical は script 化。 2 観察からの一般化 (§9.8 充足) |
| 2026-06-06 | §8.9 新設「set 差分 detector の false positive」 + [data-pipeline-automation.md §1](../conventions/data-pipeline-automation.md#single-source-of-truth) Pattern | SoT 統一 session の reference-data drift 手当から抽出。 §8.9 = §8.8 (proxy 盲点 = false negative) の対で、 set 差分 drift 検出の正当な乖離 (別管理 / 環境差 / 意図的例外) を filter で峻別。 data-pipeline §1 に「SoT invariant は生成経路でなく経路非依存 commit gate で enforce」 Pattern (= 生成 script の guard が手動編集をすり抜けた RCA の一般化)。 2 観察 (repo 照合 detector + reference DB dedup) からの一般化 (§9.8 充足)。 + §8.8 表に「委譲した調査 (subagent) の結論も proxy」 行追記 (= agent の『drift なし』 を自分で grep verify したら 9 件発見した実例、 negative 結論は ground truth でない = §3 単一情報源飛躍の subagent 版) |
| 2026-06-09 | §8.10 新設「fail-loud not fail-empty + 編集時 validity gate」 | 運用台帳 yaml の status に `: ` 混入で parse 不能化 → consumer が fail-empty (空扱い) で状態 label を 32 件誤除去した RCA から抽出。 §8.8 (proxy false-negative) / §8.9 (set 差分 false-positive) に続く mechanism の第 3 失敗モード = 「壊れた入力を空に潰して下流で破壊的 action」。 対 = 編集時 gate (parse 検証) + consume 時 fail-loud (破壊的 path を pre-flight abort)。 [conventions/data-pipeline-automation.md §1](../conventions/data-pipeline-automation.md#single-source-of-truth) (生成側 gate) の consume 側双対。 観察 2 件 (yaml 破損 + §1 guard-bypass) からの一般化 (§9.8 充足)。 実装は個人層 (yaml 編集後検証 hook + label 同期 script の fail-loud pre-flight) |
| 2026-06-13 | §14.2 に「機械 consumer に positional § 番号を与えない」 追記 | SoT registry の pointer_patterns に "8.12" を登録 + 「restructure 時に同時更新」 注記で残した同日、 user 指摘で即時除去に転換した RCA。 機械 match string は renumber で silent false-negative 化 + 将来条件付き注記は recall 依存 landmine (= §8.12 適用)。 除去後検証で pattern 自体が冗長と判明 |
| 2026-06-13 | §8.12 新設「規律の発火面 hierarchy」 + conventions/personal-skills.md 新設 + [hook-authoring.md §10](../conventions/hook-authoring.md#hook-no-go-judgment) 新設 | 横断 lookup script が規律表の機械補強 column 記載済みなのに 2 回不発 → personal skill 化で初手発火を実証した session から抽出。 §8.12 = 発火面 (hook / skill / scheduled task / doc) を内容と独立の設計軸として確立、 「reflex の徹底」 という再発防止策は発火面選択 skip の signal。 hook-authoring §10 = trigger が意図を識別できない hook は chronic FP で fleet を毀損 → skill へ切替える判定。 personal-skills.md = auto-discover skill の機構 facts (symlink 可・session 開始時 discovery、 2.1.170 実測) + description の書き方 + 多 machine 配線 (explicit allowlist registry) + 検証作法 (trigger test → discovery test の汚染回避順序、 headless `claude -p` の stdin hang / CLAUDECODE / CLI 別 auth 制約)。 kernel-up / instance-down (= incident 詳細は個人層 archive 残置) |
| 2026-06-09 | §8.11 新設「downstream 安全網は intake で正しく表現された対象しか守れない」 + §8.10 の §9.8 根拠を softening | 4 軸 self-check で §8.10 が「2 独立観察」 を over-claim (= 直接観察 1 件 + sibling) と発覚 → 「1 強 + 1 sibling、 既存 §1 の対辺補完」 に訂正。 §8.11 は別件: 「期限つき義務の見落とし」 incident 連鎖 (3+ 事例) から、 §8.8 (網が proxy を見る) の上流版 = 「網が見る対象自体が intake で mis-encode され downstream をいくら足しても掴めない / leverage は intake の encoding で、 しばしば機械化不能の判断」 を一般化。 user 方針「上の層へ移せるものは移す」 で layer 3 incident の general kernel を hoist (instance は layer 3 に残置 = kernel-up / instance-down) |
| 2026-06-13 | §2.3 新設「SoT の read 側」 | 出張案件の status を問われ source document (個人 account のメール通知) を SoT と取り違え、 null から作話で誤結論した RCA を一般化。 §2.1/§2.2/§15 は write 側 (二重に作るな) だが read 側 =「source document の null は答えでない / session 開始時 context window は案件について空 cache / null の第一仮説は『読む store を間違えた』」 が未収録だった。 同日 sibling (cite-me lookup 不発 §8.12 / labnexus burn-down の lookup-context 不実施) と合わせ 2+ 観察 (§9.8 充足)。 layer-3 機械対策 = account routing guard + matter-status SoT-read dispatch (instance 残置 = kernel-up / instance-down) |
| 2026-06-13 | §9.9 新設「新定義は origin 例で自己違反しやすい / 自己違反は under-specification の probe」 | §2.3 を新設した直後、 その origin 例で external service を SoT 扱いした自己違反を user が指摘 → §2.3 に external source 区別を追加した meta。 RCA を書く act 中でその RCA が戒める分類誤りを再演 = 「直前 discipline の self-apply」 の specific 化。 self-violation が定義の seam を probe する (= 「source document」 が内部非選択 store と external source を 1 語に潰していた) を一般化 |
| 2026-06-13 | §9.9/§9.2 cross-ref 訂正 (mis-fit 削除) | §9.9 適用例 + changelog 行が §2.3 origin 事例を「§9.2 asymmetric reflection bias の一形態」と cross-ref していたのを fresh-eyes 独立検証で mis-fit と確認し削除。§9.2 = corpus の蓄積非対称 (失敗のみ記録 → 予防一辺倒肥大化、file 内の他 §9.2 言及と一貫) で、§9.9 の self-application miss (直前に書いた定義を自分の origin 例で破る) とは別機序。citation は surface 語「reflection」(= corpus が経験を非対称に映す vs 自己反省 act 中の盲点) の意味違いに乗っていた。純粋な §9.9 self-violation =「直前 discipline の self-apply」の specific 化として残置 |
| 2026-06-17 | §16 新設「要約は load-bearing な関係を不可視に落とす — derive-not-summarize」 | 交渉案件の「肝」(= 既存削減要望に応えられないが増えはしない、で可か) が source・中間台帳・会話の各要約段で繰り返し palatable 半分へ圧縮され同一 nuance が 2 回 re-drop した RCA を一般化。inline §3 (expose/hide) の要約ドメイン双子 + §8.11 (intake encoding) の specific form。芯 = derive-not-summarize (原本逐語保持)、補助 = §15-5 逆向き completeness check。instance は個人層 work-discipline + email-office 記録に残置 (kernel-up/instance-down) |
| 2026-06-17 | §9.10 新設「完全性 audit の add-bias」 | §16 新設直後の 4軸 sweep が一般則 §16 から niche な数式記法規約 (physics-notes 添字) へ下向き cross-ref を張る missed-cross-ref finding を出し user に撤回された RCA を一般化。完全性 frame は構造的に追加へ偏り低価値/mis-weighted な接続を製造 (§9.2 sibling・§16 の audit 域発現)。restraint = instance が一般 home へ上向き / missing-cross-ref は relevance bar / audit goal を「load-bearing な欠落」 に framing。 |
| 2026-06-21 | §2.5 新設「SoT 重複の 3 つの扱い (design-out vs reactive)」 | SoT-drift の戦略 frame (A/B/C trichotomy + 成熟度 lens + 検出器の drift-patch/surfacing 仕分け) が layer-3 plan (sot-maturity-normalization) にしか無く、§2.1-2.4/§15/§8.11 が個別戦術として散在していた。frame を hoist して上位 home を与え、plan は odakin 運用台帳への適用として上を指す (kernel-up/instance-down)。sot-registry に topic 追加 (§15-5)。user 依頼。 |
| 2026-06-22 | §4.2 新設「自己 RCA の severity-minimization — §4.1 の cure 不能な残余クラス」 + §4.1 内の解放済 positional ref (§4.2/§4.3) を脱-positional 化 | 外部宛 outreach で未検証身元を断定送信した失敗を RCA する session が、単純失敗を複数回「小さく・技術的に」 framing し直し user に都度訂正された incident を一般化 (= 主題がこの reflex の最中・訂正済み版でも再演)。§4.1 (motivated substitution) の self-RCA/severity 姉妹で、両 cure (機械 gate / payoff 変更) が使えない残余クラス → goal を予防→可視化+訂正ループ短縮へ下げ、blunt-first (出力 form 変更) + 外部 review backstop。pure minimization と区別する signature = dignified な失敗の inflate による displacement。instance は layer-3 個人層 (kernel-up/instance-down)。user 依頼。 |
| 2026-06-25 | §2.5 成熟度 lens「派生データ」row に (A) field-level view を併記 | 旧記載は (B) whole-file 生成のみで、手編集 file 内の単一導出可能 field (例: slug の純関数たる公開 path) を「書かず read 時に導出」 する design-out が表に無かった。2026-06-25「派生可能な値は格納しない」 一般化 handoff の cold-eyes verdict (= build all-no、規則は §2.5 に既存) が flagged した micro-edit を owner 採用。1 cell の clarification。 |
| 2026-06-29 | §8.16 新設「不在主張の channel scope — single-channel null は universal absence の証明ではない」 | layer-3 で institutional 締切超過の指摘に対し person-to-person mail sweep の null から「事前告知無し」 と universalize → 実は internal broadcast (= 学内 portal 掲示板) に 4 ヶ月前から告知あり、 を 2 段繰り返した RCA を一般化 (= 1 段目: mail sweep null → universal absence / 2 段目: 締切時刻を verify せず時間軸で「十分早い」 argue)。 §8.11 (intake leverage) の channel-category 軸 dual = downstream sweep がいくら丁寧でも intake で channel を取りこぼすと universal absence は嘘になる。 §8.14 (identity 軸 corroboration) との対 = channel 軸 coverage。 reflex = sweep scope template 「Verified = ___ / NOT verified = ___」 を埋める、 機械化されていない broadcast は honest framing で保留。 共著メール送信前の共著者 draft 確認 (= sender-side responsibility) を research-email.md に sibling section として併設、 receiver-side responsibility (= pre-outreach-identity-check) の対辺補完 (§9.8 充足)。 user 依頼。 |
| 2026-06-30 | §17 新設「階層内の同名 entity 併存 — SoT 表現で context path を明示」 | 大学組織で「学部内 X 専攻」 と「大学院 Y 専攻」 が同 word「専攻」 で並存する fact を 3 回の user 訂正連鎖を経て理解した RCA を一般化。 §2 (= 重複避け) §15 (= 多重記述 consolidation) と直交 (= 重複でなく collision、 各 reference は legitimate に別 entity を指す literal、 重複検出器の射程外)。 1 階層 frame 暗黙仮定 → 別階層誤訂正 → 二度ハマる cycle の prevention に SoT 表現の path 明示 + 階層併存 warning + errata history + context-tagged pointer を要求。 §4 (orient before act) trap (1) の上流、 §2.4 (errata marker) の collision domain 適用。 instance は layer-3 (= 個別 user profile) に sequester (= kernel-up / instance-down)。 user 依頼。 |
| 2026-07-10 | §8.12 に doc-tier 内 placement 軸 (= grep 着地点) を追記 | 運用 doc (= ID・token 表) を grep 読みする session に、 別 doc の一般則・文末 pointer が retrieval 窓外で発火しない miss 形を 1 事例 (= discord-bot.md UA 要件の再発 → canonical script + 着地点 routing pointer で design-out) から §8.12 item 4 の clarification として追記。 新 section は §9.8 bar (= 2+ 観察) 未満で見送り、 独立 2 例目で axis 昇格を再判定。 提案 kernel の残り (= 「invocation を伴う規則は script 化が最強」) は §14.5/§10.9/§2.5 既存で dedup (= build-nothing)。 cold-eyes handoff 経由、 起票者の一般化案を N=1 で down-scope |
| 2026-07-03 | §8.17 新設「broadcast で届く個人義務 — per-person addressing proxy の構造的 false negative」 | layer-3 で年次 institutional 義務 (= 受講報告 + 書類提出、 学内締切付き) の BCC 一斉配信 3 通 (宛名「各位」) が name-mention surfacing を全通貫通し、 個別名指しの 4 通目催促で発覚 = 締切 1.5 ヶ月超過の RCA を一般化。 検出層 (= per-person proxy の盲点、 §8.8 の broadcast 形) + intake 層 (= 認識済み義務の prose 記載 ≠ encoding、 §8.11/§8.12) の複合 failure と特定。 対策 = 同 turn encoding (= 判断規律の芯) + obligation-signal surfacing (= proxy-subset と明示) + リマインド反復の escalation 信号化。 sibling 2 件 (= 役員 ML 会議招集 suppress / 学内 ML 会議通知不検出) と合わせ 3+ 観察 (§9.8 充足)。 §8.16 (= 不在主張の channel 軸) の義務検出 direction 対。 user 依頼。 |
| 2026-08-20 | §8.23 新設「失効型〆切つきの機会 — 義務網と応答網の谷間に落ちる opportunity class」 | layer-3 で地域研究会案内 4 通 (BCC「各位」、 段階〆切つき) が約 3 ヶ月・4 経路 (名指し網 / 義務網 / 〆切抽出器の書式前置+早期告知 / 未認識 backlog の rolling 窓 silent 退場) を独立に貫通し発表申込〆切が silent 失効した RCA を一般化。 §8.17 (義務 broadcast) の機会版・§8.22 (失効型) の intake 前段・§8.18 (二日付軸) の horizon 変種。 対策 = 機会 intake 規律 (検討 entry or declared skip) + 〆切抽出器の書式/距離 audit + FP 分業。 本 class 直接 1 + 隣接 sibling 2 で §9.8 は隣接充足と明示。 user green-light 経由 (worker session 実装)。 |
| 2026-07-25 | §8.8 頻出 proxy 型に「repo tree / git dirt を変更・副作用の proxy にする」 row 追加 | OAuth credential 書き戻し箇所の一掃 sweep が、 書き込み先だけ repo 外 runtime dir の 1 箇所を見落とし (= dirt にならず発見対象外)、 同日の耐久性 audit も同じ runtime dir の credential 欠落 (1 マシン 45 日不在) を scan 範囲外にしていた = 「repo の外は sweep の外」 の同一構造 2 実例 (§9.8 充足)。 別調査の独立実測が両方を発見。 user 依頼 (「層1 SoT にできることある?」)。 |
