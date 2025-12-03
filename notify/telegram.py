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


def send_telegram_message(message: str, bot_token: str = None, chat_id: str = None) -> bool:
    """
    发送 Telegram 消息

    Args:
        message: 要发送的消息内容，支持 Markdown 格式
        bot_token: Bot Token，不传则使用环境变量 TELEGRAM_BOT_TOKEN
        chat_id: Chat ID，不传则使用环境变量 TELEGRAM_CHAT_ID

    Returns:
        bool: 发送是否成功
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
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # 处理消息格式：保留粗体标记 *text*，转义其他特殊字符
    def process_message_for_markdown_v2(text: str) -> str:
        """处理消息，保留粗体标记，转义其他特殊字符"""
        # 先找出所有 *text* 粗体标记
        bold_pattern = r'\*([^*]+)\*'
        parts = []
        last_end = 0

        for match in re.finditer(bold_pattern, text):
            # 转义粗体标记之前的文本
            before_text = text[last_end:match.start()]
            parts.append(escape_markdown(before_text))
            # 保留粗体标记，但转义内部内容
            bold_content = match.group(1)
            parts.append(f'*{escape_markdown(bold_content)}*')
            last_end = match.end()

        # 转义剩余文本
        parts.append(escape_markdown(text[last_end:]))
        return ''.join(parts)

    processed_message = process_message_for_markdown_v2(message)

    # Telegram 消息长度限制 4096 字符
    MAX_LENGTH = 4096
    if len(processed_message) > MAX_LENGTH:
        # 截断并添加省略提示
        truncate_notice = "\n\n\\.\\.\\. \\(内容已截断\\)"
        processed_message = processed_message[:MAX_LENGTH - len(truncate_notice)] + truncate_notice

    data = {
        "chat_id": chat_id,
        "text": processed_message,
        "parse_mode": "MarkdownV2",
    }

    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        print("Telegram 通知发送成功")
        return True
    except requests.RequestException as e:
        print(f"Telegram 通知发送失败: {e}")
        return False
