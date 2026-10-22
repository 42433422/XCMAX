"""Old local personnel snapshots must not be repackaged into the shared catalog."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/package"


def load_script(filename):
    spec = importlib.util.spec_from_file_location(
        filename.replace("-", "_"), SCRIPTS / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retired_builder_cannot_reuse_local_template_or_supplied_source(tmp_path):
    builder = load_script("build-sunbird-seed.py")
    old = tmp_path / "seed/424/old.xlsx"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"synthetic legacy snapshot sentinel")
    before = old.read_bytes()
    with pytest.raises(RuntimeError, match="retired"):
        builder.build_sunbird_seed(seed_root=old.parents[1], template_src=old)
    assert old.read_bytes() == before
    assert list(tmp_path.rglob("*.db")) == []


def test_retired_publisher_cannot_package_or_register_supplied_zip(tmp_path):
    publisher = load_script("publish-sunbird-delivery-seed.py")
    source = tmp_path / "existing.zip"
    source.write_bytes(b"synthetic existing package sentinel")
    destination = tmp_path / "catalog"
    with pytest.raises(RuntimeError, match="disabled"):
        publisher._build_zip(tmp_path, destination, "1.0.0")
    with pytest.raises(RuntimeError, match="disabled"):
        publisher._upsert_package(destination, source, "1.0.0")
    assert not destination.exists()
    assert source.read_bytes() == b"synthetic existing package sentinel"


@pytest.mark.parametrize(
    "filename", ["build-sunbird-seed.py", "publish-sunbird-delivery-seed.py"]
)
def test_retired_cli_fails_before_handling_legacy_arguments(tmp_path, filename):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / filename),
            "--zip-path",
            str(tmp_path / "old.zip"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "private delivery workflow" in result.stderr
    assert list(tmp_path.iterdir()) == []
