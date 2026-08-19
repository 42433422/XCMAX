# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.public_visualization_api")


def _metrics_base_url() -> str:
    return (
        _facade().os.environ.get("XIUCI_VISUALIZATION_METRICS_URL")
        or "http://127.0.0.1:9999/metrics"
    ).strip()


def _parse_metric_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    return {m.group(1): m.group(2).replace('\\"', '"') for m in _facade()._LABEL_RE.finditer(raw)}


def _scrape_app_metrics() -> dict[str, _facade().Any]:
    """解析本机应用 /metrics（Prometheus 不可达时的回退源）。"""
    url = _facade()._metrics_base_url()
    if not url:
        return {}
    request = _facade().Request(url, headers={"Accept": "text/plain"})
    try:
        with _facade().urlopen(request, timeout=0.8) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (_facade().HTTPError, _facade().URLError, TimeoutError, OSError, ValueError):
        return {}
    counters: dict[str, float] = {}
    gauges: dict[str, float] = {}
    hist_buckets: dict[str, list[tuple[float, float]]] = {}
    ai_hist_buckets: list[tuple[float, float]] = []
    mod_hist_buckets: list[tuple[float, float]] = []
    labeled_counters: list[tuple[str, dict[str, str], float]] = []
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _facade()._METRIC_LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        labels = _facade()._parse_metric_labels(match.group("labels"))
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if name.endswith("_bucket") and "le" in labels:
            base = name[: -len("_bucket")]
            try:
                le = float("inf") if labels["le"] == "+Inf" else float(labels["le"])
            except ValueError:
                continue
            hist_buckets.setdefault(base, []).append((le, value))
            path = labels.get("path") or ""
            if "/api/llm/" in path or "/chat/stream" in path:
                ai_hist_buckets.append((le, value))
            if any(
                (token in path for token in ("/api/mods", "/market/", "/v1/packages", "/mod-store"))
            ):
                mod_hist_buckets.append((le, value))
        elif labels:
            labeled_counters.append((name, labels, value))
            counters[name] = counters.get(name, 0.0) + value
        else:
            gauges[name] = value
            counters[name] = counters.get(name, 0.0) + value

    def histogram_quantile(buckets: list[tuple[float, float]], q: float = 0.95) -> float | None:
        if not buckets:
            return None
        by_le: dict[float, float] = {}
        for le, count in buckets:
            by_le[le] = by_le.get(le, 0.0) + count
        ordered = sorted(by_le.items(), key=lambda item: item[0])
        total = ordered[-1][1] if ordered else 0.0
        if total <= 0:
            return 0.0
        target = total * q
        prev_le = 0.0
        prev_count = 0.0
        for le, count in ordered:
            if count >= target:
                if le == float("inf"):
                    return prev_le
                span = max(le - prev_le, 0.0)
                weight = (target - prev_count) / max(count - prev_count, 1e-09)
                return prev_le + span * weight
            (prev_le, prev_count) = (le, count)
        return prev_le

    total_req = sum(
        (v for (name, labels, v) in labeled_counters if name == "modstore_http_requests_total")
    )
    err_req = sum(
        (
            v
            for (name, labels, v) in labeled_counters
            if name == "modstore_http_requests_total" and labels.get("outcome") == "server_error"
        )
    )
    bus_metric_names = ("modstore_domain_events_published_total", "neurobus_events_published_total")
    bus_metric_present = any((name in body for name in bus_metric_names))
    published = None
    for name in bus_metric_names:
        if name in gauges:
            published = gauges[name]
            break
        if name in counters:
            published = counters[name]
            break
    if published is None and bus_metric_present:
        published = 0.0
    lost = gauges.get("neurobus_events_lost_total")
    if lost is None:
        lost = counters.get("neurobus_events_lost_total")
    if lost is None:
        lost = counters.get("modstore_domain_events_lost_total")
    dlq = gauges.get("neurobus_events_dead_lettered_total")
    if dlq is None:
        dlq = counters.get("neurobus_events_dead_lettered_total")
    if dlq is None:
        dlq = counters.get("modstore_domain_events_dead_lettered_total")
    if published is not None:
        lost = 0.0 if lost is None else float(lost)
        dlq = 0.0 if dlq is None else float(dlq)
    breaker_raw = gauges.get("circuit_breaker_state")
    if breaker_raw is None:
        breaker_raw = counters.get("circuit_breaker_state")
    if breaker_raw is not None:
        breaker_open = 1.0 if float(breaker_raw) >= 2 else 0.0
    elif published is not None:
        breaker_open = 0.0
    else:
        breaker_open = None
    delivery = None
    if published is not None:
        denom = max(float(published), 1.0)
        delivery = max(0.0, 100.0 * (1.0 - (float(lost) + float(dlq)) / denom))
    p95 = histogram_quantile(hist_buckets.get("modstore_http_request_duration_seconds") or [])
    mod_p95 = histogram_quantile(mod_hist_buckets) or p95
    ai_p95 = histogram_quantile(ai_hist_buckets) or p95
    active = gauges.get("active_requests")
    if active is None and total_req >= 0 and body.strip():
        active = 0.0
    return {
        "p95_ms": p95 * 1000.0 if p95 is not None else None,
        "mod_p95_ms": mod_p95 * 1000.0 if mod_p95 is not None else None,
        "active": active,
        "err_rate": err_req / total_req * 100.0 if total_req > 0 else None,
        "sqlite_ready": 100.0,
        "neuro_delivery": delivery,
        "bus_publish": float(published) if published is not None else None,
        "bus_loss": float(lost) + float(dlq) if published is not None else None,
        "breaker_open": breaker_open,
        "ai_p95_ms": ai_p95 * 1000.0 if ai_p95 is not None else None,
        "raw_request_total": total_req,
    }


def _bus_runtime_metrics() -> dict[str, float | None]:
    """进程内 NeuroBus 统计（单 worker；补 Prometheus 无样本时的缺口）。"""
    try:
        from modstore_server.eventing.global_bus import neuro_bus

        stats = neuro_bus.get_stats()
    except Exception:
        return {}
    if not isinstance(stats, dict):
        return {}
    published = float(stats.get("published") or 0)
    dropped = float(stats.get("dropped") or 0)
    errors = float(stats.get("errors") or 0)
    state = str(stats.get("circuit_breaker_state") or "closed").lower()
    breaker_open = 1.0 if state == "open" else 0.0
    loss = dropped + errors
    delivery = max(0.0, 100.0 * (1.0 - loss / max(published, 1.0)))
    return {
        "bus_publish": published,
        "bus_loss": loss,
        "breaker_open": breaker_open,
        "neuro_delivery": delivery,
    }


def _host_infra_metrics() -> dict[str, float | None]:
    """CVM 单机回退：负载 / 内存 / 根分区，不依赖 K8s。"""
    cpu_pct: float | None = None
    mem_gib: float | None = None
    disk_pct: float | None = None
    try:
        load1 = _facade().os.getloadavg()[0]
        nproc = max(_facade().os.cpu_count() or 1, 1)
        cpu_pct = min(100.0, max(0.0, load1 / nproc * 100.0))
    except (AttributeError, OSError):
        cpu_pct = None
    try:
        meminfo = _facade().Path("/proc/meminfo").read_text(encoding="utf-8")
        total_kb = avail_kb = None
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total_kb = float(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail_kb = float(line.split()[1])
        if total_kb and avail_kb is not None:
            mem_gib = max(0.0, (total_kb - avail_kb) * 1024.0 / 1024**3)
    except (OSError, ValueError, IndexError):
        mem_gib = None
    try:
        usage = _facade().os.statvfs("/")
        total = usage.f_blocks * usage.f_frsize
        free = usage.f_bavail * usage.f_frsize
        if total > 0:
            disk_pct = (1.0 - free / total) * 100.0
    except (AttributeError, OSError, ZeroDivisionError):
        disk_pct = None
    return {"cpu_pct": cpu_pct, "mem_gib": mem_gib, "disk_pct": disk_pct, "restarts": 0.0}


def _panel(
    title: str, value: _facade().Any, unit: str = "", *, cls: str = "c"
) -> dict[str, _facade().Any]:
    return {"title": title, "value": value, "unit": unit, "cls": cls}


def _fmt_num(value: float | None, *, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    if digits <= 0:
        return int(round(value))
    return round(value, digits)


def _coalesce(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _build_monitor_payload(
    traffic_source: dict[str, _facade().Any]
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
        neuro_delivery, app_metrics.get("neuro_delivery"), bus_runtime.get("neuro_delivery")
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
        {"status": "unavailable", "source_updated_at": None, "snapshot_path": str(last_path)},
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
    (ai, downloads, traffic_source) = _facade()._read_traffic_metrics(log_paths)
    (token_metrics, token_source) = _facade()._read_token_metrics()
    (made_metrics, made_source) = _facade()._read_platform_made_metrics()
    ai.update(token_metrics)
    ai.update(made_metrics)
    (product, release_source) = _facade()._read_product_metrics(_facade()._release_manifest_path())
    (monitor, monitor_source) = _facade()._build_monitor_payload(traffic_source)
    source_statuses = (traffic_source["status"], token_source["status"], release_source["status"])
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


def clear_public_visualization_cache() -> None:
    """Clear the per-process cache; exposed for tests and controlled reloads."""
    global _CACHE_VALUE, _CACHE_CREATED_MONOTONIC
    with _facade()._CACHE_LOCK:
        _facade()._CACHE_VALUE = None
        _facade()._CACHE_CREATED_MONOTONIC = 0.0
