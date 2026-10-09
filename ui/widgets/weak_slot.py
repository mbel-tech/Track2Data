"""Signal slots that do not keep their owner alive.

PySide stores a ``lambda`` or ``functools.partial`` slot strongly, in the C++
connection table where Python's garbage collector cannot see it. When such a
slot captures ``self`` and is connected to a signal of one of ``self``'s own
child widgets, the screen holds itself alive through a reference the collector
cannot trace, so it is never freed. Its Python wrapper is then destroyed at
interpreter shutdown, after the QApplication, and Qt aborts with "shared
QObject was deleted directly" (a segfault after every test has passed).

``weak_slot`` returns a plain function that holds the bound method only through
a ``WeakMethod``. A bound method connected directly is already handled weakly by
PySide; this is for the cases that need extra arguments or must drop the
signal's own arguments.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import Any


def weak_slot(
    method: Callable[..., Any], *bound: object, pass_args: bool = False
) -> Callable[..., None]:
    """Return a slot that calls ``method(*bound[, *signal_args])`` while its owner lives.

    By default the signal's own arguments are dropped, which is what the lambdas
    and partials this replaces did (``clicked(bool)``, ``valueChanged(int)``).
    Pass ``pass_args=True`` to forward them after ``bound``.
    """
    ref = weakref.WeakMethod(method)  # type: ignore[arg-type]

    def _slot(*args: object) -> None:
        target = ref()
        if target is not None:
            target(*bound, *(args if pass_args else ()))

    return _slot
