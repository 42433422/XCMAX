"""Pregel main module (debt19 facade). Bodies concatenated into this namespace."""

from __future__ import annotations

import builtins as _builtins
from pathlib import Path as _Path

_parts = (
    "main_body_1.py",
    "main_body_2.py",
)
_src = "".join(
    (_Path(__file__).with_name(name)).read_text(encoding="utf-8") for name in _parts
)
_builtins.exec(compile(_src, str(_Path(__file__).resolve()), "exec"), globals())
del _builtins, _Path, _parts, _src
