from __future__ import annotations

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


