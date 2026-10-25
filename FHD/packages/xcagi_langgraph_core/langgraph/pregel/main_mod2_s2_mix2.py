from __future__ import annotations

from langgraph._internal._exception_policy import TERMINATION_ERRORS
from langgraph.pregel.main_mod1 import *  # noqa: F403

class PregelDebt19Mixin2:
    def _defaults(
        self,
        config: RunnableConfig,
        *,
        stream_mode: StreamMode | Sequence[StreamMode],
        print_mode: StreamMode | Sequence[StreamMode],
        output_keys: str | Sequence[str] | None,
        interrupt_before: All | Sequence[str] | None,
        interrupt_after: All | Sequence[str] | None,
        durability: Durability | None = None,
    ) -> tuple[
        set[StreamMode],
        str | Sequence[str],
        All | Sequence[str],
        All | Sequence[str],
        BaseCheckpointSaver | None,
        BaseStore | None,
        BaseCache | None,
        Durability,
    ]:
        if config["recursion_limit"] < 1:
            raise ValueError("recursion_limit must be at least 1")
        if output_keys is None:
            output_keys = self.stream_channels_asis
        else:
            validate_keys(output_keys, self.channels)
        interrupt_before = interrupt_before or self.interrupt_before_nodes
        interrupt_after = interrupt_after or self.interrupt_after_nodes
        if isinstance(stream_mode, str):
            stream_modes = {stream_mode}
        else:
            stream_modes = set(stream_mode)
        if isinstance(print_mode, str):
            stream_modes.add(print_mode)
        else:
            stream_modes.update(print_mode)
        if self.checkpointer is False:
            checkpointer: BaseCheckpointSaver | None = None
        elif CONFIG_KEY_CHECKPOINTER in config.get(CONF, {}):
            checkpointer = config[CONF][CONFIG_KEY_CHECKPOINTER]
        elif self.checkpointer is True:
            raise RuntimeError("checkpointer=True cannot be used for root graphs.")
        else:
            checkpointer = self.checkpointer
        if isinstance(checkpointer, BaseCheckpointSaver):
            checkpointer = self._apply_checkpointer_allowlist(checkpointer)
        if checkpointer and not config.get(CONF):
            raise ValueError(
                "Checkpointer requires one or more of the following 'configurable' "
                "keys: thread_id, checkpoint_ns, checkpoint_id"
            )
        if CONFIG_KEY_RUNTIME in config.get(CONF, {}):
            store: BaseStore | None = config[CONF][CONFIG_KEY_RUNTIME].store
        else:
            store = self.store
        if CONFIG_KEY_CACHE in config.get(CONF, {}):
            cache: BaseCache | None = config[CONF][CONFIG_KEY_CACHE]
        else:
            cache = self.cache
        if durability is None:
            durability = config.get(CONF, {}).get(CONFIG_KEY_DURABILITY, "async")
        return (
            stream_modes,
            output_keys,
            interrupt_before,
            interrupt_after,
            checkpointer,
            store,
            cache,
            durability,
        )

    @overload
    def stream(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        subgraphs: bool = False,
        debug: bool | None = None,
        version: Literal["v2"],
        **kwargs: Unpack[DeprecatedKwargs],
    ) -> Iterator[StreamPart[StateT, OutputT]]: ...

    @overload
    def stream(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        subgraphs: bool = False,
        debug: bool | None = None,
        version: Literal["v1"] = ...,
        **kwargs: Unpack[DeprecatedKwargs],
    ) -> Iterator[dict[str, Any] | Any]: ...

    def stream(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        subgraphs: bool = False,
        debug: bool | None = None,
        version: Literal["v1", "v2"] = "v1",
        **kwargs: Unpack[DeprecatedKwargs],
    ) -> Iterator[dict[str, Any] | Any]:
        """Stream graph steps for a single input.

        Args:
            input: The input to the graph.
            config: The configuration to use for the run.
            context: The static context to use for the run.
                !!! version-added "Added in version 0.6.0"
            stream_mode: The mode to stream output, defaults to `self.stream_mode`.

                Options are:

                - `"values"`: Emit all values in the state after each step, including interrupts.
                    When used with functional API, values are emitted once at the end of the workflow.
                - `"updates"`: Emit only the node or task names and updates returned by the nodes or tasks after each step.
                    If multiple updates are made in the same step (e.g. multiple nodes are run) then those updates are emitted separately.
                - `"custom"`: Emit custom data from inside nodes or tasks using `StreamWriter`.
                - `"messages"`: Emit LLM messages token-by-token together with metadata for any LLM invocations inside nodes or tasks.
                    - Will be emitted as 2-tuples `(LLM token, metadata)`.
                - `"checkpoints"`: Emit an event when a checkpoint is created, in the same format as returned by `get_state()`.
                - `"tasks"`: Emit events when tasks start and finish, including their results and errors.
                - `"debug"`: Emit debug events with as much information as possible for each step.

                You can pass a list as the `stream_mode` parameter to stream multiple modes at once.
                The streamed outputs will be tuples of `(mode, data)`.

                See [LangGraph streaming guide](https://docs.langchain.com/oss/python/langgraph/streaming) for more details.
            print_mode: Accepts the same values as `stream_mode`, but only prints the output to the console, for debugging purposes.

                Does not affect the output of the graph in any way.
            output_keys: The keys to stream, defaults to all non-context channels.
            interrupt_before: Nodes to interrupt before, defaults to all nodes in the graph.
            interrupt_after: Nodes to interrupt after, defaults to all nodes in the graph.
            durability: The durability mode for the graph execution, defaults to `"async"`.

                Options are:

                - `"sync"`: Changes are persisted synchronously before the next step starts.
                - `"async"`: Changes are persisted asynchronously while the next step executes.
                - `"exit"`: Changes are persisted only when the graph exits.
            control: Optional run control used to request cooperative drain.
            subgraphs: Whether to stream events from inside subgraphs, defaults to `False`.

                If `True`, the events will be emitted as tuples `(namespace, data)`,
                or `(namespace, mode, data)` if `stream_mode` is a list,
                where `namespace` is a tuple with the path to the node where a subgraph is invoked,
                e.g. `("parent_node:<task_id>", "child_node:<task_id>")`.

                See [LangGraph streaming guide](https://docs.langchain.com/oss/python/langgraph/streaming) for more details.

        Yields:
            The output of each step in the graph. The output shape depends on the `stream_mode`.
        """
        if (checkpoint_during := kwargs.get("checkpoint_during")) is not None:
            warnings.warn(
                "`checkpoint_during` is deprecated and will be removed. Please use `durability` instead.",
                category=LangGraphDeprecatedSinceV10,
                stacklevel=2,
            )
            if durability is not None:
                raise ValueError(
                    "Cannot use both `checkpoint_during` and `durability` parameters. Please use `durability` instead."
                )
            durability = "async" if checkpoint_during else "exit"

        if stream_mode is None:
            # if being called as a node in another graph, default to values mode
            # but don't overwrite stream_mode arg if provided
            stream_mode = (
                "values"
                if config is not None and CONFIG_KEY_TASK_ID in config.get(CONF, {})
                else self.stream_mode
            )
        if debug or self.debug:
            print_mode = ["updates", "values"]

        stream = SyncQueue()

        config = ensure_config(self.config, config)
        run_manager = None
        try:
            # assign defaults
            (
                stream_modes,
                output_keys,
                interrupt_before_,
                interrupt_after_,
                checkpointer,
                store,
                cache,
                durability_,
            ) = self._defaults(
                config,
                stream_mode=stream_mode,
                print_mode=print_mode,
                output_keys=output_keys,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                durability=durability,
            )
            callback_manager = get_callback_manager_for_config(config)
            if "messages" in stream_modes and version != "v2":
                # Strip any inherited v2 messages handler so a v1 stream
                # does not get routed through the content-block event
                # protocol. Leave v1 handlers in place — an outer
                # stream(stream_mode="messages", subgraphs=True) relies
                # on its inheritable handler to observe events emitted
                # by inner stream(stream_mode="messages") calls.
                callback_manager.handlers = [
                    h
                    for h in callback_manager.handlers
                    if not isinstance(h, StreamMessagesHandlerV2)
                ]
                callback_manager.inheritable_handlers = [
                    h
                    for h in callback_manager.inheritable_handlers
                    if not isinstance(h, StreamMessagesHandlerV2)
                ]
            if "ls_integration" not in callback_manager.metadata:
                callback_manager.add_metadata({"ls_integration": "langgraph"})
            run_manager = callback_manager.on_chain_start(
                None,
                input,
                name=config.get("run_name", self.get_name()),
                run_id=config.get("run_id"),
            )
            graph_callback_manager = get_sync_graph_callback_manager_for_config(
                config,
                run_id=run_manager.run_id,
            )
            if checkpointer is None and durability is not None:
                warnings.warn(
                    "`durability` has no effect when no checkpointer is present.",
                )
            # set up subgraph checkpointing
            if self.checkpointer is True:
                ns = cast(str, config[CONF][CONFIG_KEY_CHECKPOINT_NS])
                config[CONF][CONFIG_KEY_CHECKPOINT_NS] = recast_checkpoint_ns(ns)
            # set up messages stream mode
            if "messages" in stream_modes:
                ns_ = cast(str | None, config[CONF].get(CONFIG_KEY_CHECKPOINT_NS))
                use_stream_messages_v2 = bool(
                    version == "v2" and config[CONF].get(CONFIG_KEY_STREAM_MESSAGES_V2)
                )
                messages_handler_cls = (
                    StreamMessagesHandlerV2
                    if use_stream_messages_v2
                    else StreamMessagesHandler
                )
                run_manager.inheritable_handlers.append(
                    messages_handler_cls(
                        stream.put,
                        subgraphs,
                        parent_ns=tuple(ns_.split(NS_SEP)) if ns_ else None,
                    )
                )

            # set up tools stream mode
            if "tools" in stream_modes:
                ns_tools = cast(str | None, config[CONF].get(CONFIG_KEY_CHECKPOINT_NS))
                run_manager.inheritable_handlers.append(
                    StreamToolCallHandler(
                        stream.put,
                        subgraphs,
                        parent_ns=tuple(ns_tools.split(NS_SEP)) if ns_tools else None,
                    )
                )

            # set up custom stream mode
            if "custom" in stream_modes:

                def stream_writer(c: Any) -> None:
                    stream.put(
                        (
                            tuple(
                                get_config()[CONF][CONFIG_KEY_CHECKPOINT_NS].split(
                                    NS_SEP
                                )[:-1]
                            ),
                            "custom",
                            c,
                        )
                    )
            elif CONFIG_KEY_STREAM in config[CONF]:
                stream_writer = config[CONF][CONFIG_KEY_RUNTIME].stream_writer
            else:

                def stream_writer(c: Any) -> None:
                    pass

            # set durability mode for subgraphs
            if durability is not None:
                config[CONF][CONFIG_KEY_DURABILITY] = durability_

            # build server_info from metadata + parent runtime
            parent_runtime = _coerce_parent_runtime(
                config[CONF].get(CONFIG_KEY_RUNTIME, DEFAULT_RUNTIME)
            )
            server_info = _build_server_info(config, parent_runtime)

            runtime = Runtime(
                context=_coerce_context(self.context_schema, context),
                store=store,
                stream_writer=stream_writer,
                previous=None,
                execution_info=None,
                server_info=server_info,
                control=control or parent_runtime.control or RunControl(),
            )
            runtime = parent_runtime.merge(runtime)
            config[CONF][CONFIG_KEY_RUNTIME] = runtime

            # resolve mappers for v2 stream coercion
            _output_mapper = self._output_mapper if version == "v2" else None
            _state_mapper = self._state_mapper if version == "v2" else None

            def emit_graph_lifecycle_events(loop: SyncPregelLoop) -> None:
                while (event := loop._pop_lifecycle_event()) is not None:
                    if isinstance(event, GraphResumeEvent):
                        graph_callback_manager.on_resume(
                            replace(event, run_id=graph_callback_manager.run_id)
                        )
                    else:
                        graph_callback_manager.on_interrupt(
                            replace(event, run_id=graph_callback_manager.run_id)
                        )

            with SyncPregelLoop(
                input,
                stream=StreamProtocol(stream.put, stream_modes),
                config=config,
                store=store,
                cache=cache,
                checkpointer=checkpointer,
                nodes=self.nodes,
                specs=self.channels,
                output_keys=output_keys,
                input_keys=self.input_channels,
                stream_keys=self.stream_channels_asis,
                interrupt_before=interrupt_before_,
                interrupt_after=interrupt_after_,
                manager=run_manager,
                durability=durability_,
                trigger_to_nodes=self.trigger_to_nodes,
                migrate_checkpoint=self._migrate_checkpoint,
                retry_policy=self.retry_policy,
                cache_policy=self.cache_policy,
                has_graph_lifecycle_callbacks=bool(graph_callback_manager.handlers),
            ) as loop:
                emit_graph_lifecycle_events(loop)
                # create runner
                runner = PregelRunner(
                    submit=config[CONF].get(
                        CONFIG_KEY_RUNNER_SUBMIT, weakref.WeakMethod(loop.submit)
                    ),
                    put_writes=weakref.WeakMethod(loop.put_writes),
                    node_finished=config[CONF].get(CONFIG_KEY_NODE_FINISHED),
                    node_error_handler_map=self.node_error_handler_map,
                    schedule_error_handler=loop.schedule_error_handler,
                )
                # enable subgraph streaming
                if subgraphs:
                    loop.config[CONF][CONFIG_KEY_STREAM] = loop.stream
                # enable concurrent streaming
                get_waiter: Callable[[], concurrent.futures.Future[None]] | None = None
                if (
                    self.stream_eager
                    or subgraphs
                    or "messages" in stream_modes
                    or "custom" in stream_modes
                ):
                    # we are careful to have a single waiter live at any one time
                    # because on exit we increment semaphore count by exactly 1
                    waiter: concurrent.futures.Future | None = None
                    # because sync futures cannot be cancelled, we instead
                    # release the stream semaphore on exit, which will cause
                    # a pending waiter to return immediately
                    loop.stack.callback(stream._count.release)

                    def get_waiter() -> concurrent.futures.Future[None]:
                        nonlocal waiter
                        if waiter is None or waiter.done():
                            waiter = loop.submit(stream.wait)
                            return waiter
                        else:
                            return waiter

                # Similarly to Bulk Synchronous Parallel / Pregel model
                # computation proceeds in steps, while there are channel updates.
                # Channel updates from step N are only visible in step N+1
                # channels are guaranteed to be immutable for the duration of the step,
                # with channel updates applied only at the transition between steps.
                while loop.tick():
                    for task in loop.match_cached_writes():
                        loop.output_writes(task.id, task.writes, cached=True)
                    for _ in runner.tick(
                        [t for t in loop.tasks.values() if not t.writes],
                        timeout=self.step_timeout,
                        get_waiter=get_waiter,
                        schedule_task=loop.accept_push,
                    ):
                        # emit output
                        yield from _output(
                            stream_mode,
                            print_mode,
                            subgraphs,
                            stream.get,
                            queue.Empty,
                            version,
                            _output_mapper,
                            _state_mapper,
                        )
                    loop.after_tick()
                    emit_graph_lifecycle_events(loop)
                    # wait for checkpoint
                    if durability_ == "sync":
                        loop._put_checkpoint_fut.result()
            emit_graph_lifecycle_events(loop)
            # emit output
            yield from _output(
                stream_mode,
                print_mode,
                subgraphs,
                stream.get,
                queue.Empty,
                version,
                _output_mapper,
                _state_mapper,
            )
            # handle exit
            if loop.status == "out_of_steps":
                msg = create_error_message(
                    message=(
                        f"Recursion limit of {config['recursion_limit']} reached "
                        "without hitting a stop condition. You can increase the "
                        "limit by setting the `recursion_limit` config key."
                    ),
                    error_code=ErrorCode.GRAPH_RECURSION_LIMIT,
                )
                raise GraphRecursionError(msg)
            elif loop.status == "draining":
                if loop.control is None:
                    raise RuntimeError("Draining status requires run control")
                raise GraphDrained(loop.control.drain_reason or "shutdown")
            # set final channel values as run output
            run_manager.on_chain_end(loop.output)
        except TERMINATION_ERRORS as e:
            if run_manager is not None:
                run_manager.on_chain_error(e)
            raise

    @overload
    def astream(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        subgraphs: bool = False,
        debug: bool | None = None,
        version: Literal["v2"],
        **kwargs: Unpack[DeprecatedKwargs],
    ) -> AsyncIterator[StreamPart[StateT, OutputT]]: ...

    @overload
    def astream(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        subgraphs: bool = False,
        debug: bool | None = None,
        version: Literal["v1"] = ...,
        **kwargs: Unpack[DeprecatedKwargs],
    ) -> AsyncIterator[dict[str, Any] | Any]: ...

    async def astream(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode | Sequence[StreamMode] | None = None,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        subgraphs: bool = False,
        debug: bool | None = None,
        version: Literal["v1", "v2"] = "v1",
        **kwargs: Unpack[DeprecatedKwargs],
    ) -> AsyncIterator[dict[str, Any] | Any]:
        """Asynchronously stream graph steps for a single input.

        Args:
            input: The input to the graph.
            config: The configuration to use for the run.
            context: The static context to use for the run.
                !!! version-added "Added in version 0.6.0"
            stream_mode: The mode to stream output, defaults to `self.stream_mode`.

                Options are:

                - `"values"`: Emit all values in the state after each step, including interrupts.
                    When used with functional API, values are emitted once at the end of the workflow.
                - `"updates"`: Emit only the node or task names and updates returned by the nodes or tasks after each step.
                    If multiple updates are made in the same step (e.g. multiple nodes are run) then those updates are emitted separately.
                - `"custom"`: Emit custom data from inside nodes or tasks using `StreamWriter`.
                - `"messages"`: Emit LLM messages token-by-token together with metadata for any LLM invocations inside nodes or tasks.
                    - Will be emitted as 2-tuples `(LLM token, metadata)`.
                - `"checkpoints"`: Emit an event when a checkpoint is created, in the same format as returned by `get_state()`.
                - `"tasks"`: Emit events when tasks start and finish, including their results and errors.
                - `"debug"`: Emit debug events with as much information as possible for each step.

                You can pass a list as the `stream_mode` parameter to stream multiple modes at once.
                The streamed outputs will be tuples of `(mode, data)`.

                See [LangGraph streaming guide](https://docs.langchain.com/oss/python/langgraph/streaming) for more details.
            print_mode: Accepts the same values as `stream_mode`, but only prints the output to the console, for debugging purposes.

                Does not affect the output of the graph in any way.
            output_keys: The keys to stream, defaults to all non-context channels.
            interrupt_before: Nodes to interrupt before, defaults to all nodes in the graph.
            interrupt_after: Nodes to interrupt after, defaults to all nodes in the graph.
            durability: The durability mode for the graph execution, defaults to `"async"`.

                Options are:

                - `"sync"`: Changes are persisted synchronously before the next step starts.
                - `"async"`: Changes are persisted asynchronously while the next step executes.
                - `"exit"`: Changes are persisted only when the graph exits.
            control: Optional run control used to request cooperative drain.
            subgraphs: Whether to stream events from inside subgraphs, defaults to `False`.

                If `True`, the events will be emitted as tuples `(namespace, data)`,
                or `(namespace, mode, data)` if `stream_mode` is a list,
                where `namespace` is a tuple with the path to the node where a subgraph is invoked,
                e.g. `("parent_node:<task_id>", "child_node:<task_id>")`.

                See [LangGraph streaming guide](https://docs.langchain.com/oss/python/langgraph/streaming) for more details.

        Yields:
            The output of each step in the graph. The output shape depends on the `stream_mode`.
        """
        if (checkpoint_during := kwargs.get("checkpoint_during")) is not None:
            warnings.warn(
                "`checkpoint_during` is deprecated and will be removed. Please use `durability` instead.",
                category=LangGraphDeprecatedSinceV10,
                stacklevel=2,
            )
            if durability is not None:
                raise ValueError(
                    "Cannot use both `checkpoint_during` and `durability` parameters. Please use `durability` instead."
                )
            durability = "async" if checkpoint_during else "exit"

        if stream_mode is None:
            # if being called as a node in another graph, default to values mode
            # but don't overwrite stream_mode arg if provided
            stream_mode = (
                "values"
                if config is not None and CONFIG_KEY_TASK_ID in config.get(CONF, {})
                else self.stream_mode
            )
        if debug or self.debug:
            print_mode = ["updates", "values"]

        stream = AsyncQueue()
        aioloop = asyncio.get_running_loop()
        stream_put = cast(
            Callable[[StreamChunk], None],
            partial(aioloop.call_soon_threadsafe, stream.put_nowait),
        )

        config = ensure_config(self.config, config)
        run_manager = None
        try:
            # assign defaults
            (
                stream_modes,
                output_keys,
                interrupt_before_,
                interrupt_after_,
                checkpointer,
                store,
                cache,
                durability_,
            ) = self._defaults(
                config,
                stream_mode=stream_mode,
                print_mode=print_mode,
                output_keys=output_keys,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                durability=durability,
            )
            callback_manager = get_async_callback_manager_for_config(config)
            if "messages" in stream_modes and version != "v2":
                # Strip any inherited v2 messages handler so a v1 stream
                # does not get routed through the content-block event
                # protocol. Leave v1 handlers in place — an outer
                # astream(stream_mode="messages", subgraphs=True) relies
                # on its inheritable handler to observe events emitted
                # by inner astream(stream_mode="messages") calls.
                callback_manager.handlers = [
                    h
                    for h in callback_manager.handlers
                    if not isinstance(h, StreamMessagesHandlerV2)
                ]
                callback_manager.inheritable_handlers = [
                    h
                    for h in callback_manager.inheritable_handlers
                    if not isinstance(h, StreamMessagesHandlerV2)
                ]
            if "ls_integration" not in callback_manager.metadata:
                callback_manager.add_metadata({"ls_integration": "langgraph"})
            run_manager = await callback_manager.on_chain_start(
                None,
                input,
                name=config.get("run_name", self.get_name()),
                run_id=config.get("run_id"),
            )
            graph_callback_manager = get_async_graph_callback_manager_for_config(
                config,
                run_id=run_manager.run_id,
            )
            # if running from astream_log() run each proc with streaming
            do_stream = (
                next(
                    (
                        True
                        for h in run_manager.handlers
                        if isinstance(h, _StreamingCallbackHandler)
                        and not isinstance(h, StreamMessagesHandler)
                    ),
                    False,
                )
                if _StreamingCallbackHandler is not None
                else False
            )
            if checkpointer is None and durability is not None:
                warnings.warn(
                    "`durability` has no effect when no checkpointer is present.",
                )
            # set up subgraph checkpointing
            if self.checkpointer is True:
                ns = cast(str, config[CONF][CONFIG_KEY_CHECKPOINT_NS])
                config[CONF][CONFIG_KEY_CHECKPOINT_NS] = recast_checkpoint_ns(ns)
            # set up messages stream mode
            if "messages" in stream_modes:
                # namespace can be None in a root level graph?
                ns_ = cast(str | None, config[CONF].get(CONFIG_KEY_CHECKPOINT_NS))
                use_stream_messages_v2 = bool(
                    version == "v2" and config[CONF].get(CONFIG_KEY_STREAM_MESSAGES_V2)
                )
                messages_handler_cls = (
                    StreamMessagesHandlerV2
                    if use_stream_messages_v2
                    else StreamMessagesHandler
                )
                run_manager.inheritable_handlers.append(
                    messages_handler_cls(
                        stream_put,
                        subgraphs,
                        parent_ns=tuple(ns_.split(NS_SEP)) if ns_ else None,
                    )
                )

            # set up tools stream mode
            if "tools" in stream_modes:
                ns_tools = cast(str | None, config[CONF].get(CONFIG_KEY_CHECKPOINT_NS))
                run_manager.inheritable_handlers.append(
                    StreamToolCallHandler(
                        stream_put,
                        subgraphs,
                        parent_ns=tuple(ns_tools.split(NS_SEP)) if ns_tools else None,
                    )
                )

            # set up custom stream mode
            def stream_writer(c: Any) -> None:
                aioloop.call_soon_threadsafe(
                    stream.put_nowait,
                    (
                        tuple(
                            get_config()[CONF][CONFIG_KEY_CHECKPOINT_NS].split(NS_SEP)[
                                :-1
                            ]
                        ),
                        "custom",
                        c,
                    ),
                )

            if "custom" in stream_modes:

                def stream_writer(c: Any) -> None:
                    aioloop.call_soon_threadsafe(
                        stream.put_nowait,
                        (
                            tuple(
                                get_config()[CONF][CONFIG_KEY_CHECKPOINT_NS].split(
                                    NS_SEP
                                )[:-1]
                            ),
                            "custom",
                            c,
                        ),
                    )
            elif CONFIG_KEY_STREAM in config[CONF]:
                stream_writer = config[CONF][CONFIG_KEY_RUNTIME].stream_writer
            else:

                def stream_writer(c: Any) -> None:
                    pass

            # set durability mode for subgraphs
            if durability is not None:
                config[CONF][CONFIG_KEY_DURABILITY] = durability_

            # build server_info from metadata + parent runtime
            parent_runtime = _coerce_parent_runtime(
                config[CONF].get(CONFIG_KEY_RUNTIME, DEFAULT_RUNTIME)
            )
            server_info = _build_server_info(config, parent_runtime)

            runtime = Runtime(
                context=_coerce_context(self.context_schema, context),
                store=store,
                stream_writer=stream_writer,
                previous=None,
                execution_info=None,
                server_info=server_info,
                control=control or parent_runtime.control or RunControl(),
            )
            runtime = parent_runtime.merge(runtime)
            config[CONF][CONFIG_KEY_RUNTIME] = runtime

            # resolve mappers for v2 stream coercion
            _output_mapper = self._output_mapper if version == "v2" else None
            _state_mapper = self._state_mapper if version == "v2" else None

            async def aemit_graph_lifecycle_events(loop: AsyncPregelLoop) -> None:
                while (event := loop._pop_lifecycle_event()) is not None:
                    if isinstance(event, GraphResumeEvent):
                        await graph_callback_manager.on_resume(
                            GraphResumeEvent(
                                run_id=graph_callback_manager.run_id,
                                status=event.status,
                                checkpoint_id=event.checkpoint_id,
                                checkpoint_ns=event.checkpoint_ns,
                            )
                        )
                    else:
                        await graph_callback_manager.on_interrupt(
                            GraphInterruptEvent(
                                run_id=graph_callback_manager.run_id,
                                status=event.status,
                                checkpoint_id=event.checkpoint_id,
                                checkpoint_ns=event.checkpoint_ns,
                                interrupts=event.interrupts,
                            )
                        )

            async with AsyncPregelLoop(
                input,
                stream=StreamProtocol(stream.put_nowait, stream_modes),
                config=config,
                store=store,
                cache=cache,
                checkpointer=checkpointer,
                nodes=self.nodes,
                specs=self.channels,
                output_keys=output_keys,
                input_keys=self.input_channels,
                stream_keys=self.stream_channels_asis,
                interrupt_before=interrupt_before_,
                interrupt_after=interrupt_after_,
                manager=run_manager,
                durability=durability_,
                trigger_to_nodes=self.trigger_to_nodes,
                migrate_checkpoint=self._migrate_checkpoint,
                retry_policy=self.retry_policy,
                cache_policy=self.cache_policy,
                has_graph_lifecycle_callbacks=bool(graph_callback_manager.handlers),
            ) as loop:
                await aemit_graph_lifecycle_events(loop)
                # create runner
                runner = PregelRunner(
                    submit=config[CONF].get(
                        CONFIG_KEY_RUNNER_SUBMIT, weakref.WeakMethod(loop.submit)
                    ),
                    put_writes=weakref.WeakMethod(loop.put_writes),
                    use_astream=do_stream,
                    node_finished=config[CONF].get(CONFIG_KEY_NODE_FINISHED),
                    node_error_handler_map=self.node_error_handler_map,
                    aschedule_error_handler=loop.aschedule_error_handler,
                )
                # enable subgraph streaming
                if subgraphs:
                    loop.config[CONF][CONFIG_KEY_STREAM] = StreamProtocol(
                        stream_put, stream_modes
                    )
                # enable concurrent streaming
                get_waiter: Callable[[], asyncio.Task[None]] | None = None
                _cleanup_waiter: Callable[[], Awaitable[None]] | None = None
                if (
                    self.stream_eager
                    or subgraphs
                    or "messages" in stream_modes
                    or "custom" in stream_modes
                ):
                    # Keep a single waiter task alive; ensure cleanup on exit.
                    waiter: asyncio.Task[None] | None = None

                    def get_waiter() -> asyncio.Task[None]:
                        nonlocal waiter
                        if waiter is None or waiter.done():
                            waiter = aioloop.create_task(stream.wait())

                            def _clear(t: asyncio.Task[None]) -> None:
                                nonlocal waiter
                                if waiter is t:
                                    waiter = None

                            waiter.add_done_callback(_clear)
                        return waiter

                    async def _cleanup_waiter() -> None:
                        """Wake pending waiter and/or cancel+await to avoid pending tasks."""
                        nonlocal waiter
                        # Try to wake via semaphore like SyncPregelLoop
                        with contextlib.suppress(Exception):
                            if hasattr(stream, "_count"):
                                stream._count.release()
                        t = waiter
                        waiter = None
                        if t is not None and not t.done():
                            t.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await t

                # Similarly to Bulk Synchronous Parallel / Pregel model
                # computation proceeds in steps, while there are channel updates
                # channel updates from step N are only visible in step N+1
                # channels are guaranteed to be immutable for the duration of the step,
                # with channel updates applied only at the transition between steps
                try:
                    while loop.tick():
                        for task in await loop.amatch_cached_writes():
                            loop.output_writes(task.id, task.writes, cached=True)
                        async for _ in runner.atick(
                            [t for t in loop.tasks.values() if not t.writes],
                            timeout=self.step_timeout,
                            get_waiter=get_waiter,
                            schedule_task=loop.aaccept_push,
                        ):
                            # emit output
                            for o in _output(
                                stream_mode,
                                print_mode,
                                subgraphs,
                                stream.get_nowait,
                                asyncio.QueueEmpty,
                                version,
                                _output_mapper,
                                _state_mapper,
                            ):
                                yield o
                        loop.after_tick()
                        await aemit_graph_lifecycle_events(loop)
                        # wait for checkpoint
                        if durability_ == "sync":
                            await cast(asyncio.Future, loop._put_checkpoint_fut)
                finally:
                    # ensure waiter doesn't remain pending on cancel/shutdown
                    if _cleanup_waiter is not None:
                        await _cleanup_waiter()

            await aemit_graph_lifecycle_events(loop)

            # emit output
            for o in _output(
                stream_mode,
                print_mode,
                subgraphs,
                stream.get_nowait,
                asyncio.QueueEmpty,
                version,
                _output_mapper,
                _state_mapper,
            ):
                yield o
            # handle exit
            if loop.status == "out_of_steps":
                msg = create_error_message(
                    message=(
                        f"Recursion limit of {config['recursion_limit']} reached "
                        "without hitting a stop condition. You can increase the "
                        "limit by setting the `recursion_limit` config key."
                    ),
                    error_code=ErrorCode.GRAPH_RECURSION_LIMIT,
                )
                raise GraphRecursionError(msg)
            elif loop.status == "draining":
                if loop.control is None:
                    raise RuntimeError("Draining status requires run control")
                raise GraphDrained(loop.control.drain_reason or "shutdown")
            # set final channel values as run output
            await run_manager.on_chain_end(loop.output)
        except TERMINATION_ERRORS as e:
            if run_manager is not None:
                await asyncio.shield(run_manager.on_chain_error(e))
            raise

    @beta(message="The v3 streaming protocol on Pregel is experimental.")
    def _pregel_stream_v3(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        control: RunControl | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        **kwargs: Any,
    ) -> GraphRunStream:
        """Internal v3 sync streaming implementation. Public entry: stream_events(version='v3').

        Extra keyword arguments are forwarded to the underlying ``stream(...)``
        call. The dispatcher in ``stream_events`` rejects ``stream_mode`` and
        ``subgraphs`` since v3 owns them (``stream_mode`` is derived from the
        transformer mux; ``subgraphs`` is always True so nested namespaces
        flow through scoped muxes).

        !!! warning

            The v3 streaming protocol is experimental and may change.
        """
        parent_ns = _resolve_parent_ns(self.config, config)
        compiled_factories = _normalize_stream_transformer_factories(
            self.stream_transformers
        )
        extra_factories = _normalize_stream_transformer_factories(transformers)
        mux = StreamMux(
            factories=[
                ValuesTransformer,
                MessagesTransformer,
                LifecycleTransformer,
                SubgraphTransformer,
                *compiled_factories,
                *extra_factories,
            ],
            scope=parent_ns,
            is_async=False,
        )
        graph_iter = iter(
            self.stream(
                input,
                patch_configurable(config, {CONFIG_KEY_STREAM_MESSAGES_V2: True}),
                stream_mode=_collect_stream_modes(mux),
                subgraphs=True,
                version="v2",
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                control=control,
                **kwargs,
            )
        )
        return GraphRunStream(graph_iter, mux)

    @beta(message="The v3 streaming protocol on Pregel is experimental.")
    async def _apregel_stream_v3(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        control: RunControl | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncGraphRunStream:
        """Internal v3 async streaming implementation. Public entry: astream_events(version='v3').

        Extra keyword arguments are forwarded to the underlying ``astream(...)``
        call. The dispatcher in ``astream_events`` rejects ``stream_mode`` and
        ``subgraphs`` since v3 owns them (``stream_mode`` is derived from the
        transformer mux; ``subgraphs`` is always True so nested namespaces
        flow through scoped muxes).

        !!! warning

            The v3 streaming protocol is experimental and may change.
        """
        parent_ns = _resolve_parent_ns(self.config, config)
        compiled_factories = _normalize_stream_transformer_factories(
            self.stream_transformers
        )
        extra_factories = _normalize_stream_transformer_factories(transformers)
        mux = StreamMux(
            factories=[
                ValuesTransformer,
                MessagesTransformer,
                LifecycleTransformer,
                SubgraphTransformer,
                *compiled_factories,
                *extra_factories,
            ],
            scope=parent_ns,
            is_async=True,
        )
        graph_aiter = self.astream(
            input,
            patch_configurable(config, {CONFIG_KEY_STREAM_MESSAGES_V2: True}),
            stream_mode=_collect_stream_modes(mux),
            subgraphs=True,
            version="v2",
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
            control=control,
            **kwargs,
        ).__aiter__()
        return AsyncGraphRunStream(graph_aiter, mux)

    @overload
    def stream_events(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2"] = "v2",
        **kwargs: Any,
    ) -> Iterator[StreamEvent]: ...

    @overload
    def stream_events(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v3"],
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        control: RunControl | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        **kwargs: Any,
    ) -> GraphRunStream: ...

    def stream_events(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2", "v3"] = "v2",
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        control: RunControl | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Stream events from this graph.

        For `version="v1"` / `"v2"`, yields `StreamEvent` dicts (see
        `Runnable.stream_events`). For `version="v3"`, returns a
        `GraphRunStream` whose typed projections the caller drives by
        iterating — no background thread.

        !!! warning

            The `version="v3"` API is experimental and may change.

        Builds a `StreamMux` from the built-in transformers, this
        graph's compile-time `stream_transformers`, and any additional
        `transformers=` supplied at the call site. `run.output`,
        `run.interrupted`, and `run.interrupts` work regardless of
        which transformers are registered.

        Note:
            Nesting v1 `stream(stream_mode="messages")` inside a node
            of a `stream_events(version="v3")` run is not fully
            supported. The outer v3 messages handler reroutes
            `BaseChatModel.invoke` through the v2 event protocol, so
            the inner v1 handler does not see `on_llm_new_token`
            chunks. The inner stream still yields a finalized message
            via `on_llm_end`. Use `stream_events(version="v3")` for the
            inner graph as well, or call `chat_model.stream(...)`
            explicitly, to get token-level streaming.

        Args:
            input: Graph input.
            config: Optional runnable config.
            version: Streaming-event schema version. `"v3"` selects the
                content-block-centric streaming protocol.
            interrupt_before: Nodes to interrupt before, if any. Only
                used for `version="v3"`.
            interrupt_after: Nodes to interrupt after, if any. Only
                used for `version="v3"`.
            control: Optional run control used to request cooperative
                drain. Only used for `version="v3"`.
            transformers: Extra transformer classes or configured
                factories appended after compile-time
                `stream_transformers`. Factories are called as
                `factory(scope)` so they can propagate to subgraph
                scopes. Only used for `version="v3"`.
            **kwargs: For `version="v1"`/`"v2"`, forwarded to
                `Runnable.stream_events`. For `version="v3"`, forwarded
                to the underlying `stream(...)` call (e.g. `context`,
                `durability`, `output_keys`, `print_mode`, `debug`).
                `stream_mode` and `subgraphs` are not accepted under
                `version="v3"` and raise `TypeError` if supplied; v3
                owns them.

        Returns:
            For `version="v3"`, a `GraphRunStream` the caller iterates
            to drive the run. Otherwise an `Iterator[StreamEvent]`.
        """
        if version == "v3":
            _reject_v3_invariant_kwargs(kwargs)
            return self._pregel_stream_v3(
                input,
                config,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                control=control,
                transformers=transformers,
                **kwargs,
            )
        return super().stream_events(input, config, version=version, **kwargs)

    @overload
    def astream_events(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2"] = "v2",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]: ...

    @overload
    def astream_events(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v3"],
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        control: RunControl | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        **kwargs: Any,
    ) -> Awaitable[AsyncGraphRunStream]: ...

    def astream_events(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2", "v3"] = "v2",
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        control: RunControl | None = None,
        transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent] | Awaitable[Any]:
        """Async variant of `stream_events`.

        For `version="v3"`, returns an `AsyncGraphRunStream` whose
        projections can be awaited concurrently; each subscribed cursor
        drives the pump when its buffer is empty. The same nesting
        limitation as the sync path applies — see `stream_events` for
        details.

        !!! warning

            The `version="v3"` API is experimental and may change.

        See `stream_events` for full argument and return documentation.
        """
        if version == "v3":
            _reject_v3_invariant_kwargs(kwargs)
            return self._apregel_stream_v3(
                input,
                config,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                control=control,
                transformers=transformers,
                **kwargs,
            )
        return super().astream_events(input, config, version=version, **kwargs)

    @overload
    def invoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: Literal["values"] = ...,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v2"],
        **kwargs: Any,
    ) -> GraphOutput[OutputT]: ...

    @overload
    def invoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v2"],
        **kwargs: Any,
    ) -> list[StreamPart[StateT, OutputT]]: ...

    @overload
    def invoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode = "values",
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v1"] = ...,
        **kwargs: Any,
    ) -> dict[str, Any] | Any: ...

    def invoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode = "values",
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v1", "v2"] = "v1",
        **kwargs: Any,
    ) -> dict[str, Any] | Any:
        """Run the graph with a single input and config.

        Args:
            input: The input data for the graph. It can be a dictionary or any other type.
            config: The configuration for the graph run.
            context: The static context to use for the run.
                !!! version-added "Added in version 0.6.0"
            stream_mode: The stream mode for the graph run.
            print_mode: Accepts the same values as `stream_mode`, but only prints the output to the console, for debugging purposes.

                Does not affect the output of the graph in any way.
            output_keys: The output keys to retrieve from the graph run.
            interrupt_before: The nodes to interrupt the graph run before.
            interrupt_after: The nodes to interrupt the graph run after.
            durability: The durability mode for the graph execution, defaults to `"async"`.

                Options are:

                - `"sync"`: Changes are persisted synchronously before the next step starts.
                - `"async"`: Changes are persisted asynchronously while the next step executes.
                - `"exit"`: Changes are persisted only when the graph exits.
            control: Optional run control used to request cooperative drain.
            version: The streaming format version. `"v1"` (default) returns the
                traditional format, `"v2"` returns `StreamPart` typed dicts when
                `stream_mode` is not `"values"`.
            **kwargs: Additional keyword arguments to pass to the graph run.

        Returns:
            The output of the graph run. If `stream_mode` is `"values"`, it returns the latest output.
            If `stream_mode` is not `"values"`, it returns a list of output chunks.
        """
        output_keys = output_keys if output_keys is not None else self.output_channels

        latest: dict[str, Any] | Any = None
        chunks: list[dict[str, Any] | Any] = []
        interrupts: list[Interrupt] = []

        if version == "v2":
            # v2: values stream parts carry interrupts directly
            for chunk in self.stream(
                input,
                config,
                context=context,
                stream_mode="values" if stream_mode == "values" else stream_mode,
                print_mode=print_mode,
                output_keys=output_keys,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                durability=durability,
                control=control,
                version=version,
                **kwargs,
            ):
                if stream_mode == "values":
                    latest = chunk["data"]
                    if chunk_ints := chunk.get("interrupts", ()):
                        interrupts.extend(chunk_ints)  # type: ignore[arg-type]
                else:
                    chunks.append(chunk)
        else:
            # v1: collect interrupts from updates stream
            for chunk in self.stream(
                input,
                config,
                context=context,
                stream_mode=(
                    ["updates", "values"] if stream_mode == "values" else stream_mode
                ),
                print_mode=print_mode,
                output_keys=output_keys,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                durability=durability,
                control=control,
                **kwargs,
            ):
                if stream_mode == "values":
                    if len(chunk) == 2:
                        mode, payload = cast(tuple[StreamMode, Any], chunk)
                    else:
                        _, mode, payload = cast(
                            tuple[tuple[str, ...], StreamMode, Any], chunk
                        )
                    if (
                        mode == "updates"
                        and isinstance(payload, dict)
                        and (ints := payload.get(INTERRUPT)) is not None
                    ):
                        interrupts.extend(ints)
                    elif mode == "values":
                        latest = payload
                else:
                    chunks.append(chunk)

        if stream_mode == "values":
            if version == "v2":
                return GraphOutput(value=latest, interrupts=tuple(interrupts))
            if interrupts:
                return (
                    {**latest, INTERRUPT: interrupts}
                    if isinstance(latest, dict)
                    else {INTERRUPT: interrupts}
                )
            return latest
        else:
            return chunks

    @overload
    async def ainvoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: Literal["values"] = ...,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v2"],
        **kwargs: Any,
    ) -> GraphOutput[OutputT]: ...

    @overload
    async def ainvoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode,
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v2"],
        **kwargs: Any,
    ) -> list[StreamPart[StateT, OutputT]]: ...

    @overload
    async def ainvoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode = "values",
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v1"] = ...,
        **kwargs: Any,
    ) -> dict[str, Any] | Any: ...

    async def ainvoke(
        self,
        input: InputT | Command | None,
        config: RunnableConfig | None = None,
        *,
        context: ContextT | None = None,
        stream_mode: StreamMode = "values",
        print_mode: StreamMode | Sequence[StreamMode] = (),
        output_keys: str | Sequence[str] | None = None,
        interrupt_before: All | Sequence[str] | None = None,
        interrupt_after: All | Sequence[str] | None = None,
        durability: Durability | None = None,
        control: RunControl | None = None,
        version: Literal["v1", "v2"] = "v1",
        **kwargs: Any,
    ) -> dict[str, Any] | Any:
        """Asynchronously run the graph with a single input and config.

        Args:
            input: The input data for the graph. It can be a dictionary or any other type.
            config: The configuration for the graph run.
            context: The static context to use for the run.
                !!! version-added "Added in version 0.6.0"
            stream_mode: The stream mode for the graph run.
            print_mode: Accepts the same values as `stream_mode`, but only prints the output to the console, for debugging purposes.

                Does not affect the output of the graph in any way.
            output_keys: The output keys to retrieve from the graph run.
            interrupt_before: The nodes to interrupt the graph run before.
            interrupt_after: The nodes to interrupt the graph run after.
            durability: The durability mode for the graph execution, defaults to `"async"`.

                Options are:

                - `"sync"`: Changes are persisted synchronously before the next step starts.
                - `"async"`: Changes are persisted asynchronously while the next step executes.
                - `"exit"`: Changes are persisted only when the graph exits.
            control: Optional run control used to request cooperative drain.
            version: The streaming format version. `"v1"` (default) returns the
                traditional format, `"v2"` returns `StreamPart` typed dicts when
                `stream_mode` is not `"values"`.
            **kwargs: Additional keyword arguments to pass to the graph run.

        Returns:
            The output of the graph run. If `stream_mode` is `"values"`, it returns the latest output.
            If `stream_mode` is not `"values"`, it returns a list of output chunks.
        """
        output_keys = output_keys if output_keys is not None else self.output_channels

        latest: dict[str, Any] | Any = None
        chunks: list[dict[str, Any] | Any] = []
        interrupts: list[Interrupt] = []

        if version == "v2":
            # v2: values stream parts carry interrupts directly
            async for chunk in self.astream(
                input,
                config,
                context=context,
                stream_mode="values" if stream_mode == "values" else stream_mode,
                print_mode=print_mode,
                output_keys=output_keys,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                durability=durability,
                control=control,
                version=version,
                **kwargs,
            ):
                if stream_mode == "values":
                    latest = chunk["data"]
                    if chunk_ints := chunk.get("interrupts", ()):
                        interrupts.extend(chunk_ints)  # type: ignore[arg-type]
                else:
                    chunks.append(chunk)
        else:
            # v1: collect interrupts from updates stream
            async for chunk in self.astream(
                input,
                config,
                context=context,
                stream_mode=(
                    ["updates", "values"] if stream_mode == "values" else stream_mode
                ),
                print_mode=print_mode,
                output_keys=output_keys,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
                durability=durability,
                control=control,
                **kwargs,
            ):
                if stream_mode == "values":
                    if len(chunk) == 2:
                        mode, payload = cast(tuple[StreamMode, Any], chunk)
                    else:
                        _, mode, payload = cast(
                            tuple[tuple[str, ...], StreamMode, Any], chunk
                        )
                    if (
                        mode == "updates"
                        and isinstance(payload, dict)
                        and (ints := payload.get(INTERRUPT)) is not None
                    ):
                        interrupts.extend(ints)
                    elif mode == "values":
                        latest = payload
                else:
                    chunks.append(chunk)

        if stream_mode == "values":
            if version == "v2":
                return GraphOutput(value=latest, interrupts=tuple(interrupts))
            if interrupts:
                return (
                    {**latest, INTERRUPT: interrupts}
                    if isinstance(latest, dict)
                    else {INTERRUPT: interrupts}
                )
            return latest
        else:
            return chunks

    def clear_cache(self, nodes: Sequence[str] | None = None) -> None:
        """Clear the cache for the given nodes."""
        if not self.cache:
            raise ValueError("No cache is set for this graph. Cannot clear cache.")
        # collect namespaces to clear
        namespaces: list[tuple[str, ...]] = []
        for node in nodes or self.nodes:
            if node in self.nodes:
                namespaces.append(
                    (
                        CACHE_NS_WRITES,
                        (identifier(self.nodes[node]) or "__dynamic__"),
                        node,
                    ),
                )
        # clear cache
        self.cache.clear(namespaces)

    async def aclear_cache(self, nodes: Sequence[str] | None = None) -> None:
        """Asynchronously clear the cache for the given nodes."""
        if not self.cache:
            raise ValueError("No cache is set for this graph. Cannot clear cache.")
        # collect namespaces to clear
        namespaces: list[tuple[str, ...]] = []
        for node in nodes or self.nodes:
            if node in self.nodes:
                namespaces.append(
                    (
                        CACHE_NS_WRITES,
                        (identifier(self.nodes[node]) or "__dynamic__"),
                        node,
                    ),
                )
        # clear cache
        await self.cache.aclear(namespaces)
