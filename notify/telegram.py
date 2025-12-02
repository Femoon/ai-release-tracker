#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知模块
"""

import os
import requests

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram_message(message: str) -> bool:
    """
    发送 Telegram 消息

    Args:
        message: 要发送的消息内容，支持 Markdown 格式

    Returns:
        bool: 发送是否成功
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram 配置未设置，跳过通知")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
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
