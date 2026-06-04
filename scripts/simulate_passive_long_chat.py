#!/usr/bin/env python3
"""
模拟微信群长对话 → 写入 context（可 1000 条）→ 单次 LLM → 真发 1 条到微信。

  cd FHD && XCAGI_DATA_DIR=.../desktop-dev XCAGI_DESKTOP_MODE=1 \\
    .venv/bin/python3 scripts/simulate_passive_long_chat.py --turns 1000 --wechat-send

  须双开关 --wechat-send --confirm-send；仅发 1 条 [长聊自测] 前缀消息。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SELF_TEST_PREFIX = "[长聊自测] "


def _bootstrap_desktop(data_dir: str) -> None:
    os.environ.setdefault("XCAGI_DATA_DIR", data_dir)
    os.environ.setdefault("XCAGI_DESKTOP_MODE", "1")
    from app.desktop_runtime.paths import configure_desktop_environment

    configure_desktop_environment(data_dir)


def _long_chat_transcript_core() -> list[tuple[str, str]]:
    return [
        ("self", "各位好，我是修茈科技在群里的客服助理，后续需求与报价都在本群沟通。"),
        ("other", "你好，我们是做连锁奶茶门店的"),
        ("self", "收到，连锁门店场景我们做过多套收银+进销存，您目前几家店？"),
        ("other", "现在8家，计划明年扩到15家"),
        ("self", "明白。核心是统一配方、原料预警，还是会员营销？"),
        ("other", "配方总部下发、门店要简单执行；库存要能按店看"),
        ("other", "另外会员想打通小程序，现在用表格太乱"),
        ("self", "可以：总部配方库+门店执行清单；库存按店维度；会员走小程序对接。"),
        ("other", "有没有类似案例？发我看看"),
        ("self", "有餐饮连锁案例（脱敏版），我整理一页要点发您。"),
        ("other", "预算还没完全定，你们大概什么量级"),
        ("self", "按8店、配方+库存+会员三模块，常见区间在12～25万，看是否要定制报表。"),
        ("other", "25万有点高，15万能覆盖吗"),
        ("self", "15万可做标准版：配方+库存+基础会员；复杂报表和第三方对接需另议。"),
        ("other", "第三方要对接企业微信审批和现有金蝶"),
        ("self", "金蝶有标准接口，企微审批可做轻量流程；这两项建议单独立项评估人天。"),
        ("other", "那先按15万标准版出方案，审批和金蝶你们给个增项报价"),
        ("self", "好的，我按15万标准版+两项增项拆分，今晚前发您文档目录。"),
        ("other", "文档里写清楚交付周期，我们希望6周内上线试点店"),
        ("self", "6周试点可行：前2周需求确认，中3周开发联调，最后1周两店试点。"),
        ("other", "试点选成都两家旗舰店。对了，上次发的PPT作业里活动页那几页也要并进方案"),
        ("self", "收到，活动页需求会并进方案第三章，和会员模块放一起说明。"),
        ("other", "你们是谁家的？群里好几个助理，我想确认下主体"),
        ("self", "我们是成都修茈科技，本群由修茈科技客服统一对接。"),
        ("other", "好。那15万方案今晚发，另外增项大概多少先说个数"),
        ("self", "增项粗算：金蝶对接约2～3万、企微审批约1～2万，最终以评估表为准。"),
        ("other", "可以。我下午开会，晚上8点前要能打开方案链接"),
        ("self", "没问题，我8点前发您在线文档链接，并@您确认收悉。"),
        ("other", "还有：培训要含店长和店员两套，别只给IT看"),
        ("self", "会附店长操作手册+店员速查，培训议程也分两档。"),
        ("other", "最后确认下：若下周只能先上4家店，费用能按店数折算吗"),
        ("other", "按15万先出合同草案吧，付款想三七开，验收后付尾款"),
    ]


_FILLER_OTHER = (
    "门店{shop}的库存预警阈值能按品类设吗",
    "会员小程序要和企微审批打通",
    "配方变更后门店旧料怎么处理",
    "报表能否导出Excel给财务",
    "试点店店长账号怎么开通",
    "增项评估表大概什么时候能给",
    "合同里保密条款按你们模板可以吗",
    "付款发票开专票还是普票",
)
_FILLER_SELF = (
    "收到，这点写进方案对应章节",
    "可以，试点阶段先按您说的配置",
    "我让同事把脱敏案例链接发您",
    "评估表今晚一并放进文档目录",
    "合同草案里会单列交付与验收条款",
    "专票没问题，开票信息您群里发我",
    "保密条款可用双方模板，法务可对一版",
    "门店折算规则我在合同附表里写清",
)


def build_transcript(turns: int) -> list[tuple[str, str]]:
    core = _long_chat_transcript_core()
    n = max(2, int(turns))
    if n <= len(core):
        return core[:n]
    head = core[:-2]
    tail = core[-2:]
    need = n - len(head) - len(tail)
    fillers: list[tuple[str, str]] = []
    for i in range(need):
        shop = 2 + (i % 11)
        if i % 2 == 0:
            fillers.append(("other", _FILLER_OTHER[i % len(_FILLER_OTHER)].format(shop=shop)))
        else:
            fillers.append(("self", _FILLER_SELF[i % len(_FILLER_SELF)]))
    return head + fillers + tail


def _build_messages(transcript: list[tuple[str, str]], *, base_ts: float) -> list[dict]:
    out: list[dict] = []
    for i, (role, text) in enumerate(transcript):
        ts = base_ts + i * 45.0
        out.append(
            {
                "role": role,
                "text": text,
                "timestamp": ts,
                "create_time": ts,
                "sender": "wxid_sim_customer" if role == "other" else "self",
                "sender_display": "模拟客户" if role == "other" else "我",
            }
        )
    return out


def _send_one_group_message(group_name: str, text: str) -> dict:
    from app.desktop_automation.service import get_desktop_automation_service

    outbound = f"{_SELF_TEST_PREFIX}{text}".strip()
    return get_desktop_automation_service().send_wechat_message(group_name, outbound)


def _validate_context_roundtrip(svc, cid: int, expected: int) -> str | None:
    loaded = svc.get_contact_context(cid) or []
    if len(loaded) != expected:
        return f"读写条数不一致：写入 {expected}，读出 {len(loaded)}"
    from app.services.wechat_passive_group_monitor import (
        _passive_recent_context_char_limit,
        build_passive_recent_context_from_messages,
    )

    try:
        ctx, last_bot = build_passive_recent_context_from_messages(
            loaded, group_name="测试专属", exclude_last_incoming=True
        )
    except Exception as exc:
        return f"构造 {expected} 条上下文异常: {exc}"
    cap = _passive_recent_context_char_limit()
    if len(ctx) > cap:
        return f"上下文超长 {len(ctx)} > {cap}"
    if not last_bot:
        return "未解析到上一条己方消息"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="长群聊模拟 + 微信真发 1 条")
    parser.add_argument("--data-dir", default=str(ROOT / "XCAGI" / "data" / "desktop-dev"))
    parser.add_argument("--turns", type=int, default=1000)
    parser.add_argument("--offline", action="store_true", help="不写 DB（仅本地测 LLM）")
    parser.add_argument("--market-user-id", type=int, default=29)
    parser.add_argument("--contact-id", type=int, default=2707)
    parser.add_argument("--group-name", default="测试专属")
    parser.add_argument(
        "--wechat-send",
        action="store_true",
        help="写入 DB 后向微信群真发 1 条（须 --confirm-send）",
    )
    parser.add_argument("--confirm-send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-deterministic-fallback",
        action="store_true",
        help="LLM 失败时允许合同确定性兜底（默认仅 llm 可发）",
    )
    args = parser.parse_args()

    if args.wechat_send and not args.confirm_send:
        print("须同时 --wechat-send --confirm-send", file=sys.stderr)
        return 2
    if args.wechat_send:
        args.offline = False

    _bootstrap_desktop(args.data_dir)

    from app.db.init_db import ensure_wechat_contact_tables_for_active_db
    from app.application import get_wechat_contact_app_service
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline
    from app.services.wechat_passive_group_monitor import (
        _collect_passive_reply_quality_issues,
        _load_passive_state,
        _passive_recent_context_char_limit,
        build_passive_recent_context_from_messages,
        build_passive_reply_text,
    )

    ensure_wechat_contact_tables_for_active_db()

    uid = int(args.market_user_id)
    cid = int(args.contact_id)
    group = str(args.group_name)
    turns = max(2, int(args.turns))

    transcript = build_transcript(turns)
    messages = _build_messages(transcript, base_ts=time.time() - len(transcript) * 60.0)

    svc = get_wechat_contact_app_service()
    wechat_id = "54122446504@chatroom"
    for c in svc.get_contacts(keyword=group, contact_type="group", limit=5):
        if c.get("contact_name") == group or c.get("id") == cid:
            wechat_id = str(c.get("wechat_id") or wechat_id)
            break

    if not args.offline:
        if not svc.save_contact_context(cid, wechat_id, messages):
            print("save_contact_context 返回失败", file=sys.stderr)
            return 1
        err = _validate_context_roundtrip(svc, cid, len(messages))
        if err:
            print(f"1000 条校验失败: {err}", file=sys.stderr)
            return 1
        print(f"已写入并校验 {len(messages)} 条 wechat_contact_context")

    recent_context, last_self = build_passive_recent_context_from_messages(
        messages, group_name=group, exclude_last_incoming=True
    )
    ctx_cap = _passive_recent_context_char_limit()
    ctx_lines = [ln for ln in recent_context.split("\n") if ln]

    print(f"群={group} 条数={len(messages)} 上下文={len(ctx_lines)}行/{len(recent_context)}字 cap={ctx_cap}")

    doc = load_pipeline(uid)
    state = _load_passive_state(doc)
    penultimate_ts = float(messages[-2]["timestamp"])
    state["cursors"] = {
        str(cid): {
            "last_ts": penultimate_ts,
            "last_bot_reply_ts": penultimate_ts,
            "bootstrapped": True,
            "cooldown_until": 0.0,
            "watch_armed_message_ts": penultimate_ts,
        }
    }
    state["handled_keys"] = []
    state["replied_keys"] = []
    state["stable_handled_keys"] = []
    state["last_poll_message"] = f"长聊 {turns} 条自测"
    doc["passive_state"] = state
    save_pipeline(doc)

    incoming = str(messages[-1].get("text") or "")
    print("\n待回复:", incoming)

    want_send = bool(args.wechat_send and args.confirm_send and not args.dry_run)
    max_attempts = 6 if want_send else 1
    reply, src, err = "", "blocked", ""
    send_blockers: list[str] = []

    print("\n=== LLM ===")
    t0 = time.time()
    for attempt in range(1, max_attempts + 1):
        reply, src, err = build_passive_reply_text(
            incoming=incoming,
            stage=str(doc.get("stage") or "negotiating"),
            client_name="模拟客户",
            group_name=group,
            use_llm=True,
            recent_context=recent_context,
            last_bot_reply=last_self,
        )
        send_blockers = []
        if reply and incoming:
            send_blockers = _collect_passive_reply_quality_issues(
                reply, incoming=incoming, last_bot_reply=last_self
            )
        llm_only = not args.allow_deterministic_fallback
        source_ok = src == "llm" or (src == "deterministic" and not llm_only)
        if reply and source_ok and not send_blockers:
            print(f"  第{attempt}次可发 source={src}")
            break
        if want_send and attempt < max_attempts:
            print(f"  第{attempt}次跳过: src={src} {send_blockers or err}")
    print(f"耗时 {time.time()-t0:.1f}s\nreply: {reply}")

    report: dict = {
        "turns": turns,
        "context_lines": len(ctx_lines),
        "context_chars": len(recent_context),
        "source": src,
        "reply": reply,
        "sent": False,
    }

    llm_only = not args.allow_deterministic_fallback
    source_ok = src == "llm" or (src == "deterministic" and not llm_only)
    if want_send and reply and source_ok and not send_blockers:
        print("\n=== 微信发送 ===")
        send_out = _send_one_group_message(group, reply)
        report["sent"] = bool(
            send_out.get("success")
            or send_out.get("message_sent")
            or send_out.get("ok")
        )
        report["send_result"] = send_out
        print(json.dumps(send_out, ensure_ascii=False, indent=2))
        if not report["sent"]:
            print("微信发送失败", file=sys.stderr)
            return 1
    elif want_send:
        print("未发送：质量门未通过", file=sys.stderr)
        return 1

    print("\n" + json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if reply else 1


if __name__ == "__main__":
    raise SystemExit(main())
