import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from products.codex import checker


class CodexCheckerTests(unittest.TestCase):
    def test_compare_only_release_survives_cleaning_and_notification_selection(self):
        raw = "## Changelog\n\n**Full Changelog**: https://github.com/openai/codex/compare/rust-v0.151.0...rust-v0.152.0"
        content = checker._notification_content(checker.clean_release_body(raw))
        self.assertIn('https://github.com/openai/codex/compare/rust-v0.151.0...rust-v0.152.0', content)
        self.assertTrue(content.strip())

    def test_changelog_catalog_is_still_removed_after_meaningful_notes(self):
        raw = "## Fixes\n- Fixed startup.\n\n## Changelog\n- Internal commit detail."
        content = checker._notification_content(raw)
        self.assertIn('Fixed startup', content)
        self.assertNotIn('Internal commit', content)

    def test_older_remote_candidate_never_translates_sends_or_advances_state(self):
        with patch.object(sys, 'argv', ['checker.py']), \
                patch.object(checker, 'fetch_releases_feed', return_value=('feed', None)), \
                patch.object(checker, 'parse_latest_stable_release', return_value=(
                    'rust-v0.153.0', '0.153.0', 'Older notes', 'https://github.com/openai/codex/releases/tag/rust-v0.153.0', None)), \
                patch.object(checker, 'read_saved_version', return_value='rust-v0.154.0'), \
                patch.object(checker, 'translate_changelog') as translate, \
                patch.object(checker, 'send_bilingual_notification') as send, \
                patch.object(checker, 'edit_bilingual_notification') as edit, \
                patch.object(checker, 'save_version') as save:
            self.assertEqual(checker.main(), 0)
            translate.assert_not_called()
            send.assert_not_called()
            edit.assert_not_called()
            save.assert_not_called()

    @patch.object(checker, "send_bilingual_notification")
    @patch.object(checker, "save_version")
    @patch.object(checker, "translate_changelog", return_value="")
    @patch.object(checker, "_strip_changelog_section", side_effect=lambda text: text)
    @patch.object(
        checker,
        "resolve_saved_version_to_tag",
        return_value=("rust-v0.148.0", False, None),
    )
    @patch.object(checker, "read_saved_version", return_value="rust-v0.148.0")
    @patch.object(
        checker,
        "parse_latest_stable_release",
        return_value=(
            "rust-v0.149.0",
            "0.149.0",
            "**New Features**\n\n- Agent works.",
            "https://example.invalid/release",
            None,
        ),
    )
    @patch.object(checker, "fetch_releases_feed", return_value=("feed", None))
    def test_new_release_translation_failure_does_not_advance_or_notify(
        self,
        _mock_feed,
        _mock_parse,
        _mock_saved,
        _mock_resolve,
        _mock_strip,
        _mock_translate,
        mock_save_version,
        mock_notify,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "output").mkdir()
            with patch.object(checker, "PROJECT_ROOT", temp_dir), patch.object(
                sys, "argv", ["checker.py"]
            ):
                result = checker.main()

        self.assertEqual(result, 1)
        mock_save_version.assert_not_called()
        mock_notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
