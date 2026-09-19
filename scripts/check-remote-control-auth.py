#!/usr/bin/env python3
"""check-remote-control-auth.py — Remote Control サーバーの auth を **この機械で** 診断する。

なぜ要るか (= 既存の網の穴):
  fleet の heartbeat は各サーバーの log を文字列で分類して `auth_error` を報告するが、
  「未 login」 と「環境変数の混入」 の **2 つの原因を 1 つの値に畳んで** いる (= 原因の
  異なる 2 状態が同じ顔をする。 convention-design-principles.md #silent-probe-false-healthy)。
  しかも heartbeat は**他の機械から**見える情報なので、 実際に切り分ける command は
  その機械で人が叩くしかなかった = 「次に触った人が思い出す」 頼み (= 人の記憶は carrier でない)。
  本 script は切り分けをその機械の session 開始に載せて、 結論と直し方まで出す。

判定 (= 3 状態を畳まない):
  ok            authMethod == "claude.ai" かつ loggedIn
  api_key       ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN の混入 (= RC は subscription auth 必須で
                API key を拒否する。 ⚠️ この状態では `claude auth status` 自体が loggedIn: true と
                答えるので、 loggedIn だけを見る判定は騙される)
  logged_out    素直な失効・未 login
  unknown       probe を実行できなかった (= **ok に畳まない**。 「測れなかった」 と「健全」 を分ける)

安い検出 → 高い判別:
  まず log の末尾を読んで auth の疑いがある server だけを選び、 その server にだけ
  `claude auth status` を実行する (= 健全なときの追加コストをほぼ 0 にする)。 `--all` で全 server を probe。

台帳 (= 体感を data にする):
  分類が前回と変わった時だけ 1 行追記する (既定 ~/.local/state/claude-remote-control-auth/transitions.log)。
  「別の機械で login したら切れた気がする」 のような仮説は、 切り替わった時刻が並んで初めて検証できる。
  ⚠️ 値 (token / email) は書かない。 書くのは config-dir 名・分類・時刻だけ。

usage:
  check-remote-control-auth.py [--surface] [--all] [--json] [--selftest]
    --surface  finding があるときだけ surface 用の見出しつきで出す (無ければ完全沈黙)
    --all      log の状態に関わらず全 server を probe する
    --json     機械可読

規約: conventions/remote-control-server.md #ts-api-key-conflict / #account-auth-keychain
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

# heartbeat が log から auth 異常を読むのと同じ語 (= 2 つの網が別々の語を持つと片方だけ黙る)
AUTH_TROUBLE = (
    "not logged in",
    "must be logged in",
    "requires a claude.ai subscription",
    "requires claude.ai subscription auth",
)
CONTAMINATING_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
LOG_TAIL_BYTES = 8192


def _agents_dir() -> Path:
    return Path(os.environ.get("RCAUTH_AGENTS_DIR") or (Path.home() / "Library/LaunchAgents"))


def _state_path() -> Path:
    return Path(
        os.environ.get("RCAUTH_STATE")
        or (Path.home() / ".local/state/claude-remote-control-auth/transitions.log")
    )


def discover_servers(agents_dir: Path) -> list[dict]:
    """launchd の plist から Remote Control サーバーを拾う (= 登録されている物だけが対象)."""
    out = []
    if not agents_dir.is_dir():
        return out
    for p in sorted(agents_dir.glob("*remote-control-server*.plist")):
        try:
            d = plistlib.loads(p.read_bytes())
        except Exception:
            continue
        label = d.get("Label") or p.stem
        args = d.get("ProgramArguments") or []
        cmd = " ".join(a for a in args if isinstance(a, str))
        m = re.search(r'CLAUDE_CONFIG_DIR=(?:")?([^"\s;]+)', cmd)
        cfg = m.group(1) if m else (d.get("EnvironmentVariables") or {}).get("CLAUDE_CONFIG_DIR")
        out.append({
            "label": label,
            "config_dir": cfg,
            "log": d.get("StandardErrorPath") or d.get("StandardOutPath"),
            "alias": label.rsplit(".", 1)[-1],
        })
    return out


def log_suspects_auth(log_path: str | None) -> bool:
    """log の末尾に auth 異常の語があるか (= 安い検出)."""
    if not log_path:
        return False
    p = Path(log_path)
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > LOG_TAIL_BYTES:
                f.seek(-LOG_TAIL_BYTES, os.SEEK_END)
            tail = f.read().decode("utf-8", "replace").lower()
    except Exception:
        return False
    return any(w in tail for w in AUTH_TROUBLE)


def probe(config_dir: str | None, timeout: int = 20) -> tuple[str, str]:
    """`claude auth status` を汚染変数を外して叩き、 (分類, 詳細) を返す."""
    exe = os.environ.get("RCAUTH_CLAUDE") or shutil.which("claude") \
        or str(Path.home() / ".local/bin/claude")
    if not Path(exe).exists() and not shutil.which(exe):
        return "unknown", "claude を起動できない (PATH にも既定の場所にも無い)"
    env = dict(os.environ)
    for k in CONTAMINATING_ENV:
        env.pop(k, None)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True,
                           timeout=timeout, env=env)
    except Exception as e:
        return "unknown", f"probe を実行できなかった ({type(e).__name__})"
    blob = (r.stdout or "") + (r.stderr or "")
    try:
        j = json.loads(blob[blob.index("{"):blob.rindex("}") + 1])
    except Exception:
        return "unknown", "probe の出力を解釈できなかった"
    method, logged = j.get("authMethod"), bool(j.get("loggedIn"))
    if method == "claude.ai" and logged:
        return "ok", "claude.ai"
    if method == "api_key" or (logged and method != "claude.ai"):
        return "api_key", f"authMethod={method}"
    return "logged_out", f"loggedIn={logged} authMethod={method}"


def record_transition(state: Path, rows: list[dict], now: str) -> list[str]:
    """分類が前回と変わった物だけ台帳に 1 行 (= 体感を時刻の並びにする)."""
    prev: dict[str, str] = {}
    try:
        for line in state.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                prev[parts[1]] = parts[2]
    except Exception:
        pass
    changed = []
    for r in rows:
        key, cur = r["alias"], r["status"]
        if prev.get(key) != cur:
            changed.append(f"{now}\t{key}\t{cur}")
    if changed:
        try:
            state.parent.mkdir(parents=True, exist_ok=True)
            with state.open("a", encoding="utf-8") as f:
                f.write("\n".join(changed) + "\n")
        except Exception:
            pass
    return changed


FIX = {
    "logged_out": ("🔴", "失効・未 login", 'CLAUDE_CONFIG_DIR="{cfg}" claude auth login'),
    "api_key": ("🔴", "環境変数の混入 (= RC は subscription auth 必須。 この状態では auth status 自体が "
                      "loggedIn: true と答えるので、 loggedIn だけを見る判定は騙される)",
                'unset {vars} してから CLAUDE_CONFIG_DIR="{cfg}" claude auth login '
                '(恒久対策は shell 起動 file の export 元を消す)'),
    "unknown": ("⚠️", "判定できなかった (= 健全と同じ扱いにしない)", "手で 1 度叩いて確かめる"),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surface", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()

    servers = discover_servers(_agents_dir())
    if not servers:
        return 0

    contaminated = [k for k in CONTAMINATING_ENV if os.environ.get(k)]
    rows = []
    for s in servers:
        suspect = a.all or log_suspects_auth(s["log"])
        if not suspect:
            rows.append({**s, "status": "ok", "detail": "log に auth 異常なし (probe 省略)"})
            continue
        st, detail = probe(s["config_dir"])
        rows.append({**s, "status": st, "detail": detail})

    now = _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
    record_transition(_state_path(), rows, now)

    if a.json:
        print(json.dumps({"servers": rows, "contaminated_env": contaminated}, ensure_ascii=False, indent=2))
        return 0

    bad = [r for r in rows if r["status"] != "ok"]
    if not bad and not contaminated:
        return 0

    lines = []
    if a.surface:
        lines.append("# 🔑 Remote Control の auth (この機械)")
    for r in bad:
        mark, what, fix = FIX[r["status"]]
        cfg = r["config_dir"] or "(config-dir 不明)"
        lines.append(f"  {mark} {r['alias']}: {what} — {r['detail']}")
        lines.append("     直す = " + fix.format(cfg=cfg, vars=" ".join(CONTAMINATING_ENV)))
    if contaminated:
        lines.append(f"  ⚠️ この session の環境に {' / '.join(contaminated)} が set されている "
                     "(= RC は拒否し、 auth status も嘘をつく側に倒れる)")
    if bad:
        lines.append("     ⚠️ heartbeat の `auth_error` は未 login と環境変数の混入を同じ値に畳むので、"
                     " 他機から見た表示では区別できない (本 script がこの機械で切り分ける)。")
        lines.append("     切り替わった時刻の並び = " + str(_state_path()))
    print("\n".join(lines))
    return 0


def _selftest() -> int:
    import tempfile
    ok = fail = 0

    def chk(cond, name):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS: {name}")
        else:
            fail += 1
            print(f"  FAIL: {name}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # discover: plist から config-dir と log を拾う
        agents = td / "agents"
        agents.mkdir()
        logp = td / "srv.log"
        pl = {
            "Label": "com.example.remote-control-server.alpha",
            "ProgramArguments": ["/bin/sh", "-c",
                                 'export CLAUDE_CONFIG_DIR="/tmp/cfg-alpha"; exec claude remote-control'],
            "StandardErrorPath": str(logp),
        }
        (agents / "com.example.remote-control-server.alpha.plist").write_bytes(plistlib.dumps(pl))
        got = discover_servers(agents)
        chk(len(got) == 1 and got[0]["config_dir"] == "/tmp/cfg-alpha", "discover: config-dir を拾う")
        chk(got[0]["alias"] == "alpha", "discover: alias は label 末尾")
        chk(discover_servers(td / "nope") == [], "discover: dir が無ければ空 (fail-open)")

        # 安い検出: log の語で疑う / 無ければ疑わない
        logp.write_text("all good\nConnected\n", encoding="utf-8")
        chk(log_suspects_auth(str(logp)) is False, "log: 正常な log は疑わない")
        logp.write_text("Error: You must be logged in to use Remote Control.\n", encoding="utf-8")
        chk(log_suspects_auth(str(logp)) is True, "log: auth 異常の語を拾う")
        chk(log_suspects_auth(str(td / "missing.log")) is False, "log: 無い file は疑わない (fail-open)")

        # 台帳: 変化した時だけ書く
        st = td / "trans.log"
        rows1 = [{"alias": "alpha", "status": "logged_out"}]
        chk(len(record_transition(st, rows1, "T1")) == 1, "台帳: 初回は 1 行")
        chk(len(record_transition(st, rows1, "T2")) == 0, "台帳: 変わらなければ書かない")
        rows2 = [{"alias": "alpha", "status": "ok"}]
        chk(len(record_transition(st, rows2, "T3")) == 1, "台帳: 変わったら書く")
        body = st.read_text(encoding="utf-8")
        chk("logged_out" in body and "ok" in body and "token" not in body, "台帳: 分類だけで値を書かない")

        # probe: 3 状態を畳まない (claude を偽物に差し替えて分類だけ見る)
        def fake(out: str) -> str:
            f = td / f"fake{abs(hash(out))}.sh"
            f.write_text(f"#!/bin/sh\ncat <<'J'\n{out}\nJ\n", encoding="utf-8")
            f.chmod(0o755)
            return str(f)

        os.environ["RCAUTH_CLAUDE"] = fake('{"loggedIn": true, "authMethod": "claude.ai"}')
        chk(probe("/tmp/x")[0] == "ok", "probe: claude.ai + loggedIn = ok")
        os.environ["RCAUTH_CLAUDE"] = fake('{"loggedIn": true, "authMethod": "api_key"}')
        chk(probe("/tmp/x")[0] == "api_key", "probe: api_key は ok に畳まない (loggedIn: true でも)")
        os.environ["RCAUTH_CLAUDE"] = fake('{"loggedIn": false, "authMethod": null}')
        chk(probe("/tmp/x")[0] == "logged_out", "probe: 未 login")
        os.environ["RCAUTH_CLAUDE"] = fake("not json at all")
        chk(probe("/tmp/x")[0] == "unknown", "probe: 解釈できなければ unknown (ok に畳まない)")
        os.environ["RCAUTH_CLAUDE"] = str(td / "does-not-exist")
        chk(probe("/tmp/x")[0] == "unknown", "probe: claude が無ければ unknown")
        os.environ.pop("RCAUTH_CLAUDE", None)

    print(f"\n=== Result: {ok} passed, {fail} failed ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
