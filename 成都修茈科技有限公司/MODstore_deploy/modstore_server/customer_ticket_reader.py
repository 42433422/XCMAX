"""Revocable company ticket grants, independent of user JWTs and PATs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from modstore_server.customer_service_tools import json_loads
from modstore_server.incident_team_handler_digest import redact_text
from modstore_server.models_cs import CustomerServiceAction, CustomerServiceAuditLog

PREFIX = "cst_ro_"
SCOPE = "customer-tickets:read"
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?"
    r"(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_CREDENTIAL_URI_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@:]*:[^\s/]*@")
_SECRET_FIELD_RE = re.compile(
    r"(?i)((?:api[_ -]?key|password|passwd|token|secret|authorization|"
    r"private[_ -]?key|access[_ -]?key|密码|口令|密钥|私钥|令牌|授权码)"
    r"\s*[\"']?\s*(?:[:=：]|为|是)\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\r\n,;，；]+)"
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    audit_handler = logging.StreamHandler()
    audit_handler.setFormatter(logging.Formatter("%(asctime)s ticket_read_audit %(message)s"))
    logger.addHandler(audit_handler)


def _reader_text(value: object, limit: int = 300) -> str:
    text = _PRIVATE_KEY_RE.sub("[redacted]", str(value))
    text = _CREDENTIAL_URI_RE.sub(r"\1[redacted]@", text)
    text = _SECRET_FIELD_RE.sub(r"\1[redacted]", text)
    return redact_text(text, limit)


@dataclass(frozen=True)
class TicketReader:
    grant_id: str
    principal: str
    company_id: str
    instance_id: str
    owner_ids: tuple[int, ...]
    is_admin: bool = False

    def scope(self) -> dict:
        return {
            "company_id": self.company_id,
            "instance_id": self.instance_id,
            "grant_id": self.grant_id,
            "principal": self.principal,
            "scope": SCOPE,
        }


def resolve_reader(token: str, request: Request) -> TicketReader:
    """Read protected config on EVERY request, including revocation/expiry checks."""
    grant_id = "unknown"
    try:
        path = os.environ["MODSTORE_TICKET_READ_GRANTS_FILE"]
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
                or info.st_uid not in (0, os.geteuid())
                or info.st_size > 65536
            ):
                raise ValueError("unprotected grant configuration")
            config = json.load(stream)
        instance = os.environ["MODSTORE_INSTANCE_ID"]
        if not instance or config["instance_id"] != instance or not config["company_id"]:
            raise ValueError("instance mismatch")
        owners = config["owner_user_ids"]
        if (
            not isinstance(owners, list)
            or not owners
            or any(type(i) is not int or i < 1 for i in owners)
        ):
            raise ValueError("explicit company membership required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        grant = next(g for g in config["grants"] if hmac.compare_digest(g["token_sha256"], digest))
        grant_id = grant["id"]
        expires = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
        if (
            grant.get("revoked", False)
            or grant["scopes"] != [SCOPE]
            or grant["principal"] not in ("dot", "grok-bot")
            or expires <= datetime.now(UTC)
        ):
            raise ValueError("inactive grant")
    except (OSError, KeyError, ValueError, TypeError, AttributeError, StopIteration):
        logger.warning("ticket_read denied grant=%s reason=invalid_grant", grant_id)
        raise HTTPException(401, "工单只读授权无效、已撤销或已过期") from None
    if (
        request is None
        or request.method != "GET"
        or not re.fullmatch(r"/api/customer-service/tickets(?:/[0-9]+)?", request.url.path)
    ):
        logger.warning("ticket_read denied grant=%s reason=route", grant_id)
        raise HTTPException(403, "此服务身份仅允许读取工单列表和详情")
    if set(request.query_params) - {"status", "search", "offset", "limit"}:
        logger.warning("ticket_read denied grant=%s reason=query_scope", grant_id)
        raise HTTPException(403, "工单公司范围由服务器固定，不接受范围覆盖参数")
    logger.info("ticket_read allowed grant=%s method=GET path=%s", grant_id, request.url.path)
    return TicketReader(grant_id, grant["principal"], config["company_id"], instance, tuple(owners))


async def reader_boundary(request: Request, call_next):
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith(f"Bearer {PREFIX}"):
        return await call_next(request)
    try:
        request.state.ticket_reader = resolve_reader(authorization[7:], request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    logger.info(
        "ticket_read result grant=%s status=%s",
        request.state.ticket_reader.grant_id,
        response.status_code,
    )
    return response


def reader_ticket(db, row) -> dict:
    """Operational allowlist: never export evidence, credentials or raw tool output."""
    from modstore_server.models import User

    owner = db.get(User, row.assigned_admin_id) if row.assigned_admin_id else None
    actions = (
        db.query(CustomerServiceAction)
        .filter_by(ticket_id=row.id)
        .order_by(CustomerServiceAction.id.asc())
        .all()
    )
    latest = next(
        (a for a in reversed(actions) if a.action_type == "employee.dispatch"),
        actions[-1] if actions else None,
    )
    result = json_loads(latest.result_json, {}) if latest else {}
    roles = result.get("roles", []) if isinstance(result, dict) else []
    roles = [r for r in roles if isinstance(r, dict)] if isinstance(roles, list) else []
    responsible_roles = [
        {k: _reader_text(r.get(k)) for k in ("role", "employee_id", "status")}
        for r in roles
        if isinstance(r, dict)
    ]
    blockers = [
        responsible_roles[i]
        for i, r in enumerate(roles)
        if isinstance(r, dict) and r.get("ok") is False
    ]
    if latest and latest.status in ("failed", "partial") and not blockers:
        blockers = [{"action_id": latest.id, "status": _reader_text(latest.status)}]
    if row.status in ("resolved", "closed"):
        blockers = []
    payload = {
        key: getattr(row, key)
        for key in (
            "id",
            "ticket_no",
            "user_id",
            "submitter_type",
            "intent",
            "status",
            "priority",
            "decision_status",
            "assigned_admin_id",
        )
    }
    for key, value in payload.items():
        if isinstance(value, str):
            payload[key] = _reader_text(value)
    payload.update({key: _reader_text(getattr(row, key), 4000) for key in ("title", "summary")})
    payload.update(
        {
            key: value.isoformat() if value else None
            for key in ("created_at", "updated_at", "closed_at")
            for value in (getattr(row, key),)
        }
    )
    payload.update(
        {
            "assignee": _reader_text(owner.username) if owner else None,
            "assignment_status": "assigned" if owner else "unassigned",
            "latest_action_status": _reader_text(latest.status) if latest else None,
            "blockers": blockers,
            "responsible_roles": responsible_roles,
            "due_at": None,
            "is_overdue": None,
            "deadline_status": "not_recorded",
        }
    )
    return payload


def reader_detail(db, row, reader: TicketReader) -> dict:
    from modstore_server.customer_ticket_execution import ticket_execution_overview

    audits = (
        db.query(CustomerServiceAuditLog)
        .filter_by(ticket_id=row.id)
        .order_by(CustomerServiceAuditLog.id.asc())
        .all()
    )
    return {
        "ticket": reader_ticket(db, row),
        "execution_overview": ticket_execution_overview(db, row),
        "scope": reader.scope(),
        "timeline": [
            {
                "id": a.id,
                "event_type": _reader_text(a.event_type),
                "actor_type": _reader_text(a.actor_type),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in audits
        ],
    }
