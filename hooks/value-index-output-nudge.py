#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""value-index-output-nudge.py — PostToolUse: tool の出力に、 個人層の暗号化した値の索引の値 (電話・口座・生年月日・住所) が出たら、 その種類だけを Claude に知らせる (値は出さない)

なぜ:
  暗号化した値は手元では復号されているので、 確認の出力 (警告の見本・PDF の頁の頭・画像の切り取り・値の file の形の確かめ) に
  そのまま出て、 会話の記録に残る (実測: 2 週間で 12 の session の 17 の出力)。 記録は消せない = この網は「出た瞬間に気づいて
  本人に伝え、 確かめ方を形だけを出す形に替える」 ためのもの。 規則 = conventions/confidential-repo-boundary.md#decrypted-echo。

動作 (非 block):
  - 個人層の value-index.txt (層1 scripts/check-value-index.py の --config と同じ設定) の索引で、 tool の出力の行を照合する
    (照合の正本 = check-value-index.py の Matcher)。 見るのは Bash の stdout / stderr、 Read・Grep・MCP の結果の文字列。
  - 当たったら additionalContext に、 当たった索引の行の説明 (例「— 本人の携帯」) だけを出す。 値・行・file 名は出さない。
  - 同じ説明は 1 session に 1 回だけ (状態 = ~/.claude/state/value-index-output/<session>.json、 14 日で掃除)。
  - 個人層・設定・索引が無い / 読めない (鍵の無い機械) なら何もしない (fail-open)。
env: VALUE_INDEX_OUTPUT_STATE_DIR (状態の dir)、 CLAUDE_PERSONAL_LAYER (個人層、 none で無効)、
     VALUE_INDEX_ENGINE (engine の path、 test 用)
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.environ.get("VALUE_INDEX_ENGINE") or os.path.join(REPO, "scripts", "check-value-index.py")
STATE_DIR = os.environ.get("VALUE_INDEX_OUTPUT_STATE_DIR") or os.path.expanduser("~/.claude/state/value-index-output")
KEEP_DAYS = 14
MAX_TEXT = 400000


def personal_layer():
    """lib/find-personal-layer.sh と同じ規則 (env が優先、 無ければ作業ルートの直下で印のある dir が 1 つだけのとき)。"""
    env = os.environ.get("CLAUDE_PERSONAL_LAYER")
    if env == "none":
        return None
    cands = [env] if env else [os.path.join(os.path.dirname(REPO), d) for d in sorted(os.listdir(os.path.dirname(REPO)))]
    found = [d for d in cands if d and os.path.isfile(os.path.join(d, ".claude-personal-layer"))
             and os.path.isfile(os.path.join(d, "CLAUDE.md"))]
    return found[0] if len(found) == 1 else None


def load_engine():
    spec = importlib.util.spec_from_file_location("check_value_index", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_value_index"] = mod
    spec.loader.exec_module(mod)
    return mod


def tool_text(payload):
    resp = payload.get("tool_response")
    if resp is None:
        resp = payload.get("tool_result")
    if isinstance(resp, dict):
        if "stdout" in resp or "stderr" in resp:
            return "{}\n{}".format(resp.get("stdout") or "", resp.get("stderr") or "")
        return json.dumps(resp, ensure_ascii=False)
    if isinstance(resp, list):
        return "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in resp)
    return str(resp or "")


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
        tmp = state_path(session) + ".{}.tmp".format(os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f, ensure_ascii=False)
        os.replace(tmp, state_path(session))
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            if name.endswith(".json") and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except Exception:
        pass


def message(labels):
    return "\n".join([
        "🔐 直前の tool の出力に、 暗号化した値の索引の値が出た (種類: {})。 値はこの知らせには書かない。".format(" / ".join(labels)),
        "  出力は会話の記録に残った (消せない)。 意図して扱った値でなければ、 本人に 1 行で伝え、 個人層の漏洩の記録に件数と種類を残す。",
        "  以後の確かめは形だけ (行の長さ・字の種類・件数) を出す形に替える。 本人の書類に本人の値を書くなど意図して扱った値なら、 そう伝えて続ける。",
        "  正本 = claude-config/conventions/confidential-repo-boundary.md#decrypted-echo (同じ種類はこの session では再び知らせない)",
    ])


def run_hook():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if (payload.get("hook_event_name") or "PostToolUse") != "PostToolUse":
        return 0
    text = tool_text(payload)
    if not text.strip():
        return 0
    layer = personal_layer()
    config = os.path.join(layer, "value-index.txt") if layer else None
    if not config or not os.path.isfile(config):
        return 0
    eng = load_engine()
    from pathlib import Path
    entries, _unreadable = eng.read_index(Path(config))
    if not entries:
        return 0
    matcher = eng.Matcher(entries)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT // 2] + "\n" + text[-MAX_TEXT // 2:]
    labels = []
    for line in text.splitlines():
        for lb in matcher.labels(line):
            if lb not in labels:
                labels.append(lb)
    if not labels:
        return 0
    session = str(payload.get("session_id") or "")
    seen = load_seen(session)
    new = [lb for lb in labels if lb not in seen]
    if not new:
        return 0
    save_seen(session, seen | set(new))
    out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message(new)}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run_hook())
    except Exception:
        sys.exit(0)
