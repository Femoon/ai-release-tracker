#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegraph 发布模块

用于将超长内容发布到 Telegraph，并返回文章链接
"""

import json
import os
import re

import requests

# Telegraph API 基础 URL
TELEGRAPH_API = "https://api.telegra.ph"


def get_token() -> str | None:
    """
    获取 Telegraph access_token

    从环境变量 TELEGRAPH_ACCESS_TOKEN 读取

    Returns:
        str | None: access_token，未配置返回 None
    """
    token = os.getenv("TELEGRAPH_ACCESS_TOKEN", "").strip()
    if not token:
        print("Telegraph 配置未设置（TELEGRAPH_ACCESS_TOKEN），跳过发布")
        return None
    return token


def markdown_to_html(text: str) -> str:
    """
    将 Markdown 格式转换为 Telegraph 支持的 HTML

    Telegraph 支持的标签:
    a, aside, b, blockquote, br, code, em, figcaption, figure,
    h3, h4, hr, i, iframe, img, li, ol, p, pre, s, strong, u, ul, video

    Args:
        text: Markdown 格式文本

    Returns:
        str: HTML 格式文本
    """
    # 处理标题 ## -> <h3>, ### -> <h4>
    text = re.sub(r'^## (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)

    # 处理代码块 ```code``` -> <pre>code</pre>
    text = re.sub(r'```[\w]*\n(.*?)\n```', r'<pre>\1</pre>', text, flags=re.DOTALL)

    # 处理行内代码 `code` -> <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 处理粗体 **text** 或 __text__ -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 处理斜体 *text* 或 _text_ -> <i>text</i>
    # 注意：需要避免与粗体冲突，只匹配单个 * 或 _
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)

    # 处理链接 [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 处理无序列表
    # 先找出连续的列表项，包装成 <ul>
    lines = text.split('\n')
    result_lines = []
    in_list = False
    list_items = []

    for line in lines:
        # 检查是否是列表项 (- 或 •)
        list_match = re.match(r'^[-•]\s+(.+)$', line)
        if list_match:
            if not in_list:
                in_list = True
                list_items = []
            list_items.append(f"<li>{list_match.group(1)}</li>")
        else:
            if in_list:
                # 结束列表
                result_lines.append("<ul>" + "".join(list_items) + "</ul>")
                in_list = False
                list_items = []
            # 处理普通段落（非空行且不是标签）
            stripped = line.strip()
            if stripped and not stripped.startswith('<'):
                result_lines.append(f"<p>{stripped}</p>")
            elif stripped:
                result_lines.append(stripped)

    # 处理最后可能未结束的列表
    if in_list:
        result_lines.append("<ul>" + "".join(list_items) + "</ul>")

    return "\n".join(result_lines)


def create_page(
    title: str,
    content_html: str,
    access_token: str | None = None,
    author_name: str | None = None,
    author_url: str | None = None
) -> dict:
    """
    创建 Telegraph 页面

    Args:
        title: 文章标题 (1-256字符)
        content_html: HTML 格式内容
        access_token: Telegraph access_token
        author_name: 作者名
        author_url: 作者链接

    Returns:
        dict: {"success": bool, "url": str | None, "path": str | None}
    """
    token = access_token or get_token()
    if not token:
        return {"success": False, "url": None, "path": None}

    author_name = author_name or os.getenv("TELEGRAPH_AUTHOR_NAME", "AI Release Tracker")
    author_url = author_url or os.getenv("TELEGRAPH_AUTHOR_URL", "")

    # 将 HTML 转换为 Telegraph Node 格式
    content = html_to_nodes(content_html)

    data = {
        "access_token": token,
        "title": title,
        "content": json.dumps(content),
        "author_name": author_name,
        "return_content": False,
    }
    if author_url:
        data["author_url"] = author_url

    try:
        response = requests.post(f"{TELEGRAPH_API}/createPage", data=data, timeout=30)
        result = response.json()

        if result.get("ok"):
            page = result["result"]
            print(f"Telegraph 文章发布成功: {page['url']}")
            return {
                "success": True,
                "url": page["url"],
                "path": page["path"],
                "error": None
            }
        else:
            error = result.get("error", "UNKNOWN_ERROR")
            print(f"Telegraph 文章发布失败: {error}")
            return {"success": False, "url": None, "path": None, "error": error}
    except requests.RequestException as e:
        print(f"Telegraph API 请求失败: {e}")
        return {"success": False, "url": None, "path": None, "error": str(e)}


def html_to_nodes(html: str) -> list:
    """
    将 HTML 字符串转换为 Telegraph Node 格式

    简化实现：按标签拆分，转换为 Node 数组

    Args:
        html: HTML 格式字符串

    Returns:
        list: Telegraph Node 数组
    """
    nodes = []

    # 简单的 HTML 标签解析正则
    tag_pattern = re.compile(r'<(h3|h4|p|ul|li|pre|code|b|i|a)([^>]*)>(.*?)</\1>|<(hr|br)\s*/?>|([^<]+)', re.DOTALL)

    for match in tag_pattern.finditer(html):
        if match.group(1):  # 有内容的标签
            tag = match.group(1)
            attrs_str = match.group(2)
            inner = match.group(3)

            node = {"tag": tag}

            # 解析属性（主要是 href）
            if attrs_str:
                href_match = re.search(r'href=["\']([^"\']+)["\']', attrs_str)
                if href_match:
                    node["attrs"] = {"href": href_match.group(1)}

            # 递归处理子内容
            if tag == "ul":
                # 列表项需要特殊处理
                li_pattern = re.compile(r'<li>(.*?)</li>', re.DOTALL)
                children = []
                for li_match in li_pattern.finditer(inner):
                    li_content = li_match.group(1)
                    # 如果内容包含 HTML 标签，递归处理；否则直接使用文本
                    if "<" in li_content:
                        li_children = html_to_nodes(li_content)
                    else:
                        li_children = [li_content] if li_content else []
                    children.append({"tag": "li", "children": li_children})
                node["children"] = children
            elif "<" in inner:
                # 内部还有标签，递归处理
                node["children"] = html_to_nodes(inner)
            else:
                # 纯文本
                node["children"] = [inner] if inner else []

            nodes.append(node)
        elif match.group(4):  # 自闭合标签 (hr, br)
            tag = match.group(4)
            nodes.append({"tag": tag})
        elif match.group(5):  # 纯文本
            text = match.group(5).strip()
            if text:
                nodes.append(text)

    return nodes


# 产品作者信息映射
PRODUCT_AUTHORS = {
    "Claude Code": {
        "name": "Claude Code Changelog",
        "url": "https://t.me/claude_code_push"
    },
    "Codex": {
        "name": "Codex Changelog",
        "url": "https://t.me/codex_push"
    }
}


def _strip_changelog_section(text: str) -> str:
    """
    移除 Markdown 文本中的 Changelog 详细提交列表部分

    匹配以 "Changelog" 开头的标题（可带 ** 加粗或 # 标记）及其后续内容并移除。

    Args:
        text: Markdown 格式文本

    Returns:
        str: 截断后的文本
    """
    # 匹配 Changelog / **Changelog** / ## Changelog 等标题及其后续所有内容
    truncated = re.sub(
        r'(?m)^(?:\*{0,2}#{0,4}\s*Changelog\s*\*{0,2})\s*\n.*',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    return truncated.rstrip()


def publish_changelog(
    title: str,
    original: str,
    translated: str = None,
    version: str = None
) -> dict:
    """
    发布双语更新日志到 Telegraph

    如果内容过大（CONTENT_TOO_BIG），会自动截掉 Changelog 详细提交列表后重试。

    Args:
        title: 产品名称 (如 "Claude Code")
        original: 英文原文 (Markdown 格式)
        translated: 中文翻译 (Markdown 格式)，可选
        version: 版本号，可选

    Returns:
        dict: {"success": bool, "url": str | None}
    """
    # 构建文章标题
    page_title = f"{title} {version} Release Notes" if version else f"{title} Release Notes"

    # 获取产品对应的作者信息
    author_info = PRODUCT_AUTHORS.get(title, {})
    author_name = author_info.get("name")
    author_url = author_info.get("url")

    def _build_html(orig: str, trans: str = None) -> str:
        parts = [markdown_to_html(orig)]
        if trans:
            parts.append("<hr>")
            parts.append(markdown_to_html(trans))
        return "\n".join(parts)

    # 第一次尝试：完整内容
    content_html = _build_html(original, translated)
    result = create_page(page_title, content_html, author_name=author_name, author_url=author_url)

    if result["success"] or result.get("error") != "CONTENT_TOO_BIG":
        return result

    # 第二次尝试：截掉 Changelog 部分后重试
    trimmed_original = _strip_changelog_section(original)
    trimmed_translated = _strip_changelog_section(translated) if translated else None
    print("内容过大，截掉 Changelog 详细列表后重试 Telegraph 发布...")

    content_html = _build_html(trimmed_original, trimmed_translated)
    return create_page(page_title, content_html, author_name=author_name, author_url=author_url)
