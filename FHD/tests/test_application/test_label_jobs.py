"""Real selected-template PDF artifacts, ownership, confirmation, and queue outcomes."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.application import label_job_service as jobs
from app.fastapi_routes import label_jobs, print_routes
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.printing import label_pdf_printer as pdf_printer
from app.middleware.csrf import CSRFMiddleware

OWNER = (11, 7)
PAYLOAD = {
    "product_id": 2,
    "template_id": "db:42",
    "copies": 3,
    "paper_width_mm": 90,
    "paper_height_mm": 60,
}
TEMPLATE = {
    "category": "label",
    "fields": [
        {
            "id": "name",
            "label": "品名",
            "type": "dynamic",
            "value": "SAMPLE MUST NOT PRINT",
            "position": {"left": 22, "top": 30, "width": 600, "height": 40},
        },
        {
            "id": "model",
            "label": "型号",
            "type": "dynamic",
            "position": {"left": 32, "top": 90, "width": 400, "height": 40},
        },
        {
            "id": "fixed",
            "label": "客户",
            "type": "fixed",
            "value": "客户甲",
            "position": {"left": 32, "top": 150, "width": 400, "height": 40},
        },
    ],
    "preview_data": {
        "image_size": {"width": 900, "height": 600},
        "grid": {"horizontal_lines": [210], "vertical_lines": [850]},
    },
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'isolated.db'}")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE products (id INTEGER, tenant_id INTEGER, name TEXT, model_number TEXT, specification TEXT, price NUMERIC, unit TEXT, brand TEXT, category TEXT, description TEXT, quantity INTEGER, is_active INTEGER)"
            )
        )
        db.execute(
            text(
                "INSERT INTO products VALUES (1,11,'同名产品','WRONG-1','10cm',12,'个','A','饰品','说明',4,1),(2,11,'同名产品','CORRECT-2','20cm',22,'个','A','饰品','说明',9,1),(3,12,'OTHER TENANT','SECRET','',1,'','','','',1,1)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE templates (id INTEGER, tenant_id INTEGER, template_name TEXT, template_type TEXT, analyzed_data TEXT, editable_config TEXT, business_rules TEXT, original_file_path TEXT, is_active INTEGER)"
            )
        )
        for tid, template_id in ((11, 42), (12, 43)):
            db.execute(
                text(
                    "INSERT INTO templates VALUES (:id,:tid,'客户甲专属模板','标签',:data,'[]','{}',NULL,1)"
                ),
                {"id": template_id, "tid": tid, "data": json.dumps(TEMPLATE, ensure_ascii=False)},
            )

    @contextmanager
    def database():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(jobs, "get_db", database)
    service = jobs.LabelJobService(tmp_path / "label_jobs")
    monkeypatch.setattr(label_jobs, "_service", lambda: service)
    monkeypatch.setattr(pdf_printer, "get_app_data_dir", lambda: str(tmp_path))
    app = FastAPI()
    app.include_router(print_routes.router)
    app.add_middleware(CSRFMiddleware)
    app.dependency_overrides[get_logged_in_user] = lambda: SimpleNamespace(id=7, tenant_id=11)
    client = TestClient(app)
    client.cookies.set("csrf_token", "label-test")
    client.headers["X-CSRF-Token"] = "label-test"
    yield SimpleNamespace(service=service, engine=engine, client=client, app=app, tmp=tmp_path)
    client.close()
    engine.dispose()


def create(env):
    response = env.client.post("/api/print/label-jobs", json=PAYLOAD)
    assert response.status_code == 200, response.text
    return response.json()["job"]


def test_real_product_id_selected_template_content_pages_and_physical_size(env):
    job = create(env)
    response = env.client.get(f"/api/print/label-jobs/{job['id']}/file")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    pdf = PdfReader(env.service.file(OWNER, job["id"]))
    assert len(pdf.pages) == 3
    for page in pdf.pages:
        content = page.extract_text()
        assert "同名产品" in content and "CORRECT-2" in content and "客户甲" in content
        assert "WRONG-1" not in content and "SAMPLE" not in content
        assert float(page.mediabox.width) == pytest.approx(90 * 72 / 25.4, abs=0.001)
        assert float(page.mediabox.height) == pytest.approx(60 * 72 / 25.4, abs=0.001)
    _, internal = env.service._read(OWNER, job["id"])
    assert internal["layout"]["fields"][0]["left"] == 22
    assert internal["layout"]["fields"][1]["top"] == 90
    assert internal["template_id"] == "db:42"
    assert "file_path" not in job and "confirm_hash" not in job


@pytest.mark.parametrize(
    "payload",
    [
        {"product_id": 99},
        {"product_id": 3},
        {"template_id": "db:43"},
        {"template_id": "db:999"},
        {"template_id": "builtin:demo"},
        {"copies": 0},
        {"copies": 101},
        {"copies": 1.5},
        {"product_id": True},
        {"paper_width_mm": 0},
        {"file_path": "/etc/passwd"},
    ],
)
def test_unknown_cross_tenant_invalid_inputs_fail_closed(env, payload):
    response = env.client.post("/api/print/label-jobs", json={**PAYLOAD, **payload})
    assert response.status_code in {400, 404, 422}
    assert not list(env.tmp.rglob("*.pdf"))


def test_authentication_csrf_and_user_scope_on_every_action(env):
    job = create(env)
    base = f"/api/print/label-jobs/{job['id']}"
    env.client.headers.pop("X-CSRF-Token")
    assert env.client.post("/api/print/label-jobs", json=PAYLOAD).status_code == 403
    env.client.headers["X-CSRF-Token"] = "label-test"
    for user in (SimpleNamespace(id=8, tenant_id=11), SimpleNamespace(id=7, tenant_id=12)):
        env.app.dependency_overrides[get_logged_in_user] = lambda: user
        assert env.client.get(base).status_code == 404
        assert env.client.get(base + "/file").status_code == 404
        assert (
            env.client.post(base + "/submit", json={"confirm_token": "x" * 32}).status_code == 404
        )
    env.app.dependency_overrides.clear()
    assert env.client.get(base + "/file").status_code == 401
    assert env.client.post("/api/print/label-jobs", json=PAYLOAD).status_code == 401


def test_file_integrity_and_symlink_rejection(env):
    job = create(env)
    path = env.service.file(OWNER, job["id"])
    path.write_bytes(b"changed")
    assert env.client.get(f"/api/print/label-jobs/{job['id']}/file").status_code == 409
    path.unlink()
    outside = env.tmp / "secret.pdf"
    outside.write_bytes(b"secret")
    path.symlink_to(outside)
    assert env.client.get(f"/api/print/label-jobs/{job['id']}/file").status_code == 404
    with pytest.raises(jobs.LabelJobError):
        env.service.file(OWNER, "../secret")


def test_missing_geometry_no_samples_and_failed_render_removes_partial_file(env, monkeypatch):
    broken = json.loads(json.dumps(TEMPLATE))
    del broken["fields"][0]["position"]
    with env.engine.begin() as db:
        db.execute(
            text("UPDATE templates SET analyzed_data=:data WHERE id=42"),
            {"data": json.dumps(broken)},
        )
    response = env.client.post("/api/print/label-jobs", json=PAYLOAD)
    assert response.status_code == 400 and "位置" in response.text
    assert not list(env.tmp.rglob("*.pdf"))
    assert any(
        json.loads(p.read_text())["status"] == "generation_failed"
        for p in env.tmp.rglob("job.json")
    )

    def fail(path, *args):
        path.write_bytes(b"partial")
        raise OSError("renderer failed")

    monkeypatch.setattr(jobs, "render_template_label", fail)
    assert env.client.post("/api/print/label-jobs", json=PAYLOAD).status_code == 400
    assert not list(env.tmp.rglob("*.pdf"))


def test_no_print_before_confirmation_atomic_token_consumption_and_restart(env):
    job = create(env)
    dispatch = MagicMock(return_value={"success": True, "submission_state": "submitted"})
    with pytest.raises(jobs.LabelJobError):
        env.service.submit(OWNER, job["id"], "unconfirmed", dispatch)
    dispatch.assert_not_called()
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
    restarted = jobs.LabelJobService(env.service.root)
    result = restarted.submit(OWNER, job["id"], confirmation["confirm_token"], dispatch)
    assert result["status"] == "submitted"
    restarted.submit(OWNER, job["id"], confirmation["confirm_token"], dispatch)
    assert dispatch.call_count == 1
    assert dispatch.call_args.args[0]["copies"] == 1  # PDF already contains three pages
    with pytest.raises(jobs.LabelJobError):
        restarted.confirmation(OWNER, job["id"], "LabelPrinter")


@pytest.mark.parametrize("failure_type", [TimeoutError, TypeError])
def test_expired_failed_and_uncertain_submissions_have_distinct_retry_rules(
    env, monkeypatch, failure_type
):
    job = create(env)
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
    with monkeypatch.context() as patcher:
        patcher.setattr(jobs.time, "time", lambda: 10**12)
        with pytest.raises(jobs.LabelJobError):
            env.service.submit(OWNER, job["id"], confirmation["confirm_token"], MagicMock())
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
    rejected = env.service.submit(
        OWNER,
        job["id"],
        confirmation["confirm_token"],
        lambda _: {"submission_state": "rejected", "message": "printer offline"},
    )
    assert rejected["status"] == "failed"
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")

    ambiguous = MagicMock(side_effect=failure_type("response lost after queue submission"))

    assert (
        env.service.submit(OWNER, job["id"], confirmation["confirm_token"], ambiguous)["status"]
        == "outcome_unknown"
    )
    restarted = jobs.LabelJobService(env.service.root)
    assert restarted.get(OWNER, job["id"])["status"] == "outcome_unknown"
    assert (
        restarted.submit(OWNER, job["id"], confirmation["confirm_token"], ambiguous)["status"]
        == "outcome_unknown"
    )
    ambiguous.assert_called_once()
    with pytest.raises(jobs.LabelJobError):
        restarted.confirmation(OWNER, job["id"], "LabelPrinter")
    env.service.file(OWNER, job["id"])


def test_submit_uses_real_agent_and_authenticated_identity(env, monkeypatch):
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    from app.services.printer_service import PrinterService

    service = PrinterService.__new__(PrinterService)
    service.printer_utils = MagicMock()
    service.printer_utils._resolve_cups_printer_name.return_value = "LabelPrinter"
    service.printer_utils._run_cups.return_value = SimpleNamespace(returncode=0)
    monkeypatch.setattr(pdf_printer, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(print_routes, "_svc", lambda: service)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(env.tmp / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    job = create(env)
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = env.client.post(
            f"/api/print/label-jobs/{job['id']}/submit",
            json={"confirm_token": confirmation["confirm_token"]},
            headers={"X-User-Id": "spoofed-user"},
        )
    assert response.status_code == 200, response.text
    result = response.json()["job"]
    assert result["status"] == "submitted"
    run = repo.get(result["run_id"])
    assert run.user_id == "7"
    assert {"step.waiting_user", "step.approved", "tool.completed"} <= {
        e.event_type for e in run.events
    }
    assert set(run.tool_calls[0].params) == {"file_path", "printer_name", "copies"}
    service.printer_utils._run_cups.assert_called_once()
    _, persisted = env.service._read(OWNER, job["id"])
    assert persisted["dispatch_claimed"] is True
    assert "dispatch_hash" not in persisted
    service.print_label(str(env.service.file(OWNER, job["id"])), "LabelPrinter", 1)
    assert service.printer_utils._run_cups.call_count == 1


def test_platform_adapter_pdf_cups_and_windows_no_raw(env, monkeypatch):
    utils = MagicMock()
    utils._resolve_cups_printer_name.return_value = "LabelPrinter"
    utils._run_cups.return_value = SimpleNamespace(returncode=0)
    for platform, side_effect, expected in (
        ("darwin", None, "submitted"),
        ("darwin", TimeoutError(), "outcome_unknown"),
        ("win32", None, "failed"),
    ):
        monkeypatch.setattr(pdf_printer, "sys", SimpleNamespace(platform=platform))
        utils._run_cups.side_effect = side_effect
        job = create(env)
        confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
        outcome = env.service.submit(
            OWNER,
            job["id"],
            confirmation["confirm_token"],
            lambda params: pdf_printer.submit_label_pdf(
                utils, params["file_path"], params["printer_name"]
            ),
        )
        assert outcome["status"] == expected
    assert utils._run_cups.call_count == 2


def test_concurrent_submit_observes_persisted_inflight_state_and_never_dispatches_twice(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    job = create(env)
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
    entered, release = Event(), Event()

    def dispatch(_):
        entered.set()
        assert release.wait(3)
        return {"submission_state": "submitted"}

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            env.service.submit, OWNER, job["id"], confirmation["confirm_token"], dispatch
        )
        assert entered.wait(3)
        never = MagicMock()
        other_process = jobs.LabelJobService(env.service.root)
        assert (
            other_process.submit(OWNER, job["id"], confirmation["confirm_token"], never)["status"]
            == "submitting"
        )
        never.assert_not_called()
        release.set()
        assert first.result()["status"] == "submitted"


def test_saved_paper_size_is_preserved_and_cannot_be_silently_changed(env):
    template = json.loads(json.dumps(TEMPLATE))
    template["preview_data"]["layout"] = {"paper_width_mm": 80, "paper_height_mm": 50}
    with env.engine.begin() as db:
        db.execute(
            text("UPDATE templates SET analyzed_data=:data WHERE id=42"),
            {"data": json.dumps(template)},
        )
    assert env.client.post("/api/print/label-jobs", json=PAYLOAD).status_code == 400
    response = env.client.post(
        "/api/print/label-jobs", json={**PAYLOAD, "paper_width_mm": 80, "paper_height_mm": 50}
    )
    assert response.status_code == 200
    pdf = PdfReader(env.service.file(OWNER, response.json()["job"]["id"]))
    assert float(pdf.pages[0].mediabox.width) == pytest.approx(80 * 72 / 25.4, abs=0.001)


@pytest.mark.parametrize(
    "change",
    [
        {"binding": "unknown_column"},
        {"type": "barcode"},
        {"position": {"left": 10000, "top": 0, "width": 40, "height": 30}},
    ],
)
def test_unsupported_template_fields_fail_closed(env, change):
    template = json.loads(json.dumps(TEMPLATE))
    template["fields"][0].update(change)
    with env.engine.begin() as db:
        db.execute(
            text("UPDATE templates SET analyzed_data=:data WHERE id=42"),
            {"data": json.dumps(template)},
        )
    response = env.client.post("/api/print/label-jobs", json=PAYLOAD)
    assert response.status_code == 400
    assert not list(env.tmp.rglob("*.pdf"))


def test_safe_saved_background_and_grid_are_present_in_pdf(env):
    import base64
    import io

    from PIL import Image

    image = Image.new("RGB", (900, 600), (255, 0, 0))
    data = io.BytesIO()
    image.save(data, format="PNG")
    template = json.loads(json.dumps(TEMPLATE))
    template["preview_data"]["image"] = (
        "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()
    )
    with env.engine.begin() as db:
        db.execute(
            text("UPDATE templates SET analyzed_data=:data WHERE id=42"),
            {"data": json.dumps(template)},
        )
    job = create(env)
    pdf = PdfReader(env.service.file(OWNER, job["id"]))
    assert len(pdf.pages[0].images) == 1
    commands = pdf.pages[0].get_contents().get_data()
    assert b"0 390 m 900 390 l S" in commands
    assert b"850 0 m 850 600 l S" in commands


def test_live_printer_service_uses_safe_pdf_adapter_only_once(env, monkeypatch):
    from app.services.printer_service import PrinterService

    job = create(env)
    path = str(env.service.file(OWNER, job["id"]))
    adapter = MagicMock(return_value={"success": True, "submission_state": "submitted"})
    monkeypatch.setattr(pdf_printer, "submit_label_pdf", adapter)
    printer = PrinterService.__new__(PrinterService)
    printer.printer_utils = MagicMock()
    assert printer.print_label(path, "Labels", 1)["submission_state"] == "submitted"
    adapter.assert_called_once_with(printer.printer_utils, path, "Labels")
    assert printer.print_label(path, "Labels", 3)["submission_state"] == "rejected"
    assert adapter.call_count == 1


def test_product_selection_uses_same_tenant_source_with_search_and_pagination(env):
    base = "/api/print/label-jobs/products"
    page1 = env.client.get(base, params={"page": 1, "per_page": 1}).json()
    page2 = env.client.get(base, params={"page": 2, "per_page": 1}).json()
    assert page1["total"] == page2["total"] == 2
    assert page1["data"][0]["id"] == 1
    assert page2["data"][0]["id"] == 2
    search = env.client.get(base, params={"keyword": "correct-2"}).json()
    assert search["total"] == 1 and search["data"][0]["id"] == 2
    assert env.client.get(base, params={"keyword": "SECRET"}).json()["total"] == 0
    assert env.client.get(base, params={"per_page": 1001}).status_code == 422
    env.app.dependency_overrides.clear()
    assert env.client.get(base).status_code == 401


def test_legacy_routes_cannot_print_controlled_job_without_internal_dispatch(env, monkeypatch):
    from app.services.printer_service import PrinterService
    from app.utils.path_io.print_utils import PrinterUtils

    job = create(env)
    path = str(env.service.file(OWNER, job["id"]))
    service = PrinterService.__new__(PrinterService)
    service.printer_utils = MagicMock()
    monkeypatch.setattr(print_routes, "_svc", lambda: service)
    monkeypatch.setattr(pdf_printer, "sys", SimpleNamespace(platform="darwin"))
    # Exercise the real compatibility route -> agent -> PrinterService path.
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(env.tmp / "usage-legacy.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=InMemoryAgentRunRepository(),
    ):
        response = env.client.post(
            "/api/print/label",
            json={
                "file_path": path,
                "printer_name": "LabelPrinter",
                "copies": 1,
                "require_confirm": False,
            },
        )
    assert response.json()["success"] is False
    service.printer_utils._run_cups.assert_not_called()
    service.printer_utils.print_file.assert_not_called()
    service.enhanced_utils = MagicMock()
    assert service.print_document(path, "LabelPrinter", use_automation=True)["success"] is False
    service.enhanced_utils.print_file_enhanced.assert_not_called()
    from app.utils.path_io.printer_automation import PrinterAutomation

    automation = PrinterAutomation()
    assert automation.print_with_automation(path, "LabelPrinter")["success"] is False

    # Even an explicitly allowed root cannot turn a managed PDF into an ordinary file.
    monkeypatch.setenv("XCAGI_PRINT_ALLOWED_ROOTS", str(env.service.file(OWNER, job["id"]).parent))
    assert PrinterUtils._resolve_allowed_print_path(path) is None


def test_physical_dispatch_claim_cannot_replay_or_escape_owner_hash_printer(env, monkeypatch):
    from app.infrastructure.printing.label_dispatch_guard import (
        authorized_label_dispatch,
        claim_label_dispatch,
    )

    job = create(env)
    path = env.service.file(OWNER, job["id"])
    confirmation = env.service.confirmation(OWNER, job["id"], "LabelPrinter")
    results = []

    def dispatch(_):
        assert claim_label_dispatch(path, "OtherPrinter") is False
        assert claim_label_dispatch(path, "LabelPrinter", 2) is False
        # A new worker without copied internal context must fail closed.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(claim_label_dispatch, path, "LabelPrinter").result() is False
        assert claim_label_dispatch(path, "LabelPrinter") is True
        assert claim_label_dispatch(path, "LabelPrinter") is False
        results.append(True)
        return {"submission_state": "submitted"}

    assert (
        env.service.submit(OWNER, job["id"], confirmation["confirm_token"], dispatch)["status"]
        == "submitted"
    )
    with authorized_label_dispatch(path, "forged-internal-ticket"):
        assert claim_label_dispatch(path, "LabelPrinter") is False
    assert results == [True]


def test_pdf_embeds_chinese_font_and_missing_font_or_glyph_fails_closed(env, monkeypatch):
    from app.infrastructure.printing import template_label_renderer as renderer

    job = create(env)
    pdf = PdfReader(env.service.file(OWNER, job["id"]))
    fonts = [value.get_object() for value in pdf.pages[0]["/Resources"]["/Font"].values()]
    embedded = [font["/FontDescriptor"] for font in fonts if "/FontDescriptor" in font]
    assert embedded and any(
        "/FontFile2" in descriptor or "/FontFile3" in descriptor for descriptor in embedded
    )
    assert all("STSong" not in str(font) for font in fonts)
    with monkeypatch.context() as patcher:
        patcher.setattr(renderer, "_FONT_PATH", env.tmp / "missing.ttf")
        response = env.client.post("/api/print/label-jobs", json=PAYLOAD)
        assert response.status_code == 400 and "字体资源缺失" in response.text
    with env.engine.begin() as db:
        db.execute(text("UPDATE products SET name=:name WHERE id=2"), {"name": chr(0x10FFFF)})
    response = env.client.post("/api/print/label-jobs", json=PAYLOAD)
    assert response.status_code == 400 and "缺少字符" in response.text


def test_concurrent_chinese_pdf_subsets_never_mix_product_text(env):
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.printing.template_label_renderer import render_template_label

    def generate(index):
        path = env.tmp / f"parallel-{index}.pdf"
        render_template_label(
            path,
            TEMPLATE,
            {"name": f"中文产品{index}号", "model_number": f"型号{index}"},
            2,
            90,
            60,
        )
        return "".join(page.extract_text() for page in PdfReader(path).pages)

    with ThreadPoolExecutor(max_workers=4) as pool:
        texts = list(pool.map(generate, range(4)))
    for index, content in enumerate(texts):
        assert f"中文产品{index}号" in content
        assert all(f"中文产品{other}号" not in content for other in range(4) if other != index)
