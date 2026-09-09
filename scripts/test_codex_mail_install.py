#!/usr/bin/env python3
"""Installer tests run only below temporary directories, never real Codex home."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import codex_mail_install as shared


def install(path, enabled=False):
    source = path / "source"; source.mkdir(exist_ok=True)
    (source / "SKILL.md").write_text("Fixture skill")
    helper = path / "helper.py"; helper.write_text("print('fixture help')")
    shared.apply(path, source, helper, enabled)


def _installer_runtime_available():
    """The installer binds a 3.10+ launcher and raises without one, so on such a
    machine there is nothing here to exercise. Ask `desired()` itself rather than
    re-implementing its search, which would drift. Skipping (not failing) keeps a
    permanent red out of the suite, where it would mask a real regression.

    The skip cannot go silent-permanent: CI pins Python 3.12 (.github/workflows/
    checks.yml), so these cases still run there. This gate only spares machines
    that could not run the installer at all."""
    try:
        shared.desired(Path("/nonexistent"), Path("/nonexistent/helper.py"))
    except ValueError:
        return False
    except Exception:
        return True  # A different failure is the suite's business, not this gate's.
    return True


@unittest.skipUnless(_installer_runtime_available(),
                     "no Python 3.10+ interpreter on this machine (the installer binds one)")
class InstallTests(unittest.TestCase):
    def test_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            install(p, True); install(p, True); install(p)
            self.assertEqual((p / "mail-workflow").stat().st_mode & 0o777, 0o700)

    def test_audit_uses_bound_runtime_not_callers_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            install(p, True)
            with patch.object(shared.shutil, "which", side_effect=AssertionError("PATH rediscovery")):
                install(p)

    def test_unmanaged_rule_conflict_preflights(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "rules").mkdir()
            (p / "rules/codex-mail.rules").write_text("user rule")
            with self.assertRaises(ValueError): install(p, True)
            self.assertFalse((p / "skills").exists())
            self.assertEqual((p / "rules/codex-mail.rules").read_text(), "user rule")

    def test_symlink_store_conflict_preflights(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "mail-workflow").symlink_to(p / "other")
            with self.assertRaises(ValueError): install(p, True)
            self.assertFalse((p / "skills").exists())

    def test_unmanaged_launcher_conflict_preflights(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "bin").mkdir()
            (p / "bin/codex-mail").write_text("user launcher")
            with self.assertRaises(ValueError): install(p, True)
            self.assertFalse((p / "skills").exists())
            self.assertFalse((p / "rules").exists())


if __name__ == "__main__": unittest.main()
