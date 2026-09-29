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
    monkeypatch.setattr(
        support_bundle,
        "build_evidence_ref",
        lambda: {"kind": "support_bundle", "path": str(path), "sha256": sha, "bytes": len(raw)},
    )

    async def _token():
        return "test-account-token"

    monkeypatch.setattr(
        private_mod_delivery_context, "_private_delivery_market_token", lambda _r: _token()
    )

    def identity(*, instance: str, version: str, git_sha: str) -> None:
        monkeypatch.setattr(desktop_delivery_receipt, "desktop_installation_id", lambda: instance)
        monkeypatch.setattr(
            build_identity,
            "build_identity",
            lambda: {"product_version": version, "git_sha": git_sha},
        )

    return NS(raw=raw, sha=sha, identity=identity)


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


def test_product_issue_routes_one_work_order_and_support_bundle(intake_env, monkeypatch):
    from app.application import client_product_issue_intake as intake

    intake_env.identity(instance="client-instance-41", version="1.0.0.5", git_sha="c" * 40)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((token, route, method, payload))
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-abcdef123456", "status": "candidate", "created": True}
        return {"success": True, "ticket_id": 12, "ticket_no": "CS-12"}

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
        "support_bundle_sha256": intake_env.sha,
    }
    assert len(calls) == 2 and calls[0][1].endswith("customer-candidate")
    assert calls[0][3]["expected"] == "保存成功"
    assert calls[0][3]["client_instance_id"] == "client-instance-41"
    assert calls[1][3]["source_ref"] == calls[1][3]["work_order_id"]
    assert base64.b64decode(calls[1][3]["support_bundle_base64"]) == intake_env.raw
    # 同一工单重复上报（客户重测/补报）必须原样复用 description：市场端据此判定
    # 「同一需求标识是否绑定同一内容」，混入每次都变的支持包摘要会被判 409。
    assert intake_env.sha not in calls[1][3]["description"]
    assert calls[1][3]["support_bundle_sha256"] == intake_env.sha


def test_intake_still_creates_work_order_when_client_version_is_unresolvable(
    intake_env, monkeypatch
):
    """无法解析版本标识的客户端也必须能建单。

    市场端 customer-candidate 要求 product_version 非空且至少 1 字符；未打包运行或
    构建身份文件损坏的客户端拿到空串时，接口会以 422 拒绝，客户上报缺陷只得到
    「受理服务尚未送达」。本用例锁定「版本未知 → unknown 回退」，让闭环不被挡住。
    """
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
    """客户重复上报同一问题时，即使市场拒绝重放也必须拿回同一个工单编号。

    市场按 source_ref 绑定需求内容；客户端格式升级或客户补报会让摘要变化，市场以
    409 拒绝。若不回查已有工单，客户重测原问题只会再次收到「受理服务尚未送达」。
    """
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


def test_defect_report_is_not_swallowed_when_classification_unavailable():
    """分类不可用时缺陷上报必须给出明确引导，不得静默回落业务分发。

    客户原问题：缺陷上报只收到普通业务答复、拿不到工单编号。修复把受理分支放到
    业务写分发之前；但若分类不可用就返回 None，仍会落到业务查询把缺陷吃掉。
    本用例锁定「不可用 → NEEDS_MORE_EVIDENCE 引导」，并在二次判定点不追加噪声。
    """
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

    # 规划器已给出答案后的二次判定：不追加引导噪声
    assert (
        stream._classify_and_submit_client_issue(
            object(), {}, message, "已有答案", client=_Boom(), guide_unavailable=False
        )
        is None
    )
