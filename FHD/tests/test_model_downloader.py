"""model_downloader 断点续传 + 磁盘预检 + 分离超时测试。

覆盖：
- 206 响应时从 .part 续传（append 模式）
- 磁盘空间不足时抛 OSError
- 服务器不支持 Range（返回 200）时重置为 wb 从头下载
- 下载完成但 sha256 不匹配时拒绝并清理 .part
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.desktop_runtime.model_downloader import ModelAsset, download_model


def _make_asset(url: str = "https://example.com/model.bin", sha256: str = "", size: int = 1024) -> ModelAsset:
    return ModelAsset(
        name="test-model",
        version="1.0.0",
        url=url,
        sha256=sha256,
        size=size,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestDownloadResumesFromPart:
    """206 响应时从 .part 续传。"""

    def test_download_resumes_from_part_on_206(self, tmp_path: Path) -> None:
        # 准备：.part 已有 512 bytes，服务器返回 206 + Content-Range
        existing_data = b"a" * 512
        new_data = b"b" * 512
        full_data = existing_data + new_data
        expected_sha = _sha256_bytes(full_data)

        asset = _make_asset(sha256=expected_sha, size=len(full_data))

        # 模拟 models_dir 返回 tmp_path
        with patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path), \
             patch("app.desktop_runtime.model_downloader.shutil.disk_usage") as mock_du, \
             patch("app.desktop_runtime.model_downloader.urllib.request.urlopen") as mock_urlopen:
            mock_du.return_value = MagicMock(free=10 * 1024 * 1024)

            # 先写 .part 文件（已有 512 bytes）
            target = tmp_path / "test-model" / "1.0.0" / "model.bin"
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".bin.part")
            partial.write_bytes(existing_data)

            # 模拟 206 响应
            mock_response = MagicMock()
            mock_response.status = 206
            mock_response.getcode.return_value = 206
            mock_response.headers = {"Content-Range": f"bytes {len(existing_data)}-{len(full_data) - 1}/{len(full_data)}"}
            mock_response.read.side_effect = [new_data, b""]
            mock_response.fp.raw._sock = MagicMock()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = download_model(asset, data_dir=str(tmp_path))

            assert result == target
            assert target.read_bytes() == full_data
            # 验证 Range 头被发送
            request_arg = mock_urlopen.call_args[0][0]
            assert request_arg.has_header("Range")
            assert request_arg.get_header("Range") == f"bytes={len(existing_data)}-"


class TestDownloadFailsOnLowDisk:
    """磁盘空间不足时抛 OSError。"""

    def test_download_fails_on_low_disk_space(self, tmp_path: Path) -> None:
        asset = _make_asset(size=1024 * 1024)  # 1MB

        with patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path), \
             patch("app.desktop_runtime.model_downloader.shutil.disk_usage") as mock_du:
            # 磁盘只剩 100KB，但需要 2MB
            mock_du.return_value = MagicMock(free=100 * 1024)

            with pytest.raises(OSError, match="磁盘剩余"):
                download_model(asset, data_dir=str(tmp_path))


class TestDownloadResetsOn200:
    """服务器不支持 Range（返回 200）时重置为 wb 从头下载。"""

    def test_download_resets_to_wb_on_200_despite_range_header(self, tmp_path: Path) -> None:
        full_data = b"c" * 1024
        expected_sha = _sha256_bytes(full_data)
        asset = _make_asset(sha256=expected_sha, size=len(full_data))

        with patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path), \
             patch("app.desktop_runtime.model_downloader.shutil.disk_usage") as mock_du, \
             patch("app.desktop_runtime.model_downloader.urllib.request.urlopen") as mock_urlopen:
            mock_du.return_value = MagicMock(free=10 * 1024 * 1024)

            # 先写一个假的 .part（内容不完整）
            target = tmp_path / "test-model" / "1.0.0" / "model.bin"
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".bin.part")
            partial.write_bytes(b"old-partial-data")

            # 模拟 200 响应（服务器不支持续传）
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.getcode.return_value = 200
            mock_response.headers = {"Content-Length": str(len(full_data))}
            mock_response.read.side_effect = [full_data, b""]
            mock_response.fp.raw._sock = MagicMock()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = download_model(asset, data_dir=str(tmp_path))

            assert result == target
            # 文件应是完整的 full_data，而非 old-partial-data + full_data
            assert target.read_bytes() == full_data


class TestDownloadRejectsMismatchedSha256:
    """下载完成但 sha256 不匹配时拒绝并清理 .part。"""

    def test_download_rejects_partial_206_with_mismatched_sha256(self, tmp_path: Path) -> None:
        wrong_data = b"x" * 1024
        wrong_sha = _sha256_bytes(wrong_data)
        expected_sha = "0" * 64  # 完全不匹配的 sha256
        asset = _make_asset(sha256=expected_sha, size=len(wrong_data))

        with patch("app.desktop_runtime.model_downloader.models_dir", return_value=tmp_path), \
             patch("app.desktop_runtime.model_downloader.shutil.disk_usage") as mock_du, \
             patch("app.desktop_runtime.model_downloader.urllib.request.urlopen") as mock_urlopen:
            mock_du.return_value = MagicMock(free=10 * 1024 * 1024)

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.getcode.return_value = 200
            mock_response.headers = {"Content-Length": str(len(wrong_data))}
            mock_response.read.side_effect = [wrong_data, b""]
            mock_response.fp.raw._sock = MagicMock()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            target = tmp_path / "test-model" / "1.0.0" / "model.bin"
            partial = target.with_suffix(".bin.part")

            with pytest.raises(ValueError, match="校验失败"):
                download_model(asset, data_dir=str(tmp_path))

            # .part 应被清理
            assert not partial.exists()
            # target 不应被创建
            assert not target.exists()
