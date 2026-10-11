import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text

from app.services import shipment_order_number as numbers


@pytest.fixture
def allocator(tmp_path, monkeypatch):
    db = tmp_path / "runtime.db"
    engine = create_engine(f"sqlite:///{db}", connect_args={"timeout": 30})
    monkeypatch.setattr(numbers, "get_runtime_engine", lambda: engine)
    monkeypatch.setattr(numbers, "get_shipment_output_dir", lambda: str(tmp_path))
    yield engine, tmp_path, db
    engine.dispose()


def test_shared_document_sequence_and_restart(allocator):
    from app.legacy.documents.legacy_shipment_document import (
        load_legacy_shipment_document_generator,
    )

    engine, folder, db = allocator
    loaded = load_legacy_shipment_document_generator(caller_file=__file__)
    generator = loaded.ShipmentDocumentGenerator(
        db_path=str(folder / "products.db"), output_dir=str(folder)
    )
    doc1 = generator.generate_document("", {"products": [{"name": "first"}]})
    preview = numbers.reserve_order_number()
    doc2 = generator.generate_document("", {"products": [{"name": "second"}]})
    assert [doc1.order_number, preview["order_number"], doc2.order_number] == [
        f"{preview['year_month']}-{i:05d}A" for i in (1, 2, 3)
    ]
    engine.dispose()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "XCAGI_DATA_DIR": str(folder)}
    restarted = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from app.legacy.documents.legacy_shipment_document import load_legacy_shipment_document_generator as load; "
            "import os; g=load(caller_file=__file__ if '__file__' in globals() else 'test').ShipmentDocumentGenerator("
            "output_dir=os.environ['XCAGI_DATA_DIR']); print(g.generate_document('', {'products': [{'name': 'restart'}]}).order_number)",
        ],
        env=env,
        text=True,
    )
    assert restarted.strip() == f"{preview['year_month']}-00004A"
    from openpyxl import load_workbook

    for path in folder.glob("*.xlsx"):
        workbook = load_workbook(path)
        assert path.stem.split("_")[1] in str(workbook.active["A2"].value)
        workbook.close()


def test_history_concurrency_and_month_rollover(allocator):
    engine, folder, _ = allocator
    (folder / "发货单_26-1000042A_old.xlsx").touch()
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.execute(text("CREATE TABLE orders(order_number TEXT)"))
        conn.execute(text("INSERT INTO orders VALUES ('26-10-00055B')"))
    allocate = lambda _: numbers.reserve_order_number(now=datetime(2026, 10, 11))["sequence"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sorted(pool.map(allocate, range(20))) == list(range(56, 76))
    assert numbers.reserve_order_number(now=datetime(2026, 11, 1))["sequence"] == 1


def test_failure_creates_no_document(allocator, monkeypatch):
    from app.legacy.documents.legacy_shipment_document import (
        load_legacy_shipment_document_generator,
    )

    _, folder, _ = allocator
    loaded = load_legacy_shipment_document_generator(caller_file=__file__)
    generator = loaded.ShipmentDocumentGenerator(
        db_path=str(folder / "products.db"), output_dir=str(folder)
    )
    monkeypatch.setattr(
        numbers,
        "get_runtime_engine",
        lambda: create_engine(f"sqlite:///{folder / 'missing' / 'bad.db'}"),
    )
    with pytest.raises(Exception, match="unable to open database"):
        generator.generate_document("", {"products": [{"name": "failed"}]})
    assert not list(folder.glob("*.xlsx"))


@pytest.mark.parametrize("legacy", [False, True])
def test_custom_output_history_is_scoped(allocator, legacy):
    from app.legacy.documents.legacy_shipment_document import (
        load_legacy_shipment_document_generator,
    )

    _, folder, _ = allocator
    custom = folder / "customer-output"
    custom.mkdir()
    period = datetime.now().strftime("%y-%m")
    history = f"{period}-00042A"
    if legacy:
        year, month = period.split("-")
        history = f"{year}-{month}00042A"
    (custom / f"发货单_{history}_old.xlsx").touch()
    unrelated = folder / "other-customer"
    unrelated.mkdir()
    (unrelated / f"发货单_{period}-00999A_old.xlsx").touch()
    loaded = load_legacy_shipment_document_generator(caller_file=__file__)
    generator = loaded.ShipmentDocumentGenerator(output_dir=str(custom))
    assert generator._generate_order_number() == f"{period}-00043A"
    assert numbers.reserve_order_number()["order_number"] == f"{period}-00044A"
