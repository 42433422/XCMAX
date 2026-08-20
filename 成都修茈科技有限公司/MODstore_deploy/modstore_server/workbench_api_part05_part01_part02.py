# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib
from modstore_server.workbench_api_part05_part01_part01 import EmployeeSyncTestRequest


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


@_facade().router.post("/employee-sync-test", summary="员工同步测试：bench→发布→推送到宿主安装")
async def employee_sync_test(
    body: EmployeeSyncTestRequest,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
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
    from modstore_server.models import CatalogItem

    employee_id = (body.employee_id or "").strip()
    if not employee_id:
        raise _facade().HTTPException(400, "employee_id 不能为空")
    _facade().materialize_employee_pack_if_missing(employee_id)
    pack_dir = _facade().modstore_library_path() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        raise _facade().HTTPException(404, f"员工包不存在: {employee_id}")
    try:
        raw_mf = _facade()._load_registry_aligned_employee_manifest(pack_dir, employee_id)
    except RECOVERABLE_ERRORS as exc:
        raise _facade().HTTPException(500, f"manifest.json 读取失败: {exc}") from exc
    brief = str(raw_mf.get("description") or "").strip()[:800]
    rows = raw_mf.get("workflow_employees") or []
    panel_summary = ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
    from modstore_server.services.llm import resolve_platform_bench_llm

    prov, mdl = resolve_platform_bench_llm()
    if not prov or not mdl:
        raise _facade().HTTPException(
            503,
            "同步测试需要平台 LLM 密钥（服务端环境变量），当前未配置。请联系运维设置 MODSTORE_EMPLOYEE_BENCH_PROVIDER + MODSTORE_EMPLOYEE_BENCH_MODEL 及对应供应商的 API Key 环境变量。",
        )
    sf = _facade().get_session_factory()
    with sf() as db:
        try:
            task_list = await generate_bench_tasks(
                brief or employee_id,
                panel_summary,
                db=db,
                user_id=user.id,
                provider=prov,
                model=mdl,
                use_platform_dispatch=True,
                strict=True,
            )
        except RuntimeError as exc:
            raise _facade().HTTPException(502, f"基准任务生成失败（LLM 调用）：{exc}") from exc
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

        zip_bytes = build_employee_pack_zip_for_library(pkg_id, raw_mf, pack_dir=pack_dir)
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        raise _facade().HTTPException(500, f"员工包打包失败: {exc}") from exc
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
        align_errs = package_manifest_alignment_errors(rec, _facade().Path(tmp_path_str))
        if align_errs:
            raise _facade().HTTPException(
                400, "员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs)
            )
        saved = append_package(rec, _facade().Path(tmp_path_str))
    except RECOVERABLE_ERRORS as exc:
        _facade().Path(tmp_path_str).unlink(missing_ok=True)
        raise _facade().HTTPException(500, f"写入 catalog_store 失败: {exc}") from exc
    finally:
        _facade().Path(tmp_path_str).unlink(missing_ok=True)
    sf2 = _facade().get_session_factory()
    with sf2() as db2:
        try:
            upsert_catalog_item_from_xc_package_dict(db2, saved, author_id=user.id)
            row = db2.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
            if not row:
                row = CatalogItem(pkg_id=pkg_id, author_id=user.id)
                db2.add(row)
            row.version = saved.get("version") or version
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            db2.commit()
        except RECOVERABLE_ERRORS as exc:
            db2.rollback()
            raise _facade().HTTPException(500, f"写入数据库失败: {exc}") from exc
    fhd_base = (body.fhd_base_url or "").strip().rstrip("/")
    fhd_result: _facade().Dict[str, _facade().Any] = {
        "skipped": True,
        "reason": "未提供 fhd_base_url",
    }
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


class EmployeeSaveBody(_facade().BaseModel):
    manifest: _facade().Dict[str, _facade().Any] = _facade().Field(
        ..., description="员工完整 manifest（employee_config_v2 结构）"
    )
    employee_id: _facade().Optional[str] = _facade().Field(
        None,
        max_length=128,
        description="已有员工ID；为空时从 manifest.identity.id 读取",
    )
    provider: _facade().Optional[str] = _facade().Field(
        None,
        max_length=64,
        description="注册 vibe-coding Skill 用的 LLM 供应商（为空则尝试用户默认）",
    )
    model: _facade().Optional[str] = _facade().Field(
        None, max_length=128, description="注册 vibe-coding Skill 用的 LLM 模型"
    )
    register_skills: bool = _facade().Field(
        True, description="是否同时注册 vibe-coding ESkill（需要 LLM；失败不影响保存）"
    )
