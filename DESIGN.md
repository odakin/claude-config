# DESIGN — claude-config

設計判断とその理由を記録する。

---

## 2026-06-27: Office handling 入口 router を layer 1 に hoist (`office-files.md` 新設)

### 問題

Office ファイル (Excel / Word / PDF / pptx) の handling は layer 1 に knowledge が散在していた:
- 考え方 = `office-automation-principles.md`
- 罠 = `office-automation.md` (+ `index.yaml` validator)
- 道具 = `scripts/diff-form-xlsx.py` / `pdf_form_fill.py` / `docx-to-pdf.sh` / `xlsx-to-pdf.sh` / `pptx-to-pdf.sh` / 各種 integrity check
- 権限 = `claude-code-permissions.md`
- e-Rad = `erad-submission.md`

しかし**全部を束ねる単一入口が layer 1 に無く**、 個人層 (layer 3) の `office-file-handling.md` に router がある状態だった。 = layer 1 only の参照ルートが存在せず、 「universal な Office 仕事の入口」 として generic な user が辿れる経路が欠けていた。

### 設計

`conventions/office-files.md` を**薄い router** として新設:
- 入口 ⓪〜⑥ (考え方 / 権限 / skill 判断 / 罠 / PDF 化 / 機械監査 / e-Rad) を 1 表で
- 中身は持たず**全 pointer** (layer 1 内の各 home に飛ぶ)。 罠の早見は `office-automation.md#symptom-index` 経由
- layer 3 (個人層) の `office-file-handling.md` は env 追補 (機械別 install / 生成 driver 実装例) に薄化、 入口は layer 1 へ

これに伴う 2 つの dedup:
- 「**入口の順番**」 を `office-automation-principles.md` も宣言していた (旧 L6) → 「考え方の正本、 router は `office-files.md`」 に書き換え (= 入口の 2 重宣言を解消)
- `skill vs 手動` 判断表は principles §1 「道具選択の梯子」 と同じ「道具を選ぶ判断」 軸 → principles §1 に統合 (router 側は pointer)

### 同時に投入した機械層

router §4 で参照する `scripts/diff-form-docx.py` を新設 (= `diff-form-xlsx.py` の docx 版、 ラベル欄上書き / 見出し消失 / 空の箇条書き / 全空 labeled 列を blank diff で検出)。 `office-automation.md#diff-form-docx-detection` slug + principles §5b「記入後は『審査員の目』 で閉じる」 とセット。

### origin

2026-06-27 ある研究費 docx 申請様式で同一様式に 4 記入ミス連続 → 申請者発見 ×4。 視覚 render しても自分の記入箇所しか見ない = recall 依存の規律では止まらない実証 → 機械化 + router hoist。

---

## 2026-06-17: layer-1 convention の発火面 — 「正しい層配置」 と「発火確率」 の tension (= future work)

### 問題

universal な規律 (= 全 Claude Code ユーザーで true) は 4 層 model 上 **layer 1 (`conventions/*.md`) が正しい配置**。 だが [§10](docs/convention-design-principles.md#file-role-architecture) (`docs/convention-design-principles.md`) の auto-load tier では `conventions/*.md` は T0 (= 毎 session 強制 load = CLAUDE.md / MEMORY.md のみ) でなく **on-demand**。 つまり layer-1 convention は「何かがそれを指していて、 かつその pointer が読まれた時」 にしか発火しない (= [§8.12](docs/convention-design-principles.md#firing-surface-hierarchy) 発火面 hierarchy で最弱の **doc 記載 / recall 依存**)。

→ **tension**: 規律を正しく layer 1 に置くと観客は最大化されるが、 **発火確率は下がりうる** (= 個人層 CLAUDE.md の「読み込み必須」 経由でしか辿られず、 該当 convention file を実際に開かないと効かない)。 「正しく記録したのに発火しない」 が起こりうる。

### 暫定 mitigation (= 2026-06-17 に実証した「下層から参照を張る」)

universal rule を layer 1 に置いたうえで、 **その規律が効くべき作業文脈で読まれる下層 doc (layer 2 / 3) から pointer を張る** (= 規則実体は重複させず「正本 = layer 1」 と書いた pointer のみ。 §2 ポインタ原則)。 pointer が in-context で読まれることで layer-1 の doc 規律が下層の reading path 経由で発火する。 worked example (2026-06-17): ある universal な LaTeX 編集則を `conventions/latex.md` に新設し、 それが効く文脈で読まれる layer-3 の paper 執筆 doc + layer-2 の該当 paper repo CLAUDE.md から pointer を張った。

### open (= future work、 未決定)

manual な per-rule pointer は (a) scale しない (b) 「pointer を張るのを忘れない」 という recall に再依存する。 より系統的な発火面を探す (= 本 entry の主題):

- personal skill (`conventions/personal-skills.md`、 auto-discover = 全 session 可視) を「LaTeX / paper 編集の時に latex.md を引く」 等の topic-trigger 発火面にする
- §3 の「規約を読まない」 問題 + routing を「declared → consulted at topic detection」 へ強化 (= topic 検出時に required-reading を能動 surface)
- dashboard / SessionStart の hint surface への相乗り (= §8.12「新機構を増やす前に既存 channel への相乗りを先に検討」)
- 個人層「読み込み必須」 table の trigger column に該当 convention を登録する運用 (= 既存 channel)

### un-defer trigger (= signal / 機械判定)

- layer-1 に記録済の規律が**発火せず見落とされた incident** が 1 件発生 (= 「L1 に書いたのに効かなかった」 の再演)
- L1-rule-surfacing のための manual 下層 pointer を **3 件目**張ろうとした時 (= DRY 圧 → 系統化、 §9.6 機構増殖抑制と両睨み)
- convention の発火面を別件で再設計する時 (= personal-skills 拡張等に相乗り)

### 関連

- [`docs/convention-design-principles.md` §8.12](docs/convention-design-principles.md#firing-surface-hierarchy) (発火面 hierarchy、 doc=最弱) / [§8.13](docs/convention-design-principles.md#conditional-firing-visibility) (silent dead) / [§8.15](docs/convention-design-principles.md#enforcement-surface-frontend-survival) (frontend honor、 ⚠️ ex-§8.14 typo: label "frontend honor" は §8.15 と semantically 一致、 §8.14 は identity corroboration) / [§3](docs/convention-design-principles.md#rule-addition-criteria) (「規約がない」 か「規約を読まない」 か) / [§10](docs/convention-design-principles.md#file-role-architecture) (auto-load tier)
- `conventions/personal-skills.md` (skill = auto-discover 発火面)
- 起点: universal な LaTeX 編集則 (= 段落長の判断でコメントアウト行を数えない) を latex.md に hoist した際、 user が「層 1 だと逆に読まれなくなる」 と発火面の弱さを指摘 → 下層 pointer で暫定対応 + 本 entry で系統化を future work 化

---

## 2026-06-13: CONVENTIONS.md 冒頭の conventions/ 列挙 — 完全列挙と判定して再生成、機械 enforcement は defer

### 問題と意図判定

冒頭の `conventions/*.md` 列挙が dir 実体 56 file に対し 35 file で drift していた (≈ 2.5 ヶ月分の追加忘れ)。「完全列挙のつもりが drift」 か 「意図的 curation (domain 規約のみ掲載)」 かを git 履歴で判定: (a) 初出 commit `4cdd2d4` (2026-03-31 split) では実体 2 file = 列挙 2 file の完全列挙、 (b) `git log -L` で列挙行の全履歴を見ると entry の除去は一度もなく単調追記のみ、 (c) 直近の追記 `e29fba4` は infra/meta 系 (hook-authoring / personal-skills) を含み 「domain 規約のみ」 仮説と矛盾、 (d) 漏れた 21 file 中 20 は **CONVENTIONS.md を触らない commit** で追加されたもの (全 21 を commit 単位で検証済。 残る 1 = giving-talks.ja.md だけは CONVENTIONS.md を触った同時追加 commit `24c3775` でも EN のみ列挙されており、 これは drift でなく「翻訳 variant は列挙しない」 意図的前例)。 → **完全列挙が意図、 追加忘れ drift と判定** (.ja variant のみ例外規則として明文化)。

### 修復

列挙を `ls conventions/*.md` の名前順で再生成し、 冒頭に scope marker (= 全列挙・名前順・新規 file は同 commit で追記・`.ja.md` 翻訳 variant は親 entry に併記) を明記。 これで「漏れ」 と 「意図的除外」 が区別可能になり、 将来の audit は列挙 vs `ls` の機械 diff に還元される。 `.ja.md` の扱いは前例踏襲 (= giving-talks の EN+JA 同時追加 commit `24c3775` でも EN のみ列挙していた) で親 entry への併記とした。 同型 drift だった CLAUDE.md 構造 tree (6 file 欠落) も同 commit で同期。

### 機械 enforcement: 当初 defer → 同 session で実発火に格上げ (`.claude/pre-commit-extra.sh`)

当初は「再 drift したら機械化する」 という **doc 記載の格上げ trigger** で defer した (= blast radius annoyance 級、 §9.1 triage、 §9.6 機構増殖抑制)。 しかし user が「これはしっかりそうなるようになってるか?」 と問うた — これは正しい指摘で、 **doc 記載の trigger は §8.12 の最弱発火面 (recall 依存)** であり、 まさに今回の列挙 drift を ~2.5 ヶ月 silent 累積させた失敗 mode そのもの。 「再 drift したら発動」 は安全網に見えて、 実体は「誰かが DESIGN.md を読んで思い出せたら」 に依存する note にすぎない。

→ user の問いを trigger として、 同 session で**既存 channel への相乗り**で機械発火に格上げ済 (= 新 standalone 検出器 / dashboard 項目は増やさない):

- **発火面**: `public-precommit-runner.sh` が leak gate pass 後に chain する `<repo>/.claude/pre-commit-extra.sh` (= 既存の設計済み拡張口、 従来 claude-config 未使用) に check を実装。 commit の瞬間・drift を入れた本人に発火する決定的 surface
- **検査**: CONVENTIONS.md 冒頭の全列挙 + CLAUDE.md 構造 tree の conventions/ block が、 実体 `conventions/*.md` と一致するか (.ja.md は列挙内 variant link として実体集合と一致)
- **比例性**: §9.1 に従い **warning のみ・常に exit 0** (commit を block しない)。 annoyance 級に block を当てない
- **検証**: 同期済で無音 / drift 注入で該当 file 名指し warning を self-test 済

残課題: pre-commit は claude-config に commit する瞬間にしか発火しない (= 他 clone / 別経路で dir だけ増えた状態は次 commit まで未検出)。 ただし dir 追加は必ず commit を伴うため実害は最小。

---

## 2026-06-01: setup.sh の clone step — local dir rename による重複 clone を防ぐ

### 問題

Step 7 (= 認証ユーザーの全 repo を clone) は GitHub repo 名で `$CLAUDE_DIR/$REPO` に clone し、 同名 dir が無ければ clone する。 ところが local clone の **ディレクトリ名を GitHub 名と別名に rename** している場合 (= 表示名を非 ASCII 名にする等)、 setup.sh は rename 後の dir を「未取得」 と誤認し、 **毎回 GitHub 名で重複 clone を生成**してしまう。 同一 remote の 2 clone は独立に drift し、 片方が push すると他方が silent に behind 化する (= cross-clone drift の温床)。

### 修復

clone loop の前に、 既存の `$CLAUDE_DIR/*/.git` 各 dir の `remote.origin.url` を正規化 (= `owner/repo` に統一、 https / ssh / `.git` suffix / 大小文字を吸収) して集合化。 clone 判定で従来の「dir 名一致で既存 → skip」 に加え「**同一 remote を持つ dir が別名で既存なら skip**」 を追加。 これで rename された clone は再生成されない。 bash 3.2 / Windows 互換 (= 連想配列不使用、 `git config --get` 使用 [`git remote get-url` より移植性が高い]、 集合判定は `grep -qxF`)。 純粋に「clone する件数を減らす」 方向の変更なので後方互換 (= 既に同一 remote が手元にある = repo は既に存在する、 skip は安全)。

### 発見経緯

odakin の私的環境で同一 remote の二重 clone が session 間で drift し、 片方が session 開始時の sync 規律から漏れて behind 累積していた (= 詳細は個人層の SESSION 記録)。 個人層の SessionStart 全 repo sync sweep hook が症状を session 境界で機械回収する一方、 本 setup.sh 修正は **重複生成の根本**を断つ (= 症状回収と根本断ちの 2 層)。

---

## 2026-05-26: commit-msg leak guard option B (= git native BLOCK mode) を harness invoke bug の mitigation として投入

### 起点

2026-05-25 evening の言語移植 session で claude-config 公開リポに連続 leak 発生 (= 詳細は `個人層の leak-incidents.md` 5/25 entry)。 既存 layer 3 hook (= `commit-msg-leak-guard.sh`、 2026-05-20 MVP shipped、 PreToolUse Bash matcher、 warn mode) が **本 leak を捕まえなかった**。 5/26 follow-up session で root cause 究明、 仮説 5 件 verify → **真因 = claude-code 2.1.x の `PreToolUse[Bash]` matcher harness invoke bug** (= 既存 `conventions/hook-authoring.md §2 (d)` entry、 Anthropic issues [#52715](https://github.com/anthropics/claude-code/issues/52715) + [#59513](https://github.com/anthropics/claude-code/issues/59513)) と確定。 hook script + 配信 (a)(b)(c) は全 healthy、 harness が invoke しない silent failure で、 (a)(b)(c) audit だけでは expose できない。

### 修復 candidate 4 案 evaluation

| 案 | 概要 | reliability | 投入コスト | 副作用 |
|---|---|---|---|---|
| A: Anthropic fix 待ち | issue #52715/#59513 修復を待つ | 不明 (release date 未公開) | ゼロ | leak window 無期限 open |
| **B: git-side commit-msg hook** | git native hook で harness を bypass、 同 logic を BLOCK mode で適用 | 高 (= git 自身が起動、 harness bug 影響なし) | 中 | 一部 `--no-verify` で bypass 可 |
| C: dashboard post-hoc detect | 過去 commits を retrospective scan | 低 (= 検出は事後、 leak は既に焼き付き) | 既投入 | 予防 layer ではない |
| D: workflow 強制 | Claude が commit 前に手動 invoke 規律 | 低 (= reflex に依存) | ゼロ | attention budget 圧迫 + skip で破綻 |

### Resolution: 案 B (= git-side commit-msg BLOCK mode)

新規 components:
- `scripts/lib/commit-msg-leak-matcher.sh` — sourceable matcher library (= layer 3 claude-code hook + 本 runner の両方が source、 DRY)
- `scripts/commit-msg-leak-guard-runner.sh` — git commit-msg hook 本体 (BLOCK = exit 1 on hit)、 `.claude/public-repo.marker` 確認 + comment 行 strip + merge/squash skip
- `scripts/commit-msg-leak-guard-runner.test.sh` — 17 case、 mock personal layer pattern (= `CLAUDE_PERSONAL_LAYER` env で temp dir 注入、 layer 3 data を public test file に embed しない)
- `scripts/install-public-commit-msg.sh` — installer (= `install-public-precommit.sh` と同 pattern: marker check + `core.hooksPath` cascade + 既存 hook backup + 冪等)

統合:
- `setup.sh` Step 8 を pre-commit + commit-msg 同時 install loop に拡張
- 既存 layer 3 hook を shared library を source する形に refactor、 26 test 全 pass 維持

### なぜ BLOCK mode を選ぶか

claude-code hook は warn mode (= MVP 仕様で「dry-run 観察期間」 を経由する想定)、 但し git-side で再び warn にすると **同じ single-viewpoint trap** が再現する (= 規律 §13 + `hook-authoring.md §5.1` の「生成 stream 内で自己 gate できない」 問題)。 git 層で BLOCK にすることで:

- claude-code harness が dead でも commit が止まる (= 本件の元 bug 症状を bypass)
- Claude session の自己 reflex に依存しない (= 「読んだか」 が不問になる)
- `--no-verify` は git 標準の escape hatch、 意図的 bypass は personal layer の leak-incidents 記録推奨

既存 `public-precommit-runner.sh` も BLOCK mode で統一済、 design 整合。

### なぜ matcher を layer 1 に置くか

(a) algorithm 自体は public-safe (= 6 allowlist 名は既に `CLAUDE.md §例外 list` で public)、 (b) 2 caller (= layer 3 hook + layer 1 runner) が同 logic を共有する DRY、 (c) layer 3 data (= `repos.md` / `sensitive-terms.txt`) は `find-personal-layer.sh` cascade で動的解決、 layer 1 source に literal embed しない、 (d) foreign user は personal layer 不在で fail-open (= 既存 `public-precommit-runner.sh` Tier B と同 pattern)。

### 影響範囲

- 13 public repo に `.git/hooks/commit-msg` stub 配信完了 (= 2026-05-26 時点 marker 保有 repo 全件)
- 新規 public repo は `.claude/public-repo.marker` 作成後の `setup.sh` 実行 (= 既存 missing-marker 警告は同 Step 8 内で出力) で自動 cover
- 2-layer 防御: 既存 `public-precommit-runner.sh` (= file 本文 Tier A + Tier B) と本 hook (= commit message Tier A + B) が独立に gate、 過去 leak 事例の「file 本文 OK だが commit message に leak」 死角を埋める

### 反省 (= meta)

実装 commit `4f4e636` 自体で **self-leak が発生** (= `commit-msg-leak-guard-runner.test.sh` の test case literal に 非例外 private repo 名 4 種を embed、 hook 自身が file body を scope 外として通過した)。 同 session の §10 4 軸 sweep 安全性軸で発覚、 `c7a9144` で mock personal layer pattern に refactor。 git history `4f4e636` の leak は force push せず documented (= personal layer の leak-incidents 記録)。

教訓: 「**leak 防御を実装する commit で自分の防御 scope の死角を踏む**」 trait family の同 session 内再演。 layer 1 test file は最初から mock pattern で書く reflex が要 (= 別 task: 個人層側の作業規律で追加候補)。

### 残務

- Anthropic fix (= 案 A) を background monitor、 fix released かつ 1 ヶ月安定 → claude-code hook の縮退判定 (= `hook-authoring.md §6` framework 適用)。 git-side BLOCK は継続維持 (= §5.1 trap 回避優先)
- 既存 `public-precommit-runner.sh` Tier A を「private repo name list 由来 regex」 で拡張する case (= file body leak の死角を埋める structural 対応 candidate、 別 task)

---

## 2026-05-19: 4 層 model の Core rule に「依存 vs 名指し」 区別を明示

### 起点

twcu-phys-web (L2) の責務境界 section で odakin の career DB upstream を記述するとき、 既存 wording は「odakin が別管理」 という abstract paraphrase 一本だった (= [shared-repo.md 旧版](conventions/shared-repo.md) §「公開前の Audit」 の grep が L3 repo 名 hit を 0 件要求していたため)。 しかし abstract paraphrase は collaborator にとって「upstream に何があるか」 を見えにくくし、 system 構造の理解を阻害する failure mode の方が強かった (= 何があるか分からない方が「何を訊くべきか」 も判断できない)。

### 概念整理

「**A が B を depend on する**」 と「**A の doc が B を mention する**」 は別の operation:

| | 依存 (depend) | 名指し (mention) |
|---|---|---|
| 操作的定義 | A の動作・解読に B アクセスが構造的に要求される | A の reader に B の存在を informational に伝える、 A は standalone |
| layer 違反? | smaller-audience layer (例: L3) を wider-audience layer (例: L2) から depend するのは違反 | boundary 明示付きであれば許容 |
| reader への harm | B にアクセスできない reader は A を使えない | reader は B を知るだけ、 A は使える |

旧 wording は両者を「参照」 という一語で一括 ban していた (= shared-repo.md 旧 L93「所有者の他の private リポへの参照 (= layer 3 の他リポ名)」)。 これは「mention も harm がある」 という暗黙の前提に立っていたが、 実際の harm は「reader が access 強要されて 404」 だけで、 boundary 明示付き mention にはこの harm は起きない。

### Resolution

[`docs/personal-layer.md` §「What \"depend\" means: structural dependency vs. mention」](docs/personal-layer.md) を canonical source として新設し、 以下を明示:

1. depend は依然 ban (= Core rule 不変)
2. mention は boundary statement 併記で許容 (= 新規定)
3. **「name it, don't path into it」 が compact rule**: repo 名は OK、 内部 file path は dependency 形に格上げで NG
4. 絶対 path / 個人 identifier (mail / cal ID / secret path) は別 reason (= privacy / portability) で依然 ban

`conventions/shared-repo.md` (= L2 特化版) は本 canonical を pointer で参照する形に簡素化。 同様に `claude-config/CLAUDE.md` §「安全規則（公開リポ）」 (= L1 特化版) も将来必要に応じて pointer 化する余地あり。

### 影響範囲

- 既存 L2 リポ (= twcu-phys-web 等) の CLAUDE.md / DESIGN.md / README.md で「odakin が別管理」 paraphrase が残っていれば、 新規定に従って named + boundary 明示に書き直し可能。 break 互換性なし (= 旧 wording も依然 valid な「名指しの abstract 化形」 として読める)
- audit grep の severity 二分: (a) repo 名 hit = warning (= boundary 文の有無を目視)、 (b) `<repo>/[a-z]` (= path 形) / 絶対 path / identifier hit = block (= 即修正)
- `hooks/public-leak-guard.sh` / `scripts/public-precommit-runner.sh` は L1 (claude-config 自身、 public scope) 対象で本変更とは別軸 (= L1 では実名・mail・所属機関名等の private data leak 防止が主、 L3 repo 名は安全規則の例外 list で扱う)

### 反省 (= meta)

旧 wording を私 (Claude) が書いたとき、 「audit grep が 0 件を要求しているから ban が正しい」 と grep の design から rule を読み戻していた (= tool が rule を決める circular reasoning)。 user 訂正で「rule の harm 仮定 (= mention でも harm がある) が実は false」 と気付いた。 一般則: **audit tool の design は rule から derived されるべき、 逆ではない**。 tool design に rule を合わせていないか定期的に問い直す習慣を持つ。

---

## 2026-05-14: 全 repo に pre-commit-bib install (= 時点依存検出の撤廃)

### 起点

個人層 private repo (講義運営系、 例外リスト外なので名前は伏せる) で新規 `.tex` ファイルに literal Unicode em-dash (`—`) を直書き、 西欧 accent (`ö`) も Unicode で記述。 `conventions/latex.md` L186 で「`.tex/.bib` 内 Unicode は `pre-commit-bib` hook で自動修正」 と規定があり、 `setup.sh` Step 6 が hook を install するはずだったが、 当該 repo の `.git/hooks/pre-commit` が **未 install** だった。

### 失敗構造の分解 (4 layer)

| Layer | 状態 |
|---|---|
| L1 規約 | `conventions/latex.md` に規定あり ✓ |
| L2 Tool | `scripts/fix-bib-unicode.py` 実装あり ✓ |
| L3 Hook 本体 | `scripts/pre-commit-bib` 実装あり ✓ |
| L4 Bootstrap (= setup.sh Step 6) | **時点依存の検出 logic で fail** ✗ |

### L4 の 2 つの欠陥

旧 setup.sh Step 6 は「`.tex/.bib` を含む repo にだけ install」 という検出 logic を採用:

```bash
for ext in tex bib; do
    if ls "$REPO_DIR"*."$ext" "$REPO_DIR"**/*."$ext" 2>/dev/null | head -1 | grep -q .; then
        HAS_LATEX=true
    fi
done
```

問題 1 (**時点依存**): setup.sh 実行時に `.tex/.bib` 不在の repo は skip → 後から `.tex` 追加されても hook 未 install のまま追従しない。

問題 2 (**bash glob 深度不足**): `ls "$REPO_DIR"**/*.tex` は bash で globstar 無効時に 1 階層しか見ない。 該当 private repo の `.tex` は depth 4 で detection 失敗 (= 「`.tex` 追加された」 タイミングで再実行しても検出されない)。

### 修正: 検出 logic 撤廃 + 全 repo install

観察: `scripts/pre-commit-bib` 自体が staged file に `.tex/.bib/.bst/.cls/.sty` が無ければ `exit 0` で no-op skip する (L31-35)。 つまり LaTeX file 不在の repo に hook を install しても害無し (overhead = staged file の grep 1 回)。

→ setup.sh Step 6 から検出 logic を撤廃し、 全 git repo に install するように変更。 これで:

- **時点依存性が消える**: 後から `.tex` 追加されても catch される
- **深度依存性が消える**: bash glob を使わなくなる
- **コード単純化**: 検出 logic ~10 行が消える

副次効果: hook install が repo の現在の物性ではなく「Claude エコシステムに属する repo であること」 をトリガーにするので、 同型の遅延 trigger 規約 (= setup 時の物性検出依存) の anti-pattern として参考になる。

### 一般化された anti-pattern

「**setup-time 物性検出による配備の condition gate**」 は時点依存 + 検出の robustness 依存で fragile。 代替 pattern:

- **(a) 配備時 condition gate を撤廃**: install action を冪等 + 無害化して全対象に install (今回の選択)
- **(b) runtime condition gate**: install は全対象、 hook 自身が runtime で条件判定 (= 今回の hook はこの形)
- **(c) post-merge / event-triggered re-detection**: 物性変化のたびに再走 (overhead 高、 別 trigger 設計要)

このうち (a) + (b) の組み合わせが最も robust。 setup.sh の他 step も同型の問題を持つか sweep する価値があるが、 公開 leak guard / git-crypt / dropbox-refs は明示的 marker / config file 経由の trigger なので時点依存問題は薄い (= marker 作成 = 意図的な setup action)。

### 関連修正

- `setup.sh` Step 6 の検出 logic 削除、 全 repo install に変更
- `claude-config/CLAUDE.md` Step 8 説明を更新
- `conventions/latex.md §pre-commit hook` 節を全 repo install 方式 + Claude 規律の明示 + 旧設計失敗の経緯記述に拡張
- 既存 36 repos に retroactive install + 1 repo update (= network-notes の旧 hook `../../scripts/pre-commit.sh` を上書き、 git history で復元可) + 13 repos で既存 hook を `.bak` backup して上書き

### Claude 側の reflex 失敗 (sub-RCA)

直接因とは別に: 私 (Claude) が `.tex` 新規作成前に `conventions/latex.md` を読まなかった。 CLAUDE.md table の「LaTeX」 entry は規約 file への pointer はあるが「いつ読むか」 (= 適用タイミング) の inline rule が無い。 機械化 (= hook 強化) で防げる範囲は強化したので、 reflex 規律追加は見送る (= `work-discipline.md` の 2026-04-17 教訓「規律を 1 つ増やすより hook 強化」 と整合)。

---



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

## PATH 管理: 二層防御の設計

Claude Code の Bash ツールは起動時に生成したシェルスナップショットを source する。スナップショットの `export PATH=...` がセッション中の PATH を決定するため、ここで PATH が壊れると全コマンドに影響する。

### 根本原因と第1層（.zprofile 修正）

**判断:** `.zprofile` から `brew shellenv` を削除し、PATH 設定を `~/.zshenv` に一元化。

**Why:** macOS login shell は `.zshenv` → `/etc/zprofile` → `~/.zprofile` の順に実行する。Homebrew の推奨設定（`eval "$(brew shellenv)"`）を `.zshenv` と `.zprofile` の両方に書くと、`.zprofile` 内の `path_helper`（`PATH_HELPER_ROOT="/opt/homebrew"` 付き）が `/opt/homebrew/etc/paths`（brew の bin/sbin のみ）から PATH を再構築し、`.zshenv` の if-blocks で追加した TeX・Python 等を消す。

`/etc/zprofile` の **system** `path_helper` は `/etc/paths.d/TeX` 等を読むので、login shell でも TeX は通る。`.zprofile` で再度 brew 版を呼ぶ必要はない。

**trade-off:** `.zshenv` は全 shell type で実行されるため、non-interactive shell でも brew が PATH に入る。これは Claude Code にとっては望ましい。Terminal.app のログインシェルでも問題なし。

### 第2層（スナップショット自動パッチ）

**判断:** launchd WatchPaths を採用。PreToolUse フックは棄却。

| 方式 | Bash オーバーヘッド | 仕組み |
|---|---|---|
| PreToolUse フック | ~0.05秒/回 | 毎 Bash 呼び出しで zsh を起動しパッチ済みか確認 |
| **launchd WatchPaths** | **0秒** | スナップショット生成をディレクトリ監視で検知、自動パッチ |

**Why:** スナップショットはセッション開始時に1回だけ生成される。修正も1回でいい。毎回の Bash 呼び出しでチェックするのは設計として間違い。zsh 起動コスト（~0.03秒）はスクリプト内の最適化では消せない。

**setup.sh への組み込み:** Step 2b で launchd plist を自動インストール（macOS のみ）。冪等性あり — 既にロード済みならスキップ。

### パッチスクリプトの設計: REQUIRED_PATHS 方式

**判断:** 固定 FULL_PATH の全置換ではなく、REQUIRED_PATHS リストによる不足検出・追加方式を採用。

**Why:**
1. **旧方式の脆弱性:** `grep 'export PATH=/usr/bin'` でマッチして `sed` で全置換していたが、Claude Code v2.1.87 でスナップショットの PATH 形式が変わり（先頭が `/usr/bin` ではなくなった）、パッチが効かなくなった。
2. **FULL_PATH のメンテナンス忘れ:** FULL_PATH に TeX を書き忘れていて、パッチ自体が不完全な PATH を上書きしていた。
3. **REQUIRED_PATHS 方式の利点:** 各エントリの実在チェック付きで不足分だけ追加するため、Claude Code の形式変更に耐性がある。既存の正しいエントリを壊さない。

**メンテナンスルール:** 新しいツールをインストールして PATH に追加する場合、`fix-snapshot-path-patch.sh` の REQUIRED_PATHS 配列を更新すること。

---

## 危険コマンドのブロック: deny ルール vs PreToolUse フック

**判断:** settings.json の deny ルールのみ。フックは不要。

**Why:**
1. deny ルールはフックより先に評価される。deny で拒否されたコマンドはフックに到達しない
2. つまりフックは常に死んだコードになる
3. 0.015秒/回のオーバーヘッドに見合う価値がない

当初 dangerous-commands-guard.sh を「二重防御」として残したが、deny ルールが先に評価される以上、フックが発火する状況は存在しない。背景は conventions/shell-env.md に文書化済みなので、スクリプトとして残す理由もない。削除した。

**deny ルールのパターン選定:**
- `Bash(*tccutil*)` — 広いパターンだが、Bash で tccutil に言及する正当な用途は全て Grep/Read ツールで代替可能。実害ゼロで最大安全性。

---

## ARCHITECTURE.md: 必須化せず任意ファイルに留める

**判断:** §2 の必須ファイル（CLAUDE.md / SESSION.md / DESIGN.md / .gitignore）は変更しない。ARCHITECTURE.md は §2 の「任意ファイル」サブセクションに 5 行で位置づける（作る基準・作らない場合・前例リンク）。

**Why:** 2026-04-06 に全 30 リポの CLAUDE.md を行数・コードファイル数・見出しで実地レビューした結果:

1. **適用範囲が狭い:** ARCHITECTURE.md が筋良く効くのは ~3-4 リポのみ（LorentzArena / mhlw-ec-pharmacy-finder / arxiv-digest など複数レイヤを持つコードリポ）。残り 26-27 リポは LaTeX 論文・記事・データ運用・薄いスクリプト集で、構造説明が CLAUDE.md の表 1 つに収まる。必須化すると形だけのファイルが量産され、[`docs/convention-design-principles.md` §3](docs/convention-design-principles.md#rule-addition-criteria)「過剰規約の害」と直接衝突する。
2. **CLAUDE.md 肥大化の救済策にならない:** 行数トップ群（300 行超 2 件、120-200 行 3 件）の見出しを精査すると、嵩を稼いでいるのは「動作プロトコル」「更新手順」「rotate チェックリスト」など**ランブック系**であって、構造説明ではない。ARCHITECTURE.md を切り出してもこれらは減らない。
3. **§2 役割定義との衝突:** CLAUDE.md の役割に「構造」が既に含まれている。ARCHITECTURE.md を必須化すると CLAUDE.md の役割定義を書き換える必要があり、既存 30 リポに波及する。
4. **実例不足:** 「ARCHITECTURE.md がなくて困った」事例は LorentzArena 1 件のみ。規約は実例から抽出するのが原則（`convention-design-principles.md` 冒頭）。1 サンプルでの規約化は早い。

**棄却した代替案:**
- *全リポ必須化:* 上記 1, 3 で却下
- *コードリポ限定で必須:* 「コードリポ」の判定基準（src/ の有無、ビルドコマンドの有無）が曖昧で揉める。CONVENTIONS の精神（機械的に適用できるルール）に合わない
- *§2 に何も書かず LorentzArena の個別最適に留める:* 同じ判断を別リポで再びするコストを避けるため、最低限の指針は明文化する

**作る基準の言語化:** 「コードリポで CLAUDE.md の構造説明が表 1 つに収まらず、ファイル名やクラス名から関係性が読み取れない場合」。否定形（作らない）も併記して、LaTeX/記事/データ運用リポで迷わないようにする。

---

## RUNBOOK 系ファイル: 規約化を待つ（実例先行）

**判断:** §2 に追加しない。`docs/runbook-*.md` 等の任意ファイル化も今は明文化しない。SESSION.md の残タスクとして「実例運用後に再検討」を残す。

**Why:** ARCHITECTURE.md の検討中に副産物として浮上した論点。CLAUDE.md 肥大化の真因がランブック系と判明したが、即規約化すべきではない:

1. **境界が曖昧:** データ運用リポの「一括更新手順」（150 行近いスクリプト群）、設定リポの secret rotate チェックリスト、multi-agent-shogun の Communication Protocol — これらは粒度・性質が大きく異なる。「ランブック」という単一概念で括れるか実例で確かめる必要がある。
2. **既に CLAUDE.md で動いている:** 上記はいずれも CLAUDE.md に書かれた状態で運用が回っている。困っているわけではない。先に規約を作ると「切り出すべきか否か」の再判断コストが発生する。
3. **ARCHITECTURE.md と同じ轍:** 1 サンプルでの規約化を避ける原則を、自分自身でもう一度踏んではいけない。実例 2-3 件で運用してから抽象化する。

**次の判断トリガー:** いずれかのリポで CLAUDE.md からランブックを切り出す具体的ニーズが出たとき（例: 一括更新手順が拡張されてさらに肥大化、または別端末からの実行で手順が壊れる事故）。そのとき DESIGN.md にこの欄を更新し、規約化判断を再開する。

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

## claude-config git history scrubbing (確定: 見送り 2026-04-06)

**判断**: 見送り。HEAD クリーン化で実用完了。

**核となる理由**: (1) HEAD は既にクリーンで public リポ訪問者は基本 HEAD のみ閲覧 → 実用安全性は確保済み、(2) GitHub cache / fork / archive.org / Wayback / Code Search index に既取り込み分は force-push でも消せず「完全秘匿」は達成不可、(3) force-push は安全規則 §5.3 で原則禁止、他端末 clone との不整合 / 外部参照リンク切れリスクもあり、リスクが利得 (HEAD 以外の閲覧経路遮断) を上回る。

**経緯**: 2026-04-06 に CONVENTIONS.md §2 から特定 private リポ名を削除。過去 commit には残存 (`git log -p CONVENTIONS.md` で特定可能)。

**再検討トリガー**:
- 文字列検索などで該当 private リポ名が外部から発見・言及された
- 「完全クリーン」への強い意向が新たに発生した

上記以外では検討しない (スコープ外)。手段選択肢 (`git filter-repo` / `filter-branch` / BFG) は再検討時に調査。

---

## CONVENTIONS.md / conventions/ 内の自己言及的 odakin 記述 (確定: 現状維持 2026-04-06)

**判断**: 現状維持。claude-config は odakin の流儀を public に展示するリポであり、odakin の例示は「private leak」ではなく「設計選択」。完全匿名化すると設計判断の why が伝わらず、private 化は公開目的と矛盾する。

**該当箇所** (drift 監視のため定期 re-grep 推奨):

| 場所 | 内容 | 意図 |
|---|---|---|
| `CONVENTIONS.md` L10 | `/Users/odakin/` をパス例として明示 | パス記述ルールの**反例**として使用 |
| `conventions/latex.md` L16-18 | JHEP.bst「個人的好み」、odakin-only 自動インストール | .bst が public リポ内にあるため由来を honest に記述 |
| `conventions/research-email.md` L41 | `assignee: odakin \| collaborator_id` 例示 | スキーマ説明の例示、匿名化すると意味が伝わらない |
| `conventions/scheduled-tasks.md` L58 | 「現運用者(odakin)の全マシン」 | パス hardcode を選んだ理由を honest に記述 |

**削除トリガー**: (1) odakin 以外の co-maintainer が増えた、(2) claude-config を template として使う他ユーザーが現れた (流儀の押し付けを避けたい)。以外は現状維持。

**Scope**: 上の表は `CONVENTIONS.md` と `conventions/*.md` (= **docs**) 内の意図的な odakin 記述のみ対象。`scripts/`, `hooks/`, `setup.sh` 等の実行可能コードは foreign user の machine で実行されるため、 odakin literal は categorically 不可 (= 「監視」 ではなく「禁止」、 layer-1 audience contract 違反になる)。実行コード内に `odakin-prefs/` 等の literal が混入していたら本表ではなく即修復対象。 由来: 2026-05-10 self-audit で `hooks/memory-guard*.sh` の deny message に `odakin-prefs/` literal が混入していたことを発見、 abstract化 (commit `60a58c0`)。 本表は「監視」 の言葉に騙されて執行コードのチェックを skip しないための scope marker を持つ。 5/10 後段で `scripts/{public-precommit-runner,audit-public-repos,setup-dropbox-refs}.sh` 計 13 箇所の同 class 違反も全て修復済 (= `scripts/lib/find-personal-layer.sh` 経路の動的解決へ移行、 § 「個人層検出 helper」 参照)。 さらに 5/10 最終段で `setup.sh` L863 の `SECRETS_REPOS` runtime hardcode (= 所属機関名を含む repo 名を array literal に直書き) + L738/L856 の同 class comment literal (別 class = 所属機関名 leak、 CLAUDE.md L105 違反) も個人層外出し方式で修復 (§「SECRETS_REPOS の個人層外出し」 参照)。 これで `claude-config/` の executable surface (`hooks/`, `scripts/`, `setup.sh`) は odakin / 機関名 literal-free を達成。

---

## DESIGN.md と EXPLORING.md の分離 (2026-04-06)

原則は [`docs/convention-design-principles.md §6`](docs/convention-design-principles.md#design-exploring-separation) に昇格済 (§7 の 3 分類 ACTIVE/DEFER/LESSON はこれを精緻化したもの)。初回適用: `LorentzArena/2+1/EXPLORING.md` 新設 (`88ed267`)、同日 orphan bullets を migrate (`cadf135`)。「他リポへの retroactive migration はしない」という適用方針も §6 に収録済。

---

## hooks/ の役割分担

| ファイル | 呼び出し元 | 役割 |
|---|---|---|
| memory-guard.sh | PreToolUse (Edit/Write) | メモリディレクトリへの書き込みを `permissionDecision=deny` でブロック。escape hatch: content に `<!-- machine-local: <理由> -->` marker（[`docs/convention-design-principles.md` §8.3](docs/convention-design-principles.md#precedent-as-training-data)/[§8.7](docs/convention-design-principles.md#mechanism-application-example)）。 deny message は layer-1 abstract (foreign user 対応、 個人層名は仮定しない) |
| memory-guard-bash.sh | PreToolUse (Bash) | Bash 経由のメモリ書き込みも同様に deny。escape hatch: command に `machine-local` 文字列。 deny message は layer-1 abstract |
| public-leak-guard.sh | PreToolUse (Edit/Write/MultiEdit) | `.claude/public-repo.marker` 付きリポへの書き込みを Tier A 構造制約 regex (email / abs_path / non-private IPv4 / token prefix / discord_mention) で scan、 hit 時 `ask`。 literal blocklist は持たない (= 公開して安全な hook、 literal 正本は personal layer の `sensitive-terms.txt` + pre-commit 層 `public-precommit-runner.sh` に分離) |
| google-url-guard.sh | PreToolUse (Edit/Write/MultiEdit/Bash) | Google URL の `/u/N/` パターン検出 + account-sensitive URL の `?authuser=<email>` 抜け検出 → `ask`。 placeholder URL (= path 末尾が `{...}` 等) は case glob で false positive を回避 |
| git-state-nudge.sh | PostToolUse (Bash) | 直近 60 秒以内の commit 未 push を検出して push 督促、 4h 以上ぶりの repo に入った時 first-sighting で `git fetch` (5s timeout) + dirty / ahead / behind 警告。 clean / in-sync な repo では完全 silent |
| fix-snapshot-path-patch.sh | launchd WatchPaths (Claude Code 外) | スナップショット PATH を REQUIRED_PATHS 方式で自動補完 (Bash に介入しない、 PATH 二層防御の第 2 層) |

PreToolUse Bash 系 hook は memory-guard-bash.sh と google-url-guard.sh の 2 つ。 いずれも silent pass の高速パスがあり (= jq 抽出で早期 exit、 google-url-guard は `google.com` / `googleapis.com` を含まなければ即 exit)、 平常時のオーバーヘッドは無視できる。

---

## SECRETS_REPOS の個人層外出し (2026-05-10)

**判断**: `setup.sh` Step 5d (= secrets symlink) で使う `SECRETS_REPOS` array (= secrets/ subdir を持つ git-crypt 暗号化 repo の一覧) を、 個人層の `<personal-layer>/secrets-repos.txt` から動的に読み取る方式に refactor。 `setup.sh` 内には特定 repo 名 literal を持たせない。

**Why**: もともと `setup.sh:863` で `SECRETS_REPOS=(secrets-config <organization-named repo>)` 相当の hardcode を持っていたが、 後者は所属機関名を含む repo 名 (CLAUDE.md L105 「所属機関名」 禁止) で claude-config (= public layer 1) に持たせては駄目な literal。 `secrets-config` は L101 allow-list 内だが org-named repo は別 class の leak。 単に削除すると odakin の運用が壊れる (= 該当 repo の secrets が symlink されなくなる) ため、 値の正本を個人層に移動して `setup.sh` は path 経由で読み取る mechanism 化。

**ファイル format**: 1 行 1 repo 名、 `#` 以降は行内 comment、 空行 / 末尾余白は awk で除去。 YAML / JSON ではなく plain text を採用した理由は (a) parser dependency 不要 (foreign user の machine で yq / jq の install 状態に依存しない)、 (b) inspect / 編集が単純、 (c) repo 名 list という用途に見合う最小 format。

**foreign user 対応**:
- 個人層なし or `secrets-repos.txt` 無しなら `SECRETS_REPOS=()` (= 空 array)
- 後段の `for SECRETS_REPO in "${SECRETS_REPOS[@]}"; do ... done` ループは空 array で 0 回実行 → secrets handling 全体が skip
- 既存 `~/.secrets/<name>` symlink は触られないため、 既存運用に regression なし

**棄却した代替案**:
- *array literal を残し comment で「foreign user は手で書き換える」 と注記*: 棄却。 setup.sh は `git pull` で update されるため、 foreign user の手書き変更が pull で上書きされる
- *YAML / JSON config に upgrade*: 棄却。 parser dependency 増、 plain text で十分
- *`SECRETS_REPOS` を完全削除して secrets handling 自体を撤去*: 棄却。 odakin の運用 (= 別 Mac での token rotate を `git-crypt` 経路で sync) が壊れる、 機能性自体は claude-config の価値ある提供物

**migration 順序**: 個人層に `secrets-repos.txt` を先に commit (= odakin-prefs commit `b62bb7d`)、 claude-config setup.sh refactor を後に commit。 逆順でも functional regression は無い (= setup.sh が file 不在を見たら skip するだけ、 既存 symlink 維持)。

**由来**: 2026-05-10 self-audit defer-完遂 phase の final cross-cutting sweep で発見。 `scripts/*` の修復 (= helper による動的解決) と同 class の問題だが、 `setup.sh` は claude-config の bootstrap で source 失敗の risk があるため `scripts/lib/find-personal-layer.sh` を source せず、 同等の dynamic read を `$LAYER` 変数 (= Step 5a で既に検出済) を再利用して inline で実装した。

---

## 個人層検出 helper (scripts/lib/find-personal-layer.sh) (2026-05-10)

**判断**: `setup.sh` Step 5a (= `.claude-personal-layer` marker file による個人層検出) と同じロジックを sourceable shell function `find_personal_layer` として `scripts/lib/find-personal-layer.sh` に extract、 layer-1 scripts (`public-precommit-runner.sh`, `audit-public-repos.sh`) から source して個人層 path を動的解決する。

**Why**: もともと layer-1 scripts は `SENSITIVE_TERMS="$HOME/Claude/<personal-layer>/sensitive-terms.txt"` のように特定個人層名を hardcode していて、 layer-1 audience contract (= layer 1 は特定の layer 3 名を仮定しない) に違反していた。 foreign user の machine では path が存在せず silent skip → leak detection の literal layer が機能不全になる。 abstract に書き換えるだけでは path lookup が成立しないため、 実際に個人層を動的検出する mechanism が必要。

**棄却した代替案**:
- *env var (`CLAUDE_PERSONAL_LAYER`) を `setup.sh` が export して script は env 経由で path 解決*: 棄却。 pre-commit hook (git が起動する子 process) や scheduled-task (cron 系 process) で env が継承されない経路がある。 Helper の self-contained 検出ならどこから呼ばれても動く
- *各 script で検出ロジックを inline 重複*: 棄却。 3 script 重複 + `setup.sh` = 4 箇所の同ロジック、 drift 確実
- *`setup.sh` 自身も helper を source して DRY 化*: 一旦見送り。 `setup.sh` は bootstrap script (= claude-config を新マシンに cold install するため初回起動時 source 失敗のリスクを最小化したい)、 self-contained に保つ。 helper 側に「`setup.sh` Step 5a と sync」 のコメント marker を置き、 どちらかが変わったら両方を sync する責務を編集者に明示

**Foreign user 対応**:
- 個人層を持たない claude-config 利用者では `find_personal_layer` は空文字列を返す
- 呼び出し側は `[ -n "$PERSONAL_LAYER" ]` チェックで graceful に skip
- 既存の `[ -f "$SENSITIVE_TERMS" ]` チェックも空文字列を「ファイルなし」 として扱うため、 既存 control flow を破壊しない (= odakin の既存運用にも影響なし、 dry-run で同 path に解決することを 2026-05-10 に検証)

**由来**: 2026-05-10 self-audit で memory-guard hooks の同 class 違反を発見・修復 (commit `60a58c0`) した後、 final cross-cutting sweep で `scripts/*` にも 13 箇所の同 class 違反 (= `個人層の sensitive-terms.txt` / `個人層の leak-incidents.md` の hardcode) を追加発見、 hooks のように abstract 文面では逃げられない (= path lookup が必要) ため mechanism 化で全 closure。

---

## dropbox-refs convention: per-repo symlink + personal-layer registry (2026-04-07)

### What

複数の git リポから「Dropbox の特定フォルダにある共同 PDF」を、リポ内の安定した相対 path (`./dropbox-refs/`) で参照する規約。詳細は `conventions/dropbox-refs.md`。

### Why (ここに書く最小限)

- Dropbox の install 場所が OS / Dropbox バージョン / multi-account 構成で違う
- subpath は user 固有 (collaborator ごとに Dropbox 内の階層が違う可能性)
- 共有リポに絶対パスや user 固有 subpath を書くと共同編集者の環境で壊れる
- 同パターンを複数の共同研究で再利用したい

### 検討した代替案と却下理由

| 案 | 内容 | 却下理由 |
|---|---|---|
| (A) 各リポに setup.sh を持たせて `~/Dropbox` 固定で symlink | 実装最小 | `~/Dropbox` 固定が壊れるユーザー環境 (macOS Sonoma+ CloudStorage、business アカウント、Linux) でフェイル |
| (B) global mount: `~/Claude/.dropbox -> $DBROOT` を 1 本作る | symlink 1 本で済み、registry 不要 | サブフォルダ rename 時に各リポの参照を grep 修正する必要、ASCII clean な canonical 名を経由できない |
| (C) env var `$DROPBOX` をシェルで定義してドキュメントに書く | OS-agnostic | TeX や file manager は env var を展開しない、tilde-expansion のほうが互換性高い |
| (D) Git LFS で PDF をリポに入れる | クローンするだけで PDF 入手 | LFS quota、PDF が repo 履歴に固定、共同編集者の LFS install 必須 |
| **(E, 採用) per-repo symlink + personal-layer registry** | リポ root に gitignored `dropbox-refs/` symlink、registry は personal layer に YAML で持つ | 各案の欠点を回避、TeX や relative path も動く、whole-repo Dropbox パターンと自然に共存 |

### 設計判断の小項目

- **registry format: YAML**（vs TSV）: 当初 TSV を提案したが、ユーザー要望で YAML に変更。理由は (1) 拡張性（将来 description / provider / tags 等を追加可能）、(2) 構造化が自然、(3) PyYAML が macOS / Linux で簡単に手に入る。代償は PyYAML 依存だが convention doc §3.2 で明記
- **registry の置き場: personal layer**（vs 各リポ / claude-config）: subpath は user 固有なので shared/public に置けない。personal layer は per-user / cross-machine な Dropbox layout を表現できる唯一の層
- **mount point name: visible `dropbox-refs/`**（vs hidden `.refs/`、global `~/Claude/.dropbox`）: ユーザー要望で visible。リポ内に置くことで ASCII 名 + `~` 展開不要 + relative path で参照できる
- **trigger: claude-config setup.sh + personal-layer post-merge hook**（vs SessionStart hook、手動）: SessionStart hook は claude-config DESIGN.md の既存判断 (UI notification ノイズで削除済み) と矛盾するので避けた。手動だと忘れる。setup.sh + post-merge は idempotent + git pull の自然な拡張
- **post-merge hook: tagged で常に refresh**（vs 一度 install したら触らない）: layer 移動や script 場所変更で hook 内の絶対 path が古くなる問題を防ぐため。tagged ("managed-by:" マーカー) hook は claude-config が所有しているので再書き込みは安全。tag が無い hook はユーザー手書きとして保護
- **dropbox-root.sh の resolution chain**: `$DROPBOX_ROOT` → `~/.dropbox/info.json` (`personal` → `business`) → `~/Dropbox` → `~/Library/CloudStorage/Dropbox` → `~/Library/CloudStorage/Dropbox-Personal`。最初は環境変数 override を許し、次に Dropbox 公式の info.json (最も authoritative)、最後に既知の install 場所。非 Dropbox cloud に移行する場合はこの resolver を別のものに差し替える

### 副次的な migration: 既存 whole-repo Dropbox リポの脱 Dropbox-symlink (同日、途中で revert)

新 dropbox-refs 規約の導入と同時に、ある既存リポを whole-repo Dropbox パターン (`~/Claude/<repo>` が Dropbox folder への symlink、以下 **Pattern A**) から独立 git clone + `dropbox-refs/` 参照型 (**Pattern B**) に移行する作業も実施した。旧 Dropbox 側の `.git/` は削除して asset folder 化、新 clone から `./dropbox-refs/` 経由で sibling フォルダ群 (参照 PDF・notebook 等) を参照する形に統一。

**同日夕に Pattern A へ revert**。理由:

- 移行後に作業ツリー (`~/Claude/<repo>/`) と asset folder (旧 Dropbox working tree) に、7 つの source ファイル (本文 tex、bib、bst、build output pdf、図、検証 script、メモ) が丸ごと duplicate する状態が発生した。`cp -r` 相当で作業ツリーを seed したときに asset folder 側の source を消さなかったため
- duplicate 自体は一方を消せば解消するが、**リポ固有の事情: 共同編集者とは git push/pull 経由のみ** (Dropbox folder は共有していない)。この場合 Dropbox 内の `.git/` を multi-machine が同時に触る可能性が無く、Pattern A 採用上の主要リスク (Dropbox 同期が `.git/` を破壊する事故) が発生しない
- Pattern A のほうが source と asset が同じディレクトリに同居でき、`./foo.pdf` や `../sibling/` の素朴な相対 path で全部触れる。`dropbox-refs/` symlink の layer が消えるぶん mental model が簡単

この経験から、dropbox-refs convention は **「どちらを選ぶか」の決定基準を明示**する必要があると判明。`conventions/dropbox-refs.md` の冒頭に Pattern A vs B の選択ガイドを追加した。

### Pattern A vs B の決定基準 (2026-04-07 夕 追加)

| 条件 | 推奨 | 根拠 |
|---|---|---|
| 共同編集者と Dropbox folder を共有し、複数 machine で同時に `.git/` を触る可能性あり | **B** | Dropbox 同期 race が `.git/` object store を壊すリスクが実在 |
| リポが multi-machine で同時編集される (solo でもラップトップ + デスクトップ併用等) | **B** | 同上 |
| 共同編集者はいるが git push/pull 経由のみ (Dropbox folder は share しない)、かつ同時編集マシンは実質 1 台 | **A** | Dropbox 同期 race が発生しえないので A のほうが単純 |
| solo 運用、Dropbox は単に自分の素材置き場 | **A** | 同上 |
| リポが arXiv cite だけで完結 (Dropbox の参照 PDF を触らない) | **どちらでもない** | 普通に `<base>/<repo>` に clone すれば十分 |

**Trade-off の本質**: Pattern B は `.git/` を Dropbox の外に出すことで同期 race を根本的に排除する代わりに、source と asset の場所が分離して dropbox-refs symlink という layer が増える。Pattern A は layer が少ないが Dropbox 同期が `.git/` を触る前提になる — 複数 machine が同じ `.git/` を同時に書くと壊れるので、同時編集の有無が分水嶺。

**migration の落とし穴**: B → A に revert する際は、(i) `.git/` を Dropbox tree にコピーしたあと `git checkout -- .gitignore .gitattributes ...` で deleted tracked files を復元する、(ii) `dropbox-refs/` symlink と `.gitignore` の `/dropbox-refs` 行を削除する、(iii) `personal-layer/dropbox-collabs.yaml` から対応 entry を削除する、の 3 点をまとめて実行する。A → B の手順は dropbox-refs.md §3.4 参照。

## git-state-nudge.sh: cross-session WIP leakage の検出 — STALE_DIRT (2026-04-08)

### What

`hooks/git-state-nudge.sh` の case (3) (first-sighting) に **STALE_DIRT** という新しい dirty signal を追加した。発火条件は「`git status --porcelain` の出力 (= 「dirty file の集合」を表す文字列) を sha1 化したものが、前回観測時から **24 時間以上不変**」。発火すると次の 1 行が emit される:

```
- N dirty file(s), unchanged set for ~Mh — possibly abandoned WIP from an earlier session
```

per-hash NUDGED guard (`$STATE_DIR/$REPO_HASH.stale-nudged`) で、同一 dirty set への repeat 警告は抑制される。working tree が clean になれば両 state file を破棄して各 dirty episode を independent に扱う。

### Why

2026-04-07 夜の noise 削減で case (3) から `DIRTY_COUNT > 0` 句を **完全削除**したため、AHEAD/BEHIND の無い純粋な dirty 状態は素通りする hole が生じていた。2026-04-08 朝の手動 sweep で、この hole から 2 件の cross-session WIP leakage が漏れていたことが発覚:

- **arxiv-digest**: 2026-04-02 〜 04-08 の 6 日分の cron 自動生成 archive json が uncommitted のまま蓄積 (15 ファイル)
- **私的 LaTeX 論文 repo (private)**: 04-07 の editing session (.tex/.pdf/.yaml、3 ファイル) が約 24h uncommitted。実態は人為編集 leakage

これらは「divergence」でも「直近 commit の未 push」でもなく、**前 session が dirty 状態を残したまま終了し、次 session でも誰も気付かない**という独立した failure mode。push-workflow.md の「セッション冒頭の sync 確認」「作業単位ごとの commit+push」は人間規律レベルの対策で、cron 由来の蓄積や Claude の取りこぼしには弱い。自動検知の safety net が必要。

### 検討した代替案と却下理由

| 案 | 内容 | 却下理由 |
|---|---|---|
| (A) 04-07 削除前の DIRTY_COUNT > 0 をそのまま復活 | 1 行修正 | 04-07 に「ノイズが多すぎる」として削除されたばかり。active WIP のたびに鳴る問題が再発する |
| (B) 「最新 mtime > Nh」(newest mtime semantic) | dirty file 中で最も新しい mtime が古ければ stale | **build artifact rebuild に騙される**。古い `.tex` を pdflatex で rebuild すると `.pdf` の mtime が "fresh" になり、本当に stale な `.tex` が見えなくなる (今回検出した人為編集 leakage の `.tex` + `.pdf` ペアがちょうどこの形) |
| (C) 「最古 mtime > Nh」(oldest mtime semantic) | dirty file 中で最も古い mtime が閾値超えなら stale | active な multi-day refactor (古い + 新しい dirt が混在) と「古い編集 + 新しい build artifact」(これは warn したい) を区別できない。両方とも「最古 mtime が古い」になる |
| (D) 朝の health check scheduled task | cron で全 repo を `git status` 走査して報告 | 04-07 夜の cross-machine incident postmortem で **既に却下済み** (時間ベース、重い、既存 hook の first-sighting fetch と重複)。今回もこの理由は変わらない |
| (E) PostToolUse matcher を Read/Edit/Write にも拡張 | hook 発火頻度を上げる | 04-07 夜に既に却下 (typical workflow が Bash 主体、marginal value 小、overhead 累積) |
| (F) per-repo opt-out marker (`.no-stale-warn`) | scratch repo を除外 | 現状そんな repo が無く、YAGNI。per-hash NUDGED guard で実用上は十分静か |
| (G) hook 内で自動 commit してしまう | 検知だけでなく自動修復 | 自動 commit は意図のわからない変更を git history に流し込む。生成主体側で commit するべき (cf. 「Generator owns commit」原則、下記) |
| **(H, 採用) 「porcelain hash の age > 24h」** | dirty set そのものが string レベルで何時間不変かを測る | mtime 系の失敗 mode を全て回避。active 編集は dirty set を mutate するので hash が変わり age がリセット (= 元の noise 抑制が保たれる)、abandoned WIP は hash 不変 → age 蓄積 → 警告 |

### 設計判断の小項目

- **シグナルが mtime ではなく porcelain hash の age**: file 内容の rewrite に強い。本質的には「dirty 状態が文字列レベルで何時間 invariant か」を測っている。文字列の不変性は file content の不変性と独立しており、build artifact rebuild (内容 rewrite だが porcelain 行は同じ) も backup tool の touch も hash には影響しない
- **age の累積方法: state file の mtime を使う**: PORCELAIN_FILE は hash が変わったときだけ書き直す (mtime 更新)。同じ hash を観測したときは file を touch しない → mtime が「初回観測時刻」のままに保たれる → `NOW - mtime` が age になる。time stamp を file の中に書く方式 (cross-platform `touch -d` の可搬性問題を避けるため) と同等の semantic だがより簡素
- **threshold: 24h**: 同一日内のセッション中断 (lunch/打合せ) を false positive にせず、「翌日まで持ち越した」を catch する自然な区切り。6h や 12h は long workday で false positive が増える、72h は abandonment を catch するのが遅すぎる
- **per-hash NUDGED guard**: HEAD-sha NUDGED guard (case 1, 2 用) と同じ思想を porcelain hash に適用。一度警告を出した dirty set には repeat しない。意図的に長期 dirty を残す scratch 運用 (今は無いが将来発生したとき) に対する低コストの noise 抑制
- **clean になったら state を破棄**: PORCELAIN_FILE と STALE_NUDGED_FILE 両方を `rm -f`。各 dirty episode を independent に扱うことで、(i) 過去に warn した hash が偶然再発生したときに沈黙させない、(ii) state file の累積を防ぐ
- **`shasum` / `sha1sum` fallback**: 既存 REPO_HASH 計算 (line 102-108) と同じ pattern。macOS は shasum、Linux は sha1sum、Windows Git Bash は両方。両方無いと PORCELAIN_HASH が空になり STALE_DIRT 検出は静かに無効化される (壊れず劣化)
- **case (1) ORPHAN_TREE / case (2) RECENT_COMMIT との priority**: STALE_DIRT は case (3) 内なので case (1)(2) より低 priority。orphan-tree や直近 commit が未 push な repo はそちらが先に発火する。case (1)(2) は return 0 で抜けるので、その session では STALE_DIRT は出ない (次回 first-sighting で出るチャンスを得る)。意味的には正しい priority (重大度: orphan > 直近未 push > 古い WIP)

### Bootstrap caveat (deliberate trade-off)

porcelain hash の age は **「初回観測時刻」を起点に始まる**。デプロイ時点で既に存在する dirty 状態は、この feature が初めて観測した瞬間に age 0 から始まるので、本当は 1 週間放置されてた dirt でも 24h 経過しないと警告されない。

mtime fallback で「初回観測時の oldest dirty mtime を bootstrap timestamp にする」という補正案も検討したが、

- mtime 系のシグナルを部分的にでも使うと案 (B)(C) の失敗 mode が部分的に再現する
- そもそも今回の sweep で全 repo を clean にしたので bootstrap 時に warn すべき dirt は存在しない
- 将来同様の事故が起きても 24h で catch されるので影響は限定的

として bootstrap 補正は **入れない** ことにした。code header と push-workflow.md に caveat を明記。

### 副次的な「Narrower-but-active > absent」原則

04-07 夜の DIRTY_COUNT > 0 削除は「シグナルがノイズすぎる」が理由だったが、04-08 で明らかになったのは **「ノイズなシグナルを削除すると、本来 catch したかった signal も一緒に失われる」** という当然の事実。

正しい対処は「削除」ではなく「**criterion を狭める**」: ノイズ要因を分析して、それを排除する narrower な criterion を見つける。今回は:

- 元のシグナル: `DIRTY_COUNT > 0`
- ノイズ要因: 「今書いてる active WIP が毎回鳴る」
- 区別したかった signal: 「abandoned, cross-session WIP」
- narrower criterion: 「dirty set が time-window 不変 (= 誰も触っていない) AND time-window > 1 日」

これは hook design 全般に適用できる原則として記録しておく価値がある。signal を消す前に「ノイズと本当に取りたい signal を区別する narrower criterion はないか」を必ず検討する。1 データポイントなのでまだ generalization としては弱いが、もう 1 件似たケースが出たら convention-design-principles.md に格上げを検討。

### Event-driven vs time-driven safety net

04-07 で却下した「朝の health check scheduled task」と STALE_DIRT は **似て非なるもの**:

| 軸 | 朝の health check | STALE_DIRT |
|---|---|---|
| 起動 | cron (時間ベース、ユーザー不在時も走る) | PostToolUse hook (Claude が Bash 叩いた瞬間) |
| 走査範囲 | 全 repo 一括 | cwd repo (+ literal `git -C <path>`) のみ |
| 副作用 | 報告生成 / SESSION.md 更新 / Claude 起動 | stdout 1 行を Claude session に inject |
| 重さ | 重い (全 repo `git status`) | 軽い (1-2 repo) |
| 精度 | high recall (全部見る) | event 駆動なので「触った repo だけ」に絞られる (low overhead) |
| 棄却理由 | 時間ベース、重い、既存 first-sighting fetch と重複 | 該当しない (event 駆動、軽い、first-sighting と協調) |

cron 系の安全網が却下されたからといって、event-driven な検出も自動的に却下されるわけではない。今後似た議論が出たときは「時間 vs event」の軸を最初に切り分けること。

### 関連 fix と responsibility split

STALE_DIRT は **汎用 safety net**。各 repo の root cause level の対処は別途必要:

- **arxiv-digest**: cron 自動生成の蓄積は STALE_DIRT で catch されるが、それは「警告」止まり。ファイルは依然 dirty。根治は arxiv-digest 側の `commit_archives_to_git()` (`src/archive.py`、commit b8f1539) で「生成主体が commit 主体」原則を実装した。STALE_DIRT は cron 系の generator にバグが残ったときの fail-safe として機能する
- **人為編集 leakage (上記私的 LaTeX 論文 repo の事例)**: generator がいないので STALE_DIRT が一義的な safety net。push-workflow.md の「TodoWrite で commit ステップを明示」も補完する人間規律レイヤー

責任分担の原則: **「自動で生成されるもの」は生成主体が commit 責任を持つ。「人間が編集するもの」は人間規律 + STALE_DIRT で catch する**。前者を後者に押し込むと永遠に dirty が累積する (今回の arxiv-digest が exactly そのパターンだった)。

関連 commit:
- `5ddd43f` (claude-config): STALE_DIRT 実装本体
- `b8f1539` (arxiv-digest): generator 側の root cause 対処
- `4257d0f` (odakin-prefs): push-workflow.md の `[git-nudge]` 警告 interpretation guide

### 検討事項: principles.md への昇格候補 (defer 中、再発時に再判定)

今回の STALE_DIRT 関連作業で、いくつか「hook / ルール設計に一般化できそうな原則」が副産物として浮上した。いずれも **1 データポイントなので即昇格は YAGNI**、再発する 2 件目が出たら `docs/convention-design-principles.md` への格上げを判断する。それまで以下に defer する。

1. **Narrower-but-active > absent**: 「シグナルがノイズ」だからといって signal そのものを削除すると、本来 catch したかった signal も失う。正しい対処は criterion を狭めること — ノイズ要因を分析して排除する narrower な criterion を見つける。今回の DIRTY_COUNT → STALE_DIRT 移行が 1 データポイント。§「副次的な『Narrower-but-active > absent』原則」参照。**un-defer トリガー**: 他の hook / 規約で「ノイズを理由に削除 → 実は必要だった」の事例が 1 件発生。

2. **Generator owns commit**: 「自動で生成されるもの (cron / scheduled task / script の出力) は、生成主体が commit 責任を持つ」。分離すると dirty が累積する。arxiv-digest の `commit_archives_to_git()` 設計が 1 データポイント (arxiv-digest DESIGN.md に詳述)。**un-defer トリガー**: 他の scheduled task や cron script で同じ「生成するだけで commit しない」パターンが 1 件発生、または新規 scheduled task 作成時の設計指針として active に参照された。

3. **Event-driven vs time-driven safety net**: 「時間ベース (cron) の safety net が却下されたからといって、event-driven (hook) な検出も自動的に却下されるわけではない」。2 つの軸を最初に切り分けること。morning health check 却下 (04-07) → STALE_DIRT 採用 (04-08) が対照的な 1 データポイント。§「Event-driven vs time-driven safety net」参照。**un-defer トリガー**: 「朝の cron で X する」と「hook で X する」の選択が再度議論になった時。**昇格候補として最も strong** (既に具体的比較表がある)。

4. **Multi-commit workflow checkpoint**: 個別 commit 時点の 4 軸チェックは不十分で、**複数 commit にまたがる multi-step work の完了後にもう一度横断的な 4 軸 sweep が必要**。今回の 04-08 作業 (8 ファイル / 6 commit の cross-repo work) で、個別 commit 時の check は通過したつもりだったが、横断 sweep で 5 件の issue (うち 1 件は public-safety 違反) が発覚 (commit 24a7f16 で修正)。
   - **un-defer トリガー**: 次の multi-commit cross-repo work (3 リポ以上 / 5 commit 以上) の完了時に横断 sweep を再度実施し、同じく複数 issue が発覚した場合、principles.md に「multi-commit workflow checkpoint」節を新設する。1 件なら偶発、2 件なら pattern。
   - **暫定 workaround**: 当面は本 DESIGN.md のこの注記を reminder として扱い、multi-commit work の終わりに自分 (Claude) が横断 sweep を実行する習慣を意識的に作る。ユーザーが明示的に指示しなくても、cross-repo work 後は自発的に `grep -rn "private-repo-name-a\|private-repo-name-b"` 等を走らせる。

---

## 公開リポ leak 防止: 構造制約 hook + pre-commit ephemeral literal check

**状態**: 2026-04-09〜10 に 5 セッションで実装完了。受容 leak の記録は
`個人層の leak-incidents.md`。将来課題 (段階 3 + 3-3 純粋化) は
`個人層の next-steps.md`。

### 契機
2026-04-09、LorentzArena (public) の 5 ファイル 16 行に、組織環境を
暗示する間接表現 (`<wifi_term>` 系) が複数セッションに渡って累積して
いたのを user 指摘で発見、`ae25604` で一般化して修正した。Claude は
drafting 中にも push 前にも catch しておらず、既存の指示層
(`個人層の work-network.md` の「公開リポで組織名を書かない」
ルール) は reliably トリガーが引けないと判明した。`memory-guard.sh`
(§「メモリ書き込みガード」) と `git-state-nudge.sh` (§「git-state-nudge.sh: cross-session WIP leakage の検出」)
で既に確立している「指示 → hook 化」の pattern upgrade を、leak 防止
にも適用する。

### 採用した設計: 2 層 hook + 情報配置の分離
1. **PreToolUse hook** (`public-leak-guard.sh`) — Tier A 構造制約
   regex のみ (email / `/Users/...` / IPv4 / token prefix)。literal
   blocklist は乗せない。`sensitive-repo-patterns.ja.md §3-3`
   「構造制約の設計思想」を純粋に適用する層
2. **pre-commit hook** (`public-precommit-runner.sh`) — 同じ Tier A
   regex に加えて、`個人層の sensitive-terms.txt` が存在すれば
   **ephemeral に load** して staged diff に literal check をかける。
   script 本体には literal が埋め込まれない構造分離が核心
3. **audit** (`audit-public-repos.sh`) — 週次で全 public repo を sweep、
   Tier A + sensitive-terms.txt の両方を適用して retroactive 検出
4. **情報配置の分離 (段階 1)** — `個人層の work-network.md` の
   組織名 literal を `sensitive-terms.txt` (gitignore + network-notes
   git-crypt symlink) に分離、本文は placeholder 化。odakin-prefs が万一 leak
   しても sensitive literal が git に乗っていない状態にする

判定単位は **各 public repo の `.claude/public-repo.marker`** 一本。
hook の日常 fast path はこれだけ見る。`gh repo list --visibility public`
との突合は `setup.sh` と audit script の 2 点でのみ行う (遡及検出)。

### 棄却した代替案

**案 A: 3 tier blacklist (deny/ask/hint) PreToolUse hook**
初案。blocklist.yaml に組織名・private repo 名・間接 context leak の
具体語 (以下 `<ctx_term>`) を列挙し、PreToolUse で ask。`sensitive-repo-patterns.ja.md §3-3` の
直接批判と衝突:
- (a) メンテナンスが要る
- (b) **blacklist 自体が leak 源になる**
- (c) 新しい固有名詞に追随できない

特に (b) は重大。hook script 本体に literal を埋め込むと script source
が leak 源になる。odakin-prefs の yaml に置いても、同 repo が万一
公開化されれば meta-leak。**却下**。

**案 B: pure 3-3 (Tier A regex のみ、literal check を一切持たない)**
§3-3 の純粋適用。PreToolUse も pre-commit も構造制約 regex だけ。
但し LorentzArena 型の間接 context leak (一般日本語で暗に環境を特定
する表現、具体例は sensitive-terms.txt 側にのみ保持) は regex で
捕捉不能。audit による事後検出
のみに頼ることになり、「既に push された後に気付く」状態が恒常化する。
Tier A を完璧にしても、現実の事例類型に対する防御が致命的に薄い。
**却下**。

**案 C (採用): 中間解 — pre-commit で literal を ephemeral load**
`§3-3` の最重要批判 (b)「blacklist 自体が leak 源」は構造分離 (hook
本体 = logic only / data = gitignore 済み separate file) で回避できる
点に気付いた。具体的には:
- hook **本体** には literal を埋め込まない (script source は
  claude-config の public に置いても literal leak しない)
- literal **data** は `個人層の sensitive-terms.txt` (gitignore +
  network-notes git-crypt symlink)、hook 実行時に読んで終了時に unload
- PreToolUse 層には literal を持ち込まない (3-3 純粋を維持)
- pre-commit 層に限って ephemeral load を許す (stage 済み diff のみ
  scan、`--no-verify` で bypass 可能)
- 残る批判 (a) メンテ要・(c) 新固有名詞追随不可 は運用で許容:
  `leak-incidents.md` を事例ログとして保持し、`§5-1` の「forcing
  functions は 3 回で投入」判断の材料にする

**案 D: attention banner (各 public repo CLAUDE.md 冒頭に忌避語リスト)**
Claude drafting 中の attention layer に短い blocklist を置く案。hook
enforcement ではなく指示層の補強。user 判断で **不採用**。理由: 各
public repo に同じ banner を貼る保守コスト、collaborator/reader が
見る場所に個人 attention layer を乗せる違和感、指示層は前回失敗
(work-network.md を Claude が参照しなかった) の再来リスク。

**案 E: odakin-prefs 全体を git-crypt 化**
sensitive literal の meta-leak risk を暗号化で覆う案。却下。§3-3 の
思想は「暗号化で守る」ではなく「漏らせないものを平文側に置かない」
(§1-2「公開面のフルリストを持つ」)。odakin-prefs 全体暗号化は
chicken-and-egg (setup.sh が odakin-prefs を参照、unlock 前に起動
不可) と現在の混在 (sensitive + non-sensitive) の固定化という 2 つの
問題がある。段階 1 (`work-network.md` の literal だけを gitignore 済み
sensitive-terms.txt に分離) で当面の risk は大きく下がる。段階 2-3
(他 sensitive ファイルの分離、or 完全分離新 repo) は `next-steps.md`
に切り出して別議論。

### 副次的な設計判断

**public/private 判定: marker file 一本** — `個人層の public-repos.yaml`
一本化や `gh repo view` 自動判定とも比較した。各 repo の visibility
は各 repo 固有の情報 ([`docs/convention-design-principles.md §1`](docs/convention-design-principles.md#placement-by-scope) 配置原則の
「影響範囲の最大公約数」)、正本は repo 自身にあるべき。marker 付け
忘れによる false negative は audit script の missing marker 検出と
`setup.sh` の 2 点で補う。日常 hook は marker 1 ファイルのみ見る
軽量 fast path。

**既存 leak の扱い: force push しない** — CONVENTIONS §5 item 3 と
整合。新規 leak は hook で 100% 防ぐ (Tier A) / commit gate で止める
(中間解) 方針にし、古い git log に残る既存 leak は受容。`leak-incidents.md`
に判断を記録。例外: 認証情報、または push 1 時間以内の個人識別情報。

**Tier A regex の 3 ファイル重複** — `public-leak-guard.sh` (PreToolUse)
/ `public-precommit-runner.sh` (pre-commit) / `audit-public-repos.sh`
(audit) に同じ 4 regex + allowlist が独立に定義されている。
[`docs/convention-design-principles.md §2`](docs/convention-design-principles.md#no-duplicate-rules) (定義は 1 箇所) に技術的に
違反するが、以下の理由で現状維持:
(1) 3 ファイルの実行コンテキストが完全に独立 (Claude hook stdin /
git diff / git grep)。共通 source file への extract は shell
portability と debugging 容易性のリスクが利得を上回る。
(2) Tier A regex 自体は安定 (email / path / ipv4 / token prefix)
で変更頻度が極めて低い。変更時は 3 ファイルを同時更新する。

**実装順序: 5 セッション分割** — `sensitive-repo-patterns.ja.md §5-2`
「新規ルールと既存違反の同日 sweep」は同日完結を推奨するが、今回は
step 数が多いので「1 セッション = 1 論理単位」で分割し、各セッション
内で (新規 rule + 当該 scope の sweep + fix) を 1 セットに保つ形に
組み替えた (進行管理に使った一時文書 `docs/leak-prevention-plan.md`
は実装完了後に削除済み)。

### `sensitive-repo-patterns.ja.md §3-3` との整合関係 (重要)

本設計は §3-3 に正面衝突しない。§3-3 の批判 (b)「blacklist 自体が
leak 源」の真の対象は **hook script の source に literal を埋め込む
行為** であって、「literal を外部 data file として持つこと」では
ない。ただし外部 data file を script から参照する場合、(1) data file
が物理的に公開領域に置かれていないこと、(2) script の public な
source から data file の中身が推測できないこと、の 2 条件を満たす
必要がある。本設計では (1) は gitignore、(2) は script 本体が
「ファイルが存在すれば load」と汎用的に書かれていて中身のヒントを
出さないことで満たしている。

§3-3 の批判 (a)(c) は解消されていない:
- (a) メンテナンス要: 認める。年数回の更新で足りる想定
- (c) 新固有名詞追随不可: 認める。`leak-incidents.md` を事例ログと
  して運用し、3 回以上類似事例が発生したら forcing function 強化を
  再検討する

この trade-off を明示したうえで中間解を採用した。将来 §3-3 の思想を
より純粋に適用したくなった場合の un-defer トリガーは `next-steps.md`
にも記載。

### 実装成果物 (2026-04-09〜10、5 セッション)

| ファイル | 場所 | 役割 |
|---|---|---|
| `hooks/public-leak-guard.sh` | claude-config | PreToolUse hook — Tier A regex (email/path/ipv4/token) |
| `scripts/public-precommit-runner.sh` | claude-config | pre-commit runner — Tier A + sensitive-terms.txt ephemeral |
| `scripts/install-public-precommit.sh` | claude-config | pre-commit stub を各 public repo に冪等設置 |
| `scripts/audit-public-repos.sh` | claude-config | 定期 audit — `gh repo list` + marker 突合 + Tier A + literal |
| `.claude/public-repo.marker` | 各 public repo (12 repo) | hook の visibility oracle |
| `gitignore_global` (修正) | claude-config | `.claude/*` + `!.claude/public-repo.marker` exception |
| `setup.sh` Step 2 (修正) | claude-config | hook symlink + settings.json merge に leak guard 追加 |
| `setup.sh` Step 8 (新規) | claude-config | marker 持ち repo に pre-commit install + missing marker 警告 |
| `sensitive-terms.txt` | odakin-prefs (gitignore, network-notes git-crypt symlink) | literal 正本 (9 entries: 組織名 3 + 間接 context 4 + 部門名 1 + collaborator 名 1。TWCU は研究略称として公開使用 OK と判断し 2026-04-10 に除外) |
| `work-network.md` (修正) | odakin-prefs | 組織名 literal → `<workplace>` placeholder 化 |
| `leak-incidents.md` | odakin-prefs | 事例記録 (α/β/γ/δ/ε 類型 + 3 回ルール counter) |
| `next-steps.md` | odakin-prefs | 段階 2-3 の情報配置分離 defer + un-defer トリガー |
| scheduled-task `public-repo-leak-audit-weekly` | ~/.claude/scheduled-tasks/ | 毎週月曜 09:23 に audit-public-repos.sh 実行 |

検証: PreToolUse hook 11 ケース test matrix + pre-commit runner 10 ケース test matrix + LorentzArena in-situ literal catch 確認 + audit 初回実行 (12 repo, missing markers 0)。

### 2026-04-14 追補: meta-locator と abstract-proposal 段階の未カバー領域

本設計の 2 層 hook は **値 (literal) に対する検出** として完成しているが、
β 類型 (対処フェーズで記録に pointer を残す 2 次 leak) の 2 件目発生で、
現設計が **meta-locator** と **abstract-proposal 段階** の 2 軸で
カバーを持たないことが明確になった。記録目的で整理する (構造対策の
投入判定は β counter 3 件目まで保留)。

**meta-locator (値でなく locator である情報):**
暗号化 backup の置き場所名、命名規則、`.enc` / `.key` 等の拡張子と
位置の組合せ、特定サブパス、rotation 頻度など。値そのものではないので
Tier A 構造制約 regex では発火しない。attacker の検索空間を桁で削る
効果を持つ意味で、値と同等の扱いが必要。配置は pre-commit 層の
sensitive-terms.txt 管轄 (ephemeral load 原則維持)。ただし `webhook` /
`backup` / `.enc` 等は一般技術用語で、普遍語を sensitive-terms に
入れると false positive が急増するトレードオフがある。閾値到達時
(β 3 件目) に導入形態を検討。候補: (i) sensitive-terms を 2 段化し
「literal (固有名詞) / pattern (一般技術用語の近傍 context)」を分離、
(ii) Tier B として新設、literal-free 原則との整合を再定義。

**abstract-proposal 段階 (チャット層の提案):**
現 hook は PreToolUse = Write/Edit で発火。Claude が chat で「TODO と
して SESSION.md に書きましょうか」と **提案** した段階では発火しない。
user が catch しない限り次 turn で Write に昇格する経路で、実害
(git に literal が乗る) は Write 段階で確定するので、hook は実害防止
としては機能する。ただし「ツール実行前に proposal を止める」仕組みは
現アーキで構造的に不可能 (assistant text generation に対する pre-hook
は存在しない)。対策は 2 方向:

- (a) **canonical routing の先置き**: 話題に入る時点で正準保管先を
  presented する (例: 読み込み必須テーブル経由で private な canonical
  store を強制 read させる)。「どこに書くか」の生成時 reflex の出力先
  を物理的に狭める方が、禁則 gate で事後ブロックするより予防的に強い
- (b) **Write/Edit 層の maximal catch**: chat で流れた proposal が
  実書き込みに到達した瞬間を確実に止める。既存 hook + 将来の
  meta-locator 対応で埋める

**失敗の時間軸分類 (観察):**
β 2 件目は β 1 件目の修正時に新規規律 (public SESSION に PII pointer
書かない) を昇格させた **直後** に同型を繰り返した。ルール articulation
(文章化) と application (生成時適用) が別プロセスで、articulation 直後
こそ application が緩む構造が観察された。本 DESIGN としては **prose
追加 (規律層) を重ねても application 失敗は埋まらない** ことを前提に、
構造対策 (routing + hook) の投入判定だけを forcing function 3 回
ルールで管理する。prose 追加の衝動は「やった感」の即時報酬と
trade-off にあり、mechanism 投入コストとの比較で後者を選ぶ。

### 2026-04-28 追補: pre-commit extension hook (repo-local 規律の chain)

**契機**: mhlw-ec-pharmacy-finder で `install-public-precommit.sh` の
1 行 stub が、既存の repo-specific pre-commit (placeholder 検出 +
docs↔SESSION.md 同期警告) を上書きしてしまった (2026-04-23)。leak
gate (Tier A/B) は repo 横断で同一だが、repo 固有の commit 規律
(placeholder 形式・review 必須ファイル等) は repo ごとに違う。

**設計**: stub は触らず、`public-precommit-runner.sh` 側に optional
chain を追加。leak gate を pass した時点で
`<repo_root>/.claude/pre-commit-extra.sh` が executable なら call +
exit で chain (exit code 透過)。`exec` ではなく call にしているのは、
bash の `exec` が EXIT trap (runner が `$ADDED_BUF` の cleanup に使う)
を skip するため — tempfile leak を避けるため親 shell に戻して trap を
発火させる。

利点:
1. **stub の冪等性を保つ**: install-public-precommit.sh は STUB_MARKER
   (`public-precommit-runner.sh`) で stub を識別して上書きするので、
   stub 側に repo 固有 logic を埋めると次回 install 時に消える。
   extension は stub の外 (= runner の chain) に逃がすことで、stub
   は最小のまま再生成可能を維持。
2. **extension は opt-in**: ファイルが無い repo は behavior 変化なし。
   12 既存 public repo の hook chain は不変。
3. **配置の一貫性**: marker (`.claude/public-repo.marker`) と同じ
   `.claude/` 直下に置く。`scripts/hooks/` は `core.hooksPath` の
   entry point なので非 hook ファイルを混ぜない。

**実装**: `public-precommit-runner.sh` の最終 `exit 0` の直前に
`git rev-parse --show-toplevel` で repo root を取り、
`$REPO_ROOT/.claude/pre-commit-extra.sh` が `-x` なら呼び出し、戻り値
で exit。chain された extension が `exit 1` すれば commit が reject
されるのは leak gate と同じ挙動。

**初回投入先**: mhlw-ec-pharmacy-finder の
`.claude/pre-commit-extra.sh` に旧 hook の placeholder 検出 +
docs↔SESSION.md 警告を移設。本機能の動作確認も兼ねた。

**extension 作成ガイド** (新しい public repo に extension を入れる時):

1. `chmod +x .claude/pre-commit-extra.sh`。non-executable は runner が
   skip する。
2. **gitignore exception**: `.claude/*` は gitignore_global で ignore
   され、`!.claude/pre-commit-extra.sh` は同 global に登録済 (commit
   8efeaac)。各 repo が独自 `.gitignore` で `.claude/*` を再宣言
   している場合 (現状: 数 repo) は、その local `.gitignore` にも同じ
   exception を追加する必要がある。`git check-ignore -v` で確認可。
3. **self-collision 回避**: extension が grep / regex で pattern を検出
   する場合、その pattern 文字列は extension 自身の source に出現する
   ため、pathspec exclude (`':(exclude).claude/pre-commit-extra.sh'`)
   で自分を除外しないと自身の commit が self-block する。mhlw の例
   参照。
4. **テスト**: stage に該当 pattern の fixture を仕込んで
   `~/Claude/claude-config/scripts/public-precommit-runner.sh` を直接
   実行 (commit を打たずに hook chain だけ走らせられる)。`git reset
   HEAD <fixture>` で stage を巻き戻す。
5. **stub には触らない**: `install-public-precommit.sh` の冪等性は
   stub-only 前提 (STUB_MARKER で識別して上書き)。repo 固有 logic を
   stub に埋めると次回 install 時に消える。

### 関連文書
- `docs/sensitive-repo-patterns.ja.md` — 設計思想の出所 (§3-3, §5-1, §5-2)
- `個人層の leak-incidents.md` — 受容 leak の記録と類型判断
- `個人層の next-steps.md` — 段階 2-3 の分離計画と un-defer トリガー
- `個人層の DESIGN.md §2026-04-14` — articulation→application gap と prose 追加バイアスの同定 (本追補の認知側対応)
- `conventions/shared-repo.md §公開前 Audit` — 旧来の人間 audit 手順 (本設計で hook 化)

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

## sensitive-terms.txt の symlink architecture (2026-05-14 追補)

個人層 (= layer 3) の `sensitive-terms.txt` は **gitignore** 対象で、 個人層 repo 本体に commit しない。 これは literal の正本を切り離すため (= `sensitive-repo-patterns.ja.md §3-3` の「blacklist 自体が leak 源」 批判への対応)。 実体は **git-crypt 化された別 repo** (= 個人層と並列に存在する layer 3 の sensitive repo) に置き、 そこへ symlink で参照する。

**現状の運用 architecture**:

```
個人層の sensitive-terms.txt     →  ../<sensitive-repo>/sensitive-terms.txt
  (gitignored、 symlink only)            (git-crypt encrypted、 layer 3 repo)
```

`public-precommit-runner.sh` は `lib/find-personal-layer.sh` で layer 3 を動的解決 → `$PERSONAL_LAYER/sensitive-terms.txt` を read。 symlink で透過的に sensitive repo 側 plaintext を参照する。

### symlink target の選択肢と判断

選択肢:
- (a) `<sensitive-repo>/sensitive-terms.txt` (= git-crypt repo 内、 cross-machine sync は git pull)
- (b) Dropbox 等の cloud sync folder 内 (= sync 経由、 git-crypt 不要)

(a) を採用。 (a) の利点:
- single source of truth (= git で履歴管理 + git-crypt で encrypted)
- cloud sync の状態に依存しない (= 一部マシンで Dropbox folder が selective-sync 除外されていると symlink が切れる)
- 学術 / 企業環境では cloud sync 利用が制限される場合あり、 git-crypt は universal

**(b) 経路で発生した過去事故 (2026-05-14)**: 職場マシンで symlink target が cloud sync folder にあったが、 当該 folder が selective-sync で除外されていたため symlink が**壊れていた**。 結果 `[ -f $SENSITIVE_TERMS ]` が false → tier-b literal check が silent に **完全 skip**。 同日 commit で公開 repo の `office-automation.md` に ε 識別子を leak した際、 tier-b は disabled で catch せず commit が通った。 commit 直後の 4 軸 self-sweep (= `CLAUDE.md §10 + §13`) で発見、 5 min 以内に修復 commit (= placeholder 化)。 同セッション内で symlink を (a) sensitive-repo 直接参照に変更し、 tier-b が再び active に。

### setup の依存順序

setup.sh で git-crypt unlock が **symlink を貼る前 (or 同時)** に走る必要がある (= unlock 前に symlink を参照しても read できない = silent skip)。 現 `setup.sh` Step 10 で git-crypt unlock があり、 symlink は個人層 (= layer 3) の bootstrap 時に作成されるので順序は OK。 ただし foreign user (= 個人層なし) は symlink も sensitive-terms も持たないので tier-b は skip (= 設計通り、 layer-1 audience contract 維持)。

### 検証手順 (新マシン setup 後)

```bash
# 1. symlink が壊れていないか
file <personal-layer>/sensitive-terms.txt    # → "symbolic link to ..."
ls -L <personal-layer>/sensitive-terms.txt   # 中身が読めることを確認

# 2. tier-b check が active か (= public repo で test commit)
cd /tmp && mkdir -p test-sens/.claude && cd test-sens
git init && touch .claude/public-repo.marker
<claude-config>/scripts/install-public-precommit.sh .
echo "<sensitive-literal>" > test.md && git add test.md
git commit -m "test"     # → 期待: tier-b で reject
```

### 関連事故 / 規律

- 2026-05-14 leak (= ε 3 件目、 forcing function 閾値到達): 個人層 `leak-incidents.md` に詳細
- setup.sh post-merge での symlink 自動 verify は未実装 (= 将来 enhancement、 `scripts/setup-dropbox-refs.sh` と同様の pattern で `scripts/setup-sensitive-terms.sh` を作る案あり)

## 2026-05-18: PDF Read tool fallback hook 設計判断

### 起点 = 2 連続失敗の RCA

2026-05-18 朝、 別 Claude session が個人層の private research repo plan ファイルでの議論中に arXiv preprint PDF を Read tool で読もうとして `Error: pdftoppm is not installed` で fail (= Intel Mac の Tier 2 で poppler の bottle 不在 + source build 失敗 という既知パターン)、 arXiv HTML v1 に lazy substitution → HTML v1 の section 構造から別 group の review と誤 attribution → 真は research paper で別著者 chain (= arXiv ID 自体は public、 攻撃面なし) で 1〜2 hour の議論が誤前提で進行。 個人層で規律化 (= 個人層 CLAUDE.md の PDF-read-fallback 規律 + work-discipline.md §「PDF Read tool error...」 + memory `reference_install_failures.md` の poppler entry に代替経路試行順序)。

同日後続セッションで第二事例: CosmoVerse PDF (24 MB) を Read tool fail → 「Wolfram で完全に賄える」 と発話 + PyMuPDF / sips 試行 skip + 即 Mathematica で PDF text 抽出を実行。 Mathematica 実行自体は valid だったが、 規律された default 経路 (= PyMuPDF) を skip して別 valid path に jump した = 規律順守 reflex の gap。 旧 wording 「arXiv HTML への lazy substitution」 を別セッションが arXiv HTML specific と reflex 解釈、 「Wolfram への substitution は別 issue」 と読まれた。

これは「規律 wording の reflex 解釈に依存する」 設計の脆弱性を実証 = **規律 commit のみでは不十分、 機械的 enforcement layer が必要**。

### 設計選択

**選択**: `claude-config/hooks/pdf-read-fallback-nudge.sh` を新規追加 (= layer 1、 universal 規律)、 `PostToolUse` の `matcher: "Read"` で hook、 stdin JSON の `.tool_input.file_path` (= `.pdf` 拡張子) + 全体 stdin に `pdftoppm is not installed` を含む条件で発火、 system reminder で PyMuPDF 1-liner を injection。

**logic**:
1. stdin JSON parse (jq 必須、 git-state-nudge.sh と同パターン)
2. file_path が `.pdf` (case-insensitive) かつ stdin 全体に `pdftoppm is not installed` を含む → 発火条件成立
3. `python3 -c 'import fitz'` で PyMuPDF 利用可能性を probe
4. PyMuPDF 利用可能 → `python3 -c "import fitz; doc = fitz.open('<escaped-path>'); print(doc.metadata, doc.page_count); print(doc[0].get_text()[:500])"` の 1-liner を system reminder で emit
5. PyMuPDF 利用不可 → `pip3 install --user pymupdf` の install hint + `sips` fallback hint を emit
6. system reminder には arXiv HTML 代替の絶対条件 (= 版一致 + PyMuPDF metadata で attribution cross-check) も併記

**Always exit 0**: 情報的 nudge であってブロックではない (= `permissionDecision: ask` は使わない、 既に Read tool が fail した後の事後 nudge)。

**stateless**: state file 持たず per-call 完結。 何度発火しても同じ message。

**silent 条件** (= false positive 防止):
- jq / stdin 不在 (hook 環境不在)
- `.pdf` 拡張子無し
- pdftoppm 失敗 marker 不在 (= 別 error)
- python3 不在 (= PyMuPDF も install できない環境)

### 4 層モデル上の位置付け

hook 本体 (script + settings.json schema) = **layer 1** (claude-config、 全 Claude Code ユーザー)。 「Read tool が PDF を pdftoppm で render する設計」 と「PyMuPDF が独立 path として valid」 は universal fact、 layer 1 で書ける。 ただし activation 自体は machine 環境依存:
- PyMuPDF が install されていれば 1-liner が動く
- PyMuPDF が install されていなければ install hint を emit
- python3 が無ければ silent (= 発火条件不成立)

これは layer 1 の「universal 規律 + machine 環境への conditional 反応」 という mixed pattern で、 既存 hook (= `expensive-tmp-guard.sh` が Audiveris / oemer 等の存在を probe するのと同型) と整合。

### 規律 wording との併用設計

規律本体 (= 個人層 CLAUDE.md の PDF-read-fallback 規律 + work-discipline.md §「PDF Read tool error を別経路への lazy substitution で覆い隠さない」 + memory poppler entry) は **wording-level の reflex 起動**、 hook は **mechanical enforcement layer**。 2 重 (規律 + hook) で reflex の癖に依存しない設計。 加えて当該規律の冒頭 1 行を command-form punchy 化 (= 2026-05-18 同日 commit) して reflex 起動の起点を最短化、 これと hook の system reminder の wording を一致 (= 「`python3 -c "import fitz; ..."` を 1 回」) させて、 Claude が「規律で読んだ 1-liner」 = 「hook が injection した 1-liner」 と認識できるよう設計。

### 既知の limitation

- PyMuPDF が image-only PDF (= scanned) で text empty を返した場合は sips PNG 化に fallback、 sips も無ければ Claude が手動で別経路を探す必要 (= 規律本体に書いてある)
- hook は `pdftoppm is not installed` symptom に依存。 別 PDF read failure mode (= PDF corrupt、 access denied 等) には発火しない (= 他 path で対応)
- python3 path が PATH に無い環境 (= virtualenv 未 activate 等) で `command -v python3` が fail する場合は silent。 false negative。 setup.sh の PATH 二層防御で `/usr/bin/python3` が常に見える前提

### 検証手順

```bash
# 1. hook script の手動 test (= stdin JSON 渡しで 3 scenarios)
echo '{"tool_input":{"file_path":"/path/foo.pdf"},"tool_response":{"error":"Error: pdftoppm is not installed."}}' \
  | ~/.claude/hooks/pdf-read-fallback-nudge.sh
# → system reminder emit を確認 (exit 0)

echo '{"tool_input":{"file_path":"/tmp/foo.md"},"tool_response":{"error":"x"}}' \
  | ~/.claude/hooks/pdf-read-fallback-nudge.sh
# → silent (exit 0)

# 2. settings.json に entry 登録済か
jq '.hooks.PostToolUse[] | select(.hooks[]?.command | contains("pdf-read-fallback-nudge"))' \
  ~/.claude/settings.json
# → entry 1 件返る

# 3. 実 Read tool で fail を再現して hook 発火を観察 (= 次セッションで)
# Read tool で .pdf を読む → fail → 次 turn の context に system reminder が
# inject されているか確認
```

### 関連事故 / 規律

- 2026-05-18 朝 arXiv preprint attribution 誤同定 RCA: 個人層 research repo の関連 plan + 個人層 work-discipline.md §「PDF Read tool error を別経路への lazy substitution で覆い隠さない」 + 個人層 CLAUDE.md の PDF-read-fallback 規律
- 2026-05-18 同日後続 Wolfram lazy substitution (= 第二事例): 同 plan の対応 sub-section + メタ層 RCA (= 規律を書く Claude も §16「context 構築での単一情報源 null 結論飛躍」 を起こす)
