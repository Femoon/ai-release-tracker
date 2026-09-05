"""Select concise, reader-facing Hermes Agent release-note content."""

import re

from core.notify.telegraph import _strip_changelog_section


_HIGHLIGHTS_PATTERN = re.compile(
    r"(?ms)^##\s+[^\n]*Highlights\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
    flags=re.IGNORECASE,
)
_GITHUB_CITATION_URL_PATTERN = re.compile(
    r"https://github\.com/NousResearch/hermes-agent/"
    r"(?:(?:pull|issues)/\d+|commit/[0-9a-f]+)",
    flags=re.IGNORECASE,
)
_GITHUB_REFERENCE_LINK_PATTERN = re.compile(
    r"\[[^\]]*\]\(https://github\.com/NousResearch/hermes-agent/"
    r"(?:(?:pull|issues)/\d+|commit/[0-9a-f]+)\)",
    flags=re.IGNORECASE,
)
_BARE_ISSUE_PATTERN = re.compile(r"\s*\(#\d+(?:,\s*#\d+)*\)\s*$")
_CONTRIBUTOR_PATTERN = re.compile(
    r"^\s*(?:Thanks|Contributors?:)\s+@?[\w-]+.*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
_CONTRIBUTORS_SECTION_PATTERN = re.compile(
    r"(?ms)^##\s+[^\n]*Contributors?\s*$.*\Z",
    flags=re.IGNORECASE,
)
_UPDATING_SECTION_PATTERN = re.compile(
    r"(?ms)^##\s+(?:Updating|Installation|How to update)\s*$.*\Z",
    flags=re.IGNORECASE,
)
_RELEASE_HEADING_PATTERN = re.compile(
    r"^#\s+Hermes Agent\b.*$", flags=re.IGNORECASE
)
_RELEASE_METADATA_PATTERN = re.compile(
    r"^\*\*(?:Release Date|Since\s+v?[^:*]+):\*\*.*$",
    flags=re.IGNORECASE,
)
MAX_NOTIFICATION_CHARS = 8000


def notification_content_kind(content: str) -> str:
    """Describe selected content so link labels do not overstate its scope."""
    highlights = _HIGHLIGHTS_PATTERN.search(content or "")
    return (
        "highlights"
        if highlights and _has_substantive_content(highlights.group("body"))
        else "notes"
    )


def _strip_trailing_github_citation(line: str) -> str:
    """Remove one trailing parenthetical citation without consuming earlier prose."""
    stripped = line.rstrip()
    if not stripped.endswith(")"):
        return stripped

    depth = 0
    for index in range(len(stripped) - 1, -1, -1):
        char = stripped[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                is_separate_group = index > 0 and stripped[index - 1].isspace()
                candidate = stripped[index:]
                if is_separate_group and _GITHUB_CITATION_URL_PATTERN.search(candidate):
                    return stripped[:index].rstrip()
                return stripped
    return stripped


def _strip_release_metadata(content: str) -> str:
    """Remove PR citations and contributor credits from notification lines."""
    content = _CONTRIBUTORS_SECTION_PATTERN.sub("", content)
    content = "\n".join(_strip_trailing_github_citation(line) for line in content.splitlines())
    content = _GITHUB_REFERENCE_LINK_PATTERN.sub("", content)
    cleaned = []
    for line in content.splitlines():
        line = _BARE_ISSUE_PATTERN.sub("", line)
        line = _CONTRIBUTOR_PATTERN.sub("", line)
        line = re.sub(r"\[\]\([^)]+\)", "", line)
        line = re.sub(r"\b(?:Closes?|Fixes?)\s*(?:[,;/]\s*)*\.", "", line)
        line = re.sub(
            r"\s*\((?:salvages?|salvage of|originally|and|\s|[,;:/\-–—→])*\)\s*$",
            "",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"\s+(?:salvages?|salvage of)(?:\s|[,;:/\-–—→])*\.?\s*$",
            "",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(r"\s+([,.;:])", r"\1", line)
        line = re.sub(r"(?:,\s*)+\.", ".", line)
        line = re.sub(
            r"^(-\s+[A-Z][A-Za-z /&-]{1,40})\):",
            r"\1:",
            line,
        )
        cleaned.append(line.rstrip())
    return "\n".join(cleaned).strip()


def _strip_release_header(content: str) -> str:
    """Drop metadata already represented by the Telegram/Telegraph title."""
    cleaned = []
    for line in content.splitlines():
        stripped = line.strip()
        if _RELEASE_HEADING_PATTERN.match(stripped):
            continue
        if _RELEASE_METADATA_PATTERN.match(stripped):
            continue
        if stripped == "---":
            continue
        cleaned.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def _has_substantive_content(content: str) -> bool:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and stripped != "---" and not stripped.startswith("<!--"):
            return True
    return False


def _truncate_at_complete_bullet(
    content: str,
    limit: int = MAX_NOTIFICATION_CHARS,
    notice: str = "Release notes truncated. View the complete GitHub Release for the remaining items.",
) -> str:
    """Bound long Highlights without cutting a bullet or sentence in half."""
    if len(content) <= limit:
        return content

    available = max(0, limit - len(notice) - 4)
    lines = content.splitlines()
    kept = []
    length = 0
    open_fence_index = None
    for line in lines:
        addition = len(line) + (1 if kept else 0)
        if length + addition > available:
            break
        kept.append(line)
        length += addition
        if re.match(r"^\s*```", line):
            if open_fence_index is None:
                open_fence_index = len(kept) - 1
            else:
                open_fence_index = None

    if open_fence_index is not None:
        kept = kept[:open_fence_index]

    while kept and not kept[-1].strip():
        kept.pop()
    kept.extend(["", f"> {notice}"])
    return "\n".join(kept)


def select_notification_content(body: str) -> str:
    """Prefer preamble + Highlights; keep concise patch notes otherwise."""
    if not body:
        return "（暂无更新说明）"

    highlights = _HIGHLIGHTS_PATTERN.search(body)
    if highlights and _has_substantive_content(highlights.group("body")):
        selected = f"{body[:highlights.start()]}{highlights.group(0)}"
        selected = _strip_release_header(_strip_release_metadata(selected))
        return _truncate_at_complete_bullet(
            selected,
            notice=(
                "Highlights truncated. View the complete GitHub Release for the remaining items."
            ),
        )

    # Patch releases are already short. Still drop verbose changelog/fixes
    # tails if a future patch starts carrying generated commit catalogs.
    content = body
    if highlights:
        content = f"{body[:highlights.start()]}{body[highlights.end():]}"
    content = _UPDATING_SECTION_PATTERN.sub("", content)
    content = _strip_changelog_section(content)
    content = _strip_release_header(_strip_release_metadata(content))
    return _truncate_at_complete_bullet(content)
