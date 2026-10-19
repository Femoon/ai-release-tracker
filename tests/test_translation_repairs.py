import unittest
from unittest.mock import patch

from core.notify.telegraph import build_changelog_html, html_to_nodes, publish_changelog
from scripts import apply_translation_repairs as apply_script
from scripts import prepare_translation_repairs as prepare


ORIGINAL = "## 2026.4.25\n\n### Highlights\n\n- Added `foo` support."
TRANSLATED = "## 2026.4.25\n\n### Highlights\n\n- 新增 `foo` 支持。"
SOURCE = "https://github.com/openclaw/openclaw/releases/tag/v2026.4.25"
PAGE = "OpenClaw-2026425-Release-Notes-EN-04-26-17"
BEFORE_PAGE = {"title": "OpenClaw 2026.4.25 Release Notes (EN)", "content": [{"tag": "p", "children": ["old"]}]}
BEFORE_MESSAGE = {"markdown": "**OpenClaw 2026.4.25 Released**", "body": {"tag": "div", "children": ["old"]}}


class TranslationRepairPlanTests(unittest.TestCase):
    def test_page_html_matches_checker_single_page(self):
        with patch("core.notify.telegraph.create_page", return_value={"success": True}) as create:
            publish_changelog("OpenClaw", ORIGINAL, TRANSLATED, "2026.4.25", SOURCE)
        self.assertEqual(create.call_args.args[1], build_changelog_html(ORIGINAL, TRANSLATED, SOURCE))

    def test_page_plan_is_bilingual_and_drops_en_title(self):
        plan = prepare.build_page_plan(PAGE, "OpenClaw", "2026.4.25", ORIGINAL, TRANSLATED, SOURCE, BEFORE_PAGE)
        self.assertEqual(plan["title"], "OpenClaw 2026.4.25 Release Notes")
        self.assertEqual(plan["path"], PAGE)
        self.assertEqual(plan["content"], html_to_nodes(plan["content_html"]))
        self.assertIn("新增", plan["content_html"])
        self.assertIn(SOURCE, plan["content_html"])
        self.assertTrue(all(plan["checks"].values()))
        self.assertEqual(plan["before_content"], BEFORE_PAGE["content"])

    def test_oversized_page_fails_check(self):
        with patch.object(prepare, "TELEGRAPH_CONTENT_LIMIT", 10):
            plan = prepare.build_page_plan(PAGE, "OpenClaw", "2026.4.25", ORIGINAL, TRANSLATED, SOURCE, BEFORE_PAGE)
        self.assertFalse(plan["checks"]["within_telegraph_limit"])

    def test_message_plan_keeps_page_and_source_links(self):
        summary = "• Added foo\n\n• 新增 foo"
        plan = prepare.build_message_plan(
            "openclaw_push/87", "OpenClaw", "2026.4.25", SOURCE,
            "https://telegra.ph/" + PAGE, summary, BEFORE_MESSAGE,
        )
        self.assertEqual((plan["channel"], plan["id"]), ("openclaw_push", 87))
        self.assertIn(summary, plan["after"])
        self.assertIn("https://telegra.ph/" + PAGE, plan["after"])
        self.assertIn(f"[GitHub]({SOURCE})", plan["after"])
        self.assertNotIn("暂无摘要", plan["after"])
        self.assertTrue(all(plan["checks"].values()))
        self.assertEqual(plan["before_body"], BEFORE_MESSAGE["body"])

    def prepare_with(self, target, translated, summary):
        with patch.object(prepare, "load_source", return_value=(ORIGINAL, SOURCE)), \
             patch.object(prepare, "read_page", return_value=BEFORE_PAGE), \
             patch.object(prepare, "read_message", return_value=BEFORE_MESSAGE), \
             patch.object(prepare, "translate_changelog", return_value=translated) as translate, \
             patch.object(prepare, "summarize_changelog", return_value=summary) as summarize:
            return prepare.prepare_target(target), translate, summarize

    def test_translation_failure_never_plans_english(self):
        target = {"key": "openclaw_push/87", "title": "OpenClaw", "version": "2026.4.25",
                  "page": PAGE, "message": True}
        plan, _, summarize = self.prepare_with(target, "", "summary")
        self.assertEqual(plan["status"], "failed")
        self.assertNotIn("page", plan)
        self.assertNotIn("message", plan)
        summarize.assert_not_called()

    def test_summary_failure_never_plans_degraded_notice(self):
        target = {"key": "openclaw_push/128", "title": "OpenClaw", "version": "2026.9.8",
                  "page": PAGE, "message": True, "translate": False}
        plan, translate, _ = self.prepare_with(target, TRANSLATED, "")
        self.assertEqual(plan["status"], "failed")
        self.assertNotIn("message", plan)
        translate.assert_not_called()

    def test_ready_plan_with_page_and_message(self):
        target = {"key": "openclaw_push/87", "title": "OpenClaw", "version": "2026.4.25",
                  "page": PAGE, "message": True}
        plan, _, _ = self.prepare_with(target, TRANSLATED, "• Added foo\n\n• 新增 foo")
        self.assertEqual(plan["status"], "ready", plan["reasons"])
        self.assertIn("page", plan)
        self.assertIn("message", plan)


class TranslationRepairApplyTests(unittest.TestCase):
    def setUp(self):
        self.page = prepare.build_page_plan(PAGE, "OpenClaw", "2026.4.25", ORIGINAL, TRANSLATED, SOURCE, BEFORE_PAGE)
        self.plan = {"key": "openclaw_push/95", "title": "OpenClaw", "version": "2026.4.25",
                     "status": "ready", "reasons": [], "page": self.page}

    def drift(self, content):
        with patch.object(apply_script, "get_page",
                          return_value={"success": True, "page": {"content": content}}):
            return apply_script.check(self.plan, "token", {PAGE})

    def test_unchanged_page_passes(self):
        self.assertEqual(self.drift(BEFORE_PAGE["content"]), [])

    def test_changed_page_is_blocked(self):
        self.assertEqual(self.drift([{"tag": "p", "children": ["edited"]}]), ["page changed since plan"])

    def test_applied_page_is_not_blocking(self):
        self.assertEqual(self.drift(self.page["content"]), ["already applied"])

    def test_unowned_page_is_blocked(self):
        self.assertEqual(apply_script.check(self.plan, "token", set()), ["page not owned"])

    def test_failed_plan_is_blocked(self):
        self.plan.update(status="failed", reasons=["summary_failed"])
        self.assertEqual(apply_script.check(self.plan, "token", {PAGE}), ["plan not ready (summary_failed)"])


if __name__ == "__main__":
    unittest.main()
