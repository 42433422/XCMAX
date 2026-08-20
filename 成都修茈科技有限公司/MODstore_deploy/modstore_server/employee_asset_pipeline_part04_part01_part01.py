# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def reconcile_employee_pack_manifest(
    pack_dir: _facade().Path, *, brief: str = ""
) -> _facade().Dict[str, _facade().Any]:
    """Re-apply rule_spec + _normalize_manifest after workflow/register edits."""
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        raise FileNotFoundError(f"manifest.json missing under {pack_dir}")
    raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
    rule_spec: _facade().Dict[str, _facade().Any] = {}
    rs_path = pack_dir / "rule_spec.json"
    if rs_path.is_file():
        try:
            loaded = _facade().json.loads(rs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                rule_spec = loaded
        except (OSError, _facade().json.JSONDecodeError):
            pass
    if not rule_spec:
        from modstore_server.csv_tabular_runtime import (
            build_csv_generate_rule_spec,
            build_csv_read_rule_spec,
            is_csv_full_read,
            is_csv_generate,
        )
        from modstore_server.employee_brief_utils import extract_routing_brief
        from modstore_server.excel_tabular_runtime import (
            build_excel_generate_rule_spec,
            build_excel_read_rule_spec,
            is_excel_full_read,
            is_excel_generate,
        )
        from modstore_server.pdf_extract_runtime import (
            build_pdf_generate_rule_spec,
            build_pdf_read_rule_spec,
            is_pdf_full_read,
            is_pdf_generate,
        )
        from modstore_server.txt_extract_runtime import (
            build_txt_generate_rule_spec,
            build_txt_read_rule_spec,
            is_txt_full_read,
            is_txt_generate,
        )
        from modstore_server.word_extract_runtime import (
            build_word_extract_rule_spec,
            is_word_full_extract,
        )
        from modstore_server.word_generate_runtime import (
            build_word_generate_rule_spec,
            is_word_generate,
        )

        rb = extract_routing_brief({"brief": brief}, fallback=brief)
        if is_csv_generate(rb):
            rule_spec = build_csv_generate_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_csv_full_read(rb):
            rule_spec = build_csv_read_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_excel_generate(rb):
            rule_spec = build_excel_generate_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_excel_full_read(rb):
            rule_spec = build_excel_read_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_pdf_generate(rb):
            rule_spec = build_pdf_generate_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_pdf_full_read(rb):
            rule_spec = build_pdf_read_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif _facade().is_json_quant_report(rb):
            rule_spec = _facade().build_json_quant_report_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif _facade().is_ppt_generate(rb):
            from modstore_server.ppt_extract_runtime import build_ppt_generate_rule_spec

            rule_spec = build_ppt_generate_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif _facade().is_ppt_full_read(rb):
            from modstore_server.ppt_extract_runtime import build_ppt_read_rule_spec

            rule_spec = build_ppt_read_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_txt_generate(rb):
            rule_spec = build_txt_generate_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_txt_full_read(rb):
            rule_spec = build_txt_read_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_word_generate(rb):
            rule_spec = build_word_generate_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif is_word_full_extract(rb):
            rule_spec = build_word_extract_rule_spec(rb)
            rs_path.write_text(
                _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    rb = brief
    if not rb:
        from modstore_server.employee_brief_utils import extract_routing_brief

        rb = extract_routing_brief(
            {"brief": str(raw.get("description") or "")},
            fallback=str(raw.get("description") or ""),
        )
    if rule_spec:
        aligned = _facade()._normalize_manifest(raw, rb, rule_spec)
    else:
        aligned = dict(raw)
    _facade()._sanitize_workflow_bundles(aligned)
    mf_path.write_text(
        _facade().json.dumps(aligned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return aligned


async def enrich_manifest_productivity_fields(
    db: _facade().Any,
    user: _facade().User,
    *,
    brief: str,
    rule_spec: _facade().Dict[str, _facade().Any],
    base_manifest: _facade().Dict[str, _facade().Any],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Dict[str, _facade().Any], _facade().Dict[str, _facade().Any]]:
    """轻量 LLM：仅补 description / panel_summary / behavior_rules，与模板落盘并行，不阻塞 convert。"""
    from modstore_server.employee_pipeline_routing import (
        is_direct_python_template_runtime,
    )

    runtime_kind = str(rule_spec.get("runtime_kind") or "")
    if not is_direct_python_template_runtime(runtime_kind):
        return (base_manifest, {"source": "skipped", "reason": "not_template_runtime"})
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return (base_manifest, {"source": "fallback", "warning": err})
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return (base_manifest, {"source": "fallback", "warning": "missing api key"})
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    system = "你是员工包文案助手。只输出 JSON，不要 markdown。字段：description（1-3句）、panel_summary（工作台卡片一句话）、behavior_rules（字符串数组，3-6条操作边界）。不得改写 runtime_kind、handlers 或技术契约；禁止编造已执行结果。"
    user_msg = _facade().json.dumps(
        {
            "brief": brief[:4000],
            "runtime_kind": runtime_kind,
            "name": base_manifest.get("name"),
        },
        ensure_ascii=False,
    )
    try:
        result = await _facade().chat_dispatch(
            prov,
            api_key=api_key,
            base_url=base,
            model=mdl,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=900,
        )
    except RECOVERABLE_ERRORS:
        return (
            base_manifest,
            {"source": "fallback", "warning": "enrich dispatch failed"},
        )
    if not result.get("ok"):
        return (
            base_manifest,
            {"source": "fallback", "warning": str(result.get("error") or "")},
        )
    try:
        raw = str(result.get("content") or "").strip()
        raw = _facade().re.sub("^```(?:json)?\\s*", "", raw, flags=_facade().re.I)
        raw = _facade().re.sub("\\s*```\\s*$", "", raw).strip()
        patch = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError:
        return (base_manifest, {"source": "fallback", "warning": "enrich parse failed"})
    if not isinstance(patch, dict):
        return (base_manifest, {"source": "fallback", "warning": "enrich not object"})
    out = dict(base_manifest)
    desc = str(patch.get("description") or "").strip()
    if desc:
        out["description"] = desc[:2000]
    panel = str(patch.get("panel_summary") or "").strip()
    if panel:
        out["panel_summary"] = panel[:500]
    rules = patch.get("behavior_rules")
    if isinstance(rules, list):
        cleaned = [str(x).strip() for x in rules if str(x).strip()][:8]
        if cleaned:
            v2 = out.get("employee_config_v2")
            if not isinstance(v2, dict):
                v2 = {}
                out["employee_config_v2"] = v2
            v2["behavior_rules"] = cleaned
    return (out, {"provider": prov, "model": mdl, "source": "productivity_enrich"})


async def design_asset_employee_manifest(
    db: _facade().Any,
    user: _facade().User,
    *,
    brief: str,
    rule_spec: _facade().Dict[str, _facade().Any],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Dict[str, _facade().Any], _facade().Dict[str, _facade().Any]]:
    from modstore_server.employee_pipeline_routing import (
        is_direct_python_template_runtime,
    )

    runtime_kind = str(rule_spec.get("runtime_kind") or "")
    if is_direct_python_template_runtime(runtime_kind):
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": "", "model": "", "source": "template_manifest"},
        )
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err and runtime_kind not in (
        "word_full_extract",
        "word_generate",
        "txt_full_read",
        "txt_generate",
        "pdf_full_read",
        "pdf_generate",
        "csv_full_read",
        "csv_generate",
        "excel_full_read",
        "excel_generate",
    ):
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": "", "model": "", "warning": err},
        )
    if runtime_kind in (
        "word_full_extract",
        "word_generate",
        "txt_full_read",
        "txt_generate",
        "pdf_full_read",
        "pdf_generate",
        "csv_full_read",
        "csv_generate",
        "excel_full_read",
        "excel_generate",
    ) and (err or not _facade().resolve_api_key(db, user.id, prov or "")[0]):
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {
                "provider": prov or "",
                "model": mdl or "",
                "warning": err or "missing api key",
            },
        )
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": prov, "model": mdl, "warning": "missing api key"},
        )
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    runtime_kind = rule_spec.get("runtime_kind") or "generic_excel_transform"
    _is_doc_review = runtime_kind in ("contract_doc_review", "doc_template_transform")
    if _is_doc_review:
        system = '你是 employee_pack manifest 设计器。只输出 JSON，不输出 Markdown。这个员工是文档审核/处理员工，需要 LLM 推理能力，actions.handlers 必须只有 ["agent"]。不要声明 echo、llm_md、direct_python。不要编造已经执行。cognition.agent.system_prompt 应包含文档审核的专业指令。'
    else:
        system = '你是 employee_pack manifest 设计器。只输出 JSON，不输出 Markdown。这个员工必须是 direct_python 文件处理员工，actions.handlers 必须只有 ["direct_python"]。不要声明 echo、llm_md。不要编造已经执行。'
        if runtime_kind == "word_full_extract":
            system += " rule_spec.runtime_kind 为 word_full_extract：perception.accepted_extensions 必须含 .docx；默认输出为 outputs/document_full.json（读取/提取，不是生成 docx）；capabilities 须含 doc.full_extract；禁止写成 Word 生成或仅接受 .json 的员工。"
    user_msg = _facade().json.dumps({"brief": brief, "rule_spec": rule_spec}, ensure_ascii=False)[
        :12000
    ]
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4000,
    )
    if not result.get("ok"):
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": prov, "model": mdl, "warning": str(result.get("error") or "")},
        )
    parsed, perr = _facade().parse_employee_pack_llm_json(str(result.get("content") or ""))
    if perr or not parsed:
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": prov, "model": mdl, "warning": perr or "parse failed"},
        )
    return (
        _facade()._normalize_manifest(parsed, brief, rule_spec),
        {"provider": prov, "model": mdl},
    )


def _rule_spec_python_literal(rule_spec: _facade().Dict[str, _facade().Any]) -> str:
    """Embed rule_spec as valid Python dict literal (json.dumps uses true/false/null)."""
    raw = _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2)
    return raw.replace(": true", ": True").replace(": false", ": False").replace(": null", ": None")


def render_direct_python_asset_worker(
    *,
    employee_id: str,
    label: str,
    runtime_module: str,
    rule_spec: _facade().Dict[str, _facade().Any],
) -> str:
    prompt = f"你是{label}。你必须按 direct_python 方式处理真实文件，读取 payload 中的 file_path/path/excel_path，必要时使用打包模板，成功条件是实际写出输出文件。任何输入缺失、模板缺失、转换模块异常都要返回明确错误，禁止编造已完成。"
    rule_spec_lit = _facade()._rule_spec_python_literal(rule_spec)
    return f'"""Generated direct_python employee entrypoint."""\nfrom __future__ import annotations\n\nimport asyncio\nimport json\nfrom pathlib import Path\nfrom typing import Any, Dict, List, Optional\nimport sys\n\nEMPLOYEE_ID = {_facade().json.dumps(employee_id, ensure_ascii=False)}\nEMPLOYEE_LABEL = {_facade().json.dumps(label, ensure_ascii=False)}\nSYSTEM_PROMPT = {_facade().json.dumps(prompt, ensure_ascii=False)}\nRULE_SPEC = {rule_spec_lit}\n\n\ndef _ok(data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n    return {{"ok": True, "summary": _summary(data), "items": data if isinstance(data, list) else [data], "warnings": list(warnings or []), "error": "", "meta": dict(meta or {{}})}}\n\n\ndef _err(msg: str, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n    return {{"ok": False, "summary": msg[:400], "items": [], "warnings": list(warnings or []), "error": msg[:1000], "meta": dict(meta or {{}})}}\n\n\ndef _summary(data: Any) -> str:\n    if isinstance(data, str):\n        return data[:4000]\n    try:\n        return json.dumps(data, ensure_ascii=False)[:4000]\n    except TypeError:\n        return str(data)[:4000]\n\n\ndef _pack_root() -> Path:\n    return Path(__file__).resolve().parents[1]\n\n\ndef _workspace_root(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:\n    raw = payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd()\n    return Path(str(raw)).expanduser()\n\n\ndef _resolve_input(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:\n    raw = str(payload.get("file_path") or payload.get("path") or payload.get("excel_path") or "").strip()\n    if not raw:\n        raise FileNotFoundError("缺少 file_path：请上传或指定要处理的文件。")\n    p = Path(raw).expanduser()\n    if not p.is_absolute():\n        p = _workspace_root(ctx, payload) / raw\n    if not p.is_file():\n        raise FileNotFoundError(f"文件不存在：{{p}}")\n    return p\n\n\ndef _resolve_output(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:\n    rel = str(payload.get("output_relpath") or RULE_SPEC.get("default_output_relpath") or "outputs/employee_output.xlsx").strip()\n    p = Path(rel).expanduser()\n    if not p.is_absolute():\n        p = _workspace_root(ctx, payload) / rel\n    p.parent.mkdir(parents=True, exist_ok=True)\n    return p\n\n\ndef _resolve_template(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Path]:\n    raw = str(\n        payload.get("template_relpath")\n        or RULE_SPEC.get("default_template_relpath")\n        or RULE_SPEC.get("template_relpath")\n        or ""\n    ).strip()\n    if not raw:\n        return None\n    candidates = []\n    p = Path(raw).expanduser()\n    if p.is_absolute():\n        candidates.append(p)\n    else:\n        candidates.append(_workspace_root(ctx, payload) / raw)\n        candidates.append(_pack_root() / raw)\n        candidates.append(_pack_root() / "backend" / "templates" / raw)\n        if raw.startswith("backend/"):\n            candidates.append(_pack_root() / raw[len("backend/"):])\n    for cand in candidates:\n        if cand.is_file():\n            return cand\n    bundled_templates = sorted((_pack_root() / "templates").rglob("*.xls*")) if (_pack_root() / "templates").is_dir() else []\n    if bundled_templates:\n        return bundled_templates[0]\n    return None\n\n\nasync def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:\n    payload = dict(payload or {{}})\n    ctx = dict(ctx or {{}})\n    action = str(payload.get("action") or RULE_SPEC.get("default_action") or "convert").strip().lower()\n    if action in ("help", "说明", "status"):\n        return _ok({{"employee": EMPLOYEE_LABEL, "rule_spec": RULE_SPEC}}, meta={{"handler": "direct_python", "action": "help"}})\n    if action not in ("convert", "upload", "转换", ""):\n        return _err(f"不支持的 action：{{action}}", meta={{"handler": "direct_python", "action": action}})\n    try:\n        vendor_dir = _pack_root() / "vendor"\n        if str(vendor_dir) not in sys.path:\n            sys.path.insert(0, str(vendor_dir))\n        from {runtime_module}.convert import convert_file\n        src = _resolve_input(payload, ctx)\n        out = _resolve_output(payload, ctx)\n        template = _resolve_template(payload, ctx)\n        result = convert_file(src, out, template_path=template, payload=payload, ctx=ctx, rule_spec=RULE_SPEC)\n        if asyncio.iscoroutine(result):\n            result = await result\n        if isinstance(result, dict):\n            result.setdefault("output_path", str(out))\n            result.setdefault("template_path", str(template or ""))\n        else:\n            result = {{"output_path": str(out), "template_path": str(template or ""), "result": result}}\n        if not out.is_file():\n            return _err(f"转换未生成输出文件：{{out}}", meta={{"handler": "direct_python", "action": "convert"}})\n        normalized = _ok(result, meta={{"handler": "direct_python", "action": "convert", "runtime": "generated_python"}})\n        return {{\n            "ok": normalized["ok"],\n            "summary": normalized["summary"],\n            "items": normalized["items"],\n            "warnings": normalized["warnings"],\n            "error": normalized["error"],\n            "meta": normalized["meta"],\n        }}\n    except Exception as exc:  # noqa: BLE001\n        return _err(str(exc), warnings=["请检查输入文件、模板文件和题目规则是否匹配。"], meta={{"handler": "direct_python", "action": "convert", "runtime": "generated_python"}})\n'


def _fallback_convert_module() -> str:
    return 'from __future__ import annotations\n\nfrom pathlib import Path\nfrom typing import Any, Dict, List, Optional\n\n\ndef convert_file(src_path: Path, output_path: Path, *, template_path: Optional[Path], payload: Dict[str, Any], ctx: Dict[str, Any], rule_spec: Dict[str, Any]) -> Dict[str, Any]:\n    suffix = src_path.suffix.lower()\n    if suffix not in {".xlsx", ".xlsm", ".xls"}:\n        raise ValueError(f"不支持的文件类型：{suffix or \'(无后缀)\'}")\n    from openpyxl import load_workbook, Workbook\n    src_wb = load_workbook(src_path, data_only=True)\n    src_ws = src_wb.active\n    src_rows = src_ws.max_row or 0\n    src_cols = src_ws.max_column or 0\n    headers: List[str] = []\n    if src_rows > 0:\n        for col in range(1, min(src_cols + 1, 51)):\n            val = src_ws.cell(row=1, column=col).value\n            headers.append(str(val) if val is not None else "")\n    data_rows = max(0, src_rows - 1)\n    if template_path and template_path.is_file():\n        try:\n            wb = load_workbook(template_path)\n        except Exception as exc:  # noqa: BLE001\n            raise RuntimeError(f"读取模板失败：{template_path}: {exc}") from exc\n    else:\n        wb = Workbook()\n        if "Sheet" in wb.sheetnames:\n            del wb["Sheet"]\n    if "转换结果" in wb.sheetnames:\n        ws = wb["转换结果"]\n    else:\n        ws = wb.create_sheet("转换结果")\n    ws["A1"] = "源文件"\n    ws["B1"] = src_path.name\n    ws["A2"] = "源行数"\n    ws["B2"] = data_rows\n    ws["A3"] = "源列数"\n    ws["B3"] = src_cols\n    ws["A4"] = "规则摘要"\n    ws["B4"] = str(rule_spec.get("brief") or "")[:200]\n    ws["A5"] = "状态"\n    ws["B5"] = "已根据上传资产生成 direct_python 员工并写出结果"\n    start_row = 7\n    for idx, h in enumerate(headers):\n        ws.cell(row=start_row, column=idx + 1, value=h)\n    for row_idx in range(2, min(src_rows + 1, start_row + 1000)):\n        for col_idx in range(1, min(src_cols + 1, 51)):\n            val = src_ws.cell(row=row_idx, column=col_idx).value\n            ws.cell(row=start_row + row_idx - 1, column=col_idx, value=val)\n    output_path.parent.mkdir(parents=True, exist_ok=True)\n    wb.save(output_path)\n    return {\n        "output_path": str(output_path),\n        "output_relpath": str(rule_spec.get("default_output_relpath") or output_path.name),\n        "template_path": str(template_path or ""),\n        "source_rows": data_rows,\n        "source_cols": src_cols,\n        "stat_rows": data_rows,\n        "headers": headers[:20],\n    }\n'


def render_runtime_modules(
    rule_spec: _facade().Dict[str, _facade().Any],
    generated_convert_py: _facade().Optional[str] = None,
) -> _facade().Dict[str, str]:
    runtime_kind = rule_spec.get("runtime_kind") or ""
    if runtime_kind == "csv_full_read" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_csv_read_convert_module()
    elif runtime_kind == "csv_generate" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_csv_generate_convert_module()
    elif runtime_kind == "excel_full_read" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_excel_read_convert_module()
    elif runtime_kind == "excel_generate" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_excel_generate_convert_module()
    elif runtime_kind == "txt_full_read" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_txt_read_convert_module()
    elif runtime_kind == "txt_generate" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_txt_generate_convert_module()
    elif runtime_kind == "pdf_full_read" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_pdf_read_convert_module()
    elif runtime_kind == "pdf_generate" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_pdf_generate_convert_module()
    elif runtime_kind == "ppt_full_read" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_ppt_read_convert_module()
    elif runtime_kind == "ppt_generate" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_ppt_generate_convert_module()
    elif runtime_kind == "json_quant_report" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_json_report_convert_module()
    elif runtime_kind == "word_full_extract" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_word_fallback_convert_module()
    elif runtime_kind == "word_generate" and (not (generated_convert_py or "").strip()):
        convert_py = _facade().render_word_generate_convert_module()
    else:
        convert_py = (generated_convert_py or "").strip() or _facade()._fallback_convert_module()
    modules: _facade().Dict[str, str] = {
        "__init__.py": '"""Generated runtime modules for asset-driven employee."""\n',
        "convert.py": convert_py,
        "parser.py": '"""Parser extension point generated by asset pipeline."""\n',
        "mapper.py": '"""Mapper extension point generated by asset pipeline."""\n',
        "rules.py": '"""Rules extension point generated by asset pipeline."""\n',
        "paths.py": '"""Path helpers generated by asset pipeline."""\n',
        "mapping.py": '"""Mapping helpers generated by asset pipeline."""\n',
        "header_resolver.py": '"""Header resolver generated by asset pipeline."""\n',
    }
    if runtime_kind == "word_full_extract":
        from modstore_server.legacy_doc_convert import render_legacy_doc_vendor_module

        modules["legacy_doc.py"] = render_legacy_doc_vendor_module()
    return modules


def render_build_xcemp_py(pack_id: str) -> str:
    return f'"""Build {pack_id}.xcemp from this employee_pack directory."""\nfrom __future__ import annotations\n\nimport io\nimport json\nimport zipfile\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parent\nPACK_ID = {_facade().json.dumps(pack_id, ensure_ascii=False)}\n\n\ndef main() -> None:\n    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))\n    out = ROOT / f"{{PACK_ID}}.xcemp"\n    buf = io.BytesIO()\n    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:\n        zf.writestr(f"{{PACK_ID}}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n")\n        for path in sorted((ROOT / "backend").rglob("*")):\n            if not path.is_file():\n                continue\n            if path.suffix.lower() not in {{".py", ".xlsx", ".xlsm", ".xls"}}:\n                continue\n            rel = path.relative_to(ROOT).as_posix()\n            zf.write(path, f"{{PACK_ID}}/{{rel}}")\n        readme = ROOT / "README.md"\n        if readme.is_file():\n            zf.write(readme, f"{{PACK_ID}}/README.md")\n    out.write_bytes(buf.getvalue())\n    print(out)\n\n\nif __name__ == "__main__":\n    main()\n'
