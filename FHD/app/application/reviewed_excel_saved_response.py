"""Revalidate an archived, already answered classification without a model call."""

import base64
import hashlib
import json

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_audit import call_state, verify_request


def saved_classification_answer(
    record: dict, classification_id: str, version: str, source_sha: str
):
    """Return the original answer only after checking its identity, request and receipt."""
    if (
        call_state(record) != "answered_invalid"
        or record.get("phase") != "classification"
        or record.get("classification_id") != classification_id
        or record.get("classification_version") != version
        or record.get("source_sha256") != source_sha
        or record.get("http_status") != 200
    ):
        raise ReviewedExcelError("已保存的模型回执与当前分类不匹配")
    request = record.get("request")
    if not isinstance(request, dict):
        raise ReviewedExcelError("已保存的模型请求不可核验")
    verify_request(request, record.get("request_sha256", ""))
    try:
        body = base64.b64decode(record.get("response_base64", ""), validate=True)
        if hashlib.sha256(body).hexdigest() != record.get("response_sha256"):
            raise ValueError("receipt hash mismatch")
        text = body.decode("utf-8")
        chunks, done, event = [], None, ""
        for line in text.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if event == "delta" and isinstance(payload.get("delta"), str):
                    chunks.append(payload["delta"])
                elif event == "done":
                    if done is not None:
                        raise ValueError("duplicate completion")
                    done = payload
                elif event == "error":
                    raise ValueError("provider error")
        answer = "".join(chunks)
        if not isinstance(done, dict) or done.get("ok") is not True or not answer:
            raise ValueError("missing completion")
        if done.get("content") != answer or done.get("finish_reason") not in (None, "stop"):
            raise ValueError("incomplete or inconsistent response")
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError) as exc:
        raise ReviewedExcelError("已保存的模型回执不完整或校验失败") from exc
    return answer, request
