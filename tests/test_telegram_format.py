import unittest
from unittest.mock import patch

from core.notify.telegram import (
    _build_bilingual_messages,
    clean_for_telegram,
    process_message_for_markdown_v2,
    send_bilingual_notification,
)


class TelegramFormattingTests(unittest.TestCase):
    def test_bold_and_heading_filenames_remain_standalone_code(self):
        for source in ("**CLAUDE.md**", "## CLAUDE.md", "**AGENTS.md**"):
            with self.subTest(source=source):
                filename = "AGENTS.md" if "AGENTS.md" in source else "CLAUDE.md"
                self.assertEqual(
                    process_message_for_markdown_v2(clean_for_telegram(source)),
                    f"`{filename}`",
                )

    def test_bold_splits_around_multiple_literal_code_entities(self):
        source = '**Use `foo_bar` and `codex-package-<target>` now**'
        self.assertEqual(
            process_message_for_markdown_v2(source),
            '*Use* `foo_bar` *and* `codex-package-<target>` *now*',
        )
        self.assertEqual(process_message_for_markdown_v2('**`a` `b`**'), '`a` `b`')

    def test_bold_code_split_preserves_links_and_ordinary_bold(self):
        source = '**Read [docs](https://example.com) and `a`**; **ordinary bold**'
        self.assertEqual(
            process_message_for_markdown_v2(source),
            '*Read [docs](https://example.com) and* `a`; *ordinary bold*',
        )
        self.assertEqual(
            process_message_for_markdown_v2('**See [`foo_bar`](https://example.com)**'),
            '*See [foo\\_bar](https://example.com)*',
        )

    def test_crlf_fence_preserves_shell_commands(self):
        source = '### Update\r\n```bash\r\n# keep comment\r\ncodex --version\r\n```'
        for text in (source, clean_for_telegram(source)):
            rendered = process_message_for_markdown_v2(text)
            self.assertIn('```bash\n# keep comment\ncodex --version\n```', rendered)

    def test_bold_inside_heading_has_no_star_fragments(self):
        rendered = process_message_for_markdown_v2(
            clean_for_telegram('### **Breaking change:** update configuration')
        )
        self.assertEqual(rendered, '*Breaking change: update configuration*')

    def test_literal_markdown_link_inside_code_does_not_leak_placeholder(self):
        result = process_message_for_markdown_v2("Use `[label](https://example.com)` syntax.")
        self.assertIn("`[label](https://example.com)`", result)
        self.assertNotIn("TGLINK", result)

    def test_chinese_section_labels_are_consistent_without_changing_prose(self):
        result = _build_bilingual_messages("1.2.3", "## Bug Fixes\n- Fixed.",
            "## Bug Fixes\n- 使用 Bug Fixes 字样。", "Example")["combined_message"]
        self.assertIn("*问题修复*", result)
        self.assertIn("使用 Bug Fixes 字样", result)

    def test_code_label_in_link_remains_a_link_without_nested_code(self):
        result = process_message_for_markdown_v2("[`AGENTS.md`](https://example.com)")
        self.assertEqual(result, "[AGENTS\\.md](https://example.com)")

    def test_short_release_has_source_without_language_labels_or_repeated_version(self):
        result = _build_bilingual_messages(
            "2.1.273", "## 2.1.273\n\n- Use CLAUDE.md.",
            "## 2.1.273\n\n- 使用 CLAUDE.md。", "Claude Code",
        )["combined_message"]
        self.assertEqual(result.count("2.1.273"), 1)
        self.assertIn("CHANGELOG.md#21273", result)
        self.assertNotIn("*English*", result)
        self.assertNotIn("*中文*", result)
        self.assertEqual(result.count("`CLAUDE.md`"), 2)

    def test_filename_protection_keeps_explicit_links_and_code(self):
        source = "`CLAUDE.md` [AGENTS.md](https://example.test/AGENTS.md) AGENTS.md"
        self.assertEqual(clean_for_telegram(source), source[:-9] + "`AGENTS.md`")

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
