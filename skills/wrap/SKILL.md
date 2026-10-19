---
name: wrap
description: 作業の仕上げ (締めの sweep)。 user が `/wrap` (または「仕上げ」「締め」「wrap up」) と打ったら起動する。 この session と、 この session が使った agent・子 session・別 session への依頼で得た知見・手順・使い捨ての script を正しい層の正本へ移し、 正本と参照・SESSION・TODO を整え、 repo ごとに commit + push して報告する。 claude-config の改善案は PR で出す。 Closing sweep for any claude-config user (Claude Code and Codex).
---

# wrap — 締めの sweep (claude-config の汎用版)

**手順の正本 = claude-config の [`conventions/closing-sweep.md`](../../conventions/closing-sweep.md)** — 0 から 5 まで順に読んで、 そのとおりにする
(この file は claude-config の `skills/wrap/`。 claude-config の root = この file の 2 つ上、 普通は `~/Claude/claude-config`)。
手順・OS ごとの違い (macOS / Linux / Windows)・Codex での読み替えは、 その doc の [§0.9](../../conventions/closing-sweep.md#any-os) と [§0.95](../../conventions/closing-sweep.md#codex) が持つ = ここに写さない。

## この版の値

| 段 | 値 |
|---|---|
| 0.3 / 0.5 の `<id8>` | この session の id の先頭 8 文字 (Claude Code = 会話記録の file 名の uuid。 Codex = 渡された session id) |
| 道具 | claude-config の `scripts/` (`search-agent-transcripts.py` / `session-scripts-report.py` / `subagent-reports.py` / `headless-worker-reports.py` / `fix-md-links.py`) (OS ごとの起動の違い = 上の §0.9) |
| 0.5 / 1.5 の掲示板 | 掲示板を使っていなければ飛ばし、 報告に「使っていない」 と書く |
| 作業した repo の約束 | 各 repo の `CLAUDE.md` (暗号化・平文に書かないもの・commit message の規則・公開か非公開か) を全段に当てる |
| 個人の値 | 個人層に同名の skill (`/wrap`) があればそちらが起動する。 その skill は本 file を手順の正本として指し、 その人の値だけを持つ ([closing-sweep.md#personal-skill](../../conventions/closing-sweep.md#personal-skill)) |

## claude-config への改善案は PR で出す (既定)

1 の表で「層1」 に置くと決めたもの (誰にでも効く手順・道具の壊れ方・規約の穴・雛形の不足) は手元だけに置かず、 claude-config に入れる。
claude-config に push できない人は fork して PR を出す。 **出すのが既定** = 1 件ごとに user に可否を聞かない (止めるのは user が止めたときだけ)。
手順・境界・確かめ方の正本 = [closing-sweep.md#upstream-pr](../../conventions/closing-sweep.md#upstream-pr)。 出した PR は link と要約を報告に書く。
