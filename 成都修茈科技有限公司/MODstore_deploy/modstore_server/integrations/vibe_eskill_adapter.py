"""把 vibe-coding 暴露成 ESkill 的 logic kind。

注册流程:
- :mod:`modstore_server.eskill_runtime` 在 ``_execute_logic`` 里识别
  ``logic.type in ("vibe_code", "vibe_workflow")`` 时,委派到本模块。
- 与原 ``employee_task`` 语义对齐:本模块负责把 ``logic`` + ``input_data``
  转成 vibe-coding 的调用参数,并把返回拍平成 ESkill 期望的 dict。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from modstore_server.models import get_session_factory

logger = logging.getLogger(__name__)


def _resolve_provider_model(logic: Dict[str, Any], user_id: int) -> Dict[str, str]:
    prov = str(logic.get("provider") or "").strip()
    mdl = str(logic.get("model") or "").strip()
    if prov and mdl:
        return {"provider": prov, "model": mdl}
    try:
        from modstore_server.integrations.vibe_action_handlers import (
            _safe_resolve_provider_model,
        )

        return _safe_resolve_provider_model(int(user_id or 0), prov, mdl)
    except Exception:  # pragma: no cover
        logger.exception("vibe_eskill_adapter 解析 provider/model 失败")
        return {"provider": prov, "model": mdl}


def _render_brief(logic: Dict[str, Any], input_data: Dict[str, Any]) -> str:
    """允许 brief 模板里用 ``{{key}}`` 引用 input_data 字段。"""
    raw = str(logic.get("brief") or logic.get("brief_template") or "").strip()
    if not raw:
        # 没有 brief 时把 input_data 作为 brief 主体,模型自行解读。
        import json as _json

        return _json.dumps(input_data or {}, ensure_ascii=False)[:4000]
    rendered = raw
    for k, v in (input_data or {}).items():
        token = "{{" + str(k) + "}}"
        if token in rendered:
            rendered = rendered.replace(token, str(v))
    return rendered


def _resolve_project_root(logic: Dict[str, Any], user_id: int) -> Optional[str]:
    """Validate ``logic.project_root`` against the user workspace.

    Returns the resolved absolute path string, or ``None`` when not supplied.
    Raises :class:`~modstore_server.integrations.vibe_adapter.VibePathError`
    when the path is outside the tenant workspace.
    """
    raw = str(logic.get("project_root") or "").strip()
    if not raw:
        return None
    try:
        from modstore_server.integrations.vibe_adapter import ensure_within_workspace

        validated = ensure_within_workspace(raw, user_id=int(user_id or 0))
        return str(validated)
    except Exception:  # VibePathError or any OS error — re-raise so caller can surface it
        raise


def execute_vibe_code_kind(
    logic: Dict[str, Any],
    input_data: Dict[str, Any],
    *,
    user_id: int,
) -> Dict[str, Any]:
    """``logic.type == "vibe_code"``: NL → 单 :class:`CodeSkill`,可选立即 run。

    logic 字段:
        brief / brief_template: str   必填
        skill_id: str                 可选;已有则复用
        provider/model: str           可选;默认走 user 偏好
        run_immediately: bool         默认 True;为 False 则只返回生成的代码摘要
        run_input_mapping: dict       可选,把 input_data 抽子集喂给 run(skill, ...)
        project_root: str             可选;合法工作区路径;用于项目分析/文档生成 Skill
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            VibePathError,
            get_vibe_coder,
        )
    except ImportError as exc:  # pragma: no cover
        return {
            "eskill_logic_type": "vibe_code",
            "ok": False,
            "error": f"integrations 未导入: {exc}",
        }

    pm = _resolve_provider_model(logic, int(user_id or 0))
    if not pm["provider"] or not pm["model"]:
        return {
            "eskill_logic_type": "vibe_code",
            "ok": False,
            "error": "缺少 provider/model",
        }

    # Validate and resolve project_root (workspace-bounded path check).
    project_root: Optional[str] = None
    try:
        project_root = _resolve_project_root(logic, int(user_id or 0))
    except Exception as exc:  # noqa: BLE001
        return {
            "eskill_logic_type": "vibe_code",
            "ok": False,
            "error": f"project_root 路径无效: {exc}",
        }

    brief = _render_brief(logic, input_data)
    skill_id_hint = logic.get("skill_id") or None
    mode = str(logic.get("mode") or "brief_first")
    run_immediately = bool(logic.get("run_immediately", True))
    run_mapping = logic.get("run_input_mapping")
    if isinstance(run_mapping, dict) and run_mapping:
        run_input: Dict[str, Any] = {
            str(k): (input_data or {}).get(str(v), v) for k, v in run_mapping.items()
        }
    else:
        run_input = dict(input_data or {})

    # Inject pre-computed project analysis into run_input so the generated
    # Skill can access it as project_analysis without hitting the filesystem.
    if project_root and "project_analysis" not in run_input:
        try:
            from vibe_coding.code_factory import analyze_project  # type: ignore[import-not-found]

            analysis = analyze_project(project_root)
            import json as _json

            run_input["project_analysis"] = _json.loads(
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
        except Exception:  # noqa: BLE001 — analysis is optional, never block execution
            logger.warning("vibe_code: project_root 分析失败，已跳过", exc_info=True)

    sf = get_session_factory()
    try:
        with sf() as session:
            try:
                coder = get_vibe_coder(
                    session=session,
                    user_id=int(user_id or 0),
                    provider=pm["provider"],
                    model=pm["model"],
                )
            except VibeIntegrationError as exc:
                return {
                    "eskill_logic_type": "vibe_code",
                    "ok": False,
                    "error": str(exc),
                }
            skill = None
            if skill_id_hint and getattr(coder, "code_store", None) is not None:
                try:
                    if coder.code_store.has_code_skill(str(skill_id_hint)):
                        skill = coder.code_store.get_code_skill(str(skill_id_hint))
                except Exception:  # noqa: BLE001
                    skill = None
            if skill is None:
                skill = coder.code(
                    brief, mode=mode, skill_id=skill_id_hint, project_root=project_root
                )
            run_dict: Optional[Dict[str, Any]] = None
            repaired = False
            if run_immediately:
                sid = getattr(skill, "skill_id", "") or skill_id_hint or ""
                run_obj = coder.run(sid, run_input)
                run_dict = (
                    run_obj.to_dict()
                    if hasattr(run_obj, "to_dict") and callable(run_obj.to_dict)
                    else {"output": getattr(run_obj, "output", None)}
                )
                run_error = _run_error_message(run_dict)
                if run_error and bool(logic.get("auto_repair", True)):
                    try:
                        repaired_skill = coder.repair(
                            sid,
                            failure=(
                                f"ESkill vibe_code run failed: {run_error}\n"
                                f"input_data={run_input!r}\nbrief={brief[:1000]}"
                            ),
                        )
                        sid = getattr(repaired_skill, "skill_id", sid)
                        run_obj = coder.run(sid, run_input)
                        run_dict = (
                            run_obj.to_dict()
                            if hasattr(run_obj, "to_dict") and callable(run_obj.to_dict)
                            else {"output": getattr(run_obj, "output", None)}
                        )
                        skill = repaired_skill
                        repaired = True
                    except Exception as repair_exc:  # noqa: BLE001
                        logger.warning("vibe_code auto repair failed: %s", repair_exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("vibe_code ESkill execution failed")
        return {
            "eskill_logic_type": "vibe_code",
            "ok": False,
            "error": f"vibe_code 失败: {exc}",
        }

    skill_dict: Dict[str, Any]
    if hasattr(skill, "to_dict") and callable(skill.to_dict):
        skill_dict = dict(skill.to_dict())
    else:
        skill_dict = {
            "skill_id": getattr(skill, "skill_id", ""),
            "code_excerpt": (getattr(skill, "code", "") or "")[:1500],
        }
    output_var = str(logic.get("output_var") or "vibe_result")
    return {
        "eskill_logic_type": "vibe_code",
        "ok": True,
        "vibe_skill": skill_dict,
        "vibe_run": run_dict,
        "auto_repaired": repaired,
        output_var: (run_dict or skill_dict),
    }


def _run_error_message(run_dict: Optional[Dict[str, Any]]) -> str:
    if not isinstance(run_dict, dict):
        return ""
    for key in ("error", "error_message"):
        value = run_dict.get(key)
        if value:
            return str(value)
    output = run_dict.get("output") or run_dict.get("output_data")
    if isinstance(output, dict) and output.get("error"):
        return str(output.get("error"))
    stage = str(run_dict.get("stage") or "")
    if stage.lower() in {"failed", "error"}:
        return stage
    return ""


def execute_vibe_workflow_kind(
    logic: Dict[str, Any],
    input_data: Dict[str, Any],
    *,
    user_id: int,
) -> Dict[str, Any]:
    """``logic.type == "vibe_workflow"``: NL → :class:`VibeWorkflowGraph`,立即 ``execute``。

    logic 字段同 ``vibe_code``;不接受 skill_id(workflow 总是 fresh)。
    支持 ``project_root`` 字段：合法工作区路径，会注入项目分析到 workflow 的 brief。
    返回 ``vibe_workflow_run`` 包含 vibe-coding 的 :class:`WorkflowRunResult`。
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_vibe_coder,
        )
    except ImportError as exc:  # pragma: no cover
        return {
            "eskill_logic_type": "vibe_workflow",
            "ok": False,
            "error": f"integrations 未导入: {exc}",
        }

    pm = _resolve_provider_model(logic, int(user_id or 0))
    if not pm["provider"] or not pm["model"]:
        return {
            "eskill_logic_type": "vibe_workflow",
            "ok": False,
            "error": "缺少 provider/model",
        }

    # Validate project_root if provided.
    project_root: Optional[str] = None
    try:
        project_root = _resolve_project_root(logic, int(user_id or 0))
    except Exception as exc:  # noqa: BLE001
        return {
            "eskill_logic_type": "vibe_workflow",
            "ok": False,
            "error": f"project_root 路径无效: {exc}",
        }

    brief = _render_brief(logic, input_data)
    exec_input = dict(input_data or {})
    if project_root and "project_analysis" not in exec_input:
        try:
            import json as _json

            from vibe_coding.code_factory import analyze_project  # type: ignore[import-not-found]

            analysis = analyze_project(project_root)
            exec_input["project_analysis"] = _json.loads(
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
        except Exception:  # noqa: BLE001
            logger.warning("vibe_workflow: project_root 分析失败，已跳过", exc_info=True)

    sf = get_session_factory()
    try:
        with sf() as session:
            try:
                coder = get_vibe_coder(
                    session=session,
                    user_id=int(user_id or 0),
                    provider=pm["provider"],
                    model=pm["model"],
                )
            except VibeIntegrationError as exc:
                return {
                    "eskill_logic_type": "vibe_workflow",
                    "ok": False,
                    "error": str(exc),
                }
            graph = coder.workflow(brief, project_root=project_root)
            run_result = coder.execute(graph, exec_input)
    except Exception as exc:  # noqa: BLE001
        logger.exception("vibe_workflow ESkill execution failed")
        return {
            "eskill_logic_type": "vibe_workflow",
            "ok": False,
            "error": f"vibe_workflow 失败: {exc}",
        }

    graph_dict = (
        graph.to_dict()
        if hasattr(graph, "to_dict") and callable(graph.to_dict)
        else {"nodes": getattr(graph, "nodes", []), "edges": getattr(graph, "edges", [])}
    )
    run_dict = (
        run_result.to_dict()
        if hasattr(run_result, "to_dict") and callable(run_result.to_dict)
        else {"output": getattr(run_result, "output", None)}
    )
    output_var = str(logic.get("output_var") or "vibe_workflow_result")
    return {
        "eskill_logic_type": "vibe_workflow",
        "ok": True,
        "vibe_graph": graph_dict,
        "vibe_workflow_run": run_dict,
        output_var: run_dict,
    }


VIBE_KINDS = {
    "vibe_code": execute_vibe_code_kind,
    "vibe_workflow": execute_vibe_workflow_kind,
}


def is_vibe_kind(logic_type: str) -> bool:
    return logic_type in VIBE_KINDS


def execute_vibe_kind(
    logic: Dict[str, Any],
    input_data: Dict[str, Any],
    *,
    user_id: int,
) -> Dict[str, Any]:
    """统一入口,供 :func:`eskill_runtime._execute_logic` 调用。"""
    fn = VIBE_KINDS.get(str(logic.get("type") or ""))
    if fn is None:
        raise ValueError(f"非 vibe-coding ESkill kind: {logic.get('type')!r}")
    return fn(logic, input_data, user_id=int(user_id or 0))


__all__ = [
    "VIBE_KINDS",
    "execute_vibe_code_kind",
    "execute_vibe_kind",
    "execute_vibe_workflow_kind",
    "is_vibe_kind",
]
