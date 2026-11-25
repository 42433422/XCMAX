"""Recalculate fixed performance gates from complete, source-matched measurements."""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
from datetime import datetime
from pathlib import Path

HTTP_BUDGETS = {95: 200, 99: 500}
EXPECTED_CASES = {
    ("im", 100),
    ("im", 1000),
    ("vector", 1000),
    ("vector", 10000),
    ("csv", 10000),
    ("csv", 100000),
}
FRONTEND_TESTS = {
    "home shell ready within XCAGI_SLA_READY_MS": (3000, 1),
    "/api/health responds within XCAGI_SLA_HEALTH_MS": (500, 1),
    "health P95/P99 derive from real HTTP samples": (500, 30),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def number(value, label: str, *, integer: bool = False) -> int | float:
    require(type(value) in (int, float), f"{label}: expected a number, not a flag or string")
    try:
        valid = math.isfinite(value) and value >= 0 and (not integer or int(value) == value)
    except OverflowError:
        valid = False
    require(valid, f"{label}: expected a finite nonnegative {'integer' if integer else 'number'}")
    return value


def mapping(value, label: str) -> dict:
    require(isinstance(value, dict), f"{label}: expected an object")
    return value


def sequence(value, label: str, count: int | None = None) -> list:
    require(isinstance(value, list), f"{label}: expected a list")
    require(count is None or len(value) == count, f"{label}: wrong observation count")
    return value


def exact_number(value, expected: int, label: str) -> None:
    require(number(value, label, integer=True) == expected, f"{label}: expected {expected}")


def timestamp(value, label: str) -> None:
    require(isinstance(value, str), f"{label}: missing observation time")
    require(datetime.fromisoformat(value).tzinfo is not None, f"{label}: missing time zone")


def equal_measurement(value, expected: float, label: str) -> None:
    require(
        math.isclose(number(value, label), expected, rel_tol=1e-9, abs_tol=1e-6),
        f"{label}: summary disagrees with raw observations",
    )


def validate_http(directory: Path, summary: dict) -> None:
    metrics = mapping(summary["metrics"], "k6 metrics")
    duration = metrics["http_req_duration"]["values"]
    for quantile, budget in HTTP_BUDGETS.items():
        exact_number(summary["budgets_ms"][f"p{quantile}"], budget, f"HTTP p{quantile} budget")
        require(
            number(duration[f"p({quantile})"], f"HTTP p{quantile}") < budget,
            f"HTTP p{quantile} exceeds its fixed budget",
        )
    exact_number(summary["workload"]["vus"], 5, "k6 VUs")
    require(summary["workload"]["duration"] == "30s", "k6 workload duration changed")
    count = number(metrics["http_reqs"]["values"]["count"], "HTTP count", integer=True)
    require(count >= 20, "Insufficient HTTP observations")
    for name, thresholds in {
        "http_req_duration": ("p(95)<200", "p(99)<500"),
        "http_reqs": ("count>=20",),
        "checks": ("rate==1",),
        "http_req_failed": ("rate==0",),
    }.items():
        reported = mapping(metrics[name]["thresholds"], f"{name} thresholds")
        require(
            all(
                mapping(reported.get(key, {}), "k6 threshold").get("ok") is True
                for key in thresholds
            ),
            f"{name}: fixed thresholds are missing or failed",
        )
    for metric in metrics.values():
        for result in mapping(
            mapping(metric, "k6 metric").get("thresholds", {}), "k6 thresholds"
        ).values():
            require(mapping(result, "k6 threshold").get("ok") is True, "A k6 threshold failed")
    exact_number(metrics["checks"]["values"]["rate"], 1, "HTTP check rate")
    exact_number(metrics["http_req_failed"]["values"]["rate"], 0, "HTTP failure rate")

    samples = {name: [] for name in ("http_req_duration", "http_reqs", "checks", "http_req_failed")}
    endpoints = set()
    with (directory / "k6-samples.jsonl").open() as handle:
        for line in handle:
            item = mapping(json.loads(line), "k6 raw record")
            name = item.get("metric")
            if item.get("type") != "Point" or name not in samples:
                continue
            data = mapping(item.get("data"), "k6 point data")
            timestamp(data.get("time"), "k6 point")
            samples[name].append(number(data.get("value"), f"Raw {name}"))
            if name == "http_req_duration":
                tags = mapping(data.get("tags"), "HTTP tags")
                require(tags.get("status") == "200", "Raw HTTP response failed")
                require(tags.get("endpoint") in ("/api/health", "/api/ping"), "Wrong HTTP endpoint")
                endpoints.add(tags["endpoint"])
    require(endpoints == {"/api/health", "/api/ping"}, "Missing HTTP endpoint observations")
    require(
        all(len(values) == count for values in samples.values()),
        "Raw HTTP observation counts disagree with the summary",
    )
    for name, expected in (("http_reqs", 1), ("checks", 1), ("http_req_failed", 0)):
        require(all(value == expected for value in samples[name]), f"Raw {name} failed")
    ordered = sorted(samples["http_req_duration"])
    for quantile, budget in HTTP_BUDGETS.items():
        # k6 TrendSink.P uses linear interpolation at q * (N - 1), not nearest rank.
        position = quantile / 100 * (len(ordered) - 1)
        lower, upper = math.floor(position), math.ceil(position)
        observed = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        require(observed < budget, f"Raw HTTP p{quantile} exceeds its fixed budget")
        equal_measurement(duration[f"p({quantile})"], observed, f"HTTP p{quantile}")


def validate_business(business: dict) -> None:
    cases = sequence(business.get("cases"), "Business cases", len(EXPECTED_CASES))
    require(business.get("passed") is True, "Business regressions failed")
    observed = set()
    for case in cases:
        case = mapping(case, "Business case")
        name = case.get("case")
        size = number(case.get("size"), "Business size", integer=True)
        require(
            (name, size) in EXPECTED_CASES and (name, size) not in observed,
            "Unexpected or duplicate business case",
        )
        observed.add((name, size))
        require(case.get("passed") is True and not case.get("error"), "Business case failed")
        result = mapping(case.get("result"), f"{name} result")
        require(not result.get("error"), f"{name}: failed measurement")
        if name in ("im", "vector"):
            key = "conversations" if name == "im" else "chunks"
            exact_number(result[key], size, f"{name} fixture size")
            samples = sequence(result.get("samples"), f"{name} samples", 3)
            if name == "im":
                exact_number(result["messages"], size * 10, "IM messages")
                exact_number(result["page_size"], 50, "IM page size")
                exact_number(result["query_budget"], 6, "IM query budget")
            else:
                exact_number(result["dimensions"], 256, "Vector dimensions")
                exact_number(result["top_k"], 5, "Vector top_k")
                exact_number(
                    result["python_peak_budget_bytes"], 10 * 1024**2, "Vector memory budget"
                )
            for sample in samples:
                sample = mapping(sample, f"{name} sample")
                elapsed_key = "elapsed_ms" if name == "im" else "elapsed_ms_with_tracemalloc"
                number(sample[elapsed_key], f"{name} elapsed milliseconds")
                key, budget = (
                    ("sql_statements", 6) if name == "im" else ("python_peak_bytes", 10 * 1024**2)
                )
                require(
                    0 < number(sample[key], f"{name} {key}", integer=True) <= budget,
                    f"{name}: measured work or memory exceeds its fixed budget",
                )
        else:
            exact_number(result["rows"], size, "CSV rows")
            exact_number(result["columns"], 12, "CSV columns")
            require(
                number(result["file_bytes"], "CSV file bytes", integer=True) > 0,
                "Empty CSV fixture",
            )
            exact_number(result["rss_growth_budget_bytes"], 64 * 1024**2, "CSV RSS budget")
            exact_number(result["sampling_interval_ms"], 5, "CSV sampling interval")
            before = number(result["rss_before_bytes"], "CSV initial RSS", integer=True)
            peak = number(result["rss_peak_bytes"], "CSV peak RSS", integer=True)
            growth = number(result["rss_growth_bytes"], "CSV RSS growth", integer=True)
            require(
                before > 0 and peak >= before and growth == peak - before,
                "CSV RSS growth disagrees with measured initial and peak RSS",
            )
            require(growth <= 64 * 1024**2, "CSV RSS exceeds its fixed budget")
            parsed = number(result["parse_elapsed_ms"], "CSV parse milliseconds")
            traversed = number(result["traversal_elapsed_ms"], "CSV traversal milliseconds")
            total = number(result["total_elapsed_ms_including_close"], "CSV total milliseconds")
            require(total + 1e-6 >= parsed + traversed, "CSV total omits parsing or traversal")
    require(observed == EXPECTED_CASES, "Business regressions are incomplete")


def measurement(attachment: dict, directory: Path) -> dict:
    require(attachment.get("contentType") == "application/json", "Wrong measurement content type")
    if "body" in attachment:
        # Playwright JSONReporter serializes Buffer bodies as base64 strings.
        require(isinstance(attachment["body"], str), "Invalid measurement attachment body")
        content = base64.b64decode(attachment["body"], validate=True).decode("utf-8")
    else:
        require(isinstance(attachment.get("path"), str), "Missing measurement attachment")
        path = Path(attachment["path"])
        roots = (directory.resolve(), (directory.parent / "frontend/test-results").resolve())
        candidates = (
            (path,)
            if path.is_absolute()
            else (directory / path, directory.parent / "frontend" / path)
        )
        paths = [
            candidate.resolve()
            for candidate in candidates
            if any(candidate.resolve().is_relative_to(root) for root in roots)
            and candidate.is_file()
        ]
        require(bool(paths), "Measurement path is missing or outside uploaded artifact directories")
        content = paths[0].read_text(encoding="utf-8")
    return mapping(json.loads(content), "Frontend measurements")


def specifications(suites):
    for suite in sequence(suites, "Frontend suites"):
        suite = mapping(suite, "Frontend suite")
        yield from sequence(suite.get("specs"), "Frontend specs")
        yield from specifications(suite.get("suites", []))


def validate_frontend(directory: Path, frontend: dict, source_sha: str) -> None:
    metadata = mapping(
        mapping(frontend["config"], "Frontend config")["metadata"], "Frontend metadata"
    )
    require(
        metadata.get("source_sha") == source_sha,
        "Frontend evidence has the wrong source identity",
    )
    stats = mapping(frontend["stats"], "Frontend stats")
    for key, count in (("expected", 3), ("unexpected", 0), ("skipped", 0), ("flaky", 0)):
        exact_number(stats[key], count, f"Frontend {key} count")
    timestamp(stats.get("startTime"), "Frontend run")
    number(stats["duration"], "Frontend duration")
    sequence(frontend.get("errors"), "Frontend errors", 0)
    specs = list(specifications(frontend.get("suites")))
    require(len(specs) == len(FRONTEND_TESTS), "Frontend tests are missing or duplicated")
    seen = set()
    for spec in specs:
        spec = mapping(spec, "Frontend spec")
        title = spec.get("title")
        require(title in FRONTEND_TESTS and title not in seen, "Wrong or duplicate frontend test")
        seen.add(title)
        require(
            spec.get("ok") is True and Path(spec.get("file", "")).name == "sla-perf.spec.ts",
            "Frontend performance spec failed or has the wrong source file",
        )
        test = mapping(sequence(spec.get("tests"), "Frontend tests", 1)[0], "Frontend test")
        require(
            test.get("projectName") == "chromium"
            and test.get("expectedStatus") == "passed"
            and test.get("status") == "expected",
            "Frontend test did not pass as expected",
        )
        result = mapping(
            sequence(test.get("results"), "Frontend attempts", 1)[0], "Frontend result"
        )
        require(
            result.get("status") == "passed" and not result.get("error"), "Frontend attempt failed"
        )
        sequence(result.get("errors"), "Frontend attempt errors", 0)
        exact_number(result["retry"], 0, "Frontend retry")
        number(result["duration"], "Frontend test duration")
        timestamp(result.get("startTime"), "Frontend test")
        attachments = [
            mapping(item, "Frontend attachment")
            for item in sequence(result.get("attachments"), "Attachments")
        ]
        records = [item for item in attachments if item.get("name") == "performance-measurements"]
        require(len(records) == 1, "Frontend measurements are missing or duplicated")
        data = measurement(records[0], directory)
        require(
            data.get("source_sha") == source_sha,
            "Frontend measurements have the wrong source identity",
        )
        if title == "home shell ready within XCAGI_SLA_READY_MS":
            require(
                data.get("build_source_sha") == source_sha,
                "Measured frontend build has a missing or wrong source identity",
            )
        budget, sample_count = FRONTEND_TESTS[title]
        exact_number(data["budget_ms"], budget, f"{title} budget")
        samples = [
            number(value, f"{title} sample")
            for value in sequence(data.get("samples_ms"), title, sample_count)
        ]
        require(
            all(value <= budget for value in samples),
            f"{title}: measured latency exceeds its fixed budget",
        )
        if sample_count == 30:
            ordered = sorted(samples)
            for quantile in (95, 99):
                equal_measurement(
                    data[f"p{quantile}_ms"],
                    ordered[math.ceil(quantile / 100 * sample_count) - 1],
                    f"Frontend p{quantile}",
                )


def validate(directory: Path, source_sha: str) -> None:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_sha)), "An exact source commit is required")
    summary, business, frontend = [
        mapping(json.loads((directory / name).read_text()), name)
        for name in ("k6-summary.json", "business.json", "frontend.json")
    ]
    for name, report in (("k6", summary), ("business", business)):
        require(report.get("source_sha") == source_sha, f"{name}: wrong source identity")
    validate_http(directory, summary)
    validate_business(business)
    validate_frontend(directory, frontend, source_sha)
    for name in ("k6-version.txt", "node-version.txt"):
        require(bool((directory / name).read_text().strip()), f"Missing runtime identity: {name}")


def validate_chat_soak(directory: Path, source_sha: str, days: int = 7) -> None:
    """Validate native k6 evidence for synthetic staging chat only, never production SLO."""
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_sha)), "An exact source commit is required")
    require(type(days) is int and days >= 7, "A seven-day acceptance needs at least seven days")
    summary = mapping(json.loads((directory / "k6-7d-summary.json").read_text()), "chat summary")
    require(summary.get("source_sha") == source_sha, "Chat evidence has the wrong source identity")
    require(summary.get("environment") == "staging", "Chat acceptance requires staging evidence")
    require(summary.get("test_profile") == "chat-durable-turn/v1", "Wrong chat workload profile")
    require(
        summary.get("business_reconciliation") is False,
        "Synthetic traffic cannot certify business reconciliation",
    )
    timestamp(summary.get("completed_at"), "Chat completion")
    workload = mapping(summary.get("workload"), "Chat workload")
    require(
        workload.get("executor") == "constant-arrival-rate"
        and workload.get("rate") == 30
        and workload.get("timeUnit") in {"1m", "1m0s"},
        "Chat arrival workload changed",
    )
    duration = number(summary["state"]["testRunDurationMs"], "Actual k6 duration")
    required_ms = days * 86400 * 1000
    metrics = mapping(summary.get("metrics"), "Chat metrics")
    fixed = {
        "checks": "rate==1",
        "iterations": "count>0",
        "dropped_iterations": "count==0",
        "chat_turns_verified": "count>0",
        "http_req_failed": "rate<0.01",
        "http_req_duration": "p(95)<15000",
    }
    for name, threshold in fixed.items():
        require(
            metrics[name]["thresholds"][threshold].get("ok") is True,
            f"{name}: required native k6 threshold is missing or failed",
        )
    for metric in metrics.values():
        for outcome in mapping(metric.get("thresholds", {}), "Chat thresholds").values():
            require(mapping(outcome, "Chat threshold").get("ok") is True, "A chat threshold failed")
    iterations = number(metrics["iterations"]["values"]["count"], "Chat iterations", integer=True)
    exact_number(
        metrics["chat_turns_verified"]["values"]["count"], iterations, "Verified original turns"
    )
    exact_number(metrics["dropped_iterations"]["values"]["count"], 0, "Dropped chat work")
    exact_number(metrics["checks"]["values"]["rate"], 1, "Chat check rate")
    exact_number(metrics["http_req_failed"]["values"]["rate"], 0, "Chat HTTP failure rate")
    counts = dict.fromkeys(
        ("http_reqs", "checks", "http_req_failed", "chat_turns_verified", "http_req_duration"), 0
    )
    latencies = []
    checks, endpoints = set(), set()
    first = last = None
    with (directory / "k6-7d-samples.jsonl").open() as handle:
        for line in handle:
            row = mapping(json.loads(line), "Chat raw record")
            name = row.get("metric")
            if row.get("type") != "Point" or name not in counts:
                continue
            data = mapping(row.get("data"), "Chat raw data")
            timestamp(data.get("time"), "Chat raw observation")
            observed = datetime.fromisoformat(data["time"])
            first = min(first, observed) if first else observed
            last = max(last, observed) if last else observed
            tags = mapping(data.get("tags"), "Chat raw tags")
            require(
                tags.get("source_sha") == source_sha and tags.get("environment") == "staging",
                "Chat raw sample identity mismatch",
            )
            if name == "http_req_duration":
                latencies.append(number(data.get("value"), "Raw chat HTTP duration"))
            else:
                exact_number(
                    data.get("value"), 0 if name == "http_req_failed" else 1, f"Raw {name}"
                )
            counts[name] += 1
            if name == "checks":
                checks.add(tags.get("check"))
            elif name == "http_reqs":
                require(tags.get("status") == "200", "Chat raw HTTP status failed")
                endpoints.add(tags.get("name"))
    require(first is not None and last is not None, "Chat raw observations are missing")
    require(
        checks
        == {
            "healthy tested build",
            "login ok",
            "chat stream HTTP contract",
            "original durable turn completed",
        }
        and endpoints == {"health", "login", "chat_stream", "chat_readback"},
        "Chat raw observations omit a required route or assertion",
    )
    for name, count in counts.items():
        exact_number(
            count,
            iterations if name == "chat_turns_verified" else iterations * 4,
            f"Raw {name} count",
        )
    exact_number(metrics["http_reqs"]["values"]["count"], counts["http_reqs"], "Chat HTTP count")
    exact_number(metrics["checks"]["values"]["passes"], counts["checks"], "Chat checks passed")
    exact_number(metrics["checks"]["values"]["fails"], 0, "Chat checks failed")
    require(bool(latencies), "Chat latency observations are missing")
    latencies.sort()
    position = 0.95 * (len(latencies) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    p95 = latencies[lower] + (latencies[upper] - latencies[lower]) * (position - lower)
    require(p95 < 15000, "Raw chat latency exceeds its fixed budget")
    equal_measurement(metrics["http_req_duration"]["values"]["p(95)"], p95, "Chat HTTP p95")
    require(duration >= required_ms, "Actual k6 observation is shorter than the acceptance window")
    require(iterations >= days * 86400 / 2, "Chat workload does not cover the observation window")
    require(
        (last - first).total_seconds() * 1000 >= required_ms - 5000,
        "Chat raw samples do not span the acceptance window",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--chat-soak", action="store_true", help="Validate staging chat JSONL and native k6 summary"
    )
    parser.add_argument("--window-days", type=int, default=7)
    args = parser.parse_args()
    try:
        if args.chat_soak:
            validate_chat_soak(args.directory, args.source_sha, args.window_days)
        else:
            validate(args.directory, args.source_sha)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"Performance evidence rejected: {error}")
        return 1
    print("Performance evidence complete; fixed budgets and raw measurements passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
