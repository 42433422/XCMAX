"""Retort's improvement cycle on LangGraph persistence and human interrupts."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from retort_engine.evolution_contract import digest


class EvolutionState(TypedDict, total=False):
    protocol: dict[str, Any]
    plan: dict[str, Any]
    optimization: dict[str, Any]
    dispatch: dict[str, Any]
    execution: dict[str, Any]
    verification: dict[str, Any]
    delivery: dict[str, Any]
    approval: dict[str, Any]
    knowledge: dict[str, Any]
    has_customer_feedback: bool
    impact: dict[str, Any]
    status: str


class EvolutionPorts(Protocol):
    # Implementations own idempotency for external effects, including an unknown
    # response. A checkpoint alone cannot make an HTTP side effect exactly-once.
    def plan(self, protocol: dict[str, Any]) -> dict[str, Any]: ...
    def optimize(
        self, protocol: dict[str, Any], plan: dict[str, Any]
    ) -> dict[str, Any]: ...
    def dispatch(self, state: EvolutionState) -> dict[str, Any]: ...
    def collect(self, state: EvolutionState) -> dict[str, Any]: ...
    def verify(self, state: EvolutionState) -> dict[str, Any]: ...
    def delivery(self, state: EvolutionState) -> dict[str, Any]: ...
    def impact(self, state: EvolutionState) -> dict[str, Any]: ...
    def remember(self, state: EvolutionState) -> dict[str, Any]: ...


def build_evolution_graph(ports: EvolutionPorts, checkpointer: Any):
    def plan(state: EvolutionState):
        return {"plan": ports.plan(state["protocol"]), "status": "planned"}

    def optimize(state: EvolutionState):
        proposal = ports.optimize(state["protocol"], state["plan"])
        return {"optimization": proposal, "status": "awaiting_dispatch_approval"}

    def authorize(state: EvolutionState):
        binding = digest(
            {
                "protocol": state["protocol"],
                "plan": state["plan"],
                "optimization": state["optimization"],
            }
        )
        reply = interrupt(
            {
                "kind": "dispatch_approval",
                "digest": binding,
                "title": state["protocol"]["title"],
                "plan": state["plan"],
            }
        )
        approved = _approved(reply, binding)
        return {"approval": reply, "status": "authorized" if approved else "rejected"}

    def dispatch(state: EvolutionState):
        return {"dispatch": ports.dispatch(state), "status": "waiting_execution"}

    def collect(state: EvolutionState):
        # The scheduler resumes this interrupt after a read-only poll. The resume
        # payload never supplies evidence: the trusted adapter reads it afresh.
        interrupt({"kind": "execution", "request_id": state["protocol"]["request_id"]})
        result = ports.collect(state)
        status = str(result.get("status") or "unknown")
        return {
            "execution": result,
            "status": "verifying"
            if status == "completed"
            else "failed"
            if status in {"failed", "cancelled"}
            else "waiting_execution",
        }

    def verify(state: EvolutionState):
        result = ports.verify(state)
        passed = result.get("status") == "checks_passed"
        return {
            "verification": result,
            "status": "awaiting_acceptance" if passed else "failed",
        }

    def accept(state: EvolutionState):
        binding = digest(state["verification"])
        reply = interrupt(
            {
                "kind": "acceptance",
                "digest": binding,
                "verification": state["verification"],
            }
        )
        approved = _approved(reply, binding)
        return {
            "approval": reply,
            "status": "waiting_delivery" if approved else "rejected",
        }

    def remember(state: EvolutionState):
        knowledge = ports.remember(state)
        return {"knowledge": knowledge, "status": "completed"}

    def delivery(state: EvolutionState):
        # A user's acceptance of branch evidence does not attest a production
        # deployment. Resume from durable checkpoints and re-read trusted ports.
        interrupt({"kind": "delivery", "request_id": state["protocol"]["request_id"]})
        result = ports.delivery(state)
        status = result.get("status")
        return {
            "delivery": result,
            "status": "delivered"
            if status == "deployment_verified"
            else "failed"
            if status == "failed"
            else "waiting_delivery",
        }

    def impact(state: EvolutionState):
        interrupt({"kind": "customer_impact", "request_id": state["protocol"]["request_id"]})
        result = ports.impact(state)
        return {
            "impact": result,
            "status": result["status"],
        }

    graph = StateGraph(EvolutionState)
    for name, fn in (
        ("plan", plan),
        ("optimize", optimize),
        ("authorize", authorize),
        ("dispatch", dispatch),
        ("collect", collect),
        ("verify", verify),
        ("accept", accept),
        ("delivery", delivery),
        ("impact", impact),
        ("remember", remember),
    ):
        graph.add_node(name, fn)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "optimize")
    graph.add_edge("optimize", "authorize")
    graph.add_conditional_edges(
        "authorize", lambda s: "dispatch" if s["status"] == "authorized" else END
    )
    graph.add_edge("dispatch", "collect")
    graph.add_conditional_edges(
        "collect",
        lambda s: {"verifying": "verify", "waiting_execution": "collect"}.get(
            s["status"], END
        ),
    )
    graph.add_conditional_edges(
        "verify", lambda s: "accept" if s["status"] == "awaiting_acceptance" else END
    )
    graph.add_conditional_edges(
        "accept", lambda s: "delivery" if s["status"] == "waiting_delivery" else END
    )
    graph.add_conditional_edges(
        "delivery",
        lambda s: {
            "delivered": "impact" if s.get("has_customer_feedback") else "remember",
            "waiting_delivery": "delivery",
        }.get(s["status"], END),
    )
    graph.add_conditional_edges(
        "impact",
        lambda s: {
            "customer_impact_verified": "remember",
            "waiting_customer_impact": "impact",
        }.get(s["status"], END),
    )
    graph.add_edge("remember", END)
    return graph.compile(checkpointer=checkpointer)


def _approved(reply: Any, binding: str) -> bool:
    if (
        not isinstance(reply, dict)
        or reply.get("digest") != binding
        or type(reply.get("actor_id")) is not int
        or reply["actor_id"] <= 0
        or type(reply.get("approved")) is not bool
    ):
        raise ValueError(
            "approval must bind the current evidence and authenticated administrator"
        )
    return reply["approved"]
