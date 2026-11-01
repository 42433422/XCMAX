"""Pytest hooks; kept separate so artifact verification needs only stdlib."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import pytest

from scripts.ci.backend_shards import (
    collection_leaves,
    configured_total,
    identity,
    object_digest,
    partition,
    profile,
    source_inventory,
)


class ShardEvidence:
    def __init__(self, config):
        self.index = int(os.environ["BACKEND_SHARD_INDEX"])
        self.total = configured_total()
        if not 1 <= self.index <= self.total:
            raise pytest.UsageError("Shard index outside configured range")
        self.root = config.rootpath.resolve()
        self.path = Path(os.environ["BACKEND_SHARD_MANIFEST"])
        timings, partition_profile = profile()
        configuration, files = source_inventory(self.root)
        mode = os.environ.get("BACKEND_SHARD_MODE", "full")
        roots = {(self.root / directory).resolve() for directory in configuration["roots"]}
        expected_config = configuration["config"]
        if (
            mode not in ("full", "behavior")
            or (config.inipath.resolve() if config.inipath else None)
            != ((self.root / expected_config["path"]).resolve() if expected_config else None)
            or {Path(arg).resolve() for arg in config.args} != roots
            or config.getini("python_files") != configuration["python_files"]
            or config.getini("norecursedirs") != configuration["norecursedirs"]
            or config.option.markexpr.strip() != ("not coverage_ramp" if mode == "behavior" else "")
            or any(
                getattr(config.option, name, None)
                for name in (
                    "keyword",
                    "deselect",
                    "ignore",
                    "ignore_glob",
                    "lf",
                    "failedfirst",
                    "newfirst",
                    "collectonly",
                    "pyargs",
                    "collect_in_virtualenv",
                    "keepduplicates",
                    "override_ini",
                    "inifilename",
                    "noconftest",
                    "confcutdir",
                )
            )
        ):
            raise pytest.UsageError(
                "Backend shards require the complete configured test directories and mode"
            )
        assigned = sorted(partition(list(files), self.total, timings)[self.index - 1])
        if not assigned:
            raise pytest.UsageError("Empty backend file shard")
        self.assigned = set(assigned)
        self.data = dict(
            identity(),
            schema=2,
            index=self.index,
            total=self.total,
            mode=mode,
            partition_profile=partition_profile,
            configuration=configuration,
            files=files,
            source_inventory_sha256=object_digest({"configuration": configuration, "files": files}),
            assigned_files=assigned,
            collected=[],
            selected=[],
            excluded_ramp=[],
        )
        self.reports: dict[str, list[dict]] = defaultdict(list)
        self.collection_reports: dict[str, list[dict]] = defaultdict(list)
        self.collection_errors = []
        self.collection_skips = []
        self.subtests = []
        self.started = time.monotonic()
        self.phase_seconds: dict[str, float] = {}

    def pytest_ignore_collect(self, collection_path, config):
        if collection_path.is_file():
            relative = collection_path.relative_to(self.root).as_posix()
            if relative in self.data["files"] and relative not in self.assigned:
                return True
        return None

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection(self, session):
        started = time.monotonic()
        try:
            yield
        finally:
            self.phase_seconds["collection"] = time.monotonic() - started

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtestloop(self, session):
        started = time.monotonic()
        try:
            yield
        finally:
            self.phase_seconds["execution"] = time.monotonic() - started

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, config, items):
        original = list(items)
        yield
        nodes = sorted(item.nodeid for item in original)
        ramp = sorted(item.nodeid for item in original if item.get_closest_marker("coverage_ramp"))
        selected = sorted(item.nodeid for item in items)
        self.data.update(collected=nodes, selected=selected, excluded_ramp=ramp)
        expected = [node for node in nodes if self.data["mode"] == "full" or node not in set(ramp)]
        if not selected or selected != expected:
            raise pytest.UsageError("Empty or partially selected backend shard")

    def pytest_collection_finish(self, session):
        if not self.collection_errors:
            try:
                collection_leaves(
                    dict(
                        self.data,
                        collection_reports=dict(self.collection_reports),
                        collection_skips=sorted(self.collection_skips),
                    ),
                    self.data["assigned_files"],
                )
            except ValueError as exc:
                raise pytest.UsageError(str(exc)) from exc

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(report.nodeid)
        if report.nodeid.split("::", 1)[0] in self.assigned:
            self.collection_reports[report.nodeid].append(
                {
                    "outcome": report.outcome,
                    "children": [
                        {"nodeid": node.nodeid, "collector": isinstance(node, pytest.Collector)}
                        for node in (report.result or [])
                    ],
                }
            )
            if report.skipped:
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
            collection_reports=dict(self.collection_reports),
            collection_errors=self.collection_errors,
            collection_skips=sorted(self.collection_skips),
            subtests=self.subtests,
            elapsed=time.monotonic() - self.started,
            phase_seconds=self.phase_seconds,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, sort_keys=True), encoding="utf-8")
