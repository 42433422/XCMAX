"""Pure workbook-review projections shared by HTTP and background workflows.

The API adapter supplies its existing workbook functions to preserve route-level
patch points; this module has no FastAPI, database or tenant-service imports.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

WorkbookCleaner = Callable[[bytes, str, Any], bytes]
WorkbookInspector = Callable[[bytes], dict[str, Any]]

TEST_ONLY_RESTRICTION = "仅供数据/模板测试；打印版式未验证，不得发布到企业模板库"


def build_candidate_previews(
    body: bytes,
    review: dict[str, Any],
    proposal: dict[str, Any],
    *,
    clean_workbook: WorkbookCleaner,
    inspect_workbook: WorkbookInspector,
) -> None:
    """Render each proposal from real cleaned bytes, not hidden source cells."""
    previews = []
    for candidate in proposal["candidates"]:
        cleaned = clean_workbook(body, review["sha256"], candidate["clear"])
        result = inspect_workbook(cleaned)
        previews.append(
            {
                "candidate_id": candidate["id"],
                "sha256": result["sha256"],
                "layout": result["layout"],
                "layout_truncated": result["layout_truncated"],
            }
        )
    proposal["result_previews"] = previews


def compose_usage_restrictions(
    summary: dict[str, Any], inherited: Iterable[str] = ()
) -> list[str]:
    """Preserve immutable lineage restrictions and first-occurrence ordering."""
    restrictions = list(summary.get("usage_restrictions", []))
    conversion = summary.get("conversion_receipt") or {}
    if conversion.get("purpose") == "data_template_test_only":
        restrictions.append(TEST_ONLY_RESTRICTION)
    restrictions.extend(inherited)
    return list(dict.fromkeys(restrictions))
