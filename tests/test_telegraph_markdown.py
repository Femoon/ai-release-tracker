#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegraph Markdown -> HTML -> Node 转换回归测试

覆盖 Claude Code 2.1.251 暴露的三个渲染 bug：
1. 行内代码两侧空格被吞
2. 行内代码里的下划线被当成斜体
3. 代码里的尖括号内容被当成 HTML 标签吃掉
"""

import unittest
from unittest.mock import patch

from core.notify.telegraph import html_to_nodes, markdown_to_html, publish_changelog


def _flatten(nodes) -> str:
    """把 Telegraph Node 数组还原成纯文本，用于断言最终渲染结果"""
    parts = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
        else:
            parts.append(_flatten(node.get("children", [])))
    return "".join(parts)


def _render(markdown: str) -> str:
    """走完整链路（markdown_to_html -> html_to_nodes）后取纯文本"""
    return _flatten(html_to_nodes(markdown_to_html(markdown)))


class TelegraphInlineCodeTests(unittest.TestCase):
    """bug 1：行内代码两侧的空格必须保留"""

    def test_spaces_around_inline_code_preserved(self):
        markdown = "- Added `PreModelSwitch` and `PostModelSwitch` hook events"
        html = markdown_to_html(markdown)
        self.assertIn(
            "Added <code>PreModelSwitch</code> and <code>PostModelSwitch</code> hook events",
            html
        )
        self.assertEqual(
            "Added PreModelSwitch and PostModelSwitch hook events",
            _render(markdown)
        )

    def test_spaces_around_inline_code_in_paragraph(self):
        markdown = "Moved to `/usage` and added a new panel"
        self.assertEqual("Moved to /usage and added a new panel", _render(markdown))

    def test_spaces_preserved_with_chinese_text(self):
        markdown = "- 修复了 `/usage` 与 `/status` 的显示问题"
        self.assertEqual("修复了 /usage 与 /status 的显示问题", _render(markdown))


class TelegraphCodeEmphasisTests(unittest.TestCase):
    """bug 2：行内代码里的下划线不能被当成强调语法"""

    def test_underscores_in_inline_code_are_literal(self):
        markdown = "- Added `rate_limits.spend_limit` field"
        html = markdown_to_html(markdown)
        self.assertIn("<code>rate_limits.spend_limit</code>", html)
        self.assertNotIn("<i>", html)
        self.assertNotIn("<em>", html)
        self.assertEqual("Added rate_limits.spend_limit field", _render(markdown))

    def test_double_underscores_in_inline_code_are_literal(self):
        markdown = "- Renamed `__main__` and `snake_case_name` symbols"
        html = markdown_to_html(markdown)
        self.assertIn("<code>__main__</code>", html)
        self.assertIn("<code>snake_case_name</code>", html)
        self.assertNotIn("<b>", html)

    def test_asterisks_in_inline_code_are_literal(self):
        markdown = "- Support `**/*.ts` globs"
        self.assertEqual("Support **/*.ts globs", _render("- Support `**/*.ts` globs"))
        self.assertIn("<code>**/*.ts</code>", markdown_to_html(markdown))

    def test_plain_identifiers_do_not_create_cross_text_italics(self):
        markdown = "run_agent.py became faster and session_search is now free"
        html = markdown_to_html(markdown)

        self.assertNotIn("<i>", html)
        self.assertEqual(markdown, _render(markdown))


class TelegraphEscapeTests(unittest.TestCase):
    """bug 3：尖括号等 HTML 特殊字符必须转义，不能丢内容"""

    def test_angle_brackets_in_inline_code_survive(self):
        markdown = "- Fixed a crash in `claude attach <id>`"
        html = markdown_to_html(markdown)
        self.assertIn("<code>claude attach &lt;id&gt;</code>", html)
        self.assertEqual("Fixed a crash in claude attach <id>", _render(markdown))

    def test_angle_brackets_in_plain_text_survive(self):
        markdown = "- Use <name> as the placeholder & keep it"
        html = markdown_to_html(markdown)
        self.assertIn("&lt;name&gt;", html)
        self.assertIn("&amp;", html)
        self.assertEqual("Use <name> as the placeholder & keep it", _render(markdown))

    def test_code_block_escapes_and_keeps_content(self):
        markdown = "```bash\nclaude attach <id> && echo done\n```"
        html = markdown_to_html(markdown)
        self.assertIn("<pre>claude attach &lt;id&gt; &amp;&amp; echo done</pre>", html)
        # 代码块是块级元素，不应被包进 <p>
        self.assertNotIn("<p><pre>", html)
        self.assertEqual("claude attach <id> && echo done", _render(markdown))

    def test_table_like_text_inside_code_block_is_not_converted(self):
        markdown = "```text\n| A | B |\n| --- | --- |\n| 1 | 2 |\n```"

        html = markdown_to_html(markdown)

        self.assertIn("<pre>| A | B |\n| --- | --- |\n| 1 | 2 |</pre>", html)
        self.assertNotIn("<ul>", html)

    def test_hyphenated_fence_language_is_recognized(self):
        markdown = "```objective-c\nvalue_with_underscore();\n```"

        html = markdown_to_html(markdown)

        self.assertIn("<pre>value_with_underscore();</pre>", html)
        self.assertNotIn("<code>objective-c", html)


class TelegraphMarkdownFeatureTests(unittest.TestCase):
    """现有 Markdown 特性不回归"""

    def test_headings(self):
        html = markdown_to_html("# T1\n## T2\n### T3")
        self.assertIn("<h3>T1</h3>", html)
        self.assertIn("<h3>T2</h3>", html)
        self.assertIn("<h4>T3</h4>", html)

    def test_bold_and_italic(self):
        html = markdown_to_html("This is **bold** and *italic* and _also italic_")
        self.assertIn("<b>bold</b>", html)
        self.assertIn("<i>italic</i>", html)
        self.assertIn("<i>also italic</i>", html)

    def test_unordered_list_grouped_into_ul(self):
        html = markdown_to_html("- one\n- two\n\nafter")
        self.assertIn("<ul><li>one</li><li>two</li></ul>", html)
        self.assertIn("<p>after</p>", html)

    def test_blockquote_and_horizontal_rule_are_structural(self):
        html = markdown_to_html("> A release summary\n\n---\n\nafter")
        nodes = html_to_nodes(html)

        self.assertIn("<blockquote>A release summary</blockquote>", html)
        self.assertIn("<hr>", html)
        self.assertEqual(["blockquote", "hr", "p"], [node["tag"] for node in nodes])

    def test_pipe_table_becomes_readable_list(self):
        markdown = "| Metric | Value |\n| --- | --- |\n| Commits | 180 |"
        html = markdown_to_html(markdown)

        self.assertIn("<ul>", html)
        self.assertIn("<b>Metric:</b> Commits", html)
        self.assertIn("<b>Value:</b> 180", html)

    def test_pipe_inside_inline_code_stays_in_one_table_cell(self):
        markdown = "| Setting | Value |\n| --- | --- |\n| Mode | `fast|safe` |"

        html = markdown_to_html(markdown)

        self.assertIn("<b>Value:</b> <code>fast|safe</code>", html)

    def test_link_and_query_string(self):
        markdown = "See [docs](https://example.com/a?x=1&y=2) for details"
        nodes = html_to_nodes(markdown_to_html(markdown))
        hrefs = _collect_hrefs(nodes)
        self.assertEqual(["https://example.com/a?x=1&y=2"], hrefs)
        self.assertEqual("See docs for details", _render(markdown))

    def test_mixed_changelog_snippet(self):
        markdown = (
            "## 2.1.251\n"
            "\n"
            "- Added `PreModelSwitch` and `PostModelSwitch` hook events\n"
            "- Added `rate_limits.spend_limit` field\n"
            "- Fixed `claude attach <id>` crash\n"
            "\n"
            "**Breaking**: 见 [文档](https://example.com/docs)\n"
        )
        html = markdown_to_html(markdown)
        self.assertIn("<h3>2.1.251</h3>", html)
        self.assertIn("<b>Breaking</b>", html)
        rendered = _render(markdown)
        self.assertIn("Added PreModelSwitch and PostModelSwitch hook events", rendered)
        self.assertIn("Added rate_limits.spend_limit field", rendered)
        self.assertIn("Fixed claude attach <id> crash", rendered)

    @patch("core.notify.telegraph.create_page")
    def test_publish_labels_languages_and_links_complete_source(self, mock_create):
        mock_create.return_value = {
            "success": True,
            "url": "https://telegra.ph/example",
            "path": "example",
            "error": None,
        }

        publish_changelog(
            title="Hermes Agent",
            version="v0.21.0",
            original="## Highlights\n- Bot Mode",
            translated="## 亮点\n- Bot 模式",
            source_url="https://github.com/example/release",
            content_kind="highlights",
        )

        page_title, content_html = mock_create.call_args.args[:2]
        self.assertEqual(page_title, "Hermes Agent v0.21.0 Release Highlights")
        self.assertIn("<h3>English</h3>", content_html)
        self.assertIn("<h3>中文</h3>", content_html)
        self.assertIn("https://github.com/example/release", content_html)


def _collect_hrefs(nodes) -> list:
    """递归收集 Node 树里的链接地址"""
    hrefs = []
    for node in nodes:
        if isinstance(node, str):
            continue
        attrs = node.get("attrs") or {}
        if "href" in attrs:
            hrefs.append(attrs["href"])
        hrefs.extend(_collect_hrefs(node.get("children", [])))
    return hrefs


if __name__ == "__main__":
    unittest.main()
