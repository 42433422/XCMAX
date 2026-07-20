"""Thin MODstore delegate to the FHD domain autonomy guard SSOT."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any


def ensure_fhd_on_path() -> None:
    if (
        not (os.environ.get("XCAGI_AUTONOMY_DATA_DIR") or "").strip()
        and not (os.environ.get("XCAGI_DATA_DIR") or "").strip()
    ):
        runtime = Path(
            os.environ.get("MODSTORE_RUNTIME_DIR") or str(Path.home() / ".xcmax" / "modstore-daily")
        ).expanduser()
        os.environ["XCAGI_AUTONOMY_DATA_DIR"] = str(runtime / "autonomy")
    candidates: list[Path] = []
    configured = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser() / "FHD")
    candidates.append(Path(__file__).resolve().parents[3] / "FHD")
    for candidate in candidates:
        if (candidate / "app/domain/autonomy/autonomy_guard.py").is_file():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            # FHD's application package is an eager convenience aggregator and
            # imports the full server dependency graph. MODstore only needs the
            # autonomy subpackage, so expose it as a namespace package here.
            # This avoids coupling the lightweight loop worker to unrelated FHD
            # dependencies while preserving the canonical module paths.
            if "app.application" not in sys.modules:
                application = types.ModuleType("app.application")
                application.__path__ = [str(candidate / "app" / "application")]
                application.__package__ = "app.application"
                sys.modules["app.application"] = application
            if "app.application.employee_runtime" not in sys.modules:
                employee_runtime = types.ModuleType("app.application.employee_runtime")
                employee_runtime.__path__ = [
                    str(candidate / "app" / "application" / "employee_runtime")
                ]
                employee_runtime.__package__ = "app.application.employee_runtime"
                sys.modules["app.application.employee_runtime"] = employee_runtime
            return
    raise RuntimeError("FHD autonomy_guard SSOT is unavailable")


def evaluate_risk(
    action: Any,
    context: dict[str, Any] | None = None,
    *,
    action_id: str | None = None,
    source: str,
):
    ensure_fhd_on_path()
    from app.domain.autonomy.autonomy_guard import evaluate_risk as domain_evaluate_risk

    return domain_evaluate_risk(action, context, action_id=action_id, source=source)


def request_action(
    action: str,
    *,
    action_id: str,
    payload: dict[str, Any] | None,
    source: str,
):
    ensure_fhd_on_path()
    from app.application.autonomy.approval_resume import request_action as application_request

    return application_request(
        action,
        action_id=action_id,
        payload=payload,
        source=source,
    )


__all__ = ["ensure_fhd_on_path", "evaluate_risk", "request_action"]
