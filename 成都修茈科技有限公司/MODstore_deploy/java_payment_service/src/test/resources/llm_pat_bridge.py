"""Synthetic local Python gateway -> Java wallet bridge for the Java integration test."""

import os
import sys
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import auth_service
from modstore_server import openai_llm_gateway_api as gateway
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_wallet_client import JavaWalletClient
from modstore_server.models import DeveloperToken, User

user_id, java_url, key_path, database_path = sys.argv[1:]
os.environ.update(
    {
        "MODSTORE_LLM_PAT_ENABLED": "1",
        "PAYMENT_BACKEND": "java",
        "JAVA_PAYMENT_SERVICE_URL": java_url,
        "MODSTORE_LLM_WALLET_SIGNING_KEY_PATH": key_path,
        "MODSTORE_LLM_WALLET_KEY_ID": "synthetic",
        "MODSTORE_LLM_WALLET_MAX_CENTS": "10000",
    }
)
engine = create_engine("sqlite:///" + database_path, connect_args={"check_same_thread": False})
User.__table__.create(engine)
DeveloperToken.__table__.create(engine)
sessions = sessionmaker(bind=engine)
auth_service.get_session_factory = lambda: sessions
raw, prefix, digest = auth_service.generate_pat()
with sessions.begin() as db:
    db.add(User(id=int(user_id), username="synthetic-bridge", password_hash="unused"))
    db.add(
        DeveloperToken(
            user_id=int(user_id),
            name="synthetic",
            token_prefix=prefix,
            token_hash=digest,
            scopes_json='["llm:use"]',
        )
    )

original_resolver = auth_service.resolve_pat_identity


def validate_then_revoke(token):
    identity = original_resolver(token)
    with sessions.begin() as session:
        session.query(DeveloperToken).filter(
            DeveloperToken.user_id == int(user_id)
        ).one().revoked_at = datetime.now(UTC)
    return identity


auth_service.resolve_pat_identity = validate_then_revoke


async def run(request, db, user, **kwargs):
    wallet = JavaWalletClient(request=request)
    hold = await wallet.preauthorize(
        request.headers["authorization"], Decimal("0.05"), "openai", "synthetic", "bridge-request"
    )
    await wallet.settle(request.headers["authorization"], hold, Decimal("0.02"), "bridge-request")
    return {"content": "synthetic", "billed": True, "charge_amount": 0.02}


gateway.run_billed_llm_chat = run
app = FastAPI()
app.include_router(gateway.router)
app.dependency_overrides[get_db] = lambda: None
with TestClient(app) as client:
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer " + raw},
        json={"model": "openai/synthetic", "messages": [{"role": "user", "content": "synthetic"}]},
    )
    assert response.status_code == 200, response.status_code
    assert response.json()["xcagi"]["charge_amount_cny"] == 0.02
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer " + raw},
        json={"model": "openai/synthetic", "messages": [{"role": "user", "content": "synthetic"}]},
    )
    assert response.status_code == 401, response.status_code
print("synthetic bridge passed")
