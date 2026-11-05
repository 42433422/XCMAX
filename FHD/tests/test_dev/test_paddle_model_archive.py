"""Real tar extraction boundary tests; no model download or external filesystem writes."""

from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "XCAGI/scripts/download_paddleocr_ch_models.py"
SPEC = importlib.util.spec_from_file_location("paddle_model_download_test_target", SCRIPT)
assert SPEC and SPEC.loader
models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(models)


def archive(tmp_path, name, *, kind=tarfile.REGTYPE, link=""):
    path = tmp_path / "model.tar"
    member = tarfile.TarInfo(name)
    member.type, member.linkname = kind, link
    data = b"model-data"
    member.size = len(data) if member.isfile() else 0
    with tarfile.open(path, "w") as handle:
        handle.addfile(member, io.BytesIO(data) if member.isfile() else None)
    return path


def test_regular_model_archive_extracts(tmp_path):
    models.extract_tar(archive(tmp_path, "model/inference.yml"), tmp_path / "target")
    assert (tmp_path / "target/model/inference.yml").read_bytes() == b"model-data"


@pytest.mark.parametrize("name", ["../outside", "model/../../outside"])
def test_traversal_cannot_overwrite_neighbor(tmp_path, name):
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    with pytest.raises(tarfile.FilterError):
        models.extract_tar(archive(tmp_path, name), tmp_path / "target")
    assert outside.read_bytes() == b"keep"


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_links_cannot_escape_target(tmp_path, kind):
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    with pytest.raises(tarfile.FilterError):
        models.extract_tar(
            archive(tmp_path, "escape", kind=kind, link="../outside"), tmp_path / "target"
        )
    assert outside.read_bytes() == b"keep"


def test_existing_symlink_cannot_redirect_extraction(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "inference.yml").write_bytes(b"keep")
    target = tmp_path / "target"
    target.mkdir()
    (target / "model").symlink_to(outside, target_is_directory=True)
    with pytest.raises(tarfile.FilterError):
        models.extract_tar(archive(tmp_path, "model/inference.yml"), target)
    assert (outside / "inference.yml").read_bytes() == b"keep"


def test_absolute_member_is_confined_to_target(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    models.extract_tar(archive(tmp_path, str(outside)), tmp_path / "target")
    assert outside.read_bytes() == b"keep"


@pytest.mark.parametrize("kind", [tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE])
def test_special_files_are_rejected(tmp_path, kind):
    with pytest.raises(tarfile.FilterError):
        models.extract_tar(archive(tmp_path, "special", kind=kind), tmp_path / "target")
    assert not (tmp_path / "target/special").exists()


def test_no_safe_filter_fails_closed_before_extraction(tmp_path, monkeypatch):
    path = archive(tmp_path, "model/inference.yml")
    monkeypatch.delattr(tarfile, "data_filter")
    with pytest.raises(RuntimeError, match="安全解包过滤器"):
        models.extract_tar(path, tmp_path / "target")
    assert not (tmp_path / "target").exists()


def test_cached_unsafe_archive_reports_failure_without_download(tmp_path, monkeypatch, capsys):
    target = tmp_path / "target"
    cache = target / "_downloads"
    cache.mkdir(parents=True)
    stored = cache / models.MODELS[0][0]
    stored.write_bytes(archive(tmp_path, "../outside").read_bytes())
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    monkeypatch.setattr(models.sys, "argv", ["download-models", "--dir", str(target)])
    monkeypatch.setattr(models, "download_file", lambda *args: pytest.fail("must use cached tar"))
    assert models.main() == 1
    assert "解压失败" in capsys.readouterr().err
    assert stored.is_file()
    assert outside.read_bytes() == b"keep"
