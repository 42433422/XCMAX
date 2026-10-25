"""Package quality for workbench delivery."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

_LOG = logging.getLogger("modstore_server.workbench_api")


def _employee_handlers_contract_ok(pack_dir: Path) -> Tuple[bool, str]:
    from modstore_server.employee_asset_pipeline import (
        manifest_actions_handlers,
        manifest_expects_word_runtime,
        pack_has_direct_python_runtime,
    )
    from modstore_server.word_extract_runtime import validate_word_extract_backend

    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return (False, "manifest.json 缺失")
    try:
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (False, f"manifest 不可读：{exc}")
    handlers = manifest_actions_handlers(mf)
    rs_path = pack_dir / "rule_spec.json"
    if rs_path.is_file():
        try:
            rs = json.loads(rs_path.read_text(encoding="utf-8"))
            if isinstance(rs, dict):
                rk = rs.get("runtime_kind")
                if rk == "word_full_extract":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"Word 提取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    wx_errs, _ = validate_word_extract_backend(pack_dir)
                    if wx_errs:
                        return (False, wx_errs[0][:200])
                    return (True, "")
                if rk == "txt_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"TXT 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.txt_extract_runtime import (
                        validate_txt_read_backend,
                    )

                    tx_errs, _ = validate_txt_read_backend(pack_dir)
                    if tx_errs:
                        return (False, tx_errs[0][:200])
                    return (True, "")
                if rk == "csv_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"CSV 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.csv_tabular_runtime import (
                        validate_csv_read_backend,
                    )

                    cr_errs, _ = validate_csv_read_backend(pack_dir)
                    if cr_errs:
                        return (False, cr_errs[0][:200])
                    return (True, "")
                if rk == "csv_generate":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"CSV 生成员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.csv_tabular_runtime import (
                        validate_csv_generate_backend,
                    )

                    cg_errs, _ = validate_csv_generate_backend(pack_dir)
                    if cg_errs:
                        return (False, cg_errs[0][:200])
                    return (True, "")
                if rk == "excel_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"Excel 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.excel_tabular_runtime import (
                        validate_excel_read_backend,
                    )

                    er_errs, _ = validate_excel_read_backend(pack_dir)
                    if er_errs:
                        return (False, er_errs[0][:200])
                    return (True, "")
                if rk == "excel_generate":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"Excel 生成员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.excel_tabular_runtime import (
                        validate_excel_generate_backend,
                    )

                    eg_errs, _ = validate_excel_generate_backend(pack_dir)
                    if eg_errs:
                        return (False, eg_errs[0][:200])
                    return (True, "")
                if rk == "txt_generate":
                    if "direct_python" not in handlers:
                        return (
                            False,
                            f"TXT 生成员工 handlers 须含 direct_python，当前为 {handlers}",
                        )
                    from modstore_server.txt_extract_runtime import (
                        validate_txt_generate_backend,
                    )

                    tg_errs, _ = validate_txt_generate_backend(pack_dir)
                    if tg_errs:
                        return (False, tg_errs[0][:200])
                    return (True, "")
                if rk == "pdf_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"PDF 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.pdf_extract_runtime import (
                        validate_pdf_read_backend,
                    )

                    pr_errs, _ = validate_pdf_read_backend(pack_dir)
                    if pr_errs:
                        return (False, pr_errs[0][:200])
                    return (True, "")
                if rk == "pdf_generate":
                    if "direct_python" not in handlers:
                        return (
                            False,
                            f"PDF 生成员工 handlers 须含 direct_python，当前为 {handlers}",
                        )
                    from modstore_server.pdf_extract_runtime import (
                        validate_pdf_generate_backend,
                    )

                    pg_errs, _ = validate_pdf_generate_backend(pack_dir)
                    if pg_errs:
                        return (False, pg_errs[0][:200])
                    return (True, "")
        except (OSError, json.JSONDecodeError):
            pass
    if "direct_python" in handlers and manifest_expects_word_runtime(mf):
        if not pack_has_direct_python_runtime(pack_dir):
            return (
                False,
                "声明 Word direct_python 但缺少 rule_spec/vendor convert（请在工作台走完 generate）",
            )
        wx_errs, _ = validate_word_extract_backend(pack_dir)
        if wx_errs:
            return (False, wx_errs[0][:200])
    elif "direct_python" in handlers and (not pack_has_direct_python_runtime(pack_dir)):
        return (
            False,
            "声明 direct_python 但库内无 runtime 实现（画布保存不能替代 generate）",
        )
    return (True, "")


def _employee_quality_extras(
    pack_dir: Path,
    *,
    pipeline_label: str,
    validate_errors: Optional[List[str]] = None,
    mod_sandbox: Optional[Dict[str, Any]] = None,
    runtime_generation: Optional[Dict[str, Any]] = None,
    domain_smoke: Optional[Dict[str, Any]] = None,
    golden_comparison: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], bool, bool]:
    """Return extra quality items, runnable flag, critical_failed."""
    items: List[Dict[str, Any]] = []
    critical_failed = False
    runnable = True
    handlers_ok, handlers_msg = _employee_handlers_contract_ok(pack_dir)
    items.append(
        {
            "check": "handlers 契约",
            "ok": handlers_ok,
            "note": handlers_msg[:120],
            "critical": True,
        }
    )
    if not handlers_ok:
        critical_failed = True
        runnable = False
    builtin_runtime = pipeline_label in (
        "word_full_extract",
        "txt_full_read",
        "txt_generate",
        "pdf_full_read",
        "pdf_generate",
        "csv_full_read",
        "csv_generate",
        "excel_full_read",
        "excel_generate",
    )
    if builtin_runtime and pack_dir.is_dir():
        if pipeline_label == "word_full_extract":
            from modstore_server.word_extract_runtime import (
                validate_word_extract_backend,
            )

            rx_errs, rx_warns = validate_word_extract_backend(pack_dir)
            chk_id = "word_extract_runtime"
            chk_label = "Word 解析后端"
        elif pipeline_label == "txt_full_read":
            from modstore_server.txt_extract_runtime import validate_txt_read_backend

            rx_errs, rx_warns = validate_txt_read_backend(pack_dir)
            chk_id = "txt_read_runtime"
            chk_label = "TXT 读取后端"
        elif pipeline_label == "txt_generate":
            from modstore_server.txt_extract_runtime import (
                validate_txt_generate_backend,
            )

            rx_errs, rx_warns = validate_txt_generate_backend(pack_dir)
            chk_id = "txt_generate_runtime"
            chk_label = "TXT 生成后端"
        elif pipeline_label == "pdf_full_read":
            from modstore_server.pdf_extract_runtime import validate_pdf_read_backend

            rx_errs, rx_warns = validate_pdf_read_backend(pack_dir)
            chk_id = "pdf_read_runtime"
            chk_label = "PDF 读取后端"
        elif pipeline_label == "pdf_generate":
            from modstore_server.pdf_extract_runtime import (
                validate_pdf_generate_backend,
            )

            rx_errs, rx_warns = validate_pdf_generate_backend(pack_dir)
            chk_id = "pdf_generate_runtime"
            chk_label = "PDF 生成后端"
        elif pipeline_label == "excel_full_read":
            from modstore_server.excel_tabular_runtime import (
                validate_excel_read_backend,
            )

            rx_errs, rx_warns = validate_excel_read_backend(pack_dir)
            chk_id = "excel_read_runtime"
            chk_label = "Excel 读取后端"
        elif pipeline_label == "excel_generate":
            from modstore_server.excel_tabular_runtime import (
                validate_excel_generate_backend,
            )

            rx_errs, rx_warns = validate_excel_generate_backend(pack_dir)
            chk_id = "excel_generate_runtime"
            chk_label = "Excel 生成后端"
        elif pipeline_label == "csv_full_read":
            from modstore_server.csv_tabular_runtime import validate_csv_read_backend

            rx_errs, rx_warns = validate_csv_read_backend(pack_dir)
            chk_id = "csv_read_runtime"
            chk_label = "CSV 读取后端"
        elif pipeline_label == "csv_generate":
            from modstore_server.csv_tabular_runtime import (
                validate_csv_generate_backend,
            )

            rx_errs, rx_warns = validate_csv_generate_backend(pack_dir)
            chk_id = "csv_generate_runtime"
            chk_label = "CSV 生成后端"
        else:
            rx_errs, rx_warns = ([], [])
            chk_id = "unknown_runtime"
            chk_label = "未知 runtime"
        items.append(
            {
                "check": chk_label,
                "ok": not rx_errs,
                "note": (
                    "；".join(rx_errs[:2])
                    if rx_errs
                    else "；".join(rx_warns[:2])
                    if rx_warns
                    else ""
                ),
                "critical": True,
            }
        )
        if rx_errs:
            critical_failed = True
            runnable = False
        for chk in (mod_sandbox or {}).get("checks") or []:
            if isinstance(chk, dict) and chk.get("id") == chk_id:
                items.append(
                    {
                        "check": f"{chk_label} 自检",
                        "ok": bool(chk.get("ok")),
                        "note": str(chk.get("message") or "")[:120],
                        "critical": True,
                    }
                )
                if not chk.get("ok"):
                    critical_failed = True
                    runnable = False
    val_errs = [str(x) for x in validate_errors or [] if x]
    if val_errs:
        items.append(
            {
                "check": "validate 硬错误",
                "ok": False,
                "note": "；".join(val_errs[:3])[:200],
                "critical": True,
            }
        )
        critical_failed = True
        runnable = False
    if builtin_runtime or (isinstance(runtime_generation, dict) and runtime_generation):
        from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

        _rt = (
            cast(dict[str, Any], runtime_generation)
            if isinstance(runtime_generation, dict)
            else {}
        )
        _llm_ok = is_llm_codegen_source(_rt)
        items.append(
            {
                "check": "LLM convert 来源",
                "ok": _llm_ok,
                "note": str(_rt.get("source") or "missing")[:80],
                "critical": True,
            }
        )
        if not _llm_ok:
            critical_failed = True
            runnable = False
    _ds = cast(dict[str, Any], domain_smoke) if isinstance(domain_smoke, dict) else {}
    if _ds and _ds.get("skipped") is not True:
        items.append(
            {
                "check": "领域冒烟",
                "ok": _ds.get("ok") is not False,
                "note": str(_ds.get("error") or "")[:120],
                "critical": pipeline_label == "word_full_extract",
            }
        )
        if _ds.get("ok") is False and pipeline_label == "word_full_extract":
            critical_failed = True
            runnable = False
    _gc = (
        cast(dict[str, Any], golden_comparison)
        if isinstance(golden_comparison, dict)
        else {}
    )
    if _gc.get("golden_pack_id"):
        items.append(
            {
                "check": "黄金对比",
                "ok": bool(_gc.get("passed")),
                "note": f"parity={_gc.get('parity_score')}",
                "critical": pipeline_label == "word_full_extract",
            }
        )
        if not _gc.get("passed") and pipeline_label == "word_full_extract":
            critical_failed = True
            runnable = False
    return (items, runnable, critical_failed)
