"""Settings for an installed Sunstone, from ``/etc/sunstone/config.toml``.

The file holds the same choices as the command line, which wins over it:
the topology and on-call directory, where saved files go, where to listen,
and where updates come from and how. Anything left out keeps its default.
``sunstone serve`` reads a settings file only when given one; ``sunstone
check`` and ``sunstone self-update`` read the installed one by default.
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sunstone.update.releases import GITHUB_API
from sunstone.update.versions import Version

DEFAULT_CONFIG = Path("/etc/sunstone/config.toml")
DEFAULT_REPOSITORY = "robert-patrick-texas/sunstone"


class SettingsError(Exception):
    """A settings file cannot be read, or holds something it should not."""


class _Record(BaseModel):
    # A misspelled key is an error, not a setting silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class UpdateSettings(_Record):
    """Where ``sunstone self-update`` takes releases from, and how."""

    repository: str = Field(DEFAULT_REPOSITORY, pattern=r"^[\w.-]+/[\w.-]+$")
    """A GitHub repository, as ``owner/name``."""
    api: str = Field(GITHUB_API, pattern=r"^https://[^\s/@]+(/[^\s]*[^\s/])?$")
    """The GitHub API: GitHub's own, a GitHub Enterprise server's
    (``https://HOST/api/v3``), or a test server's."""
    hold_version: str | None = None
    """Updates that pick the release never go past this one; installing a
    newer one by name still can, at the console."""
    https_proxy: str | None = Field(None, pattern=r"^http://[^\s/@]+:[0-9]+/?$")
    """A proxy that supports ``CONNECT``, as ``http://HOST:PORT``, without
    credentials; without one, ``HTTPS_PROXY`` from the environment."""
    tls_strict_x509: bool = True
    """Check certificates against OpenSSL's strict X.509 profile, as Python
    does; false accepts an inspecting proxy's CA issued before clients
    enforced it, still checking chains, validity, and host names."""

    @field_validator("hold_version")
    @classmethod
    def _a_version(cls, value: str | None) -> str | None:
        if value is not None:
            Version.parse(value)
        return value


class Settings(_Record):
    """Everything a settings file can say."""

    topology: Path | None = None
    oncall: Path | None = None
    """An on-call directory named here must exist."""
    state_dir: Path | None = None
    """Where maintenance, acknowledgements, notes, fixes, handovers, and
    layouts are kept, one JSON file each."""
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    update: UpdateSettings = UpdateSettings()


def load_settings(path: Path) -> Settings:
    """Read a settings file.

    Args:
        path: A TOML file.

    Returns:
        The settings, with defaults for anything the file leaves out.

    Raises:
        SettingsError: If the file cannot be read, is not TOML, or holds an
            unknown key or a value of the wrong kind. The message names the
            file.
    """
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SettingsError(f"{path}: {e}") from e
    try:
        return Settings.model_validate(raw)
    except ValidationError as e:
        raise SettingsError(f"{path}: {e}") from e
