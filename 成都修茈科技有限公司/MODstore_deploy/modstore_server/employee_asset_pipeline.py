# isort: skip_file
# ruff: noqa: E402, F401
"""Asset-driven employee_pack generation helpers.

This module upgrades the workbench "make employee" path from a pure prompt
manifest generator into a file-aware direct_python pack builder.  Uploaded
templates and examples stay as real files; the LLM only receives structured
summaries and generates code against a stable runtime scaffold.
"""

from __future__ import annotations

import ast
import io
import json
import os
import py_compile
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from modstore_server.csv_tabular_runtime import (
    build_csv_generate_rule_spec,
    build_csv_read_rule_spec,
    is_csv_full_read,
    is_csv_generate,
    render_csv_generate_convert_module,
    render_csv_read_convert_module,
)
from modstore_server.employee_ai_scaffold import parse_employee_pack_llm_json
from modstore_server.employee_pack_blueprints_template import (
    render_employee_pack_blueprints_py,
)
from modstore_server.excel_tabular_runtime import (
    build_excel_generate_rule_spec,
    build_excel_read_rule_spec,
    is_excel_full_read,
    is_excel_generate,
    render_excel_generate_convert_module,
    render_excel_read_convert_module,
)
from modstore_server.json_report_runtime import (
    build_json_quant_report_rule_spec,
    is_json_quant_report,
    render_json_report_convert_module,
)
from modstore_server.kitten_chart_runtime import (
    build_kitten_chart_rule_spec,
    is_kitten_chart_viz,
    render_kitten_chart_convert_module,
)
from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.mod_ai_scaffold import normalize_mod_id
from modstore_server.mod_employee_impl_scaffold import sanitize_employee_stem
from modstore_server.mod_scaffold_runner import (
    chat_dispatch,
    import_zip,
    modstore_library_path,
    resolve_llm_provider_model_auto,
)
from modstore_server.models import CatalogItem, User
from modstore_server.pdf_extract_runtime import (
    build_pdf_generate_rule_spec,
    build_pdf_read_rule_spec,
    is_pdf_full_read,
    is_pdf_generate,
    render_pdf_generate_convert_module,
    render_pdf_read_convert_module,
)
from modstore_server.ppt_extract_runtime import (
    build_ppt_generate_rule_spec,
    build_ppt_read_rule_spec,
    is_ppt_full_read,
    is_ppt_generate,
    render_ppt_generate_convert_module,
    render_ppt_read_convert_module,
)
from modstore_server.txt_extract_runtime import (
    build_txt_generate_rule_spec,
    build_txt_read_rule_spec,
    is_txt_full_read,
    is_txt_generate,
    render_txt_generate_convert_module,
    render_txt_read_convert_module,
)
from modstore_server.word_extract_runtime import (
    build_word_extract_rule_spec,
    is_word_full_extract,
    render_word_fallback_convert_module,
)
from modstore_server.word_generate_runtime import (
    build_word_generate_rule_spec,
    is_word_generate,
    render_word_generate_convert_module,
)

EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".py", ".yaml", ".yml"}

_LLM_CHAIN_MARKERS = re.compile(
    r"初始想法|澄清对话|<<<PLAN_|需要简短|不超过\d+个|字符计数|计算字符|"
    r"总结：\s*-|现在，构建|确保不泄露|从用户指令看|作为需求摘要|"
    r"输出格式必须严格|不能输出流程图|不能输出选项|不能输出执行清单|"
    r"当前制作类型|这可能意味着|为安全起见|或许更简洁|标准中文字符|"
    r"计算字符数|字符数.*不超过|以上.*字符",
)
_LLM_CHAIN_BLOCK_START = re.compile(r"【.*?(想法|对话|澄清|规划|分析)】")
_LLM_CHAIN_BLOCK_END = re.compile(r"【.*?(助手|用户|回答|结果|输出)】|<<<END")


from modstore_server.employee_asset_pipeline_part01 import (
    _clean_brief_for_description as _clean_brief_for_description,
    _safe_basename as _safe_basename,
    _classify_asset as _classify_asset,
    _runtime_module_name as _runtime_module_name,
    _runtime_package_name as _runtime_package_name,
)

DOC_SUFFIXES = {".docx", ".doc", ".pdf", ".rtf"}


from modstore_server.employee_asset_pipeline_part02 import (
    _infer_accepted_extensions as _infer_accepted_extensions,
    _infer_asset_runtime_kind as _infer_asset_runtime_kind,
    _read_text_preview as _read_text_preview,
    _excel_summary as _excel_summary,
    prepare_employee_assets as prepare_employee_assets,
    _preflight_scaffold_write_access as _preflight_scaffold_write_access,
    build_rule_spec as build_rule_spec,
    _slug_from_brief as _slug_from_brief,
    _employee_name_from_brief as _employee_name_from_brief,
    _template_storage_relpath as _template_storage_relpath,
    _employee_id_from_pack_id as _employee_id_from_pack_id,
)


from modstore_server.employee_asset_pipeline_part03 import (
    _fallback_manifest as _fallback_manifest,
    _normalize_manifest as _normalize_manifest,
    _sanitize_workflow_bundles as _sanitize_workflow_bundles,
)

_PLACEHOLDER_BRIEF = re.compile(r"（无回复）|相处报备|开始写吧", re.I)


from modstore_server.employee_asset_pipeline_part04 import (
    reconcile_employee_pack_manifest as reconcile_employee_pack_manifest,
    enrich_manifest_productivity_fields as enrich_manifest_productivity_fields,
    design_asset_employee_manifest as design_asset_employee_manifest,
    _rule_spec_python_literal as _rule_spec_python_literal,
    render_direct_python_asset_worker as render_direct_python_asset_worker,
    _fallback_convert_module as _fallback_convert_module,
    render_runtime_modules as render_runtime_modules,
    render_build_xcemp_py as render_build_xcemp_py,
    _extract_python_code as _extract_python_code,
    _validate_generated_convert_py as _validate_generated_convert_py,
    _auto_fix_generated_convert_py as _auto_fix_generated_convert_py,
    generate_runtime_convert_module as generate_runtime_convert_module,
    repair_runtime_convert_module as repair_runtime_convert_module,
    manifest_actions_handlers as manifest_actions_handlers,
    manifest_expects_word_runtime as manifest_expects_word_runtime,
)


from modstore_server.employee_asset_pipeline_part05 import (
    pack_has_direct_python_runtime as pack_has_direct_python_runtime,
)

DIRECT_PYTHON_RUNTIME_MISSING_MSG = (
    "manifest 声明了 Word/direct_python，但本地库中缺少 rule_spec 与 backend/vendor/convert。"
    "请在工作台「做员工」流水线完成 generate 步后再在浏览室保存；"
    "画布保存不能替代资产生成，否则会覆盖为仅含 LLM 脚手架的空包。"
)


from modstore_server.employee_asset_pipeline_part06 import (
    persist_manifest_to_pack_dir as persist_manifest_to_pack_dir,
    build_employee_pack_zip_for_library as build_employee_pack_zip_for_library,
    build_employee_pack_zip_from_dir as build_employee_pack_zip_from_dir,
    mirror_catalog_file_to_market_files as mirror_catalog_file_to_market_files,
    _copy_template_assets as _copy_template_assets,
    materialize_asset_employee_pack as materialize_asset_employee_pack,
    validate_asset_employee_pack as validate_asset_employee_pack,
    run_asset_employee_scaffold_async as run_asset_employee_scaffold_async,
    run_word_extract_employee_scaffold_async as run_word_extract_employee_scaffold_async,
)
