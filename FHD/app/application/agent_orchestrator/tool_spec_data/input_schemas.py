from __future__ import annotations

from typing import Any

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

from app.application.agent_orchestrator.tool_spec_data.input_schemas_part_1 import (
    SPECIAL_INPUT_SCHEMAS_PART_1,
)
from app.application.agent_orchestrator.tool_spec_data.input_schemas_part_2 import (
    SPECIAL_INPUT_SCHEMAS_PART_2,
)
from app.application.agent_orchestrator.tool_spec_data.input_schemas_part_3 import (
    SPECIAL_INPUT_SCHEMAS_PART_3,
)

_SPECIAL_INPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    **SPECIAL_INPUT_SCHEMAS_PART_1,
    **SPECIAL_INPUT_SCHEMAS_PART_2,
    **SPECIAL_INPUT_SCHEMAS_PART_3,
}

for _action in ("view", "list", "query"):
    _SPECIAL_INPUT_SCHEMAS[("wechat", _action)] = {
        "type": "object",
        "properties": {
            "contact_key": {"type": "string", "description": "联系人唯一键；为空时列出联系人"},
            "request_id": {"type": "string", "description": "刷新回执查询编号"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
    }
for _action in ("refresh_contact_cache", "refresh_messages_cache"):
    _SPECIAL_INPUT_SCHEMAS[("wechat", _action)] = {
        "type": "object",
        "properties": {
            "request_key": {"type": "string", "description": "同一次刷新重试应复用此幂等键"},
        },
    }
