"""将工作流 ID 写入 Mod manifest.workflow_employees（不生成占位路由文件）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from modman.manifest_util import read_manifest, save_manifest_validated

_EMP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class WorkflowModLinkBody(BaseModel):
    workflow_id: int = Field(..., ge=1)
    workflow_index: Optional[int] = Field(
        None,
        ge=0,
        description="若指定则向现有 workflow_employees[i] 写入 workflow_id；不指定则按原逻辑在末尾追加新项",
    )
    id: Optional[str] = Field(
        None,
        max_length=64,
        description="workflow_employees 项 id；缺省为 wf_{workflow_id}",
    )
    label: Optional[str] = Field(None, max_length=256)
    panel_title: Optional[str] = Field(None, max_length=256)
    panel_summary: Optional[str] = Field(None, max_length=8000)


def _default_entry_id(workflow_id: int, existing_ids: set[str]) -> str:
    base = f"wf{workflow_id}"
    if _EMP_ID_RE.match(base) and base not in existing_ids:
        return base
    for i in range(2, 50):
        cand = f"wf{workflow_id}_{i}"
        if _EMP_ID_RE.match(cand) and cand not in existing_ids:
            return cand
    return f"wf{workflow_id}_link"


def append_workflow_link_to_manifest(
    mod_dir: Path,
    body: WorkflowModLinkBody,
    *,
    workflow_name: str,
    workflow_description: str,
) -> Dict[str, Any]:
    """
    在 manifest.workflow_employees 末尾追加一条，含 workflow_id（整数）。
    若已有任一项 workflow_id 与 body.workflow_id 相同，抛出 ValueError。
    """
    data, err = read_manifest(mod_dir)
    if err or not data:
        raise ValueError(err or "manifest 无效")
    manifest = dict(data)
    wf = manifest.get("workflow_employees")
    if wf is None:
        wf = []
    if not isinstance(wf, list):
        raise ValueError("manifest.workflow_employees 须为数组")

    existing_ids: set[str] = set()
    for it in wf:
        if isinstance(it, dict):
            eid = str(it.get("id") or "").strip()
            if eid:
                existing_ids.add(eid)
            wid = it.get("workflow_id")
            if wid is not None and int(wid) == int(body.workflow_id):
                raise ValueError(f"该 Mod 已关联 workflow_id={body.workflow_id}，请勿重复添加")

    emp_id = (body.id or "").strip()
    if emp_id:
        if not _EMP_ID_RE.match(emp_id):
            raise ValueError(
                "员工 id 须为小写字母开头，仅含小写字母、数字、下划线、连字符（1–64 字符）"
            )
        if emp_id in existing_ids:
            raise ValueError(f"workflow_employees 已存在 id={emp_id!r}")
    else:
        emp_id = _default_entry_id(body.workflow_id, existing_ids)

    wn = (workflow_name or "").strip() or f"工作流 {body.workflow_id}"
    label = (body.label or "").strip() or wn
    panel_title = (body.panel_title or "").strip() or label
    summary_raw = (body.panel_summary or "").strip()
    panel_summary = summary_raw or (workflow_description or "").strip()[:8000]

    entry: Dict[str, Any] = {
        "id": emp_id,
        "label": label,
        "panel_title": panel_title,
        "panel_summary": panel_summary,
        "workflow_id": int(body.workflow_id),
    }
    wf = list(wf)
    wf.append(entry)
    manifest["workflow_employees"] = wf
    warnings = save_manifest_validated(mod_dir, manifest)
    return {
        "ok": True,
        "employee_entry": entry,
        "manifest_warnings": warnings,
    }


def merge_workflow_id_into_existing_entry(
    mod_dir: Path,
    body: WorkflowModLinkBody,
    *,
    workflow_name: str,
    workflow_description: str,
) -> Dict[str, Any]:
    """
    向已有 workflow_employees[workflow_index] 写入 workflow_id（不追加新行）。
    其它条目中已存在相同 workflow_id 时拒绝（与 append 行为一致）。
    """
    if body.workflow_index is None:
        raise ValueError("merge 模式须提供 workflow_index")
    idx = int(body.workflow_index)

    data, err = read_manifest(mod_dir)
    if err or not data:
        raise ValueError(err or "manifest 无效")
    manifest = dict(data)
    wf = manifest.get("workflow_employees")
    if not isinstance(wf, list) or idx < 0 or idx >= len(wf):
        raise ValueError("workflow_index 越界或 workflow_employees 非数组")
    entry = wf[idx]
    if not isinstance(entry, dict):
        raise ValueError(f"workflow_employees[{idx}] 须为对象")

    wid = int(body.workflow_id)
    for i, it in enumerate(wf):
        if not isinstance(it, dict):
            continue
        ow = it.get("workflow_id")
        if ow is None:
            continue
        if int(ow) == wid and i != idx:
            raise ValueError(f"其他条目（索引 {i}）已关联 workflow_id={wid}")

    new_entry = dict(entry)
    new_entry["workflow_id"] = wid
    # 可选：仅填空，不覆盖已有文案
    wn = (workflow_name or "").strip() or f"工作流 {wid}"
    if not str(new_entry.get("label") or "").strip() and (body.label or "").strip():
        new_entry["label"] = (body.label or "").strip()
    elif not str(new_entry.get("label") or "").strip():
        new_entry["label"] = wn
    if not str(new_entry.get("panel_title") or "").strip() and (body.panel_title or "").strip():
        new_entry["panel_title"] = (body.panel_title or "").strip()
    elif not str(new_entry.get("panel_title") or "").strip():
        new_entry["panel_title"] = str(new_entry.get("label") or wn)
    summary_raw = (body.panel_summary or "").strip()
    if summary_raw:
        new_entry["panel_summary"] = summary_raw[:8000]
    elif (
        not str(new_entry.get("panel_summary") or "").strip()
        and (workflow_description or "").strip()
    ):
        new_entry["panel_summary"] = (workflow_description or "").strip()[:8000]

    wf2 = list(wf)
    wf2[idx] = new_entry
    manifest["workflow_employees"] = wf2
    warnings = save_manifest_validated(mod_dir, manifest)
    return {
        "ok": True,
        "employee_entry": new_entry,
        "workflow_index": idx,
        "manifest_warnings": warnings,
    }
