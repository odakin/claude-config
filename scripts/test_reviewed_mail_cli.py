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


if __name__ == "__main__": unittest.main()
