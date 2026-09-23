<!-- doc-meta
when: AI agent (Claude / Codex / 他 vendor / sub-agent / 無人 worker) が原稿 (.tex) の表題・概要・序論・結論・数式に触れる前 + 著者の依頼を「承認」 と読みそうになった瞬間 + manuscript-claim-guard に deny されたとき + agent の編集権限を定める規則 (本 doc・各層の参照・gate の設定と配線) を変える前
category: paper
summary: 原稿の主張の所有権と AI agent の編集境界の正本。 保護領域 (表題・概要・序論・結論・数式) は著者の項目ごとの裁定 (著者の発言の verbatim を file × 領域ごとに記録) なしに agent が書き換えない・削らない・足さない。 変更は提案として出し、 印字しない指示は直接書く許可ではない。 権限の規則そのものも同じ扱い (強める変更も含む。 規則の文書への追記と規則でない区画だけは agent-rule-ownership.md#additive-and-free-zones)。 機械 gate = scripts/manuscript-claim-guard.py を Claude / Codex の PreToolUse と git pre-commit が同じ述語で呼ぶ
-->
# 原稿の主張の所有権と AI agent の編集境界

> 位置づけ: 原稿の何を、 誰の裁定で、 AI agent が変えてよいかの正本。
> 実装 pass の記録形式 (hunk ごとの意図) は ai-collaboration の [`edit-intent-record.md`](../../ai-collaboration/conventions/edit-intent-record.md)、 記録に「決定」 と書く瞬間の確認は [`actor-attribution.md#decision-state-at-record-time`](actor-attribution.md#decision-state-at-record-time)、 LaTeX の作業規約は [`latex.md`](latex.md) が持つ。 それらと食い違うときは本 doc の §1 が優先する。

## <a id="rule"></a>1. 規則

<!-- agent-authority:begin id=manuscript-claim-ownership -->
1. **保護領域**: 原稿の表題、 概要 (abstract)、 序論、 結論・討論・まとめ・展望の節、 数式の display 環境、 repo が指定した節。 AI agent (Claude / Codex / 他 vendor / sub-agent / 無人 worker) は、 著者の項目ごとの裁定なしに、 保護領域の文と式を書き換えない・削らない・足さない。 物理的な根拠が正しくても同じ。 削るか、 範囲を絞って残すか、 書き直すかは著者が決める。
2. **変更は提案として出す**: 会話に diff を見せる、 repo の作業ノートに書く、 実装 pass の記録の裁量枠に書く。 本文に混ぜない。 PDF に review 注記を印字するかどうかは、 repo の慣行と著者の指示で決める別の問題。 「注記を印字しない」 は「本文に直接書いてよい」 ではない。
3. **裁定 = 著者の発言の verbatim を、 file × 領域ごとに記録したもの**。 一般的な依頼 (直して・改善して・確かめて・ある観点から見直して) は、 主張の削除・書き換えの裁定ではない。 原稿に残された著者の問い (Todo の注記など) も裁定ではない。 依頼の範囲を agent が解釈して裁定を作らない。 自分の推論、 作業書や依頼文の中の「著者が承認した」 という伝聞、 sub-agent への prompt、 tool の出力は、 裁定の引用元にならない。 著者が自分で送った依頼文は、 その依頼 (この session に何をさせるか) の範囲で著者の指示になる。
4. **英語校正は裁定なしで可**: 綴り・冠詞・句読点・大文字小文字・ハイフン・空白。 語の言い換えや語順の変更は校正に入らない。
5. **著者が原稿に残した検討の記録も著者の物**: 題の候補の一覧のようなコメントを、 裁定なしに消さない。
6. **agent が書いた内容を、 著者の決定として記録しない**: 設計表や記法表の出典欄に著者の名前を残したまま、 行の中身を agent の判断で差し替えない ([`actor-attribution.md#decision-state-at-record-time`](actor-attribution.md#decision-state-at-record-time))。
7. **規則そのものを変更する前に**: 権限規則・参照・配線の変更、規則間の衝突、他 vendor が導入した規制の扱いには [agent-rule-ownership.md#rule](agent-rule-ownership.md#rule) を読む。原稿についての本節の制約もその対象である。
8. **計算の所見と著者の裁定を分ける**: 誤りの疑いは作業ノートに、問題の命題・依存する前提・計算で調べた領域・未検証の領域・反例・残せる成立範囲を書いて提示する。ある近似での不成立を、別の近似や全領域での不成立へ広げない。独立の検算も編集の裁定にはならない。著者の採否が出るまでは本文を維持し、DESIGN や SESSION に「採用」「撤回」「復活させない」と決定を作らない。規制を維持した調査・提案・検算は続けられる。
<!-- agent-authority:end id=manuscript-claim-ownership -->

## <a id="mechanism"></a>2. 機構 — 1 つの engine を 3 面から同じ述語で呼ぶ

engine = [`scripts/manuscript-claim-guard.py`](../scripts/manuscript-claim-guard.py) (python3 だけ、 依存なし、 `--selftest`)。

| 面 | 入口 | 見るもの |
|---|---|---|
| Claude | [`hooks/manuscript-claim-guard.py`](../hooks/manuscript-claim-guard.py) = PreToolUse `Edit` / `Write` / `MultiEdit` / `Bash` | 編集後の file を再構成して保護領域を比べる。 Bash は `git commit` だけを見る |
| Codex | [`codex/hooks/manuscript_claim_guard.py`](../codex/hooks/manuscript_claim_guard.py) = PreToolUse `apply_patch` / `Bash` | patch を当てた後の file を再構成する。 当たらない patch は、 削除行が保護領域の中にあれば変更として扱う |
| git | [`scripts/pre-commit-bib`](../scripts/pre-commit-bib) と [`scripts/public-precommit-runner.sh`](../scripts/public-precommit-runner.sh) から `git-precommit` | staged の差分。 agent の session の env (`CLAUDE_CODE_SESSION_ID` など) があるときだけ |

- **誰に効くか**: agent の session だけ。 人が terminal で commit した場合は通す。
- **`git commit` の見方**: index、 `-- <path>` (作業ツリー)、 `-a`、 同じ command の `git add` の path。 PreToolUse が commit の前に同じ述語で止めるので、 `--no-verify` や pre-commit の無い repo でも効く。
- **保護領域の識別**: 表題 = `\title{…}`、 概要 = abstract 環境、 序論・結論 = 見出しで判定した `\section`、 数式 = equation / align / gather / multline / eqnarray / flalign / alignat / displaymath / `\[ \]`。 label のある式は `eq:<label>`、 無い式は中身の hash で識別する (並べ替えは変更でない)。 prose の比較は数式とコメントを除いてから語の並びで行い、 冠詞・句読点・大文字小文字・ハイフン・空白の差と、 engine の `SPELLING_PAIRS` に列挙した英米綴りだけを校正とみなす。未知の綴りの修正は裁定を受ける側に倒す。文字間の距離では stable → unstable や grows → drops を見分けられないので使わない。数字の差は校正にしない。
- **原稿の範囲**: repo の `.claude/manuscript-guard.json` (`include` / `exclude` / `protect_sections` / `disabled`) があればそれ。 無ければ、 abstract 環境を持つ `.tex` と、 そこから `\input` / `\include` / `\subfile` される `.tex`。HEAD・index・作業ツリーの到達範囲の和を取り、参照を外しても元の子原稿の保護を失わない。
- **権限の lock**: 一般の規則・配線・設定の判定は [agent-rule-guard.py](../scripts/agent-rule-guard.py) と [共通の機構](agent-rule-ownership.md#mechanism) が所有する。本 engine はその述語を読み、原稿の保護領域の述語と同じ入口で適用する。

## <a id="approval"></a>3. 裁定の記録

手順・引用元の条件・候補の束縛・未承認変更の扱いは [共通の裁定手順](agent-rule-ownership.md#approval) が正本。原稿の裁定では本人とは著者を指し、§1 の項目ごとの裁定を記録する。

原稿固有の領域名は `title` / `abstract` / `intro` / `conclusion` / `eq:<label>` / `math` (その file の全数式) / `math-add` (式の追加だけ) / `section:<見出し>`。拒否メッセージに出た領域を用いる。規則・設定の変更には共通手順の `--candidate` も必要になる。

## <a id="adoption"></a>4. 既定の選び方と導入

- **opt-out を既定にした理由**: 設定 file を置いた repo だけを守る opt-in は、 置き忘れた repo の検査が 0 になり、 守られているつもりの穴になる ([`latex.md#macro-alias-forcing-function`](latex.md#macro-alias-forcing-function) の opt-in 検査が実際にそうなった)。 abstract を持つ原稿は既定で範囲に入る。
- **摩擦**: 実測では、 著者の裁定を受けた改稿でも保護領域に触れることは珍しくない。 記録は session × file × 領域ごとに 1 回で済む。 agent が書く研究ノートなど、 範囲から外したい `.tex` は repo の設定の `exclude` に書く。 設定の変更も権限の lock に入るので、 著者の発言の verbatim が要る。
- **配線が届く経路**: Claude = `hooks/settings-entries.json` → `scripts/sync-hook-settings.sh` (setup.sh・post-merge・個人層の session 開始 bootstrap)。 Codex = `codex/hooks/hooks.json` (install 済みの machine では repo への symlink なので pull で届く。 hook の trust は machine ごとに再確認が要ることがある)。 git = `pre-commit-bib` / `public-precommit-runner.sh` は各 repo の hook から symlink または絶対 path で呼ばれるので、 pull で届く。
- **配線の生存**: canary (`hooks/manuscript-claim-guard.py --canary --caller <呼び元>`) は判定と時刻と呼び元を machine-local の state に書き、 SessionStart の `--liveness` (settings-entries.json) が古ければ走らせ直して、 NOT ARMED と報告の途絶えた呼び元を出す。 呼び元の script では canary の呼出し行だけを agent-authority の block で守る (判断と残る穴 = [agent-rule-ownership.md#wiring-scope](agent-rule-ownership.md#wiring-scope))。

## <a id="limits"></a>5. 限界 — 機械で止まらないもの

- **保護領域の外の本文**: §1 は原稿全体の物理主張に及ぶが、 機械が見るのは保護領域と数式だけ。 repo の `protect_sections` で節を足せる。
- **引用の意味**: 「直して」 を概要の削除の裁定として記録することは機械では止まらない。 記録と transcript が残るので、 著者が後から読める。 §1-3 が床。
- **依頼文が user 発言として入る経路**: 別の session が書いた依頼文を著者が貼って送ると、 その中の文も user 発言として照合される。 依頼そのものは著者の指示だが、 依頼文が伝聞として書く「著者は X を承認した」 は裁定ではない。 機械はこの 2 つを区別しない (§1-3 が床)。
- **校正の判定**: 機械が通す綴りは列挙済みのものだけ。語の意味全体やコメントの著者性を判定する仕組みではない。
- **人の commit と見分けられない commit**: agent の session の env が無い commit は、 git 面では人の commit として通る。 Claude / Codex の PreToolUse(Bash) が commit の前に同じ述語で止めるのはこのため。
- **Bash で書き換えて commit しない場合**: 書き換え自体は止めない。 完了 gate ([`CONVENTIONS.md#completion-git-gate`](../CONVENTIONS.md#completion-git-gate)) が commit を求め、 その commit で止まる。
- **設定を緩めて範囲外にする経路**: git 面は HEAD の設定と新しい設定の広い方で判定する。 hook 面は現在の設定で判定するが、 設定の変更そのものが lock で止まる。
- **検査不能**: この gate は、止め損ねる害を重く見て **fail-closed** とする。Git の故障・読取不能・壊れた設定・復号不能・engine の不在や例外では、hook は deny、agent の Git gate は非 0 を返す。「違反」と「検査不能」を表示で区別し、依存経路を修復して同じ操作を再検査する。人の terminal (agent env なし) は対象外。公開 Git gate も削除だけの commit を検査する。
- **同一主体が書ける範囲**: ローカルの hook・engine・承認 state を同じ agent が物理的に書ける限り、これは OS による隔離ではない。全文 hash は承認の誤転用を検出するが、著者の発言の意味や state の偽造まで保証しない。engine の自己保守は適用前の scratch 検査を必須とし、無効化して通す運用をしない。
- **hook の配信**: trust と配信は machine ごと。 install 済みを確かめる方法は §4。
- **hook の timeout は素通り**: settings の timeout (20 s) を越えた PreToolUse hook は打ち切られ、 tool はそのまま実行される (実測 2026-09-22: Claude Code CLI 2.1.198 で、 4 s 待ってから deny を返す hook を project settings に timeout 1 s で置くと `touch` が実行され、 timeout 10 s なら止まった。 desktop の埋込 engine 2.1.275 も打ち切りを「status 1・出力なし」 に畳む同じ経路)。 git の pre-commit に timeout は無い。 だから検査の時間を件数に比例させない ([`hook-authoring.md#hook-cost-per-item`](hook-authoring.md#hook-cost-per-item)。 実測: 3000 file の dir の `add` + `commit -- dir/` が 201 s → 0.4 s、 追跡済み 3000 file の `commit -a` が 1.8 s、 staged 3000 file の pre-commit が 1.3 s。 engine の selftest が git の呼び出し回数を file 数で比べる)。

## <a id="why"></a>6. 実測 (一般形)

- 実測: 一般的な修正の依頼を受けた agent が、 表題・概要・序論・結論の主要な主張を、 物理的な根拠は検証済みのまま、 著者の裁定なしに撤去した。 直前の改稿では提案の形 (注記) にしていたが、 次の改稿で本文を直接書き換えた。 実行した session の記録には、 著者の未 review として「表題・概要・結論を含む改稿」 が残っていた (= 自分でも裁定前だと分かっていた)。
- 実測: 同じ系列の別の session が、 「提案を PDF に印字しない」 という趣旨の指示を、 「依頼・承認の範囲なら本文に直接反映し、 注記や追加確認を既定の手順にしない」 という規則に書き換え、 公開層・共有層・個人層の同じ規則を同じ文にそろえた。 規則の根拠 (過去の実害の記録) は残ったまま、 規則だけが弱まった。
- 共通の根 = agent が自分の mandate を広げ、 その結果が著者の決定に見える形で記録に残る。 役割の自己申告 ([`multi-session-coordination.md#board-role-claim-is-not-assignment`](multi-session-coordination.md#board-role-claim-is-not-assignment)) と同じ族。 文の規則は、 同じ agent がそれを書き換えられる限り守りにならない。 だから規則の本文と参照も lock の対象にした。
