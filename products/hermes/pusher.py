#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Push Hermes Agent historical GitHub Releases to Telegram."""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.notify.telegram import edit_bilingual_notification, send_bilingual_notification
from core.translate import translate_changelog
from products.hermes.checker import display_version, fetch_releases_api, stable_releases_oldest_first
from products.hermes.content import notification_content_kind, select_notification_content


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PUSHED_VERSIONS_FILE = os.path.join(PROJECT_ROOT, "output", "hermes_pushed_versions.txt")
PUSH_STATE_FILE = os.path.join(PROJECT_ROOT, "output", "hermes_push_state.json")
TELEGRAM_BOT_TOKEN = os.getenv("HERMES_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("HERMES_CHAT_ID", "")
PUSH_DELAY = 3
MAX_RETRY = 3
FORMAT_VERSION = 3


def fetch_all_releases():
    """Fetch every stable GitHub Release, oldest first."""
    releases, error = fetch_releases_api(per_page=100, paginate_all=True)
    if error:
        return None, error
    return stable_releases_oldest_first(releases), None


def read_pushed_versions():
    if not os.path.exists(PUSHED_VERSIONS_FILE):
        return set()
    try:
        with open(PUSHED_VERSIONS_FILE, "r", encoding="utf-8") as file:
            return {line.strip() for line in file if line.strip()}
    except OSError as exc:
        print(f"读取 Hermes 已推送版本失败: {exc}")
        return set()


def append_pushed_version(tag):
    try:
        os.makedirs(os.path.dirname(PUSHED_VERSIONS_FILE), exist_ok=True)
        with open(PUSHED_VERSIONS_FILE, "a", encoding="utf-8") as file:
            file.write(f"{tag}\n")
        return True
    except OSError as exc:
        print(f"记录 Hermes 已推送版本失败: {exc}")
        return False


def read_push_state():
    if not os.path.exists(PUSH_STATE_FILE):
        return {}
    try:
        with open(PUSH_STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        print(f"读取 Hermes 推送状态失败: {exc}")
        return {}


def save_push_state(state):
    """Atomically save per-release message IDs and format migration progress."""
    try:
        os.makedirs(os.path.dirname(PUSH_STATE_FILE), exist_ok=True)
        file_descriptor, temp_file = tempfile.mkstemp(
            prefix=".hermes_push_state.", suffix=".tmp", dir=os.path.dirname(PUSH_STATE_FILE)
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(temp_file, PUSH_STATE_FILE)
        return True
    except OSError as exc:
        if "temp_file" in locals():
            try:
                os.unlink(temp_file)
            except FileNotFoundError:
                pass
        print(f"记录 Hermes 推送状态失败: {exc}")
        return False


def acquire_push_lock():
    """Acquire a non-blocking process lock for stateful push/edit runs."""
    try:
        os.makedirs(os.path.dirname(PUSH_STATE_FILE), exist_ok=True)
        lock_file = open(f"{PUSH_STATE_FILE}.lock", "a+", encoding="utf-8")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except (OSError, BlockingIOError):
        if "lock_file" in locals():
            lock_file.close()
        return None


def release_push_lock(lock_file):
    if lock_file is None:
        return
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    lock_file.close()


def release_content_hash(release):
    content = select_notification_content(release["body"])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def update_push_state(state, release, result):
    message_ids = result.get("message_ids") or []
    if not message_ids:
        print("Telegram 返回成功但没有 message_id，拒绝更新推送状态")
        return False
    state[release["tag"]] = {
        "message_id": message_ids[0],
        "telegraph_url": result.get("telegraph_url"),
        "format_version": FORMAT_VERSION,
        "content_hash": release_content_hash(release),
    }
    return save_push_state(state)


def select_pending(releases, pushed, count=3, push_all=False, target_tag=None):
    pending = [release for release in releases if release["tag"] not in pushed]
    if target_tag:
        return [release for release in pending if release["tag"] == target_tag]
    return pending if push_all else pending[:count]


def deliver_release(release, message_id=None):
    content = select_notification_content(release["body"])
    print(f"  原文 {len(release['body'])} 字符，通知内容 {len(content)} 字符")
    print("  正在翻译...")
    translated = translate_changelog(content) if release["body"] else ""
    if release["body"] and content.strip() and not translated:
        print("  [FAIL] 翻译失败")
        return False

    for retry in range(MAX_RETRY):
        if retry:
            print(f"  第 {retry + 1} 次发送重试...")
            time.sleep(PUSH_DELAY)
        kwargs = {
            "version": display_version(release),
            "original": content,
            "translated": translated,
            "title": "Hermes Agent",
            "bot_token": TELEGRAM_BOT_TOKEN,
            "chat_id": TELEGRAM_CHAT_ID,
            "version_url": release["url"],
            "show_language_labels": True,
            "content_kind": notification_content_kind(content),
        }
        if message_id is None:
            result = send_bilingual_notification(**kwargs)
        else:
            result = edit_bilingual_notification(message_ids=[message_id], **kwargs)
        if result["success"]:
            return result
    return None


def _run_main(
    count=3,
    push_all=False,
    target_tag=None,
    dry_run=False,
    edit_all=False,
    edit_tag=None,
):
    edit_mode = edit_all or bool(edit_tag)
    print("Hermes Agent 历史消息格式迁移" if edit_mode else "Hermes Agent 历史版本批量推送")
    print("=" * 50)
    if not dry_run and (not TELEGRAM_BOT_TOKEN.strip() or not TELEGRAM_CHAT_ID.strip()):
        print("Hermes Telegram 配置未设置")
        return 1

    releases, error = fetch_all_releases()
    if error:
        print(f"获取 Hermes Releases 失败: {error}")
        return 1

    push_state = read_push_state()
    pushed_versions = read_pushed_versions()
    pushed = pushed_versions | set(push_state)
    pending_all = [release for release in releases if release["tag"] not in pushed]
    if edit_mode:
        missing_mappings = sorted(pushed_versions - set(push_state))
        if missing_mappings:
            print(
                "以下已推送版本缺少 Telegram message_id 映射，拒绝静默跳过: "
                + ", ".join(missing_mappings)
            )
            return 1
        selected = [
            release
            for release in releases
            if release["tag"] in push_state
            and (
                release["tag"] == edit_tag
                if edit_tag
                else (
                    push_state[release["tag"]].get("format_version", 1) < FORMAT_VERSION
                    or push_state[release["tag"]].get("content_hash")
                    != release_content_hash(release)
                )
            )
        ]
    else:
        selected = select_pending(releases, pushed, count, push_all, target_tag)
    print(f"稳定版本 {len(releases)} 个；已推送 {len(pushed)} 个；待推送 {len(pending_all)} 个")
    if edit_tag and not selected:
        print(f"目标版本 {edit_tag} 没有历史消息映射")
        return 1
    if target_tag and not selected:
        print(f"目标版本 {target_tag} 不存在或已经推送")
        return 1
    if not selected:
        print("没有待编辑的历史消息" if edit_mode else "没有待推送的版本")
        return 0
    print(f"本次处理 {len(selected)} 个版本")

    if dry_run:
        for release in selected:
            content = select_notification_content(release["body"])
            message_id = push_state.get(release["tag"], {}).get("message_id")
            print(
                f"{release['tag']}\t{display_version(release)}\t"
                f"原文={len(release['body'])}\t通知={len(content)}\t"
                f"类型={notification_content_kind(content)}\tmessage_id={message_id or '-'}"
            )
        return 0

    success_count = 0
    for index, release in enumerate(selected, 1):
        action = "编辑" if edit_mode else "推送"
        print(f"\n[{index}/{len(selected)}] {action} {display_version(release)}")
        message_id = push_state[release["tag"]]["message_id"] if edit_mode else None
        result = deliver_release(release, message_id=message_id)
        if not result:
            print(f"  [FAIL] {release['tag']} {action}失败，停止运行")
            break
        if not update_push_state(push_state, release, result):
            print(f"  [FAIL] {action}成功但状态记录失败，停止运行")
            break
        if not edit_mode and release["tag"] not in read_pushed_versions():
            if not append_pushed_version(release["tag"]):
                print("  [FAIL] 推送成功但版本记录失败，停止运行")
                break
        success_count += 1
        print(f"  [OK] {release['tag']} {action}成功")
        if index < len(selected):
            time.sleep(PUSH_DELAY)

    print("-" * 50)
    action = "编辑" if edit_mode else "推送"
    print(f"{action}完成: 成功 {success_count}/{len(selected)}")
    return 0 if success_count == len(selected) else 1


def main(
    count=3,
    push_all=False,
    target_tag=None,
    dry_run=False,
    edit_all=False,
    edit_tag=None,
):
    if dry_run:
        return _run_main(count, push_all, target_tag, dry_run, edit_all, edit_tag)

    lock_file = acquire_push_lock()
    if lock_file is None:
        print("另一个 Hermes pusher 正在运行，拒绝并发修改推送状态")
        return 1
    try:
        return _run_main(count, push_all, target_tag, dry_run, edit_all, edit_tag)
    finally:
        release_push_lock(lock_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Agent 历史版本批量推送")
    parser.add_argument("--count", type=int, default=3, help="推送数量（默认 3）")
    parser.add_argument("--all", action="store_true", help="推送所有未推送版本")
    parser.add_argument("--tag", help="只推送指定 CalVer tag，例如 v2026.5.29.2")
    edit_group = parser.add_mutually_exclusive_group()
    edit_group.add_argument("--edit-all", action="store_true", help="迁移所有旧格式历史消息")
    edit_group.add_argument("--edit-tag", help="只编辑指定 CalVer tag 的历史消息")
    parser.add_argument("--dry-run", action="store_true", help="只检查裁剪结果，不翻译或发送")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count 必须大于 0")
    if (args.edit_all or args.edit_tag) and (args.all or args.tag):
        parser.error("编辑参数不能与 --all/--tag 同时使用")
    sys.exit(
        main(
            args.count,
            args.all,
            args.tag,
            args.dry_run,
            args.edit_all,
            args.edit_tag,
        )
    )
