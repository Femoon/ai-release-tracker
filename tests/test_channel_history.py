import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from scripts.audit_channel_history import parse_channel
from scripts.repair_channel_history import apply_channel, prepare, verify_snapshot


class HistoryRepairTests(unittest.TestCase):
    def run_repair(self, html=None, error=None):
        session = Mock()
        session.post.side_effect = [
            Mock(json=lambda: {"ok": True, "result": {"username": "codex_push"}}),
            Mock(json=lambda: {"ok": True, "result": {"message_id": 259}}),
        ]
        session.get.return_value = Mock(text=html)
        session.get.side_effect = error
        plan = {"channel": "codex_push", "post": "codex_push/259", "id": 259,
                "before": "**original**", "after": "repaired", "sha256": "test",
                "before_body": {"tag": "div", "children": [{"tag": "b", "children": ["original"]}]}}
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.repair_channel_history.requests.Session", return_value=session
        ), patch("scripts.repair_channel_history.wait_for_edit_slot"), patch(
            "scripts.repair_channel_history.time.sleep"
        ):
            result = apply_channel([plan], {"CODEX_BOT_TOKEN": "dummy"}, Path(directory))
        return result[0], session

    def test_changed_or_missing_message_never_edits(self):
        for body in ("<b>updated by checker</b>", "<b>original</b><a href='https://new.test'>link</a>", None):
            html = (f'<div data-post="codex_push/259"><div class="tgme_widget_message_text">{body}</div></div>'
                    if body else '<div>Post not found</div>')
            result, session = self.run_repair(html)
            self.assertFalse(result["ok"])
            self.assertEqual(session.post.call_count, 1)  # getChat only

    def test_unreadable_message_never_edits(self):
        result, session = self.run_repair(error=requests.Timeout())
        self.assertFalse(result["ok"])
        self.assertEqual(session.post.call_count, 1)

    def test_plain_text_preserving_entity_changes_are_rejected(self):
        for entity in ("i", "em", "s", "u", "code", "blockquote"):
            with self.subTest(entity=entity):
                session = Mock()
                session.get.return_value = Mock(text=(
                    '<div data-post="codex_push/259"><div class="tgme_widget_message_text">'
                    f'<{entity}>original</{entity}></div></div>'
                ))
                plan = {"post": "codex_push/259", "before": "original",
                        "before_body": {"tag": "div", "children": ["original"]}}
                self.assertIn("changed", verify_snapshot(session, plan))

    def test_legacy_plan_without_structure_is_rejected_before_read(self):
        session = Mock()
        self.assertIn("regenerate", verify_snapshot(session, {"post": "codex_push/259", "before": "original"}))
        session.get.assert_not_called()

    def test_wrapper_variation_and_equivalent_emphasis_are_accepted(self):
        session = Mock()
        session.get.return_value = Mock(text=(
            '<div data-post="codex_push/259"><div class="tgme_widget_message_text js-message_text" dir="auto">'
            '<em>original</em></div></div>'
        ))
        plan = {"post": "codex_push/259", "before_body": {
            "tag": "div", "attrs": {"class": "tgme_widget_message_text"},
            "children": [{"tag": "i", "children": ["original"]}],
        }}
        self.assertIsNone(verify_snapshot(session, plan))

    def test_same_link_label_with_changed_target_is_rejected(self):
        session = Mock()
        session.get.return_value = Mock(text=(
            '<div data-post="codex_push/259"><div class="tgme_widget_message_text">'
            '<a href="https://new.test">original</a></div></div>'
        ))
        plan = {"post": "codex_push/259", "before_body": {"children": [{
            "tag": "a", "attrs": {"href": "https://old.test"}, "children": ["original"],
        }]}}
        self.assertIn("changed", verify_snapshot(session, plan))

    def test_unchanged_message_can_be_edited(self):
        result, session = self.run_repair('<div data-post="codex_push/259"><div class="tgme_widget_message_text"><b>original</b></div></div>')
        self.assertTrue(result["ok"])
        self.assertEqual(session.post.call_count, 2)
        self.assertTrue(session.post.call_args.args[0].endswith('/editMessageText'))

    def test_retry_rechecks_message_after_rate_limit(self):
        session = Mock()
        session.post.side_effect = [
            Mock(json=lambda: {"ok": True, "result": {"username": "codex_push"}}),
            Mock(json=lambda: {"ok": False, "parameters": {"retry_after": 1}}),
        ]
        plan = {"channel": "codex_push", "post": "codex_push/259", "id": 259,
                "before": "original", "after": "repaired", "sha256": "test"}
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.repair_channel_history.requests.Session", return_value=session
        ), patch("scripts.repair_channel_history.wait_for_edit_slot"), patch(
            "scripts.repair_channel_history.time.sleep"
        ), patch("scripts.repair_channel_history.verify_snapshot", side_effect=[None, "Message changed"]) as verify:
            result = apply_channel([plan], {"CODEX_BOT_TOKEN": "dummy"}, Path(directory))
        self.assertFalse(result[0]["ok"])
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(session.post.call_count, 2)  # No second edit after conflict.

    def test_nested_code_and_links_survive_snapshot(self):
        messages = parse_channel('''<div data-post="codex_push/246"><div class="tgme_widget_message_text js-message_text"><b>OpenAI Codex 0.147.0 Released</b><br><code>codex-package-&lt;target&gt;</code> <a href="https://example.test">source</a></div><time datetime="2026-09-01"></time></div>''')
        self.assertEqual(messages[0]["id"], 246)
        self.assertIn("`codex-package-<target>`", messages[0]["markdown"])
        self.assertEqual(messages[0]["links"], ["https://example.test"])

    def test_original_post_id_and_existing_article_link_are_preserved(self):
        message = {"post": "claude_code_push/500", "id": 500,
                   "text": "Claude Code 2.1.50 Released\nNotes", "links": ["https://telegra.ph/old"],
                   "body": {"tag": "div", "children": ["Notes"]},
                   "markdown": "**Claude Code 2.1.50 Released**\n\n[Details](https://telegra.ph/old)"}
        plan = prepare(message, "claude_code_push")
        self.assertEqual(plan["id"], 500)
        self.assertEqual(plan["before_body"], message["body"])
        self.assertIn("https://telegra.ph/old", plan["after"])
        self.assertIn("CHANGELOG.md#2150", plan["after"])

    def test_channel_created_service_message_is_never_edited(self):
        self.assertIsNone(prepare({"text": "Channel created"}, "codex_push"))


if __name__ == "__main__":
    unittest.main()
