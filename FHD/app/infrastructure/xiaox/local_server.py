"""A private loopback ASGI endpoint for one runtime invocation (Uvicorn BSD-3-Clause)."""

from __future__ import annotations

import socket
import threading
import time
from contextvars import copy_context
from typing import Any


class LocalRuntimeServer:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.url = ""
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None

    def __enter__(self) -> LocalRuntimeServer:
        import uvicorn

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(32)
        self.url = f"http://127.0.0.1:{self._socket.getsockname()[1]}"
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=0,
                access_log=False,
                log_level="warning",
                lifespan="off",
                server_header=False,
                timeout_graceful_shutdown=3,
            )
        )
        self._thread = threading.Thread(
            target=copy_context().run,
            args=(self._server.run,),
            kwargs={"sockets": [self._socket]},
            daemon=True,
            name="xcmax-xiaox-loopback",
        )
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() >= deadline:
                self.__exit__(None, None, None)
                raise RuntimeError("Private runtime endpoint failed to start")
            self._thread.join(0.01)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(5)
        if self._socket is not None:
            self._socket.close()
