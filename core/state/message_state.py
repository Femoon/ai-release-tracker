#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享的 Telegram 消息状态读写模块

每个产品（claude_code / codex / openclaw）的 checker 在 output/ 下维护一个
*_message_state.json 文件，记录已发送的版本通知消息 ID、内容 hash 和
"body-changed 已触发编辑次数"。

`edit_count` 用于限制 body-changed 分支的触发频率：每个版本号只允许编辑
一次，避免上游 CHANGELOG 反复微调时反复调用 LLM 翻译 + 重发 Telegraph。
"""

import hashlib
import json
import os

# 每个版本号下允许的最大编辑次数。超过即只更新 hash、跳过翻译和消息编辑。
MAX_EDITS_PER_VERSION = 1


def compute_body_hash(body: str) -> str:
    """计算 body 内容的 md5 hash"""
    if not body:
        return ""
    return hashlib.md5(body.encode("utf-8")).hexdigest()


def read_message_state(state_file: str) -> dict | None:
    """
    读取消息状态文件

    Returns:
        dict: {"version": str, "message_ids": list, "body_hash": str, "edit_count": int}
              或 None（文件不存在 / 解析失败）
    """
    if not os.path.exists(state_file):
        return None
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 旧文件向后兼容：edit_count 默认 0
        data.setdefault("edit_count", 0)
        return data
    except Exception as e:
        print(f"读取消息状态文件失败: {e}")
        return None


def save_message_state(
    state_file: str,
    version: str,
    message_ids: list,
    body_hash: str,
    edit_count: int = 0,
) -> bool:
    """保存消息状态到文件"""
    try:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        state = {
            "version": version,
            "message_ids": message_ids,
            "body_hash": body_hash,
            "edit_count": edit_count,
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存消息状态失败: {e}")
        return False


def clear_message_state(state_file: str) -> bool:
    """清理消息状态文件（用于消息已被删除等无法恢复的场景）"""
    try:
        if os.path.exists(state_file):
            os.remove(state_file)
            print("消息状态已清理")
        return True
    except Exception as e:
        print(f"清理消息状态失败: {e}")
        return False


def is_edit_locked(state: dict | None, version: str) -> bool:
    """
    判断当前版本是否已达 body-changed 编辑次数上限。

    锁定后调用方应只更新 hash、跳过翻译和消息编辑。版本号变化（走"新版本"
    路径）时由调用方写回 edit_count=0 来解锁。
    """
    if not state:
        return False
    if state.get("version") != version:
        return False
    return state.get("edit_count", 0) >= MAX_EDITS_PER_VERSION
