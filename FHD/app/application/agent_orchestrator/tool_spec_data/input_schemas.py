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
