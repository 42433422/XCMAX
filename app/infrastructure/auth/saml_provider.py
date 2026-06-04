"""SAML 2.0 SP（HTTP-Redirect 登录 + POST ACS；可选 signxml 签名校验）。"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import urllib.parse
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NS = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "saml2": "urn:oasis:names:tc:SAML:2.0:assertion"}


def saml_enabled() -> bool:
    return os.environ.get("XCAGI_SAML_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def saml_signature_verify_required() -> bool:
    """生产默认校验 Response 签名；开发可设 XCAGI_SAML_SKIP_SIGNATURE_VERIFY=1。"""
    if _env_flag("XCAGI_SAML_SKIP_SIGNATURE_VERIFY"):
        return False
    from app.utils.deployment import deployment_is_production, deployment_is_staging

    if deployment_is_production() or deployment_is_staging():
        return True
    return _env_flag("XCAGI_SAML_VERIFY_SIGNATURE")


def _config() -> dict[str, str]:
    entity = os.environ.get("XCAGI_SAML_SP_ENTITY_ID", "").strip()
    meta = os.environ.get("XCAGI_SAML_IDP_METADATA_URL", "").strip()
    acs = os.environ.get("XCAGI_SAML_ACS_URL", "").strip()
    if not all((entity, meta, acs)):
        raise ValueError(
            "SAML 未完整配置：需要 XCAGI_SAML_SP_ENTITY_ID / IDP_METADATA_URL / ACS_URL"
        )
    return {"entity_id": entity, "metadata_url": meta, "acs_url": acs}


def _decode_saml_payload(saml_response_b64: str) -> bytes:
    raw = base64.b64decode(saml_response_b64)
    import zlib

    try:
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    except zlib.error:
        return raw


@lru_cache(maxsize=1)
def _cached_idp_cert_pem() -> str:
    cfg = _config()
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(cfg["metadata_url"])
        resp.raise_for_status()
        content = resp.content
    root = ET.fromstring(content)
    for elem in root.iter():
        if elem.tag.endswith("X509Certificate") and (elem.text or "").strip():
            body = "".join(elem.text.split())
            lines = [body[i : i + 64] for i in range(0, len(body), 64)]
            return "-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n"
    raise ValueError("IdP metadata 中未找到 X509Certificate")


def verify_saml_response_signature(xml_bytes: bytes) -> None:
    """校验 SAML Response XML 签名（需 ``pip install -e '.[enterprise]'``）。"""
    if not saml_signature_verify_required():
        return
    try:
        from lxml import etree
        from signxml import XMLVerifier
    except ImportError as exc:
        raise RuntimeError(
            "SAML 签名校验需要 enterprise 依赖：pip install -e '.[enterprise]'"
        ) from exc
    cert_pem = _cached_idp_cert_pem()
    root = etree.fromstring(xml_bytes)
    XMLVerifier().verify(root, x509_cert=cert_pem)


async def fetch_idp_sso_url() -> str:
    cfg = _config()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(cfg["metadata_url"])
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    for elem in root.iter():
        if elem.tag.endswith("SingleSignOnService"):
            loc = elem.attrib.get("Location", "").strip()
            if loc:
                return loc
    raise ValueError("IdP metadata 中未找到 SingleSignOnService")


def _authn_request_xml(entity_id: str, acs_url: str, request_id: str) -> str:
    return (
        f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'ID="{request_id}" Version="2.0" IssueInstant="2026-01-01T00:00:00Z" '
        f'Destination="{acs_url}" AssertionConsumerServiceURL="{acs_url}" '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">{entity_id}</saml:Issuer>'
        f"</samlp:AuthnRequest>"
    )


def _deflate_saml(raw: bytes) -> bytes:
    import zlib

    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return compressor.compress(raw) + compressor.flush()


async def build_login_redirect_url() -> tuple[str, str]:
    cfg = _config()
    sso = await fetch_idp_sso_url()
    rid = f"_{secrets.token_hex(16)}"
    raw = _authn_request_xml(cfg["entity_id"], cfg["acs_url"], rid).encode("utf-8")
    saml_request = base64.b64encode(_deflate_saml(raw)).decode("ascii")
    qs = urllib.parse.urlencode({"SAMLRequest": saml_request, "RelayState": rid})
    return f"{sso}?{qs}", rid


def parse_name_id_from_response(saml_response_b64: str) -> str:
    xml_bytes = _decode_saml_payload(saml_response_b64)
    verify_saml_response_signature(xml_bytes)
    root = ET.fromstring(xml_bytes)
    for elem in root.iter():
        if elem.tag.endswith("NameID") and (elem.text or "").strip():
            return (elem.text or "").strip()
    raise ValueError("SAML Response 中未找到 NameID")


def map_saml_name_to_username(name_id: str) -> str:
    return (name_id or "").strip().lower()[:128] or "saml-user"
