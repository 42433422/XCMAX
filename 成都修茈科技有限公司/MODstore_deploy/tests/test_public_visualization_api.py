from __future__ import annotations

import gzip
import json

from sqlalchemy import create_engine, text

from modstore_server import public_visualization_api


def _log_line(method: str, target: str, status: int, day: str, *, ip: str = "203.0.113.9") -> str:
    return (
        f"{ip} - - [{day}/Jul/2026:12:00:00 +0800] "
        f'"{method} {target} HTTP/2.0" {status} 123 "-" "pytest"\n'
    )


def _configure_sources(monkeypatch, tmp_path):
    active_log = tmp_path / "xiu-ci.com.access.log"
    rotated_log = tmp_path / "xiu-ci.com.access.log.1.gz"
    active_log.write_text(
        "".join(
            (
                _log_line("POST", "/api/llm/chat/stream", 200, "19"),
                _log_line("POST", "/api/llm/chat/stream", 500, "19"),
                _log_line("GET", "/xcagi-v1.0.0.0/XCAGI.exe", 200, "19"),
                _log_line("GET", "/downloads/kellai/KeLaiLai.dmg?from=home", 200, "19"),
                _log_line("HEAD", "/xcagi-v1.0.0.0/XCAGI.apk", 200, "19"),
                _log_line("GET", "/xcagi-v1.0.0.0/XCAGI.dmg", 206, "19"),
                _log_line("GET", "/releases/stable/update.zip", 200, "19"),
                _log_line("GET", "/private/customer/acme", 200, "19", ip="198.51.100.77"),
            )
        ),
        encoding="utf-8",
    )
    with gzip.open(rotated_log, "wt", encoding="utf-8") as handle:
        handle.write(_log_line("POST", "/api/llm/chat/stream", 200, "10"))
        handle.write(_log_line("GET", "/xcagi-v1.0.0.0/XCAGI.apk", 200, "10"))

    manifest = tmp_path / "download-release.json"
    manifest.write_text(
        json.dumps(
            {
                "version_lock": "1.0.0.0",
                "release_ready": True,
                "release_history": [
                    {"version": "1.0.0.0", "platforms": ["Windows", "macOS", "Android"]},
                    {"version": "10.0.0"},
                ],
            }
        ),
        encoding="utf-8",
    )
    made_snapshot = tmp_path / "platform_made_tokens.json"
    made_snapshot.write_text(
        json.dumps(
            {
                "schema": "xiu-ci.platform-made-tokens/v1",
                "generated_at": "2026-07-21T10:00:00+00:00",
                "collected_at": "2026-07-21 18:00:00",
                "platform_made_tokens": 900,
                "platform_made_prompt_tokens": 600,
                "platform_made_completion_tokens": 300,
                "sources": [
                    {
                        "key": "local",
                        "label": "FHD 本地账本",
                        "available": True,
                        "total_tokens": 100,
                        "estimated": False,
                    },
                    {
                        "key": "cursor",
                        "label": "Cursor",
                        "available": True,
                        "total_tokens": 800,
                        "estimated": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XIUCI_VISUALIZATION_ACCESS_LOG_GLOB", str(tmp_path / "*.log*"))
    monkeypatch.setenv("XIUCI_VISUALIZATION_RELEASE_MANIFEST", str(manifest))
    monkeypatch.setenv("XIUCI_PLATFORM_MADE_TOKENS_PATH", str(made_snapshot))
    monkeypatch.setenv("XIUCI_VISUALIZATION_CACHE_TTL_SECONDS", "30")
    # 单测不打本机 Prometheus，避免 urlopen 超时拖慢用例
    monkeypatch.setattr(public_visualization_api, "_prom_instant", lambda _expr: None)

    token_engine = create_engine(f"sqlite:///{tmp_path / 'tokens.db'}")
    with token_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE llm_call_logs (
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    estimated BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE employee_execution_metrics (
                    llm_tokens INTEGER NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO llm_call_logs VALUES
                    ('success', 'alpha-pro', 'provider-a', 100, 50, 150, 0, '2026-07-10 04:00:00'),
                    ('success', 'beta', 'provider-b', 20, 10, 30, 1, '2026-07-19 12:00:00'),
                    ('failed', 'alpha-pro', 'provider-a', 0, 0, 0, 0, '2026-07-19 13:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO employee_execution_metrics VALUES
                    (220, '2026-07-12 06:00:00'),
                    (0, '2026-07-19 14:00:00')
                """
            )
        )
    monkeypatch.setattr(public_visualization_api, "_token_engine", lambda: token_engine)
    public_visualization_api.clear_public_visualization_cache()
    return token_engine


def test_live_aggregates_use_logs_and_release_manifest(monkeypatch, tmp_path):
    _configure_sources(monkeypatch, tmp_path)

    payload = public_visualization_api.get_public_visualization_data()

    assert payload["data_status"] == "live"
    assert payload["ai"]["chat_requests"] == 3
    assert payload["ai"]["chat_success"] == 2
    assert payload["ai"]["success_rate"] == 66.67
    assert payload["ai"]["platform_usage_tokens"] == 400
    assert payload["ai"]["chat_tokens"] == 180
    assert payload["ai"]["employee_tokens"] == 220
    assert payload["ai"]["platform_made_tokens"] == 900
    assert payload["ai"]["platform_tokens"] == 900
    assert payload["ai"]["top_chat_model"] == "alpha-pro"
    assert payload["ai"]["token_records"] == 3
    assert payload["sources"]["platform_made_tokens"]["status"] == "live"
    assert payload["monitor"]["stack"]["grafana_dashboards"] == 4
    assert len(payload["monitor"]["dashboards"]) == 4
    assert payload["monitor"]["dashboards"][0]["id"] == "api"
    assert payload["sources"]["monitor"]["status"] in {"live", "unavailable"}
    assert payload["sources"]["gateway_logs"]["api_requests"] >= 3
    assert payload["downloads"]["total"] == 3
    assert payload["downloads"]["platforms"] == {"windows": 1, "macos": 1, "android": 1}
    assert payload["downloads"]["products"] == {"xcagi": 2, "kellai": 1}
    assert len(payload["downloads"]["daily"]) == 10
    assert payload["downloads"]["daily"][0]["count"] == 1
    assert payload["downloads"]["daily"][-1]["count"] == 2
    assert payload["product"] == {
        "stable_version": "1.0.0.0",
        "release_iterations": 2,
        "delivery_platforms": 3,
        "release_ready": True,
        "release_status": "READY",
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "203.0.113.9" not in serialized
    assert "198.51.100.77" not in serialized
    assert "/private/customer/acme" not in serialized


def test_public_endpoint_needs_no_auth_and_sets_cache_headers(client, monkeypatch, tmp_path):
    _configure_sources(monkeypatch, tmp_path)

    response = client.get("/api/public/visualization")

    assert response.status_code == 200
    assert response.json()["data_status"] == "live"
    assert response.headers["cache-control"] == "public, max-age=15, stale-if-error=60"
    assert response.headers["x-data-generated-at"] == response.json()["generated_at"]


def test_token_metrics_include_every_historic_chat_model(monkeypatch, tmp_path):
    token_engine = _configure_sources(monkeypatch, tmp_path)
    with token_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO llm_call_logs VALUES
                    ('success', 'gamma', 'provider-c', 1, 0, 1, 0, '2026-07-19 12:01:00'),
                    ('success', 'delta', 'provider-d', 1, 0, 1, 0, '2026-07-19 12:02:00'),
                    ('success', 'epsilon', 'provider-e', 1, 0, 1, 0, '2026-07-19 12:03:00'),
                    ('success', 'zeta', 'provider-f', 1, 0, 1, 0, '2026-07-19 12:04:00'),
                    ('success', 'eta', 'provider-g', 1, 0, 1, 0, '2026-07-19 12:05:00')
                """
            )
        )
    public_visualization_api.clear_public_visualization_cache()

    models = public_visualization_api.get_public_visualization_data()["ai"]["chat_models"]

    assert len(models) == 7
    assert {item["model"] for item in models} == {
        "alpha-pro",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
    }
    assert sum(item["calls"] for item in models) == 7


def test_missing_sources_are_honestly_degraded(monkeypatch, tmp_path):
    monkeypatch.setenv("XIUCI_VISUALIZATION_ACCESS_LOG_GLOB", str(tmp_path / "missing*.log"))
    monkeypatch.setenv("XIUCI_VISUALIZATION_RELEASE_MANIFEST", str(tmp_path / "missing.json"))
    monkeypatch.setenv("XIUCI_PLATFORM_MADE_TOKENS_PATH", str(tmp_path / "missing-made.json"))
    monkeypatch.setattr(public_visualization_api, "_prom_instant", lambda _expr: None)
    monkeypatch.setattr(
        public_visualization_api,
        "_token_engine",
        lambda: (_ for _ in ()).throw(OSError("missing token ledger")),
    )
    public_visualization_api.clear_public_visualization_cache()

    payload = public_visualization_api.get_public_visualization_data()

    assert payload["data_status"] == "degraded"
    assert payload["ai"]["chat_requests"] is None
    assert payload["ai"]["platform_usage_tokens"] is None
    assert payload["ai"]["platform_made_tokens"] is None
    assert payload["ai"]["platform_tokens"] is None
    assert payload["ai"]["top_chat_model"] is None
    assert payload["downloads"]["total"] is None
    assert payload["product"]["stable_version"] is None
    assert payload["sources"]["gateway_logs"]["status"] == "unavailable"
    assert payload["sources"]["token_ledger"]["status"] == "unavailable"
    assert payload["sources"]["platform_made_tokens"]["status"] == "unavailable"
    assert payload["sources"]["release_manifest"]["status"] == "unavailable"
