"""Select the useful part of an OpenClaw release note for notifications."""

import re

from core.notify.telegraph import _strip_fixes_section


_VERSION_HEADING_PATTERN = re.compile(r"(?m)^##\s+\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?[^\n]*$")
_HIGHLIGHTS_PATTERN = re.compile(
    r"(?ims)^###\s+Highlights\s*$.*?(?=^###\s+|^##\s+|\Z)"
)


def select_notification_content(content: str) -> str:
    """Prefer Highlights; otherwise omit Fixes and everything after it."""
    highlights = _HIGHLIGHTS_PATTERN.search(content)
    if not highlights:
        return _strip_fixes_section(content)

    version_heading = _VERSION_HEADING_PATTERN.search(content)
    parts = []
    if version_heading and version_heading.start() < highlights.start():
        parts.append(version_heading.group(0).strip())
    parts.append(highlights.group(0).strip())
    return "\n\n".join(parts)
