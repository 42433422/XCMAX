from pathlib import Path

import pytest

from modstore_server.infrastructure.private_asset_storage import draft_asset_directory


def test_assets_and_preflight_share_external_runtime(monkeypatch, tmp_path):
    from modstore_server import employee_asset_pipeline as pipeline

    runtime = tmp_path / "private-runtime"
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(pipeline, "modstore_library_path", lambda: tmp_path / "library")
    ok, errors, paths = pipeline._preflight_scaffold_write_access(session_id="session-a", user_id=7)
    assert ok, errors
    result = pipeline.prepare_employee_assets(
        session_id="session-a",
        user_id=7,
        raw_files=[{"filename": "input.txt", "content": b"synthetic-only"}],
    )
    root = runtime / "employee_draft_assets" / "7" / "session-a"
    assert result["root"] == paths["draft_assets_root"] == str(root)
    assert (root / "00_input.txt").read_bytes() == b"synthetic-only"
    assert (root / "asset_manifest.json").is_file()


@pytest.mark.parametrize("session_id", ["..", "../other", "a/b", "a\\b", "/tmp/x", ""])
def test_invalid_session_cannot_delete_another_directory(tmp_path, session_id):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="session_id"):
        draft_asset_directory(user_id=1, session_id=session_id, repo_root=tmp_path)
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("user_id", [0, -1, True, "../other"])
def test_invalid_owner_is_rejected(tmp_path, user_id):
    with pytest.raises(ValueError, match="user_id"):
        draft_asset_directory(user_id=user_id, session_id="s1", repo_root=tmp_path)


def test_repository_and_symlink_destinations_are_rejected(monkeypatch, tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(checkout / "private"))
    with pytest.raises(ValueError, match="Git checkout"):
        draft_asset_directory(user_id=1, session_id="s1")
    assert not (checkout / "private").exists()
    runtime = tmp_path / "runtime"
    (runtime / "employee_draft_assets").mkdir(parents=True)
    (runtime / "employee_draft_assets" / "1").symlink_to(checkout, target_is_directory=True)
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime))
    with pytest.raises(ValueError, match="symlink"):
        draft_asset_directory(user_id=1, session_id="s1")


def test_replacing_a_session_preserves_other_owners(monkeypatch, tmp_path):
    from modstore_server.employee_asset_pipeline import prepare_employee_assets

    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    first = prepare_employee_assets(
        session_id="s1",
        user_id=1,
        raw_files=[{"filename": "old.txt", "content": b"old"}],
    )
    other = prepare_employee_assets(
        session_id="s1",
        user_id=2,
        raw_files=[{"filename": "keep.txt", "content": b"keep"}],
    )
    prepare_employee_assets(
        session_id="s1",
        user_id=1,
        raw_files=[{"filename": "new.txt", "content": b"new"}],
    )
    assert not (Path(first["root"]) / "00_old.txt").exists()
    assert (Path(first["root"]) / "00_new.txt").read_bytes() == b"new"
    assert (Path(other["root"]) / "00_keep.txt").read_bytes() == b"keep"
