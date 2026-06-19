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

**pragmatic relaxation (bundle rule):** 「1 ルール = 1 ファイル」の厳格適用は 1 行ファイルを生む。**関連密接かつ合計 10 行未満のルールは bundle 可** (配置先は影響範囲の最大公約数に従う)。例: `odakin-prefs/project-structure.md` は作業ディレクトリ宣言 + 配置ルール + preview リンク出力を 1 ファイルに束ねた (2026-04-06 の `~/Claude/CLAUDE.md` 解体時の判断、`claude-config/DESIGN.md §~/Claude/CLAUDE.md の symlink 化` 参照)。

---

## <a id="no-duplicate-rules"></a>2. ルールの重複を避ける：定義は1箇所、他はポインタ

同じルールが複数箇所に書いてあると、修正時に全箇所を直す必要がある。忘れると矛盾が生じる。

**原則:** ルールの定義（WHAT/WHY）は1箇所だけ。他の箇所からはポインタで参照する。

```
CONVENTIONS.md §5.7 ← ルールの定義（WHAT: 確認せよ、WHY: 不可逆）
    ↓ ポインタ
conventions/mcp.md  ← 手順の詳細（HOW: get_profile を実行）
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

判別フロー: **正本そのものの誤り → 本文を是正**（§2.2、marker でなく書き換え）/ **削除可能な決定記録**（価値が別所に抽出済 + git が履歴を保つ）**→ §7.2 で削除** / **削除不能な忠実履歴**（falsify せず残す要）**→ 本節 errata marker**。errata marker は「保持必須の非正本記録」専用で、正本や DESIGN.md entry には使わない（§7.2「※注釈で本文温存しない」と矛盾しない — 対象が別物）。

origin: 2026-06-18 — 研究費様式の交通費記入ルールを是正した session。確定版を SoT（規約 md）へ書いた後も既存 TODO 2 件が旧暫定を live で肯定していた（= §2.2 sweep で発見し本文是正）。加えて**削除できない履歴**（事務担当宛の送信済メール draft / 過去の打診記録）に旧暫定が残り、こちらは是正でなく errata marker で「当時の誤り」を明示し本文は温存した。user 指摘「過去の誤った判断・知見には『これは誤り』とあとで分かる注を、上層で規律化してよい」。

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

### <a id="motivated-substitution-trap"></a>4.1 指定された成果物・手段から逸脱する時の self-justification trap（motivated substitution）

タスクが**特定の成果物・手法を名指す**とき（「X を実装して」/ plan に「手法 Y」と明記 等）、より一般的・印象的・自分好みの別手法が思い浮かぶと、LLM は**逸脱の正当化を後付けで製造**しやすい。起点は「目標（outcome）」を最適化して「指定された手段（named deliverable）」を交換可能と見なすこと。§4 の「orient before act」が *事前確認のスキップ* を扱うのに対し、こちらは *（誤って）orient した後に、別物へ静かにすり替える* failure。

**なぜ特に危険:** 逸脱先がしばしば本当に有用な副産物を出すため「良い判断だった」と誤学習する。正当化は粘り、**事後分析（post-mortem）まで生き残る**（「でも技術的には正しかった」という逃げ道として）。silent な置換は依頼者が気づいて差し戻す手間を生み、「X をやる」と言った時に毎回成果物を検証させる＝信頼の侵食。判断自体が良くても、**黙って差し替えた**ことが failure。

**正当化に頻出する欠陥（逸脱を信じる前の自己尋問）:**
1. **strawman 比較** — 代替を、指定手法の*本物*でなく、その劣化版（＝一番手近な naive 実装）と比べていないか？（最頻出。「本物はもっと良い／同じ利点を持つ」を見落とす）
2. **輸入された美点** — 代替の「利点」は*この課題*の利点か、隣の課題から借りてきた非問題の解決か？
3. **別の問いへのすり替え** — 代替は*指定された問い*に答えるか、自分が好きな別の問いに答えているだけか？（しばしば指定タスクを解いてすらいない）
4. **impressiveness バイアス** — 手法を「結果が definitive／publishable になりそう」で選んでいないか？（課題適合でなく見栄えの最適化）

**対策:**
- **名指しされた成果物は load-bearing として扱う。** 着手前に「タスクは "X"」と*名前で*再唱し、自分の plan が **outcome 一致でなく name 一致**かを照合する。
- **より良い案があるなら「置換」でなく「併設＋明示」。** 指定物を出す＋代替を理由つきで提示＋依頼者に選ばせる。silent に差し替えない。
- 検証規律（CONVENTIONS.md §3）/ §9.8（単一観察から構造対策に飛ばない）/ §8.14（単一一致で同定しない）と同族 = いずれも「安価な照合を先に回して、自分の飛躍を捕まえる」。

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

**頻出する 2 種の proxy**:

| proxy 型 | 仕組み | 盲点 | 事例 |
|---|---|---|---|
| **keyword / registry whitelist** (= list-based audit) | 登録した語/topic だけ flag | **list 外**は全て素通し | `check-sot-drift.py` (登録 anchor token のみ) / `check-i18n-drift.py` (登録 field のみ) / 「記入要領を消したか」 を phrase list で照合 |
| **継承・上書きされうる surface 属性** | 要素の直接属性だけ読む | 別の場所 (style / 親 / config) で設定された値を見落とす | docx の run **直接色**だけ見る → 段落 style 継承の色を素通し / 変数の local 値だけ見る → 環境/config の override を見落とす |
| **委譲した調査の結論** (= subagent / 別 agent に投げた grep / audit の return) | 限定 scope を調べて結論 (特に「異常なし」「drift なし」) を返す | subagent が **調べなかった軸 / 範囲** を黙って「なし」 に含める (= 調査軸の盲点 = 結論の盲点)。 negative 結論ほど false confidence が大きい | agent に「X に drift あるか」 委譲 → 「なし」 だが、 自分で広く grep したら複数発見 (= agent の照合軸が狭かった)。 → subagent の **negative 結論は ground truth でなく**、 安い再 verify (= 自分で grep 1 本) を通してから採用する (= §3 単一情報源 null 飛躍の subagent 版) |

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

reflex: 構造化データを read して何か (特に削除/上書き) する script を書く時「入力が parse 失敗したら、 これは空として進むか? それは破壊的か?」 を問う。 fail-empty が destructive path に繋がるなら fail-loud + abort に変える。 cf. `conventions/data-pipeline-automation.md §1` (= SoT invariant を経路非依存 commit gate で enforce = 生成 script の guard が手動編集をすり抜ける問題の対) — 本節は consume 側の双対。

origin: 2026-06-09、 編集時 gate (= 編集後 yaml parse 検証 hook) と consume 側の fail-loud pre-flight (= 監視 yaml が 1 件でも parse 不能なら破壊的 label 除去を中止) の 2 本を実装。 ⚠️ 根拠は **直接事故 1 件** (本 yaml 破損 → fail-empty で破壊的誤動作) + §1 (生成側 gate) という **sibling 原則** であり、 §9.8 の「2 独立観察」 には厳密には届かない (= 直接観察は 1 件)。 ただし fail-loud / 編集時検証 は確立した一般原則で、 既存 §1 と双対をなすため layer 1 に置く (= 過度な一般化でなく、 既存原則の欠けていた対辺の補完)。

### <a id="downstream-net-intake-leverage"></a>8.11 downstream の安全網は intake で正しく表現された対象しか守れない — leverage は上流にあり、しばしば判断 (= 機械化不能)

§8.8-8.10 は mechanism の **実装** 品質だった。 本節は mechanism の **配置**: surfacing / detector / 通知のような **downstream の安全網は、 対象が intake (= 取り込み・登録時) で正しく表現されている前提**で動く。 追跡すべき X が intake で **下位概念に mis-encode** される (= X をその手段 Y として登録 / 締切を proxy で埋める / 優先度を取り違える) と、 その fact は **そもそも安全網が掴む形で存在しない** ので、 downstream の網をどれだけ足しても捕まらない (= 「網が見るべきものが、 網の見える場所に無い」)。

帰結:
- **failure に downstream 検出器を足し続けると whack-a-mole**: 各 fix は「前回の失敗の正確な形」 を塞ぎ、 次は隣の未カバー領域に落ちる。 検出器 fleet の増殖は「leverage が上流にあるのに下流で叩いている」 症状 (= §9.2 の予防一辺倒肥大化と同根)。
- **最大 leverage は intake の encoding を正すこと**: 追跡対象を「それ自身」 として登録する (下位手段でなく) / proxy でなく本物の制約を入れる / 不明なら **能動的に確定する**。 これは多くの場合 **意味判断**で hook 化できない (= 「この登録は対象を取り違えているか?」 は機械に解けない)。
- ゆえに downstream mechanism は「正しく encode された対象の **信頼性**を上げる」 もので「mis-encode を救済する」 ものではない、 と役割を限定する。

reflex: 見落とし failure に downstream の検出器/通知を足す前に「対象は intake で正しく表現されていたか? 失敗は **配置** (= 上流の encoding) か **実装** (= 下流の網) か?」 を問う。 配置側なら、 網を足すより intake の規律 (= 機械化不能でも登録時に正しい形を作る judgment discipline) を主にする。

origin: ある追跡システムで「期限つき義務」 が複数回見落とされた事例の連鎖。 毎回 downstream の網 (= 到着 trigger / 締切 surface / 返信 handback 検出) を 1 つずつ足したが、 各々「前回の正確な形」 を塞いだだけで次が隣の死角に落ちた。 根は intake で義務が下位ロジ (= 調整作業) として mis-encode され、 本物の締切が一度も登録されなかったこと = どの網も「存在しない fact」 を掴めなかった。 §8.8 (網が proxy を見る) の **上流版** (= 網が見る対象自体が intake で歪む)。 3+ 事例の連鎖からの一般化 (§9.8 充足)。

### <a id="firing-surface-hierarchy"></a>8.12 規律の発火面 hierarchy — doc 記載 (recall 依存) は最弱、 書く前に発火面を選ぶ

規律・手順は「内容」 と別に「**どうやって正しい瞬間に発火するか**」 という独立の設計軸を持つ。 doc に書かれた規律の発火は「その行を正しい瞬間に想起する」 という recall に依存し、 これは反復的に不発する — **機械補強 column に tool 名を書いても、 tool の存在自体が想起されなければ発火しない** (= tool は能力であって enforcer ではない)。

発火面の hierarchy (強 → 弱):

1. **hook** = tool call の決定的 interception。 条件を機械的に書けるときの最強手段 (§8 本文)。 ただし trigger が「意図」 を識別できないなら false positive が fleet を毀損する → 見送り判定は `conventions/hook-authoring.md §10`
2. **personal skill** = frontmatter description が**全 session 常時 context 内**にあり、 model が「今がその瞬間」 と判断して自律 invoke (= recall を harness が肩代わり)。 trigger を機械条件で書けない judgment 系に向く。 非発火時 noise ゼロ / worst case = 現状維持の非対称 upside / 発火は確率的。 機構詳細 = `conventions/personal-skills.md`
3. **scheduled task** = 無人定期 + Claude judgment (`conventions/scheduled-tasks.md §0`)
4. **doc 記載** = 最弱と自覚して使い、 後日 1-3 への格上げ trigger 条件を書き残す

reflex: 規律を doc に書く瞬間 + doc 記載規律の不発 RCA を書く瞬間に「これは 1-3 のどれかに乗らないか?」 を問う。 「reflex の徹底」 を再発防止策として書きそうになったら、 それは発火面の選択を skip した signal。 併せて、 新機構を増やす前に既存 enforcement channel (installer / `--check` / SessionStart surface 等) への相乗りを先に検討する (= 機構増殖の抑制、 §9.6 subtraction と同方向)。

origin: 横断 lookup script が規律表の機械補強 column に**記載済みなのに**初手 routing で 2 回不発した事例 (script 新設の起点になった null 誤結論 + 後日の遠回り routing)。 personal skill 化して description dispatch に乗せた結果、 skill 名を含まない自然な質問への初手発火を新 session trace で確認。 `conventions/hook-authoring.md §5.3` (規律で hook を代替できない) に「中間 tier として skill がある」 を加える位置付け。 2+ 事例 + 既存 §5.3 系列からの一般化 (§9.8 充足)。

### <a id="conditional-firing-visibility"></a>8.13 条件付き発火の mechanism は「自分が非活性」 を可視信号にしないと、 沈黙が解釈不能になる

§8.12 は発火面の強弱だった。 本節はその前提条件: **出力の不在は ambiguous** — 「動いて該当なし (= 正常な沈黙)」 と「そもそも動いていない (= 未配線・未登録・未 install)」 を外から区別できない。 per-machine wiring / scheduled task 登録 / opt-in install のように **活性化に手動 step を要する mechanism** は、 その step が抜けても何も言わない (= silent dead) ので、 設計者は「動いている」 と誤認し続ける。

帰結:
- 活性化が conditional / manual な mechanism には、 **「自分は今このマシンで非活性」 を能動 surface する self-check (install-check)** を持たせる。 これが無いと「沈黙 = OK」 と「沈黙 = 死んでいる」 が融合する。
- self-check は既存の毎 session 発火面 (SessionStart hook / dashboard) に相乗りさせ、 該当ホストでのみ・未活性時のみ surface する (= noise ゼロの非対称、 §8.12 reflex の「相乗り」 と接続)。
- これは **heartbeat (= 走った痕跡を残す)** と対: install-check は「配線されているか」、 heartbeat は「配線済が実際に走ったか (no-op 含む)」 を別々に可視化する。 両方無いと「設計したのに死んでいる」 と「配線したのに止まった」 を取りこぼす。

reflex: 自動化を「設計 + SKILL/doc を書いた」 で完了と思った瞬間に「これは活性化に手動 step を要するか? 要するなら、 抜けたことを誰が surface するか?」 を問う。 doc に「新 machine では再登録」 と書くだけ (= recall 依存、 §8.12 最弱面) では再演する。

origin: 朝の自動登録 scheduled task が「設計・SKILL 記述済」 なのに backend 登録 step が一度も実行されず長期 silent dead だった事例 (= 出力の不在を「該当なし」 と誤認、 真因の発覚に user の「自動で動いてないんだっけ?」 を要した)。 同型: 週次自動公開ジョブの machine setup drift (install-check 先行実装) / hook 配線 drift (installer の --check)。 3 事例からの一般化 (§9.8 充足)。

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

確定事実 (= 2026-06-13 実測、 正本 `conventions/hook-authoring.md §9.3`): **Claude desktop (Cowork) app は settings.json hook を「プロセスとして実行」 はするが、 モデルに向かう出力を honor しない** (SessionStart の additionalContext 注入は捨てられ、 PreToolUse の permissionDecision も無効。 副作用 〔file 書込〕 は走る)。 一方 **declarative な `permissions.deny` は honor される**、 ask は非 bypass mode + frontend 自身の承認系を要する (`conventions/claude-code-permissions.md`)。 ⇒ hook ベースの guard は desktop で大半 inert。

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

origin: 2026-06-13 desktop-hook-gap remediation。 odakin は desktop (Cowork) 主運用だが settings.json hook 群 (mail 誤送信 guard 含む) が desktop で hook 出力 honor されず大半 inert と判明。 再配置: mail → permission ask (`defaultMode:default` + `ask:send_email` + routine MCP を allow、 内容表示つき承認 dialog) / surfacing → SessionStart hook 副作用で `~/.claude/surface/*.txt` 書込 + CLAUDE.md 読込指示 / google-url → git-native commit warn。 qa-yaml は commit-time chronic-FP で再配置不可 → discipline、 calendar 自動強制 / memory / per-prompt §2§3 も surface 制約で discipline 受容。 §8.12 (trigger 品質軸) + §8.13 (可視性軸) に直交する frontend 生存性軸として一般化 (§9.8 充足)。

---

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

**例**: work-discipline.md の 4 過去事例 block (Memory gate / $-chat / 汎用原則 / Meta-loop) と push-workflow.md の 3 過去の失敗事例 を `odakin-prefs/incidents.md` に集約して T1 から pointer 化 (2026-04-17 実施、net -~40 lines T1 auto-load)。

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
- [`conventions/debugging-discipline.md §4`](../conventions/debugging-discipline.md) (sibling audit) の前提: scope が明示されていない list は sibling 漏れの源、 sweep が補完
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
3. **README は thin index に降格する**: 定義本体を README から抜き、 home への pointer だけ残す。 ただし **外部 (= 編集権限のない別 repo) が指している anchor / heading は保存し、 path を rename しない** (= path-targeting な外部 ref を dangle させない。 §14.2 の legacy 保存原則の cross-file 版)。
4. **全 secondary restatement を home への pointer に置換する**: 残った重複記述を全て「正本は X、 詳細は X 参照」 の pointer 文に変える。 cross-ref される表には**安定 anchor** を付け、 pointer はその anchor を指す (= positional 参照を避ける、 §14.2)。
5. **home を SoT drift-detector に登録する** (= そういう機構を保守しているなら): このとき登録 key は **裸の値 (= 金額・日付等) でなく distinctive な規則 phrase を anchor にする** (= 値は他文脈で偶然 collide する、 規則を説明する独自 token なら誤検出が少ない)。 同時に**検出対象外の blind-spot を明示**する (= list-based audit は登録 topic しか見ない、 未登録の重複は 4 軸 sweep が cover する相補関係を doc 化、 §8.8)。
6. **migration は逐語 relocation のみに留める**: 移設の最中に内容を「ついでに改善」 しない。 grep で home 前後の text が zero-loss であることを verify する (= これは移設であって内容変更ではない、 両者を 1 commit に混ぜると review で改変が埋もれる)。
7. **4 軸 sweep (= goal は error 発見) ＋同 session 内で commit/push する**: 是正は複数 file を跨ぐので、 別 session の救済に依存せず同 session 内で push 完了まで持っていく (= cross-repo drift を残さない)。

由来: ある運用ルールを複数 file に独立 author してしまい、 効率性軸の sweep が多重化を見逃した RCA を一般化 (= §13 の cell 埋め trap が SoT domain で発現した形態)。 本節は §2 / §14.3 の断片を「直す手順」 として束ねたもので、 新規原理ではなく ordered procedure の明文化。

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

## <a id="changelog"></a>変更履歴

| 日付 | 変更 | 動機 |
|------|------|------|
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
| 2026-06-06 | §8.9 新設「set 差分 detector の false positive」 + data-pipeline-automation.md §1 Pattern | SoT 統一 session の reference-data drift 手当から抽出。 §8.9 = §8.8 (proxy 盲点 = false negative) の対で、 set 差分 drift 検出の正当な乖離 (別管理 / 環境差 / 意図的例外) を filter で峻別。 data-pipeline §1 に「SoT invariant は生成経路でなく経路非依存 commit gate で enforce」 Pattern (= 生成 script の guard が手動編集をすり抜けた RCA の一般化)。 2 観察 (repo 照合 detector + reference DB dedup) からの一般化 (§9.8 充足)。 + §8.8 表に「委譲した調査 (subagent) の結論も proxy」 行追記 (= agent の『drift なし』 を自分で grep verify したら 9 件発見した実例、 negative 結論は ground truth でない = §3 単一情報源飛躍の subagent 版) |
| 2026-06-09 | §8.10 新設「fail-loud not fail-empty + 編集時 validity gate」 | 運用台帳 yaml の status に `: ` 混入で parse 不能化 → consumer が fail-empty (空扱い) で状態 label を 32 件誤除去した RCA から抽出。 §8.8 (proxy false-negative) / §8.9 (set 差分 false-positive) に続く mechanism の第 3 失敗モード = 「壊れた入力を空に潰して下流で破壊的 action」。 対 = 編集時 gate (parse 検証) + consume 時 fail-loud (破壊的 path を pre-flight abort)。 conventions/data-pipeline-automation.md §1 (生成側 gate) の consume 側双対。 観察 2 件 (yaml 破損 + §1 guard-bypass) からの一般化 (§9.8 充足)。 実装は個人層 (yaml 編集後検証 hook + label 同期 script の fail-loud pre-flight) |
| 2026-06-13 | §14.2 に「機械 consumer に positional § 番号を与えない」 追記 | SoT registry の pointer_patterns に "8.12" を登録 + 「restructure 時に同時更新」 注記で残した同日、 user 指摘で即時除去に転換した RCA。 機械 match string は renumber で silent false-negative 化 + 将来条件付き注記は recall 依存 landmine (= §8.12 適用)。 除去後検証で pattern 自体が冗長と判明 |
| 2026-06-13 | §8.12 新設「規律の発火面 hierarchy」 + conventions/personal-skills.md 新設 + hook-authoring.md §10 新設 | 横断 lookup script が規律表の機械補強 column 記載済みなのに 2 回不発 → personal skill 化で初手発火を実証した session から抽出。 §8.12 = 発火面 (hook / skill / scheduled task / doc) を内容と独立の設計軸として確立、 「reflex の徹底」 という再発防止策は発火面選択 skip の signal。 hook-authoring §10 = trigger が意図を識別できない hook は chronic FP で fleet を毀損 → skill へ切替える判定。 personal-skills.md = auto-discover skill の機構 facts (symlink 可・session 開始時 discovery、 2.1.170 実測) + description の書き方 + 多 machine 配線 (explicit allowlist registry) + 検証作法 (trigger test → discovery test の汚染回避順序、 headless `claude -p` の stdin hang / CLAUDECODE / CLI 別 auth 制約)。 kernel-up / instance-down (= incident 詳細は個人層 archive 残置) |
| 2026-06-09 | §8.11 新設「downstream 安全網は intake で正しく表現された対象しか守れない」 + §8.10 の §9.8 根拠を softening | 4 軸 self-check で §8.10 が「2 独立観察」 を over-claim (= 直接観察 1 件 + sibling) と発覚 → 「1 強 + 1 sibling、 既存 §1 の対辺補完」 に訂正。 §8.11 は別件: 「期限つき義務の見落とし」 incident 連鎖 (3+ 事例) から、 §8.8 (網が proxy を見る) の上流版 = 「網が見る対象自体が intake で mis-encode され downstream をいくら足しても掴めない / leverage は intake の encoding で、 しばしば機械化不能の判断」 を一般化。 user 方針「上の層へ移せるものは移す」 で layer 3 incident の general kernel を hoist (instance は layer 3 に残置 = kernel-up / instance-down) |
| 2026-06-13 | §2.3 新設「SoT の read 側」 | 出張案件の status を問われ source document (個人 account のメール通知) を SoT と取り違え、 null から作話で誤結論した RCA を一般化。 §2.1/§2.2/§15 は write 側 (二重に作るな) だが read 側 =「source document の null は答えでない / session 開始時 context window は案件について空 cache / null の第一仮説は『読む store を間違えた』」 が未収録だった。 同日 sibling (cite-me lookup 不発 §8.12 / labnexus burn-down の lookup-context 不実施) と合わせ 2+ 観察 (§9.8 充足)。 layer-3 機械対策 = account routing guard + matter-status SoT-read dispatch (instance 残置 = kernel-up / instance-down) |
| 2026-06-13 | §9.9 新設「新定義は origin 例で自己違反しやすい / 自己違反は under-specification の probe」 | §2.3 を新設した直後、 その origin 例で external service を SoT 扱いした自己違反を user が指摘 → §2.3 に external source 区別を追加した meta。 RCA を書く act 中でその RCA が戒める分類誤りを再演 = 「直前 discipline の self-apply」 の specific 化。 self-violation が定義の seam を probe する (= 「source document」 が内部非選択 store と external source を 1 語に潰していた) を一般化 |
| 2026-06-13 | §9.9/§9.2 cross-ref 訂正 (mis-fit 削除) | §9.9 適用例 + changelog 行が §2.3 origin 事例を「§9.2 asymmetric reflection bias の一形態」と cross-ref していたのを fresh-eyes 独立検証で mis-fit と確認し削除。§9.2 = corpus の蓄積非対称 (失敗のみ記録 → 予防一辺倒肥大化、file 内の他 §9.2 言及と一貫) で、§9.9 の self-application miss (直前に書いた定義を自分の origin 例で破る) とは別機序。citation は surface 語「reflection」(= corpus が経験を非対称に映す vs 自己反省 act 中の盲点) の意味違いに乗っていた。純粋な §9.9 self-violation =「直前 discipline の self-apply」の specific 化として残置 |
| 2026-06-17 | §16 新設「要約は load-bearing な関係を不可視に落とす — derive-not-summarize」 | 交渉案件の「肝」(= 既存削減要望に応えられないが増えはしない、で可か) が source・中間台帳・会話の各要約段で繰り返し palatable 半分へ圧縮され同一 nuance が 2 回 re-drop した RCA を一般化。inline §3 (expose/hide) の要約ドメイン双子 + §8.11 (intake encoding) の specific form。芯 = derive-not-summarize (原本逐語保持)、補助 = §15-5 逆向き completeness check。instance は個人層 work-discipline + email-office 記録に残置 (kernel-up/instance-down) |
| 2026-06-17 | §9.10 新設「完全性 audit の add-bias」 | §16 新設直後の 4軸 sweep が一般則 §16 から niche な数式記法規約 (physics-notes 添字) へ下向き cross-ref を張る missed-cross-ref finding を出し user に撤回された RCA を一般化。完全性 frame は構造的に追加へ偏り低価値/mis-weighted な接続を製造 (§9.2 sibling・§16 の audit 域発現)。restraint = instance が一般 home へ上向き / missing-cross-ref は relevance bar / audit goal を「load-bearing な欠落」 に framing。 |
