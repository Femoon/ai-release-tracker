"""Select the useful part of an OpenClaw release note for notifications."""

import re

from core.notify.telegraph import _strip_fixes_section
from core.utils.content import limit_notification_content

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


def _strip_release_metadata(content: str) -> str:
    """Remove issue references and contributor credits from release-note lines."""
    cleaned_lines = []
    for line in content.splitlines():
        line = _ISSUE_REFERENCES_PATTERN.sub("", line)
        line = _THANKS_PATTERN.sub("", line)
        cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip()


def select_notification_content(content: str) -> str:
    """Prefer Highlights; otherwise omit Fixes and everything after it."""
    highlights = _HIGHLIGHTS_PATTERN.search(content)
    if not highlights:
        return limit_notification_content(_strip_release_metadata(_strip_fixes_section(content)), SOURCE_URL)

    version_heading = _VERSION_HEADING_PATTERN.search(content)
    parts = []
    if version_heading and version_heading.start() < highlights.start():
        parts.append(version_heading.group(0).strip())
    parts.append(highlights.group(0).strip())
    return limit_notification_content(_strip_release_metadata("\n\n".join(parts)), SOURCE_URL)
