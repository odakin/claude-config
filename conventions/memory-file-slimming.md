<!-- doc-meta
when: CLAUDE.md 等の memory file が肥大して縮退 (slimming) するとき + 完了 entry を archive へ graduate するとき + 長大 bullet / table row を pointer 化するとき
category: harness-core
summary: memory file のサイズは毎 session + 毎 headless routine が払う税 — 縮退は「MOVE + pointer 化、 DELETE 禁止」 が大原則で、 SoT 照合 → 不足 MOVE → trim の順を 1 unit ずつ守れば義務を落とさず 25% 級の削減ができる (検証済手順 + gates + 一意 prefix 行置換 helper)。 追補 (2026-09-01、 6 repo −64% 実測): fleet 並列縮退 / 旧全文 verbatim 退避 / 義務 carrier 付き graduation 判定 / archive の検出器除外 glob 両形 / 並行 session 干渉 / 生成 block への適用 / 再肥大 backstop の常設 (warn 閾値 = 健康 floor の上 + live 校正) / **肥大がどこに溜まるか (graduation の空振り診断 + 状態名の節の accretion、 #where-bloat-hides)**
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

## <a id="where-bloat-hides"></a>肥大がどこに溜まるか — graduation の空振りと「状態名の節」

着手したらまず **graduation を試して yield を測る**。 その数字自体が診断になる。

- **graduation の yield が ~0 (= 移せる完了 entry がほとんど無い) なら、 その file は「死んだ記録」
  ではなく「生きた義務」 で膨れている**。 粘っても取れないので lever を pointer 化 (= 義務は残して
  payload だけ SoT へ寄せる) に切り替える。 実測 2026-09-10: 個人層 CLAUDE.md の作業 project
  67 entry のうち graduate 可は 0、 SESSION.md の状態節 12 entry のうち 3 — 削減はほぼ全て
  pointer 化から出た。 ⚠️ この状態の file に対して「もっと graduate しろ」 と圧をかけると、
  義務を運ぶ entry を移す方向にしか進めなくなる (= サイズ目標が義務保全を侵食する)。
- **見出しが状態名の節 (「現在の状態」「Open items」 等) は、 日付ベースの graduation rhythm の
  外に落ちて silently accrete する**。 dated 見出しは「古い順に archive」 の対象として目に入るが、
  状態名の節は中身が dated entry でも「現在」 と名乗るので誰も古さを疑わない。 実測 2026-09-10:
  `## 現在の状態` の中に 10〜13 日前の dated entry が 12 本溜まる一方、 同 file の dated `##` 節は
  3 日遅れで archive 済みだった (= 1 つの file に 2 つの rhythm が併存)。 **縮退のたびに
  「状態名の節の中身は本当に現在か」 を 1 回問う。**

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
⚠️ **退避先が別の深さの dir なら、 verbatim の相対 link は着地しなくなる** (`SESSION-archive/2026-09.md` へ移した `review/x.md` は `../review/x.md` が要る)。 verbatim は「文字列を変えない」 ではなく「内容を変えない」: 移した直後に `scripts/fix-md-links.py --files <archive> --fix` で深さだけを直し、 `--list --strict` が 0 になってから commit する (2026-09-13 に 40 bullet を退避した回、 staged link guard が 39 本の depth と 1 本の ambiguous で commit を止めた)。
**道具** (2026-09-13): 日付 bullet の連続ブロックなら [`scripts/fold-dated-bullets.py`](../scripts/fold-dated-bullets.py) が、 要約 1 行 (+ 追記点の行) への置換・archive への verbatim 退避・link の深さの付け替え・退避の完全性の検算を 1 回で行う (連続していない・同じ見出しが既にある、 のどちらかなら何も書かない)。 手で、 または別の道具で移した commit は [`scripts/verify-verbatim-move.py`](../scripts/verify-verbatim-move.py) `--from <src> --to <archive> --normalize-links` で検算する。 同じ commit で source の手順や状態の行も直したなら `--removed-prefix '<日付 prefix>'` で移した行だけに絞る (絞らないと、 その直した行が「移動先に無い」 と正しく列挙される)。 並列 session が同じ SESSION に追記している最中に畳むなら [`multi-session-coordination.md#fold-with-append-point`](multi-session-coordination.md#fold-with-append-point)。

## <a id="obligation-carrier-graduation"></a>義務 marker 付き entry の graduate 判定

「残 action / user 判断待ちを運ぶ entry は graduate しない」 の運用形: graduate 前に移動候補
全体を義務語彙 (残 / 未実装 / 未着手 / 判断待ち / green-light 待ち / 次 session / 保留 …) で
機械 grep し、 hit した entry ごとに **義務の carrier が別に立っているか** を確認する —
plan 内の un-defer trigger 記録 / TODO / 機械 surface (SessionStart hook 等) / 後続 session で
超越済、 のどれかがあれば MOVE 可。 無ければ (a) entry を hot に残す か
(b) 義務行だけ hot に lift して本体を MOVE (= lift 先は Open items 等の常設節)。
判定の要旨は archive header か commit message に 1 行残す (= 後から「なぜ移せた」 が追える)。

⚠️ **義務語彙は「語」 で引く — 記号を足して narrow しない。 そして grep が clean と言った候補も
MOVE 直前に本文の末尾数行を読む。** 実測 2026-09-10: 上の語彙のうち「残」 を `残 =` (= 語 + 記号)
として grep したため、 本文中の「⚠️ 残 verify = 実 terminal での live 発火」 を clean と誤判定
しかけた (MOVE 直前に読んで気づき除外)。 義務の書き方は開かれている (残 verify / watch /
目視で完了 / 次の該当 session で …) ので、 **grep は候補を絞る道具であって判定器ではない**。

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
   **揃っていない (= 縮んだ本体だけが入り、 verbatim 退避の archive が未 commit) なら、 巻き戻さず
   archive を HEAD の上に commit して対を揃える** (実測: 相手の `git commit -- <本体>` が本体だけを
   拾い、 旧全文が履歴に無い半端な状態が数分あった。 revert すると縮退が消え、 相手の変更も巻き込む。
   commit message に混入した commit の hash を書けば履歴が辿れる)。 同じ file に相手の未 commit hunk が
   居る状態で自分の分だけ commit する経路 = [`multi-session-coordination.md#temp-index-commit`](multi-session-coordination.md#temp-index-commit)。

## <a id="generated-block-slimming"></a>生成 block への適用 (= 手書き file だけが税ではない)

auto-load される file の肥大が AUTO-GENERATED block 由来なら、 縮退の対象は**生成契約そのもの**:
表示を digest (summary) から **trigger (when)** に切替え、 digest は auto-load されない生成 view
(README 等) へ移す。 [#pointer-conversion](#pointer-conversion) step 4 の
「routing table は trigger 列こそが routing 機能」 の生成側適用で、 源 data は不変なので
情報の削除ゼロで済む。 移し先の README は AUTO-GENERATED の view であり正本ではない
(= 「README に正本を置かない」 規律と両立する)。 手書きの README を生成 view に置き換える汎用の道具 =
[`scripts/generate-dir-readme.py`](../scripts/generate-dir-readme.py) (任意の dir の各 file 冒頭の説明 1 行目から
索引を作り、 `--check` で手編集と説明の書き忘れを止める。 README の詳細を各 file 冒頭へ移すときは、
1023 byte を超える多バイト行を折り返す = [`batch-text-edits.md#system-python-long-multibyte-line`](batch-text-edits.md#system-python-long-multibyte-line))。
実例 = 本 repo `generate-tree.py` の
2026-09-01 契約変更 (設計記録 = [`DESIGN.md #auto-tree-autoload-slim`](../DESIGN.md#auto-tree-autoload-slim)、
CLAUDE.md 95 → 35 KB)。

## <a id="regrowth-backstop"></a>縮退後は再肥大の機械 backstop を常設する

縮退 campaign が繰り返し露呈した根本欠陥は「**肥大を誰も機械で見ていなかった**」 こと
(276 KB cron 全滅も 2026-09-01 の fleet 肥大も、 発見の trigger は owner の手動質問だった)。
縮退したら同じ流れで、 auto-load file のサイズを定期実測して**閾値超過だけを surface する
検出器**を dashboard 等の常設面に置く (finding は本 doc へ routing = 手順まで導線を繋ぐ)。
閾値の置き方:

- **warn は「達成可能な健康 floor」 の上に置く**。 縮退直後の実測 max (= それ以上薄くすると
  義務を落とす床) より下に warn を置くと慢性点灯になり、 「healthy = silent」 が壊れて
  真の finding が noise に沈む。 floor は設計でなく実測で決まる
  (2026-09-01 実測: 縮退後 fleet max ~140 KB → warn 150 KB)。
- **机上の設計値は live 実走で即校正する**。 初版 warn (120 KB) は実走で just-slimmed fleet が
  即点灯 → 同 turn で調整した。 閾値付き検出器は「現状の実 fleet で silent になるか」 を
  出荷 gate に含める。
- archive (= 退避先) は閾値の対象外にする (= 入れると縮退が「移すほど焼ける」 self-defeating、
  [#archive-detector-exemption](#archive-detector-exemption) の閾値版)。
- **byte の閾値は auto-load されない file の再肥大を拾わない**。 SESSION.md は resume のときに読まれるだけで
  auto-load 税が小さく、 2026-09-11 の claude-config の SESSION.md は 506 行でも 91 KB (per-file warn 150 KB の
  遥か下) のまま誰も気付かなかった。 縮退した file には**行数の閾値**も登録し (warn = 目安 + slack、 同じく実 fleet で
  silent を確認)、 **追記した本人に届く面** (= commit 時の warn) にも置く。 実例 = claude-config の
  `.claude/pre-commit-extra.sh` 検査 5 (120 行 = 形の gate [#session-shape-gate](#session-shape-gate) と同じ warn)。
- **SESSION-as-SoT detector は whole-file bytes と largest UTF-8 line の両方を測る。** 行数だけでは durable payload を
  一つの巨大 bullet に詰めた file が抜け、全体量だけでは短い file 内の異常な一行が埋もれるためである。公開 engine
  [`scripts/check-session-sot.py`](../scripts/check-session-sot.py) の既定 warn は 64 KiB / 2 KiB。これは意味上の違反判定
  ではなく、高信号の byte proxy であり、live fleet で慢性点灯しない境界に校正してから変更する。

- <a id="per-entry-commit-warn"></a>**entry が並ぶ節 (作業中 project の一覧・索引) は、 file 全体の byte でなく entry ごとの byte を commit 時に見る。**
  file 全体の閾値は「どこかが育った」 しか言わず、 しかも次の session で出るので書いた本人に届かない。 一覧型の節が育つ経路は
  entry の書き換えのたびに状態・経緯を写し込むことで、 追加・更新された entry の多くが床 (~800 B) の 1.5 倍 = 1200 B を
  超えていた (実測)。 warn の対象は **HEAD に無い (新規・書き換えた) entry だけ**にする
  (= 既存の長い entry を触らない commit で慢性点灯させない)。 節の冒頭にも「entry は pointer + 次の一手だけ、
  状態・経緯は各 repo の SESSION / plan」 と規範を置き、 warn の文面から同じ規範を指す。 縮退の回によって graduation の
  yield が大きく違ったのは、 完了した RCA / plan の entry が「完了」 と書き換えられたまま一覧に残っていたため (実測。
  graduate は完了を書いた turn でするのが安い)。 engine = [`scripts/check-memory-file-bloat.py`](../scripts/check-memory-file-bloat.py)
  `--staged --file CLAUDE.md --entry-section '### <節の見出し>'` (① file 全体の KB ② `LINE_LIMITS` に登録した file の行数
  ③ 節の新規・書き換え entry の byte。 止めない、 検査不能は rc 3)。 各自の pre-commit から呼ぶ (閾値を hook に書き写さない)。

- <a id="commit-budget-gate"></a>**warn を出しても育ち続ける file は、 予算を超えて育つ commit をその時点で止める。**
  warn は書いた本人に届いてもその commit を止めないので、 並行する複数の session の追記が積み上がる (実測: 縮退した直後から
  1 日 ~4 KB 育ち、 warn の閾値に 2 日で戻った)。 gate の形: ① 予算は warn より下に置く (= commit で育つ限り surface の warn に
  届かない) ② 止めるのは「予算以上 ∧ HEAD より byte が増える」 commit だけ — 縮める commit・予算内の commit は通す (= 予算を
  超えてからは、 足す分を同じ commit で MOVE + pointer 化して払う。 縮退の commit 自体は止まらない) ③ 故障は違反と別の終了値
  (3) で「この commit では走っていない」 を出す ④ 逃げ道の env は owner が明示したときだけ使う。 engine =
  [`scripts/check-memory-file-bloat.py`](../scripts/check-memory-file-bloat.py) `--staged --block` (予算の値は engine だけが持つ)。
  <a id="pay-command"></a>⑤ **止めた画面には「払う 1 コマンド」 を出し、 止められた側は追記を取り下げずに払う。** 実測 (12 日間、 1 台の記録) では止められた
  12 回のうち払ったのは 1 回、 残りは追記の取り下げか削りで終わり、 要る routing・制約が落ちた。 払う操作 (どの行を・どこへ・verbatim で・
  link を直して・検算して) に道具が無く、 止めた画面が手順 doc を指していたことが原因。 道具 = [`scripts/memory-budget-pay.py`](../scripts/memory-budget-pay.py)
  (`status` = 予算までの余裕 / `candidates` = 行を経緯 payload の多い順に / `retreat` = 一意 prefix の 1 行を新しい行に置換して旧行を archive の
  日付つき節へ verbatim / `graduate` = entry を archive へ MOVE、 義務語彙の hit は carrier を書かないと dry-run)。 何を残すかは呼び手が決める
  (手順 4)。 利用者は既定値 (file・archive) を渡す shim を置き、 pre-commit の `--pay-cmd` と surface の `--headroom` に同じ command を渡す。
  ⑥ **払うときは予算の線まででなく余裕の目安 (予算 − 8 KB、 道具の既定) まで払う** = 足した分だけ払うと file は予算の線に張り付き、 以後の
  全 commit が境界の取引になる (実測: 2.6 KB の余裕は 3 日で尽き、 その後 2 週間ほど毎 commit 止まった)。 ⑦ **経緯 payload (日付・RCA・実測・
  引用の括弧) が数 KB しか残っていない file は pointer 化の床** — 払いの原資が無いので、 行を落とすか構造を変える (列挙を生成 file へ・制約を
  使う瞬間の hook へ) 判断が要る。 その判断は owner のもので、 道具は `candidates` の合計で床に居ることを示すだけ。
  構造を変えるときの道具 (owner の裁定の後): **routing table は全文を auto-load されない file (正本) に置き、 auto-load 面には
  [`scripts/generate-trigger-table.py`](../scripts/generate-trigger-table.py) が 3 列目の 1 文目 (trigger) と ⚠️ を含む文だけを marker の間に生成する**
  (= 行を足す人が何を書いても要約・経緯は auto-load 面に出ない。 [#generated-block-slimming](#generated-block-slimming) の表版)。
  **道具ごとの「触る前に効く制約」 の表は auto-load されない file に置き、 [`scripts/constraint-at-use.py`](../scripts/constraint-at-use.py)
  (PreToolUse hook) が Bash で道具の名を叩いた瞬間・台帳 file を開いた瞬間に該当行を session に 1 回出す** (key は行の 1 列目から導出。
  読む側が preamble から思い出すのでなく tool 結果の直前に行が居る = 発火面を使う瞬間へ移す
  [`convention-design-principles.md#symptom-keyed-entry-point`](../docs/convention-design-principles.md#symptom-keyed-entry-point))。
  実測: 2 表で auto-load file の 28% (41 KB) を降ろし、 移した行は link の深さ以外 1 字も変えていない (verbatim の照合は行単位で機械)。

(以上の置き方は任意の常設検出器に通じる一般形だが、 実例 1 件のため本 doc 留め —
2 例目で上層 doc への hoist を判断する。)

## <a id="session-shape-gate"></a>SESSION の形の gate に止められたときの直し方

SESSION.md の契約 ([CONVENTIONS.md#session-no-durable-record](../CONVENTIONS.md#session-no-durable-record)) = 案件ごとの現在地 1〜2 行 + 正本への link。
gate ([`scripts/check-session-shape.py`](../scripts/check-session-shape.py)、 pre-commit と書き込み hook) が止めた finding ごとの直し方:

| finding | 直し方 |
|---|---|
| `dated-heading` (日付を見出しにした節) | その案件の entry を探して**置き換える**。 無ければ `- <案件> — 現在地 / 次の一手 → [正本](link)` の 1〜2 行を足す。 「何をした」 は git log、 「何を決めた」 は DESIGN.md / 案件の記録へ。 ⚠️ 見出しの日付を本文へ移して finding を消すのは直しでない (実測 = README の節の中身 〔判断・照合・返事〕 は残ったまま)。 README の節なら、 中身を台帳・note へ移し、 README は入口の link だけにする |
| `commit-hash` / `message-id` | 識別子は正本 (plan / DESIGN / 台帳 / inbox) に置き、 SESSION には正本への link だけ。 `最終更新: … (sweep 済: <hash>)` の 1 行は通る |
| `long-line` (1000 byte 超) | 経緯を正本へ移し、 SESSION の行は現在地と次の一手に絞る |
| `line-budget` (200 行を超えて育つ) | 案件ごとの現在地に組み直す。 残す価値のある経緯は SESSION-archive.md へ verbatim MOVE ([#verbatim-retreat](#verbatim-retreat))。 **縮める commit は通る** (予算 gate と同じ形 = [#commit-budget-gate](#commit-budget-gate)) |
| `readme-self-sot` | 非公開 repo: 中身を CLAUDE.md / DESIGN.md / 台帳へ移し README は入口の link に。 公開 repo (warn): 中身は同じく移す。 build / quickstart / deploy の手順は README に利用者向けの写しとして残し、 正本の宣言は CLAUDE.md に置く ([CONVENTIONS.md#readme-style](../CONVENTIONS.md#readme-style)) |
| `home-redirect` (CLAUDE.md の「SESSION / README に書け」) | 行き先を種類で書き直す: 決定 → DESIGN.md、 成果物・状態 → 台帳 / 案件の記録、 SESSION は現在地の行を置き換える |
| `sot-claim` (README / SESSION 以外の file も含め、 「README / SESSION が正本」 と書いた行) | 指している中身を CLAUDE.md / DESIGN.md / conventions / 台帳へ移し、 その行は移した先を正本と書き直す。 README / SESSION には参照だけを残す。 公開 repo の build / quickstart / deploy の手順も正本は CLAUDE.md で、 README は利用者向けの写し ([CONVENTIONS.md#readme-style](../CONVENTIONS.md#readme-style)) |
| `archive-plaintext` / `session-decrypted` (暗号化している SESSION.md の中身が平文で入る) | `.gitattributes` で archive (`SESSION-archive.md` と `SESSION-archive/**`) にも SESSION.md と同じ filter を付けて同じ commit に入れる。 filter の driver が無い clone (未 unlock) では書かない。 平文で push した版は履歴に残る = 履歴から落とすのは別の作業。 この gate は形の escape hatch では外れない |

意図した例示・fixture で止まったときだけ `CLAUDE_SESSION_SHAPE_GUARD=0` で通す (出力に「何が止めたか」 が残る。 agent が使うのは本人の指示があるときだけ = [agent-rule-ownership.md#guard-escape-hatch](agent-rule-ownership.md#guard-escape-hatch))。 fleet の状態は `check-session-shape.py --fleet` (dashboard) で見る。 手で 1 file を見るときは `python3 scripts/check-session-shape.py --text SESSION.md < SESSION.md` (`--text` は本文を標準入力から読む = redirect なしだと入力を待って止まる、 [`shell-env.md#backgrounded-chain-still-runs`](shell-env.md#backgrounded-chain-still-runs))。

既存の file を一括で寄せる = [`scripts/migrate-session-shape.py`](../scripts/migrate-session-shape.py) (dry-run 既定。 日付つきの `##` 節と、 日付を含まない `##` の中の日付つき `###` 小節を archive へ verbatim MOVE し、 日付を含まない節と最新の状態は残し、 gate を通してから commit)。 archive が subdir のときは移した文の相対 link が段数ずれで壊れる = commit を止められたら `fix-md-links.py --files <archive file> --fix` で新しい base に合わせて commit し直す。 一括で寄せた後に残るのは、 日付の無い節の中に溜まった経緯 (形が同じで機械で区別できない) = その repo を次に触る commit で行数の予算が止める。

## 実測 evidence (2026-07-29/30)

個人層 memory file 276 KiB (= headless routine 全滅の実害) →
graduation 37 entry で 176 KiB → pointer 化 (38 bullet + 16 table row) で **130 KiB (−26.5%)**。
落とした義務・行動制約ゼロ (= gates 全 pass、 機械検査 74/74、 greppability 5/5、
構造 invariant 不変)。 うち bullet 平均は「wiring + 1-2 文 + ⚠️ + pointer」 で ~700-800 B
(CJK) に収束した — これ以下は routing 価値と衝突するので床として扱う。

**2 例目 (2026-09-10、 同 file の再肥大 → 再縮退)**: 154 KiB → **149 KiB**。 pointer 化 17 unit
(bullet 15 + table row 2) で −5 KiB = **1 unit あたり ~0.3 KiB**。 trim 後の bullet は 800-1000 B
に着地し、 上記の床 (~700-800 B) とほぼ一致した (= 床の再現性が 2 例で確認できた)。
**計画の目安**: 床に達していない unit しか原資にならないので、 削減見込み ≒ (未 trim unit 数)
× 0.3 KiB。 これで目標に届かないなら pointer 化ではなく構造変更 (= 列挙の生成 file 移設等) の
判断が要る — ただし移設は auto-load 面から降ろすことなので
[`convention-design-principles.md #symptom-keyed-entry-point`](../docs/convention-design-principles.md#symptom-keyed-entry-point)
の発火面判断とセットで決める。
