"""Collection rules and the ``fx`` fixture for the real-sample suite.

The suite downloads about 70 MB, so it is opt-in: select it with ``-m quirk``,
``-m contract`` or ``-m real_sample``, or set ``T2D_REAL_SAMPLES=1``. Every test here is also
marked ``network`` so that CI (``-m "not network"``) and the default developer run skip it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.real_samples.fixtures import fetch

HERE = Path(__file__).resolve().parent
# A marker name that is not directly negated ("not real_sample") counts as opting in.
_SUITE_MARKERS = re.compile(r"(?<!not )\b(quirk|contract|real_sample)\b")


def _opted_in(config: pytest.Config) -> bool:
    if os.environ.get("T2D_REAL_SAMPLES") == "1":
        return True
    return bool(_SUITE_MARKERS.search(config.getoption("markexpr") or ""))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(
        reason="the real-sample suite downloads about 70 MB: run "
        "`pytest tests/real_samples -m quirk` (or -m contract), or set T2D_REAL_SAMPLES=1"
    )
    opted_in = _opted_in(config)
    for item in items:
        if HERE not in Path(str(item.path)).parents:
            continue
        item.add_marker(pytest.mark.network)
        item.add_marker(pytest.mark.real_sample)
        if not opted_in:
            item.add_marker(skip)


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("T2D_REFERENCE_READERS") == "1":
        from tests.real_samples import reference_readers  # noqa: F401  (registers on import)


@pytest.fixture(scope="session")
def fx() -> Callable[[str], Path]:
    """fx('name.ext') -> verified Path."""
    return fetch
