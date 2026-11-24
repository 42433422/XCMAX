"""知识库来源定时同步：环境开关、单轮执行、多库汇总与线程启停。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.application.dataset_rag import auto_sync_scheduler
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_ORIGINAL = "退款政策：签收后七天内可以申请退款。" * 5


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _seed(service: DatasetRagApplicationService, dataset_id: str, source: str) -> None:
    result = service.ingest_document(
        dataset_id=dataset_id,
        source=source,
        text=_ORIGINAL,
        tenant_id="t1",
        metadata={
            "source_kind": "url",
            "source_ref": f"https://docs.example.com/{dataset_id}/{source}",
        },
        access_context=_ctx(),
    )
    assert result["success"] is True


def test_interval_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_AUTO_REFRESH_HOURS", raising=False)
    assert auto_sync_scheduler.auto_refresh_interval_hours() == 0.0

    monkeypatch.setenv("XCAGI_KB_AUTO_REFRESH_HOURS", "bad")
    assert auto_sync_scheduler.auto_refresh_interval_hours() == 0.0

    monkeypatch.setenv("XCAGI_KB_AUTO_REFRESH_HOURS", "2.5")
    assert auto_sync_scheduler.auto_refresh_interval_hours() == 2.5


def test_run_once_is_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_AUTO_REFRESH_HOURS", raising=False)

    assert auto_sync_scheduler.run_due_source_sync_once() == {
        "skipped": True,
        "reason": "disabled",
    }


def test_run_once_passes_interval_to_service() -> None:
    fake = SimpleNamespace(refresh_all_due_sources=Mock(return_value={"processed": 2}))

    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=fake,
    ):
        outcome = auto_sync_scheduler.run_due_source_sync_once(interval_hours=6)

    assert outcome == {"processed": 2}
    fake.refresh_all_due_sources.assert_called_once_with(max_age_hours=6)


def test_run_once_swallows_recoverable_errors() -> None:
    def _boom(**_kwargs):
        raise OSError("store unavailable")

    fake = SimpleNamespace(refresh_all_due_sources=_boom)
    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=fake,
    ):
        outcome = auto_sync_scheduler.run_due_source_sync_once(interval_hours=1)

    assert outcome["success"] is False
    assert "store unavailable" in outcome["error"]


def test_refresh_all_due_sources_aggregates_then_skips_fresh(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service, "kb1", "退款.md")
    _seed(service, "kb2", "退款.md")

    page = SimpleNamespace(text=_ORIGINAL, title="页面", url="https://docs.example.com")
    with patch("app.infrastructure.document_parsing.web_fetch.fetch_url_text", return_value=page):
        first = service.refresh_all_due_sources(max_age_hours=24)
        second = service.refresh_all_due_sources(max_age_hours=24)

    assert first["datasets"] == 2
    assert first["processed"] == 2
    assert first["unchanged"] == 2
    assert second["processed"] == 0
    assert second["fresh"] == 2


def test_status_reports_source_sync_health(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service, "kb1", "退款.md")
    service.ingest_document(
        dataset_id="kb1",
        source="内联.md",
        text="内联内容没有外部坐标。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    before = service.status("kb1", tenant_id="t1", access_context=_ctx())["source_sync"]
    assert before["refreshable_documents"] == 1
    assert before["never_synced"] == 1
    assert before["last_synced_at"] == ""

    page = SimpleNamespace(text=_ORIGINAL, title="页面", url="https://docs.example.com")
    with patch("app.infrastructure.document_parsing.web_fetch.fetch_url_text", return_value=page):
        service.refresh_documents("kb1", tenant_id="t1", access_context=_ctx())

    after = service.status("kb1", tenant_id="t1", access_context=_ctx())["source_sync"]
    assert after["refreshable_documents"] == 1
    assert after["never_synced"] == 0
    assert after["last_synced_at"]


def test_scheduler_start_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_AUTO_REFRESH_HOURS", raising=False)
    assert auto_sync_scheduler.start_auto_sync_scheduler() is False

    monkeypatch.setenv("XCAGI_KB_AUTO_REFRESH_HOURS", "1")
    monkeypatch.setattr(auto_sync_scheduler, "INITIAL_DELAY_SECONDS", 30)
    try:
        assert auto_sync_scheduler.start_auto_sync_scheduler() is True
        assert auto_sync_scheduler.start_auto_sync_scheduler() is True
    finally:
        auto_sync_scheduler.stop_auto_sync_scheduler()
    assert auto_sync_scheduler.start_auto_sync_scheduler() is True
    auto_sync_scheduler.stop_auto_sync_scheduler()
