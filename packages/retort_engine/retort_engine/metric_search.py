"""WeCo/AIDE-style metric-driven solution-tree search for Retort.

V1: best-first expansion with beam width, hard node budget, parseable eval metrics.
Does not trigger ops-autonomy actions (restart/freeze/etc.).
"""

from __future__ import annotations

import json
import re
import shlex
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from retort_engine.bounded_agent_loop import persist_trajectory, run_bounded_agent_loop
from retort_engine.models import ImprovementTask, ProjectAssessment
from retort_engine.process_safety import run_command_with_process_group

NODE_STATUSES = frozenset({"draft", "running", "scored", "failed", "pruned"})


@dataclass
class EvalSpec:
    metric_name: str
    eval_command: str
    higher_is_better: bool = True
    parse_regex: str = ""

    def __post_init__(self) -> None:
        if not str(self.metric_name or "").strip():
            raise ValueError("metric_name must not be empty")
        if not str(self.eval_command or "").strip():
            raise ValueError("eval_command must not be empty")
        if not self.parse_regex:
            self.parse_regex = rf"{re.escape(self.metric_name)}:\s*([0-9.]+)"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> EvalSpec:
        data = dict(payload or {})
        return cls(
            metric_name=str(data.get("metric_name") or ""),
            eval_command=str(data.get("eval_command") or ""),
            higher_is_better=bool(data.get("higher_is_better", True)),
            parse_regex=str(data.get("parse_regex") or ""),
        )


@dataclass
class SolutionNode:
    node_id: str
    parent_id: str | None
    status: str
    metric_name: str
    metric_value: float | None = None
    patch_summary: str = ""
    files_touched: list[str] = field(default_factory=list)
    worktree_path: str = ""
    trajectory_path: str = ""
    created_from: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        if self.status not in NODE_STATUSES:
            raise ValueError(f"invalid node status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SolutionNode:
        return cls(
            node_id=str(payload.get("node_id") or ""),
            parent_id=(
                None
                if payload.get("parent_id") in (None, "")
                else str(payload.get("parent_id"))
            ),
            status=str(payload.get("status") or "draft"),
            metric_name=str(payload.get("metric_name") or ""),
            metric_value=(
                None
                if payload.get("metric_value") is None
                else float(payload["metric_value"])
            ),
            patch_summary=str(payload.get("patch_summary") or ""),
            files_touched=[str(x) for x in (payload.get("files_touched") or [])],
            worktree_path=str(payload.get("worktree_path") or ""),
            trajectory_path=str(payload.get("trajectory_path") or ""),
            created_from=str(payload.get("created_from") or ""),
            error=str(payload.get("error") or ""),
        )


class SolutionTree:
    def __init__(self, metric_name: str, *, higher_is_better: bool = True) -> None:
        self.metric_name = metric_name
        self.higher_is_better = higher_is_better
        self.nodes: dict[str, SolutionNode] = {}
        self.root_id: str = ""

    def add(self, node: SolutionNode) -> SolutionNode:
        if not node.node_id:
            raise ValueError("node_id must not be empty")
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate node_id: {node.node_id}")
        if node.parent_id is None:
            if self.root_id:
                raise ValueError("tree already has a root")
            self.root_id = node.node_id
        elif node.parent_id not in self.nodes:
            raise ValueError(f"unknown parent_id: {node.parent_id}")
        self.nodes[node.node_id] = node
        return node

    def scored_nodes(self) -> list[SolutionNode]:
        return [
            n
            for n in self.nodes.values()
            if n.status == "scored" and n.metric_value is not None
        ]

    def best_node(self) -> SolutionNode | None:
        scored = self.scored_nodes()
        if not scored:
            return None
        return max(scored, key=self._rank_key)

    def select_expand_parent(self) -> SolutionNode | None:
        return self.best_node()

    def _rank_key(self, node: SolutionNode) -> tuple[float, str]:
        value = float(node.metric_value or 0.0)
        score = value if self.higher_is_better else -value
        return (score, node.node_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "higher_is_better": self.higher_is_better,
            "root_id": self.root_id,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SolutionTree:
        tree = cls(
            str(payload.get("metric_name") or ""),
            higher_is_better=bool(payload.get("higher_is_better", True)),
        )
        for raw in payload.get("nodes") or []:
            tree.add(SolutionNode.from_dict(dict(raw)))
        if payload.get("root_id"):
            tree.root_id = str(payload["root_id"])
        return tree

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target


def parse_metric_from_output(text: str, eval_spec: EvalSpec) -> float | None:
    match = re.search(eval_spec.parse_regex, text or "", flags=re.MULTILINE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError, IndexError):
        return None


def run_eval_command(
    eval_spec: EvalSpec,
    *,
    cwd: str | Path,
    timeout_sec: float = 120.0,
    command_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run eval_command and parse a numeric metric. Parse failure => failed trial."""
    runner = command_runner or run_command_with_process_group
    command = shlex.split(eval_spec.eval_command)
    raw = runner(command, cwd=str(cwd), timeout_sec=timeout_sec)
    combined = f"{raw.get('stdout') or ''}\n{raw.get('stderr') or ''}"
    value = parse_metric_from_output(combined, eval_spec)
    ok = (
        value is not None
        and not raw.get("timed_out")
        and int(raw.get("returncode") or 0) == 0
    )
    return {
        "ok": ok,
        "metric_value": value,
        "raw": raw,
        "combined_output": combined,
        "error": ""
        if ok
        else (
            "metric_parse_failed"
            if value is None
            else ("eval_timed_out" if raw.get("timed_out") else "eval_nonzero_exit")
        ),
    }


ExpandFn = Callable[[SolutionNode, int], list[dict[str, Any]]]


@dataclass
class MetricSearchConfig:
    project: str | Path
    eval_spec: EvalSpec
    max_nodes: int = 8
    beam: int = 2
    wall_time_limit_sec: float = 300.0
    eval_timeout_sec: float = 120.0
    run_id: str = ""
    output_dir: str | Path | None = None
    objective: str = "Improve metric via bounded code trials"
    expand_fn: ExpandFn | None = None
    command_runner: Callable[..., dict[str, Any]] | None = None
    # When True, root is scored via eval; children use expand_fn then eval.
    score_root: bool = True


def _default_expand_fn(parent: SolutionNode, child_index: int) -> list[dict[str, Any]]:
    """Produce one child proposal; patch application is left to caller/agent loop."""
    return [
        {
            "patch_summary": f"variant from {parent.node_id} #{child_index}",
            "files_touched": list(parent.files_touched[:5]),
            "created_from": f"best_first:{parent.node_id}:{child_index}",
        }
    ]


def _run_child_agent(
    *,
    objective: str,
    run_dir: Path,
    node_id: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Bounded agent loop as node executor (planner proposes the trial summary)."""

    def planner(_obj: str, _traj: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "kind": "metric_trial",
            "summary": proposal.get("patch_summary") or "",
            "files": list(proposal.get("files_touched") or []),
        }

    def executor(action: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "action": action}

    def judge(_obj: str, traj: list[dict[str, Any]]) -> dict[str, Any]:
        return {"complete": bool(traj), "score": 1.0, "missing": ""}

    result = run_bounded_agent_loop(
        objective,
        planner=planner,
        executor=executor,
        judge=judge,
        max_steps=2,
        wall_time_limit_sec=30.0,
        trajectory_dir=run_dir / "trajectories",
        run_id=node_id,
    )
    return result


def run_metric_search(config: MetricSearchConfig) -> dict[str, Any]:
    if config.max_nodes < 1:
        raise ValueError("max_nodes must be >= 1")
    if config.beam < 1:
        raise ValueError("beam must be >= 1")
    project = Path(config.project).expanduser().resolve()
    run_id = config.run_id or uuid.uuid4().hex[:12]
    run_dir = (
        Path(config.output_dir or (project / ".retort" / "metric_search" / run_id))
        .expanduser()
        .resolve()
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    tree = SolutionTree(
        config.eval_spec.metric_name,
        higher_is_better=config.eval_spec.higher_is_better,
    )
    expand_fn = config.expand_fn or _default_expand_fn
    started = time.monotonic()
    stop_reason = "max_nodes"

    root = SolutionNode(
        node_id=f"n-{run_id}-root",
        parent_id=None,
        status="running",
        metric_name=config.eval_spec.metric_name,
        worktree_path=str(project),
        created_from="root",
        patch_summary="baseline",
    )
    tree.add(root)

    if config.score_root:
        eval_result = run_eval_command(
            config.eval_spec,
            cwd=project,
            timeout_sec=config.eval_timeout_sec,
            command_runner=config.command_runner,
        )
        if eval_result["ok"]:
            root.status = "scored"
            root.metric_value = float(eval_result["metric_value"])
        else:
            root.status = "failed"
            root.error = str(eval_result["error"])
    else:
        root.status = "scored"
        root.metric_value = 0.0

    tree.save(run_dir / "tree.json")

    while len(tree.nodes) < config.max_nodes:
        if time.monotonic() - started >= config.wall_time_limit_sec:
            stop_reason = "time_limit"
            break
        parent = tree.select_expand_parent()
        if parent is None:
            stop_reason = "no_scored_parent"
            break
        slots = min(config.beam, config.max_nodes - len(tree.nodes))
        if slots <= 0:
            break
        expanded_any = False
        for child_index in range(1, slots + 1):
            proposals = expand_fn(parent, child_index)
            if not proposals:
                continue
            proposal = dict(proposals[0])
            # Allow synthetic expand_fn to return multiple via repeated calls;
            # here we take first proposal per beam slot.
            node_id = f"n-{run_id}-{len(tree.nodes):02d}"
            child = SolutionNode(
                node_id=node_id,
                parent_id=parent.node_id,
                status="running",
                metric_name=config.eval_spec.metric_name,
                patch_summary=str(proposal.get("patch_summary") or ""),
                files_touched=[str(x) for x in (proposal.get("files_touched") or [])][
                    :5
                ],
                worktree_path=str(proposal.get("worktree_path") or project),
                created_from=str(proposal.get("created_from") or parent.node_id),
            )
            tree.add(child)
            expanded_any = True

            if "metric_value" in proposal and proposal["metric_value"] is not None:
                # Test/synthetic path: skip shell eval when metric injected.
                child.status = "scored"
                child.metric_value = float(proposal["metric_value"])
                child.patch_summary = child.patch_summary or "synthetic_metric"
            else:
                agent = _run_child_agent(
                    objective=config.objective,
                    run_dir=run_dir,
                    node_id=node_id,
                    proposal=proposal,
                )
                child.trajectory_path = str(
                    agent.get("summary", {}).get("trajectory_path") or ""
                )
                if not child.trajectory_path:
                    traj_path = persist_trajectory(
                        {
                            "node_id": node_id,
                            "parent_id": parent.node_id,
                            "agent": agent,
                        },
                        run_dir / "trajectories",
                        run_id=node_id,
                    )
                    child.trajectory_path = str(traj_path)

                eval_result = run_eval_command(
                    config.eval_spec,
                    cwd=child.worktree_path or project,
                    timeout_sec=config.eval_timeout_sec,
                    command_runner=config.command_runner,
                )
                if eval_result["ok"]:
                    child.status = "scored"
                    child.metric_value = float(eval_result["metric_value"])
                else:
                    child.status = "failed"
                    child.error = str(eval_result["error"])

            tree.save(run_dir / "tree.json")
            if len(tree.nodes) >= config.max_nodes:
                break
        if not expanded_any:
            stop_reason = "expand_exhausted"
            break

    best = tree.best_node()
    tree_path = tree.save(run_dir / "tree.json")
    report = {
        "status": "ok" if best is not None else "failed",
        "run_id": run_id,
        "stop_reason": stop_reason,
        "project": str(project),
        "tree_path": str(tree_path),
        "eval_spec": config.eval_spec.to_dict(),
        "nodes_evaluated": len(tree.nodes),
        "scored_count": len(tree.scored_nodes()),
        "best_node_id": best.node_id if best else "",
        "best_score": best.metric_value if best else None,
        "best_node": best.to_dict() if best else None,
        "elapsed_sec": round(time.monotonic() - started, 6),
        "max_nodes": config.max_nodes,
        "beam": config.beam,
        "files_written": list(best.files_touched) if best else [],
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


class MetricTreeSearchImprover:
    """RetortImprover that runs one metric-search cycle per improve() call."""

    def __init__(
        self,
        *,
        project: str | Path,
        eval_spec: EvalSpec,
        max_nodes: int = 8,
        beam: int = 2,
        expand_fn: ExpandFn | None = None,
        command_runner: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.project = project
        self.eval_spec = eval_spec
        self.max_nodes = max_nodes
        self.beam = beam
        self.expand_fn = expand_fn
        self.command_runner = command_runner

    def improve(
        self,
        state: dict[str, Any],
        assessment: ProjectAssessment,
        tasks: tuple[ImprovementTask, ...],
        round_index: int,
    ) -> dict[str, Any]:
        del assessment, tasks  # metric-search uses eval_spec, not score backlog
        report = run_metric_search(
            MetricSearchConfig(
                project=self.project,
                eval_spec=self.eval_spec,
                max_nodes=self.max_nodes,
                beam=self.beam,
                run_id=f"improv-r{round_index:02d}-{uuid.uuid4().hex[:8]}",
                expand_fn=self.expand_fn,
                command_runner=self.command_runner,
                objective=f"Retort improve round {round_index}",
            )
        )
        next_state = dict(state)
        next_state["retort_metric_search"] = report
        next_state["retort_last_round"] = round_index
        if report.get("best_score") is not None:
            next_state["retort_last_metric"] = {
                "name": self.eval_spec.metric_name,
                "value": report["best_score"],
                "node_id": report.get("best_node_id"),
            }
        return next_state
