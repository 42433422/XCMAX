"""pack-registrar 登记前/审核门禁：上游自动化、元数据一致性、五维失败分级。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 动态阶段仅允许自动修补的审核维度（其余须 audit_passed=false + 人工）
_TRIVIAL_AUDIT_DIMENSIONS = frozenset(
    {
        "metadata_quality",
        "declaration_completeness",
    }
)
_CRITICAL_AUDIT_DIMENSIONS = frozenset(
    {
        "manifest_compliance",
        "security_and_size",
    }
)


def workflow_automation_block_reason(
    workflow_results: Optional[List[Dict[str, Any]]],
    *,
    workflow_index: Optional[int] = None,
    wf_attach: Optional[Dict[str, Any]] = None,
    wf_entry: Optional[Dict[str, Any]] = None,
    require_workflow_automation: bool = True,
) -> Optional[str]:
    """若 workflow-automator 未完成则返回拒收原因，否则 None。

    验收：显式 ``automation_complete`` 为真，或（兼容旧链路）``ok`` + ``workflow_id`` /
    manifest 条目 ``workflow_id`` / ``workflow_attachment``。
    """
    if not require_workflow_automation:
        return None

    entry = wf_entry if isinstance(wf_entry, dict) else {}
    if str(entry.get("catalog_pkg_id") or "").strip():
        return None

    has_workflow_expectation = bool(
        wf_attach
        or (isinstance(workflow_results, list) and workflow_results)
        or str(entry.get("workflow_id") or "").strip()
        or isinstance(entry.get("workflow_attachment"), dict)
        or isinstance(entry.get("workflow"), dict)
    )
    if not has_workflow_expectation:
        return None

    if isinstance(wf_attach, dict) and wf_attach:
        if wf_attach.get("automation_complete") is True:
            return None
        if wf_attach.get("ok") and wf_attach.get("workflow_id"):
            return None
        return (
            "上游 workflow-automator 未完成：缺少 automation_complete 或有效 workflow_id，"
            "已拒收登记并退回自动化步骤"
        )

    if workflow_index is not None and isinstance(workflow_results, list):
        for item in workflow_results:
            if not isinstance(item, dict):
                continue
            if int(
                item.get("workflow_index") if item.get("workflow_index") is not None else -1
            ) != int(workflow_index):
                continue
            if item.get("automation_complete") is True:
                return None
            if item.get("ok") and item.get("workflow_id"):
                return None
            if item.get("ok") is False:
                return (
                    f"上游工作流生成失败（workflow_index={workflow_index}），"
                    "须先由 workflow-automator 修复后再登记"
                )
            return (
                f"workflow_index={workflow_index} 缺少 automation_complete / workflow_id，"
                "拒收过早移交的登记请求"
            )

    if str(entry.get("workflow_id") or "").strip():
        return None
    att = entry.get("workflow_attachment")
    if isinstance(att, dict) and att.get("workflow_id"):
        return None

    if isinstance(workflow_results, list) and workflow_results:
        bad = [
            i
            for i, item in enumerate(workflow_results)
            if isinstance(item, dict)
            and not item.get("automation_complete")
            and not (item.get("ok") and item.get("workflow_id"))
        ]
        if bad:
            return (
                f"共 {len(bad)} 条工作流未标记 automation_complete，"
                "须 workflow-automator 完成后再调用 register_mod_employee_packs_async"
            )

    return "缺少 workflow-automator 完成标记（automation_complete / workflow_id），" "拒收登记"


def registration_metadata_mismatches(
    *,
    wf_entry: Dict[str, Any],
    mod_manifest: Dict[str, Any],
    audit_manifest: Dict[str, Any],
    catalog_rec: Dict[str, Any],
) -> List[str]:
    """比对登记草案与包内 manifest / Mod 条目，不一致则阻断 Catalog 写入。"""
    mismatches: List[str] = []
    am = audit_manifest if isinstance(audit_manifest, dict) else {}
    rec = catalog_rec if isinstance(catalog_rec, dict) else {}
    wf = wf_entry if isinstance(wf_entry, dict) else {}
    mod = mod_manifest if isinstance(mod_manifest, dict) else {}

    pack_id = str(am.get("id") or rec.get("id") or "").strip()
    rec_id = str(rec.get("id") or "").strip()
    if pack_id and rec_id and pack_id != rec_id:
        mismatches.append(f"id: 登记草案 {rec_id!r} ≠ 包内 {pack_id!r}")

    am_ver = str(am.get("version") or "").strip()
    rec_ver = str(rec.get("version") or "").strip()
    mod_ver = str(mod.get("version") or "").strip()
    if am_ver and rec_ver and am_ver != rec_ver:
        mismatches.append(f"version: 登记 {rec_ver!r} ≠ 包内 {am_ver!r}")
    elif mod_ver and am_ver and mod_ver != am_ver and not wf.get("catalog_pkg_id"):
        mismatches.append(f"version: Mod {mod_ver!r} ≠ 包内 {am_ver!r}")

    wf_label = str(wf.get("label") or wf.get("panel_title") or "").strip()
    am_name = str(am.get("name") or "").strip()
    rec_name = str(rec.get("name") or "").strip()
    if wf_label and am_name and wf_label != am_name and wf_label not in am_name:
        mismatches.append(f"name: 工作流条目 {wf_label!r} ≠ 包内 name {am_name!r}")
    if rec_name and am_name and rec_name != am_name:
        mismatches.append(f"name: 登记 {rec_name!r} ≠ 包内 {am_name!r}")

    mod_owner = str(mod.get("author") or mod.get("owner") or "").strip()
    am_owner = str(am.get("author") or am.get("owner") or "").strip()
    if mod_owner and am_owner and mod_owner != am_owner:
        mismatches.append(f"owner/author: Mod {mod_owner!r} ≠ 包内 {am_owner!r}")

    wf_emp = wf.get("id")
    am_emp = (am.get("employee") or {}).get("id") if isinstance(am.get("employee"), dict) else None
    if wf_emp and am_emp and str(wf_emp).strip() != str(am_emp).strip():
        mismatches.append(f"employee.id: 条目 {wf_emp!r} ≠ 包内 {am_emp!r}")

    return mismatches


def classify_audit_failure(audit: Dict[str, Any]) -> Dict[str, Any]:
    """五维审核失败分级：仅 trivial 允许进入动态自动修补预算内处理。"""
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    if summary.get("pass") is not False and audit.get("ok"):
        return {
            "audit_passed": True,
            "repair_tier": "none",
            "dynamic_repair_allowed": False,
            "escalate_to_human": False,
            "failed_dimensions": [],
        }

    dims = audit.get("dimensions") if isinstance(audit.get("dimensions"), dict) else {}
    failed: List[str] = []
    for key, val in dims.items():
        if not isinstance(val, dict):
            continue
        score = val.get("score")
        if isinstance(score, (int, float)) and score < 60:
            failed.append(str(key))

    critical_hit = bool(_CRITICAL_AUDIT_DIMENSIONS.intersection(failed))
    non_trivial_hit = any(d not in _TRIVIAL_AUDIT_DIMENSIONS for d in failed)
    avg = summary.get("average")
    avg_low = isinstance(avg, (int, float)) and avg < 50

    if critical_hit or len(failed) >= 2 or (avg_low and non_trivial_hit):
        return {
            "audit_passed": False,
            "repair_tier": "non_trivial",
            "dynamic_repair_allowed": False,
            "escalate_to_human": True,
            "failed_dimensions": failed,
        }

    if failed and all(d in _TRIVIAL_AUDIT_DIMENSIONS for d in failed):
        return {
            "audit_passed": False,
            "repair_tier": "trivial",
            "dynamic_repair_allowed": True,
            "escalate_to_human": False,
            "failed_dimensions": failed,
        }

    return {
        "audit_passed": False,
        "repair_tier": "non_trivial",
        "dynamic_repair_allowed": False,
        "escalate_to_human": True,
        "failed_dimensions": failed,
    }


def audit_failure_error_payload(
    *,
    pack_id: str,
    workflow_index: int,
    audit: Dict[str, Any],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    """构造 register_mod_employee_packs_async errors 项（含 escalate / 动态修补策略）。"""
    tier = classification.get("repair_tier") or "non_trivial"
    msg = "五维审核未通过"
    if tier == "non_trivial":
        msg = "五维审核未通过（非琐碎项，禁止动态超预算修补，须人工处理）"
    elif tier == "trivial":
        msg = "五维审核未通过（仅琐碎项，可在 max_patch_budget_tokens 内尝试动态修补）"

    return {
        "workflow_index": workflow_index,
        "pack_id": pack_id,
        "stage": "audit",
        "error": msg,
        "audit_passed": False,
        "catalog_registered": False,
        "xcemp_path": None,
        "audit_summary": audit.get("summary") if isinstance(audit.get("summary"), dict) else {},
        "audit_classification": classification,
        "dynamic_repair_allowed": bool(classification.get("dynamic_repair_allowed")),
        "escalate_to_human": bool(classification.get("escalate_to_human")),
    }
