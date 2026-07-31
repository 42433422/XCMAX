"""Shipment label output path helpers (extracted for arch-fitness size gate)."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from app.utils.path_utils import get_app_data_dir


def _current_label_owner_user_id() -> int | None:
    """Read the authenticated owner from request context when callers omit it."""

    try:
        from app.infrastructure.request_context import get_current_request

        request = get_current_request()
        value = getattr(getattr(request, "state", None), "user_id", None)
        return int(value) if value is not None else None
    except (ImportError, TypeError, ValueError, AttributeError):
        return None





def _current_label_tenant_id() -> int | None:
    try:
        from app.infrastructure.tenant_scope import current_tenant_id

        return current_tenant_id()
    except (ImportError, TypeError, ValueError, AttributeError):
        return None





def _positive_scope_id(value: Any, *, fallback: str) -> str:
    """Return a filesystem-safe tenant/owner scope without trusting a path."""

    try:
        normalized = int(value) if value is not None else 0
    except (TypeError, ValueError):
        normalized = 0
    return str(normalized) if normalized > 0 else fallback





def _safe_label_run_id(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return uuid.uuid4().hex
    # A run id is an opaque directory component, never an input path.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return cleaned[:96] or uuid.uuid4().hex





def get_shipment_label_output_dir(
    *,
    tenant_id: int | None = None,
    owner_user_id: int | None = None,
    run_id: str | None = None,
) -> tuple[str, str]:
    """Allocate the per-run user-data directory for generated shipment labels.

    Bundled ``resources`` are read-only in signed desktop builds.  Labels are
    business outputs, so they must be isolated by tenant, authenticated owner,
    and generation run under the desktop user-data root instead.
    """

    resolved_tenant_id = tenant_id if tenant_id is not None else _current_label_tenant_id()
    resolved_owner_user_id = (
        owner_user_id if owner_user_id is not None else _current_label_owner_user_id()
    )
    tenant_scope = _positive_scope_id(resolved_tenant_id, fallback="local")
    owner_scope = _positive_scope_id(resolved_owner_user_id, fallback="local")
    label_run_id = _safe_label_run_id(run_id)

    explicit_data_dir = os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR")
    if explicit_data_dir:
        explicit_path = Path(explicit_data_dir).expanduser()
        if not explicit_path.is_absolute():
            raise OSError("shipment label user-data directory must be absolute")
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            try:
                resource_root = Path(frozen_root).resolve()
                resolved_explicit = explicit_path.resolve()
                if resolved_explicit == resource_root or resource_root in resolved_explicit.parents:
                    raise OSError(
                        "shipment label user-data directory cannot be inside app resources"
                    )
            except OSError:
                raise
            except (TypeError, ValueError) as exc:
                raise OSError("shipment label user-data directory is invalid") from exc
    app_data_dir = Path(get_app_data_dir()).expanduser()
    # ``XCAGI_DATA_DIR`` is expected to be absolute in packaged desktop mode.
    # Rejecting a relative override avoids silently resolving it against the
    # PyInstaller/Electron executable directory.
    if not app_data_dir.is_absolute():
        raise OSError("shipment label user-data directory must be absolute")
    output_dir = (
        app_data_dir.resolve()
        / "shipment_outputs"
        / "labels"
        / "tenants"
        / tenant_scope
        / "owners"
        / owner_scope
        / "runs"
        / label_run_id
    )
    return str(output_dir), label_run_id



