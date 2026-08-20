# mypy: disable-error-code="arg-type, attr-defined, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.craft_steps")


async def _craft_spec(
    *,
    db: _facade().Any,
    user_id: int,
    payload: _facade().Any,
    brief: str,
    prov: _facade().Optional[str],
    mdl: _facade().Optional[str],
    routing_brief: _facade().Optional[str] = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
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

    spec_warnings: _facade().List[str] = []
    brief_domain_hints: _facade().List[str] = []
    structured_requirement: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
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
    for _kw, _domain in _facade()._SPEC_DOMAIN_KEYWORDS.items():
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
            "TXT 生成：runtime_kind=txt_generate；handlers=direct_python+agent；输出 document_parsed.json + generated_document.txt"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif is_txt_full_read(rb):
        structured_requirement = txt_read_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "TXT 全量读取：runtime_kind=txt_full_read；handlers=direct_python；输出 document_full.txt + document_meta.json"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif is_pdf_generate(rb):
        structured_requirement = pdf_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "PDF 生成：runtime_kind=pdf_generate；handlers=direct_python+agent；JSON 中介 → outputs/generated_document.pdf"
        )
    elif is_pdf_full_read(rb):
        structured_requirement = pdf_read_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "PDF 全量读取：runtime_kind=pdf_full_read；handlers=direct_python；原生文字 + 图片分类 + VLM sidecar"
        )
    elif is_word_full_extract(rb):
        structured_requirement = word_extract_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "Word 全量提取：runtime_kind=word_full_extract；handlers=direct_python；输出 document_full.json + document_full.txt + images/"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif is_word_generate(rb):
        structured_requirement = word_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "Word 生成：runtime_kind=word_generate；handlers=direct_python（+可选 agent）；JSON 中介 + 可选 template.docx → generated_document.docx"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif rb and len(rb) >= 10 and prov and mdl:
        from modstore_server.employee_pipeline_routing import (
            is_ambiguous_employee_brief,
        )

        if is_ambiguous_employee_brief(rb):
            try:
                _req_api_key, _ = resolve_api_key(db, user_id, prov)
                _req_prompt = f'请从以下用户需求中提取结构化信息，只输出 JSON，不要 markdown 围栏：\n{{"domain":"业务领域","goal":"员工要达成的目标","input":"员工接收什么输入","output":"员工输出什么","constraints":["约束1","约束2"],"suggested_capabilities":["cap1","cap2"],"suggested_handlers":["llm_md"]}}\n\n用户需求：{rb}'
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
                    _req_raw = _facade().re.sub(
                        "^```(?:json)?\\s*",
                        "",
                        (_req_result.get("content") or "").strip(),
                        flags=_facade().re.I,
                    )
                    _req_raw = _facade().re.sub("\\s*```\\s*$", "", _req_raw).strip()
                    _parsed_req = _facade().json.loads(_req_raw)
                    if isinstance(_parsed_req, dict):
                        structured_requirement = _parsed_req
                        _extracted_domain = str(_parsed_req.get("domain") or "").strip()
                        if _extracted_domain and _extracted_domain not in brief_domain_hints:
                            brief_domain_hints.append(_extracted_domain)
                        _extracted_caps = _parsed_req.get("suggested_capabilities")
                        if isinstance(_extracted_caps, list) and _extracted_caps:
                            spec_warnings.append(
                                f"LLM 建议能力：{'、'.join((str(c) for c in _extracted_caps[:4]))}"
                            )
            except RECOVERABLE_ERRORS:
                _facade().logger.debug(
                    "LLM structured requirement extraction failed", exc_info=True
                )
    if not structured_requirement and rb:
        bl = rb.lower()
        structured_requirement = {
            "domain": brief_domain_hints[0] if brief_domain_hints else "通用",
            "goal": rb.strip().splitlines()[0][:200],
            "input": (
                "Word/文档" if any((k in bl for k in ("word", "docx", "文档"))) else "用户输入"
            ),
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
    db: _facade().Any,
    user_id: int,
    payload: _facade().Any,
    prov: _facade().Optional[str],
    mdl: _facade().Optional[str],
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workbench_api import _build_employee_orchestration_plan

    employee_plan = await _build_employee_orchestration_plan(
        db=db, user_id=user_id, payload=payload, provider=prov, model=mdl
    )
    return {"employee_plan": employee_plan}


async def _craft_generate(
    *,
    db: _facade().Any,
    user: _facade().Any,
    session_id: str,
    brief: str,
    raw_files: _facade().Any,
    replace: bool,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    use_word_extract: bool = False,
    payload: _facade().Any = None,
    employee_plan: _facade().Any = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.artifact_generator_blueprint import (
        artifact_generator_preflight,
    )
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
