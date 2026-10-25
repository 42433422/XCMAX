"""经营对账调度：自上次对账截止点起汇总本地支付订单，并把结果写到用户数据目录。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services.fhd_payment_reconciliation import _parse_dt, compute_fhd_period_snapshot


def _state_path() -> Path:
    from app.utils.path_io.path_utils import get_data_dir

    return Path(get_data_dir()) / "reconciliation_state.json"


def _read_state() -> dict[str, Any]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cycle(*, persist: bool) -> dict[str, Any]:
    end = datetime.now(UTC)
    last_end = _parse_dt((_read_state().get("last_run") or {}).get("period_end"))
    snap = compute_fhd_period_snapshot(last_end or end - timedelta(days=1), end)
    run = {
        "ran_at": end.isoformat(),
        "period_start": snap["period_start"],
        "period_end": snap["period_end"],
        "order_count": len(snap["orders"]),
        "totals": snap["totals"],
        "anomalies": snap["anomalies"],
    }
    if persist:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"last_run": run}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)
    return {"success": True, "dry_run": not persist, **run}


def get_reconciliation_status() -> dict[str, Any]:
    return {
        "last_run": _read_state().get("last_run"),
        "auto_confirm_enabled": False,
        "success": True,
    }


def run_reconciliation_preview_cycle() -> dict[str, Any]:
    return {**_cycle(persist=False), "preview": True}


def run_reconciliation_full_cycle() -> dict[str, Any]:
    return _cycle(persist=True)
