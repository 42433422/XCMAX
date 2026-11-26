#!/usr/bin/env python3
"""Compare paired Playwright browser measurements; never fabricate samples.

Raw results must be produced by the same CI job and the same test fixture.
This is a web-renderer regression probe, not Electron/Flutter device evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


SCENARIOS = {
    "local synthetic API, cold and warm separated": "route",
    "timed synthetic SSE, actual parser and Vue DOM": "stream",
}
METRICS = (
    ("route", "settings_click", "p95_ms", 200.0, "Warm click to settings P95"),
    ("route", "history_back", "p95_ms", 200.0, "Warm history back P95"),
    ("stream", "idle_frame_intervals", "p95_ms", None, "Idle rAF interval P95"),
    ("stream", "frame_intervals", "p95_ms", 1000.0 / 60.0, "Stream rAF interval P95"),
    ("stream", None, "first_token_to_visible_frame_ms", None, "First token to visible frame"),
    ("stream", None, "input_to_request_ms", None, "Input click to stream request"),
)


def percentile(samples: list[float], percent: int) -> float:
    if len(samples) < 20 or not all(isinstance(x, (int, float))
                                   and math.isfinite(x) and x >= 0 for x in samples):
        raise ValueError("at least 20 valid nonnegative browser samples required")
    ordered = sorted(samples)
    return ordered[math.ceil(percent * len(ordered) / 100) - 1]


def inspect_distribution(report: dict, field: str, count: int | None = None) -> None:
    data = report.get(field) or {}
    samples = data.get("samples_ms") or []
    if data.get("count") != len(samples) or (count is not None and len(samples) != count):
        raise ValueError(f"{field}: measured sample count mismatch")
    for percent in (50, 95):
        measured = data.get(f"p{percent}_ms")
        if (not isinstance(measured, (int, float)) or not math.isfinite(measured)
                or abs(percentile(samples, percent) - measured) > .001):
            raise ValueError(f"{field}: reported P{percent} doesn't match samples")


def inspect_report(report: dict, expected_sha: str) -> None:
    if report.get("source_sha") != expected_sha:
        raise ValueError("source SHA mismatch; stale or wrong build")
    if report.get("scope") != ("production Chromium renderer, synthetic desktop bridge/account; "
                               "not native Electron or Flutter"):
        raise ValueError("missing synthetic-test provenance")
    if report.get("scenario") not in SCENARIOS:
        raise ValueError("unknown scenario")
    if report.get("browser") != "chromium":
        raise ValueError("browser does not match fixed fixture")
    if report.get("scenario") == "local synthetic API, cold and warm separated":
        for field in ("settings_click", "history_back"):
            inspect_distribution(report, field, count=30)
    else:
        inspect_distribution(report, "idle_frame_intervals", count=60)
        inspect_distribution(report, "frame_intervals")
        raw = report.get("raw") or {}
        if raw.get("tokens") != 242 or not (
            0 < raw.get("request", 0) < raw.get("firstEnqueue", 0)
            <= raw.get("firstPaint", 0) < raw.get("done", 0)
            <= raw.get("finalPaint", 0)
        ):
            raise ValueError("synthetic SSE did not render both markers before completion")
        if report.get("network_ms") is not None or report.get("model_inference_ms") is not None:
            raise ValueError("synthetic fixture cannot claim network or inference timings")
        for field in ("first_token_to_visible_frame_ms", "input_to_request_ms"):
            if not isinstance(report.get(field), (int, float)) or not math.isfinite(report[field]) or report[field] < 0:
                raise ValueError(f"invalid {field}")


def read_side(root: Path, side: str, sha: str) -> dict[str, dict]:
    folder = root / side / "results"
    files = sorted(folder.rglob("measurements.json"))
    if not files:
        raise ValueError(f"{side}: no raw measured results under {folder}")
    results = {}
    for filename in files:
        data = json.loads(filename.read_text(encoding="utf-8"))
        inspect_report(data, sha)
        key = SCENARIOS[data["scenario"]]
        if key in results:
            raise ValueError(f"{side}: duplicate scenario {key}")
        results[key] = data
    if set(results) != set(SCENARIOS.values()):
        raise ValueError(f"{side}: expected both route and stream results, got {sorted(results)}")
    return results


def metric_value(source: dict, metric: tuple) -> float:
    category, section, field, _, _ = metric
    value = source[category][section][field] if section else source[category][field]
    return float(value)


def compare(root: Path, baseline_sha: str, candidate_sha: str) -> dict:
    base = read_side(root, "baseline", baseline_sha)
    candidate = read_side(root, "candidate", candidate_sha)
    for scope in SCENARIOS.values():
        for prop in ("browser", "viewport", "node", "scope"):
            if base[scope].get(prop) != candidate[scope].get(prop):
                raise ValueError(f"non-comparable {scope}: {prop} differs")
    rows = []
    for metric in METRICS:
        _, _, _, target, label = metric
        before = metric_value(base, metric)
        after = metric_value(candidate, metric)
        rows.append({
            "metric": label, "baseline_ms": before, "candidate_ms": after,
            "delta_ms": round(after - before, 3),
            "delta_pct": round((after - before) * 100 / before, 2) if before > 0 else None,
            "target_ms": target,
            "candidate_meets_target": after <= target if target is not None else None,
        })
    return {
        "baseline_sha": baseline_sha, "candidate_sha": candidate_sha,
        "scope": "production Chromium, synthetic API and SSE, not native hardware",
        "network_and_model_inference": "not measured by synthetic fixture",
        "environment": {k: candidate["route"].get(k) for k in ("browser", "viewport", "node")},
        "measurements": rows,
        "all_navigation_targets_met": all(row["candidate_meets_target"] for row in rows[:2]),
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Frontend performance evidence (actual CI measurements)",
        "",
        f"Baseline: {report['baseline_sha']}",
        f"Candidate: {report['candidate_sha']}",
        "",
        "**Scope:** Chromium production renderer + synthetic account/SSE. "
        "Network/model inference, Electron native shell, Android/iOS hardware "
        "and long-run memory are NOT measured here.",
        "",
        "| Metric | Before (ms) | After (ms) | Delta (%) | Target (ms) | Met |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["measurements"]:
        target = row["target_ms"]
        success = row["candidate_meets_target"]
        target_label = f"{target:.2f}" if target is not None else "N/A"
        state_label = "yes" if success is True else "no" if success is False else "N/A"
        delta_label = str(row["delta_pct"]) if row["delta_pct"] is not None else "N/A"
        lines.append(f"| {row['metric']} | {row['baseline_ms']:.2f} | "
                     f"{row['candidate_ms']:.2f} | {delta_label} | "
                     f"{target_label} | {state_label} |")
    lines += ["", f"Navigation target met: **{report['all_navigation_targets_met']}**",
              "", "Data is read from immutable per-test sample JSON, not estimated.",
              "A failed/queued/cancelled CI run is not a performance pass."]
    return "\n".join(lines) + "\n"


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for side, sha, offset in (("baseline", "a" * 40, 0), ("candidate", "b" * 40, 5)):
            out = root / side / "results"
            for name, key in SCENARIOS.items():
                folder = out / key
                folder.mkdir(parents=True)
                frame = [16.0 + offset / 10] * 40
                route_samples = [80.0 + offset] * 30
                data = {
                    "source_sha": sha, "browser": "chromium",
                    "viewport": {"width": 1440, "height": 900}, "node": "test",
                    "scope": "production Chromium renderer, synthetic desktop bridge/account; not native Electron or Flutter",
                    "scenario": name,
                }
                if key == "route":
                    for field in ("settings_click", "history_back"):
                        data[field] = {"samples_ms": route_samples, "count": 30,
                                       "p50_ms": percentile(route_samples, 50),
                                       "p95_ms": percentile(route_samples, 95)}
                else:
                    idle = [16.6] * 60
                    data.update({
                        "frame_intervals": {"samples_ms": frame, "count": 40,
                                            "p50_ms": percentile(frame, 50), "p95_ms": percentile(frame, 95)},
                        "idle_frame_intervals": {"samples_ms": idle, "count": 60,
                                                 "p50_ms": percentile(idle, 50), "p95_ms": percentile(idle, 95)},
                        "raw": {"tokens": 242, "request": 1, "firstEnqueue": 2, "firstPaint": 3,
                                "done": 4, "finalPaint": 5},
                        "first_token_to_visible_frame_ms": 1, "input_to_request_ms": 1,
                        "network_ms": None, "model_inference_ms": None,
                    })
                (folder / "measurements.json").write_text(json.dumps(data), encoding="utf-8")
        report = compare(root, "a" * 40, "b" * 40)
        assert report["all_navigation_targets_met"]
        assert len(report["measurements"]) == 6
        assert "| N/A | N/A |" in render_markdown(report)
        bad = root / "candidate" / "results" / "route" / "measurements.json"
        raw = json.loads(bad.read_text(encoding="utf-8"))
        raw["settings_click"]["p95_ms"] = -1
        bad.write_text(json.dumps(raw), encoding="utf-8")
        try:
            compare(root, "a" * 40, "b" * 40)
        except ValueError:
            pass
        else:
            raise AssertionError("tampered measured percentile was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--baseline-sha")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("paired-performance comparator contract PASS")
        return 0
    if not (args.root and args.baseline_sha and args.candidate_sha):
        parser.error("root and both source SHAs required")
    try:
        report = compare(args.root, args.baseline_sha, args.candidate_sha)
        (args.root / "comparison.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.root / "comparison.md").write_text(render_markdown(report), encoding="utf-8")
        print(render_markdown(report))
        return 0 if report["all_navigation_targets_met"] else 2
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("PERFORMANCE_EVIDENCE_INVALID:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
