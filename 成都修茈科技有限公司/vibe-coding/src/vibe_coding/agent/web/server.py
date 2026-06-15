"""FastAPI web server + bundled single-page UI for vibe-coding.

Endpoints (mounted under the configurable ``api_prefix``, default
``/api``):

- ``POST /api/code``           — generate a single-skill ``CodeSkill``.
- ``POST /api/workflow``       — generate a multi-skill workflow.
- ``POST /api/run/{skill_id}`` — execute a known skill against JSON input.
- ``POST /api/index``          — build the :class:`RepoIndex` for a path.
- ``POST /api/edit``           — produce a ``ProjectPatch`` JSON.
- ``POST /api/apply``          — apply a ``ProjectPatch`` (with dry-run).
- ``POST /api/heal``           — iterative heal loop.
- ``POST /api/publish``        — publish a skill to a MODstore deployment.
- ``GET  /``                   — single-page UI (HTML + JS bundled in tree).
- ``GET  /api/health``         — server liveness.

The UI is a pragmatic single ``.html`` page (Vue 3 via CDN) so we don't
need a build step. Everything else is a thin facade over
:class:`VibeCoder` so the API surface stays in lock-step with the
Python-callable surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ...facade import VibeCoder
from ...nl.llm import LLMClient, MockLLM


class WebUIError(RuntimeError):
    """Raised when the optional ``fastapi`` dependency is not installed."""


def _require_fastapi():
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on env
        raise WebUIError(
            "fastapi is required for vibe-coding's Web UI. "
            "Install it with `pip install fastapi uvicorn` or "
            "`pip install vibe-coding[web]`."
        ) from exc


_INDEX_HTML = """<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>vibe-coding</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI",
        "PingFang SC", "Hiragino Sans GB", sans-serif;
      background: #0d1117;
      color: #e6edf3;
      min-height: 100vh;
    }
    header {
      padding: 18px 24px;
      border-bottom: 1px solid #21262d;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    header h1 { margin: 0; font-size: 18px; font-weight: 600; }
    main {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 16px;
      padding: 16px;
      max-width: 1400px;
      margin: 0 auto;
    }
    .panel {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 8px;
      padding: 16px;
      min-height: 300px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #7d8590;
    }
    label { display: block; margin: 8px 0 4px; color: #7d8590; font-size: 12px; }
    input, textarea, select {
      width: 100%;
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 6px;
      color: #e6edf3;
      padding: 8px;
      font-family: inherit;
      font-size: 13px;
    }
    textarea { min-height: 80px; resize: vertical; }
    button {
      background: #238636;
      color: #fff;
      border: 0;
      padding: 8px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
      margin-top: 8px;
    }
    button.secondary { background: #30363d; }
    button:disabled { background: #21262d; cursor: not-allowed; }
    pre {
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 6px;
      padding: 12px;
      overflow: auto;
      max-height: 540px;
      font: 12px/1.4 ui-monospace, SF Mono, Menlo, monospace;
    }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .badge {
      display: inline-block;
      background: #1f6feb20;
      color: #58a6ff;
      padding: 1px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
    }
    .error { color: #f85149; }
  </style>
</head>
<body>
  <header>
    <h1>vibe-coding · web ui</h1>
    <span class="badge" id="version">…</span>
  </header>
  <main>
    <div class="panel">
      <h2>Action</h2>
      <label>Mode</label>
      <select id="mode">
        <option value="code">Generate Skill</option>
        <option value="workflow">Workflow</option>
        <option value="index">Index Project</option>
        <option value="edit">Edit Project</option>
        <option value="heal">Heal Project</option>
      </select>
      <label>Brief</label>
      <textarea id="brief" placeholder="把字符串反转 / 给所有 print 加 logger / …"></textarea>
      <label>Project root (for index/edit/heal)</label>
      <input id="root" placeholder=". (default cwd)" />
      <div class="row">
        <button id="run" type="button">Run</button>
        <button id="clear" class="secondary" type="button">Clear</button>
      </div>
      <p class="error" id="err"></p>
    </div>
    <div class="panel">
      <h2>Result</h2>
      <pre id="result">// output appears here</pre>
    </div>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    fetch('/api/health').then(r => r.json()).then(d => {
      $('version').textContent = 'v' + (d.version || 'dev');
    });
    $('run').addEventListener('click', async () => {
      const mode = $('mode').value;
      const brief = $('brief').value.trim();
      const root = $('root').value.trim() || '.';
      $('err').textContent = '';
      $('result').textContent = '... running ...';
      $('run').disabled = true;
      try {
        let url = '/api/' + mode;
        let body = { brief };
        if (mode === 'index') { url = '/api/index'; body = { root }; }
        else if (mode === 'edit') body = { brief, root };
        else if (mode === 'heal') body = { brief, root };
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok) {
          $('err').textContent = data.error || ('HTTP ' + resp.status);
        }
        $('result').textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        $('err').textContent = 'request failed: ' + e;
      } finally {
        $('run').disabled = false;
      }
    });
    $('clear').addEventListener('click', () => {
      $('brief').value = '';
      $('result').textContent = '// output appears here';
    });
  </script>
</body>
</html>
"""


def create_app(
    *,
    coder: VibeCoder | None = None,
    coder_factory: Callable[[], VibeCoder] | None = None,
    api_prefix: str = "/api",
):
    """Build a FastAPI app exposing the vibe-coding API.

    Pass either ``coder`` (a configured :class:`VibeCoder`) or
    ``coder_factory`` (called once per request, useful when each request
    should bind to a different ``store_dir`` / ``llm``). When neither is
    given, the app constructs a :class:`MockLLM`-backed coder for demo
    purposes — that's only safe for local development.
    """
    _require_fastapi()
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    if coder is None and coder_factory is None:
        coder_factory = _default_demo_coder

    def _resolve_coder() -> VibeCoder:
        if coder is not None:
            return coder
        assert coder_factory is not None
        return coder_factory()

    app = FastAPI(title="vibe-coding", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get(f"{api_prefix}/health")
    async def health() -> dict[str, Any]:
        from ... import __version__

        return {"ok": True, "version": __version__}

    # ---------------------------------------------------- single-skill flow

    @app.post(f"{api_prefix}/code")
    async def generate_code(payload: dict[str, Any]) -> dict[str, Any]:
        brief = (payload.get("brief") or "").strip()
        if not brief:
            raise HTTPException(400, detail="`brief` is required")
        skill = _resolve_coder().code(
            brief,
            mode=payload.get("mode") or "brief_first",
            skill_id=payload.get("skill_id"),
            dependencies=payload.get("dependencies"),
        )
        return skill.to_dict()

    @app.post(f"{api_prefix}/workflow")
    async def generate_workflow(payload: dict[str, Any]) -> dict[str, Any]:
        brief = (payload.get("brief") or "").strip()
        if not brief:
            raise HTTPException(400, detail="`brief` is required")
        report = _resolve_coder().workflow_with_report(brief)
        return {
            "workflow_id": report.workflow_id,
            "graph": report.graph.to_dict(),
            "warnings": report.warnings,
        }

    @app.post(f"{api_prefix}/run" + "/{skill_id}")
    async def run_skill(skill_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        run = _resolve_coder().run(skill_id, dict(payload or {}))
        return run.to_dict()

    # ---------------------------------------------------- project agent flow

    @app.post(f"{api_prefix}/index")
    async def index_project(payload: dict[str, Any]) -> dict[str, Any]:
        root = payload.get("root") or "."
        index = _resolve_coder().index_project(root, refresh=bool(payload.get("refresh", False)))
        return index.summary()

    @app.post(f"{api_prefix}/edit")
    async def edit_project(payload: dict[str, Any]) -> dict[str, Any]:
        brief = (payload.get("brief") or "").strip()
        root = payload.get("root") or "."
        if not brief:
            raise HTTPException(400, detail="`brief` is required")
        patch = _resolve_coder().edit_project(brief, root=root)
        return patch.to_dict()

    @app.post(f"{api_prefix}/apply")
    async def apply_patch(payload: dict[str, Any]) -> dict[str, Any]:
        from ..patch import ProjectPatch

        patch_dict = payload.get("patch")
        if not isinstance(patch_dict, dict):
            raise HTTPException(400, detail="`patch` must be a ProjectPatch JSON object")
        root = payload.get("root") or "."
        dry_run = bool(payload.get("dry_run", False))
        try:
            patch = ProjectPatch.from_dict(patch_dict)
        except Exception as exc:
            raise HTTPException(400, detail=f"invalid patch: {exc}") from exc
        result = _resolve_coder().apply_patch(patch, root=root, dry_run=dry_run)
        return result.to_dict()

    @app.post(f"{api_prefix}/heal")
    async def heal_project(payload: dict[str, Any]) -> dict[str, Any]:
        brief = (payload.get("brief") or "").strip()
        root = payload.get("root") or "."
        max_rounds = int(payload.get("max_rounds") or 3)
        if not brief:
            raise HTTPException(400, detail="`brief` is required")
        result = _resolve_coder().heal_project(
            brief, root=root, max_rounds=max_rounds
        )
        return result.to_dict()

    @app.post(f"{api_prefix}/publish")
    async def publish_skill(payload: dict[str, Any]) -> dict[str, Any]:
        skill_id = (payload.get("skill_id") or "").strip()
        base_url = (payload.get("base_url") or "").strip()
        admin_token = (payload.get("admin_token") or "").strip()
        if not (skill_id and base_url and admin_token):
            raise HTTPException(
                400, detail="skill_id, base_url, admin_token are required"
            )
        result = _resolve_coder().publish_skill(
            skill_id,
            base_url=base_url,
            admin_token=admin_token,
            version=payload.get("version") or "",
            name=payload.get("name") or "",
            description=payload.get("description") or "",
            price=float(payload.get("price") or 0.0),
            artifact=payload.get("artifact") or "mod",
            industry=payload.get("industry") or "通用",
            verify_ssl=bool(payload.get("verify_ssl", True)),
            dry_run=bool(payload.get("dry_run", False)),
        )
        return result.to_dict()

    return app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    coder: VibeCoder | None = None,
    coder_factory: Callable[[], VibeCoder] | None = None,
    log_level: str = "info",
) -> None:
    """Boot the bundled UI/API on ``host:port`` via uvicorn."""
    _require_fastapi()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise WebUIError(
            "uvicorn is required to launch the Web UI. "
            "Install with `pip install uvicorn` or `pip install vibe-coding[web]`."
        ) from exc
    app = create_app(coder=coder, coder_factory=coder_factory)
    uvicorn.run(app, host=host, port=port, log_level=log_level)


def _default_demo_coder() -> VibeCoder:
    """Best-effort fallback coder so ``run_server()`` works out of the box.

    Uses :class:`MockLLM` against a temp store directory; suitable for
    poking at the UI but **not** for real generation. Production
    deployments should pass an explicit ``coder`` (or ``coder_factory``).
    """
    import tempfile

    return VibeCoder(
        llm=MockLLM(["{}"]),
        store_dir=Path(tempfile.gettempdir()) / "vibe_coding_web_demo",
    )


__all__ = ["WebUIError", "create_app", "run_server"]
