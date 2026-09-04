from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _module():
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "observability"
        / "collect_slo_metrics.py"
    )
    spec = importlib.util.spec_from_file_location("production_slo_collector", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verifier_module():
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "observability"
        / "verify_production_slo_window.py"
    )
    spec = importlib.util.spec_from_file_location("production_slo_verifier", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_workflow_uses_private_authenticated_prometheus_tunnel() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "slo-metrics-collect.yml"
    ).read_text(encoding="utf-8")

    assert "Open authenticated production Prometheus SSH tunnel" in workflow
    assert "-L 127.0.0.1:19091:127.0.0.1:9091" in workflow
    assert 'test "$PRODUCTION_PROMETHEUS_URL" = "http://127.0.0.1:19091"' in workflow
    assert "PRODUCTION_PROMETHEUS_TOKEN" in workflow
    assert "NO_PROXY: 127.0.0.1,localhost" in workflow
    assert "Close production Prometheus SSH tunnel" in workflow
    assert "seed" not in workflow.lower()


def test_missing_production_source_writes_fail_closed_evidence(tmp_path: Path) -> None:
    mod = _module()
    output = tmp_path / "evidence" / "one.json"

    payload, passed = mod.collect(
        prom_url="",
        prom_token="",
        window="30d",
        mode="preflight",
        release_id="",
        raw_retention_days=0,
        out_path=output,
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )

    assert passed is False
    assert payload["source_status"] == "source_unavailable"
    assert payload["coverage"] == 0
    assert payload["day0_eligible"] is False
    assert all(row["passes"] is False for row in payload["readings"].values())
    assert json.loads(output.read_text())["all_pass"] is False


def test_reachable_source_with_empty_metrics_is_available_but_not_eligible(
    tmp_path: Path, monkeypatch
) -> None:
    mod = _module()
    monkeypatch.setattr(mod, "prom_query", lambda *_args, **_kwargs: None)

    payload, passed = mod.collect(
        prom_url="https://prometheus.example.invalid",
        prom_token="prod-token",
        window="1d",
        mode="preflight",
        release_id="",
        raw_retention_days=120,
        out_path=tmp_path / "empty.json",
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )

    assert passed is False
    assert payload["source_status"] == "available"
    assert payload["source_errors"] == []
    assert payload["coverage"] == 0
    assert payload["day0_eligible"] is False
    assert "SLO-AI-01:empty_reading" in payload["errors"]


def test_real_samples_are_required_and_evidence_is_hash_chained(
    tmp_path: Path, monkeypatch
) -> None:
    mod = _module()
    release_id = "xcagi-1.0.0.1-" + "a" * 40
    good_values = {
        "SLO-API-01": 0.9999,
        "SLO-API-02": 100,
        "SLO-API-03": 0.0001,
        "SLO-AI-01": 200,
        "SLO-BUS-01": 0.9999,
        "SLO-BIZ-01": 200,
        "SLO-BIZ-02": 0.0001,
        "SLO-BIZ-03": 1000,
        "SLO-BIZ-04": 1000,
        "SLO-BIZ-05": 1.0,
    }

    def fake_query(
        _url: str,
        expr: str,
        bearer_token: str = "",
        query_at: datetime | None = None,
    ) -> str:
        assert bearer_token == "prod-token"
        assert query_at is not None
        assert 'environment="production"' in expr
        for slo_id, template in mod.SAMPLE_QUERIES.items():
            if expr == template.format(w="90d"):
                return str(mod.SAMPLE_MINIMUMS[slo_id])
        for slo_id, template in mod.QUERIES.items():
            if expr == template.format(w="90d"):
                return str(good_values[slo_id])
        raise AssertionError(expr)

    monkeypatch.setattr(mod, "prom_query", fake_query)
    evidence_dir = tmp_path / "evidence"
    first_path = evidence_dir / "20260904.json"
    second_path = evidence_dir / "20260905.json"
    first, first_pass = mod.collect(
        prom_url="https://prometheus.example.invalid",
        prom_token="prod-token",
        window="90d",
        mode="formal",
        release_id=release_id,
        raw_retention_days=120,
        out_path=first_path,
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )
    second, second_pass = mod.collect(
        prom_url="https://prometheus.example.invalid",
        prom_token="prod-token",
        window="90d",
        mode="formal",
        release_id=release_id,
        raw_retention_days=120,
        out_path=second_path,
        now=datetime(2026, 9, 4, tzinfo=UTC) + timedelta(days=1),
    )

    assert first_pass is True
    assert second_pass is True
    assert first["day0_eligible"] is True
    assert second["previous_chain_hash"] == first["chain_hash"]
    assert all(row["sample_sufficient"] for row in second["readings"].values())


def test_slo_evidence_never_overwrites_existing_record(tmp_path: Path) -> None:
    mod = _module()
    path = tmp_path / "existing.json"
    path.write_text("{}\n")
    try:
        mod._write_immutable(path, {"new": True})
    except FileExistsError as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("existing evidence was overwritten")


def test_hash_chain_ignores_unrelated_json_values(tmp_path: Path) -> None:
    mod = _module()
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "newer-unrelated.json").write_text('["not", "evidence"]\n')
    expected_hash = "a" * 64
    (evidence_dir / "older-evidence.json").write_text(
        json.dumps({"chain_hash": expected_hash}) + "\n"
    )

    assert mod._latest_chain_hash(evidence_dir) == expected_hash


def test_backfill_requires_reason_and_stays_within_24_hours(tmp_path: Path) -> None:
    mod = _module()
    recorded_at = datetime(2026, 9, 4, 12, tzinfo=UTC)
    for evidence_at, reason, message in (
        (recorded_at - timedelta(hours=2), "", "non-empty reason"),
        (recorded_at - timedelta(hours=25), "missed schedule", "preceding 24 hours"),
    ):
        try:
            mod.collect(
                prom_url="",
                prom_token="",
                window="1d",
                mode="preflight",
                release_id="",
                raw_retention_days=120,
                out_path=tmp_path / f"{evidence_at.hour}.json",
                now=recorded_at,
                evidence_at=evidence_at,
                backfill_reason=reason,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid backfill was accepted")


def test_verifier_requires_90_continuous_hash_chained_formal_days(
    tmp_path: Path, monkeypatch
) -> None:
    collector = _module()
    verifier = _verifier_module()
    release_id = "xcagi-1.0.0.1-" + "a" * 40
    values = {
        "SLO-API-01": 0.9999,
        "SLO-API-02": 100,
        "SLO-API-03": 0.0001,
        "SLO-AI-01": 200,
        "SLO-BUS-01": 0.9999,
        "SLO-BIZ-01": 200,
        "SLO-BIZ-02": 0.0001,
        "SLO-BIZ-03": 1000,
        "SLO-BIZ-04": 1000,
        "SLO-BIZ-05": 1.0,
    }

    def fake_query(_url, expr, bearer_token="", query_at=None):
        for slo_id, template in collector.SAMPLE_QUERIES.items():
            if expr == template.format(w="90d"):
                return str(collector.SAMPLE_MINIMUMS[slo_id])
        for slo_id, template in collector.QUERIES.items():
            if expr == template.format(w="90d"):
                return str(values[slo_id])
        raise AssertionError(expr)

    monkeypatch.setattr(collector, "prom_query", fake_query)
    start = datetime(2026, 9, 4, 12, tzinfo=UTC)
    for offset in range(90):
        collector.collect(
            prom_url="https://prometheus.example.invalid",
            prom_token="prod-token",
            window="90d",
            mode="formal",
            release_id=release_id,
            raw_retention_days=120,
            out_path=tmp_path / f"{offset:03d}.json",
            now=start + timedelta(days=offset),
        )

    passed = verifier.verify_window(tmp_path, release_id=release_id)
    assert passed["passed"] is True
    assert passed["continuous_days"] == 90

    tampered_path = tmp_path / "089.json"
    tampered = json.loads(tampered_path.read_text())
    tampered["coverage"] = 0
    tampered_path.write_text(json.dumps(tampered))
    failed = verifier.verify_window(tmp_path, release_id=release_id)
    assert failed["passed"] is False
    assert any("invalid_evidence_hash" in item for item in failed["blockers"])
