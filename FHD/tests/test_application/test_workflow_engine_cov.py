from __future__ import annotations

"""Coverage-ramp tests for app.application.workflow.engine — missing branches.

Targets (line_from → line_to):
[23,24], [23,28], [144,231], [189,190], [231,232], [267,268], [286,287],
[288,289], [288,290], [290,291], [290,296], [300,301], [399,403], [404,406],
[432,434], [521,-504], [555,556], [559,560], [574,575], [576,577], [579,580],
[581,582], [583,584], [587,588], [589,591], [597,598], [639,641]
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.application.workflow.engine as engine_mod
from app.application.workflow.engine import WorkflowEngine, _get_sync_http_client
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(dispatch_return=None):
    """Return a WorkflowEngine whose dispatcher always returns *dispatch_return*."""

    def dispatch(tool_id, action, params):
        return dispatch_return if dispatch_return is not None else {"success": True}

    return WorkflowEngine(tool_dispatcher=dispatch)


def _node(
    node_id="n1",
    tool_id="products",
    action="query",
    risk="low",
    idempotent=True,
    params=None,
    depends_on=None,
):
    return WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        risk=risk,
        idempotent=idempotent,
        params=params or {},
        depends_on=depends_on or [],
    )


def _plan(nodes, plan_id="p1"):
    return PlanGraph(plan_id=plan_id, intent="test", todo_steps=[], nodes=nodes, risk_level="low")


def _fake_http_response(status_code: int = 200, body: dict | None = None):
    """Return a fake httpx-like response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    return resp


# ---------------------------------------------------------------------------
# 1. _get_sync_http_client — branch: client already initialised (lines 23-24)
# ---------------------------------------------------------------------------


class TestGetSyncHttpClient:
    def test_returns_existing_client_when_already_set(self):
        """Lines 23-24: if _sync_http_client is not None, return it."""
        fake_client = MagicMock()
        with patch.object(engine_mod, "_sync_http_client", fake_client):
            result = _get_sync_http_client()
        assert result is fake_client

    def test_creates_new_client_when_none(self):
        """Lines 23-28: if _sync_http_client is None, create and return a new one."""
        # Temporarily wipe the module-level singleton so the None branch executes.
        original = engine_mod._sync_http_client
        try:
            engine_mod._sync_http_client = None
            import httpx

            result = _get_sync_http_client()
            assert isinstance(result, httpx.Client)
        finally:
            # Restore whatever was there (may be None or a real client).
            engine_mod._sync_http_client = original


# ---------------------------------------------------------------------------
# 2. WorkflowEngine.run() dispatch branches (lines 44-48)
# ---------------------------------------------------------------------------


class TestRunDispatch:
    def test_run_uses_batch_when_not_agentic(self):
        """agentic_loop=False → _run_batch is called, not _run_agentic_loop."""
        engine = _make_engine({"success": True})
        plan = _plan([_node()])
        with patch.object(engine, "_run_batch", wraps=engine._run_batch) as mock_batch, patch.object(
            engine, "_run_agentic_loop"
        ) as mock_agentic:
            engine.run(plan)
        mock_batch.assert_called_once()
        mock_agentic.assert_not_called()

    def test_run_uses_batch_when_tool_registry_is_none(self):
        """agentic_loop=True but tool_registry=None → _run_batch."""
        engine = _make_engine({"success": True})
        plan = _plan([_node()])
        with patch.object(engine, "_run_batch", wraps=engine._run_batch) as mock_batch, patch.object(
            engine, "_run_agentic_loop"
        ) as mock_agentic:
            engine.run(plan, agentic_loop=True, tool_registry=None)
        mock_batch.assert_called_once()
        mock_agentic.assert_not_called()

    def test_run_uses_agentic_loop_when_configured(self):
        """agentic_loop=True and tool_registry not None → _run_agentic_loop."""
        engine = _make_engine({"success": True})
        plan = _plan([_node()])
        fake_result = WorkflowRunResult(plan_id="p1", success=True)
        with patch.object(engine, "_run_agentic_loop", return_value=fake_result) as mock_agentic:
            result = engine.run(
                plan, agentic_loop=True, tool_registry={"products": {}}, user_id="u1"
            )
        mock_agentic.assert_called_once()
        assert result.success is True


# ---------------------------------------------------------------------------
# 3. _run_agentic_loop — decision_action == "done" breaks loop (lines 144-231)
# ---------------------------------------------------------------------------


class TestAgenticLoopDoneBranch:
    def test_done_on_first_step_breaks_immediately(self):
        """Line 144-231: loop breaks as soon as decision_action == 'done'."""
        engine = _make_engine()
        plan = _plan([_node()])

        with patch.object(
            engine, "_llm_decide_next_step", return_value={"action": "done"}
        ) as mock_decide:
            result = engine._run_agentic_loop(
                plan=plan,
                runtime_context={"message": "hi"},
                max_retries=1,
                tool_registry={"products": {}},
                user_id=None,
            )

        # Only one call to the LLM — loop stopped at step 1.
        assert mock_decide.call_count == 1
        assert result.success is True
        assert "1 步" in result.message
        assert result.node_results == []

    def test_skip_when_tool_action_is_execute_placeholder(self):
        """Lines 189-190: tool_action == 'execute' → skip (continue)."""
        engine = _make_engine({"success": True})
        plan = _plan([_node()])
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # action_name/tool_action omitted → tool_action falls back to decision_action
                return {
                    "action": "execute",
                    "tool_id": "products",
                    # no action_name → tool_action == decision_action == "execute"
                    "params": {},
                    "reasoning": "r",
                }
            return {"action": "done"}

        with patch.object(engine, "_llm_decide_next_step", side_effect=side_effect):
            result = engine._run_agentic_loop(
                plan=plan,
                runtime_context={"message": "skip me"},
                max_retries=1,
                tool_registry={"products": {}},
                user_id=None,
            )

        # No tool was actually executed — the bad decision was skipped.
        assert result.node_results == []

    def test_skip_when_tool_id_empty(self):
        """Lines 189-190: empty tool_id → skip."""
        engine = _make_engine({"success": True})
        plan = _plan([_node()])
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "action": "execute",
                    "tool_id": "",
                    "action_name": "query",
                    "params": {},
                    "reasoning": "r",
                }
            return {"action": "done"}

        with patch.object(engine, "_llm_decide_next_step", side_effect=side_effect):
            result = engine._run_agentic_loop(
                plan=plan,
                runtime_context={"message": "empty tool_id"},
                max_retries=1,
                tool_registry={"products": {}},
                user_id=None,
            )

        assert result.node_results == []

    def test_max_steps_warning_logged(self):
        """Lines 231-232: step >= max_steps → warning is logged."""
        engine = _make_engine({"success": True})
        plan = _plan([_node()])

        # Always return a valid execute decision so the loop runs to exhaustion.
        always_execute = {
            "action": "execute",
            "tool_id": "products",
            "action_name": "query",
            "params": {},
            "reasoning": "keep going",
        }

        with patch.object(engine, "_llm_decide_next_step", return_value=always_execute), patch(
            "app.application.workflow.engine.logger"
        ) as mock_logger:
            result = engine._run_agentic_loop(
                plan=plan,
                runtime_context={"message": "loop"},
                max_retries=0,
                tool_registry={"products": {}},
                user_id=None,
            )

        # The warning about max_steps should have been emitted.
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("最大步数" in w for w in warning_calls)
        assert result.success is True


# ---------------------------------------------------------------------------
# 4. _llm_decide_next_step branches
# ---------------------------------------------------------------------------


class TestLlmDecideNextStep:
    """Tests for _llm_decide_next_step without making real HTTP calls."""

    def _engine_with_mocked_ai(self, api_key="secret"):
        engine = _make_engine()
        ai_svc = SimpleNamespace(api_key=api_key, api_url="http://fake/v1/chat", model="test-m")
        return engine, ai_svc

    def test_returns_none_when_api_key_empty(self):
        """Lines 267-268: empty api_key → return None."""
        engine, ai_svc = self._engine_with_mocked_ai(api_key="")

        with patch("app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc):
            result = engine._llm_decide_next_step(
                user_message="hi",
                tool_registry={},
                runtime_context={},
                agent_history=[],
                user_id=None,
            )
        assert result is None

    def test_history_role_done_appended(self):
        """Lines 286-287: history entry with role == 'done' → 'Assistant: 已完成任务'."""
        engine, ai_svc = self._engine_with_mocked_ai()

        # We need the HTTP call to succeed and return a sensible JSON.
        llm_body = {
            "choices": [{"message": {"content": '{"action": "done"}'}}]
        }
        fake_resp = _fake_http_response(200, llm_body)
        history = [{"role": "done"}]

        with patch(
            "app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc
        ), patch(
            "app.application.workflow.engine._get_sync_http_client"
        ) as mock_client_fn, patch(
            "app.application.workflow.engine.default_chat_completions_url",
            return_value="http://fake/v1/chat",
            create=True,
        ):
            # Patch the import inside the function.
            mock_http = MagicMock()
            mock_http.post.return_value = fake_resp
            mock_client_fn.return_value = mock_http

            with patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://fake/v1/chat",
                create=True,
            ):
                result = engine._llm_decide_next_step(
                    user_message="done already",
                    tool_registry={},
                    runtime_context={},
                    agent_history=history,
                    user_id=None,
                )

        assert result == {"action": "done"}

    def test_history_role_assistant_appended(self):
        """Lines 288-289: history entry with role == 'assistant'."""
        engine, ai_svc = self._engine_with_mocked_ai()
        llm_body = {"choices": [{"message": {"content": '{"action": "done"}'}}]}
        fake_resp = _fake_http_response(200, llm_body)
        history = [
            {
                "role": "assistant",
                "tool_id": "products",
                "action": "query",
                "reasoning": "testing",
            }
        ]

        with patch(
            "app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc
        ), patch("app.application.workflow.engine._get_sync_http_client") as mock_client_fn:
            mock_http = MagicMock()
            mock_http.post.return_value = fake_resp
            mock_client_fn.return_value = mock_http

            with patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://fake/v1/chat",
            ):
                result = engine._llm_decide_next_step(
                    user_message="test",
                    tool_registry={},
                    runtime_context={},
                    agent_history=history,
                    user_id=None,
                )
        assert result == {"action": "done"}

    def test_history_role_other_is_system(self):
        """Lines 288-290: history entry with role == 'system' (else branch)."""
        engine, ai_svc = self._engine_with_mocked_ai()
        llm_body = {"choices": [{"message": {"content": '{"action": "done"}'}}]}
        fake_resp = _fake_http_response(200, llm_body)
        history = [{"role": "system", "content": "Tool failed: timeout"}]

        with patch(
            "app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc
        ), patch("app.application.workflow.engine._get_sync_http_client") as mock_client_fn:
            mock_http = MagicMock()
            mock_http.post.return_value = fake_resp
            mock_client_fn.return_value = mock_http

            with patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://fake/v1/chat",
            ):
                result = engine._llm_decide_next_step(
                    user_message="test",
                    tool_registry={},
                    runtime_context={},
                    agent_history=history,
                    user_id=None,
                )
        assert result == {"action": "done"}

    def test_excel_analysis_dict_populates_excel_info(self):
        """Lines 290-291: excel_analysis is a dict → excel_info is non-empty."""
        engine, ai_svc = self._engine_with_mocked_ai()
        llm_body = {"choices": [{"message": {"content": '{"action": "done"}'}}]}
        fake_resp = _fake_http_response(200, llm_body)
        ctx = {"excel_analysis": {"file_path": "/tmp/data.xlsx"}}

        with patch(
            "app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc
        ), patch("app.application.workflow.engine._get_sync_http_client") as mock_client_fn:
            mock_http = MagicMock()
            mock_http.post.return_value = fake_resp
            mock_client_fn.return_value = mock_http

            with patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://fake/v1/chat",
            ):
                result = engine._llm_decide_next_step(
                    user_message="test",
                    tool_registry={},
                    runtime_context=ctx,
                    agent_history=[],
                    user_id=None,
                )
        assert result == {"action": "done"}

    def test_excel_analysis_non_dict_skips_excel_info(self):
        """Lines 290-296: excel_analysis not a dict → excel_info stays empty."""
        engine, ai_svc = self._engine_with_mocked_ai()
        llm_body = {"choices": [{"message": {"content": '{"action": "done"}'}}]}
        fake_resp = _fake_http_response(200, llm_body)
        ctx = {"excel_analysis": "not a dict value"}

        with patch(
            "app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc
        ), patch("app.application.workflow.engine._get_sync_http_client") as mock_client_fn:
            mock_http = MagicMock()
            mock_http.post.return_value = fake_resp
            mock_client_fn.return_value = mock_http

            with patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://fake/v1/chat",
            ):
                result = engine._llm_decide_next_step(
                    user_message="test",
                    tool_registry={},
                    runtime_context=ctx,
                    agent_history=[],
                    user_id=None,
                )
        assert result == {"action": "done"}

    def test_returns_none_on_http_4xx(self):
        """Lines 300-301: response.status_code >= 400 → return None."""
        engine, ai_svc = self._engine_with_mocked_ai()
        fake_resp = _fake_http_response(status_code=500)

        with patch(
            "app.application.workflow.engine.get_ai_conversation_service", return_value=ai_svc
        ), patch("app.application.workflow.engine._get_sync_http_client") as mock_client_fn:
            mock_http = MagicMock()
            mock_http.post.return_value = fake_resp
            mock_client_fn.return_value = mock_http

            with patch(
                "app.infrastructure.llm.providers.credentials.default_chat_completions_url",
                return_value="http://fake/v1/chat",
            ):
                result = engine._llm_decide_next_step(
                    user_message="test",
                    tool_registry={},
                    runtime_context={},
                    agent_history=[],
                    user_id=None,
                )
        assert result is None


# ---------------------------------------------------------------------------
# 5. _summarize_output branches (lines 399-406)
# ---------------------------------------------------------------------------


class TestSummarizeOutputBranches:
    def test_success_true_empty_msg_data_is_list(self):
        """Lines 399-403: success=True, no message, data is a non-empty list."""
        out = {"success": True, "data": ["a", "b", "c"]}
        summary = WorkflowEngine._summarize_output(out)
        assert "3 条数据" in summary

    def test_success_true_empty_msg_data_is_not_list(self):
        """Lines 404-406: success=True, no message, data is not a list (scalar)."""
        out = {"success": True, "data": "some scalar value"}
        summary = WorkflowEngine._summarize_output(out)
        assert "some scalar value" in summary

    def test_success_true_empty_msg_data_is_none(self):
        """success=True, no message, data=None → falls through to error/fallback."""
        out = {"success": True, "data": None}
        # data is None, so the data branch is skipped; no error → returns str(output)[:200]
        summary = WorkflowEngine._summarize_output(out)
        # Should not raise and should return something printable.
        assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# 6. _run_single_tool — retryable=False sets effective_max_retries=0 (line 432-434)
#    and retries exhausted path (line 521)
# ---------------------------------------------------------------------------


class TestRunSingleToolBranches:
    def test_retryable_false_no_retries_attempted(self):
        """Lines 432-434: retryable=False → effective_max_retries=0 → single attempt only."""
        call_count = 0

        def counting_dispatch(tool_id, action, params):
            nonlocal call_count
            call_count += 1
            return {"success": False, "message": "fail"}

        engine = WorkflowEngine(tool_dispatcher=counting_dispatch)
        result = engine._run_single_tool(
            tool_id="products",
            action="query",
            params={},
            runtime_context={},
            max_retries=5,  # Would allow 5 retries if retryable
            retryable=False,  # Overrides to 0
        )

        assert result.success is False
        # With effective_max_retries=0, loop runs exactly once (retries=0 <= 0).
        assert call_count == 1
        assert result.retries == 0

    def test_retries_exhausted_returns_failure_result(self):
        """Line 521 (post-loop): all retries exhausted → NodeExecutionResult with success=False."""
        engine = _make_engine({"success": False, "message": "always fails"})
        result = engine._run_single_tool(
            tool_id="inventory",
            action="check",
            params={"item": "X"},
            runtime_context={},
            max_retries=2,
            retryable=True,
        )
        assert result.success is False
        assert result.error == "always fails"
        assert result.retries == 2  # max(0, retries-1) after loop

    def test_retryable_true_retries_on_failure(self):
        """Successful retry on second attempt when retryable=True."""
        call_count = 0

        def flaky(tool_id, action, params):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return {"success": False, "message": "temp"}
            return {"success": True}

        engine = WorkflowEngine(tool_dispatcher=flaky)
        result = engine._run_single_tool(
            tool_id="x",
            action="y",
            params={},
            runtime_context={},
            max_retries=2,
            retryable=True,
        )
        assert result.success is True
        assert call_count == 2


# ---------------------------------------------------------------------------
# 7. _has_non_empty_param — None and blank-string branches (lines 555-560)
# ---------------------------------------------------------------------------


class TestHasNonEmptyParamBranches:
    def test_none_value_is_skipped(self):
        """Lines 555-556: v is None → skipped, returns False."""
        assert WorkflowEngine._has_non_empty_param({"k": None}, ("k",)) is False

    def test_blank_string_value_is_skipped(self):
        """Lines 559-560: v is not None but str(v).strip() is empty → skipped, returns False."""
        assert WorkflowEngine._has_non_empty_param({"k": "   "}, ("k",)) is False

    def test_zero_int_is_treated_as_empty(self):
        """0 → str(0).strip() == '0' which is truthy — actually non-empty."""
        # '0' is non-empty, so this should return True.
        assert WorkflowEngine._has_non_empty_param({"k": 0}, ("k",)) is True

    def test_non_empty_value_returns_true(self):
        assert WorkflowEngine._has_non_empty_param({"k": "hello"}, ("k",)) is True

    def test_multiple_keys_first_match_wins(self):
        assert (
            WorkflowEngine._has_non_empty_param({"a": None, "b": "found"}, ("a", "b")) is True
        )


# ---------------------------------------------------------------------------
# 8. _merge_runtime_fallback_params branches (lines 574-591)
# ---------------------------------------------------------------------------


class TestMergeRuntimeFallbackParamsBranches:
    def test_empty_user_msg_returns_early(self):
        """Lines 574-575: user_msg is empty → return immediately, no injection."""
        engine = _make_engine()
        node = _node(tool_id="products", action="query")
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": ""})
        assert "keyword" not in params

    def test_products_query_with_existing_keyword_no_injection(self):
        """Lines 576-577: products.query but keyword already set → no injection."""
        engine = _make_engine()
        node = _node(tool_id="products", action="query")
        params = {"keyword": "existing"}
        engine._merge_runtime_fallback_params(node, params, {"message": "other"})
        assert params["keyword"] == "existing"  # Unchanged

    def test_products_query_empty_params_injects_keyword(self):
        """Lines 579-580: products.query, no keyword params → inject user_msg."""
        engine = _make_engine()
        node = _node(tool_id="products", action="query")
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "find bolts"})
        assert params["keyword"] == "find bolts"

    def test_customers_branch_entered(self):
        """Lines 581-582: node.tool_id == 'customers' and action == 'query'."""
        engine = _make_engine()
        node = _node(tool_id="customers", action="query")
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "Alice"})
        # Should inject because no keyword params present.
        assert params["keyword"] == "Alice"

    def test_customers_query_non_empty_keyword_no_injection(self):
        """Lines 583-584: customers.query but keyword present → no injection."""
        engine = _make_engine()
        node = _node(tool_id="customers", action="query")
        params = {"keyword": "Bob"}
        engine._merge_runtime_fallback_params(node, params, {"message": "Alice"})
        assert params["keyword"] == "Bob"

    def test_customers_query_empty_keyword_injects(self):
        """Lines 587-588: customers.query, empty keyword → inject."""
        engine = _make_engine()
        node = _node(tool_id="customers", action="query")
        params = {"keyword": ""}
        engine._merge_runtime_fallback_params(node, params, {"message": "Charlie"})
        assert params["keyword"] == "Charlie"

    def test_other_tool_not_injected(self):
        """Lines 589-591: else branch — other tool_id → nothing injected."""
        engine = _make_engine()
        node = _node(tool_id="inventory", action="query")
        params = {}
        engine._merge_runtime_fallback_params(node, params, {"message": "some message"})
        assert "keyword" not in params


# ---------------------------------------------------------------------------
# 9. _node_allows_auto_retry — idempotent=False but risk=low (line 597-598)
# ---------------------------------------------------------------------------


class TestNodeAllowsAutoRetryBranches:
    def test_idempotent_false_risk_low_allows_retry(self):
        """Lines 597-598: idempotent=False, risk='low' → True (risk branch)."""
        node = _node(idempotent=False, risk="low")
        assert WorkflowEngine._node_allows_auto_retry(node) is True

    def test_idempotent_true_any_risk_allows_retry(self):
        """idempotent=True → True regardless of risk."""
        node = _node(idempotent=True, risk="high")
        assert WorkflowEngine._node_allows_auto_retry(node) is True

    def test_idempotent_false_risk_high_disallows_retry(self):
        """idempotent=False, risk='high' → False."""
        node = _node(idempotent=False, risk="high")
        assert WorkflowEngine._node_allows_auto_retry(node) is False


# ---------------------------------------------------------------------------
# 10. _agentic_tool_allows_auto_retry — idempotent=False, risk != 'low' (lines 639-641)
# ---------------------------------------------------------------------------


class TestAgenticToolAllowsAutoRetryBranches:
    def test_meta_idempotent_false_risk_not_low_returns_false(self):
        """Lines 639-641: meta.idempotent=False, risk='high' → False."""
        registry = {
            "inventory": {
                "actions": {
                    "delete": {"idempotent": False, "risk": "high"},
                }
            }
        }
        result = WorkflowEngine._agentic_tool_allows_auto_retry(registry, "inventory", "delete")
        assert result is False

    def test_meta_idempotent_false_risk_low_returns_true(self):
        """meta.idempotent=False but risk='low' → True."""
        registry = {
            "inventory": {
                "actions": {
                    "query": {"idempotent": False, "risk": "low"},
                }
            }
        }
        result = WorkflowEngine._agentic_tool_allows_auto_retry(registry, "inventory", "query")
        assert result is True

    def test_meta_idempotent_true_returns_true(self):
        """meta.idempotent=True → True."""
        registry = {
            "inventory": {
                "actions": {
                    "add": {"idempotent": True, "risk": "medium"},
                }
            }
        }
        result = WorkflowEngine._agentic_tool_allows_auto_retry(registry, "inventory", "add")
        assert result is True

    def test_missing_tool_id_returns_true(self):
        """Tool not in registry → spec is None → return True (safe default)."""
        result = WorkflowEngine._agentic_tool_allows_auto_retry({}, "unknown", "any")
        assert result is True

    def test_spec_not_dict_returns_true(self):
        """spec is not a dict → return True."""
        registry = {"inventory": "not-a-dict"}
        result = WorkflowEngine._agentic_tool_allows_auto_retry(registry, "inventory", "query")
        assert result is True

    def test_meta_not_dict_returns_true(self):
        """action meta is not a dict → return True."""
        registry = {"inventory": {"actions": {"query": "not-a-dict"}}}
        result = WorkflowEngine._agentic_tool_allows_auto_retry(registry, "inventory", "query")
        assert result is True
