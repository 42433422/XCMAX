# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


from modstore_server.employee_executor_part03_part01_part01 import (
    _executor_max_concurrent as _executor_max_concurrent,
    _get_executor_semaphore as _get_executor_semaphore,
    _executor_extra_cognition_retries as _executor_extra_cognition_retries,
    _executor_detail_log_enabled as _executor_detail_log_enabled,
    _is_transient_llm_error as _is_transient_llm_error,
    _run_cognition_with_transient_retries as _run_cognition_with_transient_retries,
    _get_section as _get_section,
    _perception_excel as _perception_excel,
    _extract_vision_data_urls as _extract_vision_data_urls,
    _perception_image as _perception_image,
    _memory_long_term_chroma as _memory_long_term_chroma,
    _perception_real as _perception_real,
    _perception_document as _perception_document,
    _perception_web_rankings as _perception_web_rankings,
)
from modstore_server.employee_executor_part03_part01_part02 import (
    _memory_real as _memory_real,
    _cognition_real as _cognition_real,
    _cognition_sync as _cognition_sync,
)
