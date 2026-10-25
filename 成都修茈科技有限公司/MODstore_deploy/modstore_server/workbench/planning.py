"""Planning for workbench delivery."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from sqlalchemy.orm import Session

from modstore_server.operational_errors import RECOVERABLE_ERRORS

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class PlanningPorts:
    resolve_api_key: Callable[[Session, int, str], tuple[str | None, str]]
    resolve_base_url: Callable[[Session, int, str], str | None]
    chat: Callable[..., Awaitable[dict[str, Any]]]


def _script_workflow_brief(
    payload: Dict[str, Any], files: List[Dict[str, Any]]
) -> Dict[str, Any]:
    brief = (payload.get("brief") or "").strip()
    filenames = [str((f or {}).get("filename") or "upload.bin") for f in files or []]
    return {
        "goal": brief,
        "inputs": [
            {"filename": name, "description": "工作台上传样本文件"}
            for name in filenames
        ],
        "outputs": "生成处理后的结果文件到 outputs/，用于下载和沙箱复核",
        "acceptance": "脚本运行成功，outputs/ 至少生成一个结果文件",
        "fallback": "",
        "trigger_type": "manual",
        "references": {"source": "workbench-script-session"},
    }


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        import re

        t = re.sub("^```(?:json)?\\s*", "", t, flags=re.I)
        t = re.sub("\\s*```\\s*$", "", t)
    return t.strip()


def _fallback_employee_orchestration_plan(
    brief: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    from modstore_server.csv_tabular_runtime import (
        is_csv_full_read,
        is_csv_generate,
        resolve_csv_orchestration_plan,
    )
    from modstore_server.employee_brief_utils import (
        compact_routing_brief,
        extract_routing_brief,
    )
    from modstore_server.excel_tabular_runtime import (
        is_excel_full_read,
        is_excel_generate,
        resolve_excel_orchestration_plan,
    )
    from modstore_server.pdf_extract_runtime import (
        is_pdf_full_read,
        is_pdf_generate,
        resolve_pdf_orchestration_plan,
    )
    from modstore_server.txt_extract_runtime import (
        is_txt_full_read,
        is_txt_generate,
        resolve_txt_orchestration_plan,
    )
    from modstore_server.word_extract_runtime import (
        is_word_full_extract,
        word_extract_orchestration_plan,
    )
    from modstore_server.word_generate_runtime import (
        is_word_generate,
        word_generate_orchestration_plan,
    )

    routing_brief = extract_routing_brief(
        cast(dict[str, Any], payload)
        if isinstance(payload, dict)
        else {"brief": brief},
        fallback=brief,
    )
    if is_csv_full_read(routing_brief) or is_csv_generate(routing_brief):
        return resolve_csv_orchestration_plan(routing_brief, payload)
    if is_excel_full_read(routing_brief) or is_excel_generate(routing_brief):
        return resolve_excel_orchestration_plan(routing_brief, payload)
    if is_txt_full_read(routing_brief) or is_txt_generate(routing_brief):
        return resolve_txt_orchestration_plan(routing_brief, payload)
    if is_pdf_full_read(routing_brief) or is_pdf_generate(routing_brief):
        return resolve_pdf_orchestration_plan(routing_brief, payload)
    if is_word_generate(routing_brief):
        return word_generate_orchestration_plan(routing_brief, payload)
    if is_word_full_extract(routing_brief):
        return word_extract_orchestration_plan(routing_brief, payload)
    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join((f"- {x}" for x in checklist if isinstance(x, str)))
        if isinstance(checklist, list)
        else ""
    )
    source_docs = payload.get("source_documents")
    doc_hint = ""
    if isinstance(source_docs, list) and source_docs:
        names = [
            str((x or {}).get("name") or "").strip()
            for x in source_docs
            if isinstance(x, dict)
        ]
        doc_hint = "参考资料：" + "、".join([n for n in names if n][:8])
    merged = "\n".join(
        (
            x
            for x in [
                compact_routing_brief(routing_brief, max_len=500) or routing_brief,
                checklist_text,
                doc_hint,
            ]
            if x
        )
    ).strip()
    short = (
        compact_routing_brief(routing_brief, max_len=40) or "员工助手"
    ).strip() or "员工助手"
    bl = (routing_brief or "").lower()
    is_word_extract = any(
        (k in bl for k in ("word", "docx", "doc", "txt", "文本", "文档"))
    ) and any((k in bl for k in ("提取", "解析", "保存", "转换", "全量")))
    script_brief = (
        f"{merged or brief}\n\n请生成 Python 脚本：读取 inputs/ 中的 .doc/.docx 文件，提取全部纯文本，写入 outputs/ 下同名 .txt；无输入时在 outputs/ 写入说明文件。"
        if is_word_extract
        else f"{merged or brief}\n\n请生成配套 Python 脚本：读取 inputs/ 中的文档或数据文件，递归整理可读文本，输出 Markdown 摘要/处理结果到 outputs/；没有输入文件时输出示例说明。"
    )
    script_runtime = (
        "只能读 inputs/、写 outputs/；使用 python-docx 或等价库解析 Word；禁止联网和越界文件访问。"
        if is_word_extract
        else "只能读 inputs/、写 outputs/；允许 os.walk 遍历 inputs；禁止联网和越界文件访问。"
    )
    workflow_brief = (
        f"{merged or brief}\n\nSkill 组流程：接收 Word 上传 → 解析提取全文 → 保存 txt → 交付用户。"
        if is_word_extract
        else f"{merged or brief}\n\n请把该员工拆成可执行 Skill 组：接收输入、读取/归纳、生成结果、人工复核。"
    )
    return {
        "employee_name": short,
        "employee_brief": merged or brief,
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": script_runtime,
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip()
        or short,
        "workflow_brief": workflow_brief,
        "acceptance": [
            "员工包可安装并能解释自己的职责",
            "脚本工作流可空跑并生成 outputs/ 结果文件",
            "Skill 组体现输入、处理、输出、复核的顺序",
        ],
    }


def _planning_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把前端需求规划材料固定进服务端会话，方便审计与重新生成。"""
    messages = payload.get("planning_messages")
    checklist = payload.get("execution_checklist")
    docs = payload.get("source_documents")
    return {
        "brief": (payload.get("brief") or "").strip(),
        "plan_notes": (payload.get("plan_notes") or "").strip(),
        "messages": cast(list[Any], messages) if isinstance(messages, list) else [],
        "execution_checklist": cast(list[Any], checklist)
        if isinstance(checklist, list)
        else [],
        "source_documents": cast(list[Any], docs) if isinstance(docs, list) else [],
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
    }


async def _build_employee_orchestration_plan(
    db: Session,
    user_id: int,
    *,
    payload: Dict[str, Any],
    provider: Optional[str],
    model: Optional[str],
    ports: PlanningPorts,
) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import extract_routing_brief
    from modstore_server.pdf_extract_runtime import (
        is_pdf_full_read,
        is_pdf_generate,
        resolve_pdf_orchestration_plan,
    )
    from modstore_server.txt_extract_runtime import (
        is_txt_full_read,
        is_txt_generate,
        resolve_txt_orchestration_plan,
    )
    from modstore_server.word_extract_runtime import (
        is_word_full_extract,
        word_extract_orchestration_plan,
    )
    from modstore_server.word_generate_runtime import (
        is_word_generate,
        word_generate_orchestration_plan,
    )

    brief = (payload.get("brief") or "").strip()
    routing_brief = extract_routing_brief(payload, fallback=brief)
    from modstore_server.employee_pipeline_routing import (
        resolve_deterministic_orchestration_plan,
        skip_employee_plan_llm,
    )

    det_plan = resolve_deterministic_orchestration_plan(routing_brief, payload)
    if det_plan and skip_employee_plan_llm(payload, routing_brief):
        return det_plan
    if is_txt_full_read(routing_brief) or is_txt_generate(routing_brief):
        return resolve_txt_orchestration_plan(routing_brief, payload)
    if is_pdf_full_read(routing_brief) or is_pdf_generate(routing_brief):
        return resolve_pdf_orchestration_plan(routing_brief, payload)
    if is_word_generate(routing_brief):
        return word_generate_orchestration_plan(routing_brief, payload)
    if is_word_full_extract(routing_brief):
        return word_extract_orchestration_plan(routing_brief, payload)
    fallback = _fallback_employee_orchestration_plan(routing_brief, payload)
    if not provider or not model:
        return fallback
    key, _src = ports.resolve_api_key(db, user_id, provider)
    if not key:
        return fallback
    checklist = payload.get("execution_checklist")
    messages = payload.get("planning_messages")
    docs = payload.get("source_documents")
    planning_context = {
        "brief": routing_brief,
        "execution_checklist": cast(list[Any], checklist)
        if isinstance(checklist, list)
        else [],
        "planning_messages": cast(list[Any], messages)
        if isinstance(messages, list)
        else [],
        "source_documents": cast(list[Any], docs) if isinstance(docs, list) else [],
    }
    sys_prompt = "你是 XCAGI「做员工」一站式编排规划器。只输出 JSON 对象，不要 markdown。\n你要把同一个用户需求拆成三份互相一致的 brief：\n1 employee_brief：给员工包生成器，描述角色、边界、输出格式。\n2 script_brief：给 Python 脚本工作流生成器，描述如何读取 inputs/、写 outputs/，没有输入也能空跑生成说明文件。\n3 workflow_brief：给画布 Skill 组生成器，描述多步自动化流程。\n字段必须包含：employee_name, employee_brief, script_workflow_name, script_brief, script_runtime_notes, workflow_name, workflow_brief, acceptance。\nscript_brief 必须明确：只能读 inputs/、只能写 outputs/；如需遍历文件，用 os.walk('inputs')；输出 Markdown 或 JSON 结果文件。\n若需求是 Word 全量提取（段落/表格/图片/样式/元数据），employee_brief 必须要求 direct_python + document_full.json，script_brief 必须要求 python-docx/zipfile 解析，workflow_brief 必须包含上传→解析→校验→交付步骤。\n不要让脚本读取真实磁盘绝对路径，不要要求联网。"
    try:
        res = await ports.chat(
            provider,
            api_key=key,
            base_url=ports.resolve_base_url(db, user_id, provider),
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {
                    "role": "user",
                    "content": json.dumps(planning_context, ensure_ascii=False)[:12000],
                },
            ],
            max_tokens=1800,
        )
    except RECOVERABLE_ERRORS:
        _LOG.exception("employee orchestration plan LLM failed")
        return fallback
    if not res.get("ok"):
        return fallback
    try:
        data = json.loads(_strip_json_fence(str(res.get("content") or "")))
    except json.JSONDecodeError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    out = {**fallback}
    for k in (
        "employee_name",
        "employee_brief",
        "script_workflow_name",
        "script_brief",
        "script_runtime_notes",
        "workflow_name",
        "workflow_brief",
    ):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    acc = data.get("acceptance")
    if isinstance(acc, list):
        out["acceptance"] = [str(x).strip() for x in acc if str(x).strip()][:8]
    return out


async def _resolve_default_llm_for_pipeline(db: Any, user_id: int) -> tuple:
    from modstore_server.llm_api import resolve_default_llm_route

    _LOG.debug(
        "pipeline: provider/model missing, resolving default for user=%s", user_id
    )
    try:
        resolved = await resolve_default_llm_route(db, user_id)
        rp = str(resolved.get("provider") or "").strip() or None
        rm = str(resolved.get("model") or "").strip() or None
        return (rp, rm)
    except RECOVERABLE_ERRORS:
        _LOG.debug(
            "pipeline: resolve_default_llm_route failed, no LLM available for user=%s",
            user_id,
            exc_info=True,
        )
        return (None, None)
