# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
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
            {"brief": str(raw.get("description") or "")}, fallback=str(raw.get("description") or "")
        )
    if rule_spec:
        aligned = _facade()._normalize_manifest(raw, rb, rule_spec)
    else:
        aligned = dict(raw)
    _facade()._sanitize_workflow_bundles(aligned)
    mf_path.write_text(
        _facade().json.dumps(aligned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    from modstore_server.employee_pipeline_routing import is_direct_python_template_runtime

    runtime_kind = str(rule_spec.get("runtime_kind") or "")
    if not is_direct_python_template_runtime(runtime_kind):
        return (base_manifest, {"source": "skipped", "reason": "not_template_runtime"})
    (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return (base_manifest, {"source": "fallback", "warning": err})
    (api_key, _) = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return (base_manifest, {"source": "fallback", "warning": "missing api key"})
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    system = "你是员工包文案助手。只输出 JSON，不要 markdown。字段：description（1-3句）、panel_summary（工作台卡片一句话）、behavior_rules（字符串数组，3-6条操作边界）。不得改写 runtime_kind、handlers 或技术契约；禁止编造已执行结果。"
    user_msg = _facade().json.dumps(
        {"brief": brief[:4000], "runtime_kind": runtime_kind, "name": base_manifest.get("name")},
        ensure_ascii=False,
    )
    try:
        result = await _facade().chat_dispatch(
            prov,
            api_key=api_key,
            base_url=base,
            model=mdl,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            max_tokens=900,
        )
    except Exception:
        return (base_manifest, {"source": "fallback", "warning": "enrich dispatch failed"})
    if not result.get("ok"):
        return (base_manifest, {"source": "fallback", "warning": str(result.get("error") or "")})
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
    from modstore_server.employee_pipeline_routing import is_direct_python_template_runtime

    runtime_kind = str(rule_spec.get("runtime_kind") or "")
    if is_direct_python_template_runtime(runtime_kind):
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": "", "model": "", "source": "template_manifest"},
        )
    (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
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
            {"provider": prov or "", "model": mdl or "", "warning": err or "missing api key"},
        )
    (api_key, _) = _facade().resolve_api_key(db, user.id, prov)
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
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        max_tokens=4000,
    )
    if not result.get("ok"):
        return (
            _facade()._fallback_manifest(brief, rule_spec),
            {"provider": prov, "model": mdl, "warning": str(result.get("error") or "")},
        )
    (parsed, perr) = _facade().parse_employee_pack_llm_json(str(result.get("content") or ""))
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


def _extract_python_code(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        from modstore_server.script_agent.llm_client import extract_code_block

        extracted = extract_code_block(raw, lang="python").strip()
        if extracted:
            return extracted
    except Exception:
        pass
    match = _facade().re.search(
        "```(?:python|py)?\\s*(.*?)```", raw, _facade().re.S | _facade().re.I
    )
    if match:
        return match.group(1).strip()
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("from ", "import ", "def ", "class ", "@")) or stripped in {
            "# -*- coding: utf-8 -*-",
            "from __future__ import annotations",
        }:
            return "\n".join(lines[i:]).strip()
    return raw


def _validate_generated_convert_py(src: str) -> _facade().Tuple[bool, str]:
    code = (src or "").strip()
    if not code:
        return (False, "empty generated convert.py")
    if _facade().re.search("\\b(eval|exec|compile|__import__)\\s*\\(", code):
        return (False, "generated convert.py uses forbidden dynamic execution")
    if _facade().re.search("\\b(subprocess|os\\.system|ctypes|multiprocessing)\\b", code):
        return (False, "generated convert.py uses forbidden process/system API")
    if _facade().re.search("\\b(globals|locals|getattr|setattr|delattr|breakpoint)\\s*\\(", code):
        return (False, "generated convert.py uses forbidden reflection/builtin")
    try:
        tree = _facade().ast.parse(code)
    except SyntaxError as exc:
        return (False, f"generated convert.py syntax error: {exc}")
    has_convert = any(
        (
            isinstance(node, _facade().ast.FunctionDef) and node.name == "convert_file"
            for node in tree.body
        )
    )
    if not has_convert:
        return (False, "generated convert.py must define convert_file(...)")
    for node in _facade().ast.walk(tree):
        if isinstance(node, _facade().ast.Import):
            for alias in node.names:
                if alias.name in ("subprocess", "ctypes", "multiprocessing"):
                    return (False, f"generated convert.py imports forbidden module: {alias.name}")
        if isinstance(node, _facade().ast.ImportFrom):
            if node.module in ("subprocess", "ctypes", "multiprocessing"):
                return (False, f"generated convert.py imports from forbidden module: {node.module}")
    return (True, "")


def _auto_fix_generated_convert_py(src: str) -> _facade().Tuple[str, _facade().List[str]]:
    fixes: _facade().List[str] = []
    code = (src or "").strip()
    if not code:
        return (code, fixes)
    lines = code.splitlines()
    filtered: _facade().List[str] = []
    skip_patterns = [
        _facade().re.compile("\\b(eval|exec|compile|__import__)\\s*\\("),
        _facade().re.compile("\\bimport\\s+(subprocess|ctypes|multiprocessing)\\b"),
        _facade().re.compile("\\bfrom\\s+(subprocess|ctypes|multiprocessing)\\s+import\\b"),
        _facade().re.compile("\\b(globals|locals|getattr|setattr|delattr|breakpoint)\\s*\\("),
    ]
    for line in lines:
        stripped = line.strip()
        if any((p.search(stripped) for p in skip_patterns)):
            fixes.append(f"removed: {stripped[:80]}")
            continue
        filtered.append(line)
    return ("\n".join(filtered), fixes)


async def generate_runtime_convert_module(
    db: _facade().Any,
    user: _facade().User,
    *,
    brief: str,
    rule_spec: _facade().Dict[str, _facade().Any],
    asset_manifest: _facade().Dict[str, _facade().Any],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    force_llm_codegen: bool = False,
    allow_builtin_codegen: bool = False,
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Tuple[_facade().Optional[str], _facade().Dict[str, _facade().Any]]:
    """Use the configured coding model to make the asset runtime real.

    This is the workbench's vibecoding step for asset employees: the platform
    supplies inspected assets and a strict runtime contract; the model writes
    only the transform module.
    """
    _force_llm = bool(force_llm_codegen)
    _allow_builtin = bool(allow_builtin_codegen)
    runtime_kind = rule_spec.get("runtime_kind") or ""
    if _allow_builtin and runtime_kind == "csv_full_read":
        return (
            _facade().render_csv_read_convert_module(),
            {"provider": "", "model": "", "source": "csv_read_builtin"},
        )
    if _allow_builtin and runtime_kind == "csv_generate":
        return (
            _facade().render_csv_generate_convert_module(),
            {"provider": "", "model": "", "source": "csv_generate_builtin"},
        )
    if _allow_builtin and runtime_kind == "excel_full_read":
        return (
            _facade().render_excel_read_convert_module(),
            {"provider": "", "model": "", "source": "excel_read_builtin"},
        )
    if _allow_builtin and runtime_kind == "excel_generate":
        return (
            _facade().render_excel_generate_convert_module(),
            {"provider": "", "model": "", "source": "excel_generate_builtin"},
        )
    if _allow_builtin and runtime_kind == "txt_full_read":
        return (
            _facade().render_txt_read_convert_module(),
            {"provider": "", "model": "", "source": "txt_read_builtin"},
        )
    if _allow_builtin and runtime_kind == "txt_generate":
        return (
            _facade().render_txt_generate_convert_module(),
            {"provider": "", "model": "", "source": "txt_generate_builtin"},
        )
    if _allow_builtin and runtime_kind == "pdf_full_read":
        return (
            _facade().render_pdf_read_convert_module(),
            {"provider": "", "model": "", "source": "pdf_read_builtin"},
        )
    if _allow_builtin and runtime_kind == "pdf_generate":
        return (
            _facade().render_pdf_generate_convert_module(),
            {"provider": "", "model": "", "source": "pdf_generate_builtin"},
        )
    if _allow_builtin and runtime_kind == "ppt_full_read":
        return (
            _facade().render_ppt_read_convert_module(),
            {"provider": "", "model": "", "source": "ppt_read_builtin"},
        )
    if _allow_builtin and runtime_kind == "ppt_generate":
        return (
            _facade().render_ppt_generate_convert_module(),
            {"provider": "", "model": "", "source": "ppt_generate_builtin"},
        )
    if _allow_builtin and runtime_kind == "json_quant_report":
        return (
            _facade().render_json_report_convert_module(),
            {"provider": "", "model": "", "source": "json_quant_report_builtin"},
        )
    if _allow_builtin and runtime_kind == "word_full_extract" and (not _force_llm):
        return (
            _facade().render_word_fallback_convert_module(),
            {"provider": "", "model": "", "source": "word_extract_builtin"},
        )
    if _allow_builtin and runtime_kind == "word_generate" and (not _force_llm):
        return (
            _facade().render_word_generate_convert_module(),
            {"provider": "", "model": "", "source": "word_generate_builtin"},
        )
    (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return (None, {"provider": "", "model": "", "warning": err})
    (api_key, _) = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return (None, {"provider": prov, "model": mdl, "warning": "missing api key"})
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    if runtime_kind == "word_full_extract":
        from modstore_server.employee_ai_pipeline import _build_vibe_coding_prompt

        system = _build_vibe_coding_prompt(runtime_kind, rule_spec)
        contract = {
            "input": "src_path may be .docx (OOXML) or legacy .doc (OLE). For .doc or misnamed binary, call legacy_doc.ensure_docx_for_extract(src, work_dir) first, then parse the returned .docx via OOXML (zipfile). Do not fabricate document text.",
            "output": "write outputs/document_full.json with paragraphs, tables, outline, blocks, sections, images metadata, styles, headers_footers, core_properties, comments, metadata, plain_text; also document_full.txt and export images under outputs/images/. Record metadata.legacy_doc when conversion happened.",
            "template": "template_path is usually None for Word extract. vendor includes legacy_doc.py.",
        }
        max_tokens = 16000
    else:
        system = "你是工作台 vibecoding 的 Python 实现器。只输出一个 Python 代码块，内容是 backend/vendor/<runtime>/convert.py。必须定义 convert_file(src_path: Path, output_path: Path, *, template_path: Optional[Path], payload: Dict[str, Any], ctx: Dict[str, Any], rule_spec: Dict[str, Any]) -> Dict[str, Any]。必须真实读取输入 Excel、按模板/规则写出 output_path。不能调用 LLM，不能写伪结果。绝对禁止使用以下任何一种写法，否则代码将被拒绝：\n  - eval(...) / exec(...) / compile(...) / __import__(...)\n  - import subprocess / import os 后调用 os.system / import ctypes / import multiprocessing\n  - globals() / locals() / getattr(...) / setattr(...) / delattr(...) / input(...) / breakpoint()\n  - 任何形式的动态代码执行或反射调用\n允许使用 pathlib、json、datetime、re、typing、openpyxl、pandas、copy、collections、io。异常要抛出清晰错误。\n正确示例：\n  from pathlib import Path\n  from openpyxl import load_workbook\n  def convert_file(src_path, output_path, *, template_path=None, payload=None, ctx=None, rule_spec=None):\n      wb = load_workbook(src_path)\n      # ... 处理逻辑 ...\n      wb.save(output_path)\n      return {'output_path': str(output_path), 'stat_rows': 1}\n错误示例（会被拒绝）：\n  exec('print(1)')  # 禁止\n  __import__('os')   # 禁止\n  getattr(obj, 'x') # 禁止\n"
        contract = {
            "input": "src_path points to the uploaded Excel file.",
            "template": "template_path may point to a bundled template workbook, or may be None.",
            "output": "write the final workbook to output_path and return useful stats.",
        }
        max_tokens = 8000
    user_msg = _facade().json.dumps(
        {
            "brief": brief,
            "rule_spec": rule_spec,
            "asset_manifest": {
                **{k: v for (k, v) in asset_manifest.items() if k != "assets"},
                "assets": [
                    {
                        k: v
                        for (k, v) in dict(item).items()
                        if k in {"id", "filename", "kind", "suffix", "size", "excel", "preview"}
                    }
                    for item in asset_manifest.get("assets") or []
                    if isinstance(item, dict)
                ],
            },
            "contract": contract,
        },
        ensure_ascii=False,
    )[:20000]
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        max_tokens=max_tokens,
    )
    if not result.get("ok"):
        return (None, {"provider": prov, "model": mdl, "warning": str(result.get("error") or "")})
    code = _facade()._extract_python_code(str(result.get("content") or ""))
    (ok, validation_error) = _facade()._validate_generated_convert_py(code)
    if not ok:
        if _allow_builtin:
            (fixed_code, fixes) = _facade()._auto_fix_generated_convert_py(code)
            (fixed_ok, fixed_error) = _facade()._validate_generated_convert_py(fixed_code)
            if fixed_ok:
                return (
                    fixed_code.rstrip() + "\n",
                    {
                        "provider": prov,
                        "model": mdl,
                        "generated": True,
                        "auto_fixed": True,
                        "fixes": fixes,
                        "source": "llm_codegen",
                    },
                )
        return (None, {"provider": prov, "model": mdl, "warning": validation_error})
    return (
        code.rstrip() + "\n",
        {"provider": prov, "model": mdl, "generated": True, "source": "llm_codegen"},
    )


async def repair_runtime_convert_module(
    db: _facade().Any,
    user: _facade().User,
    *,
    brief: str,
    rule_spec: _facade().Dict[str, _facade().Any],
    previous_convert_py: str,
    failure: _facade().Dict[str, _facade().Any],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    round_no: int,
    allow_auto_fix: bool = False,
) -> _facade().Tuple[_facade().Optional[str], _facade().Dict[str, _facade().Any]]:
    (prov, mdl, err) = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return (None, {"provider": "", "model": "", "warning": err, "round": round_no})
    (api_key, _) = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return (
            None,
            {"provider": prov, "model": mdl, "warning": "missing api key", "round": round_no},
        )
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    system = "你是 Python 代码修复器。只输出修复后的 convert.py Python 代码块。必须保留 convert_file 签名，必须真实读取 src_path/template_path 并保存 output_path。如果业务映射复杂，最低要求也必须基于模板 workbook 写出一个有效 xlsx 到 output_path，并返回统计信息。绝对禁止使用以下任何一种写法，否则代码将被拒绝：\n  - eval(...) / exec(...) / compile(...) / __import__(...)\n  - import subprocess / import os 后调用 os.system / import ctypes / import multiprocessing\n  - globals() / locals() / getattr(...) / setattr(...) / delattr(...) / input(...) / breakpoint()\n  - 任何形式的动态代码执行或反射调用\n允许使用 pathlib、json、datetime、re、typing、openpyxl、pandas、copy、collections、io。\n"
    user_msg = _facade().json.dumps(
        {
            "round": round_no,
            "failure": failure,
            "previous_convert_py": previous_convert_py,
            "brief": brief,
            "rule_spec": rule_spec,
        },
        ensure_ascii=False,
    )[:24000]
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        max_tokens=8000,
    )
    if not result.get("ok"):
        return (
            None,
            {
                "provider": prov,
                "model": mdl,
                "warning": str(result.get("error") or ""),
                "round": round_no,
            },
        )
    code = _facade()._extract_python_code(str(result.get("content") or ""))
    (ok, validation_error) = _facade()._validate_generated_convert_py(code)
    if not ok:
        if allow_auto_fix:
            (fixed_code, fixes) = _facade()._auto_fix_generated_convert_py(code)
            (fixed_ok, _fixed_error) = _facade()._validate_generated_convert_py(fixed_code)
            if fixed_ok:
                return (
                    fixed_code.rstrip() + "\n",
                    {
                        "provider": prov,
                        "model": mdl,
                        "repaired": True,
                        "round": round_no,
                        "auto_fixed": True,
                        "fixes": fixes,
                    },
                )
        return (
            None,
            {"provider": prov, "model": mdl, "warning": validation_error, "round": round_no},
        )
    return (
        code.rstrip() + "\n",
        {"provider": prov, "model": mdl, "repaired": True, "round": round_no},
    )


def manifest_actions_handlers(mf: _facade().Dict[str, _facade().Any]) -> _facade().List[str]:
    """Read handlers from employee_config_v2.actions or canvas-root actions."""
    v2 = mf.get("employee_config_v2") if isinstance(mf.get("employee_config_v2"), dict) else {}
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    if not actions and isinstance(mf.get("actions"), dict):
        actions = mf["actions"]
    raw = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    return [str(h).strip() for h in raw if str(h).strip()]


def manifest_expects_word_runtime(
    mf: _facade().Dict[str, _facade().Any], *, brief: str = ""
) -> bool:
    """True when manifest/brief indicates Word 全量提取 direct_python delivery."""
    rs_path_inline = mf.get("rule_spec") if isinstance(mf.get("rule_spec"), dict) else {}
    if rs_path_inline.get("runtime_kind") == "word_full_extract":
        return True
    from modstore_server.employee_brief_utils import extract_routing_brief

    rb = (brief or "").strip() or extract_routing_brief(
        {"brief": str(mf.get("description") or "")}, fallback=str(mf.get("description") or "")
    )
    if _facade().is_word_full_extract(rb):
        return True
    perception = mf.get("perception")
    if not isinstance(perception, dict):
        v2 = mf.get("employee_config_v2") if isinstance(mf.get("employee_config_v2"), dict) else {}
        perception = v2.get("perception") if isinstance(v2.get("perception"), dict) else {}
    exts = (
        perception.get("accepted_extensions")
        if isinstance(perception.get("accepted_extensions"), list)
        else []
    )
    ext_l = {str(x).lower() for x in exts}
    if ext_l & {".docx", ".doc"} and "direct_python" in _facade().manifest_actions_handlers(mf):
        return True
    return False
