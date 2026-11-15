"""Reviewed Excel template routes: analysis_body."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


async def _reviewed_excel_classification_analyze_body(
    classification_id, request, version, auto_group, tenant, owner, model_session
):
    try:
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            run = app_gateway._classification_run(db, classification_id, tenant, owner)
            old = run.draft_json
            state = app_gateway.load_json(old, {})
            versions = state.get("versions", [])
            if not versions or versions[-1].get("version") != version:
                raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
            from app.application.reviewed_excel_audit import normalize_audit

            normalize_audit(state)
            body = app_gateway._source(db, run, tenant, owner)
            review = app_gateway.inspect_workbook(body)
            checkpoint = state.get("analysis_checkpoint")
            from app.application.reviewed_excel_budget import (
                BUDGET_VERSION,
                validate_checkpoint_budget,
                validate_remaining_audit_budget,
            )

            try:
                validate_checkpoint_budget(checkpoint)
            except app_gateway.ReviewedExcelError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if checkpoint and (
                checkpoint.get("version") != version
                or checkpoint.get("source_sha256") != run.file_sha256
            ):
                raise HTTPException(
                    status_code=409, detail="分类或来源版本已改变；未覆盖已确认结果"
                )
            if checkpoint and checkpoint.get("auto_group", False) != auto_group:
                raise HTTPException(status_code=409, detail="分组模式已改变，请核对已有批次")
            if checkpoint and checkpoint.get("phase") == "inflight":
                from app.application.reviewed_excel_audit import is_live, recovery_action

                latest = (state.get("model_audit") or [{}])[-1]
                if is_live(latest.get("request_sha256")):
                    return support._analysis_in_flight(classification_id, version, state)
                lookup = await support._lookup_market_call(latest.get("call_id"), owner, model_session)
                action = recovery_action(latest, lookup)
                if action == "wait":
                    return support._analysis_in_flight(classification_id, version, state)
                if action == "locked":
                    raise HTTPException(
                        status_code=409,
                        detail="上次请求结果未知且市场无法确认；不会自动重发。"
                        "如需放弃并重发，须由用户明确授权（可能重复计费）",
                    )
                checkpoint["recovery"] = {
                    "call_id": latest["call_id"],
                    "request_sha256": latest["request_sha256"],
                }
                checkpoint["phase"] = "ready"
                logger.info("analyze resumes an unsettled call by same-key market recovery")
            repair = (checkpoint or {}).get("repair") or {}
            if checkpoint and checkpoint.get("phase") == "failed":
                if repair.get("exhausted"):
                    raise app_gateway._model_processing_failure(
                        app_gateway.ModelAnswerRejected(
                            f"模型连续 {repair['rounds']} 轮答案未通过校验：{repair['reason']}；"
                            "未再调用模型，请人工核对或重新归档"
                        ),
                        stored_status=200,
                        retryable=False,
                    )
                if checkpoint.get("calls_in_round", 0) >= checkpoint["max_calls"]:
                    checkpoint["calls_in_round"] = 0
                checkpoint["phase"] = "ready"
            if checkpoint and checkpoint.get("phase") == "paused":
                checkpoint["phase"] = "ready"
                checkpoint["calls_in_round"] = 0
            from app.application.reviewed_excel_plan import (
                restore_checkpoint_review,
                split_plan_step,
                store_coordinate_plan,
            )

            if checkpoint:
                try:
                    review, batches = restore_checkpoint_review(review, checkpoint)
                except app_gateway.ReviewedExcelError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                max_calls = checkpoint["max_calls"]
            else:
                from app.application.reviewed_excel_evidence import prepare_auto_slice_review

                review = prepare_auto_slice_review(review, skip_hidden_sheets=True)
                batches, max_calls = await run_in_threadpool(
                    app_gateway.plan_semantic_batches, review, neutral=True
                )
                from app.application.reviewed_excel_template import (
                    configured_template_llm_provider,
                )

                template_provider = configured_template_llm_provider()
                checkpoint = {
                    "budget_version": BUDGET_VERSION,
                    "version": version,
                    "source_sha256": run.file_sha256,
                    "skip_hidden_sheets": True,
                    "phase": "ready",
                    "results": [],
                    "total": len(batches),
                    "max_calls": max_calls,
                    "calls_in_round": 0,
                    "auto_group": auto_group,
                    "authorization": {
                        "kind": "account_session",
                        "tenant_id": tenant,
                        "owner_user_id": owner,
                        "source_sha256": run.file_sha256,
                        "provider": template_provider,
                        "provider_basis": "configured_before_call",
                        "scope": "this_file_bounded_cells_and_structure",
                        "requested_at": app_gateway.utcnow().isoformat(),
                    },
                }
                store_coordinate_plan(checkpoint, batches)
            validate_remaining_audit_budget(state, checkpoint, len(batches))
            index = len(checkpoint["results"])
            if index > len(batches):
                raise HTTPException(status_code=409, detail="分析批次状态无效")
            state["analysis_checkpoint"] = checkpoint

            def turn_for(step):
                from app.application.reviewed_excel_audit import repair_turn

                if repair.get("step") != step or repair.get("exhausted"):
                    return None
                return repair_turn(repair.get("answer", ""), repair.get("reason", ""))

            async def audited(draft, prepared, phase, step, function, *args, **kwargs):
                """Send one claimed call: (result, draft), or a repair continuation dict."""
                from app.application.reviewed_excel_audit import claim_request, mark_live
                from app.application.reviewed_excel_template import template_llm_model_label
                from app.build_identity import build_identity

                request_sha = claim_request(
                    state,
                    prepared,
                    source_sha256=run.file_sha256,
                    version=version,
                    classification_id=classification_id,
                    code_version=build_identity()["git_sha"] or "unavailable",
                    model=template_llm_model_label(),
                    phase=phase,
                )
                checkpoint["phase"] = "inflight"
                support._recheck(request, (tenant, owner))
                app_gateway._classification_cas(db, run, draft, state)
                mark_live(request_sha)
                draft = app_gateway.dump_json(state)
                holder, save = support._response_audit_writer(
                    state, draft, classification_id, tenant, owner, request_sha
                )
                previous_calls = checkpoint.get("calls_in_round", 0)
                try:
                    with app_gateway.bind_model_session(model_session):
                        value = await run_in_threadpool(
                            support._call_with_response_audit,
                            function,
                            save,
                            *args,
                            call_id=state["model_audit"][-1].get("call_id"),
                            expected_request_sha256=request_sha,
                            owner_id=owner,
                            **kwargs,
                        )
                except (ValueError, TypeError, app_gateway.EltError) as exc:
                    return support._settle_failed_step(
                        db,
                        run,
                        state,
                        holder[0],
                        request_sha,
                        exc,
                        stored=holder[0] != draft,
                        step=step,
                        previous_calls=previous_calls,
                        classification_id=classification_id,
                        split_unit=(
                            (lambda unit: split_plan_step(checkpoint, unit, review))
                            if phase == "classification"
                            else None
                        ),
                    )
                support._recheck(request, (tenant, owner))
                app_gateway._source(db, run, tenant, owner)
                from app.application.reviewed_excel_audit import mark_answered

                mark_answered(state, request_sha)
                checkpoint["calls_in_round"] = previous_calls + 1
                checkpoint["phase"] = "ready"
                checkpoint.pop("repair", None)
                return value, holder[0]

            claimed_draft = old
            if index < len(batches):
                batch_review = {**review, "cells": batches[index], "full_cells": review["cells"]}
                options = {"reference_ids": auto_group, "repair": turn_for(index)}
                prepared = await run_in_threadpool(
                    app_gateway._classify_semantic_batch, batch_review, prepare_only=True, **options
                )
                step = await audited(
                    claimed_draft,
                    prepared,
                    "classification",
                    index,
                    app_gateway._classify_semantic_batch,
                    batch_review,
                    **options,
                )
                if isinstance(step, dict):
                    return step
                batch_result, claimed_draft = step
                checkpoint["results"].append(batch_result)
                result = app_gateway.combine_semantic_batches(
                    review, batches[: index + 1], checkpoint["results"], max_calls
                )
                if index + 1 < len(batches):
                    if checkpoint["calls_in_round"] >= max_calls:
                        checkpoint["phase"] = "paused"
                    app_gateway._classification_cas(db, run, claimed_draft, state)
                    return {
                        "classification_id": classification_id,
                        "version": version,
                        "phase": "paused" if checkpoint["phase"] == "paused" else "pending",
                        "checkpoint": support._checkpoint_view(checkpoint),
                    }
            else:
                if not auto_group or (
                    len(batches) <= 1 and not state.get("saved_response_revalidations")
                ):
                    raise HTTPException(status_code=409, detail="分析批次状态无效")
                result = app_gateway.combine_semantic_batches(review, batches, checkpoint["results"], max_calls)
            from app.application.reviewed_excel_partition import boundary_left_for_confirmation

            # Uncovered cells stay for a person. Do not send another model call to fill them.
            if auto_group and len(batches) > 1 and not boundary_left_for_confirmation(result):
                from app.application.reviewed_excel_grouping import group_semantic_fragments

                # Persist complete fragment results before beginning a separate model request.
                if index < len(batches):
                    if checkpoint["calls_in_round"] >= max_calls:
                        checkpoint["phase"] = "paused"
                    app_gateway._classification_cas(db, run, claimed_draft, state)
                    claimed_draft = app_gateway.dump_json(state)
                    if checkpoint["phase"] == "paused":
                        return {
                            "classification_id": classification_id,
                            "version": version,
                            "phase": "paused",
                            "checkpoint": support._checkpoint_view(checkpoint),
                        }
                options = {"repair": turn_for(len(batches))}
                grouping_request: dict | list[dict] = await run_in_threadpool(
                    group_semantic_fragments, review, result, prepare_only=True, **options
                )
                if not isinstance(grouping_request, dict):
                    raise app_gateway.ReviewedExcelError("分组请求格式无效")
                step = await audited(
                    claimed_draft,
                    grouping_request,
                    "grouping",
                    len(batches),
                    group_semantic_fragments,
                    review,
                    result,
                    **options,
                )
                if isinstance(step, dict):
                    return step
                result["suggested_documents"], claimed_draft = step
                result["budget"]["grouping_calls"] = 1
            old = claimed_draft
            state.pop("analysis_checkpoint", None)
            rule_sheets = app_gateway.classify_review_workbook(review)
            values = {(c["sheet"], c["cell"]): c["value"][:160] for c in review["cells"]}
            from openpyxl.utils.cell import (
                column_index_from_string,
                coordinate_from_string,
            )

            sheets = []
            for rule_sheet in rule_sheets:
                regions = []
                for region in (r for r in result["regions"] if r["sheet"] == rule_sheet["sheet"]):
                    c1, r1, c2, r2 = app_gateway.bounded_range(region["range"])

                    def inside(ref):
                        col, row = coordinate_from_string(ref["cell"])
                        return c1 <= column_index_from_string(col) <= c2 and r1 <= row <= r2

                    rule_regions = rule_sheet["regions"]
                    headers = [
                        h
                        for candidate in rule_regions
                        for h in candidate["header_cells"]
                        if inside(h)
                    ]
                    headings = [
                        e for candidate in rule_regions for e in candidate["evidence"] if inside(e)
                    ]
                    merged = []
                    for candidate in rule_regions:
                        for item in candidate["merged_ranges"]:
                            mc1, mr1, mc2, mr2 = app_gateway.bounded_range(item)
                            if (
                                c1 <= mc1 <= mc2 <= c2
                                and r1 <= mr1 <= mr2 <= r2
                                and item not in merged
                            ):
                                merged.append(item)
                    regions.append(
                        {
                            "range": region["range"],
                            "labels": region["labels"],
                            "label_source": "not_classified" if auto_group else "model",
                            "range_source": "model",
                            "evidence": [
                                {
                                    "label": "model",
                                    "cell": ref["cell"],
                                    "matched": values[(ref["sheet"], ref["cell"])],
                                }
                                for ref in region["evidence"]
                                if (ref.get("sheet"), ref.get("cell")) in values
                            ],
                            "parent_heading": headings[0]["matched"] if headings else "",
                            "header_cells": headers,
                            "merged_ranges": merged,
                            "dependencies": region["dependencies"],
                            **(
                                {"drawing_evidence": region["drawing_evidence"]}
                                if "drawing_evidence" in region
                                else {}
                            ),
                            "possible_shared_context": [
                                {
                                    "cell": ref["cell"],
                                    "kind": f"{ref['sheet']}：模型建议依赖，待确认",
                                }
                                for ref in region["dependencies"]
                            ],
                            "dependency_status": "模型建议，边界和跨区依赖待确认",
                            "needs_confirmation": True,
                            "checked_cells": 0,
                            "reason": region["reason"],
                            "open_fragment": region.get("open_fragment", False),
                            "model_original_range": region.get("model_original_range"),
                            "suggested_labels": region.get("suggested_labels", []),
                            "context_warning": region.get("context_warning", ""),
                            "continuation_context": region.get("continuation_context"),
                            "value_extent": region.get("value_extent"),
                        }
                    )
                dimensions = next(
                    item
                    for item in review["sheet_overview"]
                    if item["sheet"] == rule_sheet["sheet"]
                )
                for candidate in rule_sheet["regions"]:
                    regions.extend(
                        app_gateway.unresolved_fragments(candidate, regions, dimensions["merged_regions"])
                    )
                sheets.append({**rule_sheet, "regions": regions})
            from app.application.reviewed_excel_sheet_names import apply_unknown_sheet_names

            apply_unknown_sheet_names(sheets, review["cells"], owner_id=owner)
            actual_providers = sorted(
                {item.get("provider", "unreported") for item in result["input_summaries"]}
            )
            latest = {
                "parent_version": version,
                "sheets": sheets,
                "model_status": "returned",
                "model_authorization": checkpoint.get("authorization"),
                "source_scope": {
                    "source_sha256": run.file_sha256,
                    "skip_hidden_sheets": checkpoint.get("skip_hidden_sheets") is True,
                    "sheets": review["sheets"],
                },
                "actual_model_providers": actual_providers,
                "read_only_print_areas": review["read_only_print_areas"],
                "suggested_documents": result["suggested_documents"],
                "suggested_document_count": result["suggested_document_count"],
                "document_count_status": result["document_count_status"],
                "layout_references": result["layout_references"],
                "coverage": result["coverage"],
                "input_summaries": result["input_summaries"],
                "structure_map": result["structure_map"],
                "structure_map_source": result["structure_map_source"],
                "budget": result["budget"],
                "fragment_links": result["fragment_links"],
                "confirmed": False,
            }
            latest["version"] = app_gateway._classification_version(run.file_sha256, version, latest)
            versions.append(latest)
            if len(versions) > 50:
                raise app_gateway.ReviewedExcelError("分类版本已达上限")
            support._recheck(request, (tenant, owner))
            app_gateway._classification_cas(db, run, old, state)
        return {"classification_id": classification_id, **latest}
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(status_code=400, detail=app_gateway.public_excel_error(exc)) from None
