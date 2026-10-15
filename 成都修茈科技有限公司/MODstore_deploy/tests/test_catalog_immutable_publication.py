from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from modstore_server import catalog_store as store


def _record(version="1.0.0", source="a"):
    return {
        "id": "immutable-test",
        "version": version,
        "automation_provenance": {"source_sha": source * 40},
    }


def test_different_digest_cannot_overwrite_version(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    first.write_bytes(b"first source")
    second.write_bytes(b"different source")
    saved = store.append_package(_record(), first)
    before = store.packages_path().read_bytes()
    with pytest.raises(ValueError, match="version|版本"):
        store.append_package(_record(source="b"), second)
    assert store.packages_path().read_bytes() == before
    assert (store.files_dir() / saved["stored_filename"]).read_bytes() == first.read_bytes()


def test_same_digest_retry_preserves_original_provenance_and_rejects_old_release(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    source = tmp_path / "package.zip"
    source.write_bytes(b"package")
    saved = store.append_package(_record(), source)
    assert store.append_package(_record(source="b"), source) == saved
    newer = store.append_package(_record("1.2.0", "c"), source)
    with pytest.raises(ValueError, match="version|版本"):
        store.append_package(_record("1.1.0", "d"), source)
    assert store.get_package("immutable-test", "1.2.0") == newer
    assert store.append_package(_record(), source) == saved


def test_failed_catalog_commit_leaves_previous_files_intact(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    source = tmp_path / "package.zip"
    source.write_bytes(b"first")
    saved = store.append_package(_record(), source)
    original = store.packages_path().read_bytes()
    source.write_bytes(b"second")

    def failed(_data):
        raise OSError("simulated full disk")

    monkeypatch.setattr(store, "save_store", failed)
    with pytest.raises(OSError, match="full disk"):
        store.append_package(_record("1.1.0", "b"), source)
    assert store.packages_path().read_bytes() == original
    assert (store.files_dir() / saved["stored_filename"]).read_bytes() == b"first"
    assert len(list(store.files_dir().iterdir())) == 1


def test_competing_processes_publish_only_one_digest(monkeypatch, tmp_path):
    catalog = tmp_path / "catalog"
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    start = tmp_path / "start"
    program = """
import json, pathlib, sys, time
from modstore_server.catalog_store import append_package
start, source = map(pathlib.Path, sys.argv[1:])
while not start.exists(): time.sleep(0.005)
try:
    row = append_package({'id': 'race-test', 'version': '1.0.0'}, source)
except ValueError:
    print('conflict')
else:
    print(row['sha256'])
"""
    processes = []
    for index in range(4):
        source = tmp_path / f"source{index}.zip"
        source.write_bytes(bytes([index]) * 131072)
        processes.append(
            subprocess.Popen(
                [sys.executable, "-c", program, str(start), str(source)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        )
    start.touch()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda proc: proc.communicate(timeout=30), processes))
    assert all(proc.returncode == 0 for proc in processes), results
    successes = [out.strip() for out, _ in results if out.strip() != "conflict"]
    assert len(successes) == 1, results
    row = store.get_package("race-test", "1.0.0")
    assert row["sha256"] == successes[0]
    assert (
        hashlib.sha256((store.files_dir() / row["stored_filename"]).read_bytes()).hexdigest()
        == successes[0]
    )
    assert len(json.loads(store.packages_path().read_text())["packages"]) == 1
