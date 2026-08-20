# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def _extract_python_code(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        from modstore_server.script_agent.llm_client import extract_code_block

        extracted = extract_code_block(raw, lang="python").strip()
        if extracted:
            return extracted
    except RECOVERABLE_ERRORS:
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
                    return (
                        False,
                        f"generated convert.py imports forbidden module: {alias.name}",
                    )
        if isinstance(node, _facade().ast.ImportFrom):
            if node.module in ("subprocess", "ctypes", "multiprocessing"):
                return (
                    False,
                    f"generated convert.py imports from forbidden module: {node.module}",
                )
    return (True, "")


def _auto_fix_generated_convert_py(
    src: str,
) -> _facade().Tuple[str, _facade().List[str]]:
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
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return (None, {"provider": "", "model": "", "warning": err})
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
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
                        if k
                        in {
                            "id",
                            "filename",
                            "kind",
                            "suffix",
                            "size",
                            "excel",
                            "preview",
                        }
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
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
    )
    if not result.get("ok"):
        return (
            None,
            {"provider": prov, "model": mdl, "warning": str(result.get("error") or "")},
        )
    code = _facade()._extract_python_code(str(result.get("content") or ""))
    ok, validation_error = _facade()._validate_generated_convert_py(code)
    if not ok:
        if _allow_builtin:
            fixed_code, fixes = _facade()._auto_fix_generated_convert_py(code)
            fixed_ok, fixed_error = _facade()._validate_generated_convert_py(fixed_code)
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
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return (None, {"provider": "", "model": "", "warning": err, "round": round_no})
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return (
            None,
            {
                "provider": prov,
                "model": mdl,
                "warning": "missing api key",
                "round": round_no,
            },
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
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
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
    ok, validation_error = _facade()._validate_generated_convert_py(code)
    if not ok:
        if allow_auto_fix:
            fixed_code, fixes = _facade()._auto_fix_generated_convert_py(code)
            fixed_ok, _fixed_error = _facade()._validate_generated_convert_py(fixed_code)
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
            {
                "provider": prov,
                "model": mdl,
                "warning": validation_error,
                "round": round_no,
            },
        )
    return (
        code.rstrip() + "\n",
        {"provider": prov, "model": mdl, "repaired": True, "round": round_no},
    )


def manifest_actions_handlers(
    mf: _facade().Dict[str, _facade().Any],
) -> _facade().List[str]:
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
        {"brief": str(mf.get("description") or "")},
        fallback=str(mf.get("description") or ""),
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
    if ext_l & {
        ".docx",
        ".doc",
    } and "direct_python" in _facade().manifest_actions_handlers(mf):
        return True
    return False
