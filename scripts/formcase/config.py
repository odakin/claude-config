"""instance 設定 (= engine が持たない、 呼び元の repo に属する値) の唯一の入口。

engine は「様式の案件を雛形 + spec + 提出状態の manifest で扱う」 仕組みだけを持ち、 **どの repo の / どの様式の /
誰の案件か**は一切持たない。 それを与えるのが呼び元の repo に置く設定 file (既定名 ``formcase.config.json``) で、
engine はこの module 経由でだけそれを読む (= 各 module に path を焼かない)。

設定の見つけ方 (上から):
  1. ``configure(path_or_dict)`` を呼ぶ (= 呼び元の shim package が自分の config を渡す。 推奨)
  2. 環境変数 ``FORMCASE_CONFIG`` (file か dir)
  3. cwd から上へ ``formcase.config.json`` を探す
  4. 無ければ既定値だけ (= spec も案件も無い状態。 selftest と「engine を読むだけ」 の用途)

key (すべて任意。 相対 path は config file のある dir から、 ``glob``/``rel`` は ``workspace_root`` から解決):

  workspace_root   案件 path を人に見せるときの基準 dir (既定 = ``~``)
  workspace_label  その基準を文で書く形 (既定 = ``~/``)。 ``status`` の案内等に出る
  spec_dir         お手本 spec (``*.yaml``) の dir (既定 = config dir の ``reference``)
  template_root    spec の ``meta.template`` を解決する base (既定 = config dir)
  case_roots       案件 (``submission.yaml`` のある dir) を探す root の list
  case_root_skip   root 直下でこの名前の dir は探さない (既定 = ``["reference"]``)
  case_label_with_parent  案件 dir の下の書類 dir 名 (この名前の dir は見出しに親も出す)
  repos            ``lint --staged`` / ``guard`` が働く repo 名 (空 = どの repo でも)
  usage_doc        使い方の正本を人に案内する文字列 (engine の message に出る)
  cli              CLI の呼び方を人に案内する文字列 (同上)
  stub_sys_path    生成する記入 stub が ``sys.path`` に入れる dir の文字列
  precedent_doc    「前例を base にしない」 一般則の doc (workspace_root からの相対 path)
  gates            gate の定義 [{id, script, label, args, scope_flags}]。 script は config dir から
  default_gates    spec が ``meta.gates`` を持たないときに回す gate id
  gates_by_form    {form id: [gate id]} (spec を触らずに様式ごとに変える口)
  seal_image_cmd   押印の画像 path を 1 行で印字する command (list)。 無いと押印のある recipe は止まる
  recipes          instance の recipe を register する python file の list (config dir から)
  instance_selftest  instance 固有の selftest を持つ python file (``run(expect, tmp)`` を持つ)
  lint             {ack, targets, case_readme, forms_by_path, context_stopwords, value_shape_words}
  views            {roots, files} (generated view を探す dir / 明示 file。 workspace_root から)
  scaffold         {spec_hint, process_hint, derived_workbook_suffix}
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

CONFIG_NAME = "formcase.config.json"

DEFAULTS = {
    "workspace_root": "~",
    "workspace_label": "~/",
    "spec_dir": "reference",
    "template_root": ".",
    "case_roots": [],
    "case_root_skip": ["reference"],
    "case_label_with_parent": [],
    "repos": [],
    "usage_doc": "formcase の使い方 (呼び元の repo の USAGE doc)",
    "cli": "formcase.py",
    "stub_sys_path": "",
    "precedent_doc": "claude-config/conventions/office-automation.md#template-base-not-precedent-base",
    "gates": [],
    "default_gates": [],
    "gates_by_form": {},
    "seal_image_cmd": [],
    "recipes": [],
    "instance_selftest": "",
    "lint": {"ack": "", "targets": [], "case_readme": [], "forms_by_path": [], "context_stopwords": [],
             "value_shape_words": []},
    "views": {"roots": [], "files": []},
    "scaffold": {"spec_hint": "", "process_hint": "", "derived_workbook_suffix": {}},
}

_STATE: dict = {"cfg": None, "dir": None}


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
def configure(source, base_dir=None) -> dict:
    """設定を差し替える。 source = config file の path / dict。 dict のときの相対 path の base = base_dir。"""
    if isinstance(source, dict):
        cfg, cdir = dict(source), Path(base_dir or Path.cwd()).resolve()
    else:
        p = Path(source).expanduser().resolve()
        if p.is_dir():
            p = p / CONFIG_NAME
        if not p.exists():
            raise ConfigError(f"formcase の設定 file が無い: {p}")
        cfg, cdir = json.loads(p.read_text(encoding="utf-8")), p.parent
    _STATE["cfg"], _STATE["dir"] = _merge(DEFAULTS, {k: v for k, v in cfg.items() if not k.startswith("//")}), cdir
    _invalidate()
    return _STATE["cfg"]


def reset() -> None:
    """設定を捨てる (= 次の参照で探し直す)。 selftest が instance の設定を跨がないために使う。"""
    _STATE["cfg"], _STATE["dir"] = None, None
    _invalidate()


def _invalidate() -> None:
    from . import specs

    specs.invalidate()


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _discover() -> tuple:
    env = os.environ.get("FORMCASE_CONFIG")
    if env:
        p = Path(env).expanduser()
        return (p / CONFIG_NAME if p.is_dir() else p), True
    d = Path.cwd().resolve()
    for cand in [d, *d.parents]:
        p = cand / CONFIG_NAME
        if p.exists():
            return p, False
    return None, False


def cfg() -> dict:
    if _STATE["cfg"] is None:
        p, required = _discover()
        if p is None or not p.exists():
            if required:
                raise ConfigError(f"FORMCASE_CONFIG が指す設定 file が無い: {p}")
            _STATE["cfg"], _STATE["dir"] = dict(DEFAULTS), Path.cwd().resolve()
        else:
            configure(p)
    return _STATE["cfg"]


def config_dir() -> Path:
    cfg()
    return _STATE["dir"]


# ---------------------------------------------------------------------------
# path の解決
# ---------------------------------------------------------------------------
def _abs(rel, base: Path) -> Path:
    p = Path(str(rel)).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def from_config_dir(rel) -> Path:
    return _abs(rel, config_dir())


def workspace_root() -> Path:
    return Path(str(cfg()["workspace_root"])).expanduser().resolve()


def workspace_label() -> str:
    return str(cfg()["workspace_label"])


def show_path(p) -> str:
    """人に見せる path (workspace_root の下なら label つきの相対 path)。"""
    try:
        return workspace_label() + str(Path(p).resolve().relative_to(workspace_root()))
    except ValueError:
        return str(p)


def spec_dir() -> Path:
    return from_config_dir(cfg()["spec_dir"])


def template_root() -> Path:
    return from_config_dir(cfg()["template_root"])


def case_roots() -> list:
    return [_abs(r, workspace_root()) for r in cfg()["case_roots"]]


def case_root_skip() -> tuple:
    return tuple(cfg()["case_root_skip"])


def case_label_with_parent() -> tuple:
    return tuple(cfg()["case_label_with_parent"])


def repos() -> tuple:
    return tuple(cfg()["repos"])


def usage_doc() -> str:
    return str(cfg()["usage_doc"])


def cli() -> str:
    return str(cfg()["cli"])


def stub_sys_path() -> str:
    return str(cfg()["stub_sys_path"])


def precedent_doc() -> str:
    return str(cfg()["precedent_doc"])


def seal_image_cmd() -> list:
    return [str(x) for x in cfg()["seal_image_cmd"]]


def recipe_files() -> list:
    return [from_config_dir(r) for r in cfg()["recipes"]]


def instance_selftest() -> Path | None:
    v = str(cfg()["instance_selftest"])
    return from_config_dir(v) if v else None


def lint_cfg() -> dict:
    return cfg()["lint"]


def lint_ack() -> Path | None:
    v = str(lint_cfg().get("ack") or "")
    return from_config_dir(v) if v else None


def view_cfg() -> dict:
    return cfg()["views"]


def scaffold_cfg() -> dict:
    return cfg()["scaffold"]


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
def gates_for(form_id, spec: dict | None = None) -> list:
    """その様式で回す gate の定義 (順序つき)。 選び方 = spec の ``meta.gates`` → ``gates_by_form`` → ``default_gates``。"""
    c = cfg()
    defs = {str(g["id"]): g for g in c["gates"]}
    meta_gates = ((spec or {}).get("meta") or {}).get("gates")
    ids = meta_gates or c["gates_by_form"].get(str(form_id)) or c["default_gates"]
    out = []
    for gid in ids:
        g = defs.get(str(gid))
        if g is None:
            raise ConfigError(f"gate {gid!r} が設定の gates に無い (様式 {form_id!r})")
        out.append({"id": str(gid), "script": from_config_dir(g["script"]), "label": g.get("label", str(gid)),
                    "args": [str(a) for a in g.get("args") or []], "scope_flags": bool(g.get("scope_flags", True))})
    return out


# ---------------------------------------------------------------------------
# glob (path の照合)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=512)
def _glob_re(pat: str):
    """``*`` = ``/`` を跨がない任意、 ``**/`` = 任意の深さ、 ``?`` = 1 文字。 fnmatch と違い ``*`` が ``/`` を跨がない。"""
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def rel_to_workspace(p) -> str | None:
    try:
        return str(Path(p).resolve().relative_to(workspace_root()))
    except ValueError:
        return None


def path_matches(p, pat: str) -> bool:
    rel = rel_to_workspace(p)
    return bool(rel is not None and _glob_re(pat).match(rel))


def match_rule(p, rules) -> dict | None:
    """rules = [{glob, name_re?, or_sibling?, ...}] の最初に当たる rule (当たらなければ None)。

    ``name_re`` = その dir 名 (README なら親 dir 名) が合うか。 ``or_sibling`` = 同じ dir にその file が在れば
    ``name_re`` を問わない。 どちらも無ければ glob だけで判定。"""
    p = Path(p)
    for r in rules or []:
        if not path_matches(p, str(r.get("glob") or "")):
            continue
        nre, sib = r.get("name_re"), r.get("or_sibling")
        if nre or sib:
            name_ok = bool(nre and re.search(str(nre), p.parent.name))
            sib_ok = bool(sib and (p.parent / str(sib)).exists())
            if not (name_ok or sib_ok):
                continue
        return dict(r)
    return None
