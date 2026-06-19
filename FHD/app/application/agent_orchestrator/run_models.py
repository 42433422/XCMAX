from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

RunStatus = Literal[
    "queued",
    "planning",
    "running",
    "retrying",
    "waiting_user",
    "blocked",
    "completed",
    "failed",
    "cancelled",
]

AgentStepStatus = Literal[
    "pending",
    "running",
    "retrying",
    "waiting_user",
    "completed",
    "failed",
    "skipped",
]

ToolCallStatus = Literal["running", "completed", "failed"]
LLMCallStatus = Literal["completed", "failed"]
RetrievalCallStatus = Literal["completed", "failed"]
MemoryReferenceStatus = Literal["completed", "failed"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class RunEvent:
    run_id: str
    event_type: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("evt"))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "message": self.message,
            "data": self.data,
            "created_at": self.created_at,
        }


def run_event_from_dict(data: dict[str, Any]) -> RunEvent:
    return RunEvent(
        run_id=str(data.get("run_id") or ""),
        event_type=str(data.get("event_type") or ""),
        message=str(data.get("message") or ""),
        data=dict(data.get("data") or {}),
        event_id=str(data.get("event_id") or "") or new_id("evt"),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
    )


@dataclass
class AgentStep:
    node_id: str
    tool_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"
    idempotent: bool = False
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    step_id: str = field(default_factory=lambda: new_id("step"))
    status: AgentStepStatus = "pending"
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    attempt_count: int = 0
    max_repair_attempts: int = 0
    observations: list[dict[str, Any]] = field(default_factory=list)
    repair_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "node_id": self.node_id,
            "tool_id": self.tool_id,
            "action": self.action,
            "params": self.params,
            "risk": self.risk,
            "idempotent": self.idempotent,
            "description": self.description,
            "depends_on": self.depends_on,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "attempt_count": self.attempt_count,
            "max_repair_attempts": self.max_repair_attempts,
            "observations": self.observations,
            "repair_history": self.repair_history,
        }


def agent_step_from_dict(data: dict[str, Any]) -> AgentStep:
    return AgentStep(
        node_id=str(data.get("node_id") or ""),
        tool_id=str(data.get("tool_id") or ""),
        action=str(data.get("action") or ""),
        params=dict(data.get("params") or {}),
        risk=str(data.get("risk") or "low"),
        idempotent=bool(data.get("idempotent", False)),
        description=str(data.get("description") or ""),
        depends_on=list(data.get("depends_on") or []),
        step_id=str(data.get("step_id") or "") or new_id("step"),
        status=data.get("status") or "pending",
        output=dict(data.get("output") or {}),
        error=str(data.get("error") or ""),
        started_at=str(data.get("started_at") or ""),
        finished_at=str(data.get("finished_at") or ""),
        duration_ms=int(data.get("duration_ms") or 0),
        attempt_count=int(data.get("attempt_count") or 0),
        max_repair_attempts=int(data.get("max_repair_attempts") or 0),
        observations=[item for item in (data.get("observations") or []) if isinstance(item, dict)],
        repair_history=[
            item for item in (data.get("repair_history") or []) if isinstance(item, dict)
        ],
    )


@dataclass
class ToolCall:
    step_id: str
    node_id: str
    tool_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    status: ToolCallStatus = "running"
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    cost_units: int = 0
    permission: str = ""
    call_id: str = field(default_factory=lambda: new_id("call"))
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = ""
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "step_id": self.step_id,
            "node_id": self.node_id,
            "tool_id": self.tool_id,
            "action": self.action,
            "params": self.params,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "cost_units": self.cost_units,
            "permission": self.permission,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


def tool_call_from_dict(data: dict[str, Any]) -> ToolCall:
    return ToolCall(
        step_id=str(data.get("step_id") or ""),
        node_id=str(data.get("node_id") or ""),
        tool_id=str(data.get("tool_id") or ""),
        action=str(data.get("action") or ""),
        params=dict(data.get("params") or {}),
        status=data.get("status") or "running",
        output=dict(data.get("output") or {}),
        error=str(data.get("error") or ""),
        cost_units=int(data.get("cost_units") or 0),
        permission=str(data.get("permission") or ""),
        call_id=str(data.get("call_id") or "") or new_id("call"),
        started_at=str(data.get("started_at") or "") or utc_now_iso(),
        finished_at=str(data.get("finished_at") or ""),
        duration_ms=int(data.get("duration_ms") or 0),
        metadata=dict(data.get("metadata") or {}),
    )


@dataclass
class LLMCall:
    provider_id: str = ""
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    cost_units: int = 0
    billing_status: str = ""
    billing_source: str = ""
    status: LLMCallStatus = "completed"
    error: str = ""
    call_id: str = field(default_factory=lambda: new_id("llm"))
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "provider_id": self.provider_id,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "cost_units": self.cost_units,
            "billing_status": self.billing_status,
            "billing_source": self.billing_source,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


def llm_call_from_dict(data: dict[str, Any]) -> LLMCall:
    status = str(data.get("status") or "completed")
    return LLMCall(
        provider_id=str(data.get("provider_id") or ""),
        provider=str(data.get("provider") or ""),
        model=str(data.get("model") or ""),
        prompt_tokens=_coerce_int(data.get("prompt_tokens")),
        completion_tokens=_coerce_int(data.get("completion_tokens")),
        total_tokens=_coerce_int(data.get("total_tokens")),
        latency_ms=_coerce_float(data.get("latency_ms")),
        cost_units=_coerce_int(data.get("cost_units")),
        billing_status=str(data.get("billing_status") or ""),
        billing_source=str(data.get("billing_source") or ""),
        status=status if status in {"completed", "failed"} else "completed",
        error=str(data.get("error") or ""),
        call_id=str(data.get("call_id") or "") or new_id("llm"),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
        metadata=dict(data.get("metadata") or {}),
    )


@dataclass
class RetrievalCall:
    query: str = ""
    retriever: str = "rag"
    source: str = ""
    top_k: int = 0
    chunks: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    status: RetrievalCallStatus = "completed"
    error: str = ""
    call_id: str = field(default_factory=lambda: new_id("ret"))
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "query": self.query,
            "retriever": self.retriever,
            "source": self.source,
            "top_k": self.top_k,
            "chunks": self.chunks,
            "citations": self.citations,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


def retrieval_call_from_dict(data: dict[str, Any]) -> RetrievalCall:
    chunks = data.get("chunks")
    citations = data.get("citations")
    status = str(data.get("status") or "completed")
    return RetrievalCall(
        query=str(data.get("query") or ""),
        retriever=str(data.get("retriever") or "rag"),
        source=str(data.get("source") or ""),
        top_k=_coerce_int(data.get("top_k")),
        chunks=[item for item in chunks if isinstance(item, dict)]
        if isinstance(chunks, list)
        else [],
        citations=[item for item in citations if isinstance(item, dict)]
        if isinstance(citations, list)
        else [],
        status=status if status in {"completed", "failed"} else "completed",
        error=str(data.get("error") or ""),
        call_id=str(data.get("call_id") or "") or new_id("ret"),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
        metadata=dict(data.get("metadata") or {}),
    )


@dataclass
class MemoryReference:
    query: str = ""
    memory_type: str = "user_memory"
    source: str = ""
    hits: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    status: MemoryReferenceStatus = "completed"
    error: str = ""
    reference_id: str = field(default_factory=lambda: new_id("mem"))
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "query": self.query,
            "memory_type": self.memory_type,
            "source": self.source,
            "hits": self.hits,
            "summary": self.summary,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


def memory_reference_from_dict(data: dict[str, Any]) -> MemoryReference:
    hits = data.get("hits")
    status = str(data.get("status") or "completed")
    return MemoryReference(
        query=str(data.get("query") or ""),
        memory_type=str(data.get("memory_type") or data.get("type") or "user_memory"),
        source=str(data.get("source") or ""),
        hits=[item for item in hits if isinstance(item, dict)] if isinstance(hits, list) else [],
        summary=str(data.get("summary") or ""),
        status=status if status in {"completed", "failed"} else "completed",
        error=str(data.get("error") or ""),
        reference_id=str(data.get("reference_id") or "") or new_id("mem"),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
        metadata=dict(data.get("metadata") or {}),
    )


@dataclass
class AgentArtifact:
    artifact_type: str
    name: str = ""
    source: str = ""
    uri: str = ""
    mime_type: str = ""
    summary: str = ""
    fields: list[dict[str, Any]] = field(default_factory=list)
    preview: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact_id: str = field(default_factory=lambda: new_id("art"))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "name": self.name,
            "source": self.source,
            "uri": self.uri,
            "mime_type": self.mime_type,
            "summary": self.summary,
            "fields": self.fields,
            "preview": self.preview,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


def artifact_from_dict(data: dict[str, Any]) -> AgentArtifact:
    fields = data.get("fields")
    return AgentArtifact(
        artifact_type=str(data.get("artifact_type") or data.get("type") or ""),
        name=str(data.get("name") or ""),
        source=str(data.get("source") or ""),
        uri=str(data.get("uri") or data.get("file_path") or ""),
        mime_type=str(data.get("mime_type") or ""),
        summary=str(data.get("summary") or ""),
        fields=[item for item in fields if isinstance(item, dict)]
        if isinstance(fields, list)
        else [],
        preview=dict(data.get("preview") or {}),
        metadata=dict(data.get("metadata") or {}),
        artifact_id=str(data.get("artifact_id") or "") or new_id("art"),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
    )


@dataclass
class AgentRun:
    user_id: str
    message: str
    run_id: str = field(default_factory=lambda: new_id("run"))
    status: RunStatus = "queued"
    plan_id: str = ""
    intent: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)
    retrieval_calls: list[RetrievalCall] = field(default_factory=list)
    memory_references: list[MemoryReference] = field(default_factory=list)
    artifacts: list[AgentArtifact] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)
    final_output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def add_event(
        self,
        event_type: str,
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        event = RunEvent(
            run_id=self.run_id,
            event_type=event_type,
            message=message,
            data=dict(data or {}),
        )
        self.events.append(event)
        self.touch()
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "message": self.message,
            "status": self.status,
            "plan_id": self.plan_id,
            "intent": self.intent,
            "steps": [step.to_dict() for step in self.steps],
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "llm_calls": [call.to_dict() for call in self.llm_calls],
            "retrieval_calls": [call.to_dict() for call in self.retrieval_calls],
            "memory_references": [reference.to_dict() for reference in self.memory_references],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "events": [event.to_dict() for event in self.events],
            "final_output": self.final_output,
            "error": self.error,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def agent_run_from_dict(data: dict[str, Any]) -> AgentRun:
    return AgentRun(
        user_id=str(data.get("user_id") or ""),
        message=str(data.get("message") or ""),
        run_id=str(data.get("run_id") or "") or new_id("run"),
        status=data.get("status") or "queued",
        plan_id=str(data.get("plan_id") or ""),
        intent=str(data.get("intent") or ""),
        steps=[
            agent_step_from_dict(step)
            for step in (data.get("steps") or [])
            if isinstance(step, dict)
        ],
        tool_calls=[
            tool_call_from_dict(call)
            for call in (data.get("tool_calls") or [])
            if isinstance(call, dict)
        ],
        llm_calls=[
            llm_call_from_dict(call)
            for call in (data.get("llm_calls") or [])
            if isinstance(call, dict)
        ],
        retrieval_calls=[
            retrieval_call_from_dict(call)
            for call in (data.get("retrieval_calls") or [])
            if isinstance(call, dict)
        ],
        memory_references=[
            memory_reference_from_dict(reference)
            for reference in (data.get("memory_references") or [])
            if isinstance(reference, dict)
        ],
        artifacts=[
            artifact_from_dict(artifact)
            for artifact in (data.get("artifacts") or [])
            if isinstance(artifact, dict)
        ],
        events=[
            run_event_from_dict(event)
            for event in (data.get("events") or [])
            if isinstance(event, dict)
        ],
        final_output=dict(data.get("final_output") or {}),
        error=str(data.get("error") or ""),
        metadata=dict(data.get("metadata") or {}),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
        updated_at=str(data.get("updated_at") or "") or utc_now_iso(),
    )
