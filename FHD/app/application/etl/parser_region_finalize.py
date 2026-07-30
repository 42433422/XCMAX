"""Validation warnings and final dataset projection for region parsing."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def finalize_region_dataset(
    *,
    parsed_rows: object,
    target_type: object,
    probes: object,
    regions: object,
    excluded_charge_rows: object,
    future_dated_source_rows: object,
    same_date_source_conflicts: object,
    history_product_count: object,
    model_identity_ambiguity_count: object,
    companion_stale_records_skipped: object,
    companion_candidate_count: object,
    workbook_sheet_names: object,
    companion_sheet_counts: object,
    sheet_domain_hints: object,
    skipped_sheets: object,
    all_headers: object,
):
    if not parsed_rows:
        return None

    # A model-less price/history row is not safely interchangeable with an
    # otherwise identical modeled row.  Keep both source rows for review and
    # attach a blocking issue to each, rather than silently dropping newer data
    # or creating two products during a later preview.
    if target_type == "customer_products":
        identity_issues = source_model_ambiguity_issues(
            [row.values for row in parsed_rows],
            unit_field="customer_name",
        )
        if identity_issues:
            ambiguous_keys: set[tuple[str, str]] = set()
            for index, issues in identity_issues.items():
                row = parsed_rows[index]
                row.provenance.setdefault("validation_issues", []).extend(issues)
                ambiguous_keys.add(product_name_key(row.values, unit_field="customer_name"))
            model_identity_ambiguity_count = len(ambiguous_keys)

    llm = advise_workbook_regions(probes)
    llm_by_region = {
        str(item.get("region_id") or ""): item
        for item in list(llm.data.get("regions") or [])
        if isinstance(item, dict)
    }
    for region in regions:
        suggestion = llm_by_region.get(region["id"])
        if suggestion:
            region["llm_suggestion"] = suggestion

    selected = [region for region in regions if region["status"] == "selected"]
    excluded = [region for region in regions if region["status"] == "excluded"]
    target_label = "发货单" if target_type == "shipment_records" else "客户产品"
    warnings: list[dict[str, Any]] = [
        {
            "code": "ETL_MULTI_REGION_WORKBOOK_PLANNED",
            "message": (
                f"已从混合工作簿识别 {len(selected)} 个{target_label}业务区块，"
                f"排除 {len(excluded)} 个其他业务区块。"
            ),
            "selected_regions": len(selected),
            "excluded_regions": len(excluded),
        }
    ]
    if excluded_charge_rows:
        warnings.append(
            {
                "code": "ETL_NON_PRODUCT_CHARGES_SKIPPED",
                "message": f"已跳过 {len(excluded_charge_rows)} 行运费等非产品费用。",
                "count": len(excluded_charge_rows),
                "rows": excluded_charge_rows[:50],
            }
        )
    if future_dated_source_rows:
        warnings.append(
            {
                "code": "ETL_FUTURE_DATED_SOURCE_ROW",
                "message": (
                    f"已隔离 {len(future_dated_source_rows)} 条日期晚于当前日期的历史/报价记录，"
                    "它们不会被当作最新客户产品事实。"
                ),
                "count": len(future_dated_source_rows),
                "rows": future_dated_source_rows[:50],
            }
        )
    if same_date_source_conflicts:
        warnings.append(
            {
                "code": "ETL_LATEST_SOURCE_CONFLICT",
                "message": (
                    f"发现 {same_date_source_conflicts} 组同日跨表产品事实冲突，"
                    "已保留为错误行，需人工确认。"
                ),
                "count": same_date_source_conflicts,
            }
        )
    if history_product_count:
        warnings.append(
            {
                "code": "ETL_SHIPMENT_HISTORY_PRODUCTS_INCLUDED",
                "message": (
                    f"已从出货历史增补 {history_product_count} 个客户产品候选，"
                    "仅用于客户产品预演，不会作为新的发货记录写入。"
                ),
                "count": history_product_count,
            }
        )
    if model_identity_ambiguity_count:
        warnings.append(
            {
                "code": "ETL_PRODUCT_MODEL_AMBIGUITY",
                "message": (
                    f"发现 {model_identity_ambiguity_count} 组同客户同产品同时有型号和无型号的数据，"
                    "已标为错误，需补全型号或拆分后重新预演。"
                ),
                "count": model_identity_ambiguity_count,
            }
        )
    if companion_stale_records_skipped:
        warnings.append(
            {
                "code": "ETL_LATEST_PRODUCT_DATA_SELECTED",
                "message": (
                    f"同一客户同一产品存在 {companion_stale_records_skipped} 条较早或同日旧记录，"
                    "已按来源日期优先保留最新有效数据。"
                ),
                "count": companion_stale_records_skipped,
            }
        )
    # A shipment-record preview never writes companion history/quote rows.
    # Keep that fact visible even when deduplication also found stale product
    # facts: otherwise the generic "latest data" notice crowds out the
    # actionable explanation that the workbook's appendices were read and are
    # available through the linked customer/product preview.
    if companion_candidate_count and target_type == "shipment_records":
        warnings.append(
            {
                "code": "ETL_COMPANION_CUSTOMER_PRODUCT_DATA_FOUND",
                "message": (
                    f"已在附表发现 {companion_candidate_count} 个客户产品候选。"
                    "它们不会写入当前发货记录预演；可新建客户及产品预演后确认。"
                ),
                "count": companion_candidate_count,
            }
        )
    sheet_plan = _build_sheet_plan(
        workbook_sheet_names=workbook_sheet_names,
        regions=regions,
        companion_sheet_counts=companion_sheet_counts,
        sheet_domain_hints=sheet_domain_hints,
    )
    return ParsedDataset(
        headers=all_headers,
        rows=parsed_rows,
        source_features={
            "structure_detection": "deterministic_regions_v1",
            **region_source_features(
                target_type=target_type,
                regions=regions,
                rows=len(parsed_rows),
            ),
            "regions": regions,
            "shipment_history_product_candidates": companion_candidate_count,
            "latest_record_selection": {
                "basis": "source_date_then_same_sheet_row",
                "unique_candidates": companion_candidate_count,
                "stale_records_skipped": companion_stale_records_skipped,
                "future_dated_records_skipped": len(future_dated_source_rows),
                "same_date_conflicts": same_date_source_conflicts,
                "model_identity_ambiguity_groups": model_identity_ambiguity_count,
            },
            "sheet_plan": sheet_plan,
            "skipped_sheets": skipped_sheets,
            "headers": all_headers,
            "llm_structure": {
                **llm.public_metadata(),
                "suggestion_count": len(llm_by_region),
            },
        },
        warnings=warnings,
    )


sync_module_functions(
    target=globals(),
    source_module="app.application.etl.parser_regions",
    function_names=("finalize_region_dataset",),
)
