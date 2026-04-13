#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取 OpenClaw 所有版本日志并保存到文件
从 CHANGELOG.md 解析所有版本信息
"""

import os
import re
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

# 配置
CHANGELOG_URL = "https://raw.githubusercontent.com/openclaw/openclaw/refs/heads/main/CHANGELOG.md"
GITHUB_RELEASE_URL_BASE = "https://github.com/openclaw/openclaw/releases/tag"

# 获取项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "output", "openclaw_releases.txt")

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


def parse_all_versions(changelog_text):
    """
    解析所有版本号和更新内容（排除 beta 版本）
    返回: [(version, content), ...]，从旧到新排序
    """
    lines = changelog_text.split('\n')

    versions = []
    current_version = None
    current_lines = []

    for line in lines:
        match = re.match(VERSION_PATTERN, line)
        if match:
            # 保存上一个版本
            if current_version:
                content = '\n'.join(current_lines).strip()
                versions.append((current_version, content))

            # 跳过 beta 版本
            if "beta" in line.lower():
                current_version = None
                current_lines = []
                continue

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


def main():
    print("拉取 OpenClaw Releases")
    print("=" * 50)

    # 获取 CHANGELOG
    changelog = fetch_changelog()
    if not changelog:
        return

    # 解析所有版本
    all_versions = parse_all_versions(changelog)
    print(f"共 {len(all_versions)} 个版本（已排除 beta）")

    # 输出到文件
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for version, content in all_versions:
            # 版本号作为超链接（使用 v 前缀的 tag）
            release_url = f"{GITHUB_RELEASE_URL_BASE}/v{version}"
            f.write(f"## [{version}]({release_url})\n\n")

            # 移除版本号标题行，只保留内容
            content_lines = content.split('\n')
            body = '\n'.join(content_lines[1:]).strip() if len(content_lines) > 1 else ""

            if body:
                f.write(body)
            else:
                f.write("（暂无更新说明）")
            f.write("\n\n" + "=" * 60 + "\n\n")

    print(f"\n已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
