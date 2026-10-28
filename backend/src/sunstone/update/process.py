"""Running other programs, with argument lists only, never through a shell."""

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RunResult:
    """How a program ended."""

    code: int
    output: str
    """Standard output and error together."""


Runner = Callable[[Sequence[str], bytes | None, Mapping[str, str] | None], RunResult]
"""Runs a program with optional standard input and extra environment."""


def run_command(
    args: Sequence[str],
    stdin: bytes | None = None,
    env: Mapping[str, str] | None = None,
) -> RunResult:
    """Run a program and wait for it.

    Args:
        args: The program and its arguments.
        stdin: What to give it on standard input, if anything.
        env: Variables to add to the environment.

    Returns:
        Its exit status and output; 127 if it cannot be started.

    Raises:
        None
    """
    try:
        done = subprocess.run(
            list(args),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, **env} if env else None,
            check=False,
        )
    except OSError as e:
        return RunResult(127, f"{args[0]}: {e}")
    return RunResult(done.returncode, done.stdout.decode(errors="replace"))
