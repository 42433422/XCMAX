"""Re-export split modules (debt19). Includes private (_*) names."""

from __future__ import annotations

from . import employee_executor_merged_mod1 as _split_0
from . import employee_executor_merged_mod2 as _split_1


def _reexport(module) -> None:
    g = globals()
    for name, value in vars(module).items():
        if name.startswith("__") and name.endswith("__"):
            continue
        g[name] = value


_reexport(_split_0)
_reexport(_split_1)

del _reexport
del _split_0
del _split_1
