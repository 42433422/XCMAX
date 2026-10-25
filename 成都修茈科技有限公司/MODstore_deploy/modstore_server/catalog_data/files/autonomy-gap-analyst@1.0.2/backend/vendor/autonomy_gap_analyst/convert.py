"""Compat shim: debt19 renamed convert.py → autonomy_gap_analyst_convert.py.

Loaded via importlib.util.spec_from_file_location in pack tests, so this file
must not rely on package-relative imports.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_TARGET = Path(__file__).with_name("autonomy_gap_analyst_convert.py")
_spec = importlib.util.spec_from_file_location("autonomy_gap_analyst_convert_impl", _TARGET)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

for _name, _value in vars(_mod).items():
    if _name.startswith("_"):
        continue
    globals()[_name] = _value

del _name, _value, _mod, _spec, _TARGET, importlib, Path
