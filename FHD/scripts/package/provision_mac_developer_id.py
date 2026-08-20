#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""通过 App Store Connect API 签发 Developer ID Application 并导入本机钥匙串。

依赖环境变量（可由 setup-mac-signing.sh 从 GitHub Secrets 注入）：
  APP_STORE_CONNECT_API_KEY_ID
  APP_STORE_CONNECT_API_ISSUER_ID
  APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64  或  APP_STORE_CONNECT_API_KEY_PATH
  APPLE_TEAM_ID（可选，默认从 IOS_TEAM_ID 读取）
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import jwt
import requests

API_BASE = "https://api.appstoreconnect.apple.com/v1"
CERT_TYPE = "DEVELOPER_ID_APPLICATION"
CONFIG_DIR = Path.home() / ".config" / "xcagi"
KEY_PATH = CONFIG_DIR / "developer_id_application.key"
CSR_PATH = CONFIG_DIR / "developer_id_application.csr"
CER_PATH = CONFIG_DIR / "developer_id_application.cer"


def _env(name: str, fallback: str = "") -> str:
    return (os.environ.get(name) or fallback).strip()


def _api_key_bytes() -> bytes:
    path = _env("APP_STORE_CONNECT_API_KEY_PATH")
    if path:
        return Path(path).read_bytes()
    raw = _env("APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64")
    if not raw:
        raise SystemExit(
            "缺少 App Store Connect API 私钥：设置 APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64 或 APP_STORE_CONNECT_API_KEY_PATH"
        )
    return base64.b64decode(raw)


def _make_token() -> str:
    key_id = _env("APP_STORE_CONNECT_API_KEY_ID")
    issuer_id = _env("APP_STORE_CONNECT_API_ISSUER_ID")
    if not key_id or not issuer_id:
        raise SystemExit("缺少 APP_STORE_CONNECT_API_KEY_ID / APP_STORE_CONNECT_API_ISSUER_ID")
    private_key = _api_key_bytes()
    headers = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


def _api_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token()}", "Content-Type": "application/json"}


def find_keychain_developer_id() -> str | None:
    proc = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if "Developer ID Application" in line:
            m = re.search(r'"([^"]+)"', line)
            if m:
                return m.group(1)
    return None


def list_remote_certificates() -> list[dict]:
    url = f"{API_BASE}/certificates?filter[certificateType]={CERT_TYPE}&limit=20"
    resp = requests.get(url, headers=_api_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json().get("data", [])


def generate_csr() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        subprocess.run(
            ["openssl", "genrsa", "-out", str(KEY_PATH), "2048"],
            check=True,
        )
        KEY_PATH.chmod(0o600)
    team = _env("APPLE_TEAM_ID", _env("IOS_TEAM_ID"))
    subj = "/CN=XCAGI Desktop Developer ID/O=XCAGI/C=CN"
    if team:
        subj += f"/OU={team}"
    subprocess.run(
        ["openssl", "req", "-new", "-key", str(KEY_PATH), "-out", str(CSR_PATH), "-subj", subj],
        check=True,
    )


def create_certificate() -> str:
    csr_b64 = base64.b64encode(CSR_PATH.read_bytes()).decode("ascii")
    body = {
        "data": {
            "type": "certificates",
            "attributes": {
                "certificateType": CERT_TYPE,
                "csrContent": csr_b64,
            },
        }
    }
    resp = requests.post(f"{API_BASE}/certificates", headers=_api_headers(), json=body, timeout=120)
    if resp.status_code >= 400:
        raise SystemExit(f"创建证书失败 HTTP {resp.status_code}: {resp.text[:800]}")
    attrs = resp.json()["data"]["attributes"]
    content = attrs.get("certificateContent", "")
    if not content:
        raise SystemExit(f"API 未返回 certificateContent: {json.dumps(resp.json())[:500]}")
    cert_der = base64.b64decode(content)
    CER_PATH.write_bytes(cert_der)
    return attrs.get("serialNumber", "")


def import_keychain() -> None:
    subprocess.run(
        [
            "security",
            "import",
            str(CER_PATH),
            "-k",
            str(Path.home() / "Library/Keychains/login.keychain-db"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "security",
            "import",
            str(KEY_PATH),
            "-k",
            str(Path.home() / "Library/Keychains/login.keychain-db"),
            "-A",
        ],
        check=True,
    )
    subprocess.run(
        [
            "security",
            "set-key-partition-list",
            "-S",
            "apple-tool:,apple:,codesign:",
            "-s",
            "-k",
            "",
            str(Path.home() / "Library/Keychains/login.keychain-db"),
        ],
        check=False,
    )


def main() -> int:
    existing = find_keychain_developer_id()
    if existing:
        print(f"[ok] 钥匙串已有 Developer ID: {existing}")
        return 0

    remote = list_remote_certificates()
    active = [
        c
        for c in remote
        if not c.get("attributes", {}).get("expirationDate", "").startswith("1970")
    ]
    if active:
        print(
            "[warn] Apple 账户已有 Developer ID Application 证书，但本机钥匙串缺失私钥。\n"
            "       将创建新 CSR 并申请新证书（旧证书可在 developer.apple.com 吊销）。",
            file=sys.stderr,
        )

    generate_csr()
    serial = create_certificate()
    import_keychain()
    identity = find_keychain_developer_id()
    print(f"[ok] 已签发并导入 Developer ID（serial={serial}）")
    if identity:
        print(f"[ok] CSC_NAME={identity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
