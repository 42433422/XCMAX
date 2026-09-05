"""Browser handoff endpoints. Credentials travel in POST bodies, never URLs."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from modstore_server.api.deps import get_current_user
from modstore_server.auth_service import create_access_token, create_refresh_token
from modstore_server.browser_handoff import consume_code, issue_code
from modstore_server.models import User

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

router = APIRouter(prefix="/auth/browser-handoff", tags=["auth"])


class HandoffTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(max_length=1024)
    purpose: Literal["wallet", "plans"]


class HandoffConsume(HandoffTarget):
    code: str = Field(min_length=43, max_length=43)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("")
def issue_browser_handoff(
    body: HandoffTarget, response: Response, user: User = Depends(get_current_user)
):
    _no_store(response)
    try:
        return {"ok": True, "data": issue_code(int(user.id), body.target, body.purpose)}
    except ValueError as exc:
        raise HTTPException(400, "无法创建登录连接，请重新登录", headers=NO_STORE) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "登录连接暂时不可用，请稍后重试", headers=NO_STORE) from exc


@router.post("/consume")
def consume_browser_handoff(body: HandoffConsume, response: Response):
    _no_store(response)
    try:
        user = consume_code(body.code, body.target, body.purpose)
    except ValueError as exc:
        raise HTTPException(
            401, "登录连接已失效，请从桌面重新打开或登录", headers=NO_STORE
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "登录连接暂时不可用，请稍后重试", headers=NO_STORE) from exc
    return {
        "ok": True,
        "access_token": create_access_token(user.id, user.username, is_admin=bool(user.is_admin)),
        "refresh_token": create_refresh_token(user.id, user.username),
    }
