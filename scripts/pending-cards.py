#!/usr/bin/env python3
"""pending-cards.py — この session が出した card のうち押されていないものを数え、 本人がまだ見ていない間は最新の返事に点呼の 1 行を書かせる (Stop hook の本体)。 見張りが card を出した依頼を拾い直さないための照会と、 過去の会話記録での流し直しも持つ

正本 = conventions/multi-session-coordination.md#pending-card-rollcall。 述語 = scripts/lib/pending_cards.py。

使い方:
  --stop              Stop hook の本体 (stdin = hook の payload)。 本人がまだ見ていない押されていない card があり、
                      今の turn の最終発話に点呼の行 (「🃏 押されていない card N 枚」) が無ければ、 書く 1 行を
                      添えて 1 回だけ止める (decision=block)。 stop_hook_active・最終発話が空・読めない記録は黙る (fail-open)。
  --session ID        その session の card の一覧と、 押されていない card が名指す掲示板の request id を JSON で出す
                      (見張りが拾い直さない依頼を引く)。 ID = 会話記録の id (頭 8 字以上) か transcript の path。
  --replay PATH       会話記録の turn ごとに、 その時点で点呼が要ったか・最終発話に在ったかを並べる
                      (app の記録は、 その turn の終わりまでにできた session だけを押された印に数える)。
  --selftest          合成の会話記録で鳴る形と黙る形を確かめる。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
import pending_cards as pc  # noqa: E402

try:
    import transcript_turns as tt  # noqa: E402
except Exception:  # pragma: no cover
    tt = None


def _final_text(entries: list[dict]) -> str:
    if tt is not None:
        return tt.current_turn_final(entries)[0]
    final = ""
    for e in reversed(entries):
        if e.get("type") == "user" and not pc._is_tool_result_row(e):
            break
        if e.get("type") == "assistant":
            for b in pc._blocks(e):
                if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                    return b["text"]
    return final


def reason_for(unseen: list[dict]) -> str:
    line = pc.rollcall_line(unseen)
    return (
        "🃏 押されていない card が " + str(len(unseen)) + " 枚あり、 本人はまだ見ていません (この返事の後に本人が話せば、 "
        "その返事を最後に点呼は止まります)。 card は出した時点の会話にしか描かれず、 後の返事で画面の上に流れます。\n"
        "返事の終わりに次の 1 行をそのまま足してください (本文は出し直さない):\n"
        f"  {line}\n"
        "締めの箱を出すなら、 要約の 1 文目を「押されていない card が " + str(len(unseen)) + " 枚あります」 にし、 問いが空いていれば"
        "「待っている card " + str(len(unseen)) + " 枚を起こしますか？」 + ボタン「" + str(len(unseen)) + " 枚とも起こして」「あとで」 にする。\n"
        "本人が「起こして」 と答えたら、 その turn で start_session に proposal_id だけを渡して全部起こす。 "
        "既に点呼の行を書いてあって数が違うだけなら、 この行の数に直す (押された card は app の記録で外してある)。\n"
        "正本 = claude-config/conventions/multi-session-coordination.md#pending-card-rollcall"
    )


def stop_main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return 0
    path = payload.get("transcript_path")
    if not path or not os.path.isfile(path):
        return 0
    try:
        # card を 1 枚も出していない session (ほぼ全部) は JSON を読まずに戻る (毎 turn の費用を文字列の検索 1 回にする)
        with open(path, encoding="utf-8", errors="replace") as fh:
            if "(task_id: task_" not in fh.read():
                return 0
        entries = pc.load_entries(path)
        final = _final_text(entries)
        if not final.strip():
            return 0
        unseen = pc.unseen_pending(entries)
        if not unseen or pc.has_rollcall(final, len(unseen)):
            return 0
        print(json.dumps({"decision": "block", "reason": reason_for(unseen)}, ensure_ascii=False))
    except Exception:
        return 0
    return 0


def session_main(arg: str) -> int:
    path = arg if os.path.isfile(arg) else pc.find_transcript(arg)
    if not path:
        print(json.dumps({"error": "transcript not found", "session": arg}, ensure_ascii=False))
        return 1
    entries = pc.load_entries(path)
    cs = pc.cards(entries)
    out = {"transcript": path, "cards": cs,
           "unseen": [c["task_id"] for c in pc.unseen_pending(entries)],
           "pending_request_ids": sorted(pc.pending_request_ids(entries))}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def replay_main(path: str) -> int:
    entries = pc.load_entries(path)
    starters = pc.starter_rows(entries)
    owners = set(pc.owner_rows(entries))
    bounds = starters[1:] + [len(entries)]
    due_n = miss_n = 0
    print("時刻(UTC)  始め    点呼の要る card  最終発話に点呼  止める")
    for s, end in zip(starters, bounds):
        part = entries[:end]
        # その turn の最後の返事の時刻 = Stop hook が走る時点 (後ろに付く記録の行の時刻は使わない =
        # 返事を読んでから押された card を、 返事の時点で押されていたと数えてしまう)
        said = [pc._ts(e) for e in entries[s:end] if e.get("type") == "assistant"]
        t_end = (max(said) if said else 0.0) or None
        unseen = pc.unseen_pending(part, now=t_end, app_until=t_end)
        final = _final_text(part)
        if not unseen:
            continue
        has = pc.has_rollcall(final, len(unseen))
        block = bool(final.strip()) and not has
        due_n += 1
        miss_n += block
        ts = (entries[s].get("timestamp") or "")[11:19]
        kind = "本人" if s in owners else "自動"
        print(f"{ts}  {kind}    {len(unseen)} ({'・'.join(c['name'][:12] for c in unseen)})  "
              f"{'有' if has else '無'}  {'止める' if block else '-'}")
    print(f"点呼の要る turn = {due_n} / 止める turn = {miss_n}")
    return 0


# ---- selftest ---------------------------------------------------------------------------------------------------

def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


class _T:
    """合成の会話記録を組む。"""

    def __init__(self, t0: float):
        self.t = t0
        self.rows: list[dict] = []
        self.n = 0

    def _tick(self) -> str:
        self.t += 30
        return _iso(self.t)

    def human(self, text: str):
        self.rows.append({"type": "user", "timestamp": self._tick(), "origin": {"kind": "human"},
                          "message": {"role": "user", "content": text}})

    def event(self, text: str = "<task-notification>done</task-notification>"):
        self.rows.append({"type": "user", "timestamp": self._tick(), "origin": {"kind": "task-notification"},
                          "message": {"role": "user", "content": text}})

    def note(self, text: str):
        self.rows.append({"type": "user", "timestamp": self._tick(),
                          "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def stop_feedback(self):
        self.rows.append({"type": "user", "timestamp": self._tick(), "isMeta": True,
                          "message": {"role": "user", "content": "Stop hook feedback: x"}})

    def tool(self, name: str, inp: dict, result: str):
        self.n += 1
        tid = f"toolu_{self.n:04d}"
        self.rows.append({"type": "assistant", "timestamp": self._tick(),
                          "message": {"role": "assistant", "content": [
                              {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        self.rows.append({"type": "user", "timestamp": self._tick(),
                          "message": {"role": "user", "content": [
                              {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": result}]}]}})

    def card(self, task: str, title: str, request: str | None = None):
        prompt = f"You are the board worker for role `role-x`, request `{request}`, spec" if request else "do it"
        self.tool("mcp__ccd_session__start_session", {"initiation": "own_initiative", "title": title, "prompt": prompt},
                  f'Proposed "{title}" (task_id: {task}). The user sees a card and nothing runs until they start it.')

    def say(self, text: str):
        self.rows.append({"type": "assistant", "timestamp": self._tick(),
                          "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})

    def write(self, d: str) -> str:
        p = os.path.join(d, f"t{len(self.rows)}_{self.n}.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            for r in self.rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p


def _run_stop(path: str, active: bool = False) -> str:
    import io
    import contextlib
    old = sys.stdin
    sys.stdin = io.StringIO(json.dumps({"transcript_path": path, "stop_hook_active": active}))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            stop_main()
    finally:
        sys.stdin = old
    return buf.getvalue()


def selftest() -> int:
    fails = 0
    now = time.time()

    def check(name: str, ok: bool):
        nonlocal fails
        print(("ok   " if ok else "FAIL ") + name)
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        os.environ["CLAUDE_DESKTOP_SESSIONS_DIR"] = os.path.join(d, "app")
        os.makedirs(os.path.join(d, "app", "acct", "env"))
        board = os.path.join(d, "board")
        os.environ["PENDING_CARDS_BOARD_ROOTS"] = board
        line_mark = pc.ROLLCALL_MARK

        # 1. 鳴る: 自動の turn で card を出し、 点呼の行が無い
        t = _T(now - 3600)
        t.event()
        t.card("task_aaa1", "[local推奨] [model: opus xhigh] 検収係の RCA", "20990101T000001Z-claude-aaaa01")
        t.say("card を出しました。")
        out = _run_stop(t.write(d))
        check("自動の turn・点呼なし → 止める", '"block"' in out and "1 枚: 検収係の RCA" in out)

        # 2. 黙る: 点呼の行が在る
        t.say(f"card を出しました。\n{line_mark} 1 枚: 検収係の RCA — 押すか「起こして」 の一言で全部起こします")
        check("点呼の行が在る → 黙る", _run_stop(t.write(d)) == "")

        # 3. 鳴る: 数が違う (2 枚目を出した)
        t.event()
        t.card("task_aaa2", "[local推奨] [model: opus xhigh] 数式の件", None)
        t.say(f"{line_mark} 1 枚: 検収係の RCA")
        out = _run_stop(t.write(d))
        check("点呼の数が古い → 止める (2 枚)", '"block"' in out and "2 枚" in out)

        # 4. 黙る: stop_hook_active
        check("stop_hook_active → 黙る", _run_stop(t.write(d), active=True) == "")

        # 5. 鳴る: 本人の最初の turn への返事 (最後の点呼)
        t.human("どういう意味？")
        t.say("説明です。")
        check("本人の最初の turn の返事 → 止める", '"block"' in _run_stop(t.write(d)))

        # 6. 黙る: 本人の turn が終わった後の自動の turn (見送り = 繰り返さない)
        t.say(f"説明です。\n{line_mark} 2 枚: 検収係の RCA・数式の件")
        t.event()
        t.say("見張りが拾いました。")
        check("本人が見た後の自動の turn → 黙る", _run_stop(t.write(d)) == "")

        # 7. 鳴る: 見送りの後に新しい card → 新しい card だけを数える
        t.event()
        t.card("task_aaa3", "[local推奨] [model: opus xhigh] 道具の直し", "20990101T000003Z-claude-aaaa03")
        t.say("card を出しました。")
        out = _run_stop(t.write(d))
        check("見送りの後の新しい card → その 1 枚だけで止める", '"block"' in out and "1 枚: 道具の直し" in out)

        # 8. 黙る: 本人が「あとで」 と答えた turn
        t.say(f"{line_mark} 1 枚: 道具の直し")
        t.human("<system-reminder>x</system-reminder>\nあとで")
        t.say("分かりました。")
        check("本人の「あとで」 → 黙る", _run_stop(t.write(d)) == "")

        # 9. 黙る: 押された (会話記録の知らせ)
        t2 = _T(now - 3600)
        t2.event()
        t2.card("task_bbb1", "[local推奨] 返事の記録", None)
        t2.say("card を出しました。")
        t2.note("<system-reminder>\nThe user started your proposal task_bbb1 (\"x\") as session local_1.\n</system-reminder>")
        t2.say("押されました。")
        check("「started your proposal」 の知らせ → 黙る", _run_stop(t2.write(d)) == "")

        # 10. 黙る: proposal_id を渡して起こした
        t3 = _T(now - 3600)
        t3.event()
        t3.card("task_ccc1", "[local推奨] 返事の記録", None)
        t3.human("起こして")
        t3.tool("mcp__ccd_session__start_session", {"proposal_id": "task_ccc1"}, 'Started session "x" (session_id: local_2).')
        t3.say("起こしました。")
        check("proposal_id で起こした → 黙る", _run_stop(t3.write(d)) == "")

        # 11. 黙る: app の記録に card から起きた session がある
        t4 = _T(now - 3600)
        t4.event()
        t4.card("task_ddd1", "[local推奨] 検収係", None)
        t4.say("card を出しました。")
        p4 = t4.write(d)
        with open(os.path.join(d, "app", "acct", "env", "local_9.json"), "w") as fh:
            json.dump({"sessionId": "local_9", "createdAt": int(now * 1000),
                       "spawnedFrom": {"sessionId": "local_p", "taskId": "task_ddd1", "sideSession": True}}, fh)
        check("app の記録の spawnedFrom.taskId → 黙る", _run_stop(p4) == "")
        check("流し直しでは、 その turn の後にできた記録は数えない",
              len(pc.unseen_pending(pc.load_entries(p4), now=now - 3000, app_until=now - 3000)) == 1)

        # 12. 黙る: 取り下げ / 期限切れ
        t5 = _T(now - 3600)
        t5.event()
        t5.card("task_eee1", "[local推奨] 取り下げる", None)
        t5.tool("mcp__ccd_session__dismiss_task", {"task_id": "task_eee1"},
                "Task task_eee1 withdrawn — the chip is no longer shown to the user.")
        t5.say("取り下げました。")
        check("dismiss_task の withdrawn → 黙る", _run_stop(t5.write(d)) == "")
        t6 = _T(now - 8 * 86400)
        t6.event()
        t6.card("task_fff1", "[local推奨] 古い", None)
        t6.say("card を出しました。")
        check("7 日を過ぎた card → 黙る", _run_stop(t6.write(d)) == "")

        # 13. 掲示板の request id (見張りが拾い直さない依頼)
        ids = pc.pending_request_ids(pc.load_entries(t.write(d)))
        check("押されていない card の request id を引く (押された・見送りも含む押されていない分)",
              ids == {"20990101T000001Z-claude-aaaa01", "20990101T000003Z-claude-aaaa03"})

        # 13b. 掲示板で別の窓が引き受けた依頼の card は数えない / release の後は戻る
        tb = _T(now - 3600)
        tb.event()
        tb.card("task_jjj1", "[local推奨] 別の窓が引き受けた", "20990101T000009Z-claude-aaaa09")
        tb.say("card を出しました。")
        pb = tb.write(d)
        th = os.path.join(board, "events", "proj", "2099-01-01-x")
        os.makedirs(th)

        def ev(eid: str, kind: str, at: float):
            with open(os.path.join(th, f"{eid[:16]}--{eid}.json"), "w") as fh:
                json.dump({"event_id": eid, "kind": kind, "request_id": "20990101T000009Z-claude-aaaa09",
                           "created_at": _iso(at)}, fh)
        with open(os.path.join(th, "20990101T000009Z--20990101T000009Z-claude-aaaa09.json"), "w") as fh:
            json.dump({"event_id": "20990101T000009Z-claude-aaaa09", "kind": "request"}, fh)
        check("掲示板に引き受けが無い → 止める", '"block"' in _run_stop(pb))
        ev("20990101T000010Z-claude-bbbb10", "claim", now - 60)
        check("掲示板で引き受け済み → 黙る", _run_stop(pb) == "")
        ev("20990101T000011Z-claude-bbbb11", "release", now - 30)
        check("引き受けの後の release → また止める", '"block"' in _run_stop(pb))

        # 14. origin の無い古い記録: isMeta でなく自動の書き出しで始まらない行を本人の turn と見る
        t7 = _T(now - 3600)
        t7.rows.append({"type": "user", "timestamp": t7._tick(),
                        "message": {"role": "user", "content": "Background (from the session that started this one): x"}})
        t7.card("task_ggg1", "[local推奨] 古い形", None)
        t7.say("card を出しました。")
        t7.rows.append({"type": "user", "timestamp": t7._tick(), "message": {"role": "user", "content": "ok"}})
        t7.say("はい。")
        t7.rows.append({"type": "user", "timestamp": t7._tick(),
                        "message": {"role": "user", "content": "<task-notification>x</task-notification>"}})
        t7.say("見張りです。")
        check("origin の無い記録で本人の turn を見分ける → 見送り後は黙る", _run_stop(t7.write(d)) == "")

        # 15. 最終発話が空 (tool だけの turn) は黙る
        t8 = _T(now - 3600)
        t8.event()
        t8.card("task_hhh1", "[local推奨] 空", None)
        check("最終発話の無い turn → 黙る", _run_stop(t8.write(d)) == "")

        # 16. Stop hook の差し戻しは turn の始めに数えない (本人の turn の扱いを変えない)
        t9 = _T(now - 3600)
        t9.event()
        t9.card("task_iii1", "[local推奨] 差し戻し", None)
        t9.say("card を出しました。")
        t9.stop_feedback()
        t9.say("追記です。")
        check("Stop hook の差し戻しの後の追記 → 点呼が無ければ止める", '"block"' in _run_stop(t9.write(d)))

    print(f"{'PASS' if fails == 0 else 'FAIL'} ({fails} fail)")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--stop":
        return stop_main()
    if argv[0] == "--session" and len(argv) > 1:
        return session_main(argv[1])
    if argv[0] == "--replay" and len(argv) > 1:
        return replay_main(argv[1])
    if argv[0] == "--selftest":
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
