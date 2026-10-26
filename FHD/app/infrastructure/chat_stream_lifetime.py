"""Request-owned read-stream cancellation; never rolls back or retries tools."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import queue
import threading
from contextlib import contextmanager


class StreamStopped(Exception):
    pass


class StreamObservationTimeout(TimeoutError):
    """The observer deadline expired; execution outcome is not a confirmed failure."""


class StreamReceiptPersistenceError(StreamObservationTimeout):
    """A returned tool result could not be saved; never execute the tool again."""

    status_code = 503
    reason = "tool_receipt_persistence_failed"


class StreamLifetime:
    def __init__(self):
        self.stopped = threading.Event()
        self._lock = threading.Lock()
        self._reads = {}
        self._workers = 0
        self._observers = []
        self._tool_observers = []
        self._tool_sequence = 0
        self._tool_pending = []
        self._receipt_lock = threading.Lock()
        self._notify_lock = threading.Lock()
        self.reason = "consumer_closed"

    def check(self):
        if self.stopped.is_set():
            if self.reason == "tool_receipt_persistence_failed":
                raise StreamReceiptPersistenceError("工具回执尚未保存，请核对原调用，勿重复提交")
            raise StreamStopped()

    def cancel(self, reason="consumer_closed"):
        with self._lock:
            first = not self.stopped.is_set()
            self.stopped.set()
            if first:
                self.reason = reason
            reads = [read for read, _ in self._reads.values() if not inspect.isgenerator(read)]
            self._reads = {
                key: value for key, value in self._reads.items() if inspect.isgenerator(value[0])
            }
        for read in reads:
            # Python generators remain owned by their producer; close only the
            # underlying request-owned HTTP response from another thread.
            threading.Thread(target=self._close, args=(read,), daemon=True).start()

        if first:
            threading.Thread(target=self._notify, daemon=True).start()

    def observe(self, callback):
        with self._lock:
            self._observers.append(callback)
        if self.stopped.is_set():
            self._notify()

    def observe_tools(self, callback):
        with self._lock:
            self._tool_observers.append(callback)

    def publish_tool_record(self, record):
        with self._lock:
            self._tool_sequence += 1
            sequence = self._tool_sequence
            callbacks = list(self._tool_observers)
        with self._receipt_lock:
            self._tool_pending.extend((callback, sequence, record) for callback in callbacks)
        try:
            self._flush_tool_records()
        except StreamReceiptPersistenceError:
            self.cancel("tool_receipt_persistence_failed")
            raise

    def _flush_tool_records(self):
        with self._receipt_lock:
            while self._tool_pending:
                callback, sequence, record = self._tool_pending[0]
                for attempt in range(2):
                    try:
                        callback(sequence=sequence, record=record)
                        break
                    except Exception as exc:  # noqa: BLE001 - retry only receipt storage, never tool execution
                        if attempt:
                            raise StreamReceiptPersistenceError(
                                "工具回执尚未保存，请核对原调用"
                            ) from exc
                self._tool_pending.pop(0)

    def worker_started(self):
        with self._lock:
            self._workers += 1

    def worker_finished(self):
        try:
            self._flush_tool_records()
        except StreamReceiptPersistenceError:
            self.cancel("tool_receipt_persistence_failed")
            logging.getLogger(__name__).exception("stream tool receipt remains unsaved")
        with self._lock:
            self._workers -= 1
        if self.stopped.is_set():
            self._notify()

    def _notify(self):
        # Serialize store writes and read current state inside this lock so a
        # delayed disconnect notification cannot overwrite settled workers.
        with self._notify_lock:
            with self._lock:
                pending, callbacks = self._workers > 0, list(self._observers)
            for callback in callbacks:
                try:
                    callback(pending=pending, reason=self.reason)
                except Exception:  # noqa: BLE001 - observation failure must not retain live producers
                    logging.getLogger(__name__).exception("stream interruption persistence failed")

    @staticmethod
    def _close(read):
        try:
            close = getattr(read, "close", None)
            if close:
                close()
        except Exception:  # noqa: BLE001 - best-effort read cleanup cannot replace the original outcome
            pass

    @contextmanager
    def reading(self, read):
        with self._lock:
            stopped = self.stopped.is_set()
            if not stopped:
                _, leases = self._reads.get(id(read), (read, 0))
                self._reads[id(read)] = (read, leases + 1)
        if stopped:
            self._close(read)
            self.check()
        try:
            self.check()
            yield read
        finally:
            with self._lock:
                registered = self._reads.get(id(read))
                owned = registered is not None and registered[1] == 1
                if owned:
                    del self._reads[id(read)]
                elif registered is not None:
                    self._reads[id(read)] = (read, registered[1] - 1)
            if owned:
                self._close(read)


current_lifetime: contextvars.ContextVar[StreamLifetime | None] = contextvars.ContextVar(
    "chat_stream_lifetime", default=None
)


def check_stream_active():
    lifetime = current_lifetime.get()
    if lifetime is not None:
        lifetime.check()


@contextmanager
def owned_model_read(read):
    lifetime = current_lifetime.get() or StreamLifetime()
    with lifetime.reading(read):
        yield read


def watch_stream_interruption(callback):
    lifetime = current_lifetime.get()
    if lifetime is not None:
        lifetime.observe(callback)


def watch_stream_tool_records(callback):
    lifetime = current_lifetime.get()
    if lifetime is not None:
        lifetime.observe_tools(callback)


def publish_stream_tool_record(record):
    lifetime = current_lifetime.get()
    if lifetime is not None:
        lifetime.publish_tool_record(record)


class StreamWorker:
    """Bounded bridge. Only the producer thread owns iterator.close()."""

    END = object()

    def __init__(self, factory, *, capacity=128):
        self.queue = queue.Queue(maxsize=capacity)
        self.stopped = threading.Event()
        self.lifetime = current_lifetime.get()
        self.finished = threading.Event()
        self.thread = threading.Thread(
            target=contextvars.copy_context().run, args=(self._run, factory), daemon=True
        )
        if self.lifetime:
            self.lifetime.worker_started()
        self.thread.start()

    def _put(self, item):
        # Upstream shutdown may still produce a truthful terminal error. Only
        # consumer closure forbids delivery; it is separate from read shutdown.
        while not self.stopped.is_set():
            try:
                self.queue.put(item, timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def _run(self, factory):
        iterator = None
        try:
            check_stream_active()
            iterator = iter(factory())
            while not self.stopped.is_set():
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                if not self._put(item):
                    break
        except Exception as exc:  # noqa: BLE001 - producer boundary forwards failure to its consumer
            self._put(exc)
        finally:
            if iterator is not None:
                StreamLifetime._close(iterator)
            self._put(self.END)
            if self.lifetime:
                self.lifetime.worker_finished()
            self.finished.set()

    def close(self):
        self.stopped.set()

    async def receive(self):
        # No executor job or pending run_coroutine_threadsafe put survives abort.
        while True:
            check_stream_active()
            try:
                return self.queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
