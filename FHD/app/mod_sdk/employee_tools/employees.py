"""Installed employee manifests and roster projections, independent of the public tool registry."""

from __future__ import annotations

import json
import os

from .employee_tool_ports import EmployeeFiles, Payload
from .results import _err, _ok


async def list_employee_packs(ports: EmployeeFiles, params: Payload, ctx: Payload) -> Payload:
    """扫描本地 _employees/ 目录，列出已安装员工包。"""
    packs: list[Payload] = []
    if not ports.packs.is_dir():
        return _ok("_employees 目录不存在", packs=packs)
    for name in sorted(os.listdir(ports.packs)):
        mf = ports.packs / name / "manifest.json"
        if not mf.is_file():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        packs.append(
            {
                "id": data.get("id") or name,
                "label": data.get("name") or data.get("employee_label") or name,
                "artifact": data.get("artifact"),
                "area": (data.get("employee_config_v2") or {}).get("area"),
            }
        )
    return _ok(f"{len(packs)} 个员工包", packs=packs)


async def validate_employee_pack(ports: EmployeeFiles, params: Payload, ctx: Payload) -> Payload:
    """验证员工包 manifest 完整性。"""
    pack_id = str(params.get("pack_id") or "").strip()
    if not pack_id:
        return _err("缺少 pack_id 参数")
    mf = ports.packs / pack_id / "manifest.json"
    if not mf.is_file():
        return _err(f"manifest 不存在: {mf}")
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(f"manifest 解析失败: {exc}")
    issues: list[str] = []
    if data.get("artifact") != "employee_pack":
        issues.append(f"artifact 应为 employee_pack，实际 {data.get('artifact')!r}")
    if not data.get("id"):
        issues.append("缺少 id")
    v2 = data.get("employee_config_v2") or {}
    if not isinstance(v2, dict):
        issues.append("缺少 employee_config_v2")
    else:
        cog = v2.get("cognition") or {}
        agent = cog.get("agent") or {}
        if not agent.get("system_prompt"):
            issues.append("缺少 system_prompt")
    return _ok(
        f"验证 {pack_id}: {('通过' if not issues else '有问题')}",
        valid=not issues,
        issues=issues,
        manifest=data,
    )


async def list_employees(ports: EmployeeFiles, params: Payload, ctx: Payload) -> Payload:
    """列出全部编制员工（duty_roster.json）。"""
    if not ports.roster.is_file():
        return _err("duty_roster.json 不存在")
    try:
        roster = json.loads(ports.roster.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(f"解析失败: {exc}")

    def _collect(blocks: Payload) -> list[str]:
        ids: list[str] = []
        for block in blocks.values():
            if not isinstance(block, dict):
                continue
            raw = block.get("ids")
            if isinstance(raw, list):
                ids.extend(str(x).strip() for x in raw if str(x).strip())
            sub = block.get("subzones")
            if isinstance(sub, dict):
                ids.extend(_collect(sub))
        return ids

    planned: list[str] = []
    for key in ("areas", "departments"):
        planned.extend(_collect(roster.get(key) or {}))
    planned = sorted(set(planned))
    return _ok(f"{len(planned)} 个编制员工", employees=planned)
