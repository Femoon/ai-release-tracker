#!/usr/bin/env python3
"""Prepare/replay in-place Telegram repairs. Never sends or deletes messages."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.notify.telegram import clean_for_telegram, process_message_for_markdown_v2, release_source_url
from scripts.audit_channel_history import parse_channel, source_overrides

CONFIG = {
    "claude_code_push": ("Claude Code", "CLAUDE_CODE"),
    "codex_push": ("OpenAI Codex", "CODEX"),
    "openclaw_push": ("OpenClaw", "OPENCLAW"),
    "hermes_push": ("Hermes Agent", "HERMES"),
}
_RATE_LOCK = threading.Lock()
_NEXT_REQUEST = {}


def wait_for_edit_slot(channel):
    # Telegram applies a shared per-chat quota, including concurrent workers.
    with _RATE_LOCK:
        now = time.monotonic()
        start = max(now, _NEXT_REQUEST.get(channel, now))
        _NEXT_REQUEST[channel] = start + 3.2
    if start > now:
        time.sleep(start - now)

CORRECTIONS = {
    "codex_push/243": [("模型分辨率", "模型名称解析")],
    "codex_push/245": [("具备网络能力的模型", "具备网络安全能力的模型")],
    "codex_push/246": [("codex-package-", "`codex-package-<target>`")],
    "codex_push/251": [("保留的镜像", "保留的图片"), ("修剪较旧的镜像", "移除较旧的图片")],
    "openclaw_push/111": [("Discord/飞书的轮询", "Discord/Telegram 的轮询")],
    "hermes_push/31": [("卡死任务重新武装", "重新启用卡死的任务")],
    "hermes_push/32": [("漏发表面处理", "提示错过的定时执行")],
    "hermes_push/33": [("无 opencode 的零认证提供方", "`opencode-free` 免认证提供商")],
    "hermes_push/37": [
        ("secondary profiles no longer inherit allow-lists, credentials, vault secrets, or `.env`/`auth.json` files from the default profile", "fixed allow-list inheritance, credential misrouting and cross-profile secret access; MEDIA delivery cannot attach another profile's `.env`, `auth.json` or `state.db`"),
        ("次要 profile 不再继承默认 profile 的 allow-list、凭据、vault secrets 或 `.env`/`auth.json` 文件", "修复 allow-list 继承、凭据错发及跨 profile 密钥访问；阻止通过媒体附件发送其他 profile 的 `.env`、`auth.json` 或 `state.db`"),
        ("免密码凭据 vault", "对 agent 隐藏密码的凭据保管库"),
    ],
    "claude_code_push/601": [
        ("Fixed Bash commands the permission checker can't fully analyze bypassing prompts under `permissions.blockReadsOutsideWorkingDirectories`, including hidden dangerous `rm` in subshells", "Fixed missing prompts for unanalyzable Bash commands under `permissions.blockReadsOutsideWorkingDirectories`; separately fixed dangerous `rm` hidden in subshells under bypass mode"),
        ("修复权限检查器无法完全分析的 Bash 命令在 `permissions.blockReadsOutsideWorkingDirectories` 下跳过提示的问题，包括子 shell 中隐藏的危险 `rm`", "修复无法完整分析的 Bash 命令在 `permissions.blockReadsOutsideWorkingDirectories` 下漏掉授权提示的问题；另修复 bypass mode 下子 shell 隐藏危险 `rm` 的问题"),
    ],
}


def prepare(message, channel):
    title, _ = CONFIG[channel]
    match = re.match(re.escape(title) + r"\s+(v?\d+\.\d+\.\d+(?:-\d+)?(?:\s*\(v\d{4}\.\d+\.\d+(?:\.\d+)?\))?)\s+(Released|发布)", message["text"])
    if not match:
        return None
    version, verb = match.groups()
    source = release_source_url(title, version)
    if channel == "hermes_push":
        tag = re.search(r"v\d{4}\.\d+\.\d+(?:\.\d+)?", version)
        if not tag:
            return None
        source = "https://github.com/NousResearch/hermes-agent/releases/tag/" + tag.group()
    source = source_overrides().get(source, source)
    original = message["markdown"].strip()
    body = original.split("\n", 1)[1].strip() if "\n" in original else ""
    body = re.sub(r"\[(?:\*\*)?((?:CLAUDE|AGENTS)\.md)(?:\*\*)?\]\(https?://(?:CLAUDE|AGENTS)\.md/?\)", r"`\1`", body, flags=re.I)
    body = re.sub(r"\[\*\*(.*?)\*\*\]\(", r"[\1](", body)
    body = re.sub(r"(?m)^\*\*" + re.escape(version.removeprefix("v")) + r"\*\*[ \t]*$", "", body)
    body = body.replace("View Full Changelog | 查看完整更新日志", "View release details | 查看版本详情")
    reasons = []
    for before, after in CORRECTIONS.get(message["post"], []):
        if before not in body:
            raise ValueError("Expected correction missing: " + message["post"])
        body = body.replace(before, after)
        reasons.append("verified_semantic_or_literal_correction")
    if message["post"] == "codex_push/249":
        compare = "https://github.com/openai/codex/compare/rust-v0.149.0...rust-v0.149.1"
        body = "**English**\nOfficial release provides a comparison link, with no change summary.\n\n**中文**\n官方未提供变更摘要，可查看版本间的完整比较。\n\n[Full comparison | 完整比较](" + compare + ")"
        reasons.append("restore_compare_only_release")
    if message["post"] == "hermes_push/37":
        body += "\n\n**Recovery / 恢复提示**\nIf 0.21.0/0.21.1 damaged your database, run `hermes doctor` first; inspect recovery with `hermes sessions recover --inspect-only`.\n若数据库已被 0.21.0/0.21.1 损坏，先运行 `hermes doctor`，再用 `hermes sessions recover --inspect-only` 检查恢复方案。"
        reasons.append("restore_recovery_action")
    if channel == "hermes_push" and message["id"] in {36, 37, 38}:
        dates = {36: "2026-09-07", 37: "2026-09-11", 38: "2026-09-14"}
        body = "历史补推 · Originally released " + dates[message["id"]] + "\n\n" + body
        reasons.append("backfill_date")
    if message["post"] == "openclaw_push/120":
        source = "https://github.com/openclaw/openclaw/releases"
        verb = "Development notes / 开发中日志"
        body = "**更正 / Correction**\n原通知误将标有 Unreleased 的开发中日志称为正式发布；以下保留当时的开发预告，不代表 2026.8.3 已正式发布。\nThe original notice incorrectly labelled Unreleased development notes as a release. The preview below is retained for reference, not as confirmation of a 2026.8.3 release.\n\n" + body
        reasons.append("correct_unreleased_status")
    # Remove empty headings, not sections containing actual material.
    body = re.sub(r"(?m)^(?:\*\*)?(?:Changelog|更新日志)(?:\*\*)?\s*\Z", "", body)
    if message["post"] == "hermes_push/25":
        body = body.replace("7.0.0-rc13 ()", "7.0.0-rc13")
        reasons.append("empty_reference")
    without_labels = re.sub(r"(?m)^\*\*(?:English|中文)\*\*[ \t]*\n?", "", body)
    if without_labels != body:
        reasons.append("remove_redundant_language_labels")
        body = without_labels
    header = f"**{title} [{version}]({source}) {verb}**"
    after = header + "\n\n" + body.strip()
    after = clean_for_telegram(after)
    had_source = any(u == source for u in message["links"])
    if not had_source:
        reasons.append("official_source")
    if any(re.fullmatch(r"https?://(?:AGENTS|CLAUDE)\.md/?", u, re.I) for u in message["links"]):
        reasons.append("filename_autolink")
    if not reasons and after == clean_for_telegram(original):
        return None
    # Only edit for an identified issue; do not churn all historical typography.
    if not reasons and body == original.split("\n", 1)[-1].strip():
        return None
    if not reasons:
        reasons.append("format_consistency")
    return {"post": message["post"], "channel": channel, "id": message["id"],
            "before": original, "before_body": message["body"],
            "after": after, "reasons": sorted(set(reasons)),
            "sha256": hashlib.sha256(after.encode()).hexdigest()}


def snapshot_structure(body):
    """Ignore the message wrapper but retain every inner entity and attribute."""
    def normalize(node):
        if isinstance(node, str):
            return node
        tag = {"strong": "b", "em": "i", "strike": "s", "del": "s"}.get(node["tag"], node["tag"])
        return {
            "tag": tag,
            "attrs": node.get("attrs", {}),
            "children": children(node.get("children", [])),
        }

    def children(items):
        result = []
        for item in items:
            value = normalize(item)
            if isinstance(value, str) and result and isinstance(result[-1], str):
                result[-1] += value
            else:
                result.append(value)
        return result

    return children(body["children"])


def verify_snapshot(session, plan):
    """Fail closed if the public target is unreadable or changed since review."""
    if not isinstance(plan.get("before_body"), dict) or "children" not in plan["before_body"]:
        return "Snapshot lacks message structure; regenerate plan before editing"
    response = session.get(
        f'https://t.me/{plan["post"]}',
        params={"embed": "1", "_": time.time_ns()}, timeout=30,
    )
    response.raise_for_status()
    current = next((m for m in parse_channel(response.text)
                    if m["post"] == plan["post"]), None)
    if current is None:
        return "Current message unavailable; refusing to overwrite"
    if snapshot_structure(current["body"]) != snapshot_structure(plan["before_body"]):
        return "Message changed since snapshot; refusing to overwrite"
    return None


def apply_channel(plans, config, results_dir):
    if not plans:
        return []
    channel = plans[0]["channel"]
    _, prefix = CONFIG[channel]
    token = config[prefix + "_BOT_TOKEN"]
    # Historical IDs belong to the public snapshot, never a local test Chat ID.
    chat = "@" + channel
    base = "https://api.telegram.org/bot" + token
    session = requests.Session()
    # Resolve exact destination before editing numeric message IDs.
    r = session.post(base + "/getChat", json={"chat_id": chat}, timeout=30).json()
    if not r.get("ok") or r["result"].get("username") != channel:
        raise RuntimeError("Destination mismatch: " + channel)
    results = []
    for index, plan in enumerate(plans):
        record_path = results_dir / (plan["post"].replace("/", "-") + ".json")
        if record_path.exists():
            previous = json.loads(record_path.read_text())
            if previous.get("ok") and previous.get("sha256") == plan["sha256"]:
                results.append(previous)
                continue
        payload = {"chat_id": chat, "message_id": plan["id"],
                   "text": process_message_for_markdown_v2(plan["after"]),
                   "parse_mode": "MarkdownV2", "disable_web_page_preview": True}
        for attempt in range(16):
            wait_for_edit_slot(channel)
            try:
                conflict = verify_snapshot(session, plan)
                if conflict:
                    response = {"ok": False, "description": conflict}
                else:
                    response = session.post(base + "/editMessageText", json=payload, timeout=30).json()
            except requests.RequestException:
                response = {"ok": False, "description": "Network error (redacted)"}
            retry_after = response.get("parameters", {}).get("retry_after")
            if retry_after and attempt < 15:
                time.sleep(min(retry_after + 1, 60))
                continue
            break
        ok = bool(response.get("ok")) or "message is not modified" in response.get("description", "")
        record = {"post": plan["post"], "sha256": plan["sha256"], "ok": ok,
                  "result": response.get("result"), "error": None if ok else response.get("description")}
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        results.append(record)
        if not ok or (index + 1) % 20 == 0 or index == len(plans) - 1:
            print(f"{channel} {index+1}/{len(plans)}: {'OK' if ok else record['error']}", flush=True)
        time.sleep(1.1)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--only", nargs="*", help="Exact channel/message IDs")
    args = parser.parse_args()
    directory = ROOT / "output/channel-review"
    snapshot = json.loads((directory / "snapshot.json").read_text())
    plans = [p for c in snapshot["channels"] for m in c["messages"] if (p := prepare(m, c["channel"]))]
    (directory / "telegram-plan.json").write_text(json.dumps(plans, ensure_ascii=False, indent=2))
    if args.only:
        plans = [p for p in plans if p["post"] in args.only]
    print("Prepared existing-message edits:", len(plans), flush=True)
    if not args.apply:
        return
    results_dir = directory / "telegram-results"
    results_dir.mkdir(exist_ok=True)
    config = dotenv_values(ROOT / ".env")
    batches = []
    for channel in CONFIG:
        selected = [p for p in plans if p["channel"] == channel]
        # Independent existing messages can be edited concurrently without
        # changing their order. Each worker honors Telegram retry_after.
        shards = 3 if len(selected) > 100 else 1
        batches.extend(selected[index::shards] for index in range(shards))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda batch: apply_channel(batch, config, results_dir), batches))
    flat = [r for channel in results for r in channel]
    print(f"Edited successfully: {sum(r['ok'] for r in flat)}/{len(flat)}", flush=True)
    if not all(r["ok"] for r in flat):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
