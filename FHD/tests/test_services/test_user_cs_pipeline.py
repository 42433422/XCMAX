"""测试用户 CS Pipeline 模块。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.user_cs_pipeline import (
    PIPELINE_STAGES,
    PipelineCrmGateError,
    _STAGE_ORDER,
    _default_pipeline,
    _display_name_from_doc,
    _now_iso,
    _pipeline_file,
    _pipeline_roots,
    _read_pipeline_file,
    _stage_rank,
    _write_pipeline_file,
    analyze_customer_pipeline,
    auto_advance_pipeline_if_ready,
    build_pipeline_funnel_summary,
    list_pipeline_client_summaries,
    load_pipeline,
    repair_all_pipelines,
    repair_pipeline_crm,
    save_pipeline,
    set_pipeline_stage,
)


@pytest.fixture
def pipeline_dir(tmp_path):
    """创建临时 pipeline 数据目录。"""
    data_dir = tmp_path / "user_cs_pipelines"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def mock_pipeline_roots(pipeline_dir):
    """mock _pipeline_roots 返回临时目录。"""
    with patch("app.services.user_cs_pipeline._pipeline_roots", return_value=[pipeline_dir]):
        yield pipeline_dir


class TestPipelineStages:
    """测试阶段常量。"""

    def test_stages_not_empty(self):
        assert len(PIPELINE_STAGES) > 0

    def test_stage_order_matches_stages(self):
        stage_ids = [s["id"] for s in PIPELINE_STAGES]
        assert _STAGE_ORDER == stage_ids

    def test_each_stage_has_id_and_label(self):
        for stage in PIPELINE_STAGES:
            assert "id" in stage
            assert "label" in stage
            assert isinstance(stage["id"], str)
            assert isinstance(stage["label"], str)

    def test_idle_is_first_stage(self):
        assert _STAGE_ORDER[0] == "idle"

    def test_delivered_is_last_stage(self):
        assert _STAGE_ORDER[-1] == "delivered"


class TestStageRank:
    """测试阶段排名。"""

    def test_known_stages(self):
        for i, stage_id in enumerate(_STAGE_ORDER):
            assert _stage_rank(stage_id) == i

    def test_unknown_stage_returns_zero(self):
        assert _stage_rank("unknown_stage") == 0

    def test_none_returns_zero(self):
        assert _stage_rank(None) == 0

    def test_empty_string_returns_zero(self):
        assert _stage_rank("") == 0

    def test_rank_ordering(self):
        assert _stage_rank("idle") < _stage_rank("connected")
        assert _stage_rank("connected") < _stage_rank("intake")
        assert _stage_rank("intake") < _stage_rank("signed")
        assert _stage_rank("signed") < _stage_rank("delivered")


class TestNowIso:
    """测试时间戳生成。"""

    def test_returns_string(self):
        result = _now_iso()
        assert isinstance(result, str)

    def test_contains_t_or_z(self):
        result = _now_iso()
        assert "T" in result or "Z" in result or "+" in result


class TestDefaultPipeline:
    """测试默认 pipeline 文档。"""

    def test_returns_dict_with_required_fields(self):
        doc = _default_pipeline(1)
        assert doc["market_user_id"] == 1
        assert doc["stage"] == "idle"
        assert isinstance(doc["timeline"], list)
        assert doc["intake_sent"] is False
        assert doc["updated_at"] != ""

    def test_includes_username(self):
        doc = _default_pipeline(1, username="张三")
        assert doc["username"] == "张三"

    def test_empty_username_stripped(self):
        doc = _default_pipeline(1, username="  ")
        assert doc["username"] == ""

    def test_int_fields_default_zero(self):
        doc = _default_pipeline(1)
        assert doc["landing_contact_id"] == 0
        assert doc["erp_customer_id"] == 0
        assert doc["crm_opportunity_id"] == 0


class TestPipelineFile:
    """测试文件路径生成。"""

    def test_pipeline_file_returns_path(self, mock_pipeline_roots):
        result = _pipeline_file(42)
        assert isinstance(result, Path)
        assert result.name == "42.json"

    def test_pipeline_file_invalid_id_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="market_user_id 无效"):
            _pipeline_file(0)

    def test_pipeline_file_negative_id_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="market_user_id 无效"):
            _pipeline_file(-1)


class TestReadWritePipelineFile:
    """测试文件读写。"""

    def test_write_and_read_roundtrip(self, pipeline_dir):
        doc = _default_pipeline(1, username="test")
        path = pipeline_dir / "1.json"
        written = _write_pipeline_file(path, doc)
        assert path.is_file()

        read = _read_pipeline_file(path)
        assert read is not None
        assert read["market_user_id"] == 1
        assert read["username"] == "test"

    def test_read_nonexistent_file(self, pipeline_dir):
        path = pipeline_dir / "999.json"
        result = _read_pipeline_file(path)
        assert result is None

    def test_read_invalid_json(self, pipeline_dir):
        path = pipeline_dir / "bad.json"
        path.write_text("not json at all", encoding="utf-8")
        result = _read_pipeline_file(path)
        assert result is None

    def test_read_non_dict_json(self, pipeline_dir):
        path = pipeline_dir / "array.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        result = _read_pipeline_file(path)
        assert result is None

    def test_write_creates_parent_dirs(self, pipeline_dir):
        deep_path = pipeline_dir / "sub" / "1.json"
        doc = _default_pipeline(1)
        _write_pipeline_file(deep_path, doc)
        assert deep_path.is_file()

    def test_write_updates_timestamp(self, pipeline_dir):
        path = pipeline_dir / "1.json"
        doc = _default_pipeline(1)
        written = _write_pipeline_file(path, doc)
        assert "updated_at" in written
        assert written["updated_at"] != ""


class TestLoadPipeline:
    """测试加载 pipeline。"""

    def test_load_creates_default_when_missing(self, mock_pipeline_roots):
        doc = load_pipeline(1, username="新用户")
        assert doc["market_user_id"] == 1
        assert doc["username"] == "新用户"
        assert doc["stage"] == "idle"

    def test_load_reads_existing(self, mock_pipeline_roots):
        doc1 = load_pipeline(1, username="用户A")
        doc2 = load_pipeline(1, username="用户B")
        assert doc2["username"] == "用户A"

    def test_load_fills_missing_defaults(self, mock_pipeline_roots):
        path = _pipeline_file(1)
        partial = {"market_user_id": 1}
        path.write_text(json.dumps(partial), encoding="utf-8")

        doc = load_pipeline(1)
        assert doc["stage"] == "idle"
        assert doc["timeline"] == []

    def test_load_sets_username_if_empty(self, mock_pipeline_roots):
        doc1 = load_pipeline(1, username="")
        doc2 = load_pipeline(1, username="张三")
        assert doc2["username"] == "张三"


class TestSavePipeline:
    """测试保存 pipeline。"""

    def test_save_pipeline(self, mock_pipeline_roots):
        doc = _default_pipeline(1, username="test")
        result = save_pipeline(doc)
        assert result["market_user_id"] == 1

    def test_save_pipeline_missing_id_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="pipeline 缺少 market_user_id"):
            save_pipeline({})

    def test_save_pipeline_zero_id_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="pipeline 缺少 market_user_id"):
            save_pipeline({"market_user_id": 0})

    def test_save_pipeline_negative_id_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="pipeline 缺少 market_user_id"):
            save_pipeline({"market_user_id": -1})


class TestSetPipelineStage:
    """测试设置阶段。"""

    def test_set_stage_to_connected(self, mock_pipeline_roots):
        doc = set_pipeline_stage(1, "connected", username="test")
        assert doc["stage"] == "connected"

    def test_set_stage_adds_timeline_entry(self, mock_pipeline_roots):
        doc = set_pipeline_stage(1, "connected", source="test", note="test note")
        assert len(doc["timeline"]) > 0
        entry = doc["timeline"][-1]
        assert entry["stage"] == "connected"
        assert entry["source"] == "test"
        assert entry["note"] == "test note"

    def test_set_same_stage_no_timeline_entry(self, mock_pipeline_roots):
        doc1 = set_pipeline_stage(1, "connected")
        tl_count = len(doc1["timeline"])
        doc2 = set_pipeline_stage(1, "connected")
        assert len(doc2["timeline"]) == tl_count

    def test_set_unknown_stage_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="未知阶段"):
            set_pipeline_stage(1, "invalid_stage")

    def test_set_empty_stage_raises(self, mock_pipeline_roots):
        with pytest.raises(ValueError, match="未知阶段"):
            set_pipeline_stage(1, "")

    def test_timeline_keeps_last_30(self, mock_pipeline_roots):
        for i in range(35):
            stage = _STAGE_ORDER[i % len(_STAGE_ORDER)]
            set_pipeline_stage(1, stage, source="test")
        doc = load_pipeline(1)
        assert len(doc["timeline"]) <= 30


class TestDisplayNameFromDoc:
    """测试显示名称提取。"""

    def test_from_intake_company(self):
        doc = {"intake_form": {"company": "七彩乐园"}}
        assert _display_name_from_doc(doc) == "七彩乐园"

    def test_from_intake_name(self):
        doc = {"intake_form": {"name": "张三"}}
        assert _display_name_from_doc(doc) == "张三"

    def test_from_erp_customer_name(self):
        doc = {"erp_customer_name": "ERP客户"}
        assert _display_name_from_doc(doc) == "ERP客户"

    def test_from_username(self):
        doc = {"username": "user123"}
        assert _display_name_from_doc(doc) == "user123"

    def test_priority_company_over_name(self):
        doc = {"intake_form": {"company": "公司", "name": "张三"}}
        assert _display_name_from_doc(doc) == "公司"

    def test_priority_intake_over_erp(self):
        doc = {"intake_form": {"company": "公司"}, "erp_customer_name": "ERP"}
        assert _display_name_from_doc(doc) == "公司"

    def test_empty_doc(self):
        doc = {}
        assert _display_name_from_doc(doc) == ""

    def test_empty_intake_form(self):
        doc = {"intake_form": {"company": "", "name": ""}, "erp_customer_name": ""}
        assert _display_name_from_doc(doc) == ""

    def test_fallback_to_username_arg(self):
        doc = {}
        assert _display_name_from_doc(doc, username="arg_user") == "arg_user"


class TestAutoAdvancePipeline:
    """测试自动推进 pipeline。"""

    def test_advance_to_intake_done(self, mock_pipeline_roots):
        doc = load_pipeline(1)
        doc["intake_submitted_at"] = "2026-01-01T00:00:00"
        save_pipeline(doc)

        doc, advanced = auto_advance_pipeline_if_ready(1)
        assert advanced is True
        assert doc["stage"] == "intake_done"

    def test_advance_to_intake(self, mock_pipeline_roots):
        doc = load_pipeline(1)
        doc["intake_sent"] = True
        save_pipeline(doc)

        doc, advanced = auto_advance_pipeline_if_ready(1)
        assert advanced is True
        assert doc["stage"] == "intake"

    def test_advance_to_connected(self, mock_pipeline_roots):
        doc = load_pipeline(1)
        doc["connected_welcome_sent"] = True
        save_pipeline(doc)

        doc, advanced = auto_advance_pipeline_if_ready(1)
        assert advanced is True
        assert doc["stage"] == "connected"

    def test_no_advance_when_already_advanced(self, mock_pipeline_roots):
        doc = set_pipeline_stage(1, "signed")
        doc2, advanced = auto_advance_pipeline_if_ready(1)
        assert advanced is False

    def test_advance_priority_intake_done_over_intake(self, mock_pipeline_roots):
        doc = load_pipeline(1)
        doc["intake_sent"] = True
        doc["intake_submitted_at"] = "2026-01-01T00:00:00"
        save_pipeline(doc)

        doc, advanced = auto_advance_pipeline_if_ready(1)
        assert doc["stage"] == "intake_done"


class TestAnalyzeCustomerPipeline:
    """测试客户 pipeline 分析。"""

    def test_sets_last_message_preview(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(
            1, username="test", message_texts=["你好，我想开单"]
        )
        assert doc["last_message_preview"] == "你好，我想开单"

    def test_sets_intake_sent(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(1, intake_sent=True)
        assert doc["intake_sent"] is True

    def test_advances_to_connected_on_binding(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(1, has_binding=True)
        assert doc["stage"] == "connected"

    def test_advances_to_intake_when_sent(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(1, intake_sent=True)
        assert doc["stage"] == "intake"

    def test_no_advance_without_triggers(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(1)
        assert doc["stage"] == "idle"

    def test_empty_message_texts(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(1, message_texts=[])
        assert doc["last_message_preview"] == ""

    def test_none_message_texts(self, mock_pipeline_roots):
        doc = analyze_customer_pipeline(1, message_texts=None)
        assert doc["last_message_preview"] == ""

    def test_message_preview_truncated(self, mock_pipeline_roots):
        long_text = "x" * 1000
        doc = analyze_customer_pipeline(1, message_texts=[long_text])
        assert len(doc["last_message_preview"]) <= 500

    def test_binding_does_not_downgrade(self, mock_pipeline_roots):
        set_pipeline_stage(1, "signed")
        doc = analyze_customer_pipeline(1, has_binding=True)
        assert doc["stage"] == "signed"


class TestRepairPipelineCrm:
    """测试 CRM 修复。"""

    def test_repair_sets_synced_at(self, mock_pipeline_roots):
        doc = load_pipeline(1)
        assert doc.get("crm_db_synced_at", "") == ""

        doc = repair_pipeline_crm(1)
        assert doc["crm_db_synced_at"] != ""


class TestRepairAllPipelines:
    """测试批量修复。"""

    def test_repair_all(self, mock_pipeline_roots):
        load_pipeline(1, username="a")
        load_pipeline(2, username="b")
        result = repair_all_pipelines()
        assert result["repaired"] == 2

    def test_repair_all_empty(self, mock_pipeline_roots):
        result = repair_all_pipelines()
        assert result["repaired"] == 0


class TestListPipelineClientSummaries:
    """测试客户列表摘要。"""

    def test_list_summaries(self, mock_pipeline_roots):
        load_pipeline(1, username="user1")
        load_pipeline(2, username="user2")
        summaries = list_pipeline_client_summaries()
        assert len(summaries) == 2
        assert all("market_user_id" in s for s in summaries)
        assert all("stage" in s for s in summaries)
        assert all("display_name" in s for s in summaries)

    def test_list_summaries_empty(self, mock_pipeline_roots):
        summaries = list_pipeline_client_summaries()
        assert summaries == []

    def test_list_summaries_sorted(self, mock_pipeline_roots):
        load_pipeline(2, username="aaa")
        load_pipeline(1, username="zzz")
        summaries = list_pipeline_client_summaries()
        names = [s["username"] for s in summaries]
        assert names == sorted(names)


class TestBuildPipelineFunnelSummary:
    """测试漏斗摘要。"""

    def test_funnel_summary_structure(self, mock_pipeline_roots):
        load_pipeline(1, username="user1")
        summary = build_pipeline_funnel_summary()
        assert "stages" in summary
        assert "total_clients" in summary
        assert "counts" in summary
        assert summary["total_clients"] == 1

    def test_funnel_summary_stages_match_pipeline_stages(self, mock_pipeline_roots):
        summary = build_pipeline_funnel_summary()
        stage_ids = [s["id"] for s in summary["stages"]]
        assert stage_ids == _STAGE_ORDER

    def test_funnel_summary_max_clients_per_stage(self, mock_pipeline_roots):
        for i in range(10):
            load_pipeline(i + 1, username=f"user{i}")
        summary = build_pipeline_funnel_summary(max_clients_per_stage=3)
        for stage in summary["stages"]:
            assert len(stage["clients"]) <= 3

    def test_funnel_summary_empty(self, mock_pipeline_roots):
        summary = build_pipeline_funnel_summary()
        assert summary["total_clients"] == 0
