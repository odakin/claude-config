<!-- doc-meta
when: AI agent (Claude / Codex / 他 vendor / sub-agent / 無人 worker) が原稿 (.tex) の表題・概要・序論・結論・数式に触れる前 + 著者の依頼を「承認」 と読みそうになった瞬間 + manuscript-claim-guard に deny されたとき + agent の編集権限を定める規則 (本 doc・各層の参照・gate の設定と配線) を変える前
category: paper
summary: 原稿の主張の所有権と AI agent の編集境界の正本。 保護領域 (表題・概要・序論・結論・数式) は著者の項目ごとの裁定 (著者の発言の verbatim を file × 領域ごとに記録) なしに agent が書き換えない・削らない・足さない。 変更は提案として出し、 印字しない指示は直接書く許可ではない。 権限の規則そのものも同じ扱い (強める変更も含む。 規則の文書への変更のうち緩和の語を足さず既存の文を隠さないものと、 規則でない区画の中だけは agent-rule-ownership.md#additive-and-free-zones)。 機械 gate = scripts/manuscript-claim-guard.py を Claude / Codex の PreToolUse と git pre-commit が同じ述語で呼ぶ
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
- **保護領域の識別**: 表題 = `\title{…}`、 概要 = abstract 環境、 序論・結論 = 見出しで判定した `\section`、 数式 = equation / align / gather / multline / eqnarray / flalign / alignat / displaymath / `\[ \]` / `$$ $$`。 label のある式は `eq:<label>`、 無い式は中身の hash で識別する (並べ替えは変更でない)。 prose の比較は数式とコメントを除いてから語の並びで行い (`$$ $$` は 1 つの数式の語として prose の比較にも残す = 開きと閉じが同じ記号なので、 文書全体と節の中で組み方が食い違っても中身が比較から落ちない。 保護節の `$$` は語と式の両方で比べる)、 verbatim 系 (`\verb|…|`・verbatim 環境) の中の記号では数式を開きも閉じもせず (`$$` の組・`\[ \]`・環境の始まりと終わり)、 prose では verbatim を 1 つの語として比べ (中の記号と語の区切りの変更も変更として出る。 `comment` 環境は中を今までどおりの語として読む)、 verbatim の中の式の形の文字は今までどおり式の領域にも残す。 節は原文の見出しで切った形と、 verbatim・comment の中の見出しを読まない形の両方で比べ、 どちらかで変われば出す。 節の語が式として外した式のうち、 文書全体の読みが同じ位置の式として読まないもの (verbatim の読み方が節と文書全体で食い違う所) は節の変更として比べる。 冠詞・句読点・大文字小文字・ハイフン・空白の差と、 engine の `SPELLING_PAIRS` に列挙した英米綴りだけを校正とみなす。未知の綴りの修正は裁定を受ける側に倒す。文字間の距離では stable → unstable や grows → drops を見分けられないので使わない。数字の差は校正にしない。
- **macro で包んだ数式環境も保護領域**: 原稿が display 数式を 1 引数の macro で包んでいる場合 (`\newcommand{\al}[1]{\begin{align}#1\end{align}}` 型。 `\def\al#1{…}`・xparse の `{m}`・本体が `\[#1\]`・`$$#1$$` のものも)、 その macro の brace の引数を上の数式と同じ識別で読む。 定義は、 編集する file を含む原稿 (abstract を持つ `.tex` か設定の `include` の `.tex` から、 `\input` 系・`\usepackage` 系・`\documentclass` 系で辿れる `.tex` / `.sty` / `.cls` / `.def` / `.clo`) から拾う。 読み込み先は参照元の dir と repo の root で探し、 `\usepackage` 系・`\documentclass` 系で見つからなければ同じ名前の file を全部読む (`\input` 系の解決できない行は辿らない)。 版は作業ツリー (ignore されていない未追跡を含む)・index・HEAD のすべてで、 原稿の起点になるのは追跡済みの file と編集中の file だけ。 読み込みと定義を探すときは verbatim 系の中を読まない。 拾えない定義 (repo の外の preamble、 別の書き方) は `.claude/manuscript-guard.json` の `math_macros` に macro 名を列挙する。 その原稿の範囲で wrapper の名前の定義が変わる変更 (消す・wrapper と読めない形に書き換える・再定義を足す・定義の file の読み込みを外す) も、 式の変更として止める。 原稿の範囲の外の file (`.sty` など) の編集でも、 原稿が読み込む file ならこの検査だけは受ける。 包む環境の種類 (`align` と `align*` など) の差は、 直の環境と同じく変更とみなさない。 定義の変更を著者が承認した後は、 新しい定義で読む (wrapper でなくなった macro の引数は式として読まない)。 引数が 2 つ以上の wrapper と、 brace を使わない引数は見ない。
- **原稿の範囲**: repo の `.claude/manuscript-guard.json` (`include` / `exclude` / `protect_sections` / `disabled`) があればそれ。 無ければ、 abstract 環境を持つ `.tex` と、 そこから `\input` / `\include` / `\subfile` される `.tex`。HEAD・index・作業ツリーの到達範囲の和を取る。 commit の前 (HEAD) と後で到達範囲が変わる file は、 外れる file (commit の後も在るもの) を HEAD の全領域の削除、 入る既存の file (abstract の無いもの) を commit の後の全領域の追加として比べる。 保護領域の外の `\input` の行を消す・コメントにする・別の file に向け直す commit は、 外れる子原稿の領域で止まる。 削除・追加・移動される file はこの比較に入れない (path ごとの比較と移動の扱いが持つ)。 範囲を `include` で決める repo は読み込みに依らないので見ない。
- **権限の lock**: 一般の規則・配線・設定の判定は [agent-rule-guard.py](../scripts/agent-rule-guard.py) と [共通の機構](agent-rule-ownership.md#mechanism) が所有する。本 engine はその述語を読み、原稿の保護領域の述語と同じ入口で適用する。

- **移動**: 同じ commit (または同じ patch の `Move to:`) で消えた path と、 まだ無かった path に現れた file を 1 対 1 で組み (中身が一致する組が先、 残りは同じ拡張子で空でない行の重なり 50% 以上)、 旧い path の領域と新しい path の領域を比べる。 旧い path にあって新しい path に同じ名前で無い領域 (移動先が範囲の外・数式を包む macro の定義を読めなくなる分を含む) は delete、 新しい path にだけ在る領域は add、 中身を変えた分は両方の path の文脈で書き換えとして比べる。 finding は新しい path に付く。 組み方は承認の件数を決めるだけで、 どう組んでも保護され続けない領域は残る。 組まない (従来どおり path ごと) = 旧い path を残す複製、 既存の file への上書き、 移動した file が読んでいた子原稿を移動後に読まない、 読み込みで原稿に入っていた file が commit の後の読み込みに無い (Codex の編集の時点では abstract の無い file の移動)。 権限の lock (`authority:*`) の finding は移動でも path ごと。 Bash の `git mv` / `git rm` / `mv` そのものは検査せず、 commit の時点で staged の差分として見る。

## <a id="approval"></a>3. 裁定の記録

手順・引用元の条件・候補の束縛・未承認変更の扱いは [共通の裁定手順](agent-rule-ownership.md#approval) が正本。原稿の裁定では本人とは著者を指し、§1 の項目ごとの裁定を記録する。

原稿固有の領域名は `title` / `abstract` / `intro` / `conclusion` / `eq:<label>` / `math` (その file の全数式) / `math-add` (式の追加だけ) / `section:<見出し>`。拒否メッセージに出た領域を用いる。規則・設定の変更には共通手順の `--candidate` も必要になる。

`section:<見出し>` の見出しは `\section{…}` の文字列 (小文字化) であって、 label (`sec:…`) ではない。 記録の前に source の `\section{` 行から取る (`scan` は差分が無いうちは何も出さない)。 領域を誤って記録すると、 書き込みは通っても commit で止まり、 引ける発言は最新のものだけなので、 著者に同じ裁定を言い直してもらうことになる (実測)。 記録と最初の書き込みは別の tool call にする: 同じ command 行に `approve && 書き込み` と並べると、 書き込みの検査が記録より先に走って止まる。 `git commit` も同じで、 同じ command 行の記録は commit の検査に間に合わない (実測)。 file を改名・移動したとき (同じ commit で旧い path が消え、 まだ無かった新しい path に現れる。 Codex の `apply_patch` の `Move to:` も同じ) は、 同じ原稿の書き換えとして比べる: 中身が同じなら記録は要らない。 中身も変えたなら、 変わった領域だけを新しい path で記録する (`--file <新しい path>`)。 旧い path を残す複製・既存の file への上書き・移動先が原稿の範囲 (設定の `include` / `exclude`、 `\input` の到達範囲) の外になる移動・子原稿を親の `\input` から外す移動は、 従来どおり旧い path の削除と新しい path の追加の両方を記録する。 `\input` の行を消すと、 その行を含む節の変更として数える。 保護領域の外の行でも、 子原稿が原稿の読み込みから外れれば、 その子原稿の全領域の削除として数え、 記録は子原稿の path で取る (`--file <子原稿>`)。 原稿に入っていなかった既存の file を読み込む行を足すと、 その file の全領域の追加として数える。

## <a id="adoption"></a>4. 既定の選び方と導入

- **opt-out を既定にした理由**: 設定 file を置いた repo だけを守る opt-in は、 置き忘れた repo の検査が 0 になり、 守られているつもりの穴になる ([`latex.md#macro-alias-forcing-function`](latex.md#macro-alias-forcing-function) の opt-in 検査が実際にそうなった)。 abstract を持つ原稿は既定で範囲に入る。
- **摩擦**: 実測では、 著者の裁定を受けた改稿でも保護領域に触れることは珍しくない。 記録は session × file × 領域ごとに 1 回で済む。 agent が書く研究ノートなど、 範囲から外したい `.tex` は repo の設定の `exclude` に書く。 設定の変更も権限の lock に入るので、 著者の発言の verbatim が要る。
- **配線が届く経路**: Claude = `hooks/settings-entries.json` → `scripts/sync-hook-settings.sh` (setup.sh・post-merge・個人層の session 開始 bootstrap)。 Codex = `codex/hooks/hooks.json` (install 済みの machine では repo への symlink なので pull で届く。 hook の trust は machine ごとに再確認が要ることがある)。 git = `pre-commit-bib` / `public-precommit-runner.sh` は各 repo の hook から symlink または絶対 path で呼ばれるので、 pull で届く。
- **配線の生存**: canary (`hooks/manuscript-claim-guard.py --canary --caller <呼び元>`) は判定と時刻と呼び元を machine-local の state に書き、 SessionStart の `--liveness` (settings-entries.json) が古ければ走らせ直して、 NOT ARMED と報告の途絶えた呼び元を出す。 呼び元の script では canary の呼出し行だけを agent-authority の block で守る (判断と残る穴 = [agent-rule-ownership.md#wiring-scope](agent-rule-ownership.md#wiring-scope))。

## <a id="limits"></a>5. 限界 — 機械で止まらないもの

- **保護領域の外の本文**: §1 は原稿全体の物理主張に及ぶが、 機械が見るのは保護領域と数式だけ。 repo の `protect_sections` で節を足せる。
- **引用の意味**: 「直して」 を概要の削除の裁定として記録することは機械では止まらない。 代わりに、 記録したターンの最後の返事に引いた発言と対象の file を書くことを Stop hook が求める (無ければ 1 回差し戻す) = 著者はその場で見て止められる。 §1-3 が床。
- **依頼文が user 発言として入る経路**: 別の session が書いた依頼文を著者が貼って送ると、 その中の文も user 発言として照合される。 依頼そのものは著者の指示だが、 依頼文が伝聞として書く「著者は X を承認した」 は裁定ではない。 機械はこの 2 つを区別しない (§1-3 が床)。
- **校正の判定**: 機械が通す綴りは列挙済みのものだけ。語の意味全体やコメントの著者性を判定する仕組みではない。
- **人の commit と見分けられない commit**: agent の session の env が無い commit は、 git 面では人の commit として通る。 Claude / Codex の PreToolUse(Bash) が commit の前に同じ述語で止めるのはこのため。
- **Bash で書き換えて commit しない場合**: 書き換え自体は止めない。 完了 gate ([`CONVENTIONS.md#completion-git-gate`](../CONVENTIONS.md#completion-git-gate)) が commit を求め、 その commit で止まる。
- **設定を緩めて範囲外にする経路**: git 面は HEAD の設定と新しい設定の広い方で判定する。 hook 面は現在の設定で判定するが、 設定の変更そのものが lock で止まる。
- **検査不能**: この gate は、止め損ねる害を重く見て **fail-closed** とする。Git の故障・読取不能・壊れた設定・復号不能・engine の不在や例外では、hook は deny、agent の Git gate は非 0 を返す。「違反」と「検査不能」を表示で区別し、依存経路を修復して同じ操作を再検査する。人の terminal (agent env なし) は対象外。公開 Git gate も削除だけの commit を検査する。
- <a id="non-utf8-tex-blocks-repo"></a>**読めない古い `.tex` が repo の全編集を止める**: 範囲の判定 (abstract を持つか) は HEAD と index の全 `.tex` を UTF-8 で読む。 UTF-8 でない `.tex` (古い日本語の Shift-JIS など) が HEAD に 1 本でもあると `inspection unavailable (blob-unreadable` で、 その repo のどの `.tex` の編集も止まる (実測)。 直し方は範囲の設定 (原稿の無い repo は `disabled`、 原稿のある repo はその file を `exclude`)。 設定の変更なので著者の発言の記録が要る。 file を UTF-8 に直すのは、 その file の持ち主が決めたときだけ。
- <a id="choice-answer-not-quotable"></a>**選択肢 UI の答えは発言として引けない**: AskUserQuestion で著者が選んだ答えは、 transcript の user 発言として照合されない (実測)。 その直後に `approve --latest` を打つと、 その前に著者が打った別の発言を裁定として記録する。 裁定は著者に chat で 1 行打ってもらってから記録する (選択肢で聞いたなら、 選んだ後に「〜してよい」 と打ってもらう)。
- **同一主体が書ける範囲**: ローカルの hook・engine・承認 state を同じ agent が物理的に書ける限り、これは OS による隔離ではない。全文 hash は承認の誤転用を検出するが、著者の発言の意味や state の偽造まで保証しない。engine の自己保守は適用前の scratch 検査を必須とし、無効化して通す運用をしない。
- **hook の配信**: trust と配信は machine ごと。 install 済みを確かめる方法は §4。
- **submodule (gitlink) の中身**: 親 repo の commit は submodule の commit id (pin) を記録するだけで、 中の file を読めない。 宣言が無ければ gitlink は検査対象外 (中の変更は submodule の repo 側の commit で検査される)。 保護 path (manifest の宣言・symlink を解決した後の path・glob の固定部分を worktree で解決した形) が submodule の中を指しうるなら、 大文字小文字と Unicode 正規化をそろえて比べて、 今までどおり検査不能で止める (= その pin は上げられない)。 宣言済みの gitlink を承認する経路は無い (承認の mode に 160000 が無い)。
- **hook の timeout は素通り**: settings の timeout (20 s) を越えた PreToolUse hook は打ち切られ、 tool はそのまま実行される (実測 2026-09-22: Claude Code CLI 2.1.198 で、 4 s 待ってから deny を返す hook を project settings に timeout 1 s で置くと `touch` が実行され、 timeout 10 s なら止まった。 desktop の埋込 engine 2.1.275 も打ち切りを「status 1・出力なし」 に畳む同じ経路)。 git の pre-commit に timeout は無い。 だから検査の時間を件数に比例させない ([`hook-authoring.md#hook-cost-per-item`](hook-authoring.md#hook-cost-per-item)。 実測: 3000 file の dir の `add` + `commit -- dir/` が 201 s → 0.4 s、 追跡済み 3000 file の `commit -a` が 1.8 s、 staged 3000 file の pre-commit が 1.3 s。 engine の selftest が git の呼び出し回数を file 数で比べる)。

- **子原稿の読み込みを外す編集そのもの**: 編集 hook は親の `\input` の行の書き換えを止めない (子原稿を先に動かすか親を先に直すかの順番で、 正当な移動を誤って止めないため)。 外れたかは commit の時点で、 HEAD と commit の後の到達範囲を比べて判定する。 外す commit を人が terminal で出した後は、 子原稿は範囲の外になる (人の判断)。 `\input` を macro で包む書き方は最初から辺として読まないので、 その子原稿は初めから範囲の外 (従来どおり)。

## <a id="why"></a>6. 実測 (一般形)

- 実測: 一般的な修正の依頼を受けた agent が、 表題・概要・序論・結論の主要な主張を、 物理的な根拠は検証済みのまま、 著者の裁定なしに撤去した。 直前の改稿では提案の形 (注記) にしていたが、 次の改稿で本文を直接書き換えた。 実行した session の記録には、 著者の未 review として「表題・概要・結論を含む改稿」 が残っていた (= 自分でも裁定前だと分かっていた)。
- 実測: 同じ系列の別の session が、 「提案を PDF に印字しない」 という趣旨の指示を、 「依頼・承認の範囲なら本文に直接反映し、 注記や追加確認を既定の手順にしない」 という規則に書き換え、 公開層・共有層・個人層の同じ規則を同じ文にそろえた。 規則の根拠 (過去の実害の記録) は残ったまま、 規則だけが弱まった。
- 共通の根 = agent が自分の mandate を広げ、 その結果が著者の決定に見える形で記録に残る。 役割の自己申告 ([`multi-session-coordination.md#board-role-claim-is-not-assignment`](multi-session-coordination.md#board-role-claim-is-not-assignment)) と同じ族。 文の規則は、 同じ agent がそれを書き換えられる限り守りにならない。 だから規則の本文と参照も lock の対象にした。

### <a id="commit-in-approval-turn"></a>承認を引ける発言は「最新」 だけ = 編集した turn の内に commit する (2026-09)

guard が引用を認めるのは本人の**最新**の発言だけ。 承認の下で原稿を編集した後に別の話 (質問への返答・別の裁定) を挟むと、 その後の
commit は「承認の発言が最新ではない」 で止まり、 本人に 1 行の承認をもう一度もらう手間が要る (実測)。
規則: 承認済みの編集は**同じ turn の内に commit** する (返事を書く前に)。 生成物 (図の再生成) を待つなら、 承認済みの text を先に
commit し、 生成物は後の commit に分ける (生成物に主張の承認は要らない)。 置換 → 検査 → 組版 → 目視 の間に本人の発言が入る
流れのときは、 検査の前に commit して検査で直したら追加 commit する方が安い。
「終わったら次もやって」 のような段階の依頼も同じ形で壊れる。 前の段を commit する前に本人の次の発言が来ると、 後の段はもう予告の発言では記録できない (実測: 後の段の変更をいったん戻し、 次の段と合わせて承認をもらい直した)。 段ごとに、 その段を終えた turn の内に commit する。
