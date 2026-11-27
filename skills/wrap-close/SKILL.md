---
name: wrap-close
description: 締めてから窓を閉じる (wrap して閉じる)。 user が `/wrap-close` と打ったとき、 または普通の語で「wrap して閉じて」「締めて閉じて」「仕上げて閉じて」「子を全部締めてここも閉じて」 のように、 締め (仕上げ) とこの窓を閉じることを一緒に頼んだときに起動する。 起こした子 session を締めて archive し、 この窓の締め (`/wrap` と同じ手順) をして、 残りが無いのを道具で確かめてから閉じる口を出す。 閉じない途中の仕上げは `/wrap` (こちらは起動しない)。 Wrap the children, wrap this window, then close it (Claude Code desktop app).
---

# wrap-close — 子を締め、 自分を締め、 窓を閉じる (claude-config の汎用版)

**手順の正本 = claude-config の [`conventions/closing-sweep.md#wrap-close`](../../conventions/closing-sweep.md#wrap-close)** — 段 1 (子を締める) → 段 2 (自分を締める = 同じ doc の 0 から 5、 `/wrap` と同じ) → 段 3 (自分を閉じる) の順に読んで、 そのとおりにする
(この file は claude-config の `skills/wrap-close/`。 claude-config の root = この file の 2 つ上、 普通は `~/Claude/claude-config`)。
段の中身・閉じない場合の線・閉じる口はその節が持つ = ここに写さない。

## この版の値

| 段 | 値 |
|---|---|
| 1・3 の一覧 | `python3 scripts/child-wrap-check.py --close-plan` (既定 = この窓 = env `CLAUDE_CODE_SESSION_ID`、 別の窓なら `--parent <local_…>`。 掲示板の root は `--board-root` か個人層の `child-wrap-check.json`) |
| 1 の wrap の依頼と見張り | 一覧の「wrap を頼む」 の行が出す文と `--wait` の 1 行をそのまま使う |
| 1 の Codex の thread | `scripts/codex-thread-close.py` (手順 = `conventions/multi-session-coordination.md#codex-thread-close`) |
| 2 | 誰でも使える `/wrap` の表 ([`../wrap/SKILL.md`](../wrap/SKILL.md)) の値をそのまま当てる |
| 3 の見張り | `python3 scripts/lib/session_background_tasks.py self` (止め方 = closing-sweep.md#stop-own-watches) |
| 3 の閉じる口 | 最後の `wrap_up` の `archive` の action。 使えなければ本人の「閉じて」 の後の turn に `archive_session` の `"self"` (closing-sweep.md#wrap-close-button) |
| 個人の値 | 個人層に同名の skill (`/wrap-close`) があればそちらが起動する。 その skill は本 file と節を手順の正本として指し、 その人の窓の登録の畳み方と値だけを持つ ([closing-sweep.md#personal-skill](../../conventions/closing-sweep.md#personal-skill)) |

Codex で起動したら: 段 2 は `$wrap` と同じ締め (closing-sweep.md §0.95)、 段 1 は Codex の thread の道具の行だけ、 段 3 の閉じる口は無い (閉じるのは本人)。
