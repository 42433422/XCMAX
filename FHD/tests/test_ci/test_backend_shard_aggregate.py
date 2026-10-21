"""Real coverage files prove aggregation preserves both measurement scopes."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.backend_shards import seal
from tests.test_ci.backend_shard_fixtures import IDENTITY

ROOT = Path(__file__).resolve().parents[2]
AGGREGATE = ROOT / "scripts/ci/backend_shard_aggregate.py"


def run(command, root, env):
    return subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=45)


@pytest.fixture(scope="module")
def measured_shards(tmp_path_factory):
    root = tmp_path_factory.mktemp("coverage-aggregation")
    (root / "pytest.ini").write_text("[pytest]\nmarkers = coverage_ramp\n")
    (root / ".coveragerc").write_text("[run]\nbranch = true\nsource = demo\n")
    (root / "demo.py").write_text("def pick(n):\n    if n:\n        return 1\n    return 0\n")
    for name in ("a", "b", "c", "d"):
        (root / f"test_{name}.py").write_text(
            "import pytest\nfrom demo import pick\n"
            "def test_real(): assert pick(0) == 0\n"
            "@pytest.mark.coverage_ramp\ndef test_stub(): assert pick(1) == 1\n"
        )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("BACKEND_") and key != "GITHUB_OUTPUT"
    }
    env.update(
        IDENTITY, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(ROOT), BACKEND_SHARD_TOTAL="2"
    )
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
    for mode in ("full", "behavior"):
        selection = ["-m", "not coverage_ramp"] if mode == "behavior" else []
        result = run(base + selection + [f"--cov-report=json:serial-{mode}.json"], root, env)
        assert result.returncode == 0, result.stdout + result.stderr
        for index in (1, 2):
            directory = root / "shards" / f"backend-shard-1-{index}"
            directory.mkdir(parents=True, exist_ok=True)
            shard_env = dict(
                env,
                BACKEND_SHARD_INDEX=str(index),
                BACKEND_SHARD_MODE=mode,
                BACKEND_SHARD_MANIFEST=str(directory / f"{mode}.json"),
            )
            result = run(
                base
                + selection
                + [
                    "--cov-report=",
                    "-p",
                    "scripts.ci.backend_shards",
                    f"--junitxml={directory / f'{mode}.xml'}",
                ],
                root,
                shard_env,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            shutil.copyfile(root / ".coverage", directory / f".coverage.{mode}")
    for directory in (root / "shards").iterdir():
        seal(directory)
    gate = root / "scripts/dev/coverage_ratchet.py"
    gate.parent.mkdir(parents=True)
    gate.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "mode='behavior' if '--behavior' in sys.argv else 'full'\n"
        "report='coverage-behavior.json' if mode=='behavior' else 'coverage.json'\n"
        "actual=json.loads(Path(report).read_text())\n"
        "expected=json.loads(Path('serial-'+mode+'.json').read_text())\n"
        "assert actual['files']==expected['files']\n"
        "assert actual['totals']==expected['totals']\n"
        "assert '--require-backend' in sys.argv and '--check' in sys.argv and '--record' in sys.argv\n"
        "sys.exit(23 if os.environ.get('FAIL_GATE')==mode else 0)\n"
    )
    return root, env


def aggregate_run(fixture, **extra_env):
    root, env = fixture
    return run(
        [sys.executable, str(AGGREGATE), "shards", "--artifact-prefix", "backend-shard-1-"],
        root,
        dict(env, **extra_env),
    )


def test_aggregate_preserves_distinct_full_and_behavior_without_html(measured_shards):
    root, _ = measured_shards
    result = aggregate_run(measured_shards)
    assert result.returncode == 0, result.stdout + result.stderr
    full = json.loads((root / "coverage.json").read_text())
    behavior = json.loads((root / "coverage-behavior.json").read_text())
    assert full["totals"] != behavior["totals"]
    assert (root / "coverage.xml").is_file()
    assert (root / ".coverage.full-combined").is_file()
    assert not (root / "htmlcov").exists()
    timing = json.loads((root / "backend-aggregate-timings.json").read_text())
    assert timing["status"] == "success"
    assert [step["name"] for step in timing["stages"]] == [
        "verify-full",
        "verify-behavior",
        "combine-full",
        "json-full",
        "xml-full",
        "preserve-full-data",
        "combine-behavior",
        "json-behavior",
        "ratchet-full",
        "ratchet-behavior",
    ]
    assert all(step["status"] == "success" and step["seconds"] >= 0 for step in timing["stages"])
    assert timing["total_seconds"] >= sum(step["seconds"] for step in timing["stages"])


def test_gate_failure_keeps_exit_code_and_timing(measured_shards):
    root, _ = measured_shards
    result = aggregate_run(measured_shards, FAIL_GATE="full")
    assert result.returncode == 23, result.stdout + result.stderr
    timing = json.loads((root / "backend-aggregate-timings.json").read_text())
    assert timing["status"] == "failure"
    assert timing["stages"][-1]["name"] == "ratchet-full"
    assert timing["stages"][-1]["status"] == "failure"
