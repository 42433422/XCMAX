"""真实登录会话的多轮语义验收（手动触发，不进 CI）。

运行条件（缺一即 skip）：
- ``XCAGI_ACCEPTANCE_LLM=1``
- ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` / ``OPENAI_MODEL`` 指向可用模型

命令示例（在 FHD/ 下）：
    XCAGI_ACCEPTANCE_LLM=1 XCAGI_PRODUCT_SKU=enterprise \
    OPENAI_API_KEY=... OPENAI_BASE_URL=https://api.minimax.chat/v1 \
    OPENAI_MODEL=MiniMax-M3.1-Flash LLM_PROVIDER=openai \
    .venv/bin/python -m pytest tests/acceptance/test_semantic_multiturn_acceptance.py -q -s

验收内容：
1. 写入意图命中多候选时返回非空 candidates；
2. 用户回复“就第二个”后不再重复询问，而是进入选中候选后的执行/审批路径；
3. 不再是“业务结果暂时无法核实”的未知态。
"""

from __future__ import annotations

import os

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

pytestmark = pytest.mark.skipif(
    os.environ.get("XCAGI_ACCEPTANCE_LLM") != "1" or not os.environ.get("OPENAI_API_KEY"),
    reason="semantic acceptance requires XCAGI_ACCEPTANCE_LLM=1 and model credentials",
)


def test_ambiguous_write_returns_candidates_and_accepts_ordinal(trusted_actor, monkeypatch) -> None:
    from app.application import get_ai_chat_app_service
    from app.db.models import Product
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(role="admin")
    with tenant_scope(7), actor.factory.begin() as db:
        db.add_all(
            [
                Product(tenant_id=7, name="甲型涂料", model_number="A1", price=10),
                Product(tenant_id=7, name="乙型涂料", model_number="A1", price=20),
            ]
        )

    svc = get_ai_chat_app_service()
    found = False
    for attempt in range(1, 6):
        session_id = f"acceptance-s2-{actor.session_id}-{attempt}"
        context = {
            **actor.context,
            "session_id": session_id,
            "conversation_id": session_id,
            "turn_id": f"{session_id}:t1",
        }
        first = svc.process_chat(
            user_id=str(actor.user_id),
            message="把产品 A1 的价格改成 99 元",
            context=context,
            source="normal",
        )
        data = first.get("data") if isinstance(first.get("data"), dict) else {}
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        candidates = inner.get("candidates") or []
        if not candidates:
            continue
        found = True
        assert all(candidate.get("id") for candidate in candidates)

        second = svc.process_chat(
            user_id=str(actor.user_id),
            message="就第二个",
            context={**context, "turn_id": f"{session_id}:t2"},
            source="normal",
        )
        second_data = second.get("data") if isinstance(second.get("data"), dict) else {}
        assert "我还不能安全确定答案" not in str(second.get("response") or "")
        assert second_data.get("action") != "workflow_failed", str(second.get("response"))[:200]
        break
    assert found, "模型在 5 次尝试内未产出多候选写入计划"


@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
def test_full_multiturn_scenarios_report(trusted_actor, monkeypatch) -> None:
    """S1-S5 全量报告（真实会话 + 企业 SKU）；只记录结果，不做全量硬断言。"""
    from app.application import get_ai_chat_app_service
    from app.db.models import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(role="admin")
    scenarios = [
        ("S1-追问继承", ["帮我查一下客户张三的资料", "那他的订单呢"]),
        ("S2-候选澄清", ["把产品 A1 的价格改成 99 元", "就第二个"]),
        ("S3-参数补充", ["我要生成一张发货单", "300kg 的 A 型产品，发给王五"]),
        ("S4-否定纠正", ["把产品型号 B2 的价格改成 88 元", "不是第一个，是第二个"]),
        ("S5-重复执行", ["查一下今天有哪些新客户", "再来一遍"]),
    ]
    with tenant_scope(7), actor.factory.begin() as db:
        db.add(PurchaseUnit(tenant_id=7, unit_name="张三"))
        db.add_all(
            [
                Product(tenant_id=7, name="甲型涂料", model_number="A1", price=10),
                Product(tenant_id=7, name="乙型涂料", model_number="A1", price=20),
                Product(tenant_id=7, name="丙型涂料", model_number="B2", price=30),
                Product(tenant_id=7, name="丁型涂料", model_number="B2", price=40),
            ]
        )

    svc = get_ai_chat_app_service()
    rows: list[dict[str, object]] = []
    for label, messages in scenarios:
        session_id = f"acceptance-{actor.session_id}-{label}"
        for index, message in enumerate(messages, start=1):
            context = {
                **actor.context,
                "session_id": session_id,
                "conversation_id": session_id,
                "turn_id": f"{session_id}:t{index}",
            }
            response = svc.process_chat(
                user_id=str(actor.user_id), message=message, context=context, source="normal"
            )
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            inner = data.get("data") if isinstance(data.get("data"), dict) else {}
            row = {
                "scenario": label,
                "turn": index,
                "message": message,
                "success": bool(response.get("success")),
                "action": data.get("action"),
                "candidates": len(inner.get("candidates") or []),
                "excerpt": str(response.get("response") or "")[:120].replace("\n", " "),
            }
            rows.append(row)
            print("ACCEPTANCE", row, flush=True)
    assert rows, "未产生验收记录"
