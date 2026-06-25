"""发版闭环 ⑤：经 GitHub ``workflow_dispatch`` 触发真实 CI 构建（签名密钥留 CI）。

发版员的"真手"：调 GitHub Actions API 触发 ``fhd-release-{platform}.yml``，轮询 run 直至
结束。modstore 服务器只持触发用 token（``actions:write``），不碰 keystore/签名证书。

HTTP 经构造函数注入（``http_post`` / ``http_get`` / ``sleep``）以便单测；生产默认用 httpx
+ ``GITHUB_DISPATCH_TOKEN``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

WORKFLOW_BY_PLATFORM: Dict[str, str] = {
    "android": "fhd-release-android.yml",
    "harmony": "fhd-release-harmony.yml",
    "ios": "fhd-release-ios.yml",
}

_API = "https://api.github.com"


@dataclass
class DispatchResult:
    ok: bool
    workflow: str
    ref: str
    run_id: Optional[str] = None
    run_url: str = ""
    conclusion: Optional[str] = None
    error: str = ""


HttpFn = Callable[..., Dict[str, Any]]


def _default_http_post(
    url: str, *, json_body: Dict[str, Any], headers: Dict[str, str]
) -> Dict[str, Any]:
    import httpx

    r = httpx.post(url, json=json_body, headers=headers, timeout=30.0)
    body: Dict[str, Any] = {}
    try:
        body = r.json() if r.content else {}
    except Exception:  # noqa: BLE001
        body = {}
    return {"status": r.status_code, "json": body}


def _default_http_get(url: str, *, headers: Dict[str, str]) -> Dict[str, Any]:
    import httpx

    r = httpx.get(url, headers=headers, timeout=30.0)
    body: Dict[str, Any] = {}
    try:
        body = r.json() if r.content else {}
    except Exception:  # noqa: BLE001
        body = {}
    return {"status": r.status_code, "json": body}


class CiDispatcher:
    def __init__(
        self,
        repo: str,
        token: str = "",
        *,
        http_post: Optional[HttpFn] = None,
        http_get: Optional[HttpFn] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.repo = (repo or "").strip()
        self.token = (token or os.environ.get("GITHUB_DISPATCH_TOKEN", "")).strip()
        self._post = http_post or _default_http_post
        self._get = http_get or _default_http_get
        if sleep is not None:
            self._sleep = sleep
        else:
            import time

            self._sleep = time.sleep

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def dispatch(self, workflow: str, ref: str, inputs: Dict[str, Any]) -> DispatchResult:
        if not self.repo:
            return DispatchResult(False, workflow, ref, error="repo 未配置")
        url = f"{_API}/repos/{self.repo}/actions/workflows/{workflow}/dispatches"
        try:
            resp = self._post(
                url, json_body={"ref": ref, "inputs": inputs}, headers=self._headers()
            )
        except Exception as e:  # noqa: BLE001
            return DispatchResult(False, workflow, ref, error=f"dispatch 异常：{str(e)[:200]}")
        status = int(resp.get("status") or 0)
        if status != 204:
            msg = str((resp.get("json") or {}).get("message") or f"HTTP {status}")
            return DispatchResult(False, workflow, ref, error=f"dispatch 失败：{msg}")
        return DispatchResult(True, workflow, ref)

    def latest_run(self, workflow: str, ref: str) -> Dict[str, Any]:
        url = (
            f"{_API}/repos/{self.repo}/actions/workflows/{workflow}/runs"
            f"?branch={ref}&event=workflow_dispatch&per_page=1"
        )
        resp = self._get(url, headers=self._headers())
        runs = ((resp.get("json") or {}).get("workflow_runs")) or []
        return runs[0] if runs else {}

    def trigger_and_wait(
        self,
        workflow: str,
        ref: str,
        inputs: Dict[str, Any],
        *,
        max_polls: int = 60,
        poll_interval: float = 10.0,
    ) -> DispatchResult:
        """触发 + 轮询直至 run 结束。返回 ok（conclusion==success）与 run 信息。"""
        d = self.dispatch(workflow, ref, inputs)
        if not d.ok:
            return d
        for _ in range(max_polls):
            run = self.latest_run(workflow, ref)
            run_id = str(run.get("id") or "") or None
            status = str(run.get("status") or "")
            conclusion = run.get("conclusion")
            if status == "completed":
                ok = conclusion == "success"
                return DispatchResult(
                    ok=ok,
                    workflow=workflow,
                    ref=ref,
                    run_id=run_id,
                    run_url=str(run.get("html_url") or ""),
                    conclusion=str(conclusion or ""),
                    error="" if ok else f"CI 结论 {conclusion}",
                )
            self._sleep(poll_interval)
        return DispatchResult(False, workflow, ref, error="轮询超时：CI 未在限定次数内结束")


def dispatcher_for(
    platform: str,
    repo: str = "",
    **kwargs: Any,
) -> "CiDispatcher":
    return CiDispatcher(repo or os.environ.get("GITHUB_REPOSITORY", ""), **kwargs)


def workflow_for(platform: str) -> str:
    return WORKFLOW_BY_PLATFORM.get((platform or "").strip().lower(), "")
