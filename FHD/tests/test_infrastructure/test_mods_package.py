"""Tests for app.infrastructure.mods.package — MOD packaging, signing, verification.

行为断言版：每个用例锚定具体返回值/数据结构内容/分支转换，而非"非空/类型对"。
哈希用例对拍 hashlib 的权威摘要；签名用例覆盖真实 Ed25519 签—验闭环、篡改检测
与缺密钥/缺库降级；验签覆盖 fail-closed（XCAGI_REQUIRE_SIGNED_MODS）开关两态。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import zipfile

import pytest

from app.infrastructure.mods.package import (
    ModPackage,
    ModPackageError,
    ModSignatureError,
    build_signed_message,
    compute_directory_hash,
    compute_file_hash,
    compute_members_hash,
)

# 权威常量：直接由 hashlib 派生，作为被测函数的"金标准"对拍值。
SHA256_HELLO_WORLD = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
MD5_HELLO_WORLD = "5eb63bbbe01eeed093cb22bb8f5acdc3"
SHA256_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SHA256_256_BYTES = "40aff2e9d2d8922e47afd4648e6967497158785fbd1da870e7110266bf944880"


def _gen_ed25519_keypair(tmp_path):
    """生成一对临时 Ed25519 私/公钥并写盘，返回 (私钥路径, 公钥路径)。

    用真实 cryptography 生成，覆盖 create_package 的真实签名分支与
    _verify_package_signature 的真实密码学验签分支（而非仅空签名占位）。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    priv_path = tmp_path / "signer_priv.pem"
    priv_path.write_bytes(
        priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pub_path = tmp_path / "signer_pub.pem"
    pub_path.write_bytes(
        priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return str(priv_path), str(pub_path)


# ---------------------------------------------------------------------------
# compute_file_hash
# ---------------------------------------------------------------------------


class TestComputeFileHash:
    """compute_file_hash() — 计算文件哈希"""

    def test_sha256_hash_matches_known_digest(self, tmp_path):
        """SHA256 哈希等于 'hello world' 的权威摘要"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert compute_file_hash(str(f)) == SHA256_HELLO_WORLD

    def test_md5_hash_matches_known_digest(self, tmp_path):
        """algorithm='md5' 选用 MD5，结果等于权威 MD5 摘要"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert compute_file_hash(str(f), algorithm="md5") == MD5_HELLO_WORLD

    def test_empty_file_hash_is_sha256_of_nothing(self, tmp_path):
        """空文件的 SHA256 等于空输入摘要"""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        assert compute_file_hash(str(f)) == SHA256_EMPTY

    def test_binary_file_hash_matches_known_digest(self, tmp_path):
        """全字节范围(0..255)的二进制文件哈希等于权威摘要（验证按字节流读取）"""
        f = tmp_path / "binary.bin"
        f.write_bytes(bytes(range(256)))
        assert compute_file_hash(str(f)) == SHA256_256_BYTES

    def test_chunked_read_equals_single_shot(self, tmp_path):
        """大于 8192 字节分块边界的文件，分块读取结果与一次性 hashlib 一致"""
        payload = b"x" * 20000  # 跨越多个 8192 块
        f = tmp_path / "big.bin"
        f.write_bytes(payload)
        assert compute_file_hash(str(f)) == hashlib.sha256(payload).hexdigest()

    def test_unknown_algorithm_raises_value_error(self, tmp_path):
        """未知算法名透传 hashlib 的 ValueError（异常分支）"""
        f = tmp_path / "x.txt"
        f.write_text("data", encoding="utf-8")
        with pytest.raises(ValueError):
            compute_file_hash(str(f), algorithm="not-a-real-algo")

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

    def test_basic_directory_hash_matches_manual_composition(self, tmp_path):
        """目录哈希 == 对 (rel_path:file_hash) 排序拼接后的 SHA256（复刻算法验证内容真被纳入）"""
        (tmp_path / "file1.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("world", encoding="utf-8")

        # 手工复刻 compute_directory_hash 的权威算法：按文件名排序，
        # 逐个 update f"{rel}:{file_sha256}"。
        expected = hashlib.sha256()
        for rel, content in sorted([("file1.txt", b"hello"), ("file2.txt", b"world")]):
            fh = hashlib.sha256(content).hexdigest()
            expected.update(f"{rel}:{fh}".encode())

        assert compute_directory_hash(str(tmp_path)) == expected.hexdigest()

    def test_changing_one_file_changes_directory_hash(self, tmp_path):
        """改任意一个文件内容会改变目录哈希（哈希确实覆盖文件内容而非仅文件名）"""
        (tmp_path / "a.txt").write_text("v1", encoding="utf-8")
        before = compute_directory_hash(str(tmp_path))
        (tmp_path / "a.txt").write_text("v2", encoding="utf-8")
        after = compute_directory_hash(str(tmp_path))
        assert before != after

    def test_ignores_dotfiles(self, tmp_path):
        """忽略以 . 开头的文件"""
        (tmp_path / "visible.txt").write_text("data", encoding="utf-8")
        (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
        result_with = compute_directory_hash(str(tmp_path))

        # Remove hidden file and compute again — should be same
        os.remove(str(tmp_path / ".hidden"))
        result_without = compute_directory_hash(str(tmp_path))
        assert result_with == result_without

    def test_empty_directory_hash_is_sha256_of_nothing(self, tmp_path):
        """空目录（无任何文件被纳入）哈希等于空输入摘要"""
        assert compute_directory_hash(str(tmp_path)) == SHA256_EMPTY

    def test_meta_inf_signature_excluded_from_hash(self, tmp_path):
        """META-INF/ 下的签名产物被排除（修复 S2 自指）：加它前后哈希不变"""
        (tmp_path / "code.py").write_text("pass", encoding="utf-8")
        before = compute_directory_hash(str(tmp_path))

        meta = tmp_path / "META-INF"
        meta.mkdir()
        (meta / "signature.json").write_text('{"signature": "abc"}', encoding="utf-8")
        after = compute_directory_hash(str(tmp_path))

        assert before == after

    def test_subdirectory_files_change_hash(self, tmp_path):
        """子目录里的文件确实被纳入哈希：添加嵌套文件会改变目录哈希"""
        (tmp_path / "top.txt").write_text("top", encoding="utf-8")
        before = compute_directory_hash(str(tmp_path))

        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content", encoding="utf-8")
        after = compute_directory_hash(str(tmp_path))

        assert after != before

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

    def test_create_basic_package_path_and_name(self, tmp_path):
        """基本打包：返回路径在 output_dir 下，文件名为 {id}-{version}.xcmod 且真实存在"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        result = pkg.create_package(output_dir, include_signature=False)
        assert os.path.isfile(result)
        assert os.path.dirname(result) == output_dir
        assert os.path.basename(result) == "my-mod-2.0.0.xcmod"
        # include_signature=False -> 不写签名产物
        with zipfile.ZipFile(result, "r") as zf:
            assert "META-INF/signature.json" not in zf.namelist()

    def test_package_arcnames_under_mod_id_prefix(self, tmp_path):
        """ZIP 成员 arcname 形如 {mod_id}/<rel>，且精确包含 manifest.json + main.py + README.md"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        package_path = pkg.create_package(output_dir, include_signature=False)
        with zipfile.ZipFile(package_path, "r") as zf:
            names = set(zf.namelist())
            assert names == {
                "my-mod/manifest.json",
                "my-mod/main.py",
                "my-mod/README.md",
            }
            # 内容随包原样写入，可被解出
            assert zf.read("my-mod/main.py") == b"print('hello')"

    def test_package_with_signature(self, tmp_path):
        """带签名的打包"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = str(tmp_path / "output")

        package_path = pkg.create_package(output_dir, include_signature=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            assert "META-INF/signature.json" in zf.namelist()
            sig_data = json.loads(zf.read("META-INF/signature.json"))
            # content_hash 必须等于按 zip 成员（排除 META-INF/）重算的权威哈希
            members = [
                (info.filename, zf.read(info.filename))
                for info in zf.infolist()
                if not info.is_dir() and not info.filename.startswith("META-INF/")
            ]
            assert sig_data["content_hash"] == compute_members_hash(members)
            assert sig_data["signature"] == ""  # 无私钥 -> 空签名
            assert sig_data["warning"] == "未提供私钥，签名缺失"
            assert sig_data["manifest_id"] == "my-mod"
            assert sig_data["manifest_version"] == "2.0.0"

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

    def test_output_dir_created_for_deep_path(self, tmp_path):
        """输出目录链(deep/nested/output)不存在时自动逐级创建，包落在其中"""
        mod_dir = self._make_mod_dir(tmp_path)
        pkg = ModPackage(str(mod_dir))
        output_dir = tmp_path / "deep" / "nested" / "output"
        assert not output_dir.exists()

        result = pkg.create_package(str(output_dir), include_signature=False)
        assert output_dir.is_dir()
        assert os.path.dirname(result) == str(output_dir)
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

    def _expected_content_hash(self, pkg):
        """复刻 _generate_signature 的 content_hash：基于成员字节调 compute_members_hash。"""
        member_bytes = []
        for arcname, fp in self._members(pkg):
            with open(fp, "rb") as f:
                member_bytes.append((arcname, f.read()))
        return compute_members_hash(member_bytes)

    def test_signature_without_private_key(self, tmp_path):
        """无私钥：空签名 + 警告 + content_hash 等于权威成员哈希，且绑定 manifest 字段"""
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key=None)
        assert sig["signature"] == ""
        assert sig["warning"] == "未提供私钥，签名缺失"
        assert sig["algorithm"] == "sha256"
        assert sig["content_hash"] == self._expected_content_hash(pkg)
        assert sig["signed_fields"] == ["manifest_id", "version", "content_hash"]
        assert sig["manifest_id"] == "test"
        assert sig["manifest_version"] == "1.0.0"
        # 无密钥时不声明 key_algorithm（未做真实签名）
        assert "key_algorithm" not in sig

    def test_signature_with_real_ed25519_key(self, tmp_path):
        """有私钥：产出可被对应公钥验证通过的真实 Ed25519 签名（签名happy path）"""
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization

        priv_path, pub_path = _gen_ed25519_keypair(tmp_path)
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key=priv_path)

        assert sig["signature"] != ""
        assert sig["key_algorithm"] == "Ed25519"
        assert "warning" not in sig  # 真正签了名，不应带"签名缺失"警告

        # 用公钥验证：被签消息 = id:version:content_hash
        with open(pub_path, "rb") as f:
            public_key = serialization.load_pem_public_key(f.read())
        message = build_signed_message("test", "1.0.0", sig["content_hash"])
        # 正确签名验证通过（不抛异常）
        public_key.verify(base64.b64decode(sig["signature"]), message)
        # 篡改被签消息则验证失败
        with pytest.raises(InvalidSignature):
            public_key.verify(
                base64.b64decode(sig["signature"]),
                build_signed_message("test", "1.0.0", "tampered"),
            )

    def test_signature_rejects_non_ed25519_key(self, tmp_path):
        """提供非 Ed25519 私钥(RSA)：fail-closed 抛 ModSignatureError(不退化成伪签名)。

        注意 ModSignatureError 不属 RECOVERABLE_ERRORS，故由源码主动 raise 后
        不被 except 吞掉——这是对"用错钥类型仍签名"的硬拒绝，属正确安全行为。
        """
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path = tmp_path / "rsa.pem"
        key_path.write_bytes(
            rsa_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        pkg = self._make_pkg(tmp_path)
        with pytest.raises(ModSignatureError, match="Ed25519"):
            pkg._generate_signature(self._members(pkg), private_key=str(key_path))

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
        """私钥文件不存在(OSError 属可恢复)：吞掉异常 -> 空签名，但 content_hash 仍算出"""
        pkg = self._make_pkg(tmp_path)
        sig = pkg._generate_signature(self._members(pkg), private_key="/nonexistent/key.pem")
        assert sig["signature"] == ""
        # 即便签名失败，content_hash 仍为权威值（内容完整性可继续校验）
        assert sig["content_hash"] == self._expected_content_hash(pkg)
        assert "key_algorithm" not in sig

    def test_signature_with_cryptography_import_error(self, tmp_path):
        """cryptography 不可用(ImportError)：降级为无签名模式，content_hash 不受影响"""
        import builtins

        pkg = self._make_pkg(tmp_path)
        key_file = tmp_path / "fake_key.pem"
        key_file.write_text("not a real key", encoding="utf-8")

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "cryptography" or name.startswith("cryptography."):
                raise ImportError("cryptography disabled for test")
            return real_import(name, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(builtins, "__import__", _blocked_import)
            sig = pkg._generate_signature(self._members(pkg), private_key=str(key_file))
        assert sig["signature"] == ""
        assert sig["content_hash"] == self._expected_content_hash(pkg)


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

    def test_extract_flat_package_returns_target_dir_and_manifest(self, tmp_path):
        """扁平包(manifest 在 zip 根)：extracted_path == target_dir，manifest 全字段解出，文件落盘"""
        package_path = self._create_test_package(tmp_path, include_sig=False)
        target_dir = str(tmp_path / "extracted")

        extracted_path, manifest = ModPackage.extract_package(
            package_path, target_dir, verify_signature=False
        )
        # manifest 在根 -> mod 根目录就是 target_dir 本身
        assert extracted_path == target_dir
        assert manifest == {"id": "extract-test", "version": "1.0.0", "name": "Extract Test"}
        # 实际文件被解到磁盘
        assert os.path.isfile(os.path.join(target_dir, "manifest.json"))
        with open(os.path.join(target_dir, "code.py"), encoding="utf-8") as f:
            assert f.read() == "pass"

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

    def test_extract_target_dir_created_deeply(self, tmp_path):
        """目标目录链不存在时逐级创建，并解出 manifest（扁平包 -> extracted==target）"""
        package_path = self._create_test_package(tmp_path, include_sig=False)
        target = tmp_path / "deep" / "new" / "dir"
        assert not target.exists()

        extracted_path, manifest = ModPackage.extract_package(
            package_path, str(target), verify_signature=False
        )
        assert target.is_dir()
        assert extracted_path == str(target)
        assert manifest["id"] == "extract-test"
        assert os.path.isfile(os.path.join(str(target), "manifest.json"))


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

    def test_valid_ed25519_signature_verifies_true(self, tmp_path, monkeypatch):
        """真实签名 happy path：用打包私钥签 + 环境公钥验 -> 返回 True（VULN-1 修复正路）"""
        priv_path, pub_path = _gen_ed25519_keypair(tmp_path)
        # 通过环境变量把测试公钥加入受信集（覆盖 load_trusted_public_keys 的 env 分支）
        monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", pub_path)

        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "good-mod", "version": "2.5.0"}), encoding="utf-8"
        )
        (mod_dir / "code.py").write_text("print('ok')", encoding="utf-8")

        pkg = ModPackage(str(mod_dir))
        package_path = pkg.create_package(
            str(tmp_path / "out"), include_signature=True, private_key=priv_path
        )

        target_dir = str(tmp_path / "extracted")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(target_dir)
        with zipfile.ZipFile(package_path, "r") as zf:
            result = ModPackage._verify_package_signature(target_dir, zf)
        assert result is True

    def test_tampered_content_under_valid_signature_raises(self, tmp_path, monkeypatch):
        """有合法签名但内容被改 -> content_hash 不匹配 -> ModSignatureError（防 fail-open）"""
        priv_path, pub_path = _gen_ed25519_keypair(tmp_path)
        monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", pub_path)

        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "tamper-mod", "version": "1.0.0"}), encoding="utf-8"
        )
        (mod_dir / "code.py").write_text("print('clean')", encoding="utf-8")
        pkg = ModPackage(str(mod_dir))
        package_path = pkg.create_package(
            str(tmp_path / "out"), include_signature=True, private_key=priv_path
        )

        # 重打一个被篡改的 zip：保留原签名，但改 code.py 内容
        with zipfile.ZipFile(package_path, "r") as zf:
            sig_json = zf.read("META-INF/signature.json")
            manifest_bytes = zf.read("tamper-mod/manifest.json")
        tampered = str(tmp_path / "tampered.xcmod")
        with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("tamper-mod/manifest.json", manifest_bytes)
            zf.writestr("tamper-mod/code.py", "import os  # injected payload")
            zf.writestr("META-INF/signature.json", sig_json)

        target_dir = str(tmp_path / "extracted")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(tampered, "r") as zf:
            zf.extractall(target_dir)
        with zipfile.ZipFile(tampered, "r") as zf:
            with pytest.raises(ModSignatureError, match="哈希不匹配"):
                ModPackage._verify_package_signature(target_dir, zf)

    def test_unsigned_package_fail_closed_when_required(self, tmp_path, monkeypatch):
        """XCAGI_REQUIRE_SIGNED_MODS=1 + 内容哈希对但签名为空 -> 拒绝安装(fail-closed)。"""
        monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "1")

        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "unsigned-mod", "version": "1.0.0"}), encoding="utf-8"
        )
        (mod_dir / "code.py").write_text("pass", encoding="utf-8")
        pkg = ModPackage(str(mod_dir))
        # 不带私钥 -> content_hash 正确但 signature == ""
        package_path = pkg.create_package(
            str(tmp_path / "out"), include_signature=True, private_key=None
        )

        target_dir = str(tmp_path / "extracted")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(target_dir)
        with zipfile.ZipFile(package_path, "r") as zf:
            with pytest.raises(ModSignatureError, match="未携带签名"):
                ModPackage._verify_package_signature(target_dir, zf)

    def test_unsigned_package_default_returns_false(self, tmp_path, monkeypatch):
        """默认(未设强制)：内容哈希对但无签名 -> 返回 False（放行但标记未验签）。"""
        monkeypatch.delenv("XCAGI_REQUIRE_SIGNED_MODS", raising=False)

        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "unsigned-mod", "version": "1.0.0"}), encoding="utf-8"
        )
        (mod_dir / "code.py").write_text("pass", encoding="utf-8")
        pkg = ModPackage(str(mod_dir))
        package_path = pkg.create_package(
            str(tmp_path / "out"), include_signature=True, private_key=None
        )

        target_dir = str(tmp_path / "extracted")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(target_dir)
        with zipfile.ZipFile(package_path, "r") as zf:
            result = ModPackage._verify_package_signature(target_dir, zf)
        assert result is False

    def test_signature_from_untrusted_key_rejected(self, tmp_path, monkeypatch):
        """签名有效但签发公钥不在受信集 -> fail-closed 抛 ModSignatureError（无受信公钥可验）。"""
        # 用钥 A 签包，但只把 *无关的* 钥 B 公钥放进受信集
        priv_a, _pub_a = _gen_ed25519_keypair(tmp_path)
        # 生成第二把无关公钥并作为受信集
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        other_pub = tmp_path / "other_pub.pem"
        other_pub.write_bytes(
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(other_pub))

        mod_dir = tmp_path / "src_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "untrusted-mod", "version": "1.0.0"}), encoding="utf-8"
        )
        (mod_dir / "code.py").write_text("pass", encoding="utf-8")
        pkg = ModPackage(str(mod_dir))
        package_path = pkg.create_package(
            str(tmp_path / "out"), include_signature=True, private_key=priv_a
        )

        target_dir = str(tmp_path / "extracted")
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(target_dir)
        with zipfile.ZipFile(package_path, "r") as zf:
            with pytest.raises(ModSignatureError, match="无任何受信公钥"):
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
