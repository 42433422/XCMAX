"""RabbitMQ-backed :class:`~modstore_server.eventing.bus.NeuroBus` implementation.

Uses ``pika`` (synchronous) so that ``publish()`` remains compatible with the
existing synchronous ``NeuroBus`` interface.  A background daemon thread runs
``channel.start_consuming()`` to deliver inbound messages to in-process
subscribers.

Topology
--------
- **Exchange**: ``modstore.events`` (topic)
- **Queue**: ``modstore.events.{hostname}.{pid}`` (exclusive, auto-delete)
- **Routing key**: event name (e.g. ``payment.paid``)
- Wildcard subscribers (``*``) bind with routing key ``#``

Environment
-----------
- ``MODSTORE_RABBITMQ_URL`` — full AMQP URL, e.g.
  ``amqp://user:pass@host:5672/vhost``.  Falls back to
  ``amqp://modstore:modstore-rabbit@localhost:5672/`` when empty.

Graceful degradation
--------------------
If RabbitMQ is unreachable at init time the bus falls back to pure in-memory
dispatch (same as :class:`InMemoryNeuroBus`).  A periodic reconnection
attempt runs in the background; once the broker is available the bus
transparently switches to AMQP mode.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any

from modstore_server.eventing.bus import InMemoryNeuroBus
from modstore_server.eventing.events import DomainEvent

logger = logging.getLogger(__name__)

_EXCHANGE = "modstore.events"
_EXCHANGE_TYPE = "topic"
_QUEUE_PREFIX = "modstore.events"
_RECONNECT_INTERVAL = 10.0


def _default_amqp_url() -> str:
    raw = (os.environ.get("MODSTORE_RABBITMQ_URL") or "").strip()
    if raw:
        return raw
    user = (os.environ.get("RABBITMQ_USER") or "modstore").strip()
    password = (os.environ.get("RABBITMQ_PASSWORD") or "modstore-rabbit").strip()
    host = (os.environ.get("RABBITMQ_HOST") or "localhost").strip()
    port = (os.environ.get("RABBITMQ_PORT") or "5672").strip()
    vhost = (os.environ.get("RABBITMQ_VHOST") or "/").strip()
    if not vhost.startswith("/"):
        vhost = "/" + vhost
    return f"amqp://{user}:{password}@{host}:{port}{vhost}"


def _queue_name() -> str:
    hostname = socket.gethostname()[:48]
    pid = os.getpid()
    return f"{_QUEUE_PREFIX}.{hostname}.{pid}"


class RabbitMqNeuroBus(InMemoryNeuroBus):
    """In-process handlers + AMQP fan-out via RabbitMQ.

    ``publish()`` does two things:
    1. Dispatch to local in-process subscribers (inherited from
       :class:`InMemoryNeuroBus`).
    2. Publish the event to the ``modstore.events`` topic exchange so that
       *other* processes / workers receive it.

    Inbound messages from RabbitMQ are consumed on a daemon thread and
    dispatched to in-process subscribers — but only when the event originated
    from a *different* process (to avoid double-dispatch).
    """

    def __init__(self) -> None:
        super().__init__()
        self._amqp_url = _default_amqp_url()
        self._connection = None
        self._channel = None
        self._queue_name = _queue_name()
        self._consumer_tag: str | None = None
        self._consumer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected = False
        self._lock = threading.RLock()
        self._bindings: set[str] = set()
        self._local_producer_id = f"{socket.gethostname()}:{os.getpid()}"
        self._connect_and_setup()

    def _connect_and_setup(self) -> None:
        try:
            import pika
        except ImportError:
            logger.warning(
                "pika not installed; RabbitMqNeuroBus falling back to in-memory mode. "
                "Install with: pip install pika"
            )
            return

        try:
            params = pika.URLParameters(self._amqp_url)
            params.connection_attempts = 3
            params.retry_delay = 2
            params.blocked_connection_timeout = 300
            params.heartbeat = 600
            self._connection = pika.BlockingConnection(params)
            self._channel = self._connection.channel()
            self._channel.exchange_declare(
                exchange=_EXCHANGE,
                exchange_type=_EXCHANGE_TYPE,
                durable=True,
            )
            self._channel.queue_declare(
                queue=self._queue_name,
                exclusive=True,
                auto_delete=True,
            )
            self._connected = True
            logger.info(
                "RabbitMqNeuroBus connected to %s, queue=%s",
                self._amqp_url.split("@")[-1] if "@" in self._amqp_url else self._amqp_url,
                self._queue_name,
            )
            self._rebind_all()
            self._start_consumer()
        except Exception:
            logger.exception(
                "RabbitMqNeuroBus connection failed; falling back to in-memory mode. " "URL=%s",
                self._amqp_url.split("@")[-1] if "@" in self._amqp_url else "(unset)",
            )
            self._connected = False
            self._connection = None
            self._channel = None
            self._start_reconnector()

    def _rebind_all(self) -> None:
        if not self._channel or not self._connected:
            return
        for event_name in self._bindings:
            routing_key = "#" if event_name == "*" else event_name
            try:
                self._channel.queue_bind(
                    queue=self._queue_name,
                    exchange=_EXCHANGE,
                    routing_key=routing_key,
                )
            except Exception:
                logger.debug("queue_bind failed for %s during rebind", event_name, exc_info=True)

    def _start_consumer(self) -> None:
        if self._consumer_thread and self._consumer_thread.is_alive():
            return
        if not self._channel or not self._connected:
            return
        self._stop_event.clear()
        self._consumer_thread = threading.Thread(
            target=self._consume_loop,
            name="modstore-rabbitmq-consumer",
            daemon=True,
        )
        self._consumer_thread.start()

    def _consume_loop(self) -> None:
        if not self._channel:
            return
        try:
            self._consumer_tag = self._channel.basic_consume(
                queue=self._queue_name,
                on_message_callback=self._on_message,
                auto_ack=True,
            )
            while not self._stop_event.is_set():
                try:
                    self._connection.process_data_events(time_limit=1.0)
                except Exception:
                    if self._stop_event.is_set():
                        break
                    logger.debug("RabbitMQ consumer loop error, reconnecting", exc_info=True)
                    self._connected = False
                    self._try_reconnect()
                    if self._connected:
                        continue
                    break
        except Exception:
            logger.exception("RabbitMQ consumer thread exiting")

    def _on_message(self, channel, method, properties, body: bytes) -> None:
        try:
            data = json.loads(body)
            producer_id = data.get("_producer_id", "")
            if producer_id == self._local_producer_id:
                return
            event = DomainEvent(
                event_id=data.get("event_id", ""),
                event_name=data.get("event_name", ""),
                event_version=data.get("event_version", 1),
                occurred_at=data.get("occurred_at", ""),
                producer=data.get("producer", ""),
                idempotency_key=data.get("idempotency_key", ""),
                subject_id=data.get("subject_id", ""),
                payload=data.get("payload", {}),
                priority=data.get("priority", 2),
                trace_id=data.get("trace_id", ""),
                span_id=data.get("span_id", ""),
            )
            InMemoryNeuroBus.publish(self, event)
        except Exception:
            logger.exception(
                "RabbitMQ message handler failed for routing_key=%s", method.routing_key
            )

    def _start_reconnector(self) -> None:
        t = threading.Thread(
            target=self._reconnect_loop,
            name="modstore-rabbitmq-reconnector",
            daemon=True,
        )
        t.start()

    def _reconnect_loop(self) -> None:
        while not self._stop_event.is_set() and not self._connected:
            self._stop_event.wait(_RECONNECT_INTERVAL)
            if self._stop_event.is_set():
                break
            self._try_reconnect()
            if self._connected:
                logger.info("RabbitMqNeuroBus reconnected successfully")
                break

    def _try_reconnect(self) -> None:
        try:
            import pika
        except ImportError:
            return
        try:
            self._close_connection()
            params = pika.URLParameters(self._amqp_url)
            params.connection_attempts = 1
            params.blocked_connection_timeout = 300
            params.heartbeat = 600
            self._connection = pika.BlockingConnection(params)
            self._channel = self._connection.channel()
            self._channel.exchange_declare(
                exchange=_EXCHANGE,
                exchange_type=_EXCHANGE_TYPE,
                durable=True,
            )
            self._channel.queue_declare(
                queue=self._queue_name,
                exclusive=True,
                auto_delete=True,
            )
            self._connected = True
            self._rebind_all()
            self._start_consumer()
        except Exception:
            logger.debug("RabbitMQ reconnect attempt failed", exc_info=True)
            self._connected = False

    def _close_connection(self) -> None:
        try:
            if self._consumer_tag and self._channel:
                self._channel.basic_cancel(self._consumer_tag)
        except Exception:
            pass
        self._consumer_tag = None
        try:
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            pass
        self._connection = None
        self._channel = None
        self._connected = False

    def subscribe(
        self,
        event_name: str,
        handler,
        *,
        priority: int = 0,
        filter_fn=None,
    ):
        sub = InMemoryNeuroBus.subscribe(
            self, event_name, handler, priority=priority, filter_fn=filter_fn
        )
        with self._lock:
            if event_name not in self._bindings:
                self._bindings.add(event_name)
                if self._channel and self._connected:
                    routing_key = "#" if event_name == "*" else event_name
                    try:
                        self._channel.queue_bind(
                            queue=self._queue_name,
                            exchange=_EXCHANGE,
                            routing_key=routing_key,
                        )
                    except Exception:
                        logger.debug("queue_bind failed for %s", event_name, exc_info=True)
        return sub

    def publish(self, event: DomainEvent) -> bool:
        result = InMemoryNeuroBus.publish(self, event)
        if self._channel and self._connected:
            try:
                body = json.dumps(
                    {
                        **event.to_dict(),
                        "_producer_id": self._local_producer_id,
                    },
                    ensure_ascii=False,
                    default=str,
                )
                self._channel.basic_publish(
                    exchange=_EXCHANGE,
                    routing_key=event.event_name,
                    body=body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type="application/json",
                        message_id=event.event_id,
                    ),
                )
            except Exception:
                logger.exception(
                    "RabbitMQ publish failed for event=%s; event still dispatched locally",
                    event.event_name,
                )
        return result

    def get_stats(self) -> dict[str, Any]:
        stats = InMemoryNeuroBus.get_stats(self)
        stats["rabbitmq_connected"] = self._connected
        stats["rabbitmq_queue"] = self._queue_name
        stats["rabbitmq_exchange"] = _EXCHANGE
        stats["rabbitmq_bindings"] = len(self._bindings)
        return stats

    def close(self) -> None:
        self._stop_event.set()
        self._close_connection()


__all__ = ["RabbitMqNeuroBus"]
