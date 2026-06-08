"""把 vibe-coding 暴露成 employee_executor 的 action handler。

被 :func:`modstore_server.employee_executor._actions_real` 在遇到
``handlers: ["vibe_edit"|"vibe_heal"|"vibe_code"]`` 时调用。

设计要点:
- 所有 root 强制走 :func:`vibe_adapter.ensure_within_workspace`,越界直接拒绝。
- ``vibe_heal`` 的同步等待会比较长,默认强建议作者用 ``async_mode=True``;
  这里不支持真异步队列(MODstore 还没有统一的 task queue),用 ``async_mode``
  返回 ``status: "skipped_async_unsupported"`` 提示作者改用脚本工作流。
- 所有出错路径都返回 ``{"handler": "vibe_*", "ok": False, "error": ...}``,
  不抛异常,避免把员工任务整体打挂。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.employee_scope_policy import (
    safe_resolve_under_directory,
    validate_repo_paths_for_employee_pack,
)
from modstore_server.models import get_session_factory

logger = logging.getLogger(__name__)


def _publish_scope_violation(employee_id: str, detail: str) -> None:
    try:
        from modstore_server.incident_bus import publish

        publish(
            "employee.suggestion.created",
            {
                "kind": "scope_violation",
                "source": "vibe_handler",
                "detail": (detail or "")[:800],
                "target_employee_ids": ["daily-orchestrator"],
            },
            source=str(employee_id or "unknown"),
        )
    except Exception:  # noqa: BLE001
        logger.exception("publish scope_violation failed")


def _safe_resolve_provider_model(
    user_id: int,
    provider_hint: str,
    model_hint: str,
) -> Dict[str, str]:
    """以 user 默认 LLM 偏好补全 provider/model;不抛错,缺信息时返回空串。"""
    prov = (provider_hint or "").strip()
    mdl = (model_hint or "").strip()
    if prov and mdl:
        return {"provider": prov, "model": mdl}
    try:
        import json as _json

        from modstore_server.llm_key_resolver import KNOWN_PROVIDERS
        from modstore_server.models import User

        sf = get_session_factory()
        with sf() as session:
            urow = session.query(User).filter(User.id == int(user_id or 0)).first()
            raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
            if not raw_pref:
                return {"provider": prov, "model": mdl}
            prefs = _json.loads(raw_pref)
            if not isinstance(prefs, dict):
                return {"provider": prov, "model": mdl}
            if not prov:
                p = str(prefs.get("provider") or "").strip()
                if p in KNOWN_PROVIDERS:
                    prov = p
            if not mdl:
                mdl = str(prefs.get("model") or "").strip()
    except Exception:  # noqa: BLE001
        logger.exception("vibe action handler 解析默认 provider/model 失败")
    return {"provider": prov, "model": mdl}


def _build_brief(action_cfg: Dict[str, Any], reasoning: Dict[str, Any], task: str) -> str:
    """合成 brief:作者填的 brief 模板 + LLM reasoning + 用户 task。"""
    template = str(action_cfg.get("brief") or "").strip()
    reasoning_text = str((reasoning or {}).get("reasoning") or "").strip()
    if template:
        rendered = template.replace("{{task}}", task or "").replace("{{reasoning}}", reasoning_text)
        return rendered.strip()
    parts = []
    if task:
        parts.append(task)
    if reasoning_text:
        parts.append(reasoning_text)
    return "\n\n".join(parts).strip() or "改进当前项目质量。"


def vibe_edit_handler(
    action_cfg: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> Dict[str, Any]:
    """``vibe_edit`` action: 单轮 ``edit_project`` + ``apply_patch``。

    config 字段:
        root: str               必填,目标目录(必须在用户工作区内)
        brief: str              可选,brief 模板;未填则用 task + reasoning 拼
        focus_paths: List[str]  可选,缩窄 edit_project 的注意范围
        dry_run: bool           可选,默认 False
        provider/model: str     可选,缺省走用户默认 LLM
        async_mode: bool        预留;为 True 时直接返回 skipped_async_unsupported
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            VibePathError,
            ensure_within_workspace,
            get_vibe_coder,
            patch_to_dict,
        )
    except ImportError as exc:  # pragma: no cover
        return {"handler": "vibe_edit", "ok": False, "error": f"integrations 未导入: {exc}"}

    if action_cfg.get("async_mode"):
        return {
            "handler": "vibe_edit",
            "ok": False,
            "error": "vibe_edit 暂不支持 async_mode;请改用脚本工作流或工作台「AI 代码技能」",
        }

    raw_root = action_cfg.get("root") or ""
    try:
        root = ensure_within_workspace(raw_root, user_id=int(user_id or 0))
    except VibePathError as exc:
        return {"handler": "vibe_edit", "ok": False, "error": str(exc)}

    pm = _safe_resolve_provider_model(
        int(user_id or 0),
        str(action_cfg.get("provider") or ""),
        str(action_cfg.get("model") or ""),
    )
    if not pm["provider"] or not pm["model"]:
        return {
            "handler": "vibe_edit",
            "ok": False,
            "error": "未确定 LLM provider/model,请在配置或账户默认 LLM 中指定",
        }

    brief = _build_brief(action_cfg, reasoning, task)
    focus_paths_raw = action_cfg.get("focus_paths")
    focus_paths = (
        [str(x) for x in focus_paths_raw if x] if isinstance(focus_paths_raw, list) else None
    )
    dry_run = bool(action_cfg.get("dry_run", False))

    sf = get_session_factory()
    try:
        with sf() as session:
            paths_chk: List[Path] = [Path(root)]
            if focus_paths:
                for fp in focus_paths:
                    if not str(fp or "").strip():
                        continue
                    sub, ferr = safe_resolve_under_directory(Path(root), str(fp))
                    if ferr:
                        _publish_scope_violation(employee_id, ferr)
                        return {"handler": "vibe_edit", "ok": False, "error": ferr}
                    if sub is not None:
                        paths_chk.append(sub)
            scope_err = validate_repo_paths_for_employee_pack(session, employee_id, paths_chk)
            if scope_err:
                _publish_scope_violation(employee_id, scope_err)
                return {"handler": "vibe_edit", "ok": False, "error": scope_err}
            try:
                coder = get_vibe_coder(
                    session=session,
                    user_id=int(user_id or 0),
                    provider=pm["provider"],
                    model=pm["model"],
                )
            except VibeIntegrationError as exc:
                return {"handler": "vibe_edit", "ok": False, "error": str(exc)}
            try:
                patch = coder.edit_project(brief, root=root, focus_paths=focus_paths)
            except TypeError:
                patch = coder.edit_project(brief, root=root)
            apply_result = coder.apply_patch(patch, root=root, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("vibe_edit handler failed")
        return {"handler": "vibe_edit", "ok": False, "error": f"vibe_edit 失败: {exc}"}

    apply_dict: Dict[str, Any]
    if hasattr(apply_result, "to_dict") and callable(apply_result.to_dict):
        apply_dict = dict(apply_result.to_dict())
    else:
        apply_dict = {
            "applied": getattr(apply_result, "applied", None),
            "errors": list(getattr(apply_result, "errors", []) or []),
        }
    return {
        "handler": "vibe_edit",
        "ok": bool(apply_dict.get("applied", True)) and not apply_dict.get("errors"),
        "root": str(root),
        "dry_run": dry_run,
        "patch": patch_to_dict(patch),
        "apply": apply_dict,
        "employee_id": employee_id,
    }


def vibe_heal_handler(
    action_cfg: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> Dict[str, Any]:
    """``vibe_heal`` action: 多轮 ``heal_project``,默认 max_rounds=3。

    config 字段:
        root: str          必填
        brief: str         可选 brief 模板
        max_rounds: int    可选,默认 3,上限 5(重型动作)
        provider/model     可选
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            VibePathError,
            ensure_within_workspace,
            get_project_vibe_coder,
            heal_result_to_dict,
        )
    except ImportError as exc:  # pragma: no cover
        return {"handler": "vibe_heal", "ok": False, "error": f"integrations 未导入: {exc}"}

    raw_root = action_cfg.get("root") or ""
    try:
        root = ensure_within_workspace(raw_root, user_id=int(user_id or 0))
    except VibePathError as exc:
        return {"handler": "vibe_heal", "ok": False, "error": str(exc)}

    pm = _safe_resolve_provider_model(
        int(user_id or 0),
        str(action_cfg.get("provider") or ""),
        str(action_cfg.get("model") or ""),
    )
    if not pm["provider"] or not pm["model"]:
        return {
            "handler": "vibe_heal",
            "ok": False,
            "error": "未确定 LLM provider/model",
        }

    try:
        max_rounds = int(action_cfg.get("max_rounds") or 3)
    except (TypeError, ValueError):
        max_rounds = 3
    max_rounds = max(1, min(max_rounds, 5))

    brief = _build_brief(action_cfg, reasoning, task)

    sf = get_session_factory()
    try:
        with sf() as session:
            scope_err = validate_repo_paths_for_employee_pack(session, employee_id, [Path(root)])
            if scope_err:
                _publish_scope_violation(employee_id, scope_err)
                return {"handler": "vibe_heal", "ok": False, "error": scope_err}
            try:
                coder = get_project_vibe_coder(
                    root,
                    session=session,
                    user_id=int(user_id or 0),
                    provider=pm["provider"],
                    model=pm["model"],
                )
            except VibeIntegrationError as exc:
                return {"handler": "vibe_heal", "ok": False, "error": str(exc)}
            result = coder.heal_project(brief, max_rounds=max_rounds)
    except Exception as exc:  # noqa: BLE001
        logger.exception("vibe_heal handler failed")
        return {"handler": "vibe_heal", "ok": False, "error": f"vibe_heal 失败: {exc}"}

    return {
        "handler": "vibe_heal",
        "ok": bool(getattr(result, "ok", True)),
        "root": str(root),
        "rounds": int(getattr(result, "rounds", 0) or 0),
        "result": heal_result_to_dict(result),
        "employee_id": employee_id,
    }


def vibe_code_handler(
    action_cfg: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> Dict[str, Any]:
    """``vibe_code`` action: NL → ``CodeSkill``,可选立即 ``run`` 一次。

    config 字段:
        brief: str         可选 brief 模板;为空时用 task + reasoning
        skill_id: str      可选,允许命名复用
        run_input: dict    可选,非空时执行 .run(skill_id, run_input)
        mode: str          可选 "brief_first"|"direct",默认 brief_first
        provider/model     可选
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_vibe_coder,
        )
    except ImportError as exc:  # pragma: no cover
        return {"handler": "vibe_code", "ok": False, "error": f"integrations 未导入: {exc}"}

    pm = _safe_resolve_provider_model(
        int(user_id or 0),
        str(action_cfg.get("provider") or ""),
        str(action_cfg.get("model") or ""),
    )
    if not pm["provider"] or not pm["model"]:
        return {
            "handler": "vibe_code",
            "ok": False,
            "error": "未确定 LLM provider/model",
        }

    brief = _build_brief(action_cfg, reasoning, task)
    skill_id_hint = action_cfg.get("skill_id") or None
    mode = str(action_cfg.get("mode") or "brief_first")
    run_input = (
        action_cfg.get("run_input") if isinstance(action_cfg.get("run_input"), dict) else None
    )

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
                return {"handler": "vibe_code", "ok": False, "error": str(exc)}
            skill = coder.code(brief, mode=mode, skill_id=skill_id_hint)
            run_dict: Optional[Dict[str, Any]] = None
            if run_input is not None:
                run_obj = coder.run(
                    getattr(skill, "skill_id", "") or skill_id_hint or "", run_input
                )
                run_dict = (
                    run_obj.to_dict()
                    if hasattr(run_obj, "to_dict") and callable(run_obj.to_dict)
                    else {"output": getattr(run_obj, "output", None)}
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("vibe_code handler failed")
        return {"handler": "vibe_code", "ok": False, "error": f"vibe_code 失败: {exc}"}

    skill_dict: Dict[str, Any]
    if hasattr(skill, "to_dict") and callable(skill.to_dict):
        skill_dict = dict(skill.to_dict())
    else:
        skill_dict = {
            "skill_id": getattr(skill, "skill_id", ""),
            "code_excerpt": (getattr(skill, "code", "") or "")[:1500],
        }
    return {
        "handler": "vibe_code",
        "ok": True,
        "skill": skill_dict,
        "run": run_dict,
        "employee_id": employee_id,
    }


VIBE_HANDLERS = {
    "vibe_edit": vibe_edit_handler,
    "vibe_heal": vibe_heal_handler,
    "vibe_code": vibe_code_handler,
}


def dispatch_vibe_handler(
    handler_name: str,
    actions_cfg: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> Optional[Dict[str, Any]]:
    """供 :func:`employee_executor._actions_real` 调用的统一入口。

    返回 ``None`` 表示 handler_name 不属于 vibe 系列,调用方按原逻辑兜底。
    """
    fn = VIBE_HANDLERS.get(handler_name)
    if fn is None:
        return None
    cfg = actions_cfg.get(handler_name) if isinstance(actions_cfg.get(handler_name), dict) else {}
    return fn(cfg, reasoning, task, employee_id, int(user_id or 0))


__all__ = [
    "VIBE_HANDLERS",
    "dispatch_vibe_handler",
    "vibe_code_handler",
    "vibe_edit_handler",
    "vibe_heal_handler",
]
