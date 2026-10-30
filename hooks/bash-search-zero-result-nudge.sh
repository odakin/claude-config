#!/usr/bin/env bash
# bash-search-zero-result-nudge.sh — PostToolUse(Bash): ローカル discovery 検索の null (tree 検索空振り / glob 不成立) + truncate-before-grep pipeline + 素の grep が binary 扱いで飛ばす file を検出し「部分 scope の null で不在断定するな」 の scope 宣言 template を inject
#
# 正本: <claude-config>/hooks/bash-search-zero-result-nudge.sh
# 配信: setup.sh install_hooks (= ~/.claude/hooks/ に symlink + settings.json の
#       PostToolUse に登録、 matcher = Bash)
#
# 動作 (= 非 block、 -nudge):
#   sibling = mcp-search-zero-result-nudge.sh (外部 MCP search の 0 件) の
#   **ローカル版**。 外部 search null には nudge があるのに、 手元の grep/find の
#   null には無い非対称 (= 「1 repo だけ grep して『存在しない』」 「help 出力を
#   途中まで読んで『flag 無し』」 が素通り) を埋める。 decision-point 直前
#   (= 「null だったから X は無い」 と次 token で書く瞬間) の anchoring。
#
# detector:
#   A (tree-search null): 再帰 / tree 検索 (= grep -r/-R/--recursive、 git grep、
#     find <dir> -name/-iname/-path/-regex) の出力が完全空、 または zsh glob
#     不成立 (= shell の error 行 "<ctx>: no matches found: <pattern>" を行頭
#     anchor で検出。 phrase の素の substring では拾わない — 下の FP 設計参照)。
#     tree 検索は discovery-shaped = null を universal absence に変換する誘惑が
#     強い。 glob 不成立は更に「コマンド自体が走っていない」 ので null ですらない。
#   B (truncate-before-grep): pipeline で head / tail / sed -n (= 窓切り詰め) が
#     grep 系より **前** の segment にある = grep は切り詰めた窓の上しか見ていない。
#     正常 idiom は grep→head の順なので、 逆順は構造自体が signal (hit 有無に
#     関わらず fire)。 `tail -f` は stream 監視 idiom ゆえ除外。 見るのは同じ
#     pipeline の中だけ (`;` / `&&` / `||` / 改行で区切った別 command は別 pipeline)。
#     `head -c N | grep -q` (file 形式の magic の真偽判定) も除外。
#   C (binary-skipped file): Bash tool の素の grep (ugrep -I の shell 関数) が指す file の
#     先頭 256 KiB に NUL か不正な UTF-8 がある = 全部の行が飛ばされる (0 行で rc 1、
#     `grep -c` は何も出さない。 それより奥のバイトでは飛ばさない = 実測)。 同じ command の
#     別の出力が混ざるので空の判定では拾えない = 出力の有無に関わらず file を見て発火する。
#     `command grep` / `grep -a` / 再帰 / pipe 入力は対象外。 変数は同じ command の代入と
#     環境から解き、 解けない語 (loop の変数など) は飛ばす。 A・B より先に見る (具体的なので)。
#     conventions/shell-env.md#bash-tool-grep-ignores-gitignore
#
# FP 設計 (= conservative、 miss を許容して FP を避ける — sibling と同哲学):
#   - detector A は単一 file への grep / pipe 入力の grep を対象外にする (= leak check の
#     「0 hit = clean」 は bounded 検証で正当、 鳴らさない)
#   - 出力が 1 byte でもあれば A は沈黙 (= `|| echo` fallback 付きも沈黙 = miss 側)
#   - glob 不成立は shell error 行の形 (行頭 anchor + 直後のコロン) でだけ拾う
#     (= 2026-09-12: 本 hook の source を grep した出力に phrase が載って自己発火。
#     自分の検出文字列は検索対象になる = 素の substring match は自己言及で壊れる)
#   - rate limit (default 180s、 state = ~/.claude/state/bash-search-nudge/)
#   - 既知の miss (= 射程外、 意図的): 単一 path の存在 probe (ls -d X / test -e)、
#     Read tool の offset/limit 部分読み、 `grep -c` の "0" 出力、 rg (未使用)、
#     Bash tool の素の grep が ugrep --ignore-files として ignore された dir を飛ばす部分欠落
#     (= 0 件でないので鳴らない。 conventions/shell-env.md#bash-tool-grep-ignores-gitignore)、
#     pipe で渡した binary を素の grep が飛ばす形 (= 見る file が無い)、 再帰検索が中の binary を飛ばす形。
#     単一 path probe は discovery か bounded 検証かが機械判別不能 = claim 時の
#     scope 宣言規律 (個人層 CLAUDE.md inline §3) が floor。
#
# 設計動機 (2026-08-24 同一 session 2 連発、 個人層 RCA):
#   ① 別 repo に実在する doc を 1 repo 相当の検索 null で「存在しない stale」 と
#      誤報告 (= sweep の finding 報告そのものが部分 scope null だった)
#   ② CLI --help 227 行を先頭 ~200 行 + 切り詰め窓 grep で読み「該当 flag 無し」 を
#      公開 issue コメントに記載 (= 結論は偶然正しかったが導出が不健全)
#   詳細 = odakin-prefs/plans/2026-08-24-chat-to-code-bridge.md §4 (= 個人層)
#
# 出力経路: stdout JSON additionalContext + systemMessage + surface file
#   (sibling と同 pattern。 desktop は model 向け出力を捨てる 〔hook-authoring.md
#   #frontend-dependent-cowork〕 ため surface file が fallback)
# 安全: 全 path で fail-open。
#
# テスト env:
#   BASH_SEARCH_NUDGE_FORCE=1       matcher / 検出 / rate-limit を bypass して必ず発火
#   BASH_SEARCH_NUDGE_STATE_DIR     state dir override (test 隔離用)
#   BASH_SEARCH_NUDGE_WINDOW        rate-limit 秒数 override (0 = 無効化)

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

FORCE="${BASH_SEARCH_NUDGE_FORCE:-0}"

if command -v jq >/dev/null 2>&1; then
  TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
  COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
  RESPONSE="$(printf '%s' "$INPUT" | jq -r '
    (.tool_response // .tool_result // "") |
    if type == "object" then ((.stdout // "") + "\n" + (.stderr // ""))
    else tostring end' 2>/dev/null || true)"
else
  # jq 無し環境: command 抽出は quoting で壊れるので detector B は skip、
  # A は response 側 signal (glob null) のみ (= fail-open 縮退)
  TOOL_NAME="$(printf '%s' "$INPUT" | grep -oE '"tool_name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  COMMAND=""
  RESPONSE="$INPUT"
fi

# matcher 防御的再 check
if [ "$FORCE" != "1" ]; then
  [ "$TOOL_NAME" = "Bash" ] || exit 0
fi

FIRED=""
DETECTOR_DESC=""

# ---------- detector C: 素の grep が binary 扱いで飛ばす file ----------
# command の中の素の grep の file 引数だけを、 先頭 256 KiB まで読む。 解けない語・読めない file は
# 黙って飛ばす (fail-open)。
binary_skipped_file() {
  python3 - "$1" "$2" 2>/dev/null <<'PY'
import codecs, glob, os, re, shlex, sys

cmd, cwd = sys.argv[1], sys.argv[2]
LIMIT = 256 * 1024  # 素の grep が binary かを決める範囲 (実測)
LEADERS = {"if", "then", "elif", "else", "do", "while", "until", "time", "!", "{"}
ASSIGN = re.compile(r"([A-Za-z_]\w*)=(.*)", re.S)
env = {}


def expand(word):
    missing = []

    def sub(m):
        v = env.get(m.group(1), os.environ.get(m.group(1)))
        if v is None:
            missing.append(m.group(1))
        return v or ""

    out = re.sub(r"\$\{?([A-Za-z_]\w*)\}?", sub, word)
    return None if missing or "$" in out or "`" in out else os.path.expanduser(out)


def skipped(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(LIMIT)
    except OSError:
        return False
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return False
    if b"\0" in head:
        return True
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, False)
    except UnicodeDecodeError:
        return True
    return False


def grep_files(args):
    files, have_pattern, i = [], False, 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            rest = args[i:]
            return files + (rest if have_pattern else rest[1:])
        if a.startswith("--"):
            name = a.split("=")[0]
            if name in ("--text", "--recursive", "--dereference-recursive", "--null", "--null-data") or a == "--binary-files=text":
                return []
            have_pattern = have_pattern or name in ("--regexp", "--file")
            if "=" not in a and name in ("--regexp", "--file", "--include", "--exclude", "--exclude-dir",
                                         "--context", "--after-context", "--before-context", "--max-count"):
                i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            for j, c in enumerate(a[1:], 1):
                if c in "arRzZ":
                    return []
                have_pattern = have_pattern or c in "ef"
                if c in "efABCmd":
                    i += j == len(a) - 1
                    break
            continue
        if have_pattern:
            files.append(a)
        have_pattern = True
    return files


delim = None
for line in cmd.split("\n"):
    if delim is not None:
        delim = None if line.strip() == delim else delim
        continue
    m = re.search(r"(?<!<)<<-?(?!<)\s*['\"]?([A-Za-z_]\w*)", line)
    delim = m.group(1) if m else None
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError:
        continue
    simple, cur, skip_next = [], [], False
    for t in tokens + [";"]:
        if skip_next:
            skip_next = False
        elif set(t) <= set("();<>|&") and set(t) & set("<>"):
            skip_next = True  # 書き先・読み元は引数でない
        elif set(t) <= set("();|&"):
            simple.append(cur)
            cur = []
        else:
            cur.append(t)
    for words in simple:
        while words and words[0] in LEADERS:
            words = words[1:]
        if words and words[0] == "export":
            words = words[1:]
        if len(words) == 1 and ASSIGN.fullmatch(words[0]):
            name, value = ASSIGN.fullmatch(words[0]).groups()
            value = expand(value)
            if value is not None:
                env[name] = value
            continue
        while len(words) > 1 and ASSIGN.fullmatch(words[0]):
            words = words[1:]
        if len(words) > 1 and words[0] == "cd":
            target = expand(words[1])
            cwd = os.path.join(cwd, target) if target else cwd
        elif words and words[0] == "grep":
            for f in grep_files(words[1:]):
                p = expand(f)
                if p is None:
                    continue
                p = os.path.join(cwd, p)
                for q in (glob.glob(p) if glob.has_magic(p) else [p])[:200]:  # 広い glob で時間を使わない
                    if os.path.isfile(q) and skipped(q):
                        print(q)
                        sys.exit(0)
PY
}

case "$COMMAND" in
  *grep*)
    CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)"
    C_FILE="$(binary_skipped_file "$COMMAND" "${CWD:-$PWD}" || true)"
    if [ -n "$C_FILE" ]; then
      FIRED="C"
      DETECTOR_DESC="素の grep が binary 扱いで飛ばす file (= 先頭に NUL か不正な UTF-8。 0 行・出力なしは件数でない): $C_FILE"
    fi
    ;;
esac

# ---------- detector B: truncate-before-grep ----------
# 先に command を pipeline ごとに分け (`;` / `&&` / `||` / 改行)、 同じ pipeline の中で
# truncator が grep より前の segment にあるときだけ発火する。 分けずに command 全体を
# '|' で割ると、 `a | tail -1; b | grep x` のように別 command の tail と grep が
# 1 本の pipeline に見えて発火する (実測)。
# `head -c N | grep -q MAGIC` は file 形式の先頭 magic を真偽で確かめる idiom
# (conventions/secret-handoff.md の git-crypt 判定) = 窓を読んで不在を言う形ではないので除く。
# naive split (quoted '|' ';' の誤 split は truncator/grep 語 match に達しないので実害無し)
if [ -z "$FIRED" ] && [ -n "$COMMAND" ]; then
  B_HIT="$(printf '%s' "$COMMAND" | awk '
    { buf = buf $0 "\n" }
    END {
      gsub(/\|\||&&|;/, "\n", buf)
      nl = split(buf, lines, "\n")
      for (l = 1; l <= nl; l++) {
        ns = split(lines[l], segs, "|")
        trunc = -1; grepseg = -1; bytehead = 0; quiet = 0
        for (i = 1; i <= ns; i++) {
          seg = segs[i]
          if (trunc < 0) {
            if (seg ~ /(^|[[:space:]&(])head([[:space:]]|$)/) { trunc = i; bytehead = (seg ~ /head[[:space:]]+-c/) }
            else if (seg ~ /(^|[[:space:]&(])tail([[:space:]]|$)/ && seg !~ /tail[[:space:]]+-[a-zA-Z]*f/) trunc = i
            else if (seg ~ /(^|[[:space:]&(])sed[[:space:]]+-n([[:space:]]|$)/) trunc = i
          }
          if (grepseg < 0 && seg ~ /(^|[[:space:]&(])(grep|egrep|fgrep)([[:space:]]|$)/) {
            grepseg = i
            quiet = (seg ~ /(grep|egrep|fgrep)[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*(-[a-zA-Z]*q[a-zA-Z]*|--quiet)([[:space:]]|$)/)
          }
        }
        if (trunc > 0 && grepseg > 0 && trunc < grepseg && !(bytehead && quiet)) { print "yes"; exit }
      }
    }' 2>/dev/null || true)"
  if [ "$B_HIT" = "yes" ]; then
    FIRED="B"
    DETECTOR_DESC="truncate-before-grep (= head/tail/sed -n が grep より前 → grep は切り詰めた窓しか見ていない)"
  fi
fi

# ---------- detector A: tree-search null / glob 不成立 ----------
if [ -z "$FIRED" ]; then
  A_STRUCT=0
  if [ -n "$COMMAND" ]; then
    # (a) grep 系の再帰 flag (= grep 語直後から flag token 列を walk して r/R 入り token を探す。
    #     pattern 引数中の "-r" 文字列や別 command の -rf との誤結合を防ぐため、
    #     dash-flag token の連なりの中だけを見る)
    if printf '%s' "$COMMAND" | grep -qE '(^|[[:space:];&|(])(grep|egrep|fgrep)[[:space:]]+((-[a-zA-Z]+|--[a-z-]+)[[:space:]]+)*(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)([[:space:]]|$)'; then
      A_STRUCT=1
    # (b) git grep (= repo tree 検索)
    elif printf '%s' "$COMMAND" | grep -qE '(^|[[:space:];&|(])git[[:space:]]+grep[[:space:]]'; then
      A_STRUCT=1
    # (c) find + 検索述語
    elif printf '%s' "$COMMAND" | grep -qE '(^|[[:space:];&|(])find[[:space:]][^|]*-(iname|name|path|regex)[[:space:]]'; then
      A_STRUCT=1
    fi
  fi
  # zsh nomatch は **shell の error 行** の形でしか来ない (= 行頭の短い context
  # prefix + "no matches found: <pattern>"。 実測 3 形: "(eval):1: " = Bash tool の
  # 実行 context / "zsh:1: " = zsh -c / "zsh: " = interactive)。 素の substring
  # match だと、 この phrase を含む file を grep しただけで発火する (= 本 hook 自身の
  # source / doc / test / log を読む度に FP。 2026-09-12 に実発生) ので、 行頭 anchor
  # と phrase 直後のコロンまで要求して error 行だけを拾う。
  GLOB_NULL=0
  if printf '%s' "$RESPONSE" | grep -qE '^[^[:space:]]*:[[:space:]]?no matches found: '; then
    GLOB_NULL=1
  fi
  if [ "$GLOB_NULL" = 1 ]; then
    FIRED="A"
    DETECTOR_DESC="glob 不成立 (= zsh nomatch。 ⚠️ コマンド自体が実行されていない — glob を quote して再実行)"
  elif [ "$A_STRUCT" = 1 ]; then
    trimmed="$(printf '%s' "$RESPONSE" | tr -d '[:space:]')"
    if [ -z "$trimmed" ]; then
      FIRED="A"
      DETECTOR_DESC="tree 検索空振り (= grep -r / git grep / find の出力が完全空)"
    fi
  fi
fi

# FORCE: 検出に関わらず fire (= test 用)
if [ "$FORCE" = "1" ] && [ -z "$FIRED" ]; then
  FIRED="A"
  DETECTOR_DESC="(forced)"
fi

[ -z "$FIRED" ] && exit 0

# ---------- rate limit (= FP 許容度の主対策、 FORCE は bypass + stamp 汚染なし) ----------
STATE_DIR="${BASH_SEARCH_NUDGE_STATE_DIR:-$HOME/.claude/state/bash-search-nudge}"
WINDOW="${BASH_SEARCH_NUDGE_WINDOW:-180}"
if [ "$FORCE" != "1" ]; then
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  STAMP="$STATE_DIR/last-fire"
  # detector C は file が決まっている具体の指摘 = A・B の窓に畳まない
  [ "$FIRED" = "C" ] && STAMP="$STATE_DIR/last-fire-binary"
  now="$(date +%s 2>/dev/null || echo 0)"
  if [ -f "$STAMP" ] && [ "$WINDOW" -gt 0 ] 2>/dev/null; then
    last="$(cat "$STAMP" 2>/dev/null || echo 0)"
    case "$last" in (*[!0-9]*) last=0 ;; esac
    if [ $(( now - last )) -lt "$WINDOW" ]; then
      exit 0
    fi
  fi
  printf '%s' "$now" > "$STAMP" 2>/dev/null || true
fi

# command 表示 (= 多バイト安全な文字単位 truncate、 shell-multibyte-truncation.md)
CMD_SHOW="$(printf '%s' "$COMMAND" | python3 -c 'import sys; s = sys.stdin.read().replace("\n", " "); print(s[:200] + ("…" if len(s) > 200 else ""))' 2>/dev/null || printf '%s' "$COMMAND" | head -1)"

C_WIDEN=""
[ "$FIRED" = "C" ] && C_WIDEN="  ・command grep か grep -a で読み直す (conventions/shell-env.md#bash-tool-grep-ignores-gitignore)
"

REMINDER="🛑 ローカル検索 null — 部分 scope で不在断定しない zone

detector: $FIRED = $DETECTOR_DESC
command: $CMD_SHOW

⚠️ 次の token で禁止する claim (= scope 未宣言のまま):
  ❌ 「存在しない / 無い / 見つからなかった」 で確定
  ❌ 「〜という flag / file / 設定は無い」 (= 窓の外・他 repo/dir 未確認のまま)

✅ 断定するなら 1 行で scope を埋める:
  見た scope = ____ / NOT = ____ / null in [見た scope]

広げる例 (= 正しい行動の限界費用をゼロに):
${C_WIDEN}  ・同じ検索を 1 つ上の階層 or sibling repo 群で再実行 (grep -r / find <上位 dir>)
  ・切り詰め (head / sed -n) を外して全長で再実行、 または | wc -l で全長を先に確認

設計動機: 2026-08-24 同一 session 2 連発 (= 1 repo の検索 null で「doc 不在」 誤断定
  〔実体は sibling repo に実在〕 / --help を途中窓で grep して「flag 無し」 を公開 issue に
  投稿)。 単一 path の存在 probe と Read 部分読みは本 hook の射程外 = claim 時の
  scope 宣言が floor。 詳細 = odakin-prefs/plans/2026-08-24-chat-to-code-bridge.md §4"

# ---------- surface file (= desktop fallback) ----------
SURFACE_DIR="${CLAUDE_SURFACE_DIR:-$HOME/.claude/surface}"
mkdir -p "$SURFACE_DIR" 2>/dev/null || true
{ printf '# 🛑 ローカル検索 null (= 直前の Bash 検索、 universal claim 禁止)\n\n'
  printf '%s\n' "$REMINDER"; } > "$SURFACE_DIR/bash-search-zero.txt" 2>/dev/null || true

printf '%s\n' "$REMINDER" >&2

# stdout JSON (= additionalContext + systemMessage の 2 経路併用、 sibling と同 spec 対応)
if command -v jq >/dev/null 2>&1; then
  jq -n --arg msg "$REMINDER" '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": $msg
    },
    "systemMessage": $msg
  }'
else
  esc="$(printf '%s' "$REMINDER" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "[bash-search-zero] local search returned null")"
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s},"systemMessage":%s}\n' "$esc" "$esc"
fi

exit 0
