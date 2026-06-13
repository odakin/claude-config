# Debugging discipline

Bug fix 提案を 「root だ」 と確信する前に通すべき audit と、 fix 採択後の drift 防止規律。 Claude が fix 提案を生成する際の reflex として universal applicable。

LorentzArena Bug 14 完全治療 (2026-05-06) の spiral で複数の fail-recover round を経験した経緯から、 odakin-prefs/work-discipline.md にあった odakin-specific 規律のうち universal な核を抽出 promote。

---

## 1. Fix 提案の 3 verification (= L4-L5 + numeric trace + code coverage)

**ルール**: fix 提案を 「root だ」 と確信する前に **3 verification** を全て通す。 全 pass まで commit / approval / 「root 確定」 NG。

| # | Verification | 内容 |
|---|---|---|
| **V1 (semantic + numeric)** | Semantic / scenario trace | L4 (= 概念モデル / 設計柱と矛盾なし) + L5 (= 数値解析的安定性 / 不変条件) で root を identify、 全 case scenario で実数値 / 状態 trace、 corner case 破綻 (= over/under count、 race、 boundary 不整合) が無いか |
| **V2 (code coverage)** | 「既存が handle 済」 主張 verify | pattern match で済まさず **actual code を読んで scenario trace で coverage 確認**、 grep + 関数 read + walk-through で想定 path = actual path を confirm |
| **V3 (algorithm enumeration、 L5 fix のみ)** | 代替 algorithm 網羅 | L5 fix で「substep / cap / clamp」 系 workaround を提案したら、 **代替 algorithm 全列挙** (= explicit / implicit / analytic / symplectic / RK4 / substep) して 1st choice の正当性 confirm。 線形 ODE は通常 closed-form で解ける、 substep は workaround で root ではない (= 詳細: [`scientific-computing.md §2`](scientific-computing.md)) |

「conceptually clean」 「既存 mechanism handle するはず」 はいずれも **未検証の仮説**、 user / 自己が「ad hoc 感」 を覚えたら 3 verification を反射的に走らせる trigger。

### 自己 audit signal (= 絆創膏 sign 早期検知)

提案 fix が下記のどれかの形をしていたら絆創膏 sign:

- 「**...if X > threshold then truncate / clamp**」 (= cap 系絆創膏)
- 「**...add Y listener to catch X case**」 (= listener 系絆創膏)
- 「**...reset state on Y event**」 (= reset 系絆創膏)
- 「**...switch implementation A to B to side-step the problem**」 (= 別実装で逃げる)
- 「**Y で X case を fall back**」 (= mechanism overload signal、 別 mechanism Z の natural class fit を inventory walk で identify)

「意味論レベルで何が ill-defined か」 「数学的に何が不安定か / どの不変条件が破られているか」 を答えられないなら L4-L5 まで掘り切れていない。 V1 で refinement 試行が他 case を破壊するなら closed-form root にならない signal、 別 approach (= 別 mechanism / 別 type 識別) に移る。

### How to apply

1. fix 提案直後に **scenario list (5-10 個)** + 各 case の数値 / 状態 trace で V1。 L5 fix なら **代替 algorithm 全列挙** (= V3) で 1st choice の正当性 confirm
2. 「既存 X が Y を handle」 主張を含むなら V2 で `grep -n` + 該当関数 read + scenario walk-through、 想定 path が actual code path と一致 confirm
3. V1 + V2 (+ V3 if applicable) 全 pass まで commit / approval / 「root 確定」 NG

### Cross-level meta-principle

- **データ層 structural separation** (= 異なる事実は異なる storage、 「同じ概念を複数 ref に置かない」 系 rule) は state design の話、 V2 とは別軸
- **Mechanism 層 structural separation** (= 「Y で X case を fall back する」 → Y 過負荷 signal、 別 mechanism Z の natural class fit を inventory walk) は responsibility design の話、 V1 self-audit signal の一部
- **Assumption 層 verification** (= V2) は coverage 主張の verify 軸、 「pattern match での mechanism class 推論」 と「actual code path 確認」 は別作業

---

## 2. Audit verdict 「正当化済」 は user 質問で再評価

**ルール**: audit / 4 軸 sweep / 設計 review で 「正当化済」 「scope 外」 「fully closed」 と verdict を出した後でも、 user の epistemic skepticism signal (= 「絆創膏に見える」 「原理的におかしくない?」 「もう一度深く」 「ad hoc では?」 「本当?」) を受けたら、 **verdict を reset して 3 verification を再 trigger**。

「正当化済」 verdict は user 質問で **無効化**、 deeper layer の存在可能性を再 audit。

### Why

「conceptually clean」 や 「pattern match で類似」 で audit が通過しても、 user の実装 / 物理 / 設計感覚は別軸の signal を捉えている可能性が高い。 user pushback を反射的に rationalize したり 「scope 外」 と再判定したりせず、 **「verdict 無効化 → 3 verification 再 trigger」 の reflex** を作る。

複雑な debug session では 1-shot で root に到達するのは例外、 multi-round spiral が norm。 各 round で 「これは root だ」 verdict を出していても user pushback で更に deeper layer 発見することが多い。 reflex 化された 3 verification 再 trigger が必須。

### How to apply

- audit verdict を出した直後の user comment は反射的に skepticism signal として扱う
- 「絆創膏に見える」 「原理的におかしい」 「もう一度深く」 等を受けたら、 「では V1 V2 V3 全部回し直そう」 と即応する
- **rationalize しない** (= 「これは scope 外」 「これは clean」 等で push back を defuse しない)
- 「もう変わらない?」 と user に尋ねられても 1 round 余計に push して back-checked V1 V2 V3 で再 confirm してから返事

---

## 3. Multi-commit refactor で 4 軸 sweep + docstring drift

**ルール**: 連続 commit 後の最終 push 前に 4 軸 sweep (= [`CONVENTIONS.md §3`](../CONVENTIONS.md)) を回し、 **docstring と実装の drift** を必ず捕まえる。 commit 単位では一貫していても session 横断で docstring が stale 化することがある。

4 軸: 整合性 / 無矛盾性 / 効率性 / 安全性。

### 特に注意するべき drift pattern

- **constant 名の言及** が複数ファイルに散在、 1 commit で改名 / 削除した後の他ファイルの言及が stale
- **数値 (= performance characteristics、 build value、 test count 等)** が SESSION / docs / commit message で drift
- **section 名 / numbering** の参照先が rename / renumber で broken
- **「現状こうなっている」 系の説明** が refactor で stale 化、 「✓ 現行」 / 「✗ 撤廃済」 marker で設計史保持しつつ更新

### How to apply

- multi-commit session の最終 push 前に必ず:
  1. `git log --oneline <last-record>..HEAD` で commit 列挙
  2. `git diff <last-record>..HEAD` 全体に対し PII / 私的情報 / private repo 名の grep
  3. 触ったファイルの cross-reference 整合性 grep (= 数値定数 / section 名 / file path)
  4. typecheck + tests 実行
  5. drift 発見時は即修正 commit、 sweep を skip して push しない

詳細: [`CONVENTIONS.md §3`](../CONVENTIONS.md)、 [`docs/sensitive-repo-patterns.ja.md §パターン 5-3`](../docs/sensitive-repo-patterns.ja.md)。

---

## 4. Rule violation 1 件発見 → sibling audit 即時実施

**ルール**: structural rule (= state 単一化、 4 層モデル、 命名規約 等) で **1 件 violation を発見** したら、 同 session 内に同 rule の他 sibling violations を即時 sweep。

「単独事例」 と扱わない、 systemic pattern の signal として全件捜索。

### Why

structural rule の違反は同 codebase / 同型コード設計で **再生産される**。 1 件発見した時点で他にも存在する確率が高い。 「気付いた 1 件だけ直して終了」 すると残存 sibling が future contributor を mislead する。

具体例:
- state 単一化 (= 「同じ概念を複数 ref に置かない」) の violation 1 件発見 → 同 codebase で類似 dual-state pattern 兄弟 sweep
- 4 層モデル layer 違反 1 件発見 → 同 repo 内全 cross-layer reference grep で他 violations も発見、 同 commit で全件修正
- **2026-05-10 claude-config self-audit**: `hooks/memory-guard*.sh` の deny message に `odakin-prefs/` literal 1 件発見 → 同 session で hooks → scripts → setup.sh と段階的に sweep を broaden、 結果 sibling 20+ 件 (= `git-state-nudge.sh` の runtime emit、 `public-precommit-runner.sh` 等 3 scripts の hardcode、 `setup.sh:863` の `SECRETS_REPOS` hardcode + comment 言及) を 6 commits + 個人層 1 commit で全件 closure。 narrow scope (= memory-guard 2 件) で stop していたら sibling は次 session 以降に発見 / 残存リスク。 broadening pattern: surface ごと (= hooks → scripts → setup.sh) に「同 class があるか」 を順次問う。 関連 universal 原則: [`docs/convention-design-principles.md §12`](../docs/convention-design-principles.md) (= 監視 list の scope marker = 暗黙 scope blind spot を防ぐ doc 規律)

### How to apply

- rule violation 1 件発見時点で、 同 session 内に sibling sweep を schedule
- sweep 手段: `grep` で同型 pattern を全 codebase 検索、 violation list 作成、 全 fix を同一 PR / commit に集約
- sibling sweep を defer すると同 violation が再発、 session を跨いで残存

### Fix 時 sibling sweep (= 2026-05-25 RCA 追加: violation 発見時だけでなく fix 時にも sweep 義務)

**ルール拡張**: 上記は「violation 発見 → sibling 即 sweep」 だが、 **fix 自体を narrow scope で済ませて sibling を残置する failure mode** が独立に存在。 fix 適用時にも「同 fix が他 sibling に適用できるか」 を sweep する。

**Why**: 「flagged された 1 件を fix」 だけで止まると、 同 trait family の sibling default / sibling pattern が **未 flagged のまま残存** し、 別 unit system / 別 context で symptom が顕在化する遅延発見 cycle になる。

**実例 (2026-04-20 → 2026-05-25 の 13 ヶ月遅延発見)**: `scientific-computing.md §1` の `TauSqMax` scale-blind default fix を 2026-04-20 に commit。 同 fix で `TauSqMax` を scale-adaptive 化したが、 **同 file 同 function の `MuRange` default (= `{Min[xs]-10, Max[xs]+10}` = 同形式 scale-blind)** を sweep しなかった。 13 ヶ月後 (2026-05-25) 別 unit system (= dimensionless S₈ tension) で S₈ scale で margin 10 が data spread の 110× 過大 → posterior peak under-resolved → SE が 30-50% inflated として symptom 顕在化。 fix-time に同 file の sibling default を grep していれば同 commit で防げた。

**How to apply (= 通常 fix workflow に追加)**:

- fix を decide した直後 (= patch を書き始める前)、 fix 対象の **同 file / 同 function / 同 関数族** を grep で sweep:
  - 同 anti-pattern keyword (= 上 例なら literal `- 10` や `1000` の scale-blind constant) で grep
  - 同型 default 構造 (= `default = constant`) で grep
  - 同 function family の他 option で同 issue 候補列挙
- 発見した sibling は **同 commit で同時 fix** (= 「別 commit で defer」 は次 session で reflex skip され 13 ヶ月 silently 残存する)
- defer する場合は **explicit marker** (= 「TODO: same defect at line X, defer to next commit because Y」) を fix file 内に書き、 session 内 follow-up を guarantee

**Anti-pattern**:
- ✗ 「flagged された 1 件だけ fix、 他は別 task で」 (= defer reflex で残置)
- ✗ fix 適用後に「同 file の他 instance がないか」 を grep skip (= narrow scope closure)
- ✗ commit message に「foo を fix」 と書くが「他 sibling は不明」 と sweep 状態を明示しない

**meta-meta**: 本 §4 拡張 = §4 主旨 (= violation 発見 → sibling sweep) を **fix 時 timeline にも適用**。 violation 発見 → sibling A 認識 → A を fix する commit を書く際、 sibling B/C/D を再 sweep。 「発見 sweep」 と「fix sweep」 は別タイミングで両方必要。 narrow fix の自己強化 cycle (= 1 件 fix で「片付いた感」 が出て次の sweep を skip する) を防ぐ。

---

## 5. Plan ファイル lifecycle = multi-doc atomic operation

**ルール**: plan file (= `plans/YYYY-MM-DD-*.md` 等の session を跨いだ将来の自分への message を encode する artifact) を新規作成 / 大幅 supersede する commit には、 同 commit 内で以下を全て含める:

1. plan file 本体 (= 新規 / 改訂)
2. **SESSION.md (or 等価な session pointer file) の Active plans 等の発見可能な section に link 追加**
3. **supersede 関係があれば双方向 marker**:
   - 新 plan §1 / 冒頭付近に 「**Supersedes:** [old plan link]」
   - 旧 plan の該当 section 冒頭に 「**⚠️ Superseded by:** [new plan link]」
   - 旧 plan の 「実装済」 narrative を 「supersede 済 (= 撤回予定)」 narrative に修正

「plan file 単独」 を 1 commit にしない。 plan file は **discoverability mechanism (= SESSION.md mention) と双方向 supersession marker** と組で初めて 1 単位、 単独 commit は半製品。

### Why

plan file は session を跨いだ将来の自分 (= 別 Claude session) への message を encode する artifact。 物理的に commit + push されていても、 **次 session が SESSION.md / 等価 pointer から発見できなければ存在しないのと同じ**。

事故例 (= LorentzArena 2026-05-06): plan A §6.5 (b) を supersede する独立 plan B を新規作成、 plan B 単独で commit + push、 SESSION.md は plan A への link のみ、 plan A 本文も 「✅ implement 済」 narrative のまま → 次 session が SESSION.md → plan A の chain で navigate して plan B に到達経路無し、 plan A の narrative を信用して 「もう完了」 と誤認、 plan B 不可視化。

根本原因: plan lifecycle の atomicity 違反。 「ファイル commit したから完了」 と effort-reduce、 plan が機能する discoverability layer (= SESSION.md mention + supersession markers) と同期されていない。

### How to apply

- plan 新規 / supersede commit の self checklist:
  1. ✅ plan file 本体
  2. ✅ SESSION.md / 等価 pointer file の Active plans section に link 追加
  3. ✅ supersede 関係あれば forward marker (= 新 → 旧) + backward marker (= 旧 → 新) 双方
  4. ✅ 旧 plan の narrative を supersession を反映する形に修正 (= 「実装済」 → 「supersede 済」 等)

- **Stop signal = sweep trigger reframe**: user の 「終わろう」 「もう完了でいい?」 は **effort 削減指示ではない**、 4 軸 sweep + multi-doc atomicity check 開始の signal と read する。 commit + push だけで終了せず、 lifecycle invariants を回す。

- **機械的 enforcement (= 将来の hook)**: PostToolUse(Bash, command matches `git commit`) で `git diff HEAD~ --name-only` が `plans/*.md` 新規追加を含む場合に同 commit 内に SESSION.md (or 等価 pointer) 変更が無ければ warning。 false positive (= plan 修正のみの commit 等) は許容 (= 軽量 nudge、 hard block しない)。

### §1 (3 verification) との関係

Plan creation / supersede commit にも 3 verification を application:
- **V1 (= scenario trace)**: 「次 session が SESSION.md から plan を発見できるか」 をシミュレート (= 自分が cold start で SESSION.md だけ読んで plan に到達できるか)
- **V2 (= code coverage)**: 「SESSION.md / 等価 pointer に link あるか + 旧 plan の narrative 整合性」 を mechanical 検査
- **V3 (= alternative algorithm enumeration)**: 「supersession ではなく旧 plan を update する選択肢ではないか」 を考慮 (= 別 file に出す valid reason は時間軸 / 視点軸の独立性、 単純 patch なら旧 plan 内 update が筋)

---

## 6. Introspection facility (= dry-run / --force / --print-only / -n / --noop 等) を grep / code review より優先

**ルール**: 容疑者として name 上がった script / tool / CLI が **dry-run-like introspection facility** を持つなら、 grep / code review / docstring 読み を skip して**先に実行** (= `--dry-run`、 `--force --dry-run`、 `-n`、 `--noop`、 `--print-only`、 `--what-if`、 framework によって `--plan` 等)。 実行ログが「**この script は何を touch するか**」 の ground truth、 code review は「**何を touch するつもりか**」 の intention でしかない。

### Why

code review は **静的、 author の意図と実装の一致を仮定**。 author の意図と実装が乖離する場合 (= bug、 stale docstring、 implicit branch、 dynamic dispatch、 hidden side-effect via library) を grep + 関数 read だけで全部捕まえるのは困難。

introspection facility は **動的、 actual runtime behavior の simulation**。 「もし実行したら」 を実行せずに観測する verification path。 code review が「**probably this**」 を返すのに対し、 introspection は「**actually this**」 を返す。

特に 「相関は強いが因果は code 上見えない」 ケースで決定的: code review 「無罪っぽい」 + correlation 「有罪っぽい」 で hung jury 状態のとき、 dry-run で actual touch list を見れば瞬時に解決。

### Sample

```bash
# Script に dry-run 系 flag があるか確認 (--help / docstring grep)
script.py --help | grep -iE 'dry|noop|print[- ]?only|what[- ]?if|plan'

# あれば先に実行、 actual touch list を観測
script.py --dry-run                    # 通常モード
script.py --dry-run --force            # skip 系 (HORIZON / unconfirmed / past 等) を bypass
script.py --dry-run --period A:B       # 範囲を絞って局所検証

# 出力の "WOULD shift / WOULD delete / would touch" 行を観測、 期待外の対象が含まれるか
```

terraform `plan`、 ansible `--check`、 git `--dry-run`、 rsync `-n`、 make `-n`、 kubectl `--dry-run=client`、 dpkg `--dry-run`、 brew 系 `--dry-run` 等、 多くの CLI が標準装備。 自作 script で「何を touch するか不安」 と user が言う pattern は dry-run flag 標準装備の signal。

### How to apply

1. 容疑者 script / tool / CLI が judgement の中心になった時点で、 まず `--help` か docstring の引数列挙で introspection flag の存在確認
2. あれば即実行、 ground truth として code review より優先採用
3. なければ code review に fallback、 ただし「dry-run flag が無い script は author が dry-run の必要性を見落とした signal」 = 第二容疑度 up
4. introspection flag を追加 / patch する PR が cheap なら、 verify と同時に PR 化

### 反例 (= 検証で済まない場面)

introspection が **存在しない / 信頼できない** ケース: 
- C library / system call 系 (= dry-run なし、 strace / dtruss 等で trace)
- API call の冪等性が不明 (= dry-run flag が server side まで届かない、 sandbox 環境推奨)
- side-effect が non-deterministic / 環境依存 (= dry-run で trigger しない bug もある)

これらは V1 (= scenario trace) + V2 (= code coverage) の伝統的 path に戻る。 但し introspection を **試す前に grep に戻る** のは効率損失。

### 関連事故 / 検証例

- **2026-05-12 calendar event 2 限消失** (個人 layer 内 private repo の SESSION.md に詳細記録): shift-worship-period.py が 2 限相関で容疑かかったが、 `--dry-run --force` で touch 対象が 4 件のみ (= religious_week の特定日付の event 4 件) と判明、 4-5 月 events は range 外 → 冤罪確定。 code review 30 分 vs dry-run 30 秒、 後者が決定的。 真犯人候補は Apple Calendar sync。

---

## 7. Claude 自身を容疑者から外す手法: `~/.claude/projects/*/*.jsonl` の tool_use grep

**ルール**: 「過去の Claude session が悪さしたのでは?」 という容疑が浮上したら、 `~/.claude/projects/<project-hash>/*.jsonl` を grep して **過去の actual tool_use 履歴**を確認。 user の記憶 / 想像でなく、 実際の tool 呼び出し ledger が ground truth。

### Why

Claude Code は full session transcript を `~/.claude/projects/<project-hash>/<session-uuid>.jsonl` に local 保存している (1 行 1 record の JSONL)。 各 tool 呼び出しは `type: tool_use` record として残る。 「過去にこの tool を呼んだか」 は ledger を grep すれば deterministic に判定可能。

user / Claude の memory は信頼性低い (= autocompact、 session 跨ぎ、 関連無しと判断して捨てる、 等)。 .jsonl 全件 grep は cheap (= 数百ファイル × 数 MB を 1 秒)。 「Claude が悪さした?」 という容疑は **頻繁** で、 cheap test path として常備すべき。

### Sample

```bash
# 過去 session 全件で 特定 MCP tool の呼び出しを検索
grep -l '"name":"mcp__calendar-cis__delete_event"' ~/.claude/projects/<project-hash>/*.jsonl

# 全 calendar mutation を検索 (read-only を除外)
grep -h '"type":"tool_use"' ~/.claude/projects/<project-hash>/*.jsonl \
  | grep -E '"name":"[^"]*calendar[^"]*"' \
  | grep -vE '"name":"[^"]*list_(calendars|events)"'

# 特定 calendar (= classroom 系) を touch した tool_use を抽出
grep -h '"input":{[^}]*"calendarId":"c_classroom' ~/.claude/projects/<project-hash>/*.jsonl \
  | grep -E '"name":"[^"]*(delete|update|patch|insert|create)'

# 件数だけ確認
grep -h '"type":"tool_use"' ~/.claude/projects/<project-hash>/*.jsonl \
  | grep -E '"name":"<suspect-tool>"' | wc -l
```

project-hash は `~/.claude/projects/` 直下の `-` 区切り path 表現 (= 例: `-Users-<user>-<project-path>`)。 `ls ~/.claude/projects/` で列挙。

### How to apply

1. 「Claude が消した / 書いた / 上書きしたかも?」 容疑が user / 自己から提示されたら、 即 `~/.claude/projects/<project-hash>/*.jsonl` を grep
2. **mutation tool だけ** に絞る (= `delete`/`update`/`patch`/`insert`/`create` 系)、 read-only の `list_*`/`get_*`/`read_*` は除外
3. 0 件なら Claude を容疑者から外す (= 確信度: 高、 .jsonl ledger 全件で履歴無しなら呼んでない)
4. 1 件以上なら record の `tool_use_id` + 周辺 message を読んで context 復元 (= どの session / どの user prompt が trigger したか)

### 適用範囲

- Claude Code (= `~/.claude/projects/`) を使う user 全員に applicable
- Claude API 直接利用 / 他クライアント (= claude.ai web、 Claude for Mac の Chat) は別 storage、 同手法 NA
- session 履歴の retention は default で残る、 削除規律あれば前確認

### 関連事故 / 検証例

- **2026-05-12 calendar event 2 限消失** (個人 layer 内 private repo の SESSION.md に詳細記録): 過去 Claude session が `mcp__calendar-cis__delete_event` を呼んだのでは? という容疑 3 つ目を 1 grep で潰した (= 全 session で 0 件、 read-only の `list_calendars`/`list_events` のみ)。 user の体感容疑は「shift-worship-period.py / Apple sync / Claude 自身」 の 3 つだったので、 各 1 件ずつ独立に潰す必要があった。 .jsonl grep は 3 個目を即時に潰す cheap test。

---

## 8. Interactive script (= URL 出力 + polling) を `| tail -N` 等の pipe と combine しない

**ルール**: 「URL を stdout に出して user の手操作を待つ」 系 interactive script を `run_in_background` で起動する際、 `| tail -N` / `| head -N` / `| grep PATTERN` 等の pipe と combine すると **stdout が buffer に閉じ込められて URL が出力されない**。 unbuffered (= `python3 -u`、 `stdbuf -oL`、 `node` も default で line-buffer) + pipe なしで起動する。 注意: pipe だけでなく **plain redirect (`> file`) / `run_in_background` でも、 un-line-buffered な script は block-buffer する** (= 「pipe を避ければ安全」 は誤り)。 script を編集できるなら下記「Root fix」 (= stdout を line-buffer 化) が根本対処で `-u` を不要にできる。

### Why

`tail -N` は input が EOF に到達するまで output を出さない (= 「末尾 N 行」 を保証するため buffer 必須)。 `head -N` も同様。 interactive script は polling で永続実行 (= EOF 来ない) → user に URL が見えない → user が action 取れない → script は polling 続けて hang。

加えて Python は stdout が pipe 接続だと block-buffer モード (= 4-8 KB ごとに flush) になる (= terminal 接続なら line-buffer)。 `print()` した URL が pipe の入り口で buffer に溜まり、 buffer 容量に達するまで flush されない。 unbuffered (`-u` flag) で line-buffer に強制すれば flush されるが、 受け側 (`tail`/`head`) が buffer する以上 user には届かない。

### Sample

```bash
# ✗ NG: URL が buffer に閉じ込められて 何分待っても出力されない
python3 scripts/fetch-with-picker.py 2>&1 | tail -30

# ✓ OK: 直接実行、 stdout は file に書かれて流れる
python3 -u scripts/fetch-with-picker.py
```

`run_in_background` の場合: output file を Read tool で直接読む / `cat` する。 `tail -f` 等 follow 系も interactive ではないなら可、 但し follow は EOF を待たないので script の polling と相性は OK (= follow と "末尾 N 行" は別 semantic)。

### How to apply

1. 「URL 出力 + polling」 「pickerUri」 「ブラウザで開いて完了押下」 等の interactive 要素を含む script は **pipe を一切 combine しない**
2. Python 系は `-u` flag 付きで起動 (= line-buffer 強制、 file 出力でも line ごとに flush される)
3. `run_in_background=true` で起動 → output file を直接 Read で取る
4. 既に pipe で詰まったら kill して再起動 (= script 自体は無罪、 pipe の semantics が罠)

### Root fix: script を自分で書けるなら stdout を line-buffer 化する (= `-u` を不要にする)

上記の `-u` / 「pipe なし」 は **consumer 側の workaround** (= 呼び出すたびに正しく起動する知識に依存する)。 script を編集できるなら **root は script 側で stdout を line-buffer 化する** こと。 起動時 (main 冒頭、 最初の print より前) に:

```python
import sys
try:
    sys.stdout.reconfigure(line_buffering=True)   # Python 3.7+。改行ごとに flush
except (AttributeError, ValueError):
    pass
# さらに block する直前 (= polling / input() の手前) に念のため明示 flush (二重化):
sys.stdout.flush()
```

これで **plain redirect (`> log 2>&1`) でも `run_in_background` でも (pipe を combine しなければ) 即 flush** され、 `-u` を毎回付ける必要が消える (= 起動方法の知識に依存せず robust)。 `stdbuf -oL` / `node` の line-buffer default も同じ効果だが、 source を直せるなら script に焼き込むのが最も再発しにくい。

**ただし 2 層あることに注意** — root fix で消えるのは ① の方だけ:

| layer | 原因 | line-buffer 化で消える? |
|---|---|---|
| ① script 側 block-buffer | Python は stdout 非 TTY で block-buffer (file/pipe/background すべて) | **消える** (script を line-buffer 化すれば) |
| ② reader 側 buffer | `\| tail -N` / `\| head -N` が EOF まで出力を保持 | **消えない** (consumer の semantics、 script 無関係) |

→ line-buffer 化した script でも `| tail -N` / `| head -N` に pipe したら URL は出ない。 「interactive-polling script を tail/head に pipe しない」 原則は root fix 後も残る。

⚠️ **「pipe を避ければ安全」 は誤り**: ① は pipe 不在でも発生する。 un-line-buffered な Python script を `> file 2>&1` (pipe なし) や `run_in_background` で起動しても pickerUri は block-buffer に滞留する。 root fix (line-buffer 化) か `-u` の **どちらかが必ず要る**。

### 関連事故

- **2026-05-26**: `fetch-board-photos.py` (= Google Photos Picker workflow) を `python3 scripts/fetch-board-photos.py 2026-05-22 2>&1 | tail -30` で起動、 pickerUri が buffer に閉じ込められて user に届かず、 script は polling で永遠 hang。 kill + `python3 -u ... ` (pipe なし) で再起動 → 即 URL 出力 → user が完了押下 → 正常終了。
- **2026-06-08**: 同 `fetch-board-photos.py` を `run_in_background` + plain redirect (`> log 2>&1`、 **pipe なし**) で起動 → pickerUri が出力されず 120s+ hang。 §8 の旧 framing が pipe 中心だったため「pipe を使っていないから安全」 と誤認したのが穴。 真因は ① (= plain redirect でも Python が block-buffer する)。 `-u` で一旦凌ぎ、 その後 script の main 冒頭に `sys.stdout.reconfigure(line_buffering=True)` + poll 直前 flush を入れて root fix 化 (= 上記)。 plain redirect (`-u` なし) で pickerUri が約 3s で出力されることを再現確認。

---

## 9. MCP / API の count return「0」 / 「期待と違う検索結果」 を reflex で「想定外」 と結論しない (= §16 trait family の MCP / tool 健全性 domain)

**ルール**: MCP tool / API 呼び出しの count-style return (= `added=0`、 `affected_rows=0`、 `total: 0`、 list が空、 etc.) や「期待と違う検索結果」 を見て即座に「想定外」 「未発生」 「未登録」 「存在しない」 と reflex 結論しない。 その 0 / 結果が「true な空」 か「正常 dedup / filter による empty」 か「**tool が間違った接続先 (account / endpoint) を見ている**」 かを **別 query で 1 path 必ず cross-check** する。 特に user が「絶対あるはず」 と確信を示したら、 source 不在より先に tool 健全性を疑う。

### Why

count return「0」 / 「期待と違う中身」 は 3 つの distinct な状態を同じ表面値で返す:
- (a) **真の不在**: source 側に entry がない (= 学生が提出していない、 entry が作られていない)
- (b) **正常 filter 結果**: source 側に entry がある + script の dedup / filter / state 判定で既知 / 対象外と判定された結果 (= 既に sync 済で重複 add なし、 filter 条件に hit しない、 state 不適合で skip)
- (c) **tool が間違った接続先 (account / endpoint / dataset) を見ている**: MCP / API token が期待と別の account を指している、 endpoint が別 dataset を返している等。 0 だけでなく「らしくない中身」 (= 期待と違う account の data ばかり返る) のが signal。 (a)(b) と違い **tool 自体の健全性の問題**で、 source 側をいくら調べても解決しない。 user が「絶対ある」 と確信を示す場合の典型 root cause

(a) で reflex 結論 → (b) で誤判定の 2 重 cost: (1) user に「想定外」 を伝えて余計な調査を発生させる、 (2) 真の dedup 判定を error と誤認して fix を試み 健全な script を壊す。

これは [既存 `~/Claude/odakin-prefs/work-discipline.md §「context 構築での単一情報源 null 結論飛躍を避ける」](https://github.com/odakin/odakin-prefs/blob/main/work-discipline.md) (= CLAUDE.md inline §16) と **同 trait family** の MCP / API tool 出力 domain。 §16 は web 検索 / gmail 検索 の null result が domain、 本 §9 は MCP wrapper / sync script の count return が domain。

### How to apply

1. count-style return「0」 / 「added=0」 / 「empty list」 / 「期待と違う中身」 を観察した瞬間に「これは (a) true 不在か (b) dedup 等正常結果か (c) tool が間違った接続先を見ているか?」 を必ず問う
2. 即座に **より低 level な query** で cross-check (= MCP 経由なら raw API 直接 query、 sync script なら DB 内 entry count 直接 grep、 etc.)
3. **(c) の cross-check は tool の接続先確認**: MCP / OAuth token なら `getProfile` 系で「今どの account を見ているか」 を直接確認 (= 検索結果の中身が「らしくない」 = 別 account の data ばかり、 が強い signal)。 期待と一致しなければ tool 故障 → reauth / 接続修復が先で、 source 調査は無意味
4. cross-check で (b)/(c) と判明したら「想定外」 narrative を即訂正、 不確実性を expose した path として記録 (= §13 alignment)
5. 「想定外」 「存在しない」 を user に伝える前に最低 1 cross-check を通す reflex を hardcode。 **user が確信を示したら tool 健全性を最優先で疑う** (= source 不在の結論より tool の (c) を先に潰す)

### 関連事故

- **2026-05-26 fetch_comments.mjs added=0 reflex 結論**: 3 科目 sync で EM/QM 第5回 (締切 5/20 14:59 経過済) の `added=0` を見て「提出 0 件 = 想定外」 と reflex 結論しかけた。 `classroom_list_submissions` で raw query → EM L5: 17 RETURNED + 9 CREATED+late = 計 26 (= 履修者全数で正常提出あり)、 既存 `comments.yaml` に L5 20 entry → 別 session が 5/18-5/20 に既 sync 済 → dedup の (b) 正常結果と判明。 reflex を 1 cross-check で訂正できた、 もし user に「想定外」 を伝えていたら余計な調査 trigger。
- **2026-06-01 MCP account すり替わり = (c) tool 接続先誤りの実証**: ある account の受信メールを 4 つの MCP account で検索 → 1 つで 0 hit → Claude が「全 account 検索したが該当メール存在しない」 と user に結論。 user 「絶対来ている」 push で再調査 → 当該 MCP の検索結果が個人購読 newsletter ばかり = 「らしくない中身」 と気付き、 Python 直接で `getProfile` → **その MCP token が別 account (= 業務用のはずが個人用) を指していた** と判明 (= 過去の reauth でアカウント誤選択 + 当時 token に検証 step なし、 約35日間すり替わり)。 検索は全部別 account を見ていたため無効で、 修復後に本来の account で埋もれていた student メールが surface (= 課題提出が21日埋もれていた)。 教訓: 「らしくない検索結果」 + 「user の確信」 = (c) tool 健全性 (account/endpoint) を疑う 2 大 signal、 source 不在の結論より先に潰す。 reauth フローには login_hint + 認証後 getProfile 検証 (不一致なら token 破棄) を入れて silent すり替わりを構造的に防ぐ。 具体経緯は personal layer 運用記録 + 該当 MCP 設定リポの DESIGN を参照。

---

## 10. silent dead / 経路の穴は「violation を仕込んだ実 e2e」 でしか expose できない

§1 (3 verification) / §6 (dry-run 観測) は機構が **何をするか** を verify するが、 機構が **そもそも発火するか** は別問題。 gate / hook / detector / validator が **silent dead** (= 呼ばれない・経路の穴で skip・条件分岐で素通り) の場合、 logic 確認・syntax 確認・関数単体シミュレート・dry-run は **全て pass する** (= 機構の中身は正しいので)。 緑の ✓ が「動く」 の証明にならない (= `docs/convention-design-principles.md §8.8` の false confidence)。

### How to apply

- gate / hook / detector を作ったら、 **catch すべき violation を実際に仕込んだ実 e2e** を 1 回通す (= 「正常 input で通る」 だけでなく「**異常 input が本当に block されるか**」)。 破壊的 e2e (= 実 commit / 実書込) は revert 前提で安全に。
- **confidence 境界を report に明示し、 重要な機構は境界を残さず実検証する**。 「logic ✅ だから動く」 と打ち切らない。 4 軸 sweep (= grep / 論理) で error 0 でも、 実 e2e で silent dead が出ることがある (= 静的 sweep と動的 e2e は別 layer)。

### 関連事故 / 検証例

- 2026-06-06: pre-commit chain gate が primary hook の early-exit で **silent dead** (= `hook-authoring.md §8`)。 logic / syntax / 関数シミュレートは全 pass、 4 軸 sweep も error 0、 重複を仕込んだ **実 commit e2e (= reject されるべき commit が通る)** でのみ発覚。 confidence 境界に「pre-commit e2e 未実行」 と明示していたのを実検証して捕捉。
- §6 (dry-run = 動作観測) と本 § (= 発火 verify) は相補: dry-run でも、 そもそも発火しない機構は観測すらされない。

---

## 11. 症状の本格 forensics 前に「既存 conventions / docs に同症状の記録が無いか」を grep

**ルール**: 観測した症状 (= error 文字列 / 異常挙動) で fresh forensics (= lsof 全 attribution / web 検索 / transcript 解析 / 実験) に投資する**前**に、 まず project 自身の `conventions/` + docs を症状の distinctive token で grep する。 既知症状なら workaround doc が診断手順・root・対処まで持つことが多く、 再導出は時間の丸損。 = CLAUDE.md inline §3 (= 事実主張前に内部 grep) の debugging domain への適用 (= 「外部検索の null で結論する前に内部 grep」 の対偶 = 「外部 forensics を始める前に内部 grep」)。

### Why

症状 forensics は高価 (= lsof 全プロセス attribution / transcript 解析 / web 調査 / 実験で各数分〜)。 既存 workaround doc は同じ診断を既に済ませている可能性が高く、 grep は 1 秒。 順序を逆にする (= 先に fresh forensics) と doc が持つ答えを高コストで再導出する。

### 付随する 2 失敗 (= 本件で同時発生)

- **正しい OS artifact を測れ**: leak / 枯渇する resource **本体**を測る。 相関するが別物の artifact を測ると誤診する。 例: pty leak は `/dev/ptmx` (= master、 親プロセスが保持) で起きるが、 `/dev/ttys` (= slave、 子 shell 終了で解放) を測ると「9 本だけ open = leak 無し」 と誤結論する。 doc の診断手順 (= 何を測るか) に従えば回避できた。
- **症状の surface 地点 ≠ 原因 (= victim vs perpetrator)**: 症状が出た component / session は犯人とは限らない。 他が resource を食い尽くした状態で、 その component の正常操作が壁に当たっただけのことがある。 「symptom が出た X」 を即 root と扱わず、 X が victim の可能性を 1 path 検討する。

### How to apply

1. 症状観測 → fresh forensics の前に `grep -ril '<symptom token>' <repo>/conventions/ <repo>/docs/` (= `forkpty` / `ptmx` / error 文字列の distinctive part)
2. hit したら doc の診断手順・root・workaround を先に読む (= 再導出しない)。 forensics する場合も doc の「測るべき artifact」 に従う
3. 症状が出た component を即 root としない (= victim 可能性を 1 path check)

### 関連事故

- **2026-06-08 pty leak 再診**: macOS pty 枯渇 (`forkpty: Device not configured`) は `conventions/macos-claude-app-pty-leak.md` が症状・診断 (`lsof /dev/ptmx`)・root・workaround まで完全記載済だったのに grep せず、 lsof (= 誤って slave `/dev/ttys` を測定 → 「leak 無し / burst」 と誤診) + web 検索 + transcript 解析の fresh forensics に 1 session 費やして再導出した。 過去 session の transcript (= §7 grep) から既存 doc に辿り着いて自己訂正。 冒頭で `grep -ri ptmx conventions/` していれば即解決 + slave 誤測も回避できた。

---

## 12. 再現 ≠ 検証: 決定論的 / 撤回済 artifact は誤っていても再現する

ある計算が以前報告された数値を再現したことは、 両者が同じ (誤りうる) convention / 実装を共有している限り **検証にならない**。 決定論的 artifact は正しさと無関係に再現する。 特に **既存の analysis / audit script を結論の根拠に使う前に provenance を確認**せよ — project の retraction log (`RETRACTIONS.md` 等) と script の docstring を distinctive token で grep し、 過去に「非物理 / convention-mismatch / 撤回済」 と判定されていないか見る。

### Why

- 「自前で再現できた → だから正しい」 は循環。 同 bug / 同 convention の再実行は同じ誤値を出す。
- 撤回済 artifact は歴史記録として file が残ることが多く、 名前で hit するが**使ってはいけない**。 retraction log を読まずに「ちょうど良い既存 script」 として拾うと、 撤回済の誤 narrative を再 instantiate する。
- = CLAUDE.md inline §3 (= 単一情報源で結論飛躍しない、 安価な検証を先に) + 本 file §2 (audit verdict 再評価) の verification domain への適用。 ここでの「安価な検証」 = retraction log の grep。

### How to apply

1. 既存 script / 過去結果を結論の根拠にする前に、 その docstring + project の retraction log を grep
2. 「これは physical か、 特定 convention 内の artifact か」 を問う
3. 別実装 / 第一原理 (= 次元解析・ground-truth 機構・canonical 実装) で cross-check してから結論

### 実例

ある物理計算 session で、 retraction log に「convention-mismatch の非物理 artifact」 として撤回済の audit script を、 log を読まず physical と誤認して結論 (= 新 narrative + 新 commit) を構築。 撤回済 artifact が決定論的に再現したため「再現できた」 を validation と取り違えた。 canonical 実装で再計算して誤りに気付き retract + 削除。 → reflex: convention 依存 / `*_audit` 系 script を結論の根拠に使う前に retraction log を必ず grep。

---

## 13. mechanism が「発火したか」 を検証する時は依存ゼロの unconditional probe + 独立 discriminator、 「実行」 と「honor」 を分ける

§10 は「silent dead は実 e2e でしか expose できない」、 §12 は「再現 ≠ 検証」 だった。 本節は **mechanism (hook / 自動化 / guard) が特定 context で発火・効果したかを切り分ける**作法。 雑にやると「動いていない」 と「動いたが効果が捨てられた」 を取り違え、 誤った root cause を作話する。

3 つの落とし穴と対処:

1. **conditional な proxy で発火を判定しない** — 「cache の mtime が更新されたか」 「出力が出たか」 等は、 mechanism が **該当なしで silent** な設計だと「発火したが何も出さなかった」 と「そもそも発火しなかった」 を区別できない。 さらに proxy が複数の writer / 別 path / 認証・権限に依存すると交絡する。 → **依存ゼロの unconditional probe** を使う: 「呼ばれたら無条件に痕跡を残す」 だけの仕掛け (= file に 1 行 append する trace 等)。 API / credit / 権限 / 該当有無に依存しないので、 痕跡の有無 = 発火の有無を一意に決める。 ⚠️ 既存 mechanism に後から probe を差すと snapshot 型 harness では当該 session に反映されない (= `hook-authoring.md §9.1`) ので、 新 context (新 session / 新 frontend) で観測する。

2. **env var / 表層の自己申告を frontend/context の discriminator にしない** — 環境変数は継承・leak・汚染しうる (= 例: `CLAUDE_CODE_ENTRYPOINT` が別 context に漏れる)。 → **独立した観測量**で判別する: 親プロセスの実 path / build 番号 / cwd 等、 自己申告でない物。 1 signal が怪しい時は 2 つ目の独立 signal で corroborate (= §convention-design-principles §8.14 の identity corroboration と同根)。

3. **「実行された (executes)」 と「効果が honor された (honored)」 を分ける** — mechanism は **プロセスとして走った**のに、 その出力・決定を上位層が **捨てる**ことがある (= 例: desktop frontend は hook を実行するが stdout 注入 / permission 判定を honor しない、 `hook-authoring.md §9.3`)。 「効果が出ない」 を即「実行されていない」 と結論しない。 副作用 (file 書込等) の有無で「実行」 を、 モデル/flow への反映で「honor」 を別々に確認する。 両者は別の修復を要する (= 未実行なら配線、 honor されないなら surface 自体を変える = `docs/convention-design-principles.md §8.15`)。

reflex: 「この mechanism、 ここで効いてる?」 を検証する時、 (a) 痕跡が conditional な proxy になっていないか、 (b) frontend/context 判別が自己申告 env に依存していないか、 (c) 「効果不在」 を「未実行」 と短絡していないか、 の 3 点を問う。

origin: 2026-06-13 desktop-hook-gap 調査。 当初 SessionStart hook の死活を cache mtime で推定 → 交絡 (cache は別 writer + CLI 認証 credit 切れ + Terminal の EventKit TCC で書かれない) で不確定。 依存ゼロの trace (file append) に切替えて発火を確定、 親プロセス path で frontend を判別 (env var は汚染懸念)、 さらに「desktop は hook を実行するが出力を honor しない」 = 実行 ≠ honor を分離して初めて正確な像を得た。 起票 session は cache mtime 1 点 + env var で「SessionStart 死亡」 と推定し一部誤帰責していた (= §9.1 snapshot 交絡で PreToolUse 非発火も実は未分離だった)。

## 関連

- [`CONVENTIONS.md §3`](../CONVENTIONS.md) — 4 軸 sweep の base 規約
- [`conventions/scientific-computing.md §2`](scientific-computing.md) — L5 numerical fix の (A)/(B)/(C) 階層、 V3 algorithm 網羅の domain-specific application
- [`docs/convention-design-principles.md`](../docs/convention-design-principles.md) — 規約配置の meta-rule
- [`docs/sensitive-repo-patterns.ja.md §パターン 5-3`](../docs/sensitive-repo-patterns.ja.md) — 実装直後の 4 軸 review

### 個人層との関係

odakin の personal layer (= `odakin-prefs/work-discipline.md`) には本規律の application 例 / 反例 / odakin-specific 補強規律が記録されている (= 一部は本規律の precursor)。 本 file が universal な核、 personal layer は odakin の歴史的事例 + 個人 reflex 規律。
