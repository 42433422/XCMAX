"""Intent for workbench delivery."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, overload

CANVAS_SKILL_INTENT = "skill"
_LOG = logging.getLogger("modstore_server.workbench_api")


def _contains_uploaded_docx(raw_files: Any) -> bool:
    """Return whether the normalized upload payload contains a Word document."""
    if not isinstance(raw_files, (list, tuple)):
        return False
    for item in raw_files:
        if isinstance(item, dict):
            filename = item.get("filename") or item.get("name") or ""
        else:
            filename = getattr(item, "filename", "") or getattr(item, "name", "")
        if str(filename).strip().lower().endswith(".docx"):
            return True
    return False


def _canonical_workbench_intent(intent: Optional[str]) -> str:
    s = (intent or "").strip().lower()
    if s == "workflow":
        return CANVAS_SKILL_INTENT
    return s


def _employee_asset_publish_catalog_from_env() -> bool:
    """资产驱动「做员工」是否在生成后写入 ``packages.json`` + ``catalog_items``（默认否，以保持既有测试）。

    部署可设 ``MODSTORE_EMPLOYEE_ASSET_PUBLISH_CATALOG=1``，生成即登记，避免 ``/manifest`` 404。
    """
    return (os.environ.get("MODSTORE_EMPLOYEE_ASSET_PUBLISH_CATALOG") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@overload
def _enrich_artifact_skill_aliases(artifact: dict[str, Any]) -> dict[str, Any]: ...


@overload
def _enrich_artifact_skill_aliases(artifact: None) -> None: ...


def _enrich_artifact_skill_aliases(artifact: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not artifact or not isinstance(artifact, dict):
        return artifact
    out = dict(artifact)
    wid = out.get("workflow_id")
    if wid is not None:
        out.setdefault("skill_group_id", wid)
    wn = out.get("workflow_name")
    if wn is not None:
        out.setdefault("skill_group_name", wn)
    return out


def _default_steps(
    intent: str, execution_mode: str = "workflow", *, employee_target: str = "pack_only"
) -> List[Dict[str, Any]]:
    intent = _canonical_workbench_intent(intent)
    if execution_mode == "script":
        return [
            {"id": "spec", "label": "理解任务", "status": "pending", "message": None},
            {"id": "generate", "label": "生成处理脚本", "status": "pending", "message": None},
            {"id": "validate", "label": "安全检查", "status": "pending", "message": None},
            {"id": "run", "label": "运行并生成文件", "status": "pending", "message": None},
            {"id": "complete", "label": "完成", "status": "pending", "message": None},
        ]
    if intent == "mod":
        return [
            {"id": "spec", "label": "理解需求", "status": "pending", "message": None},
            {"id": "manifest", "label": "生成蓝图与 JSON", "status": "pending", "message": None},
            {"id": "repo", "label": "新建 Mod 仓库", "status": "pending", "message": None},
            {"id": "industry", "label": "生成行业卡片", "status": "pending", "message": None},
            {"id": "employees", "label": "创建员工骨架", "status": "pending", "message": None},
            {"id": "employee_impls", "label": "生成员工脚本", "status": "pending", "message": None},
            {
                "id": "workflows",
                "label": "生成员工 Skill 组（画布编排）",
                "status": "pending",
                "message": None,
            },
            {
                "id": "register_packs",
                "label": "登记员工包并修复图",
                "status": "pending",
                "message": None,
            },
            {"id": "api", "label": "生成/绑定 API 节点", "status": "pending", "message": None},
            {
                "id": "workflow_sandbox",
                "label": "工作流沙箱测试",
                "status": "pending",
                "message": None,
            },
            {"id": "mod_sandbox", "label": "Mod 沙箱测试", "status": "pending", "message": None},
            {"id": "complete", "label": "完成", "status": "pending", "message": None},
        ]
    base = [
        {"id": "spec", "label": "理解需求", "status": "pending", "message": None},
        {"id": "generate", "label": "生成产物", "status": "pending", "message": None},
        {"id": "validate", "label": "服务端校验", "status": "pending", "message": None},
    ]
    if intent == "employee":
        base.insert(
            1,
            {
                "id": "employee_plan",
                "label": "规划一站式员工",
                "status": "pending",
                "message": None,
            },
        )
        base.extend(
            [
                {
                    "id": "script_workflow",
                    "label": "生成配套小程序",
                    "status": "pending",
                    "message": None,
                },
                {"id": "embed_script", "label": "绑定到员工", "status": "pending", "message": None},
            ]
        )
        if (employee_target or "").strip().lower() == "pack_plus_workflow":
            base.extend(
                [
                    {
                        "id": "workflow",
                        "label": "生成自动化流程",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "register_pack",
                        "label": "登记员工包",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "workflow_sandbox",
                        "label": "流程沙箱测试",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "mod_sandbox",
                        "label": "包体与 Python 校验",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "standalone_smoke",
                        "label": "独立可执行自检",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "host_check",
                        "label": "宿主连通性检查",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "six_dim_gate",
                        "label": "六维质量评估",
                        "status": "pending",
                        "message": None,
                    },
                ]
            )
        else:
            base.extend(
                [
                    {
                        "id": "workflow",
                        "label": "生成自动化流程",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "register_pack",
                        "label": "登记员工包",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "workflow_sandbox",
                        "label": "流程沙箱测试",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "mod_sandbox",
                        "label": "包体与 Python 校验",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "standalone_smoke",
                        "label": "独立可执行自检",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "host_check",
                        "label": "宿主连通性检查",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "six_dim_gate",
                        "label": "六维质量评估",
                        "status": "pending",
                        "message": None,
                    },
                ]
            )
    base.append({"id": "complete", "label": "完成", "status": "pending", "message": None})
    if intent == CANVAS_SKILL_INTENT:
        base[1]["label"] = "创建 Skill 组"
    return base
