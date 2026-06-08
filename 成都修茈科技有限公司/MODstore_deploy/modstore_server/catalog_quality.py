"""公开市场员工包质量检测与六维报告（craft validate + six_dimension）。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PUBLIC_TABULAR_PKG_IDS: Tuple[str, ...] = (
    "excel-generate-employee",
    "excel-full-read-employee",
    "csv-generate-employee",
    "csv-full-read-employee",
    "pdf-generate-employee",
    "pdf-full-read-employee",
    "ppt-generate-employee",
    "ppt-full-read-employee",
    "word-generate-employee",
    "word-full-read-employee",
)

OFFICE_AUX_PACK_1_PKG_IDS: Tuple[str, ...] = ("json-report-employee",)

PUBLIC_OFFICE_EMPLOYEE_PKG_IDS: Tuple[str, ...] = PUBLIC_TABULAR_PKG_IDS + OFFICE_AUX_PACK_1_PKG_IDS

STANDARD_DISPLAY_NAMES: Dict[str, str] = {
    "excel-generate-employee": "Excel 生成员",
    "excel-full-read-employee": "Excel 读取员",
    "csv-generate-employee": "CSV 生成员",
    "csv-full-read-employee": "CSV 全量读取员",
    "pdf-generate-employee": "PDF 生成员",
    "pdf-full-read-employee": "PDF 全量读取员",
    "ppt-generate-employee": "PPT 生成员",
    "ppt-full-read-employee": "PPT 全量读取员",
    "word-generate-employee": "Word 生成员",
    "word-full-read-employee": "Word 全量读取员",
    "json-report-employee": "JSON 量化报告员",
}

VALID_COMPLIANCE_STATUSES = frozenset({"approved", "under_review", "restricted", "delisted"})
QUALITY_CACHE_MAX_AGE_DAYS = 7
PROCESS_CACHE_TTL_SECONDS = 600


def resolve_employee_pack_dir(pkg_id: str) -> Optional[Path]:
    """从 Mod 库目录定位员工包路径（与 employee_runtime 库回退一致）。"""
    pid = str(pkg_id or "").strip()
    if not pid:
        return None
    try:
        from modman.repo_config import load_config, resolved_library
        from modman.store import find_mod_dir_by_manifest_id

        lib = resolved_library(load_config())
        lib.mkdir(parents=True, exist_ok=True)
        mod_dir = find_mod_dir_by_manifest_id(lib, pid)
        return mod_dir if mod_dir.is_dir() else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_employee_pack_dir failed for %s: %s", pid, exc)
        return None


def read_rule_spec_runtime_kind(pack_dir: Path) -> str:
    rule_path = pack_dir / "rule_spec.json"
    if not rule_path.is_file():
        return ""
    try:
        data = json.loads(rule_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return str(data.get("runtime_kind") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def pipeline_label_from_pack(pack_dir: Path, brief: str = "") -> str:
    rk = read_rule_spec_runtime_kind(pack_dir)
    if rk:
        return rk
    bl = (brief or "").lower()
    if "excel" in bl and ("生成" in brief or "generate" in bl):
        return "excel_generate"
    if "excel" in bl:
        return "excel_full_read"
    if "csv" in bl and ("生成" in brief or "generate" in bl):
        return "csv_generate"
    if "csv" in bl:
        return "csv_full_read"
    if "pdf" in bl and ("生成" in brief or "generate" in bl):
        return "pdf_generate"
    if "pdf" in bl:
        return "pdf_full_read"
    if "word" in bl and ("生成" in brief or "generate" in bl):
        return "word_generate"
    if "word" in bl or "docx" in bl:
        return "word_full_extract"
    return "asset_direct_python"


def canonical_display_name(pkg_id: str, manifest: Optional[Dict[str, Any]] = None) -> str:
    pid = str(pkg_id or "").strip()
    if pid in STANDARD_DISPLAY_NAMES:
        return STANDARD_DISPLAY_NAMES[pid]
    if isinstance(manifest, dict):
        name = str(manifest.get("name") or "").strip()
        if name and name != pid:
            return name[:256]
    return pid


def parse_quality_snapshot(graph_snapshot: str) -> Optional[Dict[str, Any]]:
    raw = (graph_snapshot or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    report = data.get("quality_report")
    if not isinstance(report, dict):
        return None
    audited_at = str(data.get("audited_at") or "").strip()
    return {"quality_report": report, "audited_at": audited_at, "raw": data}


def quality_snapshot_fresh(
    audited_at: str, *, max_age_days: int = QUALITY_CACHE_MAX_AGE_DAYS
) -> bool:
    if not audited_at:
        return False
    try:
        ts = datetime.fromisoformat(audited_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        return age <= timedelta(days=max_age_days)
    except Exception:  # noqa: BLE001
        return False


def build_quality_snapshot_payload(
    *,
    validate_errors: List[str],
    validate_warnings: List[str],
    six_dimension: Dict[str, Any],
    gate: Dict[str, Any],
    pack_dir: Path,
    pipeline_label: str,
) -> Dict[str, Any]:
    audited_at = datetime.now(timezone.utc).isoformat()
    return {
        "audited_at": audited_at,
        "quality_report": {
            "ok": len(validate_errors) == 0,
            "validate_errors": validate_errors,
            "validate_warnings": validate_warnings,
            "six_dimension": six_dimension,
            "gate": gate,
            "pipeline_label": pipeline_label,
            "pack_dir": str(pack_dir),
        },
    }


async def run_pack_validate(*, pack_dir: Path, brief: str = "") -> Dict[str, Any]:
    from modstore_server.craft_steps import _craft_validate

    return await _craft_validate(
        res={"ok": True, "path": str(pack_dir)}, brief=brief, pack_dir=pack_dir
    )


def compute_gate_from_report(report: Dict[str, Any]) -> Dict[str, Any]:
    passed = bool(report.get("passed"))
    critical_failed = bool(report.get("critical_failed"))
    failed_dims = report.get("failed_dimensions")
    if not isinstance(failed_dims, list):
        failed_dims = []
    return {
        "passed": passed,
        "critical_failed": critical_failed,
        "failed_dimensions": failed_dims,
        "overall_score": report.get("overall_score"),
        "overall_grade": report.get("overall_grade"),
    }


async def build_employee_quality_report(
    *,
    pack_dir: Path,
    brief: str = "",
    catalog_registered: bool = True,
    use_llm: bool = False,
    target_employee_id: str = "",
    user_id: int = 0,
) -> Dict[str, Any]:
    """对单个员工包目录执行 validate + 六维汇总；use_llm 时调用 hex-quality-assessor。"""
    from modstore_server.employee_six_dimension import compute_six_dimension_report
    from modstore_server.employee_six_dimension_llm import enrich_six_dimension_report_with_llm

    pipeline_label = pipeline_label_from_pack(pack_dir, brief)
    val = await run_pack_validate(pack_dir=pack_dir, brief=brief)
    validate_errors = list(val.get("validate_errors") or [])
    validate_warnings = list(val.get("validate_warnings") or [])

    six_dimension = compute_six_dimension_report(
        pack_dir=pack_dir,
        pipeline_label=pipeline_label,
        routing_brief=brief,
        validate_errors=validate_errors,
        catalog_registered=catalog_registered,
        employee_target="pack_only",
        standalone_smoke_ok=True,
    )
    eid = (target_employee_id or pack_dir.name).strip()
    llm_meta: Dict[str, Any] = {}
    if use_llm:
        six_dimension, llm_meta = await enrich_six_dimension_report_with_llm(
            six_dimension,
            pack_dir=pack_dir,
            target_employee_id=eid,
            pipeline_label=pipeline_label,
            routing_brief=brief,
            validate_errors=validate_errors,
            user_id=int(user_id or 0),
            require_llm=True,
        )
    gate = compute_gate_from_report(six_dimension)
    return {
        "ok": len(validate_errors) == 0,
        "validate_errors": validate_errors,
        "validate_warnings": validate_warnings,
        "six_dimension": six_dimension,
        "gate": gate,
        "pipeline_label": pipeline_label,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "from_cache": False,
        "six_dimension_llm_meta": llm_meta or None,
    }


def run_build_employee_quality_report_sync(**kwargs: Any) -> Dict[str, Any]:
    return asyncio.run(build_employee_quality_report(**kwargs))


def load_cached_quality_from_item(
    item: Any, *, force_refresh: bool = False
) -> Optional[Dict[str, Any]]:
    if force_refresh:
        return None
    snap = parse_quality_snapshot(str(getattr(item, "graph_snapshot", "") or ""))
    if not snap:
        return None
    if not quality_snapshot_fresh(str(snap.get("audited_at") or "")):
        return None
    report = snap.get("quality_report")
    if not isinstance(report, dict):
        return None
    out = dict(report)
    out["from_cache"] = True
    out["audited_at"] = snap.get("audited_at")
    return out


def process_cache_key(pkg_id: str, sha256: str) -> str:
    return f"market:quality:{pkg_id}:{sha256 or 'none'}"


def get_process_cached_quality(pkg_id: str, sha256: str) -> Optional[Dict[str, Any]]:
    from modstore_server import cache

    return cache.get_json(process_cache_key(pkg_id, sha256))


def set_process_cached_quality(pkg_id: str, sha256: str, payload: Dict[str, Any]) -> None:
    from modstore_server import cache

    cache.set_json(
        process_cache_key(pkg_id, sha256), payload, ttl_seconds=PROCESS_CACHE_TTL_SECONDS
    )


async def quality_report_for_catalog_item(
    item: Any,
    *,
    brief: str = "",
    force_refresh: bool = False,
    write_snapshot: bool = False,
    session: Any = None,
    use_llm: bool = False,
    user_id: int = 0,
) -> Dict[str, Any]:
    """为 catalog 行生成或读取质量报告。"""
    pkg_id = str(getattr(item, "pkg_id", "") or "").strip()
    sha = str(getattr(item, "sha256", "") or "").strip()

    if not force_refresh and not use_llm:
        cached = get_process_cached_quality(pkg_id, sha)
        if cached is not None:
            return cached
        db_cached = load_cached_quality_from_item(item, force_refresh=False)
        if db_cached is not None:
            set_process_cached_quality(pkg_id, sha, db_cached)
            return db_cached

    pack_dir = resolve_employee_pack_dir(pkg_id)
    if not pack_dir:
        return {
            "ok": False,
            "validate_errors": [f"库中未找到员工包目录：{pkg_id}"],
            "validate_warnings": [],
            "six_dimension": None,
            "gate": {"passed": False, "critical_failed": True, "failed_dimensions": []},
            "pipeline_label": "",
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": False,
        }

    use_brief = brief or str(getattr(item, "description", "") or "")
    report = await build_employee_quality_report(
        pack_dir=pack_dir,
        brief=use_brief,
        catalog_registered=True,
        use_llm=use_llm,
        target_employee_id=pkg_id,
        user_id=user_id,
    )

    if write_snapshot and session is not None:
        snap_payload = build_quality_snapshot_payload(
            validate_errors=report["validate_errors"],
            validate_warnings=report["validate_warnings"],
            six_dimension=report["six_dimension"],
            gate=report["gate"],
            pack_dir=pack_dir,
            pipeline_label=report.get("pipeline_label") or "",
        )
        item.graph_snapshot = json.dumps(snap_payload, ensure_ascii=False)
        try:
            session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("quality snapshot commit failed for %s: %s", pkg_id, exc)
            session.rollback()

    set_process_cached_quality(pkg_id, sha, report)
    return report
