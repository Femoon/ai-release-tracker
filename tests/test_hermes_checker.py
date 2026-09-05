import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from products.hermes import checker


def release(tag, semver, published_at, body="- Improved Hermes."):
    return {
        "tag": tag,
        "name": f"Hermes Agent v{semver} ({tag})",
        "body": body,
        "url": f"https://github.com/NousResearch/hermes-agent/releases/tag/{tag}",
        "published_at": published_at,
        "updated_at": published_at,
    }


class HermesCheckerTests(unittest.TestCase):
    def test_pending_releases_are_returned_oldest_first(self):
        releases = [
            release("v2026.8.31", "0.21.0", "2026-08-31T19:29:49Z"),
            release("v2026.8.27", "0.20.6", "2026-08-27T12:06:53Z"),
            release("v2026.8.19", "0.20.5", "2026-08-21T12:16:39Z"),
        ]

        pending = checker.pending_releases(releases, "v2026.8.19")

        self.assertEqual([item["tag"] for item in pending], ["v2026.8.27", "v2026.8.31"])

    def test_missing_saved_tag_does_not_replay_older_releases(self):
        releases = [
            release("v2026.8.31", "0.21.0", "2026-08-31T19:29:49Z"),
            release("v2026.8.19", "0.20.5", "2026-08-21T12:16:39Z"),
        ]

        pending = checker.pending_releases(releases, "v2026.8.27")

        self.assertEqual([item["tag"] for item in pending], ["v2026.8.31"])

    def test_atom_fallback_filters_conventional_prereleases(self):
        feed = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Hermes Agent beta</title><link href="https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.1-beta"/><updated>2026-09-01T00:00:00Z</updated><content>beta</content></entry>
          <entry><title>Hermes Agent v0.21.0</title><link href="https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.31"/><updated>2026-08-31T00:00:00Z</updated><content>stable</content></entry>
        </feed>"""

        releases = checker.parse_atom_releases(feed)

        self.assertEqual([item["tag"] for item in releases], ["v2026.8.31"])

    def test_notification_content_keeps_preamble_and_highlights_only(self):
        item = release("v2026.8.31", "0.21.0", "2026-08-31T19:29:49Z")
        item["body"] = """# Hermes Agent v0.21.0

The Pantheon Release.

## ✨ Highlights

- Bot Mode. ([#123](https://github.com/NousResearch/hermes-agent/pull/123), [#456](https://github.com/NousResearch/hermes-agent/pull/456) — @contributor)
- Cron memory.

## Core Agent

- Detailed change.
"""

        content = checker._notification_content(item)

        self.assertNotIn("# Hermes Agent", content)
        self.assertIn("The Pantheon Release", content)
        self.assertIn("Bot Mode", content)
        self.assertNotIn("Core Agent", content)
        self.assertNotIn("Detailed change", content)
        self.assertNotIn("pull/123", content)
        self.assertNotIn("@contributor", content)

    def test_notification_content_keeps_short_patch_without_highlights(self):
        item = release("v2026.5.29.2", "0.15.2", "2026-05-29T13:37:26Z")
        item["body"] = """# Hermes Agent v0.15.2

## 🐛 Bug Fixes

- Fixed Windows setup. (#123)

## 👥 Contributors

Thanks @contributor.
"""

        content = checker._notification_content(item)

        self.assertIn("Fixed Windows setup", content)
        self.assertNotIn("#123", content)
        self.assertNotIn("@contributor", content)

    def test_oversized_highlights_are_truncated_at_complete_bullet(self):
        item = release("v2026.5.16", "0.14.0", "2026-05-16T00:00:00Z")
        item["body"] = "# Hermes\n\n## ✨ Highlights\n" + "\n".join(
            f"- Item {index}: " + ("x" * 900) for index in range(12)
        ) + "\n\n## Details\n- hidden"

        content = checker._notification_content(item)

        self.assertLessEqual(len(content), 8200)
        self.assertIn("Highlights truncated", content)
        self.assertIn("Item 6", content)
        self.assertNotIn("Item 11", content)
        self.assertFalse(content.rstrip().endswith("x" * 100))

    def test_empty_highlights_falls_back_to_bug_fixes(self):
        item = release("v2026.4.16", "0.10.0", "2026-04-16T00:00:00Z")
        item["body"] = """# Hermes Agent v0.10.0

**Release Date:** April 16, 2026

## ✨ Highlights

## 🐛 Bug Fixes & Improvements

- Fixed gateway delivery.
"""

        content = checker._notification_content(item)

        self.assertIn("Fixed gateway delivery", content)
        self.assertNotIn("Release Date", content)
        self.assertNotIn("Hermes Agent v0.10.0", content)

    def test_hermes_cleanup_removes_reference_residue_without_touching_at_words(self):
        item = release("v2026.5.29", "0.15.1", "2026-05-29T00:00:00Z")
        item["body"] = """# Hermes Agent v0.15.1

## Bug Fixes

- Mention another session with @context. Closes [](https://github.com/NousResearch/hermes-agent/issues/42). ([](https://github.com/NousResearch/hermes-agent/pull/43) — @author)
- Added a plugin. (salvage of [](https://github.com/NousResearch/hermes-agent/pull/44))
"""

        content = checker._notification_content(item)

        self.assertIn("@context", content)
        self.assertNotIn("[](", content)
        self.assertNotIn("Closes", content)
        self.assertNotIn("salvage", content.lower())
        self.assertNotIn("@author", content)

    def test_cleanup_preserves_feature_parentheses_before_trailing_pr_citation(self):
        item = release("v2026.4.16", "0.10.0", "2026-04-16T00:00:00Z")
        item["body"] = """# Hermes Agent v0.10.0

## Highlights

- Access to web search (Firecrawl), image generation, TTS, and browser automation ([#123](https://github.com/NousResearch/hermes-agent/pull/123) - @author)
"""

        content = checker._notification_content(item)

        self.assertIn(
            "Access to web search (Firecrawl), image generation, TTS, and browser automation",
            content,
        )
        self.assertNotIn("pull/123", content)
        self.assertNotIn("@author", content)

    def test_empty_highlights_heading_is_removed_on_fallback(self):
        item = release("v2026.4.16", "0.10.0", "2026-04-16T00:00:00Z")
        item["body"] = """# Hermes Agent v0.10.0

## Highlights

## Bug Fixes

- Fixed gateway delivery.
"""

        content = checker._notification_content(item)

        self.assertNotIn("Highlights", content)
        self.assertIn("## Bug Fixes", content)

    def test_patch_keeps_fenced_code_but_drops_updating_section(self):
        item = release("v2026.7.30", "0.19.1", "2026-07-30T00:00:00Z")
        item["body"] = """# Hermes Agent v0.19.1

## Bug Fixes

```bash
uv tool install -U hermes-agent
# or fresh install
```

## Updating
- Duplicate installation instructions.
"""

        content = checker._notification_content(item)

        self.assertIn("```bash", content)
        self.assertIn("# or fresh install", content)
        self.assertNotIn("Duplicate installation", content)

    def test_truncation_does_not_leave_an_unclosed_fenced_code_block(self):
        item = release("v2026.7.30", "0.19.1", "2026-07-30T00:00:00Z")
        item["body"] = (
            "# Hermes Agent v0.19.1\n\n## Bug Fixes\n\n- Preamble.\n\n"
            "```text\n"
            + ("x" * 9000)
            + "\n```\n\n- Tail.\n"
        )

        content = checker._notification_content(item)

        self.assertEqual(content.count("```"), 0)
        self.assertIn("Release notes truncated", content)

    def test_patch_drops_commit_citation_and_repairs_stray_scope_parenthesis(self):
        item = release("v2026.5.29.2", "0.15.2", "2026-05-29T00:00:00Z")
        item["body"] = """# Hermes Agent v0.15.2

## Bug Fixes

- Packaging): ship manifests ([`827f7f07`](https://github.com/NousResearch/hermes-agent/commit/827f7f07))
"""

        content = checker._notification_content(item)

        self.assertIn("- Packaging: ship manifests", content)
        self.assertNotIn("commit/", content)

    def test_normalize_release_filters_are_applied_by_fetch(self):
        response = unittest.mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"tag_name": "v2026.8.31", "name": "Hermes Agent v0.21.0", "body": "notes"},
            {"tag_name": "preview", "name": "Preview", "prerelease": True},
            {"tag_name": "draft", "name": "Draft", "draft": True},
        ]
        with patch.object(checker.requests, "get", return_value=response):
            releases, error = checker.fetch_releases_api()

        self.assertIsNone(error)
        self.assertEqual([item["tag"] for item in releases], ["v2026.8.31"])

    def test_api_paginates_until_saved_tag_is_found(self):
        first_page = unittest.mock.Mock()
        first_page.raise_for_status.return_value = None
        first_page.json.return_value = [
            {"tag_name": f"v2026.8.{day}", "name": f"Hermes Agent v0.20.{day}", "body": "notes"}
            for day in range(31, 21, -1)
        ]
        second_page = unittest.mock.Mock()
        second_page.raise_for_status.return_value = None
        second_page.json.return_value = [
            {"tag_name": "v2026.8.21", "name": "Hermes Agent v0.20.0", "body": "notes"}
        ]
        with patch.object(checker.requests, "get", side_effect=[first_page, second_page]) as mock_get:
            releases, error = checker.fetch_releases_api(stop_at_tag="v2026.8.21")

        self.assertIsNone(error)
        self.assertEqual(len(releases), 11)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["page"], 2)

    def test_api_can_paginate_all_releases_without_a_saved_tag(self):
        first_page = unittest.mock.Mock()
        first_page.raise_for_status.return_value = None
        first_page.json.return_value = [
            {"tag_name": f"v2026.8.{day}", "name": f"Hermes Agent v0.20.{day}"}
            for day in range(3, 0, -1)
        ]
        second_page = unittest.mock.Mock()
        second_page.raise_for_status.return_value = None
        second_page.json.return_value = [
            {"tag_name": "v2026.7.31", "name": "Hermes Agent v0.19.9"}
        ]
        with patch.object(checker.requests, "get", side_effect=[first_page, second_page]) as mock_get:
            releases, error = checker.fetch_releases_api(per_page=3, paginate_all=True)

        self.assertIsNone(error)
        self.assertEqual(len(releases), 4)
        self.assertEqual(mock_get.call_count, 2)

    @patch.object(checker, "send_bilingual_notification")
    @patch.object(checker, "translate_changelog")
    def test_empty_telegram_config_advances_without_translation_or_send(self, mock_translate, mock_send):
        old = release("v2026.8.27", "0.20.6", "2026-08-27T12:06:53Z")
        new = release("v2026.8.31", "0.21.0", "2026-08-31T19:29:49Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir, "hermes_latest_version.txt")
            version_file.write_text(old["tag"], encoding="utf-8")
            with (
                patch.object(checker, "VERSION_FILE", str(version_file)),
                patch.object(checker, "TELEGRAM_BOT_TOKEN", ""),
                patch.object(checker, "TELEGRAM_CHAT_ID", ""),
                patch.object(checker, "fetch_releases", return_value=([new, old], "test", None)),
                patch.object(sys, "argv", ["checker.py"]),
            ):
                result = checker.main()

            self.assertEqual(result, 0)
            self.assertEqual(version_file.read_text(encoding="utf-8"), new["tag"])
        mock_translate.assert_not_called()
        mock_send.assert_not_called()

    def test_first_run_records_latest_as_baseline(self):
        older = release("v2026.8.27", "0.20.6", "2026-08-27T12:06:53Z")
        latest = release("v2026.8.31", "0.21.0", "2026-08-31T19:29:49Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            version_file = Path(temp_dir, "hermes_latest_version.txt")
            with (
                patch.object(checker, "VERSION_FILE", str(version_file)),
                patch.object(checker, "TELEGRAM_BOT_TOKEN", ""),
                patch.object(checker, "TELEGRAM_CHAT_ID", ""),
                patch.object(checker, "fetch_releases", return_value=([latest, older], "test", None)),
                patch.object(sys, "argv", ["checker.py"]),
            ):
                result = checker.main()

            self.assertEqual(result, 0)
            self.assertEqual(version_file.read_text(encoding="utf-8"), latest["tag"])


if __name__ == "__main__":
    unittest.main()
