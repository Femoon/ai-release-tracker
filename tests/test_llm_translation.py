import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.translate.llm import translate_changelog
from core.translate.policy import protect


MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
API_KEY = "test-key"


def response(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    )


class TranslateChangelogTests(unittest.TestCase):
    def setUp(self):
        self.source = "## 1.2.3\n\n- Added Agent support in `config.toml`."
        document = protect(self.source)
        lines = document.protected.splitlines()
        lines[-1] = lines[-1].replace("Added", "新增").replace("support in", "支持，配置位于")
        self.valid_candidate = "\n".join(lines)

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_valid_translation_calls_model_once_and_caches(self, mock_completion, mock_get, mock_set):
        mock_completion.return_value = response(self.valid_candidate)

        translated = translate_changelog(self.source, MODEL, API_KEY)

        self.assertIn("Agent", translated)
        self.assertIn("`config.toml`", translated)
        self.assertEqual(mock_completion.call_count, 1)
        self.assertEqual(mock_get.call_args.kwargs["kind"], "translate_guarded_v1")
        self.assertEqual(mock_set.call_args.kwargs["kind"], "translate_guarded_v1")

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_none_content_retries_same_model_once(self, mock_completion, _mock_get, mock_set):
        mock_completion.side_effect = [response(None), response(self.valid_candidate)]

        translated = translate_changelog(self.source, MODEL, API_KEY)

        self.assertTrue(translated)
        self.assertEqual(mock_completion.call_count, 2)
        self.assertEqual(
            [call.kwargs["model"] for call in mock_completion.call_args_list],
            [MODEL, MODEL],
        )
        mock_set.assert_called_once()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_repair_changes_only_failed_line(self, mock_completion, _mock_get, mock_set):
        source = "- Agent works.\n- Skill works."
        document = protect(source)
        tokens = [placeholder.token for placeholder in document.placeholders]
        invalid_candidate = f"- {tokens[1]} 可用。\n- {tokens[0]} 可用。"
        mock_completion.side_effect = [
            response(invalid_candidate),
            response('{"0": "- ' + tokens[0] + ' 可用。", "1": "- ' + tokens[1] + ' 可用。"}'),
        ]

        translated = translate_changelog(source, MODEL, API_KEY)

        self.assertEqual(translated, "- Agent 可用。\n- Skill 可用。")
        self.assertEqual(mock_completion.call_count, 2)
        self.assertEqual(
            [call.kwargs["model"] for call in mock_completion.call_args_list],
            [MODEL, MODEL],
        )
        self.assertEqual(
            mock_completion.call_args_list[1].kwargs["response_format"],
            {"type": "json_object"},
        )
        mock_set.assert_called_once()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_nonrepairable_structure_retries_full_translation(self, mock_completion, _mock_get, mock_set):
        source = "- Agent works.\n- Skill works."
        document = protect(source)
        lines = document.protected.splitlines()
        merged_candidate = " ".join(lines)
        valid_candidate = "\n".join(line.replace("works.", "可用。") for line in lines)
        mock_completion.side_effect = [
            response(merged_candidate),
            response(valid_candidate),
        ]

        translated = translate_changelog(source, MODEL, API_KEY)

        self.assertEqual(translated, "- Agent 可用。\n- Skill 可用。")
        self.assertEqual(mock_completion.call_count, 2)
        mock_set.assert_called_once()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_failed_repair_returns_empty_and_does_not_cache(self, mock_completion, _mock_get, mock_set):
        document = protect(self.source)
        tokens = [placeholder.token for placeholder in document.placeholders]
        invalid_candidate = self.valid_candidate.replace(tokens[1], "BROKEN")
        mock_completion.side_effect = [response(invalid_candidate), response('{"2": "仍然错误"}')]

        translated = translate_changelog(self.source, MODEL, API_KEY)

        self.assertEqual(translated, "")
        self.assertEqual(mock_completion.call_count, 2)
        mock_set.assert_not_called()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_length_response_fails_without_retry(self, mock_completion, _mock_get, mock_set):
        mock_completion.return_value = response(None, finish_reason="length")

        translated = translate_changelog(self.source, MODEL, API_KEY)

        self.assertEqual(translated, "")
        self.assertEqual(mock_completion.call_count, 1)
        mock_set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
