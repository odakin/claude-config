<!-- doc-meta
when: 論文・研究ノートの主張を機械検査で守る体制を組むとき / 外部論文を検証読みするとき / 検証系 AI workflow (verify-to-learn・adversarial pass・campaign) を設計するとき
category: research-domain
summary: → **移設済 (2026-09-06)**: 正本は ai-collaboration/conventions/physics-verification-cycle.md (何を検査するか: 4 station / 機械 anchor / foil / tier / 3 状態 / verify-to-learn / 第二の目 / rubric / 止まる規律 / cross-vendor / campaign 運用 A-K)。 本 file は旧 anchor を保つ stub
-->
# physics-verification-cycle.md — 移設済 stub (2026-09-06)

**正本 = [`ai-collaboration/conventions/physics-verification-cycle.md`](../../ai-collaboration/conventions/physics-verification-cycle.md)** (layer 1、 public、 GitHub `odakin/ai-collaboration`)。 検証サイクルの platform を `claude-config` (Claude Code の harness) から vendor 中立の箱に分離した (判断 = `ai-collaboration/DESIGN.md`)。 git 履歴は移設先に `format-patch` で持ち込み済 (本 file の履歴も残る)。

旧 anchor は下表で保つ (= 496 件の literal path と `#anchor` link を壊さない)。 新 doc の同名 anchor へ:

| 旧 anchor (この file) | 移設先 |
|---|---|
| <a id="cycle-shape"></a>`#cycle-shape` — 1. サイクルの形 — 4 station + 「1 つでも fail したら進めない」 | [`physics-verification-cycle.md#cycle-shape`](../../ai-collaboration/conventions/physics-verification-cycle.md#cycle-shape) |
| <a id="machine-anchor-per-claim"></a>`#machine-anchor-per-claim` — 2. 主張ごとの機械 anchor — 安定した主張は audit script に固定する | [`physics-verification-cycle.md#machine-anchor-per-claim`](../../ai-collaboration/conventions/physics-verification-cycle.md#machine-anchor-per-claim) |
| <a id="identifier-anchor-coverage"></a>`#identifier-anchor-coverage` —  | [`physics-verification-cycle.md#identifier-anchor-coverage`](../../ai-collaboration/conventions/physics-verification-cycle.md#identifier-anchor-coverage) |
| <a id="foil-negative-control"></a>`#foil-negative-control` — 3. Foil (negative control) — 「検査に歯があること」を検査する | [`physics-verification-cycle.md#foil-negative-control`](../../ai-collaboration/conventions/physics-verification-cycle.md#foil-negative-control) |
| <a id="verification-tier"></a>`#verification-tier` — 4. 検証 tier の宣言 — 転記と検証を混同しない | [`physics-verification-cycle.md#verification-tier`](../../ai-collaboration/conventions/physics-verification-cycle.md#verification-tier) |
| <a id="claim-states"></a>`#claim-states` — 5. Claim の 3 状態 — 確かめられなかった項目を分かったことにしない | [`physics-verification-cycle.md#claim-states`](../../ai-collaboration/conventions/physics-verification-cycle.md#claim-states) |
| <a id="verify-to-learn"></a>`#verify-to-learn` — 6. Verify-to-learn — 外部論文の検証読み (名 = 日高氏講演。 手順自体は当方の検証読み運用が先行 | [`physics-verification-cycle.md#verify-to-learn`](../../ai-collaboration/conventions/physics-verification-cycle.md#verify-to-learn) |
| <a id="independent-second-eye"></a>`#independent-second-eye` — 7. 独立した第二の目 — 自己検査は独立検証ではない | [`physics-verification-cycle.md#independent-second-eye`](../../ai-collaboration/conventions/physics-verification-cycle.md#independent-second-eye) |
| <a id="cross-vendor-red-team"></a>`#cross-vendor-red-team` —  | [`physics-verification-cycle.md#cross-vendor-red-team`](../../ai-collaboration/conventions/physics-verification-cycle.md#cross-vendor-red-team) |
| <a id="rubric-before-run"></a>`#rubric-before-run` — 8. 評価基準は走らせる前に決める — 判定不能は判定不能と言う | [`physics-verification-cycle.md#rubric-before-run`](../../ai-collaboration/conventions/physics-verification-cycle.md#rubric-before-run) |
| <a id="efficacy-proxy-receiver-side"></a>`#efficacy-proxy-receiver-side` —  | [`physics-verification-cycle.md#efficacy-proxy-receiver-side`](../../ai-collaboration/conventions/physics-verification-cycle.md#efficacy-proxy-receiver-side) |
| <a id="stop-when-no-grounds"></a>`#stop-when-no-grounds` — 9. 止まる規律 — 根拠がない時は進めず人間に渡す (標語 = 日高氏講演) | [`physics-verification-cycle.md#stop-when-no-grounds`](../../ai-collaboration/conventions/physics-verification-cycle.md#stop-when-no-grounds) |
| <a id="cross-vendor-blind-verification"></a>`#cross-vendor-blind-verification` — 10. Cross-vendor 盲検 — 同系統 AI の N 実装一致は独立性が本物でない (2026-09) | [`physics-verification-cycle.md#cross-vendor-blind-verification`](../../ai-collaboration/conventions/physics-verification-cycle.md#cross-vendor-blind-verification) |
| <a id="approximation-tier-closure"></a>`#approximation-tier-closure` — 11. 近似階層の妥当性は判断でなく計算 — N 実装一致は「同じ理想化の中の一致」でしかない (2026-09) | [`physics-verification-cycle.md#approximation-tier-closure`](../../ai-collaboration/conventions/physics-verification-cycle.md#approximation-tier-closure) |
| <a id="external-ai-referee-premise-verification"></a>`#external-ai-referee-premise-verification` — 12. 外部 AI 査読レポートの前提検証 pass — 鵜呑みも防衛反射もしない (2026-09) | [`physics-verification-cycle.md#external-ai-referee-premise-verification`](../../ai-collaboration/conventions/physics-verification-cycle.md#external-ai-referee-premise-verification) |
| <a id="definition-level-judge"></a>`#definition-level-judge` — 14. verify-to-learn の実測 kernel 追補 — 41 item campaign (2026-0 | [`physics-verification-cycle.md#definition-level-judge`](../../ai-collaboration/conventions/physics-verification-cycle.md#definition-level-judge) |
| <a id="continuous-rank-one-povm-extremality"></a>`#continuous-rank-one-povm-extremality` — 連続 rank-one POVM の「極値性 → self-joint 一意性」を閉じる recipe (campaig | [`physics-verification-cycle.md#continuous-rank-one-povm-extremality`](../../ai-collaboration/conventions/physics-verification-cycle.md#continuous-rank-one-povm-extremality) |
| <a id="continuous-rank-one-povm-cell-route"></a>`#continuous-rank-one-povm-cell-route` —  | [`physics-verification-cycle.md#continuous-rank-one-povm-cell-route`](../../ai-collaboration/conventions/physics-verification-cycle.md#continuous-rank-one-povm-cell-route) |
| <a id="campaign-tooling"></a>`#campaign-tooling` — 15. Verify-to-learn campaign の運用 kernel — ledger・2 段階第二の目・繰り | [`physics-verification-cycle.md#campaign-tooling`](../../ai-collaboration/conventions/physics-verification-cycle.md#campaign-tooling) |
| <a id="sibling-routing"></a>`#sibling-routing` — 16. 隣接 doc への routing | [`physics-verification-cycle.md#sibling-routing`](../../ai-collaboration/conventions/physics-verification-cycle.md#sibling-routing) |
