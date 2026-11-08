from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_auto_slice import derive_classified_documents
from app.application.reviewed_excel_template import inspect_workbook


def workbook():
    book = Workbook()
    sheet = book.active
    sheet.title = "One"
    sheet["A1"] = "第一份"
    sheet.merge_cells("A1:B1")
    sheet["A2"] = 7
    sheet["B2"] = "=A2*2"
    sheet["A5"] = "第二份"
    other = book.create_sheet("Two")
    other["A1"] = "第三份"
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def classification(body):
    return {
        "source_sha256": inspect_workbook(body)["sha256"],
        "model_status": "returned",
        "regions": [
            {"sheet": "One", "range": "A1:B2", "dependencies": []},
            {"sheet": "One", "range": "A5:B5", "dependencies": []},
            {"sheet": "Two", "range": "A1:A1", "dependencies": []},
        ],
        "suggested_documents": [
            {"fragments": [{"sheet": "One", "range": "A1:B2"}]},
            {"fragments": [{"sheet": "One", "range": "A5:B5"}]},
            {"fragments": [{"sheet": "Two", "range": "A1:A1"}]},
        ],
    }


def test_ungrouped_regions_block_and_model_groups_preserve_formula_and_merge():
    body = workbook()
    uncertain = classification(body)
    uncertain["suggested_documents"] = []
    with pytest.raises(ReviewedExcelError, match="独立单据关系"):
        derive_classified_documents(body, uncertain)
    result = derive_classified_documents(body, classification(body))
    assert len(result) == 3
    assert all(item["basis"] == "model_group" and not item["confirmed"] for item in result)
    first = load_workbook(BytesIO(result[0]["workbook"]))
    assert first.sheetnames == ["One"]
    assert first["One"]["B2"].value == "=A2*2"
    assert "A1:B1" in {str(r) for r in first["One"].merged_cells.ranges}
    assert first["One"]["A5"].value is None
    first["One"]["A2"] = 9
    stream = BytesIO()
    first.save(stream)
    assert load_workbook(BytesIO(stream.getvalue()))["One"]["A2"].value == 9


def test_model_group_is_not_claimed_user_confirmed():
    body = workbook()
    result = classification(body)
    result["suggested_documents"] = [
        {"fragments": [{"sheet": "One", "range": "A1:B2"}, {"sheet": "One", "range": "A5:B5"}]},
        {"fragments": [{"sheet": "Two", "range": "A1:A1"}]},
    ]
    slices = derive_classified_documents(body, result)
    assert len(slices) == 2 and slices[0]["basis"] == "model_group" and not slices[0]["confirmed"]
    assert load_workbook(BytesIO(slices[0]["workbook"]))["One"]["A5"].value == "第二份"


def test_rejects_external_dependency_duplicate_group_and_source_mismatch():
    body = workbook()
    result = classification(body)
    result["regions"][0]["dependencies"] = [{"sheet": "One", "cell": "A5"}]
    with pytest.raises(ReviewedExcelError, match="外部"):
        derive_classified_documents(body, result)
    result = classification(body)
    result["suggested_documents"] = [{"fragments": [{"sheet": "One", "range": "A1:B2"}]}] * 2
    with pytest.raises(ReviewedExcelError, match="重复"):
        derive_classified_documents(body, result)
    result = classification(body)
    result["source_sha256"] = "wrong"
    with pytest.raises(ReviewedExcelError, match="原件"):
        derive_classified_documents(body, result)


def test_rejects_cross_sheet_model_group_and_flattens_cut_merged_cell():
    body = workbook()
    result = classification(body)
    result["suggested_documents"] = [
        {"fragments": [{"sheet": "One", "range": "A1:B2"}, {"sheet": "Two", "range": "A1:A1"}]},
        {"fragments": [{"sheet": "One", "range": "A5:B5"}]},
    ]
    with pytest.raises(ReviewedExcelError, match="跨工作表"):
        derive_classified_documents(body, result)
    # V3 export flattens merges that a selection cuts instead of hard-rejecting.
    result = classification(body)
    result["regions"][0]["range"] = "A1:A2"
    result["suggested_documents"][0]["fragments"][0]["range"] = "A1:A2"
    slices = derive_classified_documents(body, result)
    first = load_workbook(BytesIO(slices[0]["workbook"]))["One"]
    assert first["A1"].value == "第一份"
    assert "A1:B1" not in {str(r) for r in first.merged_cells.ranges}


def test_resplit_ledger_fragments_resolve_to_their_model_region():
    """Template export keeps the model's document. Resplit stays available for a direct check."""
    from app.application.reviewed_excel_evidence import bounded_range

    book = Workbook()
    sheet = book.active
    sheet.title = "客户档案"
    sheet["A1"] = "客户档案"
    sheet["A2"], sheet["B2"] = "客户编号", "合作起始"
    for i in range(40):
        row = 3 + i
        sheet.cell(row, 1, f"C-{i + 1:04d}")
        sheet.cell(row, 2, f"2023-{i % 12 + 1:02d}-{i % 27 + 1:02d}")
        sheet.cell(row, 8, "华东")
    stream = BytesIO()
    book.save(stream)
    body = stream.getvalue()
    result = derive_classified_documents(
        body,
        {
            "source_sha256": inspect_workbook(body)["sha256"],
            "model_status": "returned",
            "regions": [{"sheet": "客户档案", "range": "A1:H42", "dependencies": []}],
            "suggested_documents": [{"fragments": [{"sheet": "客户档案", "range": "A1:H42"}]}],
        },
    )
    assert len(result) == 1
    for item in result:
        for fragment in item["fragments"]:
            c1, r1, c2, r2 = bounded_range(fragment["range"])
            assert fragment["sheet"] == "客户档案"
            assert c1 >= 1 and c2 <= 8 and r1 >= 1 and r2 <= 42
    from app.application.reviewed_excel_verify_cut import verify_after_cut

    verified = verify_after_cut(
        inspect_workbook(body),
        [
            {
                "document_id": "export-0",
                "fragments": [{"sheet": "客户档案", "range": "A1:H42"}],
                "evidence": [],
                "reason": "",
            }
        ],
        resplit=True,
    )
    assert verified["groups"]
    for group in verified["groups"]:
        for fragment in group["fragments"]:
            c1, r1, c2, r2 = bounded_range(fragment["range"])
            assert c1 >= 1 and c2 <= 8 and r1 >= 1 and r2 <= 42


def test_chinese_names_are_bounded_unique_and_neutral_if_no_title():
    from app.application.reviewed_excel_auto_slice import _slice_filename

    used = set()
    part = [{"sheet": "One", "range": "A1:B2"}]
    cells = [{"sheet": "One", "cell": "A1", "value": "生产单"}]
    assert _slice_filename(part, cells, used) == "生产单.xlsx"
    assert _slice_filename(part, cells, used) == "生产单_2.xlsx"
    assert _slice_filename(part, [], used) == "切片_1.xlsx"
    assert _slice_filename(part, [], used) == "切片_2.xlsx"
    assert (
        _slice_filename(part, [{"sheet": "One", "cell": "A1", "value": "../客户/生产单"}], used)
        == "切片_3.xlsx"
    )


@pytest.mark.parametrize("count,accepted", [(20001, True), (25000, True), (25001, False)])
def test_workbook_nonempty_cell_limit_and_full_batch_coverage(monkeypatch, count, accepted):
    from app.application.reviewed_excel_classification import plan_semantic_batches

    monkeypatch.setattr("app.application.reviewed_excel_template.MAX_CELLS", 25000)
    book = Workbook()
    sheet = book.active
    for row in range(1, count + 1):
        sheet.cell(row, 1, row)
    stream = BytesIO()
    book.save(stream)
    if not accepted:
        with pytest.raises(ReviewedExcelError, match="超过 25000"):
            inspect_workbook(stream.getvalue())
        return
    review = inspect_workbook(stream.getvalue())
    assert len(review["cells"]) == count
    batches, budget = plan_semantic_batches(review, 4)
    primary = [
        (c["sheet"], c["cell"]) for batch in batches for c in batch if not c.get("context_only")
    ]
    assert len(primary) == len(set(primary)) == count
    from app.application.reviewed_excel_evidence import MAX_MODEL_CELLS

    assert all(len(batch) <= MAX_MODEL_CELLS for batch in batches)
    assert budget == 4


def test_second_stage_requires_complete_coverage_and_evidence_for_each_fragment():
    from app.application.reviewed_excel_grouping import prepare_grouping, validate_grouping

    body = workbook()
    review = inspect_workbook(body)
    classification_result = classification(body)
    classification_result["coverage"] = [
        {"sheet": "One", "unread": [], "unassigned": [], "merged_omitted": 0},
        {"sheet": "Two", "unread": [], "unassigned": [], "merged_omitted": 0},
    ]
    for region in classification_result["regions"]:
        region.update(labels=["unknown"], evidence=[], reason="需要核对")
    proposal = prepare_grouping(review, classification_result)
    parts = [{"sheet": "One", "range": "A1:B2"}, {"sheet": "One", "range": "A5:B5"}]
    group = {
        "document_id": "doc1",
        "fragments": parts,
        "reason": "模型建议续表",
        "evidence": [{"sheet": "One", "cell": "A1"}, {"sheet": "One", "cell": "A5"}],
    }
    valid = validate_grouping(proposal, {"groups": [group]})
    assert valid[0]["status"] == "model_suggested" and valid[0]["fragments"] == parts
    with pytest.raises(ReviewedExcelError, match="片段内证据"):
        validate_grouping(proposal, {"groups": [{**group, "evidence": group["evidence"][:1]}]})
    with pytest.raises(ReviewedExcelError, match="来源无效或重复"):
        validate_grouping(proposal, {"groups": [group, {**group, "document_id": "doc2"}]})
    classification_result["coverage"][0]["unread"] = ["A2"]
    with pytest.raises(ReviewedExcelError, match="覆盖不完整"):
        prepare_grouping(review, classification_result)


def test_classified_document_export_preserves_formula_support():
    book = Workbook()
    sheet = book.active
    sheet.title = "生产"
    sheet["A1"] = "生产单"
    sheet["A2"] = "=B2*C2"
    sheet["B2"] = 3
    sheet["C2"] = 5
    sheet["D2"] = "无关信息"
    stream = BytesIO()
    book.save(stream)
    body = stream.getvalue()
    result = derive_classified_documents(
        body,
        {
            "source_sha256": inspect_workbook(body)["sha256"],
            "model_status": "returned",
            "regions": [{"sheet": "生产", "range": "A1:B2", "dependencies": []}],
            "suggested_documents": [{"fragments": [{"sheet": "生产", "range": "A1:B2"}]}],
        },
    )
    saved = load_workbook(BytesIO(result[0]["workbook"]), data_only=False)
    assert result[0]["filename"] == "生产单.xlsx"
    assert saved.sheetnames == ["生产", "依赖支撑"]
    assert saved["生产"]["A2"].value == "=B2*'依赖支撑'!C2"
    assert saved["依赖支撑"]["C2"].value == 5
    assert saved["依赖支撑"]["D2"].value is None


def test_unresolved_open_fragment_cannot_be_exported_as_a_finished_document():
    body = workbook()
    result = classification(body)
    result["regions"][0]["open_fragment"] = True
    result["regions"][0]["model_original_range"] = "A1:B5"
    with pytest.raises(ReviewedExcelError, match="未读边界"):
        derive_classified_documents(body, result)


def test_prepare_grouping_includes_middle_structure_and_cross_fragment_formulas():
    """Final grouping input must expose middle rows and cross-fragment formulas, not only ends."""
    from app.application.reviewed_excel_grouping import prepare_grouping

    book = Workbook()
    sheet = book.active
    sheet.title = "综合"
    sheet["A103"] = "表头甲"
    sheet["B103"] = "表头乙"
    for row in range(104, 125):
        sheet[f"A{row}"] = f"上段-{row}"
        sheet[f"B{row}"] = row
    sheet["A125"] = "续表标题"
    sheet["B125"] = "数量"
    for row in range(126, 140):
        sheet[f"A{row}"] = f"下段-{row}"
        sheet[f"B{row}"] = row
    sheet["C139"] = "=SUM(B104:B124)"
    stream = BytesIO()
    book.save(stream)
    body = stream.getvalue()
    review = inspect_workbook(body)
    classification = {
        "source_sha256": review["sha256"],
        "coverage": [
            {
                "sheet": "综合",
                "unread": [],
                "unassigned": [],
                "merged_omitted": 0,
            }
        ],
        "regions": [
            {
                "sheet": "综合",
                "range": "A103:K124",
                "evidence": [{"sheet": "综合", "cell": "A103"}],
                "reason": "上段",
            },
            {
                "sheet": "综合",
                "range": "A125:G203",
                "evidence": [{"sheet": "综合", "cell": "A125"}],
                "reason": "下段",
            },
        ],
    }
    proposal = prepare_grouping(review, classification)
    cells = {(c["sheet"], c["cell"]) for c in proposal["cells"]}
    # Middle rows from the upper fragment must be present, not only A103 and the last row.
    assert ("综合", "A103") in cells
    assert any(cell.startswith("A11") or cell.startswith("A12") for _, cell in cells)
    assert ("综合", "A125") in cells
    assert ("综合", "C139") in cells
    structure = {(item["sheet"], item["range"]): item for item in proposal["fragment_structure"]}
    assert structure[("综合", "A103:K124")]["nonempty_cells"] >= 2
    assert structure[("综合", "A125:G203")]["has_formulas"] is True
    links = proposal["cross_fragment_formulas"]
    assert any(
        link["from_fragment"] == "A125:G203" and link["to_fragment"] == "A103:K124"
        for link in links
    )
    # Evidence is descriptive only: prepare_grouping must not invent merged groups.
    assert len(proposal["fragments"]) == 2


def _save(book) -> bytes:
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def _rule_run(body):
    from app.application.reviewed_excel_auto_slice import derive_rule_slices, rule_row_dispositions
    from app.application.reviewed_excel_basic_classification import classify_review_workbook

    latest = {"sheets": classify_review_workbook(inspect_workbook(body))}
    slices = derive_rule_slices(body, latest)
    return latest, slices, rule_row_dispositions(body, latest, slices)


def test_rule_regions_keep_merged_cells_and_their_title_context():
    book = Workbook()
    sheet = book.active
    sheet.title = "生产"
    rows = {
        1: ["生产任务单"],
        3: ["产品名称", "数量", "单价", "金额"],
        4: ["面漆", 3, 12, 36],
        6: ["工艺流程"],
        8: ["工序", "说明", "数量", "备注"],
        9: ["喷涂", "两遍", 1, "见附表"],
    }
    for row, values in rows.items():
        for column, value in enumerate(values, start=1):
            sheet.cell(row, column, value)
    for merged in ("A1:D2", "A6:D7", "D9:D10"):
        sheet.merge_cells(merged)
    _latest, slices, _rows = _rule_run(_save(book))
    assert [item["table_region"] for item in slices] == ["A1:D4", "A6:D10"]


def test_hidden_ledgers_and_unrecognized_regions_go_to_review_with_row_reasons():
    book = Workbook()
    sheet = book.active
    sheet.title = "出货"
    sheet.append(["产品名称", "数量", "单价", "金额"])
    sheet.append(["清面漆", 2, 10, 20])
    sheet["A5"] = "未登记业务区"
    sheet["A6"] = "斜向批次残余"
    sheet["B6"] = "口径不明"
    sheet["A7"] = "补充口径待人判读"
    ledger = book.create_sheet("台账")
    ledger.append(["客户", "金额"])
    ledger.append(["甲", 5])
    ledger.sheet_state = "hidden"
    _latest, slices, rows = _rule_run(_save(book))
    by_region = {(s["fragments"][0]["sheet"], s["table_region"]): s for s in slices}
    assert by_region[("出货", "A1:D2")]["status"] == "identified"
    assert by_region[("出货", "A6:B7")]["status"] == "pending_review"
    hidden = by_region[("台账", "A1:B2")]
    assert hidden["status"] == "pending_review" and "隐藏" in hidden["review_reason"]
    copied = load_workbook(BytesIO(hidden["workbook"]))
    assert copied["台账"]["A2"].value == "甲" and copied["切片复核说明"]["B4"].value
    status = {(r["sheet"], r["row"]): r["status"] for r in rows}
    assert status == {
        ("出货", 1): "import",
        ("出货", 2): "import",
        ("出货", 5): "pending_review",
        ("出货", 6): "pending_review",
        ("出货", 7): "pending_review",
        ("台账", 1): "pending_review",
        ("台账", 2): "pending_review",
    }
    assert all(r["reason"] for r in rows)


def test_delivery_note_print_area_crossing_fragment_uses_selected_fragment():
    """Small synthetic delivery note: the sheet print area extends past the note body."""
    book = Workbook()
    sheet = book.active
    sheet.title = "送货"
    sheet["A1"] = "送货单"
    sheet["A2"] = "客户"
    sheet["B2"] = "甲"
    sheet["A3"] = "品名"
    sheet["B3"] = "面漆"
    sheet["A8"] = "页脚说明"
    sheet.print_area = "A1:B8"
    body = _save(book)
    source = inspect_workbook(body)
    fragment = {"sheet": "送货", "range": "A1:B3"}
    slices = derive_classified_documents(
        body,
        {
            "source_sha256": source["sha256"],
            "model_status": "returned",
            "regions": [{**fragment, "dependencies": []}],
            "suggested_documents": [{"fragments": [fragment], "reason": "送货单主体"}],
        },
    )
    assert len(slices) == 1 and slices[0]["print_area_mode"] == "selected"
    derived = load_workbook(BytesIO(slices[0]["workbook"]))["送货"]
    assert str(derived.print_area) == "'送货'!$A$1:$B$3"
    assert derived["A1"].value == "送货单" and derived["B3"].value == "面漆"
    assert derived["A8"].value is None
    assert str(load_workbook(BytesIO(body))["送货"].print_area) == "'送货'!$A$1:$B$8"
    assert inspect_workbook(body)["sha256"] == source["sha256"]


def test_refused_extraction_keeps_values_and_rejects_rows_with_reason(monkeypatch):
    from app.application import reviewed_excel_auto_slice as auto_slice

    def refuse(*_args, **_kwargs):
        raise ReviewedExcelError("打印区域跨越所选文档")

    monkeypatch.setattr(auto_slice, "derive_document_workbook", refuse)
    book = Workbook()
    book.active.append(["产品名称", "数量"])
    book.active.append(["面漆", 3])
    _latest, slices, rows = _rule_run(_save(book))
    assert slices[0]["status"] == "pending_review" and "打印区域" in slices[0]["error"]
    assert load_workbook(BytesIO(slices[0]["workbook"])).worksheets[0]["A2"].value == "面漆"
    assert {r["status"] for r in rows} == {"rejected"}
    assert all("打印区域" in r["reason"] for r in rows)


def test_hidden_model_document_stays_for_review_and_visible_document_exports():
    book = Workbook()
    visible = book.active
    visible.title = "送货"
    visible["A1"] = "送货单"
    visible["B1"] = "甲"
    ledger = book.create_sheet("台账")
    ledger["A1"] = "客户"
    ledger["B1"] = "金额"
    ledger["A2"] = "甲"
    ledger.sheet_state = "hidden"
    body = _save(book)
    source = inspect_workbook(body)
    note = {"sheet": "送货", "range": "A1:B1"}
    hidden = {"sheet": "台账", "range": "A1:B2"}
    slices = derive_classified_documents(
        body,
        {
            "source_sha256": source["sha256"],
            "model_status": "returned",
            "regions": [{**note, "dependencies": []}, {**hidden, "dependencies": []}],
            "suggested_documents": [
                {"fragments": [note], "reason": "送货单"},
                {"fragments": [hidden], "reason": "隐藏台账"},
            ],
        },
    )
    exported = next(item for item in slices if item["fragments"][0]["sheet"] == "送货")
    held = next(item for item in slices if item["fragments"][0]["sheet"] == "台账")
    assert "status" not in exported
    assert load_workbook(BytesIO(exported["workbook"]))["送货"]["A1"].value == "送货单"
    assert held["status"] == "pending_review" and "隐藏" in held["review_reason"]
    copied = load_workbook(BytesIO(held["workbook"]))
    assert copied["台账"]["A2"].value == "甲" and "隐藏" in str(copied["切片复核说明"]["B4"].value)


def test_only_the_model_can_allow_a_slice_while_cells_remain_outside():
    from app.fastapi_routes.reviewed_excel_template import _model_allows_unassigned_slice

    assert _model_allows_unassigned_slice(
        {"input_summaries": [{"source_coverage": {"can_slice": True}}]}
    )
    assert not _model_allows_unassigned_slice(
        {"input_summaries": [{"source_coverage": {"can_slice": False}}]}
    )
    assert not _model_allows_unassigned_slice({"input_summaries": [{"source_coverage": {}}]})
