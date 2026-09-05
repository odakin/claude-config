<!-- doc-meta
when: 検証サイクルを session を越えて回し続ける仕組みを設計・運用・診断するとき
category: research-domain
summary: → **移設済 (2026-09-06)**: 正本は ai-collaboration/conventions/verification-cycle-ops.md (6 原則 / 導出 state / 台帳 3 種 + retro / 無人層 / fresh session の手順)。 本 file は旧 anchor を保つ stub
-->
# verification-cycle-ops.md — 移設済 stub (2026-09-06)

**正本 = [`ai-collaboration/conventions/verification-cycle-ops.md`](../../ai-collaboration/conventions/verification-cycle-ops.md)** (layer 1、 public、 GitHub `odakin/ai-collaboration`)。 検証サイクルの platform を `claude-config` (Claude Code の harness) から vendor 中立の箱に分離した (判断 = `ai-collaboration/DESIGN.md`)。 git 履歴は移設先に `format-patch` で持ち込み済 (本 file の履歴も残る)。

旧 anchor は下表で保つ (= 496 件の literal path と `#anchor` link を壊さない)。 新 doc の同名 anchor へ:

| 旧 anchor (この file) | 移設先 |
|---|---|
| <a id="why"></a>`#why` — 0. なぜ「回し続ける」 が別問題か | [`verification-cycle-ops.md#why`](../../ai-collaboration/conventions/verification-cycle-ops.md#why) |
| <a id="principles"></a>`#principles` — 1. 六つの原則 | [`verification-cycle-ops.md#principles`](../../ai-collaboration/conventions/verification-cycle-ops.md#principles) |
| <a id="state-machine"></a>`#state-machine` — 2. campaign の導出 state | [`verification-cycle-ops.md#state-machine`](../../ai-collaboration/conventions/verification-cycle-ops.md#state-machine) |
| <a id="ledgers"></a>`#ledgers` — 3. 台帳 3 種と retro | [`verification-cycle-ops.md#ledgers`](../../ai-collaboration/conventions/verification-cycle-ops.md#ledgers) |
| <a id="autonomous-layer"></a>`#autonomous-layer` — 4. 無人層 — 何を無人にし、 何を越えないか (日高氏 #17「完全自律 run」 の部分採用、 2026-09-0 | [`verification-cycle-ops.md#autonomous-layer`](../../ai-collaboration/conventions/verification-cycle-ops.md#autonomous-layer) |
| <a id="fresh-session"></a>`#fresh-session` — 5. fresh な session が最初にやること (= 手順の全部) | [`verification-cycle-ops.md#fresh-session`](../../ai-collaboration/conventions/verification-cycle-ops.md#fresh-session) |
| <a id="failure-modes"></a>`#failure-modes` — 6. 想定する壊れ方と検出 | [`verification-cycle-ops.md#failure-modes`](../../ai-collaboration/conventions/verification-cycle-ops.md#failure-modes) |
| <a id="limits"></a>`#limits` — 7. 正直な限界 | [`verification-cycle-ops.md#limits`](../../ai-collaboration/conventions/verification-cycle-ops.md#limits) |
