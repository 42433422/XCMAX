from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


DEFAULT_PAIBI_API_URL = "http://127.0.0.1:3001"
PAIBI_SUPPORTED_TOOLS = ("codex", "cursor", "trae", "claude_code")
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".toml", ".yml", ".yaml", ".json"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache"}
GENERATED_EVIDENCE_FILES = {"retort_external_review_report.json", "retort_absorption_log.md", "absorbed_external_patterns.py", "retort_absorbed_patterns.py"}
RETORT_SCORE_DIMENSIONS = (
    "product_level",
    "architecture_depth",
    "test_gate_evidence",
    "api_contract_quality",
    "operational_readiness",
    "evolution_readiness",
    "external_ingestion",
    "comparative_analysis_depth",
    "absorption_tasking",
    "employee_execution_integration",
    "feedback_loop_closure",
    "product_operability",
    "safety_license_gate",
    "branch_absorption_workflow",
    "retort_product_maturity",
    "evidence_loop_score",
    "capability_absorption_score",
    "calibrated_overall",
)
RETORT_LLM_SCORING_RUBRIC = """Retort LLM 评分必须区分“证据闭环”和“能力吸收”，不能把证据文件完整度当成产品能力：
- 你必须直接给每个维度 0-100 分，并给出可验证理由。
- 重点评估深度，不用功能数量堆高分。
- UI、按钮、关键词、文件存在只能证明“有入口”，不能证明“闭环完成”。
- lint/test 通过可以提高 test_gate_evidence 和 operational_readiness，但不能单独把产品级推到 90+。
- 没有 branch diff、员工执行结果、post-absorption tests、merge、外部优势复评五类证据时，calibrated_overall 不得超过 82。
- 没有员工真实执行证据时，employee_execution_integration 不得超过 78。
- 没有吸收后复评和反馈回灌证据时，feedback_loop_closure 不得超过 82。
- 没有真实外部项目吸收、分支落地、合并或回滚证据时，product_level 和 retort_product_maturity 不得超过 84。
- 如果吸收 diff 主要是报告、日志、absorbed_patterns 快照，而没有改动核心行为代码或行为测试，则 capability_absorption_score 不得超过 84，calibrated_overall 不得超过 84。
- 能力吸收审计只提供风险信号、阻塞项、测试/源码比例和最近 diff 类型；不得把本地能力吸收审计当作参考分。
- 如果员工执行结果由 Retort 本地 CLI 同进程生成，而不是独立 employee_runtime/agent_loop 完成，则 employee_execution_integration 不得超过 88。
- 如果只验证了一个外部项目，external_ingestion 可以高，但 retort_product_maturity 不得超过 88，除非还有跨项目复现证据。
- evidence_loop_score 用于评价五证闭环完整度；capability_absorption_score 用于评价吸收后 Retort 核心能力是否真的变强。calibrated_overall 必须更接近 capability_absorption_score，而不是 evidence_loop_score。
- 如果本地证据与项目摘要冲突，以更保守的证据解释为准。
"""


def request_paibi_llm_review(
    *,
    project: str,
    mode: str = "assess",
    external_source: str = "",
    external_path: str = "",
    scores: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    record: bool = False,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    prompt = build_retort_paibi_prompt(
        project=root,
        mode=mode,
        external_source=external_source,
        external_path=external_path,
        scores=scores or [],
        tasks=tasks or [],
        evidence=evidence or [],
        metadata=metadata or {},
    )
    client = PaibiLLMClient()
    result = client.dispatch(prompt=prompt, project=root, title=f"[report-only] 反问 Retort {mode} LLM 评分")
    payload = {
        "provider": "paibi",
        "mode": mode,
        "prompt_preview": prompt[:1200],
        "dispatch": result,
        "status": result.get("status", "unknown"),
    }
    if record:
        _record_llm_review(root, payload)
    return payload


def record_paibi_llm_deep_result(*, project: str | Path, mode: str, review: dict[str, Any], status: dict[str, Any]) -> None:
    if not status.get("scores"):
        return
    root = Path(project).expanduser().resolve()
    dispatch = review.get("dispatch") if isinstance(review.get("dispatch"), dict) else {}
    _record_llm_review(
        root,
        {
            "provider": "paibi",
            "mode": mode,
            "record_type": "deep_score",
            "status": status.get("status", "completed"),
            "task_id": status.get("task_id") or dispatch.get("task_id"),
            "scores": status.get("scores", []),
            "json_result": status.get("json_result") or {},
            "dispatch": dispatch,
        },
    )


DEFAULT_PARALLEL_PANELS = (
    {
        "panel_id": "evidence_loop",
        "title": "证据闭环评审",
        "focus": "只评估 branch diff、员工执行、post-absorption tests、merge、外部优势复评五类证据是否可复核。",
    },
    {
        "panel_id": "capability_absorption",
        "title": "能力吸收评审",
        "focus": "只评估吸收是否改动核心行为代码和行为测试，不能把报告、日志、patterns 快照当成能力提升。",
    },
    {
        "panel_id": "blocker_resolution",
        "title": "阻塞解法评审",
        "focus": "只找阻塞 Para/Retort 继续并发推进的原因，并输出可执行 unblock_tasks。",
    },
)


def request_paibi_parallel_review(
    *,
    project: str,
    mode: str = "parallel_assess",
    external_source: str = "",
    external_path: str = "",
    tasks: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,
    max_parallel: int = 3,
    record: bool = False,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    selected = list(panels or DEFAULT_PARALLEL_PANELS)[: max(1, min(8, int(max_parallel or 3)))]
    prompts = []
    for panel in selected:
        panel_id = str(panel.get("panel_id") or panel.get("id") or f"panel_{len(prompts) + 1}")
        title = str(panel.get("title") or panel_id)
        focus = str(panel.get("focus") or "")
        prompts.append(
            {
                "panel_id": panel_id,
                "title": title,
                "prompt": build_retort_paibi_panel_prompt(
                    project=root,
                    mode=mode,
                    panel_id=panel_id,
                    panel_title=title,
                    focus=focus,
                    external_source=external_source,
                    external_path=external_path,
                    tasks=tasks or [],
                    evidence=evidence or [],
                    metadata=metadata or {},
                ),
            }
        )
    client = PaibiLLMClient()
    dispatch = client.dispatch_group(project=root, title=f"[parallel] 反问 Retort {mode}", prompts=prompts)
    payload = {
        "provider": "paibi",
        "mode": mode,
        "status": dispatch.get("status", "unknown"),
        "parallel": True,
        "panels": [{"panel_id": item["panel_id"], "title": item["title"]} for item in prompts],
        "dispatch": dispatch,
    }
    if record:
        _record_llm_review(root, payload)
    return payload


def fetch_paibi_llm_review_status(task_id: str) -> dict[str, Any]:
    client = PaibiLLMClient()
    task_body = client.fetch_task(task_id)
    return _summarize_task(task_body)


def fetch_paibi_parallel_review_status(task_id: str) -> dict[str, Any]:
    status = fetch_paibi_llm_review_status(task_id)
    status["parallel"] = True
    status["blockers"] = _analyze_task_blockers(status)
    status["unblock_tasks"] = _unblock_tasks_from_blockers(status["blockers"])
    status["parallel_summary"] = _parallel_summary(status)
    return status


def wait_for_paibi_llm_review(task_id: str, *, timeout_sec: float = 90.0, interval_sec: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_sec)
    client = PaibiLLMClient()
    status = _summarize_task(client.fetch_task(task_id))
    while time.monotonic() < deadline and not status.get("json_result") and status.get("status") not in {"completed", "failed"}:
        time.sleep(max(0.25, interval_sec))
        status = _summarize_task(client.fetch_task(task_id))
    return status


def build_retort_paibi_panel_prompt(
    *,
    project: Path,
    mode: str,
    panel_id: str,
    panel_title: str,
    focus: str,
    external_source: str = "",
    external_path: str = "",
    tasks: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    base = build_retort_paibi_prompt(
        project=project,
        mode=mode,
        external_source=external_source,
        external_path=external_path,
        tasks=tasks or [],
        evidence=evidence or [],
        metadata=metadata or {},
    )
    return f"""{base}

并发评审面板：
- panel_id: {panel_id}
- panel_title: {panel_title}
- focus: {focus}

额外要求：
- 只回答本 panel 的判断，不要等待其它 panel。
- 如果发现阻塞，必须输出 blockers 和 unblock_tasks。
- JSON 须额外包含 "panel_id": "{panel_id}"。
- unblock_tasks 每项须包含 title、owner_hint、acceptance、evidence_required。
"""


def build_retort_paibi_prompt(
    *,
    project: Path,
    mode: str,
    external_source: str = "",
    external_path: str = "",
    scores: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    task_lines = "\n".join(f"- {item.get('task_id')}: {item.get('title')} [{item.get('dimension')}]" for item in tasks or []) or "- no tasks supplied"
    evidence_lines = "\n".join(f"- {item}" for item in evidence or []) or "- no evidence supplied"
    scoring_audit_json = json.dumps(_scoring_audit(metadata or {}), ensure_ascii=False, indent=2, sort_keys=True)[:5000]
    own = _project_digest(project)
    external_digest = _project_digest(Path(external_path)) if external_path and Path(external_path).is_dir() else "external project not materialized"
    return f"""MODSTORE_REPORT_ONLY=1
report_only=true
[report-only]

你是排比 Para/Codex 调度器里的 Retort LLM 评审员。

目标：你负责给反问 Retort 直接评分。确定性代码只负责采集证据；最终分数由你按下面提示词裁决。

模式：{mode}
主项目：{project}
外部来源：{external_source or "无"}
外部本地路径：{external_path or "无"}

评分提示词：
{RETORT_LLM_SCORING_RUBRIC}

本地不提供任何分数，避免锚定。能力吸收审计如果出现 local_score_removed=true，表示本地只给风险事实，不给参考分；你只能按证据、diff、本提示词评分。

当前 Retort 任务：
{task_lines}

本地证据：
{evidence_lines}

评分审计摘要：
{scoring_audit_json}

主项目摘要：
{own}

外部项目摘要：
{external_digest}

请输出严格 JSON：
{{
  "level": "prototype|usable|product",
  "score_suggestion": 0-100,
  "scores": [
    {{"dimension": "product_level", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "architecture_depth", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "test_gate_evidence", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "api_contract_quality", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "operational_readiness", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "evolution_readiness", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "external_ingestion", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "comparative_analysis_depth", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "absorption_tasking", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "employee_execution_integration", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "feedback_loop_closure", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "product_operability", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "safety_license_gate", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "branch_absorption_workflow", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "retort_product_maturity", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "evidence_loop_score", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "capability_absorption_score", "value": 0-100, "reason": "≤18字"}},
    {{"dimension": "calibrated_overall", "value": 0-100, "reason": "≤18字"}}
  ],
  "do_not_raise_score_without_proof": true,
  "architecture_gaps": ["..."],
  "absorption_opportunities": ["..."],
  "employee_tasks": [
    {{"title": "...", "owner_hint": "...", "acceptance": "...", "evidence_required": "..."}}
  ],
  "questions": ["Retort 下一轮必须反问自己的问题"]
}}

要求：
- 这是只读评分任务，不要修改任何文件。
- 直接在最终输出里打印严格 JSON，不要 markdown 代码块。
- 输出必须少于 3200 字符，不能输出逐条长证据。
- 不允许因为已有按钮、关键词或 UI 就给 90+。
- 不允许因为 evidence_loop_score 高就自动给 calibrated_overall 90+。
- 没有 branch diff、员工执行结果、post-absorption tests、merge、外部优势复评五类证据时，总分建议不得超过 82。
- 吸收 diff 只改报告/日志/absorbed_patterns 时，总分建议不得超过 84。
- 重点评估深度，不评估广度。
- scores 必须覆盖这些维度：{", ".join(RETORT_SCORE_DIMENSIONS)}。
"""


class PaibiLLMClient:
    _token_cache = ""

    def __init__(self, api_url: str = "", token: str = "", timeout: float | None = None) -> None:
        self.api_url = (api_url or _env("RETORT_PAIBI_API_URL", "XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "MODSTORE_PARA_API_URL", "DEVFLEET_API_URL") or DEFAULT_PAIBI_API_URL).strip().rstrip("/")
        self.token = (token or _env("RETORT_PAIBI_TOKEN", "XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "MODSTORE_PARA_TOKEN", "DEVFLEET_TOKEN") or self._token_cache).strip()
        self.timeout = timeout if timeout is not None else float(os.environ.get("RETORT_PAIBI_TIMEOUT_SEC") or "8")

    def dispatch(self, *, prompt: str, project: Path, title: str) -> dict[str, Any]:
        if self.api_url.lower() in {"", "0", "false", "off", "none", "disabled"}:
            return self._outbox(project, title, prompt, "paibi_disabled")
        try:
            health = self._request("GET", "/api/health")
            token = self.token or self._guest_token()
            devices = self._request("GET", "/api/devices", token=token).get("devices") or []
            slot = self._select_slot(devices)
            if not slot:
                return self._outbox(project, title, prompt, "paibi_no_online_tool_slot", health=health)
            device = slot["device"]
            tool_name = str(slot["tool_name"])
            body = {
                "title": title[:120],
                "prompt": prompt,
                "device_id": str(device.get("id") or ""),
                "tool_name": tool_name,
                "branch": os.environ.get("RETORT_PAIBI_BRANCH") or "main",
                "subtask_title": title[:120],
                "max_attempts": 3,
                "report_only": True,
            }
            task_body = self._request("POST", "/api/tasks", token=token, json_body=body)
            task = task_body.get("task") if isinstance(task_body.get("task"), dict) else {}
            return {
                "status": "accepted",
                "accepted": True,
                "dispatcher": "paibi_para_api",
                "api_url": self.api_url,
                "task_id": str(task.get("id") or ""),
                "task_status": str(task.get("status") or ""),
                "device": {"id": str(device.get("id") or ""), "name": str(device.get("name") or ""), "tool_name": tool_name},
                "response": task_body,
            }
        except Exception as exc:  # noqa: BLE001
            return self._outbox(project, title, prompt, f"paibi_dispatch_error: {str(exc)[:400]}")

    def dispatch_group(self, *, prompts: list[dict[str, str]], project: Path, title: str, sequential: bool = False) -> dict[str, Any]:
        if self.api_url.lower() in {"", "0", "false", "off", "none", "disabled"}:
            return self._group_outbox(project, title, prompts, "paibi_disabled")
        if not prompts:
            return {"status": "empty", "accepted": False, "dispatcher": "paibi_para_api", "dispatches": []}
        try:
            health = self._request("GET", "/api/health")
            token = self.token or self._guest_token()
            slots = self._select_slots(self._request("GET", "/api/devices", token=token).get("devices") or [])
            if not slots:
                return self._group_outbox(project, title, prompts, "paibi_no_online_tool_slot", health=health)
            single_device_serialized = len(slots) == 1 and len(prompts) > 1 and not sequential and os.environ.get("RETORT_PAIBI_ALLOW_SINGLE_DEVICE_PARALLEL") not in {"1", "true", "yes"}
            effective_sequential = sequential or single_device_serialized
            task_id = ""
            previous_subtask_id = ""
            dispatches: list[dict[str, Any]] = []
            for index, item in enumerate(prompts):
                slot = slots[index % len(slots)]
                device = slot["device"]
                tool_name = str(slot["tool_name"])
                depends_on = [previous_subtask_id] if effective_sequential and previous_subtask_id else []
                body = {
                    "title": title[:120],
                    "prompt": str(item.get("prompt") or ""),
                    "device_id": str(device.get("id") or ""),
                    "tool_name": tool_name,
                    "branch": os.environ.get("RETORT_PAIBI_BRANCH") or "main",
                    "subtask_title": str(item.get("title") or title)[:120],
                    "max_attempts": 3,
                    "report_only": True,
                }
                if task_id:
                    body["task_id"] = task_id
                if depends_on:
                    body["depends_on"] = depends_on
                task_body = self._request("POST", "/api/tasks", token=token, json_body=body)
                task = task_body.get("task") if isinstance(task_body.get("task"), dict) else {}
                subtask = task_body.get("subtask") if isinstance(task_body.get("subtask"), dict) else {}
                task_id = str(task.get("id") or task_id)
                previous_subtask_id = str(subtask.get("id") or previous_subtask_id)
                dispatches.append(
                    {
                        "panel_id": str(item.get("panel_id") or f"panel_{index + 1}"),
                        "title": str(item.get("title") or ""),
                        "task_id": task_id,
                        "subtask_id": previous_subtask_id,
                        "device": {"id": str(device.get("id") or ""), "name": str(device.get("name") or ""), "tool_name": tool_name},
                        "depends_on": depends_on,
                    }
                )
            unique_devices = {row["device"]["id"] for row in dispatches if row["device"]["id"]}
            unique_slots = {(row["device"]["id"], row["device"].get("tool_name")) for row in dispatches if row["device"]["id"]}
            return {
                "status": "accepted",
                "accepted": True,
                "dispatcher": "paibi_para_api",
                "api_url": self.api_url,
                "task_id": task_id,
                "task_status": "running",
                "subtask_count": len(dispatches),
                "device_count": len(unique_devices),
                "tool_slot_count": len(slots),
                "parallelism": len(unique_slots),
                "degraded_reason": "single_device_serialized_to_avoid_workspace_clone_race" if single_device_serialized else "",
                "dispatches": dispatches,
            }
        except Exception as exc:  # noqa: BLE001
            return self._group_outbox(project, title, prompts, f"paibi_dispatch_error: {str(exc)[:400]}")

    def fetch_task(self, task_id: str) -> dict[str, Any]:
        if self.api_url.lower() in {"", "0", "false", "off", "none", "disabled"}:
            raise RuntimeError("Para API is disabled")
        token = self.token or self._guest_token()
        return self._request("GET", f"/api/tasks/{task_id}", token=token)

    def _guest_token(self) -> str:
        body = self._request("POST", "/api/auth/guest", json_body={})
        token = str(body.get("token") or body.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("Para guest 登录未返回 token")
        self.token = token
        PaibiLLMClient._token_cache = token
        return token

    def _request(self, method: str, path: str, *, token: str = "", json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if json_body is None else json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Para API HTTP {exc.code}: {raw[:300]}") from exc

    def _select_device(self, devices: Any) -> dict[str, Any] | None:
        slot = self._select_slot(devices)
        return slot["device"] if slot else None

    def _select_devices(self, devices: Any) -> list[dict[str, Any]]:
        seen: set[str] = set()
        selected: list[dict[str, Any]] = []
        for slot in self._select_slots(devices):
            device = slot["device"]
            device_id = str(device.get("id") or "")
            if device_id in seen:
                continue
            seen.add(device_id)
            selected.append(device)
        return selected

    def _select_slot(self, devices: Any) -> dict[str, Any] | None:
        slots = self._select_slots(devices)
        return slots[0] if slots else None

    def _select_slots(self, devices: Any) -> list[dict[str, Any]]:
        if not isinstance(devices, list):
            return []
        selected: list[dict[str, Any]] = []
        for item in devices:
            if not isinstance(item, dict) or str(item.get("status") or "") != "online":
                continue
            for tool_name in self._device_tool_candidates(item):
                selected.append({"device": item, "tool_name": tool_name})
        worker_slots = [slot for slot in selected if not bool(slot["device"].get("isPrimary") or slot["device"].get("is_primary"))]
        return worker_slots or selected

    def _device_tool_candidates(self, device: dict[str, Any]) -> list[str]:
        tools = device.get("tools") if isinstance(device.get("tools"), list) else []
        available: list[str] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("toolName") or tool.get("tool_name") or "")
            if name not in PAIBI_SUPPORTED_TOOLS:
                continue
            status = str(tool.get("status") or "idle")
            current_task = str(tool.get("currentTask") or tool.get("current_task") or "")
            if status == "not_installed" or (status == "running" and current_task):
                continue
            available.append(name)
        dev_tool = str(device.get("devTool") or device.get("dev_tool") or "")
        ordered: list[str] = []
        if dev_tool in available:
            ordered.append(dev_tool)
        for name in PAIBI_SUPPORTED_TOOLS:
            if name in available and name not in ordered:
                ordered.append(name)
        if ordered:
            return ordered
        capabilities = device.get("capabilities") if isinstance(device.get("capabilities"), dict) else {}
        if dev_tool in PAIBI_SUPPORTED_TOOLS and not tools:
            return [dev_tool]
        if capabilities.get("codex_cli") is True:
            return ["codex"]
        return []

    def _outbox(self, project: Path, title: str, prompt: str, reason: str, **extra: Any) -> dict[str, Any]:
        outbox = project / ".retort" / "paibi_llm_outbox.jsonl"
        outbox.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "id": uuid.uuid4().hex,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "title": title,
            "prompt": prompt,
            "reason": reason,
            **extra,
        }
        with outbox.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return {"status": "queued_outbox", "accepted": False, "dispatcher": "paibi_outbox", "reason": reason, "outbox_path": str(outbox)}

    def _group_outbox(self, project: Path, title: str, prompts: list[dict[str, str]], reason: str, **extra: Any) -> dict[str, Any]:
        dispatches = []
        for item in prompts:
            result = self._outbox(project, f"{title} / {item.get('title') or item.get('panel_id')}", str(item.get("prompt") or ""), reason, **extra)
            dispatches.append({"panel_id": item.get("panel_id"), "title": item.get("title"), **result})
        return {"status": "queued_outbox", "accepted": False, "dispatcher": "paibi_outbox", "reason": reason, "dispatches": dispatches}


def _project_digest(root: Path) -> str:
    if not root.is_dir():
        return "project folder not found"
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & SKIP_PARTS:
            continue
        files.append(path)
    suffix_counts: dict[str, int] = {}
    snippets: list[str] = []
    for path in files[:400]:
        suffix_counts[path.suffix.lower() or "<none>"] = suffix_counts.get(path.suffix.lower() or "<none>", 0) + 1
        if len(snippets) >= 18 or path.suffix.lower() not in SOURCE_SUFFIXES or path.name in GENERATED_EVIDENCE_FILES:
            continue
        text = _read(path)
        if not text.strip():
            continue
        rel = path.relative_to(root)
        snippets.append(f"## {rel}\n{_compact(text)[:900]}")
    return json.dumps({"file_count": len(files), "suffix_counts": suffix_counts, "snippets": snippets}, ensure_ascii=False, indent=2)


def _scoring_audit(metadata: dict[str, Any]) -> dict[str, Any]:
    proof = metadata.get("closed_loop_proof") if isinstance(metadata.get("closed_loop_proof"), dict) else {}
    audit = metadata.get("capability_absorption_audit") if isinstance(metadata.get("capability_absorption_audit"), dict) else {}
    audit = {key: value for key, value in audit.items() if key not in {"score", "overall_cap", "employee_execution_cap"}}
    audit["local_score_removed"] = True
    return {
        "git_tracking_state": metadata.get("git_tracking_state"),
        "closed_loop_verified": proof.get("verified"),
        "closed_loop_missing": proof.get("missing"),
        "capability_absorption_audit": audit,
    }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _compact(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return "\n".join(line[:180] for line in text.splitlines()[:80])


def _record_llm_review(root: Path, payload: dict[str, Any]) -> None:
    path = root / ".retort" / "llm_reviews.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _summarize_task(task_body: dict[str, Any]) -> dict[str, Any]:
    task = task_body.get("task") if isinstance(task_body.get("task"), dict) else task_body
    subtasks = task.get("subTasks") or task.get("subtasks") or []
    normalized_subtasks: list[dict[str, Any]] = []
    logs: list[str] = []
    if isinstance(subtasks, list):
        for subtask in subtasks:
            if not isinstance(subtask, dict):
                continue
            subtask_logs = subtask.get("logs") if isinstance(subtask.get("logs"), list) else []
            for row in subtask_logs:
                if isinstance(row, dict) and str(row.get("content") or "").strip():
                    logs.append(str(row.get("content") or "").strip())
            normalized_subtasks.append(
                {
                    "id": str(subtask.get("id") or ""),
                    "title": str(subtask.get("title") or ""),
                    "status": str(subtask.get("status") or ""),
                    "blocked": bool(subtask.get("blocked")),
                    "last_error": str(subtask.get("last_error") or subtask.get("lastError") or ""),
                    "depends_on": [str(item) for item in (subtask.get("depends_on") or subtask.get("dependsOn") or [])],
                    "progress": subtask.get("progress") or 0,
                    "device_name": str(subtask.get("device_name") or ""),
                    "branch_name": str(subtask.get("branch_name") or ""),
                    "log_count": len(subtask_logs),
                }
            )
    excerpt = "\n".join(logs)[-8000:]
    json_result = _extract_last_json_object(excerpt)
    return {
        "provider": "paibi",
        "task_id": str(task.get("id") or ""),
        "status": str(task.get("status") or ""),
        "subtasks": normalized_subtasks,
        "logs_excerpt": excerpt,
        "json_result": json_result,
        "scores": _normalize_llm_scores(json_result),
    }


def _parallel_summary(status: dict[str, Any]) -> dict[str, Any]:
    subtasks = status.get("subtasks") if isinstance(status.get("subtasks"), list) else []
    counts: dict[str, int] = {}
    devices: set[str] = set()
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        sub_status = str(subtask.get("status") or "unknown")
        counts[sub_status] = counts.get(sub_status, 0) + 1
        if subtask.get("device_name"):
            devices.add(str(subtask.get("device_name")))
    return {"subtask_count": len(subtasks), "status_counts": counts, "device_count": len(devices), "has_blockers": bool(_analyze_task_blockers(status))}


def _analyze_task_blockers(status: dict[str, Any]) -> list[dict[str, Any]]:
    subtasks = status.get("subtasks") if isinstance(status.get("subtasks"), list) else []
    logs = str(status.get("logs_excerpt") or "")
    blockers: list[dict[str, Any]] = []
    pending_without_deps = [
        subtask
        for subtask in subtasks
        if isinstance(subtask, dict) and str(subtask.get("status") or "") == "pending" and not (subtask.get("depends_on") or [])
    ]
    if pending_without_deps and ("当前不可用" in logs or "执行器忙" in logs or "busy" in logs.lower()):
        blockers.append(
            {
                "kind": "worker_capacity_limit",
                "action": "add_worker_or_wait_running_slot",
                "task_id": status.get("task_id"),
                "status": status.get("status"),
                "pending_subtask_count": len(pending_without_deps),
            }
        )
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        sub_status = str(subtask.get("status") or "")
        blocked = bool(subtask.get("blocked")) or sub_status in {"failed", "blocked"}
        if not blocked:
            continue
        text = " ".join([sub_status, str(subtask.get("last_error") or ""), logs]).lower()
        kind = "subtask_blocked"
        action = "inspect_logs_and_retry"
        if "git clone --no-hardlinks" in text or "fetch-pack" in text or "tmp_pack" in text:
            kind = "workspace_clone_race"
            action = "retry_serial_or_unique_workspace"
        elif "未在线" in text or "offline" in text:
            kind = "device_offline"
            action = "start_or_replace_device"
        elif "缺少自动改码执行器" in text or "not_installed" in text or "executor" in text:
            kind = "executor_missing"
            action = "install_or_select_executor"
        elif "depends" in text or "前置" in text:
            kind = "dependency_wait"
            action = "complete_or_remove_dependency"
        elif "timeout" in text or "超时" in text:
            kind = "timeout"
            action = "split_smaller_or_retry"
        blockers.append(
            {
                "kind": kind,
                "action": action,
                "subtask_id": subtask.get("id"),
                "title": subtask.get("title"),
                "status": sub_status,
                "device_name": subtask.get("device_name"),
                "last_error": subtask.get("last_error"),
            }
        )
    if status.get("status") in {"failed", "blocked"} and not blockers:
        blockers.append({"kind": "task_blocked", "action": "inspect_task_logs_and_retry", "task_id": status.get("task_id"), "status": status.get("status")})
    return blockers


def _unblock_tasks_from_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, str]]:
    tasks = []
    for index, blocker in enumerate(blockers, start=1):
        kind = str(blocker.get("kind") or "subtask_blocked")
        subtask = str(blocker.get("subtask_id") or blocker.get("task_id") or "")
        if kind == "device_offline":
            title = "恢复或替换离线 Para 工作设备"
            acceptance = f"子任务 {subtask} 所在设备在线，或任务已迁移到在线 Codex 设备。"
            owner = "runtime"
        elif kind == "executor_missing":
            title = "安装或切换 Codex 执行器"
            acceptance = f"子任务 {subtask} 的目标设备 executorReady=true，重新派发后进入 running/completed。"
            owner = "runtime"
        elif kind == "dependency_wait":
            title = "解除无效前置依赖"
            acceptance = f"子任务 {subtask} 的 depends_on 已完成或被移除，调度器可派发。"
            owner = "scheduler"
        elif kind == "timeout":
            title = "拆小并重试超时子任务"
            acceptance = f"子任务 {subtask} 被拆成更小 panel，并在超时窗口内返回 JSON。"
            owner = "scheduler"
        elif kind == "worker_capacity_limit":
            title = "增加 Para worker 或等待执行槽位"
            acceptance = "pending 子任务进入 running/completed，或被迁移到其它在线 Codex 设备。"
            owner = "runtime"
        elif kind == "workspace_clone_race":
            title = "串行重试或隔离 Para 工作区"
            acceptance = f"子任务 {subtask} 不再共享并发 clone 目录，重试后不再出现 tmp_pack/fetch-pack 错误。"
            owner = "scheduler"
        else:
            title = "诊断并重试阻塞子任务"
            acceptance = f"子任务 {subtask} 的 last_error 已归因，重试后不再处于 failed/blocked。"
            owner = "runtime"
        tasks.append(
            {
                "title": title,
                "owner_hint": owner,
                "acceptance": acceptance,
                "evidence_required": "Para task status, subtask logs, retry result",
                "blocker_kind": kind,
                "task_id": f"para-unblock-{index:02d}",
            }
        )
    return tasks


def _extract_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            if isinstance(value.get("scores"), list) or "score_suggestion" in value:
                return value
            best = value
    return best


def _normalize_llm_scores(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_scores = payload.get("scores")
    scores: list[dict[str, Any]] = []
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            dimension = str(item.get("dimension") or "").strip()
            if dimension not in RETORT_SCORE_DIMENSIONS:
                continue
            try:
                value = max(0.0, min(100.0, float(item.get("value"))))
            except (TypeError, ValueError):
                continue
            evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
            scores.append(
                {
                    "dimension": dimension,
                    "value": round(value, 1),
                    "reason": str(item.get("reason") or "LLM score from Retort scoring prompt."),
                    "evidence": [str(row) for row in evidence],
                }
            )
    existing = {score["dimension"] for score in scores}
    if "calibrated_overall" not in existing:
        suggestion = payload.get("score_suggestion")
        try:
            value = max(0.0, min(100.0, float(suggestion)))
        except (TypeError, ValueError):
            value = -1.0
        if value >= 0:
            scores.append(
                {
                    "dimension": "calibrated_overall",
                    "value": round(value, 1),
                    "reason": "LLM score_suggestion normalized as calibrated_overall.",
                    "evidence": [],
                }
            )
    return scores


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""
