#!/usr/bin/env python3
"""Read current public Telegram posts without using bot mutation endpoints."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_channel_history import parse_channel

CHANNELS = ("claude_code_push", "codex_push", "openclaw_push", "hermes_push")


def read(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def inspect(channel):
    messages = parse_channel(read("https://t.me/s/" + channel))
    latest = max(messages, key=lambda m: m["id"])
    return {
        "channel": channel, "latest": latest,
        "visible_ids": [m["id"] for m in messages],
        "latest_has_no_standalone_language_labels": not bool(re.search(r"(?m)^\s*(?:English|中文)\s*$", latest["text"])),
    }


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        channels = list(pool.map(inspect, CHANNELS))
    special_urls = {
        "codex_259": "https://t.me/codex_push/259?embed=1",
        "codex_261": "https://t.me/codex_push/261?embed=1",
        "openclaw_124": "https://t.me/openclaw_push/124?embed=1",
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = dict(zip(special_urls, pool.map(read, special_urls.values())))
    special = {key: parse_channel(value) for key, value in pages.items()}
    codex_259 = next((m for m in special["codex_259"] if m["post"] == "codex_push/259"), None)
    openclaw_124 = next((m for m in special["openclaw_124"] if m["post"] == "openclaw_push/124"), None)
    codex = next(c for c in channels if c["channel"] == "codex_push")
    checks = {
        "all_latest_messages_have_no_standalone_language_labels": all(c["latest_has_no_standalone_language_labels"] for c in channels),
        "codex_259_still_public": bool(codex_259),
        "codex_261_absent_from_latest_history": 261 not in codex["visible_ids"],
        "codex_261_embed_reports_not_found": not special["codex_261"] and "Post not found" in pages["codex_261"],
        "openclaw_124_keeps_sept16_article_link": bool(openclaw_124 and any("telegra.ph/" in u and "09-16" in u for u in openclaw_124["links"])),
    }
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
        "channels": channels, "direct_message_reads": special,
        "codex_261_embed_not_found_excerpt": "Post not found" if "Post not found" in pages["codex_261"] else None,
    }
    target = ROOT / "output/channel-review/latest-public-validation.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == "__main__":
    main()
