"""Shared fixtures / import-order guards for route tests.

torch is imported lazily and transitively by several FastAPI endpoints (via
``app.application`` → ``app.ai_engines.bert``). When the *first* torch import
happens inside Starlette ``TestClient``'s anyio worker thread, the native
extension initializes off the main thread and segfaults on macOS/arm64.

Pre-importing torch here — on the main thread, before any TestClient request —
side-steps that crash. It is a best-effort no-op when torch is not installed
(desktop / slim-server builds), matching the optional-torch posture in
``app/ai_engines/__init__.py``.
"""

from __future__ import annotations

try:  # pragma: no cover - environment dependent
    import torch  # noqa: F401
except Exception:  # noqa: BLE001 - torch absent or broken → tests degrade gracefully
    pass
