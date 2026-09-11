import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from products.codex import checker, fetcher, pusher
from products.codex.releases import is_stable_cli_tag, tag_from_release_url


def release(tag, **kwargs):
    return dict(tag_name=tag, name="0.154.0", body="CLI notes", draft=False,
                prerelease=False, html_url=f"https://github.com/openai/codex/releases/tag/{tag}",
                published_at="2026-09-11", **kwargs)


def feed(*tags):
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(
        f'<entry><title>0.154.0</title><link href="https://github.com/openai/codex/releases/tag/{tag}"/></entry>'
        for tag in tags) + '</feed>'


class CodexReleaseFilterTests(unittest.TestCase):
    def test_tag_whitelist(self):
        for tag in ('python-v0.154.0', 'js-v0.154.0', 'rust-v0.154.0-alpha.1',
                    'rust-v0.154.0-beta', 'rust-v0.154.0-rc1', '0.154.0', '', None):
            with self.subTest(tag=tag):
                self.assertFalse(is_stable_cli_tag(tag))
        self.assertTrue(is_stable_cli_tag('rust-v0.154.0'))
        self.assertEqual(tag_from_release_url('https://example.com/rust-v0.154.0'), '')

    @patch.object(checker.requests, 'get')
    def test_mixed_feed_only_requests_cli(self, get):
        get.return_value = Mock(status_code=200, json=lambda: release('rust-v0.154.0'))
        result = checker.parse_latest_stable_release(feed('python-v0.154.0', 'rust-v0.154.0-rc1', 'rust-v0.154.0'))
        self.assertEqual(result[0], 'rust-v0.154.0')
        self.assertIsNone(result[-1])
        get.assert_called_once()
        self.assertTrue(get.call_args.args[0].endswith('/rust-v0.154.0'))

    @patch.object(checker.requests, 'get')
    def test_api_rejects_non_cli_and_unstable_metadata(self, get):
        for data in (release('python-v0.154.0'),
                     {**release('rust-v0.154.0'), 'draft': True},
                     {**release('rust-v0.154.0'), 'prerelease': True}):
            get.return_value = Mock(status_code=200, json=lambda: data)
            self.assertNotEqual(checker.verify_release_via_api('rust-v0.154.0')[1], 'stable')

    @patch.object(checker.requests, 'get')
    def test_sdk_only_feed_has_no_candidate_or_api_request(self, get):
        self.assertEqual(checker.parse_latest_stable_release(feed('python-v0.154.0')), (None,) * 5)
        get.assert_not_called()
        self.assertEqual(checker.resolve_saved_version_to_tag('python-v0.154.0'), ('python-v0.154.0', False, None))
        get.assert_not_called()

    def test_fetcher_uses_tag_not_display_title(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetcher, 'OUTPUT_FILE', str(Path(tmp) / 'releases.txt')), patch.object(
            fetcher, 'fetch_all_releases', return_value=[release('python-v0.154.0'),
                {**release('rust-v0.154.0'), 'name': 'Codex CLI release'},
                {**release('rust-v0.155.0'), 'prerelease': True}]
        ):
            fetcher.main()
            content = Path(tmp, 'releases.txt').read_text()
            self.assertIn('rust-v0.154.0', content)
            self.assertNotIn('python-v', content)
            self.assertNotIn('rust-v0.155.0', content)

    def test_old_sdk_file_never_translates_sends_or_marks_pushed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'releases.txt')
            path.write_text('## [0.154.0](https://github.com/openai/codex/releases/tag/python-v0.154.0)\n\nSDK notes\n')
            with patch.object(pusher, 'RELEASES_FILE', str(path)), patch.object(pusher, 'read_pushed_versions', return_value=set()), patch.object(pusher, 'translate_changelog') as translate, patch.object(pusher, 'send_bilingual_notification') as send, patch.object(pusher, 'append_pushed_version') as save:
                pusher.main(push_all=True)
                translate.assert_not_called()
                send.assert_not_called()
                save.assert_not_called()

    def test_python_state_is_replaced_only_after_successful_cli_notification(self):
        for success in (False, True):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
                Path(tmp, 'output').mkdir()
                for name, value in [('PROJECT_ROOT', tmp)]:
                    stack.enter_context(patch.object(checker, name, value))
                stack.enter_context(patch('sys.argv', ['checker.py']))
                stack.enter_context(patch.object(checker, 'fetch_releases_feed', return_value=('feed', None)))
                stack.enter_context(patch.object(checker, 'parse_latest_stable_release', return_value=('rust-v0.154.0', '0.154.0', 'CLI notes', release('rust-v0.154.0')['html_url'], None)))
                stack.enter_context(patch.object(checker, 'read_saved_version', return_value='python-v0.154.0'))
                stack.enter_context(patch.object(checker, 'translate_changelog', return_value='CLI 更新'))
                stack.enter_context(patch.object(checker, 'send_bilingual_notification', return_value={'success': success, 'message_ids': [261] if success else []}))
                edit = stack.enter_context(patch.object(checker, 'edit_bilingual_notification'))
                save = stack.enter_context(patch.object(checker, 'save_version', return_value=True))
                state = stack.enter_context(patch.object(checker, 'save_message_state', return_value=True))
                self.assertEqual(checker.main(), 0 if success else 1)
                edit.assert_not_called()
                if success:
                    save.assert_called_once_with('rust-v0.154.0')
                    self.assertEqual(state.call_args.args[0], 'rust-v0.154.0')
                else:
                    save.assert_not_called()
                    state.assert_not_called()


if __name__ == '__main__':
    unittest.main()
