#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check stable NousResearch/hermes-agent GitHub Releases."""

import argparse
import html
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.notify.telegram import edit_bilingual_notification, send_bilingual_notification
from core.state import (
    compute_body_hash,
    is_edit_locked,
    read_message_state as _read_message_state,
    save_message_state as _save_message_state,
)
from core.translate import translate_changelog
from products.hermes.content import notification_content_kind, select_notification_content


RELEASES_API_URL = "https://api.github.com/repos/NousResearch/hermes-agent/releases"
RELEASES_ATOM_URL = "https://github.com/NousResearch/hermes-agent/releases.atom"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
VERSION_FILE = os.path.join(PROJECT_ROOT, "output", "hermes_latest_version.txt")
MESSAGE_STATE_FILE = os.path.join(PROJECT_ROOT, "output", "hermes_message_state.json")

GITHUB_TOKEN = os.getenv("GH_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("HERMES_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("HERMES_CHAT_ID", "")
USER_AGENT = "ai-release-tracker/1.0"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
SEMVER_PATTERN = re.compile(r"Hermes Agent\s+(v\d+\.\d+\.\d+)", re.IGNORECASE)
UNSTABLE_PATTERN = re.compile(r"(?:^|[-_.\s])(alpha|beta|rc|preview|dev|nightly)(?:$|[-_.\s])", re.IGNORECASE)


def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def notification_configured():
    return bool(TELEGRAM_BOT_TOKEN.strip() and TELEGRAM_CHAT_ID.strip())


def normalize_release(data):
    """Normalize a GitHub API release into the checker representation."""
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None
    return {
        "tag": tag,
        "name": str(data.get("name") or tag).strip(),
        # Hermes has product-specific cleanup rules. Keep the API body intact
        # until content selection so issue links do not turn into empty links.
        "body": str(data.get("body") or "").strip(),
        "url": str(data.get("html_url") or "").strip(),
        "published_at": str(data.get("published_at") or data.get("created_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
    }


def fetch_releases_api(per_page=10, stop_at_tag=None, paginate_all=False):
    """Fetch recent stable releases. Return (releases, error)."""
    releases = []
    page = 1
    while True:
        try:
            response = requests.get(
                RELEASES_API_URL,
                params={"per_page": per_page, "page": page},
                headers=github_headers(),
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                return None, "GitHub Releases API 返回了非列表数据"
        except (requests.RequestException, ValueError) as exc:
            return None, str(exc)

        found_saved_tag = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("draft") or item.get("prerelease"):
                continue
            release = normalize_release(item)
            if release:
                releases.append(release)
                if release["tag"] == stop_at_tag:
                    found_saved_tag = True

        # One page is enough for normal/first runs. History migration can opt
        # into complete pagination, while saved-tag runs continue until found.
        if (
            found_saved_tag
            or len(payload) < per_page
            or (not stop_at_tag and not paginate_all)
        ):
            break
        page += 1
    return releases, None


def _clean_atom_content(content):
    content = html.unescape(content or "")
    content = re.sub(r"<li[^>]*>", "\n- ", content, flags=re.IGNORECASE)
    content = re.sub(r"</(?:p|div|h[1-6]|ul|ol)>\s*", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"<[^>]+>", "", content)
    return html.unescape(content).strip()


def parse_atom_releases(feed_xml):
    """Parse the public GitHub Releases Atom feed as a degraded fallback."""
    root = ET.fromstring(feed_xml)
    releases = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title_elem = entry.find("atom:title", ATOM_NS)
        link_elem = entry.find("atom:link", ATOM_NS)
        content_elem = entry.find("atom:content", ATOM_NS)
        updated_elem = entry.find("atom:updated", ATOM_NS)
        title = (title_elem.text or "").strip() if title_elem is not None else ""
        link = link_elem.get("href", "") if link_elem is not None else ""
        tag = link.rstrip("/").split("/")[-1] if "/releases/tag/" in link else ""
        # Atom does not expose GitHub's prerelease boolean. Fail closed on
        # conventional prerelease markers when REST is unavailable.
        if not tag or UNSTABLE_PATTERN.search(f"{tag} {title}"):
            continue
        releases.append({
            "tag": tag,
            "name": title or tag,
            "body": _clean_atom_content(content_elem.text if content_elem is not None else ""),
            "url": link,
            "published_at": (updated_elem.text or "") if updated_elem is not None else "",
            "updated_at": (updated_elem.text or "") if updated_elem is not None else "",
        })
    return releases


def fetch_releases_atom():
    try:
        response = requests.get(RELEASES_ATOM_URL, timeout=15)
        response.raise_for_status()
        return parse_atom_releases(response.text), None
    except (requests.RequestException, ET.ParseError) as exc:
        return None, str(exc)


def fetch_releases(saved_tag=None):
    releases, api_error = fetch_releases_api(stop_at_tag=saved_tag)
    if api_error is None:
        return releases, "GitHub Releases API", None

    print(f"GitHub Releases API 获取失败，尝试 Atom 备用源: {api_error}")
    releases, atom_error = fetch_releases_atom()
    if atom_error is not None:
        return None, None, f"REST: {api_error}; Atom: {atom_error}"
    return releases, "GitHub Releases Atom（备用）", None


def display_version(release):
    """Display both Hermes SemVer and its canonical CalVer tag."""
    match = SEMVER_PATTERN.search(release["name"])
    if match:
        return f"{match.group(1)} ({release['tag']})"
    return release["name"] or release["tag"]


def _timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0


def stable_releases_oldest_first(releases):
    return sorted(releases, key=lambda release: (_timestamp(release["published_at"]), release["tag"]))


def _calver_tuple(tag):
    match = re.fullmatch(r"v(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d+))?", tag or "")
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def pending_releases(releases, saved_tag):
    """Return releases newer than saved_tag, in publish order."""
    ordered = stable_releases_oldest_first(releases)
    if not saved_tag:
        return []
    for index, release in enumerate(ordered):
        if release["tag"] == saved_tag:
            return ordered[index + 1:]
    # The saved release fell outside the ten-entry window. Process the visible
    # stable releases instead of silently jumping to only the newest one.
    saved_calver = _calver_tuple(saved_tag)
    latest_calver = _calver_tuple(ordered[-1]["tag"]) if ordered else None
    if saved_calver and latest_calver and latest_calver <= saved_calver:
        return []
    if saved_calver:
        return [
            release
            for release in ordered
            if (_calver_tuple(release["tag"]) or (0, 0, 0, 0)) > saved_calver
        ]
    return ordered


def read_saved_version():
    if not os.path.exists(VERSION_FILE):
        return None
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as file:
            return file.read().strip() or None
    except OSError as exc:
        print(f"读取 Hermes 版本文件失败: {exc}")
        return None


def save_version(version):
    try:
        os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
        with open(VERSION_FILE, "w", encoding="utf-8") as file:
            file.write(version)
        return True
    except OSError as exc:
        print(f"保存 Hermes 版本文件失败: {exc}")
        return False


def read_message_state():
    return _read_message_state(MESSAGE_STATE_FILE)


def save_message_state(version, message_ids, body_hash, edit_count=0):
    return _save_message_state(MESSAGE_STATE_FILE, version, message_ids, body_hash, edit_count)


def _notification_content(release):
    return select_notification_content(release["body"])


def notify_release(release):
    """Translate and notify one release. State advances only after success."""
    if not notification_configured():
        print("Hermes Telegram 频道未配置，跳过翻译和通知")
        return True, []

    original = _notification_content(release)
    translated = translate_changelog(original) if release["body"] else ""
    if release["body"] and original.strip() and not translated:
        print("Hermes 更新日志翻译失败，版本状态未更新，下次检查将重试")
        return False, []

    result = send_bilingual_notification(
        version=display_version(release),
        original=original,
        translated=translated,
        title="Hermes Agent",
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        version_url=release["url"],
        show_language_labels=True,
        content_kind=notification_content_kind(original),
    )
    if not result["success"]:
        print("Hermes Telegram 通知发送失败")
        return False, []
    return True, result.get("message_ids", [])


def maybe_edit_latest_release(release):
    """Edit a previously sent latest-release message if its body changed."""
    if not notification_configured():
        return True
    state = read_message_state()
    if not state or state.get("version") != release["tag"] or not state.get("message_ids"):
        return True

    body_hash = compute_body_hash(release["body"])
    if state.get("body_hash", "") == body_hash:
        return True
    if is_edit_locked(state, release["tag"]):
        print("Hermes Release Notes 已更新，但本版本已达消息编辑上限")
        return save_message_state(
            release["tag"], state["message_ids"], body_hash, state.get("edit_count", 0)
        )

    print("检测到 Hermes Release Notes 更新，正在编辑之前的通知...")
    original = _notification_content(release)
    translated = translate_changelog(original) if release["body"] else ""
    if release["body"] and original.strip() and not translated:
        print("Hermes 更新日志翻译失败，保留消息状态以便下次重试")
        return False

    result = edit_bilingual_notification(
        message_ids=state["message_ids"],
        version=display_version(release),
        original=original,
        translated=translated,
        title="Hermes Agent",
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        version_url=release["url"],
        show_language_labels=True,
        content_kind=notification_content_kind(original),
    )
    if not result["success"]:
        print("Hermes Telegram 消息编辑失败")
        return False
    return save_message_state(
        release["tag"],
        result["message_ids"],
        body_hash,
        state.get("edit_count", 0) + 1,
    )


def main():
    parser = argparse.ArgumentParser(description="Hermes Agent 版本更新检查脚本")
    parser.add_argument("-f", "--force", action="store_true", help="强制推送最新版本，不更新版本记录")
    args = parser.parse_args()

    print("正在检查 Hermes Agent 更新...")
    print("-" * 50)
    saved_tag = None if args.force else read_saved_version()
    releases, source, error = fetch_releases(saved_tag=saved_tag)
    if error:
        print(f"Hermes 版本源获取失败: {error}")
        return 1
    if not releases:
        print("未找到 Hermes 稳定版本")
        return 1

    ordered = stable_releases_oldest_first(releases)
    latest = ordered[-1]
    print(f"数据源: {source}")
    print(f"远程最新版本: {display_version(latest)}")

    if args.force:
        print("强制模式：推送最新版本，不更新本地记录")
        success, _ = notify_release(latest)
        return 0 if success else 1

    if saved_tag is None:
        if not save_version(latest["tag"]):
            return 1
        print(f"首次运行，已记录基线版本 {latest['tag']}")
        if not notification_configured():
            print("Hermes Telegram 频道暂未配置")
        return 0

    pending = pending_releases(releases, saved_tag)
    if not pending:
        print(f"当前已是最新稳定版本: {saved_tag}")
        return 0 if maybe_edit_latest_release(latest) else 1

    print(f"发现 {len(pending)} 个 Hermes 新版本: {saved_tag} → {latest['tag']}")
    for release in pending:
        print("-" * 50)
        print(f"处理 {display_version(release)}")
        if release["body"]:
            print(release["body"])
        success, message_ids = notify_release(release)
        if not success:
            return 1
        if not save_version(release["tag"]):
            return 1
        if message_ids:
            save_message_state(
                release["tag"], message_ids, compute_body_hash(release["body"]), edit_count=0
            )
        print(f"Hermes 版本状态已更新为 {release['tag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
