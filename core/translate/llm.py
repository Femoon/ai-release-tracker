#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译模块 - 使用 LiteLLM 调用 LLM API 进行翻译
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
        model: 模型名称，默认使用环境变量 LLM_MODEL 或 openrouter/google/gemini-2.5-flash
        api_key: API Key，默认使用环境变量 LLM_API_KEY

    Returns:
        str: 翻译后的中文内容，失败时返回空字符串
    """
    model = model or os.getenv("LLM_MODEL", "openrouter/google/gemini-2.5-flash")
    api_key = api_key or os.getenv("LLM_API_KEY", "")

    if not api_key:
        print("翻译配置未设置，跳过翻译")
        return ""

    prompt = f"""请将以下软件更新日志翻译成中文，直接输出翻译结果，不要输出任何解释或前缀。

翻译要求：
1. 保持 Markdown 格式不变（标题、列表、代码块等）
2. 版本号、代码片段、命令保持原样
3. 以下术语必须保留英文原文，不要翻译：
   - 通用术语：API, SDK, CLI, Token, Context Window, OAuth, WebSocket, Streaming, LLM, Prompt
   - 功能名称：Agent, Subagent, Sub-agent, Skill, Hook, Plugin, Plan Mode, Compact Mode, Background Task, Memory, TUI, Sandbox, Transcript Mode
   - 命令：/compact, /context, /permissions, /mcp, /model, /resume, /export, /stats, /init, /prompts, /approvals
   - 工具与概念：MCP, Model Context Protocol, Tool Use, Tool Call, Bash Tool, Permission, Thinking Block, Frontmatter, exec_command, apply_patch, prompt cache, reasoning effort
   - 配置文件：settings.json, CLAUDE.md, config.toml, AGENTS.md, .mcp.json
4. 语言流畅自然，符合中文技术文档习惯
5. 对于不确定的专有名词，保留英文

待翻译内容：
{content}"""

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
