"""Read a topology from a YAML file."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from sunstone.model import Topology


class TopologyError(Exception):
    """A topology file could not be read or is not a valid topology."""


def load_topology(path: Path) -> Topology:
    """Load and validate a topology YAML file.

    Args:
        path: File with top-level ``sites``, ``devices``, and ``links`` lists.

    Returns:
        The validated topology.

    Raises:
        TopologyError: If the file cannot be read, is not YAML, or fails
            validation. The message names the file and every problem found.
    """
    try:
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise TopologyError(f"{path}: {e}") from e
    try:
        return Topology.model_validate(raw)
    except ValidationError as e:
        raise TopologyError(f"{path}: {e}") from e
