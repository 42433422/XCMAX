"""Business webhook delivery for MODstore domain events.

两层并行投递：

1. 全局默认 URL（``MODSTORE_WEBHOOK_URL``）—— 早期对内 / java_payment_service
   兼容入口，仍由 :func:`dispatch_event` 同步投递；
2. 用户多租户订阅表（``webhook_subscriptions``）—— PR-D 引入的开发者级订阅，
   由 :func:`dispatch_event_to_subscriptions` 按事件名匹配并写
   ``webhook_deliveries`` 投递日志。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from modstore_server.eventing import new_event
from modstore_server.eventing.contracts import canonical_event_name, event_version, validate_payload
from modstore_server.eventing.global_bus import neuro_bus

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    return (os.environ.get("MODSTORE_WEBHOOK_URL") or "").strip()


def _webhook_secret() -> str:
    return (os.environ.get("MODSTORE_WEBHOOK_SECRET") or "").strip()


def _timeout_seconds() -> float:
    try:
        return max(0.5, float(os.environ.get("MODSTORE_WEBHOOK_TIMEOUT_SECONDS", "5")))
    except ValueError:
        return 5.0


def _retry_count() -> int:
    try:
        return max(0, min(5, int(os.environ.get("MODSTORE_WEBHOOK_RETRIES", "2"))))
    except ValueError:
        return 2


_WEBHOOK_EVENTS_DIR_WARNED = False


def _events_dir() -> Path:
    """解析 webhook 投递落盘目录。

    优先级：
    1. ``MODSTORE_WEBHOOK_EVENTS_DIR`` — 显式路径（兼容历史部署，compose 已用）；
    2. ``MODSTORE_RUNTIME_DIR`` — 新的统一运行期数据根，会追加
       ``webhook_events/`` 子目录；
    3. 源码内 ``modstore_server/webhook_events``（仅 dev fallback，会记 warning）。

    生产环境必须通过 (1) 或 (2) 指向持久化卷，避免投递 JSON 文件进入 git 仓库。
    """
    global _WEBHOOK_EVENTS_DIR_WARNED
    raw = (os.environ.get("MODSTORE_WEBHOOK_EVENTS_DIR") or "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        runtime_dir = (os.environ.get("MODSTORE_RUNTIME_DIR") or "").strip()
        if runtime_dir:
            path = Path(runtime_dir).expanduser() / "webhook_events"
        else:
            path = Path(__file__).resolve().parent / "webhook_events"
            if not _WEBHOOK_EVENTS_DIR_WARNED:
                logger.warning(
                    "webhook_dispatcher using in-source default events dir %s; "
                    "set MODSTORE_RUNTIME_DIR or MODSTORE_WEBHOOK_EVENTS_DIR in production "
                    "to avoid writing runtime artifacts into the source tree.",
                    path,
                )
                _WEBHOOK_EVENTS_DIR_WARNED = True
    path.mkdir(parents=True, exist_ok=True)
    return path


def webhook_enabled() -> bool:
    return bool(_webhook_url())


def stable_event_id(event_type: str, aggregate_id: str) -> str:
    event_type = canonical_event_name(event_type)
    aggregate = (aggregate_id or "").strip()
    if aggregate:
        return f"{event_type}:{aggregate}"
    digest = hashlib.sha256(f"{event_type}:{time.time_ns()}".encode("utf-8")).hexdigest()[:16]
    return f"{event_type}:{digest}"


def build_event(
    event_type: str,
    aggregate_id: str,
    data: dict[str, Any],
    *,
    source: str = "modstore-python",
    event_id: str | None = None,
) -> dict[str, Any]:
    event_type = canonical_event_name(event_type)
    now = int(time.time())
    return {
        "id": event_id or stable_event_id(event_type, aggregate_id),
        "type": event_type,
        "version": event_version(event_type),
        "source": source,
        "aggregate_id": aggregate_id,
        "created_at": now,
        "data": data,
    }


def _event_path(event_id: str) -> Path:
    safe = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    return _events_dir() / f"{safe}.json"


def _store_event(event: dict[str, Any], result: dict[str, Any] | None = None) -> None:
    doc = {"event": event, "result": result or {}, "updated_at": int(time.time())}
    _event_path(str(event.get("id") or "")).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_event(event_id: str) -> dict[str, Any] | None:
    path = _event_path(event_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    event = doc.get("event")
    return event if isinstance(event, dict) else None


def _signature(secret: str, timestamp: str, event_id: str, body: bytes) -> str:
    msg = timestamp.encode("utf-8") + b"." + event_id.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def dispatch_event(event: dict[str, Any]) -> dict[str, Any]:
    """Deliver an event to the configured business webhook.

    Delivery errors are captured and returned instead of raised so payment/refund
    state changes never roll back solely because a downstream webhook is down.
    """
    event_id = str(event.get("id") or "")
    url = _webhook_url()
    if not url:
        result = {"ok": False, "skipped": True, "message": "MODSTORE_WEBHOOK_URL is not configured"}
        _store_event(event, result)
        return result

    body = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    timestamp = str(int(time.time()))
    secret = _webhook_secret()
    headers = {
        "Content-Type": "application/json",
        "X-Modstore-Webhook-Id": event_id,
        "X-Modstore-Webhook-Event": str(event.get("type") or ""),
        "X-Modstore-Webhook-Timestamp": timestamp,
    }
    if secret:
        headers["X-Modstore-Webhook-Signature"] = (
            f"sha256={_signature(secret, timestamp, event_id, body)}"
        )

    attempts = _retry_count() + 1
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=_timeout_seconds()) as client:
                response = client.post(url, content=body, headers=headers)
            ok = 200 <= response.status_code < 300
            result = {
                "ok": ok,
                "status_code": response.status_code,
                "attempts": attempt,
                "body": response.text[:1000],
            }
            _store_event(event, result)
            if ok:
                return result
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
            logger.warning(
                "business webhook delivery failed event=%s attempt=%s error=%s",
                event_id,
                attempt,
                exc,
            )
        if attempt < attempts:
            time.sleep(min(2.0, 0.25 * attempt))

    result = {"ok": False, "attempts": attempts, "message": last_error or "delivery failed"}
    _store_event(event, result)
    return result


def _deliver_event_to_subscription(
    session,
    subscription,
    event: dict[str, Any],
) -> None:
    """单条订阅投递（同步、重试、写 ``webhook_deliveries``）。

    任一步异常都会被吞下并写入投递记录，**不会**影响其它订阅或调用方业务。
    """
    from modstore_server.llm_crypto import decrypt_secret  # 局部 import 避免循环
    from modstore_server.models import WebhookDelivery

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    timestamp = str(int(time.time()))
    secret_plain = ""
    try:
        secret_plain = decrypt_secret(subscription.secret_encrypted or "")
    except Exception:
        secret_plain = ""
    headers = {
        "Content-Type": "application/json",
        "X-Modstore-Webhook-Id": event_id,
        "X-Modstore-Webhook-Event": event_type,
        "X-Modstore-Webhook-Timestamp": timestamp,
        "X-Modstore-Webhook-Subscription": str(subscription.id),
    }
    if secret_plain:
        headers["X-Modstore-Webhook-Signature"] = (
            f"sha256={_signature(secret_plain, timestamp, event_id, body)}"
        )

    delivery = WebhookDelivery(
        subscription_id=subscription.id,
        user_id=subscription.user_id,
        event_id=event_id,
        event_type=event_type,
        target_url=subscription.target_url,
        status="pending",
        attempts=0,
        request_body=body.decode("utf-8", errors="replace")[:4000],
    )
    session.add(delivery)
    session.flush()

    attempts = _retry_count() + 1
    last_error = ""
    last_status_code: int | None = None
    last_response_body = ""
    started = time.monotonic()
    success = False
    for attempt in range(1, attempts + 1):
        delivery.attempts = attempt
        try:
            with httpx.Client(timeout=_timeout_seconds()) as client:
                response = client.post(subscription.target_url, content=body, headers=headers)
            last_status_code = response.status_code
            last_response_body = (response.text or "")[:1000]
            if 200 <= response.status_code < 300:
                success = True
                break
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
            logger.warning(
                "subscription %s delivery failed attempt=%s url=%s err=%s",
                subscription.id,
                attempt,
                subscription.target_url,
                exc,
            )
        if attempt < attempts:
            time.sleep(min(2.0, 0.25 * attempt))

    duration_ms = (time.monotonic() - started) * 1000.0
    delivery.duration_ms = duration_ms
    delivery.completed_at = datetime.now(timezone.utc)
    delivery.status_code = last_status_code
    delivery.response_body = last_response_body
    delivery.error_message = "" if success else last_error
    delivery.status = "success" if success else "failed"

    subscription.last_delivery_at = datetime.now(timezone.utc)
    subscription.last_delivery_status = delivery.status
    if success:
        subscription.success_count = int(subscription.success_count or 0) + 1
    else:
        subscription.failure_count = int(subscription.failure_count or 0) + 1


def dispatch_event_to_subscriptions(event: dict[str, Any]) -> int:
    """把事件分发给所有命中的开发者订阅，返回已投递订阅数。

    任意一条订阅出错都会被吞下，不影响其它订阅或调用方。
    """
    from modstore_server.models import WebhookSubscription, get_session_factory

    event_type = canonical_event_name(str(event.get("type") or ""))
    if not event_type:
        return 0

    delivered = 0
    sf = get_session_factory()
    with sf() as session:
        try:
            subs = (
                session.query(WebhookSubscription)
                .filter(WebhookSubscription.is_active.is_(True))
                .all()
            )
        except Exception as exc:  # 表不存在/数据库未初始化时静默跳过
            logger.warning("webhook_subscriptions query failed: %s", exc)
            return 0

        for sub in subs:
            try:
                wanted = json.loads(sub.enabled_events_json or "[]")
                if not isinstance(wanted, list):
                    continue
            except json.JSONDecodeError:
                continue
            if "*" not in wanted and event_type not in wanted:
                continue
            try:
                _deliver_event_to_subscription(session, sub, event)
                delivered += 1
            except Exception as exc:
                logger.warning(
                    "subscription %s dispatch error event=%s: %s", sub.id, event_type, exc
                )
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("commit subscription deliveries failed: %s", exc)

    return delivered


def publish_event(
    event_type: str, aggregate_id: str, data: dict[str, Any], *, source: str = "modstore-python"
) -> dict[str, Any]:
    event_type = canonical_event_name(event_type)
    missing = validate_payload(event_type, data)
    if missing:
        logger.warning(
            "event payload missing recommended fields event=%s fields=%s",
            event_type,
            ",".join(missing),
        )
    neuro_bus.publish(
        new_event(
            event_type,
            producer=source,
            subject_id=aggregate_id,
            payload=data,
            event_version=event_version(event_type),
        )
    )
    event = build_event(event_type, aggregate_id, data, source=source)
    result = dispatch_event(event)
    try:
        delivered = dispatch_event_to_subscriptions(event)
    except Exception as exc:
        logger.warning("subscription fanout failed event=%s: %s", event_type, exc)
        delivered = 0
    if isinstance(result, dict):
        result.setdefault("subscriptions_delivered", delivered)
    return result


def enqueue_event(
    session,
    event_type: str,
    aggregate_id: str,
    data: dict[str, Any],
    *,
    source: str = "modstore-python",
):
    """事务内安全发布：把事件入 ``OutboxEvent`` 表，与业务写一同提交。

    返回 SQLAlchemy 实体或 ``None``（同 ``event_id`` 已存在）。后台
    :class:`modstore_server.eventing.db_outbox.OutboxDispatcherWorker`
    会把 pending 行 drain 到本模块 :func:`dispatch_event`。

    与 ``publish_event`` 的差异：``publish_event`` 会立刻同步投递，
    适合迁移期保留兼容；新代码应使用 ``enqueue_event`` 获得
    "业务事务回滚 → 事件不会发出" 的原子保证。
    """
    from modstore_server.eventing import db_outbox

    return db_outbox.enqueue(
        session,
        event_type,
        aggregate_id,
        data,
        producer=source,
    )


def replay_event(event_id: str) -> dict[str, Any]:
    event = _load_event(event_id)
    if not event:
        return {"ok": False, "message": "webhook event not found"}
    return dispatch_event(event)
