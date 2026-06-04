"""用户客服员工 · 按企业客户的商机进度（pipeline）。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PIPELINE_STAGES: list[dict[str, str]] = [
    {"id": "idle", "label": "未接触"},
    {"id": "connected", "label": "已建联"},
    {"id": "intake", "label": "需求采集"},
    {"id": "intake_done", "label": "需求已提交"},
    {"id": "quoted", "label": "已报价"},
    {"id": "negotiating", "label": "议价中"},
    {"id": "contract_pending", "label": "待签约"},
    {"id": "signed", "label": "已签约"},
    {"id": "delivering", "label": "交付中"},
    {"id": "delivered", "label": "已交付"},
]

_STAGE_ORDER = [s["id"] for s in PIPELINE_STAGES]

# 进入以下阶段前须 CRM 商机已入库；quoted+ 还须报价单（有 intake 时）
_STAGES_REQUIRE_CRM: frozenset[str] = frozenset(
    {
        "intake_done",
        "quoted",
        "negotiating",
        "contract_pending",
        "signed",
        "delivering",
        "delivered",
    }
)
_STAGES_REQUIRE_QUOTE: frozenset[str] = frozenset(
    {
        "quoted",
        "negotiating",
        "contract_pending",
        "signed",
        "delivering",
        "delivered",
    }
)


class PipelineCrmGateError(ValueError):
    """阶段推进被 CRM/ERP 门禁拦截。"""

    def __init__(self, message: str, *, market_user_id: int = 0):
        super().__init__(message)
        self.market_user_id = market_user_id


def _stage_requires_crm(stage: str) -> bool:
    return stage in _STAGES_REQUIRE_CRM


def _stage_requires_quote(stage: str) -> bool:
    return stage in _STAGES_REQUIRE_QUOTE


def ensure_crm_erp_prerequisites(doc: dict[str, Any], target_stage: str) -> dict[str, Any]:
    """在写入 intake_done+ 前补齐 ERP 关联并强制 CRM 同步。"""
    if not _stage_requires_crm(target_stage):
        return doc
    uid = int(doc.get("market_user_id") or 0)
    if uid <= 0:
        raise PipelineCrmGateError("缺少 market_user_id", market_user_id=uid)

    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    if not doc.get("erp_customer_id") and (
        form.get("company") or form.get("name") or form.get("phone")
    ):
        from app.services.user_cs_intake_finalize import resolve_erp_customer_for_intake

        match = resolve_erp_customer_for_intake(
            company=str(form.get("company") or ""),
            phone=str(form.get("phone") or ""),
            name=str(form.get("name") or ""),
        )
        if match:
            doc = dict(doc)
            doc["erp_customer_id"] = match.get("erp_customer_id")
            doc["erp_customer_name"] = match.get("erp_customer_name")
            doc["erp_match_score"] = match.get("erp_match_score")
            doc["erp_match_source"] = match.get("erp_match_source")

    from app.services.user_cs_crm_store import sync_crm_from_pipeline_doc

    doc = dict(doc)
    doc["stage"] = target_stage
    doc = sync_crm_from_pipeline_doc(doc, raise_on_failure=True)

    if _stage_requires_quote(target_stage) and bool(doc.get("intake_submitted_at") or form):
        if not doc.get("crm_quote_id"):
            raise PipelineCrmGateError(
                f"阶段「{target_stage}」需要报价单已生成，请先同步 CRM",
                market_user_id=uid,
            )
    return doc


def _pipeline_roots() -> list[Path]:
    from app.utils.path_utils import get_base_dir, get_data_dir

    roots: list[Path] = []
    for base in (
        Path(get_data_dir()) / "customer_service" / "pipeline",
        Path(get_base_dir()) / "data" / "customer_service" / "pipeline",
    ):
        if base not in roots:
            roots.append(base)
    return roots


def _pipeline_root() -> Path:
    """默认写入目录（优先应用 data-dir，其次仓库 FHD/data）。"""
    root = _pipeline_roots()[0]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pipeline_path(market_user_id: int) -> Path:
    uid = int(market_user_id)
    for root in _pipeline_roots():
        path = root / f"{uid}.json"
        if path.is_file():
            return path
    return _pipeline_root() / f"{uid}.json"


def iter_pipeline_market_user_ids() -> list[int]:
    """已存在 pipeline 文件的企业用户 ID 列表。"""
    out: list[int] = []
    seen: set[int] = set()
    for root in _pipeline_roots():
        root.mkdir(parents=True, exist_ok=True)
        for path in root.glob("*.json"):
            try:
                uid = int(path.stem)
            except ValueError:
                continue
            if uid in seen:
                continue
            seen.add(uid)
            out.append(uid)
    return sorted(out)


def pipeline_display_name(doc: dict[str, Any], *, login_username: str = "") -> str:
    """表单联网检索公司名 > ERP 全称 > pipeline 用户名（非登录账号时）。"""
    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = str(form.get("company") or "").strip()
    if company:
        return company
    erp = str(doc.get("erp_customer_name") or "").strip()
    if erp:
        return erp
    login = (login_username or "").strip()
    pipe_user = str(doc.get("username") or "").strip()
    if pipe_user and (not login or pipe_user.casefold() != login.casefold()):
        return pipe_user
    return pipe_user or login


def list_pipeline_client_summaries() -> list[dict[str, Any]]:
    """内部客服客户列表：已有 pipeline 档案的市场用户摘要。"""
    rows: list[dict[str, Any]] = []
    for uid in iter_pipeline_market_user_ids():
        doc = load_pipeline(uid)
        login = str(doc.get("username") or "").strip() or f"用户{uid}"
        rows.append(
            {
                "market_user_id": uid,
                "username": login,
                "display_name": pipeline_display_name(doc, login_username=login),
                "stage": str(doc.get("stage") or "idle"),
            }
        )
    return rows


def build_pipeline_funnel_summary(*, max_clients_per_stage: int = 8) -> dict[str, Any]:
    """按 PIPELINE_STAGES 聚合商机漏斗（内部客服 / 财务统计摘要）。"""
    cap = max(1, min(int(max_clients_per_stage), 50))
    by_stage: dict[str, list[dict[str, Any]]] = {s["id"]: [] for s in PIPELINE_STAGES}
    counts: dict[str, int] = {s["id"]: 0 for s in PIPELINE_STAGES}
    for uid in iter_pipeline_market_user_ids():
        doc = load_pipeline(uid)
        stage = str(doc.get("stage") or "idle")
        if stage not in counts:
            stage = "idle"
        counts[stage] = counts.get(stage, 0) + 1
        login = str(doc.get("username") or "").strip() or f"用户{uid}"
        row = {
            "market_user_id": uid,
            "username": login,
            "display_name": pipeline_display_name(doc, login_username=login),
            "stage": stage,
            "crm_opportunity_id": doc.get("crm_opportunity_id"),
            "erp_customer_name": str(doc.get("erp_customer_name") or "")[:128],
        }
        bucket = by_stage.setdefault(stage, [])
        if len(bucket) < cap:
            bucket.append(row)
    stages_out = [
        {
            "id": s["id"],
            "label": s["label"],
            "count": counts.get(s["id"], 0),
            "clients": by_stage.get(s["id"], []),
        }
        for s in PIPELINE_STAGES
    ]
    total = sum(counts.values())
    return {"stages": stages_out, "total_clients": total, "stage_counts": counts}


def default_pipeline(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "market_user_id": int(market_user_id),
        "username": username,
        "stage": "idle",
        "updated_at": now,
        "timeline": [{"stage": "idle", "at": now, "source": "init"}],
        "last_sync_at": None,
        "last_message_preview": "",
        "connected_welcome_sent": False,
        "connected_welcome_sent_at": None,
    }


def load_pipeline(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    path = _pipeline_path(market_user_id)
    if not path.is_file():
        return default_pipeline(market_user_id, username=username)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_pipeline(market_user_id, username=username)
        data.setdefault("market_user_id", int(market_user_id))
        data.setdefault("stage", "idle")
        data.setdefault("timeline", [])
        if username:
            data["username"] = username
        return data
    except (OSError, json.JSONDecodeError):
        return default_pipeline(market_user_id, username=username)


def set_pipeline_stage(
    market_user_id: int,
    stage: str,
    *,
    username: str = "",
    source: str = "manual",
    note: str = "",
) -> dict[str, Any]:
    """手动设置商机阶段（可前进或回退），并写入 timeline。"""
    stage_id = (stage or "").strip()
    if stage_id not in _STAGE_ORDER:
        raise ValueError(f"无效阶段: {stage_id}")
    doc = load_pipeline(int(market_user_id), username=username)
    old_stage = str(doc.get("stage") or "idle")
    if stage_id == old_stage:
        return doc
    if _stage_requires_crm(stage_id):
        doc = ensure_crm_erp_prerequisites(doc, stage_id)
    now = datetime.now(timezone.utc).isoformat()
    doc["stage"] = stage_id
    entry: dict[str, Any] = {
        "stage": stage_id,
        "at": now,
        "source": source or "manual",
        "from": old_stage,
    }
    if note:
        entry["note"] = str(note)[:200]
    timeline = list(doc.get("timeline") or [])
    timeline.append(entry)
    doc["timeline"] = timeline[-30:]
    return save_pipeline(doc, strict_crm=_stage_requires_crm(stage_id))


def auto_advance_pipeline_if_ready(
    market_user_id: int,
    *,
    username: str = "",
    has_binding: bool | None = None,
    has_messages: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """清单条件满足时自动进入下一阶段（如已建联 → 需求采集）。"""
    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    stage = str(doc.get("stage") or "idle")

    if has_binding is None:
        from app.services.wechat_group_customer_bridge import get_bindings_for_user

        has_binding = bool(get_bindings_for_user(uid))
    if has_messages is None:
        from app.services.wechat_group_customer_bridge import build_starred_group_feed

        has_messages = bool(build_starred_group_feed(limit=1, market_user_id=uid))

    next_stage: str | None = None
    if stage == "idle" and has_binding:
        next_stage = "connected"
    elif (
        stage == "connected"
        and has_binding
        and bool(doc.get("connected_welcome_sent"))
        and has_messages
    ):
        next_stage = "intake"
    elif stage == "intake" and bool(doc.get("intake_submitted_at")):
        next_stage = "intake_done"

    if not next_stage or next_stage == stage:
        return doc, False

    doc = set_pipeline_stage(
        uid,
        next_stage,
        username=username,
        source="auto_checklist",
        note="checklist_complete",
    )
    return doc, True


def _write_pipeline_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    """先写临时文件再 replace，避免进程崩溃时留下半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def save_pipeline(doc: dict[str, Any], *, strict_crm: bool | None = None) -> dict[str, Any]:
    uid = int(doc.get("market_user_id") or 0)
    if uid <= 0:
        raise ValueError("market_user_id required")
    doc = dict(doc)
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _pipeline_path(uid)
    stage = str(doc.get("stage") or "idle")
    if strict_crm is None:
        strict_crm = _stage_requires_crm(stage)
    try:
        from app.services.user_cs_crm_store import CrmSyncError, sync_crm_from_pipeline_doc

        doc = sync_crm_from_pipeline_doc(doc, raise_on_failure=bool(strict_crm))
    except CrmSyncError:
        raise
    except Exception:
        logger.exception("crm sync on save_pipeline failed uid=%s", uid)
        if strict_crm:
            raise
    if strict_crm and not doc.get("crm_opportunity_id"):
        raise PipelineCrmGateError(
            "CRM 商机未入库，已取消保存",
            market_user_id=uid,
        )
    _write_pipeline_json_atomic(path, doc)
    try:
        from app.services.customer_service_repository import write_pipeline_sqlite_snapshot

        write_pipeline_sqlite_snapshot(doc)
    except Exception:
        logger.debug("pipeline sqlite dual-write skipped", exc_info=True)
    try:
        from app.services.user_cs_delivery import on_pipeline_saved

        doc = on_pipeline_saved(doc)
        _write_pipeline_json_atomic(path, doc)
    except Exception:
        logger.exception("delivery hook on save_pipeline failed uid=%s", uid)
    try:
        from app.services.operations_line_bridge import on_pipeline_saved as ops_on_saved

        ops_on_saved(doc)
    except Exception:
        logger.debug("operations_line_bridge on save skipped", exc_info=True)
    return doc


def _stage_rank(stage: str) -> int:
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return 0


def _advance_stage(current: str, new: str) -> str:
    if _stage_rank(new) > _stage_rank(current):
        return new
    return current


def infer_stage_from_messages(
    messages: list[str],
    *,
    current_stage: str = "idle",
    has_binding: bool = False,
    intake_sent: bool = False,
) -> tuple[str, list[str]]:
    """规则推断阶段；返回 (stage, matched_hints)。"""
    blob = " ".join(messages).lower()
    hints: list[str] = []
    stage = current_stage or "idle"

    if has_binding:
        stage = _advance_stage(stage, "connected")
    if not blob.strip():
        if intake_sent:
            stage = _advance_stage(stage, "intake")
        return stage, hints

    rules: list[tuple[str, str, str]] = [
        (r"填了|已填|提交|表单|需求表", "intake_done", "表单/需求提交"),
        (r"报价|多少钱|价格|方案", "quoted", "报价相关"),
        (r"太贵|便宜|折扣|优惠|还价|议价", "negotiating", "议价"),
        (r"合同|签约|签署|盖章", "contract_pending", "合同"),
        (r"已签|签完|签好了", "signed", "已签约"),
        (r"交付完成|已验收|验收通过|已上线", "delivered", "交付完成"),
        (r"开发中|制作中|进度|联调|测试中", "delivering", "交付进行中"),
        (r"交付|验收|上线|部署完成", "delivering", "交付"),
        (r"需求|想要|需要|痛点|能不能", "intake", "需求沟通"),
    ]
    for pattern, target, hint in rules:
        if re.search(pattern, blob, re.I):
            hints.append(hint)
            stage = _advance_stage(stage, target)

    if intake_sent and _stage_rank(stage) < _stage_rank("intake"):
        stage = "intake"

    return stage, hints


def analyze_customer_pipeline(
    market_user_id: int,
    *,
    username: str = "",
    message_texts: list[str] | None = None,
    has_binding: bool = False,
    intake_sent: bool = False,
) -> dict[str, Any]:
    doc = load_pipeline(market_user_id, username=username)
    texts = list(message_texts or [])
    if doc.get("last_message_preview"):
        texts.append(str(doc["last_message_preview"]))
    new_stage, hints = infer_stage_from_messages(
        texts,
        current_stage=str(doc.get("stage") or "idle"),
        has_binding=has_binding,
        intake_sent=intake_sent or bool(doc.get("intake_sent")),
    )
    old_stage = str(doc.get("stage") or "idle")
    now = datetime.now(timezone.utc).isoformat()
    doc["last_sync_at"] = now
    if new_stage != old_stage:
        doc["stage"] = new_stage
        timeline = list(doc.get("timeline") or [])
        timeline.append({"stage": new_stage, "at": now, "source": "analyze", "hints": hints})
        doc["timeline"] = timeline[-30:]
    doc["analyze_hints"] = hints
    return save_pipeline(doc)


def repair_pipeline_crm(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    """运维：补齐 ERP 关联并强制 CRM 同步写回 pipeline。"""
    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    stage = str(doc.get("stage") or "idle")
    if _stage_requires_crm(stage):
        doc = ensure_crm_erp_prerequisites(doc, stage)
    elif doc.get("intake_form") or doc.get("intake_submitted_at"):
        doc = ensure_crm_erp_prerequisites(doc, "intake_done")
    from app.services.user_cs_crm_store import sync_crm_from_pipeline_doc

    doc = sync_crm_from_pipeline_doc(doc, raise_on_failure=True)
    final_stage = str(doc.get("stage") or "idle")
    return save_pipeline(doc, strict_crm=_stage_requires_crm(final_stage))


def repair_all_pipelines(*, username: str = "") -> dict[str, Any]:
    """批量 repair；单条失败不中断。"""
    results: list[dict[str, Any]] = []
    for uid in iter_pipeline_market_user_ids():
        try:
            doc = repair_pipeline_crm(uid, username=username)
            results.append(
                {
                    "market_user_id": uid,
                    "ok": True,
                    "crm_opportunity_id": doc.get("crm_opportunity_id"),
                    "crm_quote_id": doc.get("crm_quote_id"),
                    "erp_customer_name": doc.get("erp_customer_name"),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "market_user_id": uid,
                    "ok": False,
                    "error": str(exc)[:500],
                }
            )
    ok_n = sum(1 for r in results if r.get("ok"))
    return {
        "total": len(results),
        "ok": ok_n,
        "failed": len(results) - ok_n,
        "results": results,
    }
