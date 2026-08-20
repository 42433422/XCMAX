# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


from modstore_server.employee_asset_pipeline_part06_part01_part01 import (
    persist_manifest_to_pack_dir as persist_manifest_to_pack_dir,
    build_employee_pack_zip_for_library as build_employee_pack_zip_for_library,
    build_employee_pack_zip_from_dir as build_employee_pack_zip_from_dir,
    mirror_catalog_file_to_market_files as mirror_catalog_file_to_market_files,
    _copy_template_assets as _copy_template_assets,
    materialize_asset_employee_pack as materialize_asset_employee_pack,
    validate_asset_employee_pack as validate_asset_employee_pack,
)
from modstore_server.employee_asset_pipeline_part06_part01_part02 import (
    run_asset_employee_scaffold_async as run_asset_employee_scaffold_async,
    run_word_extract_employee_scaffold_async as run_word_extract_employee_scaffold_async,
)
