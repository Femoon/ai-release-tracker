import contextlib
import io
import unittest
from unittest.mock import patch

from products.claude_code import pusher as claude
from products.codex import pusher as codex
from products.openclaw import pusher as openclaw


class PusherTranslationTests(unittest.TestCase):
    def test_failed_translation_never_sends_or_marks_pushed(self):
        for module, version in ((claude, "1.2.3"), (codex, "1.2.3"), (openclaw, "2026.9.1")):
            with self.subTest(product=module.__name__), contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if module is codex:
                    stack.enter_context(patch.object(module, "parse_releases_file", return_value=[
                        {"name": version, "body": "- Fixed a bug.", "url": "https://example.invalid"}
                    ]))
                else:
                    stack.enter_context(patch.object(module, "fetch_changelog", return_value=f"## {version}\n- Fixed a bug."))
                stack.enter_context(patch.object(module, "read_pushed_versions", return_value={}))
                stack.enter_context(patch.object(module, "translate_changelog", return_value=""))
                send = stack.enter_context(patch.object(module, "send_bilingual_notification"))
                save = stack.enter_context(patch.object(module, "append_pushed_version"))
                self.assertEqual(module.main(), 1)
                send.assert_not_called()
                save.assert_not_called()
