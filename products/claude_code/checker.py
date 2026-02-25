#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 版本更新检查脚本
从 GitHub 拉取 CHANGELOG.md，检查是否有新版本发布
"""

import argparse
import hashlib
import json
import os
import re
import sys
import requests

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.notify.telegram import edit_bilingual_notification, send_bilingual_notification
from core.translate import translate_changelog

# 配置
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
VERSION_FILE = os.path.join(PROJECT_ROOT, "output", "claude_code_latest_version.txt")
MESSAGE_STATE_FILE = os.path.join(PROJECT_ROOT, "output", "claude_code_message_state.json")

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


def _parse_version_content(changelog_text, target_version=None):
    """
    解析 CHANGELOG 中指定版本的内容

    Args:
        changelog_text: CHANGELOG 全文
        target_version: 目标版本号，None 时解析最新版本

    Returns:
        (version, content) 元组；未找到时返回 (None, None)
    """
    version_pattern = r'^## (\d+\.\d+\.\d+)'
    lines = changelog_text.split('\n')
    found_version = None
    content_lines = []

    for line in lines:
        match = re.match(version_pattern, line)
        if match:
            if found_version is not None:
                break
            current = match.group(1)
            if target_version is None or current == target_version:
                found_version = current
                content_lines.append(line)
        elif found_version is not None:
            content_lines.append(line)

    if found_version is None:
        return None, None

    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    return found_version, '\n'.join(content_lines)


def parse_latest_version(changelog_text):
    """解析最新版本号和更新内容"""
    return _parse_version_content(changelog_text)


def parse_specific_version(changelog_text, target_version):
    """解析指定版本号的更新内容"""
    _, content = _parse_version_content(changelog_text, target_version)
    return content


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


def compute_body_hash(body):
    """计算 body 内容的 hash 值"""
    if not body:
        return ""
    return hashlib.md5(body.encode('utf-8')).hexdigest()


def read_message_state():
    """
    读取消息状态文件

    Returns:
        dict: {"version": str, "message_ids": list, "body_hash": str} 或 None
    """
    if not os.path.exists(MESSAGE_STATE_FILE):
        return None

    try:
        with open(MESSAGE_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"读取消息状态文件失败: {e}")
        return None


def save_message_state(version, message_ids, body_hash):
    """
    保存消息状态到文件

    Args:
        version: 版本号
        message_ids: Telegram 消息 ID 列表
        body_hash: body 内容的 hash 值
    """
    try:
        os.makedirs(os.path.dirname(MESSAGE_STATE_FILE), exist_ok=True)
        state = {
            "version": version,
            "message_ids": message_ids,
            "body_hash": body_hash
        }
        with open(MESSAGE_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存消息状态失败: {e}")
        return False


def clear_message_state():
    """
    清理消息状态文件（用于消息已删除等无法恢复的情况）
    """
    try:
        if os.path.exists(MESSAGE_STATE_FILE):
            os.remove(MESSAGE_STATE_FILE)
            print("消息状态已清理")
        return True
    except Exception as e:
        print(f"清理消息状态失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Claude Code 版本更新检查脚本")
    parser.add_argument("-f", "--force", action="store_true",
                       help="强制推送版本（跳过版本比对，不更新记录）")
    parser.add_argument("-V", "--target-version", type=str, default=None,
                       help="指定推送的版本号（需配合 --force 使用，如 --force -V 2.1.49）")
    args = parser.parse_args()

    if args.target_version is not None and not args.force:
        print("错误: --target-version 需配合 --force 使用")
        return 1

    if args.target_version is not None and not re.fullmatch(r'\d+\.\d+\.\d+', args.target_version):
        print(f"错误: 版本号格式不正确 '{args.target_version}'，期望格式如 2.1.49")
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
        if args.target_version is not None:
            push_version = args.target_version
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
        # 版本相同，检查内容是否有更新
        print("-" * 50)
        print(f"当前已是最新版本 ({latest_version})")

        # 检查 body 是否有变化（用于处理开发者延迟修改 CHANGELOG 的情况）
        current_body_hash = compute_body_hash(latest_content)
        message_state = read_message_state()

        if message_state and message_state.get("version") == latest_version:
            saved_body_hash = message_state.get("body_hash", "")
            saved_message_ids = message_state.get("message_ids", [])

            if saved_body_hash != current_body_hash and saved_message_ids:
                print("-" * 50)
                print("检测到 CHANGELOG 已更新，正在编辑之前发送的通知...")

                translated = translate_changelog(latest_content)

                edit_result = edit_bilingual_notification(
                    message_ids=saved_message_ids,
                    version=latest_version,
                    original=latest_content,
                    translated=translated,
                    title="Claude Code",
                    bot_token=TELEGRAM_BOT_TOKEN,
                    chat_id=TELEGRAM_CHAT_ID
                )

                if edit_result["success"]:
                    print("消息编辑成功")
                    if not save_message_state(latest_version, edit_result["message_ids"], current_body_hash):
                        print("⚠️ 消息状态保存失败（不影响主流程）")
                else:
                    print("⚠️  消息编辑失败，可能消息已被删除")
                    clear_message_state()
                    return 1

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

        # 保存消息状态（用于后续内容更新时编辑消息）
        if notify_result["message_ids"]:
            body_hash = compute_body_hash(latest_content)
            if not save_message_state(latest_version, notify_result["message_ids"], body_hash):
                print("⚠️ 消息状态保存失败（不影响主流程）")
            else:
                print(f"消息状态已保存 (message_ids: {notify_result['message_ids']})")

        return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        sys.exit(exit_code)
