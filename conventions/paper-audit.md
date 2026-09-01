<!-- doc-meta
when: 論文 merger 等の構造 issue を体系 audit するとき
category: paper
summary: multi-paper merger 等の forward ref / 重複 subsection / structure issue を Phase1 機械検出 + Phase2 section-by-section AI 精読 + findings.yaml で体系 audit
-->
# Paper Audit (= forward references, duplicates, structure issues)

multi-paper merger (= P1+P2 統合等の「2 個 1 フランケンシュタイン」) や複雑な LaTeX paper で、 以下を体系的に audit + 修正:

- **forward references** — 定義前に登場する symbol / 用語 / 概念
- **subsection name / content duplicates** — merger artifact (= 同名 subsection、 word-for-word identical な散文 + 数式)
- **structural issues** — `\begin{comment}...\end{comment}` で disabled、 `\end{document}` 後の section、 section title vs label name 不一致 等

**Sibling docs** (= 本書は自分 paper の internal audit、 sibling は方向違いの workflow): referee report への返信 (= author response) = [`rebuttal-letter.md`](rebuttal-letter.md) / 自分が referee として外部 paper / 申請書を評価 = [`peer-review-workflow.md`](peer-review-workflow.md) / grant 申請書の submit = [`erad-submission.md`](erad-submission.md) / 論文の journal / arXiv 投稿ポータル経由の submit = [`paper-submission.md`](paper-submission.md)。

## <a id="three-phase-structure"></a>3 Phase 構造

「1 pass で paper 全体読み」 は cell 埋め (= 安価な操作で expensive な検証を bypass する trait) になりがちなので、 **機械的検出 + AI 精読** の 2 段に分ける。

### Phase 1: 機械的 inventory (script)

template script で以下を抽出:
- `\label{X}` ↔ `\eqref/\ref/\cref{X}` の順序 (= forward label ref)
- `\newcommand{\X}` ↔ `\X` 使用 (= macro forward)
- `\emph{X}` formal 導入 ↔ X 平文初出 (= concept forward)

実装例: `(該当 private paper repo の scripts/audit-forward-refs.py)` (= 二例目で `claude-config/scripts/` に generic 化予定、 現状 (該当 private paper repo) 専用)。

出力は候補リスト (= false positive 含む)。 AI 精読で確定 / 棄却。

### Phase 2: Section-by-section reader simulation

各 section を「初見 reader が Sec.1 から順に読む」 を simulate、 各文で「ここまでに未定義の symbol / 用語 / 概念」 を flag。 Phase 1 候補を AI 精読で確定 / 棄却 + 概念レベル forward を AI 精読で新規発見。 併せて **cite の束縛検査**: 各引用がその文の主張を実際に支持するか (帰属が怪しければ abstract を一次確認 — 誤帰属 cite は隣の主張と束ね違えても文法的に読めてしまうため、 grep では出ない。 移設・書き換えを経た text は [`#relocation-rebinding-sweep`](#relocation-rebinding-sweep) class (f) と同じ検査)。

Pass 単位の分割 (= context window 内で扱える size + 中断耐性):
- Pass 1: 主要 section (= 機械的検出が集中する場所)
- Pass 2: 関連 appendix の subsection 順序
- Pass 3-N: 残り section / appendix
- Light review: forward ref ほぼゼロ予想の section

各 Pass = 複数 sub-step (= section を更に細かく分割)、 sub-step ごとに findings.yaml に追記 + commit (= 中断耐性 + trace 確保)。

### Phase 3: 統合 review + 修正フェーズ

全 Pass 完了後:
1. findings.yaml を統合 review (= 全 finding を 1 表で見渡す)
2. user 判断軸を提示 (= 重複処理方針 / structure 不整合 / readability minor の処理)
3. user 確定後、 全 finding status を `proposed → approved` / `rejected` に遷移
4. 修正実装 (= 各 step ごとに commit + compile 確認)
5. status を `approved → implemented`

## <a id="findings-yaml-schema"></a>Findings YAML database schema

`plans/<date>-findings.yaml` で構造化管理:

```yaml
schema_version: 1
last_updated: YYYY-MM-DD
total_findings: N

findings:
  - id: F1
    severity: critical | major | minor | stylistic
    category: duplication | forward_reference | naming | readability | other
    title: "1 行サマリー"
    locations:
      - section: "Sec.X.Y"
        label: "label_name"
        line_range: [start, end]
    overlap_lines: int | null
    description: |
      詳細説明
    options:
      - id: a | b | c
        label: "修正候補"
        impact: "影響範囲"
        recommended: bool
    related: [F2, F3]
    status: proposed | discussed | approved | implemented | rejected
    discovered_pass: [Pass1, Pass2-A]
    notes: |
      補足 + 実装結果 + commit hash
```

状態遷移: `proposed → discussed → approved → implemented` (もしくは `rejected`)。

YAML 採用理由:
- **検索 / filter / 集計可能** (= `yq '.findings[] | select(.severity == "critical")'`)
- **schema drift 防止** (= 同じ field を全 entry で持つ強制)
- **状態 update が field 書き換えで完結** (= markdown text の status 行を手動書き換えるより堅牢)
- **plan の slim 化** (= markdown text に詳細を埋め込むと plan が肥大化、 yaml に正本を集約)

## <a id="plan-vs-yaml-roles"></a>plan 文書と yaml の役割分担

- **plan (`<date>-<topic>.md`)**: 長期 roadmap、 process record (= 各 Pass の作業ログ)、 yaml への pointer + summary table
- **findings.yaml**: 個別 finding の正本 (= 詳細 + status)
- **TodoWrite (= Claude Code 組み込み)**: 当 session の short-term sub-step (= ephemeral、 session 内 trace)

plan + yaml + TodoWrite の 3 階層併用。 plan = ロードマップ、 yaml = state、 TodoWrite = active work。

## <a id="fix-phase-discipline"></a>修正フェーズの規律

- **数式の意味変更** は user 承認: overall 方針確定 (= 軸 N=A 等) で代用可能か個別承認かを判断。 数式 label 削除 + 同 content の別 label への ref 化 (= App C で identical な式が defined) なら overall 承認で OK
- **削除する label の use 確認** を必ず先に: 全 use 箇所を grep + redirect or 削除を確定 (= 削除後の compile で undefined refs ゼロ)
- **compile 確認** を各 step 完了時: `pdflatex + bibtex + pdflatex × 2`、 undefined refs ゼロを確認
- **1 step = 1 commit** で中断耐性 + revert 可能性確保
- **page 数の累積効果** を意識: text 行数削減 != page 数削減 (= LaTeX の line breaking で reflow、 累積効果は後段で reflect)

## <a id="compression-vs-self-containment"></a>paper 規模圧縮 vs self-containment review の trade-off

「multi-paper merger artifact」 を持つ paper では:
- **方針 A (parsimonious)**: 重複削除、 page 数圧縮、 ref で代替
- **方針 B (self-containment)**: appendix が「skippable な review」 として self-contained、 重複温存 (= appendix opening で "reader familiar... may skip this appendix" を明示)

どちらも valid、 paper の流儀 + referee 期待で **user 判断**。 critical 重複の規模が大きい (= 70+ 行) ほど方針 A の利得が大きい。

## <a id="multi-commit-discipline"></a>多 commit 連打規律

修正フェーズで 13 step を 1 commit にまとめるのではなく、 各 step (= finding 1 つ) で 1 commit。 利点:
- session 中断耐性 (= 各 step 完了状態で revert 可能)
- trace 確保 (= 各 commit message で「何を削除、 何を残した」 を明示)
- conflict 解消の単位が小さい

多 commit 連打時の 4 軸 sweep 規律と整合: 「多 commit 連打 = 1 つの作業で 2 つ以上 commit を打つと自覚した瞬間に『最後の commit 後に必ず横断 4 軸 sweep を 1 回回す』 を declare」 を、 paper audit の修正フェーズでも適用 (= 全 step 完了後の最終 sweep)。

## <a id="worked-example"></a>実例: (該当 private paper repo) (2026-05-19、 1 day で完了)

- paper 39p → **37p** (-119 行)、 **13 findings** (= 12 implemented + 1 rejected)
- Phase 1 script: `(該当 private paper repo の scripts/audit-forward-refs.py)`
- findings DB: `(該当 private paper repo の plans/<date>-findings.yaml)`
- plan: `(該当 private paper repo の plans/<date>-forward-ref-audit.md)`
- 詳細: `(該当 private paper repo の DESIGN.md)`

主要発見 (= critical 7 件):
- F1: Sec.3.2 ↔ App C `Field strength` で **subsection 全体 70+ 行 重複** (= F^{0i}/F^{ij} closed form + matrix F + Lorentz transformation すべて word-for-word identical)
- F8: Sec.2.4-2.5 ↔ App B `Point charges` で **60 行重複** (= 基本概念 definitions、 self-containment 維持 vs parsimonious で user 判断)
- F9: Sec.3 / App C opening で **散文 word-for-word identical**
- F10: Sec.3.1 / App C で **同名 subsection** `Modified gamma factor and chargeward vector` + 内容大幅重複
- F11: App F (`Implementation details`) が `\end{document}` 後にあって **disabled** (= LaTeX 上 paper PDF に含まれない、 文書記述と不一致)
- F13: App D.3 (`Choice of Green's function: retarded vs Feynman`) が `\begin{comment}` で **disabled** (= referee F2 anchor として SESSION.md に記録されていたが paper PDF に含まれない)

「2 個 1 フランケンシュタイン」 の核心 = P2 (= `formalism_v1`) の主要 content が App B/C に embedded、 P1 (= `implementation_v1`) と並走 → paper 全体で ~170 行重複。

## <a id="headline-claim-budget-check"></a>中心主張は「模型の形式に依らない収支」で検算する (2026-08)

**ルール:** paper の headline claim (= 「起きる / 起きない」 を言う主張: 場が障壁を越える、 転移が完了する、 増幅が効く 等) は、 **その paper 自身の formalism で出した数値とは独立に、 保存則・正定値性・単調性による 2〜3 行の検算**を通す。 formalism の数値と収支が食い違ったら、 **formalism 側に暗黙の初期条件・規格化が紛れている**と読む (= 逆ではない)。

**検算の型 (どれか 1 つで足りることが多い):**

- **収支**: 使えるエネルギー (資源) は初期条件で決まる量以下。 反応の生成物は親の分け前であって外部からの補給ではない。
- **正定値性**: 各項 ≥ 0 の和なら、 個々の項の上限が全体の上限になる。
- **単調性**: 膨張・散逸・減衰は資源を減らすだけ。
- **示量性 / 次元**: intensive なはずの量が体積や体系サイズに比例していたら数え過ぎ (= 位相空間の冪の取り違え等)。

**食い違った時の手順:** formalism 側の数値が成立する条件を**等式として書き出す** (= 「この係数がこの値になるのは初期条件が X の時」)。 その X を paper の他 section の設定と突き合わせると、 両立するか一目で決まる。 両立しないなら、 その節は「別の数値体系で書かれた計算」 であって、 誤りは式でなく**設定の継ぎ目**にある。

**なぜ規約にするか:** formalism 内部の検算 (= 式の再導出・数値の再現) をどれだけ厳密にやっても、 **前提が別世界なら全部通ってしまう**。 独立な収支は前提そのものを試す唯一の安価な手段で、 かつ referee 側は 2 行でやる。

**実例 (2026-08、 該当 private paper repo):** 4 誌 reject 後の 5 誌目投稿直前に、 式の再導出と図の再計算は完了していたが、 中心主張 (= 場が障壁を越える) は収支で不成立と判明した。 使えるエネルギーが障壁の 6 %、 媒質は当の場の崩壊産物なので差を埋められない。 formalism の数値が主張を支えていたのは、 振動開始時の密度を Planck 密度と置く別 letter 由来の規格化が式の係数に埋まっていたためで、 その節と inflation 側の設定は両立していなかった。 referee 1 名がこの継ぎ目を「energy scale の接続が不明」 と表現していた (= 突かれる側から見れば既知の穴)。 → 主張を成立する範囲に絞る組み替えへ。

## <a id="figure-irreproducible-taxonomy"></a>図が本文の式から再現できない時の 4 分類 (2026-08)

図を caption の定義どおりに再実装しても合わない時、 原因は 4 つに分かれる。 **どれかを決めないと処置 (式を直す / 図を差し替える / caption を直す / 設定を直す) が決まらない**ので、 「再現不能」 で止めない。

| 分類 | 徴候 | 処置 |
|---|---|---|
| **本文の式が誤り、 数値 code は正しい** | 図は物理的に筋が通る。 別の (正しい) 式を仮定すると再現できる | 本文の式を直す。 図は不変 |
| **数値 code が誤り (or 不明)** | どの式・どの規格化でも再現しない。 曲線の形が合わない | 再計算して差し替え。 code が手元に無ければ作者に問う |
| **caption / label が実態と不一致** | 曲線が caption のパラメータに依存すべきなのに依存していない (= 同じ曲線が 2 つの label で描かれている 等) | caption を実際の設定に直す |
| **図が別の数値体系で描かれている** | 単独では整合するが、 論文の他 section のパラメータでは同じ図が出ない | どちらの体系を採るか決める (= 著者判断、 波及が最大) |

判別の入口 = 図のベクトル path から曲線を復元して数値照合する ([`scientific-computing.md#figure-vector-extraction`](scientific-computing.md#figure-vector-extraction))。 **4 番目は「図の問題」 に見えて設定の問題**なので、 上の [`#headline-claim-budget-check`](#headline-claim-budget-check) に接続する。

## <a id="claim-strength-three-tests"></a>強い言明の 3 検査 (偽 / generic / tautology) (2026-08)

**ルール:** 「never / only / in practice / effectively」 級の強い副詞・限定を含む物理言明は、 書いた瞬間に 3 検査を通す。 どれか 1 つでも落ちたら、 不変量か対比で書き直す。

1. **偽でないか (= 厳密な読みで反例が無いか)**: 例: 減衰状態の erfc 型 crossover で「漸近形には実質到達しない」 — 遅い時刻では erfc → 2 で必ず漸近形に乗る (振幅が小さいだけ) → 偽。
2. **generic でないか (= 当該 regime を他と区別するか)**: 例: 「漸近形が有効になる頃には振幅が指数的に抑制されている」 — 漸近形自体が減衰指数関数なら任意の不安定系で真 → 無内容。
3. **tautology でないか (= 構成上の定義から自動的に従っていないか)**: 例: 「閾値の前は仮想伝播のみが振幅を担う」 — 積分路が極を跨ぐ前に極の寄与が存在しないのは定義そのもの → 内容なし。

**通る形は不変量 + 対比**: 「漸近形が記述するのは振幅の $e^{-n^2/2}$ 以下の裾だけ ($n \ll 1$ では $O(1)$ から全履歴を記述する、 との対比)」 のように、 **regime 間で値が変わる量**で言う。 "in practice" が過重な仕事をしていたら書き直しの合図 (= 数学的読みで偽になる言明を副詞で救おうとしている)。

**実例 (2026-08、 該当 private paper repo):** 同じ 1 文が 3 検査を 3 回連続で落ちて 3 回書き直された (「never attained in practice」 = 偽 → 「becomes valid only after the amplitude is suppressed」 = generic → 「effectively propagates only virtually」 = tautology)。 最終形は上の「裾」 の言明。 3 回とも人間の共著者の指摘で発覚 = 書いた本人には毎回もっともらしく見えた (= 自己検査を機械的に回す理由)。

**追補 (2026-08-31): 誇示 (flourish) と strawman 参照も同じ検査に掛ける.** 「〜すら消せる / 任意に〜できる」 型の誇示は tautology 検査の頻出客 — 帳簿の付け替えが 1 点の値を任意化できるのは恒等式の自明な帰結で、 主張の強さを運ばない。 また**比較で主張を膨らませるときは、 比較相手が実際に使われている referent であること** — 誰も採らない参照 (非因果極限や、 目的に合わせて調整した定数など) との開きを headline 数字に混ぜると、 数字ごと strawman になる。 実例 (2026-08、 別 draft): 「定数をうまく選べば任意に選んだ 1 点で当該項を消せる」 という誇示を人間の共著者の指摘 (「1 点だけ消せて何の意味が?」) で撤去し、 実使用の参照間の開きだけを headline に残した。

## <a id="statement-placement-check"></a>言明の配置検査 (その位置の読者の道具だけで読めるか) (2026-08)

**ルール:** 段落を置く / 残す前に 3 つ問う。

1. **記号・概念が導入済みか**: その言明が使う記号・概念は、 その時点までに定義されているか。 根拠が数十頁先の式への forward reference 頼みなら、 言明ごと後方の節へ移す。
2. **孤児文でないか**: 編集で親段落を削除した後に、 その予告・要約・脚注だけが残っていないか。 親の動機が消えたら子も消す (= 「一部だけ残す」 妥協は往々にして動機を失った孤児を作る)。
3. **前方 pointer は後方参照と重複していないか**: 後の節が既にこの節を back-reference しているなら、 前方 pointer は導線としても冗長。

**実例 (2026-08、 該当 private paper repo):** 序盤の節に置いた extreme-case 段落が、 未定義記号 1 + 未導入概念 2 + 20 頁先への forward ref の三重で破綻していた。 段落を後方の専門節に合流させ、 残した「予告 1 文」 も後日 検査 3 で削除 (後方の節が既に序盤を back-ref しており冗長)。

## <a id="stale-framing-sweep"></a>理解更新後の旧語彙 sweep (2026-08)

**ルール:** 物理理解が更新されたら (例: binary な「閾値の前後で不連続」 → graded な「crossover の中心と幅」)、 **旧 framing の語彙を原稿と派生文書 (abstract / Summary / cover note / スライド) から sweep** する。 旧語彙の典型 = 「原理的に分解不能」 「痕跡は観測に掛からない」 (= 実在するが隠れている、 の含み)。 語法の基準は**原稿内で既に最良の定式になっている箇所** (例: 「安定極限と区別不能」) に揃える — 新しい基準文を発明するより、 既にある正しい文に他を合わせる方が drift しない。

**なぜ規約にするか:** 理解の更新は通常 1 箇所 (新しい節) に書き込まれ、 Summary・序論・脚注の旧記述は無傷で残る。 旧記述同士は互いに整合しているため節単位の読み直しでは見つからず、 旧語彙の grep + 新旧対比の観点でだけ引っかかる。

**実例 (2026-08、 該当 private paper repo):** 本文の新節は graded 語法で完成していたのに、 Summary は 2 つの時間スケールを混同した旧記述のまま生きており (「この閾値は短すぎて観測困難」)、 共著者向け note の bullet も旧言明を引用していた。 指摘 3 回で Summary・note・bullet を新語法に統一。

## <a id="relocation-rebinding-sweep"></a>文脈手術後の束縛再解決 sweep + 移設は verbatim-first (2026-08)

**問題の機構:** 論文散文の 1 文は、真理値の一部を文の外が解決する束縛に預けている — 指示語・代名詞の先行詞、方向語 (below / in the main text)、対語 (counterpart / former / latter)、接続詞・分詞の係り先、次数限定 (exact / to all orders)、引用の帰属。**文脈手術 (移設・圧縮・文分割/合成・fix の連鎖) は文面を変えずに解決環境を変えるため、束縛は silent に再解決され、文単位の review では見えない。** 数式の `\cref` は rigid (壊れれば ?? で loud) だが、散文束縛は壊れても文法的に読めてしまう。特に危険なのは「先頭次数では真」な圧縮 — 書き手の頭の検算は先頭次数しか sample しないため、exact 文脈に置かれた瞬間に偽になる主張がもっともらしく見える。

**ルール 1 (移設は verbatim-first):** appendix ↔ 本文の昇格/降格・節跨ぎの移動 (>1 段落) は、(a) verbatim 移動 → (b) 新文脈への適応編集、の 2 commit に分解する。移動しながらの再圧縮・言い換えを 1 commit に混ぜない。verbatim 移動なら束縛破れは不在か loud になり (例: "used in the main text" が本文中に来れば自己言及で即座に異様)、(b) の diff は純粋な編集として新文脈で review できる。

**ルール 2 (手術 event → 同 turn で named-class sweep):** 文脈手術 (移設・>3 文の圧縮/展開・文分割/合成・同一段落への fix 3 連以上) を行った turn では、**指示を待たず** touched region に対して以下の checklist で sweep を宣言して回す:

- (a) **指示語・代名詞**: 先行詞が同一文・直前文・明示 label のいずれかに在るか
- (b) **方向語・位置語**: below / above / in the main text / in this appendix が移動後も真か
- (c) **対語・関係語**: counterpart / former / latter / both / respectively の対が新文脈でも意図した対か (同一 object の別変数表示を「対」と呼んで二物を示唆していないか)
- (d) **文頭接続詞・分詞の糊**: Instead / However / since / -ing 分詞の係り先が真の論理関係か。**直前に文の分割・合成をした場合は必ず** (= 局所的に正しい fix 2 つの合成が係り先を孤児化する実例あり)
- (e) **exactness 動詞**: terminates / vanishes / is exact / to all orders / unique / collapses は全次数の主張 — 同文か直後に display (`\labelcref`) を持つか。無ければ display を新設するか主張を弱める (= prose は隠す、式と機械は暴く。display 化した主張は機械 audit の anchor にもなる)
- (f) **移動 text 内の cite**: 引用が新文脈でも同じ主張に束縛されているか

出力は「sweep した class と範囲 / NOT した範囲 / 確信境界」を明示し、「✓ pass」で終わらせない。

**なぜ規約にするか:** 手術後の再点検は書き手の delivery loop に何も返さない (文面は完成して見える) ため構造的に落ちる ([`convention-design-principles.md#motivated-substitution-trap`](../docs/convention-design-principles.md#motivated-substitution-trap) の verification family)。**実例 (2026-08、該当 private paper repo):** appendix→本文の大型昇格 + 1 文単位 rework の 1 日で本 class のエラーが 7 件 born (偽 counterpart 主張・先行詞なし指示語・方向語の残骸・偽の二物・接続詞の孤児化・偽因果分詞・根拠二役)。standing の数式 audit fleet の事前捕捉は 0。一方、人間の指示で回した directed sweep は 2 回とも実捕捉 (計 6 件) = **欠けていたのは能力でなく自発 trigger**。うち最重の 1 件は物理的に偽の主張で、線形次で縮退する 2 量の取り違えが「counterpart」圧縮で生まれ、(e) の display 化 → 実計算で露呈した。台帳の質は予防にならない (同日の commit message は原文/読みの問題/根拠を 1 件ずつ記録する品質だったが、全て修復時の記録で生成時には効かなかった) — 効くのは**書いた pass と別の pass** による列挙・照合であり、その最小形が本 sweep。

**隣接 anchor との分担:** [`#statement-placement-check`](#statement-placement-check) の孤児文検査と class (a) は部分重複する (あちらは配置時 trigger、こちらは手術時 trigger — どちらが先に発火しても同じ検査に落ちる)。強副詞 (never / only) は [`#claim-strength-three-tests`](#claim-strength-three-tests)、裸の exactness 動詞は本 anchor (e) が受け持つ。理解更新起因の旧語彙は [`#stale-framing-sweep`](#stale-framing-sweep)。

**機械化の境界と defer:** 真理判定は機械化不能 (LLM / 人間 verify)。候補列挙 (checklist 語彙を含む文の enumeration) は grep 可能だが helper script 化は defer — un-defer trigger: 規律のみで 1 手術 event を回して列挙漏れが出たら。verbatim 移動の機械 gate (宣言済み例外 list 方式) も defer — un-defer trigger: 規律下でも move+rewrite 複合 commit が再出現したら。standing の常駐散文検出器は作らない (柔軟束縛語は正当使用が圧倒的多数で、真理判定なしの常駐 flag は FP 洪水になる — 列挙は sweep 時 on-demand に限る)。

## <a id="quotation-provenance"></a>引用の出所を「生成」と「転記」で区別する (2026-08)

原稿の引用が **画像 (書影・スキャン・写真) からモデルが起こしたもの**なら、 それは転記ではなく
生成で、 語の置換・要約・**原文に存在しない引用の創作**・典拠の年の創作が申告なしに混じる。
主張の土台が引用や典拠の年である限り、 これは文体でなく**主張の検査**の対象。

- load-bearing に使う前に全引用を原本と 1 対 1 照合し、 照合済み / 未照合を表で残す
- 孫引き (= 一次資料を二次文献経由で引く) は本文側にも経路を書く。 後で原典に当たれないと
  分かったときに傷が浅い
- 手順・失敗の型・解像度規律・「原典を持つ人が直してきたら自分の生成物を先に疑う」 は
  [`photographed-document-transcription.md#quotation-extraction`](photographed-document-transcription.md#quotation-extraction) が正本

## <a id="assumption-dependent-claim-framing"></a>未証明の仮定に主張が依存する時の framing (3 層勾配 + 無仮定 floor + 不確実性→要求仕様) (2026-09)

paper の中心機構が「未証明の仮定」 (例: あるコヒーレンス・対称性・スケーリングが維持されること) に依存すると判明した時、 主張の書き方を修辞でなく構造で決める:

1. **主張を 3 層の強度勾配に分類する**: ① 無条件に守れる定量結果 (条件を明示して) / ② 仮定を明示した上での条件つき結果 (「we show X」 でなく 「X, provided that ⟨仮定⟩」 の様相) / ③ 仮定の成立条件そのものの画定を **結果として** 提示 (= 弱点の告白でなく「問題を初めて正しく定式化した」 という寄与)。 referee に発見させると致命傷になる緊張関係は、 ③ として自分の言葉で書けば domain of validity の宣言になる。
2. **無仮定 floor を先に確保する**: 仮定が倒れてもシナリオ / 模型が生き残る fallback (例: 劇的な機構が働かなくても素過程だけで最低限が成立する) が存在するなら、 それを条件つき主張より**前**に置く。 これで「仮定 1 枚に全体重」 の all-or-nothing 構造が「安全な床 + 上振れ」 に変わり、 仮定への攻撃が paper 全体に波及しなくなる。 floor の数値は仮定側とは独立に検算しておく。
3. **不確実性は防御にならない — 要求仕様に変換する**: 「見積もりには N 桁の不確実性があるからどちらもあり得る」 は paper の言葉にすると「機構は未定量化」 という自白。 正しい変換は「成立条件は ⟨定量条件⟩、 すなわち仮定は ⟨具体量⟩ を届けなければならない」 という**要求仕様**の陳述。 その際 knob の**非対称性**を必ず検査する: (a) 動かせる knob が係争中の仮定そのものなら、 それを回して gap を閉じるのは circular / (b) 敵対側のレート (仮定と独立に決まる量) は knob で動かない / (c) 時間発展で条件が改善・悪化する trend があれば両側 fair に書く。
4. **前身 paper から輸入した増幅率・レートは、 その前提を自分が撤回した瞬間に失効する**: 自分たちの先行論文の「機構 A で増幅された率」 を、 本 paper で機構 A を無効と示した後にそのまま引き継ぐと自家撞着。 裸の率から組み直す (= [#stale-framing-sweep](#stale-framing-sweep) の系譜間版)。
5. **絶対形の不在主張 (「X は起きない」) は定義争いを招く**: 定義に幅がある現象 (共鳴・相転移等) は 「機構として効かない (ineffective)」 + 冒頭で定義 + 適用条件、 の 3 点セットで書く (= [#claim-strength-three-tests](#claim-strength-three-tests) の変種)。

起源 (2026-09): 集団増幅機構を扱う private paper で、 中心機構がコヒーレンス維持の仮定に依存 + 素朴な桁見積もりで分が悪いと判明した際の 5 誌目投稿 framing 決定。 3 層勾配 + 摂動 floor + 「V_coh ≳ X λ³」 型の要求仕様変換で、 4 誌で反復された批判を条件の画定に転換した。

## <a id="moving-observational-baseline"></a>観測制約が動いている・係争中のときの baseline 規律 (2026-09)

観測の許容域 (例: CMB の n_s–r 面) が実験間で係争中 / 直近に更新された分野では、 「どの region を使ったか」 自体が結論を変える入力になる。 投稿前に:

1. **使っている許容域の鮮度を明示的に問う** — 原稿・先行自著から継いだ数値は数年前の legacy であることが多い。 「4 実装が一致」 しても全実装が同じ古い region を仮定していれば region 依存性は未検査 (= 実装独立性と入力独立性は別物)。
2. **複数 region で計算し、 region 非依存の不変量を抽出する** — 例: 「排除/許容」 は region で反転しても「緊張が制御パラメータの単調関数」 は全 region で成立する、 という形の主張に組み替えると、 観測論争の決着を待たずに書ける。
3. **baseline の採用は物理でなく著者判断** — 採用理由 (先行自著との連続性・係争の両側の存在) を明文化し、 不利な region での帰結 (模型全体の緊張を含む) を**自分の言葉で先に書く**。 直近の観測更新は referee が最初に引く文献であり、 沈黙は一撃で見つかる。

起源 (2026-09): private cosmology paper で、 4 実装 (leading 3 + exact 1) が全て 2018 baseline を継いでいたことが user の一言 (「allowed region は新しいやつにした?」) で発覚。 2025 更新群 (上方に引く実験と下方に引く実験が併存) の 3 region で引き直した結果、 baseline では「一部シナリオの排除」 だった結論が、 最新複合 region では「模型全体の ~2σ 緊張」 まで動いた — 不変量 (緊張の単調性) だけが全 region で生存した。

## <a id="second-example-refine"></a>二例目が出たら refine

将来別 paper で同様の audit を実施したら、 script を `claude-config/scripts/` に generic 化、 本 convention を refine。 現状は 該当 private paper repo で完結。
