#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 版本更新检查脚本
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
from core.notify.telegram import edit_bilingual_notification, send_bilingual_notification
from core.translate import translate_changelog
from products.openclaw.content import select_notification_content
from core.state import (
    compute_body_hash,
    read_message_state as _read_message_state,
    save_message_state as _save_message_state,
    clear_message_state as _clear_message_state,
    is_edit_locked,
)

# 配置
CHANGELOG_URL = "https://raw.githubusercontent.com/openclaw/openclaw/refs/heads/main/CHANGELOG.md"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
VERSION_FILE = os.path.join(PROJECT_ROOT, "output", "openclaw_latest_version.txt")
MESSAGE_STATE_FILE = os.path.join(PROJECT_ROOT, "output", "openclaw_message_state.json")

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("OPENCLAW_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("OPENCLAW_CHAT_ID", "")

# 版本号正则：日期格式 YYYY.M.D 或 YYYY.M.D-N（如 2026.3.12 或 2026.4.7-1）
VERSION_PATTERN = r'^## (\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?)'


def fetch_changelog():
    """从 GitHub 获取 CHANGELOG.md 内容"""
    try:
        response = requests.get(CHANGELOG_URL, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"获取更新日志失败: {e}")
        return None


def _is_beta_version(version_line):
    """检查版本行是否包含 beta 标记"""
    return "beta" in version_line.lower()


def _parse_version_tuple(version_str):
    """将 'YYYY.M.D' 或 'YYYY.M.D-N' 版本号解析为可比较的元组"""
    try:
        if '-' in version_str:
            base, suffix = version_str.split('-', 1)
            patch = int(suffix)
        else:
            base = version_str
            patch = 0
        parts = base.split('.')
        return (*tuple(int(p) for p in parts), patch)
    except (ValueError, AttributeError):
        return None


def _is_newer_version(remote, local):
    """判断远程版本是否严格大于本地版本"""
    r = _parse_version_tuple(remote)
    loc = _parse_version_tuple(local)
    if r is None or loc is None:
        return True  # 解析失败时不阻断，保持原有行为
    return r > loc


def _parse_version_content(changelog_text, target_version=None):
    """
    解析 CHANGELOG 中指定版本的内容

    Args:
        changelog_text: CHANGELOG 全文
        target_version: 目标版本号，None 时解析最新版本

    Returns:
        (version, content) 元组；未找到时返回 (None, None)
    """
    lines = changelog_text.split('\n')
    found_version = None
    content_lines = []

    for line in lines:
        match = re.match(VERSION_PATTERN, line)
        if match:
            if found_version is not None:
                break
            current = match.group(1)
            # 跳过 beta 版本（仅在搜索最新版本时）
            if target_version is None and _is_beta_version(line):
                continue
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


def read_message_state():
    return _read_message_state(MESSAGE_STATE_FILE)


def save_message_state(version, message_ids, body_hash, edit_count=0):
    return _save_message_state(MESSAGE_STATE_FILE, version, message_ids, body_hash, edit_count)


def clear_message_state():
    return _clear_message_state(MESSAGE_STATE_FILE)


def main():
    parser = argparse.ArgumentParser(description="OpenClaw 版本更新检查脚本")
    parser.add_argument("-f", "--force", action="store_true",
                       help="强制推送版本（跳过版本比对，不更新记录）")
    parser.add_argument("-V", "--target-version", type=str, default=None,
                       help="指定推送的版本号（需配合 --force 使用，如 --force -V 2026.3.12）")
    args = parser.parse_args()

    if args.target_version is not None and not args.force:
        print("错误: --target-version 需配合 --force 使用")
        return 1

    if args.target_version is not None and not re.fullmatch(r'\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?', args.target_version):
        print(f"错误: 版本号格式不正确 '{args.target_version}'，期望格式如 2026.3.12 或 2026.4.7-1")
        return 1

    print("正在检查 OpenClaw 更新...")
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

        # 有 Highlights 时只展示 Highlights；否则跳过逐条 Fixes。
        notification_content = select_notification_content(push_content)
        translated = translate_changelog(notification_content)
        if notification_content.strip() and not translated:
            print("翻译失败，停止推送；强制模式未修改本地记录，可直接重跑")
            return 1

        notify_result = send_bilingual_notification(
            version=push_version,
            original=notification_content,
            translated=translated,
            title="OpenClaw",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID
        )

        if not notify_result["success"]:
            print("Telegram 通知发送失败")
            return 1

        print(f"版本 {push_version} 推送完成（强制模式，未更新本地记录）")
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
        notification_content = select_notification_content(latest_content)
        current_body_hash = compute_body_hash(notification_content)
        message_state = read_message_state()

        if message_state and message_state.get("version") == latest_version:
            saved_body_hash = message_state.get("body_hash", "")
            saved_message_ids = message_state.get("message_ids", [])
            saved_edit_count = message_state.get("edit_count", 0)

            if saved_body_hash != current_body_hash and saved_message_ids:
                if is_edit_locked(message_state, latest_version):
                    print("-" * 50)
                    print(
                        f"检测到 CHANGELOG 已更新，但版本 {latest_version} 已达每版本编辑上限，"
                        "跳过翻译和消息编辑"
                    )
                    save_message_state(
                        latest_version, saved_message_ids, current_body_hash,
                        edit_count=saved_edit_count,
                    )
                    return 0

                print("-" * 50)
                print("检测到 CHANGELOG 已更新，正在编辑之前发送的通知...")

                translated = translate_changelog(notification_content)
                if notification_content.strip() and not translated:
                    print("翻译失败，停止编辑；保留现有消息状态以便下次重试")
                    return 1

                edit_result = edit_bilingual_notification(
                    message_ids=saved_message_ids,
                    version=latest_version,
                    original=notification_content,
                    translated=translated,
                    title="OpenClaw",
                    bot_token=TELEGRAM_BOT_TOKEN,
                    chat_id=TELEGRAM_CHAT_ID
                )

                if edit_result["success"]:
                    print("消息编辑成功")
                    if not save_message_state(
                        latest_version, edit_result["message_ids"], current_body_hash,
                        edit_count=saved_edit_count + 1,
                    ):
                        print("消息状态保存失败（不影响主流程）")
                else:
                    print("消息编辑失败，可能消息已被删除")
                    clear_message_state()
                    return 1

        return 0
    else:
        # 版本不同，校验方向
        if not _is_newer_version(latest_version, saved_version):
            print(f"远程版本 {latest_version} 不高于本地记录 {saved_version}，跳过")
            return 0

        # 有新版本
        print(f"发现新版本！ {saved_version} -> {latest_version}")
        print("-" * 50)
        print("更新内容：")
        try:
            print(latest_content)
        except UnicodeEncodeError:
            print("(内容包含特殊字符，已跳过终端显示)")
        print("-" * 50)
        # 先翻译再落版本号：翻译失败时保持版本状态不变，下次检查会重新尝试，
        # 否则一次翻译失败会让这个版本永久只有英文。
        notification_content = select_notification_content(latest_content)
        translated = translate_changelog(notification_content)
        if notification_content.strip() and not translated:
            print("翻译失败，停止推送；版本状态未更新，下次检查将重新尝试")
            return 1

        if not save_version(latest_version):
            print("版本记录保存失败，停止推送以避免重复")
            return 1
        print("版本信息已更新")

        # 发送 Telegram 通知
        notify_result = send_bilingual_notification(
            version=latest_version,
            original=notification_content,
            translated=translated,
            title="OpenClaw",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID
        )

        # 检查通知是否发送成功
        if not notify_result["success"]:
            print("Telegram 通知发送失败")
            return 1

        # 保存消息状态（用于后续内容更新时编辑消息）；新版本重置 edit_count=0
        if notify_result["message_ids"]:
            body_hash = compute_body_hash(notification_content)
            if not save_message_state(
                latest_version, notify_result["message_ids"], body_hash, edit_count=0,
            ):
                print("消息状态保存失败（不影响主流程）")
            else:
                print(f"消息状态已保存 (message_ids: {notify_result['message_ids']})")

        return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        sys.exit(exit_code)
