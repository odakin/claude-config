# agent-authority:file
"""Read direct composer input in one native desktop Codex rollout, read-only.

The reader checks the observed desktop record format. None means that the
evidence is incomplete or unsupported. The calling policy owns liveness and
authorization. Local records are not a signed identity or process credential.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID, RFC_4122

from codex_threads import THREAD_ID, codex_home as configured_codex_home


_DESKTOP_TRIGGERS = {"composer", "app_tool_create_thread", "send_user_message_async_question"}
_QUESTION_TOOL = "request_user_input_async"
_QUESTION_REPLY = re.compile(r"<send_user_message_question_reply>(.*)</send_user_message_question_reply>", re.S)
_HEARTBEAT = re.compile(r"<heartbeat>.+</heartbeat>", re.S)


def codex_home() -> Path:
    # A command can set its own HOME or CODEX_HOME. Resolve the evidence root
    # from the OS account so an agent cannot supply a fixture as production input.
    import pwd

    return configured_codex_home({"HOME": pwd.getpwuid(os.getuid()).pw_dir})


def _unique_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _decode(text):
    return json.loads(text, object_pairs_hook=_unique_members)


def _record(line):
    entry = _decode(line)
    if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
        raise ValueError("invalid rollout record")
    return entry, entry["payload"]


def _uuid_version(value):
    if not isinstance(value, str) or not THREAD_ID.fullmatch(value):
        return None
    parsed = UUID(value)
    return parsed.version if parsed.variant == RFC_4122 else None


def _receipt(entry, payload, session_id, turn_id, text):
    if (entry.get("type") != "event_msg" or payload.get("type") != "item_completed"
            or payload.get("thread_id") != session_id or payload.get("turn_id") != turn_id):
        raise ValueError("missing matching native receipt")
    item = payload.get("item")
    if (not isinstance(item, dict) or item.get("type") != "UserMessage"
            or item.get("content") != [{"type": "text", "text": text, "text_elements": []}]):
        raise ValueError("invalid native receipt")
    return _uuid_version(item.get("client_id"))


def _questions(payload):
    questions = _decode(payload["arguments"])["questions"]
    if not isinstance(questions, list) or not questions:
        raise ValueError("missing questions")
    titles = tuple(question["title"] for question in questions)
    if not all(isinstance(title, str) and title for title in titles):
        raise ValueError("invalid question titles")
    return titles


def _question_id(value):
    if not isinstance(value, str):
        raise ValueError("invalid question id")
    if r'\"' in value:
        value = _decode('"' + value + '"')
    fields = _decode(value)
    if (not isinstance(fields, list) or len(fields) != 3 or fields[0] != _QUESTION_TOOL
            or not isinstance(fields[1], str) or type(fields[2]) is not int or fields[2] < 0):
        raise ValueError("invalid question id")
    return fields[1], fields[2]


def _question_replies(document, questions, answered):
    replies = _decode(document)
    if not isinstance(replies, list) or not replies:
        raise ValueError("missing question replies")
    titles, answers = [], []
    for reply in replies:
        if not isinstance(reply, dict) or reply.keys() != {"questionItemId", "question", "answer"}:
            raise ValueError("invalid question reply")
        call_id, index = key = _question_id(reply["questionItemId"])
        if (key in answered or questions[call_id][index] != reply["question"]
                or not isinstance(reply["answer"], str)):
            raise ValueError("unmatched or duplicate question reply")
        answered.add(key)
        titles.append(reply["question"])
        answers.append(reply["answer"])
    return {"ui_questions": titles, "ui_answers": answers}


def _owner_records(lines, session_id):
    first, meta = _record(next(lines)[1])
    source = meta.get("thread_source")
    if (first.get("type") != "session_meta" or meta.get("id") != session_id
            or meta.get("session_id", session_id) != session_id or meta.get("source") != "vscode"
            or source not in ("user", "agent_created_thread") or meta.get("parent_thread_id") is not None):
        raise ValueError("unsupported native thread")

    owner, messages, turns = [], set(), set()
    questions, answered = {}, set()
    turn_id = trigger = None
    for line, raw in lines:
        entry, payload = _record(raw)
        kind, item_type = entry.get("type"), payload.get("type")
        if kind == "session_meta":
            raise ValueError("duplicate native session metadata")
        if kind == "event_msg" and item_type == "task_started":
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id or turn_id in turns:
                raise ValueError("invalid native turn")
            turns.add(turn_id)
            tag = payload.get("turn_attribution")
            trigger = None
            if (isinstance(tag, dict) and tag.get("turn_id") == turn_id
                    and "initiating_agent_path" in tag and tag["initiating_agent_path"] is None):
                trigger = tag.get("turn_trigger")
            continue
        if kind == "event_msg" and item_type == "item_completed":
            item = payload.get("item")
            if (isinstance(item, dict) and item.get("type") == "UserMessage"
                    and _uuid_version(item.get("client_id")) == 4):
                raise ValueError("orphaned composer receipt")
            continue
        if kind != "response_item":
            continue
        if (item_type == "function_call" and payload.get("name") == _QUESTION_TOOL
                and payload.get("namespace") in (None, "functions")):
            call_id = payload.get("call_id")
            if not isinstance(call_id, str) or not call_id or call_id in questions:
                raise ValueError("invalid or duplicate question call")
            questions[call_id] = _questions(payload)
            continue
        if payload.get("role") != "user":
            meta = entry.get("metadata") or {}
            retained = meta.get("retained_source") or {}
            if (retained.get("id") or {}).get("role") == "user":
                raise ValueError("conflicting retained user role")
            continue
        if item_type != "message":
            raise ValueError("unsupported user record")

        carrier = payload["internal_chat_message_metadata_passthrough"]
        kinds, infos = carrier["content_item_kinds"], carrier["content_item_metadata"]
        if (isinstance(infos, list) and infos and all(
                isinstance(info, dict) and info.get("provenance") == {"type": "harness", "hook": True}
                for info in infos)):
            continue

        meta = entry["metadata"]
        content = payload.get("content")
        # Desktop may combine repository instructions and the environment context
        # in a user-role record before the first composer message.
        if (not messages and trigger == "composer" and carrier.get("turn_id") == turn_id
                and meta.get("client_authored") is False and "retained_source" not in meta
                and kinds == ["agents_md.instructions", "environments.environment_context"]
                and infos == [{"provenance": {"type": "agents_md"}},
                              {"provenance": {"type": "harness", "hook": False}}]
                and isinstance(content, list) and len(content) == 2
                and all(isinstance(part, dict) and part.get("type") == "input_text"
                        and isinstance(part.get("text"), str) for part in content)):
            continue
        retained = meta["retained_source"]
        message_id, timestamp = payload.get("id"), entry.get("timestamp")
        if (not isinstance(message_id, str) or not message_id or message_id in messages
                or not isinstance(timestamp, str) or not timestamp or turn_id is None
                or carrier.get("turn_id") != turn_id or retained.get("complete") is not True
                or retained.get("id") != {"message_id": message_id, "turn_id": turn_id, "role": "user"}
                or infos != [{"provenance": {"type": "user"}}] or not isinstance(content, list)
                or len(content) != 1 or content[0].get("type") != "input_text"
                or not isinstance(content[0].get("text"), str)):
            raise ValueError("incomplete retained user message")
        messages.add(message_id)
        text = content[0]["text"]
        native, receipt = _record(next(lines)[1])
        version = _receipt(native, receipt, session_id, turn_id, text)
        if trigger == "automation_heartbeat_scheduled" and kinds == ["user.heartbeat"] and _HEARTBEAT.fullmatch(text):
            continue
        if kinds != ["user.text"]:
            raise ValueError("unsupported user item")
        if trigger in ("queue", "app_tool_create_thread") and version == 7:
            continue
        if trigger not in _DESKTOP_TRIGGERS or version != 4:
            raise ValueError("unknown user input carrier")
        if trigger == "app_tool_create_thread" and source != "agent_created_thread":
            raise ValueError("unsupported tool-created turn")
        if meta.get("sender_user_messages"):
            continue

        proof = {"text": text, "line": line, "timestamp": timestamp, "message_id": message_id,
                 "turn_id": turn_id, "trigger": trigger}
        reply = _QUESTION_REPLY.fullmatch(text)
        if reply:
            proof.update(_question_replies(reply[1], questions, answered))
        elif trigger == "send_user_message_async_question" or "<send_user_message_question_reply" in text:
            raise ValueError("missing or malformed question reply")
        owner.append(proof)
    return owner


def read_owner_inputs(path: Path, session_id: str) -> list[dict] | None:
    """Return validated inputs in order, or None when evidence is incomplete."""
    if not THREAD_ID.fullmatch(session_id):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, encoding="utf-8") as file:
            before = os.fstat(file.fileno())
            if not stat.S_ISREG(before.st_mode):
                return None
            evidence = _owner_records(iter(enumerate(file, 1)), session_id)
            after = os.fstat(file.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            return None
        return evidence
    except (AttributeError, IndexError, KeyError, OSError, RecursionError, StopIteration, TypeError, ValueError):
        return None


def owner_inputs(session_id: str) -> list[dict] | None:
    """Resolve a single matching rollout in the OS account's native data root."""
    if not THREAD_ID.fullmatch(session_id):
        return None
    try:
        home = codex_home()
        walked_errors, matches = [], []
        for name in ("sessions", "archived_sessions"):
            root = home / name
            try:
                mode = root.lstat().st_mode
            except FileNotFoundError:
                if name == "archived_sessions":
                    continue
                raise
            if not stat.S_ISDIR(mode):
                return None
            for directory, subdirs, files in os.walk(root, onerror=walked_errors.append):
                if any((Path(directory) / child).is_symlink() for child in subdirs):
                    return None
                matches.extend(Path(directory) / file for file in files
                               if file.startswith("rollout-") and f"-{session_id}." in file)
        if walked_errors or len(matches) != 1 or not matches[0].name.endswith(f"-{session_id}.jsonl"):
            return None
        return read_owner_inputs(matches[0], session_id)
    except (ImportError, KeyError, OSError):
        return None
