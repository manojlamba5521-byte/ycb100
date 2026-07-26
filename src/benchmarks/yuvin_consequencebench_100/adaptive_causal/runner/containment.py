"""Minimal local containment helpers.

This module deliberately provides only CONTAINMENT_ONLY execution. It strips
ambient environment authority and creates an evaluator-owned working directory,
but it is not an operating-system security sandbox. OCI isolation is a later
evaluator deployment tier and must not be represented by this local runner.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


BASE_ENVIRONMENT_NAMES = ("COMSPEC", "PATHEXT", "PATH", "SYSTEMROOT", "WINDIR")


def filtered_environment(
    *,
    allowed_names: tuple[str, ...],
    supplied: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a minimal child environment without ambient evaluator authority."""
    source = os.environ if supplied is None else supplied
    environment = {
        name: str(source[name])
        for name in BASE_ENVIRONMENT_NAMES
        if str(source.get(name) or "")
    }
    for name in allowed_names:
        value = source.get(name)
        if value is not None:
            environment[name] = str(value)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["YCB100_EXECUTION_TIER"] = "CONTAINMENT_ONLY"
    return environment


@contextmanager
def local_agent_workspace() -> Iterator[Path]:
    """Create an evaluator-owned empty work directory for one adapter process."""
    with tempfile.TemporaryDirectory(prefix="ycb100-acc-ycb100-agent-") as directory:
        workspace = Path(directory)
        yield workspace
