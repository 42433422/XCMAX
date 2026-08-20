# mypy: disable-error-code="union-attr"
"""员工制作流水线六维质量评估（确定性汇总，不重复跑沙箱）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.employee_brief_utils import compact_routing_brief
from modstore_server.employee_six_dimension_report import (
    SIX_DIMENSION_KEYS,
)
from modstore_server.employee_six_dimension_report import clamp_score as _clamp_score
from modstore_server.employee_six_dimension_report import dim_entry as _dim_entry
from modstore_server.employee_six_dimension_report import (
    finalize_dimension_report as _finalize_dimension_report,
)
from modstore_server.employee_six_dimension_report import score_to_grade as score_to_grade
from modstore_server.operational_errors import BOUNDARY_ERRORS


def build_six_dimension_report_from_llm_dimensions(
    llm_dims: Dict[str, Dict[str, Any]],
    *,
    pipeline_label: str,
    baseline_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """由 LLM 输出的六维分数构建完整报告（可选与规则基线加权融合）。"""
    dims: Dict[str, Dict[str, Any]] = {}
    for k in SIX_DIMENSION_KEYS:
        ent = llm_dims.get(k) if isinstance(llm_dims.get(k), dict) else {}
        try:
            score = _clamp_score(float(ent.get("score", 0)))
        except (TypeError, ValueError):
            score = 0
        reasons = [str(r)[:200] for r in (ent.get("reasons") or []) if str(r).strip()][:4]
        if baseline_report:
            base_ent = (baseline_report.get("dimensions") or {}).get(k)
            if isinstance(base_ent, dict):
                try:
                    base_score = float(base_ent.get("score", 0))
                    score = _clamp_score(0.35 * base_score + 0.65 * score)
                except (TypeError, ValueError):
                    pass
                for br in (base_ent.get("reasons") or [])[:2]:
                    tag = f"规则基线：{br}"
                    if tag not in reasons:
                        reasons.append(tag[:200])
        if not reasons:
            reasons = ["LLM 评估"]
        dims[k] = _dim_entry(k, score, reasons)
    return _finalize_dimension_report(dims, pipeline_label, scoring_source="llm")


def _check_ok(mod_checks: List[Dict[str, Any]], check_id: str) -> Optional[bool]:
    for c in mod_checks:
        if str(c.get("id") or "") == check_id:
            return bool(c.get("ok"))
    return None


def _score_requirement_clarity(
    *,
    routing_brief: str,
    structured_requirement: Optional[Dict[str, Any]],
    spec_warnings: Optional[List[str]],
    pipeline_label: str,
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    rb = compact_routing_brief(routing_brief, max_len=500) or (routing_brief or "").strip()
    score = 0.0
    if len(rb) >= 10:
        score += 45
        reasons.append("routing brief 有效")
    elif rb:
        score += 20
        reasons.append("routing brief 偏短")
    else:
        reasons.append("缺少有效 routing brief")
    if rb and "【初始想法】" not in rb and "相处报备" not in rb:
        score += 20
    else:
        reasons.append("brief 仍含规划污染标记")
    if isinstance(structured_requirement, dict) and structured_requirement:
        score += 20
        handlers = structured_requirement.get("suggested_handlers")
        if pipeline_label in (
            "word_full_extract",
            "word_generate",
            "txt_full_read",
            "txt_generate",
        ):
            if isinstance(handlers, list) and "direct_python" in handlers:
                score += 15
                reasons.append(f"{pipeline_label} 场景已识别 direct_python")
            else:
                reasons.append(f"{pipeline_label} 场景未声明 direct_python handlers")
    warns = [str(x) for x in (spec_warnings or []) if x]
    if warns:
        score -= min(20, len(warns) * 5)
        reasons.append(f"spec 提示 {len(warns)} 条")
    return _clamp_score(score), reasons


def _score_pack_compliance(
    *,
    mod_checks: List[Dict[str, Any]],
    validate_errors: List[str],
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    score = 100.0
    mf_ok = _check_ok(mod_checks, "manifest")
    if mf_ok is False:
        score -= 45
        reasons.append("manifest 不可读或无效")
    elif mf_ok is True:
        reasons.append("manifest 可读")
    cons_ok = _check_ok(mod_checks, "employee_pack_consistency")
    if cons_ok is False:
        score -= 35
        reasons.append("manifest 与 employees 一致性未通过")
    if validate_errors:
        score -= min(50, len(validate_errors) * 15)
        reasons.extend(validate_errors[:3])
    if score >= 80 and not reasons:
        reasons.append("包体声明与校验通过")
    return _clamp_score(score), reasons


def _score_code_robustness(
    *, mod_checks: List[Dict[str, Any]], mod_sandbox_ok: bool
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    score = 80.0 if mod_sandbox_ok else 50.0
    py_ok = _check_ok(mod_checks, "python_compile")
    if py_ok is False:
        score -= 40
        reasons.append("Python 编译检查未通过")
    elif py_ok is True:
        reasons.append("Python 编译通过")
    cons_ok = _check_ok(mod_checks, "employee_pack_consistency")
    if cons_ok is False:
        score -= 25
        reasons.append("包体一致性有缺口")
    if mod_sandbox_ok:
        reasons.append("mod 沙箱轻量校验通过")
    else:
        reasons.append("mod 沙箱存在未通过项")
    return _clamp_score(score), reasons


def _score_executability(
    *,
    pack_dir: Path,
    pipeline_label: str,
    handlers_ok: bool,
    handlers_msg: str,
    standalone_smoke_ok: bool,
    catalog_registered: bool,
    mod_checks: List[Dict[str, Any]],
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    parts: List[float] = []
    if handlers_ok:
        parts.append(35)
        reasons.append("handlers 契约通过")
    else:
        reasons.append(handlers_msg or "handlers 契约未通过")
    if standalone_smoke_ok:
        parts.append(35)
        reasons.append("独立包 validate 通过")
    else:
        reasons.append("独立包自检未通过")
    if catalog_registered:
        parts.append(20)
        reasons.append("员工包已登记至目录")
    else:
        reasons.append("员工包未登记到 catalog")
    score = sum(parts) if parts else 0.0
    if (
        pipeline_label in ("word_full_extract", "word_generate", "txt_full_read", "txt_generate")
        and pack_dir.is_dir()
    ):
        chk_map = {
            "word_full_extract": "word_extract_runtime",
            "word_generate": "word_generate_runtime",
            "txt_full_read": "txt_read_runtime",
            "txt_generate": "txt_generate_runtime",
        }
        chk_id = chk_map.get(pipeline_label, "")
        wx = _check_ok(mod_checks, chk_id) if chk_id else None
        if wx is False:
            score = min(score, 55)
            reasons.append(f"{pipeline_label} runtime 检查未通过")
        elif wx is True:
            score = min(100, score + 10)
            reasons.append(f"{pipeline_label} convert runtime 就绪")
    return _clamp_score(score), reasons


def _score_workflow_connectivity(
    *,
    employee_target: str,
    catalog_registered: bool,
    workflow_sandbox_ok: bool,
    workflow_biz_ok: Optional[bool],
    workflow_skipped: bool,
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    score = 0.0
    if catalog_registered:
        score += 40
        reasons.append("登记成功")
    else:
        reasons.append("登记失败或未写入 catalog")
    if workflow_skipped:
        score += 30
        reasons.append("未创建画布工作流（pack_only），结构/业务子项记中性")
        biz_part = 30.0
    else:
        if workflow_sandbox_ok:
            score += 30
            reasons.append("工作流结构校验通过")
        else:
            reasons.append("工作流结构校验未通过")
        if workflow_biz_ok is True:
            biz_part = 30.0
            reasons.append("真实员工调用验证通过")
        elif workflow_biz_ok is False:
            biz_part = 0.0
            reasons.append("真实员工调用验证失败")
        else:
            biz_part = 15.0
            reasons.append("未执行真实调用验证")
    score += biz_part
    et = (employee_target or "").strip().lower()
    if et != "pack_plus_workflow" and workflow_skipped:
        score = max(score, 65)
    return _clamp_score(score), reasons


def _score_domain_delivery(
    *,
    pipeline_label: str,
    pack_dir: Path,
    mod_checks: List[Dict[str, Any]],
    validate_errors: List[str],
    asset_count: int = 0,
    domain_smoke: Optional[Dict[str, Any]] = None,
    golden_comparison: Optional[Dict[str, Any]] = None,
    runtime_generation: Optional[Dict[str, Any]] = None,
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    if pipeline_label in (
        "word_full_extract",
        "word_generate",
        "txt_full_read",
        "txt_generate",
        "csv_full_read",
        "csv_generate",
        "excel_full_read",
        "excel_generate",
    ):
        score = 85.0
        chk_runtime = {
            "word_full_extract": ("word_extract_runtime", "word_extract_coverage"),
            "word_generate": ("word_generate_runtime", "word_generate_coverage"),
            "txt_full_read": ("txt_read_runtime", "txt_read_coverage"),
            "txt_generate": ("txt_generate_runtime", "txt_generate_coverage"),
            "csv_full_read": ("csv_read_runtime", "csv_read_coverage"),
            "csv_generate": ("csv_generate_runtime", "csv_generate_coverage"),
            "excel_full_read": ("excel_read_runtime", "excel_read_coverage"),
            "excel_generate": ("excel_generate_runtime", "excel_generate_coverage"),
        }
        rt_chk, cov_chk = chk_runtime.get(pipeline_label, ("", ""))
        wx = _check_ok(mod_checks, rt_chk) if rt_chk else None
        cov = _check_ok(mod_checks, cov_chk) if cov_chk else None
        if wx is False:
            score = 35
            reasons.append(f"{pipeline_label} backend 未就绪")
        elif wx is True:
            reasons.append(f"{pipeline_label} runtime 通过")
        if cov is False:
            score -= 15
            reasons.append("输出字段覆盖可能不足")
        if validate_errors:
            score -= min(40, len(validate_errors) * 12)
            reasons.extend(validate_errors[:2])
        _ds = domain_smoke if isinstance(domain_smoke, dict) else {}
        if _ds.get("ok") is True:
            reasons.append("进程内领域冒烟通过")
        elif _ds.get("ok") is False:
            score = min(score, 40)
            reasons.append(f"领域冒烟失败：{_ds.get('error') or 'failed'}"[:80])
        _gc = golden_comparison if isinstance(golden_comparison, dict) else {}
        if _gc.get("golden_pack_id"):
            parity = float(_gc.get("parity_score") or 0)
            if _gc.get("passed"):
                reasons.append(f"黄金 parity {parity}")
            else:
                score = min(score, 45)
                reasons.append(f"黄金未达标 parity={parity}")
        if isinstance(runtime_generation, dict):
            try:
                from modstore_server.vibecoding_convert_loop import (
                    is_llm_codegen_source,
                )

                if is_llm_codegen_source(runtime_generation):
                    reasons.append("convert 为 LLM 生成")
                else:
                    score = min(score, 30)
                    reasons.append(f"非 LLM convert：{runtime_generation.get('source')}")
            except ImportError:
                pass
        rs = pack_dir / "rule_spec.json"
        if rs.is_file():
            try:
                rs_data = json.loads(rs.read_text(encoding="utf-8"))
                if isinstance(rs_data, dict) and rs_data.get("runtime_kind") == pipeline_label:
                    score = min(100, score + 10)
                    reasons.append("rule_spec runtime_kind 正确")
            except (OSError, json.JSONDecodeError):
                score -= 20
                reasons.append("rule_spec 不可读")
        return _clamp_score(score), reasons

    if pipeline_label == "asset":
        score = 75.0
        if asset_count > 0:
            score += 15
            reasons.append(f"已绑定 {asset_count} 个上传资产")
        else:
            reasons.append("内置 direct_python 模板（无上传资产）")
        dp = _check_ok(mod_checks, "word_extract_runtime")
        if dp is not None:
            pass
        return _clamp_score(score), reasons

    score = 60.0
    reasons.append("LLM 通用脚手架管线；建议确认非 Word 提取场景")
    if validate_errors:
        score -= 20
    return _clamp_score(score), reasons


def compute_six_dimension_report(
    *,
    pack_dir: Path,
    pipeline_label: str,
    routing_brief: str = "",
    structured_requirement: Optional[Dict[str, Any]] = None,
    spec_warnings: Optional[List[str]] = None,
    validate_errors: Optional[List[str]] = None,
    mod_sandbox: Optional[Dict[str, Any]] = None,
    workflow_sandbox: Optional[Dict[str, Any]] = None,
    workflow_biz_ok: Optional[bool] = None,
    standalone_smoke_ok: bool = True,
    catalog_registered: bool = True,
    employee_target: str = "pack_only",
    asset_count: int = 0,
    domain_smoke: Optional[Dict[str, Any]] = None,
    golden_comparison: Optional[Dict[str, Any]] = None,
    runtime_generation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """汇总流水线各步结果，返回六维报告（不重新执行沙箱）。"""
    mod_checks = []
    if isinstance(mod_sandbox, dict):
        mod_checks = [c for c in (mod_sandbox.get("checks") or []) if isinstance(c, dict)]
    mod_ok = bool(mod_sandbox.get("ok")) if isinstance(mod_sandbox, dict) else False
    val_errs = [str(x) for x in (validate_errors or []) if x]

    handlers_ok, handlers_msg = True, ""
    if pack_dir.is_dir():
        try:
            from modstore_server.workbench_api import _employee_handlers_contract_ok

            handlers_ok, handlers_msg = _employee_handlers_contract_ok(pack_dir)
        except BOUNDARY_ERRORS as exc:  # noqa: BLE001
            handlers_ok, handlers_msg = False, str(exc)[:120]

    wf = workflow_sandbox if isinstance(workflow_sandbox, dict) else {}
    wf_ok = bool(wf.get("ok"))
    wf_skipped = bool(wf.get("skipped"))

    dims: Dict[str, Dict[str, Any]] = {}
    dims["requirement_clarity"] = _dim_entry(
        "requirement_clarity",
        *_score_requirement_clarity(
            routing_brief=routing_brief,
            structured_requirement=structured_requirement,
            spec_warnings=spec_warnings,
            pipeline_label=pipeline_label,
        ),
    )
    dims["pack_compliance"] = _dim_entry(
        "pack_compliance",
        *_score_pack_compliance(mod_checks=mod_checks, validate_errors=val_errs),
    )
    dims["code_robustness"] = _dim_entry(
        "code_robustness",
        *_score_code_robustness(mod_checks=mod_checks, mod_sandbox_ok=mod_ok),
    )
    dims["executability"] = _dim_entry(
        "executability",
        *_score_executability(
            pack_dir=pack_dir,
            pipeline_label=pipeline_label,
            handlers_ok=handlers_ok,
            handlers_msg=handlers_msg,
            standalone_smoke_ok=standalone_smoke_ok,
            catalog_registered=catalog_registered,
            mod_checks=mod_checks,
        ),
    )
    dims["workflow_connectivity"] = _dim_entry(
        "workflow_connectivity",
        *_score_workflow_connectivity(
            employee_target=employee_target,
            catalog_registered=catalog_registered,
            workflow_sandbox_ok=wf_ok,
            workflow_biz_ok=workflow_biz_ok,
            workflow_skipped=wf_skipped,
        ),
    )
    dims["domain_delivery"] = _dim_entry(
        "domain_delivery",
        *_score_domain_delivery(
            pipeline_label=pipeline_label,
            pack_dir=pack_dir,
            mod_checks=mod_checks,
            validate_errors=val_errs,
            asset_count=asset_count,
            domain_smoke=domain_smoke,
            golden_comparison=golden_comparison,
            runtime_generation=runtime_generation,
        ),
    )

    return _finalize_dimension_report(dims, pipeline_label, scoring_source="deterministic")
