"""S3 / S3 兼容对象存储导入（成熟组件：boto3，Apache-2.0）。

只做薄胶水：URI 校验、可选桶白名单、大小上限与错误归一化。
凭证仍由标准 AWS 环境（或 ``XCAGI_S3_ENDPOINT_URL`` 指向的兼容存储）提供。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.utils.operational_errors import BOUNDARY_ERRORS

_DEFAULT_MAX_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class FetchedObject:
    bucket: str
    key: str
    filename: str
    data: bytes


def _max_bytes() -> int:
    raw = (os.environ.get("XCAGI_KB_MAX_OBJECT_BYTES") or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_BYTES


def _allowed_buckets() -> set[str]:
    raw = (os.environ.get("XCAGI_S3_ALLOWED_BUCKETS") or "").strip()
    return {part.strip() for part in raw.replace(";", ",").split(",") if part.strip()}


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """解析 ``s3://bucket/key``；非法输入抛 ValueError。"""
    text = (uri or "").strip()
    if not text.lower().startswith("s3://"):
        raise ValueError("对象地址必须以 s3:// 开头")
    remainder = text[5:]
    bucket, _, key = remainder.partition("/")
    bucket = bucket.strip()
    key = key.strip().lstrip("/")
    if not bucket or not key:
        raise ValueError("对象地址必须包含桶名和对象键")
    if "\\" in key or any(ord(ch) < 32 for ch in key):
        raise ValueError("对象键包含非法字符")
    return bucket, key


def _client():
    import boto3

    kwargs: dict[str, str] = {}
    endpoint = (os.environ.get("XCAGI_S3_ENDPOINT_URL") or "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    region = (os.environ.get("XCAGI_S3_REGION") or "").strip()
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs)


def fetch_object(uri: str, *, client=None) -> FetchedObject:
    """读取对象内容；失败抛 ValueError（调用方转 400）。"""
    bucket, key = parse_s3_uri(uri)
    allowed = _allowed_buckets()
    if allowed and bucket not in allowed:
        raise ValueError(f"桶不在允许列表中：{bucket}")
    limit = _max_bytes()
    s3 = client if client is not None else _client()
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except BOUNDARY_ERRORS as exc:
        raise ValueError(f"对象存储读取失败：{exc}") from exc
    body = response.get("Body")
    if body is None:
        raise ValueError("对象存储返回空响应体")
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = body.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError(f"对象超过大小限制（>{limit // 1024 // 1024}MB）")
            chunks.append(chunk)
    except BOUNDARY_ERRORS as exc:
        raise ValueError(f"对象读取失败：{exc}") from exc
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    filename = key.rsplit("/", 1)[-1] or "object"
    return FetchedObject(bucket=bucket, key=key, filename=filename, data=b"".join(chunks))
