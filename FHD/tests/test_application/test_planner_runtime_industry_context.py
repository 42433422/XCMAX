from __future__ import annotations

from unittest.mock import patch

from starlette.requests import Request

from app.application.planner_compat_service import (
    _derive_industry_from_session,
    _request_session_candidates,
    _summarize_context_for_log,
)


def _request(*, cookie: str = "", authorization: str = "") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/ai/chat/stream", "headers": headers}
    )
    request.state.industry_id = "通用"
    request.state.tenant_id = None
    return request


def test_session_candidates_prefer_host_cookie_over_market_bearer() -> None:
    request = _request(
        cookie="session_id=local-host-session",
        authorization="Bearer market-access-token",
    )

    # 市场 Bearer 不再当作 host session 候选（会盖掉本地 session 租户读数）。
    assert _request_session_candidates(request) == ["local-host-session"]


def test_industry_uses_cookie_session_workspace_when_bearer_is_market_token() -> None:
    request = _request(
        cookie="session_id=local-host-session",
        authorization="Bearer market-access-token",
    )

    def _meta(session_id: str):
        if session_id == "local-host-session":
            return {
                "account_kind": "enterprise",
                "local_user_id": 2,
                "tenant_id": 1,
            }
        return None

    with (
        patch(
            "app.application.session_account_meta.load_session_account_meta",
            side_effect=_meta,
        ) as load_meta,
        patch(
            "app.application.tenant_workspace_prefs.get_workspace_prefs",
            return_value={"selected_industry_id": "考勤"},
        ) as get_prefs,
    ):
        assert _derive_industry_from_session(request) == "考勤"

    assert load_meta.call_args_list[0].args == ("local-host-session",)
    get_prefs.assert_called_once_with("tenant:1")


def test_context_log_summary_never_contains_image_payload() -> None:
    payload = "A1b2" * 4096
    context = {
        "recent_messages": [{"role": "user", "content": "看看这张图片"}],
        "multimodal_attachments": [
            {
                "kind": "image",
                "filename": "attendance.png",
                "mime_type": "image/png",
                "data_url": f"data:image/png;base64,{payload}",
            }
        ],
    }

    rendered = repr(_summarize_context_for_log(context))

    assert payload not in rendered
    assert "payload_chars=16384" in rendered
    assert "attendance.png" in rendered
    assert len(rendered) < 1000
