# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


from modstore_server.daily_digest_surface_audit_part07_part01_part01 import (
    analyze_surface_lanes as analyze_surface_lanes,
    _capture_surface_target_async as _capture_surface_target_async,
)
from modstore_server.daily_digest_surface_audit_part07_part01_part02 import (
    run_surface_audit_async as run_surface_audit_async,
    _lane_summary as _lane_summary,
    _lane_analysis_md as _lane_analysis_md,
    surface_audit_excerpt_markdown as surface_audit_excerpt_markdown,
    _render_analysis_block_html as _render_analysis_block_html,
    _render_lane_html as _render_lane_html,
    _lane_count_overview_html as _lane_count_overview_html,
)
from modstore_server.daily_digest_surface_audit_part07_part01_part03 import (
    _surface_audit_badge as _surface_audit_badge,
    _email_lane_row_cap as _email_lane_row_cap,
    build_surface_audit_html_sync as build_surface_audit_html_sync,
)
