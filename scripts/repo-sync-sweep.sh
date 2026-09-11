#!/usr/bin/env bash
# repo-sync-sweep.sh — <root>/*/ の git repo を並列 fetch し behind-only は自動で最新化する engine (tracked-dirty は stash→ff-merge→pop、 並列起動は repo 単位の lock で排他、 手当ての要る repo は 1 行ずつ返す)
#
# 呼び出し側 = SessionStart hook (個人層) / 手動の一括 pull。 整形と surface は呼び出し側が持つ
# (本 engine は tab 区切りの行を返すだけ)。 test = scripts/repo-sync-sweep.test.sh
#
# 使い方:
#   repo-sync-sweep.sh [--root DIR] [--all]
#
# 出力 (stdout、 1 行 = "<種別><TAB><本文>"、 該当が無ければ何も出さない):
#   P  自動で最新化した
#   A  手当てが要る (diverged / ff 失敗 / fetch 未完了 / pop conflict / stash の空振り 等)
#   U  未 push の local commit (behind==0 ∧ ahead>0。 push はしない)
#   L  並列の sweep と重なった (lock 中で skip した / 古い lock を除去した)
#   --all の時だけ: S = 最新で何もしていない / N = upstream 未設定
# exit は常に 0 (= fail-open。 呼び出し側は A 行の有無で判断する)。
#
# 射程 = <root>/*/.git の 1 階層 (既定 root = $CLAUDE_SYNC_SWEEP_ROOT か ~/Claude)。
# upstream の無い repo は触らない。
#
# 状態ごとの処理:
#   behind>0 ∧ ahead==0 ∧ tracked-clean  → merge --ff-only @{u}
#   behind>0 ∧ ahead==0 ∧ tracked-dirty  → stash → merge --ff-only → pop。 merge 失敗なら pop して戻す /
#                                           pop conflict は自動解決せず所在と手順を出す / merge・rebase
#                                           進行中は触らない / CLAUDE_SYNC_AUTOSTASH=0 で A 行のみに戻す
#   behind>0 ∧ ahead>0 (diverged)       → A 行のみ (勝手な merge commit は作らない)
#   behind==0 ∧ ahead>0                  → U 行のみ
#   fetch が終わらなかった repo         → A 行 (behind 判定が古い ref 由来で当てにならない)
#
# 並列に起動されたときの安全 (規約の正本 = conventions/hook-authoring.md#cross-session-hook-concurrency、
# conventions/multi-session-coordination.md#stash-push-noop / #concurrent-fetch-ref-lock / #pull-fetch-head-race):
#   - HEAD / tree を書き換える区間だけを repo 単位の mkdir lock (<git common dir>/claude-sync-sweep.lock)
#     の内側で行い、 取った後に状態を読み直す。 lock 中の repo は待たずに skip して L 行
#   - 古い lock (holder の pid 死亡 / 取得から LOCK_STALE 秒超) は rename で除去して取り直し、 L 行
#   - stash は message の固有 tag で自分のものか確かめ、 sha から引いた ref で pop する。
#     「stash に残っている」 は stash list で確かめてから言う
#   - 同時 fetch の ref lock 衝突 (timeout 以外の失敗) は 1 秒おいて 1 回再試行
#   - fetch の成功を marker に残して不在で検出 (= 打ち切りを「同期済み」 に化けさせない)
#   - GIT_TERMINAL_PROMPT=0 + ssh BatchMode + fetch 8 秒 + 全体 25 秒の watchdog で hang しない
#
# env:
#   CLAUDE_SYNC_SWEEP_ROOT         --root の既定
#   CLAUDE_SYNC_AUTOSTASH=0        tracked-dirty を stash しない (A 行のみ)
#   CLAUDE_SYNC_SWEEP_LOCK_STALE   lock を古いとみなす秒数 (既定 300)
#   CLAUDE_SYNC_SWEEP_TEST=1 の時だけ効く (test で並走の窓を決定的に開ける):
#     CLAUDE_SYNC_SWEEP_TEST_HOLD_PRE / _POST  stash push の直前 / 直後に lock を持ったまま止まる秒数

# fail-open 最優先のため set -e は使わない (= 途中の error で呼び出し側を止めない)。

ROOT="${CLAUDE_SYNC_SWEEP_ROOT:-$HOME/Claude}"
_ALL=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      if [ "$#" -lt 2 ]; then printf 'A\trepo-sync-sweep: --root に値が無い\n'; exit 0; fi
      ROOT="$2"; shift 2 ;;
    --root=*) ROOT="${1#--root=}"; shift ;;
    --all) _ALL=1; shift ;;
    -h|--help) sed -n '2,/^$/{s/^# \{0,1\}//;p;}' "$0"; exit 0 ;;
    *) printf 'A\trepo-sync-sweep: 不明な引数 %s (--help)\n' "$1"; exit 0 ;;
  esac
done

[ -d "$ROOT" ] || exit 0
command -v git >/dev/null 2>&1 || exit 0

# 手順の表示用 (= $HOME 配下なら ~ で書く)
_DISP="$ROOT"
case "$ROOT" in "$HOME"/*) _DISP="~${ROOT#"$HOME"}" ;; esac

export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=5}"

# timeout binary 解決 (= macOS は GNU timeout 不在のことがある、 coreutils の gtimeout を
# fallback、 どちらも無ければ素通し実行)
_TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then _TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then _TIMEOUT_BIN="gtimeout"; fi
_t() {  # _t <seconds> <cmd...>
  local d="$1"; shift
  if [ -n "$_TIMEOUT_BIN" ]; then "$_TIMEOUT_BIN" "$d" "$@"; else "$@"; fi
}

# ---------- 1. 並列 fetch (= 全体 watchdog で hang を防ぐ) ----------
# fetch の成功だけを marker file に残す。 per-fetch timeout と全体 watchdog の kill を黙って
# 潰すと、 fetch が終わらなかった repo は remote ref が古いまま分類に渡り behind=0 = 「同期済み」
# に見える (= pull されず報告もされない)。 kill された子は自分で marker を書けないので、
# 「失敗を記録」 でなく「成功を記録 → 不在で検出」 の向きにする。
_FETCHOK="$(mktemp -d 2>/dev/null)" || _FETCHOK=""
# 終了時の後始末 = 一時 dir + この process が取った repo lock の解放。 lock は classify の
# subshell が取るが subshell には EXIT trap が継がれないので、 取った path を $_FETCHOK/.locks に
# 書いておき、 ここで owner の pid が自分のものだけ消す (SIGKILL だけは残るので stale 判定で拾う)。
_cleanup() {
  if [ -n "$_FETCHOK" ] && [ -f "$_FETCHOK/.locks" ]; then
    while IFS= read -r _lk; do
      case "$(cat "$_lk/owner" 2>/dev/null)" in "$$ "*) rm -rf "$_lk" 2>/dev/null ;; esac
    done < "$_FETCHOK/.locks"
  fi
  [ -n "$_FETCHOK" ] && rm -rf "$_FETCHOK" 2>/dev/null
  return 0
}
trap _cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
for gd in "$ROOT"/*/.git; do
  [ -e "$gd" ] || continue
  repo="${gd%/.git}"
  (
    cd "$repo" 2>/dev/null || exit 0
    git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1 || exit 0
    # 同じ repo を 2 process が同時に fetch すると remote-tracking ref の更新 lock が衝突して
    # 片方が即失敗する (multi-session-coordination.md#concurrent-fetch-ref-lock)。 timeout 以外の
    # 失敗は 1 秒おいて 1 回だけ取り直す (= 相手の fetch はその間に終わっている)。
    _ok=0
    if _t 8 git fetch -q 2>/dev/null; then _ok=1
    else
      case "$?" in
        124|137|143) : ;;
        *) sleep 1; _t 8 git fetch -q 2>/dev/null && _ok=1 ;;
      esac
    fi
    [ "$_ok" = 1 ] && [ -n "$_FETCHOK" ] && : > "$_FETCHOK/$(basename "$repo")" 2>/dev/null
  ) &
done

# 全 fetch を待つが、 timeout 不在環境でも total を bound する watchdog 付き
_deadline=$(( $(date +%s) + 25 ))
while :; do
  _running="$(jobs -rp 2>/dev/null | wc -l | tr -d ' ')"
  [ "${_running:-0}" -eq 0 ] && break
  if [ "$(date +%s)" -ge "$_deadline" ]; then
    # straggler を kill して先へ (= その repo は marker 不在で「fetch 未完了」 と報告される)
    kill $(jobs -rp 2>/dev/null) 2>/dev/null || true
    break
  fi
  sleep 0.3
done

# ---------- 2. 分類 + 安全な自動最新化 ----------
# 並走ロック: lock = <git common dir>/claude-sync-sweep.lock (= stash は worktree 間で共有なので
# common dir)。 中身 owner = "<pid> <epoch> <乱数>"。 持ち主の pid が死んでいるか、 取得から
# $_LOCK_STALE 秒を超えたら古い lock とみなして除去し取り直す (除去した事実も L 行で出す)。
_LOCK_STALE="${CLAUDE_SYNC_SWEEP_LOCK_STALE:-300}"
_LOCK_MINE=""; _LOCK_HOLDER=""; _LOCK_BROKE=""

_lock_take() {  # mkdir に成功した直後に呼ぶ: owner を書き、 §1 の後始末 list に載せる
  _LOCK_MINE="$$ $(date +%s) $RANDOM"
  printf '%s\n' "$_LOCK_MINE" > "$1/owner" 2>/dev/null
  [ -n "$_FETCHOK" ] && printf '%s\n' "$1" >> "$_FETCHOK/.locks" 2>/dev/null
  return 0
}
_lock_acquire() {  # _lock_acquire <lockdir>: 0 = 取得 / 1 = 生きた holder が居る ($_LOCK_HOLDER)
  local lk="$1" owner opid otime now stale=0 tmp
  _LOCK_MINE=""; _LOCK_HOLDER=""; _LOCK_BROKE=""
  if mkdir "$lk" 2>/dev/null; then _lock_take "$lk"; return 0; fi
  owner="$(cat "$lk/owner" 2>/dev/null)"
  if [ -n "$owner" ]; then
    opid="$(printf '%s\n' "$owner" | awk '{print $1}')"
    otime="$(printf '%s\n' "$owner" | awk '{print $2}')"
    now="$(date +%s)"
    if ! kill -0 "$opid" 2>/dev/null; then
      stale=1
    else
      case "$otime" in
        ''|*[!0-9]*) stale=1 ;;
        *) [ "$(( now - otime ))" -gt "$_LOCK_STALE" ] 2>/dev/null && stale=1 ;;
      esac
    fi
  else
    # owner 未記入 = mkdir 直後 (= 生きている) か書く前に落ちた残骸。 5 分より古い時だけ残骸扱い
    [ -n "$(find "$lk" -maxdepth 0 -mmin +5 2>/dev/null)" ] && stale=1
  fi
  if [ "$stale" -eq 1 ]; then
    # 除去は rename で原子的に行い、 動かした中身が「古いと判定した owner」 と一致した時だけ消す
    # (= 判定から除去までの間に別 process が取り直した新しい lock を消さない。 不一致なら戻して譲る)
    tmp="$lk.stale.$$.$RANDOM"
    if mv "$lk" "$tmp" 2>/dev/null; then
      if [ "$(cat "$tmp/owner" 2>/dev/null)" = "$owner" ]; then
        rm -rf "$tmp" 2>/dev/null
        if mkdir "$lk" 2>/dev/null; then
          _lock_take "$lk"; _LOCK_BROKE="${owner:-owner 未記入}"; return 0
        fi
      else
        mv "$tmp" "$lk" 2>/dev/null
      fi
    fi
    owner="$(cat "$lk/owner" 2>/dev/null)"
  fi
  _LOCK_HOLDER="${owner:-owner 未記入}"
  return 1
}
_lock_release() {  # 自分の owner のままの時だけ消す (= 除去されて別 process が取り直した lock は消さない)
  [ -n "$_LOCK_MINE" ] && [ "$(cat "$1/owner" 2>/dev/null)" = "$_LOCK_MINE" ] && rm -rf "$1" 2>/dev/null
  _LOCK_MINE=""
  return 0
}
_lock_desc() {  # owner 文字列 → "pid N、 M 秒前に取得"
  local p t
  p="$(printf '%s\n' "$1" | awk '{print $1}')"; t="$(printf '%s\n' "$1" | awk '{print $2}')"
  case "$t" in
    ''|*[!0-9]*) printf '%s' "$1" ;;
    *) printf 'pid %s、 %s 秒前に取得' "$p" "$(( $(date +%s) - t ))" ;;
  esac
}
_stash_ref_of() {  # stash の sha → stash@{N} (stash list に無ければ空)
  git stash list --format='%gd %H' 2>/dev/null | awk -v s="$1" '$2==s{print $1; exit}'
}
_stash_whereabouts() {  # $1 = repo 名, $2 = stash の sha → stash list で確かめた所在と次の手順 (1 行)
  local r s7
  r="$(_stash_ref_of "$2")"; s7="$(git rev-parse --short "$2" 2>/dev/null)"
  if [ -n "$r" ]; then
    printf '**未 commit の変更は stash に残っている (確認済: %s = %s)** → cd %s/%s && git status  (解消したら git stash drop %s。 unmerged path があると git checkout -- . は効かない — 作業前に戻すなら git reset --hard、 変更の中身は git stash show -p %s)' \
      "$r" "$s7" "$_DISP" "$1" "$r" "$s7"
  else
    printf 'stash した変更 (%s) は **stash list に無い = stash には残っていない** (別 process が pop / drop した可能性) → 中身 = git -C %s/%s stash show -p %s / worktree に在るか = cd %s/%s && git diff %s -- $(git stash show --name-only %s)  (空なら同じ変更が在る。 upstream も同じ file を変えていれば差分が出る) / 戻すなら git stash apply %s / sha を見失ったら git fsck --unreachable --no-reflogs の commit を git log -1 --format=%%s で見て "sync-sweep auto" を探す' \
      "$s7" "$_DISP" "$1" "$s7" "$_DISP" "$1" "$s7" "$s7" "$s7"
  fi
}
_test_hold() {  # test 専用: 並走の窓を決定的に開ける (CLAUDE_SYNC_SWEEP_TEST=1 の時だけ効く)
  [ "${CLAUDE_SYNC_SWEEP_TEST:-0}" = "1" ] && [ -n "${1:-}" ] && sleep "$1"
  return 0
}

classify() {
  cd "$1" 2>/dev/null || return 0
  local name up behind ahead dirty gcd lk
  name="$(basename "$1")"
  up="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" || up=""
  if [ -z "$up" ]; then
    [ "$_ALL" = 1 ] && printf 'N\t%s: upstream 未設定 (触らない)\n' "$name"
    return 0
  fi
  # fetch が完了しなかった repo は behind 判定そのものが古い ref 由来で当てにならない。
  # 「同期済み」 と誤読させないため専用行で報告する (= §1 の marker の消費側)。
  if [ -n "$_FETCHOK" ] && [ ! -e "$_FETCHOK/$name" ]; then
    printf 'A\t%s: fetch 未完了 (8s timeout / 全体 watchdog で打ち切り、 または再試行しても失敗) — behind 判定は当てにならない → cd %s/%s && git fetch && git merge --ff-only @{u}\n' \
      "$name" "$_DISP" "$name"
    return 0
  fi
  behind="$(git rev-list --count HEAD..@{u} 2>/dev/null)"; behind="${behind:-0}"
  ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null)"; ahead="${ahead:-0}"
  dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"; dirty="${dirty:-0}"
  if ! [ "$behind" -gt 0 ] 2>/dev/null; then
    # behind==0: ahead-only (= 未 push の local commit) だけ報告、 それ以外は沈黙 (--all なら S 行)
    if [ "$ahead" -gt 0 ] 2>/dev/null; then
      printf 'U\t%s: ahead=%s dirty=%s → cd %s/%s && git log --oneline @{u}..  (diff を読む → leak grep → git push)\n' \
        "$name" "$ahead" "$dirty" "$_DISP" "$name"
    elif [ "$_ALL" = 1 ]; then
      printf 'S\t%s (%s)\n' "$name" "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    fi
    return 0
  fi
  if [ "$ahead" -gt 0 ]; then
    printf 'A\t%s: behind=%s ahead=%s dirty=%s (= diverged、 作業前に手動解決)\n' \
      "$name" "$behind" "$ahead" "$dirty"
    return 0
  fi

  # ---- ここから HEAD / tree を書き換える = 並走ロックの内側でだけ行う ----
  gcd="$(git rev-parse --git-common-dir 2>/dev/null)" || gcd=""
  gcd="$( [ -n "$gcd" ] && cd "$gcd" 2>/dev/null && pwd)" || gcd=""
  if [ -z "$gcd" ]; then
    printf 'A\t%s: behind=%s だが git dir を解決できず lock を取れない (= 触らない、 手動 pull)\n' "$name" "$behind"
    return 0
  fi
  lk="$gcd/claude-sync-sweep.lock"
  if ! _lock_acquire "$lk"; then
    printf 'L\t%s: 別の sync-sweep (%s) がこの repo を処理中 → skip (結果はそちらに出る。 確認 = git -C %s/%s status -sb)\n' \
      "$name" "$(_lock_desc "$_LOCK_HOLDER")" "$_DISP" "$name"
    return 0
  fi
  if [ -n "$_LOCK_BROKE" ]; then
    printf 'L\t%s: 前回の sync-sweep が残した古い lock (%s) を除去して処理した\n' \
      "$name" "$(_lock_desc "$_LOCK_BROKE")"
  fi
  _pull_locked "$name"
  _lock_release "$lk"
  return 0
}

# lock の内側。 取るまでの間に別 sweep / 別 process が状態を変えているかもしれないので読み直す。
_pull_locked() {
  local name="$1" behind ahead dirty tracked_dirty=0 had_staged=0 tag stash ref
  behind="$(git rev-list --count HEAD..@{u} 2>/dev/null)"; behind="${behind:-0}"
  ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null)"; ahead="${ahead:-0}"
  dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"; dirty="${dirty:-0}"
  [ "$behind" -gt 0 ] 2>/dev/null || return 0     # lock を取るまでに誰かが最新化済 = 沈黙
  if [ "$ahead" -gt 0 ]; then
    printf 'A\t%s: behind=%s ahead=%s dirty=%s (= diverged、 作業前に手動解決)\n' \
      "$name" "$behind" "$ahead" "$dirty"
    return 0
  fi

  # tracked dirty (= stash が要る変更) と untracked のみ (= ff に影響しない) を区別する。
  # `git status --porcelain` の行数は untracked も数えるので判定には使わない (= untracked のみを
  # 「stash 要」 と誤判定すると pop が空振りする)。
  if ! git diff --cached --quiet 2>/dev/null; then tracked_dirty=1; had_staged=1; fi
  if ! git diff --quiet 2>/dev/null; then tracked_dirty=1; fi

  if [ "$tracked_dirty" -eq 0 ]; then
    # behind-only & tracked-clean = fast-forward 保証 (incoming commit が untracked と同名 file を
    # 足す時だけ失敗する → A 行)。 `git pull` でなく `merge --ff-only @{u}`: pull は fetch 結果を
    # .git/FETCH_HEAD 経由で読み、 並列の fetch と重なると書き換えられうる (#pull-fetch-head-race)。
    if _t 20 git merge --ff-only -q '@{u}' >/dev/null 2>&1; then
      printf 'P\t%s (was behind %s)\n' "$name" "$behind"
    else
      printf 'A\t%s: behind=%s、 ff-merge 失敗 (= 作業前に手動 pull)\n' "$name" "$behind"
    fi
    return 0
  fi

  # ---- behind-only ∧ tracked-dirty: stash → ff-merge → pop ----
  # 別 session の未 commit 作業に触れるので: merge 失敗時は必ず pop して元に戻す / pop conflict は
  # 自動解決せず所在と手順を出す / kill switch = CLAUDE_SYNC_AUTOSTASH=0
  if [ "${CLAUDE_SYNC_AUTOSTASH:-1}" = "0" ]; then
    printf 'A\t%s: behind=%s dirty=%s (= auto-stash 無効化中、 手動解決)\n' "$name" "$behind" "$dirty"
    return 0
  fi
  # merge / rebase 進行中の repo は触らない (= 中断状態を壊さない)
  if [ -e "$(git rev-parse --git-dir 2>/dev/null)/MERGE_HEAD" ] \
     || [ -d "$(git rev-parse --git-dir 2>/dev/null)/rebase-merge" ] \
     || [ -d "$(git rev-parse --git-dir 2>/dev/null)/rebase-apply" ]; then
    printf 'A\t%s: behind=%s だが merge/rebase 進行中 (= 触らない、 手動解決)\n' "$name" "$behind"
    return 0
  fi
  tag="sync-sweep auto $(date +%Y-%m-%dT%H:%M:%S) pid=$$ r=$RANDOM"
  _test_hold "${CLAUDE_SYNC_SWEEP_TEST_HOLD_PRE:-}"
  if ! _t 20 git stash push -q -m "$tag" >/dev/null 2>&1; then
    printf 'A\t%s: behind=%s dirty=%s、 stash 失敗 (= 手動解決)\n' "$name" "$behind" "$dirty"
    return 0
  fi
  # stash push は stash するものが無くても rc=0 で何も作らない。 refs/stash の先頭が自分の tag で
  # なければ自分の stash は無い = この先で pop すると他人の stash を pop する (#stash-push-noop)。
  stash="$(git rev-parse -q --verify refs/stash 2>/dev/null)" || stash=""
  case "$(git log -1 --format=%s "$stash" 2>/dev/null)" in
    *"$tag") : ;;
    *)
      printf 'A\t%s: behind=%s だが stash push が何も作らなかった (= 直前に別 process が変更を動かした可能性) → 触らずに中止 (確認 = git -C %s/%s status -sb; git -C %s/%s stash list)\n' \
        "$name" "$behind" "$_DISP" "$name" "$_DISP" "$name"
      return 0 ;;
  esac
  _test_hold "${CLAUDE_SYNC_SWEEP_TEST_HOLD_POST:-}"
  if ! _t 20 git merge --ff-only -q '@{u}' >/dev/null 2>&1; then
    # 元に戻す (= 触る前の状態が既定)。 pop は自分の stash を sha で特定して行う
    ref="$(_stash_ref_of "$stash")"
    if [ -n "$ref" ] && { { [ "$had_staged" -eq 1 ] && _t 20 git stash pop --index -q "$ref" >/dev/null 2>&1; } \
                          || _t 20 git stash pop -q "$ref" >/dev/null 2>&1; }; then
      printf 'A\t%s: behind=%s、 ff-merge 失敗のため stash を戻した (= 手動解決)\n' "$name" "$behind"
    else
      printf 'A\t%s: behind=%s、 ff-merge 失敗、 stash も戻せなかった。 %s\n' \
        "$name" "$behind" "$(_stash_whereabouts "$name" "$stash")"
    fi
    return 0
  fi
  # 自分の stash が merge の間に stash list から消えた (= 別 process が pop / drop した)。 ここで
  # 素の `git stash pop` をすると他人の stash を pop するので、 pop せずに所在を報告する。
  ref="$(_stash_ref_of "$stash")"
  if [ -z "$ref" ]; then
    printf 'A\t%s: pull は成功したが、 %s\n' "$name" "$(_stash_whereabouts "$name" "$stash")"
    return 0
  fi
  # staged だった変更は `git stash pop` 単独だと unstaged に落ちる (= 並列 session の staging window
  # を黙って崩す)。 まず --index で index ごと戻し、 失敗したら平の pop に落としてその旨を書く。
  if [ "$had_staged" -eq 1 ] && _t 20 git stash pop --index -q "$ref" >/dev/null 2>&1; then
    printf 'P\t%s (was behind %s、 未 commit の変更を stash→pop で保全 [staged も index ごと復元])\n' "$name" "$behind"
  elif _t 20 git stash pop -q "$ref" >/dev/null 2>&1; then
    if [ "$had_staged" -eq 1 ]; then
      printf 'P\t%s (was behind %s、 変更は保全されたが **staged だった分は unstaged に落ちた** = 必要なら git add し直す)\n' "$name" "$behind"
    else
      printf 'P\t%s (was behind %s、 未 commit の変更を stash→pop で保全)\n' "$name" "$behind"
    fi
  else
    # pop 失敗: conflict なら git は stash entry を残すが、 「残っている」 と言う前に stash list で
    # 確かめる (= 空振りの pop を conflict と読み、 無い stash を「残っている」 と誤報した実例がある)。
    if [ -n "$(_stash_ref_of "$stash")" ]; then
      printf 'A\t%s: pull は成功したが stash pop が conflict。 %s\n' "$name" "$(_stash_whereabouts "$name" "$stash")"
    else
      printf 'A\t%s: pull は成功したが stash pop が失敗。 %s\n' "$name" "$(_stash_whereabouts "$name" "$stash")"
    fi
  fi
}

for gd in "$ROOT"/*/.git; do
  [ -e "$gd" ] || continue
  ( classify "${gd%/.git}" )
done
exit 0
