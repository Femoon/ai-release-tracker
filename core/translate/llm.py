#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译模块 - 使用 LiteLLM 调用 OpenRouter 进行翻译
"""

import os
from litellm import completion


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
        if not response.choices or len(response.choices) == 0:
            print("翻译失败: API 返回空结果")
            return ""
        translated = response.choices[0].message.content.strip()
        print("翻译完成")
        return translated
    except Exception as e:
        print(f"翻译失败: {e}")
        return ""
