"""Hostile archives must not mutate an existing library before validation."""

from __future__ import annotations

import json
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from modman import store


def manifest(mid="safe"):
    return {
        "id": mid,
        "name": "Synthetic",
        "version": "1.0.0",
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {"routes": "frontend/routes.js"},
    }


def archive(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return path


@pytest.fixture
def protected_library(tmp_path, monkeypatch):
    library = tmp_path / "library"
    old = library / "safe"
    old.mkdir(parents=True)
    (old / "manifest.json").write_text(json.dumps(manifest()))
    (old / "original.txt").write_text("untouched")
    real_remove = shutil.rmtree
    protected = {library.resolve(), library.parent.resolve(), old.resolve()}

    def guarded_remove(path, *args, **kwargs):
        assert Path(path).resolve() not in protected, "attempted to delete pre-existing data"
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", guarded_remove)
    yield library
    assert (old / "original.txt").read_text() == "untouched"


@pytest.mark.parametrize(
    "member",
    [
        "../manifest.json",
        "/manifest.json",
        "./manifest.json",
        "safe/../escape.txt",
        "safe//ambiguous.txt",
        "safe/./ambiguous.txt",
        "safe/back\\slash.txt",
        "safe/C:stream",
        "safe/CON.txt",
        "safe/trailing. ",
    ],
)
def test_rejects_unsafe_paths_without_deleting_old_data(tmp_path, protected_library, member):
    entries = [(member, "invalid")]
    if member.startswith("safe/"):
        entries.insert(0, ("safe/manifest.json", json.dumps(manifest())))
    source = archive(tmp_path / "bad.zip", entries)
    with pytest.raises(ValueError):
        store.import_zip(source, protected_library)
    assert sorted(path.name for path in protected_library.iterdir()) == ["safe"]


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        json.dumps({"id": "other"}),
        json.dumps({"id": "safe", "name": "", "version": "1"}),
    ],
)
def test_bad_manifest_does_not_destroy_existing_version(tmp_path, protected_library, payload):
    source = archive(tmp_path / "bad.zip", [("safe/manifest.json", payload)])
    with pytest.raises(ValueError):
        store.import_zip(source, protected_library)


def test_symlink_member_is_rejected_before_mutation(tmp_path, protected_library):
    link = zipfile.ZipInfo("safe/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    source = archive(
        tmp_path / "link.zip",
        [("safe/manifest.json", json.dumps(manifest())), (link, "../../outside")],
    )
    with pytest.raises(ValueError):
        store.import_zip(source, protected_library)


def test_valid_import_and_replace_false(tmp_path):
    library = tmp_path / "library"
    source = archive(
        tmp_path / "good.zip",
        [("safe/manifest.json", json.dumps(manifest())), ("safe/readme.txt", "new")],
    )
    destination = store.import_zip(source, library, replace=False)
    assert destination == library / "safe"
    assert (destination / "readme.txt").read_text() == "new"
    with pytest.raises(FileExistsError):
        store.import_zip(source, library, replace=False)
    assert (destination / "readme.txt").read_text() == "new"


@pytest.mark.parametrize(
    "members",
    [
        ["safe/x", "safe/X"],
        ["safe/x", "safe/x/y"],
        ["safe/CONIN$", "safe/ok"],
        ["safe/COM¹.txt", "safe/ok"],
        ["safe/x?.txt", "safe/ok"],
        ["safe/con .txt", "safe/ok"],
    ],
)
def test_cross_platform_aliases_and_file_parents_are_rejected(tmp_path, protected_library, members):
    entries = [("safe/manifest.json", json.dumps(manifest()))] + [(name, "x") for name in members]
    with pytest.raises(ValueError):
        store.import_zip(archive(tmp_path / "bad.zip", entries), protected_library)


def test_duplicate_member_is_rejected(tmp_path, protected_library):
    with pytest.warns(UserWarning, match="Duplicate name"):
        source = archive(
            tmp_path / "duplicate.zip",
            [
                ("safe/manifest.json", json.dumps(manifest())),
                ("safe/a", "first"),
                ("safe/a", "second"),
            ],
        )
    with pytest.raises(ValueError):
        store.import_zip(source, protected_library)


@pytest.mark.parametrize("limit", ["MAX_FILES", "MAX_UNPACKED_BYTES", "MAX_MANIFEST_BYTES"])
def test_resource_limits_fail_before_creating_library(tmp_path, monkeypatch, limit):
    from modman import archive_import

    monkeypatch.setattr(archive_import, limit, 1)
    source = archive(
        tmp_path / "big.zip", [("safe/manifest.json", json.dumps(manifest())), ("safe/a", "x")]
    )
    library = tmp_path / "library"
    with pytest.raises(ValueError):
        store.import_zip(source, library)
    assert not library.exists()


def test_existing_destination_symlink_is_never_followed(tmp_path):
    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (library / "safe").symlink_to(outside, target_is_directory=True)
    source = archive(tmp_path / "good.zip", [("safe/manifest.json", json.dumps(manifest()))])
    with pytest.raises(ValueError):
        store.import_zip(source, library)
    assert (library / "safe").is_symlink()
    assert (outside / "keep.txt").read_text() == "keep"


def test_publication_failure_restores_previous_directory(tmp_path, monkeypatch):
    from modman import archive_import

    library = tmp_path / "library"
    previous = library / "safe"
    previous.mkdir(parents=True)
    (previous / "keep.txt").write_text("old")
    source = archive(tmp_path / "good.zip", [("safe/manifest.json", json.dumps(manifest()))])
    real_replace = archive_import.os.replace

    def fail_publication(src, dest):
        if Path(src).parent.name == "payload":
            raise OSError("synthetic publication failure")
        return real_replace(src, dest)

    monkeypatch.setattr(archive_import.os, "replace", fail_publication)
    with pytest.raises(OSError, match="synthetic"):
        store.import_zip(source, library)
    assert (previous / "keep.txt").read_text() == "old"
    assert not list(library.glob(".mod-import-*/"))


def test_failed_rollback_retains_previous_data_for_recovery(tmp_path, monkeypatch):
    from modman import archive_import

    library = tmp_path / "library"
    previous = library / "safe"
    previous.mkdir(parents=True)
    (previous / "keep.txt").write_text("old")
    source = archive(tmp_path / "good.zip", [("safe/manifest.json", json.dumps(manifest()))])
    real_replace = archive_import.os.replace

    def fail_publish_and_rollback(src, dest):
        if Path(src).parent.name == "payload" or Path(src).name == "previous":
            raise OSError("synthetic filesystem failure")
        return real_replace(src, dest)

    monkeypatch.setattr(archive_import.os, "replace", fail_publish_and_rollback)
    with pytest.raises(RuntimeError, match="旧版本保留"):
        store.import_zip(source, library)
    backups = list(library.glob(".mod-import-*/previous/keep.txt"))
    assert len(backups) == 1 and backups[0].read_text() == "old"


def test_valid_replace_replaces_only_target(tmp_path):
    library = tmp_path / "library"
    previous = library / "safe"
    previous.mkdir(parents=True)
    (previous / "old.txt").write_text("old")
    (library / "untouched.txt").write_text("neighbor")
    source = archive(
        tmp_path / "good.zip",
        [("safe/manifest.json", json.dumps(manifest())), ("safe/new.txt", "new")],
    )
    assert store.import_zip(source, library) == previous
    assert not (previous / "old.txt").exists()
    assert (previous / "new.txt").read_text() == "new"
    assert (library / "untouched.txt").read_text() == "neighbor"


def _import_in_process(source, library, start, results):
    start.wait(timeout=15)
    try:
        store.import_zip(Path(source), Path(library), replace=False)
    except FileExistsError:
        results.put("exists")
    except (OSError, ValueError, RuntimeError) as exc:
        results.put(type(exc).__name__ + ": " + str(exc))
    else:
        results.put("ok")


def test_two_processes_cannot_both_claim_the_same_new_id(tmp_path):
    import multiprocessing

    source = archive(tmp_path / "good.zip", [("safe/manifest.json", json.dumps(manifest()))])
    library = tmp_path / "library"
    context = multiprocessing.get_context("spawn")
    start, results = context.Barrier(2), context.Queue()
    processes = [
        context.Process(target=_import_in_process, args=(str(source), str(library), start, results))
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sorted(outcomes) == ["exists", "ok"]
        assert json.loads((library / "safe/manifest.json").read_text())["id"] == "safe"
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()


@pytest.mark.parametrize("phase", ["restore", "after_backup_move", "publish"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interruption_never_cleans_the_only_old_copy(tmp_path, monkeypatch, phase, interruption):
    from modman import archive_import

    library = tmp_path / "library"
    previous = library / "safe"
    previous.mkdir(parents=True)
    (previous / "keep.txt").write_text("old")
    source = archive(tmp_path / "good.zip", [("safe/manifest.json", json.dumps(manifest()))])
    real_replace = archive_import.os.replace

    def interrupted_replace(src, dest):
        if phase == "publish" and Path(src).parent.name == "payload":
            raise interruption("synthetic interrupted publication")
        if phase == "after_backup_move" and Path(dest).name == "previous":
            real_replace(src, dest)
            raise interruption("synthetic interruption after backup move")
        if phase == "restore" and Path(src).parent.name == "payload":
            raise OSError("synthetic publish failure")
        if phase == "restore" and Path(src).name == "previous":
            raise interruption("synthetic interrupted recovery")
        return real_replace(src, dest)

    monkeypatch.setattr(archive_import.os, "replace", interrupted_replace)
    with pytest.raises(interruption):
        store.import_zip(source, library)
    copies = list(library.glob(".mod-import-*/previous/keep.txt"))
    assert len(copies) == 1 and copies[0].read_text() == "old"
