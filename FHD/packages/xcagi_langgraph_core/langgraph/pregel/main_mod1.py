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


class NodeBuilder:
    __slots__ = (
        "_channels",
        "_triggers",
        "_tags",
        "_metadata",
        "_writes",
        "_bound",
        "_retry_policy",
        "_cache_policy",
        "_timeout",
    )

    _channels: str | list[str]
    _triggers: list[str]
    _tags: list[str]
    _metadata: dict[str, Any]
    _writes: list[ChannelWriteEntry]
    _bound: Runnable
    _retry_policy: list[RetryPolicy]
    _cache_policy: CachePolicy | None
    _timeout: TimeoutPolicy | None

    def __init__(
        self,
    ) -> None:
        self._channels = []
        self._triggers = []
        self._tags = []
        self._metadata = {}
        self._writes = []
        self._bound = DEFAULT_BOUND
        self._retry_policy = []
        self._cache_policy = None
        self._timeout = None

    def subscribe_only(
        self,
        channel: str,
    ) -> Self:
        """Subscribe to a single channel."""
        if not self._channels:
            self._channels = channel
        else:
            raise ValueError(
                "Cannot subscribe to single channels when other channels are already subscribed to"
            )

        self._triggers.append(channel)

        return self

    def subscribe_to(
        self,
        *channels: str,
        read: bool = True,
    ) -> Self:
        """Add channels to subscribe to.

        Node will be invoked when any of these channels are updated, with a dict of the
        channel values as input.

        Args:
            channels: Channel name(s) to subscribe to
            read: If `True`, the channels will be included in the input to the node.
                Otherwise, they will trigger the node without being sent in input.

        Returns:
            Self for chaining
        """
        if isinstance(self._channels, str):
            raise ValueError(
                "Cannot subscribe to channels when subscribed to a single channel"
            )
        if read:
            if not self._channels:
                self._channels = list(channels)
            else:
                self._channels.extend(channels)

        if isinstance(channels, str):
            self._triggers.append(channels)
        else:
            self._triggers.extend(channels)

        return self

    def read_from(
        self,
        *channels: str,
    ) -> Self:
        """Adds the specified channels to read from, without subscribing to them."""
        assert isinstance(self._channels, list), (
            "Cannot read additional channels when subscribed to single channels"
        )
        self._channels.extend(channels)
        return self

    def do(
        self,
        node: RunnableLike,
    ) -> Self:
        """Adds the specified node."""
        if self._bound is not DEFAULT_BOUND:
            self._bound = RunnableSeq(
                self._bound, coerce_to_runnable(node, name=None, trace=True)
            )
        else:
            self._bound = coerce_to_runnable(node, name=None, trace=True)
        return self

    def write_to(
        self,
        *channels: str | ChannelWriteEntry,
        **kwargs: _WriteValue,
    ) -> Self:
        """Add channel writes.

        Args:
            *channels: Channel names to write to.
            **kwargs: Channel name and value mappings.

        Returns:
            Self for chaining
        """
        self._writes.extend(
            ChannelWriteEntry(c) if isinstance(c, str) else c for c in channels
        )
        self._writes.extend(
            ChannelWriteEntry(k, mapper=v)
            if callable(v)
            else ChannelWriteEntry(k, value=v)
            for k, v in kwargs.items()
        )

        return self

    def meta(self, *tags: str, **metadata: Any) -> Self:
        """Add tags or metadata to the node."""
        self._tags.extend(tags)
        self._metadata.update(metadata)
        return self

    def add_retry_policies(self, *policies: RetryPolicy) -> Self:
        """Adds retry policies to the node."""
        self._retry_policy.extend(policies)
        return self

    def add_cache_policy(self, policy: CachePolicy) -> Self:
        """Adds cache policies to the node."""
        self._cache_policy = policy
        return self

    def set_timeout(self, timeout: float | timedelta | TimeoutPolicy | None) -> Self:
        """Set the per-attempt timeout policy for this node."""
        self._timeout = coerce_timeout_policy(timeout)
        return self

    def build(self) -> PregelNode:
        """Builds the node."""
        return PregelNode(
            channels=self._channels,
            triggers=self._triggers,
            tags=self._tags,
            metadata=self._metadata,
            writers=[ChannelWrite(self._writes)],
            bound=self._bound,
            retry_policy=self._retry_policy,
            cache_policy=self._cache_policy,
            timeout=self._timeout,
        )


# Kwargs that ``stream_events(version="v3")`` / ``astream_events(version="v3")``
# manage internally and must not be overridden by callers. ``stream_mode`` is
# derived from the transformer mux; ``subgraphs`` is forced True so nested
# namespaces flow through scoped muxes. Forwarding either to the inner
# ``stream(...)`` would silently break v3's invariants, so we raise instead.
_V3_INVARIANT_KWARGS: tuple[str, ...] = ("stream_mode", "subgraphs")


def _reject_v3_invariant_kwargs(kwargs: dict[str, Any]) -> None:
    collisions = [k for k in _V3_INVARIANT_KWARGS if k in kwargs]
    if collisions:
        raise TypeError(
            "stream_events(version='v3') / astream_events(version='v3') do "
            f"not accept {', '.join(collisions)}; v3 owns these "
            "(stream_mode is built from the transformer mux, subgraphs is "
            "forced True so nested namespaces flow through scoped muxes)."
        )


def _collect_stream_modes(mux: Any) -> list[StreamMode]:
    """Return the union of `required_stream_modes` across registered transformers.

    Transformers declare the stream modes they need to function, and
    `stream_events(version="v3")` asks the graph for exactly that union — no hardcoded
    default set. If zero transformers declare a given mode, the graph
    does not stream events for it.
    """
    modes: set[StreamMode] = set()
    for transformer in mux._transformers:
        modes.update(
            cast(
                "tuple[StreamMode, ...]",
                getattr(transformer, "required_stream_modes", ()),
            )
        )
    return list(modes)


def _normalize_stream_transformer_factories(
    specs: Sequence[Callable[[tuple[str, ...]], Any]] | None,
) -> list[Callable[[tuple[str, ...]], Any]]:
    """Normalize stream transformer specs to scoped factories.

    A stream transformer spec is a callable that accepts
    `scope: tuple[str, ...]` and returns a fresh `StreamTransformer`.
    Transformer classes work when their constructor follows the same
    shape. Pre-built instances are rejected because they cannot be
    cloned into subgraph scopes.
    """
    factories: list[Callable[[tuple[str, ...]], Any]] = []
    for spec in specs or ():
        if isinstance(spec, StreamTransformer):
            raise TypeError(
                "stream_events(version='v3') transformers must be scope-aware callables, "
                f"got pre-built instance {type(spec).__name__}. Pass the "
                "transformer class or a factory like "
                "`lambda scope: MyTransformer(scope, ...)`."
            )
        if not callable(spec):
            raise TypeError(
                "stream_events(version='v3') transformers must be scope-aware callables, "
                f"got {type(spec).__name__}."
            )

        def factory(scope: tuple[str, ...], _spec: Callable[..., Any] = spec) -> Any:
            return _spec(scope)

        factories.append(factory)
    return factories


