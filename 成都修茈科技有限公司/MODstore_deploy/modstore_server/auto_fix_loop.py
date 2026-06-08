"""异常自动修复闭环 + CVE 自动修复 PR。

步骤7（运行时监控）→ 步骤8（自动净化优化）的核心补齐：

1. 异常自动修复闭环：
   incident_bus.publish("anomaly.detected") → daily-orchestrator 自动修复
   → defer_write_as_change_request → maybe_auto_approve → apply + PR

2. CVE 自动修复 PR：
   safety/bandit 扫描 → publish("cve.detected") → 生成修复内容
   → defer_write_as_change_request → maybe_auto_approve → apply + PR
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def _anomaly_autofix_enabled() -> bool:
    return os.environ.get("XCAGI_ANOMALY_AUTOFIX_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _cve_autofix_enabled() -> bool:
    return os.environ.get("XCAGI_CVE_AUTOFIX_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def trigger_anomaly_autofix(
    incident_payload: Dict[str, Any],
    *,
    source: str = "monitor",
) -> Dict[str, Any]:
    """异常事件触发自动修复。

    流程：
    1. 解析异常信息（类型、文件、错误信息）
    2. 创建建议单 → 派发给 daily-orchestrator
    3. daily-orchestrator 产出修复 → CR → 自动审批 → 落盘 + PR
    """
    if not _anomaly_autofix_enabled():
        return {"ok": True, "skipped": True, "reason": "anomaly autofix disabled"}

    from modstore_server.employee_autonomy_service import create_employee_suggestion

    anomaly_type = str(incident_payload.get("type", "unknown"))
    anomaly_source = str(incident_payload.get("source", source))
    error_msg = str(incident_payload.get("error", ""))
    affected_files = incident_payload.get("files", [])
    severity = str(incident_payload.get("severity", "medium"))

    risk_map = {"critical": "high", "high": "high", "medium": "medium", "low": "low"}
    risk_level = risk_map.get(severity, "medium")

    summary = f"异常自动修复：{anomaly_type} ({anomaly_source})"
    detail_parts = [
        f"异常类型: {anomaly_type}",
        f"来源: {anomaly_source}",
        f"严重程度: {severity}",
    ]
    if error_msg:
        detail_parts.append(f"错误信息: {error_msg[:2000]}")
    if affected_files:
        detail_parts.append(f"影响文件: {', '.join(str(f) for f in affected_files[:20])}")

    detail = "\n".join(detail_parts)

    result = create_employee_suggestion(
        source_employee_id="log-monitor-incident",
        summary=summary,
        detail=detail,
        payload=incident_payload,
        target_employee_ids=["daily-orchestrator"],
        kind="anomaly_autofix",
        risk_level=risk_level,
        auto_dispatch=True,
        emit_event=True,
    )

    from modstore_server.incident_bus import publish

    publish(
        "anomaly.autofix.triggered",
        {"suggestion_id": result.get("suggestion_id"), "anomaly_type": anomaly_type},
        source="auto_fix_loop",
    )

    return {"ok": True, "suggestion_id": result.get("suggestion_id"), "result": result}


def trigger_cve_autofix(
    cve_payload: Dict[str, Any],
    *,
    source: str = "safety_scanner",
) -> Dict[str, Any]:
    """CVE 漏洞触发自动修复 PR。

    流程：
    1. 解析 CVE 信息（CVE ID、包名、当前版本、修复版本）
    2. 生成 requirements.txt / pyproject.toml 修复内容
    3. 创建 CR → 自动审批 → 落盘 + PR（标签 cve-fix + auto-merge）
    """
    if not _cve_autofix_enabled():
        return {"ok": True, "skipped": True, "reason": "cve autofix disabled"}

    cve_id = str(cve_payload.get("cve_id", ""))
    package = str(cve_payload.get("package", ""))
    current_version = str(cve_payload.get("current_version", ""))
    fix_version = str(cve_payload.get("fix_version", ""))
    cvss_score = float(cve_payload.get("cvss_score", 0) or 0)
    advisory = str(cve_payload.get("advisory", ""))

    if not package or not fix_version:
        return {"ok": False, "error": "missing package or fix_version"}

    if cvss_score >= 9.0:
        risk_level = "high"
    elif cvss_score >= 7.0:
        risk_level = "medium"
    else:
        risk_level = "low"

    from modstore_server.employee_change_request_service import defer_write_as_change_request
    from modstore_server.integrations.ops_action_handlers import repo_root

    root = str(repo_root())
    results = []

    for req_file in _find_requirements_files(root):
        try:
            patched = _patch_requirement(req_file, package, fix_version)
            if patched:
                cr_id = defer_write_as_change_request(
                    source_employee_id="security-secrets-guard",
                    workspace_root=root,
                    path=req_file,
                    content=patched,
                    scope_globs=["requirements*.txt", "pyproject.toml"],
                )
                results.append({"file": req_file, "cr_id": cr_id})
        except Exception as exc:
            logger.warning("cve autofix: patch %s failed: %s", req_file, exc)
            results.append({"file": req_file, "error": str(exc)})

    pyproject_path = os.path.join(root, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        try:
            patched = _patch_pyproject_dependency(pyproject_path, package, fix_version)
            if patched:
                cr_id = defer_write_as_change_request(
                    source_employee_id="security-secrets-guard",
                    workspace_root=root,
                    path="pyproject.toml",
                    content=patched,
                    scope_globs=["pyproject.toml"],
                )
                results.append({"file": "pyproject.toml", "cr_id": cr_id})
        except Exception as exc:
            logger.warning("cve autofix: patch pyproject.toml failed: %s", exc)
            results.append({"file": "pyproject.toml", "error": str(exc)})

    from modstore_server.incident_bus import publish

    publish(
        "cve.autofix.triggered",
        {
            "cve_id": cve_id,
            "package": package,
            "fix_version": fix_version,
            "cvss_score": cvss_score,
            "cr_results": results,
        },
        source="auto_fix_loop",
    )

    return {
        "ok": True,
        "cve_id": cve_id,
        "package": package,
        "fix_version": fix_version,
        "results": results,
    }


def _find_requirements_files(root: str) -> List[str]:
    files = []
    for name in os.listdir(root):
        if name.startswith("requirements") and name.endswith(".txt"):
            files.append(name)
    return sorted(files)


def _patch_requirement(rel_path: str, package: str, fix_version: str) -> Optional[str]:
    from modstore_server.integrations.ops_action_handlers import repo_root

    root = str(repo_root())
    full_path = os.path.join(root, rel_path)
    if not os.path.isfile(full_path):
        return None

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        rf"^{re.escape(package)}\s*[><=!~]+\s*[\d.]+",
        re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return None

    new_content = pattern.sub(f"{package}>={fix_version}", content)
    if new_content == content:
        return None

    return new_content


def _patch_pyproject_dependency(rel_path: str, package: str, fix_version: str) -> Optional[str]:
    from modstore_server.integrations.ops_action_handlers import repo_root

    root = str(repo_root())
    full_path = os.path.join(root, rel_path)
    if not os.path.isfile(full_path):
        return None

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        rf'"{re.escape(package)}\s*[><=!~]+\s*[\d.]+[^"]*"',
        re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return None

    new_content = pattern.sub(f'"{package}>={fix_version}"', content)
    if new_content == content:
        return None

    return new_content


def register_auto_fix_event_bindings() -> None:
    """注册异常和 CVE 事件到 incident_bus 的 trigger bindings。"""
    try:
        from modstore_server.models import EmployeeTriggerBinding, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            bindings = [
                EmployeeTriggerBinding(
                    event_type="anomaly.detected",
                    employee_id="daily-orchestrator",
                    priority=10,
                    active=True,
                ),
                EmployeeTriggerBinding(
                    event_type="cve.detected",
                    employee_id="security-secrets-guard",
                    priority=5,
                    active=True,
                ),
            ]
            for b in bindings:
                existing = (
                    session.query(EmployeeTriggerBinding)
                    .filter_by(event_type=b.event_type, employee_id=b.employee_id)
                    .first()
                )
                if not existing:
                    session.add(b)
            session.commit()
        logger.info("auto_fix event bindings registered")
    except Exception:
        logger.exception("register_auto_fix_event_bindings failed")
