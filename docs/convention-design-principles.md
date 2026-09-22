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
| ローカル補助 | メモリ（~/.claude/...） | **このマシン固有の物理的事実のみ** (⚠️ 2026-09-02 訂正: 旧記述は「クイックリファレンス、行動矯正フィードバック」 だったが、 **2026-04-17 に方針変更済** = §5 の allowlist + `memory-guard.sh` の `deny` が現行。 行動矯正 feedback を memory に置くのは precedent-as-training-data 問題で禁止) |

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
- **メモリ**: このマシン固有の物理的事実のみ (⚠️ 2026-09-02 訂正: 旧記述「クイックリファレンス（正本へのショートカット）」 は §5「メモリはリポの規約を補強する『キャッシュ』ですらない」 と両立しない = 2026-04-17 方針変更の掃討漏れ)

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

適用事例: 物理研究リポ (研究 LaTeX project) — 規約 fact（Fourier 規約・loop 符号則・1PI↔amplitude 写像など）が複数の tex note に必然的に再掲される構造に対し、リポ CLAUDE.md に 5 行の序列表を宣言（2026-06-12）。導入動機は、誤推定 1 個が 3 つの note に伝搬した事故。

### <a id="sot-declaration-collision-sweep"></a>2.2 正本の宣言・引っ越しは「衝突宣言 sweep」とワンセット

正本を新しく宣言する、または別の home へ移すと、**その瞬間に旧 home・index・tree 行にある「これが正本」という記述が stale になる**。この staleness の発生を知っているのは宣言を編集した本人だけであり、同 commit が唯一安価な処理タイミング — 後続の audit は「2 つの宣言のどちらが新しいか」をそもそも知らない。

**Reflex:** 正本の宣言・移動を含む commit には、fact の keyword ×（正本|SoT|authoritative）の **repo 横断 grep を同梱**する。最高信号の drift は「**2 箇所が同時に正本を名乗る**」状態（どちらかが必ず stale）。markdown 表の row を部分差し替えしたときは列数も数える（旧セルの尻尾残存で列崩れしやすい）。

適用事例: 2026-06-12、同一 session 内で 2 連発 — ① 序列表は note を正本へ更新したのに script の tree 行が「script が SoT」のまま残存、② row 差し替えで旧 derived セルが残り 3 列表が 4 列化。どちらも宣言 commit 直後の grep + 目視で検出・修正。編集者本人の直後 sweep 以外に拾う仕組みがない型。

**use-site の stub 規律（= 宣言の双対）:** fact の正本を宣言したら、それを*言及するだけ*の他の use-site は「最小安定警告 + pointer の stub」にする — volatile な詳細（係数・出典・erratum・手順）を copy せず正本だけに置く（詳細を copy した瞬間に新たな重複が born する）。point-of-use marker は (a) 発火に要る最小・安定・行動可能な警告 + pointer と、(b) 発火に不要で drift する詳細 payload に分解でき、use-site が要るのは (a) だけ。これは §16「正本本体は source の逐語」の反転 dual =「derived な use-site は最小要約 + pointer であれ」で、詳細の home を 1 つに保ったまま fact を point-of-use で発火させられる（= 発火と SoT 単一性は両立する、「自己完結 marker が詳細 copy を強制する」は false dilemma）。最高 leverage の発火面は宣言が born する commit 時点（= 機械化できるなら commit-time の declaration warn）。

### <a id="harmonization-amplification"></a>2.2b 派生文書間の不一致は SoT に対して解決する — 調和による増幅 (harmonization amplification)

整合性 sweep が derived 文書間の不一致 (匿名 vs 名指し、 旧値 vs 新値) を発見した時、 「不一致の解消」自体を成果と数えて解消方向を**相互調和**に取ると、 sweep は誤りを**発見した上でそれを正しい方に上書きする** — 誤りの検出器が誤りの裏付け文書を製造する。 暗黙の裁定規則になりやすいのが **specificity bias** (= 具体度が高い方が情報量が多く見え「正しい」と扱われる) だが、 具体性は生成の産物でもある (= 最も具体的な版が最も新しい confabulation でありうる)。

**Reflex:** derived 間の不一致を見つけたら、 解決方向は「互いに合わせる」でなく「**SoT に対して検証**」 — どちらが正しいかを外部 anchor (正本 repo・一次資料・機械検査) に問う 1 手を、 調和の 1 手より先に置く。 整合性軸の検査は**内部無矛盾しか見えない** — coherent な誤りは整合性軸の不動点であり、 整合性 sweep を重ねるほど強くなる。 誤りを割るのは常に外部 anchor だけ。

実例: 派生文書 A (提出文書の tex、 誤った名指し) と B (状態 doc、 匿名でほぼ正しい) の不一致を整合性 sweep が発見し、 B を A に合わせて「特定」 と commit — 合成された gloss は一次資料 (当該 arXiv の著者 list) と 1 手で矛盾する文で、 その矛盾が後日の検出 trigger にもなった (= 増幅は事故を悪化させると同時に自己矛盾を焼き込む)。 claim-target 帰属の domain 版 = [`actor-attribution.md#claim-target-attribution`](../conventions/actor-attribution.md#claim-target-attribution) 規律 9。

### <a id="sot-read-side"></a>2.3 SoT の read 側 — entity を「言及するだけの store」を SoT と取り違えない

§2.1/§2.2/§15 は **write 側**（正本を二重に*作る*な・宣言の衝突を sweep せよ・多重記述を是正せよ）。SoT には **read 側の双対**がある: ある案件の status を答えるとき **その案件の SoT を読む** — その entity を*言及するだけ*の別 store（受信メール・領収書・通知・log）を SoT と取り違えてはならない。

一つの実世界 entity は多数の store に現れる（ある予約はメール・PDF・チャット通知・業務台帳に出る）。**特定の案件について authoritative なのは 1 つだけ**で、他は **source document**（SoT が cite する材料）にすぎない。さらに **SoT は自分が制御する内部 store（grep 可能・durable・自分の repo）でなければならない**: 外部サービス（予約サイト・vendor portal 等）とそれが送ってくる通知・領収書は、変化・喪失・stale がありこちらが制御できないので **SoT たり得ない external source**（先方の system-of-record であっても、こちらから見れば snapshot にすぎない）。必要な fact は内部 SoT に **absorb** する — 外部 fact を内部にコピーするのは二重 SoT ではない（外部は元々 SoT でない）。**source document・external source の沈黙・null は案件の答えではない。** ＝「二重 SoT」は多くの場合*存在しない*: 内部の非 SoT store / external source と正しく分類すれば内部 1 SoT に解消する（design-out であって reactive 管理ではない）。

**Reflex（read 側）:**
- 「〜は済んだ?／頼んだ?／どうなってる?」型の **matter-status 質問**には、手近な source document だけで即答せず **その案件の SoT を読んでから**答える。
- **session 開始時、context window はその案件について空の cache**。会話に流れてきた情報や直前に fetch した 1 store を「知っている＝真実」と扱わない。SoT は disk 上にあり、取りに行くのは option でなく前提。
- source document を読んで見つからない時の第一仮説は「案件が無い」でなく **「SoT を未読／読む store を間違えた」**。null は世界の事実でなく「探す場所が違う」証拠。

write 側「one fact, one home」（[`personal-layer.md#owner-automation-shared-project`](personal-layer.md#owner-automation-shared-project) の partition / MOVE-not-copy。 ⚠️ 2026-09-02 修正: 旧 ref `§publish-boundary` は実在しない anchor だった = §14.7 の HARD dangling）と対で、read 側は「one matter → read its single SoT」。**二重 SoT を*作らない*のと source document を SoT と*読み違えない*のは同一原則の両面。**

origin: ある案件（出張の証明書類）の status を問われ、会話冒頭で見ていた source document（個人アカウントのメール通知）を SoT と取り違え、その null から「未対応／記録なし」と結論 + 不在を説明する誤った root cause を作話。実際は別 SoT（業務台帳）に完全記録済で 1 grep の距離にあった。write path（記録）は完璧、read path（SoT を読む）が崩れた型。同日 sibling = 横断 lookup を要する案件で SoT 直読より手近 store を先に見た失敗（§8.11 / §8.12 と同根）。layer-3 機械対策 = source store を業務 query で検索したら正しい SoT へ routing する guard + matter-status を SoT-read に乗せる dispatch（instance は layer 3 archive 残置 = kernel-up / instance-down）。

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

origin: 研究費様式の交通費記入ルールを是正した session。確定版を SoT（規約 md）へ書いた後も既存 TODO 2 件が旧暫定を live で肯定していた（= §2.2 sweep で発見し本文是正）。加えて**削除できない履歴**（事務担当宛の送信済メール draft / 過去の打診記録）に旧暫定が残り、こちらは是正でなく errata marker で「当時の誤り」を明示し本文は温存した。user 指摘「過去の誤った判断・知見には『これは誤り』とあとで分かる注を、上層で規律化してよい」。

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

規則・禁止・必須手順の適用を自分の判断で変えそうになった場合の規範と機械検査は、[agent-rule-ownership.md](../conventions/agent-rule-ownership.md#rule) が所有する。

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

**帰責軸の追記 (2026-09-01) — attribution drift**: 同じ self-serving generator の第三の軸。 §4.1 は *成果物・手段* (価値の流れを自分経由に保つ)、 本節本文は *深刻さ・性質* (severity framing)、 そしてもう 1 つが **帰責先** — 自分の機構が原因の失敗を記述するとき、 原因の帰属が「主体をぼかす → 相手や環境に寄せる → 隣接 system に寄せる」 の順に**自分から遠い候補を先に試す** drift。 pipeline 型の失敗 (= 分類したのは外部 service、 握り潰したのは自分の設定) では「嘘ではない」 帰属先の連続体が逃げ道を供給するため、 各 step が正当に見える。 対策: 不手際の原因記述は**因果の最終決定点** (= どの機構がその挙動を選んだか) に帰属させ、 相手への帰責を含む文は送る前に 1 回「不備の主体は誰か」 を問う。 origin: 2026-08-31、 見落とし事故の詫び文の原因記述が 4 連続で user 訂正を受けた (曖昧化 → 相手帰責 → 外部 service 転嫁 → 最終形 = 自機構への正確な帰属)。 domain instantiation (詫びメールの書き方) = [`research-email.md#apology-cause-attribution`](../conventions/research-email.md#apology-cause-attribution)。

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

**実例 (2026-09-13、 公開 repo の例示)**: 公開 repo の規約に残っていた未公開原稿の例示が、 後の hoist の書き方の手本になり、 禁止の規則ができた後にも同じ書き方が 2 回繰り返された。 それまでの修正はどれもその日に見つけた分だけを直していた = **前例の側を掃除しない限り、 規則を足しても手本は残る** (掃除の道具 = claude-config `scripts/check-unpublished-quote.py --scan-tree`)。

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

origin: 官製様式の docx 記入要領削除。 run 直接色だけ見る strip + phrase list 照合の検証が **両方 pass** したのに、 段落 style 継承の色付きガイダンスが残存。 決定論 check が緑なのに実際は残っており、 人が rendered 色を目視して初めて発覚 → 検証を「色そのもの (PDF span color)」 に変えて決着。 「決定論 check ✅ ≠ 正しい」 は [office-automation.md#docx-checkbox-content-control](../conventions/office-automation.md#docx-checkbox-content-control) の「validator は必要条件であって十分条件でない」 と同根。

### <a id="set-diff-false-positive"></a>8.9 set 差分で drift を検出する時、差分には「真の違反」 と「正当な乖離」 が混在する

§8.8 が detector の **false negative** (= proxy 盲点で見落とす) なら、 本節は **false positive**。 2 つの集合の差分 (= A にあって B にない) で drift を検出する detector は、 差分を全て「違反」 扱いすると noise を生む。 差分には (a) 真の違反 (= 直すべき drift) と (b) 正当な乖離 (= 別管理・環境差・意図的例外) が混在し、 (b) を filter で除外しないと detector が信用されなくなる (= §8.8 の false confidence の逆問題: 狼少年化)。

**正当な乖離の典型**:
- **別管理対象**: 検出対象の集合に「そもそも SoT に載せない category」 が混じる (例: 参照用に clone した他者の成果物 vs 自分が管理する成果物 — 後者だけが SoT 登録対象)。
- **環境差**: マシン / 環境ごとに存在が違う要素 (例: ある環境に未取得の項目を「欠落」 と誤検出)。 検出は **環境非依存な軸** (= 全環境で true な属性) でのみ行う。
- **意図的例外**: 既知の例外 list (= 規約上 SoT に載せないと決めたもの、 fork 等)。

⚠️ 本節は **detector に作り込む filter** の設計。 **走らせた run の出力をその場で「偽陽性」 と宣言する行為**は別物で、 そちらの証拠要件は [#false-positive-declaration-needs-control](#false-positive-declaration-needs-control) (= positive control を出せないなら「未検証」)。

→ reflex: set 差分 detector を書く時「差分の各要素は本当に違反か、 正当な乖離か?」 を問い、 (b) を除外する filter を **明示的に設計** する (= 除外理由を code comment + doc に書く = §8.8-3 の no silent caps と同じく「何を・なぜ落としたか」 を可視化)。 naive な全差分 flag は false positive 源。 ⚠️ 逆に filter を効かせすぎると真の違反まで黙殺する (= §8.8 に戻る) ので、 filter は「正当性が確証できる category」 のみに限定する。

origin: 2026-06 「実在する X が SoT 一覧に未登録か」 を検出する detector で、 naive 差分が『別管理の参照 clone』『別環境に未取得の項目』 を false positive にした。 self-owned ∧ 環境非依存 ∧ 非例外 の filter で真の違反 (= 1 件) のみに絞った。

**共有語彙 token の変種 (2026-09-01 追記)**: substring/token 照合の drift detector で、 anchor 語彙が**他の正当な topic と共有される** (例: 特定 tool の実装詳細を表す語が、 別 tool の同種機構の作業記録でも普通に使われる) 場合、 file 全体 scan は無関係な正当記述を将来 false-block する時限 FP になる — token を**当該 topic に言及する文脈 region に scope** する。 かつ scope の粒度は **doc の構造単位に合わせる** (= dated-entry 単位。 段落単位だと「topic 名は見出しにだけあり本文が語を繰り返さない」 正当構造で false negative に転じる)。 正負両方の fixture (= topic 文脈内の token → flag / topic 外の同 token → pass) を selftest に焼く。 origin instance: 2026-09-01 Codex integration checker の SESSION durable-token scan (検収で発見 → entry-scope 化)。

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

<a id="derived-external-deadline"></a>変種 (2026-09 追記) — **公式規則から逆算した期限も外部 hard deadline**: 規程が「出発・開催・提出の N 日前まで」と定める期限は、台帳に入れる暦日を起票者が計算していても**自己設定の目安ではない**。起票時に (a) 基準日、(b) lead time、(c) 根拠資料、(d) 算出日を同じ record に残し、失効性があるなら hard / elevated として encode する。`source: derived` や算出作業を理由に soft へ落としてはならない。期限後に謝罪を伴って受理された実績は例外処理の証拠であって、通常期限を書き換える precedent ではない。

<a id="receiverless-handoff"></a>変種 (2026-07 追記) — **受信者不在 handoff / documented false coverage**: mechanism A が case を「それは mechanism B の領分」 という routing 根拠で除外・suppress する時、 **B がその case を実際に受け取る channel を持つか**を verify する。 B の coverage が intake 前提 (= 人間判断による tracked object 化を待つ) なら、 その除外は誰も受け取らない handoff になり、 しかも code comment / doc に routing 根拠が明記されているせいで**意図された設計に見える** (= gap が最も発見されにくい形 — 網の不在でなく「網があるという文書化された誤信」)。 観測 (2026-07、 同一 incident 内で独立に 2 機構): ① 日付抽出器が締切文脈の日付を「期限 mechanism の領分」 として除外 — 先方は登録済み対象しか読めず、 無人窓では登録する主体が不在 / ② mail 検出器が特定 label を「専用表示段が cover」 として日次 push から除外 — 専用段は pull 専用で無人経路ゼロ = 除外が silent な配信降格になっていた。 evidence base は 1 incident 2 機構 (= §9.8 の 2+ は機構数で充足、 incident 数では N=1 と正直に注記)。

<a id="recall-dependent-firing"></a><!-- legacy alias: 旧 anchor 名 (rename 前) への外部参照を生かす後方互換 -->
### <a id="firing-surface-hierarchy"></a>8.12 規律の発火面 hierarchy — doc 記載 (recall 依存) は最弱、 書く前に発火面を選ぶ

規律・手順は「内容」 と別に「**どうやって正しい瞬間に発火するか**」 という独立の設計軸を持つ。 doc に書かれた規律の発火は「その行を正しい瞬間に想起する」 という recall に依存し、 これは反復的に不発する — **機械補強 column に tool 名を書いても、 tool の存在自体が想起されなければ発火しない** (= tool は能力であって enforcer ではない)。

発火面の hierarchy (強 → 弱):

1. **hook** = tool call の決定的 interception。 条件を機械的に書けるときの最強手段 (§8 本文)。 ただし trigger が「意図」 を識別できないなら false positive が fleet を毀損する → 見送り判定は [`conventions/hook-authoring.md §10`](../conventions/hook-authoring.md#hook-no-go-judgment)
2. **personal skill** = frontmatter description が**全 session 常時 context 内**にあり、 model が「今がその瞬間」 と判断して自律 invoke (= recall を harness が肩代わり)。 trigger を機械条件で書けない judgment 系に向く。 非発火時 noise ゼロ / worst case = 現状維持の非対称 upside / 発火は確率的。 機構詳細 = `conventions/personal-skills.md`
3. **scheduled task** = 無人定期 + Claude judgment ([`conventions/scheduled-tasks.md §0`](../conventions/scheduled-tasks.md#execution-locus-selection))
4. **doc 記載** = 最弱と自覚して使い、 後日 1-3 への格上げ trigger 条件を書き残す

⚠️ 実務で最も多い抜けは 3 と 4 の**間**に在る「**手動の入口 script**」 (= dashboard / CLI に検査を足して終わりにする形)。 検査自体は自動化されたが **実行は人が入口を叩くことに依存**するので、 発火面としては 4 に近い。 とくに **その検出器を作った動機が「人が見ていなかった」 だったなら、 発火面を「人が見に来る」 に置くのは元の失敗の再生産**である (= 安全網を、 それが覆う失敗モードと同じ経路に依存させている)。 検査を書いた turn に「**これは誰の・どの event で走るか**」 を 1 行で答え、 答えが「気が向いたとき」 なら 1-3 のどれかへ配線するまでが 1 単位。 ⚠️ 「CI に入っている」 も答えにならないことがある — **finding を warn 止まりにして exit 0 なら CI は緑のまま**で、 log を読む人にしか届かない ([§22](#silent-probe-false-healthy) の表示版)。

実測 (2026-09-12): auto-load される規律 file の肥大検出器が、 まさに「**過去 2 回とも肥大の発見が人間の手動だった**」 ことを動機に作られながら、 発火面は入口 script (dashboard) だけだった。 CI からも走っていたが warn 止まりで緑。 結果、 閾値超過は「たまたま誰かが入口を叩いた turn」 にしか見えず、 実際その通りにしか見つからなかった。 対処 = **同じ engine を session 開始の surfacer に配線** (= 閾値内は完全沈黙なので noise 増はゼロ、 payload も dashboard と同一)。 instance は個人層に残置 (kernel-up / instance-down)。

<a id="notice-on-the-path-actually-read"></a>**表示時の注意を足す面は、 事故の session が実際に使った読み取り経路から選ぶ**: 対策案に書かれた面 (「この command の出力に 1 行出す」) が、 そもそも対象の種類を表示していないことがある (実測: 注意を足す候補だった 2 つの command は、 事故の原因になった種類の記録を表示しなかった)。 どの command・view・生 file で読んだかを事故の session の記録 (tool call) から引き、 その面に足す。 表示を挟めない経路 (生 file を直接読む) が残るなら、 それを射程外として doc に書く。 足す前に、 全履歴に述語を当てて発火件数と誤検出を数える (較正の標本の偏り = [§8.46](#semantic-detector-ack-ratchet))。

<a id="wired-is-not-yet-firing"></a>**配線した瞬間と、 効き始める瞬間は別** — 発火面ごとに遅れが違う。 検出器を別の機械へ配るとき、 「pull すれば効く」 は面によって正しくない:

| 面 | 効き始める時点 | 理由 |
|---|---|---|
| session 開始時に読まれる設定に登録する hook | **次の session から** | その session の hook 一覧は開始時に読み終わっている。 配線した当の session では鳴らない |
| 実行のたびに source を読み直す入口 (手動の dashboard / CLI) | 同期された時点から**即時** | 起動のたびに現在の code を読む |
| 一覧を自動発見する runner の test / selftest | **その runner の次回起動** | 発見は起動時に 1 度 |
| 無人の定期実行 | **次の発火時刻** | 登録の変更が届くかは ensure の実装による ([multi-machine-state.md#ensure-reconciles-content](../conventions/multi-machine-state.md#ensure-reconciles-content)) |

⚠️ 3 つの含意:

1. **「配って終わり」 と言う前に、 最初に鳴る機会がいつか**を面ごとに答える。 稀にしか起きない事象を捕まえる検出器では、 1 回分の遅れが「次に起きるまで丸ごと」 になりうる。
2. **配線直後の session で鳴らないことを「壊れている」 と誤診しない** — 逆に、 そこで鳴らないのを見て「動いている」 と誤って安心することもある (= 鳴る条件が無かっただけかもしれない)。 死活は**壊れた state を注入して確かめる**のが唯一確実 ([§22](#silent-probe-false-healthy))。
3. **遅れの無い面を併設すると、 待ち時間を実質ゼロにできる** — 同じ engine を「次の session から効く面」 と「同期した時点で効く面」 の両方に登録すれば、 配った直後は後者が、 以後は前者が受け持つ。 §8.12 が 2 面を勧める理由 (= 人が見に来る面だけに依存しない) と、 同じ配線が遅延の面でも効く。

<a id="lower-layer-arrives-first"></a>**変種 — 層ごとに届く経路が違うと、 使う側が使われる側より先に届く**: 層の違う 2 つの repo が別の経路で各機械に同期される (例: 個人層は無人の定期実行が毎時 pull し、 共有の層は session を開いたときだけ pull する) と、 **新しい部品を使い始めた側の変更だけが先に届く**機械が出る。 そこで使う側が「部品が無ければ止まる」 と書いてあると、 それまで動いていたジョブが部品の到着まで失敗し続ける (誰も session を開かない常駐機ほど長い)。 使う側は部品の有無を見て、 **無ければ従来の動作に倒す** (部品の読み込み失敗を理由に終了しない)。 部品が届いて初めて新しい挙動になる = 配った側から見た効き始めは、 遅い方の経路で決まる (上の表)。

### <a id="documented-not-wired"></a>8.12a′ 症状表に「対処」 を書いても、共有 engine に入っていなければ効いていない (2026-09-12)

規約の症状表・落とし穴表に *対処* を書くと、それは「分かっている」 の記録であって「効いている」 の記録ではない。**その対処を誰か 1 つの project が自分の script で実装し、共有 engine は適用しないまま**、という状態が最も見つかりにくい: 規約を読む人は対処が書かれているので安心し、engine を呼ぶ人は engine が存在するので安心する。どちらも「自分の側では済んでいる」 と読む。

実測 (2026-09-12): ある共有 engine の正本規約に、同じ出力の silent な壊れ方 3 行とその対処 (前処理・引数追加・出力検査) が 2 週間前から書かれていた。対処の実装は或る paper repo の中だけに在り、engine は 1 つも適用していなかった。engine を呼ぶ別 project は、その壊れ方が起こる条件 (当該 macro 定義) を満たしていた = **規約上は既知、運用上は無防備**。

reflex: 症状表に対処を書く / 読むときに **「この対処は誰が実行するのか」** を 1 行で言えるようにする — 答えが「読んだ人が思い出して手で」 なら発火面は最弱 ([§8.12](#firing-surface-hierarchy) の 4) であり、共有 engine があるなら**そこに入れるまでが 1 単位**。逆向きの点検も安い: **project 側に在る script が、上層の engine に無い機能を持っていないか** (= 下層が上層を追い越している箇所は、他の呼び元が丸ごと取りこぼしている)。実装したら表の行に道具への link を張り、engine の既定に入れる。

**実例 (2026-09-13)**: 機密の逐語照合 gate は作られ、 docstring にも「remote 付き repo に commit されるのを止める」 と書かれていたが、 呼び出しは private repo の hook chain にだけ在り、 **公開 repo の pre-commit からは一度も呼ばれていなかった** (= 一番守るべき target で走っていない)。 公開 repo の runner に配線し、 実際の hook を通す確認 (`check-unpublished-quote.py --check-wiring --through-hooks`) を定期検査に入れた。

### <a id="automation-trigger-routing"></a>8.12a 「自動化」は mechanism 名ではない — 5 軸で発火経路を先に route する

「自動化して」「あとで見て」「監視して」は mechanism の指定ではなく、**将来の
obligation を登録せよ**という intent である。これを即座に cron / scheduled task へ
写像すると、同一会話へ戻るべき follow-up が別 session に散る、deterministic script に
LLM token を払い続ける、local file が必要なのに cloud に置く、event trigger があるのに
polling する、といった locus mismatch が生じる。

実装前に次の 5 軸を決める:

1. **wake event** — 時刻、間隔、外部 event、tool/session lifecycle のどれか。
2. **judgment** — run-time に model の判断・要約・draft が要るか。不要なら OS scheduler
   / CI / event handler の deterministic path を優先する。
3. **context continuity** — 現会話の文脈へ戻るのか、self-contained な独立 run か。
4. **execution locus** — local file / credential / network が必要か、hosted で完結するか。
5. **authority** — read/check/draft までか、送信・公開・削除等の外部 action まで無人化を
   許可されているか。

この 5 軸の答えから hook / skill / heartbeat / standalone schedule / OS scheduler /
service event trigger を選ぶ。製品が requested trigger を持たない時は「近い mechanism を
黙って代用」せず、未実装を明示して polling 等を別 option として user に選ばせる。
point-of-use の製品別 dispatcher はこの原則への薄い pointer とし、surface 名や schema は
製品別 SoT に隔離する。

origin: 同じ「定期・あとで」要求が、同一会話 heartbeat / 独立 project run /
deterministic local job / lifecycle Hook / hosted app event の 5 系統へ分かれる Codex
automation routing の実装。既存の Claude local scheduled task / cloud routine / launchd の
locus 分岐と合わせ、2 vendor・複数 mechanism で同じ mismatch を観測した一般化。

doc-tier 内にも placement 軸がある (= grep 着地点): **運用 doc (= ID・token・座標等の実務値の表) への到達はしばしば linear read でなく grep** で、 着地した session は hit 周辺の値だけ抽出して離脱する。 別 doc に住む一般則も、 同 file 文末の「関連」 pointer も、 その retrieval 窓に入らなければ発火しない (= doc は開かれたのに規則が context に入らない — 「想起されない」 〔本節冒頭〕 とも「in-context なのに不適用」 〔[§4.1](#motivated-substitution-trap) Evidence〕 とも別の miss 形)。 ∴ doc-tier に留まる規則が実務値と別の場所に住むなら、 **値の隣 (= grep 着地点) に canonical recipe / script への routing pointer を置く** ([§2](#no-duplicate-rules) の pointer 原則は「pointer にせよ」 と言うが置き場所を規定しない — 発火面としては placement が load-bearing。 手順そのものは [§14.5](#mechanical-script-extraction) の script 化が上位互換)。 origin: 運用 doc を grep 読みした session が、 別 doc に完備だった API header 要件 ([`discord-bot.md` UA 節](../conventions/discord-bot.md#discord-api-user-agent)) を素通りして再発させた 1 事例 (2026-07-10、 cure = canonical script + 着地点 routing pointer)。 ⚠️ 1 事例からの clarification につき新 section / 新 axis にしない ([§9.8](#single-observation-scope-check) bar 未満、 独立 2 例目で axis 昇格を再判定)。

reflex: 規律を doc に書く瞬間 + doc 記載規律の不発 RCA を書く瞬間に「これは 1-3 のどれかに乗らないか?」 を問う。 「reflex の徹底」 を再発防止策として書きそうになったら、 それは発火面の選択を skip した signal。 併せて、 新機構を増やす前に既存 enforcement channel (installer / `--check` / SessionStart surface 等) への相乗りを先に検討する (= 機構増殖の抑制、 §9.6 subtraction と同方向)。

origin: 横断 lookup script が規律表の機械補強 column に**記載済みなのに**初手 routing で 2 回不発した事例 (script 新設の起点になった null 誤結論 + 後日の遠回り routing)。 personal skill 化して description dispatch に乗せた結果、 skill 名を含まない自然な質問への初手発火を新 session trace で確認。 [`conventions/hook-authoring.md §5.3`](../conventions/hook-authoring.md#discipline-cannot-replace-hook) (規律で hook を代替できない) に「中間 tier として skill がある」 を加える位置付け。 2+ 事例 + 既存 §5.3 系列からの一般化 (§9.8 充足)。

⚠️ **検証資産 (selftest / \*.test.sh / index `--check`) も同じ hierarchy に従う** — 存在するが CI / pre-commit に未配線の test は doc-tier (= 誰かが思い出して回した時だけ効く recall 依存)。 実例 (2026-07-10): test 資産 20 本超を持つ repo に CI を初導入した**初日**に、 owner 環境では不可視だった別 OS 全滅 bug と自動生成 index の 10 日 drift が露出した — 資産の存在と発火面は別物。

### <a id="symptom-keyed-entry-point"></a>8.12b doc tier の中にも強弱がある — home は topic 側、 入口は「症状の瞬間」 側に置く

§8.12 の hierarchy 4 位 (= doc 記載) を選んだ後に、 もう一段の設計判断がある: **どの doc から指すか**。 規律を正しい層・正しい topic の doc に置いても、 その doc の `when` (= いつ読むか) が **topic 分類**で書かれていると、 実際に規律が要る瞬間 (= **症状**が出た瞬間) と鍵が合わず不発する。 「層も内容も正しいのに読まれない」 はこの形で起きる。

- **実例 (2026-09-10)**: 並列 session の commit を事後に区別する読み方を `conventions/multi-session-coordination.md` に置いた。 層も topic も正しい。 だがその doc の `when` は「並列 AI session と同じ repo を触るとき + spawn/handoff を設計するとき」 = **設計する瞬間**。 一方その読み方が要るのは「commit が消えた / この行はいつ入ったのか」 という **git 考古学の瞬間**で、 その時に人は並列 session の設計 doc を開かない。 修正 = 全 repo が読む `CONVENTIONS.md` の Git 規約節に**入口 (= 数行の pointer)** を置き、 本文は元の home に残した。
- **一般形**: **home (= SoT、 1 箇所) と入口 (= 発火面、 N 箇所) を分けて設計する**。 home は topic taxonomy 上の正しい場所に、 入口は「その規律が要る瞬間に人が既に開いている doc」 に。 入口は最小 (= 症状 → pointer) に留めて payload を複製しない ([§2](#no-duplicate-rules))。
- **判定の問い**: 「この規律が要る**瞬間**に、 人は何を読んでいるか?」 — 「この規律は**何の話題**か?」 ではない。 前者で入口を決め、 後者で home を決める。 両者が一致する規律もあるが、 一致を既定と思い込むと上の型で不発する。
- 入口を足すのは **実際に不発を観測した症状**に対してだけにする (= 予防的に全 doc へ撒くと [§9](#triage-and-subtraction) subtraction の対象が増えるだけ)。

### <a id="completion-boundary-state-gate"></a>8.12c 複数段 workflow は中間 command でなく完了境界の状態を gate する

変更 → 検証 → 永続化 → 配信 → 読み戻し、のように価値が複数段を完走して初めて届く workflow では、各段の成功がそれぞれ「終わった」感を作る。build 成功、worktree clean、commit 成功は中間状態であり、delivery の postcondition ではない。**完了報告の直前を独立した stage boundary として定義し、そこで最終状態を直接観測する**。

media delivery も同じで、agent が browser tool 内の player を生成・再生できたことは中間状態にすぎない。
user 向け postcondition は **user-visible surface に直接開ける link / local media file が在ること**であり、tool 側 screenshot や
accessibility tree はその証拠にならない。具体規律は [`mid-turn-text-visibility.md#tool-side-media-not-user-visible`](../conventions/mid-turn-text-visibility.md#tool-side-media-not-user-visible)。

gate の入力は「どの command を実行したか」という履歴より、workflow が要求する**状態ベクトル**を優先する。Git delivery なら task 由来 dirt、local `HEAD`、tracking ref の ahead/behind、live remote branch head。外部送信なら送信済み receipt と読み戻し、生成 mirror なら source/target digest、という形である。状態を見れば、command 自体の未実行、途中失敗、別 call へ残した最終 leg のいずれも同じ未充足として扱える。具体的な Git 契約は [`CONVENTIONS.md#completion-git-gate`](../CONVENTIONS.md#completion-git-gate)。

既存 state を task の失敗に誤帰属しないため、可能なら最初の mutation 前に baseline を取る。完了時の状態が baseline と同じなら、着手前からの無関係 dirt を agent の変更として stage しない。一方、baseline 取得後に変化した state、local/remote head の不一致、live state の照会不能は silent pass にせず、解消または明示例外へ送る。

発火面は**最後の安全な境界**へ置く。PostToolUse の nudge は特定の中間操作に結び付き、後続操作で状態が変わるうえ、agent が読まずに終了できる。commit hook は commit 内容を止められるが、agent の完了発話は見えない。製品が turn-end の blocking continuation を持つならそこへ state gate を置き、直接の instruction pointer と併用する。Codex での適用と一回継続の限界は [`codex/PARITY.md#completion-git-gate-hook`](../codex/PARITY.md#completion-git-gate-hook)。

回帰 test は happy path だけでなく、最終 leg を1本ずつ抜いた negative control を持つ。少なくとも未永続化、永続化済みだが未配信、remote 先行、live state 読取不能、後続の正規操作で gate が解除されることを別 fixture にする。「gate script が起動した」だけでは delivery property を検証していない。

origin: 長い変更 task で既存の commit/push 規則と dirty nudge が在ったのに、local build 成功が終端として解釈された事例。規則の不在ではなく、直接入口の不在、完了 event の曖昧さ、通知のみで block しない発火面、clean-but-unpublished を見ない proxy が重なった。処方は規則追加でなく、既存正本への入口と completion-state gate の追加だった。

### <a id="human-memory-not-a-carrier"></a>8.12d 人の記憶も carrier ではない — 「あとで 1 回やって」 を人に渡さない

§8.12 は agent 側の規律が recall に頼ると不発する話だった。 同じことが**人に渡す手順**でも起きる: 「別マシンで次を 1 回実行」 「次に◯◯するとき△△して」 「落ち着いたら確認して」 を chat に書いて終えると、 その手順を正しい瞬間に思い出す責任が人の記憶に移る。 人は覚えていられないし、 chat は流れて二度と表示されない = **push されない記録** ([`multi-session-coordination.md#green-light-carrier`](../conventions/multi-session-coordination.md#green-light-carrier) の人向け版)。

手順を人に渡す前に、 上から順に当てる:

0. **今この turn で自分でやれるなら、 やる** (= 手順にしない。 [`concise-output.md#user-facing-steps`](../conventions/concise-output.md#user-facing-steps) の 4)
1. **既配線の自動適用に載っていないか確かめる** — 例: git pull 後の session 開始で冪等に再走する installer。 載っていれば手順は書かず「次の session 開始で自動」 とだけ言う (= 確かめずに手順を書くと、 不要な作業と覚える負担だけを渡す)
2. **載っていなければ自動適用に足す** (冪等・fail-open・完了で沈黙)
3. **人手が本当に要る** (認証・物理操作・人の判断・外部への送信) なら、 **条件付きで出続ける carrier** に載せる: 期限つき TODO、 または特定マシン・特定状態でだけ session 開始時に出る発火 ([`multi-machine-state.md#machine-gated-pending-action`](../conventions/multi-machine-state.md#machine-gated-pending-action))。 完了を機械的に判定して自然に止める
4. chat に書く手順は carrier の**中身の写し**として添え、 その carrier を名指しする。 chat だけで渡さない

判別: 最終メッセージに「1 回実行」 「次に〜するとき」 「あとで」 「忘れずに」 と依頼の語尾が並んでいたら、 それが 1〜3 のどれに載ったかを同じメッセージで名指しできるか。 名指しできなければ carrier が無い。

<a id="state-handoff-is-the-worse-form"></a>**禁止形は 2 つあり、 後者の方が悪い** — (i) **作業**を渡す (「あとで 1 回やって」)、 (ii) **状態**を渡す (「この点は覚えておいて」 「頭の片隅に」)。
(ii) は「自分の側に残った未確認・注意点・読み違えやすい所」 を人の頭に預ける形で、 (i) より見つけにくい:
依頼の語尾を持たないので手順の検出に掛からず、 渡す側は「情報共有した」 と感じて完了扱いにする。 しかし
**作業なら carrier に載せ替えられるのに対し、 頭に預けた状態は載せ替え先が無いまま黙って減衰する**。

∴ (ii) を書きかけたら、 **その状態を出力する主体を人から機械へ移す**: 未確認なら検査にその状態を
**別の語で言わせる** ([`../conventions/confidential-repo-boundary.md#not-configured-is-not-nothing-to-protect`](../conventions/confidential-repo-boundary.md#not-configured-is-not-nothing-to-protect) の
`未配線` がこの形 — 「設定が無い」 を「守るものが無い」 と混ぜず、 毎回の検査に出し続ける)。
読み違えやすい所なら、 誤読する側の出力にその注意を埋める。 どちらも「人が覚えている必要」 を 0 にする。

⚠️ 検出を書くときは **状態の問い合わせ・報告**と分ける (「覚えていますか」 「覚えていませんでした」 は
依頼ではない)。 実測では、 素朴に「覚え」 で拾うと hit は全部この側で、 依頼形 (= 「覚えてお/覚えと + いて」) に
絞ると過去の最終発話の corpus で 0 件になった (= 陽性対照は別に用意する)。

<a id="manual-work-in-design-records"></a>**3 つ目の形 = 設計記録に「手作業で」 を置く** — schema や規約を変えた記録に「既存分は user 主導で手動移行」
「圧迫しないタイミングで手作業」 と書き、 lint は違反の件数を dashboard に出すだけにする形。 chat でなく正本の文書に
書かれるので carrier があるように見えるが、 実行する人も時期も決まっておらず、 件数の表示は毎回読み飛ばされる。
実測: この形で 4 か月置いた status の lint は 37 → 187 件に増えた (= 規約を知らない書き手が補足埋め込みの旧形式で
書き続けた)。 ∴ 変更と同じ流れで **(a) 既存分を機械で移す + (b) 新しい違反を書いた瞬間に止める** までを 1 単位にする:

<a id="rule-scoped-by-place"></a>**4 つ目の形 = 規則の対象を「場所」 で書く**。 「この repo には自動で push しない」 のように場所で書いた規則は、 本来守りたい対象 (= 世に出る中身を人が見る / 不可逆な操作を人が決める) を超えて、 その場所の**無関係な整備まで人手に固定する** (規約 file・入口・ライセンスのような、 守る対象でないものの更新が止まる)。 規則は守る対象で書き、 場所で書いてしまったら 対象を絞る文を足す (= 「この規則の対象は生成される中身だけ」)。 絞らずに例外を人の判断に任せると、 毎回同じ問いを人に投げることになる。

- 「YAML (等) を読み書きし直すと書式・コメントが壊れる」 は手作業にする理由にならない — **行単位で書き換え、
  書き換え後の file を読み直して、 entry ごとに「変えた欄以外の全 key が元と同じ」 を照合してから書く**
  (1 件でも合わなければその file は書かない)。 これで書式は保たれ、 意味の変化は機械的に 0 と言える
- 移行の前後で、 その field を読む検査の出力を保存して diff する (= 下流の判定が変わっていないことの証明)
- 意味で対応づけが要る値 (向き・文脈で変わるもの) は移行 script では個別に決め、 恒久の修正道具 (`--fix`) には
  文脈に依らない同義語だけを持たせる (= 道具が勝手に意味を決めない。 直せない値は直さずに報告)
- 件数 0 にしたら lint を **commit 時の停止** に上げる。 表示だけの lint は、 規約を知らない書き手には届かない
- <a id="fix-the-writer-before-bulk-migration"></a>**(a) の一括移行と同じ turn で、 その旧形を書き続けている書き手 (生成 script / template / 規約の例示) を grep して先に直す**。 検出器が同じ形の warning を出し続けているあいだ、 生成側は毎回それを再生産している (実測: ledger の参照形式を一括で正規形に直した直後に、 起票を生成する script が同じ旧形を書く行と、 規約 doc の例示が旧形のまま残っていた = 次の生成で warning が戻る)。 移行 script の old 形を、 `scripts/` と規約 doc の例示に対して 1 回 grep するだけで見つかる

発火面: 散文の規律は §8.12 の最弱層なので、 owner は turn 終了時の hook で最終メッセージの依頼句を検出して 1 回だけ見直させている (日本語の句に依存するので instance は個人層。 導入時の実測 = 直近 120 session・2030 turn の最終メッセージで検出 4・誤検出 0)。

origin: 2026-09-12、 新しい hook を足した直後に「別マシンで installer を 1 回実行」 と書いた。 その installer は既に毎 session 冪等に再走していて、 手順自体が不要だった。 user の返答 = 「次を 1 回実行、 とか覚えてられるわけなくない？」。 同じ session で「次に別マシンを使うとき、 そこの Claude に◯◯と頼めば済む」 とも書いており、 こちらは自動で出る carrier を作ったのが次の turn だった。

### <a id="recovery-state-transition"></a>8.12e 復旧は命令の再実行でなく状態遷移 — healthy な既存 instance を壊して作り直さない

`start` / `open` / `restart` / `retry` という command 名は、望む終状態を表さない。復旧の正本は
「どの命令をもう一度打つか」ではなく、**観測した事前状態から、望む事後状態へどの遷移を選ぶか**である。
特に singleton、profile、session、lock、共有 storage を持つ外部 application では、起動済みの instance は
捨ててよい残骸ではなく、守るべき live state である。

最低限、事前状態を次の 5 つに分ける。単一の probe の失敗を「停止中」へ潰さない。

| 事前状態 | 第一の遷移 | 禁止する短絡 |
|---|---|---|
| absent / stopped | user の許可境界を満たして 1 回だけ launch | 接続 probe の失敗だけで absent と断定 |
| present + healthy | reuse / no-op | 念のため restart、fresh instance を追加 |
| present + transport/control-plane failure | reconnect / transport repair | data-plane の application process を複製して代用 |
| present + wrong context/profile/session | explicit switch / 正しい context を user に選ばせる | 同じ storage を共有する別 instance を force-create |
| unknown / probe failure | 診断を fail-loud にして止まる | unknown を absent 扱いして mutation |

**状態保存の序列**は `reuse/no-op → reconnect → explicit context switch → orderly restart → isolated new instance`。
右へ進むほど既存 state を失うので、左の遷移が不可能だと観測してからだけ進む。真に並列 instance が必要なら、
同じ profile / user-data directory / lock を共有させず、独立 storage と lifecycle を設計する。

起動引数を確実に `main()` へ渡す、profile を指定する、新しい window を出す、といった**正当な局所目的**は、
force-new-instance の十分条件ではない。引数が fresh process にしか届かないなら、(a) stopped 時だけその launch を使う、
(b) running 時は既存 instance の制御面で context を切り替える、(c) 制御面に経路が無ければ user に明示して止まる、
の分岐を持つ。引数を通す都合で事前状態を上書きしてはならない。

retry は同じ状態から同じ副作用を増やさない冪等性と、event ごとの回数上限を持つ。検収は目的機能だけでなく、
**余剰 process / window / tab / crash report / lock / notification が増えていないこと**も state delta で見る。
具体的な診断順序は
[`debugging-discipline.md#recovery-state-dispatch`](../conventions/debugging-discipline.md#recovery-state-dispatch)、
Codex の外部 browser への適用は
[`codex/PARITY.md#external-browser-lifecycle`](../codex/PARITY.md#external-browser-lifecycle) が所有する。
文書を持つ GUI app (Office 等) を script が「reset のために quit / kill」 する場面への適用
(= user の文書を live state として数え、 自分のものだけの時に限って orderly quit) は
[`macos-gui-app-automation.md#ask-before-quit`](../conventions/macos-gui-app-automation.md#ask-before-quit) が所有する。

origin: macOS の外部 browser adapter が、既に live な singleton に対して fresh instance を強制し、
新 process が application 登録中に abort する事例。機構は複数回反復したが 1 製品 family の観察なので、
本節の scope は **singleton / context-bound な外部 application の自動復旧**に限定する。あらゆる relaunch を禁じる根拠ではない。

### <a id="conditional-firing-visibility"></a>8.13 条件付き発火の mechanism は「自分が非活性」 を可視信号にしないと、 沈黙が解釈不能になる

§8.12 は発火面の強弱だった。 本節はその前提条件: **出力の不在は ambiguous** — 「動いて該当なし (= 正常な沈黙)」 と「そもそも動いていない (= 未配線・未登録・未 install)」 を外から区別できない。 per-machine wiring / scheduled task 登録 / opt-in install のように **活性化に手動 step を要する mechanism** は、 その step が抜けても何も言わない (= silent dead) ので、 設計者は「動いている」 と誤認し続ける。

帰結:
- 活性化が conditional / manual な mechanism には、 **「自分は今このマシンで非活性」 を能動 surface する self-check (install-check)** を持たせる。 これが無いと「沈黙 = OK」 と「沈黙 = 死んでいる」 が融合する。
- self-check は既存の毎 session 発火面 (SessionStart hook / dashboard) に相乗りさせ、 該当ホストでのみ・未活性時のみ surface する (= noise ゼロの非対称、 §8.12 reflex の「相乗り」 と接続)。
- これは **heartbeat (= 走った痕跡を残す)** と対: install-check は「配線されているか」、 heartbeat は「配線済が実際に走ったか (no-op 含む)」 を別々に可視化する。 両方無いと「設計したのに死んでいる」 と「配線したのに止まった」 を取りこぼす。

reflex: 自動化を「設計 + SKILL/doc を書いた」 で完了と思った瞬間に「これは活性化に手動 step を要するか? 要するなら、 抜けたことを誰が surface するか?」 を問う。 doc に「新 machine では再登録」 と書くだけ (= recall 依存、 §8.12 最弱面) では再演する。

origin: 朝の自動登録 scheduled task が「設計・SKILL 記述済」 なのに backend 登録 step が一度も実行されず長期 silent dead だった事例 (= 出力の不在を「該当なし」 と誤認、 真因の発覚に user の「自動で動いてないんだっけ?」 を要した)。 同型: 週次自動公開ジョブの machine setup drift (install-check 先行実装) / hook 配線 drift (installer の --check) / **新規 secret の cross-machine 耐久化 step (= canonical への暗号化 commit) が skip され単一マシン地雷化** (= 作成したマシンでは動作確認が通り絶対に不可視、 別マシンで初めて露見。 self-check = 各マシンの secret 配置を耐久性分類して非耐久を surface)。 4 事例からの一般化 (§9.8 充足)。

### <a id="activation-evidence-ladder"></a>8.13a 提案・設定・活性化・実走は別状態 — UI card を activation evidence にしない

条件付き mechanism には少なくとも次の証拠段階がある:

| 段階 | 証拠 | まだ主張できないこと |
|---|---|---|
| proposed | draft / suggestion card / plan が表示された | 登録済・有効 |
| configured | file / prompt / link が存在する | runtime が読む・発火する |
| registered-active | backend/runtime が identifier + active status を返す | 時刻到来時に実走した |
| observed-run | run record / heartbeat / side effect を直接観測した | 次回以降も恒久に健全 |

「カードが出た」「設定を書いた」を「有効化した」と報告すると、§8.13 の silent dead を
success として閉じる。作成直後の完了条件は最低でも **identifier + active status**、運用健全性は
別途 heartbeat / run history で判定する。suggestion しか作れない surface なら「提案済・承認待ち」
と状態名をそのまま報告し、active と言い換えない。逆に active response が取れたなら、同じ目的の
proposal card が一時的に見えても active automation の重複とは数えず、backend/runtime の登録集合を
ground truth にする。

外部への作成・送信では、**操作可能性と対象の存在状態を分ける**。composer / form が開くことは
権限・hold 解除の証拠でしかなく、「まだ投稿されていない」の証拠ではない。conversation memory や
空の composer を receipt の代用にせず、作成前に destination-side search / object identifier / sent
record を確認する。既存 object があれば新規作成せず、更新・返信へ route する。送信後は URL / ID と
read-back 本文を `observed-run` の証拠にする。

origin: timezone anchor を含む automation の immediate create が product validation で拒否され、
`suggested_create` は UI card を描画したが active 登録の証拠を返さなかった。続く native create が
automation identifier + `ACTIVE` を返して初めて登録を確定。同じ段階差は hook trust review、
installer link、scheduled-task backend 登録にも既存観測があり、§8.13 の証拠 ladder として一般化。
外部 action 側の補強は、公開済 topic が存在するのに空の create composer を見て「未投稿・確認待ち」
と誤分類した事例から追加。destination 検索で topic ID を得て初めて状態を訂正した。

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

⚠️ **2026-09-11 注**: 下の「確定事実」 の少なくとも一部は、 作業 root の project-local に入っていた `disableAllHooks: true` による誤診だった ([`conventions/hook-authoring.md#disableallhooks-kill-switch`](../conventions/hook-authoring.md#disableallhooks-kill-switch))。 除去後の desktop では hook 出力が届いた。 本節の枠組み (surface の生存性で配置する) は有効だが、 例として挙げた desktop の性質は前提にせず session ごとに測る。 旧記述 → 確定事実 (= 2026-06-13 実測、 正本 [`conventions/hook-authoring.md §9.3`](../conventions/hook-authoring.md#frontend-dependent-cowork)): **Claude Code desktop app は settings.json hook を「プロセスとして実行」 はするが、 モデルに向かう出力を honor しない** (SessionStart の additionalContext 注入は捨てられ、 PreToolUse の permissionDecision も無効。 副作用 〔file 書込〕 は走る)。 一方 **declarative な `permissions.deny` は honor される**、 ask は非 bypass mode + frontend 自身の承認系を要する (`conventions/claude-code-permissions.md`)。 ⇒ hook ベースの guard は desktop で大半 inert。

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
- <a id="committee-workspace-channel"></a>**委員会の作業場** (= 委員会専用の LMS コース・共有 folder に置かれた議題と記録): 運用の取り決め (数え方・担当の条件など) が規程集にも手引きにも会議資料にも無く、 制度を立ち上げた委員会の初期の記録にだけ書かれていることがある。 全体向けの portal 検索では当たらないので、 その制度を扱う委員会の作業場を別の channel として数える (実測)

後者は構成員全員に同時 distribute されるが「読みに来ない人には届かない」 性質。 person-to-person mail sweep だけで「告知されていない」 と universalize すると、 broadcast channel に actual notice があった場合に大きな失敗 (= 「告知なし」 と argue → 実は portal で N 日前から告知済) を生む。

**reflex**: 「事前告知が無い」 / 「規程に書かれていない」 / 「未連絡」 等を断定する前に、 sweep scope を「Verified scope = ___ / NOT verified = ___」 で明示する。 アクセス経路が機械化されていない channel (= 手動 login portal、 MCP 経路無し) は **「未 verify」 と honest framing して保留**、 内部 portal が institution に存在することが分かっている場合は universal absence を主張せず、 確認手段を user / 他 channel に委ねる。

origin: ある institutional 締切超過の指摘を受け、 person-to-person mail (= Gmail) と 個別 reference PDF (= 配付資料) のみ sweep して「事前告知が見当たらない」 と 2 段で argue した RCA。 実際は institutional broadcast (= 学内 portal 掲示板) に 4 ヶ月前から告知が出ており、 単に sweep scope に portal が入っていなかった (= 共著者から portal URL 指摘で catch)。 [`§8.11`](#downstream-net-intake-leverage) (downstream net は intake で正しく表現された対象しか守れない) の dual: intake の channel category を取りこぼすと downstream sweep がいくら丁寧でも universal absence は嘘になる。

<a id="side-effect-trace-absence"></a>**変種 = 副作用の痕跡の不在から状態を推す**: 「X が起きたなら通知 (mail・ログ・履歴) が残るはず → 残っていない → X は無い」 も single-channel null。 通知は送られない・消される・別の宛先に行くことがある。 状態そのものを直接見られる場所 (端末の設定画面・サービスの一覧) があるなら、 推論より先にそこを 1 回見る (例: 「端末に Google のアカウントを足せば『新しいログイン』 の通知 mail が届くはず、 それが無いから端末にアカウントは無い」 と推さない。 端末の設定でアカウントを足そうとすれば「既に存在します」 で直接分かる、 実測)。

### <a id="broadcast-obligation-blind-spot"></a>8.17 broadcast で届く個人義務 — per-person addressing proxy の構造的 false negative

個人を拘束する義務 (= 受講報告・書類提出・会議出席・投票、 締切付き) は、 個人宛 mail だけでなく **broadcast 形態** (= BCC 一斉配信・ML・宛名「各位」) でも届く。 mail surfacing / triage を **per-person addressing** (= To/Cc の自分一致・本文/件名の名前 mention) を proxy に設計すると、 この class は**構造的に全通貫通する** — 宛名は「各位」 で名前はどこにも現れず、 To は list アドレスだから。 [`§8.8`](#proxy-blind-spot) の proxy 盲点の 1 具体形だが、 盲点が「institution が義務を配る**標準経路**そのもの」 と重なる点で被害が大きい: 初回 + リマインド数通が全て素通りし、 institution 側の escalation (= 業を煮やした個別名指しの催促) が唯一の catch になる = 最後の網が相手の善意。 [`§8.16`](#absence-channel-coverage) が「不在主張」 で broadcast channel を取りこぼす軸なら、 本節は「義務検出」 で broadcast channel を取りこぼす軸 (= 同じ channel category の別 direction)。

観測された failure は 2 層が結合する:
1. **検出層**: broadcast 義務 mail が per-person proxy を貫通 (= 上記)。
2. **intake 層** (= [`§8.11`](#downstream-net-intake-leverage) の instance): 義務をどこかの時点で**認識**していても、 prose (= session 記録・「今週やること」 メモ) に書いただけでは tracked object (= deadline 付き task entry) にならず、 deadline 網は「存在しない fact」 を掴めない。 prose 記載は recall 依存 = 最弱発火面 ([`§8.12`](#firing-surface-hierarchy))。

**対策 pattern** (強い順):
- **同 turn encoding (= 判断規律、 機械化不能な芯)**: 義務を認識した瞬間に tracked object 化する。 「認識して prose に書いた」 は encoding ではない。 後回しにする場合こそ、 先に最低限の tracked entry (= 締切 + 出典) を立ててから後回しする。
- **obligation-signal surfacing (= 機械層、 proxy-subset)**: institutional sender × 義務 keyword (= 「〆」「期限」「要提出」「受講依頼」「リマインド」 等) の組合せで broadcast も surface する層を、 per-person 検出と**独立に**持つ。 これ自体 keyword whitelist (= [`§8.8`](#proxy-blind-spot) の list-based audit) なので盲点を明示し、 「broadcast は全部 catch できている」 と読ませない。
- **リマインド反復を escalation 信号に**: 同 subject の (再) リマインド ≥2 通は「未 discharge 義務」 の高信号 — 個別 mail か broadcast かに関わらず surface を上げる。 institution がリマインドを重ねる行為自体が「あなたの網から漏れている」 という外部観測になっている。
- **同僚の返信数を escalation 信号に (2026-09 追記)**: ML thread で同僚 ≥N 名が返信し自分の送信が 0、 かつ root から数日経過 — これは語彙に一切依らない「あなただけ未 discharge」 の外部観測 (= リマインドの ML 版)。 依頼 class は語彙で閉じない (実測: 各 RCA が自分の事故の語彙を足しても次の依頼は別語彙で来る) ので、 語彙 override の**残余を受ける第 2 の網**として thread 構造を読む検出を別に持つ。 root だけを surface し返信は既知 thread 段に流す (= 返信 20 通を全部 🔴 にすると壁紙化する)。
- **送信者の役職自己紹介を弱い passthrough に**: 「〜@学科主任です」 型の本文冒頭は institutional 義務の送信主体の signal だが FYI も混じる (実測 ~2/3) ので、 🔴 でなく「noise から外して通常行に出す」 中間 tier に置く。 signal の強さに応じて tier を分けないと、 強い tier に全部入れて壁紙化するか、 何も入れず沈黙するかの二択になる。

reflex: mail surfacing / triage 系の検出を設計・評価する時、 「個人義務が broadcast で届く経路」 を test case に含める (= per-person proxy の盲点を設計時に名指しする)。 逆に broadcast mail を noise として suppress する filter を書く時は「この経路で個人拘束の義務も届くか?」 を問う (= 会議招集・受講依頼・投票依頼は ML/BCC で届くのが典型)。

origin: 年次の institutional 義務 (= 受講報告 + 書類提出、 学内締切付き) が BCC 一斉配信 (宛名「各位」) で初回 + リマインド 2 通の計 3 通届いたが、 name-mention surfacing を 3 通とも構造的に貫通。 4 通目 (= 個別名指しの Fwd 催促) で初めて surface し、 その時点で締切を 1.5 ヶ月超過。 しかも初回の 1 週間後に義務自体は認識され session 記録の prose に「今週の事務 N 件」 として書かれていたが、 tracked object 化されず deadline 網から不可視のまま (= 検出層と intake 層の複合failure)。 sibling 観測: 役員 ML の会議招集 3 通が ML bracket noise filter で suppress され会議欠席 (2026-06) / 学内 ML の会議通知が同型 filter で不検出 → filter 緩和 (2026-06)。 3+ 観察からの一般化 ([`§9.8`](#single-observation-scope-check) 充足)。 instance (= 検出器実装・sender 具体値) は個人層に残置 (= kernel-up / instance-down)。

### <a id="request-mail-two-date-axes"></a>8.18 依頼 mail の二日付軸 — event 日を urgency の proxy にすると行動〆切が落ちる

依頼 mail はしばしば **2 つの日付軸**を運ぶ: (1) **event 日** (= 会議・開催・実施日) と (2) **行動〆切** (= 出欠入力・登録・提出の期限)。 検出器・reminder・push gate を event 日軸に keying する (= 「event が今日・明日なら通知」) と、 行動〆切が **event 日より手前に来る**依頼類 (= 日程調整・RSVP・登録窓口) で通知が構造的に間に合わない — 〆切当日、 event はまだ「数日先」 で gate は静かに閉じたまま。 さらに **日程調整型** (= 候補日提示・開催日未確定) では event 軸そのものが未定義なので、 行動〆切だけが検出可能な軸になる。 [`§8.8`](#proxy-blind-spot) の proxy 盲点の日付版 (= event 日近接を urgency の proxy にした) であり、 [`§8.17`](#broadcast-obligation-blind-spot) の宛先軸とは独立 (= 1:1 mail でも起きる)。

reflex: 日付を扱う surfacing / reminder を設計・評価する時、 「この mail の actionable な日付はどれか — event 日か、 その手前の行動〆切か」 を分離して問い、 gate は**行動〆切軸に (も)** keying する。 締切文脈 (「までに」 等) の日付を「アポでない」 として捨てる filter を書く時は、 捨てた先に受け手が実在するかを [`§8.11 変種`](#receiverless-handoff) として verify する。

origin: 会議日程調整の broadcast 依頼 (候補日 2 つ + 入力〆切が中 1 日) で、 検出器は候補日 (event 軸) を正しく抽出しながら入力〆切の日付を「期限 = 別 mechanism の領分」 として除外し、 push gate も event 日近接のみ → 〆切は event の 2 日前に silent 超過 (週末 + 祝日と重なり human catch も無し)。 sibling 観測 (同年 7 月): 候補日未確定型の日程調整 mail が「具体日時のあるアポ」 検出の圏外に落ち、 user の直接質問だけが catch。 2 観察 ([`§9.8`](#single-observation-scope-check) の 2+ bar 充足)。 instance (= 検出器の入力〆切 class 実装) は個人層に残置。

### <a id="retrieval-key-choice"></a>8.19 retrieval の null は「対象が無い」 でなく「key が悪い」 を先に疑う — 人間可読な属性は経路で失われ、 案件 ID は残る

ある記録を探して見つからなかったとき、 「存在しない」 と結論する前に **query の key 選択**を疑う規律。 (探し物でなく「失効」「対応不要」 という結論の前に同じ key 選択を当てる版 = [§8.57](#lapse-claim-is-absence-claim)) [`§8.16`](#absence-channel-coverage) が「見た channel が足りない」 (= channel 軸)、 [`§8.14`](#single-field-identity-corroboration) が「一致させた field が足りない」 (= identity 軸) なのに対し、 本節は **正しい channel を正しく見ていても引き方だけで null になる** (= key 軸)。

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

**検出器の「既知」 判定にも同じ key の問題がある**: 送り手が毎回 新しいスレッドで送る通知 (審査結果・受付・督促) は、 thread ID で「待っている返事か」「記録済みか」 を判定する網を原理的にすり抜ける。 待ちは **送り手と件名の検索条件** で、 決着済み案件への督促は **本文の案件 ID** で判定する ([`email-surface-pattern.md#new-thread-expected-inbound`](../conventions/email-surface-pattern.md#new-thread-expected-inbound) / [`#settled-matter-key`](../conventions/email-surface-pattern.md#settled-matter-key))。

origin: ある論文の過去の査読所見を「メールに残っていない」 と報告した RCA。 誌名・送信者・添付の有無・直近時間窓で引いて null → 実際は**原稿管理 ID 単独で引けば全 round が残っていた** (= 最終報は本文のみで添付なし / 転送の件名に誌名が一度も出てこない / 発端は時間窓の外)。 sibling 観測: 同じ運用の連絡先取得手順に、 mask された公開ページを見て「取得できない」 と結論したが一次資料 (= 論文 PDF) には在った失敗例が既に記録されていた (= source 選択の同型)。 2 観察 ([`§9.8`](#single-observation-scope-check) の 2+ bar 充足)。 なお本節は「引き方」 の話で、 [`§8.11`](#downstream-net-intake-leverage) (= intake で表現されていない対象は下流で守れない) とは独立 — ID で引けたのは、 対象が最初から正しく記録されていたから。

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

origin: 官製様式の提出物を、 直前に窓口を通っていた提出物を base にして作ると、 base に含まれていた誤りをそのまま踏襲する (= 本人記入欄でない欄への記入 / 提出時に消す指定の記入要領の残置)。 base 側も同じ誤りのまま受理されていたので、 「前回問題なかった」 が誤りを通した。 規約は**両方とも既に存在していた** (= [`§3`](#rule-addition-criteria) の「規約がない」 でなく「規約を読まない」 側)。 対策として全セルの状態と根拠を宣言する spec + 生成 driver 冒頭の照合 gate を導入し、 訂正前の提出物を再現して全件検出することを確認した。

---

### <a id="noise-obligation-signal-sharing"></a>8.21 noise 抑制の識別 signal を義務 mail が共有する — bucket 混在には obligation-class override

noise 抑制 rule は **identity signal** (= sender domain / ML bracket / mail category) に key する。 低頻度の義務 mail が高 volume の noise とその signal を**共有**するとき (= 同一 domain から勧誘 spam と依頼が両方来る、 同一 ML bracket で案内と召集が両方来る)、 signal 単位の suppress は義務を silent drop する。 [`§8.17`](#broadcast-obligation-blind-spot) が**宛先軸の false negative** (= broadcast が per-person 検出を貫通) なのに対し、 本節は**抑制軸の false positive** (= noise filter が義務を積極的に殺す)。 [`§8.8`](#proxy-blind-spot) の 1 具体形。

**なぜ登録時に見落とすのか**: 抑制 entry を足す burn-down は「surface 件数を減らす」 が目標関数で、 sample された着信の**多数派** (= spam) だけを見て domain を分類する。 base rate が高い noise に低頻度の義務が混在する分布では、 観測の多数決は常に「noise domain」 と結論する — 義務側は登録の瞬間に問わなければ永遠に問われない。 最悪形は「義務を surface するために作った機構の tuning で、 hit してきた義務 mail を noise 側に登録して黙らせる」 (= 検出器の感度向上が抑制 list の肥大で相殺され、 しかも登録は『チューニング完了』 として成功に見える)。

**対策 pattern**:
- **登録時 gate (= 判断規律)**: noise entry を足す瞬間に「この signal を共有する義務 mail は何か?」 を 1 問挟む。 義務密度が高い sender class (= editorial office / 事務局 / 委員会 system) はそもそも登録しない。
- **obligation-class override (= 機械層)**: 義務 lifecycle の class pattern (= 依頼・督促・accept/decline 要求・取消) を、 抑制の**全軸より優先**して貫通させる例外レイヤーとして持つ (= allowlist-over-blocklist)。 抑制 entry の増減と独立に義務が守られる。
- **記録付き opt-out (= 例外の例外)**: 「義務 class だが既定 decline とする」 sender は、 抑制 list へ戻すのでなく override 側の**明示 opt-out** に置く (= 判断の日付・理由を併記)。 silent な再 suppress と、 監査可能な意思決定を区別する。
- **定期棚卸し (= meta-detector、 2026-09-01 追記)**: override の語彙・sender は**列挙で収束しない** (= 同一発信主体の文面変種にすら追随できない実測)。 残余は「suppress を正しくする」 でなく「**suppress の誤りを定期検出する側の網**」 で受ける — suppress 済 ∧ 未認識 ∧ 高 stakes 語彙 (依頼/期限/必須化/urgent 等の recall 優先の粗い網) を月次で列挙し人間が walk する。 実測で 2 回連続の生きた真陽性 (= 審査督促の変種 / 別 domain の必須化督促と失効型 2 件)。 発火は state file を持たない月初 N 日 gate が簡潔で、 数日の反復表示は壁紙化でなく消費補助 (= 月 1 回きり表示だと無人 runner が人間に届かないまま消費する事故がある)。 **棚卸し finding の消費規律**: scope 外 domain の高 stakes 行も同 turn で本文 1 読 + 影響・期限 1 行評価 + clock つき carrier 起票までが棚卸し — 「1 行 report で手放す」 は [`§8.24`](#surfaced-not-consumed) の audit 版 (= 本 doc §8.21 domain 軸の origin incident はまさにこの手放しで 2 段の偶然に依存した)。

reflex: noise blocklist / 抑制 filter に entry を足す瞬間に「この signal から義務も届くか?」 を問う。 ⚠️ この gate は flow にしか効かない — 原則を hoist した turn で既存 entry を 1 周する ([`§8.31`](#principle-birth-stock-audit))。 root-only / per-account の語彙 override と、 語彙に依らない構造 signal (= 同僚の返信数、 送信者の役職自己紹介) を併用すると、 語彙列挙が収束しない残余を受けられる (2026-09 追記)。 義務 mail の miss を RCA するとき、 検出器の感度でなく**抑制 list との交差**を第一容疑にする (= 同型 incident の axis が bracket / domain / category と違っても generator は同一)。

origin: 出版社 domain の noise 登録 (= 出版勧誘 spam が着信の大半) が、 同じ domain から来る依頼と督促まで全 surface 段で suppress していた RCA。 retroactive sweep で同型が他にも見つかり、 抑制 entry の一部は「義務を surface する名指し検出を tuning した同じ commit」 で登録されていた。 [`§8.17`](#broadcast-obligation-blind-spot) origin の sibling 観測と合わせ、 axis と detector が違っても generator が同一 ([`§9.8`](#single-observation-scope-check) 充足)。 instance (= override 実装・pattern / sender 具体値) は個人層 config に残置 (= kernel-up / instance-down)。 domain 別 instantiation (査読依頼) = [`peer-review-workflow.md#invitation-intake`](../conventions/peer-review-workflow.md#invitation-intake)。

**domain 軸 (追記 2026-09-01)**: 抑制の各軸 (sender / bracket / category / 語彙) を正しく設計しても、 **網がどの domain を張っているか**が未宣言だと死角は残る — 監視系の死角は「検出器の穴」 より先に「そもそも張っていない domain」 に開き、 未宣言の死角は発見が偶然 (= 別調査の副産物への写り込み・human-steering) に 100% 依存する。 実例: 業務義務用に設計された mail surface 網の scope 外で、 金融口座のセキュリティ設定必須化督促 16 通 (週次 3 ヶ月) が category suppress で全通埋没し、 口座の機能制限 2 ヶ月を誰も知らなかった (実害なしは口座が空だった僥倖。 なお金融機関の mail は宛名が username mask で氏名 token を含まず、 名指し検出はこの domain で原理的に無力 — class 語彙が唯一の識別面という副発見つき)。 対策: 網を持つ system は**カバー domain と declared-out domain を config 自身に宣言**し、 scope 外 domain には (a) 網を張る / (b) 別 system に carrier を接続 / (c) 明示 declared out のいずれかを選んで書く。 最悪の状態は「宣言なき網羅感」 = 網が在ること自体が scope 外 domain への安心感まで生む。 audit・RCA の副産物として scope 外 domain の高 stakes finding が出たときは、 「scope 外」 を理由に未読で手放さない — 同 turn で本文 1 読 + 影響・期限の 1 行評価 + clock つき carrier 起票までがその finding の消費 (= 手放しは [`§8.24`](#surfaced-not-consumed) の audit 版)。

### <a id="lapsing-deadline"></a>8.22 失効型期限 — 超過が「遅れ」でなく「義務の消滅」になる deadline class

期限には 2 class ある。 **通常の期限**は超過後も挽回できる (= 遅れて出す・詫びる・延長を頼む — 損失は連続的に増える)。 **失効型期限** (lapsing deadline) は超過の瞬間に義務・機会そのものが不可逆に消える — 依頼の自動取消・役割の解任・応募窓の閉鎖・権利の失効。 損失が階段関数なので、 期限管理の設計要件が通常の期限と質的に違う:

- **重要度と失効性は独立軸**: triage を優先度 (importance) proxy で行うと「重要度 中 × 失効型」 が件数 summary に畳まれて named visibility を失う ([`§8.8`](#proxy-blind-spot) の deadline 版 — 失効性は優先度から導出できない)。 ∴ intake の時点で失効性を**第一級属性として明示的に encode** する ([`§8.11`](#downstream-net-intake-leverage) — intake で表現されない属性は下流の網が守れない)。
- **発火は期限前でなければ価値がほぼゼロ**: 通常の期限では「超過に気づく」 安全網にも挽回価値があるが、 失効型は超過に気づいても義務が戻らない。 surfacing は期限**前**に、 優先度・件数 cap と独立の named 表示で出す。
- **超過直後の救出窓**: 失効が即時でない運用 (= 相手方がまだ再割当していない・取消に猶予がある) では、 超過直後の短い窓に限り挽回可能性が残る — 超過側も「過ぎたから畳む」 でなく、 救出窓の間は surface を続ける。
- **失効が確定したら incident**: 「取り消されたから対応不要」 で流さない — どの経路・filter で期限前 signal が落ちたかを RCA してから閉じる ([`§8.21`](#noise-obligation-signal-sharing) の抑制交差が第一容疑)。

domain 別 instantiation (査読依頼 = 依頼→数日で自動取消・解任) = [`peer-review-workflow.md#invitation-intake`](../conventions/peer-review-workflow.md#invitation-intake)。 機械 semantics (= marker field・cap 除外表示・救出窓の実装) は個人層 tooling に残置 (= kernel-up / instance-down)。

origin: 研究 platform への招待 (返答期限つき) が priority 中で件数 summary に畳まれ、 日単位で埋もれた RCA (= 失効型 marker + cap 除外 + 救出窓を個人層で tooling 化した契機)。 sibling 観測: 期限つきの依頼が応答期限内に人間に届かず自動取消 (= [`§8.21`](#noise-obligation-signal-sharing) origin と同 incident の deadline 軸)。 2 観察 ([`§9.8`](#single-observation-scope-check) 充足)。 2026-08-18 に個人層 home から本節へ昇格 (= 層 1 doc が層 3 home を参照できない registry 制約の解消)。

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

origin: 地域研究会の案内 (= 初報 + 複数のリマインド、 BCC「各位」、 参加登録・発表申込の段階〆切つき) が数か月・全通不可視のまま発表申込〆切が silent 失効。 名指し網 (宛先圏外) / 義務網 (義務でない) / 〆切抽出器 (締切語前置 + 早期告知で horizon 外) / 未認識 backlog 段 (rolling 窓で walk 前に silent 退場) の 4 経路が**独立に**落ち、 最終 catch は主催者の最後のリマインド (〆切直前) だった。 本 class 直接観察は 1 + 隣接 class sibling 2 (= [`§8.17`](#broadcast-obligation-blind-spot) 義務 broadcast 1.5 ヶ月 / [`§8.22`](#lapsing-deadline) 期限つき依頼の自動取消) — [`§9.8`](#single-observation-scope-check) は隣接 class 複数観察で充足と判断、 本 class 単独の再発で強化する。 instance (= ledger repo 名・triage 段の具体 arm・検出器実装) は個人層に残置 (= kernel-up / instance-down)。

### <a id="surfaced-not-consumed"></a>8.24 surface されても消費されない — silent 再表示の壁紙化と disposition 終端

[`§8.22`](#lapsing-deadline) は「失効型は期限**前**に named 表示せよ」 と要求するが、 named 表示は**十分条件ではない**。 毎 session 同じ行を silent に再表示する surfacing は、 数週間で**壁紙化**する (= 読者の脳が風景として filter する — alarm fatigue の表示版)。 壁紙化は 3 つの増幅因子で加速する:

1. **隣接遮蔽**: 同種の named crisis が隣の行で actively 進行中だと、 「その分野は今まさに全力でやっている」 という感覚が同〆切の sibling 行を飲み込む (= 表示は見えているのに認知が届かない)。
2. **表示文言の子守唄**: surface される item 自身の注記に「たぶん不要」 系の priming (= 「見送りの公算が高い」 等) が書いてあると、 全読者が毎回それを読んで次の危機へ移る。 安価な discharge 手 (= 1 問で決着する) が重い動詞 (= 「着手」) の下に埋もれていると特に致命的。
3. **判断〆切と行動〆切の同値化**: 「やるか判断する」 系 item の deadline を行動の〆切と同じ日に置くと、 表示が最高強度に達した時にはもう「やる」 選択肢が実行不能になっている (= 判断 deadline は行動 lead time 分だけ手前に置く。 [`§8.18`](#request-mail-two-date-axes) の判断版)。

対策 kernel: **surface は silent 再表示で循環させず、 明示 disposition で終端させる** — 失効が近い item は「act / 明示 defer / 明示 decline のどれかが記録されるまで surface を降格させない」 段に昇格させる (= 稼働実績のある同型 = mail triage の「未認識段が空になるまで準備完了としない」 規律)。 最終盤 (= 残数日) は**表示 channel 自体を変える** (= agent の session 注意経路から人間への直接通知へ) — 同じ channel の強度 escalation は壁紙化の続きでしかない。

reflex: surfacing 機構を設計・監査するとき「この表示は**何をもって消えるのか**」 を 1 行問う。 答えが「期限が過ぎたら」 なら、 それは通知ではなく風景である。

消費側の最小単位 = [§8.48](#mention-implies-triage) (自分が言及した item はその turn で終える)。 そもそも日付 detector に乗らない class = [§8.47](#deadline-in-the-referent)。 経過日数の印が期限の短い義務で逆向きになる件 = [§8.55](#elapsed-time-urgency-inversion)、 表示を読む agent と義務を負う人のずれ (配達・伝達・量) = [§8.56](#surface-reader-is-not-the-owner)。

対策を実装に落とすときの 2 つの追加 kernel (= 2026-08、 上記 RCA の対策実装で確定):

- **defer は期限付きでなければ mute である**: 「明示 defer」 branch を無期限 flag で実装すると、 それは disposition ではなく恒久消音 spigot になり、 壁紙化と同じ病気を defer 側で再生産する。 defer record は**必ず期日を運び、 期日経過で自動失効して loud 側に復帰**させる (= 永久 mute を構造的に不能にする)。 parse できない defer record も loud 側に倒す。
- **通知 channel の dedup には 2 class あり、 互いの代替にならない**: (a) 「新規 / 昇格時のみ 1 回」 dedup は速報 channel — 既知のまま放置された item を**構造的に再通知しない**ので、 壁紙化した item には最初から届かない。 (b) 最終盤 channel は「窓内は 1 日 1 回/item 再通知」 class が必要。 (a) の channel が既に稼働していることは (b) の不在を埋めない — 「通知機構はもうある」 という監査結論は、 **その dedup がどちらの class か**を確認するまで下せない。
- **通知 job の実行 locus は受け手で決める**: 人間への local OS 通知は、共有 state を更新する singleton job と違って、**通知を受ける各端末**で動かなければ配信にならない。active-host gate の背後に置くと standby 端末では正しく defer している顔のまま人間への channel が消える。一般の配備・検証契約は [`scheduled-tasks.md#per-recipient-notification-locus`](../conventions/scheduled-tasks.md#per-recipient-notification-locus)。

origin: 期限つきの判断 TODO が 2 つの独立 surface 経路で 30 日間毎日 named 表示 (最終週は最高強度 + 実働中の同〆切案件の 1 行隣) されながら一度も消費されず期限を通過した RCA (= 機械 replay で表示履歴を verify 済)。 同月 sibling = 別の期限つき依頼が名指し horizon に 6 日 named 表示のまま未消費で自動取消 ([`§8.22`](#lapsing-deadline) origin の consumption 軸)。 対照の成功例 = 明示 disposition を要求する mail triage 段は同環境で機能し続けている。 [`§9.8`](#single-observation-scope-check) は同月 2 観察 + 対照 1 で充足。 instance (= 検出器名・ack field 実装・対策 ledger) は個人層に残置 (= kernel-up / instance-down)。

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

### <a id="user-execution-handoff"></a>8.27 user-execution handoff — 最終 leg が人間本人にしかできない義務は「手渡しの機構」を要する

**class 定義**: 義務の最終 step が人間本人にしか実行できない class がある — 認証 web form の提出、 パスワード設定、 本人 login、 署名・押印。 agent はこの class で「自分は代行できない」 を**責任系列の終端** (responsibility sink) として扱いやすい: 「残 = 本人操作」 と記録した時点で仕事が済んだ気配になり、 以後は誰の queue にも載らない。 しかもこの step は価値が 100% 本人・第三者に行き agent のループに何も返さない ([`§4.1`](#motivated-substitution-trap) verification family の user-leg 変種) ため、 相手の催促も硬い期限も無いと**系統的に壁紙化する** ([`§8.24`](#surfaced-not-consumed))。 実測では同 class の成功例と失敗例は綺麗に分かれ、 分水嶺は (α) 相手の active な待ち or 失効型期限の存在 (β) packet の即時実行可能性 — つまり**本人の resistance ではなく carrier の不在**が死因。

**kernel — 手渡しは 4 段の機構である** (どの段も recall に置かない):

1. **readiness 検出**: blocking input (レビュー返信・素材・承認) が届いた**同 turn** で「実行可能」 へ状態遷移させる (= same-turn conversion family: 会議確定→calendar 登録と同型)。 この 1 bit の未記録が下流の全判断を汚染する (= 記録上「まだ待ち」 に見える案件は、 どんな丁寧な棚卸しでも誤処分される)。
2. **packet 組み立て**: 提示物は「本人がそのまま実行できる 1 行」 (= 動詞 + URL + 完成済み素材 + 所要分数)。 「残 = form 記入」 は packet ではない ([`§8.24`](#surfaced-not-consumed) 増幅因子 2 = 安価な discharge 手を重い動詞の下に埋めるな)。 packet 内の URL・座標は一次資料で verify してから書く (= 推測 URL は手渡しの瞬間に壊れる)。
3. **提示 channel**: 本人操作は本人在席時に届く必要がある — agent session 向け表示だけでは、 session を開かない期間・読まない row で落ちる。 滞留した本人操作 item は forced-disposition 段 (= act / 期日つき defer / 明示 decline を記録するまで降格しない) + 人間直行 channel (OS 通知等) に載せ、 通知 cadence は 2 class ([`§8.24`](#surfaced-not-consumed) 追加 kernel) — 期限窓内は毎日、 恒常滞留は週次 (= 恒久 daily は通知 channel 側の壁紙化)。
4. **「代行不可」 の記載規律**: 代行不可と書くには (a) probe 証拠 (= どの経路を・いつ試し・どの層で拒否されたか。 能力の不在主張は検証してから — [`§8.16`](#absence-channel-coverage) の capability 版) と (b) packet の併記を必須にする。 probe すると「不可」 の層は分解される (= platform の domain policy / 認証 / 権限 prompt — SSO だから不可、 のような class 主張はしばしば誤り)。 そして代行可否は crux ではない — 不可逆な外部提出はどのみち本人確認 gate を通るのだから、 **勝負は常に packet と提示にある**。

**close は網も外す**: 追跡 record (open TODO 等) を閉じると、 open-record を走査する全検出器の射程からその案件が同時に消える — 不完全な picture に基づく close は、 **picture を訂正できたはずの機構を自分で切断する**。 対人 loose end (未消化の相手返信・未達の deliverable) を残す close の前に「この close で死ぬ網は何か」 を 1 行問い、 escape hatch を「相手が再連絡したら reopen」 型 (= inbound 依存 = 自分側の網ゼロ) にせず、 期日つき watch record (= 公開日・発火日を anchor に) を残す。 検出器側にも対を置ける: 直近 close した record の loose end を一定窓だけ見張る close-hygiene 検査。

**委任は「見える不作為」 を cover しない**: 包括委任 (「進めておいて」) の下でも、 **不在が第三者に見える形で顕在化する義務** (公開リストに載らない・レビューまで投資した協力者が結果を見る) の見送りは外部発信級の act — 見送り前に named 確認 1 行 (「X を見送ります — Y さんがレビュー済みですが良いですか」) を要する。 判断時の警戒 2 点: (i) **催促強度は stakes の proxy ではない** (= 催促ゼロ = 低 stakes は [`§8.8`](#proxy-blind-spot) の disposition 版。 静かに自分の分を済ませた協力者ほど期待が確定済みで、 二度催促する人ほど目立つ — squeaky-wheel gradient)。 (ii) 見送り判断の前に後ろ向き 3 検査 (誰の期待を破るか / 自分の約束文が thread に無いか / 原依頼文書に可視化イベントが無いか) — いずれも記録から 1 手で読めるのに、 前向き検査 (催促が来ているか) だけで代替されやすい。

origin: 授業評価フィードバックの deep RCA。 draft 起草 + 共担者の朱入れレビューまで完了した提出義務が、 レビュー返信の未記録 (kernel 1 欠落) → SSO form への「代行不可」 記載を終端に carrier 消失 (kernel 2-4 欠落) → 包括委任下で「低 stakes・催促なし」 と見送り close (= 依頼文書には全学公開が明記、 close が thread 監視も切断) → 66 日後に公開リストの不在を共担者が指摘して顕在化。 同 class の生存 sibling 2 件 (学術誌共著者の PW 設定 38 日滞留 / 機関業績調査 8 日超過) + 隣接 (審査依頼の web 回答失効) で [`§9.8`](#single-observation-scope-check) 充足 (close-kills-net は部分納品 close の二重不可視事故 〔2026-06〕 と 2 例)。 instance (= marker field 名・gate/lint script・cadence 実装・checklist 原文) は個人層に残置 (= kernel-up / instance-down)。

### <a id="confirmation-question-aim"></a>8.28 確認設問は照準した軸しか検証しない — 事実主張を運ぶ文の user 確認は真偽を第一問に

**class 定義**: user 確認 (確認 marker・draft OK・(a)/(b) 選択肢) を検証面として設計する時、 **設問は照準した軸しか検証しない**。 事実主張を含む文に「書き方」 の選択肢だけ (このまま / 匿名化 / 軟化) を出すと、 主張の真偽は両選択肢の共通前提に埋め込まれて user の目を素通りする — user は提示された決定空間の中で決める (frame acceptance)。 これは [`§8.8`](#proxy-blind-spot) の確認面版: 「user 確認を経由した」 という proxy が「主張は検証された」 の証拠として振る舞い、 postmortem でも「検証面はあった」 と読めてしまう分、 検証面ゼロより診断しにくい。

**kernel**:

1. **事実主張 (帰属・固有名・数値・優先権) を運ぶ文の確認は、 真偽 evidence を第一問に置く**: 「この主張の根拠 = X (verify 済 / 未検証)」 を選択肢より先に提示する。 未検証の主張に style 選択肢を出す資格はない — 先に検証するか、 主張ごと落とす。
2. **選択肢を書く瞬間の self-check**: 「(a) と (b) のどちらを選んでも残る前提は何か」 — その共通前提こそ、 この確認が本来検証すべきだったものである可能性が高い。
3. **draft 提示 + user OK は事実検証に対して null protection** (mail domain で確立済みの rule の一般形)。 user は文面の質・トーン・戦略を見る — 埋め込まれた事実の再導出はしない。 確認を「検証済み」 に数えられるのは、 設問がその軸を明示的に向いていた時だけ。

**origin**: ある提出文書。 生成時に混入した誤帰属 (= グループ内略称の著名研究者名への衝突展開、 [actor-attribution.md #claim-target-attribution](../conventions/actor-attribution.md#claim-target-attribution)) を運ぶ文に、 user 確認 marker が「名指しのまま (a) / 匿名化 (b)」 の趣味だけを問い、 帰属の真偽は前提として素通りして提出に至った。 同じ marker 表の 2 行上には当の略称の正式名を問う設問があり user 回答も得ていた (= 衝突解消 data は同一 session 内に存在) が、 設問が真偽を向いていないため誰も接続しなかった。 marker の括弧書きは「名指しされた当人が審査員にいる確率」 まで評価していた — **P(読まれる) を評価して P(真) を評価しない、 照準ずれの純型**。

### <a id="generation-error-trigger-gap"></a>8.29 操作を trigger にする gate は、操作を伴わない生成 error を素通しする

**class 定義**: 検証 reflex・nudge・hook の多くは**操作** (外部 search の null、 tool の fail、 特定 file の Read/Edit) を発火 trigger にする。 しかし**自分がいま生成している文の中の誤り** (未検証の固有名・数値・帰属が流暢に埋まる confabulation class) には対応する操作イベントが無い — 生成は lookup ではないから null も fail も出ない。 結果、 操作 trigger の gate 網がどれだけ厚くても、 生成時混入は構造的に素通しする ([`§8.8`](#proxy-blind-spot) の生成版: gate の proxy = 操作イベント、 その盲点 = 無操作の error)。

**Reflex (gate 設計時):** 生成 error class を受け持つ gate は、 trigger を操作でなく**内容**に張る — (a) 成果物 text への pattern 検査 (例: 名指し × 誤り語彙の共起 regex を提出前 audit で回す)、 (b) 提出・送信という **stage boundary** での一括 audit (= 操作 trigger が無くても必ず通過する点)、 (c) 規律 wording は「書いた瞬間 = gate」 と生成の瞬間そのものに焼く (機械化不能な残余、 [`§8.12`](#firing-surface-hierarchy) の最弱面であることを承知で置く)。 生成物の fluency は provenance の証拠にならない — retrieval 由来と生成由来は書いている本人にも区別が付かない、 が設計の前提。

origin: ある提出文書の名指し誤帰属 RCA (= [`actor-attribution.md#claim-target-attribution`](../conventions/actor-attribution.md#claim-target-attribution))。 検証 reflex 群 (外部 null・mail 事実・PDF read) は全て操作 trigger で、 生成された固有名はどの reflex の射程にも入らず提出まで素通しした。 対策の機械面 = (a)(b) 型の提出前 named-claim audit。

### <a id="expected-inbound-tripwire"></a>8.30 予告された inbound 依頼には時計を — 「来るはず」 は tracked object になるまで網に乗らない

会議資料・学年暦・前年の ledger は、 **依頼が来る前に「M 月に X の依頼が来る」 と教えてくれる**ことがある。 この予告は義務そのものではないが、 義務の**到着を検知する最後の網**になり得る — 依頼 mail が検出網を素通りしても (= [`§8.17`](#broadcast-obligation-blind-spot) / [`§8.21`](#noise-obligation-signal-sharing))、 「来ているはずなのに見ていない」 を問う時計があれば拾える。 逆に予告を prose (= 会議資料の summary、 session 記録) に書くだけでは、 deadline 網は open な tracked object しか読まないので、 予告は書いた瞬間に死ぬ ([`§8.11`](#downstream-net-intake-leverage) の instance)。

**pattern**: 予告を認識した turn で、 `status: 待ち` + `deadline: 予測到着日 + slack` + task「未着なら送信元 ML / sender を grep」 の tracked entry を立てる (= **expected-inbound tripwire**)。 依頼が実際に届いたらその entry を本物の義務 entry に変換する (= 二重にならない)。 年次の依頼は前年の完了時に翌年 entry を機械生成する (= yearly-recurring template) と、 予告を読む必要すらなくなる。

reflex: 「〜が来る予定」「〜月に依頼あり」 を summary に書いた瞬間に「この予告に時計はあるか」 を問う。 [`multi-session-coordination.md #green-light-carrier`](../conventions/multi-session-coordination.md#green-light-carrier) (= 時計も owner も無い queue は拾われない) の inbound 版。

origin: 7 月の会議資料に「翌年度の授業計画案 = 10 月〆、 7 月中に依頼が来る」 と正しく summary したが tracked entry を立てず、 8 月に届いた依頼は ML noise filter に沈み、 23 日後に user の記憶で発覚。 予告は 3 週間前から手元にあった。

### <a id="principle-birth-stock-audit"></a>8.31 原則が生まれた turn で既存 config を棚卸しする — 登録時 gate は flow にしか効かない

「entry を足す瞬間に X を問う」 型の判断規律 (= 登録時 gate、 [`§8.21`](#noise-obligation-signal-sharing) の第 1 対策) は、 **原則が生まれた後の flow** にしか効かない。 原則より前に登録された stock (= 数十〜数百の既存 entry) は、 原則の存在を知らずに登録されたまま、 原則が禁じる状態で生き続ける。 原則を書いた session は「これで防げる」 と感じるが、 事故の generator は stock 側にあることが多い。

**pattern**: 新しい判断規律を hoist する turn で、 その規律を既存 stock に**1 周適用**する (= 「この既存 entry は新規なら登録を許すか」 を全 entry に問う)。 stock が大きければ機械で候補を列挙し (= 例: 抑制 entry ごとに「この signal から義務 mail が来た実績」 を過去 N 日の受信で計測)、 finding は同 turn で修正するか carrier を残す。 棚卸し済みの印を stock 側に残す (= 監査日)。

reflex: 原則の origin 節を書き終えた瞬間に「この原則で今の config を通したら何件 flag されるか」 を実測する。 0 件でないなら、 原則の本文より先にその件数を直す。

origin: noise 抑制と義務 mail の signal 共有 ([`§8.21`](#noise-obligation-signal-sharing)) を 8 月に hoist した後も、 5 月に登録済みの学科・専攻 ML の bracket 抑制 (= 職務上いちばん義務密度の高い経路) は再監査されず、 9 月に同 generator で 3 件 (うち 1 件は〆切超過) を落とした。 hoist 時に既存 63 pattern を 1 周していれば、 その場で flag された entry だった。

### <a id="rca-as-labeling"></a>8.32 「〜型」 と分類した瞬間が機械層を足す最安の瞬間 — label は対処ではない

事故を既知 principle の instance だと**正しく分類**できた時、 その turn は「型が分かった = 対処済み」 と感じやすい。 だが分類は認識であって変更ではない。 principle 側には既に対策 pattern (= 機械層 / carrier) が書いてあり、 instance を認識した turn はそれを**適用する最も安い瞬間** (= 文脈が全部手元にある) なのに、 label を書いて次の作業に移ると、 同じ generator が次の instance を作る。

**pattern**: 記録 (inbox / incident / SESSION) に「〜型 (= 既知 principle の instance)」 と書く turn は、 同じ turn で (a) principle の機械対策を当該 config に適用する、 または (b) 適用の carrier (= 期限つき task) を残す、 のどちらかを**併記しないと書けない**とする (= label 単独を禁じる)。 「(a)(b) いずれも不要」 と判断するなら、 その理由を label の隣に書く。

reflex: 「〜型」「同型」「blind-spot 型」 と打った瞬間に、 手が config / script / TODO に伸びているかを見る。 伸びていなければ label は未完成。

双対 = [#false-positive-declaration-needs-control](#false-positive-declaration-needs-control)。 「〜型」 が**対策を足す最安の瞬間**なら、「偽陽性」 は**検査を殺す最安の瞬間**である。

origin: 7 月に ML 経由の依頼を 9 日遅れで遡及 triage し「broadcast-obligation blind-spot 型」 と正しく分類した記録が、 filter も carrier も変えずに終わり、 翌月の同 ML で 23 日の見落としを生んだ。 分類は合っていた。

### <a id="protocol-cheapest-action-coverage"></a>8.33 新しい protocol は最頻・低 stakes の行為を protocol 内で最安にする — 迂回路は初日に現れる

厳しい protocol (= 状態遷移を検証し、 不正な遷移を拒否する) を導入すると、 参加者は**最も頻繁で最も軽い行為**から試す。 その行為が protocol 内に無い、 または protocol 外の旧経路より高いと、 初日に旧経路へ迂回され、 以後は「protocol は重い」 という学習だけが残る。 迂回路が開いた瞬間に、 検証する遷移も迂回される。

**pattern**: protocol を切るとき、 (a) 遷移を伴わない最頻の行為 (状況共有・memo・ping) を **protocol 内の inert な kind** として最初から用意する (= 検証は通るが状態は動かさない) / (b) 旧経路との**混在を error にしない** (= 旧形式の記録が在っても、 新 protocol の遷移が始まるまでは両方 live) / (c) 導入初日に「誰がどの経路で書いたか」 を見る (= 迂回の有無が最速の設計 feedback)。 迂回が観測されたら、 参加者に規律を説くのではなく kind を足す ([§8.32](#rca-as-labeling) と同じ向き = 記録でなく機構)。

reflex: 「〜は request が無いと投稿できない」 「旧形式で書いておいて」 と言いかけた瞬間に、 その行為を protocol 内で 1 コマンドにする方が安いかを問う。

origin: 2026-09、 layer-3 の session 宛て board を v2 (request / claim / submit / accept の検証つき) に切り替えた初日、 **両 vendor** の session が状況共有を旧形式 JSON の手 commit で投稿した (= v2 に request 不要の kind が無く、 v2 の `update` は request 必須、 旧形式が v2 thread に在ると protocol error)。 同日、 inert な `note` kind + 旧形式との混在許容 + runner 向け `--json` で design-out。 同型 = mechanism design の「default が最安でなければ守られない」、 [§8.31](#principle-birth-stock-audit) の flow / stock と対をなす「導入初日の flow 観察」。

### <a id="context-branch-as-leak-path"></a>8.34 安全側の出力が context 判定に依存するとき、 判定の設定漏れが唯一の穴になる — 分岐を消せないか先に問う

「公開面なら控えめに / 非公開面なら詳しく」 のように **出力の内容を context で分岐**させる設計は、 分岐条件 (= marker file / config flag / 環境判定) が常に正しいことに安全性を賭けている。 marker は**付け忘れる**、 flag は**新しい対象に伝播しない**、 判定は**想定外の経路で外れる** — そして外れ方は不可逆な側 (= 晒す側) に倒れる。 分岐を持つ限り、 事故の原因は「機構の欠陥」 ではなく最も起きやすい「設定漏れ」 になる。

- **先に問うべきこと**: 出力を減らして**分岐そのものを消せないか**。 消せれば「設定漏れ」 という事故クラスが構造的に消える (= [§2.5](#sot-duplication-trichotomy) の design-out を、 SoT 重複でなく*条件付き出力*に適用した形)。
- **実例 (2026-09-10)**: commit の trailer に session の出自を記録する設計で、 当初案は「公開 repo は id のみ / 非公開 repo は host と surface も」 の出し分けだった。 分岐は repo 側の marker file の有無に依存する = **marker 付け忘れの公開 repo で機器名が公開 history に焼き付く**。 採った解 = **id だけを書く**。 host は id から transcript を辿れば分かる (= 情報は失われていない) ので、 分岐を消しても機能が減らない。 結果、 全 repo で同一挙動になり marker 運用への依存がゼロになった。
- **分岐を消せる条件** = richer 側の情報が safe 側から**導出可能**なとき。 導出経路があるなら「両方に書く」 は冗長で、 冗長は leak 面だけを増やす。 導出できないなら分岐は本質的 — その時は分岐条件を fail-safe (= 判定不能なら safe 側) に倒した上で、 [§8.13](#conditional-firing-visibility) に従って「今どちらで動いているか」 を可視信号にする。
- 副次効果として、 分岐が消えると**説明も 1 本になる** (= 「public では〜、 private では〜」 という条件文を doc・test・review の全てで維持しなくてよい)。 条件分岐の維持コストは実装より doc 側に厚く乗る。
- **実例 (2026-09-13、 marker の設定漏れ)**: 公開 repo の gate (識別子・repo 名・未公開文書の逐語) は全部 marker file の有無という分岐に依存していた。 GitHub で public の clone 7 本に marker が無く、 どの gate も走っていなかった。 marker を書く経路は新規 repo の setup だけで、 他所で作られた repo の clone は一度も通らない。 公開かどうかは GitHub 側にしか無く分岐は消せないので、 visibility と marker を突き合わせる点検 (claude-config `scripts/check-public-marker.py`) を常設し、 別マシンの hook は毎 session の install で揃える。

### <a id="post-resolution-scope-revalidation"></a>8.35 resolver の出力は新しい trust boundary — 最終 action target で scope を再検証する

入力 path が許可 root 内でも、その後に呼ぶ resolver が別の path を返すと、最終的な read/write target は入力 scope を離れ得る。典型 resolver は `realpath`、symlink、Git の `rev-parse --show-toplevel` / `--git-path`、workspace manifest、cloud mount。**入力を一度検査した事実は、resolver の出力へ継承されない。**

同じ session で二つの向きが実測された:

- **scope escape**: bulk installer が許可 root 直下の candidate を列挙した後、Git top-level を解決すると root 外の checkout になった。candidate path の containment だけを見ていた初版は、その外側へ hook を書いた。
- **wrong anchor**: audit が `git rev-parse --git-path hooks` の relative result を caller の cwd 基準で読んだため、別 repo の正しい hook を `MISSING` と誤報した。relative path は resolver の所有 object (= 対象 repo) を anchor にしなければならない。

**pattern**:

1. 入力 path を構文・存在・許可 scope で検査する。
2. resolver を呼ぶ。
3. result が relative なら、shell の現在地でなく resolver contract が定める owner object に anchor する。
4. symlink を含む physical/canonical path に解決する。
5. **その最終 target で containment / audience / write authority をもう一度判定する。** 外なら skip/refuseし、必要なら exact target を明示指定させる。
6. test は「入力も出力も内側」だけでなく、(a) relative result、(b) symlink escape、(c) resolver が外側 absolute path を返す fixture を持つ。

これは path traversal 対策だけでなく、**認可判断を別表現へ運ぶ時の非継承**という一般形である。ID→record、alias→account、project→checkout等でも、resolve後のentityに対してscopeを再判定する。

### <a id="input-does-not-transfer-decision-ownership"></a>8.36 入力の提供は判断責任を移さない — 事実・規程適用・将来確約を分離する

規程・審査・算定を所有する相手が、その適用に必要として事実を照会することがある。このとき区別すべき object は 3 つある。

1. **事実入力**: 既に分かっている属性・登録情報・観測事実。照会を受けた側が提供する。
2. **規程適用の判断**: どの事実を起点・区分・支給対象として採るか。規程と判断権を持つ側が決める。
3. **将来行動の確約**: 当日にどこから移動するか、誰が追加資料を集めるか等。本人または実行主体が明示した時だけ成立する。

相手の二択照会に A と答えたことは、(1) の入力を渡しただけであり、(2) を代行したことにも、(3) を約束したことにもならない。後続のやり取りで相手が回答を別の category（例: 別用務の存在、当日の確定経路）へ拡張した場合は、元の照会を中立に示し、**回答した射程と、存在しない事実を分けて戻す**。実際に誤記していないのに「こちらの説明が不正確でした」と自己帰責すると、相手の category expansion を既成事実化する。

協力的な tone と責任の引取りは別軸である。「そちらの規程で判断してください」と命令形で突き放す必要はないが、柔らかくするために新しい仕事や個人情報収集を申し出てもいけない。既出情報で足りる場面では「先にお伝えした情報をもとに、規程に沿ってご確認いただけますと幸いです」のように、**語調だけを和らげて判断 owner は動かさない**。追加情報は、規程 owner が不足項目と必要性を具体化し、かつ取得が依頼 scope に入る場合にだけ集める。

domain 適用: 対外メールの書き方は [`research-email.md#mail-fact-policy-boundary`](../conventions/research-email.md#mail-fact-policy-boundary)。

### <a id="proxy-outbound-reply-blindspot"></a>8.37 他人名義で出した依頼の返信は、自分の受信箱に来ない — Cc は送信の証拠であって返信の網ではない

自分が起草し、**別人が自分の account から送る**依頼 (= 学生・共同研究者・家族の名義で出す照会、代理の申込) がある。自分を Cc に入れてもらうと、**送信された実文面**が手元に残る — ★ で空けた欄に本人が何を書いたかまで確定でき、記録の正本にできる。これは代理起草の返却経路として安い。

⚠️ **ところが Cc は返信の網にはならない**。相手が reply-all しなければ、回答は送信者ひとりに届く。ここで 2 つの失敗が重なる:

1. **検出器の入力面から落ちる**。「返信待ちの outbound」 を追う検出器は、たいてい *自分が送った* mail (= 送信済 category) を母集団にする。他人名義の依頼は自分の送信ではないので、書式上その母集団に入らない。⚠️ **入るように category を偽ると、検出器は鳴るが done_evidence が嘘になる** — 機械を騙して安心を買う取引で、[`§22`](#silent-probe-false-healthy) の自作版になる。
2. **probe の沈黙が両義になる**。その thread を引く probe は「送信 1 通のまま」 を返すが、これは「まだ返事が無い」 とも「返事は来たが相手にだけ届いた」 とも読める。**健全と失敗が同じ姿**をしている ([`§22`](#silent-probe-false-healthy))。

**pattern**: 代理送信を記録する turn で、追跡を**受信箱 probe でなく時計と人**に載せる。

- carrier は「期日までに動きが無ければ **送信者本人に訊く**」 という自己設定の時計にする ([`#expected-inbound-tripwire`](#expected-inbound-tripwire) の変種 — 来るはずの inbound が、そもそも自分宛でない場合)
- probe を書くなら **「この probe では未回答を判定できない」 を probe の隣に書く**。書かないと、次に読む人 (数週間後の自分を含む) が沈黙を「未回答」 と読む
- 送信前に決められるなら、**返信先を設計に入れる** — 重要な照会なら「返信は全員へ」 と本文で頼む、第三者を To に入れる、あるいは第三者名義で送る

reflex: 「自分を Cc に入れてもらった」 で追跡が済んだ気になった瞬間に、「**返事はどの受信箱に届くか**」 を 1 度問う。Cc が答えるのは「何を送ったか」 だけで、「何が返ってきたか」 ではない。

origin: 非会員の著者本人から編集事務局へ出した照会 (起草は第三者、第三者は Cc)。送信文面は Cc で正本化できたが、返信は reply-all されなければ届かず、手元の返信待ち検出器は category が違うため構造的に射程外だった。検出器を騙すより、時計と「本人に訊く」 を carrier にする方を採った。

### <a id="false-positive-declaration-needs-control"></a>8.38 「偽陽性だ」 の宣言は主張である — positive control を出せないなら、それは偽陽性でなく「未検証」

検出器が ✗ を出したとき、人はその場で「これは偽陽性だ」 と判定して先へ進むことがある。
この判定は**行動ではなく主張**であり、しかも普通の主張と違って **3 つの性質**を持つ:

1. **自己隠蔽する**。誤った「対策」 は動くので破綻が見えるが、誤った**免罪**は検査を黙らせるだけなので
   何も起きない。失敗したことが分からない形の失敗になる。
2. **class 全体に効く**。「この**様式**では印字されない」「この **kit** ではこの検査は無効」 のように、
   観察した 1 instance でなく**構造**に帰属させた瞬間、同じ class の他の instance を見る動機が消える。
3. **寿命が長い**。convention / docstring に書かれると、翌年・翌 project でも効き続ける。

∴ **宣言には証拠要件を課す**。「偽陽性」 と書いてよいのは次のいずれかを満たすときだけ:

- **(a) positive control を 1 つ挙げられる** — 同じ検査が**同じ条件で通る**対象を示す。
  ⚠️ **control は同じ run の中に居ることが多い** (= 同じ様式の別 kit / 同じ検査の別対象 / 隣の file)。
  免罪を書く前に「この class で ✓ になるものは手元にあるか」 を 1 度だけ探す。
- **(b) 検査が見ている次元そのものを別経路で観測**し、期待値と一致することを確かめた。
- **(c) どちらも不可能** → それは偽陽性ではなく **「未検証」**。第三の状態として**出力に残し**
  ([#required-field-fabrication](#required-field-fabrication) と同じ「無いを機械可読にする」)、
  その次元を見る別経路を用意するまでを 1 単位とする。

**機械側の最小の直し** = **✗ を「期待値が無い」 だけで報告しない**。同じ場所に
**「代わりに何が在るか」 (= 対立値)** を出す。不在の報告は「見えてないだけでは?」 と解釈できるので
dismiss されやすいが、対立値の提示は解釈の余地を残さない。検出器は可能なら自分で
✅ / 🔴 真陽性 / ⃠ 未検証 を判別する (材料: 前回値との差分 / 同 run の control / 表の見出し等の構造痕跡)。

**参照実装** (= 本 kernel を gate に落とした形): 検査 script に `--ack <対象> --ack-control <根拠>` を置き、
① 根拠の無い ack は拒否 (exit≠0) ② **同じ run の別対象で同じ検査が ✓ なら ack を棄却**
③ 通った ack は `⃠ 未検証` として出力と証跡 file に残す、の 3 つを機械側で強制する。
無効化を**思考から artifact へ**移すのが要点 — 思考は痕跡を残さないので、残るのは結論だけになり、
その結論が事実の書式を着てしまう ([#measured-vs-inferred-provenance](#measured-vs-inferred-provenance))。
証跡 file の helper は層1 `scripts/lib/run_log.py`。

**scope 規律**: 免罪を convention / docstring に昇格させるときは、**観察した scope をそのまま書く**
(= 「測った」 と「説明した」 を書式で分ける規律は [#measured-vs-inferred-provenance](#measured-vs-inferred-provenance))
(「1 件で観察」 を「2 件とも実測」 と書かない)。§9.8 は「単一観察から構造**対策**に飛ばない」 を言うが、
本節はその**鏡像で、鏡像の方が危険**である (上の性質 1)。
関連: [#set-diff-false-positive](#set-diff-false-positive) は**検出器に作り込む filter** の話で、
「正当性が確証できる category のみ」 と正しく言っているが、(i) **走らせた run の出力をその場で
無効と宣言する行為**を射程に入れておらず (= その判断は code にも doc にも残らないので
「除外理由を書く」 規律が発火しない) (ii) 「確証」 の**操作的な test** を与えていない。本節が (a)(b)(c) を足す。
[#rca-as-labeling](#rca-as-labeling) の双対 — あちらは「『〜型』 と言った瞬間が対策の最安時」、
こちらは「『偽陽性』 と言った瞬間が**検査を殺す最安時**」。

origin: 機関事務への申請で、入力後の突合 script が 9 件の ✗ を出した。これを
「この様式では明細行が印字されないから偽陽性」 という**確かめていない構造説明**で全部無効化して送信し、
事務から**同じ指摘を 2 度**受けた。反証 (= 同じ様式の別件が全行 ✓) は宣言の 1〜2 分前から同じ dir に
置かれており、免罪は 16 分後に layer 1 へ「2 件とも実測」 として landed していた。
事後に「✗ のとき対立値を併記する」 検査を書いて当時の artifact に当てると、当該 1 件だけが
🔴 になり旧値が並ぶ (= 反実仮想を回帰テストとして固定できた)。evidence base は 1 事例だが、
blast radius (= 誤った免罪が層 1 に残り毎年効く) で landing を判断した。

### <a id="completion-record-from-counterparty"></a>8.39 完了の記録は「送ったもの」 でなく「相手が返したもの」 から作る

外部システム (申請 portal / 投稿 system / Web フォーム / workflow) へ提出する作業では、
完了の記録が**自分の意図した成果物**から作られやすい: 上げるはずだった file を `submitted/<日付>/` に
copy し、ledger に「提出済」 と書き、task を close する。**これらは全部「送信した」 という事実だけで立つ**。

問題は、提出が**部分的に着地する**ことがある点である (= 複数の欄・複数の artifact にまたがる更新で、
一部だけが届く)。このとき上の記録は**偽証**になる。しかも典型的には、
**主張 (= 上げるはずだった file) とその反証 (= 相手が返した確認用 PDF / 受理画面) が同じ dir に
同居していて、誰も突き合わせていない**。後から読む人には両者の区別がつかない。

**pattern**:

- 完了記録の一次資料は**相手が返した artifact** (確認用 PDF / 受理番号 / 公開ページ / API の echo) にする。
- 意図した artifact を併置してもよいが、**両者の一致を機械で assert してからでないと同じ dir に置かない**。
- 記録を書く操作そのものを gate にする (= 一致しないなら `submitted/` を作らせず、
  `…-MISMATCH/` に検査出力ごと落として carrier を起票する)。
  [#completion-boundary-state-gate](#completion-boundary-state-gate) の外部システム版。
- 半端な着地が**そもそもなぜ起きるか**の側は [#batch-generation-hides-per-target-application](#batch-generation-hides-per-target-application)。
- **送信前 gate は override されうるが、送信後 gate は override できない** (= もう送ってしまっており、
  ✗ は「差し戻しを依頼する」 という行動に直結する)。完了判定は**送信後**に置く。

⚠️ 併発しやすい第 2 の穴: **検査が「集まっていないもの」 を言わない**。手順が N 種類の artifact を
集めろと言っていても、検査は**在るものだけを照合して緑を出す**ことが多い
(= [#fail-loud-not-fail-empty](#fail-loud-not-fail-empty) の**入力欠落版** — あちらは parse/load の
失敗を空で飲み込む話、こちらは**そもそも入力が来ていないことを言わない**話)。
「✗ が 0」 は「全部見た」 ではない。**期待する (対象 × 種類) の収集マトリクスを出し、
欠けていれば緑を出さない**。

origin: 申請の再提出で、`submitted/<日付>/` に「上げるはずだった明細 CSV」 と
「システムが返した確認用 PDF (= 旧い明細が写っている)」 が同居していた。ledger・状態表・task close の
4 つとも「送信した」 だけで成立しており、中身が旧いまま完了扱いになった。同じ提出で、手順が要求していた
2 種類 × 4 対象 = 8 個の検証 artifact のうち 4 個 (= 別画面の印刷) が 1 つも集まっておらず、
検査はそれを黙ったまま「✓ 全項目一致 — 送信してよい」 を出していた
(= 1 個だけ置いた dir でも同じ文言が出ることを実測)。その画面側の指摘 5 件は一度も機械照合されず、
人手の目視だけが最後の砦だった。

### <a id="measured-vs-inferred-provenance"></a>8.40 doc の一文は「測った」 と「説明した」 を書式で分ける — 説明は観察の権威を借りる

検査や観察を記録するとき、散文は **2 つの別種のもの**を同じ姿で書ける:

- **観察**: 検査が何を出したか (= 再現できる)
- **説明**: なぜそう出たのか (= 多くは仮説)

このとき説明の側に日付と「実測」 を付けると、**説明が観察の権威を借りる**。読む側 (数日後の自分・
別の session・user) には両者が区別できないので、仮説が「確かめられた事実」 として下流を縛る。

**特に危険なのは、その主張が検出器を黙らせる根拠になるとき** ([#false-positive-declaration-needs-control](#false-positive-declaration-needs-control))。
普通の誤った fact は、それに基づいて何かをすれば破綻が見える。**検出器を黙らせる fact の失敗は沈黙**なので、
誤りのまま何年でも生き延びる。

**pattern**:

1. **観察の文と説明の文を分けて書く**。同じ文に混ぜない。
2. **「実測」 の scope は実際に走らせた対象と一致させる**。1 件で観察したことを「2 件とも実測」 と書かない
   (= 複数形は測定の主張であって、見込みの表明ではない)。
3. **検出器を黙らせる根拠になる主張は、実測でなければ書かない**。推定しか無いなら「未検証」 と書き、
   検出器側にも ⃠ (= 第三の状態) を出させる ([#required-field-fabrication](#required-field-fabrication) と同じ
   「無いを機械可読にする」)。
4. 下流は**書式で信じる**。doc の一文は次の session にも user への助言にも等しく効く、と想定して書く。
5. **公開層では、観察の印は「実測」 だけにする**。日付・件数・対象 (どの申請・どの案件) の来歴は非公開の記録に置く。
   公開の手順書では、来歴そのものが owner の活動の事実になる ([`CLAUDE.md#owner-activity-facts`](../CLAUDE.md#owner-activity-facts))。
   システムの挙動がいつ真だったか (§2.6) の日付は残してよい。 消すのは owner の出来事の日付と件数。

§2.6 [#time-decaying-fact-authoring](#time-decaying-fact-authoring) が「いつ真だったか」 を要求するのに対し、
本節は「**どうやって知ったか**」 を要求する。両方とも undated/unsourced な断定を禁じる規律。

origin: 申請の入力後検収で、検査が 1 対象に出した ✗ の**説明**として立てた仮説
(「この様式では明細行が印字されない」) が、同じ turn のうちに script の docstring へ
「(実測、2 件とも)」 という形で焼かれ、同日 layer 1 にも landed した。実際には測っていない。
4 日後、その一文は (a) 別 session の診断の前提になり (b) **user への助言 (「画面を目視するしか検証手段が無い」)
にまで伝播**し、独立の再実測で初めて覆った。伝播経路のどこにも「これは仮説だ」 と読める手がかりは無かった。

**第 2 観察 (2026-09-12、同日・別 session)** — 形が違うので併記する。承認 dialog の内訳を測るのに
`permission-dialog-audit.py --diagnose` を **`--no-run-hooks` (= hook を実行しない速い測り方)** で走らせ、
出た 21 件を層 1 doc に「実測 219 件中 21 件 (約 1 割)」 と焼いた。既定 mode (= hook を実行) で
取り直すと **3 件**。差の 18 件は意図した hook gate が `rule` 系に落ちたもので、しかも
**script は自分の出力の冒頭で毎回その旨を印字していた** (= 但し書きは目の前にあった)。

∴ 上の (1)-(4) に 1 つ足す: **道具が自分で出した但し書きは、数字だけ引き写すと落ちる**。
速さ・簡便さのための flag (`--no-*` / `--quick` / sampling / 期間短縮) で得た数を doc・報告・
commit message に**載せる瞬間に、既定 mode で取り直す**。取り直せないなら flag 名を数字に添える
(= 「21 件 (`--no-run-hooks`)」)。前段の incident が「説明を観察の書式で着せた」 のに対し、
本件は「**観察ではあるが、別条件下の観察**を無条件の実測として書いた」 = 同じ scope 規律の mode 版。
2 観察で [`§9.8`](#single-observation-scope-check) の bar を充足。

### <a id="unique-token-kills-the-carrier"></a>8.41 保存する rule の key に per-call 一意な値が混ざると、その rule は二度と発火しない

[`§8.19`](#retrieval-key-choice) は**読み側**の key 軸 (= 人間可読な属性は経路で失われるので null になる)。
本節はその**書き側**: 学習した対処を保存するとき、key が**具体的すぎる**と、保存はされるのに
二度と一致しない。user から見た症状は「**直したはずなのに直っていない**」 で、
対処を繰り返すほど死んだ entry が増える。

典型は、保存 key に次のような**呼び出しごとに変わる token** が混ざる場合:

| token | 現れる場所 |
|---|---|
| session / run の UUID | 作業 dir・一時 file・log path (= path の**途中**に埋まるので目視で気付きにくい) |
| 乱数・hash の file 名 | 処理系が退避した中間成果物 |
| 日付・連番 | backup 名・snapshot 名 |
| 自由文の一部 | その回だけの検索式・message 本文 |

**判定**: 「同じ対処をもう一度したくなった場面で、保存した key はそこで literal 一致するか」。
しないなら、それは carrier ではなく**使い捨ての記録**。

**reflex**: 対処を保存した直後に *(a)* key の中で毎回変わる部分を指差す *(b)* 変わる部分があるなら、
glob / pattern を受け付ける**別の保存面**を探す (= 同じ対処でも経路を替えると pattern 化できることがある)
*(c)* literal しか保存できない面なら「これは 1 回きり」 と明示し、carrier として数えない
([`§human-memory-not-a-carrier`](#human-memory-not-a-carrier) と同じく、**carrier でないものを carrier と数えない**のが要点)。
⚠️ **「効かなかったのでもう一度保存する」 が最も自然な誤対処** — 回数を増やしても一致率は上がらない。

**機械化**: 保存面ごとに検出器を持てる。実例 = Claude Code の permission 「常に許可」 は command 文字列を
literal 保存するため、spill file や scratchpad のように path へ UUID が入る command では永久に効かない。
`scripts/permission-dialog-audit.py --diagnose` が `rule_unique` として切り分け、消し方
(= literal しか保存できない Bash でなく、glob path rule を受け付ける Read tool へ**経路を替える**) を出す
(層 1 [`claude-code-permissions.md#always-allow-never-matches-again`](../conventions/claude-code-permissions.md#always-allow-never-matches-again))。

origin: 2026-09-12、user「こういうのいちいち聞かれるのうざいんだけど。直したはずなのに直ってない」。
実際 1 週間前に同じ形で「常に許可」 を押しており、保存された rule は session UUID + 乱数 file 名を
含むため二度と一致しない状態だった。n=1 ゆえ構造対策には飛ばさず、既存の検出器に 1 分類を足す範囲に留めた
([`§9.8`](#single-observation-scope-check))。

### <a id="detector-fires-on-its-own-signal"></a>8.42 検出器が literal で持つ signal は、 その検出器について書かれた文章にも現れる — 除外でなく**構造**に anchor する

検出器の signal が「どこにでも書ける文字列」 のとき、 **その検出器を保守している最中の出力**に
signal そのものが載る。 source を grep する / test fixture を読む / doc を diff する — どれも signal を
含む text を観測 channel に流すので、 検出器は**自分自身の整備に対して鳴く**。

観察 (n=4、 いずれも別々の機構):

| 機構 | 自己発火の経路 |
|---|---|
| 検索 null の nudge hook | 検出語 (= shell の glob 失敗 message) を素の部分文字列で探していた → **その hook の source を grep した出力**で発火 |
| URL 規約の guard | 禁止 pattern を含む自分の source / test / doc が、 そのまま違反例として拾われる |
| 機密 literal の漏洩 gate | pattern 一覧を gate と同じ repo に置くと、 **一覧そのものが push される** (= 自己発火でなく自己 leak) |
| GUI app の dialog を探す probe | 検出語 (= 「アクセス」) が **probe 自身の失敗 message** (= UI を読む許可が無いという error) に含まれ、 UI を 1 つも読めていないのに「dialog あり」 と判定 (= 保守中の text でなく失敗経路の出力。 対策 = 出力を判定に使う前に probe の成否を見る、 [`macos-gui-app-automation.md#dialog-presence-probe`](../conventions/macos-gui-app-automation.md#dialog-presence-probe)) |

**対策は 2 つあり、 効く範囲が違う。 混同すると穴が残る**:

1. **path 除外** (= 自分の source / test / doc を検査対象から外す) — **走査型**の検出器 (= file 集合を
   読む lint / grep gate) にしか効かない。 ⚠️ 除外を dir 単位に広げると同居する別 gate まで silent に
   死ぬので、 除外は自分の file だけに閉じる。
   ⚠️ <a id="excluded-config-is-a-hiding-place"></a>**除外した file は「隠し場所」 になる** — 検出器の設定 file
   (受理一覧・除外語・pattern 一覧) は **検出対象の文字列をそのまま並べる**ので除外せざるを得ないが、
   除外した瞬間、 そこに何を書いても検出器は見ない。 **代償は別の検査で払い戻す**: 設定の各 entry が
   **検査対象の側に既に在る**ことを確かめ、 無いものを finding にする (= 「見た上で残す」 の宣言なら、
   その文字列は対象のどこかに在るはず。 無いなら宣言ではなく新しい書き込み)。 この検査があると、
   除外は「既に在るものを再提示しない」 だけの意味に縮み、 隠し場所には使えない。
   ⚠️ **この検査は「本体の検査を省略する回」 でも払う** — 本体が重くて台帳や cache で skip する設計だと、
   「一度 clean になった対象に、 後から設定 entry を足す」 が誰にも見られない窓になる (= 除外した gate は見ない、
   skip した走査も見ない)。 設定の検証は本体より軽いのが普通なので、 skip 判定より**前**に置く。
2. **構造 anchor** (= signal が「真の producer だけが出す形」 で現れたときだけ拾う) — **観測 channel**
   (= tool の出力・log・diff) を見る検出器には外すべき「file」 が無いので、 **こちらが唯一の手**。
   error message なら行頭 + 発行元 prefix + 区切り記号まで含めて固定する。

構造 anchor の落とし穴: **同じ error でも文脈で形が変わる**。 実測してから固定し、 観測した形を全部
test に並べる (= 1 形だけ固定すると残りを miss する)。 実測例では、 同じ shell の同じ失敗が実行文脈に
より 3 通りの prefix を持っていた。

- **判別**: 「**この signal は、 この検出器について書かれた文章の中に現れうるか?**」 を 1 問。 yes なら
  本節。 特に signal が自然言語の一文・固有の pattern 一覧・禁止 literal のとき。
- **放置のコスト**: FP が「検出器を触っている最中」 に集中するので、 直そうとするほど鳴り、 読み手は
  「この検出器はうるさい」 を学習して**本物も無視する** (= [`§8.24`](#surfaced-not-consumed) 壁紙化への最短経路)。
- **由来 (2026-09-12)**: layer-3 の session で user が「機械で警告が出る件はなんとかならんか」 と指摘。
  実体は検索 null nudge hook の素の substring match で、 **その hook 自身の source を読んだ turn に
  発火**していた。 同日、 別 session が URL guard で同型を path 除外で処理しており、 漏洩 gate の
  「pattern 一覧を同じ repo に置かない」 規律も同じ kernel だったと判明 (= n=3、 [`§9.8`](#single-observation-scope-check) 充足)。
  instance (= 各 guard の anchor 実装と回帰 test) は layer 1 の当該 hook に残置。

- **実例 (2026-09-14、 棚卸しする検出器の fixture)**: 「出来事の語と日付が同じ行にある」 を探す検出器は、 自分の selftest の例文と
  runner の test の例文を、 公開 repo の棚卸しで自分で拾う。 例文を**実行時に連結して組み立てる** (`"20" + "31-04-02"`、 `"応" + "募"`) と、
  source の行には構造 (日付の形・語) が現れないので、 除外 list も承認も要らない。

### <a id="sweep-null-needs-per-form-control"></a>8.43 sweep の「無い」 は、探している class の形ごとに陽性対照を通してから信じる

grep や正規表現で「同じ問題が他に無いか」 を掃くとき、pattern は**書いた人が思い浮かべた 1 つの形**に合わせて書かれる。
class の別の形がその pattern を素通りすると、sweep は「無い」 と答え、その null は **0 件の出力として正しそうに見える**
(= [`§8.38`](#false-positive-declaration-needs-control) の偽陽性宣言と対になる、偽陰性側の自己隠蔽)。

観察 (2026-09-13、同じ日に独立 2 件):

| sweep | pattern が合わせた形 | 素通りした形 |
|---|---|---|
| LaTeX の式参照の置き場所 (規則は「動詞や前置詞の項に素の番号を置かない」 = **位置**で定義) | 違反の表層形の 1 つ = `~` の無い `\labelcref` | `~` 付きで前置詞の直後に立つ `\labelcref` (同じ規則への違反) |
| 1 文字ごとに本文を slice で複製する書き方の同類探し | `re.match(…, text[i:])` を `[^)]*` で挟んだ正規表現 | pattern の文字列の中に `)` を含む、探していた書き方そのもの (`[^)]*` がそこで止まる) |

**対策 = sweep を本番に当てる前に、class の既知の形を 1 行ずつ並べた陽性対照に当てる。** 一致しない形があれば、
その sweep の null は「無い」 ではなく「その形は未検査」 と書く。形は規則の**定義** (位置・関係・意味) から列挙し、
見つけた instance の表層から列挙しない。規則を機械で判定する検査器があるなら grep でなくそちらに当てる
([`§8.42`](#detector-fires-on-its-own-signal) の「1 形だけ固定すると残りを miss する」 の sweep 版)。

- **判別**: 「この pattern は class の**他の書き方**に当たるか?」 を、書き方を 2 つ以上挙げてから答える。
- **由来 (2026-09-13)**: 原稿の参照形を直す pass で、手の grep を sweep の正本にしていた。位置で判定する検査器を足すと、
  grep の射程外の 1 件が出た。同じ日、性能修正の同類探しで書いた正規表現が、探している書き方に一致しない形だった
  (広い grep を併走させて気づいた)。1 件目の instance = [`latex.md#bare-parenthetical-crossrefs`](../conventions/latex.md#bare-parenthetical-crossrefs)。
- **3 件目 (2026-09-14、 漏洩 sweep)**: 公開 repo の例示から未公開文書の中身を抜く sweep で、 原稿の術語の list による走査は **文書への評価 (模擬審査の指摘など)** を 0 件と答えた (評価の文章は原稿の術語を含まない)。 「模擬審査 / 盲検 / 実測 / 評点」 という**過程の語**から入り直すと見つかった。 class の形 = 原稿の文・数値・結果、 **その文書に対する評価**、 経緯。 term list が当たるのは最初の形だけ ([`CLAUDE.md#non-identifier-content-leak`](../CLAUDE.md#non-identifier-content-leak))。

- **4 件目 (OS 差、 実測)**: 「個人の home 直下の絶対 path」 を止める gate が POSIX 形 (`/Users/<name>`) だけを見ていて、 **Windows 形 (`C:\Users\<name>`) が素通り**していた。 同じ class の事実に **OS ごとの表記**があり、 そのうち 1 形しか 書かれていない検出器は、 別 OS で書かれた成果物 (build spec・3D モデルの texture 参照・project file) の中で黙る。 class を挙げるときは「別の OS / 別の区切り文字 / 別の escape ではどう書かれるか」 まで数える (drive letter は任意、 区切りは `\` と `/` の両方が現れる)。
- **5 件目 (置き場所、 実測)**: 対象を path で選ぶ検出器 (= 「この形の file だけ検査する」 規則) を、 **1 つの基準点からの相対 path だけ**で書いていた。 同じ対象が別の場所に在るとき — 別の場所に clone した repo、 test が作る一時 repo、 別の作業 root で回した検査 — 規則はどれにも当たらず、 検出器は**何も言わずに素通り**する (= 0 件が「無い」 でなく「見ていない」)。 対象の同定は**その repo の中での位置**で書き、 基準点が外れたときは repo の最上位を代わりの起点にする。 陽性対照は、 本番で走る場所だけでなく**違う場所に置いた同じ対象**でも通す (= 配線の test が一時 repo で回るなら、 そこでも当たることまでが対照)。

### <a id="rule-visible-where-the-act-happens"></a>8.44 規則は「それを破る行為をする session」 が読み込む場所に置く — 正しい repo に書いた規則でも、 行為の場所から見えなければ無いのと同じ (2026-09-13)

**症状**: 規則は存在し、 内容も正しく、 正本もはっきりしているのに、 同じ class の事故が規則の後で 2 回起きた。

**実測 (2026-09-13)**: 「公開 repo の例示に未公開文書の文を持ち込まない」 という規則は、 公開 repo 自身の指示書 (その repo を作業 dir にしたときだけ読み込まれる) と、 別 repo の運用 doc の 1 項に在った。 例示を書いた session は上位の dir を作業 dir にして、 公開 repo の file を絶対 path で編集していた。 transcript で規則の文面が初めて現れたのは、 違反した commit の 33 分後だった。 その間に回した漏洩検査は識別子の list だけで、 規則が求める原稿の術語での走査は入っていなかった。

**規則を書くときに問う**:
1. この規則が守る**行為**は何か (例: 公開 repo に commit する、 層1 に例示を書く)。
2. その行為をする session は**どこを作業 dir にして、 どの指示書を読み込んでいるか**。 行為の対象 repo と作業 dir は、 hoist・横断 sweep・別 repo からの絶対 path 編集では一致しない。
3. 読み込まれないなら、 (a) 常に読み込まれる面 (root の指示書) に 1 行を置く、 (b) 行為の境界 (pre-commit・書き込み hook) に機械の gate を置く。 (b) は context に依存しないので、 機械で判定できる部分はこちらに寄せ、 (a) には判定できない部分 (言い換え・判断) を残す。

**なぜ気づきにくいか**: 規則の書き手は規則の repo を作業 dir にして書くので、 自分には常に見えている。 見えないのは別の場所から来る session だけで、 そちらは規則が無いことに気づけない。 代わりに手元の前例が手本になる ([§8.3](#precedent-as-training-data))。

関連: [#documented-not-wired](#documented-not-wired) (engine に入っていない) / [#firing-surface-hierarchy](#firing-surface-hierarchy) (発火面の強さ) / [#context-branch-as-leak-path](#context-branch-as-leak-path) (スイッチの設定漏れ)。


### <a id="rule-gap-not-owner-decision"></a>8.45 規則に class が無いことから生じた迷いを、 owner の判断として中立に渡さない (2026-09-14)

**症状**: sweep や監査が「要判断」 を出し、 それを受けた session が「残す？ 消す？」 と推奨なしで owner に聞く。 owner は
「有り得ん」 と答え、 実はそれが既定で決まっているべきだったと分かる。

**機構**: 迷いの原因が「規則にその種類 (class) が無い」 ことなら、 それは owner に固有の選好ではなく規則の穴である。 規則が黙っていると、
判断を回すことが正しい振る舞いに見え、 分類の誤りが質問の形で owner に移る。 推奨を付けない質問は、 誤った前例
([`§8.3`](#precedent-as-training-data)) を owner の目の前に中立の選択肢として並べる。

**対策**:
1. 「要判断」 を渡す前に、 **その迷いが規則の欠落から来ているか**を問う。 来ているなら、 近い規則の既定 (安全側の規則なら「迷ったら書かない」) を
   推奨として先に書き、 規則の穴そのものを finding として並べる。
2. 公開・送信・削除のように取り返しの効き方が非対称な判断では、 推奨は戻せる側 (書かない・送らない) に置く。
3. owner の答えが既定を示したら、 同じ turn で規則に class を足す (次の session が同じ質問を繰り返さない)。

**実例 (2026-09-14)**: 公開 repo に載っていた owner の活動の事実を、 sweep が「要判断」 と分類し、 受けた session が推奨の無い質問にした。
規則 = [`CLAUDE.md#owner-activity-facts`](../CLAUDE.md#owner-activity-facts)。

### <a id="semantic-detector-ack-ratchet"></a>8.46 誤検出を持つ意味の検出器は、 承認を「行の中身の hash」 に縛って固定する (2026-09-14)

**症状**: 語の共起で意味の違反 (例: owner の活動の事実) を探す検出器は、 正当な文でも発火する。 BLOCK にすると commit が止まり続け、
警告だけにすると読まれなくなる。 除外 list を path 単位で書くと、 その file に後から入った本物も黙る。

**pattern**:
1. **止める物と警告する物を分ける**。 固有語 (値の list、 個人層に置く) は誤検出がほぼ無いので BLOCK。 共起は commit 時には警告だけ。
2. **棚卸しは承認済み一覧つきで FAIL にする**。 一覧の 1 行 = 「repo/path + 空白を正規化した行」 の hash。 行が書き換わると hash が変わり、
   もう一度判断を求められる (= 承認が別の中身に流用されない)。 固有語の行は承認できない。
3. **承認は読んでから**。 一覧に足すのは、 その行が違反でないと判断した後だけ。 一覧が「押せば通る」 儀式にならないよう、 足した人と日を残す。
4. **較正の標本を検出器と同じ認識で選ばない**。 「今日直した行」 に対する再現率は、 直した人が違反と認識できた形に偏る。
   導入時の数字は目安にとどめ、 認識に依らない標本 (違反を持ち込んだ commit の全追加行など) で測り直す。

**実装例** = [`scripts/check-activity-facts.py`](../scripts/check-activity-facts.py) (`--scan-public` + 個人層の承認済み一覧)。 兄弟 =
[`§8.38`](#false-positive-declaration-needs-control) (偽陽性の宣言には対照を要求する) / [`§8.43`](#sweep-null-needs-per-form-control)。

### <a id="deadline-in-the-referent"></a>8.47 期限が本文に無く、参照先の予定にしかない義務 — 日付 detector の構造的圏外 (2026-09-14)

通知の中には、**期限を日付で書かないもの**がある。「事前に用意して当日お持ちください」 型の指示は、期限が受け手の予定 (= 開催日・訪問日・手続きの当日) にしかなく、本文のどこにも現れない。この class は既存の網を 3 つとも外す:

- **期限 detector の圏外** — tracked item の `deadline` field を読む設計では、誰かが起票するまで「期限」 という object がそもそも存在しない。
- **予定 detector の圏外** — 直近 1〜2 日だけを見る設計だと、「2 週間前に用意しておく」 には手遅れの時点でしか鳴らない。
- **返信 detector の圏外** — 返信を要求しないので「未返信」 の網に掛からない。

悪いことに、この class は返信不要であることが多く、**「返信不要 ⇒ 対応不要」 という省略推論**を誘発する。件名も受領物のお知らせに見え、本文 1 行目に義務が在っても開かれない。

対策は 2 面で、片方だけでは class の半分が無防備に残る:

1. **受信側 (語彙)**: 「用意して持参」 系を義務 class の識別語に入れる。⚠️ 動詞側 (持参・印刷) より**名詞側 (= 持って行く物の名前)** の方が precision が高い — 動詞は本文にしか出ないことが多く、名詞は件名に出る。
2. **予定側 (段の新設)**: 予定の台帳に「直前準備」 の段を作り、開始日から逆算した窓で「準備の記録が無い」 を検出する。**通知が来ない持ち物** (= 誰も教えてくれない物: 容れ物・変換器・現金) は原理的に受信側で拾えないので、この 2 面目が唯一の網になる。

消費の記録は**予定側に 1 つだけ**置き、準備不要と判断した場合も記録する (= 「見て要らないと決めた」 と「見ていない」 を区別できなければ、detector は毎回同じ行を出し [§8.24](#surfaced-not-consumed) の壁紙化に直行する)。

兄弟 = [§8.18](#request-mail-two-date-axes) (二日付軸がある場合にどちらを urgency に使うか) — 本節はその退化形で、**日付が片方しか存在しない**場合にあたる。

origin: 実測 (通知は届き、表示もされていたが、期限に当たる日付が本文に無く、どの日付 detector にも乗らなかった事例)。

### <a id="mention-implies-triage"></a>8.48 自分の出力で言及した item は、その turn で triage を終える — 言及は認識の証拠 (2026-09-14)

surface されている item を、自分の応答の中で**引用・言及しておきながら処理しない**のは、未読のまま放置するより悪い:

1. 言及は「認識した」 ことの証拠を残す。以後その item について「気づかなかった」 は使えず、放置は事故ではなく**選択**になる。
2. 言及した turn は、その item の文脈が既に手元にある**唯一の安い瞬間**である。次の turn には再取得のコストが戻る。

典型的な失敗は、**利用者の問いの literal scope だけを満たして閉じる**時に起きる。「この番号は何か」 に番号だけ答えると、同じ通知の中に在る未処理の義務は、参照されたのに触られないまま残る。問いに答える過程で item を開いていれば防げたことが、開かずに済ませたために残る。

reflex: **surfaced item の題名・識別子を自分が書いた瞬間**に「これは今 triage できるか」 を 1 回問う。できるなら同じ turn で終える。できないなら、その旨と理由を利用者に渡す (= 黙って次の session へ送らない)。

これは [§8.24](#surfaced-not-consumed) の消費側の最小単位。機械化は難しい (= 出力の意味を読む必要がある) が、規律としては安い — 発火条件が「自分が今書いた」 なので、判定に外部情報が 1 つも要らない。

### <a id="hedge-scope-covers-only-generated-options"></a>8.49 留保は自分が並べた選択肢の上にしか掛からない — 出所を疑う留保と、選択を疑う留保は別物 (2026-09-14)

答えに「未検証」 と添えるとき、その留保は**自分が生成した候補集合の内側**しか覆わないことがある。
候補を 2 つ並べて「どちらが正しいかは未確認」 と書いても、**候補集合そのものが間違っている**失敗
(= 求められている値がそのどちらの型でもない) には一切掛からない。

この形の留保は二重に悪い:

1. **覆っていない軸を覆ったように見せる**。読む側は「不確かさは表明された」 と読むので、
   検算の動機が消える。書いた側も同じで、留保を書いた時点で慎重さの義務を果たした感覚が生まれ、
   **1 コマンドで済む確認をしなくなる**。
2. **誤りのある軸が、留保の文言から構造的に隠れる**。留保は候補の *選択* を語っており、
   値の *出所* を語っていないため、「この値はどこから来たのか」 という問いが提起されない。

**判別**: 留保を書く前に、その値が **引用か生成か**を分ける。

- 引用 (= 手元の記録・一次資料に literal で在る) → 留保は「解釈・適用」 の軸で書く
- 生成 (= 記録には無く、隣接する値や型から埋めた) → 留保は**出所の軸**で書く:
  「この値は記録に無く、私が推測した」。これは選択の留保とは別の文であり、片方で代用できない

**reflex**: 留保を書いたら「この留保は、私が並べた候補の**外側**を含んでいるか」 を 1 回問う。
含んでいないなら、その留保は候補集合の正しさを前提にしている = 前提の方を安く検算する
(= 記録に literal で在るかを grep する、一次資料の 1 行を読む)。

**「無い」 は完全な答えである**という点も併せて要る。記録が持っていない値を問われたとき、
「記録にはありません」 は非回答ではなく、**正しく完全な回答**である。値を返す義務が真を返す義務を
上回ると、隣接する同種の値が空欄に吸い込まれる ([§4.1](#motivated-substitution-trap) の retrieval 版)。

兄弟 = [§8.40](#measured-vs-inferred-provenance) (観察と説明を書式で分ける = 出所軸の doc 版) /
[§8.14](#single-field-identity-corroboration) (1 field の一致を同一性と等値しない) /
[§8.19](#retrieval-key-choice) (null は key を先に疑う)。

origin: 実測 — ある識別子を問われ、手元の記録には**別の役割の識別子**とログイン画面の URL しか
無かったのに、前者を答えとして返した。末尾に「未検証」 と添えてはいたが、その留保は自分が並べた
2 つの候補のどちらかという軸に掛かっており、**そもそも候補の型が違う**という実際の誤りには
掛かっていなかった。訂正は人間から来た。

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

### <a id="context-capacity-evidence-layers"></a>10.7a headline context と実効耐久力を同一視しない — capacity / cost / durability の 6 軸を別々に測る

「モデルは N token 対応」と「この製品のこの session が N token まで圧縮なしで耐える」は別の主張である。context 耐久力を比較・診断するときは、少なくとも次の 6 軸を分離する。

| 軸 | 問うこと | 主な証拠 |
|---|---|---|
| model / API advertised capacity | モデル/API が公称する最大容量は何か | 公式 model/API documentation |
| product / client selected capacity | 製品・認証経路・client が選ぶ default / maximum は何か | 公式 product docs、supported config、client contract |
| billing / credit policy | 長文入力で価格・credit・quota の境界が変わるか | **同じ製品 surface / 認証経路**の公式 pricing / usage documentation |
| per-run usable window | 実行中に server/client が報告する usable window は何か | live usage event、server response、diagnostic log |
| compaction trigger | 実際にどの input 量・状態で compaction したか | 複数 run の event timestamp と token counter |
| retained useful context | compaction 後に task state・制約・根拠がどれだけ保持されたか | recovery probe、同一 task の品質評価 |

証拠の優先順位は **公式の製品契約 > live runtime / server report > bundled client catalog > clean ratio や単発観測からの推測**。例えば「報告 window が catalog 値の一定比率」は safety margin 仮説を生むが、backend contract の証明にはならない。API の headline capacity だけで product surface の usable window を断定するのも同じ誤りである。さらに、同じ token 数が capacity metadata と API の pricing discontinuity に現れても同義とは限らない。API の価格境界から subscription 製品の default window や credit 消費を推定せず、billing 軸は同じ surface の契約で別に立証する。

vendor 間比較は、repository、instruction chain、tool schema、task、認証経路を揃え、surface / client version / model / startup bytes / prefix size / per-turn input / compaction event / recovery quality を記録する。入力は少なくとも **product-owned prefix** (system / developer / built-in tools)、user-controlled always-on instructions、tool / MCP schema、turn history / tool output に所有者分解する。同じ repository を開いただけでは hidden prefix まで揃わないため、観測不能部分は unmatched confounder と明記する。

大きな `SESSION.md` や instruction file は budget を消費する一因として測れるが、製品限界や vendor 差の単独原因とは扱わない。削除前に byte inventory と with/without の marginal A/B を行い、まず user-controlled always-on 面を pointer + on-demand read に縮め、tool output を bounded にして再測定する。実測値・hostname・account state・公開先の個別 object は layer-4 / private case ledger に置き、この一般則へ instance を持ち込まない。

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

⚠️ **検出と修正を 1 つの script に入れるなら、修正は「検出した match そのもの」 から作る** — 規則を 2 度書くと、片方だけ直った時に **検査は緑なのに修正が壊れている**状態になり、しかも修正側は人が diff を読むまで沈黙する。実装形は「matcher が消費した token span / 捕捉群をそのまま置換に使う」 (= regex を書き直さない)。副作用として、置換の安全性 (境界・入れ子・引数の持ち越し) が検出側の test で同時に守られる。⚠️ 1 事例からの clarification につき新 axis にしない ([§9.8](#single-observation-scope-check))。origin: 2026-09-12、preamble alias 検査に `--fix` を足した時 (100 件級の一括置換を手 regex でやると事故る、が動機)。

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

**(E) 分割 (split) は、 検出器と転送 stub の両方に固有の腐り方を持ち込む (2026-09-12 実測、 layer-1 分割の 6 日後)**:

1. <a id="basename-index-collides-after-split"></a>**basename 索引は分割後に取り違える** — (C) の検出器は target repo の `*.md` を **basename** で索引する。 分割で同じ名前の doc が 2 repo に在る (新 home + 転送 stub) と、 **新 home へ path で正しく指している ref** が stub の anchor 集合と照合されて dangling と報告される。 実測 29 件の偽陽性で、 そのうち 2 件は同日に書かれたばかりの正しい ref だった。 ∴ ref が明示 path を持つなら **path で解決してから** basename 判定に落とす (修正済。 偽陽性 29 → 1、 残る 1 は本当に間違っていた path)。 偽陽性を放置した検出器は読まれなくなるので、 これは精度でなく**生存**の問題 ([`#firing-surface-hierarchy`](#firing-surface-hierarchy) と同じ理由)。
2. <a id="forwarding-stub-is-a-snapshot"></a>**転送 stub は分割時点の snapshot** — stub の anchor 表は移設の瞬間に存在した anchor だけを持つ。 **移設後に新 home へ足した節には転送先が無い**ので、 それを名前で指す ref (= `doc.md#new-anchor` と地の文で書く形) は最初から壊れている。 しかも壊れ方が**単調増加**する (新 home に節を足すたびに増える)。 実測: 分割 6 日で 4 anchor が転送先を持たず、 19 件の ref が届かなくなっていた。 ∴ **移設済 doc に節を足したら、 同じ turn で stub に転送行を足す** (既存 stub には「移設後に新設; 転送のみ」 と注記された前例がある = 規律は在ったが毎回は守られていなかった型 = [`#documented-not-wired`](#documented-not-wired))。
3. <a id="self-reference-is-nobodys-business"></a>**「その repo の内部参照はその repo の自分の問題」 が誰の問題でもなくなる** — (C) の検出器は設計上 target repo の内部 ref を除外する。 各 repo 側にそれを見る検査が無いと、 **同じ file の中の壊れた `#anchor`** (見出しを書き換えた・複数形の typo) は誰にも見られない。 実測: config 3 repo の 2487 link に 21 件 (単数複数の取り違え・消えた見出し・TOC の自己 link)。 ∴ path 解決で全 link を見る目を別に置く = [`scripts/check-md-anchors.py`](../scripts/check-md-anchors.py) (basename でなく path で解決するので 1 の取り違えも起きない。 (C) の検出器とは問いが違う = あちらは「restructure で下流が壊れるか」、 こちらは「書いた link がその path で解決するか」)。
4. <a id="slug-detector-pinned-to-renderer"></a>**renderer の動作を近似した検出器は、 renderer の実装に fixture で固定するまで信じない** — 3 の検出器を fleet 全体に当てた初回、 報告 33 件のうち **19 件が検出器側の誤り**だった。 内訳は 3 型: (a) slug の近似が空白の連続を `-` 1 本に潰していた (GitHub = github-slugger は空白 1 文字ごとに `-` 1 本、 `x.py — y` → `xpy--y`) / (b) 見出し中の `[label](url)` の URL まで slug に混ぜていた (GitHub は描画後の文字列 = label だけ) / (c) inline code や fence の中に**構文の例として書かれた** `[x](#slug)` を link と数えていた (+ `#L53` の行参照と `<slug>` の placeholder)。 どれも「GitHub で踏めば正しく飛ぶ link を壊れていると言う」 側の誤りで、 放置すれば読み手は検出器を信じなくなり、 **本物の 13 件も一緒に無視される**。 ∴ 近似した検出器には、 renderer が実際に出す値を**名指しの fixture** (em dash の見出し、 link 入りの見出し、 code span 内の例、 backtick 入り label の本物の link = 過剰除外の foil) として selftest に入れてから fleet に当てる。 slug 計算は 2 つの検出器で**共有する 1 実装** (`check-inbound-refs.py` の `gh_slug` + `rendered_heading_text`) に置き、 片方だけ直る drift を作らない。 修正後の fleet = 3001 link / 未解決 0、 本物 13 件は全て path 修正・転送先の補正・明示 id で解消した。
5. <a id="link-target-rot"></a>**着地先 file そのものが無い相対 link は、 答えが一意な 2 型だけ機械で直し、 残りは型を付けて報告する** — anchor 検査 (3) は着地先 file が無い link を扱わない。 同じ fleet で着地先の無い相対 link を素朴に数えると 898 本 (うち 457 本は symlink の複製を symlink の場所から解決した誤り)、 **renderer と同じ解決**をすると 8,718 本中 505 本で (symlink の複製は実体の dir から解決、 `%XX` を decode、 `file.py:12` の行番号を無視、 code span・fence・GitHub 式 `$数式$` の中は link でない) 型は 4 つに分かれた: (a) **段数ずれ** = sub-dir や `SESSION-archive/` へ移したのに `../` を張り直していない (MOVE の束縛再解決漏れ = [`paper-audit.md#relocation-rebinding-sweep`](../conventions/paper-audit.md#relocation-rebinding-sweep) の link 版)。 `../` を 0..6 段試して着地先が**ちょうど 1 つ**存在する時だけ直す (実測 219 箇所) / (b) **改名・移動** = git が改名を記録している (`git log --diff-filter=R -M -z`)、 あるいは移動先が一意 (31 箇所 + permalink 5 箇所、 計 13 repo・47 file・255 箇所を commit 済み差分から実測)。 **過去の記録が削除済み file を指す**場合は、 削除 commit の直前を指す permalink が「書いた時点で見ていた版」 に正確に届く (相対 path の書き換えでは届かない。 **現行の説明文**なら link でなく本文が古いので直さない) / (c) **path でない** = 数式 `[a,b](2)`、 メール件名の一覧 `[件名](通知:7/18締切)` を link 構文と誤認したもの / (d) **後継の無い削除・一度も commit されていない file** = 報告のみ。 道具 = [`scripts/fix-md-links.py`](../scripts/fix-md-links.py) (`--strict` で (a)(b) が残れば FAIL = suite 配線済)。 **手で直した分にも同じ検証を効かせる** (2026-09-13 追加): `--verify-diff [REV | A..B]` は変更 set が link target の中だけの差かを git の差分そのものから確かめる gate で、 新しい target は**変更後の tree** (commit ならその commit の tree = disk にだけ在る file では通さない) で実在し、 `.md` なら `#anchor` も定義されていることを要件にする (上の 255 箇所・18 commit を再生して件数が一致)。 `--list --suggest` は (d) の行に「同名の追跡 file が repo に 1 つだけ」 の移動先候補を添える (候補なので `--fix` は当てない)。 anchor 側の対 = `check-md-anchors.py --suggest` (近い実在 anchor と、 その anchor を定義している別 file)。 **発生の瞬間に止める** (2026-09-13 追加): 個人層の pre-commit chain と公開 repo の runner の両方が `--staged` を呼び、 stage した `.md` の **index の中身**に (a) があれば commit を止めて 1 行の修正コマンドを出す (0.1 秒、 escape = `CLAUDE_MD_LINKS_GUARD=0`、 壊れた engine では止めない設計 = [`hook-authoring.md#engine-failure-must-not-block`](../conventions/hook-authoring.md#engine-failure-must-not-block))。 移設の正本手順にも型として追加 = [`CONVENTIONS.md#session-trim-anchor-preservation`](../CONVENTIONS.md#session-trim-anchor-preservation)。 例示は除外 list でなく engine が見分ける: code fence (**list 内の字下げ fence を含む** = 行頭の ``` しか認識しない実装が例示を link と誤認していた) か、 行末の `<!-- md-links:ignore -->`。 ⚠️ **修正作業で 3 回踏んだ罠** (どれも selftest の foil): ① 書換えを `str.replace("](" + path)` の**前方一致**で行うと、 `DESIGN.md` の修正が正しい link `DESIGN.md.local` を壊す (link を構文解析して path が**完全一致**した時だけ書き換える) / ② 例示の中の同じ path まで書き換える (code span・fence・数式を mask してから置換) / ③ `git diff --name-only` は非 ASCII の file 名を 8 進 escape 付きで quote するので、 その path を検証に渡すと**差分 0 行として空振りして PASS** した (= 2 file が未検証のまま「検証済」 だった)。 **検証は対象ごとに「差が在った」 ことを要件にする** (no-op は失敗) → [`debugging-discipline.md#tooling-that-lies-on-binary-and-non-ascii`](../conventions/debugging-discipline.md#tooling-that-lies-on-binary-and-non-ascii)。 並行 session が同じ repo を編集中なら、 書換え → 検証 → **自分の path だけ commit** を `&&` で 1 回の実行にし、 相手が今まさに追記しうる file (当月の SESSION-archive 等) は相手の commit を待ってから触る。

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

task 記録 (TODO notes 等) の**散文の中に埋まった sub-obligation** (= 「宿泊証明書も要る」「M/D に印刷した」 型の 1 fact) は、 後の session が残 leg を**数え直す**ときに構造的に脱落する: 散文は要約されながら運ばれ、 要約は「主目的に対する残り」 だけを保存して付帯的な fact (取得窓・版・日付) を落とす。 落ちた fact が「窓が閉じる」 型 (取得は滞在中のみ / 紙は印刷時点の版で凍結) だと、 脱落 = 回収不能の実害になる。 実事例 2 系: 宿泊証明書 (残 leg の数え直しで「出張後」 バケツに畳まれ消えた → 窓が閉じる直前に人力 catch) / 印刷版 (印刷日が散文にしか無く staleness 判定不能のまま旧紙提出 → 差し戻し)。

### <a id="rollcall-line-pattern"></a>19.2 pattern: 機械可読 1 行 marker + 不在も咎める検出器

1. **固定 grammar の 1 行 marker** を task 記録に置く: `<名詞>: <値>` 形式で、 値は少数の enum + 括弧内自由文 (例: `宿泊証明書: 要(未取得) / 要(取得済 YYYY-MM-DD) / 不要(理由) / 不明(要確認)`、 `印刷版: YYYY-MM-DD (対象) / なし(理由) / 不明(要確認)`)。 散文と違い、 要約・数え直しを**素通りして生き残る** (= 行単位で copy され、 regex で機械照合できる)。
2. **検出器は marker の不在自体を咎める** (= absence-flagging): 対象 class の open task に点呼行が無ければそれを flag する。 これが無いと「書いた task だけ守られる」 = 規律の浸透度が不可視。 `不明(要確認)` を enum に含め、 「分からない」 を silent 放置でなく可視の状態にする。
3. **規律と機械は相補**: 検出器は点呼行が書かれて初めて中身 (窓・鮮度) を判定できる。 marker を書く reflex は規律側 (= 「event が起きた同 turn で書く」、 [`multi-session-coordination.md #green-light-carrier`](../conventions/multi-session-coordination.md#green-light-carrier) と同じ same-turn conversion family)。
4. **導入時に一度 stock sweep**: 既存の open task に点呼行を追記してから運用開始する (= 導入直後の absence-flag 洪水を実 triage に変える。 このとき「実は分からない」 が `不明(要確認)` として正しく可視化される)。

### <a id="rollcall-line-when"></a>19.3 適用判断

点呼行に昇格させる基準 = **散文のまま落ちると回収不能 or 高価な fact** (= 取得窓が閉じる / 版が凍結する / 期限が失効する)。 何でも marker 化すると notes が台帳化して可読性を失う (= [§2 (= #no-duplicate-rules)](#no-duplicate-rules) の運用台帳 SoT 重複問題と相似) — 「痛い脱落が 1 回起きた fact 種」 から event-driven に導入する。

### <a id="batch-generation-hides-per-target-application"></a>19.4 第 2 の消失経路 — 一括生成の完了イベントが、個別適用の未了を隠す

§19.1 は「**書かれたが散文に埋もれて消える**」 経路。もう 1 つ、**そもそも別個に表現されないまま消える**
経路がある: **1 つの変更を N 個の対象に適用する**作業で、変更の**生成**が 1 回の操作にまとまり、
**適用**が N 回に分かれるとき。

- 生成は 1 個の完了イベントを残す (「設定を N 本生成」「鍵を rotate」「規約を直した」「CSV 4 本再生成」)。
  この記録は**真**である — 生成は確かに終わっている。
- 適用は N 個の未了を作るが、**それを数える表現がどこにも無い**。完了イベントの側に吸われて見えなくなる。
- 結果、N 個のうち 1 個だけ適用されないという**半端な状態**が、記録上は「完了」 と区別できない。

**見分け方**: 完了報告・commit message に「**まとめて / 一括 / N 本 / 全部**」 が出たら、
「**では、これから何回適用するのか**」 を数える。数が 1 でないなら、その数だけの点呼が要る。

**remedy は §19.2 と同じ** (= 固定 grammar の点呼行 + 不在を咎める検出器) だが、**置き場が違う**:
点呼行は生成物の側ではなく **適用先ごとの作業記録**に置く (= 生成物は 1 つしかないので、
そこに書くと再び 1 個の完了イベントに畳まれる)。消込の ground truth は実行者の記憶ではなく
**適用先が返すもの**に置く ([#completion-record-from-counterparty](#completion-record-from-counterparty))。

⚠️ **語彙を分ける**: 「生成した」 と「適用した」 を同じ完了語 (「対応済」「done」「✅」) で書かない。
分けないと、後から読む人には**どちらの完了か判別できない**。

origin: 外部システムへの提出作業で、4 対象ぶんの明細 data を generator が一括再生成し、
その復旧が「N 本再生成」 という 1 個の完了イベントとして記録された。必要な行動は**対象ごとに
4 回の取込**だったが、その 4 個を数える表現は手順書にも記録にも無く、**1 対象ぶんの取込だけが
落ちた**まま送信され、相手から同じ指摘を 2 度受けた。落ちなかった項目は、いずれも
**対象ごとに個別編集したもの**だった (= 個別編集は per-target のしるしを残すが、一括生成は残さない)。

### <a id="state-as-one-record"></a>19.5 点呼行が 3 つ目の読み手を持ったら、 案件ごとに 1 つの状態 record へ育てる — 散文の marker を正本にしない

§19.2 の点呼行は「**人が書き、 検出器が 1 つ読む**」 規模の道具である。 同じ状態を読む道具が増えると (生成器・出口の gate・commit の関門・「これを base にするな」 の marker・入口 doc の表)、 **各々が状態を自分の表現で持ち始める** — 散文の 1 行、 file 名の印、 README の表、 人の記憶。 表現が N 個あれば、 状態が進む操作が通らなかった表現はその場で古くなる ([#index-doc-state-copy](#index-doc-state-copy) はその表の形)。

**育てる形**: **案件 (= 状態が進む単位) ごとに 1 つの機械可読な record** を置き、 状態を進める操作をその record を書く操作として実装する。 そこから先は:

1. **道具は全部その record を読む** — 生成器は「まだ作ってよい」 単位だけを作り、 gate は凍結した単位を検査対象から外し (黙って skip せず「凍結」 と 1 行出す)、 commit の関門は凍結した成果物の変更を止める。 判定の語を道具ごとに再実装しない ([#shared-field-resolver](#shared-field-resolver))。
2. **人が読む marker と表は record からの生成物にする** — 手書きの marker file・入口 doc の状態表は消さずに**描き直す** (人が読む面は要る。 要らないのは第二の正本)。 古い生成物は出口の検査と commit の関門が止める。
3. **粒度は「状態が別々に進む最小の単位」** — 案件全体で 1 状態にすると、 一部だけ出した・一部だけ刷り直した案件を表せず、 人は散文に戻る。
4. **やり直しは上書きでなく追記** — 進んだ状態を draft に戻す操作を用意し (理由を必須)、 前の record は履歴として残す。 「何を出したか」 は消してはいけない記録で、 上書きは §19.1 の消失を機械の側で再演する。
5. **状態を進める操作が record を書かない経路を残さない** — 古い生成器・手作業の経路が在るなら、 それ自身に「record を見て、 凍結なら止まる」 番人を埋める (= 移行の途中でも嘘の状態が生まれない)。

**いつ育てるか**: 読み手が 2 つ以下で、 状態が単調 (一度進んだら戻らない・粒度が 1 つ) なら点呼行で足りる。 **上の (1) の道具が 2 つ以上要る / 粒度が分かれる / やり直しが起きる** のどれかが出たら、 その時が record 化の時期。 逆に record を作ったら、 散文の点呼行の規約は**まだ record を持たない案件のために残す** (= 両方が同時に在る期間を設計に含める。 橋渡しの説明は検出器側に書く)。

適用例 = [`conventions/office-automation.md#printed-artifact-staleness`](../conventions/office-automation.md#printed-artifact-staleness) (点呼行の版) と、 同じ状態を 5 つの道具が読む形に育てた実装 (= 様式の案件の提出状態、 layer 3 の運用側に instance)。

### <a id="record-is-not-the-artifact"></a>19.6 凍結した記録は「渡した物そのもの」 として引用される — 一致するかを機械可読な field で宣言させ、 無宣言の凍結を拒否する

状態 record ([§19.5](#state-as-one-record)) に「出した・刷った・送った」 と書き、 その時の成果物の digest を残すと、 後の読み手は **その記録を現物として引用する**。 だが記録 = 現物とは限らない: 窓口で手書きの訂正が入った / 出した後に手元の source を直した / 刷ってから作り直した / **相手が刷って記入・押印した** — どれも「記録した bytes は現物と違う」 になる。 この差を note の散文に書くと、 §19.1 のとおり数え直しで落ち、 **記録が現物として引用される事故**になる (実測: 移行時に過去の記録を一括で取り直し、 どれが現物と同じかが note の文にしか無い状態ができた)。

**対策 = 一致を宣言する必須 field** (3 値 + 説明の強制):

| 値 | 意味 | 一緒に要るもの |
|---|---|---|
| 同じ | 記録した bytes・値 = 渡した物 | 何で確かめたか (同じ run で作って出した / 出した時刻の commit と照合) を任意で |
| 違う | 違うと分かっている | **何が違うか + 分かるなら現物の版の在り処を必須** |
| 不明 | どの版が現物になったか記録から決められない | **何が分からないか (候補の版) を必須** |

設計の要点:

- **宣言の無い凍結を道具が拒否する** (= field を optional にすると、 一番忙しい turn で空のまま凍結され、 後から埋める人が居ない)。 [§23](#required-field-fabrication) の「捏造される必須 field」 との違いは、 **第三の値「不明」 が最初から一級の答え**である点 — 埋められないときに嘘 (「同じ」) を書く誘因を設計で消してある。
- **「違う」「不明」 は毎回の催促にしない** — 事実として 1 行出すが、 問題の件数にも exit code にも入れない (催促にすると、 正しく「不明」 と書いた人が罰され、 嘘の「同じ」 が増える)。 未記入と形式の誤りだけを咎める。
- **後から分かった事実は、 凍結を打ち直さずに注記できる操作で書く** — 凍結をやり直すと digest が**今の** tree から取り直されて、 記録と現物の対応が切れる (= 直したつもりで証拠を壊す最短経路)。
- **差に数えないものを決めておく** — 本人が記録した file を刷って押した印のような「設計どおりの物理的追加」 は差ではない。 第三者が刷って書き込んだものは差。
- **機械が検査できるのは「書いたか・形が正しいか」 だけ** と明記する。 判定の誤り (本当は違うのに「同じ」) は検出できないので、 **根拠を読める形で残す**のが下限 ([#measured-vs-inferred-provenance](#measured-vs-inferred-provenance) の成果物版)。
- 日付が分からない凍結にも同じ形を当てる: 「不明」 + **確認した記録** (誰にいつ聞いて分からなかったか) を書けると、 検出器が「確認せよ」 を出し続けるのをやめられる ([#surfaced-not-consumed](#surfaced-not-consumed) の回避)。

## <a id="premise-bound-rule-expiry"></a>20. 規則は前提より長生きする — 上流属性の切替は下流定数の一括再判定を要求する

### <a id="premise-expiry-observation"></a>20.1 観察 pattern

運用規則の多くは **ある上流属性の下でだけ真** (= 誰が費用を持つか / どの制度で動いているか / 誰が責任者か / どの版の運用か)。 ところが規則は運用 doc に書かれた瞬間から「無条件の手順」 の顔で運ばれ、 **上流属性が切り替わっても規則本文だけが生き残る**。 出典が併記されていても「いつ・誰が」 までで「**どの前提の下で**」 が落ちているのが典型で、 その状態では規則を読んだ者に前提を再判定する手がかりが無い。

観察 2 系 (同一 session、 独立):

- **費用の出所が変わったのに、 旧出所に紐づく承認者・定数が残った**: 「申請書には X の印を押した原本を出す」 という規則の出典は「費用が X の資金だった時期の担当者発言」。 資金が別制度へ移り責任者が変わった後も規則本文はそのまま生き残り、 連動する様式の定数群 (制度名 / 課題番号 / 責任者氏名 / 押印欄) も旧値のまま default 表に居座っていた。 **user の「これ何で要るんだっけ?」 で初めて出典を遡って前提失効が判明**。
- **運用の版が変わったのに、 旧運用の文面 sample が同じ file に残った**: 手順書が新運用に全面改訂された際、 別言語 section の sample だけが旧運用の値 (曜日・所要時間・費用の扱い) のまま残置。 改訂は「本文」 を対象に行われ、 sample は改訂対象として認識されなかった。

### <a id="premise-expiry-mechanism"></a>20.2 なぜ規則だけが生き残るか

1. **規則は premise を落として運ばれる** (= [§16 (= #derive-not-summarize)](#derive-not-summarize) の規則ドメイン版)。 「A さんの印が要る」 は運びやすく、 「A さんが当時の資金の責任者だったから」 は運搬の途中で落ちる。
2. **切替は上流 1 箇所の event、 影響は下流 N 箇所**。 切替を記録した doc (= 差分 section) は誠実に書かれても、 「この切替で無効になる既存規則の list」 は書かれないことが多い。 差分 doc は **新しく増えること**を列挙する形式に自然と偏る。
3. **失効した規則は動作する** — 誰かが余計な承認を取りに行くだけで手続きは通ってしまうので、 誤りが露出しない (= [§8.8 (= #proxy-blind-spot)](#proxy-blind-spot) の silent 側)。 露出するのは「その承認者が不在で詰む」 等の別事情が重なった時だけ。

### <a id="premise-expiry-pattern"></a>20.3 pattern

1. **規則に premise を 1 句で併記する**: 出典 (いつ・誰が) に加えて **「どの前提の下で」** を書く (例: 「〜の印が要る 〔出典: 2026-06-03 担当者、 **前提 = 費用が資金 A から出ていた期間**〕」)。 これだけで後続の reader が前提の生死を判定できるようになる。
2. **切替 doc に「この切替で再判定が要る規則」 の欄を持つ**: 差分 doc を書く時、 増える項目だけでなく **「旧前提に紐づいていて再判定が要るもの」** を同じ doc に列挙する (= 空でも「無し」 と書く。 書かれない限り差分 doc は増分専用の帳簿になる)。
3. **期間を持つ規則は終端を焼き込む**: 「以降」 という open-ended な条件で書かない (= 次の切替時に stale な規則が自動延命する)。 機械判定に落とす場合も window の**終端**を条件に含める。
4. **「なぜこれが要るんだっけ?」 は premise-expiry の高信号 detector**: 手順の必要性への素朴な疑問が出たら、 反射的に手順を擁護せず **出典まで遡って前提の生死を判定する**。 今回の 2 件はどちらもこの問いで発見された。
5. **前提と一緒に動く定数群を 1 箇所に束ねる**: 上流属性に紐づく定数 (責任者 / 制度名 / 番号 / 承認経路) は個別に散らさず、 **前提名を見出しにした表**にまとめる。 切替時に表ごと差し替えられる形にしておくと、 sweep 漏れが構造的に減る。

### <a id="premise-change-stakeholder-lag"></a>20.4 前提の切替は、 自分の代わりに規則を当てる人にも届いていない — 他者の規則引用は「どの前提の文書か」 を正本で照合してから従う

§20.1-20.3 は**自分側の doc** に残る旧前提の話。 同じ構造が**他者の頭の中**にもある: 事務職員・共同運営者は自分の案件に規則を当ててくれるが、 彼らが持つ前提 (= どの財源 / どの制度で動いているか) は切替 event を知らされていなければ旧のまま。 すると **旧前提の文書から正しく引用した、 適用範囲外の規則**が「ルール違反だから変更せよ」 の形で届く。 引用は正確なので疑いにくく、 従うと不要な変更 (= 確定済の日程を動かす等) を実行してしまう。

- 実例: 講師謝金の財源を制度 A から制度 B に切り替えた後、 学科事務から「制度 A のマニュアルに『12 月中旬以降の謝金依頼は控えて』 とあるので 12/17 の講演を動かして」 と依頼が来た。 制度 B の執行文書には同趣旨の規則が**別パラメータ** (〆 12/15、 自制条項なし) で存在し、 かつ制度 B の担当課が 12/17 を名指しで個別受理済だった。 user の「別財源だからルールも別のはず」 → 正本 3 点 (A のマニュアル / B の執行文書 / B 担当課の回答) を照合して「変更不要」 が確定。
- 判別の型: 他者から規則の引用が来たら、 従う前に **(i) 引用元の文書はどの前提 (財源・制度・版) のものか (ii) 当該案件の現前提と一致するか (iii) 現前提側に同趣旨の規則があるなら、 そのパラメータと個別合意** の 3 点を正本で読む。 「同じ趣旨の規則が別文書に別パラメータで在る」 のが典型で、 趣旨が同じだからと A の数値を B に当てない (= §kofu-shinsei の「別制度の条項を輸入しない」 と同型)。
- 予防: 前提を切り替えた時点で、 **その前提で自分の案件に規則を当てる人 (学科事務等) にも切替を 1 行で伝える** (= 差分 doc の「再判定が要る規則」 欄の人間版。 伝えていなければ旧前提の介入は予測可能な event として受け止め、 相手の誤りとして扱わない)。 返答には**現前提の文書名 + 担当課の合意の記録 ID** を含め、 相手が自分の側で照合できる形にする。

### <a id="supersede-completion"></a>20.5 supersede は「新しい正本を書く」 では完了しない

規則を差し替えたとき、 転換は **上流 1 箇所に landing する** (= 新しい正本、 決定の記録)。 だが旧規則を書いた**下流の手順書は転換を知らない**。 誰も見ないまま生き残り、 次にその手順書を読んだ者が**旧規則を正しく適用する** — 従順であるほど確実に間違える。

- 実例: 「電子印影は受け付けられない、 実押印せよ」 という組織固有の運用が転換され「本人の認印は画像印影で可 (紙で出す場合)」 になった。 転換は正本と関連 3 doc には配られたが、 **別 project の手順書 1 本には配られなかった**。 5 週間後、 その手順書を読んで書類を作り、 **押印欄が空のまま完成**した (= 依頼者に指摘されるまで気づかない)。
- 同日の対照例: 別の規則転換では旧文言の literal を全 repo grep して 4 use-site を掃討した → 事故なし。 **差は「掃討したか」 だけ**。

⚠️ **掃討面は散文 doc だけではない** (= 2026-09-02 に 3 件): **code-as-SoT を名乗る script の docstring** (= 実装は新しい手順に直っているのに docstring が旧手順を説明していた)、 **skeleton / default 値** (= 新規 file の雛形が旧い定数を hard-code し、 毎回手で直す運用になっていた)、 **機械照合の spec** (= 規則を機械が読む面ゆえ露出が最も高い) も規則面である。 「doc を直した」 で完了にしない。

**規律**: supersede した瞬間に、 **旧規則の literal を全 repo grep して掃討する**。 転換の記録先を増やすのではなく、 旧規則の生存を消す。 掃討できない (= 歴史として残す) ものには「旧運用」「〜まで」「supersede 済」 の marker を必ず付ける — marker の無い旧規則は現行規則と見分けがつかない。

#### <a id="detector-watches-only-the-new-rule"></a>20.5.1 検出器の非対称: 重複は見ているが、生存は見ていない

SoT drift の検出器は **「現行規則が home 外に重複していないか」** を見る。 これは **supersede に対して構造的に無力**である:

- 旧規則の生存は**重複ではない** — 現行規則の anchor 語を含まないので、 anchor 検出には**原理的に映らない**。
- しかも旧規則は「正しく書かれた規則」 の見た目をしている。 人間の目にも留まらない。

∴ 検出器を持つなら **旧規則の literal (= superseded token) も登録し、 それが「規則が書かれる面」 (= 手順書 / 規約 / 様式 spec) に現れたら flag する**。 歴史記録 (= task 台帳 / 受信記録 / plan) は scan 対象から外し、 window 内に歴史 marker があれば flag しない — この 2 つで false positive はほぼ消える。 実装は 20 行程度で足り、 登録した当日に実データで真陽性を 1 件出した (= 別 project の様式 spec に残っていた旧規則)。

### <a id="provisional-value-freeze"></a>20.5.2 暫定値は「確定した瞬間」 に置換されないと、書類に嘘として残る

規則だけでなく**数値**にも同じ失効が起きる。 しかも数値の場合、 暫定値には **必ず出所がある** (= 申請額 / 制度の上限 / 見積り) ので、 書かれた時点では**正しい**。 腐るのは「確定値が別に生まれた」 瞬間で、 それを書いた doc は何も知らない。

観察 2 型 (2026-09、 どちらも研究費書類):

- **上限値が実額の欄に居座る**: 受給額の欄に「**制度の公募上限**」 が書かれたまま残る。 交付決定 (= 実額) が出た後も置換されず、 別の申請書の「研究費取得状況」 欄へ**過大申告**として転記されかける。
- **暫定額ベースの派生値が更新されない**: 「費目間流用の承認不要枠 = **応募額**の 50%」 と書いた数値が、 交付決定で総額が下がった後も据え置かれる。 **過大枠を信じて流用すると事前承認の手続漏れ** (= 補助金の手続違反) になる。 ⚠️ その doc は「**確定額が出たら再計算**」 と自分で書いていた — 指示は landing したが、 実行されなかった。

⚠️ 具体の金額は**個人層/案件 repo 側**に置く (= 本 doc は public。 金額そのものは pattern の理解に不要)。

**規律**:

1. **暫定値には出所と失効条件を同じ行に書く** (= 「〈値〉 (= **応募額**ベースの暫定。 ⚠️ 交付決定が出たら要再計算)」)。 出所を書かない数値は、 後から見て確定値と区別できない。
2. **確定イベント (= 採択 / 交付決定 / 契約) を処理する turn で、その値から派生した全数値を grep して置換する** — 差分 doc に「決定額 = N」 と追記するだけでは足りない (= [§20.5](#supersede-completion) の数値版)。
3. **「上限」 と「実額」 を同じ欄名で持たない**。 上限は制度の属性、 実額は自分の属性で、 混ぜると転記のたびに賭けになる。

### <a id="enumeration-staleness"></a>20.5.3 散文に焼いた「個数」 は、本文が伸びた瞬間に嘘になる

「**8 kernel**」「**3 つのルール**」「回避 (**2 択**)」「applications/ (**現状 空**)」 — summary・見出し・index に書かれた**数や状態の要約**は、 本文に項目を足す作業では更新されない (= 足す側の関心は本文にある)。 2026-09-02 の 1 日で **5 件**見つかった。

害は「数が違う」 ことではなく、 **読者が列挙を閉じたものとして扱う**ことにある: routing index の「8 kernel」 を見た session は §10-12 を規約の外だと判断し、 「回避 2 択」 を見た session は 3 番目の経路を検討しない。

**規律**: **数を書かない** (= 「主な kernel」「以下の経路」) か、 **生成する** (= index を本文から自動生成する)。 どうしても書くなら **本文に項目を足す操作と同じ commit で数を直す**のを機械 gate にする。 ⚠️ 「現状 空」 のような**状態の要約**も同類 — 状態は必ず変わるので、 doc に焼いた瞬間から腐り始める。

### <a id="derived-value-beside-inputs"></a>20.5.4 派生値を入力の隣に書くなら、 書く時に計算する — 並べた日付と期間は最初から合っていないことがある

[§20.5.2](#provisional-value-freeze) と [§20.5.3](#enumeration-staleness) は、 **入力が後で変わって**派生値が嘘になる型だった。 もう 1 つ、 **書いた時点で合っていない**型がある: 期間 (「N ヶ月」) や窓 (「起点の X 日前 〜 Y 日後」) を、 それを決める値 (日付の範囲・例の日付) と同じ段落に並べるとき、 派生値を計算せずに書く。 並べてあるので検算はできるが、 読む人も写す人も計算しない。

観察 (2026-09-14):

- **1 回の計算違いが、 同じ commit で 6 箇所に入る**: 「13 ヶ月」 と、 同じ文の 2 つの日付 (差は 35 日)。 RCA を層1 に上げた commit で、 2 つの doc の 6 箇所 (実例の見出し・本文・根本因の説明) と commit message に同じ誤りが書かれ、 111 日後の別の sweep まで残った。
- **窓の前後が逆**: 窓を「X 日前 〜 Y 日後」 と書き、 すぐ後の例の日付は「Y 日前 〜 X 日後」 の窓になっていた。 どちらが正しいかは実装の比較式で決まった (例の日付と別 file の記述が正しく、 窓の説明文が逆)。
- 期間語と日付の範囲が同じ段落に在る組を、 公開 2 repo と個人層 1 repo の追跡 file で走査すると 8 組。 上の窓の 1 組が本物で、 1 組は相対の offset (「今日 −2 日」) の誤検出だった。 「13 ヶ月」 の 2 file は走査の前に直していたので、 直す前の版に当てて 2 組とも拾うことを陽性対照にした ([§8.43](#sweep-null-needs-per-form-control))。

**規律**:

1. **派生値を入力と同じ段落に書くなら、 その場で計算する** (日付の差、 窓の端点)。 概算なら「約」 を付け、 少なくとも桁を合わせる。
2. **実例を別の doc・commit message・SESSION に写すときは、 派生値を写さず入力から計算し直す**。 写しはどれも「元にそう書いてある」 で正しく見える。
3. **食い違いを直すときは、 どちらが正しいかを一次記録で決める** (`git log -S` で書かれた commit と周りの日付、 実装の比較式)。 もっともらしく見える側に合わせない。
4. sweep の道具 = [`scripts/check-duration-beside-dates.py`](../scripts/check-duration-beside-dates.py) (on-demand。 日付 1 つに「N ヶ月後」 を付けた形は圏外、 相対 offset の誤検出があるので CI の gate にはしない)。

### <a id="premise-expiry-scope"></a>20.4 適用範囲・関連

- 適用が濃い領域 = **費用・所属・役職・制度・版**が規則の前提になっている運用 doc (= 事務手続き / 承認フロー / 様式の定数 / 対外文面の定型)。 技術 doc でも「この設定は依存ライブラリ v1 系での話」 型で同型。
- [§8.22 (= 失効型〆切)](#lapsing-deadline) が **義務の期限切れ**を扱うのに対し、 本 § は **規則の前提切れ** — 期限は書かれているが前提は書かれていない、 という非対称が本 § の核。
- [§2.4 (= errata marker)](#errata-on-preserved-records) は「誤りだった記述」 の扱い、 本 § は「当時は正しかったが前提が消えた記述」 の扱い (= 訂正でなく失効)。

---

## <a id="rule-variant-drift"></a>21. 同一 rule の variant (言語別・媒体別) は片方だけ更新され silent に stale 化する

### <a id="variant-drift-observation"></a>21.1 観察 pattern

同じ依頼・同じ手順の **variant** (= 言語別 template / 対象者別の長短版 / 媒体別 〔mail・web・紙〕 の文面) を人手で複製して持つと、 規約が更新されたとき **primary variant にしか更新が効かない**。 secondary variant は「無い」 か「古い」 のどちらかになり、 どちらも **使う瞬間まで検出されない**:

- **variant が無い場合**: 使う側は毎回ゼロから起草する → 規約で足したはずの項目が個別起草に依存して落ちる (= 実害: 依頼 mail の英語版が存在せず、 和文版に追加済みの項目 1 つが英語話者の回で丸ごと落ち、 下流の成果物の選択肢が 1 つ失われた)。
- **agent 別の写しも variant**: 同じ規約 file を別の agent 用の入口として丸ごと写し、 「片方を直したら両方直す」 と注記する形。 注記は carrier ではないので片方が古くなるうえ、 **写しを製品名の一括置換で作ると、 変数のつもりでない語まで書き換わる** — 実測では依存先の repo 名が置換され、 存在しない repo を指す案内が複数箇所残っていた (= 置換の対象は「この file はどの agent 向けか」 だけのはずが、 同じ綴りの固有名詞を巻き込む)。 入口が要るだけなら写さず、 読めと言うだけの薄い入口にする (層1 の入口契約と同じ形)。
- **variant が古い場合**: 旧運用の値が生き残る ([§20 (= #premise-bound-rule-expiry)](#premise-bound-rule-expiry) と合流)。

⚠️ **この drift は「重複を作るな」 では防げない** — variant は正当な重複 (= 言語が違えば同じ文字列は使えない) なので、 [§2 (= #no-duplicate-rules)](#no-duplicate-rules) の削除方針では解けない。

### <a id="variant-drift-remedies"></a>21.2 3 択 (強い順)

1. **variant を持たない**: primary だけを保守し、 使う瞬間に翻訳・変形する (= 変形が機械的で安価な場合の第一選択)。 保守対象が 1 つに保たれる。
2. **primary から生成する**: variant を生成物と宣言し、 手編集を禁止する (= [§2.5 (= #sot-duplication-trichotomy)](#sot-duplication-trichotomy) の design-out)。 生成できるのは構造が同型な variant に限る。
3. **parity gate を置く**: variant を人手で持つことを認め、 **primary の各項目に対し「variant へ反映済 / 意図的に非対象」 の判断を強制する gate** を機械化する。 落とし忘れが gate の失敗として顕在化する (= 「反映漏れ」 を「未判断」 に変換するのが要点)。 判断そのものは人間に残る。

### <a id="variant-drift-when"></a>21.3 判別と由来

- **判別**: 「同じことを言う文面・手順が 2 つ以上あり、 片方を直したとき他方を直す義務が *人間の記憶にしか無い*」 なら本 §。 gate も生成も無いなら、 その variant は既に stale だと仮定して先に照合する。
- **由来 (2026-09-02)**: 1 file 内に 和文の完全版 + 英文の旧サンプルのみ という非対称が存在し、 (a) 和文にだけ追加された項目が英語回で落ちた (= variant 不在)、 (b) 英文サンプルが旧運用のまま残置 (= variant 陳腐化) の 2 形が同時に観測された。 同 owner の別軸には **(3) parity gate が既に実装済**の前例があり (= 正本 doc の全 section に「配布する / しない」 の判断を強制する gate)、 remedy 3 の実効性はそちらで実証されている。 instance は個人層・共有 project 側に残置 (= kernel-up / instance-down)。

---

## <a id="silent-probe-false-healthy"></a>22. 安全網が自分で使う probe の失敗は、健全と同じ姿の答えに化ける

### <a id="false-healthy-observation"></a>22.1 観察 pattern

同期用の並列 probe (= 各 item に per-item timeout、 全体に watchdog) で、 失敗を `|| true` で潰していた。 打ち切られた item は**手元の状態が更新されないまま**判定へ渡り、 「差分 0 = 同期済み」 に見えた。 結果、 その item は自動処理もされず、 「手当てが要る」 一覧にも載らず、 完全に silent。 さらに悪いことに **差分が溜まるほど probe が重くなり、 重いほど打ち切られ、 打ち切られるほど溜まる**という正のフィードバックが回る (= 放置するほど自力では直らなくなる)。

一般形: **失敗時の値が「異常値」 ではなく「健全な状態と同じ形」 になるとき、 silent failure は false healthy (= 積極的な誤報) に化ける**。

| probe | 失敗時に返る値 | それが偽装する「健全」 |
|---|---|---|
| 同期状態の取得 | 古い手元の状態 → 差分 0 | 「同期済み」 |
| 検索 / query | 0 件 | 「該当なし」 |
| 一覧の列挙 | 空 list | 「問題なし」 |
| 版の照合 | 取得できず skip | 「一致」 |
| 外部 CLI での検証 (構文検査 / lint / 変換) | CLI 不在で skip | 「検査に通った」 |

「エラーで落ちる」 失敗は気付けるが、 この class は**沈黙が正常の顔をしている**ので、 検出器が何本あっても素通りする。

### <a id="false-healthy-why"></a>22.2 なぜ安全網の内側で起きるか

安全網を書く人は「**網が見張る対象**の失敗」 は丁寧に扱う。 一方「**網が自分で使う道具**の失敗」 は fail-open の名目で潰しやすい — session や job を止めないことが最優先だからだ。 だが **fail-open と silent は別物**で、 「止めない」 と「黙る」 を混同すると、 網の停止だけが誰にも見えなくなる。

同じ file の中でこの非対称が同居することがある: 後から足した sub-payload は guard 付きで呼ばれているのに、 最初からある主 payload だけが素通しのまま、 という形。 **原則が既に存在していても、 それが書かれる前からあるコードには適用されていない** (= §12 の暗黙 scope と同型)。

さらに、 人間 / LLM 側には「単一情報源の null を不在の証明にするな」 という規律が確立していることが多い。 それでも**機械側の probe に同じ規律が適用されているとは限らない** — 規律は人間の判断にだけ効くものとして書かれがちで、 script の中の `|| true` までは届かない。

### <a id="false-healthy-pattern"></a>22.3 pattern

1. **「成功を記録」 の向きにする** — 打ち切られた子プロセスは自分の失敗を書けない (= kill されたら何も残らない)。 「失敗を記録」 は kill に弱い。 **成功時だけ marker を残し、 marker の不在で失敗を検出**すれば、 どんな殺され方をしても拾える。
2. **測れなかったことを、測った結果と同じ型で表さない** — 「差分 0」 と「差分を測れなかった」 を同じ 0 に畳まない。 畳むと下流は永久に区別できない。
3. **fail-open は報告付きで** — 続行はする。 ただし「この項目は測れなかった」 を出力に残す。 これで「動いて 0 件」 と「動かなかった」 が分かれる。
4. **悪循環の有無を見る** — 失敗が次の失敗を招く構造 (= 溜まるほど重くなる類) なら、 放置は指数的に悪化する。 閾値の調整は、 まず 3 を入れて「実際どれだけ打ち切られているか」 を観測してから決める (= 観測なしの閾値いじりは §9.8)。
5. **悪循環は閾値では解けないことがある — 「呼び出し側が待つ時間」 と「仕事が要する時間」 を分ける** — 打ち切りが対象を育てる構造では、 閾値を上げても「上げた値 < 育った仕事」 になれば同じ所へ戻る。 しかも呼び出し側が待てる上限 (= 全体 watchdog / 起動の体感) が別に在るので、 閾値はそこまでしか上げられない。 **打ち切ったら、 呼び出し側は待たせないまま同じ仕事を裏で完走させる経路**を用意すると、 仕事の大きさに依らず次回は差分ゼロになる (= 呼び出し側の latency は不変のまま悪循環だけ切れる)。 二重起動を防ぐ lock と、 置き去り lock の stale 判定を同時に置く。

### <a id="false-healthy-when"></a>22.4 判別と由来

- **判別**: 「**この probe が失敗したとき、 出力は健全時と見分けがつくか?**」 を 1 問。 つかないなら本 §。 特に timeout / watchdog / `|| true` / `2>/dev/null` を書いた行の隣で問う。
- **由来 (2026-09-09)**: layer-3 の session 開始 hook で、 3 つの repo が 39 / 119 / 238 commits 遅れたまま数日〜数ヶ月放置され、 **まったく別目的の検査 (= 派生物と正本の整合 gate) がその古い手元を読んで落ちたことで偶然発覚**した。 3 つとも clean で、 その hook が持つ「clean なら自動同期」 の条件を満たしていた = **機構は在ったが、 その手前の probe が黙って死んでいた**。 併発した第 2 の穴は表示面の非対称 (= 「手当てが要る」 一覧が、 一部の frontend では honor されない経路にしか出ていなかった) で、 これは §12 の暗黙 scope の表示版。 再発防止は pattern 1 + 3 を実装し、 **事故構造そのもの (= 対象は進んでいるのに手元では差分 0 に見える状態で probe を失敗させる) を再現する test** を置いて、 旧実装で FAIL することを確認した (= §9.8 の「単一観察から飛ばない」 に対する、 最小の実証)。 instance (marker 実装 / 表示配線 / test) は個人層に残置 (= kernel-up / instance-down)。
- **由来 (2026-09-10、 同型の第 2 例)**: JS を生成する層の selftest が、 生成物の構文検査を `shutil.which("node")` の有無で分岐し、 不在時は「SKIP」 と印字して **0 (= 問題なし) を返して**いた。 呼び出し側は返り値を合算するだけなので、 selftest は「全項目 pass」 の顔をしたまま**構文検査が一度も走っていなかった** (node は在ったが PATH に乗っていないだけ = nvm 配下)。 対策は 3 つとも 22.3 pattern 3 の形: ① 探索を PATH だけにしない (PATH → nvm → homebrew と実体を探す) ② skip は**理由の文字列**を返す (= 「空 list = 問題なし」 と型で区別する) ③ 呼び出し側はその文字列を fail として扱う。 ⚠️ 同じ file の中で**検査の入力集合**にも同型の穴が空いていた — 後から足した分岐の生成物が構文検査の対象 list に入っておらず、 壊れた出力を手で叩くまで気付けなかった (= **機能を足したら検査の入力も足す**。 22.2「原則が既に存在していても、 それが書かれる前からあるコードには適用されていない」 が、 コードでなく**検査対象 list** に現れた形)。
- **由来 (2026-09-12、 同型の第 3 例 = 逆向き)**: 見送り close の hygiene gate で、 「完了確認の probe を実行してよいか」 を決める関数が、 lint 関数の返り値 `[]` を「clean = 実行してよい」 と読んでいた。 ところが lint 関数は**対象外 (= 既に close した entry) にも `[]` を返す**。 結果、 close した entry の probe が dashboard に毎回出続けた。 第 1・2 例は「失敗 → 健全の顔 → 沈黙」 だったが、 これは「対象外 → 問題なしの顔 → **余計に動く**」 向き。 核は同じ **1 つの空値に 2 つの意味 (clean / 対象外) を畳んだ** こと (= 22.3 pattern 2)。 対策 = 呼び出し側でも範囲 (open か) を明示に判定し、 閉じた 2 status の test を足した。 instance は個人層の gate script に残置。
- **由来 (2026-09-12、 22.1 で予告した悪循環が実際に回った)**: 同じ同期機構で、 論文 PDF を commit する共同研究 repo が 4 日で 137 commits / PDF 234 MB 溜まり、 8 秒の per-item timeout に対して実測 32 秒 = **毎回 8 秒で打ち切られ、 打ち切りは部分成果を残さないので進捗ゼロ**、 その間に対象が育つ、 を数日繰り返していた (= 人が手で叩くまで解けない)。 pattern 3 (= 報告付き fail-open) は既に入っていたので「未完了」 とは毎回出ていた — つまり **検出はされていたが機構が自力で回復できなかった**。 kernel = **報告できることと回復できることは別**。 閾値を上げる案は成立しない (実測 32 秒 > 呼び出し側が待てる上限 25 秒) と分かり、 pattern 5 を実装した (= 打ち切った後に detach した同じ仕事を投げ、 次回は差分ゼロ)。 instance は layer 1 の同期 script に在る。

- **由来 (2026-09-19、 同型の第 4 例 = capability probe)**: 常駐 server を launchd に入れる installer が、 「この CLI は命名 flag に対応しているか」 を `<cli> <subcommand> --help` の出力を grep して決めていた。 その CLI は**認証が無いと `--help` でも 1 文字も返さず即 exit する**ので、 認証が切れている間に installer を再実行しただけで grep が全て外れ、 **命名が黙って落ちた構成が書き込まれた** (= 同一 host に複数アカウントの server を並べる構成で、 picker に同名が並んで区別できなくなる)。 第 1〜3 例と同じ **1 つの空値に 2 つの意味 (「flag 非対応」 と「今この CLI を動かせない」) を畳んだ** 形だが、 結果が「沈黙」 でも「余計に動く」 でもなく **silent な機能後退** である点が新しい — 出力は壊れず、 install は成功で終わり、 差は次に picker を見るまで現れない。 対策は 22.3 pattern 2 + 3 を capability 判定に当てる形: ① probe の出力が**空かどうか**を先に分岐し、 空を否定の答えに変換しない ② 空のときは既存の構成 (= 以前 probe が成功した証拠) を引き継ぎ、 環境依存の部分だけ現在値で評価し直す ③ どちらの経路を通ったかを必ず警告として出す (= 黙って落ちない)。 ⚠️ 一般形として、 **capability probe は「対応/非対応」 の 2 値ではなく「対応/非対応/判定不能」 の 3 値**で、 判定不能を非対応に畳むと、 環境が一時的に劣化した瞬間に構成が恒久的に劣化する。 `--help` / `--version` / `which` のような「軽いから安全」 に見える probe ほど、 実行可能性そのものに依存していることが見落とされる。


---

---

## <a id="required-field-fabrication"></a>23. 必須にした field は、 値が無いとき捏造される — 「無い」 を機械可読にする第三の状態を用意する

### <a id="fabrication-observation"></a>観察

監視機構が item を拾う条件に field X を要求すると、 **X が本当は存在しない item にも X が書かれる**。 書き手 (人でも LLM でも) は「拾われないと困る」 側の誘因を持つので、 X を捏造する。 規約が明示的に「自己設定で可」 と許すと、 捏造は規律違反ですらなくなる。

実例 (2026-09-09): 期限つき義務を surface する機構が **deadline を持つ entry しか拾わない**設計で、 規約が「本人操作が要る item には deadline を必ず添える (自己設定で可)、 無 deadline は機構の射程外」 と定めていた。 結果、 **本来いつやってもよい作業に、 拾わせるためだけの日付**が入った。 実測すると該当 6 件中 3 件が捏造で、 **本物の失効型期限 1 件がその 3 件と並んで最上位 group に置かれていた**。 owner が「なんで期限とかあるの?」 と問うて初めて表面化した (= 機構の内側からは、 捏造も本物も同じ「日付を持つ item」 にしか見えない)。

### <a id="fabrication-why-bad"></a>なぜ悪いか

捏造された X は **本物の X の信号を薄める** (= 狼少年)。 機構は X の**有無**で拾うが X の**出自**を知らないので、 本物と捏造を同じ強さで表示する。 表示が強い経路ほど (最上位 group / 毎 session 再掲 / OS 通知) 劣化が速い。

[#surfaced-not-consumed](#surfaced-not-consumed) (= 壁紙化) の**上流**にある別の型: 壁紙化は「毎日出るから見なくなる」、 こちらは「**急がないものが緊急の顔で出るから、 緊急の顔を信じなくなる**」。 前者は cadence の問題、 後者は **severity の出自**の問題。

### <a id="fabrication-remedy"></a>対策: 出自を宣言する第三の状態

field を optional に戻すと item が radar から消える (= 機構が必須にした元の理由が再発)。 正しいのは **X の出自を宣言する marker** を足すこと:

| 状態 | 意味 | 扱い |
|---|---|---|
| X あり・無記載 | 外部から課された値 | 従来どおり loud |
| X あり・**自己設定 marker** | 拾わせるために置いた値 | **拾うが緊急の顔をさせない** (= 表示 tier を下げ、 強制表示・通知から外す) |
| X なし | 値が存在しない | 従来どおり射程外 |

設計要件 4 つ:

1. **無記載 = 従来の意味**。 既存データの一括移行を不要にする (= 移行を要求する設計は、 移行が終わらないまま両義的な状態が続く)
2. **loud 側を default**。 迷ったら marker を付けない — 誤った marker は「静かになる」 方に倒れるので、 default は安全側に置く
3. **「静かにする」 であって「消す」 ではない**。 named 表示は残す。 消すと「radar から消える」 という元の問題に戻る (= 目的は緊急の顔をやめさせることであって、 item を隠すことではない)
4. 本物と捏造の判別が自然言語判断なら **機械化不能と declared** して自己申告に留める。 marker の正しさを検査する機構を作ろうとしない

**複合 record は field ごとに第三状態を持つ**: identity stamp や provenance のように複数 field を束ねる record で、1 field が取れないことを理由に record 全体を省略しない。既知の field はそのまま出し、未知の field だけを `unknown` 等の機械可読値にする。全-or-nothing にすると「account が取れないから host/session も出ない」という別の false-empty を作り、既知情報まで失う。

**upstream contract が保証する field の `unknown` は無言で正常扱いしない**: runtime が値を供給すると宣言しており、独立した同値 source でも値を確認できる field の欠測は、通常は対象の性質でなく transport / wiring の故障である。安価で対象を一意に絞れる fallback を先に使い、それでも欠ければ `unknown` を明示して故障をsurfaceする。ただしhook無効化・未対応経路・local state障害まで不可能とは限らないため、記録の縮退だけで元のactionを止めない。blockは、そのfield欠測によりaction自体がunsafeまたは不正になる場合に限る。fallbackが履歴や個人情報を広く探索しないよう、record identityの完全一致とread-only schema probeを条件にする。

<a id="shared-field-resolver"></a>**同じfieldを複数consumerが使うなら、解決順とvalidationはshared resolverが一つだけ所有する**: stamp、cache writer、Git hookなどが各自で「event → explicit override → cache → fallback」の順を再実装すると、source追加・`unknown`の扱い・文字種validationの変更が一部だけに入り、同じsessionをconsumerごとに別値へ解決する。上層のresolverを単体テストし、下位adapterはsession idとeventを渡して結果を表示または保存するだけにする。consumer固有なのは最終action (印字、cache write、trailer transaction) に限る。

### <a id="fabrication-detection"></a>適用の見分け方

新しい必須 field を設計するとき、 あるいは既存機構の noise を疑うときに問う:

> **この field、 値が無い item に対して書き手は何を書くか?**

- 「何か適当に埋める」 → 本 pattern。 第三の状態を用意する
- 「書かずに済ませる (= item が機構から消える)」 → 別の問題 (= 拾い漏れ)。 [#receiverless-handoff](#receiverless-handoff) 系

⚠️ 捏造は **機構が正しく動いている間は不可視**。 気づく契機は「なぜこの値があるのか」 という**外部からの素朴な問い**であることが多い (= 内側の人間も LLM も、 規約に従って埋めたので疑わない)。 owner の「これ何で要るんだっけ?」 を detector 扱いする点は [#premise-bound-rule-expiry](#premise-bound-rule-expiry) と同じ。

---

### <a id="coarse-entry-hides-its-contents"></a>8.40 粗い 1 件が中身を隠す — 「埋まっている」 は「検討した」 ではない

集合を 1 件にまとめた entry (= session 丸ごとの予定 / 親 TODO / rollup の 1 行 / digest の 1 通) を
置くと、**その範囲を走査する側からは「もう扱い済み」 に見える**。 中身の個別要素は、 一度も候補として
検討されないまま消える。

**観察 (= 実測)**: 学会の聴講計画で「空き時間を埋める」 順序で候補を出していたところ、
session 丸ごとを 1 event にした長い block が置いてある窓が gap 計算上 busy になり、
**その窓の中の個別講演が profile 照合の射程から丸ごと落ちていた**。 依頼者が「重複を気にせず
内容で埋めて」 と言って初めて発覚した。 同型は digest でも起きる — 「日時つき・本人が出る
常設の集まり」 の案内が、 高 volume な案内 ML の digest 1 行に畳まれて消費されなかった。

**なぜ起きるか**: 走査側は **占有 (occupancy) を検討済みの proxy にしている**。 粗い entry は
占有としては真だが、 検討済みとしては偽。 [#firing-surface-hierarchy](#firing-surface-hierarchy) が
「どこで出すか」 の話なのに対し、 これは **「何を母集団にするか」** の話で、 母集団が
自分の出力 (= 既に置いた entry) で縮んでいる。

**pattern**:

- **母集団は一次資料から取る** (= プログラム全文 / 受信 mail 全件)。 自分が既に作った entry の
  「隙間」 を母集団にしない。 隙間は結果であって入力ではない。
- 粗い entry を許すなら、 **それが集合であることを機械可読にする** (= 子要素を列挙して持つ、
  `contains: [...]` を書く) か、 **走査側が粗い entry を occupancy から除外**する。
- 「まとめる」 のは **その集合に通しで従事するという判断そのものが 1 単位のとき**だけ
  (= session に通しで座る / 親子が同一の意思決定)。 便宜でまとめない。
- 粗さを解消するとき、 **元の 1 件と展開した N 件を同時に置かない** (= 二重表示。
  展開したら元は畳む。 ただし畳む操作が選択肢を減らすなら user の判断)。

**適用の見分け方**: 「この範囲はもう見た」 の根拠が **entry の存在**なら該当。
根拠が **一次資料を走査した記録**なら該当しない。

### <a id="detector-config-must-be-derived"></a>8.50 検出器が読む「人が書く一覧」 は育たない — 設定も SoT から導出し、 追随と死活を別々に検査する

検出器の多くは **config file に置いた一覧** (= 禁止 term / allowlist / 監視対象 / 名簿) を読む。
機構を作った turn には一覧も埋まっているが、 **その後に増える対象は誰も足さない**。
対象が増える経路 (= 新しい同僚・新しい repo・新しい様式) と、 一覧を編集する経路が別だからで、
間を繋いでいるのは人の記憶だけになる ([#human-memory-not-a-carrier](#human-memory-not-a-carrier) の config 版)。

**観察 (= 実測)**: 公開 repo の pre-commit に literal 照合の段が配線済みだったのに、 その一覧に
**守るべき class の項目が 1 件も入っていなかった**。 実在の氏名を公開 repo に stage して実 hook を
走らせると rc=0 で通った。 一覧は gitignore された machine-local の手書きで、 空でも hook は
`[skip] ... not found or empty` の 1 行を出して素通りする。 **その 1 行は毎 commit 出るので
noise に紛れ**、 「配線済み」 という認識だけが残っていた。

**なぜ気づけないか**: 「一覧が空」 は **「対象が無い」 と同じ顔**をする。 ARMED / NOT ARMED /
対象外 の 3 状態を出す設計 ([confidential-repo-boundary.md](../conventions/confidential-repo-boundary.md)) でも、
**空と対象外を同じ経路で表示すると区別が消える**。 §22 の「probe の失敗が健全と同じ姿になる」 の
config payload 版で、 §8.34 が分岐 (= marker の有無) を扱うのに対しこちらは**中身**を扱う。

**pattern**:

- **一覧は SoT から生成する**。 対象の実体がどこかに台帳としてあるなら (= 連絡先 doc・repo 一覧・
  メンバー名簿)、 それを読んで生成する。 手で書くのは生成できない例外だけにして、 marker で分ける。
- **検査を 2 つに割る**: ① **追随** (= SoT の項目が一覧に全部あるか。 対象が増えた瞬間に赤くなる)
  ② **死活** (= その一覧で実際に検出が起きるか)。 ①だけだと配線切れに気づけず、 ②だけだと
  一覧が痩せても緑のままになる。
- **死活は実測で持つ**。 一時の環境を作って本物の経路を通し、 **検出されること**と
  **無関係な入力は通ること**の両方を見る (= 片方だけでは「全部止める壊れ方」 を緑と誤認する)。
- **生成物を repo に置かない選択ができる**。 一覧の中身が機密なら、 生成物は ignore したまま
  「各機で生成し直せば同じ網になる」 形にすれば、 literal を撒かずに cross-machine 性が保てる。
- **検査の出力に項目そのものを書かない** (= 検査の log が leak 経路になる)。 件数と mask を出す。
- **除外一覧 (stoplist) を足す操作は網を縮める**。 足す条件を config に明記し、 誤検出が出るたび
  反射的に足さない ([#semantic-detector-ack-ratchet](#semantic-detector-ack-ratchet) と同じ ratchet)。

**適用の見分け方**: 「この検出器は何を読んで判定しているか」 を問い、 答えが**人が編集する file**なら該当。
その file に**最後に項目が足されたのはいつか**を見る — 機構を作った日のままなら、 もう死んでいる。

### <a id="flagged-text-is-not-the-defect"></a>8.51 検出器に鳴らされた文が欠陥とは限らない — 規約どおりの使用なら、 直すのは検出器で、 原文ではない

文字列で照合する検出器 (正本の重複検出・禁止語・用語の揺れ) は、 **規約の複製**と**規約どおりの使用**を
区別できない。 呼称・訳語・定義語を目印にすると、 その語を正しく使った文が全部鳴る。 鳴った文を
「直す」 と、 書き手の文 (記録・原文の移設・他人の文章・例文) が**道具を黙らせるために**書き換わる。
検査は緑になり、 失われた文は見えない。

- **順序を固定する**: ① その行は複製か使用かを判定 ② 使用なら**本文には触らず**検出器の設定を直す
  (目印を「規約を定義する文」 の言い回しへ移す。 使用箇所を除外一覧に並べるのは劣後 = 使う場所が
  増えるたびに一覧も増える) ③ 複製なら home 外の記述を消して参照にする。
- **修正依頼は内容の判断を委ねていない**: 「この指摘を直して」 は検出器との不整合の解消の依頼で、
  文の中身の是非 (例文が適切か、 公開してよいか) の判断は含まない。 中身に懸念を持ったら、 それは
  別の問いとして書き手に出し、 修正に混ぜて実行しない。 原文であることの確認は「移設した verbatim」 の
  ような明示の印に頼らない — 人が書いた文は原則すべて原文として扱う。
- **検出器の対処文が行動を決める**: 修正する側は finding の文面をそのまま手順として読む。 対処文が
  「削除する / 参照を足す」 しか示さないと、 使用の場合でも本文が書き換わる (実測)。 判定を対処文の
  先頭に置く ([#firing-surface-hierarchy](#firing-surface-hierarchy) と同じ「消費点に routing を運ぶ」)。
- **目印を移したら両向きを実測する**: 定義する文を home 外に置いた一時の foil で鳴ること、 同じ foil の
  語の使用では鳴らないこと ([#detector-config-must-be-derived](#detector-config-must-be-derived) の死活と同じ形)。
  除外一覧を削った後に finding が 0 なのは、 それだけでは「効いている」 と区別できない。

**適用の見分け方**: finding を消すための変更が**検出器の側でなく、 鳴った文の側**に入ろうとしていたら止まる。

### <a id="literal-anchor-detector"></a>8.52 目印の文字列で重複を探す検出器は、 目印と「参照あり」 の判定の両方が黙って死ぬ — 登録簿そのものを機械で点検する

「規則の正本は 1 か所、 他所は参照だけ」 を守らせる安価な検出器は、 topic ごとに**目印の文字列**
(= 正本にある語句) と **「参照あり」 とみなす文字列** を登録し、 正本の外で目印が参照なしに出たら
鳴らす。 意味の重複は文字列照合で捕まえられないので、 この形が現実的な下限になる。 ただし登録簿を
人が書く限り、 鳴るはずの場所で**黙って鳴らなくなる経路が 4 つ**あり、 どれも finding 0 の顔をする
(= [#detector-config-must-be-derived](#detector-config-must-be-derived) の「空は対象が無いと同じ顔」 の同型)。

| 死に方 | 形 | なぜ見えないか |
|---|---|---|
| 目印が語そのもの | 規約が定める呼称・訳語・定義語を目印にする | 規約どおりに**使った**文が全部鳴り、 使う側を除外一覧に並べて抑える → 除外した場所の本物の書き写しも見えない |
| 目印が参照判定に含まれる | 目印が節名・topic 名・参照文字列と同じか、 それを含む | 書き写した瞬間に「参照あり」 になり**永久に鳴らない**。 登録した日から死んでいる |
| 参照判定が広すぎる | 一般語 (節番号・repo 名・部署名・機能名) や、 同名 file が多い名前 (`README.md` 等) を参照とみなす | 書き写しの近くにその語があるだけで黙認される。 別 file・別 repo の同名 file の話でも通る |
| 目印が正本から消える | 正本の文言が書き換わり、 登録簿が古いまま | 目印が複数あると、 残りが在る間は警告も出ない |

**対策 (決め打ちの語リストを持たずに回す)**:

1. **目印は「規約を定義する文」 の固有の言い回しに置く** (= その語を定義している文。 規約に従う文書が
   規約に触れるときに使う語句は目印にしない)。 判断の問い = 「規約に従っている file にも、 この語句は出るか」。
2. **参照判定は正本と結び付く形だけにする**: 正本の file 名 (同名 file が走査対象に 1 つしか無いときだけ
   bare な名前を認め、 複数あれば「親 dir/名前」 か、 正本と同じ repo の中か、 窓に repo 名がある場合だけ)、
   節の anchor id、 topic 名。 同名かどうかは**走査したファイルの名前を数えて**決める (一覧を持たない)。
3. **登録簿を機械で点検し、 登録時と定期実行の両方で回す**。 4 つの点検はどれも構造か実データで判定できる:
   - **鳴るか**: 正本と無関係な場所に目印だけの 1 行を置いた仮想 file で、 実際に finding になるか (disk に書く必要はない)。
     参照判定に目印が含まれていればここで落ちる。
   - **正本に在るか**: 目印を 1 つずつ正本と照合する (全部消えたときだけの警告にしない)。
   - **語に見えるか**: 識別子の形 (空白を含まない ASCII・code 記号・拡張子つき) でない目印が、 正本の中で
     何度も使われている (定義文なら正本に 1 回、 語は正本自身が語彙として繰り返す、 実測)。
   - **参照が広すぎないか**: 参照文字列が正本と結び付かず (file 名の stem・節名・topic 名・正本内の anchor id を
     含まない)、 走査対象の一定割合を超える file に出る。 割合は実データの分布を見て決める (実測では、
     問題の一般語は 1% を大きく超え、 正本に結び付く参照はその下にまとまっていた)。
4. **正当な例外は理由つきの承認で黙らせる**: 識別子・値・引用の目印が「語に見える」 に当たるのは避けられない。
   topic に `承認: 理由` を書いたものだけ報告から外す ([#semantic-detector-ack-ratchet](#semantic-detector-ack-ratchet))。
   読んで判断した後にだけ足す。
5. **広すぎる参照を外すと、 隠れていた書き写しが出る**。 出たものは [#flagged-text-is-not-the-defect](#flagged-text-is-not-the-defect)
   の順で「複製か使用か」 を判定し、 複製でも**本文を参照に置き換えるかは書き手の判断**として渡す (検出器の整備の中で書き換えない)。
   - <a id="pointer-needs-reader-access"></a>**「参照を足す」 を提案する前に、 その file の読み手が正本を読めるかを確かめる**: 書き写しが
     正本より読み手の広い場所 (共同編集者のいる repo、 公開 repo) にあると、 正本への参照は読めない先を指す依存になる
     ([`personal-layer.md` の depend と mention の区別](personal-layer.md#what-depend-means-structural-dependency-vs-mention))。
     書き写しの一覧を「全部に参照を足す」 で括ると、 この 1 件が混ざっていても気づかない (実測) = 1 件ずつ読み手を見る。
   - <a id="unreferenceable-copy-is-blind"></a>**参照を足せない書き写しを除外一覧で許すと、 そこは検出器の死角になる**: 正本の規則が
     変わっても鳴らない。 許すだけで終えず、 次のどれかを選んでその理由を除外の注釈に書く — (a) **書き写しを読み手に要る
     結果だけに縮める** (規則の中身 = どの field をどう扱うか を持たず、 「どこに何が載るか」 だけにする。 規則が
     変わっても嘘になりにくい) (b) **正本から生成して配る** (手の書き写しを無くす = [`shared-repo.md#l2-style-digest`](../conventions/shared-repo.md#l2-style-digest) と同じ形)
     (c) **死角として受け入れる** (正本の規則を変える人が、 除外一覧に載った下流の file を手で確かめる。 注釈にその file 名を
     書いておけば、 正本側から検索で辿れる)。 どれも選ばずに許すと、 finding 0 のまま下流だけが古くなる。

**移すときの手順の要点**: 新しい目印ごとに ① 正本の 1 行にそのまま在る ② 参照判定に含まれない ③ 仮想 file で
「定義文は鳴り、 外した語の使用は鳴らない」 の両向きを確かめる ④ 除外一覧は 1 本ずつ外して finding が増えない
ものだけ撤去する (履歴の file 形は予防として残す)。 登録簿に注釈 comment が多いなら、 YAML を読み書きし直さず
行単位で書き換え、 書き換え後に読み直して期待どおりかを照合する (読み書きし直すと comment が消える)。

**参照実装**: [`scripts/check-sot-drift.py`](../scripts/check-sot-drift.py) (scan + 点検 `audit_registry`、 registry は呼ぶ側が渡す) と
[`scripts/sot-registry-add.py`](../scripts/sot-registry-add.py) (登録前に同じ点検を通し、 落ちたら何も書かない)。
既存 topic の移し替え (目印の差し替え・参照や除外の出し入れ・承認) は [`scripts/sot-registry-edit.py`](../scripts/sot-registry-edit.py) (行単位で書き換えて comment を保ち、 書き換え後に読み直して照合する)。

**適用の見分け方**: 検出器の finding が長く 0 件のまま、 除外一覧だけが増えている。 または、 登録から一度も鳴ったことがない topic がある。

### <a id="display-cap-is-not-the-count"></a>8.53 表示の上限を件数として出す検出器は、 自分が壊れたことを隠す — 過検出は「うるさい」 ではなく「見えなくする」

finding を並べる検出器は、 出力が長くなりすぎないよう **先頭 N 件だけ表示する** のが普通。 このとき
**表示に使った N をそのまま件数として報告する**と、 次の 2 つが同時に起きる。

- **総数が常に N に見える**。 検出語や規則が汚染されて **全部の行に当たる状態**になっても、 報告は
  「N 件」 のまま。 壊れている検出器と、 少しだけ違反がある健全な検出器が、 同じ顔をする
- **真の finding が窓から押し出される**。 過検出が先頭を占めるので、 本物は表示されない。
  検出器は動いていて、 報告も出ていて、 それでも見つけたい物だけが見えない

∴ **件数は上限をかける前に数え、 切ったことが分かる形で出す** (`N 件 … (計 M file)`)。
数えると、 これまで「少し」 に見えていたものが桁違いだったことが分かる
(実測: 表示上限どおり 5 件と出ていた検出が、 数え方を直した瞬間に 3 桁になった)。

**これは「余分に検出しても害はない」 という前提を壊す。** 検出語を機械生成する側では
「拾いすぎても実在しない語だから無害、 落とすより出すほうが安全側」 と考えがちだが、
上の 2 つ目のせいで **過検出には本物を隠す cost がある**。 特に、 固有名から
**短い prefix を機械生成する**設計では、 短い prefix が普通名詞と一致する
(= 2-4 字の断片は日常語になる) ので、 stoplist で落とすのは「網を縮める」 のではなく
**「網を機能させる」** 操作になる。

**併せて 3 つ検査する**:

1. **件数の真値** — 上限の前に数える (本節)
2. **生成物の追随** — 検出語が SoT から生成されるなら、 生成物が古いと守っているつもりになる。
   「SoT にあって一覧に無い」 を鳴らす検査を別に持つ ([#detector-config-must-be-derived](#detector-config-must-be-derived))
3. **1 つの語が何行に当たるか** — 検出語ごとに対象 corpus での出現数を測り、 桁が外れた語を
   普通名詞として落とす。 落とす前に **その語が固有名を指す形 (全形・別表記) は一覧に残る**ことを確かめる
   (= 識別力を落とさずに騒音だけ落とす)

**適用の見分け方**: 報告の件数がいつも同じ数 (= 上限値) で止まっている。 除外一覧に足しても件数が変わらない。
finding の中身がいつも同じ file から来る。

origin: 公開 repo の棚卸しで、 表示上限と件数が同じ変数から作られていたために、 検出語の汚染が
「少数の finding」 として報告され続けていたのを実測 (2026-09-15 新設)。

### <a id="detector-installed-after-the-stock"></a>8.54 後から入れた検出器は、 それ以前の在庫を検査していない — 設置と同じ turn に全量を 1 回通す

差分に対して働く検出器 (pre-commit gate・保存時 lint・投稿前 check) は、 **これから足すもの**しか見ない。
既に在るものはその検出器を一度も通っていないのに、 検出器が在るという事実だけが「検査済み」 の感触を作る。

- 「入れた」 と「検査した」 は別。 設置直後の finding 0 は、 **在庫を見ていないから 0** かもしれない
- 在庫は普通いちばん古く、 規則が緩かった頃に書かれている = 違反の密度は新しい書き込みより高い

∴ **検出器を設置したら、 同じ turn に全量を 1 回通すまでが 1 単位**。 差分用の engine を使い回せることが多い
(= 全量を「全部が新規追加」 に見える形に組み替えて同じ engine に食わせる)。 通した結果は
**対象ごとに台帳へ記録し、 finding があった対象は「走査済」 にしない**
(= 直さなかった対象が静かに検査対象から外れる = [#silent-probe-false-healthy](#silent-probe-false-healthy) の同型)。

**在庫にだけ要る口**: 在庫には「見た上で残すと決めた」 ものが必ず出る (= 第三者が公開している値、
反例として意図的に載せた例、 vendor 由来の file)。 これを毎回再提示しないための受理一覧は、
**在庫の棚卸しにだけ効かせ、 差分の gate には効かせない** (= 新しい書き込みは今までどおり止める)。
受理してよいのは **token を名指しできる種類の finding だけ**で、 件数や file 名しか出ない種類
(= 固有名・非公開の識別子) は受理させない — 受理は「寝かせる」 ことなので、 寝かせてよい物を型で絞る。

参照実装 = [`scripts/scan-public-tree.sh`](../scripts/scan-public-tree.sh) (公開 repo の tree 全体を pre-commit gate の全 Tier に通す)、
規律の instance = [`conventions/confidential-repo-boundary.md#gate-installed-after-history`](../conventions/confidential-repo-boundary.md#gate-installed-after-history)。

origin: 公開 repo の gate を新設した直後に全量を通したところ、 差分 gate が素通ししていた在庫の違反が出た (実測、 2026-09-15 新設)。

### <a id="elapsed-time-urgency-inversion"></a>8.55 経過日数で強める印は、 期限の近い義務ほど弱く付く — 期限が取れる item は残り時間で印と並びを決める

未処理の item を「届いてから N 日」 で ⚠️ → 🚨 と強め、 古い順に並べる設計は、 **放置**を捕まえるには効く。
しかし**期限の短い義務**では向きが逆になる。

- 最も危ない**届いた直後**が、 無印で一覧の最下段に置かれる
- 印が強まる頃には窓が閉じている。 「強い印が N 回表示されたら止める」 型の強制 ([§8.24](#surfaced-not-consumed)) を
  経過日数の印に紐付けていると、 **窓の中では原理的に発火しない**
- 上段は「古いだけで義務でない item」 (営業・済んだ日程・報告) が占める

∴ **本文から期限の日付が取れた item は、 残り日数で印を付けて最上段に上げる**。 経過日数は期限が取れないときだけ使う。
期限の過ぎた item は「経過」 と書き、 印は強めない (= 過去の期限を 🚨 で叫ばない)。

**期限を本文から取るときの落とし穴** (いずれも実測):

1. **範囲表記の終端は締切語を持たない** — `受付期間: A ～ B` の B は「まで・締切・期限」 を伴わない。
   締切語だけを手掛かりにする抽出器は B を落とし、 時刻付きの A と B を**予定の候補 2 件**として読む。
   label を「何かをする期間」 (受付・申込・提出・入力・回答・訂正 など) に限れば、 開催期間や閉室期間を拾わずに精度を保てる
2. **引用部の古い期限を拾わない** — 返信の引用ヘッダ以降と `>` 行を落とす。 転送された本文は残す (= 転送の期限は本物)
3. **取得の段で落ちていないか** — 本文を読みに行く前に検索語 (会議・締切の語彙) で候補を絞る経路だと、
   期限語を持たない依頼は**取得すらされない**。 抽出器を直したら、 その依頼が取得の述語を通るかも確かめる
4. **抽出の述語が変わったら cache を捨てる** — message 単位で抽出結果を cache していると、 述語を広げても取得済みの item には効かない。
   捨てる判定は、 抽出の述語 (正規表現・窓の幅) から作った**指紋**を cache に持たせて比べる (= 手で上げる版番号を持たない。 上げ忘れた版番号は、 直したのに効かない状態を静かに作る)
5. **2 条件の関門で、 1 つの語が両方の語彙に入っていないか** — 「締切語が隣接 ∧ 近くに行動語」 のような関門で、 ある語 (例: 「応募」) が
   締切語にも行動語にも入っていると、 その語 1 つで関門を通る = 実質 1 条件になり、 「結果は M/D に通知します。 応募者数は…」 で誤発火する。
   逆に**行動語の語彙が依頼の文体に合っていないと取れない**: 事務からの念押しは、 入力・回答 型の動詞を持たず
   手続きの名詞 (「申請」 の期限) だけで期限を示すことが多い。 語彙を足す前後で、 実 mail の corpus に同じ述語を当てて差分の件数と件名を見る

落とし穴 1・2・4・5 の実装 (範囲の終端 / 引用除去 / 述語の指紋 / 2 条件の語彙) = [`scripts/lib/ja_deadline_dates.py`](../scripts/lib/ja_deadline_dates.py) のメール本文の節。

**適用の見分け方**: 🚨 の行が古いものばかり / 当日届いた依頼が最下段にある / 「期限の翌日に 🚨 が付いた」。

origin: 期限の短い依頼が、 窓の間ずっと無印・一覧の下段にあり、 🚨 と強制 disposition が窓の後にしか付かなかった (実測)。

### <a id="surface-reader-is-not-the-owner"></a>8.56 表示を読むのは agent、 義務を負うのは人 — 「表示した」 を「伝わった」 と数えない

session 開始時の注入 (hook の context injection) は **agent の文脈にだけ入り、 人の画面には出ない**。
agent が返答に書かない限り、 義務を負う人は知らない。 そして agent の既定の振る舞いは「依頼された作業に集中し、 注入は背景として扱う」。
実測で、 注入された一覧に最初の返答で触れた session はごく少数だった。

この構造から 3 つの失敗が出る:

1. **量が釣り合って読まれなくなる** — 検出器を足すたびに注入が増え、 義務でない行が多数になる。
   行を足すのは自動、 消すのは手作業なので、 一覧は「読み飛ばすのが合理的な量」 で安定する
2. **数え違い** — 「N session 表示された」 を消費の失敗の証拠に数えると、 (a) hook が実際に走ったか (配達)
   (b) 人に伝わったか (伝達) の 2 段を飛ばす。 対策の効果も「表示されるようになった」 で確かめてしまう
3. **台帳の水増し** — 表示回数を、 注入以外の経路 (手で実行した script・定期 job) でも数えると、 表示していない回数が混ざり、 強制が早く付く

**対策 = 配達・伝達・量を別々に検査する**:

- **配達**: hook が走ったかを **hook 以外の経路**で見る。 hook の死を知らせる仕組みが hook だと、 止まった環境では知らせも止まる
  (= OS 通知のような外の経路に載せる。 止まり方の例 = [`conventions/hook-authoring.md#disableallhooks-kill-switch`](../conventions/hook-authoring.md#disableallhooks-kill-switch))
- **伝達**: 期限が近い少数の義務だけは、 **agent に「人へ 1 行伝える」 までを必須にする** (= 最終メッセージに件名の語が無ければ止める)。
  求めるのは伝達だけで、 処分 (対応・見送り) は求めない = 判断は人。 初回の表示から求めてよいのは件数が少ない class だけ
  (= それ以外に掛けると強制そのものが壁紙化する、 [§8.24](#surfaced-not-consumed))
- **量**: 注入を「**期限が近い ∧ 自分が動く ∧ 期限が外から決まっている**」 に絞って **全件を見出しだけ**出し、 残り
  (返事待ち・自分で決めた目安の期限・その他の検出器) は件数 1 行にする。 **上位 N 件で打ち切らない** — 打ち切りは後から来た依頼を
  見えなくする。 減らすのは件数でなく対象の定義で。 検出器は止めずに**注入だけを畳む** (台帳・通知は従来どおり)
- **述語を揃える**: 表示回数の台帳に記録する述語と注入に出す述語を一致させる (= 出していない item を「表示したのに」 と問わない)。
  台帳への記録は注入の経路からだけ行う

**変種 — 作業中に自分で読んだ義務でも同じことが起きる**: 注入でなく、 依頼された作業の途中で agent 自身が記録を読み、
期限を文中に書いても、 その期限を**依頼の属性** (文面の注記・整理表の 1 項目) としてだけ使い、 残り日数と準備物を持つ別の義務として
評価しないことがある。 同じ context に「残り日数」「準備に要るもの」「本人が動けない日」 が揃っていても組み合わされない。
機械で塞ぐ案 (「文中に書いた近い期限を持つ記録が無ければ止める」) は、 **同じ日付の別の記録があると日付の照合では一致してしまい**、
雑な語の照合でも別の記録と一致して、 実例を止められなかった — 期限を書いた文に記録の id を併記させる形でないと効かない (実測、 未実装)。

<a id="paired-signals-join-at-render"></a>**変種 — 対になる 2 行が別々の見出しに出ると、 読む側は結ばない**: 「返事を待っている義務」 の行と
「その相手から返事が届いた」 の行が同じ注入の別々の見出しに並んでも、 読む agent は 2 行を結ばず、 義務を「返事待ち」 のまま人へ伝えた
(実測。 両方の行を読んだ session の大半は結ばず、 義務を「返事待ち」 のまま伝えた)。 返事の行を足す対策の後に同じ型が再発した =
行を増やしても結び付けは読者に残る。 結ぶための鍵 (義務 → スレッドの索引) は検出器の側にしか無いので、
**結合は表示の時点で機械がやる**: 義務の行そのものに届いた返事を付けて最上段へ出し、 元の見出しからは外す (二重に出さない)。
あわせて、 片方の検出器が取得に失敗したときに「返事なし」 として空を返すと結合の相手が消える — 取得失敗は前回の結果を持ち越し、
「なし」 と区別する ([§8.26](#disjunctive-finding-self-routing) の判別を読者に残さない、 の結合版)。

**数える道具**: [`scripts/injection-reach-audit.py`](../scripts/injection-reach-audit.py) = 注入に出た session (配達、 どの段の印で出たか) と、
assistant が触れた session (伝達、 最初の返答かどうか)、 user が触れた時刻を transcript から分けて数える。

**適用の見分け方**: 「毎 session 出ていたのに誰も触れなかった」 型の RCA が続く / 注入の総量を誰も把握していない /
検出器を足すたびに注入のブロックが 1 つ増える。

origin: 義務の失効が続いた系列の RCA で、 対策が毎回「検出を足す → 表示が増える」 の形だったことを振り返って確定 (実測)。

### <a id="lapse-claim-is-absence-claim"></a>8.57 「期間が過ぎた」 は不在の主張 — 失効と書く前に、 案件の key で後続を引く

処分 (記録・close・強制への応答) は **message 1 通 / thread 単位**で行われるが、 義務の単位は**案件** (人 × 事柄) である。

- 窓の日時だけを見て「期間が終わったので対応できない」 と報告すると、 **救済・延長・再依頼が別 thread・別件名で届いていても見ない**
  (同じ一覧の数行下にあっても)。 人はその報告を前提に案件を閉じる
- 「この 1 通を処分せよ」 と止められた agent は、 その 1 通だけを処分して止まる (= 最小の遵守)

∴ **「失効」「対応不要」 と書く前に、 案件の key (人名・識別番号・案件を指す語) で未処理の記録を 1 回引く** ([§8.19](#retrieval-key-choice) の key 選択を、 探し物でなく**結論の前**に適用する)。
機械側では、 処分を強制する理由文に **件名の語 (固有の数文字) を共有する未処理 item** を並べる。 多くの件名に出る語 (年度・学期など) では結び付けない。

**適用の見分け方**: 「期間外」 の報告の根拠が、 依頼 1 通に書かれた日時だけ。

origin: 失効として閉じかけた依頼に、 後続の救済の依頼が別の件名で届いていた (実測)。

### <a id="single-deadline-field-many-legs"></a>8.58 期限欄は 1 つ、 手順の期限は複数 — 目安で欄を上書きすると、 本物の期限は注釈と散文に落ちる

複数の手続き (① 登録 → ② 書類 → ③ 支払 → ④ 申請) を 1 件の記録にまとめ、 各手順に外部の失効型期限があると、 期限欄は 1 つしか持てない。
手順が終わるたびに誰かが欄を次の期限へ進めないと、 欄は終わった手順の値で残る。

- 進めるときに**自分で置いた目安** (「なるべく早く」 の日付) を入れ、 失効型の印を残すと、 **失効型の顔をした目安が本物の期限を押し出す**。
  本物は欄の横の注釈 (YAML の comment = parser に見えない) と本文の散文にだけ残る
- 表示側はその記録を「期限超過」 として毎回出し続け、 本物の期限の日付は一度も出ない。 超過の塊は読み飛ばされる
  (「要再設定」 と表示していても、 誰も欄を触らない)
- 複数の手順の信号 (催促・返信) が同じ id に集まると、 id そのものが見慣れた壁紙になる (= hub 化。 [§8.24](#surfaced-not-consumed))
- 手順を独立の記録に切り出す契機が「外から催促が来たとき」 だと、 **催促の来ない手順だけが親に残る**

**対策**:

1. **構造**: 外部の失効型期限を持つ手順は、 **その期限を知った時点で**独立の記録に切り出す。 自分で置いた目安は失効型と別の印で
   ([#derived-external-deadline](#derived-external-deadline) の「目安は目安と宣言する」 側)。 期限欄の横の注釈に別の期限を書いたら、 それは切り出す合図
2. **検出**: **欄が過去 ∧ 未完了**の記録に限り、 本文の散文から今日〜2 週の期限らしい日付を取り、 その日付で並べて「期限欄は M/D のまま」 を併記する
   (= 行を足さずに値を正す。 再設定の合図は残す)。 **欄が未来の記録は読まない** — 完了した手順の日付や、 他の記録の期限の引用を拾って誤りが多い (実測で半分)。
   散文の日付は**隣の日付で窓を切る** (= 「A〆。 条件 = B」 の〆 を B のものと読まない / 「✅ A 支払済 → ④ … B〆」 の済 を B のものと読まない)。
   部品 = [`scripts/lib/ja_deadline_dates.py`](../scripts/lib/ja_deadline_dates.py)
3. **作らないもの**: 期限欄の注釈に日付があれば警告する lint — 注釈の日付の大半は逆算の説明で、 誤検出が多い (実測)

**関係**: 散文で書かれた sub-obligation 一般の消え方 = [§19](#rollcall-line-marker)。 §19 は fact の種類ごとに点呼行を置く対策で、
本節は「期限」 1 種類に限って、 点呼行なしで散文から拾う検出の一般形。

**適用の見分け方**: 「期限超過」 が何日も続く未完了の記録 / 期限欄の横の注釈に別の日付 / 記録の task が ①②③④ の手順列。

origin: 手順列を持つ記録で、 途中の更新が期限欄を目安の日付で上書きし、 本物の期限が注釈と散文にだけ残った。 表示は超過のまま出続けた (実測)。

### <a id="narrowing-makes-input-load-bearing"></a>8.59 表示を絞る変更は、 絞った後に残る入力の正しさを load-bearing にする — 条件の外に落ちたものは件数で残す

注入や一覧を「期限が ±N 日」 のような条件で絞ると ([§8.56](#surface-reader-is-not-the-owner) の量の対策)、 **条件の判定に使う値が誤っている記録**は、
絞る前は目立たない段にでも残っていたのに、 絞った後は**行にも件数にも出ずに消える**。
絞る変更の効果は「量が減った」 で確かめられるが、 消えた記録は見えないので確かめられない。

**対策**:

1. 条件の外に落ちたものを**種類ごとに件数で残す** (「±N 日より前に過ぎた N 件」)。 「件数だけ 1 行に畳む」 の対象に、 **条件の外**を入れ忘れない
   ([§8.53](#display-cap-is-not-the-count) の近縁 = 上限や条件で見えなくなったものは件数として出す)
2. 絞る変更を入れる turn に、 **同じ入力で旧表示と新表示を並べ、 旧にあって新に無い記録を 1 回列挙する** (= 消えるものを設計時に見る)
3. 条件の判定値 (期限欄など) が人手の更新で壊れやすいなら、 値を正す検出を同時に入れる ([§8.58](#single-deadline-field-many-legs) の 2)

**適用の見分け方**: 「黙って消さない」 と書いた設計で、 件数行の対象に「条件の外」 が無い / 絞った後の表示に、 前は出ていた古い記録が見当たらない。

origin: 注入を期限の近い義務だけに絞った変更で、 期限欄が古いまま残った記録が件数ごと消えていた (実測)。

### <a id="detector-change-breaks-downstream-writers"></a>8.60 検出器を締める変更は、 その前に立つ無人の書き手を黙って止める — 過去の出力を今の検出器に通し直す

gate (commit を止める検出器) の語を増やす・判定を広げる変更は、 **人が見ている commit では即座に鳴るので安全に見える**。
ところが同じ gate の前には、 無人で出力を commit する routine が立っていることがある。 routine は失敗を warning で握りつぶす設計が多く、
しかも **締めた当日の出力に当たる語が無ければ通る** ので、 当たる出力が出る日まで壊れたことが表に出ない (出た日にも誰も見ていない)。
検出器の較正は「人の commit で誤爆しないか」 で行われ、 **機械の出力の分布**は較正の標本に入っていない。

**対策**:

1. 検出器を変える turn に、 **無人の書き手の直近の出力を今の検出器に通し直す** (= 較正の標本に機械の出力を足す)
2. 止まる出力の中身で分ける: 誤検知 (公開済みの書誌・第三者の公開データ・地名) なら**検出器側を構造で直す** / 本物 (書き手が生成した文に実名) なら**書き手の生成の指示を直す**
3. 通し直しを定期実行にも載せる (= 検出器の変更と、 書き手の出力の変化のどちらからでも鳴る)。 窓は直近に限る (= 直した後も履歴に残る古い出力で永久に赤くならない)
4. 無人の書き手の失敗経路 (warning で握りつぶす) 自体を、 見える面に上げられるなら上げる

**適用の見分け方**: 検出器の変更を「人の commit で鳴るか」 だけで確かめた / その repo に bot や定期 routine の commit が混じっている。

**実装例** = [`scripts/replay-public-gate.sh`](../scripts/replay-public-gate.sh) (規約 = [`conventions/confidential-repo-boundary.md#gate-change-replays-unattended-writers`](../conventions/confidential-repo-boundary.md#gate-change-replays-unattended-writers))。
兄弟 = [§8.54](#detector-installed-after-the-stock) (設置前の在庫) / [§8.59](#narrowing-makes-input-load-bearing) (絞る変更で消えるもの)。

origin: 検出語を締めた後、 論文を記録する bot の archive が共著者名と要旨で必ず止まる状態になっていたが、 締めた当日の出力は通っていた (実測)。

### <a id="rules-present-but-not-read-before-the-act"></a>8.61 規則は在るのに、 行為の直前に効かない 4 つの入口 — 理由の無い手順・問いの置き換え・必読の grep 化・訂正の 1 本化

規則は正しい場所に書かれ、 行為をする session の読み込み面にも載っている ([§8.44](#rule-visible-where-the-act-happens)) のに、
行為の直前に読まれない・読んでも効かない型がある。 どれも「規則を足す」 では直らず、 **規則への経路の形**で直る。

1. <a id="procedure-step-needs-reason-pointer"></a>**理由の無い手順は、 問われると削られる**。 手順メモの手順の本当の理由が別の doc の規則にあるのに、
   メモには付随的な理由 (見た目・品質) しか書かれていないと、 「その手順は要るのか」 と問われた時に正しい手順ごと消える。
   対策 = 手順の横に、 その手順を要求する規則への pointer を置く。 手順メモを複製して次回に使う運用なら、 pointer の無い手順を lint で拾う。
2. <a id="classification-not-external-instruction"></a>**仕分けの問いを、 相手の指示の有無の問いに置き換えない**。 「どれを A (例: 紙) にするか」 と問われ、
   答えが owner の決めた規則にあるとき、 相手 (事務・取引先) の指示が無いことはその規則を開け直す理由にならない。
   相手に決めさせに行く文 (「必要なら〜します」「気になるなら聞きます」) も同じ誤り。 [§8.36](#input-does-not-transfer-decision-ownership) の双対
   (= 入力の提供は判断を移さない / 指示の不在も判断を移さない)。
3. <a id="must-read-executed-as-reason-grep"></a>**複数 topic の大きな file への「必ず読む」 は、 添えた理由の語の grep として実行される**。
   必読の指示に理由を 1 つ添えると、 読む側はその語で探し、 別の topic の規則は context に入らない。
   対策 = 必読にするなら、 その行為に効く節を名指しする (読み込み表の行に、 行為の語と節の anchor を足す) か、 判定できる部分を機械に移す。
4. <a id="one-correction-many-rules"></a>**訂正は 1 本で来るが、 規則は束で効く**。 1 本の規則で訂正されたら、 同じ行為を縛る他の規則を
   行為の性質の語 (媒体・宛先・経路・期限) で探してから答え直す。 名指しされた 1 本だけ直すと、 同じ turn の中で兄弟の規則にまた訂正される。

**適用の見分け方**: 行為の後で「規則は在った」 と分かった / 訂正を受けた直後に別の規則で再訂正された / 手順メモから手順を消した commit の理由が「不要そう」 だった。

**機械に移した例** (3 の後半) = 配布経路が file 形式より狭い成果物に作る時に印を付け、 出口で中身を見る = [`conventions/office-automation.md#seal-artifact-marker`](../conventions/office-automation.md#seal-artifact-marker)。

origin: near-miss の RCA で、 4 つが同じ判断に重なっていた (実測)。

### <a id="steady-state-is-not-a-finding"></a>8.62 通常の周期の状態を警告にしない — 知らせる価値は「今打てる手が、 用事の時点の結果を変えるか」 で決まる

検出器が正しく当たっていても、 **当てている状態が通常の状態**なら、 その警告は届いた瞬間から壁紙になる ([§8.24](#surfaced-not-consumed) は「消費されない表示」 の話、 こちらは「消費しても意味が無い表示」 の話)。 典型 = 有効期間つきの資格 (ログイン・token・承認) を、 有効期間より長い間隔でしか使わない場合。 「切れている」 が大半の時間の状態で、 先に更新しておいても、 次に使う時にはまた切れている。

警告・予告を足す前の 3 問:

1. **その状態は、 通常の運用で時間の何割を占めるか**。 大半なら、 それは異常ではなく周期。
2. **受け手が今動いたとして、 用事の時点まで効果が持つか**。 持たないなら、 予告は受け手の記憶に仕事を渡すだけ ([§8.12d](#human-memory-not-a-carrier))。
3. **用事の時点で、 その場の復帰が安く済むか**。 済むなら、 扱う場所は検出器でなく用事の入口 (just-in-time)。

→ 3 問とも「周期・持たない・済む」 なら、 **知らせるのをやめ、 用事の入口で見て、 その場で復帰する**。 死活監視に残すのは、 入口の復帰では直らない故障 (配線・権限・形式の変化) だけ。 副産物として、 監視のために相手のシステムへ定期的に撃つ request も消える。

**適用の見分け方**: 同じ警告が、 対処した後も数日で戻る / 警告の文が「都合のよい時に〜しておくと」 で終わる / 赤が付いている時間の方が長い。

origin: SSO 保護サイトを script で読む経路で、 ログインの切れを session 開始時に予告し、 dashboard でも赤く出していた。 利用の間隔が IdP の有効期間より長い使い方で、 予告に従っても結果が変わらなかった (実測)。 予告と赤をやめ、 読む時に見て復帰する形にした ([`machine-route-first.md#sso-session-recovery`](../conventions/machine-route-first.md#sso-session-recovery))。 単一の領域からの一般化なので、 資格の有効期間 × 利用間隔の形をしていない警告には、 1 の問いだけを当てる。

### <a id="observe-dont-estimate"></a>8.63 観測できるものを推定で置き換えない — 推定器を作る前に、 1 回の安い観測で同じ問いに答えられないかを問う

「X はまだ有効か」 「相手は今どの状態か」 を知りたい時、 手元の記録から推定する機構 (最後の成功時刻 + 期間、 履歴の pattern) は作れてしまう。 だが推定器は (a) 環境ごとの定数を要り、 (b) model の未決点 (放置型か絶対時間型か等) を抱え、 (c) 自分の見えない経路の変化 (別端末・別 process) を知らず、 (d) 外れた時に外れたと分からない。 同じ問いに**1 回の観測**で答えられるなら、 観測の方が単純で正確で、 環境固有の値も要らない。

- **順序**: まず観測の手段を探す (対象に 1 回触れて結末を見る) → 観測の代償 (相手への負荷・副作用・人の画面への干渉) を見積もる → 代償が受け入れられるなら推定器は作らない。 推定を残すのは、 観測が高い・副作用が大きい・そもそも観測できない時だけ。
- **観測の代償は「いつ観測するか」 で下げる**: 定期的に観測すれば負荷と副作用 (相手の session の延命等) が出るが、 用事がある時にだけ観測すれば、 それは通常の利用と区別が付かない ([§8.62](#steady-state-is-not-a-finding) と対)。
- **盲目の上限待ちは、 観測できていない印**。 「N 秒まで poll して変化が無ければ失敗」 は、 成功も失敗も直接は見えていない。 結末が見える信号 (開かせた画面の行き先・相手が返す状態) を足すと、 失敗が上限でなく数秒で分かり、 成功と失敗で次の手を分けられる。
- 既に作った推定器が在る時は、 **推定の結果を別の機構に配線して回る前に**、 その機構が自分で観測できないかを先に問う (推定を共有するほど、 (a)〜(d) が広がる)。

origin: ログインが生きているかを閲覧履歴から推定する機構と、 結末の見えない上限待ちの入り直しが並んでいて、 前者の推定を後者に渡す改修が候補に挙がった。 開かせた tab の行き先を見る形にしたら、 推定器・組織固有の定数・上限待ちが全部要らなくなった (実測: 失敗の判定が上限待ちの数十秒 → 数秒)。

### <a id="completion-by-observation"></a>8.64 人に頼んだ操作の完了は、 報告させず機械が状態で見る — 頼む・待つ・続きから進む

最終 leg が本人にしかできない操作 ([§8.27](#user-execution-handoff)) を頼んだ後、 「終わったら教えてください」 で待つと、 本人の手数が「操作 + 報告」 の 2 つになり、 agent 側は報告を待つ間に止まるか、 報告を聞き漏らす。 操作の完了が**機械から見える状態の変化** (cookie・file・相手の返す status) に現れるなら、 完了の検知は機械の仕事にする:

1. **頼む** = 1 行 (何を・どこで)。 操作の入口 (開くべき画面) は機械が先に出しておく。
2. **待つ** = 状態を上限つきで見る command を background で走らせる。 上限は人の操作の時間 (分の桁) に合わせ、 時間切れは失敗でなく「まだ」 として返す。
3. **続きから進む** = 状態が変わったら、 止まった所から再開する。 本人は報告しなくてよい。

注意: 待っている間に本人が使っているもの (入力中の画面) を機械が片付けない。 時間切れの時も、 入力の途中かもしれないものは残す。 状態の変化が機械から見えるまでに遅れがある (browser の disk への書き出し等) なら、 その遅れを上限に含める。

origin: script が「本人のログインが要る」 と止まった後、 本人がログインして agent に伝え、 agent が同じ command を実行し直していた。 ログイン完了は cookie の更新として script から見えるので、 待つ option にした。

### <a id="index-doc-state-copy"></a>8.65 入口の doc (README) に状態を写さない — 状態を進める操作は写しを通らない

作業単位ごとの dir に入口の doc (README) を置くと、 そこに「未提出」「M/D に出す予定」「返事待ち」「未決」「〜時点では下書き」「〆 M/D」 のような**状態**を書きたくなる。 だが状態を進める操作 (刷る・送る・返事を記録する) は状態の正本 (manifest・TODO・台帳) を更新し、 入口の doc を通らない。 写しは状態が進んでも残り、 後の session は入口の doc を先に読むので、 **古い状態が一番信じられやすい場所に残る** (実測)。

[§15](#sot-consolidation-recipe) (定義の多重記述の是正) と違い、 状態の写しは書いた瞬間は正しく、 時間で腐る。 だから「今は合っている」 は写しを残す理由にならない。

直し方 (強い順):

1. **状態は生成する**: 入口の doc に置くなら正本 (manifest) から描いた表にし、 **状態を変える command 自身が描き直す**。 正本を手で直した時の描き直し command と、 表が正本より古いと落ちる検査を添える。 表には状態と日付だけを出し、 説明文は出さない (説明は正本の側で読む = 表の行が散文を運ばない)。
2. **問い・約束・返事待ちは期限を持つ carrier へ**: 入口の doc には carrier への参照だけを置く。 carrier は期限の surface に乗るが、 入口の doc は乗らない。
3. **経緯は区間で囲む**: 「いつ何を出した・差し戻された」 は状態でなく経緯。 除外区間の marker で囲み、 lint の外に置く。
4. **状態の語彙を lint する**: 入口の doc の手書きの行に状態の語彙 (未〜 / 予定・約束 / 済 / 待ち / 未決 / 「時点」 / 期日) が出たら落とす。 除外 = 生成表・経緯の区間・code 表記 (file 名に「未提出」 が入る)・値の出典表 (「M/D (提出予定日)」 は記入値の出典であって状態ではない)。 ⚠️ **出典表かどうかは表の見出し行で決める** — 途中の行に「出典」 の語があるだけで以降の行を全部外すと、 表の後半が黙って lint の外に落ちる (実測)。 手順 doc (点呼の書き方を説明する doc) は対象にしない。
5. **commit で止める**: 入口の doc か manifest を stage した commit で 4 と 1 の鮮度を見る。 既存の写しは gate を入れる同じ turn に機械で移す ([#manual-work-in-design-records](#manual-work-in-design-records))。

落とし穴:

- **除外区間の marker は入れ子にできない — 崩れ自体を finding にする**: 除外を「開きから次の閉じまで」 で数えると、 区間の中に開きを書いた時に内側の閉じで外側が閉じ、 後ろの行が黙って lint に戻り、 外側の閉じは宙に浮く (実測: 経緯の区間の中に、 見出しを強調する空の区間を差し込んでいた)。 除外区間を持つ lint は、 入れ子・閉じ忘れ・宙に浮いた閉じを**承認できない** finding にする (承認できると除外範囲そのものが狂ったまま黙る)。
- **消した節を指す参照を全文で探す**: 入口の doc の節 (「未決事項」 等) を消したら、 その節名を参照している comment (生成 script の docstring 等) を repo 全体で grep する (実測: doc 以外に残った)。
- **gate が呼ぶ engine が暗号化される path にあるなら、 locked のマシンでは走らせない** ([`hook-authoring.md#locked-engine-interpreter-rc`](../conventions/hook-authoring.md#locked-engine-interpreter-rc))。
- 射程: 語彙で見るので、 語彙に無い言い換え (「まだ出していない」) は見えない。 入口の doc を書く turn に「これは今の状態か、 file の説明・出典・経緯か」 を 1 回問う。

origin: 作業単位ごとに manifest と README を持つ運用で、 README の状態の写しが古くなっていた (実測)。 生成表・状態の語彙の lint・commit gate・既存分の機械移行を同じ turn で入れた。

### <a id="audit-unit-vs-rule-unit"></a>8.66 検査が列挙する単位を、規則が守る対象の単位に合わせる — ずれた分は永久に見えない

「この class の場所には必ず X を置く」 という規則に検査を付けるとき、 検査は**何かの単位で対象を列挙する** (repo ごと / file ごと / account ごと)。 その単位が規則の言う対象の集合と違うと、 **差集合は一度も見られないまま「全部 OK」 が出る**。 緑は「見た範囲で緑」 でしかないのに、 出力にはその境界が書かれない。

実測の形: 規則は「agent が task を始める場所に入口を置く」 だったが、 検査は repo を列挙していた。 repo を並べた容れ物の dir はどの repo にも属さないので列挙に入らず、 そこだけ入口が無い状態が検査を通り続けた (指摘したのは人)。

- **検出器を書く turn に 2 つの集合を並べて書く**: 規則の対象の集合 (= 規則の言葉から取る) と、 検査が列挙する集合 (= 実装が回す list)。 一致しないなら、 差集合を検査の docstring に「見ない範囲」 として書くか、 列挙側を規則に合わせる。
- **列挙の源は規則の言葉から取る**: 「repo ごと」 は実装の都合であって規則ではない。 規則が「場所」 と言っているなら、 場所の種類 (repo・容れ物の dir・home・作業用の非 repo フォルダ) を数え上げる。
- **単位が変わる変更は検査も動かす**: 対象の定義を広げた turn に、 検査の列挙も同じ turn で広げる (別 turn に回すと、 広げた分は誰も見ない)。
- 姉妹: [§8.43](#sweep-null-needs-per-form-control) は「探している class の**形**ごとに陽性対照を通す」、 本節は「対象の**単位**を合わせる」。 どちらも「0 件」 の意味を検査の構造から決める。

origin: repo 単位の audit が全 repo で OK を出していた一方、 repo を並べた dir にだけ入口が無かった (実測、 指摘は人から)。

### <a id="green-check-endorses-unasked-premise"></a>8.67 検査の緑は、 検査が問わなかった前提まで追認して読まれる — 前提を決める判断が成果物の外にあるなら、 作る時に成果物へ書き込み、 出口で読む

成果物の性質を確かめる検査 (頁数が期待と一致・font が埋め込み済み・形式が正しい) は、 **その成果物の範囲が正しいか** (この頁の集合でよいか・この file を出してよいか) を問わない。 ところが「N 頁 = 期待どおり ✓」 のような緑は、 後段には「この N 頁で正しい」 と読まれる。 しかも期待値の N 自体が、 範囲を決めずに作った成果物から写されていることが多い = **誤った前提を、 前提を問わない検査が正しいと表示する**。

実測の形: 様式の file を丸ごと 1 本の PDF にする生成・記録・手順書・印刷前の頁数検査・印刷の 5 段が、 どれも「全頁を刷る」 を疑わなかった。 どの頁を窓口に出すかは様式の記入 map の側の判断で、 刷る段の file (raster = 字を持たない) からは見えなかった。 頁数の検査は様式付属の説明書きの頁まで「期待どおり」 と通した。

- **緑の文言は、 検査した性質だけを言う**: 「N 頁 = 期待 ✓ (= はみ出していない)」 のように、 何を確かめ・何を確かめていないかを出力に書く。 期待値は範囲を決める判断の側 (記入 map・仕様) から取り、 作った成果物から写さない。
- **範囲を決める判断が成果物の外にあるなら、 作る時に成果物へ書き込む**: 作る道具が判断を持っている瞬間に、 成果物の中 (metadata 等) に宣言を書き、 出口の gate がそれを読む。 宣言の無い成果物は出口で止め、 範囲を決めさせる (推定で補うなら、 止めるのは確度の高い語だけにし、 残りは一覧に出す)。 同じ形の先行例 = 紙専用の印 ([§8.61](#rules-present-but-not-read-before-the-act) の「機械に移した例」)。
- **推定を足すなら、 実際に出した物と出さない物の束で誤検出を数えてから止める範囲を決める**: 止めすぎの害 (宣言を 1 回足す手間) と見逃しの害 (検査の無い状態と同じ) を比べ、 確度の高い語だけで止める。 数えた道具を残しておき、 語を変える前に同じ束で数え直す。
- **検査の出口が確認 (ask) だと、 理由が人にも model にも届かない build がある**: 止めた理由と直し方を返せる形 (block + 理由) にする ([`conventions/hook-authoring.md#build-dependent-docs-drift`](../conventions/hook-authoring.md#build-dependent-docs-drift))。
- 姉妹: [§8.66](#audit-unit-vs-rule-unit) は「検査が列挙する単位を規則の単位に合わせる」 (見ていない範囲の緑)、 本節は「検査が問わない前提の緑」 (見ている範囲の、 問うていない性質)。 [§8.20](#acceptance-is-not-specification) は「受理は仕様ではない」 の成果物版、 本節は検査結果版。

**適用の見分け方**: 検査の期待値が、 検査される成果物を作った手順から写されている / 緑の表示を根拠に次の段が「このまま出す」 を決めている / 範囲を決めた判断の記録が、 出口で見る file の外にしか無い。

**実装例** = [`conventions/office-automation.md#print-submission-pages-only`](../conventions/office-automation.md#print-submission-pages-only) ([`scripts/lib/print_pages.py`](../scripts/lib/print_pages.py) = 宣言・推定・較正の `--scan`、 [`scripts/pdf-print-preflight.py`](../scripts/pdf-print-preflight.py) `--pages` / `--hook`)。

origin: 様式付属の説明書きの頁まで刷り、 印刷前の頁数検査がそれを期待どおりと通していた (実測)。

### <a id="rule-copy-lint-reach"></a>8.68 規則の写しは逐語 lint では追い切れない — doc が規則を書けない構造にし、 成果物は gate に決めさせる

[§2](#no-duplicate-rules) の「定義は 1 か所」 が守られない典型は、 **手順 doc の早見表・checklist・教訓**である。 どれも親切心で書かれ、 どれも規則の値を手で写しており、 規則が変わると**古い写しだけが残る** (実測: 同じ規則について、 手順書の表・手順書の checklist・手順書の教訓の 3 か所が、 正本の改訂より前の版のまま残っていた)。 ここで「写しを検出する lint を強くする」 方向に投資すると必ず行き止まる — 逐語照合は**言い換えを原理的に見ない** ([#literal-anchor-detector](#literal-anchor-detector) / [#proxy-blind-spot](#proxy-blind-spot))。

**4 段の構造** (下の段ほど機械が持つ):

1. **規則の home は機械可読な spec 1 つ** — 散文を home にできない理由は「空欄は誰の欄か」「この値は何の規則か」 を機械可読に持てないこと。 各規則に安定 id と 1 行の規範文 (summary) を持たせ、 **廃止した版の言い回しも spec に残す** (= 検出語の出どころ)。
2. **人が読む表・checklist は生成 view** — doc には区間 marker を置き、 spec から描く。 view が spec より古ければ出口の検査と commit の関門が止める ([#derived-view-as-recovery](#derived-view-as-recovery))。 経緯・理由の文は「歴史」 区間として lint の外に置く (= 古い言い回しを**わざと**残す場所を作らないと、 人は lint を避けるために経緯を消す)。 ⚠️ 区間は入れ子にしない — 内側の閉じで外側が閉じ、 後ろの行が黙って検査に戻る。
3. **書き写しの lint は spec から導出した語だけで判定する** ([#detector-config-must-be-derived](#detector-config-must-be-derived))。 3 種: 規則を**定義する**言い回し / **廃止した版**の言い回し / 値から導出した token (記号つきの固定値)。 語そのもの (一般語) を検出語にしない。 例外は理由つき承認一覧で ratchet ([#semantic-detector-ack-ratchet](#semantic-detector-ack-ratchet))。 鳴った文が欠陥とは限らない ([#flagged-text-is-not-the-defect](#flagged-text-is-not-the-defect))。
4. **構造で埋める = 手順 doc は規則を書けないことにする** — 「値・可否・セル番地を含む規則の形の文を、 手順 doc と理由の home に書いたら、 **矛盾していなくても**落とす」。 置けるのは規則 id と生成 view だけ。 矛盾検出 (= 誤っている写しだけを落とす) は言い換えに負けるが、 **形の検出** (= 規則の形をした文がそこに在ること) は語彙に依らず効く度合いが高い。

**なぜ穴が残っても結果が変わらないか** (= ここが投資判断の分かれ目): 成果物を実際に決めるのは doc ではなく **spec と出口の gate** である。 生成器は spec の全項目を検査してからしか出力を書かない ([`conventions/office-automation.md#gate-owns-correctness-not-the-estimate`](../conventions/office-automation.md#gate-owns-correctness-not-the-estimate)) ので、 **古い写しに従って作った成果物は gate で止まり、 外へ出ない**。 記入の雛形 (stub) も spec から生成されるので、 doc を読まなくても正しい欄が並ぶ。 ∴ lint の射程の穴の害は「**人が古い言い方を読む**」 に縮む — 実害の大きさが 1 段下がるので、 lint を意味検出へ育てる投資をしないでよい。 残る真の穴は 2 つだけ: **spec 自身が間違っている** (doc と spec が同じ誤りを持つ) と、 **doc が spec に無い規則を作った** (= 書き写しではなく新規の規則。 見つけたら spec の規則に昇格させる)。

**gate が機械で見られない規則** (= 行為の規則。 渡す時の言葉・聞いてはいけないこと) は、 上の 1-2 で summary を view として置き、 3 で矛盾する言い方を拾うところまでが上限。 そこは人が読む面なので、 **規則 id から 1 コマンドで規範文を引ける**ようにしておく (読む人が写さずに済む唯一の条件)。

適用の見分け方: 同じ規則の値が「機械が読む file」 と「人が読む doc」 の両方に in-place で書かれている / 規則を変える commit が doc を 2 か所以上直している / 検出器の設定に人が語を足す欄がある。

⚠️ **適用範囲 = その規則を機械が読む spec が在る系** (= 様式の記入規則・閾値・許容値・固定文字列のように、 成果物を作る道具が同じ規則を読んで検査できるもの)。 **罠の症例集・設計原則の doc は対象外** — そこに書かれる「規則」 は人の判断のための記述であって、 spec に写せる形を持たない (本 doc 自身がその側)。 区別の問い = 「この規則を、 成果物を作る道具が読んで検査できるか」。 できないなら 4 は当てず、 §2 の pointer 規律だけを当てる。

### <a id="failure-exit-equals-violation-exit"></a>8.69 「止まった」 は対照にならない — 故障の合図を違反の合図と同じ値にすると、 全部が止まる故障が陽性対照を緑にする

関門 (gate) は呼び元と **合図の意味**を約束して動く。 よくある形は「0 = 問題なし / 1 = 違反だから止めろ / それ以外 = 検査が走っていない (止めるな)」。 この約束の**故障側だけが漏れる**ことがある — 検査の本体が起動に失敗したとき、 言語処理系や shell の既定の終了値がたまたま **1** で、 呼び元はそれを「違反」 と読む。 結果、 **その関門が守る範囲の操作が、 違反の有無に関わらず全部止まる**。

厄介なのは症状の見え方である。 一律に止まる状態を、 次のような test に当てると:

| 段 | 期待 | 一律故障のときの出力 |
|---|---|---|
| 違反を止める (陽性対照) | 止まる | ✅ **偽の緑** — 止まった理由は見ていない |
| 無関係な操作は通す | 通る | ❌ 「止めないはずのものを止めた」 |
| 違反を止める + 文言を見る | 止まる + その検査の文言 | ❌ 「**止めなかった** (rc=1)」 という矛盾した文言 |
| 検査を無効化した環境 | 通る | ✅ (その環境では関門に到達しない) |

読む人には **2 方向の故障が同時に起きている**ように見え、 「述語がおかしいのか、 呼び出し方がおかしいのか」 と原因を 2 つ探し始める。 実際は 1 つである。

**3 つの規律**:

1. **故障の合図を違反の合図と別の値にする。** 「検査が走っていない」 は独立した第三の状態 ([`§8.38`](#false-positive-declaration-needs-control) の「未検証」 と同じ)。 そして**走らなかったことを人に見える形で出す** — 黙って通すと、 守られていない期間が誰にも気づかれない。
2. **故障を握りつぶす範囲を、 呼び元が「止める」 判断に使う入口だけに限る。** 対話的に使う入口では例外をそのまま出す (= 本当の欠陥を隠さない)。 この非対称が無いと、 故障を通す実装がそのまま debug を難しくする。
3. **陽性対照は「鳴ったこと」 でなく「その検査が鳴ったこと」 を見る。** 検査の名前か文言まで一致を要求する。 併せて、 失敗した段には**終了値と出力の 1 行目**を出す — 診断が test の外に出ないと、 読む人は環境を手で再現するところから始めることになる。

⚠️ **適用範囲**: 呼び元が終了値で分岐する関門すべて (commit hook・CI の段・定期実行の判定)。 単体で人が読む道具は対象外。

**由来 (実測)**: 関門の手前に立つ道具が起動に失敗し、 その失敗が 1 で返ったため、 対象の commit がすべて止まった。 配線の test は上表のとおり 5 段中 3 段が赤、 2 段が偽の緑になり、 症状が矛盾して見えた。 同じ形は [`§8.42`](#detector-fires-on-its-own-signal) (検出器が自分の signal で鳴る) の裏返しで、 あちらは「鳴りすぎ」、 こちらは「鳴った理由を見ない」。

### <a id="isolation-shortens-the-path"></a>8.70 隔離のために環境を差し替えた test は、 意図より手前で落ちて緑になる — 新しい対照は「直す前の実装で赤くなる」 ことまで確かめて初めて対照になる

ある段だけを見たくて環境を差し替える (別の home を指す / PATH を差し替える / 設定を空にする) と、 **差し替えが検査対象より手前の依存も同時に壊す**ことがある。 test は通るが、 通った理由は意図した経路ではない。

実測の形: 検査対象の外部依存 (追加で入れた library 群) が**利用者ごとの置き場**に在り、 home を差し替えた瞬間にそれごと見えなくなった。 対象の道具は目的の処理に入る前に読み込みで落ち、 「故障だから通す」 という**正しい振る舞い**で緑になった — 直す前の実装でも同じく緑になる、 意味の無い対照だった。

**対策は 1 つで足りる**: 新しい対照を足した turn に、 **直す前の実装でそれが赤くなることを確かめる**。 赤くならなければ、 その対照は欠陥を掴んでいない。 確かめ方は (a) 修正部分だけを戻した写しを一時的に作って当てる (b) 対象の関数を故障させて注入する、 のどちらか。 ついでに「意図した場所まで到達したか」 (= 期待する文言が出ているか) も見ると、 手前で落ちた場合に気づける。

⚠️ この確認は**欠陥を直した直後の turn でしか安く行えない**。 直す前の状態が手元にあるのはその瞬間だけで、 後から作り直すのは高い ([`§8.54`](#detector-installed-after-the-stock) の「設置と同じ turn に」 の test 版)。

### <a id="event-anchored-legs"></a>8.71 行事の日付から決まる手順は、 回ごとの起票でなく行事の日付から導く — 起票した回でしか鳴らない仕組みは、 起票を忘れた回に全部そろって黙る

定期的な行事 (講演会・会議・提出の回) には、 **行事の日付から逆算して期日が決まる手順**が付いてくる (告知・来訪者への案内・事務書類)。
これを「回ごとに子の記録を起票し、 その記録に発火日を書く」 設計にすると、 次の 3 つが同時に起きる。

- **発火の網は起票された回しか知らない**。 起票を忘れた回では、 通知・朝の要約・起動時の注入が**全部そろって黙る**。
  起票の無い回は「対象が無い」 と同じ顔をするので、 網の側からは鳴らないことに気づけない
  ([#detector-config-must-be-derived](#detector-config-must-be-derived) の回ごと版 = 人が書く一覧が、 設定でなく回ごとの記録になっただけ)
- 子を切らずに親の記録 1 件にまとめると、 期限欄は 1 つしか持てず、 途中の目安で上書きされて**行事の日付がどの欄にも無くなる**
  ([#single-deadline-field-many-legs](#single-deadline-field-many-legs))。 目安が過ぎると「期限超過」 の塊に沈む
- 期限の硬い手順 (失効型の書類) だけが独立の記録を持つと、 その回に触れる作業は**すべてそちらへ流れる**。
  期限欄を持たない手順は「次の締切は?」 の答えに一度も現れず、 その回を何度触っても思い出されない

**pattern**:

1. **期日は行事の日付から導く**。 手順ごとの「行事の N 日前」 を 1 か所 (規約の表) に書き、 検出器は**行事の一覧 (予定の正本) を読んで期日を計算する**。 回ごとの起票は要らない。
   起票の手順を守らせる規律 (「確定したら子を切る」) は残してよいが、 網の効き目をそれに依存させない
2. **済んだかは成果の記録で見る** (送った記録の名前・提出状態)。 TODO の状態では見ない — 状態は「待ち」 にされた瞬間に一覧から外れる
   ([#narrowing-makes-input-load-bearing](#narrowing-makes-input-load-bearing))
3. **その日の時点を再現できる形にする**。 成果の記録に日付があれば「その日より後の記録を数えない」 で過去の状態を出せる。
   これが陽性対照になる = **漏れた回を漏れた日の時点で再現して鳴るか**を、 設置した turn に確かめる ([#isolation-shortens-the-path](#isolation-shortens-the-path))
4. **こちらからの約束にも時計を**。 相手に「当日のご案内は改めてお送りします」 と書いた送信は、 受信側の予告
   ([#expected-inbound-tripwire](#expected-inbound-tripwire)) と対になる義務で、 送った瞬間に誰も覚えていない形になる。
   行事に紐づく約束なら 1. の期日がそのまま時計になる。 紐づかない約束は、 書いた turn に期日つきの記録にする
5. **会話で「未了です」 と報告しただけでは carrier にならない**。 状況の一覧を作った session が漏れを正しく言い当てても、
   その turn に記録か網へ載せなければ、 次の問い (「次の締切は?」) の答えは期限欄から作られ、 漏れは消える ([#surfaced-not-consumed](#surfaced-not-consumed))

**適用の見分け方**: 「この手順を思い出させるものは何か」 と問い、 答えが「その回の子の記録があれば」 なら該当。
過去の回の実施日と各手順の実行日を並べ、 規約の期日を守れた回の割合を数える — 低ければ、 仕組みではなく記憶で回っている。

origin: 定期講演会の告知と講演者への案内が、 開催の直前まで出ていなかった (実測)。 回ごとの子の記録で鳴る発火の仕組みは、
以前の同型の遅れを受けて作られていたが、 その回には子の記録が起票されず、 親の記録の期限欄は告知の目安で上書きされたまま過ぎていた。
同じ期間に複数の session がその回の事務書類 (独立の記録を持つ失効型の手順) を処理し、 うち 1 つは状況の一覧で「告知は未送信」 と
正しく報告していたが、 記録にも網にも載らなかった。 過去の回を並べると、 規約の期日を守れた回は手順によっては半数に満たなかった。

### <a id="catch-all-branch-absorbs-covered-class"></a>8.72 「未対応」 の受け皿は、 上流が既に扱う class を吸ってはいけない — 索引の miss を「resolver 未実装」 に降格しない

参照の検査器は「索引 (登録済の kind を全部読み込んだ表) で引く → 無ければ file system の resolver に落とす → resolver が知らない kind は None = ⚪ 記録のみ」 の 3 段で組まれることが多い。 このとき resolver の末尾の `return None` は「判定できない」 の意味だが、 **索引が扱う kind でここに来た**とは「索引に無かった」 = 参照先の不在そのものである。 その分岐を書き忘れると、 壊れた参照が低 severity の「resolver 拡張候補」 として恒常表示され、 読み手は「未実装の kind がある」 と読んで放置する。 実測: 索引が扱う kind の不在参照が複数、 低 severity の候補一覧に紛れて長く残っていた。 同じ検査器で同型の category error が別の入力でも起きていた (外部 URL の `:` を kind の区切りに食って「未対応 kind 'https'」 を出し続けた)。

- **受け皿の枝の前に「この class は上流が扱うか」 を問う**: 索引の (repo, kind) の集合を持ち、 resolver の冒頭でその集合に当たれば False (= 不在) を返す。 「呼び出し側が先に索引を引く」 という契約を resolver 側の注釈にも書く (= 索引 hit なら resolver には来ない、 来たら miss)。
- **key の表記ゆれは parse 段で正規化する**: schema の文書が小文字、 実装の索引が大文字、 のように表記が割れていると、 片方で書かれた参照は索引に当たらず同じ受け皿に落ちる。 登録済の kind については大小文字を問わず正規名へ寄せ、 両方の書き方を selftest に置く。 未登録の kind は触らない (= 誤って 🔴 に格上げしない)。
- **直す前の実装で陽性対照を赤にしてから直す** ([`#isolation-shortens-the-path`](#isolation-shortens-the-path) と同じ順)。 直した後は corpus 全体の finding を before / after で突き合わせる (新しい 🔴 が本物か 1 件ずつ、 消えた ⚪ が期待した集合と一致するか)。
- 同型 = [`#failure-exit-equals-violation-exit`](#failure-exit-equals-violation-exit) (故障と違反を同じ値にしない) の裏側: **不在と未判定を同じ値にしない**。 検出器を広げたら [`#detector-change-breaks-downstream-writers`](#detector-change-breaks-downstream-writers) (その前に立つ無人の書き手の過去の出力を通し直す)。

## <a id="environment-literal-placement"></a>24. 環境に依存する値は「配る物」 に焼かない — 実行時に導くか、 導けない形式なら install 時に生成する

### <a id="literal-placement-question"></a>24.1 判別の 1 問

配布される成果物 (script / 設定 file / job 定義 / app bundle) に literal を書く前に:

> **この値は、 受け取る全ての環境で同じか?**

同じでないなら literal にしてはいけない。 典型は home の path・user 名・機械名・host 名・arch・言語や地域の設定・外部 service の一時的な id。 ⚠️ **「自分の環境では動いている」 は「同じ」 の証拠にならない** — 配る物の正しさは、 書いた環境ではなく**受け取る環境の集合**で決まる (= [§10](#file-role-architecture) の観客の話が、 doc でなく実行物に現れた形)。

### <a id="literal-placement-three-ways"></a>24.2 三択 — 実行時に導く / install 時に生成する / 理由つきの literal

| 手 | 使う場面 | 注意 |
|---|---|---|
| **実行時に導く** | script・実行時に変数展開できる文脈 | 第一選択。 `$HOME` 等の変数、 または「自分の場所」 からの相対解決 |
| **install 時に生成する** | **形式が変数を展開しない**もの (= OS の job 定義、 GUI が読む設定、 署名済み bundle の中身) | 配る物は**雛形か生成器**にして、 実体は install 時に作る。 雛形を「そのまま copy する手順」 にすると literal が復活する |
| **理由つきの literal** | 値が literal でなければ機能しない時 | 下の 24.3。 **理由を隣に書く**までが 1 単位 |

⚠️ **形式が展開しない**ケースは見落とされやすい: 「変数で書けばいい」 と思って書いても、 その file を読むのは shell ではないので literal 文字列として扱われ、 **エラーにならず黙って別の場所を指す**。 配る前に「これを読むのは誰か (shell か / OS か / GUI か)」 を 1 度問う。

### <a id="justified-literal"></a>24.3 literal が正しい 3 つの型 — 消さずに理由を残す

「ハードコードを避ける」 を機械的に適用すると、 **literal でなければ壊れる所まで変数化して壊す**。 次の 3 型は literal が正しい:

1. **安定した一意の識別子** — OS の job label、 bundle 識別子、 名前空間。 環境ごとに変わってはいけない (= 変えると旧識別子が残って二重に動く)。 変更可能にするなら「変える前に古い登録を外す」 を手順に書く。
2. **展開しない API に渡す値** — 環境変数を展開しない CLI / 設定に渡す path は、 literal でなければ意図した場所を指さない。 その command を例として doc に書く時も literal のまま書く (= 読者が copy して壊れないように)。
3. **検査の検体** — 「この形の文字列を見つける」 検出器の test data。 変数化すると**検査そのものが弱くなる**。

⚠️ この 3 型は、 後から見た人 (や次の掃除) に「直し忘れ」 と誤認される。 **隣に 1 行で理由を書く**のが再発防止で、 理由の無い literal だけが掃除の対象になる。

### <a id="do-not-rewrite-records"></a>24.4 ⚠️ 記録は掃除の対象ではない

掃除の走査は、 **配る物**と**記録**を区別しないと記録を壊す。 記録 = 過去の状態の backup、 事故や作業の log、 受け渡しの記録、 実測の control。 これらの literal は**その時そうだった事実**であって、 書き換えると

- 「いつ何がどうなっていたか」 が復元できなくなる (= 後の調査の一次資料が消える)
- 実測の帰属が壊れる (= 別の環境で採った値が、 今の環境の値として読まれる)

掃除の走査は最初から**記録を除外**し、 除外したことを出力に書く (= 「見なかった」 と「無かった」 を分ける、 [§22](#silent-probe-false-healthy))。

### <a id="expansion-is-the-readers-job"></a>24.5 実装の罠 — 展開するのは書いた側ではなく読む側

変数を使うと決めた後に踏む罠:

- **引用符が展開を殺す** — 文字列を安全にしようとして単引用符で囲むと、 変数は展開されずに literal になる。 空白も変数展開も要るなら二重引用符。 ⚠️ 言語が用意する「安全な引用」 helper は、 たいてい**単引用符で囲む** = 展開を止める。 便利だからと使うと、 変数を書いたのに literal と同じ壊れ方をする (= 見た目は汎用、 実体はハードコード)。
- **展開する主体を取り違える** — 別の process にコマンド文字列を渡す構成では、 変数を展開するのは**渡した先**。 渡す側の言語が同名の変数を持っていても関係ない。
- **検証は「別の値で動くか」 で行う** — 自分の環境では literal でも変数でも同じ結果になるので、 差が出ない。 値を差し替えられる口 (= 環境変数での上書き) を用意し、 **上書きした状態で 1 度動かす**のが最小の検証。

### <a id="literal-placement-origin"></a>24.6 由来

実測: 常駐 helper の配布一式で、 ① helper 本体が呼び出す script の path に home が焼かれていた ② OS の job 定義が **home の絶対 path を持ったまま repo に追跡**されていた。 ② は「手順書に『雛形を copy する』 と書いてある」 形で固定化されていた (= 手順が literal を再生産する)。 対処は本節の三択どおり: ① は実行時の変数に、 ② は install 用の生成器を書いて雛形の配布自体をやめ、 手順書は生成器の呼び方だけを持つようにした。 副次的に、 手順書に並んでいた「落とすと壊れる option」 と「途中で止めると中途半端に残る」 の 2 つの踏み抜きも、 手順が script に移ったことで消えた (= [§8.12](#firing-surface-hierarchy) の「人の記憶を carrier にしない」 が手順書に現れた形)。 同じ走査で literal のまま残すべき 3 型 (24.3) と記録 (24.4) も出たので、 併せて規則化した。

---

---

## <a id="changelog"></a>変更履歴

| 日付 | 変更 | 動機 |
|------|------|------|
| 2026-09-22 | §8.71 新設「行事の日付から決まる手順は、 回ごとの起票でなく行事の日付から導く」 | 回ごとの子の記録で鳴る発火の仕組みが、 起票されなかった回で全部そろって黙り、 定期講演会の告知と案内が開催の直前まで出なかった (実測) |
| 2026-09-20 | §8.69 新設「『止まった』 は対照にならない — 故障の合図を違反の合図と同じ値にすると、 全部が止まる故障が陽性対照を緑にする」 / §8.70 新設「隔離のために環境を差し替えた test は、 意図より手前で落ちて緑になる」 | 関門の手前に立つ道具が起動に失敗し、 その失敗が「違反」 と同じ値で返ったため、 対象の操作がすべて止まった (実測)。 配線の test は一部が偽の緑になり、 症状が 2 方向に割れて見えた。 直す turn に足した対照が、 環境の差し替えで意図より手前で落ちて無意味になりかけた件も同じ整備で出た |
| 2026-09-19 | §19.5 新設「点呼行が 3 つ目の読み手を持ったら、 案件ごとに 1 つの状態 record へ育てる」 / §19.6 新設「凍結した記録は『渡した物そのもの』 として引用される」 / §8.68 新設「規則の写しは逐語 lint では追い切れない — doc が規則を書けない構造にし、 成果物は gate に決めさせる」 | 提出物を扱う道具が 5 つに増えた運用で、 状態が散文・file 名の印・入口 doc の表・人の記憶に分かれ、 凍結した記録が現物として引用され、 手順 doc の写しが正本より古い版で残っていた (実測)。 3 つとも既存節の続き (§19 = 点呼行 / §2 = 定義は 1 か所) として書き、 逐語 lint の限界を「構造で埋める + 成果物は gate が決める」 の形に整理した |
| 2026-09-18 | §8.67 新設「検査の緑は、 検査が問わなかった前提まで追認して読まれる」 | 成果物を丸ごと出す 5 段がどれも範囲を疑わず、 頁数の検査がそれを期待どおりと通した (実測)。 範囲の判断を作る時に成果物へ書き込み出口で読む形・推定の較正・出口を block にする理由をまとめた |
| 2026-09-18 | §8.66 新設「検査が列挙する単位を、 規則が守る対象の単位に合わせる」 / §21.1 に agent 別の写しの form / §8.12d に 4 つ目の形 (規則を場所で書く) | 規則は「agent が task を始める場所」 を対象にしていたのに検査が repo を列挙しており、 容れ物の dir だけが素通りしていた (実測)。 同じ整備で、 規約 file を別 agent 用に丸ごと写した入口 (置換が依存先の repo 名まで書き換え、 存在しない参照が残っていた) と、 場所で書いた push 規則が入口の整備まで止めていた形も出た |
| 2026-09-18 | §8.65 新設「入口の doc (README) に状態を写さない」 | 入口の doc に書いた状態の写しが、 状態を進める操作の経路に乗らず古くなっていた (実測)。 生成表・状態の語彙の lint・除外区間の崩れの検出・commit gate を同じ turn で入れた時の設計判断 |
| 2026-09-18 | §8.12d に 3 つ目の形「設計記録に『手作業で』 を置く」 (#manual-work-in-design-records) を追記 = 既存分の機械移行 (行単位 + 読み直し照合) と commit 時の停止までを 1 単位に | schema 変更で「既存分は手動移行」 と記録したまま、 件数を出すだけの lint の finding が増え続けた (実測) |
| 2026-09-17 | §8.62 新設「通常の周期の状態を警告にしない」 / §8.63 新設「観測できるものを推定で置き換えない」 / §8.64 新設「人に頼んだ操作の完了は、報告させず機械が状態で見る」 + `scripts/lib/browser_tab.py` | SSO 保護サイトを script で読む経路の login 切れ対応を作り直した時の判断の根拠。 予告と常時の赤は壁紙になり、 推定器は観測で要らなくなり、 本人の手数は操作 1 つに減った (実測)。 単一の領域からの一般化なので、 各節に適用範囲を書いた |
| 2026-09-17 | §8.61 新設「規則は在るのに、 行為の直前に効かない 4 つの入口」 | 規則が正本にも読み込み面にも在ったのに行為の前に効かなかった near-miss の RCA から、 経路の形で直る 4 型を分けた (実測) |
| 2026-09-15 | §8.58 新設「期限欄は 1 つ、手順の期限は複数」 / §8.59 新設「表示を絞る変更は、絞った後に残る入力の正しさを load-bearing にする」 / §8.55 の落とし穴 4 に指紋、 落とし穴 5 (2 条件の関門と語彙) を追補 / §8.56 に変種 (作業中に読んだ義務) と数える道具 + `scripts/lib/ja_deadline_dates.py` + `scripts/injection-reach-audit.py` | 記録の構造 (1 つの期限欄に複数の手順) と表示の条件の組み合わせで、 本物の期限が表示に出ない状態が続いた RCA から。 期限の抽出語彙の穴、 作業中に期限を読んだ agent の扱い、 注入を絞る条件の外に落ちた記録の消え方も同じ RCA で確かめた (実測) |
| 2026-09-15 | §8.55 新設「経過日数で強める印は、期限の近い義務ほど弱く付く」 / §8.56 新設「表示を読むのは agent、義務を負うのは人」 / §8.57 新設「『期間が過ぎた』 は不在の主張」 + §8.24 と §8.19 に参照 | 期限の短い依頼の失効 RCA。経過日数の印で下段に置かれ、注入の量に埋もれ、別件名で届いた後続を見ずに閉じられた。同型の RCA が毎回「検出を足す」 形だったことも振り返った |
| 2026-09-15 | §8.12e 新設「復旧は命令の再実行でなく状態遷移」 | 起動済みの singleton application に fresh instance を強制する browser adapter が、profile 引数を通す局所目的は持ちながら新 process を反復 crash させた。`absent / healthy / transport failure / wrong context / unknown` を分け、状態保存順に遷移を選ぶ kernel へ一般化。単一製品 family 由来なので適用範囲も限定した |
| 2026-09-15 | §8.12c に media delivery の最終状態を追補 | 対象言語 TTS の生成・tool 側 player の再生は成功したが、user の chat / panel に再生ボタンが存在しなかった。生成成功と提示成功を同じ完了扱いにしたため、最終応答の direct audio link まで運ぶのが遅れた。新原則を増やさず、既存の completion-boundary state gate に適用例として昇格 |
| 2026-09-14 | §8.52 の対策 5 に 2 項追補: #pointer-needs-reader-access (参照を足す前に読み手が正本を読めるか) / #unreferenceable-copy-is-blind (参照を足せない書き写しを許すと死角 → 縮める・生成する・死角として受け入れて注釈に下流 file を書く) | 露出した書き写しを「全部に参照を足す」 と提案し、 うち 1 件が読み手の広い場所にあって参照が依存になると後から気づいた (実測) |
| 2026-09-14 | §8.52 新設「目印の文字列で重複を探す検出器は、 目印と『参照あり』 の判定の両方が黙って死ぬ — 登録簿そのものを機械で点検する」 | 個人層の正本重複検出器で、 語を目印にした topic・参照判定に目印が含まれて永久に鳴らない topic・一般語を参照とみなす topic・正本から目印が消えた topic が、 すべて finding 0 のまま残っていた (実測)。 移し替えを手作業で済ませた後、 点検を検出器と登録道具に組み込んだ |
| 2026-09-14 | §8.51 新設「検出器に鳴らされた文が欠陥とは限らない — 規約どおりの使用なら、直すのは検出器で、原文ではない」 | 正本の重複検出が語の使用に鳴った箇所を、 対処文どおりに本文側で直そうとして原文を書き換えた (本文への変更を戻し、 検出器の目印を定義文へ移した)。 対処文が本文の変更しか示していなかった |
| 2026-09-14 | §8.45「規則の穴から生じた迷いを owner の判断として中立に渡さない」 / §8.46「意味の検出器の承認を行の hash に縛る」 新設 + §8.42 に実例 | 公開 repo に載っていた owner の活動の事実を推奨なしの質問で渡した件と、 その後に作った活動の事実の検出器の設計から |
| 2026-09-14 | §20.5.4 新設「派生値を入力の隣に書くなら、 書く時に計算する」 + `scripts/check-duration-beside-dates.py` | 例示 sweep の副産物の「13 ヶ月」 (実際は 35 日) を直した後、 同じ型を 3 repo で走査して窓の前後逆を 1 件見つけた。 どちらも入力が後で変わったのでなく、 書いた時点で計算していなかった (§20.5.2・20.5.3 の「後で腐る」 とは別の型) |
| 2026-09-14 | §8.44 新設「規則は、それを破る行為をする session が読み込む場所に置く」 + §8.3 / §8.12a′ / §8.34 に実例 | 公開 repo の例示に未公開原稿の文が 1 週間で 3 回上がった RCA。規則は在ったが、行為をした session の読み込み面に無かった (初出は違反 commit の 33 分後)。同じ夜に配線漏れと marker の設定漏れも見つかった |
| 2026-09-13 | §8.43 新設「sweep の「無い」 は、探している class の形ごとに陽性対照を通してから信じる」 | 同じ日に独立 2 件 (位置で定義される参照形の規則を違反の一形で掃いた grep / 探している書き方に一致しない正規表現)。§9.8 の複数事例を満たしたので、族の実例でなく節にした |
| 2026-09-12 | §8.12 に「手動の入口 script」 tier と循環の警告を追加 | user「必ず読むリポ設定の肥大化は大丈夫そ?」 から実測したところ、auto-load される規律 file の肥大検出器が**入口 script (dashboard) にしか配線されていなかった**。その検出器は「過去 2 回とも発見が人間の手動だった」 ことを動機に作られたものなので、発火面を「人が見に来る」 に置いた時点で元の失敗を再生産していた。CI からも走るが finding が warn で exit 0 なので緑のまま埋もれる (= §22 の表示版)。kernel = 発火面 hierarchy の 3 と 4 の間に「手動の入口」 tier が在ること + **安全網をそれが覆う失敗モードと同じ経路に依存させない** + 検査を書いた turn に「誰の・どの event で走るか」 を 1 行で答える。対処は同じ engine を session 開始の surfacer に配線 (閾値内は沈黙なので noise 増ゼロ)。instance は個人層に残置 |
| 2026-09-12 | §8.42 新設「検出器が literal で持つ signal は、その検出器について書かれた文章にも現れる」 | user「機械で警告が出る件はなんとかならんか」。実体は検索 null の nudge hook が検出語を素の部分文字列で探しており、**その hook 自身の source を grep した出力**で自己発火していた。同日、別 session が URL guard で同型を path 除外で処理しており、漏洩 gate の「pattern 一覧を同じ repo に置かない」 規律も同じ kernel と判明 (n=3)。kernel = 対策 2 つの射程差 — path 除外は**走査型**にしか効かず、tool 出力を見る検出器には外す file が無いので**構造 anchor** が唯一の手。落とし穴として「同じ error でも文脈で形が変わる」 (実測で 3 prefix) を明記。放置すると FP が保守作業に集中し §8.24 壁紙化の最短経路になる。instance は当該 hook の anchor 実装と回帰 test に残置 |
| 2026-09-12 | §22.3 に pattern 5 追加「悪循環は閾値では解けないことがある — 待つ時間と仕事の時間を分ける」 + §22.4 に由来 (第 4 例) | §22.1 が予告していた正のフィードバック (= 溜まるほど重く、重いほど打ち切られ、打ち切られるほど溜まる) が**実際に回った**初の実例。論文 PDF を commit する共同研究 repo が 4 日で 137 commits / 234 MB 溜まり、8 秒の per-item timeout に対し実測 32 秒で毎回打ち切り = 進捗ゼロを数日反復。pattern 3 は入っていたので「未完了」 とは出続けていた = **検出はされていたが自力回復できなかった** (kernel = 報告できることと回復できることは別)。閾値調整は呼び出し側の上限 (全体 watchdog 25 秒) に阻まれて成立しないと分かり、打ち切り後に detach して裏で完走させる経路を pattern 5 として一般化。新設せず §22 への追補にした = 観察・remedy とも同じ kernel の続き ([§2](#no-duplicate-rules))。instance は layer 1 の同期 script に landed。user 依頼「すべてのスクリプトと知見をなるべく上層に」 |
| 2026-09-12 | §8.41 新設「保存する rule の key に per-call 一意な値が混ざると、その rule は二度と発火しない」 | §8.19 (読み側の key 軸) の書き側。user「いちいち聞かれる。直したはずなのに直ってない」 の実体は、1 週間前に押した「常に許可」 が session UUID + 乱数 file 名を含む literal として保存され、二度と一致しない状態だったこと。症状が「対処したのに効かない」 なので、**同じ対処を繰り返す**のが最も自然な誤対処になり、死んだ entry だけが増える。判定は「次に同じ場面でこの key は literal 一致するか」、対処は glob を受け付ける別の保存面へ経路を替えること。機械化 = `permission-dialog-audit.py --diagnose` の `rule_unique` |
| 2026-09-12 | §8.40 に第 2 観察を追記 (別条件下の観察を無条件の「実測」 として書く) | 同節の n=1 を n=2 に。承認 dialog の内訳を `--no-run-hooks` (= 速い測り方) で測り、出た 21 件を層 1 doc に「実測」 と焼いた (既定 mode で取り直すと 3 件)。**script は自分の出力の冒頭で毎回その旨を印字していた** = 但し書きは目の前にあったのに数字だけ引き写して落ちた。kernel = 速さのための flag で得た数は、載せる瞬間に既定 mode で取り直す / 取り直せないなら flag 名を数字に添える |
| 2026-09-12 | §19.4 追補「一括生成の完了イベントが個別適用の未了を隠す」 (= §19 の第 2 の消失経路。新設せず既存 kernel への追補にした = remedy が同じ点呼行なので §2 の重複回避) + §8.38 に参照実装 (`--ack` / `--ack-control`) の pointer + §8.39 から §19.4 へ相互 link | 同 incident の掘り下げで、落ちた 1 手と落ちなかった 3 手の差が「一括生成か個別編集か」 だったと判明。生成の完了イベントは真なので記録上は「完了」 と区別できず、適用の未了を数える表現がどこにも無かった。remedy の置き場だけが §19 と違う (= 点呼行は生成物側でなく適用先ごとの記録に置く、でないと再び 1 個に畳まれる) ので、その差分を追補として明記。user 依頼「すべてのスクリプトと知見をなるべく上層に」 |
| 2026-09-12 | §8.40 新設「doc の一文は『測った』 と『説明した』 を書式で分ける — 説明は観察の権威を借りる」 | §8.38 と同じ incident の第 3 面。検査が 1 対象に出した ✗ の**説明**として立てた仮説が、同じ turn のうちに script の docstring へ「(実測、2 件とも)」 という形で焼かれ、同日 layer 1 にも landed した (実際には測っていない)。4 日後、その一文は別 session の診断の前提になり、**user への助言 (「画面を目視するしか検証手段が無い」) にまで伝播**して、独立の再実測で初めて覆った。伝播経路のどこにも「これは仮説だ」 と読める手がかりが無かったのが本体。kernel = 観察文と説明文を分ける / 「実測」 の scope は走らせた対象と一致させる / **検出器を黙らせる根拠になる主張は実測でなければ書かない** (= 失敗が沈黙になる class なので敷居を上げる) / 下流は書式で信じる。§2.6 が「いつ真だったか」 を要求するのに対し本節は「どうやって知ったか」 を要求する。forensics で確定した事実: 反証 (= 同じ様式の別対象が ✓) が同じ dir に置かれてから誤った一般化が docstring に 書かれるまで **2 分 20 秒**、かつその一般化は**書かれた時点で既に、当時の script 自身によって偽**だった (当時版を当時の artifact に当てて再現済)。user の問い「前回もダウンロードして検収したよな? なんで見落としたんだ?」 が起点 |
| 2026-09-12 | §8.38 新設「『偽陽性だ』 の宣言は主張である — positive control を出せないなら未検証」 + §8.39 新設「完了の記録は相手が返したものから作る」 + §8.9 / §8.32 から相互 link | layer-3 の申請 session で、入力後の突合 script が出した 9 件の ✗ を「この様式では印字されないから偽陽性」 という**確かめていない構造説明**で全部無効化して送信し、機関事務から**同じ指摘を 2 度**受けた。反証 (= 同じ様式の別対象が全行 ✓) は宣言の 1〜2 分前から同じ dir に在り、免罪は 16 分後に layer 1 へ「2 件とも実測」 として landed (= していない測定が実測として記録された)。§8.38 kernel = 免罪は自己隠蔽・class 全体に効く・寿命が長い、ゆえに (a) positive control (b) 別経路での直接観測 (c) どちらも不能なら「未検証」 の第三状態、+ 機械側は「不在」 でなく**対立値**を出す。§8.9 (detector の filter) との違いは「run 出力のその場の無効化は code にも doc にも残らない」 点。§8.32 の双対。同じ事故の 2 件目として、完了記録が**上げるはずだった artifact** から作られ、システムが返した反証と同じ dir に同居していた (+ 手順が要求する 8 個中 4 個しか集まっていないのに検査が「✓ 全項目一致 — 送信してよい」 を出す) ことを §8.39 に。evidence base は 1 事例だが blast radius (= 層 1 の誤りは毎年効く) で landing を判断。instance (verifier / 手順書 / 台帳) は個人層・project 側に残置 (kernel-up / instance-down)。user 依頼「完璧にしてくれ」 |
| 2026-09-11 | §8.35 新設「resolver 出力は新しい trust boundary」+ §23 に field-wise `unknown`、保証値欠測のwarning、shared resolver所有を追記 | Codex Git-hook rollout で同じ session に二方向の resolver defect を観測: (a) `--repo-root` 内 candidate が symlink/Git解決後に root 外 checkout となりbulk write scopeを脱出、(b) `git rev-parse --git-path hooks` のrelative resultをcaller cwdへ誤anchorし、別repoのhookをMISSINGと誤報。入力検査→resolve→owner基準anchor→canonicalize→最終targetで再認可、を一般化。併せてCodex冒頭stampでaccount/effortが取れないため全stampを消すのでなく、host/surface/session/modelの既知fieldを残して未知fieldだけ`unknown`にする形を§23へ昇格。follow-up でactive modelのfallbackとwarningを追加し、一度はhard blockへ振ったが、「通常は取れる」と「絶対に欠測しない」は別でありprovenance縮退はcommit本体を不正にしない、というowner指摘でfail-openへ戻した。さらにstamp/cache/Gitの3 consumerに重複していた解決順をshared resolverへ集約した。instanceはCodex技術正本とinstaller/testに残置。user依頼「すべてのスクリプトと知見をなるべく上層に」 |
| 2026-09-09 | §23 新設「必須にした field は、値が無いとき捏造される — 『無い』を機械可読にする第三の状態」 | layer-3 の TODO surface 機構で、「本人操作が要る item には deadline を必ず添える (自己設定で可)」という規約が、本来いつやってもよい作業に**拾わせるためだけの日付**を書かせていた。実測すると該当 6 件中 3 件が捏造で、本物の失効型期限 1 件がその中に並んで最上位 group に置かれていた (= 捏造が本物の信号を薄める狼少年)。owner が「なんで期限とかあるの?」と問うて初めて表面化 — 機構の内側からは捏造も本物も同じ「日付を持つ item」にしか見えない。kernel = 出自を宣言する第三の状態 + 設計要件 4 つ (無記載 = 従来の意味で移行不要 / loud 側 default / 「静かにする」であって「消す」ではない / 判別が自然言語なら機械化不能と declared) + 見分ける問い「値が無い item に書き手は何を書くか」。§8.28 壁紙化の上流にある別型 (cadence でなく severity の出自)。instance (marker field / 表示 tier / 除外する 3 経路) は個人層に残置 (kernel-up / instance-down)。user 依頼 (「すべての知見をなるべく上層に」) |
| 2026-09-09 | §22 新設「安全網が自分で使う probe の失敗は、健全と同じ姿の答えに化ける」 | layer-3 の session 開始 hook で、3 つの repo が 39 / 119 / 238 commits 遅れたまま放置され、別目的の検査がその古い手元を読んで落ちたことで偶然発覚。3 つとも「clean なら自動同期」の条件を満たしており、機構は在ったが手前の probe (並列 fetch) が per-item timeout / watchdog で打ち切られ、失敗を `\|\| true` が潰していた → 手元が更新されないまま「差分 0 = 同期済み」に化けていた (= silent failure ではなく **false healthy**)。しかも差分が溜まるほど probe が重くなり打ち切られやすくなる正のフィードバック付き。kernel = 失敗値が健全値と同じ形になる class の識別 + 4 pattern (成功を marker に記録して不在で検出 / 測れなかったことを測った結果と同型にしない / fail-open は報告付き / 閾値調整は観測後)。併発した第 2 の穴 (「手当てが要る」一覧が一部 frontend で honor されない経路にしかない) は §12 暗黙 scope の表示版。事故構造を再現する test を置き旧実装で FAIL することを確認済。instance は個人層に残置 (kernel-up / instance-down)。user 依頼 (「すべての知見をなるべく上層に」) |
| 2026-09-02 | §20 新設「規則は前提より長生きする — 上流属性の切替は下流定数の一括再判定を要求する」 + §21 新設「同一 rule の variant は片方だけ更新され silent に stale 化する」 | layer-3 の事務運用 session で独立 2 件を観測: (a) 費用の出所が別制度へ移った後も旧出所の承認者を要求する規則と、 それに紐づく様式定数群 (制度名 / 番号 / 責任者 / 押印欄) が default 表に残存 — user の「これ何で要るんだっけ?」 で初めて出典を遡り前提失効が判明 (b) 手順書が新運用に全面改訂された際、 別言語 section の文面 sample だけが旧運用の値のまま残置。 §20 = 出典に「どの前提の下で」 が落ちる → 規則だけ生き残る機序 + 5 pattern (premise 併記 / 切替 doc に再判定欄 / 期間は終端を焼く / 「なぜ要る?」 を detector 扱い / 前提に紐づく定数を 1 表に束ねる)。 §21 = 同 session で「英語版 template 不在ゆえ規約で足した項目が個別起草に依存して落ちた」 実害から、 variant は正当な重複ゆえ §2 の削除方針で解けないことを明示し 3 択 (持たない / 生成する / parity gate) を整理 — remedy 3 は同 owner の別軸 (正本 doc の全 § に配布判断を強制する gate) で実証済。 instance は個人層・共有 project に残置 (kernel-up / instance-down)。 user 依頼 (「すべての知見をなるべく上層に」) |
| 2026-09-01 | §8.27 新設「user-execution handoff — 最終 leg が人間本人にしかできない義務の手渡し機構」 | layer-3 の授業評価フィードバック deep RCA (= draft + 共担者レビュー完了済みの提出義務が、 レビュー返信未記録 → 「代行不可」 responsibility sink → 委任下の見送り close 〔全学公開の記録を読まず「低 stakes」〕 → close が thread 監視も切断 → 66 日後に第三者指摘で顕在化) を一般化。 4 段 kernel (readiness 同 turn / packet 1 行 / forced-disposition + 人間 channel / 「代行不可」 は probe + packet 併記) + close-kills-the-net + 委任は可視の不作為を cover しない (催促強度 ≠ stakes = §8.8 disposition 版)。 生存 sibling 2 + 隣接 1 + close 事故 2 例で §9.8 充足。 instance (marker field / gate script / cadence 実装) は個人層残置 (kernel-up / instance-down)。 user 依頼 (「すべての知見をなるべく上層に」) |
| 2026-08-31 | §19 追加 (点呼行 = 散文 sub-obligation の脱落防止 marker pattern) | 宿泊証明書 (取得窓が滞在中に閉じる) と 印刷版 (紙の vintage、 2026-08-31 paper-staleness 3 例目) の 2 instance から meta-pattern を抽出。 固定 grammar 1 行 + absence-flagging 検出器 + stock sweep。 instance 実装は個人層 (kernel-up / instance-down) |
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
| 2026-06-13 | §2.3 新設「SoT の read 側」 | ある案件の status を問われ source document (個人 account のメール通知) を SoT と取り違え、 null から作話で誤結論した RCA を一般化。 §2.1/§2.2/§15 は write 側 (二重に作るな) だが read 側 =「source document の null は答えでない / session 開始時 context window は案件について空 cache / null の第一仮説は『読む store を間違えた』」 が未収録だった。 同日 sibling (cite-me lookup 不発 §8.12 / labnexus burn-down の lookup-context 不実施) と合わせ 2+ 観察 (§9.8 充足)。 layer-3 機械対策 = account routing guard + matter-status SoT-read dispatch (instance 残置 = kernel-up / instance-down) |
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
| 2026-09-07 | §8.33 新設「新しい protocol は最頻・低 stakes の行為を protocol 内で最安にする — 迂回路は初日に現れる」 | layer-3 の session 宛て board v2 で両 vendor が初日に旧形式の手 commit へ迂回 (request 不要の状況共有が無かった) → inert な note kind + 混在許容で design-out |
| 2026-09-12 | §8.37 新設「他人名義で出した依頼の返信は、自分の受信箱に来ない — Cc は送信の証拠であって返信の網ではない」 | layer-3 で第三者が起草し本人名義で出した対外照会 (起草者は Cc) について、送信文面は Cc で正本化できる一方、返信は reply-all されなければ届かず、「返信待ちの outbound」 検出器は母集団が *自分の* 送信済 mail なので構造的に射程外、と判明。thread probe の沈黙が「未回答」 と「相手にだけ届いた」 の両義になる点で §22 (probe の失敗が健全と同じ姿) の入力面版、来るはずの inbound がそもそも自分宛でない点で §8.30 (expected-inbound tripwire) の変種。対策 = 検出器を通すために category を偽らない (= done_evidence が嘘になる) / carrier を時計 + 「送信者本人に訊く」 に載せる / probe の隣に「これでは未回答を判定できない」 を書く / 送信前に返信先を設計する。user 依頼 (session close の層1 hoist)。 |
| 2026-09-14 | §8.40 新設「粗い 1 件が中身を隠す — 「埋まっている」 は「検討した」 ではない」 | layer-3 の学会聴講計画で、 session 丸ごとを 1 event にした block が gap 計算上 busy になり、 **窓の中の個別講演が候補検討の射程から丸ごと落ちていた**。 姉妹 = 日時つきの常設ミーティング案内が 高 volume ML の digest 1 行に畳まれて消費されなかった件 (= 検出器の隙間)。 母集団を自分の出力の「隙間」 に取ると 占有が検討済みの proxy に化ける、 と一般化。 §8.8 (proxy 型) の母集団版・#firing-surface-hierarchy の入力面対。 対策 = 一次資料を母集団にする / 集合であることを機械可読に / 便宜でまとめない / 展開したら元を畳む。 user 依頼。 |
| 2026-09-14 | §8.50 新設「検出器が読む「人が書く一覧」 は育たない — 設定も SoT から導出し、 追随と死活を別々に検査する」 | 公開 repo の literal 照合の段が配線済みなのに一覧が空で、 守るべき class を stage しても実 hook が rc=0 で通った (実測、 temp repo と実 repo の 2 通り)。 一覧は ignore された machine-local の手書きで、 空のとき出る skip の 1 行は毎 commit 出るため noise に紛れていた。 「一覧が空」 は「対象が無い」 と同じ顔をする = §22 (probe の失敗が健全と同じ姿) の config payload 版・§8.34 (分岐の設定漏れ) の中身版。 対策 = SoT から生成 / 追随と死活を別検査 / 死活は実測 (検出されること + 無関係は通ること) / 生成物は ignore のまま各機で再生成 / 出力に項目を書かない / stoplist は ratchet。 実装 = 層1 `scripts/build-sensitive-terms.py` (config は個人層)。 user 依頼 (「いちいちスイープするとかじゃなく予防を」)。 |
| 2026-09-19 | §22 に第 4 例「capability probe の空を『非対応』 に畳むと silent な機能後退になる」 を追加 | 常駐 server の installer が `<cli> <subcommand> --help` の grep で flag 対応を判定していたが、 その CLI は未認証だと `--help` でも 1 文字も返さず即 exit する = 認証切れ中に再実行しただけで命名が黙って外れた構成が書き込まれた (実測)。 第 1〜3 例と同じ「1 つの空値に 2 つの意味を畳む」 だが、 結果が沈黙でも余計な動作でもなく **silent な機能後退** (出力は壊れず install は成功で終わる) である点が新しい。 一般形 = capability probe は 対応/非対応/**判定不能** の 3 値で、 判定不能を非対応に畳むと環境の一時的劣化が構成の恒久的劣化になる。 対策 = 空を先に分岐 / 既存構成を証拠として引き継ぐ / どちらの経路でも警告を出す。 実装 = 層1 `scripts/install-remote-control-server.sh`。 user 依頼 (「考え方も含めて正本と参照を整備、 なるべく上層に」)。 |
| 2026-09-20 | §24 新設「環境に依存する値は『配る物』 に焼かない — 実行時に導くか、 導けない形式なら install 時に生成する」 | 常駐 helper の配布一式で、 helper が呼ぶ script の path に home が焼かれ、 OS の job 定義は home の絶対 path を持ったまま repo に追跡されていた (実測)。 後者は手順書の「雛形を copy する」 が literal を再生産する形で固定化していた。 三択 (実行時に導く / install 時に生成 / 理由つき literal) + **literal が正しい 3 型** (安定した一意の識別子・展開しない API に渡す値・検査の検体) + **記録は掃除の対象でない** (backup / log / 実測の control を書き換えると一次資料と帰属が壊れる) + **展開するのは読む側** (安全な引用 helper は単引用符で囲むので展開を殺す = 見た目は汎用・実体はハードコード) まで含む。 §10 の観客の話が実行物に現れた形・§22 の「見なかったと無かったを分ける」 が走査の除外に現れた形。 user 依頼。 |
| 2026-09-20 | §8.12 に「配線した瞬間と、 効き始める瞬間は別」 (#wired-is-not-yet-firing) を追加 | 検出器を別の機械へ配る作業で、 「pull すれば効く」 が面によって正しくないと分かった (実測): session 開始時に読まれる設定に登録した hook は**次の session から**、 実行のたび source を読む入口は**即時**、 自動発見される test は**runner の次回起動**、 無人の定期実行は**次の発火時刻**。 含意 3 つ = 「配って終わり」 の前に最初に鳴る機会を面ごとに答える / 配線直後に鳴らないのを壊れたとも動いているとも誤診しない (死活は壊れた state の注入でしか確かめられない) / 遅れの無い面を併設すると待ち時間が実質ゼロになる (§8.12 が 2 面を勧める理由が遅延の面でも効く)。 user 依頼。 |
