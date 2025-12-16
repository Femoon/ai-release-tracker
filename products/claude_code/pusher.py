#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 历史版本批量推送脚本
从 GitHub 拉取 CHANGELOG.md，逐个版本推送到 Telegram
"""

import argparse
import os
import re
import sys
import time
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
PUSHED_VERSIONS_FILE = os.path.join(PROJECT_ROOT, "output", "claude_code_pushed_versions.txt")

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("CLAUDE_CODE_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CLAUDE_CODE_CHAT_ID", "")

# 推送间隔（秒）
PUSH_DELAY = 3
# 推送失败重试次数
MAX_RETRY = 3


def fetch_changelog():
    """从 GitHub 获取 CHANGELOG.md 内容"""
    try:
        response = requests.get(CHANGELOG_URL, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"获取更新日志失败: {e}")
        return None


def parse_all_versions(changelog_text):
    """
    解析所有版本号和更新内容
    返回: [(version, content), ...]，从旧到新排序
    """
    version_pattern = r'^## (\d+\.\d+\.\d+)'
    lines = changelog_text.split('\n')

    versions = []
    current_version = None
    current_lines = []

    for line in lines:
        match = re.match(version_pattern, line)
        if match:
            # 保存上一个版本
            if current_version:
                content = '\n'.join(current_lines).strip()
                versions.append((current_version, content))

            # 开始新版本
            current_version = match.group(1)
            current_lines = [line]
        elif current_version:
            current_lines.append(line)

    # 保存最后一个版本
    if current_version:
        content = '\n'.join(current_lines).strip()
        versions.append((current_version, content))

    # 返回从旧到新的顺序（反转列表）
    return list(reversed(versions))


def read_pushed_versions():
    """读取已推送的版本号集合"""
    if not os.path.exists(PUSHED_VERSIONS_FILE):
        return set()

    try:
        with open(PUSHED_VERSIONS_FILE, 'r', encoding='utf-8') as f:
            versions = set(line.strip() for line in f if line.strip())
            return versions
    except Exception as e:
        print(f"读取已推送版本文件失败: {e}")
        return set()


def append_pushed_version(version):
    """追加版本到记录文件"""
    try:
        os.makedirs(os.path.dirname(PUSHED_VERSIONS_FILE), exist_ok=True)
        with open(PUSHED_VERSIONS_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{version}\n")
        return True
    except Exception as e:
        print(f"记录推送版本失败: {e}")
        return False


def main(max_count=3, push_all=False):
    """
    主函数
    max_count: 最多推送版本数量
    push_all: 是否推送所有未推送版本
    """
    print("Claude Code 历史版本批量推送")
    print("=" * 50)

    # 获取所有版本
    changelog = fetch_changelog()
    if not changelog:
        return

    all_versions = parse_all_versions(changelog)
    print(f"共 {len(all_versions)} 个版本")

    # 读取已推送版本
    pushed_versions = read_pushed_versions()
    print(f"已推送 {len(pushed_versions)} 个版本")

    # 过滤未推送版本
    pending_versions = [(v, c) for v, c in all_versions if v not in pushed_versions]
    print(f"待推送 {len(pending_versions)} 个版本")

    if not pending_versions:
        print("没有待推送的版本")
        return

    # 限制推送数量
    if not push_all:
        pending_versions = pending_versions[:max_count]
        print(f"本次推送 {len(pending_versions)} 个版本")

    print("-" * 50)

    # 逐个推送
    success_count = 0
    for i, (version, content) in enumerate(pending_versions, 1):
        print(f"\n[{i}/{len(pending_versions)}] 推送版本 {version}...")

        # 翻译内容
        print("  正在翻译...")
        translated = translate_changelog(content)

        # 发送通知（带重试）
        result = False
        for retry in range(MAX_RETRY):
            if retry > 0:
                print(f"  第 {retry + 1} 次重试...")
                time.sleep(PUSH_DELAY)

            print("  正在发送通知...")
            result = send_bilingual_notification(
                version=version,
                original=content,
                translated=translated,
                title="Claude Code",
                bot_token=TELEGRAM_BOT_TOKEN,
                chat_id=TELEGRAM_CHAT_ID
            )

            if result["success"]:
                break

        if result["success"]:
            # 记录已推送
            append_pushed_version(version)
            success_count += 1
            print(f"  [OK] 版本 {version} 推送成功")
        else:
            print(f"  [FAIL] 版本 {version} 推送失败，已重试 {MAX_RETRY} 次，停止运行")
            break

        # 延迟（最后一个不需要延迟）
        if i < len(pending_versions):
            time.sleep(PUSH_DELAY)

    print("-" * 50)
    print(f"推送完成: 成功 {success_count}/{len(pending_versions)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude Code 历史版本批量推送")
    parser.add_argument("--count", type=int, default=3, help="推送版本数量（默认 3）")
    parser.add_argument("--all", action="store_true", help="推送所有未推送版本")

    args = parser.parse_args()
    main(max_count=args.count, push_all=args.all)
