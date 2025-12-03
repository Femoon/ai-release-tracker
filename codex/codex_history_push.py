#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Codex 历史版本批量推送脚本
通过 GitHub API 获取所有 releases，逐个版本推送到 Telegram（排除 alpha 版本）
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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notify.telegram import send_bilingual_notification
from translate import translate_changelog

# 配置
RELEASES_API_URL = "https://api.github.com/repos/openai/codex/releases"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PUSHED_VERSIONS_FILE = os.path.join(PROJECT_ROOT, "output", "codex_pushed_versions.txt")

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("CODEX_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CODEX_CHAT_ID", "")

# GitHub Token（可选，用于提升 API 速率限制）
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# 推送间隔（秒）
PUSH_DELAY = 3
# 推送失败重试次数
MAX_RETRY = 3


def fetch_all_releases():
    """通过 GitHub API 获取所有 releases（分页）"""
    all_releases = []
    page = 1
    per_page = 100

    # 构建请求头
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    while True:
        try:
            url = f"{RELEASES_API_URL}?page={page}&per_page={per_page}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            releases = response.json()

            if not releases:
                break

            all_releases.extend(releases)
            page += 1

        except requests.RequestException as e:
            print(f"获取 releases 失败 (page={page}): {e}")
            break

    return all_releases


def clean_release_body(body):
    """清理 release body 内容"""
    if not body:
        return ""

    # 移除 PRs Merged / Merged PRs / PRs 部分及后面所有内容
    clean = re.sub(r'\n##\s*PRs?\s*Merged.*', '', body, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'\n###\s*PRs?\s*Merged.*', '', clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'\n##\s*Merged\s*PRs?.*', '', clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'\n###\s*PRs?\s*$.*', '', clean, flags=re.DOTALL | re.IGNORECASE)

    # 移除 Full Changelog 行
    clean = re.sub(r'\*?\*?Full Changelog\*?\*?:?.*', '', clean, flags=re.IGNORECASE)

    # 移除 PR 列表行（各种格式）
    clean = re.sub(r'^[-*]\s+.*(?:by @|— @).*(?:in #\d+|#\d+).*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^[-*]\s+.*\(#\d+\)\s*—\s*@.*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^#\d+\s+[–—-]\s+.*$', '', clean, flags=re.MULTILINE)

    # 移除 PR/Issue 链接
    clean = re.sub(r'https://github\.com/openai/codex/pull/\d+', '', clean)
    clean = re.sub(r'https://github\.com/openai/codex/issues/\d+', '', clean)

    # 移除内联的 PR/Issue 引用
    clean = re.sub(r'\s*\(#\d+(?:\s+#\d+)*\)', '', clean)
    clean = re.sub(r'#\d+(?:\s+#\d+)*', '', clean)

    # 清理残留的引用文本
    clean = re.sub(r'See\s+for details\.?', '', clean)
    clean = re.sub(r'As of\s*,\s*', '', clean)
    clean = re.sub(r'\s+in\s+so\s+', ' so ', clean)
    clean = re.sub(r'\s+in\s*,', ',', clean)
    clean = re.sub(r'\s+in\s*\)', ')', clean)
    clean = re.sub(r'\s+in\s+because', ' because', clean)
    clean = re.sub(r'\s+in\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'thanks to\s*$', '', clean, flags=re.MULTILINE | re.IGNORECASE)
    clean = re.sub(r'fixing\s*\.?\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'\s*\(was the relevant GitHub issue\)\s*', ' ', clean)
    clean = re.sub(r'Though\s+should', 'Though it should', clean)
    clean = re.sub(r'reverted\s*,\s*fixing', 'reverted the previous change, fixing', clean)

    # 清理行首的空引用
    clean = re.sub(r'^-\s+\s+', '- ', clean, flags=re.MULTILINE)
    clean = re.sub(r'^\*\s+\s+', '* ', clean, flags=re.MULTILINE)

    # 清理多余空白和标点
    clean = re.sub(r'\s*:\s*\.?\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'\s+\)', ')', clean)
    clean = re.sub(r'\(\s+', '(', clean)
    clean = re.sub(r'\(\s*\)', '', clean)
    clean = re.sub(r',\s*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'[^\S\n]{2,}', ' ', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean)

    return clean.strip()


def is_valid_version(name):
    """检查是否是有效的语义版本号格式（如 0.3.0, 0.64.0）"""
    return bool(re.match(r'^\d+\.\d+\.\d+(-[\w.]+)?$', name))


def version_tuple(version):
    """将版本号转换为元组用于比较"""
    v = version.lstrip('v')
    parts = re.split(r'[.-]', v)
    result = []
    for part in parts[:3]:
        if part.isdigit():
            result.append(int(part))
    return tuple(result) if len(result) == 3 else None


def filter_stable_releases(releases):
    """
    过滤掉 alpha 版本和内部构建版本，按发布时间从早到新排序
    返回: [(版本名, 更新内容, release链接), ...]
    """
    stable_releases = []

    for release in releases:
        name = release.get("name") or release.get("tag_name", "")

        # 跳过 alpha 版本
        if "alpha" in name.lower():
            continue

        # 只保留有效的语义版本号格式
        if not is_valid_version(name):
            continue

        # 过滤 0.3.0 之前的版本
        vt = version_tuple(name)
        if vt and vt < (0, 3, 0):
            continue

        body = clean_release_body(release.get("body", ""))
        html_url = release.get("html_url", "")
        published_at = release.get("published_at", "")

        stable_releases.append({
            "name": name,
            "body": body,
            "url": html_url,
            "published_at": published_at
        })

    # 按发布时间从早到新排序
    stable_releases.sort(key=lambda x: x["published_at"])

    return stable_releases


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
    print("OpenAI Codex 历史版本批量推送（排除 alpha）")
    print("=" * 50)

    # 获取所有 releases
    print("正在获取 releases...")
    all_releases = fetch_all_releases()
    print(f"获取到 {len(all_releases)} 个 releases")

    # 过滤稳定版本
    stable_releases = filter_stable_releases(all_releases)
    print(f"稳定版本 {len(stable_releases)} 个（已排除 alpha）")

    # 读取已推送版本
    pushed_versions = read_pushed_versions()
    print(f"已推送 {len(pushed_versions)} 个版本")

    # 过滤未推送版本
    pending_releases = [r for r in stable_releases if r["name"] not in pushed_versions]
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
