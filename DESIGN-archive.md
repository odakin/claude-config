# DESIGN archive — claude-config

> 📦 [`DESIGN.md`](DESIGN.md) から分離した完了・超越済みの dated entry (grep 専用)。 live な設計判断は `DESIGN.md`、 変更履歴の正本は `git log`。 分離日: 2026-07-10 (= 分離判断・基準は [`DESIGN.md §2026-07-10`](DESIGN.md#design-reorg-archive-first))。

---

## 2026-05-13 (3rd round): Discord API UA + Claude in Chrome permission モデル

> ⚠️ errata (2026-07-10): この `##` 見出し行は commit `ff08f9a` (2026-05-14) で誤って削除され、 本文が直前 entry 末尾に無見出しで連結されていた。 archive 移動時に `32bfddd` 時点の原見出しを復元。

同日 3 回目の知見追加。 年次タスク (sg-l 登録) 周知のため Discord Bot で生 HTTP request を書いた + Claude in Chrome MCP で sg.smartcore.jp を操作しようとしたが domain permission で詰んだ、 の 2 件から layer 1 (claude-config) で残すべき一般則を導出。

### Discord API call の UA 必須 (= `conventions/discord-bot.md` 拡張)

#### 起点

2026-05-13 17:38、 odakin が連絡責任者として研究室 Discord #一般 に sg-l 登録周知投稿を bot 名義で送信しようとして、 初回 Python urllib による POST が **Cloudflare 1010 (Access denied)** で reject。 既存 `discord-bot.md §「ネットワーク制約」` は「組織 NW egress filter」 を 1010 原因として帰責していたが、 今回は自宅 MacBook (= 同一 NW) で再現、 NW 起因ではなく **User-Agent header 欠落** が原因と判明。 `User-Agent: DiscordBot (<url>, <ver>)` を付加して再送 → 200 OK。

#### 規律導入

`conventions/discord-bot.md` に 2 節追加 / 修正:

1. 新節「**Discord API call の User-Agent header 必須**」 — Discord 仕様で必須、 default UA (`Python-urllib/3.x`) は Cloudflare で reject、 正しい format (`DiscordBot (<repo-url>, <ver>)`) + Python サンプル
2. 既存「ネットワーク制約」 を「**Cloudflare 1010 error の鑑別**」 に refactor — 1010 の原因が「(1) UA 欠落」 と「(2) 組織 NW egress filter」 の 2 系統あることを明示、 切り分け順序 (= まず UA を疑え、 NW に責を着せる前に自分の request を直せ)

#### 判断: UA 知見を layer 1 に書く理由

Discord SDK (discord.py / discord.js) ユーザーは自動で正しい UA が付くため踏まない。 落とし穴は **ad-hoc に curl / urllib で 1-shot post 書く時**。 odakin のように bot 投稿スクリプトを CLI で書く layer は他ユーザーにも普遍的 (= 「公式 SDK 入れずに sysadmin が curl で投げる」 という運用)。 1010 の鑑別順序も同様に普遍的。 個人層に閉じる根拠なし。

### Claude in Chrome MCP の 2 層 permission モデル (= `conventions/web-tools.md` 拡張)

#### 起点

同日 sg.smartcore.jp の会員検索ページを MCP で操作しようとしたが `permission_required: sg.smartcore.jp` で reject。 user は Brave で「Chrome 標準の host_permissions = すべてのサイト」 を「ずっとむかしから」 設定済。 「全許可なのに動かない、 どこにドキュメントされているのか?」 という question で deep-dive 調査。

#### 構造の判明

claude-code-guide agent + 公式 support article の参照で、 Claude in Chrome は **2 層の permission モデル** を持つことが判明:
1. **Chrome 標準の host_permissions**: user-driven 操作 (= content script、 ページ読取)
2. **Claude in Chrome 独自の AI-driven domain allow-list**: MCP 経由の programmatic 操作 (= sidepanel prompt で domain 単位に許可)

(1) を「すべてのサイト」 にしても (2) は domain ごと別途許可が必要。 これは AI-driven 自動操作を user 確認下に置く意図的な安全機構。

期待 UX は sidepanel に「Permission required」 prompt が出て user が「Always allow actions on this site」 を click。 ただし **prompt が render されない既知バグ** ([#53630](https://github.com/anthropics/claude-code/issues/53630)) があり、 silent block で詰む。 workaround は拡張再インストール等。

#### 規律導入

`conventions/web-tools.md` 末尾に「**Claude in Chrome MCP の domain permission モデル**」 節を新規追加:

- 2 層 permission の表
- 期待 UX + sidepanel prompt の 3 択
- 既知バグ #53630 / #57219 + workaround
- MCP tab group が user 手動タブと別 group である挙動 (= 既存セッションを直接操作不可)
- 公式 doc link (Anthropic support article)

#### 判断: web-tools.md に書く vs 新規ファイル

新規 `conventions/claude-in-chrome.md` を作る案も検討したが、 既存 `web-tools.md` は「Web ツール全般の caveat 集」 (= WebSearch / WebFetch / broker block 等) として機能しており、 Claude in Chrome も同じ category。 1 ファイルに集約する方が「web 操作の時はここを見れば全部わかる」 という indexing 効果。 規約設計原則 (= 1 ルール = 1 ファイル + 密接関連は bundle 可) に照らして bundle 側。 ※将来 Claude in Chrome 専用の節が web-tools.md の半分を超えるようなら split を再検討。

### Meta: 規約導入の 4 層振り分け (1 セッション内で起こった知見の layer 配置)

今日 1 セッションで「sg-l 登録 (= odakin 固有 年次タスク)」 から派生して 4 層全てに渡る知見が得られた:

| 層 | 配置先 | 内容 |
|---|---|---|
| **layer 1 (claude-config、 全 Claude Code ユーザー)** | conventions/discord-bot.md + conventions/web-tools.md | Discord UA + Claude in Chrome 2 層 permission |
| **layer 2 相当 (email-office、 odakin 個人運用)** | docs/reference/yearly-tasks/sg-l.md + DESIGN.md §yearly_recurring schema | sg-l 検知ルール + identity + yearly_recurring schema |
| **layer 3 (odakin-prefs、 個人層)** | next-steps.md (要追記: yearly_recurring 2 例目で格上げ検討) + dev-environment.md (要追記: domain permission 既知バグ) | personal layer fact |
| **layer 4 (memory、 machine-local)** | (該当なし) | このセッションの知見はすべて cross-machine、 memory には書かない |

「漏らさず書く」 = 各層に該当する知見を全部該当層に書く。 layer 1 に上げるべき知見を odakin 個人ファイルに閉じ込めないし、 個人固有値を layer 1 に漏らさない。 4 層モデル (= `docs/personal-layer.md`) の運用例として記録。

---

## 2026-05-13: 学事業務系の見落とし防止 + Google API 直接アクセス setup

### 事故 → 規律導入 → 仕組み導入 の一連

1 セッションで連続発生した「同テーマ ML 上の議論を見落とし」 → 「規約導入」 → 「仕組み化」 のサイクル。 3 つの新 conventions + 2 つの既存 conventions 拡張で documented。

#### 起点: ML forward された依頼メールの inbox 化誤判定

ML 主任が部署外から受けた「○○作成依頼」 を ML 全体に Fwd するパターンで、 元メール To に名前がない「分野責任者」 リストを根拠に**「action なし」 と reflex 判定**してしまった事故。 半月後の主任リマインダー [ml-id:NNNN+1] で初めて自分が「○○分野担当」 と過去 ML で割当られていた事実が顕在化、 締切直前で対応。

**判定の構造的問題** (= 1 通だけ見て対応要否を判断する reflex):
- 元メール To 「分野責任者 N 名」 = 部署外 が連絡を取った中継者
- ML 経由で展開される「実作業者」 = 過去 ML で割当られた各メンバー
- **両者は別 set**、 元 To だけ見て「自分は対象外」 と判断するのは構造的に誤り

**規律導入** (`conventions/ml-forward-judgment.md`): inbox 化時に 3 段ゲートを必ず通す:
1. 元メール To に自分の名前があるか?
2. 役割割当キーワード (= 分野 / 担当 / 責任者 / 作問 / 審査) が本文にあるか?
3. 過去 ML スレッドで自分が割当 source として出ているか?

判定根拠 (= ゲート 3 の引用元 ML message ID) は inbox notes に必ず残す (= future Claude が判定を追体験可能)。

#### 派生: 重要部署 / ML トピックの見落とし防止仕組み

同セッションで別の見落とし (= 半月前から重要部署が連絡してきていた校正依頼 25 件 + 同日 ML で 7 通の議論進行中) も発覚。 規律 (= 「気をつける」) では humanly 5 日経つと埋没するため、 **機械的検出仕組み** (= filter + label + dashboard surface) を導入する方向に。

**仕組み導入** (`conventions/email-surface-pattern.md`): 3 layer 構造で構造的に検出:
- Layer 1: Gmail filter (= 自動ラベル付け、 from 限定 + ML + subject keyword の 2 pattern)
- Layer 2: Retroactive labeling (= 既存メールへの遡及適用、 batch_modify で過去 1 年分一斉)
- Layer 3: Dashboard surface (= session 開始 script で UNREAD のみ最優先表示)

false positive / false negative の trade-off は「**false positive を許容して false negative を 0 に寄せる**」 方向。 ラベル名は狭めすぎない (= 「入試-ML」 より「学科業務-ML」 で会議・人事等もカバー)。

#### Bonus: 仕組みのため Google Sheets 自動読みを設計

部署外で作成された spreadsheet (= 業務関連表) を Claude が直接読みたいユースケースで、 既存 OAuth token (Gmail / Calendar / Classroom) のいずれにも Sheets scope なし。 そこから**Google API を Python から直接アクセスする setup** を一般化:

**Setup 導入** (`conventions/google-api-direct-access.md`):
- GCP project の 3 layer 構造 (= project 管理 owner / OAuth client / account token) を明示
- 各 Google API は project レベルで個別 enable 必要 (Sheets / Drive は別)、 enable 後 propagate 5-10 分
- OAuth scope は最小化原則 (= drive.metadata.readonly が可能なら drive.readonly を avoid)
- mimeType 判別 (= Sheets native vs xlsx)、 URL の `rtpof=true` が xlsx の signal
- token は git-crypt encrypt で MCP 設定リポに保管

設計トレードオフ (= 既存 OAuth client に scope 追加 vs 新規 directory + 別 scope token) では**後者を推奨**: 既存 MCP の動作影響なし、 用途別独立管理が長期メンテで筋。

#### Meta: GCP project の owner と Workspace アカウントは別 layer

GCP コンソール (= console.developers.google.com / console.cloud.google.com) の管理操作は **project owner アカウントのみ** が実行可能。 Workspace アカウント (= 大学 / 会社の発行) で OAuth flow を回しても、 個人 Gmail の GCP project に対しては API enable できない。 URL 規約として `&authuser=<project_owner_email>` を必ず付ける (= `conventions/google-url.md` 既存ルールの新 case)。

owner email は personal layer (= 個人層) の secrets-related docs に明記する義務、 multi-account 持ちの user / Claude が「どのアカウントで GCP コンソール開けばいい?」 で繰り返し混乱しないようにする。

### Why all of these to layer 1 (claude-config)

上記 4 案件は全て「**特定 user の固有事情に依存しない一般則**」 として整理可能:

- ML forward 判定 trap は学会 ML / 委員会 ML / 顧客 ML 等に generalize 可能
- email surface 仕組みは任意の重要送信者・トピックに適用可能
- Google API 直接アクセス setup は GCP project を持つ任意の user に共通
- GCP project owner と Workspace の layer 区別は GCP utility ユーザー全員に通用

PII (= 実名・固有部署名・固有 spreadsheet ID 等) は全て placeholder 化、 examples は abstract (= 「重要部署からのメール」 「学科 ML」 等の generic 表現)。 layer 2 (= 共有プロジェクト) や layer 3 (= personal) に書くと、 同型問題に当たる他 Claude Code ユーザーが再発見しないといけない。 一般則は layer 1 に置くのが配置原則 ([`docs/convention-design-principles.md §1`](docs/convention-design-principles.md#placement-by-scope))。

---

## CONVENTIONS.md §2 記録判別表: user-specific instance を除去

**判断:** §2 の「記録先の判別」表から「特定ドメインの参照データを特定の private リポの管理ツールに送る」instance 行を削除。同等のルールは個人規約リポ (odakin-prefs) に専用ファイルとして移管した。

**Why:** 元の行は表の他の行 (普遍的な情報種別 → 記録先の対応) と性質が異なり、user-specific な instance を universal table に混入させていた。匿名化するだけでは構造的問題が残る:

1. **table の同質性が崩れる:** 他の 6 行はどれも universal な対応 (例: 「設計判断 → DESIGN.md」)。問題の行だけが特定のリポ・特定のスクリプトを名指ししており、claude-config を clone する他の利用者には無意味
2. **public リポに private リポ名が露出:** 名指しされていた管理リポは private。claude-config の安全規則 (CLAUDE.md) は非公開リポ名のコミットを禁じており、その例外リストにも該当しない
3. **一般化しても情報密度が失われる:** 「ドメイン固有の参照データは専用ツール参照」のような曖昧化では実用価値ゼロ

**移管先の選定:** 候補は (a) 個人層の CLAUDE.md (private cross-machine 個人規約), (b) memory (~/.claude/...), (c) 該当 private リポの CLAUDE.md。

- (b) memory はルール定義の置き場ではない ([`docs/convention-design-principles.md` §5](docs/convention-design-principles.md#memory-positioning))
- (c) 該当 private リポの CLAUDE.md に置くと、同ドメインの他リポで作業中にこの横断ルールが見えない (リポ単位のスコープでは届かない)
- (a) odakin-prefs は cross-machine な個人規約のために設計された場所であり、最も適合する

**odakin-prefs 側の構造:** 個人層の CLAUDE.md は「1 ルール = 1 ファイル」「テーブルに載っているファイルだけが実効的」という原則を持つ。これに従い専用ファイルを新規作成し、CLAUDE.md のテーブルに追記した。

---

## ~/Claude/CLAUDE.md の symlink 化 (完了 2026-04-06)

戦略 **(b) 個別ファイル化 + symlink 置換** で移管完了。`~/Claude/CLAUDE.md` は `個人層の CLAUDE.md` への symlink。

移管マッピング:

| 旧セクション | 移管先 |
|---|---|
| 作業ディレクトリ宣言 / プロジェクト構成 / preview リンク出力 | `個人層の project-structure.md` (bundle) |
| ユーザー情報 (氏名・所属・メール) | `個人層の user-profile.md` |
| CONVENTIONS.md 参照リスト | `個人層の CLAUDE.md` 「規約参照」セクション |

bundle 判断 (「関連密接かつ合計 10 行未満のルールは bundle 可」) は [`docs/convention-design-principles.md §1`](docs/convention-design-principles.md#placement-by-scope) に LESSON として昇格。setup.sh 側の symlink 置換経路は Step 5a (L460-481)、手動操作詳細は git log 参照。

---

## DESIGN.md と EXPLORING.md の分離 (2026-04-06)

原則は [`docs/convention-design-principles.md §6`](docs/convention-design-principles.md#design-exploring-separation) に昇格済 (§7 の 3 分類 ACTIVE/DEFER/LESSON はこれを精緻化したもの)。初回適用: `LorentzArena/2+1/EXPLORING.md` 新設 (`88ed267`)、同日 orphan bullets を migrate (`cadf135`)。「他リポへの retroactive migration はしない」という適用方針も §6 に収録済。

---

## 4 層モデルの renumber: layer 2 ↔ 3 swap (2026-05-01)

### 判断

`docs/personal-layer.md` の 4 層モデル numbering を **概念導入順** から **audience 包含順** に変更:

| old | new | layer | audience |
|---|---|---|---|
| 1 | **1** | 共通規約 (claude-config) | public (不変) |
| 2 | **3** | 個人層 (= `<owner>-prefs/` + secret 配置) | owner |
| 3 | **2** | 共有プロジェクト層 | collaborator set |
| 4 | **4** | 揮発メモリ | machine-local (不変) |

### Why

旧 numbering (1=共通 / 2=個人 / 3=共有 / 4=memory) は概念の登場順 (= 共通 → 個人 → 共有 → 揮発) で書かれていたが、audience の広さ順 (`public ⊃ collaborator set ⊃ owner ⊃ machine-local`) と一致しなかった。**「番号が小さい = audience が広い = 依存される側」 という直感的対応が成立しない** 状態で、解説や実装判断のたびに「番号と直感の捩れ」 を意識する cognitive cost が発生していた (= 5/01 セッションで user 自身が気持ち悪さを表明)。

### 影響範囲

claude-config 26 箇所 + odakin-prefs 2 箇所 = 28 箇所 (= 各 owner の shared layer リポ群には 4 層 layer N 言及がないケースが多く、odakin の場合は影響範囲ゼロだった)。

詳細: claude-config commit `146994f`、odakin-prefs commit `02658be`。

### 後方互換性

過去 commit message / chat log / 過去 doc snapshot で「layer 2 = 個人層」 (旧 numbering 前提) と書かれた箇所は immutable な history として残る。新 numbering で history を読む reader (Claude を含む) のために:

- `docs/personal-layer.md` の表の下に「2026-05-01 swap 履歴」 1 行 + 本 section へのポインタを残す
- 本 section が「2026-05-01 以前の commit log で『layer 2 = 個人層』 と書かれていれば旧 numbering」 という解読 key になる

### 同時に行った関連変更

- `personal-layer.md` の表に「numbering follows audience containment」 の根拠 1 段落を追加 (= future readers が「なぜこの numbering か」 を理解できる)
- `個人層の work-discipline.md` L102 の依存方向逆記述 bug fix (= 「layer 1 → layer 2 OK」 と書かれていたのを「layer 3 → layer 1 OK」 に訂正、4 層モデル本体ルールと整合)
- `個人層の work-discipline.md` L160 直前に別軸 Layer (= 規約配置 strategic) との用語注 1 行追加 (= 同 file 内に 2 軸の Layer N が同居していたため、混乱回避用 escape hatch)

### 別軸 Layer N との関係

odakin-prefs 内には 4 層モデルとは別軸の「Layer N」表記が 14 箇所ある:

- **memory ガード system** (Layer 1=reflex / Layer 2=詳細): `DESIGN.md §「設計判断: 2 層ゲートを配置」`
- **規約配置 strategic** (Layer 1=inline / Layer 2=convention / Layer 3=protocol): `incidents.md §「2026-04-16 Gmail URL ... 4 層防御」` / `work-discipline.md §「Send-time Protocol」`

これらは renumber 対象外 (= 4 層モデル本体とは無関係)、現状維持。混乱回避は同居している唯一の場所 (= work-discipline.md) のみ用語注で対応、他は同居なし (= 文脈で意味明確) で放置。詳細: 同セッションで `personal-layer.md` / `shared-repo.md` を読む流れで判別可能。

将来「Layer N」 を multi-axis で使う confusion が悪化したら、別軸を「Tier N」 に renumber する選択肢 (= Option D) があるが、現時点では judgment call。
