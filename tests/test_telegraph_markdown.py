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

from core.notify.telegraph import html_to_nodes, markdown_to_html


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
