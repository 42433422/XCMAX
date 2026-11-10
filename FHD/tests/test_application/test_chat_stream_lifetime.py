"""Isolated source-level lifecycle regressions: no app startup or provider I/O."""

import asyncio
import importlib
import json
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


def bind_entrypoint_modules(monkeypatch):
    global _entrypoint_patches, _entrypoint_modules
    _entrypoint_patches = monkeypatch
    _entrypoint_modules = {
        name: importlib.import_module(name)
        for name in (
            "app.fastapi_routes.xcagi_compat_chat_helpers",
            "app.application.market_llm.streaming",
            "app.application.agent_orchestrator.chat_trace",
        )
    }


@pytest.fixture(autouse=True)
def source_bindings(monkeypatch):
    bind_entrypoint_modules(monkeypatch)
    yield
    global _entrypoint_patches, _entrypoint_modules
    _entrypoint_patches = None
    _entrypoint_modules = {}


def extract(path, name, namespace):
    """Load the real entrypoint and bind only the test's explicit dependency seams."""
    module = _entrypoint_modules[Path(path).with_suffix("").as_posix().replace("/", ".")]
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

    monkeypatch.setattr(chat_trace, "mark_chat_stream_interrupted", persist)
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
    request = NS(messages=[], extra={}, payload=lambda *a, **k: {})
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
