"""小猫分析列表/详情/导出的归属过滤测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.shared_services.kitten_report.save_service import AnalysisSaveService


def _write(directory: Path, analysis_id: str, **owner) -> None:
    (directory / f"financial_{analysis_id}.json").write_text(
        json.dumps(
            {
                "id": analysis_id,
                "type": "financial",
                "created_at": "2026-11-17",
                "data": {"k": "v"},
                **owner,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed(directory: Path) -> None:
    _write(directory, "a_own", owner_id="7", tenant_id="1")
    _write(directory, "b_other", owner_id="8", tenant_id="1")
    _write(directory, "c_legacy")


def test_list_only_returns_own_records(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    _seed(tmp_path)
    items = service.list_saved_analyses(owner_id=7, tenant_id=1)
    assert [item["id"] for item in items] == ["a_own"]


def test_list_admin_sees_all(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    _seed(tmp_path)
    items = service.list_saved_analyses(allow_all=True)
    assert {item["id"] for item in items} == {"a_own", "b_other", "c_legacy"}


def test_get_hides_other_and_legacy(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    _seed(tmp_path)
    assert service.get_analysis("a_own", owner_id=7, tenant_id=1) is not None
    assert service.get_analysis("b_other", owner_id=7, tenant_id=1) is None
    assert service.get_analysis("c_legacy", owner_id=7, tenant_id=1) is None


def test_export_denies_other_users_record(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    _seed(tmp_path)
    denied = service.export_analysis_to_xlsx("b_other", owner_id=7, tenant_id=1)
    assert denied["success"] is False
