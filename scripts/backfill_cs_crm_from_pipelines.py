#!/usr/bin/env python3
"""回填 pipeline JSON → crm.sqlite3（商机/报价/ERP 关联）。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill CS CRM from pipeline JSON files")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any uid fails")
    parser.add_argument("--repair", action="store_true", help="Use repair_pipeline_crm for each uid")
    parser.add_argument("--uid", type=int, default=0, help="Only process this market_user_id")
    args = parser.parse_args()

    svc = _REPO / "app" / "services"
    crm = _load_module("user_cs_crm_store_bf", svc / "user_cs_crm_store.py")
    pipe = _load_module("user_cs_pipeline_bf", svc / "user_cs_pipeline.py")
    crm_db = _REPO / "data" / "customer_service" / "crm.sqlite3"
    crm_db.parent.mkdir(parents=True, exist_ok=True)
    crm._crm_db_path = lambda: crm_db  # type: ignore[attr-defined]

    pipeline_dir = _REPO / "data" / "customer_service" / "pipeline"
    pipe._pipeline_roots = lambda: [pipeline_dir]  # type: ignore[attr-defined]
    pipe._pipeline_root = lambda: pipeline_dir  # type: ignore[attr-defined]
    pipe._pipeline_path = lambda uid: pipeline_dir / f"{int(uid)}.json"  # type: ignore[attr-defined]

    def _uids():
        if args.uid > 0:
            return [args.uid]
        out = []
        for p in sorted(pipeline_dir.glob("*.json")):
            try:
                out.append(int(p.stem))
            except ValueError:
                continue
        return out

    uids = _uids()
    ok_uids: list[int] = []
    skipped_uids: list[int] = []
    failed: list[dict] = []

    for uid in uids:
        doc = pipe.load_pipeline(uid)
        if args.repair:
            if args.dry_run:
                print(f"would repair uid={uid} stage={doc.get('stage')}")
                ok_uids.append(uid)
                continue
            try:
                doc = pipe.repair_pipeline_crm(uid, username=str(doc.get("username") or ""))
                ok_uids.append(uid)
                print(
                    json.dumps(
                        {
                            "uid": uid,
                            "stage": doc.get("stage"),
                            "crm_opportunity_id": doc.get("crm_opportunity_id"),
                            "crm_quote_id": doc.get("crm_quote_id"),
                            "erp_customer_name": doc.get("erp_customer_name"),
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception as exc:
                failed.append({"uid": uid, "error": str(exc)})
                print(f"FAIL uid={uid}: {exc}", file=sys.stderr)
            continue

        if not doc.get("intake_submitted_at") and not doc.get("intake_form"):
            skipped_uids.append(uid)
            continue
        if doc.get("crm_opportunity_id") and doc.get("crm_quote_id"):
            skipped_uids.append(uid)
            continue
        if args.dry_run:
            print(f"would backfill uid={uid} stage={doc.get('stage')}")
            ok_uids.append(uid)
            continue
        try:
            doc = crm.sync_crm_from_pipeline_doc(doc, raise_on_failure=True)
            stage = str(doc.get("stage") or "idle")
            if pipe._stage_requires_quote(stage) and not doc.get("crm_quote_id"):
                doc["stage"] = "quoted" if pipe._stage_rank(stage) < pipe._stage_rank("quoted") else stage
                doc = crm.sync_crm_from_pipeline_doc(doc, raise_on_failure=True)
            path = pipeline_dir / f"{uid}.json"
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            ok_uids.append(uid)
            print(
                json.dumps(
                    {
                        "uid": uid,
                        "stage": doc.get("stage"),
                        "crm_opportunity_id": doc.get("crm_opportunity_id"),
                        "crm_quote_id": doc.get("crm_quote_id"),
                        "erp_customer_name": doc.get("erp_customer_name"),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            failed.append({"uid": uid, "error": str(exc)})
            print(f"FAIL uid={uid}: {exc}", file=sys.stderr)

    summary = {
        "ok": len(ok_uids),
        "skipped": len(skipped_uids),
        "failed": len(failed),
        "ok_uids": ok_uids,
        "skipped_uids": skipped_uids,
        "failed_uids": [f["uid"] for f in failed],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.strict and failed:
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
