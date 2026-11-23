from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta, timezone
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
        module.measure_retention_days = lambda *_a, **_k: 120.0
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
    assert (
        "always() && (steps.slo_collect.outcome != 'success' "
        "|| steps.sloth_generate.outcome != 'success')"
    ) in workflow
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


@pytest.fixture
def formal_slo_window(tmp_path: Path, monkeypatch):
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

    def collect(offset, *, available=True, evidence_at=None, identity=release_id):
        return collector.collect(
            prom_url="https://prometheus.example.invalid" if available else "",
            prom_token="prod-token",
            window="90d",
            mode="formal",
            release_id=identity,
            raw_retention_days=120,
            out_path=tmp_path / f"{len(list(tmp_path.glob('*.json'))):03d}.json",
            now=start + timedelta(days=offset),
            evidence_at=evidence_at,
            backfill_reason="recover raw telemetry" if evidence_at is not None else "",
        )

    for offset in range(90):
        collect(offset)
    return verifier, release_id, start + timedelta(days=89), collect


def test_verifier_requires_90_continuous_hash_chained_formal_days(tmp_path, formal_slo_window):
    verifier, release_id, now, _collect = formal_slo_window
    passed = verifier.verify_window(tmp_path, release_id=release_id, now=now)
    assert passed["passed"] is True
    assert passed["continuous_days"] == 90

    tampered_path = tmp_path / "089.json"
    tampered = json.loads(tampered_path.read_text())
    tampered["coverage"] = 0
    tampered_path.write_text(json.dumps(tampered))
    failed = verifier.verify_window(tmp_path, release_id=release_id, now=now)
    assert failed["passed"] is False
    assert any("invalid_evidence_hash" in item for item in failed["blockers"])


@pytest.mark.parametrize(
    "offset,blocker",
    [
        (timedelta(), ""),
        (timedelta(hours=24), ""),
        (timedelta(microseconds=-1), "future_collection_record"),
        (timedelta(hours=24, microseconds=1), "latest_formal_sample_stale_or_missing"),
    ],
)
def test_formal_window_freshness_has_exact_daily_boundary(
    tmp_path, formal_slo_window, offset, blocker
):
    verifier, release_id, end, _collect = formal_slo_window
    result = verifier.verify_window(tmp_path, release_id=release_id, now=end + offset)
    assert result["passed"] is (not blocker)
    assert result["latest_sample_at"] <= result["verified_at"]
    if blocker:
        assert blocker in result["blockers"]


@pytest.mark.parametrize("offset,available,expected_days", [(89.25, False, 0), (91, True, 1)])
def test_historical_pass_cannot_hide_newer_failure_or_collection_gap(
    tmp_path, formal_slo_window, offset, available, expected_days
):
    verifier, release_id, end, collect = formal_slo_window
    collect(offset, available=available)
    result = verifier.verify_window(
        tmp_path, release_id=release_id, now=end + timedelta(days=offset - 89)
    )
    assert result["passed"] is False
    assert result["continuous_days"] == expected_days
    assert f"formal_continuous_days:{expected_days}/90" in result["blockers"]


def test_formal_window_uses_utc_instants_and_not_backfill_commit_order(tmp_path, formal_slo_window):
    verifier, release_id, end, collect = formal_slo_window
    collect(89.125, available=False, evidence_at=end - timedelta(hours=1))
    observed = (end + timedelta(hours=3)).astimezone(timezone(timedelta(hours=14)))
    result = verifier.verify_window(tmp_path, release_id=release_id, now=observed)
    assert result["passed"] is True
    assert result["day_n"] == end.date().isoformat()
    assert result["verified_at"] == (end + timedelta(hours=3)).isoformat()
    with pytest.raises(ValueError, match="timezone"):
        verifier.verify_window(tmp_path, release_id=release_id, now=end.replace(tzinfo=None))


def test_other_release_cannot_refresh_or_extend_formal_window(tmp_path, formal_slo_window):
    verifier, release_id, end, collect = formal_slo_window
    collect(91, identity="xcagi-1.0.0.1-" + "b" * 40)
    result = verifier.verify_window(tmp_path, release_id=release_id, now=end + timedelta(days=2))
    assert result["passed"] is False
    assert result["continuous_days"] == 90
    assert result["day_n"] == end.date().isoformat()
    assert "latest_formal_sample_stale_or_missing" in result["blockers"]


@pytest.mark.parametrize("key", ["coverage", "scrape_coverage"])
@pytest.mark.parametrize("value", [float("inf"), float("nan"), "invalid", True, None, 1.01, 0.98])
def test_invalid_coverage_cannot_qualify_a_hash_valid_record(
    tmp_path, formal_slo_window, key, value
):
    verifier, release_id, end, _collect = formal_slo_window
    path = tmp_path / "089.json"
    record = json.loads(path.read_text())
    record[key] = value
    for excluded in ("evidence_hash", "chain_hash", "all_pass"):
        record.pop(excluded, None)
    record["evidence_hash"] = hashlib.sha256(verifier._canonical(record).encode()).hexdigest()
    record["chain_hash"] = hashlib.sha256(
        f"{record['previous_chain_hash']}:{record['evidence_hash']}".encode()
    ).hexdigest()
    path.write_text(json.dumps(record))
    result = verifier.verify_window(tmp_path, release_id=release_id, now=end)
    assert result["passed"] is False
    assert result["continuous_days"] == 0
    assert not any("hash" in blocker for blocker in result["blockers"])


def test_scrape_inventory_matches_production_configuration():
    mod = _module()
    path = Path(__file__).resolve().parents[2] / "ops/monitoring/prometheus.production.yml"
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
    "scrapes,eligible",
    [(None, False), (0, False), (5000, False), (5760, True), (11520, False)],
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
    ledger = verifier.observation_ledger(tmp_path, days=7, now=start + timedelta(days=6))
    assert ledger["passed"] is False
    assert len(ledger["days"]) == 7
    assert "2026-11-04:no_collection_record" in ledger["gaps"]
    assert any(g.startswith("2026-11-06:fhd-api-stable:scrape_coverage") for g in ledger["gaps"])
    assert ledger["retention"] == {"days": 120.0, "source": "prometheus_flags"}


def _complete_observation(tmp_path, monkeypatch, *, count=1):
    collector = _module(live_retention=True)
    monkeypatch.setattr(collector, "measure_retention_days", lambda *_a, **_k: 120.0)
    values = dict.fromkeys(collector.TARGETS, 1.0)
    values.update({"SLO-API-03": 0.0, "SLO-BIZ-02": 0.0})

    def query(_url, expr, **_kwargs):
        if expr in collector.SCRAPE_QUERIES.values():
            return "5760"
        for slo_id, template in collector.SAMPLE_QUERIES.items():
            if expr == template.format(w="90d"):
                return str(collector.SAMPLE_MINIMUMS[slo_id])
        return str(
            next(values[k] for k, v in collector.QUERIES.items() if v.format(w="90d") == expr)
        )

    monkeypatch.setattr(collector, "prom_query", query)
    for offset in range(count):
        collector.collect(
            prom_url="https://prometheus.example.invalid",
            prom_token="prod-token",
            window="90d",
            mode="formal",
            release_id="release-a",
            raw_retention_days=0,
            out_path=tmp_path / f"{offset:03d}.json",
            now=datetime(2026, 11, 1, 12, tzinfo=UTC) + timedelta(days=offset),
        )
    return collector


def _rewrite_record(path, collector, mutate, *, rehash=True):
    import hashlib

    payload = json.loads(path.read_text())
    mutate(payload)
    if rehash:
        unhashed = {
            k: v for k, v in payload.items() if k not in {"evidence_hash", "chain_hash", "all_pass"}
        }
        payload["evidence_hash"] = hashlib.sha256(
            collector._canonical_json(unhashed).encode()
        ).hexdigest()
        payload["chain_hash"] = hashlib.sha256(
            f"{payload['previous_chain_hash']}:{payload['evidence_hash']}".encode()
        ).hexdigest()
    path.write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "mutation", ["missing_target", "missing_hash", "wrong_count", "wrong_environment"]
)
def test_observation_rejects_unproven_scrape_coverage(tmp_path, monkeypatch, mutation):
    collector = _complete_observation(tmp_path, monkeypatch)
    mutations = {
        "missing_target": lambda p: p["scrape_evidence"].pop("modstore-api-production"),
        "missing_hash": lambda p: p.pop("evidence_hash"),
        "wrong_count": lambda p: p["scrape_evidence"]["fhd-api-stable"].update(
            successful_scrapes=0
        ),
        "wrong_environment": lambda p: p.update(environment="staging"),
    }
    _rewrite_record(
        tmp_path / "000.json", collector, mutations[mutation], rehash=mutation != "missing_hash"
    )
    result = _verifier_module().observation_ledger(
        tmp_path, days=1, now=datetime(2026, 11, 1, 12, tzinfo=UTC)
    )
    assert result["passed"] is False
    assert result["gaps"]


@pytest.mark.parametrize(
    "mutation", ["unknown_metric", "sample_count", "sample_floor", "reading", "declared_retention"]
)
def test_formal_window_recomputes_actual_slo_results(tmp_path, monkeypatch, mutation):
    collector = _complete_observation(tmp_path, monkeypatch)
    mutations = {
        "unknown_metric": lambda p: p["readings"].update(
            {"wrong": p["readings"].pop("SLO-BIZ-05")}
        ),
        "sample_count": lambda p: p["readings"]["SLO-BIZ-05"].update(sample_count=0),
        "sample_floor": lambda p: p["readings"]["SLO-BIZ-05"].update(
            sample_count=collector.SAMPLE_MINIMUMS["SLO-BIZ-05"] - 1
        ),
        "reading": lambda p: p["readings"]["SLO-API-01"].update(reading_numeric=0.5, reading="0.5"),
        "declared_retention": lambda p: p.update(raw_metric_retention_source="declared"),
    }
    _rewrite_record(tmp_path / "000.json", collector, mutations[mutation])
    result = _verifier_module().verify_window(
        tmp_path,
        release_id="release-a",
        required_days=1,
        now=datetime(2026, 11, 1, 12, tzinfo=UTC),
    )
    assert result["passed"] is False
    assert result["blockers"]
    assert "latest_formal_sample_stale_or_missing" not in result["blockers"]
    if mutation in {"reading", "sample_floor"}:
        slo_id = "SLO-API-01" if mutation == "reading" else "SLO-BIZ-05"
        assert f"{slo_id}:target_or_sample_failed" in result["blockers"]


def test_concurrent_collections_keep_one_chain_independent_of_filenames(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    collector = _complete_observation(tmp_path, monkeypatch)

    def append(filename):
        return collector.collect(
            prom_url="https://prometheus.example.invalid",
            prom_token="prod-token",
            window="90d",
            mode="formal",
            release_id="release-a",
            raw_retention_days=0,
            out_path=tmp_path / filename,
            now=datetime(2026, 11, 1, 12, tzinfo=UTC),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(append, ["z.json", "b.json", "q.json", "c.json"]))
    assert all(passed for _record, passed in results)
    assert len({record["chain_hash"] for record, _passed in results}) == 4
    verifier = _verifier_module()
    assert (
        verifier.observation_ledger(tmp_path, days=1, now=datetime(2026, 11, 1, 12, tzinfo=UTC))[
            "passed"
        ]
        is True
    )
    assert (
        verifier.verify_window(
            tmp_path,
            release_id="release-a",
            required_days=1,
            now=datetime(2026, 11, 1, 12, tzinfo=UTC),
        )["passed"]
        is True
    )


def test_observation_stops_passing_when_daily_collection_stops(tmp_path, monkeypatch):
    _complete_observation(tmp_path, monkeypatch, count=7)
    verifier = _verifier_module()
    final_day = datetime(2026, 11, 7, 12, tzinfo=UTC)
    assert verifier.observation_ledger(tmp_path, days=7, now=final_day)["passed"] is True
    stale = verifier.observation_ledger(tmp_path, days=7, now=final_day + timedelta(days=1))
    assert stale["passed"] is False
    assert stale["window"] == "2026-11-02..2026-11-08"
    assert "2026-11-08:no_collection_record" in stale["gaps"]


def test_declared_retention_does_not_replace_prometheus_flag_readback(tmp_path, monkeypatch):
    collector = _complete_observation(tmp_path, monkeypatch)
    monkeypatch.setattr(collector, "measure_retention_days", lambda *_a, **_k: None)
    payload, passed = collector.collect(
        prom_url="https://prometheus.example.invalid",
        prom_token="prod-token",
        window="90d",
        mode="formal",
        release_id="release-a",
        raw_retention_days=120,
        out_path=tmp_path / "declared.json",
    )
    assert passed is False
    assert payload["day0_eligible"] is False
    assert collector.telemetry_admissible(payload) is False
    assert "raw_metric_retention_not_measured" in payload["errors"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "malformed"])
def test_invalid_live_measurements_produce_blocked_evidence(tmp_path, monkeypatch, value):
    collector = _module()
    monkeypatch.setattr(collector, "prom_query", lambda *_a, **_k: value)
    payload, passed = collector.collect(
        prom_url="https://prometheus.example.invalid",
        prom_token="prod-token",
        window="90d",
        mode="formal",
        release_id="release-a",
        raw_retention_days=120,
        out_path=tmp_path / "invalid.json",
    )
    assert passed is False
    assert collector.telemetry_admissible(payload) is False
    assert all(item["reading_numeric"] is None for item in payload["readings"].values())
    assert json.loads((tmp_path / "invalid.json").read_text())["all_pass"] is False


def test_prometheus_ambiguous_result_is_not_silently_truncated(monkeypatch):
    collector = _module()
    monkeypatch.setattr(
        collector,
        "_prom_get",
        lambda *_a: {
            "status": "success",
            "data": {"result": [{"value": [0, "1"]}, {"value": [0, "0"]}]},
        },
    )
    with pytest.raises(ValueError, match="ambiguous_series"):
        collector.prom_query("http://127.0.0.1:9090", "sum(up)")
