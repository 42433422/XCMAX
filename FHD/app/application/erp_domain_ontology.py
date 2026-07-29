from __future__ import annotations

import re
from collections import Counter
from typing import Any

ERP_ONTOLOGY_VERSION = "erp_domain_ontology_v1"
ERP_ONTOLOGY_SOURCE = "ERP 领域本体"
ERP_ONTOLOGY_RETRIEVER = "erp_domain_ontology_lexical_v1"
_STRONG_ERP_TERMS = {
    "erp",
    "bom",
    "cogs",
    "grn",
    "mrp",
    "po",
    "so",
    "wip",
    "三单匹配",
    "会计",
    "会计科目",
    "供应商",
    "入库",
    "净需求",
    "出入库",
    "出库",
    "出库成本",
    "分录",
    "制造费用",
    "发票",
    "发货",
    "可用库存",
    "复式记账",
    "库存",
    "库存台账",
    "开票",
    "凭证",
    "借贷",
    "借贷必平衡",
    "成本",
    "成本卷积",
    "成本核算",
    "采购",
    "采购订单",
    "期初",
    "期末",
    "标准成本",
    "毛需求",
    "物料",
    "物料清单",
    "生产",
    "销售",
    "销售订单",
    "负库存",
    "过账",
}

_ERP_DOMAINS: list[dict[str, Any]] = [
    {
        "id": "accounting",
        "label": "财务会计",
        "summary": "以会计科目、凭证、总账、应收应付和期间结账为核心的复式记账域。",
        "keywords": ["会计", "总账", "凭证", "借贷", "复式记账", "应收", "应付", "结账"],
    },
    {
        "id": "inventory",
        "label": "库存",
        "summary": "以物料、仓库、批次、库存台账、出入库和可用量为核心的存货域。",
        "keywords": ["库存", "物料", "仓库", "批次", "出库", "入库", "台账", "可用量"],
    },
    {
        "id": "procurement",
        "label": "采购",
        "summary": "从采购申请、采购订单、收货、验收、发票匹配到应付确认的采购域。",
        "keywords": ["采购", "供应商", "采购订单", "收货", "验收", "三单匹配", "应付"],
    },
    {
        "id": "sales",
        "label": "销售",
        "summary": "从报价、销售订单、发货、开票到应收确认的销售履约域。",
        "keywords": ["销售", "报价", "销售订单", "发货", "开票", "应收", "客户"],
    },
    {
        "id": "manufacturing",
        "label": "生产计划",
        "summary": "以 BOM、工单、产能、MRP 净需求和完工入库为核心的制造域。",
        "keywords": ["BOM", "MRP", "工单", "生产", "净需求", "完工", "产能"],
    },
    {
        "id": "costing",
        "label": "成本核算",
        "summary": "以成本要素、材料、人工、制造费用、WIP 和成本结转为核心的成本域。",
        "keywords": ["成本", "成本核算", "标准成本", "移动平均", "WIP", "结转", "COGS"],
    },
]

_ERP_ENTITIES: list[dict[str, Any]] = [
    {
        "id": "accounting.account",
        "domain": "accounting",
        "label": "会计科目",
        "summary": "总账、辅助核算、余额方向和报表归集的基础分类。",
        "keywords": ["科目", "account", "总账"],
    },
    {
        "id": "accounting.journal_entry",
        "domain": "accounting",
        "label": "会计凭证",
        "summary": "已审核业务事实进入总账的复式记账载体。",
        "keywords": ["凭证", "voucher", "journal"],
    },
    {
        "id": "accounting.journal_line",
        "domain": "accounting",
        "label": "凭证明细行",
        "summary": "包含科目、借贷方向、金额、辅助核算和来源单据的原子分录。",
        "keywords": ["分录", "借方", "贷方", "明细行"],
    },
    {
        "id": "inventory.item",
        "domain": "inventory",
        "label": "物料",
        "summary": "库存、采购、销售、BOM 与成本共用的业务对象。",
        "keywords": ["物料", "产品", "SKU", "item"],
    },
    {
        "id": "inventory.stock_ledger",
        "domain": "inventory",
        "label": "库存台账",
        "summary": "按物料、仓库、批次记录库存数量和成本变动的流水账。",
        "keywords": ["库存台账", "出入库", "批次", "库存流水"],
    },
    {
        "id": "procurement.purchase_order",
        "domain": "procurement",
        "label": "采购订单",
        "summary": "供应商、物料、价格、交期、税率和收货控制的承诺单据。",
        "keywords": ["采购订单", "PO", "供应商"],
    },
    {
        "id": "procurement.goods_receipt",
        "domain": "procurement",
        "label": "采购收货",
        "summary": "采购订单履约进入库存和暂估应付的业务事件。",
        "keywords": ["收货", "入库", "GRN", "暂估应付"],
    },
    {
        "id": "sales.sales_order",
        "domain": "sales",
        "label": "销售订单",
        "summary": "客户、产品、数量、价格、交期和信用控制的履约承诺。",
        "keywords": ["销售订单", "SO", "客户", "信用"],
    },
    {
        "id": "sales.delivery",
        "domain": "sales",
        "label": "销售发货",
        "summary": "销售订单占用和发出库存，并驱动收入/成本确认的业务事件。",
        "keywords": ["发货", "出库", "delivery", "收入", "成本"],
    },
    {
        "id": "manufacturing.bom",
        "domain": "manufacturing",
        "label": "BOM",
        "summary": "成品、半成品、原料、用量、损耗和生效版本的物料结构。",
        "keywords": ["BOM", "物料清单", "用量", "损耗", "版本"],
    },
    {
        "id": "manufacturing.mrp_plan",
        "domain": "manufacturing",
        "label": "MRP 计划",
        "summary": "按需求、库存、在途、提前期和安全库存计算净需求与计划订单。",
        "keywords": ["MRP", "净需求", "计划订单", "提前期", "安全库存"],
    },
    {
        "id": "costing.cost_rollup",
        "domain": "costing",
        "label": "成本卷积",
        "summary": "沿 BOM 汇总材料、人工、制造费用和委外成本，形成标准或实际成本。",
        "keywords": ["成本卷积", "成本核算", "标准成本", "实际成本"],
    },
]

_ERP_RULES: list[dict[str, Any]] = [
    {
        "id": "accounting.double_entry_balance",
        "type": "erp_constraint",
        "domain": "accounting",
        "label": "借贷必平衡",
        "summary": "每张已过账凭证必须满足借方金额合计等于贷方金额合计，且差额为 0。",
        "expression": "forall voucher: sum(line.amount where line.side == 'debit') == sum(line.amount where line.side == 'credit')",
        "entities": ["accounting.journal_entry", "accounting.journal_line"],
        "severity": "blocking",
        "keywords": ["借贷必平衡", "复式记账", "借方", "贷方", "debit", "credit", "凭证平衡"],
    },
    {
        "id": "accounting.single_side_line",
        "type": "erp_constraint",
        "domain": "accounting",
        "label": "分录单边唯一",
        "summary": "凭证明细行必须只落在借方或贷方其中一边，并绑定有效会计科目。",
        "expression": "forall line: xor(line.side == 'debit', line.side == 'credit') and exists(line.account_id)",
        "entities": ["accounting.account", "accounting.journal_line"],
        "severity": "blocking",
        "keywords": ["分录", "借贷方向", "会计科目", "凭证明细"],
    },
    {
        "id": "accounting.posted_reversal",
        "type": "erp_rule",
        "domain": "accounting",
        "label": "已过账只能冲销",
        "summary": "已过账凭证不得静默修改；错账通过红字/反向凭证保留审计链。",
        "expression": "posted(voucher) -> immutable(voucher) and correction_method in {'reversal','red_letter'}",
        "entities": ["accounting.journal_entry"],
        "severity": "audit",
        "keywords": ["过账", "冲销", "红字", "审计链", "不可修改"],
    },
    {
        "id": "inventory.quantity_identity",
        "type": "erp_constraint",
        "domain": "inventory",
        "label": "库存数量恒等式",
        "summary": "期末库存必须等于期初库存加收入减发出，按物料、仓库、批次逐维度成立。",
        "expression": "ending_qty(item,warehouse,batch) = opening_qty + receipts - issues + adjustments",
        "entities": ["inventory.item", "inventory.stock_ledger"],
        "severity": "blocking",
        "keywords": ["库存恒等式", "库存台账", "期初", "期末", "出入库", "可用量"],
    },
    {
        "id": "inventory.no_negative_available",
        "type": "erp_constraint",
        "domain": "inventory",
        "label": "可用库存不得为负",
        "summary": "除非企业策略明确允许负库存，承诺量和出库量不得使可用库存小于 0。",
        "expression": "available_qty = on_hand_qty - allocated_qty - reserved_qty >= 0 unless policy.allow_negative_stock",
        "entities": ["inventory.item", "inventory.stock_ledger"],
        "severity": "blocking",
        "keywords": ["负库存", "可用库存", "占用", "预留", "出库"],
    },
    {
        "id": "procurement.three_way_match",
        "type": "erp_constraint",
        "domain": "procurement",
        "label": "采购三单匹配",
        "summary": "供应商发票必须在采购订单、收货数量和价格容差范围内才能确认应付。",
        "expression": "invoice.qty <= received.qty and abs(invoice.price - po.price) <= tolerance.price",
        "entities": ["procurement.purchase_order", "procurement.goods_receipt"],
        "severity": "blocking",
        "keywords": ["三单匹配", "采购订单", "收货", "发票", "价格容差", "应付"],
    },
    {
        "id": "procurement.receipt_requires_approved_po",
        "type": "erp_rule",
        "domain": "procurement",
        "label": "收货依赖已审批采购订单",
        "summary": "标准采购收货必须引用已审批、未关闭且仍有可收数量的采购订单行。",
        "expression": "goods_receipt.line -> exists(approved(po.line)) and open_qty(po.line) >= receipt.qty",
        "entities": ["procurement.purchase_order", "procurement.goods_receipt"],
        "severity": "blocking",
        "keywords": ["收货", "采购订单", "审批", "可收数量"],
    },
    {
        "id": "sales.order_to_cash_chain",
        "type": "erp_rule",
        "domain": "sales",
        "label": "订单到收款链路",
        "summary": "销售履约链必须能从销售订单追溯到发货、开票、应收和回款。",
        "expression": "sales_order -> delivery -> invoice -> accounts_receivable -> cash_receipt",
        "entities": ["sales.sales_order", "sales.delivery", "accounting.journal_entry"],
        "severity": "audit",
        "keywords": ["销售订单", "发货", "开票", "应收", "回款", "追溯"],
    },
    {
        "id": "sales.credit_limit_guard",
        "type": "erp_constraint",
        "domain": "sales",
        "label": "客户信用额度约束",
        "summary": "新增销售订单不得使客户敞口超过授信额度，除非存在审批通过的信用例外。",
        "expression": "open_ar(customer) + uninvoiced_delivery(customer) + order_amount <= credit_limit or approved_exception",
        "entities": ["sales.sales_order"],
        "severity": "blocking",
        "keywords": ["信用额度", "授信", "应收", "销售订单", "客户风险"],
    },
    {
        "id": "manufacturing.bom_acyclic",
        "type": "erp_constraint",
        "domain": "manufacturing",
        "label": "BOM 不得成环",
        "summary": "BOM 父子件关系必须是有向无环图，且用量和损耗率为非负有效数。",
        "expression": "dag(bom.parent_item -> bom.component_item) and qty_per > 0 and scrap_rate >= 0",
        "entities": ["manufacturing.bom", "inventory.item"],
        "severity": "blocking",
        "keywords": ["BOM", "成环", "父子件", "物料清单", "用量", "损耗"],
    },
    {
        "id": "manufacturing.mrp_net_requirement",
        "type": "erp_rule",
        "domain": "manufacturing",
        "label": "MRP 净需求公式",
        "summary": "MRP 按毛需求、现存量、已分配量、在途/计划收货和安全库存计算净需求。",
        "expression": "net_requirement = gross_requirement - on_hand_qty - scheduled_receipts + allocated_qty + safety_stock",
        "entities": ["manufacturing.mrp_plan", "inventory.stock_ledger", "manufacturing.bom"],
        "severity": "planning",
        "keywords": ["MRP", "净需求", "毛需求", "在途", "安全库存", "计划订单"],
    },
    {
        "id": "costing.cost_rollup_identity",
        "type": "erp_constraint",
        "domain": "costing",
        "label": "成本卷积恒等式",
        "summary": "成品成本必须能沿 BOM 分解为材料、人工、制造费用和委外成本，并与成本方法一致。",
        "expression": "finished_cost = sum(component_qty * component_cost) + labor_cost + overhead_cost + subcontract_cost",
        "entities": ["costing.cost_rollup", "manufacturing.bom", "inventory.item"],
        "severity": "blocking",
        "keywords": ["成本核算", "成本卷积", "BOM", "材料成本", "人工", "制造费用", "委外"],
    },
    {
        "id": "costing.cogs_posting_trace",
        "type": "erp_rule",
        "domain": "costing",
        "label": "出库成本可追溯",
        "summary": "销售出库生成的主营业务成本必须可追溯到成本方法、批次/层和会计分录。",
        "expression": "delivery_issue -> cost_layer -> cogs_journal_entry with amount = issued_qty * unit_cost",
        "entities": ["sales.delivery", "inventory.stock_ledger", "accounting.journal_entry"],
        "severity": "audit",
        "keywords": ["出库成本", "COGS", "主营业务成本", "批次", "成本方法", "分录"],
    },
]


def build_erp_ontology_graph(*, dataset_id: str, limit: int = 80) -> dict[str, Any]:
    dataset_key = str(dataset_id or "persy-knowledge").strip() or "persy-knowledge"
    persy_root_id = f"persy:{dataset_key}"
    ontology_root_id = "erp:ontology"
    domain_by_id = {str(row["id"]): row for row in _ERP_DOMAINS}

    nodes: list[dict[str, Any]] = [
        {
            "id": ontology_root_id,
            "label": "ERP 领域本体",
            "type": "erp_ontology",
            "summary": "会计、库存、采购、销售、BOM、MRP、成本核算的符号化业务语义层。",
            "size": 48,
            "strength": 0.96,
            "metadata": {
                "ontology_version": ERP_ONTOLOGY_VERSION,
                "domain_count": len(_ERP_DOMAINS),
                "rule_count": len(_ERP_RULES),
                "entity_count": len(_ERP_ENTITIES),
            },
        }
    ]
    edges: list[dict[str, Any]] = [
        {
            "id": f"edge:{persy_root_id}:{ontology_root_id}",
            "source": persy_root_id,
            "target": ontology_root_id,
            "type": "erp_ontology",
            "label": "领域语义",
            "weight": 0.9,
        }
    ]

    for domain in _ERP_DOMAINS:
        domain_id = str(domain["id"])
        node_id = f"erp-domain:{domain_id}"
        nodes.append(
            {
                "id": node_id,
                "label": str(domain["label"]),
                "type": "erp_domain",
                "summary": str(domain["summary"]),
                "size": 33,
                "strength": 0.82,
                "metadata": {
                    "domain": domain_id,
                    "ontology_version": ERP_ONTOLOGY_VERSION,
                    "keywords": list(domain.get("keywords") or []),
                },
            }
        )
        edges.append(
            {
                "id": f"edge:{ontology_root_id}:{node_id}",
                "source": ontology_root_id,
                "target": node_id,
                "type": "erp_domain",
                "label": "领域",
                "weight": 0.74,
            }
        )

    # Add constraints before entities so a small graph budget still exposes the rules.
    for rule in _ERP_RULES:
        domain_id = str(rule["domain"])
        node_id = f"erp-rule:{rule['id']}"
        domain = domain_by_id.get(domain_id, {})
        nodes.append(
            {
                "id": node_id,
                "label": str(rule["label"]),
                "type": str(rule.get("type") or "erp_rule"),
                "summary": _rule_summary(rule),
                "size": 31 if rule.get("type") == "erp_constraint" else 28,
                "strength": 0.9 if rule.get("type") == "erp_constraint" else 0.78,
                "metadata": {
                    "erp_ontology_id": rule["id"],
                    "erp_domain": domain_id,
                    "erp_domain_label": domain.get("label", domain_id),
                    "severity": rule.get("severity", ""),
                    "symbolic_expression": rule.get("expression", ""),
                    "ontology_version": ERP_ONTOLOGY_VERSION,
                    "keywords": list(rule.get("keywords") or []),
                },
            }
        )
        edges.append(
            {
                "id": f"edge:erp-domain:{domain_id}:{node_id}",
                "source": f"erp-domain:{domain_id}",
                "target": node_id,
                "type": "erp_rule",
                "label": "约束" if rule.get("type") == "erp_constraint" else "规则",
                "weight": 0.68,
            }
        )

    for entity in _ERP_ENTITIES:
        domain_id = str(entity["domain"])
        node_id = f"erp-entity:{entity['id']}"
        nodes.append(
            {
                "id": node_id,
                "label": str(entity["label"]),
                "type": "erp_entity",
                "summary": str(entity["summary"]),
                "size": 23,
                "strength": 0.58,
                "metadata": {
                    "erp_ontology_id": entity["id"],
                    "erp_domain": domain_id,
                    "erp_domain_label": domain_by_id.get(domain_id, {}).get("label", domain_id),
                    "ontology_version": ERP_ONTOLOGY_VERSION,
                    "keywords": list(entity.get("keywords") or []),
                },
            }
        )
        edges.append(
            {
                "id": f"edge:erp-domain:{domain_id}:{node_id}",
                "source": f"erp-domain:{domain_id}",
                "target": node_id,
                "type": "erp_entity",
                "label": "实体",
                "weight": 0.46,
            }
        )

    for rule in _ERP_RULES:
        rule_node_id = f"erp-rule:{rule['id']}"
        for entity_id in rule.get("entities") or []:
            edges.append(
                {
                    "id": f"edge:{rule_node_id}:erp-entity:{entity_id}",
                    "source": rule_node_id,
                    "target": f"erp-entity:{entity_id}",
                    "type": "erp_constrains",
                    "label": "约束对象",
                    "weight": 0.52,
                }
            )

    bounded_nodes = _bounded_nodes(nodes, limit=limit)
    node_ids = {str(node.get("id") or "") for node in bounded_nodes}
    bounded_edges = [
        edge
        for edge in edges
        if str(edge.get("source") or "") in node_ids or str(edge.get("source") or "") == persy_root_id
        if str(edge.get("target") or "") in node_ids
    ]
    categories = Counter(str(node.get("type") or "unknown") for node in bounded_nodes)
    return {
        "success": True,
        "dataset_id": dataset_key,
        "nodes": bounded_nodes,
        "edges": bounded_edges,
        "stats": {
            "erp_ontology_version": ERP_ONTOLOGY_VERSION,
            "erp_domain_count": len(_ERP_DOMAINS),
            "erp_entity_count": len(_ERP_ENTITIES),
            "erp_rule_count": sum(1 for row in _ERP_RULES if row.get("type") == "erp_rule"),
            "erp_constraint_count": sum(
                1 for row in _ERP_RULES if row.get("type") == "erp_constraint"
            ),
            "categories": dict(sorted(categories.items())),
        },
    }


def query_erp_ontology(query: str, *, top_k: int = 5) -> dict[str, Any]:
    query_text = str(query or "").strip()
    if not query_text:
        return {
            "success": False,
            "message": "query is required",
            "error_code": "erp_ontology_query_required",
            "chunks": [],
        }

    scored: list[tuple[float, dict[str, Any]]] = []
    for record in [*_ERP_RULES, *_ERP_ENTITIES, *_ERP_DOMAINS]:
        score = _score_record(query_text, record)
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda item: (item[0], item[1].get("type") == "erp_constraint"), reverse=True)
    bounded = max(1, min(int(top_k or 5), 20))
    chunks = [_record_to_chunk(record, score, idx) for idx, (score, record) in enumerate(scored[:bounded])]
    return {
        "success": True,
        "query": query_text,
        "chunks": chunks,
        "retriever": ERP_ONTOLOGY_RETRIEVER,
        "ontology_version": ERP_ONTOLOGY_VERSION,
    }


def summarize_erp_ontology_chunks(chunks: list[dict[str, Any]], *, limit: int = 3) -> str:
    parts: list[str] = []
    for chunk in chunks[: max(1, min(int(limit or 3), 5))]:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        label = str(metadata.get("erp_label") or "ERP 规则")
        expression = str(metadata.get("symbolic_expression") or "").strip()
        if expression:
            parts.append(f"{label}：{expression}")
        else:
            parts.append(f"{label}：{str(chunk.get('text') or '').strip()[:180]}")
    return "；".join(part for part in parts if part)


def merge_erp_ontology_graph(
    base_graph: dict[str, Any],
    erp_graph: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    merged = dict(base_graph)
    nodes = [dict(node) for node in base_graph.get("nodes", []) if isinstance(node, dict)]
    edges = [dict(edge) for edge in base_graph.get("edges", []) if isinstance(edge, dict)]
    node_ids = {str(node.get("id") or "") for node in nodes}
    bounded = max(20, min(int(limit or 120), 240))

    for node in erp_graph.get("nodes", []):
        if not isinstance(node, dict) or len(nodes) >= bounded:
            break
        node_id = str(node.get("id") or "")
        if node_id and node_id not in node_ids:
            nodes.append(dict(node))
            node_ids.add(node_id)

    edge_ids = {str(edge.get("id") or "") for edge in edges}
    for edge in erp_graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if (
            str(edge.get("source") or "") not in node_ids
            or str(edge.get("target") or "") not in node_ids
        ):
            continue
        edge_id = str(edge.get("id") or "")
        if edge_id and edge_id in edge_ids:
            continue
        edges.append(dict(edge))
        if edge_id:
            edge_ids.add(edge_id)

    categories = Counter(str(node.get("type") or "unknown") for node in nodes)
    stats = dict(base_graph.get("stats") or {})
    erp_stats = dict(erp_graph.get("stats") or {})
    stats.update({key: value for key, value in erp_stats.items() if key != "categories"})
    stats.update(
        {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "categories": dict(sorted(categories.items())),
        }
    )
    merged.update({"nodes": nodes, "edges": edges, "stats": stats})
    return merged


def _bounded_nodes(nodes: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    bounded = max(8, min(int(limit or 80), 160))
    return nodes[:bounded]


def _rule_summary(rule: dict[str, Any]) -> str:
    expression = str(rule.get("expression") or "").strip()
    if not expression:
        return str(rule.get("summary") or "")
    return f"{rule.get('summary')} 符号表达：{expression}"


def _record_to_chunk(record: dict[str, Any], score: float, index: int) -> dict[str, Any]:
    domain_id = str(record.get("domain") or record.get("id") or "").split(".", maxsplit=1)[0]
    domain = next((row for row in _ERP_DOMAINS if row["id"] == domain_id), {})
    label = str(record.get("label") or record.get("id") or "ERP 规则")
    expression = str(record.get("expression") or "").strip()
    text = f"{label}：{record.get('summary') or ''}"
    if expression:
        text = f"{text}\n符号表达：{expression}"
    return {
        "text": text,
        "source": ERP_ONTOLOGY_SOURCE,
        "score": round(min(1.0, max(0.0, score)), 4),
        "chunk_index": index,
        "char_start": 0,
        "char_end": len(text),
        "metadata": {
            "source": ERP_ONTOLOGY_SOURCE,
            "erp_ontology_id": record.get("id"),
            "erp_kind": record.get("type") or "erp_domain",
            "erp_label": label,
            "erp_domain": domain_id,
            "erp_domain_label": domain.get("label", domain_id),
            "severity": record.get("severity", ""),
            "symbolic_expression": expression,
            "ontology_version": ERP_ONTOLOGY_VERSION,
        },
        "source_url": f"builtin://{ERP_ONTOLOGY_VERSION}/{record.get('id')}",
    }


def _score_record(query: str, record: dict[str, Any]) -> float:
    query_lower = query.casefold()
    content = _record_search_text(record).casefold()
    score = 0.0
    strong_signal = False
    for keyword in record.get("keywords") or []:
        keyword_text = str(keyword).strip()
        if keyword_text and keyword_text.casefold() in query_lower:
            score += 0.42
            strong_signal = strong_signal or _is_strong_erp_term(keyword_text)
    for token in _query_tokens(query_lower):
        if token in content:
            score += 0.12 if len(token) <= 3 else 0.18
            strong_signal = strong_signal or _is_strong_erp_term(token)
    generic_erp_query = any(
        term in query_lower for term in ("erp", "进销存", "业财", "业务规则", "本体")
    )
    if not generic_erp_query and not strong_signal:
        return 0.0
    if generic_erp_query:
        score += 0.08
    if score > 0 and str(record.get("type") or "") == "erp_constraint":
        score += 0.06
    return min(score, 1.0)


def _record_search_text(record: dict[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in (
            record.get("id"),
            record.get("label"),
            record.get("summary"),
            record.get("expression"),
            " ".join(str(item) for item in record.get("keywords") or []),
        )
    )


def _query_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z][a-z0-9_+-]{1,40}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        tokens.add(segment)
        for size in (2, 3, 4):
            if len(segment) >= size:
                tokens.update(segment[idx : idx + size] for idx in range(len(segment) - size + 1))
    return {token for token in tokens if token.strip()}


def _is_strong_erp_term(value: str) -> bool:
    return str(value or "").strip().casefold() in _STRONG_ERP_TERMS
