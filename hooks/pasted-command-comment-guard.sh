#!/usr/bin/env bash
# pasted-command-comment-guard.sh — user に貼らせるコマンドに `#` コメントが混ざっていたら Stop で書き直させる (対話 zsh は # をコメントにしない)
#
# Stop hook: 「user に貼って実行してもらうコマンド」 を chat の fenced code block で
# 出したターンで、 その block 内に `#` コメント (行内・行頭とも) が混ざっていたら
# 1 回だけ {"decision":"block","reason":...} で書き直しを要求する。
#
# 何を塞ぐか (= 2026-09-09 RCA、 正本 = 層1
# claude-config/conventions/shell-env.md#no-inline-comments-in-pasted-commands、
# family framework = 同 paste-destined-plain-text.md#same-framework-other-paste-targets):
#   macOS 既定の **interactive zsh は `interactive_comments` が既定 OFF**。
#   対話プロンプトに貼った行の `#` は**コメントにならず通常の引数になる**。
#     `git rebase --continue    # todo 残り 0`
#       → argv = [rebase, --continue, #, todo, 残り, 0]  (= 実測、 pty 再現済)
#       → git が usage error で弾き、 rebase が続かず後続が detached HEAD で失敗
#   行頭 `#` 単独行も同様に `zsh: command not found: #` になる (= 独立行に
#   逃がしても解決しない)。 bash の interactive は同 option が既定 ON なので
#   bash ユーザーは踏まない = **zsh 固有 × macOS 既定 shell** の非対称。
#
# ⚠️ この失敗は確率的でなく **決定的** (= 貼れば必ず壊れる)。 「短い注釈なら」
#   「ASCII なら」 は全部誤り。 かつ **Claude 自身の Bash tool は非対話 zsh
#   なので `#` が正しくコメントとして効く** — つまり Claude は日常的に
#   「`#` は動く」 という体験だけを積み、 この失敗を自分の tool では
#   一度も観測できない (= 規約の外に証拠が無い class)。
#
# 述語 (2026-09-09 に transcript 59 本 / 2026-07-22..09-09 の 49 日で実測校正):
#   fire = (assistant の当ターン text に貼り付け指示語) ∧
#          (fenced block 内に 実行系コマンド行 + 行内 `#`  または 行頭 `#` 行)
#   実測: fired = 3 日分 / 49 日 (INLINE 3 行 = 2026-09-09 の事故そのもの、
#   FULLLINE 2 行 = 08-24 / 09-05)。 貼り付け指示語 filter を外しても hit 数は
#   同じ = filter は真陽性を落とさず FP だけ削る (= 実測 FP 0)。
#
# 挙動:
#   - fire 時: decision=block + reason で「① 注釈を消して素のコマンドだけ出す
#     ② 複数行なら script file に書いて 1 行の起動コマンドだけ渡す (script 内の
#     `#` は非対話 parse なので正しくコメント) ③ 自分で実行できるなら貼らせない」
#     を提示。
#   - stop_hook_active=true は即 exit 0 (loop guard)。
#   - fail-open: jq / python3 / transcript 不在・parse 不能は silent exit 0。
#
# ⚠️ 射程の限界 (honest):
#   - fence の外に素で書いたコマンドは検出しない (= 提示は普通 fence 内なので許容)。
#   - script の中身を「見せる」 目的の fence は原理的に区別できない。 貼り付け
#     指示語との共起で削っているが、 完全ではない (= FP 1 turn のコスト)。
#   - Claude Code desktop は hook の model 向け出力を honor しない
#     (層1 hook-authoring.md#frontend-dependent-cowork) → desktop session では
#     block が死ぬ可能性が高い。 CLI / Remote Control (CLI backend) が射程。
#     desktop 側の floor は規律 (= shell-env.md) と「script 経路を既定にする」 設計。
#   - 貼り付け指示語 regex は **日本語のみ実データ校正済** (49 日 / 真陽性 3 / FP 0)。
#     英語 cue は推定で足してあるだけなので、 英語 session で FP が出たら削る方向で
#     調整すること (= 校正データが無い部分は「効く」 と主張しない)。
#   - fence の言語指定 (```sh 等) は見ていない。 見せるだけの例示 fence と貼り付け用
#     fence を構文で区別する手段が無いため、 貼り付け指示語との共起で代用している。

set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)"
[ "$ACTIVE" = "true" ] && exit 0

TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0

MATCHED="$(python3 - "$TRANSCRIPT" <<'PYEOF' 2>/dev/null || true
import json, re, sys

# 実行系コマンドで始まる行 (= 貼れば走る行)
CMD = (r"git|cd|npm|npx|launchctl|python3?|bash|zsh|sh|grep|ls|rm|mv|cp|mkdir|open|brew|gh|"
       r"osascript|defaults|pbcopy|pbpaste|curl|make|cat|chmod|find|sed|awk|export|source|"
       r"claude|code|pip3?|node|yarn|plutil|killall|sudo|scp|ssh|rsync|tar|unzip|say|lp|"
       r"security|tccutil|xattr|caffeinate|env")
CMD_RE = re.compile(r"^\s*(?:%s)\b" % CMD)
INLINE_HASH_RE = re.compile(r"\S\s+#(?!!)")        # 行内 # (shebang は除外)
FULLLINE_HASH_RE = re.compile(r"^\s*#(?!!)")       # 行頭 # 単独行
# bash 3.2 parses heredoc bodies inside $(...) incorrectly; avoid literal backticks here.
FENCE_RE = re.compile(r"^\s*" + chr(96) * 3)
PASTE_CUE = re.compile(
    # 日本語 (2026-09-09 に transcript 49 日で校正、 真陽性 3 / FP 0)
    r"実行して|打って|貼って|貼り付け|ターミナル|コピペ|流して|叩いて|"
    r"走らせて|やってみて|試して|してみて"
    # English (未校正 = 実データが無いので推定。 FP が出たら削る方向で調整する)
    r"|terminal|run (?:this|these|the following|it)|paste (?:this|the|it)"
    r"|copy[ -](?:and[ -])?paste|execute (?:this|the following)|in your shell",
    re.IGNORECASE)


def strip_quoted(line):
    """quote の中身を落とす (quote 内 # の誤検出を避ける)。"""
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in "'\"":
            j = line.find(c, i + 1)
            if j == -1:
                return "".join(out)
            i = j + 1
            out.append("QQ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def scan(text):
    if not PASTE_CUE.search(text):
        return None
    in_fence = False
    for ln in text.split("\n"):
        if FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        if CMD_RE.match(ln) and INLINE_HASH_RE.search(strip_quoted(ln)):
            return ln.strip()[:120]
        if FULLLINE_HASH_RE.match(ln) and ln.strip() != "#":
            return ln.strip()[:120]
    return None


def main():
    try:
        rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8", errors="replace")
                if l.strip()]
    except Exception:
        return
    # 直近の user turn 以降の assistant text だけを見る (= 当ターン)
    start = 0
    for i, r in enumerate(rows):
        if r.get("type") == "user":
            start = i
    for r in rows[start:]:
        if r.get("type") != "assistant":
            continue
        for b in ((r.get("message") or {}).get("content") or []):
            if isinstance(b, dict) and b.get("type") == "text":
                hit = scan(b.get("text") or "")
                if hit:
                    print(hit)
                    return


main()
PYEOF
)"

[ -n "$MATCHED" ] || exit 0

REASON="貼り付け用コマンドに \`#\` コメントが混ざっています (検出行: ${MATCHED})。

macOS 既定の interactive zsh は interactive_comments が既定 OFF なので、貼り付けた行の \`#\` は
コメントにならず**通常の引数**になります。実測 (pty 再現): \`git rebase --continue    <hash> todo 残り 0\`
は argv = [rebase, --continue, <hash>, todo, 残り, 0] となり usage error で弾かれます。
行頭 \`#\` の単独行も \`command not found: #\` になるので、独立行へ逃がしても解決しません。
これは確率的でなく決定的 (貼れば必ず壊れる) です。自分の Bash tool は非対話 zsh なので
\`#\` が効きますが、user の対話 zsh では効きません — 自分の体験を根拠にしないでください。

最終メッセージを次のどれかに書き直してから終了してください:
  ① コメントを全部消し、fence 内は素のコマンドだけにする (説明は fence の外に散文で書く)
  ② 2 行以上 or quote/glob を含むなら、script file に書いて起動 1 行だけを渡す
     (script 内は非対話 parse なので \`#\` コメントは正しく効く = 注釈を捨てなくてよい)
  ③ 自分で実行できるなら、そもそも貼らせずに Bash tool で実行する

正本: claude-config/conventions/shell-env.md#no-inline-comments-in-pasted-commands"

jq -cn --arg r "$REASON" '{decision:"block", reason:$r}'
exit 0
