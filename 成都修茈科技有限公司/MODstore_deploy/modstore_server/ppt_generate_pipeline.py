"""Orchestrate PPT generate: route → plan → compose/enhance → OOXML → validate."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.office_plaintext_generate import resolve_presentation_spec
from modstore_server.ppt_compose_base import copy_template_base, create_compose_deck
from modstore_server.ppt_edit_plan import plan_from_presentation, validate_edit_plan
from modstore_server.ppt_homework_marquee import enhance_pptx_homework_marquee
from modstore_server.ppt_llm_planner import plan_with_llm
from modstore_server.ppt_ooxml_executor import apply_edit_plan, validate_pptx_package
from modstore_server.ppt_task_router import HOMEWORK_RECIPE, resolve_task_route


async def run_ppt_generate(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Optional[Dict[str, Any]] = None,
    ctx: Optional[Dict[str, Any]] = None,
    rule_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = dict(payload or {})
    ctx = dict(ctx or {})
    rule_spec = dict(rule_spec or {})
    warnings: List[str] = []

    user_q = str(payload.get("user_query") or ctx.get("user_query") or payload.get("task") or "")
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = output_dir / "output.pptx"
    if output_path.suffix.lower() == ".pptx":
        pptx_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".pptx"):
        pptx_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    workspace = Path(str(payload.get("workspace_root") or output_dir))
    route = resolve_task_route(user_query=user_q, template_path=template_path, payload=payload)
    mode = str(route.get("mode") or "compose")
    recipe = str(route.get("recipe") or "")

    if recipe == HOMEWORK_RECIPE and template_path and template_path.is_file():
        result = enhance_pptx_homework_marquee(template_path, pptx_path)
        ok, verr = validate_pptx_package(pptx_path)
        if not ok:
            warnings.extend(verr)
        return {
            **result,
            "output_path": str(pptx_path),
            "plan_mode": "enhance",
            "recipe": HOMEWORK_RECIPE,
            "warnings": warnings,
            "output_schema": list(rule_spec.get("output_schema") or []),
        }

    presentation: Optional[Dict[str, Any]] = None
    images_index: Optional[Dict[str, Any]] = None
    try:
        table, spec_warnings = await resolve_presentation_spec(src_path, payload, ctx, rule_spec)
        warnings.extend(spec_warnings or [])
        if isinstance(table, dict) and table.get("slides"):
            presentation = table
    except Exception as exc:
        warnings.append(f"解析 JSON 输入：{exc}")

    if not presentation and payload.get("presentation_full"):
        pf = payload.get("presentation_full")
        if isinstance(pf, dict):
            presentation = pf
        elif isinstance(pf, str):
            try:
                presentation = json.loads(pf)
            except json.JSONDecodeError:
                pass

    images_index_path = workspace / "outputs" / "images_index.json"
    if images_index_path.is_file():
        try:
            images_index = json.loads(images_index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    plan: Dict[str, Any]
    plan_warnings: List[str] = []
    if route.get("use_llm"):
        plan, plan_warnings = await plan_with_llm(
            user_query=user_q,
            mode=mode,
            presentation=presentation,
            images_index=images_index,
            ctx=ctx,
        )
    elif presentation:
        plan = plan_from_presentation(presentation, mode=mode)
    else:
        from modstore_server.ppt_llm_planner import _heuristic_compose_plan

        plan = _heuristic_compose_plan(user_q, mode=mode)
    warnings.extend(plan_warnings)
    plan, plan_errs = validate_edit_plan(plan)
    warnings.extend(plan_errs)

    plan_path = output_dir / "ppt_edit_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if mode == "enhance" and template_path and template_path.is_file():
        base_meta = copy_template_base(template_path, pptx_path)
    else:
        base_meta = create_compose_deck(
            plan,
            pptx_path,
            workspace_root=workspace,
        )

    exec_result = apply_edit_plan(pptx_path, plan, workspace_root=workspace)
    warnings.extend(exec_result.get("warnings") or [])

    ok, verr = validate_pptx_package(pptx_path)
    if not ok:
        warnings.extend(verr)
        warnings.append("尝试 text-only fallback")
        try:
            from modstore_server.pptx_export import build_pptx_from_presentation_json

            if presentation:
                pptx_path.write_bytes(build_pptx_from_presentation_json(presentation))
            elif plan.get("slides"):
                pptx_path.write_bytes(
                    build_pptx_from_presentation_json(
                        {
                            "title": plan.get("title"),
                            "slides": plan.get("slides"),
                        }
                    )
                )
        except Exception as exc:
            warnings.append(f"fallback 失败：{exc}")

    media_count = 0
    try:
        with zipfile.ZipFile(pptx_path, "r") as z:
            media_count = len([n for n in z.namelist() if n.startswith("ppt/media/")])
    except Exception:
        pass

    has_timing = bool(exec_result.get("has_animation"))
    if not has_timing:
        try:
            with zipfile.ZipFile(pptx_path, "r") as z:
                for name in z.namelist():
                    if name.startswith("ppt/slides/") and b"timing>" in z.read(name):
                        has_timing = True
                        break
        except Exception:
            pass

    return {
        "output_path": str(pptx_path),
        "plan_path": str(plan_path),
        "plan_mode": mode,
        "recipe": recipe or plan.get("recipe") or "",
        "slide_count": base_meta.get("slide_count", 0),
        "media_count": media_count,
        "has_animation": has_timing,
        "applied_ops": exec_result.get("applied_ops", 0),
        "title": str(plan.get("title") or ""),
        "warnings": warnings,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
