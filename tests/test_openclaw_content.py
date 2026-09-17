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

        self.assertTrue(
            selected.startswith(
            """## 2026.8.1

### Highlights

- Important release.

#### Control UI

- Nested highlight detail."""),
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
        self.assertIn("Selected release notes", selected)
        self.assertIn("releases/tag/v2026.8.2", selected)

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

    def test_recovery_and_security_actions_outside_highlights_are_retained(self):
        selected = select_notification_content("""## 2026.9.4
### Highlights
- New interface.
### Fixes
- Routine display fix.
- Security: prevent attachment file disclosure.
- Users with damaged state must run `openclaw doctor` before upgrading.
### Migration
Back up your database first.

```sh
openclaw doctor --repair
```
""")
        self.assertIn("prevent attachment file disclosure", selected)
        self.assertIn("must run `openclaw doctor`", selected)
        self.assertIn("Back up your database first", selected)
        self.assertIn("```sh\nopenclaw doctor --repair\n```", selected)
        self.assertIn("New interface", selected)
        self.assertNotIn("Routine display fix", selected)

    def test_action_after_large_highlights_is_prioritized_before_truncation(self):
        selected = select_notification_content(
            "## 2026.9.4\n### Highlights\n" + "- Routine feature.\n" * 1000
            + "### Migration\nUsers must run `openclaw doctor` before upgrading."
        )
        self.assertLessEqual(len(selected), 8000)
        self.assertIn("Users must run `openclaw doctor`", selected)
        self.assertIn("releases/tag/v2026.9.4", selected)

    def test_fixes_only_patch_does_not_become_an_empty_announcement(self):
        selected = select_notification_content("## 2026.7.1-2\n\n### Fixes\n\n- Accept npm singleton-array metadata.")
        self.assertIn("Accept npm singleton-array metadata", selected)

    def test_action_keeps_adjacent_commands_outside_named_action_sections(self):
        for command in ("```sh\nopenclaw sessions rebuild\n```", "    openclaw sessions rebuild"):
            with self.subTest(command=command):
                selected = select_notification_content(
                    "## 2026.9.4\n### Highlights\n- New UI.\n### Fixes\n"
                    "Users must run this repair command before upgrading:\n\n" + command
                )
                self.assertIn("Users must run", selected)
                self.assertIn(command, selected)

    def test_truncation_does_not_leave_instruction_without_its_commands(self):
        selected = select_notification_content(
            "## 2026.9.4\n### Highlights\n- New UI.\n### Fixes\n"
            "Users must run this repair command before upgrading:\n\n"
            "```sh\n" + "openclaw sessions rebuild\n" * 400 + "```\n"
        )
        self.assertLessEqual(len(selected), 8000)
        self.assertNotIn("Users must run", selected)
        self.assertNotIn("```", selected)
        self.assertIn("Complete official release notes", selected)

    def test_truncation_keeps_a_short_action_with_multiple_commands(self):
        selected = select_notification_content(
            "## 2026.9.4\n### Highlights\n" + "- New UI.\n" * 2000
            + "### Fixes\nUsers must run both commands:\n\n"
            "```sh\nopenclaw doctor\n```\n\n```sh\nopenclaw sessions rebuild\n```\n"
        )
        self.assertLessEqual(len(selected), 8000)
        self.assertIn("Users must run both commands", selected)
        self.assertIn("```sh\nopenclaw doctor\n```", selected)
        self.assertIn("```sh\nopenclaw sessions rebuild\n```", selected)

    def test_recovery_scope_and_nested_heading_stay_with_commands(self):
        selected = select_notification_content(
            "## 2026.9.4\n### Highlights\n- New UI.\n"
            "### Recovery for Windows users only\n\n"
            "#### Existing installations\n\nUsers must run:\n\n"
            "```sh\nopenclaw sessions rebuild\n```\n"
            "### Fixes\n- Routine fix.\n"
        )
        self.assertIn(
            "### Recovery for Windows users only\n\n#### Existing installations\n\n"
            "Users must run:\n\n```sh\nopenclaw sessions rebuild\n```", selected
        )
        self.assertNotIn("Routine fix", selected)

    def test_truncation_omits_scope_and_instruction_with_oversized_command(self):
        selected = select_notification_content(
            "## 2026.9.4\n### Highlights\n- New UI.\n"
            "### Recovery for Windows users only\n\nUsers must run:\n\n"
            "```sh\n" + "openclaw sessions rebuild\n" * 400 + "```\n"
        )
        self.assertLessEqual(len(selected), 8000)
        self.assertNotIn("Windows users only", selected)
        self.assertNotIn("Users must run", selected)
        self.assertNotIn("```", selected)
        self.assertIn("Complete official release notes", selected)


if __name__ == "__main__":
    unittest.main()
