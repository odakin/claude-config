#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session-reply-knowledge-report.py — 締めで「返事にしか無い知見」 を拾うための一覧を会話記録から作り、 1 件ずつの処分を照合する。--selftest 内蔵。

用途: 締めの sweep (conventions/closing-sweep.md#collect-from-transcript) の「研究の中身」「考え方」 の行。
  この 2 行は「会話を頭から読む」 だけで道具が無く、 締めが道具のある行だけを回して、 返事にしか無い導出を記録しないまま
  「足したものは無い」 と報告した (実測)。 文脈圧縮の後は圧縮より前の返事が手元に無く、 要約で代わりにすると、 要約が
  自分で「未記録」 と書いた項目まで落ちる (同じ実測で、 締めは要約の未記録の項目の一部だけを拾った)。
  この道具は読む範囲を、 次の 3 種の候補に絞って並べる。 返事の中身が記録済みかは機械には決められない = 1 件ずつ読んで処分を書き、
  --check で処分の根拠 (file の行・commit) が実在するかを照合する。

並べるもの (session 本体の記録から、 時刻順):
  S  文脈圧縮の要約が「未決」 と書いた項目 — 見出しが 未記録 / 残る / 保留 / Pending などの下の項目と、
     行そのものが「直していない」「未確認」「not yet」 などを含む項目 (本人の発言の一覧の節は見ない)
  Q  本人の問い (？ / なぜ / って何 / だっけ / why など) と、 その turn の返事 — 説明・導出・判断の理由は問いへの答えに出やすい
  R  圧縮より前の turn の返事のうち、 問いでない依頼 (「進めて」 など) への返事 — 圧縮の後は手元に無い
  P  (--delegated のときだけ) 最後の圧縮の後の、 問いでない依頼への返事 — 締めを別の worker に渡したとき
     (closing-sweep.md#delegated-sweep)。 依頼元はこの返事を context に持つが、 worker は持たない = 既定では出さない。
     本文は turn の返事を全部つなぐ (Q・R は turn の中の一番長い返事)
     この返事を worker が並べられず、 会話記録を手で抜き出して読んだ (実測)
  ⏪ = 圧縮より前 (今の context に無い。 全文 = --show <id>)

処分の file (--check FILE) — 1 行 1 候補、 空白区切り、 # から行末は注記:
  <id> 記録済み|recorded <根拠>      既に記録にある。 根拠 = path:行 か <git repo の dir>@<commit>
  <id> 足した|added <根拠>          この締めで記録した。 根拠は同じ形
  <id> 記録しない|不要|skip <理由>   記録しない (知見を含まない・教科書の内容・本人が記録しないと決めた など)
  path は --base (既定 = 今の dir) から。 照合の出力は根拠の行 (commit なら題) を候補の文の隣に出す = 「直していない」 の項目に
  「その話は扱わない」 と書いた行を根拠に挙げたような食い違いが目に見える。 「記録済み」 の根拠の行そのものが未決の書き方
  (扱わない・未検算・保留 など) なら ⚠️ を付ける (読み直す印。 exit は変えない)。 候補が 1 件でも処分を欠く・根拠が実在しないと exit 1。

使い方:
  session-reply-knowledge-report.py <session id か先頭の数文字>     # 既定は環境変数 CLAUDE_CODE_SESSION_ID
  session-reply-knowledge-report.py abcd1234 --show Q3                # その候補の返事 (要約の項目) の全文
  session-reply-knowledge-report.py abcd1234 --check dispositions.txt [--base ~/work]
  session-reply-knowledge-report.py abcd1234 --delegated [--check …]  # 締めを渡された worker が回す (P も並べる・照合する)
  session-reply-knowledge-report.py abcd1234 --json
  session-reply-knowledge-report.py --hook-stop < <Stop hook の JSON>   # 締め (/wrap) の turn で照合が通っていなければ 1 回差し戻す
  session-reply-knowledge-report.py --selftest
一覧の 1 行は 200 字以内 (cut で切って読んでも id と問いが残る)。
--hook-stop は記録の末尾 4 MB だけを読み、 締めの印 (/wrap・wrap の skill) が無ければすぐ戻る (Stop のたびに呼ばれるため)。
差し戻しは 1 turn に 1 回 (自分の差し戻しが同じ turn にあれば見ない。 他の hook の差し戻しの後は判定する =
conventions/hook-authoring.md#stop-hook-active-other-hooks)。 hooks/ の入口の file は保護された file で、 置くには本人の裁定が要る。

OS: macOS / Linux / Windows (Git Bash・PowerShell) で同じに動く (標準 library、 Python 3.8+、 出力は UTF-8)。
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ssr", HERE / "session-scripts-report.py")
ssr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ssr)

QUESTION = re.compile(r"[？?]|なぜ|なんで|何で|どうして|って(何|なに|なん)|だっけ|とは\s*$|\bwhy\b|\bwhat\b|\bhow come\b", re.I)
OPEN_HEAD = re.compile(r"未記録|未決|未解決|未確認|未検証|未検算|未導出|残る|残り|やり残し|保留|pending|remaining|open (items|questions)|\btodo\b", re.I)
OPEN_LINE = re.compile(r"直していない|していない|書いていない|入れていない|未記録|未決|未解決|未確認|未検証|未検算|未導出|保留|が要る|要確認|"
                       r"not yet|unresolved|pending|still needs|left to do", re.I)
NONE_LINE = re.compile(r"(は|も)(無い|ない|なし|ありません)[。.]?\s*$|^(none|no (new|explicit|pending)\b)", re.I)
SKIP_SECTION = re.compile(r"user messages|本人の発言", re.I)
SECTION = re.compile(r"^(\d+\.\s+|#+\s+)\**(.+?)\**\s*:?\s*$")
BULLET = re.compile(r"^(\s*)(?:[-*•]|\d+\.)\s+(.*)$")
LABEL_ONLY = re.compile(r"^\*\*(.+?)\*\*\s*[:：]?\s*$")
NOT_TURN_HEADS = ("Base directory for this skill", "This session is being continued", "<system-reminder>", "<task-notification>",
                  "<local-command", "Another Claude session", "Stop hook feedback", "[Request interrupted")
LEADING_REMINDERS = re.compile(r"^(?:\s*<system-reminder>.*?</system-reminder>)+\s*", re.S)
PENDING_EVIDENCE = re.compile(r"対象外|扱わない|触れない|未検算|未導出|未検証|未記録|未確認|今後|保留|out of scope|not covered|\bTODO\b", re.I)
BLOCK_MARK = "返事にしか無い知見の照合が通っていません"
WRAP_MARK = re.compile(rb"<command-name>/wrap</command-name>|skills[/\\]+wrap\b|\"skill\": ?\"(?:[\w-]+:)?wrap\"")
STATUS = {"記録済み": "recorded", "recorded": "recorded", "足した": "added", "added": "added",
          "記録しない": "skip", "不要": "skip", "skip": "skip"}


def _text(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _one_line(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _turn_head(entry):
    """本人が始めた turn の入口なら、 その発言 (slash command は名前) を返す。 そうでなければ None。"""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return None
    text = _text(entry).strip()
    if not text:
        return None
    m = re.search(r"<command-name>([^<]+)</command-name>", text)
    if m:
        return m.group(1).strip()
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    if isinstance(origin, dict) and origin.get("kind") == "human":
        # app が本人の発言の頭に差し込む通知の段 (Linked sessions now など) を外す。 外さないと本人の問いが
        # 「<system-reminder> で始まる = 本人の turn でない」 に落ちる (実測)。 origin の無い発言 (別 session の依頼など) は従来どおり
        text = LEADING_REMINDERS.sub("", text).strip()
        if not text:
            return None
    if text.startswith(NOT_TURN_HEADS):
        return None
    return text


def summary_items(text):
    """要約の文から「未決」 の項目を [(見出し, 項目の文)] で返す。"""
    items, section_open, skip, label_stack = [], False, False, []
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith(("If you need specific details", "Continue the conversation", "The messages after this summary")):
            continue
        sec = SECTION.match(raw)
        if sec and not raw.startswith(" "):
            name = sec.group(2)
            skip = bool(SKIP_SECTION.search(name))
            section_open = bool(OPEN_HEAD.search(name))
            label_stack = [(-1, name, section_open)]
            continue
        if skip:
            continue
        b = BULLET.match(raw)
        if not b:
            continue
        indent, body = len(b.group(1)), b.group(2).strip()
        while label_stack and label_stack[-1][0] >= indent:
            label_stack.pop()
        under_open = any(o for _i, _n, o in label_stack)
        label = LABEL_ONLY.match(body)
        if label:
            label_stack.append((indent, label.group(1), bool(OPEN_HEAD.search(label.group(1)))))
            continue
        parent = label_stack[-1][1] if label_stack else ""
        if NONE_LINE.search(body.replace("**", "")):
            continue
        if under_open or OPEN_LINE.search(body):
            items.append((parent, body.replace("**", "")))
    return items


def scan(entries, delegated=False):
    """候補を時刻順の dict の list で返す (id, kind, ts, pre, head, text)。
    delegated = 最後の圧縮の後の、 問いでない依頼への返事も P として並べる (締めを渡された worker の context には無い)。"""
    bounds = [i for i, e in enumerate(entries) if e.get("type") == "system" and e.get("subtype") == "compact_boundary"]
    last_bound = bounds[-1] if bounds else -1
    cands, s_n, num = [], 0, {"Q": 0, "R": 0, "P": 0}
    for n, b in enumerate(bounds):
        ts = entries[b].get("timestamp", "")
        summ = next((e for e in entries[b + 1:b + 8] if e.get("isCompactSummary")), None)
        for parent, body in summary_items(_text(summ) if summ else ""):
            s_n += 1
            cands.append({"id": "S%d" % s_n, "kind": "S", "ts": ts, "pre": False,
                          "head": "圧縮 %d の要約" % (n + 1), "text": (parent + " › " if parent else "") + body})
    heads = [(i, h) for i, h in ((i, _turn_head(e)) for i, e in enumerate(entries)) if h is not None]
    carried = ""  # 返事の前に続けて打った本人の発言は、 次の発言と 1 つの問いにまとめる
    for k, (i, head) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(entries)
        texts = [_text(e).strip() for e in entries[i + 1:end] if e.get("type") == "assistant"]
        texts = [t for t in texts if t]
        if not texts and not head.startswith("/"):
            carried += head + " / "
            continue
        head, carried = carried + head, ""
        if not texts or head.startswith("/"):
            continue
        pre = i < last_bound
        is_q = bool(QUESTION.search(head))
        if not is_q and not pre and not delegated:
            continue
        kind = "Q" if is_q else ("R" if pre else "P")
        num[kind] += 1
        # P は渡された worker が返事を全部読む = turn の返事をつなぐ (Q・R は turn の中の一番長い返事)
        cands.append({"id": kind + str(num[kind]), "kind": kind, "ts": entries[i].get("timestamp", ""),
                      "pre": pre, "head": head, "text": "\n\n".join(texts) if kind == "P" else max(texts, key=len)})
    return cands, len(bounds)


def load(path):
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def tail_entries(path, max_bytes=4_000_000):
    """記録の末尾 max_bytes だけを読む (Stop のたびに全体を読まない)。 締めの印が無ければ [] を返す。"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        raw = f.read()
    if not WRAP_MARK.search(raw):  # 「wrap」 だけでは絞れない (desktop は毎 turn wrap_up を呼ぶ)
        return []
    lines = raw.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]  # 途中から読んだ最初の行は切れている
    out = []
    for line in lines:
        try:
            o = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def _is_wrap_turn(span):
    if _turn_head(span[0]) == "/wrap":
        return True
    for e in span:
        t = _text(e) if e.get("type") == "user" else ""
        if t.startswith("Base directory for this skill:") and t.splitlines()[0].rstrip("/ ").endswith(("/skills/wrap", "\\skills\\wrap")):
            return True
        for b in (e.get("message") or {}).get("content") or [] if e.get("type") == "assistant" else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill" \
                    and str((b.get("input") or {}).get("skill", "")).split(":")[-1] == "wrap":
                return True
    return False


def stop_check(entries):
    """締めの turn で処分の照合が通っていなければ、 差し戻しの理由を返す (それ以外は None)。"""
    heads = [i for i, e in enumerate(entries) if _turn_head(e) is not None]
    if not heads:
        return None
    span = entries[heads[-1]:]
    if not _is_wrap_turn(span):
        return None
    if any(e.get("type") == "user" and BLOCK_MARK in _text(e) for e in span):
        return None  # 自分の差し戻しは 1 turn に 1 回 (stop_hook_active だけでは見ない = 他の hook の差し戻しの後も判定する)
    runs = {}
    for e in span:
        for b in (e.get("message") or {}).get("content") or [] if isinstance((e.get("message") or {}).get("content"), list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = str((b.get("input") or {}).get("command", ""))
                if "session-reply-knowledge-report" in cmd and "--check" in cmd:
                    runs[b.get("id")] = True
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in runs:
                c = b.get("content")
                out = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                if "欠け・根拠の無いもの 0 件" in out:
                    return None
    return ("締め (/wrap) の turn で、 " + BLOCK_MARK + "。 "
            "`python3 %s <session id の先頭 8 字>` で候補 (文脈圧縮の要約が「未決」 と書いた項目・本人の問いとその返事・"
            "圧縮より前の返事) を出し、 1 件ずつ読んで記録し、 処分 (記録済み / 足した / 不要) を file に書いて `--check <file>` を通す。\n"
            "報告に「足したものは無い」「すべて記録済み」 と書いていたら、 照合の後の件数で言い直す (全文は出し直さず、 書き足す)。\n"
            "正本 = claude-config/conventions/closing-sweep.md#reply-knowledge" % (HERE / "session-reply-knowledge-report.py"))


def hook_stop_main():
    """Stop hook の入口 (hooks/ の薄い file から呼ぶ)。 1 turn に 1 回だけ差し戻す。 fail-open。"""
    try:
        data = json.load(sys.stdin)
        path = data.get("transcript_path") or ""
        if not path or not os.path.isfile(path):
            return 0
        reason = stop_check(tail_entries(path))
    except Exception:
        return 0
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def read_dispositions(path):
    disp = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 2)
        disp[parts[0]] = (STATUS.get(parts[1]) if len(parts) > 1 else None, parts[2].strip() if len(parts) > 2 else "")
    return disp


def resolve_evidence(ev, base):
    """根拠を確かめて (ok, 見せる文) を返す。"""
    m = re.match(r"^(.+)@([0-9a-fA-F]{7,40})$", ev)
    if m:
        repo = (base / os.path.expanduser(m.group(1))).resolve()
        r = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s", m.group(2)], capture_output=True, text=True)
        if r.returncode != 0:
            return False, "commit が無い: %s" % ev
        return True, "commit: " + _one_line(r.stdout, 150)
    m = re.match(r"^(.+):(\d+)$", ev)
    if m:
        f = (base / os.path.expanduser(m.group(1))).resolve()
        if not f.is_file():
            return False, "file が無い: %s" % m.group(1)
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        n = int(m.group(2))
        if not 1 <= n <= len(lines):
            return False, "行が範囲外: %s (%d 行)" % (ev, len(lines))
        return True, "行: " + _one_line(lines[n - 1], 150)
    return False, "根拠の形が違う (path:行 か <repo>@<commit>): %s" % ev


def check(cands, disp, base):
    """rows = [(候補, 処分, 通ったか, 見せる文, 読み直す印)]。 印 = 「記録済み」 の根拠の行そのものが未決の書き方。"""
    rows, bad = [], 0
    for c in cands:
        status, ev = disp.get(c["id"], (None, ""))
        if status is None:
            ok, shown = False, "処分が無い"
        elif status == "skip":
            ok, shown = len(ev) >= 4, ("理由: " + ev) if len(ev) >= 4 else "記録しない理由が無い"
        else:
            ok, shown = resolve_evidence(ev, base) if ev else (False, "根拠が無い")
        warn = bool(ok and status == "recorded" and shown.startswith("行: ") and PENDING_EVIDENCE.search(shown))
        bad += not ok
        rows.append((c, status, ok, shown, warn))
    unknown = sorted(set(disp) - {c["id"] for c in cands})
    return rows, bad, unknown


def report(session, pdirs, args):
    paths = []
    for p in ssr.find_main_transcripts(pdirs, session):
        if os.path.realpath(p) not in [os.path.realpath(x) for x in paths]:
            paths.append(p)
    if not paths:
        print("記録が見つからない: session=%s (見た dir: %s)" % (session, ", ".join(map(str, pdirs))))
        return 2
    cands, n_comp = [], 0
    for p in paths:
        c, n = scan(load(p), delegated=args.delegated)
        cands += c
        n_comp += n
    if args.show:
        hit = [c for c in cands if c["id"] == args.show]
        if not hit:
            print("候補が無い: %s" % args.show)
            return 2
        c = hit[0]
        print("%s %s %s\n問い・見出し: %s\n\n%s" % (c["id"], "⏪" if c["pre"] else "", c["ts"][:19], c["head"], c["text"]))
        return 0
    if args.json:
        print(json.dumps({"compactions": n_comp, "candidates": cands}, ensure_ascii=False, indent=1))
        return 0
    print("記録: " + ", ".join(map(str, paths)))
    print("文脈圧縮: %d 回。 ⏪ = 圧縮より前 (今の context に無い、 全文 = --show <id>)" % n_comp)
    if args.check:
        rows, bad, unknown = check(cands, read_dispositions(args.check), Path(args.base).expanduser())
        n_warn = sum(1 for r in rows if r[4])
        print("処分の照合: 候補 %d 件、 欠け・根拠の無いもの %d 件、 根拠の行が未決の書き方 %d 件 (⚠️ = 読み直す)" % (len(cands), bad, n_warn))
        for c, status, ok, shown, warn in rows:
            mark = "❌" if not ok else ("⚠️" if warn else "✅")
            print("%s %-4s %s %s\n      %s" % (mark, c["id"], status or "-", _one_line(c["text"] if c["kind"] == "S" else c["head"], 90),
                                         _one_line(shown, 180) + (" ← 根拠の行も未決の書き方 = 記録したことになるか読み直す" if warn else "")))
        for u in unknown:
            print("⚠️ 処分の file にある id が候補に無い: %s" % u)
        return 1 if bad else 0
    kinds = [("S", "圧縮の要約が「未決」 と書いた項目 (締めの入力。 要約の文で済ませず、 1 件ずつ今の記録と照らす)"),
             ("Q", "本人の問いと、 その turn の返事"),
             ("R", "圧縮より前の、 問いでない依頼への返事")]
    if args.delegated:
        kinds.append(("P", "最後の圧縮の後の、 問いでない依頼への返事 (--delegated = 締めを渡された worker の context に無い)"))
    for kind, title in kinds:
        cs = [c for c in cands if c["kind"] == kind]
        print("%s. %s: %d 件" % (kind, title, len(cs)))
        for c in cs:
            if kind == "S":
                print("  %-4s %s  %s" % (c["id"], c["ts"][:16], _one_line(c["text"], 170)))
            else:
                print("  %-4s %s %s  %s\n        返事: %s" % (c["id"], "⏪" if c["pre"] else "  ", c["ts"][:16], _one_line(c["head"], 120),
                                                          _one_line(c["text"], 150)))
    print("→ 1 件ずつ処分を file に書き (記録済み / 足した / 記録しない)、 --check <file> で照合する。 「足したものは無い」 と報告するのは照合が通った後")
    return 1 if (args.strict and cands) else 0


def selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("FAIL", name, got, want)

    summ = "\n".join([
        "Summary:", "1. **Primary Request and Intent**", "   - 決定は本人の指示で保留。",
        "5. **Problem Solving**", "   - 例の図は直した。", "   - **残る未記録**",
        "     - 出所は未確認で、 TODO に書いてある。", "     - ノート §4 の補題は直していない。", "     - 結びの文は直した。",
        "6. **All user messages**", "   - まだ直していないの？",
        "7. **Pending Tasks**", "   - 新しい明示の依頼は無い。", "   - 本人に出所を確かめる。",
        "If you need specific details from before compaction, read the transcript."])
    got = [b for _p, b in summary_items(summ)]
    expect("要約: 保留の行", "決定は本人の指示で保留。" in got, True)
    expect("要約: 見出しの下は全部", [g for g in got if g.startswith(("出所", "ノート", "結び"))],
           ["出所は未確認で、 TODO に書いてある。", "ノート §4 の補題は直していない。", "結びの文は直した。"])
    expect("要約: 本人の発言の節は見ない", any("まだ直していないの" in g for g in got), False)
    expect("要約: 「無い」 の行は外す", any("依頼は無い" in g for g in got), False)
    expect("要約: Pending の下", "本人に出所を確かめる。" in got, True)
    expect("要約: 済んだ行は拾わない", "例の図は直した。" in got, False)
    expect("英語の要約", [b for _p, b in summary_items("7. Pending Tasks:\n   - Verify the sign.\n8. Current Work:\n   - Done the plot.")],
           ["Verify the sign."])

    def human(text, ts="t"):
        return {"type": "user", "origin": {"kind": "human"}, "timestamp": ts, "message": {"content": text}}

    def said(text):
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

    tool = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}
    peer = {"type": "user", "isMeta": True, "message": {"content": "Another Claude session sent a message:"}}
    boundary = {"type": "system", "subtype": "compact_boundary", "timestamp": "b"}
    summary = {"type": "user", "isCompactSummary": True, "message": {"content": summ}}
    entries = [human("進めて", "1"), said("計算した。 符号は正。"),
               human("もっと簡潔にできぬか？", "1b"), human("簡潔、平明に", "1c"), said("削った"),
               human("その符号は自明では？", "2"), said("短い"), tool, said("自明な理由: 両辺が同じ対称性の下で同じように変わる。"),
               boundary, summary,
               human("<command-message>wrap</command-message>\n<command-name>/wrap</command-name>", "3"), said("締めた"),
               human("次も進めて", "4"), said("進めた"),
               peer, said("受け取った"),
               human("これなんで but なの？", "5"), said("逆接でないから。")]
    cands, n = scan(entries)
    expect("圧縮の回数", n, 1)
    expect("候補の種類", [(c["id"][0], c["pre"]) for c in cands if c["kind"] != "S"], [("R", True), ("Q", True), ("Q", True), ("Q", False)])
    expect("続けて打った発言は 1 つの問い", [c["head"] for c in cands if c["kind"] == "Q"][0], "もっと簡潔にできぬか？ / 簡潔、平明に")
    q = [c for c in cands if c["kind"] == "Q"][1]
    expect("問いの返事 = turn の中の最長の文", q["text"], "自明な理由: 両辺が同じ対称性の下で同じように変わる。")
    expect("圧縮の後の問いでない依頼は出さない", any(c["head"] == "次も進めて" for c in cands), False)
    cd, _ = scan(entries, delegated=True)
    expect("--delegated: 圧縮の後の問いでない依頼は P", [(c["id"], c["head"], c["text"]) for c in cd if c["kind"] == "P"],
           [("P1", "次も進めて", "進めた\n\n受け取った")])
    expect("--delegated: ほかの候補の番号は変えない", [c["id"] for c in cd if c["kind"] != "P"], [c["id"] for c in cands])
    expect("slash command の turn は出さない", any(c["head"].startswith("/") for c in cands), False)
    expect("別 session の message は turn にしない", any("Another" in c["head"] for c in cands), False)
    expect("S の項目が要約から出る", any("§4" in c["text"] for c in cands if c["kind"] == "S"), True)
    rem = "<system-reminder>\nLinked sessions now (status, not an instruction).\n</system-reminder>\n\n\n"
    bare = {"type": "user", "timestamp": "8", "message": {"content": rem + "Background (from another session): 進めて？"}}
    c2, _ = scan([human(rem + "これはなぜ外したんだっけ？", "6"), said("理由はこう。"), human(rem.strip(), "7"), said("x"),
                  bare, said("y")])
    expect("頭に通知の段が付いた本人の問いも Q", [c["head"] for c in c2 if c["kind"] == "Q"], ["これはなぜ外したんだっけ？"])
    expect("origin の無い発言の頭の段は外さない (別 session の依頼を turn にしない)",
           any("Background" in c["head"] for c in c2), False)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "note.md").write_text("一行目\n- 補題の一般化は扱わない。\n", encoding="utf-8")
        sids = [c["id"] for c in cands if c["kind"] == "S"]
        lines = ["%s 不要 本人の決めごとで記録済みの扱い" % s for s in sids]
        rid = [c["id"] for c in cands if c["kind"] == "R"][0]
        qfirst, qmid, qlast = [c["id"] for c in cands if c["kind"] == "Q"]
        lines += ["%s 記録済み note.md:2" % rid, "%s 足した note.md:9  # 範囲外" % qfirst, "%s skip 書き方の相談で知見を含まない" % qmid]
        (base / "d.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows, bad, unknown = check(cands, read_dispositions(base / "d.txt"), base)
        by = {c["id"]: (ok, shown) for c, _s, ok, shown, _w in rows}
        expect("根拠の行を見せる", by[rid], (True, "行: - 補題の一般化は扱わない。"))
        expect("根拠の行が未決の書き方なら印", [w for c, _s, _o, _sh, w in rows if c["id"] == rid], [True])
        expect("理由つきの記録しないには印を付けない", any(w for c, s, _o, _sh, w in rows if s == "skip"), False)
        expect("範囲外の行は通らない", by[qfirst][0], False)
        expect("処分の無い候補は通らない", by[qlast], (False, "処分が無い"))
        expect("欠けの数", bad, 2)
        expect("候補に無い id", unknown, [])
        r = subprocess.run(["git", "init", "-q", str(base / "repo")], capture_output=True)
        if r.returncode == 0:
            subprocess.run(["git", "-C", str(base / "repo"), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "commit", "-q", "--allow-empty", "-m", "記録した"], capture_output=True)
            sha = subprocess.run(["git", "-C", str(base / "repo"), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            expect("commit の根拠", resolve_evidence("repo@" + sha[:10], base), (True, "commit: 記録した"))
            expect("無い commit", resolve_evidence("repo@deadbeef", base)[0], False)

    def bash(cmd, tid):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}

    def result(tid, text):
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}

    wrap = human("<command-message>wrap</command-message>\n<command-name>/wrap</command-name>")
    skill = {"type": "user", "isMeta": True, "message": {"content": "Base directory for this skill: /h/.claude/skills/wrap\n\n# wrap"}}
    stop_fb = {"type": "user", "isMeta": True, "message": {"content": "Stop hook feedback: 書き足す"}}
    cmd = "python3 scripts/session-reply-knowledge-report.py abcd1234 --check d.txt"
    expect("締めでない turn は見ない", stop_check([human("進めて"), said("進めた")]), None)
    expect("照合の無い締めは差し戻す", stop_check([human("前"), said("x"), wrap, skill, said("締めた")]) is not None, True)
    expect("照合が通った締めは通す", stop_check([wrap, skill, bash(cmd, "t1"), result("t1", "処分の照合: 候補 3 件、 欠け・根拠の無いもの 0 件"),
                                         said("締めた")]), None)
    expect("照合が落ちたままは差し戻す", stop_check([wrap, bash(cmd, "t1"), result("t1", "欠け・根拠の無いもの 2 件"), said("締めた")]) is not None, True)
    expect("一覧だけで --check が無い", stop_check([wrap, bash(cmd.replace(" --check d.txt", ""), "t1"),
                                             result("t1", "欠け・根拠の無いもの 0 件"), said("締めた")]) is not None, True)
    expect("他の hook の差し戻しの後も判定する", stop_check([wrap, said("締めた"), stop_fb, said("書き足した")]) is not None, True)
    own_fb = {"type": "user", "isMeta": True, "message": {"content": "Stop hook feedback: 締め (/wrap) の turn で、 " + BLOCK_MARK}}
    expect("自分の差し戻しは 1 回だけ", stop_check([wrap, said("締めた"), own_fb, said("書き足した")]), None)
    expect("Skill tool で起こした締め", stop_check([human("仕上げて"), {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}, said("締めた")]) is not None, True)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [human("x" * 300), said("y")] * 20 + [wrap, said("締めた")]) + "\n",
                     encoding="utf-8")
        tail = tail_entries(p, max_bytes=2000)
        expect("末尾だけ読む", 0 < len(tail) < 42, True)
        expect("末尾から締めを判定", stop_check(tail) is not None, True)
        p.write_text(json.dumps(human("進めて")) + "\n", encoding="utf-8")
        expect("締めの印が無ければ読まない", tail_entries(p), [])
        box = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "w", "name": "mcp__ccd_turn__wrap_up", "input": {}}]}}
        p.write_text(json.dumps(human("進めて")) + "\n" + json.dumps(box) + "\n", encoding="utf-8")
        expect("turn 終わりの箱 (wrap_up) は締めの印にしない", tail_entries(p), [])
        sk = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "wrap"}}]}}
        p.write_text(json.dumps(human("仕上げて")) + "\n" + json.dumps(sk) + "\n", encoding="utf-8")
        expect("Skill の起動は締めの印", len(tail_entries(p)), 2)

    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ssr._utf8_stdout()
    ap = argparse.ArgumentParser(description="締めで返事にしか無い知見を拾う一覧 (圧縮の要約の未決の項目・本人の問いへの答え・圧縮前の返事) と処分の照合")
    ap.add_argument("session", nargs="?", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    ap.add_argument("--projects-dir")
    ap.add_argument("--show", metavar="ID", help="その候補の全文")
    ap.add_argument("--check", metavar="FILE", help="処分の file を照合する")
    ap.add_argument("--base", default=".", help="処分の根拠の path の基準 (既定 = 今の dir)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--delegated", action="store_true",
                    help="最後の圧縮の後の、 問いでない依頼への返事も P として並べる (締めを渡された worker が回す)")
    ap.add_argument("--strict", action="store_true", help="候補が 1 件でもあれば exit 1")
    ap.add_argument("--hook-stop", action="store_true", help="Stop hook として stdin の JSON を読む (締めの turn で照合が通っていなければ 1 回差し戻す)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.hook_stop:
        return hook_stop_main()
    if not a.session:
        ap.error("session id を渡す (または CLAUDE_CODE_SESSION_ID)")
    return report(a.session, ssr.projects_dirs(a.projects_dir), a)


if __name__ == "__main__":
    sys.exit(main())
