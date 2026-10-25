"""Path-isolated, serialized backend initialization and declared hook registration."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from threading import RLock
from types import ModuleType

from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..manifest import ModMetadata
from .ports import ImportBackend, TrustedChild

_MOD_IMPORT_LOCK = RLock()
_MOD_IMPORT_ERRORS = (BaseException,)  # Never publish a partly initialized module.


def import_backend(
    mod_path: str,
    mod_id: str,
    stem: str,
    *,
    child: TrustedChild,
    relative_file: Callable[[str, str], str | None],
) -> ModuleType:
    """Load a fully initialized, path-isolated Mod backend module, including nested stems."""
    backend_path = child(mod_path, "backend", directory=True)
    path = relative_file(backend_path, f"{stem}.py") if backend_path else None
    if path is None and stem == "blueprints" and backend_path:
        path = relative_file(backend_path, "pack_surface.py")
    if path is None:
        raise FileNotFoundError(f"Mod {mod_id} backend file missing")
    safe = "".join(c if c.isalnum() else "_" for c in mod_id)
    import hashlib

    normalized_path = os.path.normpath(os.path.abspath(mod_path))
    path_digest = hashlib.sha256(normalized_path.encode()).hexdigest()[:16]
    spec_name = f"_xcagi_mod_{safe}_{path_digest}_{stem}"
    with _MOD_IMPORT_LOCK:
        existing = sys.modules.get(spec_name)
        if existing is not None:
            return existing
        spec = importlib.util.spec_from_file_location(spec_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec_name] = module
        try:
            spec.loader.exec_module(module)
        except _MOD_IMPORT_ERRORS:
            sys.modules.pop(spec_name, None)
            raise
        return module


def register_hooks(
    mod_id: str, metadata: ModMetadata, import_backend: ImportBackend, logger: logging.Logger
) -> None:
    """Subscribe manifest hook handlers. Paths are relative to each mod's backend/ on sys.path."""
    if not metadata.hooks:
        return
    from app.infrastructure.mods.hooks import subscribe

    mod_fs_path = metadata.mod_path or ""
    if not mod_fs_path:
        logger.error("Mod %s has no mod_path; cannot resolve hook handlers", mod_id)
        return
    for event, handler_spec in metadata.hooks.items():
        spec = (handler_spec or "").strip()
        if spec.startswith("backend."):
            spec = spec[len("backend.") :]
        try:
            (module_name, _, attr) = spec.rpartition(".")
            if not module_name or not attr:
                logger.error("Invalid hook handler spec for mod %s: %r", mod_id, handler_spec)
                continue
            module = import_backend(mod_fs_path, mod_id, module_name)
            handler = getattr(module, attr, None)
            if not callable(handler):
                logger.error("Hook handler not callable for mod %s: %r", mod_id, handler_spec)
                continue
            subscribe(event, handler)
            logger.info("Mod %s hook registered: %s -> %s", mod_id, event, spec)
        except RECOVERABLE_ERRORS as e:
            logger.error("Failed to register hook %r for mod %s: %s", event, mod_id, e)


def short_exc_message(exc: BaseException, max_len: int = 480) -> str:
    s = str(exc).strip() or type(exc).__name__
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def invoke_init_hook(
    init_fn: Callable[..., object], *, mod_id: str | None = None, logger: logging.Logger
) -> None:
    """调用 manifest backend.init；兼容无参与 legacy (app, mod_id) 签名。"""
    import inspect

    try:
        sig = inspect.signature(init_fn)
    except (TypeError, ValueError):
        init_fn()
        return
    params = [
        p
        for p in sig.parameters.values()
        if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    if not params:
        init_fn()
        return
    kwargs: dict[str, object] = {}
    for p in params:
        if p.name == "app":
            kwargs["app"] = None
        elif p.name == "mod_id":
            kwargs["mod_id"] = mod_id
        elif p.default is inspect.Parameter.empty:
            logger.warning(
                "Skip mod init %s: cannot satisfy required parameter %r",
                getattr(init_fn, "__qualname__", init_fn),
                p.name,
            )
            return
    try:
        sig.bind(**kwargs)
    except TypeError:  # noqa: TRY003 - signature bind failure selects legacy no-arg init.
        init_fn()
        return
    init_fn(**kwargs)
