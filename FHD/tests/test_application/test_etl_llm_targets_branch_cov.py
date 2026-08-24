"""ETL LLM 辅助 + 目标适配器行为/分支覆盖率补测。

覆盖模块：
- llm_assist.py / llm_session_provider.py / adviser.py（LLM 大都 mock，专注分支）
- compatibility_presets.py / errors.py
- targets/__init__.py / helpers.py / batch.py / customers.py / orders.py / customer_products.py

数据库类适配器用内存 SQLite（Base.metadata.create_all）+ tenant_scope(1)。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.db.base import Base

# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _reset_llm_circuit():
    from app.application.etl.llm_assist import clear_etl_llm_circuit

    clear_etl_llm_circuit()
    yield
    clear_etl_llm_circuit()


@pytest.fixture(autouse=True)
def _tenant():
    from app.infrastructure.tenant_scope import reset_current_tenant_id, set_current_tenant_id

    token = set_current_tenant_id(1)
    yield
    reset_current_tenant_id(token)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    yield db
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


# --------------------------------------------------------------------------- errors.py


def test_etl_errors():
    e = EtlError("CODE", "msg")
    assert e.code == "CODE" and e.message == "msg" and e.status_code == 400
    assert isinstance(e, RuntimeError)
    nf = EtlNotFound("资源")
    assert nf.code == "ETL_NOT_FOUND" and nf.status_code == 404
    assert "不存在或无权访问" in nf.message
    cf = EtlConflict("C", "m")
    assert cf.status_code == 409 and cf.code == "C"


# --------------------------------------------------------------------------- base helpers


def test_base_json_safe():
    assert json_safe({"a": Decimal("1.5"), "b": [date(2024, 1, 1)], "c": datetime(2024, 1, 1, 1)})
    assert json_safe(Decimal("1.5")) == "1.5"
    assert json_safe("x") == "x"


def test_target_field_and_capability():
    f = TargetField(
        "price", "价格", type="number", required=True, aliases=("单价",), updatable=True
    )
    assert f.required is True and f.type == "number"
    a = TargetAdapter()
    a.type = "demo"
    a.label = "演示"
    a.fields = (f,)
    a.actions = ("new", "skip")
    a.default_match_keys = ("price",)
    a.allow_dynamic_fields = True
    cap = a.capability()
    assert cap["type"] == "demo"
    assert cap["required_fields"] == ["price"]
    assert cap["allow_dynamic_fields"] is True
    assert cap["fields"][0]["key"] == "price"


def test_target_adapter_validate_and_defaults():
    a = TargetAdapter()
    a.fields = (TargetField("k", "字段", required=True),)
    issues = a.validate({"k": ""})
    assert issues and issues[0]["code"] == "ETL_REQUIRED_FIELD_MISSING"
    assert a.validate({"k": "v"}) == []
    dec = a.preview(MagicMock(), {"k": "v"}, allowed_update_fields=set(), context={})
    assert dec.action == "new"
    with pytest.raises(EtlError) as ex:
        a.execute_row(
            MagicMock(), {}, action="new", match_ref="", allowed_update_fields=set(), context={}
        )
    assert ex.value.code == "ETL_TARGET_NOT_IMPLEMENTED"
    with pytest.raises(EtlError) as ex2:
        a.rollback_row(MagicMock(), match_ref="", before={}, after={}, context={})
    assert ex2.value.code == "ETL_TARGET_NOT_REVERSIBLE"
    assert isinstance(PreviewDecision("new"), PreviewDecision)


# --------------------------------------------------------------------------- llm_assist.py


def test_llm_assist_mode_and_limits(monkeypatch):
    from app.application.etl import llm_assist

    monkeypatch.setenv("FHD_ETL_LLM", "0")
    assert llm_assist.etl_llm_mode() == "off"
    monkeypatch.setenv("FHD_ETL_LLM", "true")
    assert llm_assist.etl_llm_mode() == "on"
    monkeypatch.delenv("FHD_ETL_LLM")
    assert llm_assist.etl_llm_mode() == "auto"
    monkeypatch.setenv("FHD_ETL_LLM", "weird")
    assert llm_assist.etl_llm_mode() == "auto"

    monkeypatch.delenv("FHD_ETL_LLM_TIMEOUT", raising=False)
    assert llm_assist.etl_llm_timeout_seconds() == 30.0
    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "5")
    assert llm_assist.etl_llm_timeout_seconds() == 5.0
    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "99")
    assert llm_assist.etl_llm_timeout_seconds() == 60.0
    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "-1")
    assert llm_assist.etl_llm_timeout_seconds() == 1.0
    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "abc")
    assert llm_assist.etl_llm_timeout_seconds() == 30.0

    monkeypatch.delenv("FHD_ETL_LLM_ROW_ADVICE_LIMIT", raising=False)
    assert llm_assist.etl_row_advice_limit() == 20
    monkeypatch.setenv("FHD_ETL_LLM_ROW_ADVICE_LIMIT", "5")
    assert llm_assist.etl_row_advice_limit() == 5
    monkeypatch.setenv("FHD_ETL_LLM_ROW_ADVICE_LIMIT", "999")
    assert llm_assist.etl_row_advice_limit() == 100
    monkeypatch.setenv("FHD_ETL_LLM_ROW_ADVICE_LIMIT", "bad")
    assert llm_assist.etl_row_advice_limit() == 20


def test_llm_assist_request_scope_can_disable_model(monkeypatch):
    from app.application.etl import llm_assist
    from app.application.etl.llm_assist_runtime import (
        bind_request_llm_enabled,
        reset_request_llm_enabled,
    )

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    token = bind_request_llm_enabled(False)
    try:
        assert llm_assist.etl_llm_mode() == "off"
    finally:
        reset_request_llm_enabled(token)
    assert llm_assist.etl_llm_mode() == "on"


def test_llm_assist_public_metadata():
    from app.application.etl.llm_assist import LlmAssistResult

    r = LlmAssistResult()
    meta = r.public_metadata()
    assert meta["used_llm"] is False and meta["advisory_only"] is True and meta["degraded"] is False
    assert "degradation_code" not in meta and "model" not in meta and "billing" not in meta
    r.degraded = True
    r.degradation_code = "X"
    r.model = "m1"
    r.billing = {"a": 1}
    meta2 = r.public_metadata()
    assert (
        meta2["degradation_code"] == "X" and meta2["model"] == "m1" and meta2["billing"] == {"a": 1}
    )


def test_llm_assist_degradation_code_exception_types():
    from app.application.etl.llm_assist import (
        _circuit_cooldown_seconds,
        _circuit_key,
        _degradation_code,
        _owner_call_lock,
    )

    assert _degradation_code(RuntimeError("quota exhausted")) == "ETL_LLM_QUOTA_EXHAUSTED"
    assert _degradation_code(RuntimeError("429 Too Many")) == "ETL_LLM_QUOTA_EXHAUSTED"
    assert _degradation_code(RuntimeError("额度不足")) == "ETL_LLM_QUOTA_EXHAUSTED"
    assert _degradation_code(RuntimeError("boom")) == "ETL_LLM_UNAVAILABLE"

    assert _circuit_cooldown_seconds("ETL_LLM_QUOTA_EXHAUSTED") == 300.0
    assert _circuit_cooldown_seconds("ETL_LLM_UNAVAILABLE") == 30.0
    assert _owner_call_lock("k1") is _owner_call_lock("k1")


def test_llm_assist_circuit_key(monkeypatch):
    from app.application.etl import llm_assist

    with patch("app.application.etl.llm_session_provider.current_etl_llm_owner", return_value=7):
        assert llm_assist._circuit_key() == "owner:7"
    with patch("app.application.etl.llm_session_provider.current_etl_llm_owner", return_value=None):
        assert llm_assist._circuit_key() == "process"
    with patch(
        "app.application.etl.llm_session_provider.current_etl_llm_owner",
        side_effect=RuntimeError("no ctx"),
    ):
        assert llm_assist._circuit_key() == "process"


def test_llm_assist_circuit_crud(monkeypatch):
    from app.application.etl import llm_assist

    assert llm_assist._circuit_degradation("ck") == ""
    monkeypatch.setenv("FHD_ETL_LLM_FAILURE_COOLDOWN_SECONDS", "bad")
    monkeypatch.setenv("FHD_ETL_LLM_QUOTA_COOLDOWN_SECONDS", "bad")
    llm_assist._open_circuit("ck", "ETL_LLM_UNAVAILABLE")
    assert llm_assist._circuit_degradation("ck") == "ETL_LLM_UNAVAILABLE"
    llm_assist.clear_etl_llm_circuit()
    assert llm_assist._circuit_degradation("ck") == ""


def test_llm_assist_bounded_completion_success(monkeypatch):
    from app.application.etl import llm_assist
    from app.infrastructure.llm.structured_output import StructuredResult

    captured = {}

    def fake_complete(messages, **kw):
        captured["kw"] = kw
        return StructuredResult(
            data={"ok": True}, attempts=1, repaired=False, model="m", billing={"b": 1}
        )

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync", fake_complete
    )
    out = llm_assist._bounded_structured_completion(
        [{"role": "user", "content": "hi"}],
        schema={},
        max_tokens=10,
        timeout_seconds=2,
        conversation_service=None,
        provider=None,
    )
    assert out.data == {"ok": True}
    assert captured["kw"]["max_repairs"] == 0 and captured["kw"]["profile"] == "etl"


def test_llm_assist_bounded_completion_error(monkeypatch):
    from app.application.etl import llm_assist

    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_structured_sync", boom)
    with pytest.raises(RuntimeError):
        llm_assist._bounded_structured_completion(
            [], schema={}, max_tokens=1, timeout_seconds=2, conversation_service=None, provider=None
        )


def test_llm_assist_bounded_completion_timeout(monkeypatch):
    from app.application.etl import llm_assist

    def slow(*a, **k):
        import time

        time.sleep(3)
        return "x"

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_structured_sync", slow)
    with pytest.raises(TimeoutError):
        llm_assist._bounded_structured_completion(
            [], schema={}, max_tokens=1, timeout_seconds=1, conversation_service=None, provider=None
        )


def test_llm_assist_active_software_llm(monkeypatch):
    from app.application.etl import llm_assist

    class FakeProvider:
        pass

    # market provider path
    with patch(
        "app.application.etl.llm_session_provider.current_owner_market_provider",
        return_value=FakeProvider(),
    ):
        configured, service, provider = llm_assist._active_software_llm()
        assert configured is True and service is None and provider is not None

    # registry active provider path
    with (
        patch(
            "app.application.etl.llm_session_provider.current_owner_market_provider",
            return_value=None,
        ),
        patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=FakeProvider(),
        ),
    ):
        assert llm_assist._active_software_llm() == (True, None, None)

    # conversation service path
    with (
        patch(
            "app.application.etl.llm_session_provider.current_owner_market_provider",
            return_value=None,
        ),
        patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            side_effect=lambda *a, **k: FakeProvider() if "conversation_service" in k else None,
        ),
        patch(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            return_value=object(),
        ),
    ):
        configured, service, provider = llm_assist._active_software_llm()
        assert configured is True and service is not None and provider is None

    # none configured
    with (
        patch(
            "app.application.etl.llm_session_provider.current_owner_market_provider",
            return_value=None,
        ),
        patch("app.infrastructure.llm.providers.registry.get_active_provider", return_value=None),
        patch(
            "app.services.ai_conversation_service.get_ai_conversation_service", return_value=None
        ),
    ):
        assert llm_assist._active_software_llm() == (False, None, None)

    # recoverable error
    with patch(
        "app.application.etl.llm_session_provider.current_owner_market_provider",
        side_effect=RuntimeError("boom"),
    ):
        assert llm_assist._active_software_llm() == (False, None, None)


def test_llm_assist_enabled(monkeypatch):
    from app.application.etl import llm_assist

    monkeypatch.setenv("FHD_ETL_LLM", "off")
    assert llm_assist.etl_llm_enabled() is False
    monkeypatch.setenv("FHD_ETL_LLM", "auto")
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        assert llm_assist.etl_llm_enabled() is True
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(False, None, None)
    ):
        assert llm_assist.etl_llm_enabled() is False
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(False, None, None)
    ):
        assert llm_assist.etl_llm_enabled() is True


def _patch_complete(monkeypatch, data):
    from app.infrastructure.llm.structured_output import StructuredResult

    def fake(messages, **kw):
        return StructuredResult(data=data, attempts=1, repaired=False, model="m", billing={"b": 1})

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_structured_sync", fake)


def test_llm_assist_complete_off_and_not_configured(monkeypatch):
    from app.application.etl import llm_assist

    monkeypatch.setenv("FHD_ETL_LLM", "off")
    r = llm_assist._complete([], schema={}, max_tokens=1)
    assert r.used_llm is False and r.degraded is False

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(False, None, None)
    ):
        r2 = llm_assist._complete([], schema={}, max_tokens=1)
        assert r2.degraded is True and r2.degradation_code == "ETL_LLM_UNAVAILABLE"

    monkeypatch.setenv("FHD_ETL_LLM", "auto")
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(False, None, None)
    ):
        r3 = llm_assist._complete([], schema={}, max_tokens=1)
        assert r3.degraded is False and r3.degradation_code == ""


def test_llm_assist_complete_success_and_circuit(monkeypatch):
    from app.application.etl import llm_assist

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    _patch_complete(monkeypatch, {"regions": []})
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        r = llm_assist._complete([], schema={}, max_tokens=1)
        assert r.used_llm is True and r.model == "m" and r.billing == {"b": 1}

    # failure opens circuit -> subsequent call degraded early
    def boom(*a, **k):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_structured_sync", boom)
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        r2 = llm_assist._complete([], schema={}, max_tokens=1)
        assert r2.degraded is True and r2.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"
        r3 = llm_assist._complete([], schema={}, max_tokens=1)
        assert r3.degraded is True and r3.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"


def test_llm_assist_batch_advice_reviews_all_items(monkeypatch):
    from app.application.etl import llm_assist

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    _patch_complete(
        monkeypatch,
        {
            "overall_judgment": "先完整留存，再按预演结果入库",
            "reasoning": ["高置信资料可入库"] * 6,
            "cautions": ["阻断错误先修复"],
            "questions": ["是否保留低置信资料？"],
        },
    )
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        result = llm_assist.advise_batch_plan(
            [
                {
                    "file_name": "发货单/国圣化工.xlsx",
                    "target_type": "shipment_records",
                    "database_recommended": True,
                    "knowledge_ready": True,
                },
                {
                    "file_name": "发货单/对账.xlsx",
                    "target_type": "knowledge",
                    "database_recommended": False,
                    "knowledge_ready": True,
                },
            ],
            "发货单文件夹",
        )

    assert result.used_llm is True
    assert result.data["overall_judgment"] == "先完整留存，再按预演结果入库"
    assert len(result.data["reasoning"]) == 4
    assert llm_assist.advise_batch_plan([], "空批次").used_llm is False


def test_llm_assist_complete_unexpected_provider_error_degrades(monkeypatch):
    from app.application.etl import llm_assist

    class ProviderContractError(Exception):
        pass

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProviderContractError("bad output")),
    )
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        result = llm_assist._complete([], schema={}, max_tokens=1)

    assert result.used_llm is True
    assert result.degraded is True
    assert result.degradation_code == "ETL_LLM_UNAVAILABLE"


def test_llm_assist_circuit_blocked_before_call(monkeypatch):
    from app.application.etl import llm_assist

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    llm_assist._open_circuit("process", "ETL_LLM_UNAVAILABLE")
    # _circuit_key returns "process" when no owner
    r = llm_assist._complete([], schema={}, max_tokens=1)
    assert r.degraded is True


def test_llm_assist_advise_workbook_regions(monkeypatch):
    from app.application.etl import llm_assist

    assert llm_assist.advise_workbook_regions([]).used_llm is False
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    _patch_complete(
        monkeypatch,
        {
            "regions": [
                {"region_id": "r1", "role": "delivery_note", "confidence": 0.9, "reason": "ok"},
                {
                    "region_id": "bad",
                    "role": "delivery_note",
                    "confidence": 0.5,
                    "reason": "not allowed",
                },
                {"region_id": "r1", "role": "not_a_role", "confidence": 0.5, "reason": "bad role"},
                {"region_id": "r2", "role": "finance", "confidence": "x", "reason": "bad conf"},
                "not-a-dict",
            ]
        },
    )
    probes = [
        {
            "region_id": "r1",
            "sheet": "S1",
            "header_row": 3,
            "headers": ["a", "b"],
            "context_rows": [{"row": 1, "text": "x"}, {"row": 2, "text": "y"}],
            "deterministic_role": "delivery_note",
            "explicit_customer": "客户A",
        },
        {"region_id": "r2", "sheet": "S2"},
    ]
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        out = llm_assist.advise_workbook_regions(probes)
    assert out.used_llm is True
    ids = {item["region_id"] for item in out.data["regions"]}
    assert ids == {"r1", "r2"}
    assert out.data["regions"][0]["confidence"] == 0.9


def test_llm_assist_advise_field_mappings(monkeypatch):
    from app.application.etl import llm_assist

    assert (
        llm_assist.advise_field_mappings(headers=[], samples={}, target_fields=[]).used_llm is False
    )
    assert (
        llm_assist.advise_field_mappings(headers=["a"], samples={}, target_fields=[]).used_llm
        is False
    )
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    _patch_complete(
        monkeypatch,
        {
            "mappings": [
                {
                    "source": "a",
                    "target": "f1",
                    "transform": "trim",
                    "confidence": 0.8,
                    "reason": "m",
                },
                {
                    "source": "zz",
                    "target": "f1",
                    "transform": "trim",
                    "confidence": 0.8,
                    "reason": "bad src",
                },
                {
                    "source": "a",
                    "target": "zz",
                    "transform": "trim",
                    "confidence": 0.8,
                    "reason": "bad tgt",
                },
                {
                    "source": "a",
                    "target": "f1",
                    "transform": "evil",
                    "confidence": "x",
                    "reason": "bad t",
                },
                "x",
            ]
        },
    )
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        out = llm_assist.advise_field_mappings(
            headers=["a"], samples={"a": ["v1", "v2"]}, target_fields=[{"key": "f1"}]
        )
    assert out.used_llm is True
    assert out.data["mappings"][0]["transform"] == "trim"


def test_llm_assist_advise_row_decisions(monkeypatch):
    from app.application.etl import llm_assist

    assert llm_assist.advise_row_decisions([]).used_llm is False
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    _patch_complete(
        monkeypatch,
        {
            "items": [
                {"index": 0, "action": "new", "reason": "ok"},
                {"index": 99, "action": "new", "reason": "oob"},
                {"index": "bad", "action": "new", "reason": "bad index"},
                {"index": 0, "action": "kill", "reason": "bad action"},
                "x",
            ]
        },
    )
    payloads = [
        {
            "deterministic_action": "new",
            "deterministic_reason": "r",
            "normalized": {"a": 1},
            "before": {},
            "after": {"a": 1},
        }
        for _ in range(2)
    ]
    with patch(
        "app.application.etl.llm_assist._active_software_llm", return_value=(True, None, None)
    ):
        out = llm_assist.advise_row_decisions(payloads)
    assert out.data["items"] == [{"index": 0, "action": "new", "reason": "ok"}]


# --------------------------------------------------------------------------- llm_session_provider.py


def test_session_provider_is_configured():
    from app.application.etl.llm_session_provider import SessionMarketProvider

    assert SessionMarketProvider(1, "tok", timeout_seconds=3.0).is_configured is True
    assert SessionMarketProvider(1, "", timeout_seconds=3.0).is_configured is False


def test_session_provider_owner_bind(monkeypatch):
    from app.application.etl import llm_session_provider as mod

    assert mod.current_etl_llm_owner() is None
    token = mod.bind_etl_llm_owner(42)
    assert mod.current_etl_llm_owner() == 42
    mod.reset_etl_llm_owner(token)
    assert mod.current_etl_llm_owner() is None


def test_current_owner_market_provider(monkeypatch):
    from app.application.etl import llm_session_provider as mod

    assert mod.current_owner_market_provider(timeout_seconds=1.0) is None
    token = mod.bind_etl_llm_owner(3)
    try:
        with patch(
            "app.fastapi_routes.market_account.latest_session_market_token", return_value=None
        ):
            assert mod.current_owner_market_provider(timeout_seconds=1.0) is None
        with patch(
            "app.fastapi_routes.market_account.latest_session_market_token", return_value="tok"
        ):
            prov = mod.current_owner_market_provider(timeout_seconds=1.0)
            assert prov.owner_user_id == 3 and prov.is_configured is True
    finally:
        mod.reset_etl_llm_owner(token)


def test_session_provider_chat_completion_success(monkeypatch):
    from app.application.etl.llm_session_provider import SessionMarketProvider

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "provider": "p1", "model": "m1"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return FakeResp()

    class FakeAdapter:
        def __init__(self, **k):
            self.closed = False

        async def chat_completion(self, messages, **k):
            return {"ok": True}

        async def close(self):
            self.closed = True

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(
        "app.services.conversation.modstore_adapter.ModstorePlatformAdapter", FakeAdapter
    )
    prov = SessionMarketProvider(1, "tok", timeout_seconds=4.0)
    out = asyncio.run(
        prov.chat_completion([{"role": "user", "content": "hi"}], temperature=0, max_tokens=5)
    )
    assert out == {"ok": True}


def test_session_provider_chat_completion_route_failure(monkeypatch):
    from app.application.etl.llm_session_provider import SessionMarketProvider

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": False, "provider": "", "model": ""}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    prov = SessionMarketProvider(1, "tok", timeout_seconds=4.0)
    with pytest.raises(ValueError):
        asyncio.run(prov.chat_completion([]))


# --------------------------------------------------------------------------- adviser.py


def test_etl_row_adviser_fallback():
    from app.application.etl.adviser import EtlRowAdviser

    fb = EtlRowAdviser.fallback(
        deterministic_action="new",
        deterministic_reason="",
        normalized={},
        before={},
        after={},
    )
    assert (
        fb["action"] == "new" and fb["reason"] == "deterministic_rule" and fb["used_llm"] is False
    )


def test_etl_row_adviser_no_provider():
    from app.application.etl.adviser import EtlRowAdviser

    adv = EtlRowAdviser()
    out = adv.suggest(
        deterministic_action="skip", deterministic_reason="r", normalized={}, before={}, after={}
    )
    assert out["action"] == "skip" and out["used_llm"] is False


def test_etl_row_adviser_provider_branches():
    from app.application.etl.adviser import EtlRowAdviser

    # provider raises
    adv = EtlRowAdviser(provider=lambda row: (_ for _ in ()).throw(RuntimeError("boom")))
    out = adv.suggest(
        deterministic_action="new",
        deterministic_reason="r",
        normalized={"a": 1},
        before={},
        after={},
    )
    assert out["degraded"] is True and out["degradation_code"] == "ETL_LLM_UNAVAILABLE"

    # provider returns non-dict
    adv2 = EtlRowAdviser(provider=lambda row: "nope")
    out2 = adv2.suggest(
        deterministic_action="new", deterministic_reason="r", normalized={}, before={}, after={}
    )
    assert out2["degradation_code"] == "ETL_LLM_INVALID_RESPONSE"

    # invalid action
    adv3 = EtlRowAdviser(provider=lambda row: {"action": "delete", "reason": "x"})
    out3 = adv3.suggest(
        deterministic_action="new", deterministic_reason="r", normalized={}, before={}, after={}
    )
    assert out3["degradation_code"] == "ETL_LLM_INVALID_ACTION"

    # valid
    adv4 = EtlRowAdviser(provider=lambda row: {"action": "update", "reason": "good"})
    out4 = adv4.suggest(
        deterministic_action="new", deterministic_reason="r", normalized={}, before={}, after={}
    )
    assert out4["used_llm"] is True and out4["action"] == "update" and out4["reason"] == "good"


def test_etl_row_adviser_suggest_many():
    from app.application.etl.adviser import EtlRowAdviser

    rows = [
        {
            "deterministic_action": "new",
            "deterministic_reason": "r",
            "normalized": {"a": 1},
            "before": {},
            "after": {},
        }
    ]
    # empty
    assert EtlRowAdviser().suggest_many([]) == []
    # no batch provider -> per-row suggest
    adv = EtlRowAdviser(provider=lambda row: {"action": "skip", "reason": "s"})
    outs = adv.suggest_many(rows)
    assert outs[0]["used_llm"] is True and outs[0]["action"] == "skip"

    # batch provider success
    adv2 = EtlRowAdviser(
        batch_provider=lambda payloads: {
            "items": [{"index": 0, "action": "update", "reason": "ok"}],
            "metadata": {"used_llm": True, "model": "m"},
        }
    )
    outs2 = adv2.suggest_many(rows)
    assert outs2[0]["used_llm"] is True and outs2[0]["model"] == "m"

    # batch provider raises
    adv3 = EtlRowAdviser(batch_provider=lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    outs3 = adv3.suggest_many(rows)
    assert outs3[0]["degraded"] is True

    # non-dict result
    adv4 = EtlRowAdviser(batch_provider=lambda p: "x")
    outs4 = adv4.suggest_many(rows)
    assert outs4[0]["used_llm"] is False

    # degraded metadata
    adv5 = EtlRowAdviser(
        batch_provider=lambda p: {
            "items": [],
            "metadata": {"degraded": True, "degradation_code": "X"},
        }
    )
    outs5 = adv5.suggest_many(rows)
    assert outs5[0]["degraded"] is True and outs5[0]["degradation_code"] == "X"

    # metadata not used_llm
    adv6 = EtlRowAdviser(batch_provider=lambda p: {"items": [], "metadata": {"used_llm": False}})
    outs6 = adv6.suggest_many(rows)
    assert outs6[0]["used_llm"] is False

    # bad item index / bad index type / non-dict item
    adv7 = EtlRowAdviser(
        batch_provider=lambda p: {
            "items": [
                "x",
                {"index": "bad", "action": "new", "reason": "r"},
                {"index": 99, "action": "new", "reason": "r"},
                {"index": 0, "action": "kill", "reason": "r"},
                {"index": 0, "action": "new", "reason": "ok"},
            ],
            "metadata": {"used_llm": True},
        }
    )
    outs7 = adv7.suggest_many(rows)
    assert outs7[0]["used_llm"] is True and outs7[0]["action"] == "new"


def test_etl_row_adviser_default_batch_provider(monkeypatch):
    from app.application.etl import adviser

    result = {"data": {"items": [{"index": 0, "action": "skip", "reason": "r"}]}}
    result_obj = MagicMock()
    result_obj.data = result["data"]
    result_obj.public_metadata.return_value = {"used_llm": True}
    with patch("app.application.etl.llm_assist.advise_row_decisions", return_value=result_obj):
        out = adviser._default_batch_provider([{}])
        assert out["metadata"]["used_llm"] is True
    assert isinstance(adviser.get_etl_row_adviser(), adviser.EtlRowAdviser)


# --------------------------------------------------------------------------- compatibility_presets.py


def test_validate_compatibility_preset(monkeypatch):
    from app.application.etl import compatibility_presets as cp

    with pytest.raises(EtlError) as ex:
        cp.validate_compatibility_preset("p", target_type="bogus", upload_suffix=".xlsx")
    assert ex.value.code == "ETL_COMPATIBILITY_PRESET_TARGET_MISMATCH"

    with pytest.raises(EtlError) as ex:
        cp.validate_compatibility_preset("p", target_type="customers", upload_suffix=".csv")
    assert ex.value.code == "ETL_COMPATIBILITY_PRESET_FILE_UNSUPPORTED"

    with patch("app.application.shipment_etl_profile.list_profiles", side_effect=RuntimeError("x")):
        with pytest.raises(EtlError) as ex:
            cp.validate_compatibility_preset("p", target_type="customers", upload_suffix=".xlsx")
        assert (
            ex.value.code == "ETL_COMPATIBILITY_PRESET_UNAVAILABLE" and ex.value.status_code == 503
        )

    with patch(
        "app.application.shipment_etl_profile.list_profiles",
        return_value=[{"id": "a"}, {"id": "b"}, "junk"],
    ):
        with pytest.raises(EtlError) as ex:
            cp.validate_compatibility_preset(
                "missing", target_type="customers", upload_suffix=".xlsx"
            )
        assert ex.value.code == "ETL_COMPATIBILITY_PRESET_NOT_FOUND" and ex.value.status_code == 404

        # valid path
        cp.validate_compatibility_preset("a", target_type="products", upload_suffix=".xlsm")


# --------------------------------------------------------------------------- targets/helpers.py


def test_helpers_issue_optional_decimal():
    from app.application.etl.targets import helpers

    assert helpers.issue("C", "f", "m") == {
        "code": "C",
        "field": "f",
        "severity": "error",
        "message": "m",
    }
    assert helpers.optional_text("  hi  ") == "hi"
    assert helpers.optional_text("") is None
    assert helpers.optional_text(None) is None
    assert helpers.decimal_or_zero("1,000") == Decimal("1000")
    assert helpers.decimal_or_zero(None) == Decimal("0")
    assert helpers.decimal_or_zero("3.5") == Decimal("3.5")
    with pytest.raises(EtlError) as ex:
        helpers.decimal_or_zero("abc")
    assert ex.value.code == "ETL_NUMBER_INVALID"


def test_helpers_parse_date():
    from app.application.etl.targets import helpers

    assert helpers.parse_date(datetime(2024, 1, 2, 3, 4)) == date(2024, 1, 2)
    assert helpers.parse_date(date(2024, 1, 2)) == date(2024, 1, 2)
    assert helpers.parse_date("2024-01-02") == date(2024, 1, 2)
    with pytest.raises(EtlError) as ex:
        helpers.parse_date("not-a-date")
    assert ex.value.code == "ETL_DATE_INVALID"


def test_helpers_model_values_and_compare():
    from app.application.etl.targets import helpers

    obj = MagicMock()
    obj.price = Decimal("1.50")
    obj.name = "x"
    fields = (
        TargetField("price", "价格"),
        TargetField("name", "名称"),
        TargetField("missing", "缺"),
    )
    vals = helpers.model_values(obj, fields)
    assert vals["price"] == "1.50" and vals["name"] == "x" and "missing" in vals

    assert helpers._values_equal(Decimal("1.5"), "1.5") is True
    assert helpers._values_equal(Decimal("1.5"), "zz") is False
    assert helpers._values_equal(datetime(2024, 1, 1, 1), "2024-01-01T01:00:00") is True
    assert helpers._values_equal(date(2024, 1, 1), "2024-01-01") is True
    assert helpers._values_equal(None, None) is True
    assert helpers._values_equal(None, "x") is False
    assert helpers._values_equal("a", "a") is True
    assert helpers._values_equal("a", "b") is False


def test_helpers_rollback_assertions():
    from app.application.etl.targets import helpers

    fields = (TargetField("price", "价格"), TargetField("name", "名称"))
    obj = MagicMock()
    obj.price = Decimal("1.5")
    obj.name = "x"

    # _changed_image_fields path: before/after differ -> assert matches
    helpers.assert_rollback_image_matches(obj, {"price": "1.5"}, {"price": "1.5"}, fields, "产品")
    with pytest.raises(EtlError) as ex:
        helpers.assert_rollback_image_matches(obj, {"price": "1.5"}, {"price": "9"}, fields, "产品")
    assert ex.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"

    helpers.assert_created_row_unchanged(obj, {"name": "x"}, fields, "产品")
    with pytest.raises(EtlError) as ex2:
        helpers.assert_created_row_unchanged(obj, {"name": "CHANGED"}, fields, "产品")
    assert ex2.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"

    helpers.assert_snapshot_unchanged(obj, {"id": 1, "created_at": "x", "price": "1.5"}, "发货记录")
    with pytest.raises(EtlError) as ex3:
        helpers.assert_snapshot_unchanged(obj, {"price": "9"}, "发货记录")
    assert ex3.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"


def test_helpers_uploaded_document_path(tmp_path):
    from app.application.etl.targets import helpers

    assert helpers.is_uploaded_document_path("x", {}) is False
    p = tmp_path / "f.xlsx"
    p.write_bytes(b"x")
    assert helpers.is_uploaded_document_path(str(p), {"upload_path": str(p)}) is True
    assert (
        helpers.is_uploaded_document_path(str(p), {"upload_path": str(tmp_path / "other.xlsx")})
        is False
    )


def test_helpers_webhook_url(monkeypatch):
    from app.application.etl.targets import helpers

    monkeypatch.delenv("FHD_ETL_ALLOW_HTTP_WEBHOOK", raising=False)
    monkeypatch.delenv("FHD_ETL_ALLOW_PRIVATE_WEBHOOK", raising=False)

    with pytest.raises(EtlError) as ex:
        helpers.assert_safe_webhook_url("ftp://x")
    assert ex.value.code == "ETL_WEBHOOK_URL_INVALID"

    with pytest.raises(EtlError) as ex:
        helpers.assert_safe_webhook_url("http://example.com")
    assert ex.value.code == "ETL_WEBHOOK_HTTPS_REQUIRED"

    monkeypatch.setenv("FHD_ETL_ALLOW_HTTP_WEBHOOK", "1")
    with patch(
        "app.application.etl.targets.helpers.socket.getaddrinfo", side_effect=OSError("dns")
    ):
        with pytest.raises(EtlError) as ex:
            helpers.assert_safe_webhook_url("http://nope.invalid")
        assert ex.value.code == "ETL_WEBHOOK_DNS_FAILED"

    with patch(
        "app.application.etl.targets.helpers.socket.getaddrinfo",
        return_value=[("ai", 0, 0, "", ("127.0.0.1", 80))],
    ):
        with pytest.raises(EtlError) as ex:
            helpers.assert_safe_webhook_url("http://localhost")
        assert ex.value.code == "ETL_WEBHOOK_PRIVATE_ADDRESS_FORBIDDEN"

    monkeypatch.setenv("FHD_ETL_ALLOW_PRIVATE_WEBHOOK", "1")
    with patch(
        "app.application.etl.targets.helpers.socket.getaddrinfo",
        return_value=[("ai", 0, 0, "", ("8.8.8.8", 443))],
    ):
        helpers.assert_safe_webhook_url("https://example.com")


def test_helpers_truthy_env(monkeypatch):
    from app.application.etl.targets import helpers

    monkeypatch.setenv("X1", "true")
    monkeypatch.setenv("X0", "0")
    monkeypatch.delenv("X2", raising=False)
    assert helpers.truthy_env("X1") is True
    assert helpers.truthy_env("X0") is False
    assert helpers.truthy_env("X2") is False


# --------------------------------------------------------------------------- targets/__init__.py


def test_get_adapter_registry():
    from app.application.etl.targets import get_adapter, target_capabilities

    assert get_adapter("customers").type == "customers"
    assert get_adapter("products").type == "products"
    assert get_adapter("shipment_records").type == "shipment_records"
    assert get_adapter("purchase_orders").type == "purchase_orders"
    assert get_adapter("customer_products").type == "customer_products"
    assert get_adapter("attendance").type == "attendance"
    assert get_adapter("export_csv").type == "export_csv"
    assert get_adapter("export_xlsx").type == "export_xlsx"
    assert get_adapter("webhook").type == "webhook"
    assert get_adapter("knowledge").type == "knowledge"

    with pytest.raises(EtlError) as ex:
        get_adapter("bogus")
    assert ex.value.code == "ETL_TARGET_UNSUPPORTED"

    caps = target_capabilities()
    assert isinstance(caps, list) and all(isinstance(c, dict) for c in caps)


# --------------------------------------------------------------------------- targets/customers.py


def _make_customer(db, name="客户A", **kw):
    from app.db.models.purchase_unit import PurchaseUnit

    obj = PurchaseUnit(tenant_id=1, unit_name=name, is_active=True)
    for k, v in kw.items():
        setattr(obj, k, v)
    db.add(obj)
    db.flush()
    return obj


def test_customers_preview_branches(session):
    from app.application.etl.targets.customers import CustomerAdapter

    a = CustomerAdapter()
    # validation fail
    d = a.preview(session, {}, allowed_update_fields={"x"}, context={})
    assert d.action == "error" and d.reason == "validation_failed"

    # not found -> new
    ctx_virtual = {}
    d2 = a.preview(
        session, {"customer_name": "新客户"}, allowed_update_fields=set(), context=ctx_virtual
    )
    assert d2.action == "new"

    # reuse cache -> virtual dict -> skip duplicate_in_source_file
    d3 = a.preview(
        session, {"customer_name": "新客户"}, allowed_update_fields=set(), context=ctx_virtual
    )
    assert d3.action == "skip" and d3.reason == "duplicate_in_source_file"

    # existing obj, no updates -> skip duplicate_customer
    _make_customer(session, "老客户")
    d4 = a.preview(
        session, {"customer_name": "老客户"}, allowed_update_fields={"contact_person"}, context={}
    )
    assert d4.action == "skip" and d4.reason == "duplicate_customer"

    # existing obj with update
    d5 = a.preview(
        session,
        {"customer_name": "老客户", "contact_person": "新人"},
        allowed_update_fields={"contact_person"},
        context={},
    )
    assert d5.action == "update" and d5.reason == "confirmed_update_fields_changed"


def test_customers_execute_row(session):
    from app.application.etl.targets.customers import CustomerAdapter

    a = CustomerAdapter()
    # new
    r = a.execute_row(
        session,
        {"customer_name": "新客户", "contact_person": "王"},
        action="new",
        match_ref="",
        allowed_update_fields=set(),
        context={},
    )
    assert "match_ref" in r

    # new with existing -> ETL_MATCH_CHANGED
    with pytest.raises(EtlError) as ex:
        a.execute_row(
            session,
            {"customer_name": "新客户"},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
    assert ex.value.code == "ETL_MATCH_CHANGED"

    # update existing
    obj = _make_customer(session, "老客户")
    r2 = a.execute_row(
        session,
        {"customer_name": "老客户", "contact_person": "李"},
        action="update",
        match_ref=str(obj.id),
        allowed_update_fields={"contact_person"},
        context={},
    )
    assert r2["after"]["contact_person"] == "李"

    # disappear
    with pytest.raises(EtlError) as ex2:
        a.execute_row(
            session,
            {"customer_name": "无"},
            action="update",
            match_ref="999999",
            allowed_update_fields=set(),
            context={},
        )
    assert ex2.value.code == "ETL_MATCH_DISAPPEARED"


def test_customers_rollback_row(session):
    from app.application.etl.targets.customers import CustomerAdapter

    a = CustomerAdapter()
    # before present, missing obj -> ETL_ROLLBACK_TARGET_MISSING
    with pytest.raises(EtlError) as ex:
        a.rollback_row(
            session,
            match_ref="999999",
            before={"customer_name": "x"},
            after={"customer_name": "y"},
            context={},
        )
    assert ex.value.code == "ETL_ROLLBACK_TARGET_MISSING"

    # before present, mismatch -> concurrent change
    obj = _make_customer(session, "客户X", contact_person="A")
    with pytest.raises(EtlError) as ex2:
        a.rollback_row(
            session,
            match_ref=str(obj.id),
            before={"contact_person": "B"},
            after={"contact_person": "C"},
            context={},
        )
    assert ex2.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"

    # before present, match -> restore
    r = a.rollback_row(
        session,
        match_ref=str(obj.id),
        before={"contact_person": "原始"},
        after={"contact_person": "原始"},
        context={},
    )
    assert obj.contact_person == "原始"

    # before empty, obj deleted
    obj2 = _make_customer(session, "客户Y")
    a.rollback_row(
        session, match_ref=str(obj2.id), before={}, after={"customer_name": "客户Y"}, context={}
    )
    session.flush()
    session.expire_all()
    assert session.query(type(obj2)).filter(type(obj2).id == obj2.id).first() is None

    # before empty, mismatch -> concurrent
    obj3 = _make_customer(session, "客户Z")
    with pytest.raises(EtlError) as ex3:
        a.rollback_row(
            session, match_ref=str(obj3.id), before={}, after={"customer_name": "改过"}, context={}
        )
    assert ex3.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"


# --------------------------------------------------------------------------- targets/orders.py


def _make_product(db, name="漆", model=None):
    from app.db.models.product import Product

    p = Product(tenant_id=1, unit="客户A", name=name)
    if model:
        p.model_number = model
    db.add(p)
    db.flush()
    return p


def _make_supplier(db, name="供应商A"):
    from app.db.models.purchase import Supplier

    s = Supplier(tenant_id=1, code=f"sup-{name}", name=name)
    db.add(s)
    db.flush()
    return s


def test_purchase_order_preview(session):
    from app.application.etl.targets.orders import PurchaseOrderAdapter

    a = PurchaseOrderAdapter()
    supplier = _make_supplier(session, "供应商A")
    product = _make_product(session, "漆", "M1")

    # validation fail
    d = a.preview(session, {}, allowed_update_fields=set(), context={})
    assert d.action == "error"

    good = {
        "external_order_no": "PO-1",
        "supplier_name": "供应商A",
        "order_date": "2024-01-01",
        "product_name": "漆",
        "product_model": "M1",
        "quantity": "2",
    }
    d2 = a.preview(session, good, allowed_update_fields=set(), context={})
    assert d2.action == "new"

    # existing order -> skip
    from app.db.models.purchase import PurchaseOrder

    order = PurchaseOrder(
        tenant_id=1,
        order_no="PO-1",
        supplier_id=supplier.id,
        order_date=date(2024, 1, 1),
        status="draft",
    )
    session.add(order)
    session.flush()
    d3 = a.preview(session, good, allowed_update_fields=set(), context={})
    assert d3.action == "skip" and d3.reason == "existing_order_v1_no_update"

    # missing supplier
    d4 = a.preview(
        session,
        {**good, "external_order_no": "PO-2", "supplier_name": "无人"},
        allowed_update_fields=set(),
        context={},
    )
    assert d4.action == "error" and d4.reason == "reference_missing"

    # missing product (by name)
    d5 = a.preview(
        session,
        {**good, "external_order_no": "PO-3", "product_name": "无此产品", "product_model": ""},
        allowed_update_fields=set(),
        context={},
    )
    assert d5.action == "error" and d5.reason == "reference_missing"


def test_purchase_order_execute_and_rollback(session):
    from app.application.etl.targets.orders import PurchaseOrderAdapter
    from app.db.models.purchase import PurchaseOrderItem

    a = PurchaseOrderAdapter()
    supplier = _make_supplier(session, "供应商A")
    product = _make_product(session, "漆", "M1")

    good = {
        "external_order_no": "PO-1",
        "supplier_name": "供应商A",
        "order_date": "2024-01-01",
        "product_name": "漆",
        "product_model": "M1",
        "quantity": "2",
        "unit_price": "10",
        "unit": "桶",
    }
    r = a.execute_row(
        session, good, action="new", match_ref="", allowed_update_fields=set(), context={}
    )
    assert r["after"]["order_created"] is True and r["after"]["item_id"]

    # execute again -> created=False (existing order)
    r2 = a.execute_row(
        session, good, action="update", match_ref="", allowed_update_fields=set(), context={}
    )
    assert r2["after"]["order_created"] is False

    # missing supplier
    with pytest.raises(EtlError) as ex:
        a.execute_row(
            session,
            {**good, "external_order_no": "PO-2", "supplier_name": "无人"},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
    assert ex.value.code == "ETL_SUPPLIER_NOT_FOUND"

    # missing product
    with pytest.raises(EtlError) as ex2:
        a.execute_row(
            session,
            {**good, "external_order_no": "PO-3", "product_name": "无", "product_model": ""},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
    assert ex2.value.code == "ETL_PRODUCT_NOT_FOUND"

    # rollback deletes item + order
    item_id = int(r["match_ref"])
    a.rollback_row(session, match_ref=str(item_id), before={}, after=r["after"], context={})
    assert session.get(PurchaseOrderItem, item_id) is None


def _make_shipment_record(db, order_no, run_id):
    from app.db.models.shipment import ShipmentRecord

    rec = ShipmentRecord(
        tenant_id=1,
        purchase_unit="客户A",
        product_name="漆",
        quantity_kg=1.0,
        quantity_tins=1,
        parsed_data=json.dumps({"external_order_no": order_no, "etl_run_id": run_id}),
    )
    db.add(rec)
    db.flush()
    return rec


def test_shipment_preview_branches(session):
    from app.application.etl.targets.orders import ShipmentAdapter

    a = ShipmentAdapter()
    base = {
        "purchase_unit": "客户A",
        "product_name": "漆",
        "quantity_kg": "10",
        "external_order_no": "SO-1",
    }
    # validation fail
    d = a.preview(session, {}, allowed_update_fields=set(), context={})
    assert d.action == "error"

    # quantity missing
    d2 = a.preview(
        session,
        {**base, "quantity_kg": "", "quantity_tins": ""},
        allowed_update_fields=set(),
        context={},
    )
    assert d2.action == "error"

    # new
    d3 = a.preview(session, base, allowed_update_fields=set(), context={})
    assert d3.action == "new"

    # existing fingerprint -> skip
    from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

    fp = a._fingerprint(base, {})
    session.add(
        ShipmentEtlImportFingerprint(
            tenant_key="tenant:1",
            fingerprint=fp,
            shipment_id=1,
            unit_name="客户A",
            source_kind="general_etl",
        )
    )
    session.flush()
    d4 = a.preview(session, base, allowed_update_fields=set(), context={})
    assert d4.action == "skip" and d4.reason == "legacy_fingerprint_duplicate"

    # legacy_note_fingerprint duplicate
    session.query(ShipmentEtlImportFingerprint).filter(
        ShipmentEtlImportFingerprint.tenant_key == "tenant:1"
    ).delete(synchronize_session=False)
    session.flush()
    session.add(
        ShipmentEtlImportFingerprint(
            tenant_key="tenant:1", fingerprint="legacy-note-fp", shipment_id=2, source_kind=None
        )
    )
    session.flush()
    d5 = a.preview(
        session,
        {**base, "legacy_note_fingerprint": "legacy-note-fp"},
        allowed_update_fields=set(),
        context={},
    )
    assert d5.action == "skip" and d5.reason == "legacy_note_fingerprint_duplicate"

    # legacy_query match (order_no branch)
    session.query(ShipmentEtlImportFingerprint).filter(
        ShipmentEtlImportFingerprint.tenant_key == "tenant:1"
    ).delete(synchronize_session=False)
    session.flush()
    session.add(
        ShipmentEtlImportFingerprint(
            tenant_key="tenant:1",
            fingerprint="legacy-order",
            shipment_id=3,
            order_number="SO-1",
            source_kind=None,
        )
    )
    session.flush()
    d6 = a.preview(session, base, allowed_update_fields=set(), context={})
    assert d6.action == "skip" and d6.reason == "legacy_source_duplicate"

    # legacy_query match (no order_no branch)
    session.query(ShipmentEtlImportFingerprint).filter(
        ShipmentEtlImportFingerprint.tenant_key == "tenant:1"
    ).delete(synchronize_session=False)
    session.flush()
    session.add(
        ShipmentEtlImportFingerprint(
            tenant_key="tenant:1",
            fingerprint="legacy-file",
            shipment_id=4,
            file_name="a.xlsx",
            unit_name="客户A",
            source_kind=None,
        )
    )
    session.flush()
    d7 = a.preview(
        session,
        {**base, "external_order_no": ""},
        allowed_update_fields=set(),
        context={"file_name": "a.xlsx"},
    )
    assert d7.action == "skip" and d7.reason == "legacy_source_duplicate"

    # external order duplicate (record from another run)
    session.query(ShipmentEtlImportFingerprint).filter(
        ShipmentEtlImportFingerprint.tenant_key == "tenant:1"
    ).delete(synchronize_session=False)
    session.flush()
    _make_shipment_record(session, "SO-X", "other-run")
    session.flush()
    d8 = a.preview(
        session,
        {**base, "external_order_no": "SO-X"},
        allowed_update_fields=set(),
        context={"run_id": "mine"},
    )
    assert d8.action == "skip" and d8.reason == "external_order_duplicate"


def test_shipment_fingerprint_and_belongs():
    from app.application.etl.targets.orders import ShipmentAdapter

    a = ShipmentAdapter()
    assert a._fingerprint({"source_fingerprint": "  SUP  "}, {}) == "SUP"
    f2 = a._fingerprint({"external_order_no": "O1"}, {"file_sha256": "f", "source_row": 1})
    assert isinstance(f2, str) and len(f2) == 64

    rec = MagicMock()
    rec.parsed_data = json.dumps({"etl_run_id": "run1"})
    assert a._belongs_to_current_run(rec, "run1") is True
    assert a._belongs_to_current_run(rec, "run2") is False
    rec.parsed_data = "not-json"
    assert a._belongs_to_current_run(rec, "run1") is False
    rec.parsed_data = None
    assert a._belongs_to_current_run(rec, "") is False


def test_shipment_execute_and_rollback(session):
    from app.application.etl.targets.orders import ShipmentAdapter
    from app.db.models.shipment import ShipmentRecord

    a = ShipmentAdapter()
    data = {
        "purchase_unit": "客户A",
        "product_name": "漆",
        "quantity_kg": "10",
        "quantity_tins": "2",
        "tin_spec": "5",
        "unit_price": "3",
        "amount": "30",
        "external_order_no": "SO-1",
    }
    context = {"run_id": "run1", "file_name": "a.xlsx", "file_sha256": "f", "source_row": 1}
    r = a.execute_row(
        session, data, action="new", match_ref="", allowed_update_fields=set(), context=context
    )
    session.flush()
    assert r["match_ref"] and r["after"]["id"]

    # second execute -> preview not new -> ETL_MATCH_CHANGED
    with pytest.raises(EtlError) as ex:
        a.execute_row(
            session, data, action="new", match_ref="", allowed_update_fields=set(), context=context
        )
    assert ex.value.code == "ETL_MATCH_CHANGED"

    # rollback
    obj = session.get(ShipmentRecord, int(r["match_ref"]))
    a.rollback_row(session, match_ref=str(obj.id), before={}, after=r["after"], context=context)
    session.flush()
    session.expire_all()
    assert session.query(ShipmentRecord).filter(ShipmentRecord.id == obj.id).first() is None

    # rollback with empty match_ref -> no-op
    a.rollback_row(session, match_ref="", before={}, after={}, context=context)


# --------------------------------------------------------------------------- targets/customer_products.py


def _make_cp_customer(db, name="客户A"):
    from app.db.models.purchase_unit import PurchaseUnit

    c = PurchaseUnit(tenant_id=1, unit_name=name, is_active=True)
    db.add(c)
    db.flush()
    return c


def _make_cp_product(db, name="漆", model=None, unit="客户A"):
    from app.db.models.product import Product

    p = Product(tenant_id=1, unit=unit, name=name)
    if model:
        p.model_number = model
    db.add(p)
    db.flush()
    return p


def test_customer_products_preview(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    base = {"customer_name": "客户A", "name": "漆", "model_number": "M1"}
    # validation fail
    d = a.preview(session, {}, allowed_update_fields=set(), context={})
    assert d.action == "error"

    # new (both not found)
    d2 = a.preview(
        session,
        {"customer_name": "新客", "name": "新漆", "model_number": "N1"},
        allowed_update_fields=set(),
        context={},
    )
    assert d2.action == "new" and d2.reason == "customer_and_product_not_found"

    # product exists as new customer -> orphan product requires repair
    _make_cp_product(session, "漆", "M1", unit="新客")
    d3 = a.preview(
        session,
        {"customer_name": "新客", "name": "漆", "model_number": "M1"},
        allowed_update_fields=set(),
        context={},
    )
    assert d3.action == "error" and d3.reason == "orphan_product_requires_repair"

    # customer exists, product new -> linked_product_not_found
    _make_cp_customer(session, "客户A")
    d4 = a.preview(
        session,
        {"customer_name": "客户A", "name": "新漆2", "model_number": "N2"},
        allowed_update_fields=set(),
        context={"c": 1},
    )
    assert d4.action == "new" and d4.reason == "linked_product_not_found"

    # duplicate product in source (same match key twice in one context)
    ctx = {}
    d5a = a.preview(
        session,
        {"customer_name": "客户A", "name": "漆", "model_number": "M1"},
        allowed_update_fields=set(),
        context=ctx,
    )
    d5b = a.preview(
        session,
        {"customer_name": "客户A", "name": "漆", "model_number": "M1"},
        allowed_update_fields=set(),
        context=ctx,
    )
    assert d5b.action == "skip" and d5b.reason == "duplicate_product_in_source_file"

    # update: customer exists, product exists, changed update field
    _make_cp_product(session, "漆B", "M1B", unit="客户A")
    d6 = a.preview(
        session,
        {"customer_name": "客户A", "name": "漆B", "model_number": "M1B", "specification": "V2"},
        allowed_update_fields={"specification"},
        context={},
    )
    assert d6.action == "update"

    # skip duplicate_customer_product_link
    d7 = a.preview(
        session,
        {"customer_name": "客户A", "name": "漆B", "model_number": "M1B"},
        allowed_update_fields=set(),
        context={},
    )
    assert d7.action == "skip" and d7.reason == "duplicate_customer_product_link"


def test_customer_products_execute(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    # new -> creates customer + product
    r = a.execute_row(
        session,
        {"customer_name": "新客", "name": "新漆", "model_number": "N1", "price": "10"},
        action="new",
        match_ref="",
        allowed_update_fields=set(),
        context={},
    )
    assert r["after"]["_etl"]["customer_created"] is True
    assert r["after"]["_etl"]["product_created"] is True

    # new with existing product -> ETL_MATCH_CHANGED
    prod = _make_cp_product(session, "已有漆", "EM1", unit="客户A")
    match_ref = json.dumps({"customer_id": None, "product_id": prod.id})
    with pytest.raises(EtlError) as ex:
        a.execute_row(
            session,
            {"customer_name": "客户A", "name": "已有漆", "model_number": "EM1"},
            action="new",
            match_ref=match_ref,
            allowed_update_fields=set(),
            context={},
        )
    assert ex.value.code == "ETL_MATCH_CHANGED"

    # product disappeared -> ETL_MATCH_DISAPPEARED
    cust = _make_cp_customer(session, "客户D")
    match_ref2 = json.dumps({"customer_id": cust.id, "product_id": 999999})
    with pytest.raises(EtlError) as ex2:
        a.execute_row(
            session,
            {"customer_name": "客户D", "name": "未匹配", "model_number": "XX"},
            action="update",
            match_ref=match_ref2,
            allowed_update_fields=set(),
            context={},
        )
    assert ex2.value.code == "ETL_MATCH_DISAPPEARED"

    # update success
    prod2 = _make_cp_product(session, "更新漆", "UM1", unit="客户D")
    match_ref3 = json.dumps({"customer_id": cust.id, "product_id": prod2.id})
    r2 = a.execute_row(
        session,
        {"customer_name": "客户D", "name": "更新漆", "model_number": "UM1", "specification": "V9"},
        action="update",
        match_ref=match_ref3,
        allowed_update_fields={"specification"},
        context={},
    )
    assert r2["after"]["_etl"]["product_updated"] is True


def test_customer_products_parse_match_ref():
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    assert CustomerProductsAdapter._parse_match_ref(
        json.dumps({"customer_id": 1, "product_id": 2})
    ) == (1, 2)
    assert CustomerProductsAdapter._parse_match_ref("") == (None, None)
    with pytest.raises(EtlError) as ex:
        CustomerProductsAdapter._parse_match_ref("not-json")
    assert ex.value.code == "ETL_MATCH_REF_INVALID"


def test_customer_products_rollback(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    # product_created -> delete product
    r = a.execute_row(
        session,
        {"customer_name": "新客R", "name": "新漆R", "model_number": "NR"},
        action="new",
        match_ref="",
        allowed_update_fields=set(),
        context={},
    )
    a.rollback_row(session, match_ref=r["match_ref"], before={}, after=r["after"], context={})

    # customer_created with remaining products -> concurrent change
    cust = _make_cp_customer(session, "客户RC")
    prod = _make_cp_product(session, "剩漆", "RM", unit="客户RC")
    r2 = a.execute_row(
        session,
        {"customer_name": "客户RC", "name": "另漆", "model_number": "RM2"},
        action="new",
        match_ref="",
        allowed_update_fields=set(),
        context={},
    )
    r2["after"]["_etl"]["customer_created"] = True
    with pytest.raises(EtlError) as ex:
        a.rollback_row(session, match_ref=r2["match_ref"], before={}, after=r2["after"], context={})
    assert ex.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"


def test_customer_products_preview_customer_conflict(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    ctx = {}
    a.preview(
        session,
        {"customer_name": "共客", "name": "漆", "model_number": "M1", "contact_person": "甲"},
        allowed_update_fields=set(),
        context=ctx,
    )
    d = a.preview(
        session,
        {"customer_name": "共客", "name": "漆2", "model_number": "M2", "contact_person": "乙"},
        allowed_update_fields=set(),
        context=ctx,
    )
    assert d.action == "error" and d.reason == "linked_customer_fields_conflict"


def test_customer_products_preview_model_ambiguity(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    _make_cp_customer(session, "客模")
    _make_cp_product(session, "漆", "M1", unit="客模")
    d = a.preview(
        session,
        {"customer_name": "客模", "name": "漆", "model_number": ""},
        allowed_update_fields=set(),
        context={},
    )
    assert d.action == "error" and d.reason == "linked_product_model_ambiguous"


def test_customer_products_execute_customer_update(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    cust = _make_cp_customer(session, "客CU2")
    cust.contact_person = "旧"
    session.flush()
    prod = _make_cp_product(session, "漆CU", "M1", unit="客CU2")
    r = a.execute_row(
        session,
        {"customer_name": "客CU2", "contact_person": "新", "name": "漆CU", "model_number": "M1"},
        action="update",
        match_ref=json.dumps({"customer_id": cust.id, "product_id": prod.id}),
        allowed_update_fields={"contact_person"},
        context={},
    )
    assert r["after"]["_etl"]["customer_updated"] is True
    session.flush()
    session.expire_all()
    assert cust.contact_person == "新"


def test_customer_products_execute_product_update_loop(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    cust = _make_cp_customer(session, "客U")
    prod = _make_cp_product(session, "漆U", "M1", unit="客U")
    r = a.execute_row(
        session,
        {
            "customer_name": "客U",
            "name": "漆U",
            "model_number": "M1",
            "specification": "V2",
            "price": "5",
        },
        action="update",
        match_ref=json.dumps({"customer_id": cust.id, "product_id": prod.id}),
        allowed_update_fields={"specification", "price"},
        context={},
    )
    assert r["after"]["_etl"]["product_updated"] is True
    session.flush()
    session.expire_all()
    assert prod.specification == "V2" and prod.price == Decimal("5")


def test_customer_products_execute_ambiguity(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    _make_cp_customer(session, "客A")
    _make_cp_product(session, "漆", None, unit="客A")
    with pytest.raises(EtlError) as ex:
        a.execute_row(
            session,
            {"customer_name": "客A", "name": "漆", "model_number": "M1"},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
    assert ex.value.code == "ETL_PRODUCT_MODEL_AMBIGUITY"


def test_customer_products_rollback_product_missing(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    with pytest.raises(EtlError) as ex:
        a.rollback_row(
            session,
            match_ref=json.dumps({"customer_id": None, "product_id": 999}),
            before={},
            after={"product": {}, "_etl": {"product_created": True}},
            context={},
        )
    assert ex.value.code == "ETL_ROLLBACK_TARGET_MISSING"


def test_customer_products_rollback_product_updated(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    cust = _make_cp_customer(session, "客R")
    prod = _make_cp_product(session, "漆R", "M1", unit="客R")
    prod.specification = "V9"
    session.flush()
    a.rollback_row(
        session,
        match_ref=json.dumps({"customer_id": cust.id, "product_id": prod.id}),
        before={},
        after={
            "product": {"specification": "V9"},
            "_etl": {"product_updated": True, "product_before": {"specification": "V1"}},
        },
        context={},
    )
    session.flush()
    session.expire_all()
    assert prod.specification == "V1"


def test_customer_products_rollback_customer_updated(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    cust = _make_cp_customer(session, "客CU")
    cust.contact_person = "后"
    session.flush()
    a.rollback_row(
        session,
        match_ref=json.dumps({"customer_id": cust.id, "product_id": None}),
        before={},
        after={
            "customer": {"contact_person": "后"},
            "_etl": {"customer_updated": True, "customer_before": {"contact_person": "前"}},
        },
        context={},
    )
    session.flush()
    session.expire_all()
    assert cust.contact_person == "前"


def test_customer_products_rollback_customer_created_missing(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    with pytest.raises(EtlError) as ex:
        a.rollback_row(
            session,
            match_ref=json.dumps({"customer_id": 999, "product_id": None}),
            before={},
            after={"customer": {}, "_etl": {"customer_created": True}},
            context={},
        )
    assert ex.value.code == "ETL_ROLLBACK_TARGET_MISSING"


def test_customer_products_rollback_customer_created_modified(session):
    from app.application.etl.targets.customer_products import CustomerProductsAdapter

    a = CustomerProductsAdapter()
    cust = _make_cp_customer(session, "客CC")
    cust.contact_person = "改过"
    session.flush()
    with pytest.raises(EtlError) as ex:
        a.rollback_row(
            session,
            match_ref=json.dumps({"customer_id": cust.id, "product_id": None}),
            before={},
            after={"customer": {"contact_person": "原始"}, "_etl": {"customer_created": True}},
            context={},
        )
    assert ex.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"


# --------------------------------------------------------------------------- targets/batch.py


def test_attendance_adapter_preview(session, monkeypatch, tmp_path):
    from app.application.etl.targets.batch import AttendanceAdapter

    monkeypatch.setattr("app.application.etl.targets.batch.get_app_data_dir", lambda: tmp_path)
    a = AttendanceAdapter()
    context = {"upload_path": str(tmp_path / "a.csv"), "file_sha256": "f"}
    d = a.preview(MagicMock(), [], allowed_update_fields=set(), context=context)
    assert d.action == "error" and d.reason == "unsupported_attendance_file"

    ctx2 = {"upload_path": str(tmp_path / "a.xlsx"), "file_sha256": "f"}
    d2 = a.preview(MagicMock(), [], allowed_update_fields=set(), context=ctx2)
    assert d2.action == "new" and d2.reason == "new_attendance_source"

    # existing batch via cache
    ctx3 = {
        "upload_path": str(tmp_path / "a.xlsx"),
        "file_sha256": "f",
        "_preview_cache": {"attendance_batch:f:a.xlsx": {"batch_id": 1}},
    }
    d3 = a.preview(MagicMock(), [], allowed_update_fields=set(), context=ctx3)
    assert d3.action == "skip" and d3.reason == "duplicate_attendance_source"


def test_attendance_existing_batch_db(session, tmp_path):
    from app.application.etl.targets.batch import AttendanceAdapter

    a = AttendanceAdapter()
    db_path = tmp_path / "data" / "mod_dbs" / "taiyangniao-pro.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE attendance_import_batches (id INTEGER, rows_written INTEGER, imported_at TEXT, source_file TEXT)"
    )
    conn.execute("INSERT INTO attendance_import_batches VALUES (5, 3, '2024-01-01', 'f:a.xlsx')")
    conn.commit()
    conn.close()

    with patch.object(AttendanceAdapter, "_db_path", return_value=db_path):
        match = a._existing_batch(
            {"upload_path": str(tmp_path / "a.xlsx"), "file_sha256": "f", "_preview_cache": {}}
        )
        assert match["batch_id"] == 5

        # cached
        cache = {}
        match2 = a._existing_batch(
            {"upload_path": str(tmp_path / "a.xlsx"), "file_sha256": "f", "_preview_cache": cache}
        )
        match3 = a._existing_batch(
            {"upload_path": str(tmp_path / "a.xlsx"), "file_sha256": "f", "_preview_cache": cache}
        )
        assert match2["batch_id"] == 5 and match3["batch_id"] == 5

        # operational error (valid sqlite db but missing the query table)
        db_path2 = tmp_path / "other.db"
        conn2 = sqlite3.connect(str(db_path2))
        conn2.execute("CREATE TABLE unrelated (id INTEGER)")
        conn2.commit()
        conn2.close()
        with patch.object(AttendanceAdapter, "_db_path", return_value=db_path2):
            m = a._existing_batch(
                {"upload_path": str(tmp_path / "a.xlsx"), "file_sha256": "f", "_preview_cache": {}}
            )
            assert m is None


def test_attendance_execute_and_rollback(tmp_path, monkeypatch):
    from app.application.etl.targets.batch import AttendanceAdapter

    monkeypatch.setattr("app.application.etl.targets.batch.get_app_data_dir", lambda: tmp_path)
    a = AttendanceAdapter()

    # unsupported suffix
    with pytest.raises(EtlError) as ex:
        a.execute_batch([], {"upload_path": str(tmp_path / "a.csv")})
    assert ex.value.code == "ETL_ATTENDANCE_FILE_INVALID"

    # existing batch -> ETL_MATCH_CHANGED
    ctx = {
        "upload_path": str(tmp_path / "a.xlsx"),
        "file_sha256": "f",
        "_preview_cache": {"attendance_batch:f:a.xlsx": {"batch_id": 1}},
    }
    with pytest.raises(EtlError) as ex2:
        a.execute_batch([], ctx)
    assert ex2.value.code == "ETL_MATCH_CHANGED"

    # success
    ctx2 = {
        "upload_path": str(tmp_path / "a.xlsx"),
        "file_sha256": "f",
        "row_count": 3,
        "progress_callback": lambda *a: None,
    }
    with patch(
        "app.application.attendance_import_app_service.import_attendance_workbook",
        return_value={"ok": True},
    ):
        r = a.execute_batch([], ctx2)
    assert r["executed"] == 3

    # rollback data missing
    with patch.object(AttendanceAdapter, "_db_path", return_value=tmp_path / "missing.db"):
        with pytest.raises(EtlError) as ex3:
            a.rollback_batch({}, {"source_file": ""})
        assert ex3.value.code == "ETL_ATTENDANCE_ROLLBACK_DATA_MISSING"

    # rollback success
    db_path = tmp_path / "roll.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE attendance_daily_records (source_file TEXT)")
    conn.execute("CREATE TABLE attendance_employees (source_file TEXT)")
    conn.execute("CREATE TABLE attendance_departments (source_file TEXT)")
    conn.execute("CREATE TABLE products (source_file TEXT)")
    conn.execute("CREATE TABLE customers (source_file TEXT)")
    conn.execute("CREATE TABLE attendance_import_batches (id INTEGER)")
    conn.execute("INSERT INTO attendance_import_batches VALUES (1)")
    conn.commit()
    conn.close()
    deleted = a.rollback_batch({}, {"source_file": "f", "db_path": str(db_path), "batch_id": 1})
    assert deleted >= 0


def test_export_csv_adapter(tmp_path, monkeypatch):
    from app.application.etl.targets.batch import ExportCsvAdapter

    monkeypatch.setattr("app.application.etl.targets.batch.get_app_data_dir", lambda: tmp_path)
    calls = []
    rows = [{"a": "=cmd", "b": "x"}, {"a": "y", "b": "z"}]
    r = ExportCsvAdapter().execute_batch(
        rows,
        {"run_id": "r1", "row_count": 2, "progress_callback": lambda c, t: calls.append((c, t))},
    )
    assert r["executed"] == 2 and calls and calls[-1] == (2, 2)
    out = (tmp_path / "etl" / "exports" / "etl-r1.csv").read_text(encoding="utf-8-sig")
    assert "'=cmd" in out


def test_export_csv_empty_rows(tmp_path, monkeypatch):
    from app.application.etl.targets.batch import ExportCsvAdapter

    monkeypatch.setattr("app.application.etl.targets.batch.get_app_data_dir", lambda: tmp_path)
    r = ExportCsvAdapter().execute_batch(
        [], {"run_id": "r2", "row_count": 0, "output_headers": ["h1"]}
    )
    assert r["executed"] == 0


def test_export_xlsx_adapter(tmp_path, monkeypatch):
    from app.application.etl.targets.batch import ExportXlsxAdapter

    monkeypatch.setattr("app.application.etl.targets.batch.get_app_data_dir", lambda: tmp_path)
    rows = [{"a": "=evil", "b": "1"} for _ in range(501)]
    calls = []
    r = ExportXlsxAdapter().execute_batch(
        rows,
        {"run_id": "r3", "row_count": 501, "progress_callback": lambda c, t: calls.append(c)},
    )
    assert r["executed"] == 501
    assert (tmp_path / "etl" / "exports" / "etl-r3.xlsx").is_file()


def test_webhook_adapter_success(monkeypatch):
    from app.application.etl.targets.batch import WebhookAdapter

    statuses = iter([200, 200])
    calls = []

    class FakeResp:
        def __init__(self, code):
            self.status_code = code

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            calls.append(k.get("headers", {}))
            return FakeResp(next(statuses))

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr("app.application.etl.targets.batch.read_webhook_secret", lambda ref: "sec")
    with patch("app.application.etl.targets._assert_safe_webhook_url", lambda url: None):
        r = WebhookAdapter().execute_batch(
            [{"a": 1} for _ in range(501)],
            {
                "run_id": "w1",
                "target_config": {"endpoint_url": "https://x.com"},
                "row_count": 501,
                "progress_callback": lambda c, t: None,
            },
        )
    assert r["executed"] == 501
    assert calls and "Authorization" in calls[0]


def test_webhook_adapter_failure(monkeypatch):
    from app.application.etl.targets.batch import WebhookAdapter

    class FakeResp:
        status_code = 500

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr("app.application.etl.targets.batch.read_webhook_secret", lambda ref: "")
    with patch("app.application.etl.targets._assert_safe_webhook_url", lambda url: None):
        with pytest.raises(EtlError) as ex:
            WebhookAdapter().execute_batch(
                [{"a": 1}],
                {
                    "run_id": "w2",
                    "target_config": {"endpoint_url": "https://x.com"},
                    "row_count": 1,
                },
            )
    assert ex.value.code == "ETL_WEBHOOK_DELIVERY_FAILED"


def test_webhook_adapter_http_error_retry(monkeypatch):
    import httpx

    from app.application.etl.targets.batch import WebhookAdapter

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise httpx.ConnectError("conn refused")

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr("app.application.etl.targets.batch.read_webhook_secret", lambda ref: "")
    with patch("app.application.etl.targets._assert_safe_webhook_url", lambda url: None):
        with pytest.raises(EtlError) as ex:
            WebhookAdapter().execute_batch(
                [{"a": 1}],
                {
                    "run_id": "w3",
                    "target_config": {"endpoint_url": "https://x.com"},
                    "row_count": 1,
                },
            )
    assert ex.value.code == "ETL_WEBHOOK_DELIVERY_FAILED"


def test_webhook_adapter_connectivity_test(monkeypatch):
    from app.application.etl.targets.batch import WebhookAdapter

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr("app.application.etl.targets.batch.read_webhook_secret", lambda ref: "")
    with patch("app.application.etl.targets._assert_safe_webhook_url", lambda url: None):
        r = WebhookAdapter().execute_batch(
            [],
            {
                "run_id": "w4",
                "target_config": {"endpoint_url": "https://x.com"},
                "row_count": 0,
                "connectivity_test": True,
            },
        )
        assert r["executed"] == 0
