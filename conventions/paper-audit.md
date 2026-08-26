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

各 section を「初見 reader が Sec.1 から順に読む」 を simulate、 各文で「ここまでに未定義の symbol / 用語 / 概念」 を flag。 Phase 1 候補を AI 精読で確定 / 棄却 + 概念レベル forward を AI 精読で新規発見。

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

## <a id="second-example-refine"></a>二例目が出たら refine

将来別 paper で同様の audit を実施したら、 script を `claude-config/scripts/` に generic 化、 本 convention を refine。 現状は 該当 private paper repo で完結。
