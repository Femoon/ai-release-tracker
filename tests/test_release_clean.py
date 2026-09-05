import unittest
from unittest.mock import patch

from core.utils.clean import clean_release_body
from products.codex import checker


class ReleaseCleanTests(unittest.TestCase):
    def test_inline_code_is_preserved_exactly(self):
        for code in ("`../config`", "`npm install @openai/codex`", "`#123456`",
                     "``a `nested` value``", "`foo(...args)`"):
            with self.subTest(code=code):
                self.assertIn(code, clean_release_body(f"- Use {code}. (#42)"))

    def test_fences_and_indented_code_preserve_whitespace(self):
        for code in ("```python\n    print('../config', '#123456')\n    # Full Changelog\n```",
                     "~~~sh\nnpm install @openai/codex\n~~~",
                     "    npm install @openai/codex\n    echo ../config"):
            with self.subTest(code=code):
                self.assertIn(code, clean_release_body("Notes\n\n" + code + "\n\nEnd."))

    def test_links_and_plain_package_names_are_preserved(self):
        body = "Use @openai/codex and ../config. See [docs](https://example.org/a#123)."
        self.assertEqual(clean_release_body(body), body)

    def test_code_inside_link_and_standalone_indented_code(self):
        for body in ("[`../config`](https://example.org/path)", "    echo ../config"):
            self.assertEqual(clean_release_body(body), body)

    def test_prose_references_are_still_cleaned(self):
        result = clean_release_body("- Fixed a bug (#42). Thanks @alice.")
        self.assertNotIn("#42", result)
        self.assertIn("[@alice](https://github.com/alice)", result)

    def test_codex_uses_rest_markdown_for_code_preservation(self):
        feed = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>1.2.3</title><link href="https://github.com/openai/codex/releases/tag/rust-v1.2.3"/>
        <content>&lt;p&gt;Use &amp;lt;id&amp;gt;&lt;/p&gt;</content></entry></feed>'''
        with patch.object(checker, "verify_release_via_api", return_value=({
            "tag_name": "rust-v1.2.3", "body": "- Use `<id>` with `../config`."
        }, "stable")):
            result = checker.parse_latest_stable_release(feed)
        self.assertIn("`<id>`", result[2])
        self.assertIn("`../config`", result[2])
