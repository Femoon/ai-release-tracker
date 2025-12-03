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

    # 为非空、非标题、非已有点号的行添加点号
    lines = text.split('\n')
    result_lines = []
    title_patterns = ['Features', 'Bug fixes', 'Maintenance', 'PRs Merged',
                      '功能', '错误修复', '维护', '链接:', 'Source:']
    for line in lines:
        stripped = line.strip()
        # 跳过空行、已有点号的行、标题行
        if (not stripped or
            stripped.startswith('•') or
            any(stripped.startswith(t) for t in title_patterns)):
            result_lines.append(line)
        else:
            result_lines.append('• ' + line)
    text = '\n'.join(result_lines)

    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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
        print("Telegram 通知发送成功")
        return True
    except requests.RequestException as e:
        print(f"Telegram 通知发送失败: {e}")
        return False


# Telegram 消息长度限制
MAX_MESSAGE_LENGTH = 4096


def send_bilingual_notification(
    version: str,
    original: str,
    translated: str,
    title: str,
    bot_token: str = None,
    chat_id: str = None,
    version_url: str = None
) -> bool:
    """
    发送双语通知，自动处理长度限制

    - 如果双语合并后 <= 4096 字符，发送一条消息
    - 如果超出限制，分两条发送（英文一条、中文一条）

    Args:
        version: 版本号
        original: 英文原文
        translated: 中文翻译
        title: 标题（如 "Claude Code" 或 "OpenAI Codex"）
        bot_token: Bot Token
        chat_id: Chat ID
        version_url: 版本链接（可选，用于生成超链接标题）

    Returns:
        bool: 发送是否成功
    """
    # 清理内容
    original_clean = clean_for_telegram(original, remove_version=True)
    translated_clean = clean_for_telegram(translated, remove_version=True) if translated else ""

    # 英文内容：将 "链接:" 替换为 "Source:"
    original_en = original_clean.replace('链接:', 'Source:')

    # 构建标题（支持超链接）
    if version_url:
        en_title = f"*{title} [{version}]({version_url}) Released*"
        cn_title = f"*{title} [{version}]({version_url}) 发布*"
    else:
        en_title = f"*{title} {version} Released*"
        cn_title = f"*{title} {version} 发布*"

    # 生成合并的双语消息
    lines = []
    if title:
        lines.append(en_title)
        lines.append("")
    lines.append(original_en)
    if translated_clean:
        lines.append("")
        lines.append(translated_clean)
    combined_message = "\n".join(lines)

    # 计算转义后长度
    processed_combined = process_message_for_markdown_v2(combined_message)

    if len(processed_combined) <= MAX_MESSAGE_LENGTH:
        # 长度在限制内，发送合并消息
        return send_telegram_message(combined_message, bot_token, chat_id)
    else:
        # 超出限制，分两条发送
        print(f"消息长度 {len(processed_combined)} 超出限制，分两条发送")

        # 英文消息
        en_lines = []
        if title:
            en_lines.append(en_title)
            en_lines.append("")
        en_lines.append(original_en)
        en_message = "\n".join(en_lines)

        # 中文消息
        cn_lines = []
        if title:
            cn_lines.append(cn_title)
            cn_lines.append("")
        cn_lines.append(translated_clean if translated_clean else "（无翻译）")
        cn_message = "\n".join(cn_lines)

        # 发送两条消息
        result1 = send_telegram_message(en_message, bot_token, chat_id)
        result2 = send_telegram_message(cn_message, bot_token, chat_id)

        return result1 and result2
