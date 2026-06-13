# -*- coding: utf-8 -*-
"""从 mods/_employees 磁盘加载 employee_pack manifest 与 V2 配置。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.application.employee_runtime.config_v2_adapter import (
    needs_executor_translation,
    translate_v2_to_executor_config,
)
from app.utils.operational_errors import DATA_SHAPE, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DIRECT_PYTHON_RUNTIME_KINDS = frozenset(
    {
        "word_full_extract",
        "txt_full_read",
        "txt_generate",
        "pdf_full_read",
        "pdf_generate",
        "csv_full_read",
        "csv_generate",
        "generic_excel_transform",
        "contract_doc_review",
        "doc_template_transform",
        "ppt_full_read",
        "ppt_generate",
        "excel_full_read",
        "excel_generate",
    }
)

DIRECT_PYTHON_RUNTIME_MISSING_MSG = (
    "manifest 声明了 direct_python，但本地包缺少 rule_spec 与 backend/vendor/convert。"
    "请在工作台「做员工」流水线完成 generate 步后再安装；"
    "否则会覆盖为仅含 LLM 脚手架的空包。"
)


def _employees_root() -> Path:
    from app.infrastructure.mods.employee_registry import get_employee_registry

    return Path(get_employee_registry()._root())


def candidate_pack_ids(pack_id: str) -> list[str]:
    raw = str(pack_id or "").strip()
    if not raw:
        return []
    candidates = [raw]
    for item in (raw.replace("_", "-"), raw.replace("-", "_"), f"{raw.replace('_', '-')}-employee"):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def resolve_pack_dir(pack_id: str) -> Path | None:
    root = _employees_root()
    for cid in candidate_pack_ids(pack_id):
        pdir = root / cid
        if (pdir / "manifest.json").is_file():
            return pdir
    return None


def normalize_manifest_legacy_deepseek_to_auto(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        return
    v2 = manifest.get("employee_config_v2")
    if not isinstance(v2, dict):
        return
    cog = v2.get("cognition")
    if not isinstance(cog, dict):
        return
    agent = cog.get("agent")
    if not isinstance(agent, dict):
        return
    model = agent.get("model")
    if not isinstance(model, dict):
        return
    if str(model.get("provider") or "").strip().lower() != "deepseek":
        return
    model["provider"] = "auto"
    model["model_name"] = "auto"


def load_employee_pack_from_disk(pack_id: str) -> dict[str, Any]:
    pdir = resolve_pack_dir(pack_id)
    if pdir is None:
        raise ValueError(f"员工包未安装：{pack_id}")
    manifest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest 无效：{pack_id}")
    normalize_manifest_legacy_deepseek_to_auto(manifest)
    resolved_id = str(manifest.get("id") or pdir.name).strip() or pdir.name
    return {
        "pack_id": resolved_id,
        "name": str(manifest.get("name") or resolved_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "manifest": manifest,
        "pack_dir": str(pdir.resolve()),
    }


def parse_employee_config_v2(manifest: dict[str, Any]) -> dict[str, Any]:
    v2 = manifest.get("employee_config_v2") if isinstance(manifest, dict) else None
    if isinstance(v2, dict):
        if needs_executor_translation(v2):
            return translate_v2_to_executor_config(v2)
        return v2
    employee = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    label = employee.get("label") if isinstance(employee, dict) else None
    return {
        "perception": {"type": "text"},
        "memory": {"type": "session"},
        "cognition": {
            "agent": {
                "system_prompt": (f"你是员工助手：{label or manifest.get('name') or 'assistant'}"),
                "model": {"provider": "auto", "model_name": "auto", "max_tokens": 4000},
            }
        },
        "actions": {"handlers": ["echo"]},
    }


def manifest_actions_handlers(manifest: dict[str, Any]) -> list[str]:
    cfg = parse_employee_config_v2(manifest)
    actions = cfg.get("actions") if isinstance(cfg.get("actions"), dict) else {}
    inner = actions.get("actions") if isinstance(actions.get("actions"), dict) else actions
    raw = (inner or {}).get("handlers") or actions.get("handlers") or []
    return [str(x).strip() for x in raw if str(x).strip()]


def pack_has_direct_python_runtime(pack_dir: Path | str) -> bool:
    pdir = Path(pack_dir)
    if not pdir.is_dir():
        return False
    rs = pdir / "rule_spec.json"
    if rs.is_file():
        try:
            data = json.loads(rs.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("runtime_kind") in DIRECT_PYTHON_RUNTIME_KINDS:
                return True
        except (OSError, json.JSONDecodeError):
            pass
    backend = pdir / "backend"
    if not backend.is_dir():
        return False
    for py_path in backend.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def convert_file" in text and "vendor" in py_path.as_posix().lower():
            return True
        if "def convert" in text and "_import_runtime" in text:
            return True
    emp_dir = backend / "employees"
    if emp_dir.is_dir():
        for py in emp_dir.glob("*.py"):
            if not py.name.startswith("_"):
                return True
    return False


def build_employee_context(employee_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {"employee_id": employee_id, "input_data": input_data or {}}


def list_installed_pack_records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.employee_registry import get_employee_registry

        for row in get_employee_registry().list_packs():
            pack_id = str(row.get("pack_id") or row.get("id") or "").strip()
            if not pack_id:
                continue
            try:
                out.append(load_employee_pack_from_disk(pack_id))
            except DATA_SHAPE:
                logger.debug("skip broken employee pack %s", pack_id, exc_info=True)
    except RECOVERABLE_ERRORS:
        logger.debug("list_installed_pack_records failed", exc_info=True)
    return out


__all__ = [
    "DIRECT_PYTHON_RUNTIME_MISSING_MSG",
    "build_employee_context",
    "candidate_pack_ids",
    "list_installed_pack_records",
    "load_employee_pack_from_disk",
    "manifest_actions_handlers",
    "pack_has_direct_python_runtime",
    "parse_employee_config_v2",
    "resolve_pack_dir",
]
