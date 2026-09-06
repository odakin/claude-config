#!/usr/bin/env python3
"""Network-free adversarial checks of the reviewed-reply transaction."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import reviewed_mail as mail


ME = "sender" + "@" + "example.invalid"
PEER = "peer" + "@" + "example.invalid"
CC = "colleague" + "@" + "example.invalid"


class Gateway:
    def __init__(self):
        self.calls = 0
        self.identity = ME
        self.timeout = False
        self.corrupt = False
        self.parent = dict(id="parent", thread_id="thread", message_id="<parent-id>",
                           subject="Discussion", body="Original\n\nText\n", date="Some date",
                           to=ME, cc=CC, **{"from": PEER}, labels=["INBOX"], attachments=[])
        self.messages = {"parent": self.parent}

    def profile(self):
        return self.identity

    def get(self, mid):
        return copy.deepcopy(self.messages[mid])

    def send(self, raw, thread):
        self.calls += 1
        msg = mail.decode_raw(raw)
        data = dict(id="sent-id", thread_id=thread, labels=["SENT"], attachments=[],
                    body=msg.get_content(), date="Sent date")
        for k in ["From", "To", "Cc", "Subject", "Message-ID", "In-Reply-To", "References"]:
            data[k.lower().replace("-", "_")] = str(msg.get(k, ""))
        if self.corrupt:
            data["body"] += "changed"
        self.messages["sent-id"] = data
        if self.timeout:
            raise TimeoutError("Ambiguous response after delivery")
        return dict(id="sent-id", threadId=thread)

    def find(self, mid):
        return [k for k, v in self.messages.items() if v["message_id"] == mid]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / "ledger.txt"
        self.target.write_text("")
        self.directory = self.root / "bundle"
        self.gateway = Gateway()
        self.make()

    def tearDown(self):
        self.temp.cleanup()

    def make(self):
        mail.prepare(self.directory, self.gateway, "test", "parent", "Thanks!\n\nS\n",
                     "S", self.target)
        mail.preview(self.directory, self.gateway)
        self.sha = mail.read_json(self.directory / "review.json")["sha256"]

    def test_preview_never_sends_and_retains_cc_quote(self):
        review = mail.read_json(self.directory / "review.json")
        self.assertEqual(review["envelope"]["cc"], [CC])
        self.assertIn("> Original\n> \n> Text", review["body"])
        self.assertEqual(self.gateway.calls, 0)

    def test_exact_body_send_verify_record(self):
        receipt = mail.send(self.directory, self.gateway, self.sha, True)
        self.assertTrue(receipt["verified"])
        self.assertFalse(receipt["recorded"])
        with self.assertRaises(ValueError):
            mail.recorded(self.directory)
        self.target.write_text("sent-id thread")
        self.assertTrue(mail.recorded(self.directory)["recorded"])
        self.assertTrue(mail.verify(self.directory, self.gateway)["recorded"])

    def test_explicit_send_flag_required(self):
        with self.assertRaises(ValueError):
            mail.send(self.directory, self.gateway, self.sha)
        self.assertEqual(self.gateway.calls, 0)

    def test_missing_and_stale_fingerprint(self):
        for value in ["", "0" * 64]:
            with self.assertRaises(ValueError):
                mail.send(self.directory, self.gateway, value, True)
        self.assertEqual(self.gateway.calls, 0)

    def test_each_reviewed_input_mutation_blocks(self):
        for filename in ["reply.txt", "body.txt", "parent.json", "envelope.json", "review.json"]:
            p = self.directory / filename
            original = p.read_text()
            if filename.endswith(".json"):
                obj = json.loads(original)
                if filename == "parent.json": obj["body"] += "changed"
                elif filename == "envelope.json": obj["to"] = [CC]
                else: obj["body"] += "changed"
                p.write_text(json.dumps(obj))
            else:
                p.write_text("changed\n" + original)
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                mail.send(self.directory, self.gateway, self.sha, True)
            p.write_text(original)
        self.assertEqual(self.gateway.calls, 0)

    def test_signature_and_markup_rejected(self):
        p = self.directory / "reply.txt"
        for text in ["Thanks\nWrong\n", "**Thanks**\nS\n", "&gt; Text\nS\n"]:
            p.write_text(text)
            with self.assertRaises(ValueError): mail.preview(self.directory)

    def test_wrong_account_blocks_before_send(self):
        self.gateway.identity = CC
        with self.assertRaises(ValueError):
            mail.send(self.directory, self.gateway, self.sha, True)
        self.assertEqual(self.gateway.calls, 0)

    def test_duplicate_attempt_is_blocked(self):
        mail.send(self.directory, self.gateway, self.sha, True)
        with self.assertRaises(FileExistsError):
            mail.send(self.directory, self.gateway, self.sha, True)
        with self.assertRaises(ValueError): mail.preview(self.directory)
        self.assertEqual(self.gateway.calls, 1)

    def test_timeout_reconciles_without_second_send(self):
        self.gateway.timeout = True
        with self.assertRaises(TimeoutError):
            mail.send(self.directory, self.gateway, self.sha, True)
        with self.assertRaises(FileExistsError):
            mail.send(self.directory, self.gateway, self.sha, True)
        self.assertTrue(mail.verify(self.directory, self.gateway)["verified"])
        self.assertEqual(self.gateway.calls, 1)

    def test_uncertain_no_result_is_not_permission_to_retry(self):
        mail.write_private(self.directory / "attempt.json", mail.canonical(dict(sha256=self.sha,
                           message_id="<unknown>")), True)
        with self.assertRaises(ValueError): mail.verify(self.directory, self.gateway)
        with self.assertRaises(FileExistsError): mail.send(self.directory, self.gateway, self.sha, True)
        self.assertEqual(self.gateway.calls, 0)

    def test_wrong_delivery_is_saved_but_not_verified(self):
        self.gateway.corrupt = True
        with self.assertRaises(ValueError): mail.send(self.directory, self.gateway, self.sha, True)
        self.assertTrue((self.directory / "sent.json").exists())
        self.assertFalse((self.directory / "receipt.json").exists())

    def test_private_permissions_and_no_overwrite(self):
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        for p in self.directory.iterdir(): self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): self.make()

    def test_direct_mode_and_reply_to_are_explicit(self):
        self.gateway.parent["reply_to"] = CC
        mail.prepare(self.root / "direct", self.gateway, "test", "parent", "Text\nS\n",
                     "S", self.target, "direct")
        data = mail.build(self.root / "direct")["envelope"]
        self.assertEqual(data["to"], [CC])
        self.assertEqual(data["cc"], [])

    def test_missing_parent_message_id_refused(self):
        del self.gateway.parent["message_id"]
        with self.assertRaises(ValueError):
            mail.prepare(self.root / "bad", self.gateway, "test", "parent", "Text\nS\n",
                         "S", self.target)

    def test_unicode_body_and_subject_survive_mime_roundtrip(self):
        parent = mail.read_json(self.directory / "parent.json")
        parent["subject"] = "研究の質問"
        mail.write_private(self.directory / "parent.json", mail.canonical(parent))
        envelope = mail.read_json(self.directory / "envelope.json")
        envelope["subject"] = "Re: 研究の質問"
        envelope["signature"] = "署名"
        mail.write_private(self.directory / "envelope.json", mail.canonical(envelope))
        mail.write_private(self.directory / "reply.txt", "ありがとうございます。\n\n署名\n")
        mail.preview(self.directory)
        sha = mail.read_json(self.directory / "review.json")["sha256"]
        self.assertTrue(mail.send(self.directory, self.gateway, sha, True)["verified"])

    def test_broken_thread_metadata_cannot_be_repreviewed(self):
        p = self.directory / "envelope.json"
        original = p.read_text()
        for field in ["thread_id", "in_reply_to", "subject", "references"]:
            data = json.loads(original); data[field] = "broken"
            p.write_text(json.dumps(data))
            with self.subTest(field=field), self.assertRaises(ValueError): mail.preview(self.directory)
        p.write_text(original)


if __name__ == "__main__":
    unittest.main()
