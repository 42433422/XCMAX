"""按租户存放订单 Webhook 配置，文件在用户数据目录，不进安装包。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_data_dir


def list_webhooks(tenant_id: int) -> list[dict[str, Any]]:
    path = Path(get_data_dir()) / "order_webhooks.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        return []
    rows = (data.get("tenants") or {}).get(str(tenant_id), []) if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict)]
