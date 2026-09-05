import unittest
from unittest.mock import patch

from core.notify.telegram import (
    _build_bilingual_messages,
    clean_for_telegram,
    process_message_for_markdown_v2,
    send_bilingual_notification,
)


class TelegramFormattingTests(unittest.TestCase):
    def test_fenced_code_survives_cleaning_and_markdown_v2(self):
        source = """## Updating

```bash
uv tool install -U hermes-agent
# or fresh install
```"""

        processed = process_message_for_markdown_v2(clean_for_telegram(source))

        self.assertIn("```bash\n", processed)
        self.assertIn("-U hermes-agent", processed)
        self.assertIn("# or fresh install", processed)

    def test_headings_and_blockquotes_remain_structural(self):
        source = "## Highlights\n\n> Important release"

        processed = process_message_for_markdown_v2(clean_for_telegram(source))

        self.assertIn("*Highlights*", processed)
        self.assertIn("\n>Important release", processed)
        self.assertNotIn("\\> Important", processed)

    def test_bilingual_message_has_labels_without_duplicate_release_heading(self):
        messages = _build_bilingual_messages(
            version="v0.21.0 (v2026.8.31)",
            original="## Highlights\n\n- Bot Mode.",
            translated="## 亮点\n\n- Bot 模式。",
            title="Hermes Agent",
            version_url="https://example.test/release",
            show_language_labels=True,
        )

        combined = messages["combined_message"]
        self.assertEqual(combined.count("Hermes Agent"), 1)
        self.assertIn("*English*", combined)
        self.assertIn("*中文*", combined)
        self.assertNotIn("---", combined)

    @patch("core.translate.llm.summarize_changelog", return_value="")
    @patch("core.notify.telegraph.publish_changelog")
    @patch("core.notify.telegram.send_telegram_message")
    def test_highlights_link_does_not_claim_to_be_full_changelog(
        self, mock_send, mock_publish, _mock_summary
    ):
        mock_publish.return_value = {
            "success": True,
            "url": "https://telegra.ph/highlights",
            "cn_url": None,
        }
        mock_send.return_value = {"success": True, "message_id": 1}

        send_bilingual_notification(
            version="v0.21.0",
            original="x" * 5000,
            translated="中文" * 100,
            title="Hermes Agent",
            version_url="https://github.com/example/release",
            content_kind="highlights",
        )

        message = mock_send.call_args.args[0]
        self.assertIn("View bilingual highlights", message)
        self.assertIn("[GitHub](https://github.com/example/release)", message)
        self.assertNotIn("Full Changelog", message)

    @patch("core.translate.llm.summarize_changelog", return_value="")
    @patch("core.notify.telegraph.publish_changelog")
    @patch("core.notify.telegram.send_telegram_message")
    def test_split_telegraph_release_notes_are_not_labeled_as_highlights(
        self, mock_send, mock_publish, _mock_summary
    ):
        mock_publish.return_value = {
            "success": True,
            "url": "https://telegra.ph/notes-en",
            "cn_url": "https://telegra.ph/notes-cn",
        }
        mock_send.return_value = {"success": True, "message_id": 1}

        send_bilingual_notification(
            version="v0.19.1",
            original="x" * 5000,
            translated="中文" * 100,
            title="Hermes Agent",
            content_kind="notes",
        )

        message = mock_send.call_args.args[0]
        self.assertIn("English notes", message)
        self.assertIn("中文说明", message)
        self.assertNotIn("highlights", message.lower())
        self.assertNotIn("高光", message)


if __name__ == "__main__":
    unittest.main()
