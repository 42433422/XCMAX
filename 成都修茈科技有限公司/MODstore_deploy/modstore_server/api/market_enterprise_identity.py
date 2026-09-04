# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Immutable enterprise identity administration endpoints."""

from __future__ import annotations

import importlib
import os

import httpx
from pydantic import BaseModel, Field


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


class EnterpriseIdentityDTO(BaseModel):
    """Single-assignment legal identity backed by reviewed source material."""

    enterprise_subject_id: str = Field(..., min_length=4, max_length=128)
    legal_name: str = Field(..., min_length=2, max_length=256)
    verification_sha256: str = Field(..., pattern="^[0-9a-fA-F]{64}$")


def _freeze_java_enterprise_identity(
    *,
    user_id: int,
    verified_by_user_id: int,
    subject_id: str,
    legal_name: str,
    digest: str,
) -> None:
    if os.environ.get("PAYMENT_BACKEND", "").strip().lower() != "java":
        return
    key = (
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or ""
    ).strip()
    if not key:
        raise _facade().HTTPException(503, "Java 支付身份同步密钥未配置")
    base = (os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080").rstrip("/")
    try:
        response = httpx.post(
            f"{base}/api/internal/payment/enterprise-identities",
            headers={"X-Internal-Api-Key": key},
            json={
                "user_id": user_id,
                "verified_by_user_id": verified_by_user_id,
                "enterprise_subject_id": subject_id,
                "legal_name": legal_name,
                "verification_sha256": digest,
            },
            timeout=10.0,
        )
        if response.status_code == 409:
            raise _facade().HTTPException(409, "Java 支付企业主体已冻结且不一致")
        response.raise_for_status()
        payload = response.json()
    except _facade().HTTPException:
        raise
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise _facade().HTTPException(503, "Java 支付企业身份同步失败") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("ok") is not True
        or payload.get("source") != "java_postgresql"
        or payload.get("frozen") is not True
        or str(payload.get("enterprise_subject_id") or "") != subject_id
    ):
        raise _facade().HTTPException(503, "Java 支付企业身份同步回执无效")


@_facade().router.put("/admin/users/{user_id}/enterprise-identity")
def api_admin_verify_enterprise_identity(
    user_id: int,
    body: EnterpriseIdentityDTO,
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """Freeze a verified enterprise identity before its qualifying payment."""

    subject_id = body.enterprise_subject_id.strip()
    legal_name = body.legal_name.strip()
    digest = body.verification_sha256.lower()
    sf = _facade().get_session_factory()
    with sf() as session:
        target = session.query(_facade().User).filter(_facade().User.id == user_id).first()
        if not target:
            raise _facade().HTTPException(404, "用户不存在")
        if target.is_admin:
            raise _facade().HTTPException(409, "管理员账号不能计为客户企业主体")
        existing = (
            str(getattr(target, "enterprise_subject_id", "") or ""),
            str(getattr(target, "enterprise_legal_name", "") or ""),
            str(getattr(target, "enterprise_verification_sha256", "") or "").lower(),
        )
        requested = (subject_id, legal_name, digest)
        if any(existing) and existing != requested:
            raise _facade().HTTPException(409, "企业主体已冻结，不允许覆盖历史身份")
        _freeze_java_enterprise_identity(
            user_id=user_id,
            verified_by_user_id=int(user.id),
            subject_id=subject_id,
            legal_name=legal_name,
            digest=digest,
        )
        if not any(existing):
            target.enterprise_subject_id = subject_id
            target.enterprise_legal_name = legal_name
            target.enterprise_verification_sha256 = digest
            target.enterprise_verified_at = (
                _facade().datetime.now(_facade().timezone.utc).replace(tzinfo=None)
            )
            target.enterprise_verified_by_user_id = int(user.id)
        target.is_enterprise = True
        session.commit()
        return {
            "ok": True,
            "user_id": user_id,
            "enterprise_subject_id": subject_id,
            "legal_name": legal_name,
            "verification_sha256": digest,
            "frozen": True,
        }
