#!/usr/bin/env bash
# merge-hook-event.sh — settings.json への hook event merge (単一リスト駆動)
#
# 正本: <claude-config>/scripts/lib/merge-hook-event.sh
# 呼び元: setup.sh install_hooks() が source して event ごとに merge_hook_event を呼ぶ
# test:  scripts/lib/merge-hook-event.test.sh
#
# 設計 (2026-07-10): 従来の install_hooks は「JSON 定義 (HOOK_ENTRIES 等)」 と
# 「merge loop の hardcode hook 名リスト」 の二重管理で、 片方だけ更新する同期漏れが
# 実際に起きた (= stale-read-nudge.sh が JSON にも loop にも入らず silent dead)。
# 本関数は期待 hook リストを entries JSON 自身から jq で導出する = リストは 1 つ、
# 同期漏れが構造的に不可能 (design-out)。
#
# 照合は従来互換の「hooks/ 以降の substring (basename + args)」 contains 一致
# (= 既存 settings.json に絶対 path で登録済みの hook を重複追加しない)。
# 引数付き command (例 "session-commit-nudge.sh track") は引数込みで照合するため、
# 同名 script の別 mode ("... nudge") とは独立に管理される。
#
# bash 3.2 compatible (mapfile / assoc array 不使用)。 jq 必須 (呼び元が確認済み前提)。

merge_hook_event() {
    # $1 = event 名 (PreToolUse / PostToolUse / SessionStart / Stop)
    # $2 = entries JSON ([{matcher?, hooks: [{type, command}]}])
    # $3 = settings.json path
    local event="$1" entries="$2" settings="$3"
    local cmd entry

    if ! jq -e ".hooks.${event}" "$settings" > /dev/null 2>&1; then
        echo "  Adding ${event} hooks ..."
        jq --argjson entries "$entries" ".hooks.${event} = \$entries" \
            "$settings" > "$settings.tmp" && mv "$settings.tmp" "$settings"
        return 0
    fi

    # 期待 hook (basename + args) を entries JSON 自身から導出 — hardcode リストを持たない
    while IFS= read -r cmd; do
        [ -z "$cmd" ] && continue
        if ! jq -e --arg cmd "$cmd" \
            ".hooks.${event}[] | select(.hooks[]?.command | contains(\$cmd))" \
            "$settings" > /dev/null 2>&1; then
            echo "  Adding missing ${event} hook: $cmd"
            entry=$(printf '%s' "$entries" | jq --arg cmd "$cmd" \
                '[.[] | select(.hooks[]?.command | contains($cmd))][0]')
            jq --argjson entry "$entry" \
                ".hooks.${event} += [\$entry]" \
                "$settings" > "$settings.tmp" && mv "$settings.tmp" "$settings"
        fi
    done < <(printf '%s' "$entries" | jq -r '.[].hooks[]?.command | sub("^.*/hooks/"; "")' | tr -d '\r')

    # matcher の照合 (2026-09-19): 「在るか」 だけ見て足す ensure は、 宣言側で matcher を変えても
    # 既に entry が在るマシンに届かない (= そのマシンだけ旧い tool 集合のまま走る。
    # conventions/multi-machine-state.md#ensure-reconciles-content)。 その hook 専用の entry
    # (= hooks が 1 本だけ) に限って matcher を宣言どおりに直す。 他の hook と束ねられた entry は
    # 直すと巻き添えになるので、 違いを報告するだけにする。
    while IFS= read -r cmd; do
        [ -z "$cmd" ] && continue
        local want live n solo
        want=$(printf '%s' "$entries" | jq -r --arg cmd "$cmd" \
            '[.[] | select(.hooks[]?.command | contains($cmd))][0] | .matcher // empty')
        [ -z "$want" ] && continue
        n=$(jq -r --arg cmd "$cmd" "[.hooks.${event}[] | select(.hooks[]?.command | contains(\$cmd))] | length" "$settings")
        [ "$n" = "1" ] || continue
        live=$(jq -r --arg cmd "$cmd" "[.hooks.${event}[] | select(.hooks[]?.command | contains(\$cmd))][0] | .matcher // \"\"" "$settings")
        [ "$live" = "$want" ] && continue
        solo=$(jq -r --arg cmd "$cmd" "[.hooks.${event}[] | select(.hooks[]?.command | contains(\$cmd))][0] | (.hooks | length)" "$settings")
        if [ "$solo" = "1" ]; then
            echo "  Updating ${event} matcher: $cmd ($live → $want)"
            jq --arg cmd "$cmd" --arg want "$want" \
                ".hooks.${event} |= map(if ((.hooks | length) == 1) and ((.hooks[0].command // \"\") | contains(\$cmd)) then .matcher = \$want else . end)" \
                "$settings" > "$settings.tmp" && mv "$settings.tmp" "$settings"
        else
            echo "  NOTE: ${event} の $cmd は matcher が宣言と違う ($live ≠ $want) が、 他の hook と同じ entry なので触らない" >&2
        fi
    done < <(printf '%s' "$entries" | jq -r '.[].hooks[]?.command | sub("^.*/hooks/"; "")' | tr -d '\r')
}
