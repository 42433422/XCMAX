"""供 Mod / hooks 等同步读取客户端状态（与 FastAPI ``state_compat`` 同源）。"""

from app.fastapi_routes.state import (  # noqa: F401
    read_client_mods_off_state,
    write_client_mods_off_state,
)
