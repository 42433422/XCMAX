"""Deterministic module shards and fail-closed, same-run coverage evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pytest


def partition(nodes: list[str], total: int) -> list[list[str]]:
    if total < 1 or not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("Invalid shard count or empty/duplicate collection")
    modules: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        modules[node.split("::", 1)[0]].append(node)
    groups: list[list[str]] = [[] for _ in range(total)]
    for module in sorted(modules, key=lambda name: (-len(modules[name]), name)):
        target = min(range(total), key=lambda index: (len(groups[index]), index))
        groups[target].extend(modules[module])
    return groups


def identity() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "BACKEND_SOURCE_SHA")
    }


class ShardEvidence:
    def __init__(self, config):
        self.index = int(os.environ["BACKEND_SHARD_INDEX"])
        self.total = int(os.environ["BACKEND_SHARD_TOTAL"])
        if not 1 <= self.index <= self.total:
            raise pytest.UsageError("Shard index outside configured range")
        self.path = Path(os.environ["BACKEND_SHARD_MANIFEST"])
        self.data = dict(identity(), index=self.index, total=self.total, full=[], selected=[])
        self.data["mode"] = os.environ.get("BACKEND_SHARD_MODE", "full")
        self.reports: dict[str, list[dict]] = defaultdict(list)
        self.collection_errors = []
        self.collection_skips = []
        self.subtests = []
        self.started = time.monotonic()

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        nodes = [item.nodeid for item in items]
        try:
            selected = set(partition(nodes, self.total)[self.index - 1])
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        self.data.update(full=sorted(nodes), selected=sorted(selected))
        excluded = [item for item in items if item.nodeid not in selected]
        items[:] = [item for item in items if item.nodeid in selected]
        config.hook.pytest_deselected(items=excluded)

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(report.nodeid)
        elif report.skipped:
            self.collection_skips.append(report.nodeid)

    def pytest_runtest_logreport(self, report):
        if hasattr(report, "context"):
            self.subtests.append({"nodeid": report.nodeid, "outcome": report.outcome})
            return
        self.reports[report.nodeid].append(
            {"when": report.when, "outcome": report.outcome, "duration": report.duration}
        )

    def pytest_sessionfinish(self, session, exitstatus):
        self.data.update(
            exitstatus=int(exitstatus),
            reports=dict(self.reports),
            collection_errors=self.collection_errors,
            collection_skips=sorted(self.collection_skips),
            subtests=self.subtests,
            elapsed=time.monotonic() - self.started,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, sort_keys=True), encoding="utf-8")


def pytest_configure(config):
    if "BACKEND_SHARD_INDEX" not in os.environ:
        raise pytest.UsageError("Explicit backend shard configuration required")
    config.pluginmanager.register(ShardEvidence(config), "backend-shard-evidence")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(directory: Path) -> None:
    for mode in ("full", "behavior"):
        path = directory / f"{mode}.json"
        data = json.loads(path.read_text())
        data["coverage_sha256"] = digest(directory / f".coverage.{mode}")
        data["junit_sha256"] = digest(directory / f"{mode}.xml")
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def verify(root: Path, total: int, mode: str, expected: dict[str, str]) -> dict:
    directories = sorted(root.iterdir())
    if len(directories) != total or {p.name for p in directories} != {
        f"shard-{i}" for i in range(1, total + 1)
    }:
        raise ValueError("Missing or extra shard artifact")
    full = None
    skipped = None
    indices, selected, outcomes = set(), [], Counter()
    for directory in directories:
        data = json.loads((directory / f"{mode}.json").read_text())
        if any(data.get(key) != value for key, value in expected.items()):
            raise ValueError("Foreign SHA/run/attempt in shard evidence")
        index = data["index"]
        if index in indices or not 1 <= index <= total or data["total"] != total:
            raise ValueError("Invalid/duplicate shard identity")
        indices.add(index)
        if data["mode"] != mode or data["exitstatus"] != 0 or data["collection_errors"]:
            raise ValueError("Shard did not successfully finish")
        nodes = data["full"]
        groups = partition(nodes, total)
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
        for reports in data["reports"].values():
            phases = {report["when"]: report["outcome"] for report in reports}
            if len(phases) != len(reports) or phases.get("teardown") != "passed":
                raise ValueError("Duplicate or unfinished test execution")
            if phases.get("setup") == "skipped" and "call" not in phases:
                outcomes["skipped"] += 1
            elif phases.get("setup") == "passed" and phases.get("call") in ("passed", "skipped"):
                outcomes[phases["call"]] += 1
            else:
                raise ValueError("Failed/invalid test phase")
        for name, key in (
            (f".coverage.{mode}", "coverage_sha256"),
            (f"{mode}.xml", "junit_sha256"),
        ):
            path = directory / name
            if path.is_symlink() or not path.is_file() or data[key] != digest(path):
                raise ValueError("Missing or changed shard output")
        selected.extend(chosen)
    if len(selected) != len(set(selected)) or set(selected) != set(full or []):
        raise ValueError("Shard union differs from full suite")
    return {
        "mode": mode,
        "collected": len(selected),
        "outcomes": dict(outcomes),
        "collection_skips": skipped,
    }


def main() -> None:
    command, directory = sys.argv[1:3]
    if command == "seal":
        seal(Path(directory))
    elif command == "verify":
        result = [verify(Path(directory), 2, mode, identity()) for mode in ("full", "behavior")]
        print(json.dumps(result, indent=2))
    else:
        raise ValueError("Unknown command")


if __name__ == "__main__":
    main()
