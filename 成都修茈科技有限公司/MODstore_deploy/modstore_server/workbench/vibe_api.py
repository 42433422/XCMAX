"""Vibe api for workbench delivery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, cast

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.catalog import store_catalog_row
from modstore_server.workbench.schemas import WorkbenchVibeCodeSkillBody

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class VibePorts:
    database: Callable[[], Callable[[], Session]]
    publish: Callable[..., dict[str, Any]]


async def workbench_vibe_code_skill(
    body: WorkbenchVibeCodeSkillBody,
    user: User = Depends(_get_current_user),
    *,
    ports: VibePorts,
):
    """vibe-coding 端到端 API:生成代码、试跑、可选直接上架本 MODstore。

    本接口同步返回(单次代码生成大约 5-30 秒,取决于 LLM 速度);
    长时间任务请用「脚本工作流」。
    """
    from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto

    sf = ports.database()
    with sf() as db:
        prov, mdl, err = await resolve_llm_provider_model_auto(
            db, user, body.provider, body.model
        )
        if err:
            raise HTTPException(400, err)

    def _do() -> Dict[str, Any]:
        try:
            from modstore_server.integrations.vibe_adapter import (
                VibeIntegrationError,
                VibePathError,
                ensure_within_workspace,
                get_vibe_coder,
            )
        except ImportError as exc:
            return {"ok": False, "error": f"未启用 vibe-coding 集成: {exc}"}
        resolved_project_root: Optional[str] = None
        if body.project_root and body.project_root.strip():
            try:
                resolved_project_root = str(
                    ensure_within_workspace(
                        body.project_root.strip(), user_id=int(cast(int, user.id) or 0)
                    )
                )
            except VibePathError as exc:
                return {"ok": False, "error": f"project_root 路径无效: {exc}"}
            except RECOVERABLE_ERRORS as exc:
                return {"ok": False, "error": f"project_root 校验失败: {exc}"}
        sf2 = ports.database()
        with sf2() as session:
            try:
                coder = get_vibe_coder(
                    session=session,
                    user_id=int(cast(int, user.id) or 0),
                    provider=prov,
                    model=mdl,
                )
            except VibeIntegrationError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                skill = coder.code(
                    body.brief.strip(),
                    mode=body.mode,
                    skill_id=body.skill_id or None,
                    project_root=resolved_project_root,
                )
            except RECOVERABLE_ERRORS as exc:
                return {"ok": False, "error": f"vibe-coding 生成失败: {exc}"}
            run_input_final = dict(body.run_input or {})
            if resolved_project_root and "project_analysis" not in run_input_final:
                try:
                    import json as _json

                    from vibe_coding.code_factory import analyze_project

                    analysis = analyze_project(resolved_project_root)
                    run_input_final["project_analysis"] = _json.loads(
                        _json.dumps(
                            {
                                "root_name": analysis.root_name,
                                "manifests": analysis.manifests,
                                "top_level": analysis.top_level,
                                "languages": analysis.languages,
                                "tech_stack": analysis.tech_stack,
                                "entry_points": analysis.entry_points,
                                "config_files": analysis.config_files,
                                "readme_snippet": analysis.readme_snippet,
                                "git_info": analysis.git_info,
                            },
                            ensure_ascii=False,
                        )
                    )
                except RECOVERABLE_ERRORS:
                    pass
            sid = getattr(skill, "skill_id", "") or ""
            run_dict: Optional[Dict[str, Any]] = None
            try:
                run_obj = coder.run(sid, run_input_final)
                run_dict = (
                    run_obj.to_dict()
                    if hasattr(run_obj, "to_dict") and callable(run_obj.to_dict)
                    else {"output": getattr(run_obj, "output", None)}
                )
            except RECOVERABLE_ERRORS as exc:
                run_dict = {"ok": False, "error": f"试跑失败: {exc}"}
            skill_dict: Dict[str, Any]
            if hasattr(skill, "to_dict") and callable(skill.to_dict):
                skill_dict = dict(skill.to_dict())
            else:
                skill_dict = {"skill_id": sid, "code": getattr(skill, "code", "") or ""}
            publish_dict: Optional[Dict[str, Any]] = None
            if body.publish and (not body.dry_run):
                publish_dict = ports.publish(
                    coder, sid, body.publish, user_id=int(cast(int, user.id) or 0)
                )
            return {
                "ok": True,
                "provider": prov,
                "model": mdl,
                "skill": skill_dict,
                "run": run_dict,
                "publish": publish_dict,
                "project_root_used": resolved_project_root,
            }

    out = await asyncio.to_thread(_do)
    return out


def _publish_vibe_skill_via_local_modstore(
    coder: Any,
    skill_id: str,
    publish_cfg: Dict[str, Any],
    *,
    user_id: int,
    ports: VibePorts,
) -> Dict[str, Any]:
    """直接调本 MODstore 的 catalog 上传接口,不用 HTTP 自调来回。

    用 vibe-coding 的 ``SkillPackager`` 打包(它知道 .xcmod 内部结构),
    再走 :func:`catalog_store.append_package` + ``CatalogItem`` 写库。
    """
    try:
        from vibe_coding.agent.marketplace import PublishOptions, SkillPackager
    except ImportError as exc:
        return {"ok": False, "error": f"vibe-coding marketplace 未安装: {exc}"}
    pkg_id = str(publish_cfg.get("pkg_id") or "").strip()
    if not pkg_id:
        return {"ok": False, "error": "publish.pkg_id 必填"}
    artifact_kind = str(publish_cfg.get("artifact") or "mod").strip() or "mod"
    if artifact_kind not in ("mod", "employee_pack"):
        return {"ok": False, "error": f"不支持的 artifact: {artifact_kind}"}
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    risk_decision = evaluate_risk(
        "mod_auto_publish",
        {
            "human_approved": True,
            "approved_by": f"workbench-user:{user_id}",
            "trigger": "explicit_workbench_publish",
        },
        action_id=f"mod-publish:{user_id}:{pkg_id}:{str(publish_cfg.get('version') or '1.0.0')}",
        source="workbench.vibe_code_publish",
    )
    if not risk_decision.allowed:
        return {
            "ok": False,
            "error": "autonomy_guard blocked publish",
            "risk_decision": risk_decision.to_dict(),
        }
    try:
        skill = coder.code_store.get_code_skill(skill_id)
    except KeyError:
        return {"ok": False, "error": f"skill_id 不存在: {skill_id}"}
    options = PublishOptions(
        pkg_id=pkg_id,
        version=str(publish_cfg.get("version") or "1.0.0"),
        name=str(publish_cfg.get("name") or pkg_id),
        description=str(publish_cfg.get("description") or ""),
        price=float(publish_cfg.get("price") or 0.0),
        artifact=artifact_kind,
        industry=str(publish_cfg.get("industry") or "通用"),
        author=f"user-{user_id}",
    )
    try:
        packager = SkillPackager()
        artifact = packager.package_skill(skill, options=options)
    except RECOVERABLE_ERRORS as exc:
        return {"ok": False, "error": f"打包失败: {exc}"}
    try:
        from modstore_server.catalog_store import append_package

        rec = {
            "id": pkg_id,
            "name": options.name,
            "version": options.version,
            "description": options.description,
            "artifact": artifact_kind,
            "industry": options.industry,
            "release_channel": "stable",
            "commerce": {
                "mode": "free" if options.price <= 0 else "paid",
                "price": options.price,
            },
            "license": {"type": "personal", "verify_url": None},
        }
        sf3 = ports.database()
        with sf3() as session:
            saved = append_package(rec, Path(artifact.archive_path))
            row = store_catalog_row(
                session,
                pack_id=pkg_id,
                author_id=user_id,
                saved=saved,
                metadata=rec,
                price=float(options.price),
                artifact=artifact_kind,
            )
            session.commit()
            if artifact_kind == "employee_pack":
                try:
                    from modstore_server.employee_asset_pipeline import (
                        mirror_catalog_file_to_market_files,
                    )

                    mirror_catalog_file_to_market_files(row.stored_filename)
                except RECOVERABLE_ERRORS:
                    pass
    except RECOVERABLE_ERRORS as exc:
        return {
            "ok": False,
            "error": f"上架到本地 MODstore 失败: {exc}",
            "artifact": getattr(artifact, "to_dict", lambda: {})(),
        }
    return {
        "ok": True,
        "pkg_id": pkg_id,
        "version": options.version,
        "artifact": getattr(artifact, "to_dict", lambda: {})(),
    }
