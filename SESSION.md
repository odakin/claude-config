# SESSION — claude-config

> 📌 **このファイル = 直近 (概ね直近 1 ヶ月) の作業 + Open items**。 それ以前の dated entry は [`SESSION-archive.md`](SESSION-archive.md) に分離 (grep 用)。 変更履歴の正本は `git log`、 設計判断は `DESIGN.md` (= 本 dated entries は resume 用 highlights であって網羅的 changelog ではない)。 hot/cold 分離: 2026-06-10 (accretion 対策)、 第 2 回縮退: 2026-09-01 (2026-06-01〜07-31 の 29 entry を archive へ MOVE)。

## 2026-09-01h: Karananas 誤帰属 深層 RCA の層1 hoist 5 本 (claim-target 帰属軸ほか)

KARRCA-20260901-BPU205 worker session (深層 RCA = `odakin-prefs/plans/2026-09-01-karananas-misattribution-deep-rca-results.md` が正本、 実装 = 同 §6):

- `actor-attribution.md` に **#claim-target-attribution 新節** (= 第二の帰属軸「主張は誰についてか」。 自己生成した名指しの無検証断定 / 内部略称の著名人名への衝突展開 / 框のすり替えが名前より上流、 規律 6-9 追加。 doc-meta when/summary も更新)。
- `convention-design-principles.md` に 3 §: **§2.2b #harmonization-amplification** (= 派生間不一致は調和でなく SoT 検証で解決 — 整合性軸は coherent な誤りの不動点) / **§8.28 #confirmation-question-aim** (= 確認設問は照準した軸しか検証しない — 事実主張の user 確認は真偽を第一問に) / **§8.29 #generation-error-trigger-gap** (= 操作 trigger の gate は無操作の生成 error を素通しする — 内容 trigger / stage-boundary audit に張れ)。
- `physics-verification-cycle.md` §2 に **#identifier-anchor-coverage** bullet (= anchor は式・数値だけでなく identifier 〔人名・引用 ID・記号〕 にも — un-anchored の 3 class でちょうど 1 件ずつ事故った実測)。
- `kakenhi-proposal.md` #mock-review-and-claims 🔴 rule に kernel pointer 追記。
- 機械面 (層3) = `odakin-prefs/scripts/check-source-project-parity.py` (D) named-claim audit (同 repo `be52dc3`)。

## 2026-09-01g: Codex integration — shipped

- Architecture, installer/Hook contract, platform scope, and verification are
  now canonical in [`codex/PARITY.md#codex-integration-sot`](codex/PARITY.md#codex-integration-sot).
  This entry intentionally carries no duplicate technical record.
- No layer-1 implementation task remains. Each machine's installation and Hook
  trust are layer-4 state; inspect them with `scripts/audit-codex-integration.sh`
  rather than tracking them here.

## 2026-09-01f: kakenhi-proposal に凍結後差し替え改訂 § + 協力者実名 §、latex.md に行頭禁則 scan §

- kakenhi-proposal.md 2 § 新設: [`#frozen-revision-geometry`](conventions/kakenhi-proposal.md#frozen-revision-geometry)
  (= 提出後凍結中の差し戻し改訂: Web 入力不変原則 / 挿入⇄トリムの字数収支ペアリング / PyMuPDF 頁末 y 座標比較 +
  vbox + 行頭句読点の機械検証 / snapshot 不変 + carrier TODO 集約) + [`#collaborator-naming`](conventions/kakenhi-proposal.md#collaborator-naming)
  (= 実名×役割 > 匿名分野列挙、所属・身分は書かなければ見えない、学生協力者の身分開示は下方リスクのみ)。
  既存 § へ 3 bullet 追補 (= #mock-review-and-claims: 「未解決」框付けの先行結論検査 + 同一量の別表式 chain /
  #track-record-section: 年数 self-claim の検証可能形)。
- latex.md [`#line-initial-punct-scan`](conventions/latex.md#line-initial-punct-scan) 新設 (= `\textbf{…}。` の bold 境界で
  prebreakpenalty 不発 → 行頭「。」印字。修正 = 句読点を bold 内へ、検出 = PyMuPDF 行頭 scan)。
- origin = 挑戦的調書の批判的査読 → 差し戻し待機改訂 (同日の 09-01 hoist 〔#mock-review-and-claims ほか〕 の
  sibling instance、個別実例は個人層側の当該 status.md が正本)。

## 2026-09-01e: memory-file-slimming.md に #regrowth-backstop 追補

- [`#regrowth-backstop`](conventions/memory-file-slimming.md#regrowth-backstop) 新設 = 縮退後は再肥大の機械 backstop を常設する (根本欠陥「肥大を誰も見ていなかった」 の規約化) + 閾値設計 2 点 (**warn は達成可能な健康 floor の上** = 慢性点灯は healthy=silent を壊す / **設計値は live 実走で即校正** = 出荷 gate に「実 fleet で silent」)。 一般形の上層 hoist は 2 例目で判断 (実例 1 件)。 instance (検出器実装・閾値実値) は個人層 (kernel-up / instance-down)。 run-all-checks 49/49。

## 2026-09-01d: README を実態整合 + 運用ループ主軸に組み替え、知見を §README の流儀へ hoist

- README.md / README.ja.md 増強 2 段 (`6767dec` + `84d8ff4`): ① tagline・概数 (100+ 規約 doc / 60+ script / 30+ hook)・8 カテゴリ index link で understatement 解消 + 「For English-speaking users」を「一次読者は Claude ゆえ翻訳は optional」へ書き換え ② 「Example: autocompact recovery」節を「The daily loop」節に置換 (= セッション開始 → 作業中 nudge → commit gate → push 前 4 軸 → autocompact 復帰 → 多マシン再同期、 **層 1 が実 ship する hook のみに ground** = 層 3 機能は書かない)。 GitHub repo description も同期 (= 4 軸 sweep で drift 検出 → `gh repo edit`)
- 知見 3 点を [`CONVENTIONS.md §README の流儀`](CONVENTIONS.md#readme-style) へ hoist: [#readme-reality-parity](CONVENTIONS.md#readme-reality-parity) (= understatement 監査 — 概数の数字 / 看板具体例の現在性 / repo description drift 面) + [#rule-text-language](CONVENTIONS.md#rule-text-language) (= 規約本文の一次読者は Claude、 fork 採用に翻訳は前提でない) + 推奨構成 3 を「運用系リポは 1 場面でなく運用ループ全体を walkthrough に」 へ更新。 origin = user 指摘 2 連 (「understatement になっとらんかね」 「主眼が setup になっちゃってた、 肝は日々の運用」)

## 2026-09-01d: memory-file-slimming.md に fleet 縮退 campaign の知見 6 § 追補

- [`memory-file-slimming.md`](conventions/memory-file-slimming.md) に新 § 6 本: [#fleet-parallel-slimming](conventions/memory-file-slimming.md#fleet-parallel-slimming) (1 repo = 1 delegate 並列 + repo 完結 gates + 逐語 coverage 照合) / [#verbatim-retreat](conventions/memory-file-slimming.md#verbatim-retreat) (旧全文退避で fact-loss ゼロを構造保証) / [#obligation-carrier-graduation](conventions/memory-file-slimming.md#obligation-carrier-graduation) (義務語彙 grep + carrier 確認) / [#archive-detector-exemption](conventions/memory-file-slimming.md#archive-detector-exemption) (除外 glob は file 形 + dir 形の両方) / [#parallel-session-interference](conventions/memory-file-slimming.md#parallel-session-interference) (途中状態の巻き込み commit 防御 3 点) / [#generated-block-slimming](conventions/memory-file-slimming.md#generated-block-slimming) (生成契約の trigger/digest 分離、 #auto-tree-autoload-slim の一般則側)。 origin = 2026-09-01 の 6 repo / 9 file 一斉縮退 (1.37→0.49 MB、 義務喪失ゼロ)。 instance (repo 名・数値の詳細) は個人層 (kernel-up / instance-down)。

## 2026-09-01c: AUTO-TREE の auto-load 税 縮退 — CLAUDE.md 95→35 KB (生成契約変更)

- `generate-tree.py` の生成契約を変更 (owner 承認、 設計正本 = [`DESIGN.md #auto-tree-autoload-slim`](DESIGN.md#auto-tree-autoload-slim)): ① conventions tree の説明を summary → **when** (trigger) ② hooks/scripts の per-file 列挙を新生成物 [`hooks/README.md`](hooks/README.md) + [`scripts/README.md`](scripts/README.md) へ移設 (件数 + pointer のみ CLAUDE.md に残す)。 生成物 3 → 5 箇所、 `--check` 管轄不変。 summary は `conventions/README.md` に生存 = **情報の削除ゼロ**、 README 2 本は AUTO-GENERATED view で正本ではない。 `--selftest` 新契約 ALL PASS。

## 2026-09-01b: §8.21 domain 軸 + 定期棚卸し pattern / §4.2 帰責軸 / research-email 2 §

- [`§8.21 #noise-obligation-signal-sharing`](docs/convention-design-principles.md#noise-obligation-signal-sharing) に 2 追記 (`c72336c` + `f3fa41a`): **domain 軸** (= 網の scope 宣言 — 監視系の死角は検出器の穴より先に「張っていない domain」 に開く、 金融 mail は username mask で名指し検出が原理的に無力) + **定期棚卸し** (= 語彙・sender は列挙で収束しない → suppress の誤りを定期検出する meta-detector + 月初 stateless gate + 棚卸し finding の消費規律)。 origin = 個人層 IBKR パスキー督促 16 通 3 ヶ月埋没 RCA。
- [`§4.2`](docs/convention-design-principles.md#self-rca-framing-minimization) に**帰責軸** (attribution drift) 追記 (`301bd93`) = self-serving generator の第三軸 (§4.1 成果物 / §4.2 severity / 帰責)。 mail domain 形 = 同日の [`research-email.md#apology-cause-attribution`](conventions/research-email.md#apology-cause-attribution) (`8aebd34`)。
- [`research-email.md#publisher-solicitation-triage`](conventions/research-email.md#publisher-solicitation-triage) 新設 (`f3fa41a`) = 有名出版社勧誘の 4 判定軸 (送信部門 / 分野一致 / series tier / 労働実体)。 instance (config 語彙・検出器・declared-skip 実例) は個人層 (kernel-up / instance-down)。 run-all-checks 49/49。

## 2026-09-01: convention-design-principles §8.27 新設 (user-execution handoff)

- [`§8.27 #user-execution-handoff`](docs/convention-design-principles.md#user-execution-handoff) (`67d670a`) = 最終 leg が人間本人にしかできない義務 (認証 form 提出・PW 設定・本人 login) の手渡し 4 段 kernel (readiness 同 turn / packet 1 行 / forced-disposition + 人間 channel / 「代行不可」 は probe + packet 併記) + **close-kills-the-net** (open-record 走査検出器は close で射程を失う) + **委任は可視の不作為を cover しない** (催促強度 ≠ stakes = §8.8 disposition 版)
- origin = 個人層の授業評価フィードバック deep RCA (draft + 共担者レビュー完了済みの提出義務が「代行不可」 responsibility sink → 委任下見送り close → 66 日後に第三者指摘で顕在化)。 生存 sibling 2 + 隣接 1 + close 事故 2 例で §9.8 充足。 instance (gate script / marker field / cadence 実装) は個人層 (kernel-up / instance-down)。 index 再生成済、 run-all-checks 49/49

## 2026-08-31d: research-email に「返信をどのスレッドに置くか」 § 追加

- [`research-email.md #reply-thread-follows-counterpart`](conventions/research-email.md#reply-thread-follows-counterpart) 新設 (`9549303`) = 同日追加した [#version-arrives-off-thread](conventions/research-email.md#version-arrives-off-thread) の**鏡像**。 相手が毎回新規スレッドで送ってくるなら、 こちらの返信も新規で立てる — 古いスレッドへの `In-Reply-To` 返信は相手の一覧では**スレッド最初の件名**で表示され、 相手がその送信者なら「自分の古い送信」 に見えて素通りされる
- 判定材料 = **過去の往復** (前回の返信がスレッド内か新規か)。 「1 対 1 スレッドに返すのが筋」 はこちらの整理都合であって届く保証ではない
- ⚠️ **「届いていない」 と言われたら、 まず送信側の機械事実を確認** (= 送信済ラベル / 宛先が相手の送信元と一致 / bounce の有無 / Message-Id 発番)。 揃っていれば配送は成立しており原因は**可視性**の側 — そこから先 (相手の受信箱・迷惑メール・組織のフィルタ) は自分から見えないので、 再送の形を変えるのが唯一の手
- origin = 個人層で、 3 回とも新規スレッドで送ってくる共著者に 1 対 1 の旧スレッドで返信し、 配送は成立していたのに受け取っていないと言われた実例 (新規スレッドで再送して着信確認)。 個々の相手の運用は instance = 個人層の連絡先 doc が home (kernel-up / instance-down)

## 2026-08-31c: photographed-document-transcription に引用抽出 § 追加 (= 画像から起こした引用は生成物)

- [`photographed-document-transcription.md #quotation-extraction`](conventions/photographed-document-transcription.md#quotation-extraction) 新設 = 既存 doc は**手書きの一括転記**が主題だったが、 **印刷資料を撮って引用を起こす**場合も同じく「転記でなく生成」。 実測された逸脱を軽い順に表化 (語の置換 / 文体の平準化 / 圧縮・要約 / **原文に存在しない鉤括弧つき一文の創作** / 典拠の年・頁の創作)。 いずれも「読めませんでした」 と申告されず**もっともらしい形で出力される** = §pipeline の既存警告と同構造だが、 活字ゆえ「読めているはず」 の油断が加わる
- 規律 4 点 = ① load-bearing に使う前に全引用を原本と 1 対 1 照合 ② 照合済/未照合を表で残す ③ **解像度は 1 コマ 1 頁 + 寄り** (見開き 1 枚では散文は読めても仮名 1 文字・数字 1 桁を誤る、 実測で表の「15」 を「18」 と読み違え拡大して撤回) ④ **主張の土台が引用なら引用の逸脱 = 主張の逸脱** (「創設当初から」 の根拠が表の年だったなら、 年を 1 つ創作した時点で主張が崩れる)
- [#correction-baseline](conventions/photographed-document-transcription.md#correction-baseline) (sibling) = **差分の基準点を「直前の版」 に置くと、 他人の訂正が「改変」 に見える** — その版が未検証の生成物なら基準点が汚染されている。 訂正が来たらまず自分の出力を疑う / 手元に原本 (写真・PDF) があるなら指摘を書く前に開く / それでも食い違うなら断定せず「こちらの読みではこう、 現物ではどうか」 で出す
- 配線: [`paper-audit.md #quotation-provenance`](conventions/paper-audit.md#quotation-provenance) 新設 (= 引用の出所を生成/転記で区別、 孫引きは本文側にも経路を書く、 手順は上記 doc が正本) / [`research-email.md #version-arrives-off-thread`](conventions/research-email.md#version-arrives-off-thread) 新設 (= 共同執筆の相手の最新版は 1 対 1 スレッド末尾とは限らず、 会議案内等の別スレッドに添付で来る → `from:<相手>` で期間検索・版の台帳・thread 単位の検出器は構造的射程外・返信の宛先は内容で決める)
- origin = 個人層の記事共同執筆で、 書影から AI が起こした引用が上記 5 型すべてを含んでいた実例と、 それを原本で直してきた相手を「引用の改変」 と誤読して指摘リスト最上位に置いた二次過誤 (= 原本の写真は手元にあり開けば 1 回で分かった)。 instance は個人層に残置、 kernel のみ hoist。 doc-meta の when/summary 更新 + tree 再生成、 checks 49/49

## 2026-08-31d: garoon.md に fts scope 限界 + 施設予約 URL を追記

- [`garoon.md`](conventions/garoon.md) URL 表に **施設予約** (`/g/schedule/facility_index.csp`) を追加 + 注意 2 点: ① **全文検索 (`/g/fts/search.csp`) の scope = 掲示板 + ファイル管理のみ** — 施設予約・スケジュール・ワークフローは hit しない (結果ページ自身が明記)。 fts の 0 件を施設の absence 証明にしない (= scope 違いの null、 inline §3 系) ② **敷地内でも運営主体が別法人 (同窓会・生協等) の施設は Garoon 施設リストに載らない**ことがある — 「リスト不在 = 予約不能」 でなく別系統 (当該法人の事務局) を疑う
- origin = 同日、 構内の別法人運営会場の予約経路探し (= user の fts 検索 0 件 → 施設予約リスト実査 → 不在 → 公式 web で別法人の事務局窓口と確定した実測 flow)。 instance (施設名・窓口) は個人層。 leak grep 0 hit

## 2026-08-31c: principles §8.26 新設 (= 二択 finding は判別証拠を同梱する)

- [`convention-design-principles.md §8.26 (= #disjunctive-finding-self-routing)`](docs/convention-design-principles.md#disjunctive-finding-self-routing) 新設 = 検出器の finding が選言 (「X か Y」) を提示するとき、 枝を判別する安価な検査 (1 grep / 1 field read) は**検出器自身が実行して finding 文面に焼き込む** — 判別を消費側に委ねると選言は目についた片枝に潰される (= §8.24「消費されない」 の続きの層 = 「消費されたが誤読される」)。 heuristic でも routing として焼く価値あり (verdict にせず severity 不変 + honest 限界を docstring 明記)。 reflex = 「この二択、 機械が 1 手で先に検査すべき枝を教えられないか」
- origin = 同日の運用記録 ledger 検出器の finding 誤消費 RCA (= log に決着記録があるのに消費側が「未対応」 の枝で誤報告 → user catch。 上流の閉じ忘れは当の検出器が既に backstop = ゼロは消費層のみ、 §8.25 の分解を適用)。 instance (検出器実装 + fixture) は個人層。 index 再生成 (130 sections)、 leak grep 0 hit。 sot-registry は §8.25 と同判断で非登録 (= 方法論散文、 重複 risk 低)

## 2026-08-31b: name-rendering.md 新設 (= 人名の表記を transliteration から復元しない)

- [`conventions/name-rendering.md`](conventions/name-rendering.md) 新設 (user 指示「これ層１でよさそう / ヘッダの英字から日本語表記を推測しない、 という一般則」) = **機械 field の人名は正規化された不可逆な投影**。 ローマ字化 (同じ読みに多数の native 表記) / 記号平坦化 (`Jose` ← José) / 字系転写 (Dmitry/Dmitri/Dmitrii) / 全大文字姓 (`Hanako YAMADA` が示すのは**どちらが姓か**だけで字系は言っていない) のいずれも情報を捨てる方向で、 逆変換は一意でない。 ⚠️ **逆方向 (native → ローマ字) も同様に不可逆**
- 規律 = 手元に無い表記形を推測で作らず 3 択 ([#no-name-reconstruction](conventions/name-rendering.md#no-name-reconstruction)): ① 権威 source ladder (本人の署名 > 公式サイト > 本人の出版物 > 第三者言及) ② 本人に聞く ③ **その表記を使わない** (=「分からないので書かない」 は正当な選択肢であって埋めるべき空欄ではない)。 高 stakes ([#name-printing-stakes](conventions/name-rendering.md#name-printing-stakes)) = 招待状・賞状・名札・credit 等の不可逆な印字は直前照合 (= print-preflight / paper-audit と同じ位置)。 確定後 ([#name-sot-once](conventions/name-rendering.md#name-sot-once)) = SoT 1 箇所化 + **全 record grep 掃討** + errata 残置
- 機械化不能を honest に記載 (= 推測か観測かは semantic)。 実効対策は SoT 1 箇所化と**確定時の grep 掃討**の 2 つのみ (= 誤形は判明した時点で検索可能な literal になるので、 そこだけ機械が効く)
- 配線: [`actor-attribution.md`](conventions/actor-attribution.md) 隣接 kernel に相互 link (= **同じ lossy-encoding family**、 あちらが「誰の行為か」・こちらが「名前をどう書くか」) / [`identity-in-config.md #homonym-author-id`](conventions/identity-in-config.md#homonym-author-id) に anchor 付与 (被参照側整備)。 tree 3 生成物再生成 (⚠️ generator は git-tracked のみ列挙 = 新 file は `git add` 後に `--write`)
- origin = 個人層の運用記録で、 mail header のローマ字表記から人名の native 表記を漢字で補い約 4 週間誤形が生存した incident (= instance は個人層、 kernel のみ hoist)。 evidence 節は genericize (人名・機関名なし)。 checks 49/49

## 2026-08-31: paper-audit #relocation-rebinding-sweep 新設 + principles §8.25 (= prose-claim error RCA の知見 hoist)

- [`paper-audit.md #relocation-rebinding-sweep`](conventions/paper-audit.md#relocation-rebinding-sweep) (新 anchor、 既存 3 兄弟 claim-strength / statement-placement / stale-framing の 4 人目) = 散文の文脈依存束縛 (照応 / 方向語 / 対語 / 接続詞係り先 / 次数限定 / cite 帰属) は文脈手術 (移設・圧縮・文分割/合成) で **silent に再解決される** → ① 移設は verbatim-first 2 commit 分解 ② 手術 turn は自発で named-class sweep (a)-(f) + swept/not-swept 出力契約 ③ exactness 動詞は display anchor 必須 (= prose は隠す、 式と機械は暴く)。 helper script 2 種は un-defer trigger 付き defer、 常駐散文検出器は by design 不採用。 同 file Phase 2 に cite 束縛検査 1 行。 origin = 該当 private paper repo の 2026-08-31 磨き込み日 (エラー 11 件、 cold-eyes RCA 経由、 instance は個人層 plans に残置 = kernel-up / instance-down)
- [`convention-design-principles.md §8.25 (= #detection-zero-location)`](docs/convention-design-principles.md#detection-zero-location) (新設) = 検出失敗 RCA は対策設計の前に「ゼロの位置」 を分離 (standing 検査 / 自発起動 / 命令起動) — 命令起動が正なら能力は在り、 対策は新機構でなく trigger 配線。 捕捉統計の過圧縮 (「人間 N/N・機械 0/N」) も起動者 / 実行 agent / born vs 発掘の 3 軸に分解 (= §4.2 の鏡像)。 index 再生成 (129 sections)、 checks 実施
- **同日追補: [`physics-verification-cycle.md`](conventions/physics-verification-cycle.md) 新設** (user 指示「検証サイクル導入の知見を上層に」) = 数ヶ月の paper-anchored audit fleet 運用 + 当日 RCA から、 検証サイクルの 8 kernel を hoist: ① 4 station + one-fail-blocks gate (+ standing 検査の latency 窓) ② 主張ごとの機械 anchor (docstring-as-SoT / merge ごと ALL PASS 再測 / 主張文隣の machine pointer) ③ **foil (negative control) 同梱** = 歯のない検査は vacuous pass と区別不能 ④ 検証 tier 宣言 (🔧/👁/📄 = 転記 ≠ 検証) ⑤ claim 3 状態 (verified/refuted/unverified、 未検証を分かったことにしない) ⑥ verify-to-learn (外部論文の検証読み + 他者の誤り finding は default 非公開 → 報告 → 訂正後公開) ⑦ 独立した第二の目 (self-check ≠ 独立 / 相関 agent の一致 ≠ 独立検証) ⑧ rubric 事前登録 + 判定不能を判定不能と言う + 止まる規律。 着想元 attribution (公開講演) 明記、 tree 3 生成物再生成 (⚠️ generator は git-tracked のみ列挙 = 新 file は `git add` 後に `--write`)。 **同日 2 次追補 (網羅性照合 + credit 精密化)**: 講演スライド全 20 要素の照合で gap 4 点を追補 (station 1 に「調べる」 / gate に「検査なし通過は warning 記録」 + §8.13 cross-ref / kernel 5 に「確かめ直せる材料も成果物」 + DESIGN snapshot cross-ref / kernel 8 に「成果物の存在 ≠ 正しさ」 + §8.20・§8.6 cross-ref)、 credit を per-kernel 化 (氏由来の名・form と当方先行の収斂を区別 = 最も正直な attribution 形)。 照合表 = 個人層 plan §1.5、 スライド HTML 正本 archive = 個人層 conferences repo。 **3 次追補 (逆方向 credit 監査、 `26b1317`)**: user 注意「自作物に不当に他者クレジットを入れるな」で監査 → **「verify-to-learn の手順 form = 講演由来」が過剰クレジットと判明し訂正** (手順は当方の外部論文検証読みが 16 日先行、 講演由来は名 + scratch 隔離 detail のみ。 foil 初出 2026-07-01 等の先行 evidence を git で機械確定して preamble に焼き込み)。 doc に原則 1 行明文化 = 「過剰帰属も過小帰属もしない — credit も主張であり、 検証してから書く」

## 2026-08-29c: dropbox-refs §13 + dropbox-api-access read-recipe § (= Dropbox 同期エラー RCA の知見 hoist)

- [`dropbox-refs.md #cross-platform-path-hardcode`](conventions/dropbox-refs.md#cross-platform-path-hardcode) (§13 新設) = 共有 script の OS 絶対パス hardcode は POSIX で **literal 名 file** (`C:\...` がそのまま file 名) を silent に生み Dropbox 同期エラー化 / 同期エラー表示の「パスに見える file 名」を他マシン起源と誤読する前に**ローカル 1 find** / de-hardcode は入力側だけ直して出力側 write call を見落とす half-migration trap (同日実測 RCA、 instance は共同研究リポ側 SESSION)
- [`dropbox-api-access.md #sharing-read-recipes`](conventions/dropbox-api-access.md#sharing-read-recipes) (§新設) = 最小 scope のままで通る read 系 recipe — `sharing/list_folders` は **cursor 完走まで不在断定しない** (実測: 196 folder で目的 folder が 2 ページ目) / `files/get_metadata` の sharing_info 直行 / `list_folder_members` で共同編集者の own-account 検証 (device 整理の前提確認) / `search_v2` は upload 失敗 file に痕跡ゼロ。 tree + index 再生成、 checks 49/49

## 2026-08-29b: semgrep-ci.md + yaml-hazards.md 新設 + github-security-automation §11 (= fleet security sweep の知見 hoist)

- [`conventions/semgrep-ci.md`](conventions/semgrep-ci.md) 新設 = Semgrep finding の読み書き側 (SARIF は suppress 済みも `suppressions` 付きで残る / nosemgrep は match 開始行のみ有効で Python multi-line call は引数行 anchor / local 再現は同一 pack 必須 + 毒入り fixture で検出能力を検証)。 baseline 配置側の既存 [`github-security-automation.md`](conventions/github-security-automation.md) と相互 pointer で棲み分け
- [`conventions/yaml-hazards.md`](conventions/yaml-hazards.md) 新設 = YAML 脆さ 2 軸 (parser CVE / 意味論) + safe loader + 1.1⇄1.2 差 + hazard 類型表 + 形式選択 gate + hazard rule 限定 yamllint config (⚠️ `extends: null` は crash を clean と誤読させる / directive 行は純粋行)
- [`github-security-automation.md #supply-chain-hardening`](conventions/github-security-automation.md#supply-chain-hardening) (§11 新設) = Dependabot cooldown + action SHA pin (Dependabot が pin を保守) + dependabot.yml 編集で即時 scan burst
- [`hook-authoring.md #substitution-fallback-stdout-mixing`](conventions/hook-authoring.md#substitution-fallback-stdout-mixing) に変種追記 = 混入値が crash せず通ると Free blocks 変動で dedup key が不安定化する silent 動作不全。 checks 48/48
- **追補 (同日)**: [`scripts/check-yaml-lint.py`](scripts/check-yaml-lint.py) = **tool 本体も層1 hoist** (user 指示「作ったツールも層1に」。 fleet-heartbeat / check-overleaf-drift と同型 = 実体は層1・定期発火面への配線は personal layer 側)。 root 不在 / yamllint 未 install は SKIP 契約、 requirements.txt に yamllint 追加 (= CI で selftest が実走)。 checks 49/49
- **追補 2 (同日)**: [`scripts/smoke-googleapis.mjs`](scripts/smoke-googleapis.mjs) = googleapis 依存 bump 後の read-only smoke test も genericize して層1 hoist (keys/creds/dir 全部引数化、 対象 dir 自身の node_modules を createRequire で検証)。 前提として [`generate-tree.py`](scripts/generate-tree.py) に **.mjs/.js の `//` header 説明抽出**を追加 (selftest fixture 5b 付き)。 checks 49/49

## 2026-08-29: launchd-cron engine に CRON_CONFIG_DIR pin + リモート hand-off 設計の § 新設

- [`scripts/install-launchd-cron.sh`](scripts/install-launchd-cron.sh) `7933501` = **CRON_CONFIG_DIR env** — routine を別 account の認証ストア (CLAUDE_CONFIG_DIR) で走らせる pin を plist に焼く (= 対話 CLI と無人 routine の消費 account 分離。 用途例 = 週間 usage reset window を無人時間帯に揃える)。 `--run` / cli_account / banner も pin-aware。 doc = [`scheduled-tasks.md #launchd-cron-engine`](conventions/scheduled-tasks.md#launchd-cron-engine) (前提 = pin 先の headless 生成可 auth + **MCP 登録 / settings は config dir ごと独立**)
- [`multi-session-coordination.md #remote-handoff-constraints`](conventions/multi-session-coordination.md#remote-handoff-constraints) (§11 新設) = リモート操縦 session への hand-off は「そのマシンの前でしか完了できない step」 (ブラウザ OAuth localhost-callback / chip click 起票 / 物理操作) を洗い出し、 **probe 先頭配置 + rollback 分岐焼き込み + 委譲禁止** で全分岐を「進む or 安全に戻して待つ」 に着地させる。 permission dialog はリモート UI で承認可 = 詰まるのは上記類型のみ (2026-08-29 実測)。 checks 48/48

## 2026-08-29: web-tools に claude.ai share ページ access 経路の § 新設

- [`conventions/web-tools.md #claude-share-page-access`](conventions/web-tools.md#claude-share-page-access) = share ページは in-app Browser pane が素通し / page 内 same-origin fetch で snapshot API 200 (headless・curl 全滅との対比表) + snapshot JSON gotcha + bookmarklet gotcha 3 点 (javascript: 剥がし / UTF-8 BOM / `\x23`) + 回避との線引き + pane download の着地先。 [`machine-route-first.md`](conventions/machine-route-first.md) 実例 2 号も追加。 生成物再生成、 checks 48/48。 instance 記録は層 3 (odakin-prefs plans/2026-08-24-chat-to-code-bridge.md §8)

## 2026-08-28: session 自己アカウント同定 — whoami probe hoist + multi-account 破れ 2 種

- [`scripts/claude-session-whoami.py`](scripts/claude-session-whoami.py) 新設 (層3 から同日 hoist、 generic・個人値ゼロ、 selftest 6/6) = session が「どの surface・どの account」 で走っているかの機械 probe。 **desktop app の session に注入される userEmail / `~/.claude.json` は CLI 認証層を映す** (app は `CLAUDE_CODE_OAUTH_TOKEN` しか渡さない) — desktop login ≠ CLI login のマシンでは全 desktop session が誤誘導される (2026-08-28 実測 RCA、 instance は層 3)。 正しい signal = env `CLAUDE_CODE_HOST_SESSION_ID` → app の per-account session registry path
- [`multi-account-machine-surface.md`](conventions/multi-account-machine-surface.md): §典型的な破れかた に 2 bullet (harness metadata での自己同定の誤り / pinned dir の alias⇄実 auth 乖離 = 名義取り違えの silent 破れ) + I7 stamp を host + account に拡張
- [`remote-control-server.md #oauth-grabs-browser-account`](conventions/remote-control-server.md#oauth-grabs-browser-account): 既存 ⚠️⚠️ bullet に anchor 付与 + enrich (**OAuth は picker を出さず browser cookie の account で無言で通る** / `--email` は cookie があると効かない / プライベート窓 + URL 手貼り手順) = この fact の正本に一本化 (multi-account 側の重複は pointer 化)

## 2026-08-21: machine-route-first.md + dropbox-api-access.md 新設 (f7dd134)

- [`machine-route-first.md`](conventions/machine-route-first.md) (harness-core) = 経路 ladder (dedicated MCP → API 直 → CLI → **build-the-route-first** → user 依頼 → 画面 drive)。 画面 drive の 3 重コスト (unreliable / user のマシン拘束 / 遅い) と許容例外、 「実装した経路は auto-load 面に記録するまでが 1 単位」。 origin = 同日の画面 drive incident (instance は層 3)
- [`dropbox-api-access.md`](conventions/dropbox-api-access.md) (infra) = Dropbox HTTP API 直叩き recipe — 公式 MCP / CLI 不在ゆえ API 直が機械経路。 scoped app 最小 permission + **authorize 順序罠** (token の scope は consent 時点の有効 permission) / PKCE public client (app secret 無し) / 共有リンク冪等 (create 409 `shared_link_already_exists` → list fallback) / **blast radius** (sharing.write = 全 file への公開リンク発行可 = 漏洩は exfiltration 級)。 loopback hardening は [`google-api-direct-access.md#oauth-loopback-hardening`](conventions/google-api-direct-access.md#oauth-loopback-hardening) の 4 点 set を参照
- index 3 本再生成 (⚠️ `generate-tree.py` は git-tracked のみ走査 = 新 file は `git add` 後に --write、 2026-07-31 教訓の再確認)。 run-all-checks 44/44。 全 generic (個人値・機関名なし)

## 2026-08-12: 共著改訂事例の学び 3 点を hoist

- `research-email.md #shrink-the-ask` (確認依頼の縮小) / `rebuttal-letter.md #defensive-revision` (誌替え再投稿の 3 検査) / `physics-notes.md §4` (検証 note は問題・結論・手当のみ、 summary 3→4 規約 + index 再生成)

> 📦 **2026-07-31 以前の dated entry → [`SESSION-archive.md`](SESSION-archive.md)** (grep 用)。

## Open items（forward-looking）

- [ ] **Windows ネイティブで `--selftest` 2 本が未実機検証** (= 45407fa で追加した [`scripts/check-inbound-refs.py`](scripts/check-inbound-refs.py) + [`scripts/generate-doc-index.py`](scripts/generate-doc-index.py))。 macOS で開発、 後者は in-memory string で OS 非依存だが前者は tempfile + `os.path.relpath` (backslash) と forward-slash literal の混在経路を持ち、 fallback の `os.path.exists` が mixed separator を resolve できれば通る理屈。 Windows 機会あれば実走 or 受領 PR で close。
- [ ] **`scripts/xlsx-to-pdf.sh` の Excel (osascript) branch が未実機検証** — 移設時 (2026-06-01) に soffice branch は stub-engine テストで全分岐 PASS、 Excel branch は GUI 起動を伴うため未実行のまま残った。 その後 staging dir 経由化で経路自体が変わっているので、 macOS + Excel の実機で 1 回通したら close (経緯 = [`SESSION-archive.md`](SESSION-archive.md) の 2026-06-01 entry)
- [ ] **DESIGN.md の更なる縮減候補は owner 判断待ち** — archive-first 再編 (2026-07-10b) で残した live 要素含みの節 (= 「公開リポ leak 防止」 節の sub-doc 分割等) は候補列挙どまりで未着手。 候補 list は起票元 plan の results (個人層) 側、 判断基準は [`DESIGN.md #design-reorg-archive-first`](DESIGN.md#design-reorg-archive-first) の「迷ったら残す」 (経緯 = [`SESSION-archive.md`](SESSION-archive.md) の 2026-07-10b entry)
- [ ] **dropbox-refs.md の narrative 量監視** — 類似 narrative style の convention が他に波及したら系統 pattern として review
- [ ] **LorentzArena 2+1/CLAUDE.md ゲームパラメータ表の委譲は anti-value** (再訪禁止) — 再度検討しそうになったら [`docs/convention-design-principles.md` §10.8](docs/convention-design-principles.md#deletion-delegation-trap) 削除提案の self-correction 事例を先に読む
- [ ] **RUNBOOK 系ファイルの実例運用後再検討** — トリガー: いずれかのリポで CLAUDE.md からランブック切り出しの具体ニーズが出た時。詳細は DESIGN.md「RUNBOOK 系ファイル」
- [ ] **規約 rollout 原則の一般化** — case 2 発生 (RUNBOOK 導入 or 他 content-reorganization 系) で principles §7 新設昇格を再判断。1 データポイントでの formalize は YAGNI で defer 中
- [ ] **principles.md 昇格候補 4 件の再判定** — Narrower-but-active / Generator owns commit / Event-driven vs time-driven safety net / Multi-commit workflow checkpoint。un-defer トリガーは DESIGN.md 末尾「検討事項: principles.md への昇格候補」。最 strong は Event-driven vs time-driven (既に対比表あり)、最新で 1 データポイントしかないが緊急性が高いのは Multi-commit workflow checkpoint
- [ ] **CONVENTIONS.md §2 density audit** — un-defer トリガー: 100 行 or 15 KB 到達時に density check。現状 177 行 / 19 KB で trigger 発火済、次回セッションで `grep` 頻度が低い section の T1/T2 移動を検討
- [ ] **外向け発信候補** — 詳細メモは個人層 `個人層の blog-ideas.md` 参照（public 側には具体内容を置かない方針）
