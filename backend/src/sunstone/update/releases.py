"""Sunstone's releases on GitHub, and fetching their files.

Releases are read from the API's release list, which includes release
candidates and releases marked pre-release (``/releases/latest`` skips
them). Requests go over HTTPS, verified against the host's CA bundle rather
than the bundled interpreter's own paths, and against the CA certificates
in Sunstone's own directory, ``/etc/sunstone/ca.d``, where an enterprise
proxy that inspects TLS has its CA put; through the configured proxy, or
``HTTPS_PROXY`` when none is.
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

GITHUB_API = "https://api.github.com"
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


def trusted_cas(ca_dir: Path) -> list[Path]:
    """The CA certificates trusted besides the host's.

    Args:
        ca_dir: The directory they are put in.

    Returns:
        Its ``*.pem`` and ``*.crt`` files, by name; none if it is missing.

    Raises:
        None
    """
    if not ca_dir.is_dir():
        return []
    return sorted(
        p for p in ca_dir.iterdir() if p.suffix in (".pem", ".crt") and p.is_file()
    )


def tls_context(ca_dir: Path | None = None, strict: bool = True) -> ssl.SSLContext:
    """What self-update's HTTPS trusts.

    Args:
        ca_dir: A directory of CA certificates trusted besides the host's
            bundle, or None for the bundle alone.
        strict: Check certificates against OpenSSL's strict X.509 profile,
            as Python does by default.

    Returns:
        A context verifying certificates and host names.

    Raises:
        ReleaseError: If a file in the directory is not a PEM certificate;
            the message names it. A broken file is never skipped.
    """
    cafile = str(CA_BUNDLE) if CA_BUNDLE.is_file() else None
    context = ssl.create_default_context(cafile=cafile)
    for path in trusted_cas(ca_dir) if ca_dir else []:
        try:
            context.load_verify_locations(cafile=str(path))
        except (ssl.SSLError, OSError) as e:
            raise ReleaseError(f"{path}: not a PEM CA certificate: {e}") from e
    if not strict:
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def https_getter(
    ca_dir: Path | None = None, strict: bool = True, proxy: str | None = None
) -> Getter:
    """A way to fetch URLs over HTTPS.

    Args:
        ca_dir: CA certificates trusted besides the host's bundle.
        strict: Check certificates against the strict X.509 profile.
        proxy: ``http://HOST:PORT`` to go through, or None for
            ``HTTPS_PROXY`` from the environment, if set.

    Returns:
        Fetches a URL and returns the body. It raises ``ReleaseError`` if
        the host cannot be reached, the certificate does not verify (saying
        what to do about an inspecting proxy), the answer is an HTTP error
        or too large, or GitHub's rate limit is used up (saying when it
        resets).

    Raises:
        ReleaseError: If a file in ``ca_dir`` is not a PEM certificate.
    """
    extra = trusted_cas(ca_dir) if ca_dir else []
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPSHandler(context=tls_context(ca_dir, strict))
    ]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    if not extra:
        hint = f"behind a proxy that inspects TLS, put its CA certificate in {ca_dir}"
    elif strict:
        hint = (
            f"if {', '.join(p.name for p in extra)} is the inspecting proxy's CA, "
            "it may not meet the strict X.509 profile: tls_strict_x509 = false "
            "in [update] accepts it"
        )
    else:
        hint = ""

    def get(url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "sunstone-self-update", "Accept": "*/*"},
        )
        try:
            with opener.open(request, timeout=60) as answer:
                body = answer.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            remaining = e.headers.get("X-RateLimit-Remaining")
            if e.code in (403, 429) and remaining == "0":
                at = int(e.headers["X-RateLimit-Reset"])
                raise ReleaseError(
                    "GitHub API rate limit used up; it resets at "
                    f"{datetime.fromtimestamp(at, UTC):%H:%M} UTC"
                ) from e
            raise ReleaseError(f"{url}: HTTP {e.code} {e.reason}") from e
        except (urllib.error.URLError, OSError) as e:
            reason = e.reason if isinstance(e, urllib.error.URLError) else e
            if isinstance(reason, ssl.SSLCertVerificationError):
                said = f"; {hint}" if hint and ca_dir else ""
                raise ReleaseError(
                    f"{url}: certificate not trusted: {reason.verify_message}{said}"
                ) from e
            raise ReleaseError(f"{url}: {reason}") from e
        if len(body) > MAX_BYTES:
            raise ReleaseError(f"{url}: larger than {MAX_BYTES} bytes")
        return body

    return get


def list_releases(get: Getter, repository: str, api: str) -> list[Release]:
    """The repository's recent releases, newest version first.

    Args:
        get: Fetches a URL.
        repository: ``owner/name``.
        api: The GitHub API's base URL.

    Returns:
        The 30 most recent releases, leaving out drafts and tags that are
        not versions.

    Raises:
        ReleaseError: If the list cannot be fetched or read.
    """
    body = get(f"{api}/repos/{repository}/releases?per_page=30")
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
