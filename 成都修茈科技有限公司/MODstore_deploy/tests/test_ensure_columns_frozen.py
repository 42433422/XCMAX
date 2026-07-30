"""Freeze MODstore ``_ensure_columns`` patch surface (schema second head may only shrink)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parents[1] / "modstore_server" / "db" / "base.py"

_ADD_COLUMN_COL_RE = re.compile(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)

# ONLY-SHRINK: new columns must arrive via ORM model + intentional migration path,
# not by growing this runtime patch list.
FROZEN_ENSURE_PATCHES = frozenset(
    {
        ("workflows", "migration_status"),
        ("workflows", "migrated_to_id"),
        ("workflows", "kind"),
        ("users", "is_enterprise"),
        ("daily_digest_records", "vibe_prep_updates_md"),
        ("daily_digest_records", "vibe_prep_patches_md"),
        ("daily_digest_records", "vibe_prep_meta_json"),
        ("daily_digest_records", "vibe_prep_pw_md"),
        ("daily_digest_records", "vibe_prep_ps_md"),
        ("daily_digest_records", "vibe_prep_app_md"),
        ("daily_digest_records", "vibe_prep_sr_md"),
        ("daily_digest_records", "vibe_prep_line_dispatch_json"),
        ("daily_digest_records", "vibe_line_execute_json"),
        ("daily_digest_records", "release_train_before"),
        ("daily_digest_records", "release_train_after"),
        ("daily_digest_records", "release_kind"),
        ("transactions", "idempotency_key"),
        ("employee_execution_metrics", "failure_kind"),
        ("event_outbox_dlq", "resolution_status"),
        ("event_outbox_dlq", "resolution_action"),
        ("event_outbox_dlq", "resolution_note"),
        ("event_outbox_dlq", "resolved_at"),
        ("event_outbox_dlq", "last_reconciled_at"),
        ("event_outbox_dlq", "replay_outbox_id"),
        ("ai_model_prices", "official_input_price_per_1k"),
        ("ai_model_prices", "official_output_price_per_1k"),
        ("ai_model_prices", "official_min_charge"),
        ("ai_model_prices", "official_source"),
        ("ai_model_prices", "official_synced_at"),
    }
)


def _patches_from_source(source: str) -> set[tuple[str, str]]:
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_ensure_columns"
        ):
            patches: set[tuple[str, str]] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Tuple) and len(sub.elts) >= 2:
                    t0, t1 = sub.elts[0], sub.elts[1]
                    if (
                        isinstance(t0, ast.Constant)
                        and isinstance(t0.value, str)
                        and isinstance(t1, ast.Constant)
                        and isinstance(t1.value, str)
                    ):
                        patches.add((t0.value, t1.value))
            return patches
    raise AssertionError("_ensure_columns not found in modstore_server/db/base.py")


def test_modstore_ensure_columns_frozen() -> None:
    source = BASE_PATH.read_text(encoding="utf-8")
    live = _patches_from_source(source)
    grew = sorted(live - FROZEN_ENSURE_PATCHES)
    assert not grew, (
        "modstore _ensure_columns grew schema second head with new patches: "
        f"{grew}. Route new columns through ORM models; only shrink this freeze set."
    )


def test_modstore_ensure_columns_no_raw_add_column_outside_helper() -> None:
    """Guard against a parallel ADD COLUMN path outside the frozen list."""
    source = BASE_PATH.read_text(encoding="utf-8")
    # The helper uses ALTER via _add_column_if_missing; raw ADD COLUMN strings
    # outside that helper would be a second head.
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in {"_ensure_columns", "_add_column_if_missing"}:
            continue
        segment = ast.get_source_segment(source, node) or ""
        if _ADD_COLUMN_COL_RE.search(segment):
            offenders.append(node.name)
    assert not offenders, f"unexpected ADD COLUMN callsites in db/base.py: {offenders}"
