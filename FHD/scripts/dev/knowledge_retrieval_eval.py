#!/usr/bin/env python3
"""知识库检索质量评测：recall@k / MRR，自带中文小样本，可重复运行。

用法（在 FHD/ 下）::

    .venv/bin/python scripts/dev/knowledge_retrieval_eval.py
    FHD_EMBEDDING_MODE=local .venv/bin/python scripts/dev/knowledge_retrieval_eval.py
    FHD_RERANK_ENABLED=1 .venv/bin/python scripts/dev/knowledge_retrieval_eval.py --rerank

默认使用当前进程的 embedding 配置；未配置时是 hash 降级，指标只代表降级基线。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

DOCS: list[dict[str, str]] = [
    {
        "id": "refund-policy",
        "text": "退款政策：客户在签收后七天内可申请无理由退款，超过七天需提供质量问题证明。"
        "退款审批由财务负责人确认，原路退回，三到五个工作日到账。",
    },
    {
        "id": "install-guide",
        "text": "桌面安装指南：Windows 下载安装包后双击运行，macOS 拖入应用程序目录。"
        "安装完成后首次登录需要输入企业账号，安装回执会自动上报到管理端。",
    },
    {
        "id": "invoice-rules",
        "text": "开票规则：增值税专用发票需要客户提供税号、开户行和地址。"
        "普通发票可在订单详情页自助申请，电子发票一个工作日内发送到预留邮箱。",
    },
    {
        "id": "attendance",
        "text": "考勤制度：上班时间九点到十八点，迟到超过三十分钟按半天事假处理。"
        "外勤打卡需要在企业微信提交定位，补卡每月最多三次。",
    },
    {
        "id": "delivery",
        "text": "交付流程：企业客户下单后由交付中心分配安装任务，"
        "客户完成首次登录视为交付完成，未安装的订单进入待安装队列。",
    },
    {
        "id": "permissions",
        "text": "权限说明：管理员可以分配模块和员工包，普通成员只能访问被授权的业务页面。"
        "越权访问会被审计日志记录并拒绝。",
    },
    {
        "id": "backup",
        "text": "数据备份：系统每天凌晨三点自动备份数据库，保留最近十四天。"
        "恢复演练每季度一次，备份文件加密存储。",
    },
    {
        "id": "model-config",
        "text": "模型配置：平台模型需要在管理端填写供应商、接口地址和密钥，"
        "保存后立即生效；BYOK 密钥加密存储，不在前端展示明文。",
    },
    {
        "id": "approval",
        "text": "审批规则：涉及金额超过五万元的采购需要两级审批，"
        "审批人依次为部门负责人和财务负责人，超时三天自动提醒。",
    },
    {
        "id": "export",
        "text": "数据导出：订单和客户列表支持导出 Excel，导出任务异步执行，"
        "完成后在消息中心下载，文件保留七天。",
    },
]

QUERIES: list[dict[str, object]] = [
    {"q": "客户想退款，几天内可以无理由退？", "expected": "refund-policy"},
    {"q": "Mac 怎么安装客户端？", "expected": "install-guide"},
    {"q": "开增值税专用发票要什么资料？", "expected": "invoice-rules"},
    {"q": "迟到半小时怎么算？", "expected": "attendance"},
    {"q": "客户一直没安装，订单算交付完成吗？", "expected": "delivery"},
    {"q": "普通员工能看哪些页面？", "expected": "permissions"},
    {"q": "数据库多久备份一次？", "expected": "backup"},
    {"q": "平台模型的密钥在哪里配置？", "expected": "model-config"},
    {"q": "五万以上的采购要谁审批？", "expected": "approval"},
    {"q": "订单导出成 Excel 在哪里下载？", "expected": "export"},
]


def _build_service(storage: Path):
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    return DatasetRagApplicationService(
        storage_path=storage,
        rebuild_workers_enabled=False,
    )


def run(*, rerank: bool) -> dict[str, float]:
    from app.infrastructure.llm.embedding_service import get_default_embedding_service

    svc = get_default_embedding_service()
    mode = svc.mode if svc else "disabled"
    with tempfile.TemporaryDirectory(prefix="kb-eval-") as tmp:
        service = _build_service(Path(tmp) / "datasets")
        for doc in DOCS:
            service.ingest_document(
                dataset_id="eval",
                document_id=doc["id"],
                source=doc["id"],
                text=doc["text"],
                chunk_strategy="fixed",
                chunk_size=200,
                chunk_overlap=20,
            )
        hits_at = {1: 0, 3: 0, 5: 0}
        reciprocal = 0.0
        for item in QUERIES:
            result = service.query(
                dataset_id="eval",
                query=str(item["q"]),
                top_k=5,
                rerank=rerank,
            )
            doc_ids = [
                str((chunk.get("metadata") or {}).get("document_id") or "")
                for chunk in result.get("chunks") or []
            ]
            expected = str(item["expected"])
            rank = next((idx for idx, doc_id in enumerate(doc_ids, 1) if doc_id == expected), 0)
            for k in hits_at:
                if rank and rank <= k:
                    hits_at[k] += 1
            reciprocal += 1.0 / rank if rank else 0.0
        total = len(QUERIES)
        return {
            "embedding_mode": mode,
            "queries": total,
            "recall@1": round(hits_at[1] / total, 4),
            "recall@3": round(hits_at[3] / total, 4),
            "recall@5": round(hits_at[5] / total, 4),
            "mrr": round(reciprocal / total, 4),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank", action="store_true", help="启用精排（需 FHD_RERANK_* 配置）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()
    metrics = run(rerank=args.rerank)
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False))
    else:
        print("知识库检索评测（10 条中文查询）")
        for key, value in metrics.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
