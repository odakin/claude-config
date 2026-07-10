#!/usr/bin/env bash
# staged-conflict-markers.sh — merge conflict marker の staged-content gate (sourceable lib)
#
# 正本: claude-config/scripts/lib/staged-conflict-markers.sh
# 呼び元: scripts/pre-commit-bib (全 repo 共通 pre-commit、 symlink 設置) +
#         scripts/public-precommit-runner.sh (public repo stub 経由) の両方が source
#         (= DRY、 lib/commit-msg-leak-matcher.sh と同じ shared-lib pattern)。
#
# 検出:
#   この commit で変更される file (git diff --cached --name-only --diff-filter=ACMR) の
#   **staged 内容全体** (= working tree でなく index、 `git show :<path>`) に行頭
#   conflict marker (`<<<<<<< ` / `>>>>>>> `) が残っていれば 1 を返す
#   (呼び元が commit を BLOCK する)。
#   - 「この commit で触る file」 に限定 = 過去に混入済みの無関係 file が緊急 commit を
#     block しない (既存混入の全量検査は run-all-checks 検査 6 / CI 側の責務)
#   - pattern は `{7}` 表記 = 本 file / 呼び元 / test が自分自身に match しない
#   - `grep -I` = binary file は対象外
#   - `=======` 単独行は見ない (= markdown setext 見出しと衝突する FP 源。 <<< / >>> は
#     conflict で必ず対で残るので 2 種の検出で機能的に十分)
#
# escape hatch:
#   - 引用等で行頭 marker を書きたい → indent する (行頭でなければ非検出)
#   - 意図的に通したい → CLAUDE_SKIP_CONFLICT_GATE=1 git commit ... (or git 標準の --no-verify)
#
# 設計動機 (2026-07-10 実事故): 並行 session の merge 解決漏れで conflict marker 入りの
# conventions/*.md が public repo に commit+push され、 検出器ゼロのまま同日の fresh-eyes
# review まで残置された。 規律 (4 軸 sweep) は多 commit / 並行 session 圧力下で skip され
# 得るので、 commit 時点の機械 gate で発生源から design-out する。

check_staged_conflict_markers() {
    if [ "${CLAUDE_SKIP_CONFLICT_GATE:-0}" = "1" ]; then
        return 0
    fi
    local f hits found=0
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        hits="$(git show ":$f" 2>/dev/null | grep -nIE '^(<{7}|>{7}) ' || true)"
        if [ -n "$hits" ]; then
            found=1
            echo "pre-commit: ✗ merge conflict marker (staged): $f" >&2
            printf '%s\n' "$hits" | sed 's/^/    /' >&2
        fi
    done < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
    if [ "$found" = "1" ]; then
        {
            echo ""
            echo "pre-commit: merge conflict marker が staged content に残っています。 解決してから commit してください。"
            echo "  (引用目的なら行頭を避けて indent / 意図的に通すなら CLAUDE_SKIP_CONFLICT_GATE=1 か --no-verify)"
        } >&2
        return 1
    fi
    return 0
}
