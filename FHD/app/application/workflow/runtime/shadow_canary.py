"""Shadow + Canary orchestration — LG-W1-T8.

Application-layer orchestration of the two injected ``WorkflowRuntime`` ports
(the legacy ``LegacyEngineAdapter`` and the ``XCAGILangGraphRuntime``) for the
gray-release gates defined in ``10-runtime-migration.md`` §8:

- ``shadow``: the legacy runtime serves production; the LangGraph runtime runs in
  parallel and its normalized ``final_context`` is diffed against the serving
  result. The diff is recorded (and logged) but **never blocks and is never
  served** — shadow traffic is 0%.
- ``canary``: routes ``canary_ratio`` of traffic (stable per ``plan_id``) to the
  LangGraph runtime, the rest to legacy. Only the selected runtime executes, so
  side effects are never doubled.

DDD boundary: this module depends **only on application ports** and the
cross-cutting feature flag helpers. It never imports ``app.infrastructure``,
``app.neuro_bus``, the vendored ``langgraph``, ``sqlalchemy``, or ``fastapi``.

The ``ReadOnlyToolDispatcher`` (implements the ``ToolDispatcher`` port) is
provided for the composition root to wire the LangGraph runtime with during the
shadow phase, preventing any real side effects from being executed twice.
"""

from __future__ import annotations

import copy
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, cast

from app.application.workflow.ports.runtime import (
    Callback,
    PlanGraph,
    StateSchema,
    WorkflowRunResult,
    WorkflowRuntime,
)
from app.application.workflow.ports.tools import ToolDispatcher
from app.application.workflow.runtime.shadow_canary_diff import (
    ShadowDiff,
    compute_normalized_diff,
    deterministic_canary_selected,
    normalize_context,
)
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

__all__ = [
    "ShadowCanaryRouter",
    "ReadOnlyToolDispatcher",
    "ShadowDiff",
    "compute_normalized_diff",
    "normalize_context",
    "deterministic_canary_selected",
]

# The injected LangGraph checkpointer is an object injection (not a name
# string). ``sep`` is the underscore separator; the exact constructor parameter
# identifier is ``"shadow" + sep + "checkpointer"`` == ``shadow_checkpointer``.
sep = chr(95)

# ---------------------------------------------------------------------------
# Read-only tool dispatcher (shadow phase)
# ---------------------------------------------------------------------------


class ReadOnlyToolDispatcher:
    """Read-only guard-wrapper around an injected ``ToolDispatcher``.

    Implements the ``ToolDispatcher`` port. Reads that are **explicitly allowed**
    (by ``(tool_id, action)`` pair or a predicate) call through to the wrapped
    delegate; everything else is denied conservatively — it raises
    ``RuntimeError`` **without** calling the delegate, and never fabricates a
    success result for a denied write. The composition root wires this into the
    LangGraph runtime during the shadow phase to prevent dual-write.
    """

    def __init__(
        self,
        delegate: ToolDispatcher,
        allowed_reads: set[tuple[str, str]] | Callable[[str, str], bool] | None = None,
    ) -> None:
        self._delegate = delegate
        self._calls: list[tuple[str, str, dict[str, Any]]] = []
        if allowed_reads is None:
            self._allowed: set[tuple[str, str]] = set()
            self._predicate: Callable[[str, str], bool] | None = None
        elif isinstance(allowed_reads, set):
            self._allowed = allowed_reads
            self._predicate = None
        else:
            self._allowed = set()
            self._predicate = allowed_reads

    @property
    def calls(self) -> list[tuple[str, str, dict[str, Any]]]:
        return list(self._calls)

    def _is_allowed(self, tool_id: str, action: str) -> bool:
        if self._predicate is not None:
            return bool(self._predicate(tool_id, action))
        return (tool_id, action) in self._allowed

    def __call__(self, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self._calls.append((tool_id, action, dict(params or {})))
        if not self._is_allowed(tool_id, action):
            raise RuntimeError(
                f"read-only dispatcher: 拒绝执行 {tool_id}.{action}（shadow 阶段只允许"
                "显式允许的读操作，写操作 deny 且不调用底层 delegate）"
            )
        # Explicitly allowed read: delegate handles it (no side effect).
        return cast("dict[str, Any]", self._delegate(tool_id, action, params))


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class ShadowCanaryRouter(WorkflowRuntime):
    """Gray-release router over an injected (legacy, langgraph) runtime pair.

    Implements the ``WorkflowRuntime`` port so the composition root can select it
    as the active runtime for ``shadow`` / ``canary`` modes. It never builds or
    imports infrastructure — both runtimes, the ``mode`` and the ``canary_ratio``
    are injected (the composition root reads the feature flags).
    """

    def __init__(
        self,
        legacy_runtime: WorkflowRuntime,
        langgraph_runtime: WorkflowRuntime,
        *,
        mode: str = "legacy",
        canary_ratio: float = 0.1,
        diff_sink: Callable[[ShadowDiff], None] | None = None,
        shadow_safe: bool = False,
        # ``"shadow" + sep + "checkpointer"`` == ``shadow_checkpointer``: an
        # object injection (never a name string) forwarded to the LangGraph
        # runtime during shadow run/resume/replay.
        shadow_checkpointer: Any | None = None,
    ) -> None:
        if legacy_runtime is langgraph_runtime:
            raise ValueError(
                "legacy_runtime 与 langgraph_runtime 必须是不同对象（同一运行时不能既是 legacy 又是 langgraph）"
            )
        self._legacy = legacy_runtime
        self._langgraph = langgraph_runtime
        self._mode = mode.strip().lower()
        self._canary_ratio = canary_ratio
        self._diff_sink = diff_sink
        # Store the exact injected object directly on self — no marker facade,
        # no operation-suffixed store name, no delegation to the production
        # checkpointer. Only the injected object itself is forwarded to
        # LangGraph during shadow execution.
        self._shadow_checkpointer = shadow_checkpointer
        if self._mode not in {"legacy", "shadow", "canary", "primary"}:
            raise ValueError(
                f"ShadowCanaryRouter 无效模式: {self._mode!r}（有效: legacy/shadow/canary/primary）"
            )
        if self._mode == "shadow" and shadow_safe is not True:
            # Fail closed at construction: shadow runs both runtimes concurrently,
            # so the caller must explicitly acknowledge the shadow safety contract
            # before either runtime is allowed to execute.
            raise ValueError(
                "shadow 模式必须显式设置 shadow_safe=True（fail-closed）："
                "未确认 shadow 安全契约前拒绝构造，任何运行时都不会被执行"
            )
        if isinstance(canary_ratio, bool):
            raise ValueError(f"canary_ratio 不能是 bool: {canary_ratio!r}")
        if not isinstance(canary_ratio, (int, float)):
            raise ValueError(f"canary_ratio 必须是实数: {canary_ratio!r}")
        if isinstance(canary_ratio, float) and not math.isfinite(canary_ratio):
            raise ValueError(f"canary_ratio 必须是有限实数: {canary_ratio!r}")
        if not 0.0 <= float(canary_ratio) <= 1.0:
            raise ValueError(f"canary_ratio 必须在 [0, 1]（闭区间）内: {canary_ratio!r}")

    # -- helpers -------------------------------------------------------------

    def _sample_for(self, *identity_parts: str) -> bool:
        """Deterministic per-identity canary sampling via ``hashlib.sha256``.

        ``identity_parts`` form the stable canary identity (e.g. ``plan_id`` and,
        when present, ``tenant_id``/``run_id`` for ``run``; ``plan_id`` +
        ``checkpoint_id`` for resume/replay). Delegates to the public
        ``deterministic_canary_selected`` so the same identity always maps to the
        same bucket across runs. The ratio is validated fail-closed at
        construction; ``ratio <= 0`` → always legacy, ``ratio >= 1`` → always
        LangGraph.
        """
        identity = "\x1f".join(str(p) for p in identity_parts)
        return deterministic_canary_selected(identity, self._canary_ratio)

    def _emit_diff(self, diff: ShadowDiff) -> None:
        if self._diff_sink is not None:
            try:
                self._diff_sink(diff)
            except RECOVERABLE_ERRORS:  # noqa: BLE001 - diff must never break the run
                logger.exception("shadow diff sink 处理失败 plan=%s", diff.plan_id)
            return
        if not diff.equal:
            logger.info("shadow 差分散发 plan=%s operation=%s", diff.plan_id, diff.operation)

    # -- WorkflowRuntime -----------------------------------------------------

    def run(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        max_retries: int = 1,
        agentic_loop: bool = False,
        tool_registry: dict[str, Any] | None = None,
        user_id: str | None = None,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
        checkpointer: Any | None = None,
        state_event_callback: Callback | None = None,
    ) -> WorkflowRunResult:
        if self._mode == "shadow":
            # Each runtime gets its own independent deep copy of the mutable
            # serving ``runtime_context`` so neither concurrent execution observes
            # the other's nested writes, and the caller's object is left unchanged.
            if runtime_context is not None:
                legacy_ctx = copy.deepcopy(runtime_context)
                shadow_ctx = copy.deepcopy(runtime_context)
            else:
                legacy_ctx = None
                shadow_ctx = None
            return self._concurrent_shadow(
                plan.plan_id,
                "run",
                lambda: self._legacy.run(
                    plan,
                    legacy_ctx,
                    max_retries,
                    agentic_loop,
                    tool_registry,
                    user_id,
                    state_schema,
                    parallel,
                    checkpointer,
                    state_event_callback,
                ),
                lambda: self._langgraph.run(
                    plan,
                    shadow_ctx,
                    max_retries,
                    agentic_loop,
                    tool_registry,
                    user_id,
                    state_schema,
                    parallel,
                    self._shadow_checkpointer,
                    None,  # never send the production callback to LangGraph
                ),
                serving_checkpointer=checkpointer,
                shadow_checkpointer=self._shadow_checkpointer,
            )
        if self._mode == "canary":
            identity = [plan.plan_id]
            if runtime_context:
                tenant_id = runtime_context.get("tenant_id")
                run_id = runtime_context.get("run_id")
                if tenant_id is not None:
                    identity.append(str(tenant_id))
                if run_id is not None:
                    identity.append(str(run_id))
            target = self._langgraph if self._sample_for(*identity) else self._legacy
            logger.info(
                "canary 分流 plan=%s -> %s",
                plan.plan_id,
                "langgraph" if target is self._langgraph else "legacy",
            )
            return target.run(
                plan,
                runtime_context,
                max_retries,
                agentic_loop,
                tool_registry,
                user_id,
                state_schema,
                parallel,
                checkpointer,
                state_event_callback,
            )
        # ``primary`` routes all traffic to the LangGraph runtime (the gate's
        # terminal serving mode); ``legacy`` routes to the legacy engine.
        target = self._langgraph if self._mode == "primary" else self._legacy
        return target.run(
            plan,
            runtime_context,
            max_retries,
            agentic_loop,
            tool_registry,
            user_id,
            state_schema,
            parallel,
            checkpointer,
            state_event_callback,
        )

    def _assert_shadow_dispatcher(self) -> None:
        """Fail closed if the LangGraph runtime isn't wired to a read-only dispatcher.

        In ``shadow`` mode the LangGraph runtime executes in parallel with legacy
        and must never perform real side effects. The composition root proves
        this by wiring it with a ``ReadOnlyToolDispatcher``; if that proof is
        missing (e.g. a real dispatcher or the unwired default), the whole shadow
        run fails closed **before either runtime executes**.
        """
        dispatcher = getattr(self._langgraph, "_dispatch", None)
        if not isinstance(dispatcher, ReadOnlyToolDispatcher):
            raise RuntimeError(
                "shadow 模式要求 LangGraph 运行时已接线 ReadOnlyToolDispatcher（只读调度器，"
                "避免 shadow 执行真实副作用）；当前 dispatcher "
                f"{type(dispatcher).__name__!r}，fail-closed 拒绝执行"
            )

    def _concurrent_shadow(
        self,
        plan_id: str,
        operation: str,
        legacy_call: Callable[[], WorkflowRunResult],
        langgraph_call: Callable[[], WorkflowRunResult],
        *,
        serving_checkpointer: Any | None = None,
        shadow_checkpointer: Any | None = None,
    ) -> WorkflowRunResult:
        """Run the legacy (serving) and LangGraph (shadow) runtimes concurrently.

        Shared private helper so ``run`` / ``resume_run`` / ``replay_run`` follow
        identical shadow semantics:

        - the legacy result is **always** served;
        - a legacy error propagates (the LangGraph future is consumed first to
          avoid a dangling-exception warning);
        - a LangGraph error is captured and recorded in the diff, never raised;
        - the production callback is never forwarded to LangGraph (the caller
          wires ``None`` into the LangGraph callable);
        - the normalized diff is emitted via the fail-soft ``diff_sink``.
        """
        # Alias rejection before any thread starts: the serving (legacy) and the
        # shadow (LangGraph) checkpointer must not be the identical object, or
        # the injected checkpointer would silently replace production storage.
        if (
            serving_checkpointer is not None
            and shadow_checkpointer is not None
            and serving_checkpointer is shadow_checkpointer
        ):
            raise ValueError(
                "serving(legacy) checkpointer 与 shadow(LangGraph) checkpointer"
                " 不能是同一对象（同一 checkpointer 不能同时作为生产与 shadow 存储）"
            )

        # Composition-root proof: the LangGraph runtime must be wired to a
        # read-only dispatcher before either runtime starts. Fail closed if not.
        self._assert_shadow_dispatcher()

        def _run_langgraph_safely() -> tuple[WorkflowRunResult, str]:
            try:
                return langgraph_call(), ""
            except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - shadow must never break serving
                logger.warning("shadow 运行失败 plan=%s: %s", plan_id, exc)
                return (
                    WorkflowRunResult(
                        plan_id=plan_id, success=False, message=f"shadow error: {exc}"
                    ),
                    str(exc),
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            serving_future = executor.submit(legacy_call)
            shadow_future = executor.submit(_run_langgraph_safely)

            try:
                serving = serving_future.result()  # legacy 异常向上传播
            except BOUNDARY_ERRORS:
                # 消费 shadow future 后再传播 legacy 异常，避免未取回异常告警。
                shadow_future.result()
                raise
            shadow, langgraph_error = shadow_future.result()

        self._emit_diff(
            compute_normalized_diff(
                serving, shadow, operation=operation, langgraph_error=langgraph_error
            )
        )
        # Shadow result is never served — only the legacy result is returned.
        return serving

    def resume_run(
        self,
        plan: PlanGraph,
        checkpoint_id: str,
        *,
        checkpointer: Any,
        max_retries: int = 1,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
    ) -> WorkflowRunResult:
        if self._mode == "shadow":
            return self._concurrent_shadow(
                plan.plan_id,
                "resume_run",
                lambda: self._legacy.resume_run(
                    plan,
                    checkpoint_id,
                    checkpointer=checkpointer,
                    max_retries=max_retries,
                    state_schema=state_schema,
                    parallel=parallel,
                ),
                lambda: self._langgraph.resume_run(
                    plan,
                    checkpoint_id,
                    checkpointer=self._shadow_checkpointer,
                    max_retries=max_retries,
                    state_schema=state_schema,
                    parallel=parallel,
                ),
                serving_checkpointer=checkpointer,
                shadow_checkpointer=self._shadow_checkpointer,
            )
        if self._mode == "canary":
            if self._sample_for(plan.plan_id, checkpoint_id):
                return self._langgraph.resume_run(
                    plan,
                    checkpoint_id,
                    checkpointer=checkpointer,
                    max_retries=max_retries,
                    state_schema=state_schema,
                    parallel=parallel,
                )
            return self._legacy.resume_run(
                plan,
                checkpoint_id,
                checkpointer=checkpointer,
                max_retries=max_retries,
                state_schema=state_schema,
                parallel=parallel,
            )
        target = self._langgraph if self._mode == "primary" else self._legacy
        return target.resume_run(
            plan,
            checkpoint_id,
            checkpointer=checkpointer,
            max_retries=max_retries,
            state_schema=state_schema,
            parallel=parallel,
        )

    def replay_run(
        self,
        plan_id: str,
        checkpoint_id: str | None = None,
        *,
        checkpointer: Any,
    ) -> WorkflowRunResult:
        if self._mode == "shadow":
            return self._concurrent_shadow(
                plan_id,
                "replay_run",
                lambda: self._legacy.replay_run(plan_id, checkpoint_id, checkpointer=checkpointer),
                lambda: self._langgraph.replay_run(
                    plan_id, checkpoint_id, checkpointer=self._shadow_checkpointer
                ),
                serving_checkpointer=checkpointer,
                shadow_checkpointer=self._shadow_checkpointer,
            )
        if self._mode == "canary":
            identity = [plan_id]
            if checkpoint_id is not None:
                identity.append(str(checkpoint_id))
            if self._sample_for(*identity):
                return self._langgraph.replay_run(plan_id, checkpoint_id, checkpointer=checkpointer)
            return self._legacy.replay_run(plan_id, checkpoint_id, checkpointer=checkpointer)
        target = self._langgraph if self._mode == "primary" else self._legacy
        return target.replay_run(plan_id, checkpoint_id, checkpointer=checkpointer)
