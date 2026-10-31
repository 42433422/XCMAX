"""Tenant-scoped classification persistence and optimistic version checks."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import update

from app.application.elt.errors import ReviewedExcelError
from app.application.elt.service_support import dump_json
from app.db.models.elt import EltRun

_CLASS_READY = "classification_ready"


def _classification_run(db, classification_id, tenant, owner):
    run = (
        db.query(EltRun)
        .filter(
            EltRun.id == classification_id,
            EltRun.tenant_id == tenant,
            EltRun.owner_user_id == owner,
            EltRun.target_type == "template_classification",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="分类记录不存在")
    return run


def _classification_version(source_sha, parent, payload):
    return hashlib.sha256(
        dump_json({"source": source_sha, "parent": parent, "payload": payload}).encode()
    ).hexdigest()


def _confirmed_documents(source_sha, version, sheets, links, selected, source_cells):
    """Bind user-selected candidate edges to immutable source and classification versions."""
    if not isinstance(selected, list) or len(selected) > 200:
        raise ReviewedExcelError("片段关联选择无效")
    candidates = {
        (link["sheet"], link["first"], link["second"]): link for link in links.get("items", [])
    }
    regions = {
        (sheet["sheet"], region["range"]): region for sheet in sheets for region in sheet["regions"]
    }
    edges = set()
    for entry in selected:
        if not isinstance(entry, dict) or set(entry) != {"sheet", "first", "second"}:
            raise ReviewedExcelError("片段关联格式无效")
        key = (entry["sheet"], entry["first"], entry["second"])
        link = candidates.get(key)
        if not link or link.get("status") != "candidate" or key in edges:
            raise ReviewedExcelError("片段关联已失效或身份冲突")
        nodes = [(key[0], key[1]), (key[0], key[2])]
        if any(node not in regions or "unknown" in regions[node]["labels"] for node in nodes):
            raise ReviewedExcelError("未知或不存在的片段不能合并")
        edges.add(key)
    groups = []
    while edges:
        sheet, first, second = edges.pop()
        nodes = {(sheet, first), (sheet, second)}
        changed = True
        while changed:
            changed = False
            for edge in list(edges):
                ends = {(edge[0], edge[1]), (edge[0], edge[2])}
                if nodes & ends:
                    nodes |= ends
                    edges.remove(edge)
                    changed = True
        for link in candidates.values():
            if (
                link.get("status") == "identity_conflict"
                and {(link["sheet"], link["first"]), (link["sheet"], link["second"])} <= nodes
            ):
                raise ReviewedExcelError("关联片段包含身份冲突，不能合并")
        if len(nodes) > 20:
            raise ReviewedExcelError("单个逻辑文档最多关联20个片段")
        from app.application.reviewed_excel_evidence import candidate_fragment_links

        comparable = [
            {**regions[node], "sheet": node[0], "dependencies": [{"sheet": node[0], "cell": "A1"}]}
            for node in sorted(nodes)
        ]
        if any(
            link["status"] == "identity_conflict"
            for link in candidate_fragment_links(comparable, source_cells)["items"]
        ):
            raise ReviewedExcelError("关联片段包含身份冲突，不能合并")
        fragments = [{"sheet": sheet, "range": area} for sheet, area in sorted(nodes)]
        group_id = _classification_version(source_sha, version, fragments)
        groups.append(
            {
                "logical_document_id": group_id,
                "source_sha256": source_sha,
                "classification_version": version,
                "fragments": fragments,
                "status": "user_confirmed",
            }
        )
    return sorted(groups, key=lambda group: group["logical_document_id"])


def _confirmed_document_count(review, latest, groups, independent_confirmed):
    """Count only after full coverage and explicit treatment of ungrouped regions."""
    from openpyxl.utils.cell import (
        column_index_from_string,
        coordinate_from_string,
        range_boundaries,
    )

    if not independent_confirmed or latest.get("model_status") != "returned":
        return None
    coverage = latest.get("coverage", [])
    if len(coverage) != len(review["sheets"]) or any(
        item["unread"] or item["unassigned"] or item.get("merged_omitted") for item in coverage
    ):
        return None
    populated = set()
    for sheet in latest["sheets"]:
        for region in sheet["regions"]:
            c1, r1, c2, r2 = range_boundaries(region["range"])
            for cell in review["cells"]:
                if cell["sheet"] != sheet["sheet"]:
                    continue
                col, row = coordinate_from_string(cell["cell"])
                if c1 <= column_index_from_string(col) <= c2 and r1 <= row <= r2:
                    if "unknown" in region["labels"]:
                        return None
                    populated.add((sheet["sheet"], region["range"]))
                    break
    grouped = {(part["sheet"], part["range"]) for group in groups for part in group["fragments"]}
    return len(groups) + len(populated - grouped)


def _classification_cas(db, run, old_draft, state):
    result = db.execute(
        update(EltRun)
        .where(
            EltRun.id == run.id,
            EltRun.tenant_id == run.tenant_id,
            EltRun.owner_user_id == run.owner_user_id,
            EltRun.status == _CLASS_READY,
            EltRun.draft_json == old_draft,
        )
        .values(draft_json=dump_json(state))
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
    db.commit()
