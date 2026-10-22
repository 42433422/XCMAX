"""The shard gate must prove complete execution, not merely green jobs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci.backend_shards import partition, profile, seal, verify
from tests.test_ci.backend_shard_fixtures import IDENTITY, make_artifacts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolate_profile_environment(monkeypatch):
    monkeypatch.delenv("BACKEND_TIMINGS_FILE", raising=False)


def test_balancing_keeps_modules_and_exact_union():
    nodes = [f"test_{m}.py::test_{n}" for m, size in enumerate((8, 5, 3, 2)) for n in range(size)]
    groups = partition(nodes, 2)
    assert sorted(map(len, groups)) == [8, 10]
    assert set(groups[0]).isdisjoint(groups[1])
    assert set(sum(groups, [])) == set(nodes)
    assert [set(g) for g in partition(list(reversed(nodes)), 2)] == [set(g) for g in groups]
    assert all(
        len(
            {
                i
                for i, group in enumerate(groups)
                if any(n.startswith(f"test_{m}.py::") for n in group)
            }
        )
        == 1
        for m in range(4)
    )


@pytest.mark.parametrize("nodes,total", [([], 2), (["a", "a"], 2), (["a"], 0)])
def test_invalid_collection(nodes, total):
    with pytest.raises(ValueError):
        partition(nodes, total)


@pytest.fixture(scope="module", params=[2, 4, 8])
def artifacts(tmp_path_factory, request):
    return make_artifacts(tmp_path_factory.mktemp("shards"), request.param)


def test_exact_complete_artifacts_pass(artifacts):
    total = len(list(artifacts.iterdir()))
    assert verify(artifacts, total, "full", IDENTITY)["collected"] == max(4, total)
    assert verify(artifacts, total, "behavior", IDENTITY)["outcomes"] == {"passed": max(4, total)}


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "foreign_sha",
        "foreign_run",
        "attempt",
        "failed",
        "cancelled",
        "collection",
        "duplicate_index",
        "boolean_index",
        "collection_skip",
        "unexpected_artifact",
        "omitted",
        "extra",
        "unexecuted",
        "unfinished",
        "coverage",
        "junit",
        "subtest",
        "profile",
        "total",
        "toolchain",
        "manifest_symlink",
    ],
)
def test_bad_evidence_fails_closed(artifacts, tmp_path, fault):
    root = tmp_path / "copy"
    shutil.copytree(artifacts, root)
    path = root / "shard-1/full.json"
    data = json.loads(path.read_text())
    node = data["selected"][0]
    if fault == "missing":
        shutil.rmtree(root / "shard-2")
    elif fault == "foreign_sha":
        data["BACKEND_SOURCE_SHA"] = "b" * 40
    elif fault == "foreign_run":
        data["GITHUB_RUN_ID"] = "2"
    elif fault == "attempt":
        data["GITHUB_RUN_ATTEMPT"] = "2"
    elif fault in ("failed", "cancelled"):
        data["exitstatus"] = 1 if fault == "failed" else 2
    elif fault == "collection":
        data["collection_errors"] = ["test_broken.py"]
    elif fault == "collection_skip":
        data["collection_skips"] = ["test_hidden.py"]
    elif fault == "unexpected_artifact":
        (root / "unexpected").mkdir()
    elif fault == "duplicate_index":
        data["index"] = 2
    elif fault == "boolean_index":
        data["index"] = True
    elif fault == "omitted":
        data["selected"] = []
    elif fault == "extra":
        data["selected"].append("test_extra.py::test_a")
    elif fault == "unexecuted":
        data["reports"] = {}
    elif fault == "unfinished":
        data["reports"][node].pop()
    elif fault == "profile":
        data["partition_profile"] = "duration-v1:foreign"
    elif fault == "total":
        data["total"] = 3
    elif fault == "subtest":
        data["subtests"] = [{"nodeid": node, "outcome": "failed"}]
    elif fault == "toolchain":
        (root / "shard-1/report-toolchain.json").write_text('{"coverage":"1.0","python":"3.11"}')
    elif fault == "manifest_symlink":
        pass
    else:
        (root / "shard-1" / (".coverage.full" if fault == "coverage" else "full.xml")).write_text(
            "changed"
        )
    path.write_text(json.dumps(data))
    if fault == "manifest_symlink":
        target = tmp_path / "foreign-manifest.json"
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(ValueError):
        verify(root, len(list(artifacts.iterdir())), "full", IDENTITY)


@pytest.mark.parametrize("total", [4, 8])
def test_real_pytest_shards(tmp_path, total):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    for name in "abcdefgh":
        (tmp_path / f"test_{name}.py").write_text(
            "import pytest\ndef test_pass(): assert True\n@pytest.mark.skip(reason='expected')\ndef test_skip(): pass\n"
        )
    all_nodes = []
    for index in range(1, total + 1):
        manifest = tmp_path / f"manifest-{index}.json"
        env = dict(
            os.environ,
            **IDENTITY,
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            PYTHONPATH=str(ROOT),
            BACKEND_SHARD_INDEX=str(index),
            BACKEND_SHARD_TOTAL=str(total),
            BACKEND_SHARD_MANIFEST=str(manifest),
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "scripts.ci.backend_shards", "-q"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(manifest.read_text())
        assert len(evidence["selected"]) == 16 // total
        assert len(evidence["reports"]) == 16 // total
        all_nodes.extend(evidence["selected"])
    assert len(set(all_nodes)) == len(all_nodes) == 16


def test_workflow_preserves_gates_and_uses_isolated_hosted_shards():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())["jobs"]
    quality, shard, gate = (
        jobs[name] for name in ("backend-quality", "backend-test-shard", "backend-test")
    )
    prerequisites = {"guard-temp-scripts", "classify"}
    assert set(quality["needs"]) == set(shard["needs"]) == prerequisites
    assert shard["if"] == "needs.classify.outputs.backend == 'true'"
    assert shard["runs-on"] == "ubuntu-latest"
    assert shard["strategy"] == {
        "fail-fast": False,
        "max-parallel": 8,
        "matrix": "${{ fromJSON(needs.classify.outputs.backend_matrix) }}",
    }
    assert set(gate["needs"]) == prerequisites | {
        "ssot-drift-gate",
        "backend-quality",
        "backend-test-shard",
    }
    assert gate["if"] == "always()"
    assert gate["outputs"]["skip"] == "${{ needs.classify.outputs.backend_skip }}"
    preflight = gate["steps"][0]
    assert preflight["working-directory"] == "."
    assert 'test "$QUALITY" = success' in preflight["run"]
    assert 'test "$SHARDS" = skipped' in preflight["run"]
    assert 'test "$SHARDS" = success' in preflight["run"]
    text = json.dumps(quality)
    for required in (
        "ruff check",
        "ruff format",
        "mypy",
        "guard_coverage_floor.py",
        "count_coverage_ramp_stubs.py",
        "test_bloat_report.py",
    ):
        assert required in text
    commands = "\n".join(step.get("run", "") for step in gate["steps"])
    assert "scripts/ci/backend_shard_aggregate.py shards" in commands
    assert "requirements-dev.txt" not in commands
    download, verify_step, install, aggregate = (
        next(index for index, step in enumerate(gate["steps"]) if token in json.dumps(step))
        for token in (
            "actions/download-artifact@",
            "backend_shards.py verify",
            "pip install",
            "backend_shard_aggregate.py",
        )
    )
    assert download < verify_step < install < aggregate
    assert (
        gate["steps"][install]["env"]["COVERAGE_VERSION"]
        == "${{ steps.verify.outputs.coverage_version }}"
    )


@pytest.mark.parametrize("total", [4, 8])
def test_real_coverage_union_matches_serial(tmp_path, total, monkeypatch):
    timings = tmp_path / "timings.json"
    timings.write_text(
        json.dumps({"schema": 1, "fallback_seconds_per_test": 1, "modules": {"test_a.py": 8}})
    )
    monkeypatch.setenv("BACKEND_TIMINGS_FILE", str(timings))
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / ".coveragerc").write_text("[run]\nbranch = true\nsource = demo\n")
    (tmp_path / "demo.py").write_text("def pick(n):\n    if n:\n        return 1\n    return 0\n")
    for index, name in enumerate("abcdefgh"):
        value = index % 2
        (tmp_path / f"test_{name}.py").write_text(
            f"from demo import pick\ndef test_pick(): assert pick({value}) == {value}\n"
        )
    env = dict(os.environ, **IDENTITY, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(ROOT))
    base = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "pytest_cov.plugin",
        "--cov",
        "--cov-branch",
        "--cov-fail-under=0",
    ]

    def run(args, run_env):
        result = subprocess.run(
            args, cwd=tmp_path, env=run_env, capture_output=True, text=True, timeout=45
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run(base + ["--cov-report=json:serial.json"], env)
    for index in range(1, total + 1):
        directory = tmp_path / "evidence" / f"shard-{index}"
        directory.mkdir(parents=True)
        shard_env = dict(
            env,
            BACKEND_SHARD_INDEX=str(index),
            BACKEND_SHARD_TOTAL=str(total),
            BACKEND_SHARD_MODE="full",
            BACKEND_SHARD_MANIFEST=str(directory / "full.json"),
        )
        run(
            base
            + [
                "--cov-report=",
                "-p",
                "scripts.ci.backend_shards",
                f"--junitxml={directory / 'full.xml'}",
            ],
            shard_env,
        )
        shutil.copy(tmp_path / ".coverage", directory / ".coverage.full")
        data = json.loads((directory / "full.json").read_text())
        data["mode"] = "behavior"
        (directory / "behavior.json").write_text(json.dumps(data))
        shutil.copy(directory / "full.xml", directory / "behavior.xml")
        shutil.copy(directory / ".coverage.full", directory / ".coverage.behavior")
        seal(directory)
    assert verify(tmp_path / "evidence", total, "full", IDENTITY)["collected"] == 8
    run(
        [
            sys.executable,
            "-m",
            "coverage",
            "combine",
            "--keep",
            *map(str, sorted((tmp_path / "evidence").glob("shard-*/.coverage.full"))),
        ],
        env,
    )
    run([sys.executable, "-m", "coverage", "json", "-o", "combined.json", "--fail-under=0"], env)
    serial, combined = (
        json.loads((tmp_path / name).read_text()) for name in ("serial.json", "combined.json")
    )
    assert combined["files"] == serial["files"]
    assert combined["totals"] == serial["totals"]


@pytest.mark.parametrize(
    "quality,shards,skip,passed",
    [
        ("success", "success", "false", True),
        ("success", "skipped", "true", True),
        ("failure", "skipped", "false", False),
        ("cancelled", "skipped", "true", False),
        ("success", "cancelled", "false", False),
        ("success", "skipped", "false", False),
        ("success", "failure", "false", False),
        ("success", "success", "true", False),
        ("success", "success", "", False),
        ("success", "success", "unknown", False),
    ],
)
def test_aggregate_shell_result_semantics(quality, shards, skip, passed):
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())["jobs"]
    result = subprocess.run(
        ["bash", "-e", "-c", jobs["backend-test"]["steps"][0]["run"]],
        env=dict(
            os.environ,
            GUARD="success",
            SSOT="success",
            CLASSIFY="success",
            VALID="true",
            SOURCE_SHA="a" * 40,
            EXPECTED_SOURCE_SHA="a" * 40,
            QUALITY=quality,
            SHARDS=shards,
            SHOULD_RUN="false" if skip == "true" else "true",
            SKIP=skip,
        ),
        capture_output=True,
        timeout=10,
    )
    assert (result.returncode == 0) == passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("CLASSIFY", "failure"),
        ("CLASSIFY", "cancelled"),
        ("CLASSIFY", "skipped"),
        ("VALID", "false"),
        ("VALID", ""),
        ("SOURCE_SHA", "b" * 40),
        ("SOURCE_SHA", ""),
    ],
)
def test_aggregate_shell_rejects_unbound_classification(field, value):
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())["jobs"]
    env = dict(
        os.environ,
        GUARD="success",
        SSOT="success",
        CLASSIFY="success",
        VALID="true",
        SOURCE_SHA="a" * 40,
        EXPECTED_SOURCE_SHA="a" * 40,
        QUALITY="success",
        SHARDS="skipped",
        SHOULD_RUN="false",
        SKIP="true",
    )
    env[field] = value
    result = subprocess.run(
        ["bash", "-e", "-c", jobs["backend-test"]["steps"][0]["run"]],
        env=env,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0


def test_behavior_marker_is_applied_before_sharding(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = coverage_ramp\n")
    for name in ("a", "b"):
        (tmp_path / f"test_{name}.py").write_text(
            "import pytest\ndef test_real(): pass\n@pytest.mark.coverage_ramp\ndef test_stub(): pass\n"
        )
    env = dict(
        os.environ,
        **IDENTITY,
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONPATH=str(ROOT),
        BACKEND_SHARD_INDEX="1",
        BACKEND_SHARD_TOTAL="2",
        BACKEND_SHARD_MODE="behavior",
        BACKEND_SHARD_MANIFEST=str(tmp_path / "evidence.json"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.ci.backend_shards",
            "-m",
            "not coverage_ramp",
            "-q",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["mode"] == "behavior"
    assert evidence["full"] == ["test_a.py::test_real", "test_b.py::test_real"]
    assert evidence["selected"] == ["test_a.py::test_real"]


@pytest.mark.parametrize("total", [2, 4])
def test_duration_balance_new_modules_and_stable_ties(total):
    nodes = [f"test_{n}.py::test_a" for n in range(8)]
    timings = {
        "modules": {f"test_{n}.py": value for n, value in enumerate([8, 7, 6, 5])},
        "fallback_seconds_per_test": 1,
    }
    groups = partition(nodes, total, timings)
    assert sorted(sum(groups, [])) == nodes
    assert partition(list(reversed(nodes)), total, timings) == groups
    loads = [sum(timings["modules"].get(n.split("::")[0], 1) for n in g) for g in groups]
    assert max(loads) - min(loads) <= 1


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "bad"])
def test_invalid_profile_fails_closed(tmp_path, monkeypatch, value):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({"schema": 1, "fallback_seconds_per_test": 1, "modules": {"test_a.py": value}})
    )
    monkeypatch.setenv("BACKEND_TIMINGS_FILE", str(path))
    with pytest.raises(ValueError):
        profile()


def test_weighted_real_collection_and_profile_integrity(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({"schema": 1, "fallback_seconds_per_test": 1, "modules": {"test_a.py": 8}})
    )
    monkeypatch.setenv("BACKEND_TIMINGS_FILE", str(path))
    timings, identity = profile()
    assert identity.startswith("duration-v1:")
    assert partition(["test_a.py::one", "test_b.py::one"], 4, timings) == [
        ["test_a.py::one"],
        ["test_b.py::one"],
        [],
        [],
    ]
    path.write_text(path.read_text() + " ")
    assert profile()[1] != identity


def test_dynamic_production_configuration_keeps_full_and_behavior():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())["jobs"]
    shard, gate = (jobs[n] for n in ("backend-test-shard", "backend-test"))
    assert not {"backend-four-shard", "backend-four-test", "backend-shard-comparison"} & jobs.keys()
    assert shard["runs-on"] == gate["runs-on"] == "ubuntu-latest"
    assert (
        shard["env"]["BACKEND_SHARD_TOTAL"]
        == gate["env"]["BACKEND_SHARD_TOTAL"]
        == "${{ needs.classify.outputs.backend_total }}"
    )
    assert shard["env"]["BACKEND_TIMINGS_FILE"] == gate["env"]["BACKEND_TIMINGS_FILE"]
    assert shard["env"]["BACKEND_TIMINGS_FILE"] == "metrics/backend_test_timings.json"
    assert gate["if"] == "always()"
    command = next(
        step["run"] for step in shard["steps"] if "Run complete suite" in step.get("name", "")
    )
    assert command.count("--cov --cov-branch --cov-fail-under=0") == 2
    assert "-m 'not coverage_ramp'" in command
    assert "backend_shards.py seal shard-evidence" in command
    assert shard["steps"][-1]["with"]["include-hidden-files"] is True
    assert "backend-shard-${{" in json.dumps(shard) and "backend-shard-${{" in json.dumps(gate)
