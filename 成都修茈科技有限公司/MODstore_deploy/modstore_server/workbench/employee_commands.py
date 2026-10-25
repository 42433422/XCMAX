"""Employee commands for workbench delivery."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, cast

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.catalog import (
    _load_registry_aligned_employee_manifest,
    store_catalog_row,
)
from modstore_server.workbench.schemas import (
    EmployeeBenchRequest,
    EmployeePublishRequest,
    EmployeeSyncTestRequest,
)

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeCommandPorts:
    database: Callable[[], Callable[[], Session]]
    library: Callable[[], Path]
    materialize: Callable[..., bool]


async def employee_bench_test(
    body: EmployeeBenchRequest,
    user: User = Depends(_get_current_user),
    *,
    ports: EmployeeCommandPorts,
):
    """
    1. LLM 生成 1-5 级（每级 3 条）共 15 项测试任务
    2. 逐条执行并记录 ok / cost_tokens / duration_ms
    3. 量化打分 + 五维审核
    4. 返回完整报告，前端据此决定是否允许上架
    """
    from modstore_server.employee_bench import generate_bench_tasks, run_and_score_bench

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise HTTPException(400, "employee_id 不能为空")
    ports.materialize(employee_id)
    pack_dir = ports.library() / employee_id
    brief = ""
    panel_summary = ""
    mf_path = pack_dir / "manifest.json"
    if mf_path.is_file():
        try:
            mf = json.loads(mf_path.read_text(encoding="utf-8"))
            brief = (
                str(mf.get("description") or "")
                or str(mf.get("identity", {}).get("description") or "")
            )[:800]
            rows = mf.get("workflow_employees") or []
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
        except RECOVERABLE_ERRORS:
            pass
    sf = ports.database()
    with sf() as db:
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()
        if not prov or not mdl:
            raise HTTPException(
                503,
                "基准测试需要平台 LLM 密钥（服务端环境变量），当前未配置。请联系运维设置 MODSTORE_EMPLOYEE_BENCH_PROVIDER + MODSTORE_EMPLOYEE_BENCH_MODEL 及对应供应商的 API Key 环境变量。",
            )
        try:
            task_list = await generate_bench_tasks(
                brief or employee_id,
                panel_summary,
                db=db,
                user_id=cast(int, user.id),
                provider=prov,
                model=mdl,
                use_platform_dispatch=True,
                strict=True,
            )
        except RuntimeError as exc:
            raise HTTPException(502, f"基准任务生成失败（LLM 调用）：{exc}") from exc
        report = await run_and_score_bench(
            employee_id,
            task_list,
            db=db,
            user=user,
            bench_llm_override=(prov, mdl),
            per_dimension_ids=body.per_dimension_ids,
        )
    return {"ok": True, "employee_id": employee_id, **report}


async def employee_publish(
    body: EmployeePublishRequest,
    user: User = Depends(_get_current_user),
    *,
    ports: EmployeeCommandPorts,
):
    """
    将本地库中的员工包重建 zip 并写入商店目录（catalog_store + catalog_items）。
    调用方应先通过 /employee-bench-test 且 passed=true，再调此接口。
    """
    from modstore_server.catalog_store import (
        append_package,
        package_manifest_alignment_errors,
    )
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise HTTPException(400, "employee_id 不能为空")
    ports.materialize(employee_id)
    pack_dir = ports.library() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        raise HTTPException(404, f"员工包不存在: {employee_id}")
    try:
        raw_mf = _load_registry_aligned_employee_manifest(pack_dir, employee_id)
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"manifest.json 读取失败: {exc}") from exc
    mf_path.write_text(
        json.dumps(raw_mf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        pkg_id = str(raw_mf.get("id") or employee_id).strip() or employee_id
        from modstore_server.employee_asset_pipeline import (
            build_employee_pack_zip_for_library,
        )

        zip_bytes = build_employee_pack_zip_for_library(
            pkg_id, raw_mf, pack_dir=pack_dir
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"员工包打包失败: {exc}") from exc
    version = str(raw_mf.get("version") or "1.0.0").strip()
    rec = {
        "id": pkg_id,
        "name": str(raw_mf.get("name") or pkg_id),
        "version": version,
        "description": str(raw_mf.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry or str(raw_mf.get("industry") or "通用"),
        "release_channel": body.release_channel or "stable",
        "commerce": {
            "mode": "free" if body.price <= 0 else "paid",
            "price": body.price,
        },
        "license": {"type": "personal", "verify_url": None},
    }
    import tempfile as _tmpmod

    with _tmpmod.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = Path(tmp.name)
    try:
        align_errs = package_manifest_alignment_errors(rec, tmp_path)
        if align_errs:
            raise HTTPException(
                400, "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs)
            )
        saved = append_package(rec, tmp_path)
    except RECOVERABLE_ERRORS as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(500, f"写入 catalog_store 失败: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    sf = ports.database()
    with sf() as db:
        try:
            upsert_catalog_item_from_xc_package_dict(
                db, saved, author_id=cast(int, user.id)
            )
            row = store_catalog_row(
                db,
                pack_id=pkg_id,
                author_id=cast(int, user.id),
                saved=saved,
                metadata=rec,
                price=float(body.price),
                artifact="employee_pack",
            )
            db.commit()
            try:
                from modstore_server.employee_asset_pipeline import (
                    mirror_catalog_file_to_market_files,
                )

                mirror_catalog_file_to_market_files(row.stored_filename)
            except RECOVERABLE_ERRORS:
                pass
        except RECOVERABLE_ERRORS as exc:
            db.rollback()
            raise HTTPException(500, f"写入数据库失败: {exc}") from exc
    return {
        "ok": True,
        "pkg_id": pkg_id,
        "version": saved.get("version") or version,
        "stored_filename": saved.get("stored_filename") or "",
        "name": saved.get("name") or rec["name"],
    }


async def employee_sync_test(
    body: EmployeeSyncTestRequest,
    user: User = Depends(_get_current_user),
    *,
    ports: EmployeeCommandPorts,
):
    """
    一键同步流程：
    1. LLM 生成 1-5 级测试任务并执行 + 五维审核
    2. 通过后发布到 MODstore catalog（/v1/packages）
    3. 调用宿主 fhd-sandbox-runtime 的 /api/mod-store/install 安装此员工包
       → 员工出现在宿主「一键托管」面板、「员工工作流管理」页等位置
    """
    import httpx

    from modstore_server.catalog_store import (
        append_package,
        package_manifest_alignment_errors,
    )
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_bench import generate_bench_tasks, run_and_score_bench

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise HTTPException(400, "employee_id 不能为空")
    ports.materialize(employee_id)
    pack_dir = ports.library() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        raise HTTPException(404, f"员工包不存在: {employee_id}")
    try:
        raw_mf = _load_registry_aligned_employee_manifest(pack_dir, employee_id)
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"manifest.json 读取失败: {exc}") from exc
    brief = str(raw_mf.get("description") or "").strip()[:800]
    rows = raw_mf.get("workflow_employees") or []
    panel_summary = ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
    from modstore_server.services.llm import resolve_platform_bench_llm

    prov, mdl = resolve_platform_bench_llm()
    if not prov or not mdl:
        raise HTTPException(
            503,
            "同步测试需要平台 LLM 密钥（服务端环境变量），当前未配置。请联系运维设置 MODSTORE_EMPLOYEE_BENCH_PROVIDER + MODSTORE_EMPLOYEE_BENCH_MODEL 及对应供应商的 API Key 环境变量。",
        )
    sf = ports.database()
    with sf() as db:
        try:
            task_list = await generate_bench_tasks(
                brief or employee_id,
                panel_summary,
                db=db,
                user_id=cast(int, user.id),
                provider=prov,
                model=mdl,
                use_platform_dispatch=True,
                strict=True,
            )
        except RuntimeError as exc:
            raise HTTPException(502, f"基准任务生成失败（LLM 调用）：{exc}") from exc
        report = await run_and_score_bench(
            employee_id,
            task_list,
            db=db,
            user=user,
            bench_llm_override=(prov, mdl),
            per_dimension_ids=body.per_dimension_ids,
        )
    if not report.get("passed"):
        return {
            "ok": False,
            "stage": "bench_test",
            "reason": f"基准测试未通过（得分 {report.get('overall_score', 0):.1f}，需 ≥ 60）",
            "bench": report,
        }
    pkg_id = str(raw_mf.get("id") or employee_id).strip() or employee_id
    version = str(raw_mf.get("version") or "1.0.0").strip()
    try:
        from modstore_server.employee_asset_pipeline import (
            build_employee_pack_zip_for_library,
        )

        zip_bytes = build_employee_pack_zip_for_library(
            pkg_id, raw_mf, pack_dir=pack_dir
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"员工包打包失败: {exc}") from exc
    rec = {
        "id": pkg_id,
        "name": str(raw_mf.get("name") or pkg_id),
        "version": version,
        "description": str(raw_mf.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry or str(raw_mf.get("industry") or "通用"),
        "release_channel": "stable",
        "commerce": {"mode": "free", "price": 0.0},
        "license": {"type": "personal", "verify_url": None},
    }
    import tempfile as _tmpmod

    with _tmpmod.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path_str = tmp.name
    try:
        align_errs = package_manifest_alignment_errors(rec, Path(tmp_path_str))
        if align_errs:
            raise HTTPException(
                400, "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs)
            )
        saved = append_package(rec, Path(tmp_path_str))
    except RECOVERABLE_ERRORS as exc:
        Path(tmp_path_str).unlink(missing_ok=True)
        raise HTTPException(500, f"写入 catalog_store 失败: {exc}") from exc
    finally:
        Path(tmp_path_str).unlink(missing_ok=True)
    sf2 = ports.database()
    with sf2() as db2:
        try:
            upsert_catalog_item_from_xc_package_dict(
                db2, saved, author_id=cast(int, user.id)
            )
            store_catalog_row(
                db2,
                pack_id=pkg_id,
                author_id=cast(int, user.id),
                saved=saved,
                metadata=rec,
                price=0.0,
                artifact="employee_pack",
            )
            db2.commit()
        except RECOVERABLE_ERRORS as exc:
            db2.rollback()
            raise HTTPException(500, f"写入数据库失败: {exc}") from exc
    fhd_base = (body.fhd_base_url or "").strip().rstrip("/")
    fhd_result: Dict[str, Any] = {"skipped": True, "reason": "未提供 fhd_base_url"}
    if fhd_base:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{fhd_base}/api/mod-store/install",
                    json={
                        "pkg_id": pkg_id,
                        "version": saved.get("version") or version,
                        "activate": True,
                    },
                )
            if r.status_code < 400:
                fhd_result = {"ok": True, "status": r.status_code, "data": r.json()}
            else:
                fhd_result = {
                    "ok": False,
                    "status": r.status_code,
                    "error": r.text[:400],
                }
        except RECOVERABLE_ERRORS as exc:
            fhd_result = {"ok": False, "error": str(exc)[:400]}
    return {
        "ok": True,
        "stage": "synced",
        "pkg_id": pkg_id,
        "version": saved.get("version") or version,
        "bench": report,
        "catalog": {"ok": True, "stored_filename": saved.get("stored_filename") or ""},
        "fhd_install": fhd_result,
    }
