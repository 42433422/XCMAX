# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.public_visualization_api")


def _read_platform_made_metrics() -> tuple[dict[str, _facade().Any], dict[str, _facade().Any]]:
    """读取管理端同源的「平台制作 Token」公开快照。"""
    last_path = _facade()._platform_made_snapshot_path()
    for path in _facade()._platform_made_snapshot_candidates():
        last_path = path
        try:
            if not path.is_file():
                continue
            raw = _facade().json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("platform made snapshot root must be an object")
            made = int(raw.get("platform_made_tokens") or 0)
            sources_raw = raw.get("sources")
            sources: list[dict[str, _facade().Any]] = []
            if isinstance(sources_raw, list):
                for item in sources_raw:
                    if not isinstance(item, dict):
                        continue
                    sources.append(
                        {
                            "key": str(item.get("key") or ""),
                            "label": str(item.get("label") or item.get("key") or ""),
                            "available": bool(item.get("available")),
                            "total_tokens": int(item.get("total_tokens") or 0),
                            "estimated": bool(item.get("estimated")),
                        }
                    )
            metrics = {
                "platform_made_tokens": made,
                "platform_made_prompt_tokens": int(raw.get("platform_made_prompt_tokens") or 0),
                "platform_made_completion_tokens": int(
                    raw.get("platform_made_completion_tokens") or 0
                ),
                "platform_made_sources": sources,
                "platform_made_collected_at": str(
                    raw.get("collected_at") or raw.get("generated_at") or ""
                )
                or None,
                "platform_tokens": made,
            }
            source_updated_at = (
                str(raw.get("generated_at") or raw.get("collected_at") or "") or None
            )
            return (
                metrics,
                {
                    "status": "live",
                    "source_updated_at": source_updated_at,
                    "snapshot_path": str(path),
                },
            )
        except (OSError, ValueError, _facade().json.JSONDecodeError, TypeError):
            continue
    return (
        _facade()._empty_made_token_metrics(),
        {
            "status": "unavailable",
            "source_updated_at": None,
            "snapshot_path": str(last_path),
        },
    )


def _empty_token_metrics() -> dict[str, _facade().Any]:
    return {
        "platform_usage_tokens": None,
        "chat_tokens": None,
        "employee_tokens": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "estimated_chat_tokens": None,
        "top_chat_model": None,
        "top_chat_provider": None,
        "top_chat_model_tokens": None,
        "top_chat_model_calls": None,
        "top_chat_model_share": None,
        "chat_models": [],
        "token_records": None,
        "token_window_start": None,
        "token_window_end": None,
        "token_window_start_short": None,
        "token_window_end_short": None,
    }


def _read_token_metrics() -> tuple[dict[str, _facade().Any], dict[str, _facade().Any]]:
    try:
        engine = _facade()._token_engine()
        with engine.connect() as connection:
            chat = (
                connection.execute(
                    _facade().text(
                        "\n                    SELECT COUNT(*) AS records,\n                           COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,\n                           COALESCE(SUM(completion_tokens), 0) AS completion_tokens,\n                           COALESCE(SUM(total_tokens), 0) AS total_tokens,\n                           COALESCE(SUM(CASE WHEN estimated THEN total_tokens ELSE 0 END), 0)\n                               AS estimated_tokens,\n                           MIN(created_at) AS first_at,\n                           MAX(created_at) AS last_at\n                    FROM llm_call_logs\n                    WHERE status = 'success' AND total_tokens > 0\n                    "
                    )
                )
                .mappings()
                .one()
            )
            employee = (
                connection.execute(
                    _facade().text(
                        "\n                    SELECT COUNT(*) AS records,\n                           COALESCE(SUM(llm_tokens), 0) AS total_tokens,\n                           MIN(created_at) AS first_at,\n                           MAX(created_at) AS last_at\n                    FROM employee_execution_metrics\n                    WHERE llm_tokens > 0\n                    "
                    )
                )
                .mappings()
                .one()
            )
            model_rows = (
                connection.execute(
                    _facade().text(
                        "\n                    SELECT model,\n                           provider,\n                           COUNT(*) AS calls,\n                           COALESCE(SUM(total_tokens), 0) AS tokens\n                    FROM llm_call_logs\n                    WHERE status = 'success' AND total_tokens > 0\n                    GROUP BY model, provider\n                    ORDER BY tokens DESC\n                    "
                    )
                )
                .mappings()
                .all()
            )
    except (_facade().SQLAlchemyError, OSError, ValueError):
        return (
            _facade()._empty_token_metrics(),
            {"status": "unavailable", "source_updated_at": None},
        )
    chat_tokens = int(chat["total_tokens"] or 0)
    employee_tokens = int(employee["total_tokens"] or 0)
    first_values = [
        parsed
        for parsed in (
            _facade()._as_shanghai_datetime(chat["first_at"]),
            _facade()._as_shanghai_datetime(employee["first_at"]),
        )
        if parsed is not None
    ]
    last_values = [
        parsed
        for parsed in (
            _facade()._as_shanghai_datetime(chat["last_at"]),
            _facade()._as_shanghai_datetime(employee["last_at"]),
        )
        if parsed is not None
    ]
    window_start = min(first_values) if first_values else None
    window_end = max(last_values) if last_values else None
    chat_models = [
        {
            "model": str(row["model"] or "unknown"),
            "provider": str(row["provider"] or "unknown"),
            "calls": int(row["calls"] or 0),
            "tokens": int(row["tokens"] or 0),
            "share": round(int(row["tokens"] or 0) / chat_tokens * 100, 2) if chat_tokens else 0.0,
        }
        for row in model_rows
    ]
    top_model = chat_models[0] if chat_models else None
    usage_tokens = chat_tokens + employee_tokens
    metrics = {
        "platform_usage_tokens": usage_tokens,
        "chat_tokens": chat_tokens,
        "employee_tokens": employee_tokens,
        "prompt_tokens": int(chat["prompt_tokens"] or 0),
        "completion_tokens": int(chat["completion_tokens"] or 0),
        "estimated_chat_tokens": int(chat["estimated_tokens"] or 0),
        "top_chat_model": top_model["model"] if top_model else None,
        "top_chat_provider": top_model["provider"] if top_model else None,
        "top_chat_model_tokens": top_model["tokens"] if top_model else None,
        "top_chat_model_calls": top_model["calls"] if top_model else None,
        "top_chat_model_share": top_model["share"] if top_model else None,
        "chat_models": chat_models,
        "token_records": int(chat["records"] or 0) + int(employee["records"] or 0),
        "token_window_start": window_start.date().isoformat() if window_start else None,
        "token_window_end": window_end.date().isoformat() if window_end else None,
        "token_window_start_short": (
            _facade()._short_date(window_start.date()) if window_start else None
        ),
        "token_window_end_short": _facade()._short_date(window_end.date()) if window_end else None,
    }
    return (
        metrics,
        {
            "status": "live",
            "source_updated_at": window_end.isoformat(timespec="seconds") if window_end else None,
            "chat_records": int(chat["records"] or 0),
            "employee_records": int(employee["records"] or 0),
            "model_coverage": "chat_ledger_only",
        },
    )


def _build_public_visualization_data() -> dict[str, _facade().Any]:
    log_paths = _facade()._access_log_paths()
    ai, downloads, traffic_source = _facade()._read_traffic_metrics(log_paths)
    token_metrics, token_source = _facade()._read_token_metrics()
    made_metrics, made_source = _facade()._read_platform_made_metrics()
    ai.update(token_metrics)
    ai.update(made_metrics)
    product, release_source = _facade()._read_product_metrics(_facade()._release_manifest_path())
    monitor, monitor_source = _facade()._build_monitor_payload(traffic_source)
    source_statuses = (
        traffic_source["status"],
        token_source["status"],
        release_source["status"],
    )
    data_status = "live" if all((status == "live" for status in source_statuses)) else "degraded"
    generated_at = _facade().datetime.now(tz=_facade()._SHANGHAI).isoformat(timespec="seconds")
    source_updates = [
        value
        for value in (
            traffic_source.get("source_updated_at"),
            token_source.get("source_updated_at"),
            made_source.get("source_updated_at"),
            monitor_source.get("source_updated_at"),
            release_source.get("source_updated_at"),
        )
        if value
    ]
    return {
        "schema": "xiu-ci.public-visualization/v1",
        "data_status": data_status,
        "generated_at": generated_at,
        "source_updated_at": max(source_updates) if source_updates else None,
        "cache_ttl_seconds": _facade()._cache_ttl_seconds(),
        "ai": ai,
        "downloads": downloads,
        "product": product,
        "monitor": monitor,
        "sources": {
            "gateway_logs": traffic_source,
            "token_ledger": token_source,
            "platform_made_tokens": made_source,
            "monitor": monitor_source,
            "release_manifest": release_source,
        },
        "definitions": {
            "ai_requests": "生产网关滚动日志内 POST /api/llm/chat/stream 的请求数",
            "ai_success": "上述请求中 HTTP 200 的响应数",
            "platform_made_tokens": "管理端同源算法：FHD 本地账本 + Cursor + Codex + Trae + mimo 五源合计",
            "platform_usage_tokens": "线上平台使用量：对话计费日志 total_tokens 与 AI 员工执行度量 llm_tokens 之和，不重复汇总 Duty 节点副本",
            "platform_tokens": "同 platform_made_tokens（兼容旧字段）",
            "model_usage": "模型分布仅按可精确归属的对话计费日志统计；历史 AI 员工度量未存模型名，不做推断",
            "complete_downloads": "安装包 GET 请求完整返回 HTTP 200 的响应数；排除 HEAD、分片与更新 ZIP",
            "monitor": "监控仪表盘公开聚合：优先本机 Prometheus，回退网关访问日志；不含 Grafana 截图与告警明细",
        },
        "privacy": "仅提供聚合指标，不包含 IP、账户、对话内容、单用户 Token 账单或请求明细",
    }
