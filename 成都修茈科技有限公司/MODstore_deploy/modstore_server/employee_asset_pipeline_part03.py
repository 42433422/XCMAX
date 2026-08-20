# mypy: disable-error-code="arg-type, attr-defined, dict-item, index, no-any-return, union-attr, valid-type, var-annotated"
# ruff: noqa: E402, F401, I001
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def _fallback_manifest(
    brief: str, rule_spec: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    pid = _facade()._slug_from_brief(brief)
    name = _facade()._employee_name_from_brief(brief)
    is_attendance = "考勤" in brief
    runtime_kind = rule_spec.get("runtime_kind") or "generic_excel_transform"
    _is_doc_review = runtime_kind in ("contract_doc_review", "doc_template_transform")
    _is_word_extract = runtime_kind == "word_full_extract"
    _is_word_gen = runtime_kind == "word_generate"
    _is_csv_read = runtime_kind == "csv_full_read"
    _is_csv_gen = runtime_kind == "csv_generate"
    _is_excel_read = runtime_kind == "excel_full_read"
    _is_excel_gen = runtime_kind == "excel_generate"
    _is_txt_read = runtime_kind == "txt_full_read"
    _is_txt_gen = runtime_kind == "txt_generate"
    _is_pdf_read = runtime_kind == "pdf_full_read"
    _is_pdf_gen = runtime_kind == "pdf_generate"
    _is_ppt_read = runtime_kind == "ppt_full_read"
    _is_ppt_gen = runtime_kind == "ppt_generate"
    _is_json_report = runtime_kind == "json_quant_report"
    _is_kitten_chart = runtime_kind == "kitten_chart_viz"
    employee_id = str(rule_spec.get("pack_id") or pid).strip() or pid
    accepted = rule_spec.get("accepted_extensions") or [".xlsx"]
    has_doc = any(e in _facade().DOC_SUFFIXES for e in accepted)
    has_xls = any(e in _facade().EXCEL_SUFFIXES for e in accepted)
    if _is_csv_read:
        capabilities = ["data.csv_read", "data.json_export"]
    elif _is_csv_gen:
        capabilities = ["data.json_read", "data.csv_write"]
    elif _is_excel_read:
        capabilities = ["excel.full_read", "data.json_export"]
    elif _is_excel_gen:
        capabilities = ["data.json_read", "excel.write"]
    elif _is_txt_read:
        capabilities = ["text.full_read", "text.encoding_detect"]
    elif _is_txt_gen:
        capabilities = ["text.parse", "text.write", "text.polish_optional"]
    elif _is_pdf_read:
        capabilities = ["pdf.native_text", "pdf.image_extract", "vision.vlm"]
    elif _is_pdf_gen:
        capabilities = ["pdf.parse", "pdf.write", "pdf.polish_optional"]
    elif _is_ppt_read:
        capabilities = ["ppt.parse", "ppt.notes_generate", "vision.vlm"]
    elif _is_ppt_gen:
        capabilities = ["ppt.write", "ppt.ooxml", "data.json_read", "llm.plan"]
    elif _is_json_report:
        capabilities = ["data.json_read", "report.write"]
    elif _is_kitten_chart:
        capabilities = ["data.json_read", "chart.echarts", "viz.dashboard"]
    elif _is_word_gen:
        capabilities = ["doc.generate", "doc.template_merge", "doc.styles"]
    elif _is_word_extract:
        capabilities = [
            "doc.full_extract",
            "doc.tables",
            "doc.images",
            "doc.metadata",
            "doc.styles",
        ]
    elif _is_doc_review:
        capabilities = ["doc.review", "doc.compliance_check", "doc.suggestion"]
    elif is_attendance:
        capabilities = [
            "attendance.rules",
            "attendance.convert_upload",
            "attendance.template_fill",
            "attendance.download_hint",
        ]
    else:
        capabilities = [
            "file.transform",
            "doc.template_fill" if has_doc else "excel.template_fill",
        ]
    if _is_csv_read:
        prompt = f"你是{name}。你负责将用户上传的 .csv 解析为结构化 JSON（outputs/data.json）。必须真实执行 direct_python，禁止 LLM 编造行列数据。"
    elif _is_csv_gen:
        prompt = f"你是{name}。你负责根据 JSON（columns/rows）写出 outputs/output.csv。JSON 为中介；必须真实执行 direct_python，禁止编造表格内容。"
    elif _is_excel_read:
        prompt = f"你是{name}。你负责将用户上传的 xlsx 全量解析为 outputs/workbook.json（含 sheet、表头、单元格）。必须真实执行 direct_python，禁止 LLM 编造单元格数据。"
    elif _is_excel_gen:
        prompt = f"你是{name}。你负责根据 JSON（sheets/columns/rows）写出 outputs/output.xlsx。JSON 为中介；必须真实执行 direct_python，禁止编造表格内容。"
    elif _is_txt_read:
        prompt = f"你是{name}。你负责读取用户上传的 .txt 文件并原样交付全部纯文本。必须真实执行 direct_python，输出 document_full.txt 与 document_meta.json，禁止编造正文。"
    elif _is_txt_gen:
        prompt = f"你是{name}。你负责读取 .txt、输出结构化 JSON，并写入 generated_document.txt。direct_python 必须真实解析；润色/改写任务可走 agent，禁止无输入编造内容。"
    elif _is_pdf_read:
        prompt = f"你是{name}。你负责读取 PDF 原生文字并导出分类图片目录；正文禁止 LLM 编造；图片须走 VLM 描述（ctx.call_llm vision）。"
    elif _is_pdf_gen:
        prompt = f"你是{name}。你负责读取 PDF、输出 JSON 中介并生成 generated_document.pdf。direct_python 必须真实解析；润色可走 agent，禁止无输入编造。"
    elif _is_ppt_read:
        prompt = f"你是{name}。你负责全量解析 PPT：大纲、每页正文、导出图片并 VLM 描述；按「为这份PPT生成每页的演讲备注」生成 notes_generated。正文禁止 LLM 编造；必须真实执行 direct_python。"
    elif _is_ppt_gen:
        prompt = f"你是{name}。compose-first：无模板时从零合成多页 output.pptx；enhance：复制 template 后按 ppt_edit_plan 注入 OOXML 动画。必须执行 modstore_server.ppt_generate_pipeline，禁止仅输出纯文字幻灯片冒充带动效作业。"
    elif _is_json_report:
        prompt = f"你是{name}。你负责读取 document_full.json 或 execute_result 包装的 JSON，在 direct_python 内调用 LLM 生成 outputs/quantitative_report.html。仅基于 JSON 事实撰写量化报告，禁止编造未出现的指标或结论。"
    elif _is_word_gen:
        prompt = f"你是{name}。你负责读取 document_full.json（或与 Word 全量读取同 schema 的 JSON），可选 template.docx 模板，生成 generated_document.docx。direct_python 必须真实写 docx；禁止无 JSON 编造正文。"
    elif _is_word_extract:
        prompt = f"你是{name}。你负责全量提取 Word 文档的所有格式与信息：段落、表格、图片、样式、页眉页脚、元数据与批注。必须真实执行 direct_python 解析，输出 document_full.json 与 txt，禁止 LLM 编造文档内容。"
    elif _is_doc_review:
        prompt = f"你是{name}。你负责审核用户上传的合同/文档，识别缺失条款、模糊表述和合规风险，并给出具体修改建议。必须基于文档实际内容进行分析，禁止编造不存在的条款。当涉及专业法律建议时，应明确建议咨询专业律师。"
    elif is_attendance:
        prompt = f"你是{name}。你负责把用户上传的 Excel 按规则和模板生成结果。必须真实执行 direct_python 转换；输入文件、模板或转换模块缺失时返回明确错误，禁止编造成功。"
    elif has_doc:
        prompt = f"你是{name}。你负责处理用户上传的文档文件，按规则和模板生成结果。必须真实执行 direct_python 转换；输入文件缺失时返回明确错误，禁止编造成功。"
    else:
        prompt = "你是文件处理员工。必须真实执行 direct_python，失败时返回真实错误，禁止编造结果。"
    if _is_csv_read:
        expertise = ["CSV 解析", "JSON 结构化", "表格数据"]
        persona = "严谨的 CSV 全量读取员工"
        skill_brief = "上传 csv，输出 data.json 中介。"
    elif _is_csv_gen:
        expertise = ["JSON 解析", "CSV 写出", "表格生成"]
        persona = "严谨的 CSV 生成员工"
        skill_brief = "JSON 中介 → 写出 output.csv。"
    elif _is_excel_read:
        expertise = ["Excel 解析", "JSON 结构化", "单元格全量"]
        persona = "严谨的 Excel 全量读取员工"
        skill_brief = "上传 xlsx，输出 workbook.json 中介。"
    elif _is_excel_gen:
        expertise = ["JSON 解析", "Excel 写出", "多 sheet"]
        persona = "严谨的 Excel 生成员工"
        skill_brief = "JSON 中介 → 写出 output.xlsx。"
    elif _is_txt_read:
        expertise = ["TXT 读取", "编码检测", "纯文本"]
        persona = "严谨的 TXT 全量读取员工"
        skill_brief = "上传 txt，原样读出全部文本并交付。"
    elif _is_txt_gen:
        expertise = ["TXT 解析", "JSON 结构化", "文档生成"]
        persona = "严谨的 TXT 生成员工"
        skill_brief = "上传 txt → JSON → 写 generated txt，可选润色。"
    elif _is_pdf_read:
        expertise = ["PDF 原生文字", "图片分类", "VLM 描述"]
        persona = "严谨的 PDF 全量读取员工"
        skill_brief = "上传 pdf，原生文字 + 图片分类目录 + VLM sidecar。"
    elif _is_pdf_gen:
        expertise = ["PDF 解析", "JSON 中介", "PDF 生成"]
        persona = "严谨的 PDF 生成员工"
        skill_brief = "上传 pdf → JSON → 写 generated pdf，可选润色。"
    elif _is_ppt_read:
        expertise = ["PPT 解析", "演讲备注", "VLM 识图"]
        persona = "严谨的 PPT 全量读取员工"
        skill_brief = "上传 pptx → JSON 中介 + 演讲备注 + 图片 VLM。"
    elif _is_ppt_gen:
        expertise = ["PPT 合成", "OOXML 动画", "LLM 编排"]
        persona = "严谨的 PPT 生成员工"
        skill_brief = "plan → compose/enhance → output.pptx。"
    elif _is_json_report:
        expertise = ["JSON 解析", "量化报告", "HTML 撰写"]
        persona = "严谨的 JSON 量化报告员"
        skill_brief = "document_full JSON → 美观 HTML 量化报告。"
    elif _is_word_gen:
        expertise = ["Word 生成", "JSON 中介", "模板合并"]
        persona = "严谨的 Word 生成员工"
        skill_brief = "JSON + 可选模板 → 生成 docx。"
    elif _is_word_extract:
        expertise = ["Word 解析", "OOXML", "文档结构化"]
        persona = "严谨的 Word 全量提取员工"
        skill_brief = "全量解析 docx，输出 JSON/txt/图片等结构化结果。"
    elif _is_doc_review:
        expertise = ["合同审核", "条款分析", "合规检查"]
        persona = "严谨的合同审核员工"
        skill_brief = "审核上传的合同/文档，识别风险条款并给出修改建议。"
    elif has_doc:
        expertise = ["文档处理", "模板回填"]
        persona = "严谨的文档处理员工"
        skill_brief = "读取上传文档并按模板生成输出。"
    elif has_xls:
        expertise = ["Excel", "模板回填"]
        persona = "严谨的数据处理员工"
        skill_brief = "读取上传文件并按模板生成输出。"
    else:
        expertise = ["文件处理", "模板回填"]
        persona = "严谨的数据处理员工"
        skill_brief = "读取上传文件并按模板生成输出。"
    if _is_csv_read:
        panel_summary = "上传 .csv，解析为 JSON 中介 outputs/data.json。"
    elif _is_csv_gen:
        panel_summary = "上传 JSON/纯文本描述，按 columns/rows 写出 outputs/output.csv。"
    elif _is_excel_read:
        panel_summary = "上传 .xlsx，全量读取 sheet/表头/单元格并输出 workbook.json。"
    elif _is_excel_gen:
        panel_summary = "上传 JSON 或纯文本描述，按 sheets 写出 outputs/output.xlsx。"
    elif _is_txt_read:
        panel_summary = "上传 .txt，全量读取纯文本并交付 document_full.txt。"
    elif _is_txt_gen:
        panel_summary = "上传 .txt，解析为 JSON 并生成 txt 文档，可选润色。"
    elif _is_pdf_read:
        panel_summary = "上传 .pdf，只读原生文字；图片分类存储并 VLM 描述。"
    elif _is_pdf_gen:
        panel_summary = "上传 JSON/纯文本描述，生成 PDF，可选润色。"
    elif _is_ppt_read:
        panel_summary = "上传 .pptx，全量解析并生成演讲备注；图片 VLM 识图。"
    elif _is_ppt_gen:
        panel_summary = "文字/JSON 从零生成或基于 template.pptx 增强，输出 output.pptx（含动画）。"
    elif _is_json_report:
        panel_summary = (
            "上传 document_full.json（或 execute_result），生成 outputs/quantitative_report.html。"
        )
    elif _is_word_gen:
        panel_summary = "上传 JSON（document_full.json），可选模板 docx，生成 Word 文档。"
    elif _is_word_extract:
        panel_summary = "上传 Word，全量提取正文/表格/图片/样式/元数据并交付 JSON。"
    elif _is_doc_review:
        panel_summary = "上传合同/文档，AI 审核风险条款并给出修改建议。"
    elif is_attendance:
        panel_summary = "上传考勤表，按规则和模板生成考勤结果。"
    else:
        panel_summary = "读取上传文件并按模板生成输出。"
    if _is_csv_read:
        behavior_rules = [
            "必须真实解析 csv，禁止编造行列。",
            "成功必须以写出 data.json 且 row_count 正确为准。",
        ]
        few_shot = []
    elif _is_csv_gen:
        behavior_rules = [
            "必须根据 JSON columns/rows 写出 csv。",
            "成功必须以写出 output.csv 为准。",
        ]
        few_shot = []
    elif _is_excel_read:
        behavior_rules = [
            "必须真实解析 xlsx，禁止编造单元格。",
            "成功必须以写出 workbook.json 为准。",
        ]
        few_shot = []
    elif _is_excel_gen:
        behavior_rules = [
            "必须根据 JSON sheets/rows 写出 xlsx。",
            "成功必须以写出 output.xlsx 为准。",
        ]
        few_shot = []
    elif _is_txt_read:
        behavior_rules = [
            "必须真实读取 txt 原文，禁止编造内容。",
            "成功必须以写出 document_full.txt 为准。",
        ]
        few_shot = []
    elif _is_txt_gen:
        behavior_rules = [
            "必须真实读取 txt 并写出 document_parsed.json。",
            "成功必须以写出 generated_document.txt 为准。",
            "润色时须基于 JSON 摘要，禁止无输入编造。",
        ]
        few_shot = []
    elif _is_pdf_read:
        behavior_rules = [
            "正文必须来自 PDF 原生文字层，禁止 LLM 编造。",
            "图片须写入 outputs/images/<category>/ 并尽量生成 VLM sidecar。",
            "成功必须以写出 document_full.txt 与 images_index.json 为准。",
        ]
        few_shot = []
    elif _is_pdf_gen:
        behavior_rules = [
            "必须真实读取 PDF 并写出 document_parsed.json。",
            "成功必须以写出 generated_document.pdf 为准。",
            "润色时须基于 JSON，禁止无输入编造。",
        ]
        few_shot = []
    elif _is_ppt_read:
        behavior_rules = [
            "幻灯片正文必须来自 pptx 真实解析，禁止 LLM 编造。",
            "必须写出 presentation_full.json 与 speaker_notes.md。",
            "图片尽量生成 VLM sidecar。",
        ]
        few_shot = []
    elif _is_ppt_gen:
        behavior_rules = [
            "必须写出 outputs/output.pptx（含 ppt_edit_plan.json）。",
            "compose 无模板时须多页骨架；enhance 须保留 template 媒体。",
            "禁止无输入编造；禁止纯文字冒充带动效/带图 PPT。",
        ]
        few_shot = []
    elif _is_json_report:
        behavior_rules = [
            "必须写出 outputs/quantitative_report.html。",
            "禁止编造 JSON 中不存在的章节或数据。",
            "统计数字优先使用确定性摘要。",
        ]
        few_shot = []
    elif _is_word_gen:
        behavior_rules = [
            "必须基于 JSON 真实生成 docx，禁止无输入编造正文。",
            "成功必须以写出 generated_document.docx 为准。",
            "可选模板仅用于样式，不得覆盖 JSON 正文语义。",
        ]
        few_shot = []
    elif _is_word_extract:
        behavior_rules = [
            "必须真实解析 docx，禁止编造段落或表格内容。",
            "成功必须以写出 document_full.json 为准。",
            "JSON 须含 paragraphs、tables、images、core_properties 等字段。",
        ]
        few_shot = []
    elif _is_doc_review:
        behavior_rules = [
            "必须基于文档实际内容分析，禁止编造不存在的条款。",
            "涉及专业法律建议时，必须建议咨询专业律师。",
            "输出必须包含具体条款位置和修改建议。",
        ]
        few_shot = [
            {
                "input": "上传一份AI技术服务合同",
                "output": "审核报告：1) 第3条服务范围表述模糊，建议明确具体服务项；2) 缺少数据安全条款，建议补充；3) 违约责任条款不完整，建议增加违约金比例。",
            }
        ]
    else:
        behavior_rules = [
            "没有真实文件时必须报错。",
            "成功必须以实际写出输出文件为准。",
        ]
        few_shot = []
    if _is_doc_review:
        actions_cfg: _facade().Dict[str, _facade().Any] = {"handlers": ["agent"]}
    elif _is_txt_gen:
        handlers_list = (
            ["direct_python", "agent"]
            if rule_spec.get("optional_llm_polish")
            else ["direct_python", "agent"]
        )
        actions_cfg = {
            "handlers": handlers_list,
            "direct_python": {
                "module": _facade().sanitize_employee_stem(employee_id),
                "action": "convert",
                "default_output_relpath": rule_spec.get("default_output_relpath")
                or "outputs/document_parsed.json",
                "default_text_output_relpath": rule_spec.get("default_text_output_relpath")
                or "outputs/generated_document.txt",
            },
        }
    elif _is_pdf_gen:
        handlers_list = (
            ["direct_python", "agent"]
            if rule_spec.get("optional_llm_polish")
            else ["direct_python", "agent"]
        )
        actions_cfg = {
            "handlers": handlers_list,
            "direct_python": {
                "module": _facade().sanitize_employee_stem(employee_id),
                "action": "convert",
                "default_output_relpath": rule_spec.get("default_output_relpath")
                or "outputs/document_parsed.json",
                "default_pdf_output_relpath": rule_spec.get("default_pdf_output_relpath")
                or "outputs/generated_document.pdf",
            },
        }
    elif _is_word_gen:
        handlers_list = (
            ["direct_python", "agent"]
            if rule_spec.get("optional_llm_polish")
            else ["direct_python"]
        )
        actions_cfg = {
            "handlers": handlers_list,
            "direct_python": {
                "module": _facade().sanitize_employee_stem(employee_id),
                "action": "convert",
                "default_output_relpath": rule_spec.get("default_output_relpath")
                or "outputs/generated_document.docx",
                "default_template_relpath": str(
                    rule_spec.get("default_template_relpath") or "inputs/template.docx"
                ),
            },
        }
    else:
        default_out = rule_spec.get("default_output_relpath") or (
            "outputs/data.json"
            if _is_csv_read
            else (
                "outputs/output.csv"
                if _is_csv_gen
                else (
                    "outputs/workbook.json"
                    if _is_excel_read
                    else (
                        "outputs/output.xlsx"
                        if _is_excel_gen
                        else (
                            "outputs/document_full.txt"
                            if _is_txt_read
                            else (
                                "outputs/document_full.txt"
                                if _is_pdf_read
                                else (
                                    "outputs/quantitative_report.html"
                                    if _is_json_report
                                    else "outputs/employee_output.xlsx"
                                )
                            )
                        )
                    )
                )
            )
        )
        actions_cfg = {
            "handlers": ["direct_python"],
            "direct_python": {
                "module": _facade().sanitize_employee_stem(employee_id),
                "action": "convert",
                "default_output_relpath": default_out,
                "default_template_relpath": str(
                    rule_spec.get("template_relpath") or ""
                ).removeprefix("backend/templates/"),
                "default_use_personnel_roster": not (
                    _is_csv_read
                    or _is_csv_gen
                    or _is_excel_read
                    or _is_excel_gen
                    or _is_txt_read
                    or _is_txt_gen
                    or _is_pdf_read
                    or _is_pdf_gen
                ),
            },
        }
    if _is_csv_read:
        skill_name = "data.csv_read"
    elif _is_csv_gen:
        skill_name = "data.csv_write"
    elif _is_excel_read:
        skill_name = "excel.full_read"
    elif _is_excel_gen:
        skill_name = "excel.write"
    elif _is_txt_read:
        skill_name = "text.full_read"
    elif _is_txt_gen:
        skill_name = "text.generate"
    elif _is_pdf_read:
        skill_name = "pdf.full_read"
    elif _is_pdf_gen:
        skill_name = "pdf.generate"
    elif _is_ppt_read:
        skill_name = "ppt.full_read"
    elif _is_ppt_gen:
        skill_name = "ppt.generate"
    elif _is_json_report:
        skill_name = "report.quantitative"
    elif _is_word_gen:
        skill_name = "doc.generate"
    elif _is_word_extract:
        skill_name = "doc.full_extract"
    elif _is_doc_review:
        skill_name = "doc.review"
    else:
        skill_name = "file.transform"
    from modstore_server.employee_asset_pipeline_fallback_result import (
        _build_fallback_manifest_result,
    )

    return _build_fallback_manifest_result(locals())


from modstore_server.employee_asset_pipeline_part03_part01 import (
    _normalize_manifest as _normalize_manifest,
)
from modstore_server.employee_asset_pipeline_part03_part01 import (
    _sanitize_workflow_bundles as _sanitize_workflow_bundles,
)
