#!/usr/bin/env python3
"""child-wrap-check.py — 起こした子の session を畳んで (archive して) よいかを照合する。 `--wait` は子の turn が終わるまで待ってから照合する。 `--finished` は掲示板の依頼が全部受け取られたのに畳まれていない子を数える (desktop app の親 session 用、 読むだけ)。

Why (実測、 正本 = conventions/multi-session-coordination.md#tidy-after-child-turn-ends):
  - 止めて待つ向き: desktop app は、 子の turn の終わりの知らせで親を起こすのを「親が起こした子が 1 つも動いていない時」 に
    限る。 ほかの子 (長い仕事の worker) が動いていると、 知らせは親の次の turn まで待たされる = 多くは本人の次の発言に
    同梱されて届き、 親は子が終わったのを知らないまま止まっている。 一方、 親が自分の Bash を run_in_background で回すと、
    その終わりは (ほかの子が動いていても) 親の新しい turn を始める。 `--wait` はその見張り。
  - 早すぎる向き: 子が本人に頼んだ・問うたまま止まったのに、 親が代わりに答えて (別 session の message で上書きして) 子を
    閉じる。 子の最後の報告は「残りは無い」 に変わるので、 最後の知らせだけを見ると「終えた」 に見える。
  - 畳み忘れの向き (`--finished` と 2 つの hook mode): 親が子の提出を受け取った (accept) turn で畳む手順に入らず、 子が
    何時間も残る。 実測の型 = 親の文脈に畳む規則が無い (読んだ範囲が規則の 1 行下から) / 後の直しに使うつもりで残す
    (次の依頼は出していない) / 畳む前に本人に「片づけますか」 と聞いて答えを待つ。 受け取った turn の直後に 1 行を出し
    (`--hook-accept`)、 畳むべき子を残したまま turn を終えると 1 回だけ止める (`--hook-stop`)。

照合 (子ごと):
  - 動き: live の registry の status (busy = まだ動いている / waiting = turn の途中で許可・入力の確認が出たまま止まっている。
    どちらも turn の途中 = 畳まない。 waiting を turn の終わりと読むと、 子が wrap の途中で許可を待っているのに「畳んでよい」 と出た (実測))
  - wrap: 子の記録の wrap skill の起動 (Skill tool の skill=wrap か、 skill の本文の差し込み)
  - commit: 子の commit (全 repo の commit に入る `Agent-Session: claude:<子の transcript id>` の trailer で引く) が、
    その repo の remote-tracking branch に入っているか (push 済みか)
  - 本人待ちの問い: 子の turn が本人待ちで終わった最後の時点 (子の wrap_up の ask / blocked、 親の記録の
    「… finished a turn and then reported that it was waiting on the user」 の知らせより前の子の最後の応答) より後に、
    子の窓に本人の発言 (人の入力。 別 session の message・hook の差し戻し・task の通知・API の誤りの後の「Try again」 は
    数えない) があるか。 依頼元 (app の記録の親 = spawnedFrom) の message がその時点より後に子の窓に届いていても答えと数える
    (判断の問いは依頼元が答える = ai-collaboration board/CONTRACT.md#worker-questions-to-requester。 実測: 依頼元が答えて
    片づいた子の問いを本人待ちと読み、 畳む照合と archive の hook が止めた)。 ただし問いの文が承認・外部への発信の語
    (OWNER_ONLY_ASK) を含めば本人だけが答えられるので、 本人の発言だけを数える。 親でない session の message は数えない。
    **hand-off の手順 0 で止まった turn は数えない** = 掲示板の hand-off (「This window must run on
    <model> at <effort> effort」 の行) で始まった窓で、 その turn で model・effort の確かめ (`session-model.py self`) が走り、
    掲示板の claim が続かずに終わった turn は、 依頼元の go を待つ停止で本人待ちではない
    (app は親にそれも「本人待ち」 と知らせる。 実測: go の後に仕事も wrap も済んだ worker が、 手順 0 の停止を
    「本人待ちの問い」 と読まれて畳む照合と archive の hook で止まった)。 go がまだ届いていない (その停止の後に親の message が
    無い) 子は「依頼元の go 待ち」 として別の理由で残す (archive の hook が読む owner_reasons には入れない)
  - 本人と話している途中: 本人が子の窓で発言しているか (窓の最初の依頼文は数えない。 その後に親が子へ message を
    送っていても数える = 実測: 本人が子の窓で仕事をしている間に親が差し戻しを送り、 その message が本人の最後の発言を
    隠して、 `--wait-due` が本人の発言のすぐ後に「親の番」 と出した。 その前の実測: 親が「wrap して終えて」 と送った
    直後に本人が同じ子に「どうやって消すの？」 と打ち、 子が答えた 2 分後に親が畳んだ)。 子がその発言に答えて問いを
    残さず turn を終えていれば、 その時刻を添えて出す (子が止まってから ANSWERED_GRACE_MIN 分 〔既定 10、 env
    CHILD_WRAP_ANSWERED_GRACE_MIN、 `none` = 数え続ける〕、 本人がその窓で話さなければ、 話している途中ではない。
    既定は持ち主の裁定の値 = DEFAULT_ANSWERED_GRACE_MIN の注釈)
  - wrap の依頼: 親の message のうち wrap を頼む形のもの (wrap_kind = 語の直後の依頼の形。 道具の名前・thread id・
    「」 の引用・「wrap 済み」 などの報告は依頼でない。 実測: 道具の名前を書いただけの報告が依頼と読まれた)。 親が後から
    取り消した (「wrap の依頼は取り消します」) 依頼と、 それより前の子の wrap の起動は数えない
  - 「Try again」: app が API の誤り (接続が切れた等) の後に入れる再試行の 1 行。 本人の新しい発言ではないので、
    上の 2 つのどちらにも数えない (実測: 子が答え終えて止まっているのに、 これ 1 行で「話している途中」 と出ていた)
判定: 動いていない・wrap の記録がある・push されていない commit が無い・本人待ちの問いも話の途中も無い = 畳んでよい。
見ないもの: 掲示板の依頼が受理されたか (受理は親自身の操作。 `--finished` は掲示板を読む)、 子が commit しなかった変更
  (同じ作業木を共有すると帰属できない)、 trailer の hook が入っていない repo の commit。

`--finished` (掲示板の root は --board-root か env CHILD_WRAP_BOARD_ROOTS = os.pathsep 区切り。 層1 に既定は無い):
  子 = app の記録で spawnedFrom が親で、 独立させていない (lineageDetached でない) もの。 子の依頼 = この機械の instance
  (`claude@<host>`) で子が claim / submit した request (actor.task の頭の transcript id 8 字か actor.session_id で引く)。
  開いている依頼 = 子が claim して受け取られていないもの + 子が claim に使った役 (role id) か子の id 宛ての、
  まだ誰も受け取っていない request (次の依頼 = 使い回し)。 状態:
    open (開いている依頼がある) / busy / owner (本人待ち) / answered (本人が子の窓で話した後に子が答え終えている = 裁定待ち) /
    due (全部受け取られ、 wrap を頼んでいない = 規則の番) / wrapping (wrap を頼んで子がまだ終えていない) /
    wrapped (wrap が終わっている = 照合して畳む) / no-board (掲示板に子の依頼が無い = 判定しない)

Usage:
  child-wrap-check.py <local_…|transcript id> [...]     照合して出す (exit 0 = 全部畳んでよい / 1 = 残すものがある / 2 = 子が見つからない)
  child-wrap-check.py --wait <local_…> [...] [--since <epoch 秒 か ISO>] [--max-minutes N]
        子のどれか 1 つの turn が、 子の窓に届いた親の最後の wrap の依頼より後に終わって動いていない状態になるまで待ち
        (依頼の時刻は道具が子の会話記録から引く = --since は渡さなくてよい。 渡した --since が依頼より後なら依頼の時刻に
        下げる = 実測: 呼ぶ側が「今」 や「10 分前」 を渡して依頼が窓の外になり、 wrap 済みの子が ⏸ になった)、 終わった子の
        照合と、 残りの子を続けて見張る 1 行を出す (親が Bash の run_in_background で回す = 終わると親が起こされる。
        全部を待つと先に終えた子が残る = 実測。 時間切れ = exit 3)
  child-wrap-check.py <id> --as-of 2026-01-01T00:00:00 照合をその時点までの記録で (RCA の再現。 動きと commit は今の状態)
  child-wrap-check.py --finished [--parent <local_…|transcript id>] --board-root <dir> [...] [--as-of …]
        掲示板の依頼が受け取られたのに畳まれていない子を数える (--parent 無し = この機械の全部の親。 exit 1 = due / wrapped がある)
  child-wrap-check.py --wait-due <local_…> [...] --board-root … [--max-minutes N]
        子のどれかが親の番 (due / wrapped。 ANSWERED_GRACE_MIN が none なら答え終えて ASK_AFTER_MIN 分も) になるまで待って
        状態と、 残りの子を続けて見張る 1 行を出す (既定 720 分、 時間切れ = exit 3)。
        本人を待っている子に親が run_in_background で出す = 本人が子の窓で答えて子が終えたとき、 ほかの子が動いていても親が起こされる
  child-wrap-check.py --hook-sendmessage [--rule <参照>]  PostToolUse(SendMessage) の hook 用: 自分の子 (切り離した
        session は子でない) に wrap を頼んだ message (wrap_kind) なら、 同じ turn に --wait の見張りを出す 1 行を
        additionalContext で返す (それ以外は何も出さない)
  child-wrap-check.py --hook-accept --board-root … [--rule …]   PostToolUse(Bash) の hook 用: `board.py accept` で自分の子の
        依頼を受け取った直後に、 子の状態に合わせた 1 行を返す
  child-wrap-check.py --hook-stop --board-root … [--rule …] [--stop-mode off|observe|block]   Stop の hook 用: due / wrapped の
        子を残したまま turn を終えると、 子ごとに 1 回だけ止める (observe = 記録だけ。 既定 = env CHILD_FINISHED_STOP か observe)
  --no-wrap-needed (wrap の記録を判定に入れない) / --json / --selftest
env (test): CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR / CLAUDE_DESKTOP_SESSIONS_DIR / CHILD_WRAP_REPOS_GLOB /
  CHILD_WRAP_BOARD_ROOTS / CHILD_WRAP_INSTANCE / CHILD_FINISHED_STATE_DIR
"""
from __future__ import annotations

import argparse
import calendar
import collections
import glob
import importlib.util as _ilu
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import desktop_sessions as ds  # noqa: E402
import session_background_tasks as sbt  # noqa: E402
import session_model as sm  # noqa: E402

_spec = _ilu.spec_from_file_location("busy_worker_stop_check", os.path.join(HERE, "busy-worker-stop-check.py"))
_bw = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_bw)

WAIT_NOTE = "finished a turn and then reported that it was waiting on the user"
# registry status "waiting" = the child stopped mid-turn on a permission / input prompt in its own window (measured:
# a child stuck on a Bash approval read as idle-with-an-old-turn-end and was reported foldable during its wrap)
WAITING_TEXT = "子の窓で許可・入力の確認が出たまま止まっている (turn の途中 = 本人に子の窓を見てもらう)"
PEER_FROM = re.compile(r'<cross-session-message from=\\?"(local_[0-9a-f-]+)')  # kept for callers; scan uses _peer_messages
PEER_TAG = re.compile(r'<cross-session-message ((?:[a-z-]+=\\?"[^"\\]*\\?"\s*)+)>(.*?)(?:</cross-session-message>|$)', re.S)
PEER_ATTR = re.compile(r'(from-session|from)=\\?"([^"\\]*)')
RECENT_REQUEST_MIN = 30  # --wait: a parent's wrap request older than this (before the watch started) is an earlier job's
# The hand-off's step 0 (the worker reads its own model and effort and stops when they differ) and the board claim that
# follows it when they match: a turn that ran the first and not the second waits for the requester's go, not the person.
STEP0_CHECK = re.compile(r"session-model\.py['\"]?\s+self\b")
CLAIM_RUN = re.compile(r"board\.py['\"]?\s+claim\b")
# Only a window started with the board's hand-off has a step 0 (its line "This window must run on <model> at <effort>
# effort"); the first prompt arrives as an sdk prompt, not as the person's, so it is read from the user entries' text.
STEP0_HANDOFF = re.compile(r"must run on \S+ at \S+ effort")
BG_TASKS = sbt.list_tasks  # the child's live background work (replaced in the selftest)
DELIVERY_GRACE_S = 60  # --wait without a recent request: the first seconds wait for the request to land in the child's window
MAX_COMMITS = 30
# a send's result that says the message was not delivered (SendMessage: "success":false; both tools end with
# "(delivery: undelivered; …)" when it did not go, measured)
SEND_FAILED = re.compile(r'\\?"success\\?"\s*:\s*false|delivery: undelivered')
RETRY_TEXTS = {"Try again"}  # the app's retry after an API error (measured on the desktop app)
# Latin-letter boundaries, not \b: Python counts kana as word characters, so \bwrap\b misses 「wrapして」.
WRAP_WORD = re.compile(r"(?<![A-Za-z])wrap(?![A-Za-z])", re.I)
# A message asks the child to wrap only when the word is followed by a request; the word alone is a mention (measured:
# messages that reported on this tool by name, quoted someone's 「…wrap を頼んだ…」, or said no wrap had been asked for,
# were read as wrap requests, and the watch was nudged for a session that had been given none). wrap_kind() reads each
# occurrence: inside a name (child-wrap-check / a thread id …-wrap / skills/wrap / wrap_up) or in 「」 = skipped; followed
# by a report or a retraction = not a request (a retraction cancels the parent's earlier request); a request = a request
# form right after the word, or, for the command (/wrap) and the skill (`wrap` skill), anywhere later in its sentence.
WRAP_QUOTE = re.compile(r"「[^「」]*」|『[^『』]*』|“[^“”]*”")
WRAP_ASIDE = re.compile(r"[(（][^()（）]*[)）]")
# retract = the request is called off (取り消し / 止めて / まだしなくて); せず / しない stay neutral (「問いが残るなら wrap
# せずに返して」 sits next to a request in the same message)
WRAP_NOT = re.compile(r"^[\s`'\"）)\]]*(?:skill\s*)?(?:の(?:依頼|分))?\s*[はもをがの]?\s*(?P<mada>まだ\s*)?"
                      r"(?:(?P<retract>取り消|取りやめ|中止|止め)|(?P<notyet>しなくて)|しない|せず|済|終え|終わ|入ります|に入"
                      r"|頼んで|後|要らな|不要)")
WRAP_REQ_NEAR = re.compile(r"^[\s`'\"]*(?:skill(?:\s*tool)?\s*)?(?:[をで]\s*|が\s*まだなら\s*)?(?:まとめて\s*|最後まで\s*)?"
                           r"(?:お願い|起動|仕上げ|締め|回し|頼み|やって|して(?!い|もら|あ|知らせま|報告しま)|をして)|^\s*up\b", re.I)
# the command typed at the head of a line (「/wrap — 提出を受け取りました。 仕上げをしてください。」) is the request itself
WRAP_COMMAND_HEAD = re.compile(r"(?:^|\n)[ \t]*/$")
WRAP_REQ_SENTENCE = re.compile(r"ください|下さい|お願い|please", re.I)
WRAP_SENTENCE_END = re.compile(r"[。\n!?！？]")


def wrap_kind(text: str) -> str:
    """'request' / 'retract' / '' for a message: what its last wrap occurrence that is not a mention says (WRAP_NOT)."""
    t = WRAP_QUOTE.sub("", text or "")
    prev = None
    while prev != t:  # drop asides that do not hold the word (「wrap（知見を上の層へ、…）をして」 = a request)
        prev, t = t, WRAP_ASIDE.sub(lambda m: m.group(0) if WRAP_WORD.search(m.group(0)) else "", t)
    kind = ""
    for m in WRAP_WORD.finditer(t):
        before, after = t[max(0, m.start() - 12):m.start()], t[m.end():]
        if (before[-1:] in tuple("-_:.#") or (before.endswith("/") and re.search(r"[\w.-]/$", before))
                or after[:1] in ("-", "_", ":") or re.match(r"\.\w", after)):
            continue  # part of a name
        neg = WRAP_NOT.match(after)
        if neg:
            kind = "retract" if neg.group("retract") or (neg.group("mada") and neg.group("notyet")) else kind
            continue
        strong = before.endswith("/") or before.rstrip().endswith("`") or re.match(r"`?\s*skill", after, re.I) \
            or re.search(r"(?:please|run|invoke)\s+(?:the\s+)?[`/]?$", before, re.I)
        if (WRAP_REQ_NEAR.match(after) or WRAP_COMMAND_HEAD.search(t[:m.start()])
                or (strong and WRAP_REQ_SENTENCE.search(WRAP_SENTENCE_END.split(after, 1)[0]))):
            kind = "request"
    return kind
# An ask only the person can answer: an approval that counts only in the window it is given in (a protected file's change,
# an operation the permission check holds) or a send to the outside. The parent's message does not answer it. A question of
# judgment that uses these words also stays the person's (keeping a child costs less than folding it past the person).
# 当てますか・当ててよいか = 規則の文書・道具の当ての承認 (承認と当ては worker の窓で本人から取る。 親の message は答えにならない)
OWNER_ONLY_ASK = re.compile(r"承認|裁定|許可|同意|送信|送って|送る|投稿|公開|返信|approv|permission|consent|publish"
                            r"|当て(?:ますか|てよい|て良い|てもよい|てもいい|ていい|る)"
                            r"|(?<![A-Za-z])(?:send|post)(?![A-Za-z])", re.I)
ID8 = re.compile(r"^([0-9a-f]{8})\b")
# Minutes after the child answered the person's last prompt in its window (and left no question) from which that prompt
# no longer counts as "talking" = the child is the parent's to fold. The default is the owner's ruling: 30 where this was
# built, then 10 (the owner: a reply is read and the next prompt typed well within 10 minutes; 30 kept a finished child
# open long after the person had moved on, measured). env CHILD_WRAP_ANSWERED_GRACE_MIN=<minutes> overrides it, `none`
# keeps counting it (then an answered child is raised as "ask the person").
DEFAULT_ANSWERED_GRACE_MIN = 10.0


def _grace_from_env() -> float | None:
    v = (os.environ.get("CHILD_WRAP_ANSWERED_GRACE_MIN") or "").strip().lower()
    if v in ("none", "off"):
        return None
    try:
        return float(v) if v else DEFAULT_ANSWERED_GRACE_MIN
    except ValueError:
        return DEFAULT_ANSWERED_GRACE_MIN


ANSWERED_GRACE_MIN: float | None = _grace_from_env()
ASK_AFTER_MIN = 10  # an "answered" child idle this long is raised once as "ask the person whether to fold" (--hook-stop / --wait-due)
RAW_ROOTS: list[str] = []  # the --board-root values as given (patterns), repeated in the commands the hooks suggest
CHILD_DAYS = 14  # children are looked for among app records touched this recently
STATE_DIR_DEFAULT = os.path.expanduser("~/.claude/state/child-finished-stop")


def _peer_messages(blob: str) -> list[tuple[str, str]]:
    """(sender's local_… id, text) of each cross-session message in a JSON-dumped transcript entry. The sender is `from` when
    it is a local_… id, else `from-session` (measured: a message sent to a `uds:/…sock` address arrives with
    from="uds:…" and from-session="local_…" = only `from` missed the parent's messages sent that way)."""
    out = []
    for attrs, text in PEER_TAG.findall(blob or ""):
        a = dict(PEER_ATTR.findall(attrs))
        frm = a.get("from", "") if a.get("from", "").startswith("local_") else a.get("from-session", "")
        if frm.startswith("local_"):
            out.append((frm, text))
    return out


def _ts(e: dict) -> str:
    return str(e.get("timestamp") or "")


def _epoch(ts: str) -> float:
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch))


def _local_hm(ts: str) -> str:
    """'2026-10-28T09:26:52.608Z' → '10/28 18:26' in local time ('?' when unparsable)."""
    try:
        return time.strftime("%m/%d %H:%M", time.localtime(_epoch(ts)))
    except (ValueError, OverflowError):
        return "?"


def _raw_record(rec: dict | None) -> dict:
    try:
        with open(rec["path"], encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def locate(target: str) -> dict | None:
    """The child: local id, transcript id and path, title, live status, parent's transcript path, last turn edge (epoch s)."""
    t = (target or "").strip()
    if not t:
        return None
    rec = ds.find(t)
    cli = rec["cli_id"] if rec else ""
    local = rec["local_id"] if rec else (t if t.startswith("local_") else "")
    status = "(not live)"
    for s in sm.live_sessions():
        if (cli and s["sessionId"] == cli) or (local and s["host"] == local) or (not cli and not local and s["sessionId"].startswith(t)):
            status, cli, local = s["status"] or "?", s["sessionId"], local or s["host"]
            break
    if not cli and not t.startswith("local_"):
        rows = sm.resolve(t)
        cli = rows[0]["sessionId"] if rows else ""
    if not cli:
        return None
    parent_path = ""
    if rec and rec.get("parent"):
        prec = ds.find(rec["parent"])
        if prec and prec.get("cli_id"):
            parent_path = sm.transcript_path(prec["cli_id"]) or ""
    edge = _raw_record(rec).get("lastTurnEdgeAt")
    return {"local": local, "cli": cli, "title": (rec or {}).get("title", ""), "status": status,
            "archived": bool((rec or {}).get("archived")), "path": sm.transcript_path(cli) or "",
            "parent": (rec or {}).get("parent", ""), "parent_path": parent_path,
            "edge": edge / 1000 if isinstance(edge, (int, float)) else None}


def scan_child(path: str, as_of: str = "") -> dict:
    """Events from the child's transcript (timestamps): first entry, replies, turn ends, prompts of the person, asks, wrap runs.
    The app's retry line after an API error ("Try again") goes to `retries`, not to the person's prompts."""
    out = {"first": "", "replies": [], "stops": [], "human": [], "said": [], "peers": [], "asks": [], "wraps": [],
           "retries": [], "peer_wraps": [], "peer_unwraps": [], "model_checks": [], "claims": [], "step0_handoff": False}
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return out
    api_error = False
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            ts = _ts(e)
            if as_of and ts and ts[:19] > as_of[:19]:
                continue
            kind = e.get("type")
            if ts and not out["first"]:
                out["first"] = ts
            if kind == "assistant" and ts:
                out["replies"].append(ts)
                api_error = bool(e.get("isApiErrorMessage"))
            if kind == "system" and e.get("subtype") == "stop_hook_summary":
                out["stops"].append(ts)
                continue
            if kind == "user" and not out["step0_handoff"]:
                c0 = (e.get("message") or {}).get("content")
                t0 = c0 if isinstance(c0, str) else " ".join(b.get("text", "") for b in (c0 or []) if isinstance(b, dict))
                out["step0_handoff"] = bool(STEP0_HANDOFF.search(t0))
            said = _bw._human_text(e)
            if said:
                if api_error and said.strip() in RETRY_TEXTS:
                    out["retries"].append(ts)
                    continue
                out["human"].append(ts)
                out["said"].append((ts, said))
            elif kind in ("user", "attachment"):
                for frm, text in _peer_messages(json.dumps((e.get("message") or {}).get("content") or e.get("attachment") or "",
                                                           ensure_ascii=False)):
                    out["peers"].append((ts, frm))
                    kind = wrap_kind(text)
                    if kind:  # a request, or a retraction that calls the earlier ones off
                        out["peer_wraps" if kind == "request" else "peer_unwraps"].append((ts, frm))
            content = (e.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if kind == "assistant" and b.get("type") == "tool_use":
                    name, inp = str(b.get("name") or ""), b.get("input") or {}
                    if name.endswith("wrap_up") and (inp.get("ask") or inp.get("blocked") is True):
                        out["asks"].append((ts, str(inp.get("ask") or "(blocked)")))
                    elif name == "Skill" and str(inp.get("skill") or "").split(":")[-1] == "wrap":
                        out["wraps"].append(ts)
                    elif name == "Bash":
                        cmd = str(inp.get("command") or "")
                        if STEP0_CHECK.search(cmd):
                            out["model_checks"].append(ts)
                        if CLAIM_RUN.search(cmd):
                            out["claims"].append(ts)
                elif kind == "user" and e.get("isMeta") and b.get("type") == "text":
                    t = b.get("text", "")
                    if t.startswith("Base directory for this skill:") and re.search(r"/skills/wrap\s", t[:300]):
                        out["wraps"].append(ts)
    return out


def parent_wait_notes(parent_path: str, local: str, as_of: str = "") -> list[str]:
    """Times the parent was told the child ended a turn waiting on the person."""
    if not parent_path or not local:
        return []
    needle, out = f"({local}) {WAIT_NOTE}", []
    try:
        with open(parent_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if needle not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("type") == "user" and _ts(e) and not (as_of and _ts(e)[:19] > as_of[:19]):
                    out.append(_ts(e))
    except OSError:
        pass
    return out


def _wait_points(ev: dict, notes: list[str]) -> list[tuple[str, str, str]]:
    """[(when the child stopped waiting on the person, the ask text or '', when the note about it landed or '')].
    A note lands after the child's turn end, but the app may hold it until the person's next prompt in the parent's window;
    meanwhile the person may have answered in the child's window and the child gone on. When the child's turn was still
    running at the note (it replied after the note and before its next turn end), the note reports the turn that ended
    before it = date it there. Otherwise at the child's last reply before the note (measured: dated at the landing, an ask
    the person had already answered looked open and kept a finished child)."""
    points = [(t, a, "") for t, a in ev["asks"]]
    stops = sorted(ev["stops"])
    prompts = sorted(list(ev["human"]) + [t for t, _ in ev["peers"]])
    for n in notes:
        # running = the child's first reply after the note comes before its next turn end and before any new prompt
        # (a reply after a new prompt belongs to a turn that started after the note)
        nxt = min((s for s in stops if s > n), default="")
        r1 = min((r for r in ev["replies"] if r > n), default="")
        p1 = min((t for t in prompts if t > n), default="")
        at = ""
        if r1 and (not nxt or r1 <= nxt) and (not p1 or r1 < p1):
            s0 = max((t for t in prompts if t <= n), default="")  # the prompt that started the running turn
            if s0:  # the turn that ended before it (its turn-end record, else its last reply)
                at = max((s for s in stops if s <= s0), default="") or max((r for r in ev["replies"] if r < s0), default="")
        points.append((at or max((r for r in ev["replies"] if r <= n), default=n), "", n))
    return points


def step0_turn(ev: dict, at: str) -> bool:
    """The turn that ended waiting at `at` is the hand-off's step 0: it ran the model check and no board claim after it
    (a worker whose model and effort match claims in the same turn), in a window the board's hand-off started (only it
    has a step 0). Such a stop waits for the requester's go."""
    if not ev.get("step0_handoff"):
        return False
    starts = [t for t in ev["human"] if t < at] + [t for t, _ in ev["peers"] if t < at] + ([ev["first"]] if ev["first"] else [])
    start = max((t for t in starts if t <= at), default="")
    checks = [m for m in ev["model_checks"] if start <= m <= at]
    return bool(checks) and not any(min(checks) < c <= at for c in ev["claims"])


def go_wait(ev: dict, notes: list[str], parent: str = "") -> dict | None:
    """The child's latest wait is a step-0 stop and no message of the parent (any peer when the parent is unknown) has
    come in its window since = it still waits for the requester's go."""
    points = _wait_points(ev, notes)
    if not points:
        return None
    at = max(p[0] for p in points)
    if not step0_turn(ev, at) or any(h > at for h in ev["human"]):
        return None
    if any(ts > at for ts, frm in ev["peers"] if not parent or frm == parent):
        return None
    return {"at": at}


def open_ask(ev: dict, notes: list[str], parent: str = "") -> dict | None:
    """The child's last turn that ended waiting on the person, if no prompt of the person came in the child's window after it
    and, unless the ask is one only the person can answer (OWNER_ONLY_ASK), no message of the parent either (the requester
    answers questions of judgment = ai-collaboration board/CONTRACT.md#worker-questions-to-requester). A step-0 stop
    (step0_turn) is the requester's go to wait for, not the person's: it is not a wait point here."""
    points = [p for p in _wait_points(ev, notes) if not step0_turn(ev, p[0])]
    if not points:
        return None
    at, text, noted = max(points, key=lambda p: p[0])
    if any(h > at for h in ev["human"]):
        return None
    if not text:
        text = next((a for t, a in sorted(ev["asks"], reverse=True) if t <= at), "")
    owner_only = bool(OWNER_ONLY_ASK.search(text))
    if parent and not owner_only and any(ts > at for ts, frm in ev["peers"] if frm == parent):
        return None
    return {"at": at, "ask": text, "owner_only": owner_only, "noted": noted}


def owner_after_parent(ev: dict, parent: str, now: float | None = None) -> dict | None:
    """The person's latest prompt in the child's window (not the window's opening brief = its first entry), as long as it counts as the person working with the child: until the child has answered it and
    ANSWERED_GRACE_MIN minutes have passed. The parent's messages after the prompt do not end it (measured: the person
    was still working in the child's window, the parent's later messages to the child hid the person's last word there,
    and --wait-due called the child the parent's to fold right after it).
    `answered_at` = the child's first turn end after that prompt (after its later questions, when the parent answered
    them) with no question left open (None otherwise). `parent_at` = the parent's latest message to the child ('')."""
    said = [p for p in ev["said"] if p[0] != ev["first"]]
    if not parent or not said:
        return None
    at, said = max(said, key=lambda p: p[0])
    sent = [ts for ts, frm in ev["peers"] if frm == parent]
    ends = sorted(s for s in ev["stops"] if s > at)
    later = [t for t, _ in ev["asks"] if t > at]
    if later and not open_ask(ev, [], parent):  # the child asked more and the parent answered = answered after that
        ends = [s for s in ends if s > max(later)]
        later = []
    answered = ends[0] if ends and not later else None
    if answered and ANSWERED_GRACE_MIN is not None:
        ref = now if now is not None else time.time()
        if ref - _epoch(answered) >= ANSWERED_GRACE_MIN * 60:
            return None
    return {"at": at, "said": said, "parent_at": max(sent, default=""), "answered_at": answered}


def _talking_text(talking: dict) -> str:
    pa, at = talking.get("parent_at") or "", talking["at"]
    if pa and pa < at:
        head = f"親の最後の指示 {_local_hm(pa)} の後、 {_local_hm(at)} に本人がこの子の窓で発言"
    else:
        head = (f"{_local_hm(at)} に本人がこの子の窓で発言"
                + (f"。 その後の親の message ({_local_hm(pa)} まで) では本人の話は終わらない" if pa else ""))
    s = f"本人がこの子と話している途中 ({head}): {talking['said'][:120]}"
    if talking.get("answered_at"):
        s += f" (子は {_local_hm(talking['answered_at'])} に答えて turn を終え、 問いを残していない)"
    return s


def _git(repo: str, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=20)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def child_commits(cli: str, since: str) -> list[dict]:
    """The child's commits in every repo (by the Agent-Session trailer), newest first, with whether each is pushed."""
    pattern = os.environ.get("CHILD_WRAP_REPOS_GLOB") or os.path.expanduser("~/Claude/*/.git")
    out = []
    for g in sorted(glob.glob(pattern)):
        repo = os.path.dirname(g)
        args = ["log", "--all", "-F", f"--grep=Agent-Session: claude:{cli}", "--format=%h %cI"] + ([f"--since={since}"] if since else [])
        for line in _git(repo, *args)[1].splitlines():
            sha, _, at = line.partition(" ")
            if sha:
                pushed = bool(_git(repo, "branch", "-r", "--contains", sha)[1].strip())
                out.append({"at": at, "sha": sha, "repo": repo, "pushed": pushed})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:MAX_COMMITS]


def parent_sends(parent_path: str, child: dict, as_of: str = "") -> list[str]:
    """Timestamps of the parent's sends to this child (SendMessage to its local id or the uds address of its live
    process, and the app's older send_message to its session id) that were not refused (SEND_FAILED)."""
    if not parent_path or not child.get("local"):
        return []
    to = {child["local"]}
    try:
        to |= {s_["address"] for s_ in sm.live_sessions() if s_.get("sessionId") == child.get("cli") and s_.get("address")}
    except Exception:
        pass
    sent, failed = {}, set()
    try:
        fh = open(parent_path, encoding="utf-8", errors="replace")
    except OSError:
        return []
    with fh:
        for line in fh:
            if "SendMessage" not in line and "send_message" not in line and "success" not in line and "delivery" not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ts = _ts(e) if isinstance(e, dict) else ""
            if not isinstance(e, dict) or (as_of and ts[:19] > as_of[:19]):
                continue
            for b in (e.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                name, inp = str(b.get("name") or ""), b.get("input") or {}
                if b.get("type") == "tool_use" and ((name == "SendMessage" and str(inp.get("to") or "") in to)
                                                    or (name.endswith("__send_message") and str(inp.get("session_id") or "") in to)):
                    sent[str(b.get("id") or "")] = ts
                elif b.get("type") == "tool_result" and str(b.get("tool_use_id") or "") in sent:
                    c = b.get("content")
                    text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                    if SEND_FAILED.search(text):
                        failed.add(str(b.get("tool_use_id")))
    return sorted(ts for i, ts in sent.items() if i not in failed and ts)


def unanswered_send(c: dict, ev: dict, as_of: str = "") -> str:
    """The time of the parent's latest message to the child sent after the child's last turn end ('' when none) = the
    message waits for delivery, or landed and the child's turn has not started yet. The app counts both as live work
    and refuses the archive (measured: the parent's own 'stop the background work' message put the child mid-turn as
    the archive arrived)."""
    ends = [_epoch(s) for s in ev["stops"] if s] + ([c["edge"]] if c.get("edge") else [])
    last_end = max(ends, default=0.0)
    late = [ts for ts in parent_sends(c.get("parent_path", ""), c, as_of) if _epoch(ts) > last_end + 1]
    return max(late, default="")


def _stopped_at(ask: dict) -> str:
    """「HH:MM に本人待ちで止まり」 (知らせが遅れて着いたなら着いた時刻も = 読む側が着いた時刻を子の turn と取り違えない)。"""
    at, noted = _local_hm(ask["at"]), _local_hm(ask.get("noted") or "")
    return f"{at} に本人待ちで止まり" + (f" (その知らせが親の窓に着いたのは {noted})" if ask.get("noted") and noted != at else "")


def _ask_text(ask: dict) -> str:
    if ask.get("owner_only"):
        head = (f"本人だけが答えられる問いが残っている ({_stopped_at(ask)}、 その後この子の窓に本人の発言が無い。"
                " 承認・外部への発信の問いは親の message では答えにならない)")
    else:
        head = (f"本人待ちの問いが残っている ({_stopped_at(ask)}、 その後この子の窓に本人の発言も親の message も"
                " 無い。 判断の問いなら親が子に答えを送ればよい)")
    return head + (f": {ask['ask'][:160]}" if ask["ask"] else "")


def _called_off(ev: dict, parent: str, sent: list[str] | None = None) -> str:
    """When the parent last called a wrap off (its retraction as it landed in the child's window, or as sent = `sent`):
    its earlier requests and the child's wrap runs before it do not count ('' when never). Measured: the parent asked a
    child to wrap, called it off soon after (the person was still working there), and the stop of the cancelled run
    read as 'wrap は終わっている'."""
    return max([ts for ts, frm in ev["peer_unwraps"] if frm == parent] + list(sent or []), default="")


def owner_hold(target: str, as_of: str = "") -> dict:
    """Only the person-side reasons to keep a child (an ask left open / the person talking with it): the cheap part
    of check_child, for the archive guard (scripts/busy-worker-stop-check.py). {"reasons": [...], "since": the latest
    time a reason starts from (the open ask, the person's last prompt in the child's window), '' with no reason}: the
    guard lets the archive through when the person said in the parent's window, after `since`, that the child may be
    folded. `as_of` = read the records up to then (replaying a past scene). No reasons when the child is not found."""
    c = locate(target)
    if not c:
        return {"reasons": [], "since": ""}
    ev = scan_child(c["path"], as_of)
    reasons, since = [], []
    ask = open_ask(ev, parent_wait_notes(c["parent_path"], c["local"], as_of), c["parent"])
    if ask:
        reasons.append(_ask_text(ask))
        since.append(ask["at"])
    talking = owner_after_parent(ev, c["parent"], _epoch(as_of) if as_of else None)
    if talking:
        reasons.append(_talking_text(talking))
        since.append(talking["at"])
    return {"reasons": reasons, "since": max(since, key=lambda t: t[:19]) if since else ""}


def owner_reasons(target: str) -> list[str]:
    """The reasons of owner_hold (callers that do not need the time)."""
    return owner_hold(target)["reasons"]


def check_child(target: str, as_of: str = "", need_wrap: bool = True, wrap_since: str = "") -> dict:
    c = locate(target)
    if not c:
        return {"target": target, "found": False, "ok": False, "reasons": ["子が見つからない (app の記録にも live の registry にも無い)"]}
    ev = scan_child(c["path"], as_of)
    off = _called_off(ev, c["parent"])
    ev["wraps"] = [w for w in ev["wraps"] if w > off]
    earlier_wraps = []
    if wrap_since:  # after --wait: only a wrap run for this request counts, not one from an earlier request
        req = max((ts for ts, frm in ev["peer_wraps"] if frm == c["parent"] and ts > off), default="")
        earlier_wraps = [w for w in ev["wraps"] if w[:19] < wrap_since[:19] and req and w >= req]
        ev["wraps"] = [w for w in ev["wraps"] if w[:19] >= wrap_since[:19]]
    notes = parent_wait_notes(c["parent_path"], c["local"], as_of)
    ask = open_ask(ev, notes, c["parent"])
    gw = go_wait(ev, notes, c["parent"])
    commits = child_commits(c["cli"], ev["first"][:19])
    reasons = []
    if not as_of and c["status"] == "busy":
        reasons.append("まだ動いている (turn の途中)")
    if not as_of and c["status"] == "waiting":
        reasons.append(WAITING_TEXT)
    pend = unanswered_send(c, ev) if not as_of and c["status"] not in ("busy", "waiting") else ""
    if pend:
        reasons.append(f"親が {_local_hm(pend)} に子へ送った message が、 子の最後の turn の終わりより後 = 配達待ちか、 届いて子の"
                       " turn が始まる前 (app は archive を断る) → `--wait` で子がそれに答えて turn を終えるのを待ってから照合し直す"
                       " (wrap を頼んだ後は、 子の turn が終わるまで子に message を送らない)")
    try:
        bg = BG_TASKS(c["cli"]) if not as_of else None
    except Exception:
        bg = None  # cannot count = no reason (the app's refusal is the backstop)
    if bg:
        reasons.append("子の背景の作業が生きている (app は archive を断る): " + " / ".join(sbt.describe(t) for t in bg)
                       + " → " + sbt.child_next_step(bg))
    if ask:
        reasons.append(_ask_text(ask))
    if gw:
        reasons.append(f"依頼元の go を待って止まっている ({_local_hm(gw['at'])} に hand-off の手順 0 = model・effort が頼んだ値と違う"
                       " で止まり、 その後に親の message が無い。 本人待ちではない)")
    talking = owner_after_parent(ev, c["parent"], _epoch(as_of) if as_of else None)
    if talking:
        reasons.append(_talking_text(talking))
    if need_wrap and not ev["wraps"]:
        # measured: a parent passed --since 10 minutes after its wrap request, and the wrap run fell outside the window
        reasons.append("wrap の記録が無い" + (f" (--since より前の {_local_hm(max(earlier_wraps))} に wrap の記録がある = --since が"
                                              " wrap の依頼より後になっている。 --since を渡さなければ、 道具が子の窓に届いた依頼の時刻から数える)"
                                              if earlier_wraps else ""))
    bad = [x for x in commits if not x["pushed"]]
    if bad:
        reasons.append("push されていない commit: " + ", ".join(f"{os.path.basename(x['repo'])} {x['sha']}" for x in bad))
    return {"target": target, "found": True, "ok": not reasons, "reasons": reasons, "local": c["local"], "title": c["title"],
            "status": c["status"], "archived": c["archived"], "last_wrap": max(ev["wraps"], default=""),
            "last_turn_end": max(ev["stops"], default=""), "commits": commits, "open_ask": ask, "go_wait": gw,
            "background": bg, "unanswered_send": pend, "as_of": as_of}


def render(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        lines.append(f"{'✅ 畳んでよい' if r['ok'] else '⏸ 残す'}  {r.get('title') or r['target']} ({r.get('local') or r['target']})")
        if not r["found"]:
            lines.append("    " + r["reasons"][0])
            continue
        lines.append(f"    動き={r['status']}  最後の turn の終わり={_local_hm(r['last_turn_end']) if r['last_turn_end'] else 'なし'}"
                     f"  wrap={_local_hm(r['last_wrap']) if r['last_wrap'] else 'なし'}"
                     + ("  (archive 済み)" if r["archived"] else ""))
        if r["commits"]:
            lines.append("    commit: " + ", ".join(f"{os.path.basename(x['repo'])} {x['sha']}{'' if x['pushed'] else ' (未 push)'}"
                                                 for x in r["commits"][:8]) + (" ほか" if len(r["commits"]) > 8 else ""))
        if r.get("background") is None and not r.get("as_of"):
            lines.append("    (子の背景の作業は数えられなかった = ✅ でも app が断ることがある。 断られたら子に自分の背景の作業を並べてもらう)")
        for why in r["reasons"]:
            lines.append("    → " + why)
    return "\n".join(lines)


def turn_done_after(target: str, since: float) -> tuple[bool, str]:
    c = locate(target)
    if not c:
        return True, "見つからない"
    if c["status"] == "busy":
        return False, "動いている"
    if c["status"] == "waiting":
        return False, WAITING_TEXT
    ev = scan_child(c["path"])
    ends = [_epoch(s) for s in ev["stops"][-3:] if s]
    if (c["edge"] and c["edge"] > since) or any(e > since for e in ends):
        pend = unanswered_send(c, ev)
        if pend and c["status"] != "(not live)":  # the parent wrote again after that turn end: the child still has to answer it
            return False, f"親の {_local_hm(pend)} の message にまだ答えていない"
        if pend:  # no process to answer it: waiting would only run into the time-out; the check names the message
            return True, f"終わった (process が無い = 親の {_local_hm(pend)} の message は届いていない)"
        return True, "終わった"
    if c["status"] == "(not live)":
        return True, "process が無い (turn は始まっていない)"
    return False, "まだ始まっていない"


def last_parent_wrap(target: str) -> str:
    """The latest wrap request from the child's parent as it landed in the child's window ('' when none)."""
    c = locate(target)
    if not c or not c["parent"]:
        return ""
    ev = scan_child(c["path"])
    off = _called_off(ev, c["parent"])
    return max((ts for ts, frm in ev["peer_wraps"] if frm == c["parent"] and ts > off), default="")


def since_for(target: str, given: float | None, start: float, told: set | None = None) -> float | None:
    """The time the watch counts from for one child: the parent's last wrap request (a recent one = after the watch
    started minus RECENT_REQUEST_MIN). A given --since later than that request is lowered to it (said once). Without a
    given --since and without a recent request, None for the first DELIVERY_GRACE_S seconds (the request may not have
    landed yet = do not count the child's previous turn end), then the old default (start - 60 s)."""
    req = last_parent_wrap(target)
    req_e = _epoch(req) if req else None
    if req_e is not None and req_e < start - RECENT_REQUEST_MIN * 60:
        req_e = None  # an earlier job's request
    if given is not None:
        if req_e is not None and given > req_e:
            if told is not None and target not in told:
                told.add(target)
                print(f"↩︎ {target}: --since ({_local_hm(_iso(given))}) は親の最後の wrap の依頼 ({_local_hm(req)}) より後 = 依頼の時刻から数える")
            return req_e
        return given
    if req_e is not None:
        return req_e
    return None if time.time() - start < DELIVERY_GRACE_S else start - 60


def wait(targets: list[str], given: float | None, max_minutes: float, interval: float = 20.0,
         start: float | None = None) -> tuple[int, dict[str, float]]:
    """Wait until at least one child's turn has ended after its own start (since_for); (0, {child done: its start}) or
    (3, {}) on time-out. Measured: waiting for all of them left the child that finished first idle until the person noticed."""
    start = time.time() if start is None else start
    deadline = time.time() + max_minutes * 60
    told: set = set()
    while True:
        states, starts = {}, {}
        for t in targets:
            s0 = since_for(t, given, start, told)
            starts[t] = s0
            states[t] = (False, "依頼が子の窓に届くのを待っている") if s0 is None else turn_done_after(t, s0)
        done = {t: starts[t] for t, (d, _) in states.items() if d}
        if done:
            return 0, done
        if time.time() > deadline:
            print("⌛ 待ち切れなかった: " + ", ".join(f"{t} ({why})" for t, (d, why) in states.items() if not d))
            return 3, {}
        time.sleep(interval)


def _watch_running(local: str) -> bool:
    """A `--wait` / `--wait-due` watch on this child is running (on this machine)."""
    try:
        ps = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        ps = ""
    return any("child-wrap-check.py" in ln and "--wait" in ln and local in ln for ln in ps.splitlines())


def _roots_args() -> str:
    return " ".join("--board-root '" + r.replace(os.path.expanduser("~"), "~", 1) + "'" for r in RAW_ROOTS)


def _wait_due_cmd(locals_: list[str]) -> str:
    return (f"python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait-due {' '.join(locals_)} {_roots_args()}"
            .strip())


def _local_of(to: str) -> str:
    """A SendMessage `to` as the session's local_… id: as is, or a live session's `uds:` address looked up ('' otherwise)."""
    if to.startswith("local_"):
        return to
    if to.startswith("uds:"):
        for s_ in sm.live_sessions():
            if s_.get("address") == to and str(s_.get("host") or "").startswith("local_"):
                return s_["host"]
    return ""


def hook_sendmessage(inp: dict, rule: str) -> str:
    """additionalContext for a SendMessage that asks one's own child to wrap; '' otherwise."""
    if inp.get("tool_name") != "SendMessage":
        return ""
    ti = inp.get("tool_input") or {}
    to, msg = str(ti.get("to") or ""), str(ti.get("message") or "")
    if wrap_kind(msg) != "request":
        return ""
    to = _local_of(to)
    if not to:
        return ""
    me, child = ds.find(str(inp.get("session_id") or "")), ds.find(to)
    if not me or not child or child.get("parent") != me.get("local_id") or child.get("detached"):
        return ""  # a detached session (the chore conductor) is no longer the parent's child (measured: nudged for it)
    if _watch_running(to):
        return ""
    return ("🧺 child-wrap-check: 子 (" + (child.get("title") or to) + ") に wrap を頼んだ。 ほかの子が動いている間は、 子の turn の終わりで"
            " app はこの session を起こさない (知らせは本人の次の発言まで待たされる、 実測)。 この turn のうちに Bash を"
            f" run_in_background で `python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {to}`"
            " を出す (--since は要らない = 道具が子の窓に届いた依頼の時刻から数える。 同じ turn で複数の子に頼んだら id を並べた 1 本。 どれか 1 つが終わると見張りは終わり、 残りを続けて見張る 1 行が出る)。 子の turn が終わるとこの session が起こされ、 畳んでよいかの照合が出る。"
            + (f" 規則 = {rule}" if rule else ""))


# ---------------------------------------------------------------- board side (--finished / --hook-accept / --hook-stop)

def instance_name() -> str:
    """The board's instance for this machine (board.py writes agent@<short hostname>)."""
    return os.environ.get("CHILD_WRAP_INSTANCE") or "claude@" + socket.gethostname().split(".")[0]


def board_roots(extra: list[str] | None = None) -> list[str]:
    raw = list(extra or []) + [x for x in (os.environ.get("CHILD_WRAP_BOARD_ROOTS") or "").split(os.pathsep) if x]
    out = []
    for r in raw:
        for p in sorted(glob.glob(os.path.expanduser(r))) or [os.path.expanduser(r)]:
            if os.path.isdir(os.path.join(p, "events")) and p not in out:
                out.append(p)
    return out


def _compact(iso: str) -> str:
    """'2026-01-02T03:04:05' → '20260102T030405Z' (the board's event file names start with this)."""
    s = re.sub(r"[^0-9T]", "", iso[:19])
    return s + "Z" if len(s) == 15 else ""


def load_board(roots: list[str], since: str = "") -> list[dict]:
    prefix, out = _compact(since) if since else "", []
    for root in roots:
        for p in glob.glob(os.path.join(root, "events", "*", "*", "*.json")):
            if prefix and os.path.basename(p)[:16] < prefix:
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict):
                out.append(d)
    return out


def _actor(e: dict) -> dict:
    a = e.get("actor")
    return a if isinstance(a, dict) else {}


def board_state(cli: str, events: list[dict], instance: str, as_of: str = "") -> dict:
    """The child's requests on the board: claimed (this machine), open ones, and when the last of them was accepted."""
    evs = [e for e in events if not (as_of and str(e.get("created_at") or "")[:19] > as_of[:19])]
    by_req: dict[str, list[dict]] = collections.defaultdict(list)
    for e in evs:
        if e.get("request_id"):
            by_req[e["request_id"]].append(e)
    mine, roles = set(), set()
    for e in evs:
        a = _actor(e)
        if a.get("instance") != instance or e.get("kind") not in ("claim", "submit") or not e.get("request_id"):
            continue
        sid, m = str(a.get("session_id") or ""), ID8.match(str(a.get("task") or ""))
        if (m and m.group(1) == cli[:8]) or (cli and sid == cli):
            mine.add(e["request_id"])
            if sid and sid != cli:
                roles.add(sid)
    accepted = {rid: max(str(e.get("created_at") or "") for e in es if e.get("kind") == "accept")
                for rid, es in by_req.items() if any(e.get("kind") == "accept" for e in es)}
    open_ = sorted(r for r in mine if r not in accepted)
    for rid, es in by_req.items():
        if rid in mine or rid in accepted:
            continue
        req = next((e for e in es if e.get("kind") == "request"), None)
        tgt = str(((req or {}).get("assignee") or {}).get("session_id") or "")
        if tgt and (tgt in roles or tgt == cli):
            open_.append(rid)
    threads = {rid: str(by_req[rid][0].get("thread_id") or rid) for rid in set(mine) | set(open_) if by_req.get(rid)}
    return {"claimed": sorted(mine), "open": open_, "threads": threads,
            "accepted_at": max(accepted[r] for r in mine) if mine and not open_ else ""}


def children_of(parent_local: str) -> list[dict]:
    """App records whose spawnedFrom is the parent (touched in the last CHILD_DAYS days)."""
    out, cutoff = [], time.time() - CHILD_DAYS * 86400
    for p in glob.glob(os.path.join(ds.root(), "*", "*", "local_*.json")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
            with open(p, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        if parent_local not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        sf = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else {}
        if sf.get("sessionId") != parent_local:
            continue
        out.append({"local": str(d.get("sessionId") or ""), "cli": str(d.get("cliSessionId") or ""),
                    "title": str(d.get("title") or ""), "archived": bool(d.get("isArchived")),
                    "detached": bool(d.get("lineageDetached")), "created_ms": d.get("createdAt") or 0})
    return out


def parent_actions(parent_path: str, child_local: str, as_of: str = "") -> dict:
    """The parent's wrap requests and retractions (SendMessage, wrap_kind) and archive calls for this child (timestamps)."""
    out = {"wraps": [], "unwraps": [], "archives": []}
    if not parent_path or not child_local:
        return out
    try:
        fh = open(parent_path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            if child_local not in line or '"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ts = _ts(e)
            if not isinstance(e, dict) or e.get("type") != "assistant" or (as_of and ts[:19] > as_of[:19]):
                continue
            for b in (e.get("message") or {}).get("content") or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                name, inp = str(b.get("name") or ""), b.get("input") or {}
                to_child = name == "SendMessage" and str(inp.get("to") or "") == child_local
                kind = wrap_kind(str(inp.get("message") or "")) if to_child else ""
                if kind:
                    out["wraps" if kind == "request" else "unwraps"].append(ts)
                elif name.endswith("archive_session") and str(inp.get("session_id") or "") == child_local:
                    out["archives"].append(ts)
    return out


def finished_state(child: dict, parent_local: str, parent_path: str, events: list[dict], instance: str,
                   as_of: str = "") -> dict:
    row = dict(child, parent=parent_local, state="", accepted_at="", reasons=[], hours=None, threads={})
    b = board_state(child["cli"], events, instance, as_of)
    row["threads"], row["accepted_at"] = b["threads"], b["accepted_at"]
    if not b["claimed"]:
        row["state"] = "no-board"
        return row
    if b["open"]:
        row["state"] = "open"
        row["open"] = [b["threads"].get(r, r) for r in b["open"]]
        return row
    acts = parent_actions(parent_path, child["local"], as_of)
    if as_of and any(t[:19] <= as_of[:19] for t in acts["archives"]):
        row["state"] = "archived"
        return row
    ev = scan_child(sm.transcript_path(child["cli"]) or "", as_of)
    now = _epoch(as_of) if as_of else time.time()
    row["hours"] = round((now - _epoch(b["accepted_at"])) / 3600, 1)
    if as_of:
        busy = bool(ev["replies"]) and max(ev["replies"]) > max(ev["stops"], default="")
    else:
        busy = any((s["sessionId"] == child["cli"] or s["host"] == child["local"]) and s["status"] in ("busy", "waiting")
                   for s in sm.live_sessions())
    if busy:
        row["state"] = "busy"
        return row
    ask = open_ask(ev, parent_wait_notes(parent_path, child["local"], as_of), parent_local)
    talking = owner_after_parent(ev, parent_local, now)
    if ask:
        row["reasons"].append(_ask_text(ask))
    if talking:
        row["reasons"].append(_talking_text(talking))
    if row["reasons"]:
        if talking and talking.get("answered_at") and not ask:
            row["state"], row["answered_at"] = "answered", talking["answered_at"]
            row["answered_min"] = round((now - _epoch(talking["answered_at"])) / 60)
        elif ask and not ask["owner_only"] and not talking:
            # 判断の問いだけが残る = 規則 9 で親が答える番 (見張りに回すと、 見張りはその問いが消えるのを待ち、 親は見張りが
            # 起きるのを待つ = 互いの待ち、 実測)。 本人だけの問い・本人が子と話している途中は従来どおり残して見張る
            row["state"], row["wait_since"] = "judge", ask["at"]
        else:
            row["state"] = "owner"
            row["wait_since"] = (ask or talking or {}).get("at", "")
        return row
    landed = [ts for ts, frm in ev["peer_wraps"] if frm == parent_local]  # sent to the child's uds address too
    off = _called_off(ev, parent_local, acts["unwraps"])
    wraps = sorted(t for t in acts["wraps"] + ev["wraps"] + landed if t[:19] >= b["accepted_at"][:19] and t > off)
    # a turn end counts only when the child started replying after the request (measured: the child's previous turn
    # ended 3 s after the parent's SendMessage, before the message was delivered)
    last = wraps[-1] if wraps else ""
    if last in ev["wraps"]:
        started = last
    else:  # from the delivery of the parent's message in the child's window
        got = min((ts for ts, frm in ev["peers"] if frm == parent_local and last and ts >= last), default=last)
        started = min((r for r in ev["replies"] if got and r > got), default="")
    if not wraps:
        row["state"] = "due"
    elif started and any(s > started for s in ev["stops"]):
        row["state"] = "wrapped"
    else:
        row["state"] = "wrapping"
    return row


def finished(parent: str, roots: list[str], as_of: str = "", instance: str | None = None) -> list[dict]:
    """--finished for one parent (local_… or transcript id)."""
    prec = ds.find(parent)
    if not prec:
        return []
    kids = [c for c in children_of(prec["local_id"]) if not c["detached"] and (as_of or not c["archived"]) and c["cli"]]
    if as_of:
        kids = [c for c in kids if c["created_ms"] and _iso(c["created_ms"] / 1000) <= as_of[:19]]
    if not kids:
        return []
    since = _iso(min(c["created_ms"] for c in kids) / 1000 - 86400) if all(c["created_ms"] for c in kids) else ""
    events = load_board(roots, since)
    ppath = sm.transcript_path(prec["cli_id"]) or ""
    return [finished_state(c, prec["local_id"], ppath, events, instance or instance_name(), as_of) for c in kids]


DONE_STATES = ("due", "wrapped", "archived", "no-board", "judge")  # judge = 親が子の問いに答える番 (--wait-due はすぐ返す)


def _settled(r: dict) -> bool:
    """--wait-due ends here: the child is the parent's turn again (or gone)."""
    return r["state"] in DONE_STATES or (r["state"] == "answered" and ANSWERED_GRACE_MIN is None
                                         and r.get("answered_min", 0) >= ASK_AFTER_MIN)


def child_row(local: str) -> tuple[dict | None, dict | None]:
    """(child dict as children_of gives, parent's app record) for one child id."""
    rec = ds.find(local)
    if not rec or not rec.get("parent"):
        return None, None
    raw = _raw_record(rec)
    child = {"local": rec["local_id"], "cli": rec["cli_id"], "title": rec["title"], "archived": rec["archived"],
             "detached": bool(raw.get("lineageDetached")), "created_ms": rec.get("created_ms") or 0}
    return child, ds.find(rec["parent"])


def wait_due(targets: list[str], roots: list[str], max_minutes: float, interval: float = 60.0) -> int:
    """Wait until every child is settled (the parent's turn: fold it, or ask the person), then print the states.
    For a child that waits on the person: the person may answer in the child's window hours later, while another child
    of the parent is running, so the app's own turn-end note would not wake the parent (see the docstring)."""
    deadline = time.time() + max_minutes * 60
    while True:
        rows = []
        for t in targets:
            child, prec = child_row(t)
            if not child or not prec:
                rows.append({"local": t, "title": "", "parent": "", "state": "archived", "reasons": [], "hours": None,
                             "accepted_at": ""})
                continue
            if child["archived"]:
                rows.append(dict(child, parent=prec["local_id"], state="archived", reasons=[], hours=None, accepted_at=""))
                continue
            events = load_board(roots, _iso(child["created_ms"] / 1000 - 86400) if child["created_ms"] else "")
            rows.append(finished_state(child, prec["local_id"], sm.transcript_path(prec["cli_id"]) or "", events, instance_name()))
        settled = [r for r in rows if _settled(r)]
        if settled:  # the first child that is the parent's turn ends the watch (the rest are re-watched)
            print(f"🧺 子 {len(settled)} 件が親の番になった ({time.strftime('%H:%M')}):")
            print(render_finished(settled))
            rest = [r["local"] for r in rows if not _settled(r)]
            if rest:
                print(f"⏳ まだ親の番でない子 {len(rest)} 件 → 畳み終えたら、 続けて見張る (run_in_background): `{_wait_due_cmd(rest)}`")
            return 0
        if time.time() > deadline:
            print("⌛ 待ち切れなかった:\n" + render_finished([r for r in rows if not _settled(r)]))
            return 3
        time.sleep(interval)


def all_parents() -> list[str]:
    out, cutoff = set(), time.time() - CHILD_DAYS * 86400
    for p in glob.glob(os.path.join(ds.root(), "*", "*", "local_*.json")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        sf = d.get("spawnedFrom") if isinstance(d, dict) and isinstance(d.get("spawnedFrom"), dict) else {}
        if sf.get("sessionId") and not d.get("lineageDetached") and not d.get("isArchived"):
            out.add(sf["sessionId"])
    return sorted(out)


STATE_WORDS = {"due": "規則 10 の番 (wrap を頼んでいない)", "wrapped": "wrap は終わっている = 照合して畳む",
               "wrapping": "wrap の途中", "owner": "本人待ち = 残す", "judge": "判断の問いが残っている = 親が答える番 (規則 9)", "answered": "本人の発言に子が答え終えている (裁定待ち = 今は残す)",
               "open": "開いている依頼がある", "busy": "動いている", "no-board": "掲示板に依頼が無い", "archived": "archive 済み"}


def render_finished(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        mark = "🧺" if r["state"] in ("due", "wrapped") else "  "
        h = f"  受け取り {_local_hm(r['accepted_at'])} から {r['hours']} 時間" if r.get("hours") is not None else ""
        lines.append(f"{mark} [{r['state']}] {r['title'] or r['local']} ({r['local']})  親={r['parent']}{h}  — {STATE_WORDS.get(r['state'], '')}")
        for why in r["reasons"]:
            lines.append("      → " + why)
        if r.get("open"):
            lines.append("      → 開いている依頼: " + ", ".join(r["open"]))
    return "\n".join(lines)


def _accept_line(r: dict, rule: str, extra: str = "") -> str:
    who = f"子 {r['title'] or r['local']} ({r['local']})"
    tail = f" 規則 = {rule}" if rule else ""
    if r["state"] == "due":
        return (f"🧺 規則 10 の番: {who} の依頼を受け取った (accept)。 この子に開いている依頼は無く、 本人も待っていない。"
                " この turn のうちに規則 10 の順で畳む = model を確かめる → wrap を頼む → 同じ turn に見張り"
                f" (`python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {r['local']}`) → 起こされたら照合して archive。"
                " 次の仕事に使うなら、 この turn に次の依頼を掲示板に出す (宛先 = その子の役。 道具は開いている依頼と数える)。"
                + (f" {extra}" if extra else "") + tail)
    if r["state"] == "owner":
        return (f"🧺 {who} の依頼を受け取った。 子は本人を待っている ({'; '.join(r['reasons'])[:300]})"
                " = 規則 10 では残し、 本人に 1 行で伝える。 本人が子の窓で答えて子が終えたときに起こされるよう、 同じ turn に"
                f" Bash の run_in_background で `{_wait_due_cmd([r['local']])}` を出す (ほかの子が動いていると、 app は子の"
                " turn の終わりでこの session を起こさない)。" + tail)
    if r["state"] == "judge":
        return (f"🧺 {who} の依頼を受け取った。 子は判断の問いを残している ({'; '.join(r['reasons'])[:300]})"
                " = 規則 9 で親が答える番: 子に答えを SendMessage で送る (本人の判断が要るなら本人に 1 行で聞く)。"
                " 見張りでは待たない (答えを送れば子が続け、 終えたら照合し直す)。" + tail)
    if r["state"] == "answered" and ANSWERED_GRACE_MIN is not None:
        return (f"🧺 {who} の依頼を受け取った。 本人がこの子の窓で話した後、 子は答え終えて問いを残していない"
                f" ({'; '.join(r['reasons'])[:300]})。 本人がその窓で {ANSWERED_GRACE_MIN:g} 分話さなければ畳む番になる ="
                f" 起こされるよう Bash の run_in_background で `{_wait_due_cmd([r['local']])}` を出す。" + tail)
    if r["state"] == "answered":
        return (f"🧺 {who} の依頼を受け取った。 本人がこの子の窓で話した後、 子は答え終えて問いを残していない"
                f" ({'; '.join(r['reasons'])[:300]})。 道具は残す側 = 畳むかを本人に 1 行で聞く。" + tail)
    return ""


def hook_accept(inp: dict, roots: list[str], rule: str, extra: str = "") -> str:
    """additionalContext after `board.py accept` of a request one's own child worked on; '' otherwise."""
    if inp.get("tool_name") != "Bash":
        return ""
    cmd = str((inp.get("tool_input") or {}).get("command") or "")
    if not re.search(r"board\.py['\"]?\s+accept\b", cmd):
        return ""
    m = re.search(r"--request[= ]+['\"]?(\d{8}T\d{6}Z-[a-z]+-[0-9a-f]+)", cmd)
    me = ds.find(str(inp.get("session_id") or ""))
    if not m or not me or not roots:
        return ""
    rid, instance = m.group(1), instance_name()
    events = load_board(roots)
    workers = set()
    for e in events:
        a = _actor(e)
        if e.get("request_id") == rid and e.get("kind") in ("claim", "submit") and a.get("instance") == instance:
            mm = ID8.match(str(a.get("task") or ""))
            workers.add(mm.group(1) if mm else str(a.get("session_id") or "")[:8])
    if not workers:
        return ""
    ppath = sm.transcript_path(me["cli_id"]) or ""
    lines = []
    for c in children_of(me["local_id"]):
        if c["cli"][:8] in workers and not c["detached"] and not c["archived"]:
            line = _accept_line(finished_state(c, me["local_id"], ppath, events, instance), rule, extra)
            if line:
                lines.append(line)
    return "\n".join(lines)


def _state_file(parent_local: str) -> str:
    d = os.environ.get("CHILD_FINISHED_STATE_DIR") or STATE_DIR_DEFAULT
    return os.path.join(d, re.sub(r"[^A-Za-z0-9_.-]", "_", parent_local) + ".json")


def hook_stop(inp: dict, roots: list[str], rule: str, mode: str, extra: str = "") -> str:
    """A Stop decision (JSON) when the session ends a turn leaving a child due to be wrapped/archived; '' otherwise.
    Once per child and accept time: the second Stop for the same child is silent."""
    if mode == "off" or not roots:
        return ""
    me = ds.find(str(inp.get("session_id") or ""))
    if not me:
        return ""
    rows = finished(me["local_id"], roots)
    due = [r for r in rows if r["state"] in ("due", "wrapped", "answered", "owner", "judge") and not _watch_running(r["local"])]
    if not due:
        return ""
    path = _state_file(me["local_id"])
    try:
        with open(path, encoding="utf-8") as fh:
            seen = json.load(fh)
    except (OSError, ValueError):
        seen = {}
    def key(r: dict) -> str:
        late = (r["state"] == "answered" and ANSWERED_GRACE_MIN is None
                and r.get("answered_min", 0) >= ASK_AFTER_MIN)  # recent → watch, later → ask
        return f"{r['accepted_at']}|{r['state']}{'+' if late else ''}|{r.get('answered_at') or r.get('wait_since') or ''}"

    new = [r for r in due if seen.get(r["local"]) != key(r)]
    if not new:
        return ""
    for r in new:
        seen[r["local"]] = key(r)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(seen, fh, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    if mode == "observe":
        try:
            with open(os.path.join(os.path.dirname(path), "observe.jsonl"), "a", encoding="utf-8") as fh:
                for r in new:
                    fh.write(json.dumps({"at": _iso(time.time()), "parent": me["local_id"], "child": r["local"],
                                         "state": r["state"], "accepted_at": r["accepted_at"]}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return ""
    fold = [r for r in new if r["state"] in ("due", "wrapped")]
    ask = [r for r in new if r["state"] == "answered" and ANSWERED_GRACE_MIN is None
           and r.get("answered_min", 0) >= ASK_AFTER_MIN]
    judge = [r for r in new if r["state"] == "judge"]
    watch = [r for r in new if r not in fold and r not in ask and r not in judge]
    lines = []
    if fold:
        lines.append(f"🧺 規則 10 の番の子が {len(fold)} つ、 畳まれないまま残っている (掲示板の依頼は全部受け取り済みで、 子は動いておらず本人も待っていない):")
        for r in fold:
            lines.append(f"- {r['title'] or r['local']} ({r['local']}) — 受け取り {_local_hm(r['accepted_at'])} から {r['hours']} 時間"
                         + ("、 wrap は終わっている = 照合して archive" if r["state"] == "wrapped" else ""))
        lines.append("この turn のうちに規則 10 の順で畳む (wrap を頼む → 見張り → 照合 → archive)。 本人がこの子について別の指示を"
                     "しているなら (例 = 使用量の上限が戻るまで待つ)、 それを本人に 1 行で書いて turn を終える。"
                     + (f" {extra}" if extra else ""))
    if ask:
        lines.append(f"🧺 依頼は全部受け取り済みで、 本人がその窓で話した後に子が答え終え、 {ASK_AFTER_MIN} 分以上止まっている子が {len(ask)} つ"
                     " (規則 10 の「話している間」 に入るかは本人の裁定待ち = 道具は残す側):")
        for r in ask:
            lines.append(f"- {r['title'] or r['local']} ({r['local']}) — 子は {_local_hm(r['answered_at'])} に答え終えた")
        lines.append("畳んでよいかを本人に 1 行で聞く (子の窓で続けるなら残す)。")
    if watch:
        lines.append(f"🧺 依頼は全部受け取り済みで、 本人を待っている子"
                     + (f" か本人の発言に答え終えて {ANSWERED_GRACE_MIN:g} 分たたない子" if ANSWERED_GRACE_MIN is not None else "")
                     + f"が {len(watch)} つ (残す): "
                     + "、 ".join(f"{r['title'] or r['local']} ({r['local']})" for r in watch))
        lines.append("本人に 1 行で伝え (まだなら)、 本人が子の窓で答えて子が終えたときに起こされるよう、 Bash の run_in_background で"
                     f" `{_wait_due_cmd([r['local'] for r in watch])}` を出す (ほかの子が動いていると、 app は子の turn の終わりで"
                     " この session を起こさない)。")
    if judge:
        lines.append(f"🧺 依頼は全部受け取り済みで、 判断の問いを残している子が {len(judge)} つ (規則 9 = 親が答える番、 見張りでは待たない):")
        for r in judge:
            lines.append(f"- {r['title'] or r['local']} ({r['local']}) — " + "; ".join(r["reasons"])[:200])
        lines.append("子に答えを SendMessage で送る (本人の判断が要るなら本人に 1 行で聞く)。")
    lines.append("この知らせは子ごとに 1 回だけ。")
    if rule:
        lines.append(f"規則 = {rule}")
    return json.dumps({"decision": "block", "reason": "\n".join(lines)}, ensure_ascii=False)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="起こした子の session を畳んでよいかを照合する")
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--wait-due", action="store_true")
    # epoch seconds or ISO time (measured: a parent passed `date -u +%Y-%m-%dT%H:%M:%SZ` and the watch failed to start)
    ap.add_argument("--since", type=lambda s: float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else float(_epoch(s.rstrip("Z"))))
    ap.add_argument("--max-minutes", type=float, default=180)
    ap.add_argument("--as-of", default="")
    ap.add_argument("--no-wrap-needed", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook-sendmessage", action="store_true")
    ap.add_argument("--hook-accept", action="store_true")
    ap.add_argument("--hook-stop", action="store_true")
    ap.add_argument("--stop-mode", choices=("off", "observe", "block"))
    ap.add_argument("--finished", action="store_true")
    ap.add_argument("--parent", default="")
    ap.add_argument("--board-root", action="append", default=[])
    ap.add_argument("--rule", default="")
    ap.add_argument("--extra", default="", help="hook の文に足す 1 文 (個人層の規則の要点)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    RAW_ROOTS[:] = list(a.board_root) + [x for x in (os.environ.get("CHILD_WRAP_BOARD_ROOTS") or "").split(os.pathsep) if x]
    if a.wait_due:
        roots = board_roots(a.board_root)
        if not a.targets or not roots:
            ap.error("--wait-due には子の local_… と --board-root (か env CHILD_WRAP_BOARD_ROOTS) が要る")
        return wait_due(a.targets, roots, a.max_minutes if a.max_minutes != 180 else 720)
    if a.hook_sendmessage or a.hook_accept or a.hook_stop:
        try:
            inp = json.loads(sys.stdin.read() or "{}")
            if a.hook_stop:
                out = hook_stop(inp, board_roots(a.board_root), a.rule,
                                a.stop_mode or os.environ.get("CHILD_FINISHED_STOP") or "observe", a.extra)
                if out:
                    print(out)
                return 0
            ctx = (hook_accept(inp, board_roots(a.board_root), a.rule, a.extra) if a.hook_accept
                   else hook_sendmessage(inp, a.rule))
        except Exception:
            return 0  # fail-open
        if ctx:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}, ensure_ascii=False))
        return 0
    if a.finished:
        roots = board_roots(a.board_root)
        if not roots:
            ap.error("--finished には --board-root (か env CHILD_WRAP_BOARD_ROOTS) が要る")
        rows = [r for p in ([a.parent] if a.parent else all_parents()) for r in finished(p, roots, a.as_of)]
        print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else (render_finished(rows) or "(該当する子なし)"))
        return 1 if any(r["state"] in ("due", "wrapped") for r in rows) else 0
    if not a.targets:
        ap.error("子の local_… か transcript id を 1 つ以上")
    wrap_since, targets, rest = "", a.targets, []
    starts: dict[str, float] = {}
    if a.wait:
        rc, starts = wait(a.targets, a.since, a.max_minutes)
        if rc:
            return rc
        targets, rest = list(starts), [t for t in a.targets if t not in starts]
        print(f"🧺 子 {len(targets)} 件の turn が終わった ({time.strftime('%H:%M')})。 照合:")
    rows = [check_child(t, a.as_of, not a.no_wrap_needed, _iso(starts[t]) if t in starts else wrap_since) for t in targets]
    print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else render(rows))
    if rest:
        print(f"⏳ まだ終わっていない子 {len(rest)} 件 → 畳み終えたら、 続けて見張る (run_in_background):"
              f" `python3 ~/Claude/claude-config/scripts/child-wrap-check.py --wait {' '.join(rest)}`")
    if any(not r["found"] for r in rows):
        return 2
    return 0 if all(r["ok"] for r in rows) else 1


def selftest() -> int:
    import tempfile

    global ANSWERED_GRACE_MIN, BG_TASKS
    saved_grace, ANSWERED_GRACE_MIN = ANSWERED_GRACE_MIN, None  # the cases below were written for "keep counting"
    saved_bg, BG_TASKS = BG_TASKS, (lambda cli: [])  # no live background work unless a case says so
    fails: list[str] = []

    def ok(label: str, cond: bool) -> None:
        print(("ok: " if cond else "NG: ") + label)
        if not cond:
            fails.append(label)

    def u(ts: str, text: str, **kw) -> dict:
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **kw}

    def peer(ts: str, text: str, frm: str = "local_55555555-0000-4000-8000-000000000000") -> dict:
        # a peer session's message as the desktop app writes it: a long reminder first
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content":
                "<system-reminder>\n" + "Linked sessions now ... " * 20 + f"\n</system-reminder>\n<cross-session-message from=\"{frm}\">"
                + text + "</cross-session-message>"}}

    def peer_uds(ts: str, text: str, frm: str) -> dict:
        # a message sent to the child's uds address: from="uds:…" and from-session="local_…" (measured shape)
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content":
                "<system-reminder>\nLinked sessions now ...\n</system-reminder>\nAnother Claude session sent a message:\n"
                f"<cross-session-message from=\"uds:/tmp/cc-socks/77.sock\" from-session=\"{frm}\" from-name=\"p\" "
                f"from-mode=\"prompting\">{text}</cross-session-message>"}}

    def skill_wrap(ts: str) -> dict:
        return {"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}

    def reply(ts: str, ask: str | None = None) -> dict:
        inp = {"recap": "r"} | ({"ask": ask} if ask else {})
        return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": "w", "name": "mcp__ccd_turn__wrap_up", "input": inp}]}}

    def api_err(ts: str) -> dict:
        return {"type": "assistant", "timestamp": ts, "isApiErrorMessage": True,
                "message": {"content": [{"type": "text", "text": "API Error: Can't reach the API server"}]}}

    def stop(ts: str) -> dict:
        return {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts}

    with tempfile.TemporaryDirectory() as td:
        sdir, pdir, ddir = (os.path.join(td, x) for x in ("sessions", "projects", "desktop"))
        for d in (sdir, os.path.join(pdir, "-w"), os.path.join(ddir, "acct", "env")):
            os.makedirs(d)
        os.environ.update(CLAUDE_SESSIONS_DIR=sdir, CLAUDE_PROJECTS_DIR=pdir, CLAUDE_DESKTOP_SESSIONS_DIR=ddir,
                          CHILD_WRAP_REPOS_GLOB=os.path.join(td, "none", "*", ".git"))
        parent_l, parent_c = "local_00000000-0000-4000-8000-000000000000", "00000000-aaaa-4000-8000-000000000000"
        kids = {"answered": "11111111", "overridden": "22222222", "busy": "33333333", "nowrap": "44444444"}

        def ids(k: str) -> tuple[str, str]:
            n = kids[k]
            return f"local_{n}-0000-4000-8000-000000000000", f"{n}-cccc-4000-8000-000000000000"

        def record(local: str, cli: str, parent: str = "", **extra) -> None:
            with open(os.path.join(ddir, "acct", "env", local + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"sessionId": local, "cliSessionId": cli, "title": local[:14], "isArchived": False,
                           "spawnedFrom": {"sessionId": parent} if parent else {}, "lastTurnEdgeAt": 1000,
                           "createdAt": 1767225600000} | extra, fh)  # createdAt = 2026-01-01T00:00:00Z

        def transcript(cli: str, rows: list[dict]) -> None:
            with open(os.path.join(pdir, "-w", cli + ".jsonl"), "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

        def live(n: int, cli: str, local: str, status: str) -> None:
            with open(os.path.join(sdir, f"{n}.json"), "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "sessionId": cli, "hostSessionId": local, "cwd": "/w", "status": status}, fh)

        record(parent_l, parent_c)
        notes = []
        for n, k in enumerate(kids):
            local, cli = ids(k)
            record(local, cli, parent_l)
            live(n, cli, local, "busy" if k == "busy" else "idle")
            wrap = [{"type": "assistant", "timestamp": "2026-01-01T01:05:00Z",
                     "message": {"content": [{"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}]
            rows = [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), reply("2026-01-01T00:10:00Z"),
                    stop("2026-01-01T00:10:01Z")]
            if k in ("answered", "overridden"):
                rows += [u("2026-01-01T00:20:00Z", "要らんもの消して", origin={"kind": "human"}), reply("2026-01-01T00:29:00Z")]
                notes.append(u("2026-01-01T00:30:05Z", f"<system-reminder>\nThe session \"x\" you started ({local}) {WAIT_NOTE}. It reported\n</system-reminder>"))
                if k == "answered":
                    rows.append(u("2026-01-01T00:40:00Z", "はい、消した", origin={"kind": "human"}))
                else:
                    rows.append(peer("2026-01-01T00:40:00Z", "消さなくてよい"))
            if k != "nowrap":
                rows += wrap
            rows.append(stop("2026-01-01T01:10:00Z"))
            transcript(cli, rows)
        transcript(parent_c, notes)

        r = check_child(ids("answered")[0])
        ok("waited on the person, the person answered in the child's window → no open ask", not r["open_ask"])
        ok("... with no grace (keep counting) the person's answer is the person working there → kept as talking",
           any("話している途中" in x for x in r["reasons"]))
        ANSWERED_GRACE_MIN = DEFAULT_ANSWERED_GRACE_MIN
        ok("... answered long ago (the default grace), wrapped → ok", check_child(ids("answered")[0])["ok"])
        ok("... and the archive guard has no reason to keep it (owner_hold: no reasons, no time)",
           owner_hold(ids("answered")[0]) == {"reasons": [], "since": ""})
        ANSWERED_GRACE_MIN = None
        hold = owner_hold(ids("answered")[0])
        ok("owner_hold with no grace: the reason starts from the person's prompt in the child's window",
           hold["reasons"] and hold["since"] == max(p[0] for p in scan_child(locate(ids("answered")[0])["path"])["said"]))
        r = check_child(ids("overridden")[0])
        ok("waited on the person, only another session answered (reminder first) → kept with the ask", (not r["ok"])
           and r["open_ask"] and any("本人待ち" in x for x in r["reasons"]))
        ok("the ask is dated at the child's last reply before the note", r["open_ask"]["at"] == "2026-01-01T00:29:00Z")
        r = check_child(ids("busy")[0])
        ok("busy child → kept", (not r["ok"]) and any("動いている" in x for x in r["reasons"]))
        live(list(kids).index("busy"), ids("busy")[1], ids("busy")[0], "waiting")
        r = check_child(ids("busy")[0])
        ok("child stopped on a prompt mid-turn (waiting) → kept", (not r["ok"]) and WAITING_TEXT in r["reasons"])
        done, why = turn_done_after(ids("busy")[0], since=0)
        ok("--wait: waiting on a prompt → not done", not done and why == WAITING_TEXT)
        live(list(kids).index("busy"), ids("busy")[1], ids("busy")[0], "busy")
        r = check_child(ids("nowrap")[0])
        ok("no wrap run → kept", (not r["ok"]) and r["reasons"] == ["wrap の記録が無い"])
        ok("--no-wrap-needed drops that reason", check_child(ids("nowrap")[0], need_wrap=False)["ok"])
        # the child's live background work, and the parent's message after the child's last turn end: the app refuses
        # the archive on both while this check said "fold" (measured)
        ANSWERED_GRACE_MIN = DEFAULT_ANSWERED_GRACE_MIN
        watch = {"id": "bwatch01", "kind": "bash", "pid": 9, "what": "Watch the board request", "watch": True,
                 "persistent": False, "expires_in": None, "note": ""}
        BG_TASKS = lambda cli: [watch] if cli == ids("answered")[1] else []
        r = check_child(ids("answered")[0])
        ok("a live background watch keeps a wrapped child and names the task to stop",
           (not r["ok"]) and any("bwatch01" in x and "TaskStop" in x for x in r["reasons"]))
        BG_TASKS = lambda cli: []
        ok("... without it the same child is ok", check_child(ids("answered")[0])["ok"])

        def send(ts: str, to: str, failed: bool = False) -> list[dict]:
            i = "sm" + ts[11:19].replace(":", "")
            return [{"type": "assistant", "timestamp": ts, "message": {"content": [
                        {"type": "tool_use", "id": i, "name": "SendMessage", "input": {"to": to, "message": "ありがとう"}}]}},
                    {"type": "user", "timestamp": ts, "message": {"content": [
                        {"type": "tool_result", "tool_use_id": i,
                         "content": json.dumps({"success": not failed, "message": "queued" if not failed else "not found"})}]}}]
        transcript(parent_c, notes + send("2026-01-01T01:20:00Z", ids("answered")[0]))
        r = check_child(ids("answered")[0])
        ok("the parent's message after the child's last turn end keeps it (delivery or the next turn pending)",
           (not r["ok"]) and r["unanswered_send"] == "2026-01-01T01:20:00Z")
        done, why = turn_done_after(ids("answered")[0], since=0)
        ok("--wait: a turn end before the parent's last message is not done", not done and "まだ答えていない" in why)
        os.remove(os.path.join(sdir, f"{list(kids).index('answered')}.json"))  # the child's process is gone
        done, why = turn_done_after(ids("answered")[0], since=0)
        ok("--wait: with no process to answer the parent's message, the wait ends (the check names the message)",
           done and "届いていない" in why)
        live(list(kids).index("answered"), ids("answered")[1], ids("answered")[0], "idle")
        transcript(parent_c, notes + send("2026-01-01T01:20:00Z", ids("answered")[0], failed=True))
        ok("a message that was not delivered (success false) does not count", check_child(ids("answered")[0])["ok"])
        transcript(parent_c, notes + send("2026-01-01T01:00:00Z", ids("answered")[0]))
        ok("the parent's message before the child's last turn end does not count", check_child(ids("answered")[0])["ok"])
        legacy = [{"type": "assistant", "timestamp": "2026-01-01T01:20:00Z", "message": {"content": [
                      {"type": "tool_use", "id": "lg", "name": "mcp__ccd_session_mgmt__send_message",
                       "input": {"session_id": ids("answered")[0], "message": "ありがとう"}}]}},
                  {"type": "user", "timestamp": "2026-01-01T01:20:01Z", "message": {"content": [
                      {"type": "tool_result", "tool_use_id": "lg", "content": "queued (delivery: queued; message_id: x)"}]}}]
        transcript(parent_c, notes + legacy)
        ok("the app's older send_message to the child counts too", check_child(ids("answered")[0])["unanswered_send"] != "")
        legacy[1]["message"]["content"][0]["content"] = "not found (delivery: undelivered; message_id: x)"
        transcript(parent_c, notes + legacy)
        ok("... unless it says it was not delivered", check_child(ids("answered")[0])["ok"])
        BG_TASKS = lambda cli: None
        ok("background work that could not be counted is said, without keeping the child",
           check_child(ids("answered")[0])["ok"] and "数えられなかった" in render([check_child(ids("answered")[0])]))
        BG_TASKS = lambda cli: []
        transcript(parent_c, notes)
        ANSWERED_GRACE_MIN = None
        # hand-off step 0: the worker's first turn stops because its model/effort differ and waits for the requester's go;
        # the app tells the parent it waits on the person, and the go is a peer message, not the person's prompt
        gw_l, gw_c = "local_77777777-0000-4000-8000-000000000000", "77777777-cccc-4000-8000-000000000000"
        record(gw_l, gw_c, parent_l)
        live(91, gw_c, gw_l, "idle")

        def bash(ts: str, cmd: str) -> dict:
            return {"type": "assistant", "timestamp": ts, "message": {"content": [
                {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": cmd}}]}}

        step0 = [{"type": "user", "timestamp": "2026-01-01T00:00:00Z", "promptSource": "sdk", "message": {"role": "user", "content":
                  "board の worker として。 This window must run on opus at max effort. 0. session-model.py self を読み、 違えば止まる"}},
                 bash("2026-01-01T00:00:05Z", "python3 /x/session-model.py self; echo ---"),
                 reply("2026-01-01T00:00:10Z", ask="effort を直してから go を"), stop("2026-01-01T00:00:12Z")]
        gw_note = u("2026-01-01T00:00:20Z", f"<system-reminder>\nThe session \"g\" you started ({gw_l}) {WAIT_NOTE}. It reported\n</system-reminder>")
        after_go = [peer("2026-01-01T00:05:00Z", "go", parent_l), bash("2026-01-01T00:05:05Z", "python3 /x/session-model.py self"),
                    bash("2026-01-01T00:05:10Z", "python3 /x/board.py claim --root /b --request r"), reply("2026-01-01T00:40:00Z"),
                    skill_wrap("2026-01-01T00:50:00Z"), stop("2026-01-01T00:55:00Z")]
        transcript(gw_c, step0 + after_go)
        transcript(parent_c, notes + [gw_note])
        r = check_child(gw_l)
        ok("step 0: the go came from the parent, the work and the wrap are done → ok (not the person's ask)",
           r["ok"] and not r["open_ask"] and not r["go_wait"])
        ok("step 0: the archive guard's owner reasons are empty", owner_reasons(gw_l) == [])
        transcript(gw_c, step0)
        r = check_child(gw_l, need_wrap=False)
        ok("step 0, no go yet → kept as waiting for the requester's go, not as the person's ask",
           (not r["ok"]) and not r["open_ask"] and r["go_wait"] and any("go を待って" in x for x in r["reasons"])
           and not any("本人待ちの問い" in x for x in r["reasons"]))
        ok("step 0, no go yet: the archive guard does not read it as the person's ask", owner_reasons(gw_l) == [])
        claim_first = bash("2026-01-01T00:00:07Z", "python3 /x/board.py claim --root /b --request r")
        transcript(gw_c, step0[:2] + [claim_first] + step0[2:] + [peer("2026-01-01T00:05:00Z", "go")]
                   + [reply("2026-01-01T00:40:00Z"), stop("2026-01-01T00:41:00Z")])
        r = check_child(gw_l, need_wrap=False)
        ok("control: the model check, a claim and an ask in one turn → the person's ask stays (only another session answered)",
           (not r["ok"]) and r["open_ask"] and r["open_ask"]["at"] == "2026-01-01T00:00:10Z")
        later_ask = [reply("2026-01-01T00:15:00Z"), stop("2026-01-01T00:15:05Z"), peer("2026-01-01T00:20:00Z", "これも見て", parent_l),
                     reply("2026-01-01T00:30:00Z", ask="どちらにしますか"), stop("2026-01-01T00:30:05Z"), peer("2026-01-01T00:35:00Z", "B で")]
        transcript(gw_c, step0 + after_go[:3] + later_ask)
        r = check_child(gw_l, need_wrap=False)
        ok("control: a later turn (no model check in it) asks the person, only another session answered → the ask stays",
           (not r["ok"]) and r["open_ask"] and r["open_ask"]["at"] == "2026-01-01T00:30:00Z" and not r["go_wait"])
        transcript(gw_c, step0 + after_go[:3] + later_ask[:5] + [u("2026-01-01T00:35:00Z", "B で", origin={"kind": "human"})])
        ok("control: the same later ask answered by the person in the child's window → no open ask",
           not check_child(gw_l, need_wrap=False)["open_ask"])
        no_board = [step0[0], bash("2026-01-01T00:00:05Z", "python3 /x/session-model.py self"), reply("2026-01-01T00:02:00Z"),
                    stop("2026-01-01T00:02:05Z"), peer("2026-01-01T00:20:00Z", "これも見て", parent_l),
                    reply("2026-01-01T00:30:00Z", ask="どちらにしますか"), stop("2026-01-01T00:30:05Z"), peer("2026-01-01T00:35:00Z", "B で")]
        transcript(gw_c, no_board)
        ok("control: a worker that never claims (no board) checked its model in an earlier turn → its later ask stays",
           bool(check_child(gw_l, need_wrap=False)["open_ask"]))
        no_handoff = [u("2026-01-01T00:00:00Z", "これを調べて", origin={"kind": "human"}),
                      bash("2026-01-01T00:00:05Z", "python3 /x/session-model.py self"), reply("2026-01-01T00:00:10Z", ask="どちらにしますか"),
                      stop("2026-01-01T00:00:12Z"), peer("2026-01-01T00:05:00Z", "B で")]
        transcript(gw_c, no_handoff)
        r = check_child(gw_l, need_wrap=False)
        ok("control: no board hand-off in the window, the model check and an ask in its first turn → the person's ask stays",
           bool(r["open_ask"]) and not r["go_wait"])
        # A late note: the child stopped on the person, the person answered in the child's window and the child went on, and the
        # note about the first stop landed in the parent's window during that later turn (measured: read at its landing, the
        # answered ask looked open and kept a finished child)
        ev_late = {"asks": [("2026-01-01T01:08:00Z", "どちらにしますか")], "first": "2026-01-01T00:59:00Z",
                   "replies": ["2026-01-01T01:00:00Z", "2026-01-01T01:08:00Z", "2026-01-01T01:23:00Z", "2026-01-01T01:32:00Z",
                               "2026-01-01T01:35:00Z"],
                   "stops": ["2026-01-01T01:08:30Z", "2026-01-01T01:40:00Z"], "human": ["2026-01-01T01:22:00Z"], "peers": [],
                   "step0_handoff": False, "model_checks": [], "claims": []}
        late = ["2026-01-01T01:32:30Z"]
        ok("a late note (the child's next turn was running) is dated at the turn it reported",
           ("2026-01-01T01:08:30Z", "", "2026-01-01T01:32:30Z") in _wait_points(ev_late, late))
        ok("a late note: the person's answer after that turn closes the ask", open_ask(ev_late, late, parent_l) is None)
        ev_on = dict(ev_late, replies=ev_late["replies"][:2], stops=ev_late["stops"][:1], human=[])
        a_on = open_ask(ev_on, ["2026-01-01T01:09:00Z"], parent_l)
        ok("a note that landed right after the turn end is dated at the last reply before it (as before)",
           bool(a_on) and a_on["at"] == "2026-01-01T01:08:00Z")
        ev_held = dict(ev_late, asks=[("2026-01-01T01:08:00Z", "この候補を当てますか")], human=[],
                       peers=[("2026-01-01T01:22:00Z", parent_l)])
        a_held = open_ask(ev_held, late, parent_l)
        ok("当てますか is the person's to answer: the parent's message does not close it",
           bool(a_held) and a_held["owner_only"])
        ok("the reason names both times when the note landed late (the stop and the landing)",
           "その知らせが親の窓に着いたのは" in _ask_text(a_held) and _local_hm("2026-01-01T01:08:30Z") in _ask_text(a_held))
        # The requester answers the child's questions of judgment (CONTRACT.md#worker-questions-to-requester): its message in
        # the child's window after the ask closes it; an approval or a send to the outside stays the person's.

        def asked(ask: str, answer: dict) -> list[dict]:
            return [u("2026-01-01T00:00:00Z", "これを調べて", origin={"kind": "human"}), reply("2026-01-01T00:10:00Z", ask=ask),
                    stop("2026-01-01T00:10:05Z"), answer]
        transcript(gw_c, asked("run-all-checks に変異の試験の段を足すか", peer("2026-01-01T00:15:00Z", "足さない", parent_l)))
        r = check_child(gw_l, need_wrap=False)
        ok("the parent answered a question of judgment in the child's window → no open ask", r["ok"] and not r["open_ask"])
        ok("the parent answered a question of judgment: the archive guard does not keep the child", owner_reasons(gw_l) == [])
        transcript(gw_c, asked("どちらにしますか", peer_uds("2026-01-01T00:15:00Z", "B で", parent_l)))
        ok("the parent's answer sent to the child's uds address counts too", not check_child(gw_l, need_wrap=False)["open_ask"])
        transcript(gw_c, asked("この下書きを送信してよいか", peer("2026-01-01T00:15:00Z", "送って", parent_l)))
        r = check_child(gw_l, need_wrap=False)
        ok("an ask to send outside, answered only by the parent → stays the person's",
           (not r["ok"]) and bool(r["open_ask"]) and r["open_ask"]["owner_only"] and any("本人だけが答えられる" in x for x in r["reasons"]))
        transcript(gw_c, asked("表題の変更を承認しますか", peer("2026-01-01T00:15:00Z", "はい", parent_l)))
        ok("an approval ask, answered only by the parent → the archive guard keeps it",
           any("本人だけが答えられる" in x for x in owner_reasons(gw_l)))
        transcript(gw_c, asked("どちらにしますか", peer("2026-01-01T00:15:00Z", "B で")))
        r = check_child(gw_l, need_wrap=False)
        ok("a question of judgment answered by another session (not the parent) → stays",
           (not r["ok"]) and bool(r["open_ask"]) and not r["open_ask"]["owner_only"])
        transcript(gw_c, [u("2026-01-01T00:00:00Z", "これを調べて", origin={"kind": "human"}), peer("2026-01-01T00:05:00Z", "B で", parent_l),
                          reply("2026-01-01T00:10:00Z", ask="どちらにしますか"), stop("2026-01-01T00:10:05Z")])
        ok("the parent's message before the ask does not answer it", bool(check_child(gw_l, need_wrap=False)["open_ask"]))
        # The app's continuation after a compaction in the child's window is not the person talking (measured: a wrapped child
        # with no question was kept from the archive by it)
        transcript(gw_c, [u("2026-01-01T00:00:00Z", "これを調べて", origin={"kind": "human"}), peer("2026-01-01T00:20:00Z", "wrap して", parent_l),
                          skill_wrap("2026-01-01T00:21:00Z"), reply("2026-01-01T00:25:00Z"), stop("2026-01-01T00:25:05Z"),
                          {"type": "user", "isCompactSummary": True, "timestamp": "2026-01-01T00:30:00Z", "message": {"role": "user",
                           "content": "This session is being continued from a previous conversation that ran out of context."}},
                          reply("2026-01-01T00:31:00Z"), stop("2026-01-01T00:31:05Z")])
        r = check_child(gw_l)
        ok("a compaction summary in the child's window after the parent's message is not the person talking → ok",
           r["ok"] and owner_reasons(gw_l) == [])
        transcript(parent_c, notes)
        sf_l, sf_c = "local_66666666-0000-4000-8000-000000000000", "66666666-cccc-4000-8000-000000000000"
        record(sf_l, sf_c, parent_l)
        live(90, sf_c, sf_l, "idle")
        prev_job = [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), peer("2026-01-01T00:50:00Z", "前の仕事は wrap して", parent_l),
                    skill_wrap("2026-01-01T00:51:00Z"), stop("2026-01-01T00:55:00Z")]
        new_wrap = [peer("2026-01-01T01:00:00Z", "wrap して", parent_l), skill_wrap("2026-01-01T01:01:00Z"),
                    reply("2026-01-01T01:04:00Z"), stop("2026-01-01T01:05:00Z")]
        transcript(sf_c, prev_job + new_wrap)
        st = _epoch("2026-01-01T01:06:00")
        req = _epoch("2026-01-01T01:00:00")
        ok("old behaviour reproduced: --since after the request (10 minutes before 'now') → 'no wrap' ⏸ (+ the hint)",
           any(x.startswith("wrap の記録が無い") and "--since が wrap の依頼より後" in x
               for x in check_child(sf_l, wrap_since="2026-01-01T01:03:00")["reasons"]))
        ok("fix: a --since 3 minutes after the request ('10 分前' case) is lowered to the request", since_for(sf_l, _epoch("2026-01-01T01:03:00"), st) == req)
        ok("fix: a --since seconds after the request ('$(date +%s)' case) is lowered too", since_for(sf_l, req + 5, st) == req)
        ok("fix: no --since → the request time from the child's window", since_for(sf_l, None, st) == req)
        rc_s, got = wait([sf_l], None, 0.001, 0, start=st)
        ok("fix: --wait without --since → done, and the check counts this wrap (not 'no wrap')", rc_s == 0 and got.get(sf_l) == req
           and not any(x.startswith("wrap の記録が無い") for x in check_child(sf_l, wrap_since=_iso(got[sf_l]))["reasons"]))
        ok("a --since earlier than the request is kept", since_for(sf_l, req - 600, st) == req - 600)
        transcript(sf_c, prev_job + [peer("2026-01-01T01:00:00Z", "wrap して", parent_l)])
        ok("previous job: its turn end does not count for the new request (not done yet)",
           not turn_done_after(sf_l, since_for(sf_l, None, st))[0])
        ok("previous job: its wrap run does not count, and no '--since too late' hint",
           [x for x in check_child(sf_l, wrap_since="2026-01-01T01:00:00")["reasons"] if x.startswith("wrap の記録")] == ["wrap の記録が無い"])
        ok("a request older than the recent window is an earlier job's → the old default", since_for(sf_l, None, _epoch("2026-01-01T02:00:00"))
           == _epoch("2026-01-01T02:00:00") - 60)
        transcript(sf_c, prev_job[:1])
        ok("no request yet, watch just started → wait for it to land (None)", since_for(sf_l, None, time.time()) is None)
        uds_rows = [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), peer("2026-01-01T00:30:00Z", "これも見て", parent_l),
                    u("2026-01-01T00:50:00Z", "ここ直して", origin={"kind": "human"}), reply("2026-01-01T00:55:00Z"), stop("2026-01-01T00:55:01Z"),
                    peer_uds("2026-01-01T01:00:00Z", "終わったので wrap して", parent_l), skill_wrap("2026-01-01T01:01:00Z"),
                    stop("2026-01-01T01:05:00Z")]
        transcript(sf_c, uds_rows)
        ev_u = scan_child(os.path.join(pdir, "-w", sf_c + ".jsonl"))
        ok("uds: the parent's message sent to the uds address counts as the parent's (peers and wrap request)",
           ("2026-01-01T01:00:00Z", parent_l) in ev_u["peers"] and ("2026-01-01T01:00:00Z", parent_l) in ev_u["peer_wraps"])
        ok("the person spoke 5 minutes before the parent's wrap request → still 'talking' (the request does not end it)",
           any("話している途中" in x and "では本人の話は終わらない" in x for x in check_child(sf_l, need_wrap=False)["reasons"]))
        ok("the default grace is the owner's ruling (10 minutes)", DEFAULT_ANSWERED_GRACE_MIN == 10.0)
        ANSWERED_GRACE_MIN = DEFAULT_ANSWERED_GRACE_MIN
        ok("... grace 10: 8 minutes after the child answered → still 'talking'",
           any("話している途中" in x for x in check_child(sf_l, as_of="2026-01-01T01:03:00", need_wrap=False)["reasons"]))
        ok("... grace 10: 11 minutes after the child answered → not 'talking' (it was still 'talking' under 30)",
           not any("話している途中" in x for x in check_child(sf_l, as_of="2026-01-01T01:06:00", need_wrap=False)["reasons"]))
        ok("... owner_hold replays the same scene: 8 minutes → kept from the person's prompt, 11 minutes → nothing",
           owner_hold(sf_l, as_of="2026-01-01T01:03:00")["since"].startswith("2026-01-01T00:50:00")
           and owner_hold(sf_l, as_of="2026-01-01T01:06:00") == {"reasons": [], "since": ""})
        ANSWERED_GRACE_MIN = 30
        ok("... an explicit grace of 30 (env) still holds at 11 minutes",
           any("話している途中" in x for x in check_child(sf_l, as_of="2026-01-01T01:06:00", need_wrap=False)["reasons"]))
        ANSWERED_GRACE_MIN = None
        ok("uds: --wait counts from the uds-delivered request", since_for(sf_l, None, st) == req)
        transcript(sf_c, uds_rows[:5] + [stop("2026-01-01T01:05:00Z")])
        ok("uds control: without the uds message the person's prompt after the parent's last message is 'talking'",
           any("話している途中" in x for x in check_child(sf_l, need_wrap=False)["reasons"]))
        with open(os.path.join(sdir, "90.json"), "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "sessionId": sf_c, "hostSessionId": sf_l, "cwd": "/w", "status": "idle",
                       "messagingSocketPath": "/tmp/cc-socks/77.sock"}, fh)
        hk = {"tool_name": "SendMessage", "session_id": parent_c, "tool_input": {"to": "uds:/tmp/cc-socks/77.sock", "message": "wrap して"}}
        out_h = hook_sendmessage(hk, "")
        ok("hook: a wrap request to the child's uds address → the nudge with the child's id and no --since",
           "--wait " + sf_l in out_h and "--since " not in out_h.split("`")[1])
        ok("after --wait, a wrap from an earlier request does not count",
           not check_child(ids("busy")[0], wrap_since="2026-01-01T02:00:00")["ok"]
           and any(x.startswith("wrap の記録が無い") for x in check_child(ids("busy")[0], wrap_since="2026-01-01T02:00:00")["reasons"]))
        talk = [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), peer("2026-01-01T01:00:00Z", "wrap して終えて", parent_l),
                {"type": "attachment", "timestamp": "2026-01-01T01:02:00Z", "attachment": {
                    "type": "queued_command", "origin": {"kind": "human"}, "prompt": "どうやって消すの？"}},
                {"type": "assistant", "timestamp": "2026-01-01T01:05:00Z",
                 "message": {"content": [{"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}},
                stop("2026-01-01T01:10:00Z")]
        transcript(ids("nowrap")[1], talk)
        r = check_child(ids("nowrap")[0])
        ok("the person spoke in the child's window after the parent's wrap request → kept", (not r["ok"])
           and any("話している途中" in x and "どうやって" in x for x in r["reasons"]))
        ok("... and the child's answer (turn end, no question) is shown", any("答えて turn を終え" in x for x in r["reasons"]))
        ANSWERED_GRACE_MIN = DEFAULT_ANSWERED_GRACE_MIN
        ok("with a grace (the owner's call), an answered prompt long ago no longer keeps the child", check_child(ids("nowrap")[0])["ok"])
        ANSWERED_GRACE_MIN = None
        transcript(ids("nowrap")[1], talk[:2] + talk[3:])
        ok("no word of the person after the parent's request → ok", check_child(ids("nowrap")[0])["ok"])
        retry = talk[:2] + [api_err("2026-01-01T01:01:00Z"),
                            u("2026-01-01T01:02:00Z", "<system-reminder>\nLinked sessions now ...\n</system-reminder>\n\nTry again"),
                            reply("2026-01-01T01:04:00Z")] + talk[3:]
        transcript(ids("nowrap")[1], retry)
        ok("the app's 'Try again' after an API error is not the person talking", check_child(ids("nowrap")[0])["ok"])
        transcript(ids("nowrap")[1], talk[:2] + [u("2026-01-01T01:02:00Z", "Try again", origin={"kind": "human"})] + talk[3:])
        ok("'Try again' typed with no API error before it still counts", not check_child(ids("nowrap")[0])["ok"])
        transcript(ids("nowrap")[1], [u("2026-01-01T00:00:00Z", "依頼", origin={"kind": "human"}), stop("2026-01-01T01:10:00Z")])
        r = check_child(ids("overridden")[0], as_of="2026-01-01T00:25:00")
        ok("--as-of before the wait → no open ask yet", r["open_ask"] is None)
        transcript(ids("answered")[1], [reply("2026-01-01T00:10:00Z", ask="デスクトップはこのまま?"), stop("2026-01-01T00:10:01Z")])
        r = check_child(ids("answered")[0], need_wrap=False)
        ok("a wrap_up ask with no later prompt of the person → open ask with its text", r["open_ask"] and "デスクトップ" in r["open_ask"]["ask"])
        repo = os.path.join(td, "repos", "r")
        os.makedirs(repo)
        os.environ["CHILD_WRAP_REPOS_GLOB"] = os.path.join(td, "repos", "*", ".git")
        for cmd in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                    "--allow-empty", "-m", f"x\n\nAgent-Session: claude:{ids('nowrap')[1]}"]):
            subprocess.run(["git", "-C", repo, *cmd], check=True, capture_output=True)
        r = check_child(ids("nowrap")[0], need_wrap=False)
        ok("the child's commit found by its trailer, not pushed → kept", len(r["commits"]) == 1
           and any("push されていない" in x for x in r["reasons"]))
        os.environ["CHILD_WRAP_REPOS_GLOB"] = os.path.join(td, "none", "*", ".git")
        ok("missing child → not found", not check_child("local_99999999-0000-4000-8000-000000000000")["found"])
        hook = {"tool_name": "SendMessage", "session_id": parent_c,
                "tool_input": {"to": ids("answered")[0], "message": "wrap skill で仕上げて"}}
        ok("hook: wrap request to own child → nudge with --wait and the id", ids("answered")[0] in hook_sendmessage(hook, "R")
           and "--wait" in hook_sendmessage(hook, "R"))
        hook["tool_input"] = {"to": ids("answered")[0], "message": "終わったので wrapして"}
        ok("hook: 'wrap' followed by kana still counts", "--wait" in hook_sendmessage(hook, ""))
        hook["tool_input"] = {"to": ids("answered")[0], "message": "進み具合は? unwrapped な値も見て"}
        ok("hook: other message (and 'unwrapped') → silent", hook_sendmessage(hook, "") == "")
        record(ids("nowrap")[0], ids("nowrap")[1], "local_77777777-0000-4000-8000-000000000000")
        hook["tool_input"] = {"to": ids("nowrap")[0], "message": "wrap して"}
        ok("hook: someone else's child → silent", hook_sendmessage(hook, "") == "")
        record(ids("nowrap")[0], ids("nowrap")[1], parent_l, lineageDetached=True)
        hook["tool_input"] = {"to": ids("nowrap")[0], "message": "wrap skill を起動して、 知見を上の層へ移してください"}
        ok("hook: a real wrap request to a session detached from this parent → silent", hook_sendmessage(hook, "") == "")
        record(ids("nowrap")[0], ids("nowrap")[1], "local_77777777-0000-4000-8000-000000000000")
        mentions = [  # measured shapes: none of these asked for a wrap
            "道具の件 (返事は不要): hook の child-wrap-check が、 子でない session への SendMessage にも"
            "「子に wrap を頼んだ、 見張りを出せ」 と出る (どれも wrap は頼んでいない)。",
            "読み違い 1 件: child-wrap-check.py が、 go の後に仕事も wrap も済んだ worker の archive を止めた。",
            "追加の 1 件: 要約の続きを本人の発言と読み、 wrap 済みで問いの無い子の archive を止めた。",
            "提案: 起こした直後に背景の見張り (`child-wrap-check.py --wait <id>`) を出す。",
            "締めの thread today:wrap の件で、 その file を手放しました。",
            "wrap の依頼は取り消します。 本人はまだこの窓で仕事中です。 wrap を止めて、 次の指示を待ってください。",
            "前の依頼の分の wrap は、 この次の依頼が終わってからまとめてで構いません。",
            "そちらが wrap で直すならそのまま進めてください。",
        ]
        for i, msg in enumerate(mentions):
            hook["tool_input"] = {"to": ids("answered")[0], "message": msg}
            ok(f"hook: a mention, not a request ({i}) → silent", hook_sendmessage(hook, "") == "")
        requests = [
            "wrap をお願いします: `wrap` skill を起動して、 知見を上の層の正本へ移してください。",
            "/wrap — 提出を受け取りました。 仕上げをしてください。",
            "(2) そのあと `wrap` skill で、 この仕事の知見を上の層の正本へ移し、 移した先を報告してください。",
            "この依頼の分の wrap（知見を上の層へ、 SESSION・TODO、 commit + push）をして、 終わったら知らせてください。",
            "受け取りました。 /wrap で締めて turn を終えてください。",
            "問いが残っていなければ wrap skill を起動して。 問いが残っているなら、 wrap せずにそれを返してください。",
        ]
        for i, msg in enumerate(requests):
            hook["tool_input"] = {"to": ids("answered")[0], "message": msg}
            ok(f"hook: a wrap request ({i}) → nudge", "--wait" in hook_sendmessage(hook, ""))
        ok("wrap_kind: a retraction", wrap_kind(mentions[5]) == "retract"
           and wrap_kind("wrap はまだしなくて構いません。") == "retract" and wrap_kind("さきほどの /wrap は取り消します。") == "retract")
        ok("wrap_kind: a report or a name is neither", wrap_kind(mentions[2]) == "" and wrap_kind(mentions[3]) == "")
        ok("wrap_kind: a retraction then a new request → request",
           wrap_kind("さきほどの wrap は取り消します。 区切りが付いたら wrap をお願いします。") == "request")
        done, _ = turn_done_after(ids("overridden")[0], since=_epoch("2026-01-01T01:00:00"))
        ok("--wait: idle with a turn end after since → done", done)
        done, why = turn_done_after(ids("overridden")[0], since=_epoch("2026-01-01T02:00:00"))
        ok("--wait: idle, last turn end before since → not started yet", not done and why == "まだ始まっていない")
        done, why = turn_done_after(ids("busy")[0], since=0)
        ok("--wait: busy → not done", not done and why == "動いている")
        rc_w, first = wait([ids("busy")[0], ids("overridden")[0]], _epoch("2026-01-01T01:00:00"), 0.001, 0)
        ok("--wait: one child done, another still busy → ends with the done one", rc_w == 0 and list(first) == [ids("overridden")[0]])

        # ---- board side: a fresh parent with its own children (B-cases) ----
        board = os.path.join(td, "board")
        os.environ.update(CHILD_WRAP_INSTANCE="claude@testhost", CHILD_FINISHED_STATE_DIR=os.path.join(td, "state"))
        bp_l, bp_c = "local_b0000000-0000-4000-8000-000000000000", "b0000000-aaaa-4000-8000-000000000000"
        record(bp_l, bp_c)
        seq = [0]

        def event(kind: str, rid: str, at: str, task: str = "", sid: str = "", inst: str = "claude@testhost", **kw) -> None:
            seq[0] += 1
            d = os.path.join(board, "events", "proj", "t-" + rid)
            os.makedirs(d, exist_ok=True)
            eid = f"{_compact(at)}-claude-{seq[0]:06x}"
            with open(os.path.join(d, f"{_compact(at)}--{eid}.json"), "w", encoding="utf-8") as fh:
                json.dump({"event_id": eid, "thread_id": "t-" + rid, "kind": kind, "created_at": at + "Z", "request_id": rid,
                           "actor": {"agent": "claude", "task": task, "instance": inst, "session_id": sid}} | kw, fh)

        def kid(n: str, rows_: list[dict], status: str = "idle", **extra) -> tuple[str, str]:
            local, cli = f"local_{n}-0000-4000-8000-000000000000", f"{n}-cccc-4000-8000-000000000000"
            record(local, cli, bp_l, **extra)
            live(int(n[:6], 16) % 100000 + 100, cli, local, status)
            transcript(cli, rows_)
            return local, cli

        base = [u("2026-01-02T00:00:00Z", "依頼", origin={"kind": "human"}), reply("2026-01-02T01:00:00Z"), stop("2026-01-02T01:00:01Z")]
        R = {k: f"20260102T000000Z-claude-{i:06x}" for i, k in enumerate(["due", "open", "reuse", "owner", "retry", "said", "far", "wrapd",
                                                                        "judge"])}
        cases = {}
        for k, n in [("due", "c1000001"), ("open", "c1000002"), ("reuse", "c1000003"), ("owner", "c1000004"),
                     ("retry", "c1000005"), ("said", "c1000006"), ("far", "c1000007"), ("wrapd", "c1000008"),
                     ("judge", "c100000b")]:
            role = f"role-proj-{k}"
            event("request", R[k], "2026-01-02T00:00:00", task="parent", sid=bp_c, assignee={"agent": "claude", "session_id": role})
            event("claim", R[k], "2026-01-02T00:01:00", task=f"{n} (opus)", sid=role,
                  inst="claude@otherhost" if k == "far" else "claude@testhost")
            event("submit", R[k], "2026-01-02T00:50:00", task=f"{n} (opus)", sid=role,
                  inst="claude@otherhost" if k == "far" else "claude@testhost")
            if k != "open":
                event("accept", R[k], "2026-01-02T01:10:00", task="b0000000 (opus)", sid="role-proj-owner-review")
            rows_ = list(base)
            if k == "owner":
                rows_ = base[:1] + [reply("2026-01-02T01:00:00Z", ask="送ってよいですか?"), stop("2026-01-02T01:00:01Z")]
            if k == "judge":
                rows_ = base[:1] + [reply("2026-01-02T01:00:00Z", ask="どちらの案にしますか?"), stop("2026-01-02T01:00:01Z")]
            if k in ("retry", "said"):
                rows_ = base[:1] + [peer("2026-01-02T00:30:00Z", "続けて", bp_l)]
                if k == "retry":
                    rows_ += [api_err("2026-01-02T00:40:00Z"), u("2026-01-02T00:41:00Z", "Try again")]
                else:
                    rows_ += [u("2026-01-02T00:41:00Z", "全部当てて", origin={"kind": "human"})]
                rows_ += [reply("2026-01-02T01:00:00Z"), stop("2026-01-02T01:00:01Z")]
            if k == "wrapd":
                rows_ = base + [{"type": "assistant", "timestamp": "2026-01-02T01:20:00Z", "message": {"content": [
                    {"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}, stop("2026-01-02T01:30:00Z")]
            cases[k] = kid(n, rows_)
        event("request", "20260102T020000Z-claude-0000ff", "2026-01-02T02:00:00", task="parent", sid=bp_c,
              assignee={"agent": "claude", "session_id": "role-proj-reuse"})  # the next request to the same role = reuse
        rl, rc_ = kid("c100000a", base + [reply("2026-01-02T01:20:01Z"), stop("2026-01-02T01:20:03Z"),
                                          peer("2026-01-02T01:20:04Z", "wrap して", bp_l)])
        event("claim", "20260102T000000Z-claude-0000dd", "2026-01-02T00:01:00", task="c100000a (opus)", sid="role-proj-race")
        event("accept", "20260102T000000Z-claude-0000dd", "2026-01-02T01:10:00", task="x", sid="x")
        transcript(bp_c, [{"type": "assistant", "timestamp": "2026-01-02T01:20:00Z", "message": {"content": [
            {"type": "tool_use", "id": "m", "name": "SendMessage", "input": {"to": rl, "message": "wrap して"}}]}}])
        dl, dc = kid("c1000009", list(base), lineageDetached=True)
        event("claim", "20260102T000000Z-claude-0000ee", "2026-01-02T00:01:00", task="c1000009 (opus)", sid="role-proj-chore")
        event("accept", "20260102T000000Z-claude-0000ee", "2026-01-02T01:10:00", task="x", sid="x")
        rows = {r["local"]: r for r in finished(bp_l, [board])}
        st = {k: rows.get(v[0], {}).get("state") for k, v in cases.items()}
        ok("finished: all accepted, idle, no wrap asked → due", st["due"] == "due")
        ok("finished: a claimed request not accepted → open", st["open"] == "open")
        ok("finished: a new request posted to the child's role (reuse) → open", st["reuse"] == "open")
        ok("finished: the child asked the person and no answer → owner", st["owner"] == "owner")
        ok("finished: only a question of judgment left → judge (the parent's turn, rule 9)", st["judge"] == "judge")
        ok("finished: only the app's 'Try again' after the parent's message → due", st["retry"] == "due")
        ok("finished: the person spoke and the child answered → answered (kept, owner's call)", st["said"] == "answered")
        ok("finished: claimed on another machine → no-board", st["far"] == "no-board")
        ok("finished: wrap ran after the accept and the child stopped → wrapped", st["wrapd"] == "wrapped")
        ok("finished: a detached child (chore conductor) is not counted", dl not in rows)
        ok("finished: the child's previous turn ended just after the parent's wrap request → wrapping, not wrapped",
           rows.get(rl, {}).get("state") == "wrapping")
        ok("finished --as-of before the accept → open", {r["local"]: r["state"] for r in finished(
            bp_l, [board], as_of="2026-01-02T01:05:00")}.get(cases["due"][0]) == "open")
        stop_in = {"hook_event_name": "Stop", "session_id": bp_c}
        out = hook_stop(stop_in, [board], "R", "block")
        d = json.loads(out) if out else {}
        why = d.get("reason", "")
        fold_part = why.split("話している間")[0]
        ok("hook-stop: due + wrapped children → block naming them in the 'fold' part, not the owner-waiting one",
           d.get("decision") == "block" and cases["due"][0] in fold_part and cases["wrapd"][0] in fold_part
           and cases["retry"][0] in fold_part and cases["owner"][0] not in fold_part)
        ok("hook-stop: the owner-waiting child → 'keep, tell the person, start --wait-due'",
           why.index(cases["owner"][0]) > why.index("本人を待っている子") and "--wait-due " + cases["owner"][0] in why)
        ok("hook-stop: open / other-machine children are not named",
           all(cases[k][0] not in why for k in ("open", "reuse", "far")))
        ok("hook-stop: the answered child (idle > 30 min) is raised as 'ask the person', not as 'fold'",
           cases["said"][0] in d.get("reason", "") and "本人に 1 行で聞く" in d.get("reason", "")
           and d["reason"].index(cases["said"][0]) > d["reason"].index("話している間"))
        ok("hook-stop: a child still wrapping is not named", rl not in d.get("reason", ""))
        ok("hook-stop: the judge child → 'answer it (rule 9)', not the --wait-due watch",
           cases["judge"][0] in why and why.index(cases["judge"][0]) > why.index("判断の問いを残している子")
           and "--wait-due " + cases["judge"][0] not in why)
        ok("hook-stop: the second Stop for the same children → silent", hook_stop(stop_in, [board], "R", "block") == "")
        os.remove(_state_file(bp_l))
        ok("hook-stop: observe mode → silent (and logged)", hook_stop(stop_in, [board], "R", "observe") == ""
           and os.path.exists(os.path.join(td, "state", "observe.jsonl")))
        ok("hook-stop: off → silent", hook_stop(stop_in, [board], "R", "off") == "")
        acc = {"tool_name": "Bash", "session_id": bp_c, "tool_input": {"command":
               f"python3 ~/Claude/ai-collaboration/board/board.py accept --root /x --request {R['due']} --reply-to y"}}
        ok("hook-accept: accepting own child's request → the rule-10 line with --wait", "--wait " + cases["due"][0] in hook_accept(acc, [board], "R"))
        acc["tool_input"]["command"] = f"python3 board.py accept --request {R['owner']}"
        RAW_ROOTS[:] = [board]
        line = hook_accept(acc, [board], "")
        ok("hook-accept: the child waits on the person → 'keep, tell the person' + the --wait-due watch with the board root",
           "残し" in line and "--wait-due " + cases["owner"][0] in line and f"--board-root '{board}'" in line)
        ok("wait-due: a child due now → returns at once", wait_due([cases["due"][0]], [board], 0.001, 0) == 0)
        ok("wait-due: a child left with only a question of judgment → returns at once (the parent's turn)",
           wait_due([cases["judge"][0]], [board], 0.001, 0) == 0)
        ok("wait-due: a child still waiting on the person → times out", wait_due([cases["owner"][0]], [board], 0.0001, 0) == 3)
        ok("wait-due: one child due, one waiting → ends at once (the rest re-watched)",
           wait_due([cases["owner"][0], cases["due"][0]], [board], 0.0001, 0) == 0)
        acc["tool_input"]["command"] = f"python3 board.py accept --request {R['open']}"
        ok("hook-accept: a request still open (accept failed) → silent", hook_accept(acc, [board], "") == "")
        acc["tool_input"]["command"] = f"python3 board.py note --request {R['due']}"
        ok("hook-accept: not an accept → silent", hook_accept(acc, [board], "") == "")
        acc["session_id"] = parent_c
        acc["tool_input"]["command"] = f"python3 board.py accept --request {R['due']}"
        ok("hook-accept: someone else's child → silent", hook_accept(acc, [board], "") == "")
        acc["session_id"] = bp_c
        ok("hook-accept: --extra text rides on the 'fold' line", "聞かない" in hook_accept(acc, [board], "", "畳む前に聞かない"))
        ANSWERED_GRACE_MIN = DEFAULT_ANSWERED_GRACE_MIN
        ok("grace 10 (the default): answered 10.5 minutes ago → due",
           {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T01:10:30")}[cases["said"][0]]["state"] == "due")
        # the cases below test the 'answered' state itself, so they keep a grace longer than the accept's distance
        ANSWERED_GRACE_MIN = 30
        st30 = {r["local"]: r for r in finished(bp_l, [board])}
        ok("grace 30: the person spoke, the child answered long ago → due", st30[cases["said"][0]]["state"] == "due")
        early = {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T01:10:30")}[cases["said"][0]]
        ok("grace 30: answered 10 minutes ago → still answered", early["state"] == "answered")
        ok("grace 30: the accept line for a recent answer → --wait-due, not 'ask'",
           "--wait-due" in _accept_line(early, "") and "本人に 1 行で聞く" not in _accept_line(early, ""))
        ok("grace 30: wait-due does not settle on a recent answer", not _settled(early))
        # the person worked in the child's window; the parent then sent more instructions and accepted (measured shape)
        Rw = "20260102T000000Z-claude-0000a1"
        wl, wc = kid("c100000b", [u("2026-01-02T00:00:00Z", "依頼", origin={"kind": "human"}), reply("2026-01-02T00:20:00Z"),
                                  stop("2026-01-02T00:20:01Z"), u("2026-01-02T00:55:00Z", "ここも同じ形に直して", origin={"kind": "human"}),
                                  reply("2026-01-02T00:57:00Z"), stop("2026-01-02T00:57:01Z"),
                                  peer_uds("2026-01-02T00:58:00Z", "差し戻し: 1 文足して再提出を", bp_l), reply("2026-01-02T01:05:00Z"),
                                  stop("2026-01-02T01:05:01Z")])
        event("claim", Rw, "2026-01-02T00:01:00", task="c100000b (opus)", sid="role-proj-work")
        event("accept", Rw, "2026-01-02T01:10:00", task="x", sid="x")
        w_at = {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T01:12:00")}[wl]
        ok("grace 30: the person spoke in the child's window, the parent's later messages do not end it → answered, not due",
           w_at["state"] == "answered" and not _settled(w_at))
        ok("grace 30: an hour after the child answered → due",
           {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T02:00:00")}[wl]["state"] == "due")
        ANSWERED_GRACE_MIN = DEFAULT_ANSWERED_GRACE_MIN
        ok("grace 10 (the default): the same child 15 minutes after it answered → due",
           {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T01:12:00")}[wl]["state"] == "due")
        ANSWERED_GRACE_MIN = 30
        # the parent asked the child to wrap and called it off soon after; the child stopped the run
        Rc = "20260102T000000Z-claude-0000a2"
        cl, cc = kid("c100000c", base + [peer("2026-01-02T01:20:05Z", "wrap skill を起動してください", bp_l),
                                         skill_wrap("2026-01-02T01:20:30Z"),
                                         peer("2026-01-02T01:21:30Z", "wrap の依頼は取り消します。 wrap を止めてください", bp_l),
                                         reply("2026-01-02T01:22:00Z"), stop("2026-01-02T01:22:05Z")])
        event("claim", Rc, "2026-01-02T00:01:00", task="c100000c (opus)", sid="role-proj-calledoff")
        event("accept", Rc, "2026-01-02T01:10:00", task="x", sid="x")
        transcript(bp_c, [{"type": "assistant", "timestamp": "2026-01-02T01:20:00Z", "message": {"content": [
            {"type": "tool_use", "id": "m", "name": "SendMessage", "input": {"to": cl, "message": "wrap skill を起動してください"}}]}},
            {"type": "assistant", "timestamp": "2026-01-02T01:21:00Z", "message": {"content": [
                {"type": "tool_use", "id": "m2", "name": "SendMessage",
                 "input": {"to": cl, "message": "wrap の依頼は取り消します。 wrap を止めてください"}}]}}])
        c_st = {r["local"]: r for r in finished(bp_l, [board], as_of="2026-01-02T01:30:00")}[cl]["state"]
        ok("a wrap the parent called off: its run and its stop do not count → due again, not wrapped", c_st == "due")
        ok("a wrap the parent called off: check_child does not count the run", any(
            x.startswith("wrap の記録が無い") for x in check_child(cl, as_of="2026-01-02T01:30:00")["reasons"]))
        ok("a wrap the parent called off: --wait has no request to count from", last_parent_wrap(cl) == "")
        os.remove(_state_file(bp_l))
        why30 = json.loads(hook_stop(stop_in, [board], "R", "block") or "{}").get("reason", "")
        ok("grace 30: the long-answered child is in the 'fold' part, no 'ask' part",
           cases["said"][0] in why30.split("本人を待っている子")[0] and "本人に 1 行で聞く" not in why30)
        ANSWERED_GRACE_MIN = None
        for v, want in (("none", None), ("", 10.0), ("30", 30.0), ("45", 45.0), ("x", 10.0)):
            os.environ["CHILD_WRAP_ANSWERED_GRACE_MIN"] = v
            ok(f"env grace {v!r} → {want}", _grace_from_env() == want)
        os.environ.pop("CHILD_WRAP_ANSWERED_GRACE_MIN", None)
        for k in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR", "CLAUDE_DESKTOP_SESSIONS_DIR", "CHILD_WRAP_REPOS_GLOB",
                  "CHILD_WRAP_INSTANCE", "CHILD_FINISHED_STATE_DIR"):
            os.environ.pop(k, None)
    ANSWERED_GRACE_MIN, BG_TASKS = saved_grace, saved_bg
    print("selftest:", "PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
