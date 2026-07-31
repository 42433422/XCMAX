"""Focused coverage for recovered ETL / distillation / private-mod modules.

Targets CI ratchet gap (line ≥87.5%, branch ≥80.5% with 0.5 jitter).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.distillation.continuous_learning_collectors import (
    _read_training_rows,
    build_continuous_learning_corpus,
    collect_bug_fix_learning,
    collect_distillation_log_samples,
    collect_user_feedback_samples,
    export_continuous_training_data,
)
from app.application.distillation.continuous_learning_models import (
    ContinuousLearningCorpus,
    LearningSample,
)
from app.application.etl import secrets as etl_secrets
from app.application.etl.errors import EtlError
from app.application.etl.llm_assist import LlmAssistResult
from app.application.etl.llm_session_provider import (
    SessionMarketProvider,
    bind_etl_llm_owner,
    current_owner_market_provider,
    reset_etl_llm_owner,
)
from app.application.etl.llm_tabular_advice import (
    advise_field_mappings,
    advise_row_decisions,
    advise_workbook_regions,
)
from app.application.etl.mapping_assist import enhance_mappings_with_llm
from app.application.etl.parser_types import ParsedDataset, ParsedRow
from app.application.etl.targets.base import TargetAdapter, TargetField
from app.application.private_mod import delivery, delivery_applier
from app.fastapi_routes import knowledge_v1_omniscient as omni
from app.fastapi_routes.knowledge_v1 import QueryRequest
from app.infrastructure.llm import modstore_chat_failover as failover


def _preview_layout_module():
    """Import order matters: fallback must initialize before candidates."""
    import app.application.etl.shipment_preview_fallback as _spf  # noqa: F401
    from app.application.etl import preview_layout_candidates as plc

    return plc


# ---------------------------------------------------------------------------
# etl/secrets.py
# ---------------------------------------------------------------------------


def test_store_webhook_secret_rejects_empty():
    with pytest.raises(EtlError) as exc:
        etl_secrets.store_webhook_secret(1, "")
    assert exc.value.code == "ETL_SECRET_EMPTY"


def test_store_webhook_secret_keyring_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("no keyring")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(EtlError) as exc:
        etl_secrets.store_webhook_secret(1, "sekrit")
    assert exc.value.code == "ETL_CREDENTIAL_STORE_UNAVAILABLE"


def test_store_read_delete_webhook_secret_roundtrip(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def set_password(service, ref, secret):
            store[(service, ref)] = secret

        @staticmethod
        def get_password(service, ref):
            return store.get((service, ref))

        @staticmethod
        def delete_password(service, ref):
            store.pop((service, ref), None)

    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
    ref = etl_secrets.store_webhook_secret(9, "webhook-secret")
    assert ref.startswith("etl:9:")
    assert etl_secrets.read_webhook_secret(ref) == "webhook-secret"
    etl_secrets.delete_webhook_secret(ref)
    with pytest.raises(EtlError) as exc:
        etl_secrets.read_webhook_secret(ref)
    assert exc.value.code == "ETL_CREDENTIAL_UNAVAILABLE"


def test_store_webhook_secret_write_failure(monkeypatch):
    class Boom:
        @staticmethod
        def set_password(*_a, **_k):
            raise RuntimeError("disk full")

    monkeypatch.setitem(__import__("sys").modules, "keyring", Boom)
    with pytest.raises(EtlError) as exc:
        etl_secrets.store_webhook_secret(1, "x")
    assert exc.value.code == "ETL_CREDENTIAL_STORE_WRITE_FAILED"


def test_read_webhook_secret_env_and_empty_paths(monkeypatch):
    assert etl_secrets.read_webhook_secret(None) == ""
    assert etl_secrets.read_webhook_secret("  ") == ""
    monkeypatch.setenv("FHD_ETL_WEBHOOK_SECRET_ROTATE", "from-env")
    assert etl_secrets.read_webhook_secret("env:FHD_ETL_WEBHOOK_SECRET_ROTATE") == "from-env"
    monkeypatch.delenv("FHD_ETL_WEBHOOK_SECRET_ROTATE", raising=False)
    with pytest.raises(EtlError):
        etl_secrets.read_webhook_secret("env:FHD_ETL_WEBHOOK_SECRET_ROTATE")


def test_read_webhook_secret_keyring_exception(monkeypatch):
    class Boom:
        @staticmethod
        def get_password(*_a, **_k):
            raise RuntimeError("locked")

    monkeypatch.setitem(__import__("sys").modules, "keyring", Boom)
    with pytest.raises(EtlError) as exc:
        etl_secrets.read_webhook_secret("etl:1:abc")
    assert exc.value.code == "ETL_CREDENTIAL_UNAVAILABLE"


def test_delete_webhook_secret_noop_and_swallow(monkeypatch):
    etl_secrets.delete_webhook_secret(None)
    etl_secrets.delete_webhook_secret("env:FHD_ETL_WEBHOOK_SECRET_X")

    class Boom:
        @staticmethod
        def delete_password(*_a, **_k):
            raise RuntimeError("gone")

    monkeypatch.setitem(__import__("sys").modules, "keyring", Boom)
    etl_secrets.delete_webhook_secret("etl:1:abc")  # must not raise


# ---------------------------------------------------------------------------
# etl/llm_tabular_advice.py
# ---------------------------------------------------------------------------


def test_tabular_advice_empty_inputs_short_circuit():
    assert advise_workbook_regions([]).data == {}
    assert advise_field_mappings(headers=[], samples={}, target_fields=[{"key": "a"}]).data == {}
    assert advise_row_decisions([]).data == {}


def test_advise_workbook_regions_filters_invalid_items(monkeypatch):
    def complete(_messages, **_kwargs):
        return LlmAssistResult(
            used_llm=True,
            data={
                "regions": [
                    "not-a-dict",
                    {
                        "region_id": "r1",
                        "role": "delivery_note",
                        "confidence": "bad",
                        "customer_name": "甲",
                        "reason": "买家列明确",
                    },
                    {"region_id": "invented", "role": "delivery_note", "confidence": 0.9},
                    {"region_id": "r1", "role": "not_a_role", "confidence": 0.9},
                    {
                        "region_id": "r1",
                        "role": "finance",
                        "confidence": 1.5,
                        "reason": "对账表",
                    },
                ]
            },
        )

    monkeypatch.setattr("app.application.etl.llm_assist._complete", complete)
    result = advise_workbook_regions(
        [
            {
                "region_id": "r1",
                "sheet": "Sheet1",
                "header_row": 2,
                "headers": ["客户", "数量"],
                "context_rows": [{"row": 1, "text": "买方：甲"}],
                "deterministic_role": "delivery_note",
            }
        ]
    )
    regions = result.data["regions"]
    assert len(regions) == 2
    assert regions[0]["confidence"] == 0.0
    assert regions[1]["role"] == "finance"
    assert regions[1]["confidence"] == 1.0


def test_advise_field_mappings_transform_and_confidence_edges(monkeypatch):
    def complete(_messages, **_kwargs):
        return LlmAssistResult(
            used_llm=True,
            data={
                "mappings": [
                    "bad",
                    {
                        "source": "货品",
                        "target": "name",
                        "transform": "drop_table",
                        "confidence": "x",
                        "reason": "列名匹配",
                    },
                    {
                        "source": "货品",
                        "target": "missing",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                ]
            },
        )

    monkeypatch.setattr("app.application.etl.llm_assist._complete", complete)
    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[{"key": "name", "label": "名称", "type": "string", "required": True}],
    )
    assert len(result.data["mappings"]) == 1
    assert result.data["mappings"][0]["transform"] == ""
    assert result.data["mappings"][0]["confidence"] == 0.0


def test_advise_row_decisions_skips_bad_indexes(monkeypatch):
    def complete(_messages, **_kwargs):
        return LlmAssistResult(
            used_llm=True,
            data={
                "items": [
                    "bad",
                    {"index": "x", "action": "skip", "reason": "dup"},
                    {"index": 99, "action": "skip", "reason": "oob"},
                    {"index": 0, "action": "explode", "reason": "bad action"},
                    {"index": 0, "action": "skip", "reason": "重复"},
                ]
            },
        )

    monkeypatch.setattr("app.application.etl.llm_assist._complete", complete)
    result = advise_row_decisions(
        [{"deterministic_action": "skip", "deterministic_reason": "dup", "normalized": {}}]
    )
    assert result.data["items"] == [
        {"index": 0, "action": "skip", "reason": "重复"},
    ]


# ---------------------------------------------------------------------------
# etl/mapping_assist.py
# ---------------------------------------------------------------------------


class _StubAdapter(TargetAdapter):
    type = "products"
    label = "产品"
    allow_dynamic_fields = False
    fields = (
        TargetField(key="name", label="名称", aliases=("货品",)),
        TargetField(key="price", label="单价"),
    )


def test_enhance_mappings_dynamic_or_empty_short_circuit():
    adapter = _StubAdapter()
    adapter.allow_dynamic_fields = True
    dataset = ParsedDataset(headers=["货品"], rows=[], source_features={})
    out, meta = enhance_mappings_with_llm(dataset, adapter, [{"target": "name"}])
    assert meta["reason"] == "dynamic_or_empty_dataset"
    assert out == [{"target": "name"}]


def test_enhance_mappings_applies_weak_targets(monkeypatch):
    dataset = ParsedDataset(
        headers=["货品", "单价"],
        rows=[
            ParsedRow(sheet="s", row_number=2, values={"货品": "底漆", "单价": "12"}),
            ParsedRow(sheet="s", row_number=3, values={"货品": "", "单价": None}),
        ],
        source_features={},
    )
    deterministic = [
        {"target": "name", "source": "", "confidence": 0.4},
        {"target": "price", "source": "单价", "confidence": 0.95},
    ]

    def fake_advise(*, headers, samples, target_fields):
        assert "货品" in headers
        assert samples["货品"] == ["底漆"]
        return LlmAssistResult(
            used_llm=True,
            model="m",
            data={
                "mappings": [
                    {
                        "source": "货品",
                        "target": "name",
                        "transform": "trim",
                        "confidence": 0.9,
                        "reason": "列名",
                    },
                    {
                        "source": "货品",
                        "target": "price",
                        "confidence": 0.99,
                        "reason": "should skip strong",
                    },
                    {
                        "source": "单价",
                        "target": "name",
                        "confidence": 0.5,
                        "reason": "too weak",
                    },
                ]
            },
        )

    monkeypatch.setattr(
        "app.application.etl.mapping_assist.advise_field_mappings",
        fake_advise,
    )
    enhanced, meta = enhance_mappings_with_llm(dataset, _StubAdapter(), deterministic)
    assert meta["applied_count"] == 1
    assert enhanced[0]["source"] == "货品"
    assert enhanced[0]["suggested_by"] == "llm"
    assert enhanced[1]["source"] == "单价"


# ---------------------------------------------------------------------------
# etl/llm_session_provider.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_market_provider_chat_completion(monkeypatch):
    provider = SessionMarketProvider(3, "tok", timeout_seconds=5.0)
    assert provider.is_configured is True
    cloned = provider.with_timeout(8.0)
    assert cloned._timeout_seconds == 8.0

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "provider": "openai", "model": "gpt-4o-mini"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            assert url.endswith("/api/llm/resolve-chat-default")
            return FakeResp()

    adapter = MagicMock()
    adapter.chat_completion = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
    adapter.close = AsyncMock()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(
        "app.services.conversation.modstore_adapter.ModstorePlatformAdapter",
        lambda **kwargs: adapter,
    )
    out = await provider.chat_completion([{"role": "user", "content": "hi"}], max_tokens=10)
    assert out["choices"][0]["message"]["content"] == "ok"
    adapter.close.assert_awaited()


@pytest.mark.asyncio
async def test_session_market_provider_rejects_bad_route(monkeypatch):
    provider = SessionMarketProvider(1, "tok", timeout_seconds=3.0)

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": False}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, _url):
            return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    with pytest.raises(ValueError, match="unavailable"):
        await provider.chat_completion([{"role": "user", "content": "x"}])


def test_current_owner_market_provider_requires_owner_and_token(monkeypatch):
    assert current_owner_market_provider(timeout_seconds=1.0) is None
    token = bind_etl_llm_owner(11)
    try:
        monkeypatch.setattr(
            "app.fastapi_routes.market_account.latest_session_market_token",
            lambda **_k: "",
        )
        assert current_owner_market_provider(timeout_seconds=1.0) is None
        monkeypatch.setattr(
            "app.fastapi_routes.market_account.latest_session_market_token",
            lambda **_k: "market-tok",
        )
        provider = current_owner_market_provider(timeout_seconds=2.5)
        assert isinstance(provider, SessionMarketProvider)
        assert provider.owner_user_id == 11
    finally:
        reset_etl_llm_owner(token)


# ---------------------------------------------------------------------------
# infrastructure/llm/modstore_chat_failover.py
# ---------------------------------------------------------------------------


def test_chat_failover_max_attempts_and_markers(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER_MAX", "not-int")
    assert failover.chat_failover_max_attempts() == 3
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER_MAX", "99")
    assert failover.chat_failover_max_attempts() == 8
    assert failover.is_market_chat_failoverable(None, "rate limit exceeded")
    assert failover.is_market_chat_failoverable(None, "payment required")
    assert not failover.is_market_chat_failoverable(500, "internal")


def test_provider_row_usable_and_catalog_model_paths():
    assert failover._provider_row_usable("x", fernet_ok=True) is False
    assert failover._provider_row_usable({"configured": True}, fernet_ok=False) is True
    assert failover._provider_row_usable({"available": True}, fernet_ok=False) is True
    assert failover._provider_row_usable({"has_user_override": True}, fernet_ok=False) is False
    assert failover._provider_row_usable({"has_user_override": True}, fernet_ok=True) is True
    assert failover.first_model_from_catalog_block(None) == ""
    assert failover.first_model_from_catalog_block({"models": []}) == ""
    assert (
        failover.first_model_from_catalog_block({"models_detailed": [{"id": "m1"}, {"id": ""}]})
        == "m1"
    )


def test_build_failover_candidates_catalog_fallback_and_dedupe():
    out = failover.build_chat_failover_candidates(
        primary_provider="",
        primary_model="",
        status_payload={
            "fernet_configured": False,
            "providers": [
                "bad",
                {"provider": "", "has_platform_key": True},
                {"provider": "skip", "has_user_override": True},
                {"provider": "openai", "has_env_key": True},
            ],
        },
        catalog_payload={
            "providers": [
                "bad",
                {"provider": ""},
                {"provider": "openai", "models": ["gpt-mini"]},
                {"provider": "deepseek", "runtime_models": ["ds-chat"]},
            ]
        },
        resolved_default={"ok": False, "provider": "x", "model": "y"},
        max_attempts=4,
    )
    assert ("openai", "gpt-mini") in out
    assert ("deepseek", "ds-chat") in out
    assert failover.iter_unique_routes(
        [("OpenAI", "a"), ("openai", "a"), ("", "x"), ("p", ""), ("deepseek", "b")]
    ) == [("openai", "a"), ("deepseek", "b")]


# ---------------------------------------------------------------------------
# distillation/continuous_learning_collectors.py
# ---------------------------------------------------------------------------


def test_feedback_collector_edge_branches(tmp_path):
    assert collect_user_feedback_samples(tmp_path / "missing.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert collect_user_feedback_samples(bad) == []
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "u1": "not-dict",
                "u2": {"feedback_history": "nope"},
                "u3": {
                    "feedback_history": [
                        "skip",
                        {"message": "", "user_feedback": "confirmed"},
                        {
                            "message": "随便问问",
                            "user_feedback": "maybe",
                            "recognized_intent": "help",
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    samples = collect_user_feedback_samples(path)
    assert len(samples) == 1
    assert samples[0].status == "candidate"


def test_default_ticket_roots_import_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "app.services.user_cs_change_request":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from app.application.distillation import continuous_learning_collectors as clc

    assert clc._default_ticket_roots() == []


def test_collect_bug_fix_empty_and_blank_rows(tmp_path):
    assert collect_bug_fix_learning(None) == ([], [])
    path = tmp_path / "bugs.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"title": "", "problem": "", "resolution": ""}),
                json.dumps(
                    {
                        "title": "修复登录",
                        "problem": "无法登录",
                        "resolution": "重置会话",
                        "label": "settings",
                        "issue": "42",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    samples, units = collect_bug_fix_learning(path)
    assert len(samples) == 1
    assert samples[0].source_id == "42"
    assert len(units) == 1


def test_collect_distillation_log_samples_success_and_failure():
    class Row:
        def __init__(self, data):
            self._mapping = data

    class Conn:
        def execute(self, *_a, **_k):
            return SimpleNamespace(
                all=lambda: [
                    Row(
                        {
                            "id": 1,
                            "query": "查客户",
                            "intent": "customers",
                            "slots": {"k": 1},
                            "confidence": 0.9,
                            "source": "chat",
                            "created_at": "2026-07-01",
                        }
                    ),
                    Row(
                        {
                            "id": 2,
                            "query": "未知",
                            "intent": "unk",
                            "slots": None,
                            "confidence": 0.4,
                            "source": "chat",
                            "created_at": "2026-07-02",
                        }
                    ),
                ]
            )

    class Engine:
        def begin(self):
            return self

        def __enter__(self):
            return Conn()

        def __exit__(self, *a):
            return False

    samples = collect_distillation_log_samples(Engine(), limit=10)
    assert len(samples) == 2
    assert samples[0].status == "approved"
    assert samples[1].status == "candidate"

    class BoomEngine:
        def begin(self):
            raise OSError("db down")

    assert collect_distillation_log_samples(BoomEngine()) == []


def test_build_corpus_and_training_row_edges(tmp_path):
    feedback = tmp_path / "mem.json"
    feedback.write_text(
        json.dumps(
            {
                "u": {
                    "feedback_history": [
                        {
                            "message": "打开设置",
                            "recognized_intent": "settings",
                            "user_feedback": "confirmed",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    (tickets / "1.json").write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "ticket_no": "CR-1",
                        "title": "模板预览坏了",
                        "description": "预览空白",
                        "admin_note": "修好了",
                        "status": "open",
                        "change_type": "bug_fix",
                    },
                    {"ticket_no": "CR-2", "title": "", "description": "", "admin_note": ""},
                ]
            }
        ),
        encoding="utf-8",
    )
    bugs = tmp_path / "bugs.json"
    bugs.write_text(
        json.dumps(
            [
                {
                    "title": "打印失败",
                    "problem": "驱动异常",
                    "resolution": "重装驱动",
                    "label": "print_label",
                }
            ]
        ),
        encoding="utf-8",
    )

    with patch(
        "app.application.distillation.continuous_learning_collectors.collect_distillation_log_samples",
        return_value=[
            LearningSample(
                text="发货单",
                label="shipment_generate",
                source_type="distillation_log",
                source_id="9",
                confidence=0.9,
                status="approved",
            )
        ],
    ):
        corpus = build_continuous_learning_corpus(
            feedback_path=feedback,
            ticket_roots=[tickets],
            bugfix_path=bugs,
            include_distillation_log=True,
            include_defaults=False,
        )
    assert corpus.stats()["samples_total"] >= 3

    assert _read_training_rows(None) == []
    assert _read_training_rows(tmp_path / "nope.jsonl") == []
    jsonl = tmp_path / "base.jsonl"
    jsonl.write_text(
        "\n".join(
            [
                "",
                json.dumps(["list"]),
                json.dumps({"text": "a", "label": "not_a_label"}),
                json.dumps({"text": "查客户", "label": "customers", "slots": {"x": 1}}),
            ]
        ),
        encoding="utf-8",
    )
    rows = _read_training_rows(jsonl)
    assert rows == [
        {
            "text": "查客户",
            "label": "customers",
            "slots": {"x": 1},
            "source": "base_training_data",
        }
    ]
    tsv = tmp_path / "base.tsv"
    tsv.write_text("text\tlabel\n\nskipped\n查产品\tproducts\nbad\tnot_label\n", encoding="utf-8")
    assert [r["label"] for r in _read_training_rows(tsv)] == ["products"]

    out = tmp_path / "out.jsonl"
    stats = export_continuous_training_data(jsonl, out, corpus, include_candidates=False)
    assert stats["total_rows"] >= 1
    # duplicate base row should be skipped on second merge
    corpus2 = ContinuousLearningCorpus(min_confidence=0.1)
    corpus2.add_sample(
        LearningSample(
            text="查客户",
            label="customers",
            source_type="customer_feedback",
            source_id="dup",
            confidence=0.99,
            status="approved",
        )
    )
    stats2 = export_continuous_training_data(jsonl, out, corpus2)
    assert stats2["learning_rows"] == 0


# ---------------------------------------------------------------------------
# etl/preview_layout_candidates.py
# ---------------------------------------------------------------------------


def test_selected_region_and_public_helpers():
    plc = _preview_layout_module()
    assert plc._selected_region({"regions": ["x", {"id": "r1", "status": "open"}]}, "r1") is None
    assert plc._selected_region({}, "r1") is None
    region = plc._selected_region(
        {"regions": [{"id": "r1", "status": "selected", "customer_name": "甲"}]},
        "r1",
    )
    assert region["customer_name"] == "甲"
    public = plc._public_layout_candidate(
        {
            "run_id": "run-1",
            "template_id": "etl-preview:run-1",
            "name": "甲-发货单版式",
            "customer_name": "甲",
            "source_region_id": "r1",
            "sheet": "S",
            "header_row": 2,
            "file_name": "a.xlsx",
        }
    )
    assert public["provenance"]["kind"] == "etl_preview_layout_candidate"
    assert "path" not in public


def test_layout_candidate_for_run_edge_paths():
    plc = _preview_layout_module()
    db = MagicMock()
    run = SimpleNamespace(
        id="run-1",
        upload_id="up-1",
        file_sha256="abc",
        source_features_json="[]",
    )
    with patch.object(plc, "load_json", return_value=[]):
        assert (
            plc._layout_candidate_for_run(db, run=run, tenant_id=1, owner_user_id=2, unit_name="甲")
            is None
        )

    run.source_features_json = "{}"
    with (
        patch.object(plc, "load_json", return_value={"regions": []}),
        patch(
            "app.application.etl.service_shipment_templates.shipment_template_candidates",
            return_value=[],
        ),
    ):
        assert (
            plc._layout_candidate_for_run(db, run=run, tenant_id=1, owner_user_id=2, unit_name="甲")
            is None
        )

    features = {
        "regions": [{"id": "r1", "status": "selected", "customer_name": "甲公司", "sheet": "S"}],
        "shipment_template_candidates": [
            {
                "status": "detected",
                "customer_name": "甲公司",
                "source_region_id": "r1",
                "name": "甲-版式",
            }
        ],
    }
    db.query.return_value.filter.return_value.first.return_value = None
    with patch.object(plc, "load_json", return_value=features):
        assert (
            plc._layout_candidate_for_run(db, run=run, tenant_id=1, owner_user_id=2, unit_name="甲")
            is None
        )

    upload = SimpleNamespace(storage_path="/x", suffix=".xlsx", expires_at=None, file_name="a.xlsx")
    db.query.return_value.filter.return_value.first.return_value = upload
    with patch.object(plc, "load_json", return_value=features):
        record = plc._layout_candidate_for_run(
            db, run=run, tenant_id=1, owner_user_id=2, unit_name="甲"
        )
    assert record is not None
    assert record["template_id"] == "etl-preview:run-1"


def test_find_preview_layout_record_guard_and_run_id(monkeypatch):
    plc = _preview_layout_module()
    assert plc._find_preview_layout_record(owner_user_id=None, unit_name="甲") is None
    assert plc.find_latest_preview_layout_candidate(owner_user_id=1, unit_name="") is None

    with patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)):
        with patch.object(plc, "get_db", side_effect=OSError("db")):
            assert plc._find_preview_layout_record(owner_user_id=9, unit_name="甲") is None


def test_safe_owned_upload_path_and_cleanup(tmp_path, monkeypatch):
    plc = _preview_layout_module()
    # Private helpers rely on mixin sync globals from shipment_preview_fallback.
    plc._LAYOUT_SUFFIXES = frozenset({".xlsx", ".xlsm"})
    plc._TEMP_PREFIX = "fhd-etl-preview-layout-"
    runtime = tmp_path / "runtime"
    owned = runtime / "etl" / "uploads" / "7" / "9" / "file.xlsx"
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b"xlsx")
    monkeypatch.setattr(plc, "get_app_data_dir", lambda: str(runtime))

    assert plc._safe_owned_upload_path(str(owned), ".xlsx", None, tenant_id=7, owner_user_id=9)
    assert (
        plc._safe_owned_upload_path(str(owned), ".csv", None, tenant_id=7, owner_user_id=9) is None
    )
    outsider = tmp_path / "other.xlsx"
    outsider.write_bytes(b"x")
    assert (
        plc._safe_owned_upload_path(str(outsider), ".xlsx", None, tenant_id=7, owner_user_id=9)
        is None
    )
    expired = datetime.now(UTC) - timedelta(hours=1)
    assert (
        plc._safe_owned_upload_path(str(owned), ".xlsx", expired, tenant_id=7, owner_user_id=9)
        is None
    )
    naive_future = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    assert plc._safe_owned_upload_path(
        str(owned), ".xlsx", naive_future, tenant_id=7, owner_user_id=9
    )

    plc.cleanup_ephemeral_preview_layout(None)
    plc.cleanup_ephemeral_preview_layout("/definitely/not/valid/\x00")
    # non-temp path ignored
    plc.cleanup_ephemeral_preview_layout(str(owned))


def test_materialize_preview_layout_failure_and_success_paths(tmp_path, monkeypatch):
    plc = _preview_layout_module()
    # Call unwrapped body so mixin sync does not clobber local patches.
    materialize = plc.materialize_preview_layout_candidate.__wrapped__
    plc._TEMP_PREFIX = "fhd-etl-preview-layout-"
    plc._LAYOUT_SUFFIXES = frozenset({".xlsx", ".xlsm"})
    with patch.object(plc, "_find_preview_layout_record", return_value=None):
        assert materialize(owner_user_id=1, unit_name="甲") is None

    record = {
        "upload_storage_path": str(tmp_path / "missing.xlsx"),
        "upload_suffix": ".xlsx",
        "upload_expires_at": None,
        "source_features": {},
        "source_region_id": "r1",
        "run_id": "run-1",
        "template_id": "etl-preview:run-1",
        "name": "n",
        "customer_name": "甲",
        "sheet": "S",
        "header_row": 1,
        "file_name": "a.xlsx",
    }
    with (
        patch.object(plc, "_find_preview_layout_record", return_value=record),
        patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)),
        patch.object(plc, "_safe_owned_upload_path", return_value=None),
    ):
        assert materialize(owner_user_id=9, unit_name="甲") is None

    source = tmp_path / "src.xlsx"
    source.write_bytes(b"x")

    def empty_extract(_src, **_kwargs):
        Path(_kwargs["destination"]).write_bytes(b"")

    with (
        patch.object(plc, "_find_preview_layout_record", return_value=record),
        patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)),
        patch.object(plc, "_safe_owned_upload_path", return_value=source),
        patch.object(plc, "extract_shipment_template", side_effect=empty_extract),
    ):
        assert materialize(owner_user_id=9, unit_name="甲") is None

    def ok_extract(_src, **_kwargs):
        Path(_kwargs["destination"]).write_bytes(b"layout-bytes")

    with (
        patch.object(plc, "_find_preview_layout_record", return_value=record),
        patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)),
        patch.object(plc, "_safe_owned_upload_path", return_value=source),
        patch.object(plc, "extract_shipment_template", side_effect=ok_extract),
    ):
        candidate = materialize(owner_user_id=9, unit_name="甲")
    assert candidate is not None
    assert candidate["source"] == "etl_preview_candidate"
    Path(candidate["cleanup_path"]).unlink(missing_ok=True)


def test_find_preview_layout_record_run_id_and_scan():
    plc = _preview_layout_module()
    find_latest = plc.find_latest_preview_layout_candidate.__wrapped__
    run = SimpleNamespace(id="run-x")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = run

    class Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    with (
        patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)),
        patch.object(plc, "get_db", return_value=Ctx()),
        patch.object(
            plc,
            "_layout_candidate_for_run",
            return_value={
                "run_id": "run-x",
                "template_id": "etl-preview:run-x",
                "name": "n",
                "customer_name": "甲",
                "source_region_id": "r1",
                "sheet": "S",
                "header_row": 1,
                "file_name": "a.xlsx",
            },
        ),
    ):
        found = plc._find_preview_layout_record(owner_user_id=9, unit_name="甲", run_id="run-x")
        assert found["run_id"] == "run-x"

    db.query.return_value.filter.return_value.first.return_value = None
    with (
        patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)),
        patch.object(plc, "get_db", return_value=Ctx()),
    ):
        assert (
            plc._find_preview_layout_record(owner_user_id=9, unit_name="甲", run_id="missing")
            is None
        )

    with (
        patch.object(plc, "_valid_owner_and_tenant", return_value=(7, 9)),
        patch.object(plc, "get_db", return_value=Ctx()),
        patch.object(plc, "_preview_runs", return_value=[run]),
        patch.object(
            plc,
            "_layout_candidate_for_run",
            return_value={
                "run_id": "run-x",
                "template_id": "etl-preview:run-x",
                "name": "n",
                "customer_name": "甲",
                "source_region_id": "r1",
                "sheet": "S",
                "header_row": 1,
                "file_name": "a.xlsx",
            },
        ),
    ):
        public = find_latest(owner_user_id=9, unit_name="甲")
        assert public["run_id"] == "run-x"


# ---------------------------------------------------------------------------
# private_mod + knowledge omniscient quick wins
# ---------------------------------------------------------------------------


def test_private_mod_account_scope_and_corrupt_state(monkeypatch, tmp_path):
    assert delivery.account_scope(7) == "market:7"
    assert delivery.account_scope(0, "Alice") == "local:alice"
    assert delivery.account_scope(None, "") == "local:default"
    assert delivery.account_scope("bad", "Bob") == "local:bob"

    state_path = tmp_path / "state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(delivery, "_state_path", lambda: state_path)
    assert delivery._read_state()["accounts"] == {}

    state_path.write_text("[]", encoding="utf-8")
    assert delivery._read_state()["accounts"] == {}

    state_path.write_text(json.dumps({"accounts": "x"}), encoding="utf-8")
    raw = delivery._read_state()
    assert raw["accounts"] == {}

    with pytest.raises(ValueError):
        delivery.set_track_status("market:1", "m", "nope", "testing")
    with pytest.raises(ValueError):
        delivery.set_track_status("market:1", "m", "business", "nope")

    assert delivery.overall_status({"tracks": {"business": {"status": "rework"}}}) == "rework"
    assert delivery.overall_status({"tracks": {"business": {"status": "testing"}}}) == "testing"
    assert (
        delivery.overall_status(
            {
                "tracks": {
                    "business": {"status": "delivered"},
                    "employees": {"status": "delivered"},
                }
            }
        )
        == "delivered"
    )


@pytest.mark.asyncio
async def test_private_mod_fetch_library_and_auth_header():
    assert delivery._auth_header("abc") == "Bearer abc"
    assert delivery._auth_header("Bearer xyz") == "Bearer xyz"
    assert await delivery.fetch_private_mod_library("") == []

    with patch(
        "app.application.private_mod.delivery.catalog_get_json",
        new=AsyncMock(return_value={"mods": [{"id": "m1"}, "bad"]}),
    ):
        rows = await delivery.fetch_private_mod_library("tok")
    assert rows == [{"id": "m1"}]
    assert delivery._library_row_by_id(rows, "m1")["id"] == "m1"
    assert delivery._library_row_by_id(rows, "missing") is None

    with patch(
        "app.application.private_mod.delivery.catalog_get_json",
        new=AsyncMock(return_value={"data": [{"id": "m2"}]}),
    ):
        assert await delivery.fetch_private_mod_library("tok") == [{"id": "m2"}]

    with patch(
        "app.application.private_mod.delivery.catalog_get_json",
        new=AsyncMock(return_value={"data": "nope"}),
    ):
        assert await delivery.fetch_private_mod_library("tok") == []


def test_private_mod_project_state_and_status_helpers(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(delivery, "_state_path", lambda: state_path)

    project = delivery.project_state("market:1", "mod-x", name="X", version="1.0.0")
    assert project["name"] == "X"
    assert project["last_seen_version"] == "1.0.0"
    listed = delivery.account_projects("market:1")
    assert listed[0]["mod_id"] == "mod-x"
    empty_defaults = delivery.account_projects(
        "market:1", ["missing-mod"], names={"missing-mod": "M"}
    )
    assert empty_defaults[0]["name"] == "M"

    delivery.apply_account_state("market:1", {"projects": "bad"})
    delivery.apply_account_state(
        "market:1",
        {
            "projects": {
                "../bad": {"name": "no"},
                "mod-y": {
                    "name": "Y",
                    "tracks": {"business": {"status": "acceptance", "timeline": [{"status": "x"}]}},
                    "updated_at": "t",
                },
            }
        },
    )
    snap = delivery.export_account_state("market:1")
    assert "mod-y" in snap["projects"]

    updated = delivery.set_track_status(
        "market:1", "mod-y", "employees", "delivered", note="ok", name="Y2"
    )
    assert updated["tracks"]["employees"]["status"] == "delivered"
    assert delivery.overall_status(updated) in {"partial", "acceptance", "delivered"}
    assert delivery.stage_label("employees", "delivered")
    assert delivery.stage_label("business", "testing") == delivery.STAGE_LABELS["testing"]
    assert delivery.version_key("") == ((0, 0),)
    assert delivery.is_newer_version("2.0.0", "1.9.9") is True
    assert delivery.is_newer_version("", "1.0.0") is False


def test_failover_catalog_only_and_models_detailed_empty():
    out = failover.build_chat_failover_candidates(
        primary_provider="openai",
        primary_model="gpt-a",
        status_payload={"providers": [{"provider": "deepseek"}]},
        catalog_payload={
            "providers": [
                {"provider": "deepseek", "models_detailed": [{"id": ""}, "bad", {"id": "ds-1"}]}
            ]
        },
        max_attempts=3,
    )
    assert out[0] == ("openai", "gpt-a")
    assert ("deepseek", "ds-1") in out


def test_private_mod_delivery_applier(monkeypatch, tmp_path):
    _state = tmp_path / "state.json"
    monkeypatch.setattr(delivery, "_state_path", lambda: _state)
    delivery_applier._apply_private_mod_delivery({"payload": "bad"})
    delivery_applier._apply_private_mod_delivery({"payload": {}})
    delivery_applier._apply_private_mod_delivery(
        {
            "payload": {
                "market_user_id": 3,
                "username": "u",
                "projects": {
                    "mod-a": {
                        "name": "A",
                        "tracks": {"business": {"status": "testing", "timeline": []}},
                    }
                },
            }
        }
    )
    projects = delivery.account_projects("market:3", ["mod-a"])
    assert projects[0]["tracks"]["business"]["status"] == "testing"


def test_omniscient_overview_and_query_branches():
    request = MagicMock()
    access = SimpleNamespace(is_admin=False)
    with (
        patch.object(omni, "_dataset_access_context_from_request", return_value=access),
        patch.object(omni, "_dataset_admin_access", return_value=False),
    ):
        denied = omni.omniscient_overview(request)
        assert denied.status_code == 403

    access.is_admin = True
    service = MagicMock()
    service.status.return_value = {"datasets": {"ds1": {"name": "A"}}}
    service.query.side_effect = [
        {"success": False},
        {
            "success": True,
            "chunks": [{"score": 0.2, "text": "low"}, "bad", {"score": 0.9, "text": "high"}],
        },
    ]
    with (
        patch.object(omni, "_dataset_access_context_from_request", return_value=access),
        patch.object(omni, "_dataset_admin_access", return_value=True),
        patch.object(
            omni,
            "_knowledge_runtime_snapshot",
            return_value={
                "rag_enabled": True,
                "embedder_available": True,
                "semantic_embedding_available": True,
                "recommended_dataset_id": "ds1",
                "dataset_count": 1,
                "dataset_document_count": 2,
                "dataset_chunk_count": 3,
            },
        ),
        patch.object(omni, "_public_dataset_payload", side_effect=lambda payload: payload),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        overview = omni.omniscient_overview(request)
        assert overview["omniscient"] is True
        assert overview["dataset_count"] == 1

        service.status.return_value = {"datasets": {"a": {}, "b": {}}}
        result = omni.omniscient_query(QueryRequest(query="q", top_k=5), request)
        assert result["success"] is True
        assert result["chunks"][0]["text"] == "high"
        assert result["omniscient"] is True

    with (
        patch.object(omni, "_dataset_access_context_from_request", return_value=access),
        patch.object(omni, "_dataset_admin_access", return_value=False),
    ):
        denied_q = omni.omniscient_query(QueryRequest(query="q"), request)
        assert denied_q.status_code == 403
