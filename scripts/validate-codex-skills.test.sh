#!/usr/bin/env bash
# validate-codex-skills.test.sh — shipped Codex skills の discovery metadata を検証する

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/../codex/skills" && pwd)"
EXPECTED_COUNT=2
FOUND=0

for skill_file in "$SKILLS_DIR"/*/SKILL.md; do
  [ -f "$skill_file" ] || continue
  FOUND=$((FOUND + 1))
  skill_dir="$(basename "$(dirname "$skill_file")")"
  [ "$(sed -n '1p' "$skill_file")" = '---' ]
  [ "$(sed -n '2s/^name: *//p' "$skill_file")" = "$skill_dir" ]
  [ -n "$(sed -n '3s/^description: *//p' "$skill_file")" ]
  [ "$(sed -n '4p' "$skill_file")" = '---' ]
  grep -q '^# ' "$skill_file"
done

[ "$FOUND" -eq "$EXPECTED_COUNT" ]

echo "validate-codex-skills tests passed"
