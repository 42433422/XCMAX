"""自建电子签任务存储（不依赖法大大）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path() -> Path:
    from app.utils.path_utils import get_data_dir

    p = Path(get_data_dir()) / "customer_service" / "stub_esign_tasks.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _sign_secret() -> str:
    return (
        os.environ.get("ESIGN_STUB_SIGN_SECRET")
        or os.environ.get("SECRET_KEY")
        or "xcagi-stub-esign-dev"
    ).strip()


def stub_esign_public_base_url() -> str:
    for key in ("ESIGN_STUB_PUBLIC_BASE_URL", "XCAGI_FRONTEND_PUBLIC_URL", "XCAGI_MARKET_BASE_URL"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if v:
            return v
    return "http://127.0.0.1:5001"


def make_sign_token(task_id: str) -> str:
    digest = hmac.new(
        _sign_secret().encode("utf-8"), task_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return digest[:32]


def verify_sign_token(task_id: str, token: str) -> bool:
    if not task_id or not token:
        return False
    expected = make_sign_token(task_id)
    return hmac.compare_digest(expected, token.strip())


def build_sign_page_url(task_id: str) -> str:
    token = make_sign_token(task_id)
    base = stub_esign_public_base_url()
    return f"{base}/contract/sign/{task_id}?token={token}"


def _read_all() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"tasks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("stub_esign_tasks.json 读取失败")
        return {"tasks": {}}
    if not isinstance(data, dict):
        return {"tasks": {}}
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        data["tasks"] = {}
    return data


def _write_all(data: dict[str, Any]) -> None:
    path = _store_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def create_task(
    *,
    market_user_id: int,
    party_a: str,
    party_b: str,
    subject: str,
    amount_cents: int | None = None,
) -> dict[str, Any]:
    task_id = f"stub-{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    task = {
        "task_id": task_id,
        "market_user_id": int(market_user_id),
        "party_a": (party_a or "")[:200],
        "party_b": (party_b or "")[:200],
        "subject": (subject or "合同签署")[:200],
        "amount_cents": amount_cents,
        "status": "signing",
        "created_at": now,
        "signed_at": "",
        "signer_name": "",
    }
    with _LOCK:
        data = _read_all()
        data["tasks"][task_id] = task
        _write_all(data)
    sign_url = build_sign_page_url(task_id)
    return {**task, "sign_url": sign_url, "sign_token": make_sign_token(task_id)}


def get_task(task_id: str) -> dict[str, Any] | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    with _LOCK:
        data = _read_all()
        task = data.get("tasks", {}).get(tid)
    return dict(task) if isinstance(task, dict) else None


def complete_task(task_id: str, *, signer_name: str) -> dict[str, Any] | None:
    tid = (task_id or "").strip()
    with _LOCK:
        data = _read_all()
        tasks = data.get("tasks", {})
        task = tasks.get(tid)
        if not isinstance(task, dict):
            return None
        if str(task.get("status") or "") == "signed":
            return dict(task)
        task = dict(task)
        task["status"] = "signed"
        task["signed_at"] = _now_iso()
        task["signer_name"] = (signer_name or task.get("party_b") or "")[:100]
        tasks[tid] = task
        data["tasks"] = tasks
        _write_all(data)
    return task


def task_ttl_exceeded(task: dict[str, Any]) -> bool:
    days = int((os.environ.get("ESIGN_STUB_TASK_TTL_DAYS") or "90").strip() or "90")
    if days <= 0:
        return False
    created = str(task.get("created_at") or "")
    if not created:
        return False
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() > days * 86400
