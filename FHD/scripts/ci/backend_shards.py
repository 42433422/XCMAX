"""Deterministic module shards and fail-closed, same-run coverage evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def configured_total() -> int:
    value = os.environ.get("BACKEND_SHARD_TOTAL", "")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 24:
        raise ValueError("Explicit BACKEND_SHARD_TOTAL in 1..24 is required")
    return int(value)


def plan(total: int) -> dict:
    if total not in (4, 8, 16, 24):
        raise ValueError("Supported shard plans are 4, 8, 16, and 24")
    return {"total": total, "matrix": {"shard": list(range(1, total + 1))}}


def validate_toolchain(data: dict) -> dict[str, str]:
    if (
        not isinstance(data, dict)
        or set(data) != {"coverage", "python"}
        or not isinstance(data["coverage"], str)
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", data["coverage"]) is None
        or data["python"] != f"{sys.version_info.major}.{sys.version_info.minor}"
    ):
        raise ValueError("Invalid or incompatible report toolchain")
    return data


def profile() -> tuple[dict, str]:
    path = os.environ.get("BACKEND_TIMINGS_FILE")
    if not path:
        return {}, "count-v1"
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    fallback = data["fallback_seconds_per_test"]
    values = [fallback, *data["modules"].values()]
    if (
        data["schema"] != 1
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
            for v in values
        )
        or fallback <= 0
    ):
        raise ValueError("Invalid timing profile")
    return data, "duration-v1:" + hashlib.sha256(raw).hexdigest()


def partition(nodes: list[str], total: int, timings: dict | None = None) -> list[list[str]]:
    if total < 1 or not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("Invalid shard count or empty/duplicate collection")
    modules: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        modules[node.split("::", 1)[0]].append(node)
    groups: list[list[str]] = [[] for _ in range(total)]
    weights = {
        name: max(
            timings["modules"].get(name, len(items) * timings["fallback_seconds_per_test"]), 1e-6
        )
        if timings
        else len(items)
        for name, items in modules.items()
    }
    loads = [0.0] * total
    for module in sorted(modules, key=lambda name: (-weights[name], name)):
        target = min(range(total), key=lambda index: (loads[index], index))
        groups[target].extend(modules[module])
        loads[target] += weights[module]
    return groups


def identity() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "BACKEND_SOURCE_SHA")
    }


def pytest_configure(config):
    # The bootstrap verifier must run before report dependencies are installed.
    import pytest

    from scripts.ci.backend_shard_plugin import ShardEvidence

    if "BACKEND_SHARD_INDEX" not in os.environ:
        raise pytest.UsageError("Explicit backend shard configuration required")
    config.pluginmanager.register(ShardEvidence(config), "backend-shard-evidence")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def seal(directory: Path) -> None:
    toolchain = validate_toolchain(
        {
            "coverage": importlib.metadata.version("coverage"),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        }
    )
    toolchain_path = directory / "report-toolchain.json"
    toolchain_path.write_text(json.dumps(toolchain, sort_keys=True), encoding="utf-8")
    for mode in ("full", "behavior"):
        path = directory / f"{mode}.json"
        data = json.loads(path.read_text())
        data["coverage_sha256"] = digest(directory / f".coverage.{mode}")
        data["junit_sha256"] = digest(directory / f"{mode}.xml")
        data["report_toolchain_sha256"] = digest(toolchain_path)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def verify(
    root: Path, total: int, mode: str, expected: dict[str, str], artifact_prefix: str = "shard-"
) -> dict:
    if not 1 <= total <= 24 or mode not in ("full", "behavior"):
        raise ValueError("Invalid shard total or evidence mode")
    if re.fullmatch(r"[A-Za-z0-9_-]+", artifact_prefix) is None:
        raise ValueError("Invalid artifact directory prefix")
    timings, expected_profile = profile()
    directories = sorted(root.iterdir())
    if len(directories) != total or {p.name for p in directories} != {
        f"{artifact_prefix}{i}" for i in range(1, total + 1)
    }:
        raise ValueError("Missing or extra shard artifact")
    full = None
    skipped = None
    toolchain = None
    indices, selected, outcomes, node_outcomes = set(), [], Counter(), {}
    for directory in directories:
        manifest = directory / f"{mode}.json"
        if directory.is_symlink() or manifest.is_symlink() or not manifest.is_file():
            raise ValueError("Missing or indirect shard manifest")
        data = json.loads(manifest.read_text())
        if any(data.get(key) != value for key, value in expected.items()):
            raise ValueError("Foreign SHA/run/attempt in shard evidence")
        if data.get("partition_profile") != expected_profile:
            raise ValueError("Foreign partition profile")
        index = data["index"]
        if (
            type(index) is not int
            or index in indices
            or not 1 <= index <= total
            or data["total"] != total
            or directory.name != f"{artifact_prefix}{index}"
        ):
            raise ValueError("Invalid/duplicate shard identity")
        indices.add(index)
        if data["mode"] != mode or data["exitstatus"] != 0 or data["collection_errors"]:
            raise ValueError("Shard did not successfully finish")
        nodes = data["full"]
        groups = partition(nodes, total, timings)
        if full is not None and nodes != full:
            raise ValueError("Different full collections across shards")
        if skipped is not None and skipped != data["collection_skips"]:
            raise ValueError("Different collection skips across shards")
        skipped = data["collection_skips"]
        full = nodes
        chosen = data["selected"]
        if chosen != sorted(groups[index - 1]) or set(data["reports"]) != set(chosen):
            raise ValueError("Missing/extra test execution")
        if any(r["outcome"] == "failed" or r["nodeid"] not in chosen for r in data["subtests"]):
            raise ValueError("Failed or foreign subtest")
        for node, reports in data["reports"].items():
            phases = {report["when"]: report["outcome"] for report in reports}
            if len(phases) != len(reports) or phases.get("teardown") != "passed":
                raise ValueError("Duplicate or unfinished test execution")
            if phases.get("setup") == "skipped" and "call" not in phases:
                outcomes["skipped"] += 1
            elif phases.get("setup") == "passed" and phases.get("call") in ("passed", "skipped"):
                outcomes[phases["call"]] += 1
            else:
                raise ValueError("Failed/invalid test phase")
            node_outcomes[node] = phases.get("call", phases["setup"])
        for name, key in (
            (f".coverage.{mode}", "coverage_sha256"),
            (f"{mode}.xml", "junit_sha256"),
            ("report-toolchain.json", "report_toolchain_sha256"),
        ):
            path = directory / name
            if path.is_symlink() or not path.is_file() or data[key] != digest(path):
                raise ValueError("Missing or changed shard output")
        current_toolchain = validate_toolchain(
            json.loads((directory / "report-toolchain.json").read_text())
        )
        if toolchain is not None and current_toolchain != toolchain:
            raise ValueError("Different report toolchains across shards")
        toolchain = current_toolchain
        selected.extend(chosen)
    if len(selected) != len(set(selected)) or set(selected) != set(full or []):
        raise ValueError("Shard union differs from full suite")
    return {
        "mode": mode,
        "collected": len(selected),
        "outcomes": dict(outcomes),
        "collection_skips": skipped,
        "report_toolchain": toolchain,
        "collection_sha256": hashlib.sha256(json.dumps(full, sort_keys=True).encode()).hexdigest(),
        "outcomes_sha256": hashlib.sha256(
            json.dumps(node_outcomes, sort_keys=True).encode()
        ).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planner = commands.add_parser("plan")
    planner.add_argument("--total", type=int, choices=(4, 8, 16, 24), default=4)
    commands.add_parser("seal").add_argument("directory", type=Path)
    verifier = commands.add_parser("verify")
    verifier.add_argument("directory", type=Path)
    verifier.add_argument("--artifact-prefix", default="shard-")
    args = parser.parse_args()
    if args.command == "seal":
        seal(args.directory)
        return
    if args.command == "plan":
        result = plan(args.total)
        outputs = {"total": str(args.total), "matrix": json.dumps(result["matrix"])}
    else:
        result = [
            verify(args.directory, configured_total(), mode, identity(), args.artifact_prefix)
            for mode in ("full", "behavior")
        ]
        outputs = {"coverage_version": result[0]["report_toolchain"]["coverage"]}
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            for name, value in outputs.items():
                stream.write(f"{name}={value}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
