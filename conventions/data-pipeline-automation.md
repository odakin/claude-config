<!-- doc-meta
when: 下流自動化 (build / mirror / template render) を伴うデータ管理をするとき
category: infra
summary: データ単一ソース化・forward-only schema migration・judgment-required placeholder pattern・script input validation・自動化機構の validity 検証 (= reproduce by script) を bundle
-->
# データ pipeline と半自動化の設計規律

下流自動化 (= build script / mirror script / template render) を伴うデータ管理で適用。 CLAUDE.md から参照: `~/Claude/claude-config/conventions/data-pipeline-automation.md`

ポスター・告知メール・web ミラー等を 1 source から自動生成する pipeline を構築するとき、 schema 不在期や judgment-required content の取り扱いで体系的な失敗が発生する。 本 convention はその回避規律を集約する。

---

## <a id="single-source-of-truth"></a>1. データの単一ソース化 (= soft duplication 回避)

### 規律

**同じ事実を複数の file に書かない。 1 つの正本 (source of truth) を決め、 他は正本から render / transfer で生成する。**

例: ポスターの題名・概要・写真は **`<DB>.yaml` の field を正本**にし、 ポスター固有 yaml には title / abstract / photo を書かない (= 二重管理になり、 片方更新時に drift)。

### Why

- 同じ情報が 2 箇所に書かれると、 片方を update し忘れて drift する (= 体系的バグ源)
- 修正対象が増えると review コストが上がる
- 「どちらが正しい?」 の判断責務が user/Claude に転嫁される

### How to apply

- pipeline 設計時、 「この情報の単一正本はどこか?」 を最初に決定 (= schema 化)
- 下流の render / transfer は正本から **読むだけ** (write back しない)
- field の欠落が発覚したら正本に追加、 下流の重複は削除

### Pattern: schema 不在は下流自動化開始時に発覚する

schema 不在は **正本としての必要性が発覚する瞬間** = 下流自動化を始めた時に最も顕在化する。 例: ポスター生成 script を書こうとして始めて「abstract の正本がない」 と気付く。 これは正常な発見プロセス。 自動化を後回しにすると schema 不在も先送りになる (= log のような自由テキストに埋もれて構造化されない)。

「自動化要件は schema を厳密化する圧力」 として歓迎すべきで、 既存 free-text 運用を維持して「自動化は手間だから後で」 と先送りすると、 結果的に整合性管理コストが累積する。

### Pattern: SoT invariant は生成経路でなく経路非依存 gate で enforce

SoT の不変条件 (= 重複なし / uniqueness / schema 準拠) を、 それを生成する正規経路 (= 専用 add コマンド / 生成 script) の中の guard だけで守ろうとすると、 **別経路 (= file の手動編集 / 別ツール) からの違反をすり抜ける**。 guard は「最も楽な正規経路」 に置きがちだが、 invariant の本当の境界は「SoT file が変わる瞬間 = commit」 にある。

- 例: reference DB の add コマンドに「重複追加を防ぐ」 check を入れても、 file を手で直接編集して重複行を加えると add の check は走らない (= check は add 経由のみ)。 同じ check を pre-commit hook に置けば、 編集経路に依らず commit 時に必ず走る。
- reflex: invariant を enforce する時「この gate は **全経路** を cover するか、 特定経路だけか?」 を問う。 add-path guard は UX 的補助 (= 早期 feedback)、 commit gate が真の防御線。 両方あると best (= 早期 + 確実)。
- 検出が破壊的修復を伴う場合 (= 重複 merge 等) は、 gate は **report mode (= block のみ)** を default にし、 修復は明示 flag (`--fix` 等) で人間が確認してから実行 (= 無人で SoT を改変しない)。

### Pattern: SoT の home が lifecycle で移動するなら resolver + consumer redirect

正本を 1 つに決める (§1) だけでなく、 **正本の home が lifecycle で移動する**設計 (= draft 期は file A が正本、 publish 後は file B が正本 = 「publish 境界で move」、 [personal-layer.md](../docs/personal-layer.md) §「Owner automation acting on a shared project」 の partition / promotion は MOVE) では、 move 設計時に **その field を読む全 consumer を grep で洗い出し**、 home-resolution を 1 箇所に閉じ込めた **共有 resolver** 経由に redirect する。

- **落とし穴**: 「この field を読むのは publish 経路だけ」 と暗黙仮定して move/prune すると、 **publish 後に走る別 consumer** (= poster 生成・告知メール・過去 archive 移行 等) が壊れる。 move/prune を設計した瞬間に「この field の consumer は他に無いか?」 を grep で verify (= CLAUDE.md inline §3 の「assertion 前に consumer/referent を verify」)。 consumer 列挙を省くと「web publish だけが consumer」 という誤前提のまま prune して下流を壊す (実例 2026-06-09: candidates の title/abstract を poster/告知/archive の 3 経路も読んでいた)。
- **resolver**: `resolve(item)` = item が `published:<key>` を持てば新 home から、 無ければ item 自身から title 等を返す (= 公開済→新 home / 未公開→旧 home、 どの瞬間も home は 1 箇所 = single-SoT 維持)。解決ロジックを各 consumer に複製しない (= 複製 = 複数 home の smell、 §1 の dedup 思想を「読み手側」 に適用)。
- **field-scoped prune**: prune するのは新 home に移った field だけ。 移っていない field (= photo / 連絡先 / pipeline status 等) は旧 file に残し resolver も触らない。
- cross-repo read (= consumer が別 repo の新 home を読む) は層依存が合法な範囲で OK (= 依存先が同等以上に public な層、 owner script → 共有 repo 等)。

### Pattern: 生成物に焼き込んだ marker は snapshot であって live state でない

生成時にファイル名・本文へ焼き込んだ状態 marker (= 「要押印」 「draft」 「提出用」 等) は **作った瞬間の snapshot** で、 その後の進行を反映しない。 これを live state と誤読すると **済んだものが未済として残り続ける** (= drift)。

- **症状の型**: ファイル名 `提出用_…_要押印.pdf` を「要押印か」 の判定に使うと、 押印・提出が済んでも marker は変わらず、 提出済みが「要押印」 として surface し続ける (= 2026-06 提出書類一覧で、 ファイル名 marker だけ見て提出済みを誤掲載 + 当日締切分を見落とした)。
- **規律**: 「今どうか」 の判定は **live SoT** (= task の status field 等、 人が更新する 1 箇所) を権威にし、 焼き込み marker は飾り扱い。 「持っていく書類はどれか」 等の一覧は **手書きリストを別途持たず、 live SoT (status/期限) と実ファイルを呼び出し時に join して導出する派生 view** にする (= §1 の単一ソース化 + lifecycle resolver と同思想。 一覧を別 file で持つと SoT 二重化して必ず drift)。
- **副次**: 「手で 1 個ずつ探して開く」 ような痛い機械的作業は、 痛みを感じた時点で **決定論 script 化** する (= 派生 view + `--open` 等)。 機械的・再現可能なのにモデルが毎回探索する形は malformed/低速にも弱い ([`tool-call-robustness.md`](tool-call-robustness.md))。

---

## <a id="forward-only-migration"></a>2. forward-only schema migration

### 規律

**既存データを backfill しない、 次に touch する機会に新 schema へ refactor する。**

schema を拡張する時 (= 例: 候補 DB の新規 field 追加)、 既存全エントリを一気に backfill すると:

- 古い情報が不完全に転記される (= 内容欠落・判定ミス)
- 巨大な diff になり review 不能
- backfill 中の判断ミスは静かに drift する

代わりに **forward-only**: 既存 entry は触らず、 次に該当 entry を edit する機会 (= status 遷移、 update、 重要 event) で新 schema に refactor。

### How to apply

- 新 schema を確立 + 1 件 (= 当面必要な entry) のみに適用
- CLAUDE.md / DESIGN.md に「forward-only migration」 と明記 (= 将来の touch 時規律)
- 旧 schema と新 schema が **混在期** であることを許容 (= yaml で人間/Claude 両方読める = clean migration よりも safe)
- 一括 backfill task は「将来 TODO」 として明示記録、 ただし優先度低 (= forward-only で漸進的に解消される)

---

## <a id="judgment-required-placeholder"></a>3. judgment-required content の placeholder pattern

### 規律

**AI が generate できない content (= judgment、 trust、 文体判断) は script 出力に placeholder marker を残し、 user が手で埋める。 完全自動化を無理に追求しない。**

例: 告知メールの「学生向け平易紹介」 段落は AI 初稿可能だが judgment required (= 文体 + 内容 reformulation + 親しみ度合い)。 script は `{{intro_paragraph}}` placeholder を残して draft 出力 → user が edit → 完成版を yaml field に保存 (= 次回 reproduce 可能)。

### How to apply

- script 出力に **placeholder marker** を残す (= 「`{{var: 説明}}` をここに」 形式で user に hint)
- placeholder が残っていれば script は **stderr で警告** (= 「<field> 未指定 → placeholder のまま出力」)
- 完成版を yaml field に保存 (= 次回再生成時に reproduce)

### Pattern: AI 初稿 → user edit → save back to source

完全手書き > 半自動 (= AI 初稿 + user edit) > 完全自動。 judgment required は半自動止まりで OK、 むしろ judgment を user に残す方が drift 防止に効く。

完成版を yaml field に **save back** すると、 次回類似 case で参照可能 + script で reproduce 検証可能 (下記 §5)。

---

## <a id="script-input-validation"></a>4. script 入力の検証 (= input validation)

### 規律

**user input (= argparse 引数、 環境変数、 file path) は format を regex で validate、 不正値は explicit error で止める。 silent fallback しない。**

特に **filesystem path を構築する input** は path traversal を防ぐため strict validate。

```python
if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z][a-z-]*$", args.seminar_id):
    sys.exit(f"❌ seminar_id 不正: {args.seminar_id!r}")
```

### How to apply

- input 形式が固定 ID 系なら regex で validate
- pattern mismatch は `sys.exit` で early stop (= silent fallback で repo 外書き出しを防ぐ)
- error message に **期待 format と実際の値** を含める (= user が修正 hint を得る)

### Pattern: 必須 field 欠落も同様

データ正本に必須 field が欠落しているなら同じく explicit error:

```python
if not (candidate.get("title") or {}).get("ja"):
    sys.exit(f"❌ title.ja 不足、 candidates.yaml に転記が必要")
```

silent fallback (= `TBA` で render) は drift を隠す。 「データが揃ってないなら script は止まる」 が筋。

### Pattern: build → publish の責務分離

local build (= PDF/.tex 生成) と external publish (= 別リポへ mirror、 PDF copy) は別 script に分ける。 publish script は build 済 artifact の存在を前提に動き、 不在なら explicit error。 1 script に統合すると失敗時の責務切り分けが難しくなる。

---

## <a id="automation-validity-check"></a>5. 自動化機構の validity 検証

### 規律

**自動化 script を作ったら、 過去の手書き出力 (= user 承認済) を script で reproduce して完全一致を確認する。 mismatch があれば script の bug or 手書き drift。**

### How to apply

- 過去 user 承認済の出力 (= 送信済メール / 過去ポスター 等) を 1 件選ぶ
- その出力の input 条件 (= yaml field、 投稿日 等) を script の input に与える
- 出力を diff、 0 件なら validity 確認 ✓
- 差分があれば:
  - script の output format / template の bug を修正
  - or 過去手書きが流儀から drift していた (= 流儀を明文化する契機)

### Why

自動化機構を作っただけでは「動く」 が「正しい」 とは限らない。 過去手書き出力との完全一致は最も強い validity 証明 (= 「人間の OK judgement を script が再現できる」 = trust の根拠)。

### Pattern: judgment-required content の save back と validity 検証は相補

§3 の「完成版を yaml field に save back」 と §5 の「過去手書き出力を script で reproduce」 は同じ運用の表裏。 完成 content を yaml に保存 → script で再生成 → 完全一致確認 → 「次回類似 case で script を信頼して使える」 と確証。

---

## <a id="reminder-over-side-effect"></a>6. 副作用つき自動 edit よりも reminder 出力

### 規律

**script が複数 file を update する責務を持つとき、 yaml への自動 edit (= round-trip 問題で comment / 整形が壊れる) よりも、 標準出力に reminder を print して手動更新を user に任せる方が clean。**

例: ミラー script が下流リポに file を生成・copy するのは OK、 上流 yaml への「mirrored_to」 field の自動追加は yaml round-trip で壊れる → 「下記 block を yaml に追記してください」 と stdout に print。

### Why

- yaml の round-trip は library 依存 (= ruamel.yaml 等)、 PyYAML だけだと comment が消える
- idempotency 維持が複雑化 (= 既存 field との merge、 ordering)
- user が確認できる surface に出す方が trust できる

### How to apply

- 副作用は「生成 / copy / delete」 等の coarse-grained action に限定
- fine-grained yaml field 編集は print reminder で user に任せる
- script 終了前に「変更されてない方の file」 と「user が手で update する内容」 を明示

---

## <a id="autonomous-execution-gate"></a>7. 無人実行 (autonomous / scheduled) の gate

### 規律

**pipeline を cron/launchd 等で無人実行し、 結果を不可逆/外部な行き先 (= 共有・公開 repo への commit+push、 送信、 publish) に自動反映するなら、 §3 の「user が手で埋める / review する」 という run-time の人間 in-loop が無い。 そこで自動反映してよいのは「出力が入力の純粋な関数 = 推測ゼロ」 の変換だけ。 導出不能な field は (a) 人間が SoT に事前入力する (= その入力が「その item を publish してよい」 という per-item 認可になる) か、 (b) surface して人手に委ねる、 または (c) LLM-in-loop が **grounded に**自動完成する (= 翻訳 / 出典つき retrieval、 下記 subsection)。 いずれにせよ placeholder や **推測 (guess)** を外部/公開 state に push しない (= grounded な自動完成は guess ではない)。**

run-time に人間が居る半自動 (§3) では placeholder を出力に残して後で埋めればよい。 無人実行ではその猶予が無く、 placeholder/推測がそのまま公開面に焼き付く。 だから「武装 (armed)」 ゲートを設ける: **導出不能 field が SoT に揃った item だけ自動 publish、 揃わない item は surface のみ。**

### Why

- 無人実行 = 出力を誰も run-time に見ない → 誤りが公開面に直行する
- 「推測で埋める」 は不確実性を隠す assertion (= 出力が「確定情報」 に見えてしまう)。 機械翻訳した固有名詞 (例: 所属の英語表記) は典型的に誤る (= 公式名 vs 直訳)
- 人間が「導出不能な 1 field」 を埋める行為を per-item authorization に転用すると、 judgment は人間に残しつつ機械的組立ては自動化できる (= §3 の半自動を無人文脈に持ち込む橋)

### How to apply

- field を「導出可能 (= SoT の純関数)」 と「導出不能 (= 判断/翻訳/外部知識が要る)」 に分類
- 導出可能 field だけで full に組み立てられ、 かつ導出不能 field が SoT に**明示済**の item を「armed」 と判定 → 自動 publish
- armed でない item は surface (= 「この 1 field を埋めれば次回自動 publish」 と hint)、 **絶対に推測で埋めない**
- 「全 item を強制 armed 化する kill switch を false に」 等の全面手動 fallback も用意 (= 異常時の退避)
- 自動 publish した内容は事後に必ず通知 / log / git log で可視化 (= 無人でも誤 publish に早く気付ける)

### Pattern: LLM-in-loop での SoT 自動完成 (= 境界は「機械 vs 人間」 ではなく「grounded vs guessed」)

「導出不能 field は人間が埋める」 (上記 (a)) は唯一の道ではない。 **LLM を run-time に噛ませれば、 一部の「導出不能」 field は人間なしで autonomously 完成できる — ただし完成が grounded である限り**。 境界は「機械が触るか」 ではなく「**根拠があるか (grounded) / 推測か (guessed)**」:

- **翻訳 (= 与えられた content の ja→en 等)**: faithful な翻訳は「事実の推測」 ではなく「与えられた content の変換」。 LLM が SoT に自動充填してよい (+ review marker)。
- **固有名詞 / 外部事実 (= 所属の公式英語名 等)**: 翻訳すると誤る (= 直訳 ≠ 公式名) が、 真の値は **retrievable** (= その機関の公式サイトを web-search)。 **出典つきの grounded retrieval は guess ではない** → LLM が web-search で実在値を取り SoT に充填 (+ 出典 URL + review marker)。
- **content も出典も無い純粋な事実** → やはり surface / 人手 (= blind-guess は禁止)。

つまり「推測で埋めない」 規律は守ったまま、 **grounded な自動完成 (翻訳 + retrieval) を LLM 層に足す**ことで人間 pre-fill すら不要にできる。 これで「全 item 自動 publish」 が成立する (= armed ゲートが「人間が 1 field 埋めた item」 から「LLM が grounded に埋めた item」 に広がる)。

適用上の規律:
- **run-time に LLM が要る** → 機構は LLM-in-loop な定期実行 (= [`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection)「Claude judgment 要 → scheduled task」)。 純 deterministic 層 (= mirror) と LLM 層 (= 翻訳/retrieval で SoT 完成) を分離し、 LLM 層は SoT を埋めるだけ・公開生成は deterministic 層が行う (= テスト可能性 + 翻訳/retrieval を SoT に残してレビュー可能)
- **人間提供値を最優先**: 既に人間が入れた値 (= 非 TBA) は LLM で上書きしない
- **auto-completed には review marker を付け、 即ライブ + 早期レビュー** (= 公開を止めない代わりに、 通知 + drift 検出器で「自動生成・要目視」 を surface し人間が数日内に微修正)
- **retrieved fact には出典を残す** (= 後で検証可能、 grounded であることの証跡)
- それでも grounded に解決できない field は TBA で ja-first 公開 + flag (= block より degrade、 「不確実性を expose」 する側)

### Pattern: 高 stakes な無人 publish は pre-push の fresh-eyes adversarial 検証ゲートを足す

上の grounded 自動完成 + 決定的 mirror は「即 publish + review marker + 事後レビュー」 (= 公開を止めない) が default。 だが **build 通過は構造しか保証せず、 意味的誤りは素通し**する (= 翻訳の hallucination / 固有名詞の捏造 / 文字化け / 壊れた画像 — grounded retrieval でも外し得る)。 不可逆・公開・無人が重なる **stakes の高い外部チャネル** (= 公開サイト等) には、 push の手前に **AI 検証ゲート**を足すと defense-in-depth になる:

- 決定的生成 → build → **local commit (`--no-push`)** → **AI が生成物 (diff + 描画結果) を明示レビュー** → clean なら push、 疑わしい item は hold + surface (= clean だけ push、 1 件の疑義で全体を止めない =「極力自動化、 例外だけ人手」)。
- ⚠️ **fresh-eyes + adversarial 必須**: 同じ run が生成して同じ run がレビューすると自分の仕事を承認する rubber-stamp になる。 **別呼び出し** (= sub-agent / 別ターン cold 評価) で「**正しいか**でなく**間違いを探せ・疑わしきは hold**」 と framing (= deep-research / code-review の独立検証パスを自動化に持ち込む)。
- checklist 例: 翻訳が原文と意味整合 / 固有名詞が実在名で原文と一致 / 文字化け・壊れ無し / 日付・場所が正気 / 画像が空でない / placeholder 漏れ無し。
- これは「即 publish + 事後レビュー」 の上位互換でなく **stakes に応じた選択**: 低 stakes は事後レビュー (review marker + drift 検出器) で足り、 高 stakes は pre-push ゲートが見合う (= CLAUDE.md inline §4「外部発信は判断ゲート」 を無人自動化に拡張)。
- ⚠️ **ゲートは flow でなく primitive level で塞ぐ (= bypass 経路も閉じて完成)**: 検証ゲートが `--no-push`→review→`--finalize` の flow にしか無く、 同じ engine に**直接 push する別 mode** (= 例 `--apply` で即 commit+push) が併存すると、 その primitive を呼べばゲートを丸ごと素通りできる。 enforcement が「手順/SKILL が常に gated flow を選ぶ」 という運用前提に依存してしまい、 手動実行・将来の手順改変・別 scheduler で破れる。 §1 の「gate は全経路を cover するか」 と同じ原則で、 engine は**新規 AI 生成 content を含む直接 push を明示 override flag 無しで refuse** すべき (= deterministic only 〔推測ゼロの変換〕 の直接 push は従来許可)。 = AI ゲート版の「全経路 cover」。

### Pattern: 無人 commit も対話 session と同じ git 同期規律を mechanize する

無人 commit は「作業前に pull、 障害なら止める」 (= shared-repo / push-workflow の規律) を reflex でなく code で強制する。 公開 repo への非 fast-forward push / conflict / 壊れた build の流出を構造的に防ぐ:

1. `git fetch` → working tree が **clean ∧ fast-forward 可能**でなければ apply 中止 (= dirty/diverge は人手に surface、 無人で merge しない)
2. mutate (= 生成 / copy)
3. **build / validate** (= 生成物が壊れていないか。 失敗なら `git checkout` + `git clean` で全 revert + push 中止 → 壊れた state を push しない)
4. commit (= 識別 prefix 付き、 例 `[<job>]`、 後で git log で grep 可能に)
5. push → race で reject されたら fetch + ff-pull + retry 1 回、 それでも駄目なら local commit を残して surface

clean 前提を preflight で保証してから `git clean -fd <dirs>` する設計なら、 clean は「自分が今作った untracked だけ」 を消す (= 既存 untracked を巻き込まない) ことが保証される。

**Pitfall: 「clean」 判定 (`git status --porcelain`) は untracked file も拾う**。 つまり repo に**無関係な stray untracked file が 1 個でもあると preflight が dirty と判定して無人 job が静かに止まる** (= 別 session の中途 WIP、 migration 生成物、 手で置いた tmp file 等)。 これは安全側 (= 散らかった tree を触らない) だが、 停止の**原因が非自明** (= 「なぜ今日 publish されてない?」 が untracked file 由来と気付きにくい)。 対策: 無人 job には別途 **heartbeat / staleness 検出** (= N 時間 publish 無し or 実行痕跡無しを surface) を持たせ、 停止に気付ける状態にする (= preflight abort 自体は正しい、 検出層で可視化する)。

### 関連

- §3 (judgment-required placeholder) = run-time 人間あり版、 本 §7 = 無人版。 同じ「機械は推測しない」 思想の対話/無人の両極
- §5 (過去手書き出力を script で reproduce) は無人 publish 前の validity 確認に必須 (= 生成物が手書き正本と同形式かを事前検証してから arm)
- 実行 locus の選択 (= そもそも無人 job を launchd / cron / scheduled task / GitHub Actions のどれで回すか) は [`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection)
- 無人 job を「どのマシンで」 走らせるかの判定 + install 未済の surface は [multi-machine-state.md](multi-machine-state.md)

---

## <a id="auto-edit-curated-file"></a>8. 無人で「人間が curate した file」 を auto-edit する

§6 は「yaml の fine-grained 自動 edit を避け print reminder にせよ」 と説く。 だが **無人実行 (§7)** では reminder を受け取る人間が run-time に居ない。 かつ対象が「人間も編集する curated file」 (= 過去エントリに手作業の清書・補足が入っている) なら、 file ごと regenerate すると人手 curation を破壊する。 この交差点での規律。

### Pattern: surgical text-edit + 再 parse integrity (library round-trip でなく)

load→dump round-trip (PyYAML 等) は comment / 整形 / key 順を破壊し、 既存全エントリを書き換えるので「人手 curation の温存」 と両立しない。 代わりに:

- **対象の block だけを text として挿入/置換**し、 他バイトは一切触らない (= 既存エントリは byte-identical、 diff 最小、 人手 curation 不変)。
- 書込み後に **load して integrity 検証**: 「意図した key (= 追加/更新した entry) 以外の既存エントリが一切変わっていない」 を機械的に確認。 surgery に bug があっても検証で fail-safe (= 書込みを revert して中止、 壊れた state を push しない)。

整形保持 library (ruamel.yaml 等) が無い環境でも、 text-surgery + integrity gate なら依存ゼロで安全に auto-edit できる。 新規 file 作成と既存 file 編集で revert 手段が違う点に注意 (= 新規 untracked は unlink、 既存 tracked は `git checkout`、 §7 の `git clean` 巻き込み回避と同じ理由)。

### Pattern: human/machine 共有 file の ownership marker

同じ file を「pipeline が auto 生成する行」 と「人間が手で enrich する行」 が共有するなら、 auto 生成行に **provenance marker** (例 `auto: true`) を付ける:

- pipeline は **marker 付き行だけ**を上流追従で update し、 marker 無し行 (= 人間所有) は絶対に触らない。
- 人間が auto 行を手直ししたくなったら **marker を消す** → 以後 pipeline はその行を人間所有として保護。
- これで「auto は上流に追従、 人手 enrich は不可侵」 が 1 file 内で両立する。 既存に大量の人手エントリがある file へ後から pipeline を足す時も、 既存は marker 無し = 全部「人間所有」 として凍結され、 新規 auto 行だけが marker 付きで machine 所有になる (= 安全な漸進導入)。

### Pattern: 決定的 mirror が curated downstream を「品質回帰」 させるなら gate する

§7 の armed-gate は「導出不能 field を推測で埋めない」。 だが **上流が下流より雑** (= typo / 1 cell に複数値を free-form で詰める / 表記揺れ) な場合、 純粋な決定的 mirror は **curated downstream の品質を回帰させる** (= 上流 typo を公開面に焼き直す、 複数値の分割を誤る)。 この時の gate:

- 上流各行を「決定的に安全に変換できる (= 単一値・正規 token・曖昧さなし)」 と「人手 judgment が要る (= 複数値分割・翻訳・表記正規化・typo 疑い)」 に分類。
- **安全な行だけ auto-publish、 残りは surface** して人手に渡す (= §7 の armed-gate を「推測回避」 から「品質回帰回避」 へ一般化、 §3 の placeholder と同思想で「機械は安全な subset だけ触る」)。
- arm する前に §5 の reproduce で「安全 subset の自動生成が過去の人手 curation を再現するか」 を検証 (= auto 出力 == 人手出力 を確認 → 回帰しない確証)。
- mirror と record を分離: 公開描画する SoT (= curated) と、 上流の付帯情報 (= 注記・出典等) を残す collaborator-readable な record file を別 file にすると、 公開データに内部注記が混ざらず record も全行を一様に持てる。 record が「上流の疎な free-form を mirror する」 だけなら、 その不完全性 (= 「空欄 = 事実なし、 ではない」) を file header に明記して over-claim を防ぐ。

### Pattern: ownership marker で重複が温存されるなら overlay (source + overrides → generated) へ

上の ownership marker は「auto 行は上流追従・人手行は不可侵」 を 1 file 内で両立するが、 **同じ事実が上流と下流の両方に在り続ける** (= marker 無し人手行は上流と照合されないので duplication-with-drift が温存される)。 特に **その下流 file を実質 pipeline / AI しか編集しない** 運用では「人手 vs machine 所有」 の区別が形骸化し、 marker は「決定的生成 vs 判断生成」 の label に過ぎなくなる。 重複自体が問題化したら、 ownership marker でなく **source + overlay → generated artifact** へ昇格する:

- **上流** = 生事実の単一 home (不変)。 **overrides file** = 上流から導出できない判断データ (= 翻訳・複数値の分割結果・表記補正・派生 mapping) の単一 home。 **下流** = 両者から pipeline が毎回生成する成果物 (= 手編集禁止、 ownership marker 不要 = 全行が生成物)。
- 純導出できる行は重複ゼロ (= 上流からの projection)。 判断が要る行だけが overrides に実体を持つ。
- ⚠️ 限界: 「上流の雑な入力 → 清書」 が非決定的変換なら、 その結果は overrides に保存するしかなく **重複は既約**。 overlay の達成は「重複を overrides 1 箇所に集約 + 下流を純生成物化」 であって「全行で重複ゼロ」 ではない (= 単一 field 補正の行も full record を持つなら既に正しい上流 field を重複する。 field 単位 patch で削れるが複雑度増)。
- 生成物は build 時でなく **pipeline (= 無人 commit) が生成して commit** する (= build-time fetch は外部依存で脆く、 §7 の fresh-eyes gate / controlled-publish を bypass する)。 上の gate 4 分類 (auto / review) はそのまま使え、 review 行は overrides に清書 entry が要る (無ければ生成 error で fail-safe)。
- 移行の安全網: overrides を現下流から逆算 (= 純導出で再現できない差分が override) → 再生成物の **build 出力が現状と一致** することを検証してから切替 (= 公開面 byte 不変の証明)。

### Pitfall: 同一 yaml を 2 parser が読むと YAML 1.1 boolean key で食い違う

同じ yaml を **build tool の js-yaml (YAML 1.2) と script の PyYAML (YAML 1.1)** が両方読む構成では、 unquoted な `no` / `yes` / `on` / `off` / `y` / `n` を **PyYAML は boolean (例 `no:` → `False` key)、 js-yaml 1.2 は string** として load する (= 食い違う)。

- 症状: PyYAML 側で `d.get("no")` が `None` を返す (= 実 key は `False`)。 build (js-yaml) は正常なので「script だけ」 が静かに誤読する。
- 対処: script 側で両対応 (`d.get("no", d.get(False))`)、 または yaml 側で当該 key/値を quote。
- reflex: 「この yaml は他 parser も読むか? key/値に `no/yes/on/off` 系の bare token はないか?」 を script を書く時に問う。

---

## まとめ: 自動化 pipeline 設計の checklist

新規自動化 script を書く前に以下を確認:

- [ ] データの単一ソースを決めた? (= 二重管理回避)
- [ ] SoT の不変条件 (重複なし / uniqueness) は **経路非依存 gate (= commit hook 等)** で守った? (= 生成経路の guard だけでは手動編集をすり抜ける、 §1 Pattern)
- [ ] schema 拡張は forward-only? (= 一括 backfill 避ける)
- [ ] judgment-required content に placeholder pattern を用意した? (= AI 初稿 + user edit)
- [ ] user input は regex validate? path traversal mitigation?
- [ ] 必須 field 欠落は explicit error?
- [ ] 過去 user 承認済出力で reproduce 検証した? (= validity 確認)
- [ ] yaml の自動 edit を避けて print reminder にした?
- [ ] **SoT の home が lifecycle で移動するなら**: 全 consumer を grep で洗い出し共有 resolver 経由に redirect した? prune は新 home に移った field だけ (field-scoped)? (§1 Pattern)
- [ ] **無人実行なら**: 自動 publish は推測ゼロの変換だけ? 導出不能 field は事前入力 (armed) or surface? (§7)
- [ ] **高 stakes な無人 publish なら**: push 手前に fresh-eyes adversarial な AI 検証ゲート (= 別呼び出しで「間違いを探せ」、 clean だけ push・疑義は hold+surface) を足した? (§7 Pattern)
- [ ] **無人 commit なら**: clean∧ff-only-or-abort → build 検証 → 失敗 revert → commit → push retry を mechanize した? (§7)
- [ ] **無人で curated file を auto-edit するなら**: surgical text-edit + 再 parse integrity (round-trip でなく)? human/machine 共有なら ownership marker で人手所有を保護? (§8)
- [ ] **上流が下流より雑なら**: 純 mirror が品質回帰しないか? 安全 subset だけ auto・残りは surface? (§8)
- [ ] **ownership marker で重複が温存され下流を実質 pipeline/AI しか編集しないなら**: overlay (source + overrides → generated artifact) へ昇格を検討? (= 純導出行は重複ゼロ、 判断データは overrides 1 home、 下流は手編集禁止の生成物。 §8)
- [ ] **同一 yaml を 2 parser (js-yaml + PyYAML) が読むなら**: YAML 1.1 の `no/yes/on/off` boolean key 食い違いを確認? (§8)

### 関連 convention

- 既存 [convention-design-principles.md §2](../docs/convention-design-principles.md#no-duplicate-rules) 「ルールの重複を避ける」 は **規約** の単一ソース化、 本 convention §1 は **データ** の単一ソース化。 思想は同じ
- [scientific-computing.md](scientific-computing.md): 計算結果 artifact の保存規律 (= 似たテーマ、 個別 domain)
