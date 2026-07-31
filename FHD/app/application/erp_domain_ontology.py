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

from app.application.erp_domain_ontology_data import (
    ERP_DOMAINS as _ERP_DOMAINS,
    ERP_ENTITIES as _ERP_ENTITIES,
    ERP_RULES as _ERP_RULES,
)


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
        if str(edge.get("source") or "") in node_ids
        or str(edge.get("source") or "") == persy_root_id
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
    chunks = [
        _record_to_chunk(record, score, idx) for idx, (score, record) in enumerate(scored[:bounded])
    ]
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
