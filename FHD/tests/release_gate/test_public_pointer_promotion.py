import fcntl
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "成都修茈科技有限公司/MODstore_deploy/scripts/sync_site_download_release.py"


@pytest.fixture
def publication(tmp_path):
    spec = importlib.util.spec_from_file_location("pointer_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target, source, archive, lock = (
        tmp_path / name for name in ("pointer", "source", "archive", "lock")
    )
    target.write_bytes(b'{ "version": "old" }\r\n')
    source.write_bytes(b'{"version":"new"}\n')
    return module, target, source, archive, lock


@pytest.mark.parametrize("absent", [False, True])
def test_original_bytes_or_absence_are_recoverable(publication, absent):
    guard, target, source, archive, lock = publication
    old = None if absent else target.read_bytes()
    if absent:
        target.unlink()
    guard.pointer_transaction(target, archive, lock, snapshot=True)
    guard.pointer_transaction(target, archive, lock, source=source)
    assert target.read_bytes() == source.read_bytes()
    assert (archive / "replacement").read_bytes() == source.read_bytes()
    guard.pointer_transaction(target, archive, lock, restore=True)
    assert (target.read_bytes() if target.exists() else None) == old
    assert json.loads((archive / "snapshot.json").read_bytes())["target"] == str(target)


def test_two_processes_with_same_expected_bytes_cannot_both_promote(publication):
    guard, target, source, archive, lock = publication
    second = source.with_name("second")
    second.write_bytes(b'{"version":"other"}\n')
    archives = [archive, archive.with_name("second-archive")]
    for snapshot in archives:
        guard.pointer_transaction(target, snapshot, lock, snapshot=True)
    processes = []
    try:
        with lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            for incoming, snapshot in zip((source, second), archives, strict=True):
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            str(SCRIPT),
                            "--promote-source",
                            str(incoming),
                            "--pointer-target",
                            str(target),
                            "--archive-dir",
                            str(snapshot),
                            "--publication-lock",
                            str(lock),
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )
            assert all(process.poll() is None for process in processes)
        results = [process.communicate(timeout=10) for process in processes]
        assert sorted(process.returncode for process in processes) == [0, 1], results
        winner = [source, second][
            next(i for i, process in enumerate(processes) if process.returncode == 0)
        ]
        assert target.read_bytes() == winner.read_bytes()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_late_rollback_preserves_another_publication(publication):
    guard, target, source, archive, lock = publication
    guard.pointer_transaction(target, archive, lock, snapshot=True)
    guard.pointer_transaction(target, archive, lock, source=source)
    newer = archive.with_name("newer-archive")
    guard.pointer_transaction(target, newer, lock, snapshot=True)
    source.write_bytes(b'{"version":"later"}\n')
    guard.pointer_transaction(target, newer, lock, source=source)
    with pytest.raises(ValueError, match="another publication"):
        guard.pointer_transaction(target, archive, lock, restore=True)
    assert target.read_bytes() == source.read_bytes()
    assert (archive / "previous").read_bytes() == b'{ "version": "old" }\r\n'


def test_archive_failure_prevents_pointer_write(publication, monkeypatch):
    guard, target, source, archive, lock = publication
    guard.pointer_transaction(target, archive, lock, snapshot=True)
    previous = target.read_bytes()
    monkeypatch.setattr(guard.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        guard.pointer_transaction(target, archive, lock, source=source)
    assert target.read_bytes() == previous


@pytest.mark.parametrize("later_writer", [False, True])
def test_failed_readback_only_restores_our_own_replacement(publication, monkeypatch, later_writer):
    guard, target, source, archive, lock = publication
    guard.pointer_transaction(target, archive, lock, snapshot=True)
    previous, incoming, external = target.read_bytes(), source.read_bytes(), b'{"external":true}\n'
    replace = guard._replace

    def failed_readback(path, content):
        replace(path, content)
        if content == incoming:
            if later_writer:
                path.write_bytes(external)
            raise OSError("readback unavailable")

    monkeypatch.setattr(guard, "_replace", failed_readback)
    with pytest.raises(OSError, match="readback unavailable"):
        guard.pointer_transaction(target, archive, lock, source=source)
    assert target.read_bytes() == (external if later_writer else previous)
    assert (archive / "replacement").read_bytes() == incoming


def test_changed_site_symlink_refuses_promotion(publication, tmp_path):
    guard, target, source, archive, lock = publication
    sites = [tmp_path / name for name in ("old-site", "new-site")]
    for site in sites:
        site.mkdir()
        (site / "pointer").write_bytes(target.read_bytes())
    live = tmp_path / "live"
    live.symlink_to(sites[0], target_is_directory=True)
    guard.pointer_transaction(live / "pointer", archive, lock, snapshot=True)
    live.unlink()
    live.symlink_to(sites[1], target_is_directory=True)
    with pytest.raises(ValueError, match="target or archived bytes changed"):
        guard.pointer_transaction(live / "pointer", archive, lock, source=source)
    assert (live / "pointer").read_bytes() == target.read_bytes()


def test_catalog_test_only_version_is_rejected_by_real_stable_preflight(tmp_path):
    workflow = (ROOT / "FHD/.github/workflows/release-desktop.yml").read_text()
    policy = workflow.split("python - <<'PY_POLICY'\n", 1)[1].split("          PY_POLICY", 1)[0]
    catalog = json.loads((ROOT / "FHD/config/download_release.json").read_bytes())
    path = tmp_path / "FHD/config/download_release.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(catalog))
    for version, rejected in (
        (catalog["windows_interim_release"]["version"], True),
        ("older", False),
    ):
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(policy)],
            cwd=tmp_path,
            env={"REQUESTED_VERSION": version},
            capture_output=True,
            text=True,
        )
        assert (result.returncode != 0) is rejected, result.stderr
