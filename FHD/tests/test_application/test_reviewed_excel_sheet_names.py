from app.application.elt.llm_assist import LlmAssistResult
from app.application.reviewed_excel_sheet_names import (
    annotate_slice_titles,
    apply_unknown_sheet_names,
)


def test_unknown_sheet_takes_the_model_name_and_type(monkeypatch):
    def fake(*_args, **_kwargs):
        return LlmAssistResult(
            used_llm=True,
            data={
                "sheets": [
                    {"sheet": "26出货", "name": "26出货明细", "type": "送货单"},
                    {"sheet": "借原材料明细", "name": "借原材料明细", "type": "借还台账"},
                    {"sheet": "国圣", "name": "国圣送货单", "type": "送货单"},
                ]
            },
        )

    monkeypatch.setattr(
        "app.application.reviewed_excel_sheet_names._template_llm_complete", fake
    )
    sheets = [
        {
            "sheet": "26出货",
            "labels": ["unknown"],
            "processable": True,
            "regions": [{"labels": ["unknown"]}],
        },
        {
            "sheet": "借原材料明细",
            "labels": ["unknown"],
            "processable": True,
            "regions": [{"labels": ["unknown"]}, {"labels": ["delivery"]}],
        },
        {
            "sheet": "国圣",
            "labels": ["delivery"],
            "processable": True,
            "regions": [{"labels": ["delivery"]}],
        },
    ]
    apply_unknown_sheet_names(sheets, [{"sheet": "26出货", "value": "产品"}], owner_id=1)
    assert sheets[0]["model_name"] == "26出货明细" and sheets[0]["labels"] == ["delivery"]
    assert sheets[1]["labels"] == ["ledger"] and sheets[1]["regions"][1]["labels"] == ["delivery"]
    assert sheets[2]["labels"] == ["delivery"] and sheets[2]["model_name"] == "国圣送货单"
    slices = [
        {"filename": "a.xlsx", "fragments": [{"sheet": "借原材料明细", "range": "A1:I60"}]},
        {"filename": "b.xlsx", "fragments": [{"sheet": "借原材料明细", "range": "A71:I86"}]},
    ]
    annotate_slice_titles(slices, sheets)
    assert slices[0]["display_name"] == "借原材料明细（1）"
    assert slices[1]["display_name"] == "借原材料明细（2）"
    assert slices[0]["type_label"] == "借还台账"


def test_naming_failure_leaves_unknown(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "app.application.reviewed_excel_sheet_names._template_llm_complete", boom
    )
    sheets = [{"sheet": "白浆", "labels": ["unknown"], "processable": True, "regions": []}]
    apply_unknown_sheet_names(sheets, [], owner_id=1)
    assert sheets[0]["labels"] == ["unknown"] and "model_name" not in sheets[0]
