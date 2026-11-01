"""The exact reviewed Mod database context survives asynchronous ETL stages."""

from threading import Event

from app.application.elt import service_draft, service_execution, service_preview
from app.db.models import PurchaseUnit
from app.infrastructure.tenant_scope import current_tenant_id
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)
from tests.test_application.test_etl_preview_task_boundaries import (
    create_preview,
    snapshot,
)
from tests.test_application.test_etl_preview_task_boundaries import (
    preview_store as preview_store,
)


def test_preview_revalidation_and_execution_keep_mod_scope_without_worker_leak(
    preview_store, monkeypatch
):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    observed = []
    for module in (service_preview, service_draft, service_execution):

        def open_session(stage=module.__name__):
            observed.append(
                (stage.rsplit(".", 1)[-1], get_request_active_mod_id(), current_tenant_id())
            )
            return store.factory()

        monkeypatch.setattr(module, "new_session", open_session)

    # Hold the single worker so the initiating request can leave its Mod context.
    release = Event()
    store.executor.submit(release.wait, 10)
    token = set_request_active_mod_id("reviewed-mod")
    try:
        run_id = create_preview(store)
    finally:
        reset_request_active_mod_id(token)
        release.set()
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, run_id)["status"] == "preview_ready"
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0

    token = set_request_active_mod_id("reviewed-mod")
    try:
        with store.factory() as db:
            store.service.update_draft(
                db, run_id=run_id, owner_user_id=7, patch={"validation_rules": []}
            )
        store.executor.futures[-1].result(timeout=10)
        revision = snapshot(store, run_id)["preview_revision"]
        with store.factory() as db:
            store.service.execute(
                db,
                run_id=run_id,
                owner_user_id=7,
                confirmed=True,
                valid_rows_only=False,
                preview_revision=revision,
            )
        store.executor.futures[-1].result(timeout=10)
    finally:
        reset_request_active_mod_id(token)
    assert snapshot(store, run_id)["summary"]["executed"] == 2
    assert observed == [
        (stage, "reviewed-mod", 1)
        for stage in (
            "service_preview",
            "service_draft",
            "service_execution",
        )
    ]
    assert store.executor.submit(get_request_active_mod_id).result(timeout=10) == ""
    assert store.executor.submit(current_tenant_id).result(timeout=10) is None


def test_auto_ingest_thread_keeps_confirming_mod_after_request_ends(
    preview_store, tmp_path, monkeypatch
):
    from app.application.elt import auto_ingest_service

    service = auto_ingest_service.AutoIngestService()
    monkeypatch.setattr(auto_ingest_service, "get_app_data_dir", lambda: str(tmp_path))
    source = tmp_path / "confirmed.txt"
    source.write_text("confirmed")
    release, completed = Event(), Event()
    observed = []

    def run(_db, **kwargs):
        try:
            assert release.wait(timeout=10)
            observed.append((get_request_active_mod_id(), current_tenant_id(), kwargs))
        finally:
            completed.set()

    monkeypatch.setattr(service, "run", run)
    token = set_request_active_mod_id("confirmed-mod")
    try:
        service.start_background(
            owner_user_id=7,
            tenant_id=1,
            source_path=source,
            prepared_plan={"run_id": "confirmed-preview", "mod_id": "confirmed-mod"},
        )
    finally:
        reset_request_active_mod_id(token)
        release.set()
    assert completed.wait(timeout=10)
    assert len(observed) == 1
    mod_id, tenant_id, kwargs = observed[0]
    assert (mod_id, tenant_id) == ("confirmed-mod", 1)
    assert kwargs["prepared_plan"]["run_id"] == "confirmed-preview"
    assert get_request_active_mod_id() == ""
