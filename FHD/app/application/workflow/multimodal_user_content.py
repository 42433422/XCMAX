"""将 ``runtime_context["multimodal_attachments"]`` 转为 OpenAI 兼容的 user ``content``。

前端上传图片 / PDF 后，在 ``context`` 中附带 ``multimodal_attachments``（见字段说明）。
无附件时返回纯字符串，与历史行为一致；有附件时返回 ``content`` 数组（text + image_url）。
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import re
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MAX_ATTACHMENTS = 8
_MAX_B64_DECODE_BYTES = 14 * 1024 * 1024  # 单附件解码上限（约 14MB）
_MAX_PDF_TEXT_CHARS = 24_000
_MAX_PDF_PAGES = 10
_MAX_OCR_TEXT_CHARS = 16_000

_ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
_ALLOWED_PDF_MIME = frozenset({"application/pdf"})


class UnsupportedMultimodalModelError(RuntimeError):
    """The selected model cannot consume images and local OCR could not recover text."""


class EmptyMultimodalResponseError(RuntimeError):
    """A multimodal request completed without text or tool output."""


def _normalize_mime(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s == "image/jpg":
        return "image/jpeg"
    return s


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    """解析 ``data:<mime>;base64,<payload>``，返回 (bytes, mime)。"""
    u = (data_url or "").strip()
    m = re.match(r"^data:([^;]+);base64,(.+)$", u, re.IGNORECASE | re.DOTALL)
    if not m:
        raise ValueError("invalid data URL (expected data:<mime>;base64,...)")
    mime = _normalize_mime(m.group(1))
    b64 = m.group(2).strip()
    raw_bytes = base64.standard_b64decode(b64 + "=" * (-len(b64) % 4))
    if len(raw_bytes) > _MAX_B64_DECODE_BYTES:
        raise ValueError("attachment too large after decode")
    return raw_bytes, mime


def _maybe_downscale_image_jpeg(raw: bytes, mime: str) -> tuple[str, str]:
    """过大图片压成 JPEG data URL，降低 token / 限流风险。失败则回退原图 base64 data URL。"""
    try:
        from PIL import Image
    except RECOVERABLE_ERRORS:
        b64 = base64.standard_b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}", mime

    try:
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
        im.thumbnail((2048, 2048))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85, optimize=True)
        out = buf.getvalue()
        b64 = base64.standard_b64encode(out).decode("ascii")
        return f"data:image/jpeg;base64,{b64}", "image/jpeg"
    except RECOVERABLE_ERRORS as exc:
        logger.debug("image downscale skipped: %s", exc)
        b64 = base64.standard_b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}", mime


def _pdf_bytes_to_text(raw: bytes, filename: str) -> str:
    try:
        import pdfplumber
    except RECOVERABLE_ERRORS as exc:
        return f"[PDF {filename}: 无法读取（缺少 pdfplumber: {exc}）]"

    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            chunks: list[str] = []
            for i, page in enumerate(pdf.pages[:_MAX_PDF_PAGES]):
                t = page.extract_text() or ""
                if t.strip():
                    chunks.append(f"--- page {i + 1} ---\n{t.strip()}")
            body = "\n\n".join(chunks).strip()
            if not body:
                return f"[PDF {filename}: 未解析到文本（可能是扫描件）]"
            if len(body) > _MAX_PDF_TEXT_CHARS:
                body = body[:_MAX_PDF_TEXT_CHARS] + "\n…(truncated)"
            return f"[PDF 文件: {filename}]\n{body}"
    except RECOVERABLE_ERRORS as exc:
        logger.info("pdf extract failed name=%r: %s", filename, exc)
        return f"[PDF {filename}: 解析失败 {exc}]"


def build_openai_user_content(
    user_message: str,
    runtime_context: dict[str, Any] | None,
) -> str | list[dict[str, Any]]:
    """返回 ``str``（无附件）或 ``list``（多模态，OpenAI chat.completions 格式）。"""
    msg = (user_message or "").strip()
    if not runtime_context or not isinstance(runtime_context, dict):
        return msg

    raw_list = runtime_context.get("multimodal_attachments")
    if not isinstance(raw_list, list) or not raw_list:
        return msg

    parts: list[dict[str, Any]] = []
    if msg:
        parts.append({"type": "text", "text": msg})

    for item in raw_list[:_MAX_ATTACHMENTS]:
        if not isinstance(item, dict):
            continue
        filename = (
            str(item.get("filename") or item.get("name") or "attachment").strip() or "attachment"
        )
        mime_in = _normalize_mime(str(item.get("mime_type") or item.get("mime") or ""))
        data_url = str(item.get("data_url") or "").strip()
        b64_field = str(item.get("data_base64") or "").strip()
        kind = str(item.get("kind") or "").strip().lower()

        raw_bytes: bytes
        mime: str
        try:
            if data_url.startswith("data:"):
                raw_bytes, mime = _decode_data_url(data_url)
            elif b64_field:
                raw_bytes = base64.standard_b64decode(b64_field + "=" * (-len(b64_field) % 4))
                mime = mime_in or "application/octet-stream"
                if len(raw_bytes) > _MAX_B64_DECODE_BYTES:
                    raise ValueError("attachment too large")
            else:
                parts.append(
                    {
                        "type": "text",
                        "text": f"\n[跳过附件 {filename}: 无 data_url / data_base64]\n",
                    }
                )
                continue
        except (binascii.Error, ValueError, TypeError) as exc:
            parts.append({"type": "text", "text": f"\n[跳过附件 {filename}: {exc}]\n"})
            continue

        if mime_in and mime == "application/octet-stream":
            mime = mime_in

        if kind == "pdf" or mime in _ALLOWED_PDF_MIME:
            parts.append({"type": "text", "text": "\n" + _pdf_bytes_to_text(raw_bytes, filename)})
            continue

        if mime not in _ALLOWED_IMAGE_MIME:
            parts.append(
                {
                    "type": "text",
                    "text": f"\n[跳过不支持的附件类型 {filename}: mime={mime or 'unknown'}]\n",
                }
            )
            continue

        url, out_mime = _maybe_downscale_image_jpeg(raw_bytes, mime)
        parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
        if out_mime != mime:
            logger.debug("image re-encoded %s -> %s (%s)", mime, out_mime, filename)

    if not parts:
        return msg
    if len(parts) == 1 and parts[0].get("type") == "text":
        return str(parts[0].get("text") or msg)
    return parts


def messages_have_image_parts(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in content
        ):
            return True
    return False


def replace_image_parts_with_ocr_text(
    messages: list[dict[str, Any]],
    *,
    model_label: str,
    model_confirmed_text_only: bool,
    recognizer: Callable[[bytes], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Turn image parts into local OCR text for a non-visual chat model.

    The returned messages contain plain string content, which avoids forwarding
    OpenAI multimodal arrays to providers whose catalog classifies the selected
    model as a regular LLM.
    """

    if not messages_have_image_parts(messages):
        return [dict(message) for message in messages]

    if recognizer is None:
        try:
            from app.services.ocr_service import get_ocr_service

            recognizer = get_ocr_service().recognize_text_from_bytes
        except RECOVERABLE_ERRORS as exc:
            capability = "不支持" if model_confirmed_text_only else "未确认支持"
            raise UnsupportedMultimodalModelError(
                f"当前模型 {model_label} {capability}直接读取图片，且本地 OCR 引擎不可用。"
                "请启用视觉模型，或安装 OCR 组件后重试。"
            ) from exc

    transformed: list[dict[str, Any]] = []
    recognized_images = 0
    image_errors: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            transformed.append(dict(message))
            continue

        chunks: list[str] = []
        image_index = 0
        message_recognized = 0
        message_errors: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "")
            if part_type == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    chunks.append(text)
                continue
            if part_type != "image_url":
                continue

            image_index += 1
            image_url = part.get("image_url")
            url = (
                str(image_url.get("url") or "")
                if isinstance(image_url, dict)
                else str(image_url or "")
            ).strip()
            if not url.startswith("data:"):
                message_errors.append(f"第 {image_index} 张图片不是可本地识别的数据附件")
                continue
            try:
                raw, mime = _decode_data_url(url)
                if mime not in _ALLOWED_IMAGE_MIME:
                    message_errors.append(f"第 {image_index} 张图片类型 {mime} 不受支持")
                    continue
                result = recognizer(raw)
                ocr_text = str(result.get("text") or "").strip() if result else ""
                if not ocr_text:
                    reason = str((result or {}).get("message") or "未识别到文字").strip()
                    message_errors.append(f"第 {image_index} 张图片：{reason}")
                    continue
                recognized_images += 1
                message_recognized += 1
                chunks.append(
                    f"[第 {image_index} 张图片的本地 OCR 文字]\n{ocr_text[:_MAX_OCR_TEXT_CHARS]}"
                )
            except RECOVERABLE_ERRORS as exc:
                logger.info("local OCR fallback failed for image %s: %s", image_index, exc)
                message_errors.append(f"第 {image_index} 张图片：OCR 不可用")

        updated = dict(message)
        if image_index:
            image_errors.extend(message_errors)
            if message_recognized:
                guidance = (
                    "[处理说明] 当前模型不直接读取图片，系统已先做本地 OCR。"
                    "请仅根据下列文字回答；无法由文字判断的画面内容请明确说明。"
                )
                if message_errors:
                    guidance += "\n[部分图片未识别] " + "；".join(message_errors)
                chunks.insert(0, guidance)
            updated["content"] = "\n\n".join(chunks).strip()
        transformed.append(updated)

    if recognized_images:
        return transformed

    capability = "不支持" if model_confirmed_text_only else "未确认支持"
    reason = "；".join(image_errors) or "本地 OCR 未识别到可用文字"
    raise UnsupportedMultimodalModelError(
        f"当前模型 {model_label} {capability}直接读取图片，且本地 OCR 无法提取可用文字"
        f"（{reason}）。请启用视觉模型，或上传文字更清晰的截图/文档。"
    )


__all__ = [
    "EmptyMultimodalResponseError",
    "UnsupportedMultimodalModelError",
    "build_openai_user_content",
    "messages_have_image_parts",
    "replace_image_parts_with_ocr_text",
]
