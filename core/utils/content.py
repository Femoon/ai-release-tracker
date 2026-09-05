"""Bound notification input without splitting Markdown blocks."""

from markdown_it import MarkdownIt


MAX_NOTIFICATION_CHARS = 8000
_MARKDOWN = MarkdownIt()


def limit_notification_content(content: str, source_url: str = "", limit: int = MAX_NOTIFICATION_CHARS) -> str:
    if len(content) <= limit:
        return content

    notice = "Release notes shortened due to length."
    notice += (
        f" [View complete release notes]({source_url})"
        if source_url else " View the upstream release for the remaining items."
    )
    suffix = f"\n\n> {notice}"
    available = max(0, limit - len(suffix))
    lines = content.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    # Top-level blocks and individual top-level list items are atomic. Nested
    # lists, continuation paragraphs and fences remain attached to their item.
    boundaries = {0}
    for token in _MARKDOWN.parse(content):
        if token.map and (
            (token.level == 0 and token.type not in ("bullet_list_open", "ordered_list_open"))
            or (token.type == "list_item_open" and token.level == 1)
        ):
            boundaries.add(offsets[token.map[1]])
    end = max(boundary for boundary in boundaries if boundary <= available)
    selected = content[:end].rstrip()
    print(f"Notification input shortened: {len(content)} -> {len(selected + suffix)} characters")
    return selected + suffix
