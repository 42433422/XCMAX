"""Shared deterministic test builders; assertions and fixture scopes stay at call sites."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


def super_employee_request(request_id: str = "req-1", **overrides) -> dict:
    base = {
        "request_id": request_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": "xcagi_admin_im",
        "employee_id": "codex-super-employee",
        "employee_name": "超级员工-Codex",
        "mode": "code",
        "device_scope": "all_devices",
        "target_devices": ["all"],
        "user_id": 1,
        "title": "test task",
        "task": "test task",
        "prompt": "test task",
        "workspace_root": "",
        "raw_context": {},
    }
    base.update(overrides)
    return base


def department_catalog() -> dict[str, dict[str, str]]:
    return {
        "ops_acquisition": {"label": "O-A 获客部"},
        "ops_partner": {"label": "O-B 伙伴部"},
        "prod_web": {"label": "P-W 网站部"},
        "prod_mod": {"label": "P-M Mod 部"},
        "prod_software": {"label": "P-S 软件部"},
        "shared_retention": {"label": "S-R 归档部"},
    }


def extract_row(**kwargs):
    defaults = {
        "id": 1,
        "file_name": "demo.xlsx",
        "file_path": "/tmp/demo.xlsx",
        "data_type": "product",
        "total_rows": 10,
        "valid_rows": 8,
        "imported_rows": 7,
        "skipped_rows": 1,
        "failed_rows": 0,
        "status": "done",
        "error_message": None,
        "field_mapping": json.dumps({"a": "b"}),
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def tenant_profile(
    *,
    name: str = "涂料",
    units: dict | None = None,
    quantity_fields: dict | None = None,
    product_fields: dict | None = None,
    order_types: dict | None = None,
    print_config: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        units=units or {"桶": {"abbr": "t"}},
        quantity_fields=quantity_fields or {"primary_field": "tins"},
        product_fields=product_fields or {"name": "name"},
        order_types=order_types or {"shipment": "发货单"},
        print_config=print_config or {"template": "default"},
    )


def enterprise_department_catalog() -> dict[str, dict[str, str]]:
    return {
        "tools": {"label": "工具层"},
        "execution": {"label": "执行层"},
        "service": {"label": "服务层"},
        "management": {"label": "管理层"},
    }


def customers_registry() -> dict:
    return {
        "customers": {
            "actions": {
                "query": {"risk": "low", "idempotent": True},
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                },
            }
        }
    }


def error_runner(exc):
    def _run(cmd, **kw):
        raise exc

    return _run


def mod_directory(root: Path, mod_id: str, extra: dict | None = None) -> Path:
    mod_dir = root / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    data = {"id": mod_id, "name": mod_id.title(), "version": "1.0.0"}
    if extra:
        data.update(extra)
    (mod_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return mod_dir
