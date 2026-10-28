"""Sunstone's releases on GitHub, and fetching their files.

Releases are read from the API's release list, which includes release
candidates and releases marked pre-release (``/releases/latest`` skips
them). Requests go over HTTPS, verified against the host's CA bundle rather
than the bundled interpreter's own paths, and through ``HTTPS_PROXY`` when
it is set.
"""

import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sunstone.update.versions import Version

API = "https://api.github.com"
ARCH = "amd64"
# Larger than any package; a bigger answer is refused, not read into memory.
MAX_BYTES = 200 * 1024 * 1024
CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")

Getter = Callable[[str], bytes]
"""Fetches a URL and returns the body."""


class ReleaseError(Exception):
    """Releases cannot be listed or fetched, or a release lacks a file."""


@dataclass(frozen=True)
class Release:
    """One release and its files."""

    version: Version
    assets: dict[str, str]
    """File name to download URL."""
    notes: str


def https_get(url: str) -> bytes:
    """Fetch a URL over HTTPS.

    Args:
        url: The URL.

    Returns:
        The body.

    Raises:
        ReleaseError: If the host cannot be reached, the certificate does
            not verify, the answer is an HTTP error or too large, or GitHub's
            rate limit is used up (the message says when it resets).
    """
    cafile = str(CA_BUNDLE) if CA_BUNDLE.is_file() else None
    context = ssl.create_default_context(cafile=cafile)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "sunstone-self-update", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=60) as answer:
            body = answer.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            reset = datetime.fromtimestamp(int(e.headers["X-RateLimit-Reset"]), UTC)
            raise ReleaseError(
                f"GitHub API rate limit used up; it resets at {reset:%H:%M} UTC"
            ) from e
        raise ReleaseError(f"{url}: HTTP {e.code} {e.reason}") from e
    except (urllib.error.URLError, OSError) as e:
        reason = e.reason if isinstance(e, urllib.error.URLError) else e
        raise ReleaseError(f"{url}: {reason}") from e
    if len(body) > MAX_BYTES:
        raise ReleaseError(f"{url}: larger than {MAX_BYTES} bytes")
    return body


def list_releases(get: Getter, repository: str) -> list[Release]:
    """The repository's recent releases, newest version first.

    Args:
        get: Fetches a URL.
        repository: ``owner/name``.

    Returns:
        The 30 most recent releases, leaving out drafts and tags that are
        not versions.

    Raises:
        ReleaseError: If the list cannot be fetched or read.
    """
    body = get(f"{API}/repos/{repository}/releases?per_page=30")
    try:
        raw = json.loads(body)
    except ValueError as e:
        raise ReleaseError(f"{repository}: the release list is not JSON") from e
    if not isinstance(raw, list):
        raise ReleaseError(f"{repository}: unexpected release list")
    found = []
    for item in raw:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        try:
            version = Version.parse(str(item.get("tag_name", "")))
        except ValueError:
            continue
        assets = {
            a["name"]: a["browser_download_url"]
            for a in item.get("assets") or []
            if isinstance(a, dict) and "name" in a and "browser_download_url" in a
        }
        found.append(Release(version, assets, str(item.get("body") or "")))
    return sorted(found, key=lambda r: r.version, reverse=True)


def package_name(version: Version) -> str:
    """The package's file name.

    Args:
        version: The release.

    Returns:
        For example ``sunstone_1.4.0~rc.1_amd64.deb``.

    Raises:
        None
    """
    return f"sunstone_{version.deb}_{ARCH}.deb"


def asset_url(release: Release, name: str) -> str:
    """Where to download one of a release's files.

    Args:
        release: The release.
        name: The file name; GitHub may have written its ``~`` as ``.``.

    Returns:
        The download URL.

    Raises:
        ReleaseError: If the release has no such file.
    """
    for spelling in (name, name.replace("~", ".")):
        if spelling in release.assets:
            return release.assets[spelling]
    raise ReleaseError(f"release {release.version} has no {name}")
