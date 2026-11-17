"""网页正文抓取（成熟组件复用：trafilatura，Apache-2.0）。

只用于知识库 URL 导入。默认拒绝内网/回环地址，逐跳校验重定向，
限制体积与跳数，避免 SSRF 与超大响应。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

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


def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL 必须是有效的 http(s) 地址")
    if _allow_private():
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise ValueError(f"域名无法解析：{parsed.hostname}") from exc
    for info in infos:
        raw = info[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError(f"禁止抓取内网地址：{parsed.hostname}")


def _read_limited(response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(64 * 1024):
        total += len(chunk)
        if total > MAX_BYTES:
            raise ValueError(f"网页体积超过限制（>{MAX_BYTES // 1024 // 1024}MB）")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url_text(url: str) -> FetchedPage:
    """抓取网页并提取正文；失败抛 ValueError（调用方转 400）。"""
    import requests

    current = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        assert_public_http_url(current)
        response = requests.get(
            current,
            timeout=TIMEOUT_S,
            allow_redirects=False,
            headers={"User-Agent": "XCAGI-KnowledgeBot/1.0"},
        )
        if response.is_redirect:
            location = response.headers.get("location") or ""
            if not location:
                raise ValueError("重定向缺少 location")
            current = urljoin(current, location)
            continue
        if response.status_code >= 400:
            raise ValueError(f"网页返回 HTTP {response.status_code}")
        response.encoding = response.apparent_encoding or response.encoding
        raw = _read_limited(response)
        html = raw.decode(response.encoding or "utf-8", errors="replace")
        break
    else:
        raise ValueError("重定向次数过多")

    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=current,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        meta = trafilatura.extract_metadata(html, default_url=current)
        title = str(getattr(meta, "title", "") or "")
    except BOUNDARY_ERRORS as exc:
        raise ValueError(f"网页正文提取失败：{exc}") from exc
    if not text or not text.strip():
        raise ValueError("网页未提取到正文，可能是动态渲染页面")
    return FetchedPage(url=current, title=title, text=text.strip())
