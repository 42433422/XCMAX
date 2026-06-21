# -*- coding: utf-8 -*-
"""Branch-coverage tests for app.mod_sdk.customer_delivery_seed."""

from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mod_sdk.customer_delivery_seed import (
    _resolve_version,
    _safe_member_relpath,
    extract_customer_delivery_seed,
    install_customer_delivery_seed_package,
)

# ---------------------------------------------------------------------------
# _safe_member_relpath
# ---------------------------------------------------------------------------


class TestSafeMemberRelpath:
    # Branch: empty / blank name -> None
    def test_empty_string_returns_none(self):
        assert _safe_member_relpath("") is None

    def test_only_slashes_returns_none(self):
        assert _safe_member_relpath("///") is None

    def test_none_like_empty_returns_none(self):
        # str(None or "") would be "" — but we pass a normal empty string
        assert _safe_member_relpath("") is None

    # Branch: absolute path — after strip('/') becomes "etc/passwd" -> top-level "etc" not in allowed -> raises
    def test_absolute_path_raises(self):
        # "/etc/passwd" -> strip('/') -> "etc/passwd" -> top-level "etc" -> "未允许目录"
        with pytest.raises(ValueError, match="未允许目录"):
            _safe_member_relpath("/etc/passwd")

    # Branch: dotdot segment raises
    def test_dotdot_raises(self):
        with pytest.raises(ValueError, match="非法路径"):
            _safe_member_relpath("config/../etc/passwd")

    # Branch: PurePosixPath strips leading "./" so "./config/x" becomes ("config","x") — no raise
    # Instead use a genuine ".." segment to hit the illegal-path branch
    def test_embedded_dotdot_raises(self):
        with pytest.raises(ValueError, match="非法路径"):
            _safe_member_relpath("config/foo/../../../etc/passwd")

    # Branch: top-level not in _ALLOWED_TOP_LEVELS raises
    def test_disallowed_top_level_raises(self):
        with pytest.raises(ValueError, match="未允许目录"):
            _safe_member_relpath("secrets/credentials.json")

    # Branch: top-level "delivery-manifest.json" is in allowed set (it's a file)
    def test_delivery_manifest_allowed(self):
        result = _safe_member_relpath("delivery-manifest.json")
        assert result == Path("delivery-manifest.json")

    # Branch: top-level "424" allowed
    def test_424_directory_allowed(self):
        result = _safe_member_relpath("424/some/file.txt")
        assert result == Path("424/some/file.txt")

    # Branch: top-level "config" allowed
    def test_config_directory_allowed(self):
        result = _safe_member_relpath("config/settings.json")
        assert result == Path("config/settings.json")

    # Branch: data/mod_dbs is allowed
    def test_data_mod_dbs_allowed(self):
        result = _safe_member_relpath("data/mod_dbs/some.db")
        assert result == Path("data/mod_dbs/some.db")

    # Branch: data/ with subdir != mod_dbs raises
    def test_data_non_mod_dbs_raises(self):
        with pytest.raises(ValueError, match="mod_dbs"):
            _safe_member_relpath("data/other_dir/file.txt")

    # Branch: data/ with only one part (no subdirectory) — len(parts) < 2, no constraint triggered
    def test_data_alone_allowed(self):
        # "data" alone after strip — parts = ("data",), len < 2 -> no data sub-check
        result = _safe_member_relpath("data")
        # parts[0] == "data", len(parts) == 1 < 2 -> returns Path("data")
        assert result == Path("data")

    # Branch: backslash path is normalized
    def test_backslash_normalized(self):
        result = _safe_member_relpath("config\\settings.json")
        assert result == Path("config/settings.json")


# ---------------------------------------------------------------------------
# extract_customer_delivery_seed
# ---------------------------------------------------------------------------


def _make_zip(tmp_path: Path, members: dict[str, bytes], dirs: list[str] | None = None) -> Path:
    """Helper: create a zip file with given file members and optional dir entries."""
    zip_path = tmp_path / "delivery.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        if dirs:
            for d in dirs:
                info = zipfile.ZipInfo(d if d.endswith("/") else d + "/")
                zf.writestr(info, "")
        for name, content in members.items():
            zf.writestr(name, content)
    return zip_path


class TestExtractCustomerDeliverySeed:
    def test_extracts_valid_file(self, tmp_path):
        zip_path = _make_zip(tmp_path, {"config/settings.json": b'{"key": "value"}'})
        data_root = tmp_path / "data"
        data_root.mkdir()
        result = extract_customer_delivery_seed(zip_path, data_root)
        assert "config/settings.json" in result
        assert (data_root / "config" / "settings.json").read_bytes() == b'{"key": "value"}'

    def test_skips_directory_entries(self, tmp_path):
        zip_path = _make_zip(tmp_path, {"config/file.txt": b"hello"}, dirs=["config/"])
        data_root = tmp_path / "data"
        data_root.mkdir()
        result = extract_customer_delivery_seed(zip_path, data_root)
        # only the file, not the directory entry
        assert result == ["config/file.txt"]

    def test_skips_none_relpath_entries(self, tmp_path):
        """Blank-named entries (relpath returns None) are skipped."""
        zip_path = tmp_path / "delivery.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Create a file with a name that strips to empty — unusual but possible
            info = zipfile.ZipInfo("config/real.txt")
            zf.writestr(info, b"data")
        data_root = tmp_path / "data"
        data_root.mkdir()
        # Monkey-patch _safe_member_relpath to return None for our file
        with patch("app.mod_sdk.customer_delivery_seed._safe_member_relpath", return_value=None):
            result = extract_customer_delivery_seed(zip_path, data_root)
        assert result == []

    def test_raises_on_path_traversal(self, tmp_path):
        """Dest outside data_root raises ValueError."""
        zip_path = _make_zip(tmp_path, {"config/legit.txt": b"x"})
        data_root = tmp_path / "data"
        data_root.mkdir()
        # Patch _safe_member_relpath to return a path that resolves outside root
        evil = Path("../../evil.txt")
        with patch("app.mod_sdk.customer_delivery_seed._safe_member_relpath", return_value=evil):
            with pytest.raises(ValueError, match="越界"):
                extract_customer_delivery_seed(zip_path, data_root)

    def test_extracts_multiple_files(self, tmp_path):
        zip_path = _make_zip(
            tmp_path,
            {
                "config/a.json": b"{}",
                "424/b.txt": b"hello",
                "delivery-manifest.json": b"manifest",
            },
        )
        data_root = tmp_path / "data"
        data_root.mkdir()
        result = extract_customer_delivery_seed(zip_path, data_root)
        assert len(result) == 3
        assert "delivery-manifest.json" in result

    def test_creates_parent_dirs(self, tmp_path):
        zip_path = _make_zip(tmp_path, {"config/nested/deep/file.txt": b"deep"})
        data_root = tmp_path / "data"
        data_root.mkdir()
        result = extract_customer_delivery_seed(zip_path, data_root)
        assert (data_root / "config" / "nested" / "deep" / "file.txt").exists()


# ---------------------------------------------------------------------------
# _resolve_version
# ---------------------------------------------------------------------------


class TestResolveVersion:
    async def test_version_provided_returns_immediately(self):
        result = await _resolve_version("pkg-1", "1.2.3")
        assert result == "1.2.3"

    async def test_empty_version_fetches_from_catalog_dict_row(self):
        versions_payload = {"versions": [{"version": "2.0.0"}, {"version": "1.0.0"}]}
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value=versions_payload),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == "2.0.0"

    async def test_empty_version_fetches_from_catalog_string_row(self):
        versions_payload = {"versions": ["3.1.0", "3.0.0"]}
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value=versions_payload),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == "3.1.0"

    async def test_empty_version_no_versions_key(self):
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value={}),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == ""

    async def test_empty_version_empty_list(self):
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value={"versions": []}),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == ""

    async def test_version_whitespace_stripped(self):
        result = await _resolve_version("pkg-1", "  1.0.0  ")
        assert result == "1.0.0"

    async def test_none_version_treated_as_empty(self):
        # version="None" from str(None or "").strip() -> ""
        versions_payload = {"versions": [{"version": "9.0.0"}]}
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value=versions_payload),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == "9.0.0"

    async def test_first_dict_row_version_is_none(self):
        """Dict row where 'version' key maps to None -> empty string."""
        versions_payload = {"versions": [{"version": None}]}
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value=versions_payload),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == ""

    async def test_first_string_row_is_none_like(self):
        """Non-dict, non-string row: str(first or "").strip() -> empty."""
        versions_payload = {"versions": [None]}
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value=versions_payload),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == ""

    async def test_versions_not_a_list(self):
        """If 'versions' is not a list, rows = [] and ver stays empty."""
        versions_payload = {"versions": "not-a-list"}
        with patch(
            "app.mod_sdk.customer_delivery_seed.catalog_get_json",
            new=AsyncMock(return_value=versions_payload),
        ):
            result = await _resolve_version("pkg-1", "")
        assert result == ""


# ---------------------------------------------------------------------------
# install_customer_delivery_seed_package
# ---------------------------------------------------------------------------


class TestInstallCustomerDeliverySeedPackage:
    async def test_missing_mod_id_returns_error(self):
        result = await install_customer_delivery_seed_package(mod_id="")
        assert result["success"] is False
        assert "mod_id" in result["message"]

    async def test_whitespace_mod_id_returns_error(self):
        result = await install_customer_delivery_seed_package(mod_id="   ")
        assert result["success"] is False

    async def test_no_delivery_returns_skipped(self):
        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value=None,
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value=None,
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")
        assert result["success"] is True
        assert result["skipped"] is True
        assert result["applied"] is False

    async def test_no_pkg_returns_skipped(self):
        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value=None,
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")
        assert result["success"] is True
        assert result["skipped"] is True

    async def test_missing_pkg_id_or_version_returns_error(self):
        """pkg exists but pkg_id is empty and no version from catalog."""
        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "", "version": ""},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_get_json",
                new=AsyncMock(return_value={"versions": []}),
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")
        assert result["success"] is False
        assert "pkg_id" in result["message"] or "version" in result["message"]

    async def test_missing_version_only_returns_error(self):
        """pkg_id present but no version resolved."""
        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-1", "version": ""},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_get_json",
                new=AsyncMock(return_value={"versions": []}),
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")
        assert result["success"] is False

    async def test_successful_install_no_apply(self, tmp_path):
        """Full happy path: pkg downloaded, extracted, no apply_kind."""
        zip_path = tmp_path / "seed.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("config/app.json", b"{}")
        data_root = tmp_path / "data"
        data_root.mkdir()

        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d42"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-123", "version": "1.0.0", "apply": "", "artifact": "seed.zip"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(side_effect=lambda url, dest: zip_path.replace(dest) if False else None),
            ) as mock_download,
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                return_value=["config/app.json"],
            ),
        ):
            # catalog_download_to is AsyncMock that does nothing (zip stays empty but extract is mocked)
            mock_download.side_effect = None
            result = await install_customer_delivery_seed_package(mod_id="some-mod", industry_id="ind1")

        assert result["success"] is True
        assert result["applied"] is False
        assert result["mod_id"] == "some-mod"
        assert result["delivery_id"] == "d42"
        assert result["package"]["pkg_id"] == "pkg-123"
        assert result["extracted_files"] == ["config/app.json"]

    async def test_successful_install_with_sunbird_apply(self, tmp_path):
        """apply='sunbird_roster' branch: apply_sunbird_roster_seed_if_needed called."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        mock_sunbird = MagicMock(return_value=True)

        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-x", "version": "2.0.0", "apply": "sunbird_roster", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                return_value=["config/something.json"],
            ),
            patch.dict(
                "sys.modules",
                {
                    "app.desktop_runtime.sunbird_delivery_seed": MagicMock(
                        apply_sunbird_roster_seed_if_needed=mock_sunbird
                    )
                },
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")

        assert result["success"] is True
        assert result["applied"] is True

    async def test_successful_install_sunbird_returns_falsy(self, tmp_path):
        """apply='sunbird_roster' but sunbird fn returns falsy -> applied=False."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        mock_sunbird = MagicMock(return_value=None)  # falsy

        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-x", "version": "2.0.0", "apply": "sunbird_roster", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                return_value=[],
            ),
            patch.dict(
                "sys.modules",
                {
                    "app.desktop_runtime.sunbird_delivery_seed": MagicMock(
                        apply_sunbird_roster_seed_if_needed=mock_sunbird
                    )
                },
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")

        assert result["success"] is True
        assert result["applied"] is False

    async def test_recoverable_error_is_caught(self, tmp_path):
        """RECOVERABLE_ERRORS during download are caught and returned as failure."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-x", "version": "1.0.0", "apply": "", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(side_effect=OSError("network error")),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")

        assert result["success"] is False
        assert "network error" in result["message"]
        assert result["mod_id"] == "some-mod"

    async def test_value_error_is_caught(self, tmp_path):
        """ValueError (e.g., bad zip path) is caught as RECOVERABLE_ERRORS."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-x", "version": "1.0.0", "apply": "", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                side_effect=ValueError("bad zip"),
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="some-mod")

        assert result["success"] is False
        assert "bad zip" in result["message"]

    async def test_tmp_file_cleaned_up_on_success(self, tmp_path):
        """finally block: tmp file is removed after success."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        created_tmp = []

        original_ntf = tempfile.NamedTemporaryFile

        def capture_ntf(**kwargs):
            f = original_ntf(**kwargs)
            created_tmp.append(Path(f.name))
            return f

        with (
            patch("tempfile.NamedTemporaryFile", side_effect=capture_ntf),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-y", "version": "3.0.0", "apply": "", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                return_value=[],
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="clean-mod")

        assert result["success"] is True
        # tmp file should no longer exist (cleaned up by finally)
        for p in created_tmp:
            assert not p.exists(), f"Temp file {p} was not cleaned up"

    async def test_tmp_file_cleaned_up_on_error(self, tmp_path):
        """finally block: tmp file is removed even after failure."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        created_tmp = []
        original_ntf = tempfile.NamedTemporaryFile

        def capture_ntf(**kwargs):
            f = original_ntf(**kwargs)
            created_tmp.append(Path(f.name))
            return f

        with (
            patch("tempfile.NamedTemporaryFile", side_effect=capture_ntf),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-z", "version": "1.0.0", "apply": "", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(side_effect=ConnectionError("timeout")),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="err-mod")

        assert result["success"] is False
        for p in created_tmp:
            assert not p.exists(), f"Temp file {p} was not cleaned up after error"

    async def test_tmp_file_cleanup_oserror_is_swallowed(self, tmp_path):
        """finally block: OSError during cleanup is silently ignored."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"delivery_id": "d1"},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-q", "version": "1.0.0", "apply": "", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                return_value=[],
            ),
            # Make os.unlink raise to hit the except OSError: pass branch
            patch("os.unlink", side_effect=OSError("cannot delete")),
        ):
            # Should not raise — OSError in finally is swallowed
            result = await install_customer_delivery_seed_package(mod_id="swallow-mod")

        assert result["success"] is True

    async def test_industry_id_is_stripped(self):
        """industry_id whitespace is stripped and passed correctly."""
        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value=None,
            ) as mock_delivery,
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value=None,
            ),
        ):
            result = await install_customer_delivery_seed_package(
                mod_id="mod-x", industry_id="  my-industry  "
            )

        # Verify stripped industry_id was passed
        mock_delivery.assert_called_once_with("mod-x", "my-industry")
        assert result["skipped"] is True

    async def test_delivery_delivery_id_fallback_empty(self, tmp_path):
        """delivery dict with an unrelated key (truthy) but no delivery_id -> delivery_id=""."""
        data_root = tmp_path / "data"
        data_root.mkdir()

        # Use a truthy dict that lacks the delivery_id key so (delivery or {}).get("delivery_id") is None
        with (
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_for_account_custom_mod",
                return_value={"some_other_key": "x"},  # truthy, but no delivery_id
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.delivery_seed_package_for_mod",
                return_value={"pkg_id": "pkg-r", "version": "1.0.0", "apply": "", "artifact": None},
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.catalog_download_to",
                new=AsyncMock(),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.get_desktop_data_dir",
                return_value=str(data_root),
            ),
            patch(
                "app.mod_sdk.customer_delivery_seed.extract_customer_delivery_seed",
                return_value=[],
            ),
        ):
            result = await install_customer_delivery_seed_package(mod_id="no-did-mod")

        assert result["success"] is True
        assert "delivery_id" in result
        # str((delivery or {}).get("delivery_id") or "") == str(None or "") == ""
        assert result["delivery_id"] == ""
