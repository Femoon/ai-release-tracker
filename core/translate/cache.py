#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译结果落盘缓存

相同 (model, source_text) 的翻译结果只调用 LLM 一次，后续命中直接复用，
避免上游 changelog 反复抖动时重复消耗 API 配额。
"""

import hashlib
import json
import os
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
CACHE_DIR = os.path.join(PROJECT_ROOT, "output", "translation_cache")


def _cache_key(text: str, model: str, kind: str) -> str:
    """根据 (kind, model, text) 计算 sha256 缓存键"""
    payload = f"{kind}\n{model}\n{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def get(text: str, model: str, kind: str = "translate") -> str | None:
    """
    查询缓存，命中返回翻译结果，未命中返回 None。

    kind: "translate" 或 "summarize"，区分两类不同的 prompt。
    """
    if not text or not model:
        return None
    try:
        path = _cache_path(_cache_key(text, model, kind))
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = data.get("translated", "")
        if result:
            return result
        return None
    except Exception as e:
        print(f"翻译缓存读取失败 (忽略): {e}")
        return None


def set(text: str, model: str, translated: str, kind: str = "translate") -> None:
    """
    写入缓存。空翻译结果不缓存。
    """
    if not text or not model or not translated:
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        key = _cache_key(text, model, kind)
        path = _cache_path(key)
        payload = {
            "kind": kind,
            "model": model,
            "len_in": len(text),
            "len_out": len(translated),
            "created_at": int(time.time()),
            "translated": translated,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"翻译缓存写入失败 (忽略): {e}")
