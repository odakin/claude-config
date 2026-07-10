#!/usr/bin/env bash
# public-leak-guard.test.sh — public-leak-guard.sh の self-test (hermetic)
#
# 正本: claude-config/hooks/public-leak-guard.test.sh
# 実行: bash hooks/public-leak-guard.test.sh (run-all-checks.sh が自動発見)
#
# 象限: ask (Tier A hit) / pass (clean・marker 無し・非 repo)。
# 本 hook に deny 象限は無い (設計上 ask のみ)。
#
# fixture 設計:
#   - mktemp 下に fake repo (mkdir .git + .claude/public-repo.marker) を作る。
#     hook は `.git` の存在と marker file しか見ないので git 実体は不要。
#   - Tier A に hit する fixture 値 (email / abs path / IPv4 / token / discord
#     mention) は **文字列連結で実行時に合成** する。 test source に完全形の
#     literal を書くと、 この test file 自身が public-leak-guard / pre-commit
#     Tier A gate に hit してしまう (= self-scan 回避、 CLAUDE.md 安全規則
#     「Test file の literal 禁止」 の構造版)。 値はすべて架空
#     (example.com / TEST-NET-3 / 合成 token)。

set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/public-leak-guard.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }

pass=0; fail=0; results=()

BASE="$(mktemp -d)"
trap 'rm -rf "$BASE"' EXIT

# fake public repo (marker あり) / fake private repo (marker なし) / 非 repo
PUB="$BASE/pubrepo"
PRIV="$BASE/privrepo"
mkdir -p "$PUB/.git" "$PUB/.claude" "$PRIV/.git" "$BASE/norepo"
touch "$PUB/.claude/public-repo.marker"

# ---- Tier A fixture 値 (連結合成、 冒頭コメント参照) ----
AT="@"
EMAIL="leak.tester${AT}example.com"
ABS_PATH="/Use""rs/leaktester"
PUB_IP="203.0.""113.7"                    # TEST-NET-3 (非 allowlist)
PRIV_IP="192.168.""1.1"                   # RFC1918 (allowlist)
TOKEN="ghp_$(printf 'a%.0s' $(seq 1 32))" # ghp_ + 32 chars
DISCORD="<""${AT}123456789012345678>"     # <@ + snowflake 18 桁

run_hook() { # <json>
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null || true
}

decision() { # <json input> -> "ask" or ""
  run_hook "$1" | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null
}

assert() { # <label> <expect: ask|pass> <json>
  local label="$1" expect="$2" json="$3" got
  got="$(decision "$json")"
  [ -z "$got" ] && got="pass"
  if [ "$got" = "$expect" ]; then
    pass=$((pass+1)); results+=("✅ $label")
  else
    fail=$((fail+1)); results+=("❌ $label (expect=$expect got=$got)")
  fi
}

mk_write() { # <file_path> <content> -> Write tool JSON
  jq -nc --arg p "$1" --arg c "$2" '{tool_name:"Write",tool_input:{file_path:$p,content:$c}}'
}
mk_edit() { # <file_path> <new_string> -> Edit tool JSON
  jq -nc --arg p "$1" --arg s "$2" '{tool_name:"Edit",tool_input:{file_path:$p,new_string:$s}}'
}
mk_multiedit() { # <file_path> <new_string> -> MultiEdit tool JSON
  jq -nc --arg p "$1" --arg s "$2" '{tool_name:"MultiEdit",tool_input:{file_path:$p,edits:[{old_string:"x",new_string:$s}]}}'
}

echo "=== ask 象限 (Tier A hit in public repo) ==="
assert "A1: email (Write)"            ask  "$(mk_write "$PUB/doc.md" "contact: $EMAIL")"
assert "A2: abs path (Write)"         ask  "$(mk_write "$PUB/doc.md" "path is $ABS_PATH/file")"
assert "A3: public IPv4 (Write)"      ask  "$(mk_write "$PUB/doc.md" "host $PUB_IP responds")"
assert "A4: token prefix (Write)"     ask  "$(mk_write "$PUB/doc.md" "secret=$TOKEN")"
assert "A5: discord mention (Write)"  ask  "$(mk_write "$PUB/doc.md" "notify $DISCORD ok")"
assert "A6: email (Edit new_string)"  ask  "$(mk_edit "$PUB/doc.md" "mail me: $EMAIL")"
assert "A7: email (MultiEdit edits)"  ask  "$(mk_multiedit "$PUB/doc.md" "cc: $EMAIL")"

echo "=== pass 象限 ==="
assert "P1: clean content"            pass "$(mk_write "$PUB/doc.md" "nothing sensitive here")"
assert "P2: allowlist email"          pass "$(mk_write "$PUB/doc.md" "noreply${AT}anthropic.com")"
assert "P3: RFC1918 IPv4"             pass "$(mk_write "$PUB/doc.md" "lan: $PRIV_IP")"
assert "P4: token 例示 (30 字未満)"    pass "$(mk_write "$PUB/doc.md" "e.g. ghp_shortexample")"
assert "P5: marker 無し repo は素通し" pass "$(mk_write "$PRIV/doc.md" "contact: $EMAIL")"
assert "P6: 非 git path は素通し"      pass "$(mk_write "$BASE/norepo/doc.md" "contact: $EMAIL")"
assert "P7: file_path 無し input"      pass "$(jq -nc '{tool_name:"Write",tool_input:{}}')"
assert "P8: 空 stdin"                  pass ""

echo ""
echo "=== 結果 ==="
for r in "${results[@]}"; do echo "  $r"; done
echo ""
echo "pass: $pass / fail: $fail"
exit "$fail"
