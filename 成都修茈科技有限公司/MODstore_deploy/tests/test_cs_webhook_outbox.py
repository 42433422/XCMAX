from __future__ import annotations

import sqlite3
from pathlib import Path


def _create_legacy_outbox(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE cs_webhook_outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              target_url TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              headers_json TEXT NOT NULL DEFAULT '{}',
              attempts INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL DEFAULT 5,
              last_error TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              landing_contact_id INTEGER,
              market_user_id INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              next_retry_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO cs_webhook_outbox (
              target_url, payload_json, headers_json, attempts, max_attempts,
              last_error, status, created_at, updated_at, next_retry_at
            ) VALUES (?, ?, '{}', 0, 5, '', 'pending', ?, ?, ?)
            """,
            (
                "http://127.0.0.1:5100/api/mod/example/user-cs/landing-funnel/sync",
                '{"landing_contact_id": 1}',
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )


def test_runtime_dir_is_preferred_over_tmp(monkeypatch, tmp_path):
    from modstore_server import cs_webhook_outbox as outbox

    monkeypatch.delenv("MODSTORE_CS_WEBHOOK_OUTBOX_PATH", raising=False)
    monkeypatch.delenv("MODSTORE_DATA_DIR", raising=False)
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))

    assert outbox._db_path() == tmp_path / "runtime" / "cs_webhook_outbox.sqlite3"


def test_legacy_pending_rows_are_migrated_once_and_held(monkeypatch, tmp_path):
    from modstore_server import cs_webhook_outbox as outbox

    legacy_path = tmp_path / "legacy.sqlite3"
    _create_legacy_outbox(legacy_path)
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODSTORE_LEGACY_CS_WEBHOOK_OUTBOX_PATH", str(legacy_path))

    outbox.ensure_outbox_schema()
    outbox.ensure_outbox_schema()

    summary = outbox.outbox_status_summary()
    assert summary["storage"] == "configured"
    assert summary["pending_count"] == 0
    assert summary["recovery_pending_count"] == 1
    with sqlite3.connect(outbox._db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cs_webhook_outbox").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM cs_webhook_outbox_migrations").fetchone()[0] == 1


def test_retry_job_is_registered_and_tracked(monkeypatch):
    from modstore_server import cs_webhook_outbox as outbox

    jobs = []
    tracked = []

    class Scheduler:
        def add_job(self, func, trigger, **kwargs):
            jobs.append((func, trigger, kwargs))

    monkeypatch.setenv("MODSTORE_CS_WEBHOOK_OUTBOX_RETRY_SECONDS", "5")
    monkeypatch.setattr(
        outbox,
        "process_pending_outbox",
        lambda *, limit: {"delivered": 0, "failed": 0, "skipped": 0},
    )

    assert outbox.register_retry_job(
        Scheduler(),
        track_job=lambda job_id, fn: tracked.append((job_id, fn())),
    )
    assert jobs[0][2]["id"] == "cs_webhook_outbox_retry"
    assert jobs[0][1].interval.total_seconds() == 30
    jobs[0][0]()
    assert tracked == [("cs_webhook_outbox_retry", {"delivered": 0, "failed": 0, "skipped": 0})]


def test_cs_webhook_url_requires_explicit_bridge_configuration(monkeypatch):
    from modstore_server import market_auth_api

    for name in (
        "XCAGI_FHD_INTERNAL_URL",
        "FHD_INTERNAL_BASE_URL",
        "XCAGI_API_BASE_URL",
        "XCAGI_LANDING_FUNNEL_WEBHOOK_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert market_auth_api._default_landing_funnel_webhook_url() == ""


def test_scheduler_extensions_register_the_capability_and_webhook_jobs(monkeypatch):
    from modstore_server import scheduler_extensions

    seen = []

    monkeypatch.setattr(
        "modstore_server.capability_proposal_relay.register_capability_proposal_relay_job",
        lambda scheduler, *, track_job: seen.append(("capability", scheduler, track_job)),
    )
    monkeypatch.setattr(
        "modstore_server.cs_webhook_outbox.register_retry_job",
        lambda scheduler, *, track_job: seen.append(("webhook", scheduler, track_job)),
    )

    scheduler_extensions.register_extensions("scheduler", track_job="tracker")

    assert seen == [
        ("capability", "scheduler", "tracker"),
        ("webhook", "scheduler", "tracker"),
    ]
