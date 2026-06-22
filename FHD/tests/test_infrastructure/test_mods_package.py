"""Tests for app.infrastructure.mods.package — MOD packaging, signing, verification."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.package import (
    ModPackage,
    ModPackageError,
    ModSignatureError,
    compute_directory_hash,
    compute_file_hash,
)

# ---------------------------------------------------------------------------
# compute_file_hash
# ---------------------------------------------------------------------------


class TestComputeFileHash:
    """compute_file_hash() — 计算文件哈希"""

    def test_sha256_hash(self, tmp_path):
        """SHA256 哈希计算"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = compute_file_hash(str(f))
        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex digest length

    def test_md5_hash(self, tmp_path):
        """MD5 哈希计算"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = compute_file_hash(str(f), algorithm="md5")
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex digest length

    def test_empty_file(self, tmp_path):
        """空文件哈希"""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        result = compute_file_hash(str(f))
        assert isinstance(result, str)
        assert len(result) == 64

    def test_binary_file(self, tmp_path):
        """二进制文件哈希"""
        f = tmp_path / "binary.bin"
        f.write_bytes(bytes(range(256)))
        result = compute_file_hash(str(f))
        assert isinstance(result, str)

    def test_deterministic(self, tmp_path):
        """相同内容产生相同哈希"""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("same content", encoding="utf-8")
        f2.write_text("same content", encoding="utf-8")
        assert compute_file_hash(str(f1)) == compute_file_hash(str(f2))

    def test_different_content_different_hash(self, tmp_path):
        """不同内容产生不同哈希"""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A", encoding="utf-8")
        f2.write_text("content B", encoding="utf-8")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))


# ---------------------------------------------------------------------------
# compute_directory_hash
# ---------------------------------------------------------------------------


class TestComputeDirectoryHash:
    """compute_directory_hash() — 计算目录哈希"""

    def test_basic_directory_hash(self, tmp_path):
        """基本目录哈希"""
        (tmp_path / "file1.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("world", encoding="utf-8")
        result = compute_directory_hash(str(tmp_path))
        assert isinstance(result, str)
        assert len(result) == 64

    def test_ignores_dotfiles(self, tmp_path):
        """忽略以 . 开头的文件"""
        (tmp_path / "visible.txt").write_text("data", encoding="utf-8")
        (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
        result_with = compute_directory_hash(str(tmp_path))

        # Remove hidden file and compute again — should be same
        os.remove(str(tmp_path / ".hidden"))
        result_without = compute_directory_hash(str(tmp_path))
        assert result_with == result_without

    def test_empty_directory(self, tmp_path):
        """空目录哈希"""
        result = compute_directory_hash(str(tmp_path))
        assert isinstance(result, str)
        assert len(result) == 64

    def test_subdirectory_files_included(self, tmp_path):
        """子目录中的文件被包含"""
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content", encoding="utf-8")
        result = compute_directory_hash(str(tmp_path))
        assert isinstance(result, str)

    def test_deterministic(self, tmp_path):
        """相同内容产生相同哈希"""
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")
        h1 = compute_directory_hash(str(tmp_path))
        h2 = compute_directory_hash(str(tmp_path))
        assert h1 == h2


# ---------------------------------------------------------------------------
# ModPackage — __init__
# ---------------------------------------------------------------------------


class TestModPackageInit:
    """ModPackage.__init__() — 初始化验证"""

    def test_valid_mod_directory(self, tmp_path):
        """有效 MOD 目录初始化"""
        manifest = {"id": "test-mod", "version": "1.0.0", "name": "Test MOD"}
        (tmp_path / "Manifest.json").write_text(  # case-sensitive
            json.dumps(manifest), encoding="utf-8"
        )
        # Rename to manifest.json (lowercase)
        os.rename(str(tmp_path / "Manifest.json"), str(tmp_path / "manifest.json"))

        pkg = ModPackage(str(tmp_path))
        assert pkg.mod_id == "test-mod"
        assert pkg.version == "1.0.0"

    def test_missing_directory_raises(self, tmp_path):
        """目录不存在时抛出 ModPackageError"""
        with pytest.raises(ModPackageError, match="MOD 目录不存在"):
            ModPackage(str(tmp_path / "nonexistent"))

    def test_missing_manifest_raises(self, tmp_path):
        """manifest.json 不存在时抛出 ModPackageError"""
        with pytest.raises(ModPackageError, match="manifest.json 不存在"):
            ModPackage(str(tmp_path))

    def test_missing_id_raises(self, tmp_path):
        """manifest.json 缺少 id 字段时抛出 ModPackageError"""
        (tmp_path / "manifest.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
        with pytest.raises(ModPackageError, match="缺少必填字段 'id'"):
            ModPackage(str(tmp_path))

    def test_empty_id_raises(self, tmp_path):
        """id 为空字符串时抛出 ModPackageError"""
        (tmp_path / "manifest.json").write_text(
            json.dumps({"id": "", "version": "1.0.0"}), encoding="utf-8"
        )
        with pytest.raises(ModPackageError, match="缺少必填字段 'id'"):
            ModPackage(str(tmp_path))

    def test_default_version(self, tmp_path):
        """version 缺失时默认 1.0.0"""
        (tmp_path / "manifest.json").write_text(json.dumps({"id": "test-mod"}), encoding="utf-8")
        pkg = ModPackage(str(tmp_path))
        assert pkg.version == "1.0.0"


# ---------------------------------------------------------------------------
# ModPackage — create_package
# ---------------------------------------------------------------------------


class TestCreatePackage:
    """ModPackage.create_package() — 创建 MOD ZIP 包"""

    def _make_mod_dir(self, tmp_path):
        """创建测试用 MOD 目录"""
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        manifest = {"id": "my-mod", "version": "2.0.0", "name": "My MOD"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (mod_dir / "main.py").write_text("print('hello')", encoding="utf-8")
        (mod_dir / "README.md").write_text("# My MOD", encoding="utf-8")
        return mod_dir

    def test_create_basic_package(self, tmp_path):
        """基本打包"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        result = pkg.create_package(output_dir, include_signature=False)
        assert os.path.isfile(result)
        assert result.endswith(".xcmod")

    def test_package_contains_files(self, tmp_path):
        """ZIP 包包含正确文件"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        package_path = pkg.create_package(output_dir, include_signature=False)
        with zipfile.ZipFile(package_path, "r") as zf:
            names = zf.namelist()
            assert any("manifest.json" in n for n in names)
            assert any("main.py" in n for n in names)

    def test_package_with_signature(self, tmp_path):
        """带签名的打包"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        package_path = pkg.create_package(output_dir, include_signature=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            assert "META-INF/signature.json" in zf.namelist()
            sig_data = json.loads(zf.read("META-INF/signature.json"))
            assert "content_hash" in sig_data
            assert "timestamp" in sig_data
            assert sig_data["signature"] == ""  # No private key

    def test_package_with_exclude_patterns(self, tmp_path):
        """自定义排除模式"""
        mod_dir = self._make_mod_dir(tmp_path)
        (mod_dir / "secrets.env").write_text("SECRET=123", encoding="utf-8")
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        package_path = pkg.create_package(
            output_dir, include_signature=False, exclude_patterns=["secrets.env"]
        )
        with zipfile.ZipFile(package_path, "r") as zf:
            names = zf.namelist()
            assert not any("secrets.env" in n for n in names)

    def test_default_excludes_pycache(self, tmp_path):
        """默认排除 __pycache__"""
        mod_dir = self._make_mod_dir(tmp_path)
        pycache = mod_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "main.cpython-311.pyc").write_bytes(b"\x00")
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        package_path = pkg.create_package(output_dir, include_signature=False)
        with zipfile.ZipFile(package_path, "r") as zf:
            names = zf.namelist()
            assert not any("__pycache__" in n for n in names)

    def test_output_dir_created(self, tmp_path):
        """输出目录不存在时自动创建"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "deep" / "nested" / "output")

        result = pkg.create_package(output_dir, include_signature=False)
        assert os.path.isfile(result)

    def test_package_name_format(self, tmp_path):
        """ZIP 包名格式为 {id}-{version}.xcmod"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        result = pkg.create_package(output_dir, include_signature=False)
        assert os.path.basename(result) == "my-mod-2.0.0.xcmod"


# ---------------------------------------------------------------------------
# ModPackage — _should_exclude
# ---------------------------------------------------------------------------


class TestShouldExclude:
    """ModPackage._should_exclude() — 文件排除逻辑"""

    def _make_pkg(self, tmp_path):
        (tmp_path / "manifest.json").write_text(
            json.dumps({"id": "test", "version": "1.0.0"}), encoding="utf-8"
        )
        return ModPackage(str(tmp_path))

    def test_exact_match(self, tmp_path):
        """精确匹配排除"""
        pkg = self._make_pkg(tmp_path)
        assert pkg._should_exclude("secrets.env", {"secrets.env"}) is True

    def test_glob_match(self, tmp_path):
        """通配符匹配"""
        pkg = self._make_pkg(tmp_path)
        assert pkg._should_exclude("test.pyc", {"*.pyc"}) is True

    def test_directory_component_match(self, tmp_path):
        """目录组件匹配"""
        pkg = self._make_pkg(tmp_path)
        assert pkg._should_exclude(os.path.join("__pycache__", "main.pyc"), {"__pycache__"}) is True

    def test_no_match(self, tmp_path):
        """无匹配"""
        pkg = self._make_pkg(tmp_path)
        assert pkg._should_exclude("main.py", {"*.pyc"}) is False


# ---------------------------------------------------------------------------
# ModPackage — _generate_signature
# ---------------------------------------------------------------------------


class TestGenerateSignature:
    """ModPackage._generate_signature() — 签名生成"""

    def _make_pkg(self, tmp_path):
        (tmp_path / "manifest.json").write_text(
            json.dumps({"id": "test", "version": "1.0.0"}), encoding="utf-8"
        )
        (tmp_path / "code.py").write_text("pass", encoding="utf-8")
        return ModPackage(str(tmp_path))

    def _members(self, pkg):
        """构造 (arcname, 磁盘路径) 成员列表，模拟 create_package 收集的内容。"""
        members = []
        for root, _, files in os.walk(pkg.mod_path):
            for filename in files:
                fp = os.path.join(root, filename)
                rel = os.path.relpath(fp, pkg.mod_path)
                members.append((os.path.join(pkg.mod_id, rel), fp))
        return members

    def test_signature_without_private_key(self, tmp_path):
        """无私钥时生成空签名"""
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key=None)
        assert sig["signature"] == ""
        assert "warning" in sig
        assert sig["algorithm"] == "sha256"
        assert "content_hash" in sig
        assert "timestamp" in sig

    def test_signature_with_signer_env(self, tmp_path, monkeypatch):
        """XCAGI_MOD_SIGNER 环境变量"""
        monkeypatch.setenv("XCAGI_MOD_SIGNER", "test-signer")
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key=None)
        assert sig["signer"] == "test-signer"

    def test_signature_default_signer(self, tmp_path, monkeypatch):
        """默认 signer 为 unknown"""
        monkeypatch.delenv("XCAGI_MOD_SIGNER", raising=False)
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key=None)
        assert sig["signer"] == "unknown"

    def test_signature_with_missing_private_key_file(self, tmp_path):
        """私钥文件不存在时签名失败但不抛异常"""
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key="/nonexistent/key.pem")
        assert sig["signature"] == ""

    def test_signature_with_cryptography_import_error(self, tmp_path):
        """cryptography 库不可用时使用无签名模式"""
        pkg = self._make_pkg(tmp_path)
        # Create a fake private key file
        key_file = tmp_path / "fake_key.pem"
        key_file.write_text("not a real key", encoding="utf-8")

        with patch.dict("sys.modules", {"cryptography": None}):
            sig = pkg._generate_signature(self._members(pkg), private_key=str(key_file))
        assert sig["signature"] == ""


# ---------------------------------------------------------------------------
# ModPackage — extract_package
# ---------------------------------------------------------------------------


class TestExtractPackage:
    """ModPackage.extract_package() — 解压 MOD 包"""

    def _create_test_package(self, tmp_path, include_sig=True):
        """创建测试用 MOD 包（manifest.json 在 zip 根目录）"""
        # Create a zip directly with manifest.json at root level
        package_path = str(tmp_path / "pkg_output" / "extract-test-1.0.0.xcmod")
        os.makedirs(os.path.dirname(package_path), exist_ok=True)

        manifest = {"id": "extract-test", "version": "1.0.0", "name": "Extract Test"}

        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("code.py", "pass")
            if include_sig:
                sig = {
                    "version": "1.0",
                    "algorithm": "sha256",
                    "content_hash": "fake_hash",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "signature": "",
                }
                zf.writestr("META-INF/signature.json", json.dumps(sig))

        return package_path

    def test_extract_basic_package(self, tmp_path):
        """基本解压"""
        package_path = self._create_test_package(tmp_path, include_sig=False)
        target_dir = str(tmp_path / "extracted")

        # The zip has files under "extract-test/" prefix; after extraction
        # manifest.json is at target_dir/extract-test/manifest.json.
        # extract_package checks target_dir/manifest.json first, then target_dir/{mod_id}/manifest.json.
        # We need to handle both cases — copy manifest.json to root if needed.
        extracted_path, manifest = ModPackage.extract_package(
            package_path, target_dir, verify_signature=False
        )
        assert manifest["id"] == "extract-test"
        # extracted_path is either target_dir/extract-test or target_dir
        assert os.path.isdir(extracted_path)

    def test_extract_nonexistent_package_raises(self, tmp_path):
        """包不存在时抛出 ModPackageError"""
        with pytest.raises(ModPackageError, match="MOD 包不存在"):
            ModPackage.extract_package("/nonexistent.xcmod", str(tmp_path))

    def test_extract_invalid_zip_raises(self, tmp_path):
        """非 ZIP 文件时抛出 ModPackageError"""
        bad_file = tmp_path / "bad.xcmod"
        bad_file.write_text("not a zip", encoding="utf-8")
        with pytest.raises(ModPackageError, match="不是有效的 ZIP 文件"):
            ModPackage.extract_package(str(bad_file), str(tmp_path / "out"))

    def test_extract_without_manifest_raises(self, tmp_path):
        """缺少 manifest.json 时抛出 ModPackageError"""
        # Create a zip without manifest.json at root
        zip_path = str(tmp_path / "no_manifest.xcmod")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("some_file.txt", "data")

        target_dir = str(tmp_path / "extracted")
        with pytest.raises(ModPackageError, match="缺少 manifest.json"):
            ModPackage.extract_package(zip_path, target_dir, verify_signature=False)

    def test_extract_manifest_without_id_raises(self, tmp_path):
        """manifest.json 缺少 id 时抛出 ModPackageError"""
        zip_path = str(tmp_path / "no_id.xcmod")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"version": "1.0.0"}))

        target_dir = str(tmp_path / "extracted")
        with pytest.raises(ModPackageError, match="缺少 'id' 字段"):
            ModPackage.extract_package(zip_path, target_dir, verify_signature=False)

    def test_extract_with_mod_id_subdir(self, tmp_path):
        """解压后 manifest 位于 mod_id 子目录时，应解析到该子目录（不再误报缺失）。

        VULN-1 核心修复附带修正了 create_package(写 {mod_id}/ 前缀) 与
        extract_package(只看顶层 manifest) 不一致的历史 bug：现在 extract 会
        在唯一的 mod_id 子目录中找到 manifest 并以其为 mod 根目录。
        """
        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        manifest = {"id": "sub-mod", "version": "1.0.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (mod_dir / "code.py").write_text("pass", encoding="utf-8")

        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "pkg_output")
        package_path = pkg.create_package(output_dir, include_signature=False)

        target_dir = str(tmp_path / "extracted")
        extracted_path, returned_manifest = ModPackage.extract_package(
            package_path, target_dir, verify_signature=False
        )
        assert returned_manifest["id"] == "sub-mod"
        # mod 根目录应为 target_dir/sub-mod，且其中含 manifest.json。
        assert os.path.basename(extracted_path) == "sub-mod"
        assert os.path.isfile(os.path.join(extracted_path, "manifest.json"))

    def test_extract_target_dir_created(self, tmp_path):
        """目标目录不存在时自动创建"""
        package_path = self._create_test_package(tmp_path, include_sig=False)
        target_dir = str(tmp_path / "deep" / "new" / "dir")

        extracted_path, _ = ModPackage.extract_package(
            package_path, target_dir, verify_signature=False
        )
        assert os.path.isdir(extracted_path)


# ---------------------------------------------------------------------------
# ModPackage — _verify_package_signature
# ---------------------------------------------------------------------------


class TestVerifyPackageSignature:
    """ModPackage._verify_package_signature() — 签名验证"""

    def test_empty_signature_returns_false(self, tmp_path):
        """空签名返回 False"""
        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        manifest = {"id": "sig-test", "version": "1.0.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (mod_dir / "code.py").write_text("pass", encoding="utf-8")

        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "pkg_output")
        package_path = pkg.create_package(output_dir, include_signature=True)

        target_dir = str(tmp_path / "extracted")
        with zipfile.ZipFile(package_path, "r") as zf:
            result = ModPackage._verify_package_signature(target_dir, zf)
        assert result is False

    def test_hash_mismatch_raises(self, tmp_path):
        """哈希不匹配且签名非空时抛出 ModSignatureError"""
        # Create a zip with a non-empty signature and a known content hash
        package_path = str(tmp_path / "pkg_output" / "hash-test-1.0.0.xcmod")
        os.makedirs(os.path.dirname(package_path), exist_ok=True)

        manifest = {"id": "hash-test", "version": "1.0.0"}
        sig = {
            "version": "1.0",
            "algorithm": "sha256",
            "content_hash": "fake_hash_that_wont_match",
            "timestamp": "2026-01-01T00:00:00Z",
            "signature": "non_empty_signature_value",
        }

        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("code.py", "pass")
            zf.writestr("META-INF/signature.json", json.dumps(sig))

        # Extract the zip to a target directory
        target_dir = str(tmp_path / "extracted")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(target_dir)

        # Now verify — the computed hash will differ from the stored fake hash,
        # and since signature is non-empty, it should raise ModSignatureError.
        with zipfile.ZipFile(package_path, "r") as zf:
            with pytest.raises(ModSignatureError, match="哈希不匹配"):
                ModPackage._verify_package_signature(target_dir, zf)


# ---------------------------------------------------------------------------
# ModPackage — get_package_info
# ---------------------------------------------------------------------------


class TestGetPackageInfo:
    """ModPackage.get_package_info() — 获取 MOD 包信息"""

    def test_basic_info(self, tmp_path):
        """基本信息"""
        (tmp_path / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "info-mod",
                    "version": "3.0.0",
                    "name": "Info MOD",
                    "author": "Test Author",
                    "description": "A test MOD",
                    "dependencies": {"core": ">=1.0"},
                }
            ),
            encoding="utf-8",
        )
        pkg = ModPackage(str(tmp_path))
        info = pkg.get_package_info()

        assert info["id"] == "info-mod"
        assert info["name"] == "Info MOD"
        assert info["version"] == "3.0.0"
        assert info["author"] == "Test Author"
        assert info["description"] == "A test MOD"
        assert info["dependencies"] == {"core": ">=1.0"}
        assert "file_size" in info

    def test_minimal_manifest(self, tmp_path):
        """最小 manifest"""
        (tmp_path / "manifest.json").write_text(json.dumps({"id": "minimal-mod"}), encoding="utf-8")
        pkg = ModPackage(str(tmp_path))
        info = pkg.get_package_info()

        assert info["id"] == "minimal-mod"
        assert info["name"] == ""
        assert info["author"] == ""
        assert info["description"] == ""
        assert info["dependencies"] == {}


# ---------------------------------------------------------------------------
# ModPackageError / ModSignatureError
# ---------------------------------------------------------------------------


class TestExceptions:
    """异常类"""

    def test_mod_package_error_is_exception(self):
        assert issubclass(ModPackageError, Exception)

    def test_mod_signature_error_is_exception(self):
        assert issubclass(ModSignatureError, Exception)

    def test_mod_package_error_message(self):
        with pytest.raises(ModPackageError, match="test error"):
            raise ModPackageError("test error")

    def test_mod_signature_error_message(self):
        with pytest.raises(ModSignatureError, match="sig error"):
            raise ModSignatureError("sig error")
