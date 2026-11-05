"""Static architecture metrics for arch_fitness: import graph, cycles, layering, API surface.

Everything is computed from the AST so the gate never imports application code. Edges include
string-literal ``importlib.import_module("pkg.mod")`` / ``sys.modules["pkg.mod"]`` lookups, which
otherwise hide runtime back-references from every static tool.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_FRAGMENT_NAME = re.compile(
    r"(_part\d+|_phase\d+|mixin\d+|_merged(_|$)|_mod\d+(_|$)|_r\d+$|__\w+mixin)", re.IGNORECASE
)


@dataclass
class Module:
    name: str
    path: Path
    tree: ast.Module | None
    source: str
    is_package: bool


@dataclass
class Graph:
    package: str
    modules: dict[str, Module] = field(default_factory=dict)
    import_time: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    all_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def fan_out(self, mod: str) -> int:
        return len(self.all_edges.get(mod, ()))

    def fan_in(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for targets in self.all_edges.values():
            for target in targets:
                counts[target] += 1
        return counts


def load_graph(root: Path, package: str, *, skip: tuple[str, ...] = ()) -> Graph:
    graph = Graph(package)
    for path in sorted((root / package).rglob("*.py")):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or any(part in skip for part in rel.parts):
            continue
        parts = list(rel.with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree: ast.Module | None = ast.parse(source)
        except SyntaxError:
            tree = None
        graph.modules[".".join(parts)] = Module(".".join(parts), path, tree, source, is_package)
    for mod in graph.modules.values():
        if mod.tree is not None:
            _collect_edges(graph, mod)
    return graph


def _resolve(graph: Graph, dotted: str) -> str | None:
    while dotted and dotted not in graph.modules:
        dotted = dotted.rpartition(".")[0]
    return dotted or None


def _absolute(mod: Module, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    base = mod.name.split(".") if mod.is_package else mod.name.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


class _EdgeVisitor(ast.NodeVisitor):
    def __init__(self, graph: Graph, mod: Module) -> None:
        self.graph, self.mod = graph, mod
        self.deferred = 0

    def _add(self, dotted: str) -> None:
        if not dotted.startswith(self.graph.package):
            return
        target = _resolve(self.graph, dotted)
        if not target or target == self.mod.name:
            return
        self.graph.all_edges[self.mod.name].add(target)
        if not self.deferred:
            self.graph.import_time[self.mod.name].add(target)

    def _scoped(self, node: ast.AST) -> None:
        self.deferred += 1
        self.generic_visit(node)
        self.deferred -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _scoped

    def visit_If(self, node: ast.If) -> None:
        if "TYPE_CHECKING" in ast.unparse(node.test):
            self._scoped(node)
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = _absolute(self.mod, node)
        for alias in node.names:
            dotted = f"{base}.{alias.name}"
            self._add(dotted if dotted in self.graph.modules else base)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in {"import_module", "__import__"} and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self._add(arg.value)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if ast.unparse(node.value) == "sys.modules" and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                self._add(node.slice.value)
        self.generic_visit(node)


def _collect_edges(graph: Graph, mod: Module) -> None:
    assert mod.tree is not None
    _EdgeVisitor(graph, mod).visit(mod.tree)


def strongly_connected(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan; returns components with more than one module."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for start in nodes:
        if start in index:
            continue
        work = [(start, iter(sorted(edges.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
    return result


def cycle_edges(graph: Graph, edges: dict[str, set[str]]) -> list[tuple[str, str]]:
    out = []
    for comp in strongly_connected(sorted(graph.modules), edges):
        members = set(comp)
        out.extend((src, dst) for src in comp for dst in sorted(edges.get(src, ())) if dst in members)
    return out


def public_api_count(mod: Module) -> int:
    """``__all__`` when declared, otherwise public defs/assignments plus explicit ``x as x`` re-exports."""
    if mod.tree is None:
        return 0
    names: set[str] = set()
    for node in mod.tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return len(node.value.elts)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(t.id for t in targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.asname for a in node.names if a.asname and a.asname == a.name)
    return sum(1 for n in names if not n.startswith("_"))


def is_fragment_name(path: Path) -> bool:
    return bool(_FRAGMENT_NAME.search(path.stem))


def defines_facade_hook(mod: Module) -> bool:
    if mod.tree is None:
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name == "_facade" for n in mod.tree.body)


_MYPY_FILE_DISABLE = re.compile(r"^#\s*mypy:\s*(disable-error-code|ignore-errors)", re.MULTILINE)


def mypy_file_disables(mod: Module) -> int:
    return len(_MYPY_FILE_DISABLE.findall(mod.source[:2000]))


def _is_stub(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any("abstractmethod" in ast.unparse(d) for d in fn.decorator_list):
        return True
    for stmt in fn.body:
        if isinstance(stmt, ast.Pass) or (
            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        ):
            continue
        if isinstance(stmt, ast.Raise) and "NotImplementedError" in ast.unparse(stmt):
            continue
        return False
    return True


def _class_index(graph: Graph) -> dict[tuple[str, str], tuple[list[ast.expr], set[str]]]:
    index = {}
    for mod in graph.modules.values():
        if mod.tree is None:
            continue
        for node in mod.tree.body:
            if isinstance(node, ast.ClassDef):
                is_protocol = any("Protocol" in ast.unparse(b) for b in node.bases)
                methods = {
                    n.name
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not (n.name.startswith("__") and n.name.endswith("__"))
                    and not is_protocol
                    and not _is_stub(n)
                }
                index[(mod.name, node.name)] = (node.bases, methods)
    return index


def _import_table(mod: Module, graph: Graph) -> dict[str, tuple[str, str]]:
    table: dict[str, tuple[str, str]] = {}
    if mod.tree is None:
        return table
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.ImportFrom):
            base = _absolute(mod, node)
            for alias in node.names:
                table[alias.asname or alias.name] = (base, alias.name)
    return table


def mixin_collisions(graph: Graph) -> list[tuple[str, str, str]]:
    """Classes whose sibling bases contribute the same method name from different origins."""
    classes = _class_index(graph)
    tables: dict[str, dict[str, tuple[str, str]]] = {}

    def resolve_base(mod_name: str, expr: ast.expr, depth: int = 0) -> tuple[str, str] | None:
        if not isinstance(expr, ast.Name) or depth > 4:
            return None
        if (mod_name, expr.id) in classes:
            return (mod_name, expr.id)
        mod = graph.modules.get(mod_name)
        if mod is None:
            return None
        table = tables.setdefault(mod_name, _import_table(mod, graph))
        if expr.id not in table:
            return None
        src_mod, src_name = table[expr.id]
        if (src_mod, src_name) in classes:
            return (src_mod, src_name)
        if src_mod in graph.modules:
            return resolve_base(src_mod, ast.Name(id=src_name), depth + 1)
        return None

    origins_cache: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}

    def origins(key: tuple[str, str], seen: frozenset = frozenset()) -> dict[str, tuple[str, str]]:
        if key in origins_cache:
            return origins_cache[key]
        if key in seen:
            return {}
        bases, methods = classes[key]
        result: dict[str, tuple[str, str]] = {}
        for base in reversed(bases):
            resolved = resolve_base(key[0], base)
            if resolved:
                result.update(origins(resolved, seen | {key}))
        result.update({m: key for m in methods})
        origins_cache[key] = result
        return result

    found = []
    for key, (bases, methods) in classes.items():
        resolved = [r for b in bases if (r := resolve_base(key[0], b))]
        if len(resolved) < 2:
            continue
        owner: dict[str, tuple[str, str]] = {}
        for base in resolved:
            for method, origin in origins(base).items():
                if method in methods:
                    continue
                if method in owner and owner[method] != origin:
                    found.append((key[0], key[1], method))
                owner.setdefault(method, origin)
    return sorted(set(found))


def layer_of(module: str, layers: dict[str, str]) -> str | None:
    for prefix, layer in layers.items():
        if module == prefix or module.startswith(prefix + "."):
            return layer
    return None


def cross_layer_edges(
    graph: Graph, layers: dict[str, str], forbidden: dict[str, tuple[str, ...]],
    allowed_targets: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    out = []
    for src, targets in graph.all_edges.items():
        src_layer = layer_of(src, layers)
        if src_layer is None:
            continue
        for dst in targets:
            if any(dst == a or dst.startswith(a + ".") for a in allowed_targets):
                continue
            if layer_of(dst, layers) in forbidden.get(src_layer, ()):
                out.append((src, dst))
    return sorted(out)


if __name__ == "__main__":
    root, package = Path(sys.argv[1]), sys.argv[2]
    g = load_graph(root, package)
    comps = strongly_connected(sorted(g.modules), g.all_edges)
    print(f"{package}: {len(g.modules)} modules; import-time cycle edges "
          f"{len(cycle_edges(g, g.import_time))}; deferred SCC sizes "
          f"{sorted((len(c) for c in comps), reverse=True)[:5]}")
