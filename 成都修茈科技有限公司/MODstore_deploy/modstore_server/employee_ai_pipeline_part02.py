# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_ai_pipeline")


from modstore_server.employee_ai_pipeline_part02_part01 import (
    stage_generate_code as stage_generate_code,
)
from modstore_server.employee_ai_pipeline_part02_part02 import (
    refine_system_prompt as refine_system_prompt,
)
from modstore_server.employee_ai_pipeline_part02_part02 import run_pipeline as run_pipeline
