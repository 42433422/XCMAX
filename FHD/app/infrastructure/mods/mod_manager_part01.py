# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


def is_mods_disabled() -> bool:
    """为 true 时不加载任何 Mod（扩展蓝图、行业覆盖、Hooks 等），仅用核心与原始配置/数据库。"""
    v = (_facade().os.environ.get("XCAGI_DISABLE_MODS") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _default_mods_root() -> str:
    """Resolve the MOD root across source and packaged layouts."""
    _facade().logger.debug(
        "[_default_mods_root] Resolving mods root, CWD: %s", _facade().os.getcwd()
    )
    env = (
        _facade().os.environ.get("XCAGI_MODS_ROOT")
        or _facade().os.environ.get("XCAGI_MODS_DIR")
        or ""
    ).strip()
    if env:
        p = _facade().os.path.abspath(env)
        if _facade().os.path.isdir(p):
            _facade().logger.debug("[_default_mods_root] Mods root from env: %s", p)
            return p
        _facade().logger.warning(
            "[_default_mods_root] XCAGI_MODS_ROOT / XCAGI_MODS_DIR is set but not a directory: %s",
            p,
        )
    file_here = _facade().os.path.abspath(__file__)
    from_pkg_layout = _facade().os.path.join(
        _facade().os.path.dirname(
            _facade().os.path.dirname(
                _facade().os.path.dirname(_facade().os.path.dirname(file_here))
            )
        ),
        "mods",
    )
    _facade().logger.debug(
        "[_default_mods_root] Checking package-relative path: %s, exists: %s",
        from_pkg_layout,
        _facade().os.path.isdir(from_pkg_layout),
    )
    if _facade().os.path.isdir(from_pkg_layout):
        _facade().logger.debug(
            "[_default_mods_root] Mods root (next to app package): %s", from_pkg_layout
        )
        return from_pkg_layout
    cwd_mods = _facade().os.path.join(_facade().os.getcwd(), "mods")
    _facade().logger.debug(
        "[_default_mods_root] Checking CWD mods: %s, exists: %s",
        cwd_mods,
        _facade().os.path.isdir(cwd_mods),
    )
    if _facade().os.path.isdir(cwd_mods):
        _facade().logger.debug("[_default_mods_root] Mods root (./mods from cwd): %s", cwd_mods)
        return cwd_mods
    cur = _facade().os.path.abspath(_facade().os.getcwd())
    for i in range(8):
        trial = _facade().os.path.join(cur, "mods")
        _facade().logger.debug(
            "[_default_mods_root] Walking up: %s, exists: %s", trial, _facade().os.path.isdir(trial)
        )
        if _facade().os.path.isdir(trial):
            _facade().logger.debug("[_default_mods_root] Mods root (walk up from cwd): %s", trial)
            return trial
        parent = _facade().os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    _facade().logger.warning(
        "[_default_mods_root] No mods directory found; using package-relative path (may be empty): %s. Set XCAGI_MODS_ROOT or run from project root.",
        from_pkg_layout,
    )
    return from_pkg_layout


def _repo_layout_mods_candidates() -> list[str]:
    """Find additional repository MOD roots missing from a packaged deployment."""
    file_here = _facade().os.path.abspath(__file__)
    repo_root = _facade().os.path.dirname(
        _facade().os.path.dirname(_facade().os.path.dirname(_facade().os.path.dirname(file_here)))
    )
    out: list[str] = []
    for rel in ("mods", _facade().os.path.join("XCAGI", "mods")):
        p = _facade().os.path.abspath(_facade().os.path.join(repo_root, rel))
        if _facade().os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def _all_mods_roots(primary: str) -> list[str]:
    """主 mods_root + 仓库内其它 mods 目录（去重，主目录优先）。"""
    roots: list[str] = []
    primary_abs = _facade().os.path.abspath((primary or "").strip())
    if primary_abs and _facade().os.path.isdir(primary_abs) and (primary_abs not in roots):
        roots.append(primary_abs)
    env = (
        _facade().os.environ.get("XCAGI_MODS_ROOT")
        or _facade().os.environ.get("XCAGI_MODS_DIR")
        or ""
    ).strip()
    if env:
        p = _facade().os.path.abspath(env)
        if _facade().os.path.isdir(p) and p not in roots:
            roots.append(p)
    for p in _facade()._repo_layout_mods_candidates():
        if p not in roots:
            roots.append(p)
    return roots


def _trusted_child_path(parent: str, child_name: str, *, directory: bool) -> str | None:
    try:
        with _facade().os.scandir(parent) as entries:
            for entry in entries:
                if entry.name != child_name or entry.is_symlink():
                    continue
                if directory and entry.is_dir(follow_symlinks=False):
                    return entry.path
                if not directory and entry.is_file(follow_symlinks=False):
                    return entry.path
    except OSError:
        return None
    return None


def _backend_path_for_mod(mod_path: str) -> str:
    """Return the conventional backend path without touching the filesystem."""
    return _facade().os.path.join(mod_path, "backend")


def _trusted_relative_file(parent: str, relative_path: str) -> str | None:
    """Resolve a nested regular file using names returned by directory scans."""
    parts = relative_path.replace("\\", "/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    current = parent
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        resolved = _facade()._trusted_child_path(current, part, directory=not is_last)
        if resolved is None:
            return None
        current = resolved
    return current


def import_mod_backend_py(mod_path: str, mod_id: str, stem: str):
    """
    从指定 Mod 的 backend/<stem>.py 按文件路径加载为唯一模块名，避免多个 Mod 都叫 blueprints/services 时 sys.modules 冲突。
    stem 不含 .py；允许 ``employees/name`` 这类 backend 内相对模块路径。
    """
    backend_path = _facade()._trusted_child_path(mod_path, "backend", directory=True)
    path = _facade()._trusted_relative_file(backend_path, f"{stem}.py") if backend_path else None
    if path is None:
        raise FileNotFoundError(f"Mod {mod_id} backend file missing")
    safe = "".join(c if c.isalnum() else "_" for c in mod_id)
    import hashlib

    path_digest = hashlib.sha256(
        _facade().os.path.normpath(_facade().os.path.abspath(mod_path)).encode()
    ).hexdigest()[:16]
    spec_name = f"_xcagi_mod_{safe}_{path_digest}_{stem}"
    existing = _facade().sys.modules.get(spec_name)
    if existing is not None:
        return existing
    spec = _facade().importlib.util.spec_from_file_location(spec_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    module = _facade().importlib.util.module_from_spec(spec)
    _facade().sys.modules[spec_name] = module
    spec.loader.exec_module(module)
    return module


def _register_mod_hooks(mod_id: str, metadata: _facade().ModMetadata) -> None:
    """Subscribe manifest hook handlers. Paths are relative to each mod's backend/ on sys.path."""
    if not metadata.hooks:
        return
    from app.infrastructure.mods.hooks import subscribe

    mod_fs_path = metadata.mod_path or ""
    if not mod_fs_path:
        _facade().logger.error("Mod %s has no mod_path; cannot resolve hook handlers", mod_id)
        return
    for event, handler_spec in metadata.hooks.items():
        spec = (handler_spec or "").strip()
        if spec.startswith("backend."):
            spec = spec[len("backend.") :]
        try:
            (module_name, _, attr) = spec.rpartition(".")
            if not module_name or not attr:
                _facade().logger.error(
                    "Invalid hook handler spec for mod %s: %r", mod_id, handler_spec
                )
                continue
            module = _facade().import_mod_backend_py(mod_fs_path, mod_id, module_name)
            handler = getattr(module, attr, None)
            if not callable(handler):
                _facade().logger.error(
                    "Hook handler not callable for mod %s: %r", mod_id, handler_spec
                )
                continue
            subscribe(event, handler)
            _facade().logger.info("Mod %s hook registered: %s -> %s", mod_id, event, spec)
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.error("Failed to register hook %r for mod %s: %s", event, mod_id, e)


def _short_exc_message(exc: BaseException, max_len: int = 480) -> str:
    s = str(exc).strip() or type(exc).__name__
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _invoke_mod_init_hook(init_fn: _facade().Any, *, mod_id: str | None = None) -> None:
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
    kwargs: dict[str, _facade().Any] = {}
    for p in params:
        if p.name == "app":
            kwargs["app"] = None
        elif p.name == "mod_id":
            kwargs["mod_id"] = mod_id
        elif p.default is inspect.Parameter.empty:
            _facade().logger.warning(
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
