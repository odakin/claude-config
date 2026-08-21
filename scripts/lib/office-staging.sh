#!/usr/bin/env bash
# office-staging.sh — Office (Word / Excel / PowerPoint) automation の「事前 grant 済み staging dir」 helper (sourceable lib、 macOS App Sandbox の folder-grant dialog を design-out、 office-automation.md#office-pregranted-staging-dir)
#
# WHY
#   macOS の Microsoft Office は App Sandbox。 AppleScript / `open` で渡した file を読むのは
#   通るが、 その **folder へ書く** (= PDF export / save) 瞬間に Office 独自の
#   「ファイル アクセスを許可」 dialog が folder ごとに出る (= security-scoped bookmark を
#   folder 単位で溜める仕組み、 2026-08-21 実測: open では出ず save-as で出る)。 案件ごとに
#   dir を切る運用だと案件のたびに出る + remote 操作では押せない。
#   一方、 Office 3 app が entitlement で共有する App Group container
#   `~/Library/Group Containers/UBF8T346G9.Office/` は sandbox profile の内側 = grant 不要
#   (2026-08-21 macOS 13.7 / Office 16.101 実測: Word + Excel とも dialog ゼロで export 成功)。
#   → 変換 script は入力をそこへ copy → Office に開かせる → 出力を呼び出し元へ copy back。
#   呼び出し側 API (= path を渡す) は不変、 staging は内部実装。
#
# API (source して使う。 bash 3.2 compatible)
#   office_staging_root           … staging root を echo。 無効 / 非 macOS / 不可 なら空文字 (= 呼び出し側は in-place で続行)
#   office_stage_file <src>       … <root>/<unique>/<basename> に copy。 成功で OFFICE_STAGED (= staged path) と
#                                   OFFICE_STAGE_DIR (= unique subdir) を set、 staging 不可なら rc=1 (変数は空)
#   office_stage_cleanup          … OFFICE_STAGE_DIR を削除 (= 成功時のみ呼ぶ、 失敗時は残して診断。 root 外は拒否)
#   office_stage_prune [days]     … root 直下の古い subdir を掃除 (default 7 日、 失敗残骸の無限増殖防止)
#   office_staging_fallback_reason … root が空になる理由を 1 語で echo:
#                                   disabled / not-darwin / no-office / mkdir-failed / not-writable / ok
#   office_stage_report_fallback <src> … staging が効かず in-place に落ちた時に呼ぶ (= wrapper の else 分岐)。
#                                   「予期せぬ」 理由 (mkdir-failed / not-writable / no-office) なら stderr に
#                                   ⚠️ + fallback log (下記) に 1 行 append。 disabled / not-darwin は意図的
#                                   なので沈黙。 ⚠️ 2026-08-22: staging の silent fallback は「dialog 復活」 を
#                                   黙って起こす = 機構の死が見えない → ここで必ず声を出す + log を残して
#                                   別 session の検出器 (個人層の check script) が拾えるようにする。
#
# 制御 (env)
#   CLAUDE_OFFICE_STAGING_LOG=FILE … fallback log の path (default
#                                   ${XDG_STATE_HOME:-$HOME/.local/state}/claude-office-staging/fallback.log、
#                                   1 行 = <ISO ts>\t<reason>\t<root>\t<src>)
#   CLAUDE_OFFICE_STAGING=0       … staging を無効化 (= 旧挙動 in-place、 `--no-stage` 相当)
#   CLAUDE_OFFICE_STAGING_DIR=DIR … root を override (= group container が使えない環境で、 一度だけ手動 grant
#                                   した固定 dir を指す。 macOS 15+ の App Data 保護で Terminal から
#                                   Group Containers に書けない場合の逃げ道。 2026-08-22 macOS 26.5 実測では
#                                   Claude Code 配下の shell から group container がそのまま通り override 不要だった)
#
# 設計
#   * unique subdir = mktemp -d (<timestamp>-<pid>-XXXXXX): 並列 session の同名衝突を隔離し、 Word の
#     stale in-memory cache (#docx-pdf-stale-cache) が「同じ path を再 open」 で再発しない
#   * <subdir>/.source に元 path を記録 (= provenance、 失敗残骸の診断用)
#   * basename は保持 (= Office の window title / PowerPoint の HFS 変換 / recent list がそのまま読める)
#   * Python driver 用の鏡像 = scripts/lib/office_staging.py (同じ規則。 drift は office-staging.test.sh が検出)

OFFICE_STAGING_ROOT_NAME="claude-office-staging"
OFFICE_STAGING_GROUP_CONTAINER="Library/Group Containers/UBF8T346G9.Office"

office_staging_root() {
    case "${CLAUDE_OFFICE_STAGING:-1}" in
        0|no|off|false) return 0 ;;
    esac
    local root
    if [ -n "${CLAUDE_OFFICE_STAGING_DIR:-}" ]; then
        root="$CLAUDE_OFFICE_STAGING_DIR"
    else
        [ "$(uname)" = "Darwin" ] || return 0
        local gc="$HOME/$OFFICE_STAGING_GROUP_CONTAINER"
        [ -d "$gc" ] || return 0          # Office 未 install
        root="$gc/$OFFICE_STAGING_ROOT_NAME"
    fi
    mkdir -p "$root" 2>/dev/null || return 0
    [ -w "$root" ] || return 0
    printf '%s\n' "$root"
}

office_stage_file() {
    local src="$1" root base dir
    OFFICE_STAGED=""; OFFICE_STAGE_DIR=""
    root="$(office_staging_root)"
    [ -n "$root" ] || return 1
    [ -f "$src" ] || return 1
    base="$(basename "$src")"
    dir="$(mktemp -d "$root/$(date +%Y%m%dT%H%M%S)-$$-XXXXXX" 2>/dev/null)" || return 1
    if ! cp -p "$src" "$dir/$base"; then
        rm -rf "$dir"; return 1
    fi
    printf '%s\n' "$src" > "$dir/.source"
    OFFICE_STAGE_DIR="$dir"
    OFFICE_STAGED="$dir/$base"
    export OFFICE_STAGE_DIR OFFICE_STAGED
    return 0
}

office_stage_cleanup() {
    local root
    [ -n "${OFFICE_STAGE_DIR:-}" ] || return 0
    root="$(office_staging_root)"
    case "$OFFICE_STAGE_DIR" in
        "$root"/?*) [ -n "$root" ] && rm -rf "$OFFICE_STAGE_DIR" ;;
        *) echo "⚠️  office_stage_cleanup: refusing to remove outside staging root: $OFFICE_STAGE_DIR" >&2 ;;
    esac
    OFFICE_STAGE_DIR=""; OFFICE_STAGED=""
    return 0
}

office_stage_prune() {
    local days="${1:-7}" root
    root="$(office_staging_root)"
    [ -n "$root" ] || return 0
    find "$root" -mindepth 1 -maxdepth 1 -type d -mtime +"$days" -exec rm -rf {} + 2>/dev/null || true
    return 0
}

office_staging_fallback_reason() {
    # office_staging_root と同じ分岐を辿り、 空を返す理由を 1 語で echo (root が取れるなら ok)。
    case "${CLAUDE_OFFICE_STAGING:-1}" in
        0|no|off|false) echo disabled; return 0 ;;
    esac
    local root
    if [ -n "${CLAUDE_OFFICE_STAGING_DIR:-}" ]; then
        root="$CLAUDE_OFFICE_STAGING_DIR"
    else
        [ "$(uname)" = "Darwin" ] || { echo not-darwin; return 0; }
        local gc="$HOME/$OFFICE_STAGING_GROUP_CONTAINER"
        [ -d "$gc" ] || { echo no-office; return 0; }
        root="$gc/$OFFICE_STAGING_ROOT_NAME"
    fi
    mkdir -p "$root" 2>/dev/null || { echo mkdir-failed; return 0; }
    [ -w "$root" ] || { echo not-writable; return 0; }
    echo ok
}

office_staging_log_path() {
    printf '%s\n' "${CLAUDE_OFFICE_STAGING_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-office-staging/fallback.log}"
}

office_stage_report_fallback() {
    # office_stage_report_fallback <src>
    # 予期せぬ fallback (= staging を使うつもりだったのに root が作れない) を可視化:
    #   stderr に ⚠️ (= 呼んだ session が即気づく) + fallback log に append (= 後続 session の検出器が拾う)。
    # 意図的な無効化 (disabled) / 非 macOS は沈黙。 log 書込失敗は無視 (= 変換自体は止めない)。
    local src="${1:-}" reason root log
    reason="$(office_staging_fallback_reason)"
    case "$reason" in
        ok|disabled|not-darwin) return 0 ;;
    esac
    if [ -n "${CLAUDE_OFFICE_STAGING_DIR:-}" ]; then root="$CLAUDE_OFFICE_STAGING_DIR"
    else root="$HOME/$OFFICE_STAGING_GROUP_CONTAINER/$OFFICE_STAGING_ROOT_NAME"; fi
    echo "⚠️  staging: UNAVAILABLE ($reason: $root) → in-place. Office の「ファイル アクセスを許可」 dialog が出うる" >&2
    echo "    対処 = office-automation.md#office-pregranted-staging-dir (TCC 許可 or CLAUDE_OFFICE_STAGING_DIR=<dir> + 1 回 grant)" >&2
    log="$(office_staging_log_path)"
    mkdir -p "$(dirname "$log")" 2>/dev/null || return 0
    printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$reason" "$root" "$src" >> "$log" 2>/dev/null || true
    return 0
}
