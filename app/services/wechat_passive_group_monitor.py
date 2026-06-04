"""微信群被动监听：快照读库 → 发现他人新消息 → LLM/确定性回复（默认不发模板兜底）→ Mac UI 发送。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 同群两次自动回复最短间隔（秒），仅防连点；新消息 ts 晚于上次回复仍会处理
_PASSIVE_REPLY_COOLDOWN_SEC = 5


def _passive_llm_quality_retries() -> int:
    try:
        return max(0, min(3, int(os.environ.get("XCAGI_PASSIVE_LLM_QUALITY_RETRIES", "2"))))
    except ValueError:
        return 2


def _passive_llm_parse_retries() -> int:
    """解析失败（空 reply / 非 JSON）时的额外生成次数；与质量重写分开，避免只堆并行条数。"""
    try:
        return max(0, min(3, int(os.environ.get("XCAGI_PASSIVE_LLM_PARSE_RETRIES", "1"))))
    except ValueError:
        return 1


def _passive_llm_candidate_count() -> int:
    """每轮一次生成多条候选再筛选（默认 2）。设 XCAGI_PASSIVE_LLM_CANDIDATES=1 可关闭。"""
    try:
        return max(1, min(3, int(os.environ.get("XCAGI_PASSIVE_LLM_CANDIDATES", "2"))))
    except ValueError:
        return 2


def _passive_allow_template_fallback() -> bool:
    """默认 fail-closed：LLM/质量失败不发模板套话。设 XCAGI_PASSIVE_ALLOW_TEMPLATE_FALLBACK=1 可回滚。"""
    return os.environ.get("XCAGI_PASSIVE_ALLOW_TEMPLATE_FALLBACK", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_PASSIVE_LLM_MAX_TOKENS = 256
_PASSIVE_LLM_RETRY_MAX_TOKENS = 320


def _passive_recent_context_char_limit() -> int:
    try:
        return max(
            200, min(4000, int(os.environ.get("XCAGI_PASSIVE_RECENT_CONTEXT_CHARS", "2400")))
        )
    except (TypeError, ValueError):
        return 2400


def _passive_llm_temperature() -> float:
    try:
        return max(0.2, min(0.85, float(os.environ.get("XCAGI_PASSIVE_LLM_TEMPERATURE", "0.58"))))
    except (TypeError, ValueError):
        return 0.58


def build_passive_recent_context_from_messages(
    messages: list[dict[str, Any]],
    *,
    group_name: str = "",
    exclude_last_incoming: bool = True,
) -> tuple[str, str]:
    """
    从群聊消息列表构造被动 LLM 近期上下文（支持 1000+ 条，按字符上限取尾部）。
    返回 (recent_context, last_bot_reply)。
    """
    from app.services.wechat_message_display import is_bot_outbound_group_message

    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    pool = msgs[:-1] if exclude_last_incoming and msgs else msgs
    cap = _passive_recent_context_char_limit()
    lines: list[str] = []
    for m in pool:
        body = str(m.get("text") or "").strip().replace("\n", " ")[:120]
        if not body:
            continue
        if is_bot_outbound_group_message(body, group_name=group_name):
            continue
        if is_prompt_echo_reply(body):
            continue
        who = str(
            m.get("sender_display")
            or m.get("sender")
            or ("我" if str(m.get("role") or "").lower() == "self" else "成员")
        )
        lines.append(f"{who}: {body}")

    selected: list[str] = []
    total = 0
    for line in reversed(lines):
        add = len(line) + (1 if selected else 0)
        if total + add > cap and selected:
            break
        selected.append(line)
        total += add
    selected.reverse()

    last_bot_outbound = ""
    for m in reversed(msgs):
        body = str(m.get("text") or "").strip()
        if not body:
            continue
        if str(m.get("role") or "").lower() == "self" or is_bot_outbound_group_message(
            body, group_name=group_name
        ):
            last_bot_outbound = body.replace("\n", " ")[:200]
            break
    return "\n".join(selected), last_bot_outbound


_STAGE_LABELS = {
    "idle": "未接触",
    "connected": "已建联",
    "intake": "需求采集",
    "intake_done": "需求已提交",
    "quoted": "已报价",
    "negotiating": "议价中",
    "contract_pending": "待签约",
    "signed": "已签约",
    "delivering": "交付中",
    "delivered": "已交付",
}


def _msg_key(msg: dict[str, Any]) -> str:
    ts = msg.get("timestamp") or msg.get("create_time") or 0
    text = str(msg.get("text") or "").strip()
    role = str(msg.get("role") or "other")
    return hashlib.sha256(f"{role}|{ts}|{text}".encode()).hexdigest()[:32]


def _stable_msg_key(msg: dict[str, Any]) -> str:
    """按发送者+正文+时间戳去重：同一句重复发送（如再次问「你有什么功能」）仍可回复。"""
    sender = str(msg.get("sender") or "").strip()
    text = re.sub(r"\s+", " ", str(msg.get("text") or msg.get("content") or "").strip())[:240]
    ts = _message_ts(msg)
    return hashlib.sha256(f"{sender}|{text}|{ts:.3f}".encode()).hexdigest()[:32]


def _message_ts(msg: dict[str, Any]) -> float:
    try:
        return float(msg.get("timestamp") or msg.get("create_time") or 0)
    except (TypeError, ValueError):
        return 0.0


def _sorted_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [m for m in messages if isinstance(m, dict)],
        key=_message_ts,
    )


def _pick_single_pending_incoming(
    messages: list[dict[str, Any]],
    *,
    group_name: str,
    cursor: dict[str, Any],
    handled: set[str],
    replied: set[str],
    stable_handled: set[str],
    catch_up_latest: bool = False,
) -> dict[str, Any] | None:
    """
    一问一答：每群每轮最多选 1 条——最新一条待回复的他人消息。
    若最新消息已是己方/机器人话术，则不再追问。
    """
    from app.services.wechat_message_display import (
        is_actionable_incoming_group_message,
        is_bot_outbound_group_message,
    )

    ordered = _sorted_messages(messages)
    if not ordered:
        return None

    last = ordered[-1]
    if str(last.get("role") or "").lower() == "self":
        return None
    if is_bot_outbound_group_message(str(last.get("text") or ""), group_name=group_name):
        return None

    min_ts = max(
        float(cursor.get("last_ts") or 0),
        float(cursor.get("last_bot_reply_ts") or 0),
    )
    # 重新监听时记录的是「消息时间戳」地板，勿用墙钟 time.time()（会与消息 ts 混比导致永不回复）
    armed_msg_ts = float(cursor.get("watch_armed_message_ts") or 0)
    if catch_up_latest:
        floor_ts = min_ts
    elif armed_msg_ts > 0:
        floor_ts = max(min_ts, armed_msg_ts)
    else:
        floor_ts = min_ts

    candidate: dict[str, Any] | None = None
    candidate_ts = 0.0
    for msg in ordered:
        if not is_actionable_incoming_group_message(msg, group_name=group_name):
            continue
        ts = _message_ts(msg)
        mk = _msg_key(msg)
        sk = _stable_msg_key(msg)
        if mk in replied or sk in stable_handled:
            continue
        # 允许与 floor_ts 同秒的消息（微信 ts 常为整秒）；重新监听后须严格晚于 armed
        eligible = ts + 1e-3 > floor_ts or (catch_up_latest and ts + 1e-3 >= floor_ts and ts > 0)
        if not eligible:
            handled.add(mk)
            # 勿写入 stable_handled：否则相同正文（如再次发「你好」）将永远不再回复
            continue
        if ts >= candidate_ts:
            candidate_ts = ts
            candidate = msg

    return candidate


def _load_passive_state(doc: dict[str, Any]) -> dict[str, Any]:
    state = doc.get("passive_state")
    if not isinstance(state, dict):
        state = {
            "enabled": True,
            "poll_enabled": False,
            "poll_interval_sec": 60,
            "cursors": {},
            "handled_keys": [],
            "replied_keys": [],
            "stable_handled_keys": [],
        }
    state.setdefault("enabled", True)
    state.setdefault("poll_enabled", False)
    state.setdefault("poll_interval_sec", 60)
    state.setdefault("cursors", {})
    state.setdefault("handled_keys", [])
    state.setdefault("replied_keys", [])
    state.setdefault("stable_handled_keys", [])
    if not isinstance(state["cursors"], dict):
        state["cursors"] = {}
    if not isinstance(state["handled_keys"], list):
        state["handled_keys"] = []
    if not isinstance(state["replied_keys"], list):
        state["replied_keys"] = []
    if not isinstance(state["stable_handled_keys"], list):
        state["stable_handled_keys"] = []
    try:
        state["poll_interval_sec"] = max(10, min(600, int(state.get("poll_interval_sec") or 60)))
    except (TypeError, ValueError):
        state["poll_interval_sec"] = 60
    return state


def get_passive_poll_config(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline

    doc = load_pipeline(int(market_user_id), username=username)
    state = _load_passive_state(doc)
    return {
        "market_user_id": int(market_user_id),
        "poll_enabled": bool(state.get("poll_enabled")),
        "poll_interval_sec": int(state.get("poll_interval_sec") or 60),
        "last_poll_at": state.get("last_poll_at"),
        "last_poll_message": state.get("last_poll_message"),
    }


def _arm_passive_watch_after_sync(
    market_user_id: int,
    *,
    username: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    开启轮询或重置监听时：先同步本机微信库，再把各群游标拨到当前最新消息时刻，
    并清空 handled，避免历史消息被误回复，同时保证之后的新消息能被识别。
    """
    from app.application import get_wechat_contact_app_service
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline
    from app.services.wechat_group_customer_bridge import (
        get_bindings_for_user,
        sync_group_messages,
    )

    uid = int(market_user_id)
    sync_group_messages(
        market_user_id=uid,
        message_limit=80,
        force_refresh=True,
    )
    doc = load_pipeline(uid, username=username)
    state = state if state is not None else _load_passive_state(doc)
    cursors: dict[str, Any] = dict(state.get("cursors") or {})
    service = get_wechat_contact_app_service()
    for b in get_bindings_for_user(uid):
        cid = int(b["wechat_contact_id"])
        messages = service.get_contact_context(cid) or []
        if not isinstance(messages, list):
            messages = []
        max_ts = max((_message_ts(m) for m in messages), default=0.0)
        prev = cursors.get(str(cid)) or {}
        cursors[str(cid)] = {
            "last_ts": max_ts,
            "last_bot_reply_ts": float(prev.get("last_bot_reply_ts") or 0),
            "bootstrapped": True,
            "cooldown_until": float(prev.get("cooldown_until") or 0),
            "watch_armed_message_ts": max_ts,
        }
    state["cursors"] = cursors
    state["handled_keys"] = []
    state["stable_handled_keys"] = []
    state["last_poll_message"] = (
        "已对齐群聊进度：仅自动回复本次点击之后他人新消息（与微信发送时间对比）"
    )
    doc["passive_state"] = state
    save_pipeline(doc)
    return state


def reset_passive_watch(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    """手动重置被动监听游标（不关闭轮询开关）。"""
    return _arm_passive_watch_after_sync(int(market_user_id), username=username)


def save_passive_poll_config(
    market_user_id: int,
    *,
    username: str = "",
    poll_enabled: bool | None = None,
    poll_interval_sec: int | None = None,
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    doc = load_pipeline(int(market_user_id), username=username)
    state = _load_passive_state(doc)
    was_enabled = bool(state.get("poll_enabled"))
    if poll_enabled is not None:
        state["poll_enabled"] = bool(poll_enabled)
    if poll_interval_sec is not None:
        state["poll_interval_sec"] = max(10, min(600, int(poll_interval_sec)))
    if poll_enabled is not None and bool(poll_enabled) and not was_enabled:
        state = _arm_passive_watch_after_sync(int(market_user_id), username=username, state=state)
        doc["passive_state"] = state
        save_pipeline(doc)
        return get_passive_poll_config(market_user_id, username=username)
    doc["passive_state"] = state
    save_pipeline(doc)
    return get_passive_poll_config(market_user_id, username=username)


def _passive_ui_llm_overlap_enabled() -> bool:
    """Mac 上 LLM 生成与微信打开输入框并行（可用 XCAGI_PASSIVE_UI_LLM_OVERLAP=0 关闭）。"""
    if sys.platform != "darwin":
        return False
    return os.environ.get("XCAGI_PASSIVE_UI_LLM_OVERLAP", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def send_passive_reply_overlapped(
    group_name: str,
    *,
    build_reply: Callable[[], tuple[str, str, str]],
) -> tuple[dict[str, Any], str, str, str]:
    """
    LLM 生成回复的同时在 Mac 微信里打开群聊并聚焦输入框；
    生成完成后仅粘贴发送，缩短总耗时。
    """
    import concurrent.futures

    from app.desktop_automation.service import get_desktop_automation_service

    desktop = get_desktop_automation_service()
    prep: dict[str, Any] = {"success": False, "prepared": False}
    reply_text, reply_source, llm_error = "", "template", ""

    def run_prep() -> None:
        nonlocal prep
        prep = desktop.prepare_wechat_chat(group_name)

    def run_llm() -> None:
        nonlocal reply_text, reply_source, llm_error
        reply_text, reply_source, llm_error = build_reply()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fut_prep = pool.submit(run_prep)
        fut_llm = pool.submit(run_llm)
        try:
            fut_prep.result(timeout=45)
        except Exception as exc:
            prep = {"success": False, "prepared": False, "error": str(exc)[:200]}
        try:
            fut_llm.result(timeout=95)
        except Exception as exc:
            llm_error = str(exc)[:300]
            logger.warning("并行 LLM 生成失败，同步重试: %s", llm_error)
            try:
                reply_text, reply_source, llm_error = build_reply()
            except Exception as exc2:
                llm_error = str(exc2)[:300]

    if not (reply_text or "").strip():
        llm_error = llm_error or "LLM 未返回可发送内容"
        reply_text, reply_source, llm_error = build_reply()

    safe_reply = assert_safe_outbound_group_reply(reply_text)
    if not safe_reply and (reply_text or "").strip():
        logger.warning(
            "并行发送前拦截不安全回复: %s",
            (reply_text or "")[:120],
        )
        return (
            {
                "success": False,
                "message_sent": False,
                "error": "回复未通过安全校验，已拦截",
            },
            "",
            reply_source,
            llm_error or "已拦截不安全回复",
        )
    if safe_reply:
        reply_text = safe_reply

    send_result: dict[str, Any]
    if prep.get("prepared") and prep.get("success") and (reply_text or "").strip():
        send_result = desktop.complete_wechat_prepared_send(reply_text)
        if not (send_result.get("message_sent") or send_result.get("success")):
            logger.warning(
                "预热粘贴发送失败，回退完整流程: %s",
                send_result.get("error") or send_result.get("message"),
            )
            desktop.clear_wechat_prepare()
            send_result = desktop.send_wechat_message(group_name, reply_text)
            send_result["send_mode"] = "overlap_fallback"
        else:
            send_result["send_mode"] = send_result.get("send_mode") or "overlap"
    else:
        desktop.clear_wechat_prepare()
        if not prep.get("prepared"):
            logger.info(
                "微信预热未完成，走完整发送: %s",
                prep.get("error") or prep.get("message") or "",
            )
        send_result = desktop.send_wechat_message(group_name, reply_text)
        send_result["send_mode"] = "sequential"

    if prep.get("steps"):
        existing = send_result.get("steps")
        if isinstance(existing, list):
            send_result["steps"] = [{"step": "prepare", "ok": prep.get("success")}] + existing
        else:
            send_result["prepare_steps"] = prep.get("steps")
    return send_result, reply_text, reply_source, llm_error


def _run_async(coro):
    """在同步被动轮询中安全执行 async LLM 调用。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=90)


_WXID_SALUTATION_RE = re.compile(r"^wxid_[0-9a-zA-Z_-]+$", re.I)
_LOOSE_ACCOUNT_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,31}$")


def _normalize_passive_salutation(name: str) -> str:
    """称呼：不用 wxid/纯账号当客户名。"""
    n = (name or "").strip()
    if not n or _WXID_SALUTATION_RE.match(n) or _LOOSE_ACCOUNT_RE.match(n):
        return "您好"
    return n


def _clean_incoming_snippet(text: str, *, max_len: int = 80) -> str:
    """模板摘要：去掉 @ 提及与过长引用，避免「已看到：@修茈科技 …」。"""
    t = re.sub(r"@\S+", "", (text or "").strip())
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_len:
        t = t[:max_len].rstrip() + "…"
    return t


def build_passive_reply_text_template(
    *,
    incoming: str,
    stage: str,
    client_name: str,
) -> str:
    """被动回复话术（规则模板，LLM 不可用时的兜底）。"""
    name = _normalize_passive_salutation(client_name)
    det = build_deterministic_passive_reply(incoming, client_name=name)
    if det:
        return det
    snippet = _clean_incoming_snippet(incoming)
    if stage in ("idle", "connected"):
        return (
            f"{name}，收到您的消息。"
            + (f"关于「{snippet}」，" if snippet else "")
            + "我是修茈科技客服，稍后为您详细回复。若方便也可直接说明您的具体需求。"
        )
    if stage in ("intake", "intake_done"):
        return (
            f"{name}，已看到：{snippet or '您的反馈'}。"
            "需求信息我们已记录，会按您的场景整理方案后回复。"
        )
    if stage in ("quoted", "negotiating", "contract_pending"):
        return (
            f"{name}，收到。关于报价/合同相关的问题（{snippet or '您刚提到的内容'}），"
            "我这边确认后尽快在群里回复您。"
        )
    # delivered/signed 等阶段勿再用「我们会尽快跟进」套话
    return (
        f"{name}，收到您的消息。"
        + (f"关于「{snippet}」，" if snippet else "")
        + "我是修茈科技客服，稍后为您详细回复。若方便也可直接说明您的具体需求。"
    )


_GENERIC_CANNED_FRAGMENTS = (
    "您刚说的我看到了",
    "有需要直接说就行",
    "有需要随时告诉",
    "您刚说的我已看到",
    "您说我在听",
    "我们会尽快跟进",
    "有需要随时告诉我就行",
)

_TEMPLATE_CANNED_FRAGMENTS = (
    "稍后为您详细回复",
    "已看到：",
    "需求信息我们已记录",
    "如有其他需要",
    "请随时告知",
    "收到您的消息",
    "会按您的场景整理方案",
)

_INCOMING_ENTITY_KEYWORDS_RE = re.compile(
    r"PPT|ppt|金蝶|企微|合同|草案|方案|增项|尾款|试点|付款|预算|"
    r"门店|培训|验收|三七|链接|审批|配方|活动页|作业|库存|会员",
    re.IGNORECASE,
)

_INCOMING_STOPWORDS = frozenset(
    {
        "你好",
        "您好",
        "谢谢",
        "感谢",
        "好的",
        "嗯嗯",
        "在吗",
        "请问",
        "一下",
        "我们",
        "你们",
        "这个",
        "那个",
        "什么",
        "怎么",
        "可以",
        "已经",
        "就是",
        "还是",
    }
)

_SHARE_FILE_INCOMING_RE = re.compile(
    r"PPT|ppt|文件|附件|链接|作业|分享|图片|文档|表格|pdf|PDF",
    re.IGNORECASE,
)

_VAGUE_FILE_ACK_RE = re.compile(
    r"收到您的文件|已经收到您的文件|感谢您分享",
    re.IGNORECASE,
)


def _is_identity_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(
        re.search(
            r"谁家|哪家|你是谁|你是啥|你叫啥|叫什么|什么名字|"
            r"什么AI|啥AI|什么模型|哪个公司|什么公司|谁家的|你是Ai",
            t,
            re.I,
        )
    )


def _mentions_xiuci_brand(text: str) -> bool:
    return "修茈" in (text or "")


def build_deterministic_passive_reply(
    incoming: str,
    *,
    client_name: str = "",
    allow_contract_fallback: bool = True,
) -> str | None:
    """
    不经 LLM 的短回复。
    allow_contract_fallback=False 时仅身份问句（走 LLM 前勿抢答合同/付款，避免每条都一样）。
    """
    who = _normalize_passive_salutation(client_name)
    inc = (incoming or "").strip()
    if _is_identity_question(inc):
        prefix = f"{who}，" if who != "您好" else ""
        return f"{prefix}我是修茈科技在群里为您服务的客服助理，您有问题可以直接在这里说。"
    if (
        allow_contract_fallback
        and re.search(r"合同|草案", inc)
        and re.search(r"付款|三七|尾款", inc)
    ):
        prefix = f"{who}，" if who and who != "您好" else ""
        amt_m = re.search(r"\d+万", inc)
        amount = amt_m.group(0) if amt_m else "15万"
        return (
            f"{prefix}好的，按{amount}标准版我先起草合同草案，"
            "付款三七开、验收后付尾款写进条款，今天发您确认。"
        )
    return None


def _contextual_passive_fallback_reply(
    incoming: str,
    *,
    client_name: str = "",
    last_bot_reply: str = "",
) -> str | None:
    """
    LLM 解析/质量全失败后的最后兜底：确定性规则 + 带对方原句摘要的短回复。
    避免 fail-closed 导致「未能解析为可发送的中文回复」却完全不发。
    """
    who = _normalize_passive_salutation(client_name)
    inc = (incoming or "").strip()
    if not inc:
        return None
    det = build_deterministic_passive_reply(inc, client_name=who, allow_contract_fallback=True)
    if det:
        safe_det = assert_safe_outbound_group_reply(det, client_name=who)
        if safe_det:
            issues = _collect_passive_reply_quality_issues(
                safe_det,
                incoming=inc,
                last_bot_reply=last_bot_reply,
            )
            if not issues:
                return safe_det
    prefix = f"{who}，" if who and who != "您好" else ""
    snippet = _clean_incoming_snippet(inc, max_len=28)
    if _is_identity_question(inc):
        cand = f"{prefix}我是修茈科技在群里为您服务的客服助理，您有问题可以直接在这里说。"
    elif snippet:
        kws = _extract_incoming_keywords(inc)
        mention = kws[0] if kws else snippet[:10].rstrip("…")
        cand = (
            f"{prefix}好的，关于您提到的{mention}，我这边已记录，马上帮您核实，有结果在群里跟您说。"
        )
    else:
        cand = f"{prefix}好的，您说的我记下了，马上帮您处理，有结果在群里回复您。"
    safe = assert_safe_outbound_group_reply(cand, client_name=who)
    if not safe or is_generic_canned_reply(safe):
        return None
    issues = _collect_passive_reply_quality_issues(
        safe, incoming=inc, last_bot_reply=last_bot_reply
    )
    if not _reply_addresses_incoming(safe, inc):
        return None
    return safe


def is_generic_canned_reply(text: str) -> bool:
    """模型常照抄 prompt 示例的空泛套话。"""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"您好，我在的，您刚说", t):
        return True
    if any(frag in t for frag in _TEMPLATE_CANNED_FRAGMENTS):
        return True
    return sum(1 for frag in _GENERIC_CANNED_FRAGMENTS if frag in t) >= 2


def _extract_incoming_keywords(incoming: str) -> list[str]:
    """从对方原句提取 ≥2 字中文锚点词，供相关性校验。"""
    t = (incoming or "").strip()
    if not t:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def _add(tok: str) -> None:
        tok = (tok or "").strip()
        if len(tok) < 2:
            return
        if tok.endswith("吧") and len(tok) > 2:
            tok = tok[:-1]
        if tok in _INCOMING_STOPWORDS or tok in seen:
            return
        seen.add(tok)
        out.append(tok)

    for tok in re.findall(r"\d+万", t):
        _add(tok)
    t_han = re.sub(r"\d+万", " ", t)
    for tok in re.findall(r"[\u4e00-\u9fff]{2,}", t_han):
        _add(tok)
        if len(tok) > 5:
            for part in re.split(r"[和与及、]", tok):
                _add(part)
    for ent in _INCOMING_ENTITY_KEYWORDS_RE.findall(t):
        _add(ent)
    return out[:10]


def _incoming_mentions_share_or_file(incoming: str) -> bool:
    return bool(_SHARE_FILE_INCOMING_RE.search((incoming or "").strip()))


def _is_vague_file_acknowledgment(reply: str, incoming: str) -> bool:
    """对方未提文件/分享，回复却泛泛「收到文件/感谢分享」。"""
    rep = (reply or "").strip()
    if not _VAGUE_FILE_ACK_RE.search(rep):
        return False
    if _incoming_mentions_share_or_file(incoming):
        return not bool(re.search(r"PPT|ppt|文件|作业|附件|链接|文档", rep, re.IGNORECASE))
    return True


def _reply_has_incoming_anchor(reply: str, incoming: str) -> bool:
    """回复须扣住对方原句中的具体词，或属于可接受的短寒暄/身份答。"""
    rep = (reply or "").strip()
    inc = (incoming or "").strip()
    if not rep:
        return False
    if _is_identity_question(inc):
        return _mentions_xiuci_brand(rep)
    if len(inc) <= 6:
        return True
    keywords = _extract_incoming_keywords(inc)
    if keywords and any(kw in rep for kw in keywords):
        return True
    if _incoming_mentions_share_or_file(inc) and re.search(
        r"PPT|ppt|文件|作业|附件|链接|文档|分享", rep, re.IGNORECASE
    ):
        return True
    if not keywords and len(inc) <= 12:
        return True
    return False


def _is_meta_echo_of_incoming(reply: str, incoming: str) -> bool:
    """禁止把对方原句当回复，或带「具体词句/对方说」等分析口吻。"""
    rep = (reply or "").strip()
    inc = (incoming or "").strip()
    if not rep:
        return False
    if re.search(
        r"(具体词句|具体内容是|对方(刚)?说[：:\"「]|用户(刚)?说[：:\"「]|对方提到|针对[「\"“]|"
        r"[吧呢啊][\"\"」][：:]|^例如[，,]|对方的意思是|意思是：|我可以确认)",
        rep,
    ):
        return True
    if inc and len(inc) >= 8 and inc in rep and len(rep) <= len(inc) + 36:
        return True
    return False


def _reply_addresses_incoming(reply: str, incoming: str) -> bool:
    """弱校验：拒绝空泛套话、未针对对方原句的敷衍回复（不预设答案内容）。"""
    rep = (reply or "").strip()
    inc = (incoming or "").strip()
    if not rep or is_generic_canned_reply(rep):
        return False
    if _is_meta_echo_of_incoming(rep, inc):
        return False
    if len(inc) >= 4 and "您刚说的我看到了" in rep:
        return False
    if _is_vague_file_acknowledgment(rep, inc):
        return False
    return _reply_has_incoming_anchor(rep, inc)


def _collect_passive_reply_quality_issues(
    reply: str,
    *,
    incoming: str,
    last_bot_reply: str = "",
) -> list[str]:
    """供 LLM 重写提示使用，不生成固定话术。"""
    issues: list[str] = []
    text = (reply or "").strip()
    if not text:
        issues.append("未能解析为可发送的中文回复")
        return issues
    if is_generic_canned_reply(text):
        issues.append("勿使用「您刚说的我看到了、有需要直接说」等泛泛套话")
    if _is_meta_echo_of_incoming(text, incoming):
        issues.append("勿复述对方原句或写「具体词句/对方说」等分析句，须写可直接发送的客服回复")
    if re.match(r"^(对方|客户)(提出|要求|的意思|要)", text):
        issues.append("须用客服口吻直接回复（好的/收到开头），勿写「对方提出/客户要求」转述句")
    if is_reply_format_placeholder(text):
        issues.append(
            "勿把任务说明写进 reply（如「用口语写1～2句中文直接回复对方」），只写发给客户的话"
        )
    prev = (last_bot_reply or "").strip()
    if prev and text == prev:
        issues.append("勿与上一条机器人回复完全相同，须换措辞")
    if not _reply_addresses_incoming(text, incoming):
        issues.append("须针对对方刚说的内容作答，勿答非所问")
    if _is_vague_file_acknowledgment(text, incoming):
        issues.append("勿空泛说「收到文件/感谢分享」；须点出对方提到的 PPT/作业/文件等具体内容")
    if _is_identity_question(incoming) and not _mentions_xiuci_brand(text):
        issues.append("对方在问身份/归属，回复中须表明是修茈科技的客服或助理（须出现「修茈」）")
    return issues


_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"
_REDACTED_OPEN = "<" + "redacted_thinking" + ">"
_REDACTED_CLOSE = "</" + "redacted_thinking" + ">"
_THINK_BLOCK_RE = re.compile(
    re.escape(_THINK_OPEN) + r"[\s\S]*?" + re.escape(_THINK_CLOSE),
    re.IGNORECASE,
)
_THINK_TAIL_RE = re.compile(re.escape(_THINK_OPEN) + r"[\s\S]*", re.IGNORECASE)
_REDACTED_BLOCK_RE = re.compile(
    re.escape(_REDACTED_OPEN) + r"[\s\S]*?" + re.escape(_REDACTED_CLOSE),
    re.IGNORECASE,
)
_REPLY_TAG_RE = re.compile(r"【回复】\s*([\s\S]+)", re.IGNORECASE)

# 模型常复述 system 里的约束；命中任一片段即不可发到微信群
_PROMPT_ECHO_FRAGMENTS: tuple[str, ...] = (
    "原样发到微信",
    "发到微信群",
    "客户可见",
    "只能写客户",
    "禁止以",
    "禁止复述",
    "英文分析",
    "对方原话",
    "任务、规则",
    "套话",
    "口语化中文",
    "不要 json",
    "不要 wxid",
    "专属客服助理",
    "输出会",
    "特定词语开头",
    "不能复述",
    "用口语写",
    "直接回复对方",
    "直接回答对方",
    "1～2句",
    "1-2句",
    "只输出 json",
    "reply字段",
    "客户的最新消息",
    "参考近期群聊",
    "参考近期",
    "不要照抄",
    "勿照抄",
    "作为客服",
    "已经回复过",
    "必须换措辞",
    "不能复读",
    "从参考的近期",
    "历史中，我",
    "本次必须",
    "需求信息我们已记录",
    "已看到：",
    "会按您的场景",
)

_REPLY_FORMAT_PLACEHOLDER_RE = re.compile(
    r"^(用口语)?写?\s*[12一二][到～\-—.]?\s*[23二三]?\s*句.{0,24}(直接)?(回复|回答)对方",
    re.IGNORECASE,
)


def is_reply_format_placeholder(text: str) -> bool:
    """模型把 JSON 格式说明抄进 reply 字段（如「用口语写1～2句中文直接回复对方」）。"""
    t = (text or "").strip()
    if not t:
        return True
    compact = re.sub(r"[\s\u3000]+", "", t)
    for sample in (
        "用口语写1～2句中文直接回复对方",
        "用口语写1-2句中文直接回复对方",
        "1～2句口语化中文直接回答对方这一句",
        "1-2句口语化中文直接回答对方这一句",
        "12句口语化中文直接回答对方这一句",
        "发给客户的1～3句口语化中文",
        "发给客户的1-3句口语化中文",
    ):
        if compact == re.sub(r"[\s\u3000]+", "", sample) or t == sample:
            return True
    if _REPLY_FORMAT_PLACEHOLDER_RE.match(t):
        return True
    if len(t) <= 40 and re.search(
        r"(用口语写|直接回复对方|直接回答对方这一句|口语化中文|只输出\s*json)",
        t,
        re.I,
    ):
        if not re.search(r"(您好|你好|在的|修茈|？|！)", t):
            return True
    return False


_META_SENTENCE_RE = re.compile(
    "|".join(
        (
            r"^好的[，,]\s*(我(来|将|需要|会)?(分析|考虑|根据|结合|整理|回复|说)|让(我|我们))",
            r"^结合(一下|分析|考虑|用户|对方|上文|历史|群聊)",
            r"^首先[，,]",
            r"^让我",
            r"^根据",
            r"^分析",
            r"^考虑",
            r"^因此",
            r"^所以",
            r"^这里",
            r"^现在",
            r"^这句话",
            r"^对方(的)?(消息|说|提到)",
            r"修茈科技之前",
            r"不能使用套话",
            r"^我需要(回复|写|在群里)",
            r"^我要回复",
            r"用户是\s*\w+",
            r"客户(称呼|是)",
            r"商机阶段",
            r"当前.{0,8}阶段",
            r"在微信群(聊)?里(回复|说|配置)",
            r"他说[：:\"]",
            r"对方(刚)?说",
            r"回复要",
            r"用中文",
            r"[12][到～\-]3\s*句",
            r"专属客服助理",
            r"口语化",
            r"群名称",
            r"不要输出",
            r"禁止重复",
            r"思考过程",
            r"原样发到",
            r"客户可见",
            r"禁止以",
            r"禁止复述",
            r"英文分析",
            r"^输出会",
            r"特定词语",
            r"不能复述",
            r"Looking at",
            r"^First,",
            r"^I need to",
            r"客户的最新消息",
            r"参考近期",
            r"不要照抄",
            r"勿照抄",
            r"作为客服",
            r"已经回复过",
            r"必须换措辞",
            r"不能复读",
            r"从参考的",
            r"^历史中",
        )
    ),
    flags=re.IGNORECASE,
)

_UNSAFE_OUTBOUND_WHOLE_RE = re.compile(
    r"客户的最新消息|参考近期群聊|不要照抄|勿照抄|作为客服|已经回复过|"
    r"必须换措辞|不能复读|从参考的近期|只输出\s*json|reply\s*字段",
    re.IGNORECASE,
)
_CONTEXT_VERDICT_RE = re.compile(
    r"[-–—]\s*[\u4e00-\u9fff]{1,12}\s*[:：]\s*.+\s*[-–—]\s*(对|错|是|否)\s*$"
)


def is_prompt_echo_reply(text: str) -> bool:
    """是否为复述提示词/规则/判题格式，禁止发到微信群。"""
    t = (text or "").strip()
    if not t:
        return True
    if _UNSAFE_OUTBOUND_WHOLE_RE.search(t):
        return True
    if is_reply_format_placeholder(t):
        return True
    lower = t.lower()
    if any(f.lower() in lower for f in _PROMPT_ECHO_FRAGMENTS):
        return True
    if _CONTEXT_VERDICT_RE.search(t):
        return True
    if " - " in t and re.search(r"[:：].*[-–—]\s*(对|错)\s*$", t):
        return True
    return False


def _extract_tagged_reply(text: str) -> str:
    """若模型按约定输出【回复】…，只取标签后正文（截断后续分析句）。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    body = ""
    m = _REPLY_TAG_RE.search(raw)
    if m:
        body = m.group(1).strip()
    elif "【回复】" in raw:
        body = raw.split("【回复】", 1)[-1].strip()
    else:
        return raw
    stop = re.search(r"(这有点|让我|用户(说|似乎)|解析|混乱|指令|格式是)", body)
    if stop and stop.start() > 0:
        body = body[: stop.start()].strip()
    parts = [p.strip() for p in re.split(r"(?<=[。！？])", body) if p.strip()]
    clean: list[str] = []
    for p in parts:
        if _sentence_is_llm_meta(p) or is_prompt_echo_reply(p):
            break
        clean.append(p)
        if len(clean) >= 3:
            break
    if clean:
        return "".join(clean)
    return body.strip()


def _sentence_is_llm_meta(sentence: str) -> bool:
    s = (sentence or "").strip()
    if not s or len(s) < 2:
        return True
    if _META_SENTENCE_RE.search(s):
        return True
    if is_prompt_echo_reply(s):
        return True
    if (
        len(s) > 60
        and sum(1 for k in ("需要", "回复", "用户", "阶段", "群聊", "助理") if k in s) >= 3
    ):
        return True
    return False


def _looks_like_thinking_dump(text: str) -> bool:
    """整段仍是分析/复述而非客户可见话术时视为无效。"""
    t = (text or "").strip()
    if not t:
        return True
    markers = (
        "让我",
        "分析",
        "考虑",
        "根据",
        "用户说",
        "对方说",
        "我需要",
        "应该回复",
        "思考",
        "首先",
        "其次",
        "总结",
        "商机",
        "阶段是",
        "客户的最新消息",
        "参考近期",
        "不要照抄",
        "作为客服",
        "已经回复过",
    )
    hits = sum(1 for m in markers if m in t)
    if hits >= 2 and len(t) > 35:
        return True
    if hits >= 1 and len(t) > 120 and not re.search(r"[。！？]\s*[\u4e00-\u9fff]{2,8}[，,]", t):
        return True
    return False


def strip_model_reasoning_from_reply(raw: str) -> str:
    """去掉推理模型  /redacted_thinking/ 英文分析等，再交给 sanitize。"""
    text = (raw or "").strip()
    if not text:
        return ""
    text = _THINK_BLOCK_RE.sub("", text)
    text = _THINK_TAIL_RE.sub("", text)
    text = _REDACTED_BLOCK_RE.sub("", text)
    lower = text.lower()
    if _THINK_CLOSE.lower() in lower:
        text = re.split(re.escape(_THINK_CLOSE), text, flags=re.IGNORECASE)[-1].strip()
    if _THINK_OPEN.lower() in lower and _THINK_CLOSE.lower() not in lower:
        text = re.split(re.escape(_THINK_OPEN), text, flags=re.IGNORECASE)[0].strip()
    for sep in (
        "可直接发送的回复：",
        "可直接发送的回复:",
        "最终回复：",
        "最终回复:",
        "发给客户：",
        "发给微信群：",
        "回复正文：",
        "回复正文:",
    ):
        if sep in text:
            text = text.split(sep)[-1].strip()
    return text.strip()


def _is_valid_passive_reply_body(reply: str) -> bool:
    """过滤 JSON 占位符/格式说明，避免把「发给客户的1～3句…」当正文发出。"""
    t = (reply or "").strip()
    if len(t) < 8 or len(t) > 220:
        return False
    if not re.search(r"[\u4e00-\u9fff]{4,}", t):
        return False
    bad = (
        "发给客户",
        "口语化",
        "JSON",
        "格式",
        "1～3",
        "1-3",
        "中文回复",
        "示例",
        "reply",
        "MiMo",
        "参数",
    )
    if any(b in t for b in bad):
        return False
    if is_prompt_echo_reply(t):
        return False
    if is_generic_canned_reply(t):
        return False
    return True


def _parse_passive_reply_json(raw: str) -> str:
    """从模型 JSON 输出中解析 reply 字段（适配 mimo 等爱包在 markdown 里的返回）。"""
    text = strip_model_reasoning_from_reply(raw)
    if not text:
        return ""
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                text = block
                break
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blob = text[start : end + 1]
        try:
            obj = json.loads(blob)
            reply = str(obj.get("reply") or "").strip()
            if _is_valid_passive_reply_body(reply):
                return reply
        except json.JSONDecodeError:
            # mimo 等偶发尾逗号、单引号包裹
            blob2 = re.sub(r",\s*}", "}", blob)
            blob2 = blob2.replace("'", '"')
            try:
                obj = json.loads(blob2)
                reply = str(obj.get("reply") or "").strip()
                if _is_valid_passive_reply_body(reply):
                    return reply
            except json.JSONDecodeError:
                pass
    # 从全文找最后一个像真实回复的 "reply":"…"（跳过提示词里的格式示例）
    for m in re.finditer(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
        candidate = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
        if _is_valid_passive_reply_body(candidate):
            return candidate
    return ""


def _parse_passive_reply_candidates_from_json(raw: str) -> list[str]:
    """解析 {\"replies\":[\"…\",\"…\"]} 或多键 reply / reply_alt。"""
    text = strip_model_reasoning_from_reply(raw)
    if not text:
        return []
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.lower().startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                text = block
                break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    blob = text[start : end + 1]
    obj: dict[str, Any] | None = None
    try:
        parsed = json.loads(blob)
        if isinstance(parsed, dict):
            obj = parsed
    except json.JSONDecodeError:
        blob2 = re.sub(r",\s*}", "}", blob)
        blob2 = blob2.replace("'", '"')
        try:
            parsed = json.loads(blob2)
            if isinstance(parsed, dict):
                obj = parsed
        except json.JSONDecodeError:
            obj = None
    out: list[str] = []
    if obj:
        replies = obj.get("replies")
        if isinstance(replies, list):
            for item in replies:
                s = str(item or "").strip()
                if _is_valid_passive_reply_body(s) and s not in out:
                    out.append(s)
        for key in ("reply", "reply_alt", "reply2", "alternative"):
            s = str(obj.get(key) or "").strip()
            if _is_valid_passive_reply_body(s) and s not in out:
                out.append(s)
    return out


def _coerce_passive_candidates_from_raw(
    raw: str,
    *,
    client_name: str = "",
    incoming: str = "",
) -> list[str]:
    """从单次 LLM 原始输出抽取 0～N 条可发送候选。"""
    accepted: list[str] = []
    seen: set[str] = set()

    def _add(cand: str) -> None:
        safe = _accept_coerced_passive_reply(cand, client_name=client_name, incoming=incoming)
        if safe and safe not in seen:
            seen.add(safe)
            accepted.append(safe)

    for body in _parse_passive_reply_candidates_from_json(raw):
        _add(body)
    if not accepted:
        single = _coerce_passive_llm_reply_text(raw, client_name=client_name, incoming=incoming)
        if single:
            _add(single)
    return accepted


def _pick_best_passive_candidate(
    candidates: list[str],
    *,
    incoming: str,
    last_bot_reply: str = "",
    client_name: str = "",
) -> str:
    """在多条候选中选质量问题最少且可发送的一条。"""
    inc = (incoming or "").strip()
    prev = (last_bot_reply or "").strip()
    scored: list[tuple[int, int, str]] = []
    for cand in candidates:
        c = (cand or "").strip()
        if not c:
            continue
        safe = assert_safe_outbound_group_reply(c, client_name=client_name)
        if (
            not safe
            or is_generic_canned_reply(safe)
            or safe.lstrip().startswith("{")
            or '"replies"' in safe
        ):
            continue
        issues = _collect_passive_reply_quality_issues(safe, incoming=inc, last_bot_reply=prev)
        scored.append((len(issues), -len(safe), safe))
    if not scored:
        return ""
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored[0][2]


_EXAMPLE_REPLY_IN_PROSE_RE = re.compile(
    r"(?:例如|比如|可以回复|回复(?:可以)?是?|建议回复)[：:]\s*[「\"“]?"
    r"([^「」\"”\n]{8,160}?)"
    r"[」\"”]?(?:[。！？]|$)",
    re.IGNORECASE,
)

_QUOTED_CN_REPLY_RE = re.compile(
    r"[「\"“]([^「」\"”]{8,160}[。！？])[」\"”]",
)
_CHAT_LOG_LINE_RE = re.compile(r"^(模拟客户|成员|客户|群主|我)\s*[:：]")


def _accept_coerced_passive_reply(
    cand: str,
    *,
    client_name: str = "",
    incoming: str = "",
) -> str | None:
    """抽取候选须可发送，且不能是复述群聊记录或答非所问。"""
    safe = assert_safe_outbound_group_reply(cand, client_name=client_name)
    if not safe:
        return None
    if _CHAT_LOG_LINE_RE.search(safe):
        return None
    inc = (incoming or "").strip()
    if _is_meta_echo_of_incoming(safe, inc):
        return None
    if len(inc) >= 4 and not _reply_addresses_incoming(safe, inc):
        return None
    return safe


def _coerce_passive_llm_reply_text(
    raw: str,
    *,
    client_name: str = "",
    incoming: str = "",
) -> str:
    """
    mimo 等模型常输出长段分析而非 JSON；从正文中抽取可发送的一句客服话术。
    """
    text = strip_model_reasoning_from_reply(raw or "")
    if not text:
        return ""
    parsed = _parse_passive_reply_json(text)
    if parsed:
        safe = _accept_coerced_passive_reply(parsed, client_name=client_name, incoming=incoming)
        if safe:
            return safe
    sanitized = sanitize_passive_group_reply_text(text, client_name=client_name)
    if sanitized:
        safe = _accept_coerced_passive_reply(sanitized, client_name=client_name, incoming=incoming)
        if safe:
            return safe
    for m in _EXAMPLE_REPLY_IN_PROSE_RE.finditer(text):
        cand = (m.group(1) or "").strip()
        safe = _accept_coerced_passive_reply(cand, client_name=client_name, incoming=incoming)
        if safe:
            return safe
    inline = _extract_inline_reply_candidates(text, client_name=client_name)
    if inline:
        safe = _accept_coerced_passive_reply(inline, client_name=client_name, incoming=incoming)
        if safe:
            return safe
    for m in _QUOTED_CN_REPLY_RE.finditer(text):
        cand = (m.group(1) or "").strip()
        if _sentence_is_llm_meta(cand) or is_prompt_echo_reply(cand):
            continue
        safe = _accept_coerced_passive_reply(cand, client_name=client_name, incoming=incoming)
        if safe:
            return safe
    for line in re.split(r"[\n。]", text):
        line = line.strip().strip("「」\"'")
        if not line or len(line) < 8 or len(line) > 120:
            continue
        if _CHAT_LOG_LINE_RE.match(line):
            continue
        if not re.match(r"^(好的|收到|您好|感谢|关于|这份|PPT|我们)", line):
            continue
        if _sentence_is_llm_meta(line) or is_prompt_echo_reply(line):
            continue
        safe = _accept_coerced_passive_reply(
            line if line.endswith(("。", "！", "？")) else f"{line}。",
            client_name=client_name,
            incoming=incoming,
        )
        if safe:
            return safe
    aligned = _extract_keyword_aligned_reply_from_prose(text, incoming, client_name=client_name)
    if aligned:
        return aligned
    safe_raw = _accept_coerced_passive_reply(text, client_name=client_name, incoming=incoming)
    if safe_raw:
        return safe_raw
    return ""


def _extract_keyword_aligned_reply_from_prose(
    text: str,
    incoming: str,
    *,
    client_name: str = "",
) -> str:
    """从分析长文中捞含对方锚点词、且像客服口吻的句子。"""
    kws = _extract_incoming_keywords(incoming)
    if not kws:
        return ""
    best: tuple[int, str] = (0, "")
    for line in re.split(r"[\n。；;]", text or ""):
        line = line.strip().strip("「」\"'-*·")
        if len(line) < 10 or len(line) > 140:
            continue
        if _CHAT_LOG_LINE_RE.match(line) or _sentence_is_llm_meta(line):
            continue
        if not re.search(r"[\u4e00-\u9fff]{4,}", line):
            continue
        hits = sum(1 for kw in kws if kw in line)
        if hits < 1:
            continue
        if not re.search(r"(好的|收到|可以|我们|按|会|将|先)", line):
            continue
        if hits > best[0]:
            body = line if line.endswith(("。", "！", "？")) else f"{line}。"
            best = (hits, body)
    if not best[1]:
        return ""
    safe = _accept_coerced_passive_reply(best[1], client_name=client_name, incoming=incoming)
    return safe or ""


def _extract_inline_reply_candidates(raw: str, *, client_name: str = "") -> str:
    """模型未按【回复】格式时，从分析文本中捞一句像客服话术的短中文。"""
    who = (client_name or "").strip()
    for line in re.split(r"[\n；;]", raw or ""):
        line = re.sub(r"^[\s\-•*·\d.)、]+", "", line).strip().strip("「」\"'")
        if not line or len(line) < 4 or len(line) > 96:
            continue
        if not re.search(r"[\u4e00-\u9fff]{2,}", line):
            continue
        if _sentence_is_llm_meta(line) or is_prompt_echo_reply(line):
            continue
        if any(k in line for k in ("可能的回复", "回复结构", "禁止输出", "用户指令", "示例是")):
            continue
        if _CHAT_LOG_LINE_RE.match(line):
            continue
        if re.match(r"^[\u4e00-\u9fff]{1,8}[，,]?您好", line):
            return line if line.endswith(("。", "！", "？")) else f"{line}。"
    return ""


def sanitize_passive_group_reply_text(raw: str, *, client_name: str = "") -> str:
    """
    从模型输出中提取可发到微信群的一句/几句中文，去掉思考过程与英文规则复述。
    部分推理模型会把 prompt 分析（含中文）一并输出，此处做兜底裁剪。
    """
    text = _extract_tagged_reply(strip_model_reasoning_from_reply(raw))
    if not text:
        return ""
    if is_prompt_echo_reply(text):
        return ""

    for sep in (
        "Possible response:",
        "possible response:",
        "可直接发送的回复：",
        "可直接发送的回复:",
        "可直接发送：",
        "最终回复：",
        "回复示例：",
        "发给微信群：",
        "【只输出下面这种",
    ):
        if sep in text:
            text = text.split(sep)[-1].strip()

    cn_start = re.search(r"[\u4e00-\u9fff]", text)
    if cn_start and cn_start.start() > 0:
        prefix = text[: cn_start.start()]
        if re.search(r"[A-Za-z]{8,}", prefix):
            text = text[cn_start.start() :].strip()

    text = re.sub(r"\s+", " ", text).strip().strip('"').strip("「」").strip("】")
    parts = [p.strip() for p in re.split(r"(?<=[。！？])", text) if p.strip()]
    parts = [p for p in parts if re.search(r"[\u4e00-\u9fff]", p) and not _sentence_is_llm_meta(p)]
    if parts:
        text = "".join(parts[:3])
    else:
        text = ""

    if not text:
        return ""
    if _looks_like_thinking_dump(text):
        return ""
    if is_prompt_echo_reply(text):
        return ""
    if len(text) > 220:
        text = text[:220].rstrip()
        for end in ("。", "！", "？", "，"):
            if end in text:
                text = text[: text.rfind(end) + 1]
                break
    return text


def assert_safe_outbound_group_reply(
    raw: str,
    *,
    client_name: str = "",
) -> str | None:
    """
    发送前最后一道闸：清洗 + 禁 meta/思考过程 + 正文校验。
    不通过则返回 None（fail-closed，不发到微信群）。
    """
    if not (raw or "").strip():
        return None
    if _UNSAFE_OUTBOUND_WHOLE_RE.search(raw):
        return None
    cleaned = sanitize_passive_group_reply_text(raw, client_name=client_name)
    if not cleaned:
        return None
    if is_prompt_echo_reply(cleaned) or _looks_like_thinking_dump(cleaned):
        return None
    if not _is_valid_passive_reply_body(cleaned):
        return None
    lead = cleaned.split("，", 1)[0].strip()
    if _WXID_SALUTATION_RE.match(lead) or _LOOSE_ACCOUNT_RE.match(lead):
        return None
    return cleaned


def _finalize_outbound_reply(
    raw: str,
    *,
    incoming: str,
    client_name: str,
) -> tuple[str, str]:
    """
    将候选回复变为可发送正文；失败时尝试确定性短回复。
    返回 (text, block_reason)，text 为空表示不可发送。
    """
    safe = assert_safe_outbound_group_reply(raw, client_name=client_name)
    if safe:
        return safe, ""
    det = build_deterministic_passive_reply(incoming, client_name=client_name)
    if det:
        safe_det = assert_safe_outbound_group_reply(det, client_name=client_name)
        if safe_det:
            return safe_det, ""
    return "", "未通过发送安全校验（疑似思考过程或复述任务）"


async def _build_passive_reply_llm_async(
    *,
    incoming: str,
    stage: str,
    client_name: str,
    group_name: str,
    recent_context: str = "",
    last_bot_reply: str = "",
    session_id: str = "",
    request: Any = None,
) -> str:
    from app.mod_sdk.mod_employee_llm import mod_employee_complete

    who = _normalize_passive_salutation(client_name or "客户")
    incoming_clean = (incoming or "").strip().replace("\n", " ")[:500]
    det = build_deterministic_passive_reply(
        incoming_clean, client_name=who, allow_contract_fallback=False
    )
    if det:
        safe_det = assert_safe_outbound_group_reply(det, client_name=who)
        if safe_det:
            return safe_det

    stage_label = _STAGE_LABELS.get(stage, stage)
    passive_provider = os.environ.get("XCAGI_PASSIVE_LLM_PROVIDER", "").strip()
    passive_model = os.environ.get("XCAGI_PASSIVE_LLM_MODEL", "").strip()
    prev = (last_bot_reply or "").strip()

    system = (
        "你是修茈科技在企业微信群里的客服。只输出 JSON 对象，键名 reply。"
        "reply 的值必须是直接发给客户的中文话术，1～3 句口语，禁止分析、禁止复述任务或规则。"
        "必须针对 user 里「对方说」中的具体词句回应，禁止「收到您的消息」「稍后为您详细回复」"
        "「已看到：」「有需要随时告知」等空话。禁止出现「客户的最新消息」「参考近期」「不要照抄」等字样。"
        "回复中应自然体现修茈科技身份。每次须换自然措辞，勿与「上一条己方已发」雷同。"
    )
    user_parts = [
        f"群：{group_name or '未知'}",
        f"阶段：{stage_label}",
        f"对方说：{incoming_clean}",
    ]
    if recent_context:
        ctx_cap = _passive_recent_context_char_limit()
        user_parts.append(f"近期群聊（仅供理解，勿照抄原文）：\n{recent_context[:ctx_cap]}")
    if prev:
        user_parts.append(f"上一条己方已发（勿复读）：{prev[:80]}")
    user_content = "\n".join(user_parts)

    json_format: dict[str, Any] = {"type": "json_object"}
    n_cand = _passive_llm_candidate_count()

    async def _call_llm_raw(
        messages: list[dict[str, str]],
        *,
        max_tokens: int = _PASSIVE_LLM_MAX_TOKENS,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = json_format,
    ) -> str:
        out = await mod_employee_complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature if temperature is not None else _passive_llm_temperature(),
            session_id=session_id,
            request=request,
            provider=passive_provider,
            model=passive_model,
            response_format=response_format,
        )
        if not out.get("ok"):
            raise RuntimeError(str(out.get("error") or "LLM 失败"))
        return str(out.get("content") or "")

    async def _call_llm(
        messages: list[dict[str, str]],
        *,
        max_tokens: int = _PASSIVE_LLM_MAX_TOKENS,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = json_format,
    ) -> str:
        raw_content = await _call_llm_raw(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        return (
            _coerce_passive_llm_reply_text(raw_content, client_name=who, incoming=incoming_clean)
            or ""
        )

    async def _generate_passive_llm_candidates(
        base_messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        dual_json: bool = True,
        parallel_singles: bool = True,
    ) -> list[str]:
        """一次生成多条候选：先 dual JSON，再并行单条补全。"""
        pool: list[str] = []
        temp0 = temperature if temperature is not None else _passive_llm_temperature()

        if dual_json and n_cand >= 2:
            batch_hint = (
                f'请只输出 JSON：{{"replies":["第一条可直接发微信的中文","第二条换措辞的中文"]}}，'
                f"共 {n_cand} 条，措辞须不同，均须扣住对方刚说的内容，禁止套话。"
            )
            batch_messages = list(base_messages) + [{"role": "user", "content": batch_hint}]
            try:
                raw_batch = await _call_llm_raw(
                    batch_messages,
                    max_tokens=_PASSIVE_LLM_RETRY_MAX_TOKENS + 80,
                    temperature=temp0,
                    response_format=json_format,
                )
                pool.extend(
                    _coerce_passive_candidates_from_raw(
                        raw_batch,
                        client_name=who,
                        incoming=incoming_clean,
                    )
                )
            except Exception as exc:
                logger.debug("被动回复 dual JSON 批次失败: %s", exc)

        if len(pool) < n_cand and parallel_singles:
            temps = [
                temp0,
                min(0.86, temp0 + 0.11),
                min(0.88, temp0 + 0.18),
            ]
            tasks = [
                _call_llm(
                    base_messages,
                    max_tokens=_PASSIVE_LLM_MAX_TOKENS,
                    temperature=temps[i % len(temps)],
                    response_format=json_format,
                )
                for i in range(n_cand)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, str) and r.strip() and r not in pool:
                    pool.append(r.strip())

        return pool

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    # 阶段 1：一次生成 N 条候选并筛选（用户要求：避免单条反复失败）
    text = _pick_best_passive_candidate(
        await _generate_passive_llm_candidates(messages),
        incoming=incoming_clean,
        last_bot_reply=prev,
        client_name=who,
    )
    if text and not _collect_passive_reply_quality_issues(
        text, incoming=incoming_clean, last_bot_reply=prev
    ):
        return text

    # 阶段 2：仍失败则少量串行补救（强调 JSON / 纯中文）
    parse_rounds = 1 + _passive_llm_parse_retries()
    for parse_i in range(parse_rounds):
        temp = min(0.82, _passive_llm_temperature() + parse_i * 0.07)
        use_plain = parse_i >= parse_rounds - 1 and parse_rounds > 1
        round_messages = list(messages)
        max_tok = _PASSIVE_LLM_MAX_TOKENS
        fmt: dict[str, Any] | None = json_format
        if parse_i == 0 and n_cand >= 2:
            round_messages.append(
                {
                    "role": "user",
                    "content": (
                        '请只输出 JSON：{"replies":["…","…"]} 两条不同措辞，'
                        "针对对方刚说的内容，可直接发微信群。"
                    ),
                }
            )
            max_tok = _PASSIVE_LLM_RETRY_MAX_TOKENS + 60
            try:
                raw_retry = await _call_llm_raw(
                    round_messages,
                    max_tokens=max_tok,
                    temperature=temp,
                    response_format=fmt,
                )
                picked = _pick_best_passive_candidate(
                    _coerce_passive_candidates_from_raw(
                        raw_retry,
                        client_name=who,
                        incoming=incoming_clean,
                    ),
                    incoming=incoming_clean,
                    last_bot_reply=prev,
                    client_name=who,
                )
                if picked:
                    text = picked
                    break
            except Exception:
                pass
            continue
        if parse_i == 1:
            round_messages.append(
                {
                    "role": "user",
                    "content": (
                        '请只输出 JSON：{"reply":"针对对方刚说的内容写 1～2 句可直接发到微信群的中文"}'
                    ),
                }
            )
            max_tok = _PASSIVE_LLM_RETRY_MAX_TOKENS
        elif use_plain:
            round_messages.append(
                {
                    "role": "user",
                    "content": (
                        "请只写一句可直接发到微信群的中文客服回复。"
                        "不要 JSON、不要分析、不要英文、不要解释。"
                    ),
                }
            )
            max_tok = _PASSIVE_LLM_RETRY_MAX_TOKENS
            fmt = None
        candidates = await _generate_passive_llm_candidates(
            round_messages,
            temperature=temp,
            dual_json=False,
            parallel_singles=True,
        )
        picked = _pick_best_passive_candidate(
            candidates,
            incoming=incoming_clean,
            last_bot_reply=prev,
            client_name=who,
        )
        if picked:
            text = picked
            if not _collect_passive_reply_quality_issues(
                text, incoming=incoming_clean, last_bot_reply=prev
            ):
                break

    if not text:
        fallback = _contextual_passive_fallback_reply(
            incoming_clean,
            client_name=who,
            last_bot_reply=prev,
        )
        if fallback:
            logger.info(
                "被动回复使用上下文兜底（LLM 未解析出正文） incoming=%s",
                incoming_clean[:40],
            )
            return fallback

    for attempt in range(_passive_llm_quality_retries()):
        issues = _collect_passive_reply_quality_issues(
            text or "",
            incoming=incoming_clean,
            last_bot_reply=prev,
        )
        if not issues:
            break
        retry_user = (
            f"对方说：{incoming_clean}\n"
            f"请重写（第{attempt + 2}稿，换说法、扣住对方原话）。问题：{'；'.join(issues)}。"
            '输出 JSON：{"replies":["候选一","候选二"]} 两条不同措辞。'
        )
        retry_msgs = messages + [{"role": "user", "content": retry_user}]
        retried = _pick_best_passive_candidate(
            await _generate_passive_llm_candidates(
                retry_msgs,
                temperature=min(0.85, _passive_llm_temperature() + 0.08 * (attempt + 1)),
            ),
            incoming=incoming_clean,
            last_bot_reply=prev,
            client_name=who,
        )
        if retried:
            text = retried

    safe_final = assert_safe_outbound_group_reply(text or "", client_name=who)
    if safe_final:
        issues = _collect_passive_reply_quality_issues(
            safe_final,
            incoming=incoming_clean,
            last_bot_reply=prev,
        )
        if not issues:
            return safe_final

    fallback = _contextual_passive_fallback_reply(
        incoming_clean,
        client_name=who,
        last_bot_reply=prev,
    )
    if fallback:
        logger.info(
            "被动回复使用上下文兜底（质量检查未过） incoming=%s",
            incoming_clean[:40],
        )
        return fallback

    issues = _collect_passive_reply_quality_issues(
        text or "",
        incoming=incoming_clean,
        last_bot_reply=prev,
    )
    raise RuntimeError(
        "LLM 回复未通过质量检查（" + ("；".join(issues) if issues else "无有效内容") + "）"
    )


def probe_passive_llm_ready(*, session_id: str = "", request: Any = None) -> dict[str, Any]:
    """检查被动回复 LLM 是否可用（与智能对话同源，供前端展示）。"""
    try:
        from app.mod_sdk.mod_employee_llm import probe_host_llm_ready

        return probe_host_llm_ready(session_id=session_id, request=request)
    except Exception as exc:
        return {"ready": False, "mode": "unavailable", "message": str(exc)[:200]}


def build_passive_reply_text(
    *,
    incoming: str,
    stage: str,
    client_name: str,
    group_name: str = "",
    use_llm: bool = True,
    recent_context: str = "",
    last_bot_reply: str = "",
    session_id: str = "",
    request: Any = None,
) -> tuple[str, str, str]:
    """
    生成被动回复。返回 (reply_text, source, llm_error)。
    source 为 llm|deterministic|blocked|template（template 仅当允许兜底时）。
    """
    who = _normalize_passive_salutation(client_name)
    llm_error = ""

    det = build_deterministic_passive_reply(
        incoming, client_name=who, allow_contract_fallback=not use_llm
    )
    if det:
        safe_det = assert_safe_outbound_group_reply(det, client_name=who)
        if safe_det:
            return safe_det, "deterministic", ""

    if use_llm:
        try:
            reply = _run_async(
                _build_passive_reply_llm_async(
                    incoming=incoming,
                    stage=stage,
                    client_name=who,
                    group_name=group_name,
                    recent_context=recent_context,
                    last_bot_reply=last_bot_reply,
                    session_id=session_id,
                    request=request,
                )
            )
            safe = assert_safe_outbound_group_reply(reply, client_name=who)
            if safe:
                return safe, "llm", ""
            raise RuntimeError("LLM 输出未通过发送安全校验")
        except Exception as exc:
            llm_error = str(exc)[:300]
            logger.warning("被动回复 LLM 失败（fail-closed，不发模板）: %s", exc)

    if _passive_allow_template_fallback():
        tpl = build_passive_reply_text_template(
            incoming=incoming,
            stage=stage,
            client_name=who,
        )
        safe_tpl = assert_safe_outbound_group_reply(tpl, client_name=who)
        if safe_tpl:
            if use_llm and not llm_error:
                llm_error = (
                    probe_passive_llm_ready(session_id=session_id, request=request).get("message")
                    or "LLM 未启用"
                )
            return safe_tpl, "template", llm_error
        finalized, block_reason = _finalize_outbound_reply(tpl, incoming=incoming, client_name=who)
        if finalized:
            return finalized, "template", llm_error
        return "", "blocked", block_reason or llm_error or "无可发送的安全回复"

    if use_llm:
        fb = _contextual_passive_fallback_reply(
            incoming,
            client_name=who,
            last_bot_reply=last_bot_reply,
        )
        if fb:
            return (
                fb,
                "deterministic",
                llm_error or "LLM 失败后使用上下文兜底",
            )
        return "", "blocked", llm_error or "LLM 未生成可发送回复"
    return "", "blocked", "未启用 LLM 且无确定性回复"


def passive_poll_once(
    *,
    market_user_id: int,
    username: str = "",
    message_limit: int = 40,
    dry_run: bool = False,
    auto_reply: bool = True,
    max_replies: int = 1,
    use_llm: bool = True,
    skip_sync: bool = False,
    refresh_count_new: int | None = None,
    refresh_latest_label: str = "",
    catch_up_latest: bool = False,
    session_id: str = "",
    request: Any = None,
) -> dict[str, Any]:
    """
    执行一轮被动探测：
    - 快照复制+解密（不直接读微信目录）
    - 同步绑定群消息到 context
    - 对每条新的他人消息（可选）自动回复
    """
    from app.application import get_wechat_contact_app_service
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline
    from app.services.wechat_group_customer_bridge import (
        get_bindings_for_user,
        sync_bound_groups_from_live_wechat,
    )
    from app.services.wechat_message_display import is_bot_outbound_group_message

    uid = int(market_user_id)
    bindings = get_bindings_for_user(uid)
    if not bindings:
        return {
            "success": False,
            "message": "未绑定群聊：请先在内部客服页勾选群并保存绑定",
            "replies": [],
        }

    if skip_sync:
        pulled_new = int(refresh_count_new or 0)
        latest_label = str(refresh_latest_label or "").strip()
        if not latest_label:
            try:
                from app.services.wechat_group_customer_bridge import (
                    build_starred_group_feed,
                )

                max_ts = 0.0
                for row in build_starred_group_feed(limit=20, market_user_id=uid):
                    ts = float(row.get("timestamp") or row.get("last_message_time") or 0)
                    if ts > max_ts:
                        max_ts = ts
                if max_ts > 0:
                    latest_label = datetime.fromtimestamp(max_ts).strftime("%m-%d %H:%M")
            except Exception:
                pass
        sync_result = {
            "success": True,
            "message": "聊天记录已由前端刷新（与数据来源同 API）",
            "synced": len(bindings),
            "failed": 0,
            "messages_pulled": pulled_new,
            "messages_pulled_this_round": pulled_new,
            "latest_message_label": latest_label,
            "message_db_ready": True,
            "skipped_sync": True,
        }
        snapshot_result = {
            "success": True,
            "message": "",
            "rebuilt": False,
            "skipped": False,
        }
    else:
        sync_result = sync_bound_groups_from_live_wechat(
            uid,
            message_limit=message_limit,
            mode="poll",
        )
        snapshot_result = sync_result.get("snapshot") or {
            "success": False,
            "message": "未执行快照",
            "rebuilt": False,
        }
        if not sync_result.get("message_db_ready", True) and not sync_result.get("success"):
            return {
                "success": False,
                "message": (
                    "微信库同步未就绪："
                    + str(sync_result.get("message") or "请先在数据来源配置微信目录并扫描密钥")
                ),
                "snapshot": snapshot_result,
                "sync": sync_result,
                "replies": [],
            }

    doc = load_pipeline(uid, username=username)
    state = _load_passive_state(doc)
    handled: set[str] = set(str(x) for x in state.get("handled_keys") or [])
    replied: set[str] = set(str(x) for x in state.get("replied_keys") or [])
    stable_handled: set[str] = set(str(x) for x in state.get("stable_handled_keys") or [])
    cursors: dict[str, Any] = dict(state.get("cursors") or {})
    binding_n = len(bindings)
    # 每群每轮最多 1 条；全局允许多个绑定群各回 1 条（原先 cap=1 导致只回第一个群）
    req_cap = int(max_replies or 0)
    if req_cap <= 0:
        max_replies = max(1, min(binding_n, 5))
    else:
        max_replies = max(1, min(req_cap, binding_n, 5))
    service = get_wechat_contact_app_service()
    stage = str(doc.get("stage") or "connected")
    client_name = (username or str(doc.get("username") or "")).strip()

    detected: list[dict[str, Any]] = []
    replies: list[dict[str, Any]] = []

    pulled_new = 0
    if isinstance(sync_result, dict):
        pulled_new = int(
            sync_result.get("messages_pulled_this_round") or sync_result.get("messages_pulled") or 0
        )
    effective_catch_up = bool(catch_up_latest or (not dry_run and auto_reply and pulled_new > 0))

    for b in bindings:
        cid = int(b["wechat_contact_id"])
        contact_name = str(b.get("contact_name") or b.get("remark") or "").strip()
        messages = service.get_contact_context(cid)
        if not isinstance(messages, list):
            messages = []

        cursor = cursors.get(str(cid)) or {
            "last_ts": 0.0,
            "last_bot_reply_ts": 0.0,
            "bootstrapped": False,
            "cooldown_until": 0.0,
            "watch_armed_message_ts": 0.0,
        }
        bootstrapped = bool(cursor.get("bootstrapped"))
        max_ts = max((_message_ts(m) for m in messages), default=0.0)

        if not bootstrapped:
            cursor = {
                **cursor,
                "last_ts": max_ts,
                "bootstrapped": True,
                "watch_armed_message_ts": max_ts,
            }
            cursors[str(cid)] = cursor

        pending = _pick_single_pending_incoming(
            messages,
            group_name=contact_name,
            cursor=cursor,
            handled=handled,
            replied=replied,
            stable_handled=stable_handled,
            catch_up_latest=effective_catch_up,
        )
        if pending:
            text = str(pending.get("text") or "").strip()
            ts = _message_ts(pending)
            sender_disp = str(pending.get("sender_display") or "").strip()
            detected.append(
                {
                    "contact_id": cid,
                    "contact_name": contact_name,
                    "text": text,
                    "timestamp": ts,
                    "key": _msg_key(pending),
                    "stable_key": _stable_msg_key(pending),
                    "sender_display": sender_disp,
                }
            )

        ordered_for_cursor = _sorted_messages(messages)
        if pending:
            cursors[str(cid)] = {**cursor, "bootstrapped": True}
        else:
            last_m = ordered_for_cursor[-1] if ordered_for_cursor else None
            last_is_ours = False
            if last_m is not None:
                if str(last_m.get("role") or "").lower() == "self":
                    last_is_ours = True
                elif is_bot_outbound_group_message(
                    str(last_m.get("text") or ""), group_name=contact_name
                ):
                    last_is_ours = True
            if last_is_ours:
                cursors[str(cid)] = {
                    **cursor,
                    "last_ts": max(float(cursor.get("last_ts") or 0), max_ts),
                    "bootstrapped": True,
                }
            else:
                # 最新仍是他人消息但未选中时，勿把 last_ts 顶到 max_ts，否则永远 ts>floor 不成立
                cursors[str(cid)] = {**cursor, "bootstrapped": True}

    detected.sort(key=lambda x: float(x.get("timestamp") or 0))

    # 正式轮询跳过 LLM 探测（省一次 HTTP），探测模式仍检查
    llm_probe = (
        probe_passive_llm_ready(session_id=session_id, request=request)
        if use_llm and dry_run
        else {"ready": bool(use_llm), "message": "" if use_llm else "未开启 LLM"}
    )
    # 探测模式：生成一条预览回复（不发微信），用于确认 LLM/模板
    effective_max = max_replies
    if dry_run and detected:
        effective_max = max(effective_max, 1)

    reply_count = 0
    llm_used = 0
    template_used = 0
    blocked_count = 0
    last_llm_error = ""
    pending_count = 0
    for item in detected:
        if reply_count >= effective_max:
            pending_count += 1
            continue
        group_name = str(item.get("contact_name") or "")
        cid = int(item.get("contact_id") or 0)
        recent_context = ""
        last_bot_outbound = ""
        if cid:
            ctx_msgs = service.get_contact_context(cid)
            if isinstance(ctx_msgs, list) and ctx_msgs:
                recent_context, last_bot_outbound = build_passive_recent_context_from_messages(
                    ctx_msgs,
                    group_name=group_name,
                    exclude_last_incoming=True,
                )
        peer_name = str(item.get("sender_display") or "").strip()
        if peer_name.startswith("wxid_") or _LOOSE_ACCOUNT_RE.match(peer_name):
            peer_name = ""
        reply_to_name = _normalize_passive_salutation(peer_name if peer_name else client_name)
        incoming_text = str(item.get("text") or "")

        def _build_this_reply() -> tuple[str, str, str]:
            return build_passive_reply_text(
                incoming=incoming_text,
                stage=stage,
                client_name=reply_to_name,
                group_name=group_name,
                use_llm=use_llm,
                recent_context=recent_context,
                last_bot_reply=last_bot_outbound,
                session_id=session_id,
                request=request,
            )

        reply_text = ""
        reply_source = "template"
        llm_error = ""
        send_result: dict[str, Any] | None = None
        if not dry_run and auto_reply and group_name and _passive_ui_llm_overlap_enabled():
            send_result, reply_text, reply_source, llm_error = send_passive_reply_overlapped(
                group_name,
                build_reply=_build_this_reply,
            )
        else:
            reply_text, reply_source, llm_error = _build_this_reply()

        if reply_source == "llm":
            llm_used += 1
        elif reply_source == "deterministic":
            llm_used += 1
        elif reply_source == "blocked":
            blocked_count += 1
            if llm_error:
                last_llm_error = llm_error
        else:
            template_used += 1
            if llm_error:
                last_llm_error = llm_error
        entry = {
            "contact_id": item.get("contact_id"),
            "contact_name": group_name,
            "incoming": item.get("text"),
            "reply": reply_text,
            "reply_source": reply_source,
            "llm_error": llm_error,
            "dry_run": dry_run,
            "sent": False,
        }
        msg_key = str(item.get("key") or "")
        stable_key = str(item.get("stable_key") or "")
        reply_ts = float(item.get("timestamp") or 0)
        if (
            not dry_run
            and auto_reply
            and group_name
            and (reply_source == "blocked" or not (reply_text or "").strip())
        ):
            entry["blocked"] = True
            entry["block_reason"] = llm_error or "未生成可发送回复（已拦截，未发到微信）"
            logger.info(
                "被动回复已拦截 群=%s: %s",
                group_name,
                entry["block_reason"],
            )
            cur = cursors.get(str(cid)) or {}
            cur["cooldown_until"] = time.time() + 30
            cursors[str(cid)] = cur
            replies.append(entry)
            continue
        if not dry_run and auto_reply and group_name:
            safe_out, block_reason = _finalize_outbound_reply(
                reply_text,
                incoming=incoming_text,
                client_name=reply_to_name,
            )
            if not safe_out:
                entry["blocked"] = True
                entry["block_reason"] = block_reason
                entry["reply"] = (reply_text or "")[:200]
                logger.warning(
                    "被动回复已拦截 群=%s: %s",
                    group_name,
                    block_reason,
                )
                cur = cursors.get(str(cid)) or {}
                cur["cooldown_until"] = time.time() + 30
                cursors[str(cid)] = cur
                replies.append(entry)
                continue

            reply_text = safe_out
            entry["reply"] = reply_text
            if send_result is None:
                from app.desktop_automation.service import get_desktop_automation_service

                send_result = get_desktop_automation_service().send_wechat_message(
                    group_name, reply_text
                )
            entry["send_result"] = send_result
            entry["sent"] = bool(send_result.get("message_sent") or send_result.get("success"))
            cur = cursors.get(str(cid)) or {}
            if entry["sent"]:
                reply_count += 1
                replied.add(msg_key)
                handled.add(msg_key)
                if stable_key:
                    stable_handled.add(stable_key)
                    replied.add(stable_key)
                cur["last_bot_reply_ts"] = max(float(cur.get("last_bot_reply_ts") or 0), reply_ts)
                cur["cooldown_until"] = time.time() + _PASSIVE_REPLY_COOLDOWN_SEC
                # 一问一答：本轮已回复后，把更早的他人消息一并标记为已处理，避免下轮补发
                for m in service.get_contact_context(cid) or []:
                    if not isinstance(m, dict):
                        continue
                    if _message_ts(m) <= reply_ts:
                        handled.add(_msg_key(m))
                        stable_handled.add(_stable_msg_key(m))
            else:
                # 发送失败也进入短冷却，避免同一秒内连发；不推进 last_ts，下轮可重试
                cur["cooldown_until"] = time.time() + 30
                send_err = str(
                    (send_result or {}).get("error")
                    or (send_result or {}).get("message")
                    or "未知原因"
                )[:120]
                entry["send_error"] = send_err
                logger.warning("被动回复发送失败 群=%s: %s", group_name, send_err)
            cursors[str(cid)] = cur
        elif dry_run:
            reply_count += 1
        replies.append(entry)

    sent_count = sum(1 for r in replies if r.get("sent"))
    preview_count = sum(1 for r in replies if r.get("reply") and not r.get("sent"))
    state["cursors"] = cursors
    state["handled_keys"] = list(handled)[-500:]
    state["replied_keys"] = list(replied)[-500:]
    state["stable_handled_keys"] = list(stable_handled)[-800:]
    state["last_poll_at"] = datetime.now(timezone.utc).isoformat()
    if dry_run:
        src_hint = ""
        if replies:
            rs = str(replies[0].get("reply_source") or "")
            src_hint = f"，预览={rs}" + (f"（{last_llm_error[:40]}）" if last_llm_error else "")
        state["last_poll_message"] = f"新消息 {len(detected)} 条（探测{src_hint}）"
    elif pending_count > 0:
        state["last_poll_message"] = (
            f"新消息 {len(detected)} 条，已回复 {sent_count} 条，待下轮 {pending_count} 条"
        )
    elif sent_count > 0 and llm_used > 0:
        state["last_poll_message"] = (
            f"新消息 {len(detected)} 条，已回复 {sent_count} 条（LLM {llm_used}）"
        )
    elif sent_count > 0 and template_used > 0:
        hint = last_llm_error[:80] if last_llm_error else str(llm_probe.get("message") or "")
        state["last_poll_message"] = (
            f"新消息 {len(detected)} 条，已回复 {sent_count} 条（模板"
            + (f"，LLM 未用: {hint}" if hint else "")
            + "）"
        )
    elif blocked_count > 0 and sent_count == 0 and not dry_run:
        reason = last_llm_error[:100] if last_llm_error else "质量或 LLM 未通过"
        state["last_poll_message"] = (
            f"识别 {len(detected)} 条，已拦截未发送 {blocked_count} 条（{reason}）"
        )
    elif len(detected) > 0 and sent_count == 0 and not dry_run:
        send_err = ""
        if replies:
            send_err = str(
                replies[0].get("send_error")
                or (replies[0].get("send_result") or {}).get("error")
                or ""
            )[:120]
        state["last_poll_message"] = f"识别 {len(detected)} 条待回复，但未能发送到微信" + (
            f"：{send_err}"
            if send_err
            else "（请确认 Mac 微信已打开、群名与列表完全一致、已授权辅助功能）"
        )
    elif len(detected) == 0:
        armed_hint = ""
        try:
            floors = [
                float((cursors.get(k) or {}).get("watch_armed_message_ts") or 0) for k in cursors
            ]
            if any(f > 0 for f in floors):
                armed_hint = "（已重新监听：仅回复对齐时刻之后的新他人消息）"
        except Exception:
            pass
        snap_hint = ""
        if not skip_sync and isinstance(snapshot_result, dict) and snapshot_result.get("success"):
            if snapshot_result.get("rebuilt"):
                snap_hint = "；快照：已复制解密本机微信库"
            elif snapshot_result.get("skipped"):
                snap_hint = "；快照：本机库未变，复用"
        sync_hint = snap_hint + armed_hint
        if isinstance(sync_result, dict):
            if skip_sync:
                latest = str(sync_result.get("latest_message_label") or "")
                pulled_new = int(sync_result.get("messages_pulled_this_round") or 0)
                sync_hint = (
                    snap_hint
                    + (f"；库内最新 {latest}" if latest else "")
                    + (
                        f"；本次新增 {pulled_new} 条"
                        if pulled_new > 0
                        else "；无新增他人待回复消息"
                    )
                )
            elif sync_result.get("stale"):
                reason = str(sync_result.get("stale_reason") or "解密库落后于本机微信")[:56]
                sync_hint = snap_hint + f"；⚠ 库过期：{reason}"
            elif not sync_result.get("message_db_ready", True):
                sync_hint = snap_hint + "；⚠ 未连上微信消息库，请到数据来源配置并解密"
            elif (
                int(
                    sync_result.get("messages_pulled_this_round")
                    or sync_result.get("messages_pulled")
                    or 0
                )
                == 0
            ):
                latest = str(sync_result.get("latest_message_label") or "")
                sync_hint = snap_hint + (
                    f"；⚠ 本轮未入库新消息（库内最新 {latest or '未知'}）"
                    if latest
                    else "；⚠ 本轮未入库新消息"
                )
            elif not sync_result.get("success"):
                sync_hint = snap_hint + f"；同步异常：{str(sync_result.get('message') or '')[:48]}"
            else:
                synced_n = int(sync_result.get("synced") or 0)
                pulled = int(
                    sync_result.get("messages_pulled_this_round")
                    or sync_result.get("messages_pulled")
                    or 0
                )
                latest = str(sync_result.get("latest_message_label") or "")
                sync_hint = snap_hint + f"；本轮入库 {pulled} 条（{synced_n} 群，最新 {latest}）"
        state["last_poll_message"] = (
            f"新消息 0 条（无待回复他人消息；LLM={'就绪' if llm_probe.get('ready') else '未配置'}"
            f"{sync_hint}）"
        )
    else:
        state["last_poll_message"] = f"新消息 {len(detected)} 条，已回复 {sent_count} 条"
    doc["passive_state"] = state
    save_pipeline(doc)

    feed_preview: list[dict[str, Any]] = []
    try:
        from app.services.wechat_group_customer_bridge import build_starred_group_feed

        feed_preview = build_starred_group_feed(limit=20, market_user_id=uid)
    except Exception as exc:
        logger.debug("build_starred_group_feed after passive poll: %s", exc)

    return {
        "success": True,
        "message": state["last_poll_message"],
        "replied_count": sent_count,
        "preview_count": preview_count,
        "detected_count": len(detected),
        "llm_used": llm_used,
        "template_used": template_used,
        "blocked_count": blocked_count,
        "llm_probe": llm_probe,
        "snapshot": snapshot_result,
        "sync": sync_result,
        "messages_pulled_this_round": int(
            sync_result.get("messages_pulled_this_round") or sync_result.get("messages_pulled") or 0
        ),
        "detected": detected,
        "replies": replies,
        "feed": feed_preview,
        "dry_run": dry_run,
    }
