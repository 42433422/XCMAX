# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# ruff: noqa: E402, F401
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
from typing import Literal


def _facade():
    return importlib.import_module("app.application.tools.workflow")


from app.application.tools.workflow_part01_part01 import (
    _read_excel_dataframe as _read_excel_dataframe,
)
from app.application.tools.workflow_part01_part01 import (
    handle_excel_analysis as handle_excel_analysis,
)
from app.application.tools.workflow_part01_part01 import (
    run_natural_language_pandas as run_natural_language_pandas,
)
from app.application.tools.workflow_registry_data_part01 import _base_registry_chunk_01
from app.application.tools.workflow_registry_data_part02 import _base_registry_chunk_02


def _base_registry() -> _facade().list[_facade().dict[str, _facade().Any]]:
    return _base_registry_chunk_01() + _base_registry_chunk_02()


from app.application.tools.workflow_part01_part02 import (
    execute_workflow_tool as execute_workflow_tool,
)
from app.application.tools.workflow_part01_part02 import (
    get_workflow_tool_registry as get_workflow_tool_registry,
)
from app.application.tools.workflow_part01_part02 import (
    invalidate_workflow_tool_registry as invalidate_workflow_tool_registry,
)
