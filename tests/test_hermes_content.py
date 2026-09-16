import unittest

from products.hermes.content import select_notification_content


class HermesContentTests(unittest.TestCase):
    def test_recovery_after_contributors_survives_long_highlights(self):
        body = (
            "# Hermes Agent v0.21.2\n\n## ✨ Highlights\n\n"
            + "\n".join(f"- Feature {i}: " + "x" * 900 for i in range(12))
            + "\n\n## Notable Bug Fixes\n- Other fixes.\n\n"
            "## 👥 Contributors\nThanks @someone.\n\n## Updating\n\n"
            "- Existing install: `hermes update`\n"
            "- If your `state.db` was already damaged by 0.21.0/0.21.1: "
            "run `hermes doctor` first; inspect with "
            "`hermes sessions recover --inspect-only`.\n\n"
            "**Full Changelog:** https://github.com/NousResearch/hermes-agent/compare/a...b\n"
        )
        selected = select_notification_content(body)
        self.assertLessEqual(len(selected), 8000)
        self.assertTrue(selected.startswith("## Updating"))
        self.assertIn("If your `state.db` was already damaged by 0.21.0/0.21.1", selected)
        self.assertIn("`hermes doctor` first", selected)
        self.assertIn("`hermes sessions recover --inspect-only`", selected)
        self.assertEqual(selected.count("## Updating"), 1)
        self.assertIn("Highlights truncated", selected)
        self.assertNotIn("@someone", selected)
        self.assertNotIn("Full Changelog", selected)

    def test_patch_migration_is_prioritized_without_dropping_later_fixes(self):
        body = (
            "# Hermes Agent v0.21.3\n\n## Bug Fixes\n- Fixed refresh.\n\n"
            "## Migration notes\n- Back up `state.db` before changing storage.\n\n"
            "## Other changes\n- Faster startup.\n"
        )
        selected = select_notification_content(body)
        self.assertTrue(selected.startswith("## Migration notes"))
        self.assertIn("before changing storage", selected)
        self.assertIn("Fixed refresh", selected)
        self.assertIn("Faster startup", selected)

    def test_inline_citation_cleanup_does_not_leave_empty_parentheses(self):
        body = (
            "- Use published 7.0.0-rc13 "
            "([#123](https://github.com/NousResearch/hermes-agent/pull/123)) "
            "— the bridge now installs from npm.\n"
            "- Keep `open()` and callback() behavior (Windows)."
        )
        selected = select_notification_content(body)
        self.assertIn("7.0.0-rc13", selected)
        self.assertNotIn(" ()", selected)
        self.assertNotIn("pull/123", selected)
        self.assertIn("`open()` and callback() behavior (Windows)", selected)


if __name__ == "__main__":
    unittest.main()
