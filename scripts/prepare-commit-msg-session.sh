#!/usr/bin/env bash
# prepare-commit-msg-session.sh — commit に発生元 Claude session の trailer を 1 行付ける (並列 session の事後追跡)
#
# 正本: <claude-config>/scripts/prepare-commit-msg-session.sh
# 配置: install-session-trailer.sh が各 repo の .git/hooks/prepare-commit-msg に 1 行
#       stub を置き、 本 script を exec する (= 更新は本 script を編集するだけで全 repo
#       に波及。 install-public-commit-msg.sh と同 pattern)。
#
# 何をするか: commit message の trailer block に 1 行足すだけ。
#
#     Claude-Session: <CLAUDE_CODE_SESSION_ID>
#
# 解く問題:
#   同一 working tree で複数の Claude session が並行して commit すると、 author は全
#   commit で同一人物に潰れ、 「どの commit がどの session のものか」 が git から復元
#   できない。 staging window race (= 検証に空けた数分で他 session の `git commit` に
#   自分の hunk が吸われる、 conventions/multi-session-coordination.md#staging-window-race)
#   の事後追跡が、 transcript 漁りと散文の記憶しか残らなくなる。 trailer があれば
#
#       git log --format='%h %(trailers:key=Claude-Session,valueonly)'
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
#   - CLAUDE_CODE_SESSION_ID が未設定 → 人手 commit / 非 Claude 経路。
#     「trailer の無い commit = Claude 経由でない」 が読めるのは副産物の利点。
#   - 既に Claude-Session: trailer がある → amend / rebase / cherry-pick で増殖させず、
#     最初に書いた session を保存する (冪等は git の --if-exists doNothing に委ねる)。
#     ⚠️ 帰結: rebase で書き換えた session ではなく「元の」 session が残る。
#   - session id が [A-Za-z0-9-] 以外を含む → message injection 拒否。
#   - git config claude.sessionTrailer = false → repo 単位の opt-out。
#
# fail-open: 何が起きても exit 0。 commit を止める価値のある検査ではない (= 止まると
#   並列 session の作業が詰まる方が高くつく)。
#
# selftest: prepare-commit-msg-session.test.sh (run-all-checks.sh が自動発見)

set -u

MSG_FILE="${1:-}"
[ -n "$MSG_FILE" ] || exit 0
[ -f "$MSG_FILE" ] || exit 0

SESSION="${CLAUDE_CODE_SESSION_ID:-}"
[ -n "$SESSION" ] || exit 0

# message injection 拒否 (= 改行 / 空白 / ":" を含む値で trailer block を壊さない)
case "$SESSION" in
    *[!A-Za-z0-9-]*) exit 0 ;;
esac

# repo 単位の opt-out
if [ "$(git config --get claude.sessionTrailer 2>/dev/null || true)" = "false" ]; then
    exit 0
fi

# --if-exists doNothing = 同 key の trailer が既にあれば git 側で no-op。
# git は comment 行 (core.commentChar) を認識して trailer block の位置を決めるので、
# ここで message の構造を自前で parse しない。
if git interpret-trailers --if-exists doNothing \
        --trailer "Claude-Session: $SESSION" \
        --in-place "$MSG_FILE" 2>/dev/null; then
    exit 0
fi

# --in-place 非対応な古い git への fallback (= 出力を書き戻す)。
TMP="$(mktemp 2>/dev/null)" || exit 0
if git interpret-trailers --if-exists doNothing \
        --trailer "Claude-Session: $SESSION" \
        "$MSG_FILE" > "$TMP" 2>/dev/null && [ -s "$TMP" ]; then
    cat "$TMP" > "$MSG_FILE" 2>/dev/null || true
fi
rm -f "$TMP" 2>/dev/null || true
exit 0
