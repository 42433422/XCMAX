# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type, var-annotated"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
    from modstore_server.mod_employee_impl_scaffold import (
        employee_py_system_prompt_gaps,
    )

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
                    from modstore_server.word_extract_runtime import (
                        validate_word_extract_backend,
                    )

                    wx_errs, wx_warns = validate_word_extract_backend(pack_dir)
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
                    from modstore_server.txt_extract_runtime import (
                        validate_txt_read_backend,
                    )

                    tx_errs, tx_warns = validate_txt_read_backend(pack_dir)
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
                    from modstore_server.txt_extract_runtime import (
                        validate_txt_generate_backend,
                    )

                    tg_errs, tg_warns = validate_txt_generate_backend(pack_dir)
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
                    from modstore_server.pdf_extract_runtime import (
                        validate_pdf_read_backend,
                    )

                    pr_errs, pr_warns = validate_pdf_read_backend(pack_dir)
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
                    from modstore_server.pdf_extract_runtime import (
                        validate_pdf_generate_backend,
                    )

                    pg_errs, pg_warns = validate_pdf_generate_backend(pack_dir)
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
                    from modstore_server.word_generate_runtime import (
                        validate_word_generate_backend,
                    )

                    wg_errs, wg_warns = validate_word_generate_backend(pack_dir)
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
                    from modstore_server.excel_tabular_runtime import (
                        validate_excel_read_backend,
                    )

                    er_errs, er_warns = validate_excel_read_backend(pack_dir)
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

                    eg_errs, eg_warns = validate_excel_generate_backend(pack_dir)
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
                    from modstore_server.csv_tabular_runtime import (
                        validate_csv_read_backend,
                    )

                    cr_errs, cr_warns = validate_csv_read_backend(pack_dir)
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
                    from modstore_server.csv_tabular_runtime import (
                        validate_csv_generate_backend,
                    )

                    cg_errs, cg_warns = validate_csv_generate_backend(pack_dir)
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
        except RECOVERABLE_ERRORS:
            pass
    return results
