<!-- doc-meta
when: cold-eyes / 盲検 review を別 session に投げる前 / referee 版の原稿を用意する時 / review 結果の独立性を判定する時
category: research-domain
summary: → **移設済 (2026-09-06)**: 正本は ai-collaboration/conventions/cold-eyes-isolation.md (汚染経路 6 口 / 封じた sandbox / spec に書いてよいこと / 受領後の汚染 grep)。 本 file は旧 anchor を保つ stub
-->
# cold-eyes-isolation.md — 移設済 stub (2026-09-06)

**正本 = [`ai-collaboration/conventions/cold-eyes-isolation.md`](../../ai-collaboration/conventions/cold-eyes-isolation.md)** (layer 1、 public、 GitHub `odakin/ai-collaboration`)。 検証サイクルの platform を `claude-config` (Claude Code の harness) から vendor 中立の箱に分離した (判断 = `ai-collaboration/DESIGN.md`)。 git 履歴は移設先に `format-patch` で持ち込み済 (本 file の履歴も残る)。

旧 anchor は下表で保つ (= 496 件の literal path と `#anchor` link を壊さない)。 新 doc の同名 anchor へ:

| 旧 anchor (この file) | 移設先 |
|---|---|
| <a id="contamination-channels"></a>`#contamination-channels` — 1. 汚染経路 — reviewer session に著者の結論が流れ込む 6 つの口 | [`cold-eyes-isolation.md#contamination-channels`](../../ai-collaboration/conventions/cold-eyes-isolation.md#contamination-channels) |
| <a id="sealed-sandbox"></a>`#sealed-sandbox` — 2. 封じた sandbox の recipe | [`cold-eyes-isolation.md#sealed-sandbox`](../../ai-collaboration/conventions/cold-eyes-isolation.md#sealed-sandbox) |
| <a id="spec-leakage"></a>`#spec-leakage` — 3. spec に書いてよいこと・書いてはいけないこと | [`cold-eyes-isolation.md#spec-leakage`](../../ai-collaboration/conventions/cold-eyes-isolation.md#spec-leakage) |
| <a id="post-check"></a>`#post-check` — 4. 受領後の汚染 check | [`cold-eyes-isolation.md#post-check`](../../ai-collaboration/conventions/cold-eyes-isolation.md#post-check) |
| <a id="external-paper-variant"></a>`#external-paper-variant` — 4.5 変種: 外部論文の検証読み (verify-to-learn) は sandbox でなく deny list  | [`cold-eyes-isolation.md#external-paper-variant`](../../ai-collaboration/conventions/cold-eyes-isolation.md#external-paper-variant) |
