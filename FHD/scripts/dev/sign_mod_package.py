#!/usr/bin/env python3
"""MOD 包签名 CLI（开发/发布用）。

用受信发布私钥（Ed25519, PEM）对一个 MOD 目录打包并签名，产出 ``.xcmod``。
签名写入 ``META-INF/signature.json``，content_hash 基于 zip 成员（排除
META-INF/）计算，与运行时验签端（``ModPackage._verify_package_signature`` +
``app.infrastructure.mods.trusted_keys``）完全对齐。

私钥绝不入仓库：用 ``--private-key`` 指向仓库外的 PEM 文件，或由发布流水线
在受控环境注入。对应的公钥须已登记在
``app/infrastructure/mods/trusted_keys.py`` 的 ``TRUSTED_MOD_PUBLIC_KEYS_PEM``，
否则运行时无法用内置受信公钥验签。

用法：
    python scripts/dev/sign_mod_package.py \\
        --mod-dir path/to/mod \\
        --private-key /secure/outside/repo/mod_signing_ed25519.pem \\
        --output-dir dist/

生成测试用 Ed25519 密钥对（私钥放仓库外）：
    python scripts/dev/sign_mod_package.py --gen-key /tmp/keys/mod_dev
"""

from __future__ import annotations

import argparse
import os
import sys


def _repo_root_on_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def _gen_key(prefix: str) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path = f"{prefix}_ed25519.pem"
    pub_path = f"{prefix}_ed25519.pub.pem"
    os.makedirs(os.path.dirname(os.path.abspath(priv_path)) or ".", exist_ok=True)
    with open(priv_path, "wb") as f:
        f.write(priv_pem)
    os.chmod(priv_path, 0o600)
    with open(pub_path, "wb") as f:
        f.write(pub_pem)

    print(f"私钥（请放仓库外、勿提交）：{priv_path}")
    print(f"公钥（登记到 trusted_keys.py）：{pub_path}")
    print("\n--- 公钥 PEM（粘贴进 TRUSTED_MOD_PUBLIC_KEYS_PEM）---")
    print(pub_pem.decode())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MOD 包 Ed25519 签名工具")
    parser.add_argument("--mod-dir", help="待打包签名的 MOD 目录（含 manifest.json）")
    parser.add_argument(
        "--private-key",
        help="Ed25519 私钥 PEM 路径（仓库外）。省略则产出未签名包。",
    )
    parser.add_argument("--output-dir", default="dist", help="输出目录（默认 dist/）")
    parser.add_argument(
        "--gen-key",
        metavar="PREFIX",
        help="生成一对 Ed25519 测试密钥到 PREFIX_ed25519.pem / .pub.pem 后退出",
    )
    args = parser.parse_args(argv)

    _repo_root_on_path()

    if args.gen_key:
        return _gen_key(args.gen_key)

    if not args.mod_dir:
        parser.error("必须提供 --mod-dir（或用 --gen-key 生成密钥）")

    from app.infrastructure.mods.package import ModPackage

    pkg = ModPackage(args.mod_dir)
    out = pkg.create_package(
        output_dir=args.output_dir,
        include_signature=True,
        private_key=args.private_key,
    )
    if args.private_key:
        print(f"已签名 MOD 包：{out}")
    else:
        print(f"未签名 MOD 包（未提供 --private-key）：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
