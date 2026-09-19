"""案件 manifest の検査 (構造 + 凍結の不変条件 + 印刷した紙の鮮度)。 gate の実行は gates.py。

findings = [(level, where, msg)]。 level = 🔴 FAIL / 🟡 WARN / 🔵 INFO / 🧊 FROZEN (= 凍結 group を
見ていないことを見える形で出す行。 FAIL でも黙った skip でもない) / 📄 PAPER (= 記録が紙と違う・どの版か不明、
の事実。 問題の件数にも exit code にも入れないが --quiet でも出す)。
"""
from __future__ import annotations

from pathlib import Path

from . import manifest as M
from . import specs as S


def check_case(m: M.Manifest, digests: bool = True) -> list:
    f = list(M.validate(m, S.get))
    for doc_id, doc, gid, g in m.iter_groups():
        spec = S.get(doc.get("form"))
        cur = g.get("current") or {}
        where = f"{doc_id}/{gid}"
        st = cur.get("state")
        # --- 同じ出力 path を、 bytes の記録 (commit) を持たない前の凍結 issue と共有していないか ----
        cur_paths = set((cur.get("outputs") or {}).values())
        for i, prev in enumerate(g.get("previous") or []):
            if prev.get("state") in M.FROZEN_STATES and not prev.get("commit"):
                shared = cur_paths & set((prev.get("outputs") or {}).values())
                if shared:
                    f.append((M.FAIL, f"{where} previous[{i}]",
                              f"前の凍結 issue と current が同じ出力 path {sorted(shared)} を使っている — "
                              "前の版の bytes がどの commit にあるかを `commit:` に書く (上書き済みの記録)"))
        if st not in M.FROZEN_STATES:
            continue
        fr = cur.get("frozen") or {}
        label = f"{st} {cur.get('date', '')}".strip()
        # --- 凍結出力の bytes ---------------------------------------------------------------
        for role, rel in (cur.get("outputs") or {}).items():
            p = m.case_dir / rel
            want = (fr.get("sha256") or {}).get(role)
            if want and p.exists():
                got = M.file_sha256(p)
                if got != want:
                    f.append((M.FAIL, where,
                              f"凍結出力 {rel} ({label}) の bytes が記録と違う — 提出物を上書きした疑い。 "
                              f"git log -- '{rel}' で戻す (作り直すなら formcase.py reopen)"))
        # --- 凍結 group の sheet の値 --------------------------------------------------------
        want_d = fr.get("sheet_digest") or fr.get("docx_digest") or {}
        wb = m.workbook(doc_id)
        if digests and want_d and wb is not None and wb.exists() and spec is not None:
            try:
                got = M.frozen_sheet_changes(fr, wb)
            except M.Locked:
                f.append((M.WARN, where, "workbook が git-crypt locked = sheet digest 未検査"))
                got = None
            if got is not None:
                changed, fmt_only = got
                ver = M.frozen_digest_version(fr)
                if fmt_only:
                    what = ("段落の揃え・字の大きさ・太字・表の列幅・用紙と余白" if ver == "docx" else
                            "罫線・色・空 cell の罫線/塗り・表示書式・font・揃え・結合・行高・列幅・印刷設定・条件付き書式・"
                            "header/footer・図形/form control" if ver == "v3"
                            else "表示書式・font・揃え・結合・行高・列幅・印刷設定")
                    f.append((M.FAIL, where, f"{st} ({label}) の後に sheet {fmt_only} の**書式** ({what}、 記録 = {ver}) が"
                                             "変わった = 値が同じでも紙の見た目が違う。 意図した作り直しなら formcase.py reopen"))
                if changed:
                    if st == "submitted":
                        msg = (f"提出済み ({label}) の sheet {changed} の値が提出時の記録から変わっている — "
                               "提出記録の改変。 意図した訂正 (差し戻し対応) なら formcase.py reopen で新 issue に")
                    else:
                        msg = (f"{st} ({label}) の後に sheet {changed} の値が変わった = 手元の紙 / 送った file は旧版 "
                               "(STALE)。 formcase.py reopen で新 issue を作って刷り直す / 差し替える")
                    f.append((M.FAIL, where, msg))
        elif digests and spec is not None and wb is not None and not want_d:
            f.append((M.WARN, where, f"凍結 issue ({label}) に sheet_digest の記録が無い = 提出後の改変を検出できない"))
        if st == "unknown":
            f.append((M.WARN, where, f"状態 unknown: {cur.get('note', '')} → owner に確認して freeze し直す"))
    # --- legacy driver の宣言 ---------------------------------------------------------------
    for doc_id, doc in m.documents.items():
        drv = doc.get("drivers") or {}
        names = drv if isinstance(drv, list) else list(drv.keys())
        for n in names:
            p = m.case_dir / n
            if not p.exists():
                f.append((M.WARN, doc_id, f"drivers に宣言された {n} が無い"))
            elif "legacy_guard" not in p.read_text(encoding="utf-8", errors="replace"):
                f.append((M.FAIL, doc_id, f"legacy driver {n} が formcase.legacy_guard を呼んでいない "
                                          "(= 凍結出力を上書きできる経路が残る)"))
    return f


def frozen_lines(m: M.Manifest) -> list:
    """凍結 group を 1 行ずつ (gate が見ない範囲を見える形で出す)。"""
    out = []
    for doc_id, doc, gid, g in m.iter_groups():
        cur = g.get("current") or {}
        if cur.get("state") in M.FROZEN_STATES:
            out.append((M.FROZEN, f"{doc_id}/{gid}",
                        f"{cur.get('state')} {cur.get('date', '')} = 凍結 (検査・再生成の対象外)".strip()))
    return out


def render(case_label: str, findings: list, quiet_ok: bool = False) -> bool:
    """🔴/🟡 と 📄 (記録と紙の差 = 常に見せる事実) を出す。 🔵 は --quiet でない時だけ。 戻り値 = 🔴 があるか。

    📄 は問題の件数に入れない (exit code を変えない = 毎回の催促にしない) が、 --quiet でも黙らせない。"""
    bad = any(x[0] == M.FAIL for x in findings)
    shown = [x for x in findings if x[0] != M.INFO or not quiet_ok]
    problems = [x for x in shown if x[0] not in (M.INFO, M.PAPER)]
    if not shown:
        if not quiet_ok:
            print(f"✅ {case_label}")
        return bad
    print(f"── {case_label}" + ("" if problems else "  (問題なし、 以下は記録の注記)"))
    order = {M.FAIL: 0, M.WARN: 1, M.PAPER: 2, M.INFO: 3}
    for lv, where, msg in sorted(shown, key=lambda x: order.get(x[0], 9)):
        print(f"   {lv} {where}: {msg}")
    return bad


def status_rows(m: M.Manifest) -> list:
    """(doc, form, group, state, date, outputs, note, 注記行 [...])。 注記行 = 前の issue も含む 📄 と date_ack。"""
    rows = []
    for doc_id, doc, gid, g in m.iter_groups():
        cur = g.get("current") or {}
        extra = []
        for label, issue in [("", cur)] + [(f"前 {x.get('state')} {x.get('date', '')}: ", x)
                                           for x in (g.get("previous") or [])]:
            line = M.paper_line(issue)
            if line:
                extra.append(label + line)
            elif issue.get("state") in M.PAPER_STATES and not issue.get("paper"):
                extra.append(label + "📄 (paper: 未記入 = 記録が紙と同じか分からない)")
            if issue.get("date_ack"):
                extra.append(label + f"🗓 日付不明 (owner 確認済: {issue['date_ack']})")
            if issue.get("outputs_ack"):
                extra.append(label + f"🗂 出力 file は記録に無い (確認済: {issue['outputs_ack']})")
        rows.append((doc_id, doc.get("form"), gid, cur.get("state"), cur.get("date", ""),
                     ", ".join(f"{k}={Path(v).name}" for k, v in (cur.get("outputs") or {}).items()),
                     cur.get("note", ""), extra))
    return rows
