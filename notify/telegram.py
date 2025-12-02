#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知模块
"""

import os
import requests


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
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        print("Telegram 通知发送成功")
        return True
    except requests.RequestException as e:
        print(f"Telegram 通知发送失败: {e}")
        return False
