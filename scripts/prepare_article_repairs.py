#!/usr/bin/env python3
"""Prepare reviewable Telegraph repairs from a snapshot; never publish or edit pages."""
from __future__ import annotations

import argparse
import copy
import html
import json
from pathlib import Path
import re
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.notify.telegraph import html_to_nodes
from scripts.audit_channel_history import markdown, nodes, plain, source_overrides

# The old HTML regex consumed '<' on unmatched tags. These tokens are artifacts,
# not source prose. Only enable this reconstruction on confirmed damaged pages.
DEBRIS = re.compile(r"(?<![\w<])(/?(?:blockquote|ul|ol|li|b|i|p|h3|h4))>")


def text(node):
    return plain({"children": node}) if isinstance(node, list) else plain(node)


def serialize(node, repair_debris=False):
    if isinstance(node, str):
        if not repair_debris:
            return html.escape(node, quote=False)
        pieces = []
        previous = 0
        for match in DEBRIS.finditer(node):
            pieces.append(html.escape(node[previous:match.start()], quote=False))
            pieces.append("<" + match.group(1) + ">")
            previous = match.end()
        pieces.append(html.escape(node[previous:], quote=False))
        return "".join(pieces)
    tag = {"strong": "b", "em": "i"}.get(node["tag"], node["tag"])
    content = "".join(serialize(c, repair_debris) for c in node.get("children", []))
    attrs = "".join(
        f' {k}="{html.escape(v, quote=True)}"'
        for k, v in node.get("attrs", {}).items() if k in {"href", "src"}
    )
    if tag in {"br", "hr", "img"}:
        return f"<{tag}{attrs}>"
    # <blockquote> was matched as <b lockquote> until a later </b>. Restore its
    # opening tag while retaining that later closing </b> at the correct position.
    quote_prefix = text(node).startswith("b>")
    start = "blockquote" if repair_debris and tag == "b" and (
        "/blockquote>" in text(node) or quote_prefix
    ) else tag
    return f"<{start}{attrs}>{content}</{tag}>"


def semantic_tree(items):
    """Normalize only HTML aliases, unsupported attributes and text segmentation."""
    result = []
    for item in items:
        if isinstance(item, str):
            if result and isinstance(result[-1], str):
                result[-1] += item
            elif item:
                result.append(item)
            continue
        tag = {"strong": "b", "em": "i"}.get(item["tag"], item["tag"])
        normalized = {"tag": tag}
        attrs = {k: v for k, v in item.get("attrs", {}).items() if k in {"href", "src"}}
        if attrs:
            normalized["attrs"] = attrs
        children = semantic_tree(item.get("children", []))
        if children:
            normalized["children"] = children
        result.append(normalized)
    return result


def code_original(node):
    if isinstance(node, str):
        return node
    value = "".join(code_original(c) for c in node.get("children", []))
    if node["tag"] in {"em", "i"}:
        return "_" + value + "_"
    if node["tag"] in {"b", "strong"}:
        return "__" + value + "__"
    return value


def stripped_code(value):
    return re.sub(r"/?[ib]>", "", re.sub(r"<[^>]*>", "", value)).replace("_", "")


def code_signature(value):
    return re.sub(r"[\s_*<>]", "", re.sub(r"/?[ib]>", "", value))


def fetch_sections(url):
    response = requests.get(
        url, timeout=30,
    )
    response.raise_for_status()
    return {
        section.splitlines()[0].strip(): "\n".join(section.splitlines()[1:])
        for section in re.split(r"(?m)^## ", response.text)[1:]
    }


def repair_codes(content, source):
    source_codes = set(re.findall(r"`([^`\n]+)`", source))
    changes = []
    for node in nodes({"children": content}):
        if node.get("tag") != "code":
            continue
        old = text(node)
        candidate = old
        matches = sorted(c for c in source_codes if (
            stripped_code(c) == stripped_code(old) or code_signature(c) == code_signature(old)
        ))
        recovered = code_original(node)
        literal_candidates = {
            re.sub(bold_pattern, bold, re.sub(italic_pattern, italic, recovered))
            for bold in ("__", "**") for italic in ("_", "*")
            for bold_pattern in (r"/?b>", r"b>")
            for italic_pattern in (r"/?i>", r"i>")
        }
        exact = sorted(c for c in matches if c in literal_candidates)
        if len(exact) == 1:
            matches = exact
        if not matches:
            matches = sorted(c for c in literal_candidates if c != old and c in source)
        if len(matches) == 1:
            candidate = matches[0]
        if candidate.startswith(("#", "@")) and candidate.endswith(">") and "<" + candidate in source:
            candidate = "<" + candidate
        if candidate != old:
            node["children"] = [candidate]
            changes.append({"before": old, "after": candidate, "verified_in_source": candidate in source})
    return changes


def repair_plain_identifiers(content, source):
    """Restore an italic marker inside plain identifiers only with source proof."""
    changes = []
    pattern = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:/?i>[A-Za-z0-9_]+)+")
    def visit(node):
        if isinstance(node, str):
            def replace(match):
                old = match.group()
                restored = re.sub(r"/?i>", "_", old)
                if restored in source:
                    changes.append({"before": old, "after": restored, "verified_in_source": True})
                    return restored
                return old
            return pattern.sub(replace, node)
        if node.get("tag") != "code":
            node["children"] = [visit(c) for c in node.get("children", [])]
        return node
    return [visit(n) for n in content], changes


def restore_code_spaces(content, source):
    changes = []
    for node in nodes({"children": content}):
        children = node.get("children", [])
        for i, child in enumerate(children):
            if not isinstance(child, dict) or child.get("tag") != "code":
                continue
            code = text(child)
            if i and isinstance(children[i - 1], str):
                left = children[i - 1]
                word = re.search(r"([A-Za-z]+)$", left)
                if word and f"{word.group(1)} `{code}`" in source:
                    children[i - 1] += " "
                    changes.append({"before": word.group(1) + code, "after": word.group(1) + " " + code})
            if i + 1 < len(children) and isinstance(children[i + 1], str):
                right = children[i + 1]
                word = re.match(r"([A-Za-z]+)", right)
                if word and f"`{code}` {word.group(1)}" in source:
                    children[i + 1] = " " + right
                    changes.append({"before": code + word.group(1), "after": code + " " + word.group(1)})
    return changes


def replace_text(content, replacements):
    found = []
    def visit(node):
        if isinstance(node, str):
            for old, new in replacements:
                if old in node:
                    found.append({"before": old, "after": new})
                    node = node.replace(old, new)
            return node
        node["children"] = [visit(c) for c in node.get("children", [])]
        return node
    return [visit(n) for n in content], found


def prepare(snapshot):
    overrides = source_overrides()
    claude = fetch_sections("https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md")
    openclaw = fetch_sections("https://raw.githubusercontent.com/openclaw/openclaw/v2026.6.5/CHANGELOG.md")
    claude_corpus = "\n".join(claude.values())
    openclaw_corpus = "\n".join(openclaw.values())
    discord_reference_url = "https://discord.com/developers/docs/reference#message-formatting"
    discord_response = requests.get(discord_reference_url, timeout=30)
    discord_response.raise_for_status()
    discord_source = html.unescape(discord_response.text)
    plans = []
    scans = []
    for article in snapshot["articles"]:
        if "page" not in article:
            continue
        page = article["page"]
        before = page["content"]
        content = copy.deepcopy(before)
        title = page["title"]
        reasons = []
        damaged = bool(re.search(r"/blockquote>|/li>|/ul>|ul>li>", text(content)))
        if damaged:
            content = html_to_nodes("".join(serialize(n, True) for n in content))
            reasons.append("Restore HTML tags consumed by the old blockquote/b prefix regex")
        version = re.search(r"Claude Code (\d+\.\d+\.\d+)", title)
        source = claude.get(version.group(1), "") if version else ""
        claw_version = re.search(r"OpenClaw (\d+\.\d+\.\d+)", title)
        if claw_version:
            source = openclaw.get(claw_version.group(1), "")
            if "#CHANNEL/i>ID>" in text(content):
                # This historical release tag is no longer available. Discord's
                # own formatting reference proves the exact channel-mention token.
                source += "\n" + discord_source
        code_changes = repair_codes(content, source)
        corpus = claude_corpus if version else openclaw_corpus if claw_version else ""
        if corpus:
            # Some old release sections have since been removed/edited upstream.
            # Recover remaining mangled code only when its exact spelling is
            # present elsewhere in the same official product changelog.
            for node in nodes({"children": content}):
                if node.get("tag") == "code" and re.search(r"/?[ib]>", text(node)):
                    code_changes.extend(repair_codes([node], corpus))
        content, plain_changes = repair_plain_identifiers(content, source or corpus)
        code_changes.extend(plain_changes)
        space_changes = restore_code_spaces(content, source)
        if code_changes:
            reasons.append("Restore literal code underscores/placeholders from markup and official source")
        if space_changes:
            reasons.append("Restore English word/code boundaries verified against official source")
        replacements = []
        if "Hermes" in title:
            replacements.extend([
                ("无 opencode", "opencode-free"),
                ("漏发表面处理", "提示错过的定时执行"),
                ("从之后的 v0.21.0 开始", "从 v0.21.0 开始"),
            ])
        if "Claude Code 2.1.273" in title:
            replacements.extend([
                (" prompt 这样的命令", " 这样的命令"),
                ("命令现在会再次运行而不是被拒绝", "命令现在会再次请求授权，而不再直接被拒绝"),
            ])
        content, wording = replace_text(content, replacements)
        if wording:
            reasons.append("Correct confirmed mistranslations while preserving the original paragraph")
        if "Hermes Agent v0.21.2" in title and "hermes sessions recover --inspect-only" not in text(content):
            insert = html_to_nodes(
                '<h3>Recovery instructions | 恢复指引</h3>'
                '<p>If an earlier version damaged state.db, run <code>hermes doctor</code> first, '
                'then inspect recoverable sessions with <code>hermes sessions recover --inspect-only</code>.</p>'
                '<p>如果旧版本已损坏 state.db，请先运行 <code>hermes doctor</code>，'
                '再用 <code>hermes sessions recover --inspect-only</code> 检查可恢复的会话。</p>'
            )
            content.extend(insert)
            reasons.append("Restore omitted official recovery commands for existing state.db damage")
        source_url = None
        if version:
            source_url = "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#" + version.group(1).replace(".", "")
        elif claw_version:
            source_url = "https://github.com/openclaw/openclaw/releases/tag/v" + claw_version.group(1)
            if claw_version.group(1) == "2026.4.30":
                # GitHub's API currently returns 404 for this historical tag.
                source_url = "https://github.com/openclaw/openclaw/releases"
        elif "Hermes" in title:
            date_tag = re.search(r"\((v\d{4}\.\d+\.\d+(?:\.\d+)?)\)", title)
            if date_tag:
                source_url = "https://github.com/NousResearch/hermes-agent/releases/tag/" + date_tag.group(1)
        elif "Codex" in title:
            codex_version = re.search(r"(?:OpenAI )?Codex v?(\d+\.\d+\.\d+)", title)
            if codex_version:
                source_url = "https://github.com/openai/codex/releases/tag/rust-v" + codex_version.group(1)
        if claw_version and claw_version.group(1) == "2026.8.3":
            title = "OpenClaw 2026.8.3 Development Notes (Historical correction)"
            content = html_to_nodes(
                '<h3>Historical correction | 历史更正</h3>'
                '<p>This entry was marked Unreleased in the source when the notification was sent. '
                'It documents development changes and was incorrectly announced as Released.</p>'
                '<p>此条目推送时，官方原文标注为 Unreleased（未发布）。以下保留当时的开发日志，'
                '更正此前将其称为正式发布的错误；实际发布状态请以官方 Releases 为准。</p>'
            ) + content
            source_url = "https://github.com/openclaw/openclaw/releases"
            for node in nodes({"children": content}):
                if node.get("attrs", {}).get("href") == "https://github.com/openclaw/openclaw/releases/tag/v2026.8.3":
                    node["attrs"]["href"] = source_url
            reasons.append("Correct historical Unreleased announcement without deleting its development notes")
        source_url = overrides.get(source_url, source_url)
        for node in nodes({"children": content}):
            old_url = node.get("attrs", {}).get("href")
            if old_url in overrides:
                node["attrs"]["href"] = overrides[old_url]
                reasons.append("Replace unavailable historical source with a verified official source")
        existing_urls = {n.get("attrs", {}).get("href") for n in nodes({"children": content}) if n.get("tag") == "a"}
        if source_url and source_url not in existing_urls:
            content.extend(html_to_nodes(
                '<hr><p><a href="' + html.escape(source_url, quote=True)
                + '">Official source | 官方完整日志</a></p>'
            ))
            reasons.append("Add a permanent official source link")
        # Source text survives repairs; stripped whitespace is ignored because the
        # original serializer already dropped some English word boundaries.
        expected_content = copy.deepcopy(before)
        repair_codes(expected_content, source)
        if corpus:
            for node in nodes({"children": expected_content}):
                if node.get("tag") == "code" and re.search(r"/?[ib]>", text(node)):
                    repair_codes([node], corpus)
        expected_content, _ = repair_plain_identifiers(expected_content, source or corpus)
        expected_content, _ = replace_text(expected_content, replacements)
        def original_visible(node):
            if isinstance(node, str):
                return DEBRIS.sub("", node) if damaged else node
            return "".join(original_visible(c) for c in node.get("children", []))
        expected = re.sub(r"\s+", "", original_visible({"children": expected_content}))
        actual = re.sub(r"\s+", "", text(content))
        checks = {
            "no_html_debris": not bool(DEBRIS.search(text(content))),
            "original_text_preserved": expected in actual,
            "before_text_length": len(text(before)),
            "after_text_length": len(text(content)),
            "code_changes": code_changes,
            "space_changes": space_changes,
            "wording_changes": wording,
        }
        content_html = "".join(serialize(n) for n in content)
        wire_content = html_to_nodes(content_html)
        def links_and_media(value):
            return [n.get("attrs", {}).get(k) for n in nodes({"children": value})
                    for k in ("href", "src") if k in n.get("attrs", {})]
        def code_text(value):
            return [text(n) for n in nodes({"children": value}) if n.get("tag") in {"code", "pre"}]
        checks.update({
            "roundtrip_text_preserved": text(wire_content) == text(content),
            "roundtrip_links_preserved": links_and_media(wire_content) == links_and_media(content),
            "roundtrip_code_preserved": code_text(wire_content) == code_text(content),
            "roundtrip_structure_preserved": semantic_tree(wire_content) == semantic_tree(content),
        })
        scans.append({"url": article["url"], "has_changes": bool(reasons), "checks": checks})
        if reasons:
            plans.append({
                "url": article["url"], "path": page["path"], "title": title,
                "before_title": page["title"], "source_url": source_url,
                "before_content": before,
                "before_markdown": article["markdown"],
                "content_html": content_html,
                "content": wire_content,
                "markdown": markdown({"tag": "root", "children": wire_content}),
                "reasons": reasons, "checks": checks,
            })
    return {"plans": plans, "scans": scans, "translation_requests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default="output/channel-review/snapshot.json")
    parser.add_argument("--output", default="output/channel-review/article-repairs.json")
    args = parser.parse_args()
    report = prepare(json.loads((ROOT / args.snapshot).read_text()))
    (ROOT / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({
        "scanned": len(report["scans"]), "planned": len(report["plans"]),
        "requires_review": [p["url"] for p in report["plans"] if not all(
            p["checks"][key] for key in (
                "no_html_debris", "original_text_preserved", "roundtrip_text_preserved",
                "roundtrip_links_preserved", "roundtrip_code_preserved", "roundtrip_structure_preserved",
            )
        )], "translation_requests": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
