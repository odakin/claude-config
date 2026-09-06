#!/usr/bin/env python3
"""Shared mail CLI/Gmail gateway with injected account factory; stdlib only.

Commands except `send --send` are read-only on Gmail. A review fingerprint is
an integrity check, not permission: explicit user send approval remains required.
"""
from __future__ import annotations

import argparse
import re
import socket
import sys
from pathlib import Path

import reviewed_mail as workflow


class Gateway:
    def __init__(self, direct, token):
        self.direct = direct
        self.token = token
        self.identity = self.direct.api("profile", token=self.token)["emailAddress"]

    def profile(self):
        return self.identity

    def api(self, path, params=None):
        return self.direct.api(path, params, token=self.token)

    def get(self, mid):
        data = self.api("messages/" + mid, {"format": "full"})
        headers = {h["name"].lower(): h["value"] for h in data["payload"].get("headers", [])}
        out = {k.replace("-", "_"): headers.get(k, "") for k in
               ["from", "to", "cc", "reply-to", "subject", "date", "message-id", "in-reply-to", "references"]}
        out["references"] = " ".join(out["references"].split())
        attachments = []
        def walk(part):
            if part.get("filename"):
                attachments.append(dict(filename=part["filename"], mime_type=part.get("mimeType"),
                                        size=part.get("body", {}).get("size")))
            for child in part.get("parts", []): walk(child)
        walk(data["payload"])
        out.update(id=mid, thread_id=data["threadId"], labels=data.get("labelIds", []),
                   body=self.direct._find_text(data["payload"]).replace("\r\n", "\n"), attachments=attachments)
        return out

    def send(self, raw, thread):
        return self.direct.post("messages/send", {"raw": raw, "threadId": thread}, self.token)

    def find(self, mid):
        result = self.api("messages", {"q": "in:sent rfc822msgid:" + mid, "maxResults": 3})
        return [m["id"] for m in result.get("messages", [])]

    def search(self, query, limit):
        found, token = [], None
        while len(found) < limit:
            params = {"q": query, "maxResults": min(100, limit - len(found))}
            if token: params["pageToken"] = token
            page = self.api("messages", params)
            for row in page.get("messages", []):
                data = self.api("messages/" + row["id"], {"format": "metadata",
                                "metadataHeaders": ["From", "To", "Cc", "Subject", "Date"]})
                h = {v["name"].lower(): v["value"] for v in data["payload"]["headers"]}
                found.append(dict(id=row["id"], thread_id=row["threadId"], **h))
            token = page.get("nextPageToken")
            if not token: break
        return dict(account=self.profile(), query=query, count=len(found), complete=not bool(token),
                    next_page_token=token, messages=found)


def parser(accounts=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ["read", "search", "prepare"]:
        q = sub.add_parser(name, allow_abbrev=False)
        q.add_argument("--account", required=True, choices=accounts)
        if name == "search":
            q.add_argument("--query", required=True)
            q.add_argument("--limit", type=int, default=50)
        else:
            q.add_argument("--message", required=True)
        if name == "prepare":
            q.add_argument("--bundle", required=True)
            q.add_argument("--reply-file", required=True)
            q.add_argument("--signature", required=True)
            q.add_argument("--record-target", required=True)
            q.add_argument("--mode", choices=["reply-all", "direct"], default="reply-all")
    for name in ["preview", "send", "verify", "recorded"]:
        q = sub.add_parser(name, allow_abbrev=False)
        q.add_argument("--bundle", required=True)
        if name == "send":
            q.add_argument("--approved-sha256", required=True)
            q.add_argument("--send", action="store_true", required=True)
    q = sub.add_parser("pending", allow_abbrev=False)
    q.add_argument("--root", default=str(Path.home() / ".codex/mail-workflow"))
    return p


def main(gateway_factory, accounts=None):
    a = parser(accounts).parse_args()
    socket.setdefaulttimeout(30)
    if a.command == "pending":
        rows = []
        for path in sorted(Path(a.root).glob("*/attempt.json")):
            receipt = path.with_name("receipt.json")
            data = workflow.read_json(receipt) if receipt.exists() else {"verified": False, "recorded": False}
            if not data.get("recorded"):
                rows.append(dict(bundle=str(path.parent), **data))
        print(workflow.canonical(rows)); return
    if a.command == "recorded":
        print(workflow.canonical(workflow.recorded(Path(a.bundle)))); return
    if a.command in {"preview", "send", "verify"}:
        a.account = workflow.read_json(Path(a.bundle) / "envelope.json")["account"]
        if a.command == "send":
            workflow.reviewed(Path(a.bundle), a.approved_sha256)  # fail before network
    if a.command == "search" and not 1 <= a.limit <= 500:
        raise ValueError("limit must be 1..500; narrow the query if complete=false")
    if getattr(a, "message", None) and not re.fullmatch(r"[0-9a-f]+", a.message):
        raise ValueError("Gmail message ID must be hexadecimal")
    gateway = gateway_factory(a.account)
    if a.command == "read": result = gateway.get(a.message)
    elif a.command == "search": result = gateway.search(a.query, a.limit)
    elif a.command == "prepare":
        directory = workflow.prepare(Path(a.bundle), gateway, a.account, a.message,
                  Path(a.reply_file).read_text(), a.signature, a.record_target, a.mode)
        print(workflow.preview(directory, gateway)); return
    elif a.command == "preview": print(workflow.preview(Path(a.bundle), gateway)); return
    elif a.command == "send": result = workflow.send(Path(a.bundle), gateway, a.approved_sha256, a.send)
    elif a.command == "verify": result = workflow.verify(Path(a.bundle), gateway)
    print(workflow.canonical(result))


def run(gateway_factory, accounts=None):
    try:
        main(gateway_factory, accounts)
    except Exception as exc:
        # Never dump credentials or a raw OAuth HTTP response.
        print(f"ERROR ({type(exc).__name__}): {exc}. If send was attempted, use verify; do not resend.", file=sys.stderr)
        raise SystemExit(1)
