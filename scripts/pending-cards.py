#!/usr/bin/env python3
"""pending-cards.py — この session が出した card のうち押されていないものを、 turn の終わりごとに取り下げて一番下に出し直させ、 最新の返事に点呼の 1 行を書かせる (Stop hook の本体)。 見張りが card を出した依頼を拾い直さないための照会と、 過去の会話記録での流し直しも持つ

正本 = conventions/multi-session-coordination.md#pending-card-rollcall。 述語 = scripts/lib/pending_cards.py。

使い方:
  --stop              Stop hook の本体 (stdin = hook の payload)。 次のどれかが成り立てば、 直し方を添えて止める (decision=block):
                        - 押されていない card (同じ依頼の出し直しは 1 本に結ぶ) が前の turn に出たまま = 取り下げて一番下に出し直す
                        - 押されていない card があるのに、 今の turn の最終発話に点呼の行 (「🃏 押されていない card N 枚」) が無い
                        - 同じ依頼の card が押された後に出た card が残っている (押すと 2 人目の worker になる) = 取り下げる
                      出し直しの指示を出した後の Stop (stop_hook_active) では、 名指した card を取り下げたまま出し直して
                      いない形だけを見る (同じ turn に 2 回まで)。 最終発話が空・読めない記録・例外は黙る (fail-open)。
                      出し直す card の元の入力は env PENDING_CARDS_STATE_DIR (既定 ~/.claude/state/pending-cards) の
                      <session>/<task_id>.json に写す (会話が圧縮されて元の呼び出しが context に無いときに読む)。
  --session ID        その session の card の一覧・依頼の鎖・押されていない card が名指す掲示板の request id を JSON で出す
                      (見張りが拾い直さない依頼を引く)。 ID = 会話記録の id (頭 8 字以上) か transcript の path。
  --replay PATH       会話記録の turn ごとに、 その時点で点呼の要る card・出し直す card・最終発話の点呼の有無を並べる
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

RULE = "claude-config/conventions/multi-session-coordination.md#pending-card-rollcall"
MAX_REISSUE_FEEDBACK = 2  # 同じ turn に出す出し直しの差し戻しの上限 (止め続けの輪を作らない)
COPY_KEYS = ("initiation", "title", "prompt", "background", "context", "model", "effort", "name", "use_worktree")


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


def _maybe_check_dismiss_replies() -> None:
    """app の版か返事の読み分けの file が前に確かめた時と違えば、 返事の表の照合 (scripts/check-dismiss-replies.py) を
    背景で起こす (待たない。 外れは digest の ⚙️ の段に出る)。 毎 turn の費用 = Info.plist と 2 file を読むだけ。
    文は app の版で変わり、 読み分けが黙って外れた (実測)。 env PENDING_CARDS_NO_REPLY_CHECK=1 で起こさない (試験)。"""
    if os.environ.get("PENDING_CARDS_NO_REPLY_CHECK"):
        return
    try:
        import importlib.util
        import subprocess
        chk = os.path.join(os.path.dirname(os.path.realpath(__file__)), "check-dismiss-replies.py")
        spec = importlib.util.spec_from_file_location("check_dismiss_replies", chk)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if mod.needs_check():
            subprocess.Popen([sys.executable, chk, "--if-changed"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass


def _state_dir() -> str:
    return os.environ.get("PENDING_CARDS_STATE_DIR") or os.path.expanduser("~/.claude/state/pending-cards")


def save_inputs(session: str, cs: list[dict]) -> dict[str, str]:
    """出し直す card の元の入力を写す。 → {task_id: path}。 書けなければ空 (理由の文から写しの path を外すだけ)。"""
    out: dict[str, str] = {}
    sid = "".join(ch for ch in (session or "unknown") if ch.isalnum() or ch in "-_")[:64] or "unknown"
    d = os.path.join(_state_dir(), sid)
    for c in cs:
        inp = {k: v for k, v in (c.get("input") or {}).items() if k in COPY_KEYS}
        inp["initiation"] = "own_initiative"
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, c["task_id"] + ".json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(inp, fh, ensure_ascii=False, indent=1)
            out[c["task_id"]] = p
        except OSError:
            continue
    return out


def _card_list(cs: list[dict], copies: dict[str, str] | None = None) -> str:
    parts = []
    for c in cs:
        s = f"{c['task_id']} (「{c['name']}」"
        if copies and copies.get(c["task_id"]):
            s += f"、 元の入力の写し = {copies[c['task_id']]}"
        parts.append(s + ")")
    return "、 ".join(parts)


def _box_text(n: int) -> str:
    # 1 枚のときに「1 枚とも」 は日本語にならない = ボタンは「起こして」、 2 枚以上は「N 枚とも起こして」
    button = "起こして" if n == 1 else str(n) + " 枚とも起こして"
    start = "その card を起こす" if n == 1 else "全部起こす"
    return ("締めの箱を出すなら、 要約の 1 文目を「押されていない card が " + str(n) + " 枚あります」 にし、 問いが空いていれば"
            "「待っている card " + str(n) + " 枚を起こしますか？」 + ボタン「" + button + "」「あとで」 にする。 "
            "本人が「起こして」 と答えたら、 その turn で start_session に proposal_id だけを渡して" + start + "。")


def reason_for(active: list[dict], due: list[dict], second: list[dict], need_line: bool,
               copies: dict[str, str] | None = None) -> str:
    n = len(active)
    out = []
    if due:
        withdraw = [c for ch in due for c in pc.to_withdraw(ch)]
        latest = [ch["latest"] for ch in due]
        out.append(
            f"{pc.REISSUE_HEAD}: 前の turn に出した押されていない card が {len(due)} 枚あり、 返事の上に流れています。\n"
            f"1. この応答では dismiss_task だけを出す (並べてよい): {_card_list(withdraw)}\n"
            "2. 結果を読んでから、 次の応答で:\n"
            "   - 「withdrawn」 が返った依頼は、 元と同じ入力で start_session を 1 枚ずつ出し直す (initiation = own_initiative。 "
            "title・prompt・background・context・model・effort・name・use_worktree を変えない。 元の呼び出しが context に無ければ写しを Read する): "
            f"{_card_list(latest, copies)}\n"
            "   - 押されていた・起動の途中の返事 (「is no longer pending」「is being started right now」、 旧い app では「already started」「has just clicked Start」) が返った依頼は出し直さない (本人が押した = worker が起きている)。\n"
            "   - 「had already left the queue」 (本人が閉じた・新しい card に押し出された、 旧い app では「already dismissed」)・「No pending task」 (app に card が無い)・「already expired」 (app で期限切れ) が返った依頼も出し直さない。\n"
            "   - 「Not withdrawn: … edited …」 (本人が文を編集した) が返った依頼は出し直さず、 card の上で押すか閉じるよう本人に頼む。\n"
            "   取り下げと出し直しを同じ応答に並べない (結果を読む前に出し直すと、 本人がその間に押した card と 2 人目の worker になる)。")
    if second:
        out.append(
            "⚠️ 同じ依頼の card が押された後に出た card が残っています (押すと同じ依頼の 2 人目の worker になる)。 "
            f"dismiss_task で取り下げ、 出し直さない: {_card_list(second)}")
    edited = [ch["latest"] for ch in active if ch["status"] == "edited"]
    if edited and (need_line or due):
        out.append(
            "本人が文を編集した card は、 取り下げも出し直しもしない (その card だけが本人の書いた文で起こせる = app の返事)。 "
            f"返事で、 card の上で Start を押すか、 要らなければ閉じるよう本人に頼む: {_card_list(edited)}")
    if n and (need_line or due):
        out.append("返事の終わりに次の 1 行をそのまま足す (本文は出し直さない。 既に点呼の行があって数が違うだけなら、 この行の数に直す):\n"
                   f"  {pc.rollcall_line(active)}\n" + _box_text(n))
    out.append(f"正本 = {RULE}")
    return "\n".join(out)


def reason_dropped(dropped: list[dict], copies: dict[str, str] | None = None) -> str:
    return (f"{pc.REISSUE_HEAD} (続き): 取り下げた card を出し直していません: {_card_list([ch['latest'] for ch in dropped], copies)}。\n"
            "元と同じ入力で start_session を出す (initiation = own_initiative。 元の呼び出しが context に無ければ写しを Read する)。 "
            "本人の指示などでわざと取り下げたのなら、 そのままでよい (この知らせは同じ turn に 2 回までしか出ない)。\n"
            f"正本 = {RULE}")


def evaluate(entries: list[dict], now: float | None = None, app_until: float | None = None,
             stop_hook_active: bool = False) -> dict:
    """turn の終わりの判定。 → {active, due, second, need_line, dropped, block}。"""
    chs = pc.chains(entries, now=now, app_until=app_until)
    active = pc.active_chains(chs)
    res = {"active": active, "due": [], "second": [], "need_line": False, "dropped": [], "block": False}
    if stop_hook_active:
        start = pc.current_turn_start(entries)
        if len(pc.reissue_feedback_rows(entries, start)) <= MAX_REISSUE_FEEDBACK:
            res["dropped"] = pc.dropped_chains(entries, chs, now=now)
        res["block"] = bool(res["dropped"])
        return res
    final = _final_text(entries)
    if not final.strip():
        return res
    res["due"] = pc.reissue_due(entries, chs)
    res["second"] = pc.second_worker_cards(chs, now=now)
    res["need_line"] = bool(active) and not pc.has_rollcall(final, len(active))
    res["block"] = bool(res["due"] or res["second"] or res["need_line"])
    return res


def stop_main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    _maybe_check_dismiss_replies()
    path = payload.get("transcript_path")
    if not path or not os.path.isfile(path):
        return 0
    try:
        # card を 1 枚も出していない session (ほぼ全部) は JSON を読まずに戻る (毎 turn の費用を文字列の検索 1 回にする)
        with open(path, encoding="utf-8", errors="replace") as fh:
            if "(task_id: task_" not in fh.read():
                return 0
        entries = pc.load_entries(path)
        active_flag = bool(payload.get("stop_hook_active"))
        r = evaluate(entries, stop_hook_active=active_flag)
        if not r["block"]:
            return 0
        session = payload.get("session_id") or os.path.splitext(os.path.basename(path))[0]
        if r["dropped"]:
            copies = save_inputs(session, [ch["latest"] for ch in r["dropped"]])
            reason = reason_dropped(r["dropped"], copies)
        else:
            copies = save_inputs(session, [ch["latest"] for ch in r["due"]])
            reason = reason_for(r["active"], r["due"], r["second"], r["need_line"], copies)
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
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
    chs = pc.chains(entries, cs=cs)
    out = {"transcript": path,
           "cards": [{k: v for k, v in c.items() if k != "input"} for c in cs],
           "chains": [{"key": ch["key"], "name": ch["name"], "status": ch["status"],
                       "cards": [c["task_id"] for c in ch["cards"]]} for ch in chs],
           "active": [ch["latest"]["task_id"] for ch in pc.active_chains(chs)],
           "reissue_due": [ch["latest"]["task_id"] for ch in pc.reissue_due(entries, chs)],
           "pending_request_ids": sorted(pc.pending_request_ids(entries))}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def replay_main(path: str) -> int:
    entries = pc.load_entries(path)
    starters = pc.starter_rows(entries)
    owners = set(pc.owner_rows(entries))
    bounds = starters[1:] + [len(entries)]
    due_n = block_n = reissue_n = 0
    print("時刻(UTC)  始め    点呼の要る card  出し直す  最終発話に点呼  止める")
    for s, end in zip(starters, bounds):
        part = entries[:end]
        # その turn の最後の返事の時刻 = Stop hook が走る時点 (後ろに付く記録の行の時刻は使わない =
        # 返事を読んでから押された card を、 返事の時点で押されていたと数えてしまう)
        said = [pc._ts(e) for e in entries[s:end] if e.get("type") == "assistant"]
        t_end = (max(said) if said else 0.0) or None
        r = evaluate(part, now=t_end, app_until=t_end)
        if not r["active"] and not r["second"]:
            continue
        has = not r["need_line"]
        due_n += 1
        block_n += r["block"]
        reissue_n += bool(r["due"])
        ts = (entries[s].get("timestamp") or "")[11:19]
        kind = "本人" if s in owners else "自動"
        names = "・".join(ch["name"][:12] for ch in r["active"])
        print(f"{ts}  {kind}    {len(r['active'])} ({names})  {len(r['due'])}  "
              f"{'有' if has else '無'}  {'止める' if r['block'] else '-'}")
    print(f"点呼の要る turn = {due_n} / 出し直しの要る turn = {reissue_n} / 止める turn = {block_n}")
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

    def feedback(self, text: str = "x"):
        self.rows.append({"type": "user", "timestamp": self._tick(), "isMeta": True,
                          "message": {"role": "user", "content": "Stop hook feedback:\n" + text}})

    def tool(self, name: str, inp: dict, result: str, is_error: bool = False, stamp=()):
        """stamp = 結果の行の構造化した値 (mcpMeta._meta.ccdToolStamp.outcome、 None = null)。 既定 () = 載せない。"""
        self.n += 1
        tid = f"toolu_{self.n:04d}"
        self.rows.append({"type": "assistant", "timestamp": self._tick(),
                          "message": {"role": "assistant", "content": [
                              {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        res = {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": result}]}
        if is_error:
            res["is_error"] = True
        row = {"type": "user", "timestamp": self._tick(), "message": {"role": "user", "content": [res]}}
        if stamp != ():
            row["mcpMeta"] = {"_meta": {"ccdToolStamp": {"outcome": stamp}}}
        self.rows.append(row)

    def parallel(self, calls: list[tuple[str, dict, str, bool]]):
        """1 つの応答に並べた呼び出し (tool_use を全部出してから結果が並ぶ)。"""
        ids = []
        for name, inp, _res, _err in calls:
            self.n += 1
            tid = f"toolu_{self.n:04d}"
            ids.append(tid)
            self.rows.append({"type": "assistant", "timestamp": self._tick(),
                              "message": {"role": "assistant", "content": [
                                  {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        for tid, (_name, _inp, result, err) in zip(ids, calls):
            res = {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": result}]}
            if err:
                res["is_error"] = True
            self.rows.append({"type": "user", "timestamp": self._tick(), "message": {"role": "user", "content": [res]}})

    @staticmethod
    def card_input(title: str, request: str | None = None) -> dict:
        prompt = f"You are the board worker for role `role-x`, request `{request}`, spec" if request else "do it"
        return {"initiation": "own_initiative", "title": title, "prompt": prompt, "background": "bg", "context": "fresh",
                "model": "opus", "effort": "xhigh", "name": "x", "use_worktree": False}

    def card(self, task: str, title: str, request: str | None = None):
        self.tool("mcp__ccd_session__start_session", self.card_input(title, request),
                  f'Proposed "{title}" (task_id: {task}). The user sees a card and nothing runs until they start it.')

    def dismiss(self, task: str, started: bool = False):
        # 押されていた返事 = 今の app の文 (旧い文 = 「Task … was already started by the user …」 は (b) の形で試す)
        res = (f"Task {task} is no longer pending, so there is nothing to withdraw: it was started in its own session, "
               "or the user sent it to this one, which starts none." if started
               else f"Task {task} withdrawn — the chip is no longer shown to the user.")
        self.tool("mcp__ccd_session__dismiss_task", {"task_id": task}, res)

    def say(self, text: str):
        self.rows.append({"type": "assistant", "timestamp": self._tick(),
                          "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})

    def write(self, d: str) -> str:
        p = os.path.join(d, f"t{len(self.rows)}_{self.n}_{id(self)}.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            for r in self.rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p


def _run_stop(path: str, active: bool = False) -> str:
    import io
    import contextlib
    old = sys.stdin
    sys.stdin = io.StringIO(json.dumps({"transcript_path": path, "stop_hook_active": active, "session_id": "selftest"}))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            stop_main()
    finally:
        sys.stdin = old
    return buf.getvalue()


def _reason(out: str) -> str:
    try:
        return json.loads(out)["reason"]
    except Exception:
        return ""


def selftest() -> int:
    fails = 0
    now = time.time()
    os.environ["PENDING_CARDS_NO_REPLY_CHECK"] = "1"   # 試験の Stop から本物の app の照合を起こさない

    def check(name: str, ok: bool):
        nonlocal fails
        print(("ok   " if ok else "FAIL ") + name)
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        os.environ["CLAUDE_DESKTOP_SESSIONS_DIR"] = os.path.join(d, "app")
        os.makedirs(os.path.join(d, "app", "acct", "env"))
        board = os.path.join(d, "board")
        os.environ["PENDING_CARDS_BOARD_ROOTS"] = board
        os.environ["PENDING_CARDS_STATE_DIR"] = os.path.join(d, "state")
        mark = pc.ROLLCALL_MARK
        R1, R3 = "20990101T000001Z-claude-aaaa01", "20990101T000003Z-claude-aaaa03"

        # ---- 点呼の行 (今の turn に出した card) ----
        t = _T(now - 3600)
        t.event()
        t.card("task_aaa1", "[local推奨] [model: opus xhigh] 検収係の RCA", R1)
        t.say("card を出しました。")
        out = _run_stop(t.write(d))
        rs = _reason(out)
        check("今の turn の card・点呼なし → 止める (点呼の行だけ、 出し直しは無し)",
              '"block"' in out and "1 枚: 検収係の RCA" in rs and pc.REISSUE_HEAD not in rs)
        check("card 1 枚の止める文: ボタンは「起こして」 (「1 枚とも」 と言わない)、 点呼の行は「全部」 と言わない",
              "ボタン「起こして」「あとで」" in rs and "1 枚とも" not in rs and "全部起こします" not in rs
              and "の一言で起こします" in rs)
        two = [{"name": "甲の仕事"}, {"name": "乙の仕事"}]
        check("card 2 枚の文: ボタンは「2 枚とも起こして」、 点呼の行は「全部起こします」",
              "ボタン「2 枚とも起こして」「あとで」" in _box_text(2) and "全部起こす" in _box_text(2)
              and pc.rollcall_line(two).endswith("の一言で全部起こします"))
        check("点呼の行の検出は文の末尾の言い方に依らない (1 枚の新しい形も 2 枚の形も見つける)",
              pc.has_rollcall(pc.rollcall_line([{"name": "甲の仕事"}]), 1) and pc.has_rollcall(pc.rollcall_line(two), 2)
              and not pc.has_rollcall(pc.rollcall_line(two), 1))
        t.say(f"card を出しました。\n{mark} 1 枚: 検収係の RCA — 押すか「起こして」 の一言で起こします")
        check("今の turn の card・点呼あり → 黙る (出し直しの要らない形)", _run_stop(t.write(d)) == "")
        check("stop_hook_active (出し直しの指示の後でない) → 黙る", _run_stop(t.write(d), active=True) == "")

        # ---- 出し直し (前の turn に出した card) ----
        t.event()
        t.say(f"見張りが拾いました。\n{mark} 1 枚: 検収係の RCA")
        out = _run_stop(t.write(d))
        rs = _reason(out)
        copy = os.path.join(d, "state", "selftest", "task_aaa1.json")
        check("前の turn の card → 点呼の行があっても止めて出し直させる",
              '"block"' in out and pc.REISSUE_HEAD in rs and "task_aaa1" in rs and "dismiss_task" in rs)
        check("出し直しの指示は取り下げと出し直しを別の応答に分けさせる", "同じ応答に並べない" in rs)
        try:
            with open(copy, encoding="utf-8") as fh:
                cp = json.load(fh)
        except (OSError, ValueError):
            cp = {}
        check("元の入力の写しを書く (initiation = own_initiative、 title・prompt・background が元のまま)",
              cp.get("initiation") == "own_initiative" and cp.get("title", "").endswith("検収係の RCA")
              and R1 in cp.get("prompt", "") and cp.get("background") == "bg" and copy in rs)

        # 取り下げ → 結果を読んで → 出し直し → 点呼
        t.feedback(rs)
        t.dismiss("task_aaa1")
        t.card("task_aaa1b", "[local推奨] [model: opus xhigh] 検収係の RCA", R1)
        t.say(f"出し直しました。\n{mark} 1 枚: 検収係の RCA")
        p = p_reissued = t.write(d)
        check("出し直した後 (stop_hook_active) → 黙る", _run_stop(p, active=True) == "")
        chs = pc.chains(pc.load_entries(p))
        check("出し直した card は同じ依頼の続き (鎖 1 本・card 2 枚・最初の card を起点)",
              len(chs) == 1 and [c["task_id"] for c in chs[0]["cards"]] == ["task_aaa1", "task_aaa1b"]
              and chs[0]["status"] == "pending" and chs[0]["origin_ts"] == chs[0]["cards"][0]["ts"])

        # 本人の turn でも (見たかに依らず) 出し直す = 本人の裁定
        t.human("ほかの件だけど、 あれどうなった？")
        t.say(f"説明です。\n{mark} 1 枚: 検収係の RCA")
        rs = _reason(_run_stop(t.write(d)))
        check("本人の turn の終わりでも前の turn の card は出し直す", "task_aaa1b" in rs and pc.REISSUE_HEAD in rs)

        # 取り下げたまま出し直さない → 続きの Stop で 1 回知らせる (2 回まで)
        t.feedback(rs)
        t.dismiss("task_aaa1b")
        t.say(f"取り下げました。\n{mark} 1 枚: 検収係の RCA")
        p = t.write(d)
        rs = _reason(_run_stop(p, active=True))
        check("名指した card を取り下げたまま (stop_hook_active) → 出し直しを求める", "出し直していません" in rs and "task_aaa1b" in rs)
        t.feedback(rs)
        t.feedback(rs)
        t.say("わざと取り下げました。")
        check("出し直しの差し戻しが同じ turn に 3 回目になる → 黙る (止め続けない)", _run_stop(t.write(d), active=True) == "")

        # わざと取り下げた (差し戻しが名指していない) card は数えない
        tw = _T(now - 3600)
        tw.event()
        tw.card("task_www1", "[local推奨] 取り下げる", None)
        tw.dismiss("task_www1")
        tw.say("取り下げました。")
        pw = tw.write(d)
        check("自分で取り下げた card → 黙る (通常の Stop と stop_hook_active の両方)",
              _run_stop(pw) == "" and _run_stop(pw, active=True) == "")

        # 取り下げの結果を読む前に出し直す形 (a) = 二重起動の guard が止めて card が出ない → 取り下げたまま扱い
        ta = _T(now - 3600)
        ta.event()
        ta.card("task_rrr1", "[local推奨] 並べた形", None)
        ta.say(f"{mark} 1 枚: 並べた形")
        ta.event()
        ta.say("見張り。")
        rs = _reason(_run_stop(ta.write(d)))
        ta.feedback(rs)
        ta.parallel([("mcp__ccd_session__dismiss_task", {"task_id": "task_rrr1"},
                      "Task task_rrr1 withdrawn — the chip is no longer shown to the user.", False),
                     ("mcp__ccd_session__start_session", _T.card_input("[local推奨] 並べた形"),
                      "PreToolUse:mcp__ccd_session__start_session hook error: 🛑 spawn-dedupe-guard: 同じ依頼の worker を 2 つ起動させる chip なので止めた。",
                      True)])
        ta.say(f"{mark} 1 枚: 並べた形")
        rs2 = _reason(_run_stop(ta.write(d), active=True))
        check("取り下げと出し直しを並べ、 出し直しが止められた → 出し直しを求める", "出し直していません" in rs2 and "task_rrr1" in rs2)

        # (b) = guard の無い所で並べ、 その間に本人が押した (取り下げが already started) → 後の card を取り下げさせる
        tb = _T(now - 3600)
        tb.event()
        tb.card("task_sss1", "[local推奨] 押された形", R3)
        tb.say(f"{mark} 1 枚: 押された形")
        tb.event()
        tb.parallel([("mcp__ccd_session__dismiss_task", {"task_id": "task_sss1"},
                      "Task task_sss1 was already started by the user — it's no longer pending and can't be withdrawn.", False),
                     ("mcp__ccd_session__start_session", _T.card_input("[local推奨] 押された形", R3),
                      'Proposed "[local推奨] 押された形" (task_id: task_sss2). The user sees a card.', False)])
        tb.say("出し直しました。")
        rs = _reason(_run_stop(tb.write(d)))
        check("押された後に出た同じ依頼の card → 取り下げさせ、 出し直させない",
              "2 人目" in rs and "task_sss2" in rs and pc.REISSUE_HEAD not in rs)
        # その 2 枚目を取り下げたら「had already left the queue」 (本人が閉じていた) → もう押せないので取り下げを求め続けない
        tb.feedback(rs)
        tb.tool("mcp__ccd_session__dismiss_task", {"task_id": "task_sss2"},
                "Task task_sss2 had already left the queue (dismissed earlier, or displaced by newer suggestions); "
                "any copy kept for later is being withdrawn too. Do not re-flag it.")
        tb.say("閉じられていました。")
        tb.event()
        tb.say("次の turn。")
        check("2 人目になる card が閉じられていた返事 → 次の turn で取り下げを求めない",
              _run_stop(tb.write(d)) == "")

        # 今の app の文で押されていたと返る (「is no longer pending」) → 押された card として出し直さない
        tn2 = _T(now - 3600)
        tn2.event()
        tn2.card("task_npn1", "[local推奨] 今の文", None)
        tn2.say(f"{mark} 1 枚: 今の文")
        tn2.event()
        tn2.say("見張り。")
        tn2.feedback(_reason(_run_stop(tn2.write(d))))
        tn2.dismiss("task_npn1", started=True)
        tn2.say("押されていました。")
        pn2 = tn2.write(d)
        check("取り下げが今の文の「is no longer pending」 → 押された (取り下げたままの知らせも出ない)",
              _run_stop(pn2, active=True) == "" and pc.chains(pc.load_entries(pn2))[0]["status"] == "started")

        # dismiss_task の返事 (app 本体の表の文、 今の版と旧い版)。 期待 = 鎖の状態 / 次の turn で出し直しを求めるか
        forms = [
            ("already_dismissed (今の文)", "Task {t} had already left the queue (dismissed earlier, or displaced by newer "
             "suggestions); any copy kept for later is being withdrawn too. Do not re-flag it.", "closed"),
            ("expired", "Task {t} already expired unstarted, so it is no longer shown; any copy kept for later is being "
             "withdrawn too. Do not re-propose it.", "expired"),
            ("spawn_in_flight", "Task {t} is being started right now — it can't be withdrawn while the spawn is in "
             "flight. Nothing was changed.", "started"),
            ("withdrawn", "Task {t} withdrawn. The card is no longer shown to the user. Continue your current work.",
             "withdrawn"),
            ("already_started", "Task {t} is no longer pending, so there is nothing to withdraw: the user started it as a new "
             "session, or sent it to this one, which starts none.", "started"),
            ("already_started (旧い文)", "Task {t} was already started by the user — it's no longer pending and can't be "
             "withdrawn.", "started"),
            ("starting", "The user has just clicked Start on task {t}, so it is being launched and was not withdrawn; if that "
             "launch fails, your withdrawal is applied and the card is removed. Do not re-flag it.", "started"),
            ("edited_start", "Not withdrawn: the user edited the message of {t} and has just clicked Start on it, so it is being "
             "launched with what they wrote.", "started"),
            ("already_dismissed", "Task {t} was already dismissed. Nothing was changed.", "closed"),
            ("not_found", "No pending task with id {t}. Possible causes include it never being queued in this session. "
             "Do not re-flag it. Nothing was changed.", "closed"),
            ("edited", "Not withdrawn: the user edited the message of {t}, so only its card starts it, with what they wrote. "
             "Ask them to press Start there, or to dismiss it if they no longer want it.", "edited"),
        ]
        for k, (label, reply, want) in enumerate(forms):
            tid = f"task_form{k}"
            tf = _T(now - 3600)
            tf.event()
            tf.card(tid, f"[local推奨] 返事の形 {k}", None)
            tf.say(f"{mark} 1 枚: 返事の形 {k}")
            tf.event()
            tf.say("見張り。")
            tf.feedback(_reason(_run_stop(tf.write(d))))
            tf.tool("mcp__ccd_session__dismiss_task", {"task_id": tid}, reply.format(t=tid))
            tf.say(f"{mark} 1 枚: 返事の形 {k}")
            pf = tf.write(d)
            st = pc.chains(pc.load_entries(pf))[0]["status"]
            after = _run_stop(pf, active=True)
            tf.event()
            tf.say("次の turn。")
            nxt = _reason(_run_stop(tf.write(d)))
            if want == "withdrawn":
                ok = st == "withdrawn" and "出し直していません" in _reason(after)
            elif want == "edited":
                ok = (st == "edited" and after == "" and pc.REISSUE_HEAD not in nxt and "編集した" in nxt
                      and "1 枚: 返事の形" in nxt)
            else:
                ok = st == want and after == "" and nxt == ""
            check(f"取り下げの返事「{label}」 → {want}", ok)

        # 構造化した値 (mcpMeta の outcome) を先に読む: 文がどの読み分けにも当たらなくても分かれる。 期限切れだけは文で分ける。
        # 知らない値・値の無い行は文で読む (今までどおり)
        stamps = [
            ("did・知らない文", "did", "Task {t} went away.", "withdrawn"),
            ("not_done・知らない文", "not_done", "Task {t} cannot be pulled back now.", "started"),
            ("no_change・期限切れの文", "no_change", "Task {t} already expired unstarted, so it is no longer shown.", "expired"),
            ("null・知らない文", None, "Task {t} is gone.", "closed"),
            ("知らない値・取り下げの文", "weird", "Task {t} withdrawn — the chip is no longer shown to the user.", "withdrawn"),
        ]
        for k, (label, stamp, reply, want) in enumerate(stamps):
            tid = f"task_stmp{k}"
            ts = _T(now - 3600)
            ts.event()
            ts.card(tid, f"[local推奨] 値の形 {k}", None)
            ts.say(f"{mark} 1 枚: 値の形 {k}")
            ts.tool("mcp__ccd_session__dismiss_task", {"task_id": tid}, reply.format(t=tid), stamp=stamp)
            st = pc.chains(pc.load_entries(ts.write(d)))[0]["status"]
            check(f"取り下げの構造化した値「{label}」 → {want}", st == want)
        check("dismiss_kind: 版の照合が読む 1 つの文の読み分け",
              [pc.dismiss_kind(f.format(t="task_x1")) for _l, f, _w in forms[:3]] == ["closed", "expired", "started"]
              and pc.dismiss_kind("Session not found — cannot look up task task_x1.") == "")
        te = _T(now - 3600)
        te.event()
        te.card("task_edok", "[local推奨] 編集済み", None)
        te.say("x")
        te.event()
        te.say("見張り。")
        te.feedback(_reason(_run_stop(te.write(d))))
        te.tool("mcp__ccd_session__dismiss_task", {"task_id": "task_edok"}, forms[-1][1].format(t="task_edok"))
        te.event()
        te.say(f"card の上で押してください。\n{mark} 1 枚: 編集済み")
        pe = te.write(d)
        check("編集された card は点呼の行があれば黙る (取り下げも出し直しも求めない)", _run_stop(pe) == "")
        check("編集された card の依頼は見張りが拾い直さない側 (押されていない card と同じ)",
              [c["status"] for c in pc.cards(pc.load_entries(pe))] == ["edited"])

        # 起きた session を本人が消した後: 押された印は起こした側の app の記録に積まれた知らせだけ
        tg = _T(now - 3600)
        tg.event()
        tg.card("task_ghost1", "[local推奨] 消された子", None)
        tg.say(f"{mark} 1 枚: 消された子")
        tg.event()
        tg.say("見張り。")
        pg = tg.write(d)
        check("起こした側の記録に知らせが無い → 出し直しを求める", pc.REISSUE_HEAD in _reason(_run_stop(pg)))
        with open(os.path.join(d, "app", "acct", "env", "local_parent.json"), "w") as fh:
            json.dump({"sessionId": "local_parent", "pendingSystemReminder":
                       "<system-reminder>\nThe user started your proposal task_ghost1 (\"x\") as session local_gone.\n"
                       "</system-reminder>"}, fh)
        check("起こした側の記録に積まれた「started your proposal」 → 押された (起きた session が消された後も)", _run_stop(pg) == "")
        check("流し直し (時刻つき) では積まれた知らせを使わない",
              len(evaluate(pc.load_entries(pg), now=now - 3000, app_until=now - 3000)["active"]) == 1)

        # ---- 出し直さない形 ----
        # 「あとで」 = その鎖は以後も出し直さない・点呼しない。 その後の新しい card だけを数える
        tl = _T(now - 3600)
        tl.event()
        tl.card("task_lll1", "[local推奨] 道具の直し", None)
        tl.say(f"{mark} 1 枚: 道具の直し")
        tl.human("<system-reminder>x</system-reminder>\nあとで")
        tl.say("分かりました。")
        check("本人の「あとで」 → 黙る", _run_stop(tl.write(d)) == "")
        tl.event()
        tl.say("見張り。")
        check("「あとで」 の後の turn → 黙る (出し直さない)", _run_stop(tl.write(d)) == "")
        tl.card("task_lll2", "[local推奨] 数式の件", None)
        tl.say("新しい card。")
        rs = _reason(_run_stop(tl.write(d)))
        check("「あとで」 の後の新しい card → その 1 枚だけで点呼", "1 枚: 数式の件" in rs and pc.REISSUE_HEAD not in rs)

        # turn の途中に打った「あとで」 (queued_command) も本人の発言
        tq = _T(now - 3600)
        tq.event()
        tq.card("task_qqq1", "[local推奨] 途中の発言", None)
        tq.say(f"{mark} 1 枚: 途中の発言")
        tq.event()
        tq.rows.append({"type": "attachment", "timestamp": _iso(tq.t + 5), "attachment": {
            "type": "queued_command", "origin": {"kind": "human"},
            "prompt": [{"type": "text", "text": "<system-reminder>x</system-reminder>"}, {"type": "text", "text": "あとで"}]}})
        tq.say("了解。")
        check("turn の途中の本人の「あとで」 → 黙る", _run_stop(tq.write(d)) == "")

        # origin が human でも別 session の message の形の「あとで」 は本人の発言にしない
        tc = _T(now - 3600)
        tc.event()
        tc.card("task_ccc1", "[local推奨] 本人でない human", None)
        tc.say(f"{mark} 1 枚: 本人でない human")
        tc.human('<cross-session-message from="local_x" encoded="1">あとで</cross-session-message>')
        tc.say("受けました。")
        check("別 session の message の「あとで」 → 出し直しは続く", pc.REISSUE_HEAD in _reason(_run_stop(tc.write(d))))

        # 7 日: 最初の card から数える (出し直しで延びない)
        t7 = _T(now - 8 * 86400)
        t7.event()
        t7.card("task_777a", "[local推奨] 古い依頼", "20990101T000007Z-claude-aaaa07")
        t7.say(f"{mark} 1 枚: 古い依頼")
        t7.t = now - 600
        t7.event()
        t7.dismiss("task_777a")
        t7.card("task_777b", "[local推奨] 古い依頼", "20990101T000007Z-claude-aaaa07")
        t7.say("出し直し。")
        t7.event()
        t7.say("見張り。")
        check("最初の card から 7 日を過ぎた依頼 → 出し直した card が新しくても黙る", _run_stop(t7.write(d)) == "")

        # request id の無い card は仕事の名前で結ぶ
        tn = _T(now - 3600)
        tn.event()
        tn.card("task_nnn1", "[local推奨] 名前だけ", None)
        tn.dismiss("task_nnn1")
        tn.card("task_nnn2", "[worktree推奨] 名前だけ", None)
        chs = pc.chains(pc.load_entries(tn.write(d)))
        check("request id の無い card は題の tag を外した名前で結ぶ", len(chs) == 1 and len(chs[0]["cards"]) == 2)

        # ---- 押された・片付いた ----
        t2 = _T(now - 3600)
        t2.event()
        t2.card("task_bbb1", "[local推奨] 返事の記録", None)
        t2.say("card を出しました。")
        t2.note("<system-reminder>\nThe user started your proposal task_bbb1 (\"x\") as session local_1.\n</system-reminder>")
        t2.say("押されました。")
        check("「started your proposal」 の知らせ → 黙る", _run_stop(t2.write(d)) == "")

        t3 = _T(now - 3600)
        t3.event()
        t3.card("task_ddd1", "[local推奨] 返事の記録", None)
        t3.human("起こして")
        t3.tool("mcp__ccd_session__start_session", {"proposal_id": "task_ddd1"}, 'Started session "x" (session_id: local_2).')
        t3.say("起こしました。")
        check("proposal_id で起こした → 黙る", _run_stop(t3.write(d)) == "")

        t4 = _T(now - 3600)
        t4.event()
        t4.card("task_eee1", "[local推奨] 検収係", None)
        t4.say("card を出しました。")
        t4.event()
        t4.say("見張り。")
        p4 = t4.write(d)
        with open(os.path.join(d, "app", "acct", "env", "local_9.json"), "w") as fh:
            json.dump({"sessionId": "local_9", "createdAt": int(now * 1000),
                       "spawnedFrom": {"sessionId": "local_p", "taskId": "task_eee1", "sideSession": True}}, fh)
        check("app の記録の spawnedFrom.taskId → 黙る", _run_stop(p4) == "")
        r = evaluate(pc.load_entries(p4), now=now - 3000, app_until=now - 3000)
        check("流し直しでは、 その turn の後にできた記録は数えない", len(r["active"]) == 1)

        tb2 = _T(now - 3600)
        tb2.event()
        tb2.card("task_jjj1", "[local推奨] 別の窓が引き受けた", "20990101T000009Z-claude-aaaa09")
        tb2.say("card を出しました。")
        pb = tb2.write(d)
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

        # ---- 掲示板の request id (見張りが拾い直さない依頼) ----
        check("出し直した後の card の request id を引く (見張りが拾い直さない依頼)",
              pc.pending_request_ids(pc.load_entries(p_reissued)) == {R1})
        check("取り下げたままの依頼の request id は引かない", pc.pending_request_ids(pc.load_entries(t.write(d))) == set())

        # ---- その他の黙る形 ----
        t8 = _T(now - 3600)
        t8.event()
        t8.card("task_hhh1", "[local推奨] 空", None)
        check("最終発話の無い turn → 黙る", _run_stop(t8.write(d)) == "")
        t9 = _T(now - 3600)
        t9.event()
        t9.card("task_iii1", "[local推奨] 差し戻し", None)
        t9.say("card を出しました。")
        t9.feedback("別の hook の差し戻し")
        t9.say("追記です。")
        check("別の hook の差し戻しの後の追記 → 差し戻しは turn を始めない (点呼が無ければ止める)", '"block"' in _run_stop(t9.write(d)))

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
