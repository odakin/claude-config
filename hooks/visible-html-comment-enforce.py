#!/usr/bin/env python3
"""visible-html-comment-enforce.py — Stop: 最終メッセージに HTML comment (`<!-- ... -->`) が裸で出ていたら、 1 回だけ差し戻して置き場所を直させる

何を塞ぐか (正本 = conventions/mid-turn-text-visibility.md#html-comment-not-hidden):
  Claude Code の chat は最終メッセージの HTML comment を literal に表示する。 web の markdown renderer で消えることを根拠に
  「user には見えない印」 として hook 向けの marker を本文に置くと、 そのまま user の画面に出る。 規約を書いた後も、
  古い書き方の写し (repo の CLAUDE.md 等) を読んだ session が 4 turn 続けて同じ marker を出した (実測)。
  文書の規律は写しが 1 つ残れば破れるので、 出た turn で止めて、 同じ session の次の turn から繰り返させない。

述語:
  fire = 今の turn の最終 assistant 発話から fenced code block と inline code を除いた残りに `<!--` が在る。
  除外 = fenced block の中 / inline code の中 (= marker について説明している文は止めない)。
  frontend は問わない (CLI でも literal に出る)。

挙動: fire 時 decision=block + reason (見つけた comment と、 marker の正しい置き場所 = Bash command の末尾 comment)。
  差し戻された turn の出し直しでは本文から comment を除いた全文を出す。 stop_hook_active=true は即 exit 0 (1 回だけ)。
  fail-open: transcript / 部品 (scripts/lib/transcript_turns.py) の不在や例外は沈黙。

⚠️ 射程の限界: 出た後に止める網で、 最初の 1 回の露出は防げない (Stop hook は表示の後に走る)。 露出そのものを無くすのは
  marker を要らなくする側 (検出を tool 入力の走査にする / 発火条件を hook 自身が判定する) = 同 doc #machine-marker-in-tool-input。
  test = hooks/visible-html-comment-enforce.test.sh
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = os.environ.get("CLAUDE_CONFIG_ROOT") or str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(Path(ROOT) / "scripts" / "lib"))

# fence / inline code の式は chat_file_refs.py と同じ (list・引用の中の fence も code block として除く)
FENCE_RE = re.compile(r"^[ \t>]*(`{3,}(?=[^`\n]*\n)|~{3,})[^\n]*\n.*?(?:^[ \t>]*\1[ \t]*$|\Z)", re.S | re.M)
CODE_SPAN_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
COMMENT_RE = re.compile(r"<!--(.*?)(?:-->|\Z)", re.S)


def find_comments(text: str) -> list[str]:
    bare = CODE_SPAN_RE.sub(" ", FENCE_RE.sub(" ", text))
    return [m.group(0).strip()[:80] for m in COMMENT_RE.finditer(bare)]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("stop_hook_active"):
        return 0
    path = data.get("transcript_path") or ""
    if not path or not os.path.isfile(path):
        return 0
    try:
        import transcript_turns as tt
        final, _ = tt.current_turn_final(tt.load_entries(path))
    except Exception:
        return 0
    found = find_comments(final or "")
    if not found:
        return 0
    reason = (
        "最終メッセージに HTML comment が裸で出ています: " + " / ".join(found[:3]) + "\n"
        "Claude Code の chat は HTML comment を literal に表示するので、 user の画面にそのまま出ました。\n"
        "hook 向けの marker は応答本文でなく tool 入力に置く (例: Bash command の末尾に `# <marker>`)。 "
        "marker が要るのは、 その hook の発火条件を満たす turn だけ。\n"
        "いまの応答を、 comment を除いた全文で出し直し、 以後の turn で本文に置かない。 "
        "comment を例として見せたいだけなら inline code か fenced code block に入れる。\n"
        "正本 = claude-config/conventions/mid-turn-text-visibility.md#html-comment-not-hidden"
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
