import unittest

from products.openclaw.content import select_notification_content


class OpenClawContentTests(unittest.TestCase):
    def test_selects_version_and_highlights_only(self):
        content = """## 2026.8.1

### Highlights

- Important release.

#### Control UI

- Nested highlight detail.

### Changes

- Routine change.

### Fixes

- Routine fix.
"""

        selected = select_notification_content(content)

        self.assertEqual(
            selected,
            """## 2026.8.1

### Highlights

- Important release.

#### Control UI

- Nested highlight detail.""",
        )

    def test_without_highlights_omits_fixes_and_later_sections(self):
        content = """## 2026.8.2

### Changes

- Important change.

### Fixes

- Routine fix.

### Complete contribution record

- PR #123.
"""

        selected = select_notification_content(content)

        self.assertIn("### Changes", selected)
        self.assertNotIn("### Fixes", selected)
        self.assertNotIn("Complete contribution record", selected)
        self.assertIn("Fixes section omitted due to length limit", selected)

    def test_highlights_match_is_case_insensitive(self):
        content = "## 2026.8.3\n\n### HIGHLIGHTS\n\n- Important.\n\n### Changes\n\n- Later."

        selected = select_notification_content(content)

        self.assertIn("### HIGHLIGHTS", selected)
        self.assertNotIn("### Changes", selected)

    def test_removes_issue_references_and_contributor_credits(self):
        content = """## 2026.8.1

### Highlights

- **Find conversations:** search past conversations. (#105057, #105635) Thanks @hercial61.
- **Use dashboards:** pin widgets. (#101840) Thanks @one, @two, and @three.
- **Keep mentions:** notify @owner when work finishes.
"""

        selected = select_notification_content(content)

        self.assertIn("- **Find conversations:** search past conversations.", selected)
        self.assertIn("- **Use dashboards:** pin widgets.", selected)
        self.assertIn("notify @owner when work finishes", selected)
        self.assertNotIn("#105057", selected)
        self.assertNotIn("#101840", selected)
        self.assertNotIn("Thanks @", selected)


if __name__ == "__main__":
    unittest.main()
