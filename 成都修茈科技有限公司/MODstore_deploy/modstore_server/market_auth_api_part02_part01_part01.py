# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.market_auth_api_part01_part01_part02 import (
    AdminResetUserPasswordDTO,
)
from modstore_server.market_auth_api_part01_part01_part02 import LoginDTO
from modstore_server.market_auth_api_part01_part01_part02 import LoginWithCodeDTO
from modstore_server.market_auth_api_part01_part01_part02 import PasswordChangeDTO
from modstore_server.market_auth_api_part01_part01_part02 import ProfileUpdateDTO
from modstore_server.market_auth_api_part01_part01_part02 import RegisterDTO
from modstore_server.market_auth_api_part01_part01_part02 import ResetPasswordDTO
from modstore_server.market_auth_api_part01_part01_part02 import SendCodeDTO


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


class InternalSsoIssueTokenDTO(_facade().BaseModel):
    username: str = _facade().Field(default="", max_length=128)
    email: str = _facade().Field(default="", max_length=256)
    oidc_sub: str = _facade().Field(default="", max_length=256)
    display_name: str = _facade().Field(default="", max_length=128)


@_facade().router.post("/auth/internal/sso-issue-token", include_in_schema=False)
def api_internal_sso_issue_token(body: InternalSsoIssueTokenDTO, request: _facade().Request):
    """FHD OIDC 回调后签发 MODstore JWT（Header: X-Internal-Api-Key）。"""
    _facade()._require_internal_api_key(request)
    from modstore_server.auth_service import issue_market_tokens_for_sso_identity

    try:
        data = issue_market_tokens_for_sso_identity(
            username=(body.username or "").strip(),
            email=(body.email or "").strip(),
            oidc_sub=(body.oidc_sub or "").strip(),
            display_name=(body.display_name or "").strip(),
        )
    except ValueError as exc:
        raise _facade().HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "data": data}


@_facade().router.post("/auth/avatar", summary="上传或更换当前用户头像")
async def api_upload_avatar(
    file: _facade().UploadFile = _facade().File(...),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    payload = await file.read()
    relpath, _mime = _facade().save_user_avatar(
        int(user.id), payload, file.filename or "avatar.jpg"
    )
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.avatar_path = relpath
        row.avatar_version = int(getattr(row, "avatar_version", 0) or 0) + 1
        session.commit()
        version = int(row.avatar_version)
        url = _facade().public_avatar_url_for_user(row)
    return {"ok": True, "avatar_url": url, "avatar_version": version}


@_facade().router.delete("/auth/avatar", summary="移除当前用户头像")
def api_delete_avatar(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    _facade().delete_user_avatar_files(int(user.id))
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.avatar_path = ""
        row.avatar_version = int(getattr(row, "avatar_version", 0) or 0) + 1
        session.commit()
    return {"ok": True, "avatar_url": None}


@_facade().router.get("/auth/avatar/file", summary="读取当前用户头像（需登录）")
def api_avatar_file(
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
    v: _facade()
    .Optional[int] = _facade()
    .Query(None, description="与 avatar_url 中 v 一致，仅用于缓存校验"),
):
    rel = _facade().avatar_path_column(user)
    if not rel:
        raise _facade().HTTPException(404, "未设置头像")
    if v is not None and int(v) != _facade().avatar_version_column(user):
        raise _facade().HTTPException(404, "头像已更新，请刷新")
    path = _facade().resolve_avatar_file(rel)
    if not path.is_file():
        raise _facade().HTTPException(404, "头像文件不存在")
    suffix = path.suffix.lower()
    media = _facade()._MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    return _facade().FileResponse(path, media_type=media, filename=f"avatar{suffix}")
