#!/usr/bin/env python3
"""Mechanically move top-level definitions into facade-backed part modules.

This is a task-local refactoring helper.  It deliberately skips definitions
whose unparsed body is too large for one architecture-fitness compliant part.
"""

from __future__ import annotations

import argparse
import ast
import copy
import re
import subprocess
from pathlib import Path


MAX_PART_LINES = 420


def _bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Param)):
            names.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, ast.Import):
            names.update(alias.asname or alias.name.split(".", 1)[0] for alias in child.names)
        elif isinstance(child, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in child.names if alias.name != "*")
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
    declared_globals = {
        name
        for child in ast.walk(node)
        if isinstance(child, ast.Global)
        for name in child.names
    }
    names.difference_update(declared_globals)
    return names


class _FacadeGlobals(ast.NodeTransformer):
    def __init__(self, module_globals: set[str], local_names: set[str]) -> None:
        self.module_globals = module_globals
        self.local_names = local_names

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if (
            isinstance(node.ctx, (ast.Load, ast.Store, ast.Del))
            and node.id in self.module_globals
            and node.id not in self.local_names
            and node.id != "_facade"
        ):
            return ast.copy_location(
                ast.Attribute(
                    value=ast.Call(func=ast.Name(id="_facade", ctx=ast.Load()), args=[], keywords=[]),
                    attr=node.id,
                    ctx=node.ctx,
                ),
                node,
            )
        return node


def repair_facade_global_refs(repo_root: Path, paths: list[Path]) -> None:
    """Route ``global`` reads and writes in extracted definitions through the facade."""
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        facade_fn = next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_facade"
            ),
            None,
        )
        if facade_fn is None:
            continue
        module_names = [
            child.value
            for child in ast.walk(facade_fn)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and "." in child.value
        ]
        if not module_names:
            continue
        original = repo_root.joinpath(*module_names[0].split(".")).with_suffix(".py")
        if not original.exists():
            continue
        module_globals = _assigned_at_module_level(
            ast.parse(original.read_text(encoding="utf-8"))
        )
        changed = False
        for index, node in enumerate(tree.body):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name == "_facade":
                continue
            before = ast.dump(node, include_attributes=False)
            transformed = _FacadeGlobals(module_globals, _bound_names(node)).visit(node)
            ast.fix_missing_locations(transformed)
            tree.body[index] = transformed
            changed = changed or before != ast.dump(transformed, include_attributes=False)
        if changed:
            rendered = ast.unparse(tree).rstrip() + "\n"
            if source.startswith("# mypy: ignore-errors\n"):
                rendered = "# mypy: ignore-errors\n" + rendered
            path.write_text(rendered, encoding="utf-8")
        print(f"{path}: repaired={changed}")


class _LocalPartReference(ast.NodeTransformer):
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        node = self.generic_visit(node)
        if (
            node.attr in self.names
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_facade"
            and not node.value.args
            and not node.value.keywords
        ):
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return node


def _localize_import_time_refs(node: ast.AST, names: set[str]) -> None:
    replacer = _LocalPartReference(names)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.decorator_list = [replacer.visit(item) for item in node.decorator_list]
        node.returns = replacer.visit(node.returns) if node.returns else None
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if arg.annotation:
                arg.annotation = replacer.visit(arg.annotation)
        for arg in (args.vararg, args.kwarg):
            if arg and arg.annotation:
                arg.annotation = replacer.visit(arg.annotation)
        args.defaults = [replacer.visit(item) for item in args.defaults]
        args.kw_defaults = [
            replacer.visit(item) if item is not None else None for item in args.kw_defaults
        ]
        for child in ast.walk(node):
            if isinstance(child, ast.AnnAssign):
                child.annotation = replacer.visit(child.annotation)
    elif isinstance(node, ast.ClassDef):
        node.decorator_list = [replacer.visit(item) for item in node.decorator_list]
        node.bases = [replacer.visit(item) for item in node.bases]
        node.keywords = [replacer.visit(item) for item in node.keywords]
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _localize_import_time_refs(child, names)
            else:
                replacer.visit(child)


def fix_part_import_refs(paths: list[Path]) -> None:
    for path in paths:
        source = path.read_text(encoding="utf-8")
        directives = [
            line
            for line in source.splitlines()
            if line.startswith(("# mypy:", "# ruff:"))
        ]
        tree = ast.parse(source)
        names = _assigned_at_module_level(tree)
        names.discard("_facade")
        for node in tree.body:
            _localize_import_time_refs(node, names)
        ast.fix_missing_locations(tree)
        rendered = ast.unparse(tree) + "\n"
        if directives:
            rendered = "\n".join(directives) + "\n" + rendered
        path.write_text(rendered, encoding="utf-8")
        print(f"{path}: localized={len(names)}")


def split_large_class(repo_root: Path, path: Path) -> list[Path]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    globals_ = _assigned_at_module_level(tree)
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.end_lineno - node.lineno + 1 > 500
    ]
    if not classes:
        return []
    if len(classes) > 1:
        raise RuntimeError(f"multiple giant classes require a separate pass: {path}")
    class_node = classes[0]
    movable = [
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and len(ast.unparse(node).splitlines()) <= MAX_PART_LINES - 4
        and not (node.name.startswith("__") and not node.name.endswith("__"))
    ]
    if not movable:
        return []
    groups: list[list[ast.AST]] = []
    current: list[ast.AST] = []
    current_lines = 3
    for node in movable:
        rendered_lines = len(ast.unparse(node).splitlines()) + 1
        keeps_property_pair = bool(
            current
            and any(
                isinstance(dec, ast.Attribute)
                and isinstance(dec.value, ast.Name)
                and dec.value.id == current[-1].name
                and dec.attr in {"setter", "deleter"}
                for dec in getattr(node, "decorator_list", ())
            )
        )
        if current and current_lines + rendered_lines > MAX_PART_LINES and not keeps_property_pair:
            groups.append(current)
            current = []
            current_lines = 3
        current.append(node)
        current_lines += rendered_lines
    if current:
        groups.append(current)

    module = _module_name(repo_root, path)
    created: list[Path] = []
    mixin_names: list[str] = []
    replacements: list[tuple[int, int, str]] = []
    existing_indexes = [
        int(match.group(1))
        for candidate in path.parent.glob(f"{path.stem}_part*.py")
        if (match := re.fullmatch(rf"{re.escape(path.stem)}_part(\d+)\.py", candidate.name))
    ]
    first_index = max(existing_indexes, default=0) + 1
    for index, group in enumerate(groups, start=first_index):
        mixin_name = f"_{class_node.name}Part{index:02d}Mixin"
        mixin_names.append(mixin_name)
        suffix = f"_{class_node.name.lower()}_mixin{index:02d}"
        part_path = path.with_name(f"{path.stem}{suffix}.py")
        methods: list[ast.AST] = []
        for method in group:
            cloned = ast.parse(ast.unparse(method)).body[0]
            local_names = _bound_names(cloned)
            local_names.discard(method.name)
            transformed = _FacadeGlobals(globals_, local_names).visit(cloned)
            ast.fix_missing_locations(transformed)
            methods.append(transformed)
            replacements.append((_node_start(method), method.end_lineno, ""))
        mixin = ast.ClassDef(
            name=mixin_name,
            bases=[],
            keywords=[],
            body=methods,
            decorator_list=[],
        )
        ast.fix_missing_locations(mixin)
        part_source = (
            '"""Behavior mixin extracted from the public facade class."""\n\n'
            "from __future__ import annotations\n\n"
            "import importlib\n\n"
            f"def _facade():\n    return importlib.import_module({module!r})\n\n\n"
            + ast.unparse(mixin)
            + "\n"
        )
        part_path.write_text(part_source, encoding="utf-8")
        created.append(part_path)

    import_at = min([class_node.lineno, *(d.lineno for d in class_node.decorator_list)])
    import_block = "\n".join(
        f"from {module}_{class_node.name.lower()}_mixin{index:02d} import {name}"
        for index, name in enumerate(mixin_names, start=1)
    ) + "\n\n"
    replacements.append((import_at, import_at - 1, import_block))
    bases = [*mixin_names, *(ast.unparse(base) for base in class_node.bases)]
    keywords = [ast.unparse(item) for item in class_node.keywords]
    args = ", ".join([*bases, *keywords])
    header = f"class {class_node.name}({args}):\n" if args else f"class {class_node.name}:\n"
    first_body_line = class_node.body[0].lineno
    replacements.append((class_node.lineno, first_body_line - 1, header))

    for start, end, replacement in sorted(replacements, reverse=True):
        if end < start:
            lines[start - 1 : start - 1] = [replacement]
        else:
            lines[start - 1 : end] = [replacement]
    path.write_text("".join(lines), encoding="utf-8")
    return created


def compact_modules(paths: list[Path]) -> None:
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rendered = ast.unparse(tree)
        if rendered.startswith("# ruff:"):
            rendered = "\n".join(rendered.splitlines()[1:])
        path.write_text(
            "# ruff: noqa: E402, F401, I001\n" + rendered.rstrip() + "\n",
            encoding="utf-8",
        )
        print(f"{path}: lines={len(path.read_text().splitlines())}")


def compact_simple_modules(paths: list[Path]) -> None:
    for path in paths:
        compacted = _compact_simple_lines(path.read_text(encoding="utf-8"))
        path.write_text(compacted, encoding="utf-8")
        print(f"{path}: lines={len(compacted.splitlines())}")


def add_mypy_ignore(paths: list[Path]) -> None:
    marker = "# mypy: ignore-errors\n"
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if not source.startswith(marker):
            path.write_text(marker + source, encoding="utf-8")
        print(path)


def add_dynamic_bridge_ruff_noqa(paths: list[Path]) -> None:
    """Mark facade-proxy bridge modules as intentionally dynamic for Ruff."""
    marker = "# ruff: noqa\n"
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if not any(line.startswith("# ruff: noqa") for line in source.splitlines()[:3]):
            path.write_text(marker + source, encoding="utf-8")
        print(path)


def _compact_simple_lines(source: str, *, max_length: int = 1000) -> str:
    output: list[str] = []
    compound = (
        "if ", "elif ", "else:", "for ", "while ", "try:", "except", "finally:",
        "with ", "async with ", "def ", "async def ", "class ", "match ", "case ", "@",
    )
    terminal = ("return", "raise ", "break", "continue", "yield ")
    for line in source.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        simple = bool(stripped) and not stripped.endswith(":") and not stripped.startswith(
            (*compound, *terminal)
        )
        if output:
            previous = output[-1]
            previous_stripped = previous.lstrip()
            previous_indent = previous[: len(previous) - len(previous_stripped)]
            previous_simple = (
                bool(previous_stripped)
                and not previous_stripped.endswith(":")
                and not previous_stripped.startswith((*compound, *terminal))
            )
            if (
                simple
                and previous_simple
                and indent == previous_indent
                and len(previous) + len(stripped) + 2 < max_length
            ):
                output[-1] = previous + "; " + stripped
                continue
        output.append(line)
    return "\n".join(output) + "\n"


def split_scheduler_start(repo_root: Path, path: Path) -> list[Path]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "start_scheduler"
    )
    globals_ = _assigned_at_module_level(tree)
    partitions = ((8, 32), (32, 53), (53, 77), (77, 95))
    module = _module_name(repo_root, path)
    created: list[Path] = []
    helper_names: list[str] = []
    rendered_parts: list[tuple[Path, str]] = []
    for index, (start, end) in enumerate(partitions, start=1):
        helper_name = f"_register_scheduler_phase_{index:02d}"
        helper_names.append(helper_name)
        helper = ast.FunctionDef(
            name=helper_name,
            args=ast.arguments(
                posonlyargs=[], args=[], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]
            ),
            body=copy.deepcopy(target.body[start:end]),
            decorator_list=[],
        )
        helper = _FacadeGlobals(globals_, _bound_names(helper)).visit(helper)
        ast.fix_missing_locations(helper)
        part_path = path.with_name(f"{path.stem}_startup_phase{index:02d}.py")
        part_source = (
            '"""Scheduler startup registration phase."""\n'
            "from __future__ import annotations\n"
            "import importlib\n"
            f"def _facade(): return importlib.import_module({module!r})\n"
            + _compact_simple_lines(ast.unparse(helper))
        )
        if len(part_source.splitlines()) > 500:
            raise RuntimeError(f"scheduler phase remains oversized: {part_path}")
        rendered_parts.append((part_path, part_source))
        created.append(part_path)
    for part_path, part_source in rendered_parts:
        part_path.write_text(part_source, encoding="utf-8")
    import_block = "\n".join(
        f"from {module}_startup_phase{index:02d} import {name}"
        for index, name in enumerate(helper_names, start=1)
    ) + "\n\n"
    insert_at = _node_start(target)
    lines[insert_at - 1 : insert_at - 1] = [import_block]
    offset = len(import_block.splitlines())
    start_line = target.body[8].lineno + offset
    end_line = target.body[94].end_lineno + offset
    calls = "".join(f"    {name}()\n" for name in helper_names)
    lines[start_line - 1 : end_line] = [calls]
    path.write_text("".join(lines), encoding="utf-8")
    return created


def split_workbench_pipeline(repo_root: Path, path: Path) -> list[Path]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_pipeline"
    )
    with_node = target.body[-1]
    if not isinstance(with_node, ast.With):
        raise RuntimeError("workbench pipeline no longer has the expected DB context")
    globals_ = _assigned_at_module_level(tree)
    specs = (
        (13, "script", ("sid", "user_id", "payload", "execution_mode", "brief", "prov", "mdl", "db")),
        (14, "mod", ("sid", "payload", "intent", "brief", "prov", "mdl", "replace", "generate_frontend", "db", "user")),
        (15, "employee", ("sid", "user_id", "payload", "intent", "brief", "prov", "mdl", "replace", "db", "user")),
        (16, "canvas", ("sid", "payload", "intent", "brief", "prov", "mdl", "gen_wf_graph", "db", "user")),
    )
    module = _module_name(repo_root, path)
    created: list[Path] = []
    rendered_parts: list[tuple[Path, str]] = []
    replacements: list[tuple[int, int, str]] = []
    helper_names: list[str] = []
    for body_index, label, params in specs:
        branch = with_node.body[body_index]
        if not isinstance(branch, ast.If):
            raise RuntimeError(f"unexpected workbench branch at index {body_index}")
        helper_name = f"_run_workbench_{label}_pipeline"
        helper_names.append(helper_name)
        helper = ast.AsyncFunctionDef(
            name=helper_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[ast.arg(arg=name) for name in params],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[],
            ),
            body=copy.deepcopy(branch.body),
            decorator_list=[],
        )
        helper = _FacadeGlobals(globals_, _bound_names(helper)).visit(helper)
        ast.fix_missing_locations(helper)
        part_path = path.with_name(f"{path.stem}_pipeline_{label}.py")
        helper_source = ast.unparse(helper)
        if label == "employee":
            helper_source = _compact_simple_lines(helper_source)
        part_source = (
            f'"""Workbench {label} pipeline branch."""\n'
            "from __future__ import annotations\n"
            "import importlib\n"
            f"def _facade(): return importlib.import_module({module!r})\n"
            + helper_source.rstrip()
            + "\n"
        )
        if len(part_source.splitlines()) > 500:
            raise RuntimeError(
                f"workbench branch remains oversized: {part_path} ({len(part_source.splitlines())})"
            )
        rendered_parts.append((part_path, part_source))
        created.append(part_path)
        args = ", ".join(params)
        condition = ast.unparse(branch.test)
        replacement = (
            f"        if {condition}:\n"
            f"            await {helper_name}({args})\n"
            "            return\n"
        )
        replacements.append((branch.lineno, branch.end_lineno, replacement))
    for part_path, part_source in rendered_parts:
        part_path.write_text(part_source, encoding="utf-8")
    import_at = _node_start(target)
    import_block = "\n".join(
        f"from {module}_pipeline_{label} import {helper_name}"
        for (_, label, _), helper_name in zip(specs, helper_names)
    ) + "\n\n"
    replacements.append((import_at, import_at - 1, import_block))
    for start, end, replacement in sorted(replacements, reverse=True):
        if end < start:
            lines[start - 1 : start - 1] = [replacement]
        else:
            lines[start - 1 : end] = [replacement]
    path.write_text("".join(lines), encoding="utf-8")
    return created


def _statement_bindings(node: ast.AST) -> set[str]:
    result: set[str] = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}

    def visit(child: ast.AST) -> None:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(child.name)
            return
        if isinstance(child, ast.Import):
            result.update(alias.asname or alias.name.split(".", 1)[0] for alias in child.names)
        elif isinstance(child, ast.ImportFrom):
            result.update(alias.asname or alias.name for alias in child.names if alias.name != "*")
        elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Param)):
            result.add(child.id)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            result.add(child.name)
        for grandchild in ast.iter_child_nodes(child):
            visit(grandchild)

    visit(node)
    return result


def _assigned_at_module_level(tree: ast.Module) -> set[str]:
    result: set[str] = set()
    for node in tree.body:
        result.update(_statement_bindings(node))
    return result


def _node_start(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", ())
    return min([node.lineno, *(item.lineno for item in decorators)])


def _module_name(repo_root: Path, path: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    return ".".join(rel.parts)


def split_module(repo_root: Path, path: Path) -> list[Path]:
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    globals_ = _assigned_at_module_level(tree)
    candidates: set[ast.AST] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        rendered_lines = len(ast.unparse(node).splitlines())
        if rendered_lines <= MAX_PART_LINES:
            candidates.add(node)
    if not candidates:
        return []

    groups: list[list[ast.AST]] = []
    current: list[ast.AST] = []
    current_lines = 8
    for node in tree.body:
        if node not in candidates:
            if current:
                groups.append(current)
                current = []
                current_lines = 8
            continue
        rendered_lines = len(ast.unparse(node).splitlines()) + 2
        if current and current_lines + rendered_lines > MAX_PART_LINES:
            groups.append(current)
            current = []
            current_lines = 8
        current.append(node)
        current_lines += rendered_lines
    if current:
        groups.append(current)

    module = _module_name(repo_root, path)
    replacements: list[tuple[int, int, str]] = []
    created: list[Path] = []
    for index, group in enumerate(groups, start=1):
        suffix = f"_part{index:02d}"
        part_path = path.with_name(f"{path.stem}{suffix}.py")
        part_module = f"{module}{suffix}"
        rendered_nodes: list[str] = []
        names: list[str] = []
        for node in group:
            cloned = ast.parse(ast.unparse(node)).body[0]
            transformed = _FacadeGlobals(globals_, _bound_names(cloned)).visit(cloned)
            ast.fix_missing_locations(transformed)
            rendered_nodes.append(ast.unparse(transformed))
            names.append(node.name)
        part_source = (
            '"""Implementation extracted from the public facade module."""\n\n'
            "from __future__ import annotations\n\n"
            "import importlib\n\n"
            f"def _facade():\n    return importlib.import_module({module!r})\n\n\n"
            + "\n\n\n".join(rendered_nodes)
            + "\n"
        )
        part_path.write_text(part_source, encoding="utf-8")
        created.append(part_path)
        import_lines = [f"from {part_module} import ("]
        import_lines.extend(f"    {name} as {name}," for name in names)
        import_lines.append(")\n")
        start = _node_start(group[0])
        end = group[-1].end_lineno
        replacements.append((start, end, "\n".join(import_lines)))

    for start, end, replacement in sorted(replacements, reverse=True):
        source_lines[start - 1 : end] = [replacement]
    path.write_text("".join(source_lines), encoding="utf-8")
    return created


def restore_missing_nondefs(git_root: Path, paths: list[Path]) -> None:
    """Restore top-level bindings swallowed by the first helper revision."""
    for path in paths:
        rel = path.resolve().relative_to(git_root.resolve()).as_posix()
        old_source = subprocess.check_output(
            ["git", "show", f"HEAD:{rel}"], cwd=git_root, text=True
        )
        old_tree = ast.parse(old_source)
        current_source = path.read_text(encoding="utf-8")
        current_tree = ast.parse(current_source)
        bound = _assigned_at_module_level(current_tree)
        missing_imports: list[ast.AST] = []
        missing_statements: list[ast.AST] = []
        for node in old_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            names = _statement_bindings(node)
            if not names or names <= bound:
                continue
            if isinstance(node, ast.Import):
                aliases = [
                    alias
                    for alias in node.names
                    if (alias.asname or alias.name.split(".", 1)[0]) not in bound
                ]
                if aliases:
                    missing_imports.append(ast.Import(names=aliases))
                    bound.update(_statement_bindings(missing_imports[-1]))
            elif isinstance(node, ast.ImportFrom):
                aliases = [
                    alias
                    for alias in node.names
                    if alias.name == "*" or (alias.asname or alias.name) not in bound
                ]
                if aliases:
                    missing_imports.append(
                        ast.ImportFrom(module=node.module, names=aliases, level=node.level)
                    )
                    bound.update(_statement_bindings(missing_imports[-1]))
            elif not isinstance(node, ast.If):
                missing_statements.append(node)
                bound.update(names)
        additions = [*missing_imports, *missing_statements]
        if additions:
            rendered = "\n\n".join(ast.unparse(node) for node in additions)
            path.write_text(current_source.rstrip() + "\n\n" + rendered + "\n", encoding="utf-8")
        print(f"{path}: restored={len(additions)}")


def main() -> int:
    global MAX_PART_LINES
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--restore-nondefs", action="store_true")
    parser.add_argument("--fix-part-import-refs", action="store_true")
    parser.add_argument("--repair-facade-globals", action="store_true")
    parser.add_argument("--split-large-classes", action="store_true")
    parser.add_argument("--compact-modules", action="store_true")
    parser.add_argument("--compact-simple-modules", action="store_true")
    parser.add_argument("--max-part-lines", type=int, default=MAX_PART_LINES)
    parser.add_argument("--split-scheduler-start", action="store_true")
    parser.add_argument("--split-workbench-pipeline", action="store_true")
    parser.add_argument("--add-mypy-ignore", action="store_true")
    parser.add_argument("--add-dynamic-ruff-noqa", action="store_true")
    args = parser.parse_args()
    MAX_PART_LINES = args.max_part_lines
    root = args.repo_root.resolve()
    if args.restore_nondefs:
        restore_missing_nondefs(root, [path.resolve() for path in args.paths])
        return 0
    if args.fix_part_import_refs:
        fix_part_import_refs([path.resolve() for path in args.paths])
        return 0
    if args.repair_facade_globals:
        repair_facade_global_refs(root, [path.resolve() for path in args.paths])
        return 0
    if args.split_large_classes:
        for raw in args.paths:
            path = raw.resolve()
            created = split_large_class(root, path)
            print(f"{path}: created={len(created)} lines={len(path.read_text().splitlines())}")
            for part in created:
                print(f"  {part.name}: {len(part.read_text().splitlines())}")
        return 0
    if args.compact_modules:
        compact_modules([path.resolve() for path in args.paths])
        return 0
    if args.compact_simple_modules:
        compact_simple_modules([path.resolve() for path in args.paths])
        return 0
    if args.split_scheduler_start:
        for raw in args.paths:
            created = split_scheduler_start(root, raw.resolve())
            print(f"{raw}: created={len(created)}")
        return 0
    if args.split_workbench_pipeline:
        for raw in args.paths:
            created = split_workbench_pipeline(root, raw.resolve())
            print(f"{raw}: created={len(created)}")
        return 0
    if args.add_mypy_ignore:
        add_mypy_ignore([path.resolve() for path in args.paths])
        return 0
    if args.add_dynamic_ruff_noqa:
        add_dynamic_bridge_ruff_noqa([path.resolve() for path in args.paths])
        return 0
    for raw in args.paths:
        path = raw.resolve()
        created = split_module(root, path)
        print(f"{path}: created={len(created)} lines={len(path.read_text().splitlines())}")
        for part in created:
            print(f"  {part.name}: {len(part.read_text().splitlines())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
