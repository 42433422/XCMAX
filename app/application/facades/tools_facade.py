"""已废弃。"""
import warnings
from app.infrastructure.gateways import tools as _gw
warnings.warn("tools_facade 已废弃", DeprecationWarning, stacklevel=2)
_parse_order_text = _gw._parse_order_text
execute_registered_workflow_tool = _gw.execute_registered_workflow_tool
execute_tool_from_payload = _gw.execute_tool_from_payload
get_workflow_tool_registry = _gw.get_workflow_tool_registry
set_tool_execute_headers = _gw.set_tool_execute_headers
__all__ = list(_gw.__all__)
