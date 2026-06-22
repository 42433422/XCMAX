"""employee_report_feed 单测：MODstore collab 线程/消息 → app DTO 映射、过滤、排序、降级。"""

from __future__ import annotations

import asyncio

from app.application import employee_report_feed as feed


def _reset() -> None:
    feed._DEPT_THREAD.clear()


def test_list_report_groups_maps_and_filters(monkeypatch):
    _reset()

    async def fake_get(path, **kw):
        return {
            "items": [
                {
                    "id": 5,
                    "title": "[员工交流圈] P-S 软件部 · dept=prod_software",
                    "created_at": "t1",
                    "updated_at": "t2",
                },
                {"id": 9, "title": "随便一个别的线程", "created_at": "t0"},
                {
                    "id": 7,
                    "title": "[员工交流圈] 公司大会 / 编排 · dept=company",
                    "created_at": "t3",
                    "updated_at": "t4",
                },
            ],
            "count": 3,
        }

    monkeypatch.setattr(feed, "modstore_get", fake_get)
    groups = asyncio.run(feed.list_report_groups())
    assert [g["id"] for g in groups] == ["report:prod_software", "report:company"]
    g = groups[0]
    assert g["department_key"] == "prod_software"
    assert g["read_only"] is True
    assert g["name"].endswith("工作汇报")
    assert g["last_message_at"] == "t2"
    assert feed._DEPT_THREAD["prod_software"] == 5


def test_get_report_messages_maps_dto_sorted(monkeypatch):
    _reset()

    async def fake_get(path, **kw):
        if path.endswith("/messages"):
            return {
                "items": [
                    {
                        "id": 12,
                        "sender_employee_id": "fhd-core-maintainer",
                        "content": "稍后的",
                        "created_at": "c2",
                    },
                    {
                        "id": 3,
                        "sender_employee_id": "fhd-core-maintainer",
                        "content": "更早的",
                        "created_at": "c1",
                    },
                ],
                "count": 2,
            }
        return {
            "items": [{"id": 5, "title": "[员工交流圈] P-S 软件部 · dept=prod_software"}],
            "count": 1,
        }

    monkeypatch.setattr(feed, "modstore_get", fake_get)
    profiles = {"fhd-core-maintainer": {"name": "FHD核心", "avatar": "http://a/x.png"}}
    msgs = asyncio.run(
        feed.get_report_messages(group_id="report:prod_software", limit=50, profiles=profiles)
    )
    assert [m["id"] for m in msgs] == ["3", "12"]  # 旧→新
    m = msgs[0]
    assert set(m.keys()) == {
        "id",
        "group_id",
        "role",
        "sender_id",
        "sender_name",
        "sender_avatar",
        "body",
        "created_at",
    }
    assert m["role"] == "ai"
    assert m["group_id"] == "report:prod_software"
    assert m["sender_name"] == "FHD核心"
    assert m["sender_avatar"] == "http://a/x.png"


def test_http_error_degrades_to_empty(monkeypatch):
    _reset()

    async def boom(path, **kw):
        raise RuntimeError("modstore down")

    monkeypatch.setattr(feed, "modstore_get", boom)
    assert asyncio.run(feed.list_report_groups()) == []
    assert asyncio.run(feed.get_report_messages(group_id="report:prod_software", limit=10)) == []
