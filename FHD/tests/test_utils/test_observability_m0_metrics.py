"""M0 Grafana panel metric names (mod_sqlite_copy_present / neurobus_events_*)."""

from __future__ import annotations

from unittest.mock import patch


def test_neurobus_metric_counters_increment():
    from app.utils import metrics

    before_pub = metrics.neurobus_events_published_total._value.get()
    before_lost = metrics.neurobus_events_lost_total._value.get()
    before_dlq = metrics.neurobus_events_dead_lettered_total._value.get()

    metrics.record_neurobus_published(2)
    metrics.record_neurobus_lost(1)
    metrics.record_neurobus_dead_lettered(1)

    assert metrics.neurobus_events_published_total._value.get() == before_pub + 2
    assert metrics.neurobus_events_lost_total._value.get() == before_lost + 1
    assert metrics.neurobus_events_dead_lettered_total._value.get() == before_dlq + 1


def test_record_api_request_increments_counter():
    from app.utils import metrics

    before = metrics.api_requests_total.labels(
        method="GET", endpoint="/api/health", status="200"
    )._value.get()
    metrics.record_api_request("GET", "/api/health", 200)
    after = metrics.api_requests_total.labels(
        method="GET", endpoint="/api/health", status="200"
    )._value.get()
    assert after == before + 1


def test_refresh_mod_sqlite_copy_metrics_sets_gauge(tmp_path, monkeypatch):
    from app.db.init_db import DEFAULT_DB_FILES
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    from app.utils import metrics

    mod_id = "demo-mod"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    db_name = DEFAULT_DB_FILES[0]
    dest = sqlite_filename_with_mod_suffix(db_name, mod_id)
    (work_dir / dest).write_bytes(b"sqlite")

    monkeypatch.setenv("XCAGI_SQLITE_PER_MOD_COPIES", "1")

    with patch("app.db.init_db.get_app_data_dir", return_value=str(work_dir)):
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path / "data")):
            ready = metrics.refresh_mod_sqlite_copy_metrics([mod_id])

    assert ready == 1
    assert metrics.mod_sqlite_copy_present.labels(mod_id=mod_id)._value.get() == 1.0


def test_seed_local_observability_metrics_sets_api_counters(monkeypatch):
    from app.utils import metrics

    monkeypatch.setattr(
        "app.utils.metrics.refresh_mod_sqlite_copy_metrics",
        lambda *a, **k: 0,
    )
    monkeypatch.setattr(
        "app.neuro_bus.bus.get_neuro_bus",
        lambda: type("B", (), {"_running": False})(),
    )
    out = metrics.seed_local_observability_metrics(neuro_probe_events=0)
    assert out["api_requests_seeded"] == 10000
    total = sum(
        metrics.api_requests_total.labels(
            method="GET", endpoint="/api/health", status=s
        )._value.get()
        for s in ("200", "500")
    )
    assert total >= 10000
