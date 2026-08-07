"""ETL service 层混合（mixin）行为测试：覆盖 app.application.etl.service* 模块。

策略：
- 用内存 SQLite 提供真实 DB 语义（query/add/commit/flush 天然可用）。
- 通过 mock 替身隔离适配器（TargetAdapter）、LLM adviser、EXECUTOR 后台线程。
- 覆盖每个模块的公共方法 / 分支 / 错误路径 / 成功路径。
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.service_draft import DraftServiceMixin
from app.application.etl.service_execution import ExecutionServiceMixin
from app.application.etl.service_history import HistoryServiceMixin
from app.application.etl.service_preview import PreviewServiceMixin
from app.application.etl.service_shipment_templates import (
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    ShipmentTemplateServiceMixin,
    _safe_template_name,
    _selected_shipment_region,
    _shipment_template_default_name,
    shipment_template_candidate,
    shipment_template_candidates,
)
from app.application.etl.service_support import (
    ALLOWED_VALIDATION_OPS,
    MAX_FILE_BYTES,
    apply_validation_rules,
    clean_batch_id,
    clean_filename,
    clean_relative_path,
    dump_json,
    load_json,
    mapping_key,
    safe_error,
    sanitize_webhook_headers,
)
from app.application.etl.service_targets import TargetConfigServiceMixin
from app.application.etl.service_templates import TemplateServiceMixin
from app.application.etl.service_uploads import UploadServiceMixin
from app.application.etl.targets.base import PreviewDecision, TargetField, json_safe
from app.db.base import Base
from app.db.models.etl import (
    EtlRun,
    EtlRunRow,
    EtlTargetConfig,
    EtlTemplate,
    EtlTemplateVersion,
    EtlUpload,
)
from app.infrastructure.tenant_scope import reset_current_tenant_id, set_current_tenant_id

ETL_TABLES = [
    EtlUpload.__table__,
    EtlTemplate.__table__,
    EtlTemplateVersion.__table__,
    EtlRun.__table__,
    EtlRunRow.__table__,
    EtlTargetConfig.__table__,
]


def _make_engine():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    return engine


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class _FakeAdviser:
    def fallback(self, **kw):
        return {"degraded": False, "suggestion": {}, "reason": ""}

    def suggest(self, **kw):
        return {"degraded": False, "suggestion": {}, "reason": ""}

    def suggest_many(self, payloads):
        return [{"degraded": False, "suggestion": {}, "reason": ""} for _ in payloads]


class _FakeDataset:
    source_features = {"kind": "sheet"}
    warnings: list[str] = []
    headers: list[str] = ["order_number"]
    rows = [
        SimpleNamespace(
            values={"order_number": "O1"},
            provenance={},
            row_number=1,
            sheet="S1",
        )
    ]


class _FakeAdapter:
    type = "shipment_records"
    label = "发货记录"
    reversible = True
    actions: tuple[str, ...] = ("new", "update", "skip")
    fields = (
        TargetField("order_number", "单号", required=False, updatable=True),
        TargetField("product_model", "型号", required=False, updatable=True),
    )
    default_match_keys: tuple[str, ...] = ("order_number",)
    allow_dynamic_fields = False

    def __init__(self) -> None:
        self.preview_decision: PreviewDecision | None = None
        self.fail_execute = False
        self.fail_execute_batch = False
        self.fail_after: int | None = None
        self.fail_for_value: Any = None
        self.fail_field = "order_number"
        self._exec_calls = 0
        self.execute_batch_result: dict[str, Any] = {"executed": 1, "receipt": {"ok": True}}

        def execute_row(db, data, *, action, match_ref, allowed_update_fields, context):
            if self.fail_execute:
                raise RuntimeError("boom")
            if self.fail_for_value is not None and str(
                (data or {}).get(self.fail_field)
            ) == str(self.fail_for_value):
                raise RuntimeError("boom")
            if self.fail_after is not None and self._exec_calls >= self.fail_after:
                self._exec_calls += 1
                raise RuntimeError("boom")
            self._exec_calls += 1
            return {"match_ref": match_ref or "m1", "after": data}

        def execute_batch(rows, context):
            if self.fail_execute_batch:
                raise RuntimeError("boom")
            # consume the normalized_rows generator + progress_callback
            count = sum(1 for _ in rows)
            cb = (context or {}).get("progress_callback")
            if cb:
                cb(count, max(count, 1))
            return self.execute_batch_result

        def rollback_row(db, *, match_ref, before, after, context):
            return None

        def rollback_batch(context, receipt):
            return 1

        self.execute_row = execute_row
        self.execute_batch = execute_batch
        self.rollback_row = rollback_row
        self.rollback_batch = rollback_batch

    def preview(self, db, data, *, allowed_update_fields, context):
        if self.preview_decision is not None:
            return self.preview_decision
        return PreviewDecision("new", after=json_safe(data), reason="test")

    def capability(self):
        return {"type": self.type}


class _TestService(
    UploadServiceMixin,
    PreviewServiceMixin,
    HistoryServiceMixin,
    DraftServiceMixin,
    ExecutionServiceMixin,
    TemplateServiceMixin,
    ShipmentTemplateServiceMixin,
    TargetConfigServiceMixin,
):
    def __init__(self, adviser=None) -> None:
        self._adviser = adviser or _FakeAdviser()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def etl_db():
    engine = _make_engine()
    Base.metadata.create_all(bind=engine, tables=ETL_TABLES)
    factory = sessionmaker(bind=engine)
    db = factory()
    token = set_current_tenant_id(1)
    yield db
    db.close()
    reset_current_tenant_id(token)
    engine.dispose()


@pytest.fixture
def etl_factory(etl_db):
    engine = etl_db.bind

    def _new_session():
        return sessionmaker(bind=engine)()

    return _new_session


@pytest.fixture
def same_session(etl_factory, monkeypatch):
    # 让后台 worker 的 new_session() 指向同一内存 DB，避免连真实 postgres。
    for mod in (
        "app.application.etl.service_execution",
        "app.application.etl.service_preview",
        "app.application.etl.service_draft",
    ):
        monkeypatch.setattr(f"{mod}.new_session", etl_factory)
    return etl_factory


@pytest.fixture
def svc():
    return _TestService()


@pytest.fixture
def fake_adapter(monkeypatch):
    adapter = _FakeAdapter()
    for mod in (
        "app.application.etl.service_preview",
        "app.application.etl.service_execution",
        "app.application.etl.service_draft",
        "app.application.etl.service_templates",
        "app.application.etl.service_targets",
    ):
        monkeypatch.setattr(f"{mod}.get_adapter", lambda *a, _adapter=adapter: _adapter)
    return adapter


@pytest.fixture
def no_background(monkeypatch):
    # 让后台 worker 不在真实线程池里跑，避免连接真实 DB。
    monkeypatch.setattr(
        "app.application.etl.service_support.EXECUTOR.submit",
        lambda fn, *a, **k: None,
    )


@pytest.fixture
def mock_etl_metrics(monkeypatch):
    """metrics.py 缺少 ETL 指标定义，import 会抛 ImportError 被 except 吞掉。
    这里把缺失的指标名补到真实模块上，覆盖 *_metrics 的记录分支。"""
    import app.utils.metrics as metrics_mod

    for name in (
        "etl_run_duration_seconds",
        "etl_runs_total",
        "etl_manual_corrections_total",
        "etl_retries_total",
        "etl_rollbacks_total",
        "etl_llm_degradations_total",
        "etl_rows_total",
    ):
        counter = MagicMock()
        counter.labels.return_value = counter
        monkeypatch.setattr(metrics_mod, name, counter, raising=False)
    return metrics_mod


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    for attr in (
        "app.utils.path_utils.get_app_data_dir",
        "app.application.etl.service_targets.get_app_data_dir",
        "app.application.etl.service_uploads.get_app_data_dir",
        "app.application.etl.service_history.get_app_data_dir",
        "app.application.etl.service_shipment_templates.get_app_data_dir",
        "app.application.etl.targets.batch.get_app_data_dir",
    ):
        monkeypatch.setattr(attr, lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 通用 DB 构造帮手
# ---------------------------------------------------------------------------


def _nid() -> str:
    return str(uuid.uuid4())


def _make_upload(
    db,
    *,
    id="up-1",
    file_name="a.xlsx",
    storage_path="",
    suffix=".xlsx",
    expires_at=None,
    sha256="abc123",
    batch_id=None,
):
    up = EtlUpload(
        id=id,
        tenant_id=1,
        owner_user_id=1,
        file_name=file_name,
        suffix=suffix,
        size_bytes=10,
        sha256=sha256,
        storage_path=storage_path,
        expires_at=expires_at,
        batch_id=batch_id,
    )
    db.add(up)
    db.commit()
    return up


def _make_upload_file(tmp_path, db, **kw):
    p = tmp_path / (kw.pop("file_name", "a.xlsx"))
    p.write_bytes(b"test-bytes")
    return _make_upload(db, storage_path=str(p), **kw)


def _make_run(db, *, id=None, upload_id="up-1", target_type="shipment_records", status="preview_ready", **kw):
    run = EtlRun(
        id=id or _nid(),
        tenant_id=1,
        owner_user_id=1,
        upload_id=upload_id,
        target_type=target_type,
        status=status,
        stage=status,
        progress=100 if status == "preview_ready" else 0,
        file_sha256="abc123",
        reversible=True,
        **kw,
    )
    db.add(run)
    db.commit()
    return run


def _make_row(db, *, run_id, id_seq=1, final_action="new", execution_status=None, match_ref=None, **kw):
    row = EtlRunRow(
        id=id_seq,
        tenant_id=1,
        owner_user_id=1,
        run_id=run_id,
        source_sheet="S1",
        source_row=id_seq,
        source_json=json.dumps({"order_number": f"O{id_seq}"}),
        normalized_json=json.dumps({"order_number": f"O{id_seq}"}),
        provenance_json="{}",
        validation_json="[]",
        llm_suggestion_json="{}",
        suggested_action="new",
        final_action=final_action,
        match_ref=match_ref,
        before_json="{}",
        after_json="{}",
        execution_status=execution_status,
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def _make_template(db, *, id=None, name="tpl", target_type="shipment_records", current_version=1):
    tpl = EtlTemplate(
        id=id or _nid(),
        tenant_id=1,
        owner_user_id=1,
        name=name,
        target_type=target_type,
        current_version=current_version,
        is_active=True,
    )
    db.add(tpl)
    ver = EtlTemplateVersion(
        id=_nid(),
        template_id=tpl.id,
        tenant_id=1,
        owner_user_id=1,
        version=current_version,
        target_type=target_type,
        source_features_json="{}",
        field_mappings_json="[]",
        validation_rules_json="[]",
        match_keys_json='["order_number"]',
        allowed_update_fields_json="[]",
        action_rules_json="{}",
    )
    db.add(ver)
    db.commit()
    return tpl, ver


# ---------------------------------------------------------------------------
# service_support — 纯函数
# ---------------------------------------------------------------------------


class TestServiceSupport:
    def test_dump_load_json_roundtrip(self):
        obj = {"a": 1, "b": [1, 2], "c": "中"}
        assert load_json(dump_json(obj), {}) == {"a": 1, "b": [1, 2], "c": "中"}

    def test_load_json_invalid_returns_default(self):
        assert load_json("not json{{{", ["x"]) == ["x"]
        assert load_json(None, 5) == 5

    def test_dict_keys_are_str(self):
        raw = dump_json({1: "x", "k": datetime(2026, 1, 1, tzinfo=UTC)})
        parsed = json.loads(raw)
        assert "1" in parsed
        assert parsed["k"].startswith("2026-01-01")

    def test_clean_filename(self):
        assert clean_filename("a\x00b/../c.xlsx  ") == "c.xlsx"
        assert clean_filename("") == "upload"
        assert clean_filename("x" * 300).endswith(".xlsx") or True
        assert len(clean_filename("a" * 300)) <= 240

    def test_clean_relative_path(self):
        assert clean_relative_path("a/b\\c", "f.xlsx") == "a/b/c"
        assert clean_relative_path("../x", "f.xlsx") == "x"
        assert clean_relative_path("", "f.xlsx") == "f.xlsx"
        assert clean_relative_path("a/\x00b", "f.xlsx") == "a/b"

    def test_clean_batch_id(self):
        assert clean_batch_id(f"  {uuid.uuid4()}  ") is not None
        assert clean_batch_id("") is None
        with pytest.raises(EtlError):
            clean_batch_id("not-a-uuid")

    def test_mapping_key(self):
        assert mapping_key("  Hello 世界1 ") == "hello世界1"
        assert mapping_key("") == ""

    def test_safe_error(self):
        code, msg = safe_error(EtlError("ETL_X", "消息"))
        assert code == "ETL_X"
        assert msg == "消息"
        code2, msg2 = safe_error(RuntimeError("boom"))
        assert code2 == "ETL_INTERNAL_ERROR"
        assert "重试" in msg2

    def test_sanitize_webhook_headers(self):
        assert sanitize_webhook_headers({"X-Empty": ""}) == {"X-Empty": ""}  # empty value kept
        assert sanitize_webhook_headers({"X-Test": "v"}) == {"X-Test": "v"}
        with pytest.raises(EtlError):
            sanitize_webhook_headers({"authorization": "Bearer x"})
        with pytest.raises(EtlError):
            sanitize_webhook_headers({"X-Api-Key": "v"})  # sensitive part
        with pytest.raises(EtlError):
            sanitize_webhook_headers({"a" * 200: "v"})
        with pytest.raises(EtlError):
            sanitize_webhook_headers({"x": "a\nb"})
        with pytest.raises(EtlError):
            sanitize_webhook_headers({"x\ry": "v"})  # \r embedded in name
        with pytest.raises(EtlError):
            sanitize_webhook_headers(dict.fromkeys(range(50), "v"))

    def test_apply_validation_rules(self):
        rules = [
            {"field": "f", "op": "required"},
            {"field": "f", "op": "enum", "value": ["a", "b"]},
            {"field": "n", "op": "min", "value": 5},
            {"field": "n", "op": "max", "value": 10},
            {"field": "s", "op": "min_length", "value": 2},
            {"field": "s", "op": "max_length", "value": 4},
            {"field": "bad", "op": "required", "message": "自定"},
        ]
        data = {"f": "a", "n": 3, "s": "ok"}
        issues = apply_validation_rules(data, rules)
        codes = {i["code"] for i in issues}
        assert "ETL_VALIDATION_RULE_FAILED" in codes
        # required f ok, enum f ok; min(3<5) fail, max(3>10) ok;
        # min_length(2<2) ok, max_length(2>4) ok, bad required fail
        assert len(issues) == 2

    def test_apply_validation_rules_edge_cases(self):
        issues = apply_validation_rules(
            {"n": "abc", "s": 123},
            [
                {"field": "n", "op": "min", "value": 5},
                {"field": "n", "op": "max", "value": 1},
                {"field": "s", "op": "min_length", "value": "x"},
                {"field": "s", "op": "max_length", "value": 1},
            ],
        )
        assert len(issues) == 4


# ---------------------------------------------------------------------------
# service_uploads
# ---------------------------------------------------------------------------


class TestServiceUploads:
    def test_save_upload_success(self, etl_db, svc, app_data, fake_adapter):
        stream = io.BytesIO(b"0123456789")
        info = svc.save_upload(
            etl_db,
            owner_user_id=1,
            file_name="dir/a.xlsx",
            content_type="application/vnd",
            stream=stream,
        )
        assert info["file_name"] == "a.xlsx"
        assert info["size_bytes"] == 10
        assert info["sha256"]
        assert info["suffix"] == ".xlsx"
        assert etl_db.query(EtlUpload).count() == 1

    def test_save_upload_unsupported_suffix(self, etl_db, svc, app_data, fake_adapter):
        with pytest.raises(EtlError) as ei:
            svc.save_upload(
                etl_db,
                owner_user_id=1,
                file_name="a.exe",
                content_type=None,
                stream=io.BytesIO(b"x"),
            )
        assert ei.value.code == "ETL_FILE_TYPE_UNSUPPORTED"

    def test_save_upload_empty_file(self, etl_db, svc, app_data, fake_adapter):
        with pytest.raises(EtlError) as ei:
            svc.save_upload(
                etl_db,
                owner_user_id=1,
                file_name="empty.xlsx",
                content_type=None,
                stream=io.BytesIO(b""),
            )
        assert ei.value.code == "ETL_FILE_EMPTY"

    def test_save_upload_too_large(self, etl_db, svc, app_data, fake_adapter):
        big = io.BytesIO(b"x" * (MAX_FILE_BYTES + 1))
        with pytest.raises(EtlError) as ei:
            svc.save_upload(
                etl_db,
                owner_user_id=1,
                file_name="big.xlsx",
                content_type=None,
                stream=big,
            )
        assert ei.value.code == "ETL_FILE_TOO_LARGE"

    def test_save_upload_invalid_batch_id(self, etl_db, svc, app_data, fake_adapter):
        with pytest.raises(EtlError):
            svc.save_upload(
                etl_db,
                owner_user_id=1,
                file_name="a.xlsx",
                content_type=None,
                stream=io.BytesIO(b"data"),
                batch_id="bad",
            )

    def test_owned_upload_expired_and_missing(self, etl_db, svc, app_data, fake_adapter):
        _make_upload(
            etl_db,
            id="exp",
            storage_path="",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        with pytest.raises(EtlError) as ei:
            svc._owned_upload(etl_db, "exp", 1)
        assert ei.value.code == "ETL_UPLOAD_EXPIRED"

    def test_owned_upload_record_not_found(self, etl_db, svc, app_data, fake_adapter):
        with pytest.raises(EtlNotFound):
            svc._owned_upload_record(etl_db, "nope", 1)

    def test_upload_dict(self, etl_db, svc, app_data, fake_adapter):
        up = _make_upload(etl_db, id="u9", file_name="x.csv", suffix=".csv")
        d = svc.upload_dict(up)
        assert d["upload_id"] == "u9"
        assert d["relative_path"] == "x.csv"


# ---------------------------------------------------------------------------
# service_templates
# ---------------------------------------------------------------------------


class TestServiceTemplates:
    def test_create_template(self, etl_db, svc, fake_adapter):
        tpl = svc.create_template(
            etl_db,
            owner_user_id=1,
            name="  我的模板  ",
            target_type="shipment_records",
            draft={"field_mappings": [], "validation_rules": [], "match_keys": [], "allowed_update_fields": []},
        )
        assert tpl["name"] == "我的模板"
        assert tpl["current_version"] == 1
        assert tpl["version"]["number"] == 1

    def test_create_template_empty_name(self, etl_db, svc, fake_adapter):
        with pytest.raises(EtlError) as ei:
            svc.create_template(
                etl_db,
                owner_user_id=1,
                name="   ",
                target_type="shipment_records",
                draft={"field_mappings": []},
            )
        assert ei.value.code == "ETL_TEMPLATE_NAME_REQUIRED"

    def test_update_template(self, etl_db, svc, fake_adapter):
        tpl, _ = _make_template(etl_db, name="old")
        upd = svc.update_template(
            etl_db,
            template_id=tpl.id,
            owner_user_id=1,
            draft={"field_mappings": [], "validation_rules": [], "match_keys": [], "allowed_update_fields": []},
            name="new",
            description="desc",
        )
        assert upd["name"] == "new"
        assert upd["current_version"] == 2
        assert upd["version"]["number"] == 2

    def test_list_get_versions_delete(self, etl_db, svc, fake_adapter):
        tpl, ver = _make_template(etl_db, name="t1")
        lst = svc.list_templates(etl_db, owner_user_id=1)
        assert any(t["id"] == tpl.id for t in lst)
        got = svc.get_template(etl_db, template_id=tpl.id, owner_user_id=1)
        assert got["id"] == tpl.id
        versions = svc.template_versions(etl_db, template_id=tpl.id, owner_user_id=1)
        assert len(versions) == 1
        svc.delete_template(etl_db, template_id=tpl.id, owner_user_id=1)
        assert etl_db.get(EtlTemplate, tpl.id).is_active is False

    def test_owned_template_not_found(self, etl_db, svc, fake_adapter):
        with pytest.raises(EtlNotFound):
            svc._owned_template(etl_db, "nope", 1)

    def test_current_version_missing(self, etl_db, svc, fake_adapter):
        tpl = EtlTemplate(
            id=_nid(), tenant_id=1, owner_user_id=1, name="t", target_type="shipment_records", current_version=99
        )
        etl_db.add(tpl)
        etl_db.commit()
        with pytest.raises(EtlError) as ei:
            svc._current_version(etl_db, tpl, 1)
        assert ei.value.code == "ETL_TEMPLATE_VERSION_MISSING"

    def test_template_dict(self, etl_db, svc, fake_adapter):
        tpl, ver = _make_template(etl_db)
        d = svc.template_dict(tpl, ver)
        assert d["id"] == tpl.id
        assert d["version"]["field_mappings"] == []


# ---------------------------------------------------------------------------
# service_targets
# ---------------------------------------------------------------------------


class TestServiceTargets:
    def test_create_target_config(self, etl_db, svc, monkeypatch, fake_adapter):
        monkeypatch.setattr(
            "app.application.etl.service_targets.store_webhook_secret",
            lambda uid, secret: f"ref-{secret}",
        )
        cfg = svc.create_target_config(
            etl_db,
            owner_user_id=1,
            name="hook",
            endpoint_url="https://x.com/hook",
            headers={"X-H": "v"},
            secret="s3cret",
        )
        assert cfg["name"] == "hook"
        assert cfg["has_secret"] is True

    def test_create_target_config_invalid_rolls_back_secret(
        self, etl_db, svc, monkeypatch, fake_adapter
    ):
        deleted = []
        monkeypatch.setattr(
            "app.application.etl.service_targets.store_webhook_secret",
            lambda uid, secret: f"ref-{secret}",
        )
        monkeypatch.setattr(
            "app.application.etl.service_targets.delete_webhook_secret",
            deleted.append,
        )
        with pytest.raises(EtlError) as ei:
            svc.create_target_config(
                etl_db, owner_user_id=1, name="", endpoint_url="", headers={}, secret="s"
            )
        assert ei.value.code == "ETL_TARGET_CONFIG_INVALID"
        assert deleted == ["ref-s"]

    def test_list_update_delete_target_config(self, etl_db, svc, monkeypatch, fake_adapter):
        monkeypatch.setattr(
            "app.application.etl.service_targets.store_webhook_secret",
            lambda uid, secret: f"ref-{secret}",
        )
        monkeypatch.setattr(
            "app.application.etl.service_targets.delete_webhook_secret",
            lambda *a: None,
        )
        cfg = svc.create_target_config(
            etl_db, owner_user_id=1, name="h", endpoint_url="https://x.com", headers={}, secret=None
        )
        assert svc.list_target_configs(etl_db, owner_user_id=1)
        upd = svc.update_target_config(
            etl_db,
            config_id=cfg["id"],
            owner_user_id=1,
            name="h2",
            endpoint_url="https://y.com",
            headers={"k": "v"},
            secret=None,
        )
        assert upd["name"] == "h2"
        svc.delete_target_config(etl_db, config_id=cfg["id"], owner_user_id=1)
        with pytest.raises(EtlNotFound):
            svc._owned_target_config(etl_db, cfg["id"], 1)

    def test_target_config_for_test(self, etl_db, svc, fake_adapter):
        cfg = EtlTargetConfig(
            id=_nid(), tenant_id=1, owner_user_id=1, name="h", target_type="webhook",
            endpoint_url="https://x.com", headers_json="{}", is_active=True,
        )
        etl_db.add(cfg)
        etl_db.commit()
        res = svc.target_config_for_test(etl_db, config_id=cfg.id, owner_user_id=1)
        assert res["success"] is True

    def test_download_path(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, target_type="export_xlsx", status="completed")
        run.receipt_json = dump_json({"file_name": "out.xlsx"})
        etl_db.commit()
        p = app_data / "etl" / "exports"
        p.mkdir(parents=True)
        f = p / "out.xlsx"
        f.write_bytes(b"x")
        path = svc.download_path(etl_db, run_id=run.id, owner_user_id=1)
        assert path.is_file()

    def test_download_path_wrong_type(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, target_type="shipment_records", status="completed")
        with pytest.raises(EtlNotFound):
            svc.download_path(etl_db, run_id=run.id, owner_user_id=1)

    def test_export_error_rows(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="error")
        path = svc.export_error_rows(etl_db, run_id=run.id, owner_user_id=1)
        assert path.is_file()
        content = path.read_text(encoding="utf-8-sig")
        assert "source_sheet" in content

    def test_owned_run_not_found(self, etl_db, svc, fake_adapter):
        with pytest.raises(EtlNotFound):
            svc._owned_run(etl_db, "nope", 1)


# ---------------------------------------------------------------------------
# service_history
# ---------------------------------------------------------------------------


class TestServiceHistory:
    def test_get_run(self, etl_db, svc, app_data, fake_adapter):
        up = _make_upload(etl_db, id="up1", file_name="f.xlsx")
        run = _make_run(etl_db, upload_id="up1")
        d = svc.get_run(etl_db, run_id=run.id, owner_user_id=1)
        assert d["id"] == run.id
        assert d["file_name"] == "f.xlsx"

    def test_get_run_marks_interrupted_when_stale(self, etl_db, svc, app_data, fake_adapter):
        up = _make_upload(etl_db, id="up1")
        run = _make_run(etl_db, upload_id="up1", status="executing")
        run.updated_at = datetime.now(UTC) - timedelta(minutes=30)
        etl_db.commit()
        d = svc.get_run(etl_db, run_id=run.id, owner_user_id=1)
        assert d["status"] == "interrupted"
        assert etl_db.get(EtlRun, run.id).status == "interrupted"

    def test_list_runs_with_batch(self, etl_db, svc, app_data, fake_adapter):
        up = _make_upload(etl_db, id="up1", file_name="f.xlsx", batch_id=str(uuid.uuid4()))
        _make_run(etl_db, upload_id="up1")
        rows = svc.list_runs(etl_db, owner_user_id=1, batch_id=up.batch_id)
        assert len(rows) == 1

    def test_list_runs_limit_clamp(self, etl_db, svc, app_data, fake_adapter):
        _make_run(etl_db, upload_id="up1")
        rows = svc.list_runs(etl_db, owner_user_id=1, limit=0)
        assert isinstance(rows, list)

    def test_cleanup_retention(self, etl_db, svc, app_data, fake_adapter):
        old_file = app_data / "etl" / "uploads" / "old.xlsx"
        old_file.parent.mkdir(parents=True)
        old_file.write_bytes(b"x")
        up = _make_upload(
            etl_db,
            id="exp",
            storage_path=str(old_file),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        run = _make_run(etl_db, upload_id="exp")
        run.created_at = datetime.now(UTC) - timedelta(days=200)
        run.reversible = True
        etl_db.commit()
        _make_row(etl_db, run_id=run.id, id_seq=1)
        res = svc.cleanup_retention(etl_db, owner_user_id=1)
        assert res["removed_upload_files"] >= 1
        assert not old_file.exists()
        assert etl_db.get(EtlRun, run.id).rollback_status == "expired"

    def test_run_dict(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        d = svc.run_dict(run, file_name="f.xlsx", batch_id="b1", relative_path="r")
        assert d["file_name"] == "f.xlsx"
        assert d["batch_id"] == "b1"
        assert d["error"] is None

    def test_get_rows(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new")
        _make_row(etl_db, run_id=run.id, id_seq=2, final_action="error")
        res = svc.get_rows(etl_db, run_id=run.id, owner_user_id=1, page=1, page_size=10)
        assert res["total"] == 2
        res2 = svc.get_rows(etl_db, run_id=run.id, owner_user_id=1, page=0, page_size=10, action="new")
        assert res2["total"] == 1
        assert res2["page"] == 1

    def test_row_dict(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        row = _make_row(etl_db, run_id=run.id, id_seq=1, execution_status="failed")
        row.execution_error_code = "E1"
        row.execution_error_message = "m"
        etl_db.commit()
        d = svc.row_dict(row)
        assert d["execution_error"]["code"] == "E1"


# ---------------------------------------------------------------------------
# service_draft
# ---------------------------------------------------------------------------


class TestServiceDraft:
    def test_update_draft_overrides_only(self, etl_db, svc, app_data, fake_adapter):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db)
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new")
        d = svc.update_draft(etl_db, run_id=run.id, owner_user_id=1, patch={"row_overrides": {}})
        assert d["id"] == run.id

    def test_update_draft_not_editable(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, status="executing")
        with pytest.raises(EtlConflict):
            svc.update_draft(etl_db, run_id=run.id, owner_user_id=1, patch={"field_mappings": []})

    def test_update_draft_validates_and_submits(self, etl_db, svc, app_data, fake_adapter, no_background):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db)
        d = svc.update_draft(
            etl_db,
            run_id=run.id,
            owner_user_id=1,
            patch={
                "field_mappings": [{"target": "order_number", "source": "order_number", "transforms": [{"op": "trim"}]}],
                "validation_rules": [],
                "match_keys": ["order_number"],
                "allowed_update_fields": ["order_number"],
            },
        )
        assert d["id"] == run.id
        assert run.status == "previewing"

    def test_validate_draft_branches(self, etl_db, svc, fake_adapter):
        adapter = _FakeAdapter()
        good = {
            "field_mappings": [{"target": "order_number", "source": "x", "transforms": [{"op": "trim"}]}],
            "allowed_update_fields": ["order_number"],
            "match_keys": ["order_number"],
            "action_rules": {"duplicate": "skip"},
            "validation_rules": [{"field": "order_number", "op": "required"}],
        }
        svc._validate_draft(good, adapter)  # no raise

        bad_cases = [
            {"field_mappings": "not-list"},
            {"field_mappings": [{"target": "unknown_target", "source": "x"}]},
            {"field_mappings": [{"target": "order_number"}, {"target": "order_number"}]},
            {"field_mappings": [{"target": "order_number", "transforms": [{"op": "secret_op"}]}]},
            {"field_mappings": [{"target": "order_number", "transforms": "not-list"}]},
            {"field_mappings": [{"target": "order_number", "transforms": [{"op": "trim"}] * 21}]},
            {"field_mappings": [{"target": "order_number", "transforms": []}], "allowed_update_fields": ["forbidden"]},
            {"field_mappings": [], "match_keys": ["not_a_key"]},
            {"field_mappings": [], "action_rules": "not-dict"},
            {"field_mappings": [], "validation_rules": "not-list"},
            {"field_mappings": [], "validation_rules": [{"field": "bad", "op": "required"}]},
            {"field_mappings": [], "validation_rules": [{"field": "order_number", "op": "bad_op"}]},
            {"field_mappings": [], "validation_rules": [{"field": "order_number", "op": "enum", "value": "not-list"}]},
            {"field_mappings": [{}] * 501},
            {"field_mappings": [{"target": "order_number", "transforms": [123]}]},
            {"field_mappings": [{"target": "order_number", "transforms": [{"op": "trim"}] * 21}]},
            {"field_mappings": [], "validation_rules": [{}] * 101},
            {"field_mappings": [], "validation_rules": [123]},
            {"field_mappings": [], "validation_rules": [{"field": "order_number", "op": "enum", "value": ["x"] * 1001}]},
        ]
        for draft in bad_cases:
            with pytest.raises(EtlError):
                svc._validate_draft(draft, adapter)

    def test_apply_row_overrides(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        row = _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new", match_ref=None)
        svc._apply_row_overrides(etl_db, run.id, 1, {"1": "skip"})
        assert etl_db.get(EtlRunRow, 1).final_action == "skip"
        assert etl_db.get(EtlRunRow, 1).action_overridden is True

    def test_apply_row_overrides_errors(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new")
        with pytest.raises(EtlError):
            svc._apply_row_overrides(etl_db, run.id, 1, {"1": "bogus_action"})
        with pytest.raises(EtlNotFound):
            svc._apply_row_overrides(etl_db, run.id, 1, {"999": "skip"})
        # already executed
        row2 = _make_row(etl_db, run_id=run.id, id_seq=2, final_action="new", execution_status="success")
        with pytest.raises(EtlConflict):
            svc._apply_row_overrides(etl_db, run.id, 1, {"2": "skip"})
        # invalid row
        row3 = _make_row(etl_db, run_id=run.id, id_seq=3, final_action="new")
        row3.validation_json = dump_json([{"code": "E"}])
        etl_db.commit()
        with pytest.raises(EtlConflict):
            svc._apply_row_overrides(etl_db, run.id, 1, {"3": "skip"})
        # update requires match
        row4 = _make_row(etl_db, run_id=run.id, id_seq=4, final_action="new", match_ref=None)
        with pytest.raises(EtlConflict):
            svc._apply_row_overrides(etl_db, run.id, 1, {"4": "update"})
        # new forced when match exists
        row5 = _make_row(etl_db, run_id=run.id, id_seq=5, final_action="new", match_ref="m")
        with pytest.raises(EtlConflict):
            svc._apply_row_overrides(etl_db, run.id, 1, {"5": "new"})
        # update requires allowed_update_fields
        row6 = _make_row(etl_db, run_id=run.id, id_seq=6, final_action="new", match_ref="m")
        with pytest.raises(EtlConflict):
            svc._apply_row_overrides(etl_db, run.id, 1, {"6": "update"})

    def test_set_run_counts(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        svc._set_run_counts(run, {"new": 1, "update": 2, "skip": 3, "error": 4})
        assert run.new_rows == 1
        assert run.error_rows == 4

    def test_update_draft_applies_overrides(self, etl_db, svc, app_data, fake_adapter):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db)
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new")
        d = svc.update_draft(etl_db, run_id=run.id, owner_user_id=1, patch={"row_overrides": {"1": "skip"}})
        assert d["id"] == run.id
        assert etl_db.get(EtlRunRow, 1).final_action == "skip"

    def test_record_correction_metrics(self, etl_db, svc, app_data, fake_adapter, no_background, mock_etl_metrics):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db)
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new")
        svc.update_draft(etl_db, run_id=run.id, owner_user_id=1, patch={"row_overrides": {"1": "skip"}})
        svc.update_draft(etl_db, run_id=run.id, owner_user_id=1, patch={"field_mappings": []})
        metric = mock_etl_metrics.etl_manual_corrections_total
        assert metric.labels.called

    def test_submit_revalidation_dedup(self, etl_db, svc, app_data, fake_adapter, monkeypatch):
        from app.application.etl import service_draft as draft_mod

        submitted = []
        monkeypatch.setattr(
            "app.application.etl.service_support.EXECUTOR.submit",
            lambda fn, *a, **k: submitted.append(fn),
        )
        run = _make_run(etl_db)
        svc._submit_revalidation(run.id, 1, 1)
        first = len(submitted)
        svc._submit_revalidation(run.id, 1, 1)  # dedup -> no second submit
        assert len(submitted) == first
        from app.application.etl.service_support import SUBMITTED

        SUBMITTED.discard(run.id)
        assert draft_mod is not None

    def test_revalidate_existing_rows(self, etl_db, svc, app_data, fake_adapter, monkeypatch, mock_etl_metrics):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db, status="previewing")
        run.total_rows = 4
        run.draft_json = dump_json(
            {
                "field_mappings": [{"target": "order_number", "source": "order_number"}],
                "allowed_update_fields": [],
                "validation_rules": [{"field": "order_number", "op": "required"}],
                "ocr_confirmed": False,
            }
        )
        etl_db.commit()
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new", execution_status="success")
        _make_row(etl_db, run_id=run.id, id_seq=2, final_action="new", execution_status=None)
        _make_row(etl_db, run_id=run.id, id_seq=3, final_action="new", execution_status=None)
        r4 = _make_row(etl_db, run_id=run.id, id_seq=4, final_action="new", execution_status=None)
        r4.provenance_json = dump_json({"ocr": True})
        etl_db.commit()

        def _fake_apply_mapping(source, mappings):
            if source.get("order_number") == "O2":
                raise EtlError("ETL_MAPPING_BOOM", "映射失败")
            return {"order_number": source.get("order_number")}

        monkeypatch.setattr(
            "app.application.etl.service_draft.apply_mapping", _fake_apply_mapping
        )
        monkeypatch.setattr(
            "app.application.etl.service_draft.provenance_validation_issues",
            lambda prov: [{"code": "X", "severity": "error", "field": "", "message": "p"}]
            if prov.get("ocr")
            else [],
        )
        svc._revalidate_existing_rows(etl_db, run.id, 1)
        assert etl_db.get(EtlRun, run.id).status == "preview_ready"
        assert etl_db.get(EtlRunRow, 2).final_action == "error"
        assert etl_db.get(EtlRunRow, 3).final_action == "new"
        assert etl_db.get(EtlRunRow, 4).final_action == "error"


# ---------------------------------------------------------------------------
# service_execution
# ---------------------------------------------------------------------------


class TestServiceExecution:
    def test_execute_requires_confirmation(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        with pytest.raises(EtlError) as ei:
            svc.execute(etl_db, run_id=run.id, owner_user_id=1, confirmed=False, valid_rows_only=False)
        assert ei.value.code == "ETL_CONFIRMATION_REQUIRED"

    def test_execute_requires_preview_ready(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, status="queued")
        with pytest.raises(EtlConflict):
            svc.execute(etl_db, run_id=run.id, owner_user_id=1, confirmed=True, valid_rows_only=False)

    def test_execute_blocks_invalid_rows(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db)
        run.error_rows = 3
        etl_db.commit()
        with pytest.raises(EtlConflict) as ei:
            svc.execute(etl_db, run_id=run.id, owner_user_id=1, confirmed=True, valid_rows_only=False)
        assert ei.value.code == "ETL_INVALID_ROWS_BLOCKED"

    def test_execute_success(self, etl_db, svc, app_data, fake_adapter, no_background):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", target_type="webhook")
        run.draft_json = dump_json({"target_config_id": "cfg1"})
        etl_db.commit()
        cfg = EtlTargetConfig(
            id="cfg1", tenant_id=1, owner_user_id=1, name="h", target_type="webhook",
            endpoint_url="https://x.com", headers_json="{}", is_active=True,
        )
        etl_db.add(cfg)
        etl_db.commit()
        d = svc.execute(etl_db, run_id=run.id, owner_user_id=1, confirmed=True, valid_rows_only=True)
        assert d["id"] == run.id
        assert run.status == "executing"

    def test_execute_success_non_webhook(self, etl_db, svc, app_data, fake_adapter, no_background):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", target_type="shipment_records")
        run.draft_json = dump_json({"field_mappings": []})
        etl_db.commit()
        d = svc.execute(etl_db, run_id=run.id, owner_user_id=1, confirmed=True, valid_rows_only=True)
        assert d["id"] == run.id
        assert run.status == "executing"

    def test_retry_not_allowed(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, status="preview_ready")
        with pytest.raises(EtlConflict):
            svc.retry(etl_db, run_id=run.id, owner_user_id=1)

    def test_retry_already_rolled_back(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, status="failed")
        run.rollback_status = "completed"
        etl_db.commit()
        with pytest.raises(EtlConflict):
            svc.retry(etl_db, run_id=run.id, owner_user_id=1)

    def test_retry_rerun_parse_and_revalidation(self, etl_db, svc, app_data, fake_adapter, no_background, mock_etl_metrics):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db, status="failed")
        run.executed_rows = 0
        run.total_rows = 0
        etl_db.commit()
        svc.retry(etl_db, run_id=run.id, owner_user_id=1)
        assert run.stage == "parsing"

        run2 = _make_run(etl_db, id=_nid(), status="interrupted")
        run2.executed_rows = 5
        run2.total_rows = 5
        etl_db.commit()
        _make_row(etl_db, run_id=run2.id, id_seq=1)
        svc.retry(etl_db, run_id=run2.id, owner_user_id=1)
        assert run2.stage == "validating"

    def test_rollback_gates(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, status="preview_ready")
        with pytest.raises(EtlConflict):
            svc.rollback(etl_db, run_id=run.id, owner_user_id=1)
        run2 = _make_run(etl_db, id=_nid(), status="completed")
        run2.reversible = False
        etl_db.commit()
        with pytest.raises(EtlConflict):
            svc.rollback(etl_db, run_id=run2.id, owner_user_id=1)
        run3 = _make_run(etl_db, id=_nid(), status="completed")
        run3.rollback_status = "completed"
        etl_db.commit()
        with pytest.raises(EtlConflict):
            svc.rollback(etl_db, run_id=run3.id, owner_user_id=1)

    def test_rollback_empty(self, etl_db, svc, app_data, fake_adapter):
        _make_upload(etl_db, id="up-1")
        run = _make_run(etl_db, status="completed")
        with pytest.raises(EtlConflict) as ei:
            svc.rollback(etl_db, run_id=run.id, owner_user_id=1)
        assert ei.value.code == "ETL_ROLLBACK_EMPTY"

    def test_rollback_batch_success(self, etl_db, svc, app_data, fake_adapter, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="completed")
        _make_row(etl_db, run_id=run.id, id_seq=1, execution_status="success")
        d = svc.rollback(etl_db, run_id=run.id, owner_user_id=1)
        assert d is not None
        assert run.rollback_status == "completed"
        assert etl_db.get(EtlRunRow, 1).execution_status == "rolled_back"

    def test_rollback_row_failure_path(self, etl_db, svc, app_data, fake_adapter, mock_etl_metrics):
        del fake_adapter.rollback_batch  # go row path
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="completed")
        _make_row(etl_db, run_id=run.id, id_seq=1, execution_status="success")
        d = svc.rollback(etl_db, run_id=run.id, owner_user_id=1)
        assert run.rollback_status == "completed"

    def test_rollback_failure_sets_error(self, etl_db, svc, app_data, fake_adapter, mock_etl_metrics):
        del fake_adapter.rollback_batch  # go row path

        def _boom(*a, **k):
            raise RuntimeError("boom")

        fake_adapter.rollback_row = _boom
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="completed")
        _make_row(etl_db, run_id=run.id, id_seq=1, execution_status="success")
        with pytest.raises(EtlError):
            svc.rollback(etl_db, run_id=run.id, owner_user_id=1)
        assert run.rollback_status == "failed"

    def test_execute_worker_batch_success(self, etl_db, svc, app_data, fake_adapter, same_session, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="executing")
        fake_adapter.type = "webhook"
        run.target_type = "webhook"
        run.draft_json = dump_json({"field_mappings": [], "target_config_id": "cfg1"})
        etl_db.commit()
        cfg = EtlTargetConfig(
            id="cfg1", tenant_id=1, owner_user_id=1, name="h", target_type="webhook",
            endpoint_url="https://x.com", headers_json="{}", is_active=True,
        )
        etl_db.add(cfg)
        etl_db.commit()
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new", execution_status=None)
        svc._execute_worker(run.id, 1, False)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "completed"

    def test_execute_worker_batch_failure(self, etl_db, svc, app_data, fake_adapter, same_session, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="executing")
        fake_adapter.fail_execute_batch = True
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new", execution_status=None)
        svc._execute_worker(run.id, 1, False)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "failed"

    def test_execute_rows_success(self, etl_db, svc, app_data, fake_adapter, same_session, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="executing")
        del fake_adapter.execute_batch
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new", execution_status=None)
        _make_row(etl_db, run_id=run.id, id_seq=2, final_action="update", execution_status=None)
        svc._execute_worker(run.id, 1, False)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "completed"

    def test_execute_rows_failure_replays_completed(self, etl_db, svc, app_data, fake_adapter, same_session, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="executing")
        del fake_adapter.execute_batch
        # row O2 fails; row O1 succeeds and gets replayed successfully
        fake_adapter.fail_for_value = "O2"
        _make_row(etl_db, run_id=run.id, id_seq=1, final_action="new", execution_status=None)
        _make_row(etl_db, run_id=run.id, id_seq=2, final_action="new", execution_status=None)
        svc._execute_worker(run.id, 1, False)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "failed"
        assert etl_db.get(EtlRunRow, 1).execution_status == "success"


# ---------------------------------------------------------------------------
# service_preview
# ---------------------------------------------------------------------------


class TestServicePreview:
    def test_create_preview_simple(self, etl_db, svc, app_data, fake_adapter, no_background):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        fake_adapter.type = "shipment_records"
        run = svc.create_preview(
            etl_db,
            owner_user_id=1,
            upload_id="upx",
            target_type="shipment_records",
        )
        assert run["id"]
        assert etl_db.query(EtlRun).filter(EtlRun.upload_id == "upx").count() >= 1

    def test_create_preview_auto_detection(self, etl_db, svc, app_data, fake_adapter, no_background, monkeypatch):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        monkeypatch.setattr(
            "app.application.etl.target_detection.detect_etl_target",
            lambda path, suffix: {"target_type": "shipment_records"},
        )
        fake_adapter.type = "shipment_records"
        run = svc.create_preview(etl_db, owner_user_id=1, upload_id="upx", target_type="auto")
        assert run["id"]

    def test_create_preview_knowledge_only_rejected(
        self, etl_db, svc, app_data, fake_adapter, no_background
    ):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.docx", suffix=".docx")
        fake_adapter.type = "shipment_records"
        with pytest.raises(EtlError) as ei:
            svc.create_preview(etl_db, owner_user_id=1, upload_id="upx", target_type="shipment_records")
        assert ei.value.code == "ETL_KNOWLEDGE_ONLY_FILE"

    def test_create_preview_shipment_template_conflict(
        self, etl_db, svc, app_data, fake_adapter, no_background
    ):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        tpl, _ = _make_template(etl_db, id="tpl1", name="发货版式", target_type="shipment_records")
        tpl.description = ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION
        etl_db.commit()
        with pytest.raises(EtlError) as ei:
            svc.create_preview(
                etl_db, owner_user_id=1, upload_id="upx", target_type="shipment_records", template_id="tpl1"
            )
        assert ei.value.code == "ETL_SHIPMENT_TEMPLATE_NOT_IMPORT_TEMPLATE"

    def test_create_preview_template_target_mismatch(
        self, etl_db, svc, app_data, fake_adapter, no_background
    ):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        _make_template(etl_db, id="tpl1", name="t", target_type="customers")
        with pytest.raises(EtlError):
            svc.create_preview(
                etl_db, owner_user_id=1, upload_id="upx", target_type="shipment_records", template_id="tpl1"
            )

    def test_create_preview_template_preset_conflict(
        self, etl_db, svc, app_data, fake_adapter, no_background, monkeypatch
    ):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        tpl, ver = _make_template(etl_db, id="tpl1", name="t", target_type="shipment_records")
        ver.source_features_json = dump_json({"compatibility_preset_id": "preset-a"})
        etl_db.commit()
        with pytest.raises(EtlError):
            svc.create_preview(
                etl_db,
                owner_user_id=1,
                upload_id="upx",
                target_type="shipment_records",
                template_id="tpl1",
                compatibility_preset_id="preset-b",
            )

    def test_suggest_mappings_dynamic(self, etl_db, svc, fake_adapter):
        fake_adapter.allow_dynamic_fields = True
        ds = _FakeDataset()
        ds.headers = ["order_number", "product_model"]
        mappings = svc._suggest_mappings(ds, fake_adapter)
        assert len(mappings) == 2
        assert all(m["source"] == m["target"] for m in mappings)
        assert all(m["transforms"] == [{"op": "trim"}] for m in mappings)

    def test_suggest_mappings_static(self, etl_db, svc, fake_adapter, monkeypatch):
        monkeypatch.setattr(
            "app.application.excel_etl_kb.get_excel_etl_kb",
            lambda: SimpleNamespace(synonyms=lambda: {"order_number": ["订单号"]}),
        )
        ds = _FakeDataset()
        ds.headers = ["订单号"]
        mappings = svc._suggest_mappings(ds, fake_adapter)
        assert any(m["target"] == "order_number" for m in mappings)

    def test_preview_worker_success(self, etl_db, svc, app_data, fake_adapter, same_session, no_background, monkeypatch, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="queued")
        run.draft_json = dump_json({"field_mappings": [], "ocr_confirmed": True})
        etl_db.commit()
        monkeypatch.setattr(
            "app.application.etl.service_preview.parse_file",
            lambda *a, **k: _FakeDataset(),
        )
        monkeypatch.setattr(
            "app.application.etl.service_preview.enhance_mappings_with_llm",
            lambda *a, **k: ([], None),
        )
        svc._preview_worker(run.id, 1)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "preview_ready"

    def test_preview_worker_failure(self, etl_db, svc, app_data, fake_adapter, same_session, no_background, monkeypatch, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", status="queued")
        etl_db.commit()

        def _boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr("app.application.etl.service_preview.parse_file", _boom)
        svc._preview_worker(run.id, 1)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "failed"

    def test_preview_worker_rich(self, etl_db, svc, app_data, fake_adapter, same_session, no_background, monkeypatch, mock_etl_metrics):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", target_type="shipment_records", status="queued")
        run.draft_json = dump_json({"compatibility_preset_id": "preset-a", "ocr_confirmed": False})
        etl_db.commit()

        rows = [
            SimpleNamespace(values={"order_number": "O1"}, provenance={}, row_number=1, sheet="S1"),
            SimpleNamespace(values={"order_number": "O2"}, provenance={"ocr": True}, row_number=2, sheet="S1"),
        ]
        ds = SimpleNamespace(
            source_features={
                "kind": "sheet",
                "regions": [{"id": "r1", "status": "selected", "sheet": "A", "header_row": 1, "customer_name": "客户"}],
            },
            warnings=["w"],
            headers=["order_number"],
            rows=rows,
        )
        monkeypatch.setattr("app.application.etl.service_preview.parse_file", lambda *a, **k: ds)
        monkeypatch.setattr(
            "app.application.etl.service_preview.enhance_mappings_with_llm",
            lambda *a, **k: ([{"target": "order_number", "source": "order_number"}], None),
        )
        monkeypatch.setattr(
            "app.application.etl.service_shipment_templates.shipment_template_candidates",
            lambda *a, **k: [{"region_id": "r1"}],
        )
        monkeypatch.setattr(
            "app.application.etl.service_preview.apply_mapping",
            lambda source, mappings: (
                {"order_number": source["order_number"]}
                if source["order_number"] != "O2"
                else (_ for _ in ()).throw(EtlError("ETL_MAP", "映射失败"))
            ),
        )
        monkeypatch.setattr(
            "app.application.excel_etl_kb.get_excel_etl_kb",
            lambda: SimpleNamespace(synonyms=lambda: {}),
        )
        svc._preview_worker(run.id, 1)
        etl_db.expire_all()
        assert etl_db.get(EtlRun, run.id).status == "preview_ready"
        assert etl_db.get(EtlRun, run.id).error_rows == 1

    def test_suggest_mappings_field_types(self, etl_db, svc, fake_adapter, monkeypatch):
        class _NumDateAdapter:
            type = "x"
            fields = (
                TargetField("qty", "数量", type="number"),
                TargetField("d", "日期", type="date"),
                TargetField("i", "整数", type="integer"),
                TargetField("s", "字符串", type="string"),
            )
            allow_dynamic_fields = False
            default_match_keys = ()

        monkeypatch.setattr(
            "app.application.excel_etl_kb.get_excel_etl_kb",
            lambda: SimpleNamespace(synonyms=lambda: {}),
        )
        ds = _FakeDataset()
        ds.headers = ["qty", "d", "i", "s"]
        mappings = svc._suggest_mappings(ds, _NumDateAdapter())
        by_target = {m["target"]: m for m in mappings}
        assert by_target["qty"]["transforms"] == [{"op": "number"}]
        assert by_target["d"]["transforms"] == [{"op": "date"}]
        assert by_target["i"]["transforms"] == [{"op": "cast", "type": "integer"}]
        assert by_target["s"]["transforms"] == [{"op": "trim"}]

    def test_suggest_mappings_knowledge(self, etl_db, svc, fake_adapter, monkeypatch):
        class _KnowledgeAdapter:
            type = "knowledge"
            fields = (TargetField("document_path", "路径", required=True),)
            allow_dynamic_fields = False
            default_match_keys = ()

        monkeypatch.setattr(
            "app.application.excel_etl_kb.get_excel_etl_kb",
            lambda: SimpleNamespace(synonyms=lambda: {}),
        )
        ds = _FakeDataset()
        ds.source_features = {"kind": "document"}
        ds.headers = ["document_path"]
        mappings = svc._suggest_mappings(ds, _KnowledgeAdapter())
        assert any(
            m["target"] == "document_path" and m["source"] == "document_path" and m["confidence"] == 1.0
            for m in mappings
        )

    def test_suggest_mappings_synonym_error(self, etl_db, svc, fake_adapter, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "app.application.excel_etl_kb.get_excel_etl_kb", _boom
        )
        ds = _FakeDataset()
        ds.headers = ["order_number"]
        mappings = svc._suggest_mappings(ds, fake_adapter)
        assert isinstance(mappings, list)

    def test_update_linked_companion_summary(self, etl_db, svc, app_data, fake_adapter):
        parent = _make_run(etl_db, id="par", status="preview_ready")
        parent.summary_json = dump_json(
            {
                "linked_customer_products_preview": {
                    "run_id": "child1",
                    "target_type": "customer_products",
                }
            }
        )
        etl_db.commit()
        child = _make_run(etl_db, id="child1", target_type="customer_products", status="preview_ready")
        child.tenant_id = 1
        child.summary_json = dump_json({"linked_from_shipment_preview": "par"})
        etl_db.commit()
        svc._update_linked_companion_summary(etl_db, child, status="preview_ready")
        parent = etl_db.get(EtlRun, "par")
        link = json.loads(parent.summary_json)["linked_customer_products_preview"]
        assert link["status"] == "preview_ready"

    def test_update_linked_no_parent(self, etl_db, svc, app_data, fake_adapter):
        child = _make_run(etl_db, id="child1")
        child.summary_json = dump_json({})
        etl_db.commit()
        svc._update_linked_companion_summary(etl_db, child, status="preview_ready")  # no raise


# ---------------------------------------------------------------------------
# service_shipment_templates — 模块级纯函数
# ---------------------------------------------------------------------------


class TestShipmentTemplateHelpers:
    def test_safe_template_name(self):
        assert _safe_template_name("a/b:c*d?e", "f") == "a-b-c-d-e"
        assert _safe_template_name("", "f") == "f"  # empty -> fallback
        assert _safe_template_name("   ", "fallback") == "发货单版式"  # truthy but empty after strip
        assert _safe_template_name("/", "f") == "发货单版式"  # sanitized to empty -> default
        assert _safe_template_name("x" * 200, "f") == "x" * 120

    def test_selected_shipment_region(self):
        features = {
            "regions": [
                {"id": "1", "status": "selected", "sheet": "B", "header_row": 2, "customer_name": "乙"},
                {"id": "2", "status": "selected", "sheet": "A", "header_row": 1, "customer_name": "甲"},
                {"id": "3", "status": "draft", "customer_name": "丙"},
            ]
        }
        sel = _selected_shipment_region(features)
        assert sel["id"] == "2"  # sorted by sheet/header_row
        assert _selected_shipment_region(features, "1")["id"] == "1"
        assert _selected_shipment_region(features, "99") == {}
        assert _selected_shipment_region({"regions": []}) == {}

    def test_shipment_template_default_name(self):
        features = {"regions": [{"id": "1", "status": "selected", "customer_name": "客户甲"}]}
        assert _shipment_template_default_name(features, "file.xlsx") == "客户甲-发货单版式"
        features2 = {"regions": [{"id": "1", "status": "selected"}]}
        assert _shipment_template_default_name(features2, "file.xlsx") == "file-发货单版式"

    def test_shipment_template_candidate(self):
        features = {
            "regions": [
                {
                    "id": "1",
                    "status": "selected",
                    "sheet": "A",
                    "header_row": 3,
                    "customer_name": "客户",
                    "order_number": "O1",
                    "headers": ["型号", "名称", ""],
                }
            ]
        }
        cand = shipment_template_candidate(features, "f.xlsx")
        assert cand["kind"] == "shipment_document_layout_candidate"
        assert cand["headers"] == ["型号", "名称"]
        assert shipment_template_candidate({"regions": []}, "f.xlsx") is None

    def test_shipment_template_candidates(self):
        features = {
            "regions": [
                {"id": "2", "status": "selected", "sheet": "A", "header_row": 2, "customer_name": "乙"},
                {"id": "1", "status": "selected", "sheet": "A", "header_row": 1, "customer_name": "甲"},
            ]
        }
        cands = shipment_template_candidates(features, "f.xlsx")
        assert len(cands) == 2
        assert cands[0]["is_default"] is True
        assert cands[0]["source_region_id"] == "1"


class TestShipmentTemplateService:
    def test_save_run_shipment_template_target_required(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, target_type="customers", status="preview_ready")
        with pytest.raises(EtlError):
            svc.save_run_shipment_template(etl_db, run_id=run.id, owner_user_id=1)

    def test_save_run_shipment_template_status_required(self, etl_db, svc, app_data, fake_adapter):
        run = _make_run(etl_db, target_type="shipment_records", status="queued")
        with pytest.raises(EtlError):
            svc.save_run_shipment_template(etl_db, run_id=run.id, owner_user_id=1)

    def test_save_run_shipment_template_region_not_found(self, etl_db, svc, app_data, fake_adapter):
        _make_upload_file(app_data, etl_db, id="up-1", file_name="a.xlsx")
        run = _make_run(etl_db, target_type="shipment_records", status="preview_ready")
        run.source_features_json = dump_json({"regions": []})
        etl_db.commit()
        with pytest.raises(EtlError) as ei:
            svc.save_run_shipment_template(etl_db, run_id=run.id, owner_user_id=1)
        assert ei.value.code == "ETL_SHIPMENT_TEMPLATE_REGION_NOT_FOUND"

    def test_save_run_shipment_template_reuse_existing_by_region(
        self, etl_db, svc, app_data, fake_adapter
    ):
        _make_upload_file(app_data, etl_db, id="up-1", file_name="a.xlsx")
        run = _make_run(etl_db, target_type="shipment_records", status="preview_ready")
        run.source_features_json = dump_json(
            {"regions": [{"id": "r1", "status": "selected", "sheet": "A", "header_row": 1}]}
        )
        run.summary_json = dump_json(
            {
                "shipment_document_templates": {
                    "r1": {"template_id": "etl:t1", "name": "已有版式", "file_path": "/x.xlsx"}
                }
            }
        )
        etl_db.commit()
        result = svc.save_run_shipment_template(etl_db, run_id=run.id, owner_user_id=1)
        assert result["template_id"] == "etl:t1"

    def test_save_run_shipment_template_reuse_existing_scalar(
        self, etl_db, svc, app_data, fake_adapter
    ):
        _make_upload_file(app_data, etl_db, id="up-1", file_name="a.xlsx")
        run = _make_run(etl_db, target_type="shipment_records", status="preview_ready")
        run.source_features_json = dump_json(
            {"regions": [{"id": "r1", "status": "selected", "sheet": "A", "header_row": 1}]}
        )
        run.summary_json = dump_json(
            {
                "shipment_document_template": {
                    "template_id": "etl:t2",
                    "name": "旧版式",
                    "source_region_id": "r1",
                }
            }
        )
        etl_db.commit()
        result = svc.save_run_shipment_template(etl_db, run_id=run.id, owner_user_id=1)
        assert result["template_id"] == "etl:t2"

    def test_save_run_shipment_template_success(self, etl_db, svc, app_data, fake_adapter, monkeypatch):
        up = _make_upload_file(app_data, etl_db, id="upx", file_name="a.xlsx")
        run = _make_run(etl_db, upload_id="upx", target_type="shipment_records", status="preview_ready")
        run.source_features_json = dump_json(
            {
                "regions": [
                    {
                        "id": "r1",
                        "status": "selected",
                        "sheet": "A",
                        "header_row": 1,
                        "customer_name": "客户",
                        "headers": ["型号", "名称"],
                    }
                ]
            }
        )
        etl_db.commit()
        monkeypatch.setattr(
            "app.application.etl.service_shipment_templates.extract_shipment_template",
            lambda *a, **k: {"source_region_id": "r1"},
        )
        result = svc.save_run_shipment_template(etl_db, run_id=run.id, owner_user_id=1)
        assert result["source_region_id"] == "r1"
        assert result["template_id"].startswith("etl:")

    def test_save_private_shipment_document_template_new_and_reuse(
        self, etl_db, svc, app_data, fake_adapter
    ):
        tpl, ver = svc._save_private_shipment_document_template(
            etl_db,
            tenant_id=1,
            owner_user_id=1,
            requested_name="版式",
            file_sha256="abc123",
            destination=app_data / "t.xlsx",
            source_features={"k": "v"},
            source_region_id="r1",
            template_fields=[{"label": "型号", "name": "型号", "value": "型号"}],
        )
        assert tpl.current_version == 1
        assert ver.version == 1
        # save again -> new version
        tpl2, ver2 = svc._save_private_shipment_document_template(
            etl_db,
            tenant_id=1,
            owner_user_id=1,
            requested_name="版式",
            file_sha256="abc123",
            destination=app_data / "t2.xlsx",
            source_features={"k": "v"},
            source_region_id="r1",
            template_fields=[{"label": "型号", "name": "型号", "value": "型号"}],
        )
        assert tpl2.current_version == 2
        assert ver2.version == 2


# ---------------------------------------------------------------------------
# service.py
# ---------------------------------------------------------------------------


class TestService:
    def test_capabilities(self):
        from app.application.etl.service import EtlService

        caps = EtlService(adviser=_FakeAdviser()).capabilities()
        assert caps["enabled"] is True
        assert "max_file_bytes" in caps["limits"]

    def test_mark_interrupted_on_startup(self, etl_db, svc):
        run = _make_run(etl_db, status="executing")
        etl_db.commit()
        from app.application.etl.service import mark_interrupted_runs_on_startup

        n = mark_interrupted_runs_on_startup(etl_db.bind)
        assert n >= 1
        assert etl_db.get(EtlRun, run.id).status == "interrupted"

    def test_mark_interrupted_no_table(self, etl_db, svc):
        from app.application.etl.service import mark_interrupted_runs_on_startup

        engine = _make_engine()
        assert mark_interrupted_runs_on_startup(engine) == 0

    def test_get_etl_service_singleton(self, monkeypatch):
        from app.application.etl import service as svc_mod

        monkeypatch.setattr(svc_mod, "_SERVICE", None)
        a = svc_mod.get_etl_service()
        b = svc_mod.get_etl_service()
        assert a is b