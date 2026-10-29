"""Isolated source-level lifecycle regressions: no app startup or provider I/O."""

import asyncio
import importlib
import json
import queue
import sys
import threading
import time
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
life = importlib.import_module("app.infrastructure.chat_stream_lifetime")
_entrypoint_patches = None
_entrypoint_modules = {}


@pytest.fixture(autouse=True)
def source_bindings(monkeypatch):
    global _entrypoint_patches

    for path in (
        "app.fastapi_routes.xcagi_compat_chat_helpers",
        "app.fastapi_routes.xcagi_compat_chat_stream",
        "app.legacy.chat.legacy_chat_runtime",
        "app.legacy.chat.legacy_chat_adapter",
        "app.legacy.market_llm.openai_compat",
        "app.application.market_llm.streaming",
        "app.domain.shared_services.conversation.modstore_adapter",
        "app.application.agent_orchestrator.chat_trace",
    ):
        _entrypoint_modules[path] = importlib.import_module(path)
    _entrypoint_patches = monkeypatch
    yield
    _entrypoint_patches = None


def extract(path, name, namespace):
    """Load the real entrypoint and bind only the test's explicit dependency seams."""
    module = _entrypoint_modules[str(Path(path).with_suffix("")).replace("/", ".")]
    for key, value in namespace.items():
        _entrypoint_patches.setattr(module, key, value, raising=False)
    namespace[name] = getattr(module, name)
    return namespace[name]


@pytest.fixture
def lifetime():
    return life.StreamLifetime()


@contextmanager
def bound_lifetime(lifetime):
    token = life.current_lifetime.set(lifetime)
    try:
        yield
    finally:
        life.current_lifetime.reset(token)


def bridge(factory):
    return extract(
        "app/fastapi_routes/xcagi_compat_chat_helpers.py",
        "_xcagi_planner_stream_bytes_async",
        {
            "_xcagi_planner_stream_bytes": factory,
            "_sse_event_line": lambda value: json.dumps(value).encode(),
        },
    )(None, None, ai_tier="synthetic")


async def wait(event):
    assert await asyncio.to_thread(event.wait, 2)


@pytest.mark.asyncio
async def test_normal_last_piece_and_exception():
    assert [x async for x in bridge(lambda *a, **k: iter([b"first", b"last"]))] == [
        b"first",
        b"last",
    ]

    def failed(*a, **k):
        yield b"first"
        raise ValueError("synthetic producer failure")

    result = [x async for x in bridge(failed)]
    assert result[0] == b"first"
    assert json.loads(result[1]) == {"type": "error", "message": "synthetic producer failure"}


@pytest.mark.asyncio
async def test_timeout_does_not_cancel_consumer_between_stream_pieces(monkeypatch):
    helper = _entrypoint_modules["app.fastapi_routes.xcagi_compat_chat_helpers"]
    monkeypatch.setattr(helper, "_xcagi_chat_timeout_seconds", lambda: 0.1)
    stream = bridge(lambda *a, **k: iter([b"first", b"last"]))
    assert await anext(stream) == b"first"
    await asyncio.sleep(0.15)
    assert json.loads(await anext(stream))["status_code"] == 504
    await stream.aclose()


@pytest.mark.parametrize("same_id", [False, True])
def test_stream_timeout_identity_cannot_be_rebound_to_another_run(lifetime, same_id):
    original = NS(run_id="first-run")
    lifetime.observe(lambda **state: None, run_snapshot=original)
    with pytest.raises(ValueError, match="different run"):
        lifetime.observe(
            lambda **state: None,
            run_snapshot=NS(run_id="first-run" if same_id else "other-run"),
        )
    assert lifetime.run_snapshot is original


@pytest.mark.asyncio
async def test_cancel_blocked_read_closes_read_and_generator_on_owner_thread():
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    thread_ids, close_calls = [], []

    class Read:
        def close(self):
            close_calls.append(1)
            released.set()

    def producer(*a, **k):
        thread_ids.append(threading.get_ident())
        try:
            with life.owned_model_read(Read()):
                yield b"first"
                entered.set()
                assert released.wait(2)
                life.check_stream_active()
                yield b"must-not-arrive"
        finally:
            thread_ids.append(threading.get_ident())
            finished.set()

    stream = bridge(producer)
    assert await anext(stream) == b"first"
    await wait(entered)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.02)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await stream.aclose()
    await wait(finished)
    assert close_calls == [1]
    assert thread_ids[0] == thread_ids[1]


@pytest.mark.asyncio
async def test_cancel_full_queue_never_replays_side_effect():
    finished, progressed = threading.Event(), threading.Event()
    calls = []

    def producer(*a, **k):
        try:
            calls.append("business already executed")
            for index in range(1000):
                if index > 128:
                    progressed.set()
                yield str(index).encode()
        finally:
            finished.set()

    stream = bridge(producer)
    await anext(stream)
    await wait(progressed)
    await stream.aclose()
    await wait(finished)
    assert calls == ["business already executed"]


@pytest.mark.asyncio
async def test_cancel_cannot_pretend_to_stop_noninterruptible_work():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    late = []

    def producer(*a, **k):
        try:
            yield b"first"
            entered.set()
            assert release.wait(2)
            late.append("existing operation completed")
            yield b"late"
        finally:
            finished.set()

    stream = bridge(producer)
    await anext(stream)
    await wait(entered)
    await stream.aclose()
    assert not finished.is_set()  # Caller unblocked, underlying operation not falsely cancelled.
    release.set()
    await wait(finished)
    assert late == ["existing operation completed"]


def test_cancel_before_worker_start_and_read_registration_race(lifetime):
    lifetime.cancel()
    calls = []
    with bound_lifetime(lifetime):
        worker = life.StreamWorker(lambda: calls.append("unexpected factory"))
        assert worker.finished.wait(1)
        with pytest.raises(life.StreamStopped):
            with life.owned_model_read(NS(close=lambda: calls.append("read closed"))):
                pass
    assert calls == ["read closed"]


@pytest.mark.parametrize("fail", [False, True])
def test_read_closed_exactly_once_on_normal_or_exception(fail, lifetime):
    calls = []
    try:
        with lifetime.reading(NS(close=lambda: calls.append(1))):
            if fail:
                raise ValueError("failure")
    except ValueError:
        pass
    lifetime.cancel()
    assert calls == [1]


def guarded(factory, monkeypatch, timeout=0.15):
    monkeypatch.setitem(
        sys.modules, "app.infrastructure.tenant_scope", NS(tenant_scope=lambda _: nullcontext())
    )
    return extract(
        "app/fastapi_routes/xcagi_compat_chat_helpers.py",
        "_xcagi_guarded_planner_stream_events",
        {
            "chat_stream_sse_events": factory,
            "time": time,
            "queue": queue,
            "MODEL_STREAM_ACCEPTED_EVENT": {"type": "token", "text": "accepted"},
            "_xcagi_chat_timeout_seconds": lambda: timeout,
            "_xcagi_stream_first_token_timeout_seconds": lambda: timeout,
            "_xcagi_stream_idle_notice_seconds": lambda: 0.05,
            "_xcagi_chat_http_exc": lambda e: NS(detail=str(e), status_code=500),
        },
    )(
        NS(message="synthetic", system_prompt=None, db_write_token=None),
        runtime_context={},
        workspace_root="",
        client=None,
    )


def test_guard_timeout_closes_owned_upstream(monkeypatch):
    released, finished = threading.Event(), threading.Event()

    def events(*a, **k):
        try:
            with life.owned_model_read(NS(close=released.set)):
                assert released.wait(2)
                yield {"type": "token", "text": "late"}
        finally:
            finished.set()

    stream = guarded(events, monkeypatch)
    with pytest.raises(TimeoutError):
        list(stream)
    assert finished.wait(1)


def test_guard_normal_completion_and_error(monkeypatch):
    def events(*a, **k):
        yield {"type": "token", "text": "last"}

    assert list(guarded(events, monkeypatch))[-1]["text"] == "last"

    def error(*a, **k):
        raise ValueError("guard failed")
        yield

    assert list(guarded(error, monkeypatch))[-1] == {
        "type": "error",
        "message": "guard failed",
        "status_code": 500,
    }


@pytest.mark.asyncio
async def test_two_bridges_cancel_propagates_to_read(monkeypatch):
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()

    def events(*a, **k):
        try:
            with life.owned_model_read(NS(close=released.set)):
                entered.set()
                assert released.wait(2)
                yield {"type": "token", "text": "late"}
        finally:
            finished.set()

    stream = bridge(lambda *a, **k: guarded(events, monkeypatch, timeout=3))
    assert (await anext(stream))["text"] == "accepted"
    await wait(entered)
    await stream.aclose()
    await wait(finished)


@pytest.mark.asyncio
@pytest.mark.parametrize("before_planner", [False, True])
async def test_two_bridge_timeout_delivers_terminal_error(monkeypatch, before_planner):
    released = threading.Event()

    def events(*a, **k):
        with life.owned_model_read(NS(close=released.set)):
            assert released.wait(2)
            yield {"type": "token", "text": "late"}

    helper = _entrypoint_modules["app.fastapi_routes.xcagi_compat_chat_helpers"]
    monkeypatch.setattr(
        helper, "_xcagi_chat_timeout_seconds", lambda: 3 if before_planner else 0.15
    )
    monkeypatch.setattr(helper, "_xcagi_stream_first_token_timeout_seconds", lambda: 0.05)
    factory = events if before_planner else lambda *a, **k: guarded(events, monkeypatch)
    result = await asyncio.wait_for(_collect(bridge(factory)), 1)
    assert json.loads(result[-1])["type"] == "error"
    await wait(released)
    assert released.is_set()
    if before_planner:
        assert "勿重复提交" in json.loads(result[-1])["message"]


async def _collect(stream):
    return [item async for item in stream]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["storage", "programming", "timeout"])
async def test_outer_timeout_storage_failure_stays_unknown_and_returns_without_replay(
    monkeypatch, caplog, failure
):
    from app.application.agent_orchestrator import chat_trace

    release, finished, storage_finished = (threading.Event() for _ in range(3))
    helper = _entrypoint_modules["app.fastapi_routes.xcagi_compat_chat_helpers"]
    monkeypatch.setattr(helper, "_xcagi_chat_timeout_seconds", lambda: 0.03)
    monkeypatch.setattr(helper, "_STREAM_SAFETY_STORE_TIMEOUT", 0.03)
    effects, stores = [], []

    def persist(*args, **kwargs):
        stores.append(kwargs)
        try:
            if failure == "timeout":
                assert release.wait(2)
            else:
                raise (OSError if failure == "storage" else TypeError)("PRIVATE_DRIVER_DETAIL")
        finally:
            storage_finished.set()

    def producer(*args, **kwargs):
        life.watch_stream_interruption(lambda **state: None, run_snapshot=NS(run_id="owned-run"))
        try:
            effects.append("committed-once")
            assert release.wait(2)
            yield b"late"
        finally:
            finished.set()

    monkeypatch.setattr(chat_trace, "mark_legacy_chat_stream_interrupted", persist)
    try:
        chunks = await asyncio.wait_for(_collect(bridge(producer)), 1)
        error = json.loads(chunks[-1])
        assert error["status_code"] == 503 and error["run_id"] == "owned-run"
        assert error["execution_outcome"] == "unknown" and error["requires_reconciliation"] is True
        assert "PRIVATE_DRIVER_DETAIL" not in str(error) + caplog.text
        assert effects == ["committed-once"] and len(stores) == 1
        assert not finished.is_set()
    finally:
        release.set()
        await wait(finished)
        await wait(storage_finished)


@pytest.mark.parametrize("cancel_when", ["before_tool", "during_tool", "none"])
def test_real_runtime_tool_boundary_is_not_replayed(cancel_when, lifetime):
    calls, closes = [], []
    chunk = NS(
        choices=[
            NS(
                finish_reason="tool_calls",
                delta=NS(
                    content=None,
                    tool_calls=[
                        NS(index=0, id="tool-1", function=NS(name="business_write", arguments="{}"))
                    ],
                ),
            )
        ]
    )

    class Read:
        def __iter__(self):
            return iter([chunk])

        def close(self):
            closes.append("read")

    def create(**kwargs):
        calls.append("model")
        return Read()

    def append(*args, **kwargs):
        calls.append("business committed")
        if cancel_when == "during_tool":
            lifetime.cancel()
        return {"requires_token": True}

    facade = NS(
        reset_planner_tool_dedup_state=lambda: None,
        _tool_stream_call_label=lambda *a: "write",
        _slow_tool_wait_message=lambda *a: "",
        append_tool_messages=append,
    )
    runtime = extract(
        "app/legacy/chat/legacy_chat_runtime.py",
        "chat_stream_text",
        {
            "_facade": lambda: facade,
            "check_stream_active": life.check_stream_active,
            "owned_model_read": life.owned_model_read,
            "SimpleNamespace": NS,
            "_prepare_chat": lambda *a: (
                [],
                False,
                NS(chat=NS(completions=NS(create=create))),
                "fake",
                [],
                None,
                False,
            ),
            "_format_tool_calls": lambda t: [],
            "llm_client_scope": lambda *a: nullcontext(),
        },
    )
    with bound_lifetime(lifetime), closing(runtime("synthetic")) as stream:
        assert "正在调用工具" in next(stream)
        if cancel_when == "before_tool":
            lifetime.cancel()
        if cancel_when == "none":
            assert list(stream)[-1]["_planner_sse"] == "requires_token"
        else:
            with pytest.raises(life.StreamStopped):
                list(stream)
    assert calls == (["model"] if cancel_when == "before_tool" else ["model", "business committed"])
    assert closes == ["read"]


def test_guard_full_queue_close_does_not_close_executing_generator(monkeypatch):
    queued, finished = threading.Event(), threading.Event()
    owners = []

    def events(*a, **k):
        owners.append(threading.get_ident())
        try:
            for index in range(1000):
                if index == 128:
                    queued.set()
                yield {"type": "token", "text": str(index)}
        finally:
            owners.append(threading.get_ident())
            finished.set()

    stream = guarded(events, monkeypatch, timeout=3)
    assert next(stream)["text"] == "accepted"
    assert queued.wait(1)
    stream.close()
    assert finished.wait(1)
    assert owners[0] == owners[1]


@pytest.mark.parametrize("attempt", range(25))
def test_cancel_and_normal_read_close_race_is_exactly_once(lifetime, attempt):
    calls = []
    rendezvous = threading.Barrier(2)
    closed = threading.Event()

    def close():
        calls.append(1)
        closed.set()

    def cancel():
        rendezvous.wait()
        lifetime.cancel()

    with lifetime.reading(NS(close=close)):
        thread = threading.Thread(target=cancel)
        thread.start()
        rendezvous.wait()
    thread.join(1)
    assert closed.wait(1)
    assert calls == [1]


@pytest.mark.asyncio
async def test_blocked_stream_create_registers_and_closes_after_cancel():
    entered, release, closed, finished = (threading.Event() for _ in range(4))

    def producer(*a, **k):
        try:
            yield b"accepted"
            entered.set()  # Simulate a provider create() that cannot be interrupted.
            assert release.wait(2)
            with life.owned_model_read(NS(close=closed.set)):
                pytest.fail("cancelled create must not start consuming its returned stream")
                yield b"late"
        finally:
            finished.set()

    stream = bridge(producer)
    await anext(stream)
    await wait(entered)
    await stream.aclose()
    assert not closed.is_set()
    release.set()
    await wait(finished)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_python_generator_read_is_closed_only_on_owner_thread():
    entered, release, closed, finished = (threading.Event() for _ in range(4))
    owners = []

    def read():
        owners.append(threading.get_ident())
        try:
            entered.set()
            assert release.wait(2)
            yield b"late"
        finally:
            owners.append(threading.get_ident())
            closed.set()

    def producer(*a, **k):
        try:
            yield b"first"
            with life.owned_model_read(read()) as stream:
                for item in stream:
                    life.check_stream_active()
                    yield item
        finally:
            finished.set()

    stream = bridge(producer)
    await anext(stream)
    await wait(entered)
    await stream.aclose()
    assert not closed.is_set()
    release.set()
    await wait(finished)
    assert closed.is_set()
    assert owners[0] == owners[1]


@pytest.mark.asyncio
async def test_real_sync_wrapper_catches_guard_timeout_and_delivers_error(monkeypatch):
    released = threading.Event()

    def events(*a, **k):
        with life.owned_model_read(NS(close=released.set)):
            assert released.wait(2)
            yield {"type": "token", "text": "late"}

    stubs = {
        "app.application": NS(get_ai_chat_app_service=lambda: NS(_pending_workflows={})),
        "app.application.ai_chat.workflow_session": NS(CANCEL_WORDS=set(), CONFIRM_WORDS=set()),
        "app.application.normal_chat_dispatch": NS(route_normal_mode_message=lambda _: {}),
        "app.application.workflow.planner": NS(_looks_like_business_db_write=lambda *a: False),
        "app.domain.conversation.services.chat_tool_intent": NS(
            references_recent_business_record=lambda _: False
        ),
        "app.application.agent_task_context": NS(
            scoped_conversation_user_id=lambda *a: "synthetic"
        ),
        "app.infrastructure.tenant_scope": NS(tenant_scope=lambda _: nullcontext()),
        "app.domain.app_pure.chat_business_safety": NS(
            try_handle_business_chat_action=lambda *a, **k: None
        ),
    }
    for name, stub in stubs.items():
        monkeypatch.setitem(sys.modules, name, stub)
    facade = NS(
        _merge_runtime_context_with_message_paths=lambda *a: ({}, None),
        _runtime_context_with_authenticated_actor=lambda *a: {},
        runtime_context_with_tier=lambda *a: {},
        _ensure_chat_db_read_authorized=lambda *a, **k: (True, None),
        _message_requires_db_read_token=lambda _: False,
        planner_workflow_interrupt_reply=lambda _: None,
        _ensure_vector_index_if_needed=lambda *a: None,
        os=NS(environ={}, getcwd=lambda: ""),
        create_modstore_openai_client_from_request=lambda _: object(),
        start_legacy_chat_run=lambda **k: NS(run_id="synthetic-run"),
        finalize_legacy_chat_run=lambda *a, **k: None,
        _sse_event_line=lambda value: json.dumps(value).encode(),
        _sse_payload_with_run_id=lambda value, run_id: {**value, "run_id": run_id},
        _xcagi_guarded_planner_stream_events=lambda *a, **k: guarded(events, monkeypatch),
        _xcagi_chat_http_exc=lambda error: NS(detail=str(error), status_code=504),
        RECOVERABLE_ERRORS=(Exception,),
    )
    runtime = extract(
        "app/fastapi_routes/xcagi_compat_chat_stream.py",
        "_xcagi_planner_stream_bytes",
        {
            "_facade": lambda: facade,
            "watch_stream_interruption": life.watch_stream_interruption,
            "watch_stream_tool_records": life.watch_stream_tool_records,
            "mark_legacy_chat_stream_interrupted": lambda *a, **k: None,
            "record_legacy_stream_tool_receipt": lambda *a, **k: None,
            "StreamObservationTimeout": life.StreamObservationTimeout,
            "_classify_and_submit_client_issue": lambda *a: None,
            "_client_issue_reply": lambda _: None,
        },
    )
    body = NS(
        mode="", context={}, message="synthetic", user_id="fake", source="test", db_read_token=None
    )
    result = await asyncio.wait_for(
        _collect(bridge(lambda *a, **k: runtime(None, body, ai_tier="fake"))), 2
    )
    assert json.loads(result[-1])["type"] == "error"
    assert json.loads(result[-1])["status_code"] == 504
    assert json.loads(result[-1])["run_id"] == "synthetic-run"


def test_nested_and_concurrent_owned_reads_all_close_once(lifetime):
    calls = []
    reads = [NS(close=lambda index=index: calls.append(index)) for index in range(3)]
    with (
        lifetime.reading(reads[0]),
        lifetime.reading(reads[0]),
        lifetime.reading(reads[1]),
        lifetime.reading(reads[2]),
    ):
        lifetime.cancel()
    deadline = time.monotonic() + 1
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sorted(calls) == [0, 1, 2]


@pytest.mark.asyncio
async def test_real_modstore_generator_http_response_interrupts_blocked_mocktransport(monkeypatch):
    import httpx

    from app.domain.shared_services.conversation.modstore_adapter import _ModstoreOpenAICompletions

    entered, closed, finished = (threading.Event() for _ in range(3))
    requests, close_calls = [], []

    class BlockingResponse(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            assert closed.wait(2)
            return
            yield b"unused"

        def close(self):
            close_calls.append(1)
            closed.set()

    def handle(request):
        requests.append(str(request.url))
        return httpx.Response(200, stream=BlockingResponse())

    native = extract(
        "app/application/market_llm/streaming.py",
        "stream_sync",
        {
            "httpx": httpx,
            "check_stream_active": life.check_stream_active,
            "owned_model_read": life.owned_model_read,
        },
    )
    ports = NS(
        candidates=lambda *a: [("fake", "fake")],
        prepare_sync=lambda messages, *a: messages,
        sync_client=lambda **k: httpx.Client(transport=httpx.MockTransport(handle), **k),
        connect_timeout=lambda: 1,
        status_code=lambda response, default: response.status_code,
        sync_payloads=lambda response: response.iter_lines(),
    )
    connection = NS(platform_url="https://synthetic.invalid", timeout=1, headers=lambda: {})
    request = NS(messages=[], payload=lambda *a, **k: {})
    adapter = NS(
        chat_completion_sync=lambda **k: pytest.fail("must not replay completion"),
        stream_chat_completion_sync=lambda **k: native(
            connection, ("fake", "fake"), request, ports
        ),
        model_name="fake",
    )
    monkeypatch.setenv("XCAGI_MODSTORE_USE_NATIVE_STREAM", "1")

    def producer(*a, **k):
        try:
            source = _ModstoreOpenAICompletions(adapter).create(messages=[], stream=True)
            with life.owned_model_read(source):
                yield from source
        finally:
            finished.set()

    stream = bridge(producer)
    await anext(stream)  # Actual adapter's role prelude, before HTTP response.
    await wait(entered)
    await stream.aclose()
    await wait(finished)
    assert closed.is_set()
    assert close_calls == [1]
    assert requests == ["https://synthetic.invalid/api/llm/chat/stream"]


def test_concurrent_owned_reads_cancel_all_without_shared_client_close(lifetime):
    registered = threading.Barrier(4)
    calls = []

    def reader(index):
        released = threading.Event()

        def close():
            calls.append(index)
            released.set()

        with lifetime.reading(NS(close=close)):
            registered.wait()
            assert released.wait(1)

    threads = [threading.Thread(target=reader, args=(index,)) for index in range(3)]
    for thread in threads:
        thread.start()
    registered.wait()
    lifetime.cancel()
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert sorted(calls) == [0, 1, 2]


def test_cancel_during_guard_queue_wait_does_not_translate_read_close_to_business_error(
    monkeypatch,
    lifetime,
):
    entered, release, settled = (threading.Event() for _ in range(3))
    seen = []
    waiting = threading.Event()
    original_queue = queue.Queue

    class ObservedQueue(original_queue):
        def get(self, *args, **kwargs):
            waiting.set()
            return super().get(*args, **kwargs)

    monkeypatch.setattr(life.queue, "Queue", ObservedQueue)

    def events(*a, **k):
        with life.owned_model_read(NS(close=release.set)):
            entered.set()
            assert release.wait(2)
            raise ValueError("synthetic HTTP read closed after disconnect")
            yield

    with bound_lifetime(lifetime):
        stream = guarded(events, monkeypatch, timeout=3)
        assert next(stream)["text"] == "accepted"

    def consume():
        try:
            seen.append(next(stream))
        except life.StreamStopped:
            seen.append("stopped")
        finally:
            stream.close()
            settled.set()

    consumer = threading.Thread(target=consume)
    consumer.start()
    assert entered.wait(1)
    assert waiting.wait(1)  # Pause exactly after the pre-read cancellation check.
    lifetime.cancel()
    assert settled.wait(1)
    consumer.join(1)
    assert seen == ["stopped"]
