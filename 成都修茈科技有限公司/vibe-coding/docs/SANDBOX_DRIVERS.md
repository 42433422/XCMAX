# Sandbox Drivers

The agent uses a driver abstraction so the same interface works across
many execution environments:

| Driver | Dependencies | Network isolation | FS isolation | Memory cap | Best for |
| --- | :---: | :---: | :---: | :---: | --- |
| `SubprocessSandboxDriver` | none | ✗ | AST whitelist only | POSIX only | Default; fast local runs |
| `DockerSandboxDriver` | `docker` CLI | ✓ (`--network=none`) | ✓ (`--read-only`) | ✓ | Hostile-input testing |
| `WebContainerSandboxDriver` | bridge URL | (browser-side) | iframe / WC | n/a | Front-end (Node) workflows |
| `CloudSandboxDriver` | API key | provider-managed | provider-managed | provider-managed | Hosted execution (E2B / Daytona / Modal) |
| `MockSandboxDriver` | none | n/a | n/a | n/a | Unit tests |

## SubprocessSandboxDriver (default)

Always available. For **function** jobs it delegates to the existing
`runtime.sandbox.CodeSandbox` which enforces a restricted `__builtins__`,
an import whitelist and (on POSIX) `RLIMIT_AS`.

For **command** jobs (linters, type checkers, test runners) it spawns a
plain subprocess in `workspace_dir` with the policy's timeout applied.

## DockerSandboxDriver

Requires the `docker` CLI and a running daemon. Each job runs in a fresh
container:

```
docker run --rm -i
    --network=none
    --read-only
    --memory=<mb>m
    --cpus=<n>
    --pids-limit=<n>
    --cap-drop=ALL
    --security-opt=no-new-privileges
    --tmpfs=/tmp:rw,size=64m
    --volume <workspace>:/work:<ro|rw>
    --workdir /work
    <image>
    <command>
```

For function jobs a tiny bootstrap script is generated on the fly, mounted
into the container and executed there. The script enforces the same
restricted builtins as `SubprocessSandboxDriver` so the safety guarantees
are equivalent (and augmented by the container boundary).

## Choosing a driver

```python
from vibe_coding.agent.sandbox import create_default_driver, SandboxPolicy

# Auto: Docker if available, subprocess otherwise
driver = create_default_driver(prefer="auto")

# Force subprocess (useful on CI where Docker is slow)
driver = create_default_driver(prefer="subprocess")

# Force Docker (raises RuntimeError if unavailable)
driver = create_default_driver(prefer="docker")

# Run a function job
from vibe_coding.agent.sandbox import SandboxJob
res = driver.execute(
    SandboxJob(
        kind="function",
        source_code="def run(x): return {'result': x * 2}",
        function_name="run",
        input_data={"x": 21},
    ),
    policy=SandboxPolicy(timeout_s=5, memory_mb=128),
)

# Run a command job
res = driver.execute(
    SandboxJob(
        kind="command",
        workspace_dir="./my_project",
        command=["ruff", "check", "."],
    ),
    policy=SandboxPolicy(timeout_s=60),
)
```

## Custom policies

```python
from vibe_coding.agent.sandbox import SandboxPolicy

strict = SandboxPolicy(
    timeout_s=10,
    memory_mb=64,
    cpu_limit=0.5,
    network=False,
    pids_limit=32,
    max_output_size=5_000,
)
```

`network=True` is only honoured by the Docker driver. When `network=False`
(default) the Docker driver passes `--network=none`. The subprocess driver
cannot enforce network isolation.

## WebContainerSandboxDriver

WebContainers run a full Node.js stack inside the browser via
WebAssembly. The driver itself is a **bridge proxy**: it talks JSON
over HTTP to a small server (the bundled Web UI in
`vibe_coding.agent.web`) that owns the actual WebContainer instance.

```python
from vibe_coding.agent.sandbox import (
    WebContainerSandboxDriver, WebContainerBridge, SandboxJob,
)

drv = WebContainerSandboxDriver(
    WebContainerBridge(
        base_url="http://127.0.0.1:8765/api/sandbox",
        auth_token="your-bridge-token",
        workspace_id="my-frontend-project",
    )
)
res = drv.execute(
    SandboxJob(kind="command", command=["vitest", "run"], workspace_dir="/work"),
)
```

Bridge contract: `POST /exec` takes the serialised `SandboxJob`,
returns a JSON object matching `SandboxResult` (success / stdout /
stderr / exit_code / output / duration_ms). `GET /health` is used by
`is_available()` for fast yes/no checks.

Use cases:

- Run `vitest` / `tsc` / `eslint` against the user's workspace from a
  browser-only IDE.
- Spin up `vite dev` while the agent edits files; the user watches the
  page live-update next to the chat.
- Quick demo / playground deployments where Docker isn't available.

## CloudSandboxDriver

The cloud driver is a thin shell over a pluggable
`CloudSandboxBackend`. Two reference backends ship in tree:

```python
from vibe_coding.agent.sandbox import (
    CloudSandboxDriver, E2BBackend, HTTPCloudBackend, create_cloud_driver,
)

# E2B (https://e2b.dev) — set E2B_API_KEY in the environment
drv = create_cloud_driver(backend="e2b")

# Generic HTTP cloud — talk to your own /exec endpoint (Modal, Daytona, …)
drv = CloudSandboxDriver(
    HTTPCloudBackend(base_url="https://exec.example.com", auth_token="…"),
    workspace_id="proj-1234",
)

# Auto: tries E2B first, falls back to HTTP backend if base_url is set
drv = create_cloud_driver(backend="auto", base_url="https://exec.example.com")
```

Both backends support **command** and **function** jobs. The driver
takes care of policy enforcement (timeout / max_output_size) and
maps results into the standard `SandboxResult` shape so callers are
oblivious to which provider answered.

### Writing a custom cloud backend

Implement the `CloudSandboxBackend` Protocol — three methods:

```python
class MyBackend:
    name = "my_cloud"
    def is_available(self) -> bool: ...
    def execute_command(self, *, command, workspace_id, env, stdin,
                        timeout_s, max_output_size) -> dict: ...
    def execute_function(self, *, source_code, function_name,
                         input_data, timeout_s, max_output_size) -> dict: ...
```

Return the same JSON shape the bundled backends use; the driver wraps
it into a `SandboxResult` for you.

## MockSandboxDriver

In-memory test double. Records every job it receives and returns a
scripted response — no spawn cost, no flakiness.

```python
from vibe_coding.agent.sandbox import MockSandboxDriver, SandboxJob

drv = MockSandboxDriver.passing(stdout="ok", output={"x": 42})
drv.execute(SandboxJob(kind="function", function_name="run"))
drv.assert_called_with_function("run")
```

Two factories cover the common cases: `MockSandboxDriver.passing(...)`
and `MockSandboxDriver.failing(...)`. For more complex scripting, pass
a `handler` callable that branches on the incoming `SandboxJob`.
