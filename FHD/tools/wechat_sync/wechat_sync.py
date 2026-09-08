"""
微信聊天记录同步代理（本机 → 服务器 → 本机，AI 第一载体基建·本机端）。

SSOT 说明：本目录（FHD/tools/wechat_sync/）是同步代理的唯一受管版本；
FHD/mutants/resources/wechat_cv/ 下的同名脚本为历史沙箱副本（已移除），勿再改动。
wechat_db_read.py 亦从 wechat_cv 复制而来：沙箱内仍被 CV 脚本引用，两处独立维护。

职责：
1. 从微信本地 DB 增量采集联系人消息（wechat_db_read），新消息分配单调 client_seq；
2. POST /api/ops/wechat/ingest 批量上行（token 认证，服务器幂等入库+身份解析）；
3. 响应中的客户情报（context）写回本地 wechat_context_cache.json —— 服务器 AI 智慧回流本机。

运行环境：微信宿主机（Windows）。需要同目录 wechat_db_key.json（wechat_cv/wechat_db_key.json
拷贝即可，含 key_hex 与可选 wechat_data_dir；已被 .gitignore 排除，禁止提交）。

配置优先级：CLI 参数 > 环境变量 > wechat_sync_config.json > 内置默认。
  WECHAT_SYNC_SERVER_URL  默认 http://127.0.0.1:5100；生产 https://xiu-ci.com/fhd-api
  WECHAT_SYNC_TOKEN       必填（AUTONOMY_WEBHOOK_TOKEN / MODSTORE_OPS_INGEST_TOKEN 同源）
  WECHAT_SYNC_TENANT_ID   可选
  WECHAT_SYNC_INTERVAL    循环间隔秒（默认 300）
  WECHAT_SYNC_LIMIT       每联系人每轮最多拉取条数（默认 50）
配置文件：同目录 wechat_sync_config.json（键：server_url/token/tenant_id/interval/limit/contacts/log_file），
样例见 wechat_sync_config.json.example；该文件含 token，已被 .gitignore 排除，禁止提交。
状态文件：本目录 wechat_sync_state.json（仅 POST 成功后落盘，失败不推进游标）。
自动运行：Windows 用 wechat_sync_start.bat（崩溃自拉起）+ wechat_sync_install_task.ps1（登录自启计划任务）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# 守护进程隔离边界：同步代理必须活着，任何异常都不能杀死 loop（具名元组过 broad-except gate）
_GUARD_ERRORS: tuple[type[Exception], ...] = (Exception,)

STATE_PATH = os.path.join(_here, "wechat_sync_state.json")
CONTEXT_CACHE_PATH = os.path.join(_here, "wechat_context_cache.json")
CONFIG_PATH = os.path.join(_here, "wechat_sync_config.json")
DEFAULT_SERVER_URL = "http://127.0.0.1:5100"
DEFAULT_LOG_PATH = os.path.join(_here, "wechat_sync.log")
_LOG_MAX_BYTES = 5 * 1024 * 1024
_SEEN_CAP = 5000


def load_config() -> dict[str, Any]:
    """读取同目录 wechat_sync_config.json（可选；损坏/缺失一律视为空配置）。"""
    if not os.path.isfile(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _append_log(line: str, log_path: str) -> None:
    """追加一行到日志文件；超 5MB 滚动一次（.1），失败静默（日志不能拖垮同步）。"""
    try:
        if os.path.isfile(log_path) and os.path.getsize(log_path) > _LOG_MAX_BYTES:
            os.replace(log_path, log_path + ".1")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {line}\n")
    except OSError:
        pass


def _load_state() -> dict[str, Any]:
    if os.path.isfile(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def _extract_contact_names(list_out: Any) -> list[str]:
    """容忍 get_contact_list_from_db 的多种返回形状，抽联系人名列表。"""
    if not isinstance(list_out, dict) or not list_out.get("success"):
        return []
    for key in ("contacts", "rows", "items"):
        value = list_out.get(key)
        if isinstance(value, list):
            names: list[str] = []
            for item in value:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = (
                        item.get("remark")
                        or item.get("Remark")
                        or item.get("nickName")
                        or item.get("nickname")
                        or item.get("name")
                        or item.get("display_name")
                        or item.get("userName")
                        or ""
                    )
                    if name:
                        names.append(str(name))
            return names
    return []


def _collect_payload(
    contact_filter: list[str] | None,
    limit: int,
    tenant_id: int | None,
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """采集本批上行 payload；返回 (payload|None, new_state)。不落盘。"""
    from wechat_db_read import (
        get_contact_and_messages_from_db,
        get_contact_list_from_db,
        get_default_wechat_data_dir,
    )

    data_dir = get_default_wechat_data_dir() or (
        r"C:\xwechat_files" if os.path.isdir(r"C:\xwechat_files") else None
    )
    names = _extract_contact_names(get_contact_list_from_db(wechat_data_dir=data_dir))
    if contact_filter:
        wanted = {n for n in contact_filter}
        names = [n for n in names if n in wanted] + [n for n in contact_filter if n not in names]

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    contacts_payload: list[dict[str, Any]] = []
    messages_payload: list[dict[str, Any]] = []
    new_state = json.loads(json.dumps(state, ensure_ascii=False))

    for name in names:
        entry = state.get(name) or {"seen": {}, "next_seq": 1}
        seen: dict[str, int] = dict(entry.get("seen") or {})
        next_seq = int(entry.get("next_seq") or 1)
        out = get_contact_and_messages_from_db(
            name, wechat_data_dir=data_dir, limit=limit, only_other=False
        )
        if not out.get("success"):
            continue
        messages = out.get("messages") or []
        # DB 按时间倒序返回；先转时间正序，保证 client_seq 随对话推进单调递增
        chronological = list(reversed(messages))
        fresh = 0
        for msg in chronological:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "other")
            content = str(msg.get("text") or msg.get("content") or "").strip()
            if not content:
                continue
            raw_ts = msg.get("ts")
            if isinstance(raw_ts, (int, float)) and raw_ts > 0:
                ts_val = float(raw_ts)
                if ts_val > 1e12:
                    ts_val = ts_val / 1000.0
                msg_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts_val))
            else:
                msg_iso = now_iso
            # 去重锚定真实消息时间（无 ts 退化为内容指纹），同文重复消息不再互相吞掉
            key = f"{role}|{msg_iso}|{content}" if raw_ts else f"{role}|{content}"
            if key in seen:
                continue
            seen[key] = next_seq
            messages_payload.append(
                {
                    "contact_key": name,
                    "role": "self" if role == "self" else "other",
                    "content": content,
                    "client_seq": next_seq,
                    "msg_ts": msg_iso,
                    "source": "db",
                }
            )
            next_seq += 1
            fresh += 1
        if fresh or name not in state:
            contacts_payload.append({"contact_key": name, "display_name": name})
        # 截断 seen，防止无限膨胀
        if len(seen) > _SEEN_CAP:
            kept = sorted(seen.items(), key=lambda kv: kv[1])[-_SEEN_CAP:]
            seen = dict(kept)
        new_state[name] = {"seen": seen, "next_seq": next_seq}

    if not contacts_payload and not messages_payload:
        return None, new_state
    payload: dict[str, Any] = {"contacts": contacts_payload, "messages": messages_payload}
    if tenant_id:
        payload["tenant_id"] = tenant_id
    return payload, new_state


def _post_json(url: str, token: str, body: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url.rstrip("/") + "/api/ops/wechat/ingest",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sync_once(
    *,
    server_url: str,
    token: str,
    contact_filter: list[str] | None = None,
    limit: int = 50,
    tenant_id: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """单轮同步：采集 → 上行 → 回流写缓存。返回结果摘要。"""
    state = _load_state()
    payload, new_state = _collect_payload(contact_filter, limit, tenant_id, state)
    if payload is None:
        return {"success": True, "skipped": True, "message": "无新消息"}
    if dry_run:
        preview = json.dumps(payload, ensure_ascii=False)
        return {"success": True, "dry_run": True, "preview": preview[:1200]}

    result = _post_json(server_url, token, payload)
    if not result.get("success"):
        return {"success": False, "message": str(result.get("message") or "ingest failed")}
    # 上行成功才推进游标
    _save_state(new_state)
    context = result.get("context") or {}
    cache = {
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "server": server_url,
        "context": context,
    }
    tmp = CONTEXT_CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONTEXT_CACHE_PATH)
    return {
        "success": True,
        "contacts": result.get("contacts_upserted"),
        "inserted": result.get("messages_inserted"),
        "skipped": result.get("messages_skipped"),
        "context_cache": CONTEXT_CACHE_PATH,
    }


def _resolve_settings(args: argparse.Namespace) -> dict[str, Any]:
    """配置优先级：CLI 参数 > 环境变量 > wechat_sync_config.json > 内置默认。"""
    cfg = load_config()

    def pick(cli_value: Any, env_name: str, cfg_key: str, default: Any) -> Any:
        if cli_value not in (None, ""):
            return cli_value
        env_value = str(os.environ.get(env_name, "") or "").strip()
        if env_value:
            return env_value
        cfg_value = cfg.get(cfg_key)
        if cfg_value not in (None, ""):
            return cfg_value
        return default

    server_url = str(pick(None, "WECHAT_SYNC_SERVER_URL", "server_url", DEFAULT_SERVER_URL)).strip()
    token = str(pick(None, "WECHAT_SYNC_TOKEN", "token", "")).strip()
    interval = pick(args.interval, "WECHAT_SYNC_INTERVAL", "interval", 300)
    try:
        interval = max(30, int(interval))
    except (TypeError, ValueError):
        interval = 300
    limit = pick(args.limit, "WECHAT_SYNC_LIMIT", "limit", 50)
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 50
    tenant_raw = str(pick(None, "WECHAT_SYNC_TENANT_ID", "tenant_id", "")).strip()
    tenant_id = int(tenant_raw) if tenant_raw.isdigit() else None
    contacts_cfg = cfg.get("contacts")
    cli_contacts = list(args.contact or [])
    cfg_contacts = (
        [str(c).strip() for c in contacts_cfg if str(c).strip()]
        if isinstance(contacts_cfg, list)
        else []
    )
    contact_filter = cli_contacts or cfg_contacts or None
    log_path = str(pick(args.log_file, "WECHAT_SYNC_LOG_FILE", "log_file", "") or "").strip()
    return {
        "server_url": server_url,
        "token": token,
        "tenant_id": tenant_id,
        "interval": interval,
        "limit": limit,
        "contact_filter": contact_filter,
        "log_path": log_path,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="微信聊天记录同步代理（本机→服务器→本机）")
    ap.add_argument("--loop", action="store_true", help="守护模式循环同步")
    ap.add_argument("--interval", type=int, default=None, help="循环间隔秒数（默认 300）")
    ap.add_argument("--contact", action="append", default=None, help="仅同步指定联系人（可多次）")
    ap.add_argument("--limit", type=int, default=None, help="每联系人每轮最多拉取条数")
    ap.add_argument("--dry-run", action="store_true", help="只打印 payload 不上行")
    ap.add_argument("--list", action="store_true", help="仅列联系人")
    ap.add_argument(
        "--log-file", default=None, help="追加运行日志到该文件（loop 模式默认 wechat_sync.log）"
    )
    args = ap.parse_args()

    settings = _resolve_settings(args)
    server_url = settings["server_url"]
    token = settings["token"]
    tenant_id = settings["tenant_id"]
    log_path = settings["log_path"]

    if args.list:
        from wechat_db_read import get_contact_list_from_db, get_default_wechat_data_dir

        data_dir = get_default_wechat_data_dir() or (
            r"C:\xwechat_files" if os.path.isdir(r"C:\xwechat_files") else None
        )
        print(
            json.dumps(
                get_contact_list_from_db(wechat_data_dir=data_dir), ensure_ascii=False, indent=2
            )
        )
        return 0

    if not args.dry_run and not token:
        print(
            json.dumps(
                {
                    "success": False,
                    "message": "缺少 WECHAT_SYNC_TOKEN（环境变量或 wechat_sync_config.json token 键）",
                },
                ensure_ascii=False,
            )
        )
        return 1

    out: dict[str, Any] = {"success": False, "message": "not run"}
    while True:
        try:
            out = sync_once(
                server_url=server_url,
                token=token,
                contact_filter=settings["contact_filter"],
                limit=settings["limit"],
                tenant_id=tenant_id,
                dry_run=args.dry_run,
            )
            line = json.dumps(out, ensure_ascii=False)
        except _GUARD_ERRORS as exc:  # 守护模式必须活着（进程隔离边界）
            out = {"success": False, "message": str(exc)}
            line = json.dumps(out, ensure_ascii=False)
        print(line)
        # 自动运行模式（loop）默认落盘日志，便于无人值守排障
        if args.loop and log_path and not args.dry_run:
            _append_log(line, log_path)
        if not args.loop:
            return 0 if out.get("success") else 1
        time.sleep(settings["interval"])


if __name__ == "__main__":
    sys.exit(main())
