"""Model isolation and concurrent breaker recovery at the existing admission boundary."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException as FastAPIHTTPException
from openai import APIStatusError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.infrastructure.llm import model_admission as admission


@pytest.fixture(autouse=True)
def gates(monkeypatch):
    monkeypatch.setattr(admission, "_MODEL_BREAKERS", {})
    monkeypatch.setattr(admission, "_MODEL_INFLIGHT", 0)
    monkeypatch.setattr(admission, "_MODEL_ROUTE_INFLIGHT", {})
    monkeypatch.setenv("XCAGI_MODEL_BREAKER_THRESHOLD", "2")
    monkeypatch.setenv("XCAGI_MODEL_BREAKER_COOLDOWN", "10")
    monkeypatch.setenv("XCAGI_MODEL_MAX_INFLIGHT", "4")
    monkeypatch.setenv("XCAGI_MODEL_MAX_INFLIGHT_PER_MODEL", "2")
    clock = [100.0]
    monkeypatch.setattr(admission.time, "monotonic", lambda: clock[0])
    yield clock
    assert admission._MODEL_INFLIGHT == 0
    assert admission._MODEL_ROUTE_INFLIGHT == {}


def provider(model="unavailable"):
    return SimpleNamespace(provider_id="shared", model_name=model)


def fail(model=None, error=None):
    error = error or httpx.ConnectError("unavailable")
    with pytest.raises(type(error)):
        with admission.model_call_slot(model or provider()):
            raise error


def assert_open(model=None):
    with pytest.raises(admission.ModelCircuitOpenError):
        with admission.model_call_slot(model or provider()):
            pytest.fail("An open model circuit must refuse before provider I/O")


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout, TimeoutError])
def test_transport_failures_open_only_the_same_model(error_type):
    for _ in range(2):
        fail(error=error_type("transport failed"))
    assert_open()
    with admission.model_call_slot(provider("available")):
        pass
    assert_open()


def test_request_model_and_actor_are_independent_buckets():
    raw = SimpleNamespace(provider_id="shared")
    with admission.model_rate_limit_scope({"tenant_id": "t1", "actor_id": "a1"}):
        for _ in range(2):
            with pytest.raises(TimeoutError):
                with admission.model_call_slot(raw, model="namespace/model"):
                    raise TimeoutError()
        with admission.model_call_slot(raw, model="namespace_model"):
            pass
        with pytest.raises(admission.ModelCircuitOpenError):
            with admission.model_call_slot(raw, model="namespace/model"):
                pass
    with admission.model_rate_limit_scope({"tenant_id": "t1", "actor_id": "a2"}):
        with admission.model_call_slot(raw, model="namespace/model"):
            pass


@pytest.mark.parametrize("error", [asyncio.CancelledError(), admission.ModelRateLimitError(1)])
def test_cancel_and_local_denial_preserve_prior_provider_failures(error):
    fail(error=TimeoutError())
    fail(error=error)
    fail(error=TimeoutError())
    assert_open()


@pytest.mark.parametrize("exception_type", [StarletteHTTPException, FastAPIHTTPException])
@pytest.mark.parametrize("status_code", [408, 429, 503])
def test_local_http_refusal_preserves_prior_provider_failure_without_opening_circuit(
    exception_type, status_code
):
    fail(error=httpx.ConnectError("Earlier provider failure"))
    for _ in range(3):
        fail(error=exception_type(status_code, "Local task deadline, budget or storage refusal"))
    fail(error=httpx.ConnectError("Next provider failure"))
    assert_open()


@pytest.mark.parametrize("source", ["httpx", "openai"])
@pytest.mark.parametrize("status_code", [408, 429, 503])
def test_upstream_http_refusal_still_opens_the_model_circuit(source, status_code):
    request = httpx.Request("POST", "https://model.test/responses")
    response = httpx.Response(status_code, request=request)
    error = (
        httpx.HTTPStatusError("Upstream failure", request=request, response=response)
        if source == "httpx"
        else APIStatusError("Upstream failure", response=response, body=None)
    )
    for _ in range(2):
        fail(error=error)
    assert_open()


@pytest.mark.parametrize("error", [PermissionError(), ValueError(), httpx.PoolTimeout("")])
def test_local_faults_do_not_count_as_provider_outages(error):
    for _ in range(3):
        fail(error=error)
    with admission.model_call_slot(provider()):
        pass


def test_late_success_cannot_close_a_newer_open_circuit():
    with admission.model_call_slot(provider()):
        for _ in range(2):
            fail(error=TimeoutError())
        assert_open()
    assert_open()


def test_old_failure_cannot_reopen_a_recovered_circuit(gates):
    with pytest.raises(TimeoutError):
        with admission.model_call_slot(provider()):
            for _ in range(2):
                fail(error=TimeoutError())
            gates[0] += 11
            with admission.model_call_slot(provider()):
                pass
            raise TimeoutError("Older request ended after the successful probe")
    fail(error=TimeoutError())
    with admission.model_call_slot(provider()):
        pass


def test_single_half_open_probe_and_cancel_preserve_the_open_circuit(gates):
    for _ in range(2):
        fail(error=TimeoutError())
    gates[0] += 11
    with pytest.raises(asyncio.CancelledError):
        with admission.model_call_slot(provider()):
            assert_open()
            raise asyncio.CancelledError()
    # A cancelled probe grants no proof of recovery. Another probe may run,
    # while overlapping arrivals must still be excluded.
    with admission.model_call_slot(provider()):
        assert_open()
    with admission.model_call_slot(provider()):
        with admission.model_call_slot(provider()):
            pass


def test_slow_model_cannot_take_all_global_slots():
    with admission.model_call_slot(provider()):
        with admission.model_call_slot(provider()):
            with pytest.raises(admission.ModelConcurrencyLimitError):
                with admission.model_call_slot(provider()):
                    pass
            with admission.model_call_slot(provider("available")):
                pass


def test_route_capacity_is_shared_across_actors_without_blocking_other_models():
    with admission.model_rate_limit_scope({"actor_id": "a1"}):
        with admission.model_call_slot(provider()):
            with admission.model_rate_limit_scope({"actor_id": "a2"}):
                with admission.model_call_slot(provider()):
                    with admission.model_rate_limit_scope({"actor_id": "a3"}):
                        with pytest.raises(admission.ModelConcurrencyLimitError):
                            with admission.model_call_slot(provider()):
                                pass
                        with admission.model_call_slot(provider("healthy")):
                            pass


def test_concurrent_half_open_arrivals_have_one_probe(gates):
    for _ in range(2):
        fail(error=TimeoutError())
    gates[0] += 11
    start, release, refused = Barrier(6), Event(), Event()
    lock, refusals = Lock(), []

    def attempt():
        start.wait(timeout=2)
        try:
            with admission.model_call_slot(provider()):
                assert release.wait(timeout=2)
                return "probe"
        except admission.ModelCircuitOpenError:
            with lock:
                refusals.append(True)
                if len(refusals) == 5:
                    refused.set()
            return "refused"

    with ThreadPoolExecutor(max_workers=6) as workers:
        pending = [workers.submit(attempt) for _ in range(6)]
        try:
            assert refused.wait(timeout=2)
        finally:
            release.set()
        results = [future.result(timeout=2) for future in pending]
    assert results.count("probe") == 1 and results.count("refused") == 5


@pytest.mark.asyncio
async def test_rate_limited_provider_uses_request_model_for_streams_and_completions(monkeypatch):
    monkeypatch.setattr(admission, "admit_model_call", lambda *args, **kwargs: None)

    class Raw:
        provider_id = "shared"

        async def chat_completion(self, messages, **kwargs):
            raise httpx.ConnectTimeout("not connected")

        async def stream_chat_completion(self, messages, **kwargs):
            yield "available"

    wrapped = admission.rate_limit_provider(Raw())
    for _ in range(2):
        with pytest.raises(httpx.ConnectTimeout):
            await wrapped.chat_completion([], model="unavailable")
    with pytest.raises(admission.ModelCircuitOpenError):
        await wrapped.chat_completion([], model="unavailable")
    assert [item async for item in wrapped.stream_chat_completion([], model="available")] == [
        "available"
    ]


def test_admission_preserves_existing_instrumentation():
    from app.infrastructure.llm.instrumented_provider import InstrumentedProvider, wrap_provider

    traced = InstrumentedProvider(provider())
    wrapped = admission.rate_limit_provider(traced)
    assert wrapped._xcagi_instrumented
    assert wrap_provider(wrapped) is wrapped
    assert admission.rate_limit_provider(wrapped) is wrapped


def test_modstore_endpoint_changes_do_not_inherit_another_gate():
    def selected(endpoint):
        return SimpleNamespace(
            provider_id="modstore",
            _adapter=SimpleNamespace(platform_url=endpoint, model_name="same-model", user_id=71),
        )

    unavailable = selected("https://unavailable.test")
    for _ in range(2):
        fail(unavailable, TimeoutError())
    assert_open(unavailable)
    with admission.model_call_slot(selected("https://available.test")):
        with admission.model_call_slot(selected("https://available.test")):
            with admission.model_call_slot(selected("https://independent.test")):
                pass
    assert_open(unavailable)


@pytest.mark.parametrize("market_facade", [False, True])
def test_scoped_sdk_endpoint_isolated_without_reading_credentials(market_facade):
    from app.infrastructure.llm.client import llm_client_scope
    from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider

    class SelectedClient:
        def __init__(self, endpoint):
            if market_facade:
                self.is_modstore_openai_compatible = True
                self.adapter = SimpleNamespace(platform_url=endpoint, model_name="same-model")
            else:
                self.base_url = httpx.URL(endpoint)

        @property
        def api_key(self):
            pytest.fail("Circuit identity must not read credentials")

    raw = OpenAISdkProvider()
    first, second = (
        SelectedClient("https://unavailable.test"),
        SelectedClient("https://available.test"),
    )
    with llm_client_scope(first, "same-model"):
        for _ in range(2):
            fail(raw, TimeoutError())
        assert_open(raw)
    with llm_client_scope(second, "same-model"):
        with admission.model_call_slot(raw):
            pass
    with llm_client_scope(first, "same-model"):
        assert_open(raw)


@pytest.mark.parametrize("model", [None, "explicit-model"])
def test_route_observation_never_resolves_a_lazy_client(model):
    from app.infrastructure.llm.client import _scoped_client, llm_client_factory_scope
    from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider

    def forbidden():
        pytest.fail("The admission key must not instantiate a lazy client")

    with llm_client_factory_scope(forbidden):
        with admission.model_call_slot(OpenAISdkProvider(), model=model):
            assert _scoped_client.get() == (forbidden, None)
