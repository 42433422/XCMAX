"""WO-18443017efd5 复现件：客户缺陷上报必须拿到工单编号。

客户原问题（WO context）：
  expected = 自动采集脱敏支持包、创建唯一 Work Order，并返回工单编号和 Owner 受理状态
  actual   = 原测试会话只收到无法接入问题受理的答复，没有工单编号

复现判据：聊天路径必须存在「客户缺陷 → 工单受理」分支，且回执文案包含
Work Order 编号与市场工单号。修复前该分支不存在，缺陷上报会被员工/业务工具
分支消费掉，客户拿不到任何编号 —— 本用例在修复前必须以断言失败结束（RED）。
"""

from __future__ import annotations

import importlib

_MODULE = "app.fastapi_routes.xcagi_compat_chat_stream"


def test_client_defect_report_returns_work_order_receipt():
    mod = importlib.import_module(_MODULE)

    submit = getattr(mod, "_classify_and_submit_client_issue", None)
    assert submit is not None, (
        "聊天路径缺少客户缺陷受理分支：产品缺陷上报不会建单，客户拿不到工单编号"
    )

    reply_for = getattr(mod, "_client_issue_reply", None)
    assert reply_for is not None, "缺少工单编号回执文案构造器"

    text = reply_for(
        {
            "state": "ROUTED",
            "work_order_id": "WO-18443017efd5",
            "owner_ticket_no": "CI5a10d66d11e4d49777fccc2af13235a88df742fa3c82bf97",
            "support_bundle_sha256": "aa689a0d5c19824d979efddf0863a68db6df373e06fb5695bf5ef982cd56732b",
        }
    )
    assert "WO-18443017efd5" in text, "回执必须包含 Work Order 编号"
    assert "CI5a10" in text, "回执必须包含市场工单号"