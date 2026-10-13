"""The two-shard gate must prove complete execution, not merely green jobs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci.backend_shards import partition, seal, verify

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = {
    "GITHUB_SHA": "a" * 40,
    "GITHUB_RUN_ID": "1",
    "GITHUB_RUN_ATTEMPT": "1",
    "BACKEND_SOURCE_SHA": "a" * 40,
}


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


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp("shards")
    for index in (1, 2):
        directory = root / f"shard-{index}"
        directory.mkdir()
        nodes = ["test_a.py::test_a", "test_b.py::test_b"]
        selected = partition(nodes, 2)[index - 1]
        data = dict(
            IDENTITY,
            index=index,
            total=2,
            mode="full",
            full=nodes,
            selected=selected,
            exitstatus=0,
            collection_errors=[],
            collection_skips=[],
            subtests=[],
            reports={
                n: [
                    {"when": phase, "outcome": "passed", "duration": 0.1}
                    for phase in ("setup", "call", "teardown")
                ]
                for n in selected
            },
        )
        for mode in ("full", "behavior"):
            data["mode"] = mode
            (directory / f"{mode}.json").write_text(json.dumps(data))
            (directory / f".coverage.{mode}").write_bytes(b"coverage-test")
            (directory / f"{mode}.xml").write_text("<testsuite/>")
        seal(directory)
    return root


def test_exact_complete_artifacts_pass(artifacts):
    assert verify(artifacts, 2, "full", IDENTITY)["collected"] == 2
    assert verify(artifacts, 2, "behavior", IDENTITY)["outcomes"] == {"passed": 2}


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "foreign_sha",
        "attempt",
        "failed",
        "cancelled",
        "collection",
        "duplicate_index",
        "collection_skip",
        "unexpected_artifact",
        "omitted",
        "extra",
        "unexecuted",
        "unfinished",
        "coverage",
        "junit",
        "subtest",
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
    elif fault == "omitted":
        data["selected"] = []
    elif fault == "extra":
        data["selected"].append("test_extra.py::test_a")
    elif fault == "unexecuted":
        data["reports"] = {}
    elif fault == "unfinished":
        data["reports"][node].pop()
    elif fault == "subtest":
        data["subtests"] = [{"nodeid": node, "outcome": "failed"}]
    else:
        (root / "shard-1" / (".coverage.full" if fault == "coverage" else "full.xml")).write_text(
            "changed"
        )
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify(root, 2, "full", IDENTITY)


def test_real_pytest_two_shards(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    for name in ("a", "b"):
        (tmp_path / f"test_{name}.py").write_text(
            "import pytest\ndef test_pass(): assert True\n@pytest.mark.skip(reason='expected')\ndef test_skip(): pass\n"
        )
    all_nodes = []
    for index in (1, 2):
        manifest = tmp_path / f"manifest-{index}.json"
        env = dict(
            os.environ,
            **IDENTITY,
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            PYTHONPATH=str(ROOT),
            BACKEND_SHARD_INDEX=str(index),
            BACKEND_SHARD_TOTAL="2",
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
        assert len(evidence["selected"]) == 2
        assert len(evidence["reports"]) == 2
        all_nodes.extend(evidence["selected"])
    assert len(set(all_nodes)) == len(all_nodes) == 4


def test_workflow_preserves_gates_and_uses_isolated_hosted_shards():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())["jobs"]
    quality, shard, gate = (
        jobs[name] for name in ("backend-quality", "backend-test-shard", "backend-test")
    )
    assert set(quality["needs"]) == {"guard-temp-scripts", "ssot-drift-gate"}
    assert shard["needs"] == "backend-quality"
    assert shard["runs-on"] == "ubuntu-latest"
    assert shard["strategy"] == {"fail-fast": False, "matrix": {"shard": [1, 2]}}
    assert set(gate["needs"]) == {"backend-quality", "backend-test-shard"}
    assert gate["if"] == "always()"
    assert gate["outputs"]["skip"] == "${{ needs.backend-quality.outputs.skip }}"
    preflight = gate["steps"][0]
    assert preflight["working-directory"] == "."
    assert 'test "$QUALITY" = success' in preflight["run"]
    assert 'test "$SHARDS" = skipped' in preflight["run"]
    assert 'test "$SHARDS" = success' in preflight["run"]
    text = json.dumps(quality) + json.dumps(gate)
    for required in (
        "ruff check",
        "ruff format",
        "mypy",
        "guard_coverage_floor.py",
        "count_coverage_ramp_stubs.py",
        "test_bloat_report.py",
        "--behavior --require-backend",
        "--check --require-backend",
    ):
        assert required in text


def test_real_coverage_union_matches_serial(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / ".coveragerc").write_text("[run]\nbranch = true\nsource = demo\n")
    (tmp_path / "demo.py").write_text("def pick(n):\n    if n:\n        return 1\n    return 0\n")
    for name, value in (("a", 1), ("b", 0)):
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
    for index in (1, 2):
        directory = tmp_path / "evidence" / f"shard-{index}"
        directory.mkdir(parents=True)
        shard_env = dict(
            env,
            BACKEND_SHARD_INDEX=str(index),
            BACKEND_SHARD_TOTAL="2",
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
    assert verify(tmp_path / "evidence", 2, "full", IDENTITY)["collected"] == 2
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
    ],
)
def test_aggregate_shell_result_semantics(quality, shards, skip, passed):
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())["jobs"]
    result = subprocess.run(
        ["bash", "-e", "-c", jobs["backend-test"]["steps"][0]["run"]],
        env=dict(os.environ, QUALITY=quality, SHARDS=shards, SKIP=skip),
        capture_output=True,
        timeout=10,
    )
    assert (result.returncode == 0) == passed


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
