#!/usr/bin/env python3
"""Exercise the Codex completion-gate acknowledgement on isolated Git data."""
from __future__ import annotations

import contextlib
import datetime
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
        self.assertEqual(self.nudge(), {})
        self.assertIn("dirty", gate.repo_issues(self.repo, gate.load_state(self.state)["repos"][str(self.repo)], "fixture")[0])
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
        self.assertEqual(self.nudge(), {})
        entry = gate.load_state(self.state)["repos"][str(self.repo)]
        self.assertIn("dirty", gate.repo_issues(self.repo, entry, "fixture")[0])

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
        self.assertEqual(self.nudge(), {})
        entry = gate.load_state(self.state)["repos"][str(self.repo)]
        self.assertIn("1 unacknowledged current path(s)", gate.repo_issues(self.repo, entry, "fixture")[0])

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


    def test_notice_read_only_unknown_tools_and_replayed_stop(self):
        self.fixture()
        baseline = gate.load_state(self.state)["repos"][str(self.repo)]["baseline"]
        self.blocked("dirty")
        for active, run in ((True, "same"), (False, "same"), (False, "new")):
            self.track("git status --short && git diff --stat")
            self.track("python3 - <<'PY'\nprint('read-only report')\nPY")
            self.assertEqual(self.call(gate.nudge, hook_event_name="Stop",
                                      stop_hook_active=active, hook_run_id=run)[1], {})
        state = gate.load_state(self.state)
        entry = state["repos"][str(self.repo)]
        self.assertEqual(entry["baseline"], baseline)
        self.assertNotIn("receipt", entry)
        self.assertTrue(entry["unknown_write"])
        self.assertIn("dirty", gate.repo_issues(self.repo, entry, "fixture")[0])
        self.assertIn("last_dirty_notice", state)

    def test_notice_same_path_updates_stay_quiet_and_path_set_changes_warn(self):
        self.fixture()
        self.blocked("dirty")
        old_porcelain = self.git("status", "--porcelain=v1")
        (self.repo / "foreign a").write_text("new same-status bytes\n")
        self.assertEqual(self.git("status", "--porcelain=v1"), old_porcelain)
        self.assertEqual(self.nudge(), {})
        self.git("add", "--", "foreign a")
        self.assertEqual(self.nudge(), {})
        old_porcelain = self.git("status", "--porcelain=v1")
        (self.repo / "foreign a").write_text("new staged bytes\n")
        self.git("add", "--", "foreign a")
        self.assertEqual(self.git("status", "--porcelain=v1"), old_porcelain)
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign a").chmod(0o755)
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign a").unlink()
        self.assertEqual(self.nudge(), {})
        (self.repo / "foreign a").write_text("new staged bytes\n")
        self.assertEqual(self.nudge(), {})
        (self.repo / "new-path").write_text("new\n")
        self.blocked("2 unacknowledged")
        (self.repo / "new-path").unlink()
        self.blocked("1 unacknowledged")

    def test_notice_own_dirty_publication_refused_same_path_writes_stay_quiet(self):
        self.track("*** Begin Patch\n*** Update File: ours\n*** End Patch", "apply_patch")
        (self.repo / "ours").write_text("authorized task work awaiting publication permission\n")
        self.blocked("dirty")
        self.track("git status --short && git diff --stat")
        self.track("python3 - <<'PY'\nprint('read-only publication status')\nPY")
        self.assertEqual(self.nudge(), {})
        self.assertEqual(self.call(gate.nudge, hook_event_name="Stop", stop_hook_active=True)[1], {})
        baseline = gate.load_state(self.state)["repos"][str(self.repo)]["baseline"]
        for command, tool in (("*** Begin Patch\n*** Update File: ours\n*** End Patch", "apply_patch"),
                              ("git add -- ours", "Bash"), ("git commit -m retry -- ours", "Bash")):
            self.track(command, tool)
            self.assertEqual(self.nudge(), {})
        entry = gate.load_state(self.state)["repos"][str(self.repo)]
        self.assertEqual(entry["baseline"], baseline)
        self.assertNotIn("receipt", entry)
        self.assertNotIn("notice_write_generation", entry)

    def test_notice_unattributed_patch_same_paths_stay_quiet(self):
        self.fixture()
        self.blocked("dirty")
        for phase in ("PreToolUse", "PostToolUse", "PreToolUse"):
            self.call(gate.track, tool_name="apply_patch", hook_event_name=phase,
                      tool_input={"command": "unrecognized patch target"})
            self.assertEqual(self.nudge(), {})
        self.assertNotIn("notice_write_generation", gate.load_state(self.state)["repos"][str(self.repo)])

    def test_notice_three_paths_tex_pdf_updates_and_same_path_writes_stay_quiet(self):
        names = ("paper.tex", "preview.pdf", "notes.txt")
        for name in names:
            (self.repo / name).write_text("base fixture bytes\n")
        self.git("add", "--", *names)
        self.git("commit", "-qm", "three-path fixture")
        self.bare_remote()
        for known in (False, True):
            self.git("restore", "--", *names)
            (self.repo / "new-path").unlink(missing_ok=True)
            self.event["session_id"] = "three-path-" + str(known)
            self.state = gate.state_path(self.event)
            with self.subTest(known_writer=known):
                patch_text = "*** Begin Patch\n" + "".join("*** Update File: " + p + "\n" for p in names) + "*** End Patch"
                self.track(patch_text if known else "git status", "apply_patch" if known else "Bash")
                for name in names:
                    (self.repo / name).write_text("unresolved fixture bytes\n")
                self.blocked("3 unacknowledged")
                porcelain = self.git("status", "--porcelain=v1")
                for name in names[:2]:
                    (self.repo / name).write_text("new content, same unresolved file\n")
                self.assertEqual(self.git("status", "--porcelain=v1"), porcelain)
                self.track("git status --short")
                self.assertEqual(self.nudge(), {})
                self.track(patch_text, "apply_patch")
                self.assertEqual(self.nudge(), {})
                entry = gate.load_state(self.state)["repos"][str(self.repo)]
                self.assertIn("3 unacknowledged", gate.repo_issues(self.repo, entry, self.event["session_id"])[0])
                (self.repo / "new-path").write_text("additional unresolved path\n")
                self.blocked("4 unacknowledged")
                (self.repo / "new-path").unlink()
                self.blocked("3 unacknowledged")
                for commit in range(2):
                    self.git("commit", "--allow-empty", "-qm", f"new fixture head {commit}")
                    self.git("push", "-q")
                    self.assertEqual(self.nudge(), {})
                with patch.object(gate, "live_remote_head", return_value=(None, "unavailable")):
                    for _ in range(2):
                        self.blocked("live remote head could not be verified")

    def test_parallel_dirt_notice_survives_clean_stop(self):
        self.bare_remote()
        paths = ("foreign a", "foreign-b", "ours")
        for owned in (False, True):
            with self.subTest(owned=owned):
                self.event["session_id"] = "clean-stop-" + str(owned)
                self.state = gate.state_path(self.event)
                self.track()
                for name in paths:
                    (self.repo / name).write_text(f"first parallel change {owned}\n")
                self.blocked("3 unacknowledged")
                self.git("commit", "-qam", "first parallel commit")
                self.git("push", "-q")
                self.assertEqual(self.nudge(), {})
                self.assertEqual(gate.load_state(self.state)["repos"], {})
                self.assertEqual(self.nudge(), {})

                if owned:
                    self.track("*** Begin Patch\n*** Update File: ours\n*** End Patch", "apply_patch")
                else:
                    self.track()
                for name in paths:
                    (self.repo / name).write_text("second parallel change\n")
                if owned:
                    self.blocked("3 unacknowledged")
                else:
                    self.assertEqual(self.nudge(), {})
                    self.track("*** Begin Patch\n*** Update File: ours\n*** End Patch", "apply_patch")
                    (self.repo / "ours").write_text("this session now writes the same file\n")
                    self.blocked("3 unacknowledged")
                (self.repo / "new-path").write_text("new unresolved change\n")
                self.blocked("4 unacknowledged")
                (self.repo / "new-path").unlink()
                self.git("restore", "--", *paths)

    def test_notice_git_inspection_forms_do_not_rearm(self):
        self.track("*** Begin Patch\n*** Update File: ours\n*** End Patch", "apply_patch")
        (self.repo / "ours").write_text("owned dirty state\n")
        self.blocked("dirty")
        for command in ("git branch -a", "git remote show origin", "git stash list",
                        "git apply --check candidate.patch", "git add --dry-run -- ours"):
            with self.subTest(command=command):
                self.track(command)
                self.assertEqual(self.nudge(), {})

    def test_notice_receipt_missing_scope_keys_stays_loud(self):
        self.approved()
        original = gate.load_state(self.state)
        for field in ("session", "worktree", "epoch", "day"):
            with self.subTest(field=field):
                state = json.loads(json.dumps(original))
                receipt = state["repos"][str(self.repo)]["receipt"]
                receipt["manifest"].pop(field)
                receipt["digest"] = gate.digest(receipt["manifest"])
                gate.save_state(self.state, state)
                for _ in range(2):
                    self.blocked("dirty")

    def test_notice_receipt_nul_scope_after_three_paths_report_stays_loud(self):
        self.track()
        for name in ("foreign a", "foreign-b", "ours"):
            (self.repo / name).write_text("unresolved fixture bytes\n")
        self.blocked("3 unacknowledged")
        original = gate.load_state(self.state)
        entry = original["repos"][str(self.repo)]
        reviewed = gate.receipt_manifest("fixture", self.repo, entry,
                                        gate.repo_signature(self.repo, with_identity=True))
        for field in ("session", 0, 3, 6):
            with self.subTest(scope_field=field):
                state = json.loads(json.dumps(original))
                manifest = json.loads(json.dumps(reviewed))
                if field == "session":
                    manifest["session"] = "\x00"
                else:
                    manifest["worktree"][field] += "\x00"
                state["repos"][str(self.repo)]["receipt"] = {
                    "manifest": manifest, "digest": gate.digest(manifest), "invalidated": []}
                gate.save_state(self.state, state)
                for _ in range(2):
                    self.blocked("3 unacknowledged")
                current = gate.load_state(self.state)["repos"][str(self.repo)]
                self.assertEqual(current["baseline"], entry["baseline"])
                self.assertEqual(current["receipt"]["manifest"], manifest)
                self.assertEqual(gate.acknowledged_paths("fixture", self.repo, current,
                                                       gate.repo_signature(self.repo, with_identity=True)), set())

    def test_notice_receipt_nul_path_stays_loud_without_repair(self):
        self.fixture()
        state = gate.load_state(self.state)
        entry = state["repos"][str(self.repo)]
        manifest = gate.receipt_manifest("fixture", self.repo, entry,
                                         gate.repo_signature(self.repo, with_identity=True))
        manifest["paths"] = {"bad\x00name": next(iter(manifest["paths"].values()))}
        entry["receipt"] = {"manifest": manifest, "digest": gate.digest(manifest), "invalidated": []}
        gate.save_state(self.state, state)
        for _ in range(3):
            self.blocked("dirty")
        entry = gate.load_state(self.state)["repos"][str(self.repo)]
        self.assertEqual(entry["receipt"]["manifest"], manifest)
        self.assertEqual(gate.acknowledged_paths("fixture", self.repo, entry,
                                               gate.repo_signature(self.repo, with_identity=True)), set())

    def test_notice_baseline_nul_path_stays_loud_without_repair(self):
        self.fixture()
        state = gate.load_state(self.state)
        baseline = state["repos"][str(self.repo)]["baseline"]
        baseline["paths"]["bad\x00name"] = baseline["paths"].pop("foreign a")
        gate.save_state(self.state, state)
        for _ in range(3):
            self.blocked("dirty")
        self.assertEqual(gate.load_state(self.state)["repos"][str(self.repo)]["baseline"], baseline)

    def test_notice_receipt_invalid_day_stays_loud(self):
        self.approved()
        original = gate.load_state(self.state)
        for day in (None, 42, [], {}, "2026-02-30", "not-a-date"):
            with self.subTest(day=day):
                state = json.loads(json.dumps(original))
                receipt = state["repos"][str(self.repo)]["receipt"]
                receipt["manifest"]["day"] = day
                receipt["digest"] = gate.digest(receipt["manifest"])
                gate.save_state(self.state, state)
                for _ in range(2):
                    self.blocked("dirty")

    def test_notice_invalid_baseline_stays_loud_without_repair(self):
        self.fixture()
        original = gate.load_state(self.state)
        baseline = original["repos"][str(self.repo)]["baseline"]
        variants = ({}, {**baseline, "head": None}, {**baseline, "status_hash": 4},
                    {**baseline, "dirty_count": False}, {**baseline, "paths": None})
        for invalid in variants:
            with self.subTest(baseline=invalid):
                state = json.loads(json.dumps(original))
                state["repos"][str(self.repo)]["baseline"] = invalid
                gate.save_state(self.state, state)
                for _ in range(2):
                    self.blocked("dirty")
                self.assertEqual(gate.load_state(self.state)["repos"][str(self.repo)]["baseline"], invalid)

    def test_notice_scope_branch_day_session_and_worktree(self):
        self.fixture()
        self.blocked("dirty")
        self.assertEqual(self.nudge(), {})
        self.git("switch", "-qc", "other")
        self.blocked("dirty")
        self.assertEqual(self.nudge(), {})
        original_datetime = datetime.datetime
        class Tomorrow(original_datetime):
            @classmethod
            def now(cls, tz=None):
                return original_datetime.now(tz) + datetime.timedelta(days=1)
        with patch.object(gate.datetime, "datetime", Tomorrow):
            self.blocked("dirty")
            self.assertEqual(self.nudge(), {})
        self.blocked("dirty")
        self.assertEqual(self.nudge(), {})
        # A copied notice is still bound to its native session, even if state
        # restoration or a legacy migration copied the enclosing tracker.
        state = gate.load_state(self.state)
        other_event = {**self.event, "session_id": "different"}
        gate.save_state(gate.state_path(other_event), state)
        self.assertEqual(self.call(gate.nudge, **other_event, hook_event_name="Stop")[1].get("decision"), "block")
        gitdir = self.repo / ".git"
        saved_gitdir = self.root / "saved-gitdir"
        gitdir.rename(saved_gitdir)
        shutil.copytree(saved_gitdir, gitdir)
        self.blocked("dirty")

    def test_notice_live_remote_rechecked_and_ahead_behind_stay_loud(self):
        self.bare_remote()
        self.fixture()
        original = gate.live_remote_head
        with patch.object(gate, "live_remote_head", wraps=original) as live:
            self.blocked("dirty")
            self.assertEqual(self.nudge(), {})
            self.assertEqual(live.call_count, 2)
        (self.repo / "ours").write_text("local committed progress\n")
        self.git("commit", "-qm", "ours", "--", "ours")
        for _ in range(2):
            self.blocked("ahead=1")
        self.git("push", "-q")
        self.blocked("dirty")
        self.assertEqual(self.nudge(), {})
        clone = self.root / "remote-writer"
        self.git("clone", "-q", str(self.remote), str(clone))
        (clone / "ours").write_text("remote progress\n")
        self.git("commit", "-qam", "remote", cwd=clone)
        self.git("push", "-q", cwd=clone)
        self.git("fetch", "-q")
        for _ in range(2):
            self.blocked("behind=1")
        with patch.object(gate, "live_remote_head", return_value=(None, "unavailable")):
            for _ in range(2):
                self.blocked("live remote head could not be verified")

    def test_notice_unreadable_state_or_snapshot_stays_loud(self):
        self.fixture()
        self.blocked("dirty")
        with patch.object(gate, "file_snapshot", side_effect=OSError("unavailable")):
            for _ in range(2):
                self.blocked("exact dirty state could not be read")
        state = gate.load_state(self.state)
        state["repos"][str(self.repo)]["receipt"] = {"digest": "malformed"}
        gate.save_state(self.state, state)
        for _ in range(2):
            self.blocked("dirty")
        self.state.write_text("{bad JSON")
        for _ in range(2):
            self.blocked("state could not be read")

    def test_notice_concurrent_tracker_and_state_write_failure_stay_loud(self):
        self.fixture()
        self.blocked("dirty")
        original = gate.repo_issues
        def tracker_race(*args):
            answer = original(*args)
            self.track("git add -- foreign a")
            return answer
        with patch.object(gate, "repo_issues", side_effect=tracker_race):
            self.blocked("state changed during verification")
        # Force a new candidate notice, then fail to persist it. A warning must
        # still be emitted, and an unrecorded notice must never be suppressed.
        (self.repo / "foreign-b").write_text("additional unknown change\n")
        with patch.object(gate, "save_state", side_effect=OSError("read-only state")):
            for _ in range(2):
                self.blocked("state could not be verified")

    def test_notice_snapshot_changed_during_verification_stays_loud(self):
        self.bare_remote()
        self.fixture()
        self.blocked("dirty")
        original = gate.live_remote_head
        def racing(*args):
            result = original(*args)
            (self.repo / "foreign a").write_text("changed during query\n")
            return result
        with patch.object(gate, "live_remote_head", side_effect=racing):
            self.blocked("dirty")
        self.blocked("dirty")
        self.assertEqual(self.nudge(), {})

    def test_notice_malformed_other_repo_and_no_lock_stay_loud(self):
        self.fixture()
        self.blocked("dirty")
        state = gate.load_state(self.state)
        state["repos"]["malformed"] = []
        gate.save_state(self.state, state)
        for _ in range(2):
            self.blocked("repository state is malformed")
        state["repos"].pop("malformed")
        gate.save_state(self.state, state)
        with patch.object(gate, "fcntl", None):
            for _ in range(2):
                self.blocked("dirty")


if __name__ == "__main__":
    unittest.main()
