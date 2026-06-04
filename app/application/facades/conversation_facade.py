"""已废弃：请使用 conversation / user_preference 应用服务或 gateways.conversation。"""
import warnings
from app.infrastructure.gateways import conversation as _gw
warnings.warn("conversation_facade 已废弃", DeprecationWarning, stacklevel=2)
get_conversation_service = _gw.get_conversation_service
get_data_analysis_service = _gw.get_data_analysis_service
get_user_preference_service = _gw.get_user_preference_service
__all__ = ["get_conversation_service", "get_data_analysis_service", "get_user_preference_service"]
