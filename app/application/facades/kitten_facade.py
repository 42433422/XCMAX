"""已废弃：请使用 kitten_app_service。"""
import warnings
from app.infrastructure.gateways import kitten as _gw
warnings.warn("kitten_facade 已废弃", DeprecationWarning, stacklevel=2)
for _n in _gw.__all__:
    globals()[_n] = getattr(_gw, _n)
__all__ = list(_gw.__all__)
