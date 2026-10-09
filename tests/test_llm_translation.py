import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from core.translate import llm
from core.translate.llm import _normalize_bilingual_summary, _translation_max_tokens, summarize_changelog, translate_changelog
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
    def test_budget_accounts_for_placeholder_expansion(self, mock_completion, _get, _set):
        source = "\n".join("- API CLI SDK LLM Agent works." for _ in range(200))
        document = protect(source)
        mock_completion.return_value = response(document.protected.replace("works.", "功能正常，可正常使用。"))
        translate_changelog(source, MODEL, API_KEY)
        budget = mock_completion.call_args.kwargs["max_tokens"]
        self.assertEqual(budget, _translation_max_tokens(document.protected))
        self.assertGreater(budget, _translation_max_tokens(source))

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_valid_translation_calls_model_once_and_caches(self, mock_completion, mock_get, mock_set):
        mock_completion.return_value = response(self.valid_candidate)

        translated = translate_changelog(self.source, MODEL, API_KEY)

        self.assertIn("Agent", translated)
        self.assertIn("`config.toml`", translated)
        self.assertEqual(mock_completion.call_count, 1)
        self.assertEqual(mock_get.call_args.kwargs["kind"], "translate_guarded_v2")
        self.assertEqual(mock_set.call_args.kwargs["kind"], "translate_guarded_v2")

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
    def test_duplicated_placeholder_is_repaired_without_extra_call(
        self, mock_completion, _mock_get, mock_set
    ):
        source = "- Fixed Remote Control reporting a failure when disabled."
        document = protect(source)
        token = document.placeholders[0].token
        mock_completion.return_value = response(f"- 修复了禁用 {token} 时 {token} 报告失败的问题。")

        translated = translate_changelog(source, MODEL, API_KEY)

        self.assertEqual(translated, "- 修复了禁用 Remote Control 时报告失败的问题。")
        self.assertEqual(mock_completion.call_count, 1)
        mock_set.assert_called_once()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_long_source_accepts_small_residual_drift(self, mock_completion, _mock_get, mock_set):
        source = "\n".join(f"- Agent fixed issue {index} in Skill." for index in range(30))
        document = protect(source)
        translated_lines = [
            line.replace("fixed issue", "修复了问题").replace("in", "于")
            for line in document.protected.splitlines()
        ]
        # 一个 placeholder 被模型丢掉，结构完好；定向修复没修好也应降级放行
        translated_lines[0] = translated_lines[0].replace(
            document.placeholders[0].token, ""
        )
        mock_completion.side_effect = [
            response("\n".join(translated_lines)),
            response("{}"),
        ]

        translated = translate_changelog(source, MODEL, API_KEY)

        self.assertTrue(translated)
        self.assertEqual(len(translated.splitlines()), 30)
        self.assertEqual(mock_completion.call_count, 2)
        mock_set.assert_called_once()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_long_source_rejects_large_drift(self, mock_completion, _mock_get, mock_set):
        source = "\n".join(f"- Agent fixed issue {index} in Skill." for index in range(30))
        document = protect(source)
        broken = document.protected
        for placeholder in document.placeholders[:12]:
            broken = broken.replace(placeholder.token, "")
        mock_completion.side_effect = [response(broken), response("{}")]

        translated = translate_changelog(source, MODEL, API_KEY)

        self.assertEqual(translated, "")
        mock_set.assert_not_called()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_widely_broken_candidate_retries_instead_of_repairing(
        self, mock_completion, _mock_get, mock_set
    ):
        source = "\n".join(f"- Agent fixed issue {index} in Skill." for index in range(30))
        document = protect(source)
        # 结构完好但 placeholder 大面积错乱：应重新翻译，不做逐行修复
        broken = "\n".join(
            f"- {document.placeholders[0].token} 修复了问题 {index}。" for index in range(30)
        )
        valid_candidate = "\n".join(
            line.replace("fixed issue", "修复了问题").replace(" in ", " 于 ")
            for line in document.protected.splitlines()
        )
        mock_completion.side_effect = [response(broken), response(valid_candidate)]

        translated = translate_changelog(source, MODEL, API_KEY)

        self.assertTrue(translated)
        self.assertEqual(mock_completion.call_count, 2)
        self.assertNotIn(
            "response_format", mock_completion.call_args_list[1].kwargs
        )
        mock_set.assert_called_once()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_repair_making_things_worse_is_discarded(self, mock_completion, _mock_get, mock_set):
        source = "- Agent works.\n- Skill works."
        document = protect(source)
        first, second = (item.token for item in document.placeholders)
        candidate = f"- {second} 可用。\n- {first} 可用。"
        # 修复把两行都写坏：应保留修复前结果，并因短文本 fail closed
        mock_completion.side_effect = [
            response(candidate),
            response('{"0": "全丢了", "1": "也丢了"}'),
        ]

        translated = translate_changelog(source, MODEL, API_KEY)

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


class BuildExtraBodyTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=False)
    def test_without_env_var_only_disables_reasoning(self):
        import os

        os.environ.pop("LLM_PROVIDER_ONLY", None)
        os.environ.pop("LLM_REASONING_EFFORT", None)
        from core.translate.llm import _build_extra_body

        self.assertEqual(_build_extra_body(), {"reasoning": {"effort": "none"}})

    @patch.dict("os.environ", {"LLM_REASONING_EFFORT": "minimal"})
    def test_reasoning_effort_env_override(self):
        from core.translate.llm import _build_extra_body

        self.assertEqual(_build_extra_body()["reasoning"], {"effort": "minimal"})

    @patch.dict("os.environ", {"LLM_PROVIDER_ONLY": "deepseek"})
    def test_single_provider_is_pinned(self):
        from core.translate.llm import _build_extra_body

        self.assertEqual(
            _build_extra_body()["provider"], {"only": ["deepseek"]}
        )

    @patch.dict("os.environ", {"LLM_PROVIDER_ONLY": " deepseek , fireworks ,"})
    def test_comma_separated_providers_are_trimmed(self):
        from core.translate.llm import _build_extra_body

        self.assertEqual(
            _build_extra_body()["provider"], {"only": ["deepseek", "fireworks"]}
        )

    @patch.dict(
        "os.environ",
        {"LLM_PROVIDER_ONLY": "deepseek", "LLM_REASONING_EFFORT": "none"},
    )
    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_provider_pin_reaches_completion_call(self, mock_completion, _mock_get, _mock_set):
        source = "## 1.2.3\n\n- Added Agent support in `config.toml`."
        document = protect(source)
        lines = document.protected.splitlines()
        lines[-1] = lines[-1].replace("Added", "新增").replace("support in", "支持，配置位于")
        mock_completion.return_value = response("\n".join(lines))

        translate_changelog(source, MODEL, API_KEY)

        extra_body = mock_completion.call_args.kwargs["extra_body"]
        self.assertEqual(extra_body["provider"], {"only": ["deepseek"]})
        self.assertEqual(extra_body["reasoning"], {"effort": "none"})


class SummaryFormattingTests(unittest.TestCase):
    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_summary_uses_new_policy_cache_and_rejects_lost_command(
        self, mock_completion, mock_get, mock_set
    ):
        mock_completion.return_value = response(
            "*Key Updates:*\n• For damaged databases run `hermes doctor` first.\n\n"
            "*更新要点：*\n• 数据库损坏时直接重新安装。"
        )
        self.assertEqual(summarize_changelog(
            "If state.db is already damaged, run `hermes doctor` first.", MODEL, API_KEY
        ), "")
        self.assertEqual(mock_get.call_args.kwargs["kind"], "summarize_guarded_v3")
        mock_set.assert_not_called()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_summary_rejects_invented_breaking_label(self, completion, _get, cache_set):
        completion.return_value = response(
            "*Key Updates:*\n• Breaking: secondary profiles no longer inherit allow-lists\n\n"
            "*更新要点：*\n• 破坏性变更：次要配置不再继承允许列表"
        )
        self.assertEqual(summarize_changelog(
            "Secondary profiles no longer inherit default allow-lists.", MODEL, API_KEY
        ), "")
        cache_set.assert_not_called()

    @patch("core.translate.llm.translation_cache.set")
    @patch("core.translate.llm.translation_cache.get", return_value=None)
    @patch("core.translate.llm.completion")
    def test_summary_retries_invalid_format_and_caches_valid_result(
        self, completion, _get, cache_set
    ):
        valid = "*Key Updates:*\n• Fixed `claude` startup.\n\n*更新要点：*\n• 修复 `claude` 启动问题。"
        completion.side_effect = [response("unpaired summary"), response(valid)]

        self.assertEqual(summarize_changelog("Fixed `claude` startup.", MODEL, API_KEY), valid)
        self.assertEqual(completion.call_count, 2)
        self.assertEqual(completion.call_args.kwargs["temperature"], 0)
        cache_set.assert_called_once()

    def test_summary_rejects_translation_of_provider_identifier(self):
        summary = (
            "*Key Updates:*\n• Added the opencode-free zero-auth provider.\n\n"
            "*更新要点：*\n• 新增无 opencode 的零认证提供方。"
        )
        self.assertEqual(_normalize_bilingual_summary(summary), "")
        self.assertTrue(_normalize_bilingual_summary(
            summary.replace("无 opencode 的零认证提供方", "opencode-free 免认证提供商")
        ))

    def test_summary_keeps_recovery_command_with_its_translation(self):
        summary = (
            "*Key Updates:*\n• If state.db is damaged, run `hermes doctor` first.\n\n"
            "*更新要点：*\n• 若 state.db 已损坏，先运行 hermes doctor。"
        )
        self.assertTrue(_normalize_bilingual_summary(summary))
        self.assertEqual(_normalize_bilingual_summary(
            summary.replace("先运行 hermes doctor", "重新安装")
        ), "")

    def test_summary_rejects_extra_untranslated_claim(self):
        summary = "*Key Updates:*\n• First\n• Second\n\n*更新要点：*\n• 第一条"
        self.assertEqual(_normalize_bilingual_summary(summary), "")

    def test_summary_is_capped_to_six_bilingual_pairs(self):
        english = [f"• English item {index}" for index in range(10)]
        chinese = [f"• 中文要点 {index}" for index in range(10)]
        summary = "\n".join(
            ["*Key Updates:*", *english, "", "*更新要点：*", *chinese]
        )

        normalized = _normalize_bilingual_summary(summary)

        self.assertEqual(normalized.count("• "), 12)
        self.assertNotIn("item 6", normalized)
        self.assertLessEqual(len(normalized), 1800)

    def test_invalid_unpaired_summary_is_rejected(self):
        summary = "*Key Updates:*\n• English only"

        self.assertEqual(_normalize_bilingual_summary(summary), "")


class CompletionClientTests(unittest.TestCase):
    def setUp(self):
        llm._client.cache_clear()
        self.addCleanup(llm._client.cache_clear)

    @patch.dict("os.environ", {"LLM_BASE_URL": "", "LLM_TIMEOUT": ""})
    @patch("openai.OpenAI")
    def test_defaults_to_openrouter_without_sdk_retries(self, openai_cls):
        create = openai_cls.return_value.chat.completions.create
        create.return_value = response("ok")

        result = llm.completion(
            model=MODEL, api_key=API_KEY, messages=[], extra_body={"reasoning": {"effort": "none"}}
        )

        self.assertEqual(result.choices[0].message.content, "ok")
        openai_cls.assert_called_once_with(
            base_url="https://openrouter.ai/api/v1", api_key=API_KEY, max_retries=0
        )
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model"], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(kwargs["timeout"], 300)
        self.assertEqual(kwargs["extra_body"], {"reasoning": {"effort": "none"}})

    @patch.dict("os.environ", {"LLM_BASE_URL": "https://api.deepseek.com/v1/", "LLM_TIMEOUT": "60"})
    @patch("openai.OpenAI")
    def test_base_url_and_timeout_are_configurable(self, openai_cls):
        create = openai_cls.return_value.chat.completions.create
        create.return_value = response("ok")

        llm.completion(model="deepseek-chat", api_key=API_KEY, messages=[])
        llm.completion(model="deepseek-chat", api_key=API_KEY, messages=[])

        openai_cls.assert_called_once_with(
            base_url="https://api.deepseek.com/v1", api_key=API_KEY, max_retries=0
        )
        self.assertEqual(create.call_args.kwargs["model"], "deepseek-chat")
        self.assertEqual(create.call_args.kwargs["timeout"], 60.0)

    @patch("openai.OpenAI")
    def test_error_object_in_ok_response_raises(self, openai_cls):
        openai_cls.return_value.chat.completions.create.return_value = SimpleNamespace(
            error={"code": 402, "message": "Insufficient credits"}, choices=None
        )

        with self.assertRaises(llm.LLMError) as ctx:
            llm.completion(model=MODEL, api_key=API_KEY, messages=[])
        self.assertTrue(llm._is_fatal_error(ctx.exception))

    def test_http_status_errors_are_classified_end_to_end(self):
        """真实走一遍 SDK 的 HTTP 和异常路径，确认致命错误判定仍然生效。"""
        status_code, message = 402, b""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = b'{"error": {"code": %d, "message": "%s"}}' % (status_code, message)
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base_url = f"http://127.0.0.1:{server.server_port}/v1"

        for status_code, message, fatal in (
            (402, b"Insufficient credits", True),
            (503, b"Service temporarily unavailable", False),
        ):
            with self.subTest(status=status_code), patch.dict(
                "os.environ", {"LLM_BASE_URL": base_url, "LLM_TIMEOUT": "5"}
            ):
                with self.assertRaises(Exception) as ctx:
                    llm.completion(model=MODEL, api_key=API_KEY, messages=[])
                self.assertEqual(llm._is_fatal_error(ctx.exception), fatal, str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
