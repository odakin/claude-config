# 共通の規則保護: 2026-09-22 の検証記録

規則・原因分析・手順の正本は [agent-rule-ownership](../conventions/agent-rule-ownership.md)。本書は実装の検証証拠を持つ。個別案件の本文や裁定、機械ローカルの承認記録を公開側へ移していない。

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
