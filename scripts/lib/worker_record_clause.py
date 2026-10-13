"""Shared report contract text for vendor-specific delegation adapters.

# agent-authority:file

The common semantic requirement is multi-session-coordination.md#worker-record-clause.
This module contains no tool policy or vendor configuration.
"""
MARKER = "記録の約束"
CLAUSE = (
    "\n\n## " + MARKER + " (委ねた側が自動で足した段 / appended by the delegating side)\n"
    "作業の最後に、次の3項目を簡潔に報告してください。成果物のfileに書く場合は、そのpathを報告してください。"
    "該当が無い項目は「なし」と書いてください。\n"
    "1. 捨てた案とその理由\n"
    "2. 途中で気づいたこと (壊れ方・想定外・周辺の問題)\n"
    "3. 確かめていないこと・推定のままのこと\n"
    "(In your final report or a linked deliverable, briefly summarize discarded options and why, "
    "findings encountered during the work, and remaining uncertainties. Write 'none' where applicable.)"
)
