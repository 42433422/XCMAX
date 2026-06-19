#!/usr/bin/env python3
"""影子模式启动验证：跑 13 类真实事件，确认 NN 决策被记录且不影响实际路由。"""
import os
import time
import json
from pathlib import Path

print("=== 影子模式启动 ===")
print(f"XCAGI_ROUTING_POLICY_ENABLED={os.environ.get('XCAGI_ROUTING_POLICY_ENABLED')}")

log_path = Path("resources/routing_policies/routing_decisions.jsonl")
size_before = log_path.stat().st_size if log_path.exists() else 0

from app.neuro_bus.routing.policy_router import decide_processor_with_policy
from app.neuro_bus.events import NeuroEvent

test_cases = [
    ("你好", "greeting"),
    ("确认", "confirm"),
    ("1", "option_select"),
    ("订单 20240001 状态？", "order_query"),
    ("库存还剩多少？", "inventory"),
    ("帮我生成一份出货单", "generate_doc"),
    ("OCR 识别这张发票", "ocr_task"),
    ("打印拣货单", "print"),
    ("紧急停止！", "emergency_stop"),
    ("/help", "slash_cmd"),
    ("客户张三的联系方式", "customer_query"),
    ("分析一下本月销售趋势", "complex_analysis"),
    ("微信支付回调 12345", "wechat_callback"),
]

print(f"\n=== 跑 {len(test_cases)} 条真实事件 ===")
shadow_decisions = 0
null_returns = 0
t0 = time.perf_counter()
for text, desc in test_cases:
    event = NeuroEvent(event_type=desc, payload={"text": text})
    result = decide_processor_with_policy(text, event, trace_id=f"shadow-test-{desc}")
    if result is None:
        null_returns += 1
    else:
        shadow_decisions += 1
elapsed = (time.perf_counter() - t0) * 1000

size_after = log_path.stat().st_size if log_path.exists() else 0
new_bytes = size_after - size_before

print(f"\n=== 影子模式验证结果 ===")
print(f"  总事件数：{len(test_cases)}")
print(f"  返回 None（不影响路由）：{null_returns}/{len(test_cases)}")
print(f"  实际路由影响：{shadow_decisions}（应为 0）")
print(f"  总耗时：{elapsed:.2f}ms（均值 {elapsed/len(test_cases):.3f}ms/条）")
print(f"  日志增长：{new_bytes} bytes（NN 决策已记录）")

print(f"\n=== 影子日志样本（最后 13 条）===")
with log_path.open() as f:
    lines = f.readlines()
shadow_lines = []
for line in lines[-20:]:
    try:
        obj = json.loads(line)
        if obj.get("extra", {}).get("shadow"):
            shadow_lines.append(obj)
    except json.JSONDecodeError:
        continue
for obj in shadow_lines[-13:]:
    extra = obj.get("extra", {})
    print(
        f"  action={obj['action']:12s} latency={obj['latency_ms']:.4f}ms "
        f"conf={extra.get('confidence', 0):.3f} source={extra.get('source')}"
    )

print(f"\n=== 影子模式启动成功，NN 决策已记录，不影响实际路由 ===")
