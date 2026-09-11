#!/usr/bin/env bash
# audit-hooks.sh — 4 軸 hook 配信 audit (= silent malfunction の構造的検出、 (d) は自動部分のみ)
# 付随: 本番 hooks dir に残置された *.test.sh は「未登録」 でなく掃除対象 (🧹) として分類する (2026-07-10)
#
# 設計動機: conventions/hook-authoring.md#delivery-audit-4-axes の audit 規律を script 化。
# 単発 (P1) check + dashboard 統合 (= unified-dashboard.py 経由の P2 continuous
# monitoring) の dual purpose。
#
# 3 軸:
#   (a) symlink target 健全性 — ~/.claude/hooks/<name> が指す target file 存在
#   (b) settings.json entry — 該当 hook が PreToolUse / PostToolUse / SessionStart
#                              等 event の hooks list に登録済
#   (c) syntax 健全性 — bash -n (.sh) / py_compile (.py) が通る
#   (d) harness invoke 経路の生死 (自動部分) — hook-liveness-audit.py --findings-only
#       = disableAllHooks kill switch の settings 全 tier 走査 + transcript 上の SessionStart
#       発火証拠 (hook-authoring.md#disableallhooks-kill-switch)。 個別 hook の trace による
#       invoke 確認は manual のまま (hook-authoring.md#delivery-audit-method)。 python3 不在なら skip
#
# 出力:
#   - 全 green: silent skip (= dashboard noise 抑制)
#   - finding あり: section 出力 + 件数 + 各 finding の概要
#
# 例外:
#   - fix-snapshot-path-patch.sh: launchd WatchPaths 経由 invoke のため
#     settings.json 登録不要 (= conventions/hook-authoring.md §関連 で明記)
#
# 制約:
#   - bash 3.2 compatible (= macOS stock /bin/bash で動作、 mapfile 不使用)
#   - jq 必須 (= setup.sh が前提とする tool、 brew で install 想定)
#   - 非 macOS / hooks dir 不在環境 では silent skip

set -u

HOOKS_DIR="${HOME}/.claude/hooks"
SETTINGS="${HOME}/.claude/settings.json"

# 環境確認 (= 不在環境は silent skip、 dashboard が止まらない)
if [ ! -d "$HOOKS_DIR" ]; then
    exit 0
fi

if [ ! -f "$SETTINGS" ]; then
    echo "⚠️ audit-hooks: settings.json not found" >&2
    exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "⚠️ audit-hooks: jq not installed (= setup.sh が前提とする tool)" >&2
    exit 0
fi

# settings.json から全 hook command path を抽出
# bash 3.2 compatible: mapfile 不使用、 while read で配列構築
registered_files=()
while IFS= read -r cmd; do
    [ -z "$cmd" ] && continue
    # command は "path [args...]" 形式がありうる (例: session-commit-nudge.sh track)
    # → 第 1 token だけを file path として扱う (この repo の hook path は space を含まない前提)
    cmd="${cmd%% *}"
    # ~/... を $HOME に expand
    expanded="${cmd/#\~/$HOME}"
    registered_files+=("$expanded")
done < <(jq -r '
  .hooks // {} | to_entries | .[] |
  .value[]? | .hooks[]? | .command // empty
' "$SETTINGS" 2>/dev/null | tr -d '\r')

# bash 3.2 では空配列に対する "${arr[@]}" は unbound、 set -u と組合せ防御
[ ${#registered_files[@]} -eq 0 ] && registered_files=("")

issues=()

# (a) + (c): ~/.claude/hooks/ の各 file
# bash 3.2 compatible glob (= shopt -s nullglob は bash 3.2 でも動く)
shopt -s nullglob 2>/dev/null || true

for hook in "$HOOKS_DIR"/*.sh "$HOOKS_DIR"/*.py; do
    [ ! -e "$hook" ] && continue
    name=$(basename "$hook")

    # .test.sh は開発用 self-test で配信対象外 (setup.sh も除外) — 「未登録」 finding に数えない。
    # 過去の setup.sh が配った残置 symlink は掃除対象として別途 flag する
    case "$name" in
        *.test.sh)
            issues+=("🧹 $name: .test.sh が本番 hooks dir に残置 (= 旧 setup.sh の配信残骸、 rm 可)")
            continue ;;
    esac

    # (a) symlink target 健全性
    if [ -L "$hook" ]; then
        target=$(readlink "$hook")
        # 相対 symlink の場合の解決
        case "$target" in
            /*) ;;  # 絶対 path、 そのまま
            *) target="$(dirname "$hook")/$target" ;;
        esac
        if [ ! -e "$target" ]; then
            issues+=("❌ ${name}: broken symlink (target missing: ${target})")
            continue  # 以下の check は意味なし
        fi
    fi

    # (c) syntax check
    syntax_ok=1
    case "$name" in
        *.sh)
            bash -n "$hook" 2>/dev/null || syntax_ok=0
            ;;
        *.py)
            python3 -m py_compile "$hook" 2>/dev/null || syntax_ok=0
            ;;
    esac
    if [ $syntax_ok -eq 0 ]; then
        issues+=("❌ ${name}: syntax error (= bash -n or py_compile fail)")
        continue
    fi

    # (b) settings.json entry
    found=0
    for reg in "${registered_files[@]}"; do
        [ -z "$reg" ] && continue
        if [ "$(basename "$reg")" = "$name" ]; then
            found=1
            break
        fi
    done
    if [ $found -eq 0 ]; then
        # launchd 経由の例外
        if [ "$name" != "fix-snapshot-path-patch.sh" ]; then
            issues+=("⚠️ ${name}: not registered in settings.json (= file 存在 / invoke 経路無し)")
        fi
    fi
done

# (b) orphan check: settings.json 登録あり / file 不在
for reg in "${registered_files[@]}"; do
    [ -z "$reg" ] && continue
    if [ ! -e "$reg" ]; then
        issues+=("⚠️ orphan: ${reg} (= settings.json 登録あり / file 不在 = partial uninstall)")
    fi
done

# (d) 自動部分: kill switch + transcript 上の発火証拠。 (a)-(c) が全部 green でも hook が
#     1 本も走っていない状態 (= root 限定の disableAllHooks 等) はここでしか見えない。
LIVENESS="$(cd "$(dirname "$0")" && pwd)/hook-liveness-audit.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$LIVENESS" ]; then
    while IFS= read -r line; do
        [ -n "$line" ] && issues+=("$line")
    done < <(python3 "$LIVENESS" --findings-only 2>/dev/null)
fi

# Output
if [ ${#issues[@]} -eq 0 ]; then
    exit 0  # silent if all green
fi

echo ""
echo "=== 🔧 hook 配信 audit (${#issues[@]} 件 finding) ==="
for issue in "${issues[@]}"; do
    echo "  $issue"
done
echo ""
echo "  → 4 軸 (symlink + settings.json + syntax + 発火証拠 / kill switch) で expose"
echo "  → 規律: ~/Claude/claude-config/conventions/hook-authoring.md#delivery-audit-4-axes"
exit 0
