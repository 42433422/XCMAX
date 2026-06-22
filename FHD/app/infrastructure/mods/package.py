"""
MOD Package Management - ZIP packaging, signing, and verification
"""

import hashlib
import json
import logging
import os
import zipfile
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_iso_z

logger = logging.getLogger(__name__)


class ModPackageError(Exception):
    """MOD 打包/解包错误"""


class ModSignatureError(Exception):
    """MOD 签名验证错误"""


def _require_signed_mods() -> bool:
    """是否启用 fail-closed 强制验签（运维开关 XCAGI_REQUIRE_SIGNED_MODS）。

    未设 / "0" / "false" -> False（默认，不破坏现有安装）；
    "1" / "true" / "yes" / "on" -> True（fail-closed）。
    """
    return os.environ.get("XCAGI_REQUIRE_SIGNED_MODS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def compute_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """计算文件哈希值"""
    hash_func = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


# 算 content_hash 时必须两端一致排除的签名产物：META-INF/ 下的签名文件本身
# 不能进入它所签名的内容哈希（否则形成自指，签名时算的 hash != 验签时重算的 hash）。
# 这是 S2 自指 bug 的修复基准——签名/验签两端都用此前缀集合排除。
SIGNATURE_EXCLUDE_PREFIXES: tuple[str, ...] = ("META-INF/", "META-INF" + os.sep)


def _is_excluded_rel_path(rel_path: str, exclude_prefixes: tuple[str, ...]) -> bool:
    """判断相对路径是否落在需要排除的前缀下（同时兼容 / 与平台分隔符）。"""
    norm = rel_path.replace(os.sep, "/")
    for prefix in exclude_prefixes:
        p = prefix.replace(os.sep, "/")
        if norm == p.rstrip("/") or norm.startswith(p):
            return True
    return False


def build_signed_message(manifest_id: str, version: str, content_hash: str) -> bytes:
    """构造被 Ed25519 签名的规范化字节串。

    绑定 manifest id 与 version（而非仅签 content_hash），可防止把一个合法
    签名包的内容哈希挪用到另一个 id/version 上的混淆攻击。
    """
    return f"{manifest_id}:{version}:{content_hash}".encode()


def compute_members_hash(
    members: list[tuple[str, bytes]],
    algorithm: str = "sha256",
    exclude_prefixes: tuple[str, ...] = SIGNATURE_EXCLUDE_PREFIXES,
) -> str:
    """基于一组 (arcname, content_bytes) 成员计算规范内容哈希。

    这是签名/验签两端共享的 *权威* 内容哈希算法：

    * 排除 ``META-INF/`` 下的签名产物（修复 S2 自指）；
    * arcname 统一用 ``/`` 归一并排序，与磁盘/解压布局无关；
    * 哈希基于 arcname + 文件内容字节，签名时（从 mod 目录读取内容）与验签时
      （从 zip 成员读取内容）完全一致，因此不受 ``mod_id/`` 前缀差异影响。
    """
    norm: list[tuple[str, bytes]] = []
    for arcname, content in members:
        rel = arcname.replace(os.sep, "/")
        if _is_excluded_rel_path(rel, exclude_prefixes):
            continue
        if rel.rsplit("/", 1)[-1].startswith("."):
            continue
        norm.append((rel, content))

    hash_func = hashlib.new(algorithm)
    for rel, content in sorted(norm, key=lambda x: x[0]):
        file_hash = hashlib.new(algorithm)
        file_hash.update(content)
        hash_func.update(f"{rel}:{file_hash.hexdigest()}".encode())
    return hash_func.hexdigest()


def compute_directory_hash(
    dir_path: str,
    algorithm: str = "sha256",
    exclude_prefixes: tuple[str, ...] = SIGNATURE_EXCLUDE_PREFIXES,
) -> str:
    """计算目录内所有文件的组合哈希值。

    Args:
        dir_path: 目录路径。
        algorithm: 哈希算法。
        exclude_prefixes: 需要从内容哈希中排除的相对路径前缀。默认排除
            ``META-INF/`` 下的签名产物（``signature.json`` 等），以消除
            "签名文件被纳入它自己签名的内容哈希"的自指（S2）问题——这样
            签名时（在原始 mod 目录，无 META-INF）算的 hash 与验签时
            （在解压目录，含 META-INF/signature.json）重算的 hash 完全一致。
    """
    hash_func = hashlib.new(algorithm)

    for root, _, files in os.walk(dir_path):
        for filename in sorted(files):
            if filename.startswith("."):
                continue
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, dir_path)
            if _is_excluded_rel_path(rel_path, exclude_prefixes):
                continue
            file_hash = compute_file_hash(file_path, algorithm)
            hash_func.update(f"{rel_path}:{file_hash}".encode())

    return hash_func.hexdigest()


class ModPackage:
    """MOD 打包与解包工具"""

    def __init__(self, mod_path: str):
        self.mod_path = os.path.abspath(mod_path)
        self.manifest_path = os.path.join(self.mod_path, "manifest.json")

        if not os.path.isdir(self.mod_path):
            raise ModPackageError(f"MOD 目录不存在：{self.mod_path}")

        if not os.path.isfile(self.manifest_path):
            raise ModPackageError(f"manifest.json 不存在：{self.manifest_path}")

        with open(self.manifest_path, encoding="utf-8") as f:
            self.manifest = json.load(f)

        self.mod_id = self.manifest.get("id", "")
        self.version = self.manifest.get("version", "1.0.0")

        if not self.mod_id:
            raise ModPackageError("manifest.json 缺少必填字段 'id'")

    def create_package(
        self,
        output_dir: str,
        include_signature: bool = True,
        private_key: str | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> str:
        """
        创建 MOD ZIP 包

        Args:
            output_dir: 输出目录
            include_signature: 是否包含签名
            private_key: 私钥路径（用于签名）
            exclude_patterns: 排除的文件模式列表

        Returns:
            生成的 ZIP 文件路径
        """
        os.makedirs(output_dir, exist_ok=True)

        package_name = f"{self.mod_id}-{self.version}.xcmod"
        package_path = os.path.join(output_dir, package_name)

        default_excludes = {
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".git",
            ".gitignore",
            "*.log",
            ".env",
            ".venv",
            "node_modules",
            "dist",
            "*.zip",
            "*.xcmod",
        }

        if exclude_patterns:
            default_excludes.update(exclude_patterns)

        # 收集即将写入 zip 的成员 (arcname -> 磁盘路径)。content_hash 在
        # 签名/验签两端都基于这些 *zip 成员 arcname*（排除 META-INF/）计算，
        # 从而与解压后的磁盘布局无关，彻底消除 S2 自指与 mod_id/ 前缀不一致。
        members: list[tuple[str, str]] = []
        for root, _, files in os.walk(self.mod_path):
            for filename in files:
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, self.mod_path)

                if self._should_exclude(rel_path, default_excludes):
                    logger.debug("Excluding: %s", rel_path)
                    continue

                arcname = os.path.join(self.mod_id, rel_path)
                members.append((arcname, file_path))

        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for arcname, file_path in members:
                zipf.write(file_path, arcname)
                logger.debug("Added: %s", arcname)

            if include_signature:
                signature_data = self._generate_signature(members, private_key)
                zipf.writestr(
                    "META-INF/signature.json",
                    json.dumps(signature_data, indent=2, ensure_ascii=False),
                )

        logger.info("MOD package created: %s", package_path)
        return package_path

    def _should_exclude(self, rel_path: str, patterns: set) -> bool:
        """检查文件是否应该被排除"""
        import fnmatch

        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if fnmatch.fnmatch(os.path.basename(rel_path), pattern):
                return True
            if pattern in rel_path.split(os.sep):
                return True

        return False

    def _generate_signature(
        self,
        members: list[tuple[str, str]],
        private_key: str | None = None,
    ) -> dict[str, Any]:
        """生成 MOD 签名（Ed25519）。

        Args:
            members: 即将写入 zip 的 (arcname, 磁盘路径) 列表。content_hash
                基于这些成员（排除 META-INF/）计算，与解压布局无关（修复 S2）。
            private_key: 私钥 PEM 文件路径；为空时签名留空（保留向后兼容）。
        """
        member_bytes: list[tuple[str, bytes]] = []
        for arcname, file_path in members:
            with open(file_path, "rb") as f:
                member_bytes.append((arcname, f.read()))
        content_hash = compute_members_hash(member_bytes)

        signature = {
            "version": "1.0",
            "algorithm": "sha256",
            "content_hash": content_hash,
            "timestamp": utc_now_iso_z(),
            "signer": os.environ.get("XCAGI_MOD_SIGNER", "unknown"),
            # 声明签名实际绑定的字段，验签端据此复现被签消息。
            "signed_fields": ["manifest_id", "version", "content_hash"],
            "manifest_id": self.mod_id,
            "manifest_version": self.version,
        }

        if private_key:
            try:
                import base64

                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                    Ed25519PrivateKey,
                )

                with open(private_key, "rb") as f:
                    key = serialization.load_pem_private_key(f.read(), password=None)

                if not isinstance(key, Ed25519PrivateKey):
                    raise ModSignatureError(
                        "MOD 签名要求 Ed25519 私钥，提供的私钥类型不受支持"
                    )

                message = build_signed_message(self.mod_id, self.version, content_hash)
                sig = key.sign(message)

                signature["signature"] = base64.b64encode(sig).decode("utf-8")
                signature["key_algorithm"] = "Ed25519"
            except ImportError:
                logger.warning("cryptography 库未安装，使用无签名模式")
                signature["signature"] = ""
            except RECOVERABLE_ERRORS as e:
                logger.error("签名生成失败：%s", e)
                signature["signature"] = ""
        else:
            signature["signature"] = ""
            signature["warning"] = "未提供私钥，签名缺失"

        return signature

    @classmethod
    def extract_package(
        cls,
        package_path: str,
        target_dir: str,
        verify_signature: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        """
        解压 MOD 包

        Args:
            package_path: MOD 包路径
            target_dir: 目标目录
            verify_signature: 是否验证签名

        Returns:
            (解压后的 MOD 路径，元数据)
        """
        if not os.path.isfile(package_path):
            raise ModPackageError(f"MOD 包不存在：{package_path}")

        if not zipfile.is_zipfile(package_path):
            raise ModPackageError(f"不是有效的 ZIP 文件：{package_path}")

        os.makedirs(target_dir, exist_ok=True)

        with zipfile.ZipFile(package_path, "r") as zipf:
            zipf.extractall(target_dir)

            signature_file = "META-INF/signature.json"
            if signature_file in zipf.namelist():
                if verify_signature:
                    cls._verify_package_signature(target_dir, zipf)
            else:
                if verify_signature:
                    if _require_signed_mods():
                        # fail-closed：强制要求签名却根本没有签名文件 -> 拒绝。
                        raise ModSignatureError(
                            "XCAGI_REQUIRE_SIGNED_MODS 已启用，但 MOD 包缺少签名"
                            f"文件，拒绝安装：{package_path}"
                        )
                    logger.warning("MOD 包缺少签名文件：%s", package_path)

        # manifest 可能位于顶层（旧式扁平包），也可能位于 mod_id/ 子目录下
        # （create_package 的标准布局：arcname = mod_id/<rel>）。两种都支持。
        manifest_path = os.path.join(target_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            nested = cls._find_nested_manifest(target_dir)
            if nested is None:
                raise ModPackageError("MOD 包缺少 manifest.json")
            manifest_path = nested

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        mod_id = manifest.get("id", "")
        if not mod_id:
            raise ModPackageError("manifest.json 缺少 'id' 字段")

        # 解出的 mod 根目录：优先 manifest 所在目录，其次 target_dir/mod_id。
        manifest_dir = os.path.dirname(manifest_path)
        if os.path.isfile(os.path.join(manifest_dir, "manifest.json")):
            extracted_path = manifest_dir
        elif os.path.isdir(os.path.join(target_dir, mod_id)):
            extracted_path = os.path.join(target_dir, mod_id)
        else:
            extracted_path = target_dir

        logger.info("MOD package extracted: %s", extracted_path)
        return extracted_path, manifest

    @staticmethod
    def _find_nested_manifest(target_dir: str) -> str | None:
        """在 target_dir 的直接子目录中查找 manifest.json（mod_id/ 布局）。

        仅在排除 META-INF 后存在 *唯一* 候选 mod 子目录时返回其 manifest，
        避免在含多个子目录的歧义包上误判。
        """
        candidates: list[str] = []
        try:
            entries = sorted(os.listdir(target_dir))
        except OSError:
            return None
        for name in entries:
            if name == "META-INF":
                continue
            sub = os.path.join(target_dir, name)
            cand = os.path.join(sub, "manifest.json")
            if os.path.isdir(sub) and os.path.isfile(cand):
                candidates.append(cand)
        if len(candidates) == 1:
            return candidates[0]
        return None

    @classmethod
    def _verify_package_signature(cls, extract_dir: str, zipf: zipfile.ZipFile) -> bool:
        """验证 MOD 包签名（fail-closed Ed25519）。

        修复 VULN-1 fail-open RCE：

        1. 内容完整性——基于 zip 成员重算 content_hash（排除 META-INF/），
           与签名内记录的 ``content_hash`` 必须一致，否则视为被篡改并 raise。
        2. 密码学验签——用 **打包内置** 的受信公钥（外加可选的环境变量公钥）
           验 Ed25519 签名；任一受信公钥通过即可信，全部失败则 raise。
        3. 删除"仅比对自生成 content_hash 就 return True"的伪验证：内容哈希由
           包自带，攻击者可自洽生成，绝不能作为信任依据。

        行为开关 ``XCAGI_REQUIRE_SIGNED_MODS``：
        * 默认（关）：若包无签名 / 无可用受信公钥 / cryptography 缺失，保持历史
          的不破坏安装行为（放行，但内容哈希仍校验，篡改仍会被拒）。
        * 开启："1"/"true"/"yes"/"on" -> 上述任一无法完成真实验签的情形一律
          raise（fail-closed）。
        """
        try:
            signature_data = json.loads(zipf.read("META-INF/signature.json").decode("utf-8"))

            stored_hash = signature_data.get("content_hash", "")
            signature = signature_data.get("signature", "")

            # ---- 1) 内容完整性：基于 zip 成员重算（排除 META-INF/）----
            members: list[tuple[str, bytes]] = []
            for info in zipf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if _is_excluded_rel_path(name.replace(os.sep, "/"), SIGNATURE_EXCLUDE_PREFIXES):
                    continue
                members.append((name, zipf.read(name)))
            computed_hash = compute_members_hash(members)

            if not stored_hash or computed_hash != stored_hash:
                raise ModSignatureError("MOD 内容哈希不匹配，可能被篡改")

            require_signed = _require_signed_mods()

            if not signature:
                if require_signed:
                    raise ModSignatureError(
                        "XCAGI_REQUIRE_SIGNED_MODS 已启用，但 MOD 未携带签名，拒绝安装"
                    )
                logger.warning(
                    "MOD 未携带密码学签名：仅校验了内容哈希。如需强制验签请设置 "
                    "XCAGI_REQUIRE_SIGNED_MODS=1。"
                )
                return False

            # ---- 2) 密码学验签：用打包内置受信公钥 ----
            manifest_id = signature_data.get("manifest_id", "")
            version = signature_data.get("manifest_version", "")
            message = build_signed_message(manifest_id, version, stored_hash)

            try:
                import base64

                from cryptography.exceptions import InvalidSignature

                from app.infrastructure.mods.trusted_keys import load_trusted_public_keys

                trusted_keys = load_trusted_public_keys()
            except ImportError:
                if require_signed:
                    raise ModSignatureError(
                        "cryptography 库未安装，无法对 MOD 验签，"
                        "XCAGI_REQUIRE_SIGNED_MODS 已启用 -> 拒绝安装"
                    ) from None
                logger.warning("cryptography 库未安装，跳过密码学验签（仅校验内容哈希）")
                return True

            if not trusted_keys:
                if require_signed:
                    raise ModSignatureError(
                        "无可用受信公钥，无法对 MOD 验签，"
                        "XCAGI_REQUIRE_SIGNED_MODS 已启用 -> 拒绝安装"
                    )
                logger.warning("无可用受信公钥，跳过密码学验签（仅校验内容哈希）")
                return True

            sig_bytes = base64.b64decode(signature)
            for public_key in trusted_keys:
                try:
                    public_key.verify(sig_bytes, message)
                    logger.info("MOD signature verified successfully (Ed25519)")
                    return True
                except InvalidSignature:
                    continue
                except (TypeError, ValueError) as e:
                    # 非 Ed25519 公钥或签名格式不符——视为该把钥匙不匹配，继续尝试。
                    logger.debug("受信公钥验签不匹配：%s", e)
                    continue

            # 所有受信公钥均验签失败 -> fail-closed（无论开关）。
            raise ModSignatureError("MOD 签名验证失败：无任何受信公钥可验证该签名")

        except ModSignatureError:
            raise
        except RECOVERABLE_ERRORS as e:
            # 解析/IO 等可恢复错误：fail-closed 模式下也应拒绝，避免成为绕过通道。
            if _require_signed_mods():
                raise ModSignatureError(f"MOD 签名验证过程出错，拒绝安装：{e}") from e
            logger.error("签名验证失败：%s", e)
            return False

    def get_package_info(self) -> dict[str, Any]:
        """获取 MOD 包信息"""
        return {
            "id": self.mod_id,
            "name": self.manifest.get("name", ""),
            "version": self.version,
            "author": self.manifest.get("author", ""),
            "description": self.manifest.get("description", ""),
            "dependencies": self.manifest.get("dependencies", {}),
            "file_size": os.path.getsize(self.manifest_path),
        }
