# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _check_vibe_coding_capability(
    pack_dir: _facade().Path, wf_attach: _facade().Dict[str, _facade().Any]
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """Inspect pack_dir + workflow attachment for vibe-coding completeness.

    Returns check-result dicts ``{id, ok, message}`` merged into mod_sandbox.
    ``vibe_logic_present`` is observability-only (always ``ok``). Other ids such as
    ``vibe_system_prompt_quality`` / ``vibe_how_to_do_logic`` set ``ok=False``
    when gaps are detected; the employee pipeline treats aggregate ``ok`` as
    failing mod_sandbox and may hard-fail when ``vibe_system_prompt_quality`` is bad.
    """
    import re as _re
    from modstore_server.mod_employee_impl_scaffold import employee_py_system_prompt_gaps

    results: _facade().List[_facade().Dict[str, _facade().Any]] = []
    nl_data = wf_attach.get("nl") if isinstance(wf_attach, dict) else None
    skill_blueprints = []
    if isinstance(nl_data, dict):
        skill_blueprints = nl_data.get("skill_blueprints") or []
    vibe_logic_count = sum(
        (
            1
            for bp in skill_blueprints
            if isinstance(bp, dict)
            and str(bp.get("static_logic", {}).get("type") or "").startswith("vibe")
        )
    )
    results.append(
        {
            "id": "vibe_logic_present",
            "ok": True,
            "message": (
                f"Skill 组含 {vibe_logic_count} 个 vibe 类 logic / {int(wf_attach.get('eskill_count') or 0)} 个 ESkill"
                if isinstance(wf_attach, dict) and wf_attach
                else "未创建画布工作流，vibe-coding 能力检查已跳过"
            ),
        }
    )
    emp_dir = pack_dir / "backend" / "employees"
    if emp_dir.is_dir():
        prompt_gaps = employee_py_system_prompt_gaps(emp_dir)
        hollow_files = prompt_gaps["hollow"]
        missing_prompt_files = prompt_gaps["missing"]
        if hollow_files:
            results.append(
                {
                    "id": "vibe_system_prompt_quality",
                    "ok": False,
                    "message": f"以下员工文件的 SYSTEM_PROMPT 为空洞占位，缺少角色/任务/输出格式说明： {', '.join(hollow_files[:5])}",
                }
            )
        elif missing_prompt_files:
            results.append(
                {
                    "id": "vibe_system_prompt_quality",
                    "ok": False,
                    "message": f"以下员工文件未定义 SYSTEM_PROMPT 常量（员工只能调 LLM 但无明确指导）： {', '.join(missing_prompt_files[:5])}",
                }
            )
        else:
            results.append(
                {
                    "id": "vibe_system_prompt_quality",
                    "ok": True,
                    "message": "员工文件均定义了 SYSTEM_PROMPT 常量",
                }
            )
        thin_impl_files: _facade().List[str] = []
        for py_file in sorted(emp_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(src.strip()) < 200:
                continue
            has_payload_steps = bool(
                _re.search(
                    "(?:payload|project_analysis|pa|manifests|tech_stack|scripts|config|data)\\s*\\.\\s*(?:get|items|values|keys)\\s*\\(",
                    src,
                )
                or _re.search("payload\\s*\\[", src)
                or _re.search("for\\s+\\w+\\s+in\\s+", src)
                or _re.search("os\\.|glob\\.|pathlib\\.", src)
            )
            if not has_payload_steps and "call_llm" in src:
                thin_impl_files.append(py_file.name)
        if thin_impl_files:
            results.append(
                {
                    "id": "vibe_how_to_do_logic",
                    "ok": False,
                    "message": f"以下员工文件调用了 call_llm 但缺乏数据提取/目录扫描等前置步骤，建议补充「怎么做」逻辑： {', '.join(thin_impl_files[:5])}",
                }
            )
        else:
            results.append(
                {
                    "id": "vibe_how_to_do_logic",
                    "ok": True,
                    "message": "员工文件包含数据处理步骤（怎么做逻辑检查通过）",
                }
            )
    else:
        results.append(
            {
                "id": "vibe_system_prompt_quality",
                "ok": True,
                "message": "无 backend/employees 目录，跳过员工代码检查",
            }
        )
        results.append(
            {
                "id": "vibe_how_to_do_logic",
                "ok": True,
                "message": "无 backend/employees 目录，跳过怎么做检查",
            }
        )
    rule_spec_path = pack_dir / "rule_spec.json"
    if rule_spec_path.is_file():
        try:
            rs = _facade().json.loads(rule_spec_path.read_text(encoding="utf-8"))
            if isinstance(rs, dict):
                rk = rs.get("runtime_kind")
                if rk == "word_full_extract":
                    from modstore_server.word_extract_runtime import validate_word_extract_backend

                    (wx_errs, wx_warns) = validate_word_extract_backend(pack_dir)
                    results.append(
                        {
                            "id": "word_extract_runtime",
                            "ok": not wx_errs,
                            "message": (
                                "Word 全量提取 runtime 检查通过"
                                if not wx_errs
                                else "；".join(wx_errs[:3])
                            ),
                        }
                    )
                    if wx_warns:
                        results.append(
                            {
                                "id": "word_extract_coverage",
                                "ok": len(wx_warns) <= 2,
                                "message": "；".join(wx_warns[:4]),
                            }
                        )
                elif rk == "txt_full_read":
                    from modstore_server.txt_extract_runtime import validate_txt_read_backend

                    (tx_errs, tx_warns) = validate_txt_read_backend(pack_dir)
                    results.append(
                        {
                            "id": "txt_read_runtime",
                            "ok": not tx_errs,
                            "message": (
                                "TXT 全量读取 runtime 检查通过"
                                if not tx_errs
                                else "；".join(tx_errs[:3])
                            ),
                        }
                    )
                    if tx_warns:
                        results.append(
                            {
                                "id": "txt_read_coverage",
                                "ok": len(tx_warns) <= 2,
                                "message": "；".join(tx_warns[:4]),
                            }
                        )
                elif rk == "txt_generate":
                    from modstore_server.txt_extract_runtime import validate_txt_generate_backend

                    (tg_errs, tg_warns) = validate_txt_generate_backend(pack_dir)
                    results.append(
                        {
                            "id": "txt_generate_runtime",
                            "ok": not tg_errs,
                            "message": (
                                "TXT 生成 runtime 检查通过"
                                if not tg_errs
                                else "；".join(tg_errs[:3])
                            ),
                        }
                    )
                    if tg_warns:
                        results.append(
                            {
                                "id": "txt_generate_coverage",
                                "ok": len(tg_warns) <= 2,
                                "message": "；".join(tg_warns[:4]),
                            }
                        )
                elif rk == "pdf_full_read":
                    from modstore_server.pdf_extract_runtime import validate_pdf_read_backend

                    (pr_errs, pr_warns) = validate_pdf_read_backend(pack_dir)
                    results.append(
                        {
                            "id": "pdf_read_runtime",
                            "ok": not pr_errs,
                            "message": (
                                "PDF 全量读取 runtime 检查通过"
                                if not pr_errs
                                else "；".join(pr_errs[:3])
                            ),
                        }
                    )
                    if pr_warns:
                        results.append(
                            {
                                "id": "pdf_read_coverage",
                                "ok": len(pr_warns) <= 2,
                                "message": "；".join(pr_warns[:4]),
                            }
                        )
                elif rk == "pdf_generate":
                    from modstore_server.pdf_extract_runtime import validate_pdf_generate_backend

                    (pg_errs, pg_warns) = validate_pdf_generate_backend(pack_dir)
                    results.append(
                        {
                            "id": "pdf_generate_runtime",
                            "ok": not pg_errs,
                            "message": (
                                "PDF 生成 runtime 检查通过"
                                if not pg_errs
                                else "；".join(pg_errs[:3])
                            ),
                        }
                    )
                    if pg_warns:
                        results.append(
                            {
                                "id": "pdf_generate_coverage",
                                "ok": len(pg_warns) <= 2,
                                "message": "；".join(pg_warns[:4]),
                            }
                        )
                elif rk == "word_generate":
                    from modstore_server.word_generate_runtime import validate_word_generate_backend

                    (wg_errs, wg_warns) = validate_word_generate_backend(pack_dir)
                    results.append(
                        {
                            "id": "word_generate_runtime",
                            "ok": not wg_errs,
                            "message": (
                                "Word 生成 runtime 检查通过"
                                if not wg_errs
                                else "；".join(wg_errs[:3])
                            ),
                        }
                    )
                    if wg_warns:
                        results.append(
                            {
                                "id": "word_generate_coverage",
                                "ok": len(wg_warns) <= 2,
                                "message": "；".join(wg_warns[:4]),
                            }
                        )
                elif rk == "excel_full_read":
                    from modstore_server.excel_tabular_runtime import validate_excel_read_backend

                    (er_errs, er_warns) = validate_excel_read_backend(pack_dir)
                    results.append(
                        {
                            "id": "excel_read_runtime",
                            "ok": not er_errs,
                            "message": (
                                "Excel 全量读取 runtime 检查通过"
                                if not er_errs
                                else "；".join(er_errs[:3])
                            ),
                        }
                    )
                    if er_warns:
                        results.append(
                            {
                                "id": "excel_read_coverage",
                                "ok": len(er_warns) <= 2,
                                "message": "；".join(er_warns[:4]),
                            }
                        )
                elif rk == "excel_generate":
                    from modstore_server.excel_tabular_runtime import (
                        validate_excel_generate_backend,
                    )

                    (eg_errs, eg_warns) = validate_excel_generate_backend(pack_dir)
                    results.append(
                        {
                            "id": "excel_generate_runtime",
                            "ok": not eg_errs,
                            "message": (
                                "Excel 生成 runtime 检查通过"
                                if not eg_errs
                                else "；".join(eg_errs[:3])
                            ),
                        }
                    )
                    if eg_warns:
                        results.append(
                            {
                                "id": "excel_generate_coverage",
                                "ok": len(eg_warns) <= 2,
                                "message": "；".join(eg_warns[:4]),
                            }
                        )
                elif rk == "csv_full_read":
                    from modstore_server.csv_tabular_runtime import validate_csv_read_backend

                    (cr_errs, cr_warns) = validate_csv_read_backend(pack_dir)
                    results.append(
                        {
                            "id": "csv_read_runtime",
                            "ok": not cr_errs,
                            "message": (
                                "CSV 全量读取 runtime 检查通过"
                                if not cr_errs
                                else "；".join(cr_errs[:3])
                            ),
                        }
                    )
                    if cr_warns:
                        results.append(
                            {
                                "id": "csv_read_coverage",
                                "ok": len(cr_warns) <= 2,
                                "message": "；".join(cr_warns[:4]),
                            }
                        )
                elif rk == "csv_generate":
                    from modstore_server.csv_tabular_runtime import validate_csv_generate_backend

                    (cg_errs, cg_warns) = validate_csv_generate_backend(pack_dir)
                    results.append(
                        {
                            "id": "csv_generate_runtime",
                            "ok": not cg_errs,
                            "message": (
                                "CSV 生成 runtime 检查通过"
                                if not cg_errs
                                else "；".join(cg_errs[:3])
                            ),
                        }
                    )
                    if cg_warns:
                        results.append(
                            {
                                "id": "csv_generate_coverage",
                                "ok": len(cg_warns) <= 2,
                                "message": "；".join(cg_warns[:4]),
                            }
                        )
        except Exception:
            pass
    return results


def _employee_handlers_contract_ok(pack_dir: _facade().Path) -> _facade().Tuple[bool, str]:
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
        mf = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError) as exc:
        return (False, f"manifest 不可读：{exc}")
    handlers = manifest_actions_handlers(mf)
    rs_path = pack_dir / "rule_spec.json"
    if rs_path.is_file():
        try:
            rs = _facade().json.loads(rs_path.read_text(encoding="utf-8"))
            if isinstance(rs, dict):
                rk = rs.get("runtime_kind")
                if rk == "word_full_extract":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"Word 提取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    (wx_errs, _) = validate_word_extract_backend(pack_dir)
                    if wx_errs:
                        return (False, wx_errs[0][:200])
                    return (True, "")
                if rk == "txt_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"TXT 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.txt_extract_runtime import validate_txt_read_backend

                    (tx_errs, _) = validate_txt_read_backend(pack_dir)
                    if tx_errs:
                        return (False, tx_errs[0][:200])
                    return (True, "")
                if rk == "csv_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"CSV 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.csv_tabular_runtime import validate_csv_read_backend

                    (cr_errs, _) = validate_csv_read_backend(pack_dir)
                    if cr_errs:
                        return (False, cr_errs[0][:200])
                    return (True, "")
                if rk == "csv_generate":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"CSV 生成员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.csv_tabular_runtime import validate_csv_generate_backend

                    (cg_errs, _) = validate_csv_generate_backend(pack_dir)
                    if cg_errs:
                        return (False, cg_errs[0][:200])
                    return (True, "")
                if rk == "excel_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"Excel 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.excel_tabular_runtime import validate_excel_read_backend

                    (er_errs, _) = validate_excel_read_backend(pack_dir)
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

                    (eg_errs, _) = validate_excel_generate_backend(pack_dir)
                    if eg_errs:
                        return (False, eg_errs[0][:200])
                    return (True, "")
                if rk == "txt_generate":
                    if "direct_python" not in handlers:
                        return (
                            False,
                            f"TXT 生成员工 handlers 须含 direct_python，当前为 {handlers}",
                        )
                    from modstore_server.txt_extract_runtime import validate_txt_generate_backend

                    (tg_errs, _) = validate_txt_generate_backend(pack_dir)
                    if tg_errs:
                        return (False, tg_errs[0][:200])
                    return (True, "")
                if rk == "pdf_full_read":
                    if handlers != ["direct_python"]:
                        return (
                            False,
                            f"PDF 读取员工 handlers 应为 ['direct_python']，当前为 {handlers}",
                        )
                    from modstore_server.pdf_extract_runtime import validate_pdf_read_backend

                    (pr_errs, _) = validate_pdf_read_backend(pack_dir)
                    if pr_errs:
                        return (False, pr_errs[0][:200])
                    return (True, "")
                if rk == "pdf_generate":
                    if "direct_python" not in handlers:
                        return (
                            False,
                            f"PDF 生成员工 handlers 须含 direct_python，当前为 {handlers}",
                        )
                    from modstore_server.pdf_extract_runtime import validate_pdf_generate_backend

                    (pg_errs, _) = validate_pdf_generate_backend(pack_dir)
                    if pg_errs:
                        return (False, pg_errs[0][:200])
                    return (True, "")
        except (OSError, _facade().json.JSONDecodeError):
            pass
    if "direct_python" in handlers and manifest_expects_word_runtime(mf):
        if not pack_has_direct_python_runtime(pack_dir):
            return (
                False,
                "声明 Word direct_python 但缺少 rule_spec/vendor convert（请在工作台走完 generate）",
            )
        (wx_errs, _) = validate_word_extract_backend(pack_dir)
        if wx_errs:
            return (False, wx_errs[0][:200])
    elif "direct_python" in handlers and (not pack_has_direct_python_runtime(pack_dir)):
        return (False, "声明 direct_python 但库内无 runtime 实现（画布保存不能替代 generate）")
    return (True, "")


def _employee_quality_extras(
    pack_dir: _facade().Path,
    *,
    pipeline_label: str,
    validate_errors: _facade().Optional[_facade().List[str]] = None,
    mod_sandbox: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    runtime_generation: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    domain_smoke: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    golden_comparison: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], bool, bool]:
    """Return extra quality items, runnable flag, critical_failed."""
    items: _facade().List[_facade().Dict[str, _facade().Any]] = []
    critical_failed = False
    runnable = True
    (handlers_ok, handlers_msg) = _facade()._employee_handlers_contract_ok(pack_dir)
    items.append(
        {"check": "handlers 契约", "ok": handlers_ok, "note": handlers_msg[:120], "critical": True}
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
            from modstore_server.word_extract_runtime import validate_word_extract_backend

            (rx_errs, rx_warns) = validate_word_extract_backend(pack_dir)
            chk_id = "word_extract_runtime"
            chk_label = "Word 解析后端"
        elif pipeline_label == "txt_full_read":
            from modstore_server.txt_extract_runtime import validate_txt_read_backend

            (rx_errs, rx_warns) = validate_txt_read_backend(pack_dir)
            chk_id = "txt_read_runtime"
            chk_label = "TXT 读取后端"
        elif pipeline_label == "txt_generate":
            from modstore_server.txt_extract_runtime import validate_txt_generate_backend

            (rx_errs, rx_warns) = validate_txt_generate_backend(pack_dir)
            chk_id = "txt_generate_runtime"
            chk_label = "TXT 生成后端"
        elif pipeline_label == "pdf_full_read":
            from modstore_server.pdf_extract_runtime import validate_pdf_read_backend

            (rx_errs, rx_warns) = validate_pdf_read_backend(pack_dir)
            chk_id = "pdf_read_runtime"
            chk_label = "PDF 读取后端"
        elif pipeline_label == "pdf_generate":
            from modstore_server.pdf_extract_runtime import validate_pdf_generate_backend

            (rx_errs, rx_warns) = validate_pdf_generate_backend(pack_dir)
            chk_id = "pdf_generate_runtime"
            chk_label = "PDF 生成后端"
        elif pipeline_label == "excel_full_read":
            from modstore_server.excel_tabular_runtime import validate_excel_read_backend

            (rx_errs, rx_warns) = validate_excel_read_backend(pack_dir)
            chk_id = "excel_read_runtime"
            chk_label = "Excel 读取后端"
        elif pipeline_label == "excel_generate":
            from modstore_server.excel_tabular_runtime import validate_excel_generate_backend

            (rx_errs, rx_warns) = validate_excel_generate_backend(pack_dir)
            chk_id = "excel_generate_runtime"
            chk_label = "Excel 生成后端"
        elif pipeline_label == "csv_full_read":
            from modstore_server.csv_tabular_runtime import validate_csv_read_backend

            (rx_errs, rx_warns) = validate_csv_read_backend(pack_dir)
            chk_id = "csv_read_runtime"
            chk_label = "CSV 读取后端"
        elif pipeline_label == "csv_generate":
            from modstore_server.csv_tabular_runtime import validate_csv_generate_backend

            (rx_errs, rx_warns) = validate_csv_generate_backend(pack_dir)
            chk_id = "csv_generate_runtime"
            chk_label = "CSV 生成后端"
        else:
            (rx_errs, rx_warns) = ([], [])
            chk_id = "unknown_runtime"
            chk_label = "未知 runtime"
        items.append(
            {
                "check": chk_label,
                "ok": not rx_errs,
                "note": (
                    "；".join(rx_errs[:2])
                    if rx_errs
                    else "；".join(rx_warns[:2]) if rx_warns else ""
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

        _rt = runtime_generation if isinstance(runtime_generation, dict) else {}
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
    _ds = domain_smoke if isinstance(domain_smoke, dict) else {}
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
    _gc = golden_comparison if isinstance(golden_comparison, dict) else {}
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


def _refresh_employee_pack_catalog_zip(
    db: _facade().Session, user: _facade().User, pack_dir: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    """Rebuild stored .xcemp after in-place manifest edits.

    ``run_employee_ai_scaffold_async`` first imports/saves the package, then the
    employee pipeline may mutate ``library/<pack>/manifest.json`` (for example
    writing workflow_id into employee_config_v2).  The catalog runtime reads the
    stored .xcemp, not the library folder, so rebuild and re-register that file.
    """
    from modstore_server.catalog_store import append_package, package_manifest_alignment_errors
    from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest

    raw = _facade()._load_registry_aligned_employee_manifest(pack_dir, pack_dir.name)
    pack_id = str(raw.get("id") or pack_dir.name).strip() or pack_dir.name
    mf_path = pack_dir / "manifest.json"
    mf_path.write_text(
        _facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        reconcile_employee_pack_manifest(pack_dir, brief="")
        raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
        pack_id = str(raw.get("id") or pack_dir.name).strip() or pack_dir.name
    except Exception:
        pass
    try:
        from modstore_server.employee_asset_pipeline import build_employee_pack_zip_for_library

        raw_zip = build_employee_pack_zip_for_library(pack_id, raw, pack_dir=pack_dir)
    except Exception:
        raw_zip = _facade().build_employee_pack_zip(pack_id, raw)
    with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        rec = {
            "id": pack_id,
            "name": str(raw.get("name") or pack_id),
            "version": str(raw.get("version") or "1.0.0"),
            "description": str(raw.get("description") or ""),
            "artifact": "employee_pack",
            "industry": str(raw.get("industry") or "通用"),
            "release_channel": "stable",
            "commerce": raw.get("commerce") or {"mode": "free", "price": 0},
            "license": {"type": "personal", "verify_url": None},
        }
        align_errs = package_manifest_alignment_errors(rec, tmp_path)
        if align_errs:
            raise ValueError("员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs))
        saved = append_package(rec, tmp_path)
        row = (
            db.query(_facade().CatalogItem).filter(_facade().CatalogItem.pkg_id == pack_id).first()
        )
        if not row:
            row = _facade().CatalogItem(pkg_id=pack_id, author_id=user.id)
            db.add(row)
        row.version = saved.get("version") or rec["version"]
        row.name = saved.get("name") or rec["name"]
        row.description = saved.get("description") or rec["description"]
        row.price = 0.0
        row.artifact = "employee_pack"
        row.industry = saved.get("industry") or rec["industry"]
        row.stored_filename = saved.get("stored_filename") or ""
        row.sha256 = saved.get("sha256") or ""
        db.commit()
        try:
            from modstore_server.api.catalog_public_routes import _invalidate_catalog_list_caches

            _invalidate_catalog_list_caches(pack_id, row.version)
        except Exception:
            pass
        try:
            from modstore_server.employee_asset_pipeline import mirror_catalog_file_to_market_files

            mirror_catalog_file_to_market_files(row.stored_filename)
        except Exception:
            pass
        return saved
    finally:
        tmp_path.unlink(missing_ok=True)


def _assert_employee_catalog_registered(db: _facade().Session, pack_id: str) -> bool:
    """Return True when pack_id is visible to employee_executor (DB or packages.json)."""
    pid = str(pack_id or "").strip()
    if not pid:
        return False
    row = (
        db.query(_facade().CatalogItem)
        .filter(
            _facade().CatalogItem.pkg_id == pid, _facade().CatalogItem.artifact == "employee_pack"
        )
        .first()
    )
    if row:
        return True
    try:
        from modstore_server.catalog_store import employee_pack_records_from_store

        rec = employee_pack_records_from_store().get(pid)
        return isinstance(rec, dict)
    except Exception:
        return False


def _load_registry_aligned_employee_manifest(
    pack_dir: _facade().Path, pack_id: str
) -> _facade().Dict[str, _facade().Any]:
    mf = pack_dir / "manifest.json"
    raw = _facade().json.loads(mf.read_text(encoding="utf-8"))
    (aligned, errs) = _facade().normalize_editor_manifest_for_registry(raw, pack_id)
    if errs:
        from modman.artifact_constants import normalize_artifact

        if normalize_artifact(aligned) != "employee_pack":
            raise ValueError("manifest 规范化失败: " + "; ".join(errs))
    return aligned
