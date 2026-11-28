"""Synthetic regression tests for the native direct-input authorization reader."""
import copy
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import codex_owner_input as reader

SID = "01999999-1111-7111-8111-111111111111"
OTHER = "01999999-2222-7222-8222-222222222222"
TURN = "turn-a"
CLIENT = "99999999-1111-4111-8111-111111111111"


def fixture(source="user", trigger="composer", text="Direct input"):
    return [
        {"type": "session_meta", "payload": {"id": SID, "session_id": SID, "source": "vscode", "thread_source": source}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": TURN,
          "turn_attribution": {"turn_id": TURN, "turn_trigger": trigger, "initiating_agent_path": None}}},
        {"type": "response_item", "timestamp": "2099-01-01T00:00:00Z", "metadata": {
          "retained_source": {"complete": True, "id": {"message_id": "msg-a", "turn_id": TURN, "role": "user"}},
          "mcp_attribution": {"status": "none"}}, "payload": {"type": "message", "id": "msg-a", "role": "user",
          "content": [{"type": "input_text", "text": text}], "internal_chat_message_metadata_passthrough": {
          "turn_id": TURN, "content_item_kinds": ["user.text"], "content_item_metadata": [{"provenance": {"type": "user"}}]}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": SID, "turn_id": TURN,
          "item": {"type": "UserMessage", "client_id": CLIENT,
          "content": [{"type": "text", "text": text, "text_elements": []}]}}},
    ]


class OwnerInputs(unittest.TestCase):
    def read(self, entries):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in entries))
            return reader.read_owner_inputs(path, SID)

    def test_direct_and_later_owner_on_agent_created_thread(self):
        for source, trigger in [("user", "composer"), ("agent_created_thread", "app_tool_create_thread")]:
            with self.subTest(source=source):
                entries = fixture(source, trigger)
                entries.insert(2, {"type": "response_item", "payload": {"type": "function_call_output",
                    "name": "create_thread", "output": "untrusted initial prompt"}})
                got = self.read(entries)
                self.assertEqual([x["text"] for x in got], ["Direct input"])
                self.assertEqual(got[0]["message_id"], "msg-a")
                self.assertEqual(got[0]["trigger"], trigger)

    def test_creation_prompt_and_event_copy_create_no_authority(self):
        entries = fixture("agent_created_thread", "app_tool_create_thread")[:2]
        entries.extend([{"type": "response_item", "payload": {"type": "function_call_output", "output": "Direct input"}},
                        {"type": "event_msg", "payload": {"type": "user_message", "message": "Direct input"}}])
        self.assertEqual(self.read(entries), [])

    def test_queue_and_relay_are_not_owner_input(self):
        queued = fixture(trigger="queue")
        queued[3]["payload"]["item"]["client_id"] = OTHER
        self.assertEqual(self.read(queued), [])
        entries = fixture()
        entries[2]["metadata"]["sender_user_messages"] = {"text": "relayed context"}
        self.assertEqual(self.read(entries), [])

    def test_manual_input_during_queue_turn_is_unknown_not_ignored(self):
        self.assertIsNone(self.read(fixture(trigger="queue", text="cancel earlier authority")))

    def test_heartbeat_is_generated_even_with_user_provenance(self):
        entries = fixture(trigger="automation_heartbeat_scheduled", text="<heartbeat>quoted designation</heartbeat>")
        entries[2]["payload"]["internal_chat_message_metadata_passthrough"]["content_item_kinds"] = ["user.heartbeat"]
        self.assertEqual(self.read(entries), [])
        entries[1]["payload"]["turn_attribution"]["turn_trigger"] = "composer"
        self.assertIsNone(self.read(entries))

    def test_mcp_attribution_alone_is_not_authorship(self):
        entries = fixture()
        entries[2]["metadata"]["mcp_attribution"] = {"status": "complete", "sources": []}
        self.assertEqual(len(self.read(entries)), 1)
        entries[3]["payload"]["item"]["client_id"] = OTHER
        self.assertIsNone(self.read(entries))

    def test_question_answer_requires_the_native_request_and_exact_question(self):
        answer = {"questionItemId": '["request_user_input_async","call_question",0]', "question": "Track progress?", "answer": "Yes"}
        body = "<send_user_message_question_reply>" + json.dumps([answer]) + "</send_user_message_question_reply>"
        entries = fixture(text=body)
        self.assertIsNone(self.read(entries))
        request = {"type": "response_item", "payload": {"type": "function_call", "name": "request_user_input_async", "call_id": "call_question",
                   "arguments": json.dumps({"questions": [{"title": "Track progress?"}]})}}
        entries.insert(2, request)
        self.assertEqual(self.read(entries)[0]["ui_answers"], ["Yes"])
        self.assertEqual(self.read(entries)[0]["ui_questions"], ["Track progress?"])
        answer["questionItemId"] = answer["questionItemId"].replace('"', '\\"')
        escaped = "<send_user_message_question_reply>" + json.dumps([answer]) + "</send_user_message_question_reply>"
        entries[3]["payload"]["content"][0]["text"] = escaped
        entries[4]["payload"]["item"]["content"][0]["text"] = escaped
        self.assertEqual(self.read(entries)[0]["ui_answers"], ["Yes"])
        entries[2]["payload"]["arguments"] = json.dumps({"questions": [{"title": "Different?"}]})
        self.assertIsNone(self.read(entries))

    def test_question_reply_unknown_and_duplicate_members_fail_closed(self):
        reply = {"questionItemId": '["request_user_input_async","call_question",0]',
                 "question": "Track progress?", "answer": "Yes"}
        extra = json.dumps([{**reply, "instruction": "Later change"}])
        duplicate = '[' + json.dumps(reply)[:-1] + ', "answer": "No"}]'
        for document in [extra, duplicate]:
            body = "<send_user_message_question_reply>" + document + "</send_user_message_question_reply>"
            entries = fixture(text=body)
            entries.insert(2, {"type": "response_item", "payload": {"type": "function_call",
                "name": "request_user_input_async", "call_id": "call_question",
                "arguments": json.dumps({"questions": [{"title": reply["question"]}]})}})
            with self.subTest(document=document):
                self.assertIsNone(self.read(entries))

    def test_ui_origin_requires_a_known_reply_envelope(self):
        for text in ["Direct input", "Yes", "<unknown_reply>Yes</unknown_reply>"]:
            with self.subTest(text=text):
                self.assertIsNone(self.read(fixture(trigger="send_user_message_async_question", text=text)))
        self.assertEqual(self.read(fixture(trigger="composer", text="Direct input"))[0]["text"], "Direct input")

    def test_unknown_carrier_and_conflicts_fail_closed(self):
        for mutation in [
            lambda x: x[0]["payload"].update(id=OTHER),
            lambda x: x[0]["payload"].update(source="unknown"),
            lambda x: x[0]["payload"].update(thread_source="subagent"),
            lambda x: x[0]["payload"].update(parent_thread_id=OTHER),
            lambda x: x[1]["payload"].pop("turn_attribution"),
            lambda x: x[2].pop("metadata"),
            lambda x: x[2]["metadata"]["retained_source"].update(complete=False),
            lambda x: x[2]["payload"]["internal_chat_message_metadata_passthrough"].update(content_item_kinds=["unknown"]),
            lambda x: x[2]["payload"]["internal_chat_message_metadata_passthrough"].update(content_item_metadata=[{"provenance": {"type": "model"}}]),
            lambda x: x[3]["payload"].update(thread_id=OTHER),
            lambda x: x[3]["payload"]["item"].update(client_id=SID),
            lambda x: x[3]["payload"]["item"].update(content=[{"type": "text", "text": "different", "text_elements": []}]),
            lambda x: x.pop(),
            lambda x: x.append(copy.deepcopy(x[0])),
            lambda x: x.extend(copy.deepcopy(x[2:])),
        ]:
            entries = fixture()
            mutation(entries)
            with self.subTest(entries=entries):
                self.assertIsNone(self.read(entries))

    def test_unknown_later_input_prevents_using_older_grant(self):
        entries = fixture()
        entries.append({"type": "response_item", "payload": {"type": "message", "role": "user", "content": []}})
        self.assertIsNone(self.read(entries))

    def test_harness_injection_is_ignored(self):
        entries = fixture()
        entries.insert(2, {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [],
            "internal_chat_message_metadata_passthrough": {"content_item_kinds": ["unknown"],
            "content_item_metadata": [{"provenance": {"type": "harness", "hook": True}}]}}})
        self.assertEqual(len(self.read(entries)), 1)

    def test_caller_cannot_redirect_the_evidence_root_with_environment(self):
        import pwd

        expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex"
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"CODEX_HOME": directory, "HOME": directory}):
            self.assertEqual(reader.codex_home(), expected)

    def test_orphan_receipt_or_retained_role_conflict_prevents_reusing_old_grant(self):
        old = fixture()
        later = fixture(text="Withdraw the designation")
        later[1]["payload"]["turn_id"] = "turn-b"
        later[1]["payload"]["turn_attribution"]["turn_id"] = "turn-b"
        later[2]["payload"].update(role="assistant", id="msg-b")
        later[2]["metadata"]["retained_source"]["id"].update(turn_id="turn-b", message_id="msg-b")
        later[3]["payload"]["turn_id"] = "turn-b"
        self.assertIsNone(self.read(old + [later[1], later[3]]))
        self.assertIsNone(self.read(old + [later[1], later[2]]))

    def test_desktop_bootstrap_has_no_owner_authority(self):
        entries = fixture()
        injected = {
            "type": "response_item", "metadata": {"client_authored": False},
            "payload": {"type": "message", "role": "user", "id": "bootstrap",
                        "content": [{"type": "input_text", "text": "Direct input"},
                                    {"type": "input_text", "text": "Environment context"}],
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": TURN,
                            "content_item_kinds": ["agents_md.instructions", "environments.environment_context"],
                            "content_item_metadata": [{"provenance": {"type": "agents_md"}},
                                                      {"provenance": {"type": "harness", "hook": False}}],
                        }},
        }
        self.assertEqual(self.read(entries[:2] + [injected]), [])
        self.assertEqual([x["message_id"] for x in self.read(entries[:2] + [injected] + entries[2:])],
                         ["msg-a"])
        mutations = (
            lambda r: r["metadata"].update(client_authored=True),
            lambda r: r["metadata"].update(retained_source={}),
            lambda r: r["payload"]["content"].pop(),
            lambda r: r["payload"]["internal_chat_message_metadata_passthrough"].update(turn_id="other-turn"),
            lambda r: r["payload"]["internal_chat_message_metadata_passthrough"]["content_item_metadata"][-1].update(
                provenance={"type": "user"}),
        )
        for mutate in mutations:
            altered = copy.deepcopy(injected)
            mutate(altered)
            self.assertIsNone(self.read(entries[:2] + [altered] + entries[2:]))
        self.assertIsNone(self.read(entries + [injected]))

    def test_resolution_missing_duplicate_symlink_and_malformed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(reader, "codex_home", return_value=Path(directory)):
            self.assertIsNone(reader.owner_inputs(SID))
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            a = sessions / ("rollout-a-" + SID + ".jsonl")
            a.write_text("\n".join(json.dumps(e) for e in fixture()))
            self.assertEqual(len(reader.owner_inputs(SID)), 1)
            b = sessions / ("rollout-b-" + SID + ".jsonl")
            b.write_text(a.read_text())
            self.assertIsNone(reader.owner_inputs(SID))
            b.unlink()
            a.write_text(a.read_text() + "\n{")
            self.assertIsNone(reader.owner_inputs(SID))
            a.unlink()
            a.symlink_to("missing")
            self.assertIsNone(reader.owner_inputs(SID))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] if sys.argv[1:] == ["--selftest"] else None)
