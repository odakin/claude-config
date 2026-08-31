<!-- doc-meta
when: CLAUDE.md 等の memory file が肥大して縮退 (slimming) するとき + 完了 entry を archive へ graduate するとき + 長大 bullet / table row を pointer 化するとき
category: harness-core
summary: memory file のサイズは毎 session + 毎 headless routine が払う税 — 縮退は「MOVE + pointer 化、 DELETE 禁止」 が大原則で、 SoT 照合 → 不足 MOVE → trim の順を 1 unit ずつ守れば義務を落とさず 25% 級の削減ができる (検証済手順 + gates + 一意 prefix 行置換 helper)。 追補 (2026-09-01、 6 repo −64% 実測): fleet 並列縮退 / 旧全文 verbatim 退避 / 義務 carrier 付き graduation 判定 / archive の検出器除外 glob 両形 / 並行 session 干渉 / 生成 block への適用
-->
# Memory file の縮退 (slimming) — MOVE + pointer 化の手順

CLAUDE.md 連鎖 (= session 開始時に丸ごとロードされる memory file) のサイズは
**毎 session + 毎 headless routine が払う税**である。 肥大の failure mode
(= headless `claude -p` が "Prompt is too long" で黙って全滅する) と診断 ladder は
[`scheduled-tasks.md #headless-context-budget`](scheduled-tasks.md#headless-context-budget) が正本。
本 doc はその「真の root = 肥大」 への **縮退の手順**の正本。

## 大原則

**MOVE + pointer 化のみ、 DELETE 禁止。 義務保全 > サイズ目標。**
縮退は何度でもできるが、 消えた義務・行動制約は戻らない。 目標サイズに届かないときは
無理せず、 できた分と理由を記録して打ち切る (= scope 縮小は失敗ではない)。

## 縮退の 2 形態

1. **graduation** (= hot/cold 分離): 完了 / DEPRECATED になった entry を archive file へ
   **MOVE** する。 ⚠️ 残 action / user 判断待ちを運ぶ entry は完了マークがあっても
   graduate しない (= 義務が消える)。
2. **pointer 化**: 生き残る bullet / table row が抱える payload (= RCA 経緯・実装史・
   述語詳細・severity 表) を SoT 側 (script docstring / 専用 doc / archive / plan) へ寄せ、
   memory file 側は routing に必要な最小だけ残す。 手順は下記。

## <a id="pointer-conversion"></a>pointer 化の手順 (= 1 unit ずつ、 batch 一括置換しない)

0. **着手前に全関連 repo を fetch/pull** (= 下記 [#stale-checkout](#stale-checkout))。
1. **実測**: 対象 block を unit (bullet / row) 別に byte 計測し、 肥大順に並べる
   (= 効果の大きい所から、 かつ「どこまでやったか」 を機械で追える)。
2. **指定 SoT を特定**: unit 内の「正本 =」「SoT =」 宣言を読む。 通常は
   ① script docstring (code-as-SoT) ② 設計 plan / results ③ 上層 doc のどれか。
3. **payload が SoT 側に実在するか照合**: unit 内の各 fact (述語 / 日付 / 限界 /
   severity 分岐) を、 SoT 側 file への **distinctive substring 2-3 個の grep** で確認する。
   **SoT 側に無い fact は先に MOVE** (docstring なら文体を合わせて追記 — ⚠️ `--selftest` を
   持つ script は編集後に必ず再走。 plan なら「追補」 節として append)。
   **どこにも home が無い fact は unit に残す** (= 消さない)。
4. **trim**: 残すのは 4 点だけ —
   - 名前 + 発火 wiring (= どこから呼ばれるか)
   - **何をするか 1-2 文** (= routing に必要な最小)
   - **⚠️ live な行動制約** (= 「〜してはいけない」「〜は射程外」 級の、 誤用を防ぐ caveat)
   - **SoT pointer** (= 正本の file#anchor / docstring / plan)
   ⚠️ の判別: **行動制約の ⚠️ は残す、 経緯の ⚠️ は落とす。 迷ったら残す。**
   routing table (= 「いつ何を読むか」 の row 群) の row では **trigger 列 (適用タイミング)
   こそが row の routing 機能** — trigger は残し、 rule の digest (= 対象 doc の要約・日付・
   優先順) を payload として落とす。 digest が対象 doc に実在することを照合してから
   (= digest は doc の目次代わりに見えるが、 drift する複製にすぎない)。
   編集は [`scripts/replace-line.py`](../scripts/replace-line.py) (= 一意 prefix assert 付き
   行置換、 「検証してから書く」 の機械化。 行番号指定や sed の多重 hit 事故を構造的に防ぐ)。
5. **greppability 確認**: unit から落とした固有名 (= 事故名・incident の呼び名) が
   SoT / archive / plans 側で依然 grep hit することを確認する (= 将来の grep 起点を殺さない)。

## gates (全部 pass してから push)

1. repo の全機械検査 runner が全 PASS (= 縮退前の基準本数と比較、 増減は理由を記録)
2. SoT drift 検査が**縮退作業由来の新規 finding ゼロ**。 帰属判定 = flagged file が
   自分の編集集合に含まれるか (= 含まれなければ pre-existing。 直さず「out-of-scope
   引き継ぎ」 として results に記録する — 縮退 commit に無関係な修正を混ぜない)
3. **構造 invariant の機械検証**: routing 構造 (table の全 row 存在 / bullet 本数) が不変
4. docstring を触った script 全部の `--selftest` 再走 = 全 PASS
5. before/after のサイズ実測を results に記録
6. commit は**明示 path** (= 並列 session 対策)。 縮退の変更は 1 commit にまとめる
   (= unit 単位の revert が容易)

## <a id="stale-checkout"></a>⚠️ stale checkout の罠 (= 着手前 pull が step 0 な理由)

SoT 照合も drift 検出器も **local checkout を読む**。 照合先 repo が behind だと:

- 「SoT 側に fact が無い」 という**偽の照合失敗** → 不要な MOVE (= 重複を新設) を誘発
- 検出器の config 警告 (= 「registry の anchor が home に無い」 等) が **stale checkout の
  artifact** として出る → registry を「直し」 に行くと逆に壊す

実測 (2026-07-30): 照合先 repo が behind 72 のまま検出器を走らせ、 registry 警告 2 件が出た。
home file を pull しただけで両方消えた — registry は正しく、 直すべきは checkout だった。

## 副産物: 照合は stale SoT 発見の機会

手順 3 の照合で、 SoT 側の自己矛盾 (= docstring 冒頭が旧仕様のまま、 後半の実装記述と食い違う) や
移動済み section への stale 引用が見つかることがある。 見つけたら **SoT 側を先に直してから**
pointer 化する (= stale な正本への pointer は縮退の意味を毀損する)。
実測 1 pass で docstring 自己矛盾 2 件 + 移動済 § への stale 引用 2 箇所を発見・修復した。

## <a id="fleet-parallel-slimming"></a>fleet 並列縮退 (= 複数 repo を delegate で一斉に)

肥大は repo 単位で独立なので、 縮退は **1 repo = 1 delegate** で並列化できる
(実測 2026-09-01: 6 repo / 9 file を親 1 + delegate 4 で一斉、 1.37 MB → 0.49 MB 〔−64%〕、 義務喪失ゼロ)。 規律:

- spec には本 doc を「最初に全文読む」 と明記し、 大原則 (MOVE + pointer 化 / DELETE 禁止 /
  義務保全 > サイズ目標) と repo 固有の live 制約 (触ってはいけない表・改変禁止 file) を焼き込む。
- gates は repo ごとに完結させる: 各 delegate が自 repo の検査 runner / drift 検査 / greppability /
  構造 invariant を回し、 **1 repo 1 commit + push まで完遂**してから報告する。
- **逐語 coverage の機械照合が最強の gate**: 「旧 file の全行が new + archive のどちらかに literal
  存在する」 を script で assert すると DELETE ゼロが証明になる (見出し level 変更等の意図的差分のみ
  個別 assert)。 byte 収支 (new + moved ≥ 旧) の照合はその軽量版。
- delegate の out-of-scope findings (= 縮退 commit に混ぜない引き継ぎ) は親が集約し、
  修復するか carrier (SESSION entry / TODO) に載せるまでが 1 単位。

## <a id="verbatim-retreat"></a>pointer 化の安価な安全化 = 旧全文の verbatim 退避

[#pointer-conversion](#pointer-conversion) step 3 (payload の SoT 実在照合) は unit 数が多いと高くつく。
代替: **pointer 化する unit の旧全文を archive の専用節 (例: 「pointer 化退避」) へ verbatim MOVE
してから trim する**。 fact ごとの照合を省いても、 home の無い fact が archive に生き残る
(= archive が catch-all home になる) ので fact-loss ゼロが構造で保証される。
pointer 行には「旧全文 = <archive>」 を 1 語添える (= 読み手が退避の存在を知る経路)。
SoT 照合を丁寧にやる余裕があるときは本則 (= SoT 側へ寄せる方が home が 1 つで済む)、
live entry を大量に薄くするときはこの variant。

## <a id="obligation-carrier-graduation"></a>義務 marker 付き entry の graduate 判定

「残 action / user 判断待ちを運ぶ entry は graduate しない」 の運用形: graduate 前に移動候補
全体を義務語彙 (残 / 未実装 / 未着手 / 判断待ち / green-light 待ち / 次 session / 保留 …) で
機械 grep し、 hit した entry ごとに **義務の carrier が別に立っているか** を確認する —
plan 内の un-defer trigger 記録 / TODO / 機械 surface (SessionStart hook 等) / 後続 session で
超越済、 のどれかがあれば MOVE 可。 無ければ (a) entry を hot に残す か
(b) 義務行だけ hot に lift して本体を MOVE (= lift 先は Open items 等の常設節)。
判定の要旨は archive header か commit message に 1 行残す (= 後から「なぜ移せた」 が追える)。

## <a id="archive-detector-exemption"></a>archive file と検出器の除外 glob

archive は「正本の重複」 を意図的に抱える (= verbatim 退避) ので、 SoT drift 系検出器の scan からは
除外するのが正しい。 ⚠️ 除外 glob は **file 形 (`*/SESSION-archive.md`) と dir 形
(`*/SESSION-archive/*`) の両方**を張る — 片方だけだと命名差で false positive が出る
(実測 2026-09-01: dir 形のみ登録済みの環境で file 形 archive を新設し FP 1 件)。
archive を新設したら検出器の除外 registry を同 commit で更新する。

## <a id="parallel-session-interference"></a>並行 session 干渉 (= stale checkout の姉妹)

縮退中の working tree は、 並行 session の `git add` に巻き込まれて**途中状態のまま commit され得る**
(実測 2026-09-01: SESSION 分割中に別 worker の無関係 commit へ同梱された)。 防御:

1. 分割の write は「新 archive + 縮んだ本体」 を**同一 script 実行内で連続 write** する
   (= どの瞬間に commit されても対で入り、 transient に片割れだけが history に残らない)。
2. 着手時の実測サイズと直前 read のサイズがずれたら、 続行前に diff で出所を特定する
   (= 並行編集の混入は「読んだ内容を保存し直す」 操作で無言に取り込まれる)。
3. 自分の途中状態が他者 commit に入っていたら、 当該 commit に対の file が揃っているかを
   commit 単位で機械確認する (揃っていれば欠損なし、 巻き込みの旨を自 commit message に記載)。

## <a id="generated-block-slimming"></a>生成 block への適用 (= 手書き file だけが税ではない)

auto-load される file の肥大が AUTO-GENERATED block 由来なら、 縮退の対象は**生成契約そのもの**:
表示を digest (summary) から **trigger (when)** に切替え、 digest は auto-load されない生成 view
(README 等) へ移す。 [#pointer-conversion](#pointer-conversion) step 4 の
「routing table は trigger 列こそが routing 機能」 の生成側適用で、 源 data は不変なので
情報の削除ゼロで済む。 移し先の README は AUTO-GENERATED の view であり正本ではない
(= 「README に正本を置かない」 規律と両立する)。 実例 = 本 repo `generate-tree.py` の
2026-09-01 契約変更 (設計記録 = [`DESIGN.md #auto-tree-autoload-slim`](../DESIGN.md#auto-tree-autoload-slim)、
CLAUDE.md 95 → 35 KB)。

## 実測 evidence (2026-07-29/30)

個人層 memory file 276 KiB (= headless routine 全滅の実害) →
graduation 37 entry で 176 KiB → pointer 化 (38 bullet + 16 table row) で **130 KiB (−26.5%)**。
落とした義務・行動制約ゼロ (= gates 全 pass、 機械検査 74/74、 greppability 5/5、
構造 invariant 不変)。 うち bullet 平均は「wiring + 1-2 文 + ⚠️ + pointer」 で ~700-800 B
(CJK) に収束した — これ以下は routing 価値と衝突するので床として扱う。
