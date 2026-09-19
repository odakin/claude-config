"""お手本 spec (``<spec_dir>/*.yaml``) の読み込み。 spec の書式の正本は各 yaml と記入内容 gate。

spec の dir・雛形の base は instance 設定 (``config.py``) が持つ = engine は「どの様式か」 を知らない。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from . import config as CF


@lru_cache(maxsize=None)
def _load_all(spec_dir: str) -> dict:
    out = {}
    for p in sorted(Path(spec_dir).glob("*.yaml")):
        raw = p.read_bytes()
        if raw.startswith(b"\x00GITCRYPT"):
            continue
        d = yaml.safe_load(raw.decode("utf-8")) or {}
        sid = (d.get("meta") or {}).get("id")
        if sid:
            d["_path"] = p
            out[str(sid)] = d
    return out


def invalidate() -> None:
    """設定が差し替わったら読み直す (config.configure / reset が呼ぶ)。"""
    _load_all.cache_clear()


def all_specs(spec_dir: Path | None = None) -> dict:
    return _load_all(str(spec_dir or CF.spec_dir()))


def get(form_id, spec_dir: Path | None = None):
    return all_specs(spec_dir).get(str(form_id)) if form_id is not None else None


def spec_ids() -> list:
    return sorted(all_specs())


def group_def(spec: dict, group_id: str) -> dict:
    g = (spec.get("groups") or {}).get(group_id)
    if g is None:
        raise KeyError(f"spec {spec['meta'].get('id')!r} に group {group_id!r} が無い")
    return g


def group_sheets(spec: dict, group_id: str, with_depends: bool = True) -> list:
    g = group_def(spec, group_id)
    out = list(g.get("sheets") or [])
    if with_depends:
        out += [s for s in (g.get("depends") or []) if s not in out]
    return out


def template_path(spec: dict) -> Path:
    return (CF.template_root() / spec["meta"]["template"]).resolve()


def history_homes() -> set:
    """規則の理由・経緯の home = spec の ``meta.history_home`` (spec file からの相対 path) の実在するもの。"""
    out = set()
    for spec in all_specs().values():
        hh = (spec.get("meta") or {}).get("history_home") or []
        for rel in ([hh] if isinstance(hh, str) else hh):
            cand = (spec["_path"].parent / rel).resolve()
            if cand.exists():
                out.add(cand)
    return out


# ---------------------------------------------------------------------------
# 頁の役割 (page_roles) — どの頁が窓口に出す頁か。 判定の実体 = scripts/lib/print_pages.py
# (役割の語・矛盾の検査・頁の目印の照合。 本 module は spec の形を渡す adapter だけ)
# ---------------------------------------------------------------------------
def _pp():
    import sys

    lib = str(Path(__file__).resolve().parent.parent / "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    import print_pages

    return print_pages


def page_roles(spec: dict) -> dict:
    """{package の頁番号 (1 始まり): {"role", "anchor", "label", "why"}}。 spec に無ければ {}。"""
    out = {}
    for k, v in (spec.get("page_roles") or {}).items():
        out[int(k)] = v if isinstance(v, dict) else {"role": v}
    return out


def page_role_problems(spec: dict) -> list:
    """spec の頁の役割の矛盾 (空 = 問題なし)。 検査の中身 = print_pages.role_map_problems:
    役割の語 / submit の anchor / group (= まとまり) は submit だけ / submit はどれかの group に。
    docx 様式 (package = Word の文書まるごと) は meta.pages の全頁に役割が要る (= 様式に付いてくる説明書き・記載例を
    黙って刷らない)。 Excel 様式は group の sheets と印刷範囲 (= 刷る sheet の whitelist) だけを刷るので無くてよい。"""
    meta = spec.get("meta") or {}
    n = int(meta.get("pages") or 1) if str(meta.get("kind") or "") == "docx" else None
    groups = {gid: (g or {}).get("pages") or [] for gid, g in (spec.get("groups") or {}).items()}
    return _pp().role_map_problems(page_roles(spec), groups, n_pages=n, name=str(meta.get("id")))
