"""AST-level validation for patched Python source."""

from __future__ import annotations

import ast

from .._internals.code_models import CodeFunctionSignature, CodeValidationResult

FORBIDDEN_BUILTINS = frozenset({
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "breakpoint",
})

ALLOWED_IMPORT_MODULES = frozenset({
    # core data / text
    "json",
    "re",
    "math",
    "string",
    "textwrap",
    "unicodedata",
    "pprint",
    # date / time / timing
    "datetime",
    "time",           # time.time / time.sleep / time.monotonic — no FS/net
    # concurrency primitives (Lock, RLock, Event, local — no raw OS threads needed)
    "threading",
    # data structures / algorithms
    "collections",
    "itertools",
    "functools",
    "heapq",
    "bisect",
    "operator",
    # typing / dataclasses / copy
    "typing",
    "dataclasses",
    "copy",
    # numeric / statistics
    "statistics",
    "decimal",
    "fractions",
    "random",
    # enums / io / context
    "enum",
    "io",
    "contextlib",     # contextmanager, suppress, nullcontext
    # abstract base classes / type utilities
    "abc",
    "numbers",
    "types",
    # path string manipulation only (PurePath / PurePosixPath)
    # actual FS access still blocked by FORBIDDEN_BUILTINS (open) and sandbox
    "pathlib",
    # binary / struct
    "struct",
    # encoding / hashing (read-only, no FS/net access)
    "base64",
    "hashlib",
    "uuid",
    # logging (writes to stderr/handler only, no FS writes in sandbox)
    "logging",
    # warnings suppression
    "warnings",
})

# Safe methods on dict/list/str/tuple/set or generic objects in typical skill code
_SAFE_ATTR_METHODS = frozenset({
    # --- dict ---
    "get",
    "setdefault",
    "keys",
    "values",
    "items",
    "update",
    "pop",
    "popitem",
    "clear",
    "copy",
    # --- list ---
    "append",
    "extend",
    "insert",
    "remove",
    "sort",
    "reverse",
    # --- set ---
    "add",
    "discard",
    "difference",
    "difference_update",
    "intersection",
    "intersection_update",
    "union",
    "issubset",
    "issuperset",
    "symmetric_difference",
    # --- str ---
    "strip",
    "lstrip",
    "rstrip",
    "split",
    "rsplit",
    "splitlines",
    "join",
    "lower",
    "upper",
    "title",
    "capitalize",
    "replace",
    "startswith",
    "endswith",
    "find",
    "rfind",
    "format",
    "format_map",
    "encode",
    "zfill",
    "ljust",
    "rjust",
    "center",
    "count",
    "index",
    "rindex",
    "isdigit",
    "isalpha",
    "isalnum",
    "isspace",
    "isnumeric",
    # --- logging / logger instances (.info / .debug / .warning / .error / .critical) ---
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    "log",
    # --- misc helpers (collections, itertools objects, etc.) ---
    "most_common",
    "elements",
    "total",
    "hex",
    "digest",
    "hexdigest",
})

MAX_CODE_LINES = 300


class CodeValidator:
    """AST safety checks for user-supplied Python."""

    def __init__(
        self,
        *,
        allowed_imports: frozenset[str] | None = None,
        max_lines: int = MAX_CODE_LINES,
    ):
        self._allowed_imports = allowed_imports or ALLOWED_IMPORT_MODULES
        self._max_lines = max_lines

    def validate(
        self,
        source_code: str,
        *,
        function_name: str,
        signature: CodeFunctionSignature,
        dependencies: list[str] | None = None,
    ) -> CodeValidationResult:
        issues: list[str] = []
        deps = set(dependencies or [])
        allowed_mods = frozenset(self._allowed_imports & deps) if deps else self._allowed_imports

        lines = source_code.count("\n") + 1 if source_code.strip() else 0
        if lines > self._max_lines:
            issues.append(f"code_too_long:{lines}>{self._max_lines}")

        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            return CodeValidationResult(safe=False, issues=[f"syntax_error:{exc}"])

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                ok = self._check_import(node, allowed_mods)
                if not ok:
                    issues.append(f"disallowed_import:{ast.dump(node, include_attributes=False)}")
            elif isinstance(node, ast.Global):
                issues.append("forbidden_global")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in FORBIDDEN_BUILTINS:
                        issues.append(f"forbidden_builtin:{node.func.id}")
                elif isinstance(node.func, ast.Attribute) and not self._allowed_attribute_call(
                    node.func, allowed_mods
                ):
                    issues.append(
                        f"disallowed_attribute_call:{ast.dump(node.func, include_attributes=False)}"
                    )

        sig_issues = self._check_signature(tree, function_name, signature)
        issues.extend(sig_issues)

        return CodeValidationResult(safe=not issues, issues=issues)

    def _allowed_attribute_call(self, node: ast.Attribute, allowed_mods: frozenset[str]) -> bool:
        if node.attr in _SAFE_ATTR_METHODS:
            return True
        root = self._attribute_root_name(node)
        return bool(root and root in allowed_mods)

    def _attribute_root_name(self, node: ast.Attribute | ast.Name) -> str | None:
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            cur = cur.value
        if isinstance(cur, ast.Name):
            return cur.id
        return None

    def _check_import(self, node: ast.Import | ast.ImportFrom, allowed_mods: frozenset[str]) -> bool:
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = (alias.name or "").split(".")[0]
                if base not in allowed_mods:
                    return False
            return True
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            base = mod.split(".")[0] if mod else ""
            if node.level and node.level > 0:
                return False
            return not (base and base not in allowed_mods)
        return False

    def _check_signature(
        self,
        tree: ast.AST,
        function_name: str,
        signature: CodeFunctionSignature,
    ) -> list[str]:
        issues: list[str] = []
        func_def: ast.FunctionDef | None = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                func_def = node
                break
        if func_def is None:
            issues.append(f"missing_function:{function_name}")
            return issues

        if not (func_def.body and isinstance(func_def.body[0], ast.Expr) and isinstance(func_def.body[0].value, ast.Constant) and isinstance(func_def.body[0].value.value, str)):
            issues.append("missing_docstring")

        args = func_def.args
        posonly = [a.arg for a in args.posonlyargs]
        pos = [a.arg for a in args.args]
        kwonly = [a.arg for a in args.kwonlyargs]
        all_pos_names = posonly + pos
        declared = set(all_pos_names) | set(kwonly)
        for req in signature.required_params:
            if req not in declared:
                issues.append(f"missing_param:{req}")
        for name in signature.params:
            if name not in declared:
                issues.append(f"signature_mismatch_param:{name}")
        return issues
