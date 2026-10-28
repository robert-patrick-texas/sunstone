"""Checking a release before anything is installed.

``SHA256SUMS`` carries an SSH signature made with the release key, which
``ssh-keygen -Y verify`` checks against the signers file the installed
package ships; then the package must match its line in ``SHA256SUMS``.
Either failing stops the update with nothing changed.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sunstone.update.process import Runner

# The signature's namespace and the principal in the signers file.
SIGNER = "sunstone-release"


class VerificationError(Exception):
    """A release's signature or checksum does not check out."""


@dataclass(frozen=True)
class Artifacts:
    """A release's three files, side by side."""

    package: Path
    sums: Path
    sig: Path


def verify(artifacts: Artifacts, signers: Path, run: Runner) -> None:
    """Check a release's signature, then its package's checksum.

    Args:
        artifacts: The package, ``SHA256SUMS``, and ``SHA256SUMS.sig``.
        signers: The trusted signers, in ssh-keygen's allowed-signers form.
        run: Runs ``ssh-keygen``.

    Raises:
        VerificationError: If a file cannot be read, the signers file has
            no key, the signature does not verify against it, or the package
            is missing from ``SHA256SUMS`` or does not match its line.
    """
    try:
        keys = [
            line
            for line in signers.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    except OSError as e:
        raise VerificationError(f"release signers file unreadable: {e}") from e
    if not keys:
        raise VerificationError(f"release signers file {signers} lists no key")
    try:
        sums = artifacts.sums.read_bytes()
        digest = _sha256(artifacts.package)
    except OSError as e:
        raise VerificationError(f"release file unreadable: {e}") from e
    checked = run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(signers),
            "-I",
            SIGNER,
            "-n",
            SIGNER,
            "-s",
            str(artifacts.sig),
        ],
        sums,
        None,
    )
    if checked.code != 0:
        raise VerificationError(
            f"signature verification failed: {checked.output.strip()}"
        )
    names = {artifacts.package.name, artifacts.package.name.replace("~", ".")}
    for line in sums.decode(errors="replace").splitlines():
        expected, _, name = line.partition("  ")
        if name.lstrip("*") in names:
            if expected.lower() != digest:
                raise VerificationError(
                    f"{artifacts.package.name} does not match SHA256SUMS"
                )
            return
    raise VerificationError(f"{artifacts.package.name} is not in SHA256SUMS")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
