"""微信群被动轮询 / LLM 就绪探测。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.user_cs_pipeline import _pipeline_roots

logger = logging.getLogger(__name__)

_THINKING_MARKERS = re.compile(
    r"(^|\n)\s*(思考|Thought|Let me think|我需要先|分析如下)",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_root() -> Path:
    root = _pipeline_roots()[0].parent / "user_cs_passive_poll"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _config_file(market_user_id: int) -> Path:
    return _config_root() / f"{int(market_user_id)}.json"


def _load_config(market_user_id: int) -> dict[str, Any]:
    path = _config_file(market_user_id)
    if not path.is_file():
        return {"market_user_id": int(market_user_id), "poll_enabled": False, "poll_interval_sec": 60}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"market_user_id": int(market_user_id), "poll_enabled": False, "poll_interval_sec": 60}
    return raw if isinstance(raw, dict) else {}


def _save_config(data: dict[str, Any]) -> dict[str, Any]:
    uid = int(data.get("market_user_id") or 0)
    path = _config_file(uid)
    data = dict(data)
    data["updated_at"] = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _llm_configured() -> tuple[bool, str]:
    keys = (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "SILICONFLOW_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
    )
    for key in keys:
        if (os.environ.get(key) or "").strip():
            return True, f"已配置 {key}（与智能对话同源）"
    return False, "请配置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 等 LLM 密钥"


def probe_passive_llm_ready(*, session_id: str = "", request: Any = None) -> dict[str, Any]:
    _ = session_id
    _ = request
    ready, message = _llm_configured()
    return {"ready": ready, "message": message}


def assert_safe_outbound_group_reply(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    if _THINKING_MARKERS.search(text):
        return None
    if len(text) > 4000:
        return text[:4000]
    return text


def get_passive_poll_config(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    _ = username
    cfg = _load_config(int(market_user_id))
    cfg.setdefault("poll_enabled", False)
    cfg.setdefault("poll_interval_sec", 60)
    return cfg


def save_passive_poll_config(
    market_user_id: int,
    *,
    username: str = "",
    poll_enabled: bool = False,
    poll_interval_sec: int = 60,
) -> dict[str, Any]:
    _ = username
    cfg = _load_config(int(market_user_id))
    cfg.update(
        {
            "market_user_id": int(market_user_id),
            "poll_enabled": bool(poll_enabled),
            "poll_interval_sec": max(10, min(600, int(poll_interval_sec))),
        }
    )
    return _save_config(cfg)


def reset_passive_watch(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    _ = username
    cfg = _load_config(int(market_user_id))
    cfg["watch_reset_at"] = _now_iso()
    cfg["last_seen_message_id"] = ""
    return _save_config(cfg)


def passive_poll_once(
    *,
    market_user_id: int,
    username: str = "",
    dry_run: bool = True,
    auto_reply: bool = True,
    max_replies: int = 0,
    use_llm: bool = True,
    skip_sync: bool = False,
    refresh_count_new: int | None = None,
    refresh_latest_label: str = "",
    catch_up_latest: bool = False,
    session_id: str = "",
    request: Any = None,
) -> dict[str, Any]:
    from app.services.wechat_group_customer_bridge import build_starred_group_feed, sync_group_messages

    _ = username
    _ = refresh_count_new
    _ = refresh_latest_label
    _ = catch_up_latest
    _ = session_id
    _ = request
    uid = int(market_user_id)
    if not skip_sync:
        sync_group_messages(market_user_id=uid)
    feed = build_starred_group_feed(limit=20, market_user_id=uid)
    texts = [str(x.get("content") or x.get("message") or "") for x in feed if x.get("content") or x.get("message")]
    detected = len(texts)
    ready, llm_msg = _llm_configured()
    llm_error = "" if ready or not use_llm else llm_msg
    replies: list[dict[str, Any]] = []
    if auto_reply and not dry_run and detected > 0 and texts:
        reply_text = "您好，已收到消息，客服稍后回复。"
        reply_source = "template"
        if use_llm and ready:
            reply_source = "llm_stub"
        replies.append(
            {
                "reply": reply_text,
                "reply_source": reply_source,
                "llm_error": llm_error,
            }
        )
    cfg = _load_config(uid)
    cfg["last_poll_at"] = _now_iso()
    _save_config(cfg)
    return {
        "success": True,
        "dry_run": dry_run,
        "detected_count": detected,
        "replies": replies[: max(0, int(max_replies))] if max_replies else replies[:1],
        "llm_ready": ready,
        "message_count": detected,
    }
