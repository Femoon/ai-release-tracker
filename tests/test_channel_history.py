import unittest

from scripts.audit_channel_history import parse_channel
from scripts.repair_channel_history import prepare


class HistoryRepairTests(unittest.TestCase):
    def test_nested_code_and_links_survive_snapshot(self):
        messages = parse_channel('''<div data-post="codex_push/246"><div class="tgme_widget_message_text js-message_text"><b>OpenAI Codex 0.147.0 Released</b><br><code>codex-package-&lt;target&gt;</code> <a href="https://example.test">source</a></div><time datetime="2026-09-01"></time></div>''')
        self.assertEqual(messages[0]["id"], 246)
        self.assertIn("`codex-package-<target>`", messages[0]["markdown"])
        self.assertEqual(messages[0]["links"], ["https://example.test"])

    def test_original_post_id_and_existing_article_link_are_preserved(self):
        message = {"post": "claude_code_push/500", "id": 500,
                   "text": "Claude Code 2.1.50 Released\nNotes", "links": ["https://telegra.ph/old"],
                   "markdown": "**Claude Code 2.1.50 Released**\n\n[Details](https://telegra.ph/old)"}
        plan = prepare(message, "claude_code_push")
        self.assertEqual(plan["id"], 500)
        self.assertIn("https://telegra.ph/old", plan["after"])
        self.assertIn("CHANGELOG.md#2150", plan["after"])

    def test_channel_created_service_message_is_never_edited(self):
        self.assertIsNone(prepare({"text": "Channel created"}, "codex_push"))


if __name__ == "__main__":
    unittest.main()
