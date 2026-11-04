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
    evidence = {
        "kind": "support_bundle",
        "path": str(path),
        "sha256": sha,
        "bytes": len(raw),
    }
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


def _submit_issue(
    *,
    tenant_id=41,
    customer_message="保存采购订单报错，点保存没有任何反应",
    actual="报服务器内部错误",
    confidence=0.95,
):
    return asyncio.run(
        submit_product_issue(
            request=object(),
            tenant_id=tenant_id,
            customer_message=customer_message,
            triage={
                "type": "product_defect",
                "confidence": confidence,
                "expected": "保存成功",
                "actual": actual,
                "missing_evidence": [],
            },
        )
    )


def test_report_classifier_requires_structured_product_defect():
    client, calls = _client('{"type":"product_defect","confidence":0.93,"actual":"failed"}')
    triage = classify_report(client, "保存时报错", "这是软件缺陷。")
    assert triage["type"] == "product_defect" and triage["actual"] == "failed"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert classify_report(None, "提交产品问题，期望：" + "\t" * 100_000, "")[
        "missing_evidence"
    ] == ["expected_behavior", "actual_behavior"]
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


@pytest.mark.parametrize("ack", ["matching", "missing", "wrong_digest", "non_boolean"])
def test_product_issue_routes_one_work_order_and_support_bundle(intake_env, monkeypatch, ack):
    saved = ack == "matching"
    from app.application import client_product_issue_intake as intake

    intake_env.identity(instance="client-instance-41", version="1.0.0.5", git_sha="c" * 40)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((token, route, method, payload))
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-abcdef123456", "status": "candidate", "created": True}
        result = {"success": True, "ticket_id": 12, "ticket_no": "CS-12"}
        if ack != "missing":
            result["support_bundle_saved"] = "true" if ack == "non_boolean" else True
            result["support_bundle_sha256"] = "0" * 64 if ack == "wrong_digest" else intake_env.sha
        return result

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    result = _submit_issue(
        customer_message="按钮没反应，保存操作失败",
        actual="按钮没有响应",
        confidence=0.94,
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
        return {
            "success": True,
            "ticket_id": 6,
            "ticket_no": "CI6",
            "support_bundle_saved": True,
            "support_bundle_sha256": intake_env.sha,
        }

    monkeypatch.setattr(support_bundle, "build_evidence_ref", evidence)
    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    attachments = [
        {
            "kind": "image",
            "data_url": "data:image/png;base64," + base64.b64encode(b"png").decode(),
        },
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
    result = _submit_issue()
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
                {
                    "id": 7,
                    "ticket_no": "CI-existing",
                    "evidence": {"source_ref": "WO-other"},
                },
                {
                    "id": 12,
                    "ticket_no": "CI6412760e",
                    "evidence": {"source_ref": "WO-18443017efd5"},
                },
            ]
        }

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    result = _submit_issue(tenant_id=1, confidence=0.9)
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


@pytest.mark.parametrize("complete", [False, True])
def test_explicit_report_does_not_initialize_llm(intake_env, monkeypatch, complete):
    from unittest.mock import Mock

    from app.application import client_product_issue_intake as intake
    from app.fastapi_routes import xcagi_compat_chat_stream as stream

    intake_env.identity(instance="synthetic-instance", version="1.0.0.6", git_sha="a" * 40)
    factory = Mock(side_effect=RuntimeError("synthetic model is unavailable"))
    monkeypatch.setattr(stream._facade(), "create_modstore_openai_client_from_request", factory)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((route, method, payload))
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-synthetic", "created": True}
        return {"success": True, "ticket_id": 424242, "ticket_no": "CI-synthetic"}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    message = "【原单010069验收测试，仅提交一次】请为‘管理端基础设施展示不直观’提交产品问题，并返回正式客服受理编号。"
    if complete:
        message += "期望：清晰展示状态。实际：状态文字难以阅读。"
    result = asyncio.run(
        stream._classify_and_submit_client_issue_async(object(), {"tenant_id": 424242}, message, "")
    )
    factory.assert_not_called()
    if complete:
        assert result["state"] == "ROUTED"
        assert result["owner_ticket_no"] == "CI-synthetic"
        assert [entry[0] for entry in calls] == [
            "/api/work-orders/customer-candidate",
            "/api/customer-service/issues/intake",
        ]
    else:
        assert result["state"] == "RECEIVED"
        assert result["owner_ticket_no"] == "CI-synthetic"
        assert set(result["missing_evidence"]) == {
            "expected_behavior",
            "actual_behavior",
        }
        assert [entry[0] for entry in calls] == ["/api/customer-service/issues/intake"]
        assert not calls[0][2].get("work_order_id")
        assert message in calls[0][2]["description"]
        assert "CI-synthetic" in stream._client_issue_reply(result)


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("failure", ["no_session_token", "missing_formal_number"])
def test_model_free_report_still_requires_authenticated_formal_receipt(
    intake_env, monkeypatch, failure, complete
):
    from unittest.mock import Mock

    from app.application import client_product_issue_intake as intake
    from app.fastapi_routes import private_mod_delivery_context
    from app.fastapi_routes import xcagi_compat_chat_stream as stream

    factory = Mock(side_effect=AssertionError("explicit intake must not create an LLM client"))
    monkeypatch.setattr(stream._facade(), "create_modstore_openai_client_from_request", factory)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((route, method))
        if route.endswith("customer-candidate"):
            return {"wo_id": "WO-synthetic"}
        if route.endswith("intake"):
            return {"success": True, "ticket_id": 424242}
        return {"items": []}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    if failure == "no_session_token":

        async def no_token(_request):
            return ""

        monkeypatch.setattr(
            private_mod_delivery_context, "_private_delivery_market_token", no_token
        )
    result = asyncio.run(
        stream._classify_and_submit_client_issue_async(
            object(),
            {"tenant_id": 424242},
            "提交产品问题。" + ("期望：页面正常显示。实际：页面报错。" if complete else ""),
            "",
        )
    )
    factory.assert_not_called()
    assert result["state"] == "OWNER_ROUTE_UNAVAILABLE"
    assert not result.get("owner_ticket_no")
    if failure == "no_session_token":
        assert calls == []
    else:
        assert sum(method == "POST" for _, method in calls) == (2 if complete else 1)
        assert calls[-1][1] == "GET"


@pytest.mark.parametrize(
    "message",
    [
        "帮我提个工单：生产员工页面看不清当前阶段，想显示清楚。",
        "帮我建个工单：交付流程那一块不好看，不容易看懂。",
        "帮我建个工单：客户资料页面的字体想放大一些。",
        "帮我建个工单：各个页面的样式不太统一，我想把整站风格统一一下。",
        "请给客服记个工单：后台侧栏别重复放自动化方针。",
    ],
)
def test_plain_support_request_is_received_before_model_or_business_query(
    intake_env, monkeypatch, message
):
    from unittest.mock import Mock

    from app.application import client_product_issue_intake as intake
    from app.fastapi_routes import xcagi_compat_chat_stream as stream

    model = Mock(side_effect=AssertionError("software feedback must not need a model"))
    monkeypatch.setattr(stream._facade(), "create_modstore_openai_client_from_request", model)
    calls = []

    async def remote(token, route, *, method="GET", payload=None):
        calls.append((route, payload))
        return {"success": True, "ticket_id": 48, "ticket_no": "CI-synthetic-48"}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    receipt = asyncio.run(
        stream._classify_and_submit_client_issue_async(object(), {"tenant_id": 29}, message, "")
    )
    assert receipt["state"] == "RECEIVED"
    assert receipt["owner_ticket_no"] == "CI-synthetic-48"
    assert set(receipt["missing_evidence"]) == {"expected_behavior", "actual_behavior"}
    assert calls == [
        (
            "/api/customer-service/issues/intake",
            {
                "source": "customer_feedback",
                "source_ref": calls[0][1]["source_ref"],
                "title": f"客户端产品问题 · {message}",
                "description": f"客户原话：{message}",
                "issue_domain": "platform",
                "acceptance_criteria": "在原工单补充期望、实际与诊断证据后复现验证。",
            },
        )
    ]
    model.assert_not_called()


@pytest.mark.parametrize(
    "message",
    [
        "怎么提交工单？",
        "请问如何建个工单？",
        "不要帮我建工单。",
        "帮我建个生产工单，明天生产100件铝件。",
        "帮我建个工单：生产100件包装盒。",
        "帮我建个工单：生产100件包装盒，需要走审批。",
        "帮我建个工单：包装车间制造一批纸箱。",
        "帮我建个工单：加工100件物料，生产订单需要排产。",
        "已经建个工单了，帮我查看一下。",
        "不是要建工单，只想知道怎么用。",
        "查询客户的生产工单。",
    ],
)
def test_support_intake_does_not_swallow_usage_negation_or_production(message):
    from app.application.client_product_issue_intake import classify_explicit_report

    assert not looks_like_issue_report(message)
    assert classify_explicit_report(message) is None


@pytest.mark.parametrize(
    "followup",
    [
        "我要建个工单。",
        "刚说的这个记一单。",
        "按上面说的建一个工单。",
        "也给我开一张吧。",
        "刚才说的这个问题帮我提个工单。",
    ],
)
@pytest.mark.parametrize(
    "prior",
    [
        "我想先聊聊每日摘要。现在反馈是它像一堆运维日志，我更想看懂今天做了什么、还有什么要处理。",
        "刚才想反馈的是自治建议的看板，有遮挡或者错位的情况需要再复现看看。",
        "管理端有没有市场总览、入口在哪里、内容齐不齐，这件事我还没确认，想查清楚。",
        "工单里谁是管理员、谁是客户，以及分给哪个管理员，显示和筛选还要核实一下，现在部分页面有身份字段，但我不确定整体做好没有。",
    ],
)
def test_bare_intake_inherits_only_current_conversation_customer_context(
    intake_env, monkeypatch, followup, prior
):
    from app.application import client_product_issue_intake as intake
    from app.fastapi_routes import xcagi_compat_chat_stream as stream

    bodies = []

    async def remote(token, route, *, method="GET", payload=None):
        bodies.append(payload)
        return {"success": True, "ticket_id": 50, "ticket_no": "CI-synthetic-50"}

    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    context = {
        "tenant_id": 29,
        "conversation_id": "original-chat",
        "recent_messages": [
            {"role": "user", "content": prior},
            {"role": "assistant", "content": "处理失败：达到最大迭代次数"},
            {"role": "user", "content": followup},
        ],
    }
    receipt = asyncio.run(
        stream._classify_and_submit_client_issue_async(object(), context, followup, "")
    )
    assert receipt["state"] == "RECEIVED" and receipt["owner_ticket_id"] == 50
    assert prior in bodies[0]["description"] and followup in bodies[0]["description"]
    assert "最大迭代" not in bodies[0]["description"]
    assert "work_order_id" not in bodies[0]


@pytest.mark.parametrize(
    "recent",
    [
        [],
        [{"role": "assistant", "content": "软件页面报错"}],
        [{"role": "user", "content": "明天生产100件铝件。"}],
        [{"role": "user", "content": "明天生产100件铝件，需要走审批。"}],
        [{"role": "user", "content": "软件页面报错", "conversation_id": "other-conversation"}],
        [{"role": "user", "content": "软件页面报错", "actor_id": 88}],
        [
            {"role": "user", "content": "后台页面太乱。"},
            {"role": "assistant", "content": "产品问题已受理，市场工单：CI-existing。"},
        ],
    ],
)
def test_bare_intake_without_unhandled_customer_subject_asks_without_writing(monkeypatch, recent):
    from unittest.mock import Mock

    from app.application import client_product_issue_intake as intake
    from app.fastapi_routes import xcagi_compat_chat_stream as stream

    remote = Mock(side_effect=AssertionError("no duplicate or topic-free intake"))
    monkeypatch.setattr(intake, "custom_delivery_remote_json", remote)
    receipt = asyncio.run(
        stream._classify_and_submit_client_issue_async(
            object(), {"recent_messages": recent}, "我要建个工单。", ""
        )
    )
    assert receipt == {
        "state": "NEEDS_MORE_EVIDENCE",
        "missing_evidence": ["issue_description"],
    }
    assert "不用固定格式" in stream._client_issue_reply(receipt)
    remote.assert_not_called()
