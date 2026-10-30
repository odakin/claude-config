<!-- doc-meta
when: 論文 merger 等の構造 issue を体系 audit するとき + 自分の 2 点関数・自己エネルギーを文献の結果と比べるとき (#offshell-2pt-literature-comparison) + 出版済みの論文の正誤表の本文を書く・縮めるとき (#erratum-text) + 高階微分の逆伝播関数でどちらの極が負ノルムかを言う前 (#negative-norm-pole-assignment) + 統計量で型 (外れ値・ばらつき・2 群) を分けると書く前・その較正を組むとき (#classifier-claim-calibration) + 測定や総説を読み込んだ表の入力が今も最新かを投稿の前に確かめるとき (#input-freshness-audit) + 表の入力を直した後に何が動くかを確かめるとき (#input-fix-propagation) + 測定の表で 1 測定を名指す・抜く案を書く前 (#named-measurement-needs-physics) + 積分路や規約で分けた項に物理の名前を付けたとき・分解の恒等式から測定の予言を立てるとき (#decomposition-label-check)
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

各 section を「初見 reader が Sec.1 から順に読む」 を simulate、 各文で「ここまでに未定義の symbol / 用語 / 概念」 を flag。 Phase 1 候補を AI 精読で確定 / 棄却 + 概念レベル forward を AI 精読で新規発見。 併せて **cite の束縛検査**: 各引用がその文の主張を実際に支持するか (帰属が怪しければ abstract を一次確認し、 abstract が扱った範囲を言わなければ本文の範囲の文 (「〜だけを考える」) まで読む — abstract は主題が合っていても、 本文が別の量しか計算していないことがある (実測)。 複数の文献を 1 つの動詞で束ねる文 (「A–C は X を計算した」) は 1 本ずつ当てる。 誤帰属 cite は隣の主張と束ね違えても文法的に読めてしまうため、 grep では出ない。 移設・書き換えを経た text は [`#relocation-rebinding-sweep`](#relocation-rebinding-sweep) class (f) と同じ検査)。

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
- <a id="fix-adds-new-claims"></a>**査読の指摘への直しで足した例・限定の文は新しい主張**: 指摘に答えるために足した具体例や「〜だけが決める」 型の言い直しは、 元の文より検査が薄いまま入る。 足した式・例は自分の script で再導出し、 直した版を同じ reviewer に返すときは「新しい式・例も再導出」 を課す (実測: 平均の訂正に添えた小さな例が全体の状態と部分系の状態を取り違え、 射程を絞る言い直しが別の過大を作った。 どちらも突合で出た。 突合の形 = ai-collaboration `conventions/cold-eyes-isolation.md#revised-target-second-round`)
- <a id="mark-unruled-batch-lines"></a>**著者が項目ごとに裁定していない一括の直し (共著者経由の口頭の許可で提案をまとめて当てた等) の後に監査するときは、 その commit で入った行に印を付けてから finding を書く**: 採否を著者に戻す行が一目で分かり、 保護領域 ([`manuscript-claim-ownership.md#rule`](manuscript-claim-ownership.md#rule)) の確認の範囲が決まる。 印は `git blame -M -s <rev> -- <file>` で、 その commit の hash を持つ行を拾う。 ⚠️ `-M` を付けないと、 後で図の位置を動かした commit がその辺りの行を持っていき、 一括の直しの行が印から落ちる (実測)
- <a id="read-previous-fix-round-first"></a>**次の読みでは、 前の査読の直しで入った文を先に読む**: 直しの文は元の文より検査が薄い ([#fix-adds-new-claims](#fix-adds-new-claims))。 実測では、 reviewer の提案した句を統合するときに足した 1 語で主語と目的語が逆になり、 数を直した後も別の文に古い数が残り、 足した処方の文が隣の節の処方と食い違った。 前の round の統合の commit の行を `git blame -M -s` で拾い ([#mark-unruled-batch-lines](#mark-unruled-batch-lines) と同じ手)、 それらの文を周りの文と突き合わせて先に読む。
- <a id="review-note-quotes-verbatim"></a>**提案 note・査読票が原稿の文を引くときは、 引用が逐語か・指した行に在るかを機械で確かめる**: 逐語でない引用 (落とした `~\cite`・`\emph`、 表の欄を「欄名: 値」 と書き直したもの) は、 読み手に存在しない文を探させる。 source を開いたまま書いた note でも出た (実測)。 道具 = [`scripts/check-note-quotes.py`](../scripts/check-note-quotes.py) (`--note NOTE.md --source <原稿> --only-lines '<項目の見出しの regex>'`、 `:NNN「…」` の行の照合も)。 道具が見るのは 「…」 と "…" だけで、 原稿の行を code block や表の欄に写して引く note はその外 = その形で引くなら、 各行・各欄が source にあるかを別に数え、 一致しない行が案だけであることを読んで確かめる (実測: 今の文を code block で引いた提案 note で、 道具は今の文を 1 行も照合しなかった)。

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

- 頁数が数頁減り、 findings は十数件 (大半を implemented、 1 件 rejected)
- Phase 1 script: `(該当 private paper repo の scripts/audit-forward-refs.py)`
- findings DB: `(該当 private paper repo の plans/<date>-findings.yaml)`
- plan: `(該当 private paper repo の plans/<date>-forward-ref-audit.md)`
- 詳細: `(該当 private paper repo の DESIGN.md)`

主要発見の型 (= critical):
- 本文の節 ↔ 付録の節で **subsection 全体が数十行 word-for-word 重複** (式・行列・変換則まで一致)
- 基本概念の定義の節どうしの重複 (self-containment 維持 vs parsimonious で user 判断)
- 本文の節と付録の冒頭で **散文が word-for-word identical**
- 本文の節と付録で **同名 subsection** + 内容の大幅重複
- 付録の 1 つが `\end{document}` 後にあって **disabled** (= paper PDF に含まれない、 文書記述と不一致)
- 付録の小節が `\begin{comment}` で **disabled** (= 査読対応の anchor として記録されていたのに paper PDF に含まれない)

「2 個 1 フランケンシュタイン」 の核心 = 片方の原稿の主要 content が付録に embedded、 もう片方と並走 → paper 全体で百数十行の重複。

## <a id="headline-claim-budget-check"></a>中心主張は「模型の形式に依らない収支」で検算する (2026-08)

**ルール:** paper の headline claim (= 「起きる / 起きない」 を言う主張: 場が障壁を越える、 転移が完了する、 増幅が効く 等) は、 **その paper 自身の formalism で出した数値とは独立に、 保存則・正定値性・単調性による 2〜3 行の検算**を通す。 formalism の数値と収支が食い違ったら、 **formalism 側に暗黙の初期条件・規格化が紛れている**と読む (= 逆ではない)。

**検算の型 (どれか 1 つで足りることが多い):**

- **収支**: 使えるエネルギー (資源) は初期条件で決まる量以下。 反応の生成物は親の分け前であって外部からの補給ではない。
- **正定値性**: 各項 ≥ 0 の和なら、 個々の項の上限が全体の上限になる。
- **単調性**: 膨張・散逸・減衰は資源を減らすだけ。
- **示量性 / 次元**: intensive なはずの量が体積や体系サイズに比例していたら数え過ぎ (= 位相空間の冪の取り違え等)。

**食い違った時の手順:** formalism 側の数値が成立する条件を**等式として書き出す** (= 「この係数がこの値になるのは初期条件が X の時」)。 その X を paper の他 section の設定と突き合わせると、 両立するか一目で決まる。 両立しないなら、 その節は「別の数値体系で書かれた計算」 であって、 誤りは式でなく**設定の継ぎ目**にある。

**近似の端点から出た閾値は、 厳密な解で解き直す:** ある段の終わりの量を近似式で見積もって別の量と比べ、 「パラメタが X を越えると起きる」 と閾値を出したら、 同じ比較を厳密な方程式で 1 回解く。 単調性が厳密に効く量は出発点の値を越えられないので、 近似の見積もりが単調性を破っているだけで、 閾値そのものが無いことがある (実測)。 数値の違いは定数倍でも、 閾値の有無という定性的な主張が変わる。

**なぜ規約にするか:** formalism 内部の検算 (= 式の再導出・数値の再現) をどれだけ厳密にやっても、 **前提が別世界なら全部通ってしまう**。 独立な収支は前提そのものを試す唯一の安価な手段で、 かつ referee 側は 2 行でやる。

**実例 (該当 private paper repo):** 再投稿の直前に、 式の再導出と図の再計算は完了していたが、 「起きる」 型の中心主張は収支で不成立と判明した。 使える資源が必要量に遠く届かず、 媒質は当の過程の生成物なので差を埋められない。 formalism の数値が主張を支えていたのは、 別の論文由来の規格化 (初期条件の置き方) が式の係数に埋まっていたためで、 その節と他の節の設定は両立していなかった。 過去の査読所見もこの継ぎ目を指していた (= 突かれる側から見れば既知の穴)。 → 主張を成立する範囲に絞る組み替えへ。

**符号も収支の対象 (2026-09-11 追補)**: 係数の**符号**が物理を運ぶとき (真空エネルギーの向き、 運動項・質量二乗の符号、 running の向き)、 それも formalism と独立な 2〜3 行で検算する — 振幅と有効作用の辞書を定義から導き直し、 教科書の絶対量 (1 loop 真空エネルギー、 真空偏極の遮蔽の向き) と比べる。 起源事例 (2026-09): 投稿前 gate の worker がこの anchor に従って辞書を白紙から導き、 1 つの項を教科書の 1 loop の絶対量と比べたことで、 多数の検査が全 PASS のまま見逃していた有効作用の全体符号の反転が見つかった → [#absolute-sign-external-anchor](#absolute-sign-external-anchor)。

## <a id="regime-premise-in-lab-quantities"></a>「現実の regime」 と呼ぶ前に、 不変な parameter を lab の観測量に直す — 確立した結果を覆す帰結は前提から疑う

**Pattern**: 模型の Lorentz 不変な parameter (幅・結合・スケールの比) を静止系の長さや Compton 波長と比べて「現実の系はこちらの regime」 と決め、 その regime の帰結を headline に置く。 不変な量が lab のどの量に当たるか (横か縦か、 静止系か lab か) は取り違えやすく、 取り違えたまま regime を名指すと、 帰結の全体が前提の 1 文に乗る。 前提の文は短く導出の途中に置かれるので、 式の再導出や数値の再現では試されない。

**Check** (「realistic」「for any physical」「現実の」 を regime に付ける前に 1 回):

1. 条件を lab の量 (局在の幅・エネルギー幅・時間幅) で書き直す。 不変量 1 つが lab の複数の量 (方向ごとの幅など) に対応するなら全部書く。
2. 条件が含意する lab の量を、 線源と検出の運動学 (生成過程が許すエネルギー幅、 測定の分解能) と突き合わせる。 含意されるエネルギー幅がエネルギー自体に届くなら、 その regime は「現実の」 ではなく特殊な準備である。
3. 物理量を固定した極限 (質量 → 0、 エネルギー → ∞) で条件がどう動くかを見る。 「質量が小さいから X」 と書く前に、 lab の量を固定したとき条件が質量に依るかを確かめる。
4. 数値は桁ごとに算術を書く (単位換算で二乗を取り忘れると桁が半分になる。 実測)。

**補足の検査** (盲検の導出で出た一般則。 実測):

- **長さごとに frame と方向を書く**。 動く波束の lab の長さは収縮した長さで、 静止系の長さは boost 因子倍。 lab の長さを静止系 (または横) の長さとして不変な幅に入れると boost 因子の 2 乗が落ち、 反対の漸近 regime に移る。 見分ける症状 = 含意される平均エネルギーが label のエネルギーと一致しない。
- **label と平均**。 共変な波束の族では、 label の運動量が平均の運動量に等しいのは片方の漸近 regime だけ。 label を「粒子のエネルギー」 として使う前に、 運動量空間の密度から平均と相対幅を計算する。 相対幅が 1 の程度なら「label = 物理的なエネルギー」 という模型化が既に破れている。
- **1 parameter には 1 観測量**。 静止系で等方な 1 parameter の族は、 縦と横の独立な data を同時には再現できない。 その parameter が再現すべき観測量 (距離をまたぐ干渉なら coherent なエネルギー幅) を先に決め、 族が外す方を明記する。 弱めて書かない。
- **線源の scale は 2 つある**。 頂点の局在 (運動量の不確定) と coherence 時間 (エネルギーの不確定) は、 放出する粒子が遅いとき何桁も違う。 coherence length の観測量が使うのは後者。 干渉 data から抜いた幅は生成と検出の合成 (2 乗和) で、 合成の下限はどちらか一方の下限ではない。
- **裾の重い profile は芯の半値幅と分位点も出す**。 rms は cutoff の scale で決まることがあり、 どの密度 (不変測度つきの場の絶対値 2 乗、 位置演算子の密度、 電荷密度) を使うかで parameter 的に大きく違う。 「波束の位置」 も、 絶対値 2 乗の最大・周辺分布の中央値・確率で重みづけた平均が別の場所 (波面、 そのはるか後ろ、 古典軌道) に来ることがある。 どれを指すかを書く。
- **不確定性原理の sanity check**。 引用したエネルギーでの換算波長より短い局在は、 そのエネルギーの状態ではない。 そういう入力は exotic な regime の証拠ではなく、 不整合な入力として扱う。
- <a id="apparatus-bounds-axis-convention-run"></a>**装置の量で模型の幅を上下から縛るときは、 軸・規約・運転を揃える**。 (a) 同じ軸の量で比べる。 横の幅を進行方向の運動量広がりで縛ると桁で弱くなる。 方向ごとの幅を 1 parameter で持つ族では、 いちばんきつい軸が効く。 (b) 幅の parameter と RMS の換算を式で書いてから比べる。 Gauss の $e^{-x^2/2\sigma}$ なら 1 軸の位置の分散は $\sigma/2$、 運動量の分散は $1/2\sigma$ で、 「$1/\sqrt\sigma$ が運動量幅」 と読むと $\sqrt2$ ずれる。 (c) 装置の値は、 主張が比べる data を取った運転のものを使う。 設計値と別の運転では光学系が違い、 bound が桁で動く (実測)。 bound は必要条件で幅の値を決めないので、 閾値と比べるときは bound の側で上界として言う。
- <a id="apparatus-value-two-routes"></a>**転記した装置の値は別の経路で照合する**。 同じ表の中で導ける量 (規格化エミッタンスと β 関数から衝突点のビームの大きさ) が表の値と合うかを確かめ、 bound を決める鍵の値は独立な 2〜3 経路 (装置のエミッタンスからの計算・実験論文の本文の値・実験の角度分解能の data) で突き合わせる。 1 桁に丸めた本文の値 (「約 0.3」) はいちばん弱い bound を与えうるので、 bound は範囲で書く (実測)。 スキャンの表の OCR の数字は画像で確かめてから写す ([`web-tools.md#large-scan-pdf-few-pages`](web-tools.md#large-scan-pdf-few-pages))。

**Prior check**: 帰結が、 長く使われてきた近似や標準の公式を「現実の parameter で破綻する」 と言うなら、 それは発見か前提の誤りのどちらかで、 事前確率は後者に傾く。 headline に上げる前に、 帰結を支える前提の 1 文を独立に検算する (前提だけを渡す導出の盲検 = [`cold-eyes-isolation.md`](../../ai-collaboration/conventions/cold-eyes-isolation.md))。 前提の文の出所と著者の確認状況は [`actor-attribution.md#premise-provenance`](actor-attribution.md#premise-provenance) の手順で引く。

**有限の定数と冪の係数も収支の対象**: 「処方に依らない」「予言」「裸の項で動かせない」 と書く量が、 発散と同じ次数の有限の局所項か冪の発散の係数であるときは、 書く前に [`scientific-computing.md#symmetry-of-prescription-finite-part`](scientific-computing.md#symmetry-of-prescription-finite-part) の 3 つを通す (有限部での Ward 恒等式の検査、 対称性を保つ別の regulator での再計算、 既知の極限との照合)。 同じ類の処方どうしの検算の一致は根拠にしない (実測)。

**境界**: これは主張を立てる側の検査。 他の agent や査読から原稿の主張に不利な finding を受けたとき、 その finding が効く regime と原稿がそこに居るかを査定するのは受ける側の規則で、 入口は [`manuscript-claim-ownership.md`](manuscript-claim-ownership.md)。 両者は「確立した結果を覆す含意なら前提を先に疑う」 で同じ向きを向く。 隣接: [#headline-claim-budget-check](#headline-claim-budget-check) (中心主張を形式に依らない収支で検算) / [#threshold-is-not-regime-onset](#threshold-is-not-regime-onset) (閾値は反対 regime の始点ではない)。

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

**実例 (2026-08、 該当 private paper repo):** 同じ 1 文が 3 検査を 3 回連続で落ちて 3 回書き直された (「never … in practice」 型 = 偽 → 「only after …」 型 = generic → 「effectively only …」 型 = tautology)。 最終形は上の「裾」 と同じ型の言明。 3 回とも人間の共著者の指摘で発覚 = 書いた本人には毎回もっともらしく見えた (= 自己検査を機械的に回す理由)。

**追補 (2026-08-31): 誇示 (flourish) と strawman 参照も同じ検査に掛ける.** 「〜すら消せる / 任意に〜できる」 型の誇示は tautology 検査の頻出客 — 帳簿の付け替えが 1 点の値を任意化できるのは恒等式の自明な帰結で、 主張の強さを運ばない。 また**比較で主張を膨らませるときは、 比較相手が実際に使われている referent であること** — 誰も採らない参照 (非因果極限や、 目的に合わせて調整した定数など) との開きを headline 数字に混ぜると、 数字ごと strawman になる。 実例 (2026-08、 別 draft): 「定数をうまく選べば任意に選んだ 1 点で当該項を消せる」 型の誇示を、 1 点で消せることの意味を問う人間の共著者の指摘で撤去し、 実使用の参照間の開きだけを headline に残した。

## <a id="statement-placement-check"></a>言明の配置検査 (その位置の読者の道具だけで読めるか) (2026-08)

**ルール:** 段落を置く / 残す前に 3 つ問う。

1. **記号・概念が導入済みか**: その言明が使う記号・概念は、 その時点までに定義されているか。 根拠が数十頁先の式への forward reference 頼みなら、 言明ごと後方の節へ移す。
2. **孤児文でないか**: 編集で親段落を削除した後に、 その予告・要約・脚注だけが残っていないか。 親の動機が消えたら子も消す (= 「一部だけ残す」 妥協は往々にして動機を失った孤児を作る)。
3. **前方 pointer は後方参照と重複していないか**: 後の節が既にこの節を back-reference しているなら、 前方 pointer は導線としても冗長。

**実例 (2026-08、 該当 private paper repo):** 序盤の節に置いた extreme-case 段落が、 未定義の記号・未導入の概念・遠く先の頁への forward ref の三重で破綻していた。 段落を後方の専門節に合流させ、 残した「予告 1 文」 も後日 検査 3 で削除 (後方の節が既に序盤を back-ref しており冗長)。

## <a id="stale-framing-sweep"></a>理解更新後の旧語彙 sweep (2026-08)

**ルール:** 物理理解が更新されたら (例: binary な「閾値の前後で不連続」 → graded な「crossover の中心と幅」)、 **旧 framing の語彙を原稿と派生文書 (abstract / Summary / cover note / スライド) から sweep** する。 旧語彙の典型 = 「原理的に分解不能」 「痕跡は観測に掛からない」 (= 実在するが隠れている、 の含み)。 語法の基準は**原稿内で既に最良の定式になっている箇所** (例: 「安定極限と区別不能」) に揃える — 新しい基準文を発明するより、 既にある正しい文に他を合わせる方が drift しない。

<a id="stale-endpoint-after-boundary-move"></a>**数値の端点も同じ sweep に入れる (実測):** 境界・閾値の値を更新すると、 旧値を端点や代表行に使っていた箇所が旧値のまま残る — 表の行、 図の帯と凡例、 caption と本文の最上級 (`the fastest` / `at the boundary`)、 概要の範囲 (`A to B`)。 語彙の grep では出ない (その数字は別の文脈では正しく使われている)。 表と図を作る script の scenario 一覧から 「その値を端点・代表に使っている所」 を引き、 新しい端点の行を計算して足す。 足したら、 概要に書いた範囲が丸めの内に収まるか、 「N% の外」 のような言い切りがまだ全行で成り立つかを数値で確かめる (端の行が動くと言い切りの方が偽になる)。

**なぜ規約にするか:** 理解の更新は通常 1 箇所 (新しい節) に書き込まれ、 Summary・序論・脚注の旧記述は無傷で残る。 旧記述同士は互いに整合しているため節単位の読み直しでは見つからず、 旧語彙の grep + 新旧対比の観点でだけ引っかかる。

**実例 (2026-08、 該当 private paper repo):** 本文の新節は graded 語法で完成していたのに、 Summary は 2 つの時間スケールを混同した旧記述のまま生きており、 共著者向け note の bullet も旧言明を引用していた。 指摘 3 回で Summary・note・bullet を新語法に統一。

## <a id="relocation-rebinding-sweep"></a>文脈手術後の束縛再解決 sweep + 移設は verbatim-first (2026-08)

**問題の機構:** 論文散文の 1 文は、真理値の一部を文の外が解決する束縛に預けている — 指示語・代名詞の先行詞、方向語 (below / in the main text)、対語 (counterpart / former / latter)、接続詞・分詞の係り先、次数限定 (exact / to all orders)、引用の帰属。**文脈手術 (移設・圧縮・文分割/合成・fix の連鎖) は文面を変えずに解決環境を変えるため、束縛は silent に再解決され、文単位の review では見えない。** 数式の `\cref` は rigid (壊れれば ?? で loud) だが、散文束縛は壊れても文法的に読めてしまう。特に危険なのは「先頭次数では真」な圧縮 — 書き手の頭の検算は先頭次数しか sample しないため、exact 文脈に置かれた瞬間に偽になる主張がもっともらしく見える。

**ルール 1 (移設は verbatim-first):** appendix ↔ 本文の昇格/降格・節跨ぎの移動 (>1 段落) は、(a) verbatim 移動 → (b) 新文脈への適応編集、の 2 commit に分解する。移動しながらの再圧縮・言い換えを 1 commit に混ぜない。verbatim 移動なら束縛破れは不在か loud になり (例: "in the main text" が本文中に来れば自己言及で即座に異様)、(b) の diff は純粋な編集として新文脈で review できる。

**ルール 2 (手術 event → 同 turn で named-class sweep):** 文脈手術 (移設・>3 文の圧縮/展開・文分割/合成・同一段落への fix 3 連以上) を行った turn では、**指示を待たず** touched region に対して以下の checklist で sweep を宣言して回す:

- (a) **指示語・代名詞**: 先行詞が同一文・直前文・明示 label のいずれかに在るか
- (b) **方向語・位置語**: below / above / in the main text / in this appendix が移動後も真か。 display の行位置 (`the second line of Eq. N`) は式の改行を変えただけで別の項を指すので、項の名前か順番に直す ([#referent-and-scope-pinning](#referent-and-scope-pinning))
- (c) **対語・関係語**: counterpart / former / latter / both / respectively の対が新文脈でも意図した対か (同一 object の別変数表示を「対」と呼んで二物を示唆していないか)
- (d) **文頭接続詞・分詞の糊**: Instead / However / since / -ing 分詞の係り先が真の論理関係か。**直前に文の分割・合成をした場合は必ず** (= 局所的に正しい fix 2 つの合成が係り先を孤児化する実例あり)
- (e) **exactness 動詞**: terminates / vanishes / is exact / to all orders / unique / collapses は全次数の主張 — 同文か直後に display (`\labelcref`) を持つか。無ければ display を新設するか主張を弱める (= prose は隠す、式と機械は暴く。display 化した主張は機械 audit の anchor にもなる)
- (f) **移動 text 内の cite**: 引用が新文脈でも同じ主張に束縛されているか
- (g) <a id="orphaned-definition-after-move"></a>**定義の孤児**: 移した block の中でだけ定義されていた記号・略記が、 残した側の式や文にまだ使われていないか。 付録の導出を補足へ移して結果だけ残すと起きやすい (実測: 残した display に「2 つの等しい形」 が並んでいて、 片方の形の変数の定義だけが導出と一緒に移り、 残した式に未定義の記号が残った。 ref は壊れないので build は通る)。 残す側の数式に出る記号を列挙し、 残す側の中に定義があるかを確かめる
- (h) <a id="sentence-table-neighbors"></a>**文の表を当てる pass の隣の文**: 決まった文に置き換える pass では、 式を変えない制約のもとで隣が壊れる。 display の直後の節を消すと、 display の末尾が comma なら次の文は小文字で続ける必要があり、 period の後に so that で始める文は文にならない (末尾の句読点が次の文の形を縛る)。 置き換える文が次の文の指示語 (That of … など) の先行詞を持っていることもある。 表を当てる前に、 前の display の句読点と次の文の指示語を見る (実測: 表どおりに当てると comma の後に大文字の文が続く所と、 先行詞の消える所が出た)。 表の行番号と記号は古くなるので、 文の中身で探し、 今の記号に読み替える

出力は「sweep した class と範囲 / NOT した範囲 / 確信境界」を明示し、「✓ pass」で終わらせない。

**なぜ規約にするか:** 手術後の再点検は書き手の delivery loop に何も返さない (文面は完成して見える) ため構造的に落ちる ([`convention-design-principles.md#motivated-substitution-trap`](../docs/convention-design-principles.md#motivated-substitution-trap) の verification family)。**実例 (2026-08、該当 private paper repo):** appendix→本文の大型昇格 + 1 文単位 rework の 1 日で本 class のエラーが複数 born (偽 counterpart 主張・先行詞なし指示語・方向語の残骸・偽の二物・接続詞の孤児化・偽因果分詞・根拠二役)。standing の数式 audit fleet の事前捕捉は 0。一方、人間の指示で回した directed sweep は 2 回とも実捕捉 = **欠けていたのは能力でなく自発 trigger**。うち最重の 1 件は物理的に偽の主張で、近似の最低次では区別されない 2 量の取り違えが「counterpart」圧縮で生まれ、(e) の display 化 → 実計算で露呈した。台帳の質は予防にならない (同日の commit message は原文/読みの問題/根拠を 1 件ずつ記録する品質だったが、全て修復時の記録で生成時には効かなかった) — 効くのは**書いた pass と別の pass** による列挙・照合であり、その最小形が本 sweep。

**隣接 anchor との分担:** [`#statement-placement-check`](#statement-placement-check) の孤児文検査と class (a) は部分重複する (あちらは配置時 trigger、こちらは手術時 trigger — どちらが先に発火しても同じ検査に落ちる)。強副詞 (never / only) は [`#claim-strength-three-tests`](#claim-strength-three-tests)、裸の exactness 動詞は本 anchor (e) が受け持つ。理解更新起因の旧語彙は [`#stale-framing-sweep`](#stale-framing-sweep)。

**機械化の境界と defer:** 真理判定は機械化不能 (LLM / 人間 verify)。候補列挙 (checklist 語彙を含む文の enumeration) は grep 可能だが helper script 化は defer — un-defer trigger: 規律のみで 1 手術 event を回して列挙漏れが出たら。verbatim 移動の**検算**は [`scripts/verify-verbatim-move.py`](../scripts/verify-verbatim-move.py) (2026-09-13): 消えた行がすべて移動先の追加行として現れるかを多重集合で数える。 同じ file の中の MOVE も数え、 `MOVE:` と名乗った commit の直後に `--rev HEAD~1..HEAD` で回す (書き換えが混ざっていれば、 その行を名指しして exit 1)。 文書をまたぐ移設 (付録を別論文や補足へ) では、 label の参照の切れと class (b) の入れ物の語を、 移す前に [`scripts/latex-split-deps.py`](../scripts/latex-split-deps.py) が列挙する (手順 = [`latex.md#companion-paper-split`](latex.md#companion-paper-split))。 ほかの class の列挙の defer は変わらない。 commit を止める常設の gate (宣言済み例外 list 方式) は引き続き defer — un-defer trigger: 規律下でも move+rewrite 複合 commit が再出現したら。standing の常駐散文検出器は作らない (柔軟束縛語は正当使用が圧倒的多数で、真理判定なしの常駐 flag は FP 洪水になる — 列挙は sweep 時 on-demand に限る)。

## <a id="referent-and-scope-pinning"></a>指示対象と射程を文面で固定する — 書き手には自明な係り先ほど読み手は取り違える (2026-09-13)

[`#relocation-rebinding-sweep`](#relocation-rebinding-sweep) は文脈手術で**束縛が壊れる**ときの sweep。こちらは**新しく書いた文**で、係り先・射程が最初から一意でない形。著者の通読 pass (1 日 40 pass) で「何を指してるか分からない」「曖昧」と止まった箇所の多くは、下の表の先頭 7 形のどれかだった (同日の裁定の残りは冗長・段落構成・呼称・脚注の位置などで、この節の対象外)。

| 形 | 実例 (2026-09-13) | 処方 |
|---|---|---|
| **指示語・対語の先行詞** | `the former`、`for either field`、`these combinations`、`each line`、`between the two schemes` | 名詞か式番号で言い直す (`Only $A_\mu$ enters …`、`the left-hand sides of Eqs. (N)–(N+3)`、`between minimal subtraction and a hard cutoff`)。対語は 2 項が同じ文に在っても、間に修飾が挟まれば崩れる |
| **前置の限定句が等位の後半まで掛かる** | `In scheme A the divergence appears as a pole …, and the coupling is fixed at the scale μ` (後半まで scheme A の話に読める) | 限定句を掛けたい文だけに置き、文を切る。後半は別の文で主語から始める |
| **射程語 (反対称化・trace・部分) の範囲** | `the totally antisymmetric part` (微分の添字まで反対称化するかで別の量になる)、`the trace` (どの 2 添字の縮約か) | 記号で書く: `$X_{[abc]}$`、`the trace $X^{a}{}_{ba}$`。語は定義の場で 1 回だけ |
| **display の行位置** | `the second line of Eq. (N)` (式の改行が変われば黙って別の項を指す) | 項の名前か項の順番で呼ぶ (`the two mass terms of Eq. (N)`)。 [`scripts/check-paper-prose.py`](../scripts/check-paper-prose.py) の P が `… line of` / `in the … line` を列挙する |
| **排他・必然の modal** | `must be generated by quantum effects`、`only through quantum effects` (「古典的に消去しても同じ項が出る」 という既知の反論を招く) | 論文が既に引いている線引きの語 (`of its own`、`at tree level`) を残して、事実を平叙で書く。排他を言う必要があるのは序論の定義の場だけ |
| **結論が依存する選択を落とす** | `here these coefficients are outputs of the one-loop computation` (別の結合の選び方なら自由パラメータ) | 同じ文に選択を付ける (`here, for the minimal choice, …`)。同じ主張の他の出現 (abstract・結語) を grep して射程を揃える。 ⚠️ **「X が与えられれば Y は決まる」 型の構造の主張には付けない**: 選択を逆にしても真なら (`within this basis, the input fixes the output with nothing left free` は、 input の係数が別の選び方で決まっても成り立つ)、 限定は係数の値を言う上流の文に置けば足りる。 判定 = 選択を逆にして文がまだ真か |
| **標準的な操作を必然と読ませる** | `Once the auxiliary field is eliminated by its equation of motion, …` (本稿の立場ではその場は運動項を持ち、 補助場でない) | 条件文にし (`In the standard treatment, where the field is auxiliary and eliminated, …`)、本稿の変数での対応物を言う |
| <a id="one-comparative-two-directions"></a>**1 つの比較語に、 向きの違う 2 量を掛ける** (後日の追加) | `A lies below B by Δ in x and by a factor f in y` (y は A の方が大きいのに、 `below` が y にも掛かって読める) | 量ごとに向きの語を置く (`below B by Δ in x and above it by a factor f in y`)。 圧縮した比較文は、 量を 1 つずつ表・図の数値と突き合わせて向きを確かめる。 主語も数字も合っているので、 書き手も読み手も前半の向きのまま後半を読み、 文単位の通読を何度重ねても残る (実測: 概要・序論・結語の同じ文に残っていた) |

**How to apply**: 書いた段落を、代名詞・`former/latter/either/both/the two`・前置の `In … ,`・`part/trace/sector`・`must/only/once`・比較語の後の `and by` (`below/above/larger/smaller … and by …`) の 6 語群で 1 回ずつ引き、各 hit の係り先を 1 語で言えるか確かめる。言えなければ上の処方。 `check-paper-prose.py` の P は位置語 (`above/below/former/latter/… line of`) だけを機械で列挙し、係り先の真偽は読む側の仕事。

**なぜ別節か**: relocation sweep は「前は正しかった束縛が壊れた」 を探すので、新文には発火しない。こちらは書いた瞬間から一意でない形で、書き手は自分の意図で補って読むため自分では気づかない (同日、 1 文を 3 回書き直してまだ「前置詞句が何に掛かっているか分かりにくい」 と戻った例がある)。

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

起源: ある private paper で、 中心機構が未証明の仮定に依存 + 素朴な桁見積もりで分が悪いと判明した際の再投稿 framing 決定。 3 層勾配 + 摂動 floor + 「⟨量⟩ ≳ ⟨閾値⟩」 型の要求仕様変換で、 過去の査読で反復された批判を条件の画定に転換した。

## <a id="moving-observational-baseline"></a>観測制約が動いている・係争中のときの baseline 規律 (2026-09)

観測の許容域 (例: CMB の n_s–r 面) が実験間で係争中 / 直近に更新された分野では、 「どの region を使ったか」 自体が結論を変える入力になる。 投稿前に:

1. **使っている許容域の鮮度を明示的に問う** — 原稿・先行自著から継いだ数値は数年前の legacy であることが多い。 「複数実装が一致」 しても全実装が同じ古い region を仮定していれば region 依存性は未検査 (= 実装独立性と入力独立性は別物)。
2. **複数 region で計算し、 region 非依存の不変量を抽出する** — 例: 「排除/許容」 は region で反転しても「緊張が制御パラメータの単調関数」 は全 region で成立する、 という形の主張に組み替えると、 観測論争の決着を待たずに書ける。
   ⚠️ 派生 trap: 「データが機構 A を機構 B より favor する」 は、 パラメータ空間の測度 (窓幅 = 事前体積、 Occam 因子) を実際に計算していない限り書けない — 両機構に許容点が残るなら頻度論的には無差別で、 referee に一撃で返される。 defensible な形 = 「観測は遅い機構を fine-tuned な corner に confine し、 速い機構は窓を reopen する」 という**彫刻の記述** + 未確立の機構には条件法 (would)。
3. **baseline の採用は物理でなく著者判断** — 採用理由 (先行自著との連続性・係争の両側の存在) を明文化し、 不利な region での帰結 (模型全体の緊張を含む) を**自分の言葉で先に書く**。 直近の観測更新は referee が最初に引く文献であり、 沈黙は一撃で見つかる。
4. **「係争中」 と書くなら中身と出典を 1 文で書く** (2026-09-02 追記) — 「still debated」 だけでは referee に「誰が何を」 と返される。 形 = 「その組合せは標準模型を仮定するが、 同じ測定は CMB と合わせると ⟨代替模型⟩ を ⟨Nσ⟩ で好む [測定 collaboration 自身の結果]」 + 「よって baseline はそれ抜き、 込みは completeness のために併記」 の 2 文。 user の問いは 4 段で進んだ (追加の data を入れるとどうなるか → 係争中なら許容 → 本文にそう書いてあるか → どう係争中かの中身が要る)。 沈黙 → 無根拠の一言 → 出典つき 1 文、 の 3 段を最初から最後の形で書く。

起源 (2026-09): ある private paper で、 独立に書いた複数の実装が全て数年前の baseline を継いでいたことが、 許容域の鮮度を問う user の一言で発覚。 直近の更新群 (逆向きに引く実験が併存) の複数 region で引き直した結果、 baseline での結論が region によって定性的に動いた — 不変量 (緊張の単調性) だけが全 region で生存した。

**追補 (2026-09、 動く基線の下での主張の型)**: ① baseline は 1 つに固定せず「現行の主 data set を主、 旧 data set を比較、 係争中の拡張 data set 込みは注記」 と列挙する ② 絶対文 (「dataset X は模型を Nσ で排除」) は中心値が 1σ 動けば死ぬ。 相対文 (「緊張は制御 parameter の単調関数」「2 つの history の差は $\Delta\chi^2$ でこの範囲」) と data 非依存の予言 (一方の観測量を固定したときの他方の差・比、 到達可能な下限) で書く ③ 現状の data との比較は付加情報として節末・abstract 末尾に置く。 起源事例 (2026-09、 private paper repo): 「Nσ 内に残るのは片側のシナリオのみ」 を joint 2D で検査したらその側も外だった → 主張の型ごと差し替え。

## <a id="input-freshness-audit"></a>投稿の前に、 表の入力の鮮度を行ごとに確かめる — 解析の日付は入力の締めではない

測定や総説を読み込んだ表 (比較の表・結合・診断の一覧) は、 解析を回した日が新しくても、 入力は総説の版や編集物の締めで止まっている (実測)。 上の節が基線の取り方を扱うのに対し、 ここは表の 1 行ずつの入力を点検する手順。

1. **締めを読む** — data file から、 どの総説のどの版か、 一番新しい入力はいつかを書き出す。 解析の日付や file の更新日で代えない
2. **3 か所を探す** — (a) 総説の新しい版で置き換えられた項 (同じ実験の更新) (b) 同じ観測計画の後継 (c) 新しい計画。 検索の語と見た範囲を行ごとに書く。 題名の検索で止めない ([`web-tools.md#literature-search-apis`](web-tools.md#literature-search-apis))
3. **足すのと置き換えるのを分ける** — 同じ実験の更新を足すと同じデータを 2 度数える。 手法の違う低精度の測定は足しても重みが無いので、 足さない理由を書く
4. **値の身分を分ける** — 総説が採った値 / 査読済みの論文 / 査読前 / 予備結果 / 同じデータの再解析。 行の判定は総説の値で出し、 残りは感度として並べる。 再解析は値より小さい誤差が効くことがあるので、 値だけ替えた場合も回す
5. **編集物の誤差を原論文の総誤差と照合する** — 較正の基準を固定した条件つきの誤差が、 編集物では総誤差のように載っていることがある (実測)。 重みは誤差の 2 乗で効くので、 1 点の読み違いが行の結論を決めることがある
6. **先に印字を再現する gate を通す** — 探索の script は canonical の入力を変えず、 同じ関数で印字の値を再現してから新しい値を足す。 許容は印字の桁に揃える (緩い gate は再現を示さない、 実測)
7. **1 点ずつ動かす** — 全部を替えた結果だけでなく、 1 点ずつ替えた表を出す。 分布の形で型を分ける指標は 1 点で閾値を跨ぐので、 どの 1 点が判定を動かすかが分かる形にする
8. **判定は 3 段** — 変更なし / 数が少し動く / 読みが変わる。 編集物の行を日付つきの読みとして残すか作り直すかは著者の判断なので、 両方の場合に変わる箇所を出す

## <a id="input-fix-propagation"></a>表の入力を直した後の波及 — 数の照合表が見ない所

上の節の点検で入力を 1 点でも直したら、 印字の数を照合表で合わせるだけでは足りない。 照合表は登録した数しか見ない (実測)。

1. **較正の元が入力の複写でないか** — 合成 ensemble の誤差の並び、 中心の固定値、 検査の基準値が入力から来ていれば、 較正の率は全部動く。 率を持ち越さず回し直す。 基準値の定数は定義の 1 か所に置くか、 test で入力と照合する
2. **数でない主張は別に引く** — 「どの閾値でも安定」「どの場合も N 以上」 のような文は、 数の照合が全部通っても偽になれる。 語で原稿を引いて 1 文ずつ計算し直す (実測: 安定の文が成り立たなくなり、 回帰 test の失敗で初めて分かった)
3. **感度の表は基準を替えたら作り直す** — 1 点替えの判定は基準の入力に依る。 前の基準の表を持ち越すと、 新しく判定を動かす点を見落とす (実測)
4. **感度の文は、 根拠にしてよい入力の集合の上で計算する** — 全部の組み合わせの最小値には、 本文の根拠にしないと決めた値が入っていることがある。 集合を決めてから最小値を出し、 どの入力の組かを行ごとに記録する (実測)
5. **判定が保たれても余裕を書く** — 分類の行が変わらなくても、 閾値からの距離は大きく減ることがある。 距離を記録し、 減ったら本文の読みに反映する
6. **注記の位置を見る** — 文字の位置を固定値で置いた図は、 点が動くと重なる。 作り直した図は画像で 1 回見る

## <a id="named-measurement-needs-physics"></a>結合の中の 1 測定を名指す前に — 数だけで疑わない、 規則と公式の処置の食い違いは入力の締めから見る

測定の表を読むとき、 抜くと結論が閾値を跨ぐ 1 点を見つけると、 その点を「調べるべき」 と名指す案を出しやすい。 根拠は数だけで、 結果を見てから選んだ点なので、 主張としても選択としても弱い (実測)。

1. **抜く前に物理を言う** — その量の真値がいくつあるか、 「中心が 2 つ」 が物理として何を意味するか (新しい現象か、 片方の群に共通の系統誤差か)、 手法の群がどちら側に散っているかを先に書く。 不一致の軸が群の間でなく同じ群の中にあるなら、 その群を 1 つの陣営として数えた差は読みにならない
2. **結果を見てから選んだ 1 点を名指さない** — 全部を 1 つずつ抜いた幅で書く。 1 点を名指すのは、 再測定や原因の同定のような物理の根拠があるときだけ。 「抜くと差が小さくなる」 は測定を疑う根拠にならない
3. **規則と公式の処置が食い違って見えたら、 規則を直す前に入力の締めを見る** — 規則が単一の値を許さないのに公式が 1 値を出しているとき、 入力が公式より後の測定を落としていることがある。 先に [#input-freshness-audit](#input-freshness-audit) を回す (実測: 規則の問いに見えた議題が、 入力の見落としで解けた)
4. **解決の側も同じ検査に掛ける** — 新しい測定で差が閾値の下に入っても、 その 1 点を抜いた差を計算して書く。 全部残した集合の読みも並べる

## <a id="printed-number-provenance"></a>受け取った数と比較の語を本文に写す前に — 比較は発表の時点のもの、 丸めは元の値から 1 回

入力を足す・直す pass で、 下書きのノート・依頼書・原論文の文から印字の値や比較の語を受け取るときの 2 つの罠。 どちらも、 受け取った文が読みやすい形をしているほど素通りする。

1. <a id="quoted-comparison-as-of-publication"></a>**引用した比較は発表の時点のもの** — 「他のどの測定より N 倍精密」「最も精密」 のような論文の文は、 その論文が出た時点の比較。 同じ表に後の測定を足すと成り立たないことがある (実測: 後から足した行との比は N 倍を下回った)。 本文に写す前に、 今の表の全行で計算し直す。 論文の主張を gate で照合するときは比べる相手を発表の前の行に絞り、 今の表の全行で言えることは別の文にする
2. <a id="round-once-from-raw"></a>**丸めは元の値から 1 回** — ノートや依頼書の 2 桁の値から 1 桁の印字を作らない。 x.x49 は x.x5 を経ると 1 つ上がる (実測)。 依頼書の「決めたこと」 の欄に書かれた印字の値も、 決定ではなく計算の写しなので、 本番の設定の元の値から出し直す。 食い違ったら元の値から丸めた数を印字し、 違えた理由を意図記録と提出に書く

## <a id="scope-vs-epistemic-state"></a>「この論文の計算」 と「著者の認識状態」 を混同しない (2026-09)

referee に「その量は決まらないのでは」 と突かれた時、 縮退させた文が **著者が実際に知っていること**まで否定してしまうことがある。 典型形:

> The present calculation neither computes nor fixes X.

`this paper の計算では` と読めば字義的に真でも、 X が別稿・手元で既に計算済みなら、 読者は「誰も決めていない量」 と受け取る。 companion paper に載る結果を、 本稿が先に否定してしまう。

**ルール**: 縮退させるのは **claim の射程** であって **認識状態** ではない。 書き分けは 3 通り:

| 状況 | 書き方 |
|---|---|
| 計算していない | 「本稿では扱わない」 (= scope の宣言) |
| 計算済み・別稿で提示 | 「値は Ref. [X] で報告する」 (= 存在と所在を述べ、 導出だけ譲る) |
| 計算済み・本稿に載せる | 数値を印字 (⚠️ 導出のない数値は別の指摘を招く。 [#claim-strength-three-tests](#claim-strength-three-tests)) |
| 計算済み・本稿には結果の文だけ | 「計算して確かめた」 とだけ書き、**節や式を典拠として引かない** (2026-09-13: 「§N の振幅で確認」 「reported in §N」 と書いたが、 §N に振幅も確認の過程も無く、 読者が探しても見つからない。 別の段落でその事実に触れる必要が無ければ、触れない) |

**なぜ**: 論文の主張は将来の自分の論文とも整合しなければならない。 本稿で「決まらない」 と書いた量を companion で「これが値です」 と出せば、 referee が両方読んだ時に矛盾になる。 縮退は安全側に見えて、 系譜全体では新しい負債を作る。

起源: 委譲先が referee の指摘に応えて脚注を「本稿では決めない」 へ縮退させたが、 その量は手元で第一原理導出 + 独立 cross-check 済みで companion の中身だった。 著者判断で「値は存在し、 次稿で報告する」 型に差し戻し。

## <a id="dissolve-by-definition"></a>「その量は scheme / 規約に依る」 には撤退でなく定義で答える (2026-09)

「X は scheme 依存だから予言にならない」 型の指摘は、 しばしば **X が何を指すか宣言していない**ことに由来する。 この時の選択肢は撤退 (主張を落とす) だけではない。

**ルール**: 指摘を受けたら、 まず **問題の量を一意に指す言い方が存在するか**を探す。 存在すれば、 その定義を本文に書くだけで曖昧さは消え、 caveat 節ごと不要になる。 存在しなければその時に撤退する。

- 良い定義は**物理的に指させる**もの (「form factor の零運動量値」「閾値以下の漸近形」「保存量の比」) で、 手続きの名前 (「MS-bar での値」) ではない — 手続き名は scheme 依存性をむしろ確認してしまう。
- 定義が効くのは、 その点で量が**解析的**な時 (例: 質量つきループの form factor は閾値 q² = −4m² に枝点を持つが原点では解析的 ∴ 零運動量値は一意)。 解析性が無い所を定義で押し切ろうとすると、 指摘は正当なので撤退が正解。
- 定義を書けば、 同じ指摘が再来した時の応答も固定される (= 撤回でなく定義の提示)。 その応答を decision ledger に書いておく。

**なぜ**: 撤退は安全だが、 論文から情報が消える。 定義は 1 句で済み、 主張は残り、 referee の懸念も閉じる。 曖昧さの指摘を「主張が弱すぎた」 でなく「名指しが足りなかった」 と読む余地を、 常に一度は検査する。

起源 (2026-09): 上と同じ arc。 「その分離は prescription 依存」 という正しい指摘に対し、 量を物理的に指させる定義で名指すことで caveat 節を削除できた。

## <a id="title-claim-check"></a>題・副題の 4 検査 (読者語彙 / 非自明 / caveat 生存 / 統計 register) (2026-09)

giving-talks の題の基準 (主題 / レベル / 引き / 既知語、 平叙断定か疑問文) を paper に当てるとき、 再構成後の題で特に踏む 4 つ:

1. **名詞句ごとに「読者は本文なしで parse できるか」** — 著者の造語・内部略号は落とす。 典型 = 演算子の尺度と無次元結合の混同 (尺度の意味で「⟨尺度名⟩ coupling」 と書いたが、 結合自体は無次元 → 「⟨無次元の parameter⟩ of order unity」)。
2. **副題は非自明な情報を運ぶときだけ付ける** — 読者が本文を読まなくても知っていること (分野の標準的な定性事実) は副題にしない。 副題候補ごとに「これは読者に自明か」 を問い、 自明なら削るか、 観測が要求する量に置換する。
3. **題の主張は paper 自身が列挙した caveat が倒れても生き残る形にする** — 機構が実際に働くことを断定する題 (「X が宇宙を reheat する」) は、 その regime の整合性が open なら書けない。 「観測は A と B を見分ける」 型は caveat の帰趨に依らず成立する (= [#assumption-dependent-claim-framing](#assumption-dependent-claim-framing) の題版)。
4. **2σ の主張を題・abstract で「requires」 にしない** — 忠実な形は「within two standard deviations the data leave only X」。 別 baseline で対抗シナリオが生きているなら「requires」 は偽 (= [#claim-strength-three-tests](#claim-strength-three-tests) の偽検査。 対抗シナリオが残っていないかを問う user の一言で発覚)。
5. **否定語で始まる複合名詞は hyphen で結ぶ** — 英語の「No X does Y」 は「Y する X は無い」 (全称否定)。 「X が無いこと」 を名詞化した「No-X」 を主語にするなら hyphen が意味を担う: 合成例 "No-collision term dominates the sum" と "No collision term dominates the sum" は逆の主張。 冠詞を落とした題ほど滑りやすい ("The no-X …" なら誤読しない)。 "Non-" / "Zero-" / "Null-" を頭に置く題も同じ検査。
6. **冠詞は題の形で決める** — 名詞句の題は頭の冠詞を落とす慣例 (「Decay rate in …」)、 副題が主語 + 動詞の文なら冠詞を残す (「The decay rate decides」。 落とすと見出し語になる。 複数形の一般名詞 「Black holes are stable」 だけは無冠詞で文になる)。 無冠詞にしたいなら文を名詞句に変える。

起源 (2026-09): 再構成中の private paper で題を何度も回して確定した session。 却下理由は上の 4 検査にそのまま対応した (無次元量に尺度の語 / 副題が自明 / 「requires」 は統計的な過大表現 / 機構の断定は整合性が未解決)。 確定形 = 「A vs B in ⟨model⟩: The ⟨observable⟩ can tell」 (疑問の形をした平叙断定、 "can tell" が現状の分離の強さに忠実)。 却下案は原稿 header に理由つきで温存する。

## <a id="characterization-vs-derivation"></a>「導出」 と「特徴づけ」 を混同しない + 表現 (座標) を定義や公理の位置に書かない (2026-09)

**症状 1 — 導出に見える特徴づけ**: 「自然な要請 Y を置くと理論 X しかありえない」 型の主張は、 Y の中に X の物差しが既に入っていることが多い (例: 「量子測定より識別性能の高い測定は無い」 という要請は trace 距離 = 量子の物差しを先に借りている)。 このとき言えているのは **X の身分証** (= X と同型でないものは Y を満たさない、 iff の特徴づけ) であって **X の導出** (= X を知らない前提から X が出る) ではない。 3 検査: (a) Y の文面に X 固有の量 (距離・norm・構造) が入っていないか / (b) Y を満たす X 以外の model が無いことは定理か、 それとも Y が X を言い換えただけか / (c) 「なぜ X か」 に答えているか、 「X は他と混ざらない」 に答えているか。 書き方は 「X の身分証」 と明示し、 「導出」 「当たり前の仮定から」 を使わない。 出典 = 一般確率論の量子論特徴づけ (状態識別の性能上限) を教科書序章に引く場面の 2026-09-06 検討 (owner「大したことは言えてない気がしてくる」 → 言えること = 非 X model は隠れられない / より弱い上限では足りない / 1 個の量で検証可)。

**症状 2 — 表現を定義に昇格させる**: ある対象の便利な座標 (Bloch 球、 密度行列の書き換え、 特定の基底) を 「状態の定義」 や 「公理」 の位置に書く。 層を分ける: ① 定義 (何を状態と呼ぶか、 例: 測定統計の同値類) / ② 観測事実 (その表現に何個の数が要るか) / ③ 公理 (許される値の集合の形、 確率の関数形) / ④ 道具 (絵、 座標、 記法)。 ④ を ① や ③ の位置に書かない。 ④ の寿命 (2 準位限定の球、 有限次元限定の行列) が別の記法の導入時期を決めるので、 「いつ ρ を出すか」 は好みでなく道具の射程から決まる。 owner 指摘 2026-09-06 「Bloch 球は単なる道具では」。 隣接 = [`#claim-strength-three-tests`](#claim-strength-three-tests) (強い言明の偽 / generic / tautology)、 [`#dissolve-by-definition`](#dissolve-by-definition)。

## <a id="uniqueness-claim-exhaustion"></a>「X だけが届く」 型の唯一性主張は列挙表 + 前提 + regime 整合で支える (2026-09)

題や abstract が「この機構 / channel だけが条件を満たす」 と言う瞬間、 それは定理でなく**列挙の主張**になる。 user の一言「本当に確実に確認されてるの？」 に答えられる形を先に用意する:

1. **前提を列挙する** (場の内容 / 背景場の値 / 線形化 / パラメータ範囲)。 「他に無い」 はこの前提の下でしか言えない。
2. **候補を全部表にする** — 各 channel に「条件に届くための要求値」 と「届かない理由」 を 1 行ずつ。 理由は数値 (要求値が模型の妥当領域の外) か構造 (保存流への微分結合は位相回転で消える / fermion は Pauli で指数成長しない / 重力は (m/M_P)² 抑制) のどちらかで書く。
3. **唯一の候補が要求される regime を、 模型の他の場所で整合させる** — 例: 結合 O(1) が必要と出たら、 その値が模型の別の時期・別 sector (有効結合の値等) をどう変えるかを検査。 未解決なら共著者への問いとして note + 原稿の著者注に残し、 題はその帰趨に依らない形 ([#title-claim-check](#title-claim-check) 3) に落とす。
4. **閾値の精度を書く** — 線形化で出た閾値には 2 次項 (例: 場の再定義で現れる項の変調) が O(1) で効くことがある。 「≳ O(1) の閾値」 は桁の主張であって小数 1 桁の主張ではない。

起源 (2026-09): 同 private paper。 候補 channel を走査して 1 つだけが条件に届くと結論した後、 user の確認質問で前提と弱点を列挙する監査 note を切り、 題を「機構が起きる」 型から「観測が 2 つの機構を見分ける」 型に降ろした。

## <a id="second-example-refine"></a>二例目が出たら refine

将来別 paper で同様の audit を実施したら、 script を `claude-config/scripts/` に generic 化、 本 convention を refine。 現状は 該当 private paper repo で完結。

## <a id="box-test-vs-joint-posterior"></a>「$n_s$ が ±2σ 内 ∧ $r$ < 上限」 型の 1D box test は joint 領域を過大評価する — 縁に居る模型は公開 chain で 2D 判定 (2026-09)

**Pattern**: 2 つの観測量への制約を「各 1D の ±2σ / 95% 上限を独立に満たす」 で判定すると、 模型が片方の上限の縁 (例: $r$ の 95% 上限付近) に居るとき許容域を過大評価する。 joint posterior の 95% 等高線は角で切れており、 1D box の角は 2D では外。 起源事例 (2026-09、 private paper repo): 1D box で開いていた parameter 窓の大半が joint 2D で閉じ、 それに依っていた中心主張が消えた。

**Fix**: (1) 公開 chain / 等高線点列 (観測論文の著者 repo に `contour_lines/` `chains/` があることが多い) で各模型点の信用水準 $C$ (= その点を通る HPD 等高線) を計算し、 軌跡上の最小値で判定する。 (2) **基線を混ぜない**: $n_s$ を dataset A (BAO 無し) から、 $r$ の上限を dataset B (BAO 込み chain 由来) から取ると、 存在しない組合せで判定している。 (3) tail の信用水準 (99.9x%) を 0.01% 刻みで引用しない — 65k sample の KDE は手法で 0.05–0.13% 動く。 2 自由度の $\Delta\chi^2$ か「$\gtrsim99.7\%$」 に丸める。 (4) 等高線への「距離」 は物理的に意味のある軸に沿って測る ([`scientific-computing.md#contour-distance-axis`](scientific-computing.md#contour-distance-axis))。 (5) 図から起こした等高線の精度は線幅 (~0.001) なので、 それ以下の「接触」 判定はしない。 (6) **引く中心値・上限の出典と data の組み合わせは、 その値を表・式・キャプションで出している頁で確かめ、 組み合わせの label もその頁の語で書く** — 拡張模型の論文は基本の模型の値を companion の論文から引くだけのことがあり、 abstract の上限 (その実験単独の likelihood) と図の組み合わせ (他の data を足したもの) の上限は別の数になる (実測: 同じ論文の 2 つの 95% 上限が別の組み合わせの値だった)。 (2) の「基線を混ぜない」 は、 この確かめの後でしか判定できない。 表の値は語の座標で行と列の見出しに結び ([`office-automation.md#pdf-table-layout-aware-reading`](office-automation.md#pdf-table-layout-aware-reading))、 照合の script には列や頁を入れ替えた foil を入れる。 図の軸の量は [`scientific-computing.md#figure-vector-extraction`](scientific-computing.md#figure-vector-extraction) の「軸の量は図の軸ラベルで読む」。

## <a id="threshold-is-not-regime-onset"></a>近似が破れる閾値は、 反対 regime の始点ではない (2026-09)

**Pattern**: 「パラメータ $X\gtrsim x_0$ で narrow-resonance の式が使えなくなる」 を「$X\gtrsim x_0$ で broad / tachyonic 共鳴が起きて速く終わる」 と読み替える。 前者は記述の限界、 後者は別の力学の主張で、 後者には独自の根拠 (成長が完了する条件、 膨張との競争) が要る。 起源事例 (2026-09、 private paper repo): 閾値の上を「瞬時に完了する」 と同一視して観測の結論の核にしていたが、 盲検査読 + 著者側の再計算で、 膨張による共鳴 parameter の減衰が速く、 線形成長では完了に桁で足りないと判明。 引用していた lattice 論文は別の regime の結果だった。

**Check**: 閾値の上について書く前に (a) その regime で「完了」 に必要な量 (占有数・エネルギー移送率) を書き下し、 (b) 膨張・振幅減衰・非線形の各競争相手と時間 scale を比べ、 (c) 引用先が同じ regime (同じ $q$、 同じ $H/m$) を扱っているか確認する。 閾値の上は「記述できる regime の終わり」 と書き、 到達不能な参照点 (瞬時値) は「模型外の参照」 と明記する。

**2026-09-08 追補 (同事例、 第 3 回盲検)**: 閾値が 2 つあると (「式が使えなくなる」 $x_0$ と「膨張が成長を止めなくなる」 $x_1\gg x_0$)、 本文が両方を「the threshold」 と呼び、 表は $x_0$ 未満の history だけを載せ、 abstract の分離幅は $x_0$ 未満だけから取られる、 という型になる。 $x_0<x<x_1$ の history は本文の定義では摂動的なのに表に無く、 載せると分離幅が縮む (同事例でも縮んだ)。 → **(d) 2 つの閾値に別の名前を付け、 その間の history を表・図に 1 行以上載せてから分離幅を書く**。 (e) 閾値の数値は「onset」 の定義 (振動開始を $\epsilon_V=1$ / $\epsilon_H=1$ / 最初の零点通過のどれで取るか) に有意に依存するので、 定義を書かずに 2 桁で書かない ([`scientific-computing.md#onset-is-eps-H-one`](scientific-computing.md#onset-is-eps-H-one))。

## <a id="decomposition-label-check"></a>分け方で定義した項に物理の名前を付けたら、 全域で中身と合うかを確かめる (2026-10)

**Pattern**: 1 つの量を、 積分路・切り方・規約で 2 項に分け、 項に物理の名前 (on-shell / off-shell、 共鳴 / 背景、 極の項 / 残り、 など) を付ける。 すると、 項が切り替わる値が「物理が始まる値」 に読まれ、 項ごとの 2 乗が別々の確率に読まれ、 ある領域で項の中身が文献の同じ語と別の物になっていることが見落とされる。 読者は名前で読むので、 ここで読み違いが起きる。 近似の破れの閾値は [#threshold-is-not-regime-onset](#threshold-is-not-regime-onset)、 こちらは分解の切り替え。

**Check**:

- (a) 切り替わりが分け方に依らないかを確かめる。 別の分け方で同じ値に切り替わらないなら、 その値は分け方の都合で、 開始の時刻や閾値の物理として書かない。 全体の量が滑らかかも見る。
- (b) パラメータの両極限で、 各項が何を含むかを文献の語で書く。 文献が反対の語で呼ぶものがその項に入る極限があれば、 本文で断る (実測)。
- (c) 項の 2 乗を確率と読む前に、 全体との差 (干渉) を積分で数える。 干渉が 2 乗の項より大きく符号が逆のことがあり、 符号はチャンネルで変わることがある (実測)。
- (d) 依存性がどの因子から来るかを恒等式で分ける。 新しい効果と書いた依存が、 既知の因子の言い換えのことがある (実測)。 その場合、 既知の物理との違いの根拠は依存性に置けない。
- (e) 式は観測量 (積分した率) まで持っていき、 既知の 2 つの極限と、 極限の順序で全体が変わらないことを確かめる。 分け方が順序に依るなら、 それも書く。
- (f) 分解の恒等式から測定の予言を立てる前に、 各項の期待値を取る状態が、 動かすパラメータに依らないかを確かめる。 条件づけ・規格化・選択の後の状態は装置のパラメータに依る。 恒等式が正しくても 2 つのパラメータ値の差で状態の項は消えず、 片方の項に見える振る舞いが和では打ち消し合って消えることがある (実測)。 入力の状態を固定して、 和そのものをパラメータの関数として計算してから書く。 入力の状態の種類で答えが変わるなら、 予言の文に種類を書く。 差で消す形を残すなら、 規格化の後の状態がそろう入力の条件と、 それに要る入力の精度を書く。

## <a id="abstract-geroch-compression"></a>Abstract = 文脈降下 + 3 message + 持ち帰る 1 文 (Geroch の introduction と conclusion の圧縮) (2026-09)

**Pattern**: 技術的言明を結果の順に並べた abstract (演算子の次元・coupling scale・信用水準の細かい百分率 …) は、 読者に文脈も持ち帰る 1 文も残さない。 abstract は論文の introduction (文脈降下 + 結論の先出し) と conclusion (束ねる 1 文) の圧縮版として組む ([`giving-talks.md`](giving-talks.md) の introduction 節と conclusion 節)。

**Form** (12 文前後): ① 文脈降下 2 文 (なぜこの量が観測に効くか → この模型ではそれが何で決まるか) ② 問い 1 文 ③ 3 message を各 1–2 文の非技術的な言い方で (道具立ての語は落とす、 恒等式は本文へ) ④ 持ち帰る 1 文 = **試験であって判決ではない** (「data は模型に X を求める」 は論文の価値を殺す。 「観測量 Y がこの模型の X を試験し、 次の測定が決着させる」) ⑤ 現状の data との比較は**付加情報として末尾** ⑥ 副産物は最後の 1 文。 **禁止**: 同格の挿入句 (「the only ⟨類⟩, a ⟨具体⟩, …」)、 絶対的な有意度 (「最新 data が Nσ で排除」 = 中心値が動けば死ぬ、 [#moving-observational-baseline](#moving-observational-baseline))、 細かい百分率 (99.7% → 3σ → 不要なら削除)、 自分の旧提案を受け身で書くこと (「proposed for this model」 → 「that we proposed earlier」)、 先行詞の無い複数形 (「the bounds will tighten」 → 「however the observational bounds tighten」)、 対象の長い言い換え (説明句で呼ぶより標準の名で呼ぶ)。

## <a id="sentence-length-audit"></a>文の長さの機械 sweep — 40 語超は分割候補 (2026-09)

**Pattern**: 1 文 1 行の source では、 tex の各行を文として語数を数えるだけで冗長の分布が出る。 40 語超の文はほぼ例外なく 2–3 主張を接続詞で繋いだもので、 分割しても情報は落ちない。 起源事例 (2026-09): 主張を運ぶ節 (abstract / intro / 結果節 / summary) の 40 語超 36 文を全て分割し (36 → 0、 30 語超 82 → 56)、 反復していた修飾句 (同じ限定を節内で 4 回) を各節 1 回に減らした。

**How**: `$…$` を 1 token に潰して語数を数える script ([`check-paper-prose.py`](../scripts/check-paper-prose.py) の L = 文単位、 脚注は本体と別に数える) を回し、 長い順に読む。 分割は主張の切れ目で切り、 接続詞 (so / and / while) を period に替える。 圧縮した文は読み直して、 落ちた load-bearing 語と**その節で裁定済みの主張の型** (相対 / 予言 / 試験) が残っているかを数える (同事例: 短縮の反復で絶対文に戻った)。

## <a id="advocate-pass-after-retraction"></a>撤回を採用したら advocate pass を 1 回回す — 誤り探しの査読の反復は最小の防御可能な主張に収束する (2026-09)

**Pattern**: 盲検・cold-eyes を「主張は証明されているか」 の向きで反復すると、 各 round は主張を削ることしかできない (退けた主張が実は正しいかは誰も問わない) ので、 生き残りは「最も守りやすい主張」 に収束する。 その過程で、 **計算で退けた regime と定義で退けた regime が同じ顔をする**。 起源事例 (2026-09、 private paper repo): ある regime を 2 round の盲検で「閾値の上は完了しない」 → 「模型外の参照」 と書き換え、 題の二分法だけが残った。 元の主張が消えてよいのかを問う著者の一言で段ごとに棚卸しすると、 定理と数値の段は耐え、 「その結合の範囲は模型外」 の 1 段だけが計算でなく判断だった。 著者側 anchor script の scan 範囲を 1 行伸ばすと、 その regime では成長が速やかに完了し、 引用していた先行研究の parameter とも整合した — regime は在ったのに定義で消していた。

**Check** (撤回を本文に入れる turn で): (a) 撤回が覆う parameter 領域と覆わない領域を書き分ける (「x まで完了しない」 は「x より上で完了しない」 を含意しない)。 (b) 覆わない領域を**同じ anchor script で**走査してから「模型外 / beyond scope / we do not follow」 と書く — 安価な scan があるのに scope 宣言で閉じるのは cell 埋め。 (c) 生き残った regime は消さずに置き、 その regime が模型の他の部分に課す条件 (値札) を数字で付ける ([#odd-coupling-sign-before-pricing](#odd-coupling-sign-before-pricing))。 (d) reviewer の finding 採用 = 前提検証 pass ([`physics-verification-cycle.md`](../../ai-collaboration/conventions/physics-verification-cycle.md#external-ai-referee-premise-verification)) の対として、 採用後に advocate pass「退けた主張はどこなら生きるか」 を**1 回だけ**、 数字で回す (advocate の反復は逆向きの ratchet)。

## <a id="nested-assumption-levels"></a>「A か B か」 の構成論争は入れ子にする — 一般 parametrization で走査し、 仮定を 1 つ足すごとに決まる関係と予言点を示す (2026-09)

**Pattern**: 模型の「構成」 に複数の読み (例: ある因子が変換から自動的に出るのか、 手で入れたのか) があり、 どちらを採るかで自由 parameter の数が変わるとき、 「A に決めろ」 と共著者に迫るか、 曖昧なまま独立 parameter として走査するかの二択になりがち。 前者は系譜 (前作の思想) とぶつかり、 後者は模型が持つ**予言点**を捨てる。 起源事例 (2026-09、 private paper repo): 系譜の前作が構成を決めていなかった (作ごとに A 寄り・B 寄りが割れていた) ため、 現行稿は「言葉は A、 表は B」 の混在で、 盲検が「どちらか書け」 と指摘した。

**Fix**: 入れ子で書く。 (1) **一般レベル** = 前作と同じ現象論 (parameter は独立、 表・図の走査はここ) → (2) **構成レベル** = 1 つの仮定 (例: ある因子は変換由来で、 手で入れた部分は無い) で 1 つの関係 (例: 2 つの結合の比が固定される) が決まる → (3) **最も制約された特別な場合** (例: 全結合が共通 = 元の理論の Lagrangian そのもの) で残りも決まり、 parameter が消えて**予言点**になる。 各段で「仮定 1 つにつき関係 1 つ」 を明示し、 予言点は表・図に 1 行 / 1 点として**主役**に置く。 前作の自由さを否定せず、 「この scenario ならここまで決まる」 と読める。 共著者への問いは「A に決めてよいか」 でなく「この入れ子でよいか」 になり、 軽くなる。

**Check**: (a) 各レベルの仮定と、 それが決める関係を 1 対 1 で書けるか (書けないなら段が混ざっている)。 (b) 一般レベルの「独立 parameter」 が暗に何を許しているかを 1 文で言う (例: 「元の potential が自前の依存を持つことを許す」 = 変換の因子自体は外せない)。 (c) 予言点の数値は同じ fixed-point 機械で出し、 表の他の行と同じ精度で置く。 (d) 参照行 (どの history も超えない極限値) は「上限」 と呼び、 未計算の regime の代表にしない ([#threshold-is-not-regime-onset](#threshold-is-not-regime-onset) (c))。 (e) 別機構 (例: 量子補正で同じ因子を生成する付録) が同じ関係に落ちる条件と落ちない条件を 1 文で添える。

## <a id="odd-coupling-sign-before-pricing"></a>regime に値札を付ける前に、 結合の符号に奇な量と偶な量を仕分ける (2026-09)

**Pattern**: regime を定める効果 (成長率 ∝ γ²) は結合の符号に偶、 その regime の値札 (別の時期の質量項 ∝ γ) は奇、 という組合せで、 片方の符号だけで値札を書くと、 反対符号では売りになるものを「代償」 と報告する。 起源事例 (2026-09、 同上): 強結合 regime の値札を「不安定化する質量項」 と書いたが、 質量項は γ に奇で、 負符号では同じ大きさの**正**質量 = 真空を安定化する標準機構そのものだった。 原稿は符号を固定していなかった。 さらに値札の 2 軸目 (高 scale での結合の符号) は外部入力の誤差内で決まらなかったので、 判決でなく依存関係として書く。

**Check**: (a) 各 parameter について、 主張のどれがその符号に偶でどれが奇かを列挙する。 (b) 符号が模型で固定されていなければ両枝を事実として書き、 符号の決定を模型の構成 (共著者・原典) に routing する。 (c) 外部入力 (top 質量・α_s・結合の running) に依存する verdict は「中心値では X、 誤差内で Y」 の形で書き、 中心値の verdict を事実にしない。 (d) anchor script は両符号を走らせる (偶なら一致が検算、 奇なら両枝の数字が本文に要る)。

**2026-09-08 訂正 (同事例)**: 上の仕分けは不完全だった。 奇な項を 1 つ (微分由来の質量項 ∝ γ) 見つけて反対符号を「安定化」 と報告したが、 小結合で「無視できる」 として落としていた別の質量項の conformal 因子 $e^{-\gamma\chi/M_\text{P}}$ も奇で、 regime の結合 × 場の excursion では指数が大きくなり verdict を反転させた (負符号は別の scale を持ち上げて除外された)。 → **(e) 仕分けは全項で行う。 小結合で落とした項は、 regime の結合 × 場の excursion の指数を入れ直してから落とす** (negligible × 大きな指数因子は negligible ではない。 dilaton 型結合では質量次元を持つ parameter は必ず走られる = 4 点結合を不変にする関係は質量項を不変にしない)。 原典の convention 確認 (共著者への問い) より、 自分の Lagrangian の全項を再評価する方が安価で決定的だった。 訂正は元の判断記録と本 anchor の双方に日付つきで置く ([`physics-verification-cycle.md`](../../ai-collaboration/conventions/physics-verification-cycle.md#external-ai-referee-premise-verification) item 7 の型)。


## <a id="appendix-order-by-first-reference"></a>付録は本文での初参照順に並べる — 「展望は最後」 は本当に展望のときだけ (2026-09-08)

**Pattern**: 付録を足す・移す pass のたびに順序が場当たりになり、 本文で先に参照される付録が後ろに来る。 「outlook だから最後」 の例外を作ると、 その付録が実は方法の説明 (レビュー) だったとき例外の根拠が消える (2026-09-08 の研究 LaTeX project の付録 = 題は私が付けた "Outlook"、 中身は方法の段取りの説明)。

**Rule**: 序論の案内文を除いた本文での初参照位置で並べる。 除くのは案内文の段落だけで、 序論の他の段落 (例: 結果の要約が「derived in App. X」 と付録を指す) からの参照は数える (2026-09-11 の gate record は、 結果段落の先行参照を「規則は案内文を除く」 として除外し付録順を ○ にした = 誤適用)。 序論の結果段落まで案内扱いにするかは原稿ごとの著者判断で、 そうするなら判断を記録に残し、 検査の設定 (`--exclude-section`) に書く。 案内文も同順に書き直す。 機械 = [`check-paper-prose.py`](../scripts/check-paper-prose.py) (A1 = 初参照順と file 順の食い違い / A2 = 本文から参照されない付録 / A3 = 案内文の中の順、 除いた行は毎回印字)。 ⚠️ この検査が見るのは付録の最上位の節だけ = 1 つの付録に小節を並べる原稿では、 小節の順の null は証拠にならない (実測)。 小節の順は、 小節ごとの label の本文での初参照の行を出して比べる。 移動は verbatim の MOVE (label 不変で cref は追従)、 位置依存の語 (previous / next appendix、 above / below) を grep 0 にする。 例外は「本当に展望しか書いていない付録」 だけで、 題でなく中身を読んで判断する。

**Cost**: 共著者への連絡で付録の letter が変わる → [`research-email.md#appendix-letters-unstable`](research-email.md#appendix-letters-unstable)。 diff PDF には MOVE の artifact が出る → [`latex.md#latexdiff-move-artifacts`](latex.md#latexdiff-move-artifacts)。

## <a id="new-symbol-convention-consistency"></a>文献との対照のために導入する記号は、 まず本稿の規約で定義する — 文献の正規化は辞書 1 文で吸収する (2026-09-08)

**Pattern**: 付録で文献の量をその文献の規格化 (階乗因子なし) のまま導入し、 本稿の縮約規約 (階乗の重み付き) と衝突した。 「文献に合わせた、 意図的」 と答えたが、 同類 sweep の grep 出力にその規約の行が出ていたのを読み落としていた (著者訂正)。

**Rule**: 新記号を定義する前に、 本稿の同種の縮約・添字型・分数の書き方を grep して型を決める (ε の重み、 frame / spacetime 添字、 display の `\frac`)。 文献との換算は「文献の量 = 本稿の量 × 定数」 の辞書 1 文で書き、 結合定数は本稿の正規化で印字する (例: 文献の量 = 本稿の量 × 定数、 文献の結合の値 ↔ 本稿の結合の値)。 数値が変わるなら、 機械 anchor と living note に同じ turn で換算行を足す (CONVENTIONS「規約を変えたら同じ作業で」)。

**Check**: 定義 display の直後に、 本稿の既存の同型の式 (ε ε の縮約、 反対称化の重み) を 1 つ並べて読み、 重みが揃うか見る。 「文献がそう定義している」 は本稿内の不整合の言い訳にならない。

### <a id="notation-continuity-across-sections"></a>同じ対象の記法を本文・付録で照合する

既存の量を使う付録を書くときは、定義・引数・係数・文章中の呼称を本文と突き合わせる。原稿が保持すると定めた粒子種などの添字を、「以下では省略する」という局所的な断りで落とさない。空間運動量と四元運動量、実際の物理量と補助量を区別する。式の短縮が必要なら、対象の識別を保ったまま不要な中間量や重複を減らす。

修正時は対象ごとの記法を列挙し、節の境界を越えて出現箇所を照合する。新ルールを追記するだけでなく、古い略記を許す規約・定義・コメントも検索する。履歴の記録と現在採用するノートを分け、旧記法を live note の参照経由で戻さない。純粋な散文修正の保持検査には [cross-reference checker](../scripts/check-latex-crossrefs.py) の baseline 機能を使えるが、記法自体を変更する場合は機械的なバイト一致を適用せず、変更範囲と式・ラベルの対応を個別に検証する。

### <a id="notation-rename-sweep"></a>記法を原稿全体で統一する pass の受け入れ検査 (2026-09-12)

一括改稿そのものの純粋性 (置換以外が紛れていないか) は機械で見る = [`ai-collaboration/scripts/check-rename-purity.py`](../../ai-collaboration/scripts/check-rename-purity.py) (逆写像して残差だけ読む、 規律 = [`physics-verification-cycle.md#inverse-map-purity`](../../ai-collaboration/conventions/physics-verification-cycle.md#inverse-map-purity))。 機械が通った後に人が読むのは次の 4 点で、 どれも「置換は正しいが原稿が読めない」 型:

1. **初出で scheme を定義したか** — 改稿は綴りを揃えるだけで、 **記法の意味を導入する文は増えない**。 新綴りの初出箇所で、 (a) 区切り記号の後ろが何を表すか、 (b) 区切りの無い素の形が何を意味するか、 (c) 複合添字の区切り (`,` 等) の意味、 の 3 つが読者に渡っているか見る。 実測では初出は 2 つの具体例を語で説明するだけで、 一般則は遠く後ろの付録にしか無かった。
2. **同じ対象の 2 綴りの関係を、 必要な位置で述べたか** — 全体を表す綴りと、 その一部 (特定の寄与) を表す下付きつきの綴りが併存するのは正しい。 述べるべきは**どこで一致するか**で、 その 1 文が最初に必要になる箇所より後ろにあると読者は橋を架けられない ([`#statement-placement-check`](#statement-placement-check) の記法版)。
3. <a id="delimiter-overloading"></a>**区切り記号が既存の用法と衝突していないか** — 新記法が縦棒・括弧・下付きを使うなら、 同じ display の中で**同じ字面が別の意味**で既に使われていないか読む (「～に関する変分」 の縦棒と「～の部分に制限」 の縦棒、 「～で評価」 の縦棒)。 改稿前は片方が下付き添字だったので衝突が無く、 **改稿によって初めて生まれる**。 大きさ (`\big|` と `|`) は区別の根拠にならない (読者は意味でなく寸法を読まされる)。
4. **改訂しなかった節にこそ旧綴り・別綴りが残る** — 「この節は既にその scheme を使っていた」 と判断して触らなかった節が、 実は自分の中で 2 通りの綴りを使っていることがある (実測: 引数つきの長い形と短い形、 全体を指す素の形と一部を指す形が同一節内で混在)。 改稿の対象外と宣言した節を、 改稿後に 1 度読む。 comment 行の旧綴りは `--forbid` で走査する (comment を後で復活させると表に出る)。 **綴りの棚卸しは機械で**: `check-rename-purity.py --after <file> --census '<記号族の regex>'` が、 一致した綴りごとに出現数・行範囲・**その綴りが現れる節**をまとめて出す (2 綴りが別々の節に住んでいれば一目で分かる。 diff は綺麗なままなので純粋性検査では出ない = この項が機械化できる唯一の形)。
5. <a id="single-letter-rename-completeness"></a>**1 文字の記号の改名は、 積の形を取りこぼす** — 1 文字の変数を語境界の正規表現 (前後が英字でない) で置き換えると、 空白を入れずに積を書いた形 (`2ut` = 2·u·t、 `e^{-2uy}`) の u は「後ろが英字」 なので置き換わらない。 逆写像の純粋性検査は「置き換えた所が純粋か」 を見るだけで、 置き換え損ねは見ない (実測: 置き換え損ねが残り、 次の作業で式を読んで見つかった)。 置き換えの後に、 数式の中で旧い文字が他の英字に接している所を列挙して 1 つずつ読む (`--census` に接した形の regex、 例 `(?<![A-Za-z\\])u(?=[A-Za-z])` を渡す)。 範囲の判定を正規表現の終端に頼らないことも合わせる ([`batch-text-edits.md#span-by-first-terminator`](batch-text-edits.md#span-by-first-terminator))。
6. <a id="single-letter-macro-pass"></a>**1 文字の記号を macro に替える pass (frame 添字を太字の macro に、 揺らぎに hat、 等) は、 候補を数式の文脈で全部並べて 1 つずつ判定する** — 一括の置換は必ず壊れる。 同じ字が添字以外の役を持つ: 時空の次元 (`d^d\ell`)、 冪 (`(\ell^2)^a`)、 場の種類のラベル (`J^{e\omega}`)、 係数や関数の名 (`c_R`、 `f_1`)、 trace 公式の一般のベクトル (`\mathrm{Tr}[\slashed a\,\slashed b]`)、 射影子の名、 アクセントの付いた記号 (`O(\hat e)`)。 実測: 前の一括の pass が次元と冪を添字と取り違えて太字にしていた / 機械の案が種類のラベルを拾った。 道具 = [`tex-letter-census.py`](../../ai-collaboration/scripts/tex-letter-census.py) (候補を添字の中と外に分けて全部並べ、 添字の中は macro に替える案を行ごとに出す。 案は判定ではないので全行を読む。 添字の外の候補 = 関数の引数・散文の `$b$`・`\epsilon[abcd]` の中は手で当てる)。 当てた後は純粋性 (`check-rename-purity.py`) と組版 (頁数・未定義の制御綴) を見る。
   - **括弧の無い添字は括弧で包む** (`x^a` → `x^{\ba}`): macro が `\textbf{…}` に展開されると `x^\ba` は壊れる。
   - **規則を字面で当てる前に、 揃える先の記法 (最新の論文など) でその対象が何と書かれているかを引く** — 「記号 X に hat を付ける」 を字面で当てると、 揃える先では別の対象に予約された記号ができる (実測: vierbein の揺らぎを h と書いていた note の h に hat を付けると、 揃える先では計量の揺らぎの記号になる。 vierbein の全体のほうに hat が付いていた note もあった)。 揃える先が決まっているなら、 規則の字面でなく揃える先の綴りに合わせる。
   - <a id="index-height-per-equation"></a>**添字の上下を揃える pass は式ごとに行い、 1 つの記号だけを上げ下げしない** — 揃える先の文書は、 同じ量の添字の上下を文脈で使い分けることがある (定義・変換則では全部下、 頂点関数との縮約では場が frame 上・時空下 など)。 記号ごとの一括置換は、 同じ式の他の脚 (右辺の変換の parameter・縮約の相手・微分した量の脚) と上下が食い違う式を作る (実測)。 当てる前に、 揃える先がその量を文脈ごとにどの上下で書いているかを全部引き、 変えた式ごとに自由添字が `=` の左右で揃い、 縮約が上下の組になっているかを読む。
   - <a id="decorate-after-definition"></a>**記号を飾る (hat・太字) 前に、 その記号・括弧が文書の中で何と定義されているかを確かめる** — 期待値の括弧 `\langle\cdots\rangle` に見えても、 中身が 1PI の 2 点関数 (2 次の有効作用の係数) なら、 揃える先の頂点関数の名で書く。 見た目どおりに飾ると別の量 (期待値なら伝播関数) を指す表記になる (実測)。 著者に問うときも定義を添える ([`concise-output.md#define-before-notation-ruling`](concise-output.md#define-before-notation-ruling))。
   - **純粋性の検査の使い分け**: 改名が単射 (旧い綴り 1 つ → 新しい綴り 1 つ) なら逆写像 (`check-rename-purity.py --map`)、 2 つの旧い綴りが 1 つになる改名は前向き (`--forward`、 行数が同じこと)。 記号を飾るだけの pass は PDF の文字も数で比べる ([`compare-tex-builds.py --chars`](../../ai-collaboration/scripts/compare-tex-builds.py))。
   - **他の文書から写した式 (引用・転記) の記法をどうするかを pass の前に決め、 全 note で同じにする** — note ごとに「原典のまま」 と「揃える先に合わせる」 が割れると、 同じ引用が note によって違う綴りになる (実測)。 決めた方針は記録に残す。

### <a id="one-name-per-object"></a>1 つの対象には 1 つの名 — 同格で並べた 2 名は「どちらが類か」 を決めない (2026-09-12)

**規則**: 同じ対象を節ごとに違う名で呼ばない。 総称と具体名の**両方**が要るときは、 初出で 1 度だけ関係を述べ、
以後は**片方だけ**を通し名にする。 通し名には、 その文脈で射程の広い方 (= 機構で決まる類の名) か機構語を選び、
固有名は初出の同定に使う。

**同格は関係を決めない**: `an X, the Y of Z` と並べると、 書き手は「X (類) の Z における実例が Y」 のつもりでも、
読み手は定冠詞の付いた Y を総称と読む。 **関係節で書く** = `an X, which in Z is the Y`。

**How to apply**: 対象ごとに「本稿での呼び名」 を 1 つ決めて grep で数える (節ごとに割れていないか)。
論文内に既にある呼び名を優先し、 新しい名を作らない ([`#notation-rename-sweep`](#notation-rename-sweep) の 2 番と同じ原理: 綴りを増やさない)。

**実例 (2026-09-12〜13)**: (a) 負ノルム mode の類の名と、 ある模型での具体名を、 初出で同格に並べていた (`an A ghost, the B ghost of theory C`)。 以後の節では 2 つの名を交互に使い、 著者は同格の向きを逆 (A が具体) に読んだ。
→ 関係節 (`which in theory C is the B ghost`) にし、 通し名は類の名に統一、 極を指す語は機構の語にそろえた。 文献の使用頻度も通し名の選択根拠になる。 件数は [`ai-collaboration/scripts/inspire-phrase-frequency.py`](../../ai-collaboration/scripts/inspire-phrase-frequency.py) で title と全文を横並びに出す (件数は「どれが標準の呼び名か」 の証拠で、 正しさの証拠ではない。 引くときは日付と field を添える)。
(b) 恒等式を群の略称だけで `G identity` と呼んだら、 群の恒等式とも読めた → `G WT identity` のように恒等式の種類を名前に入れる (略語は本文初出で定義)。 (c) 比較の段落だけ先行研究の別名で書き、 本文は本稿の語だった → 本稿の語に統一。 名前を付けた極を後の節で `an unphysical pole` と総称に戻していた → 付けた名前で呼ぶ。 語順は文献の定番に合わせる (定番かどうかは件数で確かめる)。

## <a id="comparison-before-derivation"></a>比較の要点を導出の入口に置く

二つの理論・方法の違いを示すときは、同じ階層の見出しで並列に分け、冒頭に何が変わり何が共通かを短い比較表や段落で示す。名前を見出しへ足すだけでは、物理や計算の相違は伝わらない。相違を読者に推測させず、結論を表す主語と述語を書く。

両者を比較する表とまとめは、一方の枝の冒頭に埋めず、共通の親節で最初の枝が始まる前に置く。各欄はその主張を実際に支える式へつなぎ、対応する式がない場合は既存の別の式を便宜的に貼らない。必要な帰結を導出するか、主張を支えられる範囲に直す。保存則や「全体」の意味を左右する仮定は、その枝を読む前に表の近くで明記する。和の範囲と電荷の区別は [観測量と保存則の検証](scientific-computing.md#observable-projectors-and-symmetry) を参照する。

比較条件と観測量を揃え、条件を変えた結果を理論の差と呼ばない。異なる観測量の結果を並べる必要があるときは、その違いを表の近くで明示する。冒頭の比較は後の式へ直接つなぎ、導出は入力・演算子・初期状態・出力の依存順に保つ。冒頭だけを読んで相違点と比較条件を言い直せるかを確認する。検証の原理は [演算子・状態の比較](scientific-computing.md#operator-time-state-order) を参照する。

## <a id="euclidean-check-in-lorentzian-paper"></a>Lorentzian の論文に Euclidean の cross-check を載せるときは、 signature の写像と全体符号の anchor を 1 文で書く (2026-09-08)

**Pattern**: 付録の検算を Euclidean で行うのは標準だが、 「その結果が本稿の Lorentzian の式と同じ符号規約か」 を言わないと referee は比べられない。 著者の問い「ユークリッドでやって大丈夫か」 がその 1 文の不在を突いた。

**Rule**: (a) mostly-plus なら Wick 回転 x⁰ = −ix⁴ は座標変換で、 parity-even なスカラー密度の**相対係数**は signature に依らない (parity-odd = ε 1 個は i を拾う。 ε を 2 つ含む縮約 = Hodge 双対どうし 〔例 = 3-form の双対ベクトルの 2 乗〕 は εε の符号の分だけ反転するので、 Euclidean で双対の形に書いた結果は計量だけの縮約の形に戻してから写し、 写した先の εε で双対に直す。 実測: 双対の形のまま写すと誘導項の符号が逆になる)。 ただし**作用密度の全体符号は反転する** (iS_M = −S_E、 すなわち Euclidean の作用密度 = −Lorentzian の Lagrangian 密度。 有効作用も同じ)。 よって「Euclidean の pole は Lorentzian の有効作用の −1 倍で、 比べるのは括弧 (相対係数) どうし」 と 1 文で書く。 mostly-minus なら更に g → −g の (−1)ⁿ 則 (n = 逆計量の縮約数) が項ごとに入る。 (b) 全体符号は、 Euclidean の結果と「同符号」 と確かめても anchor にならない (その比較自体が Wick の符号を渡る)。 本稿の signature の中で振幅 ↔ 有効作用の辞書を定義から置き (e^{iS}: amputated 1PI 図の和 = i × Γ⁽ⁿ⁾、 e^{−S}: = −Γ_E⁽ⁿ⁾)、 外部の絶対量に結ぶ → [#absolute-sign-external-anchor](#absolute-sign-external-anchor)。 (c) 同じ入力を δ と η で解いて係数を比べる script は**相対係数**の signature 非依存性の検査で、 同じ辞書を両 signature に使う限り全体符号については恒等式 (必ず一致する)。 辞書の符号は signature ごとに置き、 script には「Lorentzian の括弧 = −1 × Euclidean の括弧」 を assert させる。

**2026-09-11 訂正**: 本 anchor の初版 (2026-09-08) は (a) で「共通因子は測度だけ」、 (b) で「ある項が Euclidean 有効作用の対応項と、 本稿の規約から出る項で同符号に一致」、 (c) で「δ と η の両方で解いて Wick dictionary が恒等になることを実測」 としていた。 3 点とも Wick の全体符号を落としており、 起源事例の原稿は有効作用の全体符号が逆のまま「確認済み」 と記録された (3 日後、 別 session の投稿前 gate が [#headline-claim-budget-check](#headline-claim-budget-check) の検算で発見)。 初版の文言は git history にある。

**Wording**: 自動詞の "continues with one common sign" は慣用でない (数学の "f continues analytically to" は別物)。 他動詞受動 "is analytically continued to" か、 動詞を避けて「座標変換だから不変」 で言う。

## <a id="absolute-sign-external-anchor"></a>符号を持つ印字係数は外部の絶対量に「全体反転で落ちる」 機械検査で結ぶ — 整合性検査の全 PASS は全体符号について何も言わない (2026-09-11)

**Pattern**: loop で誘導される有効作用の係数を印字する paper で、 数十本の検査が全 PASS のまま**有効作用の全体符号が逆**だった (起源事例 2026-09)。 検査はどれも次のいずれかで、 全体反転 Γ → −Γ に不変だった: (i) Ward–Takahashi 型の恒等式 (Γ⁽¹⁾, Γ⁽²⁾ に同次線形 — 両方反転しても成立)、 (ii) 比・相対係数・spin-parity channel への分解、 (iii) 振幅 ↔ 有効作用の同じ辞書を両辺に使う照合・校正、 (iv) 別 frame (Euclidean) の絶対値との比較で、 frame 間の橋 (Wick の符号) を未検証のまま渡したもの、 (v) 振幅の印字を Feynman 則と照合する regression (振幅の符号は見るが、 振幅 ↔ 有効作用の辞書は見ない)。 誤った版と正しい版の原稿に既存の検査を全部当てると、 全部が二つの版で同じ結果だった。 原稿 file を実際に開くのは 1 本 (頂点の表示を parse する audit で、 辞書は読まない) だけで、 残りは印字を script 内へ転記した検査か note 側の計算だった (= 印字が変わっても結果が変わらない構造)。 見分けたのは後から足した外部 anchor (原稿を parse し、 1 つの項を教科書の 1 loop の絶対量と比べる audit) だけだった。

**Rule**:

1. **物理的な意味を持つ符号** (有効作用の全体符号、 真空エネルギー・運動項・質量二乗の符号、 running の向き) を印字したら、 **外部の絶対量に結ぶ機械検査を 1 本以上**置く。 外部の絶対量 = 教科書の値 (1 loop 真空エネルギー〔Coleman–Weinberg〕、 真空偏極の遮蔽の向き・β 関数の符号、 共形 anomaly の係数 〔文献の値と比べる前の signature と T^{μν} の定義の換算 = [`scientific-computing.md#literature-sign-map`](scientific-computing.md#literature-sign-map)〕) か、 正定値性・unitarity。 その検査は**全体反転で FAIL しなければならない** — 原稿の辞書と係数を一斉に反転した版、 または誤っていた過去版に当てて落ちることを PASS 条件に含める (global-flip foil)。
2. **整合性検査は数えない**: 恒等式・比・channel 分解・同一辞書の校正・別 frame の値との「同符号」 は、 何本積んでも全体符号の証拠にならない。 fleet を「ALL PASS」 と報告するときは、 fleet が不変な変換 (全体符号 / 全体規格化 / 因子 i / Levi-Civita の向き / ε の規約) を列挙し、 それぞれを破る anchor の有無を並べて書く (fleet invariance の申告)。
3. **振幅 ↔ 有効作用の辞書は定義から置く**: 他の文書・別 signature の計算・数値の一致から写さない。 e^{iS} では amputated 1PI 図の和 = i × Γ⁽ⁿ⁾、 e^{−S} では = −Γ_E⁽ⁿ⁾ で、 両者は Wick の符号だけ異なる。 数値の一致から辞書を「同定」 したら、 比べた二つが同じ signature かを必ず書く (起源事例では、 signature の違う 2 つの計算の比較で出た −1 が、 signature の注記なしに原稿の辞書になった)。
4. **gate の worker は project の規約文書を前提でなく検算対象として扱う**: 規約文書に書かれた符号の同定こそ、 定義から導き直す。 起源事例で誤りを見つけたのは、 規約文書より先に辞書を白紙で導いた pass だった。

**Check**: (a) 符号を持つ印字量を列挙し、 各々の外部 anchor と global-flip foil を表 (登録簿) にする。 (b) foil は**入力 (原稿) を反転して** end-to-end で当てる — parse した変数を script 内で反転する foil は parse の取り違えを見ない。 (c) 例外 (traceback) で落ちたのは歯ではない (assertion で落ちること)。 (d) 同型の不変量 = 全体規格化 (kernel-level と action-level の因子 2)、 因子 i、 Levi-Civita の向き、 D = 4 − ε と 4 − 2ε の違い。 比と恒等式に不変な量は全部同じ扱い (全体規格化でも同型の事故が起きうる。 決着は物理観測量の直接計算で付ける)。 機械 backstop = ai-collaboration の [`scripts/check-sign-anchors.py`](../../ai-collaboration/scripts/check-sign-anchors.py) (登録簿の coverage / `--run` = foil の歯を end-to-end で / `--fleet-scan` = fleet のどの検査が変換を見分けるか / `--readers` = どの検査が原稿 file をそもそも開くか / `--deferrals` = 下の carrier 無し「規約差」 の ratchet)。 (e) 「原稿を開く検査は何本か」 は実行時に数える (`--readers` = audit hook)。 source を file 名で grep すると docstring・コメントの言及まで拾って過大になる (起源事例では grep の数が実行時の十倍以上)。

## <a id="negative-norm-pole-assignment"></a>高階微分の逆伝播関数で「どちらの極が負ノルムか」 を言う前に — 留数を直接出し、 正ノルムの向きを外部の錨で決め、 極は繰り込まれた係数で探す

**Pattern** (実測): 2 階と 4 階の項を持つ逆伝播関数 $K(q^2)=aq^2+bq^4$ (Euclid、 宇宙項は除く) の零点を、 教科書の部分分数 $1/(q^4+M^2q^2)=M^{-2}\,[1/q^2-1/(q^2+M^2)]$ に当てて「重い極が負ノルム」 と読む。 この分解は $a,b>0$ を前提にしているので、 全体に負号のある逆伝播関数に当てると 2 つの極の役を取り違える。 零点の位置・係数の比・Ward 恒等式は全体の符号に不変なので、 取り違えはそれらの検査を通る。

**Rule**:

1. **留数を直接出す**: 零点 $q^2=0$ と $q^2=-a/b$ での $1/K$ の留数は $1/a$ と $-1/a$。 必ず逆符号で、 **どちらが負ノルムかは 2 階の係数 $a$ の符号だけで決まる** (重い極が時間的になるのは $ab>0$ のとき)。 形状因子が運動量に依るときは、 留数を微分 ($1/K'$) と零点のまわりの周回積分の 2 通りで出して照合し、 2 つの零点のあいだに他の零点が無いことを偏角の原理で確かめる。
2. **正ノルムの向きを外部の錨で決める** — 前提にした scenario の符号を「正しい符号」 と置かない: (i) Euclid で $\Gamma_E\supset\frac12\int\phi K\phi$、 重み $e^{-\Gamma_E}$ なら、 Källén–Lehmann の $\rho\ge0$ から留数 $1/K'>0$ が正ノルム (正準なスカラーの Wick 像 $K=q^2+M^2$ と、 Pais–Uhlenbeck の負ノルムの重い極 $K'<0$ で向きを確かめる)。 (ii) tree の作用の符号は絶対量に結ぶ (Einstein–Hilbert なら、 宇宙項つきの作用の S⁴ の saddle が de Sitter のエントロピー $A/4G>0$ を与える符号)。 2 次形式の辞書 (曲率の 2 次の項が逆伝播関数の各成分に与える係数) も、 球面で曲率の符号を確かめた同じ code で導き直す。 (iii) loop で誘起した係数なら、 loop の全体の符号も絶対量に結ぶ (例: Weyl² 項の log の係数は、 どの unitary な自由場でも $-(c/2)$ × log で、 $c>0$ は Weyl anomaly の係数 = $\langle TT\rangle$ の規格化)。 全体反転の foil で、 留数の主張と (iii) の両方が落ちることを確かめる ([#absolute-sign-external-anchor](#absolute-sign-external-anchor))。
3. **極は繰り込まれた係数で探す**: 2 階の係数を同じ loop の log の項だけから取る読み (冪の発散の列を落とした読み) は物理の読みではない — 落とすには冪の列をちょうど打ち消す必要があり、 残る係数の符号も物理の符号とは限らない。 伝播関数に入るのは繰り込まれた (観測される) 係数で、 極の有無・位置・ノルムはそれを入れて判定する。 log の係数そのもの (正則化に依らない) には意味があり、 意味がないのは log の係数だけで極を論じること。
4. **cutoff の外の零点で判定しない**: 繰り込まれた係数を入れて零点が cutoff より上に出たら、 その位置は regulator の profile に依る = その有効作用は極の有無を決めない、 と書く。 cutoff より下の零点が出る条件 (2 階の係数を裸の項でどこまで打ち消したら出るか) を数で示す。

## <a id="closed-form-transcription-carries-its-metric"></a>検証 script の閉形式を数値 notebook に写すときは、 符号を「その閉形式の計量」 ごと写す — 確率の cross 項は $A_0^*A_1$ であって $A_0A_1$ ではない

**Pattern** (実測、 2 件が同じ図で同居): (1) spinor 縮約の閉形式を mostly-minus で確立した検証 script が docstring に「原稿は mostly-plus なので −1 倍」 と書いていたのに、 数値 notebook にはその値が符号を落として写された。 縮約 $(\bar u_3\gamma^\mu u_1)(\bar u_4\gamma_\mu u_2)\to4P_1\cdot P_2$ は 4-vector の内積なので、 signature を変えると符号が反転する (spinor の位相規約には依らない)。 一次の振幅の全体符号が反転し、 零次 (散乱なし) 項との干渉が constructive ↔ destructive で入れ替わった。 大きさの検査 ($|A_1|^2$、 零次と一次の交点、 符号反転の位置) は全部 PASS のままなので、 fleet は何も言わない。 (2) 原稿が「零次の共役を掛ける」 と書きながら位相だけ落として分母の $(1+i\cdots)$ を共役し忘れ、 notebook が `A0 A1 + c.c.` をそのまま継承した。 $|A_0+A_1|^2$ の cross 項は $A_0^*A_1+{\rm c.c.}$ で、 二つは $A_0$ が位相を持つ帯 (波束の広がり因子 $\sim1$) でだけ違うため、 まさにその帯にある符号反転の位置と回数が変わっていた。

**Rule**:

1. 閉形式を別の文書・notebook に写すときは、 **その閉形式の計量・規約を値と一緒に運ぶ** (docstring の「原稿は −1 倍」 は写す側が当てる義務)。 写した先では、 符号を運ぶ量 (零次との相対符号 = 干渉の向き) に外部 anchor を 1 本置く: 一次項 $=iM$ なら $S=1+iT$ の規約で 斥力 ⇔ $M<0$ (同符号電荷の vector 交換の非相対論極限 $M=-(2m)^2\tilde V$)、 吸収 ⇔ 光学定理の $\mathrm{Im}\,M>0$ — [`#absolute-sign-external-anchor`](#absolute-sign-external-anchor) の一次振幅版。
2. cross 項は $|A_0+A_1|^2-|A_0|^2-|A_1|^2$ を**別経路で数値評価して恒等式で assert** する (共役の取り違えは大きさの検査では出ない)。 図に $|A_0+A_1|^2$ 自体を 1 本足せば、 cross 項の符号が目で見える (足したことで (2) が露見した)。
3. t-channel propagator の幅 $m^2\to m^2-im\Gamma$ が作る虚部は s-channel の吸収ではない: その符号は光学定理の制約の外にあり、 物理の吸収振幅と逆向きにもなる。 toy の幅由来の干渉の符号を物理の主張に使わない (使うなら振幅を物理の位相 〔$(\rho+i)\sigma_{\rm tot}$ 型〕 に置換する)。

## <a id="checker-reads-what-the-text-states"></a>数値照合の script が、 本文と同じ量を同じ場所で読んでいるかを確かめる — 一致していても基準量か読む場所が違うことがある

**Pattern** (実測): 本文の数値と照合 script の出力は一致していて、 照合は PASS していた。 しかし (1) 本文が「ある波長のまわりの ±X」 と書いた帯域を、 script は別の波長で換算していた (帯域を周波数で求めて波長に直す換算は λ² に比例する = 波長が 2 倍違えば値は 4 倍違う)。 (2) 本文の「零点が A から B へ変わる」 は、 補正で非対称になったスペクトルの片側だけを読んだ値で、 反対側では逆向きに動いていた。 どちらも、 本文の文から独立に計算した別の目が見つけた (照合の PASS は「script と本文が同じ数字を言う」 ことしか言わない)。

**Rule**:

1. 換算を含む数値 (周波数 ↔ 波長、 強度 ↔ 振幅の減衰率、 幅の定義) は、 照合 script の換算に使った基準量 (どの波長・どの規約) を本文の文の基準量と 1 対 1 で確かめる。 script の入力に本文の文と違う名前の量があれば、 それが食い違いの候補。
2. 非対称になりうる量 (補正を入れたスペクトル、 片側の零点、 符号の変わる点) は両側で読み、 本文の値がどちらの側かを文に書く。 片側の値だけを書くなら、 反対側の値を記録に残す。
3. 照合 script を書いた人と別の目 (盲検・別の vendor) に、 **本文の文から**照合させる。 同じ script の再実行は同じ読み違いを繰り返す ([`#closed-form-transcription-carries-its-metric`](#closed-form-transcription-carries-its-metric) と同じ形)。
4. <a id="checker-shares-the-approximation"></a>照合 script が、 原稿の数を出したのと同じ計算の出力 (同じ probe の json) を読んでいると、 その計算の近似や規約の誤りごと PASS する。 近似の式で出した数 (定常の率・断熱の近似・雑音の置き方) は、 別の方法 (時間発展の直接の積分・規約の定義からの導き) で 1 回出し直し、 近似が成り立つかを決める parameter を記録に書く。 実測: 短いパルスで散乱する光子の数を、 定常の散乱率を強度の包絡で積分して数えていた。 パルスの帯域が線幅と同じ程度だと、 直接の積分の値は定常の式の √π n e^{n²} erfc(n) 倍 (n = γ√σ、 γ = Γ/2 は励起の振幅の減衰率、 強度の包絡 ∝ e^{−t²/σ}。 n = 1 で 0.76、 n → ∞ で 1) で、 照合も定常の式の値を読んで通っていた。 同じ照合は、 単位効率のヘテロダインの雑音 (複素振幅の分散 1 光子 = 直交成分ごとに 1/2) を半分に置いた値も通していた。

## <a id="printed-number-registry"></a>原稿が印字する数は全数を登録して pin する — 原稿の断片・印字の桁・記録した食い違い・誤った規約の対照

**Pattern** (実測): 長い期間に results の file から写した原稿の数を、 入力から計算し直して印字の桁で照合すると、 個々の照合 ([#checker-reads-what-the-text-states](#checker-reads-what-the-text-states)) が通っていても、 次の 5 つの型の食い違いが出た。

1. **二重丸め** — 記録に 3 桁で残した値 (…5) を、 さらに 2 桁に丸めて印字した。 元の値 (…48) を 2 桁に丸めると 1 小さい。 不確かさの括弧の最後の桁でも同じ形が出た。
2. **合成の構成の parameter を、 データの統計量として印字した** — 較正のための合成の構成を「データに合わせる」 ときに中心を目分量で置き、 その構成の parameter がデータの値として表と本文に入った。 データから計算すると数値がずれ、 一緒に印字した検出率もその構成の値だった。
3. **定性の label に計算の記録が無い** — 結果の表の型の名 (「一様」「1 点が支配」 の類) に判定の基準と計算が無く、 計算し直すと逆の型だった。
4. **下限を切り捨てで書いた** — 下限として印字した数を丸めれば 1 つ上になる。 下限なら保守側だが、 登録で「下限」 と宣言しないと照合が落ちる。 文の直しで下限を言う語を外したら、 その数は同じ値の他の箇所の桁に丸め直し、 登録の型も丸めに戻す (切り捨ては語に守られていただけ = 語を外すと、 同じ条件の違う丸めに見える。 実測)。
5. **観測値での率を、 粗い格子の内挿で出していた** — 偽警報の率を、 観測した分散を挟む 2 つの格子点の内挿で書き、 帯の 2 つの端を別々の手法の値から取っていた。 観測値に合わせた ensemble で直接回すと、 印字の旗と同じ手法での率は内挿の帯の上の端より大きかった。

**Rule**:

1. 原稿が印字する数を 1 件ずつ登録表に書く: (a) その数を含む原稿の source の断片 (test は断片がまだあるかを確かめる = 原稿で数を書き換えると test が落ち、 登録の見直しを強制する) (b) 印字の文字列 (c) 入力からの再計算 (d) その数を既に pin している test の名 (e) 状態 = 一致 / 外部の引用 (追跡している text cache の印字で照合) / 食い違い。
2. 照合は印字の桁で行う: 小数 d 桁の印字 p は |x − p| ≤ ½·10⁻ᵈ。 範囲「a–b」 は再計算の最小と最大で。 「≈」 と下限は、 許容と型を登録に書く。 既存の pin が印字の桁より緩いなら、 その旨を表に残す。
3. 食い違いは「印字に一致しない」 と「記録した再計算値に一致する」 の両方で pin する。 test は通り続け、 原稿が直された時点で断片の照合が落ちるので、 状態を一致に戻す。 原稿は直さない (直すかは著者が決める = [`manuscript-claim-ownership.md`](manuscript-claim-ownership.md))。
4. 対照 (foil) を置く: 近い規約の誤り (自由度を N−1 にする・非対称誤差の反復で χ² を出す・look-elsewhere を外す・別の手法の posterior で読む・peak の閾値を変える・BIC を AIC にする) で印字が出ないこと。 再計算を印字の 1 単位ずらすと一致しないこと (許容が印字より緩くない)。 食い違いの出所が分かったら、 その誤った経路が印字を再現することを「出所の対照」 として pin する。
5. 仕組みが空でないことを mutation で示す: 印字を変えた登録・断片を変えた登録・入力の cache を隠した状態が、 それぞれ不一致・断片なし・理由を名指した skip になること。
6. 印字は full precision の値から丸める。 丸めた中間の値 (results の file の桁) から丸め直さない。
7. データに合わせた合成の構成は、 その parameter をデータから code で計算し、 一致を assert する。 構成の parameter をデータの統計量として印字しない。
8. 表の定性の label には判定の基準を書き、 計算を記録に残す ([`writing-discipline.md#no-unshown-verification-claim`](writing-discipline.md#no-unshown-verification-claim) の表の版)。 型を分ける label (外れ値・ばらつき・2 群の類) なら、 基準の較正のしかた = [#classifier-claim-calibration](#classifier-claim-calibration)。
9. 生成器を同じ seed で回し直して一致するのは再現性の検査で、 生成器の正しさの検証ではない (正しさは独立実装か spot-check の仕事)。
10. 2 つ目の project で同じことをするときに、 登録・照合・対照の engine を層1 の道具にする ([#second-example-refine](#second-example-refine))。
11. 観測値での率 (偽警報・検出率) は、 観測値に合わせた ensemble で直接回して出し、 印字の旗と同じ手法で読む。 粗い格子の内挿は、 格子点の二項誤差と曲線の曲がりで偏る。 図の帯をその直接の計算から引いたら、 その計算の点を図に描いて凡例で名指す (格子の曲線が帯の外を通ると、 帯の出所が図から読めない)。
12. 別の worker や前の pass が書いた案の文を原稿に当てるときも、 案の数を当てる前に登録して照合する。 案は検証前の主張で、 実測では案の範囲の端が切り捨てで、 丸めると 1 つ上だった。

## <a id="classifier-claim-calibration"></a>「この統計量で型を分ける」 と書く前に、 観測に合わせた合成で混同行列を測る — 感度だけでは label の当たる率は分からない

**Pattern** (実測): 統計量の「型ごとの典型の形」 (外れ値 1 つ・広いばらつき・2 群でそれぞれ形が違う) を理由に、 その統計量で型を分けられると本文に書いていた。 観測と同じ誤差の並びと同じ分散に合わせた合成で測ると、 その統計量の分布は型の間でほとんど重なっていた。 別の部品 (1 点を抜くと分散の警告が消えるか) は本物の外れ値には敏感だったが、 外れ値の無いばらつきでも同じ反応がよく出た = 感度だけを見て「外れ値を見つける」 と書くと、 型を混ぜたときの「外れ値」 の label の多くは本物でない。

**Rule**:

1. **規則と合成の作り方を、 対象の統計量を計算する前に commit で固定する** — 判定の段・閾値の決め方・合成の家系・読み方 (何倍で「示された」 と言うか) を note の節に書いて commit し、 対象の統計量はその後に計算する。 後で気づいたことは別の節 (事後の注) に足す。 締めで、 固定した節を見出しで切り出し、 固定した commit の同じ範囲と 1 字も違わないことを code で確かめる。
2. **型ごとに純粋な家系を作り、 分散の統計量は観測値に厳密に合わせる** — 家系を混ぜると真の型が決まらず、 混同行列が読めない。 誤差の並びは観測のまま、 χ² のような分散の統計量は replica ごとに観測値と等しくする (平均で合わせない)。 分散の大きさが家系で違うと、 型でなく分散の大きさで「分けた」 ように見える。 各家系の構造を 1 つの振幅に持たせると、 重みつき平均からの残差の 2 乗和は振幅の 2 次式になるので、 2 次方程式の正の根で合わせられる (雑音だけで目標を超えた replica だけを引き直す)。
3. **閾値を決める replica と率を測る replica は別の乱数列にする** — 同じ列だと、 閾値のゆらぎがその列に合わさって偽警報が少なく見える。 seed は (case・家系・用途・番号) から作り、 並列の worker の数で結果が変わらないことを test で確かめる。
4. **報告は混同行列と、 label のうち本物の割合の両方** — 真の家系ごとに各 label の率 (二項の標準誤差つき) を出し、 家系を等しく混ぜたときに各 label のうち本物がどれだけかも書く。 感度 (本物を拾う率) だけを書かない。 等しく混ぜる割合は仮定で、 現実の型の頻度ではないと添える。
5. **観測した 1 件は、 規則の label のほかに家系ごとの密度の比で読む** — 観測した統計量の点での家系の密度の比 (尤度比) を出す。 「示された」 と言う強さ (例: 3 倍以上) は 1 で前もって決める。 label だけでは、 観測が判定の境界のどれだけ内側にいるかが落ちる。
6. **構造が分かっている case を陽性対照にする** — 期待する型を計算の前に宣言して当てる。 label が期待と合っても、 密度の比が小さければ「分けられる」 根拠にはならない。
7. **本文の主張は測った率に合わせて絞る** — 分けられなかった型の組は「この統計量では分けず、 別の部品 (分布の形を見る層・前もって宣言した群の検定など) が分ける」 と書く。 絞るかは著者が決める ([`manuscript-claim-ownership.md`](manuscript-claim-ownership.md))。 絞ると、 その統計量を文献の道具と対比した文 (「より狭い問いを立てる」 の類) が成り立たなくなることがある = 一緒に読み直す。

## <a id="flagged-formula-consumption"></a>付録に「この式は誤り」 の注記が残っているときは、 本文が消費しているかを機械で引き、 本文の数値の出所を辿る

**Pattern** (実測): 原稿の付録に、 以前の検算で付けた「この閉形式は近似の欠陥で誤り」 の注記が数件残っていた。 注記は「本文のある節がこの式を直接使う」「誤差は別の経路で計算するので影響しない」 と消費関係まで書いていたが、 原稿の再編 (分割・移設) の後では、 その節は式を使っておらず、 「影響しない理由」 に挙げた経路の式にも別の誤りの注記が付いていた。 本文の数値は実際には、 付録のどちらの式でもなく、 厳密な入力から別の検算 script が出していた。 一方で、 本文の著者判断待ちの注記 1 つが、 付録の誤った式から出る比を「本文に書ける一般の言明」 の候補に挙げていた (書けば誤りが本文に入る)。

**Rule**:

1. 注記が書く消費関係 (どの節が使う・何が影響しない) は、 書いた時点の原稿についての主張で、 再編で古くなる。 注記を信じず、 本文の全 `\ref` / `\eqref` の参照先と、 注記の付いた範囲の `\label` を機械で突き合わせる。 範囲は行番号でなく label で探し、 既知の参照 1 つを陽性対照にする。 式番号のほかに、 節の label への参照 (「出所 = 付録 X」) と、 本文の中の判断待ちの注記が誤った式の帰結を候補にしていないかを読む。
2. 本文が印字する数値ごとに、 どの script のどの入力から出たかを辿り、 誤った式を通っていないことを確かめる。 そのうえで独立な実装で数値を再現し、 誤った式を使った場合の値を foil として並べる (本文の値と食い違うことが出所の確認になる)。
3. 「誤り」 とされた式は、 数値の前に、 その形式が持つ厳密な一般の不等式と比べる (例: 推定の誤差の量が状態の標準偏差で上から抑えられる、 確率の総和が 1、 正定値性)。 不等式を破る式は parameter に依らず誤り。
4. 注記の「訂正形」 も検証前の主張として扱う。 「最低次で A に近づく」 とあれば、 どの小さな parameter がそれを支配するかを、 他を固定して 1 つずつ動かして確かめる (補正が注記の言う parameter でなく、 別の parameter の 1 次だった実測がある)。 厳密な恒等式が書けるなら、 近似の言明より先にそれを出す。
5. 全空間で定義した量が、 有限の窓・有限の切断では有限に見えても、 測度零の領域 (零運動量など) から対数で発散していることがある。 窓や切断を何桁か動かし、 予言した傾きと比べる。 注記の「厳密な値は有限」 は、 どの極限・どの部分空間についての言明かを書き分ける。

記録は注記ごとに「本文での消費 (0 件ならその旨) / 効く・効かない・既に直っている」 の表にし、 注記の文そのものの古い・不正確な箇所は、 原稿に当てる提案と分けて書く (原稿の式と主張は著者の裁定の後 = [`manuscript-claim-ownership.md`](manuscript-claim-ownership.md))。 浮動小数の比較点の選び方 = [`scientific-computing.md#reference-side-numerics`](scientific-computing.md#reference-side-numerics) の 9、 foil の識別力 = `ai-collaboration/conventions/physics-verification-cycle.md#foil-discrimination-measured`。

## <a id="implementation-claim-reachable-states"></a>実装の振る舞いについての文は、 実装が届く状態の集合で確かめる — 状態の全範囲で探すと、 作れない状態が反例に出る

**Pattern** (実測): 本文の「実装では、 この限界に当たるのは境界のごく近くだけ」 を、 状態の parameter の全範囲で走査すると、 境界から離れたところでも当たる状態が見つかった。 その状態は、 実装の操作 (入力の強さの上限・入る時の初期状態・状態を置き換える操作) では作れなかった。 文は実装の届く範囲では正しく、 状態空間の全体では偽。 同じ原稿で、 同じ操作の語が本文の式と実装で違う量に掛かっていて (どの量の変化率を与えるかが違う)、 結論の符号と上界はどちらでも成り立ち、 数の対応だけがある因子だけ違っていた。

**Rule**:

1. 実装についての文を検算するときは、 先に状態の集合を書く: 入る時の初期状態、 操作が変えられる量とその速さの上限、 状態を置き換える操作。 その集合の上で探す。 全範囲で反例が出たら、 それが届く状態かを確かめてから finding にする (届かないなら finding でなく、 2 の書き方の提案)。
2. 文の正しさが届く範囲に依るなら、 依る量 (操作の上限) を文に書くか、 実装の中の話だと限る語を付ける。
3. 同じ語 (操作・加速の類) を本文の式と実装の両方に使うときは、 2 つが同じ模型かを確かめる。 違うなら、 結論 (符号・上界・極限) が両方で成り立つかを分けて検算し、 数の対応 (換算の因子) を記録に残す。 どちらを正とするかは著者の裁定で、 検算の側では決めない。

## <a id="convention-difference-closure"></a>「規約差」 は写像を書いて閉じる — 語で済ませた符号の食い違いは unverified として carrier に載せる (2026-09-11)

**Pattern**: 外部の値と符号が逆に出た食い違いを「Euclidean と Minkowski の規約差」 と書いて閉じる。 起源事例 (2026-09) では、 同じ Wick の符号が 3 か月で 3 回「規約」 として処理された。 ① 教科書に符号が載っている量を自前の計算機構で出して逆符号になり、 設計記録に「規約差、 絶対符号は規約の追跡が要る」 と書いて、 大きさの一致だけを採った。 ② signature の違う二つの独立計算の全体 −1 を、 signature に共通な別の由来の −1 と同定した。 裏付けに使った検査 (特定の成分だけを比べる) は添字の signature を消すが、 作用密度の全体符号 (Wick の −1) は添字に依らないので消さない — 残った −1 は Wick の符号だった。 同定の第一原理導出は「整合が閉じているので実害なし」 として残された。 ③ その −1 が signature の注記なしに原稿の辞書として印字され、 付録の検算と「同符号」 と確認された。 どの記録にも carrier (担当・期日・写像が書かれるまで落ち続ける検査) は無く、 「規約」 の語が open の食い違いを closed に見せた。 ① の時点で写像 (Euclidean の有効作用密度 = −Lorentzian の有効作用密度) を 1 行書いていれば、 ② の数値一致と合わせて正しい辞書がその場で決まっていた。

**Rule**:

1. 符号・規格化の食い違いを規約で説明するなら、 **写像を式で書いて計算で閉じる**: 両側の定義 (e^{iS} か e^{−S} か、 計量の signature、 曲率の符号、 場の規格化、 i の配置、 ε の規約) を並べ、 片側の値を写像で送って他方と一致することを計算で示す。 語 (「規約差」 「convention tracking」 「up to conventions」) だけで閉じない。
2. 写像を計算するまでは **unverified** ([`physics-verification-cycle.md#claim-states`](../../ai-collaboration/conventions/physics-verification-cycle.md#claim-states)) のまま **carrier** に載せる = 担当と期日のある TODO、 decision ledger の未決項目、 または写像が書かれるまで落ち続ける検査。 設計記録の散文に書いた open は carrier ではない。 同じ行に carrier を書く習慣 (例: `carrier: <ledger 項目 / TODO / audit 名>`) にすれば grep で機械検査できる。
3. **Wick 回転は二つの効果を持つ**: (a) 座標・添字の signature (mostly-plus なら座標変換で、 相対係数は不変)、 (b) 作用密度の全体符号 (iS_M = −S_E)。 (a) だけを消す検査 (空間成分に限る比較、 parity-even スカラーの不変性、 δ と η で同じ辞書を使う解き比べ) は (b) を見ない。
4. 「二つの計算が違ったらまず規約差を疑う」 は初手の仮説として正しいが、 仮説は写像の計算で閉じるまで仮説のまま。 数値が「全成分でクリーンに全体 −1」 で合うことは写像の証明ではない (fit であって導出ではない)。
5. <a id="offshell-2pt-literature-comparison"></a>**文献の 2 点関数・自己エネルギーと比べるときは、 場の変数・場の数え方・量の種類・極の単位を揃えてから比べる**: off-shell の 1PI 2 点関数は場の変数で変わる (1 次の書き換えで係数が、 非線形の部分で真空のエネルギーに比例する接触項が変わる)。 揃えるもの = (a) 場の変数 (計量の揺らぎ h = g − η / 密度つきの逆計量 √g g^{μν} / 対称な vierbein) と、 その間の 1 次の写像 (trace の部分と g = η + 2ŝ の 2 を含めて、 文献の定義式から自分で導いて数値で確かめる) (b) 内線の場の数え方 (2 成分と 4 成分の spinor で全体 2 倍) (c) 文献の量が自己エネルギー (伝播関数の補正 D T D の T) か 1PI の Γ⁽²⁾ か (Γ⁽²⁾ = −T) (d) 極の単位 (D = 4 − 2ε と D = 2ω なら 1/ε = 1/(2 − ω)、 D = 4 − ε なら 2 倍違う)。 比べる前に、 文献の式の転記を、 その文献自身が印字した恒等式 (Ward・trace) が次元を一般にして恒等的に成り立つかで確かめる。 比べ方は、 両側を同じ共変な密度 (例: C² の 2 次の部分) に射影して係数を出すと、 構造 (残差) と規格化 (係数) が分かれる。 foil は因子を 1 つずつ外す (写像の 2 を落とす・数え方を変える・form factor を 1 つ変える) (実測: この手順で、 変数と数え方の違う文献の結果と全体符号まで一致した)。

**Check**: 設計記録・living note・原稿を「規約差 / convention tracking / up to … conventions / absolute sign / at the level of magnitude / not done here」 で grep し、 各 hit に写像の計算か carrier があるかを見る。 機械 = [`check-sign-anchors.py --deferrals`](../../ai-collaboration/scripts/check-sign-anchors.py) (carrier の無い新規 hit を finding にし、 既知の open は baseline に理由つきで載せて毎回表示する)。

## <a id="cross-check-appendix-shape"></a>cross-check 付録の形 — 教科書でなく論文の密度: 目的 → 規約 → 写像 → 入力 → 結果 → 表 → 射程 (2026-09-08)

**Pattern**: 検算の付録を書くと、 「一意な接続と関数があって」 型の前置き、 逐次代入の再掲 (「これを代入すると … で、 これは式 (N) の最初の数項」)、 結果に効かない量の注、 本文中の文献引用、 定義の教科書的説明が積もり、 散文が式の 2 倍になる (著者「死ぬほど冗長」、 645 → 387 語)。

**Shape**: (1) 目的と独立性 1 文 (何を再現するか、 何に依らないか) → (2) 規約 (signature、 符号 anchor) 2 文 → (3) 写像 (pole map) display 1 本 → (4) 入力 (係数の一般式) display 1 本、 短い一般式は inline → (5) sector ごとに「入力 → 係数の値」 display 1 本 → (6) 文献辞書 1 文 (換算定数のみ) → (7) 表 (項 / 係数 / 入力 / 文献) → (8) 「写像を通せば表の係数」 + 射程 1 文。 落とすもの = 逐次代入の再掲 (表が担う)、 本文中の文献引用 (表の列が担う)、 標準恒等式の陽な形 (名前だけ)、 結果に効かない規約 (γ₅ の定義など)。

**Symbol audit (同 pass)**: display に出る記号を列挙し、 各々に定義文があるか確認する。 「Laplace 型」 のような型の名前は定義の代わりにならない (著者「この記号が無定義では」)。 本稿の既存記号と衝突する文献記号は別字にするか肩付きで区別し、 その理由を ledger に残す。

**Display は 1 目的** (2026-09-09 追記): 定義 (記号・ノルム関係) と物理の恒等式を 1 つの display に並べない。定義は本文の 1 文に、display は恒等式と係数の値だけ (著者「これは定義がメインで残りは補足なの？」)。射程の but 書き (「matching の代替ではない」 等) が同段落や本文に既出なら付録で繰り返さない。裸の括弧参照「(Sec. X)」 は関係を動詞で言う (as shown in / as described in)。 記法をまたぐ候補列挙と参照先の保持検査には [bare-parenthetical-crossrefs](latex.md#bare-parenthetical-crossrefs) の手順を使う。

**Floor**: 定義・display・表・射程 1 文が残れば床。 そこから先は「何を読者に検算させないか」 の判断であって、 削減ではない。 家風の機械 backstop = [`scripts/check-display-math-style.py`](../scripts/check-display-math-style.py) (display 内の `\tfrac` と `\qquad` 並列)。

## <a id="composite-quantity-notation-migration"></a>合成量の記法を乗り換えたら前係数を自明極限で検算する — 「和」 系と「平均」 系の差は定数倍で潜る (2026-09-09)

**Pattern**: 2 つの幅・分散・重みから作る合成量には「和」 系と「平均」 系の 2 流儀がある (例: $\bar\sigma := (\sigma+\sigma')/2$ 〔平均〕 vs $\Sigma := \sigma+\sigma'$ 〔和〕、 $\tilde\sigma := [(\sigma^{-1}+\sigma'^{-1})/2]^{-1}$ 〔逆数の平均の逆数〕 vs $\sigma_\ast := (\sigma^{-1}+\sigma'^{-1})^{-1}$ 〔逆数の和の逆数〕)。 **記法を乗り換えるとき、 括弧の形だけ写して定義の差を吸収し忘れる**と、 前係数が定数倍ずれる。 指数部は合っているので読んでも気づかない。 起源事例 (2026-09): 先行の式の比 (平均系の幅どうし) を、 後の式が和系の幅どうしの比として同じ冪で写した。 平均系と和系は分子・分母で 2 倍ずつ違い、 **その 2 倍が同じ向きに効いて括弧の中で 4 倍**が落ちた。 誤りは既に印字された式に在り、 それを引いた式にも伝播していた。

**Check 1 (自明極限の 1 行検算 — これが決定打)**: 前係数は必ず「答えが自明になる配置」 を持つ。 規格化された状態の自己重なり = 1、 等幅、 同一点、 距離ゼロ、 $t=0$、 結合ゼロ。 **その 1 点を代入するだけで真偽が確定する** (起源事例では自己重なり = 1 のはずの配置で、 誤った係数は 1 から明らかに外れた値を返した)。 導出の再演より安く、 結論が二値。 前係数を書いた・写した・変えた **どの turn でも 1 行で回す**。

**Check 2 (正しい形は自然な不等式を満たすことが多い)**: 例: 2 つの幅の重なり係数は、 正しく書くと (幾何平均 / 算術平均) の冪になり、 相加相乗平均から $\le 1$、 等号は等幅のとき。 **合成量の比が既知の不等式・極限に載るか**を見ると、 定数倍のずれは形の不自然さとして表に出る (誤った形は等幅でも 1 にならない)。 載る形が見つかったら、 それを本文の言い方にも使う (「逆数の和系と和系の比」 より「幾何平均と算術平均の比」 の方が主張として明快だった)。

**Check 3 (同一文書内に正しい系統が同居しうる)**: 誤りが引用経由で入った場合、 **自分の文書の別の節には独立導出した正しい形が残っていることがある** (起源事例でも、 旧計算の節が正しい形を持っていた)。 記法の全出現を grep して並べ、 形が割れていないか見る。 「引用元がそう書いている」 は自分の文書内の不整合の言い訳にならない ([#new-symbol-convention-consistency](#new-symbol-convention-consistency) の姉妹)。

**Check 4 (引用の係数は写す前に導出する)**: 先行研究から係数を持ってくるときは、 **自分の規約で 1 回導出してから**写す。 起源事例では独立な 2 経路 (運動量空間と位置空間の積分) が一致し、 引用元との差が確定した。 導出コストは Gauss 積分 1 本で、 published error を継承するコストより遥かに安い。

<a id="relabel-quantity-substitute-definition"></a>**Check 5 (文の呼称だけを変えたときも同じ)**: 式も記号も変えず、 印字した数値が**どの量のもの**かを文で言い換えただけでも、 規格化はずれる。 慣習の前因子 (½ など) を含めて定義した parameter と、 演算子に直接掛かる係数は、 同じ変化に対して定数倍違う値を取る。 量の呼称を変えた turn では、 その数値を定義の式に代入し、 言い換えた後の量の値になっているかを 1 行で確かめる (実測)。 数値照合の script が言い換え前の量で PASS していても、 文の側は照合されていない ([#checker-reads-what-the-text-states](#checker-reads-what-the-text-states))。

**Downstream (誤りが published だったとき)**: 影響を「全体定数か、 力学変数 ($L$, $T$, 運動量移行) に依存するか」 で仕分ける。 全体定数なら物理的結論 (コヒーレンス長・位相・局在・保存則因子) は無傷なので erratum は規格化に限定できる。 ⚠️ ただし **abstract が「全体確率は X で決まる」 型の主張をしていればそこが直撃する**。 誤りの伝播先 (自分の他稿・引用した進行中原稿) を同じ turn で grep し、 carrier (TODO・erratum) に落とすまでを 1 単位にする。

**Downstream 2 (published の符号 1 つ、 縮約の途中で落ちる型)**: 盲検や読者の「符号が逆では」 は、 ① 規約に依らない別経路 (例: スピン和の重みを不変量で書き直す) と直接求積の両方で確かめ、 印字 / 訂正 / 直接の 3 列で数点並べる ② その記号が現れる式を source で全数列挙し、 形が変わる式と値だけ変わる式に分ける ③ erratum に書く式番号は preprint でなく誌面の PDF で照合する (版で番号がずれうる) ④ 訂正版が既知の極限を保つことを 1 行書く。 draft は carrier に紐づく file に置き、 共著者への連絡・投稿・preprint の差し替えを段取りとして列挙する (実測: ①〜④ で 1 session)。

<a id="erratum-vor-reading"></a>**③ の誌面の PDF の読み方**: (a) **誌面の PDF と校正刷りを取り違えない** — 校正刷りは 1 頁目の頭に「ARTICLE IN PRESS」 と雑誌の内部番号があり、 頁数も違う。 file 名や置き場所の名前 (「published」) で決めず、 1 頁目の頭と md5 で区別する (実測: 「published」 と名付けた file が校正刷りだった)。 (b) **番号だけでなく中身も読む** — 誌面の本文は著者の最後の source でなく校正で直した形になっていることがあり、 組版で、 著者のどの版の source にも無い誤植が入ることもある (実測)。 見つけた誤植は、 同じ erratum に入れるかを著者に聞く。 (c) **番号は頁の画像で読む** — 式の右端の番号は PyMuPDF の words に出ないことがあるので、 頁を段ごとに画像にして読む (PyMuPDF の `page.get_pixmap(dpi=170, clip=<段の矩形>)`。 様式用の `scripts/pdf-review-render.py` は数字の形の語を塗るので、 式の画像には使わない)。 text 層に番号が単独の行で入っている PDF なら、 その並びを source の `.aux` と比べるのは安い照合だが、 display の最後の行と同じ行に入った番号を落とす (実測) = 画像を正にする。 (d) **記号の飾りが「落ちている」 と書く前に、 寄って描画を見る** — p̸ のような斜線つきの記号の斜線は、 glyph でなく描画の path として入っていることがある。 その場合 text 層には出ず、 200 dpi 程度の画像では見えないことがある (実測: 誌面で斜線が落ちていると見えたが、 1200 dpi で寄ると在った)。 その記号の矩形に重なる path を PyMuPDF の `page.get_drawings()` で確かめるか、 その記号だけを 1200 dpi で描いてから判断する。

<a id="erratum-other-dimensions"></a>**一般の次元 d で書かれた式は、 d を変えて検算する**: 式が d を含むなら (Bessel 関数の次数 (d−1)/2、 (2π)^d、 角度の積分、 spinor の次元)、 d = 3 だけの検算では、 d に依る因子の誤りと d = 3 での偶然の一致を区別できない。 d = 1, 2 でも同じ検算を独立に組んで回す。 spinor は d ごとに Clifford 代数の表現を組み、 u = Cv^* の行列 C は γ 行列の積を探して決める (表現と規約で形が変わる = [`dirac-conventions.md#charge-conjugation`](dirac-conventions.md#charge-conjugation))。 d が偶数だと Bessel 関数の次数が半整数になって初等関数で書けるので、 閉形が有理式になり厳密に照合できる。 d = 3 に戻して、 元の検算と数値が全桁で一致することも確かめる (独立に組んだことの確かめ)。

<a id="erratum-full-ledger"></a>**review のたびに別の式で誤植が見つかる論文は、 表示式を全数の台帳にする**: 1 回の通読で直しても、 次の review で別の誤植が見つかる (実測)。 表示式を source から機械で列挙し (align の行ごとの番号、 `\nonumber` の行、 `.aux` の番号と照合)、 脚注の表示式も含めて 1 本ずつ verified / refuted / unverified と根拠 (script か導出) を付ける。 誤植が残りやすいのは、 括弧で並べて書いた別の形 (u の形と v の形・計量の違う付録の写し) と、 途中の行。 前者は等しくなる点 (同じ運動量・同じ点) の検算では見えないので、 一般の点で当てる。

<a id="erratum-downstream-sweep"></a>**Downstream 3 (他人の論文と、 同じ系統の論文)**: 誤りが published なら、 自分の稿の grep (上の Downstream) に加えて 2 つを確かめる。
(i) **引用している論文が誤った式を値として使っていないか** — INSPIRE で訂正する論文ごとに「この論文を引く論文」 を引いて和集合を取り、 訂正する論文どうしの相互引用と、 2 つ以上を引く本の重複を分けて数える (`ai-collaboration/scripts/inspire-bibliography.py citing <arXiv|recid>...`。 INSPIRE が保管する出版社の PDF の URL も出る)。 各本の PDF で引用の番号を全部拾い (範囲 [21–25] を展開、 `ai-collaboration/scripts/pdf-citation-contexts.py`)、 その周りで式を値として使っているかを読む。 INSPIRE に出ない手元の未発表の原稿は、 symlink を辿る grep (`command grep -R`) で引用の key を探す。 結果は「使っている式 / 影響の有無 / 根拠の頁」 の表にし、 読めなかった本は理由つきで未確認と書く (入手の経路 = [`web-tools.md#paper-pdf-routes`](web-tools.md#paper-pdf-routes))。
(ii) **同じ系統の他の論文に同じ形の誤りが独立に入っていないか** — 規格化の検査 (同じ状態の内積 = 1 など) を各論文の規約で当て、 検算の script には印字の形が別の値を出す foil を入れる ([`physics-verification-cycle.md#foil-negative-control`](../../ai-collaboration/conventions/physics-verification-cycle.md#foil-negative-control))。 古い論文の特別な場合 (パラメータが等しい場合など) の式は、 訂正後の式の同じ特別な場合と比べると、 訂正の独立な支えになる (Check 4 の姉妹)。 「その論文も同じ量を持っているはず」 は本文を読むまで仮説 (実測: 検査する量そのものが論文に無かった)。 他人の論文で誤りを見つけたら、 既定で非公開。

<a id="erratum-text"></a>**正誤表の本文の書き方**: 正誤表は短いほどよい。 読者は訂正を当てたいだけなので、 次の形にする (実測: 経緯や確かめた範囲を書いた初稿は、 著者の直しを重ねて下の形に縮んだ)。
- **最初の 1 文で結論への影響を言う** — 「下の訂正は論文の結論を変えない」 を冒頭に置くと、 全部の訂正にかかる。 特定の結果 (ある量が変わらない、 など) を理由に「だから結論は変わらない」 とつなぐと、 その結果だけが論文の結論のように読まれる。 値が変わる訂正があるなら「小さな変更」 のような評価は書かない。
- **訂正は「X should read Y」「should have a minus sign」「should be deleted」 の形だけで書く** — 「〜は誤っている (is in error)」 と宣言してから直し方を書かない。 正しい式を挙げない (挙げていない式は正しいと読まれる)。 誤りが生じた経緯 (どの縮約で符号が落ちたか) は正誤表に書かず、 共著者への便に書く。
- **主な誤りとその帰結 → それとは独立の誤り → typo の一覧、 の順** — 主な誤りの帰結 (直した量で成り立つ関係) は同じ段落に 1 文で置く。 独立の誤りは段落を分ければ足り、 「Independently of …」 の前置きは要らない。 帰結と独立の誤りを 1 つの一覧に混ぜると、 どれが主な誤りから来るのか読めない。
- **誤りと typo の線引き** — 結果・値・主張として誤った値が残るなら誤り。 途中の行・添字・二重に書いた因子のように、 結果は他の箇所で正しく書かれているなら typo。 線引きは著者が決める。 一覧の前置きも「直すべき」 の形 (should be corrected) にする (受け身の現在形 are corrected は、 正誤表がもう直したように読める)。 文脈で明らかな添字の取り違えを載せるかも著者に任せる。
- **同じ種類の typo は 1 項目にまとめる** — 和と演算子の添字の取り違えを 1 項目、 消す因子・余計な引数を 1 項目 (「… should be deleted; likewise …」)。 項目は「Eqs. (a) and (b), second line:」 のように式番号と行で始め、 2 つの式の行の構成が違うなら「Eq. (a), second line, and Eq. (b)」 と書き分ける。
- **新しい記号を持ち込まない** — 正しい右辺を書くのに論文に無い略記を作らず、 式を直接書く。 論文が一般の関数に同じ括弧の記法を使っているなら、 定義の文も要らない。
- **組版と渡し方** — revtex で 1 頁の正誤表を組むときの崩れ = [`latex.md#revtex-short-document`](latex.md#revtex-short-document)。 共著者にソースを渡すときは、 作業メモのコメント (著者の指示の引用・検算の記録) を外した写しにする = [`paper-submission.md#arxiv-package-tool`](paper-submission.md#arxiv-package-tool) の `arxiv-package.py build` がコメント除去と元の PDF との文字の一致の確かめを 1 回で行う (1 頁の正誤表でも通る、 実測)。

## <a id="figure-input-is-a-claim"></a>図に入れる量は本文が導いた量 — 「置き換えられるはず」 の外部値は新しい主張 (2026-09)

**Pattern**: 本文が模型 (特定の交換粒子・特定の結合) で導いた式を数値にする段で、 agent が「この block は一般の振幅に等しいから、 実測値 (現象論の parametrization) を入れた方が物理的」 と判断し、 図の入力だけを本文に無い量に差し替える。 図と caption はその外部値の語彙で書かれ、 本文のどの式もそれを導いていない。 著者から見れば「勝手に変えた量で、 今の計算に関係が無い」 = 図が論文を説明しなくなる。

**規則**:
1. 図・表の入力は、 本文の式に**その値を代入した**ものだけ。 本文が導いていない同定 (「この block は一般の振幅」) に基づく差し替えは、 式を 1 本足すのと同じ**新しい主張**で、 著者の項目ごとの裁定を経る (裁定は台帳に verbatim、 [manuscript-claim-ownership.md](manuscript-claim-ownership.md))。
2. 差し替えを提案するときは、 図を差し替える前に「本文の何行目がこの同定を導くか」 を示す。 導いていなければ図は本文の量で描き、 提案は別 note に置く。
3. caption は本文が計算した模型を名指す (交換粒子の質量・幅・結合)。 外部値の語彙で本文に無い物理を語らない。
4. 結合や parameter の**値**も同じ線: 本文が値を決めていないなら、 図に使った値は「仮置き」 か「著者が採った標準値 (出典つき)」 のどちらかを caption に明記し、 台帳にその裁定を残す。

**なぜ滑るか**: agent は「より正しい物理」 に寄せることを改善と感じるが、 論文の図の仕事は**論文が導いたことを見せる**ことで、 世界の真の値を見せることではない。 実測: 図の入力を外部値に替えた版は、 交点の位置も干渉の符号も本文の模型と違い、 著者の一言で全部差し戻しになった (差し戻しは台帳に 1 entry、 図・caption・検証 script を本文の量に戻す)。

関連: [#figures-bound-to-a-convention](#figures-bound-to-a-convention) (図は本文の source で描く)、 [#figure-irreproducible-taxonomy](#figure-irreproducible-taxonomy)。

## <a id="figures-bound-to-a-convention"></a>本文の規約に縛られる図は本文の source で描く — 外部画像は drift して誰も気づかない (2026-09)

**Pattern**: Feynman 図・運動量の流れ・添字の付き方・符号の向きは、本文のどこかの式が定義している。その図を外部 tool で作った画像 (PNG / PDF) として `\includegraphics` すると、**定義を直しても画像は直らない**。しかも caption は本文に合わせて更新されるので、**caption と画像が食い違ったまま何 pass も生き延びる**。機械 gate は掛からない (組版は通る、参照も解決する)。実際、盲検査読で初めて「図は運動量がある脚から入るが、 caption は別の脚」 が出た。

**Check**: 図が本文の規約に縛られているなら (= 図の中の記号・矢印が式の定義から決まるなら)、**その図は原稿の source で描く** (TikZ など)。同じ preamble の style を使えば、vertex rule の図と loop 図の線種・矢印が自動で揃う。画像のままにするのは、規約に縛られない図 (写真・数値プロット・外部から借りた図) だけ。

**食い違いを見つけたときに直すのは図であって caption ではない**: caption は本文の定義に縛られている側で、画像はその像。どちらが正かは「定義の式」 が決める。定義そのものが曖昧なら、そこを先に決める。

**対称性で答えが変わらない場合も直す**: 上の例では振幅が運動量の偶関数で、向きを逆に定義しても印字式は 1 文字も変わらなかった。それでも直すのは、**読者が図から規約を読み取るから**。「式が変わらない」 は「直さなくてよい」 ではない。

origin: 2026-09-12、長く改稿を重ねた原稿で、共著者が外部 tool で作った図 (PNG) の運動量の向きが付録の定義と逆だった。TikZ で描き直して解消。ついでに定義の等号 (振幅 = …) を図の中に置けるようになった (数式 display にはしない = 図は figure 環境 + caption のまま、という著者判断)。

## <a id="gate-spec-anchor-list"></a>投稿前 gate の spec に並べる anchor の最小 list (2026-09-11)

投稿前の readiness gate (別 session・別 vendor に渡す機械 gate + claim sweep) の spec は、 claim sweep の対象として少なくとも次の anchor を名指す (anchor 名は安定 — spec からそのまま引く):

- 主張の収支と強さ: [`headline-claim-budget-check`](#headline-claim-budget-check) (**係数の符号を含む**) / [`claim-strength-three-tests`](#claim-strength-three-tests) / [`uniqueness-claim-exhaustion`](#uniqueness-claim-exhaustion) / [`title-claim-check`](#title-claim-check)
- 符号と規約: [`absolute-sign-external-anchor`](#absolute-sign-external-anchor) / [`convention-difference-closure`](#convention-difference-closure) / [`euclidean-check-in-lorentzian-paper`](#euclidean-check-in-lorentzian-paper)
- 配置と語彙: [`statement-placement-check`](#statement-placement-check) / [`stale-framing-sweep`](#stale-framing-sweep) / [`abstract-geroch-compression`](#abstract-geroch-compression) / [`sentence-length-audit`](#sentence-length-audit) (機械 = [`check-paper-prose.py`](../scripts/check-paper-prose.py) の L・位置語 P・強い語 W) / 略語の 2 条件 = [`latex.md#abbreviation-first-occurrence`](latex.md#abbreviation-first-occurrence) (機械 = `check-abbreviations.py`)
- 記号と付録: [`new-symbol-convention-consistency`](#new-symbol-convention-consistency) / [`notation-continuity-across-sections`](#notation-continuity-across-sections) / [`cross-check-appendix-shape`](#cross-check-appendix-shape) / [`appendix-order-by-first-reference`](#appendix-order-by-first-reference) (機械 = `check-paper-prose.py` の A1–A3) / [`flagged-formula-consumption`](#flagged-formula-consumption) (付録に誤りの注記が残る原稿)
- 文献同定: HEP 系の `refs.bib` は [`inspire-bib-audit.py`](../scripts/inspire-bib-audit.py) で title・著者・journal・volume・初頁・DOI・eprint を照合する。ローカルの説明的 texkey が INSPIRE の canonical texkey でなくても、arXiv ID、次に DOI へ fallback して SKIP と誤認しない。引用が本文の主張を実際に支えるかは別の原文確認であり、metadata PASS で代替しない。 bib でない業績リスト (応募書類・CV の論文欄、 docx や text) は [`check-doi-list.py`](../scripts/check-doi-list.py) で DOI ごとに Crossref の書誌を出し、 記載の行と DOI ごとに並べて読む (著者名の綴り・年・巻の違いを拾う。 突き合わせは人)。

符号を持つ印字量の登録簿がある repo では、 gate record に `check-sign-anchors.py --run --deferrals` の結果 (fleet を変えた後なら `--fleet-scan` の表も) を載せる。 gate の worker には「規約文書は検算対象」 ([#absolute-sign-external-anchor](#absolute-sign-external-anchor) の Rule 4) を spec で明示する。 起源 = 2026-09 の gate spec が `headline-claim-budget-check` を含み、 中心主張の検算を worker 自身にさせたことで全体符号の誤りが出た (= 偶然だった手順を標準にする)。

## <a id="final-pass-open-items"></a>最終 pass の未手当は 1 表に畳み、 著者が 1 件ずつ決める (2026-09-11)

投稿前の最終 pass では、 機械 gate の残り (readiness record の open items) と盲検 referee の findings (ledger の refuted / unverified を含む) を **1 つの表**に畳む。

- 列は 出典 / 場所 / 内容 / 見立て / 決定。 **AI の見立てと著者の決定を別の列に**置き、 見立てで決定を埋めない。
- 同じ問題を gate と referee が別の言葉で指摘していたら 1 行に畳み、 出典に両方を書く。 閉じたものは「済み」 節へ移し、 どの commit / 決定で閉じたかを書く。
- 著者は 1 件ずつ決める。 AI は表を出したら、 上から順に 1 件ずつ選択肢と見立てを示して聞く (勝手に決めない)。
- 途中で届いた別 worker の結果 (再発防止の実装・hoist など) も、 同じ表の行として足す。 受領側の汚染 grep の結果は「済み」 節に 1 行で残す。

## <a id="distribution-shape-claim"></a>分布形の主張 (べき乗則 / 折れ点 / カットオフ) は 3 点セットで支える (2026-09-12)

「この量はべき乗則に従う」「分布に折れ点がある」 型の主張は、 経験分布を 1 つのモデルで説明できたことでは支えられない。 **同じ枠組みで比べた対立モデル・偽陽性率の較正・適合度**の 3 点が揃って初めて査読で残る。

1. **対立モデルとの尤度比較** — 単一べき / 折れべき / べき × 指数カットオフ を最低限、 加えて**べきでない分布** (対数正規・Weibull・混合指数) を同じ標本・同じ台で最尤推定し、 情報量規準で比べる。 入れ子でない比較は Vuong 検定を併記する。 「べきの枠内での勝者」 だけを示すと、 分布形の主張ではなく model family の内部順位の主張になる
2. **偽陽性率と検出力の較正** — 対立モデル (= 折れの無い真値) から同じ n の標本を生成し、 「折れあり」 が選ばれる割合を数える。 論文で使う判定閾値は**この表から決める** (慣用の ΔBIC ≥ 6 / 10 を借りてこない)。 併せて真値ありの検出力も出す。 これが無いと「n が足りなくて決着しない」 と「構造が無い」 を区別できない
3. **適合度** — 勝者モデルの KS 距離をパラメトリック・ブートストラップの p 値で評価する。 全モデルが棄却される cell は「勝者」 を報告しない

⚠️ **CCDF (累積分布) を log-log 平面で最小二乗して情報量規準を回すのは、 証拠を 1〜2 桁過大に評価する** — CCDF の点は同じ標本を共有していて残差が独立でないため。 実測 1 例: 同じデータで RSS ベースでは「極めて有意」 だった ΔBIC が、 離散標本の直接尤度では決着しない大きさになった。 探索・可視化には CCDF 回帰でよいが、 **主張の根拠は生標本の尤度**に置き換える。

- 折れ点の探索は縮退に注意する。 候補点の左右それぞれに **標本数と「異なる値の数」 の両方**の下限を課さないと、 同値が縦積みになった端点で見かけの完全一致が起き、 病的な最良適合が出る (勾配が負になる等、 分布として不正な解が「勝つ」)
- 有限窓 (月・年で切る) は長い側を系統的に落とす。 打ち切り尤度で扱うか、 窓をまたぐ全長で数えるかを決め、 他方を感度解析に回す

## <a id="derived-claim-vs-source-caveats"></a>自著から派生した文書 (申請書・講演・press) は、原論文の仮定節・脚注・future work を越えて強めない (2026-09-12)

論文が出た後、その結果は申請書・講演・解説・press release へ**言い換えられて**流れる。言い換えの過程で
主張は必ず強くなる (紙幅が減り、断定の方が読みやすいため)。ところが**原論文は公開されていて、読み手は
それを開ける** — つまり派生文書の過剰主張に対する**最強の反証者は自分の論文**になる。

**検査 (派生文書を書き終えた時点で 1 回)**: 派生文書が自著 [X] を根拠に主張している文を列挙し、[X] の
本文で対応箇所を開いて 3 つ照合する。

1. **仮定節** — [X] がその結果を出すために置いた仮定は、派生文書が語っている系で成り立つか。
   典型的な破れ方は「[X] は A ≃ B の領域で導いた式を、A ≪ B の系に適用して結論を書く」。
2. **脚注・注記** — [X] が「ただしこの場合は結論が変わりうる」と書いていないか。**脚注は査読で最も
   よく効いた留保が沈む場所**なので、本文の grep では出てこない。
3. **future work / 結語** — [X] が「今後の課題」としたものを、派生文書が「本研究で決着する」と書いて
   いないか。逆に [X] が「〜の妥当性を確立した」と結論したものを、派生文書が「〜の限界を確定する」と
   向きを裏返していないか (= 同じ結果の positive/negative の言い換えは、読み比べると温度差として出る)。

**実例の形 (2026-09、盲検模擬審査で観測)**: 派生文書が「自著 [X] の結果と先行研究の予言の食い違いを
決着させる」を中心に据えたが、[X] の**脚注**は、その結果が仮定 P の下のものであり、当の系では P が破れる
ので結論は必ずしも従わない、と留保し、結語も同じ系を「今後の課題」に送っていた。= **派生文書が主張した
「矛盾」は原論文の適用範囲外への外挿**で、専門が近い読み手が [X] を開けば 1 分で崩れる。**留保は脚注と
結語にあり、本文の grep では出てこない**のがこの型の要点。

**書き直しの型**: 「[X] は仮定 P の下で結果 R を得た。本研究が扱う系では P が破れる。P を外した解析を
行い、R がどう変わるかを決める」= **仮定を明示して差分を主張する形**にすると、原論文と整合したまま挑戦性
が立つ (しかも「自分の結果の適用限界を自分で把握している」という信号になる)。

- 隣接: [#scope-vs-epistemic-state](#scope-vs-epistemic-state) (論文の計算 vs 著者の認識状態) /
  [#assumption-dependent-claim-framing](#assumption-dependent-claim-framing) (未証明の仮定に依存する主張の
  3 層勾配) / [#claim-strength-three-tests](#claim-strength-three-tests)。
- 科研費調書での現れ方と、分野の「欠落」主張の姉妹規律 =
  [kakenhi-proposal.md#mock-review-and-claims](kakenhi-proposal.md#mock-review-and-claims) /
  [kakenhi-proposal.md#absence-claim-adjacent-field](kakenhi-proposal.md#absence-claim-adjacent-field)。

## <a id="novelty-calibrated-to-venue"></a>新規性は venue の型で測る — AI の評価は安全側に倒れる (2026-09-12)

読み手側から「何が新しくて、 面白くて、 重要なのか」 を量る 3 問 (正しさの検査の後、 低/中/高 → 媒体の重さ) = [manuscript-value-triage.md](manuscript-value-triage.md)。

「新規性が足りるか」 の答えは投稿先の型 (原著論文 / 短報 / 資料・調査ノート / レター) で変わる。 **測る物差しを先に固定しないと、 評価は必ず辛い方に倒れる**。

- AI に新規性を評価させると、 明示しない限り**原著論文の物差し**を当てる傾向がある。 短報や資料区分に出す原稿がそれで「弱い」 と判定されても、 判定が変わったのは物差しであって原稿ではない
- 辛め評価は否定材料でなく**次段 (フルペーパー化) の課題リスト**として回収する。 同じ指摘が「今の投稿では範囲限定で守れる / 次の版では実装が要る」 の 2 つに仕分けられる
- 逆向きも同じくらい危ない。 短報で通った枠組みをそのまま国際誌に出すと、 **その分野の合格ラインの型** (統計手続きの正しさ / データの新規性 / 解釈の妥当性 / 先行研究への正対) で落ちる。 型は分野ごとに違うので、 対象誌の最近号を数本読んで言語化してから判断する
- **先行研究の網羅は物差しと一緒に変わる**。 国内誌の短報では触れなくてよかった系統 (同じ量を別手法で扱う海外の学派) が、 国際誌では最初の査読で聞かれる。 venue を上げる決定をした turn で、 文献調査をやり直す WP を立てる

## <a id="invariant-structure-before-asymmetry-claim"></a>「X だけが運動項を持つ / X は補助場」 と言う前に、 実際の背景まわりの 2 次形式を書く — 微分の所在は部分積分で動き、 閉じた形の特異点は展開の特異点ではない (2026-09-14)

第一次形式 (p q̇ − H 型: 1 階の混合項 + 代数項) では、 混合項の微分はどちらの場にも置ける。 「e には微分が無い」「ω が微分を持つ」 は
書き方であって主張ではない。 **不変なのは 2 次形式 (Hessian) の微分次数構造** — 対角に (∂X)² があるか、 非対角が 1 階の混合か、 代数項か。

- **どの場を先に消しても解集合と経路積分は同じ** (差は超局所な Jacobian、 dim reg では消える)。 違うのは中間の有効作用の**局所形**。
  対角ブロックが 0 の場は Lagrange 乗数で、 消すと δ 汎関数 (= 拘束) が出る。 これは特異ではない — 「無限に硬い運動項」 と同じもの。
- **閉じた形の消去が背景で発散しても、 同じ点のまわりの摂動展開は正則でありうる** (例: 1/Λ を含む純接続形式の作用は Λ → 0 で発散するが、
  平坦背景の 2 次形式は δ 汎関数として正則)。 「特異」 と言う前に、 その背景で 2 次形式を書いて確かめる。
- **手順 (主張を書く前に 1 回)**: ① 背景を固定 ② 2 次形式のブロックを微分次数つきで表にする ③ 部分積分で消える主張を落とす
  ④ 消去の順序を入れ替えて同じ自由度が出ることを 1 行で確認 ⑤ その上で「固有の運動項」「補助場」 の文を書く。
- **実例の型 (2026-09、 講演準備の問答)**: 4 往復かかった。 ①「e の微分が作用に無い」 (部分積分で崩れる) → ②「e を消すのは平坦背景で特異」
  (閉じた形の 1/Λ から。 実際は Lagrange 乗数) → ③ 不変な文「tree の 2 次形式に (∂e)² も (∂ω)² も無く、 あるのは 1 階の混合と代数項。
  どちらを消しても同じ自由度。 ループがその 2 次形式に固有の運動項を書き足す」。 最初に ③ の 2 次形式を書いていれば 1 往復。
- 隣接: [#headline-claim-budget-check](#headline-claim-budget-check) (中心主張を模型の形式に依らない収支で検算) /
  [#convention-difference-closure](#convention-difference-closure) (語で済ませた差を写像で閉じる)。

## <a id="symbol-collision-sweep"></a>記号の衝突の走査 — 同じ文字が 2 つの量 / 分野の標準記号との衝突 / 添字順の規約 (2026-09)

「別物には別の名前を」。 査読の巡は記号の**呼び名**を見るが**文字**の衝突はまず見ない (実測)。 投稿前に 1 回、 読み手側で走査する。

衝突の 3 型:
- **(i) 原稿の中**: 1 文字が 2 つの量 (Mandelstam の s と Bloch 成分の s / helicity 差の c と不等式の分母の c / witness の値 W と
  演算子 W / Pauli の σ と特異値の σ と断面積の σ と統計の σ)。 三つ組の文字が揃っていない (Bloch 成分を r, s, z と書く)。
- **(ii) 分野の標準との衝突**: 原稿が式を借りてくる分野の標準記号 (PDG の中性メソン混合は x = Δm/Γ、 y = ΔΓ/2Γ。 隣の分野の
  標準比 R_ll と小文字 r。 核子の A_ij と重陽子のテンソル解析能 A_ij)。 その分野の読者は自分の意味で読む。
- **(iii) 添字順・軸名の規約**: 節ごとに「前がビーム / 前が標的 / 前が qubit」 が違う、 軸名が (S, N, L) と (x, y, z) で辞書の
  1 文が無い。

手順: [`scripts/tex-rename-symbols.py scan`](../scripts/tex-rename-symbols.py) で standalone な 1 文字を列挙 → 各文字の意味を
数える → **借りている分野の標準に揃える**提案 (PDG の規約を第一に) → 提案する文字が原稿で未使用かを `grep` で確かめてから出す
(χ² の χ、 相対 CP 偶奇の η、 ξ_a の ξ、 レプトン方向の n̂ は使用済み、 のように) → 採否は著者。 改名の実施は
[latex.md#symbol-rename](latex.md#symbol-rename)。 読み手の note には「見てほしい点」 の 1 項として衝突の list を置く
([manuscript-value-triage.md](manuscript-value-triage.md))。

## <a id="induced-vs-bare-same-variables"></a>「ループが bare の係数 X を補正する」 と書く前に、 誘導項と bare 項を同じ変数に直す — 一階形式の項を二階形式の項と同一視できるのは接続を消した枝だけ (2026-09-29)

bare 作用が一階形式 (vierbein + 独立な接続) で、 誘導作用が二階形式 (metric の Levi-Civita 曲率 + contorsion) で書かれている時、 「誘導された R 項が bare の Planck 質量を補正する」 は**そのままでは 2 つの項を等置していない**。 bare の一階の項は (g, K) 変数に直すと R(g) と捩率² の固定した組合せの和で、 誘導された R(g) 項はその**前半だけ**を rescale する。 後半 (捩率²) は bare の係数のまま残る。 「補正する」 が文字どおり正しいのは K = 0 (接続 = Levi-Civita、 = tree で接続を消した枝) のときで、 原稿はたいてい序論でその同一視を明示し (「接続を消せば Einstein–Hilbert になる」)、 結果の節で暗黙に引き継ぐ。

**検査 (結果の節を書く時に 1 回)**: ① bare 項と誘導項を同じ変数 (metric + contorsion、 または vierbein + 接続) に直す ② 「補正される」 と言う係数がどの単項式の係数かを名指す (「R(g) の係数」 か 「一階の項全体の係数」 か) ③ 残る差 (捩率² の bare 係数と誘導係数のずれ) をどの帳簿に載せるか決め、 **同じ節の中で帳簿を混ぜない** (R 項は 「一階の項の係数が動いた」 と言い、 捩率² 項は 「一階の項の係数 (bare) の固定組合せ」 と言うのは混在)。 ④ 「invisible to the correlator we compute」 型の免責で覆えるかを確かめる: 捩率² は揺らぎの 2 次なので接続側の 2 点関数に tree で見える = 免責の外。

**なぜ**: 物理 (metric sector の Newton 定数が動く) は正しいのに、 どの係数が動いたかの文が変数の混在で曖昧になり、 「Planck 質量」 が R(g) の係数か一階の項の係数かで読者ごとに割れる。 定義で答える型 ([#dissolve-by-definition](#dissolve-by-definition)) の一例。

起源 (2026-09-29): 著者の問い 「この文は背景の接続 = Levi-Civita を暗黙に仮定していないか」 に対する読み。 背景そのものは explicit に torsion-free を選んでいて仮定漏れは無かったが、 「補正する」 の文だけが一階 = 二階の同一視に依っていた (実測)。 隣接: [#invariant-structure-before-asymmetry-claim](#invariant-structure-before-asymmetry-claim) (2 次形式を書いてから 「固有の運動項」 を言う) / [#headline-claim-budget-check](#headline-claim-budget-check)。

## <a id="novelty-from-variables-or-identities"></a>新規性の論拠に「変数の取り方」 と「恒等式が成り立つ」 を使わない — 既知の汎関数の変分は連鎖律で決まり、 不変な汎関数は恒等式を恒等的に満たす (2026-10)

**型 1 (変数)**: 変数 Y で書いた一ループの汎関数 Γ[Y] が既に知られていて、 こちらは別の変数 X での 2 点関数を計算した、 という設定で「相手の変数には X が無い」「相手は X を量子化しない、 こちらは量子化する」「X の一部の成分は相手の計算に現れない」 を新規性の論拠にする。
その一ループに X の内線が無ければ、 X を量子場と呼ぶかどうかは行列式を変えない。 こちらの量は Γ[Y(X)] の X についての 2 階変分で、 連鎖律 Γ_{,ij} = Y^A_{,i} Γ_{,AB} Y^B_{,j} + Γ_{,A} Y^A_{,ij} で決まる (第 2 項 = off-shell の接触項・tadpole)。
相手の変数に X の一部の成分が無くても、 その成分は Y(X) を通して入っている。 合成例: O(N) 模型の有効ポテンシャルが不変量 ρ = φ_aφ_a の関数 V(ρ) として知られていれば、 成分の 2 点関数は ∂²V/∂φ_a∂φ_b = 2δ_ab V'(ρ) + 4φ_aφ_b V''(ρ) で決まり、 ρ に現れない角度の方向 (Goldstone の方向) も第 1 項を通して入る。 読み手は数行でこれを示せる。

**型 2 (恒等式)**: 「Ward–Takahashi 恒等式を確かめた」 を、 相手の有効作用の計算より量子的な中身がある証拠にする。
不変性から導いた WT 恒等式は、 係数が何であれ、 不変な汎関数の変分で恒等的に成り立つ (機械で示せる: 共変な汎関数の係数を乱数にしても、 その 2 点関数と混合 2 点関数で恒等式の残差は 0)。
確かめて分かるのは図の計算 (頂点・正則化・図どうしの相対規格化) の整合で、 汎関数に無い情報ではない。 恒等式を破るのは anomaly だけで、 その理論にその対称性の anomaly が無ければ、 恒等式が成り立つことは係数について何も言わない。

**検査 (新規性の文を書く前に 1 回)**:
1. こちらの量を、 既知の汎関数の変数の取り替えと変分で書けるか (その loop の内線にこちらの場があるか) を問う。 書けるなら、 新しいのは「その明示的な評価・整理・その模型での読み」 で、 「新しい一ループの情報」 ではない。
2. 新規性の文は事実だけで書く = こちらが計算した対象 (どの理論で・どの成分を・どの恒等式を確かめたか) と、 相手が計算したもの (本文で読んだ範囲)。 「別の対象」「相手に無い情報」 とは書かない。
3. 否定の文 (「その量は先行研究に無い」) は、 挙げた文献を 1 本ずつ本文で読んでから書く ([#three-phase-structure](#three-phase-structure) の cite の束縛検査)。 有料・電子版以前で読めないなら本人に取得を頼む。 裏の取れない文を弱めて済ませない (束ねた文献の 1 本が別の量だけを計算していると、 弱めた動詞のほうが誤りになる。 実測)。
4. <a id="open-question-read-footnotes"></a>引いた論文が「未解決」 と書いた問いを、 こちらが「解いた」「説明した」 と書く前に、 その論文の脚注と結びの段を読む。 原因の候補がそこに書いてあれば、 こちらの貢献は解決でなく、 その候補の確認と定量になる = 要旨・序論の動詞もそう書く (実測: 引用元の脚注が原因の候補を名指していたのに、 要旨が「残された未解決の因子」 と書き、 盲検の referee に新規性の書き過ぎとして指摘された)。

返答書での使い方 (聞かれていない関係を認めて弱めない・問われたら導出の節を指す) = [`rebuttal-letter.md#reconsideration-reply`](rebuttal-letter.md#reconsideration-reply)。 隣接: [#invariant-structure-before-asymmetry-claim](#invariant-structure-before-asymmetry-claim) / [#induced-vs-bare-same-variables](#induced-vs-bare-same-variables) / [#absolute-sign-external-anchor](#absolute-sign-external-anchor) (恒等式の全 PASS が見ないもの、 という同じ型)。

## <a id="post-formula-generalization-traps"></a>式の直後の散文が式より広く言う — 解説・教科書の文で盲検が繰り返し拾った 6 つの型 (2026-10)

式そのものは正しく、 その直後に書いた「だから〜」 の一文が式の成立範囲を超えている、 という finding が解説文の盲検で繰り返し出る (実測: 初回の盲検で複数件、 訂正版の突合では訂正で足した文からも同じ型が出た)。 式を検算しても文は検算されない。 型:

1. **条件つきの単調性**: 「係数を変えると縞は薄くなる」 型。 式が比 (分子 / 分母) なら、 分母の偏りで単調性が逆転する領域がある。 最大・最小の条件 (微分 = 0) を出してから、 単調になる変数の範囲を書く。
2. **「単峰」 で位相を縛ったつもり**: 波束・分布の重なりを「山が一つなら遅延に単調」 と書く型。 強度の形は位相の形を縛らない (周期的な位相変調で重なりが戻る)。 形と位相の両方を条件に書くか、 重なりそのものを変数にして言う。
3. **実効係数の帰属**: 損失を入力側にまとめた実効的な状態の係数 (「一個の成分 55\%」 型) を、 源の性能として書く型。 「測った結果を説明する状態」 と「源が出した状態」 を分け、 係数に何の損失が入っているかを 1 文添える。
4. **条件つき確率の和**: 部分集合ごとの確率 $(1\pm\cos\phi)/2$ を「足すと一定」 と書く型。 足すのは各集合の重みを掛けた同時確率で、 条件つき確率の単純和は 1 になる。 「結果ごとの状態を足すと元に戻る」 も同じく重みつき (混合) の等式。
5. **生の行列の等式と、 位相を取り直した後の同等性**: 「境界面の関係を当てると第 1 章の行列そのものになる」 型。 得られるのは出口の入れ替え (X·H) か出口の符号 (Z·H) で、 H そのものではない。 「番号を付け替えれば / 位相の基準を取り直せば同じ」 と操作を書く。
6. **演算子の作用と確率**: 「$E$ は $|n\rangle$ に $(1-\eta)^n$ を返す」 型。 固有ベクトル・固有値・Born 則の確率を分けて書く (「$|n\rangle$ は固有ベクトルで固有値が確率」)。

付随して出る帰属の型: 複数の方法を持つ論文の 1 つの図だけを引くときは、 その図の光源・装置を論文で確かめる (論文全体を単一の方法で要約しない) / 総説に載っていない後年の数値を総説に帰属させない / 装置の実装の数 (検出器が 2 個で区画が 8) を混同しない。 検査の手 = 式の直後の文ごとに「この文が真になる条件は式のどの変数の範囲か」 を 1 行で書き、 条件が書けない文は限定を足す。 盲検に出すときは、 新しく足した式・数値だけでなく**足した文**も再導出の対象に挙げる (訂正は新しい一般化を持ち込む = `ai-collaboration/conventions/cold-eyes-isolation.md#revised-target-second-round`)。

## <a id="conclusion-rule-against-own-cases"></a>結論の規則は、 本文の表の全部の行に当てて確かめる — 範囲が広がった規則は、 列挙でなく理由で書き直す

**Pattern**: 結論・処方の節が規則を一般形で書く (「どれかの検査が鳴ったら、 その値を出さない」)。 一方で本文は事例ごとに違う処置を書いている (ある型には「幅を広げて出す」、 別の型には「出さない」)。 設計の段階では「どれか」 が一部の検査 (構造を読む検査) を指していたのに、 結論を書くときに全部の検査へ広がった、 という形が多い。 書き手には規則と事例の両方が一貫して見えるので、 通読では素通りしやすい (実測: 規則を本文の表の行に 1 つずつ当てた時点で初めて、 規則と本文の処置の食い違いが分かった)。

**Check**:
1. 結論・処方・要約に書いた規則を 1 本ずつ取り出す (「〜なら〜しない」「〜のときだけ〜する」)。
2. 本文の表・事例の全部の行に規則を当て、 規則が出す処置と、 本文がその行に書いた処置を並べる。
3. 食い違う行があれば、 どちらを直すかを決める。 設計の記録と、 著者が承認済みの文 (概要など) の側に合わせるのが普通で、 結論の一般化のほうが後から広がったものであることが多い。

**Fix**: 範囲を、 規則が掛かる検査の名前の列挙で狭めない (「A か B が鳴ったら」)。 列挙は「なぜちょうどその検査なのか」 と突かれ、 答えるには結局理由が要る。 理由そのもの (その型でその処置が正しくなる訳) を規則の芯にし、 検査はその理由を読む道具として出す。 合成例: 「どれかの警報が鳴ったら運転を止める」 と書いた手順書の本文が、 ある警報には「速度を落とす」 と書いているなら、 規則を警報の名前で絞るより「速度で直る原因なら速度を落とし、 速度で直らない原因なら止める」 と理由で書く。 型ごとの処置が規則から導けるようになり、 新しい事例にも当てられる。 理由の形にしても、 道具の検出力の範囲 (見逃す率) は規則と同じ所に書く。

## <a id="registered-predictions-check"></a>「予言」 と呼ぶものを 1 件ずつ検査する — 既に成り立っている・外れようがない・探索であるものは予言と呼ばない

**Pattern**: 結論や展望の節が「N 件の予言」 を並べて反証可能性を示すが、 1 件ずつ見ると予言になっていない。 この種の節は反証可能性の防御として書かれるので、 referee は 1 件ずつ確かめる。 1 件でも崩れると、 論文の「登録した」「事前に宣言した」 という語全体の信用が落ちる。

**Check** (各項目に):
1. **登録の時点で結果が未知か** — 既に成り立っている条件 (「閾値の下にとどまる」 と書いた量が、 いまも閾値の下にある) には中身が無い。 計算済みの結果の再掲も予言ではない (同じ入力なら外れようがない)。
2. **外れる観測が書いてあるか** — 「どちらに解消しても追跡できる」 型は外れない。 外れる条件を 1 文で書けないなら、 予言でなく追跡の約束と呼ぶ。
3. **論文自身の主張が、 外れを外れと数えさせるか** — 対象の性質が時間とともに変わりうると論文が書いているなら、 将来の性質を当てる予言は、 外れても「新しい状態」 と言えてしまう。 その予言は道具の試験でなく、 物理 (あるいは対象の側) への賭けになる。
4. **探索と予言を分ける** — 「例が見つかるまで探し続ける」 は探索で、 予言ではない。 探索の結果を道具の価値の試金石と書くなら、 その基準が論文の今の役割の定義と合うかを確かめる (論文が自分の役割として捨てた基準を、 結論で戻さない)。
5. **他の入力と混ざるか** — 次の更新が複数の入力を同時に動かすなら、 「X が入ったら Y になる」 は、 X だけを足した計算の意味 (外れようがない) か、 更新全体についての賭けの意味かのどちらかになる。 どちらかを書く。
6. **予言の結果が、 論文の他の規則の下で何を意味するか** — 予言どおりになっても規則の結論が変わらない場合 (形の上の構造は消えても、 別の検査がまだ構造を示す、 など) は、 そのことを同じ所に書く。 書かないと「予言どおり = 問題が解消」 と読まれる。

**Fix**: 項目を呼び分ける (予言 / 追跡の約束 / 探索)。 「道具を危険にさらす」 のような強い言い方は、 本当に外れうる項目にだけ使う。 予言として残す項目には、 外れる観測を 1 文で書く。 登録の日付を外から確かめられるようにする仕組み (公開の repository と版の DOI) が裏づけるのは、 その日付より後の出来事についての宣言だけ。 内部の記録だけで日付を持つ基準を「事前に登録した」 と書かない。
