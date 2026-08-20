# mypy: disable-error-code="call-overload"
"""运行时真相投影（MODstore 侧）：读公开 JSON 或本机轻量探针。

完整探针 SSOT 在 ``FHD/scripts/ops/runtime_inventory.py``；此处供公司大厅 /
员工感知嵌入，避免跨包硬依赖 FHD app。
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA = "xcagi.runtime_inventory/v1"

# 与 FHD/config/service_topology.yaml 生产真值对齐（大厅 fallback 探针）
_DEFAULT_PROBES = (
    {"id": "modstore", "kind": "service", "port": 9999, "must_run": True},
    {"id": "modstore-scheduler", "kind": "service", "port": 9990, "must_run": True},
    {"id": "fhd-api-upstream", "kind": "service", "port": 5100, "must_run": True},
)


def _repo_root() -> Path:
    env = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


def _candidate_paths() -> List[Path]:
    root = _repo_root()
    out = [
        root / "成都修茈科技有限公司" / "download-runtime-inventory.json",
        root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-runtime-inventory.json",
        root / "FHD" / "config" / "runtime_inventory.generated.json",
    ]
    for raw in (
        "/root/成都修茈科技有限公司",
        "/opt/xcmax/current/成都修茈科技有限公司",
    ):
        try:
            live = Path(raw)
            if live.is_dir():
                out.append(live.resolve() / "download-runtime-inventory.json")
        except OSError:
            pass
    return out


def load_published_runtime_inventory() -> Optional[Dict[str, Any]]:
    for path in _candidate_paths():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema") == SCHEMA:
                data = dict(data)
                data["_loaded_from"] = str(path)
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("runtime_inventory: read failed %s: %s", path, exc)
    return None


def _port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def probe_local(*, host: str = "127.0.0.1") -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    failed = 0
    for spec in _DEFAULT_PROBES:
        alive = _port_open(host, int(spec["port"]))
        actual = "running" if alive else "stopped"
        must = bool(spec.get("must_run"))
        if must and not alive:
            failed += 1
        items.append(
            {
                "kind": spec["kind"],
                "id": spec["id"],
                "desired": "running" if must else "optional",
                "actual": actual,
                "must_run": must,
                "listen_port": spec["port"],
                "detail": f"{host}:{spec['port']}",
            }
        )
    running = sum(1 for i in items if i["actual"] == "running")
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "host": host,
        "ok": failed == 0,
        "failed_must_run": failed,
        "counts": {
            "total": len(items),
            "running": running,
            "stopped": len(items) - running,
            "unknown": 0,
            "must_run_failed": failed,
        },
        "items": items,
        "note": "modstore fallback probe（完整清单见 FHD runtime_inventory）",
        "source": {"probe": "modstore_local_ports"},
    }


def runtime_inventory_summary() -> Dict[str, Any]:
    """供公司大厅嵌入的精简视图：优先公开投影，否则本机端口探针。"""
    published = load_published_runtime_inventory()
    payload = published if published is not None else probe_local()
    items = list(payload.get("items") or [])
    must_failed = [
        {
            "kind": i.get("kind"),
            "id": i.get("id"),
            "actual": i.get("actual"),
            "detail": i.get("detail") or "",
        }
        for i in items
        if i.get("must_run") and i.get("actual") != "running"
    ]
    return {
        "schema": SCHEMA,
        "ok": bool(payload.get("ok")),
        "generated_at": payload.get("generated_at"),
        "failed_must_run": int(payload.get("failed_must_run") or len(must_failed)),
        "counts": dict(payload.get("counts") or {}),
        "must_run_failed_items": must_failed[:20],
        "source": payload.get("source") or payload.get("_loaded_from") or "probe",
        "note": "什么在跑/停了的单一可消费摘要；员工勿臆造进程状态。",
    }
