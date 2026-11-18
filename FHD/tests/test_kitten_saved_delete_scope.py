"""小猫分析删除的归属校验测试：本人可删、他人不可删、历史无主记录仅管理员可删。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.shared_services.kitten_report.save_service import AnalysisSaveService


def _write_analysis(directory: Path, analysis_id: str, **owner) -> Path:
    path = directory / f"financial_{analysis_id}.json"
    path.write_text(
        json.dumps(
            {"id": analysis_id, "type": "financial", "created_at": "2026-11-17", **owner},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_owner_can_delete_own_analysis(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    path = _write_analysis(tmp_path, "analysis_1", owner_id="7", tenant_id="1")
    result = service.delete_analysis("analysis_1", owner_id=7, tenant_id=1)
    assert result is True
    assert not path.exists()


def test_other_user_cannot_delete(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    path = _write_analysis(tmp_path, "analysis_2", owner_id="7", tenant_id="1")
    result = service.delete_analysis("analysis_2", owner_id=8, tenant_id=1)
    assert isinstance(result, dict)
    assert result["code"] == "ANALYSIS_FORBIDDEN"
    assert path.exists()


def test_cross_tenant_cannot_delete(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    path = _write_analysis(tmp_path, "analysis_3", owner_id="7", tenant_id="1")
    result = service.delete_analysis("analysis_3", owner_id=7, tenant_id=2)
    assert isinstance(result, dict)
    assert result["code"] == "ANALYSIS_FORBIDDEN"
    assert path.exists()


def test_legacy_unowned_requires_admin(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    path = _write_analysis(tmp_path, "analysis_4")
    denied = service.delete_analysis("analysis_4", owner_id=7, tenant_id=1)
    assert isinstance(denied, dict)
    assert denied["code"] == "ANALYSIS_OWNER_UNKNOWN"
    assert path.exists()

    allowed = service.delete_analysis("analysis_4", owner_id=7, tenant_id=1, allow_unowned=True)
    assert allowed is True
    assert not path.exists()


def test_save_records_owner_metadata(tmp_path):
    service = AnalysisSaveService(str(tmp_path))
    saved = service.save_analysis("financial", {"k": "v"}, owner_id=7, tenant_id=1)
    assert saved["success"] is True
    payload = json.loads(Path(saved["filepath"]).read_text(encoding="utf-8"))
    assert payload["owner_id"] == "7"
    assert payload["tenant_id"] == "1"
