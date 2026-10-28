"""Settings for an installed Sunstone, from ``/etc/sunstone/config.toml``.

The file holds the same choices as the command line, which wins over it:
the topology and on-call directory, where saved files go, where to listen,
and the repository updates come from. Anything left out keeps its default.
``sunstone serve`` reads a settings file only when given one; ``sunstone
check`` and ``sunstone self-update`` read the installed one by default.
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_CONFIG = Path("/etc/sunstone/config.toml")
DEFAULT_REPOSITORY = "robert-patrick-texas/sunstone"


class SettingsError(Exception):
    """A settings file cannot be read, or holds something it should not."""


class _Record(BaseModel):
    # A misspelled key is an error, not a setting silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class UpdateSettings(_Record):
    """Where ``sunstone self-update`` takes releases from."""

    repository: str = Field(DEFAULT_REPOSITORY, pattern=r"^[\w.-]+/[\w.-]+$")
    """A GitHub repository, as ``owner/name``."""


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
