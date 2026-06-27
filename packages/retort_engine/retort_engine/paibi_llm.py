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
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md", ".toml", ".yml", ".yaml", ".json"}
SKIP_PARTS = {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache"}
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
    "calibrated_overall",
)
RETORT_LLM_SCORING_RUBRIC = """旧的规则评分已经转成以下评分提示词，只作为 LLM 的裁判标准，不再作为最终分数：
- 你必须直接给每个维度 0-100 分，并给出可验证理由。
- 重点评估深度，不用功能数量堆高分。
- UI、按钮、关键词、文件存在只能证明“有入口”，不能证明“闭环完成”。
- lint/test 通过可以提高 test_gate_evidence 和 operational_readiness，但不能单独把产品级推到 90+。
- 没有 branch diff、员工执行结果、post-absorption tests、merge、外部优势复评五类证据时，calibrated_overall 不得超过 82。
- 没有员工真实执行证据时，employee_execution_integration 不得超过 78。
- 没有吸收后复评和反馈回灌证据时，feedback_loop_closure 不得超过 82。
- 没有真实外部项目吸收、分支落地、合并或回滚证据时，product_level 和 retort_product_maturity 不得超过 84。
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
    _record_llm_review(root, payload)
    return payload


def fetch_paibi_llm_review_status(task_id: str) -> dict[str, Any]:
    client = PaibiLLMClient()
    task_body = client.fetch_task(task_id)
    return _summarize_task(task_body)


def wait_for_paibi_llm_review(task_id: str, *, timeout_sec: float = 90.0, interval_sec: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_sec)
    client = PaibiLLMClient()
    status = _summarize_task(client.fetch_task(task_id))
    while time.monotonic() < deadline and not status.get("json_result") and status.get("status") not in {"completed", "failed"}:
        time.sleep(max(0.25, interval_sec))
        status = _summarize_task(client.fetch_task(task_id))
    return status


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
    score_lines = "\n".join(f"- {item.get('dimension')}: {item.get('value')} ({item.get('reason', '')})" for item in scores or []) or "- no local fallback scores supplied"
    task_lines = "\n".join(f"- {item.get('task_id')}: {item.get('title')} [{item.get('dimension')}]" for item in tasks or []) or "- no tasks supplied"
    evidence_lines = "\n".join(f"- {item}" for item in evidence or []) or "- no evidence supplied"
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, indent=2, sort_keys=True)[:5000]
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

本地 fallback 规则分，仅供参考，不是最终分：
{score_lines}

当前 Retort 任务：
{task_lines}

本地证据：
{evidence_lines}

本地元数据：
{metadata_json}

主项目摘要：
{own}

外部项目摘要：
{external_digest}

请输出严格 JSON：
{{
  "level": "prototype|usable|product",
  "score_suggestion": 0-100,
  "scores": [
    {{"dimension": "product_level", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "architecture_depth", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "test_gate_evidence", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "api_contract_quality", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "operational_readiness", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "evolution_readiness", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "external_ingestion", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "comparative_analysis_depth", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "absorption_tasking", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "employee_execution_integration", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "feedback_loop_closure", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "product_operability", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "safety_license_gate", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "branch_absorption_workflow", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "retort_product_maturity", "value": 0-100, "reason": "...", "evidence": ["..."]}},
    {{"dimension": "calibrated_overall", "value": 0-100, "reason": "...", "evidence": ["..."]}}
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
- 不允许因为已有按钮、关键词或 UI 就给 90+。
- 没有 branch diff、员工执行结果、post-absorption tests、merge、外部优势复评五类证据时，总分建议不得超过 82。
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
            device = self._select_device(devices)
            if not device:
                return self._outbox(project, title, prompt, "paibi_no_online_codex_device", health=health)
            device = self._ensure_codex_device(device, token)
            body = {
                "title": title[:120],
                "prompt": prompt,
                "device_id": str(device.get("id") or ""),
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
                "device": {"id": str(device.get("id") or ""), "name": str(device.get("name") or "")},
                "response": task_body,
            }
        except Exception as exc:  # noqa: BLE001
            return self._outbox(project, title, prompt, f"paibi_dispatch_error: {str(exc)[:400]}")

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
        if not isinstance(devices, list):
            return None
        for item in devices:
            if not isinstance(item, dict) or str(item.get("status") or "") != "online":
                continue
            capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
            tools = item.get("tools") if isinstance(item.get("tools"), list) else []
            tool_ok = any(isinstance(tool, dict) and str(tool.get("toolName") or "") == "codex" and str(tool.get("status") or "idle") != "not_installed" for tool in tools)
            if str(item.get("devTool") or "") == "codex" or capabilities.get("codex_cli") is True or tool_ok:
                return item
        return None

    def _ensure_codex_device(self, device: dict[str, Any], token: str) -> dict[str, Any]:
        if str(device.get("devTool") or "") == "codex":
            return device
        device_id = str(device.get("id") or "")
        if not device_id:
            return device
        body = self._request("PUT", f"/api/devices/{device_id}/dev-tool", token=token, json_body={"devTool": "codex"})
        updated = body.get("device")
        return updated if isinstance(updated, dict) else {**device, "devTool": "codex"}

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
        if len(snippets) >= 18 or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        text = _read(path)
        if not text.strip():
            continue
        rel = path.relative_to(root)
        snippets.append(f"## {rel}\n{_compact(text)[:900]}")
    return json.dumps({"file_count": len(files), "suffix_counts": suffix_counts, "snippets": snippets}, ensure_ascii=False, indent=2)


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
                    "status": str(subtask.get("status") or ""),
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
