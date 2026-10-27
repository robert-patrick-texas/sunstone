"""Saved layouts of the topology view.

A layout is the view's settings plus the position of every node, so a picture
someone arranged by hand can be opened again later. All layouts for one
topology live in one JSON file, rewritten whole on every change: a new file
is written beside it and moved into place, so a crash never leaves it
half-written.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

MAX_LAYOUTS = 200
MAX_NAME = 64

# No leading or trailing spaces, so a name always finds the same layout.
LayoutName = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_NAME, pattern=r"^\S(.*\S)?$")
]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class DeviceCenter(_Record):
    """A neighborhood built around one device."""

    kind: Literal["device"]
    id: str


class SiteCenter(_Record):
    """A neighborhood built around every device of a site."""

    kind: Literal["site"]
    id: str


class LinksCenter(_Record):
    """A neighborhood built around the ends of some links."""

    kind: Literal["links"]
    ids: list[str]


Center = Annotated[DeviceCenter | SiteCenter | LinksCenter, Field(discriminator="kind")]


class PathEnds(_Record):
    """The two devices whose shortest paths are shown."""

    start: str = Field(alias="from")
    to: str


class LayoutSettings(_Record):
    """The topology view's settings when the layout was saved."""

    scope: Literal["network", "neighborhood", "path"]
    layout: Literal["force", "radial"]
    grouped: bool
    hops: int = Field(ge=1, le=4)
    center: Center | None = None
    path: PathEnds | None = None
    expanded: list[str] = Field(default_factory=list, max_length=10_000)


class Position(_Record):
    """Where a node was drawn."""

    x: float
    y: float


class LayoutIn(_Record):
    """A layout as the browser sends it."""

    settings: LayoutSettings
    positions: dict[str, Position] = Field(max_length=20_000)


class SavedLayout(LayoutIn):
    """A stored layout."""

    name: LayoutName
    saved_at: datetime


class LayoutSummary(_Record):
    """A stored layout without its positions, for listing."""

    name: str
    saved_at: datetime
    scope: str
    nodes: int


class LayoutStoreError(Exception):
    """The layouts file cannot be read."""


class LayoutStoreFull(LayoutStoreError):
    """The layouts file already holds ``MAX_LAYOUTS`` layouts."""


_FILE = TypeAdapter(list[SavedLayout])


class LayoutStore:
    """Saved layouts kept in one JSON file."""

    def __init__(self, path: Path) -> None:
        """Use a layouts file, created on first save.

        Args:
            path: The JSON file.

        Raises:
            None
        """
        self.path = path
        self._lock = Lock()

    def summaries(self) -> list[LayoutSummary]:
        """Summaries of every layout, most recently saved first.

        Returns:
            The summaries.

        Raises:
            LayoutStoreError: If the file cannot be read.
        """
        with self._lock:
            layouts = self._read()
        summaries = [
            LayoutSummary(
                name=lay.name,
                saved_at=lay.saved_at,
                scope=lay.settings.scope,
                nodes=len(lay.positions),
            )
            for lay in layouts.values()
        ]
        return sorted(summaries, key=lambda s: s.saved_at, reverse=True)

    def get(self, name: str) -> SavedLayout | None:
        """One layout.

        Args:
            name: Its name.

        Returns:
            The layout, or None if there is none by that name.

        Raises:
            LayoutStoreError: If the file cannot be read.
        """
        with self._lock:
            return self._read().get(name)

    def put(self, name: str, layout: LayoutIn) -> SavedLayout:
        """Save a layout, replacing any with the same name.

        Args:
            name: Its name.
            layout: Settings and positions.

        Returns:
            The stored layout.

        Raises:
            LayoutStoreError: If the file cannot be read.
            LayoutStoreFull: If it already holds ``MAX_LAYOUTS`` layouts and
                this is a new name.
            ValidationError: If the name is empty, too long, or starts or
                ends with a space.
        """
        saved = SavedLayout(
            name=name,
            saved_at=datetime.now(UTC),
            settings=layout.settings,
            positions=layout.positions,
        )
        with self._lock:
            layouts = self._read()
            if saved.name not in layouts and len(layouts) >= MAX_LAYOUTS:
                raise LayoutStoreFull(f"{self.path}: already holds {MAX_LAYOUTS}")
            layouts[saved.name] = saved
            self._write(layouts)
        return saved

    def delete(self, name: str) -> bool:
        """Delete a layout.

        Args:
            name: Its name.

        Returns:
            True if it existed.

        Raises:
            LayoutStoreError: If the file cannot be read.
        """
        with self._lock:
            layouts = self._read()
            if layouts.pop(name, None) is None:
                return False
            self._write(layouts)
        return True

    def _read(self) -> dict[str, SavedLayout]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as e:
            raise LayoutStoreError(f"{self.path}: {e}") from e
        try:
            return {lay.name: lay for lay in _FILE.validate_json(raw)}
        except ValidationError as e:
            raise LayoutStoreError(f"{self.path}: {e}") from e

    def _write(self, layouts: dict[str, SavedLayout]) -> None:
        data = _FILE.dump_python(list(layouts.values()), mode="json", by_alias=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)
