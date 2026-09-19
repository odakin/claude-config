"""案件 dir の隔離 marker (00-⚠️-DO-NOT-USE-AS-BASE.md) を manifest から生成する。

手書きの marker は「どれが提出済みか」 を人が書き写していた (= 状態の二重 home)。 状態の正本は submission.yaml で、
marker はそこから描く生成物。 既知の誤りの明細・注意は manifest の ``errata:`` (markdown の箇条、 case dir 相対の link)。
凍結 issue が 1 つも無い案件には marker を作らない (あれば stale として報告)。
"""
from __future__ import annotations

from pathlib import Path

from . import config as CF
from . import manifest as M

MARKER_NAME = "00-⚠️-DO-NOT-USE-AS-BASE.md"
GEN = "<!-- 生成物 (formcase.py markers --write、 元 = submission.yaml)。 手で直さない — 状態は manifest、 誤りの明細は manifest の errata -->"


def _precedent_link(case_dir: Path) -> str:
    """「前例を base にしない」 一般則への link (案件 dir からの相対。 workspace の外なら label つきの絶対)。"""
    doc = CF.precedent_doc()
    try:
        depth = len(case_dir.resolve().relative_to(CF.workspace_root()).parts)
        return "../" * depth + doc
    except ValueError:
        return CF.workspace_label() + doc


def render(m: M.Manifest) -> str | None:
    rows, paper_rows = [], []
    for doc_id, doc, gid, g in m.iter_groups():
        for label, issue in [("今", g.get("current") or {})] + [("前", x) for x in (g.get("previous") or [])]:
            st = issue.get("state")
            if st not in M.FROZEN_STATES:
                continue
            outs = ", ".join(f"`{Path(p).name}`" for p in (issue.get("outputs") or {}).values()) or (
                f"(出力 file なし = {' '.join(str(issue['outputs_ack']).split())})" if issue.get("outputs_ack")
                else "(出力 file なし)")
            if issue.get("commit"):
                outs += f" (版 = commit `{issue['commit']}`、 file は後で上書き済)"
            paper = {"same": "= 同じ", "differs": "≠ **違う**", "unverified": "? **不明**"}.get(
                issue.get("paper"), "(未記入)" if st in M.PAPER_STATES else "—")
            rows.append(f"| {doc_id} / {gid} ({label}) | {st} {issue.get('date', '')} | {outs} | {paper} |")
            line = M.paper_line(issue)
            if line:
                paper_rows.append(f"- {doc_id} / {gid} ({label}、 {st} {issue.get('date', '')}): {line}")
    if not rows:
        return None
    lines = [
        "# ⚠️ この folder の提出版ファイルを新規書類の base にしない",
        "",
        GEN,
        "",
        "下の表の出力は印刷・送付・提出した**史実の記録** = 書き換え禁止 (commit 時に pre-commit が止め、 "
        "`formcase.py check` が bytes と sheet の値の変化を 🔴 にする)。 参照してよいのは「何を出したか」 の確認だけ。",
        "",
        f"**新しい書類は `formcase.py new` で配布雛形から** (前の案件の xlsx・driver を写さない。 一般則 = "
        f"[`{Path(CF.precedent_doc()).name}`]({_precedent_link(m.case_dir)}))。 "
        "この案件の draft の group を作り直すのは `formcase.py build`、 凍結 group の作り直しは `formcase.py reopen` (新しい file 名)。",
        "",
        "列「紙」 = 記録した file・sheet の値が、 実際に刷った / 送った / 出したものと同じか (manifest の `paper:`)。",
        "",
        "| document / group | 状態 | 出力 | 紙 |",
        "|---|---|---|---|",
        *rows,
    ]
    if paper_rows:
        lines += ["", "## 📄 記録と紙の差 (この表の出力を「出したもの」 として引用しない)", "", *paper_rows]
    errata = m.data.get("errata") or []
    if errata:
        lines += ["", "## 既知の誤り・注意 (明細の正本は各 link 先)", ""]
        lines += ["- " + "\n  ".join(x.strip() for x in e.strip().split("\n")) for e in errata]
    return "\n".join(lines) + "\n"


def check_case(m: M.Manifest, write: bool = False) -> tuple:
    """(status, path)。 status = ok / stale / written / absent-ok / extra (凍結なしなのに marker がある)。"""
    p = m.case_dir / MARKER_NAME
    want = render(m)
    have = p.read_text(encoding="utf-8") if p.exists() else None
    if want is None:
        return ("extra" if have and GEN in have else "absent-ok"), p
    if have == want:
        return "ok", p
    if write:
        p.write_text(want, encoding="utf-8")
        return "written", p
    return "stale", p
