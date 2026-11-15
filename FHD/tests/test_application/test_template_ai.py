"""模板库 AI 起名与语义匹配的降级边界。"""

from __future__ import annotations

from typing import Any

from app.application import template_ai
from app.application.elt.llm_assist_runtime import LlmAssistResult


def _result(data: dict[str, Any], *, degraded: bool = False) -> LlmAssistResult:
    return LlmAssistResult(used_llm=True, degraded=degraded, data=data)


def test_suggest_template_name_uses_model_answer(monkeypatch):
    monkeypatch.setattr(
        template_ai, "_complete", lambda *a, **k: _result({"name": "《材料采购明细》", "confidence": 0.9})
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
        template_ai, "_complete", lambda *a, **k: _result({"name": "材料采购明细", "confidence": 0.2})
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
    monkeypatch.setattr(template_ai, "_complete", lambda *a, **k: _result({"index": 5, "confidence": 0.9}))
    assert template_ai.rank_templates(requirement="q", candidates=candidates) is None
    monkeypatch.setattr(template_ai, "_complete", lambda *a, **k: _result({"index": 0, "confidence": 0.1}))
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
        template_ai, "_complete", lambda *a, **k: _result({"name": "材料采购明细", "confidence": 0.9})
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
