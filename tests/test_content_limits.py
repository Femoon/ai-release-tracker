import unittest

from core.utils.content import limit_notification_content


class ContentLimitTests(unittest.TestCase):
    def test_short_content_is_unchanged(self):
        content = "## Notes\n\n- Use `../config`.\n"
        self.assertEqual(limit_notification_content(content), content)

    def test_does_not_split_multiline_list_item(self):
        first = "- Keep this item.\n"
        second = "- A longer item\n\n  " + "continuation " * 100
        result = limit_notification_content(first + second, limit=180)
        self.assertIn(first.strip(), result)
        self.assertNotIn("A longer item", result)
        self.assertLessEqual(len(result), 180)

    def test_nested_list_is_not_cut(self):
        content = "- Keep.\n- Parent\n  - " + "child " * 100
        result = limit_notification_content(content, limit=160)
        self.assertIn("- Keep.", result)
        self.assertNotIn("Parent", result)

    def test_fenced_and_indented_code_are_atomic(self):
        for block in ("```sh\n" + "echo test\n" * 50 + "```", "    echo test\n" * 50):
            result = limit_notification_content("## Notes\n\n" + block, limit=180)
            self.assertIn("## Notes", result)
            self.assertNotIn("echo", result)
            self.assertNotIn("```", result)

    def test_source_link_and_notice_fit_with_large_first_block(self):
        result = limit_notification_content("x" * 12000, "https://example.invalid/release")
        self.assertIn("https://example.invalid/release", result)
        self.assertIn("shortened", result)
        self.assertLessEqual(len(result), 8000)
