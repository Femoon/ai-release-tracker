import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from products.hermes import pusher
from tests.test_hermes_checker import release


class HermesPusherTests(unittest.TestCase):
    def test_select_pending_preserves_oldest_first_order(self):
        releases = [
            release("v2026.3.12", "0.2.0", "2026-03-12T00:00:00Z"),
            release("v2026.3.17", "0.3.0", "2026-03-17T00:00:00Z"),
            release("v2026.3.23", "0.4.0", "2026-03-23T00:00:00Z"),
        ]

        selected = pusher.select_pending(releases, {"v2026.3.17"}, count=1)

        self.assertEqual([item["tag"] for item in selected], ["v2026.3.12"])

    def test_target_tag_does_not_repush_recorded_release(self):
        releases = [release("v2026.8.31", "0.21.0", "2026-08-31T00:00:00Z")]

        selected = pusher.select_pending(
            releases, {"v2026.8.31"}, target_tag="v2026.8.31"
        )

        self.assertEqual(selected, [])

    def test_main_records_tag_only_after_successful_send(self):
        item = release("v2026.3.12", "0.2.0", "2026-03-12T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            pushed_file = Path(temp_dir, "pushed.txt")
            with (
                patch.object(pusher, "PUSHED_VERSIONS_FILE", str(pushed_file)),
                patch.object(pusher, "PUSH_STATE_FILE", str(Path(temp_dir, "state.json"))),
                patch.object(pusher, "TELEGRAM_BOT_TOKEN", "token"),
                patch.object(pusher, "TELEGRAM_CHAT_ID", "chat"),
                patch.object(pusher, "fetch_all_releases", return_value=([item], None)),
                patch.object(
                    pusher,
                    "deliver_release",
                    return_value={
                        "success": True,
                        "message_ids": [42],
                        "telegraph_url": None,
                    },
                ),
            ):
                result = pusher.main(count=1)

            self.assertEqual(result, 0)
            self.assertEqual(pushed_file.read_text(encoding="utf-8"), "v2026.3.12\n")

    def test_edit_all_resumes_only_old_format_messages(self):
        old = release("v2026.3.12", "0.2.0", "2026-03-12T00:00:00Z")
        current = release("v2026.3.17", "0.3.0", "2026-03-17T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir, "state.json")
            state_file.write_text(
                json.dumps(
                    {
                        old["tag"]: {"message_id": 5, "format_version": 1},
                        current["tag"]: {
                            "message_id": 8,
                            "format_version": pusher.FORMAT_VERSION,
                            "content_hash": pusher.release_content_hash(current),
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(pusher, "PUSHED_VERSIONS_FILE", str(Path(temp_dir, "pushed.txt"))),
                patch.object(pusher, "PUSH_STATE_FILE", str(state_file)),
                patch.object(pusher, "TELEGRAM_BOT_TOKEN", "token"),
                patch.object(pusher, "TELEGRAM_CHAT_ID", "chat"),
                patch.object(pusher, "fetch_all_releases", return_value=([old, current], None)),
                patch.object(
                    pusher,
                    "deliver_release",
                    return_value={
                        "success": True,
                        "message_ids": [5],
                        "telegraph_url": "https://telegra.ph/new",
                    },
                ) as mock_deliver,
            ):
                result = pusher.main(edit_all=True)

            self.assertEqual(result, 0)
            mock_deliver.assert_called_once_with(old, message_id=5)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(state[old["tag"]]["format_version"], pusher.FORMAT_VERSION)
            self.assertEqual(state[old["tag"]]["telegraph_url"], "https://telegra.ph/new")

    def test_edit_all_fails_when_a_pushed_tag_has_no_message_mapping(self):
        item = release("v2026.3.12", "0.2.0", "2026-03-12T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            pushed_file = Path(temp_dir, "pushed.txt")
            pushed_file.write_text(f"{item['tag']}\n", encoding="utf-8")
            with (
                patch.object(pusher, "PUSHED_VERSIONS_FILE", str(pushed_file)),
                patch.object(pusher, "PUSH_STATE_FILE", str(Path(temp_dir, "state.json"))),
                patch.object(pusher, "TELEGRAM_BOT_TOKEN", "token"),
                patch.object(pusher, "TELEGRAM_CHAT_ID", "chat"),
                patch.object(pusher, "fetch_all_releases", return_value=([item], None)),
                patch.object(pusher, "deliver_release") as mock_deliver,
            ):
                result = pusher.main(edit_all=True)

        self.assertEqual(result, 1)
        mock_deliver.assert_not_called()

    def test_edit_all_reedits_current_format_when_content_hash_changes(self):
        item = release("v2026.3.12", "0.2.0", "2026-03-12T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir, "state.json")
            state_file.write_text(
                json.dumps(
                    {
                        item["tag"]: {
                            "message_id": 5,
                            "format_version": pusher.FORMAT_VERSION,
                            "content_hash": "stale",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(pusher, "PUSHED_VERSIONS_FILE", str(Path(temp_dir, "pushed.txt"))),
                patch.object(pusher, "PUSH_STATE_FILE", str(state_file)),
                patch.object(pusher, "TELEGRAM_BOT_TOKEN", "token"),
                patch.object(pusher, "TELEGRAM_CHAT_ID", "chat"),
                patch.object(pusher, "fetch_all_releases", return_value=([item], None)),
                patch.object(
                    pusher,
                    "deliver_release",
                    return_value={"success": True, "message_ids": [5], "telegraph_url": None},
                ) as mock_deliver,
            ):
                result = pusher.main(edit_all=True)

        self.assertEqual(result, 0)
        mock_deliver.assert_called_once_with(item, message_id=5)

    def test_concurrent_pusher_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir, "state.json")
            with patch.object(pusher, "PUSH_STATE_FILE", str(state_file)):
                lock_file = pusher.acquire_push_lock()
                self.assertIsNotNone(lock_file)
                try:
                    result = pusher.main(dry_run=False)
                finally:
                    pusher.release_push_lock(lock_file)

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
