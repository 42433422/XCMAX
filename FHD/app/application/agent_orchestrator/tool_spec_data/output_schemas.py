from __future__ import annotations

from typing import Any

_DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["success"],
    "properties": {
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "data": {},
    },
}

from app.application.agent_orchestrator.tool_spec_data.output_schemas_part_1 import (
    SPECIAL_OUTPUT_SCHEMAS_PART_1,
)
from app.application.agent_orchestrator.tool_spec_data.output_schemas_part_2 import (
    SPECIAL_OUTPUT_SCHEMAS_PART_2,
)
from app.application.agent_orchestrator.tool_spec_data.output_schemas_part_3 import (
    SPECIAL_OUTPUT_SCHEMAS_PART_3,
)

_SPECIAL_OUTPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    **SPECIAL_OUTPUT_SCHEMAS_PART_1,
    **SPECIAL_OUTPUT_SCHEMAS_PART_2,
    **SPECIAL_OUTPUT_SCHEMAS_PART_3,
}
