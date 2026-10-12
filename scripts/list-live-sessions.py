#!/usr/bin/env python3
"""list-live-sessions.py — 同 cwd で生きてる兄弟 Claude session を surface する read-only reader。

規約: conventions/multi-session-coordination.md (並列 session と同じ repo を触るときの race-awareness)

= なぜ存在するか:
  harness は全 live session を `~/.claude/sessions/<pid>.json` に刻印している
  ({pid, sessionId(=transcript UUID), cwd, startedAt, entrypoint})。 無人の `claude -p` も実行中は刻印を書き、 終了で消す
  (実測)。 ⚠️ 刻印の `kind` / `entrypoint` は起動した側の env を継ぐ = desktop の session の Bash から起動した `claude -p` は
  `kind: interactive`・`entrypoint: claude-desktop` と書いた (実測) = 刻印の欄から無人の実行かは判別できない。 これは
  multi-session-coordination.md §1「同 file path を別 session が独立に上書きする race」 の
  awareness 素材として既に在るのに、 session には surface されていない。 本 script は
  その disk 刻印を読み、 *同じ cwd で今 生きてる兄弟 session* を一覧化する (= discovery 半分の robust 実体)。

  読む刻印はこの機械の全部の設定フォルダ (~/.claude と ~/.claude-* と $CLAUDE_CONFIG_DIR)。 各行に、 その刻印の
  socket から作る SendMessage の宛先 (`uds:<path>`) を出す: harness の ListAgents は設定フォルダごとで、 別の
  設定フォルダ (= アカウント固定の Remote Control server = スマホから始めた session) の兄弟は名前で届かないことがあるが、
  この宛先なら設定フォルダとアカウントを跨いで届く (実測。 規約 = multi-account-machine-surface.md#peer-discovery-across-config-dirs)。
  desktop app の `send_message` (ccd) の `local_<uuid>` は扱わない。

  同じ機械の Codex の thread も出す (lib/codex_threads.py: thread の書き込み lock を process が開いている = 生きている)。
  Codex には SendMessage が無いので、 宛先の代わりに `codex queue --thread <id> --message …` の 1 行を出す
  (生きている thread には今の turn の後の新しい turn として届く = 実測。 規約 = multi-account-machine-surface.md#codex-peers)。

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

# 読む場所 = この機械の全部の設定フォルダ (~/.claude / $CLAUDE_CONFIG_DIR / ~/.claude-*、 lib/claude_config_dirs.py)。
# アカウント固定の Remote Control server (= スマホから始めた session) や CLAUDE_CONFIG_DIR を付けた CLI は ~/.claude でなく
# 自分の設定フォルダに刻印と transcript を書く。 ~/.claude だけを読むと、 その session は生きていても兄弟に出ない (実測)。
# 各行に設定フォルダの名前と SendMessage の宛先 (`uds:<socket>`) を出す = harness の ListAgents は設定フォルダごとなので、
# 別の設定フォルダの session には名前では届かず、 この宛先なら届く (規約 = multi-account-machine-surface.md#peer-discovery-across-config-dirs)。
# test 用 env override: CLAUDE_SESSIONS_DIR / CLAUDE_PROJECTS_DIR = 1 つの dir で走査を置き換える。
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import claude_config_dirs as _ccd
except Exception:  # pragma: no cover - 古い配置
    _ccd = None


def _sessions_dirs() -> list[str]:
    if _ccd is not None:
        return _ccd.sessions_dirs()
    return [os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.expanduser("~/.claude/sessions")]


def _projects_dirs() -> list[str]:
    if _ccd is not None:
        return _ccd.projects_dirs()
    return [os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")]

# 各 session の実際の model (transcript の最後の応答の message.model)。 題名の札や chip の tag は推奨で、
# model を決めない = 仕事を送る前に読む値 (multi-session-coordination.md#delegate-model-routing)。
# lib が無い配置 (古い checkout) では列を空にして動き続ける。
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import session_model as _sm
except Exception:  # pragma: no cover - 古い配置
    _sm = None


def _model_of(session_id: str, cwd: str) -> str:
    if _sm is None:
        return ""
    try:
        return _sm.model_of(session_id, cwd or None)
    except Exception:
        return ""


try:
    import codex_threads as _ct
except Exception:  # pragma: no cover - 古い配置
    _ct = None


def collect_codex(cwd_filter: str | None = None) -> list[dict]:
    """同じ機械で生きている Codex の thread (sub-agent を除く)。 読めなければ [] (fail-open)。"""
    if _ct is None:
        return []
    try:
        return _ct.live_threads(cwd=cwd_filter) or []
    except Exception:
        return []


def _codex_lines(rows: list[dict], indent: str = "   ") -> list[str]:
    out = []
    for r in rows:
        out.append(f"{indent}• codex {_ct.describe(r)}")
        out.append(f"{indent}  知らせる (SendMessage は無い) = {_ct.queue_hint(r['id'])}")
    return out


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
    path = ""
    for root in _projects_dirs():
        p = os.path.join(root, _encode_cwd(cwd), f"{session_id}.jsonl")
        if os.path.isfile(p):
            path = p
            break
    if not path:
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
    files = []
    try:
        for sdir in _sessions_dirs():
            label = _ccd.label_of(sdir) if _ccd is not None else ""
            files += [(f, label) for f in glob.glob(os.path.join(sdir, "*.json"))]
    except Exception:
        return out
    now_ms = int(time.time() * 1000)
    seen: set[str] = set()
    for f, label in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        pid = d.get("pid")
        sid = d.get("sessionId", "")
        cwd = d.get("cwd", "")
        if not isinstance(pid, int) or not sid or sid in seen:
            continue
        if cwd_filter and cwd != cwd_filter:
            continue
        if not _pid_alive(pid):
            continue  # stale file (= 死んだ process の置き土産)
        started = d.get("startedAt")
        age_min = None
        if isinstance(started, (int, float)):
            age_min = max(0, (now_ms - started) // 60000)
        seen.add(sid)
        out.append({
            "pid": pid,
            "sessionId": sid,
            "cwd": cwd,
            "started_at": started,
            "age_min": age_min,
            "entrypoint": d.get("entrypoint", ""),
            "is_self": bool(self_uuid) and sid == self_uuid,
            "intent": _intent_snippet(sid, cwd),
            "model": _model_of(sid, cwd),
            "config": label,
            "address": _ccd.socket_address(d) if _ccd is not None else "",
        })
    out.sort(key=lambda r: (r["cwd"], -(r["started_at"] or 0)))
    return out


def _fmt_age(m):
    if m is None:
        return "?"
    if m < 60:
        return f"{m}分"
    return f"{m // 60}時間{m % 60}分"


def render(rows: list[dict], self_uuid: str | None, codex_rows: list[dict] | None = None) -> str:
    codex_rows = codex_rows or []
    if not rows and not codex_rows:
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
            model = f" / {r['model']}" if r.get("model") else " / model ?"
            cfg = f" / 設定フォルダ {r['config']}" if r.get("config") not in (None, "", "default") else ""
            to = f"\n       SendMessage の to = {r['address']}" if r.get("address") and not r["is_self"] else ""
            lines.append(f"   • pid {r['pid']} / {sid} / {_fmt_age(r['age_min'])}前起動{model}{cfg}{tag}{intent}{to}")
    if codex_rows:
        lines.append(f"🤖 Codex の生きている thread — {len(codex_rows)} 個")
        lines += _codex_lines(codex_rows)
    return "\n".join(lines)


def _other_dir_note(r: dict, self_config: str | None) -> str:
    """自分と別の設定フォルダの兄弟には宛先を添える (ListAgents の名前では届かないことがある)。"""
    if not r.get("address") or self_config is None or r.get("config") == self_config:
        return ""
    return f" [設定フォルダ {r.get('config') or '?'} → to={r['address']}]"


OTHER_DIR_FOOTER = ("   ↳ [設定フォルダ …] = 自分と別の設定フォルダの session。 ListAgents の名前では届かないことがある"
                    " (別アカウントでは実測で出なかった) → 知らせるなら SendMessage の to に、 その uds: 宛先をそのまま書く")


def surface(self_uuid: str | None, cwd_filter: str | None) -> str:
    """hook/dashboard 向け: 自分以外の兄弟が同 cwd に在る時だけ短文、 無ければ空 (= 沈黙)。"""
    rows = collect(self_uuid=self_uuid, cwd_filter=cwd_filter)
    siblings = [r for r in rows if not r["is_self"]]
    self_rows = [r for r in rows if r["is_self"]]
    # 自分の設定フォルダ: self 行から、 無ければ CLAUDE_CONFIG_DIR (hook は self 行より先に走ることがある)
    self_config = self_rows[0].get("config") if self_rows else (
        _ccd.label(os.environ["CLAUDE_CONFIG_DIR"]) if _ccd is not None and os.environ.get("CLAUDE_CONFIG_DIR") else
        ("default" if _ccd is not None else None))
    # cwd_filter 無指定なら「自分の cwd」 を self 行から推定して同 cwd のみに絞る
    mycwd = cwd_filter
    if not cwd_filter and self_uuid:
        if self_rows:
            mycwd = self_rows[0]["cwd"]
            siblings = [r for r in siblings if r["cwd"] == mycwd]
    # 同じ cwd の Codex の thread (cwd が分からなければ出さない = 機械じゅうの Codex を毎回並べない)
    codex_rows = collect_codex(mycwd) if mycwd else []
    if not siblings and not codex_rows:
        return ""
    if not siblings:
        return (f"🔀 同じ作業ディレクトリで Codex の thread が {len(codex_rows)} 個生きています"
                " (並列上書き race 注意 → 編集前に git fetch + 突き合わせ):\n" + "\n".join(_codex_lines(codex_rows)))
    head = f"🔀 同じ作業ディレクトリで {len(siblings)} 個の別 session が生きています (並列上書き race 注意 → 編集前に git fetch + 突き合わせ):"
    body = []
    for r in siblings:
        intent = f" — 「{r['intent']}」" if r["intent"] else ""
        model = f", {r['model']}" if r.get("model") else ""
        body.append(f"   • {r['sessionId'][:8]} ({_fmt_age(r['age_min'])}前起動{model}){intent}{_other_dir_note(r, self_config)}")
    if any(_other_dir_note(r, self_config) for r in siblings):
        body.append(OTHER_DIR_FOOTER)
    if codex_rows:
        body.append(f"   🤖 同じ作業ディレクトリの Codex の thread — {len(codex_rows)} 個")
        body += _codex_lines(codex_rows, indent="     ")
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
    # 設定フォルダを跨ぐ: ~/.claude の自分と ~/.claude-alpha の兄弟 (= スマホから始めた session の形)
    if _ccd is not None:
        import tempfile
        saved = {k: os.environ.get(k) for k in ("CLAUDE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR", "CLAUDE_CONFIG_DIRS_HOME", "CLAUDE_CONFIG_DIR")}
        try:
            with tempfile.TemporaryDirectory() as td:
                for k in saved:
                    os.environ.pop(k, None)
                os.environ["CLAUDE_CONFIG_DIRS_HOME"] = td
                for cfg, sid, pidf in ((".claude", "aaaaaaaa-0000-0000-0000-000000000001", "1"),
                                       (".claude-alpha", "bbbbbbbb-0000-0000-0000-000000000002", "2")):
                    os.makedirs(os.path.join(td, cfg, "sessions"))
                    os.makedirs(os.path.join(td, cfg, "projects", _encode_cwd("/w/p")))
                    with open(os.path.join(td, cfg, "sessions", pidf + ".json"), "w", encoding="utf-8") as fh:
                        json.dump({"pid": os.getpid(), "sessionId": sid, "cwd": "/w/p", "startedAt": 0,
                                   "messagingSocketPath": f"/tmp/cc-socks/{pidf}.sock"}, fh)
                    with open(os.path.join(td, cfg, "projects", _encode_cwd("/w/p"), sid + ".jsonl"), "w", encoding="utf-8") as fh:
                        fh.write(json.dumps({"type": "user", "message": {"content": f"topic in {cfg}"}}, separators=(",", ":")) + "\n")
                rows = collect(self_uuid="aaaaaaaa-0000-0000-0000-000000000001")
                other = [r for r in rows if r["sessionId"].startswith("bbbbbbbb")]
                if not (len(rows) == 2 and other and other[0]["config"] == "alpha" and other[0]["address"] == "uds:/tmp/cc-socks/2.sock"):
                    print(f"FAIL collect across config dirs: {rows}"); ok = False
                if not (other and other[0]["intent"] == "topic in .claude-alpha"):
                    print("FAIL intent read from the other config dir's transcript"); ok = False
                s = surface("aaaaaaaa-0000-0000-0000-000000000001", None)
                if "bbbbbbbb" not in s or "to=uds:/tmp/cc-socks/2.sock" not in s or "ListAgents" not in s:
                    print(f"FAIL surface: sibling in another config dir must carry its address: {s!r}"); ok = False
                s2 = surface("bbbbbbbb-0000-0000-0000-000000000002", None)
                if "aaaaaaaa" not in s2 or "uds:/tmp/cc-socks/1.sock" not in s2:
                    print(f"FAIL surface from the pinned side: {s2!r}"); ok = False
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    # Codex の thread: 同じ cwd で lock が開かれていれば surface に queue の 1 行つきで出る / 別 cwd は出ない
    if _ct is not None and _ct.held_lock_ids() is not None:
        import sqlite3
        import tempfile
        saved = {k: os.environ.get(k) for k in ("CODEX_HOME", "CODEX_CLI_PATH", "CLAUDE_SESSIONS_DIR")}
        try:
            with tempfile.TemporaryDirectory() as td:
                tid = "01a00000-0000-7000-8000-0000000000cc"
                os.environ["CODEX_HOME"] = td
                os.environ["CODEX_CLI_PATH"] = os.path.join(td, "codex")
                with open(os.environ["CODEX_CLI_PATH"], "w") as fh:
                    fh.write("#!/bin/sh\n")
                os.chmod(os.environ["CODEX_CLI_PATH"], 0o755)
                os.environ["CLAUDE_SESSIONS_DIR"] = os.path.join(td, "none")
                os.makedirs(os.path.join(td, "thread-writer-locks"))
                db = sqlite3.connect(os.path.join(td, "state_5.sqlite"))
                db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, title TEXT, model TEXT, source TEXT, updated_at INTEGER, archived INTEGER)")
                db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?)", (tid, "/w/codex", "codex fixture", "m-x", "vscode", 1, 0))
                db.commit(); db.close()
                lock = os.path.join(td, "thread-writer-locks", tid + ".lock")
                open(lock, "w").close()
                if surface(None, "/w/codex") != "":
                    print("FAIL codex: an unheld lock must not count as live"); ok = False
                with open(lock):
                    s = surface(None, "/w/codex")
                    if "codex 01a00000" not in s or f"queue --thread {tid}" not in s:
                        print(f"FAIL codex: live thread in the same cwd must be surfaced with its queue line: {s!r}"); ok = False
                    if surface(None, "/w/other") != "":
                        print("FAIL codex: a thread in another cwd must stay out of the surface"); ok = False
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
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
        print(render(rows, args.self_uuid, collect_codex(args.cwd_filter)))
        return 0
    except Exception as e:
        # fail-open: 何があっても dashboard/hook を止めない
        sys.stderr.write(f"list-live-sessions: {e}\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
