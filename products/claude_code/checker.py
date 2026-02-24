#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 版本更新检查脚本
从 GitHub 拉取 CHANGELOG.md，检查是否有新版本发布
"""

import argparse
import os
import re
import sys
import requests

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.notify.telegram import send_bilingual_notification
from core.translate import translate_changelog

# 配置
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
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


def parse_specific_version(changelog_text, target_version):
    """解析指定版本号的更新内容"""
    version_pattern = r'^## (\d+\.\d+\.\d+)'
    lines = changelog_text.split('\n')

    content_lines = []
    found_target = False

    for line in lines:
        match = re.match(version_pattern, line)
        if match:
            if found_target:
                # 遇到下一个版本，停止收集
                break
            if match.group(1) == target_version:
                found_target = True
                content_lines.append(line)
        elif found_target:
            content_lines.append(line)

    if not found_target:
        return None

    # 清理尾部空行
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    return '\n'.join(content_lines)


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
    parser = argparse.ArgumentParser(description="Claude Code 版本更新检查脚本")
    parser.add_argument("-f", "--force", action="store_true",
                       help="强制推送版本（跳过版本比对，不更新记录）")
    parser.add_argument("-v", "--version", type=str, default=None,
                       help="指定推送的版本号（需配合 --force 使用，如 --force -v 2.1.49）")
    args = parser.parse_args()

    if args.version and not args.force:
        print("错误: --version 需配合 --force 使用")
        return 1

    print("正在检查 Claude Code 更新...")
    print("-" * 50)

    # 获取最新的 CHANGELOG
    changelog = fetch_changelog()
    if not changelog:
        return 1

    # 解析最新版本
    latest_version, latest_content = parse_latest_version(changelog)
    if not latest_version:
        print("无法解析版本信息")
        return 1

    print(f"远程最新版本: {latest_version}")

    # 强制模式：直接推送，不比对，不更新记录
    if args.force:
        # 确定推送的版本和内容
        if args.version:
            push_version = args.version
            push_content = parse_specific_version(changelog, push_version)
            if push_content is None:
                print(f"错误: 未在 CHANGELOG 中找到版本 {push_version}")
                return 1
        else:
            push_version = latest_version
            push_content = latest_content

        print("-" * 50)
        print(f"强制模式：直接推送版本 {push_version}")
        print("-" * 50)
        print("更新内容：")
        try:
            print(push_content)
        except UnicodeEncodeError:
            print("(内容包含特殊字符，已跳过终端显示)")
        print("-" * 50)

        # 发送 Telegram 通知
        translated = translate_changelog(push_content)
        notify_result = send_bilingual_notification(
            version=push_version,
            original=push_content,
            translated=translated,
            title="Claude Code",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID
        )

        if not notify_result["success"]:
            print("⚠️  Telegram 通知发送失败")
            return 1

        print(f"✓ 版本 {push_version} 推送完成（强制模式，未更新本地记录）")
        return 0

    # 读取本地保存的版本
    saved_version = read_saved_version()

    if saved_version is None:
        # 首次运行
        print(f"首次运行，已记录版本 {latest_version}")
        save_version(latest_version)
        return 0
    elif saved_version == latest_version:
        # 版本相同
        print(f"当前已是最新版本 ({latest_version})")
        return 0
    else:
        # 有新版本
        print(f"发现新版本！ {saved_version} → {latest_version}")
        print("-" * 50)
        print("更新内容：")
        try:
            print(latest_content)
        except UnicodeEncodeError:
            print("(内容包含特殊字符，已跳过终端显示)")
        print("-" * 50)
        if not save_version(latest_version):
            print("⚠️ 版本记录保存失败，停止推送以避免重复")
            return 1
        print("版本信息已更新")

        # 发送 Telegram 通知
        translated = translate_changelog(latest_content)
        notify_result = send_bilingual_notification(
            version=latest_version,
            original=latest_content,
            translated=translated,
            title="Claude Code",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID
        )

        # 检查通知是否发送成功
        if not notify_result["success"]:
            print("⚠️  Telegram 通知发送失败")
            return 1

        return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        sys.exit(exit_code)
