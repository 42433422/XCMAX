# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


def rehydrate_employee_pack_bundles(
    employee_id: str, *, db: _facade().Session, user: _facade().User
) -> bool:
    """Rehydrate bundled workflow definitions for an already-materialized pack.

    Call this after ``materialize_employee_pack_if_missing`` when you have the
    target ``db`` session and ``user`` objects available (e.g. in request
    context).  Safe to call multiple times — bundles track their own
    ``rehydrated_*_id`` markers to avoid creating duplicate rows.

    Returns ``True`` if the pack directory and manifest exist (regardless of
    whether there were any bundles to rehydrate).
    """
    lib = _facade().modstore_library_path()
    pack_dir = lib / (employee_id or "").strip()
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return False
    try:
        from modstore_server.employee_pack_workflow_bundle import (
            rehydrate_workflow_bundles,
        )

        raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
        if raw.get("workflow_bundles") or raw.get("script_workflow_bundles"):
            raw = rehydrate_workflow_bundles(db, user, raw, commit=True)
            mf_path.write_text(
                _facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except RECOVERABLE_ERRORS:
        import logging as _logging

        _logging.getLogger(__name__).warning("rehydrate_employee_pack_bundles failed")
    return mf_path.is_file()


def mod_compileall_warnings(mod_dir: _facade().Path) -> _facade().List[str]:
    """对 Mod 下 backend 内 .py 做语法编译检查；失败仅作警告列表，不删 Mod。"""
    backend = mod_dir / "backend"
    if not backend.is_dir():
        return []
    out: _facade().List[str] = []
    for p in sorted(backend.rglob("*.py")):
        try:
            _facade().py_compile.compile(str(p), doraise=True)
        except _facade().py_compile.PyCompileError as e:
            rel = p.relative_to(mod_dir).as_posix()
            out.append(f"{rel}: {e.msg}")
        except OSError as e:
            rel = p.relative_to(mod_dir).as_posix()
            out.append(f"{rel}: {e}")
    return out


def employee_pack_consistency_warnings(mod_dir: _facade().Path) -> _facade().List[str]:
    """员工包静态一致性校验（Phase 1 修复对应的验收规则）：

    1. ``manifest.employee_config_v2.cognition.agent.model.max_tokens`` 与
       ``backend/employees/*.py`` 中 ``call_llm(...)`` 的 ``max_tokens=...`` 一致。
    2. ``actions.handlers`` 声明的每个 handler 在员工 .py 里都能找到对应分支
       （形如 ``'echo'`` / ``'llm_md'`` / ``'webhook'`` 字符串字面量出现）。
    3. 每个 ``await call_llm(`` 调用都被 ``try:`` 包裹（行级启发式：向上 6 行内出现 ``try:``）。
    4. 员工 ``run`` 返回结构包含统一字段（出现 ``'ok'``/``'summary'``/``'error'`` 字面量）。

    仅做静态启发式检查，目的是防止再出现「manifest 与代码脱节 / handlers 形同虚设
    / call_llm 裸 await / 返回字段三套」这类回归。返回的字符串将作为 mod_sandbox
    的 warnings 显示在「包体与 Python 校验」步骤；非阻塞。
    """
    backend = mod_dir / "backend"
    manifest_path = mod_dir / "manifest.json"
    if not backend.is_dir() or not manifest_path.is_file():
        return []
    try:
        manifest = _facade().json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError):
        return []
    if not isinstance(manifest, dict) or manifest.get("artifact") != "employee_pack":
        return []
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
    model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    declared_handlers = [
        str(h).strip()
        for h in (actions.get("handlers") if isinstance(actions.get("handlers"), list) else [])
        if isinstance(h, str) and str(h).strip()
    ]
    manifest_max_tokens = model.get("max_tokens")
    emp_dir = backend / "employees"
    if not emp_dir.is_dir():
        return []
    emp_files = [p for p in sorted(emp_dir.glob("*.py")) if p.name != "__init__.py"]
    if not emp_files:
        return []
    warnings: _facade().List[str] = []
    for emp_py in emp_files:
        try:
            src = emp_py.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = emp_py.relative_to(mod_dir).as_posix()
        lines = src.splitlines()
        for idx, ln in enumerate(lines):
            if "await call_llm(" in ln or ("call_llm(messages" in ln and "await" in ln):
                window = "\n".join(lines[max(0, idx - 6) : idx])
                if "try:" not in window and "asyncio.wait_for" not in ln:
                    warnings.append(
                        f"{rel}:L{idx + 1}: call_llm 调用未被 try/except 或 asyncio.wait_for 包裹（建议统一异常返回）"
                    )
        missing_keys = [
            repr(k)
            for k in ("ok", "summary", "error")
            if f"'{k}'" not in src and f'"{k}"' not in src
        ]
        if missing_keys:
            warnings.append(
                f"{rel}: run 返回结构未见统一字段 {missing_keys}，建议返回 {{ok, summary, items, warnings, error, meta}}"
            )
        if isinstance(manifest_max_tokens, int) and manifest_max_tokens > 0:
            if (
                f"max_tokens={manifest_max_tokens}" not in src
                and f"max_tokens = {manifest_max_tokens}" not in src
            ):
                if _facade().re.search("max_tokens\\s*=\\s*\\d+", src):
                    warnings.append(
                        f"{rel}: call_llm 的 max_tokens 与 manifest({manifest_max_tokens}) 不一致；建议从 manifest 动态读取，避免与 employee_config_v2.cognition.agent.model.max_tokens 漂移"
                    )
        for h in declared_handlers:
            if h in {"vibe_edit", "vibe_heal", "vibe_code"}:
                continue
            if f"'{h}'" not in src and f'"{h}"' not in src:
                warnings.append(
                    f"{rel}: manifest.actions.handlers 声明 '{h}'，但员工实现中未见对应分支字面量"
                )
    return warnings
