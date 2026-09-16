#!/usr/bin/env python3
"""Snapshot public channel history and linked Telegraph pages without sending messages."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ("claude_code_push", "codex_push", "openclaw_push", "hermes_push")


def source_overrides():
    path = ROOT / "output/channel-review/source-link-validation.json"
    if not path.exists():
        return {}
    report = json.loads(path.read_text())
    return {item["url"]: item["suggested_source"] for item in report.get("unmatched_sources", [])
            if item.get("suggested_source")}


class TreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1]["children"].append(data)


def nodes(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []):
            yield from nodes(child)


def plain(node):
    if isinstance(node, str):
        return node
    if node.get("tag") == "br":
        return "\n"
    return "".join(plain(c) for c in node.get("children", []))


def markdown(node):
    if isinstance(node, str):
        return node
    tag = node.get("tag")
    content = "".join(markdown(c) for c in node.get("children", []))
    if tag == "br":
        return "\n"
    if tag == "pre":
        return "\n```\n" + plain(node).strip() + "\n```\n"
    if tag == "code":
        return "`" + plain(node) + "`"
    if tag in {"b", "strong"}:
        return "**" + content + "**"
    if tag == "a":
        return "[" + content + "](" + node.get("attrs", {}).get("href", "") + ")"
    if tag in {"h3", "h4"}:
        return "\n\n## " + content + "\n\n"
    if tag == "li":
        return "\n- " + content.strip() + "\n"
    if tag == "blockquote":
        return "\n\n" + "\n".join("> " + l for l in content.strip().splitlines()) + "\n\n"
    if tag in {"p", "ul", "ol"}:
        return "\n\n" + content.strip() + "\n\n"
    if tag == "hr":
        return "\n\n---\n\n"
    return content


def links(node):
    return [n.get("attrs", {}).get("href", "") for n in nodes(node) if n.get("tag") == "a"]


def parse_channel(html):
    parser = TreeParser()
    parser.feed(html)
    result = []
    for node in nodes(parser.root):
        post = node.get("attrs", {}).get("data-post")
        if not post:
            continue
        body = next((n for n in nodes(node) if "tgme_widget_message_text" in n.get("attrs", {}).get("class", "").split()), None)
        if body is None:
            continue
        date = next((n.get("attrs", {}).get("datetime") for n in nodes(node) if n.get("tag") == "time"), None)
        result.append({"post": post, "id": int(post.split("/")[-1]), "date": date,
                       "text": plain(body), "markdown": markdown(body), "links": links(body), "body": body})
    return result


def get(url, **kwargs):
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 2:
                raise RuntimeError("Read failed: " + urlparse(url).netloc) from None
            time.sleep(attempt + 1)


def snapshot_channel(channel, directory, max_pages):
    found = {}
    before = None
    pages = 0
    while pages < max_pages:
        html = get("https://t.me/s/" + channel, params={"before": before} if before else {}).text
        (directory / f"{channel}-{before or 'latest'}.html").write_text(html)
        messages = parse_channel(html)
        pages += 1
        new = [m for m in messages if m["id"] not in found]
        if not new:
            break
        found.update({m["id"]: m for m in new})
        oldest = min(m["id"] for m in new)
        if oldest <= 1 or (before is not None and oldest >= before):
            break
        before = oldest
    print(f"{channel}: {len(found)} messages, {pages} pages", flush=True)
    return {"channel": channel, "pages": pages, "messages": sorted(found.values(), key=lambda m: m["id"])}


def snapshot_article(url, token):
    path = urlparse(url).path.lstrip("/")
    try:
        params = {"return_content": "true"}
        if token:
            params["access_token"] = token
        data = get("https://api.telegra.ph/getPage/" + path, params=params).json()
        if not data.get("ok"):
            return {"url": url, "error": data.get("error", "unknown")}
        page = data["result"]
        root = {"tag": "root", "children": page.get("content", [])}
        return {"url": url, "page": page, "text": plain(root), "markdown": markdown(root), "links": links(root)}
    except (RuntimeError, ValueError) as exc:
        return {"url": url, "error": str(exc)}


def owned_article_paths(token):
    """getPage's can_edit flag is not an API ownership check; use page listing."""
    owned = set()
    if not token:
        return owned
    offset = 0
    while True:
        try:
            response = requests.post("https://api.telegra.ph/getPageList", data={
                "access_token": token, "offset": offset, "limit": 200,
            }, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            raise RuntimeError("Telegraph ownership listing failed") from None
        if not data.get("ok"):
            raise RuntimeError("Telegraph ownership listing rejected")
        result = data["result"]
        pages = result.get("pages", [])
        owned.update(p["path"] for p in pages)
        offset += len(pages)
        if not pages or offset >= result.get("total_count", 0):
            return owned


def findings(text, urls):
    issues = []
    if re.search(r"(?:/blockquote>|/li>|/ul>|ul>li>|(?<![A-Za-z])p>Measured|b>\d+ non-merge)", text):
        issues.append("html_debris")
    if any(re.fullmatch(r"https?://(?:AGENTS|CLAUDE)\.md/?", u, re.I) for u in urls):
        issues.append("filename_autolink")
    if "Released" in text and "Unreleased" in text:
        issues.append("unreleased_announced")
    if re.search(r"\(\s*\)", text):
        issues.append("empty_parentheses")
    if not re.search(r"[\u4e00-\u9fff]", text):
        issues.append("no_chinese")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/channel-review")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--skip-articles", action="store_true")
    args = parser.parse_args()
    directory = ROOT / args.output
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / "raw"
    raw.mkdir(exist_ok=True)
    snapshot_path = directory / "snapshot.json"
    if args.cached:
        snapshot = json.loads(snapshot_path.read_text())
    else:
        with ThreadPoolExecutor(max_workers=4) as pool:
            channels = list(pool.map(lambda c: snapshot_channel(c, raw, args.max_pages), CHANNELS))
        urls = sorted({u for c in channels for m in c["messages"] for u in m["links"] if urlparse(u).netloc in {"telegra.ph", "www.telegra.ph"}})
        token = dotenv_values(ROOT / ".env").get("TELEGRAPH_ACCESS_TOKEN", "")
        with ThreadPoolExecutor(max_workers=4) as pool:
            articles = [] if args.skip_articles else list(pool.map(lambda u: snapshot_article(u, token), urls))
        owned = set() if args.skip_articles else owned_article_paths(token)
        for article in articles:
            article["owned_by_configured_account"] = urlparse(article["url"]).path.lstrip("/") in owned
        snapshot = {"channels": channels, "articles": articles}
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    report = {"channels": {}, "articles": {}, "counts": {}}
    for channel in snapshot["channels"]:
        report["counts"][channel["channel"]] = len(channel["messages"])
        for msg in channel["messages"]:
            issues = findings(msg["text"], msg["links"])
            if not any("github.com/" in u or "docs.openclaw.ai/releases/" in u for u in msg["links"]):
                issues.append("no_official_source")
            if issues:
                report["channels"][msg["post"]] = issues
    for article in snapshot["articles"]:
        issues = [article["error"]] if "error" in article else findings(article["text"], article["links"])
        if issues:
            report["articles"][article["url"]] = issues
    report["counts"]["articles"] = len(snapshot["articles"])
    report["counts"]["owned_articles"] = sum(bool(a.get("owned_by_configured_account")) for a in snapshot["articles"])
    (directory / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["counts"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
