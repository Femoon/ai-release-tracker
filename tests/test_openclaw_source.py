import unittest
from unittest.mock import Mock, patch

from products.openclaw import checker, fetcher, pusher, source


def release(version="2026.9.4", **kwargs):
    return {"tag_name": f"v{version}", "draft": False, "prerelease": False,
            "published_at": "2026-09-04T00:00:00Z", "body": "### Highlights\n- New feature.", **kwargs}


class OpenClawSourceTests(unittest.TestCase):
    def test_rejects_nonpublished_and_prerelease_records(self):
        for item in (release(draft=True), release(prerelease=True), release(published_at=None),
                     release("2026.9.5-beta.1"), release("2026.9.5-rc.1")):
            self.assertIsNone(source.stable_version(item))

    def test_latest_is_gated_on_github_release_not_main_changelog(self):
        with patch.object(source, "_get_json", return_value=release()) as api:
            text = checker.fetch_changelog()
        api.assert_called_once_with(f"{source.API_URL}/latest")
        self.assertEqual(checker.parse_latest_version(text)[0], "2026.9.4")

    def test_publication_stub_fetches_matching_split_notes(self):
        response = Mock(status_code=200, text='<!-- metadata -->\n## 2026.9.4\n### v2026.9.4\n### Highlights\n- Actual change.')
        with patch.object(source, "_get_json", return_value=release(body="<!-- openclaw-release-publication:docs-v1 -->")), patch.object(
            source.requests, "get", return_value=response
        ) as get:
            text = source.fetch_release_changelog()
        get.assert_called_once_with(f"{source.RAW_URL}/CHANGELOG/2026.9.4.md", timeout=30)
        version, body = checker.parse_latest_version(text)
        self.assertEqual(version, "2026.9.4")
        self.assertIn("Actual change", body)
        self.assertEqual(body.count("## 2026.9.4"), 1)
        self.assertNotIn("<!--", body)

    def test_missing_linked_changelog_fails_closed(self):
        with patch.object(source, "_get_json", return_value=release(body="<!-- openclaw-release-publication:docs-v1 -->")), patch.object(
            source.requests, "get", return_value=Mock(status_code=404)
        ):
            self.assertIsNone(source.fetch_release_changelog())

    def test_unreleased_note_is_not_announced(self):
        with patch.object(source, "_get_json", return_value=release(body="## 2026.9.4 (Unreleased)\n- Preview")):
            self.assertIsNone(source.fetch_release_changelog())
        for parse in (checker.parse_latest_version, fetcher.parse_all_versions, pusher.parse_all_versions):
            result = parse("## 2026.9.5 (Unreleased)\n- Preview\n## 2026.9.4\n- Stable")
            self.assertNotIn("2026.9.5", str(result))

    def test_history_paginates_filters_and_sorts_patch_versions(self):
        first = [release("2026.9.5", prerelease=True)] * 98 + [release("2026.9.4-1"), release("2026.9.4")]
        with patch.object(source, "_get_json", side_effect=[first, [release("2026.9.3")]]) as api:
            text = source.fetch_release_changelog(all_versions=True)
        self.assertEqual(api.call_count, 2)
        self.assertEqual([v for v, _ in fetcher.parse_all_versions(text)], ["2026.9.3", "2026.9.4", "2026.9.4-1"])
        self.assertEqual(fetcher.parse_all_versions(text), pusher.parse_all_versions(text))

    def test_explicit_version_still_requires_official_publication(self):
        with patch.object(source, "_get_json", return_value=release("2026.8.2")) as api:
            text = source.fetch_release_changelog("2026.8.2")
        api.assert_called_once_with(f"{source.API_URL}/tags/v2026.8.2")
        self.assertTrue(text.startswith("## 2026.8.2"))

    def test_crlf_release_heading_does_not_hide_the_entire_body(self):
        text = source.release_content(release(body="## 2026.9.4\r\n\r\n### Highlights\r\n- Real change."))
        self.assertIn("Real change", checker.parse_latest_version(text)[1])


if __name__ == "__main__":
    unittest.main()
