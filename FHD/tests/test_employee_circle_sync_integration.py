"""Live 集成测试：FHD 同步真实 MODstore 汇报流 → ai_circle 动态。

默认 **skip**；当 ``E2E_LIVE=1`` 且 MODstore 可达（``MODSTORE_LOCAL_BASE_URL``，默认
``http://127.0.0.1:8788``，其 collab feed 已有 ``employee_collab_reporter`` 写入的部门汇报线程）时运行。

复跑示例（在能起真 MODstore 的开发机上）：

    E2E_LIVE=1 \\
    MODSTORE_LOCAL_BASE_URL=http://127.0.0.1:8788 \\
    DATABASE_URL=sqlite:////tmp/e2e_fhd.db \\
    PYTHONPATH=FHD FHD/.venv/bin/python -m pytest \\
      FHD/tests/test_employee_circle_sync_integration.py -q
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_LIVE"),
    reason="live 集成测试：设 E2E_LIVE=1 且 MODstore 可达时运行",
)


def test_sync_real_modstore_reports_to_circle():
    from app.application import ai_circle_service
    from app.application import employee_circle_sync as sync

    out1 = asyncio.run(sync.sync_modstore_reports(force=True))
    assert out1.get("ok"), out1

    posts = ai_circle_service.list_posts(user_id=1, limit=100)
    loop_posts = [p for p in posts if p.get("source_type") == "loop_report"]
    assert loop_posts, "未投影出 loop_report 动态——确认 MODstore collab feed 已有汇报数据"
    assert all(p["author_kind"] == "employee" for p in loop_posts)
    assert all(p.get("employee_id") for p in loop_posts)

    # 幂等：同库重跑不应新增
    out2 = asyncio.run(sync.sync_modstore_reports(force=True))
    assert out2.get("synced") == 0, out2
