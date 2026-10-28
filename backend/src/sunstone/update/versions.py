"""Release versions: ``MAJOR.MINOR.PATCH``, optionally ``-rc.N``, from the
repository's ``VERSION`` file, in the forms tags, packages, and Python use."""

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Self

# v1.4.0, 1.4.0-rc.1 (VERSION), 1.4.0~rc.1 (Debian), 1.4.0.rc.1 (GitHub's
# spelling of a "~" in a file name), and 1.4.0rc1 (Python).
_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:(?:-rc\.|~rc\.|\.rc\.|rc)(\d+))?$")


@total_ordering
@dataclass(frozen=True)
class Version:
    """A release version; a release candidate comes before its release."""

    major: int
    minor: int
    patch: int
    rc: int | None = None

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read a version in any of the forms it is written in.

        Args:
            text: For example ``1.4.0``, ``v1.4.0-rc.1``, ``1.4.0~rc.1``,
                or ``1.4.0rc1``.

        Returns:
            The version.

        Raises:
            ValueError: If it is not a version.
        """
        found = _PATTERN.match(text.strip())
        if found is None:
            raise ValueError(f"not a version: {text!r}")
        major, minor, patch, rc = found.groups()
        return cls(int(major), int(minor), int(patch), None if rc is None else int(rc))

    def __str__(self) -> str:
        """The form ``VERSION`` holds, such as ``1.4.0-rc.1``."""
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.rc is None else f"{base}-rc.{self.rc}"

    def __lt__(self, other: object) -> bool:
        """Whether this version comes before another."""
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def _key(self) -> tuple[int, int, int, bool, int]:
        return (self.major, self.minor, self.patch, self.rc is None, self.rc or 0)

    @property
    def deb(self) -> str:
        """The package's form, where an rc sorts first: ``1.4.0~rc.1``."""
        return str(self).replace("-rc.", "~rc.")

    @property
    def tag(self) -> str:
        """The release's tag: ``v1.4.0-rc.1``."""
        return f"v{self}"
