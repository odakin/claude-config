"""様式ごとの生成 recipe (= 値は spec と案件の workbook、 体裁は使い捨ての temp / staged copy にだけ当てる)。

build(m, doc_id, groups, out_dir) は:
  1. gate (gates.py) を group の範囲で回す。 FAIL なら何も書かない
  2. 体裁を当てて Excel で PDF 化 (元 xlsx は触らない)。 体裁の出どころは全様式で同じ 3 つ (layout.py、 form-case-pipeline.md #layout-3):
     配布雛形 (行高・印刷範囲・手動改ページ) / spec の ``render:`` (雛形の欠陥、 各 entry に理由) / 記入値の長さ (折り返し・行高)
  3. Excel の PDF を字の切れ・はみ出し gate (check-form-clipping) で見て、 引っかかった欄を折り返し → 行を伸ばして刷り直す
     (最大 FIT_ROUNDS 回)。 残れば出力を書かずに止める
  4. package から group の page を切り出し、 その group の page にだけ押印を overlay
     (設定 ``seal_mode: physical`` なら重ねずに「刷ったら押す場所」 を列挙する = 押印欄は空のまま刷る)
  5. group の出力 (print = 紙で出す版 / confirm = 押印なし / 様式固有の派生) を書く
凍結 group は作らない (呼び元が弾く)。 押印の variant は group ごとに引くので、 他 group の出力は変わらない。

temp の作り方は雛形で 2 通り:
  - openpyxl で temp workbook を作って Excel に PDF 化させる。 openpyxl の save は図形 (標題・「外部資金」 の枠・
    様式番号・㊞ の丸・斜線) を落とすので、 ``_save`` が読み込み元の workbook から同名 sheet の図形を移し直す
    (drawings.graft_drawings。 form control = checkbox は移さない)
  - 図形を移せない雛形 (画像等を参照する drawing) → 体裁は openpyxl の読み込みの上で計算し、
    差分だけを Excel の操作として staged copy に当てて PDF 化する (layout.snapshot / excel_ops、 excel.ops_lines)

**様式ごとの recipe はこの module が持たない** (= 雛形の page 構成・sheet 名・押印位置・出力名は呼び元のもの)。
呼び元は設定の ``recipes`` が指す python file で ``Recipe`` を継承したクラスを書き、 ``register(form_id, cls)``
で登録する。 docx 様式は spec から全部読めるので ``RecipeDocx`` が汎用に扱う。
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from . import config as CF
from . import excel as X
from . import fidelity as FD
from . import gates as GT
from . import layout as LY
from . import specs as S

CC = Path(__file__).resolve().parent.parent          # 同じ repo の scripts/
sys.path.insert(0, str(CC / "lib"))
import print_pages as PP  # noqa: E402  (刷る頁の宣言と推定、 conventions/office-automation.md#print-submission-pages-only)

SEAL_ENGINE = CC / "overlay-seal-pdf.py"
GUIDANCE_GATE = CC / "verify-form-guidance.py"
CLOSE_BOXES = CC / "close-pdf-form-boxes.py"
CLIPPING = CC / "check-form-clipping.py"
STATIC_TEXT = CC / "check-form-static-text.py"


class BuildError(Exception):
    pass


# _build が設定する「今の build」 = _save の census (spec の accept_loss) と、 照合に渡す体裁つき temp の所在
_CURRENT: dict = {"spec": None, "temp": None}


def static_text_lines(spec: dict, group: str, pdf, filled=None, blank=None) -> tuple:
    """雛形との照合 (fidelity.check_group = check-form-static-text --json)。 返り値 = (行, 止める理由 or None)。

    雛形の図形の字 (標題・区分の枠・様式番号・㊞) が無ければ**止める** (2026-09-25、 それまでは warn。 他の gate は
    書いたもの 〔記入値・字の切れ・記入要領〕 しか見ず、 雛形が元から紙に出す図形が消えても全部通った =
    form-case-pipeline.md#fidelity)。 書き換えていない cell の見出し・素刷りとの画像の数・増えた字は行に出す (warn)。
    filled = 体裁を当てた temp (無ければ案件の workbook) / blank = 素刷り。 docx 様式は雛形 docx で照合。
    検査が走らなかった時も黙らず ⚪ の行を出す (止めない = 検査の故障を違反と同じにしない)。"""
    rep = FD.check_group(spec, group, pdf, filled=filled, blank=blank)
    lines, stop = FD.report_lines(rep, spec)
    return lines, stop, rep


def case_is_scratch(case_dir, out_dir=None) -> bool:
    """照合用の build か = --out-dir で案件 dir に書かない build、 または案件 dir が設定の case_roots の外 (repo の外に複製した
    案件 = 検収・実験の build)。 D3 の「案件の数」 に数えない印 (fidelity_log の scratch)。"""
    if out_dir:
        return True
    try:
        cd = Path(case_dir).resolve()
        roots = [Path(r).resolve() for r in CF.case_roots()]
    except Exception:  # noqa: BLE001  設定が無い等 = 判断できない → 数える側に倒さない
        return True
    return not any(cd == r or r in cd.parents for r in roots)


def log_fidelity(m, doc_id: str, group: str, rep: dict, stop, out_dir) -> None:
    """雛形との照合の結果を設定 ``fidelity_log`` (jsonl) に 1 行足す (D3 の carrier = 見出しの ⚠️ / ✅ が案件ごとに残り、
    誤検出の実測が溜まる。 読み手 = 呼び元の dashboard)。 設定が無ければ何もしない。 書けなくても build は止めない。
    scratch = 照合用 (--out-dir) か repo の外に複製した案件の build (= 案件の数に数えない、 検収 2026-09-25 の指摘)。"""
    import datetime as _dt
    import json

    path = CF.fidelity_log()
    if not path or not isinstance(rep, dict) or "targets" not in rep:
        return
    rec = {"date": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "case": Path(m.case_dir).name, "doc": doc_id,
           "group": group, "scratch": case_is_scratch(m.case_dir, out_dir), "stop": bool(stop),
           "targets": [{"where": f"{t['sheet'].strip()}!{t['range']}", "page": t.get("page"),
                        "shapes": t.get("checked", 0), "missing": len(t.get("missing") or []),
                        "labels": t.get("labels_checked", 0), "missing_labels": len(t.get("missing_labels") or []),
                        "missing_label_cells": [x["cell"] for x in (t.get("missing_labels") or [])][:8],
                        "images": (t.get("blank") or {}).get("images"),
                        "template_defect": len(t.get("template_defect") or [])} for t in rep["targets"]]}
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"   ⚪ 照合の記録を書けない ({path}: {e})")


def _run(argv, label):
    r = subprocess.run([str(a) for a in argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.stdout.strip():
        print("\n".join("   " + x for x in r.stdout.rstrip().splitlines()))
    if r.returncode != 0:
        raise BuildError(f"{label} FAIL → 出力を書かずに中断")


def _seal_image() -> str:
    """印影の画像 path (設定の ``seal_image_cmd`` が 1 行で印字する。 = どの印を押すかは呼び元のもの)。"""
    cmd = CF.seal_image_cmd()
    if not cmd:
        raise BuildError("押印のある出力を作るには設定の seal_image_cmd (印影の画像 path を最後の行に印字する command) が要る")
    argv = [sys.executable if x == "python3" else os.path.expanduser(str(x)) for x in cmd]
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise BuildError(f"seal_image_cmd が印影の path を返さない ({argv}): {r.stderr.strip()[-200:]}")
    return r.stdout.strip().splitlines()[-1]


def _extract(src_pdf, pages_1based, dst):
    import fitz

    d = fitz.open(src_pdf)
    o = fitz.open()
    for p in pages_1based:
        o.insert_pdf(d, from_page=p - 1, to_page=p - 1)
    o.save(dst)
    o.close()
    d.close()


def _close_boxes(src, dst):
    """Excel が PDF で落とす結合セルの下罫線を閉じる。 開いた枠が無いと engine は出力を書かない (実測: 枠が全部
    閉じている PDF で FileNotFoundError) = その時は入力をそのまま使う。"""
    _run([sys.executable, CLOSE_BOXES, src, dst], "枠の下端を閉じる (close-pdf-form-boxes)")
    if not Path(dst).exists():
        shutil.copy2(src, dst)
    return dst


def with_copy_page(src, plain, page_index: int, dst, anchor: str | None = None, dpi: int = 300):
    """当事者に送る 1 本 (form-case-pipeline.md #recipient-send-version): 束の 1 頁 (0 始まり) だけを白黒の raster
    (= コピーに見える) に差し替える。 src = 押印済みの束 (無ければ plain)、 plain = 刷る頁の宣言を持つ押印なしの束。
    anchor を渡すと、 その頁の字にその語が無いとき止める (雛形の頁の並びが変わった)。 認印の画像の印と宣言を引き継ぐ。"""
    import fitz

    sys.path.insert(0, str(CC / "lib"))
    from seal_artifact import copy_marker

    d = fitz.open(str(src))
    if anchor is not None and anchor not in "".join(d[page_index].get_text().split()):
        raise BuildError(f"{page_index + 1} 頁目に「{anchor}」 が無い = recipe の頁の前提外")
    out = fitz.open()
    for i, pg in enumerate(d):
        if i != page_index:
            out.insert_pdf(d, from_page=i, to_page=i)
            continue
        pix = pg.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    copy_marker(d, out)
    PP.copy_record(fitz.open(str(plain)), out)
    out.save(str(dst), deflate=True)
    return Path(dst)


def _raster(src, dst, dpi=600):
    """印刷用の raster PDF (subset font の printer 化け対策、 層1 #print-raster-pdf。 pdf_form_fill と同じ作り)。
    刷る頁の宣言 (層1 print_pages) を引き継ぐ (= raster は字が無く、 刷る直前の gate が中身を読めないため)。"""
    import fitz

    d = fitz.open(src)
    out = fitz.open()
    for pg in d:
        pix = pg.get_pixmap(dpi=dpi)
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, stream=pix.tobytes("png"))
    PP.copy_record(d, out)
    out.save(dst, deflate=True)
    return dst


# ---------------------------------------------------------------------------
# 刷る頁 (form-case-pipeline.md #page-roles) — 出力は group の pages (= 窓口に出す頁) だけ。 その宣言を出力に書き込む
# ---------------------------------------------------------------------------
def check_page_anchors(pdf, spec) -> list:
    """spec の page_roles の anchor が PDF のその頁に在るか。 [(頁, anchor)] = 見つからないもの (= 雛形の頁構成が spec と違う)。
    照合の実体 = 層1 print_pages.anchor_misses (空白と全角半角を無視)。"""
    import fitz

    return PP.anchor_misses(fitz.open(str(pdf)), S.page_roles(spec))


def declare_pages(pdf, spec, group, pages, blank=None) -> list:
    """group の出力 PDF (pages = package の頁番号) に「全頁 = 窓口に出す頁」 の宣言を書く。 返り値 = 表示用の行。
    実体 = 層1 print_pages.declare_submit: spec の page_roles の無い頁 (Excel 様式) に記載例・控え・注意事項・白紙の推定が
    当たれば書かずに BuildError (= spec の page_roles に submit + anchor を書くか、 group の pages から外すかを決める)。
    page_roles で submit と宣言した頁は推定が疑わしくても止めない (anchor で中身を照合済み)、 行に出すだけ。
    宣言には雛形との照合に要るもの (雛形の path・sha256・対象・drop_shape・素刷り) も載せる = 刷る直前の preflight が
    同じ照合を回す (form-case-pipeline.md#fidelity)。"""
    import fitz

    roles = S.page_roles(spec)
    d = fitz.open(str(pdf))
    labels = [(roles.get(pp) or {}).get("label") if pp in roles else None for pp in pages]
    dropped = [{"from": k, "role": r.get("role"), "label": r.get("label", "")} for k, r in roles.items() if k not in pages]
    stop, lines = PP.declare_submit(d, labels, f"formcase {spec['meta']['id']}/{group}", dropped=dropped or None)
    if stop:
        raise BuildError(f"group {group} の出力に窓口に出さない頁に見える頁が入る (出力の頁番号): " + " / ".join(stop)
                         + "。 出す頁なら spec の page_roles に submit + anchor を書く、 出さないなら group の pages から外す "
                         "(form-case-pipeline.md #page-roles)")
    rec = PP.read_record(d)
    fid = FD.fidelity_record(spec, group, blank)
    if rec is not None and fid:
        PP.write_record(d, rec["pages"], rec.get("src", ""), rec.get("dropped"), rec.get("include_flagged"), fidelity=fid)
    tmp = Path(str(pdf) + ".decl.pdf")
    d.save(str(tmp), garbage=3, deflate=True)
    d.close()
    tmp.replace(pdf)
    return [f"group {group}: {x}" for x in lines]


def _ensure_declared(src, like) -> Path:
    """src (出力) に宣言が無ければ like (宣言済みの group の PDF) から写した copy を返す。 頁数が違えば BuildError。"""
    import fitz

    d = fitz.open(str(src))
    if PP.read_record(d) is not None:
        return Path(src)
    ref = fitz.open(str(like))
    if ref.page_count != d.page_count:
        raise BuildError(f"{Path(src).name} の頁数 {d.page_count} が group の頁数 {ref.page_count} と違う = 刷る頁の宣言を写せない")
    if not PP.copy_record(ref, d):
        raise BuildError(f"{Path(src).name} に写す刷る頁の宣言が group の PDF に無い (declare_pages の後で書き換えられた)")
    out = Path(str(src) + ".decl.pdf")
    d.save(str(out), garbage=3, deflate=True)
    return out


def stamp_hint(place_spec: str) -> str:
    """place spec (``anchor=印,occurrence=2,...``) を紙の上で探せる言い方にする (seal_mode: physical の案内)。"""
    kv = dict(x.split("=", 1) for x in str(place_spec).split(",") if "=" in x)
    anchor = kv.get("anchor")
    if not anchor:
        return f"押印の位置 ({place_spec})"
    occ = kv.get("occurrence", "1")
    return f"「{anchor}」" + (f" の {occ} 個目" if occ not in ("", "1") else "") + " の欄"


def _seal(plain, sealed, places):
    """places = [(page_in_group, place_spec_without_page)]。"""
    argv = [sys.executable, SEAL_ENGINE, plain, "--out", sealed]
    for page, spec in places:
        argv += ["--place", f"page={page},{spec}", "--image", _seal_image()]
    _run(argv, "押印 overlay")


def _save(wb, dst, census: bool = True):
    """openpyxl で save し、 ``_load`` した元 workbook の図形を同名 sheet に移し直す (= 紙から標題・区分の枠・
    様式番号が消えない)。 移せなければ BuildError (黙って落とさない)。
    census=True (刷る temp) なら、 保存で読み込み元より減った「紙に出るもの」 (form control・画像・条件付き書式…) を
    spec の meta.accept_loss に無い限り ⚠️ の行で出す (fidelity.temp_census_lines = 名前を知らない損失も数で見る)。"""
    from . import drawings as DR

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb.save(dst)
    src = getattr(wb, "_formcase_source", None)
    if src:
        drops = getattr(wb, "_formcase_drop_shapes", None) or {}
        try:
            DR.graft_drawings(src, dst, drop=drops)
        except DR.GraftError as e:
            raise BuildError(f"図形 (標題・様式番号等) を temp に移せない: {e}") from e
        if census:
            for line in FD.temp_census_lines(_CURRENT.get("spec"), src, dst, dropped=sum(len(v) for v in drops.values())):
                print("   " + line)
    if census:
        _CURRENT["temp"] = str(dst)
    return dst


# ---------------------------------------------------------------------------
# 字の切れ・はみ出し gate (全様式共通)
# ---------------------------------------------------------------------------
def _load(path, data_only=False):
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, data_only=data_only)
    if not data_only:
        wb._formcase_source = str(path)   # _save が図形をここから移し直す (data_only の読み込みは値の照合用 = PDF にしない)
    return wb


def _require_cached(workbook):
    """数式の計算済み値が要る (字の切れ gate が、 数式で他 sheet に複製された欄も値として見る)。"""
    from . import fingerprint as FP

    w = FP.last_writer(workbook) or ""
    if "openpyxl" in w.lower():
        raise BuildError(f"{Path(workbook).name} の最後の保存が openpyxl ({w}) = 数式の計算済み値が無い → "
                         "`formcase.py normalize CASE DOC` で Excel に保存させてから build")


def _in_ranges(coord, ranges):
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string, range_boundaries

    col, row = coordinate_from_string(coord)
    ci = column_index_from_string(col)
    for rng in ranges:
        c0, r0, c1, r1 = range_boundaries(rng)
        if c0 <= ci <= c1 and r0 <= row <= r1:
            return True
    return False


def _clip_source(workbook, tpl, keep: dict, dst: Path) -> Path:
    """字の切れ検査に渡す workbook。 keep = {sheet: [range, ...]} (= この PDF に刷った範囲、 None = sheet 全体)。

    範囲の外の cell は雛形の値に戻す (check-form-clipping は記入値を PDF 全体で探すので、 刷っていない sheet の値が
    別の page に偶然現れて誤検出する = 実測、 同じ値の欄の数も数え過ぎる)。 数式は計算済みの値にして
    保存する (= 数式で他 sheet に複製された欄も記入値として照合される)。 元 workbook は触らない。"""
    from openpyxl.cell.cell import MergedCell

    wb, wt = _load(workbook, data_only=True), _load(tpl, data_only=True)
    keep = {k.strip(): v for k, v in keep.items()}
    for ws in wb.worksheets:
        kept = ws.title.strip() in keep
        ranges = keep.get(ws.title.strip())          # None = sheet 全体
        src = next((t for t in wt.worksheets if t.title.strip() == ws.title.strip()), None)
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c, MergedCell) or c.value is None:
                    continue
                if kept and (ranges is None or _in_ranges(c.coordinate, ranges)):
                    continue
                c.value = src[c.coordinate].value if src is not None else None
    return _save(wb, dst, census=False)          # 検査用の temp (刷らない) = census は取らない


# 記入値の描画の倍率の下限 (= 描画の字の大きさ / cell の font size)。 提出して受理された紙で一番縮んでいた page が
# 0.61 倍だった実測から。 それ未満 = 行を伸ばし過ぎ・値が長過ぎで page が縮み過ぎ (form-case-pipeline.md #layout-3)。
MIN_SCALE = 0.6


def _clip_findings(tpl, src, pdf) -> dict:
    import json

    r = subprocess.run([sys.executable, str(CLIPPING), "--json", "--min-scale", str(MIN_SCALE), str(tpl), str(src), str(pdf)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise BuildError(f"字の切れ gate の出力が読めない (exit {r.returncode}): {r.stdout[-300:]}")


def _clip_gate(workbook, tpl, keep, pdf, tmp, tag):
    _require_cached(workbook)
    src = _clip_source(workbook, tpl, keep, Path(tmp) / f"{tag}_clip_source.xlsx")
    _run([sys.executable, CLIPPING, "--min-scale", MIN_SCALE, tpl, src, pdf],
         "字の切れ・はみ出し・###・字の小ささ (check-form-clipping)")


def grow(wb, extra, found) -> list:
    """見つかった欄 (loc = sheet!cell、 fan-out は同じ値の全欄) の行を伸ばす量を extra に足す。 足した欄の説明を返す。

    まだ折り返していない欄 = まず折り返す (行は見積りで伸びる) / 折り返している欄 = 見えた字数から 1 行の字数を出し、
    欠けた字の行数 (はみ出し・字の小ささは 1 行) だけ行を足す。"""
    from openpyxl.utils import get_column_letter

    grown = []
    for kind, f in found:
        for loc in f["loc"].split(", "):
            sheet, coord = loc.rsplit("!", 1)
            ws = LY._sheet(wb, sheet)
            if ws is None:
                continue
            c0, r0, c1, r1, _merged = LY._box(ws, coord)
            tl = f"{get_column_letter(c0)}{r0}"
            key = (sheet.strip(), tl)
            ex = extra.setdefault(key, {})
            if not ws[tl].alignment.wrap_text and not ex.get("wrap"):
                ex["wrap"] = True
                grown.append(f"{sheet.strip()}!{tl} 折り返し")
                continue
            pitch = float(ws[tl].font.sz or 11) * LY.line_pitch(ws[tl].font.name)
            height = sum(LY._row_h(ws, r) for r in range(r0, r1 + 1))
            lines = 1
            if kind == "clip" and 0 < f["frag"] < f["len"]:   # 見えた字数から 1 行の字数を出し、 欠けた字の行数だけ
                per_line = max(1.0, f["frag"] / max(1, math.floor(height / pitch)))
                lines = min(4, math.ceil((f["len"] - f["frag"]) / per_line))
            ex["pt"] = float(ex.get("pt", 0)) + lines * pitch
            grown.append(f"{sheet.strip()}!{tl} +{lines * pitch:.1f}pt")
    return grown


# ---------------------------------------------------------------------------
# recipe 定義
# ---------------------------------------------------------------------------
class Recipe:
    form = ""
    outputs = {}        # group → {role: 名前の型 ({stem} = workbook の stem。 変数を足すのは name_vars)}
    seals = {}          # package page (1 始まり) → place spec (page= を除く)
    FIT_ROUNDS = 3      # Excel で刷る回数の上限 (= 刷り直しは FIT_ROUNDS - 1 回まで)

    def package(self, workbook: Path, tmp: Path) -> Path:
        raise NotImplementedError

    def package_for(self, group: str, workbook: Path, tmp: Path) -> Path:
        """group の page を含む package。 既定 = 全 group 共通の 1 本。
        group ごとに別の sheet を刷る様式は上書きする。"""
        if getattr(self, "_pkg", None) is None:
            self._pkg = self.package(workbook, tmp)
        return self._pkg

    def seals_for(self, group: str) -> dict:
        return self.seals

    def post_group(self, m, doc_id, group, plain: Path):
        """group の押印なし PDF に対する後処理と gate (recipe 固有)。"""

    def derive(self, group: str, role: str, plain: Path, workbook: Path, tmp: Path):
        """print / confirm 以外の出力 (raster・送付用 xlsx 等) を作って path を返す。 作らない role は None。"""
        return None

    def name_vars(self, stem: str) -> dict:
        """出力名の型に渡す変数。 既定 = ``{stem}`` だけ。 派生名の要る様式は足す (= 名づけは呼び元のもの)。"""
        return {"stem": stem}

    def default_outputs(self, stem: str) -> dict:
        v = self.name_vars(stem)
        return {g: {role: pat.format(**v) for role, pat in roles.items()}
                for g, roles in self.outputs.items()}

    # --- 刷り直しの loop (全様式共通) ----------------------------------------------------------
    def fit(self, label, render, findings):
        """render(extra, rnd) -> (体裁を当てた openpyxl workbook, PDF) / findings(PDF, rnd) -> [(kind, finding)]。
        切れ・はみ出しが無くなるか、 FIT_ROUNDS 回刷るか、 伸ばす欄が無くなるまで回し、 最後の PDF を返す
        (残った切れは呼び元の gate が止める = 出力を書かない)。"""
        extra = {}
        pdf = None
        for rnd in range(1, self.FIT_ROUNDS + 1):
            wb, pdf = render(extra, rnd)
            found = findings(pdf, rnd)
            if not found:
                return pdf
            if rnd == self.FIT_ROUNDS:
                print(f"   体裁{label}: {self.FIT_ROUNDS} 回刷っても切れ・はみ出しが残る (下の gate が止める)")
                return pdf
            grown = grow(wb, extra, found)
            if not grown:
                print(f"   体裁{label}: 切れ・はみ出し {len(found)} 件は伸ばせる欄に無い (下の gate が止める)")
                return pdf
            print(f"   体裁{label}: 切れ・はみ出し {len(found)} 件 → 行を伸ばして刷り直す ({rnd}/{self.FIT_ROUNDS - 1}): "
                  + ", ".join(grown))
        return pdf

    def found_in(self, workbook, tpl, keep, pdf, tmp, tag) -> list:
        src = _clip_source(workbook, tpl, keep, tmp / f"{tag}.xlsx")
        res = _clip_findings(tpl, src, pdf)
        return [("clip", c) for c in res["clip"]] + [("overflow", o) for o in res["overflow"]]


def excel_chunks_pdf(workbook, sheet: str, chunks, lines, tmp, tag):
    """Excel の操作の経路 (D2): 案件の workbook の copy を chunks (紙 1 枚ずつの range) ごとに、 lines (体裁 + 他 sheet の
    非表示、 excel.ops_lines の行) + 印刷範囲 + 1 枚に収める、 を staged copy に当てて PDF にし、 並べる。
    openpyxl で保存しない = 図形・form control・数式の cache が案件の workbook のまま紙に出る。"""
    import fitz

    jobs = []
    for k, area in enumerate(chunks):
        x = Path(tmp) / f"{tag}_{k}.xlsx"
        shutil.copy2(workbook, x)                        # 同じ名前の workbook は 1 つの staging dir に置けない
        jobs.append((x, Path(tmp) / f"{tag}_{k}.pdf", list(lines) + X.ops_lines(sheet, [("print_area", area), ("one_page",)])))
    X.export_pdfs(jobs)
    out = fitz.open()
    for (_x, p, _o), area in zip(jobs, chunks):
        d = fitz.open(p)
        if d.page_count != 1:
            raise BuildError(f"{sheet} {area} が紙 1 枚にならない ({d.page_count} page)")
        out.insert_pdf(d)
    raw = Path(tmp) / f"{tag}.pdf"
    out.save(raw)
    return raw


def hide_lines(wb, keep) -> list:
    """keep (sheet 名の list) 以外の sheet を非表示にする行 (= 刷らない。 削除しない = 参照の数式を壊さない)。"""
    keep = {str(s).strip() for s in keep}
    hide = [n for n in wb.sheetnames if n.strip() not in keep]
    return X.ops_lines(wb.sheetnames[0], [("hide_sheet", n) for n in hide])


CONTROL_FRAME_PT = 18.0   # form control (checkbox) の枠の最低 pt (実測: 枠 ≤ 16pt = 箱の右辺が切れる、 ≥ 17pt = 4 辺揃う)


def fit_control_lines(workbook, sheets) -> list:
    """form control (checkbox) の枠の**幅**を CONTROL_FRAME_PT 以上にする行 (検収の宿題 (a)、 2026-09-25): Mac Excel は箱を control の枠
    の raster (1 px/pt) で刷り、 枠が 16pt 以下だと箱 (≈13pt) の右辺が切れる (実測: 枠 ≤ 16pt の箱は右辺が欠け、 ≥ 17pt は 4 辺が出る)。
    高さは足さない (Excel は箱を枠の中で縦に中央に描く = 足した分の半分だけ箱が下がる、 実測 = 検収 F7)。
    staged copy にだけ当てる (案件の workbook は変えない)。 印刷する sheet に checkbox が無ければ空。"""
    import office_census as OC

    want = {str(s).strip() for s in sheets}
    have = []
    for c in OC.form_controls(workbook):
        if c["type"] == "CheckBox" and c["sheet"].strip() in want and c["sheet"] not in have:
            have.append(c["sheet"])
    lines = []
    for name in have:
        lines += X.ops_lines(name, [("control_frame_min", CONTROL_FRAME_PT)])
    return lines


def fit_shape_lines(workbook, sheets) -> list:
    """雛形の 1 行の label (様式番号等) が枠に入り切らず末尾が消える図形の余白を縮める行 (drawings.single_line_insets =
    移植の経路の ``_fit_single_line`` と同じ判定。 sheets = 刷る sheet の名前)。 図形の無い workbook は空。"""
    from . import drawings as DR

    want = {str(s).strip() for s in sheets}
    lines = []
    for name, fixes in DR.single_line_insets(workbook).items():
        if name.strip() in want:
            lines += X.ops_lines(name, [("shape_insets", n, pt, pt) for n, pt in fixes])
    return lines


def _chunks_pdf(wb, sheet, chunks, tmp, tag):
    """sheet だけが残った wb を、 chunks (紙 1 枚ずつの range) ごとに 1 枚に収めて Excel で PDF にし、 並べる。"""
    import fitz

    ws = LY._sheet(wb, sheet)
    jobs = []
    for k, area in enumerate(chunks):
        LY.one_page(ws, area)
        x, p = tmp / f"{tag}_{k}.xlsx", tmp / f"{tag}_{k}.pdf"
        _save(wb, x)
        jobs.append((x, p))
    X.export_pdfs(jobs)
    out = fitz.open()
    for (_x, p), area in zip(jobs, chunks):
        d = fitz.open(p)
        if d.page_count != 1:
            raise BuildError(f"{sheet} {area} が紙 1 枚にならない ({d.page_count} page)")
        out.insert_pdf(d)
    raw = tmp / f"{tag}.pdf"
    out.save(raw)
    return raw


class RecipeDocx(Recipe):
    """Word (docx) 様式 (spec の meta.kind = docx、 form-case-pipeline.md #docx)。 group は spec の groups (1 つ = 全 page)。

    package = 案件の docx を Word で PDF → page 数を spec の meta.pages と照合 (autofit の表で頁がはみ出す様式 =
    はみ出したら止める) → 選択肢の ○ と短い値を overlay.yaml から重ねる。 押印の位置は spec の docx.seal から PDF で出す。
    出力 = print (押印、 紙専用の印) / raster (print の 600dpi RGB = 刷るのはこれ、 印を引き継ぐ) / confirm (押印なし)。
    出力名の型は spec の ``outputs:`` (無ければ下の既定。 = 名づけは呼び元のもの)。"""
    OUT = {"print": "{stem}_print.pdf", "raster": "{stem}_print_raster.pdf", "confirm": "{stem}_confirm.pdf"}

    def __init__(self, form_id):
        from . import docx_form as DF

        self.DF = DF
        self.form = str(form_id)
        self.spec = S.get(self.form)
        out = {str(k): str(v) for k, v in (self.spec.get("outputs") or {}).items()} or dict(self.OUT)
        self.outputs = {g: dict(out) for g in (self.spec.get("groups") or {})}
        self._pkg = None
        self._seals = {}
        self._sealed = {}

    def package_for(self, group, workbook, tmp):
        import fitz

        if self._pkg is not None:
            return self._pkg
        DF = self.DF
        try:
            raw = DF.to_pdf(Path(workbook), tmp / "word.pdf")
            n = fitz.open(raw).page_count
            if n != DF.pages(self.spec):
                raise BuildError(f"Word の PDF が {n} page (spec の meta.pages = {DF.pages(self.spec)}) = 値の長さで表の頁が"
                                 "はみ出した (層1 office-automation.md#docx-autofit-grid-overflow)。 欄の値を短くするか spec の "
                                 "docx.render で字を小さくする")
            miss = check_page_anchors(raw, self.spec)
            if miss:
                raise BuildError("Word の PDF の頁が spec の page_roles と合わない (頁の目印が無い): "
                                 + ", ".join(f"{k} 頁「{a}」" for k, a in miss)
                                 + " = 雛形が改訂されて頁の中身がずれた。 各頁を見て page_roles と groups の pages を直す "
                                 "(form-case-pipeline.md #page-roles)")
            pkg = tmp / "package.pdf"
            DF.overlay(raw, pkg, self.spec, DF.load_overlay(workbook))
            self._seals = DF.seal_places(pkg, self.spec)
        except DF.DocxFormError as e:
            raise BuildError(str(e))
        self._pkg = pkg
        return pkg

    def seals_for(self, group):
        return self._seals

    def derive(self, group, role, plain, workbook, tmp):
        if role != "raster":
            return None
        import fitz

        sys.path.insert(0, str(CC / "lib"))
        from seal_artifact import copy_marker

        sealed = tmp / f"{group}_sealed.pdf"
        src = sealed if sealed.exists() else plain
        d = fitz.open(src)
        out = fitz.open()
        for pg in d:
            pix = pg.get_pixmap(dpi=600, colorspace=fitz.csRGB)
            np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
            np_.insert_image(np_.rect, pixmap=pix)
        copy_marker(d, out)
        PP.copy_record(fitz.open(plain), out)   # 刷る頁の宣言 (build が group の頁に書いたもの) を raster へ
        dst = tmp / f"{group}_raster.pdf"
        out.save(dst, deflate=True)
        # 期待の頁数 = group の頁 (= 窓口に出す頁) の数。 meta.pages (Word が出す頁) ではない = 説明書きの頁まで「期待どおり」
        # と通した実測から (form-case-pipeline.md #page-roles)。 頁の役割 (宣言) も preflight が見る
        n = len(S.group_def(self.spec, group).get("pages") or [])
        _run([sys.executable, CC / "pdf-print-preflight.py", dst, "--expect-pages", n], "印刷の preflight (raster 版)")
        return dst


# 様式ごとの recipe の登録簿。 中身は呼び元が入れる (= engine は空で出荷する)
RECIPES: dict = {}
_FROM_FILE: set = set()          # file の load で入った form id (= 設定が変わったら捨てる。 直接の register は残す)
_LOADED_FROM = None


def register(form_id, cls):
    """様式 ``form_id`` の recipe を登録する (呼び元の設定 ``recipes`` が指す file から呼ぶ)。"""
    RECIPES[str(form_id)] = cls
    return cls


def load_instance_recipes() -> None:
    """設定の ``recipes`` が指す python file を読む (= その file が register を呼ぶ)。 設定が変わったら読み直す。"""
    global _LOADED_FROM

    key = str(CF.config_dir())
    if _LOADED_FROM == key:
        return
    import importlib.util

    for fid in _FROM_FILE:
        RECIPES.pop(fid, None)
    _FROM_FILE.clear()
    before = set(RECIPES)
    for f in CF.recipe_files():
        if not f.exists():
            raise BuildError(f"設定の recipes が指す file が無い: {f}")
        sp = importlib.util.spec_from_file_location(f"formcase_recipes_{abs(hash(str(f)))}", f)
        mod = importlib.util.module_from_spec(sp)
        sys.modules[sp.name] = mod
        sp.loader.exec_module(mod)
    _FROM_FILE.update(set(RECIPES) - before)
    _LOADED_FROM = key


def recipe_for(form_id):
    load_instance_recipes()
    cls = RECIPES.get(str(form_id))
    if cls is None:
        from . import docx_form as DF

        if DF.is_docx(S.get(form_id)):
            return RecipeDocx(form_id)
        raise BuildError(f"form {form_id!r} の生成 recipe が無い (設定の recipes が指す file に register する。 "
                         "form-case-pipeline.md #scope)")
    return cls()


def build(m, doc_id, groups, out_dir=None) -> dict:
    """group の出力を作る。 返り値 = {group: {role: path}}。 out_dir 指定時は案件 dir に書かない (照合用)。
    Excel の失敗 (excel.ExcelError、 osascript の標準エラーを逐語で含む) は BuildError にして出力を書かない。"""
    try:
        return _build(m, doc_id, groups, out_dir)
    except X.ExcelError as e:
        raise BuildError(str(e))


def _build(m, doc_id, groups, out_dir=None) -> dict:
    doc = m.doc(doc_id)
    rc = recipe_for(doc.get("form"))
    spec = S.get(doc.get("form"))
    wb = m.workbook(doc_id)
    if wb is None or not wb.exists():
        raise BuildError(f"{doc_id}: workbook が無い")
    unsupported = [g for g in groups if g not in rc.outputs]
    if unsupported:
        raise BuildError(f"recipe {rc.form} は group {unsupported} を作れない (form-case-pipeline.md #scope)")
    try:
        S.controls(spec)                                 # controls: の state / anchor の不正は build の前にきれいに止める (検収 H8)
    except ValueError as e:
        raise BuildError(f"spec の controls: が不正 = {e}")
    role_probs = S.page_role_problems(spec)              # 刷る頁の宣言の矛盾 (form-case-pipeline.md #page-roles)
    if role_probs:
        raise BuildError("spec の頁の役割が矛盾している: " + " / ".join(role_probs))
    GT.run_scoped(m, doc_id, groups)                     # FAIL なら BuildError
    from . import docx_form as DF

    bind_msgs, bind_differs = FD.bind_lines(spec)        # 雛形の identity (bind の記録と同じか)
    for line in bind_msgs:
        print("   " + line)
    if bind_differs:                                     # D5 (2026-09-25): 違えば止める = 雛形が改訂・差し替わった (または無い)
        raise BuildError(f"雛形が bind の記録と違う (または無い) → 出力を書かない。 `formcase.py bind {spec['meta']['id']}` で"
                         " sha256 と素刷りを記録し直し、 差 (見出し・図形・欄) を見てから build (form-case-pipeline.md#fidelity)")
    _CURRENT.update({"spec": spec, "temp": None})
    written = {}
    with tempfile.TemporaryDirectory(prefix="formcase-build-") as td:
        tmp = Path(td)
        for g in groups:
            pkg = rc.package_for(g, wb, tmp)
            gdef = S.group_def(spec, g)
            pages = [int(p) for p in gdef.get("pages") or []]   # package 内の page (recipe の package 構成と一致させる)
            plain = tmp / f"{g}_plain.pdf"
            _extract(pkg, pages, plain)
            blank = None if DF.is_docx(spec) else FD.group_blank(spec, g, tmp)   # 素刷り (cache、 Excel が無ければ None)
            for line in declare_pages(plain, spec, g, pages, blank=blank):   # 出力の全頁 = 窓口に出す頁、 と宣言 (刷る直前の gate が読む)
                print("   " + line)
            rc.post_group(m, doc_id, g, plain)
            if S.controls(spec) and not DF.is_docx(spec):
                # D9 (検収 F1): control 自身の ✓ は raster の灰色の点で紙では読めない → 印の入った箱に太い ✓ を vector で重ねる
                mk = FD.mark_boxes(spec, plain)
                if mk.get("error"):
                    print(f"   ⚪ 箱の ✓ の重ね描きが走らなかった ({mk['error'][:80]}) = 読めない印は次の照合が止める")
                else:
                    print(f"   ☑ 印の入った箱に ✓ を重ねた {mk.get('marked', 0)} 個 (control 自身の ✓ は紙で読めない = 実測)")
            # 雛形との照合: 図形の字が無ければ止める / 見出し・素刷りとの画像の差・増えた字は行に (form-case-pipeline.md#fidelity)
            lines, stop, rep = static_text_lines(spec, g, plain, filled=_CURRENT.get("temp") or wb, blank=blank)
            for line in lines:
                print("   " + line)
            log_fidelity(m, doc_id, g, rep, stop, out_dir)   # D3 の carrier (見出しの ⚠️ / ✅ の記録)
            if stop:
                raise BuildError(stop + " → 出力を書かずに中断")
            outs =(m.group(doc_id, g).get("current") or {}).get("outputs") or rc.default_outputs(wb.stem)[g]
            places = [(pages.index(pp) + 1, spec_) for pp, spec_ in rc.seals_for(g).items() if pp in pages]
            base = Path(out_dir) if out_dir else m.case_dir
            written[g] = {}
            overlay = bool(places) and CF.seal_mode() != "physical"
            if overlay:
                sealed = tmp / f"{g}_sealed.pdf"
                _seal(plain, sealed, places)
            for page, spec_ in [] if overlay else places:
                print(f"   ✋ 実押印 ({g}): {page} 頁目の {stamp_hint(spec_)} — 押印欄は空のまま刷る。 刷ったら紙に押す"
                      " (seal_mode: physical)")
            for role, rel in outs.items():
                if role == "print":
                    src = sealed if overlay else plain
                elif role == "confirm":
                    src = plain
                else:
                    src = rc.derive(g, role, plain, wb, tmp)
                    if src is None and out_dir:
                        # 照合用の build (案件 dir に書かない) = 凍結 issue の記録にある recipe 外の役割名は飛ばす
                        # (K8: 記録は変えない、 print / confirm だけ作れれば照合できる)
                        print(f"   ⏭️  {g}/{role}: recipe {rc.form} が知らない役割 = 照合用の build では飛ばす")
                        continue
                    if src is None:
                        raise BuildError(f"recipe {rc.form} は group {g} の出力 role {role!r} を作れない "
                                         "(manifest の outputs の役割名を recipe の既定に揃える)")
                if str(src).lower().endswith(".pdf"):
                    src = _ensure_declared(src, plain)      # 押印 engine 等が宣言を落としても出力には必ず載せる
                written[g][role] = _put(src, base / rel, m, out_dir)
    return written


def _put(src, dst: Path, m, out_dir):
    if out_dir is None and str(dst.resolve()) in m.frozen_outputs():
        raise BuildError(f"{dst.name} は凍結出力 = 書かない (formcase.py reopen で新しい issue を作る)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst
