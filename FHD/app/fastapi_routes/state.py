"""客户端状态 API（原版模式开关等），自归档 state 蓝图迁移。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/state", tags=["client-state"])

# Test compatibility override.  Normal state belongs to userData; a
# module-relative ``.archive`` would be inside the signed packaged backend.
STATE_FILE: Path | None = None


def _state_file() -> Path:
    if STATE_FILE is not None:
        return STATE_FILE
    return Path(get_app_data_dir()) / "config" / "client_mods_state.json"


def read_client_mods_off_state() -> bool:
    try:
        state_file = _state_file()
        if state_file.exists():
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return bool(data.get("client_mods_off", False))
    except RECOVERABLE_ERRORS as e:
        logger.warning("[State API] 读取状态文件失败: %s", e)
    return False


def write_client_mods_off_state(value: bool) -> None:
    try:
        state_file = _state_file()
        data = {
            "client_mods_off": value,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[State API] 已写入 client_mods_off=%s", value)
    except RECOVERABLE_ERRORS as e:
        logger.error("[State API] 写入状态文件失败: %s", e)


@router.get("/client-mods-off")
def get_client_mods_off():
    return JSONResponse(
        {
            "success": True,
            "data": {"client_mods_off": read_client_mods_off_state()},
        }
    )


@router.post("/client-mods-off")
def set_client_mods_off(body: dict[str, Any] = Body(default_factory=dict)):
    value = bool(body.get("client_mods_off", False))
    write_client_mods_off_state(value)
    return JSONResponse(
        {
            "success": True,
            "data": {"client_mods_off": value},
        }
    )
