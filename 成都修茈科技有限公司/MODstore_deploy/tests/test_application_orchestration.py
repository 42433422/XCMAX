"""Application-layer orchestration smoke tests (in-memory bus + repos)."""

from __future__ import annotations

from pathlib import Path

from modstore_server.application.catalog import CatalogApplicationService
from modstore_server.application.employee import EmployeeApplicationService
from modstore_server.eventing.bus import InMemoryNeuroBus
from modstore_server.eventing.contracts import CATALOG_PACKAGE_PUBLISHED, EMPLOYEE_PACK_REGISTERED
from modstore_server.infrastructure.catalog_repository import (
    InMemoryCatalogPackageStorage,
    InMemoryCatalogRepository,
)


def test_catalog_register_publishes_event(tmp_path):
    bus = InMemoryNeuroBus()
    seen: list[str] = []

    def cap(ev):
        seen.append(ev.event_name)

    bus.subscribe("*", cap)
    storage = InMemoryCatalogPackageStorage()
    svc = CatalogApplicationService(
        storage=storage,
        bus=bus,
        catalog_repository=InMemoryCatalogRepository(),
    )

    class _Sess:
        def flush(self):
            return None

        def commit(self):
            return None

    zf = Path(tmp_path / "f.zip")
    zf.write_bytes(b"PK\x03\x04")
    svc.register_employee_pack(
        _Sess(),
        author_id=1,
        mod_id="m1",
        pack_id="p1",
        package_record={"id": "p1", "version": "1.0.0", "name": "N", "artifact": "employee_pack"},
        package_file=zf,
        price=0.0,
    )
    assert CATALOG_PACKAGE_PUBLISHED in seen


def test_employee_register_pack_publishes_event():
    bus = InMemoryNeuroBus()
    seen: list[str] = []

    def cap(ev):
        seen.append(ev.event_name)

    bus.subscribe("*", cap)
    svc = EmployeeApplicationService(bus=bus)
    svc.register_pack(author_id=2, mod_id="m", pack_id="pk", version="1.0.0")
    assert EMPLOYEE_PACK_REGISTERED in seen
