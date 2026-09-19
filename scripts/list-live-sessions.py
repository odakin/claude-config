#!/usr/bin/env python3
"""list-live-sessions.py — 同 cwd で生きてる兄弟 Claude session を surface する read-only reader。

規約: conventions/multi-session-coordination.md (並列 session と同じ repo を触るときの race-awareness)

= なぜ存在するか:
  harness は全 live session を `~/.claude/sessions/<pid>.json` に刻印している
  ({pid, sessionId(=transcript UUID), cwd, startedAt, entrypoint})。 これは
  multi-session-coordination.md §1「同 file path を別 session が独立に上書きする race」 の
  awareness 素材として既に在るのに、 session には surface されていない。 本 script は
  その disk 刻印を読み、 *同じ cwd で今 生きてる兄弟 session* を一覧化する (= discovery 半分の robust 実体)。

  ⚠️ これは「兄弟が存在する・素性」 までで、 send_message できる addressable id (`local_<uuid>`) は
  持てない (= harness ブロック、 plan §1 F4)。 messaging でなく race-awareness の道具。

設計上の安全: 全 path で fail-open (= dashboard 連鎖 / hook を止めない)。 読むだけ・何も書かない。

使い方:
  python3 list-live-sessions.py                 # 全 live session を cwd 別に
  python3 list-live-sessions.py --cwd /path      # 指定 cwd の兄弟のみ (既定 = 自 cwd 推定なし → 全件)
  python3 list-live-sessions.py --self <uuid>    # transcript UUID で自分を除外/マーク
  python3 list-live-sessions.py --surface        # dashboard/hook 向け: 該当ありなら短文、 無ければ沈黙
  python3 list-live-sessions.py --selftest
"""
# ── 運用メモ (2026-09-19 に scripts/README.md の節から verbatim で移設。 README は生成索引) ──
# ## list-live-sessions.py
#
# **同 cwd で生きている兄弟 Claude session** を surface する read-only reader
# (= 並列上書き race の事前察知。 SessionStart hook から注入される)。
# 設計 = `../plans/2026-06-27-cross-session-findability-investigation.md` §4.1。
#
# ── 運用メモここまで ──
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time

# test 用 env override (= 既定は実 ~/.claude。 hook test / fixture で差し替えるため)
SESSIONS_DIR = os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.expanduser("~/.claude/sessions")
PROJECTS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 別 uid だが存在はする (この環境では通常起きない)
    except Exception:
        return True  # 判定不能は「生きてる扱い」 で false-negative を避ける
    return True


def _encode_cwd(cwd: str) -> str:
    # ~/.claude/projects/ の dir 名は cwd の '/' を '-' に置換した形
    return cwd.replace("/", "-")


def _intent_snippet(session_id: str, cwd: str, max_len: int = 70) -> str:
    """対応 jsonl から直近の人間 user 発話を best-effort 抽出 (= その session が今 何の話か)。"""
    path = os.path.join(PROJECTS_DIR, _encode_cwd(cwd), f"{session_id}.jsonl")
    if not os.path.isfile(path):
        return ""
    last = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or '"type":"user"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "user":
                    continue
                content = (obj.get("message") or {}).get("content")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text += part.get("text", "")
                        elif isinstance(part, str):
                            text += part
                if not text:
                    continue
                # 注入 (system-reminder / tool_result) 混じりや巨大初回ターンを除外
                if "<system-reminder>" in text or "tool_use_id" in text:
                    # 注入を剥がして残る人間文があれば拾う
                    tail = text.split("</system-reminder>")[-1].strip()
                    text = tail if tail else ""
                text = " ".join(text.split())
                if 0 < len(text) <= 4000:
                    last = text  # より新しい発話で上書き → 直近 = 現在の話題
    except Exception:
        return ""
    if len(last) > max_len:
        last = last[: max_len - 1] + "…"
    return last


def collect(self_uuid: str | None = None, cwd_filter: str | None = None) -> list[dict]:
    out = []
    try:
        files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
    except Exception:
        return out
    now_ms = int(time.time() * 1000)
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        pid = d.get("pid")
        sid = d.get("sessionId", "")
        cwd = d.get("cwd", "")
        if not isinstance(pid, int) or not sid:
            continue
        if cwd_filter and cwd != cwd_filter:
            continue
        if not _pid_alive(pid):
            continue  # stale file (= 死んだ process の置き土産)
        started = d.get("startedAt")
        age_min = None
        if isinstance(started, (int, float)):
            age_min = max(0, (now_ms - started) // 60000)
        out.append({
            "pid": pid,
            "sessionId": sid,
            "cwd": cwd,
            "started_at": started,
            "age_min": age_min,
            "entrypoint": d.get("entrypoint", ""),
            "is_self": bool(self_uuid) and sid == self_uuid,
            "intent": _intent_snippet(sid, cwd),
        })
    out.sort(key=lambda r: (r["cwd"], -(r["started_at"] or 0)))
    return out


def _fmt_age(m):
    if m is None:
        return "?"
    if m < 60:
        return f"{m}分"
    return f"{m // 60}時間{m % 60}分"


def render(rows: list[dict], self_uuid: str | None) -> str:
    if not rows:
        return "(生きてる兄弟 session は見つからず)"
    lines = []
    by_cwd: dict[str, list[dict]] = {}
    for r in rows:
        by_cwd.setdefault(r["cwd"], []).append(r)
    for cwd, group in by_cwd.items():
        lines.append(f"📂 {cwd} — {len(group)} session")
        for r in group:
            tag = " 👈自分" if r["is_self"] else ""
            sid = r["sessionId"][:8]
            intent = f"  「{r['intent']}」" if r["intent"] else ""
            lines.append(f"   • pid {r['pid']} / {sid} / {_fmt_age(r['age_min'])}前起動{tag}{intent}")
    return "\n".join(lines)


def surface(self_uuid: str | None, cwd_filter: str | None) -> str:
    """hook/dashboard 向け: 自分以外の兄弟が同 cwd に在る時だけ短文、 無ければ空 (= 沈黙)。"""
    rows = collect(self_uuid=self_uuid, cwd_filter=cwd_filter)
    siblings = [r for r in rows if not r["is_self"]]
    # cwd_filter 無指定なら「自分の cwd」 を self 行から推定して同 cwd のみに絞る
    if not cwd_filter and self_uuid:
        self_rows = [r for r in rows if r["is_self"]]
        if self_rows:
            mycwd = self_rows[0]["cwd"]
            siblings = [r for r in siblings if r["cwd"] == mycwd]
    if not siblings:
        return ""
    head = f"🔀 同じ作業ディレクトリで {len(siblings)} 個の別 session が生きています (並列上書き race 注意 → 編集前に git fetch + 突き合わせ):"
    body = []
    for r in siblings:
        intent = f" — 「{r['intent']}」" if r["intent"] else ""
        body.append(f"   • {r['sessionId'][:8]} ({_fmt_age(r['age_min'])}前起動){intent}")
    return head + "\n" + "\n".join(body)


def _selftest() -> int:
    ok = True
    # _encode_cwd
    if _encode_cwd("/w/proj") != "-w-proj":
        print("FAIL encode_cwd"); ok = False
    # _pid_alive: 自 pid は生きてる / pid 1 も生きてる / 巨大 pid は死んでる想定
    if not _pid_alive(os.getpid()):
        print("FAIL pid_alive self"); ok = False
    if _pid_alive(2 ** 30):
        print("FAIL pid_alive huge"); ok = False
    # collect は例外を投げない
    try:
        collect()
    except Exception as e:
        print(f"FAIL collect raised {e}"); ok = False
    # surface は該当無し時 空文字 (fail-open)
    try:
        s = surface(self_uuid="__nonexistent__", cwd_filter="/__no_such_cwd__")
        if s != "":
            print("FAIL surface non-empty on no-match"); ok = False
    except Exception as e:
        print(f"FAIL surface raised {e}"); ok = False
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # harness は session UUID を CLAUDE_CODE_SESSION_ID で export する (= 2026-06-27
    # 実測。 旧 CLAUDE_SESSION_ID は誤名で空だった)。 hook は --self を明示で渡すので
    # この default は CLI 手叩き時の便宜。
    ap.add_argument("--self", dest="self_uuid",
                    default=os.environ.get("CLAUDE_CODE_SESSION_ID")
                    or os.environ.get("CLAUDE_SESSION_ID"))
    ap.add_argument("--cwd", dest="cwd_filter", default=None)
    ap.add_argument("--surface", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    try:
        if args.selftest:
            return _selftest()
        if args.surface:
            out = surface(args.self_uuid, args.cwd_filter)
            if out:
                print(out)
            return 0
        rows = collect(self_uuid=args.self_uuid, cwd_filter=args.cwd_filter)
        print(render(rows, args.self_uuid))
        return 0
    except Exception as e:
        # fail-open: 何があっても dashboard/hook を止めない
        sys.stderr.write(f"list-live-sessions: {e}\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
