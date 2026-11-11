#!/usr/bin/env python3
"""Exercise the Codex completion-gate acknowledgement on isolated Git data."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("session_touch", Path(__file__).with_name("session_touch.py"))
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@unittest.skipIf(gate.fcntl is None, "receipt storage requires file locking")
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "repo"
        self.remote = self.root / "origin.git"
        self.repo.mkdir()
        environment = patch.dict(os.environ, {
            "CODEX_SESSION_TOUCH_STATE_DIR": str(self.root / "state"),
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "-q", "-b", "main")
        for path in ("foreign a", "foreign-b", "ours"):
            (self.repo / path).write_text("base\n")
        self.git("add", "--", "foreign a", "foreign-b", "ours")
        self.git("commit", "-qm", "base")
        self.event = {"cwd": str(self.repo), "session_id": "fixture"}
        self.state = gate.state_path(self.event)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args],
                              capture_output=True, text=True, check=True).stdout

    def call(self, fn, **event):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = fn({**self.event, **event})
        return code, json.loads(out.getvalue()) if out.getvalue() else {}

    def track(self, command="git status", tool="Bash"):
        self.call(gate.track, tool_name=tool, hook_event_name="PreToolUse",
                  tool_input={"command": command})

    def fixture(self):
        (self.repo / "foreign a").write_text("other a\n")
        (self.repo / "foreign-b").write_text("other b\n")
        self.track()
        self.git("restore", "--", "foreign-b")

    def review(self, expected=("foreign a",)):
        code, body = self.call(gate.review)
        self.assertEqual(code, 0, body)
        self.assertEqual(tuple(body["paths"]), expected)
        return body["owner_prompt"]

    def acknowledge(self, prompt=None, **kwargs):
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt or self.review(), **kwargs}
        _, body = self.call(gate.acknowledge, **event)
        return body.get("hookSpecificOutput", {}).get("additionalContext", "")

    def approved(self):
        self.fixture()
        self.assertIn("Recorded", self.acknowledge())

    def nudge(self):
        return self.call(gate.nudge, hook_event_name="Stop")[1]

    def blocked(self, message):
        result = self.nudge()
        self.assertEqual(result.get("decision"), "block", result)
        self.assertIn(message, result["reason"])
        return result["reason"]

    def bare_remote(self):
        self.git("init", "--bare", "-q", "-b", "main", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-qu", "origin", "main")

    def test_exact_ack_repeats_read_only_with_no_remote(self):
        self.fixture()
        self.blocked("1 unacknowledged current path(s)")
        prompt = self.review()
        self.assertEqual(self.acknowledge(prompt, hook_event_name="PreToolUse"), "")
        self.blocked("dirty")
        self.assertIn("Recorded", self.acknowledge(prompt))
        self.assertEqual(self.nudge(), {})
        self.track("git status --short && git diff --stat")
        self.assertEqual(self.nudge(), {})
        self.assertTrue(self.state.exists())

    def test_same_porcelain_worktree_and_replay(self):
        self.approved()
        prior = self.git("status", "--porcelain=v1")
        (self.repo / "foreign a").write_text("changed\n")
        self.assertEqual(prior, self.git("status", "--porcelain=v1"))
        self.blocked("dirty")
        (self.repo / "foreign a").write_text("other a\n")
        self.blocked("dirty")

    def test_same_porcelain_index(self):
        self.fixture()
        self.git("add", "--", "foreign a")
        self.assertIn("Recorded", self.acknowledge())
        prior = self.git("status", "--porcelain=v1")
        (self.repo / "foreign a").write_text("changed staged bytes\n")
        self.git("add", "--", "foreign a")
        self.assertEqual(prior, self.git("status", "--porcelain=v1"))
        self.blocked("dirty")

    def test_worktree_change_before_acceptance(self):
        self.fixture()
        prompt = self.review()
        (self.repo / "foreign a").write_text("changed before approval\n")
        self.assertIn("No exception", self.acknowledge(prompt))
        self.blocked("dirty")

    def test_own_changes_mixed_with_foreign(self):
        self.approved()
        self.track("*** Begin Patch\n*** Update File: ours\n*** End Patch", "apply_patch")
        (self.repo / "ours").write_text("owned\n")
        self.blocked("1 unacknowledged current path(s)")
        self.assertIn("Recorded", self.acknowledge())
        self.blocked("1 unacknowledged current path(s)")

    def test_same_porcelain_own_edit_of_preexisting_path(self):
        (self.repo / "foreign a").write_text("other a\n")
        self.track("*** Begin Patch\n*** Update File: foreign a\n*** End Patch", "apply_patch")
        prior = self.git("status", "--porcelain=v1")
        (self.repo / "foreign a").write_text("now ours\n")
        self.assertEqual(prior, self.git("status", "--porcelain=v1"))
        self.blocked("dirty")
        self.assertEqual(self.call(gate.review)[0], 2)

    def test_new_path_and_untracked_shell(self):
        self.approved()
        (self.repo / "unseen").write_text("new\n")
        self.blocked("1 unacknowledged current path(s)")
        (self.repo / "unseen").unlink()
        self.track("git status & touch other-file")
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign a").write_text("residual change after ambiguous shell\n")
        self.blocked("dirty")

    def test_ambiguous_write_outside_repository(self):
        self.approved()
        self.call(gate.track, cwd=str(self.root), tool_name="Bash",
                  hook_event_name="PreToolUse", tool_input={"command": "python3 writes.py"})
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign a").write_text("residual change from elsewhere\n")
        self.blocked("dirty")

    def test_deleted_path_and_mode_change(self):
        self.approved()
        (self.repo / "foreign a").chmod(0o755)
        self.blocked("dirty")
        (self.repo / "foreign a").unlink()
        self.assertIn("Recorded", self.acknowledge())
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign a").write_text("present again\n")
        self.blocked("dirty")

    def test_branch_and_wrong_session(self):
        self.fixture()
        prompt = self.review()
        self.assertIn("No exception", self.acknowledge(prompt, session_id="different"))
        self.assertIn("Recorded", self.acknowledge(prompt))
        self.git("switch", "-qc", "other")
        self.blocked("dirty")

    def test_malformed_missing_and_raced_state(self):
        self.approved()
        state = gate.load_state(self.state)
        state["repos"][str(self.repo)]["receipt"] = {"digest": "malformed"}
        gate.save_state(self.state, state)
        self.blocked("dirty")
        self.assertIn("Recorded", self.acknowledge())
        state = gate.load_state(self.state)
        state["repos"][str(self.repo)].pop("receipt")
        gate.save_state(self.state, state)
        self.blocked("dirty")
        self.assertIn("Recorded", self.acknowledge())
        original = gate.status_output
        outputs = 0
        def racing(root):
            nonlocal outputs
            outputs += 1
            if outputs == 2:
                (self.repo / "foreign a").write_text("changed while snapshot was taken\n")
            return original(root)
        with patch.object(gate, "status_output", side_effect=racing):
            self.blocked("dirty")
        self.state.write_text("{bad JSON")
        self.blocked("state could not be read")

    def test_remote_ahead_split_behind_and_read_failure(self):
        self.bare_remote()
        self.approved()
        self.assertEqual(self.nudge(), {})
        self.track("git commit -m own -- ours")
        (self.repo / "ours").write_text("own published candidate\n")
        self.git("commit", "-qm", "own", "--", "ours")
        reason = self.blocked("ahead=1, behind=0")
        self.assertIn("commit and push were split", reason)
        self.git("push", "-q")
        self.assertIn("Recorded", self.acknowledge())
        self.assertEqual(self.nudge(), {})
        clone = self.root / "other"
        self.git("clone", "-q", str(self.remote), str(clone))
        (clone / "ours").write_text("remote progress\n")
        self.git("commit", "-qam", "other", cwd=clone)
        self.git("push", "-q", cwd=clone)
        self.git("fetch", "-q")
        reason = self.blocked("behind=1")
        self.assertNotIn("dirty (", reason)
        self.git("remote", "set-url", "origin", str(self.root / "gone"))
        self.blocked("live remote head could not be verified")

    def test_remote_list_failure_is_not_no_remote(self):
        self.approved()
        original = gate.run_git
        def unavailable(root, *args, **kwargs):
            return None if args == ("remote",) else original(root, *args, **kwargs)
        with patch.object(gate, "run_git", side_effect=unavailable):
            self.blocked("configured remotes could not be read")

    def test_worktree_replacement_invalidates_identity(self):
        self.approved()
        original_dir = self.repo / ".git"
        old_dir = self.root / "old-git-dir"
        original_dir.rename(old_dir)
        shutil.copytree(old_dir, original_dir)
        self.blocked("dirty")

    def test_local_change_during_remote_check(self):
        self.bare_remote()
        self.approved()
        original = gate.live_remote_head
        def racing(*args):
            answer = original(*args)
            (self.repo / "foreign a").write_text("changed during remote lookup\n")
            return answer
        with patch.object(gate, "live_remote_head", side_effect=racing):
            self.blocked("state changed during verification")
        (self.repo / "foreign a").write_text("other a\n")
        self.blocked("dirty")

    def test_only_changed_path_loses_acknowledgement(self):
        self.fixture()
        (self.repo / "foreign-b").write_text("different other work\n")
        prompt = self.review(expected=("foreign a", "foreign-b"))
        self.assertIn("Recorded", self.acknowledge(prompt))
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign-b").write_text("later content\n")
        self.blocked("1 unacknowledged current path(s)")

    def test_legacy_equal_porcelain_with_unreadable_snapshot_stays_loud(self):
        self.fixture()
        prior = {"head": self.git("rev-parse", "HEAD").strip(),
                 "status_hash": hashlib.sha256(self.git("status", "--porcelain=v1").encode()).hexdigest(),
                 "dirty_count": 1}
        gate.save_state(self.state, {"version": 1, "repos": {str(self.repo): {"baseline": prior}}})
        with patch.object(gate, "file_snapshot", side_effect=OSError("unavailable")):
            self.blocked("exact dirty state could not be read")
            self.assertEqual(self.call(gate.review)[0], 2)

    def test_legacy_baseline_requires_explicit_receipt(self):
        self.fixture()
        entry = gate.load_state(self.state)["repos"][str(self.repo)]
        prior = {"head": self.git("rev-parse", "HEAD").strip(),
                 "status_hash": hashlib.sha256(b"").hexdigest(), "dirty_count": 0}
        entry.clear()
        entry["baseline"] = prior
        gate.save_state(self.state, {"version": 1, "repos": {str(self.repo): entry}})
        self.blocked("dirty")
        code, body = self.call(gate.review)
        self.assertEqual(code, 0)
        self.assertTrue(body["tracking_incomplete"])
        self.assertIn("Recorded", self.acknowledge(body["owner_prompt"]))
        self.assertEqual(self.nudge(), {})
        self.assertEqual(gate.load_state(self.state)["repos"][str(self.repo)]["baseline"], prior)
        (self.repo / "foreign a").write_text("new current data\n")
        self.blocked("dirty")


if __name__ == "__main__":
    unittest.main()
