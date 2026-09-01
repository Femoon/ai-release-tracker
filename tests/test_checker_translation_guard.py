"""翻译失败守卫：版本状态必须在翻译成功之后才推进。"""

import sys
import unittest
from unittest.mock import patch

from products.claude_code import checker as claude_code_checker
from products.openclaw import checker as openclaw_checker


CHANGELOG = "## 2.1.251\n\n- Added Agent support.\n"
OPENCLAW_CHANGELOG = "## 2026.3.12\n\n- Added Agent support.\n"
OPENCLAW_CHANGELOG_WITH_FIXES = """## 2026.8.1

### Highlights

- Added Agent support.

### Changes

- Improved sessions.

### Fixes

- Fixed retries.

### Complete contribution record

- PR #123.
"""


class TranslationGuardTests(unittest.TestCase):
    def _run(self, checker, changelog, argv):
        with patch.object(checker, "fetch_changelog", return_value=changelog), patch.object(
            checker, "translate_changelog", return_value=""
        ), patch.object(checker, "save_version") as mock_save_version, patch.object(
            checker, "send_bilingual_notification"
        ) as mock_notify, patch.object(
            checker, "read_saved_version", return_value="0.0.1"
        ), patch.object(
            sys, "argv", argv
        ):
            result = checker.main()
        return result, mock_save_version, mock_notify

    def test_claude_code_new_version_stops_before_saving_version(self):
        result, mock_save_version, mock_notify = self._run(
            claude_code_checker, CHANGELOG, ["checker.py"]
        )

        self.assertEqual(result, 1)
        mock_save_version.assert_not_called()
        mock_notify.assert_not_called()

    def test_claude_code_force_stops_before_notifying(self):
        result, _mock_save_version, mock_notify = self._run(
            claude_code_checker, CHANGELOG, ["checker.py", "--force"]
        )

        self.assertEqual(result, 1)
        mock_notify.assert_not_called()

    def test_openclaw_new_version_stops_before_saving_version(self):
        result, mock_save_version, mock_notify = self._run(
            openclaw_checker, OPENCLAW_CHANGELOG, ["checker.py"]
        )

        self.assertEqual(result, 1)
        mock_save_version.assert_not_called()
        mock_notify.assert_not_called()

    def test_openclaw_force_stops_before_notifying(self):
        result, _mock_save_version, mock_notify = self._run(
            openclaw_checker, OPENCLAW_CHANGELOG, ["checker.py", "--force"]
        )

        self.assertEqual(result, 1)
        mock_notify.assert_not_called()

    def test_openclaw_displays_only_highlights_when_present(self):
        translated = "## 2026.8.1\n\n### 亮点\n\n- 新增 Agent 支持。"
        with patch.object(
            openclaw_checker,
            "fetch_changelog",
            return_value=OPENCLAW_CHANGELOG_WITH_FIXES,
        ), patch.object(
            openclaw_checker, "translate_changelog", return_value=translated
        ) as mock_translate, patch.object(
            openclaw_checker, "save_version", return_value=True
        ), patch.object(
            openclaw_checker,
            "send_bilingual_notification",
            return_value={"success": True, "message_ids": [1]},
        ) as mock_notify, patch.object(
            openclaw_checker, "save_message_state", return_value=True
        ), patch.object(
            openclaw_checker, "read_saved_version", return_value="2026.7.1"
        ), patch.object(
            sys, "argv", ["checker.py"]
        ):
            result = openclaw_checker.main()

        self.assertEqual(result, 0)
        translation_input = mock_translate.call_args.args[0]
        self.assertIn("### Highlights", translation_input)
        self.assertNotIn("### Changes", translation_input)
        self.assertNotIn("### Fixes", translation_input)
        self.assertNotIn("Complete contribution record", translation_input)
        self.assertEqual(
            mock_notify.call_args.kwargs["original"],
            translation_input,
        )
        self.assertEqual(mock_notify.call_args.kwargs["translated"], translated)

    def test_claude_code_saves_version_after_successful_translation(self):
        with patch.object(
            claude_code_checker, "fetch_changelog", return_value=CHANGELOG
        ), patch.object(
            claude_code_checker, "translate_changelog", return_value="- 新增 Agent 支持。"
        ), patch.object(
            claude_code_checker, "save_version", return_value=True
        ) as mock_save_version, patch.object(
            claude_code_checker,
            "send_bilingual_notification",
            return_value={"success": True, "message_ids": [1]},
        ) as mock_notify, patch.object(
            claude_code_checker, "save_message_state", return_value=True
        ), patch.object(
            claude_code_checker, "read_saved_version", return_value="0.0.1"
        ), patch.object(
            sys, "argv", ["checker.py"]
        ):
            result = claude_code_checker.main()

        self.assertEqual(result, 0)
        mock_save_version.assert_called_once_with("2.1.251")
        mock_notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
