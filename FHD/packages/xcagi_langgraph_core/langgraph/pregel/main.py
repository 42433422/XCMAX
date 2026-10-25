"""Re-export split modules (debt19)."""

from __future__ import annotations

from .main_mod1 import *  # noqa: F403
from .main_mod2 import *  # noqa: F403
from .main_mod3 import *  # noqa: F403

__all__ = ("NodeBuilder", "Pregel")
