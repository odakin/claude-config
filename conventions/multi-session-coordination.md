<!-- doc-meta
when: 並列 Claude session と同じ repo を触るとき + spawn/handoff を設計するとき
category: harness-core
summary: 同 user の並列 Claude session が同 file path を race する防御 (= session 開始 git fetch + log + plan read、 Write 前 ls/find、 Edit 前 Read 強制、 commit 時は git add -A でなく明示 add 〔= 並行 session の未 commit WIP 巻き込み防止〕、 plan checkbox [x] は実装済のみ semantics、 prev session の commit を「他人 commit」 として cold-read)
-->
# Multi-session coordination — 同 user の並列 Claude session が race する

同じ user が同じマシン (or 別マシン) で **複数の Claude session を並列起動して同じ shared repo を同時編集** している状況は、 zoom session 中の long-running 議論や autocompact 復帰直後の sub-task spawn 等で日常的に発生する。 collaborator (= 他 user) との race は [`shared-repo.md`](shared-repo.md) の Git workflow で扱うが、 本ファイルは **同 user の concurrent Claude session 同士の race** という別軸の risk と防御を扱う。

scope: 1 user の手元で 2 つ以上の Claude session 〜 過去の自分 session が残した artifact (= 自 commit / 自 plan の `[x]` mark / 自 SESSION entry) を新 session が「他人 commit」 のように扱う場面。

---

## <a id="file-path-race"></a>1. 同 file path を別 session が独立に書く race

### 問題

- session A: 朝の zoom 中に `analyses/data/foo.yaml` を compile + commit
- session B (= session A 終了後、 別 chat tab で再開): user の「foo について analyze して」 指示で同じ `foo.yaml` を独立に compile しようとして Write tool で同 path を上書き

session A の commit を session B が pull せずに開始すると、 session B の `git status` には「`foo.yaml` は untracked」 と見える (= session B はその file の存在を知らない) → session B が Write tool で新規作成扱いになる → 同じ content なら git diff zero (= 害なし) だが、 content が分岐していると session A の work が silently 破壊される。

「同じ content になる」 保証は **存在しない**: dataset compile / script generation 等で似た choice をしても、 1 entry の order / 1 line の punctuation / asymmetric error の符号 で差分が出る。 偶然 overlap は **判断が pure に決まる task** (= raw data から compile、 既存 mirror から複製) でのみ発生し、 creative choice が混ざる task では分岐する。

### 防御策の階層

**(A) Session 開始時 reflex** (= 最優先、 全 session の冒頭で必須)

[`shared-repo.md` session-start](shared-repo.md#session-start) の `git fetch` + `git status` に加えて:

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

**(D) Commit 時 reflex** (= stage する時)

- 並行 session が同 tree に居る (可能性がある) 環境では **`git add -A` / `git add .` を使わない** — 相手の**未 commit の WIP** を丸ごと自 commit に巻き込む (= 自分の commit message が説明しない変更が push され、 相手の WIP が中間状態で publish される + 相手側からは自分の編集が「勝手に consume された」 ように見える)。 **自分が編集した file を明示列挙して add** する
- 実例 (2026-07-10): session X が script を編集中 (前半 commit 済・続き未 commit) のところへ、 session Y が別作業の `git add -A` で X の未 commit 分 42 行を無関係な message の commit に混入させて push。 X はその上に続きを積めたため実害は attribution の濁りに留まったが、 X の WIP が中間状態で publish される class の事故。 **同型再発 (2026-07-25)**: 「repo A は並行 session が編集中だから add を限定しろ」 という警告を chat で受け **repo A では遵守した** session が、 直後に隣の repo B で `git add -A` を打ち並行 session の WIP 3 file を巻き込んだ — 警告を named repo の話として受け取り一般原則に拡張し損ねた形で、 **rule の in-context presence でも止まらなかった** (= 防御は「並行 session が居る間はどの repo でも明示 add」 という無条件 reflex 側に置く。 巻き込んだ側の事後責務 = 相手 session への通知 + 巻き込み内容の commit message / 記録での明示、 history 書き換えはしない)

### Anti-pattern

- **`git status` が clean だから別 session の work と被らないと assume**: clean は「自 session の uncommitted がない」 を意味するだけで、 別 session の最新 commit を pull したかは別問題。 fetch + log 確認が必要
- **Edit retry エラーを「またユーザーが触ったか」 で済ませて再 try**: 再 Read せずに retry すると pre-empt 内容を上書き
- **「新規 Write だから Read 不要」**: 新規だと思った path が既存だった事故が頻発。 Write tool は `read_before_write` を強制しないので、 自己規律で `find` or `ls` で先に確認
- **`git add -A` なら「自分の変更だけが stage される」 と assume**: 並行 session の未 commit WIP も無差別に拾う ((D) 参照)。 明示 add が defense

---

## <a id="plan-checkbox-semantics"></a>2. Plan / SESSION の `[x]` mark を「実装済」 と reflex 解釈する race

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

## <a id="prev-commit-as-foreign"></a>3. 自 session の prev commit を「他人 commit」 と扱う

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

## <a id="realtime-coediting"></a>4. zoom 中の real-time co-editing

### 状況

zoom session で user + Claude session が並列に動き、 user が手で `CLAUDE.md` / `SESSION.md` / plan を編集する一方、 Claude session が別 file を Edit する。 Edit tool の `File has been modified since read` エラーは zoom 中に高頻度で発生する (= 30 分の zoom で 3-5 回)。

### 規律

- **Edit エラー時の再 Read は必須** (§1 (C))
- **user の手動編集を尊重**: 自分の Edit と user の edit が conflict した時、 user の edit を優先 (= 「user の意図が反映された latest」 として再 Read)
- **重複 Edit を避けるための同期 signal**: zoom 中で user が「これは私が書く」 等の signal を出していたら、 当該 file は自 Edit を保留して user の commit を待つ
- **session 終了前に未 push commit + 未 commit 変更を確認** (= [`shared-repo.md` session-end](shared-repo.md#session-end))。 zoom 後に user が別マシンから pull する経路を保持

### user による手動編集の検出パターン

Claude tool result に

```
Note: <path> was modified, either by the user or by a linter.
This change was intentional, so make sure to take it into account as you proceed
```

の system reminder が混ざってきたら、 **その file への次 Edit 前に必ず Read** する。 system reminder 無しでも `File has been modified since read` が出たら同様。

---

## <a id="shared-tmpdir-enospc"></a>5. 並列 session が共有 tmpdir を埋め、 Bash 出力が ENOSPC で消える

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

## <a id="pilot-single-brain"></a>6. Pilot single-brain — 並列 session に同型の構造/規約タスクを渡す時

### 問題

同じ convention / structural task (= anchor schema 設計、 SoT 統合、 index 形式の確定 等) を**複数の parallel session に「各自 完成まで」 渡す**と、 各 session が独立に設計判断を下し、 **divergent な解に着地**する。 §1 の「同 file を別 session が独立に書く」 race と違い、 ここで衝突するのは file content でなく **設計それ自体** (= anchor の命名規則、 slug の振り方、 registry の schema)。 結果、 各 session が「正しいが互いに非互換な convention」 を生み、 **"multiple SoT" 問題**を 1 段上 (= メタレベル) で再生産する (= 後で統合する羽目になり、 [`convention-design-principles.md` §15](../docs/convention-design-principles.md#sot-consolidation-recipe) 「SoT consolidation recipe」 の是正手順を回す対象が増える)。

### 規律: sequential な pilot→worker にする (= parallel-to-completion にしない)

- **1 つの session が convention design を所有する** (= pilot single-brain)。 anchor / slug / registry schema 等の**設計を確定 (frozen) させる**のはこの 1 session だけ。
- 設計が frozen になってから、 **worker session には個別 entry の適用だけを伝播**する (= worker は schema を再設計せず、 確定済 schema に従って自分の担当 entry を埋めるだけ)。
- frozen な instruction を worker に渡す (= 「この slug 規則・この anchor 形式で適用せよ」 と明示)。 worker が設計判断を再度行う余地を残さない。

### Anti-pattern

- **同型タスクを N session に「完成まで」 fan-out**: 各 session が良かれと独立設計し、 N 個の非互換な convention が生まれる。 N が大きいほど後段の統合コストが爆発
- **pilot の設計が frozen 前に worker を走らせる**: worker が暫定 schema で適用を始め、 pilot が schema を変えると worker の成果が陳腐化 (= §13 のデータ→コード ordering と同型、 「確定する側」 を先に固める)

---

## <a id="spawn-handoff-token-return"></a>7. 別 session への hand-off と結果の返送 — spawn_task + send_message (token-handshake で宛先解決)

§1-6 は並列 race の **防御**。 本節は逆に、 **意図的に独立 session を起こして結果を受け取る** 構築的 technique。

### 用途と、 なぜ Agent でなくこちらか

「**完全に独立した別 session に作業を渡し、 結果も受け取りたい**」 とき。 委譲 primitive は 2 つあり、 **3 軸**で性質が分かれる:

| 軸 | Agent (subagent) | 別 session (spawn_task / 下記 file-handoff) |
|---|---|---|
| **ブロッキング (= 並列性)** | **build 依存 — CLI 2.1.232 (2026-08) 以降の interactive session は background 既定で非同期 (= 呼び元は解放、 完了時に通知)。 それ以前の build / SDK / headless / `run_in_background: false` 明示は同期で、 呼び元は Agent 完了までブロックし idle で待つ** (いずれにせよ独立 session ではない = 下段) | **非同期 — 委譲した瞬間に呼び元が解放され、 別 session が走る間も自分の作業を続けられる** (真の並列) |
| 独立性 | 呼び元 context を継承する *subagent* で **独立でない** (呼び元 session 終了で消える / user が独立に steer 不可) | **完全に独立** (own worktree〔= 任意、 §8〕 / 呼び元記憶ゼロ / 呼び元終了後も生存 / user が steer 可) |
| 結果返送 | 結果は *呼び元に自動で返る* | 結果は *自動では返らない* → 下記 token-handshake (push) / file-handoff (pull) で返す |

**⚠️ 最重要 (= 見落とされやすい実害): Agent は呼び元を同期ブロックする。** Agent が走っている間、 呼び元の会話 (= 人間が今見ている session) は次の作業に進めず手待ちになる。 作業が長いほど待ちは長い。 さらに **複数の session がそれぞれ Agent に委譲すると、 その全部が同時に凍る** = 人間の手元の全 session が一斉に手待ちになり **仕事が止まる = 純粋な無駄** (= 2026-06-27 に実際に 2 session 同時 stall で観測、 本節強化の契機)。 別 session は真に並列ゆえ、 委譲の瞬間に呼び元が解放され、 人間は他の作業を続けられる。

⇒ **ユーザーが「別セッション / 独立した新 session」 を名指したら、 Agent でなく別 session を使う** (spawn_task、 無ければ下記 §file-handoff)。 これは破ってはならない既定: Agent は (a) 上記の通り呼び元をブロックして仕事を止め、 (b) そもそも独立 session でない (= ユーザーが名指した「別」 を満たさない)。 結果も要るなら spawn_task に「結果を呼び元に返せ」 を併せれば **「独立 ∧ 非ブロッキング ∧ 結果返送」 が同時に in-scope** で得られる (harness 変更不要)。 「新 session」 を Agent に潰すのは [`convention-design-principles.md §4.1` 深層](../docs/convention-design-principles.md#motivated-substitution-trap) の deliverer-retention 置換 (= ユーザーが名指した独立性を、 結果が自分に返る Agent へ無意識に潰す失敗) — §4.1 は **「なぜ滑るか」** の説明であって、 **滑った時の実害がこのブロッキング (= 仕事が止まる)**。

**🚦 標準ルーティング (= 「仕事を止めない」 ための既定。 本節の運用結論 = 必ずこれに従う):**

| 仕事の性質 | 使う道具 | なぜ親 (呼び元) が止まらないか |
|---|---|---|
| **長い / 独立 / ユーザーがオーナーの仕事** | **別セッション** (spawn_task / 下記 file-handoff) | 構造上ぜったいに親を止めない (別プロセス・別 context window) |
| **答えを自分の手元に戻して今の作業に繋ぐ調査** | **background Agent** (`run_in_background: true`) | 非同期 — 委譲した瞬間に呼び元が解放され、 完了時に通知で戻る |
| 前景 Agent (= `run_in_background: false` 明示。 2.1.232 より前の build では省略も前景) | **禁止** | 前景 *だけ* が呼び元を同期ブロックして止める。 同ターン内 inline chaining の便宜は失うが、 background + ターンを跨いで結果受領で代替でき (= 結果は呼び元の context に戻る・1 往復遅いだけ)、 親は止まらない |

**∴ Agent は必ず `run_in_background: true` を明示で付ける (= 前景は禁止、 「ほぼ」 でなく全面)。** ⚠️ **upstream 状況 (2026-08-17)**: この要求を出した [anthropics/claude-code#71768](https://github.com/anthropics/claude-code/issues/71768) が maintainer により「shipped」 で close — CHANGELOG 2.1.232「non-teammate agent spawns in interactive sessions now run in the background by default」 + interactive では foreground option 自体が撤去、 frontmatter `background: true` で per-agent pin 可。 ∴ 最新 CLI では省略しても本規律を満たすが、 **明示は維持する** (= (a) 2.1.232 より前の build / Agent SDK / headless は既定が同期のまま = build 横断の耐性、 (b) 下記 legibility の二重化。 規律の文面は変えない、 「既定がそうなった」 は明示を外す理由にならない)。 理由は 2 つ: (i) 前景 *だけ* が親を止める、 (ii) **legibility** = `ask:Agent` の承認ダイアログは生引数を出すだけで前景/background を読み取りにくい (= `run_in_background` を省くと前景なのに dialog に何の印も出ない) → **常に background に固定すれば「dialog に現れた Agent は必ず background (= 止まらない)」 と確定**し、 human は gate で「これは止まるやつか?」 を判定せず済む (= veto は『そもそも立てるべきか・別 session にすべきか』 だけに使える)。 明示 `true` は dialog 引数でも裏取りできる二重化。 ⚠️ **機械 backstop の frontend 別整理** (= 2 段ある):
- **(a) 細かい強制** (= 「background 無しの Agent だけ deny して付け直させる」 等、 tool 引数を見る介入型 guard) は **CLI のみ可**。 desktop app は介入型 guard が原理的に不能 ([`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork))。
- **(b) 粗い pre-launch gate** (= settings.json `permissions.ask` に **`Agent` ツール名を入れる**) は **desktop でも honor される**: Agent 起動の*前*に承認ダイアログが出て human が veto できる (= mail 誤送信 gate と同機構、 `defaultMode: default` 前提、 [`claude-code-permissions.md` desktop-per-tool-gate](claude-code-permissions.md#desktop-per-tool-gate))。 前景/background の自動判別はできない (= 引数を見ないので) が、 human が dialog で「background か別 session で」 と差し戻せる。 tradeoff = 正当な調査 Agent も毎回承認。

∴ desktop でも「Agent 起動を human の一拍に乗せる」 機械 backstop は在る ((b))。 その上で *前景禁止 (= 常に background)* を保つのは依然 *規律* (= dialog 通過後に Claude が前景を選ばない保証は機械化されない — desktop は引数を見て前景だけ弾けない) で、 最後の砦は human-steering。

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

### spawn-spec template (= 結果を返したい委譲の boilerplate)

**設計目標 = 結果が呼び元 (人間) に *自動で* 届く。 人間に検索/記憶/fetch させない (= 機械が手間を消す、 2026-06-24 RCA + user 訂正「機械が人間を楽にするためにある」)。** ⚠️ 一度この template を「durable file を人間が読みに行く」 方向へ書き換えたが、 機械から人間へ手間を移す逆方向で撤回した。

**required (= 機械が結果を人間に届ける spine)**:

- **deliverable を決定的 path に commit** (= 結果の実体、 push が無くても残る)。
- **完了 marker を決定的な "results inbox" に 1 個落とす** (= status / result_path / 1 行要約)。 これを **surfacing 機構** (= session 開始時の surface・dashboard・OS 通知) が拾い、 人間が次に居る *どの session でも* 「結果が届いた・場所はここ」 と自動表示する。 surfacing は file を読む script 操作なので機械化可能 (= model の chat 出力にも親の findability 仕込みにも依存しない)。 ⚠️ marker は **子自身の完了 action** なので live-push より reliable。 ⚠️ inbox / surfacing 機構の実体は各 user の private layer に置く (= 本 public doc は *形* のみ規定、 具体 path は書かない)。

**task sizing (= worker を殺さない)**: 長い導出・生成 task を 1 spec に mega 盛りしない — worker は 1 応答の出力上限 (thinking 込み) を超える巨大 turn を試みると **決定的 retry loop で silent 死する**。 spec に焼き込む分割・turn 規律・部分結果 permission の正本 = [`output-cap-death-loop.md`](output-cap-death-loop.md#prevention-spec-rules)。 **どの大きさに切るか** (= sizing 述語) と **orientation cost の spec 前払い** は [§9](#worker-task-sizing)。

**optional (= live-push の bonus。 効けば即時 push、 落ちても上の auto-surface が拾うので人間は何もしない)**:

- **token 行**: 起票側の会話 (= assistant の message turn) に unique token を残す (spec にも明記、 例 `RET-<slug>-<date>-<rand>`)。 ⚠️ **chat に出さないと `search_session_transcripts` に引っかからず呼び元が findable にならない** (= method A step 1、 spec=tool_use 引数は search 対象外)。 ⚠️ 「親の session-id 欄」 は作らない (= addressable id ≠ transcript id の namespace 不一致、 誤 id は推測より悪い、 robust なのは content marker = token)。
- **返送指示**: 「完了時 `search_session_transcripts(<token>)` で起票元を特定し send_message。 self/他 session 除外、 token を持つ起票元以外に絶対送らない。 解決不能なら push せず + user 確認 (推測 push 禁止)」。

### <a id="return-signal-economy"></a>Marker 経済 — 完了 marker は「受領義務」 の model であって完了 log ではない (2026-07-14)

required spine の完了 marker は「**人間が受領するまで surface し続ける義務**」 を 1 個 mint する操作 (= consumed になるまで毎 session 開始時に出る、 消すには手動 consume が要る)。 ∴ mint は「完了の記録」 でなく「**受領してもらう必要**」 がある時に行う — 記録自体は deliverable の commit が既に担っている。 これを無差別に行うと委譲 chain (実装 → 検品 → 検品の検品 …) の各段が marker を増殖させ、 子 marker・孫 marker が誰にも consume されず滞留する = **人間の注意を節約するための機構が人間の注意に課税し始める** (2026-07-14 観測: 起票者が「報告不要」 と明示した検品 spec に、 spine を反射で丸写しして 2 個目の marker 義務を焼き込み user 訂正)。

1. **報告 waiver は marker にも及ぶ。** 起票者が「返事不要・完了通知不要」 と明示したら、 それは live-push (send_message) だけでなく完了 marker (= もう一つの返送経路) にも適用する — clean 完了は mint しない、 deliverable の commit が durable 記録。 ⚠️ waiver が放棄したのは「完了通知」 であって「問題の報告」 ではない: **行動を要する発見** (= FAIL verdict / major issue / user 判断 gate) が出たらその時だけ mint する (= findings-only marker policy)。
2. **1 系譜 1 marker。** 同一作業系譜の follow-up (検品 / land / fix) は新 token で 2 個目を mint しない — root token の marker を更新する (= 同 token での再 record は in-place 更新挙動にする) か、 旧 marker を consume してから置く。 常に高々 1 個。
3. **meta-work の default = findings-only。** 検品・review 等の meta 段は clean pass なら silent 終端 (= 結果 file のみ)。 これで chain は自然に沈黙終息し、 孫 marker が構造的に生まれない。
4. **consume は受領した turn 内で完遂。** marker の内容を人間が受領した (= surface を見て言及した / live で結果を受け取った) session は、 同 turn で consume まで実行する。 「後で consume」 が滞留の入口。 consume は marker の所在 + token だけで誰でも可 (= 親 session である必要はない、 下の「consumer の拾い方」 と同型)。

不変条件は変えない: 「**作られた受領義務は取りこぼさない** (= consumed まで surface し続ける)」 は維持し、 本節は「**義務をいつ作るか**」 を絞る = no-silent-drop と no-noise-accumulation の両立。

### <a id="receiver-side-recognition"></a>受け取った側 = 「自分が worker か」 の判定 (2026-07-07 試験 rule)

sender 側は上記 spawn-spec template を書いて chip を投げる。 receiver 側の逆問い = **自分が今受け取っている message は spawn-spec template そのものか**。 そうであれば **君 = worker**、 その prompt を再度 spawn_task に転記して grandchild を作らない (= 冗長な 1 段 indirection、 handoff-chain の無限延長を招く)。 execute in-tree。

**判別 signal (form-syntactic、 動詞の semantic 判別より頑健)**:

- 決定的 path (spec / results / return spine) 明示
- unique token
- 完了時実行 command 全文 (= results-inbox の `--record` 系)
- 「上位 session の次回起動時に自動 surface」 等の **上位 session 前提** wording

これらが揃った message を受けたら **その prompt を再 spawn しない**。 template の構造要素そのものが「君は終端の worker」 を示す **addressing の form marker** である (sender は自分を「上位」 として frame している = message は自分より下位 = 君に向けて書かれている)。 動詞 semantic 判別 (「投げて」 = spawn 明示 vs 「担当してほしい」 = execute 明示 vs あいまい 3-way) より、 form の syntactic 判別が頑健 = 前者は [`convention-design-principles.md §8.8 (= #proxy-blind-spot)`](../docs/convention-design-principles.md#proxy-blind-spot) の意味的 proxy 判別に該当、 後者は proxy でなく form 直接。

**根**: [`convention-design-principles.md §4.1 (= #motivated-substitution-trap)`](../docs/convention-design-principles.md#motivated-substitution-trap) の inverse-direction 発現 = 泥仕事を admin 役 (chip-authoring) に退避 = deliverer-retention の反方向 substitution。 2026-07-07 Evidence 参照。

⚠️ **試験 rule 段階 (2026-07-07 land 時点、 empirically untested)**: §4.1 doctrine「ambient rule 追加は既に override された最強信号より弱い → 構造的に無効」 は本 rule にも fade を **predict** する。 他 rule で fade は実証あり (2026-06-27 SPAWN-STATUS-CONFAB F3 = 4 分前 in-context Read でも未発火 / 2026-06-29 WTLOCAL-TITLE-REMISS = 2 日前 land + 常時 load でも未発火 / 2026-07-04 CHATLINK F1 = 4 重 load 下でも未発火)。 receiver-side recognition は未 test の rule で、 「form-syntactic な rule は semantic reflex より頑健」 という hypothesis の test 素材。 2-3 週の observation で判定:

- **効いた (再発ゼロ)** → §4.1 doctrine の boundary refine (= form-syntactic rule は fade しない亜種の可能性)
- **再発 (fade)** → §4.1 evidence 追記 + 本 rule 廃止 or 縮退。 「rule 追加は無効」 doctrine を form-syntactic domain にも extend する追認。

⚠️ 判定 trigger = (a) 3 ヶ月以内に本 rule が発火した観測 (= assistant が chip-prompt-format を receive して in-tree 実行に切替えた明示 record)、 (b) 3 ヶ月以内に同型再発 (= chip-prompt-format 受領 → grandchild 誤 spawn)、 (c) いずれも観測されない (= evidence 不足 for evaluate)。 (c) は「本 rule の fire は目立たない = 予防効果ゆえ observe 困難」 の可能性を含む (= placebo と区別困難)。

### 注意 (caveat)

- **⚠️ これらのツール (`spawn_task` / `send_message` / `search_session_transcripts` / `list_sessions`) は harness 依存で、 全環境にある保証はない。** Claude Code CLI (= 2026-06-21 確認) では deferred tools 一覧にも ToolSearch (= 概念検索 + exact name select の双方) にも無く呼べなかった。 = 本 §7 は Claude Code (desktop) 等これらを提供する harness での「観測例」 を前提に書かれており、 **その観測を全 harness に一般化していた** (= `convention-design-principles.md` の「一度の観察を一般法則化しない」 の doc-authoring 版 = doc が tool の実在を裏取りせず前提化する drift)。 CLI で「独立 session + 結果返送」 が要るときは **下記 file-handoff (pull) で spec ファイル化 → user が手動で別 CLI session を開いて拾う** 形にする (= Agent は「独立」 要件を満たさないので代替にしない)。 ⚠️ ただし deferred tools は session 中に動的 surface されうるので「絶対に無い」 とも断定しない (= 「現時点で呼べる tool に無い」 までが正確、 = inline §3「null を universal absence にしない」 の presence 版)。
- `send_message` は **常に user 確認を挟み、 unsupervised (auto / bypass) mode では使えない** ⇒ **この push 経路は supervised 専用**。 unsupervised (scheduled-task / cron) では下記「Unsupervised 返送」 の file-handoff (pull) を使う。
- **⚠️ live-push (`search_session_transcripts` / `send_message`) は permission 設定で抑止できない always-prompt class** (= tool 側が「毎回明示承認」 を宣言、 `allow` 登録済 + `defaultMode: default` でも承認チップが出る = 起票元へ返すたびに踏む。 観測 2026-06-28、 機構正本 = [`claude-code-permissions.md` §always-approve-tools](claude-code-permissions.md#always-approve-tools))。 ∴ **required spine の results-inbox marker がチップを踏まない正規経路**、 live-push は「効けば bonus」 だがチップ込み (= この点でも optional 扱いが正しい)。
- **非同期**: 結果は spawned 完了時に届く (呼び元はブロックしない = 「自分の作業を続けたい」 と両立)。
- token は一意性を持たせる。 複数 HIT した場合 (= token が spawned の spec にも引用される等) も **recency で選ばない** (= similarity≠identity)。 self を除外し、 その token を *自分の発話として最初に残した* 起票元を呼び元とする。 判別不能なら push せず user 確認。 **token を持つ呼び元以外には絶対送らない** (= 誤着防止)。
- **⚠️ 機械 enforcement の限界**: spawn_task / send_message への PreToolUse guard は (a) 一部 harness (Claude Code desktop 等) が hook を honor しない + (b) これらの tool が hook 非対応 harness に偏在し『hook が効く環境 ∩ tool がある環境』 が乏しいため ~無効 (= placebo にしない、 = [`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork))。 `list_sessions` に lineage (spawnedBy) field が在れば spawned が宛先を推測する必要自体が消えるが、 これは harness 側の改修 (= upstream、 本 doc の scope 外)。 ∴ 現状の防御は本 § の規律 (token + 子側 fail-safe) が担う。

### Unsupervised 返送 (= cron / scheduled / auto / bypass): file-handoff (pull)

返す先の live 会話も承認 user も居ない文脈では `send_message` が発火しない。 代わりに **decoupled な pull**:

- **どこに書くか**: orchestrator が **spawn 時に result path を契約として固定** (= ここでは **path が token の役割を兼ねる**。 supervised で token-handshake が要るのは consumer の addressable id が事前に不明だから / unsupervised は orchestrator が path を決めるので id discovery 不要)。 場所は **決定的なリポ内 path** (`/tmp` は不可 = reboot で消える + 別 session の誤参照、 [`expensive-intermediate-artifacts.md`](expensive-intermediate-artifacts.md))、 **self-describing な structured file** (`status: done|partial|failed` / timestamp / payload / error = cold な consumer が context ゼロで parse 可)、 collision-free な命名 (slug / run-id)。
- **consumer の拾い方**: (a) [主] 次の run が既知 path を読む (= cron の自然形、 `status==done ∧ fresh` を確認して consume + marker clear)、 (b) [従] spawner が live だが unsupervised なら既知 path を **bounded poll + timeout**。 timestamp で staleness 判定。
- **使い分け基準 (1 文)**: 結果を受け取る live 会話 (+ 承認 user) が在る → **send_message (push)** / 受け手も承認者も居ない → **決定的 path に書き consumer が次 run で読む (pull)**。

= push (send_message、 id を token で探す) と pull (file、 path が token を兼ねる) は同じ hand-off の **supervised / unsupervised 双対**。 producer が決定的 path に書き consumer が自分の schedule で読む pull は、 他の決定的-path/pull 機構 (定期生成物・status marker file 等) と同型。

### この technique の射程 (honest)

これは「結果が返らないから独立 session を避ける」 動機を解消し route を *可能にする*。 ただし route は **選択の瞬間に表象されている必要**があり (= 存在を知っているだけでは pre-deliberative な既定を変えない)。 ⚠️ **cross-session の「使えば馴染む」 習慣化は起きない** (= 各 session は fresh instance で学習の持ち越しが無い)。 route が選択の瞬間に表象されるのは (a) 同一 session 内で既に使った後 (in-context) か (b) auto-loaded surface (= session 冒頭で必ず読まれる場所) 経由のみで、 **ambient な convention doc (本 doc 含む) は cold session では発火しない**。 ⇒ technique は route を *可能にする* enabler であって、 それを必ず選ばせる仕組みではない (= 「書いた」 だけでは fresh session の既定は変わらない)。 (⚠️ 「結果が要らない場面でも独立を避けるなら *作る主体でいたい* 別動機が残る」 という説は証拠が薄く speculative — tool availability / 動機づけられた task 誤読で説明でき、 別個の cure を要する load-bearing 問題として扱わない。)

### 親が子の起動 / 走行を知る (= 第 3 方向、 parent → child)

上記は全て **結果の返送** (child → parent)。 別 need = **親が「chip が起動したか・子が走っているか」 を live で知りたい** (= 例: 長く走る子を course-correct したい)。 ⚠️ まず frame: **完了結果は上記 spawn-spec template の results-inbox marker が必ず自動で届ける**ので、 live 起動確認は *course-correct が要る稀ケース限定*、 過剰利用しない。

棚卸し済の現実解 (= 2026-06-27 に親 session で probe して確定):

- ❌ **`read_widget_context("spawn_task")` は使えない**: 親 session で実走 (`spawn_task` / `mcp__ccd_session__spawn_task` 双方) → `No widget context available`。 chip は readable widget context として state を露出しない (= 当初は「新規 tool ゼロで起動を知る最有力 lead」 だったが negative 確定)。
- ❌ **`Task*` family も chip を追えない**: `TaskList` / `TaskGet` = session-local な構造化 TODO (= 別 namespace、 spawn chip は列挙されない)、 `TaskOutput` / `TaskStop` = in-session background task 用で DEPRECATED。 chip の `task_id` (= `mcp__ccd_session__*` namespace) を status-query する tool は無い。
- ✅ **現実解 = `list_sessions` を chip の distinctive な title で突き合わせ**: `isRunning` / `lastActivityAt` で走行を確認 (sessionId / cwd / branch も取れる)。 ⚠️ `list_sessions` は **self 除外 + task_id → session の対応無し**ゆえ title / cwd / branch の **突き合わせ** が要る。 title が generic だと誤特定 ([`§8.14`](../docs/convention-design-principles.md#single-field-identity-corroboration) の cross-session 版) → **chip に distinctive な title を付ける** (§8 の `[local推奨]` / `[worktree推奨]` prefix も識別の足しになる)。
- ❌ **`dismiss_task` の "already started" 返りを起動確認に使うな**: 破壊的意図と紛らわしく、 消そうとしないと分からない偶然依存。

honest な天井: **「起動した」 を *live 親に自動 push* する経路は harness 上ほぼ無い** (= harness 通知無し / desktop hook gap で SessionStart 注入が live 親に効かない 〔[`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork)〕 / `send_message` は child → parent + user 確認)。 ∴ realistic な上限は **discoverable な pull** = 本手順で、 「完了は auto-deliver のまま起動確認だけ on-demand に倒した」 honest な fallback (= 結果を取りこぼす穴ではない)。 真の根治は **upstream** (`spawn_task` が session_id を返す / `list_sessions` に `spawnedBy` lineage field があれば突き合わせ fragility も discoverability も一掃される = §7 caveat の lineage field と同根、 harness 改修ゆえ本 doc scope 外)。

〔3 方向の責務境界: **完了** = results-inbox marker (child → 人間 / 未来 session) ／ **findability** = 本 §7 method A (child → parent) ／ **本節** = parent → child 起動。〕

---

### <a id="green-light-carrier"></a>green-light は同 turn で「運搬体 (carrier)」 を持たねばならない — 「別 session 待ち」 は carrier ではない

**失敗 mode**: handoff spec (plan file) を書き、 実装 OK (= green-light) も取れているのに、 状態表記が「別 session 待ち」 のまま**誰にも push されず眠る**。 待ち行列に (a) **時計が無い** (= deadline を持たない義務は deadline 系の surfacing 全部の圏外)、 (b) **owner が無い** (= 「どこかの将来 session」 は全 session にとって他人の仕事 = 責任の拡散)。 ambient に置かれた doc は cold で発火しない (= 各 session は fresh instance) ため、 これは「いつか拾われる」 のではなく**構造的に拾われない**。 実事例: ある再発防止 plan が green-light 済みのまま 2 ヶ月滞留し、 その間に防ぐはずだった同型 incident の 3 例目が発生した (= 対策の設計は正しかったのに、 queue の力学で負けた)。

**ルール**: **決定 (green-light) が生まれた同 turn で、 機械に push される運搬体へ変換する**。 運搬体は次のどれか:

1. **spawn_task chip** (harness にあれば) — user の可視 queue に入り、 1 click で worker session が立つ
2. **deadline つき TODO** (task ledger に mint、 `cross_ref` = plan file path、 self-imposed deadline 〔例 +14d〕 + 適切な priority) — deadline-horizon 系の毎 session push + 強制 disposition (= act / 明示 defer / 見送り決着) の管轄に入る
3. **即時実装** (= 小さければその場でやる — queue に入れない のが最強の queue 管理)

「plan header に green-light 済みと書く」 「project list に 🟡 で載せる」 は**どれも carrier ではない** (= push されない記録)。 これは same-turn conversion family の一員: 会議確定メール → 同 turn calendar 登録 / 依頼メール → 同 turn TODO / 印刷 → 同 turn 点呼行、 と同じ「生まれた瞬間に機械の管轄へ」。

**user 判断待ちの plan も同型に眠る**: blocked-on-user は「正しく idle」 に見えるが、 **その質問自体が carrier を持たなければ二度と user に提示されない** (= 「OK 待ち」 のまま数ヶ月、 誰も聞き直さない)。 → 「disposition を取る」 という TODO (deadline つき) を mint するか、 複数溜まっているなら 1 本の棚卸し TODO に束ねる。

**限界の宣言**: mint の瞬間の recall (= 「green-light が出た、 carrier を作らねば」 と気づくこと) は規律依存で残る。 plan file の散文から green-light を機械検出する案は棄却 (= 表現が freeform で fragile、 検出器肥大)。 構造的利得は「ambient (push ゼロ) → deadline-horizon pipeline (毎 session push + 強制 disposition)」 への移動であり、 保証ではない — 床は human-steering。

## <a id="worktree-vs-shared-checkout"></a>8. worktree (隔離) か shared checkout (ローカル) か — 並列変更の隔離 vs live 反映

独立 session / subagent を起こすとき (= §7 の spawn_task hand-off、 Agent tool の `isolation: "worktree"` オプション 等)、 その作業を **隔離 worktree** (= 同じリポの別フォルダ checkout、 履歴は共有・作業中の中身は独立) でやるか **本物の checkout (ローカル、 共有作業ツリー)** でやるかを選ぶ。 これは §1「同 file path を別 session が並列上書きする race」 の構造的な解 (= 隔離) と、 その**適用限界**の節。

### 判断ルール (default + 例外)

- **worktree (隔離) が向くのは**: 並列の別 session/agent が同じ file を変更して衝突しうる **∧** 作業が **自己完結** (= 成果が隔離コピーの中でコミットまで完結し、 live 環境に反映されなくても検証できる) とき。 worktree は安くない (= 別 checkout の setup コスト + disk。 Agent tool の説明も「並列衝突する時だけ使え」 と注意している) ので、 衝突の実害が無いなら使わない。
- **ローカル (shared checkout) にすべきは**: 成果が **本物の作業ツリーに反映されて初めて意味を持つ / 検証できる** とき。 典型 = symlink や install/setup スクリプトで **live 環境** (= 例: hook や dotfile を home 配下の決まった場所へ配線する構成) に効く変更、 live 環境がないと動作検証できない変更。 worktree だと (a) 変更が live の場所に **届かない** (= 別フォルダなので symlink 先の実体は変わらない)、 (b) 隔離コピー内で setup/install を走らせると symlink が **後で自動削除されるコピー** を指して **live 設定を壊す**。 この場合、 並列衝突の risk は worktree でなく §1 の規律 (= 着手前 `git fetch` + 自分の file だけ明示 path で commit + 他 session の未 commit 変更に触れない) で抑える。

### 迷ったら 2 問 (= worktree は AND 条件、 1 問 shortcut だと片方を見落とす)

worktree は **(a) 別 session が同じ file (path) を並列に上書きしうる (= 衝突 risk あり) ∧ (b) 成果が隔離コピー内で完結** の両方 yes で初めて正当化される (= 上 line 308 規則の operational 再述):

> (a) 別 session が同じ file (path) を並列に上書きしうるか? — no → **local 確定** (= worktree は衝突解、 衝突 risk 無しに expensive option を正当化しない) / yes → (b) へ
> (b) 成果物は **隔離コピーの中で完結** するか? — no → **local** (= worktree は live 反映できない、 隔離コピー内の変更が live に届かない) / yes → **worktree**

### 既定: 新規 unique-名 file の handoff は local

新規 unique-名 file 1 本を書いて commit/push で完成する handoff (= cold-eyes RCA / 一回限りの調査 note / 個別 slug の plan 等) は **file path が unique で他 session と衝突しえない** ゆえ (a)=no → **既定 `[local推奨]`**。 既存 file 編集や複数 file 触りを含む handoff はこの既定の射程外 (= conflict-risk を個別判断)。

⚠️ **観測された application error pattern**: (b) 自己完結だけ見て (a) 衝突 risk を未確認のまま worktree を選ぶ (= 2026-06-29、 4 軸 family の (ii) under-execution residual の correctness 軸 instance、 詳細 [`docs/convention-design-principles.md` §4.1 evidence](../docs/convention-design-principles.md#motivated-substitution-trap) + layer-3 plan)。 ⚠️ 本節 codify は **correctness 軸** (= worktree AND 条件の明示化) であって firing 軸 (= prefix 脱落自体) ではない — firing は build-nothing verdict (= 同 §4.1 evidence、 firing-surface lever 枯渇)。

### 注意

- この判断は **hand-off / 隔離オプションを選ぶその瞬間に表象されている必要**がある (= §7「この technique の射程」 と同じく、 ambient な doc は cold session では発火しない)。 ∴ spawn_task の spec を書く・`isolation` を渡す **まさにその時** に本節を想起する。
- **chip / spawn_task UI で human が worktree か local を選ぶ hand-off では、 本節 verdict を chip の *title 頭* に `[local推奨]` / `[worktree推奨]` で付ける**。 理由: `spawn_task` には isolation 引数が **無い** (= Agent / Workflow `agent()` の `isolation` 引数と非対称) ので system が推奨を pre-select できず、 worktree/local は human が UI で選ぶしかない。 → 推奨の **default 化は不可、 visibility で代替**する。 tldr (= ホバーしないと出ない tooltip) でなく **常時表示の title** が唯一の視認 lever ゆえ、 human が何も考えず押しても推奨が目に入るようにする。

---

## <a id="worker-task-sizing"></a>9. worker task の適正サイズと orientation の spec 前払い — 委譲 spec の切り方 (宛先は spec author)

§7 が hand-off の**運び方** (token / 返送 spine)、 [`output-cap-death-loop.md`](output-cap-death-loop.md) が worker の **output (生成) 側**の死機構と予防の正本。 本節はその上流 = **task をどの大きさに切るか** (sizing) と、 **input (読解) 側**の立ち上がり費用 (orientation) を spec 側で前払いする規律。 worker は cold session で ambient doc は発火しない (§7 「この technique の射程」) — ここでも操縦桿は spec だけなので、 両方とも spec author (親) の仕事。

### <a id="sizing-predicate"></a>sizing 述語: 新規概念 1 個 + 既存部品の合成まで

spec を書く前に **「この chip に新規概念がいくつあるか」 を数える** (新規概念 = worker が spec と名指し部品だけからは組み立てられず、 自力で設計・導出しなければならない要素):

- **0-1 個** (例: 部品 library 単体 / 較正 1 本 / 既存 pipeline への 1 部品差し替え / 検証済み手法の新 target への適用) → 1 chip で OK。 機械的な合成の**量**は大きくてよい (= 1 つの coherent な新規概念 + repo 内の既存部品の組み合わせで完結する大きめの chip は一発 landed した実測)。
- **2 個以上** (例: 「machinery 構築 + 較正 + 適用 + 検証」 を 1 spec に束ねる monolith) → **直列 stage に分割** (機械 stage 先・判断 stage 後、 前 stage の成果物 (file / API) を次 spec が名指す)。 = [`output-cap-death-loop.md` prevention rule 1](output-cap-death-loop.md#prevention-spec-rules) 「1 worker = 1 bounded stage」 の "bounded" を、 spec を書く手が数えられる述語にしたもの。

### <a id="orientation-prepay"></a>orientation cost は spec 側で先払いする

worker の立ち上がりの「何を読むべきか探す」 段階は、 最初の durable 成果 (= 初 commit) が出る**前に** context と時間を消費する = そこで死ぬと全損になる無防備区間。 spec author が前払いする:

- (a) **読んでよい file を名指しで cap** (≤ ~4-5 個 + 「他を開かない。 疑問が出たら results に書いて進む」)。
- (b) **copy 元を関数名まで名指す** (「pipeline の copy 元 = script X の関数 F / G / H」)。
- (c) **組み立て図を 1-2 行で書く** (「X の関数 F の部品 Y を Z の G に差し替えるだけ」)。

(a)-(c) が書けないのは**親自身が構成を把握していない signal** で、 その chip はまだ切り出せる状態にない (= 先に親が scout するか、 scout 自体を bounded chip にする)。 write 側の cap (「触ってよい file はこれだけ」 「成果物はこれだけ、 増やさない」) は並列衝突防止 (§1) と scope creep 防止を兼ねる。

### <a id="junction-fanin"></a>sizing 述語の追加軸: 合流点の入力 fan-in (2026-07-11 追記)

新規概念数と別に、 **「読ませる入力 context をいくつ融合させるか」 (= fan-in)** も数える。 複数の独立した部品 script / 結果 file を 1 つに突き合わせる **junction chip** は、 新規概念が 1 個でも「全入力を読了した直後の最初の設計 turn」 に thinking が集中し、 orientation 前払い (a)-(c) が完備でも**読了直後に silent stall し得る** (実測 1 件: 入力 5 file の junction chip が file 読了直後に ~30 分沈黙・durable 出力ゼロ)。 fan-in が 4-5 file に達する junction は、 **「最小の must-close anchor 1 本を通して commit するまで」 を第 1 stage に切り出す** (= 巨大設計 turn を構造的に不可能にする) か、 spec に「骨格 Write → 実行 → append の逐次 turn 規律 + 部分 commit permission」 を焼き込む。

### <a id="stall-rescue"></a>stalled worker の rescue: message 注入 (2026-07-11 追記)

orientation 直後の silent stall (session は running のまま・活動 timestamp 停止・durable 出力ゼロ) は、 **稼働中 session への cross-session message 送信で復活できる** (= message は相手 session に新 user turn を注入する → 死んだ生成 loop を捨てて新 turn から再開される)。 実測 1 件で有効だった rescue message の 4 要素: ① scope 縮小 (最小 must-close 単位に落とす) ② turn 規律の明示 (1 turn = 1 小 step、 骨格 → 実行 → append) ③ 部分結果 permission (「gate 1 本通過時点で commit + marker してよい」) ④ 放棄予告 (「応答なければ session を放棄して fresh chip で再発注する」)。 rescue 失敗時は **zombie session を閉じてから** fresh chip を切る (= local-tree worker は同じ file path に書くので、 後で目を覚ました zombie と fresh worker の併走は衝突源)。

### Evidence と正直な限界 (2026-07-11、 同日 2 回更新)

単一 project・単一日の staged numerical-audit chain (worker 委譲 9 chip) の実測:

- **一発 landed 8** = 部品 library / 較正 1 本 / 部品差し替え / 1 概念 + 既存部品再構成の大きめ chip (以上 4 = 弱い前払い) + **(a)-(c) 最強形 (explicit file cap + 関数名指し) を焼いた 4 chip が全部一発 landed** (= 起票時 「未着地」 だった直接実証は同日中に解消。 うち 1 chip は死んだ monolith の scope を分割した再発注)。
- **死亡 3 (いずれも初回成果物ゼロ)** = ① 6-stage monolith 6h stall (= output-cap 死 loop、 正本 = [`output-cap-death-loop.md` §Evidence](output-cap-death-loop.md#evidence) の project B) / ② bounded 寄り spec の orientation 段階死 (proximate は infra error — 「orientation が長いほど初 commit 前に死ぬ露出時間が延びる」 という robustness 解釈までが誠実な範囲) / ③ **(a)-(c) 完備でも入力 5 file の junction chip が読了直後に stall** (= 上の fan-in 軸の evidence。 この 1 件は message 注入 rescue により縮小 scope で完遂 = 全損回避、 上の rescue 節の evidence)。

⚠️ **一般化は暫定** (N = 単一 project・単一日、 landed 8 / 死亡 3 うち 1 rescue 成功)。 fan-in 述語と rescue 手順はどちらも **N=1**。 反例 (= 高 fan-in junction の一発 landed / rescue message 無効例 / cap 付き非 junction chip の同型死) や追加観察が出たら本節を更新する。

---

## <a id="delegate-model-routing"></a>10. delegate の model 選択と routing — main と別 model で走らせる

§7-8 は hand-off の運び方 (token / 返送 / worktree-vs-local)、 §9 は spec を書く時の task サイズだが、 それらと**直交**する軸として、 **delegate (Agent tool / headless CLI / spawn_task 別 session) を main session と別 model で走らせる**選択がある。 main を高価 or 最新の model に置いたまま、 機械的な sweep / rename / doc 編集 / verification-gate 回し等を安価 or 安定な model へ振ると、 (a) main の premium-model budget を温存でき、 (b) 特定 model 版に既知 bug がある場合 ([`tool-call-robustness.md`](tool-call-robustness.md) 参照) それを避けられる。 ただし **version 粒度で pin できる経路は限られる**ので、 選択の瞬間に本節を思い出す必要がある。

### 3 経路の比較 (2026-07-12 実測)

| 経路 | model 指定粒度 | pin 精度 | いつ使う |
|---|---|---|---|
| **(a) Agent per-call `model` 引数** | **alias のみ** (`sonnet`/`opus`/`haiku`/`fable`) | ✗ **alias は最新解決** = `opus` → `claude-opus-4-8[1m]` (実測)、 特定 version への固定は構造的に不能 | main から subagent を投げるだけ・model 保証不要な bg 調査 |
| **(b) custom agent 定義** (`.claude/agents/*.md` の frontmatter `model:` + `effort:`) | **full model ID** (例: `claude-opus-5[1m]`)+`effort:` | ○ pin 可、 durable | delegate の既定を version 単位で固定・毎回 CLI 引数を書きたくない (⚠️ registry は session 開始時 load = mid-session 追加した定義は次 session から) |
| **(c) headless CLI** (`claude --model <full-id> --effort <level> -p …`) | **full model ID** + effort | ○ pin 可、 起動時即時反映 | scheduled / cron / launchd から model を明示的に pin して走らせる・(b) との組合せ可 |

- ⚠️ **`spawn_task` (chip → 別 session) には model 引数が無い** (= chip はアプリ既定 model で開く)。 起票側から見て model は成り行きになる。 chip を通した独立 session に version pin したい needs が生じたら、 現状は upstream 依存 (= harness 側で model 引数を追加してもらう) しかない。
- 既知 bug のある最新 model を alias が掴む事故は (a) では構造的に避けられない (= alias は最新解決)。 bug 回避目的の delegate は必ず (b) / (c) で pin する。

### 使い分け litmus

- **model 保証 + 非 block + fresh context で足りる** → (b) の pinned custom agent、 または (c) の headless CLI で pin。
- **真の並列 UI session が要る** (= 人が途中で対話する / user が独立に steer する) → `spawn_task` (§7)。 model 保証は諦める (= アプリ既定で開く) — その代わり真の並列と live steer が得られる。

### 注意

- **(a) の alias 解決 gotcha が最大の見落とし**: 「`opus` を指定したから 4.7 か 4.8 のどちらか安定な方が来る」 は幻想で、 alias は常に**最新**を返す。 特定 version で走らせたいなら (b) / (c)。
- **(b) の frontmatter `model:` には alias でなく full ID** (= 例 `claude-opus-5[1m]`、 `[1m]` suffix 込み) を書く。 alias を書くと (a) と同じ「最新解決」 の穴が空く。 `effort:` も frontmatter で pin する (`low`/`medium`/`high`/`xhigh`/`max`)。
- **(b) の registry load timing**: `.claude/agents/foo.md` を mid-session に追加しても当 session からは呼べず (`Agent type 'foo' not found`)、 次 session から効く。 起票時に「あるはず」 と assume して呼ぶ前に、 定義が session 開始前に配置済みかを確認する。
- **(c) の headless run は auth を消費する**アカウントで CLI が login 済みでなければならない (= `~/.claude.json` の login と launchd job の`claude` 実体が同 account を指す)。 cron / launchd に組込むときの auth 経路の正本は [`multi-machine-state.md`](multi-machine-state.md#account-host-failover)。

---

## <a id="remote-handoff-constraints"></a>11. リモート session への hand-off — 物理不在で完了できない step の全分岐着地設計

user がそのマシンの前に居ない session (= Remote Control 経由でスマホ / 別端末から操縦する session) に
作業指示を渡すときは、 **「そのマシンの前でしか完了できない step」 を事前に洗い出し、 どの分岐でも
安全に着地する指示文にする**。 リモートでも permission dialog は操縦側 UI (claude.ai/code) に出て
承認できるし Bash / tool 実行は全部通る — 詰まるのは以下の類型だけ:

| リモートで完了できない step | なぜ |
|---|---|
| ブラウザ対話 OAuth (`claude auth login` 等の localhost-callback 型) | 認可はそのマシンのブラウザで完了する必要がある (callback = localhost)。 操縦者は承認画面に到達できない |
| chip (spawn_task) の click 起票 | chip の click 面は操縦側 client で制御できない (2026-08-29 user 観測) |
| 物理操作 (印刷物の回収・USB・電源・紙書類) | 自明だが checklist に 1 つ混ざっているだけで全体が中断する |

設計原則 — **全分岐が「進む or 安全に戻して待つ」 に着地する**:

- **成否が分かる probe を checklist の先頭に置く**: 現地でしか直せない前提 (認証・デバイス) は
  最初の 1 コマンドで判定し、 途中で発覚して半端状態になるのを防ぐ。
- **fallback 分岐を指示文に焼き込む**: 「probe 失敗なら <rollback コマンド> で元の構成に戻し
  (関連 state は触らない)、 『現地で <対処> が必要』 と報告して終了」。 中途半端な状態
  (半分だけ移行した設定・認証の切れた pin) で session を終わらせることを設計で禁じる。
- **委譲を禁じる**: 「spawn_task / 別 session への委譲はせず、 全 step をこの session 内で直接実行」
  と明記する (= chip がリモートで押せない上、 結果の受領面も物理不在)。

実例 (genericized): 無人 launchd routine の消費 account を別 config dir に pin する移行を対象マシンへ
リモートから指示。 headless 生成の 401 (= 現地 OAuth でしか直らない) を step 1 の probe に置き、
401 なら「pin 解除 rollback + 台帳は触らず + 現地対処を報告して終了」 の分岐を指示文に焼いた
(2026-08-29、 実施は成功分岐で完遂)。

---

## 関連

- リモート操縦 session への hand-off (物理不在で完了できない step の分岐設計): §11 (RC 機構自体は [`remote-control-server.md`](remote-control-server.md))
- worker task の切り方 (sizing 述語 + orientation 前払い) = spec author 宛の規律: §9 (output 側の死機構は [`output-cap-death-loop.md`](output-cap-death-loop.md))
- delegate を main と別 model で走らせる選択 (alias 不能 / custom agent / headless CLI): §10 (bug 回避のみを目的にした model 切替は [`tool-call-robustness.md`](tool-call-robustness.md))
- worktree (隔離) か ローカルか = 並列変更の隔離 vs live 反映のトレードオフ: §8
- collaborator (= 他 user) との Git race / branching: [`shared-repo.md`](shared-repo.md)
- 4 軸 sweep + sweep goal alignment (= 「✓ pass」 closure を禁じる規律): [`CONVENTIONS.md` §3](../CONVENTIONS.md)
- review / audit の goal は error 発見 規律: 同上 §3 「sweep / review / audit の goal alignment」
- prev session の `[x]` を信頼するか自分で実装するかの境界判断: 個人層 (`<your>-prefs/`) の work-discipline に machine-local な reflex-trap として記録するのが筋 (= machine-dependent な作業 mode 切替)
