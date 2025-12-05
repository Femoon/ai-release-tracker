# -*- coding: utf-8 -*-
"""
Release body 清理工具函数
用于清理 GitHub release notes 中的无关内容
"""

import re


def clean_release_body(body: str) -> str:
    """
    清理 release body 内容

    移除：
    - PR 列表标题及后续内容
    - Full Changelog 行
    - PR 列表行（各种格式）
    - 内联 PR/Issue 引用
    - PR/Issue 链接
    - 残留的引用文本

    转换：
    - @用户名 转为 GitHub 超链接

    Args:
        body: 原始 release body 文本

    Returns:
        清理后的文本
    """
    if not body:
        return ""

    clean = body

    # 移除各种 PR 列表标题及后面所有内容
    pr_title_patterns = [
        r'\n[-#]*\s*Full list of merged PRs.*',
        r'\n[-#]*\s*Merged PRs.*',
        r'\n[-#]*\s*All merged PRs.*',
        r'\n[-#]*\s*List of merged PRs.*',
        r'\n[-#]*\s*PRs Merged.*',
        r'\n#+\s*PRs\s*\n.*',  # ### PRs 后跟换行
    ]
    for pattern in pr_title_patterns:
        clean = re.sub(pattern, '', clean, flags=re.DOTALL | re.IGNORECASE)

    # 移除 Full Changelog 行
    clean = re.sub(r'\*?\*?Full Changelog\*?\*?:?.*', '', clean, flags=re.IGNORECASE)

    # 移除 PR 列表行（各种格式）
    clean = re.sub(r'^[-*]\s+.*(?:by @|— @).*(?:in #\d+|#\d+).*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^[-*]\s+.*\(#\d+\)\s*—\s*@.*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^#\d+\s+[–—-]\s+.*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^[-*]\s+PR\s*$', '', clean, flags=re.MULTILINE)  # 单独的 "- PR" 行

    # 移除内联的 PR/Issue 引用（如 #6222, (#6189)）
    clean = re.sub(r'\s*\(#\d+(?:\s+#\d+)*\)', '', clean)
    clean = re.sub(r'#\d+(?:\s+#\d+)*', '', clean)

    # 移除 PR/Issue 链接
    clean = re.sub(r'https://github\.com/openai/codex/pull/\d+', '', clean)
    clean = re.sub(r'https://github\.com/openai/codex/issues/\d+', '', clean)

    # 清理残留的引用文本
    clean = re.sub(r'See\s+for details\.?', '', clean)
    clean = re.sub(r'As of\s*,\s*', '', clean)
    clean = re.sub(r'\s+in\s+so\s+', ' so ', clean)
    clean = re.sub(r'\s+in\s*,', ',', clean)
    clean = re.sub(r'\s+in\s*\)', ')', clean)
    clean = re.sub(r'\s+in\s+because', ' because', clean)
    clean = re.sub(r'\s+in\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'thanks to\s*$', '', clean, flags=re.MULTILINE | re.IGNORECASE)
    clean = re.sub(r'fixing\s*\.?\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'\s*\(was the relevant GitHub issue\)\s*', ' ', clean)
    clean = re.sub(r'gracefully\s+- ', 'gracefully\n- ', clean)
    clean = re.sub(r'though from the additional details on\s*,', 'though', clean)
    clean = re.sub(r'Though\s+should', 'Though it should', clean)
    clean = re.sub(r'reverted\s*,\s*fixing', 'reverted the previous change, fixing', clean)

    # 清理行首的空引用
    clean = re.sub(r'^-\s+\s+', '- ', clean, flags=re.MULTILINE)
    clean = re.sub(r'^\*\s+\s+', '* ', clean, flags=re.MULTILINE)

    # 将 GitHub @用户名 转换为超链接
    clean = re.sub(r'@(\w[\w-]*)', r'[@\1](https://github.com/\1)', clean)

    # 清理多余空白和标点
    clean = re.sub(r'\s*:\s*\.?\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'\s+\)', ')', clean)
    clean = re.sub(r'\(\s+', '(', clean)
    clean = re.sub(r'\([\s,]*\)', '', clean)  # 移除空括号和仅含逗号的括号如 (,) (, , ,)
    clean = re.sub(r'\s+:', ':', clean)  # 移除冒号前的多余空格
    clean = re.sub(r',\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'[^\S\n]{2,}', ' ', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)

    # 统一列表符号为 -（兼容 Windows GBK 终端）
    clean = re.sub(r'^[*]\s+', '- ', clean, flags=re.MULTILINE)

    # 删除列表项之间的空行
    clean = re.sub(r'\n\n+(?=- )', '\n', clean)

    return clean.strip()
