<!-- doc-meta
when: CLAUDE.md 等の memory file が肥大して縮退 (slimming) するとき + 完了 entry を archive へ graduate するとき + 長大 bullet / table row を pointer 化するとき
category: harness-core
summary: memory file のサイズは毎 session + 毎 headless routine が払う税 — 縮退は「MOVE + pointer 化、 DELETE 禁止」 が大原則で、 SoT 照合 → 不足 MOVE → trim の順を 1 unit ずつ守れば義務を落とさず 25% 級の削減ができる (検証済手順 + gates + 一意 prefix 行置換 helper)
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
   編集は [`scripts/replace-line.py`](../scripts/replace-line.py) (= 一意 prefix assert 付き
   行置換、 「検証してから書く」 の機械化。 行番号指定や sed の多重 hit 事故を構造的に防ぐ)。
5. **greppability 確認**: unit から落とした固有名 (= 事故名・incident の呼び名) が
   SoT / archive / plans 側で依然 grep hit することを確認する (= 将来の grep 起点を殺さない)。

## gates (全部 pass してから push)

1. repo の全機械検査 runner が全 PASS (= 縮退前の基準本数と比較、 増減は理由を記録)
2. SoT drift 検査が**縮退作業由来の新規 finding ゼロ**
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

## 実測 evidence (2026-07-29/30)

個人層 memory file 276 KiB (= headless routine 全滅の実害) →
graduation 37 entry で 176 KiB → pointer 化 (38 bullet + 16 table row) で **130 KiB (−26.5%)**。
落とした義務・行動制約ゼロ (= gates 全 pass、 機械検査 74/74、 greppability 5/5、
構造 invariant 不変)。 うち bullet 平均は「wiring + 1-2 文 + ⚠️ + pointer」 で ~700-800 B
(CJK) に収束した — これ以下は routing 価値と衝突するので床として扱う。
