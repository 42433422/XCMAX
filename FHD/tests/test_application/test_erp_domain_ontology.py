from __future__ import annotations

from app.application.erp_domain_ontology import (
    ERP_ONTOLOGY_VERSION,
    build_erp_ontology_graph,
    merge_erp_ontology_graph,
    query_erp_ontology,
    summarize_erp_ontology_chunks,
)


def test_erp_ontology_query_returns_symbolic_double_entry_constraint() -> None:
    result = query_erp_ontology("复式记账里借贷必平衡怎么校验？", top_k=3)

    assert result["success"] is True
    first = result["chunks"][0]
    assert first["metadata"]["erp_ontology_id"] == "accounting.double_entry_balance"
    assert first["metadata"]["erp_kind"] == "erp_constraint"
    assert "sum(line.amount" in first["metadata"]["symbolic_expression"]
    assert "借贷必平衡" in summarize_erp_ontology_chunks(result["chunks"])


def test_erp_ontology_query_does_not_pollute_unrelated_questions() -> None:
    result = query_erp_ontology("客户北辰科技负责人是谁？", top_k=3)

    assert result["success"] is True
    assert result["chunks"] == []


def test_erp_ontology_graph_projects_domains_rules_and_entities() -> None:
    graph = build_erp_ontology_graph(dataset_id="persy-knowledge", limit=80)

    node_ids = {node["id"] for node in graph["nodes"]}
    assert "erp:ontology" in node_ids
    assert "erp-domain:accounting" in node_ids
    assert "erp-rule:accounting.double_entry_balance" in node_ids
    assert "erp-entity:manufacturing.bom" in node_ids
    assert graph["stats"]["erp_ontology_version"] == ERP_ONTOLOGY_VERSION
    assert graph["stats"]["erp_constraint_count"] >= 6
    assert any(edge["label"] == "领域语义" for edge in graph["edges"])


def test_merge_erp_ontology_graph_preserves_base_and_updates_stats() -> None:
    base = {
        "success": True,
        "dataset_id": "persy-knowledge",
        "nodes": [{"id": "persy:persy-knowledge", "label": "Persy", "type": "core"}],
        "edges": [],
        "stats": {"document_count": 0},
    }
    erp = build_erp_ontology_graph(dataset_id="persy-knowledge", limit=32)

    merged = merge_erp_ontology_graph(base, erp, limit=40)

    assert any(node["type"] == "erp_constraint" for node in merged["nodes"])
    assert any(edge["type"] == "erp_ontology" for edge in merged["edges"])
    assert merged["stats"]["document_count"] == 0
    assert merged["stats"]["erp_rule_count"] >= 1
    assert merged["stats"]["categories"]["core"] == 1
