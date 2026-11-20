"""Settle image generation against the upstream's exact token receipt."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from modstore_server import llm_client_requests as ledger
from modstore_server.llm_billing import (
    JavaWalletClient,
    UsageMeter,
    authorization_header,
    enforce_risk_limits,
    estimate_preauthorization,
    money,
    service_fee_multiplier,
)
from modstore_server.llm_billing_recovery import complete_receipt, recover_receipt
from modstore_server.llm_billing_values import reported_token_dimensions
from modstore_server.llm_chat_proxy import image_dispatch
from modstore_server.llm_model_gates import _get_priced_row
from modstore_server.llm_operation_routes import OperationRoute, resolve_operation_route
from modstore_server.models import AiModelPrice
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_IMAGE_DEADLINE_SECONDS = 180
# Output estimate for the wallet hold only. Settlement uses the provider's exact tokens.
_PREAUTH_OUTPUT_TOKENS_PER_IMAGE = 4096


def image_token_tariff(db: Session, route: OperationRoute) -> tuple[Decimal, Decimal] | None:
    """Only admit platform routes with a known usage contract and an active token price."""
    base = urlsplit(route.base_url or "https://api.openai.com/v1")
    if (
        route.provider != "openai"
        or base.scheme != "https"
        or base.netloc != "api.openai.com"
        or base.path.rstrip("/") not in {"", "/v1"}
        or not (route.model.startswith("gpt-image-") or route.model == "chatgpt-image-latest")
        or route.model == "gpt-image-1"
    ):
        return None
    price = _get_priced_row(db, route.provider, route.model)
    if price is None:
        return None
    input_price = Decimal(str(price.input_price_per_1k or 0))
    output_price = Decimal(str(price.output_price_per_1k or 0))
    if not all(value.is_finite() and value > 0 for value in (input_price, output_price)):
        return None
    multiplier = service_fee_multiplier(db)
    return input_price * multiplier, output_price * multiplier


def exact_image_usage(raw: Any) -> UsageMeter | None:
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(usage, dict):
        return None
    input_tokens, output_tokens, total_tokens = (
        usage.get(name) for name in ("input_tokens", "output_tokens", "total_tokens")
    )
    if (
        not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
        or not isinstance(total_tokens, int)
        or any(isinstance(v, bool) for v in (input_tokens, output_tokens, total_tokens))
    ):
        return None
    if input_tokens < 0 or output_tokens <= 0 or total_tokens != input_tokens + output_tokens:
        return None
    return UsageMeter(input_tokens, output_tokens, total_tokens, estimated=False)


async def run_billed_image(
    request: Request,
    db: Session,
    user_id: int,
    *,
    provider: str,
    model: str,
    prompt: str,
    size: str,
    count: int,
    client_request_id: str | None,
) -> dict[str, Any]:
    if not prompt:
        raise HTTPException(422, "生图提示词不能为空")

    digest = None
    if client_request_id:
        digest = ledger.request_digest(
            {
                "operation": "image_generation",
                "provider": provider,
                "model": model,
                "prompt": prompt,
                "size": size,
                "n": count,
            }
        )
        completed = ledger.completed_receipt(db, user_id, client_request_id, digest)
        if completed is not None:
            outcome, value = completed
            if outcome == "replay" and isinstance(value, dict):
                return value
            raise HTTPException(
                409, {"message": "生图请求已提交或请求内容发生变化", "state": outcome}
            )

    # Materialize only price eligibility before releasing the request connection.
    # Re-read the chosen tariff after discovery before reserving or charging.
    priced_models = {
        row.model
        for row in db.query(AiModelPrice)
        .filter(AiModelPrice.provider == "openai", AiModelPrice.enabled.is_(True))
        .all()
        if all(
            (value := Decimal(str(raw or 0))).is_finite() and value > 0
            for raw in (row.input_price_per_1k, row.output_price_per_1k)
        )
    }

    def eligible(route: OperationRoute) -> bool:
        if route.key_source == "user_override":
            return True
        base = urlsplit(route.base_url or "https://api.openai.com/v1")
        return (
            route.provider == "openai"
            and base.scheme == "https"
            and base.netloc == "api.openai.com"
            and base.path.rstrip("/") in {"", "/v1"}
            and (route.model.startswith("gpt-image-") or route.model == "chatgpt-image-latest")
            and route.model != "gpt-image-1"
            and route.model in priced_models
        )

    route = await resolve_operation_route(
        db,
        user_id,
        "image_generation",
        provider=provider,
        model=model,
        detached_route_filter=eligible,
        release_before_discovery=True,
    )
    tariff = image_token_tariff(db, route) if route.key_source == "platform" else None
    wallet = JavaWalletClient(verify_receipt=True)
    if route.key_source == "platform":
        if tariff is None or not wallet.enabled:
            raise HTTPException(503, "当前生图模型未配置可核验的 token 计费")
        if not client_request_id:
            raise HTTPException(422, "平台代付生图需要请求键")
    messages = [{"role": "user", "content": prompt}]
    enforce_risk_limits(db, user_id, route.provider, route.model, messages, request)

    row = None
    request_id = ""
    auth = authorization_header(request)
    if client_request_id:
        assert digest is not None
        outcome, value = ledger.begin(
            db, user_id, client_request_id, digest, _IMAGE_DEADLINE_SECONDS
        )
        if outcome == "replay" and isinstance(value, dict):
            return value
        if outcome == "processing":
            recovered = await recover_receipt(
                db, user_id, client_request_id, auth, operation="image_generation", request=request
            )
            if recovered is not None:
                return recovered
        if outcome != "run":
            raise HTTPException(
                409, {"message": "生图请求已提交或请求内容发生变化", "state": outcome}
            )
        row = value
        request_id = ledger.attempt_request_id(user_id, client_request_id, row.attempts)

    if row is not None:
        ledger.mark_settling(db, row)
    hold = None
    if tariff:
        assert row is not None
        amount = estimate_preauthorization(
            db,
            route.provider,
            route.model,
            messages,
            _PREAUTH_OUTPUT_TOKENS_PER_IMAGE * count,
        )
        try:
            hold = await wallet.preauthorize(auth, amount, route.provider, route.model, request_id)
        except HTTPException as exc:
            if exc.status_code in {400, 401, 402, 403, 422, 429}:
                return finish_rejected_image(db, row, exc.status_code, request_id)
            raise HTTPException(
                409, {"message": "生图预授权状态待核对", "request_id": request_id}
            ) from exc
        if not hold.enabled or not hold.hold_no:
            raise HTTPException(409, {"message": "生图预授权状态待核对", "request_id": request_id})

    try:
        result = await image_dispatch(
            route.provider,
            api_key=route.api_key,
            base_url=route.base_url,
            model=route.model,
            prompt=prompt,
            size=size,
            n=count,
        )
        status = result.get("status")
        if not result.get("ok") or not result.get("images"):
            if isinstance(status, int) and status in {400, 401, 403, 404, 422, 429}:
                if hold:
                    await wallet.release(auth, hold, "image provider rejected request", request_id)
                if row is not None:
                    return finish_rejected_image(db, row, status, request_id)
                raise HTTPException(status, "生图供应商拒绝请求")
            if row is not None:
                raise HTTPException(
                    409,
                    {"message": "生图结果与计费状态待核对", "request_id": request_id},
                )
            raise HTTPException(502, "生图供应商未返回图像")
        usage = exact_image_usage(result.get("raw"))
        charge = Decimal("0")
        if hold and tariff:
            if usage is None:
                raise HTTPException(
                    409,
                    {
                        "message": "供应商未返回可核验的 token 用量",
                        "request_id": request_id,
                    },
                )
            charge = money(
                (usage.prompt_tokens * tariff[0] + usage.completion_tokens * tariff[1]) / 1000
            )
        receipt = {
            "ok": True,
            "images": result["images"],
            "provider": route.provider,
            "model": route.model,
            "key_source": route.key_source,
            "billed": hold is not None,
            "charge_amount": str(charge),
            "usage": vars(usage) if usage else None,
            "usage_details": reported_token_dimensions(
                result.get("raw", {}).get("usage") if isinstance(result.get("raw"), dict) else None
            ),
            "request_id": request_id,
            "operation": "image_generation",
        }
        if hold and tariff:
            assert row is not None
            receipt.update(
                hold_no=hold.hold_no,
                pricing={
                    "currency": "CNY",
                    "effective_input_per_1k": str(tariff[0]),
                    "effective_output_per_1k": str(tariff[1]),
                },
            )
            ledger.prepare_settlement(db, row, receipt)
            try:
                await wallet.settle(auth, hold, charge, request_id)
            except HTTPException as exc:
                if client_request_id:
                    recovered = await recover_receipt(
                        db,
                        user_id,
                        client_request_id,
                        auth,
                        operation="image_generation",
                        request=request,
                    )
                    if recovered is not None:
                        return recovered
                raise HTTPException(
                    409,
                    {
                        "message": "图像已生成，钱包结算状态待核对",
                        "request_id": request_id,
                    },
                ) from exc
            return complete_receipt(db, row, receipt)
        if row is not None:
            ledger.finish(db, row, receipt)
        return receipt
    except HTTPException as exc:
        if row is not None and exc.status_code >= 500:
            raise HTTPException(
                409, {"message": "生图与计费状态待核对", "request_id": request_id}
            ) from exc
        raise
    except RECOVERABLE_ERRORS as exc:
        if row is not None:
            raise HTTPException(
                409, {"message": "生图与计费状态待核对", "request_id": request_id}
            ) from exc
        raise HTTPException(502, "生图供应商调用失败") from exc


def finish_rejected_image(db: Session, row, status: int, request_id: str) -> dict[str, Any]:
    receipt = {
        "ok": False,
        "status": status,
        "request_id": request_id,
        "message": "生图请求被拒绝",
    }
    ledger.finish(db, row, receipt)
    return receipt
