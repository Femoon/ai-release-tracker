#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Codex 历史版本批量推送脚本
从 codex_releases.txt 读取版本内容，逐个版本推送到 Telegram
"""

import argparse
import os
import re
import sys
import time

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notify.telegram import send_bilingual_notification
from translate import translate_changelog

# 配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RELEASES_FILE = os.path.join(PROJECT_ROOT, "output", "codex_releases.txt")
PUSHED_VERSIONS_FILE = os.path.join(PROJECT_ROOT, "output", "codex_pushed_versions.txt")

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("CODEX_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CODEX_CHAT_ID", "")

# 推送间隔（秒）
PUSH_DELAY = 3
# 推送失败重试次数
MAX_RETRY = 3


def parse_releases_file(filepath):
    """
    解析 codex_releases.txt 文件
    返回: [{name, body, url}, ...]
    """
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        return []

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 按分隔符拆分版本
    sections = re.split(r'={10,}', content)
    releases = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 提取版本号和链接: ## [0.5.0](https://...)
        match = re.match(r'^##\s*\[(.+?)\]\((.+?)\)', section)
        if not match:
            continue

        name = match.group(1)
        url = match.group(2)

        # 提取 body（标题行之后的内容）
        body = section[match.end():].strip()

        releases.append({
            "name": name,
            "body": body,
            "url": url
        })

    return releases


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
    print("OpenAI Codex 历史版本批量推送")
    print("=" * 50)

    # 从文件读取版本
    print(f"读取文件: {RELEASES_FILE}")
    all_releases = parse_releases_file(RELEASES_FILE)
    print(f"共 {len(all_releases)} 个版本")

    # 读取已推送版本
    pushed_versions = read_pushed_versions()
    print(f"已推送 {len(pushed_versions)} 个版本")

    # 过滤未推送版本（排除 beta 版本）
    pending_releases = [
        r for r in all_releases
        if r["name"] not in pushed_versions and "beta" not in r["name"].lower()
    ]
    print(f"待推送 {len(pending_releases)} 个版本")

    if not pending_releases:
        print("没有待推送的版本")
        return

    # 限制推送数量
    if not push_all:
        pending_releases = pending_releases[:max_count]
        print(f"本次推送 {len(pending_releases)} 个版本")

    print("-" * 50)

    # 逐个推送
    success_count = 0
    for i, release in enumerate(pending_releases, 1):
        version = release["name"]
        body = release["body"]
        url = release["url"]

        print(f"\n[{i}/{len(pending_releases)}] 推送版本 {version}...")

        # 构建内容（不再需要在内容中包含链接，因为标题已有超链接）
        original_content = body or "（暂无更新说明）"

        # 翻译内容
        print("  正在翻译...")
        translated = translate_changelog(body) if body else ""

        # 发送通知（带重试）
        result = False
        for retry in range(MAX_RETRY):
            if retry > 0:
                print(f"  第 {retry + 1} 次重试...")
                time.sleep(PUSH_DELAY)

            print("  正在发送通知...")
            result = send_bilingual_notification(
                version=version,
                original=original_content,
                translated=translated,
                title="OpenAI Codex",
                bot_token=TELEGRAM_BOT_TOKEN,
                chat_id=TELEGRAM_CHAT_ID,
                version_url=url
            )

            if result:
                break

        if result:
            # 记录已推送
            append_pushed_version(version)
            success_count += 1
            print(f"  [OK] 版本 {version} 推送成功")
        else:
            print(f"  [FAIL] 版本 {version} 推送失败，已重试 {MAX_RETRY} 次，停止运行")
            break

        # 延迟（最后一个不需要延迟）
        if i < len(pending_releases):
            time.sleep(PUSH_DELAY)

    print("-" * 50)
    print(f"推送完成: 成功 {success_count}/{len(pending_releases)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenAI Codex 历史版本批量推送")
    parser.add_argument("--count", type=int, default=3, help="推送版本数量（默认 3）")
    parser.add_argument("--all", action="store_true", help="推送所有未推送版本")

    args = parser.parse_args()
    main(max_count=args.count, push_all=args.all)
