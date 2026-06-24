# Multi-session coordination — 同 user の並列 Claude session が race する

同じ user が同じマシン (or 別マシン) で **複数の Claude session を並列起動して同じ shared repo を同時編集** している状況は、 zoom session 中の long-running 議論や autocompact 復帰直後の sub-task spawn 等で日常的に発生する。 collaborator (= 他 user) との race は [`shared-repo.md`](shared-repo.md) の Git workflow で扱うが、 本ファイルは **同 user の concurrent Claude session 同士の race** という別軸の risk と防御を扱う。

scope: 1 user の手元で 2 つ以上の Claude session 〜 過去の自分 session が残した artifact (= 自 commit / 自 plan の `[x]` mark / 自 SESSION entry) を新 session が「他人 commit」 のように扱う場面。

---

## 1. 同 file path を別 session が独立に書く race

### 問題

- session A: 朝の zoom 中に `analyses/data/foo.yaml` を compile + commit
- session B (= session A 終了後、 別 chat tab で再開): user の「foo について analyze して」 指示で同じ `foo.yaml` を独立に compile しようとして Write tool で同 path を上書き

session A の commit を session B が pull せずに開始すると、 session B の `git status` には「`foo.yaml` は untracked」 と見える (= session B はその file の存在を知らない) → session B が Write tool で新規作成扱いになる → 同じ content なら git diff zero (= 害なし) だが、 content が分岐していると session A の work が silently 破壊される。

「同じ content になる」 保証は **存在しない**: dataset compile / script generation 等で似た choice をしても、 1 entry の order / 1 line の punctuation / asymmetric error の符号 で差分が出る。 偶然 overlap は **判断が pure に決まる task** (= raw data から compile、 既存 mirror から複製) でのみ発生し、 creative choice が混ざる task では分岐する。

### 防御策の階層

**(A) Session 開始時 reflex** (= 最優先、 全 session の冒頭で必須)

`shared-repo.md §「セッション開始時」` の `git fetch` + `git status` に加えて:

1. **`git log --oneline -5`** で **最後の 5 commit を確認** (= session の prev work と被っていないか)
2. **`SESSION.md` + 進行中 plan を読む** (= plan の `[x]` mark で「すでに実装済み」 と分かる task は重複実装しない)
3. **同名 file の last-modified を `ls -la <path>` で確認** (= 同 session 内で別 turn が触ったか確認、 timestamp が想定外なら別 session の work を疑う)

(A) はすべて pull だけでなく **「session の context として最新 state を読み込む」** ことが要点。 `git status` が「clean」 でも、 別 session の commit を pull していないだけかもしれない → `git fetch` の後に `git log` で実態確認。

**(B) Write 前 reflex** (= 新規 file 作成と思った時)

- `find ~/<repo> -path '*<basename>*'` で同名 file の有無を確認
- 既存があれば必ず `Read` で content を取って差分判断
- 「新規」 と思った path に既存 file があれば、 別 session が書いたもの (or 過去の自分 session が忘れた artifact) と仮定して **必ず Read してから決める**

**(C) Edit 前 Read** (= 既存 file 編集と判明した時)

Edit tool は `read_before_edit` 強制があるが、 **read のタイミングと edit の間に別 session の改変が挟まる可能性** がある (= zoom 中の real-time co-editing で頻発)。 Edit が

```
File has been modified since read, either by the user or by a linter.
Read it again before attempting to write it.
```

を返したら **必ず再 Read してから retry**。 retry を「直前の Edit 内容で再試行」 と reflex に判断すると、 別 session が pre-empt した content を上書きする。 retry の前に diff 判断:

1. 再 Read で latest 取得
2. 自分の予定変更が依然意味があるか確認 (= 別 session が同じ意図で先に edit していれば自分の変更は冗長)
3. 矛盾なし & 必要 → retry / 冗長 → skip / 矛盾あり → user 確認

### Anti-pattern

- **`git status` が clean だから別 session の work と被らないと assume**: clean は「自 session の uncommitted がない」 を意味するだけで、 別 session の最新 commit を pull したかは別問題。 fetch + log 確認が必要
- **Edit retry エラーを「またユーザーが触ったか」 で済ませて再 try**: 再 Read せずに retry すると pre-empt 内容を上書き
- **「新規 Write だから Read 不要」**: 新規だと思った path が既存だった事故が頻発。 Write tool は `read_before_write` を強制しないので、 自己規律で `find` or `ls` で先に確認

---

## 2. Plan / SESSION の `[x]` mark を「実装済」 と reflex 解釈する race

### 問題

session A が plan の `[x] foo.yaml compile` を **forward-look (= 「次に実装予定」)** の意図で書いて, 実装途中で session 中断。 session B が plan を読んで `[x]` を「実装済」 と解釈し、 重複実装を skip。 結果: 実装が永遠に欠落し、 SESSION.md 上は「完了」 のまま。

逆 pattern: session A が `[x]` を「実装済」 として書き、 session B が plan を読まずに同じ task を独立に再現。 上の §1 race と直結し、 偶然 content overlap なら害なし、 分岐すれば session A の work を破壊。

### 規律: `[x]` は **実装済のみ**、 forward-look は別マーカー

| マーカー | 意味 |
|---|---|
| `[ ]` | 未着手 |
| `[ ] (実装中: <commit-hash> ↓)` | 着手済、 部分実装、 まだ完了でない |
| `[x]` | **実装済**。 該当 commit が main に含まれている and その実装が当該 plan の意図を満たす |
| `[x] (forward-look)` | (使うなら) 明示ラベル必須、 別 session が「実装済」 と reflex 解釈しないように |

`[x] (forward-look)` は避けるのが原則。 forward-look は plan 本文に「次にやる」 section を別に作って、 checkbox 軸を「実装済 / 未着手」 の 2 値に保つ。 mixed semantics の checkbox は別 session で誤読される。

### 検証: session 開始時に `[x]` の信用度を git log で確認

新規 session で plan を読んで `[x]` を見たら、 その task が **対応する commit を含むか** を `git log --grep` で確認する習慣を入れる:

```bash
git log --oneline --all -- analyses/data/foo.yaml | head -3
# → commit が存在 = `[x]` 信用できる
# → 存在しない = forward-look の疑い、 plan 著者に確認 (= user) or 自分で実装
```

特に同日内の session re-entry では「self-trust の罠」 (= 「自分が `[x]` 書いたから実装したはず」) に陥りやすい。 git log で artifact を直接確認するのが安全。

### Anti-pattern

- **plan を流し読みして `[x]` を unconditionally trust**: forward-look 混入を見抜けず重複 skip
- **session 切れる直前に「予定として `[x]`」 を書く**: 次 session の自分 (or 別 Claude session) が誤読の温床になる。 切れる前に `[ ] (next session で実装)` の方が明示的

---

## 3. 自 session の prev commit を「他人 commit」 と扱う

### 観察

新 session が `git log` を見て、 同 user の prev session が打った commit を確認する時、 「**他人の commit と等価に扱う**」 のが安全。 つまり:

- commit message を読んで意図を理解 (= 自分の意図と想定するな)
- diff を読んで実装内容を確認 (= 自分が書いたつもりの code と等価でない可能性)
- 関連 plan / SESSION の最新 state も同様に「他人が書いた」 として cold-read

理由: prev session の Claude は別 context window で別 reasoning trail を持っていた。 同 user の chat だが context window は分断されている → 知識・前提・判断は別 entity と仮定する方が安全。

### 実例パターン

- prev session が attribution 訂正 commit (= arXiv preprint の著者帰責を別グループへ訂正) を打った後、 新 session が plan の旧著者名と書かれた残存箇所を読んで「旧著者帰責は確定」 と reflex 採用 → 訂正済 fact を逆戻り
- prev session が plan の Phase 2 task list で `[x]` を打った後、 新 session が「Phase 2 完了」 と reflex 解釈して Phase 3 着手 → Phase 2 の cross-check task が残っていることに気付かない

防御: `git log -p -3` で最近 3 commit の **完全 diff** を読み、 prev session の意図を context として吸収してから自 session の action を判断。

### SESSION narrative の stale (= state を変えた session が SESSION を更新しなかった)

prev session が repo の **state を変える commit** (例: review markup の accept 変換、 設定の切替) を打ったのに **SESSION.md を更新しなかった**場合、 SESSION の prose が現状を**積極的に誤って記述**する (= §2 `[x]` の aspirational 疑いより強く、 「〜は未反映 / 未着手」 等の断定が事実と逆になる)。

防御: 行動を分岐させる load-bearing な SESSION 主張 (= 「X は未反映」「Y は提案 markup のまま」 等) は **file/git の実体と突き合わせてから信用**する。 特に `git log --oneline -- SESSION.md` の「最後に SESSION を触った commit」 と「state を変えた commit」 がズレていたら narrative を疑う (= state 変更が SESSION を伴っていない = 記述が古い signal)。 grep / ls-tree / byte 比較等の安価な実測で裏取りし、 narrative を黙って上書きせず **stale を注記で flag してから user に渡す**。

---

## 4. zoom 中の real-time co-editing

### 状況

zoom session で user + Claude session が並列に動き、 user が手で `CLAUDE.md` / `SESSION.md` / plan を編集する一方、 Claude session が別 file を Edit する。 Edit tool の `File has been modified since read` エラーは zoom 中に高頻度で発生する (= 30 分の zoom で 3-5 回)。

### 規律

- **Edit エラー時の再 Read は必須** (§1 (C))
- **user の手動編集を尊重**: 自分の Edit と user の edit が conflict した時、 user の edit を優先 (= 「user の意図が反映された latest」 として再 Read)
- **重複 Edit を避けるための同期 signal**: zoom 中で user が「これは私が書く」 等の signal を出していたら、 当該 file は自 Edit を保留して user の commit を待つ
- **session 終了前に未 push commit + 未 commit 変更を確認** (= [`shared-repo.md §「セッション終了時」`](shared-repo.md))。 zoom 後に user が別マシンから pull する経路を保持

### user による手動編集の検出パターン

Claude tool result に

```
Note: <path> was modified, either by the user or by a linter.
This change was intentional, so make sure to take it into account as you proceed
```

の system reminder が混ざってきたら、 **その file への次 Edit 前に必ず Read** する。 system reminder 無しでも `File has been modified since read` が出たら同様。

---

## 5. 並列 session が共有 tmpdir を埋め、 Bash 出力が ENOSPC で消える

### 問題

Claude Code は各 Bash 呼び出しの stdout/stderr を per-session tmp dir (= macOS では `/private/tmp/claude-<uid>/.../tasks/*.output`) に書く。 同 user が **複数 session を並列運用**すると、 共有 tmpfs (= 小容量) が他 session の蓄積 output (= 特に PDF render PNG 等の大物) で満杯になり、 自 session の Bash が `temp filesystem ... is full (0MB free)` / `writes failed with ENOSPC` で **出力を失う** (= command 自体は実行されるが結果が読めない)。 file 系 tool (Edit/Write/Read) は別経路で影響を受けにくい。

### 対処

- **掃除**: `find /private/tmp/claude-* -name '*.output' -delete 2>/dev/null` (+ `-name '*.png'`) で旧 session task output を削除して空き回復。 ⚠️ 自 session の current output も消す race があるので、 削除と本命 command を 1 行に併記 + 本命は出力最小化 (`... >/dev/null 2>&1; echo rc=$?`)。
- **回避**: bash grep の代わりに **Read / Edit / Grep tool を使う** (= ENOSPC の影響小)。 git は `... 2>&1 | tail -1` 等で小出力化。
- **根治 (harness 側)**: `CLAUDE_CODE_TMPDIR` を空きのある FS に向けると安定 (= session 起動前の環境変数)。

### 実例 (2026-06-02)

ドキュメント整備 session 中、 別 Claude session が同 project で並行稼働し共有 tmpfs を埋め、 grep/git の Bash 出力が断続的に ENOSPC 消失。 旧 session output 削除で回復 → 以降 git は小出力 + file 系は Read/Edit に切替えて継続。

### 関連 (本 §)
- §1-§3 の並列 session race family の shared-resource 版 (= file race でなく tmpdir race)

---

## 6. Pilot single-brain — 並列 session に同型の構造/規約タスクを渡す時

### 問題

同じ convention / structural task (= anchor schema 設計、 SoT 統合、 index 形式の確定 等) を**複数の parallel session に「各自 完成まで」 渡す**と、 各 session が独立に設計判断を下し、 **divergent な解に着地**する。 §1 の「同 file を別 session が独立に書く」 race と違い、 ここで衝突するのは file content でなく **設計それ自体** (= anchor の命名規則、 slug の振り方、 registry の schema)。 結果、 各 session が「正しいが互いに非互換な convention」 を生み、 **"multiple SoT" 問題**を 1 段上 (= メタレベル) で再生産する (= 後で統合する羽目になり、 [`convention-design-principles.md` §15 「SoT consolidation recipe」](../docs/convention-design-principles.md) の是正手順を回す対象が増える)。

### 規律: sequential な pilot→worker にする (= parallel-to-completion にしない)

- **1 つの session が convention design を所有する** (= pilot single-brain)。 anchor / slug / registry schema 等の**設計を確定 (frozen) させる**のはこの 1 session だけ。
- 設計が frozen になってから、 **worker session には個別 entry の適用だけを伝播**する (= worker は schema を再設計せず、 確定済 schema に従って自分の担当 entry を埋めるだけ)。
- frozen な instruction を worker に渡す (= 「この slug 規則・この anchor 形式で適用せよ」 と明示)。 worker が設計判断を再度行う余地を残さない。

### Anti-pattern

- **同型タスクを N session に「完成まで」 fan-out**: 各 session が良かれと独立設計し、 N 個の非互換な convention が生まれる。 N が大きいほど後段の統合コストが爆発
- **pilot の設計が frozen 前に worker を走らせる**: worker が暫定 schema で適用を始め、 pilot が schema を変えると worker の成果が陳腐化 (= §13 のデータ→コード ordering と同型、 「確定する側」 を先に固める)

---

## 7. 別 session への hand-off と結果の返送 — spawn_task + send_message (token-handshake で宛先解決)

§1-6 は並列 race の **防御**。 本節は逆に、 **意図的に独立 session を起こして結果を受け取る** 構築的 technique。

### 用途と、 なぜ Agent でなくこちらか

「**完全に独立した別 session に作業を渡し、 結果も受け取りたい**」 とき。 委譲 primitive は 2 つあり desideratum が分かれている:

- **Agent (subagent)**: 結果は *呼び元に返る* が、 呼び元 context を継承する *subagent* で **独立でない** (呼び元 session 終了で消える / user が独立に steer 不可)。
- **spawn_task (新 session)**: *完全に独立* (own worktree / 呼び元記憶ゼロ / 呼び元終了後も生存 / user が steer 可) だが、 結果は *user に fire* で **呼び元に自動では返らない**。

⇒ ユーザーが「独立した新 session」 を求め、 かつ結果も要るなら、 **spawn_task に「結果を呼び元に返せ」 を組み合わせる** と「独立 ∧ 結果返送」 が in-scope で得られる (harness 変更不要)。 「新 session」 を Agent に潰さないこと (= [`convention-design-principles.md §4.1` 深層](../docs/convention-design-principles.md#motivated-substitution-trap) の deliverer-retention 置換 = ユーザーが名指した独立性を、 結果が自分に返る Agent へ無意識に潰す失敗)。

### robust な宛先解決 = token-handshake (method A)

呼び元が「自分の id を spawned に渡す」 のは **破綻する**: session が *自分で取得できる id* (= 自分の transcript file 名 / jsonl の `sessionId` field) は、 `send_message` / `list_sessions` が routing に使う *addressable id* (`local_<uuid>` 形式) と **一致する保証がない** (= 観測例では別物だった)。 加えて `list_sessions` は self を除外するので自分を引けない。 ⇒ 呼び元は自分の addressable id を実行時に確実には知れない。

robust 解:

1. **呼び元が会話 (= assistant の message turn) に unique token を残す** (= 衝突しない distinctive な文字列 `<TOKEN>`)。 ⚠️ **token は message turn に出す必要がある — spawn_task の spec (= tool_use 引数) に入れるだけでは findable にならない**: `search_session_transcripts` は user/assistant の **message のみ** index し tool_use 引数は対象外。 ∴ spec の token は spawned に「何を検索するか」 を渡すだけで、 呼び元の findability は chat echo だけが達成する (= 2026-06-24 incident: spec に token はあったが chat に出さず子の search が 0 件 → 手動特定に degrade。 親 transcript の forensic で token の first appearance が spawn_task の tool_use 引数だったことを確認)。
2. **spawned 側が完了時に `search_session_transcripts(<TOKEN>)` で全文検索** → HIT した session の addressable id を**直接取得** → `send_message` で結果を返す。
3. 結果は呼び元会話に `From <title>` の user turn として着地 (= user 確認 gate 経由)。

これは **呼び元が自分の id を知らなくても動く唯一 robust な方法**。 他は脆い: (B) 呼び元が id を渡す = 上記 namespace 不一致で誤 routing / (C) spawned が **similarity heuristic (title 意味一致 / cwd 一致 / recency / 話題近さ) で宛先を推定** = それは findability であって identity でない (= [`§8.14`](../docs/convention-design-principles.md#single-field-identity-corroboration) 単一一致≠同定 の cross-session routing 版) → **誤着** (実際に起きた; 観測例では起票元の title が generic だったため spawned が *話題が一致する無関係な sibling* を起票元と誤断。 recency はむしろ正解を指していたので「recency を見れば直る」 でもない = どの similarity 軸も identity の代用にできない)。

### 既定の返送路 + 子側 fail-safe (= token が落ちた / push が後付けされた時)

**既定の返送路は durable artifact (commit) = robust。 live session push は token が事前配置されている時のみ。** push の必要は *後から* 呼び元 user が live で要求して生じうる (= 起票時に async-only で設計しても後で push を頼まれる) ので、 token の事前配置は「push を計画しているか」 に condition せず常に行う。

token / handle が無いのに「起票元に返せ」 と言われた spawned は、 **絶対に similarity (title / cwd / recency / topic) で宛先を推測して push してはならない** (= 上記 (C) findability≠identity)。 手順:

1. `search_session_transcripts(<token>、 無ければ自分の spec の distinctive な語句)` で **自分を起票した session を content 照合で特定** (= identity を establish)。
2. self を除外し一意に解決できれば、 その session **のみ** に send_message。
3. 一意化できない / 候補ゼロなら **push せず durable file (commit 済) に倒し、 user に確認** (= 誤着を safe degrade に変える)。

identity は similarity でなく content corroboration でしか establish できない。

### spawn-spec template (= 結果を返したい委譲の boilerplate、 順 = robust 度)

- **durable deliverable (= required な spine)**: 成果物を決定的 path に commit し **その path を spec で固定**する (= 既定の返送路、 robust、 push が無くても結果が残る)。 呼び元は完了後その path を読む (= supervised でも「path が token を兼ねる」 pull が成立、 search も id discovery も不要)。 ⚠️ 置き場は spawn 時にどのみち決める = **construction-forced で落ちにくい** (= 2026-06-24 incident でも durable path は固定され機能し、 結果喪失ゼロだった — 壊れたのは下記 live-push の方だけ)。
- **token 行 + 返送指示 (= live-push を使うなら。 optional。 落としても上の durable pull が無傷なので harmless)**: 起票側の **会話 (message turn) に** unique token を残す (例 `RET-<slug>-<date>-<rand>`)。 ⚠️ spec にも token を書くが、 **呼び元を findable にするのは chat echo だけ** (= 上記 method A step 1 の機械、 spec=tool_use 引数は search 対象外)。 ⚠️ 「親の session-id 欄」 は作らない (= addressable id ≠ transcript id の namespace 不一致、 誤 id は推測より悪い、 robust なのは content marker = token)。 返送指示 = 「完了時 `search_session_transcripts(<token>)` で起票元を特定し send_message。 self/他 session 除外、 token を持つ起票元以外に絶対送らない。 token で解決不能なら push せず durable file のみ + user 確認 (推測 push 禁止)」。

⚠️ **「分離不能な 1 単位」 の真の atomic は spawn_task + durable deliverable** (= live-push の token/echo/push は optional layer)。 過去の「片方だけ適用」 失敗 (token 全落とし→誤着 / spec-only token→search 0 件) は、 live-push を required と誤認したことが半分。 live-push を optional と正しく置けば、 落ちやすい肢 (= chat echo、 局所 forcing が無く帰結が remote) が非 load-bearing になり、 失敗が「事故」 から「ping が無いだけ (= 固定 path の file を読めばよい)」 へ degrade する (= reminder を積む 〔§4.1 が構造的に無効と評価〕 でなく、 落ちる肢を非 load-bearing にして dissolve する subtraction)。

### 注意 (caveat)

- **⚠️ これらのツール (`spawn_task` / `send_message` / `search_session_transcripts` / `list_sessions`) は harness 依存で、 全環境にある保証はない。** Claude Code CLI (= 2026-06-21 確認) では deferred tools 一覧にも ToolSearch (= 概念検索 + exact name select の双方) にも無く呼べなかった。 = 本 §7 は Cowork 等これらを提供する harness での「観測例」 を前提に書かれており、 **その観測を全 harness に一般化していた** (= `convention-design-principles.md` の「一度の観察を一般法則化しない」 の doc-authoring 版 = doc が tool の実在を裏取りせず前提化する drift)。 CLI で「独立 session + 結果返送」 が要るときは **下記 file-handoff (pull) で spec ファイル化 → user が手動で別 CLI session を開いて拾う** 形にする (= Agent は「独立」 要件を満たさないので代替にしない)。 ⚠️ ただし deferred tools は session 中に動的 surface されうるので「絶対に無い」 とも断定しない (= 「現時点で呼べる tool に無い」 までが正確、 = inline §3「null を universal absence にしない」 の presence 版)。
- `send_message` は **常に user 確認を挟み、 unsupervised (auto / bypass) mode では使えない** ⇒ **この push 経路は supervised 専用**。 unsupervised (scheduled-task / cron) では下記「Unsupervised 返送」 の file-handoff (pull) を使う。
- **非同期**: 結果は spawned 完了時に届く (呼び元はブロックしない = 「自分の作業を続けたい」 と両立)。
- token は一意性を持たせる。 複数 HIT した場合 (= token が spawned の spec にも引用される等) も **recency で選ばない** (= similarity≠identity)。 self を除外し、 その token を *自分の発話として最初に残した* 起票元を呼び元とする。 判別不能なら push せず user 確認。 **token を持つ呼び元以外には絶対送らない** (= 誤着防止)。
- **⚠️ 機械 enforcement の限界**: spawn_task / send_message への PreToolUse guard は (a) 一部 harness (Cowork desktop 等) が hook を honor しない + (b) これらの tool が hook 非対応 harness に偏在し『hook が効く環境 ∩ tool がある環境』 が乏しいため ~無効 (= placebo にしない、 = [`hook-authoring.md §9.3`](hook-authoring.md))。 `list_sessions` に lineage (spawnedBy) field が在れば spawned が宛先を推測する必要自体が消えるが、 これは harness 側の改修 (= upstream、 本 doc の scope 外)。 ∴ 現状の防御は本 § の規律 (token + 子側 fail-safe) が担う。

### Unsupervised 返送 (= cron / scheduled / auto / bypass): file-handoff (pull)

返す先の live 会話も承認 user も居ない文脈では `send_message` が発火しない。 代わりに **decoupled な pull**:

- **どこに書くか**: orchestrator が **spawn 時に result path を契約として固定** (= ここでは **path が token の役割を兼ねる**。 supervised で token-handshake が要るのは consumer の addressable id が事前に不明だから / unsupervised は orchestrator が path を決めるので id discovery 不要)。 場所は **決定的なリポ内 path** (`/tmp` は不可 = reboot で消える + 別 session の誤参照、 [`expensive-intermediate-artifacts.md`](expensive-intermediate-artifacts.md))、 **self-describing な structured file** (`status: done|partial|failed` / timestamp / payload / error = cold な consumer が context ゼロで parse 可)、 collision-free な命名 (slug / run-id)。
- **consumer の拾い方**: (a) [主] 次の run が既知 path を読む (= cron の自然形、 `status==done ∧ fresh` を確認して consume + marker clear)、 (b) [従] spawner が live だが unsupervised なら既知 path を **bounded poll + timeout**。 timestamp で staleness 判定。
- **使い分け基準 (1 文)**: 結果を受け取る live 会話 (+ 承認 user) が在る → **send_message (push)** / 受け手も承認者も居ない → **決定的 path に書き consumer が次 run で読む (pull)**。

= push (send_message、 id を token で探す) と pull (file、 path が token を兼ねる) は同じ hand-off の **supervised / unsupervised 双対**。 producer が決定的 path に書き consumer が自分の schedule で読む pull は、 他の決定的-path/pull 機構 (定期生成物・status marker file 等) と同型。

### この technique の射程 (honest)

これは「結果が返らないから独立 session を避ける」 動機を解消し route を *可能にする*。 ただし route は **選択の瞬間に表象されている必要**があり (= 存在を知っているだけでは pre-deliberative な既定を変えない)。 ⚠️ **cross-session の「使えば馴染む」 習慣化は起きない** (= 各 session は fresh instance で学習の持ち越しが無い)。 route が選択の瞬間に表象されるのは (a) 同一 session 内で既に使った後 (in-context) か (b) auto-loaded surface (= session 冒頭で必ず読まれる場所) 経由のみで、 **ambient な convention doc (本 doc 含む) は cold session では発火しない**。 ⇒ technique は route を *可能にする* enabler であって、 それを必ず選ばせる仕組みではない (= 「書いた」 だけでは fresh session の既定は変わらない)。 (⚠️ 「結果が要らない場面でも独立を避けるなら *作る主体でいたい* 別動機が残る」 という説は証拠が薄く speculative — tool availability / 動機づけられた task 誤読で説明でき、 別個の cure を要する load-bearing 問題として扱わない。)

---

## 関連

- collaborator (= 他 user) との Git race / branching: [`shared-repo.md`](shared-repo.md)
- 4 軸 sweep + sweep goal alignment (= 「✓ pass」 closure を禁じる規律): [`CONVENTIONS.md` §3](../CONVENTIONS.md)
- review / audit の goal は error 発見 規律: 同上 §3 「sweep / review / audit の goal alignment」
- prev session の `[x]` を信頼するか自分で実装するかの境界判断: 個人層 (`<your>-prefs/`) の work-discipline に machine-local な reflex-trap として記録するのが筋 (= machine-dependent な作業 mode 切替)
