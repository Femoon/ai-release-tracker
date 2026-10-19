#!/usr/bin/env python3
"""Prepare reviewable translation repairs for published notices; never edits anything.

Calls the LLM through the production translation and summary paths, so every
quality gate applies. Targets that fail a gate are recorded as failed and are
never downgraded to English.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from core.notify.telegram import (
    MAX_MESSAGE_LENGTH,
    _build_bilingual_messages,
    _telegraph_notification_message,
    process_message_for_markdown_v2,
    release_source_url,
)
from core.notify.telegraph import build_changelog_html, get_page, html_to_nodes
from core.translate import summarize_changelog, translate_changelog
from core.utils.content import limit_notification_content
from scripts.audit_channel_history import parse_channel

OUTPUT = ROOT / "output/channel-review/translation-repairs.json"
REVIEW_DIR = ROOT / "output/channel-review/translation-repairs"
# Telegraph rejects page content above 64 KB with CONTENT_TOO_BIG.
TELEGRAPH_CONTENT_LIMIT = 64 * 1024

# 2026.5.9 no longer has a GitHub release or tag; its notes survive only in
# the monolithic CHANGELOG.md history.
OPENCLAW_259_COMMIT = "9431d18aaf9f149fc71b277abdbbf9e4c46e4f1d"
OPENCLAW_259_SOURCE = (
    f"https://github.com/openclaw/openclaw/blob/{OPENCLAW_259_COMMIT}/CHANGELOG.md#202659"
)

TARGETS = [
    {"key": "claude_code_push/579", "title": "Claude Code", "version": "2.1.243",
     "page": "Claude-Code-21243-Release-Notes-08-25", "message": False},
    {"key": "openclaw_push/87", "title": "OpenClaw", "version": "2026.4.25",
     "page": "OpenClaw-2026425-Release-Notes-EN-04-26-17", "message": True},
    {"key": "openclaw_push/88", "title": "OpenClaw", "version": "2026.4.26",
     "page": "OpenClaw-2026426-Release-Notes-EN-04-27-13", "message": True},
    {"key": "openclaw_push/95", "title": "OpenClaw", "version": "2026.5.9",
     "page": "OpenClaw-202659-Release-Notes-EN-05-13-2", "message": False},
    {"key": "openclaw_push/117", "title": "OpenClaw", "version": "2026.6.11",
     "page": "OpenClaw-2026611-Release-Notes-06-30", "message": False},
    # The page is already bilingual; only the degraded "Summary unavailable"
    # notice needs a summary.
    {"key": "openclaw_push/128", "title": "OpenClaw", "version": "2026.9.8",
     "page": "OpenClaw-202698-Release-Notes-10-03", "message": True, "translate": False},
]


def load_source(target):
    """Return (notification content, source URL) exactly as the checker builds them."""
    title, version = target["title"], target["version"]
    if title == "Claude Code":
        from products.claude_code.checker import CHANGELOG_URL, fetch_changelog, parse_specific_version
        changelog = fetch_changelog()
        content = parse_specific_version(changelog, version) if changelog else None
        if content is None:
            raise RuntimeError(f"{version} not found in CHANGELOG.md")
        return limit_notification_content(content, CHANGELOG_URL), release_source_url(title, version)

    from products.openclaw.checker import parse_specific_version
    from products.openclaw.content import select_notification_content
    from products.openclaw.source import fetch_release_changelog, release_url
    if version == "2026.5.9":
        response = requests.get(
            f"https://raw.githubusercontent.com/openclaw/openclaw/{OPENCLAW_259_COMMIT}/CHANGELOG.md",
            timeout=30,
        )
        response.raise_for_status()
        changelog = response.text
    else:
        changelog = fetch_release_changelog(version)
    content = parse_specific_version(changelog, version) if changelog else None
    if content is None:
        raise RuntimeError(f"{version} notes unavailable")
    selected = select_notification_content(content)
    if version == "2026.5.9":
        # The selection footer links the release page, which is now a 404.
        selected = selected.replace(release_url(version), OPENCLAW_259_SOURCE)
        return selected, OPENCLAW_259_SOURCE
    return selected, release_url(version)


def page_title(title, version):
    return f"{title} {version} Release Notes"


def build_page_plan(path, title, version, original, translated, source_url, before):
    content_html = build_changelog_html(original, translated, source_url)
    content = html_to_nodes(content_html)
    size = len(json.dumps(content, ensure_ascii=False).encode())
    return {
        "path": path,
        "url": "https://telegra.ph/" + path,
        "before_title": before["title"],
        "before_content": before["content"],
        "title": page_title(title, version),
        "content_html": content_html,
        "content": content,
        "content_bytes": size,
        "checks": {
            "has_translation": bool(translated.strip()),
            "within_telegraph_limit": size <= TELEGRAPH_CONTENT_LIMIT,
        },
        "sha256": hashlib.sha256(
            json.dumps([page_title(title, version), content], ensure_ascii=False).encode()
        ).hexdigest(),
    }


def build_message_plan(post, title, version, version_url, page_url, summary, before):
    en_title = _build_bilingual_messages(version, "", "", title, version_url)["en_title"]
    link_line = f"\n\n[View release notes | 查看版本说明]({page_url})"
    if version_url:
        link_line += f" | [GitHub]({version_url})"
    after = _telegraph_notification_message(en_title, summary, "", link_line)
    channel, message_id = post.split("/")
    return {
        "post": post,
        "channel": channel,
        "id": int(message_id),
        "before": before["markdown"],
        "before_body": before["body"],
        "after": after,
        "length": len(process_message_for_markdown_v2(after)),
        "checks": {
            "has_summary": bool(summary.strip()),
            "within_telegram_limit": len(process_message_for_markdown_v2(after)) <= MAX_MESSAGE_LENGTH,
            "links_page": page_url in after,
        },
        "sha256": hashlib.sha256(after.encode()).hexdigest(),
    }


def read_message(post):
    response = requests.get(
        f"https://t.me/{post}", params={"embed": "1", "_": time.time_ns()}, timeout=30,
    )
    response.raise_for_status()
    message = next((m for m in parse_channel(response.text) if m["post"] == post), None)
    if message is None:
        raise RuntimeError(f"{post} unavailable")
    return message


def read_page(path):
    result = get_page(path)
    if not result.get("success"):
        raise RuntimeError(f"Telegraph page {path} unavailable")
    return result["page"]


def prepare_target(target):
    plan = {"key": target["key"], "title": target["title"], "version": target["version"],
            "status": "failed", "reasons": []}
    original, source_url = load_source(target)
    plan.update(original=original, source_url=source_url)
    before_page = read_page(target["page"])
    page_url = "https://telegra.ph/" + target["page"]

    if target.get("translate", True):
        translated = translate_changelog(original)
        plan["translated"] = translated
        if not translated:
            plan["reasons"].append("translation_failed_quality_gate")
            return plan
        plan["page"] = build_page_plan(
            target["page"], target["title"], target["version"],
            original, translated, source_url, before_page,
        )
        failed = [name for name, ok in plan["page"]["checks"].items() if not ok]
        plan["reasons"].extend("page_" + name for name in failed)

    if target["message"]:
        summary = summarize_changelog(original)
        plan["summary"] = summary
        if not summary:
            plan["reasons"].append("summary_failed")
            return plan
        plan["message"] = build_message_plan(
            target["key"], target["title"], target["version"], source_url,
            page_url, summary, read_message(target["key"]),
        )
        failed = [name for name, ok in plan["message"]["checks"].items() if not ok]
        plan["reasons"].extend("message_" + name for name in failed)

    if not plan["reasons"]:
        plan["status"] = "ready"
    return plan


def review_markdown(plan):
    lines = [f"# {plan['key']} · {plan['title']} {plan['version']}", "",
             f"- 状态：{plan['status']}" + (f"（{', '.join(plan['reasons'])}）" if plan["reasons"] else ""),
             f"- 原文链接：{plan.get('source_url', '')}"]
    if "page" in plan:
        page = plan["page"]
        lines += [f"- 页面：{page['url']}",
                  f"- 标题：{page['before_title']} → {page['title']}",
                  f"- 页面内容：{page['content_bytes']:,} bytes"]
    if "message" in plan:
        lines += [f"- 消息：https://t.me/{plan['message']['post']}（{plan['message']['length']} 字符）"]
    if "message" in plan:
        lines += ["", "## 消息：修改前", "", plan["message"]["before"], "",
                  "## 消息：修改后", "", plan["message"]["after"]]
    if plan.get("original"):
        lines += ["", "## 原文", "", plan["original"]]
    if plan.get("translated"):
        lines += ["", "## 译文", "", plan["translated"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="Target keys, e.g. openclaw_push/128")
    args = parser.parse_args()
    targets = [t for t in TARGETS if not args.only or t["key"] in args.only]
    if args.only and len(targets) != len(set(args.only)):
        parser.error("unknown target in --only")

    existing = json.loads(OUTPUT.read_text())["plans"] if OUTPUT.exists() else []
    plans = {p["key"]: p for p in existing}
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for target in targets:
        print("=" * 50, flush=True)
        print(f"{target['key']}  {target['title']} {target['version']}", flush=True)
        try:
            plan = prepare_target(target)
        except (RuntimeError, requests.RequestException) as exc:
            plan = {"key": target["key"], "title": target["title"], "version": target["version"],
                    "status": "failed", "reasons": ["error: " + str(exc)]}
        plans[target["key"]] = plan
        review = REVIEW_DIR / (target["key"].replace("/", "-") + ".md")
        review.write_text(review_markdown(plan))
        print(f"→ {plan['status']}" + (f" ({', '.join(plan['reasons'])})" if plan["reasons"] else ""), flush=True)

    ordered = [plans[t["key"]] for t in TARGETS if t["key"] in plans]
    OUTPUT.write_text(json.dumps({"plans": ordered}, ensure_ascii=False, indent=2))
    ready = sum(p["status"] == "ready" for p in ordered)
    print(f"Ready: {ready}/{len(ordered)}  → {OUTPUT.relative_to(ROOT)}", flush=True)
    if ready != len(ordered):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
