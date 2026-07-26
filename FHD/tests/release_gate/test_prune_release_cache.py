from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.deploy.prune_release_cache import prune_backups, prune_release_cache


def _touch(path: Path, timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (timestamp, timestamp))


def test_prunes_old_releases_and_abandoned_partials_after_success(tmp_path: Path) -> None:
    release_dir = tmp_path / "update" / "server"
    for index in range(6):
        _touch(
            release_dir / f"fhd-full-1.0.0-{index:012x}.tar.gz",
            1_000 + index,
        )
    current = "fhd-full-1.0.0-000000000000.tar.gz"
    _touch(release_dir / "fhd-full-1.0.0-deadbeef0000.tar.gz.part", 1)

    result = prune_release_cache(
        release_dir,
        current_artifact=current,
        retain_releases=2,
        part_max_age_hours=1,
        now=10_000,
    )

    assert (release_dir / current).is_file()
    assert len(result["removed_releases"]) == 3
    assert result["removed_partials"] == ["fhd-full-1.0.0-deadbeef0000.tar.gz.part"]


def test_prunes_only_named_backup_directories(tmp_path: Path) -> None:
    backup_dir = tmp_path / "fhd" / "backups"
    for index in range(5):
        path = backup_dir / f"pre-2026072{index}-010203"
        path.mkdir(parents=True)
        os.utime(path, (1_000 + index, 1_000 + index))
    unrelated = backup_dir / "manual-keep"
    unrelated.mkdir()

    removed = prune_backups(backup_dir, retain_backups=2)

    assert len(removed) == 3
    assert unrelated.is_dir()


def test_rejects_broad_cleanup_target() -> None:
    with pytest.raises(ValueError, match="broad cleanup"):
        prune_release_cache("/", current_artifact="fhd-full-1.0.0-deadbeef0000.tar.gz")
