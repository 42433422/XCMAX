"""Shared attendance header matching exposed to independently packaged Mods."""

from app.mod_sdk.attendance import ensure_attendance_engine_on_path

ensure_attendance_engine_on_path()

from attendance_engine.header_resolver import (  # type: ignore[import-not-found] # noqa: E402
    ResolvedHeader as ResolvedHeader,
)
from attendance_engine.header_resolver import (
    llm_enabled_by_env as llm_enabled_by_env,
)
from attendance_engine.header_resolver import (
    resolve_daily_stats_header as resolve_daily_stats_header,
)
from attendance_engine.header_resolver import (
    resolve_raw_records_header as resolve_raw_records_header,
)
