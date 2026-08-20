# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def build_rule_spec(
    brief: str,
    asset_manifest: _facade().Dict[str, _facade().Any],
    *,
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.employee_pipeline_routing import confident_word_full_extract_routing

    if confident_word_full_extract_routing(brief):
        return _facade().build_word_extract_rule_spec(brief)
    if _facade().is_csv_generate(brief):
        return _facade().build_csv_generate_rule_spec(brief)
    if _facade().is_csv_full_read(brief):
        return _facade().build_csv_read_rule_spec(brief)
    if _facade().is_excel_generate(brief):
        return _facade().build_excel_generate_rule_spec(brief)
    if _facade().is_excel_full_read(brief):
        return _facade().build_excel_read_rule_spec(brief)
    if _facade().is_pdf_generate(brief):
        return _facade().build_pdf_generate_rule_spec(brief)
    if _facade().is_pdf_full_read(brief):
        return _facade().build_pdf_read_rule_spec(brief)
    if _facade().is_json_quant_report(brief):
        return _facade().build_json_quant_report_rule_spec(brief)
    if _facade().is_kitten_chart_viz(brief):
        return _facade().build_kitten_chart_rule_spec(brief)
    if _facade().is_ppt_generate(brief):
        return _facade().build_ppt_generate_rule_spec(brief)
    if _facade().is_ppt_full_read(brief):
        return _facade().build_ppt_read_rule_spec(brief)
    if _facade().is_txt_generate(brief):
        return _facade().build_txt_generate_rule_spec(brief)
    if _facade().is_txt_full_read(brief):
        return _facade().build_txt_read_rule_spec(brief)
    if _facade().is_word_full_extract(brief):
        return _facade().build_word_extract_rule_spec(brief)
    if _facade().is_word_generate(brief):
        return _facade().build_word_generate_rule_spec(brief)
    templates = asset_manifest.get("templates") or []
    if not templates:
        excels = [
            a
            for a in asset_manifest.get("assets") or []
            if a.get("suffix") in _facade().EXCEL_SUFFIXES
        ]
        templates = excels[:1]
    template_asset = templates[0] if templates else None
    template_relpath = ""
    if template_asset:
        template_relpath = _facade()._template_storage_relpath(
            str(template_asset["filename"]), brief
        )
    runtime_kind = _facade()._infer_asset_runtime_kind(brief, asset_manifest)
    accepted_exts = _facade()._infer_accepted_extensions(asset_manifest)
    _is_doc_kind = runtime_kind in ("contract_doc_review", "doc_template_transform")
    if not accepted_exts:
        if _is_doc_kind:
            accepted_exts = [".docx", ".pdf"]
        else:
            accepted_exts = [".xlsx", ".xlsm", ".xls"]
    output_ext = accepted_exts[0] if accepted_exts else ".xlsx"
    output_relpath = f"outputs/employee_output{output_ext}"
    if "考勤" in brief:
        output_relpath = f"424/考勤转换输出{output_ext}"
    _mode = (
        "llm_doc_review"
        if runtime_kind == "contract_doc_review"
        else "direct_python_file_transform"
    )
    spec = {
        "brief": brief,
        "mode": _mode,
        "accepted_extensions": accepted_exts,
        "default_action": "review" if _is_doc_kind else "convert",
        "default_output_relpath": output_relpath,
        "default_template_relpath": (
            template_relpath.removeprefix("backend/templates/") if template_relpath else ""
        ),
        "template_relpath": template_relpath,
        "template_asset_id": template_asset.get("id") if template_asset else "",
        "runtime_kind": runtime_kind,
        "assets_summary": {
            "templates": [
                {
                    "filename": a.get("filename"),
                    "sheets": [
                        {
                            "name": s.get("name"),
                            "max_row": s.get("max_row"),
                            "max_column": s.get("max_column"),
                            "headers": s.get("header_candidates", [])[:2],
                        }
                        for s in ((a.get("excel") or {}).get("sheets") or [])[:6]
                    ],
                }
                for a in templates[:3]
            ],
            "example_inputs": [
                a.get("filename") for a in (asset_manifest.get("example_inputs") or [])[:5]
            ],
            "expected_outputs": [
                a.get("filename") for a in (asset_manifest.get("expected_outputs") or [])[:5]
            ],
            "rules": [
                {"filename": a.get("filename"), "preview": str(a.get("preview") or "")[:1000]}
                for a in (asset_manifest.get("rules") or [])[:5]
            ],
        },
        "requirements": [
            "Use direct_python only; do not add echo or llm_md.",
            "Preserve uploaded templates as binary files and copy them into backend/templates.",
            "Never claim success unless an output file is actually written.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }
    if runtime_kind == "contract_doc_review":
        spec["requirements"] = [
            "This employee reviews contracts/documents using LLM reasoning via the agent handler.",
            "Read the uploaded document, identify missing clauses, ambiguous terms, and compliance issues.",
            "Output a structured review with specific suggestions for each issue found.",
            "Never fabricate legal advice; clearly state when professional legal review is recommended.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ]
    elif runtime_kind in {"excel_rules_transform", "reference_python_transform"}:
        spec["requirements"].extend(
            [
                "Generate deterministic Python from the uploaded rules, template, and examples.",
                "If reference Python is provided, adapt or call it instead of replacing it with a placeholder.",
                "Fail explicitly when the generated transform cannot map the input workbook to the output workbook.",
            ]
        )
    return spec


def _slug_from_brief(brief: str) -> str:
    text = brief or ""
    explicit = _facade().re.search(
        "(?:pack_id|员工包\\s*ID|员工包ID|员工包 id|包ID|包 id)\\s*[:：=]\\s*([A-Za-z0-9][A-Za-z0-9_-]{2,80})",
        text,
        _facade().re.I,
    )
    if explicit:
        return _facade().normalize_mod_id(explicit.group(1)) or "asset-worker-employee"
    if _facade().re.search(
        "\\btaiyangniao[-_ ]attendance(?:[-_ ]employee)?\\b", text, _facade().re.I
    ):
        return "taiyangniao-attendance-employee"
    if _facade().is_csv_generate(brief):
        return "csv-generate-employee"
    if _facade().is_csv_full_read(brief):
        return "csv-full-read-employee"
    if _facade().is_excel_generate(brief):
        return "excel-generate-employee"
    if _facade().is_excel_full_read(brief):
        return "excel-full-read-employee"
    if _facade().is_pdf_generate(brief):
        return "pdf-generate-employee"
    if _facade().is_pdf_full_read(brief):
        return "pdf-full-read-employee"
    if _facade().is_json_quant_report(brief):
        return "json-report-employee"
    if _facade().is_ppt_generate(brief):
        return "ppt-generate-employee"
    if _facade().is_ppt_full_read(brief):
        return "ppt-full-read-employee"
    if _facade().is_txt_generate(brief):
        return "txt-generate-employee"
    if _facade().is_txt_full_read(brief):
        return "txt-full-read-employee"
    if _facade().is_word_full_extract(brief):
        return "word-full-read-employee"
    if _facade().is_word_generate(brief):
        return "word-generate-employee"
    if "考勤" in brief:
        return "attendance-transform-employee"
    return "asset-worker-employee"


def _employee_name_from_brief(brief: str, fallback: str = "文件处理员工") -> str:
    text = (brief or "").strip()
    explicit = _facade().re.search(
        "(?:员工名称|员工名|name)\\s*[:：=]\\s*([^\\n\\r,，。；;]{2,40})", text, _facade().re.I
    )
    if explicit:
        return explicit.group(1).strip()
    if "考勤" in text:
        return "考勤处理员"
    if "报表" in text:
        return "报表处理员"
    if _facade().re.search("审核|审查|合规|风控|合同", text):
        return "合同审核员工"
    if _facade().re.search("翻译|本地化|多语言", text):
        return "文档翻译员工"
    if _facade().re.search("比对|对比|校对|校验", text):
        return "文档比对员工"
    if _facade().is_csv_generate(text):
        return "CSV 生成员"
    if _facade().is_csv_full_read(text):
        return "CSV 全量读取员"
    if _facade().is_excel_generate(text):
        return "Excel 生成员"
    if _facade().is_excel_full_read(text):
        return "Excel 全量读取员"
    if _facade().is_pdf_generate(text):
        return "PDF 生成员"
    if _facade().is_pdf_full_read(text):
        return "PDF 全量读取员"
    if _facade().is_ppt_generate(text):
        return "PPT 生成员"
    if _facade().is_ppt_full_read(text):
        return "PPT 全量读取员"
    if _facade().is_txt_generate(text):
        return "TXT 生成员"
    if _facade().is_txt_full_read(text):
        return "TXT 全量读取员"
    if _facade().is_word_generate(text):
        return "Word 生成员"
    if _facade().is_word_full_extract(text):
        return "Word 全量读取员"
    return fallback


def _template_storage_relpath(filename: str, brief: str = "") -> str:
    safe = _facade()._safe_basename(filename, "template.xlsx")
    return (
        f"backend/templates/424/{safe}" if "考勤" in (brief or "") else f"backend/templates/{safe}"
    )


def _employee_id_from_pack_id(pack_id: str) -> str:
    pid = (pack_id or "").strip()
    if pid.endswith("-employee"):
        return pid[: -len("-employee")] or pid
    return pid
