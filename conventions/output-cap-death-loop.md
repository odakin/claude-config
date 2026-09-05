<!-- doc-meta
when: worker session (spawn_task / headless claude -p / Agent subagent / 別ベンダー CLI 〔Codex 等〕) に長い導出・生成 task を渡す spec を書くとき・spawn した worker が「isRunning なのに成果ゼロ」 のとき・受け手の context 窓が小さい (自動圧縮が早い) と分かっているとき
category: harness-core
summary: 1 応答の出力上限 (Claude Code 既定 64,000 output token、 thinking 込み) を超える巨大 turn を worker が試みると、 API error → 同じ turn を retry → また超過、 の決定的 loop で session が silent 死する (= output-cap 死 loop)。 診断 signature = 実作業ゼロ + 空 thinking block が ~10-15 分間隔で規則的に並ぶ (rate-limit backoff と誤診しやすい)。 復旧 = 粘らず捨てる + **spec を分割してから** 再spawn (同 spec の再spawn は同じ死に方をする、 実測 2 連死)。 予防の宛先は worker でなく **spec author (親)**: 1 worker = 1 bounded stage / 開放的判断問題には「未解決と書いて閉じてよい」 permission / turn 分割規律 (1 応答で完結させない・小節ごと commit) / 1 Write ≤~150 行・定型は shell 複製 / 部分結果 = 成功 mode。 2026-07-10/11 に独立 2 project で計 3 worker 同型死 + bounded な sibling 2 worker は完走の実測から。 姉妹機構 = **context 圧縮による途中経過の消失** (#context-compaction-loss、 別ベンダー worker で context 窓が ~250K 級の場合): 予防は同じ = step ごとに file に書いて commit + 読ませる文書を最小化。
-->
# Output-cap 死 loop — worker が 1 応答の出力上限で silent 死し続ける

> 適用対象: **無人で回る Claude session 全部** — spawn_task worker / headless `claude -p` routine / Agent subagent。 attended session でも起きるが、 その場合は error が user に見えて即座に対処される。 無人 worker では **誰も error を見ない** ので、 何時間でも死に続ける。

---

## <a id="mechanism"></a>機構

1 応答 (assistant turn) が生成できる出力 token には上限がある (Claude Code 既定 **64,000**、 error 文言 = "Claude's response exceeded the 64000 output token maximum"。 `CLAUDE_CODE_MAX_OUTPUT_TOKENS` で変更可)。 重要な観測 2 点:

1. **thinking token も同じ枠を消費する**。 可視出力ゼロのまま上限に達しうる = 開放的な難問 (「この量は 0 か正か決めよ」 型の判断問題、 開放的な導出) で extended thinking が単独で枠を食い潰す。
2. 上限超過した turn は **何も durable に残らない** (tool call 未発行・text 未出力)。 client は同じ turn を retry する → 同じ context から同じ巨大 generation → また超過。 **決定的 loop で、 自己回復しない**。

巨大 turn を誘発する task の形 (= 実測で死んだ形):

- 開放的な判断・導出問題を「決めろ / 導出せよ」 とだけ渡す (thinking 爆発)
- 「完成 note を納品せよ」 の monolithic deliverable framing (一撃 whole-artifact 生成の引力)
- 大きな定型 (数百行の preamble 等) を型どおり打ち直させる (可視出力での枠浪費)
- all-or-nothing の成功条件 (部分 commit の弁が無いと turn を切る動機が生まれない)

## <a id="diagnosis"></a>診断 signature (親側)

worker が `isRunning` なのに commit / marker / 成果 file がゼロで、 transcript (`~/.claude/projects/<dir>/<uuid>.jsonl`) の末尾に:

- **中身が空の thinking block が ~10-15 分間隔で規則的に並ぶ** (= 1 個 = 1 回の doomed generation 試行。 上限超過 or client timeout → retry の周期)
- text も tool call も出ない。 **割り込みで「何やってるの?」 と聞いても、 その返答 turn 自体が同じ loop に入る** (= 数秒で返るはずの応答が返らない = 決定打)

⚠️ **誤診 trap (実測)**: この signature は rate-limit backoff・malformed-tool-call bug ([`tool-call-robustness.md`](tool-call-robustness.md)) と紛らわしい。 鑑別: 同 account の並行 session が普通に応答しているなら account rate limit ではない / malformed bug は「壊れた tool call」 が transcript に残るが、 本 loop は**何も残らない**。 UI 側の 64k error 文言は起動した端末にしか出ないことがあり、 transcript からは空 thinking の周期だけが見える。

## <a id="recovery"></a>復旧 playbook

**粘らない** ([`tool-call-robustness.md`](tool-call-robustness.md) と同じ精神 = root に最も近い一手を先に):

1. worker session を捨てる (成果は commit 済みの分だけ。 だからこそ予防規律の「小節ごと commit」 が保険になる)
2. **spec を直してから** 再spawn する。 ⚠️ **同じ spec の再spawn は同じ死に方をする** (実測: 同一 monolithic spec で 2 連死 = loop は spec の形に対して決定的)。 旧 spec には supersession banner を付けて分割版へ redirect する (worker が古い spec を読む race の防止)
3. `CLAUDE_CODE_MAX_OUTPUT_TOKENS` を上げるのは対症 (thinking 主導の爆発は任意の枠を食い潰しうる)。 本筋は分割

## <a id="prevention-spec-rules"></a>予防 = spec 設計規律 (宛先は spec author)

worker は cold session で、 ambient な規約 doc は発火しない — **spec が唯一の操縦桿**。 よって予防は worker の心掛けでなく、 **spec author (親) が spec に焼き込む**:

1. **1 worker = 1 bounded stage**。 機械的に閉じる仕事 (転記・検算・積分・table 生成) 単位に分割し、 逐次依存は「A 完了後に B を spawn」 の直列 stage にする (mega-spec 1 本にしない)。 **機械 stage を先・判断 stage を最後** に置き、 判断 stage は機械 stage の成果物を食う
2. **開放的な判断問題には explicit permission を書く**: 「決められなければ『何が決まれば決まるか』 を書いて未解決で閉じてよい」。 これが無いと worker は決まるまで考え続けて thinking で死ぬ
3. **turn 分割規律を spec に明記**: 1 応答で完結させようとするな (最低 4-6 turn) / 導出は小節ごとに file append → build/test → commit / 詰まったら部分結果を書いて turn を切る — ledger 型の deliverable なら「小節ごと commit」 は **pre-commit gate で機械化**できる ([`../scripts/ledger-commit-cadence-gate.py`](../scripts/ledger-commit-cadence-gate.py)、 散文規律が 41 item / 2 commit で空振りした実測から。 [`physics-verification-cycle.md#campaign-tooling`](physics-verification-cycle.md#campaign-tooling) E)
4. **1 回の Write は ≤ ~150 行**。 大きな定型 (preamble・boilerplate) は生成させず **shell で複製** (`sed` / `cp`) — 出力 token は有限資源として扱う
5. **部分結果を成功 mode にする**: 「未完でも部分結果を commit + marker (`--status partial`) で閉じてよい」 を spec の成功条件に含める (all-or-nothing framing が巨大 turn を誘発する)
6. deliverable に **サイズ目標** (≤ N ページ / 行) を書く

### 正直な限界

spec 規律は wording レベルの誘導であって保証ではない (worker が指示を無視して長考する可能性は残る)。 backstop = 親側の監視 (spawn 後に transcript の成長と commit の有無を確認、 空 thinking 周期を見たら即・死と判定してよい — 回復しない) + human-steering。

## <a id="evidence"></a>Evidence (2026-07-10/11)

同日に独立 2 project (いずれも長い物理導出 note の worker 委譲) で計 3 worker が同型死、 分割で解消:

- project A: monolithic spec の worker が ~50 分 silent 死 (空 thinking ~14 分周期 ×4) → **同 spec で再spawn した worker も同型死** (= spec 決定性の実測) → bounded stage に分割後の worker は健全完走
- project B: 開放的な図式導出の worker が **6 時間 stall・空 thinking ×26・成果ゼロ** → 親 session が独立に同じ治療 (physics-free の bounded library stage を先頭に置く A0-A4 直列分割) に到達。 同環境の bounded/mechanical な sibling worker 2 体 (ledger 計算・転記+検算) は完走 = **生死を分けたのは task の形**

## <a id="context-compaction-loss"></a>姉妹機構: context 自動圧縮で途中の導出が消える (別ベンダー / 小さい context 窓の worker、 2026-09)

**機構**: output-cap 死は「1 応答が大きすぎて API が拒む」 が、 こちらは「**会話全体が受け手の context 窓を超えて自動圧縮 (compaction) され、 file に書いていない途中の導出・判断が要約に潰れる**」。 session は死なず走り続けるので silent。 影響が大きいのは context 窓が Claude Code より小さい受け手 — 実測例: Codex CLI + GPT-5.6 Sol は 2026-07 以降 effective window ≈ 258K (カタログ 272K の 95%)、 自動圧縮は ≈ 215-243K で観測 (web 二次情報: [OpenAI community](https://community.openai.com/t/why-does-codex-report-a-258-400-token-context-window-for-gpt-5-6-sol/1394346) / [openai/codex#32806](https://github.com/openai/codex/issues/32806) / [解説](https://codex.danielvaughan.com/2026/07/20/context-window-gap-codex-cli-gpt56-advertised-vs-effective-budget-compaction-strategy/)、 1M へ override する手順の存在も同記事群。 数値は client version で動く = 一次資料優先の規律は [`../codex/PARITY.md#context-capacity-diagnosis`](../codex/PARITY.md#context-capacity-diagnosis))。 owner の観測 (2026-09-05): 「Codex は 0.25M くらいで会話圧縮になる」。

**予防 (spec author 向け、 上の 1-6 と同じ精神)**:

1. **読ませる文書を最小化する** — allow / deny list を spec に書く (対象論文 1 本 + spec + repo の CLAUDE/DESIGN 程度)。 起票側の巨大 instruction file は別ベンダーには読ませない (入口は `AGENTS.md`)。 隔離 (= 独立性) と context 節約は同じ手段で両立する
2. **step ごとに file へ書いて commit させる** — 「導出は step が 1 つ閉じるごとに notes に追記して git commit (圧縮で途中経過が消えても file に残る)」 を spec に 1 行焼く。 output-cap 予防 3 と同文で足りる
3. **単一の逐次仕事には推論並列 mode を使わない** (例: Codex の ultra は subagent 分割 = context を増やし独立性も薄める、 深い 1 本の証明は xhigh)
4. 崩れたら **粘らず閉じる** — board に `abandoned`、 部分結果の commit があればそれを受領。 cross-vendor pass は bonus (第二の目は同ベンダー別 session が担う) なので失敗しても台帳は汚れない
5. **圧縮閾値の設定は vendor の一次資料で確認してから** (= `codex/PARITY.md` の規律。 未検証の設定値を規約に書かない)

**Evidence**: 2026-09-05 時点で実測 0 件 (owner の経験則から予防先行)。 初回 instance = 外部論文の検証読み campaign で Codex に 1 本の証明を cross-vendor red-team させる spec (private repo)。 結果が出たら本節に n を書く。

## 関連

- spawn handoff の spec template・token-handshake・返送 spine: [`multi-session-coordination.md` §7](multi-session-coordination.md#spawn-handoff-token-return) (spec を書く時に本 doc の予防規律を焼き込む)
- task をどの大きさに切るか (sizing 述語 = 新規概念を数える) + input 側 = orientation cost の spec 前払い: [`multi-session-coordination.md` §9](multi-session-coordination.md#worker-task-sizing) (= 本 doc の prevention rule 1 の上流補完)
- 別 root の session 死 (malformed tool call、 model 切替が本命): [`tool-call-robustness.md`](tool-call-robustness.md) — 「粘らず root に近い一手」 の精神は共通、 機構と対処は別
- 並列 worker が共有 tmpdir を埋めて Bash 出力が消える別症状: [`multi-session-coordination.md` §5](multi-session-coordination.md#shared-tmpdir-enospc)
- 別ベンダー worker の context 容量の測り方 (advertised / client 窓 / 圧縮 trigger を混ぜない): [`../codex/PARITY.md#context-capacity-diagnosis`](../codex/PARITY.md#context-capacity-diagnosis) + [`../docs/convention-design-principles.md#context-capacity-evidence-layers`](../docs/convention-design-principles.md#context-capacity-evidence-layers)
