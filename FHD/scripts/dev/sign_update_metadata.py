#!/usr/bin/env python3
"""对 electron-updater 的 latest.yml / latest-mac.yml 签名（Ed25519）。

用法：
    # 签名单个文件
    python scripts/dev/sign_update_metadata.py latest.yml

    # 签名多个文件
    python scripts/dev/sign_update_metadata.py latest.yml latest-mac.yml

    # 用环境变量指定私钥（CI 用）
    XCAGI_UPDATE_ED25519_PRIVATE_KEY="$(cat ed25519_private.pem)" \
        python scripts/dev/sign_update_metadata.py latest.yml

    # 用文件指定私钥
    python scripts/dev/sign_update_metadata.py --key-file ed25519_private.pem latest.yml

签名格式：在 yml 末尾加一行 `signature: ed25519:<base64>`。
校验端（updater.ts）会移除该行后对剩余内容验签。
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SIGNATURE_PREFIX = "signature: ed25519:"


def load_private_key(key_file: str | None = None) -> Ed25519PrivateKey:
    """从文件或环境变量加载 Ed25519 私钥。"""
    pem_data: bytes
    if key_file:
        pem_data = Path(key_file).read_bytes()
    else:
        env_val = os.environ.get("XCAGI_UPDATE_ED25519_PRIVATE_KEY", "").strip()
        if not env_val:
            raise SystemExit(
                "错误：未找到私钥。请用 --key-file 或设置 "
                "XCAGI_UPDATE_ED25519_PRIVATE_KEY 环境变量。"
            )
        pem_data = env_val.encode()
    key = serialization.load_pem_private_key(pem_data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit(f"错误：密钥不是 Ed25519 类型，实际类型: {type(key).__name__}")
    return key


def sign_file(file_path: Path, private_key: Ed25519PrivateKey) -> None:
    """对单个 yml 文件签名（原地修改，追加 signature 行）。"""
    raw = file_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # 移除已有签名行（幂等，可重复签名）
    body_lines = [line for line in lines if not line.startswith(SIGNATURE_PREFIX)]
    # body 末尾不加 \n，与 updater.ts 的 trimEnd() 一致
    body = "\n".join(body_lines).rstrip()

    signature = private_key.sign(body.encode("utf-8"))
    sig_b64 = base64.b64encode(signature).decode()

    # 写回：body + 换行 + 签名行
    file_path.write_text(body + "\n" + f"{SIGNATURE_PREFIX}{sig_b64}\n", encoding="utf-8")
    print(f"✅ 已签名: {file_path} (signature={sig_b64[:20]}...)")


def main() -> int:
    parser = argparse.ArgumentParser(description="对 update 元数据签名（Ed25519）")
    parser.add_argument("files", nargs="+", help="要签名的 yml 文件路径")
    parser.add_argument("--key-file", help="Ed25519 私钥 PEM 文件路径")
    args = parser.parse_args()

    private_key = load_private_key(args.key_file)

    for f in args.files:
        path = Path(f)
        if not path.exists():
            print(f"⚠️  跳过（不存在）: {path}", file=sys.stderr)
            continue
        sign_file(path, private_key)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
