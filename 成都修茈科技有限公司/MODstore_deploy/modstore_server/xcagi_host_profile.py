"""FHD 宿主侧「副窗 / 内置轨道」与 employee_pack manifest 扩展字段校验。

与文档 docs/fhd-employee-composition.md 中 ``xcagi_host_profile`` 约定对齐；字段全部可选，向后兼容旧包。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 与 FHD frontend defaultWorkflowBuiltinEnabled + 文档固定扩展 id 对齐（勿随意扩展字符串）
BUILTIN_TRACK_IDS = frozenset(
    {
        "label_print",
        "shipment_mgmt",
        "receipt_confirm",
        "wechat_msg",
        "wechat_phone",
        "real_phone",
    }
)

VALID_PANEL_KINDS = frozenset({"builtin_track", "mod_http", "placeholder"})


def normalize_xcagi_host_profile(raw: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    校验并返回可写入 manifest 的 ``xcagi_host_profile``；错误时 errs 非空且返回 (None, errs)。
    """
    errs: List[str] = []
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["xcagi_host_profile 须为对象"]
    out: Dict[str, Any] = {}
    panel_kind = str(raw.get("panel_kind") or "mod_http").strip()
    if panel_kind not in VALID_PANEL_KINDS:
        errs.append(f"panel_kind 无效，允许: {', '.join(sorted(VALID_PANEL_KINDS))}")
    else:
        out["panel_kind"] = panel_kind

    bid = str(raw.get("builtin_track_id") or "").strip()
    if bid:
        if panel_kind != "builtin_track":
            errs.append("填写 builtin_track_id 时 panel_kind 应为 builtin_track")
        elif bid not in BUILTIN_TRACK_IDS:
            errs.append(f"builtin_track_id 不在宿主白名单: {bid}")
        else:
            out["builtin_track_id"] = bid

    row = raw.get("workflow_employee_row")
    if row is not None:
        if not isinstance(row, dict):
            errs.append("workflow_employee_row 须为对象")
        else:
            # 浅拷贝，避免后续修改污染 LLM 原始结构
            out["workflow_employee_row"] = {str(k): v for k, v in row.items() if k}

    if errs:
        return None, errs
    return (out if out else None), []


def merge_workflow_employee_for_manifest(
    *,
    employee_id: str,
    label: str,
    panel_summary: str,
    host_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """合成单条 ``manifest.workflow_employees[0]``，合并 host_profile.workflow_employee_row。"""
    row_extra = (
        (host_profile or {}).get("workflow_employee_row")
        if isinstance((host_profile or {}).get("workflow_employee_row"), dict)
        else {}
    )
    base: Dict[str, Any] = {
        "id": employee_id,
        "label": label,
        "panel_title": label,
        "panel_summary": (panel_summary or "")[:800],
        "api_base_path": f"employees/{employee_id}",
    }
    for k, v in row_extra.items():
        if k in base and base[k] == v:
            continue
        base[str(k)] = v
    return base
