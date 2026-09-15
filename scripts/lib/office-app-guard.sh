#!/usr/bin/env bash
# office-app-guard.sh — Office (Excel / Word / PowerPoint) を osascript で駆動する前後の安全な reset + 背景起動 (user が開いた文書を持つ app は quit も kill もしない・前面に出さない、 sourceable lib + CLI、 office-automation.md#office-app-reset-guard)
#
# WHY
#   旧 reset は毎回 `tell application "Microsoft Excel" to quit` + sleep (Word は pkill) だった。
#   user が Excel で文書を開いていると、 未保存なら保存 dialog が出て script が止まり、 kill なら
#   未保存の作業ごと消える。 さらに `activate` / Finder の `open` で毎回 app が前面に出て user の手を止める。
#   → 「app に今開いている文書を聞き、 staging root の外の文書 (= user のもの) が 1 つでもあれば quit しない」
#     + 「起動は open -g (前面に出さない)、 activate しない、 奪ってしまった前面は元の app に返す」。
#
# API (source して使う。 bash 3.2 compatible。 <app> = excel | word | powerpoint)
#   office_app_state <app>             … echo `not-running` / `clear` / `user-docs <n>` / `unknown`
#                                        (clear = 開いている文書が staging root の中の copy と、 保存済みの起動用 book だけ)
#   office_app_documents <app>         … 1 文書 1 行 "<saved>\t<path または未保存文書の名前>"。 rc=1 = 応答なし、 rc=3 = 未起動
#   office_app_reset <app>             … clear の時だけ staged 文書を閉じて quit + 終了待ち。 それ以外は触らず stderr に notice。
#                                        結果 = OFFICE_APP_RESET (not-running / quit / quit-slow / skipped-user-docs / skipped-dialog / skipped-unknown)
#   office_app_launch_background <app> … 未起動なら `open -g -b` で背景起動 + 応答待ち。 自分で起動したら OFFICE_APP_LAUNCHED=1
#   office_app_release <app>           … OFFICE_APP_LAUNCHED=1 (= この実行が起動した) の時だけ、 staged 文書を閉じて
#                                        user の文書が無ければ quit (= 起動前の状態に戻す)
#   office_app_close_ours <app> [path...] … staging root の中の文書 (+ 渡した path の文書) だけを保存せず閉じる
#   office_app_has_path <app> <path>   … その path の文書が既に開いていれば rc=0 (Excel は同名の book も rc=0 = 同名は 2 つ開けない)
#   office_app_failure_hint <app>      … 失敗時の案内 (reset を省いた理由に応じて) を stderr へ
#   office_front_remember              … 前面 app の path を OFFICE_FRONT_APP に
#   office_front_restore <bundle名>    … 今の前面が <bundle名> (例 "Microsoft Excel.app") で、 覚えた前面が別 app なら返す
#
# CLI (python driver 用。 source 済みの関数と同じ実装)
#   bash office-app-guard.sh state|documents|reset|launch <app>
#   bash office-app-guard.sh release <app> <launched 0|1>
#   bash office-app-guard.sh has-path <app> <path>
#   bash office-app-guard.sh close-ours <app> [path...]
#   bash office-app-guard.sh front-remember            → 前面 app の path を stdout
#   bash office-app-guard.sh front-restore <remembered> <bundle名>
#
# 制御 (env)
#   CLAUDE_OFFICE_APP_WAIT=秒         … quit 後の終了待ち上限 (default 20)
#   CLAUDE_OFFICE_APP_LAUNCH_WAIT=秒  … 背景起動後の応答待ち上限 (default 120 = 遅いマシンの cold start)
#   CLAUDE_OFFICE_APP_QUERY_TIMEOUT=秒 … 文書一覧の問い合わせ 1 回の AppleEvent timeout (default 15)
#
# 絶対にしないこと: killall / pkill / `quit saving no` / staging root の外の文書への close・save / activate。
#   quit は「自分の staged 文書を閉じた後、 同じ osascript の中で文書数を数え直して 0 の時だけ」 plain quit で撃つ
#   (= 間に user が文書を開いても quit しない。 万一すり抜けても saving no ではないので保存 dialog が作業を守る)。

_OFFICE_APP_GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! type office_staging_root >/dev/null 2>&1; then
    # shellcheck source=office-staging.sh
    . "$_OFFICE_APP_GUARD_DIR/office-staging.sh"
fi

_office_app_id() {
    case "$1" in
        excel|Excel) echo com.microsoft.Excel ;;
        word|Word) echo com.microsoft.Word ;;
        powerpoint|PowerPoint|ppt) echo com.microsoft.Powerpoint ;;
        *) echo "office-app-guard: unknown app: $1 (excel|word|powerpoint)" >&2; return 2 ;;
    esac
}
_office_app_class() {   # 文書 class の単数形 (AppleScript の `workbook i` 等)
    case "$1" in
        excel|Excel) echo workbook ;;
        word|Word) echo document ;;
        *) echo presentation ;;
    esac
}
_office_app_bundle() {
    case "$1" in
        excel|Excel) echo "Microsoft Excel.app" ;;
        word|Word) echo "Microsoft Word.app" ;;
        *) echo "Microsoft PowerPoint.app" ;;
    esac
}
_office_app_label() { _office_app_bundle "$1" | sed 's/\.app$//'; }

# 比較用の正規化: 大文字小文字を無視 (macOS 既定 FS) + /private/{tmp,var,etc} と /{tmp,var,etc} を同一視
# (Excel は /private/tmp/x を /tmp/x と答える = 実測。 揃えないと自分が開いた文書を閉じ損ねる)
_office_lower() { LC_ALL=C tr 'A-Z' 'a-z' | sed -E 's#^/private/(tmp|var|etc)(/|$)#/\1\2#'; }

# 「自分の文書」 と見なす root (= office_staging.py staging_roots_for_match と同じ: default root + override。 mkdir しない)
_office_app_roots() {
    local home="${HOME:-}" r
    for r in "$home/$OFFICE_STAGING_GROUP_CONTAINER/$OFFICE_STAGING_ROOT_NAME" "${CLAUDE_OFFICE_STAGING_DIR:-}"; do
        [ -n "$r" ] || continue
        printf '%s\n' "${r%/}"   # /private の有無は _office_lower が揃える
    done
}
# Excel の起動用 book (PERSONAL.XLSB 等) の置き場。 保存済みなら quit を妨げないので user の文書に数えない
_office_app_startup_prefix() { printf '%s/%s/User Content/Startup/\n' "${HOME:-}" "$OFFICE_STAGING_GROUP_CONTAINER"; }

_office_path_is_ours() {   # $1 = 文書の path。 staging root の内側なら rc=0 (大文字小文字は区別しない)
    local p r
    case "$1" in /*) ;; *) return 1 ;; esac
    p="$(printf '%s' "$1" | _office_lower)"
    while IFS= read -r r; do
        [ -n "$r" ] || continue
        r="$(printf '%s' "$r" | _office_lower)"
        case "$p" in "$r"/?*) return 0 ;; esac
    done <<EOF
$(_office_app_roots)
EOF
    return 1
}

# stdin = office_app_documents の出力 → echo `clear` / `user-docs <n>`
office_docs_verdict() {
    local line sv fn n=0 startup
    startup="$(_office_app_startup_prefix | _office_lower)"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        sv="${line%%	*}"; fn="${line#*	}"
        _office_path_is_ours "$fn" && continue
        if [ "$sv" = "true" ]; then
            case "$(printf '%s' "$fn" | _office_lower)" in "$startup"?*) continue ;; esac
        fi
        n=$((n + 1))
    done
    if [ "$n" -eq 0 ]; then echo clear; else echo "user-docs $n"; fi
}

office_app_running() {
    local id
    id="$(_office_app_id "$1")" || return 2
    [ "$(osascript -e "application id \"$id\" is running" 2>/dev/null)" = "true" ]
}

office_app_documents() {
    local app="$1" id cls tmo out
    id="$(_office_app_id "$app")" || return 2
    cls="$(_office_app_class "$app")"
    tmo="${CLAUDE_OFFICE_APP_QUERY_TIMEOUT:-15}"
    # full name は app に聞き、 HFS → POSIX の変換は tell の外で (scripting addition を sandbox app に送らない)
    out="$(osascript - <<AS 2>/dev/null
-- office-app-guard:documents $app
on run argv
  if not (application id "$id" is running) then return "not-running"
  set names to {}
  set saves to {}
  with timeout of $tmo seconds
    tell application id "$id"
      repeat with i from 1 to (count of ${cls}s)
        set fn to ""
        try
          set fn to (full name of $cls i) as text
        end try
        set sv to "unknown"
        try
          set sv to (saved of $cls i) as text
        end try
        set end of names to fn
        set end of saves to sv
      end repeat
    end tell
  end timeout
  set out to "ok"
  repeat with i from 1 to (count of names)
    set fn to item i of names
    if fn does not start with "/" and fn contains ":" then
      try
        set fn to POSIX path of fn
      end try
    end if
    set out to out & linefeed & (item i of saves) & tab & fn
  end repeat
  return out
end run
AS
)" || return 1
    case "$out" in
        not-running) return 3 ;;
        ok) return 0 ;;
        ok*) printf '%s\n' "${out#ok
}"; return 0 ;;
        *) return 1 ;;
    esac
}

office_app_state() {
    local docs rc
    office_app_running "$1" || { [ $? -eq 2 ] && return 2; echo not-running; return 0; }
    rc=0; docs="$(office_app_documents "$1")" || rc=$?   # set -e の呼び出し側でも落ちない形
    case "$rc" in
        0) printf '%s\n' "$docs" | office_docs_verdict ;;
        3) echo not-running ;;
        *) echo unknown ;;
    esac
}

office_app_has_path() {
    local app="$1" want docs line fn base
    want="$(printf '%s' "$2" | _office_lower)"
    base="$(basename "$2" | _office_lower)"
    office_app_running "$app" || return 1
    docs="$(office_app_documents "$app")" || return 1
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        fn="$(printf '%s' "${line#*	}" | _office_lower)"
        [ "$fn" = "$want" ] && return 0
        case "$app" in excel|Excel) [ "$(basename "$fn")" = "$base" ] && return 0 ;; esac
    done <<EOF
$docs
EOF
    return 1
}

# staged 文書 (+ 引数で渡した path = in-place で自分が開いた文書) だけを閉じる (保存しない)。
# 閉じる対象は bash 側で path を確定して argv で渡す = user の文書は構造的に対象にならない
office_app_close_ours() {
    local app="$1" id cls docs line fn want x
    local ours=()
    id="$(_office_app_id "$app")" || return 2
    shift
    cls="$(_office_app_class "$app")"
    docs="$(office_app_documents "$app")" || return 0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        fn="${line#*	}"
        if _office_path_is_ours "$fn"; then ours+=("$fn"); continue; fi
        want="$(printf '%s' "$fn" | _office_lower)"
        for x in "$@"; do
            [ "$(printf '%s' "$x" | _office_lower)" = "$want" ] && { ours+=("$fn"); break; }
        done
    done <<EOF
$docs
EOF
    [ "${#ours[@]}" -gt 0 ] || return 0
    osascript - "${ours[@]}" >/dev/null 2>&1 <<AS || true
-- office-app-guard:close-ours $app
on run argv
  if not (application id "$id" is running) then return 0
  with timeout of ${CLAUDE_OFFICE_APP_QUERY_TIMEOUT:-15} seconds
    tell application id "$id" to set n to (count of ${cls}s)
    repeat with i from n to 1 by -1
      set fn to ""
      try
        tell application id "$id" to set fn to (full name of $cls i) as text
      end try
      if fn does not start with "/" and fn contains ":" then
        try
          set fn to POSIX path of fn
        end try
      end if
      if argv contains {fn} then
        tell application id "$id" to close $cls i saving no
      end if
    end repeat
  end timeout
  return 0
end run
AS
    return 0
}

# 文書を数え直して、 保存済みの起動用 book 以外が 0 の時だけ quit (同じ tell の中で = 数えてから quit までに隙間を作らない)
_office_app_quit_if_empty() {
    local app="$1" id cls out
    id="$(_office_app_id "$app")" || return 2
    cls="$(_office_app_class "$app")"
    out="$(osascript - "$(_office_app_startup_prefix)" 2>/dev/null <<AS
-- office-app-guard:quit-if-empty $app
on run argv
  set startupPrefix to item 1 of argv
  if not (application id "$id" is running) then return "not-running"
  with timeout of ${CLAUDE_OFFICE_APP_QUERY_TIMEOUT:-15} seconds
    tell application id "$id"
      set blocking to 0
      repeat with i from 1 to (count of ${cls}s)
        set fn to ""
        set sv to false
        try
          set fn to (full name of $cls i) as text
        end try
        try
          set sv to (saved of $cls i)
        end try
        if not (sv is true and fn starts with startupPrefix) then set blocking to blocking + 1
      end repeat
      if blocking is 0 then
        try
          quit
        on error errMsg number errNum
          if errNum is -128 then return "canceled"   -- app 側の dialog (開く panel・警告) が quit を取り消した
        end try
        return "quit"
      end if
      return "blocked " & blocking
    end tell
  end timeout
end run
AS
)" || out=unknown   # -609 等で osascript 自体が落ちた = 状態不明
    printf '%s\n' "$out"
}

_office_app_wait_exit() {
    local app="$1" ticks=0 max
    max=$(( ${CLAUDE_OFFICE_APP_WAIT:-20} * 2 ))
    while office_app_running "$app"; do
        [ "$ticks" -ge "$max" ] && return 1
        sleep 0.5
        ticks=$((ticks + 1))
    done
    return 0
}

office_app_reset() {
    local app="$1" state label out
    label="$(_office_app_label "$app")"
    state="$(office_app_state "$app")" || return 2
    case "$state" in
        not-running)
            OFFICE_APP_RESET=not-running ;;
        clear)
            office_app_close_ours "$app"
            out="$(_office_app_quit_if_empty "$app")"
            case "$out" in
                quit|not-running)
                    if _office_app_wait_exit "$app"; then OFFICE_APP_RESET=quit
                    else
                        OFFICE_APP_RESET=quit-slow
                        echo "⚠️  $label: quit したが ${CLAUDE_OFFICE_APP_WAIT:-20} 秒以内に終わらない → kill せずそのまま続行" >&2
                    fi ;;
                blocked*)
                    OFFICE_APP_RESET=skipped-user-docs
                    echo "ℹ️  $label: 確認中に別の文書が開かれた → quit せず続行 (この script は自分の staged copy だけを開閉する)" >&2 ;;
                canceled)
                    OFFICE_APP_RESET=skipped-dialog
                    echo "⚠️  $label: dialog が出ていて quit が取り消された → 触らず続行 (Dock の $label を押すと dialog が見える)" >&2 ;;
                *)
                    OFFICE_APP_RESET=skipped-unknown
                    echo "⚠️  $label: 応答しない → quit も kill もせず続行" >&2 ;;
            esac ;;
        user-docs*)
            OFFICE_APP_RESET=skipped-user-docs
            echo "ℹ️  $label: この script が開いていない文書が ${state#user-docs } 件開いている → reset (quit) を省いて続行 (自分の staged copy だけを開閉する)" >&2 ;;
        *)
            OFFICE_APP_RESET=skipped-unknown
            echo "⚠️  $label: 起動中だが応答しない (固まっている / 許可 dialog 待ち) → 開いている文書を確かめられないので quit も kill もせず続行" >&2 ;;
    esac
    export OFFICE_APP_RESET
    return 0
}

office_app_launch_background() {
    local app="$1" id ticks=0 max
    OFFICE_APP_LAUNCHED=0; export OFFICE_APP_LAUNCHED
    id="$(_office_app_id "$app")" || return 2
    office_app_running "$app" && return 0
    # -g = 前面に出さない。 -j (hidden) は使わない = 開く失敗の警告などの dialog まで見えなくなり、
    #      quit が -128 で取り消されたまま誰にも気づかれない (実測)
    open -g -b "$id" >/dev/null 2>&1 || return 1
    OFFICE_APP_LAUNCHED=1
    max=$(( ${CLAUDE_OFFICE_APP_LAUNCH_WAIT:-120} * 2 ))
    until office_app_documents "$app" >/dev/null; do     # 文書一覧に答えたら ready
        [ "$ticks" -ge "$max" ] && { echo "⚠️  $(_office_app_label "$app"): 背景起動後 ${CLAUDE_OFFICE_APP_LAUNCH_WAIT:-120} 秒応答しない" >&2; return 1; }
        sleep 0.5
        ticks=$((ticks + 1))
    done
    return 0
}

office_app_release() {
    local app="$1" out
    [ "${OFFICE_APP_LAUNCHED:-0}" = 1 ] || return 0
    office_app_running "$app" || return 0
    office_app_close_ours "$app"
    out="$(_office_app_quit_if_empty "$app")"
    case "$out" in
        quit) _office_app_wait_exit "$app" || true ;;
        blocked*) echo "ℹ️  $(_office_app_label "$app"): 実行中に user の文書が開かれた → 起動したままにする" >&2 ;;
        canceled) echo "⚠️  $(_office_app_label "$app"): dialog が出ていて quit が取り消された → 起動したままにする (Dock から dialog を確認)" >&2 ;;
    esac
    return 0
}

office_app_failure_hint() {
    local label
    label="$(_office_app_label "$1")"
    case "${OFFICE_APP_RESET:-}" in
        skipped-user-docs)
            echo "   $label に user の文書が開いていたため reset (quit) を省いた。 失敗が続くなら $label で作業を保存して自分で終了 (⌘Q) してから再実行 (script は user の文書を閉じない)" >&2 ;;
        skipped-dialog)
            echo "   $label に dialog が出ている。 Dock の $label を押して dialog を閉じてから再実行" >&2 ;;
        skipped-unknown|quit-slow)
            echo "   $label が応答しない。 未保存の文書が無いか確かめてから自分で終了 / 強制終了して再実行 (script は kill しない)" >&2 ;;
        *)
            echo "   再実行する。 続くなら $label を自分で終了してから (office-automation.md#office-app-reset-guard)" >&2 ;;
    esac
}

office_front_remember() {
    OFFICE_FRONT_APP="$(osascript -e 'POSIX path of (path to frontmost application)' 2>/dev/null || true)"
    export OFFICE_FRONT_APP
}

office_front_restore() {
    local bundle="$1" now
    [ -n "${OFFICE_FRONT_APP:-}" ] || return 0
    now="$(osascript -e 'POSIX path of (path to frontmost application)' 2>/dev/null || true)"
    case "${now%/}" in */"$bundle") ;; *) return 0 ;; esac                 # Office が前面でなければ何もしない
    case "${OFFICE_FRONT_APP%/}" in */"$bundle") return 0 ;; esac          # 元から前面だったなら返さない
    open -a "${OFFICE_FRONT_APP%/}" >/dev/null 2>&1 || true
    return 0
}

# ---- CLI ----------------------------------------------------------------------
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    cmd="${1:-}"; shift || true
    case "$cmd" in
        state) office_app_state "${1:?app}" ;;
        documents) office_app_documents "${1:?app}" ;;
        reset) office_app_reset "${1:?app}"; echo "reset=${OFFICE_APP_RESET:-}" ;;
        launch) office_app_launch_background "${1:?app}"; rc=$?; echo "launched=${OFFICE_APP_LAUNCHED:-0}"; exit "$rc" ;;
        release) OFFICE_APP_LAUNCHED="${2:-0}" office_app_release "${1:?app}" ;;
        has-path) office_app_has_path "${1:?app}" "${2:?path}" ;;
        close-ours) office_app_close_ours "${1:?app}" "${@:2}" ;;
        front-remember) office_front_remember; printf '%s\n' "$OFFICE_FRONT_APP" ;;
        front-restore) OFFICE_FRONT_APP="${1:-}" office_front_restore "${2:?bundle}" ;;
        *) awk 'NR>1 && !/^#/{exit} NR>1{sub(/^# ?/,""); print}' "$0" >&2; exit 2 ;;
    esac
fi
