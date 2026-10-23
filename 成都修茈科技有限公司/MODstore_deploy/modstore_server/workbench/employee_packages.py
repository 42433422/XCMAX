"""Employee packages for workbench delivery."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, cast

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.catalog import _write_workflow_reference_report, store_catalog_row
from modstore_server.workbench.schemas import EmployeeExportBody, EmployeeSaveBody

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeePackagePorts:
    database: Callable[[], Callable[[], Session]]
    library: Callable[[], Path]
    build_archive: Callable[..., bytes]
    normalize_manifest: Callable[..., tuple[dict[str, Any], list[str]]]


async def employee_save_impl(
    body: EmployeeSaveBody, user: User, *, ports: EmployeePackagePorts
) -> Dict[str, Any]:
    """employee_save 核心实现；管理员批量对齐 manifest 时可复用（传入登记作者 user）。"""
    import re as _re
    import tempfile as _tmp
    import zipfile as _zipfile

    from modstore_server.catalog_store import append_package, package_manifest_alignment_errors
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict

    mf = body.manifest
    if not isinstance(mf, dict):
        raise HTTPException(400, "manifest 必须是 JSON 对象")
    raw_id = (
        (body.employee_id or "").strip()
        or str((mf.get("identity") or {}).get("id") or "").strip()
        or str(mf.get("id") or "").strip()
    )
    if not raw_id:
        raise HTTPException(400, "manifest 中缺少 identity.id 或顶层 id 字段")
    pack_id = _re.sub("[^a-z0-9._-]", "-", raw_id.lower()).strip("-")[:48]
    if not pack_id:
        raise HTTPException(400, f"无法从 employee_id/manifest.id 生成合法 pack_id: {raw_id!r}")
    mf["id"] = mf.get("id") or pack_id
    mf, registry_errs = ports.normalize_manifest(mf, pack_id)
    if registry_errs:
        _LOG.info("employee_save: manifest 校验警告 pack=%s: %s", pack_id, registry_errs)
    ref_warnings: List[str] = []
    sf_ref = ports.database()
    with sf_ref() as db_ref:
        try:
            from modstore_server.employee_pack_workflow_bundle import (
                embed_workflow_bundles_in_manifest,
            )

            embed_workflow_bundles_in_manifest(db_ref, mf)
        except RECOVERABLE_ERRORS as _bundle_exc:
            _LOG.warning("employee_save: embed bundles failed pack=%s: %s", pack_id, _bundle_exc)
            ref_warnings = _write_workflow_reference_report(db_ref, user, mf)
    from modman.artifact_constants import normalize_artifact

    if normalize_artifact(mf) != "employee_pack":
        raise HTTPException(
            400, f"manifest 规范化后 artifact 仍无效；校验详情: {'; '.join(registry_errs)}"
        )
    from modstore_server.employee_asset_pipeline import (
        DIRECT_PYTHON_RUNTIME_MISSING_MSG,
        build_employee_pack_zip_for_library,
        manifest_actions_handlers,
        manifest_expects_word_runtime,
        pack_has_direct_python_runtime,
        persist_manifest_to_pack_dir,
    )

    lib = ports.library()
    pack_dir = lib / pack_id
    _brief_for_pack = str(
        mf.get("description") or (mf.get("identity") or {}).get("description") or ""
    ).strip()
    _wants_word = manifest_expects_word_runtime(mf, brief=_brief_for_pack)
    _has_runtime = pack_dir.is_dir() and pack_has_direct_python_runtime(pack_dir)
    if _wants_word and "direct_python" in manifest_actions_handlers(mf) and (not _has_runtime):
        raise HTTPException(400, DIRECT_PYTHON_RUNTIME_MISSING_MSG)
    try:
        mf = persist_manifest_to_pack_dir(pack_dir, mf, brief=_brief_for_pack)
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"manifest 落盘失败: {exc}") from exc
    if not _has_runtime:
        try:
            zip_bytes = ports.build_archive(pack_id, mf)
        except RECOVERABLE_ERRORS as exc:
            raise HTTPException(500, f"员工包打包失败: {exc}") from exc
        try:
            with _tmp.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
                tmp.write(zip_bytes)
                tmp_zip_path = Path(tmp.name)
            pack_dir.mkdir(parents=True, exist_ok=True)
            with _zipfile.ZipFile(tmp_zip_path, "r") as zf:
                for member in zf.namelist():
                    parts = member.split("/", 1)
                    if len(parts) == 2 and parts[1]:
                        dest = pack_dir / Path(parts[1])
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if not member.endswith("/"):
                            dest.write_bytes(zf.read(member))
        except RECOVERABLE_ERRORS as exc:
            _LOG.warning("employee_save: zip 解压失败 pack=%s: %s", pack_id, exc)
        finally:
            try:
                tmp_zip_path.unlink(missing_ok=True)
            except RECOVERABLE_ERRORS:
                pass
    try:
        from modstore_server.mod_scaffold_runner import rehydrate_employee_pack_bundles

        sf_rh = ports.database()
        with sf_rh() as db_rh:
            rehydrate_employee_pack_bundles(pack_id, db=db_rh, user=user)
            mf_path_rh = pack_dir / "manifest.json"
            if mf_path_rh.is_file():
                mf = json.loads(mf_path_rh.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS as _rh_exc:
        _LOG.warning("employee_save: rehydrate bundles failed pack=%s: %s", pack_id, _rh_exc)
    eskill_result: Dict[str, Any] = {"registered": 0, "skipped": False, "error": ""}
    if body.register_skills:
        try:
            from modstore_server.employee_skill_register import register_employee_pack_as_eskills
            from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto

            sf_reg = ports.database()
            with sf_reg() as db_reg:
                prov, mdl, perr = await resolve_llm_provider_model_auto(
                    db_reg, user, body.provider, body.model
                )
            if perr:
                eskill_result["skipped"] = True
                eskill_result["error"] = f"LLM 解析失败（跳过 Skill 注册）: {perr}"
            else:
                brief = str(
                    mf.get("description")
                    or (mf.get("identity") or {}).get("description")
                    or mf.get("name")
                    or pack_id
                )
                panel_summary = ""
                wf_rows = mf.get("workflow_employees") or []
                if isinstance(wf_rows, list) and wf_rows and isinstance(wf_rows[0], dict):
                    panel_summary = str(wf_rows[0].get("panel_summary") or "")
                sf_sk = ports.database()
                with sf_sk() as db_sk:
                    specs = await register_employee_pack_as_eskills(
                        db_sk,
                        user,
                        pack_dir=pack_dir,
                        brief=brief,
                        panel_summary=panel_summary,
                        provider=prov,
                        model=mdl,
                    )
                eskill_result["registered"] = len(specs)
                if specs:
                    v2 = (
                        cast(dict[str, Any], mf.get("employee_config_v2"))
                        if isinstance(mf.get("employee_config_v2"), dict)
                        else {}
                    )
                    cog = (
                        cast(dict[str, Any], v2.get("cognition"))
                        if isinstance(v2.get("cognition"), dict)
                        else {}
                    )
                    existing_skills = (
                        cast(list[Any], cog.get("skills"))
                        if isinstance(cog.get("skills"), list)
                        else []
                    )
                    name_to_spec = {s["name"]: s for s in specs}
                    updated = []
                    for sk in existing_skills:
                        sk_dict = dict(sk) if isinstance(sk, dict) else {}
                        matched = name_to_spec.get(sk_dict.get("name") or "")
                        if matched:
                            sk_dict["eskill_id"] = matched["eskill_id"]
                            sk_dict["vibe_skill_id"] = matched.get("vibe_skill_id") or ""
                        updated.append(sk_dict)
                    existing_names = {s.get("name") or "" for s in updated}
                    for spec in specs:
                        if spec["name"] not in existing_names:
                            updated.append(
                                {
                                    "name": spec["name"],
                                    "brief": spec.get("output_var") or spec["name"],
                                    "eskill_id": spec["eskill_id"],
                                    "vibe_skill_id": spec.get("vibe_skill_id") or "",
                                }
                            )
                    cog["skills"] = updated
                    v2["cognition"] = cog
                    mf["employee_config_v2"] = v2
                    mf_path = pack_dir / "manifest.json"
                    mf_path.write_text(
                        json.dumps(mf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
        except RECOVERABLE_ERRORS as exc:
            _LOG.warning("employee_save: Skill registration failed; saving continues")
            eskill_result["skipped"] = True
            eskill_result["error"] = str(exc)[:400]
    try:
        zip_bytes = build_employee_pack_zip_for_library(
            pack_id, mf, pack_dir=pack_dir, brief=_brief_for_pack
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"员工包打包失败: {exc}") from exc
    version = str(mf.get("version") or (mf.get("identity") or {}).get("version") or "1.0.0").strip()
    name = str(mf.get("name") or (mf.get("identity") or {}).get("name") or pack_id).strip()
    rec = {
        "id": pack_id,
        "name": name,
        "version": version,
        "description": str(
            mf.get("description") or (mf.get("identity") or {}).get("description") or ""
        ),
        "artifact": "employee_pack",
        "industry": str(mf.get("industry") or (mf.get("commerce") or {}).get("industry") or "通用"),
        "release_channel": "stable",
        "commerce": mf.get("commerce") or {"mode": "free", "price": 0},
        "license": {"type": "personal", "verify_url": None},
    }
    with _tmp.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
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
            upsert_catalog_item_from_xc_package_dict(db, saved, author_id=cast(int, user.id))
            store_catalog_row(
                db,
                pack_id=pack_id,
                author_id=cast(int, user.id),
                saved=saved,
                metadata=rec,
                price=0.0,
                artifact="employee_pack",
            )
            db.commit()
        except RECOVERABLE_ERRORS as exc:
            db.rollback()
            raise HTTPException(500, f"写入数据库失败: {exc}") from exc
    try:
        from modstore_server.employee_api import sync_triggers_after_registration

        sync_triggers_after_registration(mf)
    except RECOVERABLE_ERRORS:
        _LOG.warning("employee_save: sync triggers failed")
    return {
        "ok": True,
        "pack_id": pack_id,
        "version": version,
        "name": name,
        "stored_filename": saved.get("stored_filename") or "",
        "eskill_registered": eskill_result["registered"],
        "eskill_skipped": eskill_result["skipped"],
        "eskill_error": eskill_result["error"],
        "manifest": mf,
        "manifest_warnings": (registry_errs if registry_errs else []) + ref_warnings,
    }


async def employee_export(
    body: EmployeeExportBody,
    user: User = Depends(_get_current_user),
    *,
    ports: EmployeePackagePorts,
):
    """接收前端当前 manifest，用后端模板生成完整 .xcemp（含 blueprints.py + employee.py），直接返回 zip 流。
    ``standalone=true`` 时额外嵌入 zipapp 入口（与 employee_pack_export._build_employee_pack_zip_with_source 一致），
    便于本机 ``python xxx.xcemp validate`` / ``run``；平台装载仍只读 ``<pack_id>/manifest.json`` 与 ``backend/``。
    不写入数据库，仅供本地查看/调试用。
    """
    import re as _re

    mf = body.manifest
    if not isinstance(mf, dict):
        raise HTTPException(400, "manifest 必须是 JSON 对象")
    raw_id = (
        (body.employee_id or "").strip()
        or str((mf.get("identity") or {}).get("id") or "").strip()
        or str(mf.get("id") or "").strip()
    )
    if not raw_id:
        raise HTTPException(400, "manifest 中缺少 identity.id 或顶层 id 字段")
    pack_id = _re.sub("[^a-z0-9._-]", "-", raw_id.lower()).strip("-")[:48] or "employee"
    mf["id"] = mf.get("id") or pack_id
    mf, registry_errs = ports.normalize_manifest(mf, pack_id)
    if registry_errs:
        _LOG.info("employee_export: manifest validation warnings count=%s", len(registry_errs))
    ref_warnings: List[str] = []
    sf_ref = ports.database()
    with sf_ref() as db_ref:
        try:
            from modstore_server.employee_pack_workflow_bundle import (
                embed_workflow_bundles_in_manifest,
            )

            embed_workflow_bundles_in_manifest(db_ref, mf)
        except RECOVERABLE_ERRORS as _bundle_exc:
            _LOG.warning("employee_export: workflow bundles could not be embedded")
            ref_warnings = _write_workflow_reference_report(db_ref, user, mf)
    from modstore_server.employee_asset_pipeline import (
        DIRECT_PYTHON_RUNTIME_MISSING_MSG,
        build_employee_pack_zip_for_library,
        manifest_actions_handlers,
        manifest_expects_word_runtime,
        pack_has_direct_python_runtime,
    )
    from modstore_server.mod_scaffold_runner import modstore_library_path

    _export_brief = str(
        mf.get("description") or (mf.get("identity") or {}).get("description") or ""
    ).strip()
    _lib_pack = modstore_library_path() / pack_id
    if (
        manifest_expects_word_runtime(mf, brief=_export_brief)
        and "direct_python" in manifest_actions_handlers(mf)
        and (not (_lib_pack.is_dir() and pack_has_direct_python_runtime(_lib_pack)))
    ):
        raise HTTPException(400, DIRECT_PYTHON_RUNTIME_MISSING_MSG)
    try:
        if body.standalone:
            from modstore_server.employee_pack_export import _build_employee_pack_zip_with_source

            zip_bytes = _build_employee_pack_zip_with_source(pack_id, mf, None)
        else:
            zip_bytes = build_employee_pack_zip_for_library(
                pack_id, mf, pack_dir=_lib_pack if _lib_pack.is_dir() else None, brief=_export_brief
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(500, f"员工包打包失败: {exc}") from exc
    dl_name = f"{pack_id}-standalone.xcemp" if body.standalone else f"{pack_id}.xcemp"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{dl_name}"',
            "X-Manifest-Warnings": (
                "; ".join((registry_errs + ref_warnings)[:5])
                if registry_errs or ref_warnings
                else ""
            ),
        },
    )
