"""Allow-listed command execution for the XC diagnostic terminal."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Sequence

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from modstore_server.deploy_context import health_payload
from modstore_server.diagnostic_terminal_core import (
    COMMANDS,
    MAX_LIMIT,
    DiagnosticTerminalError,
    ParsedCommand,
    envelope,
    item,
    matches,
    parse_command,
    status_for,
)
from modstore_server.diagnostic_terminal_sources import (
    delivery_items,
    dlq_items,
    file_log_items,
    find_accounts,
    incident_items,
    route_items,
    scheduler_items,
    scheduler_snapshot,
)
from modstore_server.entitlement_fast_lane import (
    FastLaneNotFound,
    account_fast_lane_status,
    resolve_account,
)
from modstore_server.models import IncidentEvent, OutboxDeadLetter, UpdateInstallationReceipt


def _doctor(
    db: Session,
    parsed: ParsedCommand,
    runtime_provider: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    deploy = health_payload()
    db.execute(text("SELECT 1"))
    recent_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    runtime = scheduler_snapshot(runtime_provider)
    scheduler_evidence = scheduler_items(runtime, "", MAX_LIMIT)
    items.extend(entry for entry in scheduler_evidence if entry["severity"] != "info")
    items.extend(dlq_items(db, "", 20))
    items.extend(incident_items(db, "", 20, problems_only=True, since=recent_cutoff))
    failed_installs = (
        db.query(UpdateInstallationReceipt)
        .filter(
            or_(
                UpdateInstallationReceipt.error != "",
                UpdateInstallationReceipt.status.in_(["failed", "error"]),
            ),
            UpdateInstallationReceipt.reported_at >= recent_cutoff,
        )
        .order_by(UpdateInstallationReceipt.id.desc())
        .limit(10)
        .all()
    )
    for row in failed_installs:
        items.append(
            item(
                "installation",
                "error",
                f"安装回执失败 · 用户 {row.user_id}",
                row.error or row.status,
                source=str(row.source or "update_installation_receipts"),
                reference=f"installation-receipt:{row.id}",
                timestamp=row.reported_at,
            )
        )
    _delivery_rows, delivery_summary = delivery_items(db, "", 1)
    event_count = int(
        db.query(func.count(IncidentEvent.id))
        .filter(IncidentEvent.created_at >= recent_cutoff)
        .scalar()
        or 0
    )
    dlq_count = int(
        db.query(func.count(OutboxDeadLetter.id))
        .filter(OutboxDeadLetter.resolved_at.is_(None))
        .scalar()
        or 0
    )
    raw_scheduler_summary = runtime.get("summary")
    scheduler_summary: dict[str, Any] = (
        raw_scheduler_summary if isinstance(raw_scheduler_summary, dict) else {}
    )
    status = status_for(items)
    attention = delivery_summary["pending_install"] + delivery_summary["pending_first_login"]
    if status == "healthy" and attention:
        status = "attention"
    metrics = {
        "deploy_tier": deploy.get("deploy_tier"),
        "git_sha": deploy.get("git_sha"),
        "artifact_sha256": deploy.get("artifact_sha256"),
        "database": "ok",
        "scheduler_status": runtime.get("status")
        or ("healthy" if runtime.get("ok") else "degraded"),
        "scheduler_failing": int(
            scheduler_summary.get("actionable_failing") or scheduler_summary.get("failing") or 0
        ),
        "scheduler_stale": int(
            scheduler_summary.get("actionable_stale") or scheduler_summary.get("stale") or 0
        ),
        "scheduler_deferred": int(scheduler_summary.get("deferred") or 0),
        "unresolved_dlq": dlq_count,
        "system_events_24h": event_count,
        **delivery_summary,
    }
    return envelope(
        parsed,
        summary=("发现需要处理的运行问题" if status == "degraded" else "运行面已完成快速体检"),
        status=status,
        metrics=metrics,
        items=items[: parsed.limit],
        hints=[
            "输入 problems 只看异常；输入 find <关键词> 跨账号、交付、任务、事件和路由搜索。",
            "策略等待（deferred）与真正失败分开显示；终端不会执行 shell 或修改业务数据。",
        ],
    )


def _account(db: Session, parsed: ParsedCommand) -> dict[str, Any]:
    try:
        user = resolve_account(db, parsed.query)
    except FastLaneNotFound as exc:
        raise DiagnosticTerminalError(str(exc)) from exc
    account_status = account_fast_lane_status(db, int(user.id))
    deliveries, _summary = delivery_items(db, str(user.id), MAX_LIMIT)
    data = {**account_status, "deliveries": [entry.get("data") for entry in deliveries]}
    account_item = item(
        "account",
        "info",
        str(user.username or user.id),
        f"有效套餐 {len(account_status['active_plans'])} 个，交付记录 {len(deliveries)} 条",
        source="users+user_plans+delivery_ssot",
        reference=f"user:{user.id}",
        data=data,
    )
    return envelope(
        parsed,
        summary=f"已定位账号 {user.username}",
        metrics={
            "active_plans": len(account_status["active_plans"]),
            "deliveries": len(deliveries),
        },
        items=[account_item],
        hints=["权益变更请使用独立的 entitlement-fast-lane；诊断终端始终只读。"],
    )


def _help(parsed: ParsedCommand) -> dict[str, Any]:
    selected = [
        entry
        for entry in COMMANDS
        if not parsed.query or matches(parsed.query, entry["name"], *entry["aliases"])
    ]
    return envelope(
        parsed,
        summary=f"可用只读命令 {len(selected)} 个",
        status="info",
        items=[
            item(
                "command",
                "info",
                entry["usage"],
                entry["description"],
                source="diagnostic_terminal",
            )
            for entry in selected
        ],
        hints=["示例：doctor；find 登录；account SUNBIRD；logs error --limit 20"],
    )


def _dispatch_query_command(
    db: Session,
    parsed: ParsedCommand,
    *,
    route_catalog: Sequence[dict[str, Any]],
    runtime_provider: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    if parsed.name == "delivery":
        items, metrics = delivery_items(db, parsed.query, parsed.limit)
        return envelope(
            parsed,
            summary=f"匹配交付 {len(items)} 条",
            status=status_for(items, empty="info"),
            metrics=metrics,
            items=items,
            hints=[
                "完成规则：客户外部 macOS/Windows 安装回执 + 同一购买账号首次登录；内部本机不计入。"
            ],
        )
    if parsed.name == "scheduler":
        runtime = scheduler_snapshot(runtime_provider)
        items = scheduler_items(runtime, parsed.query, parsed.limit)
        raw_metrics = runtime.get("summary")
        scheduler_metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
        return envelope(
            parsed,
            summary=f"匹配调度任务 {len(items)} 个",
            status=status_for(items, empty="info"),
            metrics=scheduler_metrics,
            items=items,
            hints=["deferred 表示策略等待人工批准，不等同于执行失败；请优先处理 failing/stale。"],
        )
    if parsed.name == "incidents":
        items = incident_items(db, parsed.query, parsed.limit)
        return envelope(
            parsed,
            summary=f"匹配系统事件 {len(items)} 条",
            status=status_for(items, empty="info"),
            items=items,
        )
    if parsed.name == "logs":
        evidence = incident_items(db, parsed.query, parsed.limit)
        evidence.extend(dlq_items(db, parsed.query, parsed.limit))
        evidence.extend(file_log_items(parsed.query, parsed.limit))
        items = evidence[: parsed.limit]
        return envelope(
            parsed,
            summary=f"匹配安全日志证据 {len(items)} 条",
            status=status_for(items, empty="info"),
            items=items,
            hints=["只读取配置允许的错误日志和事件账本；密钥、令牌与密码形态会自动脱敏。"],
        )
    if parsed.name == "routes":
        items = route_items(route_catalog, parsed.query, parsed.limit)
        hints = (
            []
            if route_catalog
            else ["当前未提供运行时路由表；请用 --openapi-url 指向本机 OpenAPI 后重试。"]
        )
        return envelope(
            parsed,
            summary=f"匹配 API 路由 {len(items)} 条",
            status="info",
            metrics={"runtime_routes": len(route_catalog)},
            items=items,
            hints=hints,
        )
    raise DiagnosticTerminalError(f"命令未实现：{parsed.name}")


def _problems(
    db: Session,
    parsed: ParsedCommand,
    runtime_provider: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    doctor = _doctor(db, ParsedCommand("doctor", limit=MAX_LIMIT), runtime_provider)
    items = [entry for entry in doctor["items"] if matches(parsed.query, *entry.values())]
    items = items[: parsed.limit]
    return envelope(
        parsed,
        summary=(f"匹配问题 {len(items)} 条" if items else "没有匹配到当前问题"),
        status=status_for(items),
        metrics=doctor["metrics"],
        items=items,
        hints=["没有结果只表示当前证据未命中关键词，不等于相关外部系统一定正常。"],
    )


def _find(
    db: Session,
    parsed: ParsedCommand,
    *,
    route_catalog: Sequence[dict[str, Any]],
    runtime_provider: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    runtime = scheduler_snapshot(runtime_provider)
    items: list[dict[str, Any]] = []
    items.extend(find_accounts(db, parsed.query, parsed.limit))
    delivery_evidence, _summary = delivery_items(db, parsed.query, parsed.limit)
    items.extend(delivery_evidence)
    items.extend(scheduler_items(runtime, parsed.query, parsed.limit))
    items.extend(incident_items(db, parsed.query, parsed.limit))
    items.extend(dlq_items(db, parsed.query, parsed.limit))
    items.extend(route_items(route_catalog, parsed.query, parsed.limit))
    items = items[: parsed.limit]
    return envelope(
        parsed,
        summary=f"跨域匹配 {len(items)} 条",
        status=status_for(items, empty="info"),
        metrics={"result_count": len(items), "searched_domains": 6},
        items=items,
        hints=[
            "需要精确账号详情时继续输入 account <账号>；需要原始事件时输入 incidents <关键词>。"
        ],
    )


def execute_diagnostic_command(
    db: Session,
    command_line: str,
    *,
    route_catalog: Sequence[dict[str, Any]] = (),
    runtime_provider: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Parse and execute one allow-listed, read-only diagnostic command."""

    started = time.perf_counter()
    parsed = parse_command(command_line)
    if parsed.name == "help":
        result = _help(parsed)
    elif parsed.name == "version":
        deploy = health_payload()
        result = envelope(
            parsed,
            summary=(
                f"{deploy.get('deploy_tier') or 'unknown'} · "
                f"{deploy.get('git_sha') or 'SHA 未知'}"
            ),
            status="info",
            metrics=deploy,
            hints=["生产验收应同时核对 git_sha、release_id 和 artifact_sha256。"],
        )
    elif parsed.name == "doctor":
        result = _doctor(db, parsed, runtime_provider)
    elif parsed.name == "account":
        result = _account(db, parsed)
    elif parsed.name == "problems":
        result = _problems(db, parsed, runtime_provider)
    elif parsed.name == "find":
        result = _find(
            db,
            parsed,
            route_catalog=route_catalog,
            runtime_provider=runtime_provider,
        )
    else:
        result = _dispatch_query_command(
            db,
            parsed,
            route_catalog=route_catalog,
            runtime_provider=runtime_provider,
        )
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


__all__ = ["execute_diagnostic_command"]
