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
