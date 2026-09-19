"""formcase — 様式の案件を「配布雛形 + お手本 spec + 提出状態の manifest」 で扱う汎用 engine。

規約の正本 = ``conventions/form-case-pipeline.md``。 instance (どの repo の / どの様式の案件か) は
``config.py`` が読む設定 file が持ち、 engine 側には持たない。

呼び元の repo での使い方 = 設定 file を置き、 自分の package からこの package を読む::

    # <repo>/forms/formcase/__init__.py  (呼び元の shim package)
    from pathlib import Path
    __path__.append(str(Path.home() / "Claude/claude-config/scripts/formcase"))
    from .config import configure                      # noqa: E402
    configure(Path(__file__).resolve().parent.parent / "formcase.config.json")
    from .guard import legacy_guard                    # noqa: F401,E402

旧 driver (案件 dir に残っている生成 script) の冒頭に置く 1 行は、 呼び元 package の path を入れて::

    import sys, os; sys.path.insert(0, os.path.expanduser("<呼び元の forms dir>"))
    from formcase.guard import legacy_guard; legacy_guard(__file__)
"""
from .config import configure  # noqa: F401
from .guard import legacy_guard  # noqa: F401
from .manifest import FROZEN_STATES, STATES, Manifest, ManifestError, load  # noqa: F401

MODULES = ("check", "config", "docx_form", "excel", "fill", "fingerprint", "gates", "guard", "layout",
           "lifecycle", "lint", "manifest", "markers", "recipes", "rules", "scaffold", "specs", "views")
