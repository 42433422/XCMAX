# mypy: disable-error-code="arg-type, attr-defined, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
            prev_le, prev_count = (le, count)
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
    bus_metric_names = (
        "modstore_domain_events_published_total",
        "neurobus_events_published_total",
    )
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
    except RECOVERABLE_ERRORS:
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
    return {
        "cpu_pct": cpu_pct,
        "mem_gib": mem_gib,
        "disk_pct": disk_pct,
        "restarts": 0.0,
    }


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
