#!/usr/bin/env bash
# owner-window-notice.test.sh — owner-window-notice.sh の検査 (user の対話の窓への SendMessage・掲示板の note で鳴る / 同じ宛先は 1 時間に 1 回 / 止めない / board.py の無い Bash は engine を起動しない / 壊れた入力・engine の不在で黙る)
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/owner-window-notice.sh"
ENGINE="${OWNER_WINDOW_NOTICE_ENGINE:-$HERE/../scripts/owner-window-notice.py}"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
[ -f "$ENGINE" ] || { echo "FAIL: engine not found: $ENGINE (set OWNER_WINDOW_NOTICE_ENGINE)"; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); echo "✅ $1"; }
ng() { fail=$((fail+1)); echo "❌ $1"; }

# 架空の session 4 本: 本人が 20 分前に発言した窓 (reader) / 別 session の message だけの worker (helper) / 送り手 (conductor) /
# 起動文 (origin が human で入る最初の prompt) しか本人側の行が無い worker (launched)
W=aaaaaaaa-0000-4000-8000-000000000001; P=bbbbbbbb-0000-4000-8000-000000000002; S=dddddddd-0000-4000-8000-000000000004
L=eeeeeeee-0000-4000-8000-000000000005
python3 - "$TMP" "$W" "$P" "$S" "$L" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone
tmp, W, P, S, L = sys.argv[1:6]
now = time.time()
iso = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
proj = os.path.join(tmp, "projects", "-w"); sess = os.path.join(tmp, "sessions"); board = os.path.join(tmp, "board")
for d in (proj, sess, os.path.join(tmp, "desktop"), os.path.join(board, "events", "p", "t"), os.path.join(board, "scripts")):
    os.makedirs(d, exist_ok=True)
human = lambda t: {"type": "user", "timestamp": iso(t), "entrypoint": "claude-desktop", "origin": {"kind": "human"},
                   "message": {"role": "user", "content": "read and comment"}}
peer = lambda t: {"type": "user", "timestamp": iso(t), "entrypoint": "claude-desktop",
                  "message": {"role": "user", "content": "<cross-session-message from=\"local_x\">hi"}}
asst = lambda t: {"type": "assistant", "timestamp": iso(t), "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
for sid, lines in ((W, [human(now - 3000), asst(now - 2000), human(now - 1200), asst(now - 600)]),
                   (P, [peer(now - 300), asst(now - 100)]), (S, [asst(now - 10)]), (L, [human(now - 900), asst(now - 800)])):
    with open(os.path.join(proj, sid + ".jsonl"), "w") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines))
for i, (sid, name) in enumerate(((W, "reader"), (P, "helper"), (S, "conductor"), (L, "launched"))):
    with open(os.path.join(sess, f"{2000 + i}.json"), "w") as fh:
        json.dump({"sessionId": sid, "name": name, "pid": os.getppid(), "hostSessionId": f"local_{sid}", "cwd": "/w",
                   "messagingSocketPath": f"/tmp/owt/{2000 + i}.sock"}, fh)
open(os.path.join(board, "board.json"), "w").write("{}")
for name, ev in (("r1", {"kind": "request", "event_id": "20260101T000000Z-claude-aaaaaa", "created_at": "2026-01-01T00:00:00Z",
                         "actor": {"session_id": S}, "assignee": {"session_id": "role-p-reader"}}),
                 ("c1", {"kind": "claim", "event_id": "20260101T000100Z-claude-bbbbbb", "created_at": "2026-01-01T00:01:00Z",
                         "request_id": "20260101T000000Z-claude-aaaaaa",
                         "actor": {"session_id": "role-p-reader", "task": W[:8] + " (opus)"}})):
    with open(os.path.join(board, "events", "p", "t", name + ".json"), "w") as fh:
        json.dump(ev, fh)
PY
export CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_SESSIONS_DIR="$TMP/sessions" CLAUDE_DESKTOP_SESSIONS_DIR="$TMP/desktop"
export CLAUDE_PERSONAL_LAYER=none OWNER_WINDOW_NOTICE_ENGINE="$ENGINE" OWNER_WINDOW_NOTICE_STATE_DIR="$TMP/state"
run() { printf '%s' "$1" | bash "$HOOK"; }
ev() { python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "hook_event_name": "PreToolUse", "tool_name": sys.argv[2], "tool_input": json.loads(sys.argv[3])}))' "$S" "$1" "$2"; }

out="$(run "$(ev SendMessage '{"to": "reader", "message": "another agenda"}')")"
if printf '%s' "$out" | grep -q 'owner-driven-window-no-funnel' && printf '%s' "$out" | grep -q '"additionalContext"'; then
  ok "T1 本人が話している窓への SendMessage で鳴る (additionalContext)"
else ng "T1: ${out:-silent}"; fi
printf '%s' "$out" | grep -q 'permissionDecision' && ng "T2 permissionDecision を出した: $out" || ok "T2 止めない (permissionDecision を出さない)"

out="$(run "$(ev SendMessage '{"to": "uds:/tmp/owt/2000.sock", "message": "x"}')")"
[ -z "$out" ] && ok "T3 同じ宛先は 1 時間に 1 回 (宛先の書き方が違っても同じ session)" || ng "T3 鳴った: $out"

out="$(run "$(ev SendMessage '{"to": "helper", "message": "x"}')")"
[ -z "$out" ] && ok "T4 別 session の message しか無い worker では黙る" || ng "T4 鳴った: $out"

out="$(run "$(ev SendMessage '{"to": "launched", "message": "x"}')")"
[ -z "$out" ] && ok "T4b 起動文 (最初の prompt) しか本人側の行が無い worker では黙る" || ng "T4b 鳴った: $out"

export OWNER_WINDOW_NOTICE_STATE_DIR="$TMP/state2"
NOTE="python3 $TMP/board/scripts/board.py note --agent claude --session $S --request 20260101T000000Z-claude-aaaaaa --project p --policy ordinary --summary 'another agenda'"
out="$(run "$(ev Bash "$(python3 -c 'import json,sys; print(json.dumps({"command": sys.argv[1]}))' "$NOTE")")")"
printf '%s' "$out" | grep -q 'reader' && ok "T5 窓の役割に宛てた掲示板の note で鳴る (claim から session を引く)" || ng "T5: ${out:-silent}"

# board.py を含まない Bash は engine を起動しない (起動したら印を残す偽の engine で確かめる)
cat > "$TMP/fake-engine.py" <<'PY'
import os
open(os.environ["FAKE_MARK"], "w").write("ran")
PY
out="$(FAKE_MARK="$TMP/mark" OWNER_WINDOW_NOTICE_ENGINE="$TMP/fake-engine.py" run "$(ev Bash '{"command": "git status"}')")"
[ ! -e "$TMP/mark" ] && [ -z "$out" ] && ok "T6 board.py の無い Bash では engine を起動しない" || ng "T6 起動した"

out="$(run 'not json')"; rc=$?
[ -z "$out" ] && [ "$rc" = 0 ] && ok "T7 壊れた入力では黙って exit 0" || ng "T7 rc=$rc out=$out"

out="$(OWNER_WINDOW_NOTICE_ENGINE="$TMP/none.py" run "$(ev SendMessage '{"to": "reader", "message": "x"}')")"; rc=$?
[ -z "$out" ] && [ "$rc" = 0 ] && ok "T8 engine が無ければ黙って exit 0" || ng "T8 rc=$rc out=$out"

out="$(OWNER_WINDOW_NOTICE_DISABLE=1 OWNER_WINDOW_NOTICE_STATE_DIR="$TMP/state3" run "$(ev SendMessage '{"to": "reader", "message": "x"}')")"
[ -z "$out" ] && ok "T9 OWNER_WINDOW_NOTICE_DISABLE=1 で黙る" || ng "T9 鳴った: $out"

python3 "$ENGINE" --selftest >/dev/null && ok "T10 engine の --selftest が通る" || ng "T10 selftest が落ちた"

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
