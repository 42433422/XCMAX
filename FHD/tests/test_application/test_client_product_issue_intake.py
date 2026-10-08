from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import zipfile
from types import SimpleNamespace as NS

import pytest

from app.application.client_product_issue_intake import (
    classify_report,
    looks_like_issue_report,
    submit_product_issue,
)


@pytest.fixture
def intake_env(tmp_path, monkeypatch):
    """客户上报所需的最小环境：脱敏支持包、市场凭据、可覆盖的客户端身份。"""
    from app import build_identity
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
    evidence = {"kind": "support_bundle", "path": str(path), "sha256": sha, "bytes": len(raw)}
    monkeypatch.setattr(support_bundle, "build_evidence_ref", lambda **_: evidence)

    async def _token(_request):
        return "test-account-token"

    monkeypatch.setattr(private_mod_delivery_context, "_private_delivery_market_token", _token)

    def identity(*, instance: str, version: str, git_sha: str) -> None:
        monkeypatch.setattr(desktop_delivery_receipt, "desktop_installation_id", lambda: instance)
        monkeypatch.setattr(
            build_identity,
            "build_identity",
            lambda: {"product_version": version, "git_sha": git_sha},
        )

    return NS(raw=raw, sha=sha, identity=identity, evidence=evidence)


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
    assert looks_like_issue_report("登录后软件不能用")
    assert not looks_like_issue_report("请写入验收文本。不能用排队或待审批代替完成。")


def test_report_classifier_does_not_escalate_usage_question_or_bad_json():
    client, _ = _client(
        '{"type":"usage_question","confidence":0.99,"expected":"",'
        '"actual":"","missing_evidence":[]}'
    )
    assert classify_report(client, "不会操作", "我来教你。")["type"] == "usage_question"
    broken, _ = _client("not-json")
    assert classify_report(broken, "按钮没反应", "请联系支持。") is None


@pytest.mark.parametrize("ack, saved", [
    ("matching", True), ("missing", False), ("wrong_digest", False), ("non_boolean", False),
])
def test_product_issue_routes_one_work_order_and_support_bundle(intake_env, monkeypatch, ack, saved):
    from app.application import client_product_issue_intake as intake

    intake_env.identity(instance="client-instance-41", version="1.0.0.5", git_sha="c" * 40)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((token, route, method, payload))
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-abcdef123456", "status": "candidate", "created": True}
        return {"success": True, "ticket_id": 12, "ticket_no": "CS-12", **({} if ack == "missing" else {
            "support_bundle_saved": "true" if ack == "non_boolean" else True,
            "support_bundle_sha256": "0" * 64 if ack == "wrong_digest" else intake_env.sha,
        })}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    result = asyncio.run(
        submit_product_issue(
            request=object(),
            tenant_id=41,
            customer_message="按钮没反应，保存操作失败",
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
        "support_bundle_saved": saved,
        "support_bundle_sha256": intake_env.sha if saved else "",
    }
    from app.fastapi_routes.xcagi_compat_chat_stream import _client_issue_reply
    reply = _client_issue_reply({**result, "screenshots": {"selected": 1, "included": 1}})
    assert "CS-12" in reply and "WO-abcdef123456" in reply
    assert ("支持包已附截图" in reply) is saved
    assert ("本次诊断附件保存尚未确认" in reply) is not saved
    assert (intake_env.sha in reply) is saved
    assert len(calls) == 2 and calls[0][1].endswith("customer-candidate")
    assert calls[0][3]["expected"] == "保存成功"
    assert calls[0][3]["client_instance_id"] == "client-instance-41"
    assert calls[1][3]["source_ref"] == calls[1][3]["work_order_id"]
    assert base64.b64decode(calls[1][3]["support_bundle_base64"]) == intake_env.raw
    # 同一工单重复上报（客户重测/补报）必须原样复用 description：市场端据此判定
    # 「同一需求标识是否绑定同一内容」，混入每次都变的支持包摘要会被判 409。
    assert intake_env.sha not in calls[1][3]["description"]
    assert calls[1][3]["support_bundle_sha256"] == intake_env.sha


def test_screenshots_attached_to_the_report_reach_the_support_bundle(intake_env, monkeypatch):
    import importlib

    from app.application import client_product_issue_intake as intake
    from app.desktop_runtime import support_bundle

    stream = importlib.import_module("app.fastapi_routes.xcagi_compat_chat_stream")
    intake_env.identity(instance="client-instance-6", version="1.0.0.5", git_sha="f" * 40)
    bundled = []

    def evidence(*, screenshots):
        bundled.append(screenshots)
        return {**intake_env.evidence, "screenshots": {"selected": 1, "included": 1}}

    async def remote(token, route, *, method="GET", payload=None):
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-0123456789ab", "status": "candidate", "created": True}
        return {"success": True, "ticket_id": 6, "ticket_no": "CI6",
                "support_bundle_saved": True, "support_bundle_sha256": intake_env.sha}

    monkeypatch.setattr(support_bundle, "build_evidence_ref", evidence)
    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    attachments = [
        {"kind": "image", "data_url": "data:image/png;base64," + base64.b64encode(b"png").decode()},
        {"kind": "pdf", "data_url": "data:application/pdf;base64,JVBERi0="},
        {"kind": "image", "data_url": "data:image/png;base64,@@@"},
        "not-a-row",
    ]
    receipt = stream._classify_and_submit_client_issue(
        object(),
        {"tenant_id": 6, "multimodal_attachments": attachments},
        "导出报表报错。期望：导出成功。实际：提示服务器内部错误。",
        "",
        client=object(),
    )
    assert bundled == [[b"png"]]
    assert receipt["state"] == "ROUTED" and receipt["screenshots"]["included"] == 1
    assert "支持包已附截图 1/1 张" in stream._client_issue_reply(receipt)


def test_intake_still_creates_work_order_when_client_version_is_unresolvable(
    intake_env, monkeypatch
):
    """版本未知回退为 unknown，仍可正常建单。"""
    from app.application import client_product_issue_intake as intake

    intake_env.identity(instance="client-instance-77", version="", git_sha="d" * 40)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append(payload)
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-versionless00", "status": "candidate", "created": True}
        return {"success": True, "ticket_id": 9, "ticket_no": "CS-9"}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    result = asyncio.run(
        submit_product_issue(
            request=object(),
            tenant_id=41,
            customer_message="保存采购订单报错，点保存没有任何反应",
            triage={
                "type": "product_defect",
                "confidence": 0.95,
                "expected": "保存成功",
                "actual": "报服务器内部错误",
                "missing_evidence": [],
            },
        )
    )
    assert result["state"] == "ROUTED", "版本未知不得阻断建单"
    assert calls[0]["product_version"] == "unknown"
    assert calls[1]["product_version"] == "unknown"


def test_repeat_report_reuses_existing_ticket_when_market_refuses_replay(intake_env, monkeypatch):
    """拒绝补报时保留原工单号，同时不冒充新附件已保存。"""
    from app.application import client_product_issue_intake as intake

    intake_env.identity(instance="client-instance-55", version="1.0.0.5", git_sha="e" * 40)
    routes = []

    async def remote(token, route, *, method="GET", payload=None):
        routes.append(route)
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-18443017efd5", "status": "in_dev", "created": False}
        if route.endswith("issues/intake"):
            raise RuntimeError("相同需求标识已绑定其他内容，请使用新的 source_ref")
        return {
            "items": [
                {"id": 7, "ticket_no": "CI-existing", "evidence": {"source_ref": "WO-other"}},
                {
                    "id": 12,
                    "ticket_no": "CI6412760e",
                    "evidence": {"source_ref": "WO-18443017efd5"},
                },
            ]
        }

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    result = asyncio.run(
        submit_product_issue(
            request=object(),
            tenant_id=1,
            customer_message="保存采购订单报错，点保存没有任何反应",
            triage={
                "type": "product_defect",
                "confidence": 0.9,
                "expected": "保存成功",
                "actual": "报服务器内部错误",
                "missing_evidence": [],
            },
        )
    )
    assert result["state"] == "ROUTED", "重复上报必须仍返回工单编号"
    assert result["work_order_id"] == "WO-18443017efd5"
    assert result["owner_ticket_id"] == 12
    assert result["owner_ticket_no"] == "CI6412760e"
    assert any("tickets" in route for route in routes)
    assert result["support_bundle_saved"] is False and result["support_bundle_sha256"] == ""
    from app.fastapi_routes.xcagi_compat_chat_stream import _client_issue_reply
    reply = _client_issue_reply(result)
    assert "CI6412760e" in reply and "本次诊断附件保存尚未确认" in reply
    assert intake_env.sha not in reply and "已附截图" not in reply


def test_defect_report_is_not_swallowed_when_classification_unavailable():
    """分类不可用时引导补充期望/实际，保留真实回执与二次判定行为。"""
    import importlib

    stream = importlib.import_module("app.fastapi_routes.xcagi_compat_chat_stream")
    message = "保存采购订单的时候报错，点保存没有任何反应，这应该是软件缺陷，请处理"

    class _Boom:
        """分类调用抛意外异常（如无凭据/网络被代理拦截）。"""

        default_model = "boom"

        def __init__(self):
            def _create(**kwargs):
                raise RuntimeError("no llm credential")

            self.chat = NS(completions=NS(create=_create))

    receipt = stream._classify_and_submit_client_issue(object(), {}, message, "", client=_Boom())
    assert receipt is not None, "缺陷上报不得静默回落业务分发"
    assert receipt["state"] == "NEEDS_MORE_EVIDENCE"
    reply = stream._client_issue_reply(receipt)
    assert "期望" in reply and "实际" in reply

    # 受理成功时客户必须看到真实编号（原客户问题：永远拿不到工单编号）
    routed = stream._client_issue_reply(
        {
            "state": "ROUTED",
            "work_order_id": "WO-18443017efd5",
            "owner_ticket_no": "CI5a10d66d11e4d49777fccc2af13235a88df742fa3c82bf97",
        }
    )
    assert "WO-18443017efd5" in routed, "回执必须包含 Work Order 编号"
    assert "CI5a10" in routed, "回执必须包含市场工单号"

    # 规划器已给出答案后的二次判定：不追加引导噪声
    assert (
        stream._classify_and_submit_client_issue(
            object(), {}, message, "已有答案", client=_Boom(), guide_unavailable=False
        )
        is None
    )
