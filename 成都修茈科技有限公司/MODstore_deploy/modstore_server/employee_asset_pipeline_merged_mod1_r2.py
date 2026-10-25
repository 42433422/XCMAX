"""Auto-merged part* modules (debt24)."""

# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file

from __future__ import annotations

import importlib

from modstore_server.infrastructure.private_asset_storage import (
    draft_asset_directory,
    reset_draft_directory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from employee_asset_pipeline_part01.py ---
"""Implementation extracted from the public facade module."""


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


# --- from employee_asset_pipeline_part05.py ---
"""Implementation extracted from the public facade module."""


def pack_has_direct_python_runtime(pack_dir: _facade().Path) -> bool:
    """Disk pack contains vendor convert and/or rule_spec for asset/direct_python employees."""
    rs = pack_dir / "rule_spec.json"
    if rs.is_file():
        try:
            data = _facade().json.loads(rs.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("runtime_kind") in (
                "word_full_extract",
                "txt_full_read",
                "txt_generate",
                "pdf_full_read",
                "pdf_generate",
                "csv_full_read",
                "csv_generate",
                "generic_excel_transform",
                "contract_doc_review",
                "doc_template_transform",
            ):
                return True
        except (OSError, _facade().json.JSONDecodeError):
            pass
    backend = pack_dir / "backend"
    if not backend.is_dir():
        return False
    for py_path in backend.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def convert_file" in text and "vendor" in py_path.as_posix().lower():
            return True
        if "def convert" in text and "_import_runtime" in text:
            return True
    return False


# --- from employee_asset_pipeline_part06_part01_part01.py ---
"""Implementation extracted from the public facade module."""


