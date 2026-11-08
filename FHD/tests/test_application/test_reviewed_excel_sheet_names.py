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

    monkeypatch.setattr("app.application.reviewed_excel_sheet_names._template_llm_complete", fake)
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


def test_naming_uses_reply_order_when_sheet_keys_differ(monkeypatch):
    def fake(*_args, **_kwargs):
        return LlmAssistResult(
            used_llm=True,
            data={"sheets": [{"sheet": "表1", "name": "白浆配方", "type": "原料"}]},
        )

    monkeypatch.setattr("app.application.reviewed_excel_sheet_names._template_llm_complete", fake)
    sheets = [
        {
            "sheet": "白浆",
            "labels": ["unknown"],
            "processable": True,
            "regions": [{"labels": ["unknown"]}],
        }
    ]
    apply_unknown_sheet_names(sheets, [{"sheet": "白浆", "value": "白浆"}], owner_id=1)
    assert sheets[0]["model_name"] == "白浆配方"
    assert sheets[0]["labels"] == ["material"]


def test_sheet_name_reply_accepts_a_bare_array():
    from app.application.reviewed_excel_template import _coerce_sheet_name_payload

    data = _coerce_sheet_name_payload(
        None,
        '说明\n[{"sheet":"白浆","name":"白浆配方","type":"原料","note":"多余"}]',
    )
    assert data == {"sheets": [{"sheet": "白浆", "name": "白浆配方", "type": "原料"}]}
    renamed = _coerce_sheet_name_payload(
        {"sheets": [{"sheet_name": "白浆", "名称": "白浆配方", "类型": "原料"}]},
        "",
    )
    assert renamed == {"sheets": [{"sheet": "白浆", "name": "白浆配方", "type": "原料"}]}
    nameless = _coerce_sheet_name_payload(
        None,
        '[{"name": "国圣送货单", "type": "送货单"}, {"name": "白浆配方", "type": "配方表"}]',
    )
    assert nameless == {
        "sheets": [
            {"sheet": "", "name": "国圣送货单", "type": "送货单"},
            {"sheet": "", "name": "白浆配方", "type": "配方表"},
        ]
    }


def test_names_without_sheet_keys_follow_sheet_order(monkeypatch):
    def fake(*_args, **_kwargs):
        return LlmAssistResult(
            used_llm=True,
            data={
                "sheets": [
                    {"sheet": "", "name": "国圣送货单", "type": "送货单"},
                    {"sheet": "", "name": "白浆配方", "type": "配方表"},
                ]
            },
        )

    monkeypatch.setattr("app.application.reviewed_excel_sheet_names._template_llm_complete", fake)
    sheets = [
        {"sheet": "国圣", "labels": ["delivery"], "processable": True, "regions": []},
        {
            "sheet": "白浆",
            "labels": ["unknown"],
            "processable": True,
            "regions": [{"labels": ["unknown"]}],
        },
    ]
    apply_unknown_sheet_names(sheets, [], owner_id=1)
    assert sheets[0]["model_name"] == "国圣送货单"
    assert sheets[1]["model_name"] == "白浆配方"
    assert sheets[1]["model_type"] == "配方表"
    assert sheets[1]["labels"] == ["template"]


def test_unknown_sheet_naming_runs_inside_a_live_event_loop(monkeypatch):
    import asyncio
    import json

    from app.application.elt.llm_session_provider import SessionMarketProvider

    for name, value in {
        "FHD_TEMPLATE_LLM_PROVIDER": "mimo",
        "FHD_TEMPLATE_MIMO_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
        "FHD_TEMPLATE_MIMO_MODEL": "mimo-v2.6-flash",
        "MIMO_API_KEY": "synthetic-placeholder",
        "FHD_ETL_LLM": "on",
    }.items():
        monkeypatch.setenv(name, value)

    async def fake(self, messages, **kwargs):
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"sheets": [{"sheet": "白浆", "name": "白浆配方", "type": "原料"}]},
                            ensure_ascii=False,
                        )
                    },
                }
            ]
        }

    monkeypatch.setattr(SessionMarketProvider, "chat_completion", fake)
    monkeypatch.setattr(
        "app.application.elt.llm_session_provider.current_owner_market_provider",
        lambda **_: SessionMarketProvider(7, "synthetic-market", timeout_seconds=1),
    )
    sheets = [
        {
            "sheet": "白浆",
            "labels": ["unknown"],
            "processable": True,
            "regions": [{"labels": ["unknown"]}],
        }
    ]

    async def drive():
        apply_unknown_sheet_names(sheets, [{"sheet": "白浆", "value": "白浆"}], owner_id=7)

    asyncio.run(drive())
    assert sheets[0]["model_name"] == "白浆配方"
    assert sheets[0]["model_type"] == "原料"
    assert sheets[0]["labels"] == ["material"]


def test_a_missing_sheet_name_is_asked_again(monkeypatch):
    calls = []

    def fake(messages, _schema, _max_tokens, owner_id=None):
        calls.append(messages)
        if len(calls) == 1:
            return LlmAssistResult(
                used_llm=True,
                data={
                    "sheets": [
                        {"name": "国圣送货单", "type": "送货单"},
                        {"name": "26出货记录", "type": "出货明细"},
                        {"name": "借还材料明细", "type": "借还台账"},
                    ]
                },
            )
        return LlmAssistResult(
            used_llm=True,
            data={"sheets": [{"name": "白浆测算", "type": "测算表"}]},
        )

    monkeypatch.setattr("app.application.reviewed_excel_sheet_names._template_llm_complete", fake)
    sheets = [
        {"sheet": "国圣", "labels": ["delivery"], "processable": True, "regions": []},
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
            "regions": [{"labels": ["unknown"]}],
        },
        {
            "sheet": "白浆",
            "labels": ["unknown"],
            "processable": True,
            "regions": [{"labels": ["unknown"]}],
        },
    ]
    apply_unknown_sheet_names(sheets, [{"sheet": "白浆", "value": "25.12.27亮光白浆"}], owner_id=1)
    assert len(calls) == 2
    assert "不能少、不能合并、不能跳过" in calls[0][0]["content"]
    assert "公式多的表" in calls[0][0]["content"]
    assert "共 4 张表" in calls[0][1]["content"]
    assert "表名依次是：国圣、26出货、借原材料明细、白浆" in calls[0][1]["content"]
    assert "上次没有名字" in calls[1][0]["content"]
    assert "数组长度必须等于 1" in calls[1][0]["content"]
    assert "共 1 张表" in calls[1][1]["content"]
    assert "表名依次是：白浆" in calls[1][1]["content"]
    assert "亮光白浆" in calls[1][1]["content"]
    assert sheets[0]["model_name"] == "国圣送货单"
    assert sheets[3]["model_name"] == "白浆测算"
    assert sheets[3]["model_type"] == "测算表"
    assert sheets[3]["labels"] == ["calculation"]


def test_sheet_naming_retries_a_missing_name_only_once(monkeypatch):
    calls = {"n": 0}

    def fake(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LlmAssistResult(
                used_llm=True,
                data={"sheets": [{"name": "国圣送货单", "type": "送货单"}]},
            )
        return LlmAssistResult(used_llm=True, data={"sheets": []})

    monkeypatch.setattr("app.application.reviewed_excel_sheet_names._template_llm_complete", fake)
    sheets = [
        {"sheet": "国圣", "labels": ["delivery"], "processable": True, "regions": []},
        {"sheet": "白浆", "labels": ["unknown"], "processable": True, "regions": []},
    ]
    apply_unknown_sheet_names(sheets, [], owner_id=1)
    assert calls["n"] == 2
    assert sheets[0]["model_name"] == "国圣送货单"
    assert "model_name" not in sheets[1]


def test_naming_failure_leaves_unknown(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("app.application.reviewed_excel_sheet_names._template_llm_complete", boom)
    sheets = [{"sheet": "白浆", "labels": ["unknown"], "processable": True, "regions": []}]
    apply_unknown_sheet_names(sheets, [], owner_id=1)
    assert sheets[0]["labels"] == ["unknown"] and "model_name" not in sheets[0]
