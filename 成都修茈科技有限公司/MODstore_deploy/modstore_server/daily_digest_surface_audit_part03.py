# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


from modstore_server.daily_digest_surface_audit_part03_part01 import (
    _base_url as _base_url,
    _ps_base_url as _ps_base_url,
    _ps_audit_enabled as _ps_audit_enabled,
    _safe_slug_name as _safe_slug_name,
    _fetch_market_catalog_sync as _fetch_market_catalog_sync,
    _surface_audit_mode as _surface_audit_mode,
    _is_full_surface_audit as _is_full_surface_audit,
    _is_sample_surface_audit as _is_sample_surface_audit,
    _is_daily_surface_audit as _is_daily_surface_audit,
    _max_targets_per_lane as _max_targets_per_lane,
    _catalog_screenshot_max as _catalog_screenshot_max,
    _catalog_fetch_enabled as _catalog_fetch_enabled,
    _stable_sample_catalog_items as _stable_sample_catalog_items,
    _is_ai_employee_material as _is_ai_employee_material,
    _filter_catalog_ai_employee_items as _filter_catalog_ai_employee_items,
    _is_ai_employee_store_target as _is_ai_employee_store_target,
    _is_ps_ai_employee_target as _is_ps_ai_employee_target,
    _is_papp_ai_ecosystem_target as _is_papp_ai_ecosystem_target,
    _pick_lane_sample_target as _pick_lane_sample_target,
    _pick_sample_targets as _pick_sample_targets,
    _limit_targets_per_lane as _limit_targets_per_lane,
    _append_pw_catalog_targets as _append_pw_catalog_targets,
    _pw_catalog_items_for_daily as _pw_catalog_items_for_daily,
    _build_pw_full_targets as _build_pw_full_targets,
)


from modstore_server.daily_digest_surface_audit_part03_part02 import (
    build_digest_surface_targets as build_digest_surface_targets,
    build_surface_targets as build_surface_targets,
    default_surface_targets as default_surface_targets,
    _repo_root as _repo_root,
    _png_fingerprint as _png_fingerprint,
    compute_surface_baseline_delta as compute_surface_baseline_delta,
    baseline_delta_excerpt_markdown as baseline_delta_excerpt_markdown,
    _save_dir as _save_dir,
)
