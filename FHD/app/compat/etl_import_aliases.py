"""Deprecated ETL import paths kept importable for Mods built before the ETL → ELT rename.

New code must import ``app.*.elt_*`` directly; this module only re-points old
``app.*.elt_*`` imports at the renamed implementation and exposes the previous
symbol names (e.g. ``ShipmentEtlProfile``) on the same module object.
"""

from __future__ import annotations

import importlib
import re
import sys


def _legacy_symbols(module) -> dict[str, object]:
    legacy: dict[str, object] = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if "Elt" in name or re.search(r"(?<![A-Za-z0-9])elt_", name):
            old = name.replace("Elt", "Etl").replace("elt_", "elt_")
            if not hasattr(module, old):
                legacy[old] = value
    return legacy


def alias_module(old_name: str, new_name: str, submodules: tuple[str, ...] = ()) -> None:
    module = importlib.import_module(new_name)
    for name, value in _legacy_symbols(module).items():
        setattr(module, name, value)
    sys.modules[old_name] = module
    for submodule in submodules:
        sys.modules[f"{old_name}.{submodule}"] = importlib.import_module(
            f"{new_name}.{submodule}"
        )
