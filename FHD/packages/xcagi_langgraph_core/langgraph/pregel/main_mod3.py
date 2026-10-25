from __future__ import annotations

import asyncio
import concurrent
import concurrent.futures
import contextlib
import queue
import warnings
import weakref
from collections import defaultdict, deque
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import is_dataclass, replace
from datetime import timedelta
from functools import partial
from inspect import isclass
from typing import (
    Any,
    Generic,
    Literal,
    cast,
    get_type_hints,
    overload,
)
from uuid import UUID, uuid5

from langchain_core._api import beta
from langchain_core.globals import get_debug
from langchain_core.runnables import (
    RunnableSequence,
)
from langchain_core.runnables.base import Input, Output
from langchain_core.runnables.config import (
    RunnableConfig,
    get_async_callback_manager_for_config,
    get_callback_manager_for_config,
)
from langchain_core.runnables.graph import Graph
from langchain_core.runnables.schema import StreamEvent
from langgraph.cache.base import BaseCache
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointTuple,
)
from langgraph.store.base import BaseStore
from pydantic import BaseModel, TypeAdapter
from typing_extensions import Self, Unpack, deprecated, is_typeddict

from langgraph._internal import _serde
from langgraph._internal._config import (
    ensure_config,
    merge_configs,
    patch_checkpoint_map,
    patch_config,
    patch_configurable,
    recast_checkpoint_ns,
)
from langgraph._internal._constants import (
    CACHE_NS_WRITES,
    CONF,
    CONFIG_KEY_CACHE,
    CONFIG_KEY_CHECKPOINT_ID,
    CONFIG_KEY_CHECKPOINT_NS,
    CONFIG_KEY_CHECKPOINTER,
    CONFIG_KEY_DURABILITY,
    CONFIG_KEY_NODE_FINISHED,
    CONFIG_KEY_READ,
    CONFIG_KEY_RUNNER_SUBMIT,
    CONFIG_KEY_RUNTIME,
    CONFIG_KEY_SEND,
    CONFIG_KEY_STREAM,
    CONFIG_KEY_STREAM_MESSAGES_V2,
    CONFIG_KEY_TASK_ID,
    CONFIG_KEY_THREAD_ID,
    ERROR,
    INPUT,
    INTERRUPT,
    NS_END,
    NS_SEP,
    NULL_TASK_ID,
    PUSH,
    TASKS,
)
from langgraph._internal._exception_policy import TERMINATION_ERRORS
from langgraph._internal._pydantic import create_model
from langgraph._internal._queue import (  # type: ignore[attr-defined]
    AsyncQueue,
    SyncQueue,
)
from langgraph._internal._runnable import (
    Runnable,
    RunnableLike,
    RunnableSeq,
    coerce_to_runnable,
)
from langgraph._internal._timeout import coerce_timeout_policy
from langgraph._internal._typing import MISSING, DeprecatedKwargs
from langgraph.callbacks import (
    GraphInterruptEvent,
    GraphResumeEvent,
    get_async_graph_callback_manager_for_config,
    get_sync_graph_callback_manager_for_config,
)
from langgraph.channels.base import BaseChannel
from langgraph.channels.topic import Topic
from langgraph.config import get_config
from langgraph.constants import END
from langgraph.errors import (
    ErrorCode,
    GraphDrained,
    GraphRecursionError,
    InvalidUpdateError,
    create_error_message,
)
from langgraph.managed.base import ManagedValueSpec
from langgraph.pregel._algo import (
    PregelTaskWrites,
    _scratchpad,
    apply_writes,
    local_read,
    prepare_next_tasks,
)
from langgraph.pregel._call import identifier
from langgraph.pregel._checkpoint import (
    achannels_from_checkpoint,
    channels_from_checkpoint,
    copy_checkpoint,
    create_checkpoint,
    create_checkpoint_plan_for_update_state_api,
    empty_checkpoint,
    get_updated_channels_from_tasks,
)
from langgraph.pregel._draw import draw_graph
from langgraph.pregel._io import map_input, read_channels
from langgraph.pregel._loop import (
    AsyncPregelLoop,
    SyncPregelLoop,
)
from langgraph.pregel._messages import (
    StreamMessagesHandler,
    StreamMessagesHandlerV2,
)
from langgraph.pregel._read import DEFAULT_BOUND, PregelNode
from langgraph.pregel._retry import RetryPolicy
from langgraph.pregel._runner import PregelRunner
from langgraph.pregel._tools import StreamToolCallHandler
from langgraph.pregel._utils import (
    get_new_channel_versions,
    validate_timeout_supported,
)
from langgraph.pregel._validate import validate_graph, validate_keys
from langgraph.pregel._write import ChannelWrite, ChannelWriteEntry
from langgraph.pregel.debug import get_bolded_text, get_colored_text, tasks_w_writes
from langgraph.pregel.protocol import PregelProtocol, StreamChunk, StreamProtocol
from langgraph.runtime import (
    DEFAULT_RUNTIME,
    BaseUser,
    RunControl,
    Runtime,
    ServerInfo,
)
from langgraph.stream._mux import StreamMux
from langgraph.stream._types import StreamTransformer
from langgraph.stream.run_stream import AsyncGraphRunStream, GraphRunStream
from langgraph.stream.transformers import (
    LifecycleTransformer,
    MessagesTransformer,
    SubgraphTransformer,
    ValuesTransformer,
)
from langgraph.types import (
    All,
    CachePolicy,
    Checkpointer,
    Command,
    Durability,
    GraphOutput,
    Interrupt,
    Send,
    StateSnapshot,
    StateUpdate,
    StreamMode,
    StreamPart,
    TimeoutPolicy,
    ensure_valid_checkpointer,
)
from langgraph.typing import ContextT, InputT, OutputT, StateT
from langgraph.warnings import LangGraphDeprecatedSinceV10

try:
    from langchain_core.tracers._streaming import _StreamingCallbackHandler
except ImportError:
    _StreamingCallbackHandler = None  # type: ignore

__all__ = ("NodeBuilder", "Pregel")

_WriteValue = Callable[[Input], Output] | Any


def _trigger_to_nodes(nodes: dict[str, PregelNode]) -> Mapping[str, Sequence[str]]:
    """Index from a trigger to nodes that depend on it."""
    trigger_to_nodes: defaultdict[str, list[str]] = defaultdict(list)
    for name, node in nodes.items():
        for trigger in node.triggers:
            trigger_to_nodes[trigger].append(name)
    return dict(trigger_to_nodes)


def _output(
    stream_mode: StreamMode | Sequence[StreamMode],
    print_mode: StreamMode | Sequence[StreamMode],
    stream_subgraphs: bool,
    getter: Callable[[], tuple[tuple[str, ...], str, Any]],
    empty_exc: type[Exception],
    version: Literal["v1", "v2"] = "v1",
    output_mapper: Callable[[Any], Any] | None = None,
    state_mapper: Callable[[Any], Any] | None = None,
) -> Iterator:
    while True:
        try:
            ns, mode, payload = getter()
        except empty_exc:
            break
        if mode in print_mode:
            if stream_subgraphs and ns:
                print(
                    " ".join(
                        (
                            get_bolded_text(f"[{mode}]"),
                            get_colored_text(f"[graph={ns}]", color="yellow"),
                            repr(payload),
                        )
                    )
                )
            else:
                print(
                    " ".join(
                        (
                            get_bolded_text(f"[{mode}]"),
                            repr(payload),
                        )
                    )
                )
        if mode in stream_mode:
            if version == "v2":
                if mode == "values":
                    # pop __interrupt__ into typed field, coerce data
                    ints: tuple[Interrupt, ...] = ()
                    if isinstance(payload, dict):
                        ints = payload.pop(INTERRUPT, ())
                        if output_mapper:
                            payload = output_mapper(payload)
                    yield {"type": mode, "ns": ns, "data": payload, "interrupts": ints}
                elif mode in ("checkpoints", "debug"):
                    # coerce state values in checkpoint/debug payloads
                    if state_mapper:
                        _coerce_checkpoint_values(payload, state_mapper)
                    yield {"type": mode, "ns": ns, "data": payload}
                else:
                    yield {"type": mode, "ns": ns, "data": payload}
            elif stream_subgraphs and isinstance(stream_mode, list):
                yield (ns, mode, payload)
            elif isinstance(stream_mode, list):
                yield (mode, payload)
            elif stream_subgraphs:
                yield (ns, payload)
            else:
                yield payload


def _coerce_checkpoint_values(payload: Any, mapper: Callable[[Any], Any]) -> None:
    """Coerce `values` dicts inside checkpoint or debug payloads in-place.

    Skips the initial checkpoint (where next contains ``__start__``) because
    not all channels are populated yet and coercion would fail.
    """
    _START = "__start__"
    # debug wrapper: {"type": "checkpoint", "payload": {"values": dict, ...}}
    if (
        isinstance(payload, dict)
        and payload.get("type") == "checkpoint"
        and isinstance(payload.get("payload"), dict)
        and isinstance(payload["payload"].get("values"), dict)
        and _START not in payload["payload"].get("next", ())
    ):
        payload["payload"]["values"] = mapper(payload["payload"]["values"])
    # direct checkpoint payload: {"values": dict, ...}
    elif (
        isinstance(payload, dict)
        and isinstance(payload.get("values"), dict)
        and _START not in payload.get("next", ())
    ):
        payload["values"] = mapper(payload["values"])


def _resolve_parent_ns(
    graph_config: RunnableConfig | None, call_config: RunnableConfig | None
) -> tuple[str, ...]:
    """Return the checkpoint namespace the caller is running under.

    `stream_events(version="v3")` uses this to scope its native projections
    (`ValuesTransformer`, `MessagesTransformer`) to events emitted at
    the run's own level. A root call resolves to `()`; a call made
    from inside a node carries the outer graph's task namespace so the
    projection still matches its own root-level events.
    """
    merged = ensure_config(graph_config, call_config)
    ns = merged.get(CONF, {}).get(CONFIG_KEY_CHECKPOINT_NS)
    if not ns:
        return ()
    return tuple(ns.split(NS_SEP))


def _coerce_parent_runtime(value: Any) -> Runtime[Any]:
    """Normalize the value stored under `CONFIG_KEY_RUNTIME` into a `Runtime`.

    During a graph run this is always a `Runtime` the framework created and
    published for child tasks to inherit. Layers outside the run (for example a
    server's graph-factory path) may instead seed an object that only carries
    `context`/`store`. Adopt its `context` so context set at the graph level
    plumbs through (`merge` lets the run's own `context` take precedence when
    one is provided). `store` is resolved separately (passed to the graph
    directly), so it is not read off here. `merge` then combines this with the
    run's own runtime, including the framework's `control`.
    """
    if isinstance(value, Runtime):
        return value
    return Runtime(context=getattr(value, "context", None))


def _build_server_info(
    config: RunnableConfig, parent_runtime: Runtime[Any]
) -> ServerInfo | None:
    """Build ServerInfo from config configurable.

    The server puts assistant_id/graph_id in config configurable and the
    authenticated user dict in configurable["langgraph_auth_user"].
    """
    configurable = config.get(CONF) or {}
    assistant_id = configurable.get("assistant_id")
    graph_id = configurable.get("graph_id")

    # Read authenticated user from configurable (set by LangGraph Server).
    # We prefer isinstance(BaseUser) but fall back to hasattr("identity")
    # because the server's ProxyUser provides `permissions` via __getattr__,
    # which Python's runtime_checkable Protocol check doesn't see.
    auth_user_data = configurable.get("langgraph_auth_user")
    user: BaseUser | None = None
    if auth_user_data is not None:
        if isinstance(auth_user_data, BaseUser) or hasattr(auth_user_data, "identity"):
            user = cast(BaseUser, auth_user_data)

    if assistant_id is not None or graph_id is not None or user is not None:
        return ServerInfo(
            assistant_id=str(assistant_id) if assistant_id else "",
            graph_id=str(graph_id) if graph_id else "",
            user=user,
        )
    return None


def _coerce_context(
    context_schema: type[ContextT] | None, context: Any
) -> ContextT | None:
    """Coerce context input to the appropriate schema type.

    If context is a dict and context_schema is a dataclass or pydantic model, we coerce.
    Else, we return the context as-is.

    Args:
        context_schema: The schema type to coerce to (BaseModel, dataclass, or TypedDict)
        context: The context value to coerce

    Returns:
        The coerced context value or None if context is None
    """
    if context is None:
        return None

    if context_schema is None:
        return context

    schema_is_class = issubclass(context_schema, BaseModel) or is_dataclass(
        context_schema
    )
    if isinstance(context, dict) and schema_is_class:
        return context_schema(**context)  # type: ignore[misc]

    return cast(ContextT, context)
