"""加载 six_line_event_routes.json 与事件轨持久化。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

_CONFIG_NAME = "six_line_event_routes.json"
_BACKLOG_NAME = "six_line_digest_backlog.jsonl"
_INCIDENT_OUTBOX = "incident_outbox.jsonl"
_AUDIT_NAME = "six_line_event_audit.jsonl"


def _config_path() -> Path:
    from app.utils.path_utils import get_base_dir

    return Path(get_base_dir()) / "config" / _CONFIG_NAME


def _customer_service_dir() -> Path:
    from app.utils.path_utils import get_base_dir, get_data_dir

    for base in (
        Path(get_data_dir()) / "customer_service",
        Path(get_base_dir()) / "data" / "customer_service",
    ):
        base.mkdir(parents=True, exist_ok=True)
        return base
    p = Path(get_data_dir()) / "customer_service"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_routes_config() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        logger.warning("six_line_event_routes.json missing: %s", path)
        return {}
    with path.open(encoding="utf-8") as f:
        return cast("dict[str, Any]", json.load(f))


def append_jsonl(filename: str, entry: dict[str, Any]) -> Path:
    path = _customer_service_dir() / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def append_backlog(entry: dict[str, Any]) -> Path:
    return append_jsonl(_BACKLOG_NAME, entry)


def append_incident_outbox(entry: dict[str, Any]) -> Path:
    return append_jsonl(_INCIDENT_OUTBOX, entry)


def append_audit(entry: dict[str, Any]) -> Path:
    return append_jsonl(_AUDIT_NAME, entry)


def count_jsonl_pending(filename: str) -> int:
    path = _customer_service_dir() / filename
    if not path.is_file():
        return 0
    n = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def read_recent_audit(limit: int = 20) -> list[dict[str, Any]]:
    path = _customer_service_dir() / _AUDIT_NAME
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
