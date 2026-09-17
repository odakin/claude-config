#!/usr/bin/env bash
# prune-retired-hooks.sh — 退役した hook を外す (hooks dir の symlink + settings.json の entry)。 registry 駆動・冪等
#
# 正本: <claude-config>/scripts/lib/prune-retired-hooks.sh
# 呼び元: scripts/sync-hook-settings.sh (層1 の hook) / 個人層の hook installer (同じ関数に自分の registry を渡す)
# test:  scripts/lib/prune-retired-hooks.test.sh
# 規約:  conventions/hook-authoring.md#additive-wiring-needs-retirement
#
# なぜ要るか: hook の配線 (symlink + settings.json の entry) は「無いものを足すだけ」 で作ってある
# (= 他の層・利用者が足した entry を壊さないため)。 その代わり、 hook を repo から消しても各マシンの配線は残り、
# 以後その event のたびに「file が無い」 hook が走って失敗し続ける。 掃除を install script の中の hardcode にすると、
# その script を再実行しないマシンでは永久に残る。 → 退役は registry (1 行 1 名) に書き、
# 毎 session 走る sync 経路が同じ関数で外す。
#
# registry の書式: 1 行 1 file 名 (basename。 例 old-hook.sh)。 `#` 以降は comment (退役の理由を書く)。
#   `Event:file 名` (例 UserPromptSubmit:anchor.py) = その event からだけ外す。 file は別の event で現役なので
#   symlink は触らず、 下の「SRC_DIR に在れば外さない」 も当てない。
#
# 安全:
#   - event 指定の無い名前は、 SRC_DIR に同名 file がまだ在れば外さない (= 書き間違いで生きている hook を消さない)。 WARN を出す。
#   - hooks dir から消すのは symlink だけ (Windows の copy 方式は通常 file なので、 MSYS 系でだけ通常 file も消す)。
#   - settings.json は、 command の空白区切りの語のどれかが "/<file 名>" で終わる hook だけを entry から抜き、
#     hooks が空になった entry と、 entry が空になった event を落とす (= 同じ entry に同居する他の hook、 他の層の entry は残る)。
#
# bash 3.2 compatible。 jq 必須 (無ければ何もせず return 0)。

# prune_retired_hooks REGISTRY SRC_DIR HOOKS_DST SETTINGS [--check]
#   --check: 何も書かず、 残骸を 1 行ずつ出して、 残骸があれば return 1
prune_retired_hooks() {
    local registry="$1" src_dir="$2" hooks_dst="$3" settings="$4" check="${5:-}"
    local line name event found=0 copy_mode=0 in_settings has_link
    # $ev が空なら全 event、 そうでなければその event だけを走査する jq の断片
    local in_scope='(.hooks // {}) | to_entries[] | select($ev == "" or .key == $ev) | .value[]?'
    [ -f "$registry" ] || return 0
    command -v jq >/dev/null 2>&1 || return 0
    case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) copy_mode=1 ;; esac

    while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$line" in
            *:*) event="${line%%:*}"; name="${line#*:}" ;;
            *)   event=""; name="$line" ;;
        esac
        if [ -z "$event" ] && [ -e "$src_dir/$name" ]; then
            [ "$check" = "--check" ] || echo "  WARN: $name は退役 registry に在るが $src_dir にも在る — 外さない (registry か file のどちらかを直す)"
            continue
        fi
        in_settings=0
        if [ -f "$settings" ] && jq -e --arg n "/$name" --arg ev "$event" \
            "[$in_scope | .hooks[]? | (.command // \"\") | split(\" \") | .[] | select(endswith(\$n))] | length > 0" \
            "$settings" >/dev/null 2>&1; then
            in_settings=1
        fi
        has_link=0
        if [ -z "$event" ]; then
            if [ -L "$hooks_dst/$name" ] || { [ "$copy_mode" -eq 1 ] && [ -f "$hooks_dst/$name" ]; }; then has_link=1; fi
        fi
        if [ "$check" = "--check" ]; then
            if [ "$has_link" -eq 1 ] || [ "$in_settings" -eq 1 ]; then
                echo "  - 退役 hook の残骸: $line"
                found=$((found + 1))
            fi
            continue
        fi
        if [ "$has_link" -eq 1 ]; then
            rm -f "$hooks_dst/$name" && echo "  RETIRED-UNLINK: $name"
        fi
        if [ "$in_settings" -eq 1 ]; then
            jq --arg n "/$name" --arg ev "$event" '.hooks |= with_entries(
                    if ($ev == "" or .key == $ev) then .value |= (
                        map(.hooks |= map(select(((.command // "") | split(" ") | any(endswith($n))) | not)))
                        | map(select((.hooks | length) > 0))) else . end)
                | .hooks |= with_entries(select((.value | length) > 0))' \
                "$settings" > "$settings.tmp" && mv "$settings.tmp" "$settings"
            echo "  RETIRED-UNREGISTER: $line"
        fi
    done < <(sed 's/#.*//' "$registry" | awk 'NF {print $1}' | tr -d '\r')

    [ "$found" -eq 0 ]
}
