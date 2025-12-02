#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译模块 - 使用 LiteLLM 调用 OpenRouter 进行翻译
"""

import os
from litellm import completion

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()


def translate_changelog(
    content: str,
    model: str = None,
    api_key: str = None
) -> str:
    """
    翻译更新日志内容

    Args:
        content: 要翻译的英文内容
        model: 模型名称，默认使用环境变量 TRANSLATE_MODEL 或 openrouter/google/gemini-2.5-flash
        api_key: API Key，默认使用环境变量 OPENROUTER_API_KEY

    Returns:
        str: 翻译后的中文内容，失败时返回空字符串
    """
    model = model or os.getenv("TRANSLATE_MODEL", "openrouter/google/gemini-2.5-flash")
    api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    if not api_key:
        print("翻译配置未设置，跳过翻译")
        return ""

    prompt = f"""请将以下软件更新日志翻译成中文。要求：
1. 保持 Markdown 格式不变
2. 技术术语可保留英文（如 API、SDK、CLI 等）
3. 版本号、代码、命令等保持原样
4. 翻译要准确、通顺

原文：
{content}

中文翻译："""

    try:
        response = completion(
            model=model,
            api_key=api_key,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        translated = response.choices[0].message.content.strip()
        print("翻译完成")
        return translated
    except Exception as e:
        print(f"翻译失败: {e}")
        return ""


def format_bilingual(
    version: str,
    original: str,
    translated: str,
    title: str = ""
) -> str:
    """
    格式化双语内容（Markdown 格式，适用于 Telegram）

    Args:
        version: 版本号
        original: 英文原文
        translated: 中文翻译
        title: 标题（如 "Claude Code" 或 "OpenAI Codex"）

    Returns:
        str: 格式化后的双语内容（Markdown）
    """
    import re

    def clean_for_telegram(text, remove_version=False):
        """清理内容，移除 Telegram 不支持的 Markdown 语法"""
        # 移除 ## 标题标记
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        # 移除版本号行（如单独的 "2.0.56" 行）
        if remove_version:
            text = re.sub(r'^\d+\.\d+\.\d+\s*$', '', text, flags=re.MULTILINE)
        # 替换列表符号 "- " 为 "• "
        text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
        # 清理多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    original_clean = clean_for_telegram(original, remove_version=True)
    translated_clean = clean_for_telegram(translated, remove_version=True) if translated else ""

    lines = []

    if title:
        lines.append(f"*{title} {version} Released*")
        lines.append("")

    lines.append(original_clean)

    if translated_clean:
        lines.append("")
        lines.append(translated_clean)

    return "\n".join(lines)
