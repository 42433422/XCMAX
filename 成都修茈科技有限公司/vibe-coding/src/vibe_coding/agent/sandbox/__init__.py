"""Sandbox drivers: subprocess + Docker + WebContainer + cloud + mock.

Two execution modes are supported by every driver:

- **function** — run a single Python function in isolation, fed JSON input,
  returning a JSON output. This is the legacy path used by ``CodeSandbox``
  and ``CodeSkillRuntime`` and remains the default for skills.
- **command** — run an arbitrary shell command against a workspace
  directory. This unlocks running real linters / type checkers / test
  frameworks (the P1 :mod:`vibe_coding.agent.tools` package leans on it).

Available drivers:

- :class:`SubprocessSandboxDriver` — always available, no external deps.
- :class:`DockerSandboxDriver` — opt-in, full container isolation.
- :class:`WebContainerSandboxDriver` — proxy to a browser-side WebContainer
  (Node-only, ideal for front-end vitest / vite dev sessions).
- :class:`CloudSandboxDriver` — thin shell over E2B / generic HTTP cloud
  backends; lets the agent run in a hosted, isolated workspace far from
  the user's machine.
- :class:`MockSandboxDriver` — in-memory test double.

:func:`create_default_driver` picks Docker when the ``docker`` CLI is on
``PATH`` and the daemon is reachable; otherwise it returns a
:class:`SubprocessSandboxDriver`. Pass ``prefer="subprocess"`` /
``"webcontainer"`` / ``"cloud"`` to override.
"""

from __future__ import annotations

from .cloud_driver import (
    CloudSandboxBackend,
    CloudSandboxDriver,
    E2BBackend,
    HTTPCloudBackend,
    create_cloud_driver,
)
from .docker_driver import DockerSandboxDriver
from .driver import (
    SandboxDriver,
    SandboxJob,
    SandboxPolicy,
    SandboxResult,
    create_default_driver,
)
from .mock_driver import MockSandboxDriver
from .subprocess_driver import SubprocessSandboxDriver
from .webcontainer_driver import WebContainerBridge, WebContainerSandboxDriver

__all__ = [
    "CloudSandboxBackend",
    "CloudSandboxDriver",
    "DockerSandboxDriver",
    "E2BBackend",
    "HTTPCloudBackend",
    "MockSandboxDriver",
    "SandboxDriver",
    "SandboxJob",
    "SandboxPolicy",
    "SandboxResult",
    "SubprocessSandboxDriver",
    "WebContainerBridge",
    "WebContainerSandboxDriver",
    "create_cloud_driver",
    "create_default_driver",
]
