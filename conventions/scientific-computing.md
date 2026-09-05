<!-- doc-meta
when: 数値解析・科学計算 code を書くとき
category: research-domain
summary: 数値解析 gotchas (scale-dependent default 等、科学計算リポ共通)
-->
# Scientific computing conventions

数値解析を伴うコードで silently 壊れる典型パターンと防止策を集約する。対象: 物理シミュレーション、 Bayesian fit pipeline、 場理論計算、 数値積分・ODE integrator など、 任意の科学計算系リポ (= public 例: [sogebu/LorentzArena](https://github.com/sogebu/LorentzArena))。

---

## <a id="scale-dependent-default"></a>1. Scale-dependent default は unit system 変更で silently 壊れる

### 問題

ある unit system (例: SI 秒、秒²) を想定して書かれた numerical integration / grid / bracket の default が、同じコードを別の unit system (例: GeV、GeV²) で使うと silently 壊れる。型エラーも数値エラーも出ず、grid が粗すぎ or 細かすぎて posterior / integral / fit が歪んだ値を返す。

**誤検出リスク**: 歪んだ返値が先行研究の値に**偶然**近いと、「よし一致した」と誤解釈する可能性がある。これが一番危険。

### 実例 (2026-04-20、 Hierarchical Bayes mean estimation pipeline)

ある Bayesian fit pipeline の `HierarchicalBayesMean` 関数で、 `TauSqMax` (= τ² の積分上端) の default が固定値 `1000` (= 中性子寿命系の s² 単位を想定)。同じコードを W boson mass の解析 (GeV² 単位) に port した際、 10 万倍オーバーで τ² grid 50 点がほぼ全域で integrand ≈ 0 になり、 HB(α=0) が 80.371 と報告され PDG official 80.369 と「一致」したように見えた。実際の正しい値は 80.386。 詳細 RCA は該当リポの `DESIGN.md` に記載。

### 実例 (2026-05-25、 同 pipeline で MuRange propagation case = sibling defect 13 ヶ月遅延発見)

同じ `HierarchicalBayesMean` 関数で **別の scale-blind default** `MuRange` (= μ 積分の bracket) の default が固定 `{Min[xs] - 10, Max[xs] + 10}` (= 中性子寿命系の s 単位、 spread ~5 を想定した margin 10)。 dimensionless 量 (= S₈ tension、 data spread ~0.09) に port した際、 margin 10 が data spread の **110× 過大** → μ grid 400 点で posterior peak (~0.06 wide) を 1-2 点しか拾えず Trapz discretization で HB SE が **30-50% inflated** + NIntegrate::precw 多発。 13 ヶ月 (2026-04-20 → 2026-05-25) 文書化された値が under-resolved な wrong value のまま使われていた。

**根本因 (= 2026-04-20 fix の narrow scope)**: 2026-04-20 の §1 fix は flagged された `TauSqMax` のみ scale-adaptive 化したが、 同 file 同 function の **同形式 default (= `MuRange`)** を sweep しなかった。 同 trait family の sibling defect を残置 → 13 ヶ月後に別 unit system (= S₈ dimensionless) で symptom 顕在化。

### 実例 (2026-06-01、 scale-adaptive default 自体が「非 robust 統計量 + outlier」で破綻 = 3 例目、 §1 framing を 2 方向に拡張)

2026-04-20 fix で `TauSqMax` (= τ² 積分上端) は **scale-adaptive 化されていた** (= `Max[(10·maxσ)², (5·data spread)²]`) のに、 ある heterogeneous dataset (= 同 unit 内、 49 点、 σ range 0.94〜**50.5**、 σ=50.5 の outlier 1 点を含む) でまた silently 破綻。 `10·maxσ = 505 → TauSqMax ≈ 2.5×10⁵` と真の τ² integrand peak (~5) の **5 万倍**に膨張、 各 μ 点の τ² 積分の peak-finder coarse grid (= **linear** 50 点、 spacing ~5100) が幅 ~10 の真の peak を踏み越え、 quad が peak を盲目積分で取り逃して `res≈0 → density = -∞ → 0` に truncate → posterior の片側が完全欠落 (= 共著者が「右側が突然 0 に落ちる」と発見、 修正前は wrong な単峰として report されていた)。

この 3 例目は §1 の従来 framing (= 「unit system 変更で破綻」) を **2 方向に拡張**する:

1. **trigger は unit 変更ではなく単一 outlier**: 同一 unit system 内でも、 scale-adaptive default が `Max[]` / `Min[]` 系の **非 robust 統計量**を使っていると、 たった 1 点の outlier がそれを膨張させて破綻する。 **「scale-adaptive 化すれば安全」 (= 2026-04-20 防止策) は、 中身が非 robust 統計量だと不十分**。
2. **根治は default の robust 化ではなく downstream consumer の scale-free 化**: bound を robust 化 (= `Max` → median 等) しても `(5·data spread)²` 項が依然 peak の数千倍残り不十分。 真の根治は **bound を消費する側 (= 積分 peak-finder grid) を geometric (log) 間隔にする**こと — そうすれば bound が何桁であれ任意 scale の peak を解像でき、 bound の exact 値に依存しなくなる。 **consumer の scale-invariance が bound の fragility を無効化する** (= この grid-only fix は bound 非変更ゆえ既存の別 unit 検証値を byte-exact で保つ、 という追加利点もある)。 詳細 RCA は該当リポの `DESIGN.md`。

### 防止策

**code 側**:
- Numerical hyperparameter (integration upper bound, grid bracket, bin size, step size 等) の default を**定数で書かない**。`xs`, `sigmas`, data range から計算する scale-adaptive な式にする
- どうしても定数を置くなら、関数先頭で data scale を assert して範囲外なら fail loudly にする
- **sibling sweep at fix time** (= 2026-05-25 RCA 追加、 関連: [`debugging-discipline.md` sibling-audit-on-violation](debugging-discipline.md#sibling-audit-on-violation) の fix-time sibling sweep): scale-blind default を 1 件 fix する際、 **同 file / 同 function / 同 関数族**を grep で sweep して `Max[xs] - 10` 系 (= 中性子寿命用) や `1000` 系 (= s² 想定) の literal を全 enumerate、 同 fix を全 sibling に同時適用する。 「flagged された 1 件を fix」 で止めると残存 sibling が将来 silently symptom を出す (= 上 2026-05-25 case)
- **scale-adaptive default が非 robust 統計量を使うと outlier で破綻** (= 2026-06-01 RCA 追加): `Max[σ]` / `Min[]` ベースの adaptive 式は 1 点の outlier がそれを数桁膨張させて破綻しうる (= scale-adaptive 化は「定数を避ける」 の必要条件だが十分条件ではない)。 対処の優先順位: (1) **bound を消費する grid / integrator を scale-free にする** (= geometric/log 間隔、 適応分割) — bound の exact 値に依存しなくなり最も根治的 (+ bound 非変更ゆえ既存検証値を保てる)、 (2) それが無理なら bound 自体に robust 統計量 (median / percentile) を使う、 (3) どちらも無理なら data scale assert で fail loudly。 ただし robust 統計量だけでは `(5·data spread)²` のような second term が残ると不十分なことがある (= 上 2026-06-01 case) ので (1) を先に検討

**discipline 側**:

新しい物理量 / 新しい unit system にコードを port するとき、**同じ量を 2 つ以上の独立経路で計算して値が一致することを verify する**。経路は例えば:

- `run_<quantity>_check.wl` (simple single eval at α=0)
- `run_<quantity>_alpha_scan.wl` の α=0 point

同じ data、同じ likelihood、同じ α=0 の周辺化なので μ/SE は一致すべき。不一致 = grid / range / default が data scale に合っていない。修正するまで downstream の解析 (density plot、ロバスト性比較等) を信じない。

**check.wl と alpha_scan.wl の MuRange convention** (= 2026-05-25 追加): 同 quantity の 2 script が **異なる integration grid** を使うと SE が drift する (= 上 MuRange propagation case)。 narrow posterior (= bottle/S₈ のような tight 分布) では integration grid resolution が Trapz error を dominate、 default muRange は不十分。 解決策: check.wl の HB call にも alpha_scan.wl と同じ explicit `MuRange` + `GridPoints` (= 600 以上) を pass する (= 2 script が同 grid で同 SE を produce する設計)。 「check は quick simple eval、 alpha_scan は accurate scan」 という責務分離は **数値 accuracy には適用できない** (= 同じ HB call は同じ value を返すべき)。

### Anti-pattern

- 「3 手法走らせたら答えが近かった、OK」→ 3 手法全部が同じ default を共有しているなら、同じバグを 3 回引き当てているだけ。独立経路にならない
- 「先行研究と一致したから合ってる」→ 偶然の一致を排除できない。**同じコード**の別経路で再現することが必要

---

## <a id="explicit-integrator-instability"></a>2. Explicit integrator は dτ 安定境界を超えると silently 発散、 implicit Euler / 解析解で根治

### 問題

**explicit** integrator は ODE の linearization 固有値で安定境界を持つ。 friction-like 項 `du/dτ = -k u` の explicit Euler は

```
u_new = u_old + (-k u_old) Δ = u_old (1 - k Δ)
```

の係数 `(1 - kΔ)` が `|· | < 1` のときのみ stable。 `Δ > 2/k` で sign flip + amplitude amplification、 1 step で `u_new = -O(kΔ) × u_old` の桁外れ値、 続く積分で全 state が runaway。 型エラー無し、 `NaN` 無し、 silently 数値発散して realistic な物理範囲を外れた値に飛ぶ。

caller 側で大 dτ が発生する経路は実環境で必ず存在する:
- ブラウザ tab の background suspend からの wake (= 数時間〜数日 dτ)
- main thread lag spike (= GC pause、 debugger break、 OS schedule pre-emption、 数秒 dτ)
- 物理 sim のテストで意図的に大 dτ を渡す (= 終状態だけ確認したい場合)

**重要**: 物理的には連続時間の friction `du/dτ = -ku` は **常に安定** (= 解 `u(τ) = u₀ exp(-kτ)` で 0 に指数減衰)、 発散は **explicit Euler という数値計算法の選択による artifact** であり friction という現象の性質ではない。 つまり 「dτ > 2/k で発散」 は 「explicit Euler の限界」 であり、 別の integrator (= implicit Euler / 解析解) を選べば任意 dτ で安定。

### 実例 (LorentzArena Bug 14、 2026-05-06)

スマホ Brave で 12.5h background suspend → wake 直後の gameLoop が `dτ = 45000 sec` 1 tick で fire。 friction `k = 0.5` で `1 - kΔ = -22499`、 friction terminal velocity `γ_max = 1.886` で bounded のはずの `pos.t` が 1 tick で **20.37M sec (= 235 日相当)** に runaway。 詳細: [LorentzArena Bug 14 plan](https://github.com/sogebu/LorentzArena/blob/main/2%2B1/plans/2026-05-06-bug14-global-active-time.md) §2.1。

### 防止策の階層 (= 上から順に preferred、 fundamental → workaround)

**(A) Implicit Euler** (= 推奨、 root level fix):

```typescript
// 連続時間 du/dτ = a - k × u を semi-implicit Euler で解く:
// newU = u + (a - k × newU) × Δ
// → newU (1 + kΔ) = u + a × Δ
// → newU = (u + a × Δ) / (1 + kΔ)
const newU = (u + a * dTau) / (1 + k * dTau);
```

- closed-form 1 step、 O(1) 計算
- **任意 dτ で unconditionally 安定** (= 分母 ≥ 1、 オーバーフロー無し)
- `Δ → ∞` で `newU → 0` (= friction 無し thrust の場合) または `newU → a/k` (= terminal balance、 物理正解と一致)
- 線形 ODE は通常 closed-form で解ける、 非線形でも Newton iteration で対応可

LorentzArena では `evolvePhaseSpace` の `frictionCoefficient` 引数経由で friction を semi-implicit に積分 (= [`physics/mechanics.ts`](https://github.com/sogebu/LorentzArena/blob/main/2%2B1/src/physics/mechanics.ts)、 thrust は explicit / friction だけ implicit、 Lorentz boost effect は γ で吸収)。

**(B) Analytic** (= 系が単純なら最高精度):

friction-only `du/dτ = -ku` の厳密解 `u(τ) = u₀ × exp(-kτ)`。 thrust が定数なら `u(τ) = u_inf + (u₀ - u_inf) × exp(-kτ)` (= `u_inf = a/k` terminal balance)。 任意 dτ で exact、 浮動小数点誤差のみ。

但し pos / x 等の積分が closed-form でない (= elliptic 等) 場合は 数値積分が必要、 そのとき implicit Euler の方が pragmatic に。

**(C) Substep with explicit Euler** (= workaround、 implicit / analytic が難しい場合の fallback):

```typescript
// Stable bound: |1 - kΔ| < 1 ⟺ Δ < 2/k. Use 20-40x safety factor.
const MAX_STABLE_SUB_DTAU = (2 / k) / 40;
const N = Math.max(1, Math.ceil(dTau / MAX_STABLE_SUB_DTAU));
const subDTau = dTau / N;
let state = initial;
for (let i = 0; i < N; i++) {
  const force = computeForce(state.u);  // u-dependent force per substep
  state = explicitIntegrator(state, force, subDTau);
}
```

- explicit Euler を温存して dτ を分割する **数値 workaround**
- per-substep で u-dependent な力を再計算 (= constant force のみなら 1-step で OK)
- 通常 dτ で N=1 (no overhead)、 異常 dτ で N=線形 (= 1h dτ で N=36000 ≈ 2ms、 24h で N=864000 ≈ 50ms)
- N に **cap を設けず素直に integrate** (= cap は scientific correctness を犠牲、 線形コストは安価)

**(C) を選ぶ trigger**: implicit Euler の数式 derivation が複雑 (= 強い非線形性 / 多自由度 coupling)、 または既存 integrator の signature 変更コストが高い。 (A) / (B) が closed-form で書ける線形系なら (C) は採らない。

**選択基準まとめ**:

| 系の性質 | 推奨 |
|---|---|
| 線形 ODE (= friction、 spring、 damped oscillator 等) | **(A) implicit Euler** (= closed-form solve、 unconditionally stable) |
| 厳密解が elementary functions で書ける | **(B) analytic** (= exact、 数値誤差 floating-point のみ) |
| 強い非線形 / 多自由度 coupling で implicit が intractable | **(C) substep + explicit** |

LorentzArena Bug 14 では当初 (C) substep を採用したが、 user 「原理的におかしくない?」 push back を契機に (A) implicit Euler に refactor (= friction が線形項なので closed-form solve 可能、 substep は workaround だった)。 詳細経緯: [LorentzArena 5/6 plan §6.5](https://github.com/sogebu/LorentzArena/blob/main/2%2B1/plans/2026-05-06-bug14-global-active-time.md) + [`debugging-discipline.md` fix-verification-3-axis](debugging-discipline.md#fix-verification-3-axis) V1/V3 reflection。

**discipline 側**: physics simulation で「caller がいつでも well-bounded な dτ を渡す」 と仮定しない。 lag spike / browser suspend / debugger break で dτ が秒〜時間オーダーになる経路は実環境で必ず発生する。 integrator は **caller-agnostic に任意 dτ で stable** であるべき、 そのための first-line tool は implicit Euler、 substep は fallback。

### Anti-pattern (= 絆創膏 path)

- **「dτ を caller 側で cap」**: 安定境界の上限 truncate は L2 timing 層の絆創膏。 cap を超えた経路で爆発、 cap 値の tuning が増える、 lag spike で legitimate な大 dτ を truncate して挙動が change する。 cap は「数値解析の正攻法」 ではなく「症状を覆い隠す」
- **「visibilitychange listener で reset」**: L3 architecture 層の絆創膏。 listener が漏れた経路 / fire しない browser で爆発、 listener が乱立して責務が分散
- **「`performance.now()` に切替で dτ 自体を小さくする」**: clock semantic の側面変更で逃げる。 browser-specific な suspend-freeze 挙動 (= mobile はする / desktop はしない) に依存、 spec 不保証、 別経路で爆発する
- **「explicit Euler を温存したまま substep で吸収」**: (C) は valid な fallback だが、 線形系では (A) implicit Euler の方が cleaner で `MAX_STABLE_SUB_DTAU` 等の safety margin constant が不要。 まず (A) を考える、 (C) は (A)/(B) が intractable な場合のみ。
- **「3 手法 (cap + listener + clock 切替) を全部やる、 defense-in-depth」**: 全部 L1-L3 の症状経路 patches、 真の安定性 (= integrator 自身が任意 dτ で正解を出す) は治っていない。 次の経路で再発する

### 関連

- LorentzArena Bug 14 完全治療 plan: [`plans/2026-05-06-bug14-global-active-time.md`](https://github.com/sogebu/LorentzArena/blob/main/2%2B1/plans/2026-05-06-bug14-global-active-time.md) §2.1 + §6.1-6.5 (= 却下した代替案 + implicit Euler refactor 経緯)
- 数値解析教科書: Numerical Recipes §16.6 「Stiff Sets and Multistep Methods」、 implicit method / BDF / step size adaptation 等の古典的扱い
- 関連メタ規律: [`debugging-discipline.md` fix-verification-3-axis](debugging-discipline.md#fix-verification-3-axis) (= V1 numeric trace で代替 algorithm を網羅したか check、 V3 algorithm enumeration の domain-specific 適用が本 §)

---

## <a id="nintegrate-workingprecision"></a>3. NIntegrate WorkingPrecision propagation: 入力配列の precision を inherit させないと `NIntegrate::precw` 大量発火

### 問題

Mathematica の `NIntegrate[expr, {v, breakpts}, WorkingPrecision -> wp]` は integrand `expr` の precision が `wp` 以上であることを期待する。 ところが integrand が依存する pre-NIntegrate 配列 (= integration grid を locate するための `vGrid`、 breakpoint list、 default 上端 `vMax` 等) が **MachinePrecision で計算されていた** 場合、 integrand 評価結果は wp に boost されず MachinePrecision (~16 digits) で返る → NIntegrate が

```
NIntegrate::precw: The precision of the argument function (E ...) is less than WorkingPrecision (80.).
```

を毎 mu grid 点で発火 (= 数百回)。 result 値は MachinePrecision 範囲では正しいが、 wp=80 の意図とは異なる。

### 典型 source (= literal float literal)

```mathematica
(* これらは MachinePrecision を返す *)
tauSqMax = N[Max[(10. Max[ss])^2, ...]]    (* 10. が MachinePrecision *)
vGrid = N[Subdivide[0., tauSqMax, 50]]     (* 0. が MachinePrecision *)
breakpts = N @ Select[{0, vPeak/10, ...}, 0 <= # <= tauSqMax &]  (* N が default で MachinePrecision *)
```

これらが NIntegrate の integrand 経由に渡ると、 上 warning が大量発生。

### 解決策: 全 pre-NIntegrate 配列を wp に SetPrecision

```mathematica
(* wp != MachinePrecision の場合のみ精度 boost *)
tauSqMax = Max[(10 Max[ss])^2, ...];   (* 10 = exact Integer、 ss が wp なら結果は wp *)
tauSqMax = If[wp === MachinePrecision, N[tauSqMax], SetPrecision[tauSqMax, wp]];
vGrid = Subdivide[0, tauSqMax, 50];     (* 0 = exact Integer *)
vGrid = If[wp === MachinePrecision, N[vGrid], SetPrecision[vGrid, wp]];
breakpts = Sort @ DeleteDuplicates @ Select[{...}, 0 <= # <= tauSqMax &];
breakpts = If[wp === MachinePrecision, N[breakpts], SetPrecision[breakpts, wp]];
```

literal は `10.` ではなく `10` (= exact Integer) を使い、 wp != MachinePrecision なら最後に `SetPrecision[..., wp]`。 これで integrand 全体が wp で評価され NIntegrate が文句を言わない。

### benign warning の限定 Quiet (= 残 precw への対処)

posterior peak から離れた extreme mu (= muGrid の端点) では、 integrand exponent が **huge negative** (例 -1500) になり offset subtraction (`integrand - offset` で `offset = max(integrand)`) で cancellation 起こる。 `Exp[-1500 + 1500 + ε]` の ε が MachinePrecision に落ちて NIntegrate::precw が依然発火する。 これは結果が ~Exp[-large] ≈ 0 で mu posterior への寄与が negligible のため **benign** — Quiet で限定 suppress 可:

```mathematica
res = Quiet[
  NIntegrate[..., WorkingPrecision -> wp, ...],
  {NIntegrate::precw}   (* この warning だけ suppress、 他 warning は通常通り出る *)
];
```

Quiet の第 2 引数で **特定の message symbol だけ** を suppress (= 全 warning を握り潰す `Quiet[expr]` は anti-pattern)。 source 直読で benign と確認した warning のみ Quiet 対象に。

### Anti-pattern

- **全 `Quiet[expr]`** (= 第 2 引数なし): 既知 benign 以外の warning も握り潰す。 silent な numerical error の見落としに直結
- **literal `10.` `5.` `0.` を pre-NIntegrate 配列に使う**: MachinePrecision 強制で wp=80 が無意味化、 warning 大量発火
- **`NIntegrate::precw` を「benign だから無視」 と source 確認なしで dismiss**: 真に benign か (= extreme point での cancellation) か実際は数値結果汚染 (= integrand 中の関数が wp 失う) かは source 直読が必要

### 実例 (2026-05-25、 Hierarchical Bayes mean estimation pipeline 拡張)

§1 と同 pipeline で、 `HierarchicalBayesMean` の `MuRange` scale-adaptive 化に伴い `tauSqMax` / `vGrid` / `breakpts` の precision を `wp` に inherit させる修正を実施。 同時に extreme mu (= muRange 端点) での残 precw を `Quiet[..., {NIntegrate::precw}]` で限定 suppress (= 結果が negligible な mu 点での benign cancellation を source 直読で確認後)。 詳細 RCA は該当リポの `DESIGN.md §10 LESSON propagation` 参照。

### 関連

- 上 §1 (= scale-blind default): 同 commit / 同 pipeline での 2 つの修正、 root cause family が「scale-adaptive default + precision propagation」 で対をなす
- [`wolfram-scripting.md`](wolfram-scripting.md): Mathematica の tool semantics gotcha 集 (= 本 § は数値 silent failure 側、 wolfram-scripting.md は tool semantics 側で scope 分離)

---

## <a id="porting-metric-divergence"></a>4. 言語移植 verification: 副次 metric vs main metric の divergence は edge-of-stability boundary として documented で済む

### 問題

同一アルゴリズムを言語 A → 言語 B に移植した時、 implementation の **数値結果** が両者で一致するか? の verification で、 **複数 metric** (= main result + 副次 metric) を取って初めて divergence の **意味** が判明する。

**典型 case** (= 適応 quadrature を含む Bayes posterior の言語間移植、 source / target ともに高水準数値ライブラリ):
- main metric = mu posterior (= per-μ 適応 quadrature + trapezoidal integral)
- 副次 metric = ハイパーパラメータ posterior moments (= analytic μ-marginalization → 1D quadrature)
- main metric が一部 parameter 領域 (= 極端な hyperparameter 値) で divergent (= 異 implementation 間で μ Δ が SE の数倍 order に達する)
- **同 parameter 領域で副次 metric は byte exact 一致** (= 同 grid + 同 formula + 同 trapezoidal、 implementations 間で formula identical)

→ divergence は **共通 formula** (= analytic μ-marginal) の implementation 差ではなく、 **adaptive quadrature 戦略差** (= subdivision 選択や局所最適到達点の差) 由来。 既知の edge-of-stability behavior と整合。

### 含意 (= 移植 verify の design pattern)

副次 metric を併せて取ると、 divergence の **localizability** が向上:
- 全 metric divergent → 形式 / algorithm の根本差 = bug 候補
- 副次 byte exact + main divergent → adaptive 戦略 / 局所最適 差 = boundary-of-stability documented 化で済む (= bug ではない、 implementation 戦略の選択)
- main exact + 副次 divergent → 副次 computation pipeline (= grid resolution / normalization) の差 = 別 issue

### 実例 narrative

該当リポの DESIGN.md (= 「α ≤ X で実用」 boundary 注記) で documented:
- ある dataset で Python (scipy.integrate.quad) ≡ Mathematica (NIntegrate) が高 hyperparameter 領域で main metric (μ/SE) 不一致
- ただし副次 metric (= analytic μ-marginal path) は byte exact
- → 「X 以下で実用」 boundary は **scale-dependent + implementation-dependent**、 該当領域の値を引用する場合は implementation 名 明記推奨

### How to apply

- 移植 verify で **2 つ以上の独立 metric** を取る (= 同 algorithm の異なる aspect を probe)
- main metric divergent でも副次 byte exact なら implementation 戦略差として documented で良し、 強制的に一致させる必要なし (= adaptive quad は inherent に不一致リスクあり)
- documented する際は「副次 metric は byte exact = 共通 formula identical」 を明記 (= reader が 「これは bug か?」 と疑う余地を消す)
- main divergent + 副次 divergent なら **bug 候補**、 source 直読 / regression test 追加で原因特定

### 関連

- DESIGN.md §10 LESSON (= scale-blind default、 本 file §1) の言語移植 verify domain への拡張
- 副次 metric を取らないと「両 implementations が正しい / どちらかが bug」 の判定不能、 sweep mode で「✓ pass」 と書く前に副次取得義務 (= `debugging-discipline.md` sibling sweep の言語移植 verify domain への応用)

---

## <a id="archive-cutover-precondition"></a>5. archive / cutover の precondition: smoke (= exit 0) ではなく sample assertion (= 1 件以上 byte exact verify)

### 問題

migration / refactor で 旧 implementation を archive / removal する **不可逆 cutover** を実行する前に「新 implementation がちゃんと動く」 と判定するゲートを通すが、 「ちゃんと動く」 の定義が **`exit 0` のみ** (= smoke) だと:
- script は走るが output が wrong number でも検出されない
- regression test が無い領域は完全 unknown
- 「全 script 走った ✓」 = cell 埋め assertion (= sweep の goal alignment 違反、 「安価な操作で expensive 操作を bypass」)

### honest precondition (= 3 layer の verify を pass してから cutover)

**Layer 1**: smoke (= 全 entry point が `exit 0`)
- 必要だが不十分、 false sense of done を生む

**Layer 2**: sample output assertion (= 各 entry point の output から **1 件以上** documented value と byte-or-percent exact verify)
- 「該当 documented value どれか 1 つを assert」 で良い、 全 documented value を assert するのは scope 巨大
- script-level regression test (= pytest 等) として fixed-time に embed すると future drift も catch

**Layer 3**: cross-implementation diff (= 旧 implementation も別途実行、 stdout / output file で 3-way diff)
- 「旧 vs 新 が独立に同 documented value を produce する」 verify
- 旧 implementation が依然動く環境 (= 旧 binary / 旧 language runtime) が必要

### 実例 narrative

ある言語移植プロジェクトの archive cutover (= 旧 source file を archive sub-dir に移動) の precondition として:
- Layer 1: N script × 主要 datasets 全 `exit 0` (= 数十回 invocation 確認)
- Layer 2: regression test 数十件 pass (= 全 dataset × method の documented numeric byte-or-percent exact)
- Layer 3: 旧 implementation を archive 後 path から再実行、 sample documented value が新 implementation と byte exact 再現
- 3 layer 全 pass を確認してから不可逆操作 (= git mv) 実行

### How to apply

- 不可逆 cutover (= file removal / archive move / branch deletion / data migration) の前に **3 layer の verify** を明示的に通す
- 「smoke のみ pass」 で cutover すると後で「あの数値 wrong だった」 が発覚した時 rollback コスト高 (= archive されたら 旧 implementation 探しに行く必要、 documented value drift の origin tracing 困難)
- 「ちゃんと動く」 をユーザーから言われた時 / 自分で判断する時、 「**3 layer どこまで pass か?**」 を chat 本文で明示 (= silent assumption 防止)
- regression test 体制が無い領域 (= 新規 migration の初期段階) では Layer 2 ↔ Layer 3 を組み合わせる (= 旧 implementation で sample run + 新 implementation で同 case run + diff、 = manual byte-or-percent exact verify)

### 関連

- `debugging-discipline.md` の sibling sweep + fix verification (= 同 trait の異 framing)
- sweep の goal alignment (= error 発見であって report 生産ではない) の cutover domain 応用

---

## <a id="sympy-verify-transcript"></a>6. Visual source (= 写真 / scan / PDF) からの数式 transcript の hallucination は sympy symbolic verify で expose する

### 問題

板書写真 / 手書きノート scan / PDF 図中の式 を LLM (= Claude / GPT) が visual reading で transcript し、 そのまま LaTeX / Markdown / notes に書き起こすと、 **小さな係数・記号・添字の hallucination が紛れ込む確率が高い**。 typical pattern:

- 「{x/σ + ∂_x} φ_0 = 0」 を「{x/σ + σ ∂_x} φ_0 = 0」 と σ を勝手に補う (= 「次元的に整合する係数を補完しよう」 という generative bias)
- 行列の (i,j) 成分を入れ替える
- 符号 (= +/-) を読み間違える、 dagger / bar / hat 記号を落とす
- 添字の上下を入れ替える (= covariant / contravariant 混在)
- 板書中の **斜め筆記** (= ²) や **薄い chalk** (= 上付き dot) を見落とす

これらは「visual reading の不確実性」 が origin で、 transcript 単独では検出不可能 (= source と transcript の比較しか方法がない)。 LLM 自身も「自信を持って書いた」 感覚で transcript するため、 self-review (= 同 LLM が読み直す) でも素通りする。

### 防止策: 数式 transcript の後、 必ず sympy / numpy / wolframscript で 1 path symbolic verify

transcript した式が「方程式」 / 「恒等式」 / 「expectation value」 等の **algebra で検証可能な claim** を含む場合、 commit 後 sweep の一環として sympy / numpy で symbolic verify を 1 path 試行する。 例:

```python
import sympy as sp
x, sigma, N = sp.symbols('x sigma N', positive=True, real=True)
phi0 = N * sp.exp(-x**2 / (2*sigma))
lhs = (x/sigma) * phi0 + sp.diff(phi0, x)  # ← transcript の eq の左辺
print(sp.simplify(lhs))  # 期待: 0
```

`sp.simplify` が 0 を返せば transcript が algebraic に整合、 0 でなければ hallucination 候補。 数 sec で expose できる。

numeric verify は補完手段 (= sympy が解けない場合):
```python
import math
sigma = 1.7  # arbitrary positive
N2 = 1 / math.sqrt(math.pi * sigma)
integral_xsq = (math.sqrt(math.pi) / 2) * sigma**1.5
expectation = N2 * integral_xsq
assert abs(expectation - sigma/2) < 1e-9, "MISMATCH"
```

### How to apply

1. 数式を含む transcript を commit したら、 sweep の中で「algebra で検証可能な claim」 を列挙
2. sympy 1-liner で symbolic verify、 0 / true / 期待値 一致 を expose
3. mismatch を発見したら **fixup commit** で source を読み直して訂正 (= 「源 transcript の re-read」 + 「sympy verify pass」 の組で確定)
4. 「fix できた」 を symbolic な 0 / true return で expose、 chat 上「✓ pass」 と書くだけで終わらせない (= [`debugging-discipline.md` fix-verification-3-axis](debugging-discipline.md#fix-verification-3-axis) と整合)

### 反例 (= verify が無効な場面)

- transcript が **数式でない pure prose** (= 物理的解釈・歴史的経緯・図解 caption): sympy verify NA、 source と 1 文ずつ照合する手作業 path に戻る
- transcript の式が **解析的に閉じない** (= 数値計算でしか比較できない場合): numeric verify で補完、 但し initial value 依存があれば全 case sweep 不可
- **新規 derivation の transcript** (= 「板書ではこう導出した」 を再現する場合): sympy で derivation step 全 chain を verify するのは scope 大、 代わりに「最終結果が source と一致するか」 のみ verify

### 関連事故

- **2026-05-26 ある講義運営 repo の QM §4**: 板書写真から transcript した「{x/σ + ∂_x} φ_0 = 0」 を「{x/σ + σ ∂_x} φ_0 = 0」 と σ を勝手に補って notes.md / SESSION.md に書き、 commit `1e7d097`。 直後の 4 軸 sweep (= 多 commit 連打圧力 sweep) で sympy で `sp.simplify({x/σ + σ ∂_x} φ_0)` を試行 → (x/σ - x) φ_0 ≠ 0 (σ=1 以外) と expose、 fixup commit `603366b` で訂正。 sympy verify 無しに「transcript した」 で確定していたら、 後の自分 / 学生に誤式を留学させる risk。

### 関連

- [`debugging-discipline.md` fix-verification-3-axis](debugging-discipline.md#fix-verification-3-axis) — 「conceptually clean」 主張の verify 義務 (= 同 trait の異 framing、 transcript domain への応用)
- sweep の goal alignment (= error 発見であって report 生産ではない) の数式 transcript domain 応用

---

## <a id="verify-independent-derivation"></a>7. 検証は source からの独立導出 — 一致合わせは検証でない; 公表式の係数も数値 verify

### 問題

disputed な量 (vertex 係数・規格化・符号) を「相手の結果に一致するよう自分の parameter を tune して『一致した』」 とするのは **検証ではない (= circular)**。 相手が正しいと仮定して fit しただけで、 どちらが正しいかを決めていない。 検証は **source (= 作用 / 定義 / 第一原理) からの独立導出** でのみ成立する。 さらに、 source とした **公表論文の式自体に係数 misprint** があり得る (= peer-reviewed / co-authored でも)。 literal-copy した式を信頼の base にすると誤りを継承する。

### 実例 (= 場の理論の vertex 係数が disputed なケース、 2026-06)

- ある vertex の係数 (= mass:kinetic weight) が co-author 間で disputed。 初手で「相手の値に一致するよう自分の parameter を tune」 して相手の値を得た = **循環論法** (user 指摘で発覚)。
- 正しい検証 = 作用からの汎関数微分 (= finite-difference、 inverse は行列 inverse で厳密) で独立導出 → 自分の元の値が正しいと確定。 **4 経路独立確認** (手導出 / finite-diff / 記号 CAS / 先行文献の正しい恒等式) で cross-check。
- 相手の値の source = 公表論文 (peer-reviewed) の densitised-tensor 恒等式の **係数 misprint** (= 反対称化の 1/k! 欠落、 例: 1/2 vs 正 1/(2!·2!)=1/4)。 同 group の先行論文には正しく載っていた → 公表式でも独立に数値 verify (= 恒等式に成分代入して LHS=RHS check) すべきだった (= peer-reviewed でも misprint はある)。 〔詳細 narrative は当該 private research project の RETRACTIONS.md に記録〕

### 防止策

1. **disputed な量は必ず source から独立導出**。 「相手の数値に合う parameter」 を探す行為が出たら fit であって検証でないと自覚 (= sweep の §「cell 埋めか error expose か」 の verification domain 版)。
2. **source の異なる複数経路で cross-check** (= 手導出 / 数値 / 記号 CAS / 別文献)。 1 経路一致は弱い。
3. **公表式・引用式の係数も数値 verify** (= 恒等式は成分代入、 closed form は sympy)。 「published だから正しい」 は不成立。 §6 (transcript hallucination) の sibling = source 自体の error。
4. literal-copy した式を「source of truth」 化しない。

### Anti-pattern

- 相手の結果に一致する parameter を見つけて「検証完了」 と報告 (= circular)
- 公表論文の式を成分 verify せず信頼の base にし、 misprint を継承

### 関連

- §6 — transcript hallucination の sympy verify (= 本 § は「source 自体の error」 への拡張)
- [`debugging-discipline.md` fix-verification-3-axis](debugging-discipline.md#fix-verification-3-axis) — 「conceptually clean」 主張の verify 義務 (= 同 trait)
- 同 trait family = 「安価な操作 (= 一致合わせ / memory recall / literal-copy) で expensive 操作 (= 独立導出 / 数値 verify) を bypass する」。 review / sweep / context 構築 domain にも同型に現れる

## <a id="first-principles-crosscheck"></a>8. 数値結果は第一原理 (次元解析・対称性・Ward 恒等式・既知極限) で cross-check; 自前の数値がバグり得る

### 問題

自前の数値計算 (script) は **バグり得る**。 数値が第一原理 (次元解析・対称性・ゲージ/Ward 恒等式・既知の極限・文献値) と矛盾したとき、 **数値を信じて第一原理を曲げる** のは誤り。 第一原理は不変だが数値はバグる。 §7 が「相手 (外部) の結果に合わせる circular」 を戒めたのに対し、 本 § は「**自分の数値が正しいと仮定して第一原理を上書きする**」 inverse の trap。

### 実例 (2026-06、 場の理論の 1-loop 2 点関数発散部の一般質量 m 形)

- 1-loop 2 点関数の 1/ε 極の係数を一般質量 m で求めた。 **次元解析**: 4D 2 点関数の 1/ε 極は質量次元 4 の同次 (= m⁴, m²q², q⁴ のみ; 純 m² や定数項は counterterm 構造上あり得ない — Λ~m⁴ / R~m²q² / C²~q⁴)。 ところが script は質量非依存テンソルの係数を **混合次元** (= m⁴−4m²+2) で返した。 私は **script の数値を次元解析より優先**し混合次元形を成果物に記載 → user「次元解析からして質量の色んな冪が足されてるのは明らかに誤り」 で発覚。
- 真因 = seagull/tadpole 関数が single-propagator dim-reg 積分を **m=1 値に hard-code** (= I_{0,1}, I_{1,1} を −1, +1 固定; 正しくは I_{0,1}=−m², I_{1,1}=m⁴)。 **m=1 で偶然一致するため m=1 検証では露見しなかった**。 修正後は同次 dim-4 に。 別の主積分 (= bubble) は常に正しく、 バグは特殊値で縮退する 1 関数に局在。

### 防止策

1. **数値出力を第一原理で必ず cross-check**: (a) 次元解析 (= 同次性)、 (b) 対称性 (= Bose / 離散対称)、 (c) ゲージ/Ward 恒等式 (= 数値結果が満たすべき identity)、 (d) 既知極限 (= 質量ゼロ・運動量ゼロ・共形点)、 (e) 文献値。
2. **数値が第一原理と矛盾したら数値を疑え** (= 数値はバグり得るが第一原理は不変)。 「数値が出たから正しい」 は「cell 埋め」 trait の数値 domain 形態。
3. **verify は疑わしい機構を共有しない独立な方法で**: バグった関数を使った再計算は同じバグを継承する。 独立経路 (= 別定義・別積分法・解析的手計算・第一原理) で。 実例では seagull を頂点 Feynman 則から独立に再構成して確認。
4. **特殊値 (m=1 等) だけで検証しない** (= バグが特殊値で縮退して隠れる)。 一般値 (= 一般 m, 一般運動量) で sweep。
5. **verify 方法それ自体もバグり得る (= 隠れた仮定)**: reconstruction / back-solve が既検証 (= established) record と矛盾したら、 即「record が誤り」 と結論せず、 まず reconstruction の隠れた仮定を疑い ground truth (= 実コード・実データ) で確認。 防止策 3「独立な方法で verify」 の**独立性も暗黙の仮定に依存すれば誤る** (= 例: 係数を m 非依存と仮定した back-solve が m 依存の真値を見逃す)。 ground truth は reconstruction でなく source 自身。

### Anti-pattern

- 自前の数値が次元解析・対称性・WI と矛盾するのに、 数値を信じて第一原理形を「混合次元」 等に歪める
- 特殊値 (m=1) のみで検証し、 一般値での縮退バグを見逃す
- バグった関数を使った再計算を「独立検証」 と称する
- 自分の verify reconstruction が既検証 record と矛盾 → reconstruction の隠れた仮定を疑わず record を即 falsify

### 関連

- §7 — source からの独立導出 (= 本 § は「自分の数値を第一原理より優先する」 inverse trap、 §7 は「相手の数値に合わせる circular」)
- §6 — transcript hallucination の sympy verify (= 同 trait family)
- 同 trait family = 「安価な操作 (= 数値の盲信) で expensive 操作 (= 第一原理 cross-check) を bypass」。 個人層の RCA と詳細物理 narrative は owner の private layer に記録されている (= collaborator は access 不要)

## <a id="calibrate-magnitude-sign"></a>9. Ratio/構造 check は overall scale を fix しない; 既知量で calibrate し、 magnitude と sign を分ける

### 問題

Ward 恒等式・対称性・内部無矛盾性・projector 代数 等の check は全て **ratio / 構造** で、 結果の **overall normalization (絶対 scale)** を constrain しない。 これらが全て pass しても、 全 coefficient が共通因子で間違っている可能性は残る。 「全 check pass」 を「結果は absolute に正しい」 と読むと、 この死角を見落とす。 外部の既知量と比較するときも、 magnitude と sign を一緒に「match」 と言うと符号規約の罠に落ちる。

### 防止策

1. **overall scale は『同じ機構で既知量を計算』 して calibrate**: 自分の loop / 数値機構 (= 積分 measure・trace・pole 抽出・単位) で、 textbook 値が分かっている量を計算し、 一致を確認。 例: 場の理論の loop 機構なら QED vacuum polarization (= 1 Dirac fermion で発散 |Π|=4/3、 units 1/(16π²ε)、 transverse も同時 check)。 これが ratio check では届かない絶対 scale の唯一の anchor。
2. **外部比較は magnitude と sign を分けて述べる**: 絶対値は calibrate 可能だが、 符号は規約依存 (= Euclidean vs Minkowski、 self-energy の overall sign 定義 等) のことが多い。 「match」 と一括りにせず「magnitude 一致 (calibrate 済) / sign は規約依存」 と分けて記す。
3. **doc の数値 claim には実 check を紐付ける**: 「~を 1e-16 で満たす」 等と書いたら、 それを実際に検証する script が存在するか確認。 無ければ claim は未検証 — check を足す (= 「cell 埋めでなく error expose」 の claim-vs-check 版)。
4. **calibration は『その既知量が exercise した構造的特徴』 の scale しか fix しない** (= calibration の scope 限界): 防止策 1 の QED calibration (= 単一添字 γ^μ 頂点) は、 target が持つ richer な構造 (= 多添字の縮約 / index-mixing) を cover しない。 単純構造の calibration pass を「pipeline 全体が absolute に正しい」 と一般化すると、 target の未 calibrate な構造を **crude な射影のまま信じる**死角になる (= §8 防止策 4「特殊値縮退」 の構造版 = **特殊構造縮退**)。 汚染されうる量は crude な index-trace/sum でなく、 **汚染構造が恒等的に消える clean probe** (= 関心量に直交する添字・配置を選ぶ) で直接抽出して cross-check する (= calibration が validation した「構造的特徴」 が target の構造を網羅しているかを問う、 一般則は [`convention-design-principles.md §8.8`](../docs/convention-design-principles.md#proxy-blind-spot) list-audit implicit-scope の数値 calibration 版)。

### 実例 (2026-06、 場の理論の 1-loop 2 点関数)

- 内部 check (diff WI / LL WI / projector 代数 / massless 極限) は全て ratio で overall normalization を constrain せず。 外部 conformal-anomaly 照合 (= form factor vs central charge c) が初の絶対 anchor だったが、 それ自体「自分の値が標準単位」 前提に**循環依存**していた。 → QED vacuum polarization を同機構で計算し |Π|=4/3 (textbook 一致) で scale を独立 calibrate、 magnitude match が solid 化。
- 一方 QED は +4/3 (textbook −4/3) で **符号が規約依存** と判明 → 「magnitude 一致 + sign 規約依存」 と分けて記載 (= 当初 sign 込みで一括 match を主張していたのを訂正)。
- projector 代数を「note は 1e-16 で満たすと主張」 していたが regression が未検証だった → 検証 script を追加 (= 防止策 3)。

### Anti-pattern

- 全 ratio/構造 check pass を「結果は absolute に正しい」 と読み、 overall scale の死角を見落とす
- 外部既知量との「match」 を magnitude と sign 一括で主張 (= 符号規約の罠)
- 単純構造の calibration (例: 単一添字頂点) pass を「pipeline 全体が airtight」 と一般化し、 target の未 calibrate な構造 (= 多添字 mixing 等) を crude 射影のまま信じる (= calibration の scope を validation した構造に限定して読まない)
- doc に「verified」 と書くが実 check の script が無い

### 関連

- §8 — 数値は第一原理で cross-check (= 本 § は「第一原理 check も ratio なら scale を fix しない」 の補完、 絶対 scale には別 anchor 要)
- §7 — source からの独立導出
- 同 trait family = 「verify したつもり」 の死角 (= scale / sign / claim-vs-check の 3 つ)。 個人層 reflex は owner の private layer に記録 (= collaborator access 不要)、 詳細物理 narrative は当該 private research project の DESIGN.md §5.5

## 次に追加される予定 (placeholder)

- 浮動小数点精度起因の silent failure パターン
- 単位系変換ミス (cgs ↔ SI ↔ 自然単位系)
- 境界条件・初期条件の scale-dependence

## <a id="figure-vector-extraction"></a>5. 論文 PDF 図のベクトル path から曲線データを復元して数値照合する (2026-08-21)

> **抽出の次**: 再現できなかった時に「式が誤り / code が誤り / caption が不一致 / 別の数値体系」 のどれかを決める分類 = [`paper-audit.md#figure-irreproducible-taxonomy`](paper-audit.md#figure-irreproducible-taxonomy)。

### 問題
共著者が描いた図 (code なし) が本文の式から再現できるかを検証したい。 目視比較は「だいたい合う」 で止まり、 z 依存の有無・極の位置といった定量的不整合を見落とす。

### 方法
matplotlib / Mathematica 出力の PDF はベクトルなので、 PyMuPDF で path を抜いて data 座標に戻せる:
```python
import fitz, numpy as np
p = fitz.open('fig.pdf')[0]
words = p.get_text('words')          # 目盛りラベルの位置 → 軸の線形/対数写像を決める
for d in p.get_drawings():           # 曲線 = items が多い path; color/dashes で凡例と対応付け
    pts = [(it[1].x, it[1].y) for it in d['items'] if it[0] in 'lc']
```
軸写像は目盛り word の bbox 中心から最小二乗で決める。 得た (x, y) を本文の式で計算した曲線と**最大偏差**で比較する (rms は tail の 0 に引きずられて過小評価になる)。

### 得られる判定
- 同一曲線の重なり (= 図中で別 label の 2 本が vector level で一致) → 作図 code にその parameter が入っていない
- 極・終点の位置 → 規格化定数の逆算 → 本文の定義との比 (z 依存・振幅依存) を検査
- 候補式 × 規約 (θ = 2Δωt か Δωt か等) の総当たり fit で作図時の式を同定 — **横軸の変数と式の変数の因子 2 を最初に固定する** (取り違えると全候補が外れ、 1 周無駄にする)

### 実例 (2026-08-21、 該当 private paper repo)
escape 確率図 4 本のうち label の異なる 2 本ずつが完全一致 → 定義 χ̃ ∝ (z₀/z)^{9/2} と両立せず、 code は z を変えていないと確定。 72 通りの fit で 1 本は最大偏差 0.03 で再現 (使われた式と積分変数を同定)、 もう 1 本は再現不能と確定し、 図を本文の式からの再計算版に差し替える判断材料になった。

**先に著者 repo を探す (2026-09 追補)**: 観測論文は `contour_lines/` `chains/` を GitHub で公開していることがある (例: $r$–$n_s$ の 2025 総合)。 点列があれば図の抽出は cross-check に降格し (2026-09 実測: 95% 外周が抽出と点列で $10^{-4}$ 一致)、 引用条件 (README の cite 要請) を caption で満たす。 chain があれば信用水準そのものを計算できる ([`paper-audit.md#box-test-vs-joint-posterior`](paper-audit.md#box-test-vs-joint-posterior))。

## <a id="evolve-constraints-algebraically"></a>10. 拘束量は独立変数として積分しない — drift → 符号反転 → 反減衰爆発 (2026-09)

**Pattern**: 拘束 (constraint) で決まる量 (宇宙論の H = √(ρ/3M²)、 エネルギー、 正定値であるべき量) を独立の ODE 変数として積分すると、 拘束からの数値 drift が蓄積する。 量が小さくなる regime で drift が符号を反転させると、 **散逸項が反転して反減衰**になり、 解は指数的に爆発する (= silent ではなく派手に壊れるが、 出力だけ見ると「別の物理」 に見える)。

起源事例 (2026-09、 private paper repo): インフレーション後の場の振動を (χ, χ̇, H) の 3 変数系で積分 — H を Ḣ = −χ̇²/2 で独立進化させたところ、 振動位相の誤差蓄積で小さくなった H が実効的に負へ drift し、 摩擦項 −3Hχ̇ が反摩擦化してエネルギーが 3 e-folds で 10²² 倍に「増加」。 診断の入口は物理不変量の監視だった (⟨w⟩ = +0.89 と ρ 増加 = 単一場では不可能)。

**Fix**: 拘束量は代数的に評価する — H = √((½χ̇² + V)/3) を右辺で毎回計算する定式化にすると、 ρ̇ = −3Hχ̇² ≤ 0 (単調減少) が**構造的に保証**され、 爆発経路が design-out される。 一般則: 「保存則・拘束・正定値性は積分で維持するのでなく、 定式化に焼き込む」。

**Validation layer** (同事例で有効だった 3 点セット): ① 不変量の bool 監視 (ρ 単調減少) ② 恒等式の全桁照合 (ρ 比 = e^{−3ΔN(1+w̄)}、 w̄ は計算値) ③ 独立の高次手法との spot-check (mode 方程式の直接積分 vs 2 次摂動公式、 4 桁一致)。 §8 (第一原理 cross-check) の具体形。

## <a id="namespace-override-verification"></a>11. 別 script の関数を差し替える wrapper は、 差し替えが効いたことを sentinel で検証する (2026-09)

**Pattern**: 正本 script の 1 関数 (例: 崩壊率の規格化) だけ差し替えて表を再計算する wrapper で、 `runpy.run_path()` の戻り値 dict に代入して差し替えたつもりになる。 `run_path` は module globals の**コピー**を返すので、 正本の関数群が参照する globals は変わらず、 **差し替えは silent no-op**。 wrapper 自身は正常終了し、 出力は旧規格化のまま。 実害 (2026-09、 private paper repo) = 論文の表 2 枚が旧規格化の値で 1 版流通。 wrapper が自前で計算していた 1 列 (T_rh) だけ正しかったので、 表を見ても気づかなかった。

**Fix**: `g = {"__name__": "not_main"}; exec(open(f).read(), g); g["func"] = new_func` — exec に渡した dict が module globals そのものになるので差し替えが効く (importlib は macOS system python の stale .pyc 問題で別途避ける)。

**Validation**: 差し替えた関数に sentinel (print / 戻り値に印) を入れ、 **再計算の出力に sentinel が現れること**を 1 回確認してから表を採用する。 最も安価なのは「変わるはずの数字が実際に変わったか」 の diff (例: N_* が +0.2 動くはず、 動いていなければ差し替えは効いていない)。 「override したから新しい値」 は検証でない ([#verify-independent-derivation](#verify-independent-derivation) の道具版)。

## <a id="declared-self-consistency-audit"></a>「self consistent に解いた」 と書く前に、 loop の全変数が code で戻っているか列挙する (2026-09)

**Pattern**: 「$V_0$ は $A_s$ から、 $m$ は $V_0$ から、 rate は $m$ から、 $N_*$ は rate から」 という自己整合の連鎖を本文で謳いながら、 code は $m$ を定数に固定していた ($V_0\to m$ の 1 本だけ戻していない)。 影響は小さかった ($N_*$ +0.02–0.05、 $T_\text{rh}$ +7–16%、 観測量 $<10^{-4}$) が、 本文の主張が code より強い状態が数版続いた。 別 AI session の独立反復で検出 (2026-09、 private paper repo)。

**Fix**: 「self consistent」 の文を書く時点で fixed point に入る量を列挙し (入力 → 導出 → 戻し先)、 code の loop 内で各量が再計算されている行を指す。 固定するなら本文にそう書く (「$m=2\times10^{13}$ で固定」)。 検証は「戻すはずの量を戻したら数字が動く」 の diff ([#namespace-override-verification](#namespace-override-verification) と同型)。

## <a id="floquet-exact-background"></a>Floquet 指数は厳密な周期解の上で取る — 調和近似の背景は偽の不安定性を作る (2026-09)

**Pattern**: 振動する背景 $\chi(t)$ の上で mode の Floquet 指数を出す時、 背景を $\chi=\Phi\cos mt$ で代用すると、 厳密には marginal な mode (例: 運動項の conformal factor から来る $k=0$ mode、 厳密解 $H_c\propto e^{-\gamma\chi/2}$ で有界) に有限の指数が出る。 質量項が背景の運動方程式を使って導かれている場合、 その相殺は**真の解の上でしか成り立たない**。

**Fix**: 背景は非調和ポテンシャルの周期解を数値で取り ($\chi(0)=\Phi$、 $\dot\chi=0$ から $\dot\chi=0$ への戻りを event で捕まえて周期 $T$ を得る、 event の direction は戻り側の符号)、 monodromy を 1 周期で取る。 検算 = 解析的に marginal と分かる mode の指数が 0 になること (同事例: 調和背景で +0.2〜+1.3 だった $k=0$ の指数が厳密背景で 0.000、 最速成長は $k\simeq0.5$–$0.75\,m$ に移動)。

## <a id="first-step-skips-initial-heuristic"></a>SciPy `solve_ivp` の初期 step 推定 overflow は `first_step` で消す (2026-09)

**Pattern**: `solve_ivp(..., atol=1e-300)` で初期値の一成分が $10^{-290}$ のような極小値だと、 初期 step 推定 (`d1 = norm(f0/scale)`) が overflow / invalid の warning を出す。 結果は正しいが、 warning-clean でないと再現者が「何かおかしい」 で止まる。

**Fix**: `first_step=<小さな値>` を渡す (推定を skip、 適応刻みはそのまま)。 出力が文字単位で同一であることを diff で確認してから採用する (同事例: 表の不変行 5 本が IDENTICAL)。

## <a id="contour-distance-axis"></a>等高線への「距離」 は物理的に意味のある軸に沿って測る (2026-09)

**Pattern**: 模型の軌跡と 95% 等高線の関係を $(\Delta n_s,\,0.1\,\Delta r)$ の scaled Euclid 距離で報告すると、 縁に接するように見えて実際は固定 $r$ で $\Delta n_s=+0.002$–$0.003$ 外だった (Euclid 0.0009)。 scaled 距離は等高線の傾き方向に最短を取るので、 読者が問う「同じ $r$ でどれだけ外か」 とは別の量。 盲検 reviewer との数値不一致で発覚 (2026-09)。

**Fix**: 点内判定は多角形で厳密に、 「どれだけ外か」 は物理軸 1 本 (固定 $r$ での $n_s$ の隙間) で報告する。 別実装と数値が合わない時は、 まず距離の定義を突き合わせる。

## <a id="small-sdp-without-solver"></a>小さな SDP を solver 無しで回す — SLSQP + explicit dual certificate の sandwich (2026-09)

**Pattern**: 検証 worker の環境に SDP solver (cvxpy / SCS / MOSEK) が無く、 install も spec で避けたい (再現環境の最小化) が、 qubit〜qutrit 規模の半正定値計画 (共通下界 max Tr c s.t. 0 ≤ c ≤ a, b / joint measurement の最適化) が要る。 scipy の SLSQP で固有値制約を扱うと動くが、 局所 solver の答えは**それ自体では証明にならない**。

**Fix (= `scripts/gpt_measurements.py` に固定した recipe)**:
1. **primal + dual を別々に解いて sandwich する**: 弱双対性で primal ≤ dual が常に成り立つので、 両方の feasible point を出して [primal, dual] を報告すれば、 solver がどう動いたかによらず float 精度で厳密な区間になる。 dual の feasibility 違反は identity 方向へ shift して repair (例: Y, Z を violation/2 だけ持ち上げ)。
2. **定性判定 (存在 / 非存在) は solver に頼らない**: 「非零共通下界が無い」 は supp 射影から作る explicit certificate (Y = tP_ker a, Z = tP_ker b、 Y+Z ≥ I、 Tr(aY+bZ) = 0) で証明、 「有る」 は具体的な c と witness を構成して検証。 solver は量的値 (α の数値) にだけ使う。
3. **gotcha 群** (全て実測): (a) 2×2 の PSD を滑らかな形 (対角 ≥ 0 ∧ det ≥ 0) で書くと SLSQP が凸問題で stall する (det の線形化が悪い) — 固有値制約 + random restart の方が良く動く、 best feasible iterate を保持し全滅時は feasible な x0 に fallback。 (b) 等式制約 (周辺条件) は冗長で QP が rank 落ちする — null-space parametrization で消去する。 (c) c = 0 や canonical joint は制約の退化点 (勾配 0) で動かない — parallel sum a:b = (a⁻¹+b⁻¹)⁻¹ ≤ a, b を内点の出発点にする。 (d) 凹関数の最小化 (α_IS = min_B λ_min(Σb_xx)) は凸計画でない — 純粋状態の scan × 内側凸計画に分解し、 外側 scan は evidence であって certificate でないと明記する。
5. **並列和の sandwich = solver ゼロの certified 区間** (2026-09 第二の目 campaign): 最大共通下界ノルムは **‖a:b‖ ≤ max‖c‖ ≤ 2‖a:b‖** (a:b = (a⁻¹+b⁻¹)⁻¹ ≤ a, b は自身が共通下界、 逆に任意の共通下界 c は ⟨ξ,cξ⟩ = ⟨x+y, c(x+y)⟩ ≤ 2(⟨x,ax⟩+⟨y,by⟩) の inf で c ≤ 2 a:b)。 SLSQP を回す前にこれで足りるか見る。 道具 = `gpt_measurements.common_lower_bound_sandwich`。 ⚠️ 固有値が 1e-8 を割る作用素 (例: e^{-2|n|} 減衰) は float の逆行列が壊れる — `dps=` で mpmath に切替、 正則化 δ は入力の丸め (double なら 1e-14) 以上に取る (δ 未満だと a+δ が PSD でなく逆行列が発散)。
6. **exact な主張が double の下にある時は高精度で certify する**: 正定値性・非零性の閾値を float の λ_min に当てる前に、 その量の減衰 rate を見る (prolate 型 Gram 行列は N=16 で 1e-38)。 mpmath 100 桁 (`mp.eighe`) で証明書を出し、 「double で見えない」 を「偽」 と読まない。 実測 = [`physics-verification-cycle.md#definition-level-judge`](physics-verification-cycle.md#definition-level-judge) 10。
7. **run hygiene**: 長い check を background で回す時、 **同じ出力 file に 2 プロセスが同時書き込みしない** (旧 run を kill せず relaunch すると PASS 行と旧 run の OVERALL: FAIL 行が混ざり、 grep で FAIL 行が見つからないのに OVERALL が FAIL という説明不能な出力になる。 2026-09-05 実測)。 relaunch は `pgrep -fl <script>` で旧 run の不在を確認してから、 出力 file は run ごとに別名。
8. **汎用 dual が緩い時は問題の構造から明示 dual を組む** (2026-09-05 実測): 共通下界 SDP の dual を SLSQP に解かせると identity 近傍で止まり dual ≈ Tr a + Tr b (primal の 50 倍) で sandwich が無意味になった。 a, b が単位 vector u, v 方向にほぼ rank-one なら (Y, Z) = t(Q_u, Q_v)、 t = 1/(1−|⟨u|v⟩|) が dual 実行可能 (‖p_u + p_v‖ = 1 + |⟨u|v⟩| ⇒ Y + Z ≥ I) で、 値 t[Tr(Q_u a) + Tr(Q_v b)] は証明で使う不等式そのもの = **証明の核心不等式 = 明示 dual certificate** という一致が起きる。 solver の dual は「出せたら報告」、 上界として引用するのは構造から作った方 (`gpt_measurements.py` の `nearly_rank_one_clb_bound`、 一般則 = [`physics-verification-cycle.md#definition-level-judge`](physics-verification-cycle.md#definition-level-judge) kernel 14)。

**関連**: [`physics-verification-cycle.md#definition-level-judge`](physics-verification-cycle.md#definition-level-judge) (証明書ベースの定性判定を検証 item の既定にする理由) / [#verify-independent-derivation](#verify-independent-derivation)。
