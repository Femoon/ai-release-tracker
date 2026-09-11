"""Shared policy for Codex Rust CLI stable releases."""

import re
from urllib.parse import unquote, urlparse


def is_stable_cli_tag(tag):
    return isinstance(tag, str) and re.fullmatch(r"rust-v[0-9]+\.[0-9]+\.[0-9]+", tag) is not None


def is_stable_cli_release(release):
    return (is_stable_cli_tag(release.get("tag_name"))
            and not release.get("draft", False)
            and not release.get("prerelease", False))


def tag_from_release_url(url):
    parsed = urlparse(url)
    prefix = "/openai/codex/releases/tag/"
    if parsed.hostname != "github.com" or not parsed.path.startswith(prefix):
        return ""
    return unquote(parsed.path[len(prefix):].rstrip("/"))
