"""Label output against real PostgreSQL models and the production template bootstrap."""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager

import pytest
from pypdf import PdfReader
from sqlalchemy import text

from app.application import label_job_service as jobs
from app.db.init_db import init_template_tables_for_engine
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_rollback_compare_swap import store as store
from tests.test_application.test_label_jobs import TEMPLATE


@pytest.mark.parametrize("store", ["postgres"], indirect=True)
def test_label_selection_and_pdf_use_real_postgres_product_and_template_rows(
    store, tmp_path, monkeypatch
):
    engine, factory, (_customer_id, product_id) = store
    init_template_tables_for_engine(engine)
    template = copy.deepcopy(TEMPLATE)
    template["fields"][2].update(label="单价", type="dynamic", binding="price")
    with engine.begin() as connection:
        for tenant_id, template_id in ((1, 42), (2, 43)):
            connection.execute(
                text(
                    "INSERT INTO templates (id, tenant_id, template_name, template_type, "
                    "analyzed_data, editable_config, business_rules, is_active) "
                    "VALUES (:id, :tenant, 'PG中文产品标签', '标签', :data, '[]', '{}', 1)"
                ),
                {
                    "id": template_id,
                    "tenant": tenant_id,
                    "data": json.dumps(template, ensure_ascii=False),
                },
            )

    @contextmanager
    def database():
        with factory() as session:
            yield session

    monkeypatch.setattr(jobs, "get_db", database)
    service = jobs.LabelJobService(tmp_path / "label_jobs")
    owner = (1, 7)
    payload = {
        "product_id": product_id,
        "template_id": "db:42",
        "copies": 3,
        "paper_width_mm": 90,
        "paper_height_mm": 60,
    }
    with tenant_scope(1):
        listed = service.products(owner, "CAS-1", 1, 10)
        assert listed["total"] == 1
        assert listed["data"][0]["id"] == product_id
        assert service.products((2, 7), "", 1, 10)["total"] == 0
        job = service.generate(owner, payload)
        pdf = PdfReader(service.file(owner, job["id"]))
        assert len(pdf.pages) == 3
        for page in pdf.pages:
            content = page.extract_text()
            assert "并发回滚产品" in content and "CAS-1" in content and "单价: 10" in content
        for wrong_owner, wrong_payload in (
            ((2, 7), payload),
            (owner, {**payload, "template_id": "db:43"}),
        ):
            with pytest.raises(jobs.LabelJobError) as error:
                service.generate(wrong_owner, wrong_payload)
            assert error.value.status == 404
        assert len(list(tmp_path.rglob("labels.pdf"))) == 1
