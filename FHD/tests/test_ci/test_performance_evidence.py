"""Negative controls against missing, contradictory or over-budget measurements."""

from __future__ import annotations

import base64
import importlib.util
import json
from fnmatch import fnmatchcase
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

FHD = Path(__file__).resolve().parents[2]
SOURCE_SHA = "a" * 40
START_TIME = "2026-10-29T12:00:00.123456789Z"
SPEC_PATH = "suites.0.suites.0.specs"
TEST_PATH = f"{SPEC_PATH}.0.tests.0"
RESULT_PATH = f"{TEST_PATH}.results.0"
REJECTED = (OSError, KeyError, TypeError, ValueError)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load(FHD / "scripts/loadtest/validate_evidence.py", "performance_evidence_validator")


def write_json(path, data):
    path.write_text(json.dumps(data))


def attachment(report, index=0):
    return report["suites"][0]["suites"][0]["specs"][index]["tests"][0]["results"][0][
        "attachments"
    ][0]


def encode(data):
    return base64.b64encode(json.dumps(data).encode()).decode()


def business_result(case, size):
    if case == "im":
        return {
            "conversations": size,
            "messages": size * 10,
            "page_size": 50,
            "query_budget": 6,
            "samples": [{"elapsed_ms": 30.5, "sql_statements": 5} for _ in range(3)],
        }
    if case == "vector":
        return {
            "chunks": size,
            "dimensions": 256,
            "top_k": 5,
            "python_peak_budget_bytes": 10 * 1024**2,
            "samples": [
                {"elapsed_ms_with_tracemalloc": 300.5, "python_peak_bytes": 256000}
                for _ in range(3)
            ],
        }
    return {
        "rows": size,
        "columns": 12,
        "file_bytes": size * 120,
        "parse_elapsed_ms": 1000.5,
        "traversal_elapsed_ms": 150,
        "total_elapsed_ms_including_close": 1151,
        "rss_before_bytes": 64 * 1024**2,
        "rss_peak_bytes": 66 * 1024**2,
        "rss_growth_bytes": 2 * 1024**2,
        "rss_growth_budget_bytes": 64 * 1024**2,
        "sampling_interval_ms": 5,
    }


@pytest.fixture
def evidence(tmp_path):
    summary = {
        "source_sha": SOURCE_SHA,
        "budgets_ms": {"p95": 200, "p99": 500},
        "workload": {"vus": 5, "duration": "30s"},
        "metrics": {
            "http_req_duration": {
                # k6 linear interpolation of the raw samples 10, 11, ..., 39.
                "values": {"p(95)": 37.55, "p(99)": 38.71},
                "thresholds": {"p(95)<200": {"ok": True}, "p(99)<500": {"ok": True}},
            },
            "http_reqs": {"values": {"count": 30}, "thresholds": {"count>=20": {"ok": True}}},
            "checks": {"values": {"rate": 1}, "thresholds": {"rate==1": {"ok": True}}},
            "http_req_failed": {"values": {"rate": 0}, "thresholds": {"rate==0": {"ok": True}}},
        },
    }
    business = {
        "source_sha": SOURCE_SHA,
        "passed": True,
        "cases": [
            {"case": case, "size": rows, "passed": True, "result": business_result(case, rows)}
            for case, rows in (
                ("im", 100),
                ("im", 1000),
                ("vector", 1000),
                ("vector", 10000),
                ("csv", 10000),
                ("csv", 100000),
            )
        ],
    }
    specs = []
    for index, (title, data) in enumerate(
        (
            (
                "home shell ready within XCAGI_SLA_READY_MS",
                {"samples_ms": [1000.5], "budget_ms": 3000, "build_source_sha": SOURCE_SHA},
            ),
            (
                "/api/health responds within XCAGI_SLA_HEALTH_MS",
                {"samples_ms": [20.5], "budget_ms": 500},
            ),
            (
                "health P95/P99 derive from real HTTP samples",
                {"samples_ms": list(range(10, 40)), "p95_ms": 38, "p99_ms": 39, "budget_ms": 500},
            ),
        )
    ):
        specs.append(
            {
                "title": title,
                "ok": True,
                "id": f"perf-{index}",
                "file": "sla-perf.spec.ts",
                "line": index + 1,
                "column": 1,
                "tags": [],
                "tests": [
                    {
                        "timeout": 45000,
                        "annotations": [],
                        "projectId": "chromium",
                        "projectName": "chromium",
                        "expectedStatus": "passed",
                        "status": "expected",
                        "results": [
                            {
                                "status": "passed",
                                "duration": 1500,
                                "retry": 0,
                                "startTime": START_TIME,
                                "workerIndex": 0,
                                "parallelIndex": 0,
                                "errors": [],
                                "stdout": [],
                                "stderr": [],
                                "attachments": [
                                    {
                                        "name": "performance-measurements",
                                        "contentType": "application/json",
                                        "body": encode(
                                            {
                                                "source_sha": SOURCE_SHA,
                                                "scope": "synthetic validator fixture",
                                                **data,
                                            }
                                        ),
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    frontend = {
        "config": {"metadata": {"source_sha": SOURCE_SHA}},
        "stats": {
            "expected": 3,
            "unexpected": 0,
            "skipped": 0,
            "flaky": 0,
            "startTime": START_TIME,
            "duration": 4500,
        },
        "errors": [],
        "suites": [
            {
                "title": "sla-perf.spec.ts",
                "specs": [],
                "suites": [
                    {"title": "Measured performance budgets", "specs": specs},
                ],
            }
        ],
    }
    for name, payload in (
        ("k6-summary.json", summary),
        ("business.json", business),
        ("frontend.json", frontend),
    ):
        write_json(tmp_path / name, payload)
    points = [{"type": "Metric", "metric": "http_req_duration", "data": {"type": "trend"}}]
    for index, elapsed in enumerate(range(10, 40)):
        for metric, value in (
            ("http_req_duration", elapsed),
            ("http_reqs", 1),
            ("checks", 1),
            ("http_req_failed", 0),
        ):
            points.append(
                {
                    "type": "Point",
                    "metric": metric,
                    "data": {
                        "value": value,
                        "time": START_TIME,
                        "tags": {
                            "status": "200",
                            "endpoint": "/api/health" if index % 2 else "/api/ping",
                        },
                    },
                }
            )
    (tmp_path / "k6-samples.jsonl").write_text("\n".join(map(json.dumps, points)))
    (tmp_path / "k6-version.txt").write_text("k6 v0.54.0")
    (tmp_path / "node-version.txt").write_text("v24")
    return tmp_path


def test_complete_evidence_is_accepted(evidence):
    validator.validate(evidence, SOURCE_SHA)


def change(data, path, value):
    parts = path.split(".")
    for key in parts[:-1]:
        data = data[int(key)] if isinstance(data, list) else data[key]
    data[int(parts[-1]) if isinstance(data, list) else parts[-1]] = value


@pytest.mark.parametrize(
    ("filename", "path", "value"),
    [
        ("k6-summary.json", "source_sha", "b" * 40),
        ("k6-summary.json", "budgets_ms.p95", float("inf")),
        ("k6-summary.json", "budgets_ms.p99", 10000),
        ("k6-summary.json", "metrics.http_req_duration.values.p(95)", 200),
        ("k6-summary.json", "metrics.http_req_duration.values.p(99)", 501),
        ("k6-summary.json", "metrics.http_req_duration.values.p(99)", 100),
        ("k6-summary.json", "metrics.http_req_duration.thresholds", {}),
        ("k6-summary.json", "metrics.http_req_duration.thresholds.p(99)<500.ok", False),
        ("k6-summary.json", "metrics.http_reqs.values.count", 31),
        ("k6-summary.json", "metrics.http_reqs.values.count", 19),
        ("k6-summary.json", "metrics.http_reqs.values.count", float("nan")),
        ("k6-summary.json", "metrics.checks.values.rate", True),
        ("k6-summary.json", "metrics.http_req_failed.values.rate", 0.1),
        ("k6-summary.json", "workload.vus", 1),
        ("k6-summary.json", "workload.duration", "1s"),
        ("business.json", "source_sha", "b" * 40),
        ("business.json", "passed", False),
        ("business.json", "cases", []),
        ("business.json", "cases.0.passed", False),
        ("business.json", "cases.0.result", {}),
        ("business.json", "cases.0.size", 10),
        ("business.json", "cases.0.result.conversations", 10),
        ("business.json", "cases.0.result.messages", 100),
        ("business.json", "cases.0.result.page_size", 1),
        ("business.json", "cases.0.result.query_budget", 99999),
        ("business.json", "cases.0.result.samples", []),
        ("business.json", "cases.0.result.samples.1.sql_statements", 7),
        ("business.json", "cases.0.result.samples.1.sql_statements", 0),
        ("business.json", "cases.0.result.samples.1.sql_statements", 5.5),
        ("business.json", "cases.2.result.python_peak_budget_bytes", 10**12),
        ("business.json", "cases.2.result.dimensions", 8),
        ("business.json", "cases.2.result.top_k", 1),
        ("business.json", "cases.2.result.chunks", 10),
        ("business.json", "cases.2.result.samples.2.python_peak_bytes", 10 * 1024**2 + 1),
        ("business.json", "cases.4.result.rss_growth_budget_bytes", 10**12),
        ("business.json", "cases.4.result.rows", 10),
        ("business.json", "cases.4.result.columns", 1),
        ("business.json", "cases.4.result.file_bytes", 0),
        ("business.json", "cases.4.result.sampling_interval_ms", 500),
        ("business.json", "cases.4.result.rss_growth_bytes", 0),
        ("business.json", "cases.4.result.rss_peak_bytes", 130 * 1024**2),
        ("business.json", "cases.4.result.total_elapsed_ms_including_close", 1000.5),
        ("frontend.json", "config.metadata.source_sha", "b" * 40),
        ("frontend.json", "stats.skipped", 1),
        ("frontend.json", "stats.expected", 4),
        ("frontend.json", "stats.unexpected", False),
        ("frontend.json", "suites", []),
        ("frontend.json", f"{SPEC_PATH}.0.title", "unrelated test"),
        ("frontend.json", f"{SPEC_PATH}.0.file", "unrelated.spec.ts"),
        ("frontend.json", f"{SPEC_PATH}.0.ok", False),
        ("frontend.json", f"{TEST_PATH}.projectName", "webkit"),
        ("frontend.json", f"{TEST_PATH}.expectedStatus", "failed"),
        ("frontend.json", f"{TEST_PATH}.status", "flaky"),
        ("frontend.json", f"{TEST_PATH}.results", []),
        ("frontend.json", f"{RESULT_PATH}.status", "skipped"),
        ("frontend.json", f"{RESULT_PATH}.retry", 1),
        ("frontend.json", f"{RESULT_PATH}.errors", [{"message": "failed"}]),
        ("frontend.json", f"{RESULT_PATH}.attachments", []),
        ("frontend.json", f"{RESULT_PATH}.attachments.0.body", '{"unencoded": "JSON"}'),
        ("frontend.json", f"{RESULT_PATH}.attachments.0.contentType", "text/plain"),
    ],
)
def test_incomplete_or_over_budget_evidence_fails(evidence, filename, path, value):
    report = json.loads((evidence / filename).read_text())
    change(report, path, value)
    write_json(evidence / filename, report)
    with pytest.raises(REJECTED):
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "30", True])
@pytest.mark.parametrize(
    ("filename", "path"),
    [
        ("k6-summary.json", "metrics.http_req_duration.values.p(95)"),
        ("business.json", "cases.0.result.samples.0.elapsed_ms"),
        ("business.json", "cases.2.result.samples.0.python_peak_bytes"),
        ("business.json", "cases.4.result.traversal_elapsed_ms"),
    ],
)
def test_measurements_require_finite_nonnegative_numbers(evidence, filename, path, value):
    report = json.loads((evidence / filename).read_text())
    change(report, path, value)
    write_json(evidence / filename, report)
    with pytest.raises(REJECTED):
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize(
    "failure",
    [
        "empty",
        "no_data",
        "no_value",
        "nonfinite",
        "boolean",
        "string",
        "negative",
        "slow",
        "wrong_status",
        "missing_endpoint",
        "one_endpoint",
        "wrong_time",
        "missing_check",
        "failed_check",
        "failed_request",
        "wrong_request_count",
        "missing_point",
    ],
)
def test_raw_http_evidence_cannot_disagree_with_a_passing_summary(evidence, failure):
    path = evidence / "k6-samples.jsonl"
    points = [json.loads(line) for line in path.read_text().splitlines()]
    duration = points[1]
    if failure == "empty":
        points = []
    elif failure == "no_data":
        duration.pop("data")
    elif failure == "no_value":
        duration["data"].pop("value")
    elif failure in ("nonfinite", "boolean", "string", "negative", "slow"):
        duration["data"]["value"] = {
            "nonfinite": float("nan"),
            "boolean": True,
            "string": "100",
            "negative": -1,
            "slow": 1000,
        }[failure]
    elif failure == "wrong_status":
        duration["data"]["tags"]["status"] = "500"
    elif failure == "missing_endpoint":
        duration["data"]["tags"].pop("endpoint")
    elif failure == "one_endpoint":
        for point in points[1:]:
            point["data"]["tags"]["endpoint"] = "/api/health"
    elif failure == "wrong_time":
        duration["data"]["time"] = "2026-10-29"
    elif failure == "missing_check":
        points = [point for point in points if point["metric"] != "checks"]
    elif failure == "failed_check":
        points[3]["data"]["value"] = 0
    elif failure == "failed_request":
        points[4]["data"]["value"] = 1
    elif failure == "wrong_request_count":
        points[2]["data"]["value"] = 2
    elif failure == "missing_point":
        points.pop()
    path.write_text("\n".join(map(json.dumps, points)))
    with pytest.raises(REJECTED):
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize(
    ("index", "key", "value"),
    [
        (0, "source_sha", "b" * 40),
        (0, "budget_ms", 30000),
        (0, "samples_ms", [3000.1]),
        (0, "samples_ms", [float("nan")]),
        (0, "samples_ms", [True]),
        (0, "samples_ms", ["10"]),
        (0, "samples_ms", []),
        (1, "budget_ms", float("inf")),
        (1, "samples_ms", [500.1]),
        (2, "samples_ms", list(range(29))),
        (2, "p95_ms", 10),
        (2, "p99_ms", 10),
        (2, "p99_ms", float("nan")),
    ],
)
def test_frontend_attachment_is_recomputed(evidence, index, key, value):
    path = evidence / "frontend.json"
    report = json.loads(path.read_text())
    record = attachment(report, index)
    data = json.loads(base64.b64decode(record["body"]))
    data[key] = value
    record["body"] = encode(data)
    write_json(path, report)
    with pytest.raises(REJECTED):
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize("build_sha", [None, "b" * 40], ids=["missing", "wrong"])
def test_frontend_requires_the_measured_build_identity(evidence, build_sha):
    path = evidence / "frontend.json"
    report = json.loads(path.read_text())
    record = attachment(report)
    data = json.loads(base64.b64decode(record["body"]))
    data.pop("build_source_sha")
    if build_sha is not None:
        data["build_source_sha"] = build_sha
    record["body"] = encode(data)
    write_json(path, report)
    with pytest.raises(ValueError, match="Measured frontend build"):
        validator.validate(evidence, SOURCE_SHA)


def test_consistent_but_over_budget_csv_rss_is_rejected(evidence):
    path = evidence / "business.json"
    report = json.loads(path.read_text())
    result = report["cases"][5]["result"]
    result["rss_growth_bytes"] = 64 * 1024**2 + 1
    result["rss_peak_bytes"] = result["rss_before_bytes"] + result["rss_growth_bytes"]
    write_json(path, report)
    with pytest.raises(ValueError, match="CSV RSS exceeds"):
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize("kind", ["business_case", "ui_spec", "ui_attempt", "ui_attachment"])
def test_duplicate_evidence_does_not_replace_missing_measurements(evidence, kind):
    filename = "business.json" if kind == "business_case" else "frontend.json"
    report = json.loads((evidence / filename).read_text())
    if kind == "business_case":
        report["cases"][-1] = report["cases"][0]
    else:
        specs = report["suites"][0]["suites"][0]["specs"]
        if kind == "ui_spec":
            specs[-1] = specs[0]
        elif kind == "ui_attempt":
            results = specs[0]["tests"][0]["results"]
            results.append(results[0])
        else:
            attachments = specs[0]["tests"][0]["results"][0]["attachments"]
            attachments.append(attachments[0])
    write_json(evidence / filename, report)
    with pytest.raises(ValueError):
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize("location", ["relative", "absolute", "frontend_output", "outside"])
def test_file_attachments_must_be_available_in_uploaded_artifacts(evidence, location):
    path = evidence / "frontend.json"
    report = json.loads(path.read_text())
    record = attachment(report)
    content = base64.b64decode(record.pop("body")).decode()
    output = evidence / "attachments" / "measurements.json"
    if location == "frontend_output":
        output = evidence.parent / "frontend/test-results" / evidence.name / "measurements.json"
    elif location == "outside":
        output = evidence.parent / f"{evidence.name}-outside.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    record["path"] = str(output.relative_to(evidence)) if location == "relative" else str(output)
    write_json(path, report)
    if location == "outside":
        with pytest.raises(ValueError, match="outside uploaded artifact"):
            validator.validate(evidence, SOURCE_SHA)
    else:
        validator.validate(evidence, SOURCE_SHA)


@pytest.mark.parametrize(
    "filename",
    [
        "k6-summary.json",
        "k6-samples.jsonl",
        "business.json",
        "frontend.json",
        "k6-version.txt",
        "node-version.txt",
    ],
)
def test_missing_required_artifact_is_rejected(evidence, filename):
    (evidence / filename).unlink()
    with pytest.raises(REJECTED):
        validator.validate(evidence, SOURCE_SHA)


def test_exact_frontend_budget_is_allowed(evidence):
    path = evidence / "frontend.json"
    report = json.loads(path.read_text())
    for index, (budget, count) in enumerate(((3000, 1), (500, 1), (500, 30))):
        record = attachment(report, index)
        data = json.loads(base64.b64decode(record["body"]))
        data["samples_ms"] = [budget] * count
        if count == 30:
            data.update(p95_ms=budget, p99_ms=budget)
        record["body"] = encode(data)
    write_json(path, report)
    validator.validate(evidence, SOURCE_SHA)


def test_health_probe_does_not_multiply_its_budget(monkeypatch):
    probe = load(FHD / "tests/test_sla_health_probe.py", "strict_health_probe")
    clock = iter([0, 0.501])
    monkeypatch.setattr(probe.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(probe, "BUDGET_MS", 500)
    client = SimpleNamespace(get=lambda _: SimpleNamespace(status_code=200))
    assert probe._probe_health(client)["within_budget"] is False


def test_published_workflow_requires_the_real_artifact_paths():
    workflow = yaml.safe_load(
        (FHD.parent / ".github/workflows/fhd-performance-smoke.yml").read_text()
    )
    triggers = workflow.get("on", workflow.get(True))
    paths = triggers["pull_request"]["paths"]
    for source in (
        "FHD/.github/workflows/performance-smoke.yml",
        ".github/workflows/fhd-performance-smoke.yml",
    ):
        assert any(fnmatchcase(source, pattern) for pattern in paths), source
    steps = workflow["jobs"]["smoke"]["steps"]
    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact")
    )
    assert upload["with"]["if-no-files-found"] == "error"
    assert "FHD/performance-results/" in upload["with"]["path"]
    verify = next(step for step in steps if "validate_evidence.py" in step.get("run", ""))
    assert verify["if"] == "always()"
    assert not verify.get("continue-on-error", False)
