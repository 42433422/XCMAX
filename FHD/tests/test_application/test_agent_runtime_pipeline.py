"""统一 Agent Runtime 主链路收口测试：编排 / 计费 / 记忆 / RAG 四接缝。

覆盖：
- pipeline 内核：hooks 开关、usage 提取、计量入账、知识召回、终态记忆回写
- agent_orchestrator 接线：memory_recall → run.memory_references、
  知识召回 RetrievalCall、终态 runtime.memory_writeback 事件
- planner_llm_gateway 计量（source=agent_planner）
- employee agent_loop 每轮计量（source=employee_agent_loop）
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.application.agent_runtime.pipeline import (
    agent_runtime_hooks_enabled,
    completion_usage,
    meter_llm_call,
    recall_knowledge_context,
    remember_run_outcome,
)


@pytest.fixture(autouse=True)
def _isolated_agent_usage_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    monkeypatch.delenv("XCAGI_AGENT_RUNTIME_HOOKS", raising=False)
    monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)


def _read_ledger(tmp_path):
    path = tmp_path / "model_usage_ledger.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entries") or []


class TestAgentRuntimeHooksSwitch:
    def test_default_off(self):
        assert agent_runtime_hooks_enabled() is False

    @pytest.mark.parametrize("raw", ["1", "true", "YES", "on"])
    def test_explicit_on(self, monkeypatch, raw):
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", raw)
        assert agent_runtime_hooks_enabled() is True

    @pytest.mark.parametrize("raw", ["0", "false", "off", "", "garbage"])
    def test_explicit_off_or_garbage(self, monkeypatch, raw):
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", raw)
        assert agent_runtime_hooks_enabled() is False

    @pytest.mark.parametrize("raw", [" 1 ", "TRUE", "On", "True"])
    def test_on_tolerates_whitespace_and_case(self, monkeypatch, raw):
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", raw)
        assert agent_runtime_hooks_enabled() is True

    @pytest.mark.parametrize("raw", [" 0 ", "enabled", "2", "OFF"])
    def test_off_rejects_lookalike_values(self, monkeypatch, raw):
        # 仅精确匹配 on 集合才放行，形近值一律关闭（fail-closed）
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", raw)
        assert agent_runtime_hooks_enabled() is False

    def test_gate_is_read_live_not_cached(self, monkeypatch):
        # 灰度切换无需重启进程：每次调用都实时读 env
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        assert agent_runtime_hooks_enabled() is True
        monkeypatch.delenv("XCAGI_AGENT_RUNTIME_HOOKS")
        assert agent_runtime_hooks_enabled() is False
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        assert agent_runtime_hooks_enabled() is True


class TestHooksGatePipelineContracts:
    """门控边界契约：pipeline 原语自身不读开关，灰度决策只存在于接缝调用方。"""

    def test_recall_primitive_does_not_self_gate(self, monkeypatch):
        monkeypatch.delenv("XCAGI_AGENT_RUNTIME_HOOKS", raising=False)
        result = recall_knowledge_context(query="q", dataset_id="")
        assert result["status"] == "skipped"

    def test_remember_primitive_does_not_self_gate(self, monkeypatch):
        monkeypatch.delenv("XCAGI_AGENT_RUNTIME_HOOKS", raising=False)
        with (
            patch("app.services.conversation_service.ConversationService", lambda: MagicMock()),
            patch(
                "app.application.user_memory_vector_app_service."
                "get_user_memory_vector_ingest_app_service",
                lambda: MagicMock(
                    **{"ingest_chunks.return_value": {"success": True, "written": 1}}
                ),
            ),
        ):
            assert (
                remember_run_outcome(user_id="u1", task="t", summary="s", session_id="s1") is True
            )


class TestCompletionUsage:
    def test_object_form(self):
        completion = MagicMock()
        completion.usage.prompt_tokens = 11
        completion.usage.completion_tokens = 7
        completion.usage.total_tokens = 18
        assert completion_usage(completion) == {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }

    def test_dict_form_and_total_fallback(self):
        payload = {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}
        assert completion_usage(payload) == {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        }

    def test_missing_usage(self):
        assert sum(completion_usage(MagicMock(spec=[])).values()) == 0
        assert sum(completion_usage({"model": "x"}).values()) == 0


class TestMeterLlmCall:
    def test_records_into_ledger(self, tmp_path):
        entry = meter_llm_call(
            source="employee_agent_loop",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            metadata={"employee_id": "emp1"},
        )
        assert entry is not None
        assert entry["source"] == "employee_agent_loop"
        assert entry["total_tokens"] == 15
        entries = _read_ledger(tmp_path)
        assert len(entries) == 1
        assert entries[0]["usage_id"] == entry["usage_id"]

    def test_metering_not_gated_by_hooks_switch(self, tmp_path):
        # hooks 默认关，但计费必须始终生效（主链路硬接缝）
        assert agent_runtime_hooks_enabled() is False
        entry = meter_llm_call(
            source="agent_planner", model="m", usage={"prompt_tokens": 1, "completion_tokens": 1}
        )
        assert entry is not None
        assert len(_read_ledger(tmp_path)) == 1

    def test_failure_returns_none(self, monkeypatch):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        def _boom(**kwargs):
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr("app.infrastructure.billing.model_usage.record_model_usage", _boom)
        assert meter_llm_call(source="agent_planner", model="m", usage={"total_tokens": 3}) is None


class TestRecallKnowledgeContext:
    def test_without_dataset_skipped(self):
        result = recall_knowledge_context(query="如何退货")
        assert result["status"] == "skipped"
        assert result["chunks"] == []

    def test_with_dataset_returns_chunks(self, monkeypatch):
        svc = MagicMock()
        svc.query.return_value = {
            "success": True,
            "chunks": [{"text": "7 天无理由退货", "score": 0.9}],
            "citations": [{"index": 1, "text": "7 天无理由退货"}],
        }
        monkeypatch.setattr(
            "app.application.dataset_rag_app_service_part05.get_dataset_rag_app_service",
            lambda: svc,
        )
        result = recall_knowledge_context(query="退货政策", dataset_id="ds1", top_k=3)
        assert result["status"] == "completed"
        assert result["retriever"] == "dataset_rag"
        assert result["source"] == "ds1"
        assert result["chunks"] and result["citations"]
        svc.query.assert_called_once()

    def test_backend_failure_degrades(self, monkeypatch):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        def _boom():
            raise RuntimeError("dataset backend down")

        monkeypatch.setattr(
            "app.application.dataset_rag_app_service_part05.get_dataset_rag_app_service",
            _boom,
        )
        result = recall_knowledge_context(query="q", dataset_id="ds1")
        assert result["status"] == "failed"
        assert result["chunks"] == []


class TestRememberRunOutcome:
    def test_writes_short_term_and_long_term(self, monkeypatch):
        saved = []
        ingested = []

        svc = MagicMock()
        svc.save_message.side_effect = lambda *a, **k: saved.append(a)
        monkeypatch.setattr("app.services.conversation_service.ConversationService", lambda: svc)

        from app.application.user_memory_vector_app_service import UserMemoryVectorChunk

        ingest = MagicMock()
        ingest.ingest_chunks.side_effect = lambda user_id, chunks: (
            ingested.append((user_id, chunks)) or {"success": True, "written": len(chunks)}
        )
        monkeypatch.setattr(
            "app.application.user_memory_vector_app_service."
            "get_user_memory_vector_ingest_app_service",
            lambda: ingest,
        )

        ok = remember_run_outcome(
            user_id="u1",
            task="查产品库存",
            summary="查询完成，共 3 条",
            success=True,
            session_id="s1",
            metadata={"run_id": "run-1"},
        )
        assert ok is True
        assert len(saved) == 2  # user task + assistant summary
        assert ingested and ingested[0][0] == "u1"
        chunk: UserMemoryVectorChunk = ingested[0][1][0]
        assert chunk.content.startswith("[agent_run]")
        assert chunk.metadata["source"] == "agent_runtime"

    def test_empty_payload_returns_false(self):
        assert remember_run_outcome(user_id="u1", task="", summary="") is False

    def test_backend_failure_degrades_false(self, monkeypatch):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        svc = MagicMock()
        svc.save_message.side_effect = RuntimeError("db down")
        monkeypatch.setattr("app.services.conversation_service.ConversationService", lambda: svc)
        monkeypatch.setattr(
            "app.application.user_memory_vector_app_service."
            "get_user_memory_vector_ingest_app_service",
            MagicMock(side_effect=RuntimeError("vector down")),
        )
        assert remember_run_outcome(user_id="u1", task="t", summary="s", session_id="s1") is False


class TestOrchestratorMainLinkWiring:
    def _build_orchestrator(self):
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.agent_orchestrator.run_repository import (
            InMemoryAgentRunRepository,
        )

        return AgentOrchestrator(repository=InMemoryAgentRunRepository())

    def test_plan_memory_recall_lands_on_run(self):
        from app.application.workflow.types import PlanGraph

        plan = PlanGraph(plan_id="p1", intent="test")
        plan.metadata["memory_recall"] = {
            "user_memory_rag": {
                "summary": "【UserMemoryRAG】偏好摘要",
                "hits": [{"content": "偏好企业微信通知", "score": 0.8}],
            },
            "memory_v2": {"summary": "用户偏好简明结论"},
        }
        orch = self._build_orchestrator()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": []},
        ):
            run = orch.start_run_from_plan(
                user_id="u1", message="查库存", plan=plan, auto_execute=False
            )

        assert len(run.memory_references) == 2
        assert run.memory_references[0].source == "user_memory_rag"
        assert run.memory_references[0].hits
        assert run.memory_references[1].memory_type == "memory_v2"
        assert any(e.event_type == "runtime.memory_recalled" for e in run.events)

    def test_knowledge_recall_lands_on_retrieval_calls(self):
        call = {
            "query": "q",
            "retriever": "dataset_rag",
            "source": "ds1",
            "top_k": 5,
            "chunks": [{"text": "t"}],
            "citations": [{"index": 1}],
            "status": "completed",
            "error": "",
        }
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="q")
        with (
            patch(
                "app.application.agent_runtime.pipeline.agent_runtime_hooks_enabled",
                return_value=True,
            ),
            patch(
                "app.application.agent_runtime.pipeline.recall_knowledge_context",
                return_value=call,
            ),
        ):
            orch._recall_knowledge_for_run(run, context={})

        assert len(run.retrieval_calls) == 1
        assert run.retrieval_calls[0].source == "ds1"
        assert any(e.event_type == "runtime.knowledge_recalled" for e in run.events)

    def test_knowledge_recall_disabled_by_switch(self):
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="q")
        with patch(
            "app.application.agent_runtime.pipeline.recall_knowledge_context"
        ) as mock_recall:
            orch._recall_knowledge_for_run(run, context={})
        mock_recall.assert_not_called()
        assert run.retrieval_calls == []

    def test_terminal_writeback_event_on_completed_run(self):
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="查库存")
        run.status = "completed"
        run.final_output = {"node_outputs": {"n1": {"message": "库存充足"}}}
        with (
            patch(
                "app.application.agent_runtime.pipeline.agent_runtime_hooks_enabled",
                return_value=True,
            ),
            patch(
                "app.application.agent_runtime.pipeline.remember_run_outcome",
                return_value=True,
            ) as mock_remember,
        ):
            orch._remember_run_outcome_for(run)

        mock_remember.assert_called_once()
        assert mock_remember.call_args.kwargs["success"] is True
        assert mock_remember.call_args.kwargs["summary"] == "库存充足"
        assert any(e.event_type == "runtime.memory_writeback" for e in run.events)

    def test_writeback_skipped_when_hooks_off(self):
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="查库存")
        run.status = "completed"
        with patch("app.application.agent_runtime.pipeline.remember_run_outcome") as mock_remember:
            orch._remember_run_outcome_for(run)
        mock_remember.assert_not_called()

    def test_gate_off_leaves_run_and_context_untouched(self):
        # 开关关闭：不召回、不上账、不注入 planner context、无 runtime 事件
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="q")
        context: dict = {"message": "q"}
        with patch(
            "app.application.agent_runtime.pipeline.recall_knowledge_context"
        ) as mock_recall:
            orch._recall_knowledge_for_run(run, context=context)
        mock_recall.assert_not_called()
        assert run.retrieval_calls == []
        assert "knowledge_rag" not in context
        assert not any(e.event_type.startswith("runtime.") for e in run.events)

    def test_gate_on_injects_knowledge_rag_into_context(self, monkeypatch):
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        call = {
            "query": "q",
            "retriever": "dataset_rag",
            "source": "ds1",
            "top_k": 5,
            "chunks": [{"text": "t"}],
            "citations": [{"index": 1}],
            "status": "completed",
            "error": "",
        }
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="q")
        context: dict = {"dataset_id": "ds1"}
        with patch(
            "app.application.agent_runtime.pipeline.recall_knowledge_context",
            return_value=call,
        ) as mock_recall:
            orch._recall_knowledge_for_run(run, context=context)
        mock_recall.assert_called_once_with(query="q", dataset_id="ds1")
        assert context["knowledge_rag"]["dataset_id"] == "ds1"
        assert context["knowledge_rag"]["chunks"] == [{"text": "t"}]
        assert run.retrieval_calls[0].source == "ds1"

    def test_gate_on_skipped_recall_adds_no_retrieval(self, monkeypatch):
        # hooks 开但未指定 dataset → skipped 短路：不上账、不发事件
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="q")
        with patch(
            "app.application.agent_runtime.pipeline.recall_knowledge_context",
            return_value={"status": "skipped", "chunks": [], "citations": []},
        ):
            orch._recall_knowledge_for_run(run, context={})
        assert run.retrieval_calls == []
        assert not any(e.event_type == "runtime.knowledge_recalled" for e in run.events)

    def test_writeback_failure_still_traced_when_gate_on(self, monkeypatch):
        # hooks 开 + 回写后端失败 → 事件仍上账且 remembered=False（降级可观测）
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        orch = self._build_orchestrator()
        from app.application.agent_orchestrator.run_models import AgentRun

        run = AgentRun(user_id="u1", message="查库存")
        run.status = "completed"
        run.final_output = {"node_outputs": {"n1": {"message": "库存充足"}}}
        with patch(
            "app.application.agent_runtime.pipeline.remember_run_outcome",
            return_value=False,
        ):
            orch._remember_run_outcome_for(run)
        events = [e for e in run.events if e.event_type == "runtime.memory_writeback"]
        assert len(events) == 1
        assert events[0].data["remembered"] is False

    def test_full_run_records_writeback_event(self, monkeypatch):
        """端到端：start_run_from_plan 全流程 → completed + runtime.memory_writeback。"""
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        from app.application.workflow.types import PlanGraph, WorkflowNode

        plan = PlanGraph(
            plan_id="p1",
            intent="business_db_read",
            nodes=[
                WorkflowNode(
                    node_id="read_db",
                    tool_id="business_db",
                    action="read",
                    params={"entity": "products", "keyword": "XG"},
                    risk="low",
                    idempotent=True,
                )
            ],
        )
        orch = self._build_orchestrator()
        with (
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [{"model_number": "XG-5003"}]},
            ),
            patch(
                "app.application.agent_runtime.pipeline.remember_run_outcome",
                return_value=True,
            ) as mock_remember,
        ):
            run = orch.start_run_from_plan(user_id="u1", message="查数据库产品 XG-5003", plan=plan)

        assert run.status == "completed"
        mock_remember.assert_called_once()
        assert any(e.event_type == "runtime.memory_writeback" for e in run.events)


class TestPlannerGatewayMetering:
    def test_direct_key_path_meters(self, tmp_path):
        from app.application.workflow import planner_llm_gateway

        ai_service = MagicMock()
        ai_service.api_key = "sk-test"
        ai_service.api_url = "http://llm.test/v1/chat/completions"
        ai_service.model = "test-model"

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"content": "plan"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }
        http_client = MagicMock()
        http_client.post.return_value = response

        result = planner_llm_gateway.request_planner_completion(
            ai_service=ai_service,
            context={},
            messages=[{"role": "user", "content": "plan this"}],
            http_client_factory=lambda: http_client,
        )
        assert result is not None
        entries = _read_ledger(tmp_path)
        assert len(entries) == 1
        assert entries[0]["source"] == "agent_planner"
        assert entries[0]["model"] == "test-model"
        assert entries[0]["total_tokens"] == 20

    def test_failed_http_call_does_not_meter(self, tmp_path):
        from app.application.workflow import planner_llm_gateway

        ai_service = MagicMock()
        ai_service.api_key = "sk-test"
        ai_service.api_url = "http://llm.test/v1/chat/completions"
        ai_service.model = "test-model"

        response = MagicMock()
        response.status_code = 500
        http_client = MagicMock()
        http_client.post.return_value = response

        result = planner_llm_gateway.request_planner_completion(
            ai_service=ai_service,
            context={},
            messages=[{"role": "user", "content": "plan this"}],
            http_client_factory=lambda: http_client,
        )
        assert result is None
        assert _read_ledger(tmp_path) == []


class TestEmployeeAgentLoopMetering:
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="test-model")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_each_round_meters_usage(
        self, mock_key, mock_client, mock_model, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        from app.application.employee_runtime.agent_loop import run_employee_agent_loop

        completion = MagicMock()
        msg = MagicMock()
        msg.content = "已完成"
        msg.tool_calls = None
        completion.choices = [MagicMock(message=msg)]
        completion.usage.prompt_tokens = 9
        completion.usage.completion_tokens = 6
        completion.usage.total_tokens = 15

        client_instance = MagicMock()
        client_instance.chat.completions.create.return_value = completion
        mock_client.return_value = client_instance

        result = run_employee_agent_loop(
            employee_id="emp1", system_prompt="test", task="do something"
        )
        assert result["ok"] is True

        entries = _read_ledger(tmp_path)
        assert len(entries) == 1
        assert entries[0]["source"] == "employee_agent_loop"
        assert entries[0]["model"] == "test-model"
        assert entries[0]["total_tokens"] == 15
        assert entries[0]["metadata"]["employee_id"] == "emp1"

    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="test-model")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_metering_failure_does_not_break_loop(
        self, mock_key, mock_client, mock_model, monkeypatch
    ):
        monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "1")
        from app.application.employee_runtime.agent_loop import run_employee_agent_loop

        completion = MagicMock()
        msg = MagicMock()
        msg.content = "已完成"
        msg.tool_calls = None
        completion.choices = [MagicMock(message=msg)]
        completion.usage.prompt_tokens = 1
        completion.usage.completion_tokens = 1
        completion.usage.total_tokens = 2

        client_instance = MagicMock()
        client_instance.chat.completions.create.return_value = completion
        mock_client.return_value = client_instance

        def _boom(**kwargs):
            raise RuntimeError("ledger exploded")

        with patch("app.application.agent_runtime.pipeline.meter_llm_call", side_effect=_boom):
            result = run_employee_agent_loop(
                employee_id="emp1", system_prompt="test", task="do something"
            )
        assert result["ok"] is True


class TestEmployeeModLlmMetering:
    """mod 直连通道（httpx）绕过宿主 chat_completion，必须显式计量。"""

    @staticmethod
    def _direct_override() -> dict:
        return {
            "use_direct": True,
            "api_key": "k",
            "chat_url": "http://llm.test/v1/chat/completions",
            "model": "deepseek-chat",
            "provider": "deepseek",
        }

    @staticmethod
    def _raw_response() -> dict:
        return {
            "model": "deepseek-chat",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }

    def _run_complete(self, raw: dict) -> dict:
        import asyncio

        from app.mod_sdk import mod_employee_llm

        async def _fake_call(*args, **kwargs):
            return raw

        with (
            patch.object(
                mod_employee_llm,
                "_resolve_provider_override",
                return_value=self._direct_override(),
            ),
            patch.object(mod_employee_llm, "_resolve_fallback_overrides", return_value=[]),
            patch.object(mod_employee_llm, "_call_openai_compatible_chat", _fake_call),
        ):
            return asyncio.run(
                mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
            )

    def test_direct_channel_meters_usage(self, tmp_path):
        result = self._run_complete(self._raw_response())
        assert result["success"] is True
        entries = _read_ledger(tmp_path)
        assert len(entries) == 1
        assert entries[0]["source"] == "employee_mod_llm"
        assert entries[0]["model"] == "deepseek-chat"
        assert entries[0]["provider"] == "deepseek"
        assert entries[0]["metadata"]["channel"] == "mod_direct"
        assert entries[0]["total_tokens"] == 10

    def test_zero_usage_not_metered(self, tmp_path):
        raw = {"model": "m", "choices": [{"message": {"content": "ok"}}]}
        result = self._run_complete(raw)
        assert result["success"] is True
        assert _read_ledger(tmp_path) == []

    def test_metering_failure_does_not_break_completion(self, tmp_path):
        with patch(
            "app.application.agent_runtime.pipeline.meter_llm_call",
            side_effect=RuntimeError("ledger exploded"),
        ):
            result = self._run_complete(self._raw_response())
        assert result["success"] is True
        assert _read_ledger(tmp_path) == []
