"""管理员：将仍为 deepseek 默认厂商的员工包对齐到当前环境下可用的平台/BYOK LLM（与 resolve_llm_provider_model_auto 一致）。"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List

from fastapi import HTTPException

from modstore_server.employee_executor import list_employees
from modstore_server.employee_runtime import load_employee_pack
from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto
from modstore_server.models import CatalogItem, User, get_session_factory

logger = logging.getLogger(__name__)


async def align_catalog_employee_packs_llm_from_deepseek(
    admin_user: User,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    遍历 catalog 中的 employee_pack：若 ``employee_config_v2.cognition.agent.model.provider`` 为 ``deepseek``，
    则按登记作者（无 author 时用管理员）解析首个可用 ``provider/model``，写回 manifest 并执行与 ``employee-save`` 相同的落库流程
    （register_skills=false，避免批量触发 Skill LLM）。
    """
    from modstore_server.workbench_api import EmployeeSaveBody, employee_save_impl

    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for emp in list_employees():
        pack_id = str(emp.get("id") or "").strip()
        if not pack_id:
            continue

        sf = get_session_factory()
        with sf() as db:
            try:
                pack = load_employee_pack(db, pack_id)
            except ValueError as e:
                errors.append({"pack_id": pack_id, "error": str(e)})
                continue

            mf = pack.get("manifest")
            if not isinstance(mf, dict):
                errors.append({"pack_id": pack_id, "error": "manifest 无效"})
                continue

            v2 = (
                mf.get("employee_config_v2")
                if isinstance(mf.get("employee_config_v2"), dict)
                else {}
            )
            cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
            agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
            model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
            cur_p = str(model.get("provider") or "").strip().lower()

            if cur_p != "deepseek":
                skipped.append(
                    {
                        "pack_id": pack_id,
                        "reason": "provider 不是 deepseek",
                        "current_provider": cur_p or "(empty)",
                    }
                )
                continue

            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
            aid = int(row.author_id) if row and row.author_id else int(admin_user.id)
            eff_user = db.query(User).filter(User.id == aid).first() or admin_user

            new_p, new_m, err = await resolve_llm_provider_model_auto(db, eff_user, None, None)
            if err or not new_p or not new_m:
                errors.append({"pack_id": pack_id, "error": err or "无法解析可用 LLM"})
                continue

            old_name = str(model.get("model_name") or "").strip()

            if dry_run:
                updated.append(
                    {
                        "pack_id": pack_id,
                        "from_provider": cur_p,
                        "from_model": old_name,
                        "to_provider": new_p,
                        "to_model": new_m,
                        "acting_user_id": eff_user.id,
                        "dry_run": True,
                    }
                )
                continue

        mf2 = copy.deepcopy(mf)
        v2b = mf2.setdefault("employee_config_v2", {})
        if not isinstance(v2b, dict):
            v2b = {}
            mf2["employee_config_v2"] = v2b
        cogb = v2b.setdefault("cognition", {})
        agb = cogb.setdefault("agent", {})
        mdl = agb.setdefault("model", {})
        mdl["provider"] = new_p
        mdl["model_name"] = new_m

        body = EmployeeSaveBody(manifest=mf2, employee_id=pack_id, register_skills=False)
        try:
            await employee_save_impl(body, eff_user)
        except HTTPException as he:
            errors.append({"pack_id": pack_id, "error": he.detail or str(he)})
            continue
        except Exception as e:  # noqa: BLE001
            logger.exception("align deepseek pack=%s", pack_id)
            errors.append({"pack_id": pack_id, "error": str(e)[:500]})
            continue

        updated.append(
            {
                "pack_id": pack_id,
                "from_provider": "deepseek",
                "from_model": old_name,
                "to_provider": new_p,
                "to_model": new_m,
                "acting_user_id": eff_user.id,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


async def align_single_employee_pack_llm_to_auto(
    admin_user: User,
    pack_id: str,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把单个员工包的 LLM 绑定改为 ``provider=model_name=auto``（工作台「自动」）。

    与 :func:`align_catalog_employee_packs_llm_to_auto_sentinel` 区别：
    - 仅处理给定 ``pack_id``；
    - **不**按 provider 过滤（`deepseek` / `openai` / 已是 `auto` 的也允许覆写为 ``auto/auto``，
      让它跟随账户可解析的 BYOK / 平台密钥）；
    - 失败时返回 4xx-style ``error`` 字段，由路由转 HTTPException。
    """
    from modstore_server.workbench_api import EmployeeSaveBody, employee_save_impl

    pack_id = str(pack_id or "").strip()
    if not pack_id:
        return {"ok": False, "error": "pack_id 为空"}

    sf = get_session_factory()
    eff_user: User = admin_user
    mf: Dict[str, Any] | None = None
    cur_p: str = ""
    cur_m: str = ""

    with sf() as db:
        try:
            pack = load_employee_pack(db, pack_id)
        except ValueError as e:
            return {"ok": False, "error": str(e), "pack_id": pack_id}

        mf_raw = pack.get("manifest")
        if not isinstance(mf_raw, dict):
            return {"ok": False, "error": "manifest 无效", "pack_id": pack_id}

        v2 = (
            mf_raw.get("employee_config_v2")
            if isinstance(mf_raw.get("employee_config_v2"), dict)
            else {}
        )
        cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
        agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
        model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
        cur_p = str(model.get("provider") or "").strip().lower()
        cur_m = str(model.get("model_name") or "").strip()

        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        aid = int(row.author_id) if row and row.author_id else int(admin_user.id)
        eff_user = db.query(User).filter(User.id == aid).first() or admin_user

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "pack_id": pack_id,
                "from_provider": cur_p or "(empty)",
                "from_model": cur_m,
                "to_provider": "auto",
                "to_model": "auto",
                "acting_user_id": eff_user.id,
                "already_auto": cur_p == "auto" and cur_m == "auto",
            }

        mf = mf_raw

    assert mf is not None
    mf2 = copy.deepcopy(mf)
    v2b = mf2.setdefault("employee_config_v2", {})
    if not isinstance(v2b, dict):
        v2b = {}
        mf2["employee_config_v2"] = v2b
    cogb = v2b.setdefault("cognition", {})
    agb = cogb.setdefault("agent", {})
    mdl = agb.setdefault("model", {})
    mdl["provider"] = "auto"
    mdl["model_name"] = "auto"

    body = EmployeeSaveBody(manifest=mf2, employee_id=pack_id, register_skills=False)
    try:
        await employee_save_impl(body, eff_user)
    except HTTPException as he:
        return {"ok": False, "error": he.detail or str(he), "pack_id": pack_id}
    except Exception as e:  # noqa: BLE001
        logger.exception("align single auto sentinel pack=%s", pack_id)
        return {"ok": False, "error": str(e)[:500], "pack_id": pack_id}

    return {
        "ok": True,
        "dry_run": False,
        "pack_id": pack_id,
        "from_provider": cur_p or "(empty)",
        "from_model": cur_m,
        "to_provider": "auto",
        "to_model": "auto",
        "acting_user_id": eff_user.id,
        "already_auto": cur_p == "auto" and cur_m == "auto",
    }


async def align_catalog_employee_packs_llm_to_auto_sentinel(
    admin_user: User,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    将仍为 ``provider=deepseek`` 的员工包改为清单内的 ``provider=model_name=auto``（工作台「自动」），
    执行与 ``employee-save`` 相同的落库流程（register_skills=false）。
    """
    from modstore_server.workbench_api import EmployeeSaveBody, employee_save_impl

    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for emp in list_employees():
        pack_id = str(emp.get("id") or "").strip()
        if not pack_id:
            continue

        sf = get_session_factory()
        mf: Dict[str, Any] | None = None
        eff_user = admin_user

        with sf() as db:
            try:
                pack = load_employee_pack(db, pack_id)
            except ValueError as e:
                errors.append({"pack_id": pack_id, "error": str(e)})
                continue

            mf_raw = pack.get("manifest")
            if not isinstance(mf_raw, dict):
                errors.append({"pack_id": pack_id, "error": "manifest 无效"})
                continue

            v2 = (
                mf_raw.get("employee_config_v2")
                if isinstance(mf_raw.get("employee_config_v2"), dict)
                else {}
            )
            cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
            agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
            model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
            cur_p = str(model.get("provider") or "").strip().lower()

            if cur_p != "deepseek":
                skipped.append(
                    {
                        "pack_id": pack_id,
                        "reason": "provider 不是 deepseek",
                        "current_provider": cur_p or "(empty)",
                    }
                )
                continue

            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
            aid = int(row.author_id) if row and row.author_id else int(admin_user.id)
            eff_user = db.query(User).filter(User.id == aid).first() or admin_user
            old_name = str(model.get("model_name") or "").strip()

            if dry_run:
                updated.append(
                    {
                        "pack_id": pack_id,
                        "from_provider": cur_p,
                        "from_model": old_name,
                        "to_provider": "auto",
                        "to_model": "auto",
                        "acting_user_id": eff_user.id,
                        "dry_run": True,
                    }
                )
                continue

            mf = mf_raw

        assert mf is not None
        mf2 = copy.deepcopy(mf)
        v2b = mf2.setdefault("employee_config_v2", {})
        if not isinstance(v2b, dict):
            v2b = {}
            mf2["employee_config_v2"] = v2b
        cogb = v2b.setdefault("cognition", {})
        agb = cogb.setdefault("agent", {})
        mdl = agb.setdefault("model", {})
        mdl["provider"] = "auto"
        mdl["model_name"] = "auto"

        body = EmployeeSaveBody(manifest=mf2, employee_id=pack_id, register_skills=False)
        try:
            await employee_save_impl(body, eff_user)
        except HTTPException as he:
            errors.append({"pack_id": pack_id, "error": he.detail or str(he)})
            continue
        except Exception as e:  # noqa: BLE001
            logger.exception("align auto sentinel pack=%s", pack_id)
            errors.append({"pack_id": pack_id, "error": str(e)[:500]})
            continue

        updated.append(
            {
                "pack_id": pack_id,
                "from_provider": "deepseek",
                "from_model": old_name,
                "to_provider": "auto",
                "to_model": "auto",
                "acting_user_id": eff_user.id,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
