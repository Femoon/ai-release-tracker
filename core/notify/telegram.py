#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知模块
"""

import os
import re
import requests


def _safe_request_error(error: Exception, bot_token: str = "") -> str:
    """Render network errors without leaking Telegram credentials in URLs."""
    message = str(error)
    if bot_token:
        message = message.replace(bot_token, "<redacted>")
    return message


def escape_markdown(text: str) -> str:
    """
    转义 Telegram Markdown 特殊字符

    Args:
        text: 原始文本

    Returns:
        str: 转义后的文本
    """
    # Telegram Markdown 特殊字符: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r'_*`\[\]()~>#+=|{}.!-'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def process_message_for_markdown_v2(text: str) -> str:
    """Render the supported Markdown subset as valid Telegram MarkdownV2."""
    block_codes = []
    block_placeholder = "TGPRE{}TOKEN"

    def save_block_code(match):
        idx = len(block_codes)
        block_codes.append((match.group(1), match.group(2)))
        return block_placeholder.format(idx)

    text = re.sub(
        r'```([A-Za-z0-9_+.-]*)\n(.*?)```',
        save_block_code,
        text,
        flags=re.DOTALL,
    )

    # Preserve native MarkdownV2 blockquote markers at the start of a line.
    text = re.sub(r'(?m)^>\s?', 'TGBLOCKQUOTETOKEN', text)

    # 先提取并保护超链接 [text](url)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    links = []
    link_placeholder = "TGLINK{}TOKEN"

    def save_link(match):
        idx = len(links)
        links.append((match.group(1), match.group(2)))
        return link_placeholder.format(idx)

    text = re.sub(link_pattern, save_link, text)

    # 提取并保护代码块 `code`
    code_pattern = r'`([^`]+)`'
    codes = []
    code_placeholder = "TGCODE{}TOKEN"

    def save_code(match):
        idx = len(codes)
        codes.append(match.group(1))
        return code_placeholder.format(idx)

    text = re.sub(code_pattern, save_code, text)

    # Common Markdown uses **bold**, while Telegram MarkdownV2 uses *bold*.
    text = re.sub(r'\*\*([^*\n]+)\*\*', r'*\1*', text)
    bolds = []
    bold_placeholder = "TGBOLD{}TOKEN"

    def save_bold(match):
        idx = len(bolds)
        bolds.append(match.group(1))
        return bold_placeholder.format(idx)

    text = re.sub(r'\*([^*\n]+)\*', save_bold, text)
    result = escape_markdown(text)

    for idx, bold_content in enumerate(bolds):
        result = result.replace(
            bold_placeholder.format(idx),
            f'*{escape_markdown(bold_content)}*',
        )

    # 恢复超链接
    for idx, (link_text, link_url) in enumerate(links):
        escaped_text = escape_markdown(link_text)
        placeholder = escape_markdown(link_placeholder.format(idx))
        escaped_url = link_url.replace('\\', '\\\\').replace(')', '\\)')
        result = result.replace(placeholder, f'[{escaped_text}]({escaped_url})')

    # 恢复代码块（代码内容需要转义特殊字符，但保留反引号格式）
    for idx, code_content in enumerate(codes):
        escaped_code = code_content.replace('\\', '\\\\').replace('`', '\\`')
        placeholder = escape_markdown(code_placeholder.format(idx))
        result = result.replace(placeholder, f'`{escaped_code}`')

    for idx, (language, code_content) in enumerate(block_codes):
        escaped_code = code_content.replace('\\', '\\\\').replace('`', '\\`')
        result = result.replace(
            block_placeholder.format(idx),
            f'```{language}\n{escaped_code}```',
        )

    result = result.replace('TGBLOCKQUOTETOKEN', '>')

    return result


def clean_for_telegram(text: str, remove_version: bool = False) -> str:
    """清理内容，移除 Telegram 不支持的 Markdown 语法"""
    blocks = []

    def save_block(match):
        blocks.append(match.group(0))
        return f"TGCLEANPRE{len(blocks) - 1}TOKEN"

    text = re.sub(
        r'```[A-Za-z0-9_+.-]*\n.*?```', save_block, text, flags=re.DOTALL
    )
    # Preserve hierarchy after removing unsupported Markdown heading syntax.
    text = re.sub(r'^#{1,6}\s*(.+)$', r'*\1*', text, flags=re.MULTILINE)
    # 移除版本号行（如单独的 "2.0.56" 行）
    if remove_version:
        text = re.sub(r'^\d+\.\d+\.\d+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*)[-*]\s+', r'\1• ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*(?:---|\*\*\*|___)\s*$', '', text, flags=re.MULTILINE)

    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    for idx, block in enumerate(blocks):
        text = text.replace(f"TGCLEANPRE{idx}TOKEN", block)
    return text


def send_telegram_message(message: str, bot_token: str = None, chat_id: str = None) -> dict:
    """
    发送 Telegram 消息

    Args:
        message: 要发送的消息内容，支持 Markdown 格式
        bot_token: Bot Token，不传则使用环境变量 TELEGRAM_BOT_TOKEN
        chat_id: Chat ID，不传则使用环境变量 TELEGRAM_CHAT_ID

    Returns:
        dict: {"success": bool, "message_id": int or None}
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    # 验证并清理 token
    if bot_token:
        bot_token = bot_token.strip()
    if chat_id:
        chat_id = chat_id.strip()

    if not bot_token or not chat_id:
        print("Telegram 配置未设置，跳过通知")
        return {"success": False, "message_id": None}

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    processed_message = process_message_for_markdown_v2(message)

    data = {
        "chat_id": chat_id,
        "text": processed_message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        result = response.json()
        message_id = result.get("result", {}).get("message_id")
        print(f"Telegram 通知发送成功 (message_id: {message_id})")
        return {"success": True, "message_id": message_id}
    except requests.RequestException as e:
        print(f"Telegram 通知发送失败: {_safe_request_error(e, bot_token)}")
        return {"success": False, "message_id": None}


def edit_telegram_message(
    message_id: int,
    message: str,
    bot_token: str = None,
    chat_id: str = None
) -> dict:
    """
    编辑已发送的 Telegram 消息

    Args:
        message_id: 要编辑的消息 ID
        message: 新的消息内容
        bot_token: Bot Token
        chat_id: Chat ID

    Returns:
        dict: {"success": bool, "message_id": int or None}
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    if bot_token:
        bot_token = bot_token.strip()
    if chat_id:
        chat_id = chat_id.strip()

    if not bot_token or not chat_id:
        print("Telegram 配置未设置，跳过编辑")
        return {"success": False, "message_id": None}

    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"

    processed_message = process_message_for_markdown_v2(message)

    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": processed_message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=data, timeout=10)
        # 先检查响应内容，处理 Telegram API 特定错误
        result = response.json()
        if not result.get("ok"):
            error_desc = result.get("description", "").lower()
            if "message is not modified" in error_desc:
                print("消息内容未变化，无需编辑")
                return {"success": True, "message_id": message_id}
            print(f"Telegram 消息编辑失败: {result.get('description')}")
            return {"success": False, "message_id": None}

        edited_message_id = result.get("result", {}).get("message_id")
        print(f"Telegram 消息编辑成功 (message_id: {edited_message_id})")
        return {"success": True, "message_id": edited_message_id}
    except requests.RequestException as e:
        print(f"Telegram 消息编辑失败: {_safe_request_error(e, bot_token)}")
        return {"success": False, "message_id": None}


# Telegram 消息长度限制
MAX_MESSAGE_LENGTH = 4096


def _build_bilingual_messages(
    version: str,
    original: str,
    translated: str,
    title: str,
    version_url: str = None,
    show_language_labels: bool = False,
) -> dict:
    """
    构建双语消息内容（内部辅助函数）

    Returns:
        dict: {
            "en_message": str,      # 英文消息
            "cn_message": str,      # 中文消息
            "combined_message": str, # 合并消息
            "is_oversized": bool,   # 合并消息是否超长
            "en_title": str,        # 英文标题
            "cn_title": str         # 中文标题
        }
    """
    # 清理内容
    original_clean = clean_for_telegram(original, remove_version=True)
    translated_clean = clean_for_telegram(translated, remove_version=True) if translated else ""
    original_en = original_clean.replace('链接:', 'Source:')

    # 构建标题
    if version_url:
        en_title = f"*{title} [{version}]({version_url}) Released*"
        cn_title = f"*{title} [{version}]({version_url}) 发布*"
    else:
        en_title = f"*{title} {version} Released*"
        cn_title = f"*{title} {version} 发布*"

    # 构建英文消息
    en_content = ["*English*", "", original_en] if show_language_labels else [original_en]
    en_lines = [en_title, "", *en_content] if title else en_content
    en_message = "\n".join(en_lines)

    # 构建中文消息
    cn_content = translated_clean if translated_clean else "（无翻译）"
    cn_content_lines = ["*中文*", "", cn_content] if show_language_labels else [cn_content]
    cn_lines = [cn_title, "", *cn_content_lines] if title else cn_content_lines
    cn_message = "\n".join(cn_lines)

    # 构建合并消息
    combined_lines = [en_title, "", *en_content] if title else en_content
    if translated_clean:
        combined_lines.extend(["", *cn_content_lines])
    combined_message = "\n".join(combined_lines)

    # 检测消息长度
    processed_combined = process_message_for_markdown_v2(combined_message)
    is_oversized = len(processed_combined) > MAX_MESSAGE_LENGTH

    return {
        "en_message": en_message,
        "cn_message": cn_message,
        "combined_message": combined_message,
        "is_oversized": is_oversized,
        "combined_length": len(processed_combined),
        "en_title": en_title,
        "cn_title": cn_title
    }


def send_bilingual_notification(
    version: str,
    original: str,
    translated: str,
    title: str,
    bot_token: str = None,
    chat_id: str = None,
    version_url: str = None,
    show_language_labels: bool = False,
    content_kind: str = "notes",
) -> dict:
    """
    发送双语通知，自动处理长度限制

    处理策略:
    - 如果双语合并后 <= 4096 字符，发送一条消息
    - 如果合并超长（> 4096），发布到 Telegraph，发送标题 + AI 总结 + 链接

    Args:
        version: 版本号
        original: 英文原文
        translated: 中文翻译
        title: 标题（如 "Claude Code" 或 "OpenAI Codex"）
        bot_token: Bot Token
        chat_id: Chat ID
        version_url: 版本链接（可选，用于生成超链接标题）

    Returns:
        dict: {"success": bool, "message_ids": list[int], "telegraph_url": str | None}
    """
    msgs = _build_bilingual_messages(
        version,
        original,
        translated,
        title,
        version_url,
        show_language_labels,
    )

    # 消息超长，使用 Telegraph + AI 总结
    if msgs["is_oversized"]:
        print(f"消息超长 ({msgs['combined_length']} 字符)，发布到 Telegraph")

        from core.notify.telegraph import publish_changelog
        from core.translate.llm import summarize_changelog

        # Telegraph：发布完整中英文对照（上游已去掉 Changelog）
        telegraph_result = publish_changelog(
            title=title,
            original=original,
            translated=translated,
            version=version,
            source_url=version_url,
            content_kind=content_kind,
        )

        if not telegraph_result["success"]:
            print("Telegraph 发布失败，无法发送通知")
            return {"success": False, "message_ids": [], "telegraph_url": None}

        telegraph_url = telegraph_result["url"]
        cn_url = telegraph_result.get("cn_url")

        # TG 消息：AI 生成简短总结 + Telegraph 链接
        summary = summarize_changelog(original)

        if cn_url and content_kind == "highlights":
            link_line = (
                f"\n\n[English highlights]({telegraph_url}) | [中文高光]({cn_url})"
            )
        elif cn_url:
            link_line = f"\n\n[English notes]({telegraph_url}) | [中文说明]({cn_url})"
        elif content_kind == "highlights":
            link_line = f"\n\n[View bilingual highlights | 查看双语高光]({telegraph_url})"
        else:
            link_line = f"\n\n[View release notes | 查看版本说明]({telegraph_url})"
        if version_url:
            link_line += f" | [GitHub]({version_url})"

        if summary:
            message = f"{msgs['en_title']}\n\n{summary}{link_line}"
        else:
            message = f"{msgs['en_title']}{link_line}"

        result = send_telegram_message(message, bot_token, chat_id)
        message_ids = [result["message_id"]] if result["message_id"] else []

        return {
            "success": result["success"],
            "message_ids": message_ids,
            "telegraph_url": telegraph_url
        }

    # 长度在限制内，发送合并消息
    result = send_telegram_message(msgs["combined_message"], bot_token, chat_id)
    message_ids = [result["message_id"]] if result["message_id"] else []
    return {"success": result["success"], "message_ids": message_ids, "telegraph_url": None}


def edit_bilingual_notification(
    message_ids: list,
    version: str,
    original: str,
    translated: str,
    title: str,
    bot_token: str = None,
    chat_id: str = None,
    version_url: str = None,
    show_language_labels: bool = False,
    content_kind: str = "notes",
) -> dict:
    """
    编辑已发送的双语通知

    处理策略:
    - 内容超长（> 4096）: 发布到 Telegraph，编辑为短链接消息
    - 内容不超长: 直接编辑合并消息
    - 兼容旧的2条消息状态: 第一条编辑为内容，第二条编辑为提示

    Args:
        message_ids: 要编辑的消息 ID 列表（1个或2个）
        version: 版本号
        original: 英文原文
        translated: 中文翻译
        title: 标题
        bot_token: Bot Token
        chat_id: Chat ID
        version_url: 版本链接

    Returns:
        dict: {"success": bool, "message_ids": list[int]}
    """
    if not message_ids:
        print("没有可编辑的消息 ID")
        return {"success": False, "message_ids": []}

    msgs = _build_bilingual_messages(
        version,
        original,
        translated,
        title,
        version_url,
        show_language_labels,
    )

    # 消息超长，改用 Telegraph 处理
    if msgs["is_oversized"]:
        print(f"消息超长 ({msgs['combined_length']} 字符)，发布到 Telegraph")

        from core.notify.telegraph import publish_changelog
        from core.translate.llm import summarize_changelog

        telegraph_result = publish_changelog(
            title=title,
            original=original,
            translated=translated,
            version=version,
            source_url=version_url,
            content_kind=content_kind,
        )

        if not telegraph_result["success"]:
            print("Telegraph 发布失败，无法编辑通知")
            return {"success": False, "message_ids": []}

        telegraph_url = telegraph_result["url"]
        cn_url = telegraph_result.get("cn_url")

        # AI 生成简短总结
        summary = summarize_changelog(original)

        if cn_url and content_kind == "highlights":
            link_line = (
                f"\n\n[English highlights]({telegraph_url}) | [中文高光]({cn_url})"
            )
        elif cn_url:
            link_line = f"\n\n[English notes]({telegraph_url}) | [中文说明]({cn_url})"
        elif content_kind == "highlights":
            link_line = f"\n\n[View bilingual highlights | 查看双语高光]({telegraph_url})"
        else:
            link_line = f"\n\n[View release notes | 查看版本说明]({telegraph_url})"
        if version_url:
            link_line += f" | [GitHub]({version_url})"

        if summary:
            short_message = f"{msgs['en_title']}\n\n{summary}{link_line}"
        else:
            short_message = f"{msgs['en_title']}{link_line}"

        edit_results = []
        for idx, message_id in enumerate(message_ids):
            if idx == 0:
                edit_results.append(edit_telegram_message(message_id, short_message, bot_token, chat_id))
            else:
                merge_notice = f"*{title} {version}*\n\n已合并至上一条消息 ↑"
                edit_results.append(edit_telegram_message(message_id, merge_notice, bot_token, chat_id))

        success = all(result["success"] for result in edit_results)
        return {
            "success": success,
            "message_ids": message_ids if success else [],
            "telegraph_url": telegraph_url if success else None,
        }

    # 内容不超长，编辑合并消息
    is_single_message = len(message_ids) == 1

    if is_single_message:
        # 单条消息，直接编辑为合并内容
        result = edit_telegram_message(message_ids[0], msgs["combined_message"], bot_token, chat_id)
        return {
            "success": result["success"],
            "message_ids": message_ids if result["success"] else [],
            "telegraph_url": None,
        }

    # 兼容旧的2条消息状态: 第一条编辑为合并内容，第二条编辑为提示
    result1 = edit_telegram_message(message_ids[0], msgs["combined_message"], bot_token, chat_id)
    merge_notice = f"*{title} {version}*\n\n已合并至上一条消息 ↑"
    result2 = edit_telegram_message(message_ids[1], merge_notice, bot_token, chat_id)

    return {
        "success": result1["success"] and result2["success"],
        "message_ids": message_ids,
        "telegraph_url": None,
    }
