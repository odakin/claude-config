#!/usr/bin/env python3
"""Reviewed plain-text replies, independent of credentials and agent products.

The injected gateway supplies profile(), get(id), send(raw, thread), and
find(message_id). No function here discovers accounts or reads agent history.
Local bundles are evidence, not proof of human authorization. The caller must
obtain explicit approval of the preview before invoking send().
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_private(path, text, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    parent_fd = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def read_json(path):
    return json.loads(Path(path).read_text())


def addresses(value):
    result = []
    for _, addr in getaddresses([value or ""]):
        if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+", addr):
            raise ValueError("Invalid or unsupported address")
        if addr.lower() not in [a.lower() for a in result]:
            result.append(addr)
    return result


def quote(parent):
    return ("\n------- Original Message -------\nOn " + parent["date"] + ", "
            + parent["from"] + " wrote:\n\n"
            + "\n".join("> " + line for line in parent["body"].splitlines()) + "\n")


def prepare(directory, gateway, account, parent_id, reply, signature, record_target,
            mode="reply-all"):
    """Read only remotely; create one local bundle, refusing overwrite."""
    sender = gateway.profile()
    parent = gateway.get(parent_id)
    if not parent.get("message_id") or not parent.get("subject") or not parent.get("body", "").strip():
        raise ValueError("Parent needs Message-ID, subject, and readable body")
    if not re.fullmatch(r"<[^\s<>]+>", parent["message_id"]):
        raise ValueError("Invalid parent Message-ID")
    if mode not in {"reply-all", "direct"}:
        raise ValueError("Unsupported recipient mode")
    to = addresses(parent.get("reply_to") or parent["from"])
    peers = addresses(parent.get("to", "") + "," + parent.get("cc", ""))
    if sender.lower() in [a.lower() for a in to]:
        raise ValueError("Select an incoming parent, not your own sent message")
    cc = [a for a in peers if a.lower() not in [sender.lower()] + [x.lower() for x in to]]
    if not to:
        raise ValueError("No recipient")
    if mode == "direct":
        cc = []
    target = Path(record_target).expanduser().resolve()
    if not target.is_file():
        raise ValueError("Record target must be an existing project ledger")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    data = dict(version=1, account=account, sender=sender, to=to, cc=cc,
                subject=(parent["subject"] if parent["subject"].lower().startswith("re:")
                         else "Re: " + parent["subject"]),
                parent_id=parent_id, thread_id=parent["thread_id"],
                in_reply_to=parent["message_id"],
                references=(parent.get("references", "") + " " + parent["message_id"]).strip(),
                message_id=make_msgid(domain=sender.split("@", 1)[1]),
                signature=signature, record_target=str(target), recipient_mode=mode)
    write_private(directory / "parent.json", canonical(parent), True)
    write_private(directory / "envelope.json", canonical(data), True)
    write_private(directory / "reply.txt", reply, True)
    return directory


def build(directory):
    directory = Path(directory)
    envelope = read_json(directory / "envelope.json")
    parent = read_json(directory / "parent.json")
    reply = (directory / "reply.txt").read_text()
    if not envelope["signature"] or reply.rstrip().splitlines()[-1:] != [envelope["signature"]]:
        raise ValueError("Reply must end with the selected signature")
    if "------- Original Message -------" in reply:
        raise ValueError("Edit reply.txt only; original quote is generated")
    if re.search(r"&(?:[a-zA-Z][a-zA-Z0-9]+|#\d+|#x[0-9a-fA-F]+);", reply):
        raise ValueError("HTML entities in plain-text reply")
    if "**" in reply:
        raise ValueError("Markdown bold in plain-text reply")
    if envelope["in_reply_to"] != parent["message_id"] or envelope["thread_id"] != parent["thread_id"]:
        raise ValueError("Envelope does not match parent")
    expected_subject = (parent["subject"] if parent["subject"].lower().startswith("re:")
                        else "Re: " + parent["subject"])
    expected_references = (parent.get("references", "") + " " + parent["message_id"]).strip()
    if envelope["subject"] != expected_subject or envelope["references"] != expected_references:
        raise ValueError("Reply subject/references must preserve the parent thread")
    for key in ["sender", "subject", "in_reply_to", "references", "message_id"]:
        if any(c in envelope[key] for c in "\r\n"):
            raise ValueError("Header injection")
    for key in ["sender", "to", "cc"]:
        values = [envelope[key]] if key == "sender" else envelope[key]
        for value in values:
            if addresses(value) != [value]:
                raise ValueError("Invalid envelope address")
    if not envelope["to"]:
        raise ValueError("No recipient")
    body = reply.rstrip("\n") + "\n" + quote(parent)
    return dict(envelope=envelope, body=body)


def preview(directory, gateway=None):
    directory = Path(directory)
    if (directory / "attempt.json").exists():
        raise ValueError("A send was attempted; use verify, never re-preview for retry")
    content = build(directory)
    if gateway and gateway.profile() != content["envelope"]["sender"]:
        raise ValueError("Account identity changed")
    sha = digest(content)
    write_private(directory / "review.json", canonical(dict(sha256=sha, **content)))
    write_private(directory / "body.txt", content["body"])
    e = content["envelope"]
    text = (f"DRY RUN — NOT SENT\nAccount: {e['account']}\nFrom: {e['sender']}\n"
            f"To: {', '.join(e['to'])}\nCc: {', '.join(e['cc']) or '(none)'}\n"
            f"Subject: {e['subject']}\nAttachments: none\nThread: {e['thread_id']}\n"
            f"In-Reply-To: {e['in_reply_to']}\nReferences: {e['references']}\n"
            f"Record target: {e['record_target']}\nSHA256: {sha}\n\n{content['body']}")
    write_private(directory / "preview.txt", text)
    return text


def reviewed(directory, approved_sha256):
    content = build(directory)
    saved = read_json(Path(directory) / "review.json")
    if not approved_sha256 or approved_sha256 != digest(content) or saved != dict(sha256=approved_sha256, **content):
        raise ValueError("Preview changed or approval fingerprint missing; preview and review again")
    if (Path(directory) / "body.txt").read_text() != content["body"]:
        raise ValueError("Generated body changed; preview and review again")
    return content


def raw_message(content):
    e = content["envelope"]
    msg = EmailMessage(policy=policy.SMTP)
    for header, key in [("From", "sender"), ("Subject", "subject"),
                        ("In-Reply-To", "in_reply_to"), ("References", "references"),
                        ("Message-ID", "message_id")]:
        msg[header] = e[key]
    msg["To"] = ", ".join(e["to"])
    if e["cc"]:
        msg["Cc"] = ", ".join(e["cc"])
    msg.set_content(content["body"], charset="utf-8")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send(directory, gateway, approved_sha256, send_requested=False):
    """Single attempt per bundle. Never retry POST, even after timeout."""
    directory = Path(directory)
    if not send_requested:
        raise ValueError("Explicit --send required; use preview for dry run")
    content = reviewed(directory, approved_sha256)
    if gateway.profile() != content["envelope"]["sender"]:
        raise ValueError("Account identity changed")
    payload = raw_message(content)
    attempt = dict(sha256=approved_sha256, message_id=content["envelope"]["message_id"],
                   started=datetime.now(timezone.utc).isoformat())
    # O_EXCL is the interprocess lock and survives crashes. No cleanup/retry.
    write_private(directory / "attempt.json", canonical(attempt), True)
    result = gateway.send(payload, content["envelope"]["thread_id"])
    write_private(directory / "sent.json", canonical(result), True)
    return verify(directory, gateway)


def verify(directory, gateway):
    directory = Path(directory)
    attempt = read_json(directory / "attempt.json")
    content = reviewed(directory, attempt["sha256"])
    if gateway.profile() != content["envelope"]["sender"]:
        raise ValueError("Account identity changed")
    if (directory / "sent.json").exists():
        sent = read_json(directory / "sent.json")
    else:
        matches = gateway.find(attempt["message_id"])
        if len(matches) != 1:
            raise ValueError("Send outcome uncertain: no unique match. Do not resend")
        sent = dict(id=matches[0])
        write_private(directory / "sent.json", canonical(sent), True)
    actual = gateway.get(sent["id"])
    e = content["envelope"]
    normalize = lambda s: s.replace("\r\n", "\n").replace("\r", "\n")
    if ("SENT" not in actual["labels"] or actual["thread_id"] != e["thread_id"]
            or addresses(actual["from"]) != [e["sender"]]
            or addresses(actual["to"]) != e["to"] or addresses(actual.get("cc", "")) != e["cc"]
            # Gmail may replace the client-supplied RFC Message-ID. The
            # messages.send response's immutable Gmail ID anchors this read.
            or actual["subject"] != e["subject"] or not actual.get("message_id")
            or actual["in_reply_to"] != e["in_reply_to"]
            or " ".join(actual.get("references", "").split()) != " ".join(e["references"].split())
            or normalize(actual["body"]) != normalize(content["body"]) or actual.get("attachments")):
        raise ValueError("Sent message mismatch. Do not resend; inspect sent.json")
    receipt = dict(message_id=sent["id"], thread_id=e["thread_id"], account=e["account"],
                   requested_rfc_message_id=e["message_id"], actual_rfc_message_id=actual["message_id"],
                   date=actual["date"], sha256=attempt["sha256"], record_target=e["record_target"],
                   verified=True, recorded=False)
    if (directory / "receipt.json").exists():
        receipt["recorded"] = read_json(directory / "receipt.json").get("recorded", False)
    write_private(directory / "receipt.json", canonical(receipt))
    return receipt


def recorded(directory):
    directory = Path(directory)
    receipt = read_json(directory / "receipt.json")
    text = Path(receipt["record_target"]).read_text()
    if not receipt["verified"] or receipt["message_id"] not in text or receipt["thread_id"] not in text:
        raise ValueError("Verified message and thread IDs not yet present in target ledger")
    receipt["recorded"] = True
    write_private(directory / "receipt.json", canonical(receipt))
    return receipt


def decode_raw(raw):
    """MIME parser for adapters/tests; no private state access."""
    msg = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
    return msg
