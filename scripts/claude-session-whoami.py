#!/usr/bin/env python3
"""claude-session-whoami.py — session の host / surface (desktop|CLI) / account を機械同定する probe。

desktop app の session では harness 注入の userEmail が session の実 account と乖離し得る
(下記) ため、 「この session はどのアカウントで走っているか」 はこの probe で同定する。

## なぜ要るか (2026-08-28 実測 RCA)

Claude Code desktop app は bundled CLI に自 account の `CLAUDE_CODE_OAUTH_TOKEN` を env で
渡すだけで、 email/account metadata を渡さない。 CLI は harness が session に注入する
userEmail を**自分の config (= `~/.claude.json` の `oauthAccount` = CLI login 層)** から組む。
∴ 「desktop のログイン account ≠ CLI (`claude auth login`) の account」 のマシンでは、
**desktop の全 session が構造的に誤った userEmail を注入され**、 モデルがそれを信じて
自分を別 account と誤同定する (実測で user 訂正により発覚)。
一般則 = conventions/multi-account-machine-surface.md §典型的な破れかた。

## 同定 logic

surface 判定 = env CLAUDE_CODE_ENTRYPOINT ('claude-desktop' = desktop app / それ以外 = CLI 系)。
CLI 系のうち **Remote Control server 配下** (= スマホ / 別マシンから bridge で入っている session) は
CLAUDE_PID とその祖先 process (3 段) の cmdline に `remote-control` が居れば `rc/<label>` と出す
(2026-09-05 追加、 user 要望「リモートかどうかも頭に表示」。 ps 経路が失敗したら `cli/<label>` に
fail-open = リモート性を捏造しない。 ⚠️ RC 実機での検証は未実施 = 初回 RC session の stamp で確認)。

desktop の account:
  1. env CLAUDE_CODE_HOST_SESSION_ID (= app が bundled CLI に渡す host session id) を key に
     ~/Library/Application Support/Claude/claude-code-sessions/<accountUuid>/<orgUuid>/<hostSid>.json
     を glob → **path の <accountUuid> が session の account** (2026-08-28 実測で確立)。
     ⚠️ **registry file は session 開始の直後にはまだ無いことがある** (2026-09-11 実測: app の
     `createdAt` から ~2 秒以内に走った SessionStart hook では 18/20 が miss し、 解決した 2 件は
     作成から 2.2 秒 / 4.7 秒後に走っていた)。 → hook は `--wait SECS` で registry の出現を待つ。
     tool call 時点 (= 数秒後) の実行では通常すでに在る。
  2. fallback: env CLAUDE_PID の process cmdline に app が焼き込む
     `--plugin-dir .../skills-plugin/<orgUuid>/<accountUuid>` を parse。
     ⚠️ 2026-09-11 実測: 現行の desktop 埋込 build (2.1.26x) の CLI cmdline には `--plugin-dir` も
     account uuid も**無い** = この経路は旧 build 用の残置で、 今は効かない。 path の
     `Application Support` は ps 出力で空白を含むので、 正規表現は空白を跨いで読む。
  uuid → email の解決 = ~/.claude.json / ~/.claude/.claude.json / ~/.claude-*/.claude.json の
  oauthAccount を scan (各 file 内の accountUuid⇄emailAddress pair は常に内部整合なので、
  pinned dir の auth が alias と食い違っていても map としては truthful)。
  未解決 uuid は uuid のまま出す (= 「不明」 を email で埋めない)。

CLI 系 (terminal / RC server / headless -p) の account:
  $CLAUDE_CONFIG_DIR (無ければ ~/.claude) の .claude.json oauthAccount が正 (= この層では
  従来どおり信じてよい。 desktop でだけ嘘になるのが本 probe の存在理由)。

同定できない経路 (2026-08-28 実測、 verified scope): app 内 MCP `get_session` の返却に
account field は無い / env に email を直接運ぶ変数は無い / keychain・`oauth:tokenCache` は
暗号化で読めない。 ⚠️ transcript 先頭の `bridge-session.ownerAccountUuid` も session の
account ではない (2026-09-11 実測: registry の account と 42/95 で食い違った) — 使わない。

⚠️ 射程: macOS + Claude for Mac (desktop app) の内部 path 依存。 app update で registry 構造が
   変わったら「account 未同定」 に fail-open する (= 嘘はつかない) — その時は本 docstring の
   logic を実測し直す。 test 用に registry の場所は env CLAUDE_WHOAMI_SESSIONS_DIR で差し替えられる。

usage:
  claude-session-whoami.py            # 詳細 (stamp + source + 警告)
  claude-session-whoami.py --stamp    # 1 行 stamp のみ
  claude-session-whoami.py --who      # 'surface = account' 部分のみ (SessionStart hook 用)
  claude-session-whoami.py --wait 3   # desktop registry の出現を最大 3 秒待つ (他 flag と併用)
  claude-session-whoami.py --session-id  # native session UUID 全体 (= env CLAUDE_CODE_SESSION_ID、 board 等の宛先 id に使う)
  claude-session-whoami.py --selftest # fixture selftest
"""

import glob
import json
import os
import re
import socket
import subprocess
import sys
import time

APP_SESSIONS_DIR = os.environ.get("CLAUDE_WHOAMI_SESSIONS_DIR") or os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code-sessions")

# ps の cmdline は argv を空白で連結するだけ = path 中の空白 (Application Support) を
# quote しない。 ∴ `\S*?` では跨げない (2026-09-11 に発見した旧 regex の欠陥)。
_PLUGIN_DIR_RE = re.compile(
    r"--plugin-dir\s+.*?/skills-plugin/[0-9a-f-]{36}/([0-9a-f-]{36})")


def _read_oauth(path):
    try:
        with open(path) as f:
            oa = json.load(f).get("oauthAccount") or {}
        uuid, email = oa.get("accountUuid"), oa.get("emailAddress")
        if uuid and email:
            return uuid, email
    except Exception:
        pass
    return None


def uuid_email_map(home=None):
    """既知の accountUuid → emailAddress map (CLI 系 config file 群を scan)。"""
    home = home or os.path.expanduser("~")
    m = {}
    # base は歴史的に ~/.claude.json (top-level) と ~/.claude/.claude.json の二重配置 (両方 scan)
    for p in [os.path.join(home, ".claude.json"),
              os.path.join(home, ".claude", ".claude.json")] + sorted(
            glob.glob(os.path.join(home, ".claude-*", ".claude.json"))):
        pair = _read_oauth(p)
        if pair:
            m[pair[0]] = pair[1]
    return m


def account_from_cmdline(cmd):
    """app が焼き込む --plugin-dir から accountUuid を読む (旧 build 用)。 無ければ None。"""
    m = _PLUGIN_DIR_RE.search(cmd or "")
    return m.group(1) if m else None


def _registry_hit(host_sid, sessions_dir):
    hits = glob.glob(os.path.join(glob.escape(sessions_dir), "*", "*",
                                  glob.escape(host_sid) + ".json"))
    return hits[0] if hits else None


def desktop_account_uuid(host_sid, sessions_dir=APP_SESSIONS_DIR, claude_pid=None, wait=0.0):
    """desktop session の accountUuid と、 どの経路で同定したか (source 文字列) を返す。

    wait > 0 なら registry file の出現を最大 wait 秒待つ (session 開始直後の race 対策)。"""
    if host_sid:
        deadline = time.monotonic() + max(0.0, float(wait or 0))
        while True:
            hit = _registry_hit(host_sid, sessions_dir)
            if hit:
                # .../claude-code-sessions/<accountUuid>/<orgUuid>/<hostSid>.json
                return (os.path.basename(os.path.dirname(os.path.dirname(hit))),
                        "claude-code-sessions registry (CLAUDE_CODE_HOST_SESSION_ID)")
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
    if claude_pid:
        try:
            out = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(claude_pid)],
                                 capture_output=True, text=True, timeout=5).stdout
            uuid = account_from_cmdline(out)
            if uuid:
                return uuid, "process cmdline --plugin-dir (CLAUDE_PID)"
        except Exception:
            pass
    return None, None


def _is_remote_control(env, max_depth=3):
    """CLAUDE_PID とその祖先 (max_depth 段) の cmdline に `remote-control` が居るか。
    ps 失敗・pid 不明は False (= fail-open で cli 表記に落ちる)。"""
    pid = env.get("CLAUDE_PID")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    for _ in range(max_depth):
        if pid <= 1:
            return False
        # ⚠️ macOS ps: `command` 列は**最後の -o に置かないと 16 文字に切られる** (2026-09-05 実測、
        #    -ww でも同じ) → ppid を先、 command を最後に並べて split(None, 1) で分ける
        try:
            out = subprocess.run(["ps", "-ww", "-o", "ppid=", "-o", "command=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            return False
        if not out:
            return False
        parts = out.split(None, 1)
        ppid, cmd = (parts[0], parts[1]) if len(parts) == 2 else ("0", out)
        if re.search(r"\bremote-control\b", cmd):
            return True
        try:
            pid = int(ppid)
        except ValueError:
            return False
    return False


def identify(env=None, home=None, sessions_dir=None, wait=0.0):
    """dict: host / surface / email / uuid / source / sid8 / warn"""
    env = env if env is not None else os.environ
    home = home or os.path.expanduser("~")
    sessions_dir = sessions_dir or APP_SESSIONS_DIR
    host = socket.gethostname().split(".")[0] or "unknown-host"
    sid8 = (env.get("CLAUDE_CODE_SESSION_ID") or "")[:8] or "unknown"
    entry = env.get("CLAUDE_CODE_ENTRYPOINT", "")
    r = {"host": host, "sid8": sid8, "email": None, "uuid": None,
         "source": None, "warn": None}
    if entry == "claude-desktop":
        r["surface"] = "desktop"
        uuid, source = desktop_account_uuid(
            env.get("CLAUDE_CODE_HOST_SESSION_ID"), sessions_dir,
            env.get("CLAUDE_PID"), wait)
        r["uuid"], r["source"] = uuid, source
        if uuid:
            r["email"] = uuid_email_map(home).get(uuid)
            if not r["email"]:
                r["warn"] = ("uuid は同定できたが email 未解決 (= 既知 config file 群に "
                             "この uuid の oauthAccount 無し)。 uuid で報告せよ")
        else:
            r["warn"] = ("desktop だが account 未同定 (registry / cmdline 両経路 miss)。 "
                         "userEmail で埋めるな — user に確認するのが正")
    else:
        cfg = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
        label = os.path.basename(cfg).removeprefix(".claude").removeprefix("-") or "base"
        kind = "rc" if _is_remote_control(env) else "cli"
        r["surface"] = f"{kind}/{label}"
        pair = _read_oauth(os.path.join(cfg, ".claude.json"))
        if pair:
            r["uuid"], r["email"] = pair
            r["source"] = f"{cfg}/.claude.json oauthAccount"
        else:
            r["warn"] = f"{cfg}/.claude.json に oauthAccount 無し (未 auth?)"
    return r


def who(r):
    w = r["email"] or (f"uuid {r['uuid'][:8]}…" if r["uuid"] else "account 未同定")
    return f"{r['surface']} = {w}"


def stamp(r):
    return f"🖥 {r['host']} · {who(r)} · session {r['sid8']}"


def selftest():
    import tempfile
    import threading
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        home = os.path.join(td, "home")
        sess = os.path.join(td, "app support", "claude-code-sessions")  # 空白入り = 実 path と同形
        uA, uB = "a" * 8 + "-1111-2222-3333-" + "a" * 12, "b" * 8 + "-1111-2222-3333-" + "b" * 12
        org = "c" * 8 + "-1111-2222-3333-" + "c" * 12
        os.makedirs(os.path.join(home, ".claude"))
        os.makedirs(os.path.join(home, ".claude-alt"))
        json.dump({"oauthAccount": {"accountUuid": uA, "emailAddress": "cli-base@example.com"}},
                  open(os.path.join(home, ".claude", ".claude.json"), "w"))
        json.dump({"oauthAccount": {"accountUuid": uB, "emailAddress": "alt@example.com"}},
                  open(os.path.join(home, ".claude-alt", ".claude.json"), "w"))
        os.makedirs(os.path.join(sess, uB, org))
        open(os.path.join(sess, uB, org, "local_abc.json"), "w").write("{}")

        # 1) desktop: registry 経路で uuid → alt email (≠ CLI base email = 誤同定の再現拒否)
        r = identify({"CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                      "CLAUDE_CODE_HOST_SESSION_ID": "local_abc",
                      "CLAUDE_CODE_SESSION_ID": "12345678-x"}, home, sess)
        check("desktop registry → alt email", r["email"] == "alt@example.com" and r["uuid"] == uB)
        check("desktop stamp 形", stamp(r) == "🖥 %s · desktop = alt@example.com · session 12345678" % r["host"])
        # 2) desktop で registry miss → email で埋めず warn
        r = identify({"CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                      "CLAUDE_CODE_HOST_SESSION_ID": "local_missing"}, home, sess)
        check("desktop miss → email None + warn", r["email"] is None and r["warn"] is not None)
        # 3) cli base
        r = identify({}, home, sess)
        check("cli base → base email", r["email"] == "cli-base@example.com" and r["surface"] == "cli/base")
        # 4) cli pinned dir
        r = identify({"CLAUDE_CONFIG_DIR": os.path.join(home, ".claude-alt")}, home, sess)
        check("cli pinned → alt email + label", r["email"] == "alt@example.com" and r["surface"] == "cli/alt")
        # 5) uuid_email_map が両 pair を持つ
        m = uuid_email_map(home)
        check("uuid map 2 entries", m == {uA: "cli-base@example.com", uB: "alt@example.com"})

        # 6) race: registry file が 0.4 秒後に現れる → --wait で解決 (2026-09-11 の未同定 18/20 の再現)
        late = os.path.join(sess, uB, org, "local_late.json")
        threading.Timer(0.4, lambda: open(late, "w").write("{}")).start()
        env_late = {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                    "CLAUDE_CODE_HOST_SESSION_ID": "local_late"}
        r0 = identify(env_late, home, sess, wait=0)
        check("race: wait 0 では未同定 (= 旧挙動)", r0["uuid"] is None)
        r = identify(env_late, home, sess, wait=3)
        check("race: --wait で遅れて現れた registry を拾う", r["email"] == "alt@example.com")
        # 7) wait しても現れない → 期限で打ち切って未同定 (嘘はつかない)
        t0 = time.monotonic()
        r = identify({"CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                      "CLAUDE_CODE_HOST_SESSION_ID": "local_never"}, home, sess, wait=0.3)
        check("wait 期限で未同定に fail-open", r["uuid"] is None and time.monotonic() - t0 >= 0.3)

        # 8) cmdline fallback: path の空白 (Application Support) を跨いで読む
        cmd = ("/x/claude --model m --plugin-dir /opt/app/Library/Application Support/Claude/"
               f"skills-plugin/{org}/{uB} --verbose")
        check("cmdline fallback は空白入り path を読む", account_from_cmdline(cmd) == uB)
        check("cmdline に --plugin-dir が無ければ None (= 現行 build)", account_from_cmdline("/x/claude --verbose") is None)
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def _wait_arg(argv):
    if "--wait" not in argv:
        return 0.0
    i = argv.index("--wait")
    try:
        return max(0.0, min(float(argv[i + 1]), 30.0))
    except (IndexError, ValueError):
        return 0.0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    try:
        r = identify(wait=_wait_arg(argv))
    except Exception as e:  # fail-open: 同定不能でも session を止めない
        print(f"🖥 whoami 失敗 ({e}) — account 未同定。 userEmail で埋めるな")
        return 0
    if '--session-id' in argv:
        print(os.environ.get('CLAUDE_CODE_SESSION_ID') or 'unknown'); return 0

    if "--who" in argv:  # hook 用: surface = account の部分のみ (sid は hook 側が持つ)
        print(who(r))
        return 0
    print(stamp(r))
    if "--stamp" not in argv:
        if r["source"]:
            print(f"source: {r['source']}")
        if r["warn"]:
            print(f"⚠️ {r['warn']}")
        print("⚠️ harness 注入 userEmail / ~/.claude.json は CLI 認証層を映す"
              " — desktop session の自己同定に使わない"
              " (SoT: conventions/multi-account-machine-surface.md §典型的な破れかた)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
