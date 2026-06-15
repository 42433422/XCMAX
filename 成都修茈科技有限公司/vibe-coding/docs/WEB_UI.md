# Web UI & IDE Integration

vibe-coding ships two HTTP-facing surfaces:

1. **Web UI** — a single-page browser app (HTML + Vue 3 from CDN; no
   build step required) backed by a small FastAPI server that wraps
   `VibeCoder`'s entire API.
2. **LSP-lite** — a JSON-RPC-style adapter for editor plugins (VSCode,
   Trae, Cursor) that runs over stdio or HTTP.

Install the optional `[web]` extra to pull in FastAPI + uvicorn:

```bash
pip install "vibe-coding[web]"
```

## Web UI

Launch the bundled server:

```bash
# default: http://127.0.0.1:8765
python -m vibe_coding web
# customise host/port + log level
python -m vibe_coding web --host 0.0.0.0 --port 9000 --log-level debug
```

Navigate to `http://localhost:8765/`; you'll see a minimal cockpit that
lets you switch between **Generate Skill / Workflow / Index Project /
Edit Project / Heal Project** without ever leaving the browser.

### JSON API

The same server exposes a JSON API under `/api/`:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/health` | GET | Liveness + version |
| `/api/code` | POST | Generate a single CodeSkill |
| `/api/workflow` | POST | Generate a multi-skill workflow |
| `/api/run/{skill_id}` | POST | Execute a known skill |
| `/api/index` | POST | Build / refresh the RepoIndex |
| `/api/edit` | POST | Generate a ProjectPatch |
| `/api/apply` | POST | Apply a ProjectPatch (with dry-run) |
| `/api/heal` | POST | Iterative heal loop |
| `/api/publish` | POST | Push a skill to MODstore |

All endpoints accept and return JSON. Example:

```bash
curl -X POST http://localhost:8765/api/code \
  -H "Content-Type: application/json" \
  -d '{"brief":"Reverse a string"}'
```

### Embedding into your own app

```python
from fastapi import FastAPI
from vibe_coding import VibeCoder, OpenAILLM
from vibe_coding.agent.web import create_app

main_app = FastAPI()
vibe_app = create_app(coder=VibeCoder(llm=OpenAILLM(api_key="...")))
main_app.mount("/vibe", vibe_app)
```

Pass `coder_factory=...` instead of `coder=...` to construct a fresh
coder per request — useful when the back-end serves multiple users
with different store directories.

## LSP-lite (editor plugin integration)

The LSP-lite adapter speaks **JSON-RPC 2.0** with framed messages
(`Content-Length: …\r\n\r\n<body>`) for stdio transports, identical to
real LSP — but the method set is intentionally tiny:

| Method | Purpose |
| --- | --- |
| `vibe.code` | Generate a CodeSkill |
| `vibe.edit` | Generate a ProjectPatch |
| `vibe.apply` | Apply a patch (with dry-run) |
| `vibe.heal` | Iterative heal loop |
| `vibe.index` | Build / refresh index |
| `vibe.publish` | Publish to MODstore |

Each request takes the same params as the corresponding HTTP endpoint
and returns the same response. Errors use standard JSON-RPC codes
(`-32601` method not found, `-32000` internal error).

### Run as a stdio server (for plugins)

```bash
python -m vibe_coding lsp
```

Now any editor plugin can spawn that process and pipe LSP messages
through it. Example session (with framing stripped):

```json
// → editor sends
{"jsonrpc":"2.0","id":1,"method":"vibe.edit","params":{"brief":"rename foo→bar","root":"."}}

// ← server replies
{"jsonrpc":"2.0","id":1,"result":{"patch_id":"…","summary":"…","edits":[…]}}
```

### HTTP transport (for non-stdio plugins)

If your editor plugin can't spawn subprocesses, it can post the same
JSON envelope to the Web UI server:

```python
from vibe_coding import VibeCoder, OpenAILLM
from vibe_coding.agent.web import LSPServer

coder = VibeCoder(llm=OpenAILLM(api_key="..."))
server = LSPServer(coder)

# ``handle_one`` is dict-in / dict-out — easy to wire to any HTTP layer.
response = server.handle_one({
    "jsonrpc": "2.0", "id": 1, "method": "vibe.code",
    "params": {"brief": "Reverse a string"}
})
```

## Plugin samples

Reference plugins for VSCode and the Trae IDE are tracked in their
respective extension repos; both connect via the stdio transport above.
