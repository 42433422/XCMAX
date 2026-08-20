# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


from modstore_server.workbench_api_part02_part01_part01 import (
    _check_vibe_coding_capability as _check_vibe_coding_capability,
)
from modstore_server.workbench_api_part02_part01_part02 import (
    _employee_handlers_contract_ok as _employee_handlers_contract_ok,
    _employee_quality_extras as _employee_quality_extras,
    _refresh_employee_pack_catalog_zip as _refresh_employee_pack_catalog_zip,
)
from modstore_server.workbench_api_part02_part01_part03 import (
    _assert_employee_catalog_registered as _assert_employee_catalog_registered,
)
