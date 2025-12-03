#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 版本更新检查脚本
从 GitHub 拉取 CHANGELOG.md，检查是否有新版本发布
"""

import os
import re
import sys
import requests

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notify.telegram import send_bilingual_notification
from translate import translate_changelog

# 配置
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VERSION_FILE = os.path.join(PROJECT_ROOT, "output", "claude_code_latest_version.txt")

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("CLAUDE_CODE_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CLAUDE_CODE_CHAT_ID", "")


def fetch_changelog():
    """从 GitHub 获取 CHANGELOG.md 内容"""
    try:
        response = requests.get(CHANGELOG_URL, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"获取更新日志失败: {e}")
        return None


def parse_latest_version(changelog_text):
    """解析最新版本号和更新内容"""
    # 匹配版本号格式: ## X.Y.Z
    version_pattern = r'^## (\d+\.\d+\.\d+)'

    lines = changelog_text.split('\n')
    version = None
    content_lines = []
    found_first_version = False

    for line in lines:
        match = re.match(version_pattern, line)
        if match:
            if not found_first_version:
                # 找到第一个版本（最新版本）
                version = match.group(1)
                found_first_version = True
                content_lines.append(line)
            else:
                # 遇到第二个版本，停止收集
                break
        elif found_first_version:
            content_lines.append(line)

    # 清理尾部空行
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    content = '\n'.join(content_lines)
    return version, content


def read_saved_version():
    """读取本地保存的版本号"""
    if not os.path.exists(VERSION_FILE):
        return None

    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        print(f"读取本地版本文件失败: {e}")
        return None


def save_version(version):
    """保存版本号到本地文件"""
    try:
        os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
        with open(VERSION_FILE, 'w', encoding='utf-8') as f:
            f.write(version)
        return True
    except Exception as e:
        print(f"保存版本信息失败: {e}")
        return False


def main():
    print("正在检查 Claude Code 更新...")
    print("-" * 50)

    # 获取最新的 CHANGELOG
    changelog = fetch_changelog()
    if not changelog:
        return

    # 解析最新版本
    latest_version, latest_content = parse_latest_version(changelog)
    if not latest_version:
        print("无法解析版本信息")
        return

    print(f"远程最新版本: {latest_version}")

    # 读取本地保存的版本
    saved_version = read_saved_version()

    if saved_version is None:
        # 首次运行
        print(f"首次运行，已记录版本 {latest_version}")
        save_version(latest_version)
    elif saved_version == latest_version:
        # 版本相同
        print(f"当前已是最新版本 ({latest_version})")
    else:
        # 有新版本
        print(f"发现新版本！ {saved_version} → {latest_version}")
        print("-" * 50)
        print("更新内容：")
        print(latest_content)
        print("-" * 50)
        save_version(latest_version)
        print("版本信息已更新")

        # 发送 Telegram 通知
        translated = translate_changelog(latest_content)
        send_bilingual_notification(
            version=latest_version,
            original=latest_content,
            translated=translated,
            title="Claude Code",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID
        )


if __name__ == "__main__":
    main()
