"""submission.yaml (案件ごとの提出状態) の読み書きと凍結の判定。

schema (= formcase/1) の説明は ``conventions/form-case-pipeline.md`` #manifest。 ここはその実行系。

用語:
  document  1 つの workbook (+ そこから作る出力) の単位 (= 1 人 1 様式の書類)
  group     spec の ``groups:`` が定義する page のまとまり (例: 事前に出す p.1-4 / 帰着後に出す p.5-6)
  issue     group を 1 回発行した記録。 ``current`` が今の issue、 ``previous`` が過去の issue
  state     draft / printed / sent / submitted / unknown。 draft 以外は凍結

凍結 (= draft 以外) の issue は:
  - 出力 file の bytes を ``frozen.sha256`` に記録し、 変わったら check が 🔴
  - group の sheet (+ depends) の値の digest を ``frozen.sheet_digest``、 書式の digest を ``frozen.sheet_digest_v3``
    (新しい freeze。 それ以前の issue は ``sheet_digest_v2`` か値だけ) に記録し、 変わったら 🔴
  - 出力 path に build が書かない / legacy driver が止まる / pre-commit が staged 変更を止める
作り直すときは ``reopen`` が新しい draft issue (出力名に ``_r<N>``) を作る = 凍結 file は残る。

凍結の記録は「freeze した時の tree」 で、 刷った・送った・出したものと同じとは限らない。 printed / sent / submitted の
issue は ``paper: same|differs|unverified`` (+ ``paper_diff`` / ``paper_basis`` / ``paper_commit``) でその関係を持ち、
``date: unknown`` を owner に確認済みなら ``date_ack`` を持つ (正本 = ``conventions/form-case-pipeline.md`` #paper)。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import warnings
from pathlib import Path

import yaml

SCHEMA = "formcase/1"
MANIFEST_NAME = "submission.yaml"
STATES = ("draft", "printed", "sent", "submitted", "unknown")
FROZEN_STATES = tuple(s for s in STATES if s != "draft")
# 紙 (または送った file) になった state。 この issue は「記録が紙と同じか」 を paper: に書く
PAPER_STATES = ("printed", "sent", "submitted")
PAPER_VALUES = ("same", "differs", "unverified")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
GITCRYPT_MAGIC = b"\x00GITCRYPT"

# 🔵 INFO = check --quiet では出さない注記 / 📄 PAPER = 記録と紙の差 (常に出す事実、 問題の件数には数えない)
FAIL, WARN, INFO, FROZEN, PAPER = "🔴", "🟡", "🔵", "🧊", "📄"
PAPER_MARK = {"differs": "📄≠ 記録は提出した紙と違う", "unverified": "📄? どの版が紙になったか不明"}


def paper_line(issue: dict) -> str | None:
    """differs / unverified の issue を 1 行で (status / check / marker が同じ文言を使う)。 same・未記入は None。"""
    p = issue.get("paper")
    if p not in PAPER_MARK:
        return None
    diff = " ".join(str(issue.get("paper_diff") or "(paper_diff 未記入)").split())
    commit = f" [紙の版 = commit {issue['paper_commit']}]" if issue.get("paper_commit") else ""
    return f"{PAPER_MARK[p]}: {diff}{commit}"


class ManifestError(Exception):
    pass


class Locked(ManifestError):
    """git-crypt が unlock されていない (= 読めない。 fail-open で SKIP を宣言する側)。"""


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------
def read_bytes(path: Path) -> bytes:
    b = Path(path).read_bytes()
    if b.startswith(GITCRYPT_MAGIC):
        raise Locked(f"git-crypt locked: {path}")
    return b


def load(case_dir) -> "Manifest":
    case_dir = Path(case_dir).resolve()
    if case_dir.is_file():
        case_dir = case_dir.parent
    p = case_dir / MANIFEST_NAME
    if not p.exists():
        raise ManifestError(f"{MANIFEST_NAME} が無い: {case_dir}")
    data = yaml.safe_load(read_bytes(p).decode("utf-8"))
    return Manifest(case_dir, data)


def loads(text: str, case_dir) -> "Manifest":
    return Manifest(Path(case_dir).resolve(), yaml.safe_load(text))


def dump_text(data: dict) -> str:
    from . import config as CF

    head = ("# formcase manifest (schema formcase/1)。 状態を変えるときは手で書き換えず\n"
            f"#   python3 {CF.cli()} freeze|annotate|reopen|status …\n"
            f"# を使う (sha256 / sheet_digest を記録するため)。 使い方の正本 = {CF.usage_doc()}\n")
    body = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000,
                     default_flow_style=False)
    return head + body


class _Dumper(yaml.SafeDumper):
    pass


def _str_repr(dumper, s):
    style = "|" if "\n" in s else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


_Dumper.add_representer(str, _str_repr)


class Manifest:
    def __init__(self, case_dir: Path, data: dict):
        self.case_dir = Path(case_dir)
        self.data = data or {}
        self.path = self.case_dir / MANIFEST_NAME

    # -- 構造 --------------------------------------------------------------
    @property
    def documents(self) -> dict:
        return self.data.get("documents") or {}

    def doc(self, doc_id: str) -> dict:
        d = self.documents.get(doc_id)
        if d is None:
            raise ManifestError(f"document {doc_id!r} が manifest に無い ({self.path})")
        return d

    def group(self, doc_id: str, group_id: str) -> dict:
        g = (self.doc(doc_id).get("groups") or {}).get(group_id)
        if g is None:
            raise ManifestError(f"group {doc_id}/{group_id} が manifest に無い ({self.path})")
        return g

    def iter_groups(self):
        for doc_id, d in self.documents.items():
            for gid, g in (d.get("groups") or {}).items():
                yield doc_id, d, gid, g

    def workbook(self, doc_id: str) -> Path | None:
        wb = self.doc(doc_id).get("workbook")
        return (self.case_dir / wb) if wb else None

    def out_path(self, rel: str) -> Path:
        return self.case_dir / rel

    # -- 凍結 --------------------------------------------------------------
    def frozen_outputs(self) -> dict:
        """{abs path: (doc, group, issue state)} = 書いてはいけない出力 (current + previous の凍結 issue)。"""
        out = {}
        for doc_id, _d, gid, g in self.iter_groups():
            for issue in [g.get("current") or {}] + list(g.get("previous") or []):
                if issue.get("state") in FROZEN_STATES and not issue.get("commit"):
                    for rel in (issue.get("outputs") or {}).values():
                        out[str(self.out_path(rel).resolve())] = (doc_id, gid, issue.get("state"))
        return out

    def group_is_frozen(self, doc_id: str, group_id: str) -> bool:
        cur = self.group(doc_id, group_id).get("current") or {}
        return cur.get("state") in FROZEN_STATES

    def drivers_of(self, script_name: str):
        """legacy driver が書く (doc, group) の list。 ``drivers:`` に {name: [groups]} か [name] で宣言。"""
        hits = []
        for doc_id, d in self.documents.items():
            drv = d.get("drivers") or {}
            if isinstance(drv, list):
                drv = {n: list((d.get("groups") or {}).keys()) for n in drv}
            if script_name in drv:
                for gid in drv[script_name] or list((d.get("groups") or {}).keys()):
                    hits.append((doc_id, gid))
        return hits

    # -- save --------------------------------------------------------------
    def save(self):
        self.path.write_text(dump_text(self.data), encoding="utf-8")


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------
def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_value(v):
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return repr(int(v))
    return repr(v)


def sheet_digests(workbook, sheets) -> dict:
    """sheet 名 → 値 (数式は数式文字列) の digest。 書式・行高は含めない (= Excel の再保存で揺れるため)。

    存在しない sheet は ``missing`` を返す (= 黙って無視しない)。
    """
    import openpyxl  # 遅延 import (= manifest だけ読む用途で openpyxl を要求しない)

    read_bytes(workbook)  # locked 判定
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(workbook)
    out = {}
    for name in sheets:
        if name not in wb.sheetnames:
            out[name] = "missing"
            continue
        h = hashlib.sha256()
        for row in wb[name].iter_rows():
            for c in row:
                if c.value is None or (isinstance(c.value, str) and c.value == ""):
                    continue
                h.update(f"{c.coordinate}\t{_norm_value(c.value)}\n".encode("utf-8"))
        out[name] = h.hexdigest()[:24]
    return out


def _half(x):
    """行高 (pt)・列幅 (文字) を 0.5 刻みに丸める (Excel / openpyxl の保存で 1.25 → 1.1640625 のように揺れる分を吸う)。"""
    return None if x is None else round(float(x) * 2) / 2


def _format_items(ws):
    """紙の見た目を変える書式の要素を順序つきの行にする (値は含めない = v1 の digest が持つ)。

    射程 = 値のある cell の表示書式・font の大きさ/太字・横/縦揃え・折り返し + 結合範囲 + 行高 + 列幅 +
    印刷範囲 + page setup (向き・用紙・倍率・fitTo・余白) + 手動改ページ。 罫線・色は含めない (空の cell の書式は
    Excel の再保存で揺れる実測があるので、 cell の書式は値のある cell だけ)。"""
    items = []
    for row in ws.iter_rows():
        for c in row:
            if c.value is None or (isinstance(c.value, str) and c.value == ""):
                continue
            f, a = c.font, c.alignment
            items.append(f"cell\t{c.coordinate}\t{c.number_format}\t{f.sz}\t{bool(f.b)}\t{a.horizontal}\t"
                         f"{a.vertical}\t{bool(a.wrap_text)}\t{bool(a.shrink_to_fit)}")
    items += sorted(f"merge\t{m}" for m in ws.merged_cells.ranges)
    items += [f"row\t{r}\t{_half(d.height)}" for r, d in sorted(ws.row_dimensions.items()) if d.height is not None]
    items += [f"col\t{k}\t{_half(d.width)}" for k, d in sorted(ws.column_dimensions.items())
              if d.width is not None and d.customWidth]
    ps, pm = ws.page_setup, ws.page_margins
    fit = ws.sheet_properties.pageSetUpPr.fitToPage if ws.sheet_properties.pageSetUpPr else None
    items.append(f"print\t{ws.print_area}\t{ps.orientation}\t{ps.paperSize}\t{ps.scale}\t{ps.fitToWidth}\t"
                 f"{ps.fitToHeight}\t{fit}")
    items.append("margins\t" + "\t".join(f"{_half(getattr(pm, k))}" for k in ("left", "right", "top", "bottom")))
    items += [f"break\t{b.id}" for b in ws.row_breaks.brk]
    return items


def sheet_digests_v2(workbook, sheets) -> dict:
    """sheet 名 → {"values": v1 と同じ値の digest, "format": 書式の digest}。 存在しない sheet は "missing"。

    v1 (``sheet_digests``) は値と数式だけで、 行高・結合・表示書式だけを変えた改変 (= 紙は変わる) を見なかった
    (実測)。 既存の凍結 issue は v1 のまま有効、 新しい freeze は v1 と v2 を両方記録し、
    check は在る方を照合する (manifest の ``frozen.sheet_digest_v2``)。"""
    import openpyxl

    read_bytes(workbook)
    v1 = sheet_digests(workbook, sheets)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(workbook)
    out = {}
    for name in sheets:
        if name not in wb.sheetnames:
            out[name] = "missing"
            continue
        h = hashlib.sha256("\n".join(_format_items(wb[name])).encode("utf-8")).hexdigest()[:24]
        out[name] = {"values": v1[name], "format": h}
    return out


def frozen_sheet_changes(fr: dict, workbook) -> tuple:
    """(値が変わった sheet, 書式だけが変わった sheet)。 凍結の記録 ``fr`` に在る版のうち sheet ごとに一番新しい版
    (v3 → v2 → v1) で、 今の workbook を同じ版で計算して比べる (= 前の版の issue を今の版で裁かない)。"""
    from . import fingerprint as FP

    if fr.get("docx_digest"):                 # Word 様式 (docx_form.py): 文字 / 書式 / PDF に重ねた値
        from . import docx_form as DF

        got = DF.docx_digest(workbook)
        want = fr["docx_digest"]
        values = ["docx"] if got.get("values") != want.get("values") else []
        fmt = ["docx"] if not values and got.get("format") != want.get("format") else []
        od = DF.overlay_digest(workbook)
        if fr.get("overlay_digest") and od is not None and od != fr["overlay_digest"]:
            values.append("overlay.yaml")
        return values, fmt
    v1w, v2w, v3w = fr.get("sheet_digest") or {}, fr.get("sheet_digest_v2") or {}, fr.get("sheet_digest_v3") or {}
    sheets = list(dict.fromkeys(list(v3w) + list(v2w) + list(v1w)))
    if not sheets:
        return [], []
    got1 = sheet_digests(workbook, sheets)
    only2 = [s for s in v2w if s not in v3w]
    got2 = sheet_digests_v2(workbook, only2) if only2 else {}
    got3 = FP.sheet_digests_v3(workbook, list(v3w), got1) if v3w else {}
    values, fmt = [], []
    for s in sheets:
        if s in v3w:
            w, g = v3w[s], got3.get(s)
        elif s in v2w:
            w, g = v2w[s], got2.get(s)
        else:
            if got1.get(s) != v1w[s]:
                values.append(s)
            continue
        if not isinstance(w, dict) or not isinstance(g, dict):
            if w != g:
                values.append(s)
            continue
        if g.get("values") != w.get("values"):
            values.append(s)
        elif g.get("format") != w.get("format"):
            fmt.append(s)
    return values, fmt


def frozen_digest_version(fr: dict) -> str:
    if fr.get("docx_digest"):
        return "docx"
    return "v3" if fr.get("sheet_digest_v3") else ("v2" if fr.get("sheet_digest_v2") else "v1")


def has_source_digest(fr: dict) -> bool:
    """凍結の記録が元 file (workbook / docx) の digest を持つか。"""
    return bool(fr.get("sheet_digest") or fr.get("docx_digest"))


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def _paper_findings(issue: dict, iw: str, st: str) -> list:
    """紙になった issue の paper: (記録 = 紙か)。 未記入 WARN / 値の誤り・差の説明なし FAIL / 差は 📄 で常に見せる。"""
    f = []
    p = issue.get("paper")
    if p is None:
        f.append((WARN, iw, f"{st} の issue に paper: (same / differs / unverified) が無い = 記録が紙と同じか分からない"))
        return f
    if p not in PAPER_VALUES:
        f.append((FAIL, iw, f"paper: {p!r} は {PAPER_VALUES} のどれでもない"))
        return f
    if p in PAPER_MARK and not str(issue.get("paper_diff") or "").strip():
        f.append((FAIL, iw, f"paper: {p} には paper_diff: (何が違う / 何が分からないか、 分かれば紙の版の在り処) が要る"))
    if p == "same" and issue.get("paper_diff"):
        f.append((WARN, iw, "paper: same に paper_diff: がある (差があるなら differs、 same の根拠は paper_basis:)"))
    pc = issue.get("paper_commit")
    if pc is not None and not COMMIT_RE.match(str(pc)):
        f.append((FAIL, iw, f"paper_commit: {pc!r} が commit hash (7-40 桁の 16 進) でない"))
    line = paper_line(issue)
    if line and str(issue.get("paper_diff") or "").strip():
        f.append((PAPER, iw, line))
    return f


def validate(m: Manifest, spec_lookup, check_files: bool = True) -> list:
    """manifest の形の検査。 spec_lookup(form_id) -> spec dict | None。 findings = [(level, where, msg)]。"""
    f = []
    d = m.data
    if d.get("schema") != SCHEMA:
        f.append((FAIL, "schema", f"schema が {SCHEMA!r} でない ({d.get('schema')!r})"))
    if not m.documents:
        f.append((FAIL, "documents", "document が 1 つも無い"))
    for doc_id, doc in m.documents.items():
        where = doc_id
        form = doc.get("form")
        untyped = form == "other"     # spec の無い書類 (例: 宿泊証明書の事前印字)。 bytes の凍結だけを持つ
        spec = spec_lookup(form) if form and not untyped else None
        if not form:
            f.append((FAIL, where, "form (spec id、 spec の無い書類は other) が無い"))
        elif spec is None and not untyped:
            f.append((FAIL, where, f"form {form!r} に合う spec (reference/*.yaml の meta.id) が無い"))
        wb = doc.get("workbook")
        if check_files and wb and not (m.case_dir / wb).exists():
            f.append((FAIL, where, f"workbook が無い: {wb}"))
        groups = doc.get("groups") or {}
        if not groups:
            f.append((FAIL, where, "group が 1 つも無い"))
        sgroups = (spec or {}).get("groups") or {}
        for gid, g in groups.items():
            gw = f"{doc_id}/{gid}"
            if spec is not None and gid not in sgroups:
                f.append((FAIL, gw, f"spec {form!r} に group {gid!r} が無い (spec の groups: {list(sgroups)})"))
            issues = [("current", g.get("current"))] + [(f"previous[{i}]", x)
                                                        for i, x in enumerate(g.get("previous") or [])]
            if not g.get("current"):
                f.append((FAIL, gw, "current issue が無い"))
            for label, issue in issues:
                if not issue:
                    continue
                iw = f"{gw} {label}"
                st = issue.get("state")
                if st not in STATES:
                    f.append((FAIL, iw, f"state {st!r} は {STATES} のどれでもない"))
                    continue
                if st in PAPER_STATES:
                    dt = str(issue.get("date") or "")
                    if dt == "unknown":
                        if issue.get("date_ack"):
                            f.append((INFO, iw, f"{st} の日付は不明のまま (owner 確認済: {issue['date_ack']})"))
                        elif label == "current":
                            f.append((WARN, iw, f"{st} の日付が記録から分からない (date: unknown) → owner に確認 "
                                                "(分からないと確認できたら date_ack: に書く)"))
                    elif not DATE_RE.match(dt):
                        f.append((FAIL, iw, f"state {st} なのに date (YYYY-MM-DD か unknown) が無い"))
                    f += _paper_findings(issue, iw, st)
                else:
                    for k in ("paper", "paper_diff", "paper_basis", "paper_commit"):
                        if k in issue and st == "draft":
                            f.append((WARN, iw, f"draft の issue に {k}: がある (紙になった issue だけに書く)"))
                if issue.get("date_ack") and str(issue.get("date") or "") != "unknown":
                    f.append((WARN, iw, "date_ack: は date: unknown の issue だけに書く"))
                if st == "unknown" and not issue.get("note"):
                    f.append((WARN, iw, "state unknown には何が分からないかの note を書く"))
                outs = issue.get("outputs") or {}
                ack = str(issue.get("outputs_ack") or "").strip()
                if label == "current" and not outs and st in FROZEN_STATES:
                    if ack:
                        f.append((INFO, iw, f"出力 file は記録に無い (確認済: {ack})"))
                    else:
                        f.append((WARN, iw, "outputs が無い (= 何を発行したか追えない)。 folder と git history に発行した file が"
                                            "本当に無いと確かめたら annotate --outputs-ack に理由を書く"))
                if ack and outs:
                    f.append((WARN, iw, "outputs_ack: は出力 file の記録が無い issue だけに書く (outputs があるなら消す)"))
                if label == "current":
                    for role, rel in outs.items():
                        p = m.case_dir / rel
                        if check_files and st in FROZEN_STATES and not p.exists():
                            f.append((FAIL, iw, f"凍結 issue の出力 {role}={rel} が無い"))
                if st in FROZEN_STATES and label == "current":
                    fr = issue.get("frozen") or {}
                    if not fr.get("sha256") and outs:
                        f.append((WARN, iw, "凍結 issue に sha256 の記録が無い (freeze で記録)"))
    return f
