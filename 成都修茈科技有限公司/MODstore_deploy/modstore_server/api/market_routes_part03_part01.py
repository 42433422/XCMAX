# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


from modstore_server.api.market_routes_part03_part01_part01 import (
    _existing_child_file as _existing_child_file,
    _existing_upload_session as _existing_upload_session,
    _catalog_suffix as _catalog_suffix,
    _new_catalog_file as _new_catalog_file,
    _compute_sha256 as _compute_sha256,
    UploadSession as UploadSession,
    UploadChunk as UploadChunk,
    CompleteUpload as CompleteUpload,
    CatalogItemAdminPatchDTO as CatalogItemAdminPatchDTO,
    api_admin_upload_catalog as api_admin_upload_catalog,
    api_admin_patch_catalog_item as api_admin_patch_catalog_item,
    api_admin_sync_xc_catalog_packages as api_admin_sync_xc_catalog_packages,
    api_admin_list_catalog as api_admin_list_catalog,
    api_initiate_upload as api_initiate_upload,
    api_upload_chunk as api_upload_chunk,
    api_complete_upload as api_complete_upload,
)
from modstore_server.api.market_routes_part03_part01_part02 import (
    api_admin_delete_catalog as api_admin_delete_catalog,
    api_admin_delete_employee_pack as api_admin_delete_employee_pack,
    api_admin_align_employee_llm_from_deepseek as api_admin_align_employee_llm_from_deepseek,
    api_admin_align_employee_llm_to_auto as api_admin_align_employee_llm_to_auto,
    api_admin_align_single_employee_llm_to_auto as api_admin_align_single_employee_llm_to_auto,
    api_admin_purge_all_employee_packs as api_admin_purge_all_employee_packs,
    api_admin_purge_all_mods as api_admin_purge_all_mods,
)
