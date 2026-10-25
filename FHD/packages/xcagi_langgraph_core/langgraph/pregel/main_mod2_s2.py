from __future__ import annotations

from .main_mod2_s2_mix1 import PregelDebt19Mixin1
from .main_mod2_s2_mix2 import PregelDebt19Mixin2

class Pregel(PregelDebt19Mixin1, PregelDebt19Mixin2):
    """Composition of debt19 mixins; behavior unchanged."""
    pass
