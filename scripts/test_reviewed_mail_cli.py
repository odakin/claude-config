#!/usr/bin/env python3
"""Offline checks: CLI authorization shape, pagination, full source extraction."""
import contextlib
import io
import unittest
from pathlib import Path

import reviewed_mail_cli as m


class EntryTests(unittest.TestCase):
    def test_send_cannot_default_or_abbreviate_flags(self):
        base = ["send", "--bundle", "unused", "--approved-sha256", "abc"]
        for suffix in [[], ["--sen"], ["--dry-run"]]:
            with self.subTest(suffix=suffix), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                m.parser().parse_args(base + suffix)
        self.assertTrue(m.parser().parse_args(base + ["--send"]).send)

    def test_search_reports_limit_and_follows_pages(self):
        g = m.Gateway.__new__(m.Gateway)
        g.identity = "test"
        seen = []
        def api(path, params):
            seen.append((path, params))
            if path == "messages":
                if params.get("pageToken"):
                    return {"messages": [{"id": "b", "threadId": "t"}]}
                return {"messages": [{"id": "a", "threadId": "t"}], "nextPageToken": "next"}
            return {"payload": {"headers": [{"name": "Subject", "value": "Test"}]}}
        g.api = api
        self.assertFalse(g.search("query", 1)["complete"])
        result = g.search("query", 2)
        self.assertTrue(result["complete"])
        self.assertEqual([v["id"] for v in result["messages"]], ["a", "b"])
        self.assertTrue(any(p.get("pageToken") == "next" for _, p in seen))

    def test_read_exposes_cc_reply_to_and_nested_attachment(self):
        g = m.Gateway.__new__(m.Gateway)
        g.api = lambda *a: {"threadId": "t", "payload": {"headers": [
            {"name": "Cc", "value": "peer"}, {"name": "Reply-To", "value": "reply"}],
            "parts": [{"parts": [{"filename": "資料.pdf", "mimeType": "application/pdf", "body": {"size": 10}}]}]}}
        g.direct = type("Direct", (), {"_find_text": staticmethod(lambda _: "full\r\nbody")})
        result = g.get("id")
        self.assertEqual(result["cc"], "peer")
        self.assertEqual(result["reply_to"], "reply")
        self.assertEqual(result["body"], "full\nbody")
        self.assertEqual(result["attachments"][0]["filename"], "資料.pdf")

    def test_thread_listing_maps_fields_and_fails_closed(self):
        g = m.Gateway.__new__(m.Gateway)
        seen = []
        def api(path, params):
            seen.append((path, params))
            return {"messages": [
                {"id": "a1", "internalDate": "1700", "labelIds": ["INBOX"], "snippet": "hi",
                 "payload": {"headers": [{"name": "From", "value": "peer"},
                                         {"name": "Message-ID", "value": "<a1>"}]}},
                {"id": "b2", "payload": {"headers": []}}]}
        g.api = api
        rows = g.thread("abc123")
        self.assertEqual(seen[0][0], "threads/abc123")
        self.assertEqual(seen[0][1]["format"], "metadata")
        self.assertEqual(rows[0]["internal_date"], 1700)
        self.assertEqual((rows[0]["from"], rows[0]["message_id"], rows[0]["labels"]),
                         ("peer", "<a1>", ["INBOX"]))
        self.assertIsNone(rows[1]["internal_date"])
        with self.assertRaises(ValueError):
            g.thread("../x")

    def test_send_exits_6_until_newest_counterpart_acknowledged(self):
        import sys
        import tempfile
        import test_reviewed_mail as t
        import reviewed_mail as workflow
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ledger.txt").write_text("")
            gateway = t.Gateway()
            bundle = root / "bundle"
            workflow.prepare(bundle, gateway, "test", "parent", "Thanks\nS\n", "S", root / "ledger.txt")
            workflow.preview(bundle, gateway)
            sha = workflow.read_json(bundle / "review.json")["sha256"]
            gateway.add("abc", 200, t.PEER)
            base = ["reviewed-mail", "send", "--bundle", str(bundle), "--approved-sha256", sha, "--send"]
            saved = sys.argv
            try:
                for extra, code in [([], 6), (["--ack-newer", "def"], 6), (["--ack-newer", "abc"], None)]:
                    sys.argv = base + extra
                    err = io.StringIO()
                    with self.subTest(extra=extra), contextlib.redirect_stderr(err), \
                            contextlib.redirect_stdout(io.StringIO()):
                        if code is None:
                            m.run(lambda account: gateway)
                        else:
                            with self.assertRaises(SystemExit) as caught:
                                m.run(lambda account: gateway)
                            self.assertEqual(caught.exception.code, code)
                            self.assertIn("NOT SENT", err.getvalue())
            finally:
                sys.argv = saved
            self.assertEqual(gateway.calls, 1)
            self.assertEqual(workflow.read_json(bundle / "attempt.json")["acknowledged_newer"], "abc")


if __name__ == "__main__": unittest.main()
