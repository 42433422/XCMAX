"""Pytest hooks; kept separate so artifact verification needs only stdlib."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import pytest

from scripts.ci.backend_shards import configured_total, identity, partition, profile


class ShardEvidence:
    def __init__(self, config):
        self.index = int(os.environ["BACKEND_SHARD_INDEX"])
        self.total = configured_total()
        if not 1 <= self.index <= self.total:
            raise pytest.UsageError("Shard index outside configured range")
        self.path = Path(os.environ["BACKEND_SHARD_MANIFEST"])
        self.data = dict(identity(), index=self.index, total=self.total, full=[], selected=[])
        self.timings, self.data["partition_profile"] = profile()
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
            selected = set(partition(nodes, self.total, self.timings)[self.index - 1])
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
