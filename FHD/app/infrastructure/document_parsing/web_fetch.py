"""网页正文抓取（成熟组件复用：trafilatura，Apache-2.0）。

只用于知识库 URL 导入。默认拒绝内网/回环地址，逐跳校验重定向，
限制体积与跳数，避免 SSRF 与超大响应。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from email.message import Message
from urllib.parse import urljoin, urlsplit

import urllib3

from app.utils.operational_errors import BOUNDARY_ERRORS

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_S = 15


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    text: str


def _allow_private() -> bool:
    return (os.environ.get("XCAGI_KB_ALLOW_PRIVATE_URLS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def assert_public_http_url(url: str) -> str:
    """Validate every resolved address and return the numeric connection target."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL 必须是有效的 http(s) 地址")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"域名无法解析：{parsed.hostname}") from exc
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses:
        raise ValueError(f"域名无法解析：{parsed.hostname}")
    if not _allow_private() and any(
        not ip.is_global or ip.is_multicast or ip.is_reserved for ip in addresses
    ):
        raise ValueError(f"禁止抓取内网地址：{parsed.hostname}")
    return str(addresses[0])


def _read_limited(response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.stream(64 * 1024, decode_content=True):
        total += len(chunk)
        if total > MAX_BYTES:
            raise ValueError(f"网页体积超过限制（>{MAX_BYTES // 1024 // 1024}MB）")
        chunks.append(chunk)
    return b"".join(chunks)


def extract_html_text(html: str, *, url: str = "") -> tuple[str, str]:
    """从 HTML 提取 (正文, 标题)；无正文抛 ValueError。URL 导入与本地 HTML 共用。"""
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = str(getattr(meta, "title", "") or "")
    except BOUNDARY_ERRORS as exc:
        raise ValueError("网页正文提取失败") from exc
    if not text or not text.strip():
        raise ValueError("网页未提取到正文，可能是动态渲染页面")
    return text.strip(), title


def fetch_url_text(url: str) -> FetchedPage:
    """抓取网页并提取正文；失败抛 ValueError（调用方转 400）。"""
    current = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        address = assert_public_http_url(current)
        parsed = urlsplit(current)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii")
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        # Pin the checked IP, while retaining the origin Host, TLS SNI and
        # certificate identity. Direct pools do not inherit environment proxies.
        pool = (
            urllib3.HTTPSConnectionPool(
                address,
                port=parsed.port,
                server_hostname=hostname,
                assert_hostname=hostname,
                cert_reqs="CERT_REQUIRED",
            )
            if parsed.scheme == "https"
            else urllib3.HTTPConnectionPool(address, port=parsed.port)
        )
        target = parsed.path or "/"
        if parsed.query:
            target += f"?{parsed.query}"
        try:
            with pool:
                response = pool.request(
                    "GET",
                    target,
                    timeout=TIMEOUT_S,
                    redirect=False,
                    retries=False,
                    preload_content=False,
                    headers={"Host": authority, "User-Agent": "XCAGI-KnowledgeBot/1.0"},
                )
                try:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location") or ""
                        if not location:
                            raise ValueError("重定向缺少 location")
                        current = urljoin(current, location)
                        continue
                    if response.status >= 400:
                        raise ValueError(f"网页返回 HTTP {response.status}")
                    raw = _read_limited(response)
                    content_type = Message()
                    content_type["content-type"] = response.headers.get("content-type", "")
                    html = raw.decode(
                        content_type.get_content_charset() or "utf-8", errors="replace"
                    )
                finally:
                    response.close()
        except (urllib3.exceptions.HTTPError, OSError, LookupError) as exc:
            raise ValueError("网页请求失败") from exc
        break
    else:
        raise ValueError("重定向次数过多")

    text, title = extract_html_text(html, url=current)
    return FetchedPage(url=current, title=title, text=text)
