"""Re-export (debt19). Includes private (_*) names."""

# mypy: ignore-errors

from __future__ import annotations

from . import employee_asset_pipeline_merged_mod1_r1 as _split_0
from . import employee_asset_pipeline_merged_mod1_r2 as _split_1


def _reexport(module) -> None:
    g = globals()
    for name, value in vars(module).items():
        if name.startswith("__") and name.endswith("__"):
            continue
        g[name] = value


_reexport(_split_0)
_reexport(_split_1)
del _reexport, _split_0, _split_1
