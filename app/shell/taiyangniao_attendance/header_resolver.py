"""Deprecated shim — re-export from ``taiyangniao_attendance.header_resolver``."""

from __future__ import annotations

from . import _load_mod_submodule

_mod = _load_mod_submodule("header_resolver")

ResolvedHeader = _mod.ResolvedHeader
resolve_daily_stats_header = _mod.resolve_daily_stats_header
resolve_raw_records_header = _mod.resolve_raw_records_header
llm_enabled_by_env = _mod.llm_enabled_by_env

__all__ = [
    "ResolvedHeader",
    "resolve_daily_stats_header",
    "resolve_raw_records_header",
    "llm_enabled_by_env",
]
