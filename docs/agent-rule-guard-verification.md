# 共通の規則保護: 2026-09-22 の検証記録

規則・原因分析・手順の正本は [agent-rule-ownership](../conventions/agent-rule-ownership.md)。本書は実装の検証証拠を持つ。個別案件の本文や裁定、機械ローカルの承認記録を公開側へ移していない。

整理した全資料の入口は [成果物と検収の記録](guard-review-records.md)。後続検収では機能の確認と別に性能の差し戻しがあり、以下の過去の限定 accept を全面受領と読まない。

## 先行する共通 gate の修正

`7f25cee` の原稿保護強化では次を再現して修正した。一般化後も回帰試験に残している。

| 再現した挙動 | 対策 |
|---|---|
| `stable → unstable`、`grows → drops` が近い綴りとして通る | 文字の距離を廃し、明示した英米綴りの組だけを通す |
| 呼出行を残したまま `exit 0`・発火条件・インデントを変えて検査を無効化できる | 配線を含む code・設定 file は周囲の制御も含めて保護 |
| 強化の承認が同一 session・file・領域の別の変更にも効く | 権限・設定の承認を具体的な候補全文の SHA-256 に束縛し、内容の違う変更には使わせない |
| 作業ツリーから input を外すと子原稿が範囲外になり得る | HEAD・index・作業ツリーの到達範囲を合わせて検査 |
| patch の move や絶対 path の Git を十分に見ない | 移動元の削除も検査し、絶対 path の Git commit を認識 |
| 公開 gate が削除だけの commit で原稿保護検査より前に終了する | 削除のみでも検査してから終了 |
| Git・設定・engine の故障が検査なしの通過になる | 「検査不能」を示して停止し、修復後に同じ操作を検査 |
| Codex app の user message 形式では本人の依頼を照合できない | `response_item` の本人発言を読み、assistant・tool 結果・既知の規約注入・subagent を除外 |


全体 CI の [今回の run](https://github.com/odakin/claude-config/actions/runs/35692071219) は 218 成功・6 失敗。原稿保護 engine・両 adapter・実 Git gate の試験は成功した。失敗は文書生成 3 件と installer/audit 3 件で、対象の実装・試験・依存指定は変更前と同じ。audit の「親 workspace の AGENTS.md がない」は変更前 `70204a2` と変更後 `7f25cee` の隔離 clone で同じ失敗を再現した。残る失敗の原因は本調査では確定していない。全体 CI を成功とは扱わず、失敗を通すための規制変更もしない。

後続 head `a29a2b7` の [CodeQL](https://github.com/odakin/claude-config/actions/runs/35692606926) は成功したが、同じ head の [総合 checks](https://github.com/odakin/claude-config/actions/runs/35692607515) は失敗した。以前の記録が前者を「CI 成功」とまとめたのは誤りであり、本記録で訂正する。一般化の反映直前の `396ac4d` でも [checks](https://github.com/odakin/claude-config/actions/runs/35705548140) は失敗していた。workflow 名・head・結果の対応を失わず、CodeQL の成功を全体の成功に転用しない。

## 検証対象と受領した指摘

従来の原稿保護 dispatcher から、一般の規則・制御ファイルの検出を [agent-rule-guard.py](../scripts/agent-rule-guard.py) へ分離した。既存の Claude / Codex / Git の呼出し名と承認経路は維持した。以下は架空の repository と規則で実行した。

| 修正前に再現した不足 | 修正版で確認したこと |
|---|---|
| marker のない AGENTS や hook の無効化設定を検出しない | 既定の指示文書・制御設定を全文検査 |
| 宣言された `.rb` などを拡張子で捨てる | manifest の宣言を拡張子より優先し、読めなければ検査不能 |
| 本文が同じ chmod や file type 変更を検出しない | Git mode / type と symlink の内容を検査し、候補の属性にも承認を束縛 |
| 保護 file の symlink 参照先、親 directory の symlink 経由を見落とす | HEAD / index / 作業ツリーごとに path の途中も解決し、link と実体を保護。repo 外への保護 link は検査不能 |
| 改行した Git 呼出しを逃し、引用した演算子を実行と誤認する | 引用・改行・here-document を区別する lexer で実行位置を検査 |
| 古い commit 検出が printf / here-document の例文を拒否する | bypass と commit の検出を共通の分割・引数解析に揃え、表示だけの正常例も全 hook 経路で確認 |
| symlink の参照先名で承認を記録し、link 自身の変更には効かない | link entry の identity を保持。別の内容・mode の変更には効かない |
| apply_patch の追加・更新の改行を再構成し違え、正しい候補を拒否する | 実 tool の bytes と比較し、空 file・元の末尾改行なし・patch 枠の改行を含む回帰例で確認 |

scope の削除は HEAD / index / 作業ツリーの和で防ぐ。保護 directory の隣の通常 file は一括保護されず、通常の編集・stage が通ることも確認した。質問 UI が user-role に再掲する質問文は本人発言に含めず、本人の answer だけを照合する反例も追加した。

## 独立検品

作業履歴を渡さない別の Codex context に、隔離した変更前・変更後の source と中立の要件を渡した。実環境・本人の発言・承認 state への access は与えていない。複数回の指摘を変更側で再現して修正し、最終の 22 項目の再検証で新たな重大指摘なし、対象範囲を accept と受領した。

最終検品の core source SHA-256:

| source | SHA-256 |
|---|---|
| `scripts/agent-rule-guard.py` | `ccb20b15d224fec33417ab08f597f5821c3e7fdf7cb088fc8f4c5faccc6db3d8` |
| `scripts/manuscript-claim-guard.py` | `3de871fa9745d5f73ada53c392f2b27aef1a74388b67881f624b6744e2173594` |
| `scripts/audit-codex-hook-runtime.py` | `aa4f9ddf0d5867240ed95066cb1e6eef4a9a65038c753a5f9713350101ddedf4` |

続く改行再構成の差分も独立検品し、native apply_patch の 9 ケース・改行枠ありなし・2 候補で計 36 の bytes 比較が一致した。未承認の拒否、正規候補の許可、別候補への転用拒否も確認した。

この verdict は列挙した経路の検品であり、全ての shell 表現や runtime の発火を証明しない。Python 3.10 / 3.11 の grammar として parse することも確認したが、それらの版で全試験を実行したという意味ではない。

## 回帰試験

最終候補で一般 engine と dispatcher の全 selftest、`hooks/manuscript-claim-guard.test.sh` の 68 件、`codex/hooks/codex-hooks.test.sh`、runtime audit の 7 件を実行して成功した。原稿の校正・数式・input graph・承認転用・検査不能の既存反例も維持している。新しい否定例だけでなく、通常 file の編集、例文の表示、mode に対応した正規の承認が通る正常例を含む。

リポジトリの `requirements.txt` を専用の一時 Python 環境に入れた全体検査は **223 成功・3 失敗**。失敗は `check-unpublished-quote.py` の wiring canary、`formcase.py` の font 行高、`install-hook-stubs.test.sh` の再生成試験だった。今回の未 commit 変更を含まない同時点の clone でも、3 件それぞれを同じ環境で再実行し、同じ失敗を確認した。今回のガード・両 adapter・runtime audit・installer/audit の対象試験は成功した。全体成功とは報告せず、これらの失敗を消すための規則変更も行っていない。

runtime の構成監査は [audit-codex-hook-runtime.py](../scripts/audit-codex-hook-runtime.py) が担う。`trusted` / `enabled` を読めても `live_dispatch=not_tested` と出し、実際の tool 呼出しによる確認と分ける。

## Git pathspec の誤拒否と見逃し

ディレクトリをそのまま file として読む実装は、普通のディレクトリでは検査不能、ドットを含む名前や glob では未検査の通過となった。`expand_commit_pathspec` は、元の作業ディレクトリと pathspec の集合を保持して Git へ渡す。HEAD から変わった追跡済み file と ignore を除く未追跡 file の和を選び、HEAD がない場合は cached file を使う。空の選択は何も検査せず、Git の失敗は検査不能として拒否する。

`git add -A` / `git add .` の後の commit に含まれる未追跡 file の検査も今回実装した。`commit -a` / `add -u` だけでは未追跡 file を含めない。 path commit は追跡済み file と先行 add で実際に stage される file のみを対象にする。`-Av` のような短縮 option の束、force で選んだ ignore 対象、dry-run、先行 add で取り消される index だけの式変更も実 Git と照合した。サブディレクトリの `add .`、Git magic、exclude pathspec、明示 path commit に含まれない他の add も対照にした。今回挙げられた未追跡 file の不足は見送っていない。

`hooks/manuscript-claim-guard.test.sh` に 24 件を追加した。要求された (a) 原稿のない未追跡 directory の add+commit、(b) directory 内の式、(c) ドットを含む directory 内の式、(d) glob 内の式は、修正前の本番 source で全て赤となることを確認した。(b) は単に deny では緑になってしまうため、`eq:pathspec` が原因であり `inspection unavailable` ではないことを検査する。修正版では 68 件全て成功した。 この追加差分も独立検品へ戻し、実 Git を用いた 24 確認で既報 3 件の解消と新たな重大指摘なしを確認した。

## Codex の実作業ディレクトリの欠落

実ツールの試験で、`exec_command.workdir` だけで指定した架空 repo の commit が検査から漏れ、絶対 `git -C` を書いた呼出しは拒否された。対象タスクだけの一時診断で、event の `cwd` は親タスクの場所、`tool_input` は `command` のみで、実作業先が欠落していることを確認した。診断はキー名・cwd だけを記録し、直後に撤去して検品済み source への復元を照合した。

実作業先の情報がない Codex 経路では、各 Git add/commit に絶対 `-C` がない呼出しを検査不能として拒否する。独立検品の 30 例で、条件付き cd・subshell・不正な workdir を推測せず、明示された作業先では保護式を本来の規則で検査し、通常操作・dry-run・Claude の経路を保つことを確認した。恒久的な runtime の契約と呼出し方は [Codex 統合仕様](../codex/PARITY.md#codex-integration-sot) が所有する。

## 実環境の確認

最終候補の反映後、デスクトップのこのタスクの実際の tool 呼出しで次を確認した。試験用 repo は架空であり、本番の制限を弱める試験変更は行っていない。

| 呼出し | 観測結果 |
|---|---|
| marker のない AGENTS の義務を撤廃する apply_patch | `authority:file` によって編集前に拒否 |
| manifest が指定する symlink の実装本体を書き換える apply_patch | 参照先の `authority:file` によって編集前に拒否 |
| 普通の README の進捗変更 | 許可され、保存した bytes も照合 |
| 実作業先が欠落した Bash commit | `inspection unavailable (working directory)` として実行前に拒否 |
| 絶対 `git -C` で指定した未承認の実行属性変更 | `authority:mode` によって実行前に拒否 |
| 未承認の属性変更が stage にあっても、別の普通の directory だけを指定する commit | 実 Git で成功。指定外の変更を誤って取り込まない |
| dot 付き directory / quoted glob の add + commit に新規の保護式を含める | 対象の abstract / equation によって実行前に拒否 |
| `--no-verify` による Git gate の省略 | bypass 自体を実行前に拒否 |
| printf / here-document 内の Git commit の例文 | 表示を許可し、実際の commit と混同しない |

これらは adapter に JSON を直接渡す試験と別の証拠である。別の host、版、実行経路の発火まで保証しない。

## 残る境界

一般の自然言語の義務、本人発言の許可の意味、未知の shell 表現、任意のプログラムからの実行、OS による権限分離はこの検証の対象外である。[保証の境界](../conventions/agent-rule-ownership.md#limits) を参照する。操作ごとの gate は引き続きその操作の直前で働く必要がある。

観測した誤停止 (fail-closed 側、2026-09-22): Bash の `cd $VAR` (変数) は展開されずに path として辿られ、存在しない path から親へ上がって cwd の repo に当たるため、一時 dir での `cd $T && git commit` が cwd の repo の未 commit 変更で deny された。直すなら変数を含む cd は検査不能 (`WorkingDirectoryUnavailable`) に倒す。未修正。

## 後続 reviewer の検収と未解決点

Claude reviewer は `ab95786` に対して独立の合成例を実行し、機能の分類を受領した。一方、追加済みの具体的な file 名を一つずつ Git pathspec として再展開する経路について性能を差し戻した。報告値は 150 file の binary で約 0.0→5.9 秒、text で約 4.0→9.0 秒、3000 text file の directory で約184秒。これらは reviewer の報告であり、本整理で新たに再計測した値ではない。20秒の hook timeout を超えた場合の実際の停止/通過は未確認と報告されている。

保存した観測 script とその限界は [成果物台帳](guard-review-records.md)。規模の軸と委任の境界は [review-handoff](../conventions/multi-session-coordination.md#review-handoff)、外部 process の回数と timeout の測り方は [hook-cost-per-item](../conventions/hook-authoring.md#hook-cost-per-item) が所有する。今回の資料整理は、この性能問題を解決したことにも、wiring の設計を採用したことにもならない。後続の担当へ引継ぎ済みである。

続く依頼元の追加報告では、commit の command に stdout の redirect (`> file` / `> file 2>&1`) があると inspection unavailable になる誤拒否が挙げられた。報告では `|| { … }`・command substitution・pipe と切り分けている。本整理で再現・修正した結果ではなく、後続担当への追加課題として受領した。

新しい保護 file の commit は、本文だけでなく追加による Git mode の差分にも既存の承認記録が必要、という操作上の注意も受領した。記録の正本は [共通の裁定手順](../conventions/agent-rule-ownership.md#approval) と CLI であり、ここで別の承認手順を新設しない。

上の未解決点 (性能・timeout・redirect・wiring の裁定) は、次の 2 節で解決した。mode の注意は [共通の裁定手順](../conventions/agent-rule-ownership.md#approval) の 3 に 1 文で足した。

## 規模の後退の修正 (2026-09-22、後続担当)

`ab95786` の pathspec 展開は、先行する `git add` で選ばれた file ごとに `:(literal)` の pathspec を 1 つ作り、commit の検査がそれを 1 つずつ Git に展開し直していた (1 file あたり git 約 5 回)。新しい text file はさらに HEAD の読み取りで約 4 回。対象外として読み飛ばす binary も展開の段で同じだけ払っていた。修正 = Git が展開した具体名をそのまま運ぶ (`GitNames`)、HEAD にある path の一覧を 1 回で取る (無い path は git を呼ばない)、blob は `git cat-file --batch --filters` で 1 回にまとめる (空白を含む path は 1 件ずつ、batch が失敗したら従来の 1 件ずつに戻る)、file ごとの `rev-parse` を repo 既知のときは省く。

実測 (同じ machine、hook 1 回の壁時計。fixture = 架空 repo に未追跡の text file N 個、command = `git add big/ && git commit -m x -- big/`):

| 入力 | 修正前 (`a8ce60c`) | 修正後 |
|---|---|---|
| 150 text | 9.6 s | 0.23 s |
| 500 text | 28.7 s (> timeout 20 s) | 0.24 s |
| 3000 text | 201 s | 0.37 s |
| 150 / 3000 PDF (対象外) | 6.3 s / — | 0.23 s / 0.27 s |
| 150 / 3000 追跡済み .tex を変更 (`commit -a`) | 8.6 s / — | 0.32 s / 1.8 s |
| 3000 staged text の pre-commit | — | 1.3 s |

engine の selftest が git の呼び出し回数を数える (件数に依らないこと): 未追跡 dir の add + commit で 40 file と 80 file が同じ 19 回、`commit -a` の 80 file 変更で 11 回、staged 40 file の pre-commit で 10 回。`hooks/manuscript-claim-guard.test.sh` に 3000 file の 3 経路 (add + commit -- dir/、`commit -a`、git-precommit) の経過時間 < 10 s と、3000 file の中の未追跡の原稿を止める陽性対照を足した。ab95786 の検収で使った正しさの例 (dot 付き dir・glob・`:(glob)`・`:!` 除外・`add -A` の新原稿・dir の削除は止める / ignore だけの dir・空白入り dir・非原稿の dir は通す / 不正な magic は検査不能) は同じ test で変わらず通る。依頼元の独立 harness ([guard-review-pathspec.sh](../scripts/guard-review-pathspec.sh) / [guard-review-compare.py](../scripts/guard-review-compare.py)) の結果は下の表。

**redirect の誤停止と素通り**: 依頼元の追加報告 (`> file` で inspection unavailable) を再現すると、`> /dev/null` と `< /dev/null` は検査不能、`2>/dev/null` と `> log 2>&1` は **素通り** だった (`2>/dev/null` が何にも当たらない pathspec になり、`commit -a` の原稿の変更が空の選択として通る)。修正 = shell の分割で redirect (`[fd]>` `>>` `>|` `<` `<>` `&>` `&>>`、`&fd` の複製、対象の語) を引数から外す。対象の無い redirect は分割の失敗 (= bash も構文 error)。検査 = 述語の selftest 10 件、engine の selftest 3 件、hook 経由の 3 件 (修正前は検査不能 1 件・素通り 2 件で赤)。`--no-verify` の検出は redirect の後ろでも効く。

**timeout 超過は素通り (実測)**: Claude Code CLI 2.1.198 で、project settings に「4 s 待ってから deny を返す」 PreToolUse hook を置き、timeout 1 s なら `touch` が実行され (fail-open)、timeout 10 s なら止まった。desktop の埋込 engine 2.1.275 の hook runner も、打ち切り (abort) を「status 1・stdout なし・aborted」 に畳む同じ経路。公式 docs はこの挙動を書いていない。記録先 = [manuscript-claim-ownership.md#limits](../conventions/manuscript-claim-ownership.md#limits)。Codex の hook の timeout 挙動は未測定。

## 配線 lock の範囲 (2026-09-22、後続担当)

裁定と理由の正本 = [agent-rule-ownership.md#wiring-scope](../conventions/agent-rule-ownership.md#wiring-scope)。実装 = `authority_regions()` が、engine の名前への言及が全部 `agent-authority` の block の中にある file では `authority:wiring` を出さない (block は `authority:<id>` として従来どおり領域)。同じ id の block が複数あれば `authority:<id>~2` … として全部を領域にする (以前は最後の block だけが残り、前の block の変更が見えなかった)。canary は判定・時刻・呼び元を state に書き、SessionStart の `--liveness` が古ければ走らせ直して NOT ARMED と報告の途絶えを出す。

検査 (全部、修正前の部品では赤):

| 性質 | test |
|---|---|
| block の外の行は通る / block の中の呼出し行・marker の削除は止まる / 言及が block の外に残る file は全文のまま / marker の id にある名前は block の外 / 閉じ忘れは末尾まで / 宣言済み・組み込みの file lock は block で解除されない / 同じ id の block は全部が領域 | `agent-rule-guard.py --selftest` (+11)、hook 経由の Edit と Bash commit = `manuscript-claim-guard.test.sh` (+5) |
| canary が state を書く / 健全なら沈黙 / 14 日途絶えた呼び元を 🟡 / 古い state は走らせ直す / 配線切れは NOT ARMED と exit 1 → 🔴 | `manuscript-claim-guard.test.sh` (+6) |
| 迂回の形: 手前の `exit 0`・`run()` の差し替えは報告が更新されない (陽性対照 = 元の script は更新する) / `|| true` は script の exit を 0 にするが NOT ARMED は表に出る | 同 (+5) |

**修正前で赤** (修正前 = `a8ce60c` の hook / engine / 述語に、新しい test をそのまま当てた):

| 新しい test | 修正前の結果 |
|---|---|
| engine selftest の git 回数 (40 / 80 file の add + commit -- dir/) | 390 回 / 750 回 = 1 file あたり 9 回 (修正後 19 / 19) |
| test.sh の規模 3 経路 (3000 file、< 10 s) | 190.6 s / 22.9 s / 43.7 s で 3 件とも赤 (修正後 0.4 / 1.3 / 1.3 s) |
| 述語の selftest (block 限定・同じ id の block) | 「block の外は普通」「全文の領域を出さない」「同じ id の block を全部守る」「同じ id で領域を分ける」 の 4 件が赤。block の中・marker の削除・外の言及・閉じ忘れ・宣言済み file の 6 件は修正前も通る (= 全文 lock の下でも守られていた性質) |
| test.sh の block 化 (hook 経由の Edit / Bash commit) | 「block の外の行は自由」 2 件が赤、止める側の 3 件は修正前も通る |
| test.sh の redirect | `> /dev/null` = 検査不能、`2>/dev/null` と `> log 2>&1` = 素通り (allow) の 3 件が赤 |
| test.sh の生存記録 | 11 件のうち 7 件が赤 (state が書かれない / 沈黙しない / 🟡・🔴 が出ない / 走らせ直さない / 陽性対照が更新しない / `|| true` で NOT ARMED が出ない)。迂回 2 件 (手前の `exit 0`・`run()` の差し替え = 「報告が更新されない」) は、修正前は state 自体が無いので空同士で一致して緑 — 陽性対照の赤がそれを補う |

修正前の hook は `--liveness` を知らず hook mode で stdin を読むため、旧 guard での run は stdin を閉じ、規模の節を外し、`set -e` を外して最後まで走らせた (規模の節は上の別 run)。合計 75 通過 / 12 赤。新しい hook は `--liveness` で stdin を読み切ってから判定する (SessionStart の入力を捨てて EPIPE にしない)。

依頼元の独立 harness (Codex が `2c277c4` で上層へ移したもの) を候補に当てた結果:

| harness | 結果 |
|---|---|
| `scripts/guard-review-pathspec.sh` (GUARD_REVIEW_HOOK = 候補の hook) | 20 / 20 (非原稿 4・保護の変更 9・新規/削除 4・非保護 1・fail-closed 1・規模 3000 file = 0.7 s) |
| `scripts/guard-review-compare.py 300 --before-ref 7f25cee` (text 300 file) | hook「add files && commit -- files」 15.9 s → 0.3 s / 「add dir && commit -- dir」 InspectionError (7f25cee の dir の誤拒否) → 0.2 s ok / pre-commit (index) 19.7 s → 0.2 s。PDF は両方 0.1〜0.2 s。3000 file は 7f25cee 側が長すぎて打ち切った (候補側の 3000 は上の表と pathspec harness) |
| `scripts/guard-review-profile.py 150 .txt` (候補) | `subprocess` の communicate 10 回 = git 10 回で 150 file (件数に依らない) |

## 報告経路の修正候補の照合用 SHA-256 (2026-09-26)

以下は候補確認後の修正内容の識別子であり、先行する独立検品の hash を置き換えない。構成監査と実際の Stop 発火は別々に確認する。

| source | SHA-256 |
|---|---|
| `scripts/manuscript-claim-guard.py` | `333252a3a627e044107bb58555eeee536ee50f36835ef072ccf80f973ec789e1` |
| `scripts/audit-codex-hook-runtime.py` | `d2cf7c1c67a0dd32e1c96ba5570f83197ed3c413d6de9afde3b988650df7f529` |
| `scripts/audit-codex-integration.sh` | `37ea54f50b009cd85deafdb89a158d2821fdcf8eba0a9179e403558b6674ea4b` |
| `hooks/manuscript-claim-guard.test.sh` | `111cce1a000b96a6bc0110a61c450adec474002e44ab6734aa1e1f6ce2cf20b7` |
| `codex/hooks/codex-hooks.test.sh` | `1c06aac89cf8e089b297e8db8998a48b1824d41e734e27fdae39676571412abf` |

## 承認の引用元の修正候補の照合用 SHA-256 (2026-09-26)

| source | SHA-256 |
|---|---|
| `scripts/manuscript-claim-guard.py` | `8970c42e970c8e6904e180a15f55efa716dbdfea4fd583940153978d149003e4` |
| `hooks/manuscript-claim-guard.test.sh` | `2ecfd1adbfb04f9d8d2d19b36ea900d3c7785fe35839aff095b1ddeb992ad17e` |
| `codex/hooks/codex-hooks.test.sh` | `99b7ba51fd832b626686b145fb6922a10efe7d55cde6e12c44fca2e3bd4dcab7` |
