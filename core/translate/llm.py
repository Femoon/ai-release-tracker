#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译模块 - 使用 LiteLLM 调用 LLM API 进行翻译
"""

import os
import re
from litellm import completion


# 翻译质量检查：中文字符最低占比
MIN_CHINESE_RATIO = 0.15  # 15%
# 最大重试次数
MAX_RETRIES = 2


def _count_chinese_chars(text: str) -> int:
    """统计中文字符数量"""
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    return len(chinese_pattern.findall(text))


def _check_translation_quality(translated: str) -> bool:
    """
    检查翻译质量

    Returns:
        bool: True 表示翻译有效，False 表示翻译失败（返回了英文原文）
    """
    if not translated:
        return False

    chinese_count = _count_chinese_chars(translated)
    total_length = len(translated)

    if total_length == 0:
        return False

    chinese_ratio = chinese_count / total_length

    return chinese_ratio >= MIN_CHINESE_RATIO


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

    prompt = f"""请将以下软件更新日志逐条翻译成中文，直接输出翻译结果。

关键要求（必须严格遵守）：
- 逐行翻译，禁止总结、合并或重新组织内容
- 每个列表项（以 - 或 • 开头的行）必须单独翻译，不能合并成段落
- 保持原文的结构和格式不变，翻译后的行数应与原文基本一致
- 不要添加标题、摘要或任何原文没有的内容
- Changelog/commit 条目也必须翻译！格式如 "- fix: xxx" 翻译为 "- fix: 中文描述"，保留前缀(fix/feat/chore等)，翻译描述部分

格式要求：
1. 保持 Markdown 格式不变（标题、列表、代码块等）
2. 版本号、行内代码保持原样
3. 以下内容保留英文原文：
   - commit 类型前缀：fix, feat, chore, docs, refactor, test, style, perf, ci, build, revert
   - GitHub 用户名：@xxx 格式保持不变
   - 通用术语：API, SDK, CLI, Token, Context Window, OAuth, WebSocket, Streaming, LLM, Prompt
   - 功能名称：Agent, Subagent, Sub-agent, Skill, Hook, Plugin, Plan Mode, Compact Mode, Background Task, Memory, TUI, Sandbox, Transcript Mode
   - 斜杠命令：/compact, /context, /permissions, /mcp, /model, /resume, /export, /stats, /init, /prompts, /approvals
   - 工具与概念：MCP, Model Context Protocol, Tool Use, Tool Call, Bash Tool, Permission, Thinking Block, Frontmatter, exec_command, apply_patch, prompt cache, reasoning effort
   - 配置文件：settings.json, CLAUDE.md, config.toml, AGENTS.md, .mcp.json
4. 语言流畅自然，符合中文技术文档习惯
5. 对于不确定的专有名词，保留英文

待翻译内容：
{content}"""

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = completion(
                model=model,
                api_key=api_key,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            if not response.choices or len(response.choices) == 0:
                print("翻译失败: API 返回空结果")
                continue

            translated = response.choices[0].message.content.strip()

            # 检查翻译质量
            if _check_translation_quality(translated):
                chinese_count = _count_chinese_chars(translated)
                chinese_ratio = chinese_count / len(translated) * 100
                print(f"翻译完成 (中文占比: {chinese_ratio:.1f}%)")
                return translated
            else:
                chinese_count = _count_chinese_chars(translated)
                chinese_ratio = chinese_count / len(translated) * 100 if translated else 0
                print(f"翻译质量不合格 (中文占比: {chinese_ratio:.1f}%，要求 >= {MIN_CHINESE_RATIO * 100}%)")
                if attempt < MAX_RETRIES:
                    print(f"重试翻译 ({attempt + 2}/{MAX_RETRIES + 1})...")

        except Exception as e:
            print(f"翻译失败: {e}")
            if attempt < MAX_RETRIES:
                print(f"重试翻译 ({attempt + 2}/{MAX_RETRIES + 1})...")

    print("翻译失败: 已达到最大重试次数")
    return ""
