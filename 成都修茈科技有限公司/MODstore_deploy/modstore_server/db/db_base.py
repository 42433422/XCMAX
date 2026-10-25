"""Compat module path for ``modstore_server.db.db_base`` imports.

Canonical implementation lives in ``base.py`` (AST / path guards read that
file). This module aliases the same module object so ``_engine`` and other
mutable module state stay shared.
"""

from __future__ import annotations

import sys
from importlib import import_module

_base = import_module(__name__.rsplit(".", 1)[0] + ".base")
sys.modules[__name__] = _base
