"""Thin MODstore delegate to the FHD domain autonomy guard SSOT."""

from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path
from typing import Any

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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


def _candidate_fhd_roots() -> list[Path]:
    """Resolve FHD roots that may contain autonomy_guard SSOT.

    Daily runtime often sets ``XCAGI_FHD_ROOT`` / ``XCMAX_MONOREPO_ROOT`` to a
    mirrored tree that can lag the workspace. Prefer explicit runtime overrides,
    then env roots, then ``MODSTORE_GIT_REPO_ROOT`` (source checkout), then
    layout-relative guesses for both runtime and monorepo checkouts.
    """
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        text = str(path.expanduser())
        if not text or text in seen:
            return
        seen.add(text)
        candidates.append(Path(text))

    for key in ("XCAGI_FHD_RUNTIME_ROOT", "XCAGI_FHD_ROOT", "MODSTORE_DAILY_FHD_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            add(Path(raw))
    for key in (
        "XCMAX_MONOREPO_ROOT",
        "MODSTORE_GIT_REPO_ROOT",
        "MODSTORE_DAILY_XCMAX_ROOT",
    ):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            add(Path(raw) / "FHD")
    here = Path(__file__).resolve()
    # Runtime: <runtime>/MODstore_deploy/modstore_server → parents[2]/FHD
    # Workspace: <repo>/成都修茈.../MODstore_deploy/modstore_server → parents[3]/FHD
    if len(here.parents) > 2:
        add(here.parents[2] / "FHD")
    if len(here.parents) > 3:
        add(here.parents[3] / "FHD")
    return candidates


def ensure_fhd_on_path() -> None:
    if (
        not (os.environ.get("XCAGI_AUTONOMY_DATA_DIR") or "").strip()
        and not (os.environ.get("XCAGI_DATA_DIR") or "").strip()
    ):
        runtime = Path(
            os.environ.get("MODSTORE_RUNTIME_DIR") or str(Path.home() / ".xcmax" / "modstore-daily")
        ).expanduser()
        os.environ["XCAGI_AUTONOMY_DATA_DIR"] = str(runtime / "autonomy")
    for candidate in _candidate_fhd_roots():
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
            _prepend_package_path(
                "app.application.autonomy",
                candidate / "app" / "application" / "autonomy",
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

    try:
        decision = domain_evaluate_risk(action, context, action_id=action_id, source=source)
    except RECOVERABLE_ERRORS as exc:
        if exc.__class__.__name__ == "ProhibitedActionError" and getattr(exc, "action_id", None):
            try:
                from modstore_server.autonomy_decision_audit import (
                    append_prohibited_exception,
                )

                append_prohibited_exception(
                    action=getattr(exc, "action", "unknown"),
                    action_id=getattr(exc, "action_id", action_id),
                    context=context,
                    source=source,
                )
            except RECOVERABLE_ERRORS:
                # Preserve the hard policy exception; an audit outage must not
                # accidentally turn a prohibited action into an allowed one.
                logger.exception("failed to mirror prohibited autonomy decision")
        raise

    from modstore_server.autonomy_decision_audit import append_domain_risk_decision

    # Successful decisions fail closed when their immutable audit append fails:
    # an autonomous action must never execute without a durable decision trail.
    append_domain_risk_decision(decision, context=context, source=source)
    return decision


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
