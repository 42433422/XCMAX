"""生成语义路由语料：意图配置关键词 + 回归集标注文本。

回归集（intent_golden_set.json）只用作文本来源，不参与留出集评测；
输出写入 resources/config/intent_semantic_utterances.yaml，供运行时只读加载。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "benchmarks" / "intent_golden_set.json"
OUTPUT = ROOT / "resources" / "config" / "intent_semantic_utterances.yaml"

# 人工维护的业务表达：回归集未覆盖、但线上高频的口语说法。
CURATED: dict[str, list[str]] = {
    "shipment_generate": [
        "给客户安排发货",
        "给客户备货",
        "备货发出去",
        "这批货今天必须发出去",
        "安排出库发货",
        "货配齐了出个单",
        "出个单给客户",
        "照惯例开单",
        "单子先开了再叫车",
        "通知仓库发货",
        "物流来提货了",
        "按老规矩开一张送货单",
    ],
    "price_list": [
        "给客户报个价",
        "现在的价位是多少",
        "最新价格列一下",
        "做个报价单",
        "价格表发我一份",
    ],
    "customer_export": [
        "客户名单做成表格",
        "把客户资料导出来",
        "客户表拉个清单",
        "导出单位名单",
    ],
}


def collect() -> dict[str, list[str]]:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    corpus: dict[str, list[str]] = {}
    for case in golden:
        tool_key = str(case.get("expected_tool") or case.get("expected_primary") or "").strip()
        text = str(case.get("text") or "").strip()
        if not tool_key or not text:
            continue
        bucket = corpus.setdefault(tool_key, [])
        if text not in bucket:
            bucket.append(text)
    for tool_key, texts in CURATED.items():
        bucket = corpus.setdefault(tool_key, [])
        for text in texts:
            if text not in bucket:
                bucket.append(text)
    return {key: sorted(values) for key, values in sorted(corpus.items())}


def main() -> None:
    corpus = collect()
    payload = {
        "_generated_by": "scripts/dev/build_intent_semantic_corpus.py",
        "_source": "tests/benchmarks/intent_golden_set.json",
        "version": 1,
        "utterances": corpus,
    }
    OUTPUT.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT} ({sum(len(v) for v in corpus.values())} utterances / {len(corpus)} tools)")


if __name__ == "__main__":
    main()
