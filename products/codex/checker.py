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
import json
import hashlib

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.notify.telegram import send_bilingual_notification, edit_bilingual_notification
from core.translate import translate_changelog
from core.utils import clean_release_body

# 配置
RELEASES_ATOM_URL = "https://github.com/openai/codex/releases.atom"
GITHUB_RELEASE_BY_TAG_URL = "https://api.github.com/repos/openai/codex/releases/tags/{tag}"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
VERSION_FILE = os.path.join(PROJECT_ROOT, "output", "codex_latest_version.txt")
MESSAGE_STATE_FILE = os.path.join(PROJECT_ROOT, "output", "codex_message_state.json")

# GitHub API 配置
GITHUB_TOKEN = os.getenv("GH_TOKEN", "")  # 使用 GH_TOKEN 避免与 GitHub Actions 的 GITHUB_TOKEN 冲突
USER_AGENT = "ai-release-tracker/1.0"

# Telegram 配置（独立环境变量）
TELEGRAM_BOT_TOKEN = os.getenv("CODEX_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CODEX_CHAT_ID", "")

# Atom 命名空间
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# 常见的不稳定版本关键词
UNSTABLE_KEYWORDS = [
    "alpha", "beta", "rc", "preview", "pre",
    "dev", "nightly", "snapshot", "test"
]


def is_unstable_title(title):
    """快速判断标题是否包含常见的不稳定版本关键词"""
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in UNSTABLE_KEYWORDS)


def github_headers():
    """构建 GitHub API 请求头"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def extract_tag_name(link, fallback_title):
    """从 release 链接提取 tag 名称，失败时回退到标题"""
    if link:
        parts = link.rstrip("/").split("/")
        if parts:
            return parts[-1]
    return fallback_title


def verify_release_via_api(tag_name):
    """
    调用 GitHub API 验证是否为稳定 release

    返回:
        (release_data, status) 元组
        - release_data: API 返回的 release 数据（成功时）或 None
        - status: "stable" | "tag_only" | "draft" | "prerelease" |
                  "rate_limited" | "server_error" | "network_error" |
                  "json_error" | "api_error_<code>"
    """
    api_url = GITHUB_RELEASE_BY_TAG_URL.format(tag=tag_name)

    try:
        resp = requests.get(api_url, headers=github_headers(), timeout=10)
    except requests.RequestException as e:
        print(f"  [验证失败] 网络错误: {e}")
        return None, "network_error"

    # 处理不同的状态码
    if resp.status_code == 404:
        return None, "tag_only"
    if resp.status_code == 403:
        return None, "rate_limited"
    if resp.status_code == 401:
        # 认证失败是严重错误，应该立即失败
        return None, "auth_error"
    if resp.status_code >= 500:
        return None, "server_error"
    if resp.status_code != 200:
        # 其他 4xx 错误（如 422）也是严重问题
        return None, f"api_error_{resp.status_code}"

    # 解析响应
    try:
        data = resp.json()
    except ValueError as e:
        print(f"  [验证失败] JSON 解析错误: {e}")
        return None, "json_error"

    # 检查 draft 和 prerelease 标志
    if data.get("draft", False):
        return None, "draft"
    if data.get("prerelease", False):
        return None, "prerelease"

    return data, "stable"


def fetch_releases_feed():
    """从 GitHub 获取 releases Atom feed"""
    try:
        response = requests.get(RELEASES_ATOM_URL, timeout=10)
        response.raise_for_status()
        return response.text, None
    except requests.RequestException as e:
        print(f"获取 releases feed 失败: {e}")
        return None, f"fetch_feed_error: {e}"


def parse_latest_stable_release(feed_xml):
    """
    解析最新的稳定版本（含 API 验证）

    返回:
        (tag_name, title, content, link, error) 元组
        - tag_name: Git tag 名称（用于版本比对和持久化）
        - title: Release 标题（用于显示）
        - content: Release 内容
        - link: Release 链接
        - error: 错误信息（API 故障时）或 None
    """
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as e:
        print(f"解析 XML 失败: {e}")
        return None, None, None, None, f"xml_parse_error: {e}"

    entries = root.findall("atom:entry", ATOM_NS)
    api_errors = []  # 记录 API 错误
    found_stable = None  # 记录找到的稳定版本

    for entry in entries:
        title_elem = entry.find("atom:title", ATOM_NS)
        if title_elem is None:
            continue

        title = title_elem.text.strip()

        # 第一步：快速过滤常见的不稳定版本
        if is_unstable_title(title):
            print(f"  [跳过] {title} (包含不稳定关键词)")
            continue

        # 获取链接和 tag 名称（临时，用于 API 查询）
        link_elem = entry.find("atom:link", ATOM_NS)
        link = link_elem.get("href") if link_elem is not None else ""
        tag_name_from_url = extract_tag_name(link, title)

        # 获取更新内容
        content_elem = entry.find("atom:content", ATOM_NS)
        content = ""
        if content_elem is not None and content_elem.text:
            content = clean_html_content(content_elem.text)

        # 第二步：通过 API 验证是否为稳定 release
        print(f"  [验证] {title} (tag: {tag_name_from_url})")
        release_data, status = verify_release_via_api(tag_name_from_url)

        # 致命错误：立即返回，不继续尝试其他条目
        if status in ("auth_error", "json_error"):
            error_msg = {
                "auth_error": "GitHub 认证失败（Token 无效或过期）",
                "json_error": "API 响应解析失败",
            }.get(status, status)
            print(f"  [致命错误] {title} ({error_msg})")
            return None, None, None, None, f"fatal_error: {status}"

        # 可恢复错误：记录并继续，但最终会返回错误（即使找到了稳定版本）
        if status in ("rate_limited", "server_error", "network_error"):
            error_msg = {
                "rate_limited": "API 速率限制",
                "server_error": "GitHub API 服务器错误",
                "network_error": "网络错误",
            }.get(status, status)
            print(f"  [警告] {title} ({error_msg})")
            api_errors.append(f"{title}: {status}")
            continue

        # 其他 API 错误码（如 422）- 也视为致命错误
        if status.startswith("api_error_"):
            error_code = status.replace("api_error_", "")
            print(f"  [致命错误] {title} (API 错误码: {error_code})")
            return None, None, None, None, f"fatal_error: {status}"

        if status == "stable":
            # 使用 API 返回的规范 tag name（而非从 URL 解析）
            canonical_tag = release_data.get("tag_name", tag_name_from_url)
            print(f"  [确认] 这是一个稳定版本 ✓ (规范 tag: {canonical_tag})")

            # 记录找到的稳定版本，但不立即返回（需要检查是否有 API 错误）
            if found_stable is None:
                found_stable = (canonical_tag, title, content, link)

            # 找到第一个稳定版本后就停止
            break

        # 记录跳过原因（tag_only, draft, prerelease）
        status_messages = {
            "tag_only": "仅有 tag，无 release 对象",
            "draft": "Draft release",
            "prerelease": "Prerelease",
        }
        reason = status_messages.get(status, status)
        print(f"  [跳过] {title} ({reason})")

    # 如果遇到 API 错误，即使找到了稳定版本也要报告
    if api_errors:
        error_summary = "; ".join(api_errors[:3])  # 只显示前 3 个
        print(f"  [错误汇总] 检测到 API 错误: {error_summary}")
        return None, None, None, None, f"api_errors: {error_summary}"

    # 返回找到的稳定版本
    if found_stable:
        return found_stable[0], found_stable[1], found_stable[2], found_stable[3], None

    return None, None, None, None, None


def clean_html_content(html_text):
    """清理 HTML 标签，提取纯文本，然后调用共享清理函数"""
    # 1. 先处理 HTML 实体（原始内容是 &lt;li&gt; 形式，可能有双重编码）
    clean = html_text
    # 处理可能的双重编码（&amp;amp; → &amp; → &）
    while '&amp;' in clean:
        clean = clean.replace('&amp;', '&')
    clean = clean.replace('&lt;', '<').replace('&gt;', '>')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'")
    # 2. 将 <li> 标签转换为换行+列表符号（使用 ASCII 字符兼容 Windows GBK 终端）
    clean = re.sub(r'<li[^>]*>', '\n- ', clean)
    # 3. 移除其他 HTML 标签
    clean = re.sub(r'<[^>]+>', '', clean)
    # 4. 调用共享清理函数进行进一步处理
    return clean_release_body(clean)


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


def resolve_saved_version_to_tag(saved_version):
    """
    尝试将保存的版本（可能是 title）解析为 tag name
    用于处理旧格式迁移和 title 编辑的场景

    返回: (tag_name, is_resolved, error) 元组
        - tag_name: 解析后的 tag name
        - is_resolved: 是否通过 API 解析（True）或原样返回（False）
        - error: 解析失败的错误信息或 None
    """
    # 尝试通过 API 查找对应的 tag（包括可能的 tag 格式）
    # 构造可能的 tag 名称（openai/codex 使用 rust-vX.Y.Z 格式）
    possible_tags = [
        saved_version,  # 首先尝试原值（可能本身就是 tag）
        f"rust-v{saved_version}",
        f"v{saved_version}",
    ]

    network_errors = 0
    api_errors = 0

    for possible_tag in possible_tags:
        api_url = GITHUB_RELEASE_BY_TAG_URL.format(tag=possible_tag)
        try:
            resp = requests.get(api_url, headers=github_headers(), timeout=5)

            if resp.status_code == 401:
                # 认证失败，应该报错
                return saved_version, False, "auth_error"

            if resp.status_code == 200:
                data = resp.json()
                canonical_tag = data.get("tag_name", possible_tag)
                # 只有当解析出的 tag 与原值不同时才显示迁移消息
                if canonical_tag != saved_version:
                    print(f"  [迁移] 解析旧版本 '{saved_version}' → tag '{canonical_tag}'")
                return canonical_tag, canonical_tag != saved_version, None

            if resp.status_code >= 500:
                api_errors += 1

        except requests.RequestException as e:
            # 网络错误
            network_errors += 1

    # 如果所有尝试都失败了（网络错误或服务器错误）
    if network_errors > 0 or api_errors > 0:
        # 检查saved_version 是否看起来像有效的 tag
        if '-v' in saved_version or saved_version.startswith('v') or saved_version.startswith('rust'):
            # 看起来像 tag，但无法验证 - 警告但继续
            print(f"  [警告] 无法验证版本 '{saved_version}'（网络: {network_errors}, API错误: {api_errors}）")
            return saved_version, False, None
        else:
            # 看起来不像 tag，且无法验证 - 这是问题
            print(f"  [错误] 无法验证非标准版本 '{saved_version}'（网络: {network_errors}, API错误: {api_errors}）")
            return saved_version, False, "unable_to_verify"

    # 所有尝试都返回 404 - 说明这个版本不存在
    # 如果看起来像有效的 tag，可能是旧的已删除版本
    if '-v' in saved_version or saved_version.startswith('v') or saved_version.startswith('rust'):
        print(f"  [警告] 版本 '{saved_version}' 在 API 中未找到，可能已被删除")
        return saved_version, False, None

    # 看起来不像 tag，且API 中不存在 - 可能是旧的 title 格式但找不到对应 tag
    print(f"  [警告] 无法解析版本 '{saved_version}' 为有效 tag")
    return saved_version, False, None


def main():
    print("正在检查 OpenAI Codex 更新...")
    print("-" * 50)

    # 显示 GitHub Token 状态
    if GITHUB_TOKEN:
        print("✓ 使用 GitHub Token 进行 API 认证")
    else:
        print("⚠  未配置 GH_TOKEN，API 请求可能受速率限制")
    print("-" * 50)

    # 获取 releases feed
    feed_xml, fetch_error = fetch_releases_feed()
    if fetch_error:
        print("-" * 50)
        print(f"⚠️  获取 feed 失败: {fetch_error}")
        print("提示：请检查网络连接和 GitHub 服务状态")
        return 1  # 返回非零退出码
    if not feed_xml:
        print("-" * 50)
        print("⚠️  获取 feed 失败（未知原因）")
        return 1

    # 解析最新稳定版本
    latest_tag, latest_title, latest_content, release_link, error = parse_latest_stable_release(feed_xml)

    # 处理 API 错误
    if error:
        print("-" * 50)
        print(f"⚠️  检查失败: {error}")
        print("提示：请稍后重试，或检查网络连接和 GitHub API 状态")
        return 1  # 返回非零退出码

    if not latest_tag:
        print("-" * 50)
        print("未找到稳定版本")
        return 0

    print("-" * 50)
    print(f"远程最新稳定版本: {latest_title}")
    print(f"Tag: {latest_tag}")
    if release_link:
        print(f"链接: {release_link}")

    # 读取本地保存的版本
    saved_version = read_saved_version()

    if saved_version is None:
        # 首次运行
        print("-" * 50)
        print(f"首次运行，已记录版本 {latest_tag}")
        save_version(latest_tag)
        return 0

    # 智能解析保存的版本为 tag（处理旧格式和 title 编辑）
    saved_tag, was_resolved, resolve_error = resolve_saved_version_to_tag(saved_version)

    # 如果解析过程中遇到认证错误，应该失败
    if resolve_error == "auth_error":
        print("-" * 50)
        print("⚠️  版本迁移失败：GitHub 认证失败")
        print("提示：请检查 GH_TOKEN 是否有效")
        return 1

    # 如果无法验证非标准版本格式，警告但继续（允许用户手动处理）
    if resolve_error == "unable_to_verify":
        print("-" * 50)
        print("⚠️  警告：无法验证保存的版本格式")
        print(f"    保存的版本: {saved_version}")
        print(f"    最新版本: {latest_tag}")
        print("    建议：如果这是新安装，将自动使用最新版本")

    # 比对版本
    if saved_tag == latest_tag:
        # 版本相同，检查 body 是否有更新
        print("-" * 50)
        print(f"当前已是最新稳定版本")

        # 检查 body 是否有变化（用于处理开发者延迟更新 release notes 的情况）
        current_body_hash = compute_body_hash(latest_content)
        message_state = read_message_state()

        if message_state and message_state.get("version") == latest_tag:
            saved_body_hash = message_state.get("body_hash", "")
            saved_message_ids = message_state.get("message_ids", [])

            # 检查 body 是否有变化且之前的 body 是空的
            if saved_body_hash != current_body_hash and saved_message_ids:
                print("-" * 50)
                print("检测到 Release Notes 已更新，正在编辑之前发送的通知...")

                # 翻译新内容
                original_content = latest_content or "（暂无更新说明）"
                translated = translate_changelog(latest_content) if latest_content else ""

                # 编辑之前发送的消息
                edit_result = edit_bilingual_notification(
                    message_ids=saved_message_ids,
                    version=latest_title,
                    original=original_content,
                    translated=translated,
                    title="OpenAI Codex",
                    bot_token=TELEGRAM_BOT_TOKEN,
                    chat_id=TELEGRAM_CHAT_ID,
                    version_url=release_link
                )

                if edit_result["success"]:
                    print("消息编辑成功")
                    # 更新 body_hash 和可能变化的 message_ids
                    save_message_state(latest_tag, edit_result["message_ids"], current_body_hash)
                else:
                    print("消息编辑失败，可能消息已被删除")

        # 如果刚刚解析了旧格式，更新版本文件
        if was_resolved:
            save_version(latest_tag)
        return 0
    else:
        # 有新版本
        print("-" * 50)
        print(f"发现新版本！ {saved_version} → {latest_tag}")
        print("-" * 50)
        if latest_content:
            print("更新内容：")
            try:
                print(latest_content)
            except UnicodeEncodeError:
                print("(内容包含特殊字符，已跳过终端显示，请查看输出文件)")
        else:
            print("（暂无更新说明）")
        print("-" * 50)
        save_version(latest_tag)
        print("版本信息已更新")

        # 翻译更新内容
        original_content = latest_content or "（暂无更新说明）"
        translated = translate_changelog(latest_content) if latest_content else ""

        # 调试：将内容写入本地文件
        debug_output = os.path.join(PROJECT_ROOT, "output", "codex_debug_content.txt")
        with open(debug_output, 'w', encoding='utf-8') as f:
            f.write(f"Tag: {latest_tag}\n")
            f.write(f"Title: {latest_title}\n")
            f.write(f"链接: {release_link}\n")
            f.write("=" * 50 + "\n")
            f.write("原文:\n")
            f.write(original_content + "\n")
            f.write("=" * 50 + "\n")
            f.write("翻译:\n")
            f.write(translated + "\n")
        print(f"调试内容已保存到: {debug_output}")

        # 发送 Telegram 通知
        notify_result = send_bilingual_notification(
            version=latest_title,  # 使用 title 作为显示版本号（更友好）
            original=original_content,
            translated=translated,
            title="OpenAI Codex",
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID,
            version_url=release_link
        )

        # 保存消息状态（用于后续 body 更新时编辑消息）
        if notify_result["success"] and notify_result["message_ids"]:
            body_hash = compute_body_hash(latest_content)
            save_message_state(latest_tag, notify_result["message_ids"], body_hash)
            print(f"消息状态已保存 (message_ids: {notify_result['message_ids']})")

        return 0


if __name__ == "__main__":
    import sys
    exit_code = main()
    if exit_code:
        sys.exit(exit_code)
