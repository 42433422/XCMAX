#!/usr/bin/env python3
"""
P0 联调：员工直调、工作流沙盒（真实员工）、工作流正式执行。

环境变量（任选其一拿 token）：
  MODSTORE_TOKEN / ACCESS_TOKEN / MODSTORE_ACCESS_TOKEN
或密码登录：
  MODSTORE_USERNAME + MODSTORE_PASSWORD

可选覆盖：
  MODSTORE_BASE_URL   默认 http://127.0.0.1:8765
  MODSTORE_EMPLOYEE_ID
  MODSTORE_WORKFLOW_ID

未指定 employee/workflow 时，会调用列表接口自动选第一个；
若指定了 employee，会优先用 /api/workflow/by-employee 找关联工作流。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _env_token() -> str:
    for k in ("MODSTORE_TOKEN", "ACCESS_TOKEN", "MODSTORE_ACCESS_TOKEN"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    p = (os.environ.get("MODSTORE_TOKEN_FILE") or "").strip()
    if p:
        try:
            return Path_read(p).strip()
        except OSError:
            pass
    return ""


def Path_read(path: str) -> str:
    from pathlib import Path

    return Path(path).expanduser().read_text(encoding="utf-8")


def login(base: str, username: str, password: str) -> str:
    r = httpx.post(
        f"{base.rstrip('/')}/api/auth/login",
        json={"username": username, "password": password},
        timeout=60.0,
        trust_env=False,
    )
    r.raise_for_status()
    data = r.json()
    tok = (data.get("access_token") or "").strip()
    if not tok:
        raise RuntimeError(f"login ok but no access_token: {data}")
    return tok


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(client: httpx.Client, path: str) -> Any:
    r = client.get(path, timeout=120.0)
    r.raise_for_status()
    return r.json()


def post_json(client: httpx.Client, path: str, body: Optional[Dict[str, Any]] = None) -> httpx.Response:
    return client.post(path, json=body or {}, timeout=180.0)


def pick_employee_id(client: httpx.Client, explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    rows = get_json(client, "/api/employees/")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("未指定 MODSTORE_EMPLOYEE_ID 且 /api/employees/ 为空")
    eid = str(rows[0].get("id") or "").strip()
    if not eid:
        raise RuntimeError(f"员工列表首条无 id: {rows[0]!r}")
    return eid


def pick_workflow_id(
    client: httpx.Client, employee_id: str, explicit: str
) -> int:
    if explicit.strip():
        return int(explicit.strip())
    from urllib.parse import quote

    data = get_json(client, f"/api/workflow/by-employee?employee_id={quote(employee_id, safe='')}")
    wfs = data.get("workflows") if isinstance(data, dict) else None
    if isinstance(wfs, list) and wfs:
        return int(wfs[0]["id"])
    lst = get_json(client, "/api/workflow/")
    if not isinstance(lst, list) or not lst:
        raise RuntimeError("未指定 MODSTORE_WORKFLOW_ID 且工作流列表为空")
    # 优先 is_active
    for w in lst:
        if w.get("is_active"):
            return int(w["id"])
    return int(lst[0]["id"])


def main() -> int:
    ap = argparse.ArgumentParser(description="P0 API smoke: employee + workflow sandbox + execute")
    ap.add_argument("--base-url", default=os.environ.get("MODSTORE_BASE_URL", "http://127.0.0.1:8765"))
    ap.add_argument("--token", default=_env_token(), help="Bearer access token")
    ap.add_argument(
        "--mint-user-id",
        type=int,
        default=int(os.environ.get("MODSTORE_MINT_USER_ID", "0") or 0),
        help="若未提供 token：用服务端 JWT 规则签发（仅本地 dev-secret 场景）",
    )
    ap.add_argument(
        "--mint-username",
        default=os.environ.get("MODSTORE_MINT_USERNAME", "testuser").strip(),
        help="与 mint-user-id 一起用于 create_access_token",
    )
    ap.add_argument("--username", default=os.environ.get("MODSTORE_USERNAME", "").strip())
    ap.add_argument("--password", default=os.environ.get("MODSTORE_PASSWORD", "").strip())
    ap.add_argument("--employee-id", default=os.environ.get("MODSTORE_EMPLOYEE_ID", "").strip())
    ap.add_argument("--workflow-id", default=os.environ.get("MODSTORE_WORKFLOW_ID", "").strip())
    ap.add_argument("--task", default="smoke", help="员工任务名")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    token = (args.token or "").strip()
    if not token and args.mint_user_id > 0:
        from modstore_server.auth_service import create_access_token

        token = create_access_token(args.mint_user_id, args.mint_username or "user")
    if not token and args.username and args.password:
        token = login(base, args.username, args.password)
    if not token:
        print(
            "缺少 token：请设置 MODSTORE_TOKEN（或 ACCESS_TOKEN），"
            "或设置 MODSTORE_USERNAME + MODSTORE_PASSWORD",
            file=sys.stderr,
        )
        return 2

    out: Dict[str, Any] = {"base_url": base, "paths": {}}

    with httpx.Client(
        base_url=base,
        headers=auth_headers(token),
        trust_env=False,
    ) as client:
        employee_id = pick_employee_id(client, args.employee_id)
        workflow_id = pick_workflow_id(client, employee_id, args.workflow_id)
        out["resolved"] = {"employee_id": employee_id, "workflow_id": workflow_id}

        # 1) 员工直调
        r1 = client.post(
            f"/api/employees/{employee_id}/execute",
            params={"task": args.task},
            json={"message": "p0 smoke", "source": "p0_api_smoke"},
            timeout=180.0,
        )
        out["paths"]["employee_execute"] = {
            "status_code": r1.status_code,
            "body": _safe_json(r1),
        }
        r1.raise_for_status()

        # 2) 沙盒（真实员工）
        r2 = post_json(
            client,
            f"/api/workflow/{workflow_id}/sandbox-run",
            {
                "input_data": {"message": "sandbox", "employee_hint": employee_id},
                "mock_employees": False,
                "validate_only": False,
            },
        )
        out["paths"]["workflow_sandbox_run"] = {
            "status_code": r2.status_code,
            "body": _safe_json(r2),
        }
        if r2.status_code >= 400:
            out["paths"]["workflow_sandbox_run"]["note"] = (
                "沙盒失败常见于图校验错误、或员工节点配置缺失；仍继续尝试正式执行。"
            )

        # 3) 正式执行（需 is_active）
        r3 = post_json(
            client,
            f"/api/workflow/{workflow_id}/execute",
            {"input_data": {"message": "execute", "employee_hint": employee_id}},
        )
        out["paths"]["workflow_execute"] = {
            "status_code": r3.status_code,
            "body": _safe_json(r3),
        }

    # Windows 控制台常见 GBK，避免 LLM 输出中的非 BMP 字符导致打印失败
    print(json.dumps(out, ensure_ascii=True, indent=2))
    # 若员工成功而后两条失败，仍返回 1 便于 CI
    if out["paths"]["employee_execute"]["status_code"] >= 400:
        return 1
    if out["paths"]["workflow_sandbox_run"]["status_code"] >= 400 and out["paths"]["workflow_execute"][
        "status_code"
    ] >= 400:
        return 1
    return 0


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return {"text": r.text[:4000]}


if __name__ == "__main__":
    raise SystemExit(main())
