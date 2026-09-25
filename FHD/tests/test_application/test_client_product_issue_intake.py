from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import zipfile
from types import SimpleNamespace as NS

from app.application.client_product_issue_intake import (
    classify_report,
    looks_like_issue_report,
    submit_product_issue,
)


def _client(content: str):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return NS(choices=[NS(message=NS(content=content))])

    return NS(default_model="test-model", chat=NS(completions=NS(create=create))), calls


def test_report_classifier_requires_structured_product_defect():
    client, calls = _client(
        '{"type":"product_defect","confidence":0.93,"expected":"saved",'
        '"actual":"save failed","missing_evidence":[]}'
    )
    triage = classify_report(client, "保存时报错", "这是软件缺陷。")
    assert triage == {
        "type": "product_defect",
        "confidence": 0.93,
        "expected": "saved",
        "actual": "save failed",
        "missing_evidence": [],
    }
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert looks_like_issue_report("保存时报错")
    assert not looks_like_issue_report("怎么导出报表？")


def test_report_classifier_does_not_escalate_usage_question_or_bad_json():
    client, _ = _client(
        '{"type":"usage_question","confidence":0.99,"expected":"",'
        '"actual":"","missing_evidence":[]}'
    )
    assert classify_report(client, "不会操作", "我来教你。")["type"] == "usage_question"
    broken, _ = _client("not-json")
    assert classify_report(broken, "按钮没反应", "请联系支持。") is None


def test_product_issue_routes_one_work_order_and_support_bundle(tmp_path, monkeypatch):
    from app import build_identity
    from app.application import client_product_issue_intake as intake
    from app.application import desktop_delivery_receipt
    from app.desktop_runtime import support_bundle
    from app.fastapi_routes import private_mod_delivery_context

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", '{"redacted":true}')
    raw = archive.getvalue()
    path = tmp_path / "support.zip"
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(
        support_bundle,
        "build_evidence_ref",
        lambda: {"kind": "support_bundle", "path": str(path), "sha256": sha, "bytes": len(raw)},
    )
    monkeypatch.setattr(
        desktop_delivery_receipt, "desktop_installation_id", lambda: "client-instance-41"
    )
    monkeypatch.setattr(
        build_identity,
        "build_identity",
        lambda: {"product_version": "1.0.0.5", "git_sha": "c" * 40},
    )
    monkeypatch.setattr(
        private_mod_delivery_context, "_private_delivery_market_token", lambda _r: _token()
    )
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((token, route, method, payload))
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-abcdef123456", "status": "candidate", "created": True}
        return {"success": True, "ticket_id": 12, "ticket_no": "CS-12"}

    async def _token():
        return "test-account-token"

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    result = asyncio.run(
        submit_product_issue(
            request=object(),
            client=object(),
            tenant_id=41,
            customer_message="按钮没反应，保存操作失败",
            assistant_reply="这是产品缺陷。",
            triage={
                "type": "product_defect",
                "confidence": 0.94,
                "expected": "保存成功",
                "actual": "按钮没有响应",
                "missing_evidence": [],
            },
        )
    )
    assert result == {
        "state": "ROUTED",
        "work_order_id": "WO-abcdef123456",
        "owner_ticket_id": 12,
        "owner_ticket_no": "CS-12",
        "support_bundle_sha256": sha,
    }
    assert len(calls) == 2 and calls[0][1].endswith("customer-candidate")
    assert calls[0][3]["expected"] == "保存成功"
    assert calls[0][3]["client_instance_id"] == "client-instance-41"
    assert calls[1][3]["source_ref"] == calls[1][3]["work_order_id"]
    assert base64.b64decode(calls[1][3]["support_bundle_base64"]) == raw
