#!/usr/bin/env python3
"""check-dismiss-replies.py — card の取り下げ (dismiss_task) の返事の文が、 desktop app の版が変わっても、 返事を読み分ける 2 か所 (scripts/lib/pending_cards.py の点呼・scripts/lib/spawn_dedupe.py の二重起動の guard) に当たるかを、 app 本体の返事の表で確かめる

なぜ:
  dismiss_task の返事は app 本体の表 (`{dismissed:…, already_started:…, …}[outcome]`) の英文で、 文は app の版で変わる。
  読み分けは文の形で読むので、 版が変わると黙って外れ、 取り下げた card を点呼し続けたり、 同じ依頼の card の作り直しを
  止め続けたりした (実測 = 10 日で 3 回、 2 か所が別々に外れた回も同時に外れた回もある)。 版が変わったら、 表の各文を
  2 か所の読み分けの code にそのまま通して、 期待どおりに分かれるかを先に見る。 表の鍵 (dismissed など) は機械の値で、
  文より変わりにくい。 結果に付く構造化した値 (did / not_done / no_change) の対応も同じ表の隣にあるので一緒に見る
  (pending_cards.py はこの値を先に読む)。 正本 = conventions/multi-session-coordination.md#pending-card-rollcall。

動作:
  - app の版 = Info.plist の CFBundleShortVersionString。 表 = app.asar の main process の chunk のうち
    `dismissBackgroundTaskSuggestionById(` の後の `{dismissed:` から `}[` まで (読み方 = scripts/claude-app-bundle.py、
    conventions/claude-app-bundle-reading.md)。
  - 各文の `${n}` に試しの task id を入れ、 `${名}` は同じ chunk の `名="…"`、 `${名(n)}` は `function 名(e){return`…`}`
    から組む。 組めない文は「確かめられない」 (通ったことにしない)。
  - 読み分け = pending_cards.dismiss_kind(文) と、 spawn_dedupe.post_dismiss (台帳の置き場を一時 dir に差し替えて回し、
    台帳に書かれた状態を読む = 本物の code の道)。 鍵ごとの期待 = EXPECT。 知らない鍵・期待と違う文・表が無い・
    構造化した値の対応が見当たらない → problems。
  - 結果は state (既定 ~/.claude/state/dismiss-replies-check.json) に版・読み分けの file の sha256 と一緒に書く。
使い方:
  check-dismiss-replies.py               今の app で確かめる (rc 0 = 当たる / 1 = 外れ・確かめられない / 2 = app が無い)
  check-dismiss-replies.py --if-changed  前に確かめた版と読み分けの file が同じなら何もしない (点呼の Stop hook が背景で呼ぶ)
  check-dismiss-replies.py --status      前の結果が外れなら 1 行 (digest の ⚙️ の段が読む)。 当たり・未確認なら何も出さない
  check-dismiss-replies.py --selftest
env: CLAUDE_APP (app の path、 既定 /Applications/Claude.app) / DISMISS_REPLIES_STATE (state file の path)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
APP = os.environ.get("CLAUDE_APP") or "/Applications/Claude.app"
STATE = os.environ.get("DISMISS_REPLIES_STATE") or os.path.expanduser("~/.claude/state/dismiss-replies-check.json")
READERS = (os.path.join(HERE, "lib", "pending_cards.py"), os.path.join(HERE, "lib", "spawn_dedupe.py"))
TID = "task_0a1b2c3d"
# 鍵 → (pending_cards.dismiss_kind, spawn_dedupe の台帳の状態 〔None = 台帳を変えない〕)
EXPECT = {
    "dismissed": ("withdrawn", "withdrawn"),
    "already_started": ("started", "started"),
    "spawn_in_flight": ("started", "started"),
    "already_dismissed": ("closed", "dismissed"),
    "expired": ("expired", "dismissed"),
    "not_found": ("closed", "dismissed"),
    "edited": ("edited", "edited"),
    "session_not_found": ("", None),
}
ANCHOR = b"dismissBackgroundTaskSuggestionById("


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def app_version(app: str = APP) -> str:
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            return str(plistlib.load(f).get("CFBundleShortVersionString") or "")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return ""


def readers_digest() -> str:
    h = hashlib.sha256()
    for p in READERS:
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"-")
    return h.hexdigest()


def find_source(app: str = APP) -> str | None:
    """表を持つ chunk の文字列 (無ければ None)。"""
    cab = _load("claude_app_bundle", os.path.join(HERE, "claude-app-bundle.py"))
    for _name, data in cab.grep_sources("asar", app, None):
        b = bytes(data)
        i = b.find(ANCHOR)
        if i >= 0 and b.find(b"{dismissed:`", i, i + 6000) >= 0:
            return b.decode("utf-8", "replace")
    return None


def _unescape(s: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s).replace("\\`", "`")


def parse_table(src: str) -> tuple[dict[str, str], str, str]:
    """(鍵 → 試しの id を入れた文 〔組めない文は "" 〕, 表の後の構造化した値の式, 問題)。"""
    i = src.find(ANCHOR.decode())
    j = src.find("{dismissed:`", i if i >= 0 else 0)
    if j < 0:
        return {}, "", "返事の表が見つからない"
    k = src.find("}[", j)
    body = src[j + 1:k]
    out: dict[str, str] = {}
    for m in re.finditer(r"(\w+):`((?:[^`\\]|\\.)*)`", body):
        key, tpl = m.group(1), _unescape(m.group(2))

        def sub(mm, src=src):
            expr = mm.group(1)
            if expr == "n":
                return TID
            call = re.fullmatch(r"(\w+)\(n\)", expr)
            if call:
                d = re.search(r"function %s\((\w+)\)\{return`((?:[^`\\]|\\.)*)`" % re.escape(call.group(1)), src)
                if not d:
                    raise LookupError(expr)
                return _unescape(d.group(2)).replace("${%s}" % d.group(1), TID)
            d = re.search(r"(?<![\w$.])%s=(?:\"([^\"]*)\"|`([^`]*)`)" % re.escape(expr), src)
            if not d:
                raise LookupError(expr)
            return d.group(1) if d.group(1) is not None else d.group(2)

        try:
            out[key] = re.sub(r"\$\{([^}]*)\}", sub, tpl)
        except LookupError:
            out[key] = ""
    tail = src[k:k + 600]
    om = re.search(r"outcome:([^}]*)\}", tail)
    return out, (om.group(1) if om else ""), ""


def outcome_problem(expr: str) -> str:
    """構造化した値の対応 (pending_cards.STAMP_KINDS が前提にする形) が見当たらなければ問題の文。"""
    need = ('"dismissed"?"did"', '"already_started"', '"spawn_in_flight"?"not_done"', '"no_change"')
    miss = [x for x in need if x not in expr]
    return ("構造化した値 (did / not_done / no_change) の対応が見当たらない: " + ", ".join(miss)) if miss else ""


def classify(texts: dict[str, str]) -> list[str]:
    """各文を 2 か所の読み分けに通し、 期待と違うものを問題の文にして返す。"""
    pc = _load("pending_cards_chk", READERS[0])
    sd = _load("spawn_dedupe_chk", READERS[1])
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        sd.STATE_DIR = tmp
        for key, text in texts.items():
            if key not in EXPECT:
                problems.append(f"知らない返事の鍵 {key} (文の頭: {text[:60]!r})")
                continue
            if not text:
                problems.append(f"{key} の文を組めない (表の中の値・関数を読めない) = 確かめられない")
                continue
            want_pc, want_sd = EXPECT[key]
            got_pc = pc.dismiss_kind(text)
            sid = "check-" + key
            sd.post_dismiss({"session_id": sid, "tool_input": {"task_id": TID}, "tool_response": text})
            got_sd = next((e.get("state") for e in sd.load_ledger(sid) if e.get("task_id") == TID), None)
            if got_pc != want_pc:
                problems.append(f"{key}: 点呼 (pending_cards) の読み分け = {got_pc or '当たらない'} (期待 {want_pc or '当たらない'})")
            if got_sd != want_sd:
                problems.append(f"{key}: 二重起動の guard (spawn_dedupe) の読み分け = {got_sd or '台帳を変えない'}"
                                f" (期待 {want_sd or '台帳を変えない'})")
    return problems


def check(app: str = APP, src: str | None = None) -> dict:
    ver = app_version(app)
    problems: list[str] = []
    if src is None:
        src = find_source(app) if ver else None
    if src is None:
        problems.append("返事の表を持つ chunk が app 本体に見つからない" if ver else f"app が無い ({app})")
    else:
        texts, expr, why = parse_table(src)
        if why:
            problems.append(why)
        else:
            problems += classify(texts)
            p = outcome_problem(expr)
            if p:
                problems.append(p)
    return {"app": ver, "readers": readers_digest(), "ok": not problems, "problems": problems,
            "checked": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def load_state(path: str = STATE) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(d: dict, path: str = STATE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def needs_check(app: str = APP, path: str = STATE) -> bool:
    """前に確かめた版・読み分けの file と今が違えば True (点呼の Stop hook が毎 turn 呼ぶ = Info.plist と 2 file を読むだけ)。"""
    st = load_state(path)
    ver = app_version(app)
    return bool(ver) and (st.get("app") != ver or st.get("readers") != readers_digest())


def take_lock(path: str, stale: float = 600) -> bool:
    """O_EXCL で lock を取る。 取れなければ False (10 分より古い lock は落ちた run の残り = 取り直す)。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) < stale:
                    return False
                os.remove(path)
            except OSError:
                return False
    return False


def status_line(app: str = APP, path: str = STATE) -> str:
    st = load_state(path)
    if not st or st.get("ok") or st.get("app") != app_version(app):
        return ""
    # 行頭は通知の見張りが拾う印 (🚨 🔴 ⚠️ ❗ 🔥) にしない = digest の model 向けの行
    return (f"🃏 app {st.get('app')} の card の取り下げの返事が読み分けに当たらない ({'; '.join(st.get('problems') or [])[:300]})"
            f" → 直す所 = claude-config/scripts/lib/pending_cards.py・spawn_dedupe.py (確かめ = python3 {os.path.realpath(__file__)})")


def selftest() -> int:
    fails = []

    def ok(label, cond):
        print(("PASS " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    table = ('x.dismissBackgroundTaskSuggestionById(i.sessionId,n,a),l={dismissed:`Task ${n} withdrawn \\u2014 the chip is no'
             ' longer shown to the user. Continue your current work.`,already_started:`Task ${n} is no longer pending, so there'
             ' is nothing to withdraw: ${ub}. Nothing was changed.`,already_dismissed:`Task ${n} had already left the queue'
             ' (dismissed earlier, or displaced by newer suggestions); any copy kept for later is being withdrawn too. Do not'
             ' re-flag it.`,expired:`Task ${n} already expired unstarted, so it is no longer shown; any copy kept for later is'
             ' being withdrawn too. Do not re-propose it.`,spawn_in_flight:`Task ${n} is being started right now \\u2014 it'
             " can't be withdrawn while the spawn is in flight. Nothing was changed.`,edited:`Not withdrawn: ${cb(n)}`,"
             'not_found:`No pending task with id ${n} \\u2014 possible causes include it never being queued. Do not re-flag'
             ' it.`,session_not_found:`Session not found \\u2014 cannot look up task ${n}.`}[s];return t.sQ(l,{outcome:'
             's==="dismissed"?"did":s==="already_started"||s==="spawn_in_flight"?"not_done":await c?null:"no_change"})')
    helpers = ('ub="it was started in its own session";function cb(e){return`the user edited the message of ${e}, so only its'
               ' card starts it, with what they wrote.`}')
    src = helpers + table
    texts, expr, why = parse_table(src)
    ok("表の 8 つの鍵を読む", set(texts) == set(EXPECT) and not why)
    ok("${n}・${ub}・${cb(n)} を組む", TID in texts["dismissed"] and "own session" in texts["already_started"]
       and "edited the message of " + TID in texts["edited"] and "—" in texts["dismissed"])
    r = check(app="/nonexistent", src=src)
    ok("今の読み分けで 8 つとも当たる", r["ok"] and r["problems"] == [])
    r = check(app="/nonexistent", src=src.replace("had already left the queue", "has left the line"))
    ok("閉じた返事の文が変わると 2 か所とも外れを出す",
       not r["ok"] and sum("already_dismissed" in p for p in r["problems"]) == 2)
    r = check(app="/nonexistent", src=src.replace(",session_not_found:", ",parked:`Task ${n} parked.`,session_not_found:"))
    ok("知らない鍵を出す", any("知らない返事の鍵 parked" in p for p in r["problems"]))
    r = check(app="/nonexistent", src=src.replace("function cb(e)", "function cz(e)"))
    ok("組めない文は確かめられないと出す (通ったことにしない)", any("edited の文を組めない" in p for p in r["problems"]))
    r = check(app="/nonexistent", src=src.replace('"not_done"', '"pending"'))
    ok("構造化した値の対応が変わると出す", any("構造化した値" in p for p in r["problems"]))
    r = check(app="/nonexistent", src="nothing here")
    ok("表が無ければ出す", not r["ok"] and any("見つからない" in p for p in r["problems"]))
    with tempfile.TemporaryDirectory() as tmp:
        sp = os.path.join(tmp, "s.json")
        fake = os.path.join(tmp, "Fake.app")
        os.makedirs(os.path.join(fake, "Contents"))
        with open(os.path.join(fake, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "9.1.0"}, f)
        ok("app が無ければ needs_check は False", not needs_check(app="/nonexistent", path=sp))
        ok("確かめた記録が無ければ needs_check は True", needs_check(app=fake, path=sp))
        save_state({"app": "9.1.0", "readers": readers_digest(), "ok": False, "problems": ["x"]}, sp)
        ok("同じ版・同じ読み分けなら needs_check は False", not needs_check(app=fake, path=sp))
        ok("今の版の外れは status に 1 行", status_line(app=fake, path=sp).startswith("🃏 app 9.1.0"))
        save_state({"app": "9.0.0", "readers": readers_digest(), "ok": False, "problems": ["x"]}, sp)
        ok("版が変われば needs_check は True、 前の版の外れは status に出さない",
           needs_check(app=fake, path=sp) and status_line(app=fake, path=sp) == "")
        save_state({"app": "9.1.0", "readers": "other", "ok": True, "problems": []}, sp)
        ok("読み分けの file が変われば needs_check は True", needs_check(app=fake, path=sp))
        lk = os.path.join(tmp, "x.lock")
        ok("lock は 1 本だけ取れる", take_lock(lk) and not take_lock(lk))
        os.utime(lk, (time.time() - 3600, time.time() - 3600))
        ok("古い lock は取り直す", take_lock(lk))
    print(f"selftest: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--if-changed", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.status:
        line = status_line()
        if line:
            print(line)
        return 0
    if a.if_changed and not needs_check():
        return 0
    if not app_version():
        print(f"app が無い ({APP})", file=sys.stderr)
        return 2
    lock = STATE + ".lock"
    if not take_lock(lock):   # 並列の session の Stop が同時に起こした = 1 本だけ回す (退く判定は try の外)
        return 0
    try:
        r = check()
        save_state(r)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    print(f"app {r['app']}: " + ("8 つの返事とも 2 か所の読み分けに当たる" if r["ok"] else "外れ:\n  " + "\n  ".join(r["problems"])))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
