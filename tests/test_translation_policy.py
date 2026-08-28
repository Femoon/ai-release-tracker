import unittest

from core.translate.policy import (
    DEGRADED_MIN_PLACEHOLDERS,
    apply_repair,
    degraded_tolerance,
    is_acceptable_degradation,
    protect,
    repair_items,
    repair_placeholders,
    restore,
    validate,
)


def long_document(term_count: int):
    """构造一份 placeholder 数量足够触发降级判断的文档。"""
    source = "\n".join(f"- Agent fixed issue {index} in Skill." for index in range(term_count))
    return protect(source)


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

    def test_allows_blank_line_changes_without_losing_structure(self):
        document = protect("**New Features**\n\n- Agent works.\n- Skill works.")
        candidate = document.protected.replace("\n\n", "\n")

        validation = validate(document, candidate)

        self.assertTrue(validation.valid)

    def test_repair_placeholders_drops_duplicated_token(self):
        # 复现 2.1.251 的真实失败形态：中文语序把同一个术语重复了一次
        document = protect("- Fixed Remote Control reporting a failure when disabled.")
        token = document.placeholders[0].token
        candidate = f"- 修复了禁用 {token} 时 {token} 报告失败的问题。"

        self.assertFalse(validate(document, candidate).valid)
        repaired, removed = repair_placeholders(document, candidate)

        self.assertEqual(removed, 1)
        self.assertTrue(validate(document, repaired).valid)
        self.assertEqual(restore(document, repaired), "- 修复了禁用 Remote Control 时报告失败的问题。")

    def test_repair_placeholders_keeps_cross_line_move_for_model_repair(self):
        document = protect("- Agent works.\n- Skill works.")
        first, second = (item.token for item in document.placeholders)
        candidate = f"- {second} 可用。\n- {first} 可用。"

        repaired, removed = repair_placeholders(document, candidate)

        self.assertEqual(removed, 0)
        self.assertEqual(repaired, candidate)

    def test_repair_placeholders_noop_when_line_counts_differ(self):
        document = protect("- Agent works.\n- Skill works.")
        token = document.placeholders[0].token

        repaired, removed = repair_placeholders(document, f"- {token} {token} 可用。")

        self.assertEqual(removed, 0)

    def test_degraded_tolerance_scales_and_excludes_short_documents(self):
        self.assertEqual(degraded_tolerance(3), 0)
        self.assertEqual(degraded_tolerance(DEGRADED_MIN_PLACEHOLDERS - 1), 0)
        self.assertEqual(degraded_tolerance(20), 1)
        self.assertEqual(degraded_tolerance(143), 8)
        self.assertEqual(degraded_tolerance(10000), 10)

    def test_small_placeholder_drift_in_long_document_is_acceptable(self):
        document = long_document(30)
        lines = document.protected.splitlines()
        lines[0] = lines[0].replace(document.placeholders[0].token, "")
        validation = validate(document, "\n".join(lines))

        self.assertFalse(validation.valid)
        self.assertEqual(validation.structure_issue_count, 0)
        self.assertTrue(is_acceptable_degradation(document, validation))

    def test_large_placeholder_drift_is_not_acceptable(self):
        document = long_document(30)
        candidate = document.protected
        for placeholder in document.placeholders[:12]:
            candidate = candidate.replace(placeholder.token, "")
        validation = validate(document, candidate)

        self.assertGreater(validation.token_issue_count, degraded_tolerance(60))
        self.assertFalse(is_acceptable_degradation(document, validation))

    def test_structure_violation_is_never_acceptable(self):
        document = long_document(30)
        candidate = document.protected + "\n- 额外的一行"
        validation = validate(document, candidate)

        self.assertGreater(validation.structure_issue_count, 0)
        self.assertFalse(is_acceptable_degradation(document, validation))

    def test_short_document_drift_is_never_acceptable(self):
        document = protect("## 1.2.3\n\n- Agent works.")
        candidate = document.protected.replace(document.placeholders[1].token, "")
        validation = validate(document, candidate)

        self.assertFalse(validation.valid)
        self.assertEqual(validation.structure_issue_count, 0)
        self.assertFalse(is_acceptable_degradation(document, validation))

    def test_repair_items_carry_precise_token_diffs(self):
        document = protect("- Agent works.\n- Skill works.")
        first, second = (item.token for item in document.placeholders)
        candidate = f"- {second} 可用。\n- {first} 可用。"
        validation = validate(document, candidate)

        items = repair_items(document, candidate, validation)

        self.assertEqual([item["line"] for item in items], [0, 1])
        self.assertEqual(items[0]["missing_placeholders"], [first])
        self.assertEqual(items[0]["extra_placeholders"], [second])

    def test_line_count_change_is_not_repairable(self):
        document = protect("## 1.2.3\n\n- Agent works.")
        candidate = document.protected + "\nextra"

        validation = validate(document, candidate)

        self.assertFalse(validation.valid)
        self.assertFalse(validation.repairable)


if __name__ == "__main__":
    unittest.main()
