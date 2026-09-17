"""Select the useful part of an OpenClaw release note for notifications."""

import re

from markdown_it import MarkdownIt

from core.utils.content import limit_notification_content
from products.openclaw.source import release_url

SOURCE_URL = "https://github.com/openclaw/openclaw/blob/main/CHANGELOG.md"


_VERSION_HEADING_PATTERN = re.compile(r"(?m)^##\s+\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?[^\n]*$")
_HIGHLIGHTS_PATTERN = re.compile(
    r"(?ims)^###\s+Highlights\s*$.*?(?=^###\s+|^##\s+|\Z)"
)
_ISSUE_REFERENCES_PATTERN = re.compile(r"\s*\(#\d+(?:,\s*#\d+)*\)")
_THANKS_PATTERN = re.compile(
    r"\s+Thanks\s+@[\w-]+(?:\s*,\s*@[\w-]+)*(?:\s*,?\s+and\s+@[\w-]+)?\.?(?=\s*$)",
    re.IGNORECASE,
)
_IMPORTANT_HEADING = re.compile(r"(?i)\b(?:security|breaking|migration|upgrade|recovery|action required)\b")
_IMPORTANT_ACTION = re.compile(
    r"(?i)\b(?:breaking|security|vulnerabilit\w*|CVE-\d+|data loss|corrupt\w*|"
    r"must|need to|should (?:run|upgrade|migrate)|before (?:upgrading|updating)|"
    r"run `[^`]*(?:doctor|recover|migrat)[^`]*`)\b"
)


def _important_blocks(content: str) -> list[str]:
    """Keep entire actionable Markdown blocks, including command fences."""
    lines = content.splitlines(keepends=True)
    blocks = []
    important_depth = None
    previous_end = None
    pending_heading_start = None
    for token in MarkdownIt().parse(content):
        if not token.map:
            continue
        if token.type == "heading_open" and token.level == 0:
            previous_end = None
            heading = "".join(lines[token.map[0]:token.map[1]])
            depth = int(token.tag[1:])
            if important_depth is not None and depth <= important_depth:
                important_depth = None
                pending_heading_start = None
            if important_depth is None and _IMPORTANT_HEADING.search(heading):
                important_depth = depth
            if important_depth is not None and pending_heading_start is None:
                pending_heading_start = token.map[0]
            elif important_depth is None:
                pending_heading_start = None
            continue
        if (token.level == 0 and token.type in ("paragraph_open", "fence", "code_block", "blockquote_open")) or (
            token.type == "list_item_open" and token.level == 1
        ):
            block = "".join(lines[token.map[0]:token.map[1]]).rstrip()
            if (
                token.type in ("fence", "code_block")
                and previous_end is not None
                and not "".join(lines[previous_end:token.map[0]]).strip()
            ):
                # An instruction and its following commands form one action.
                blocks[-1] += "".join(lines[previous_end:token.map[0]]) + "\n" + block
                previous_end = token.map[1]
                continue
            if block and (important_depth is not None or _IMPORTANT_ACTION.search(block)):
                if pending_heading_start is not None:
                    # Scope such as "Windows users only" belongs to the action,
                    # and must survive both prioritization and length clipping.
                    block = "".join(lines[pending_heading_start:token.map[0]]) + block
                    pending_heading_start = None
                blocks.append(block)
                previous_end = token.map[1]
            else:
                previous_end = None
    return list(dict.fromkeys(blocks))


def _strip_release_metadata(content: str) -> str:
    """Remove issue references and contributor credits from release-note lines."""
    cleaned_lines = []
    for line in content.splitlines():
        line = _ISSUE_REFERENCES_PATTERN.sub("", line)
        line = _THANKS_PATTERN.sub("", line)
        cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip()


def select_notification_content(content: str) -> str:
    """Prefer Highlights while retaining upgrade, recovery and security actions."""
    version_heading = _VERSION_HEADING_PATTERN.search(content)
    source_url = SOURCE_URL
    if version_heading:
        version = re.search(r"\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?", version_heading.group(0)).group(0)
        source_url = release_url(version)
    highlights = _HIGHLIGHTS_PATTERN.search(content)
    fixes = re.search(r"(?im)^###\s+Fixes\s*$", content)
    selected = highlights.group(0).strip() if highlights else content[:fixes.start()].strip() if fixes else content.strip()
    if not _VERSION_HEADING_PATTERN.sub("", selected).strip():
        # A patch containing only Fixes still needs a meaningful announcement.
        selected = content.strip()
    parts = []
    if version_heading:
        parts.append(version_heading.group(0).strip())
        selected = _VERSION_HEADING_PATTERN.sub("", selected).strip()
    important = _important_blocks(content)
    if important:
        for block in important:
            selected = selected.replace(block, "")
        parts.append("### Important upgrade and security notes\n\n" + "\n\n".join(important))
    if selected:
        parts.append(selected)
    # Always label the selection and link the precise release, even when short.
    footer = f"\n\n> Selected release notes. [Complete official release notes]({source_url})"
    cleaned = _strip_release_metadata("\n\n".join(parts))
    result = limit_notification_content(cleaned, source_url, limit=8000 - len(footer))
    if result != cleaned:
        # The shared limiter knows Markdown blocks, but instructions and their
        # adjacent command blocks must also fit together or be omitted together.
        prefix, separator, notice = result.rpartition("\n\n> Release notes shortened due to length.")
        if separator:
            for block in important:
                group = _strip_release_metadata(block)
                start = cleaned.find(group)
                if start >= 0 and start < len(prefix) < start + len(group):
                    prefix = prefix[:start].rstrip()
                    break
            result = prefix + separator + notice
    return result + footer
