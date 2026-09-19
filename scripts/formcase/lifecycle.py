"""issue の状態遷移 (freeze / reopen)。 manifest を手で書き換えずにこれを通す = sha256 と sheet digest が残る。"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import manifest as M
from . import specs as S


def _today() -> str:
    return _dt.date.today().isoformat()


def record_frozen(m: M.Manifest, doc_id: str, group_id: str, issue: dict) -> dict:
    """issue の出力 sha256 と group の sheet digest を計算して返す (書き込みはしない)。"""
    doc = m.doc(doc_id)
    spec = S.get(doc.get("form"))
    fr = {"sha256": {}, "sheet_digest": {}, "sheet_digest_v3": {}}
    for role, rel in (issue.get("outputs") or {}).items():
        p = m.case_dir / rel
        if not p.exists():
            raise M.ManifestError(f"出力 {rel} が無いので凍結できない (先に build する)")
        fr["sha256"][role] = M.file_sha256(p)
    wb = m.workbook(doc_id)
    from . import docx_form as DF

    if DF.is_docx(spec) and wb is not None and wb.exists():
        # Word 様式 = docx の文字・書式の digest + PDF に重ねた値 (overlay.yaml) の digest (form-case-pipeline.md #docx)
        fr.pop("sheet_digest_v3", None)
        fr.pop("sheet_digest", None)
        fr["docx_digest"] = DF.docx_digest(wb)
        od = DF.overlay_digest(wb)
        if od:
            fr["overlay_digest"] = od
        return fr
    if spec is not None and wb is not None and wb.exists():
        from . import fingerprint as FP

        writer = FP.last_writer(wb)
        if writer != FP.MAC_EXCEL:
            # 別の app が最後に保存した workbook は、 次に Mac Excel が保存した時に列幅・空 cell の書式・図形の位置が
            # 格子に丸め直される (fingerprint.py 冒頭の実測) = 凍結の後に 🔴 の誤検出になる。 先に Mac Excel の形にする
            raise M.ManifestError(
                f"workbook {wb.name} の最後の保存が Mac Excel でない ({writer or '不明'}) = 書式の fingerprint (v3) が次の "
                f"Excel の保存で揺れる。 先に formcase.py normalize {m.case_dir} {doc_id} (Excel で開いて保存するだけ、 "
                "値は変えない) → freeze")
        fr["sheet_digest"] = M.sheet_digests(wb, S.group_sheets(spec, group_id))
        missing = [s for s, v in fr["sheet_digest"].items() if v == "missing"]
        if missing:
            raise M.ManifestError(f"workbook {wb.name} に sheet {missing} が無い (spec の group 定義と合わない)")
        fr["sheet_digest_v3"] = FP.sheet_digests_v3(wb, S.group_sheets(spec, group_id), fr["sheet_digest"])
    return fr


PAPER_FIELDS = ("paper", "paper_diff", "paper_basis", "paper_commit")


def _paper_fields(state: str, paper: str | None, paper_diff: str | None, paper_basis: str | None,
                  paper_commit: str | None) -> dict:
    """freeze / annotate が書く paper 系 field を検査して返す (書き込みはしない)。"""
    if state not in M.PAPER_STATES:
        if paper or paper_diff or paper_basis or paper_commit:
            raise M.ManifestError(f"paper は紙になった state ({M.PAPER_STATES}) の issue だけに書く (state = {state})")
        return {}
    if paper is None:
        raise M.ManifestError(
            f"{state} の freeze には --paper same|differs|unverified が要る (= 記録した file / sheet が紙・送った file と"
            " 同じか。 同じ run で作った / 刷った時の commit と照合できた = same、 違うと分かっている = differs、"
            " どの版が紙になったか分からない = unverified)")
    if paper not in M.PAPER_VALUES:
        raise M.ManifestError(f"--paper は {M.PAPER_VALUES} のどれか ({paper!r})")
    if paper in M.PAPER_MARK and not (paper_diff or "").strip():
        raise M.ManifestError(f"--paper {paper} には --paper-diff (何が違う / 何が分からないか) が要る")
    if paper == "same" and paper_diff:
        raise M.ManifestError("--paper same に --paper-diff は書かない (根拠は --paper-basis)")
    if paper_commit and not M.COMMIT_RE.match(paper_commit):
        raise M.ManifestError(f"--paper-commit {paper_commit!r} が commit hash でない")
    out = {"paper": paper}
    for k, v in (("paper_diff", paper_diff), ("paper_basis", paper_basis), ("paper_commit", paper_commit)):
        if v:
            out[k] = v.strip()
    return out


def freeze(m: M.Manifest, doc_id: str, group_id: str, state: str, date: str | None = None,
           evidence: str | None = None, note: str | None = None, paper: str | None = None,
           paper_diff: str | None = None, paper_basis: str | None = None, paper_commit: str | None = None,
           date_ack: str | None = None) -> dict:
    if state not in M.FROZEN_STATES:
        raise M.ManifestError(f"freeze の state は {M.FROZEN_STATES} のどれか (draft に戻すのは reopen)")
    pf = _paper_fields(state, paper, paper_diff, paper_basis, paper_commit)  # 計算の前に拒否する
    if date_ack and date != "unknown":
        raise M.ManifestError("--date-ack は --date unknown と一緒にだけ使う")
    g = m.group(doc_id, group_id)
    cur = g.setdefault("current", {"state": "draft"})
    date = date or _today()
    if cur.get("state") in M.FROZEN_STATES:
        # 凍結 → 凍結 (例: printed → submitted)。 印刷後に sheet / 出力が変わっていたら拒否 (= 旧紙の提出)
        old = cur.get("frozen") or {}
        wbp = m.workbook(doc_id)
        vals, fmts = M.frozen_sheet_changes(old, wbp) if (wbp is not None and wbp.exists()) else ([], [])
        drift = vals + [f"{s} (書式)" for s in fmts]
        for k, v in (old.get("sha256") or {}).items():
            p = m.case_dir / str((cur.get("outputs") or {}).get(k, ""))
            if not p.is_file() or M.file_sha256(p) != v:
                drift.append(f"output:{k}")
        if drift:
            raise M.ManifestError(
                f"{doc_id}/{group_id} は {cur.get('state')} {cur.get('date', '')} の後に {drift} が変わっている = "
                "手元の紙 / 送った file は旧版。 reopen して作り直した新 issue を freeze する")
        new = record_frozen(m, doc_id, group_id, cur)
    else:
        new = record_frozen(m, doc_id, group_id, cur)
    log = list(cur.get("log") or [])
    stamp = date if date != "unknown" else f"(日付不明、 {_today()} に記録)"
    log.append(f"{stamp} {state}" + (f" ({evidence})" if evidence else ""))
    if not new.get("sheet_digest_v3"):
        new.pop("sheet_digest_v3", None)
    cur.update({"state": state, "date": date, "frozen": new, "log": log})
    for k in PAPER_FIELDS:          # 前の state の paper 注記を持ち越さない (state ごとに言い直す)
        cur.pop(k, None)
    cur.update(pf)
    cur.pop("date_ack", None)
    if date_ack:
        cur["date_ack"] = date_ack.strip()
    if evidence:
        cur["evidence"] = evidence
    if note:
        cur["note"] = note
    _place(cur)
    return cur


HEAD_KEYS = ("state", "issue", "date", "date_ack", "outputs", "outputs_ack", "commit", "evidence") + PAPER_FIELDS
TAIL_KEYS = ("note", "reopened", "log", "frozen")


def _place(it: dict) -> None:
    """issue の key を読む順に並べ直す (state・日付・出力・根拠・紙との関係 → その他 → note・log・frozen)。 値は変えない。"""
    items = dict(it)
    it.clear()
    for k in HEAD_KEYS:
        if k in items:
            it[k] = items.pop(k)
    rest = {k: v for k, v in items.items() if k not in TAIL_KEYS}
    it.update(rest)
    for k in TAIL_KEYS:
        if k in items:
            it[k] = items[k]


def issue_ref(g: dict, issue: str | None) -> dict:
    """``current`` (既定) / ``previous[N]`` / ``N`` で issue を選ぶ。"""
    if issue in (None, "", "current"):
        cur = g.get("current")
        if not cur:
            raise M.ManifestError("current issue が無い")
        return cur
    s = str(issue)
    s = s[len("previous["):-1] if s.startswith("previous[") and s.endswith("]") else s
    try:
        return (g.get("previous") or [])[int(s)]
    except (ValueError, IndexError):
        raise M.ManifestError(f"issue {issue!r} が無い (current / previous[N])") from None


def annotate(m: M.Manifest, doc_id: str, group_id: str, issue: str | None = None, paper: str | None = None,
             paper_diff: str | None = None, paper_basis: str | None = None, paper_commit: str | None = None,
             date_ack: str | None = None, outputs_ack: str | None = None, note: str | None = None) -> dict:
    """凍結 issue に「記録と紙の関係」「日付不明の確認済み」「出力 file が記録に無いことの確認済み」 を書く。
    note = issue の note を置き換える (draft も可。 状態の説明の置き場 = README に状態を書かない)。
    sha256 / sheet_digest / state / date は触らない (= 後から分かった事実の注記。 freeze を打ち直すと digest を今の
    tree で取り直してしまうので使わない)。"""
    it = issue_ref(m.group(doc_id, group_id), issue)
    st = it.get("state")
    if outputs_ack is not None:
        if st not in M.FROZEN_STATES:
            raise M.ManifestError(f"outputs_ack は凍結 issue だけに書く (state = {st})")
        if it.get("outputs"):
            raise M.ManifestError("outputs_ack は出力 file の記録が無い issue だけに書く (この issue には outputs がある)")
        if not outputs_ack.strip():
            raise M.ManifestError("outputs_ack には理由 (どこを探して無かったか) を書く")
        it["outputs_ack"] = outputs_ack.strip()
    if paper is not None or paper_diff or paper_basis or paper_commit:
        pf = _paper_fields(st, paper, paper_diff, paper_basis, paper_commit)
        for k in PAPER_FIELDS:
            it.pop(k, None)
        it.update(pf)
    if date_ack is not None:
        if str(it.get("date") or "") != "unknown":
            raise M.ManifestError(f"date_ack は date: unknown の issue だけに書く (date = {it.get('date')!r})")
        it["date_ack"] = date_ack.strip()
    if note is not None:
        if note.strip():
            it["note"] = note.strip()
        else:
            it.pop("note", None)
    _place(it)
    return it


def versioned(rel: str, n: int) -> str:
    p = Path(rel)
    stem = p.stem
    import re
    stem = re.sub(r"_r\d+$", "", stem)
    return str(p.with_name(f"{stem}_r{n}{p.suffix}"))


def reopen(m: M.Manifest, doc_id: str, group_id: str, reason: str, date: str | None = None) -> dict:
    if not reason or not reason.strip():
        raise M.ManifestError("reopen には理由 (--reason) が要る (= 紙の履歴に残る)")
    g = m.group(doc_id, group_id)
    cur = g.get("current") or {}
    if cur.get("state") not in M.FROZEN_STATES:
        raise M.ManifestError(f"{doc_id}/{group_id} は既に draft = reopen 不要 (そのまま build できる)")
    date = date or _today()
    prev = dict(cur)
    prev["reopened"] = f"{date} {reason.strip()}"
    g.setdefault("previous", []).append(prev)
    n = int(cur.get("issue") or 1) + 1
    new = {"state": "draft", "issue": n,
           "outputs": {k: versioned(v, n) for k, v in (cur.get("outputs") or {}).items()},
           "note": f"reopen {date}: {reason.strip()}"}
    g["current"] = new
    return new
