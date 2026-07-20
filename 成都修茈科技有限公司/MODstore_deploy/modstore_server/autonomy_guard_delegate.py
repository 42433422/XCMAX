"""Thin MODstore delegate to the FHD domain autonomy guard SSOT."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any


def _prepend_package_path(module_name: str, package_path: Path, *, create: bool) -> None:
    module = sys.modules.get(module_name)
    if module is None and create:
        module = types.ModuleType(module_name)
        module.__path__ = [str(package_path)]
        module.__package__ = module_name
        sys.modules[module_name] = module
    if module is None:
        return
    search_path = getattr(module, "__path__", None)
    if search_path is None or str(package_path) in search_path:
        return
    try:
        search_path.insert(0, str(package_path))
    except AttributeError:
        search_path.append(str(package_path))


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
    runtime_fhd = (os.environ.get("XCAGI_FHD_RUNTIME_ROOT") or "").strip()
    if runtime_fhd:
        candidates.append(Path(runtime_fhd).expanduser())
    configured = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser() / "FHD")
    candidates.append(Path(__file__).resolve().parents[3] / "FHD")
    for candidate in candidates:
        if (candidate / "app/domain/autonomy/autonomy_guard.py").is_file():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            # A long-lived MODstore worker may already have an unrelated
            # ``app`` namespace loaded. sys.path alone cannot change that
            # package's submodule search path, so explicitly attach FHD.
            _prepend_package_path("app", candidate / "app", create=True)
            _prepend_package_path("app.domain", candidate / "app" / "domain", create=False)
            _prepend_package_path(
                "app.domain.autonomy",
                candidate / "app" / "domain" / "autonomy",
                create=False,
            )
            # FHD's application package is an eager convenience aggregator and
            # imports the full server dependency graph. MODstore only needs the
            # autonomy subpackage, so expose it as a namespace package here.
            # This avoids coupling the lightweight loop worker to unrelated FHD
            # dependencies while preserving the canonical module paths.
            _prepend_package_path("app.application", candidate / "app" / "application", create=True)
            _prepend_package_path(
                "app.application.employee_runtime",
                candidate / "app" / "application" / "employee_runtime",
                create=True,
            )
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
