"""已废弃。"""
import warnings
from app.infrastructure.gateways import session as _gw
warnings.warn("session_facade 已废弃", DeprecationWarning, stacklevel=2)
get_auth_service = _gw.get_auth_service
get_database_service = _gw.get_database_service
get_session_service = _gw.get_session_service
get_system_service = _gw.get_system_service
__all__ = list(_gw.__all__)
