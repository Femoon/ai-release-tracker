import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.state import compute_body_hash
from products.claude_code import checker as claude
from products.codex import checker as codex
from products.openclaw import checker as openclaw


CASES = ((claude, "1.0.0", "1.0.1"),
         (codex, "rust-v1.0.0", "rust-v1.0.1"),
         (openclaw, "2026.8.1", "2026.9.1"))


class DeliveryRetryTests(unittest.TestCase):
    @contextlib.contextmanager
    def scenario(self, module, old, new, content=None):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            (root / "output").mkdir()
            version = root / "output/version.txt"
            state = root / "output/state.json"
            version.write_text(old)
            body = content or f"## {new}\n\n- Fixed a bug."
            for name, value in (("VERSION_FILE", str(version)), ("MESSAGE_STATE_FILE", str(state)),
                                ("PROJECT_ROOT", directory)):
                stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(sys, "argv", ["checker.py"]))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if module is codex:
                stack.enter_context(patch.object(module, "fetch_releases_feed", return_value=("feed", None)))
                stack.enter_context(patch.object(module, "parse_latest_stable_release",
                    return_value=(new, new, body, "https://example.invalid/release", None)))
                stack.enter_context(patch.object(module, "resolve_saved_version_to_tag",
                    side_effect=lambda value: (value, False, None)))
            else:
                stack.enter_context(patch.object(module, "fetch_changelog", return_value=body))
            translate = stack.enter_context(patch.object(module, "translate_changelog", return_value="修复错误。"))
            yield version, state, body, translate

    def test_failed_delivery_retries_and_only_then_advances(self):
        for module, old, new in CASES:
            with self.subTest(product=module.__name__), self.scenario(module, old, new) as (version, state, _, _):
                with patch.object(module, "send_bilingual_notification", side_effect=[
                    {"success": False, "message_ids": []}, {"success": True, "message_ids": [123]}
                ]) as send:
                    self.assertEqual(module.main(), 1)
                    self.assertEqual(version.read_text(), old)
                    self.assertFalse(state.exists())
                    self.assertEqual(module.main(), 0)
                    self.assertEqual(version.read_text(), new)
                    self.assertEqual(module.read_message_state()["message_ids"], [123])
                    self.assertEqual(module.main(), 0)
                    self.assertEqual(send.call_count, 2)

    def test_transient_edit_failure_retains_state_for_retry(self):
        for module, old, new in CASES:
            with self.subTest(product=module.__name__), self.scenario(module, old, new) as (version, _, _, _):
                version.write_text(new)
                module.save_message_state(new, [123], "old-hash")
                with patch.object(module, "edit_bilingual_notification", side_effect=[
                    {"success": False, "message_ids": []}, {"success": True, "message_ids": [123]}
                ]) as edit:
                    self.assertEqual(module.main(), 1)
                    self.assertEqual(module.read_message_state()["body_hash"], "old-hash")
                    self.assertEqual(module.main(), 0)
                    self.assertEqual(module.read_message_state()["edit_count"], 1)
                    self.assertEqual(edit.call_count, 2)

    def test_long_translation_and_notification_share_bounded_input(self):
        for module, old, new in CASES:
            content = f"## {new}\n\n" + "\n".join(f"- Feature {i}: " + "description " * 30 for i in range(80))
            with self.subTest(product=module.__name__), self.scenario(module, old, new, content) as (_, _, _, translate):
                with patch.object(module, "send_bilingual_notification", return_value={"success": True, "message_ids": [1]}) as send:
                    self.assertEqual(module.main(), 0)
                    selected = translate.call_args.args[0]
                    self.assertLessEqual(len(selected), 8000)
                    self.assertIn("View complete release notes", selected)
                    self.assertEqual(send.call_args.kwargs["original"], selected)
                    hash_source = selected if module is openclaw else content
                    self.assertEqual(module.read_message_state()["body_hash"], compute_body_hash(hash_source))
                    with patch.object(module, "edit_bilingual_notification") as edit:
                        self.assertEqual(module.main(), 0)
                        edit.assert_not_called()

    def test_force_failure_keeps_existing_state(self):
        for module, old, new in CASES:
            with self.subTest(product=module.__name__), self.scenario(module, old, new) as (version, state, _, _):
                with patch.object(sys, "argv", ["checker.py", "--force"]), patch.object(
                    module, "send_bilingual_notification", return_value={"success": False, "message_ids": []}
                ):
                    self.assertEqual(module.main(), 1)
                    self.assertEqual(version.read_text(), old)
                    self.assertFalse(state.exists())
