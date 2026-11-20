from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.application import client_product_issue_intake as ticket_status


@pytest.mark.asyncio
async def test_ticket_status_reads_exact_account_and_number(monkeypatch):
    number = "CI" + "ab" * 24
    remote = AsyncMock(
        return_value={
            "items": [
                {"ticket_no": number, "user_id": 999, "lifecycle_label": "已完成"},
                {"ticket_no": number + "0", "user_id": 501, "lifecycle_label": "已完成"},
                {"ticket_no": number, "user_id": 501, "lifecycle_label": "处理中"},
            ]
        }
    )
    monkeypatch.setattr(ticket_status, "custom_delivery_remote_json", remote)

    reply = await ticket_status.reply_to_ticket_status_request(
        f"在 macOS 上查一下工单 {number.lower()} 的进度",
        market_user_id=501,
        market_token="owner-token",
    )

    assert reply and number in reply and "处理中" in reply and "已完成" not in reply
    remote.assert_awaited_once()
    token, path = remote.await_args.args
    assert token == "owner-token"
    assert urlsplit(path).path == "/api/customer-service/tickets"
    assert parse_qs(urlsplit(path).query) == {
        "search": [number],
        "account_id": ["501"],
        "limit": ["10"],
    }
    assert remote.await_args.kwargs == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", ["010066", "010066号工单解决了吗？", "工单 010066", "工单编号：010066"]
)
async def test_ticket_status_does_not_report_an_expired_ticket_as_completed(monkeypatch, body):
    remote = AsyncMock(
        return_value={
            "items": [
                {
                    "ticket_no": "010066",
                    "user_id": 501,
                    "status": "expired",
                    "lifecycle_label": "已完成",
                },
            ]
        }
    )
    monkeypatch.setattr(ticket_status, "custom_delivery_remote_json", remote)

    reply = await ticket_status.reply_to_ticket_status_request(
        body, market_user_id=501, market_token="owner-token"
    )

    assert reply and "已过期不再处理" in reply and "已完成" not in reply


@pytest.mark.asyncio
async def test_ticket_status_handles_unavailable_upstream(monkeypatch):
    remote = AsyncMock(side_effect=ConnectionError("internal service error"))
    monkeypatch.setattr(ticket_status, "custom_delivery_remote_json", remote)

    reply = await ticket_status.reply_to_ticket_status_request(
        "工单 CS-20261016-290063 状态", market_user_id=501, market_token="owner-token"
    )

    assert reply == "工单状态暂时无法核对，请稍后查询或打开原工单查看。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "owner", "token", "expected"),
    [
        ("工单状态查询按钮没反应，请登记故障", 501, "owner-token", None),
        ("帮我查工单", 501, "owner-token", "完整工单编号"),
        ("查工单 010066", 501, "", "重新登录"),
    ],
)
async def test_ticket_status_requires_explicit_query_and_owner(
    monkeypatch, body, owner, token, expected
):
    remote = AsyncMock()
    monkeypatch.setattr(ticket_status, "custom_delivery_remote_json", remote)

    reply = await ticket_status.reply_to_ticket_status_request(
        body, market_user_id=owner, market_token=token
    )

    if expected is None:
        assert reply is None
    else:
        assert reply and expected in reply
    remote.assert_not_awaited()
