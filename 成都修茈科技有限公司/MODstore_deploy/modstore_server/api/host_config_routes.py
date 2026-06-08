# -*- coding: utf-8 -*-
"""宿主配置 API：与 FHD /api/system/* 对齐，供 MODstore 制作端读取 config/*.json。"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["config"])


def _fhd_root() -> Path | None:
    for raw in (
        os.environ.get("XCAGI_FHD_ROOT"),
        os.environ.get("XCMAX_FHD_ROOT"),
    ):
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                return p
    here = Path(__file__).resolve()
    for parent in here.parents:
        trial = parent / "FHD"
        if trial.is_dir() and (trial / "config" / "host_profiles").is_dir():
            return trial
    return None


def _config_dir() -> Path | None:
    root = _fhd_root()
    if root is None:
        return None
    cfg = root / "config"
    return cfg if cfg.is_dir() else None


def _try_fhd_sdk(fn_name: str, *args: Any, **kwargs: Any) -> Any:
    root = _fhd_root()
    if root is None:
        return None
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    try:
        import app.mod_sdk.host_profile as hp

        fn = getattr(hp, fn_name, None)
        if callable(fn):
            return fn(*args, **kwargs)
    except Exception:
        logger.debug("FHD host_profile.%s unavailable", fn_name, exc_info=True)
    return None


def _read_json(name: str) -> dict[str, Any]:
    cfg = _config_dir()
    if cfg is None:
        raise HTTPException(status_code=503, detail="FHD config directory not found")
    path = cfg / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Missing config file: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/host-profile")
async def get_host_profile():
    payload = _try_fhd_sdk("build_host_profile_api_payload")
    if payload is not None:
        return {"success": True, "data": payload}
    raise HTTPException(status_code=503, detail="host profile unavailable")


def _load_industry_presets_document() -> dict[str, Any]:
    doc = _try_fhd_sdk("load_industry_presets_document")
    if doc is not None:
        return doc
    try:
        return _read_json("industry_presets.json")
    except HTTPException:
        pass
    deploy_root = Path(__file__).resolve().parents[2]
    for trial in (
        deploy_root / "FHD" / "config" / "industry_presets.json",
        deploy_root / "config" / "industry_presets.json",
    ):
        if trial.is_file():
            data = json.loads(trial.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    raise HTTPException(status_code=503, detail="industry presets config not found")


@router.get("/industry-presets")
async def get_industry_presets():
    doc = _load_industry_presets_document()
    return {
        "success": True,
        "data": {
            "schema_version": doc.get("schema_version", 1),
            "preset_ids": doc.get("preset_ids") or list((doc.get("presets") or {}).keys()),
            "presets": doc.get("presets") or {},
        },
    }


@router.get("/workflow-employee-catalog")
async def get_workflow_employee_catalog():
    catalog = _try_fhd_sdk("scan_workflow_employee_catalog_from_mods")
    static = _try_fhd_sdk("load_workflow_employee_catalog")
    prof = _try_fhd_sdk("load_host_profile")
    if catalog is None:
        catalog = _read_json("workflow_employee_catalog.json")
    return {
        "success": True,
        "data": {
            "catalog": catalog,
            "workflow_delivery": (prof or {}).get("workflow_delivery") if prof else None,
            "workflow_monolith_mod_id": (
                (prof or {}).get("workflow_monolith_mod_id") if prof else None
            ),
            "workflow_split_mod_ids": (prof or {}).get("workflow_split_mod_ids") if prof else None,
            "static_catalog": static or {},
        },
    }


@router.get("/employee-registry-rules")
async def get_employee_registry_rules():
    rules = _try_fhd_sdk("get_employee_registry_rules")
    if rules is None:
        try:
            base = _read_json("host_profiles/_base.json")
            rules = base.get("employee_registry_rules") or {}
        except HTTPException:
            deploy_root = Path(__file__).resolve().parents[2]
            for trial in (
                deploy_root / "FHD" / "config" / "host_profiles" / "_base.json",
                deploy_root / "config" / "host_profiles" / "_base.json",
            ):
                if trial.is_file():
                    base = json.loads(trial.read_text(encoding="utf-8"))
                    rules = base.get("employee_registry_rules") if isinstance(base, dict) else {}
                    break
            else:
                rules = {}
    return {"success": True, "data": rules}
