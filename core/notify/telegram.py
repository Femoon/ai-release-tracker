#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知模块
"""

import os
import re
import requests


def escape_markdown(text: str) -> str:
    """
    转义 Telegram Markdown 特殊字符

    Args:
        text: 原始文本

    Returns:
        str: 转义后的文本
    """
    # Telegram Markdown 特殊字符: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # 但我们只转义最常见的问题字符，保留 * 用于粗体
    escape_chars = r'_`\[\]()~>#+=|{}.!-'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def process_message_for_markdown_v2(text: str) -> str:
    """处理消息，保留粗体标记、超链接和代码块，转义其他特殊字符"""
    # 先提取并保护超链接 [text](url)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    links = []
    link_placeholder = "\x00LINK{}\x00"

    def save_link(match):
        idx = len(links)
        links.append((match.group(1), match.group(2)))
        return link_placeholder.format(idx)

    text = re.sub(link_pattern, save_link, text)

    # 提取并保护代码块 `code`
    code_pattern = r'`([^`]+)`'
    codes = []
    code_placeholder = "\x01CODE{}\x01"

    def save_code(match):
        idx = len(codes)
        codes.append(match.group(1))
        return code_placeholder.format(idx)

    text = re.sub(code_pattern, save_code, text)

    # 处理粗体
    bold_pattern = r'\*([^*]+)\*'
    parts = []
    last_end = 0

    for match in re.finditer(bold_pattern, text):
        before_text = text[last_end:match.start()]
        parts.append(escape_markdown(before_text))
        bold_content = match.group(1)
        escaped_bold = escape_markdown(bold_content)
        parts.append(f'*{escaped_bold}*')
        last_end = match.end()

    parts.append(escape_markdown(text[last_end:]))
    result = ''.join(parts)

    # 恢复超链接
    for idx, (link_text, link_url) in enumerate(links):
        escaped_text = escape_markdown(link_text)
        placeholder = escape_markdown(link_placeholder.format(idx))
        result = result.replace(placeholder, f'[{escaped_text}]({link_url})')

    # 恢复代码块（代码内容需要转义特殊字符，但保留反引号格式）
    for idx, code_content in enumerate(codes):
        escaped_code = escape_markdown(code_content)
        placeholder = escape_markdown(code_placeholder.format(idx))
        result = result.replace(placeholder, f'`{escaped_code}`')

    return result


def clean_for_telegram(text: str, remove_version: bool = False) -> str:
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
        print(f"Telegram 通知发送失败: {e}")
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
        print(f"Telegram 消息编辑失败: {e}")
        return {"success": False, "message_id": None}


# Telegram 消息长度限制
MAX_MESSAGE_LENGTH = 4096


def _build_bilingual_messages(
    version: str,
    original: str,
    translated: str,
    title: str,
    version_url: str = None
) -> dict:
    """
    构建双语消息内容（内部辅助函数）

    Returns:
        dict: {
            "en_message": str,      # 英文消息
            "cn_message": str,      # 中文消息
            "combined_message": str, # 合并消息
            "is_oversized": bool,   # 合并消息是否超长
            "is_single_oversized": bool,  # 单条消息是否超长（需要 Telegraph）
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
    en_lines = [en_title, "", original_en] if title else [original_en]
    en_message = "\n".join(en_lines)

    # 构建中文消息
    cn_content = translated_clean if translated_clean else "（无翻译）"
    cn_lines = [cn_title, "", cn_content] if title else [cn_content]
    cn_message = "\n".join(cn_lines)

    # 构建合并消息
    combined_lines = [en_title, "", original_en] if title else [original_en]
    if translated_clean:
        combined_lines.extend(["", translated_clean])
    combined_message = "\n".join(combined_lines)

    # 检测消息长度
    processed_combined = process_message_for_markdown_v2(combined_message)
    processed_en = process_message_for_markdown_v2(en_message)
    processed_cn = process_message_for_markdown_v2(cn_message)

    is_oversized = len(processed_combined) > MAX_MESSAGE_LENGTH
    # 判断单条消息是否超长（任一条超长就需要使用 Telegraph）
    is_single_oversized = len(processed_en) > MAX_MESSAGE_LENGTH or len(processed_cn) > MAX_MESSAGE_LENGTH

    return {
        "en_message": en_message,
        "cn_message": cn_message,
        "combined_message": combined_message,
        "is_oversized": is_oversized,
        "is_single_oversized": is_single_oversized,
        "combined_length": len(processed_combined),
        "en_length": len(processed_en),
        "cn_length": len(processed_cn),
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
    version_url: str = None
) -> dict:
    """
    发送双语通知，自动处理长度限制

    处理策略:
    - 如果双语合并后 <= 4096 字符，发送一条消息
    - 如果合并超长但单条 <= 4096，分两条发送（英文一条、中文一条）
    - 如果单条也超长（> 4096），发布到 Telegraph，发送标题+链接

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
    msgs = _build_bilingual_messages(version, original, translated, title, version_url)

    # 情况3: 单条消息超长，使用 Telegraph
    if msgs["is_single_oversized"]:
        print(f"单条消息超长 (英文: {msgs['en_length']}, 中文: {msgs['cn_length']})，发布到 Telegraph")

        # 导入 Telegraph 模块
        from core.notify.telegraph import publish_changelog

        # 发布到 Telegraph
        telegraph_result = publish_changelog(
            title=title,
            original=original,
            translated=translated,
            version=version
        )

        if not telegraph_result["success"]:
            print("Telegraph 发布失败，无法发送通知")
            return {"success": False, "message_ids": [], "telegraph_url": None}

        # 构建简短的 Telegram 消息（标题 + Telegraph 链接）
        telegraph_url = telegraph_result["url"]
        short_message = f"{msgs['en_title']}\n\n[View Full Changelog | 查看完整更新日志]({telegraph_url})"

        result = send_telegram_message(short_message, bot_token, chat_id)
        message_ids = [result["message_id"]] if result["message_id"] else []
        return {
            "success": result["success"],
            "message_ids": message_ids,
            "telegraph_url": telegraph_url
        }

    # 情况1: 长度在限制内，发送合并消息
    if not msgs["is_oversized"]:
        result = send_telegram_message(msgs["combined_message"], bot_token, chat_id)
        message_ids = [result["message_id"]] if result["message_id"] else []
        return {"success": result["success"], "message_ids": message_ids, "telegraph_url": None}

    # 情况2: 合并超长但单条不超长，分两条发送
    print(f"消息长度 {msgs['combined_length']} 超出限制，分两条发送")

    result1 = send_telegram_message(msgs["en_message"], bot_token, chat_id)
    result2 = send_telegram_message(msgs["cn_message"], bot_token, chat_id)

    message_ids = []
    if result1["message_id"]:
        message_ids.append(result1["message_id"])
    if result2["message_id"]:
        message_ids.append(result2["message_id"])

    return {
        "success": result1["success"] and result2["success"],
        "message_ids": message_ids,
        "telegraph_url": None
    }


def edit_bilingual_notification(
    message_ids: list,
    version: str,
    original: str,
    translated: str,
    title: str,
    bot_token: str = None,
    chat_id: str = None,
    version_url: str = None
) -> dict:
    """
    编辑已发送的双语通知

    处理策略:
    - 单条消息也超长: 发布到 Telegraph，编辑为短链接消息
    - 1条消息 + 内容不超长: 直接编辑
    - 1条消息 + 内容超长: 编辑为英文，新发中文
    - 2条消息: 分别编辑英文和中文

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

    msgs = _build_bilingual_messages(version, original, translated, title, version_url)
    # 单条消息也超长，改用 Telegraph 处理
    if msgs["is_single_oversized"]:
        print(f"单条消息超长 (英文: {msgs['en_length']}, 中文: {msgs['cn_length']})，发布到 Telegraph")

        from core.notify.telegraph import publish_changelog

        telegraph_result = publish_changelog(
            title=title,
            original=original,
            translated=translated,
            version=version
        )

        if not telegraph_result["success"]:
            print("Telegraph 发布失败，无法编辑通知")
            return {"success": False, "message_ids": []}

        telegraph_url = telegraph_result["url"]
        short_en = f"{msgs['en_title']}\n\n[View Full Changelog | 查看完整更新日志]({telegraph_url})"
        short_cn = f"{msgs['cn_title']}\n\n[查看完整更新日志]({telegraph_url})"

        edit_results = []
        for idx, message_id in enumerate(message_ids):
            message = short_en if idx == 0 else short_cn
            edit_results.append(edit_telegram_message(message_id, message, bot_token, chat_id))

        success = all(result["success"] for result in edit_results)
        return {
            "success": success,
            "message_ids": message_ids if success else []
        }
    is_single_message = len(message_ids) == 1

    # 情况1: 原本是单条消息
    if is_single_message:
        if not msgs["is_oversized"]:
            # 内容不超长，直接编辑合并消息
            result = edit_telegram_message(message_ids[0], msgs["combined_message"], bot_token, chat_id)
            return {
                "success": result["success"],
                "message_ids": message_ids if result["success"] else []
            }
        else:
            # 内容超长，需要拆分: 编辑原消息为英文，新发一条中文
            print(f"消息长度 {msgs['combined_length']} 超出限制，拆分为2条消息")
            result1 = edit_telegram_message(message_ids[0], msgs["en_message"], bot_token, chat_id)
            result2 = send_telegram_message(msgs["cn_message"], bot_token, chat_id)

            new_ids = list(message_ids)
            if result2["message_id"]:
                new_ids.append(result2["message_id"])

            return {
                "success": result1["success"] and result2["success"],
                "message_ids": new_ids if result1["success"] else []
            }

    # 情况2: 原本是两条消息，分别编辑
    result1 = edit_telegram_message(message_ids[0], msgs["en_message"], bot_token, chat_id)
    result2 = edit_telegram_message(message_ids[1], msgs["cn_message"], bot_token, chat_id)

    return {
        "success": result1["success"] and result2["success"],
        "message_ids": message_ids
    }
