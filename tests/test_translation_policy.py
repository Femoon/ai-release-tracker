import unittest

from core.translate.policy import apply_repair, protect, restore, validate


class TranslationPolicyTests(unittest.TestCase):
    def test_protects_case_and_plural_variants(self):
        source = "- Subagent and subagents use agent prompts, Skills, Sandboxes, and Memories."

        document = protect(source)
        restored = restore(document, document.protected)

        self.assertNotIn("Subagent", document.protected)
        self.assertNotIn("subagents", document.protected)
        self.assertEqual(restored, source)
        self.assertTrue(validate(document, document.protected).valid)

    def test_does_not_protect_non_cli_agent_phrases(self):
        source = "- Updated the user agent and proxy agent while Agent workers run."

        document = protect(source)

        self.assertIn("user agent", document.protected)
        self.assertIn("proxy agent", document.protected)
        self.assertNotIn("Agent workers", document.protected)

    def test_restores_fixed_translation_without_chinese_spaces(self):
        source = "- Supported newer models under full-strength redaction with context cost."

        document = protect(source)
        candidate = "- 在 " + " 下使用 ".join(
            placeholder.token for placeholder in document.placeholders
        )
        restored = restore(document, candidate)

        self.assertNotIn("在 更新的模型", restored)
        self.assertNotIn("完整强度脱敏 下", restored)
        self.assertIn("更新的模型", restored)
        self.assertIn("完整强度脱敏", restored)
        self.assertIn("上下文开销", restored)

    def test_allows_placeholder_reordering_within_line(self):
        source = "- Agent uses Skill."
        document = protect(source)
        first, second = (item.token for item in document.placeholders)
        candidate = f"- {second} 使用 {first}。"

        validation = validate(document, candidate)

        self.assertTrue(validation.valid)

    def test_detects_placeholder_moved_between_lines(self):
        document = protect("- Agent works.\n- Skill works.")
        first, second = (item.token for item in document.placeholders)
        candidate = f"- {second} 可用。\n- {first} 可用。"

        validation = validate(document, candidate)

        self.assertFalse(validation.valid)
        self.assertTrue(validation.repairable)
        repaired = apply_repair(
            candidate,
            validation.affected_lines,
            '{"0": "- ' + first + ' 可用。", "1": "- ' + second + ' 可用。"}',
        )
        self.assertTrue(validate(document, repaired).valid)

    def test_line_count_change_is_not_repairable(self):
        document = protect("## 1.2.3\n\n- Agent works.")
        candidate = document.protected + "\nextra"

        validation = validate(document, candidate)

        self.assertFalse(validation.valid)
        self.assertFalse(validation.repairable)


if __name__ == "__main__":
    unittest.main()
