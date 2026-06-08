"""运营开关与发布门禁 API。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User

router = APIRouter(prefix="/api/ops", tags=["ops"])

_FLAGS_FILE = Path(__file__).resolve().parent / "data" / "release_flags.json"


def _read_flags() -> Dict[str, bool]:
    if not _FLAGS_FILE.is_file():
        return {
            "entitlement_enabled": True,
            "employee_runtime_enabled": True,
            "workflow_realtime_enabled": True,
        }
    try:
        return json.loads(_FLAGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_flags(flags: Dict[str, bool]) -> None:
    _FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FLAGS_FILE.write_text(json.dumps(flags, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/release-gates")
def get_release_gates(user: User = Depends(_get_current_user)):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return {"flags": _read_flags(), "updated_at": datetime.now(timezone.utc).isoformat()}


@router.put("/release-gates")
def put_release_gates(payload: Dict[str, bool], user: User = Depends(_get_current_user)):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    flags = _read_flags()
    for k, v in (payload or {}).items():
        flags[str(k)] = bool(v)
    _save_flags(flags)
    return {"ok": True, "flags": flags}
