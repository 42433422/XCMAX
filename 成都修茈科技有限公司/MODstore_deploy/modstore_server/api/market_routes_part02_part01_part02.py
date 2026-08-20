# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.api.market_routes_part01_part01_part01 import AiWalletRefundDTO
from modstore_server.api.market_routes_part01_part01_part01 import AiWalletReleaseDTO
from modstore_server.api.market_routes_part01_part01_part01 import AiWalletSettleDTO


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.post("/wallet/ai/settle")
def api_wallet_ai_settle(
    body: AiWalletSettleDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """结算 AI 预授权：实际金额低于预授权则释放差额，高于则补扣差额。"""
    actual = _facade()._wallet_money(body.actual_amount)
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_settle", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, body.hold_no.strip())
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(
                    preauth, status="settled", settled_amount=actual
                ),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        reserved = abs(_facade()._wallet_money(preauth.amount))
        delta = actual - reserved
        balance_before = _facade()._wallet_money(wallet.balance)
        if delta > 0 and balance_before < delta:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{_facade()._wallet_money_str(delta)}，当前 ¥{_facade()._wallet_money_str(balance_before)}",
            )
        wallet.balance = balance_before - delta
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-delta,
            txn_type="ai_settle",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=body.hold_no.strip(),
                actual_amount=_facade()._wallet_money_str(actual),
                reserved_amount=_facade()._wallet_money_str(reserved),
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(preauth, status="settled", settled_amount=actual),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/release")
def api_wallet_ai_release(
    body: AiWalletReleaseDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """释放 AI 预授权；已结算的 hold 不再退回，保持幂等。"""
    key = body.idempotency_key.strip()
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_release", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, body.hold_no.strip())
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        if existing:
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(preauth, status="released", settled_amount=0),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        settled = (
            session.query(_facade().Transaction)
            .filter(
                _facade().Transaction.user_id == user.id,
                _facade().Transaction.txn_type == "ai_settle",
            )
            .order_by(_facade().Transaction.created_at.desc())
            .limit(200)
            .all()
        )
        if any(
            (
                str(_facade()._parse_ai_wallet_meta(row.description).get("hold_no") or "")
                == body.hold_no.strip()
                for row in settled
            )
        ):
            return {
                "ok": True,
                "hold": _facade()._ai_hold_payload(preauth, status="settled", settled_amount=0),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        reserved = abs(_facade()._wallet_money(preauth.amount))
        wallet.balance = _facade()._wallet_money(wallet.balance) + reserved
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=reserved,
            txn_type="ai_release",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=body.hold_no.strip(), reason=(body.reason or "release")[:128]
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        return {
            "ok": True,
            "hold": _facade()._ai_hold_payload(preauth, status="released", settled_amount=0),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.post("/wallet/ai/refund")
def api_wallet_ai_refund(
    body: AiWalletRefundDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """Refund a settled AI wallet hold. The idempotency key makes retries safe."""
    key = body.idempotency_key.strip()
    hold_no = body.hold_no.strip()
    refund_amount = _facade()._wallet_money(body.refund_amount)
    sf = _facade().get_session_factory()
    with sf() as session:
        existing = _facade()._find_ai_txn_by_key(session, user.id, "ai_refund", key)
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = _facade().Wallet(user_id=user.id, balance=0.0)
            session.add(wallet)
            session.flush()
        preauth = _facade()._find_ai_preauth_by_hold(session, user.id, hold_no)
        if not preauth:
            raise _facade().HTTPException(404, "预授权不存在")
        settled_amount = _facade()._ai_settled_amount_for_hold(session, user.id, hold_no)
        if settled_amount <= 0:
            raise _facade().HTTPException(400, "预授权尚未结算，不能退款")
        if existing:
            return {
                "ok": True,
                "refund": {
                    "hold_no": hold_no,
                    "amount": _facade()._wallet_money_str(existing.amount),
                    "status": "refunded",
                    "refund_transaction_id": existing.id,
                },
                "hold": _facade()._ai_hold_payload(
                    preauth, status="refunded", settled_amount=settled_amount
                ),
                "balance": _facade()._wallet_money_str(wallet.balance),
                "idempotent": True,
            }
        refunded_before = _facade()._ai_refunded_amount_for_hold(session, user.id, hold_no)
        refundable = settled_amount - refunded_before
        if refund_amount > refundable:
            raise _facade().HTTPException(
                400,
                f"退款金额超过可退余额：申请 ¥{_facade()._wallet_money_str(refund_amount)}，可退 ¥{_facade()._wallet_money_str(refundable)}",
            )
        wallet.balance = _facade()._wallet_money(wallet.balance) + refund_amount
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=refund_amount,
            txn_type="ai_refund",
            status="completed",
            description=_facade()._ai_wallet_meta(
                hold_no=hold_no,
                refund_amount=_facade()._wallet_money_str(refund_amount),
                settled_amount=_facade()._wallet_money_str(settled_amount),
                refunded_total_after=_facade()._wallet_money_str(refunded_before + refund_amount),
                reason=(body.reason or "refund")[:128],
            ),
            idempotency_key=key,
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return {
            "ok": True,
            "refund": {
                "hold_no": hold_no,
                "amount": _facade()._wallet_money_str(refund_amount),
                "status": "refunded",
                "refund_transaction_id": txn.id,
            },
            "hold": _facade()._ai_hold_payload(
                preauth, status="refunded", settled_amount=settled_amount
            ),
            "balance": _facade()._wallet_money_str(wallet.balance),
        }


@_facade().router.get("/wallet/transactions")
def api_wallet_transactions(
    limit: int = _facade().Query(50, ge=1, le=200),
    offset: int = _facade().Query(0, ge=0),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        total = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .count()
        )
        rows = (
            session.query(_facade().Transaction)
            .filter(_facade().Transaction.user_id == user.id)
            .order_by(_facade().Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "transactions": [
                {
                    "id": r.id,
                    "amount": r.amount,
                    "type": r.txn_type,
                    "status": r.status,
                    "description": r.description,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ],
            "total": total,
        }


@_facade().router.post("/market/catalog/{item_id}/buy")
def api_buy_item(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise _facade().HTTPException(404, "商品不存在")
        if item.price <= 0:
            existing = (
                session.query(_facade().Purchase)
                .filter(
                    _facade().Purchase.user_id == user.id,
                    _facade().Purchase.catalog_id == item.id,
                )
                .first()
            )
            from modstore_server.market_shared import _grant_catalog_entitlement

            if existing:
                _grant_catalog_entitlement(
                    session, user_id=user.id, item=item, source="free_catalog"
                )
                session.commit()
                return {"ok": True, "message": "已拥有"}
            purchase = _facade().Purchase(user_id=user.id, catalog_id=item.id, amount=0)
            session.add(purchase)
            _grant_catalog_entitlement(session, user_id=user.id, item=item, source="free_catalog")
            session.commit()
            return {"ok": True, "message": "免费领取成功"}
        existing = (
            session.query(_facade().Purchase)
            .filter(
                _facade().Purchase.user_id == user.id,
                _facade().Purchase.catalog_id == item.id,
            )
            .first()
        )
        if existing:
            return {"ok": True, "message": "已拥有"}
        wallet = (
            session.query(_facade().Wallet)
            .filter(_facade().Wallet.user_id == user.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            session.add(_facade().Wallet(user_id=user.id, balance=0.0))
            session.flush()
            wallet = (
                session.query(_facade().Wallet)
                .filter(_facade().Wallet.user_id == user.id)
                .with_for_update()
                .first()
            )
        if not wallet or wallet.balance < item.price:
            raise _facade().HTTPException(
                402,
                f"余额不足，需要 ¥{item.price}，当前 ¥{(wallet.balance if wallet else 0)}",
            )
        wallet.balance -= item.price
        wallet.updated_at = _facade().datetime.now(_facade().timezone.utc)
        purchase = _facade().Purchase(user_id=user.id, catalog_id=item.id, amount=item.price)
        txn = _facade().Transaction(
            user_id=user.id,
            amount=-item.price,
            txn_type="purchase",
            status="completed",
            description=f"购买 {item.name} ({item.pkg_id})",
        )
        session.add(purchase)
        session.add(txn)
        session.commit()
        return {"ok": True, "message": "购买成功", "new_balance": wallet.balance}


@_facade().router.get("/market/catalog/{item_id}/download")
def api_download_item(
    item_id: int, user: _facade().User = _facade().Depends(_facade()._get_current_user)
):
    sf = _facade().get_session_factory()
    with sf() as session:
        item = (
            session.query(_facade().CatalogItem).filter(_facade().CatalogItem.id == item_id).first()
        )
        if not item:
            raise _facade().HTTPException(404, "商品不存在")
        if _facade().is_planned_duty_employee_pack(item.pkg_id, item.artifact):
            raise _facade().HTTPException(404, "商品不存在")
        if item.price > 0:
            purchased = (
                session.query(_facade().Purchase)
                .filter(
                    _facade().Purchase.user_id == user.id,
                    _facade().Purchase.catalog_id == item.id,
                )
                .first()
            )
            if not purchased:
                raise _facade().HTTPException(403, "未购买此商品，请先购买后下载")
        if not item.stored_filename:
            raise _facade().HTTPException(404, "该商品无文件可下载")
        from fastapi.responses import StreamingResponse
        from modstore_server.catalog_store import files_dir

        path = _facade()._existing_child_file(files_dir(), item.stored_filename)
        if path is None:
            raise _facade().HTTPException(404, "文件缺失")

        def generate():
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk

        return StreamingResponse(
            generate(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={item.pkg_id}.zip",
                "Content-Length": str(path.stat().st_size),
            },
        )
