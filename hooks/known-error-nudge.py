#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""known-error-nudge.py — PostToolUse / PostToolUseFailure(Bash・archive_session): 出力・エラー文に既知の壊れ方のエラー文が出たら、 その壊れ方を書いた規約の節を Claude に知らせる (台帳 = hooks/known-errors.json)

なぜ:
  壊れ方を規約に書いても、 次にそのエラーに当たった session がその規約を引くとは限らない。 エラー文は原因と
  違うことを言うことが多く (例: 正しい UTF-8 の file に「Non-UTF-8 code」)、 引かない session は推測で原因を探し、
  「原因不明」 で終える。 実測: 規約に記録済みの壊れ方に別の session が当たり、 規約を引かないまま「原因を
  確かめていない」 と報告した。 規約を引く判断を人の記憶に頼らず、 エラーが出た瞬間に節を出す。
  一般則 = conventions/debugging-discipline.md#known-error-lookup。

動作 (非 block):
  - PostToolUse は tool_response の stdout / stderr、 PostToolUseFailure は error の文字列を見る
    (Bash が終了値 0 以外で終わると PostToolUse は呼ばれず PostToolUseFailure が呼ばれる)。
  - desktop app の archive_session も見る (結果の content の文。 断りの文がどの原因かを言わない = 台帳の行が読み方の
    節を出す。 matcher = hooks/settings-entries.json の `Bash|mcp__.*__archive_session`)。
  - 台帳の各 entry の match が出たら (部分一致、 "regex": true なら正規表現)、 additionalContext に
    「既知の壊れ方: 〈match〉 → 〈doc〉 (〈hint〉)」 を返す。 原因を推測する前にその節を読むよう促す。
  - 同じ entry は 1 session に 1 回だけ (状態 = ~/.claude/state/known-error-nudge/<session>.json、 14 日で掃除)。
  - 台帳は hook の実体 (symlink の先) と同じ dir の known-errors.json。 読めなければ何もしない (fail-open)。

台帳に足す:
  規約に壊れ方を書いたら、 そのエラー文の変わらない部分を 1 件足す。 `--check` が doc と anchor の実在と、
  match の文字列が doc の本文にあることを確かめる (= 規約に書いていないエラー文を台帳だけに置かない)。

usage:
  (hook) stdin に hook の JSON
  python3 hooks/known-error-nudge.py --check     # 台帳の点検 (問題があれば exit 1)
env: KNOWN_ERROR_NUDGE_STATE_DIR (状態の dir)、 KNOWN_ERROR_NUDGE_REGISTRY (台帳の path、 test 用)
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
REGISTRY = os.environ.get("KNOWN_ERROR_NUDGE_REGISTRY") or os.path.join(HERE, "known-errors.json")
STATE_DIR = os.environ.get("KNOWN_ERROR_NUDGE_STATE_DIR") or os.path.expanduser("~/.claude/state/known-error-nudge")
KEEP_DAYS = 14
MAX_TEXT = 200000  # 長い出力の先頭だけを見る (エラー文は普通は先頭か末尾にある = 末尾も足す)


def load_entries(path=REGISTRY):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [e for e in data.get("entries", []) if isinstance(e, dict) and e.get("match") and e.get("doc")]


def hit(entry, text):
    m = entry["match"]
    if entry.get("regex"):
        try:
            return re.search(m, text) is not None
        except re.error:
            return False
    return m in text


def tool_text(payload):
    """event に応じて、 見る文字列を返す。"""
    if payload.get("hook_event_name") == "PostToolUseFailure":
        return str(payload.get("error") or "")
    resp = payload.get("tool_response")
    if resp is None:
        resp = payload.get("tool_result")
    if isinstance(resp, dict) and ("stdout" in resp or "stderr" in resp):
        return "{}\n{}".format(resp.get("stdout") or "", resp.get("stderr") or "")
    if isinstance(resp, (dict, list)):  # an MCP tool's result (content blocks): the text is inside
        return json.dumps(resp, ensure_ascii=False)
    return str(resp or "")


def watched_tool(name):
    """Bash, and the desktop app's archive_session (its refusal text names no cause = the ledger points to the reading)."""
    return name == "Bash" or (name.startswith("mcp__") and name.endswith("__archive_session"))


def clip(text):
    if len(text) <= MAX_TEXT:
        return text
    half = MAX_TEXT // 2
    return text[:half] + "\n" + text[-half:]


def state_path(session):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session or "nosession")
    return os.path.join(STATE_DIR, safe + ".json")


def load_seen(session):
    try:
        with open(state_path(session), encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(session, seen):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(state_path(session), "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f, ensure_ascii=False)
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            if name.endswith(".json") and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        pass


def message(found):
    lines = ["🔎 既知の壊れ方 (規約に書いてある) — 原因を推測する前に、 その節を読む:"]
    for e in found:
        line = "  - 「{}」 → claude-config/{}".format(e["match"], e["doc"])
        if e.get("hint"):
            line += " ({})".format(e["hint"])
        lines.append(line)
    lines.append("  (台帳 = claude-config/hooks/known-errors.json。 同じ壊れ方はこの session では再び知らせない)")
    return "\n".join(lines)


def run_hook():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if not watched_tool(str(payload.get("tool_name") or "")):
        return 0
    event = payload.get("hook_event_name") or "PostToolUse"
    if event not in ("PostToolUse", "PostToolUseFailure"):
        return 0
    text = clip(tool_text(payload))
    if not text.strip():
        return 0
    try:
        entries = load_entries()
    except Exception:
        return 0
    session = str(payload.get("session_id") or "")
    seen = load_seen(session)
    found = [e for e in entries if e["match"] not in seen and hit(e, text)]
    if not found:
        return 0
    seen.update(e["match"] for e in found)
    save_seen(session, seen)
    out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message(found)}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


def check():
    """台帳の点検: doc の実在・anchor の実在・match が doc の本文にあること・regex が正しいこと。"""
    try:
        entries = load_entries()
    except Exception as ex:  # noqa: BLE001
        print("known-errors: 台帳を読めない: {}".format(ex))
        return 1
    bad = 0
    for e in entries:
        path, _, anchor = e["doc"].partition("#")
        full = os.path.join(REPO, path)
        if not os.path.isfile(full):
            print("❌ doc が無い: {} ({})".format(e["doc"], e["match"]))
            bad += 1
            continue
        with open(full, encoding="utf-8") as f:
            body = f.read()
        if anchor and 'id="{}"'.format(anchor) not in body:
            print("❌ anchor が無い: {}".format(e["doc"]))
            bad += 1
        if e.get("regex"):
            try:
                re.compile(e["match"])
            except re.error as ex:
                print("❌ 正規表現が壊れている: {} ({})".format(e["match"], ex))
                bad += 1
        elif e["match"] not in body:
            print("❌ match の文字列が doc の本文に無い (規約に書いてから台帳へ): 「{}」 → {}".format(e["match"], e["doc"]))
            bad += 1
    print("known-errors: {} 件、 問題 {} 件".format(len(entries), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    try:
        sys.exit(run_hook())
    except Exception:
        sys.exit(0)
