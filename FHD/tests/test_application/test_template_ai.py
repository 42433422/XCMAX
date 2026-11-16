"""模板库 AI 起名与语义匹配的降级边界。"""

from __future__ import annotations

from typing import Any

from app.application import template_ai
from app.application.elt.llm_assist_runtime import LlmAssistResult


def _result(data: dict[str, Any], *, degraded: bool = False) -> LlmAssistResult:
    return LlmAssistResult(used_llm=True, degraded=degraded, data=data)


def test_suggest_template_name_uses_model_answer(monkeypatch):
    monkeypatch.setattr(
        template_ai,
        "_complete",
        lambda *a, **k: _result({"name": "《材料采购明细》", "confidence": 0.9}),
    )
    name = template_ai.suggest_template_name(
        file_name="2026.10月综合系列.xlsx", sheet_title="Sheet1", target_type="materials"
    )
    assert name == "材料采购明细"


def test_suggest_template_name_falls_back_when_degraded(monkeypatch):
    monkeypatch.setattr(
        template_ai, "_complete", lambda *a, **k: _result({"name": "材料采购明细"}, degraded=True)
    )
    assert template_ai.suggest_template_name(file_name="a.xlsx") == ""


def test_suggest_template_name_rejects_placeholder_and_low_confidence(monkeypatch):
    monkeypatch.setattr(template_ai, "_complete", lambda *a, **k: _result({"name": "Sheet1-模板"}))
    assert template_ai.suggest_template_name(file_name="a.xlsx") == ""
    monkeypatch.setattr(
        template_ai,
        "_complete",
        lambda *a, **k: _result({"name": "材料采购明细", "confidence": 0.2}),
    )
    assert template_ai.suggest_template_name(file_name="a.xlsx") == ""


def test_is_meaningless_name():
    assert template_ai.is_meaningless_name("2026.10月综合系列-Sheet1")
    assert template_ai.is_meaningless_name("客户资料-区段2")
    assert not template_ai.is_meaningless_name("材料采购明细")


def test_rank_templates_returns_picked_candidate(monkeypatch):
    candidates = [{"name": "发货单版式"}, {"name": "客户对账表"}]
    monkeypatch.setattr(
        template_ai,
        "_complete",
        lambda *a, **k: _result({"index": 1, "confidence": 0.82, "reason": "用户在问对账"}),
    )
    picked = template_ai.rank_templates(requirement="用对账模板", candidates=candidates)
    assert picked is not None
    assert picked["template"]["name"] == "客户对账表"
    assert picked["confidence"] == 0.82


def test_rank_templates_rejects_out_of_range_or_unconfident(monkeypatch):
    candidates = [{"name": "发货单版式"}]
    monkeypatch.setattr(
        template_ai, "_complete", lambda *a, **k: _result({"index": 5, "confidence": 0.9})
    )
    assert template_ai.rank_templates(requirement="q", candidates=candidates) is None
    monkeypatch.setattr(
        template_ai, "_complete", lambda *a, **k: _result({"index": 0, "confidence": 0.1})
    )
    assert template_ai.rank_templates(requirement="q", candidates=candidates) is None
    monkeypatch.setattr(template_ai, "_complete", lambda *a, **k: _result({}, degraded=True))
    assert template_ai.rank_templates(requirement="q", candidates=candidates) is None


class _FakeService:
    def __init__(self, templates: list[dict[str, Any]]):
        self._templates = templates
        self.updated: list[tuple[int, dict[str, Any]]] = []

    def get_templates(self):
        return {"templates": self._templates}

    def update_template(self, template_id: int, payload: dict[str, Any]):
        self.updated.append((template_id, payload))
        return {"success": True, "id": template_id}


def test_rename_meaningless_templates_is_bounded_and_skips_duplicates(monkeypatch):
    service = _FakeService(
        [
            {"source": "db", "db_id": 1, "name": "综合系列-Sheet1", "filename": "a.xlsx"},
            {"source": "db", "db_id": 2, "name": "客户对账表", "filename": "b.xlsx"},
            {"source": "db", "db_id": 3, "name": "综合系列-区段2", "filename": "c.xlsx"},
        ]
    )
    monkeypatch.setattr(
        template_ai, "_complete", lambda *a, **k: _result({"name": "客户对账表", "confidence": 0.9})
    )
    renamed = template_ai.rename_meaningless_templates(service, limit=3)
    # 起出来的名字与已有模板重名时不改，避免模板库出现两个同名条目。
    assert renamed == []
    assert service.updated == []


def test_rename_meaningless_templates_renames_placeholder(monkeypatch):
    service = _FakeService(
        [{"source": "db", "db_id": 7, "name": "综合系列-Sheet1", "filename": "a.xlsx"}]
    )
    monkeypatch.setattr(
        template_ai,
        "_complete",
        lambda *a, **k: _result({"name": "材料采购明细", "confidence": 0.9}),
    )
    renamed = template_ai.rename_meaningless_templates(service)
    assert renamed == [{"id": "7", "from": "综合系列-Sheet1", "to": "材料采购明细"}]
    assert service.updated == [(7, {"template_name": "材料采购明细"})]


def test_resolve_template_ranks_multiple_candidates(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt

    candidates = [
        {"id": "t1", "name": "发货单版式", "target_type": "customers"},
        {"id": "t2", "name": "客户对账表", "target_type": "customers"},
    ]

    class _Svc:
        def list_templates(self, db, *, owner_user_id):
            return candidates

    class _DB:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "app.application.elt.target_detection.detect_elt_target",
        lambda *a, **k: {"target_type": "customers"},
    )
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: _Svc())
    monkeypatch.setattr(tools_workflow_elt, "get_db", lambda: _DB())
    monkeypatch.setattr(
        "app.application.template_ai.rank_templates",
        lambda **k: {"index": 1, "confidence": 0.75, "reason": "", "template": candidates[1]},
    )
    target_type, template = tools_workflow_elt._resolve_template(
        {"storage_path": "/tmp/客户对账.xlsx"}, 1
    )
    assert target_type == "customers"
    assert template["id"] == "t2"
    assert template["match_confidence"] == 0.75


def test_propose_import_template_filters_unknown_target(monkeypatch):
    monkeypatch.setattr(
        template_ai,
        "_complete",
        lambda *a, **k: _result(
            {
                "target_type": "not_a_target",
                "confidence": 0.9,
                "field_mappings": [{"source": "客户名称", "target": "customer_name"}],
            }
        ),
    )
    assert (
        template_ai.propose_import_template(
            file_name="a.xlsx",
            headers=["客户名称"],
            targets=[{"type": "customers", "label": "客户", "fields": []}],
        )
        is None
    )


def test_propose_import_template_returns_mappings_and_index(monkeypatch):
    monkeypatch.setattr(
        template_ai,
        "_complete",
        lambda *a, **k: _result(
            {
                "target_type": "customers",
                "template_index": 0,
                "name": "客户资料",
                "confidence": 0.88,
                "field_mappings": [
                    {"source": "客户名称", "target": "customer_name", "confidence": 0.95}
                ],
            }
        ),
    )
    proposal = template_ai.propose_import_template(
        file_name="a.xlsx",
        headers=["客户名称"],
        samples={"客户名称": ["甲公司"]},
        candidates=[{"name": "客户资料", "target_type": "customers"}],
        targets=[{"type": "customers", "label": "客户", "fields": []}],
    )
    assert proposal is not None
    assert proposal["template_index"] == 0
    assert proposal["name"] == "客户资料"
    assert proposal["field_mappings"][0]["target"] == "customer_name"


def _features(headers=("客户名称", "电话")):
    return {"headers": list(headers), "samples": {}, "sheet": "Sheet1", "file_name": "客户表.xlsx"}


class _EltService:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def create_template(self, db, **kwargs):
        self.calls.append(kwargs)
        return {
            "id": "tpl-ai",
            "name": kwargs["name"],
            "target_type": kwargs["target_type"],
            "current_version": 1,
            "version": {"source_features": kwargs.get("source_features") or {}},
        }


class _DB:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


def test_create_ai_template_drops_invalid_mappings(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt

    service = _EltService()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: service)
    monkeypatch.setattr(tools_workflow_elt, "get_db", lambda: _DB())
    created = tools_workflow_elt._create_ai_import_template(
        1,
        _features(),
        {
            "target_type": "customers",
            "name": "客户资料",
            "confidence": 0.88,
            "reason": "客户表",
            "field_mappings": [
                {"source": "客户名称", "target": "customer_name", "confidence": 0.95},
                {"source": "不存在的列", "target": "contact_person", "confidence": 0.9},
                {"source": "电话", "target": "未知字段", "confidence": 0.9},
                {"source": "电话", "target": "contact_phone", "confidence": 0.8},
            ],
        },
        [],
    )
    assert created["ai_generated"] is True
    draft = service.calls[0]["draft"]
    assert [item["target"] for item in draft["field_mappings"]] == [
        "customer_name",
        "contact_phone",
    ]
    assert service.calls[0]["name"] == "客户资料"


def test_create_ai_template_requires_required_field(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt

    service = _EltService()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: service)
    monkeypatch.setattr(tools_workflow_elt, "get_db", lambda: _DB())
    created = tools_workflow_elt._create_ai_import_template(
        1,
        _features(),
        {
            "target_type": "customers",
            "name": "客户资料",
            "confidence": 0.88,
            "field_mappings": [{"source": "电话", "target": "contact_phone", "confidence": 0.9}],
        },
        [],
    )
    assert created == {}
    assert service.calls == []


def test_create_ai_template_reuses_same_header_signature(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt

    service = _EltService()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: service)
    monkeypatch.setattr(tools_workflow_elt, "get_db", lambda: _DB())
    existing = {
        "id": "tpl-old",
        "name": "客户资料",
        "target_type": "customers",
        "version": {"source_features": {"headers": ["电话", "客户名称"]}},
    }
    created = tools_workflow_elt._create_ai_import_template(
        1,
        _features(),
        {
            "target_type": "customers",
            "confidence": 0.88,
            "field_mappings": [{"source": "客户名称", "target": "customer_name"}],
        },
        [existing],
    )
    assert created["id"] == "tpl-old"
    assert created["matched_by"] == "signature"
    assert service.calls == []
