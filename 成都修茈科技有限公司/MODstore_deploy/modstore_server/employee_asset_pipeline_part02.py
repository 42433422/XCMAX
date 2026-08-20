# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


from modstore_server.employee_asset_pipeline_part02_part01 import _excel_summary as _excel_summary
from modstore_server.employee_asset_pipeline_part02_part01 import (
    _infer_accepted_extensions as _infer_accepted_extensions,
)
from modstore_server.employee_asset_pipeline_part02_part01 import (
    _infer_asset_runtime_kind as _infer_asset_runtime_kind,
)
from modstore_server.employee_asset_pipeline_part02_part01 import (
    _preflight_scaffold_write_access as _preflight_scaffold_write_access,
)
from modstore_server.employee_asset_pipeline_part02_part01 import (
    _read_text_preview as _read_text_preview,
)
from modstore_server.employee_asset_pipeline_part02_part01 import (
    prepare_employee_assets as prepare_employee_assets,
)
from modstore_server.employee_asset_pipeline_part02_part02 import (
    _employee_id_from_pack_id as _employee_id_from_pack_id,
)
from modstore_server.employee_asset_pipeline_part02_part02 import (
    _employee_name_from_brief as _employee_name_from_brief,
)
from modstore_server.employee_asset_pipeline_part02_part02 import (
    _slug_from_brief as _slug_from_brief,
)
from modstore_server.employee_asset_pipeline_part02_part02 import (
    _template_storage_relpath as _template_storage_relpath,
)
from modstore_server.employee_asset_pipeline_part02_part02 import build_rule_spec as build_rule_spec
