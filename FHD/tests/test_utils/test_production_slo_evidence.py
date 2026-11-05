from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml


def _module(*, live_retention: bool = False):
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "observability" / "collect_slo_metrics.py"
    )
    spec = importlib.util.spec_from_file_location("production_slo_collector", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not live_retention:
        module.measure_retention_days = lambda *_a, **_k: None
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


def test_daily_workflow_queries_prometheus_over_ssh_exec_not_port_forward() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "slo-metrics-collect.yml"
    ).read_text(encoding="utf-8")

    assert "Open production SSH channel and ensure Prometheus is serving" in workflow
    assert "-L 127.0.0.1" not in workflow
    assert "ensure_production_prometheus.sh" in workflow
    assert "PRODUCTION_PROMETHEUS_SSH_TARGET" in workflow
    assert "PRODUCTION_PROMETHEUS_SSH_CONTROL" in workflow
    assert "Close production SSH channel" in workflow
    assert "always() && steps.slo_collect.outcome != 'success'" in workflow
    assert "seed" not in workflow.lower()


def test_observability_installer_paths_resolve_under_published_working_directory():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load(
        (root / ".github/workflows/fhd-production-observability.yml").read_text()
    )
    cwd = root / workflow["defaults"]["run"]["working-directory"]
    steps = workflow["jobs"]["install-and-readback"]["steps"]
    command = next(
        step["run"]
        for step in steps
        if step.get("name") == "Install, validate, and read back production targets"
    )
    lines = command.splitlines()
    index = next(i for i, line in enumerate(lines) if line.strip().startswith("scp "))
    sources = []
    for line in lines[index + 1 :]:
        if line.strip().startswith('"${remote}'):
            break
        sources.append(line.strip().rstrip("\\").strip())
    assert len(sources) == 6
    assert all((cwd / path).is_file() for path in sources)


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
        **_kwargs,
    ) -> str:
        assert bearer_token == "prod-token"
        assert query_at is not None
        assert 'environment="production"' in expr
        if expr in mod.SCRAPE_QUERIES.values():
            return "5760"
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

    def fake_query(_url, expr, bearer_token="", query_at=None, **_kwargs):
        if expr in collector.SCRAPE_QUERIES.values():
            return "5760"
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


def test_scrape_inventory_matches_production_configuration():
    mod = _module()
    path = Path(__file__).resolve().parents[2] / "monitoring/prometheus.production.yml"
    config = yaml.safe_load(path.read_text())
    assert config["global"]["scrape_interval"] == f"{mod.SCRAPE_INTERVAL_SECONDS}s"
    production = {
        job["job_name"]: entry
        for job in config["scrape_configs"]
        for entry in job.get("static_configs", [])
        if entry["labels"].get("environment") == "production"
    }
    assert {job: entry["targets"][0] for job, entry in production.items()} == mod.SCRAPE_TARGETS
    assert {
        job: entry["labels"]["service"] for job, entry in production.items()
    } == mod.SCRAPE_SERVICES
    for job, entry in production.items():
        assert len(entry["targets"]) == 1
        assert entry["labels"]["env"] == entry["labels"]["environment"] == "production"
        assert f'service="{mod.SCRAPE_SERVICES[job]}"' in mod.SCRAPE_QUERIES[job]


@pytest.mark.parametrize(
    "scrapes,eligible", [(None, False), (0, False), (5000, False), (5760, True), (11520, False)]
)
def test_metric_presence_cannot_replace_real_per_target_scrape_coverage(
    tmp_path, monkeypatch, scrapes, eligible
):
    mod = _module()

    def query(_url, expr, **_kwargs):
        if expr == mod.SCRAPE_QUERIES["modstore-api-production"]:
            return None if scrapes is None else str(scrapes)
        if expr in mod.SCRAPE_QUERIES.values():
            return "5760"
        return "1"

    monkeypatch.setattr(mod, "prom_query", query)
    payload, _ = mod.collect(
        prom_url="https://prometheus.example.invalid",
        prom_token="prod-token",
        window="1d",
        mode="preflight",
        release_id="",
        raw_retention_days=120,
        out_path=tmp_path / "record.json",
    )
    assert payload["coverage"] == 1.0
    assert payload["day0_eligible"] is eligible
    if not eligible:
        assert payload["scrape_coverage"] < 0.99


def test_connection_reset_is_retried_then_succeeds(tmp_path: Path, monkeypatch) -> None:
    mod = _module()

    class Resp:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    state = {"n": 0}

    def fake_urlopen(req, timeout=30):
        state["n"] += 1
        if state["n"] < 3:
            raise ConnectionResetError("simulated tunnel reset")
        return Resp(b'{"status":"success","data":{"result":[{"value":[0,"5760"]}]}}')

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    assert mod.prom_query("http://127.0.0.1:19091", "up", bearer_token="t") == "5760"
    assert state["n"] == 3


def test_main_exits_nonzero_when_source_unavailable(tmp_path: Path, monkeypatch, capsys) -> None:
    mod = _module()
    out = tmp_path / "fail.json"
    monkeypatch.setattr(
        mod.sys,
        "argv",
        [
            "collect_slo_metrics.py",
            "--prom-url",
            "",
            "--prom-token",
            "",
            "--window",
            "1d",
            "--mode",
            "preflight",
            "--raw-retention-days",
            "0",
            "--out",
            str(out),
        ],
    )
    code = mod.main()
    assert code == 2
    payload = json.loads(out.read_text())
    assert payload["source_status"] == "source_unavailable"
    assert payload["coverage"] == 0
    assert payload["all_pass"] is False
    assert mod.telemetry_admissible(payload) is False


def test_empty_coverage_fails_preflight_gate(tmp_path: Path, monkeypatch) -> None:
    mod = _module()
    monkeypatch.setattr(mod, "prom_query", lambda *_a, **_k: None)
    out = tmp_path / "empty.json"
    monkeypatch.setattr(
        mod.sys,
        "argv",
        [
            "collect_slo_metrics.py",
            "--prom-url",
            "http://127.0.0.1:19091",
            "--prom-token",
            "tok",
            "--window",
            "1d",
            "--mode",
            "preflight",
            "--raw-retention-days",
            "120",
            "--out",
            str(out),
        ],
    )
    code = mod.main()
    assert code == 2
    payload = json.loads(out.read_text())
    assert payload["source_status"] == "available"
    assert payload["coverage"] == 0
    assert mod.telemetry_admissible(payload) is False


def test_ssh_exec_transport_sends_promql_on_stdin_without_port_forward(
    tmp_path: Path, monkeypatch
) -> None:
    mod = _module(live_retention=True)
    calls: list[tuple[list[str], bytes]] = []

    class Done:
        returncode = 0

        def __init__(self, body: str) -> None:
            self.stdout = body.encode()

    def fake_run(command, input, **_kwargs):
        calls.append((command, input))
        if "/api/v1/status/flags" in command[-1]:
            return Done('{"status":"success","data":{"storage.tsdb.retention.time":"17w1d"}}')
        return Done('{"status":"success","data":{"result":[{"value":[0,"5760"]}]}}')

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    ssh = mod.SshTransport("root@prod.example.invalid", "/tmp/ctl")
    payload, _ = mod.collect(
        prom_url=mod.HOST_LOCAL_PROMETHEUS,
        prom_token="",
        window="1d",
        mode="preflight",
        release_id="",
        raw_retention_days=0,
        out_path=tmp_path / "ssh.json",
        ssh=ssh,
    )
    assert payload["transport"] == "ssh-exec"
    assert payload["source_status"] == "available"
    assert payload["raw_metric_retention_days"] == 120
    assert payload["raw_metric_retention_source"] == "prometheus_flags"
    for command, stdin in calls:
        assert "-L" not in command
        assert command[command.index("-S") + 1] == "/tmp/ctl"
        assert command[-1].startswith("curl -fsS")
        assert "up{" not in command[-1]
    assert any(b'service="modstore"' in stdin for _command, stdin in calls)


def test_ssh_exec_failure_is_retried_then_recorded_fail_closed(tmp_path: Path, monkeypatch) -> None:
    mod = _module(live_retention=True)

    class Failed:
        returncode = 255
        stdout = b""

    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k: Failed())
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    payload, all_pass = mod.collect(
        prom_url=mod.HOST_LOCAL_PROMETHEUS,
        prom_token="",
        window="1d",
        mode="preflight",
        release_id="",
        raw_retention_days=0,
        out_path=tmp_path / "fail.json",
        ssh=mod.SshTransport("root@prod.example.invalid"),
    )
    assert all_pass is False
    assert payload["source_status"] == "source_unavailable"
    assert "SLO-API-01:source_unavailable:ConnectionError" in payload["source_errors"]
    assert payload["raw_metric_retention_source"] == "declared"


def test_seven_day_observation_ledger_records_every_gap(tmp_path: Path, monkeypatch) -> None:
    mod = _module()
    verifier = _verifier_module()
    start = datetime(2026, 11, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(mod, "measure_retention_days", lambda *_a, **_k: 120.0)
    for offset in range(7):
        if offset == 3:
            continue

        def query(_url, expr, offset=offset, **_kwargs):
            if expr in mod.SCRAPE_QUERIES.values():
                return "5000" if offset == 5 else "5760"
            return "1"

        monkeypatch.setattr(mod, "prom_query", query)
        mod.collect(
            prom_url="https://prometheus.example.invalid",
            prom_token="prod-token",
            window="1d",
            mode="preflight",
            release_id="",
            raw_retention_days=0,
            out_path=tmp_path / f"{offset:03d}.json",
            now=start + timedelta(days=offset),
        )
    ledger = verifier.observation_ledger(tmp_path, days=7)
    assert ledger["passed"] is False
    assert len(ledger["days"]) == 7
    assert "2026-11-04:no_collection_record" in ledger["gaps"]
    assert any(g.startswith("2026-11-06:fhd-api-stable:scrape_coverage") for g in ledger["gaps"])
    assert ledger["retention"] == {"days": 120.0, "source": "prometheus_flags"}
