from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from modstore_server.craft_executor import register_craft_step

logger = logging.getLogger(__name__)


_SPEC_DOMAIN_KEYWORDS = {
    "合同": "合同/法务",
    "法律": "合同/法务",
    "合规": "合同/法务",
    "财务": "财务/会计",
    "发票": "财务/会计",
    "报销": "财务/会计",
    "客服": "客服/售后",
    "售后": "客服/售后",
    "退款": "客服/售后",
    "文档": "文档/知识",
    "知识库": "文档/知识",
    "RAG": "文档/知识",
    "电话": "电话/语音",
    "语音": "电话/语音",
    "TTS": "电话/语音",
    "数据分析": "数据/报表",
    "报表": "数据/报表",
    "统计": "数据/报表",
    "SEO": "SEO/站点",
    "站点": "SEO/站点",
    "sitemap": "SEO/站点",
}


async def _craft_spec(
    *,
    db: Any,
    user_id: int,
    payload: Any,
    brief: str,
    prov: Optional[str],
    mdl: Optional[str],
    routing_brief: Optional[str] = None,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.csv_tabular_runtime import (
        csv_generate_structured_spec,
        csv_read_structured_spec,
        is_csv_full_read,
        is_csv_generate,
    )
    from modstore_server.employee_brief_utils import extract_routing_brief
    from modstore_server.excel_tabular_runtime import (
        excel_generate_structured_spec,
        excel_read_structured_spec,
        is_excel_full_read,
        is_excel_generate,
    )
    from modstore_server.llm_chat_proxy import chat_dispatch
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.pdf_extract_runtime import (
        is_pdf_full_read,
        is_pdf_generate,
        pdf_generate_structured_spec,
        pdf_read_structured_spec,
    )
    from modstore_server.txt_extract_runtime import (
        is_txt_full_read,
        is_txt_generate,
        txt_generate_structured_spec,
        txt_read_structured_spec,
    )
    from modstore_server.word_extract_runtime import (
        is_word_full_extract,
        word_extract_structured_spec,
    )
    from modstore_server.word_generate_runtime import (
        is_word_generate,
        word_generate_structured_spec,
    )

    spec_warnings: List[str] = []
    brief_domain_hints: List[str] = []
    structured_requirement: Optional[Dict[str, Any]] = None

    rb = (routing_brief or "").strip()
    if not rb:
        rb = extract_routing_brief(
            payload if isinstance(payload, dict) else {"brief": brief}, fallback=brief
        )

    if not rb:
        spec_warnings.append(
            "需求描述为空，将使用默认配置生成员工；建议补充描述以获得更精准的员工能力"
        )
    elif len(rb) < 10:
        spec_warnings.append(
            f"需求描述仅 {len(rb)} 字，信息可能不足；建议补充员工的目标、输入输出和业务场景"
        )
    elif len(rb) > 2000:
        spec_warnings.append(f"需求描述 {len(rb)} 字较长，LLM 可能截断；建议精简到 500 字以内")

    _brief_lower = rb.lower() if rb else ""
    for _kw, _domain in _SPEC_DOMAIN_KEYWORDS.items():
        if _kw.lower() in _brief_lower and _domain not in brief_domain_hints:
            brief_domain_hints.append(_domain)

    if is_csv_generate(rb):
        structured_requirement = csv_generate_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "CSV 生成：runtime_kind=csv_generate；handlers=direct_python；JSON 中介 → outputs/output.csv"
        )
    elif is_csv_full_read(rb):
        structured_requirement = csv_read_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "CSV 全量读取：runtime_kind=csv_full_read；handlers=direct_python；输出 outputs/data.json"
        )
    elif is_excel_generate(rb):
        structured_requirement = excel_generate_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "Excel 生成：runtime_kind=excel_generate；handlers=direct_python；JSON 中介 → outputs/output.xlsx"
        )
    elif is_excel_full_read(rb):
        structured_requirement = excel_read_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "Excel 全量读取：runtime_kind=excel_full_read；handlers=direct_python；输出 outputs/workbook.json"
        )
    elif is_txt_generate(rb):
        structured_requirement = txt_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "TXT 生成：runtime_kind=txt_generate；handlers=direct_python+agent；"
            "输出 document_parsed.json + generated_document.txt"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join(str(c) for c in _caps[:4])}")
    elif is_txt_full_read(rb):
        structured_requirement = txt_read_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "TXT 全量读取：runtime_kind=txt_full_read；handlers=direct_python；"
            "输出 document_full.txt + document_meta.json"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join(str(c) for c in _caps[:4])}")
    elif is_pdf_generate(rb):
        structured_requirement = pdf_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "PDF 生成：runtime_kind=pdf_generate；handlers=direct_python+agent；"
            "JSON 中介 → outputs/generated_document.pdf"
        )
    elif is_pdf_full_read(rb):
        structured_requirement = pdf_read_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "PDF 全量读取：runtime_kind=pdf_full_read；handlers=direct_python；"
            "原生文字 + 图片分类 + VLM sidecar"
        )
    elif is_word_full_extract(rb):
        structured_requirement = word_extract_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "Word 全量提取：runtime_kind=word_full_extract；handlers=direct_python；"
            "输出 document_full.json + document_full.txt + images/"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join(str(c) for c in _caps[:4])}")
    elif is_word_generate(rb):
        structured_requirement = word_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "Word 生成：runtime_kind=word_generate；handlers=direct_python（+可选 agent）；"
            "JSON 中介 + 可选 template.docx → generated_document.docx"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join(str(c) for c in _caps[:4])}")
    elif rb and len(rb) >= 10 and prov and mdl:
        from modstore_server.employee_pipeline_routing import is_ambiguous_employee_brief

        if is_ambiguous_employee_brief(rb):
            try:
                _req_api_key, _ = resolve_api_key(db, user_id, prov)
                _req_prompt = (
                    "请从以下用户需求中提取结构化信息，只输出 JSON，不要 markdown 围栏：\n"
                    '{"domain":"业务领域","goal":"员工要达成的目标","input":"员工接收什么输入",'
                    '"output":"员工输出什么","constraints":["约束1","约束2"],'
                    '"suggested_capabilities":["cap1","cap2"],"suggested_handlers":["llm_md"]}\n\n'
                    f"用户需求：{rb}"
                )
                _req_result = await chat_dispatch(
                    prov,
                    api_key=_req_api_key,
                    base_url=(
                        resolve_base_url(db, user_id, prov)
                        if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
                        else None
                    ),
                    model=mdl,
                    messages=[{"role": "user", "content": _req_prompt}],
                    max_tokens=1500,
                )
                if _req_result.get("ok"):
                    _req_raw = re.sub(
                        r"^```(?:json)?\s*",
                        "",
                        (_req_result.get("content") or "").strip(),
                        flags=re.I,
                    )
                    _req_raw = re.sub(r"\s*```\s*$", "", _req_raw).strip()
                    _parsed_req = json.loads(_req_raw)
                    if isinstance(_parsed_req, dict):
                        structured_requirement = _parsed_req
                        _extracted_domain = str(_parsed_req.get("domain") or "").strip()
                        if _extracted_domain and _extracted_domain not in brief_domain_hints:
                            brief_domain_hints.append(_extracted_domain)
                        _extracted_caps = _parsed_req.get("suggested_capabilities")
                        if isinstance(_extracted_caps, list) and _extracted_caps:
                            spec_warnings.append(
                                f"LLM 建议能力：{'、'.join(str(c) for c in _extracted_caps[:4])}"
                            )
            except Exception:
                logger.debug("LLM structured requirement extraction failed", exc_info=True)

    if not structured_requirement and rb:
        bl = rb.lower()
        structured_requirement = {
            "domain": brief_domain_hints[0] if brief_domain_hints else "通用",
            "goal": rb.strip().splitlines()[0][:200],
            "input": "Word/文档" if any(k in bl for k in ("word", "docx", "文档")) else "用户输入",
            "output": "txt 文本" if "txt" in bl or "文本" in bl else "结构化结果",
            "constraints": [],
            "suggested_handlers": ["llm_md"],
        }

    return {
        "spec_warnings": spec_warnings,
        "brief_domain_hints": brief_domain_hints,
        "structured_requirement": structured_requirement,
        "routing_brief": rb,
    }


async def _craft_employee_plan(
    *,
    db: Any,
    user_id: int,
    payload: Any,
    prov: Optional[str],
    mdl: Optional[str],
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.workbench_api import _build_employee_orchestration_plan

    employee_plan = await _build_employee_orchestration_plan(
        db=db,
        user_id=user_id,
        payload=payload,
        provider=prov,
        model=mdl,
    )
    return {"employee_plan": employee_plan}


async def _craft_generate(
    *,
    db: Any,
    user: Any,
    session_id: str,
    brief: str,
    raw_files: Any,
    replace: bool,
    provider: Optional[str],
    model: Optional[str],
    use_word_extract: bool = False,
    payload: Any = None,
    employee_plan: Any = None,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.artifact_generator_blueprint import artifact_generator_preflight
    from modstore_server.employee_asset_pipeline import (
        run_asset_employee_scaffold_async,
        run_word_extract_employee_scaffold_async,
    )

    _payload = dict(payload) if isinstance(payload, dict) else {}
    if isinstance(employee_plan, dict) and employee_plan:
        _payload.setdefault("employee_plan", employee_plan)
    _bp = artifact_generator_preflight(payload=_payload, brief=brief)
    if _bp.get("status") == "error":
        return {
            "res": {
                "ok": False,
                "status": "error",
                "error": _bp.get("error"),
                "generation_mode": _bp.get("generation_mode"),
                "artifact_paths": [],
                "validation_result": _bp.get("validation_result"),
                "warnings": [],
                "missing_fields": _bp.get("missing_fields") or [],
            }
        }
    _scaffold_kw = dict(
        session_id=session_id,
        brief=brief,
        raw_files=raw_files,
        replace=replace,
        provider=provider,
        model=model,
        publish_to_catalog=False,
        force_llm_codegen=True,
        payload=_payload,
    )

    if use_word_extract:
        res = await run_word_extract_employee_scaffold_async(db=db, user=user, **_scaffold_kw)
    else:
        res = await run_asset_employee_scaffold_async(db=db, user=user, **_scaffold_kw)
    return {"res": res}


async def _craft_validate(
    *,
    res: Dict[str, Any],
    brief: str = "",
    pack_dir: Any = None,
    **_kw: Any,
) -> Dict[str, Any]:
    validate_warnings: List[str] = []
    validate_errors: List[str] = []

    if isinstance(res.get("validate_warnings"), list):
        validate_warnings.extend(str(x) for x in res["validate_warnings"] if x)
    if isinstance(res.get("validate_errors"), list):
        validate_errors.extend(str(x) for x in res["validate_errors"] if x)

    from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

    _rt = res.get("runtime_generation") if isinstance(res.get("runtime_generation"), dict) else {}
    if _rt and not is_llm_codegen_source(_rt):
        validate_errors.append(f"convert 非 LLM 生成：source={_rt.get('source')}")
    _ds = res.get("domain_smoke") if isinstance(res.get("domain_smoke"), dict) else {}
    if _ds.get("ok") is False:
        validate_errors.append(f"领域冒烟失败：{_ds.get('error') or 'failed'}"[:200])
    _gc = res.get("golden_comparison") if isinstance(res.get("golden_comparison"), dict) else {}
    if _gc.get("golden_pack_id") and not _gc.get("passed"):
        validate_errors.append(
            f"黄金对比未达标：parity={_gc.get('parity_score')} diffs={len(_gc.get('diff_items') or [])}"
        )

    _pack = Path(str(pack_dir or res.get("path") or ""))
    if not res.get("ok") and not _pack.is_dir():
        validate_errors.append(str(res.get("error") or "生成产物无效或缺少包目录"))
        return {"validate_warnings": validate_warnings, "validate_errors": validate_errors}

    if _pack.is_dir():
        from modman.manifest_util import read_manifest
        from modstore_server.mod_scaffold_runner import (
            employee_pack_consistency_warnings,
            mod_compileall_warnings,
        )

        mf, mf_err = read_manifest(_pack)
        if mf_err:
            validate_errors.append(f"manifest 不可读：{mf_err}")
        elif isinstance(mf, dict):
            if not str(mf.get("id") or "").strip():
                validate_errors.append("manifest 缺少 id")
            ec2 = mf.get("employee_config_v2")
            if isinstance(ec2, dict):
                actions = ec2.get("actions")
                if isinstance(actions, dict):
                    handlers = actions.get("handlers")
                    if not isinstance(handlers, list) or not handlers:
                        validate_warnings.append("employee_config_v2.actions.handlers 为空")
            emp = mf.get("employee")
            if not isinstance(emp, dict) or not str(emp.get("id") or "").strip():
                validate_warnings.append("manifest.employee.id 缺失")

        py_warns = mod_compileall_warnings(_pack)
        if py_warns:
            validate_errors.extend(f"Python 编译：{w}" for w in py_warns[:8])

        cons_warns = employee_pack_consistency_warnings(_pack)
        if cons_warns:
            validate_errors.extend(f"一致性：{w}" for w in cons_warns[:5])

        from modstore_server.csv_tabular_runtime import (
            is_csv_full_read,
            is_csv_generate,
            validate_csv_generate_backend,
            validate_csv_read_backend,
        )
        from modstore_server.employee_brief_utils import extract_routing_brief
        from modstore_server.excel_tabular_runtime import (
            is_excel_full_read,
            is_excel_generate,
            validate_excel_generate_backend,
            validate_excel_read_backend,
        )
        from modstore_server.txt_extract_runtime import (
            is_txt_full_read,
            is_txt_generate,
            validate_txt_generate_backend,
            validate_txt_read_backend,
        )
        from modstore_server.word_extract_runtime import (
            is_word_full_extract,
            validate_word_extract_backend,
        )
        from modstore_server.word_generate_runtime import (
            is_word_generate,
            validate_word_generate_backend,
        )

        rule_spec_path = _pack / "rule_spec.json"
        rule_kind = ""
        if rule_spec_path.is_file():
            try:
                import json as _json

                rs = _json.loads(rule_spec_path.read_text(encoding="utf-8"))
                if isinstance(rs, dict):
                    rule_kind = str(rs.get("runtime_kind") or "")
            except Exception:
                pass
        routing_brief = extract_routing_brief({"brief": brief}, fallback=brief)
        bl = routing_brief.lower()
        csv_gen_runtime = rule_kind == "csv_generate" or is_csv_generate(routing_brief)
        csv_read_runtime = rule_kind == "csv_full_read" or is_csv_full_read(routing_brief)
        excel_gen_runtime = rule_kind == "excel_generate" or is_excel_generate(routing_brief)
        excel_read_runtime = rule_kind == "excel_full_read" or is_excel_full_read(routing_brief)
        word_runtime = rule_kind == "word_full_extract" or is_word_full_extract(routing_brief)
        word_gen_runtime = rule_kind == "word_generate" or is_word_generate(routing_brief)
        txt_read_runtime = rule_kind == "txt_full_read" or is_txt_full_read(routing_brief)
        txt_gen_runtime = rule_kind == "txt_generate" or is_txt_generate(routing_brief)
        if csv_gen_runtime:
            cg_errs, cg_warns = validate_csv_generate_backend(_pack)
            if cg_errs:
                validate_errors.extend(cg_errs[:5])
            validate_warnings.extend(cg_warns[:5])
        elif excel_gen_runtime:
            eg_errs, eg_warns = validate_excel_generate_backend(_pack)
            if eg_errs:
                validate_errors.extend(eg_errs[:5])
            validate_warnings.extend(eg_warns[:5])
        elif excel_read_runtime:
            er_errs, er_warns = validate_excel_read_backend(_pack)
            if er_errs:
                validate_errors.extend(er_errs[:5])
            validate_warnings.extend(er_warns[:5])
        elif csv_read_runtime:
            cr_errs, cr_warns = validate_csv_read_backend(_pack)
            if cr_errs:
                validate_errors.extend(cr_errs[:5])
            validate_warnings.extend(cr_warns[:5])
        elif txt_gen_runtime:
            tg_errs, tg_warns = validate_txt_generate_backend(_pack)
            if tg_errs:
                validate_errors.extend(tg_errs[:5])
            validate_warnings.extend(tg_warns[:5])
        elif txt_read_runtime:
            tr_errs, tr_warns = validate_txt_read_backend(_pack)
            if tr_errs:
                validate_errors.extend(tr_errs[:5])
            validate_warnings.extend(tr_warns[:5])
        elif word_gen_runtime:
            wg_errs, wg_warns = validate_word_generate_backend(_pack)
            if wg_errs:
                validate_errors.extend(wg_errs[:5])
            validate_warnings.extend(wg_warns[:5])
        elif word_runtime:
            wx_errs, wx_warns = validate_word_extract_backend(_pack)
            validate_errors.extend(wx_errs)
            validate_warnings.extend(wx_warns)
            handlers_ok, handlers_msg = True, ""
            try:
                from modstore_server.workbench_api import _employee_handlers_contract_ok

                handlers_ok, handlers_msg = _employee_handlers_contract_ok(_pack)
            except Exception:
                pass
            if not handlers_ok and handlers_msg:
                validate_errors.append(handlers_msg)
        elif any(k in bl for k in ("word", "docx", ".doc", "txt", "文本", "文档")):
            backend = _pack / "backend"
            py_blob = ""
            if backend.is_dir():
                for py_path in backend.rglob("*.py"):
                    try:
                        py_blob += py_path.read_text(encoding="utf-8", errors="ignore").lower()
                    except Exception:
                        pass
            if not any(
                tok in py_blob for tok in ("docx", "document", "python-docx", "word", "zipfile")
            ):
                validate_warnings.append(
                    "Word/文档提取类任务：backend 中未发现 docx/文档解析相关实现，请确认生成逻辑"
                )

    return {"validate_warnings": validate_warnings, "validate_errors": validate_errors}


async def _craft_script_workflow(
    *,
    db: Any,
    user_id: int,
    session_id: str,
    brief: str,
    files: Any,
    provider: Optional[str],
    model: Optional[str],
    system_hint: Optional[str] = None,
    payload: Any = None,
    status_hook: Optional[Callable[..., Coroutine[Any, Any, Any]]] = None,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.workbench_api import _commit_script_workflow_from_result
    from modstore_server.workbench_script_runner import run_script_agent_job

    script_result = await run_script_agent_job(
        db=db,
        user_id=user_id,
        session_id=session_id,
        brief=brief,
        files=files,
        provider=provider,
        model=model,
        system_hint=system_hint,
        status_hook=status_hook,
    )
    script_wf = None
    if script_result.get("ok"):
        script_wf = _commit_script_workflow_from_result(
            db=db,
            user_id=user_id,
            session_id=session_id,
            payload=payload,
            files=files,
            result=script_result,
        )
        if script_wf is None:
            logger.warning(
                "craft_script_workflow: ok=True but commit returned None — script_len=%d errors=%s session=%s",
                len(str(script_result.get("script") or "")),
                script_result.get("errors"),
                session_id,
            )
    else:
        logger.warning(
            "craft_script_workflow: ok=False — errors=%s session=%s",
            script_result.get("errors"),
            session_id,
        )
    return {"script_result": script_result, "script_wf": script_wf}


async def _craft_embed_script(
    *,
    pack_dir: Any,
    script_wf: Any,
    brief: str,
    db: Any,
    published_to_catalog: bool = False,
    user: Any = None,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.workbench_api import (
        _embed_script_workflow_in_employee_pack,
        _refresh_employee_pack_catalog_zip,
    )

    script_attachment = _embed_script_workflow_in_employee_pack(
        pack_dir=pack_dir,
        script_workflow=script_wf,
        brief=brief,
        db=db,
    )
    saved_package = None
    if published_to_catalog and user:
        saved_package = _refresh_employee_pack_catalog_zip(db=db, user=user, pack_dir=pack_dir)
    return {"script_attachment": script_attachment, "saved_package": saved_package}


async def _craft_workflow(
    *,
    db: Any,
    user: Any,
    pack_dir: Any,
    brief: str,
    workflow_name: str,
    provider: Optional[str],
    model: Optional[str],
    published_to_catalog: bool = False,
    status_hook: Optional[Callable[..., Coroutine[Any, Any, Any]]] = None,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.mod_scaffold_runner import attach_nl_workflow_to_employee_pack_dir
    from modstore_server.workbench_api import _refresh_employee_pack_catalog_zip

    wf_attach = await attach_nl_workflow_to_employee_pack_dir(
        db=db,
        user=user,
        pack_dir=pack_dir,
        brief=brief,
        workflow_name=workflow_name,
        provider=provider,
        model=model,
        status_hook=status_hook,
    )
    saved_package = None
    if published_to_catalog:
        saved_package = _refresh_employee_pack_catalog_zip(db=db, user=user, pack_dir=pack_dir)
    return {"wf_attach": wf_attach, "saved_package": saved_package}


async def _craft_register_pack(
    *,
    db: Any,
    user: Any,
    mod_dir: Any,
    workflow_results: Any = None,
    wf_attach: Any = None,
    status_hook: Optional[Callable[..., Coroutine[Any, Any, Any]]] = None,
    industry: str = "通用",
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.mod_scaffold_runner import register_mod_employee_packs_async
    from modstore_server.pack_registration_guards import workflow_automation_block_reason

    _wf_results = workflow_results if isinstance(workflow_results, list) else []
    _wf_attach = wf_attach if isinstance(wf_attach, dict) else None
    block = workflow_automation_block_reason(
        _wf_results,
        wf_attach=_wf_attach,
        require_workflow_automation=True,
    )
    if block:
        return {
            "ok": False,
            "status": "fail",
            "summary": block[:400],
            "error": block,
            "rejected_upstream": "workflow-automator",
            "_emp_reg_result": {
                "ok": False,
                "registered": [],
                "errors": [{"stage": "upstream", "error": block}],
            },
        }

    _emp_reg_result = await register_mod_employee_packs_async(
        db=db,
        user=user,
        mod_dir=mod_dir,
        workflow_results=_wf_results,
        status_hook=status_hook,
        industry=industry,
        wf_attach=_wf_attach,
    )
    reg_ok = bool(_emp_reg_result.get("ok")) and not (_emp_reg_result.get("errors") or [])
    return {
        "ok": reg_ok,
        "status": "ok" if reg_ok else "fail",
        "summary": (
            f"已登记 {len(_emp_reg_result.get('registered') or [])} 个员工包"
            if reg_ok
            else (_emp_reg_result.get("errors") or [{}])[0].get("error", "登记失败")[:400]
        ),
        "_emp_reg_result": _emp_reg_result,
    }


async def _craft_workflow_sandbox(
    *,
    workflow_id: int,
    brief: str,
    user_id: int,
    db: Any,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.craft_failure_signals import (
        emit_craft_step_failure,
        invalid_workflow_sandbox_report,
    )
    from modstore_server.workflow_engine import run_workflow_sandbox

    try:
        wid = int(workflow_id)
    except (TypeError, ValueError):
        wid = 0
    if wid <= 0:
        report = invalid_workflow_sandbox_report(workflow_id)
        emit_craft_step_failure(
            step_id="workflow_sandbox",
            error=str(report["errors"][0]),
            user_id=int(user_id or 0),
            extra={"workflow_id": workflow_id, "sandbox_report": report},
        )
        return {"report": report, "ok": False, "status": "fail", "summary": report["summary"]}

    report = run_workflow_sandbox(
        wid,
        {},
        mock_employees=True,
        validate_only=True,
        user_id=user_id,
    )
    return {"report": report}


async def _craft_mod_sandbox(
    *,
    pack_dir: Any,
    wf_attach: Any = None,
    user_id: int = 0,
    db: Any = None,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.mod_scaffold_runner import (
        employee_pack_consistency_warnings,
        run_employee_pack_code_validation_report,
    )

    mod_checks: List[Dict[str, Any]] = []
    _pack = Path(str(pack_dir)) if not isinstance(pack_dir, Path) else pack_dir

    validation_report = await run_employee_pack_code_validation_report(
        _pack,
        db=db,
        xcemp_timeout_seconds=20.0,
    )
    mv = (
        validation_report.get("manifest_validation")
        if isinstance(validation_report.get("manifest_validation"), dict)
        else {}
    )
    pc = (
        validation_report.get("python_compile")
        if isinstance(validation_report.get("python_compile"), dict)
        else {}
    )
    cc = (
        validation_report.get("consistency_check")
        if isinstance(validation_report.get("consistency_check"), dict)
        else {}
    )
    xv = (
        validation_report.get("xcemp_validation")
        if isinstance(validation_report.get("xcemp_validation"), dict)
        else {}
    )

    mod_checks.append(
        {
            "id": "manifest_validation",
            "ok": mv.get("status") == "ok",
            "message": "；".join(mv.get("errors") or [])[:800] or "manifest 校验通过",
        },
    )
    mod_checks.append(
        {
            "id": "python_compile",
            "ok": pc.get("status") in ("ok", "skipped"),
            "message": "；".join(pc.get("errors") or [])[:800]
            or (
                "；".join(pc.get("warnings") or [])[:400]
                if pc.get("warnings")
                else "Python 编译通过"
            ),
        },
    )
    _cc_msg_parts: List[str] = []
    if cc.get("missing_depends"):
        _cc_msg_parts.append("depends_on 未注册: " + ", ".join(cc["missing_depends"][:6]))
    if cc.get("missing_skills"):
        _cc_msg_parts.append("skills 缺失: " + ", ".join(cc["missing_skills"][:6]))
    if cc.get("warnings"):
        _cc_msg_parts.append("；".join(str(w) for w in cc["warnings"][:4])[:400])
    mod_checks.append(
        {
            "id": "consistency_check",
            "ok": cc.get("status") in ("ok", "skipped"),
            "message": "；".join(_cc_msg_parts)[:1200] if _cc_msg_parts else "一致性校验通过",
        },
    )
    mod_checks.append(
        {
            "id": "xcemp_validation",
            "ok": xv.get("status") in ("ok", "skipped"),
            "message": "；".join(xv.get("errors") or [])[:800] or "xcemp validate 通过",
        },
    )

    if _pack.is_dir():
        cons_warns = employee_pack_consistency_warnings(_pack)
        if cons_warns and cc.get("status") == "ok":
            mod_checks.append(
                {
                    "id": "employee_pack_consistency",
                    "ok": False,
                    "message": "；".join(cons_warns)[:1200],
                },
            )
        try:
            from modstore_server.workbench_api import _check_vibe_coding_capability

            vibe_checks = _check_vibe_coding_capability(_pack, wf_attach or {})
            mod_checks.extend(vibe_checks)
        except Exception as vibe_exc:
            logger.warning("vibe-coding capability check failed: %s", vibe_exc)
            mod_checks.append(
                {"id": "vibe_check", "ok": False, "message": f"vibe-coding 检查异常: {vibe_exc!s}"},
            )

    core_ok = validation_report.get("status") == "ok"
    emp_mod_sandbox = {
        "ok": core_ok and all(c.get("ok") for c in mod_checks if c.get("id") != "vibe_check"),
        "checks": mod_checks,
        "validation_report": validation_report,
        "note": "员工包四阶段校验（manifest / Python / 一致性 / xcemp）",
    }

    if xv.get("escalate_to_human"):
        from modstore_server.craft_failure_signals import emit_craft_step_failure

        _xv_errs = xv.get("errors") if isinstance(xv.get("errors"), list) else []
        _xv_err = str(
            xv.get("timeout_log") or (_xv_errs[0] if _xv_errs else "xcemp validate 超时")
        )[:500]
        emit_craft_step_failure(
            step_id="mod_sandbox",
            error=_xv_err,
            employee_id="code-validator",
            user_id=int(user_id or 0),
            extra={
                "escalate_to_human": True,
                "package_hash": xv.get("package_hash"),
                "validation_report": validation_report,
            },
        )

    _all_pass = emp_mod_sandbox["ok"]
    _vibe_gaps = [c for c in mod_checks if not c.get("ok") and "vibe" in str(c.get("id") or "")]
    mod_sb_msg = str(validation_report.get("summary") or "")
    if _all_pass:
        mod_sb_msg = mod_sb_msg or "包体四阶段校验通过"
    elif _vibe_gaps and core_ok:
        mod_sb_msg = (
            mod_sb_msg
            + "；vibe-coding 能力存在缺口："
            + "；".join(c.get("message", "") for c in _vibe_gaps)
        )[:480]
    elif not mod_sb_msg:
        mod_sb_msg = "包体校验未通过，见 validation_report"

    return {
        "emp_mod_sandbox": emp_mod_sandbox,
        "mod_sb_msg": mod_sb_msg,
        "report": validation_report,
    }


async def _craft_standalone_smoke(
    *,
    res: Any = None,
    pack_dir: Any = None,
    user_id: int = 0,
    **_kw: Any,
) -> Dict[str, Any]:
    from modman.manifest_util import read_manifest

    _pack = Path(str(pack_dir)) if pack_dir and not isinstance(pack_dir, Path) else pack_dir
    _standalone_smoke_ok = False
    _standalone_smoke_skipped = False
    _standalone_smoke_msg = "跳过（未能获取包字节）"

    try:
        from modstore_server.employee_pack_export import (
            _build_employee_pack_zip_with_source,
            collect_vendor_modules_from_pack,
        )

        _sm_manifest = res.get("manifest") if isinstance(res, dict) else None
        if not _sm_manifest and _pack and _pack.is_dir():
            _mf_disk, _mf_disk_err = read_manifest(_pack)
            if not _mf_disk_err:
                _sm_manifest = _mf_disk
        if _sm_manifest and isinstance(_sm_manifest, dict):
            _sm_pid = str(_sm_manifest.get("id") or "employee-pack").strip() or "employee-pack"
            _sm_vendor_modules_first = (
                collect_vendor_modules_from_pack(_pack) if _pack and _pack.is_dir() else None
            )
            _sm_zip_bytes = _build_employee_pack_zip_with_source(
                _sm_pid, _sm_manifest, None, vendor_modules=_sm_vendor_modules_first
            )
            with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as _tf:
                _tf.write(_sm_zip_bytes)
                _tmp_xcemp = _tf.name
            try:
                _proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        sys.executable,
                        _tmp_xcemp,
                        "validate",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    ),
                    timeout=20,
                )
                _stdout, _stderr = await asyncio.wait_for(_proc.communicate(), timeout=20)
                if _proc.returncode == 0:
                    _standalone_smoke_ok = True
                    _standalone_smoke_msg = f"独立运行 OK — python {_sm_pid}.xcemp validate 通过 ✅"
                else:
                    _out_text = (_stderr or _stdout or b"").decode("utf-8", errors="replace")[:300]
                    _standalone_smoke_msg = (
                        f"validate 失败（退出码 {_proc.returncode}）：{_out_text}"
                    )

                    if _pack and _pack.is_dir() and _sm_manifest:
                        _repair_msg = await _standalone_smoke_auto_repair(
                            _pack,
                            _sm_manifest,
                            _sm_pid,
                            _sm_vendor_modules_first,
                        )
                        _standalone_smoke_msg = _repair_msg
                        if "成功" in _repair_msg or "✅" in _repair_msg:
                            _standalone_smoke_ok = True
            except Exception as _se:
                _standalone_smoke_msg = (
                    f"⚠️ 自检子进程异常：{_se}；建议手动运行 python xxx.xcemp validate 排查"
                )
            finally:
                try:
                    os.unlink(_tmp_xcemp)
                except Exception:
                    pass
        else:
            _standalone_smoke_msg = "manifest 尚未生成，独立自检跳过"
            _standalone_smoke_ok = True
            _standalone_smoke_skipped = True
    except Exception as _smoke_exc:
        _standalone_smoke_msg = f"⚠️ 独立自检异常：{_smoke_exc}；建议手动验证 .xcemp 包完整性"

    if not _standalone_smoke_ok:
        _standalone_smoke_msg = "⚠️ " + _standalone_smoke_msg.lstrip("⚠️ ")

    return {
        "standalone_smoke_ok": _standalone_smoke_ok,
        "standalone_smoke_msg": _standalone_smoke_msg,
        "standalone_smoke_skipped": _standalone_smoke_skipped,
    }


async def _standalone_smoke_auto_repair(
    pack_dir: Path,
    manifest: Dict[str, Any],
    pack_id: str,
    vendor_modules: Optional[Dict[str, str]] = None,
) -> str:
    from modstore_server.employee_pack_export import (
        _build_employee_pack_zip_with_source,
        collect_vendor_modules_from_pack,
    )

    try:
        await asyncio.sleep(0)
        from modstore_server.employee_pack_blueprints_template import (
            render_employee_pack_blueprints_py,
            render_employee_pack_employee_py,
        )
        from modstore_server.mod_employee_impl_scaffold import sanitize_employee_stem

        _sm_emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
        _sm_eid = pack_id
        _sm_stem = sanitize_employee_stem(_sm_eid)
        _sm_label = str(_sm_emp.get("label") or _sm_eid).strip()

        _bp_content = render_employee_pack_blueprints_py(
            pack_id=pack_id,
            employee_id=_sm_eid,
            stem=_sm_stem,
            label=_sm_label,
        )

        _sm_v2 = (
            manifest.get("employee_config_v2")
            if isinstance(manifest.get("employee_config_v2"), dict)
            else {}
        )
        _sm_actions = _sm_v2.get("actions") if isinstance(_sm_v2.get("actions"), dict) else {}
        _sm_handlers = (
            _sm_actions.get("handlers") if isinstance(_sm_actions.get("handlers"), list) else []
        )
        _is_direct_python = "direct_python" in _sm_handlers

        if _is_direct_python:
            from modstore_server.employee_asset_pipeline import render_direct_python_asset_worker

            _rule_spec_path = pack_dir / "rule_spec.json"
            _sm_rule_spec = {}
            if _rule_spec_path.is_file():
                try:
                    _sm_rule_spec = json.loads(_rule_spec_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            _runtime_mod = re.sub(r"[^a-z0-9_]+", "_", (_sm_eid or pack_id).lower()).strip("_")
            if _runtime_mod.endswith("_employee"):
                _runtime_mod = _runtime_mod[: -len("_employee")] or _runtime_mod
            _emp_content = render_direct_python_asset_worker(
                employee_id=_sm_eid,
                label=_sm_label,
                runtime_module=_runtime_mod,
                rule_spec=_sm_rule_spec,
            )
        else:
            _emp_content = render_employee_pack_employee_py(
                employee_id=_sm_eid,
                stem=_sm_stem,
                label=_sm_label,
            )

        _bp_path = pack_dir / "backend" / "blueprints.py"
        _emp_path = pack_dir / "backend" / "employees" / f"{_sm_stem}.py"
        if _bp_path.parent.is_dir():
            _bp_path.write_text(_bp_content, encoding="utf-8")
        if _emp_path.parent.is_dir():
            _emp_path.write_text(_emp_content, encoding="utf-8")

        _sm_vendor_modules = (
            collect_vendor_modules_from_pack(pack_dir)
            if _is_direct_python and pack_dir.is_dir()
            else None
        )

        _sm_zip_bytes = _build_employee_pack_zip_with_source(
            pack_id, manifest, None, vendor_modules=_sm_vendor_modules
        )
        with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as _tf2:
            _tf2.write(_sm_zip_bytes)
            _tmp_xcemp2 = _tf2.name
        try:
            _proc2 = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    _tmp_xcemp2,
                    "validate",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=20,
            )
            _stdout2, _stderr2 = await asyncio.wait_for(_proc2.communicate(), timeout=20)
            if _proc2.returncode == 0:
                return "自检失败后自动修复成功 ✅ — 已重新生成 backend 代码并通过 validate"
            else:
                _out_text2 = (_stderr2 or _stdout2 or b"").decode("utf-8", errors="replace")[:200]
                return f"⚠️ 自动修复后仍失败：{_out_text2}；建议手动检查 run() 函数"
        finally:
            try:
                os.unlink(_tmp_xcemp2)
            except Exception:
                pass
    except Exception as _repair_exc:
        return f"⚠️ 自动修复异常：{_repair_exc}；建议手动检查 backend/employees/*.py"


async def _craft_host_check(
    *,
    fhd_base: str,
    user_id: int = 0,
    **_kw: Any,
) -> Dict[str, Any]:
    host_probe: Dict[str, Any] = {"skipped": True}
    host_check_msg = "未配置 fhd_base_url，已跳过；如需部署到宿主，请在环境变量或配置中设置 FHD_BASE_URL 后重新运行连通性检查"

    if not fhd_base:
        return {"host_probe": host_probe, "host_check_msg": host_check_msg}

    try:
        from modstore_server.infrastructure.http_clients import get_external_client

        base = fhd_base.rstrip("/")
        host_warnings: List[str] = []
        client = get_external_client()
        r = await client.get(f"{base}/api/mods/", timeout=10.0)
        host_probe = {
            "skipped": False,
            "ok": r.status_code < 500,
            "status_code": r.status_code,
            "url": f"{base}/api/mods/",
        }
        try:
            lr = await client.get(f"{base}/api/mods/llm-status")
            if lr.status_code == 200:
                try:
                    lj = lr.json()
                    if isinstance(lj, dict) and lj.get("api_key_configured") is False:
                        host_warnings.append(
                            "宿主返回 llm-status：未配置 LLM API Key，员工运行时可能无法调用模型"
                        )
                except Exception:
                    host_warnings.append("llm-status 返回非 JSON，跳过密钥探测")
            elif lr.status_code == 404:
                host_warnings.append(
                    "宿主未提供 /api/mods/llm-status（可选），无法在编排阶段探测 LLM 密钥"
                )
        except Exception:
            host_warnings.append("无法请求宿主 /api/mods/llm-status（可选端点）")

        try:
            vr = await client.get(f"{base}/api/version")
            if vr.status_code == 200:
                try:
                    vj = vr.json()
                    if isinstance(vj, dict) and vj.get("min_mod_sdk_version"):
                        host_probe["host_min_mod_sdk_version"] = str(
                            vj.get("min_mod_sdk_version") or ""
                        )
                except Exception:
                    pass
        except Exception:
            pass

        msg = f"HTTP {r.status_code}" if host_probe.get("ok") else f"HTTP {r.status_code}（异常）"
        if host_warnings:
            msg += "；" + "；".join(host_warnings[:3])[:400]
            host_probe["warnings"] = host_warnings
        host_check_msg = msg[:480]
    except Exception as e:
        host_probe = {"skipped": False, "ok": False, "error": str(e)[:300]}
        host_check_msg = f"探测失败: {e!s}"[:300]

    return {"host_probe": host_probe, "host_check_msg": host_check_msg}


async def _craft_six_dim_gate(
    *,
    pack_dir: Any = None,
    pipeline_label: str = "",
    routing_brief: str = "",
    structured_requirement: Any = None,
    spec_warnings: Any = None,
    validate_errors: Any = None,
    mod_sandbox: Any = None,
    workflow_sandbox: Any = None,
    workflow_biz_ok: Any = None,
    standalone_smoke_ok: bool = True,
    catalog_registered: bool = True,
    employee_target: str = "pack_only",
    asset_count: int = 0,
    domain_smoke: Any = None,
    golden_comparison: Any = None,
    runtime_generation: Any = None,
    target_employee_id: str = "",
    user_id: int = 0,
    **_kw: Any,
) -> Dict[str, Any]:
    from modstore_server.employee_six_dimension import compute_six_dimension_report
    from modstore_server.employee_six_dimension_llm import enrich_six_dimension_report_with_llm

    _pack = Path(str(pack_dir)) if pack_dir and not isinstance(pack_dir, Path) else pack_dir
    _pack_path = _pack or Path(".")
    report = compute_six_dimension_report(
        pack_dir=_pack_path,
        pipeline_label=pipeline_label or "",
        routing_brief=routing_brief or "",
        structured_requirement=(
            structured_requirement if isinstance(structured_requirement, dict) else None
        ),
        spec_warnings=spec_warnings if isinstance(spec_warnings, list) else None,
        validate_errors=validate_errors if isinstance(validate_errors, list) else None,
        mod_sandbox=mod_sandbox if isinstance(mod_sandbox, dict) else None,
        workflow_sandbox=workflow_sandbox if isinstance(workflow_sandbox, dict) else None,
        workflow_biz_ok=workflow_biz_ok,
        standalone_smoke_ok=bool(standalone_smoke_ok),
        catalog_registered=bool(catalog_registered),
        employee_target=employee_target or "pack_only",
        asset_count=int(asset_count or 0),
        domain_smoke=domain_smoke if isinstance(domain_smoke, dict) else None,
        golden_comparison=golden_comparison if isinstance(golden_comparison, dict) else None,
        runtime_generation=runtime_generation if isinstance(runtime_generation, dict) else None,
    )
    eid = (target_employee_id or _kw.get("employee_id") or "").strip()
    if not eid and _pack_path.is_dir():
        try:
            mf = json.loads((_pack_path / "manifest.json").read_text(encoding="utf-8"))
            eid = str(mf.get("id") or (mf.get("identity") or {}).get("id") or "").strip()
        except Exception:  # noqa: BLE001
            eid = ""
    llm_report, llm_meta = await enrich_six_dimension_report_with_llm(
        report,
        pack_dir=_pack_path,
        target_employee_id=eid or "unknown",
        pipeline_label=pipeline_label or report.get("pipeline_label") or "",
        routing_brief=routing_brief or "",
        validate_errors=validate_errors if isinstance(validate_errors, list) else None,
        mod_sandbox=mod_sandbox if isinstance(mod_sandbox, dict) else None,
        user_id=int(user_id or 0),
    )
    return {"six_dimension_report": llm_report, "six_dimension_llm_meta": llm_meta}


def register_all_craft_steps() -> None:
    register_craft_step("spec", _craft_spec)
    register_craft_step("employee_plan", _craft_employee_plan)
    register_craft_step("generate", _craft_generate)
    register_craft_step("validate", _craft_validate)
    register_craft_step("script_workflow", _craft_script_workflow)
    register_craft_step("embed_script", _craft_embed_script)
    register_craft_step("workflow", _craft_workflow)
    register_craft_step("register_pack", _craft_register_pack)
    register_craft_step("workflow_sandbox", _craft_workflow_sandbox)
    register_craft_step("mod_sandbox", _craft_mod_sandbox)
    register_craft_step("standalone_smoke", _craft_standalone_smoke)
    register_craft_step("host_check", _craft_host_check)
    register_craft_step("six_dim_gate", _craft_six_dim_gate)
