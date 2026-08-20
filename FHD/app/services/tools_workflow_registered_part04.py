# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from app.services.tools_workflow_registered_part03 import prepare_business_db_write_target

_DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET = prepare_business_db_write_target


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


from app.services.tools_workflow_registered_part04_part01 import (
    _business_db_update_fields as _business_db_update_fields,
)
from app.services.tools_workflow_registered_part04_part01 import (
    _registered_router_business_db as _registered_router_business_db,
)
from app.services.tools_workflow_registered_part04_part02 import (
    _registered_router_dataset_rag as _registered_router_dataset_rag,
)
from app.services.tools_workflow_registered_part04_part02 import (
    _registered_router_memory_v2 as _registered_router_memory_v2,
)
from app.services.tools_workflow_registered_part04_part03 import (
    _ocr_artifact_payload as _ocr_artifact_payload,
)
from app.services.tools_workflow_registered_part04_part03 import (
    _registered_router_excel_analysis as _registered_router_excel_analysis,
)
from app.services.tools_workflow_registered_part04_part03 import (
    _registered_router_excel_vector_index as _registered_router_excel_vector_index,
)
from app.services.tools_workflow_registered_part04_part03 import (
    _registered_router_generate_office_document as _registered_router_generate_office_document,
)
