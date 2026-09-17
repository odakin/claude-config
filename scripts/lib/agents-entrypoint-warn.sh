#!/usr/bin/env bash
# agents-entrypoint-warn.sh — root に CLAUDE.md があるのに AGENTS.md が無い repo の commit で 1 回知らせる (止めない)
#
# 契約 = CONVENTIONS.md#agent-instruction-entrypoints (本規約に従う repo は root に tracked・非空の AGENTS.md)。
# Codex は CLAUDE.md を自動で読まないので、 入口が無い repo では Codex の task が規約も現在地も知らずに始まる。
# 「既存 repo は次に触る時に足す」 を人の記憶に任せると足されない (= 実測、
# docs/convention-design-principles.md#manual-work-in-design-records)。 足すのは雛形を置くだけなので、
# 書いた commit でその repo の作業者に知らせる。 中身 (pointer・4 KiB・symlink でない) の検査は
# scripts/audit-codex-integration.sh --repo <path>。
#
# 判定 = index に CLAUDE.md があり AGENTS.md が無い (この commit で足す分は index に在るので鳴らない)。
# 鳴らさない: repo root 以外 / `git config agent.entrypointWarn false`。
# 呼び方: source して warn_missing_agents_entrypoint (常に return 0)。 pre-commit-bib と public-precommit-runner.sh が呼ぶ。

warn_missing_agents_entrypoint() {
    [ "$(git config --bool agent.entrypointWarn 2>/dev/null)" = "false" ] && return 0
    git ls-files --error-unmatch -- CLAUDE.md >/dev/null 2>&1 || return 0
    git ls-files --error-unmatch -- AGENTS.md >/dev/null 2>&1 && return 0
    local tpl="$HOME/Claude/claude-config/templates/shared-project/AGENTS.md.template"
    echo "⚠️ pre-commit: root に AGENTS.md が無い (CLAUDE.md はある) — Codex は CLAUDE.md を自動で読まないので入口が要る (commit は止めない)" >&2
    echo "   雛形: sed 's#<owner>#<GitHub の owner>#g' ${tpl} > AGENTS.md  (契約 = claude-config CONVENTIONS.md#agent-instruction-entrypoints、 不要なら git config agent.entrypointWarn false)" >&2
    return 0
}
