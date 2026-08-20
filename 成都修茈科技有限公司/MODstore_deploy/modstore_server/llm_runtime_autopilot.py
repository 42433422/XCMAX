# isort: skip_file
# ruff: noqa: E402, F401, I001
"""Active health/quota loop for the platform-funded AI employee route."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from modstore_server.operational_errors import BOUNDARY_ERRORS

_LOCK = threading.Lock()
_MAX_LEDGER_LINES = 500


from modstore_server.llm_runtime_autopilot_part01 import (
    _now_iso as _now_iso,
    _env_bool as _env_bool,
    _env_int as _env_int,
    autopilot_enabled as autopilot_enabled,
    _failure_threshold as _failure_threshold,
    _minimum_residence_seconds as _minimum_residence_seconds,
    _max_candidate_probes as _max_candidate_probes,
    autopilot_ledger_path as autopilot_ledger_path,
    _secret_safe as _secret_safe,
    _read_audit_events as _read_audit_events,
    _write_audit as _write_audit,
    _record as _record,
    _consecutive_route_errors as _consecutive_route_errors,
    _route_residence_seconds as _route_residence_seconds,
    autopilot_status as autopilot_status,
    _provider_order as _provider_order,
    _ordered_models as _ordered_models,
    _quota_by_provider as _quota_by_provider,
)


from modstore_server.llm_runtime_autopilot_part02 import (
    reconcile_llm_route_autopilot as reconcile_llm_route_autopilot,
    run_llm_route_autopilot as run_llm_route_autopilot,
)

__all__ = [
    "autopilot_enabled",
    "autopilot_ledger_path",
    "autopilot_status",
    "reconcile_llm_route_autopilot",
    "run_llm_route_autopilot",
]
