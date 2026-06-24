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
from typing import Any, Dict, List, Optional

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
    fix_version = str(cve_payload.get("fix_version", ""))
    cvss_score = float(cve_payload.get("cvss_score", 0) or 0)

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
            "risk_level": risk_level,
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
    if os.path.islink(full_path):
        return None
    if not os.path.isfile(full_path):
        return None

    with open(full_path, encoding="utf-8") as f:
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
    if os.path.islink(full_path):
        return None
    if not os.path.isfile(full_path):
        return None

    with open(full_path, encoding="utf-8") as f:
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
    """注册异常、CVE、Dependabot、gitleaks、CodeQL 事件到 incident_bus 的 trigger bindings。"""
    try:
        from modstore_server.models import EmployeeTriggerBinding, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            bindings = [
                EmployeeTriggerBinding(
                    event_type="anomaly.detected",
                    employee_id="daily-orchestrator",
                    priority=10,
                    is_active=True,
                ),
                EmployeeTriggerBinding(
                    event_type="cve.detected",
                    employee_id="security-secrets-guard",
                    priority=5,
                    is_active=True,
                ),
                # P1 扩展：GitHub 原生工具信号桥接
                EmployeeTriggerBinding(
                    event_type="dependabot.pr.opened",
                    employee_id="github-pr-gatekeeper",
                    priority=8,
                    is_active=True,
                ),
                EmployeeTriggerBinding(
                    event_type="gitleaks.scan.completed",
                    employee_id="security-secrets-guard",
                    priority=3,
                    is_active=True,
                ),
                EmployeeTriggerBinding(
                    event_type="codeql.alert.created",
                    employee_id="vibe-coding-maintainer",
                    priority=5,
                    is_active=True,
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


# ---------------------------------------------------------------------------
# P1 扩展：GitHub 原生工具信号桥接（Dependabot / gitleaks / CodeQL）
# ---------------------------------------------------------------------------


def _dependabot_autofix_enabled() -> bool:
    return os.environ.get("XCAGI_DEPENDABOT_AUTOFIX_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _gitleaks_response_enabled() -> bool:
    return os.environ.get("XCAGI_GITLEAKS_RESPONSE_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _codeql_response_enabled() -> bool:
    return os.environ.get("XCAGI_CODEQL_RESPONSE_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def trigger_dependabot_autofix(
    pr_event: Dict[str, Any],
    *,
    source: str = "github_webhook",
) -> Dict[str, Any]:
    """Dependabot PR 自动审查与合并。

    信号源：GitHub webhook (pull_request.opened, sender=dependabot[bot])
    策略：
    - patch/minor + 测试通过 → 自动 approve + merge
    - major → 派发给 vibe-coding-maintainer 做兼容性验证
    - security PR → 优先级最高，跳过 major 限制

    流程：
    1. 解析 PR 信息（number、url、依赖名、版本变更类型）
    2. 创建建议单 → 派发给 github-pr-gatekeeper
    3. github-pr-gatekeeper 调用 GitHub API 做 review/approve/merge
    """
    if not _dependabot_autofix_enabled():
        return {"ok": True, "skipped": True, "reason": "dependabot autofix disabled"}

    sender_login = str(pr_event.get("sender", {}).get("login", ""))
    if "dependabot" not in sender_login:
        return {"ok": True, "skipped": True, "reason": f"not dependabot PR: {sender_login}"}

    pr_number = int(pr_event.get("number", 0) or 0)
    pr_url = str(pr_event.get("html_url", "") or pr_event.get("pull_request", {}).get("html_url", ""))
    pr_title = str(pr_event.get("title", "") or pr_event.get("pull_request", {}).get("title", ""))

    # 从 PR 标题解析版本变更类型
    # Dependabot 标题格式："Bump foo from 1.0.0 to 1.1.0" 或 "Bump foo from 1.0.0 to 2.0.0"
    update_type = _classify_dependabot_update(pr_title)
    is_security = "security" in pr_title.lower() or "security" in pr_url.lower()

    risk_level = "low"
    if is_security:
        risk_level = "high"  # 安全 PR 优先级最高，但风险也高（需快速验证）
    elif update_type == "major":
        risk_level = "medium"  # major 版本可能有 breaking change

    from modstore_server.employee_autonomy_service import create_employee_suggestion

    summary = f"Dependabot PR #{pr_number}: {pr_title[:120]}"
    detail_parts = [
        f"PR 编号: #{pr_number}",
        f"PR URL: {pr_url}",
        f"PR 标题: {pr_title}",
        f"版本变更类型: {update_type}",
        f"是否安全更新: {is_security}",
        f"来源: {source}",
    ]
    detail = "\n".join(detail_parts)

    result = create_employee_suggestion(
        source_employee_id="security-secrets-guard",
        summary=summary,
        detail=detail,
        payload={
            "pr_number": pr_number,
            "pr_url": pr_url,
            "pr_title": pr_title,
            "update_type": update_type,
            "is_security": is_security,
            "source": source,
        },
        target_employee_ids=["github-pr-gatekeeper"],
        kind="dependabot_autofix",
        risk_level=risk_level,
        auto_dispatch=True,
        emit_event=True,
    )

    from modstore_server.incident_bus import publish

    publish(
        "dependabot.autofix.triggered",
        {
            "pr_number": pr_number,
            "pr_url": pr_url,
            "update_type": update_type,
            "is_security": is_security,
            "suggestion_id": result.get("suggestion_id"),
        },
        source="auto_fix_loop",
    )

    return {
        "ok": True,
        "pr_number": pr_number,
        "update_type": update_type,
        "is_security": is_security,
        "suggestion_id": result.get("suggestion_id"),
        "result": result,
    }


def _classify_dependabot_update(pr_title: str) -> str:
    """从 Dependabot PR 标题解析版本变更类型。

    Dependabot 标题格式：
    - "Bump foo from 1.0.0 to 1.0.1" → patch
    - "Bump foo from 1.0.0 to 1.1.0" → minor
    - "Bump foo from 1.0.0 to 2.0.0" → major
    """
    if not pr_title:
        return "unknown"

    # 匹配 "from X.Y.Z to A.B.C" 模式
    match = re.search(r"from\s+(\d+)\.(\d+)\.(\d+)\s+to\s+(\d+)\.(\d+)\.(\d+)", pr_title)
    if not match:
        return "unknown"

    from_major, from_minor, _ = int(match.group(1)), int(match.group(2)), int(match.group(3))
    to_major, to_minor, _ = int(match.group(4)), int(match.group(5)), int(match.group(6))

    if to_major > from_major:
        return "major"
    if to_minor > from_minor:
        return "minor"
    return "patch"


def trigger_gitleaks_response(
    scan_result: Dict[str, Any],
    *,
    source: str = "gitleaks_action",
) -> Dict[str, Any]:
    """gitleaks 扫描结果响应。

    信号源：gitleaks-action workflow 完成 + webhook 通知
    策略：
    - 无泄漏 → 记录日志，不派发
    - 有泄漏 → 立即派发 security-secrets-guard 评估
    - 高危泄漏（私钥/数据库密码/生产 token）→ 创建 incident + 通知 + 准备密钥轮换

    流程：
    1. 解析扫描结果（leaks 列表、严重程度）
    2. 按 secret type 分级
    3. 创建建议单 → 派发给 security-secrets-guard
    4. security-secrets-guard 评估 → 决定是否轮换密钥
    """
    if not _gitleaks_response_enabled():
        return {"ok": True, "skipped": True, "reason": "gitleaks response disabled"}

    leaks = scan_result.get("leaks", [])
    if not leaks:
        logger.info("gitleaks scan clean: no leaks found")
        return {"ok": True, "clean": True, "leaks_count": 0}

    # 按泄漏类型分级
    high_risk_types = {
        "private-key",
        "aws-access-token",
        "github-pat",
        "github-oauth",
        "database-url",
        "xcmag-cursor-admin-token",
        "xcmag-modstore-api-key",
        "xcmag-lan-gateway-secret",
    }

    high_risk_leaks = []
    other_leaks = []
    for leak in leaks:
        rule_id = str(leak.get("RuleID", "") or leak.get("rule_id", ""))
        if rule_id in high_risk_types or "private" in rule_id.lower() or "key" in rule_id.lower():
            high_risk_leaks.append(leak)
        else:
            other_leaks.append(leak)

    risk_level = "high" if high_risk_leaks else "medium"

    from modstore_server.employee_autonomy_service import create_employee_suggestion

    summary = f"gitleaks 发现 {len(leaks)} 处泄漏（高危 {len(high_risk_leaks)} 处）"
    detail_parts = [
        f"扫描来源: {source}",
        f"总泄漏数: {len(leaks)}",
        f"高危泄漏数: {len(high_risk_leaks)}",
        f"严重程度: {risk_level}",
        "",
        "## 高危泄漏清单（脱敏）",
    ]
    for i, leak in enumerate(high_risk_leaks[:20], 1):
        rule_id = str(leak.get("RuleID", "") or leak.get("rule_id", "unknown"))
        file_path = str(leak.get("File", "") or leak.get("file", "unknown"))
        start_line = leak.get("StartLine", leak.get("start_line", "?"))
        # 脱敏：不输出 secret 明文，只输出位置和规则
        detail_parts.append(f"{i}. [{rule_id}] {file_path}:{start_line}")
    detail_parts.append("")
    detail_parts.append("## 其他泄漏清单（脱敏）")
    for i, leak in enumerate(other_leaks[:20], 1):
        rule_id = str(leak.get("RuleID", "") or leak.get("rule_id", "unknown"))
        file_path = str(leak.get("File", "") or leak.get("file", "unknown"))
        start_line = leak.get("StartLine", leak.get("start_line", "?"))
        detail_parts.append(f"{i}. [{rule_id}] {file_path}:{start_line}")

    detail = "\n".join(detail_parts)

    result = create_employee_suggestion(
        source_employee_id="log-monitor-incident",
        summary=summary,
        detail=detail,
        payload={
            "leaks_count": len(leaks),
            "high_risk_count": len(high_risk_leaks),
            "risk_level": risk_level,
            "source": source,
            # 不传 leaks 原文，避免 secret 明文进入建议单
            "leaks_summary": [
                {
                    "rule_id": str(leak_item.get("RuleID", "") or leak_item.get("rule_id", "")),
                    "file": str(leak_item.get("File", "") or leak_item.get("file", "")),
                    "line": leak_item.get("StartLine", leak_item.get("start_line", "?")),
                }
                for leak_item in leaks[:50]
            ],
        },
        target_employee_ids=["security-secrets-guard"],
        kind="gitleaks_response",
        risk_level=risk_level,
        auto_dispatch=True,
        emit_event=True,
    )

    from modstore_server.incident_bus import publish

    publish(
        "gitleaks.response.triggered",
        {
            "leaks_count": len(leaks),
            "high_risk_count": len(high_risk_leaks),
            "risk_level": risk_level,
            "suggestion_id": result.get("suggestion_id"),
        },
        source="auto_fix_loop",
    )

    return {
        "ok": True,
        "leaks_count": len(leaks),
        "high_risk_count": len(high_risk_leaks),
        "risk_level": risk_level,
        "suggestion_id": result.get("suggestion_id"),
        "result": result,
    }


def trigger_codeql_response(
    alert: Dict[str, Any],
    *,
    source: str = "codeql_webhook",
) -> Dict[str, Any]:
    """CodeQL 告警响应。

    信号源：GitHub code-scanning alert webhook
    策略：
    - HIGH/CRITICAL → 派发 vibe-coding-maintainer 修复
    - MEDIUM/LOW → 加入 backlog，由 daily-orchestrator 排期

    流程：
    1. 解析告警（rule_id、severity、location、description）
    2. 按 security_severity_level 分级
    3. HIGH/CRITICAL → 创建建议单 → 派发 vibe-coding-maintainer
    4. MEDIUM/LOW → 创建 backlog item
    """
    if not _codeql_response_enabled():
        return {"ok": True, "skipped": True, "reason": "codeql response disabled"}

    rule = alert.get("rule", {}) or {}
    severity = str(rule.get("security_severity_level", "") or rule.get("severity", "low")).lower()
    rule_id = str(rule.get("id", "") or rule.get("name", "unknown"))
    rule_description = str(rule.get("description", "") or rule.get("short_description", ""))

    instance = alert.get("most_recent_instance", {}) or {}
    location = instance.get("location", {}) or {}
    file_path = str(location.get("path", "unknown"))
    start_line = location.get("start_line", location.get("startLine", "?"))

    alert_url = str(alert.get("html_url", "") or alert.get("url", ""))

    # 分级
    if severity in ("critical", "high"):
        risk_level = "high"
        target_employees = ["vibe-coding-maintainer"]
        kind = "codeql_fix"
        auto_dispatch = True
    elif severity == "medium":
        risk_level = "medium"
        target_employees = ["daily-orchestrator"]
        kind = "codeql_backlog"
        auto_dispatch = False
    else:
        risk_level = "low"
        target_employees = ["daily-orchestrator"]
        kind = "codeql_backlog"
        auto_dispatch = False

    from modstore_server.employee_autonomy_service import create_employee_suggestion

    summary = f"CodeQL [{severity.upper()}] {rule_id}: {file_path}:{start_line}"
    detail_parts = [
        f"告警来源: {source}",
        f"规则 ID: {rule_id}",
        f"严重程度: {severity}",
        f"风险等级: {risk_level}",
        f"文件位置: {file_path}:{start_line}",
        f"告警 URL: {alert_url}",
        f"规则描述: {rule_description}",
    ]
    detail = "\n".join(detail_parts)

    result = create_employee_suggestion(
        source_employee_id="security-secrets-guard",
        summary=summary,
        detail=detail,
        payload={
            "rule_id": rule_id,
            "severity": severity,
            "risk_level": risk_level,
            "file_path": file_path,
            "start_line": start_line,
            "alert_url": alert_url,
            "rule_description": rule_description,
            "source": source,
        },
        target_employee_ids=target_employees,
        kind=kind,
        risk_level=risk_level,
        auto_dispatch=auto_dispatch,
        emit_event=True,
    )

    from modstore_server.incident_bus import publish

    publish(
        "codeql.response.triggered",
        {
            "rule_id": rule_id,
            "severity": severity,
            "risk_level": risk_level,
            "file_path": file_path,
            "suggestion_id": result.get("suggestion_id"),
            "auto_dispatched": auto_dispatch,
        },
        source="auto_fix_loop",
    )

    return {
        "ok": True,
        "rule_id": rule_id,
        "severity": severity,
        "risk_level": risk_level,
        "auto_dispatched": auto_dispatch,
        "suggestion_id": result.get("suggestion_id"),
        "result": result,
    }
