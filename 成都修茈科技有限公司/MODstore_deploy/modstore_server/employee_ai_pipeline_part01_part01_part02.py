# mypy: disable-error-code="attr-defined, index, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.employee_ai_pipeline_part01_part01_part01 import EmployeeConfigV2
from modstore_server.employee_ai_pipeline_part01_part01_part01 import Intent
from modstore_server.employee_ai_pipeline_part01_part01_part01 import PricingHint
from modstore_server.employee_ai_pipeline_part01_part01_part01 import SuggestedSkill
from modstore_server.employee_ai_pipeline_part01_part01_part01 import WorkflowChoice


def _facade():
    return importlib.import_module("modstore_server.employee_ai_pipeline")


async def stage_suggest_pricing(
    intent: Intent,
    v2: EmployeeConfigV2,
    skills: _facade().List[SuggestedSkill],
    llm: _facade().LlmClient,
) -> _facade().Tuple[_facade().Optional[PricingHint], str]:
    handlers = list(v2.actions.get("handlers") or [])
    ctx = f"角色：{intent.role}\n行业：{intent.industry}\n复杂度：{intent.complexity}\n技能数：{len(skills)}\n已启用功能：{', '.join(handlers)}"
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_SUGGEST_PRICING},
            {"role": "user", "content": ctx},
        ],
        max_tokens=1024,
    )
    data, err = _facade()._parse_json(content)
    if err:
        return (None, err)
    if not isinstance(data, dict):
        return (None, "须返回 JSON 对象")
    return (
        _facade().PricingHint(
            tier=str(data.get("tier") or "free"),
            cny=float(data.get("cny") or 0),
            period=str(data.get("period") or "month"),
            reasoning=str(data.get("reasoning") or "")[:120],
        ),
        "",
    )


def stage_assemble(
    intent: Intent,
    workflow_choice: _facade().Optional[WorkflowChoice],
    v2: EmployeeConfigV2,
    skills: _facade().List[SuggestedSkill],
    pricing: _facade().Optional[PricingHint],
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], _facade().List[str]]:
    from modman.manifest_util import validate_manifest_dict
    from modstore_server.xcagi_host_profile import (
        merge_workflow_employee_for_manifest,
        normalize_xcagi_host_profile,
    )

    eid = intent.id
    hp_norm, _ = normalize_xcagi_host_profile({"panel_kind": "mod_http"})
    wf_row = merge_workflow_employee_for_manifest(
        employee_id=eid,
        label=intent.name,
        panel_summary=intent.scenario,
        host_profile=hp_norm,
    )
    if workflow_choice and workflow_choice.workflow_id:
        wf_row["workflow_id"] = workflow_choice.workflow_id
    metadata: _facade().Dict[str, _facade().Any] = {
        "framework_version": "2.0.0",
        "created_by": "employee_ai_pipeline",
    }
    if skills:
        metadata["suggested_skills"] = [_facade().asdict(s) for s in skills]
    if pricing:
        metadata["suggested_pricing"] = _facade().asdict(pricing)
    if workflow_choice and workflow_choice.workflow_id and (not workflow_choice.sandbox_passed):
        metadata["workflow_needs_sandbox"] = True
    v2_dict = _facade().asdict(v2)
    v2_dict.setdefault(
        "identity",
        {
            "id": intent.id,
            "version": "1.0.0",
            "artifact": "employee_pack",
            "name": intent.name,
            "description": intent.scenario,
        },
    )
    cognition = v2_dict.get("cognition") if isinstance(v2_dict.get("cognition"), dict) else {}
    caps = _facade()._default_capabilities(
        pid=intent.id,
        name=intent.name,
        description=intent.scenario,
        employee_id=eid,
        label=intent.name,
        capabilities=[s.name for s in skills],
    )
    if skills:
        cognition["skills"] = [_facade().asdict(s) for s in skills]
    else:
        cognition["skills"] = _facade()._default_skill_entries(
            caps, label=intent.name, description=intent.scenario
        )
    v2_dict["cognition"] = cognition
    collab = v2_dict.get("collaboration") if isinstance(v2_dict.get("collaboration"), dict) else {}
    workflow = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
    workflow["workflow_id"] = (
        workflow_choice.workflow_id if workflow_choice and workflow_choice.workflow_id else 0
    )
    workflow["name"] = (
        workflow_choice.workflow_name
        if workflow_choice and workflow_choice.workflow_name
        else f"{intent.name}工作流"
    )
    collab["workflow"] = workflow
    v2_dict["collaboration"] = collab
    v2_dict["metadata"] = metadata
    if _facade()._is_project_analysis_intent(intent):
        actions_in_v2 = v2_dict.get("actions")
        if isinstance(actions_in_v2, dict):
            if "agent" not in (actions_in_v2.get("handlers") or []):
                actions_in_v2["handlers"] = ["agent"]
            if not isinstance(actions_in_v2.get("agent"), dict):
                actions_in_v2["agent"] = {}
            actions_in_v2["agent"].setdefault(
                "workspace",
                {
                    "mode": "user_project",
                    "requires_project_root": True,
                    "read_only": True,
                },
            )
        v2_dict["actions"] = actions_in_v2
    manifest: _facade().Dict[str, _facade().Any] = {
        "id": intent.id,
        "name": intent.name,
        "version": "1.0.0",
        "author": "",
        "description": intent.scenario,
        "artifact": "employee_pack",
        "scope": "global",
        "industry": intent.industry,
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {"id": eid, "label": intent.name, "capabilities": caps},
        "employee_config_v2": v2_dict,
        "xcagi_host_profile": hp_norm or {"panel_kind": "mod_http"},
        "workflow_employees": [wf_row],
        "backend": {"entry": "blueprints", "init": "mod_init"},
    }
    if pricing and (pricing.cny > 0 or pricing.tier != "free"):
        manifest["commerce"] = {
            "price": pricing.cny,
            "currency": "CNY",
            "tier": pricing.tier,
            "period": pricing.period,
        }
    errs = validate_manifest_dict(manifest)
    return (manifest, errs)


def _build_vibe_coding_prompt(
    runtime_kind: str, rule_spec: _facade().Dict[str, _facade().Any]
) -> str:
    """Build a domain-specific system prompt for vibe coding convert.py.

    Includes a few-shot example from the built-in runtime so the LLM can
    learn the expected code structure, naming conventions, and output schema.
    """
    from modstore_server.csv_tabular_runtime import render_csv_read_convert_module
    from modstore_server.excel_tabular_runtime import render_excel_read_convert_module
    from modstore_server.pdf_extract_runtime import render_pdf_read_convert_module
    from modstore_server.ppt_extract_runtime import render_ppt_read_convert_module
    from modstore_server.txt_extract_runtime import render_txt_read_convert_module
    from modstore_server.word_extract_runtime import render_word_fallback_convert_module

    _FEW_SHOT_MAP = {
        "word_full_extract": render_word_fallback_convert_module,
        "excel_full_read": render_excel_read_convert_module,
        "csv_full_read": render_csv_read_convert_module,
        "pdf_full_read": render_pdf_read_convert_module,
        "ppt_full_read": render_ppt_read_convert_module,
        "txt_full_read": render_txt_read_convert_module,
    }
    few_shot_code = ""
    if runtime_kind in _FEW_SHOT_MAP:
        few_shot_code = _FEW_SHOT_MAP[runtime_kind]()
    if len(few_shot_code) > 8000:
        few_shot_code = few_shot_code[:8000] + "\n# ... (truncated for brevity)\n"
    output_schema = rule_spec.get("output_schema") or []
    schema_str = (
        _facade().json.dumps(output_schema, ensure_ascii=False)
        if output_schema
        else "(see rule_spec)"
    )
    prompt = (
        "你是工作台 vibecoding 的 Python 实现器。你的任务是生成 convert.py —— 一个完整的、可直接运行的 Python 文件，用于处理特定文件格式。\n\n## 核心要求\n\n1. 必须定义 `convert_file(src_path: Path, output_path: Path, *, template_path: Optional[Path], payload: Dict[str, Any], ctx: Dict[str, Any], rule_spec: Dict[str, Any]) -> Dict[str, Any]` 函数\n2. 必须真实读取输入文件、按规则写出 output_path，不能写伪结果或占位符\n3. 输出 JSON 必须包含以下顶层字段: "
        + schema_str
        + "\n4. 同时输出纯文本文件 (document_full.txt)\n\n## 安全约束\n\n- 禁止使用: eval/exec/compile/__import__/subprocess/os.system/ctypes/multiprocessing\n- 允许使用: pathlib, json, datetime, re, typing, io, copy, collections, zipfile, xml.etree.ElementTree, openpyxl, pandas\n- 对于 .docx 文件，必须用 zipfile + ElementTree 直接解析 OOXML，不要依赖 python-docx\n\n## 输出格式\n\n只输出一个完整的 Python 文件（不要 Markdown 围栏、不要解释、不要注释说明这是生成的代码）\n\n"
    )
    if few_shot_code:
        prompt += (
            "## 参考实现 (few-shot example)\n\n以下是一个类似任务的参考实现，你可以学习其代码结构、命名规范和解析策略，但需要根据当前 brief 和 rule_spec 生成你自己的实现：\n\n```python\n"
            + few_shot_code
            + "\n```\n\n"
        )
    prompt += f"## 当前任务\n\nruntime_kind: {runtime_kind}\n请根据下方 user message 中的 brief 和 rule_spec 生成 convert.py。"
    return prompt


@_facade().dataclass
class GeneratedCode:
    employee_py: str = ""
    vendor_modules: _facade().Dict[str, str] = _facade().field(default_factory=dict)
    rule_spec: _facade().Dict[str, _facade().Any] = _facade().field(default_factory=dict)
    asset_manifest: _facade().Dict[str, _facade().Any] = _facade().field(default_factory=dict)
    runtime_kind: str = ""
    code_source: str = ""
    warnings: _facade().List[str] = _facade().field(default_factory=list)
