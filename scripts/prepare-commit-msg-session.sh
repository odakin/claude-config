#!/usr/bin/env bash
# prepare-commit-msg-session.sh — commit に発生元 agent/session/model/effort の trailer block を付ける (並列 session の事後追跡)
#
# 正本: <claude-config>/scripts/prepare-commit-msg-session.sh
# 配置: install-session-trailer.sh が各 repo の .git/hooks/prepare-commit-msg に 1 行
#       stub を置き、 本 script を exec する (= 更新は本 script を編集するだけで全 repo
#       に波及。 install-public-commit-msg.sh と同 pattern)。
#
# 何をするか: commit message の trailer block に provenance 3 行を足すだけ。
#
#     Agent-Session: claude:<CLAUDE_CODE_SESSION_ID>
#     Agent-Session: codex:<Codex session id>
#     Agent-Model: <runtime model id|unknown>
#     Agent-Effort: <effective effort|unknown>
#
# 解く問題:
#   同一 working tree で複数の AI session が並行して commit すると、 author は全
#   commit で同一人物に潰れ、 「どの commit がどの session のものか」 が git から復元
#   できない。 staging window race (= 検証に空けた数分で他 session の `git commit` に
#   自分の hunk が吸われる、 conventions/multi-session-coordination.md#staging-window-race)
#   の事後追跡が、 transcript 漁りと散文の記憶しか残らなくなる。 trailer があれば
#
#       git log --format='%h %(trailers:key=Agent-Session,valueonly)'
#
#   で機械的に読める。 session id は transcript の file 名でもある
#   (~/.claude*/projects/<slug>/<session-id>.jsonl) ので commit → 会話の逆引きも通る。
#
# 何を書かないか (= 意図的な設計):
#   host / account / surface は書かない。 それらは session id から transcript を引けば
#   冒頭の自己同定 stamp に載っており、 commit に焼くと公開 repo で機器名 (しばしば人名
#   を含む) を晒す経路が 1 本増えるだけ。 公開面には具体値でなく属性で書く原則 =
#   conventions/multi-account-machine-surface.md I7。 この判断の結果、 public / private
#   の出し分けが不要になり全 repo で同一挙動になる (= 出し分けの設定ミスで漏れる、 という
#   事故の型そのものが消える)。
#
# 帰属の読み方 (= 誤読防止):
#   この trailer が記録するのは carrier (= どの経路を通って commit されたか) であって、
#   判断主体ではない。 内容を決めたのは通常 human である。 commit author を判断主体と
#   等値しない規律をそのまま適用すること = conventions/actor-attribution.md。
#
# no-op になる条件 (全て意図的):
#   - session source が未設定 → 人手 commit / 未対応 runtime 経路。
#   - 既に Agent-Session: または legacy の Claude-Session:/Codex-Session: trailer がある
#     → amend / rebase / cherry-pick で増殖させず、
#     message に運ばれた最初の session を保存する (冪等は git の --if-exists
#     doNothing に委ねる)。`git commit --amend -m` は message 全体を置換するため、Git が
#     元 commit id を hook に渡さない経路では amending session の新 block になる。
#   - agent namespace が [A-Za-z0-9._-]、session id が [A-Za-z0-9_-] 以外を含む
#     → message injection 拒否。
#   - git config agent.sessionTrailer = false → repo 単位の opt-out。
#     legacy の claude.sessionTrailer=false / codex.sessionTrailer=false も尊重する。
#
# session source の優先順:
#   1. CLAUDE_CONFIG_AGENT_SESSION=<agent>:<id> (明示・vendor-neutral)
#   2. CLAUDE_CODE_SESSION_ID               (Claude Code)
#   3. CODEX_SESSION_ID / CODEX_THREAD_ID   (Codex compatibility probe)
#
# Codex の stable public contract は lifecycle Hook input の session_id であり、上記
# CODEX_* shell env は公開契約ではない。Codex SessionStart adapter は公式 session_id を
# model context に渡し、必要時に 1 の明示値を git commit command へ付けられるようにする。
# CODEX_* は現行 local runtime での自動経路を保つ fail-open compatibility probe。
# model / effort は CLAUDE_CONFIG_AGENT_MODEL / CLAUDE_CONFIG_AGENT_EFFORT の明示値を
# 最優先し、Claude は machine-local cache を次に読む。Codex の優先順位・validation・
# cache・exact-session local fallback は session_provenance_cache.py が一括所有する。
# Claude effort は公式の Bash env CLAUDE_EFFORT から effective 値を取得する。
# 両方で取れなければ警告した上で literal `unknown` を書く。config default で
# 穴埋めせず、provenance の縮退をcommit停止と同一視しない。
#
# selftest: prepare-commit-msg-session.test.sh (run-all-checks.sh が自動発見)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MSG_FILE="${1:-}"
[ -n "$MSG_FILE" ] || exit 0
[ -f "$MSG_FILE" ] || exit 0
SOURCE_COMMIT="${3:-}"

# Message 自体が既に provenance を持つ通常 amend/rebase/cherry-pick はそのまま保つ。
if git interpret-trailers --parse "$MSG_FILE" 2>/dev/null \
        | grep -Eq '^(Agent-Session|Claude-Session|Codex-Session):[[:space:]]'; then
    exit 0
fi

# `git commit --amend -m ...` は旧 message を丸ごと置換する。prepare-commit-msg の
# 第 3 引数が元 commit を運ぶ場合は、そこから最初の carrier と metadata を復元する。
ORIGINAL_AGENT_SESSION=""
ORIGINAL_MODEL=""
ORIGINAL_EFFORT=""
LEGACY_KEY=""
LEGACY_VALUE=""
if [ -n "$SOURCE_COMMIT" ]; then
    ORIGINAL_TRAILERS="$(git show -s --format=%B "$SOURCE_COMMIT" 2>/dev/null \
        | git interpret-trailers --parse 2>/dev/null || true)"
    ORIGINAL_AGENT_SESSION="$(printf '%s\n' "$ORIGINAL_TRAILERS" | sed -n 's/^Agent-Session:[[:space:]]*//p' | sed -n '1p')"
    ORIGINAL_MODEL="$(printf '%s\n' "$ORIGINAL_TRAILERS" | sed -n 's/^Agent-Model:[[:space:]]*//p' | sed -n '1p')"
    ORIGINAL_EFFORT="$(printf '%s\n' "$ORIGINAL_TRAILERS" | sed -n 's/^Agent-Effort:[[:space:]]*//p' | sed -n '1p')"
    if [ -z "$ORIGINAL_AGENT_SESSION" ]; then
        for candidate in Claude-Session Codex-Session; do
            value="$(printf '%s\n' "$ORIGINAL_TRAILERS" | sed -n "s/^$candidate:[[:space:]]*//p" | sed -n '1p')"
            if [ -n "$value" ]; then
                LEGACY_KEY="$candidate"
                LEGACY_VALUE="$value"
                break
            fi
        done
    fi
fi

if [ -n "$LEGACY_KEY" ]; then
    case "$LEGACY_VALUE" in
        *[!A-Za-z0-9_-]*) exit 0 ;;
    esac
    git interpret-trailers --if-exists doNothing \
        --trailer "$LEGACY_KEY: $LEGACY_VALUE" --in-place "$MSG_FILE" 2>/dev/null || true
    exit 0
fi

SESSION="${ORIGINAL_AGENT_SESSION:-${CLAUDE_CONFIG_AGENT_SESSION:-}}"
if [ -z "$SESSION" ]; then
    if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
        SESSION="claude:$CLAUDE_CODE_SESSION_ID"
    elif [ -n "${CODEX_SESSION_ID:-}" ]; then
        SESSION="codex:$CODEX_SESSION_ID"
    elif [ -n "${CODEX_THREAD_ID:-}" ]; then
        SESSION="codex:$CODEX_THREAD_ID"
    fi
fi
[ -n "$SESSION" ] || exit 0

# message injection 拒否。":" は namespace と id の区切りとして正確に 1 個だけ許す。
case "$SESSION" in
    *:*) ;;
    *) exit 0 ;;
esac
AGENT="${SESSION%%:*}"
SESSION_ID="${SESSION#*:}"
case "$SESSION_ID" in
    *:*) exit 0 ;;
esac
case "$AGENT" in
    ""|*[!A-Za-z0-9._-]*) exit 0 ;;
esac
case "$SESSION_ID" in
    ""|*[!A-Za-z0-9_-]*) exit 0 ;;
esac

# repo 単位の opt-out は metadata gate より先に判定する。opt-out した repo を
# provenance 不足で止めてはならない。
for OPT_OUT_KEY in agent.sessionTrailer claude.sessionTrailer codex.sessionTrailer; do
    [ "$(git config --get "$OPT_OUT_KEY" 2>/dev/null || true)" != "false" ] || exit 0
done

if [ -n "$ORIGINAL_AGENT_SESSION" ]; then
    MODEL="${ORIGINAL_MODEL:-unknown}"
    EFFORT="${ORIGINAL_EFFORT:-unknown}"
else
    MODEL="${CLAUDE_CONFIG_AGENT_MODEL:-}"
    EFFORT="${CLAUDE_CONFIG_AGENT_EFFORT:-}"
fi
if [ -z "$ORIGINAL_AGENT_SESSION" ] && [ "$AGENT" = "codex" ]; then
    RESOLVED_METADATA="$(python3 "$SCRIPT_DIR/session_provenance_cache.py" \
        --resolve-codex "$SESSION_ID" 2>/dev/null || true)"
    RESOLVED_MODEL="$(printf '%s\n' "$RESOLVED_METADATA" | sed -n 's/^model=//p' | sed -n '1p')"
    RESOLVED_EFFORT="$(printf '%s\n' "$RESOLVED_METADATA" | sed -n 's/^effort=//p' | sed -n '1p')"
    [ -z "$RESOLVED_MODEL" ] || MODEL="$RESOLVED_MODEL"
    [ -z "$RESOLVED_EFFORT" ] || EFFORT="$RESOLVED_EFFORT"
else
    STATE_FILE=""
    if [ -n "${CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR:-}" ]; then
        STATE_FILE="$CLAUDE_CONFIG_SESSION_PROVENANCE_STATE_DIR/$SESSION_ID.env"
    elif [ -n "${HOME:-}" ] && [ "$AGENT" = "claude" ]; then
        STATE_FILE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/state/session-provenance/$SESSION_ID.env"
    fi
    if [ -n "$STATE_FILE" ] && [ -f "$STATE_FILE" ]; then
        [ -n "$MODEL" ] || MODEL="$(sed -n 's/^model=//p' "$STATE_FILE" 2>/dev/null | sed -n '1p')"
        [ -n "$EFFORT" ] || EFFORT="$(sed -n 's/^effort=//p' "$STATE_FILE" 2>/dev/null | sed -n '1p')"
    fi
fi
if [ -z "$EFFORT" ] && [ "$AGENT" = "claude" ]; then
    EFFORT="${CLAUDE_EFFORT:-}"
fi
MODEL_CHECK="$(printf '%s' "$MODEL" | tr -d '[]')"
if ! printf '%s\n' "$MODEL_CHECK" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._/@+-]*$'; then
    MODEL="unknown"
fi
if ! printf '%s\n' "$EFFORT" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]*$'; then
    EFFORT="unknown"
fi
if [ -z "$ORIGINAL_AGENT_SESSION" ] && [ "$AGENT" = "codex" ] && [ "$MODEL" = "unknown" ]; then
    echo "prepare-commit-msg: warning: active Codex model metadata is unavailable for session $SESSION_ID; writing Agent-Model: unknown" >&2
    echo "Check Codex hook trust/state when practical; do not substitute a configured default for the active model." >&2
fi

# --if-exists doNothing = 同 key の trailer が既にあれば git 側で no-op。
# git は comment 行 (core.commentChar) を認識して trailer block の位置を決めるので、
# ここで message の構造を自前で parse しない。
if git interpret-trailers --if-exists doNothing \
        --trailer "Agent-Session: $SESSION" \
        --trailer "Agent-Model: $MODEL" \
        --trailer "Agent-Effort: $EFFORT" \
        --in-place "$MSG_FILE" 2>/dev/null; then
    exit 0
fi

# --in-place 非対応な古い git への fallback (= 出力を書き戻す)。
TMP="$(mktemp 2>/dev/null)" || exit 0
if git interpret-trailers --if-exists doNothing \
        --trailer "Agent-Session: $SESSION" \
        --trailer "Agent-Model: $MODEL" \
        --trailer "Agent-Effort: $EFFORT" \
        "$MSG_FILE" > "$TMP" 2>/dev/null && [ -s "$TMP" ]; then
    cat "$TMP" > "$MSG_FILE" 2>/dev/null || true
fi
rm -f "$TMP" 2>/dev/null || true
exit 0
