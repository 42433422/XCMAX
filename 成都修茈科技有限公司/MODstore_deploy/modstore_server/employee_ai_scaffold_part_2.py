# mypy: disable-error-code="arg-type, attr-defined, no-any-return, valid-type"
"""Employee scaffold helpers split by generation responsibility."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_scaffold")


from modstore_server.employee_ai_scaffold_part_2_part01 import (
    _default_employee_config_v2 as _default_employee_config_v2,
)
from modstore_server.employee_ai_scaffold_part_2_part01 import (
    _normalize_behavior_rules as _normalize_behavior_rules,
)
from modstore_server.employee_ai_scaffold_part_2_part01 import (
    _normalize_employee_config_v2_for_canvas as _normalize_employee_config_v2_for_canvas,
)
from modstore_server.employee_ai_scaffold_part_2_part01 import (
    _normalize_employee_system_prompt as _normalize_employee_system_prompt,
)
from modstore_server.employee_ai_scaffold_part_2_part01 import (
    _strip_json_fence as _strip_json_fence,
)
from modstore_server.employee_ai_scaffold_part_2_part01 import (
    append_employee_stub_files_to_zip as append_employee_stub_files_to_zip,
)
from modstore_server.employee_ai_scaffold_part_2_part01 import (
    parse_employee_pack_llm_json as parse_employee_pack_llm_json,
)
from modstore_server.employee_ai_scaffold_part_2_part02 import (
    build_employee_pack_zip as build_employee_pack_zip,
)
from modstore_server.employee_ai_scaffold_part_2_part02 import (
    normalize_editor_manifest_for_registry as normalize_editor_manifest_for_registry,
)
