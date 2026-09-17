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
    @patch.object(checker, 'verify_release_via_api')
    def test_atom_backport_does_not_hide_higher_stable_version(self, verify):
        verify.side_effect = lambda tag: (release(tag), 'stable')
        result = checker.parse_latest_stable_release(feed('rust-v0.153.1', 'rust-v0.155.0', 'rust-v0.154.0'))
        self.assertEqual(result[0], 'rust-v0.155.0')

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
    def test_sdk_only_feed_uses_releases_api_without_treating_sdk_as_cli(self, get):
        get.return_value = Mock(status_code=200, json=lambda: [])
        self.assertEqual(checker.parse_latest_stable_release(feed('python-v0.154.0')), (None,) * 5)
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], checker.GITHUB_RELEASES_URL)
        get.reset_mock()
        self.assertEqual(checker.resolve_saved_version_to_tag('python-v0.154.0'), ('python-v0.154.0', False, None))
        get.assert_not_called()

    @patch.object(checker.requests, 'get')
    def test_alpha_only_feed_paginates_past_sdk_and_prereleases(self, get):
        page_one = [release(f'rust-v0.155.0-alpha.{i}') for i in range(100)]
        page_two = [release('python-v0.155.0'),
                    {**release('rust-v0.155.0'), 'prerelease': True},
                    {**release('rust-v0.156.0'), 'draft': True},
                    release('rust-v0.153.0'), release('rust-v0.154.0')]
        get.side_effect = [Mock(status_code=200, json=lambda: page_one),
                           Mock(status_code=200, json=lambda: page_two)]
        result = checker.parse_latest_stable_release(feed('rust-v0.155.0-alpha.1'))
        self.assertEqual(result[0], 'rust-v0.154.0')
        self.assertEqual(result[2], 'CLI notes')
        self.assertIsNone(result[-1])
        self.assertEqual([call.kwargs['params']['page'] for call in get.call_args_list], [1, 2])

    @patch.object(checker.requests, 'get')
    def test_fallback_selects_highest_stable_version_across_all_pages(self, get):
        page_one = [release('rust-v0.9.9')] + [release(f'rust-v0.155.0-alpha.{i}') for i in range(99)]
        page_two = [release('rust-v0.10.0')] + [release(f'python-v0.200.{i}') for i in range(99)]
        page_three = [release('rust-v0.11.0'),
                      {**release('rust-v0.999.0'), 'prerelease': True},
                      {**release('rust-v0.998.0'), 'draft': True}]
        get.side_effect = [Mock(status_code=200, json=lambda: page_one),
                           Mock(status_code=200, json=lambda: page_two),
                           Mock(status_code=200, json=lambda: page_three)]
        result = checker.fetch_latest_stable_release_via_api()
        self.assertEqual(result[0], 'rust-v0.11.0')
        self.assertIsNone(result[-1])
        self.assertEqual([call.kwargs['params'] for call in get.call_args_list],
                         [{'per_page': 100, 'page': page} for page in (1, 2, 3)])

    @patch.object(checker.requests, 'get')
    def test_partial_stable_candidate_is_not_returned_after_later_page_failure(self, get):
        page_one = [release('rust-v0.154.0')] * 100
        for later in (Mock(status_code=503),
                      Mock(status_code=200, json=Mock(side_effect=ValueError('bad json'))),
                      checker.requests.ConnectionError('offline')):
            with self.subTest(later=type(later).__name__):
                get.side_effect = [Mock(status_code=200, json=lambda: page_one), later]
                result = checker.fetch_latest_stable_release_via_api()
                self.assertEqual(result[:4], (None,) * 4)
                self.assertTrue(result[-1])

    @patch.object(checker.requests, 'get')
    def test_pagination_limit_rejects_partial_stable_candidate(self, get):
        get.return_value = Mock(status_code=200, json=lambda: [release('rust-v0.154.0')] * 100)
        with patch.object(checker, 'MAX_RELEASE_PAGES', 2):
            result = checker.fetch_latest_stable_release_via_api()
        self.assertEqual(result, (None, None, None, None, 'releases_api: pagination_limit_reached'))
        self.assertEqual(get.call_count, 2)

    @patch.object(checker.requests, 'get')
    def test_final_empty_page_returns_prior_candidate_without_extra_request(self, get):
        get.side_effect = [Mock(status_code=200, json=lambda: [release('rust-v0.154.0')] * 100),
                           Mock(status_code=200, json=lambda: [])]
        result = checker.fetch_latest_stable_release_via_api()
        self.assertEqual(result[0], 'rust-v0.154.0')
        self.assertIsNone(result[-1])
        self.assertEqual(get.call_count, 2)

    @patch.object(checker.requests, 'get')
    def test_fallback_failures_are_errors_not_empty_success(self, get):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                get.return_value = Mock(status_code=status)
                result = checker.parse_latest_stable_release(feed('rust-v0.155.0-alpha.1'))
                self.assertIsNone(result[0])
                self.assertIn(str(status), result[-1])
        get.return_value = Mock(status_code=200, json=lambda: {'message': 'not a release list'})
        self.assertIn('invalid_response', checker.fetch_latest_stable_release_via_api()[-1])
        get.return_value = Mock(status_code=200)
        get.return_value.json.side_effect = ValueError('bad json')
        self.assertIn('json_error', checker.fetch_latest_stable_release_via_api()[-1])
        get.side_effect = checker.requests.ConnectionError('offline')
        self.assertIn('network_error', checker.fetch_latest_stable_release_via_api()[-1])

    @patch.object(checker.requests, 'get')
    def test_second_page_failure_and_pagination_limit_are_not_empty_success(self, get):
        alphas = [release(f'rust-v0.155.0-alpha.{i}') for i in range(100)]
        get.side_effect = [Mock(status_code=200, json=lambda: alphas), Mock(status_code=503)]
        self.assertIn('http_503', checker.fetch_latest_stable_release_via_api()[-1])
        get.side_effect = None
        get.return_value = Mock(status_code=200, json=lambda: alphas)
        with patch.object(checker, 'MAX_RELEASE_PAGES', 1):
            self.assertIn('pagination_limit_reached', checker.fetch_latest_stable_release_via_api()[-1])

    @patch.object(checker, 'fetch_latest_stable_release_via_api')
    @patch.object(checker, 'verify_release_via_api', return_value=(None, 'server_error'))
    def test_candidate_verification_failure_does_not_fall_back_to_older_release(self, verify, fallback):
        result = checker.parse_latest_stable_release(feed('rust-v0.155.0'))
        self.assertIn('api_errors', result[-1])
        fallback.assert_not_called()

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

    def test_non_cli_state_never_causes_automatic_cli_repost(self):
        for saved_tag in ('python-v0.154.0', 'python-v0.153.0', 'js-v0.154.0', 'rust-v0.154.0-alpha.1'):
            with self.subTest(saved_tag=saved_tag), tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
                Path(tmp, 'output').mkdir()
                for name, value in [('PROJECT_ROOT', tmp)]:
                    stack.enter_context(patch.object(checker, name, value))
                stack.enter_context(patch('sys.argv', ['checker.py']))
                stack.enter_context(patch.object(checker, 'fetch_releases_feed', return_value=('feed', None)))
                stack.enter_context(patch.object(checker, 'parse_latest_stable_release', return_value=('rust-v0.154.0', '0.154.0', 'CLI notes', release('rust-v0.154.0')['html_url'], None)))
                stack.enter_context(patch.object(checker, 'read_saved_version', return_value=saved_tag))
                translate = stack.enter_context(patch.object(checker, 'translate_changelog'))
                send = stack.enter_context(patch.object(checker, 'send_bilingual_notification'))
                edit = stack.enter_context(patch.object(checker, 'edit_bilingual_notification'))
                save = stack.enter_context(patch.object(checker, 'save_version', return_value=True))
                state = stack.enter_context(patch.object(checker, 'save_message_state', return_value=True))
                self.assertEqual(checker.main(), 1)
                translate.assert_not_called()
                send.assert_not_called()
                edit.assert_not_called()
                save.assert_not_called()
                state.assert_not_called()

    @patch.object(checker.requests, 'get')
    def test_bare_semver_still_migrates_after_api_confirms_cli_identity(self, get):
        get.side_effect = [Mock(status_code=404),
                           Mock(status_code=200, json=lambda: release('rust-v0.154.0'))]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('sys.argv', ['checker.py']))
            stack.enter_context(patch.object(checker, 'fetch_releases_feed', return_value=('feed', None)))
            stack.enter_context(patch.object(checker, 'parse_latest_stable_release', return_value=(
                'rust-v0.154.0', '0.154.0', 'CLI notes', release('rust-v0.154.0')['html_url'], None)))
            stack.enter_context(patch.object(checker, 'read_saved_version', return_value='0.154.0'))
            stack.enter_context(patch.object(checker, 'read_message_state', return_value=None))
            send = stack.enter_context(patch.object(checker, 'send_bilingual_notification'))
            edit = stack.enter_context(patch.object(checker, 'edit_bilingual_notification'))
            save = stack.enter_context(patch.object(checker, 'save_version', return_value=True))
            self.assertEqual(checker.main(), 0)
            send.assert_not_called()
            edit.assert_not_called()
            save.assert_called_once_with('rust-v0.154.0')

    @patch.object(checker.requests, 'get', side_effect=checker.requests.ConnectionError('offline'))
    def test_unverifiable_legacy_semver_fails_closed_without_notification(self, _get):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('sys.argv', ['checker.py']))
            stack.enter_context(patch.object(checker, 'fetch_releases_feed', return_value=('feed', None)))
            stack.enter_context(patch.object(checker, 'parse_latest_stable_release', return_value=(
                'rust-v0.154.0', '0.154.0', 'CLI notes', release('rust-v0.154.0')['html_url'], None)))
            stack.enter_context(patch.object(checker, 'read_saved_version', return_value='0.154.0'))
            send = stack.enter_context(patch.object(checker, 'send_bilingual_notification'))
            translate = stack.enter_context(patch.object(checker, 'translate_changelog'))
            save = stack.enter_context(patch.object(checker, 'save_version'))
            self.assertEqual(checker.main(), 1)
            send.assert_not_called()
            translate.assert_not_called()
            save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
