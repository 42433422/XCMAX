# mypy: disable-error-code="attr-defined, index, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.public_visualization_api")


def _build_monitor_payload(
    traffic_source: dict[str, _facade().Any],
) -> tuple[dict[str, _facade().Any], dict[str, _facade().Any]]:
    """公开监控仪表盘：Prometheus → 本机 /metrics → 主机/网关日志。"""
    job = _facade()._prometheus_job()
    p95 = _facade()._prom_instant(
        f'histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{{job="{job}"}}[5m]))) * 1000'
    )
    rps = _facade()._prom_instant(f'sum(rate(api_requests_total{{job="{job}"}}[1m]))')
    err_rate = _facade()._prom_instant(
        f'sum(rate(api_requests_total{{job="{job}",status=~"5.."}}[5m])) / clamp_min(sum(rate(api_requests_total{{job="{job}"}}[5m])), 1) * 100'
    )
    active = _facade()._prom_instant("sum(active_requests)")
    pod_cpu = _facade()._prom_instant(
        'sum(rate(container_cpu_usage_seconds_total{pod=~"xcagi.*",container!=""}[5m])) * 100'
    )
    pod_mem = _facade()._prom_instant(
        'sum(container_memory_usage_bytes{pod=~"xcagi.*",container!=""})'
    )
    disk = _facade()._prom_instant(
        '100 * (1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}))'
    )
    restarts = _facade()._prom_instant(
        'sum(increase(kube_pod_container_status_restarts_total{pod=~"xcagi.*"}[1h]))'
    )
    mod_qps = _facade()._prom_instant(
        f'sum(rate(api_requests_total{{job="{job}",endpoint=~"/api/(mod-store|mods).*"}}[1m]))'
    )
    sqlite_ready = _facade()._prom_instant(
        f'sum(mod_sqlite_copy_present{{job="{job}"}}) / clamp_min(count(mod_sqlite_copy_present{{job="{job}"}}), 1) * 100'
    )
    neuro_delivery = _facade()._prom_instant(
        "100 * (1 - (sum(rate(neurobus_events_lost_total[5m])) + sum(rate(neurobus_events_dead_lettered_total[5m]))) / clamp_min(sum(rate(neurobus_events_published_total[5m])), 1))"
    )
    mod_p95 = _facade()._prom_instant(
        f'histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{{job="{job}",endpoint=~"/api/(mod-store|mods).*"}}[5m]))) * 1000'
    )
    bus_publish = _facade()._prom_instant("sum(rate(neurobus_events_published_total[1m]))")
    bus_loss = _facade()._prom_instant(
        "sum(increase(neurobus_events_lost_total[5m])) + sum(increase(neurobus_events_dead_lettered_total[5m]))"
    )
    breaker = _facade()._prom_instant("max(circuit_breaker_state) or on() vector(0)")
    ai_p95 = _facade()._prom_instant(
        f'histogram_quantile(0.95, sum by (le) (rate(ai_request_duration_seconds_bucket{{job="{job}"}}[5m]))) * 1000'
    )
    app_metrics = _facade()._scrape_app_metrics()
    bus_runtime = _facade()._bus_runtime_metrics()
    host = _facade()._host_infra_metrics()
    p95 = _facade()._coalesce(p95, app_metrics.get("p95_ms"))
    active = _facade()._coalesce(active, app_metrics.get("active"))
    err_rate = _facade()._coalesce(err_rate, app_metrics.get("err_rate"))
    mod_p95 = _facade()._coalesce(mod_p95, app_metrics.get("mod_p95_ms"))
    sqlite_ready = _facade()._coalesce(sqlite_ready, app_metrics.get("sqlite_ready"))
    neuro_delivery = _facade()._coalesce(
        neuro_delivery,
        app_metrics.get("neuro_delivery"),
        bus_runtime.get("neuro_delivery"),
    )
    bus_publish_rate = bus_publish
    bus_publish_total = _facade()._coalesce(
        app_metrics.get("bus_publish"), bus_runtime.get("bus_publish")
    )
    bus_loss = _facade()._coalesce(
        bus_loss, app_metrics.get("bus_loss"), bus_runtime.get("bus_loss")
    )
    breaker = _facade()._coalesce(
        (1.0 if breaker is not None and breaker >= 2 else 0.0) if breaker is not None else None,
        app_metrics.get("breaker_open"),
        bus_runtime.get("breaker_open"),
    )
    ai_p95 = _facade()._coalesce(ai_p95, app_metrics.get("ai_p95_ms"))
    use_host_infra = not any((v is not None for v in (pod_cpu, pod_mem, disk, restarts)))
    if use_host_infra:
        pod_cpu = host.get("cpu_pct")
        pod_mem_gib = host.get("mem_gib")
        disk = host.get("disk_pct")
        restarts = host.get("restarts")
    else:
        pod_mem_gib = pod_mem / 1024 / 1024 / 1024 if pod_mem is not None else None
    prom_hits = sum(
        (
            1
            for value in (
                p95,
                rps,
                err_rate,
                active,
                pod_cpu,
                pod_mem_gib,
                disk,
                restarts,
                mod_qps,
                sqlite_ready,
                neuro_delivery,
                mod_p95,
                bus_publish_rate,
                bus_loss,
                breaker,
                ai_p95,
            )
            if value is not None
        )
    )
    metrics_live = bool(app_metrics)
    api_requests = int(traffic_source.get("api_requests") or 0)
    api_5xx = int(traffic_source.get("api_5xx") or 0)
    mod_requests = int(traffic_source.get("mod_requests") or 0)
    window_days = int(traffic_source.get("window_days") or 0) or None
    log_err_rate = round(api_5xx / api_requests * 100, 2) if api_requests else None
    log_rps = (
        round(api_requests / (window_days * 86400), 4) if api_requests and window_days else None
    )
    log_mod_qps = (
        round(mod_requests / (window_days * 86400), 4) if mod_requests and window_days else None
    )
    if rps is not None:
        api_mode = "live"
    elif p95 is not None or active is not None or err_rate is not None:
        api_mode = "metrics"
    elif api_requests:
        api_mode = "logs"
    else:
        api_mode = "offline"
    if use_host_infra and any((v is not None for v in (pod_cpu, pod_mem_gib, disk))):
        infra_mode = "host"
    elif not use_host_infra and any(
        (v is not None for v in (pod_cpu, pod_mem_gib, disk, restarts))
    ):
        infra_mode = "live"
    else:
        infra_mode = "offline"
    mod_mode = (
        "live"
        if mod_qps is not None
        else (
            "metrics"
            if any((v is not None for v in (sqlite_ready, neuro_delivery, mod_p95)))
            else "logs" if mod_requests else "offline"
        )
    )
    bus_mode = (
        "live"
        if bus_publish_rate is not None
        else (
            "metrics"
            if any((v is not None for v in (bus_publish_total, bus_loss, breaker, ai_p95)))
            else "offline"
        )
    )
    bus_volume_value = _facade()._coalesce(bus_publish_rate, bus_publish_total)
    bus_volume_unit = "条/秒" if bus_publish_rate is not None else "条"
    bus_volume_title = "事件量 / 秒" if bus_publish_rate is not None else "事件累计"
    bus_loss_title = "丢失+DLQ 5m" if bus_publish_rate is not None else "丢失+DLQ 累计"
    monitor = {
        "title": "监控仪表盘 · Grafana / Prometheus / Loki",
        "subtitle": "4 块公开聚合面板 · Prometheus / 本机 metrics / 主机与网关日志回退",
        "stack": {
            "grafana_dashboards": 4,
            "prometheus": (
                "live"
                if rps is not None or bus_publish_rate is not None
                else "metrics" if metrics_live else "unavailable"
            ),
            "loki": "provisioned",
            "alertmanager": "provisioned",
        },
        "live_note": f"聚合命中 {prom_hits} 项"
        + (" · 含本机 /metrics" if metrics_live else "")
        + (" · 主机指标" if use_host_infra else ""),
        "dashboards": [
            {
                "id": "api",
                "title": "XCAGI · API 总览",
                "desc": "xcagi-api-overview · RED 指标 · modstore_http_* / 网关日志",
                "status": api_mode,
                "panels": [
                    _facade()._panel("API 延迟 P95", _facade()._fmt_num(p95), "ms", cls="c"),
                    _facade()._panel(
                        "请求量 / 秒",
                        (
                            _facade()._fmt_num(rps, digits=2)
                            if rps is not None
                            else _facade()._fmt_num(log_rps, digits=4)
                        ),
                        "次/秒",
                        cls="b",
                    ),
                    _facade()._panel(
                        "5xx 错误率",
                        (
                            _facade()._fmt_num(err_rate, digits=2)
                            if err_rate is not None
                            else _facade()._fmt_num(log_err_rate, digits=2)
                        ),
                        "%",
                        cls="g",
                    ),
                    _facade()._panel("活跃请求", _facade()._fmt_num(active), "个", cls="o"),
                ],
            },
            {
                "id": "infra",
                "title": "XCAGI · 基础设施",
                "desc": (
                    "xcagi-infrastructure · 本机 CPU/内存/磁盘"
                    if use_host_infra
                    else "xcagi-infrastructure · node / container 指标"
                ),
                "status": infra_mode,
                "panels": [
                    _facade()._panel(
                        "CPU 负载" if use_host_infra else "Pod CPU 使用率",
                        _facade()._fmt_num(pod_cpu, digits=1),
                        "%",
                        cls="c",
                    ),
                    _facade()._panel(
                        "内存已用" if use_host_infra else "Pod 内存",
                        _facade()._fmt_num(pod_mem_gib, digits=2),
                        "GiB",
                        cls="b",
                    ),
                    _facade()._panel("磁盘 /（根分区）", _facade()._fmt_num(disk), "%", cls="y"),
                    _facade()._panel(
                        "服务重启计数" if use_host_infra else "Pod 重启（1 小时）",
                        _facade()._fmt_num(restarts),
                        "次",
                        cls="g",
                    ),
                ],
            },
            {
                "id": "mod",
                "title": "XCAGI · Mod 商店",
                "desc": "xcagi-mod-store · Mod API 与目录流量",
                "status": mod_mode,
                "panels": [
                    _facade()._panel(
                        "目录 QPS",
                        (
                            _facade()._fmt_num(mod_qps, digits=2)
                            if mod_qps is not None
                            else _facade()._fmt_num(log_mod_qps, digits=4)
                        ),
                        "次/秒",
                        cls="c",
                    ),
                    _facade()._panel(
                        "SQLite 就绪率", _facade()._fmt_num(sqlite_ready), "%", cls="b"
                    ),
                    _facade()._panel(
                        "NeuroBus 投递率",
                        _facade()._fmt_num(neuro_delivery, digits=2),
                        "%",
                        cls="g",
                    ),
                    _facade()._panel("Mod API P95", _facade()._fmt_num(mod_p95), "ms", cls="p"),
                ],
            },
            {
                "id": "bus",
                "title": "XCAGI · 神经总线",
                "desc": "xcagi-neurobus · modstore_domain_events_* · circuit_breaker_state",
                "status": bus_mode,
                "panels": [
                    _facade()._panel(
                        bus_volume_title,
                        _facade()._fmt_num(bus_volume_value, digits=2),
                        bus_volume_unit,
                        cls="c",
                    ),
                    _facade()._panel(bus_loss_title, _facade()._fmt_num(bus_loss), "条", cls="g"),
                    _facade()._panel("断路器 OPEN", _facade()._fmt_num(breaker), "路", cls="g"),
                    _facade()._panel("AI 请求 P95", _facade()._fmt_num(ai_p95), "ms", cls="p"),
                ],
            },
        ],
        "issues": [],
    }
    source = {
        "status": "live" if prom_hits or api_requests or metrics_live else "unavailable",
        "prometheus": monitor["stack"]["prometheus"],
        "app_metrics": "live" if metrics_live else "unavailable",
        "host_metrics": "live" if use_host_infra else "unused",
        "gateway_logs": traffic_source.get("status") or "unavailable",
        "source_updated_at": traffic_source.get("source_updated_at"),
        "prom_hits": prom_hits,
    }
    return (monitor, source)


def _read_product_metrics(
    path: _facade().Path,
) -> tuple[dict[str, _facade().Any], dict[str, _facade().Any]]:
    try:
        raw = _facade().json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("release manifest root must be an object")
        history = raw.get("release_history")
        history = history if isinstance(history, list) else []
        current = history[0] if history and isinstance(history[0], dict) else {}
        platforms = current.get("platforms") if isinstance(current, dict) else []
        platforms = platforms if isinstance(platforms, list) else []
        release_ready = raw.get("release_ready")
        release_ready = release_ready if isinstance(release_ready, bool) else None
        product = {
            "stable_version": raw.get("version_lock") or raw.get("download_version"),
            "release_iterations": len(history),
            "delivery_platforms": len(platforms),
            "release_ready": release_ready,
            "release_status": (
                "READY" if release_ready is True else "PENDING" if release_ready is False else None
            ),
        }
        source_updated_at = (
            _facade()
            .datetime.fromtimestamp(path.stat().st_mtime, tz=_facade()._SHANGHAI)
            .isoformat(timespec="seconds")
        )
        return (product, {"status": "live", "source_updated_at": source_updated_at})
    except (OSError, ValueError, _facade().json.JSONDecodeError):
        return (
            {
                "stable_version": None,
                "release_iterations": None,
                "delivery_platforms": None,
                "release_ready": None,
                "release_status": None,
            },
            {"status": "unavailable", "source_updated_at": None},
        )


def _token_engine():
    from modstore_server.env_loader import load_modstore_env
    from modstore_server.models import get_engine

    load_modstore_env(_facade().Path(__file__).resolve().parents[1])
    return get_engine()


def _as_shanghai_datetime(value: _facade().Any) -> _facade().datetime | None:
    if value is None:
        return None
    parsed = value
    if not isinstance(parsed, _facade().datetime):
        try:
            parsed = _facade().datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_facade().ZoneInfo("UTC"))
    return parsed.astimezone(_facade()._SHANGHAI)


def _platform_made_snapshot_candidates() -> list[_facade().Path]:
    configured = (_facade().os.environ.get("XIUCI_PLATFORM_MADE_TOKENS_PATH") or "").strip()
    if configured:
        return [_facade().Path(configured).expanduser()]
    site_root = _facade().Path(__file__).resolve().parents[2]
    return [
        site_root / "data" / "platform_made_tokens.json",
        _facade().Path("/root/成都修茈科技有限公司/data/platform_made_tokens.json"),
        _facade().Path("/opt/xcmax/current/成都修茈科技有限公司/data/platform_made_tokens.json"),
        _facade().Path(
            "/opt/xcmax/releases/current/成都修茈科技有限公司/data/platform_made_tokens.json"
        ),
    ]


def _platform_made_snapshot_path() -> _facade().Path:
    for path in _facade()._platform_made_snapshot_candidates():
        if path.is_file():
            return path
    return _facade()._platform_made_snapshot_candidates()[0]


def _empty_made_token_metrics() -> dict[str, _facade().Any]:
    return {
        "platform_made_tokens": None,
        "platform_made_prompt_tokens": None,
        "platform_made_completion_tokens": None,
        "platform_made_sources": [],
        "platform_made_collected_at": None,
        "platform_tokens": None,
    }
