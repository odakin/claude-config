# SESSION — claude-config

## Current — deadline intake and notification locus (2026-09-11)

2026-09-11 (論文の推敲 session から): 略語の検査 [`scripts/check-abbreviations.py`](scripts/check-abbreviations.py) を新設した (定義が本文で長形の初出にあること、 定義前に略語が出ないこと、 定義後に長形が戻らないこと、 「et al.」 「Ref.」 の後の文末スペース)。 規約 = [`conventions/latex.md#abbreviation-first-occurrence`](conventions/latex.md#abbreviation-first-occurrence) (投稿前 gate の list にも追加)。 最終 pass の一覧運用 = [`conventions/paper-audit.md#final-pass-open-items`](conventions/paper-audit.md#final-pass-open-items)。 分解の display・記号の置き場所・μ^{2ε} の出どころ = [`conventions/physics-notes.md#display-decomposition-and-symbol-scope`](conventions/physics-notes.md#display-decomposition-and-symbol-scope)。

The durable rules are [`#derived-external-deadline`](docs/convention-design-principles.md#derived-external-deadline) (an official relative deadline remains external/hard), [`scheduled-tasks.md#per-recipient-notification-locus`](conventions/scheduled-tasks.md#per-recipient-notification-locus) (local human notifications run once per recipient device), and the [Codex lifecycle boundary](codex/PARITY.md#managed-lifecycle-subset). Product-specific fields, schedulers, and incident evidence belong to their lower-layer repositories; resume from those records rather than this note.

既存の研究図を生成図へ置換した session から、旧図の情報 inventory、比較版への一旦 hoist、項目ごとの明示 prune、generator/output/caption snapshot、actual-render での同色重なり確認を [matplotlib figure replacement audit](conventions/matplotlib-figure-qa.md#figure-replacement-information-audit) へ昇格した。論文固有の図・parameter・採否判断・snapshot は owning project に残す。

説明的 BibTeX key を使う正しい2 entry が旧 INSPIRE audit で SKIP したため、[`inspire-bib-audit.py`](scripts/inspire-bib-audit.py) を texkey → arXiv ID → DOI の同定順に拡張した。設計判断は [stable-ID fallback](DESIGN.md#inspire-stable-id-fallback)、投稿前の発火面は [paper audit gate](conventions/paper-audit.md#gate-spec-anchor-list)。論文固有 entry と引用内容の確認は owning project に残す。

Codex の変更 task 完了 gate は、共通の意味契約を [`CONVENTIONS.md#completion-git-gate`](CONVENTIONS.md#completion-git-gate)、複数段 workflow の一般原則を [`#completion-boundary-state-gate`](docs/convention-design-principles.md#completion-boundary-state-gate)、Codex 固有の発火・検査・限界を [`codex/PARITY.md#completion-git-gate-hook`](codex/PARITY.md#completion-git-gate-hook) が所有する。発火面 tension の今回の resolution は [`DESIGN.md#completion-gate-firing-resolution`](DESIGN.md#completion-gate-firing-resolution) から辿る。現在の検収は正本と aggregate checks / layer-4 audit から再開し、この SESSION に規則や hook 詳細を複製しない。

Codex の project instruction discovery を root `AGENTS.md` の必須契約として層1化し、意味上の正本を [agent instruction entrypoint](CONVENTIONS.md#agent-instruction-entrypoints)、Codex 固有の discovery と検証境界を [project instruction discovery](codex/PARITY.md#project-instruction-discovery) に置いた。shared-project template と `audit-codex-integration.sh --repo` が同じ契約を実体化する。American spelling の再利用可能な検査 engine は [`scripts/check-american-spelling.py`](scripts/check-american-spelling.py) へ上げ、layer 2 project には [style checker mirror契約](conventions/shared-repo.md#style-checker-mirror) に従うstandalone生成mirrorだけを残した。最初の既存 shared repo `time-energy-head-on` はentrypoint・style digest・checker mirror・hook/CIをlocalとCIの両方で検証済み。他の既存 repoは次に触る通常の整備単位でauditが不足を顕在化する。

研究レビューで得た再利用可能な手順を、[部分空間・電荷・保存則](conventions/scientific-computing.md#observable-projectors-and-symmetry)、[比較表の配置](conventions/paper-audit.md#comparison-before-derivation)、[配布前検査](conventions/shared-repo.md#l2-style-digest) に整理したところ。注記の表示とフォントキャッシュの失敗時の扱いは [LaTeX 手順](conventions/latex.md#equation-safety)、スクリプトとノートの全数索引は [研究成果の配置](conventions/scientific-computing.md#research-script-homes) から再開する。模型固有の計算は各研究 project が所有する。以下の Codex 配線の検証再開点は保っている。

Codex の自己同定とprovenance整備は、技術契約・実装所有表・設計理由・一般運用規約・上層原則の参照を揃え、このMacの生成済み配線まで更新したところ。現在の仕様と全スクリプトのhomeは [Codex/Git provenance](codex/PARITY.md#git-session-provenance) と [実装・検査の所有表](codex/PARITY.md#session-provenance-implementation)、判断理由は [DESIGN](DESIGN.md#session-provenance-trailer-design)、横断運用は [multi-session coordination](conventions/multi-session-coordination.md#session-provenance-trailer) が正本。残る確認は次の新規taskでliveなprompt-time cacheをend-to-end観測することだけ。

> 📌 **このファイル = 直近 (概ね直近 1 ヶ月) の作業 + Open items**。 それ以前の dated entry は [`SESSION-archive.md`](SESSION-archive.md) に分離 (grep 用)。 変更履歴の正本は `git log`、 設計判断は `DESIGN.md` (= 本 dated entries は resume 用 highlights であって網羅的 changelog ではない)。 hot/cold 分離: 2026-06-10 (accretion 対策)、 第 2 回縮退: 2026-09-01 (2026-06-01〜07-31 の 29 entry を archive へ MOVE)。

## 2026-09-11 — Garoon workflow write の一般化

Garoon の施設予約を実申請した経験から、read 用 cookie script と workflow write の射程を分離した。汎用機構の正本は [`garoon.md#garoon-workflow-write`](conventions/garoon.md#garoon-workflow-write): 画面外の値 SoT → 承認済み同 form 再利用 → 内容/経路/確認の3段読戻し → owner 明示 OK → 送信一覧で申請番号・状態・処理者検証。操作列の汎用部品は既存 [`scripts/lib/web_driver.py`](scripts/lib/web_driver.py) を再利用し、組織固有の field 名・値・申請 ID は project/private 層に残した。

## 2026-09-11 — 事実入力・規程判断・将来確約の責任境界

学内事務への返信推敲から、相手の規程適用に必要な事実を答えたことを、当方の判断・当日の行動確約・追加資料収集へ膨らませない一般則を hoist。概念の正本は [`#input-does-not-transfer-decision-ownership`](docs/convention-design-principles.md#input-does-not-transfer-decision-ownership)、対外メールの適用は [`research-email.md#mail-fact-policy-boundary`](conventions/research-email.md#mail-fact-policy-boundary)。mail workflow からも事務・policy-owner 返信時に必ず読む参照を追加した。実名・個別案件は private/project 層に残した。

## 2026-09-11 — 記号計算 pipeline の無音 bug 3 型 (`#exact-rational-pipelines`)

自著の盲検査読で 1-loop の極を独立に再計算した session から層1 に上がった分。`nsimplify` が厳密有理数を代数的数に「同定」する / propagator の routing が展開式と逆 / 印字式の添字を下げずに比較、の 3 つが重なって「恒等式が成り立たない」という偽の物理結論に見えた。規律 = [`scientific-computing.md#exact-rational-pipelines`](conventions/scientific-computing.md#exact-rational-pipelines)、道具 (Float 拒否 + 単項式 selftest) = `ai-collaboration/scripts/one_loop_pole.py`。instance は owner の private repo 側。

## 2026-09-10 — 事務の赤入れを機械で先回りする 3 script + 「黙って消える」削除への防御

owner の科研費 session (別 repo が主戦場) から、層1 に上がった分。過去 4 年の赤入れ 16 件を
読んだら**同じ指摘を毎年受けていた**ので、年に依らない部分を機械化した。

- **`kakenhi-preflight.py`** — 様式 docx と組み上がり PDF を突き合わせ、機関事務の指摘類型を
  提出前に拾う。⚠️ **値を持たない** (「誰の機関コードが何番か」は本 script の観客にとって
  true でない) ので `--identity` で受ける。公開情報かどうかは層の判定に無関係。
  `--strict` + `--ack` = 🟠 も「直す」か「理由を書く」まで通さない (実害はどちらも 🟠 相当だった)。
- **`check-doc-truncation.py`** — 台帳 doc の切り詰めを git 高水位で検出。閾値は比例
  (固定値だと大きい doc で誤検出)、git-crypt は `cat-file --filters`、cache で 41s→1.1s。
  初手柄 = **自分が pointer 化のついでに消した表**を、手作業の復元より正確に検出した。
- **`check-markup-artifacts.py`** — 他人が紙に書き込んで返す物 (事務の赤入れ / 査読の校正 /
  契約書) は**スキャンで text 層を持たず grep に掛からない**。file 単位の台帳を正本にし、
  現物の側から台帳の穴を突く。⚠️ 1 頁目だけ見ない (後半にしか書き込みが無い物を実際に取り逃した)。
- **`conventions/kakenhi-proposal.md`** — `#drafting-entry-point` (起草の入口) を新設。
  ⚠️ 実務規律の多くが「差し戻しループ」節に埋まっていて**書くときに届いていなかった**。
  他に `#form-template-integrity` / `#keihi-meisai-expense-category` / `#identity-code-verification`、
  指摘類型を 5 → 12 に。🔴 **呼び出し口は 2 つ以上持つ** (1 経路だと年が替わって静かに失効する)。

一般則として効いたもの: **前年の指摘を読み返すのが最も安い予防策** (対処法まで書いてもらって
いたのに翌年また同じ箇所を落としていた) / **要求項目は年ごとに増える**ので「去年と同じでよい」
は成り立たない / **捨てた情報は検査できない** (誤りと確定した旧値も消さずに残す)。

## 2026-09-10/11 — commit provenance trailer (Claude + Codex)

owner の質問から始まった commit forensics。現在の agent/session/model/effort 契約、取得不能値の
扱い、Claude/Codex の配線・監査境界は
[Codex/Git provenance の正本](codex/PARITY.md#git-session-provenance)、判断理由は
[DESIGN](DESIGN.md#session-provenance-trailer-design)、運用規約は
[`multi-session-coordination`](conventions/multi-session-coordination.md#session-provenance-trailer) を読む。

現在地: Git trailer と会話冒頭自己同定の実装・同 session 検査は済んだ。残る end-to-end 確認は、
次の新規 Codex task で Hook trust 後の冒頭表示を観測すること。期待値と fallback は
[conversation-start stampの正本](codex/PARITY.md#conversation-start-stamp)を直接読む。

- **今回の最終 hoist**: resolver の入力 scope は解決結果に継承されないため、owner基準でanchor・canonicalizeした
  最終targetを再認可する一般則を [`§8.35`](docs/convention-design-principles.md#post-resolution-scope-revalidation)へ置いた。
  bulk discoveryの解決後scope escapeと、relative resultのcaller-cwd誤anchorが同じ核の両向きの実例。
- **記録の欠測はfield単位**: account/effortが取れなくてもstamp全体を消さず、既知のhost/session/model等を残し、
  未知fieldだけ`unknown`にする原則を [`§23`](docs/convention-design-principles.md#required-field-fabrication)へ統合した。
- **backtick事故の切り分け**: 実行前に`bash -n`で落ちるBash 3.2 heredoc parser bugと、commandは成功してpayloadだけ
  欠けるruntime command substitutionを [`hook-authoring`](conventions/hook-authoring.md#bash32-vs-runtime-backtick-expansion)で比較した。
- **一般知見を層1 へ hoist** (= 本件固有でなく再利用可能な形):
  [`§8.34`](docs/convention-design-principles.md#context-branch-as-leak-path) = 安全側の出力が context 判定に依存するなら
  **分岐を消せないか先に問う** (marker 付け忘れが唯一の穴になる。 消せる条件 = richer 側が safe 側から導出可能なとき) +
  [`§8.12b`](docs/convention-design-principles.md#symptom-keyed-entry-point) = **home は topic 側 / 入口は「症状の瞬間」 側**
  (契機 = 読み方を層1 の正しい topic doc に置いたのに、 その `when` が「並列 session を設計するとき」 で、
  実際に要る「commit が消えた」 瞬間と鍵が合っていなかった)。
- 後者は [§layer-1 発火面 tension](DESIGN.md#layer1-firing-surface-tension) の open に対する **基準の言語化であって解決ではない**
  (= manual pointer が scale しない問題は不変。 同 entry に追記済、 un-defer trigger は据え置き = **near-miss ゆえ 1 件目に数えない**)。
- 参照整備 = `CONVENTIONS.md` Git 規約に入口 / convention ⇄ DESIGN ⇄ §8.34 の双方向 pointer /
  層3 `sot-registry.yaml` に topic 登録 (登録直後の drift 検査で FP 0)。
- **縮退作業そのものから出た知見も層1 へ** (= 個人層 CLAUDE.md を 154 → 149 KB に縮退した副産物):
  [`memory-file-slimming.md#where-bloat-hides`](conventions/memory-file-slimming.md#where-bloat-hides) を新設 —
  ① **graduation の yield が ~0 なら、 その file は「死んだ記録」 でなく「生きた義務」 で膨れている**ので
  lever を pointer 化へ切り替える (実測: 作業 project 67 entry のうち graduate 可 0)。 この状態で
  「もっと graduate しろ」 と圧をかけると義務を運ぶ entry を移す方向にしか進めない ②
  **見出しが状態名の節 (「現在の状態」「Open items」) は日付ベースの graduation rhythm の外に落ちて
  silently accrete する** (実測: `## 現在の状態` に 10〜13 日前の dated entry 12 本、 同 file の
  dated 節は 3 日遅れで archive 済 = 1 file に 2 rhythm)。
- 同 doc の `#obligation-carrier-graduation` に refinement = **義務語彙は「語」 で引き、 記号を足して
  narrow しない。 grep が clean と言った候補も MOVE 直前に本文末尾を読む** (「残」 を `残 =` と narrow
  して本文の「残 verify」 を clean と誤判定しかけた実例。 grep は候補を絞る道具で判定器ではない)。
  実測 evidence に 2 例目 (pointer 化 1 unit ≒ 0.3 KiB、 **bullet の床 ~700-800 B が 2 例で再現**、
  床に達していない unit 数から削減見込みを見積もる式)。
- `check-yaml-lint.py` の SKIP メッセージを**実際に効く install 形** (`pip3 install --user yamllint`) に更新。
  `pip install` 案内だと PATH に該当 dir が無い環境で「入れたのに SKIP のまま」 になる
  (find_yamllint() は `~/.local/bin` と `~/Library/Python/<ver>/bin` を probe するので `--user` で足りる)。

## 2026-09-10 (別 session) — 画面 drive の harness を層1 化 + 並列 session / gate hook の 2 規約

owner の質問「e-Rad 以外のサイトでも GUI 抜きにできるか」 から。 **汎用化すべきは driver でなく「降り方」** と判定し、
科研費 driver の汎用部分をここへ上げた (instance = 個人層 / 科研費 repo に残置)。

- **[`scripts/lib/web_driver.py`](scripts/lib/web_driver.py)** (新規) — 「値の正本 → 画面に打つ操作列」 を決定的に出す
  site 非依存 harness。 frameset と素の page / SPA の両対応、 element 不在は throw せず `{missing}`、
  `audit_steps()` が site 非依存の不変条件 (JS 構文 / server 往復の wait / 生 HTML 返し / async IIFE / JSON 化) を検査。
  `--probe` = 新サイト着手の 1 コマンド (7 段: login → frame 構造 → 画面 API → field 名 → 内部 endpoint 捕捉 → 語彙)。
  ⚠️ **⑤⑥ で内部 endpoint が見えたら段 4 へ昇格して画面 driver は書かない** = 降りすぎの防止を機構に埋めた。
  selftest = 26 項目 + **node の stub DOM 上で生成 JS を実際に走らせる挙動テスト 16 項目**
  (= 「構文が通る」 と「意図どおり動く」 は別。 不在時に throw しない契約は実行しないと確かめられない)。
- 規約 = [`web-form-automation.md#step-driver-harness`](conventions/web-form-automation.md#step-driver-harness) (§9)。
  route ladder の rung 6 と `kakenhi-proposal.md#ai-write-route` から道を通した。
- 移設は**出力同値性を 281 step で証明してから**行った (完全一致 173 / 既知 5 種の書き換えで説明可 108 / 未説明 0)。
  副産物の実バグ 3 件 = ① 保存 link 不在で throw していた ② node が PATH に無く **JS 構文検査が silent SKIP していた**
  ③ 後から足した分岐が構文検査の対象 list に入っていなかった。
- 併走で 2 規約を hoist: [`#staging-window-race`](conventions/multi-session-coordination.md#staging-window-race) に
  **`git commit -- <path>`** (index を経由しない = 実験で 4 点確認) を防御 1 として追加 (従来の「唯一の現実的な defense」 を更新)、
  [`hook-authoring.md#gate-hook-unreadable-input`](conventions/hook-authoring.md#gate-hook-unreadable-input) (§0 補足 4) を新設、
  原則 [`§22`](docs/convention-design-principles.md#silent-probe-false-healthy) に同型の第 2 例を追記。

## 2026-09-09 (別 session) — 規格化係数の記法乗り換え事故 + 対数プロットの目盛 (規約 2 本)

owner の物理 repo で `2π factor` フラグを監査したところ、 フラグの射程内は正しく、 代わりに **published 論文由来の前係数が 4 倍低い**ことが判明した。 一般則を 2 本 hoist。

- **`conventions/paper-audit.md#composite-quantity-notation-migration` (新設)**: 合成量には「和」 系
  ($\sigma+\sigma'$) と「平均」 系 ($(\sigma+\sigma')/2$) の 2 流儀があり、 **記法を乗り換えるとき括弧の形
  だけ写すと前係数が定数倍ずれる**。 指数部は合うので読んでも気づかない。 実例 = 分子と分母で
  2 倍ずつ同じ向きに効いて括弧の中で 4 倍が落ち、 published 論文 + 引用先の進行中原稿 9 式に伝播。
  **決定打は自明極限の 1 行検算** (規格化された状態の自己重なり = 1 / 等幅 / 距離ゼロ) — 導出の再演より
  安く結論が二値。 併せて (2) 正しい形は自然な不等式に載る (相加相乗) (3) **同一文書の別節に独立導出の
  正しい形が同居しうる** ので記法の全出現を grep (4) 引用の係数は写す前に自分の規約で 1 回導出。
  downstream = 影響を「全体定数か力学変数依存か」 で仕分け、 定数でも **abstract が「全体確率は X で
  決まる」 型なら直撃**する。
- **`conventions/wolfram-scripting.md#logplot-ticks` (§5 新設)**: `LogLogPlot` の目盛。 (a) **user が渡す
  `Ticks`/`FrameTicks` はデータ座標、 読み出し (`ScaledTicks` / `AbsoluteOptions`) は自然対数座標** という
  非対称があり、 読み出し側に合わせて `Log[10^k]` を渡すと **その軸のラベルが黙って全消失**する
  (error も warning も無い)。 (b) 自動生成器は **6〜8 decade を境に decade 内の細目盛を落とす** (実測表)、
  密度引数は効かない。 (c) 同一位置に labeled と `""` を重ねると後勝ちで消える。 (d) 強制の可否は実寸で
  割って決める (42.6 decade を 2.7 in に載せると細目盛は 178 µm = 黒い櫛)。 (e) `AbsoluteOptions` は
  front end 必須なので、 検証は §4 と同じく **Export した PDF から text 抽出**。
  doc-meta の `when` に「対数プロットの目盛」 を追記 (= 生成索引からの routing)。

## 現在地 — 偽の締切 / 自己報告値 / 同一 file staging の 3 原則（2026-09-09）

今回の整備は終了点。 instance (marker field の実装・個別 item への付与) は private layer に残置 (kernel-up / instance-down)。

- **`docs/convention-design-principles.md#required-field-fabrication` (§23 新設)**: 監視機構が拾う条件に必須 field を置くと、 値が無い item に対して**捏造される**。 実例 = 期限 surface が deadline 持ちしか拾わない設計 + 「本人操作が要る item には必ず添える (自己設定で可)」 という規約 → 該当 6 件中 3 件が捏造で、 **本物の失効型期限 1 件がその中に並んで最上位 group に居た**。 kernel = 出自を宣言する第三の状態 + 設計要件 4 (無記載 = 従来の意味で移行不要 / loud 側 default / 「静かにする」 であって「消す」 ではない / 判別が自然言語なら機械化不能と declared) + 見分ける問い「値が無い item に書き手は何を書くか」。 §8.28 壁紙化の**上流** (= cadence でなく severity の出自)。 index.yaml 再生成済。
- **`conventions/debugging-discipline.md` §15.5 [#tool-self-report-is-not-measurement](conventions/debugging-discipline.md#tool-self-report-is-not-measurement) + §15.6 [#stale-base-measurement](conventions/debugging-discipline.md#stale-base-measurement)**: bundler が build ごとに印字する `gzip:` を配布サイズとして読み、 依存の major 更新を「圧縮後が 9 kB 太る」 と評価して見送った → `gzip -9` 実測では**逆に 1.6 kB 減っていた**。 姉妹罠 = bot の更新 branch は作成時点の古い base 由来なので、 そこで build すると現在存在しない構成を測る。
- **`conventions/multi-session-coordination.md#staging-window-race`**: 既存の「`git add -A` を使わず明示列挙」 は**相手が別 file に居るとき**しか効かない — 同一 file なら staging は file 単位で hunk の作者を区別せず、 検証に空けた数分で相手の commit に自分の hunk が吸われる。 防御 = **編集と commit の間を空けない** (検証は commit 後)。 public repo では**相手の未検査変更が leak gate を素通りする**のが最も危険。 同 session 内で双方向に 1 回ずつ発生。
- registry 登録 = 前 2 者 (= layer-3 の drift 検出に配線)。

## 2026-09-09 (別 session) — 貼り付けコマンドの `#` 事故を層1 へ (hook 1 + 規律 5 節)

owner の対話 session で「rebase 手順を貼らせたら壊れた」 の RCA を回し、 成果を層1 に集約した。

- **`conventions/shell-env.md#no-inline-comments-in-pasted-commands`**: 既存節に実測を追加。
  対話 zsh は `interactive_comments` 既定 OFF で `#` が **argv に化ける** (pty で再現、
  `git rebase --continue  # 注釈` → `[rebase,--continue,#,todo,…]` で usage error)。
  **決定的**であって確率的でない / **行頭 `#` 単独行も壊れる** (= 独立行へ逃がす案は不成立) /
  **第一選択は「注釈を消す」 でなく script 経路** (script 内の `#` は効くので説明を捨てずに済む)。
  ⚠️ doc-meta の `when:` が「PATH 消失…」 だけで、 `when` のみ表示する生成索引から
  「コマンドを渡す瞬間」 に到達できなかった = **routing 欠陥**。 trigger を追記して根治。
- **`hooks/pasted-command-comment-guard.sh` (新設、 層3 から移設)**: Stop hook。
  貼り付け指示語 ∧ fence 内の実行系コマンド行の `#` で block。 `setup.sh` STOP_ENTRIES に登録。
  日本語 cue は 49 日 transcript で校正 (真陽性 3 / FP 0)、 英語 cue は推定 = FP 監視対象。 selftest 12。
- **`setup.sh` Step 6d (新設)**: `~/.zshrc` に `setopt interactive_comments` を追記
  (odakin 自動 / 他ユーザーは tip 表示のみ、 冪等)。 ⚠️ 受け手側の保険であって出し手の規律の
  代替ではない (提示先の環境は選べない) を doc に明記。
- **`conventions/paste-destined-plain-text.md`**: terminal 側を「最上位 mode = silent 成功」 と
  だけ書いていたため **loud な失敗の診断をミスリード**していた。 loud (`#`) / silent (`~`) の
  2 mode 併記に修正。
- **`conventions/concise-output.md#user-facing-steps` (新設)**: user 自身にやってもらう操作は
  「冒頭に・番号付きで・それだけ」 6 則。 ⚠️「散文で直る保証は無い」 も明記 (= 本節を書いた
  直後に同じ規律を破っている)。
- **`conventions/secret-handoff.md` 4 節 (新設)**: `#no-shell-rc-copies` (rc への複製は
  **os.environ 優先で正本を上書きし rotate が silent に効かなくなる**) / `#backup-round-trip` /
  `#passphrase-loss-is-recoverable` / `#rotation-labor-split` (人間は再発行のみ・残りは script、
  AI が値を手で扱うと context/transcript に載る + 主体照合必須)。

⚠️ desktop は hook の model 向け出力を honor しないので、 本件の事故 (= desktop) は hook では
止まらない。 desktop の floor は上記 doc と script 経路の既定化。
深層 RCA = `odakin-prefs/plans/2026-09-09-paste-comment-contamination-rca-results.md`。


## 現在地 — Discord ⇄ board bridge engine + 組織図 builder（2026-09-08）

今回の整備は終了点。 再開時は下記正本を読む (owner の instance / 経緯は private layer)。

- 新規 script 2 本 (config 駆動、 stdlib + PyYAML、 `--selftest` 内蔵): `scripts/discord-board-bridge.py` (chat message → board request、 課長 ack / 係長 進捗 / ✅ → accept、 `--dry` / `--backfill-minutes` / `--setup-webhooks`) + `scripts/discord-org-build.py` (組織図 YAML → category / channel / webhook を冪等生成)。 `scripts/README.md` は generate-tree で再生成。
- 一般則: `multi-session-coordination.md#chat-board-bridge` = 6 原則 + 実装 pointer + 初回 live で踏んだ 2 点 (初回 tick 前の投稿は履歴扱い / accept にも references ≥ 1)。 原則 6 を「bot (token) は 1、 役割は組織図 + persona」 に改訂。
- Discord 機構 fact: `discord-bot.md#webhook-personas` (username 切替 / Manage Webhooks は標準セット外 / reply 不可・reaction 可 / topic 禁止語 filter) + `#guild-creation-user-only` (`POST /guilds` は bot 不可 20001、 器は人間が作る = ladder で user 依頼 > 画面 drive の実例)。
- 起点は private layer の記事議論 (川辺健太郎氏の「Discord 上の会社」、 朝日 2026-09-08)。 instance (組織図・人名・ids・config) は公開しない。

## 現在地 — GAROON script 経路 + 配線 gap 規律（2026-09-07）

今回の整備は終了点。 再開時は下記正本を読む (個別案件の状態はここへ転記しない)。

- 新規 script 2 本: `scripts/chromium-cookies.py` (Chromium cookie 復号) + `scripts/garoon-client.py` (Garoon 全文検索 API / 掲示板 REST / 添付 download、 `--org` 必須)。 機構 fact = `conventions/garoon.md#garoon-script-route`。
- 新規則: `machine-route-first.md#wiring-gap-is-a-task` (経路は在るが配線が通らない時も同 turn で診断→修復/user 1 画面→carrier+機械別配線表) + `#session-cookie-reuse` (SSO-only で credential が発行できない web app は browser session cookie を script に持ち出す、 recipe 6 点)。
- 追補: `web-tools.md` chrome permission How to apply (Permission denied が未 login を隠す / 複数接続は broadcast で user に命名させる / browser_batch + read_network_requests の classifier block / navigate 直後 get_page_text の描画前読み) / `ask-user-question.md` (harness の MUST 注入 vs user 選好) / `jps-talk-submission.md#program-slot-lookup` (講演番号 → 時刻は `<li>` を数える、 fetch 要約は 1 件落とす)。
- 同日後半: `scripts/jps-program-talks.py` 新設 (JPS Web program の sessions / talks / grep / slot、 開始時刻は `<li>` 積算で計算、 構造 fact は docstring) + `jps-talk-submission.md#program-triage-by-interest-profile` (arXiv digest の関心プロファイルで学会 program を triage する 5 手順、 calendar 3 層)。
- leak sweep: 既存 doc の研究室 bot 名 ×3 + private repo 名 ×1 を匿名化 (`6fc069b`)、 新 script docstring の subdomain 例も `<org>` 化 (`65c402a`)。 history は user 判断で受容。

## 現在地 — Codexのセッション引継ぎ整備

今回の引継ぎ整備は終了点。次回この仕組みを変更する場合は
[引継ぎの技術正本](codex/PARITY.md#session-handoff-contract)を読み、参照配線検査と
hook fixtureを実行する。個別案件の状態はここへ転記しない。

## 現在地 — メール運用の整備（2026-09-06）

今回のメール運用整備は終了点。再開時は新しい依頼の対象に応じて下記正本を読む。

- 起草の意味・会議手続き: [research-email](conventions/research-email.md#commitment-vs-logistics) / [Indico runbook](conventions/indico-abstract-submission.md#registration-payment-separation)。
- 送信機構の確認: [sending contract](conventions/gmail-sending.md#reviewed-reply-bundle) / [Codexの承認境界](codex/PARITY.md#mail-approval-boundary)。
- SESSION整備の判断基準: [更新手順](CONVENTIONS.md#auto-update-protocol)。

## 2026-09-06: Codex context の一次資料と参照を更新

- 製品案内と検証境界を [PARITY の正本](codex/PARITY.md#long-context-opt-in) に集約し、圧縮対策側の数値・二次情報の重複を参照へ置換。実行時イベントと診断ログで設定値・実効窓・圧縮しきい値を区別する確認経路も同正本へ追記。

## 2026-09-06: Session 宛て board の一般則と参照を整理

- 主体・提出と受領・明示引継ぎ・受領経路の正本は [multi-session coordination §13](conventions/multi-session-coordination.md#git-immutable-event-board)。移設せず、検証サイクル側から参照する。

## 2026-09-06: 地図UIの知見を既存規約へ統合

- [web-map-projections.md](conventions/web-map-projections.md): 国名の候補／衝突判定、自転と中央経線の符号、操作欄の状態表現を更新。適用先の DESIGN は節参照へ整理。

## 2026-09-06b: 検証サイクルの規約 3 本 + script 4 本を新 layer-1 repo `ai-collaboration` へ分離 (stub + forwarder 残置)

- user 決定「ai-collaboration で public でいこう」 (rename / rebrand は却下)。 移設 = `conventions/{physics-verification-cycle,verification-cycle-ops,cold-eyes-isolation}.md` + `scripts/{verification-campaign-report,ledger-commit-cadence-gate,make-review-sandbox,gpt_measurements}.py`、 git 履歴は `git format-patch --root` → `git am` で持ち込み (30 commit)。 本 repo は **Claude Code harness** (setup / hooks / domain 規約) に戻り、 あちらは **AI 協働 platform** (vendor 中立)。
- 本 repo 側: 3 doc は **旧 anchor を全部保つ stub** (= 33 anchor の対応表、 `#slug` link は壊れない) / 4 script は **forwarder** (同 argv で正本を exec、 `gpt_measurements` は import 時に symbol を re-export)。 generate-tree 再生成。 外部からの literal path (`claude-config/scripts/<name>`、 `#anchor`) は当面そのまま動く = 呼び元は急いで直さなくてよい (owner 側は同日切替済)。
- Phase 2 (`multi-session-coordination.md` + `codex/` の移設) は trigger 付き = `ai-collaboration/DESIGN.md`。 判断の記録 = 下 DESIGN §2026-09-06。

## 2026-09-06: verification-cycle-ops.md 新設 (回し続ける構造) + campaign-report --index/--surface + round-2 retro tooling

- [`conventions/verification-cycle-ops.md`](conventions/verification-cycle-ops.md) 新設 = 「何を検査するか」 (physics-verification-cycle) の隣の「どう回し続けるか」: 6 原則 / 導出 state 機械 (spec → running → done → received → retro'd) / 台帳 3 種 / retro / 無人層 (日高 #17 の部分採用、 人間 gate を越えない契約) / fresh session の手順 / 壊れ方と検出 / 限界。
- scripts: `verification-campaign-report.py` に `--index [--write]` (INDEX.md = efficacy dataset) + `--surface` (finding のみ) + `--run` (foil 契約) / `ledger-commit-cadence-gate.py --worker-scope-env` / `make-review-sandbox.py` 新規。 physics-verification-cycle §15 I-K + G′、 §16 routing に ops pointer。 instance (台帳・retro・QUEUE・hook・launchd tick) は private layer。

## 2026-09-05d: verify-to-learn campaign の運用 kernel + 道具 2 本を hoist (初回 campaign + retro から)

- [`physics-verification-cycle.md`](conventions/physics-verification-cycle.md): **§14 `#campaign-tooling`** 新設 (ledger schema / 👁 繰り越し台帳 / 新結果の 2 段階第二の目 / deny list 隔離 + 並走 dir 分離 / cadence の機械 gate / git 由来 stats / 受領手順、 全部 n=1 と明記)、 §8 に `#efficacy-proxy-receiver-side` (受領側記入 + 所要は git から、 同日先行)、 doc-meta 更新。 [`cold-eyes-isolation.md`](conventions/cold-eyes-isolation.md) §4.5 `#external-paper-variant` / [`output-cap-death-loop.md`](conventions/output-cap-death-loop.md) 予防 3 に機械 gate pointer + 同日先行の `#context-compaction-loss` (Codex 等の小さい context 窓)。
- scripts: **`ledger-commit-cadence-gate.py`** (pre-commit、 1 commit の追加 entry ≤ N、 escape env → hygiene log) + **`verification-campaign-report.py`** (git 由来 stats を results.md の AUTO block に / carryover.yaml 生成)、 両方 `--selftest`。 private repo 側は shim。 数学 library `gpt_measurements.py` は同日別 session が hoist 済。
- README tree 再生成。 instance と finding (外部論文 2 本の誤り疑い 3 件 = 非公開) は private repo に残置。

## 2026-09-05c: ML broadcast 義務の見落とし RCA と GUI 記入事故から 6 anchor を hoist

- [`docs/convention-design-principles.md`](docs/convention-design-principles.md): **§8.30 `#expected-inbound-tripwire`** (予告された inbound 依頼に時計 = 待ち entry + 予測日 + slack) / **§8.31 `#principle-birth-stock-audit`** (登録時 gate は flow にしか効かない → 原則 hoist の turn で既存 config を 1 周) / **§8.32 `#rca-as-labeling`** (「〜型」 と分類した瞬間が機械層を足す最安の瞬間、 label 単独禁止) / §8.17 に「同僚の返信数」「役職自己紹介 = 弱い passthrough」 の 2 signal / §8.21 に stock audit + root-only + 構造 signal の追記。 origin = 学科/専攻 ML 依頼 23 日見落とし (5 網全部が構造的に不通過、 個人層 RCA `odakin-prefs/plans/2026-09-05-ml-broadcast-obligation-miss-rca.md`)。 index 再生成済。
- [`machine-route-first.md #shared-document-write`](conventions/machine-route-first.md#shared-document-write) 新設 = 他人 owner の共有 document への書込は画面 drive しない (blast radius が自分の外、 focus 取り違え / 先頭 keystroke 欠落 / stale 画面の 3 機構を実測)。 ladder 6 の例外を「対象を指した画面指示のみ」 に締め、 「見て / やって / 任せる」 は GUI 許可でないと明記。 実例 ledger に 2026-09-05 xlsx 事故 (= 同日 2 例目)。
- [`google-api-direct-access.md #drive-xlsx-inplace-update`](conventions/google-api-direct-access.md#drive-xlsx-inplace-update) 新設 = 他人 owner の xlsx を `files.update` で同 ID 更新する recipe (full drive を別 token / **revisions.get_media が truth、 files.get_media は数分 stale を実測** / openpyxl round-trip の損失 / 再 download literal verify)。 個人層 instance = `odakin-prefs/scripts/drive-xlsx-set-cells.py`。
- README tree 再生成 (summary 更新 2 本)。

## 2026-09-05b: 公開 API の無い web app の機械経路 / desktop 自己同定 / 拡張 stale 接続 / data repo pattern を hoist

- [`machine-route-first.md #internal-endpoint-replay`](conventions/machine-route-first.md#internal-endpoint-replay) 新設 = ladder 4 の一形態 (XHR hook で UI 操作 1 回を捕捉 → 同 endpoint を page context から叩く → rules / dry-run / apply → reload で確認、 6 点 + 線引き) + 実例 (家計簿 SaaS のカテゴリ一括修正、 業種語 regex の巻き込み)。 [`web-tools.md #javascript-tool-gotchas`](conventions/web-tools.md#javascript-tool-gotchas) (async IIFE → `{}` / 出力 filter / 内部 endpoint) + permission 節に「再インストール前に `list_connected_browsers`」。
- `scripts/claude-session-whoami.py`: Remote Control 配下を `rc/<label>` と同定 (プロセス祖先 cmdline probe、 fail-open)。 ⚠️ macOS `ps` は `command` 列を最後の `-o` に置かないと 16 文字で切れる (fix 済、 fake process で direct / parent 両 case 実測)。 **実 RC session での表示は未確認** = 次にスマホから入った session の冒頭 stamp で確認。
- [`multi-account-machine-surface.md`](conventions/multi-account-machine-surface.md): I7 を `hostname -s` → whoami `--stamp` (account 軸必須、 2 回の誤同定) に更新 / §典型的な破れかた に「拡張署名 ≠ session でも MCP は繋がる (denied + prompt 不可視で現れる) + 再ログイン後の stale 接続」 を追加。 [`hook-authoring.md §9.3`](conventions/hook-authoring.md#frontend-dependent-cowork) に 2.1.260 再測定 (不変)。
- [`data-pipeline-automation.md #cross-ledger-join`](conventions/data-pipeline-automation.md#cross-ledger-join) (金額 SoT / domain fact SoT の分離 + read-only join 4 面) / [`docs/personal-layer.md #owner-only-data-repo`](docs/personal-layer.md#owner-only-data-repo) (data repo は prefs から分離、 default-encrypt + 平文 allow-list、 tools は PII を実行時に読む)。 instance = 個人層の医療記録 repo (同日新設)。

## 2026-09-05: 地図図法ビューアの知見を層1 に hoist — `conventions/web-map-projections.md` 新設

- 起点 = `equal-earth-viewer` (odakin の公開教材、同日 1 日で初版→国境・国名・拡大・南を上まで)。 project 固有の判断史は同 repo DESIGN.md、 再利用できる一般則だけを本 doc に。
- 中身 = §1 図法の性質 (正積・極・断裂) は自称でなく d3 で実測して守る (同日に手書き metadata 2 件が誤り) / §2 経度回転で外郭不変な図法だけ fit をキャッシュ、断裂図法は回せない / §3 拡大 = viewBox 切り出し + 動作中 110m・静止時 50m の 2 段 / §4 Natural Earth の国データ (key は name、 name_ja、 MAPCOLOR9 をデータのまま、 国名描き込みの fit 規則) / §5 UI 判断 (user 指摘で確定) / §6 web 一般の罠 (hidden vs display、 Number(null)、 色 literal の同形異字、 headless 高さ 0)。
- 個人層側 = odakin-prefs `work-discipline.md` §A/§B に 2 bullet (実測で守る / 「本当に?」 質問 = audit trigger + 個別手直しの連鎖) + archive に当日の訂正一覧。

## 2026-09-02c: Codex automation routing — 正本・発火 skill・上層原則へ結晶

- 製品固有の durable contract は [`codex/PARITY.md#native-automation-routing`](codex/PARITY.md#native-automation-routing)、常時発火面は [`codex-automation-routing`](codex/skills/codex-automation-routing/SKILL.md)。本 entry は snapshot pointer のみ。
- 横断知見は [`#automation-trigger-routing`](docs/convention-design-principles.md#automation-trigger-routing)（自動化 intent を wake event / judgment / context continuity / locus / authority の 5 軸で route）と [`#activation-evidence-ladder`](docs/convention-design-principles.md#activation-evidence-ladder)（proposed / configured / registered-active / observed-run を混同しない）へ hoist。
- context 耐久力の一般診断は [`#context-capacity-evidence-layers`](docs/convention-design-principles.md#context-capacity-evidence-layers) と [`codex/PARITY.md#context-capacity-diagnosis`](codex/PARITY.md#context-capacity-diagnosis) へ hoist。実測値・外部問い合わせの object / response state は owner-private case ledger が正本で、本 public snapshot には複製しない。

## 2026-09-02b: supersede 掃討 campaign — 4 監査 / 約 50 finding / §20.5 系 3 節を hoist

user 指示「他にも同じような supersede 済みルール残ってないか全部見て」 → 4 範囲 (層1 conventions 99 file + docs 8 / 事務書類の手順書群 / 研究費 / 層3) を全文監査し、 確定 finding を修正。 **本 session だけで約 50 件**。

- **§20.5.2 暫定値の凍結** (新設): 上限値が実額欄に居座る / 暫定額ベースの派生値が更新されない。 実害 = 補助金の費目間流用枠が応募額ベースのまま (= 過大枠で流用すると事前承認漏れ) + 受給額欄に公募上限 (= 過大申告)。 ⚠️ どちらも doc 自身が「確定後に再計算」 と書いていたのに実行されなかった。
- **§20.5.3 列挙の凍結** (新設): summary の「8 kernel」「3 つのルール」「回避 2 択」「現状 空」 が本文の伸びに追随しない。 **1 日で 5 件**。 害は数の誤りでなく **読者が列挙を閉じたものとして扱う**こと (= routing index の「8 kernel」 を見た session が §10-12 を規約外と判断する)。 → 数を書かないか生成する。
- **§20.5 に掃討面を追記**: 散文 doc だけでなく **code-as-SoT の docstring / skeleton の default 値 / 機械照合 spec** も規則面 (= 3 件実発生。 driver は正しいのに docstring が旧手順、 skeleton が旧定数を hard-code)。
- **[`multi-session-coordination.md#fanout-audit-resilience`](conventions/multi-session-coordination.md#fanout-audit-resilience)** (新設): fan-out 監査の親が停止しても子が起票元に直接返す設計なら中身は失われない (= 実際に起きて実証)。

**layer-1 側の修正** = docx-to-pdf の default 反転未追随 / `make new picture` 不成立の旧結論 / paste 用 doc の model pin / 存在しない tool 名 / Tahoe で silent fail する壁紙 recipe 2 件 / overleaf の leak 楽観 / memory 行 (= §20.5 を書いた doc 自身) / 規律節の二重生存 / 列挙 3 件。 詳細は個人層の監査レポート 4 本。

## 2026-09-02: 規則の前提失効 (§20) + variant drift (§21) + 出力直結 field (data-pipeline §14)

layer-3 の事務運用 session (= 承認者・様式定数・依頼 template・押印) から 4 件を kernel-up。 instance は個人層・共有 project に残置。

- **§20 規則は前提より長生きする** — 上流属性 (費用の出所 / 制度 / 責任者 / 運用の版) が切り替わっても規則と定数だけが無条件の手順の顔で生き残る機序 + 5 pattern。 「これ何で要るんだっけ?」 を premise-expiry の高信号 detector として明記。
- **§20.5 supersede は「新しい正本を書く」 では完了しない** (+ §20.5.1 検出器の非対称) — 転換は上流 1 箇所に landing し、 旧規則を書いた下流手順書は知らないまま生き残って**次に読んだ者が正しく適用する**。 SoT drift 検出は「現行規則の重複」 を見るので旧規則の生存は原理的に映らない → 旧 literal も登録して「規則が書かれる面」 だけ scan する設計を提示 (= layer-3 で実装、 登録当日に真陽性 1 件)。
- **§21 rule variant の silent stale 化** — 言語別・媒体別 variant は**正当な重複**ゆえ §2 の削除方針では解けない。 3 択 (持たない / 生成する / parity gate)。
- **[`conventions/data-pipeline-automation.md#display-bound-field-purity`](conventions/data-pipeline-automation.md#display-bound-field-purity)** — 人物 DB の 1 field が生成物に印字される構造で運用注記が対外表示に漏れた事例の一般化。 新 consumer を足す瞬間が検査点、 直すのは生成物側でなく SoT field 側。

⚠️ 4 件とも **同 session 内で自分が踏んだ**失敗の一般化 (= §20 を書いた当日に §20 の failure mode を踏み、 §20.5 の必要性が判明した)。

## 2026-09-01j: 検証方法論 4 § hoist (private paper の framing/検算 campaign から)

- [`conventions/paper-audit.md`](conventions/paper-audit.md) に `#assumption-dependent-claim-framing` (3 層勾配 / 無仮定 floor / 不確実性→要求仕様) + `#moving-observational-baseline` (係争中の観測許容域: 複数 region + 不変量抽出 + baseline は著者判断)。
- [`conventions/physics-verification-cycle.md`](conventions/physics-verification-cycle.md) に `#cross-vendor-blind-verification` (別 vendor AI への盲検 spec、 公式自選、 一様 offset = 規約差 signature) + `#approximation-tier-closure` (N 実装一致は同一理想化階層内の一致 — 階層を計算で外す。 §番号 10-11 挿入で routing は §12 へ)。
- [`conventions/scientific-computing.md`](conventions/scientific-computing.md) に `#evolve-constraints-algebraically` (拘束量を独立積分すると drift→符号反転→反減衰爆発、 代数評価で単調性を構造保証 + validation 3 点セット)。

## 2026-09-01i: Codex integration 検収 + durable 化 (別 session による受け入れ検査)

- 検収 verdict = 合格 (机上 + 実機 audit + 両 repo 全 suite green + pull 起点 refresh の live 観測)。 技術詳細は
  [`codex/PARITY.md#codex-integration-sot`](codex/PARITY.md#codex-integration-sot) が正本 (本 entry は snapshot のみ)。
- 検収で landed した hardening = `68cfe86` (誤検知地雷 3 件: SESSION scan の文脈 scope 化 / state 自動 prune /
  effort 値を製品受理集合に一致) + `ca5d1bc` (scope 粒度を entry 単位へ) + `c8b1b47` (public-layer pull refresh の
  配信 gap audit + writer path 間 marker 統一)。 4 層定義の明確化 (観客 vs 配布機構) = `f1bbb93`。
- 一般知見の hoist 先 = [`conventions/hook-authoring.md`](conventions/hook-authoring.md) §2「配信 drift の根本因」実装例
  (template≠配信 / marker 統一 / audit test の hermetic 化) + [`docs/convention-design-principles.md #set-diff-false-positive`](docs/convention-design-principles.md#set-diff-false-positive)
  共有語彙 token 変種。
- 実機 (⚠️ 2026-09-01 訂正: 検収 session の host は **MacBook 側** と `hostname -s` 実測で判明 〔具体 hostname は owner 個人層に記録〕 —
  初報の「iMac 側で作業」 は host 未検証の思い込みで **逆**だった。 まさに同日 landing の worker-host
  provenance 規律が塞ぐ同族 error の実例): **MacBook = setup.sh 再実行 + composite refresh 済で audit
  全 green (checked 2026-09-01)。 iMac = 未検証** (= bootstrap 状態不明、 そちらで audit を回して判定。
  手順は owner 個人層の codex/README.md)。

## 2026-09-01h: Karananas 誤帰属 深層 RCA の層1 hoist 5 本 (claim-target 帰属軸ほか)

KARRCA-20260901-BPU205 worker session (深層 RCA = `odakin-prefs/plans/2026-09-01-karananas-misattribution-deep-rca-results.md` が正本、 実装 = 同 §6):

- `actor-attribution.md` に **#claim-target-attribution 新節** (= 第二の帰属軸「主張は誰についてか」。 自己生成した名指しの無検証断定 / 内部略称の著名人名への衝突展開 / 框のすり替えが名前より上流、 規律 6-9 追加。 doc-meta when/summary も更新)。
- `convention-design-principles.md` に 3 §: **§2.2b #harmonization-amplification** (= 派生間不一致は調和でなく SoT 検証で解決 — 整合性軸は coherent な誤りの不動点) / **§8.28 #confirmation-question-aim** (= 確認設問は照準した軸しか検証しない — 事実主張の user 確認は真偽を第一問に) / **§8.29 #generation-error-trigger-gap** (= 操作 trigger の gate は無操作の生成 error を素通しする — 内容 trigger / stage-boundary audit に張れ)。
- `physics-verification-cycle.md` §2 に **#identifier-anchor-coverage** bullet (= anchor は式・数値だけでなく identifier 〔人名・引用 ID・記号〕 にも — un-anchored の 3 class でちょうど 1 件ずつ事故った実測)。
- `kakenhi-proposal.md` #mock-review-and-claims 🔴 rule に kernel pointer 追記。
- 機械面 (層3) = `odakin-prefs/scripts/check-source-project-parity.py` (D) named-claim audit (同 repo `be52dc3`)。

## 2026-09-01g: Codex integration — L1 contract and routes consolidated

- The durable result of this session is canonical in
  [`codex/PARITY.md#codex-integration-sot`](codex/PARITY.md#codex-integration-sot).
  README, installed instructions, skills, and the personal-layer template
  route there; this entry intentionally carries no second technical record.
- No layer-1 implementation task remains. Per-machine evidence belongs to the
  prescribed audit and client review, not to this session snapshot.

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
