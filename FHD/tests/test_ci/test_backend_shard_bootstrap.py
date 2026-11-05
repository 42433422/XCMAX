"""Bootstrap must validate complete evidence before emitting an install version."""

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.backend_shards import configured_total, digest, seal, verify
from tests.test_ci.backend_shard_fixtures import IDENTITY, artifact_source, make_artifacts

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci/backend_shards.py"


@pytest.fixture(autouse=True)
def no_external_profile(monkeypatch):
    monkeypatch.delenv("BACKEND_TIMINGS_FILE", raising=False)


def cli(args, output, total="4", cwd=None):
    return subprocess.run(
        [sys.executable, "-S", str(SCRIPT), *map(str, args)],
        env=dict(os.environ, **IDENTITY, BACKEND_SHARD_TOTAL=total, GITHUB_OUTPUT=str(output)),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("total", [4, 8, 16, 24])
def test_plan_and_complete_evidence_agree_without_site_packages(tmp_path, total):
    output = tmp_path / "outputs"
    result = cli(["plan", "--total", total], output)
    assert result.returncode == 0, result.stderr
    planned = json.loads(result.stdout)
    assert planned == {"total": total, "matrix": {"shard": list(range(1, total + 1))}}
    assert f"total={total}\n" in output.read_text()
    root = make_artifacts(tmp_path / "shards", total)
    assert (
        verify(root, total, "full", IDENTITY, source_root=artifact_source(root))["collected"]
        == total
    )


def test_downloaded_artifacts_bootstrap_without_pytest_or_coverage(tmp_path):
    root = make_artifacts(tmp_path / "shards", 4)
    for path in root.iterdir():
        path.rename(root / path.name.replace("shard-", "backend-shard-1-"))
    output = tmp_path / "outputs"
    result = cli(
        ["verify", root, "--artifact-prefix", "backend-shard-1-"], output, cwd=artifact_source(root)
    )
    assert result.returncode == 0, result.stderr
    summaries = json.loads(result.stdout)
    assert [item["mode"] for item in summaries] == ["full", "behavior"]
    version = importlib.metadata.version("coverage")
    assert output.read_text() == f"coverage_version={version}\n"
    assert all(item["report_toolchain"]["coverage"] == version for item in summaries)


def rebind_toolchain(root, coverage_version):
    directory = root / "shard-1"
    toolchain = directory / "report-toolchain.json"
    data = json.loads(toolchain.read_text())
    data["coverage"] = coverage_version
    toolchain.write_text(json.dumps(data))
    for mode in ("full", "behavior"):
        manifest = directory / f"{mode}.json"
        data = json.loads(manifest.read_text())
        data["report_toolchain_sha256"] = digest(toolchain)
        manifest.write_text(json.dumps(data))


@pytest.mark.parametrize(
    "version", ["1.0.0", "7.16.2 --index-url=bad", "7.16.2\nother=bad", "file:/bad", ""]
)
def test_foreign_or_unsafe_toolchain_never_becomes_install_output(tmp_path, version):
    root = make_artifacts(tmp_path / "shards", 4)
    rebind_toolchain(root, version)
    output = tmp_path / "outputs"
    result = cli(["verify", root], output, cwd=artifact_source(root))
    assert result.returncode != 0
    assert not output.exists()


def test_behavior_failure_cannot_publish_full_only_success(tmp_path):
    root = make_artifacts(tmp_path / "shards", 4)
    (root / "shard-4/.coverage.behavior").write_bytes(b"changed")
    output = tmp_path / "outputs"
    result = cli(["verify", root], output, cwd=artifact_source(root))
    assert result.returncode != 0
    assert not output.exists()


def test_mode_dependent_collection_cannot_publish_install_output(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pytest.ini").write_text("[pytest]\n")
    (source / "test_dynamic.py").write_text(
        "import os\ndef test_always(): pass\n"
        "if os.environ.get('BACKEND_SHARD_MODE') != 'behavior':\n"
        "    def test_unmarked(): pass\n"
    )
    directory = source / "shards/shard-1"
    directory.mkdir(parents=True)
    for mode in ("full", "behavior"):
        env = dict(
            os.environ,
            **IDENTITY,
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            PYTHONPATH=str(SCRIPT.parents[2]),
            BACKEND_SHARD_INDEX="1",
            BACKEND_SHARD_TOTAL="1",
            BACKEND_SHARD_MODE=mode,
            BACKEND_SHARD_MANIFEST=str(directory / f"{mode}.json"),
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "scripts.ci.backend_shards",
                f"--junitxml={directory / f'{mode}.xml'}",
                *(["-m", "not coverage_ramp"] if mode == "behavior" else []),
            ],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        (directory / f".coverage.{mode}").write_bytes(b"coverage-test")
    seal(directory)
    output = tmp_path / "outputs"
    result = cli(["verify", source / "shards"], output, total="1", cwd=source)
    assert result.returncode != 0
    assert "Full and behavior must collect the same" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("value", [None, "", "0", "25", "eight", "4;false", "٤"])
def test_total_has_no_implicit_or_unsafe_fallback(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BACKEND_SHARD_TOTAL", raising=False)
    else:
        monkeypatch.setenv("BACKEND_SHARD_TOTAL", value)
    with pytest.raises(ValueError, match="Explicit BACKEND_SHARD_TOTAL"):
        configured_total()
