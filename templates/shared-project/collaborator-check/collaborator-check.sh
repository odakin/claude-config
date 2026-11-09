#!/usr/bin/env bash
# collaborator-check.sh — 共有リポの各 clone で session 開始時に走り、 その repo が各自の手元に要る設定 (個人の token・道具・Python の版) と初回に読む節を、 欠けている時だけ直し方つきで出す。 隣に要る repo は無ければ clone し、 あれば最新にする。
#
# 正本 = claude-config の templates/shared-project/collaborator-check/ 。 repo の
# tools/collaborator-check/ は写し (共同編集者は claude-config を持たないので repo 単体で動く)。
# 直すときは正本を直し、 scripts/install-collaborator-check.py install <repo> で配り直す。
# 規約 = conventions/shared-repo.md#collaborator-check
#
# 設定 = repo root の .collaborator-check.conf (1 行 1 項目、 # で始まる行と空行は無視):
#   file <path> [<上書きの環境変数>] -- <直し方>     例: file ~/.secrets/svc-token SVC_TOKEN_FILE -- 自分の token を発行して置く
#     (その環境変数に none を入れた人は「使わない」 扱いで出さない = 満たせない項目で毎回 ❌ を出し続けないため)
#   command <名前> -- <直し方>                       例: command latexmk -- TeX Live を入れる
#   read <file の節> -- <何が書いてあるか>            例: read CLAUDE.md §共同編集者向け -- 招待された人の手順
#   repo <dir 名> <clone URL> [<上書きの環境変数>] -- <何に使うか>
#                                                    例: repo tool-repo https://github.com/<owner>/tool-repo TOOL_REPO_DIR -- 道具
#     この repo の隣 (= 同じ親 dir) の <dir 名> に要る repo。 無ければその場で clone し、 あれば 20 時間に 1 回
#     fast-forward で最新にする (作業中の変更がある・分岐している時は触らない)。 URL は https:// か file:// だけ。
#     別の場所に置いている人は環境変数にその path、 要らない人は none。 人に「隣に clone して」 と頼まない
#     (人の記憶は carrier でない) ための項目 = 規約 conventions/shared-repo.md#collaborator-check
#   board <board dir> [<engine の dir の環境変数>] -- <何か>   例: board board AI_COLLABORATION_DIR -- 掲示板の自分宛て
#     この repo の中の掲示板 (<board dir>/board.json) で要注意の thread (引受待ち・検収待ち・質問) を session の冒頭に出す。
#     engine = 環境変数の dir (既定 AI_COLLABORATION_DIR)、 無ければこの repo の隣の ai-collaboration (= 上の repo 行が clone する)。
#     手元の写しを読む (network なし)。 要注意が無ければ何も出さない。 engine が無ければ黙る (repo 行の ❌ が先に出る)
#   python [<入口の path>] -- <何に使うか>              例: python tools/py -- 計算と検算
#     この repo の Python の入口 (既定 tools/py = claude-config の templates/shared-project/python-env/py の写し) に
#     `--venv-check` を聞く (network なし、 何も変えない)。 venv の用意・requirements への追従は入口が初回の実行で
#     自動でやるので、 ここで出すのは人の手が要るとき (宣言の版の Python がこの機械に無い / 宣言外の venv を使っている) だけ。
#     規約 = conventions/python-env.md
#   ⚠️ 上書きの環境変数 (file・repo・board 行) に Claude Code・SDK 自身の変数 (CLAUDE_CONFIG_DIR・CLAUDE_CODE_*・ANTHROPIC_*)
#     を使わない。 session がその変数に値を入れていることがあり、 check がその値 (例 = Claude Code の設定フォルダ) を
#     この行の置き場と取り違える (無ければそこへ clone もする)。 当たる行は読まずに ⚠️ を出す。 名前は
#     <REPO>_REPO_DIR / <NAME>_FILE の形にする (止める名前の一覧 = 下の RESERVED_ENV_NAMES・RESERVED_ENV_PREFIXES)
#
# 出力: file / command / repo が揃っていれば何も出さない。 read は clone ごとの初回だけ出す
# (印 = .git/collaborator-check.seen)。 欠けた項目・その場で clone した repo・初回の read を 1 block で出す。
# 終了値は常に 0 (session を止めない)。 呼び方:
#   bash tools/collaborator-check/collaborator-check.sh            # 普通に (Claude Code の SessionStart hook もこれ)
#   bash tools/collaborator-check/collaborator-check.sh --all      # 揃っている項目も ✅ で出す (確認用、 初回の印は付けない)

ALL=0
[ "${1:-}" = "--all" ] && ALL=1

ROOT="$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)" || exit 0
CONF="$ROOT/.collaborator-check.conf"
[ -f "$CONF" ] || exit 0

GITDIR="$(git -C "$ROOT" rev-parse --absolute-git-dir 2>/dev/null)"
SEEN=""
[ -n "$GITDIR" ] && SEEN="$GITDIR/collaborator-check.seen"
FIRST=0
if [ -n "$SEEN" ] && [ ! -e "$SEEN" ]; then FIRST=1; fi

missing=""
ok=""
reads=""
done_now=""
boards=""
PARENT="$(dirname "$ROOT")"
PULL_EVERY_MIN=1200

git_net() {
  GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 "$@" </dev/null
}

expand_home() {
  case "$1" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s/%s' "$HOME" "${1#\~/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# 上書きの変数に使えない名前 = Claude Code・SDK が自分で読む変数 (完全一致の名前と、 接頭)。 足すときはここに並べる
RESERVED_ENV_NAMES="CLAUDE_CONFIG_DIR"
RESERVED_ENV_PREFIXES="CLAUDE_CODE_ ANTHROPIC_"

reserved_env() {
  local n
  for n in $RESERVED_ENV_NAMES; do [ "$1" = "$n" ] && return 0; done
  for n in $RESERVED_ENV_PREFIXES; do case "$1" in "$n"*) return 0 ;; esac; done
  return 1
}

reserved_list() {
  local n out=""
  for n in $RESERVED_ENV_NAMES; do out="${out}・${n}"; done
  for n in $RESERVED_ENV_PREFIXES; do out="${out}・${n}*"; done
  printf '%s' "${out#・}"
}

# 代わりの名前の例: <素を大文字にして英数字以外を _ に><末尾>。 それ自体が止める名前に当たれば COLLAB_ を前に付ける
env_suggest() {
  local s
  s="$(printf '%s' "$1" | sed 's/^\.*//' | LC_ALL=C tr 'a-z' 'A-Z' | LC_ALL=C sed 's/[^A-Z0-9_]/_/g')$2"
  reserved_env "$s" && s="COLLAB_${s}"
  printf '%s' "$s"
}

reserved_line() {  # $1 = 行の種類、 $2 = 変数、 $3 = 代わりの名前の例、 $4 = conf の行
  missing="$missing
  ⚠️ .collaborator-check.conf の ${1} 行の上書きの変数 ${2} は Claude Code・SDK 自身の変数 ($(reserved_list)) で、 session が値を入れていることがある (その値をこの行の置き場と取り違える) → この行は読まない。 変数の名前を変える (例 ${3}): ${4}"
}

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  head="${line%% -- *}"
  how=""
  [ "$head" != "$line" ] && how="${line#* -- }"
  set -f
  # shellcheck disable=SC2086
  set -- $head
  set +f
  kind="${1:-}"
  case "$kind" in
    file)
      path="$(expand_home "${2:-}")"
      envvar="${3:-}"
      shown="${2:-}"
      if [ -n "$envvar" ] && reserved_env "$envvar"; then
        reserved_line file "$envvar" "$(env_suggest "${shown##*/}" _FILE)" "$line"
        continue
      fi
      if [ -n "$envvar" ]; then
        val="$(printenv "$envvar" 2>/dev/null)"
        if [ "$val" = "none" ]; then
          ok="$ok
  ⏭ $shown は使わない (\$$envvar=none)"
          continue
        fi
        if [ -n "$val" ]; then path="$(expand_home "$val")"; shown="$val (\$$envvar)"; fi
      fi
      if [ -s "$path" ]; then
        ok="$ok
  ✅ $shown がある"
      else
        missing="$missing
  ❌ $shown が無い → $how"
      fi
      ;;
    command)
      name="${2:-}"
      if command -v "$name" >/dev/null 2>&1; then
        ok="$ok
  ✅ $name がある"
      else
        missing="$missing
  ❌ $name が無い → $how"
      fi
      ;;
    read)
      shift
      reads="$reads
  📖 $* を読む${how:+ ($how)}"
      ;;
    repo)
      name="${2:-}"
      url="${3:-}"
      envvar="${4:-}"
      case "$name" in ''|.|..|*/*|-*)
        missing="$missing
  ⚠️ .collaborator-check.conf の repo の dir 名が使えない: $line"
        continue ;;
      esac
      case "$url" in https://*|file://*) ;; *)
        missing="$missing
  ⚠️ .collaborator-check.conf の repo の URL は https:// か file:// だけ: $line"
        continue ;;
      esac
      if [ -n "$envvar" ] && reserved_env "$envvar"; then
        reserved_line repo "$envvar" "$(env_suggest "$name" _REPO_DIR)" "$line"
        continue
      fi
      dest="$PARENT/$name"
      shown="$name"
      if [ -n "$envvar" ]; then
        val="$(printenv "$envvar" 2>/dev/null)"
        if [ "$val" = "none" ]; then
          ok="$ok
  ⏭ $name は使わない (\$$envvar=none)"
          continue
        fi
        if [ -n "$val" ]; then dest="$(expand_home "$val")"; shown="$name ($val = \$$envvar)"; fi
      fi
      if [ ! -e "$dest" ]; then
        if git_net clone -q -- "$url" "$dest" >/dev/null 2>&1; then
          d_git="$(git -C "$dest" rev-parse --absolute-git-dir 2>/dev/null)"
          [ -n "$d_git" ] && : > "$d_git/collaborator-check.pulled" 2>/dev/null
          done_now="$done_now
  📥 $shown が無かったので clone した ($dest)${how:+ = $how}"
        else
          rm -rf "$dest" 2>/dev/null
          missing="$missing
  ❌ $shown を clone できなかった (network?) → git clone $url \"$dest\"${how:+ ($how)}"
        fi
        continue
      fi
      d_git="$(git -C "$dest" rev-parse --absolute-git-dir 2>/dev/null)"
      if [ -z "$d_git" ]; then
        missing="$missing
  ❌ $dest はあるが git の checkout でない → 退けてから次の session で clone される${how:+ ($how)}"
        continue
      fi
      ok="$ok
  ✅ $shown がある"
      stamp="$d_git/collaborator-check.pulled"
      if [ -z "$(find "$stamp" -mmin -"$PULL_EVERY_MIN" 2>/dev/null)" ]; then
        : > "$stamp" 2>/dev/null
        if [ -z "$(git -C "$dest" status --porcelain 2>/dev/null)" ] \
            && git -C "$dest" rev-parse -q --verify '@{u}' >/dev/null 2>&1; then
          if ! git_net -C "$dest" pull -q --ff-only >/dev/null 2>&1; then
            missing="$missing
  ⚠️ $shown を最新にできなかった (network か、 手元の commit が分岐している) → git -C \"$dest\" pull --ff-only"
          fi
        fi
      fi
      ;;
    board)
      bdir="${2:-board}"
      envvar="${3:-AI_COLLABORATION_DIR}"
      if reserved_env "$envvar"; then
        reserved_line board "$envvar" "AI_COLLABORATION_DIR = 既定なので省いてもよい" "$line"
        continue
      fi
      engine="$(printenv "$envvar" 2>/dev/null)"
      [ "$engine" = "none" ] && continue
      [ -n "$engine" ] && engine="$(expand_home "$engine")" || engine="$PARENT/ai-collaboration"
      start="$engine/board/board-session-start.py"
      if [ -f "$ROOT/$bdir/board.json" ] && [ -f "$start" ] && command -v python3 >/dev/null 2>&1; then
        text="$(python3 "$start" --no-sync --plain --root "$ROOT/$bdir" 2>/dev/null)"
        [ -n "$text" ] && boards="$boards
$text"
      fi
      ;;
    python)
      wrapper="${2:-tools/py}"
      case "$wrapper" in /*|*..*)
        missing="$missing
  ⚠️ .collaborator-check.conf の python の入口は repo の中の相対 path だけ: $line"
        continue ;;
      esac
      if [ ! -f "$ROOT/$wrapper" ]; then
        missing="$missing
  ❌ $wrapper (Python の入口) が無い → claude-config の scripts/install-collaborator-check.py で配り直す${how:+ ($how)}"
        continue
      fi
      pyout="$(bash "$ROOT/$wrapper" --venv-check 2>/dev/null)"
      if [ $? -eq 0 ]; then
        ok="$ok
  ✅ Python の環境 ($wrapper)${how:+ = $how}"
      else
        [ -n "$pyout" ] || pyout="❌ $wrapper --venv-check が理由を出さずに失敗した"
        missing="$missing
$(printf '%s\n' "$pyout" | sed 's/^/  /')"
      fi
      ;;
    *)
      missing="$missing
  ⚠️ .collaborator-check.conf の読めない行: $line"
      ;;
  esac
done < "$CONF"

show_reads=0
[ "$FIRST" = 1 ] && [ -n "$reads" ] && show_reads=1
[ "$ALL" = 1 ] && [ -n "$reads" ] && show_reads=1

if [ -z "$missing" ] && [ -z "$done_now" ] && [ "$show_reads" = 0 ] && [ "$ALL" = 0 ] && [ -z "$boards" ]; then
  exit 0
fi

if [ -n "$missing" ] || [ -n "$done_now" ] || [ "$show_reads" = 1 ] || [ "$ALL" = 1 ]; then
  echo "🧩 この共有リポを手元で使う準備 (tools/collaborator-check。 設定 = .collaborator-check.conf)"
  [ "$show_reads" = 1 ] && [ "$ALL" = 0 ] && echo "  この clone で初めての session:"
  [ "$show_reads" = 1 ] && printf '%s\n' "${reads#?}"
  [ -n "$done_now" ] && printf '%s\n' "${done_now#?}"
  [ -n "$missing" ] && printf '%s\n' "${missing#?}"
  [ "$ALL" = 1 ] && [ -n "$ok" ] && printf '%s\n' "${ok#?}"
  if [ -n "$missing" ] || [ -n "$done_now" ] || [ "$show_reads" = 1 ]; then
    echo "  → agent はこの block を user に 1 項目 1 行で伝える (❌ は直すまで毎回出る)"
  fi
fi
if [ -n "$boards" ]; then
  printf '%s\n' "${boards#?}"
  echo "  → 自分 (この session) 宛ての依頼・検収があれば、 最初の返答で user に 1 行で伝え、 作業の始めに inbox --sync で読む"
fi

if [ "$FIRST" = 1 ] && [ "$ALL" = 0 ] && [ -n "$SEEN" ]; then
  : > "$SEEN" 2>/dev/null || true
fi
exit 0
