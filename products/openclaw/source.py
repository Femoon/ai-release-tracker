"""Fetch notes only for published, stable GitHub releases."""

import os
import re

import requests

API_URL = "https://api.github.com/repos/openclaw/openclaw/releases"
RAW_URL = "https://raw.githubusercontent.com/openclaw/openclaw/main"
VERSION_RE = re.compile(r"v?(\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?)")


def release_url(version):
    return f"https://github.com/openclaw/openclaw/releases/tag/v{version}"


def _get_json(url, **kwargs):
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.getenv("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, headers=headers, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json()


def stable_version(release):
    match = VERSION_RE.fullmatch(release.get("tag_name", ""))
    if not match or release.get("draft") or release.get("prerelease") or not release.get("published_at"):
        return None
    return match.group(1)


def version_key(version):
    base, _, patch = version.partition("-")
    return (*map(int, base.split(".")), int(patch or 0))


def release_content(release):
    version = stable_version(release)
    if not version:
        raise ValueError("OpenClaw release is not a published stable version")
    body = (release.get("body") or "").strip()
    split_notes = "openclaw-release-publication:docs-v1" in body or bool(
        re.search(r"\]\([^\s)]*/CHANGELOG/" + re.escape(version) + r"\.md\)", body)
    )
    if not body or split_notes:
        # The root changelog is now an index. Never parse its first entry as
        # a release; fetch a matching split file after confirming publication.
        response = requests.get(f"{RAW_URL}/CHANGELOG/{version}.md", timeout=30)
        if response.status_code == 404:
            if split_notes:
                raise ValueError(f"OpenClaw {version} linked changelog is unavailable")
            body = f"Official release has no change summary. [Release notes]({release_url(version)})"
        else:
            response.raise_for_status()
            body = response.text.strip()
    # GitHub release status is authoritative, but conflicting notes should
    # fail closed rather than announce an explicitly unreleased document.
    if re.search(r"(?im)^#{1,2}\s+[^\n]*\b(?:unreleased|beta|alpha|rc)\b", body):
        raise ValueError(f"OpenClaw {version} notes are marked unreleased/prerelease")
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"(?m)^#{1,3}[ \t]+(?:OpenClaw[ \t]+)?v?" + re.escape(version) + r"[ \t]*$", "", body).strip()
    return f"## {version}\n\n{body}"


def fetch_release_changelog(target_version=None, *, all_versions=False):
    """Return the existing changelog text shape, backed by Releases API."""
    try:
        if target_version:
            release = _get_json(f"{API_URL}/tags/v{target_version}")
            if stable_version(release) != target_version:
                raise ValueError(f"{target_version} is not a published stable release")
            return release_content(release)
        if not all_versions:
            return release_content(_get_json(f"{API_URL}/latest"))
        releases = {}
        page = 1
        while True:
            batch = _get_json(API_URL, params={"per_page": 100, "page": page})
            for release in batch:
                if version := stable_version(release):
                    releases[version] = release
            if len(batch) < 100:
                break
            page += 1
        return "\n\n".join(
            release_content(releases[version])
            for version in sorted(releases, key=version_key, reverse=True)
        )
    except (requests.RequestException, ValueError) as exc:
        print(f"获取 OpenClaw 正式发布记录失败: {exc}")
        return None
