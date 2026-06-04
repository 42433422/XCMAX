"""客服域持久化门面：Pipeline JSON + CRM sqlite 统一入口。"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.services.user_cs_crm_store import (
    CrmSyncError,
    ensure_crm_schema,
    get_opportunity_by_market_user,
    sync_crm_from_pipeline_doc,
)
from app.services.user_cs_pipeline import (
    PipelineCrmGateError,
    _pipeline_path,
    _pipeline_roots,
    default_pipeline,
)
from app.services.user_cs_pipeline import (
    load_pipeline as _load_pipeline_impl,
)
from app.services.user_cs_pipeline import (
    save_pipeline as _save_pipeline_impl,
)
from app.services.user_cs_pipeline import (
    set_pipeline_stage as _set_pipeline_stage_impl,
)


def load_pipeline(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    return _load_pipeline_impl(market_user_id, username=username)


def save_pipeline(doc: dict[str, Any], *, strict_crm: bool | None = None) -> dict[str, Any]:
    return _save_pipeline_impl(doc, strict_crm=strict_crm)


def set_pipeline_stage(
    market_user_id: int,
    stage: str,
    *,
    username: str = "",
    source: str = "manual",
    note: str = "",
) -> dict[str, Any]:
    return _set_pipeline_stage_impl(
        market_user_id,
        stage,
        username=username,
        source=source,
        note=note,
    )


def write_pipeline_sqlite_snapshot(doc: dict[str, Any]) -> None:
    """可选双写：Pipeline JSON 同步快照至 crm.sqlite3（Phase 9 迁库前置）。"""
    import json
    import os

    if str(os.environ.get("CS_PIPELINE_SQLITE_DUAL_WRITE", "1")).strip().lower() in (
        "0",
        "false",
        "off",
        "no",
    ):
        return
    uid = int(doc.get("market_user_id") or 0)
    if uid <= 0:
        return
    ensure_crm_schema()
    payload = json.dumps(doc, ensure_ascii=False)
    stamp = datetime.now(timezone.utc).isoformat()
    with crm_connection() as conn:
        conn.execute(
            """
            INSERT INTO cs_pipeline_snapshots (market_user_id, doc_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(market_user_id) DO UPDATE SET
              doc_json=excluded.doc_json,
              updated_at=excluded.updated_at
            """,
            (uid, payload, stamp),
        )
        conn.commit()


def write_pipeline_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def crm_connection() -> Iterator[Any]:
    """sqlite3 连接（WAL + 外键）。"""
    import sqlite3

    from app.services.user_cs_crm_store import _crm_db_path

    conn = sqlite3.connect(str(_crm_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
    finally:
        conn.close()


class CustomerServiceRepository:
    """Pipeline 与 CRM 读写门面，供路由与新代码使用。"""

    def load_pipeline(self, market_user_id: int, *, username: str = "") -> dict[str, Any]:
        return load_pipeline(market_user_id, username=username)

    def save_pipeline(
        self, doc: dict[str, Any], *, strict_crm: bool | None = None
    ) -> dict[str, Any]:
        return save_pipeline(doc, strict_crm=strict_crm)

    def set_stage(
        self,
        market_user_id: int,
        stage: str,
        *,
        username: str = "",
        source: str = "manual",
        note: str = "",
    ) -> dict[str, Any]:
        return set_pipeline_stage(
            market_user_id,
            stage,
            username=username,
            source=source,
            note=note,
        )

    def get_opportunity(self, market_user_id: int) -> dict[str, Any] | None:
        ensure_crm_schema()
        return get_opportunity_by_market_user(int(market_user_id))

    def sync_crm_from_pipeline(
        self,
        doc: dict[str, Any],
        *,
        raise_on_failure: bool = False,
    ) -> dict[str, Any]:
        return sync_crm_from_pipeline_doc(doc, raise_on_failure=raise_on_failure)

    def pipeline_file_path(self, market_user_id: int) -> Path:
        return _pipeline_path(int(market_user_id))

    def pipeline_roots(self) -> list[Path]:
        return list(_pipeline_roots())

    def backup_pipeline_doc(self, market_user_id: int) -> Path | None:
        """复制当前 pipeline JSON 到同目录 .bak 文件（运维备份）。"""
        path = self.pipeline_file_path(market_user_id)
        if not path.is_file():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = path.with_suffix(f".{stamp}.bak.json")
        dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return dest


_default_repo: CustomerServiceRepository | None = None


def get_customer_service_repository() -> CustomerServiceRepository:
    global _default_repo
    if _default_repo is None:
        _default_repo = CustomerServiceRepository()
    return _default_repo


__all__ = [
    "CrmSyncError",
    "CustomerServiceRepository",
    "PipelineCrmGateError",
    "crm_connection",
    "default_pipeline",
    "get_customer_service_repository",
    "load_pipeline",
    "save_pipeline",
    "set_pipeline_stage",
    "write_pipeline_json_atomic",
]
