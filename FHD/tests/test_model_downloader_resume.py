"""Model downloader resume, disk guard and integrity tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.desktop_runtime.model_downloader import ModelAsset, download_model


def _asset(data: bytes) -> ModelAsset:
    return ModelAsset(
        name="test-model",
        version="1.0.0",
        url="https://example.com/model.bin",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )


def _response(
    data: bytes,
    *,
    status: int,
    headers: dict[str, str],
) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.headers = headers
    response.read.side_effect = [data, b""]
    response.fp.raw._sock = MagicMock()
    return response


def test_download_resumes_valid_partial_response(tmp_path: Path) -> None:
    existing = b"a" * 512
    remainder = b"b" * 512
    asset = _asset(existing + remainder)
    target = tmp_path / asset.name / asset.version / "model.bin"
    target.parent.mkdir(parents=True)
    target.with_suffix(".bin.part").write_bytes(existing)
    response = _response(
        remainder,
        status=206,
        headers={"Content-Range": "bytes 512-1023/1024"},
    )

    with (
        patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path),
        patch(
            "app.desktop_runtime.model_downloader.shutil.disk_usage",
            return_value=MagicMock(free=100 * 1024 * 1024),
        ),
        patch(
            "app.desktop_runtime.model_downloader.urllib.request.urlopen",
            return_value=response,
        ) as urlopen,
    ):
        result = download_model(asset)

    assert result.read_bytes() == existing + remainder
    request = urlopen.call_args.args[0]
    assert request.get_header("Range") == "bytes=512-"
    response.fp.raw._sock.settimeout.assert_called_once_with(60.0)


def test_download_restarts_when_server_ignores_range(tmp_path: Path) -> None:
    complete = b"complete-model"
    asset = _asset(complete)
    target = tmp_path / asset.name / asset.version / "model.bin"
    target.parent.mkdir(parents=True)
    target.with_suffix(".bin.part").write_bytes(b"old")
    ignored = _response(complete, status=200, headers={"Content-Length": str(len(complete))})
    restarted = _response(
        complete,
        status=200,
        headers={"Content-Length": str(len(complete))},
    )

    with (
        patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path),
        patch(
            "app.desktop_runtime.model_downloader.shutil.disk_usage",
            return_value=MagicMock(free=100 * 1024 * 1024),
        ),
        patch(
            "app.desktop_runtime.model_downloader.urllib.request.urlopen",
            side_effect=[ignored, restarted],
        ) as urlopen,
    ):
        result = download_model(asset)

    assert result.read_bytes() == complete
    assert urlopen.call_count == 2
    assert urlopen.call_args_list[1].args[0].get_header("Range") is None


def test_download_rejects_insufficient_disk_space(tmp_path: Path) -> None:
    asset = _asset(b"x" * 1024)

    with (
        patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path),
        patch(
            "app.desktop_runtime.model_downloader.shutil.disk_usage",
            return_value=MagicMock(free=1),
        ),
    ):
        with pytest.raises(OSError, match="下载空间不足"):
            download_model(asset)


def test_download_removes_corrupt_partial(tmp_path: Path) -> None:
    expected = b"expected"
    asset = _asset(expected)
    target = tmp_path / asset.name / asset.version / "model.bin"
    response = _response(
        b"corrupt!",
        status=200,
        headers={"Content-Length": str(len(expected))},
    )

    with (
        patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path),
        patch(
            "app.desktop_runtime.model_downloader.shutil.disk_usage",
            return_value=MagicMock(free=100 * 1024 * 1024),
        ),
        patch(
            "app.desktop_runtime.model_downloader.urllib.request.urlopen",
            return_value=response,
        ),
    ):
        with pytest.raises(ValueError, match="校验失败"):
            download_model(asset)

    assert not target.exists()
    assert not target.with_suffix(".bin.part").exists()
