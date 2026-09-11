#!/usr/bin/env python3
"""check-first-reply-stamp.py — 最初の返信に自己同定 stamp (I7) が出たかを transcript から数える事後 audit

hook (scripts/first_reply_stamp.py) の外側に置く物差し: hook が止まっても (kill switch・install 漏れ・
trust 未承認) transcript は残るので、 ここは劣化を検出できる。 数えるもの:
  S1 = 最初の turn の最初の返信の 1 行目に stamp
  S2 = 最初の turn のどれかの返信の 1 行目に stamp (= Stop 段が保証しようとする床)
  注入 stamp の「account 未同定」 (Claude: SessionStart hook の record。 whoami の race の監視)
  Stop 段の記録 (stop-log.jsonl = observe なら「block なら差し戻していた」 件数)
範囲は hook と同じ (workspace base 配下の cwd、 Claude headless と Codex sub-agent を除く)。

設計と実測 = conventions/multi-account-machine-surface.md#first-reply-stamp-mechanism。

usage:
  check-first-reply-stamp.py [--days 14] [--since YYYY-MM-DD] [--threshold 0.10] [--min-sessions 5] [--no-codex]
  check-first-reply-stamp.py --findings-only     # dashboard 用 (所見が無ければ無出力)
  check-first-reply-stamp.py --json
  check-first-reply-stamp.py --selftest
env (test 用): FIRST_REPLY_STAMP_CLAUDE_GLOB / FIRST_REPLY_STAMP_CODEX_ROOT / FIRST_REPLY_STAMP_BASE /
  FIRST_REPLY_STAMP_STATE_DIR
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import first_reply_stamp as frs  # noqa: E402

# whoami --wait を hook に入れた日。 これ以降の注入で「未同定」 が出たら race 対策が効いていない
WAIT_FIX_DATE = "2026-09-12"


def claude_glob() -> str:
    return os.environ.get("FIRST_REPLY_STAMP_CLAUDE_GLOB") or str(Path.home() / ".claude*" / "projects" / "*" / "*.jsonl")


def codex_root() -> Path:
    value = os.environ.get("FIRST_REPLY_STAMP_CODEX_ROOT")
    return Path(value) if value else Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def _head(path: Path, limit: int = 400):
    for i, entry in enumerate(frs._iter_jsonl(path)):
        if i >= limit:
            break
        yield entry


def claude_session(path: Path) -> dict | None:
    cwd = entry_point = started = None
    injected = ""
    for entry in _head(path):
        cwd = cwd or entry.get("cwd")
        entry_point = entry_point or entry.get("entrypoint")
        attachment = entry.get("attachment") if entry.get("type") == "attachment" else None
        if isinstance(attachment, dict) and "session-start-host-stamp" in str(attachment.get("command") or ""):
            injected = next((ln for ln in str(attachment.get("content") or "").splitlines()
                             if ln.startswith(frs.STAMP_MARK)), injected)
        if started is None and frs._claude_user_text(entry) is not None:
            started = str(entry.get("timestamp") or "")[:10]
    if started is None or not cwd or (entry_point or "").startswith("sdk-") or not frs.in_scope(cwd):
        return None
    prompts, texts = frs.claude_first_turn(path)
    if prompts < 1 or not texts:
        return None
    return {"flavor": "claude", "session": path.stem[:8], "date": started, "cwd": cwd,
            "s1": frs.has_top_stamp(texts[0]), "s2": any(frs.has_top_stamp(t) for t in texts),
            "injected": bool(injected), "unresolved": "未同定" in injected,
            "head": frs.top_line(texts[0])[:50]}


def codex_session(path: Path) -> dict | None:
    cwd = started = None
    for entry in _head(path):
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        if entry.get("type") == "session_meta" and payload.get("parent_thread_id"):
            return None
        cwd = cwd or payload.get("cwd")
        if started is None and entry.get("type") == "event_msg" and payload.get("type") == "user_message":
            started = str(entry.get("timestamp") or "")[:10]
    if started is None or not cwd or not frs.in_scope(cwd):
        return None
    prompts, texts = frs.codex_first_turn(path)
    if prompts < 1 or not texts:
        return None
    return {"flavor": "codex", "session": path.stem[-36:][:8], "date": started, "cwd": cwd,
            "s1": frs.has_top_stamp(texts[0]), "s2": any(frs.has_top_stamp(t) for t in texts),
            "injected": False, "unresolved": False, "head": frs.top_line(texts[0])[:50]}


def collect(days: int, with_codex: bool, since_date: str = "") -> list[dict]:
    cutoff = time.time() - days * 86400
    rows = []
    for name in glob.glob(claude_glob()):
        path = Path(name)
        try:
            if path.stat().st_mtime < cutoff:
                continue
            row = claude_session(path)
        except OSError:
            continue
        if row:
            rows.append(row)
    if with_codex and codex_root().is_dir():
        for path in codex_root().glob("**/rollout-*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
                row = codex_session(path)
            except OSError:
                continue
            if row:
                rows.append(row)
    since = max((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"), since_date or "")
    return sorted((r for r in rows if r["date"] >= since), key=lambda r: r["date"])


def stop_log(days: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out, seen = [], set()
    for flavor in ("claude", "codex"):
        path = frs.stop_log_path(flavor)
        if path in seen or not path.is_file():  # state dir を共有する設定では同じ file を 2 度読まない
            continue
        seen.add(path)
        for entry in frs._iter_jsonl(path):
            if str(entry.get("ts", "")) >= since:
                out.append(entry)
    return out


def summarize(rows: list[dict], logs: list[dict], threshold: float, min_sessions: int,
              fix_date: str = WAIT_FIX_DATE) -> dict:
    by = {}
    for flavor in ("claude", "codex"):
        sub = [r for r in rows if r["flavor"] == flavor]
        if not sub:
            continue
        misses = [r for r in sub if not r["s2"]]
        by[flavor] = {"n": len(sub), "s1": sum(r["s1"] for r in sub), "s2": len(sub) - len(misses),
                      "misses": misses[-8:], "miss_rate": len(misses) / len(sub)}
    unresolved = [r for r in rows if r["unresolved"] and r["date"] >= fix_date]
    findings = []
    for flavor, s in by.items():
        if s["n"] >= min_sessions and s["miss_rate"] > threshold:
            findings.append(f"🟡 {flavor}: 最初の turn で stamp が一度も出なかった session が "
                            f"{s['n'] - s['s2']}/{s['n']} (閾値 {threshold:.0%})")
    if unresolved:
        findings.append(f"🟡 claude: 注入 stamp が「account 未同定」 の session が {len(unresolved)} 件 "
                        f"({fix_date} 以降) = whoami --wait が効いていない")
    info = []
    if logs:
        modes = sorted({str(e.get('mode')) for e in logs})
        info.append(f"ℹ️ Stop 段の記録 {len(logs)} 件 (mode {'/'.join(modes)}) — observe なら block で差し戻していた件数")
    return {"by_flavor": by, "unresolved": unresolved, "findings": findings, "info": info}


def render(summary: dict, days: int) -> str:
    lines = [f"🖥 最初の返信の自己同定 stamp (直近 {days} 日、 workspace 内の session)"]
    for flavor, s in summary["by_flavor"].items():
        lines.append(f"  {flavor}: n={s['n']}  S1 (最初の返信の 1 行目) {s['s1']}/{s['n']}  "
                     f"S2 (最初の turn のどこか) {s['s2']}/{s['n']}")
        for r in s["misses"]:
            lines.append(f"    ✗ {r['date']} {r['session']}  「{r['head']}」")
    lines += ["  " + x for x in summary["findings"] + summary["info"]]
    if not summary["by_flavor"]:
        lines.append("  (対象 session なし)")
    return "\n".join(lines)


def selftest() -> int:
    import tempfile
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name)
        ok = ok and bool(cond)

    today = datetime.now().strftime("%Y-%m-%dT09:00:00Z")
    saved = {k: os.environ.get(k) for k in ("FIRST_REPLY_STAMP_CLAUDE_GLOB", "FIRST_REPLY_STAMP_CODEX_ROOT",
                                            "FIRST_REPLY_STAMP_BASE", "FIRST_REPLY_STAMP_STATE_DIR")}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = root / "base"
        (base / "repo").mkdir(parents=True)
        proj = root / "projects" / "p"
        proj.mkdir(parents=True)
        cwd = str(base / "repo")

        def write(name: str, rows: list[dict]) -> None:
            (proj / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

        def sess(first_text: str, later: str = "", cwd_: str = cwd, entry: str = "claude-desktop",
                 injected: str = "") -> list[dict]:
            rows = []
            if injected:
                rows.append({"type": "attachment", "cwd": cwd_, "entrypoint": entry,
                             "attachment": {"type": "hook_success", "hookEvent": "SessionStart",
                                            "command": "~/.claude/hooks/session-start-host-stamp.sh",
                                            "content": f"<system-reminder>\n{injected}\n</system-reminder>"}})
            rows.append({"type": "user", "cwd": cwd_, "entrypoint": entry, "timestamp": today,
                         "message": {"content": "やって"}})
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": first_text}]}})
            if later:
                rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": later}]}})
            return rows

        write("aaaaaaaa-1.jsonl", sess("🖥 h · desktop = x · session aaaaaaaa\n本文"))
        write("bbbbbbbb-2.jsonl", sess("Status: reading", later="🖥 h · desktop = x · session bbbbbbbb"))
        write("cccccccc-3.jsonl", sess("確認中です", injected="🖥 h · desktop = account 未同定 · session cccccccc"))
        write("dddddddd-4.jsonl", sess("sandbox", cwd_=str(root / "sandbox")))
        write("eeeeeeee-5.jsonl", sess("routine", entry="sdk-cli"))
        codex = root / "codex" / "2026" / "09" / "12"
        codex.mkdir(parents=True)
        (codex / "rollout-x-ffffffff-0000.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"type": "session_meta", "payload": {"id": "f", "cwd": cwd}},
            {"type": "event_msg", "timestamp": today, "payload": {"type": "user_message", "message": "go"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": "Working"}]}},
        ]) + "\n", encoding="utf-8")
        os.environ.update({"FIRST_REPLY_STAMP_CLAUDE_GLOB": str(root / "projects" / "*" / "*.jsonl"),
                           "FIRST_REPLY_STAMP_CODEX_ROOT": str(root / "codex"),
                           "FIRST_REPLY_STAMP_BASE": str(base),
                           "FIRST_REPLY_STAMP_STATE_DIR": str(root / "state")})
        frs.log_stop("claude", {"ts": datetime.now(timezone.utc).isoformat(), "mode": "observe", "session": "cccccccc"})

        rows = collect(14, with_codex=True)
        claude = [r for r in rows if r["flavor"] == "claude"]
        check("範囲: sandbox と headless を除いて claude 3 件", len(claude) == 3)
        s = summarize(rows, stop_log(14), threshold=0.10, min_sessions=1, fix_date="2000-01-01")
        c = s["by_flavor"]["claude"]
        check("S1 = 1/3 (最初の返信の 1 行目)", c["s1"] == 1)
        check("S2 = 2/3 (後の返信の 1 行目も数える)", c["s2"] == 2)
        check("codex rollout も数える (S2 0/1)", s["by_flavor"]["codex"]["s2"] == 0)
        check("未同定の注入を所見にする", any("未同定" in f for f in s["findings"]))
        check("閾値超えの見落としを所見にする", any("claude: 最初の turn" in f for f in s["findings"]))
        check("Stop 段の記録を info に出す", any("Stop 段の記録 1 件" in x for x in s["info"]))
        check("render に見落とし session が並ぶ", "cccccccc" in render(s, 14))
        quiet = summarize([r for r in rows if r["s2"]], [], threshold=0.10, min_sessions=1)
        check("全部出ていれば所見なし", not quiet["findings"] and not quiet["info"])
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="最初の返信の自己同定 stamp の事後 audit")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--min-sessions", type=int, default=5)
    ap.add_argument("--no-codex", action="store_true")
    ap.add_argument("--since", default="", help="この日 (YYYY-MM-DD) 以降に始まった session だけ数える (= 機構の導入日で切る)")
    ap.add_argument("--findings-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    rows = collect(args.days, with_codex=not args.no_codex, since_date=args.since)
    summary = summarize(rows, stop_log(args.days), args.threshold, args.min_sessions)
    if args.json:
        print(json.dumps({"rows": rows, **summary}, ensure_ascii=False, indent=1, default=str))
    elif args.findings_only:
        if summary["findings"] or summary["info"]:
            print(render(summary, args.days))
    else:
        print(render(summary, args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
