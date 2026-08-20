# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_bench")


async def _audit_single_pack(employee_id: str) -> _facade().Dict[str, _facade().Any]:
    """对单个员工包构建 zip 并调沙盒审核，返回原始 audit 结果。"""
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )
    from modstore_server.package_sandbox_audit import run_package_audit_async

    materialize_employee_pack_if_missing(employee_id)
    pack_dir = modstore_library_path() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return {
            "ok": False,
            "error": f"员工包目录不存在: {employee_id}",
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }
    try:
        manifest = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
        zip_bytes = build_employee_pack_zip(employee_id, manifest)
    except RECOVERABLE_ERRORS as exc:
        return {
            "ok": False,
            "error": f"构建员工包失败: {exc}",
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }
    try:
        return await run_package_audit_async(zip_bytes, {"artifact": "employee_pack"})
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("audit failed employee=%s: %s", employee_id, exc)
        return {
            "ok": False,
            "error": str(exc),
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }


async def _run_five_dim_audit(
    employee_id: str,
    per_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = None,
    auto_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """五维合成审核：每个维度可独立指向不同员工包。

    合并优先级（后者覆盖前者）：
    1. 环境变量 ``MODSTORE_AUDIT_DIM_<DIM>_EMPLOYEE``
    2. ``auto_dimension_ids``（LLM 从评审池自动挑选，仅填补空缺）
    3. ``per_dimension_ids``（API / 人工显式指定）

    未配置的维度回退到主员工 employee_id 的静态审核得分。
    """
    env_defaults = _facade()._load_audit_dimension_env_defaults()
    effective_map: _facade().Dict[str, str] = {}
    effective_map.update(env_defaults)
    if auto_dimension_ids:
        for dim in _facade().AUDIT_DIMENSIONS:
            if str(effective_map.get(dim) or "").strip():
                continue
            v = str(auto_dimension_ids.get(dim) or "").strip()
            if v:
                effective_map[dim] = v
    if per_dimension_ids:
        effective_map.update(
            {k: v for (k, v) in per_dimension_ids.items() if k in _facade().AUDIT_DIMENSIONS and v}
        )
    pack_ids_needed: set[str] = {employee_id}
    for dim in _facade().AUDIT_DIMENSIONS:
        eid = effective_map.get(dim, employee_id)
        pack_ids_needed.add(eid)
    import asyncio

    raw_audits: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    coros = {eid: _facade()._audit_single_pack(eid) for eid in pack_ids_needed}
    results = await asyncio.gather(*coros.values(), return_exceptions=True)
    for eid, res in zip(coros.keys(), results):
        if isinstance(res, Exception):
            raw_audits[eid] = {
                "ok": False,
                "error": str(res),
                "dimensions": {},
                "summary": {"average": 0, "pass": False},
            }
        else:
            raw_audits[eid] = res
    primary_audit = raw_audits[employee_id]
    merged_dims: _facade().Dict[str, _facade().Any] = {}
    for dim in _facade().AUDIT_DIMENSIONS:
        target_eid = effective_map.get(dim, employee_id)
        target_audit = raw_audits.get(target_eid, primary_audit)
        dim_data = (target_audit.get("dimensions") or {}).get(dim)
        if dim_data is not None:
            entry = dict(dim_data)
            if target_eid != employee_id:
                entry["_source_employee"] = target_eid
        else:
            fallback = (primary_audit.get("dimensions") or {}).get(dim)
            if fallback is not None:
                entry = dict(fallback)
                if target_eid != employee_id:
                    entry["reasons"] = list(entry.get("reasons") or []) + [
                        f"[分包 {target_eid} 审核失败，已回退到主员工]"
                    ]
                    entry["_source_employee"] = f"{target_eid}(fallback→{employee_id})"
            else:
                entry = {"score": 0, "reasons": ["审核数据缺失"]}
        merged_dims[dim] = entry
    scores = [int(merged_dims[d].get("score") or 0) for d in _facade().AUDIT_DIMENSIONS]
    average = round(sum(scores) / len(scores), 1) if scores else 0.0
    manifest_ok = int(merged_dims.get("manifest_compliance", {}).get("score") or 0) >= 40
    orig_manifest_err = bool(
        primary_audit.get("summary", {}).get("pass") is False
        and (not primary_audit.get("dimensions"))
    )
    passed = average >= 60 and manifest_ok and (not orig_manifest_err)
    return {
        "ok": True,
        "dimensions": merged_dims,
        "functional_tests": primary_audit.get("functional_tests") or [],
        "summary": {
            "average": average,
            "pass": passed,
            "artifact": (primary_audit.get("summary") or {}).get("artifact", "employee_pack"),
            "composite": bool(effective_map),
        },
    }
