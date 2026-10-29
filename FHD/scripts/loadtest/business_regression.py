"""Synthetic business-path regressions; each size runs in a fresh process.

This checks work and memory bounds, not production capacity. All fixtures live in
TemporaryDirectory; neither customer databases nor paid model providers are used.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD))


def im_case(rows: int, directory: Path) -> dict:
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session

    from app.application.im_app_service import ImApplicationService
    from app.db.db_base import Base
    from app.db.models.im import ImConversation, ImConversationMember, ImMessage
    from app.db.models.user import User

    engine = create_engine("sqlite:///:memory:")
    tables = [
        User.__table__,
        ImConversation.__table__,
        ImConversationMember.__table__,
        ImMessage.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.execute(
            User.__table__.insert(),
            [
                {
                    "id": i,
                    "username": f"perf-{i}",
                    "password": "!",
                    "display_name": f"Synthetic {i}",
                }
                for i in range(1, rows + 2)
            ],
        )
        connection.execute(
            ImConversation.__table__.insert(),
            [
                {
                    "id": i,
                    "title": f"Synthetic {i}",
                    "is_direct": True,
                    "last_message_at": datetime(2026, 1, 1),
                }
                for i in range(1, rows + 1)
            ],
        )
        connection.execute(
            ImConversationMember.__table__.insert(),
            [
                {"conversation_id": i, "user_id": user, "last_read_message_id": 0}
                for i in range(1, rows + 1)
                for user in (1, i + 1)
            ],
        )
        connection.execute(
            ImMessage.__table__.insert(),
            [
                {"conversation_id": i, "sender_user_id": i + 1, "body": "Synthetic message"}
                for i in range(1, rows + 1)
                for _ in range(10)
            ],
        )
    count = 0

    def counted(*_args):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", counted)
    samples = []
    try:
        for _ in range(3):
            count = 0
            with Session(engine) as session:
                started = time.perf_counter()
                items, cursor = ImApplicationService(session).list_conversations_page(1, limit=50)
                elapsed = (time.perf_counter() - started) * 1000
                assert len(items) == 50 and cursor, (
                    "First page must retain access to later conversations"
                )
            samples.append({"elapsed_ms": elapsed, "sql_statements": count})
        assert all(sample["sql_statements"] <= 6 for sample in samples), samples
        return {
            "conversations": rows,
            "messages": rows * 10,
            "page_size": 50,
            "query_budget": 6,
            "samples": samples,
        }
    finally:
        engine.dispose()


def vector_case(rows: int, directory: Path) -> dict:
    from app.infrastructure.rag.dataset_vector_index import DatasetVectorSQLiteIndex
    from app.infrastructure.rag.hybrid_retriever import RetrievedChunk

    index = DatasetVectorSQLiteIndex(directory / "vectors.sqlite")
    embedding = [(i % 19 - 9) / 19 for i in range(256)]
    chunks = [
        RetrievedChunk(
            text=f"Synthetic chunk {i}",
            score=0,
            chunk_index=i,
            metadata={
                "tenant_id": "perf",
                "document_id": "synthetic",
                "document_version": 1,
                "_embedding": embedding,
            },
        )
        for i in range(rows)
    ]
    index.replace_dataset("synthetic", chunks)
    del chunks
    gc.collect()
    samples = []
    for _ in range(3):
        tracemalloc.start()
        started = time.perf_counter()
        result = index.query("synthetic", embedding, top_k=5, tenant_id="perf")
        elapsed = (time.perf_counter() - started) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert len(result) == 5
        assert all(item.metadata["tenant_id"] == "perf" for item in result)
        assert peak <= 10 * 1024**2, f"Vector query allocated {peak} bytes"
        samples.append({"elapsed_ms_with_tracemalloc": elapsed, "python_peak_bytes": peak})
    return {
        "chunks": rows,
        "dimensions": 256,
        "top_k": 5,
        "python_peak_budget_bytes": 10 * 1024**2,
        "samples": samples,
        "algorithm": "exact SQLite scan; memory bound does not claim ANN latency",
    }


def csv_case(rows: int, directory: Path) -> dict:
    import psutil

    from app.application.etl.parsers import MAX_ROWS, _parse_csv

    fixture = directory / "synthetic.csv"
    with fixture.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "产品名称",
                "产品编码",
                "规格",
                "单位",
                "单价",
                "库存",
                "仓库",
                "分类",
                "备注",
                "品牌",
                "型号",
                "批次",
            ]
        )
        for i in range(rows):
            writer.writerow(
                [
                    f"测试产品{i:06d}",
                    f"TEST-{i:06d}",
                    "100x200",
                    "件",
                    "12.50",
                    str(i % 100),
                    "测试仓库",
                    "合成样例",
                    "性能回归合成数据",
                    "TEST",
                    "M01",
                    "20261029",
                ]
            )
    gc.collect()
    process = psutil.Process()
    before = process.memory_info().rss
    peak = before
    stopped = threading.Event()

    def sample():
        nonlocal peak
        while not stopped.wait(0.005):
            peak = max(peak, process.memory_info().rss)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    parsed = None
    try:
        started = time.perf_counter()
        parsed = _parse_csv(fixture, MAX_ROWS, "products")
        parsed_at = time.perf_counter()
        assert len(parsed.rows) == rows
        # Verify repeatable traversal without constructing a second list.
        assert sum(1 for _ in parsed.rows) == rows
        traversed_at = time.perf_counter()
        parsed.close()
        parsed = None
        gc.collect()
        finished = time.perf_counter()
        peak = max(peak, process.memory_info().rss)
    finally:
        stopped.set()
        sampler.join()
        if parsed is not None:
            parsed.close()
    delta = peak - before
    assert delta <= 64 * 1024**2, f"CSV parser retained {delta} bytes for {rows} rows"
    return {
        "rows": rows,
        "columns": 12,
        "file_bytes": fixture.stat().st_size,
        "parse_elapsed_ms": (parsed_at - started) * 1000,
        "traversal_elapsed_ms": (traversed_at - parsed_at) * 1000,
        "total_elapsed_ms_including_close": (finished - started) * 1000,
        "rss_before_bytes": before,
        "rss_peak_bytes": peak,
        "rss_growth_bytes": delta,
        "rss_growth_budget_bytes": 64 * 1024**2,
        "sampling_interval_ms": 5,
    }


CASES = {"im": im_case, "vector": vector_case, "csv": csv_case}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--rows", type=int)
    parser.add_argument("--output", type=Path, default=Path("performance-results/business.json"))
    args = parser.parse_args()
    if args.case:
        if args.rows is None or args.rows < 50:
            parser.error("--case requires --rows >= 50")
        with tempfile.TemporaryDirectory(prefix="xcmax-perf-regression-") as temp:
            directory = Path(temp)
            os.environ.update(
                {
                    "FHD_ENV": "test",
                    "XCAGI_DEBUG": "1",
                    "XCAGI_DATA_DIR": temp,
                    "DATABASE_URL": f"sqlite:///{directory / 'host.sqlite'}",
                }
            )
            print(json.dumps(CASES[args.case](args.rows, directory), ensure_ascii=False))
        return 0
    results = []
    for case, rows in (
        ("im", 100),
        ("im", 1000),
        ("vector", 1000),
        ("vector", 10000),
        ("csv", 10000),
        ("csv", 100000),
    ):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--case",
            case,
            "--rows",
            str(rows),
        ]
        try:
            run = subprocess.run(command, cwd=FHD, capture_output=True, text=True, timeout=180)
            result = (
                json.loads(run.stdout) if run.returncode == 0 else {"error": run.stderr[-2000:]}
            )
            results.append(
                {"case": case, "size": rows, "passed": run.returncode == 0, "result": result}
            )
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            results.append({"case": case, "size": rows, "passed": False, "error": str(error)})
    payload = {
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=FHD, text=True
        ).strip(),
        "scope": "isolated synthetic business regressions; not production capacity",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {name: version(name) for name in ("SQLAlchemy", "psutil", "openpyxl")},
        },
        "cases": results,
        "passed": all(item["passed"] for item in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": payload["passed"], "output": str(args.output)}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
