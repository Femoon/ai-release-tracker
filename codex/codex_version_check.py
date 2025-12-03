#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Codex 版本更新检查脚本
从 GitHub releases Atom feed 拉取，检查是否有新的稳定版本发布（排除 alpha 版本）
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
import requests

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notify.telegram import send_bilingual_notification
from translate import translate_changelog

# 配置
RELEASES_ATOM_URL = "https://github.com/openai/codex/releases.atom"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
VERSION_FILE = os.path.join(PROJECT_ROOT, "output", "codex_latest_version.txt")

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("CODEX_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CODEX_CHAT_ID", "")

# Atom 命名空间
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def fetch_releases_feed():
    """从 GitHub 获取 releases Atom feed"""
    try:
        response = requests.get(RELEASES_ATOM_URL, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"获取 releases feed 失败: {e}")
        return None


def parse_latest_stable_release(feed_xml):
    """解析最新的非 alpha 版本"""
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as e:
        print(f"解析 XML 失败: {e}")
        return None, None, None

    entries = root.findall("atom:entry", ATOM_NS)

    for entry in entries:
        title_elem = entry.find("atom:title", ATOM_NS)
        if title_elem is None:
            continue

        title = title_elem.text.strip()

        # 跳过包含 alpha 关键字的版本（不区分大小写）
        if "alpha" in title.lower():
            continue

        # 找到第一个非 alpha 版本
        # 获取链接
        link_elem = entry.find("atom:link", ATOM_NS)
        link = link_elem.get("href") if link_elem is not None else ""

        # 获取更新内容
        content_elem = entry.find("atom:content", ATOM_NS)
        content = ""
        if content_elem is not None and content_elem.text:
            content = clean_html_content(content_elem.text)

        return title, content, link

    return None, None, None


def clean_html_content(html_text):
    """清理 HTML 标签，提取纯文本"""
    # 移除 HTML 标签
    clean = re.sub(r'<[^>]+>', '', html_text)
    # 处理 HTML 实体
    clean = clean.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'")
    # 过滤掉 "Full Changelog:" 行
    lines = clean.split('\n')
    lines = [line for line in lines if not line.strip().startswith('Full Changelog:')]
    clean = '\n'.join(lines)
    # 移除 PRs Merged 部分（太长，会超出 Telegram 4096 字符限制）
    prs_merged_pattern = r'\n\s*PRs Merged\s*\n.*'
    clean = re.sub(prs_merged_pattern, '', clean, flags=re.DOTALL)
    # 清理多余空白
    clean = re.sub(r'\n\s*\n', '\n\n', clean)
    return clean.strip()


def read_saved_version():
    """读取本地保存的版本信息"""
    if not os.path.exists(VERSION_FILE):
        return None, None

    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n', 1)
        version = lines[0].strip()
        saved_content = lines[1] if len(lines) > 1 else ""
        return version, saved_content
    except Exception as e:
        print(f"读取本地版本文件失败: {e}")
        return None, None


def save_version(version, content):
    """保存版本信息到本地文件"""
    try:
        os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
        with open(VERSION_FILE, 'w', encoding='utf-8') as f:
            f.write(f"{version}\n{content}")
        return True
    except Exception as e:
        print(f"保存版本信息失败: {e}")
        return False


def main():
    print("正在检查 OpenAI Codex 更新（排除 alpha 版本）...")
    print("-" * 50)

    # 获取 releases feed
    feed_xml = fetch_releases_feed()
    if not feed_xml:
        return

    # 解析最新稳定版本
    latest_version, latest_content, release_link = parse_latest_stable_release(feed_xml)
    if not latest_version:
        print("未找到非 alpha 版本")
        return

    print(f"远程最新稳定版本: {latest_version}")

    # 读取本地保存的版本
    saved_version, _ = read_saved_version()

    if saved_version is None:
        # 首次运行
        print(f"首次运行，已记录版本 {latest_version}")
        if release_link:
            print(f"Release 链接: {release_link}")
        save_version(latest_version, latest_content)
    elif saved_version == latest_version:
        # 版本相同
        print(f"当前已是最新稳定版本 ({latest_version})")
    else:
        # 有新版本
        print(f"发现新版本！ {saved_version} → {latest_version}")
        if release_link:
            print(f"Release 链接: {release_link}")
        print("-" * 50)
        if latest_content:
            print("更新内容：")
            print(latest_content)
        else:
            print("（暂无更新说明）")
        print("-" * 50)
        save_version(latest_version, latest_content)
        print("版本信息已更新")

        # 发送 Telegram 通知
        original_content = latest_content or "（暂无更新说明）"
        content_to_translate = latest_content or ""
        if release_link:
            link_text = f"链接: {release_link}\n\n"
            original_content = link_text + original_content
            content_to_translate = link_text + content_to_translate if content_to_translate else ""
        translated = translate_changelog(content_to_translate) if content_to_translate else ""
        send_bilingual_notification(
            version=latest_version,
            original=original_content,
            translated=translated,
            title="OpenAI Codex",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID
        )


if __name__ == "__main__":
    main()
