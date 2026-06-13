"""内部客服商机 pipeline 档案（桌面 SQLite 栈 · JSON 侧存储）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class PipelineCrmGateError(Exception):
    """阶段推进被 CRM 门禁拦截。"""


PIPELINE_STAGES: list[dict[str, str]] = [
    {"id": "idle", "label": "未接触"},
    {"id": "connected", "label": "已建联"},
    {"id": "intake", "label": "需求采集"},
    {"id": "intake_done", "label": "已提交"},
    {"id": "quoted", "label": "已报价"},
    {"id": "negotiating", "label": "议价"},
    {"id": "contract_pending", "label": "待签"},
    {"id": "signed", "label": "已签"},
    {"id": "delivering", "label": "交付中"},
    {"id": "delivered", "label": "已交付"},
]

_STAGE_ORDER = [s["id"] for s in PIPELINE_STAGES]
_STAGE_LABELS = {s["id"]: s["label"] for s in PIPELINE_STAGES}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stage_rank(stage: str | None) -> int:
    st = str(stage or "idle")
    try:
        return _STAGE_ORDER.index(st)
    except ValueError:
        return 0


def _resolve_data_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    for env_key in ("XCAGI_DATA_DIR", "XCAGI_DESKTOP_DATA_DIR"):
        raw = (os.environ.get(env_key) or "").strip()
        if raw:
            base = Path(raw).expanduser().resolve()
            add(base / "data" / "user_cs_pipelines")
            add(base / "user_cs_pipelines")

    try:
        from app.desktop_runtime.paths import get_desktop_data_dir

        base = get_desktop_data_dir()
        add(base / "data" / "user_cs_pipelines")
        add(base / "user_cs_pipelines")
    except RECOVERABLE_ERRORS:
        pass

    if not roots:
        add(Path.cwd() / "data" / "user_cs_pipelines")
    return roots


def _pipeline_roots() -> list[Path]:
    roots = _resolve_data_roots()
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    return roots


def _pipeline_file(market_user_id: int) -> Path:
    uid = int(market_user_id)
    if uid <= 0:
        raise ValueError("market_user_id 无效")
    primary = _pipeline_roots()[0]
    return primary / f"{uid}.json"


def _default_pipeline(market_user_id: int, username: str = "") -> dict[str, Any]:
    return {
        "market_user_id": int(market_user_id),
        "username": str(username or "").strip(),
        "stage": "idle",
        "timeline": [],
        "intake_sent": False,
        "intake_form_notice_sent": False,
        "connected_welcome_sent": False,
        "last_message_preview": "",
        "intake_submitted_at": "",
        "landing_contact_id": 0,
        "intake_form": None,
        "erp_customer_id": 0,
        "erp_customer_name": "",
        "crm_opportunity_id": 0,
        "crm_quote_id": 0,
        "crm_funnel_synced_at": "",
        "crm_db_synced_at": "",
        "crm_invoice_id": 0,
        "updated_at": _now_iso(),
    }


def _read_pipeline_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("invalid pipeline json: %s", path)
        return None
    return raw if isinstance(raw, dict) else None


def _write_pipeline_file(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    doc["updated_at"] = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return doc


def load_pipeline(market_user_id: int, username: str = "") -> dict[str, Any]:
    uid = int(market_user_id)
    path = _pipeline_file(uid)
    doc = _read_pipeline_file(path)
    if doc is None:
        doc = _default_pipeline(uid, username=username)
        _write_pipeline_file(path, doc)
        return doc
    doc.setdefault("market_user_id", uid)
    if username and not doc.get("username"):
        doc["username"] = str(username).strip()
    doc.setdefault("stage", "idle")
    doc.setdefault("timeline", [])
    return doc


def save_pipeline(doc: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    _ = kwargs  # strict_crm 等历史参数兼容
    uid = int(doc.get("market_user_id") or 0)
    if uid <= 0:
        raise ValueError("pipeline 缺少 market_user_id")
    path = _pipeline_file(uid)
    return _write_pipeline_file(path, doc)


def _append_timeline(doc: dict[str, Any], stage: str, source: str, note: str = "") -> None:
    entry = {"stage": stage, "at": _now_iso(), "source": source}
    if note.strip():
        entry["note"] = note.strip()
    tl = list(doc.get("timeline") or [])
    tl.append(entry)
    doc["timeline"] = tl[-30:]


def set_pipeline_stage(
    market_user_id: int,
    stage: str,
    *,
    username: str = "",
    source: str = "manual",
    note: str = "",
) -> dict[str, Any]:
    st = str(stage or "").strip()
    if st not in _STAGE_ORDER:
        raise ValueError(f"未知阶段: {st}")
    doc = load_pipeline(market_user_id, username=username)
    if doc.get("stage") != st:
        doc["stage"] = st
        _append_timeline(doc, st, source, note=note)
    return save_pipeline(doc)


def _display_name_from_doc(doc: dict[str, Any], username: str = "") -> str:
    intake = doc.get("intake_form")
    if isinstance(intake, dict):
        company = str(intake.get("company") or "").strip()
        if company:
            return company
        name = str(intake.get("name") or "").strip()
        if name:
            return name
    erp = str(doc.get("erp_customer_name") or "").strip()
    if erp:
        return erp
    login = str(doc.get("username") or username or "").strip()
    return login


def _iter_pipeline_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for root in _pipeline_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            doc = _read_pipeline_file(path)
            if not doc:
                continue
            uid = int(doc.get("market_user_id") or 0)
            if uid <= 0:
                try:
                    uid = int(path.stem)
                except ValueError:
                    continue
                doc["market_user_id"] = uid
            if uid in seen:
                continue
            seen.add(uid)
            docs.append(doc)
    return docs


def list_pipeline_client_summaries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in _iter_pipeline_docs():
        uid = int(doc.get("market_user_id") or 0)
        if uid <= 0:
            continue
        stage = str(doc.get("stage") or "idle")
        rows.append(
            {
                "market_user_id": uid,
                "username": str(doc.get("username") or ""),
                "stage": stage,
                "stage_label": _STAGE_LABELS.get(stage, stage),
                "display_name": _display_name_from_doc(doc),
                "intake_sent": bool(doc.get("intake_sent")),
                "last_message_preview": str(doc.get("last_message_preview") or "")[:500],
                "updated_at": str(doc.get("updated_at") or ""),
            }
        )
    rows.sort(key=lambda r: (r.get("username") or "", r["market_user_id"]))
    return rows


def build_pipeline_funnel_summary(*, max_clients_per_stage: int = 8) -> dict[str, Any]:
    counts = {s["id"]: 0 for s in PIPELINE_STAGES}
    clients_by_stage: dict[str, list[dict[str, Any]]] = {s["id"]: [] for s in PIPELINE_STAGES}
    for row in list_pipeline_client_summaries():
        st = str(row.get("stage") or "idle")
        if st not in counts:
            st = "idle"
        counts[st] += 1
        bucket = clients_by_stage[st]
        if len(bucket) < max(1, int(max_clients_per_stage)):
            bucket.append(row)
    stages = [
        {
            "id": s["id"],
            "label": s["label"],
            "count": counts.get(s["id"], 0),
            "clients": clients_by_stage.get(s["id"], []),
        }
        for s in PIPELINE_STAGES
    ]
    return {
        "stages": stages,
        "total_clients": sum(counts.values()),
        "counts": counts,
    }


def auto_advance_pipeline_if_ready(
    market_user_id: int,
    *,
    username: str = "",
) -> tuple[dict[str, Any], bool]:
    doc = load_pipeline(market_user_id, username=username)
    before = str(doc.get("stage") or "idle")
    advanced = False

    if doc.get("intake_submitted_at") and _stage_rank(doc.get("stage")) < _stage_rank(
        "intake_done"
    ):
        doc = set_pipeline_stage(
            market_user_id,
            "intake_done",
            username=username,
            source="auto",
            note="表单已提交",
        )
        advanced = True
    elif doc.get("intake_sent") and _stage_rank(doc.get("stage")) < _stage_rank("intake"):
        doc = set_pipeline_stage(
            market_user_id,
            "intake",
            username=username,
            source="auto",
            note="已发送采集话术",
        )
        advanced = True
    elif doc.get("connected_welcome_sent") and _stage_rank(doc.get("stage")) < _stage_rank(
        "connected"
    ):
        doc = set_pipeline_stage(
            market_user_id,
            "connected",
            username=username,
            source="auto",
            note="建联欢迎语已发送",
        )
        advanced = True

    after = str(doc.get("stage") or "idle")
    return doc, advanced or before != after


def analyze_customer_pipeline(
    market_user_id: int,
    *,
    username: str = "",
    message_texts: list[str] | None = None,
    has_binding: bool = False,
    intake_sent: bool = False,
) -> dict[str, Any]:
    doc = load_pipeline(market_user_id, username=username)
    texts = [str(t or "").strip() for t in (message_texts or []) if str(t or "").strip()]
    if texts:
        doc["last_message_preview"] = texts[0][:500]
    if intake_sent:
        doc["intake_sent"] = True
    if has_binding and _stage_rank(doc.get("stage")) <= _stage_rank("idle"):
        doc["stage"] = "connected"
        _append_timeline(doc, "connected", "analyze", note="检测到群绑定")
    elif intake_sent and _stage_rank(doc.get("stage")) < _stage_rank("intake"):
        doc["stage"] = "intake"
        _append_timeline(doc, "intake", "analyze", note="已标记采集")
    return save_pipeline(doc)


def repair_pipeline_crm(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    doc = load_pipeline(market_user_id, username=username)
    doc["crm_db_synced_at"] = _now_iso()
    return save_pipeline(doc)


def repair_all_pipelines() -> dict[str, Any]:
    repaired = 0
    for doc in _iter_pipeline_docs():
        uid = int(doc.get("market_user_id") or 0)
        if uid <= 0:
            continue
        repair_pipeline_crm(uid, username=str(doc.get("username") or ""))
        repaired += 1
    return {"repaired": repaired}


__all__ = [
    "PIPELINE_STAGES",
    "PipelineCrmGateError",
    "_STAGE_ORDER",
    "_pipeline_roots",
    "analyze_customer_pipeline",
    "auto_advance_pipeline_if_ready",
    "build_pipeline_funnel_summary",
    "list_pipeline_client_summaries",
    "load_pipeline",
    "repair_all_pipelines",
    "repair_pipeline_crm",
    "save_pipeline",
    "set_pipeline_stage",
]
