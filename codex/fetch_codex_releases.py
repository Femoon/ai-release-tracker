#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取 OpenAI Codex 所有 releases 日志并保存到文件
"""

import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

RELEASES_API_URL = "https://api.github.com/repos/openai/codex/releases"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
OUTPUT_FILE = "output/codex_releases.txt"


def fetch_all_releases():
    """通过 GitHub API 获取所有 releases"""
    all_releases = []
    page = 1
    per_page = 100

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        print("使用 GitHub Token 认证")
    else:
        print("警告: 未配置 GITHUB_TOKEN，可能遇到速率限制")

    while True:
        url = f"{RELEASES_API_URL}?page={page}&per_page={per_page}"
        print(f"获取第 {page} 页...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        releases = response.json()

        if not releases:
            break

        all_releases.extend(releases)
        page += 1

    return all_releases


def clean_body(body):
    """清理 release body"""
    if not body:
        return ""

    # 移除 PRs Merged / Merged PRs / PRs 部分及后面所有内容
    clean = re.sub(r'\n##\s*PRs?\s*Merged.*', '', body, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'\n###\s*PRs?\s*Merged.*', '', clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'\n##\s*Merged\s*PRs?.*', '', clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'\n###\s*PRs?\s*$.*', '', clean, flags=re.DOTALL | re.IGNORECASE)  # ### PRs

    # 移除 Full Changelog 行
    clean = re.sub(r'\*?\*?Full Changelog\*?\*?:?.*', '', clean, flags=re.IGNORECASE)

    # 移除 PR 列表行（各种格式）
    clean = re.sub(r'^[-*]\s+.*(?:by @|— @).*(?:in #\d+|#\d+).*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^[-*]\s+.*\(#\d+\)\s*—\s*@.*$', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^#\d+\s+[–—-]\s+.*$', '', clean, flags=re.MULTILINE)  # #5897 – xxx 格式

    # 移除内联的 PR/Issue 引用（如 #6222, (#6189)）
    clean = re.sub(r'\s*\(#\d+(?:\s+#\d+)*\)', '', clean)  # (#6189) 或 (#6406 #6517)
    clean = re.sub(r'#\d+(?:\s+#\d+)*', '', clean)  # #6222 #6189

    # 移除 PR/Issue 链接
    clean = re.sub(r'https://github\.com/openai/codex/pull/\d+', '', clean)
    clean = re.sub(r'https://github\.com/openai/codex/issues/\d+', '', clean)

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
    clean = re.sub(r'gracefully\s+- ', 'gracefully\n- ', clean)
    clean = re.sub(r'though from the additional details on\s*,', 'though', clean)
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


def version_tuple(version):
    """将版本号转换为元组用于比较"""
    # 移除 v 前缀
    v = version.lstrip('v')
    # 分割版本号，只取数字部分
    parts = re.split(r'[.-]', v)
    result = []
    for part in parts[:3]:  # 只取前3个数字
        if part.isdigit():
            result.append(int(part))
    return tuple(result) if len(result) == 3 else None


def is_valid_version(name):
    """检查是否是有效的语义版本号格式（如 0.3.0, 0.64.0）"""
    # 匹配 X.Y.Z 或 X.Y.Z-beta 等格式
    return bool(re.match(r'^\d+\.\d+\.\d+(-[\w.]+)?$', name))


def main():
    print("拉取 OpenAI Codex Releases")
    print("=" * 50)

    # 获取所有 releases
    all_releases = fetch_all_releases()
    print(f"\n共获取 {len(all_releases)} 个 releases")

    # 过滤有效版本（排除 alpha 和内部构建版本）
    stable_releases = []
    for release in all_releases:
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

        stable_releases.append({
            "name": name,
            "body": clean_body(release.get("body", "")),
            "url": release.get("html_url", ""),
            "published_at": release.get("published_at", "")
        })

    # 按发布时间从早到新排序
    stable_releases.sort(key=lambda x: x["published_at"])

    print(f"稳定版本（>=0.3.0，排除 alpha）: {len(stable_releases)} 个")

    # 输出到文件
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for release in stable_releases:
            # 版本号作为超链接
            f.write(f"## [{release['name']}]({release['url']})\n\n")
            if release['body']:
                f.write(release['body'])
            else:
                f.write("（暂无更新说明）")
            f.write("\n\n" + "=" * 60 + "\n\n")

    print(f"\n已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
